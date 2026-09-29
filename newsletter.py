#!/usr/bin/env python3
"""
Weekly Debrief: Poland — Newsletter Agent
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
ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
GMAIL_USER         = os.environ["GMAIL_USER"]           # sending address
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]   # Gmail app password
# Comma-separated list of recipients, e.g. "a@gmail.com,b@gmail.com"
RECIPIENTS = [
    r.strip()
    for r in os.environ.get("RECIPIENT_EMAIL", GMAIL_USER).split(",")
    if r.strip()
]

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
SYSTEM_PROMPT = """You are a senior editor writing a weekly briefing on Poland for an American reader with a \
personal connection to Poland — an immigrant, someone of Polish heritage, a traveler, or simply \
someone who cares about understanding the country on its own terms.

This reader follows US news closely (think NYT subscriber) and is aware of how American media \
frames the world. They are not looking for that frame. They want a clear-eyed, non-partisan window \
into what is actually happening in Poland — politically, culturally, socially, economically.

You will receive a JSON list of news articles from Polish outlets over the past week. \
Each article includes: title, summary/description, outlet name, political bias, and URL. \
You may also receive social media excerpts flagged with "source": "social_media".

— SELECTION & RANKING —
Select and rank exactly 5 stories. Rank #1 is the single most important story of the week. \
Rank the rest in descending order of importance to this specific reader.

Apply the following tests in order:

  TEST 1 — WHY WOULD AN AMERICAN CARE?
  Every story must pass this test. Ask: would a thoughtful American with ties to Poland \
find this genuinely meaningful, illuminating, or relevant to their life? If the answer \
is no, drop the story. A story can pass this test in two ways:
    a) It connects to something Americans already track: NATO, US-EU relations, energy, \
migration, democracy and rule of law, or Polish-American policy.
    b) It reveals something true and important about Polish identity, culture, or society \
that helps an outsider understand the country more deeply — even if it has no US angle.

  TEST 2 — SIGNAL VS. NOISE
  Prefer stories that represent a meaningful, durable shift over one-off events. \
Inner-party maneuvering, procedural votes, and routine appointments fail this test \
unless they signal a larger realignment (e.g. a new political force gaining traction, \
a coalition fracturing, a generational shift in public opinion). Think: what would still \
matter in six months?

  TEST 3 — ACCESSIBILITY
  If a story requires deep technical knowledge (niche legal proceedings, financial \
regulatory details, obscure institutional disputes) to understand why it matters, \
reconsider it. The story either needs a strong plain-English "why it matters" framing \
or should be dropped in favor of something more accessible.

Exclude always: celebrity gossip, routine crime, minor local events, PR pieces, \
near-duplicates (keep only the most informative version of any repeated story).

For each story, assign exactly one story_type tag:
  "national"       — primarily a domestic Polish story (politics, society, culture)
  "international"  — Poland's role in EU, NATO, or global affairs
  "us-poland"      — directly involves US-Poland relations, US policy, or American interests
  "regional"       — Central/Eastern European context beyond Poland alone

— FOR EACH STORY, WRITE THREE TIGHT SECTIONS —

1. HEADLINE
Write a clear, informative headline that tells the reader exactly what happened and why it matters — \
in one line. Pack the key takeaway directly into the headline; do not tease or withhold it. \
Avoid clickbait constructions like "— and the Irony Is Rich" or "— and It's Starting to Cost Real Money." \
The reader should finish the headline knowing the story, not just curious about it. \
Good: "Trump Praises Poland's New President at Polish-American Gala, Complicating Tusk's Coalition" \
Good: "Kraków Municipal Vote Shows Losses for Both Major Parties as Independents Surge" \
Bad: "Trump Praised Poland's President — and the Irony Is Rich" \
Bad: "Kraków Just Had an Election — and Every Major Party Lost"

2. WHAT HAPPENED
2 sentences max: who did what, and when/where. No editorializing here — just the facts.

3. WHY IT MATTERS
2–3 sentences. Assume the reader does NOT know Polish political history or institutions — \
briefly name any essential background (e.g. what a referenced law, party, or institution is, \
why a particular conflict has been ongoing). Then state clearly why this is significant — \
especially any connection to US interests, NATO, or the broader Western world.

4. SENTIMENT & REACTION
2 sentences maximum. Lead with the sharpest, most specific reaction available — \
quote or paraphrase a named person with their full name and role on first mention \
(e.g. "Donald Tusk, Poland's Prime Minister," not just "Tusk"). \
If outlets frame the story differently across the political spectrum, capture that in one sentence.

