"""Email alerts through Gmail SMTP (use a Google App Password, never your real password)."""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage

from .config import log


def send_email(subject: str, body: str) -> bool:
    user = os.getenv("SMTP_USER")
    pwd = os.getenv("SMTP_APP_PASSWORD")
    to = os.getenv("ALERT_TO") or user
    if not (user and pwd and to):
        log.warning("Email not configured; would have sent: %s\n%s", subject, body[:500])
        return False
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = user, to, subject
    msg.set_content(body)
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=30) as s:
            s.login(user, pwd)
            s.send_message(msg)
        return True
    except Exception as e:  # never let alerting crash the pipeline
        log.error("Could not send email: %s", e)
        return False


def run_url() -> str:
    if os.getenv("GITHUB_RUN_ID"):
        return (f"{os.getenv('GITHUB_SERVER_URL', 'https://github.com')}/"
                f"{os.getenv('GITHUB_REPOSITORY')}/actions/runs/{os.getenv('GITHUB_RUN_ID')}")
    return "(local run)"


def alert_error(channel: str, stage: str, detail: str) -> None:
    send_email(f"[MysteryStudio] ERROR on {channel} at {stage}",
               f"Channel: {channel}\nStage: {stage}\nRun: {run_url()}\n\n{detail[-3500:]}")
