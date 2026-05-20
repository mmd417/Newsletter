# 🇵🇱 Polish Press Weekly — Newsletter Agent

A scheduled GitHub Actions agent that scrapes Polish news outlets, summarizes the week's top stories using Claude, and emails you a clean digest every Sunday evening.

---

## What It Does

- Pulls articles from **Gazeta Wyborcza, Rzeczpospolita, Onet.pl, TVN24, Polsat News**
- Uses **Claude** to filter noise, rank importance, and write English summaries
- Labels each story with the outlet's **political bias** (center-left, center-right, centrist, etc.)
- Flags **framing divergences** when the same story is spun differently across outlets
- Delivers a styled HTML email every **Sunday at ~6 PM Chicago time**

---

## Repo Structure

```
├── newsletter.py                        # Main agent script
├── requirements.txt                     # Python dependencies
├── .github/
│   └── workflows/
│       └── weekly_newsletter.yml        # GitHub Actions cron schedule
└── README.md
```

---

## Setup

### 1. Create a private GitHub repository

Push this folder to a **private** repo (keeps your secrets safe).

```bash
git init
git remote add origin https://github.com/YOUR_USERNAME/polish-news-agent.git
git add .
git commit -m "Initial commit"
git push -u origin main
```

### 2. Add GitHub Secrets

Go to your repo → **Settings → Secrets and variables → Actions → New repository secret**

| Secret name | Value |
|---|---|
| `ANTHROPIC_API_KEY` | Your Anthropic API key (from console.anthropic.com) |
| `GMAIL_USER` | Your Gmail address (e.g. `matt@gmail.com`) |
| `GMAIL_APP_PASSWORD` | A Gmail App Password (see below) |
| `RECIPIENT_EMAIL` | Where to send the newsletter (can be same as GMAIL_USER) |
| `GW_COOKIES` | *(Optional)* Gazeta Wyborcza session cookies as JSON (see below) |

### 3. Create a Gmail App Password

Google requires an App Password (not your regular password) for SMTP access:

1. Go to [myaccount.google.com/security](https://myaccount.google.com/security)
2. Enable **2-Step Verification** if not already on
3. Search for **"App passwords"**
4. Create one named "Polish Press Newsletter"
5. Copy the 16-character password → paste as `GMAIL_APP_PASSWORD` secret

### 4. (Optional) Add Gazeta Wyborcza Cookies

If you're a Gazeta Wyborcza subscriber and want full article access:

1. Log in to wyborcza.pl in Chrome
2. Open DevTools → Application → Cookies → `wyborcza.pl`
3. Export as a JSON array in this format:
```json
[
  {"name": "piano_id", "value": "YOUR_VALUE", "domain": ".wyborcza.pl"},
  {"name": "sessionid", "value": "YOUR_VALUE", "domain": ".wyborcza.pl"}
]
```
4. Paste the JSON string as the `GW_COOKIES` secret

If you skip this, the agent falls back to the free RSS feed for Gazeta Wyborcza.

### 5. Test Manually

Once secrets are saved, go to **Actions → Polish Press Weekly Newsletter → Run workflow** to trigger a test run without waiting for Sunday.

---

## Timing

The workflow runs every **Sunday at 23:00 UTC**, which is:
- **6:00 PM CDT** (Chicago, summer)
- **5:00 PM CST** (Chicago, winter)

To adjust, edit the cron line in `.github/workflows/weekly_newsletter.yml`:
```yaml
- cron: "0 23 * * 0"   # minute hour day-of-month month day-of-week
```

---

## Outlet Bias Labels

| Outlet | Bias |
|---|---|
| Gazeta Wyborcza | center-left / liberal |
| Rzeczpospolita | center-right / conservative |
| Onet.pl | centrist |
| TVN24 | center-left / liberal |
| Polsat News | centrist / populist |

These reflect broad editorial positions. Individual articles may differ. The agent will flag stories where outlets with opposing biases frame the same event differently.

---

## Customization

**Change topics or add outlets:** Edit the `OUTLETS` list and `SYSTEM_PROMPT` in `newsletter.py`.

**Change delivery day/time:** Edit the `cron` schedule in the workflow YAML.

**Change number of stories:** Edit the `8–12` range in the system prompt.

**Add more paywall outlets:** Add a new entry to `OUTLETS` with `"paywall": True` and a `"cookie_env"` pointing to a new GitHub Secret.
