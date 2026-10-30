# DSA Mentor AI - Progress & Implementation Tracker

## Overview
A personal, zero-recurring-cost agentic system that imports LeetCode history, estimates topic-level mastery, selects exactly ONE unsolved problem per day, delivers it with a reason and hint ladder, captures feedback, and adapts future recommendations.

---

## Phase Checklist & Definition of Done (DoD)

### [x] Step A: Plan & Specification
- [x] Read and internalize all constraints, hard stops, Ponytail rules, and architectural rules.
- [x] Create `PROGRESS.md` and `BLOCKERS.md`.
- **DoD**: Specifications and progress tracker established before any coding.

---

### [ ] Phase 0: Setup & Foundation
- [ ] Initialize git repo inside `./dsa-mentor-ai` on branch `main` or local feature branch.
- [ ] Setup Python virtual environment (`.venv`) and requirements base.
- [ ] Implement `.env` loader (`app/config.py`) ensuring no secrets are exposed.
- [ ] Configure structured logging with scrubbers for secrets, cookies, tokens, and passwords.
- [ ] Create `.gitignore` ignoring `.env`, `*.db`, `data/raw/`, `.venv/`, `node_modules/`, `dist/`.
- [ ] Create `README.md` skeleton and `.env.example`.
- **DoD**: App configuration boots without errors; secrets and DB paths are git-ignored.

---

### [ ] Phase 1: Data Layer & Ingestion
- [ ] Write `database/schema.sql` with SQLite foreign keys enabled, append-only activity events, ISO 8601 UTC timestamps, and unique constraints.
- [ ] Implement `app/db.py` connection manager and migration/initialization runner.
- [ ] Create verified starter catalogue `data/problems.json` with >= 30 verified LeetCode problems (IDs, titles, slugs, URLs, difficulties, topics, sources, verification dates).
- [ ] Implement `app/catalogue.py` to load, validate, and query the catalogue without invented tags.
- [ ] Implement `app/importer.py` supporting CSV/JSON LeetCode submission history, deduplicating by `problem_id` (not title), and preserving raw import metadata.
- [ ] Implement `app/leetcode_client.py` for read-only public GraphQL profile sync with rate limiting, exponential backoff, raw snapshot caching, stale fallback, and partial response detection.
- [ ] Write unit tests for schema integrity, catalogue validation, CSV/JSON import, and LeetCode client fallback.
- **DoD**: >=95% imported records have stable IDs; duplicates handled cleanly; offline fallback functions on network failure.

---

### [ ] Phase 2: Learner Model & Mastery Engine
- [ ] Define comprehensive taxonomy (Data Structures, Core Techniques, DP Types, Graph Techniques).
- [ ] Implement `app/learner_model.py` calculating per-topic and per-pattern metrics: exposure, success rate, recency, difficulty ceiling, hint dependence, time-to-solve, and confidence.
- [ ] Implement normalized mastery formula (0-100):
  `Mastery = 0.30*success + 0.20*recency + 0.20*difficulty + 0.15*low_hint + 0.15*confidence`
  with proportional redistribution for missing signals, and `Weakness = 100 - Mastery`.
- [ ] Flag topics with < 3 meaningful attempts as "insufficient evidence".
- [ ] Implement `app/pattern_analyzer.py` for structural pattern tracking and gap identification.
- [ ] Unit tests for empty history, sparse history, imported-only (unknown success/hints), conflicting outcomes, and stale practice.
- **DoD**: Learner model outputs validated mastery and weakness profiles across all edge-case history states.

---

### [ ] Phase 3: Deterministic Recommender
- [ ] Implement `app/recommender.py` with strict candidate eligibility:
  - In verified catalogue with working URL
  - Never solved
  - Cooldown active for recent skips or failed repeats
  - Free (not premium)
  - Target difficulty band based on topic ceiling
  - Linked to learner model topics
- [ ] Implement bucket allocations (50% weak-topic, 30% spaced revision, 20% new pattern) with graceful redistribution.
- [ ] Implement composite scoring formula with repeat and excessive-difficulty penalties:
  `score = 0.30*weakness + 0.20*revision_due + 0.20*diff_fit + 0.15*pattern_value + 0.10*conf_fit + 0.05*novelty - penalties`
- [ ] Implement deterministic tie-breaking via stable hash: `hash(date + problem_id)`.
- [ ] Enforce idempotency: exactly ONE problem per day via SQLite `UNIQUE(date)` in `daily_recommendations`.
- [ ] Gracefully handle empty candidate pool with explicit explanation (never force a bad pick).
- [ ] Unit tests for selection reproducibility, exclusion of solved problems, and score breakdown persistence.
- **DoD**: Deterministic selection; identical inputs and date produce identical saved recommendation; solved problems never picked.

---

### [ ] Phase 4: Feedback Loop & Adaptive Calibration
- [ ] Implement `app/feedback.py` and `scripts/feedback_cli.py` capturing outcome, minutes, hints used, perceived difficulty, confidence (1-5), and blocker category.
- [ ] Implement rolling-window adaptation rules:
  - Solved no hints -> maintain or slightly raise difficulty
  - Solved with hints -> same difficulty + schedule reinforcement
  - Stuck -> hint ladder review + easier prerequisite
  - Repeated wrong approach / timeout -> targeted pattern lesson or easier problem (never mark mastered)
  - Skipped (busy) -> no mastery penalty, reschedule
  - Too easy / too hard -> gradual difficulty calibration
