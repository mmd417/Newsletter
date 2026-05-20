#!/usr/bin/env python3
"""
Polish Press Weekly Newsletter Agent
Fetches articles from Polish news outlets, summarizes them with Claude,
and sends a formatted email digest every Sunday evening.
"""

import os
import json
import logging
import smtplib
import feedparser
import requests
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from bs4 import BeautifulSoup
import anthropic

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GMAIL_USER        = os.environ["GMAIL_USER"]          # your Gmail address
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"] # Gmail app password
RECIPIENT_EMAIL   = os.environ.get("RECIPIENT_EMAIL", GMAIL_USER)

# Paywalled outlets: store cookies as JSON strings in GitHub Secrets
# e.g. GW_COOKIES = '[{"name":"piano_id","value":"...","domain":".wyborcza.pl"}]'
GW_COOKIES_JSON = os.environ.get("GW_COOKIES", "")  # Gazeta Wyborcza session cookies

LOOKBACK_DAYS = 7  # articles published within the last 7 days

# ── Outlet Definitions ─────────────────────────────────────────────────────────
OUTLETS = [
    # ── Paywalled (falls back to RSS if no cookies) ────────────────────────────
    {
        "name": "Gazeta Wyborcza",
        "bias": "center-left / liberal",
        "rss": "https://wyborcza.pl/pub/rss/najnowsze_wyborcza.xml",
        "paywall": True,
        "cookie_env": "GW_COOKIES",
    },
    # ── Free RSS ───────────────────────────────────────────────────────────────
    {
        "name": "Rzeczpospolita",
        "bias": "center-right / conservative",
        "rss": "https://www.rp.pl/rss/1019",
        "paywall": False,
    },
    {
        "name": "Onet.pl",
        "bias": "centrist",
        "rss": "https://wiadomosci.onet.pl/.feed",
        "paywall": False,
    },
    {
        "name": "TVN24",
        "bias": "center-left / liberal",
        "rss": "https://tvn24.pl/najnowsze.xml",
        "paywall": False,
    },
    {
        "name": "Polsat News",
        "bias": "centrist / populist",
        "rss": "https://www.polsatnews.pl/rss/wszystkie.xml",
        "paywall": False,
    },
    {
        # Weekly magazine; deepest investigative tradition in Poland
        "name": "Tygodnik Powszechny",
        "bias": "center-left / Catholic liberal",
        "rss": "https://www.tygodnikpowszechny.pl/rss.xml",
        "paywall": False,
    },
    {
        # Right-wing weekly; flagship voice of the national-conservative camp
        "name": "Do Rzeczy",
        "bias": "right-wing / national-conservative",
        "rss": "https://dorzeczy.pl/feed/",
        "paywall": False,
    },
    {
        # High-traffic centrist news portal
        "name": "Interia Fakty",
        "bias": "centrist",
        "rss": "https://fakty.interia.pl/feed",
        "paywall": False,
    },
    {
        # Largest Polish web portal; broad centrist audience
        "name": "WP Wiadomości",
        "bias": "centrist",
        "rss": "https://wiadomosci.wp.pl/rss.xml",
        "paywall": False,
    },
    {
        # Leading financial/business daily
        "name": "Bankier.pl",
        "bias": "business / centrist",
        "rss": "https://www.bankier.pl/rss/wiadomosci.xml",
        "paywall": False,
    },
]

# ── Claude System Prompt ───────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a senior editor writing a weekly briefing on Poland for an English-speaking reader \
who follows international affairs but has limited background on Polish politics, history, or institutions.

You will receive a JSON list of news articles from Polish outlets over the past week. \
Each article includes: title, summary/description, outlet name, political bias, and URL. \
You may also receive social media excerpts flagged with "source": "social_media".

— SELECTION STANDARD —
Include exactly 4–6 stories — never fewer than 4, never more than 6. A story earns its place only if it:
  • Signals a real shift in Polish politics, law, economy, or foreign policy
  • Reveals how Polish institutions or society actually function
  • Gives an informed reader genuine insight unavailable from generic Western coverage
Exclude: gossip, routine crime, minor local events, PR, near-duplicates (keep the best version).
Fewer strong stories beat a padded list.

— FOR EACH STORY, WRITE THREE TIGHT SECTIONS —

1. WHAT HAPPENED
One crisp headline (your framing, not a translation). Then 2 sentences max: who did what, and when/where.

2. WHY IT MATTERS
2–3 sentences. Assume the reader does NOT know Polish political history or institutions — \
briefly name any essential background (e.g. what a referenced law, party, or institution is, \
why a particular relationship or conflict has been ongoing). Then state why this development is significant \
beyond Poland's borders or why it changes something meaningful domestically.

