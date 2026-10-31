"""History Importer for CSV and JSON LeetCode solved records."""

import csv
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from app.db import get_db, utc_now_iso
from app.config import BASE_DIR, logger

RAW_DATA_DIR = BASE_DIR / "data" / "raw"


def save_raw_copy(source_path: Path) -> Path:
    """Safely archive a timestamped raw copy of the import file in data/raw/."""
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest_path = RAW_DATA_DIR / f"{timestamp}_{source_path.name}"
    shutil.copy2(source_path, dest_path)
    return dest_path


def parse_problem_id(val: Any) -> Optional[int]:
    """Parse problem ID safely into a positive integer."""
    if val is None or val == "":
        return None
    try:
        pid = int(float(str(val).strip()))
        return pid if pid > 0 else None
    except (ValueError, TypeError):
        return None


def parse_timestamp(val: Any) -> str:
    """Parse or fallback to ISO 8601 UTC timestamp."""
    if not val:
        return utc_now_iso()
    val_str = str(val).strip()
    # Try parsing unix timestamp
    try:
        ts = float(val_str)
        if ts > 1e11:  # ms
            ts = ts / 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except (ValueError, OverflowError):
        pass

    # Try standard string formats
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(val_str, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        except ValueError:
            continue

    return utc_now_iso()


def import_history_from_file(
    file_path: Path,
    db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Import solved LeetCode history from CSV or JSON file.
    Deduplicates strictly by problem_id.
    Ensures foreign keys remain valid and returns statistics.
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Import file does not exist: {path}")

    # Step 1: Archive raw copy
    archived_path = save_raw_copy(path)
    started_at = utc_now_iso()

    # Step 2: Read raw records
    raw_records: List[Dict[str, Any]] = []
    suffix = path.suffix.lower()

    if suffix == ".json":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                raw_records = data
            elif isinstance(data, dict) and "submissions" in data:
                raw_records = data["submissions"]
            elif isinstance(data, dict):
                raw_records = [data]
    elif suffix in (".csv", ".txt"):
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            raw_records = [dict(row) for row in reader]
    else:
        raise ValueError(f"Unsupported file format '{suffix}'. Use .csv or .json")

    total_seen = len(raw_records)
    records_added = 0
    skipped_duplicates = 0
    invalid_records = 0

    seen_problem_ids_in_batch = set()

    with get_db(db_path) as conn:
        # Load all already solved / imported problem_ids from activity_events to deduplicate strictly by problem_id
        cur = conn.execute(
            """
            SELECT DISTINCT problem_id FROM activity_events
            WHERE event_type IN ('solved', 'imported')
            """
        )
        existing_solved_ids = {row["problem_id"] for row in cur.fetchall()}

        for rec in raw_records:
            # Look for common column names for problem ID
            raw_id = (
                rec.get("problem_id")
                or rec.get("id")
                or rec.get("frontend_question_id")
                or rec.get("question_id")
                or rec.get("Problem ID")
            )
            problem_id = parse_problem_id(raw_id)

            if problem_id is None:
                invalid_records += 1
                continue

            # Deduplicate strictly by problem_id (never by title)
            if problem_id in existing_solved_ids or problem_id in seen_problem_ids_in_batch:
                skipped_duplicates += 1
                continue

            seen_problem_ids_in_batch.add(problem_id)

            # Ensure problem exists in problems table (foreign key constraint)
            prob_cur = conn.execute(
                "SELECT problem_id FROM problems WHERE problem_id = ?", (problem_id,)
            )
            if not prob_cur.fetchone():
                # Register minimal placeholder problem without invented tags or difficulty
                title = str(
                    rec.get("title")
                    or rec.get("title_slug")
                    or rec.get("slug")
                    or f"Problem {problem_id}"
                ).strip()
                slug = str(rec.get("slug") or rec.get("title_slug") or f"problem-{problem_id}").strip()
                url = f"https://leetcode.com/problems/{slug}/"
                conn.execute(
                    """
                    INSERT INTO problems (
                        problem_id, title, slug, url, difficulty, topics_json,
                        premium_status, source, verified_at
                    ) VALUES (?, ?, ?, ?, 'unknown', '[]', 0, 'import_placeholder', ?)
                    """,
                    (problem_id, title, slug, url, utc_now_iso()),
                )

            # Extract event details
            occurred_at = parse_timestamp(
                rec.get("occurred_at")
                or rec.get("timestamp")
                or rec.get("submission_date")
                or rec.get("date")
            )
            runtime_ms = None
            try:
                if rec.get("runtime_ms") is not None:
                    runtime_ms = int(float(rec.get("runtime_ms")))
            except (ValueError, TypeError):
                pass

            language = str(rec.get("language") or rec.get("lang") or "").strip() or None

            conn.execute(
                """
                INSERT INTO activity_events (
                    problem_id, event_type, occurred_at, source, runtime_ms, language
                ) VALUES (?, 'imported', ?, 'import', ?, ?)
                """,
                (problem_id, occurred_at, runtime_ms, language),
            )
            existing_solved_ids.add(problem_id)
            records_added += 1

        # Record sync run log
        completed_at = utc_now_iso()
        conn.execute(
            """
            INSERT INTO sync_runs (
                source, started_at, completed_at, records_seen, records_added, status, error_summary
            ) VALUES (?, ?, ?, ?, ?, 'success', NULL)
            """,
            (f"{suffix.lstrip('.')}_import", started_at, completed_at, total_seen, records_added),
        )

    logger.info(
        f"Import completed from {path.name}: seen={total_seen}, added={records_added}, "
        f"skipped_duplicates={skipped_duplicates}, invalid={invalid_records}"
    )

    return {
        "archived_path": str(archived_path),
        "total_seen": total_seen,
        "records_added": records_added,
        "skipped_duplicates": skipped_duplicates,
        "invalid_records": invalid_records,
        "success_rate": (records_added / total_seen) if total_seen > 0 else 0.0,
    }
