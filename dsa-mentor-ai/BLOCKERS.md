# BLOCKERS & RISKS LOG

This file tracks blockers, hard stops encountered, and mitigations during development.

| ID | Date | Blocker / Issue | Status | Resolution / Mitigation |
|---|---|---|---|---|
| BLK-001 | 2026-10-30 | Local Ollama CLI not pre-installed in environment | MITIGATED | System built with strict Ollama abstraction: template fallback is always available, unit tests mock Ollama, and full documentation provided for local model installation (e.g. `llama3.2:3b` or `qwen2.5:3b`). |