3. SENTIMENT & REACTION
3–4 sentences, as specific as possible. Pull directly from the articles: \
quote or paraphrase named politicians, officials, or public figures where available. \
If any article references Twitter/X posts, social media trends, or online public reaction, \
surface those explicitly (e.g. "#XYZ trended on Polish Twitter," or "a viral post by @handle argued…"). \
Where outlets with opposing political biases frame the same event differently, name both framings \
(e.g. "Conservative Rzeczpospolita calls this … while liberal TVN24 frames it as …").
Be specific; avoid vague phrases like "many Poles feel" without evidence from the articles.

— STYLE —
Write in plain, direct English. No padding, no throat-clearing. \
Each section should be as short as it can be while remaining complete. \
Prefer concrete nouns and active verbs.

— GROUPING —
Organise stories under (omit empty sections):
  🏛️ Politics & Government
  💰 Economy & Business
  🇪🇺 International & EU Affairs
  🧭 Society & Culture

Output format — return ONLY valid JSON, no markdown fences, no preamble:
{
  "week_range": "May 12–18, 2026",
  "sections": [
    {
      "title": "🏛️ Politics & Government",
      "stories": [
        {
          "headline": "...",
          "what_happened": "...",
          "why_it_matters": "...",
          "sentiment_and_reaction": "...",
          "source": "Outlet Name",
          "bias": "center-left / liberal",
          "url": "https://..."
        }
      ]
    }
  ]
}"""

# ── Helpers ────────────────────────────────────────────────────────────────────

def parse_cookies(json_str: str) -> dict:
    """Convert a JSON cookie array to a requests-compatible dict."""
    if not json_str:
        return {}
    try:
        cookies = json.loads(json_str)
        return {c["name"]: c["value"] for c in cookies}
    except Exception:
        log.warning("Failed to parse cookies JSON")
        return {}


def is_recent(entry) -> bool:
    """Return True if the feed entry was published within LOOKBACK_DAYS."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    published = getattr(entry, "published_parsed", None)
    if published is None:
        return True  # include if date unknown
    pub_dt = datetime(*published[:6], tzinfo=timezone.utc)
    return pub_dt >= cutoff


def fetch_rss_articles(outlet: dict) -> list[dict]:
    """Fetch articles via RSS feed."""
    articles = []
    try:
        feed = feedparser.parse(outlet["rss"])
        for entry in feed.entries:
            if not is_recent(entry):
                continue
            summary = entry.get("summary", "") or entry.get("description", "")
            # Strip HTML tags from summary
            summary = BeautifulSoup(summary, "html.parser").get_text(separator=" ").strip()
            articles.append({
                "title":   entry.get("title", "").strip(),
                "summary": summary[:600],  # cap length
                "url":     entry.get("link", ""),
                "outlet":  outlet["name"],
                "bias":    outlet["bias"],
            })
        log.info(f"[{outlet['name']}] {len(articles)} articles from RSS")
    except Exception as e:
        log.error(f"[{outlet['name']}] RSS fetch failed: {e}")
    return articles


def fetch_paywall_articles(outlet: dict) -> list[dict]:
    """
    Attempt to fetch paywalled content using stored session cookies.
    Falls back to RSS if cookies are missing or expired.
    """
    cookie_env = outlet.get("cookie_env", "")
    raw_cookies = os.environ.get(cookie_env, "")
    if not raw_cookies:
        log.info(f"[{outlet['name']}] No cookies found — falling back to RSS")
        return fetch_rss_articles(outlet)

    cookies = parse_cookies(raw_cookies)
    articles = []
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; NewsletterBot/1.0)",
            "Accept-Language": "pl-PL,pl;q=0.9",
        }
        # Fetch the outlet's main news page
        base_url = outlet["rss"].rsplit("/rss", 1)[0]
        resp = requests.get(base_url, cookies=cookies, headers=headers, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Generic article link extractor — works for most Polish news sites
        seen = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not href.startswith("http"):
                href = base_url.rstrip("/") + "/" + href.lstrip("/")
            if href in seen or len(seen) >= 30:
                continue
            text = a.get_text(strip=True)
            if len(text) > 40:  # likely a headline link
                seen.add(href)
                articles.append({
                    "title":   text[:200],
                    "summary": "",  # Claude will work with title alone if needed
                    "url":     href,
                    "outlet":  outlet["name"],
                    "bias":    outlet["bias"],
                })
        log.info(f"[{outlet['name']}] {len(articles)} articles via authenticated scrape")
    except Exception as e:
        log.error(f"[{outlet['name']}] Scrape failed: {e} — falling back to RSS")
        return fetch_rss_articles(outlet)
    return articles


def _parse_rss_feed(url: str, outlet_name: str, max_items: int = 10) -> list[dict]:
    """Shared helper: parse an RSS feed and return normalised article dicts."""
    items = []
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:max_items]:
            summary = entry.get("summary", "") or entry.get("description", "")
            summary = BeautifulSoup(summary, "html.parser").get_text(separator=" ").strip()
            items.append({
                "title":   entry.get("title", "").strip()[:200],
                "summary": summary[:500],
                "url":     entry.get("link", ""),
                "outlet":  outlet_name,
                "bias":    "public sentiment",
                "source":  "social_media",
            })
    except Exception as e:
        log.warning(f"[{outlet_name}] RSS fetch failed: {e}")
    return items


