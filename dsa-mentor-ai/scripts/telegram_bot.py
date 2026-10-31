"""Interactive Telegram bot runner allowing full control of DSA Mentor AI from chat."""

import sys
from pathlib import Path

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import time
import argparse
from typing import Dict, Any, Optional
import requests

from app.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, logger
from app.recommender import select_daily_problem, get_current_date_in_tz
from app.mentor import get_daily_mentor_message, get_hint_ladder
from app.feedback import record_feedback, VALID_OUTCOMES
from app.learner_model import refresh_topic_stats
from app.notifier import format_daily_message


def send_reply(chat_id: str, text: str, token: str) -> bool:
    """Send a Markdown-formatted reply to a Telegram chat."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False,
    }
    try:
        r = requests.post(url, json=payload, timeout=10.0)
        return r.status_code == 200
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")
        return False


def handle_telegram_command(
    text: str,
    chat_id: str,
    allowed_chat_id: Optional[str] = None,
    db_path: Optional[Any] = None,
) -> str:
    """
    Parse and process a command received from Telegram.
    Enforces authorization check against configured chat_id.
    """
    if allowed_chat_id and str(chat_id) != str(allowed_chat_id):
        return "⚠️ Unauthorized. This bot is configured for a private user."

    cmd_parts = text.strip().split()
    if not cmd_parts:
        return "Type `/help` to see available commands."

    cmd = cmd_parts[0].lower()

    if cmd in ("/start", "/help"):
        return (
            "🤖 *DSA Mentor AI — Telegram Assistant*\n\n"
            "Available commands:\n"
            "• `/today` — Get today's recommended problem & reasoning\n"
            "• `/hint1` — Reveal Hint 1 (Subtle nudge)\n"
            "• `/hint2` — Reveal Hint 2 (Pattern guidance)\n"
            "• `/outline` — Reveal Step 3 Approach Outline\n"
            "• `/solved [minutes]` — Log problem solved (e.g. `/solved 25`)\n"
            "• `/stuck` — Log session stuck / failed\n"
            "• `/skip` — Skip today without penalty\n"
            "• `/stats` — View current topic mastery and weakness\n"
        )

    elif cmd == "/today":
        today = get_current_date_in_tz()
        rec = select_daily_problem(target_date=today, db_path=db_path)
        if rec.get("status") == "no_candidates":
            return f"⚠️ {rec.get('reason')}"
        coaching = get_daily_mentor_message(rec, rec.get("reason", ""), db_path=db_path)
        return format_daily_message(rec, coaching)

    elif cmd in ("/hint1", "/hint2", "/outline"):
        today = get_current_date_in_tz()
        rec = select_daily_problem(target_date=today, db_path=db_path)
        if rec.get("status") == "no_candidates":
            return "No active recommendation for today."
        ladder = get_hint_ladder(rec, db_path=db_path)

        if cmd == "/hint1":
            return f"💡 *Hint 1 (Nudge):*\n{ladder.get('hint_1')}"
        elif cmd == "/hint2":
            return f"🔍 *Hint 2 (Pattern):*\n{ladder.get('hint_2')}"
        else:
            return f"🪜 *Approach Outline:*\n{ladder.get('approach_outline')}"

    elif cmd in ("/solved", "/stuck", "/skip"):
        today = get_current_date_in_tz()
        rec = select_daily_problem(target_date=today, db_path=db_path)
        if rec.get("status") == "no_candidates":
            return "No problem recommended for today to record feedback for."

        pid = rec["problem_id"]
        outcome_map = {"/solved": "solved", "/stuck": "stuck", "/skip": "skipped"}
        outcome = outcome_map[cmd]

        minutes = 25
        if len(cmd_parts) > 1:
            try:
                minutes = int(cmd_parts[1])
            except ValueError:
                minutes = 25

        res = record_feedback(
            problem_id=pid,
            outcome=outcome,
            minutes=minutes,
            hints_used=0 if outcome == "solved" else 2,
            perceived_difficulty="right" if outcome == "solved" else "hard",
            confidence=4 if outcome == "solved" else 2,
            db_path=db_path,
        )
        return (
            f"✅ *Feedback Recorded for Problem #{pid}!*\n"
            f"Outcome: `{outcome.upper()}` ({minutes} mins)\n"
            f"Adaptation: {res.get('adaptation_summary')}\n"
            f"Updated Topic Mastery: {res.get('updated_mastery', 0):.1f}%"
        )

    elif cmd == "/stats":
        stats = refresh_topic_stats(db_path=db_path)
        lines = ["📊 *Top Topic Mastery:*"]
        sorted_topics = sorted(stats.items(), key=lambda x: -x[1]["mastery_score"])
        for topic, s in sorted_topics[:6]:
            lines.append(f"• *{topic}:* {s['mastery_score']:.1f}% (exposures: {s['exposure_count']})")
        return "\n".join(lines)

    return "Unknown command. Type `/help` for options."


def run_telegram_bot(token: Optional[str] = None, chat_id: Optional[str] = None, db_path: Optional[Any] = None):
    """Run long-polling loop for the Telegram bot."""
    bot_token = (token or TELEGRAM_BOT_TOKEN).strip()
    target_chat = (chat_id or TELEGRAM_CHAT_ID).strip()

    if not bot_token:
        print("Error: TELEGRAM_BOT_TOKEN is not set in .env")
        return

    print("🤖 DSA Mentor AI Telegram Bot started listening for commands...")
    print(f"Target Chat ID: {target_chat or 'Any authorized user'}")
    print("Press Ctrl+C to stop.")

    offset = None
    while True:
        try:
            url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
            params = {"timeout": 30}
            if offset:
                params["offset"] = offset

            resp = requests.get(url, params=params, timeout=35)
            if resp.status_code == 200:
                data = resp.json()
                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    msg = update.get("message", {})
                    text = msg.get("text", "")
                    sender_chat = str(msg.get("chat", {}).get("id", ""))

                    if text:
                        logger.info(f"Received Telegram command: {text[:20]} from {sender_chat}")
                        reply = handle_telegram_command(text, sender_chat, target_chat, db_path=db_path)
                        send_reply(sender_chat, reply, bot_token)
            time.sleep(1)
        except KeyboardInterrupt:
            print("\nTelegram bot stopped.")
            break
        except Exception as e:
            logger.warning(f"Telegram polling error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the interactive Telegram bot listener.")
    parser.add_argument("--db", default=None, help="Custom database path")
    args = parser.parse_args()

    run_telegram_bot(db_path=args.db)
