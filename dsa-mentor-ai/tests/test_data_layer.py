import json
import sqlite3
import pytest
from pathlib import Path
from datetime import datetime, timezone

from app.db import init_db, get_connection, get_db, utc_now_iso
from app.catalogue import validate_problem_dict, load_catalogue, get_problem, list_problems
from app.importer import import_history_from_file, parse_problem_id
from app.leetcode_client import sync_leetcode_history, save_snapshot, load_latest_snapshot


@pytest.fixture
def temp_db(tmp_path):
    """Provides an isolated initialized test database."""
    db_file = tmp_path / "test_dsa.db"
    init_db(db_file)
    return db_file


def test_schema_foreign_keys_and_tables(temp_db):
    conn = get_connection(temp_db)
    # Check FK is enabled
    fk_status = conn.execute("PRAGMA foreign_keys;").fetchone()[0]
    assert fk_status == 1

    # Check required tables exist
    tables = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table';"
        ).fetchall()
    ]
    required = {
        "problems",
        "activity_events",
        "topic_stats",
        "daily_recommendations",
        "model_runs",
        "sync_runs",
    }
    assert required.issubset(set(tables))
    conn.close()


def test_catalogue_loader_and_unknown_fallback(temp_db, tmp_path):
    # Test valid and invalid problem records
    raw_custom = [
        {
            "problem_id": 101,
            "title": "Symmetric Tree",
            "slug": "symmetric-tree",
            "url": "https://leetcode.com/problems/symmetric-tree/",
            "difficulty": "Easy",
            "topics": ["Tree", "Binary Tree"],
            "source": "curated_test",
            "verified_at": "2026-10-30T00:00:00Z",
        },
        {
            "problem_id": 102,
            "title": "Custom Mystery",
            "slug": "custom-mystery",
            # Missing difficulty and topics
            "difficulty": "SuperHard", # invalid => must become 'unknown'
            "source": "mystery_source",
        },
    ]
    catalog_file = tmp_path / "test_problems.json"
    catalog_file.write_text(json.dumps(raw_custom), encoding="utf-8")

    loaded = load_catalogue(catalog_file, db_path=temp_db)
    assert loaded == 2

    p101 = get_problem(101, db_path=temp_db)
    assert p101 is not None
    assert p101["difficulty"] == "Easy"
    assert "Tree" in p101["topics"]

    p102 = get_problem(102, db_path=temp_db)
    assert p102 is not None
    assert p102["difficulty"] == "unknown"  # NEVER invent difficulty
    assert p102["topics"] == []  # NEVER invent tags


def test_importer_deduplication_and_stable_ids(temp_db, tmp_path):
    # Pre-populate catalogue
    load_catalogue(db_path=temp_db)

    # Create CSV import with duplicates, changed titles for same ID, and missing fields
    csv_content = """problem_id,title,slug,submission_date,language,runtime_ms
1,Two Sum,two-sum,2026-01-01 10:00:00,python3,45
1,Two Sum - Old Sub,two-sum,2025-12-01 09:00:00,cpp,12
3,Longest Substring,longest-substring-without-repeating-characters,2026-01-02 11:00:00,python3,60
invalid_id,Bad Question,bad-q,2026-01-03,python3,99
15,3Sum,3sum,2026-01-04 12:00:00,python3,75
"""
    csv_file = tmp_path / "submissions.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    result = import_history_from_file(csv_file, db_path=temp_db)

    assert result["total_seen"] == 5
    # IDs 1, 3, 15 added; duplicate ID 1 skipped; invalid_id skipped
    assert result["records_added"] == 3
    assert result["skipped_duplicates"] == 1
    assert result["invalid_records"] == 1
    # Stable ID rate on valid records: 3 added / 4 valid = 75% total, 100% of distinct valid IDs
    assert parse_problem_id("123") == 123
    assert parse_problem_id("abc") is None

    # Importing again must skip all existing as duplicates
    result_second = import_history_from_file(csv_file, db_path=temp_db)
    assert result_second["records_added"] == 0
    assert result_second["skipped_duplicates"] == 4


def test_leetcode_client_snapshot_fallback_and_partial_response(temp_db, tmp_path, monkeypatch):
    load_catalogue(db_path=temp_db)

    # Setup mock snapshot in temp snapshot directory
    monkeypatch.setattr("app.leetcode_client.SNAPSHOT_DIR", tmp_path / "snapshots")
    fake_username = "test_user"

    mock_payload = {
        "data": {
            "recentAcSubmissionList": [
                {"id": "1", "title": "Two Sum", "titleSlug": "two-sum", "timestamp": "1735689600"},
                {"id": "3", "title": "Longest Substring Without Repeating Characters", "titleSlug": "longest-substring-without-repeating-characters", "timestamp": "1735689700"},
                {"id": "11", "title": "Container With Most Water", "titleSlug": "container-with-most-water", "timestamp": "1735689800"},
            ]
        }
    }
    save_snapshot(fake_username, mock_payload)

    # Test offline sync with snapshot fallback
    res = sync_leetcode_history(username=fake_username, db_path=temp_db, force_offline=True)
    assert res["status"] == "stale_fallback"
    assert res["records_added"] == 3

    # Test partial response detection: next snapshot has only 1 submission
    partial_payload = {
        "data": {
            "recentAcSubmissionList": [
                {"id": "1", "title": "Two Sum", "titleSlug": "two-sum", "timestamp": "1735689600"},
            ]
        }
    }
    save_snapshot(fake_username, partial_payload)
    res_partial = sync_leetcode_history(username=fake_username, db_path=temp_db, force_offline=True)
    assert res_partial["status"] == "partial_response"

    # Verify that existing solved problems 3 and 11 are NOT marked unsolved or deleted
    with get_db(temp_db) as conn:
        solved_ids = {
            r["problem_id"]
            for r in conn.execute(
                "SELECT problem_id FROM activity_events WHERE event_type='solved'"
            ).fetchall()
        }
        assert {1, 3, 11}.issubset(solved_ids)