def fetch_social_media_signals() -> list[dict]:
    """
    Collect public sentiment signals from Polish Reddit communities and Wykop.
    Both sources are open — no API key required.

    Reddit:  JSON API (reddit.com/r/<sub>/top.json) — returns top posts of the week.
    Wykop:   RSS feed for trending/hot content.

    Twitter/X upgrade path: replace or extend this function with X API v2
    (search/recent endpoint) using TWITTER_BEARER_TOKEN stored in env/secrets.
    """
    signals: list[dict] = []

    # ── Reddit ─────────────────────────────────────────────────────────────────
    REDDIT_SUBS = [
        ("r/poland",      "https://www.reddit.com/r/poland/top.json?t=week&limit=10"),
        ("r/Polska",      "https://www.reddit.com/r/Polska/top.json?t=week&limit=10"),
        ("r/europe (PL)", "https://www.reddit.com/r/europe/search.json?q=Poland&sort=top&t=week&limit=10"),
    ]
    headers = {"User-Agent": "PolishPressWeekly/1.0 (newsletter bot; contact via GitHub)"}
    for name, url in REDDIT_SUBS:
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            posts = resp.json().get("data", {}).get("children", [])
            for post in posts:
                d = post.get("data", {})
                title   = d.get("title", "").strip()
                selftext = d.get("selftext", "")[:300].strip()
                score   = d.get("score", 0)
                comments = d.get("num_comments", 0)
                link    = "https://reddit.com" + d.get("permalink", "")
                if not title:
                    continue
                signals.append({
                    "title":   f"[Reddit {name}] {title}",
                    "summary": (
                        f"{selftext} " if selftext else ""
                    ) + f"(↑{score} upvotes, {comments} comments)",
                    "url":     link,
                    "outlet":  f"Reddit {name}",
                    "bias":    "public sentiment",
                    "source":  "social_media",
                })
            log.info(f"[Reddit {name}] {len(posts)} posts collected")
        except Exception as e:
            log.warning(f"[Reddit {name}] fetch failed: {e}")

    # ── Wykop ──────────────────────────────────────────────────────────────────
    # Wykop is Poland's largest link-aggregator / social news site (~Reddit equivalent).
    # The RSS feed surfaces the week's most-upvoted ("wykopane") links.
    WYKOP_FEEDS = [
        ("Wykop / Trending",  "https://wykop.pl/rss/trendy"),
        ("Wykop / Główna",    "https://wykop.pl/rss/wykopalisko"),
    ]
    for name, url in WYKOP_FEEDS:
        items = _parse_rss_feed(url, name, max_items=8)
        # Prefix titles so Claude knows the source
        for item in items:
            item["title"] = f"[{name}] {item['title']}"
        signals.extend(items)
        log.info(f"[{name}] {len(items)} posts collected")

    log.info(f"[Social Media total] {len(signals)} signals collected")
    return signals


def collect_all_articles() -> list[dict]:
    """Collect articles from all configured outlets, plus social media signals."""
    all_articles = []
    for outlet in OUTLETS:
        if outlet.get("paywall"):
            articles = fetch_paywall_articles(outlet)
        else:
            articles = fetch_rss_articles(outlet)
        all_articles.extend(articles)

    # Append social media signals as supplementary context for Claude
    all_articles.extend(fetch_social_media_signals())

    log.info(f"Total articles collected: {len(all_articles)}")
    return all_articles


# ── Claude Summarization ───────────────────────────────────────────────────────

