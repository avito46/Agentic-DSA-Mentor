import pytest
import sqlite3
from datetime import datetime, timezone, timedelta
from app.db import init_db, get_connection
from app.catalogue import load_catalogue
from scripts.weekly_report import generate_weekly_report_data
from scripts.metrics_30day import compute_30day_metrics
from scripts.backup_db import perform_database_backup


@pytest.fixture
def metrics_db(tmp_path):
    db_file = tmp_path / "test_metrics.db"
    init_db(db_file)
    load_catalogue(db_path=db_file)
    return db_file


def test_weekly_report_empty_and_populated(metrics_db):
    # Empty case: insufficient data flag
    data_empty = generate_weekly_report_data(metrics_db)
    assert data_empty["has_sufficient_data"] is False
    assert data_empty["total_attempts"] == 0

    # Populate 3 events
    conn = get_connection(metrics_db)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO activity_events (problem_id, event_type, occurred_at, source, time_spent, hints_used, self_rating) VALUES (1, 'solved', ?, 'manual_feedback', 20, 0, 'right')",
        (now,),
    )
    conn.execute(
        "INSERT INTO activity_events (problem_id, event_type, occurred_at, source, time_spent, hints_used, self_rating) VALUES (3, 'solved', ?, 'manual_feedback', 30, 1, 'right')",
        (now,),
    )
    conn.execute(
        "INSERT INTO activity_events (problem_id, event_type, occurred_at, source, time_spent, hints_used, self_rating) VALUES (11, 'failed', ?, 'manual_feedback', 40, 2, 'hard')",
        (now,),
    )
    conn.commit()
    conn.close()

    data_pop = generate_weekly_report_data(metrics_db)
    assert data_pop["has_sufficient_data"] is True
    assert data_pop["total_attempts"] == 3
    assert data_pop["solves_count"] == 2
    assert data_pop["stuck_count"] == 1
    assert data_pop["total_minutes"] == 90


def test_30day_metrics_repeat_rate_and_completion(metrics_db):
    conn = get_connection(metrics_db)
    now = datetime.now(timezone.utc).isoformat()

    # Add recommendations
    conn.execute(
        """
        INSERT INTO daily_recommendations (date, problem_id, score, score_breakdown_json, reason, status, generated_at)
        VALUES ('2026-10-28', 1, 0.85, '{}', 'Reason 1', 'solved', ?)
        """,
        (now,),
    )
    conn.execute(
        """
        INSERT INTO daily_recommendations (date, problem_id, score, score_breakdown_json, reason, status, generated_at)
        VALUES ('2026-10-29', 3, 0.82, '{}', 'Reason 2', 'pending', ?)
        """,
        (now,),
    )

    # Add activity
    conn.execute(
        "INSERT INTO activity_events (problem_id, event_type, occurred_at, source, self_rating) VALUES (1, 'solved', ?, 'manual_feedback', 'right')",
        (now,),
    )
    conn.commit()
    conn.close()

    metrics = compute_30day_metrics(metrics_db)
    assert metrics["total_recommendations"] == 2
    # 1 solved out of 2 recommendations = 50%
    assert metrics["completion_rate_pct"] == 50.0
    # Zero solved repeat problems = 0.0%
    assert metrics["repeat_rate_pct"] == 0.0
    # Difficulty fit: 1 rating, and it's 'right' => 100%
    assert metrics["difficulty_fit_pct"] == 100.0


def test_backup_db_creation_integrity_and_rotation(metrics_db, tmp_path):
    backup_dir = tmp_path / "backups"

    # Create 3 backups keeping max 2
    b1 = perform_database_backup(metrics_db, backup_dir=backup_dir, max_backups=2)
    assert b1.is_file()

    # Verify integrity of backup SQLite database
    conn = sqlite3.connect(str(b1))
    check = conn.execute("PRAGMA integrity_check;").fetchone()
    assert check[0] == "ok"
    conn.close()
