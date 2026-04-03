"""IMAP IDLE email monitor — watches an inbox for new emails in real time."""
import asyncio
import base64
import email as email_lib
import hashlib
import logging
from email.header import decode_header
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Tuple

import aioimaplib
from sqlalchemy.orm import Session

from config.settings import settings
from src.models import ProcessedEmail

logger = logging.getLogger(__name__)

# Folders for processed/failed emails
PROCESSED_FOLDER = "Processed"
FAILED_FOLDER = "Failed"


class EmailMessage:
    """Parsed email with extracted metadata and attachments."""

    def __init__(
        self,
        uid: str,
        message_id: str,
        subject: str,
        sender: str,
        body_text: str,
        pdf_attachments: List[Dict],
        raw_date: Optional[str] = None,
    ):
        self.uid = uid
        self.message_id = message_id
        self.subject = subject
        self.sender = sender
        self.body_text = body_text
        self.pdf_attachments = pdf_attachments  # [{"filename": str, "bytes": bytes}]
        self.raw_date = raw_date

    @property
    def fingerprint(self) -> str:
        """SHA-256 hash of Message-ID, truncated to 32 chars."""
        return hashlib.sha256(self.message_id.encode()).hexdigest()[:32]

    @property
    def subject_business_name(self) -> Optional[str]:
        """Try to extract a business name from the subject line.

        Returns the subject stripped of common prefixes/noise, or None if empty.
        """
        if not self.subject:
            return None
        name = self.subject.strip()
        # Strip common prefixes like "Fwd:", "Re:", "FW:"
        for prefix in ["Fwd:", "FW:", "Re:", "RE:", "Fw:"]:
            if name.upper().startswith(prefix.upper()):
                name = name[len(prefix):].strip()
        return name if name else None


