"""CLI script to import LeetCode solved history from CSV or JSON files."""

import sys
from pathlib import Path

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import argparse
from app.db import init_db
from app.catalogue import load_catalogue
from app.importer import import_history_from_file
from app.config import logger


def main():
    parser = argparse.ArgumentParser(description="Import LeetCode solved history into DSA Mentor AI.")
    parser.add_argument("file", help="Path to CSV or JSON export of LeetCode history")
    parser.add_argument("--db", default=None, help="Optional custom SQLite database path")
    args = parser.parse_args()

    file_path = Path(args.file)
    if not file_path.exists():
        logger.error(f"File not found: {file_path}")
        sys.exit(1)

    # Ensure DB and catalogue exist
    init_db(args.db)
    load_catalogue(db_path=args.db)

    logger.info(f"Starting import from {file_path}")
    result = import_history_from_file(file_path, db_path=args.db)

    print("\n=== IMPORT SUMMARY ===")
    print(f"Archived to: {result['archived_path']}")
    print(f"Records seen: {result['total_seen']}")
    print(f"Records added: {result['records_added']}")
    print(f"Duplicates skipped: {result['skipped_duplicates']}")
    print(f"Invalid skipped: {result['invalid_records']}")
    print("======================\n")


if __name__ == "__main__":
    main()
