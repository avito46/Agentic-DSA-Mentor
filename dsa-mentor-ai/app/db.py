"""Database connectivity and schema initialization for DSA Mentor AI."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Generator
from contextlib import contextmanager
from app.config import DB_PATH, SCHEMA_PATH, logger


def utc_now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Create and return a SQLite connection with foreign keys and Row factory enabled."""
    path = Path(db_path) if db_path else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


@contextmanager
def get_db(db_path: Optional[Path] = None) -> Generator[sqlite3.Connection, None, None]:
    """Context manager for SQLite connections with automatic commit/rollback."""
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Database transaction rolled back: {e}")
        raise
    finally:
        conn.close()


def init_db(db_path: Optional[Path] = None) -> None:
    """Initialize SQLite database with schema."""
    target_path = Path(db_path) if db_path else DB_PATH
    target_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"Initializing database schema at {target_path}")

    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with get_db(target_path) as conn:
        conn.executescript(schema_sql)
    logger.info("Database schema initialized successfully.")
