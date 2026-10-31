"""Notification dispatcher supporting Terminal and Telegram Bot API with bounded retries."""

import time
from typing import Dict, Any, Optional
import requests

from app.config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    logger,
)


def format_daily_message(
    recommendation: Dict[str, Any],
    coaching: Dict[str, Any],
) -> str:
    """Format daily recommendation and coaching guidance into readable Markdown."""
    title = recommendation.get("title", "DSA Problem")
    prob_id = recommendation.get("problem_id", "")
    difficulty = recommendation.get("difficulty", "Standard")
    url = recommendation.get("url", "https://leetcode.com")
    topics = recommendation.get("topics", [])
    topics_str = ", ".join(topics) if topics else "Algorithms"

    date_str = recommendation.get("date", "")
    why_selected = coaching.get("why_selected") or recommendation.get("reason", "")
    learning_target = coaching.get("learning_target", "")
    hint_1 = coaching.get("hint_1", "")
    hint_2 = coaching.get("hint_2", "")
    approach = coaching.get("approach_outline", "")
    call_to_action = coaching.get("call_to_action", "Log your solve time and hints in the dashboard when done!")

    lines = [
        f"🎯 *DSA MENTOR AI — DAILY PICK ({date_str})*",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📌 *Problem #{prob_id}: {title}*",
        f"📊 *Difficulty:* `{difficulty}` | *Topics:* _{topics_str}_",
        f"🔗 *URL:* {url}",
        "",
        "💡 *WHY THIS PROBLEM:*",
        f"{why_selected}",
        "",
        "🎯 *LEARNING TARGET:*",
        f"{learning_target}",
        "",
        "🪜 *PROGRESSIVE HINT LADDER:*",
        f"• *Hint 1 (Nudge):* {hint_1}",
        f"• *Hint 2 (Pattern):* {hint_2}",
        f"• *Approach Outline:*",
        f"{approach}",
        "",
        "📝 *NEXT STEPS:*",
        f"{call_to_action}",
        "Run `python scripts/feedback_cli.py` or visit the local dashboard to record your session.",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    return "\n".join(lines)


def send_telegram_message(
    message: str,
    token: Optional[str] = None,
    chat_id: Optional[str] = None,
    max_retries: int = 3,
) -> bool:
    """
    Send message via Telegram Bot API with bounded retries.
    Never logs bot token or sensitive credentials.
    """
    bot_token = (token or TELEGRAM_BOT_TOKEN).strip()
    target_chat = (chat_id or TELEGRAM_CHAT_ID).strip()

    if not bot_token or not target_chat:
        logger.info("Telegram credentials not configured. Skipping Telegram dispatch.")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": target_chat,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False,
    }

    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(url, json=payload, timeout=10.0)
            if resp.status_code == 200:
                logger.info("Telegram notification delivered successfully.")
                return True
            else:
                logger.warning(
                    f"Telegram API responded with HTTP {resp.status_code} (attempt {attempt}/{max_retries})"
                )
        except requests.RequestException as e:
            logger.warning(
                f"Telegram network delivery attempt {attempt}/{max_retries} failed: {type(e).__name__}"
            )
        if attempt < max_retries:
            time.sleep(2.0 ** attempt)

    logger.error("All Telegram delivery attempts failed.")
    return False


def notify_daily_problem(
    recommendation: Dict[str, Any],
    coaching: Dict[str, Any],
    dispatch_telegram: bool = True,
) -> Dict[str, Any]:
    """
    Deliver daily recommendation to terminal and optionally to Telegram.
    Returns status summary.
    """
    message_text = format_daily_message(recommendation, coaching)

    # 1. Terminal Output (Always delivered)
    print("\n" + message_text + "\n")

    # 2. Telegram Dispatch
    telegram_delivered = False
    if dispatch_telegram:
        telegram_delivered = send_telegram_message(message_text)

    return {
        "terminal_delivered": True,
        "telegram_delivered": telegram_delivered,
        "formatted_message": message_text,
    }
