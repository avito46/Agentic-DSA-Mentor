"""Pattern taxonomy and structural pattern analyzer for DSA Mentor AI."""

import json
from typing import Dict, List, Set, Any, Optional
from pathlib import Path
from app.db import get_db

# Canonical DSA Taxonomy
TAXONOMY: Dict[str, List[str]] = {
    "Data Structures": [
        "Array",
        "String",
        "Hash Table",
        "Linked List",
        "Stack",
        "Queue",
        "Tree",
        "Binary Tree",
        "Binary Search Tree",
        "Heap (Priority Queue)",
        "Graph",
        "Trie",
        "Matrix",
        "Union Find",
    ],
    "Core Techniques": [
        "Two Pointers",
        "Sliding Window",
        "Binary Search",
        "Prefix Sum",
        "Divide and Conquer",
        "Greedy",
        "Backtracking",
        "Recursion",
        "Sorting",
        "Bit Manipulation",
        "Quickselect",
        "Monotonic Stack",
    ],
    "Dynamic Programming Types": [
        "Dynamic Programming",
        "1D Dynamic Programming",
        "2D Dynamic Programming",
        "Memoization",
        "State Machine DP",
        "Knapsack",
    ],
    "Graph Techniques": [
        "Depth-First Search",
        "Breadth-First Search",
        "Topological Sort",
        "Shortest Path",
        "Minimum Spanning Tree",
        "Bipartite Graph",
    ],
}

# Inverted index: topic/pattern -> category
CATEGORY_LOOKUP: Dict[str, str] = {}
for cat, items in TAXONOMY.items():
    for item in items:
        CATEGORY_LOOKUP[item.lower()] = cat


def get_canonical_patterns(topics: List[str]) -> List[str]:
    """Map raw problem tags to canonical pattern names."""
    canonical = []
    for t in topics:
        clean = t.strip()
        # Find exact or case-insensitive match
        matched = False
        for cat, items in TAXONOMY.items():
            for item in items:
                if clean.lower() == item.lower():
                    canonical.append(item)
                    matched = True
                    break
            if matched:
                break
        if not matched:
            canonical.append(clean)
    return sorted(list(set(canonical)))


def analyze_pattern_gaps(db_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Analyze exposure across taxonomy categories and highlight unpracticed or overdue patterns.
    """
    with get_db(db_path) as conn:
        # Get all distinct topics and their stats from topic_stats
        rows = conn.execute(
            """
            SELECT topic, mastery_score, exposure_count, last_practised_at
            FROM topic_stats
            """
        ).fetchall()
        practiced_map = {r["topic"].lower(): dict(r) for r in rows}

        category_analysis = {}
        all_unpracticed = []

        for category, patterns in TAXONOMY.items():
            cat_patterns_data = []
            for pat in patterns:
                stat = practiced_map.get(pat.lower())
                if stat and stat["exposure_count"] > 0:
                    cat_patterns_data.append({
                        "pattern": pat,
                        "status": "practiced",
                        "exposure_count": stat["exposure_count"],
                        "mastery_score": stat["mastery_score"],
                        "last_practised_at": stat["last_practised_at"],
                    })
                else:
                    cat_patterns_data.append({
                        "pattern": pat,
                        "status": "unpracticed",
                        "exposure_count": 0,
                        "mastery_score": 0.0,
                        "last_practised_at": None,
                    })
                    all_unpracticed.append(pat)

            practiced_count = sum(1 for p in cat_patterns_data if p["status"] == "practiced")
            category_analysis[category] = {
                "total_patterns": len(patterns),
                "practiced_patterns": practiced_count,
                "coverage_pct": round((practiced_count / len(patterns)) * 100.0, 1),
                "patterns": cat_patterns_data,
            }

        return {
            "categories": category_analysis,
            "unpracticed_patterns": all_unpracticed,
        }