def summarize_with_claude(articles: list[dict]) -> dict:
    """Send articles to Claude and receive structured newsletter JSON."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Trim payload — send at most 120 articles to stay within context
    payload = articles[:120]
    user_message = json.dumps(payload, ensure_ascii=False, indent=2)

    log.info(f"Sending {len(payload)} articles to Claude for summarization...")
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = response.content[0].text.strip()
    # Strip accidental markdown fences
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw)


# ── Email Rendering ────────────────────────────────────────────────────────────

def render_html_email(newsletter: dict) -> str:
    """Convert the structured newsletter JSON into a styled HTML email."""
    week_range = newsletter.get("week_range", "")
    sections   = newsletter.get("sections", [])

    stories_html = ""
    for section in sections:
        stories_html += f"""
        <tr><td style="padding: 28px 0 8px;">
          <h2 style="margin:0;font-size:17px;color:#1a1a1a;font-family:Georgia,serif;
                     border-bottom:2px solid #e8e0d5;padding-bottom:8px;">
            {section['title']}
          </h2>
        </td></tr>"""
        for story in section.get("stories", []):
            stories_html += f"""
        <tr><td style="padding:20px 0;border-bottom:1px solid #f0ebe3;">

          <!-- Headline -->
          <a href="{story['url']}" style="text-decoration:none;">
            <p style="margin:0 0 14px;font-size:16px;font-weight:bold;
                      color:#1a1a1a;font-family:Georgia,serif;line-height:1.4;">
              {story['headline']}
            </p>
          </a>

          <!-- What happened -->
          <p style="margin:0 0 4px;font-size:11px;font-weight:bold;color:#b0956a;
                    letter-spacing:1.2px;text-transform:uppercase;">What happened</p>
          <p style="margin:0 0 14px;font-size:14px;color:#333;line-height:1.7;">
            {story['what_happened']}
          </p>

          <!-- Why it matters -->
          <p style="margin:0 0 4px;font-size:11px;font-weight:bold;color:#b0956a;
                    letter-spacing:1.2px;text-transform:uppercase;">Why it matters</p>
          <p style="margin:0 0 14px;font-size:14px;color:#333;line-height:1.7;">
            {story['why_it_matters']}
          </p>

          <!-- Sentiment & reaction -->
          <p style="margin:0 0 4px;font-size:11px;font-weight:bold;color:#b0956a;
                    letter-spacing:1.2px;text-transform:uppercase;">Sentiment &amp; reaction</p>
          <p style="margin:0 0 14px;font-size:14px;color:#333;line-height:1.7;
                    border-left:3px solid #e8e0d5;padding-left:12px;">
            {story['sentiment_and_reaction']}
          </p>

          <!-- Source tag -->
          <p style="margin:0;font-size:12px;color:#999;">
            <span style="background:#f5f0ea;border-radius:3px;
                         padding:2px 7px;margin-right:6px;">
              {story['source']}
            </span>
            <span style="color:#b0956a;">{story['bias']}</span>
          </p>

        </td></tr>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Polish Press Weekly</title></head>
<body style="margin:0;padding:0;background:#f9f5f0;font-family:Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" bgcolor="#f9f5f0">
  <tr><td align="center" style="padding:32px 16px;">
    <table width="620" cellpadding="0" cellspacing="0"
           style="background:#fff;border-radius:8px;
                  box-shadow:0 2px 12px rgba(0,0,0,0.07);overflow:hidden;">

      <!-- Header -->
      <tr><td style="background:#1a1a1a;padding:28px 36px;">
        <p style="margin:0;font-size:11px;color:#b0956a;
                  letter-spacing:2px;text-transform:uppercase;">Weekly Digest</p>
        <h1 style="margin:6px 0 4px;font-size:26px;color:#fff;
                   font-family:Georgia,serif;">🇵🇱 Polish Press Weekly</h1>
        <p style="margin:0;font-size:13px;color:#888;">{week_range}</p>
      </td></tr>

      <!-- Body -->
      <tr><td style="padding:0 36px 36px;">
        <table width="100%" cellpadding="0" cellspacing="0">
          {stories_html}
        </table>
      </td></tr>

      <!-- Footer -->
      <tr><td style="background:#f5f0ea;padding:20px 36px;
                     border-top:1px solid #e8e0d5;">
        <p style="margin:0;font-size:11px;color:#aaa;line-height:1.6;">
          Sources: Gazeta Wyborcza · Rzeczpospolita · Onet.pl · TVN24 · Polsat News<br>
          Bias labels reflect broad editorial positions — individual articles may vary.<br>
          Generated by your Polish Press Weekly Agent · {datetime.now().strftime("%B %d, %Y")}
        </p>
      </td></tr>

    </table>
  </td></tr>
</table>
</body></html>"""


# ── Email Sending ──────────────────────────────────────────────────────────────

def send_email(html_body: str, week_range: str):
    """Send the newsletter via Gmail SMTP."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🇵🇱 Polish Press Weekly — {week_range}"
    msg["From"]    = GMAIL_USER
    msg["To"]      = RECIPIENT_EMAIL
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    log.info(f"Sending email to {RECIPIENT_EMAIL}...")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, RECIPIENT_EMAIL, msg.as_string())
    log.info("Email sent successfully.")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    log.info("=== Polish Press Weekly Agent starting ===")

    articles   = collect_all_articles()
    if not articles:
        log.error("No articles collected. Aborting.")
        return

    newsletter = summarize_with_claude(articles)
    html       = render_html_email(newsletter)
    send_email(html, newsletter.get("week_range", "This Week"))

    log.info("=== Done ===")


if __name__ == "__main__":
    main()
