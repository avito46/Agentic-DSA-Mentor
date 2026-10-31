import json
import pytest
from app.api import create_app
from app.db import init_db, get_connection
from app.catalogue import load_catalogue


@pytest.fixture
def api_client(tmp_path):
    db_file = tmp_path / "test_api.db"
    init_db(db_file)
    load_catalogue(db_path=db_file)
    app = create_app(custom_db_path=db_file)
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client, db_file


def test_api_health_and_localhost(api_client):
    client, db_file = api_client
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "healthy"
    assert "timestamp" in data


def test_api_today_recommendation(api_client):
    client, db_file = api_client
    res = client.get("/api/today?date=2026-10-30")
    assert res.status_code == 200
    data = res.get_json()
    assert "recommendation" in data
    rec = data["recommendation"]
    assert rec["date"] == "2026-10-30"
    assert rec["problem_id"] is not None
    assert "score_breakdown" in rec
    assert "coaching" in data
    assert "hint_1" in data["coaching"]


def test_api_feedback_input_validation(api_client):
    client, db_file = api_client

    # 1. Reject missing or non-JSON body
    res_bad = client.post("/api/feedback", data="not json")
    assert res_bad.status_code == 400

    # 2. Reject missing or invalid problem_id
    res_no_pid = client.post("/api/feedback", json={"outcome": "solved"})
    assert res_no_pid.status_code == 400

    # 3. Reject invalid outcome string
    res_bad_outcome = client.post("/api/feedback", json={"problem_id": 1, "outcome": "cheated"})
    assert res_bad_outcome.status_code == 400


def test_api_feedback_end_to_end_adaptation(api_client):
    client, db_file = api_client

    # Fetch today's problem first
    today_res = client.get("/api/today?date=2026-10-30")
    today_data = today_res.get_json()
    pid = today_data["recommendation"]["problem_id"]

    # Submit valid feedback for pid
    feedback_payload = {
        "problem_id": pid,
        "outcome": "solved",
        "minutes": 20,
        "hints_used": 0,
        "perceived_difficulty": "right",
        "confidence": 4,
    }
    fb_res = client.post("/api/feedback", json=feedback_payload)
    assert fb_res.status_code == 200
    fb_data = fb_res.get_json()
    assert fb_data["status"] == "success"
    assert fb_data["problem_id"] == pid
    assert "updated_mastery" in fb_data

    # Check that recommendation status is updated to 'solved'
    today_res_after = client.get("/api/today?date=2026-10-30")
    rec_after = today_res_after.get_json()["recommendation"]
    assert rec_after["status"] == "solved"

    # Check history endpoint contains the event
    hist_res = client.get("/api/history")
    assert hist_res.status_code == 200
    events = hist_res.get_json()["activity_events"]
    assert any(e["problem_id"] == pid and e["event_type"] == "solved" for e in events)


def test_api_read_endpoints(api_client):
    client, db_file = api_client

    res_topics = client.get("/api/topics")
    assert res_topics.status_code == 200
    assert "topics" in res_topics.get_json()

    res_sync = client.get("/api/sync/status")
    assert res_sync.status_code == 200
    assert "is_stale" in res_sync.get_json()

    res_metrics = client.get("/api/metrics")
    assert res_metrics.status_code == 200
    assert "repeat_rate_pct" in res_metrics.get_json()
