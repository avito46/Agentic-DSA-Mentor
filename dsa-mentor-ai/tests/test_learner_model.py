import pytest
from datetime import datetime, timezone, timedelta
from app.learner_model import (
    calculate_topic_mastery,
    compute_weighted_mastery,
    calculate_recency_score,
    calculate_difficulty_ceiling_score,
    refresh_topic_stats,
)
from app.db import init_db, get_connection
from app.catalogue import load_catalogue


def test_empty_history():
    stat = calculate_topic_mastery([])
    assert stat["mastery_score"] == 0.0
    assert stat["weakness_score"] == 100.0
    assert stat["exposure_count"] == 0
    assert stat["evidence_count"] == 0
    assert stat["is_insufficient_evidence"] is True
    assert stat["difficulty_ceiling"] == "None"


def test_sparse_history_insufficient_evidence():
    # Only 2 attempts (< 3)
    now = datetime.now(timezone.utc).isoformat()
    events = [
        {"event_type": "solved", "source": "manual_feedback", "occurred_at": now, "difficulty": "Easy", "hints_used": 0, "self_rating": "easy"},
        {"event_type": "attempted", "source": "manual_feedback", "occurred_at": now, "difficulty": "Medium", "hints_used": 2, "self_rating": "hard"},
    ]
    stat = calculate_topic_mastery(events)
    assert stat["evidence_count"] == 2
    assert stat["is_insufficient_evidence"] is True
    assert 0 < stat["mastery_score"] < 100


def test_imported_only_history_redistributes_weights():
    # 4 imported events: spec requires imported-only success rate = unknown (None)
    now = datetime.now(timezone.utc).isoformat()
    events = [
        {"event_type": "imported", "source": "import", "occurred_at": now, "difficulty": "Easy"},
        {"event_type": "imported", "source": "import", "occurred_at": now, "difficulty": "Easy"},
        {"event_type": "imported", "source": "import", "occurred_at": now, "difficulty": "Medium"},
        {"event_type": "imported", "source": "import", "occurred_at": now, "difficulty": "Medium"},
    ]
    stat = calculate_topic_mastery(events)
    assert stat["evidence_count"] == 4
    assert stat["is_insufficient_evidence"] is False
    # Success component must be None for imported-only
    assert stat["components"]["success"] is None
    # Low-hint and confidence must be None (no feedback)
    assert stat["components"]["low_hint"] is None
    assert stat["components"]["confidence"] is None
    # Difficulty ceiling: Medium solved 2+ times = 75.0
    assert stat["components"]["difficulty"] == 75.0
    # Recency: day 0 = 100.0
    assert round(stat["components"]["recency"], 0) == 100.0
    # Weights for difficulty (0.20) and recency (0.20) are redistributed equally (0.50 each)
    # Expected mastery: 0.5 * 75 + 0.5 * 100 = 87.5
    assert abs(stat["mastery_score"] - 87.5) < 1.0


def test_conflicting_history():
    # 2 failures followed by 1 solve
    now = datetime.now(timezone.utc).isoformat()
    events = [
        {"event_type": "failed", "source": "manual_feedback", "occurred_at": now, "difficulty": "Medium", "hints_used": 2, "self_rating": "hard"},
        {"event_type": "failed", "source": "manual_feedback", "occurred_at": now, "difficulty": "Medium", "hints_used": 3, "self_rating": "hard"},
        {"event_type": "solved", "source": "manual_feedback", "occurred_at": now, "difficulty": "Medium", "hints_used": 1, "self_rating": "right"},
    ]
    stat = calculate_topic_mastery(events)
    assert stat["evidence_count"] == 3
    assert stat["is_insufficient_evidence"] is False
    assert stat["success_rate"] == 0.33  # 1 solve out of 3 attempts
    # Success rate drags down mastery
    assert stat["mastery_score"] < 60.0
    assert stat["weakness_score"] > 40.0


def test_stale_history_decays_recency():
    # Solved 90 days ago
    stale_date = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    events = [
        {"event_type": "solved", "source": "manual_feedback", "occurred_at": stale_date, "difficulty": "Hard", "hints_used": 0, "self_rating": "easy"},
        {"event_type": "solved", "source": "manual_feedback", "occurred_at": stale_date, "difficulty": "Hard", "hints_used": 0, "self_rating": "easy"},
        {"event_type": "solved", "source": "manual_feedback", "occurred_at": stale_date, "difficulty": "Hard", "hints_used": 0, "self_rating": "easy"},
    ]
    stat = calculate_topic_mastery(events)
    assert stat["components"]["recency"] < 20.0  # Decayed substantially
    # Same problems solved today should have significantly higher mastery
    fresh_events = [
        {"event_type": "solved", "source": "manual_feedback", "occurred_at": datetime.now(timezone.utc).isoformat(), "difficulty": "Hard", "hints_used": 0, "self_rating": "easy"},
        {"event_type": "solved", "source": "manual_feedback", "occurred_at": datetime.now(timezone.utc).isoformat(), "difficulty": "Hard", "hints_used": 0, "self_rating": "easy"},
        {"event_type": "solved", "source": "manual_feedback", "occurred_at": datetime.now(timezone.utc).isoformat(), "difficulty": "Hard", "hints_used": 0, "self_rating": "easy"},
    ]
    fresh_stat = calculate_topic_mastery(fresh_events)
    assert fresh_stat["mastery_score"] > stat["mastery_score"]


def test_refresh_topic_stats_database(tmp_path):
    db_file = tmp_path / "test_learner.db"
    init_db(db_file)
    load_catalogue(db_path=db_file)

    conn = get_connection(db_file)
    now = datetime.now(timezone.utc).isoformat()
    # Add events for Two Sum (problem 1: Array, Hash Table)
    conn.execute(
        """
        INSERT INTO activity_events (problem_id, event_type, occurred_at, source, hints_used, self_rating)
        VALUES (1, 'solved', ?, 'manual_feedback', 0, 'easy')
        """,
        (now,),
    )
    conn.commit()
    conn.close()

    updated = refresh_topic_stats(db_path=db_file)
    assert "Array" in updated
    assert "Hash Table" in updated
    assert updated["Array"]["exposure_count"] == 1
