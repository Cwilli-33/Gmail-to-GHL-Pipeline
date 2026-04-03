"""Main FastAPI application — Email (IMAP) → Claude → GHL pipeline."""
import asyncio
import base64
import json
import logging
import os
import secrets
import sys
import traceback
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI, Request, Depends, HTTPException, Header
from sqlalchemy.orm import Session

from config.settings import settings
from src.database import get_db, get_db_session, init_db
from src.imap_client import (
    IMAPMonitor, EmailMessage, is_duplicate, cleanup_old_fingerprints, pdf_to_base64,
)
from src.claude_extractor import ClaudeExtractor
from src.ghl_client import GHLClient
from src.lead_matcher import LeadMatcher
from src.data_merger import DataMerger
from src.notifications import send_failure_notification
from src.models import LeadExtraction, ProcessedEmail

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# Admin auth token
ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", secrets.token_urlsafe(32))

# Store last 20 processing results for debugging
_debug_log = deque(maxlen=20)

# Shared service instances
claude_extractor = ClaudeExtractor()
ghl_client = GHLClient()
lead_matcher = LeadMatcher(ghl_client)
data_merger = DataMerger()

# IMAP monitor instance (initialized in lifespan)
_imap_monitor: IMAPMonitor = None
_imap_task: asyncio.Task = None


# ---------------------------------------------------------------------------
# Document type classification
# ---------------------------------------------------------------------------

FUNDING_APP_TYPES = {
    "MCA_APPLICATION", "CREDIT_SCRUB", "FUNDING_APPLICATION",
    "TAX_DOCUMENT", "BUSINESS_DOCUMENT", "CRM_SCREENSHOT", "CREDIT_REPORT",
}


# ---------------------------------------------------------------------------
# Core pipeline — process a single email
# ---------------------------------------------------------------------------

