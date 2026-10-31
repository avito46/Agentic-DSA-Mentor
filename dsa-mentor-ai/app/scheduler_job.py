"""Daily scheduled workflow execution engine."""

import time
from pathlib import Path
from typing import Dict, Any, Optional

from app.db import init_db
from app.catalogue import load_catalogue
from app.leetcode_client import sync_leetcode_history
from app.recommender import select_daily_problem, get_current_date_in_tz
from app.mentor import get_daily_mentor_message
from app.notifier import notify_daily_problem
from app.config import logger


def run_daily_pipeline(
    target_date: Optional[str] = None,
    db_path: Optional[Path] = None,
    sync_online: bool = True,
    dispatch_telegram: bool = True,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """
    Executes the complete daily workflow:
    1. Ensures DB and catalogue are initialized.
    2. Syncs LeetCode history (sync failure NEVER blocks daily run).
    3. Selects exactly ONE unsolved problem for target_date (idempotent).
    4. Generates mentoring message & hint ladder (with offline fallback).
    5. Dispatches notification to terminal and Telegram.
    """
    date_str = target_date or get_current_date_in_tz()
    logger.info(f"=== Starting Daily DSA Mentor Pipeline for {date_str} ===")

    # Step 1: Initialize database & load catalogue if needed
    init_db(db_path)
    try:
        load_catalogue(db_path=db_path)
    except Exception as e:
        logger.warning(f"Catalogue load notice: {e}")

    # Step 2: Attempt LeetCode sync (Failure NEVER blocks the daily run)
    sync_result = {"status": "skipped"}
    if sync_online:
        try:
            logger.info("Syncing LeetCode history...")
            sync_result = sync_leetcode_history(db_path=db_path)
        except Exception as e:
            logger.warning(f"LeetCode sync encountered an error but will not block daily run: {e}")
            sync_result = {"status": "error_bypassed", "error": str(e)}

    # Step 3: Select daily problem (Deterministic & Idempotent per date)
    recommendation = select_daily_problem(
        target_date=date_str,
        db_path=db_path,
        force_refresh=force_refresh,
    )

    if recommendation.get("status") == "no_candidates":
        logger.warning(f"No candidates available: {recommendation.get('reason')}")
        return {
            "status": "no_candidates",
            "date": date_str,
            "sync": sync_result,
            "recommendation": recommendation,
        }

    # Step 4: Generate coaching message & hint ladder (with deterministic template fallback)
    problem_meta = {
        "problem_id": recommendation["problem_id"],
        "title": recommendation["title"],
        "slug": recommendation["slug"],
        "url": recommendation["url"],
        "difficulty": recommendation["difficulty"],
        "topics": recommendation["topics"],
    }
    coaching = get_daily_mentor_message(
        problem=problem_meta,
        reason=recommendation["reason"],
        db_path=db_path,
    )

    # Step 5: Deliver notification with retry
    notify_result = None
    for attempt in range(1, 4):
        try:
            notify_result = notify_daily_problem(
                recommendation=recommendation,
                coaching=coaching,
                dispatch_telegram=dispatch_telegram,
            )
            break
        except Exception as e:
            logger.warning(f"Notification attempt {attempt}/3 failed: {e}")
            time.sleep(1.5 * attempt)

    logger.info(f"=== Finished Daily Pipeline for {date_str} ===")

    return {
        "status": "success",
        "date": date_str,
        "sync": sync_result,
        "recommendation": recommendation,
        "coaching": coaching,
        "notification": notify_result,
    }