— NAMES & TITLES —
Every person named must be identified on first mention with their full name and role \
(e.g. "Andrzej Duda, Poland's President," "Jarosław Kaczyński, leader of the opposition PiS party"). \
Never assume the reader recognises a Polish or European name.

— TONE & VOICE —
Write like a sharp, curious American explaining something to a friend who genuinely cares about Poland. \
Direct, a little sardonic when the situation calls for it, no hedging. \
Drop the journalistic passive voice — no "it remains to be seen," no "observers note," \
no "the development comes amid." \
If something is surprising or ironic, say so. If the stakes are high, say so plainly. \
You are not a wire service. You are a person with a point of view who has done the reading.

Output format — return ONLY valid JSON, no markdown fences, no preamble:
{
  "week_range": "Sep 22–28, 2026",
  "stories": [
    {
      "rank": 1,
      "story_type": "national",
      "headline": "...",
      "what_happened": "...",
      "why_it_matters": "...",
      "sentiment_and_reaction": "...",
      "source": "Outlet Name",
      "bias": "center-left / liberal",
      "url": "https://..."
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

TYPE_LABELS = {
    "national":      ("🏛", "National",      "#e8f0fe", "#1a56db"),
    "international": ("🌍", "International", "#fef3c7", "#b45309"),
    "us-poland":     ("🇺🇸", "US–Poland",    "#fce7f3", "#9d174d"),
    "regional":      ("🗺", "Regional",      "#ecfdf5", "#065f46"),
}

def render_html_email(newsletter: dict) -> str:
    """Convert the structured newsletter JSON into a styled HTML email."""
    week_range = newsletter.get("week_range", "")
    stories    = newsletter.get("stories", [])

    # Build the at-a-glance headlines list
    headlines_html = ""
    for story in sorted(stories, key=lambda s: s.get("rank", 99)):
        rank  = story.get("rank", "")
        stype = story.get("story_type", "national")
        icon, label, bg, fg = TYPE_LABELS.get(stype, ("📰", stype.title(), "#f5f0ea", "#444"))
        headlines_html += f"""
          <tr><td style="padding:5px 0;">
            <span style="font-size:13px;font-weight:bold;color:#d4a84b;margin-right:8px;">#{rank}</span>
            <span style="background:{bg};color:{fg};border-radius:3px;
                         padding:1px 6px;font-size:10px;font-weight:bold;
                         margin-right:8px;">[{icon} {label}]</span>
            <span style="font-size:13px;color:#1a1a1a;">{story['headline']}</span>
          </td></tr>"""

    stories_html = ""
    for story in sorted(stories, key=lambda s: s.get("rank", 99)):
        rank  = story.get("rank", "")
        stype = story.get("story_type", "national")
        icon, label, bg, fg = TYPE_LABELS.get(stype, ("📰", stype.title(), "#f5f0ea", "#444"))

        stories_html += f"""
        <tr><td style="padding:20px 0;border-bottom:1px solid #f0ebe3;">

          <!-- Rank + type badge row -->
          <p style="margin:0 0 10px;font-size:12px;color:#999;display:flex;align-items:center;gap:8px;">
            <span style="font-size:18px;font-weight:bold;color:#d4a84b;margin-right:6px;">#{rank}</span>
            <span style="background:{bg};color:{fg};border-radius:4px;
                         padding:2px 8px;font-size:11px;font-weight:bold;letter-spacing:0.5px;">
              [{icon} {label}]
            </span>
          </p>

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
<title>Weekly Debrief: Poland</title></head>
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
                   font-family:Georgia,serif;">🇵🇱 Weekly Debrief: Poland</h1>
        <p style="margin:0;font-size:13px;color:#888;">{week_range}</p>
      </td></tr>

      <!-- Top headlines summary -->
      <tr><td style="padding:24px 36px 0;border-bottom:2px solid #f0ebe3;">
        <p style="margin:0 0 14px;font-size:11px;font-weight:bold;color:#b0956a;
                  letter-spacing:1.2px;text-transform:uppercase;">This week</p>
        <table width="100%" cellpadding="0" cellspacing="0">
          {headlines_html}
        </table>
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
          Generated by Weekly Debrief: Poland · {datetime.now().strftime("%B %d, %Y")}
        </p>
      </td></tr>

    </table>
  </td></tr>
</table>
</body></html>"""


# ── Email Sending ──────────────────────────────────────────────────────────────

STORY_TYPE_LABELS = {
    "national":      "National",
    "international": "International",
    "us-poland":     "US – Poland",
    "regional":      "Regional",
}

def render_substack_html(newsletter: dict) -> str:
    """
    Render the newsletter as HTML suitable for copy-paste into Substack.
    Uses real HTML tags so Gmail's clipboard carries rich formatting —
    headings, bold, italics, and dividers all paste correctly in the editor.
    """
    week_range = newsletter.get("week_range", "")
    stories    = sorted(newsletter.get("stories", []), key=lambda s: s.get("rank", 99))
    parts      = []

    parts.append(f"<h1>\U0001f1f5\U0001f1f1 Weekly Debrief: Poland</h1>")
    parts.append(f"<h3>{week_range}</h3>")
    parts.append("<hr>")

    parts.append("<h2>This Week</h2>")
    for story in stories:
        rank  = story.get("rank", "")
        stype = STORY_TYPE_LABELS.get(story.get("story_type", ""), "")
        parts.append(f"<p><strong>#{rank}</strong> &nbsp; [<em>{stype}</em>] &nbsp; {story['headline']}</p>")
    parts.append("<hr>")

    for story in stories:
        rank  = story.get("rank", "")
        stype = STORY_TYPE_LABELS.get(story.get("story_type", ""), "")

        parts.append(f"<h2>#{rank} &middot; {story['headline']}</h2>")
        parts.append(f"<p>[<em>{stype}</em>]</p>")

        parts.append("<p><strong>What happened</strong></p>")
        parts.append(f"<p>{story['what_happened']}</p>")

        parts.append("<p><strong>Why it matters</strong></p>")
        parts.append(f"<p>{story['why_it_matters']}</p>")

        parts.append("<p><strong>Sentiment &amp; reaction</strong></p>")
        parts.append(f"<p>{story['sentiment_and_reaction']}</p>")

        parts.append(f"<p><em>Source: <a href=\"{story['url']}\">{story['source']}</a> &middot; {story['bias']}</em></p>")
        parts.append("<hr>")

    parts.append("<p><em>Sources: Gazeta Wyborcza &middot; Rzeczpospolita &middot; Onet.pl &middot; TVN24 &middot; Polsat News &middot; Tygodnik Powszechny &middot; Do Rzeczy &middot; Interia &middot; WP &middot; Bankier.pl</em></p>")
    parts.append(f"<p><em>Generated {datetime.now().strftime('%B %d, %Y')}</em></p>")

    return "\n".join(parts)


def send_email(html_body: str, substack_html: str, week_range: str):
    """
    Send the newsletter to all recipients via Gmail SMTP.
    The Substack section is rendered as real HTML so copying and pasting
    into Substack's editor preserves headings, bold, and dividers.
    """
    substack_block = f"""
<div style="margin:40px auto;max-width:620px;padding:28px 32px;
            border-top:3px solid #e8e0d5;font-family:Georgia,serif;">
  <p style="margin:0 0 20px;font-size:12px;font-weight:bold;color:#999;
             letter-spacing:1px;text-transform:uppercase;font-family:Helvetica,Arial,sans-serif;">
    📋 Substack version &mdash; select all text below this line and paste into the editor
  </p>
  {substack_html}
</div>"""

    full_html = html_body.replace("</body>", substack_block + "</body>")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🇵🇱 Weekly Debrief: Poland — {week_range}"
    msg["From"]    = GMAIL_USER
    msg["To"]      = ", ".join(RECIPIENTS)
    msg.attach(MIMEText(full_html, "html", "utf-8"))

    log.info(f"Sending email to: {', '.join(RECIPIENTS)}")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, RECIPIENTS, msg.as_string())
    log.info(f"Email sent successfully to {len(RECIPIENTS)} recipient(s).")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    log.info("=== Weekly Debrief: Poland — Agent starting ===")

    articles   = collect_all_articles()
    if not articles:
        log.error("No articles collected. Aborting.")
        return

    newsletter    = summarize_with_claude(articles)
    html          = render_html_email(newsletter)
    substack_html = render_substack_html(newsletter)
    send_email(html, substack_html, newsletter.get("week_range", "This Week"))

    log.info("=== Done ===")


if __name__ == "__main__":
    main()
