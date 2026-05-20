# 🇵🇱 Weekly Debrief: Poland

A scheduled newsletter that reads the Polish press so you don't have to. Every Sunday evening it pulls articles from across Poland's political media spectrum, uses Claude AI to curate the week's most important stories, and delivers a clean digest to your inbox — written for readers who follow international affairs but don't have deep background on Polish politics or institutions.

---

## What It Does

- Pulls articles from **10 Polish outlets** spanning the full political spectrum (see outlet list below)
- Collects **public sentiment signals** from Reddit (r/poland, r/Polska) and Wykop (Poland's Reddit equivalent)
- Uses **Claude AI** to select only the 4–6 stories that genuinely matter — no filler
- Writes each story in three sections: **What Happened / Why It Matters / Sentiment & Reaction**
- Provides **background context** for non-Polish readers (explains parties, institutions, historical conflicts on first reference)
- Flags **framing divergences** when left- and right-leaning outlets cover the same event differently
- Delivers a styled HTML email every **Sunday at ~6 PM Chicago time**

---

## Story Format

Each story in the newsletter follows a consistent three-part structure:

**What Happened** — A crisp headline and 2-sentence factual description: who, what, when, where.

**Why It Matters** — Context and significance. Explains any Polish-specific background a non-expert needs, then explains why the development matters beyond Poland's borders.

**Sentiment & Reaction** — How the story is landing: public mood, political reactions from named figures, social media signals from Reddit/Wykop, and explicit framing comparisons between left- and right-leaning outlets where relevant.

---

## Outlet Coverage

| Outlet | Bias | Notes |
|---|---|---|
| Gazeta Wyborcza | Center-left / liberal | Poland's largest broadsheet |
| TVN24 | Center-left / liberal | Leading TV news channel |
| Tygodnik Powszechny | Catholic liberal | Oldest and most respected weekly magazine |
| Onet.pl | Centrist | High-traffic news portal |
| WP Wiadomości | Centrist | Largest Polish web portal by traffic |
| Interia Fakty | Centrist | Major news aggregator |
| Polsat News | Centrist / populist | Large commercial TV network |
| Rzeczpospolita | Center-right / conservative | Leading center-right daily |
| Do Rzeczy | Right-wing / national-conservative | Flagship voice of the PiS/nationalist camp |
| Bankier.pl | Business / financial | Primary source for economic stories |

Bias labels reflect broad editorial positions — individual articles may vary. The newsletter flags stories where outlets on opposing ends of the spectrum frame the same event differently.

---

## Repo Structure

```
├── newsletter.py          # Main pipeline: fetch → summarize → email
├── preview_run.py         # Local test runner — generates HTML, skips email
├── requirements.txt       # Python dependencies
├── weekly_newsletter.yml  # GitHub Actions cron schedule (runs every Sunday)
└── README.md
```

---

## Setup

### 1. Add GitHub Secrets

Go to your repo → **Settings → Secrets and variables → Actions → New repository secret**

| Secret | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | ✅ | From [console.anthropic.com](https://console.anthropic.com/settings/api-keys) |
| `GMAIL_USER` | ✅ | Your Gmail address |
| `GMAIL_APP_PASSWORD` | ✅ | Gmail App Password (see below) |
| `RECIPIENT_EMAIL` | ✅ | Where to send the newsletter |
| `GW_COOKIES` | Optional | Gazeta Wyborcza session cookies for full article access |

### 2. Create a Gmail App Password

Google requires an App Password (not your regular password) for SMTP access:

1. Go to [myaccount.google.com/security](https://myaccount.google.com/security)
2. Enable **2-Step Verification** if not already on
3. Search for **"App passwords"**
4. Create one named "Weekly Debrief Poland"
5. Copy the 16-character password → paste as the `GMAIL_APP_PASSWORD` secret

### 3. (Optional) Add Gazeta Wyborcza Cookies

If you're a Gazeta Wyborcza subscriber and want full article text (not just RSS headlines):

1. Log in to wyborcza.pl in Chrome
2. Open DevTools → Application → Cookies → `wyborcza.pl`
3. Export the relevant cookies as a JSON array:
```json
[
  {"name": "piano_id", "value": "YOUR_VALUE", "domain": ".wyborcza.pl"},
  {"name": "sessionid", "value": "YOUR_VALUE", "domain": ".wyborcza.pl"}
]
```
4. Paste the JSON string as the `GW_COOKIES` secret

Without cookies, the agent uses the public RSS feed, which provides headlines and summaries.

### 4. Test Locally (No Email)

Run `preview_run.py` to generate and inspect the newsletter as an HTML file before sending:

```bash
cd newsletter-project
ANTHROPIC_API_KEY="sk-ant-..." python3 preview_run.py
```

Opens `newsletter_preview.html` — review it in any browser.

### 5. Trigger a Test Send

Once secrets are saved, go to **Actions → Weekly Debrief Poland → Run workflow** to trigger a full run (including email) without waiting for Sunday.

---

## Schedule

The workflow runs every **Sunday at 23:00 UTC**:
- **6:00 PM CDT** (Chicago, summer)
- **5:00 PM CST** (Chicago, winter)

To change the time, edit the cron line in `weekly_newsletter.yml`:
```yaml
- cron: "0 23 * * 0"   # minute hour day-of-month month day-of-week
```

---

## Customization

| What | Where |
|---|---|
| Add or remove outlets | Edit the `OUTLETS` list in `newsletter.py` |
| Change story count | Edit `4–6` in the `SYSTEM_PROMPT` in `newsletter.py` |
| Change delivery day/time | Edit the `cron` line in `weekly_newsletter.yml` |
| Add Twitter/X signals | Replace `fetch_social_media_signals()` with X API v2 calls using `TWITTER_BEARER_TOKEN` |
