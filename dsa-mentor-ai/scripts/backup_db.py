"""Automated SQLite database backup utility using SQLite's online backup API."""

import sys
from pathlib import Path

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import argparse
import sqlite3
import os
from datetime import datetime, timezone
from app.config import DB_PATH, logger

BACKUP_DIR = BASE_DIR / "backups"


def perform_database_backup(
    src_db_path: Path = None,
    backup_dir: Path = None,
    max_backups: int = 7,
) -> Path:
    """
    Perform a safe, atomic online backup of SQLite database.
    Verifies backup integrity and rotates older snapshots.
    """
    source = Path(src_db_path) if src_db_path else DB_PATH
    if not source.is_file():
        raise FileNotFoundError(f"Source database not found at {source}")

    dest_dir = Path(backup_dir) if backup_dir else BACKUP_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_file = dest_dir / f"dsa_mentor_backup_{timestamp}.db"

    # Online atomic backup
    src_conn = sqlite3.connect(str(source))
    dst_conn = sqlite3.connect(str(backup_file))
    try:
        src_conn.backup(dst_conn)
        logger.info(f"Database backed up to {backup_file}")
    finally:
        dst_conn.close()
        src_conn.close()

    # Integrity verification
    verify_conn = sqlite3.connect(str(backup_file))
    try:
        check = verify_conn.execute("PRAGMA integrity_check;").fetchone()
        if not check or check[0] != "ok":
            raise RuntimeError(f"Backup integrity check failed: {check}")
        logger.info("Backup integrity verification: PASSED (ok)")
    finally:
        verify_conn.close()

    # Rotate old backups keeping latest max_backups
    existing = sorted(dest_dir.glob("dsa_mentor_backup_*.db"), key=os.path.getmtime)
    if len(existing) > max_backups:
        for old in existing[:-max_backups]:
            try:
                old.unlink()
                logger.info(f"Rotated old backup: {old.name}")
            except Exception as e:
                logger.warning(f"Could not remove old backup {old}: {e}")

    return backup_file


def main():
    parser = argparse.ArgumentParser(description="Create an atomic SQLite database backup.")
    parser.add_argument("--src", default=None, help="Source database path")
    parser.add_argument("--dest", default=None, help="Destination directory for backups")
    parser.add_argument("--keep", type=int, default=7, help="Number of recent backups to preserve")
    args = parser.parse_args()

    out = perform_database_backup(args.src, args.dest, args.keep)
    print(f"\n✅ Backup created and verified at: {out}\n")


if __name__ == "__main__":
    main()
