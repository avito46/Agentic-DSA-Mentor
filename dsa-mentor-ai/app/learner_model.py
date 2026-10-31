"""Learner Model: Estimates topic-level mastery, weakness, and practice signals."""

import math
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from app.db import get_db, utc_now_iso
from app.config import MASTERY_WEIGHTS, logger
from app.pattern_analyzer import get_canonical_patterns


def calculate_recency_score(last_practised_iso: Optional[str]) -> Optional[float]:
    """Calculate 0-100 recency score using a 30-day half-life decay. None if never practiced."""
    if not last_practised_iso:
        return None
    try:
        dt = datetime.fromisoformat(last_practised_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        days = max(0.0, (now - dt).total_seconds() / 86400.0)
        # 30-day exponential half-life: 100 at day 0, 50 at day 30, 25 at day 60
        score = 100.0 * math.exp(-0.0231 * days)
        return max(0.0, min(100.0, score))
    except Exception:
        return None


def calculate_difficulty_ceiling_score(solves_by_difficulty: Dict[str, int]) -> float:
    """
    Difficulty ceiling is based on the highest difficulty solved MORE THAN ONCE.
    Hard (2+ solves): 100
    Medium (2+ solves): 75
    Easy (2+ solves): 40
    Single solves provide baseline credit: Hard(1)=60, Med(1)=45, Easy(1)=25.
    """
    hard_count = solves_by_difficulty.get("Hard", 0)
    med_count = solves_by_difficulty.get("Medium", 0)
    easy_count = solves_by_difficulty.get("Easy", 0)

    if hard_count >= 2:
        return 100.0
    if med_count >= 2:
        return 75.0
    if easy_count >= 2:
        return 40.0

    # Single solve baselines
    if hard_count >= 1:
        return 60.0
    if med_count >= 1:
        return 45.0
    if easy_count >= 1:
        return 25.0
    return 0.0


def calculate_hint_score(hint_counts: List[int]) -> Optional[float]:
    """
    Calculates low-hint performance (0-100).
    0 hints = 100
    1 hint = 65
    2 hints = 35
    3+ (editorial) = 10
    None if no feedback records with hint data exist.
    """
    if not hint_counts:
        return None
    scores = []
    for h in hint_counts:
        if h == 0:
            scores.append(100.0)
        elif h == 1:
            scores.append(65.0)
        elif h == 2:
            scores.append(35.0)
        else:
            scores.append(10.0)
    return sum(scores) / len(scores)


def calculate_confidence_score(ratings: List[str]) -> Optional[float]:
    """
    Maps self_rating ['easy', 'right', 'hard'] to 0-100 score.
    easy -> 100
    right -> 75
    hard -> 40
    None if no self_rating data exists.
    """
    if not ratings:
        return None
    mapping = {"easy": 100.0, "right": 75.0, "hard": 40.0}
    scores = [mapping[r] for r in ratings if r in mapping]
    if not scores:
        return None
    return sum(scores) / len(scores)


def compute_weighted_mastery(components: Dict[str, Optional[float]]) -> float:
    """
    Computes weighted mastery score (0-100).
    If any component is missing (None), redistributes weights proportionally among present components.
    If no components are present, returns 0.0.
    """
    valid_items = {k: v for k, v in components.items() if v is not None and k in MASTERY_WEIGHTS}
    if not valid_items:
        return 0.0

    total_weight = sum(MASTERY_WEIGHTS[k] for k in valid_items)
    if total_weight <= 0.0:
        return 0.0

    weighted_sum = sum(valid_items[k] * (MASTERY_WEIGHTS[k] / total_weight) for k in valid_items)
    return max(0.0, min(100.0, round(weighted_sum, 1)))


def calculate_topic_mastery(
    events: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Calculate full mastery signals for a single topic from its activity events.
    Handles empty, sparse, imported-only, and conflicting history.
    """
    exposure_count = len(events)
    if exposure_count == 0:
        return {
            "mastery_score": 0.0,
            "weakness_score": 100.0,
            "exposure_count": 0,
            "evidence_count": 0,
            "success_rate": 0.0,
            "is_insufficient_evidence": True,
            "difficulty_ceiling": "None",
            "last_practised_at": None,
            "components": {},
        }

    # Meaningful attempts: solved, attempted, failed, imported
    meaningful_events = [e for e in events if e.get("event_type") in ("solved", "attempted", "failed", "imported")]
    evidence_count = len(meaningful_events)
    is_insufficient_evidence = evidence_count < 3

    # Check if history is imported-only
    imported_only = all(e.get("source") == "import" for e in meaningful_events)

    # 1. Success Rate Component
    if imported_only:
        # Spec: imported-only = unknown
        success_component = None
        success_rate = 0.0
    else:
        # Feedback or sync present
        solves = sum(1 for e in meaningful_events if e.get("event_type") in ("solved", "imported"))
        attempts = sum(1 for e in meaningful_events if e.get("event_type") in ("solved", "attempted", "failed", "imported"))
        success_rate = solves / attempts if attempts > 0 else 0.0
        success_component = success_rate * 100.0

    # 2. Recency Component
    latest_dt = None
    for e in events:
        occ = e.get("occurred_at")
        if occ:
            if latest_dt is None or occ > latest_dt:
                latest_dt = occ
    recency_component = calculate_recency_score(latest_dt)

    # 3. Difficulty Evidence Component
    solves_by_diff = {"Easy": 0, "Medium": 0, "Hard": 0}
    for e in meaningful_events:
        if e.get("event_type") in ("solved", "imported"):
            diff = e.get("difficulty")
            if diff in solves_by_diff:
                solves_by_diff[diff] += 1

    difficulty_component = calculate_difficulty_ceiling_score(solves_by_diff)
    if solves_by_diff["Hard"] >= 2:
        diff_ceiling = "Hard"
    elif solves_by_diff["Medium"] >= 2:
        diff_ceiling = "Medium"
    elif solves_by_diff["Easy"] >= 2:
        diff_ceiling = "Easy"
    elif solves_by_diff["Hard"] == 1:
        diff_ceiling = "Hard (1x)"
    elif solves_by_diff["Medium"] == 1:
        diff_ceiling = "Medium (1x)"
    elif solves_by_diff["Easy"] == 1:
        diff_ceiling = "Easy (1x)"
    else:
        diff_ceiling = "None"

    # 4. Low-Hint Component
    hints_list = [e["hints_used"] for e in events if e.get("hints_used") is not None and e.get("source") == "manual_feedback"]
    low_hint_component = calculate_hint_score(hints_list)

    # 5. Confidence Component
    ratings_list = [e["self_rating"] for e in events if e.get("self_rating") and e.get("source") == "manual_feedback"]
    confidence_component = calculate_confidence_score(ratings_list)

    components = {
        "success": success_component,
        "recency": recency_component,
        "difficulty": difficulty_component,
        "low_hint": low_hint_component,
        "confidence": confidence_component,
    }

    mastery_score = compute_weighted_mastery(components)
    weakness_score = round(100.0 - mastery_score, 1)

    return {
        "mastery_score": mastery_score,
        "weakness_score": weakness_score,
        "exposure_count": exposure_count,
        "evidence_count": evidence_count,
        "success_rate": round(success_rate, 2),
        "is_insufficient_evidence": is_insufficient_evidence,
        "difficulty_ceiling": diff_ceiling,
        "last_practised_at": latest_dt,
        "components": components,
    }


def refresh_topic_stats(db_path: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    """
    Recompute topic statistics across all topics in the database and persist to topic_stats table.
    """
    with get_db(db_path) as conn:
        # Fetch all activity events joined with problem topics and difficulty
        cur = conn.execute(
            """
            SELECT ae.event_id, ae.problem_id, ae.event_type, ae.occurred_at,
                   ae.source, ae.runtime_ms, ae.hints_used, ae.self_rating,
                   ae.time_spent, p.difficulty, p.topics_json
            FROM activity_events ae
            JOIN problems p ON ae.problem_id = p.problem_id
            ORDER BY ae.occurred_at ASC
            """
        )
        events = [dict(r) for r in cur.fetchall()]

        # Group events by canonical topic
        topic_events_map: Dict[str, List[Dict[str, Any]]] = {}
        for ev in events:
            topics = json.loads(ev.get("topics_json") or "[]")
            canonical_topics = get_canonical_patterns(topics)
            for t in canonical_topics:
                topic_events_map.setdefault(t, []).append(ev)

        # Also ensure all taxonomy topics are represented
        from app.pattern_analyzer import TAXONOMY
        for cat, items in TAXONOMY.items():
            for item in items:
                topic_events_map.setdefault(item, [])

        updated_stats = {}
        now_iso = utc_now_iso()

        for topic, t_events in topic_events_map.items():
            stat = calculate_topic_mastery(t_events)
            updated_stats[topic] = stat

            conn.execute(
                """
                INSERT INTO topic_stats (
                    topic, mastery_score, exposure_count, success_rate,
                    last_practised_at, evidence_count, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(topic) DO UPDATE SET
                    mastery_score = excluded.mastery_score,
                    exposure_count = excluded.exposure_count,
                    success_rate = excluded.success_rate,
                    last_practised_at = excluded.last_practised_at,
                    evidence_count = excluded.evidence_count,
                    updated_at = excluded.updated_at
                """,
                (
                    topic,
                    stat["mastery_score"],
                    stat["exposure_count"],
                    stat["success_rate"],
                    stat["last_practised_at"],
                    stat["evidence_count"],
                    now_iso,
                ),
            )

    logger.info(f"Refreshed stats for {len(updated_stats)} topics in learner model.")
    return updated_stats
