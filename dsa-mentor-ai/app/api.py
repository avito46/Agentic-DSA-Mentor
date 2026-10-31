"""Localhost-only Flask HTTP API for DSA Mentor AI."""

import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

from app.config import (
    API_HOST,
    API_PORT,
    BASE_DIR,
    DB_PATH,
    logger,
)
from app.db import get_connection, init_db, utc_now_iso
from app.catalogue import load_catalogue, get_problem, list_problems
from app.recommender import select_daily_problem, get_current_date_in_tz
from app.mentor import get_daily_mentor_message, get_hint_ladder, review_user_approach
from app.feedback import record_feedback, VALID_OUTCOMES, VALID_BLOCKERS, VALID_RATINGS
from app.pattern_analyzer import analyze_pattern_gaps
from app.leetcode_client import sync_leetcode_history
from scripts.metrics_30day import compute_30day_metrics


def create_app(custom_db_path: Optional[Path] = None) -> Flask:
    """Factory creating configured Flask application."""
    dist_folder = BASE_DIR / "dashboard" / "dist"
    app = Flask(
        __name__,
        static_folder=str(dist_folder) if dist_folder.exists() else None,
        static_url_path="/",
    )
    # Enable CORS for local development (e.g. Vite dev server on localhost:5173)
    CORS(app, resources={r"/api/*": {"origins": ["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:5000", "http://127.0.0.1:5000"]}})

    active_db = Path(custom_db_path) if custom_db_path else DB_PATH

    @app.route("/api/health", methods=["GET"])
    def health():
        return jsonify({
            "status": "healthy",
            "timestamp": utc_now_iso(),
            "database": str(active_db),
        })

    @app.route("/api/today", methods=["GET"])
    def get_today_recommendation():
        """Returns today's daily recommendation with reason, score breakdown, and coaching ladder."""
        date_str = request.args.get("date") or get_current_date_in_tz()
        try:
            rec = select_daily_problem(target_date=date_str, db_path=active_db)
            if rec.get("status") == "no_candidates":
                return jsonify(rec), 200

            # Fetch or generate coaching hints
            coaching = get_daily_mentor_message(
                problem=rec,
                reason=rec.get("reason", ""),
                db_path=active_db,
            )
            return jsonify({
                "recommendation": rec,
                "coaching": coaching,
            }), 200
        except Exception as e:
            logger.error(f"Error fetching today's recommendation: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/hints/<int:problem_id>", methods=["GET"])
    def get_hints_for_problem(problem_id: int):
        """Retrieve 3-step hint ladder for specific problem."""
        prob = get_problem(problem_id, db_path=active_db)
        if not prob:
            return jsonify({"error": f"Problem {problem_id} not found"}), 404
        hints = get_hint_ladder(prob, db_path=active_db)
        return jsonify(hints), 200

    @app.route("/api/topics", methods=["GET"])
    def get_topics_mastery():
        """Return topic stats, category groupings, and pattern gaps."""
        try:
            conn = get_connection(active_db)
            cur = conn.execute(
                """
                SELECT topic, mastery_score, exposure_count, success_rate,
                       last_practised_at, evidence_count, updated_at
                FROM topic_stats
                ORDER BY mastery_score ASC
                """
            )
            topics = [dict(r) for r in cur.fetchall()]
            conn.close()

            gaps = analyze_pattern_gaps(db_path=active_db)
            return jsonify({
                "topics": topics,
                "category_analysis": gaps.get("categories", {}),
                "unpracticed_patterns": gaps.get("unpracticed_patterns", []),
            }), 200
        except Exception as e:
            logger.error(f"Error fetching topic stats: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/history", methods=["GET"])
    def get_history():
        """Return recent practice events and past recommendations."""
        limit = min(100, int(request.args.get("limit", 50)))
        try:
            conn = get_connection(active_db)
            events_cur = conn.execute(
                """
                SELECT ae.event_id, ae.problem_id, ae.event_type, ae.occurred_at,
                       ae.source, ae.time_spent, ae.hints_used, ae.self_rating, ae.blocker,
                       p.title, p.difficulty, p.slug, p.url, p.topics_json
                FROM activity_events ae
                JOIN problems p ON ae.problem_id = p.problem_id
                ORDER BY ae.occurred_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            events = []
            for r in events_cur.fetchall():
                d = dict(r)
                d["topics"] = json.loads(d["topics_json"])
                events.append(d)

            recs_cur = conn.execute(
                """
                SELECT dr.date, dr.problem_id, dr.score, dr.score_breakdown_json,
                       dr.reason, dr.status, dr.generated_at,
                       p.title, p.difficulty, p.url
                FROM daily_recommendations dr
                JOIN problems p ON dr.problem_id = p.problem_id
                ORDER BY dr.date DESC
                LIMIT ?
                """,
                (limit,),
            )
            recs = []
            for r in recs_cur.fetchall():
                d = dict(r)
                d["score_breakdown"] = json.loads(d["score_breakdown_json"])
                recs.append(d)

            conn.close()
            return jsonify({
                "activity_events": events,
                "recommendations": recs,
            }), 200
        except Exception as e:
            logger.error(f"Error fetching history: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/feedback", methods=["POST"])
    def submit_feedback():
        """
        Record feedback from practice session and adapt learner model.
        Strict input validation on trust boundary.
        """
        data = request.get_json(silent=True)
        if not data or not isinstance(data, dict):
            return jsonify({"error": "Request body must be a valid JSON object"}), 400

        problem_id = data.get("problem_id")
        if not isinstance(problem_id, int) or problem_id <= 0:
            return jsonify({"error": "Valid positive integer problem_id is required"}), 400

        outcome = str(data.get("outcome", "")).strip().lower()
        if outcome not in VALID_OUTCOMES:
            return jsonify({"error": f"Invalid outcome '{outcome}'. Must be one of: {sorted(list(VALID_OUTCOMES))}"}), 400

        minutes = data.get("minutes", 0)
        try:
            minutes = max(0, int(minutes))
        except (ValueError, TypeError):
            minutes = 0

        hints_used = data.get("hints_used", 0)
        try:
            hints_used = max(0, min(3, int(hints_used)))
        except (ValueError, TypeError):
            hints_used = 0

        rating = data.get("perceived_difficulty")
        confidence = data.get("confidence", 3)
        try:
            confidence = max(1, min(5, int(confidence)))
        except (ValueError, TypeError):
            confidence = 3

        blocker = data.get("blocker")

        try:
            result = record_feedback(
                problem_id=problem_id,
                outcome=outcome,
                minutes=minutes,
                hints_used=hints_used,
                perceived_difficulty=rating,
                confidence=confidence,
                blocker=blocker,
                db_path=active_db,
            )
            return jsonify(result), 200
        except ValueError as ve:
            return jsonify({"error": str(ve)}), 400
        except Exception as e:
            logger.error(f"Error processing feedback: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/sync/status", methods=["GET"])
    def get_sync_status():
        """Retrieve recent sync runs and staleness indicator."""
        conn = get_connection(active_db)
        cur = conn.execute(
            """
            SELECT sync_id, source, started_at, completed_at, records_seen, records_added, status, error_summary
            FROM sync_runs
            ORDER BY sync_id DESC
            LIMIT 5
            """
        )
        runs = [dict(r) for r in cur.fetchall()]
        conn.close()

        latest = runs[0] if runs else None
        is_stale = latest and latest.get("status") in ("stale_fallback", "failed", "partial_response")
        return jsonify({
            "latest_sync": latest,
            "is_stale": bool(is_stale),
            "recent_runs": runs,
        }), 200

    @app.route("/api/sync/trigger", methods=["POST"])
    def trigger_sync():
        """Trigger LeetCode profile sync (read-only)."""
        force_offline = request.args.get("offline", "false").lower() == "true"
        try:
            res = sync_leetcode_history(db_path=active_db, force_offline=force_offline)
            return jsonify(res), 200
        except Exception as e:
            return jsonify({"status": "failed", "error": str(e)}), 500

    @app.route("/api/metrics", methods=["GET"])
    def get_metrics():
        """Return rolling 30-day health metrics."""
        try:
            metrics = compute_30day_metrics(db_path=active_db)
            return jsonify(metrics), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # Serve React SPA if dist folder exists
    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def serve_frontend(path):
        if dist_folder.exists() and (dist_folder / path).is_file():
            return send_from_directory(str(dist_folder), path)
        elif dist_folder.exists():
            return send_from_directory(str(dist_folder), "index.html")
        return jsonify({
            "service": "DSA Mentor AI API",
            "status": "running",
            "message": "Frontend build not generated yet. Use Vite dev server or run npm run build in ./dashboard",
        })

    return app


def run_api_server(host: str = "127.0.0.1", port: int = 5000):
    """Run API server strictly bound to localhost."""
    # Enforce localhost security hard stop
    if host not in ("127.0.0.1", "localhost"):
        logger.warning(f"Binding overridden to 127.0.0.1 for security (was {host})")
        host = "127.0.0.1"

    app = create_app()
    init_db()
    try:
        load_catalogue()
    except Exception:
        pass

    logger.info(f"Starting DSA Mentor AI API server on http://{host}:{port} (Localhost only)")
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    run_api_server(API_HOST, API_PORT)
