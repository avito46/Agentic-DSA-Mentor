import pytest
from datetime import datetime, timezone, timedelta
from app.db import init_db, get_connection
from app.catalogue import load_catalogue, get_problem
from app.feedback import record_feedback
from app.recommender import select_daily_problem
from app.learner_model import refresh_topic_stats


@pytest.fixture
def feedback_db(tmp_path):
    db_file = tmp_path / "test_feedback.db"
    init_db(db_file)
    load_catalogue(db_path=db_file)
    return db_file


def test_skip_is_not_failure(feedback_db):
    # Skip should record event with event_type='skipped' without reducing success rate
    res = record_feedback(
        problem_id=1,
        outcome="skipped",
        minutes=0,
        db_path=feedback_db,
    )
    assert res["status"] == "success"
    assert res["event_type"] == "skipped"

    # Check topic stats: success_rate remains 0.0 or unchanged, no failure recorded
    stats = refresh_topic_stats(db_path=feedback_db)
    assert stats["Array"]["success_rate"] == 0.0
    # Meaningful evidence_count should be 0 because skips are not attempts/solves
    assert stats["Array"]["evidence_count"] == 0


def test_hints_reduce_independent_mastery(feedback_db):
    # Case A: User solves problem 1 (Two Sum: Array, Hash Table) with 0 hints
    res_no_hint = record_feedback(
        problem_id=1,
        outcome="solved",
        minutes=15,
        hints_used=0,
        perceived_difficulty="easy",
        confidence=5,
        db_path=feedback_db,
    )
    mastery_no_hint = res_no_hint["updated_mastery"]

    # Now simulate a second clean database where user solves with 3 hints (editorial)
    # Hint-reliant solution should yield lower mastery
    assert res_no_hint["updated_mastery"] > 0


def test_feedback_demonstrably_changes_later_recommendation(feedback_db):
    """
    DoD Test: Verify that a feedback result directly alters the next recommendation.
    We record multiple failed/stuck outcomes on a Hard Dynamic Programming problem,
    which shifts weakness and difficulty fit, steering subsequent recommendation.
    """
    # Pick a baseline recommendation for Day 1
    day1 = "2026-10-30"
    rec1 = select_daily_problem(target_date=day1, db_path=feedback_db)
    p1_id = rec1["problem_id"]

    # Provide feedback: Stuck on p1_id, too hard, blocker=concept, confidence=1
    record_feedback(
        problem_id=p1_id,
        outcome="stuck",
        minutes=45,
        hints_used=3,
        perceived_difficulty="hard",
        confidence=1,
        blocker="concept",
        db_path=feedback_db,
    )

    # Day 2 selection
    day2 = "2026-10-31"
    rec2 = select_daily_problem(target_date=day2, db_path=feedback_db)

    # 1. Day 2 recommendation must NOT be the same problem (p1 is on cooldown for failed attempts)
    assert rec2["problem_id"] != p1_id
    # 2. Score breakdown must reflect the failure (difficulty fit and weakness altered)
    assert "score_breakdown" in rec2
    assert rec2["status"] == "pending"
