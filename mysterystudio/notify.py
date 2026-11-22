"""Email alerts through Gmail SMTP (use a Google App Password, never your real password)."""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage

from .config import log


def send_email(subject: str, body: str, attachments=None) -> bool:
    user = os.getenv("SMTP_USER")
    pwd = os.getenv("SMTP_APP_PASSWORD")
    to = os.getenv("ALERT_TO") or user
    if not (user and pwd and to):
        log.warning("Email not configured; would have sent: %s\n%s", subject, body[:500])
        return False
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = user, to, subject
    msg.set_content(body)
    for a in attachments or []:             # e.g. the review video (Gmail allows ~25 MB per email)
        try:
            from pathlib import Path
            pa = Path(a)
            if pa.exists() and pa.stat().st_size >= 22 * 1024 * 1024:
                small = pa.with_name(pa.stem + "_preview.mp4")      # email-sized copy; the upload uses the original
                import subprocess
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(pa), "-vf", "scale=720:-2",
                                "-c:v", "libx264", "-preset", "veryfast", "-crf", "29", "-c:a", "aac",
                                "-b:a", "96k", str(small)], check=False)
                if small.exists():
                    pa = small
            if pa.exists() and pa.stat().st_size < 22 * 1024 * 1024:
                msg.add_attachment(pa.read_bytes(), maintype="video", subtype="mp4", filename=pa.name)
            else:
                log.warning("Attachment %s skipped (missing or over 22 MB)", a)
        except Exception as e:
            log.warning("Could not attach %s: %s", a, e)
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
    log.error("ALERT %s / %s: %s", channel, stage, detail[-1500:])   # visible in the GitHub Actions log too
    send_email(f"[MysteryStudio] ERROR on {channel} at {stage}",
               f"Channel: {channel}\nStage: {stage}\nRun: {run_url()}\n\n{detail[-3500:]}")
