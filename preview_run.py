#!/usr/bin/env python3
"""
Preview runner — collects articles and generates the newsletter HTML locally.
Does NOT send any email. Output saved to newsletter_preview.html and newsletter_preview.json.

Usage:
    ANTHROPIC_API_KEY=sk-ant-... python3 preview_run.py
"""

import json
import logging
import os
import time
from datetime import datetime

# Stub out email env vars so newsletter.py can be imported without them
os.environ.setdefault("GMAIL_USER", "preview@example.com")
os.environ.setdefault("GMAIL_APP_PASSWORD", "preview")

from newsletter import (
    collect_all_articles,
    summarize_with_claude,
    render_html_email,
    OUTLETS,
    log,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

def main():
    log.info("=== Polish Press Weekly — Preview Run (no email) ===")

    # ── Step 1: Collect articles ───────────────────────────────────────────────
    articles = collect_all_articles()

    # Per-outlet summary for the run report
    outlet_counts = {o["name"]: 0 for o in OUTLETS}
    for a in articles:
        if a["outlet"] in outlet_counts:
            outlet_counts[a["outlet"]] += 1

    zero_outlets = [name for name, count in outlet_counts.items() if count == 0]

    if not articles:
        log.error("No articles collected from any outlet. Aborting.")
        return

    # ── Step 2: Summarize with Claude (one retry on failure) ──────────────────
    newsletter = None
    for attempt in range(1, 3):
        try:
            newsletter = summarize_with_claude(articles)
            break
        except Exception as e:
            log.error(f"Claude API call failed (attempt {attempt}): {e}")
            if attempt == 1:
                log.info("Retrying in 30 seconds...")
                time.sleep(30)
            else:
                log.error("Claude API failed after retry. Aborting.")
                return

    # ── Step 3: Render HTML ────────────────────────────────────────────────────
    html = render_html_email(newsletter)

    # Count included stories
    included = sum(len(s.get("stories", [])) for s in newsletter.get("sections", []))

    # ── Step 4: Save outputs ──────────────────────────────────────────────────
    html_path  = "newsletter_preview.html"
    json_path  = "newsletter_preview.json"

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(newsletter, f, ensure_ascii=False, indent=2)

    log.info(f"HTML saved → {html_path}")
    log.info(f"JSON saved → {json_path}")

    # ── Run summary ────────────────────────────────────────────────────────────
    week_range = newsletter.get("week_range", "unknown")
    zero_note  = (f" Outlets with zero articles: {', '.join(zero_outlets)}." if zero_outlets else "")

    print("\n" + "="*70)
    print("RUN SUMMARY")
    print("="*70)
    print(f"  Date/time  : {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Week range : {week_range}")
    print(f"  Collected  : {len(articles)} articles across {len(outlet_counts)} outlets")
    for name, count in outlet_counts.items():
        flag = " ⚠️  ZERO" if count == 0 else ""
        print(f"               {name}: {count}{flag}")
    print(f"  Included   : {included} stories in final newsletter")
    print(f"  Email      : NOT sent (preview mode)")
    print(f"  Output     : {html_path} / {json_path}")
    print(f"  Status     : ✅ SUCCESS{zero_note}")
    print("="*70 + "\n")


if __name__ == "__main__":
    main()
