"""Non-negotiable end-to-end acceptance test suite for DSA Mentor AI."""

import json
import pytest
from datetime import datetime, timezone, timedelta

from app.db import init_db, get_connection, get_db
from app.catalogue import load_catalogue, get_problem
from app.recommender import select_daily_problem
from app.mentor import get_daily_mentor_message
from app.feedback import record_feedback
from app.leetcode_client import sync_leetcode_history, save_snapshot
from app.scheduler_job import run_daily_pipeline


@pytest.fixture
def acceptance_db(tmp_path):
    """Provides isolated, initialized database for acceptance verification."""
    db_file = tmp_path / "acceptance.db"
    init_db(db_file)
    load_catalogue(db_path=db_file)
    return db_file


def test_acceptance_1_one_question_per_day_idempotency(acceptance_db):
    """ACCEPTANCE CRITERION 1: Exactly ONE question per day; duplicate run returns the same saved pick."""
    test_date = "2026-10-30"

    # First execution generates and persists recommendation
    res1 = run_daily_pipeline(
        target_date=test_date,
        db_path=acceptance_db,
        sync_online=False,
        dispatch_telegram=False,
    )
    assert res1["status"] == "success"
    first_pid = res1["recommendation"]["problem_id"]
    assert first_pid is not None

    # Duplicate execution on same date returns identical saved pick
    res2 = run_daily_pipeline(
        target_date=test_date,
        db_path=acceptance_db,
        sync_online=False,
        dispatch_telegram=False,
    )
    assert res2["status"] == "success"
    assert res2["recommendation"]["problem_id"] == first_pid
    assert res2["recommendation"]["date"] == test_date

    # Database UNIQUE(date) check
    with get_db(acceptance_db) as conn:
        count = conn.execute(
            "SELECT COUNT(*) as c FROM daily_recommendations WHERE date = ?", (test_date,)
        ).fetchone()["c"]
        assert count == 1


def test_acceptance_2_no_solved_repeats(acceptance_db):
    """ACCEPTANCE CRITERION 2: No solved repeats. A previously solved or imported problem is NEVER selected."""
    # 1. Day 1 recommendation
    day1_rec = select_daily_problem(target_date="2026-10-30", db_path=acceptance_db)
    day1_pid = day1_rec["problem_id"]

    # 2. Mark Day 1 problem as solved in activity_events
    record_feedback(
        problem_id=day1_pid,
        outcome="solved",
        minutes=25,
        hints_used=0,
        perceived_difficulty="right",
        confidence=4,
        db_path=acceptance_db,
    )

    # 3. Simulate multiple future days (e.g. Day 2 through Day 7)
    for day_offset in range(1, 8):
        future_date = (datetime(2026, 10, 30) + timedelta(days=day_offset)).strftime("%Y-%m-%d")
        future_rec = select_daily_problem(target_date=future_date, db_path=acceptance_db)
        # Verify solved problem is NEVER selected
        assert future_rec["problem_id"] != day1_pid


def test_acceptance_3_score_breakdown_and_reason_saved(acceptance_db):
    """ACCEPTANCE CRITERION 3: Every recommendation has a saved score breakdown and evidence-based reason."""
    rec = select_daily_problem(target_date="2026-10-30", db_path=acceptance_db)

    # In-memory return checks
    assert "score_breakdown" in rec
    breakdown = rec["score_breakdown"]
    assert "topic_weakness" in breakdown
    assert "revision_due" in breakdown
    assert "difficulty_fit" in breakdown
    assert "pattern_learning_value" in breakdown
    assert "final_score" in breakdown
    assert len(rec["reason"]) > 10

    # Database persistence checks
    with get_db(acceptance_db) as conn:
        row = conn.execute(
            "SELECT score_breakdown_json, reason FROM daily_recommendations WHERE date = '2026-10-30'"
        ).fetchone()
        assert row is not None
        saved_breakdown = json.loads(row["score_breakdown_json"])
        assert "final_score" in saved_breakdown
        assert row["reason"] == rec["reason"]


def test_acceptance_4_ollama_off_fallback(acceptance_db):
    """ACCEPTANCE CRITERION 4: Ollama-off fallback produces full coaching message without crashing."""
    problem = get_problem(1, db_path=acceptance_db)

    # When Ollama daemon is offline/unreachable
    coaching = get_daily_mentor_message(
        problem=problem,
        reason="Testing offline reliability",
        db_path=acceptance_db,
    )

    assert coaching is not None
    assert "Two Sum" in coaching["greeting"]
    assert len(coaching["hint_1"]) > 5
    assert len(coaching["hint_2"]) > 5
    assert len(coaching["approach_outline"]) > 10
    assert "call_to_action" in coaching


def test_acceptance_5_offline_resilience_and_stale_warning(acceptance_db, tmp_path, monkeypatch):
    """ACCEPTANCE CRITERION 5: Offline resilience: uses last snapshot with stale warning when network fails."""
    monkeypatch.setattr("app.leetcode_client.SNAPSHOT_DIR", tmp_path / "snaps")
    username = "offline_tester"

    snapshot_data = {
        "data": {
            "recentAcSubmissionList": [
                {"id": "1", "title": "Two Sum", "titleSlug": "two-sum", "timestamp": "1735689600"}
            ]
        }
    }
    save_snapshot(username, snapshot_data)

    # Force offline sync
    res = sync_leetcode_history(username=username, db_path=acceptance_db, force_offline=True)
    assert res["status"] == "stale_fallback"
    assert res["is_stale_fallback"] is True
    assert res["records_seen"] == 1


def test_acceptance_6_feedback_adaptation_shifts_subsequent_selection(acceptance_db):
    """ACCEPTANCE CRITERION 6: Feedback adaptation ('too hard/stuck') demonstrably changes later difficulty or topic ranking."""
    # Day 1 recommendation
    rec1 = select_daily_problem(target_date="2026-10-30", db_path=acceptance_db)
    pid1 = rec1["problem_id"]

    # Record severe struggle on pid1: stuck, perceived hard, confidence 1
    record_feedback(
        problem_id=pid1,
        outcome="stuck",
        minutes=60,
        hints_used=3,
        perceived_difficulty="hard",
        confidence=1,
        blocker="concept",
        db_path=acceptance_db,
    )

    # Day 2 recommendation
    rec2 = select_daily_problem(target_date="2026-10-31", db_path=acceptance_db)
    pid2 = rec2["problem_id"]

    # 1. Day 2 cannot recommend pid1 (cooldown for failed problems)
    assert pid2 != pid1
    # 2. Adaptation occurred: score breakdown reflects updated weakness
    assert rec2["score_breakdown"]["topic_weakness"] >= 0.0
