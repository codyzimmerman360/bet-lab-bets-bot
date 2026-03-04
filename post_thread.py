print("SCRIPT STARTED")

import os
import time
import json
import requests
from datetime import datetime, timezone, timedelta
from requests_oauthlib import OAuth1

X_CREATE_TWEET = "https://api.x.com/2/tweets"
ODDS_BASE = "https://api.the-odds-api.com/v4"

SPORT_PRIORITY = [
    "basketball_nba",
    "icehockey_nhl",
    "soccer_epl",
    "soccer_uefa_champs_league",
    "americanfootball_nfl",
]

MARKETS = "h2h,spreads,totals"

BOOK_WHITELIST = {
    "DraftKings",
    "FanDuel",
    "BetMGM",
    "Caesars",
    "PointsBet",
    "ESPN BET",
    "bet365",
    "Hard Rock Bet",
    "Fanatics Sportsbook",
}

def normalize_book(name: str) -> str:
    n = name.strip()
    n = n.replace("Sportsbook", "").strip()
    n = n.replace("Sports Book", "").strip()
    return n
    
def create_tweet(auth: OAuth1, text: str, reply_to_id: str | None = None) -> str:
    payload = {"text": text}
    if reply_to_id:
        payload["reply"] = {"in_reply_to_tweet_id": reply_to_id}

    r = requests.post(X_CREATE_TWEET, auth=auth, json=payload, timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"X API error {r.status_code}: {r.text}")

    return r.json()["data"]["id"]


def _get_json(url, params):
    r = requests.get(url, params=params, timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"Odds API error {r.status_code}: {r.text}")
    return r.json()


def fetch_odds_for_sport(sport_key: str, odds_api_key: str):
    url = f"{ODDS_BASE}/sports/{sport_key}/odds"
    params = {
        "apiKey": odds_api_key,
        "regions": "us",
        "markets": MARKETS,
        "oddsFormat": "american",
        "dateFormat": "iso",
    }
    return _get_json(url, params)


def pick_one_play(events):
    now = datetime.now(timezone.utc)
    min_start = now + timedelta(minutes=60)

    upcoming = []
    for e in events:
        try:
            start = datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00"))
        except Exception:
            continue
        if start >= min_start:
            upcoming.append((start, e))

    if not upcoming:
        return None

    upcoming.sort(key=lambda x: x[0])
    _, event = upcoming[0]

    home = event.get("home_team")
    away = event.get("away_team")

    offers = []
    for bm in event.get("bookmakers", []):
   bname_raw = bm.get("title") or bm.get("key") or "book"
bname = normalize_book(bname_raw)
if bname not in BOOK_WHITELIST:
    continue
        for m in bm.get("markets", []):
            mkey = m.get("key")
            for o in m.get("outcomes", []):
                offers.append(
                    {
                        "book": bname,
                        "market": mkey,
                        "name": o.get("name"),
                        "price": o.get("price"),
                        "point": o.get("point"),
                        "sport": event.get("sport_key"),
                        "event": f"{away} @ {home}",
                    }
                )

    def in_price_band(price):
        return price is not None and (-125 <= price <= 125)

    def better_price(p_new, p_old):
        return p_old is None or p_new > p_old

    # Moneyline (h2h)
    h2h = [o for o in offers if o["market"] == "h2h" and in_price_band(o["price"])]
    if h2h:
        best = None
        for o in h2h:
            if best is None or better_price(o["price"], best["price"]):
                best = o
        return {
            "sport": best["sport"],
            "event": best["event"],
            "market": "moneyline",
            "pick": f"{best['name']} ML",
            "odds": best["price"],
            "book": best["book"],
            "price_rule": f"Play only at {best['price']} or better",
        }

    # Spreads
    spreads = [
        o
        for o in offers
        if o["market"] == "spreads"
        and in_price_band(o["price"])
        and o["point"] is not None
    ]
    if spreads:
        best = None
        for o in spreads:
            if best is None or better_price(o["price"], best["price"]):
                best = o
        sign = "+" if best["point"] > 0 else ""
        return {
            "sport": best["sport"],
            "event": best["event"],
            "market": "spread",
            "pick": f"{best['name']} {sign}{best['point']}",
            "odds": best["price"],
            "book": best["book"],
            "price_rule": f"Play only at {best['price']} or better",
        }

    # Totals
    totals = [
        o
        for o in offers
        if o["market"] == "totals"
        and in_price_band(o["price"])
        and o["point"] is not None
    ]
    if totals:
        best = None
        for o in totals:
            if best is None or better_price(o["price"], best["price"]):
                best = o
        return {
            "sport": best["sport"],
            "event": best["event"],
            "market": "total",
            "pick": f"{best['name']} {best['point']}",
            "odds": best["price"],
            "book": best["book"],
            "price_rule": f"Play only at {best['price']} or better",
        }

    return None


