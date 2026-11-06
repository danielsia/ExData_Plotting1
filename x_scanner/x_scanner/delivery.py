"""Deliver the briefing. Each channel is enabled only if its env vars are set."""

from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

log = logging.getLogger(__name__)


def send_telegram(text: str) -> bool:
    token, chat_id = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (token and chat_id):
        return False
    # Telegram messages are capped at 4096 chars.
    for i in range(0, len(text), 4000):
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text[i : i + 4000], "disable_web_page_preview": True},
            timeout=30,
        )
        r.raise_for_status()
    return True


def send_slack(text: str) -> bool:
    url = os.getenv("SLACK_WEBHOOK_URL")
    if not url:
        return False
    requests.post(url, json={"text": text}, timeout=30).raise_for_status()
    return True


def send_email(subject: str, markdown_text: str, html_text: str) -> bool:
    host = os.getenv("SMTP_HOST")
    to = os.getenv("EMAIL_TO")
    if not (host and to):
        return False
    user = os.getenv("SMTP_USER", "")
    sender = os.getenv("EMAIL_FROM", user)
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, sender, to
    msg.attach(MIMEText(markdown_text, "plain", "utf-8"))
    msg.attach(MIMEText(html_text, "html", "utf-8"))
    with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587")), timeout=30) as s:
        s.starttls()
        if user:
            s.login(user, os.getenv("SMTP_PASSWORD", ""))
        s.sendmail(sender, [a.strip() for a in to.split(",")], msg.as_string())
    return True


def deliver_all(subject: str, digest: str, markdown_text: str, html_text: str) -> list[str]:
    sent = []
    for name, fn in (
        ("telegram", lambda: send_telegram(digest + "\n\nFull report: see email / run artifacts.")),
        ("slack", lambda: send_slack(digest)),
        ("email", lambda: send_email(subject, markdown_text, html_text)),
    ):
        try:
            if fn():
                sent.append(name)
        except Exception:  # one failing channel shouldn't block the others
            log.exception("Delivery via %s failed", name)
    return sent
