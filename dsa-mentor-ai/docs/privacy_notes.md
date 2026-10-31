# DSA Mentor AI — Privacy & Zero-Cloud Guarantees

## 1. Zero Cloud Architecture
DSA Mentor AI was designed from day one to operate with zero cloud dependencies and zero recurring costs:
- **No Cloud AI APIs**: Uses local Ollama LLMs running on your machine CPU/GPU or high-fidelity deterministic template engines. No OpenAI, Anthropic, or Gemini cloud endpoints are invoked.
- **No Third-Party Telemetry**: Zero analytics, trackers, or external CDN dependencies. All CSS, JavaScript, and fonts are self-hosted.
- **Local Storage**: All history, recommendations, and topic mastery models reside in a local SQLite file (`database/dsa_mentor.db`).

## 2. LeetCode Security Boundaries
To ensure strict privacy and protect your LeetCode account:
1. **Never Stored or Requested**:
   - No passwords.
   - No session cookies (`LEETCODE_SESSION`).
   - No CSRF tokens (`csrftoken`).
   - No authentication headers.
2. **Read-Only Public Sync**:
   - Network synchronization queries only public profile endpoints (public accepted submissions) for the configured username.
   - The system **never** submits solutions, edits profile information, or performs write actions on LeetCode.
3. **Local Raw Snapshots**:
   - Raw responses saved for offline resilience in `data/snapshots/` are scrubbed of any headers, cookies, or metadata prior to writing to disk.

## 3. Secret Scrubbing in Logs
The logging subsystem in `app/config.py` enforces a `SensitiveDataFilter`:
- Automatically scrubs configured Telegram bot tokens, authorization keys, and potential credential patterns before emitting to stdout or disk logs.
- Sensitive files (`.env`, `*.db`, `data/raw/`, `backups/`) are strictly ignored in `.gitignore` to prevent accidental exposure in version control.
