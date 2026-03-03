import os
import time
import json
import requests
from requests_oauthlib import OAuth1

X_CREATE_TWEET = "https://api.x.com/2/tweets"  # Create Post endpoint: POST /2/tweets

def create_tweet(auth: OAuth1, text: str, reply_to_id: str | None = None) -> str:
    payload = {"text": text}
    if reply_to_id:
        payload["reply"] = {"in_reply_to_tweet_id": reply_to_id}

    r = requests.post(X_CREATE_TWEET, auth=auth, json=payload, timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"X API error {r.status_code}: {r.text}")

    return r.json()["data"]["id"]

def build_thread() -> list[str]:
    # Round 1 = stable template. Later we swap in “odds → 1 pick”.
    return [
        "🧪 BET LAB BETS — Daily Board\n1 official play. Tracked. No fluff.",
        "Rules:\n• 1 play/day\n• 1u flat\n• Best line or no bet\n• No chasing",
        "Record: 0–0 | +0.00u | ROI 0.0%\n(Tracking begins today.)",
        "✅ OFFICIAL: [AUTO PICK PLACEHOLDER]\nOdds: [ODDS]\n1.0u\nPlay only if price holds.",
        "Why:\n• Market/price note\n• Quick matchup note\n(No guarantees.)",
        "🚫 Pass list:\nEverything else until the number is right.",
        "👀 Watchlist:\nIf line improves, it’s noted. Otherwise, no action.",
        "Risk plan: max 1.0u today.\nIf it loses, we move on.",
        "Recap tonight + record update.\nWin or lose, it gets logged.",
        "Follow + turn on notifications if you want the daily board.\n21+ | Entertainment only."
    ]

def main():
    consumer_key = os.environ["X_CONSUMER_KEY"]
    consumer_secret = os.environ["X_CONSUMER_SECRET"]
    access_token = os.environ["X_ACCESS_TOKEN"]
    access_secret = os.environ["X_ACCESS_TOKEN_SECRET"]

    auth = OAuth1(consumer_key, consumer_secret, access_token, access_secret)

    tweets = build_thread()
    if not (8 <= len(tweets) <= 12):
        raise ValueError("Thread must be 8–12 tweets.")
    for t in tweets:
        if len(t) > 260:
            raise ValueError(f"Tweet too long ({len(t)} chars): {t}")

    first_id = None
    prev_id = None
    posted_ids = []

    for i, text in enumerate(tweets):
        tweet_id = create_tweet(auth, text, reply_to_id=prev_id)
        posted_ids.append(tweet_id)
        if i == 0:
            first_id = tweet_id
        prev_id = tweet_id
        time.sleep(1.2)

    print(json.dumps({"first_tweet_id": first_id, "tweet_ids": posted_ids, "tweet_count": len(tweets)}))

if __name__ == "__main__":
    main()
