"""Deterministic problem recommendation engine for DSA Mentor AI."""

import json
import hashlib
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from app.db import get_db, utc_now_iso
from app.config import (
    RECOMMENDER_WEIGHTS,
    RECOMMENDER_BUCKETS,
    REPEAT_PENALTY,
    EXCESSIVE_DIFFICULTY_PENALTY,
    COOLDOWN_DAYS_SKIP,
    COOLDOWN_DAYS_FAILED,
    PREFERRED_DIFFICULTIES,
    TIMEZONE,
    logger,
)
from app.learner_model import refresh_topic_stats
from app.pattern_analyzer import get_canonical_patterns


def get_current_date_in_tz(tz_name: Optional[str] = None) -> str:
    """Get current date formatted as YYYY-MM-DD in the user's local timezone (Asia/Kolkata)."""
    target_tz_str = tz_name or TIMEZONE
    try:
        tz = ZoneInfo(target_tz_str)
    except Exception:
        tz = timezone.utc
    return datetime.now(tz).strftime("%Y-%m-%d")


def compute_stable_tie_break(target_date: str, problem_id: int) -> int:
    """Stable deterministic integer hash for tie-breaking: sha256(date + problem_id)."""
    payload = f"{target_date}:{problem_id}".encode("utf-8")
    return int(hashlib.sha256(payload).hexdigest()[:12], 16)


