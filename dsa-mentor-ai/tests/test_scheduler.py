import pytest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from app.db import init_db, get_connection
from app.catalogue import load_catalogue
from app.recommender import get_current_date_in_tz
from app.scheduler_job import run_daily_pipeline
from app.notifier import format_daily_message, send_telegram_message


@pytest.fixture
def scheduler_db(tmp_path):
    db_file = tmp_path / "test_sched.db"
    init_db(db_file)
    load_catalogue(db_path=db_file)
    return db_file


def test_timezone_boundary():
    # User in Asia/Kolkata (+05:30)
    kolkata_date = get_current_date_in_tz("Asia/Kolkata")
    utc_date = get_current_date_in_tz("UTC")
    # Date format must be YYYY-MM-DD
    assert len(kolkata_date) == 10
    assert len(utc_date) == 10


def test_failed_sync_never_blocks_daily_run(scheduler_db, monkeypatch):
    """
    DoD Test: Even if LeetCode GraphQL sync throws network or schema errors,
    the daily recommendation pipeline MUST proceed to select a problem and produce coaching.
    """
    def mock_broken_sync(*args, **kwargs):
        raise ConnectionError("LeetCode GraphQL endpoint completely unreachable")

    monkeypatch.setattr("app.scheduler_job.sync_leetcode_history", mock_broken_sync)

    result = run_daily_pipeline(
        target_date="2026-10-30",
        db_path=scheduler_db,
        sync_online=True,
        dispatch_telegram=False,
    )

    assert result["status"] == "success"
    assert result["sync"]["status"] == "error_bypassed"
    assert result["recommendation"]["problem_id"] is not None
    assert "coaching" in result
    assert result["notification"]["terminal_delivered"] is True


def test_duplicate_run_same_date_is_idempotent(scheduler_db):
    target_date = "2026-10-30"

    # Run 1
    res1 = run_daily_pipeline(
        target_date=target_date,
        db_path=scheduler_db,
        sync_online=False,
        dispatch_telegram=False,
    )

    # Run 2
    res2 = run_daily_pipeline(
        target_date=target_date,
        db_path=scheduler_db,
        sync_online=False,
        dispatch_telegram=False,
    )

    assert res1["status"] == "success"
    assert res2["status"] == "success"
    # Exactly same problem recommended
    assert res1["recommendation"]["problem_id"] == res2["recommendation"]["problem_id"]
    assert res1["recommendation"]["date"] == res2["recommendation"]["date"]


def test_format_daily_message_structure():
    rec = {
        "problem_id": 1,
        "title": "Two Sum",
        "difficulty": "Easy",
        "url": "https://leetcode.com/problems/two-sum/",
        "topics": ["Array", "Hash Table"],
        "date": "2026-10-30",
        "reason": "Targeting core lookup patterns",
    }
    coaching = {
        "why_selected": "Targeting core lookup patterns",
        "learning_target": "O(N) Hash Table mapping",
        "hint_1": "Store visited elements in a map",
        "hint_2": "Look up target - current",
        "approach_outline": "1. Init map\n2. Iterate array\n3. Check complement",
    }
    msg = format_daily_message(rec, coaching)
    assert "Two Sum" in msg
    assert "https://leetcode.com/problems/two-sum/" in msg
    assert "PROGRESSIVE HINT LADDER" in msg
    assert "Hint 1" in msg
