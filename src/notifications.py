"""SMTP failure notification sender."""
import logging
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

import aiosmtplib

from config.settings import settings

logger = logging.getLogger(__name__)


async def send_failure_notification(
    reason: str,
    business_name: Optional[str] = None,
    document_type: Optional[str] = None,
    subject_line: Optional[str] = None,
):
    """Send a failure notification email when lead processing fails.

    Args:
        reason: Human-readable description of why processing failed.
        business_name: Business name if known from extraction.
        document_type: Type of document being processed.
        subject_line: Original email subject line.
    """
    if not settings.smtp_host or not settings.imap_email:
        logger.warning("SMTP not configured — skipping failure notification")
        return

    to_email = settings.effective_notification_email
    from_email = settings.imap_email

    # Build email body
    lines = [
        "⚠️ Lead Processing Failed",
        "",
    ]
    if business_name:
        lines.append(f"Business: {business_name}")
    if subject_line:
        lines.append(f"Original Subject: {subject_line}")
    if document_type:
        lines.append(f"Document Type: {document_type}")
    lines.append(f"Reason: {reason}")
    lines.append(f"Time: {datetime.utcnow().strftime('%b %d, %Y %I:%M %p')} UTC")
    lines.append("")
    lines.append("Please check the email in the 'Failed' folder and re-send or process manually.")

    body = "\n".join(lines)

    msg = MIMEMultipart()
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = f"⚠️ Lead Processing Failed{f': {business_name}' if business_name else ''}"
    msg.attach(MIMEText(body, "plain"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.imap_email,
            password=settings.imap_password,
            start_tls=True,
        )
        logger.info(f"Failure notification sent to {to_email}")
    except Exception as e:
        logger.warning(f"Could not send failure notification: {e}")