def evaluate_candidate_problem(
    problem: Dict[str, Any],
    topic_stats_map: Dict[str, Dict[str, Any]],
    recent_events_map: Dict[int, List[Dict[str, Any]]],
    target_date: str,
) -> Dict[str, Any]:
    """
    Computes normalized score components and penalties for a candidate problem.
    All positive terms are in [0, 1].
    Strictly pattern-aligned: prioritizes problems that build upon and continue the
    user's demonstrated practice patterns while penalizing completely unstudied alien topics.
    """
    topics = problem.get("topics", [])
    canonical_topics = get_canonical_patterns(topics)
    problem_id = problem["problem_id"]
    difficulty = problem.get("difficulty", "Medium")

    # Check if this is a cold start (no solved history in entire database)
    total_db_exposure = sum(ts.get("exposure_count", 0) for ts in topic_stats_map.values())
    is_cold_start = (total_db_exposure == 0)

    # Check if candidate matches any topic the user has actually practiced
    practiced_canonical = [
        t for t in canonical_topics if topic_stats_map.get(t, {}).get("exposure_count", 0) > 0
    ]
    has_practiced_in_pattern = len(practiced_canonical) > 0 or is_cold_start

    # 1. Topic Weakness & Recency
    weakness_values = []
    recency_values = []
    for t in canonical_topics:
        ts = topic_stats_map.get(t)
        if ts and ts.get("exposure_count", 0) > 0:
            mastery = ts.get("mastery_score", 0.0)
            weakness_values.append(max(0.2, (100.0 - mastery) / 100.0))
            last_practised = ts.get("last_practised_at")
            if last_practised:
                try:
                    dt = datetime.fromisoformat(last_practised)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    days = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0)
                    rec_score = max(0.0, 1.0 - (days / 30.0))
                    recency_values.append(rec_score)
                except Exception:
                    recency_values.append(0.5)
            else:
                recency_values.append(0.5)
        else:
            if is_cold_start:
                weakness_values.append(0.8)
                recency_values.append(0.0)
            else:
                # Unstudied topic: low weakness so alien topics do not dominate
                weakness_values.append(0.15)
                recency_values.append(0.0)

    # Base weakness on practiced topics if any exist
    practiced_weaknesses = [w for w, t in zip(weakness_values, canonical_topics) if topic_stats_map.get(t, {}).get("exposure_count", 0) > 0]
    topic_weakness = sum(practiced_weaknesses) / len(practiced_weaknesses) if practiced_weaknesses else (sum(weakness_values) / len(weakness_values) if weakness_values else 0.2)

    # Revision due & Active Pattern Momentum
    if has_practiced_in_pattern:
        max_rec = max(recency_values) if recency_values else 0.5
        # Strong bonus for continuing an active recent practice streak (e.g. Linked List in last 3 days)
        revision_due = 0.50 + 0.50 * max_rec
    else:
        revision_due = 0.10

    # 2. Difficulty fit: evaluate match against topic difficulty ceiling
    highest_ceiling = "None"
    has_medium_solves = False
    for t in canonical_topics:
        ts = topic_stats_map.get(t, {})
        ceil = ts.get("difficulty_ceiling", "None")
        if "Hard" in ceil:
            highest_ceiling = "Hard"
            has_medium_solves = True
        elif "Medium" in ceil and highest_ceiling != "Hard":
            highest_ceiling = "Medium"
            has_medium_solves = True
        elif "Easy" in ceil and highest_ceiling == "None":
            highest_ceiling = "Easy"

    # Also check overall user medium solve history
    total_medium_solves = sum(
        1 for evs in recent_events_map.values()
        for e in evs if e.get("event_type") == "solved" and e.get("difficulty") == "Medium"
    )
    if total_medium_solves >= 2:
        has_medium_solves = True

    if difficulty == "Easy":
        difficulty_fit = 1.0 if is_cold_start or highest_ceiling in ("None", "Easy") else 0.5
    elif difficulty == "Medium":
        difficulty_fit = 1.0 if has_medium_solves or highest_ceiling in ("Easy", "Medium") else 0.7
    elif difficulty == "Hard":
        difficulty_fit = 0.8 if has_medium_solves else 0.25
    else:
        difficulty_fit = 0.5

    # 3. Pattern Learning Value: highest for active learning track within solved patterns
    if is_cold_start:
        pattern_learning_value = 0.8
    elif not has_practiced_in_pattern:
        # Alien topic out of user's active pattern tracks
        pattern_learning_value = 0.15
    else:
        learning_vals = []
        for t in canonical_topics:
            exp = topic_stats_map.get(t, {}).get("exposure_count", 0)
            if 1 <= exp <= 12:
                # Active learning track (sweet spot: foundational reinforcement & level up)
                learning_vals.append(1.0)
            elif 13 <= exp <= 25:
                learning_vals.append(0.8)
            elif exp > 25:
                # High exposure (e.g. Array with 53 solves)
                learning_vals.append(0.55)
            else:
                learning_vals.append(0.2)
        pattern_learning_value = max(learning_vals) if learning_vals else 0.5

    # 4. Confidence fit
    confidence_fit = 0.7

    # 5. Novelty
    problem_events = recent_events_map.get(problem_id, [])
    has_attempt = any(e.get("event_type") in ("attempted", "failed") for e in problem_events)
    novelty = 0.3 if has_attempt else 1.0

    # 6. Penalties
    repeat_penalty = 0.0
    if problem_events:
        repeat_penalty = REPEAT_PENALTY

    excessive_difficulty_penalty = 0.0
    if difficulty == "Hard" and not has_medium_solves:
        excessive_difficulty_penalty = EXCESSIVE_DIFFICULTY_PENALTY

    # Composite score
    w = RECOMMENDER_WEIGHTS
    raw_score = (
        w["topic_weakness"] * topic_weakness
        + w["revision_due"] * revision_due
        + w["difficulty_fit"] * difficulty_fit
        + w["pattern_learning_value"] * pattern_learning_value
        + w["confidence_fit"] * confidence_fit
        + w["novelty"] * novelty
        - repeat_penalty
        - excessive_difficulty_penalty
    )
    final_score = round(raw_score, 4)

    tie_break = compute_stable_tie_break(target_date, problem_id)

    # Primary reason generation
    reasons = []
    if practiced_canonical:
        reasons.append(f"Advancing your active practice pattern ({', '.join(practiced_canonical[:2])})")
    elif is_cold_start:
        reasons.append(f"Targeting growth in core DSA pattern: {canonical_topics[0] if canonical_topics else 'core'}")
    if pattern_learning_value >= 0.8:
        reasons.append(f"Optimal level-up problem matching your solved history")
    if revision_due >= 0.7:
        reasons.append("Reinforcing momentum from recent successful submissions")

    if not reasons:
        reasons.append(f"Optimal difficulty match ({difficulty}) for current problem-solving momentum")

    primary_reason = ". ".join(reasons)

    breakdown = {
        "topic_weakness": round(topic_weakness, 3),
        "revision_due": round(revision_due, 3),
        "difficulty_fit": round(difficulty_fit, 3),
        "pattern_learning_value": round(pattern_learning_value, 3),
        "confidence_fit": round(confidence_fit, 3),
        "novelty": round(novelty, 3),
        "repeat_penalty": round(repeat_penalty, 3),
        "excessive_difficulty_penalty": round(excessive_difficulty_penalty, 3),
        "final_score": final_score,
    }

    return {
        "problem": problem,
        "score": final_score,
        "tie_break": tie_break,
        "score_breakdown": breakdown,
        "reason": primary_reason,
    }