async def process_email(email_msg: EmailMessage) -> bool:
    """Process a single email through the full pipeline.

    Called by the IMAP monitor for each new email.

    Args:
        email_msg: Parsed email with subject, body, and PDF attachments.

    Returns:
        True on success, False on failure (determines Processed vs Failed folder).
    """
    event = {"timestamp": datetime.utcnow().isoformat(), "steps": []}
    fingerprint = email_msg.fingerprint

    def log_step(step: str, detail: str = ""):
        entry = {"step": step, "detail": detail}
        event["steps"].append(entry)
        logger.info(f"[PIPELINE] {step}: {detail}")

    try:
        log_step("RECEIVED", f"subject='{email_msg.subject}', from={email_msg.sender}, pdfs={len(email_msg.pdf_attachments)}")

        # ── Dedup check ──────────────────────────────────────────────────
        with get_db_session() as db:
            if is_duplicate(fingerprint, db):
                log_step("SKIPPED", f"duplicate fingerprint={fingerprint}")
                event["result"] = "skipped_duplicate"
                _debug_log.append(event)
                return True  # Move to Processed — already handled

            # Claim fingerprint
            placeholder = ProcessedEmail(
                fingerprint=fingerprint,
                message_id=email_msg.message_id,
                sender_email=email_msg.sender,
                contact_id=None,
                action="PROCESSING",
                confidence=None,
                document_type=None,
                processed_at=datetime.utcnow(),
            )
            db.add(placeholder)

        log_step("FINGERPRINT", fingerprint)

        # ── Check for PDF attachments ────────────────────────────────────
        if not email_msg.pdf_attachments:
            log_step("SKIPPED", "no PDF attachments")
            with get_db_session() as db:
                _mark_processed(fingerprint, email_msg, None, "SKIPPED_NO_PDFS", None, None, db)
            event["result"] = "skipped_no_pdfs"
            _debug_log.append(event)
            await send_failure_notification(
                reason="No PDF attachments found in email",
                subject_line=email_msg.subject,
            )
            return False

        log_step("PDFS_FOUND", f"{len(email_msg.pdf_attachments)} PDF(s)")

        # ── Send each PDF to Claude ──────────────────────────────────────
        extraction_results = []  # (pdf_bytes, filename, extracted_data)

        for att in email_msg.pdf_attachments:
            pdf_bytes = att["bytes"]
            filename = att["filename"]
            pdf_b64 = pdf_to_base64(pdf_bytes)

            log_step("EXTRACTING", f"{filename} ({len(pdf_bytes)} bytes)")
            extracted = await claude_extractor.extract(pdf_b64)

            confidence = extracted.get("confidence", 0.0)
            doc_type = extracted.get("document_type", "OTHER")
            log_step("EXTRACTED", (
                f"{filename}: confidence={confidence}, type={doc_type}, "
                f"biz_name={extracted.get('business_info', {}).get('legal_name')}"
            ))

            extraction_results.append((pdf_bytes, filename, extracted))

        # ── Classify: funding apps vs bank statements ────────────────────
        funding_apps = []
        bank_statements = []

        for pdf_bytes, filename, extracted in extraction_results:
            doc_type = extracted.get("document_type", "OTHER")
            confidence = extracted.get("confidence", 0.0)

            if doc_type in FUNDING_APP_TYPES and confidence >= settings.min_confidence_threshold:
                funding_apps.append((pdf_bytes, filename, extracted))
            elif doc_type == "BANK_STATEMENT":
                bank_statements.append((pdf_bytes, filename, extracted))
            else:
                bank_statements.append((pdf_bytes, filename, extracted))

        log_step("CLASSIFIED", f"{len(funding_apps)} funding app(s), {len(bank_statements)} bank statement(s)")

        if not funding_apps:
            log_step("SKIPPED", "no funding application found")
            with get_db_session() as db:
                _mark_processed(fingerprint, email_msg, None, "SKIPPED_NO_APP", None, None, db)
            event["result"] = "skipped_no_funding_app"
            _debug_log.append(event)
            await send_failure_notification(
                reason="No funding application found among PDF attachments",
                subject_line=email_msg.subject,
            )
            return False

        # ── Process best funding application ─────────────────────────────
        funding_apps.sort(key=lambda x: x[2].get("confidence", 0.0), reverse=True)
        best_app_bytes, best_app_filename, best_extracted = funding_apps[0]

        confidence = best_extracted.get("confidence", 0.0)
        document_type = best_extracted.get("document_type", "OTHER")

        # ── Subject line fallback for business name ──────────────────────
        biz = best_extracted.get("business_info", {}) or {}
        if not biz.get("legal_name") and not biz.get("dba"):
            subject_name = email_msg.subject_business_name
            if subject_name:
                log_step("SUBJECT_FALLBACK", f"using subject line as business name: '{subject_name}'")
                if "business_info" not in best_extracted:
                    best_extracted["business_info"] = {}
                best_extracted["business_info"]["legal_name"] = subject_name

        # ── Match against existing GHL contacts ──────────────────────────
        with get_db_session() as db:
            matched_contact, match_method, match_confidence = await lead_matcher.find_match(
                best_extracted, email_id=email_msg.sender, db=db
            )
        log_step("MATCHED", f"method={match_method}, confidence={match_confidence}, found={bool(matched_contact)}")

        contact_id: str
        action: str

        if matched_contact:
            contact_id = matched_contact.get("id", "")
            update_payload = data_merger.merge(
                matched_contact, best_extracted, match_method, match_confidence
            )
            log_step("MERGING", f"updating contact {contact_id}")
            result = await ghl_client.update_contact(contact_id, update_payload)
            action = "UPDATE"

            if result:
                log_step("GHL_UPDATED", f"contact_id={contact_id}")
            else:
                log_step("GHL_UPDATE_FAILED", f"contact_id={contact_id}")
                biz_name = biz.get("legal_name") or biz.get("dba")
                await send_failure_notification(
                    reason="Could not update existing contact in GHL",
                    business_name=biz_name,
                    document_type=document_type,
                    subject_line=email_msg.subject,
                )
        else:
            new_payload = data_merger.build_new_contact(best_extracted)
            log_step("CREATING", f"payload keys: {list(new_payload.keys())}")
            result = await ghl_client.create_contact(new_payload)
            action = "CREATE"

            if result:
                contact_id = result.get("id", "unknown")
                log_step("GHL_CREATED", f"contact_id={contact_id}")
            else:
                contact_id = "failed"
                log_step("GHL_CREATE_FAILED", "no result returned")
                biz_name = biz.get("legal_name") or biz.get("dba")
                await send_failure_notification(
                    reason="Could not create contact in GHL — check API key and field data",
                    business_name=biz_name,
                    document_type=document_type,
                    subject_line=email_msg.subject,
                )

        # ── Add email body as GHL contact note ───────────────────────────
        if contact_id and contact_id not in ("failed", "unknown") and email_msg.body_text:
            note_body = f"📧 Email Context (received {datetime.utcnow().strftime('%b %d, %Y %I:%M %p')} UTC)\n"
            note_body += f"Subject: {email_msg.subject}\n"
            note_body += f"From: {email_msg.sender}\n\n"
            note_body += email_msg.body_text

            note_result = await ghl_client.create_note(contact_id, note_body)
            if note_result:
                log_step("NOTE_CREATED", f"email body added as note on {contact_id}")
            else:
                log_step("NOTE_FAILED", f"could not add note on {contact_id}")

        # ── Upload ALL PDFs to Source Documents ──────────────────────────
        source_docs_field_id = settings.source_documents_field_id

        if contact_id and contact_id not in ("failed", "unknown") and source_docs_field_id:
            for pdf_bytes, filename, _ in extraction_results:
                upload_result = await ghl_client.upload_file_to_custom_field(
                    contact_id=contact_id,
                    custom_field_id=source_docs_field_id,
                    file_bytes=pdf_bytes,
                    filename=filename,
                    content_type="application/pdf",
                )
                if upload_result:
                    log_step("PDF_UPLOADED", f"'{filename}' → Source Documents on {contact_id}")
                else:
                    log_step("PDF_UPLOAD_FAILED", f"could not upload '{filename}'")
        elif not source_docs_field_id:
            log_step("UPLOAD_SKIPPED", "SOURCE_DOCUMENTS_FIELD_ID not configured")

        # ── Record in database ───────────────────────────────────────────
        biz = best_extracted.get("business_info", {}) or {}
        owner = best_extracted.get("owner_info", {}) or {}

        with get_db_session() as db:
            extraction_record = LeadExtraction(
                fingerprint=fingerprint,
                contact_id=contact_id,
                action=action,
                ein=biz.get("ein"),
                business_name=biz.get("legal_name") or biz.get("dba"),
                owner_phone=owner.get("phone") or biz.get("phone"),
                owner_email=owner.get("email") or biz.get("email"),
                match_method=match_method,
                match_confidence=match_confidence,
                extraction_confidence=confidence,
                document_type=document_type,
                raw_extracted_data=json.dumps(best_extracted),
            )
            db.add(extraction_record)

            _mark_processed(fingerprint, email_msg, contact_id, action, confidence, document_type, db)

        log_step("DONE", f"action={action}, contact_id={contact_id}")
        event["result"] = f"{action}_{contact_id}"
        _debug_log.append(event)
        return True

    except Exception as e:
        error_tb = traceback.format_exc()
        logger.error(f"Pipeline error: {e}\n{error_tb}")
        log_step("ERROR", f"{type(e).__name__}: {str(e)}")
        event["result"] = f"error: {str(e)}"
        event["traceback"] = error_tb
        _debug_log.append(event)

        # Clean up stale PROCESSING placeholder
        try:
            with get_db_session() as db:
                stale = db.query(ProcessedEmail).filter(
                    ProcessedEmail.fingerprint == fingerprint,
                    ProcessedEmail.action == "PROCESSING",
                ).first()
                if stale:
                    db.delete(stale)
                    logger.info(f"Removed stale PROCESSING record for {fingerprint}")
        except Exception:
            logger.warning("Could not clean up stale record", exc_info=True)

        # Send failure notification
        biz_name = None
        try:
            biz_name = email_msg.subject_business_name
        except Exception:
            pass

        await send_failure_notification(
            reason=f"Unexpected error: {type(e).__name__}: {str(e)}",
            business_name=biz_name,
            subject_line=email_msg.subject,
        )

        return False


