"""
Instagram Video Scorer - scraper.py
Fetches last 10 posts from @foodpharmer using Instaloader,
scores them, and updates Google Sheets.
"""

import instaloader
import gspread
import json
import os
import time
import requests
from datetime import datetime, timezone
from google.oauth2.service_account import Credentials
from collections import defaultdict

# ── Config ────────────────────────────────────────────────────────────────────
INSTAGRAM_USERNAME = "foodpharmer"
POSTS_TO_FETCH     = 10
COMMENTS_PER_POST  = 10          # max comments to analyse per post
GEMINI_API_KEY     = os.environ["GEMINI_API_KEY"]
GOOGLE_CREDS_JSON  = os.environ["GOOGLE_CREDS_JSON"]   # full JSON string
SPREADSHEET_ID     = os.environ["SPREADSHEET_ID"]

WEIGHTS = {
    "views":     0.35,
    "likes":     0.25,
    "sentiment": 0.25,
    "comments":  0.15,
}

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# ── Instaloader ───────────────────────────────────────────────────────────────
def fetch_posts():
    """Fetch last N posts from the public profile."""
    L = instaloader.Instaloader(
        download_pictures=False,
        download_videos=False,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=True,
        save_metadata=False,
        quiet=True,
    )

    # Load session from base64-encoded secret
    ig_session = os.environ.get("IG_SESSION")
    if ig_session:
        try:
            import base64, tempfile
            session_bytes = base64.b64decode(ig_session)
            with tempfile.NamedTemporaryFile(delete=False, suffix="-narsicode") as f:
                f.write(session_bytes)
                session_path = f.name
            L.load_session_from_file("narsicode", session_path)
            print("✅ Loaded Instagram session")
        except Exception as e:
            print(f"⚠️  Session load failed, continuing anonymously: {e}")

    profile = instaloader.Profile.from_username(L.context, INSTAGRAM_USERNAME)
    posts   = []

    for post in profile.get_posts():
        if len(posts) >= POSTS_TO_FETCH:
            break

        comments = []
        try:
            comment_start = time.time()
            for comment in post.get_comments():
                if len(comments) >= COMMENTS_PER_POST:
                    break
                if time.time() - comment_start > 20:  # 20 sec max per post
                    print(f"  ⏱️  Comment timeout hit for {post.shortcode}, moving on")
                    break
                comments.append(comment.text)
                time.sleep(0.2)
        except Exception as e:
            print(f"⚠️  Could not fetch comments for post {post.shortcode}: {e}")

        posts.append({
            "shortcode": post.shortcode,
            "url":       f"https://www.instagram.com/p/{post.shortcode}/",
            "caption":   (post.caption or "")[:120],
            "date":      post.date_utc.strftime("%Y-%m-%d"),
            "likes":     post.likes,
            "views":     post.video_view_count if post.is_video else post.likes * 3,
            "comments":  post.comments,
            "raw_comments": comments,
            "is_video":  post.is_video,
        })
        print(f"  ✅ Fetched post {post.shortcode} ({post.date_utc.strftime('%Y-%m-%d')})")
        time.sleep(1.5)   # be polite to Instagram

    return posts