class IMAPMonitor:
    """Monitors an IMAP inbox using IDLE for real-time new email detection."""

    def __init__(self, on_new_email: Callable):
        """
        Args:
            on_new_email: Async callback called with an EmailMessage for each new email.
                          Should return True on success, False on failure.
        """
        self.host = settings.imap_host
        self.port = settings.imap_port
        self.email = settings.imap_email
        self.password = settings.imap_password
        self.on_new_email = on_new_email
        self._client: Optional[aioimaplib.IMAP4_SSL] = None
        self._running = False

    async def start(self):
        """Connect to IMAP and start monitoring the inbox."""
        self._running = True
        logger.info(f"IMAP monitor starting for {self.email} at {self.host}:{self.port}")

        while self._running:
            try:
                await self._connect()
                await self._ensure_folders()
                await self._process_existing_unseen()
                await self._idle_loop()
            except asyncio.CancelledError:
                logger.info("IMAP monitor cancelled")
                break
            except Exception as e:
                logger.error(f"IMAP monitor error: {e}", exc_info=True)
                if self._running:
                    logger.info("Reconnecting in 30 seconds...")
                    await asyncio.sleep(30)

        await self._disconnect()
        logger.info("IMAP monitor stopped")

    async def stop(self):
        """Stop the IMAP monitor."""
        self._running = False
        if self._client:
            try:
                await self._client.logout()
            except Exception:
                pass

    async def _connect(self):
        """Establish IMAP connection and authenticate."""
        self._client = aioimaplib.IMAP4_SSL(
            host=self.host,
            port=self.port,
        )
        await self._client.wait_hello_from_server()
        await self._client.login(self.email, self.password)
        await self._client.select("INBOX")
        logger.info(f"IMAP connected and watching INBOX for {self.email}")

    async def _disconnect(self):
        """Close the IMAP connection."""
        if self._client:
            try:
                await self._client.logout()
            except Exception:
                pass
            self._client = None

    async def _ensure_folders(self):
        """Create Processed and Failed folders if they don't exist."""
        for folder in [PROCESSED_FOLDER, FAILED_FOLDER]:
            try:
                result = await self._client.select(folder)
                if result.result == "OK":
                    # Folder exists, switch back to INBOX
                    await self._client.select("INBOX")
                    continue
            except Exception:
                pass

            try:
                await self._client.create(folder)
                logger.info(f"Created IMAP folder: {folder}")
            except Exception as e:
                # Folder might already exist, that's OK
                logger.debug(f"Could not create folder {folder}: {e}")

            # Make sure we're back in INBOX
            await self._client.select("INBOX")

    async def _process_existing_unseen(self):
        """Process any existing unseen emails in the inbox on startup."""
        result, data = await self._client.search("UNSEEN")
        if result != "OK":
            return

        uids = data[0].decode().split() if data[0] else []
        if uids:
            logger.info(f"Found {len(uids)} unseen email(s) on startup")
            for uid in uids:
                await self._fetch_and_process(uid)

    async def _idle_loop(self):
        """Enter IMAP IDLE mode and wait for new emails."""
        while self._running:
            try:
                # Start IDLE — server will notify us of new messages
                idle_task = await self._client.idle_start(timeout=300)
                # Wait for the IDLE response (new mail or timeout)
                await self._client.wait_server_push()
                # Stop IDLE to process
                self._client.idle_done()
                await asyncio.wait_for(idle_task, timeout=10)

                # Check for new unseen messages
                result, data = await self._client.search("UNSEEN")
                if result == "OK" and data[0]:
                    uids = data[0].decode().split()
                    for uid in uids:
                        await self._fetch_and_process(uid)

            except asyncio.TimeoutError:
                # IDLE timeout — just restart the IDLE loop
                continue
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"IDLE loop error: {e}", exc_info=True)
                raise  # Will trigger reconnect in start()

    async def _fetch_and_process(self, uid: str):
        """Fetch a single email by UID, parse it, and run the callback."""
        try:
            result, data = await self._client.fetch(uid, "(RFC822)")
            if result != "OK":
                logger.warning(f"Failed to fetch UID {uid}: {result}")
                return

            # Parse the raw email bytes
            raw_bytes = data[1]
            if isinstance(raw_bytes, tuple):
                raw_bytes = raw_bytes[1]
            if isinstance(raw_bytes, str):
                raw_bytes = raw_bytes.encode()

            parsed = self._parse_email(uid, raw_bytes)
            if not parsed:
                logger.warning(f"Could not parse email UID {uid}")
                await self._move_to_folder(uid, FAILED_FOLDER)
                return

            logger.info(
                f"New email: subject='{parsed.subject}', "
                f"from={parsed.sender}, "
                f"pdfs={len(parsed.pdf_attachments)}, "
                f"fingerprint={parsed.fingerprint}"
            )

            # Call the processing callback
            success = await self.on_new_email(parsed)

            # Move to appropriate folder
            if success:
                await self._move_to_folder(uid, PROCESSED_FOLDER)
            else:
                await self._move_to_folder(uid, FAILED_FOLDER)

        except Exception as e:
            logger.error(f"Error processing email UID {uid}: {e}", exc_info=True)
            try:
                await self._move_to_folder(uid, FAILED_FOLDER)
            except Exception:
                pass

    async def _move_to_folder(self, uid: str, folder: str):
        """Move an email to a folder by copying + deleting from INBOX."""
        try:
            await self._client.copy(uid, folder)
            await self._client.store(uid, "+FLAGS", "\\Deleted")
            await self._client.expunge()
            logger.info(f"Moved email UID {uid} to {folder}")
        except Exception as e:
            logger.warning(f"Could not move email UID {uid} to {folder}: {e}")

    def _parse_email(self, uid: str, raw_bytes: bytes) -> Optional[EmailMessage]:
        """Parse raw email bytes into an EmailMessage object."""
        try:
            msg = email_lib.message_from_bytes(raw_bytes)

            # Message-ID
            message_id = msg.get("Message-ID", "").strip("<>")
            if not message_id:
                message_id = f"no-id-{uid}-{datetime.utcnow().isoformat()}"

            # Subject
            subject = self._decode_header(msg.get("Subject", ""))

            # Sender
            sender = self._decode_header(msg.get("From", ""))

            # Date
            raw_date = msg.get("Date", "")

            # Body text
            body_text = self._extract_body(msg)

            # PDF attachments
            pdf_attachments = self._extract_pdf_attachments(msg)

            return EmailMessage(
                uid=uid,
                message_id=message_id,
                subject=subject,
                sender=sender,
                body_text=body_text,
                pdf_attachments=pdf_attachments,
                raw_date=raw_date,
            )

        except Exception as e:
            logger.error(f"Failed to parse email UID {uid}: {e}", exc_info=True)
            return None

    @staticmethod
    def _decode_header(value: str) -> str:
        """Decode an email header value (handles encoded-word syntax)."""
        if not value:
            return ""
        parts = decode_header(value)
        decoded = []
        for part, charset in parts:
            if isinstance(part, bytes):
                decoded.append(part.decode(charset or "utf-8", errors="replace"))
            else:
                decoded.append(part)
        return " ".join(decoded)

    @staticmethod
    def _extract_body(msg: email_lib.message.Message) -> str:
        """Extract plain text body from an email message."""
        body_parts = []

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                disposition = str(part.get("Content-Disposition", ""))

                # Skip attachments
                if "attachment" in disposition:
                    continue

                if content_type == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        body_parts.append(payload.decode(charset, errors="replace"))
        else:
            if msg.get_content_type() == "text/plain":
                payload = msg.get_payload(decode=True)
                if payload:
                    charset = msg.get_content_charset() or "utf-8"
                    body_parts.append(payload.decode(charset, errors="replace"))

        return "\n".join(body_parts).strip()

    @staticmethod
    def _extract_pdf_attachments(msg: email_lib.message.Message) -> List[Dict]:
        """Extract all PDF attachments from an email message."""
        attachments = []

        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition", ""))
            filename = part.get_filename()

            is_pdf = (
                content_type == "application/pdf"
                or (filename and filename.lower().endswith(".pdf"))
            )

            if is_pdf and ("attachment" in disposition or filename):
                payload = part.get_payload(decode=True)
                if payload:
                    attachments.append({
                        "filename": filename or "attachment.pdf",
                        "bytes": payload,
                    })
                    logger.debug(f"Found PDF attachment: {filename} ({len(payload)} bytes)")

        return attachments


# -------------------------------------------------------------------------
# Deduplication helpers (used by main.py)
# -------------------------------------------------------------------------

def is_duplicate(fingerprint: str, db: Session) -> bool:
    """Check if this email has already been processed."""
    processed = db.query(ProcessedEmail).filter(
        ProcessedEmail.fingerprint == fingerprint
    ).first()
    if processed:
        logger.info(f"Duplicate email detected: {fingerprint}")
        return True
    return False


def cleanup_old_fingerprints(db: Session):
    """Remove fingerprint records older than the configured TTL."""
    ttl = timedelta(hours=settings.image_fingerprint_ttl_hours)
    cutoff_time = datetime.utcnow() - ttl
    deleted_count = (
        db.query(ProcessedEmail)
        .filter(ProcessedEmail.processed_at < cutoff_time)
        .delete()
    )
    db.commit()
    if deleted_count > 0:
        logger.info(f"Cleaned up {deleted_count} old email fingerprints")


def pdf_to_base64(pdf_bytes: bytes) -> str:
    """Encode PDF bytes to base64 string."""
    return base64.b64encode(pdf_bytes).decode("utf-8")
