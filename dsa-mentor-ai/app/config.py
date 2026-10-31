"""Configuration and logging setup for DSA Mentor AI."""

import os
import re
import logging
from pathlib import Path
from typing import Dict, Any, List

# Root directory of dsa-mentor-ai
BASE_DIR = Path(__file__).resolve().parent.parent


def load_env_file(env_path: Path) -> None:
    """Load key-value pairs from .env into os.environ if not already set (stdlib only)."""
    if not env_path.is_file():
        return
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception as e:
        # Don't crash on unreadable .env, just proceed
        pass


# Load .env if present
load_env_file(BASE_DIR / ".env")


class SensitiveDataFilter(logging.Filter):
    """Logging filter that scrubs sensitive patterns (tokens, cookies, auth keys) from logs."""

    # Patterns matching potential credentials, tokens, or auth headers
    PATTERNS = [
        re.compile(r"(bot\d+:[A-Za-z0-9_-]{20,})", re.IGNORECASE),
        re.compile(r"(bearer\s+[A-Za-z0-9_\-\.]{15,})", re.IGNORECASE),
        re.compile(r"([A-Za-z0-9_-]{30,})", re.IGNORECASE),  # general long token candidates
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            msg = record.msg
            # Scrub configured secrets if they exist
            token = os.environ.get("TELEGRAM_BOT_TOKEN")
            if token and len(token) > 5 and token in msg:
                msg = msg.replace(token, "[REDACTED_TELEGRAM_TOKEN]")
            for p in self.PATTERNS:
                msg = p.sub("[REDACTED_SECRET]", msg)
            record.msg = msg
        return True


def setup_logger(name: str = "dsa_mentor", level: str = None) -> logging.Logger:
    """Returns a configured logger with secret scrubbing enabled."""
    log_level_name = level or os.environ.get("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)

    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(log_level)
        handler = logging.StreamHandler()
        handler.setLevel(log_level)
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        handler.addFilter(SensitiveDataFilter())
        logger.addHandler(handler)
        logger.propagate = False
    return logger


# Global logger instance
logger = setup_logger()

def _resolve_config_path(env_var: str, default_subpath: str) -> Path:
    val = os.environ.get(env_var)
    if val:
        p = Path(val)
        return p if p.is_absolute() else (BASE_DIR / p)
    return BASE_DIR / default_subpath


# Config paths
DB_PATH = _resolve_config_path("DB_PATH", "database/dsa_mentor.db")
CATALOGUE_PATH = _resolve_config_path("CATALOGUE_PATH", "data/problems.json")
SNAPSHOT_DIR = _resolve_config_path("SNAPSHOT_DIR", "data/snapshots")
SCHEMA_PATH = BASE_DIR / "database" / "schema.sql"

# LeetCode Configuration
LEETCODE_USERNAME = os.environ.get("LEETCODE_USERNAME", "").strip()
LEETCODE_GRAPHQL_URL = "https://leetcode.com/graphql"
LEETCODE_RATE_LIMIT_DELAY = float(os.environ.get("LEETCODE_RATE_LIMIT_DELAY", "2.0"))

# Ollama Local LLM Configuration
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_TIMEOUT_SECONDS = int(os.environ.get("OLLAMA_TIMEOUT_SECONDS", "15"))

# Telegram Configuration
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# Scheduling & Timezone
TIMEZONE = os.environ.get("TIMEZONE", "Asia/Kolkata")
DAILY_RUN_HOUR = int(os.environ.get("DAILY_RUN_HOUR", "8"))
DAILY_RUN_MINUTE = int(os.environ.get("DAILY_RUN_MINUTE", "0"))

# API Configuration
API_HOST = os.environ.get("API_HOST", "127.0.0.1")
API_PORT = int(os.environ.get("API_PORT", "5000"))

# Mastery Formula Weights (Phase 2)
# Sum = 1.00; missing components redistributed proportionally
MASTERY_WEIGHTS: Dict[str, float] = {
    "success": 0.30,
    "recency": 0.20,
    "difficulty": 0.20,
    "low_hint": 0.15,
    "confidence": 0.15,
}

# Recommender Weights (Phase 3)
RECOMMENDER_WEIGHTS: Dict[str, float] = {
    "topic_weakness": 0.30,
    "revision_due": 0.20,
    "difficulty_fit": 0.20,
    "pattern_learning_value": 0.15,
    "confidence_fit": 0.10,
    "novelty": 0.05,
}

# Recommender Buckets
RECOMMENDER_BUCKETS: Dict[str, float] = {
    "weak_topic": 0.50,
    "spaced_revision": 0.30,
    "new_pattern": 0.20,
}

# Penalties
REPEAT_PENALTY = 0.50
EXCESSIVE_DIFFICULTY_PENALTY = 0.40
COOLDOWN_DAYS_SKIP = 3
COOLDOWN_DAYS_FAILED = 5

# Difficulty Preferences (e.g. Medium,Hard)
_raw_pref = os.environ.get("PREFERRED_DIFFICULTIES", "").strip()
PREFERRED_DIFFICULTIES: List[str] = (
    [d.strip().capitalize() for d in _raw_pref.split(",") if d.strip()]
    if _raw_pref
    else []
)
