import pytest
from app.db import init_db
from app.catalogue import load_catalogue
from scripts.telegram_bot import handle_telegram_command


@pytest.fixture
def tg_db(tmp_path):
    db_file = tmp_path / "test_tg.db"
    init_db(db_file)
    load_catalogue(db_path=db_file)
    return db_file


def test_telegram_authorization(tg_db):
    # Denies wrong chat_id
    res = handle_telegram_command("/today", chat_id="999", allowed_chat_id="123", db_path=tg_db)
    assert "Unauthorized" in res

    # Allows correct chat_id
    res_ok = handle_telegram_command("/help", chat_id="123", allowed_chat_id="123", db_path=tg_db)
    assert "Available commands" in res_ok


def test_telegram_today_and_hints(tg_db):
    res_today = handle_telegram_command("/today", chat_id="123", allowed_chat_id="123", db_path=tg_db)
    assert "DSA MENTOR AI" in res_today

    res_hint1 = handle_telegram_command("/hint1", chat_id="123", allowed_chat_id="123", db_path=tg_db)
    assert "Hint 1" in res_hint1

    res_hint2 = handle_telegram_command("/hint2", chat_id="123", allowed_chat_id="123", db_path=tg_db)
    assert "Hint 2" in res_hint2


def test_telegram_feedback_and_stats(tg_db):
    res_solve = handle_telegram_command("/solved 20", chat_id="123", allowed_chat_id="123", db_path=tg_db)
    assert "Feedback Recorded" in res_solve
    assert "SOLVED" in res_solve

    res_stats = handle_telegram_command("/stats", chat_id="123", allowed_chat_id="123", db_path=tg_db)
    assert "Top Topic Mastery" in res_stats
