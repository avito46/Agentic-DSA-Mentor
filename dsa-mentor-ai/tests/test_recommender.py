import pytest
import json
from datetime import datetime, timezone, timedelta

from app.db import init_db, get_connection
from app.catalogue import load_catalogue
from app.recommender import select_daily_problem, compute_stable_tie_break


@pytest.fixture
def recommender_db(tmp_path):
    db_file = tmp_path / "test_rec.db"
    init_db(db_file)
    load_catalogue(db_path=db_file)
    return db_file


def test_reproducible_selection_and_idempotency(recommender_db):
    target_date = "2026-10-30"

    # First run generates and persists recommendation
    rec1 = select_daily_problem(target_date=target_date, db_path=recommender_db)
    assert rec1["problem_id"] is not None
    assert rec1["date"] == target_date
    assert "score_breakdown" in rec1
    assert rec1["score_breakdown"]["final_score"] == rec1["score"]

    # Second run for the SAME date must return the EXACT same problem (idempotent)
    rec2 = select_daily_problem(target_date=target_date, db_path=recommender_db)
    assert rec2["problem_id"] == rec1["problem_id"]
    assert rec2["score"] == rec1["score"]
    assert rec2["generated_at"] == rec1["generated_at"]


def test_solved_problems_never_selected(recommender_db):
    target_date = "2026-10-31"

    # Suppose problem 1 (Two Sum) was recommended
    rec = select_daily_problem(target_date=target_date, db_path=recommender_db)
    chosen_id = rec["problem_id"]

    # Now mark chosen_id as solved in activity_events
    conn = get_connection(recommender_db)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO activity_events (problem_id, event_type, occurred_at, source) VALUES (?, 'solved', ?, 'manual_feedback')",
        (chosen_id, now),
    )
    conn.commit()
    conn.close()

    # Next day recommendation must NEVER pick chosen_id
    next_date = "2026-11-01"
    rec_next = select_daily_problem(target_date=next_date, db_path=recommender_db)
    assert rec_next["problem_id"] != chosen_id


def test_cooldown_excludes_recently_skipped_problem(recommender_db):
    # Get recommendation for today
    rec = select_daily_problem(target_date="2026-10-30", db_path=recommender_db)
    pid = rec["problem_id"]

    # Mark as skipped today
    conn = get_connection(recommender_db)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO activity_events (problem_id, event_type, occurred_at, source) VALUES (?, 'skipped', ?, 'manual_feedback')",
        (pid, now),
    )
    conn.commit()
    conn.close()

    # Tomorrow's pick should exclude pid due to cooldown
    rec_tomorrow = select_daily_problem(target_date="2026-10-31", db_path=recommender_db)
    assert rec_tomorrow["problem_id"] != pid


def test_empty_candidate_pool_graceful_handling(tmp_path):
    # Create empty database with no problems
    empty_db = tmp_path / "empty.db"
    init_db(empty_db)

    result = select_daily_problem(target_date="2026-10-30", db_path=empty_db)
    assert result["status"] == "no_candidates"
    assert result["problem_id"] is None
    assert "catalogue" in result["reason"].lower()


def test_tie_breaking_is_deterministic():
    # Stable hash must produce identical integer for same inputs, different for different
    h1 = compute_stable_tie_break("2026-10-30", 1)
    h2 = compute_stable_tie_break("2026-10-30", 1)
    h3 = compute_stable_tie_break("2026-10-30", 2)
    h4 = compute_stable_tie_break("2026-10-31", 1)

    assert h1 == h2
    assert h1 != h3
    assert h1 != h4


def test_preferred_difficulties_filter(recommender_db, monkeypatch):
    # Set preferred difficulties to Medium and Hard only
    monkeypatch.setattr("app.recommender.PREFERRED_DIFFICULTIES", ["Medium", "Hard"])

    rec = select_daily_problem(target_date="2026-11-05", db_path=recommender_db)
    assert rec["difficulty"] in ("Medium", "Hard")
    assert rec["difficulty"] != "Easy"
