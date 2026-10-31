"""Weekly Progress & Strategic Focus Report generator."""

import sys
from pathlib import Path

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import argparse
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List

from app.db import get_connection, init_db
from app.catalogue import load_catalogue
from app.pattern_analyzer import TAXONOMY


def generate_weekly_report_data(db_path: Path = None) -> Dict[str, Any]:
    """Calculate measured weekly performance numbers without hallucinating or inventing data."""
    conn = get_connection(db_path)
    now = datetime.now(timezone.utc)
    week_ago = (now - timedelta(days=7)).isoformat()

    # 1. Recent activity events
    cur = conn.execute(
        """
        SELECT ae.event_id, ae.problem_id, ae.event_type, ae.occurred_at,
               ae.time_spent, ae.hints_used, ae.self_rating, ae.blocker,
               p.title, p.difficulty, p.topics_json
        FROM activity_events ae
        JOIN problems p ON ae.problem_id = p.problem_id
        WHERE ae.occurred_at >= ?
        ORDER BY ae.occurred_at DESC
        """,
        (week_ago,),
    )
    events = [dict(r) for r in cur.fetchall()]

    # 2. Daily recommendations in past 7 days
    rec_cur = conn.execute(
        """
        SELECT date, problem_id, score, reason, status
        FROM daily_recommendations
        WHERE generated_at >= ?
        ORDER BY date DESC
        """,
        (week_ago,),
    )
    recommendations = [dict(r) for r in rec_cur.fetchall()]

    # 3. Topic stats
    topic_cur = conn.execute(
        "SELECT topic, mastery_score, exposure_count, success_rate, last_practised_at, evidence_count FROM topic_stats"
    )
    all_topics = [dict(r) for r in topic_cur.fetchall()]
    conn.close()

    total_attempts = len(events)
    solves = [e for e in events if e["event_type"] in ("solved", "imported")]
    stuck = [e for e in events if e["event_type"] == "failed"]
    skips = [e for e in events if e["event_type"] == "skipped"]

    total_minutes = sum((e["time_spent"] or 0) for e in events)

    # Topic breakdown
    strengths = [t for t in all_topics if t["mastery_score"] >= 70.0 and t["evidence_count"] >= 3]
    weak_areas = [t for t in all_topics if t["mastery_score"] < 40.0 and t["evidence_count"] >= 1]
    unpracticed = [t for t in all_topics if t["exposure_count"] == 0]

    # Priorities
    priorities = []
    if weak_areas:
        top_weak = sorted(weak_areas, key=lambda x: x["mastery_score"])[:3]
        for w in top_weak:
            priorities.append(f"Reinforce {w['topic']} (Mastery: {w['mastery_score']:.1f}%) with foundational problems.")
    if stuck:
        recent_blockers = [e["blocker"] for e in stuck if e.get("blocker")]
        if recent_blockers:
            priorities.append(f"Address recurring blocker '{recent_blockers[0]}' via focused conceptual review.")
    if not priorities:
        priorities.append("Continue regular daily cadence; maintain balance across core data structures.")

    has_sufficient_data = total_attempts >= 3

    return {
        "period_start": week_ago[:10],
        "period_end": now.isoformat()[:10],
        "has_sufficient_data": has_sufficient_data,
        "total_attempts": total_attempts,
        "solves_count": len(solves),
        "stuck_count": len(stuck),
        "skipped_count": len(skips),
        "total_minutes": total_minutes,
        "avg_minutes_per_solve": round(total_minutes / len(solves), 1) if solves else 0.0,
        "strengths": strengths,
        "weak_areas": weak_areas,
        "priorities": priorities,
    }


def print_weekly_report(data: Dict[str, Any]) -> None:
    print("\n" + "=" * 55)
    print(f"📊 DSA MENTOR AI — WEEKLY REPORT ({data['period_start']} to {data['period_end']})")
    print("=" * 55)

    if not data["has_sufficient_data"]:
        print("⚠️  NOTICE: Insufficient data recorded this week (< 3 sessions).")
        print("   Metrics below reflect raw recorded activity so far.")
        print("-" * 55)

    print(f"🎯 Total Sessions Recorded: {data['total_attempts']}")
    print(f"✅ Solved: {data['solves_count']}  |  🛑 Stuck/Failed: {data['stuck_count']}  |  ⏭️ Skipped: {data['skipped_count']}")
    print(f"⏱️ Total Time Invested: {data['total_minutes']} minutes (avg {data['avg_minutes_per_solve']} min/solve)")
    print("-" * 55)

    print("🏆 STRENGTHS (Mastery >= 70% with verified evidence):")
    if data["strengths"]:
        for s in data["strengths"][:5]:
            print(f"  • {s['topic']}: {s['mastery_score']:.1f}% mastery ({s['exposure_count']} exposures)")
    else:
        print("  • Insufficient evidence to establish mastery ceilings yet.")

    print("\n⚠️ AREAS NEEDING ATTENTION (Weakness / Low Success):")
    if data["weak_areas"]:
        for w in data["weak_areas"][:5]:
            print(f"  • {w['topic']}: {w['mastery_score']:.1f}% mastery ({w['evidence_count']} attempts)")
    else:
        print("  • No high-urgency weak areas flagged.")

    print("\n🎯 TOP STRATEGIC PRIORITIES:")
    for i, p in enumerate(data["priorities"], 1):
        print(f"  {i}. {p}")
    print("=" * 55 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Generate weekly progress and strategic priorities report.")
    parser.add_argument("--db", default=None, help="Custom database path")
    args = parser.parse_args()

    data = generate_weekly_report_data(args.db)
    print_weekly_report(data)


if __name__ == "__main__":
    main()
