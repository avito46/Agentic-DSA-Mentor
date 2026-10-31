-- DSA Mentor AI - SQLite Schema
-- Foreign keys must be ON for every connection
PRAGMA foreign_keys = ON;

-- 1. Catalogue of verified problems
CREATE TABLE IF NOT EXISTS problems (
    problem_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    url TEXT NOT NULL,
    difficulty TEXT NOT NULL, -- Easy, Medium, Hard, or unknown
    topics_json TEXT NOT NULL, -- JSON array of topics e.g. ["Array", "Hash Table"]
    premium_status INTEGER NOT NULL DEFAULT 0, -- 0 = free, 1 = paid/premium
    source TEXT NOT NULL, -- curated_starter, leetcode_api, custom
    verified_at TEXT NOT NULL -- ISO 8601 UTC
);

-- 2. Append-only activity events
CREATE TABLE IF NOT EXISTS activity_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    problem_id INTEGER NOT NULL,
    event_type TEXT NOT NULL CHECK(event_type IN ('solved', 'attempted', 'failed', 'skipped', 'imported')),
    occurred_at TEXT NOT NULL, -- ISO 8601 UTC
    source TEXT NOT NULL CHECK(source IN ('leetcode_sync', 'manual_feedback', 'import')),
    runtime_ms INTEGER,
    language TEXT,
    time_spent INTEGER, -- minutes spent
    hints_used INTEGER DEFAULT 0, -- 0, 1, 2, or editorial
    self_rating TEXT CHECK(self_rating IS NULL OR self_rating IN ('easy', 'right', 'hard')),
    blocker TEXT, -- concept, implementation, edge cases, complexity, time
    FOREIGN KEY (problem_id) REFERENCES problems(problem_id) ON DELETE RESTRICT
);

-- 3. Topic mastery & exposure statistics (materialized view updated deterministically)
CREATE TABLE IF NOT EXISTS topic_stats (
    topic TEXT PRIMARY KEY,
    mastery_score REAL NOT NULL DEFAULT 0.0, -- 0.0 to 100.0
    exposure_count INTEGER NOT NULL DEFAULT 0,
    success_rate REAL NOT NULL DEFAULT 0.0, -- 0.0 to 1.0
    last_practised_at TEXT, -- ISO 8601 UTC
    evidence_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL -- ISO 8601 UTC
);

-- 4. Daily recommendations (Strictly ONE per date)
CREATE TABLE IF NOT EXISTS daily_recommendations (
    date TEXT PRIMARY KEY, -- YYYY-MM-DD in user timezone (Asia/Kolkata), UNIQUE
    problem_id INTEGER NOT NULL,
    score REAL NOT NULL,
    score_breakdown_json TEXT NOT NULL, -- JSON with term weights and values
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending', -- pending, solved, skipped, failed
    generated_at TEXT NOT NULL, -- ISO 8601 UTC
    FOREIGN KEY (problem_id) REFERENCES problems(problem_id) ON DELETE RESTRICT
);

-- 5. Local LLM / Ollama execution telemetry
CREATE TABLE IF NOT EXISTS model_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    task TEXT NOT NULL, -- daily_message, hint_ladder, approach_review, weekly_summary
    latency_ms INTEGER NOT NULL,
    success INTEGER NOT NULL, -- 1 for success, 0 for fallback
    created_at TEXT NOT NULL -- ISO 8601 UTC
);

-- 6. External sync runs and audit logs
CREATE TABLE IF NOT EXISTS sync_runs (
    sync_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL, -- leetcode_graphql, csv_import, json_import
    started_at TEXT NOT NULL, -- ISO 8601 UTC
    completed_at TEXT NOT NULL, -- ISO 8601 UTC
    records_seen INTEGER NOT NULL DEFAULT 0,
    records_added INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL, -- success, partial_response, failed, stale_fallback
    error_summary TEXT
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_activity_problem ON activity_events(problem_id);
CREATE INDEX IF NOT EXISTS idx_activity_event_type ON activity_events(event_type);
CREATE INDEX IF NOT EXISTS idx_activity_occurred_at ON activity_events(occurred_at);
CREATE INDEX IF NOT EXISTS idx_daily_problem ON daily_recommendations(problem_id);