def _mark_processed(fingerprint, email_msg, contact_id, action, confidence, document_type, db):
    """Update or create the ProcessedEmail record."""
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
        record = ProcessedEmail(
            fingerprint=fingerprint,
            message_id=email_msg.message_id,
            sender_email=email_msg.sender,
            contact_id=contact_id,
            action=action,
            confidence=confidence,
            document_type=document_type,
            processed_at=datetime.utcnow(),
        )
        db.add(record)


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _imap_monitor, _imap_task

    logger.info("Starting Email → GHL Pipeline...")
    init_db()
    logger.info("Database initialized")
    logger.info(f"Claude key set: {bool(settings.claude_api_key)}")
    logger.info(f"GHL key set: {bool(settings.ghl_api_key)}")
    logger.info(f"GHL location: {settings.ghl_location_id}")
    logger.info(f"IMAP host: {settings.imap_host}")
    logger.info(f"IMAP email: {settings.imap_email}")
    logger.info(f"Source Documents field ID: {settings.source_documents_field_id}")
    if not os.environ.get("ADMIN_API_KEY"):
        logger.info(f"Auto-generated ADMIN_API_KEY: {ADMIN_API_KEY}")

    # Start IMAP monitor as a background task
    if settings.imap_host and settings.imap_email and settings.imap_password:
        _imap_monitor = IMAPMonitor(on_new_email=process_email)
        _imap_task = asyncio.create_task(_imap_monitor.start())
        logger.info("IMAP monitor started as background task")
    else:
        logger.warning("IMAP not configured — email monitoring disabled")

    yield

    logger.info("Shutting down...")
    if _imap_monitor:
        await _imap_monitor.stop()
    if _imap_task:
        _imap_task.cancel()
        try:
            await _imap_task
        except asyncio.CancelledError:
            pass
    await ghl_client.close()


