print("SCRIPT STARTED")

import os
import time
import json
import requests
from datetime import datetime, timezone, timedelta
from requests_oauthlib import OAuth1

import random
import hashlib

AIRTABLE_TOKEN = os.environ.get("AIRTABLE_TOKEN", "")
AIRTABLE_BASE_ID = os.environ.get("AIRTABLE_BASE_ID", "")
AIRTABLE_RUNS_TABLE = os.environ.get("AIRTABLE_RUNS_TABLE", "runs")

HOOKS = [
    "Alright fellas, one clean one today. Not forcing it.",
    "Boys. Quick card. One play. In and out.",
    "I’m not doing the 6-play circus today. One spot I actually like.",
    "Daily board: one official. If you’re itching, go lift.",
    "One play today. If the number moves, we don’t chase. Simple.",
    "I’m keeping it boring today — boring is how you keep units.",
    "We’re not donating today. One play at the right number.",
    "Short and sweet: one official. Everything else is noise.",
    "If you missed yesterday, don’t chase today. Here’s the play.",
    "One play. One unit. Same rules. Let’s work.",
]

WHY_LINES = [
    "This is a price play. I’m taking the number, not writing fan fiction.",
    "I’ll take it at this price. If it’s worse, I’m out. No ego.",
    "This one’s clean: liquid market, fair entry, no weird stuff.",
    "I’m not married to the side — I’m married to the price.",
    "Nothing heroic. Just the best number I found with legit books.",
    "It’s the kind of bet you forget about… which is usually a good sign.",
]

PASS_LINES = [
    "Pass list: literally everything else unless the line gifts us something.",
    "No extra plays. I’m not turning this into a donation drive.",
    "If you want action, play Madden. I’m passing on the rest.",
    "I’m not sprinkling today. One bet and I’m done.",
    "Everything else is a watch, not a play.",
]

RECAP_LINES = [
    "I’ll post the result tonight. Win or lose, it’s getting logged.",
    "Recap later. No deleting. No hiding.",
    "We’ll check back after it settles and update the record.",
    "Result later. Same energy either way.",
]

CTA_LINES = [
    "If you want these daily: follow + turn on notis. That’s it.",
    "Tailing? Line shop. Flat stake. Don’t be a hero.",
    "Follow if you’re building a bankroll, not chasing dopamine.",
    "Notis on if you want the play when it drops.",
]

def seeded_pick(options, seed_str):
    seed = int(hashlib.sha256(seed_str.encode()).hexdigest(), 16) % (10**8)
    rnd = random.Random(seed)
    return rnd.choice(options)

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

    # NEW: scan upcoming games until we find one with whitelisted books + valid markets
    for _, event in upcoming:
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
            if o["market"] == "spreads" and in_price_band(o["price"]) and o["point"] is not None
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
            if o["market"] == "totals" and in_price_band(o["price"]) and o["point"] is not None
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

    # none of the upcoming games had whitelisted markets in band
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
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    nonce = hashlib.sha256(f"{stamp}{play.get('event','')}{time.time()}".encode()).hexdigest()[:6]
    seed = f"{stamp}|{play.get('event','')}|{play.get('market','')}"
    hook = seeded_pick(HOOKS, seed + "|hook")
    why = seeded_pick(WHY_LINES, seed + "|why")
    passed = seeded_pick(PASS_LINES, seed + "|pass")
    recap = seeded_pick(RECAP_LINES, seed + "|recap")
    cta = seeded_pick(CTA_LINES, seed + "|cta")
    odds = play.get("odds", "")
    odds_str = f" ({odds})" if odds not in ("", None) else ""

    pick_line = f"✅ OFFICIAL ({league}): {play.get('pick','')}{odds_str} — 1.0u"
    meta_line = f"{play.get('event','')} | Book: {play.get('book','')}"

    return [
     f"🧪 BET LAB BETS — Daily Board | {stamp} #{nonce}\n{hook}",
    "Rules:\n• 1 play/day\n• 1u flat\n• Best line or no bet\n• No chasing",
    "Record: 0–0 | +0.00u | ROI 0.0%\n(Tracking begins today.)",
    pick_line,
    meta_line,
    f"Price rule: {play.get('price_rule','')}",
    why,
    passed,
    recap,
    f"{cta}\n21+ | Entertainment only.",
]

