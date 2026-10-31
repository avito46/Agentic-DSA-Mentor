"""Local AI Mentor via Ollama with strict prompt contracts, JSON validation, and deterministic template fallback."""

import json
import time
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional
import requests

from app.db import get_db, utc_now_iso
from app.config import (
    OLLAMA_HOST,
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT_SECONDS,
    logger,
)

PROMPT_VERSION = "1.0.0"

SYSTEM_PROMPT = """You are DSA Mentor AI, a focused, disciplined algorithmic coach.
Strict Contract Rules:
1. Use ONLY the supplied verified problem metadata (title, URL, difficulty, topics, problem_id) and learner profile.
2. NEVER invent problem titles, URLs, tags, constraints, or test cases.
3. NEVER provide full solution code unless explicitly requested.
4. If any metadata is missing, state it is unknown.
5. You must output ONLY valid, parseable JSON matching the requested schema. No conversational preamble or postscript.
"""


def sanitize_untrusted_input(text: str) -> str:
    """Sanitize user-pasted text/code to neutralize prompt injection attempts."""
    if not text:
        return ""
    # Strip potential delimiter / instruction overrides
    cleaned = re.sub(r"(?i)(ignore previous instructions|system\s*prompt:|system:)", "[FILTERED]", text)
    # Truncate overly long pastes (max 4000 chars)
    if len(cleaned) > 4000:
        cleaned = cleaned[:4000] + "... [TRUNCATED]"
    return cleaned.strip()


def validate_json_schema(data: Any, task: str) -> bool:
    """Validate JSON schema based on the specific task."""
    if not isinstance(data, dict):
        return False
    if task == "daily_message":
        required = ["greeting", "why_selected", "learning_target", "hint_1", "hint_2", "approach_outline"]
        return all(k in data and isinstance(data[k], str) and data[k].strip() for k in required)
    elif task == "hint_ladder":
        required = ["hint_1", "hint_2", "approach_outline"]
        return all(k in data and isinstance(data[k], str) and data[k].strip() for k in required)
    elif task == "approach_review":
        required = ["strengths", "potential_pitfalls", "refinement_suggestion"]
        return all(k in data for k in required)
    elif task == "weekly_summary":
        required = ["strengths", "weak_areas", "priorities", "summary"]
        return all(k in data for k in required)
    return True


