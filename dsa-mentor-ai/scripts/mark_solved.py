"""Quickly mark one or more LeetCode problems as solved by problem_id or slug."""

import sys
from pathlib import Path
from datetime import datetime, timezone

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import argparse
from app.db import get_db, utc_now_iso
from app.config import logger
from app.learner_model import refresh_topic_stats
from app.leetcode_client import fetch_question_metadata


def mark_problems_solved(problem_identifiers: list[str], db_path: Path = None):
    with get_db(db_path) as conn:
        for ident in problem_identifiers:
            ident = ident.strip().strip(",")
            if not ident:
                continue

            # Check if it's integer ID
            prob_row = None
            if ident.isdigit():
                pid = int(ident)
                prob_row = conn.execute(
                    "SELECT problem_id, title, slug FROM problems WHERE problem_id = ?",
                    (pid,)
                ).fetchone()
            else:
                slug = ident.lower().replace(" ", "-")
                prob_row = conn.execute(
                    "SELECT problem_id, title, slug FROM problems WHERE slug = ?",
                    (slug,)
                ).fetchone()

            if not prob_row:
                # Try fetching metadata from LeetCode
                slug_to_fetch = ident.lower().replace(" ", "-")
                meta = fetch_question_metadata(slug_to_fetch)
                if meta and meta.get("questionFrontendId"):
                    real_id = int(meta["questionFrontendId"])
                    title = meta.get("title") or ident
                    diff = meta.get("difficulty") or "Medium"
                    import json
                    topics = [t["name"] for t in meta.get("topicTags", []) if t.get("name")]
                    conn.execute(
                        """
                        INSERT INTO problems (problem_id, title, slug, url, difficulty, topics_json, premium_status, source, verified_at)
                        VALUES (?, ?, ?, ?, ?, ?, 0, 'manual_mark', ?)
                        ON CONFLICT(problem_id) DO UPDATE SET title=excluded.title
                        """,
                        (real_id, title, slug_to_fetch, f"https://leetcode.com/problems/{slug_to_fetch}/", diff, json.dumps(topics), utc_now_iso())
                    )
                    prob_id = real_id
                    title = title
                else:
                    print(f"Warning: Could not find or resolve problem '{ident}'. Skipping.")
                    continue
            else:
                prob_id = prob_row["problem_id"]
                title = prob_row["title"]

            # Insert solved event into activity_events
            conn.execute(
                """
                INSERT INTO activity_events (problem_id, event_type, occurred_at, source)
                VALUES (?, 'solved', ?, 'manual_mark')
                """,
                (prob_id, utc_now_iso())
            )
            print(f"Marked as SOLVED: #{prob_id} - {title}")

    refresh_topic_stats(db_path=db_path)
    print("Updated learner model topic statistics.")


def main():
    parser = argparse.ArgumentParser(description="Mark LeetCode problems as solved.")
    parser.add_argument("problems", nargs="+", help="Problem IDs or slugs to mark as solved (e.g. 1 15 20 or two-sum)")
    parser.add_argument("--db", default=None, help="Custom SQLite database path")
    args = parser.parse_args()

    # Flatten if commas were passed inside arguments
    raw_list = []
    for p in args.problems:
        raw_list.extend(p.split(","))

    mark_problems_solved(raw_list, db_path=args.db)


if __name__ == "__main__":
    main()
