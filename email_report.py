"""
email_report.py
Reads scored_posts.json and sends a detailed HTML email report
via Gmail SMTP (App Password).
"""

import json
import os
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import requests

GMAIL_USER     = os.environ["GMAIL_USER"]       # e.g. foodpharmer@gmail.com
GMAIL_APP_PASS = os.environ["GMAIL_APP_PASS"]   # 16-char Gmail App Password
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
SPREADSHEET_URL = f"https://docs.google.com/spreadsheets/d/{os.environ['SPREADSHEET_ID']}"

RECIPIENTS = [
    "foodpharmer@gmail.com",
    "dhairyavora4@gmail.com",
    "samvida.patel@nyu.edu",
    "dev.narsinghani@gmail.com",
    "manufilmwala@gmail.com",
    "harshdas199@gmail.com",
]

# ── Gemini: generate actionable tip ──────────────────────────────────────────
def generate_tip(posts: list[dict]) -> str:
    top    = posts[0]
    bottom = posts[-1]
    prompt = f"""
You are a social media strategist for @foodpharmer, a health & food education creator on Instagram.

Top performing post today:
- Caption: {top['caption']}
- Score: {top['score']}/100
- Positive themes in comments: {', '.join(top['sentiment']['positive_themes'])}

Lowest performing post today:
- Caption: {bottom['caption']}
- Score: {bottom['score']}/100
- Negative themes: {', '.join(bottom['sentiment']['negative_themes'])}

In 2-3 sentences, give ONE specific, actionable content tip for tomorrow based on this data.
Be direct and concrete. No generic advice.
"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    resp = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=30)
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()


# ── HTML Email Builder ────────────────────────────────────────────────────────
def build_html(posts: list[dict], tip: str) -> str:
    run_date = datetime.now(timezone.utc).strftime("%B %d, %Y")
    top      = posts[0]
    bottom   = posts[-1]

    # Find trending post: biggest view count not at rank 1
    trending = max(posts[1:], key=lambda p: p["views"]) if len(posts) > 1 else top

    def score_bar(score):
        color = "#22c55e" if score >= 70 else "#f59e0b" if score >= 40 else "#ef4444"
        return f"""
        <div style="background:#e5e7eb;border-radius:999px;height:8px;width:100%;margin-top:4px;">
          <div style="background:{color};width:{score}%;height:8px;border-radius:999px;"></div>
        </div>"""

    def theme_pills(themes, color):
        if not themes:
            return "<span style='color:#9ca3af;font-size:12px;'>None detected</span>"
        return " ".join(
            f'<span style="background:{color};padding:2px 10px;border-radius:999px;font-size:12px;margin-right:4px;">{t}</span>'
            for t in themes
        )

    # Full scorecard rows
    scorecard_rows = ""
    for rank, p in enumerate(posts, 1):
        medal = ["🥇","🥈","🥉"][rank-1] if rank <= 3 else f"#{rank}"
        row_bg = "#f0fdf4" if rank == 1 else "#fff7ed" if rank == len(posts) else "white"
        scorecard_rows += f"""
        <tr style="background:{row_bg};">
          <td style="padding:10px 12px;font-weight:600;">{medal}</td>
          <td style="padding:10px 12px;">
            <a href="{p['url']}" style="color:#6366f1;text-decoration:none;">{p['caption'][:50]}…</a>
            <div style="font-size:11px;color:#9ca3af;">{p['date']}</div>
          </td>
          <td style="padding:10px 12px;font-weight:700;color:#1f2937;">{p['score']}</td>
          <td style="padding:10px 12px;">{p['views']:,}</td>
          <td style="padding:10px 12px;">{p['likes']:,}</td>
          <td style="padding:10px 12px;">{p['comments']:,}</td>
          <td style="padding:10px 12px;">{round(p['sentiment_score']*100)}%</td>
        </tr>"""

    html = f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:'Segoe UI',Arial,sans-serif;">

<div style="max-width:680px;margin:32px auto;background:white;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);">

  <!-- Header -->
  <div style="background:linear-gradient(135deg,#6366f1,#8b5cf6);padding:32px 40px;color:white;">
    <div style="font-size:13px;opacity:0.8;letter-spacing:1px;text-transform:uppercase;">Daily Report</div>
    <h1 style="margin:8px 0 4px;font-size:26px;">📊 FoodPharmer Video Intelligence</h1>
    <div style="font-size:14px;opacity:0.85;">{run_date} · Last 10 Posts Analysed</div>
  </div>

  <div style="padding:32px 40px;">

    <!-- 🏆 Top Performer -->
    <div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:12px;padding:20px 24px;margin-bottom:20px;">
      <div style="font-size:11px;color:#16a34a;font-weight:700;letter-spacing:1px;text-transform:uppercase;">🏆 Top Performer</div>
      <a href="{top['url']}" style="color:#1f2937;text-decoration:none;font-size:17px;font-weight:700;display:block;margin:8px 0 4px;">{top['caption'][:80]}…</a>
      <div style="font-size:13px;color:#6b7280;margin-bottom:12px;">{top['date']} · Score: <strong>{top['score']}/100</strong></div>
      {score_bar(top['score'])}
      <div style="margin-top:14px;display:flex;gap:24px;font-size:13px;">
        <span>👁️ <strong>{top['views']:,}</strong> views</span>
        <span>❤️ <strong>{top['likes']:,}</strong> likes</span>
        <span>💬 <strong>{top['comments']:,}</strong> comments</span>
      </div>
      <div style="margin-top:12px;">
        <div style="font-size:12px;color:#6b7280;margin-bottom:6px;">What resonated:</div>
        {theme_pills(top['sentiment']['positive_themes'], '#dcfce7')}
      </div>
      <div style="margin-top:8px;font-size:13px;color:#374151;font-style:italic;">"{top['sentiment']['summary']}"</div>
    </div>

    <!-- 📉 Needs Work -->
    <div style="background:#fef2f2;border:1px solid #fecaca;border-radius:12px;padding:20px 24px;margin-bottom:20px;">
      <div style="font-size:11px;color:#dc2626;font-weight:700;letter-spacing:1px;text-transform:uppercase;">📉 Needs Work</div>
      <a href="{bottom['url']}" style="color:#1f2937;text-decoration:none;font-size:17px;font-weight:700;display:block;margin:8px 0 4px;">{bottom['caption'][:80]}…</a>
      <div style="font-size:13px;color:#6b7280;margin-bottom:12px;">{bottom['date']} · Score: <strong>{bottom['score']}/100</strong></div>
      {score_bar(bottom['score'])}
      <div style="margin-top:14px;display:flex;gap:24px;font-size:13px;">
        <span>👁️ <strong>{bottom['views']:,}</strong> views</span>
        <span>❤️ <strong>{bottom['likes']:,}</strong> likes</span>
        <span>💬 <strong>{bottom['comments']:,}</strong> comments</span>
      </div>
      <div style="margin-top:12px;">
        <div style="font-size:12px;color:#6b7280;margin-bottom:6px;">What didn't land:</div>
        {theme_pills(bottom['sentiment']['negative_themes'], '#fee2e2')}
      </div>
      <div style="margin-top:8px;font-size:13px;color:#374151;font-style:italic;">"{bottom['sentiment']['summary']}"</div>
    </div>

    <!-- 📈 Trending -->
    <div style="background:#fffbeb;border:1px solid #fde68a;border-radius:12px;padding:20px 24px;margin-bottom:20px;">
      <div style="font-size:11px;color:#d97706;font-weight:700;letter-spacing:1px;text-transform:uppercase;">📈 Highest Reach (Non-#1)</div>
      <a href="{trending['url']}" style="color:#1f2937;text-decoration:none;font-size:17px;font-weight:700;display:block;margin:8px 0 4px;">{trending['caption'][:80]}…</a>
      <div style="font-size:13px;color:#6b7280;margin-bottom:8px;">{trending['date']} · {trending['views']:,} views · Score {trending['score']}/100</div>
      <div style="font-size:13px;color:#374151;font-style:italic;">"{trending['sentiment']['summary']}"</div>
    </div>

    <!-- 🎯 AI Tip -->
    <div style="background:#f5f3ff;border:1px solid #ddd6fe;border-radius:12px;padding:20px 24px;margin-bottom:28px;">
      <div style="font-size:11px;color:#7c3aed;font-weight:700;letter-spacing:1px;text-transform:uppercase;">🎯 Tomorrow's Actionable Tip</div>
      <div style="margin-top:10px;font-size:14px;color:#374151;line-height:1.6;">{tip}</div>
    </div>

    <!-- 📊 Full Scorecard -->
    <div style="font-size:16px;font-weight:700;color:#1f2937;margin-bottom:12px;">📊 Full Scorecard</div>
    <table style="width:100%;border-collapse:collapse;font-size:13px;">
      <thead>
        <tr style="background:#f9fafb;color:#6b7280;text-transform:uppercase;font-size:11px;letter-spacing:0.5px;">
          <th style="padding:10px 12px;text-align:left;">Rank</th>
          <th style="padding:10px 12px;text-align:left;">Post</th>
          <th style="padding:10px 12px;text-align:left;">Score</th>
          <th style="padding:10px 12px;text-align:left;">Views</th>
          <th style="padding:10px 12px;text-align:left;">Likes</th>
          <th style="padding:10px 12px;text-align:left;">Comments</th>
          <th style="padding:10px 12px;text-align:left;">Sentiment</th>
        </tr>
      </thead>
      <tbody>
        {scorecard_rows}
      </tbody>
    </table>

    <!-- Footer -->
    <div style="margin-top:32px;padding-top:20px;border-top:1px solid #e5e7eb;text-align:center;">
      <a href="{SPREADSHEET_URL}" style="display:inline-block;background:#6366f1;color:white;padding:12px 28px;border-radius:8px;text-decoration:none;font-weight:600;font-size:14px;">
        📈 Open Full Dashboard in Google Sheets
      </a>
      <div style="margin-top:16px;font-size:12px;color:#9ca3af;">
        Automated daily report for @foodpharmer · Powered by Instaloader + Gemini AI
      </div>
    </div>

  </div>
</div>
</body>
</html>"""
    return html


# ── Send Email ─────────────────────────────────────────────────────────────────
def send_email(html: str, posts: list[dict]):
    run_date = datetime.now(timezone.utc).strftime("%b %d, %Y")
    top_score = posts[0]["score"]
    subject = f"📊 FoodPharmer Daily Report — {run_date} · Top Score: {top_score}/100"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_USER
    msg["To"]      = ", ".join(RECIPIENTS)

    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASS)
        server.sendmail(GMAIL_USER, RECIPIENTS, msg.as_string())

    print(f"✅ Email sent to {len(RECIPIENTS)} recipients")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("📧 Building email report...")
    with open("scored_posts.json") as f:
        posts = json.load(f)

    print("🧠 Generating AI tip...")
    tip = generate_tip(posts)

    html = build_html(posts, tip)
    send_email(html, posts)
    print("✅ Done")


if __name__ == "__main__":
    main()
