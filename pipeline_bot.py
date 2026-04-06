"""
JLG Pipeline Bot — Telegram inline keyboard handler
────────────────────────────────────────────────────
Runs as a persistent process (separate from the daily agent) to handle
Telegram callback queries from the inline stage buttons on job cards.

Usage:
    python pipeline_bot.py          # long-polling loop (run on a VPS or locally)
    python pipeline_bot.py --once   # process pending callbacks once, then exit (for cron)

Telegram inline buttons are added to job alert messages by notifier.py.
When tapped, the callback payload is:  stage|<job_id>|<stage_name>
e.g.:  stage|a3f1c9d2...|applied

Pipeline stages (in order):
    recommended → applied → interviewing → offer → rejected → archived
"""

import sys
import time
import logging
import argparse
import requests

from config   import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from database import update_job_stage

logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt = "%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

STAGES = ["recommended", "applied", "interviewing", "offer", "rejected", "archived"]

STAGE_LABELS = {
    "recommended": "⭐ Recommended",
    "applied":     "📨 Applied",
    "interviewing":"🤝 Interviewing",
    "offer":       "💰 Offer",
    "rejected":    "❌ Rejected",
    "archived":    "📁 Archived",
}


# ── Telegram helpers ──────────────────────────────────────────────────────────

def get_updates(offset: int = 0) -> list:
    try:
        r = requests.get(
            f"{BASE_URL}/getUpdates",
            params={"offset": offset, "timeout": 30, "allowed_updates": ["callback_query"]},
            timeout=40,
        )
        r.raise_for_status()
        return r.json().get("result", [])
    except Exception as e:
        logger.error(f"getUpdates failed: {e}")
        return []


def answer_callback(callback_id: str, text: str = "", alert: bool = False) -> None:
    try:
        requests.post(
            f"{BASE_URL}/answerCallbackQuery",
            json={"callback_query_id": callback_id, "text": text, "show_alert": alert},
            timeout=10,
        )
    except Exception as e:
        logger.error(f"answerCallbackQuery failed: {e}")


def edit_message_reply_markup(chat_id, message_id, reply_markup) -> None:
    """Replace the inline keyboard on a message (e.g. after stage change)."""
    try:
        requests.post(
            f"{BASE_URL}/editMessageReplyMarkup",
            json={
                "chat_id":      chat_id,
                "message_id":   message_id,
                "reply_markup": reply_markup,
            },
            timeout=10,
        )
    except Exception as e:
        logger.error(f"editMessageReplyMarkup failed: {e}")


def send_message(text: str) -> None:
    try:
        requests.post(
            f"{BASE_URL}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        logger.error(f"sendMessage failed: {e}")


# ── Inline keyboard builder ───────────────────────────────────────────────────

def build_stage_keyboard(job_id: str, current_stage: str) -> dict:
    """Build a 3-button-per-row inline keyboard for stage selection.
    Current stage button is marked with a check mark.
    """
    buttons = []
    row = []
    for stage in STAGES:
        label = STAGE_LABELS[stage]
        if stage == current_stage:
            label = "✓ " + label
        row.append({
            "text":          label,
            "callback_data": f"stage|{job_id}|{stage}",
        })
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return {"inline_keyboard": buttons}


# ── Callback handler ──────────────────────────────────────────────────────────

def handle_callback(update: dict) -> int:
    """Process one callback query. Returns the update_id."""
    cb      = update.get("callback_query", {})
    cb_id   = cb.get("id", "")
    data    = cb.get("data", "")
    msg     = cb.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    msg_id  = msg.get("message_id")

    if not data.startswith("stage|"):
        return update.get("update_id", 0)

    parts = data.split("|", 2)
    if len(parts) != 3:
        answer_callback(cb_id, "Invalid callback data", alert=True)
        return update.get("update_id", 0)

    _, job_id, new_stage = parts
    if new_stage not in STAGES:
        answer_callback(cb_id, f"Unknown stage: {new_stage}", alert=True)
        return update.get("update_id", 0)

    success = update_job_stage(job_id, new_stage)
    if success:
        logger.info(f"Stage updated: job {job_id[:8]}... -> {new_stage}")
        answer_callback(cb_id, f"Moved to: {STAGE_LABELS[new_stage]}")
        new_keyboard = build_stage_keyboard(job_id, new_stage)
        edit_message_reply_markup(chat_id, msg_id, new_keyboard)
    else:
        answer_callback(cb_id, "Failed to update stage — check logs", alert=True)

    return update.get("update_id", 0)


# ── Main polling loop ─────────────────────────────────────────────────────────

def run_once() -> None:
    """Process all pending callback updates once, then exit."""
    updates = get_updates(offset=0)
    if not updates:
        logger.info("No pending callbacks.")
        return
    for update in updates:
        if "callback_query" in update:
            handle_callback(update)


def run_polling() -> None:
    """Long-polling loop — runs indefinitely on a server."""
    logger.info("Pipeline bot started — long-polling for stage callbacks...")
    offset = 0
    while True:
        updates = get_updates(offset=offset)
        for update in updates:
            uid = update.get("update_id", 0)
            if "callback_query" in update:
                handle_callback(update)
            offset = uid + 1
        time.sleep(1)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="JLG Pipeline Bot — Telegram stage manager")
    parser.add_argument("--once", action="store_true", help="Process pending callbacks once and exit")
    args = parser.parse_args()

    if not TELEGRAM_BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN not set")
        sys.exit(1)

    if args.once:
        run_once()
    else:
        run_polling()