def select_daily_pick(odds_api_key: str):
    for sport in SPORT_PRIORITY:
        events = fetch_odds_for_sport(sport, odds_api_key)
        if events:
            play = pick_one_play(events)
            if play:
                return play
    return None


def build_thread(play: dict) -> list[str]:
    sport_map = {
        "basketball_nba": "NBA",
        "icehockey_nhl": "NHL",
        "soccer_epl": "EPL",
        "soccer_uefa_champs_league": "UCL",
        "americanfootball_nfl": "NFL",
        "none": "NO BET",
    }
    league = sport_map.get(play.get("sport", "unknown"), play.get("sport", "unknown"))

    odds = play.get("odds", "")
    odds_str = f" ({odds})" if odds not in ("", None) else ""

    pick_line = f"✅ OFFICIAL ({league}): {play.get('pick','')}{odds_str} — 1.0u"
    meta_line = f"{play.get('event','')} | Book: {play.get('book','')}"

    return [
        f"🧪 BET LAB BETS — Daily Board\n1 official play. Tracked. {league} today.",
        "Rules:\n• 1 play/day\n• 1u flat\n• Best line or no bet\n• No chasing",
        "Record: 0–0 | +0.00u | ROI 0.0%\n(Tracking begins today.)",
        pick_line,
        meta_line,
        f"Price rule: {play.get('price_rule','')}",
        "Why this made the cut:\n• Liquid market (ML/spread/total)\n• Best price across books\n• No forcing action",
        "🚫 Pass list:\nEverything else until the number is right.",
        "Recap tonight + record update.\nWin or lose, it gets logged.",
        "Follow + turn on notifications if you want the daily board.\n21+ | Entertainment only.",
    ]


def main():
    print("MAIN STARTED")

    odds_api_key = os.environ.get("ODDS_API_KEY", "")
    if not odds_api_key:
        raise RuntimeError("Missing ODDS_API_KEY secret.")

    consumer_key = os.environ["X_CONSUMER_KEY"]
    consumer_secret = os.environ["X_CONSUMER_SECRET"]
    access_token = os.environ["X_ACCESS_TOKEN"]
    access_secret = os.environ["X_ACCESS_TOKEN_SECRET"]

    auth = OAuth1(consumer_key, consumer_secret, access_token, access_secret)

    play = select_daily_pick(odds_api_key)
    if not play:
        play = {
            "sport": "none",
            "event": "No qualifying slate found",
            "market": "none",
            "pick": "NO BET (no price worth taking)",
            "odds": "",
            "book": "",
            "price_rule": "No action unless the number is right",
        }

    tweets = build_thread(play)

    if not (8 <= len(tweets) <= 12):
        raise ValueError("Thread must be 8–12 tweets.")
    for t in tweets:
        if len(t) > 260:
            raise ValueError(f"Tweet too long ({len(t)} chars): {t}")

    print("ABOUT TO POST", len(tweets), "TWEETS")

    first_id = None
    prev_id = None
    posted_ids = []

    for i, text in enumerate(tweets):
        tweet_id = create_tweet(auth, text, reply_to_id=prev_id)
        print("POSTED", i + 1, "ID", tweet_id)
        posted_ids.append(tweet_id)
        if i == 0:
            first_id = tweet_id
        prev_id = tweet_id
        time.sleep(1.2)

    print(json.dumps({"first_tweet_id": first_id, "tweet_ids": posted_ids, "tweet_count": len(tweets)}))


if __name__ == "__main__":
    main()