app = FastAPI(
    title="Email → GHL Lead Pipeline",
    description="Automated MCA lead processing via IMAP email monitoring",
    version="2.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Health & admin endpoints
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    return {
        "status": "healthy",
        "service": "email-ghl-pipeline",
        "version": "2.0.0",
        "imap_connected": _imap_monitor is not None,
    }


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "database": "connected",
        "imap_monitoring": bool(_imap_monitor),
        "message": "Ready to process emails",
    }


async def _verify_admin(x_api_key: str = Header(None)):
    if not x_api_key or not secrets.compare_digest(x_api_key, ADMIN_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing X-Api-Key header")


@app.get("/admin/debug")
async def debug_log(x_api_key: str = Header(None)):
    await _verify_admin(x_api_key)
    return {"count": len(_debug_log), "events": list(_debug_log)}


@app.post("/admin/cleanup-fingerprints")
async def admin_cleanup_fingerprints(db: Session = Depends(get_db), x_api_key: str = Header(None)):
    await _verify_admin(x_api_key)
    cleanup_old_fingerprints(db)

    stale_cutoff = datetime.utcnow() - timedelta(minutes=10)
    stale_count = (
        db.query(ProcessedEmail)
        .filter(
            ProcessedEmail.action == "PROCESSING",
            ProcessedEmail.processed_at < stale_cutoff,
        )
        .delete()
    )
    if stale_count:
        db.commit()
        logger.info(f"Cleaned up {stale_count} stale PROCESSING records")

    return {"status": "ok", "message": f"Cleaned up fingerprints and {stale_count} stale records"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True)
