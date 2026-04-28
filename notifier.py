import smtplib
import requests
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, SCORE_PRIORITY_THRESHOLD,
    GMAIL_APP_PASSWORD, GMAIL_FROM, GMAIL_TO,
)

logger = logging.getLogger(__name__)

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def send_message(text: str, reply_markup: dict | None = None) -> bool:
    """Send a plain text message via Telegram Bot API.
    Optionally attach an inline keyboard via reply_markup.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram credentials not configured — skipping notification")
        return False
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        resp = requests.post(
            f"{BASE_URL}/sendMessage",
            json=payload,
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Telegram send error: {e}")
        return False


def _stage_keyboard(job_id: str) -> dict:
    """Inline keyboard for pipeline stage management."""
    stages = [
        ("📨 Apply",        f"stage|{job_id}|applied"),
        ("🤝 Interviewing", f"stage|{job_id}|interviewing"),
        ("💰 Offer",        f"stage|{job_id}|offered"),
        ("❌ Reject",       f"stage|{job_id}|rejected"),
        ("📁 Archive",      f"stage|{job_id}|archived"),
    ]
    # Two buttons per row
    rows = []
    row  = []
    for label, cb_data in stages:
        row.append({"text": label, "callback_data": cb_data})
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return {"inline_keyboard": rows}


def notify_new_job(job: dict) -> bool:
    """Send a rich notification for a single new job match, with pipeline stage buttons."""
    score    = job.get("score", 0)
    title    = job.get("title", "")
    company  = job.get("company", "")
    geo      = job.get("geography", "")
    sector   = job.get("sector", "")
    cv       = "PE CV" if job.get("cvVersion") == "PE Operating Partner" else "Corp CV"
    rationale = job.get("scoringRationale", "")
    url      = job.get("url", "")
    job_id   = job.get("id", "")

    priority = score >= SCORE_PRIORITY_THRESHOLD
    flag     = "🔴 PRIORITY" if priority else "🟡 RECOMMENDED"
    bar      = _score_bar(score)

    outreach = job.get("outreachDraft", "").strip()

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

    if outreach:
        preview_lines = [ln.strip() for ln in outreach.split("\n") if ln.strip()]
        preview = " ".join(preview_lines[:2])[:280]
        if len(preview) < len(" ".join(preview_lines[:2])):
            preview += "…"
        text += f"\n\n✉️ <b>Outreach draft ready:</b>\n<i>{preview}</i>"

    keyboard = _stage_keyboard(job_id) if job_id else None
    return send_message(text, reply_markup=keyboard)


def notify_daily_summary(new_jobs: list, total_pipeline: int,
                         source_errors: list | None = None) -> bool:
    """Send the daily digest summary, including any source health warnings."""
    if not new_jobs:
        text = (
            "📋 <b>JLG Job Hunt — Daily Update</b>\n\n"
            "No new executive matches found today.\n"
            f"Pipeline total: {total_pipeline} roles tracked."
        )
        if source_errors:
            text += "\n\n⚠️ <b>Source issues detected:</b>\n"
            for err in source_errors:
                text += f"  • {err}\n"
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

    if source_errors:
        text += "\n\n⚠️ <b>Source issues detected:</b>\n"
        for err in source_errors:
            text += f"  • {err}\n"

    return send_message(text)


def _score_bar(score: int) -> str:
    """Visual score bar using unicode blocks."""
    filled = round(score / 10)
    return "█" * filled + "░" * (10 - filled)


# ── Email notifications ───────────────────────────────────────────────────────

def send_email(subject: str, html_body: str) -> bool:
    if not GMAIL_APP_PASSWORD:
        logger.warning("Gmail credentials not configured — skipping email")
        return False
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_FROM
    msg["To"]      = GMAIL_TO
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(GMAIL_FROM, GMAIL_APP_PASSWORD)
            smtp.sendmail(GMAIL_FROM, GMAIL_TO, msg.as_string())
        logger.info("Email summary sent successfully")
        return True
    except Exception as e:
        logger.error(f"Email send error: {e}")
        return False


def notify_daily_summary_email(new_jobs: list, total_pipeline: int,
                                source_errors: list | None = None) -> bool:
    subject = "JLG Job Hunt — Daily Update"

    if not new_jobs:
        html = (
            "<h2>&#128203; JLG Job Hunt &#8212; Daily Update</h2>"
            "<p>No new executive matches found today.</p>"
            f"<p>Pipeline total: <strong>{total_pipeline}</strong> roles tracked.</p>"
        )
        if source_errors:
            html += "<h3>&#9888;&#65039; Source issues detected:</h3><ul>"
            for err in source_errors:
                html += f"<li>{err}</li>"
            html += "</ul>"
        return send_email(subject, html)

    priority  = [j for j in new_jobs if j.get("score", 0) >= SCORE_PRIORITY_THRESHOLD]
    recommend = [j for j in new_jobs if 70 <= j.get("score", 0) < SCORE_PRIORITY_THRESHOLD]

    html = (
        "<h2>&#128203; JLG Job Hunt &#8212; Daily Update</h2>"
        f"<p><strong>{len(new_jobs)} new matches found today</strong></p>"
        f"<p>&#128308; Priority (&ge;{SCORE_PRIORITY_THRESHOLD}): {len(priority)} &nbsp;"
        f"&#128993; Recommended (70&#8211;{SCORE_PRIORITY_THRESHOLD - 1}): {len(recommend)}</p>"
        f"<p>&#128202; Pipeline total: {total_pipeline} roles</p>"
    )

    def _job_rows(jobs: list) -> str:
        rows = ""
        for j in jobs[:10]:
            url       = j.get("url", "")
            title     = j.get("title", "")
            company   = j.get("company", "")
            score     = j.get("score", 0)
            rationale = j.get("scoringRationale", "")
            geo       = j.get("geography", "")
            cv        = "PE CV" if j.get("cvVersion") == "PE Operating Partner" else "Corp CV"
            link      = f'<a href="{url}">{title}</a>' if url else title
            rows += (
                f"<tr>"
                f"<td style='padding:8px;border-bottom:1px solid #eee'>{link}</td>"
                f"<td style='padding:8px;border-bottom:1px solid #eee'>{company}</td>"
                f"<td style='padding:8px;border-bottom:1px solid #eee'>{geo}</td>"
                f"<td style='padding:8px;border-bottom:1px solid #eee;text-align:center'>"
                f"<strong>{score}</strong></td>"
                f"<td style='padding:8px;border-bottom:1px solid #eee;font-size:12px;"
                f"color:#555'>{cv} &mdash; {rationale}</td>"
                f"</tr>"
            )
        return rows

    table_style = (
        "border-collapse:collapse;width:100%;font-family:Arial,sans-serif;font-size:14px"
    )
    header = (
        "<tr style='background:#f0f0f0'>"
        "<th style='padding:8px;text-align:left'>Role</th>"
        "<th style='padding:8px;text-align:left'>Company</th>"
        "<th style='padding:8px;text-align:left'>Location</th>"
        "<th style='padding:8px;text-align:center'>Score</th>"
        "<th style='padding:8px;text-align:left'>Notes</th>"
        "</tr>"
    )

    if priority:
        html += (
            "<h3>&#128308; Priority matches</h3>"
            f"<table style='{table_style}'>{header}{_job_rows(priority)}</table>"
        )
    if recommend:
        html += (
            "<h3>&#128993; Other recommendations</h3>"
            f"<table style='{table_style}'>{header}{_job_rows(recommend)}</table>"
        )

    if source_errors:
        html += "<h3>&#9888;&#65039; Source issues detected:</h3><ul>"
        for err in source_errors:
            html += f"<li>{err}</li>"
        html += "</ul>"

    return send_email(subject, html)
