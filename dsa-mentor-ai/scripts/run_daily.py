"""CLI runner for the daily recommendation & notification job."""

import sys
from pathlib import Path

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import argparse
from app.scheduler_job import run_daily_pipeline
from app.config import logger


def main():
    parser = argparse.ArgumentParser(description="Run the daily DSA Mentor AI recommendation pipeline.")
    parser.add_argument("--date", default=None, help="Target date (YYYY-MM-DD), defaults to today in Asia/Kolkata")
    parser.add_argument("--db", default=None, help="Custom SQLite database path")
    parser.add_argument("--no-sync", action="store_true", help="Skip LeetCode network synchronization")
    parser.add_argument("--no-telegram", action="store_true", help="Skip Telegram notification dispatch")
    parser.add_argument("--force-refresh", action="store_true", help="Force recalculate recommendation for the date")
    args = parser.parse_args()

    result = run_daily_pipeline(
        target_date=args.date,
        db_path=args.db,
        sync_online=not args.no_sync,
        dispatch_telegram=not args.no_telegram,
        force_refresh=args.force_refresh,
    )

    if result.get("status") == "success":
        logger.info("Daily pipeline completed successfully.")
        sys.exit(0)
    elif result.get("status") == "no_candidates":
        logger.warning(f"Pipeline stopped: {result.get('recommendation', {}).get('reason')}")
        sys.exit(0)
    else:
        logger.error(f"Pipeline failed: {result}")
        sys.exit(1)


if __name__ == "__main__":
    main()
