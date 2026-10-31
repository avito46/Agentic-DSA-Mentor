import logging
import os
from pathlib import Path
from app.config import setup_logger, SensitiveDataFilter, BASE_DIR, MASTERY_WEIGHTS, RECOMMENDER_WEIGHTS


def test_config_paths():
    assert BASE_DIR.is_dir()
    assert sum(MASTERY_WEIGHTS.values()) == 1.00
    assert sum(RECOMMENDER_WEIGHTS.values()) == 1.00


def test_sensitive_data_filter():
    logger = setup_logger("test_filter")
    # Verify filter catches telegram-style bot token
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Error calling api with token bot123456789:ABCdefGHIjklMNOpqrSTUvwxYZ123456",
        args=(),
        exc_info=None,
    )
    f = SensitiveDataFilter()
    assert f.filter(record) is True
    assert "bot123456789:ABCdefGHIjklMNOpqrSTUvwxYZ123456" not in record.msg
    assert "[REDACTED_SECRET]" in record.msg


def test_gitignore_covers_sensitive_files():
    gitignore_path = BASE_DIR / ".gitignore"
    assert gitignore_path.exists()
    content = gitignore_path.read_text(encoding="utf-8")
    assert ".env" in content
    assert "*.db" in content
    assert "data/raw/" in content
    assert ".venv/" in content
