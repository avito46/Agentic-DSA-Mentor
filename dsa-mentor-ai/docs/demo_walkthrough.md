# DSA Mentor AI — End-to-End Demo Walkthrough

This demo walks through the complete end-to-end user lifecycle: historical import -> learner mastery calibration -> daily problem recommendation -> progressive hint revelation -> feedback capture -> adaptive recalibration.

---

### Step 1: Initialize Database & Starter Catalogue
```bash
# Activate your virtual environment
.venv\Scripts\activate   # Windows
# source .venv/bin/activate # Linux/Mac

# Initialize SQLite database and populate starter problems catalogue
python -c "from app.db import init_db; from app.catalogue import load_catalogue; init_db(); load_catalogue()"
```

### Step 2: Import LeetCode Solved History
Prepare a sample CSV of solved history or use an export:
```bash
# Create demo sample submissions
cat << 'EOF' > demo_history.csv
problem_id,title,slug,submission_date,language,runtime_ms
1,Two Sum,two-sum,2026-10-25 10:00:00,python3,45
20,Valid Parentheses,valid-parentheses,2026-10-26 12:00:00,python3,32
21,Merge Two Sorted Lists,merge-two-sorted-lists,2026-10-27 15:30:00,python3,38
EOF

# Import into DSA Mentor AI
python scripts/import_history.py demo_history.csv
```
*Output Summary shows records archived to `data/raw/` and stable deduplication.*

### Step 3: Run Daily Recommendation Pipeline
```bash
python scripts/run_daily.py --no-sync --no-telegram
```
*What happens:*
1. Recommender checks learner profile (detects solve history in Hash Tables and Linked Lists; identifies gaps in Trees, Dynamic Programming, Two Pointers).
2. Evaluates candidate pool, calculates composite score with repeat penalties.
3. Selects exactly ONE unsolved problem.
4. Generates progressive hint ladder (nudge, pattern clue, approach outline).
5. Dispatches to terminal output.

### Step 4: Inspect Weekly Status & 30-Day Metrics
```bash
python scripts/weekly_report.py
python scripts/metrics_30day.py
```
*Observe that completion rates, 0% repeat rates, and topic priorities are calculated from actual data.*

### Step 5: Record Session Feedback
```bash
# Submit feedback for today's pick
python scripts/feedback_cli.py --outcome solved --minutes 20 --hints 0 --rating right --confidence 4
```
*What happens:*
- Activity event logged in append-only table.
- Recommendation status transitioned from `pending` to `solved`.
- Learner model recalculates topic mastery and elevates difficulty ceiling.

### Step 6: Launch Web Dashboard
```bash
# Start the localhost API server
python -m app.api
```
Open `http://localhost:5000` (or run `npm run dev` in `./dashboard` for interactive hot-reloading on `http://localhost:5173`).
Review today's target, click to reveal hints, view topic mastery radar, and submit feedback directly through the UI.