def select_daily_problem(
    target_date: Optional[str] = None,
    db_path: Optional[Path] = None,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """
    Selects exactly ONE verified, unsolved problem for target_date.
    Idempotent: if target_date already has a recommendation, returns it.
    Deterministic tie-breaking ensures identical outputs across runs.
    """
    date_str = target_date or get_current_date_in_tz()

    with get_db(db_path) as conn:
        # Step 1: Idempotency check - if already generated for date_str, return it
        if not force_refresh:
            cur = conn.execute(
                """
                SELECT dr.date, dr.problem_id, dr.score, dr.score_breakdown_json,
                       dr.reason, dr.status, dr.generated_at,
                       p.title, p.slug, p.url, p.difficulty, p.topics_json
                FROM daily_recommendations dr
                JOIN problems p ON dr.problem_id = p.problem_id
                WHERE dr.date = ?
                """,
                (date_str,),
            )
            existing = cur.fetchone()
            if existing:
                res = dict(existing)
                res["topics"] = json.loads(res["topics_json"])
                res["score_breakdown"] = json.loads(res["score_breakdown_json"])
                logger.info(f"Retrieved existing daily recommendation for {date_str}: Problem {res['problem_id']} ({res['title']})")
                return res

        # Refresh learner model statistics
        topic_stats = refresh_topic_stats(db_path=db_path)

        # Step 2: Load candidate problems from verified catalogue
        all_problems_cur = conn.execute(
            """
            SELECT problem_id, title, slug, url, difficulty, topics_json, premium_status, source, verified_at
            FROM problems
            WHERE premium_status = 0
            """
        )
        all_problems = []
        for r in all_problems_cur.fetchall():
            d = dict(r)
            d["topics"] = json.loads(d["topics_json"])
            all_problems.append(d)

        # Step 3: Filter out already solved problems (activity_events 'solved' or 'imported')
        solved_cur = conn.execute(
            """
            SELECT DISTINCT problem_id FROM activity_events
            WHERE event_type IN ('solved', 'imported')
            """
        )
        solved_ids = {r["problem_id"] for r in solved_cur.fetchall()}

        # Step 4: Check cooldowns (skips: 3 days, failed: 5 days)
        now_dt = datetime.now(timezone.utc)
        skip_threshold = (now_dt - timedelta(days=COOLDOWN_DAYS_SKIP)).isoformat()
        failed_threshold = (now_dt - timedelta(days=COOLDOWN_DAYS_FAILED)).isoformat()

        cooldown_cur = conn.execute(
            """
            SELECT problem_id, event_type, occurred_at FROM activity_events
            WHERE (event_type = 'skipped' AND occurred_at >= ?)
               OR (event_type = 'failed' AND occurred_at >= ?)
            """,
            (skip_threshold, failed_threshold),
        )
        cooldown_ids = {r["problem_id"] for r in cooldown_cur.fetchall()}

        # Filter candidate pool
        eligible = []
        for p in all_problems:
            pid = p["problem_id"]
            if pid in solved_ids:
                continue
            if pid in cooldown_ids:
                continue
            if not p["url"].startswith("http"):
                continue
            if not p["topics"]:
                continue
            eligible.append(p)

        # Apply user difficulty preference if configured (e.g. Medium, Hard)
        if PREFERRED_DIFFICULTIES:
            preferred = [p for p in eligible if p.get("difficulty") in PREFERRED_DIFFICULTIES]
            if preferred:
                eligible = preferred
                logger.info(
                    f"Filtered candidate pool to preferred difficulties ({', '.join(PREFERRED_DIFFICULTIES)}): {len(eligible)} remaining"
                )

        if not eligible:
            logger.warning("No eligible candidate problems remain in catalogue.")
            return {
                "status": "no_candidates",
                "date": date_str,
                "reason": "All catalogue problems are solved or currently on cooldown. Please import additional catalogue problems to continue practice.",
                "problem_id": None,
            }

        # Step 5: Load recent events map for candidates to check attempt history
        recent_cur = conn.execute(
            "SELECT ae.problem_id, ae.event_type, ae.occurred_at, p.difficulty FROM activity_events ae JOIN problems p ON ae.problem_id = p.problem_id"
        )
        recent_events_map: Dict[int, List[Dict[str, Any]]] = {}
        for r in recent_cur.fetchall():
            recent_events_map.setdefault(r["problem_id"], []).append(dict(r))

        # Step 6: Evaluate each candidate problem
        scored_candidates = [
            evaluate_candidate_problem(p, topic_stats, recent_events_map, date_str)
            for p in eligible
        ]

        # Step 7: Sort deterministically by (-score, tie_break)
        scored_candidates.sort(key=lambda x: (-x["score"], x["tie_break"]))

        # Pick top candidate
        top_pick = scored_candidates[0]
        picked_prob = top_pick["problem"]
        score = top_pick["score"]
        score_breakdown_json = json.dumps(top_pick["score_breakdown"])
        reason = top_pick["reason"]
        generated_at = utc_now_iso()

        # Step 8: Save to daily_recommendations (enforcing UNIQUE date)
        conn.execute(
            """
            INSERT INTO daily_recommendations (
                date, problem_id, score, score_breakdown_json, reason, status, generated_at
            ) VALUES (?, ?, ?, ?, ?, 'pending', ?)
            ON CONFLICT(date) DO UPDATE SET
                problem_id = excluded.problem_id,
                score = excluded.score,
                score_breakdown_json = excluded.score_breakdown_json,
                reason = excluded.reason,
                status = excluded.status,
                generated_at = excluded.generated_at
            """,
            (
                date_str,
                picked_prob["problem_id"],
                score,
                score_breakdown_json,
                reason,
                generated_at,
            ),
        )

        logger.info(
            f"Selected daily problem for {date_str}: Problem {picked_prob['problem_id']} "
            f"({picked_prob['title']}) with score {score:.4f}"
        )

        return {
            "date": date_str,
            "problem_id": picked_prob["problem_id"],
            "title": picked_prob["title"],
            "slug": picked_prob["slug"],
            "url": picked_prob["url"],
            "difficulty": picked_prob["difficulty"],
            "topics": picked_prob["topics"],
            "score": score,
            "score_breakdown": top_pick["score_breakdown"],
            "reason": reason,
            "status": "pending",
            "generated_at": generated_at,
        }
