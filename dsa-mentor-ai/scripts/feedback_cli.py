"""CLI tool to capture daily problem-solving feedback and trigger adaptation."""

import sys
from pathlib import Path

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import argparse
from app.db import get_connection, init_db
from app.catalogue import load_catalogue
from app.recommender import get_current_date_in_tz
from app.feedback import record_feedback, VALID_OUTCOMES, VALID_BLOCKERS


def main():
    parser = argparse.ArgumentParser(description="Submit feedback for DSA Mentor AI session.")
    parser.add_argument("--problem", type=int, default=None, help="Problem ID (defaults to today's recommendation)")
    parser.add_argument("--outcome", choices=list(VALID_OUTCOMES), default=None, help="Session outcome")
    parser.add_argument("--minutes", type=int, default=None, help="Time spent in minutes")
    parser.add_argument("--hints", type=int, choices=[0, 1, 2, 3], default=None, help="Hints used (0, 1, 2, 3=editorial)")
    parser.add_argument("--rating", choices=["easy", "right", "hard", "too easy", "too hard"], default=None, help="Perceived difficulty")
    parser.add_argument("--confidence", type=int, choices=[1, 2, 3, 4, 5], default=None, help="Confidence rating (1-5)")
    parser.add_argument("--blocker", choices=[b for b in VALID_BLOCKERS if b], default=None, help="Main blocker category")
    parser.add_argument("--db", default=None, help="Custom database path")
    args = parser.parse_args()

    conn = get_connection(args.db)
    today = get_current_date_in_tz()

    # If problem ID not provided, find today's recommendation
    problem_id = args.problem
    if not problem_id:
        cur = conn.execute(
            """
            SELECT dr.problem_id, p.title
            FROM daily_recommendations dr
            JOIN problems p ON dr.problem_id = p.problem_id
            WHERE dr.date = ?
            """,
            (today,),
        )
        row = cur.fetchone()
        if row:
            problem_id = row["problem_id"]
            print(f"Submitting feedback for today's problem: #{problem_id} - {row['title']}")
        else:
            print(f"No daily recommendation found for date {today}. Please specify --problem <ID>")
            sys.exit(1)
    conn.close()

    # Prompt interactively if missing arguments
    outcome = args.outcome
    if not outcome:
        print("\nSelect Outcome:")
        print("  1. Solved")
        print("  2. Attempted (made progress but didn't finish)")
        print("  3. Stuck (hit a wall / couldn't solve)")
        print("  4. Skipped (busy / skipped today)")
        choice = input("Enter choice (1-4) [1]: ").strip() or "1"
        mapping = {"1": "solved", "2": "attempted", "3": "stuck", "4": "skipped"}
        outcome = mapping.get(choice, "solved")

    minutes = args.minutes
    if minutes is None:
        raw_min = input("Minutes spent [25]: ").strip() or "25"
        try:
            minutes = int(raw_min)
        except ValueError:
            minutes = 25

    hints = args.hints
    if hints is None:
        raw_hints = input("Hints used (0, 1, 2, 3=editorial) [0]: ").strip() or "0"
        try:
            hints = int(raw_hints)
        except ValueError:
            hints = 0

    rating = args.rating
    if not rating:
        print("\nPerceived difficulty:")
        print("  1. Too Easy")
        print("  2. Just Right")
        print("  3. Too Hard")
        c = input("Enter choice (1-3) [2]: ").strip() or "2"
        rating_map = {"1": "easy", "2": "right", "3": "hard"}
        rating = rating_map.get(c, "right")

    confidence = args.confidence
    if confidence is None:
        raw_c = input("Confidence rating (1=Lost to 5=Mastered) [3]: ").strip() or "3"
        try:
            confidence = int(raw_c)
        except ValueError:
            confidence = 3

    blocker = args.blocker
    if not blocker and outcome in ("attempted", "stuck"):
        print("\nMain blocker:")
        print("  1. Concept / Missing theory")
        print("  2. Implementation / Syntax / Data structure mechanics")
        print("  3. Edge cases / Off-by-one errors")
        print("  4. Time complexity / Optimization")
        print("  5. Time shortage")
        b_c = input("Enter choice (1-5) [1]: ").strip() or "1"
        b_map = {
            "1": "concept",
            "2": "implementation",
            "3": "edge cases",
            "4": "complexity",
            "5": "time",
        }
        blocker = b_map.get(b_c, "concept")

    res = record_feedback(
        problem_id=problem_id,
        outcome=outcome,
        minutes=minutes,
        hints_used=hints,
        perceived_difficulty=rating,
        confidence=confidence,
        blocker=blocker,
        db_path=args.db,
    )

    print("\n=== FEEDBACK RECORDED ===")
    print(f"Problem: #{res['problem_id']} - {res['title']}")
    print(f"Outcome: {res['outcome'].upper()}")
    print(f"Adaptation: {res['adaptation_summary']}")
    print(f"Updated Topic Mastery: {res['updated_mastery']:.1f}% (Weakness: {res['updated_weakness']:.1f}%)")
    print("=========================\n")


if __name__ == "__main__":
    main()
