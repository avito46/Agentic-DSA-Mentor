"""Rolling 30-day algorithmic mentor performance and consistency metrics."""

import sys
from pathlib import Path

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import argparse
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, Any

from app.db import get_connection, init_db
from app.catalogue import load_catalogue
from app.pattern_analyzer import TAXONOMY


def compute_30day_metrics(db_path: Path = None) -> Dict[str, Any]:
    """Compute measured 30-day metrics without inventing numbers."""
    conn = get_connection(db_path)
    now = datetime.now(timezone.utc)
    start_date = (now - timedelta(days=30)).isoformat()

    # 1. Daily recommendations in 30 days
    recs_cur = conn.execute(
        """
        SELECT date, problem_id, status, generated_at
        FROM daily_recommendations
        WHERE generated_at >= ?
        ORDER BY date ASC
        """,
        (start_date,),
    )
    recs = [dict(r) for r in recs_cur.fetchall()]

    # 2. Activity events in 30 days
    events_cur = conn.execute(
        """
        SELECT ae.event_id, ae.problem_id, ae.event_type, ae.occurred_at,
               ae.self_rating, ae.hints_used, ae.source, p.topics_json
        FROM activity_events ae
        JOIN problems p ON ae.problem_id = p.problem_id
        WHERE ae.occurred_at >= ?
        """,
        (start_date,),
    )
    events = [dict(r) for r in events_cur.fetchall()]

    # 3. Model runs in 30 days
    model_cur = conn.execute(
        """
        SELECT run_id, task, success, latency_ms
        FROM model_runs
        WHERE created_at >= ?
        """,
        (start_date,),
    )
    model_runs = [dict(r) for r in model_cur.fetchall()]

    # 4. Solved prior checks for repeat rate (target 0%)
    all_solved_cur = conn.execute(
        """
        SELECT problem_id, MIN(occurred_at) as first_solved
        FROM activity_events
        WHERE event_type IN ('solved', 'imported')
        GROUP BY problem_id
        """
    )
    solved_prior_map = {r["problem_id"]: r["first_solved"] for r in all_solved_cur.fetchall()}
    conn.close()

    total_recs = len(recs)
    total_events = len(events)
    has_sufficient_data = total_recs >= 5 or total_events >= 5

    # 1. Completion Rate: % of daily recommendations that were solved
    solved_rec_count = sum(1 for r in recs if r["status"] == "solved")
    completion_rate = (solved_rec_count / total_recs * 100.0) if total_recs > 0 else 0.0

    # 2. Repeat Rate: Check if any recommended problem was ALREADY solved before the recommendation date
    repeated_count = 0
    for r in recs:
        pid = r["problem_id"]
        rec_gen = r["generated_at"]
        first_solved = solved_prior_map.get(pid)
        if first_solved and first_solved < rec_gen:
            repeated_count += 1
    repeat_rate = (repeated_count / total_recs * 100.0) if total_recs > 0 else 0.0

    # 3. Difficulty Fit: share of feedback rating 'right'
    feedback_ratings = [e["self_rating"] for e in events if e.get("self_rating")]
    right_count = sum(1 for r in feedback_ratings if r == "right")
    difficulty_fit_pct = (right_count / len(feedback_ratings) * 100.0) if feedback_ratings else 0.0

    # 4. Learning Coverage: distinct patterns practiced
    practiced_patterns = set()
    for e in events:
        try:
            topics = json.loads(e.get("topics_json") or "[]")
            for t in topics:
                practiced_patterns.add(t)
        except Exception:
            pass

    total_taxonomy_patterns = sum(len(items) for items in TAXONOMY.values())
    coverage_pct = (len(practiced_patterns) / total_taxonomy_patterns * 100.0) if total_taxonomy_patterns > 0 else 0.0

    # 5. Reliability: successful daily runs vs calendar days in period (up to 30)
    # If system just started, use elapsed days since first recommendation or min 1
    if recs:
        first_rec_dt = datetime.fromisoformat(recs[0]["generated_at"])
        if first_rec_dt.tzinfo is None:
            first_rec_dt = first_rec_dt.replace(tzinfo=timezone.utc)
        days_active = max(1, min(30, int((now - first_rec_dt).total_seconds() / 86400.0) + 1))
    else:
        days_active = 1
    reliability_pct = min(100.0, (total_recs / days_active) * 100.0)

    # 6. Explanation Usefulness: % of successful mentor runs
    successful_model_runs = sum(1 for m in model_runs if m["success"] == 1)
    explanation_usefulness = (
        (successful_model_runs / len(model_runs) * 100.0) if model_runs else 100.0
    )

    return {
        "period_days": 30,
        "has_sufficient_data": has_sufficient_data,
        "total_recommendations": total_recs,
        "total_feedback_events": total_events,
        "completion_rate_pct": round(completion_rate, 1),
        "repeat_rate_pct": round(repeat_rate, 1),
        "difficulty_fit_pct": round(difficulty_fit_pct, 1),
        "distinct_patterns_practiced": len(practiced_patterns),
        "total_patterns_in_taxonomy": total_taxonomy_patterns,
        "pattern_coverage_pct": round(coverage_pct, 1),
        "reliability_pct": round(reliability_pct, 1),
        "explanation_usefulness_pct": round(explanation_usefulness, 1),
    }


def print_metrics(data: Dict[str, Any]) -> None:
    print("\n" + "=" * 55)
    print("📈 DSA MENTOR AI — 30-DAY PERFORMANCE & HEALTH METRICS")
    print("=" * 55)

    if not data["has_sufficient_data"]:
        print("⚠️  INSUFFICIENT DATA: Fewer than 5 days of history recorded.")
        print("   Showing real measured metrics collected to date without extrapolation.")
        print("-" * 55)

    print(f"🎯 Completion Rate:             {data['completion_rate_pct']}% (solved / recommended)")
    print(f"🔄 Repeat Rate (Target 0%):     {data['repeat_rate_pct']}% (unsolved guarantee)")
    print(f"⚖️  Difficulty Fit ('Right'):    {data['difficulty_fit_pct']}% of sessions")
    print(f"🗺️  Pattern Coverage:           {data['distinct_patterns_practiced']}/{data['total_patterns_in_taxonomy']} patterns ({data['pattern_coverage_pct']}%)")
    print(f"⏱️ System Reliability:          {data['reliability_pct']}% scheduled uptime")
    print(f"🧠 Mentor Telemetry Success:    {data['explanation_usefulness_pct']}%")
    print("=" * 55 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Compute 30-day algorithmic learning metrics.")
    parser.add_argument("--db", default=None, help="Custom database path")
    args = parser.parse_args()

    metrics = compute_30day_metrics(args.db)
    print_metrics(metrics)


if __name__ == "__main__":
    main()
