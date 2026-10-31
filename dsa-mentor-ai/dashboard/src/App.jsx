import React, { useState, useEffect } from 'react';

export default function App() {
  const [todayData, setTodayData] = useState(null);
  const [topicsData, setTopicsData] = useState(null);
  const [historyData, setHistoryData] = useState(null);
  const [syncStatus, setSyncStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Progressive Hint Ladder visibility
  const [revealedHints, setRevealedHints] = useState({
    hint_1: false,
    hint_2: false,
    approach_outline: false,
  });

  // Feedback form state
  const [feedbackForm, setFeedbackForm] = useState({
    outcome: 'solved',
    minutes: 25,
    hints_used: 0,
    perceived_difficulty: 'right',
    confidence: 4,
    blocker: '',
  });
  const [feedbackSubmitting, setFeedbackSubmitting] = useState(false);
  const [feedbackSuccess, setFeedbackSuccess] = useState(null);

  const fetchDashboardData = async () => {
    try {
      setLoading(true);
      setError(null);

      // Concurrent fetch of all dashboard endpoints
      const [todayRes, topicsRes, historyRes, syncRes] = await Promise.all([
        fetch('/api/today'),
        fetch('/api/topics'),
        fetch('/api/history'),
        fetch('/api/sync/status'),
      ]);

      if (!todayRes.ok) throw new Error(`Today endpoint failed (${todayRes.status})`);
      const todayJson = await todayRes.json();
      setTodayData(todayJson);

      if (topicsRes.ok) {
        const topicsJson = await topicsRes.json();
        setTopicsData(topicsJson);
      }

      if (historyRes.ok) {
        const historyJson = await historyRes.json();
        setHistoryData(historyJson);
      }

      if (syncRes.ok) {
        const syncJson = await syncRes.json();
        setSyncStatus(syncJson);
      }
    } catch (err) {
      console.error('Failed to load dashboard data:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDashboardData();
  }, []);

  const handleToggleHint = (key) => {
    setRevealedHints((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const handleFeedbackSubmit = async (e) => {
    e.preventDefault();
    if (!todayData?.recommendation?.problem_id) return;

    setFeedbackSubmitting(true);
    setFeedbackSuccess(null);

    try {
      const payload = {
        problem_id: todayData.recommendation.problem_id,
        outcome: feedbackForm.outcome,
        minutes: parseInt(feedbackForm.minutes, 10),
        hints_used: parseInt(feedbackForm.hints_used, 10),
        perceived_difficulty: feedbackForm.perceived_difficulty,
        confidence: parseInt(feedbackForm.confidence, 10),
        blocker: feedbackForm.blocker || null,
      };

      const res = await fetch('/api/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const errJson = await res.json();
        throw new Error(errJson.error || 'Failed to submit feedback');
      }

      const result = await res.json();
      setFeedbackSuccess(result.adaptation_summary);

      // Re-fetch dashboard data so learner model updates reflect immediately
      await fetchDashboardData();
    } catch (err) {
      alert(`Submission error: ${err.message}`);
    } finally {
      setFeedbackSubmitting(false);
    }
  };

  if (loading && !todayData) {
    return (
      <div className="container" style={{ textAlign: 'center', paddingTop: '80px' }}>
        <h2>Loading DSA Mentor AI...</h2>
        <p style={{ color: 'var(--text-secondary)' }}>Querying local learner model & deterministic recommender...</p>
      </div>
    );
  }

  const rec = todayData?.recommendation || {};
  const coaching = todayData?.coaching || {};
  const breakdown = rec.score_breakdown || {};
  const isNoCandidates = rec.status === 'no_candidates';

  return (
    <div className="container">
      {/* Header */}
      <header>
        <div className="header-brand">
          <h1>DSA Mentor AI</h1>
          <p>Autonomous Daily LeetCode Mastery & Adaptive Feedback</p>
        </div>
        <div className="header-status">
          {syncStatus?.is_stale ? (
            <span className="badge badge-amber">⚠️ Snapshot Stale</span>
          ) : (
            <span className="badge badge-green">✓ Local Core Active</span>
          )}
          <span className="badge badge-blue">Date: {rec.date || 'Today'}</span>
        </div>
      </header>

      {error && (
        <div className="card" style={{ borderLeft: '4px solid var(--accent-rose)' }}>
          <h3>System Notice</h3>
          <p style={{ color: 'var(--text-secondary)' }}>{error}</p>
        </div>
      )}

      {/* Main Grid Layout */}
      <div className="grid-layout">
        {/* Left Column: Today's Pick, Hint Ladder & Feedback */}
        <div>
          {/* Today's Recommendation Card */}
          <div className="card">
            <div className="card-title">
              <span>Today's Daily Target</span>
              {rec.status && (
                <span className={`badge ${rec.status === 'solved' ? 'badge-green' : 'badge-amber'}`}>
                  {rec.status.toUpperCase()}
                </span>
              )}
            </div>

            {isNoCandidates ? (
              <div className="reason-box">
                <p><strong>Notice:</strong> {rec.reason}</p>
              </div>
            ) : (
              <>
                <div className="problem-header">
                  <a
                    href={rec.url}
                    target="_blank"
                    rel="noreferrer"
                    className="problem-title"
                  >
                    #{rec.problem_id}: {rec.title} ↗
                  </a>
                  <span
                    className={`badge ${
                      rec.difficulty === 'Easy'
                        ? 'badge-green'
                        : rec.difficulty === 'Hard'
                        ? 'badge-rose'
                        : 'badge-amber'
                    }`}
                  >
                    {rec.difficulty}
                  </span>
                </div>

                <div className="topics-list">
                  {(rec.topics || []).map((t, i) => (
                    <span key={i} className="topic-tag">
                      {t}
                    </span>
                  ))}
                </div>

                <div className="reason-box">
                  <strong>Why Selected:</strong> {coaching.why_selected || rec.reason}
                  {coaching.learning_target && (
                    <div style={{ marginTop: '8px' }}>
                      <strong>Target:</strong> {coaching.learning_target}
                    </div>
                  )}
                </div>

                {/* Score Breakdown Accordion / Grid */}
                <div className="score-breakdown">
                  <div className="score-item">
                    <span>Topic Weakness</span>
                    <span>{((breakdown.topic_weakness || 0) * 100).toFixed(0)}%</span>
                  </div>
                  <div className="score-item">
                    <span>Revision Due</span>
                    <span>{((breakdown.revision_due || 0) * 100).toFixed(0)}%</span>
                  </div>
                  <div className="score-item">
                    <span>Difficulty Fit</span>
                    <span>{((breakdown.difficulty_fit || 0) * 100).toFixed(0)}%</span>
                  </div>
                  <div className="score-item">
                    <span>Pattern Value</span>
                    <span>{((breakdown.pattern_learning_value || 0) * 100).toFixed(0)}%</span>
                  </div>
                  <div className="score-item">
                    <span>Composite Score</span>
                    <span style={{ color: 'var(--accent-blue)' }}>
                      {(rec.score || 0).toFixed(3)}
                    </span>
                  </div>
                </div>

                {/* Progressive Hint Reveal Ladder */}
                <div className="ladder-section">
                  <h4 style={{ marginBottom: '12px' }}>Progressive Hint Ladder</h4>

                  <div className="ladder-step">
                    <button
                      className="ladder-btn"
                      onClick={() => handleToggleHint('hint_1')}
                      type="button"
                    >
                      <span>💡 Step 1: Subtle Nudge</span>
                      <span>{revealedHints.hint_1 ? '▲ Hide' : '▼ Reveal'}</span>
                    </button>
                    {revealedHints.hint_1 && (
                      <div className="ladder-content">
                        {coaching.hint_1 || 'Focus on maintaining state invariants.'}
                      </div>
                    )}
                  </div>

                  <div className="ladder-step">
                    <button
                      className="ladder-btn"
                      onClick={() => handleToggleHint('hint_2')}
                      type="button"
                    >
                      <span>🔍 Step 2: Pattern Clue</span>
                      <span>{revealedHints.hint_2 ? '▲ Hide' : '▼ Reveal'}</span>
                    </button>
                    {revealedHints.hint_2 && (
                      <div className="ladder-content">
                        {coaching.hint_2 || 'Relate the subproblems to standard data structure mechanics.'}
                      </div>
                    )}
                  </div>

                  <div className="ladder-step">
                    <button
                      className="ladder-btn"
                      onClick={() => handleToggleHint('approach_outline')}
                      type="button"
                    >
                      <span>🪜 Step 3: Algorithmic Outline</span>
                      <span>{revealedHints.approach_outline ? '▲ Hide' : '▼ Reveal'}</span>
                    </button>
                    {revealedHints.approach_outline && (
                      <div className="ladder-content">
                        {coaching.approach_outline || '1. Parse input limits.\n2. Apply optimal structure.\n3. Return result.'}
                      </div>
                    )}
                  </div>
                </div>
              </>
            )}
          </div>

          {/* Feedback Form Card */}
          <div className="card">
            <h3 className="card-title">Log Practice Session Feedback</h3>

            {feedbackSuccess && (
              <div className="alert-success">
                <strong>✓ Feedback saved!</strong> {feedbackSuccess}
              </div>
            )}

            <form onSubmit={handleFeedbackSubmit}>
              <div className="form-group">
                <label>Outcome</label>
                <div className="button-group">
                  {['solved', 'attempted', 'stuck', 'skipped'].map((o) => (
                    <button
                      key={o}
                      type="button"
                      className={`btn-option ${feedbackForm.outcome === o ? 'active' : ''}`}
                      onClick={() => setFeedbackForm({ ...feedbackForm, outcome: o })}
                    >
                      {o.toUpperCase()}
                    </button>
                  ))}
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                <div className="form-group">
                  <label>Minutes Spent</label>
                  <input
                    type="number"
                    min="1"
                    max="300"
                    value={feedbackForm.minutes}
                    onChange={(e) =>
                      setFeedbackForm({ ...feedbackForm, minutes: e.target.value })
                    }
                  />
                </div>

                <div className="form-group">
                  <label>Hints Used</label>
                  <select
                    value={feedbackForm.hints_used}
                    onChange={(e) =>
                      setFeedbackForm({ ...feedbackForm, hints_used: e.target.value })
                    }
                  >
                    <option value="0">0 (Independent)</option>
                    <option value="1">1 (Tiny Nudge)</option>
                    <option value="2">2 (Pattern Hint)</option>
                    <option value="3">3 (Editorial Outline)</option>
                  </select>
                </div>
              </div>

              <div className="form-group">
                <label>Perceived Difficulty</label>
                <div className="button-group">
                  {[
                    { label: 'Too Easy', val: 'easy' },
                    { label: 'Just Right', val: 'right' },
                    { label: 'Too Hard', val: 'hard' },
                  ].map((r) => (
                    <button
                      key={r.val}
                      type="button"
                      className={`btn-option ${
                        feedbackForm.perceived_difficulty === r.val ? 'active' : ''
                      }`}
                      onClick={() =>
                        setFeedbackForm({ ...feedbackForm, perceived_difficulty: r.val })
                      }
                    >
                      {r.label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="form-group">
                <label>Confidence Level (1=Lost to 5=Mastered)</label>
                <div className="button-group">
                  {[1, 2, 3, 4, 5].map((lvl) => (
                    <button
                      key={lvl}
                      type="button"
                      className={`btn-option ${feedbackForm.confidence === lvl ? 'active' : ''}`}
                      onClick={() => setFeedbackForm({ ...feedbackForm, confidence: lvl })}
                    >
                      {lvl}★
                    </button>
                  ))}
                </div>
              </div>

              {['attempted', 'stuck'].includes(feedbackForm.outcome) && (
                <div className="form-group">
                  <label>Primary Blocker Encountered</label>
                  <select
                    value={feedbackForm.blocker}
                    onChange={(e) =>
                      setFeedbackForm({ ...feedbackForm, blocker: e.target.value })
                    }
                  >
                    <option value="">Select Blocker...</option>
                    <option value="concept">Concept / Missing Algorithm Theory</option>
                    <option value="implementation">Implementation / Syntax / Pointer Bug</option>
                    <option value="edge cases">Edge Cases / Off-by-one bounds</option>
                    <option value="complexity">Time / Space Complexity Optimization</option>
                    <option value="time">Time Shortage</option>
                  </select>
                </div>
              )}

              <button
                type="submit"
                className="btn-submit"
                disabled={feedbackSubmitting || isNoCandidates}
              >
                {feedbackSubmitting ? 'Recording & Adapting...' : 'Submit Session Feedback'}
              </button>
            </form>
          </div>
        </div>

        {/* Right Column: Topic Mastery Radar & Activity History */}
        <div>
          {/* Topic Mastery Progress Bars */}
          <div className="card">
            <h3 className="card-title">Topic Mastery & Coverage</h3>

            <div style={{ maxHeight: '380px', overflowY: 'auto', paddingRight: '4px' }}>
              {(topicsData?.topics || []).slice(0, 10).map((t) => {
                const mastery = t.mastery_score || 0;
                const fillColor =
                  mastery >= 70
                    ? 'var(--accent-green)'
                    : mastery >= 40
                    ? 'var(--accent-blue)'
                    : 'var(--accent-amber)';

                return (
                  <div key={t.topic} className="topic-meter">
                    <div className="topic-meter-header">
                      <span>{t.topic}</span>
                      <span style={{ color: 'var(--text-muted)' }}>
                        {mastery.toFixed(0)}% (exp: {t.exposure_count})
                      </span>
                    </div>
                    <div className="progress-bar-bg">
                      <div
                        className="progress-bar-fill"
                        style={{ width: `${Math.max(5, mastery)}%`, backgroundColor: fillColor }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>

            {topicsData?.unpracticed_patterns?.length > 0 && (
              <div style={{ marginTop: '16px', fontSize: '0.85rem' }}>
                <span style={{ color: 'var(--accent-amber)' }}>⚠️ Overdue / Unpracticed: </span>
                <span style={{ color: 'var(--text-secondary)' }}>
                  {topicsData.unpracticed_patterns.slice(0, 4).join(', ')}...
                </span>
              </div>
            )}
          </div>

          {/* Activity History Timeline */}
          <div className="card">
            <h3 className="card-title">Recent Activity History</h3>
            <div style={{ maxHeight: '420px', overflowY: 'auto', paddingRight: '4px' }}>
              {(historyData?.activity_events || []).slice(0, 8).map((ev) => (
                <div key={ev.event_id} className="timeline-item">
                  <div className="timeline-date">
                    {ev.occurred_at ? ev.occurred_at.slice(0, 16).replace('T', ' ') : 'Recent'}
                  </div>
                  <div style={{ fontWeight: 600 }}>
                    #{ev.problem_id} {ev.title}
                  </div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                    Outcome: <span style={{ color: 'var(--text-primary)' }}>{ev.event_type}</span>{' '}
                    {ev.time_spent ? `• ${ev.time_spent}m` : ''}{' '}
                    {ev.hints_used ? `• ${ev.hints_used} hints` : ''}
                  </div>
                </div>
              ))}
              {(!historyData?.activity_events || historyData.activity_events.length === 0) && (
                <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>
                  No recent activity logged yet. Submit feedback above or import history!
                </p>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
