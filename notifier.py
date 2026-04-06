import requests
import logging
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, SCORE_PRIORITY_THRESHOLD

logger = logging.getLogger(__name__)

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def send_message(text: str) -> bool:
    """Send a plain text message via Telegram Bot API."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram credentials not configured — skipping notification")
        return False
    try:
        resp = requests.post(
            f"{BASE_URL}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Telegram send error: {e}")
        return False


def notify_new_job(job: dict) -> bool:
    """Send a rich notification for a single new job match."""
    score    = job.get("score", 0)
    title    = job.get("title", "")
    company  = job.get("company", "")
    geo      = job.get("geography", "")
    sector   = job.get("sector", "")
    cv       = "PE CV" if job.get("cvVersion") == "PE Operating Partner" else "Corp CV"
    rationale = job.get("scoringRationale", "")
    url      = job.get("url", "")

    priority = score >= SCORE_PRIORITY_THRESHOLD
    flag     = "🔴 PRIORITY" if priority else "🟡 RECOMMENDED"
    bar      = _score_bar(score)

    text = (
        f"{flag} — New executive role\n\n"
        f"<b>{title}</b>\n"
        f"🏢 {company}\n"
        f"🌍 {geo}\n"
        f"📊 {sector}\n\n"
        f"Score: <b>{score}/100</b>  {bar}\n"
        f"CV: {cv}\n\n"
        f"💡 {rationale}\n"
    )
    if url:
        text += f"\n🔗 <a href='{url}'>View role</a>"

    return send_message(text)


def notify_daily_summary(new_jobs: list, total_pipeline: int) -> bool:
    """Send the daily digest summary."""
    if not new_jobs:
        text = (
            "📋 <b>JLG Job Hunt — Daily Update</b>\n\n"
            "No new executive matches found today.\n"
            f"Pipeline total: {total_pipeline} roles tracked."
        )
        return send_message(text)

    priority  = [j for j in new_jobs if j.get("score", 0) >= SCORE_PRIORITY_THRESHOLD]
    recommend = [j for j in new_jobs if 70 <= j.get("score", 0) < SCORE_PRIORITY_THRESHOLD]

    text = f"📋 <b>JLG Job Hunt — Daily Update</b>\n\n"
    text += f"<b>{len(new_jobs)} new matches found today</b>\n"
    text += f"🔴 Priority (≥85): {len(priority)}\n"
    text += f"🟡 Recommended (70–84): {len(recommend)}\n"
    text += f"📊 Pipeline total: {total_pipeline} roles\n\n"

    if priority:
        text += "<b>Priority matches:</b>\n"
        for j in priority[:5]:
            text += f"  • {j['title']} @ {j['company']} — {j['score']}/100\n"

    if recommend:
        text += "\n<b>Other recommendations:</b>\n"
        for j in recommend[:5]:
            text += f"  • {j['title']} @ {j['company']} — {j['score']}/100\n"

    text += "\nOpen dashboard to review and move pipeline stages."
    return send_message(text)


def _score_bar(score: int) -> str:
    """Visual score bar using unicode blocks."""
    filled = round(score / 10)
    return "█" * filled + "░" * (10 - filled)