- [ ] Unit tests showing feedback demonstrably changes subsequent recommendations.
- **DoD**: Feedback updates learner model and demonstrably shifts future difficulty/topic selection.

---

### [ ] Phase 5: Local AI Mentor & Safe Fallback
- [ ] Implement `app/mentor.py` with Ollama HTTP client (short timeout, small context window).
- [ ] Strict prompt contract: verified metadata only; no hallucinated URLs/tags; never emit full solution by default.
- [ ] Structured JSON output parser and validator for daily message, hint ladder (tiny hint, pattern, approach outline), and approach review.
- [ ] Untrusted input sanitization for user code / problem descriptions.
- [ ] Full deterministic template fallback when Ollama is offline or returns invalid JSON.
- [ ] Telemetry logged to `model_runs` table.
- [ ] Unit tests for valid JSON parsing, malformed JSON recovery, and Ollama offline fallback.
- **DoD**: When Ollama is stopped/unreachable, problem selection succeeds and template message is produced with zero crash.

---

### [ ] Phase 6: Notification & Task Scheduling
- [ ] Implement `app/notifier.py` supporting terminal output and Telegram Bot API (token strictly from `.env`).
- [ ] Format daily message: problem metadata, evidence-based selection reason, learning target, 3-step hint ladder, and feedback call-to-action.
- [ ] Implement `app/scheduler_job.py` and `scripts/run_daily.py` (idempotent for date, Asia/Kolkata timezone handling, UTC storage, retry on notification failure, LeetCode sync failure does not abort daily recommendation).
- [ ] Create `scripts/register_task.ps1` for Windows Task Scheduler registration with run-at-next-login support.
- **DoD**: Daily job runs, logs to database, and produces exactly one daily recommendation and dispatch.

---

### [ ] Phase 7: Reports, 30-Day Metrics & Backup
- [ ] Implement `scripts/weekly_report.py` (strengths, weak areas, revision priorities).
- [ ] Implement `scripts/metrics_30day.py` calculating completion rate, 0% repeat rate, difficulty fit, pattern coverage, and system reliability. No invented numbers; explicitly flag insufficient data.
- [ ] Implement `scripts/backup_db.py` for automated SQLite database snapshotting outside Git.
- [ ] Unit tests verifying accurate metric calculations.
- **DoD**: Reports and metrics execute without error on real and synthetic history; backup script creates restorable SQLite file.

---

### [ ] Phase 8: Local Web Dashboard & API
- [ ] Implement `app/api.py` (Flask localhost-only HTTP API with schema-validated endpoints for recommendations, hints, topic stats, history, sync, and feedback submission).
- [ ] Build React + Vite dashboard in `./dashboard`:
  - Today's recommendation with reason and score breakdown
  - Interactive hint reveal ladder (progressive disclosure)
  - Topic mastery visualizer
  - History & activity timeline
  - Weak & overdue topic alerts
  - Sync status & staleness indicator
  - Complete feedback submission form
- [ ] Ensure fully responsive, accessible design with zero external network calls.
- **DoD**: Dashboard displays live database state; feedback submitted in dashboard updates backend state and subsequent recommendation.

---

### [ ] Phase 9: Local Container Packaging
- [ ] Create `Dockerfile` for local containerization.
- [ ] Create `docker-compose.yml` mounting local SQLite volume, passing local `.env`, exposing API and dashboard on localhost.
- [ ] Verify local build and run without registry push or cloud dependencies.
- **DoD**: Docker build completes and runs locally in isolated container environment.

---

### [ ] Phase 10: Evaluation, Acceptance Suite & Documentation
- [ ] Run complete test suite (`pytest tests/ -v`).
- [ ] Verify all hard acceptance criteria:
  1. Exactly one question per day; duplicate run returns same pick.
  2. No solved repeats.
  3. Every recommendation contains saved score breakdown and reason.
  4. Ollama offline fallback produces complete message.
  5. Offline resilience (snapshot cache, stale warning).
  6. Feedback adaptation demonstrably alters difficulty / topic ranking.
- [ ] Create documentation:
  - `docs/architecture.md` (diagrams, data flows, deterministic boundaries)
  - `docs/privacy_notes.md` (zero cloud, no LeetCode credentials, local storage)
  - `docs/limitations.md` (edge cases, model sizing, rate limits)
- [ ] Complete `README.md` with setup guide, demo walkthrough script, and measured benchmark results.
- **DoD**: All tests pass, sweep clean, documentation complete.

---

## Ponytail Debt Ledger

| Item ID | Location | Shortcut Taken | Reason & When to Revisit |
|---|---|---|---|
| DBT-001 | Ollama Mentor | Fallback to deterministic template when Ollama daemon is absent | Avoids hard dependency on local Ollama process while enabling instant testability. Revisit if local GPU hardware is configured. |
| DBT-002 | LeetCode Client | Public GraphQL queries using public submissions endpoint | Zero credentials required, compliant with read-only rules. Revisit if LeetCode GraphQL schema changes. |

---

## Phase Execution Log

| Date | Phase | Status | Branch / Commit | Notes |
|---|---|---|---|---|
| 2026-10-30 | Step A (Plan) | COMPLETE | main | Initialized PROGRESS.md and BLOCKERS.md |
