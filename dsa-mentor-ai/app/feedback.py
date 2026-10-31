"""Feedback capture, validation, and adaptive learner model calibration."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

from app.db import get_db, utc_now_iso
from app.config import logger
from app.learner_model import refresh_topic_stats

VALID_OUTCOMES = {"solved", "attempted", "stuck", "skipped"}
VALID_RATINGS = {"easy", "right", "hard", "too easy", "too hard"}
VALID_BLOCKERS = {"concept", "implementation", "edge cases", "complexity", "time", None}


def normalize_outcome_to_event(outcome: str) -> str:
    """Map outcome choice to database event_type."""
    clean = outcome.strip().lower()
    if clean == "solved":
        return "solved"
    if clean == "attempted":
        return "attempted"
    if clean == "stuck":
        return "failed"
    if clean == "skipped":
        return "skipped"
    raise ValueError(f"Invalid outcome: {outcome}. Allowed: {VALID_OUTCOMES}")


def normalize_self_rating(rating: Optional[str]) -> Optional[str]:
    """Normalize user perceived difficulty into schema self_rating ('easy', 'right', 'hard')."""
    if not rating:
        return None
    r = rating.strip().lower()
    if r in ("easy", "too easy"):
        return "easy"
    if r == "right":
        return "right"
    if r in ("hard", "too hard"):
        return "hard"
    return None


def record_feedback(
    problem_id: int,
    outcome: str,
    minutes: int,
    hints_used: int = 0,
    perceived_difficulty: Optional[str] = None,
    confidence: int = 3,
    blocker: Optional[str] = None,
    notes: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Record user practice session feedback and adapt learner model.
    Validates all inputs at the trust boundary.
    """
    if not isinstance(problem_id, int) or problem_id <= 0:
        raise ValueError(f"Invalid problem_id: {problem_id}")

    event_type = normalize_outcome_to_event(outcome)
    time_spent = max(0, int(minutes))
    hints = max(0, min(3, int(hints_used)))
    rating = normalize_self_rating(perceived_difficulty)

    clean_blocker = blocker.strip().lower() if blocker else None
    if clean_blocker and clean_blocker not in VALID_BLOCKERS:
        clean_blocker = None

    conf = max(1, min(5, int(confidence)))
    occurred_at = utc_now_iso()

    with get_db(db_path) as conn:
        # Check problem exists
        prob = conn.execute(
            "SELECT problem_id, title, difficulty, topics_json FROM problems WHERE problem_id = ?",
            (problem_id,),
        ).fetchone()
        if not prob:
            raise ValueError(f"Problem {problem_id} does not exist in catalogue")

        # 1. Insert into append-only activity_events
        conn.execute(
            """
            INSERT INTO activity_events (
                problem_id, event_type, occurred_at, source, time_spent,
                hints_used, self_rating, blocker
            ) VALUES (?, ?, ?, 'manual_feedback', ?, ?, ?, ?)
            """,
            (
                problem_id,
                event_type,
                occurred_at,
                time_spent,
                hints,
                rating,
                clean_blocker,
            ),
        )

        # 2. Update status in daily_recommendations if this problem was recommended
        status_update = "solved" if event_type == "solved" else ("skipped" if event_type == "skipped" else "failed")
        conn.execute(
            """
            UPDATE daily_recommendations
            SET status = ?
            WHERE problem_id = ? AND status = 'pending'
            """,
            (status_update, problem_id),
        )

    # 3. Refresh learner model statistics to immediately adapt future recommendations
    updated_stats = refresh_topic_stats(db_path=db_path)

    # Determine adaptation summary message
    topics = json.loads(prob["topics_json"])
    primary_topic = topics[0] if topics else "General"
    topic_stat = updated_stats.get(primary_topic, {})

    adaptation_notes = []
    if event_type == "solved":
        if hints == 0:
            adaptation_notes.append(f"Mastery increased in {primary_topic}. Ready for higher difficulty step.")
        else:
            adaptation_notes.append(f"Solved with hints in {primary_topic}. Scheduling reinforcement problem.")
    elif event_type == "failed":
        adaptation_notes.append(f"Difficulty recalibrated for {primary_topic}: weaker confidence noted; easier prerequisite queued.")
    elif event_type == "skipped":
        adaptation_notes.append("Session skipped (busy/rescheduled). No mastery penalty applied.")

    logger.info(
        f"Recorded feedback for Problem {problem_id} ({outcome}): "
        f"{', '.join(adaptation_notes)}"
    )

    return {
        "status": "success",
        "problem_id": problem_id,
        "title": prob["title"],
        "outcome": outcome,
        "event_type": event_type,
        "adaptation_summary": " ".join(adaptation_notes),
        "updated_mastery": topic_stat.get("mastery_score", 0.0),
        "updated_weakness": topic_stat.get("weakness_score", 100.0),
    }
