"""Isolated, read-only LeetCode GraphQL client with rate limiting, retries, and offline fallback."""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional
import requests

from app.db import get_db, utc_now_iso
from app.config import (
    LEETCODE_USERNAME,
    LEETCODE_GRAPHQL_URL,
    LEETCODE_RATE_LIMIT_DELAY,
    SNAPSHOT_DIR,
    logger,
)

GRAPHQL_QUERY = """
query recentAcSubmissions($username: String!, $limit: Int!) {
  recentAcSubmissionList(username: $username, limit: $limit) {
    id
    title
    titleSlug
    timestamp
  }
}
"""


class LeetCodeSyncError(Exception):
    """Base exception for LeetCode synchronization issues."""
    pass


def save_snapshot(username: str, data: Dict[str, Any]) -> Path:
    """Save raw response snapshot without headers or credentials."""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    clean_username = "".join(c for c in username if c.isalnum() or c in ("-", "_"))
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    # Save timestamped snapshot
    snap_path = SNAPSHOT_DIR / f"{clean_username}_{timestamp}.json"
    with open(snap_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    # Also update latest symlink/file
    latest_path = SNAPSHOT_DIR / f"{clean_username}_latest.json"
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    return latest_path


def load_latest_snapshot(username: str) -> Optional[Dict[str, Any]]:
    """Load the most recent snapshot for a username if network is unavailable."""
    clean_username = "".join(c for c in username if c.isalnum() or c in ("-", "_"))
    latest_path = SNAPSHOT_DIR / f"{clean_username}_latest.json"
    if latest_path.is_file():
        try:
            with open(latest_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read snapshot from {latest_path}: {e}")

    # Fallback to scanning SNAPSHOT_DIR
    candidates = sorted(SNAPSHOT_DIR.glob(f"{clean_username}_*.json"), reverse=True)
    for c in candidates:
        if c.name.endswith("_latest.json"):
            continue
        try:
            with open(c, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            continue
    return None


# shortcut: Public GraphQL queries using public submissions endpoint, upgrade: Revisit if LeetCode GraphQL schema changes
def fetch_public_submissions_from_api(
    username: str,
    limit: int = 50,
    max_retries: int = 3,
    backoff_factor: float = 1.5,
) -> Dict[str, Any]:
    """
    Fetch public accepted submissions with rate limiting and exponential backoff.
    Never sends cookies, passwords, or personal tokens.
    """
    if not username:
        raise ValueError("Username must not be empty.")

    payload = {
        "query": GRAPHQL_QUERY,
        "variables": {"username": username, "limit": limit},
    }
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "DSA-Mentor-AI/1.0 (Educational Sync Client)",
    }

    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            time.sleep(LEETCODE_RATE_LIMIT_DELAY)
            response = requests.post(
                LEETCODE_GRAPHQL_URL,
                json=payload,
                headers=headers,
                timeout=10.0,
            )
            response.raise_for_status()
            data = response.json()

            # Schema validation
            if not isinstance(data, dict):
                raise LeetCodeSyncError("Response is not a valid JSON dictionary")
            if "errors" in data and not data.get("data"):
                error_msg = "; ".join(e.get("message", "unknown") for e in data["errors"])
                raise LeetCodeSyncError(f"GraphQL errors: {error_msg}")

            submission_list = (data.get("data") or {}).get("recentAcSubmissionList")
            if submission_list is None or not isinstance(submission_list, list):
                raise LeetCodeSyncError("Missing recentAcSubmissionList in response schema")

            return data
        except (requests.RequestException, LeetCodeSyncError) as e:
            last_exc = e
            logger.warning(
                f"LeetCode fetch attempt {attempt}/{max_retries} failed: {e}. "
                f"Backing off for {backoff_factor ** attempt:.1f}s"
            )
            time.sleep(backoff_factor ** attempt)

    raise LeetCodeSyncError(f"All {max_retries} fetch attempts failed: {last_exc}")


def sync_leetcode_history(
    username: Optional[str] = None,
    db_path: Optional[Path] = None,
    force_offline: bool = False,
) -> Dict[str, Any]:
    """
    Synchronize LeetCode public accepted submissions into activity_events.
    If sync fails, falls back to the latest snapshot marked stale.
    Guard against partial response (never marks removed problems unsolved).
    """
    target_username = (username or LEETCODE_USERNAME).strip()
    if not target_username:
        logger.info("No LeetCode username configured. Skipping network sync.")
        return {"status": "skipped", "reason": "no_username_configured"}

    started_at = utc_now_iso()
    raw_data: Optional[Dict[str, Any]] = None
    is_stale_fallback = False
    error_summary = None

    if not force_offline:
        try:
            raw_data = fetch_public_submissions_from_api(target_username)
            save_snapshot(target_username, raw_data)
        except Exception as e:
            error_summary = f"API fetch failed: {str(e)}"
            logger.warning(f"Live sync failed, attempting snapshot fallback: {e}")
            raw_data = load_latest_snapshot(target_username)
            if raw_data:
                is_stale_fallback = True
            else:
                completed_at = utc_now_iso()
                with get_db(db_path) as conn:
                    conn.execute(
                        """
                        INSERT INTO sync_runs (
                            source, started_at, completed_at, records_seen, records_added, status, error_summary
                        ) VALUES ('leetcode_graphql', ?, ?, 0, 0, 'failed', ?)
                        """,
                        (started_at, completed_at, error_summary),
                    )
                return {"status": "failed", "error": error_summary}
    else:
        raw_data = load_latest_snapshot(target_username)
        if raw_data:
            is_stale_fallback = True
        else:
            return {"status": "failed", "error": "offline_mode_no_snapshot"}

    submissions = (raw_data.get("data") or {}).get("recentAcSubmissionList", [])
    total_seen = len(submissions)
    records_added = 0
    status = "stale_fallback" if is_stale_fallback else "success"

    with get_db(db_path) as conn:
        # Partial response check: check how many records previous successful sync saw
        prev_sync_cur = conn.execute(
            """
            SELECT MAX(records_seen) as max_seen FROM sync_runs
            WHERE source = 'leetcode_graphql' AND status IN ('success', 'partial_response', 'stale_fallback')
            """
        )
        prev_max_row = prev_sync_cur.fetchone()
        prev_max_seen = prev_max_row["max_seen"] if prev_max_row and prev_max_row["max_seen"] else 0

        if prev_max_seen > 0 and total_seen < prev_max_seen:
            status = "partial_response"
            error_summary = (
                f"Partial response detected: saw {total_seen} items vs {prev_max_seen} in previous sync. "
                "Retaining existing solved history without marking removed problems unsolved."
            )
            logger.warning(error_summary)

        # Get existing solved problem slugs and IDs
        cur = conn.execute("SELECT problem_id, slug FROM problems")
        slug_to_id = {row["slug"]: row["problem_id"] for row in cur.fetchall()}

        solved_cur = conn.execute(
            "SELECT DISTINCT problem_id FROM activity_events WHERE event_type IN ('solved', 'imported')"
        )
        already_solved_ids = {row["problem_id"] for row in solved_cur.fetchall()}

        for sub in submissions:
            slug = sub.get("titleSlug")
            title = sub.get("title") or (slug.replace("-", " ").title() if slug else "Unknown")
            ts = sub.get("timestamp")
            occurred_at = (
                datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
                if ts
                else utc_now_iso()
            )

            # Match slug to problem
            problem_id = slug_to_id.get(slug)
            if not problem_id:
                # If problem not in catalogue yet, assign next synthetic negative/high ID or query max ID
                max_id_row = conn.execute("SELECT MAX(problem_id) as m FROM problems").fetchone()
                next_id = (max_id_row["m"] or 10000) + 1
                conn.execute(
                    """
                    INSERT INTO problems (
                        problem_id, title, slug, url, difficulty, topics_json,
                        premium_status, source, verified_at
                    ) VALUES (?, ?, ?, ?, 'unknown', '[]', 0, 'leetcode_sync', ?)
                    """,
                    (next_id, title, slug, f"https://leetcode.com/problems/{slug}/", utc_now_iso()),
                )
                problem_id = next_id
                slug_to_id[slug] = problem_id

            if problem_id not in already_solved_ids:
                conn.execute(
                    """
                    INSERT INTO activity_events (
                        problem_id, event_type, occurred_at, source
                    ) VALUES (?, 'solved', ?, 'leetcode_sync')
                    """,
                    (problem_id, occurred_at),
                )
                already_solved_ids.add(problem_id)
                records_added += 1

        completed_at = utc_now_iso()
        conn.execute(
            """
            INSERT INTO sync_runs (
                source, started_at, completed_at, records_seen, records_added, status, error_summary
            ) VALUES ('leetcode_graphql', ?, ?, ?, ?, ?, ?)
            """,
            (started_at, completed_at, total_seen, records_added, status, error_summary),
        )

    logger.info(
        f"LeetCode sync finished: status={status}, seen={total_seen}, added={records_added}"
    )
    return {
        "status": status,
        "records_seen": total_seen,
        "records_added": records_added,
        "is_stale_fallback": is_stale_fallback,
        "error_summary": error_summary,
    }
