"""
JLG Executive Job Hunt Agent
─────────────────────────────
Runs daily via GitHub Actions at 07:00 Madrid time.
Searches multiple sources, scores against CV, saves to Supabase,
and sends Telegram alerts for high-score matches.

Usage:
    python agent.py              # full run
    python agent.py --dry-run    # score and print, don't save
    python agent.py --test       # send test Telegram message
"""

import sys
import logging
import argparse
from datetime import datetime

from scraper  import fetch_all_jobs
from scorer   import score_jobs_batch
from database import get_seen_urls, save_job, get_all_jobs
from notifier import notify_new_job, notify_daily_summary, send_message
from config   import SCORE_ALERT_THRESHOLD, SCORE_ARCHIVE_THRESHOLD

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt = "%Y-%m-%d %H:%M:%S",
    handlers= [logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


# ── Main run ──────────────────────────────────────────────────────────────────

def run(dry_run: bool = False) -> None:
    start = datetime.now()
    logger.info("=" * 60)
    logger.info("JLG Executive Job Hunt Agent — starting run")
    logger.info(f"Mode: {'DRY RUN (no saves)' if dry_run else 'LIVE'}")
    logger.info("=" * 60)

    # 1. Get all URLs already in the database (deduplication)
    seen_urls = get_seen_urls() if not dry_run else set()
    logger.info(f"Existing jobs in pipeline: {len(seen_urls)}")

    # 2. Scrape all sources
    raw_jobs = fetch_all_jobs()
    logger.info(f"Raw jobs fetched: {len(raw_jobs)}")

    # 3. Filter out already-seen jobs
    new_raw = [j for j in raw_jobs if j.get("url", "") not in seen_urls]
    logger.info(f"New (unseen) jobs to score: {len(new_raw)}")

    if not new_raw:
        logger.info("No new jobs found. Sending summary and exiting.")
        total = len(get_all_jobs()) if not dry_run else 0
        notify_daily_summary([], total)
        return

    # 4. Score all new jobs via Claude
    scored_jobs = score_jobs_batch(new_raw)

    # 5. Separate by threshold
    to_save    = [j for j in scored_jobs if j["score"] >= SCORE_ARCHIVE_THRESHOLD]
    archived   = [j for j in scored_jobs if j["score"] <  SCORE_ARCHIVE_THRESHOLD]
    alertable  = [j for j in to_save    if j["score"] >= SCORE_ALERT_THRESHOLD]

    logger.info(f"Scored: {len(scored_jobs)} total")
    logger.info(f"  ≥{SCORE_ARCHIVE_THRESHOLD} (save):  {len(to_save)}")
    logger.info(f"  <{SCORE_ARCHIVE_THRESHOLD} (archive): {len(archived)}")
    logger.info(f"  ≥{SCORE_ALERT_THRESHOLD} (alert):  {len(alertable)}")

    # 6. Save to Supabase
    saved_count = 0
    if not dry_run:
        for job in to_save:
            if save_job(job):
                saved_count += 1
        logger.info(f"Saved {saved_count}/{len(to_save)} jobs to Supabase")
    else:
        _print_dry_run_summary(scored_jobs)

    # 7. Send Telegram alerts for high-score individual matches
    if not dry_run:
        # Sort by score descending, alert for each individually
        for job in sorted(alertable, key=lambda j: j["score"], reverse=True):
            notify_new_job(job)

        # Daily summary
        total_pipeline = len(get_all_jobs())
        notify_daily_summary(alertable, total_pipeline)

    elapsed = (datetime.now() - start).seconds
    logger.info(f"Run complete in {elapsed}s — {saved_count} new roles saved")
    logger.info("=" * 60)


def _print_dry_run_summary(jobs: list) -> None:
    """Pretty-print scoring results for dry run mode."""
    print("\n" + "=" * 70)
    print(f"DRY RUN RESULTS — {len(jobs)} jobs scored")
    print("=" * 70)
    for job in sorted(jobs, key=lambda j: j["score"], reverse=True)[:20]:
        score  = job["score"]
        flag   = "🔴" if score >= 85 else "🟡" if score >= 70 else "⚪"
        print(f"\n{flag} {score:3d}/100  {job['title']}")
        print(f"          {job['company']} — {job.get('geography', '')}")
        print(f"          CV: {job.get('cvVersion', '')}  |  {job.get('scoringRationale', '')}")
    print("=" * 70 + "\n")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="JLG Executive Job Hunt Agent")
    parser.add_argument("--dry-run", action="store_true", help="Score jobs but don't save to DB or send alerts")
    parser.add_argument("--test",    action="store_true", help="Send a test Telegram message and exit")
    args = parser.parse_args()

    if args.test:
        ok = send_message("✅ JLG Job Hunt Agent — test message. Connection working.")
        print("Telegram test:", "OK" if ok else "FAILED — check TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
        return

    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