def log_model_run(
    task: str,
    latency_ms: int,
    success: bool,
    model_name: str = OLLAMA_MODEL,
    db_path: Optional[Path] = None,
) -> None:
    """Record execution telemetry in model_runs table."""
    try:
        with get_db(db_path) as conn:
            conn.execute(
                """
                INSERT INTO model_runs (
                    model_name, prompt_version, task, latency_ms, success, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    model_name,
                    PROMPT_VERSION,
                    task,
                    latency_ms,
                    1 if success else 0,
                    utc_now_iso(),
                ),
            )
    except Exception as e:
        logger.error(f"Failed to log model run to database: {e}")


# shortcut: Fallback to deterministic template when Ollama daemon is absent, upgrade: Revisit if local GPU hardware is configured
def generate_template_fallback(
    task: str,
    problem: Optional[Dict[str, Any]] = None,
    reason: Optional[str] = None,
    extra_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Deterministic template fallback when Ollama is offline or returns invalid JSON.
    Guaranteed to always succeed using only verified catalogue metadata.
    """
    prob = problem or {}
    title = prob.get("title", "Selected DSA Problem")
    diff = prob.get("difficulty", "Standard")
    topics = prob.get("topics", [])
    topic_str = ", ".join(topics) if topics else "Algorithm Design"
    rec_reason = reason or "Selected based on topic mastery profile and spaced revision."

    if task == "daily_message":
        return {
            "greeting": f"Good morning! Ready for today's challenge: {title}?",
            "why_selected": rec_reason,
            "learning_target": f"Mastery and execution speed in {topic_str} ({diff} difficulty).",
            "core_concept": f"Optimal state tracking and constraint bounds in {topic_str}.",
            "hint_1": f"Start by identifying the invariants. What properties remain true across iterations?",
            "hint_2": f"Consider the time-space tradeoff: could a hash table, two pointers, or auxiliary array reduce complexity?",
            "approach_outline": "1. Clarify constraints and edge cases (e.g. empty inputs, negative numbers).\n2. Formulate the brute-force baseline and measure its bottleneck.\n3. Apply the canonical pattern to eliminate redundant scans.\n4. Trace with a small example before coding.",
            "call_to_action": f"Head over to LeetCode and solve {title}. When finished, log your minutes and hints in the dashboard!",
        }

    elif task == "hint_ladder":
        return {
            "hint_1": "Level 1 (Nudge): Identify the core invariant and constraint limits.",
            "hint_2": f"Level 2 (Pattern): Think about how {topic_str} patterns structure the subproblems.",
            "approach_outline": "Level 3 (Approach Outline): Break down the state transitions, maintain necessary pointers/indices, and verify termination conditions.",
        }

    elif task == "approach_review":
        return {
            "strengths": ["Structured formulation of the problem components."],
            "potential_pitfalls": ["Check boundary conditions, empty/single-element bounds, and integer overflow."],
            "time_complexity": "Review the inner loop iterations to ensure no hidden O(N^2) bottlenecks.",
            "space_complexity": "O(1) auxiliary space preferred if in-place pointer manipulation is feasible.",
            "refinement_suggestion": "Dry-run the algorithm against extreme edge cases before final implementation.",
        }

    elif task == "weekly_summary":
        return {
            "strengths": ["Consistent practice engagement across core foundational structures."],
            "weak_areas": ["Edge-case handling in medium-tier techniques under time constraints."],
            "priorities": ["Continue targeted reinforcement on high-weakness topics before advancing difficulty."],
            "summary": "Solid progress maintained this week with steady execution discipline.",
        }

    return {"status": "fallback_complete"}


def query_ollama(
    prompt: str,
    task: str,
    problem: Optional[Dict[str, Any]] = None,
    reason: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Execute query against local Ollama instance.
    Validates output JSON; seamlessly defaults to template fallback if Ollama is unreachable.
    """
    start_time = time.time()
    url = f"{OLLAMA_HOST}/api/generate"
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "system": SYSTEM_PROMPT,
        "format": "json",
        "stream": False,
        "options": {
            "temperature": 0.2,
            "num_ctx": 2048,
        },
    }

    try:
        response = requests.post(
            url,
            json=payload,
            timeout=(1.0, float(OLLAMA_TIMEOUT_SECONDS)),
        )
        latency_ms = int((time.time() - start_time) * 1000)

        if response.status_code == 200:
            res_json = response.json()
            raw_content = res_json.get("response", "").strip()
            # Parse JSON
            parsed = json.loads(raw_content)
            if validate_json_schema(parsed, task):
                log_model_run(task, latency_ms, True, db_path=db_path)
                return parsed
            else:
                logger.warning(f"Ollama returned invalid schema for task '{task}'. Using template fallback.")
        else:
            logger.warning(f"Ollama HTTP error {response.status_code}. Using template fallback.")

    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        logger.info(f"Ollama offline or timed out ({e}). Using deterministic template fallback.")

    # Fallback path
    latency_ms = int((time.time() - start_time) * 1000)
    log_model_run(task, latency_ms, False, db_path=db_path)
    return generate_template_fallback(task, problem, reason)


def get_daily_mentor_message(
    problem: Dict[str, Any],
    reason: str,
    learner_profile: Optional[Dict[str, Any]] = None,
    db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Generate daily coaching message and 3-step hint ladder for a recommended problem."""
    topics = problem.get("topics", [])
    prompt = f"""Generate a structured daily mentoring message for today's selected problem.
Problem Details (Verified):
- ID: {problem.get('problem_id')}
- Title: {problem.get('title')}
- Difficulty: {problem.get('difficulty')}
- URL: {problem.get('url')}
- Topics: {', '.join(topics)}
- Selection Reason: {reason}

Return a JSON object with:
{{
  "greeting": "Energizing short greeting mentioning the problem title",
  "why_selected": "1-2 sentences explaining why this fits their learning trajectory",
  "learning_target": "The specific algorithmic outcome or pattern to master today",
  "core_concept": "The underlying mathematical or computer science concept",
  "hint_1": "Subtle nudge (invariant or initial observation)",
  "hint_2": "Pattern recognition guidance (how to transform the data structure)",
  "approach_outline": "Numbered high-level algorithm steps (NO solution code)",
  "call_to_action": "Clear encouragement to solve and submit feedback"
}}
"""
    return query_ollama(prompt, "daily_message", problem, reason, db_path=db_path)


def get_hint_ladder(
    problem: Dict[str, Any],
    db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Retrieve 3-step progressive hint ladder for problem."""
    prompt = f"""Generate a 3-step progressive hint ladder for the following problem.
Problem: {problem.get('title')} ({problem.get('difficulty')})
Topics: {', '.join(problem.get('topics', []))}

Return JSON:
{{
  "hint_1": "Subtle nudge",
  "hint_2": "Pattern-level clue",
  "approach_outline": "Algorithmic outline steps without code"
}}
"""
    return query_ollama(prompt, "hint_ladder", problem, db_path=db_path)


def review_user_approach(
    problem: Dict[str, Any],
    user_approach: str,
    db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Safely review user-pasted approach with prompt injection protection."""
    safe_approach = sanitize_untrusted_input(user_approach)
    prompt = f"""Review the user's proposed approach for {problem.get('title')} ({problem.get('difficulty')}).
User's proposed approach:
<user_untrusted_input>
{safe_approach}
</user_untrusted_input>

Return JSON:
{{
  "strengths": ["list of positive aspects"],
  "potential_pitfalls": ["edge cases or potential bottlenecks"],
  "time_complexity": "Expected time complexity analysis",
  "space_complexity": "Expected auxiliary space complexity",
  "refinement_suggestion": "Actionable feedback to improve implementation"
}}
"""
    return query_ollama(prompt, "approach_review", problem, db_path=db_path)
