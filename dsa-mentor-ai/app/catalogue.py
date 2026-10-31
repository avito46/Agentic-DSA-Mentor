"""Problem Catalogue loader and query service."""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from app.db import get_db, utc_now_iso
from app.config import CATALOGUE_PATH, logger

VALID_DIFFICULTIES = {"Easy", "Medium", "Hard"}


def validate_problem_dict(p: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and normalize a raw problem record. Never invent tags or difficulty."""
    problem_id = p.get("problem_id")
    if not isinstance(problem_id, int) or problem_id <= 0:
        raise ValueError(f"Invalid problem_id: {problem_id}")

    title = str(p.get("title", "")).strip()
    if not title:
        raise ValueError(f"Missing title for problem {problem_id}")

    slug = str(p.get("slug", "")).strip()
    if not slug:
        raise ValueError(f"Missing slug for problem {problem_id}")

    url = str(p.get("url", "")).strip()
    if not url.startswith("http"):
        url = f"https://leetcode.com/problems/{slug}/"

    difficulty = str(p.get("difficulty", "")).capitalize()
    if difficulty not in VALID_DIFFICULTIES:
        # Never invent difficulty; use unknown
        difficulty = "unknown"

    raw_topics = p.get("topics")
    if isinstance(raw_topics, list):
        topics = [str(t).strip() for t in raw_topics if str(t).strip()]
    elif isinstance(raw_topics, str) and raw_topics.strip():
        # Fallback if provided as comma-separated or json string
        try:
            parsed = json.loads(raw_topics)
            topics = [str(t).strip() for t in parsed if str(t).strip()]
        except Exception:
            topics = [t.strip() for t in raw_topics.split(",") if t.strip()]
    else:
        topics = []

    premium_status = 1 if p.get("premium_status") in (1, True, "1") else 0
    source = str(p.get("source", "custom")).strip() or "custom"
    verified_at = str(p.get("verified_at", "")).strip() or utc_now_iso()

    return {
        "problem_id": problem_id,
        "title": title,
        "slug": slug,
        "url": url,
        "difficulty": difficulty,
        "topics_json": json.dumps(topics),
        "premium_status": premium_status,
        "source": source,
        "verified_at": verified_at,
    }


def load_catalogue(file_path: Optional[Path] = None, db_path: Optional[Path] = None) -> int:
    """Load verified problems from a JSON file into the database. Returns count inserted/updated."""
    path = Path(file_path) if file_path else CATALOGUE_PATH
    if not path.is_file():
        raise FileNotFoundError(f"Catalogue file not found at {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("Catalogue JSON root must be a list of problem objects")

    records = [validate_problem_dict(item) for item in data]

    with get_db(db_path) as conn:
        for r in records:
            conn.execute(
                """
                INSERT INTO problems (
                    problem_id, title, slug, url, difficulty, topics_json,
                    premium_status, source, verified_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(problem_id) DO UPDATE SET
                    title=excluded.title,
                    slug=excluded.slug,
                    url=excluded.url,
                    difficulty=excluded.difficulty,
                    topics_json=excluded.topics_json,
                    premium_status=excluded.premium_status,
                    source=excluded.source,
                    verified_at=excluded.verified_at;
                """,
                (
                    r["problem_id"],
                    r["title"],
                    r["slug"],
                    r["url"],
                    r["difficulty"],
                    r["topics_json"],
                    r["premium_status"],
                    r["source"],
                    r["verified_at"],
                ),
            )

    logger.info(f"Loaded {len(records)} problems into catalogue from {path}")
    return len(records)


def get_problem(problem_id: int, db_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Retrieve problem by ID from the database."""
    with get_db(db_path) as conn:
        cur = conn.execute("SELECT * FROM problems WHERE problem_id = ?", (problem_id,))
        row = cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["topics"] = json.loads(d["topics_json"])
        return d


def list_problems(db_path: Optional[Path] = None, free_only: bool = True) -> List[Dict[str, Any]]:
    """List all problems from the catalogue database."""
    query = "SELECT * FROM problems"
    if free_only:
        query += " WHERE premium_status = 0"
    query += " ORDER BY problem_id ASC"

    with get_db(db_path) as conn:
        cur = conn.execute(query)
        rows = cur.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["topics"] = json.loads(d["topics_json"])
            result.append(d)
        return result