# ── Gemini Sentiment ──────────────────────────────────────────────────────────
def analyse_sentiment(comments: list[str]) -> dict:
    """
    Returns {score: 0-1, positive_themes: [...], negative_themes: [...], summary: str}
    """
    if not comments:
        return {"score": 0.5, "positive_themes": [], "negative_themes": [], "summary": "No comments"}

    joined = "\n".join(f"- {c}" for c in comments[:COMMENTS_PER_POST])
    prompt = f"""
You are analysing Instagram comments for a health & food education creator (@foodpharmer).

Comments:
{joined}

Respond ONLY with a JSON object (no markdown, no explanation):
{{
  "sentiment_score": <float 0.0 to 1.0, where 1.0 is very positive>,
  "positive_themes": [<up to 3 short phrases of what resonated>],
  "negative_themes": [<up to 3 short phrases of concerns or criticism>],
  "summary": "<one sentence summary of audience reaction>"
}}
"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    resp = requests.post(url, json=payload, timeout=30)
    resp.raise_for_status()

    raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    # Strip possible markdown fences
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


# ── Scoring ───────────────────────────────────────────────────────────────────
def normalise(values: list[float]) -> list[float]:
    mn, mx = min(values), max(values)
    if mx == mn:
        return [0.5] * len(values)
    return [(v - mn) / (mx - mn) for v in values]


def compute_scores(posts: list[dict]) -> list[dict]:
    """Add normalised weighted scores to each post."""
    views_n    = normalise([p["views"]    for p in posts])
    likes_n    = normalise([p["likes"]    for p in posts])
    comments_n = normalise([p["comments"] for p in posts])

    for i, post in enumerate(posts):
        sentiment_data = analyse_sentiment(post["raw_comments"])
        post["sentiment"]         = sentiment_data
        post["sentiment_score"]   = sentiment_data["sentiment_score"]

        post["score"] = round((
            WEIGHTS["views"]     * views_n[i]    +
            WEIGHTS["likes"]     * likes_n[i]    +
            WEIGHTS["sentiment"] * post["sentiment_score"] +
            WEIGHTS["comments"]  * comments_n[i]
        ) * 100, 1)

        print(f"  📊 {post['shortcode']} → score {post['score']}")

    return sorted(posts, key=lambda p: p["score"], reverse=True)


# ── Google Sheets ─────────────────────────────────────────────────────────────
def update_sheets(posts: list[dict]):
    creds_dict = json.loads(GOOGLE_CREDS_JSON)
    creds      = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    gc         = gspread.authorize(creds)
    sh         = gc.open_by_key(SPREADSHEET_ID)

    # ── Tab 1: Scores ──────────────────────────────────────────────────────
    try:
        ws = sh.worksheet("Scores")
        ws.clear()
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet("Scores", rows=50, cols=15)

    headers = [
        "Rank", "Date", "Score (/100)", "Views", "Likes",
        "Comments", "Sentiment", "Positive Themes",
        "Negative Themes", "Caption (preview)", "URL"
    ]
    rows = [headers]
    for rank, p in enumerate(posts, 1):
        rows.append([
            rank,
            p["date"],
            p["score"],
            p["views"],
            p["likes"],
            p["comments"],
            round(p["sentiment_score"], 2),
            ", ".join(p["sentiment"]["positive_themes"]),
            ", ".join(p["sentiment"]["negative_themes"]),
            p["caption"][:80],
            p["url"],
        ])
    ws.update("A1", rows)

    # Bold header
    ws.format("A1:K1", {"textFormat": {"bold": True}})

    # ── Tab 2: History ─────────────────────────────────────────────────────
    try:
        hist = sh.worksheet("History")
    except gspread.WorksheetNotFound:
        hist = sh.add_worksheet("History", rows=1000, cols=6)
        hist.update("A1", [["Run Date", "Shortcode", "Post Date", "Score", "Views", "Likes"]])

    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    hist_rows = [
        [run_date, p["shortcode"], p["date"], p["score"], p["views"], p["likes"]]
        for p in posts
    ]
    hist.append_rows(hist_rows)

    print(f"✅ Google Sheets updated ({len(posts)} posts)")
    return posts   # pass through for email


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    import random
    print(f"\n🚀 Starting Instagram scorer — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    delay = random.randint(10, 30)
    print(f"⏳ Waiting {delay}s before hitting Instagram...")
    time.sleep(delay)
    print("📥 Fetching posts...")
    posts = fetch_posts()
    print(f"   {len(posts)} posts fetched")

    print("🧠 Scoring posts...")
    posts = compute_scores(posts)

    print("📊 Updating Google Sheets...")
    update_sheets(posts)

    # Save scored posts for the email script
    with open("scored_posts.json", "w") as f:
        json.dump(posts, f, indent=2, default=str)

    print("✅ Done — scored_posts.json written")


if __name__ == "__main__":
    main()
