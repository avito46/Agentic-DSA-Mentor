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
from app.learner_model import refresh_topic_stats
from app.pattern_analyzer import get_canonical_patterns

GRAPHQL_QUERY = """
query userProfileAndRecentAc($username: String!, $limit: Int!) {
  matchedUser(username: $username) {
    username
    submitStatsGlobal {
      acSubmissionNum {
        difficulty
        count
      }
    }
    tagProblemCounts {
      advanced {
        tagName
        tagSlug
        problemsSolved
      }
      intermediate {
        tagName
        tagSlug
        problemsSolved
      }
      fundamental {
        tagName
        tagSlug
        problemsSolved
      }
    }
  }
  recentAcSubmissionList(username: $username, limit: $limit) {
    id
    title
    titleSlug
    timestamp
  }
}
"""

QUESTION_QUERY = """
query questionData($titleSlug: String!) {
  question(titleSlug: $titleSlug) {
    questionFrontendId
    title
    titleSlug
    difficulty
    topicTags {
      name
      slug
    }
  }
}
"""


class LeetCodeSyncError(Exception):
    """Base exception for LeetCode synchronization issues."""
    pass


def get_ca_bundle() -> Optional[str]:
    """Return certifi bundle path if available to prevent Windows ASN1 certificate store crashes."""
    try:
        import certifi
        return certifi.where()
    except Exception:
        return None


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


def fetch_question_metadata(
    title_slug: str,
    max_retries: int = 2,
) -> Optional[Dict[str, Any]]:
    """Fetch verified difficulty and topic tags from LeetCode for a question slug."""
    payload = {
        "query": QUESTION_QUERY,
        "variables": {"titleSlug": title_slug},
    }
    headers = {
        "Content-Type": "application/json",
        "Referer": "https://leetcode.com",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    ca_bundle = get_ca_bundle()

    for attempt in range(1, max_retries + 1):
        try:
            time.sleep(0.3)
            kwargs: Dict[str, Any] = {"timeout": 8.0}
            if ca_bundle:
                kwargs["verify"] = ca_bundle
            resp = requests.post(
                LEETCODE_GRAPHQL_URL,
                json=payload,
                headers=headers,
                **kwargs,
            )
            resp.raise_for_status()
            data = resp.json()
            q = (data.get("data") or {}).get("question")
            if q and q.get("questionFrontendId"):
                return q
        except Exception as e:
            logger.debug(f"Question metadata fetch for {title_slug} attempt {attempt} failed: {e}")
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
        "Referer": "https://leetcode.com",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    ca_bundle = get_ca_bundle()

    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            time.sleep(LEETCODE_RATE_LIMIT_DELAY)
            kwargs: Dict[str, Any] = {"timeout": 10.0}
            if ca_bundle:
                kwargs["verify"] = ca_bundle

            response = requests.post(
                LEETCODE_GRAPHQL_URL,
                json=payload,
                headers=headers,
                **kwargs,
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
        cur = conn.execute("SELECT problem_id, slug, difficulty, topics_json FROM problems")
        existing_problem_rows = {row["slug"]: dict(row) for row in cur.fetchall()}

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

            # Match slug to existing problem in DB
            prob_info = existing_problem_rows.get(slug)
            problem_id = prob_info["problem_id"] if prob_info else None
            needs_meta = (
                not prob_info
                or prob_info.get("difficulty") in ("unknown", None)
                or prob_info.get("topics_json") in ("[]", None)
            )

            if needs_meta and not force_offline and not is_stale_fallback:
                meta = fetch_question_metadata(slug)
                if meta and meta.get("questionFrontendId"):
                    try:
                        real_id = int(meta["questionFrontendId"])
                        q_title = meta.get("title") or title
                        q_diff = meta.get("difficulty") or "Medium"
                        q_topics = [t["name"] for t in meta.get("topicTags", []) if t.get("name")]
                        q_topics_json = json.dumps(q_topics)

                        conn.execute(
                            """
                            INSERT INTO problems (
                                problem_id, title, slug, url, difficulty, topics_json,
                                premium_status, source, verified_at
                            ) VALUES (?, ?, ?, ?, ?, ?, 0, 'leetcode_sync', ?)
                            ON CONFLICT(problem_id) DO UPDATE SET
                                title = excluded.title,
                                slug = excluded.slug,
                                url = excluded.url,
                                difficulty = excluded.difficulty,
                                topics_json = excluded.topics_json,
                                verified_at = excluded.verified_at
                            """,
                            (
                                real_id,
                                q_title,
                                slug,
                                f"https://leetcode.com/problems/{slug}/",
                                q_diff,
                                q_topics_json,
                                utc_now_iso(),
                            ),
                        )
                        problem_id = real_id
                        existing_problem_rows[slug] = {
                            "problem_id": real_id,
                            "slug": slug,
                            "difficulty": q_diff,
                            "topics_json": q_topics_json,
                        }
                    except (ValueError, TypeError) as e:
                        logger.debug(f"Failed parsing questionFrontendId for {slug}: {e}")

            if not problem_id:
                # If problem still not resolved, assign next synthetic ID
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
                existing_problem_rows[slug] = {
                    "problem_id": problem_id,
                    "slug": slug,
                    "difficulty": "unknown",
                    "topics_json": "[]",
                }

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

        # Ingest overall tagProblemCounts from matchedUser if available
        user_data = (raw_data.get("data") or {}).get("matchedUser") or {}
        tag_counts = user_data.get("tagProblemCounts") or {}
        if tag_counts and isinstance(tag_counts, dict):
            now_iso = utc_now_iso()
            for cat_name, tag_list in tag_counts.items():
                if isinstance(tag_list, list):
                    for t in tag_list:
                        tag_name = t.get("tagName", "")
                        count = t.get("problemsSolved", 0)
                        if count > 0:
                            canonical_topics = get_canonical_patterns([tag_name])
                            for c_topic in canonical_topics:
                                conn.execute(
                                    """
                                    INSERT INTO topic_stats (
                                        topic, mastery_score, exposure_count, success_rate,
                                        last_practised_at, evidence_count, updated_at
                                    ) VALUES (?, ?, ?, 1.0, ?, ?, ?)
                                    ON CONFLICT(topic) DO UPDATE SET
                                        exposure_count = MAX(topic_stats.exposure_count, excluded.exposure_count),
                                        evidence_count = MAX(topic_stats.evidence_count, excluded.evidence_count),
                                        mastery_score = CASE
                                            WHEN excluded.exposure_count >= 20 THEN MAX(topic_stats.mastery_score, 85.0)
                                            WHEN excluded.exposure_count >= 10 THEN MAX(topic_stats.mastery_score, 70.0)
                                            WHEN excluded.exposure_count >= 5 THEN MAX(topic_stats.mastery_score, 55.0)
                                            ELSE topic_stats.mastery_score
                                        END,
                                        updated_at = excluded.updated_at
                                    """,
                                    (
                                        c_topic,
                                        50.0 if count < 10 else 75.0,
                                        count,
                                        now_iso,
                                        count,
                                        now_iso,
                                    ),
                                )

        completed_at = utc_now_iso()
        conn.execute(
            """
            INSERT INTO sync_runs (
                source, started_at, completed_at, records_seen, records_added, status, error_summary
            ) VALUES ('leetcode_graphql', ?, ?, ?, ?, ?, ?)
            """,
            (started_at, completed_at, total_seen, records_added, status, error_summary),
        )

    # Recompute topic statistics with the fresh activity events
    try:
        refresh_topic_stats(db_path=db_path)
    except Exception as e:
        logger.warning(f"Post-sync topic stats refresh warning: {e}")

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
