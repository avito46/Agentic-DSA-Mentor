# DSA Mentor AI — System Boundaries & Limitations

## 1. Hardware & Local Model Sizing
- **Recommended Hardware**: 8 GB to 16 GB of unified RAM or system memory.
- **Supported Quantized Models**:
  - `llama3.2:3b` (~2.0 GB VRAM/RAM) — *Default & Recommended*
  - `qwen2.5:3b` (~2.2 GB VRAM/RAM) — *High quality code reasoning*
  - `deepseek-r1:1.5b` (~1.1 GB VRAM/RAM) — *Low resource footprint*
- **Offline / LLM-Down Behavior**:
  If Ollama is not installed or the daemon is stopped, the application will not crash or fail. A deterministic template engine immediately takes over, populating hints, reasons, and outlines using only verified problem metadata.

## 2. LeetCode Public API Boundaries
- **Public Submissions Rate Limits**: LeetCode's public GraphQL endpoint is rate-limited. The client applies a conservative delay (`LEETCODE_RATE_LIMIT_DELAY = 2.0s`) and bounded exponential backoff.
- **Partial Responses**: LeetCode's public endpoint may occasionally return only recent submissions (e.g. last 20-50). The client detects partial responses and will **never** mark previously imported/solved problems as unsolved.
- **Private Profiles**: If a LeetCode user's profile is set to completely private, public GraphQL queries cannot read submissions. In this scenario, users can seamlessly import their CSV/JSON submission export using `python scripts/import_history.py <file>`.

## 3. Catalogue Constraints
- The system strictly forbids hallucinating or inventing difficulty levels, tags, or problem URLs.
- If a problem is missing difficulty or topic tags, it is categorized as `"unknown"` / `[]`.
- Problem selection is constrained to verified problems in `problems.json`. Users can expand the catalogue at any time by placing additional verified problem objects into `data/problems.json` and rerunning `load_catalogue()`.
