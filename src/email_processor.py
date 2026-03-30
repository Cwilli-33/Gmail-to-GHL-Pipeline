"""Email processing: parsing SendGrid webhooks, fingerprinting, and duplicate detection."""
import base64
import hashlib
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from config.settings import settings
from src.models import ProcessedEmail

logger = logging.getLogger(__name__)


class EmailProcessor:
    """Handles parsing and validation of inbound emails from SendGrid Inbound Parse."""

    def __init__(self):
        self.allowed_senders = [
            s.strip().lower()
            for s in settings.allowed_senders.split(",")
            if s.strip()
        ]
        self.fingerprint_ttl = timedelta(hours=settings.image_fingerprint_ttl_hours)

    def validate_sender(self, from_field: str) -> bool:
        """Extract email from 'Display Name <email>' format and check whitelist.

        Args:
            from_field: The raw 'from' field from the email (e.g. "John Doe <john@example.com>").

        Returns:
            True if sender is allowed, False otherwise.
        """
        email = self._extract_email_address(from_field)
        if not email:
            logger.warning(f"Could not parse sender email from: {from_field}")
            return False

        allowed = email.lower() in self.allowed_senders
        if not allowed:
            logger.warning(f"Sender not whitelisted: {email}")
        else:
            logger.info(f"Sender validated: {email}")
        return allowed

    def get_sender_email(self, from_field: str) -> str:
        """Extract just the email address from the from field."""
        return self._extract_email_address(from_field) or from_field.strip().lower()

    def extract_message_id(self, headers: str) -> Optional[str]:
        """Parse Message-ID from raw email headers string.

        Args:
            headers: Raw email headers as a single string.

        Returns:
            The Message-ID value, or None if not found.
        """
        if not headers:
            return None

        # Message-ID header looks like: Message-ID: <unique-id@domain.com>
        match = re.search(r"Message-ID:\s*<?([^>\s]+)>?", headers, re.IGNORECASE)
        if match:
            return match.group(1).strip()

        return None

    def extract_pdf_attachments(self, form_data: dict) -> List[Dict]:
        """Extract PDF attachments from SendGrid parsed webhook form data.

        Args:
            form_data: Dict-like object from the multipart form data.
                       Attachment files are in keys like 'attachment1', 'attachment2', etc.

        Returns:
            List of dicts with 'filename', 'content_type', and 'bytes' keys.
        """
        attachments = []

        # SendGrid provides attachment count in the 'attachments' field
        num_attachments = 0
        try:
            num_attachments = int(form_data.get("attachments", "0"))
        except (ValueError, TypeError):
            pass

        if num_attachments == 0:
            logger.info("No attachments found in email")
            return attachments

        for i in range(1, num_attachments + 1):
            attachment = form_data.get(f"attachment{i}")
            if attachment is None:
                continue

            content_type = getattr(attachment, "content_type", "") or ""
            filename = getattr(attachment, "filename", f"attachment{i}") or f"attachment{i}"

            if content_type == "application/pdf" or filename.lower().endswith(".pdf"):
                attachments.append({
                    "filename": filename,
                    "content_type": "application/pdf",
                    "file": attachment,  # UploadFile object — read bytes in handler
                })
                logger.info(f"Found PDF attachment: {filename}")
            else:
                logger.info(f"Skipping non-PDF attachment: {filename} ({content_type})")

        logger.info(f"Extracted {len(attachments)} PDF attachment(s)")
        return attachments

    def create_fingerprint(self, message_id: str) -> str:
        """Create a fingerprint from the email Message-ID.

        Args:
            message_id: The email's Message-ID header value.

        Returns:
            SHA-256 hash truncated to 32 characters.
        """
        return hashlib.sha256(message_id.encode()).hexdigest()[:32]

    def is_duplicate(self, fingerprint: str, db: Session) -> bool:
        """Check if this email has already been processed.

        Args:
            fingerprint: The fingerprint to check.
            db: Database session.

        Returns:
            True if duplicate, False otherwise.
        """
        processed = db.query(ProcessedEmail).filter(
            ProcessedEmail.fingerprint == fingerprint
        ).first()
        if processed:
            logger.info(f"Duplicate email detected: {fingerprint}")
            return True
        return False

    def mark_as_processed(
        self,
        fingerprint: str,
        message_id: str,
        sender_email: str,
        contact_id: Optional[str],
        action: str,
        confidence: Optional[float],
        document_type: Optional[str],
        db: Session,
    ):
        """Update the placeholder record with final processing status.

        Args:
            fingerprint: The email fingerprint.
            message_id: The email Message-ID.
            sender_email: The sender's email address.
            contact_id: The GHL contact ID (if created/updated).
            action: The action taken (CREATE, UPDATE, SKIPPED, etc.).
            confidence: Extraction confidence score.
            document_type: Type of document extracted.
            db: Database session.
        """
        existing = db.query(ProcessedEmail).filter(
            ProcessedEmail.fingerprint == fingerprint
        ).first()

        if existing:
            existing.contact_id = contact_id
            existing.action = action
            existing.confidence = confidence
            existing.document_type = document_type
            existing.processed_at = datetime.utcnow()
        else:
            processed = ProcessedEmail(
                fingerprint=fingerprint,
                message_id=message_id,
                sender_email=sender_email,
                contact_id=contact_id,
                action=action,
                confidence=confidence,
                document_type=document_type,
                processed_at=datetime.utcnow(),
            )
            db.add(processed)
        logger.info(f"Marked email {fingerprint} as processed ({action})")

    def cleanup_old_fingerprints(self, db: Session):
        """Remove fingerprint records older than the configured TTL."""
        cutoff_time = datetime.utcnow() - self.fingerprint_ttl
        deleted_count = (
            db.query(ProcessedEmail)
            .filter(ProcessedEmail.processed_at < cutoff_time)
            .delete()
        )
        db.commit()
        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} old email fingerprints")

    @staticmethod
    def pdf_to_base64(pdf_bytes: bytes) -> str:
        """Encode PDF bytes to base64 string."""
        return base64.b64encode(pdf_bytes).decode("utf-8")

    @staticmethod
    def _extract_email_address(from_field: str) -> Optional[str]:
        """Extract bare email address from a 'From' field.

        Handles formats like:
            - "John Doe <john@example.com>"
            - "<john@example.com>"
            - "john@example.com"
        """
        if not from_field:
            return None

        # Try to extract from angle brackets
        match = re.search(r"<([^>]+)>", from_field)
        if match:
            return match.group(1).strip().lower()

        # Try bare email
        candidate = from_field.strip().lower()
        if "@" in candidate and "." in candidate.split("@")[-1]:
            return candidate

        return None