def airtable_headers():
    
def runs_table_id():
    return os.environ.get("AIRTABLE_RUNS_TABLE_ID", AIRTABLE_RUNS_TABLE)

def runs_url():
    return f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{runs_table_id()}"

def acquire_daily_lock(date_str: str) -> str | None:
    """
    Returns Airtable record_id if lock acquired, else None (already locked/posted).
    """
    if not AIRTABLE_TOKEN or not AIRTABLE_BASE_ID:
        raise RuntimeError("Airtable not configured; refusing to post to avoid duplicates.")

    params = {
        "maxRecords": 1,
        "filterByFormula": f"AND({{run_date}}='{date_str}', OR({{status}}='locked', {{status}}='posted'))"
    }
    r = requests.get(runs_url(), headers=airtable_headers(), params=params, timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"Airtable check failed {r.status_code}: {r.text}")

    if len(r.json().get("records", [])) > 0:
        return None

    payload = {"fields": {"run_date": date_str, "status": "locked", "error": ""}}
    r = requests.post(runs_url(), headers=airtable_headers(), json=payload, timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"Airtable lock create failed {r.status_code}: {r.text}")

    return r.json()["id"]

def finalize_lock(record_id: str, status: str, note: str = ""):
    payload = {"fields": {"status": status, "error": note}}
    r = requests.patch(f"{runs_url()}/{record_id}", headers=airtable_headers(), json=payload, timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"Airtable lock finalize failed {r.status_code}: {r.text}")
    return {
        "Authorization": f"Bearer {AIRTABLE_TOKEN}",
        "Content-Type": "application/json",
    }

def already_posted_today(date_str: str) -> bool:
    if not AIRTABLE_TOKEN or not AIRTABLE_BASE_ID:
        return False  # if not configured, don't block posting

    runs_table = os.environ.get("AIRTABLE_RUNS_TABLE_ID", AIRTABLE_RUNS_TABLE)

    # filterByFormula checks if a record exists for today's date with status "posted"
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{runs_table}"
    params = {
        "maxRecords": 1,
        "filterByFormula": f"AND({{run_date}}='{date_str}', {{status}}='posted')"
    }
    r = requests.get(url, headers=airtable_headers(), params=params, timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"Airtable check failed {r.status_code}: {r.text}")
    data = r.json()
    return len(data.get("records", [])) > 0

def log_posted(date_str: str, note: str = ""):
    if not AIRTABLE_TOKEN or not AIRTABLE_BASE_ID:
        return

    runs_table = os.environ.get("AIRTABLE_RUNS_TABLE_ID", AIRTABLE_RUNS_TABLE)

    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{runs_table}"
    payload = {
        "fields": {
            "run_date": date_str,
            "status": "posted",
            "error": note,
        }
    }
    r = requests.post(url, headers=airtable_headers(), json=payload, timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"Airtable log failed {r.status_code}: {r.text}")
        
def main():
    print("MAIN STARTED")

    # Kill switch
    if os.environ.get("BOT_ENABLED", "true").lower() != "true":
        print("BOT_DISABLED: exiting.")
        return

    odds_api_key = os.environ.get("ODDS_API_KEY", "")
    if not odds_api_key:
        raise RuntimeError("Missing ODDS_API_KEY secret.")

    consumer_key = os.environ["X_CONSUMER_KEY"]
    consumer_secret = os.environ["X_CONSUMER_SECRET"]
    access_token = os.environ["X_ACCESS_TOKEN"]
    access_secret = os.environ["X_ACCESS_TOKEN_SECRET"]

    auth = OAuth1(consumer_key, consumer_secret, access_token, access_secret)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lock_id = acquire_daily_lock(today)
if not lock_id:
    print("Already posted/locked today. Exiting.")
    return

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

    # Airtable log (NON-FATAL)
    try:
    # POSTING LOOP (your for i, text in enumerate(tweets): ... )
    # After the loop finishes successfully:
    finalize_lock(lock_id, "posted", note=f"first_tweet_id={first_id}")
except Exception as e:
    try:
        finalize_lock(lock_id, "failed", note=str(e))
    except Exception:
        pass
    raise


if __name__ == "__main__":
    main()
