"""Main FastAPI application — Email → Claude → GHL pipeline."""
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
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from config.settings import settings
from src.database import get_db, init_db
from src.email_processor import EmailProcessor
from src.claude_extractor import ClaudeExtractor
from src.ghl_client import GHLClient
from src.lead_matcher import LeadMatcher
from src.data_merger import DataMerger
from src.models import LeadExtraction, ProcessedEmail

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# Admin auth token — set ADMIN_API_KEY env var, or a random one is generated each boot
ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", secrets.token_urlsafe(32))

# Store last 20 webhook results for debugging via /admin/debug
_debug_log = deque(maxlen=20)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Email → GHL Pipeline...")
    init_db()
    logger.info("Database initialized")
    logger.info(f"Claude key set: {bool(settings.claude_api_key)}")
    logger.info(f"GHL key set: {bool(settings.ghl_api_key)}")
    logger.info(f"GHL location: {settings.ghl_location_id}")
    logger.info(f"Allowed senders: {settings.allowed_senders}")
    logger.info(f"Source Documents field ID: {settings.source_documents_field_id}")
    if not os.environ.get("ADMIN_API_KEY"):
        logger.info(f"Auto-generated ADMIN_API_KEY (set env var to persist): {ADMIN_API_KEY}")
    yield
    logger.info("Shutting down...")
    await ghl_client.close()


app = FastAPI(
    title="Email → GHL Lead Pipeline",
    description="Automated MCA lead processing from email PDF attachments",
    version="1.0.0",
    lifespan=lifespan,
)

# Shared service instances
email_processor = EmailProcessor()
claude_extractor = ClaudeExtractor()
ghl_client = GHLClient()
lead_matcher = LeadMatcher(ghl_client)
data_merger = DataMerger()


# ---------------------------------------------------------------------------
# Health endpoints
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    return {
        "status": "healthy",
        "service": "email-ghl-pipeline",
        "version": "1.0.0",
    }


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "database": "connected",
        "message": "Ready to process emails",
    }


# ---------------------------------------------------------------------------
# Debug endpoint — view recent webhook activity
# ---------------------------------------------------------------------------

async def _verify_admin(x_api_key: str = Header(None)):
    """Verify admin API key for protected endpoints."""
    if not x_api_key or not secrets.compare_digest(x_api_key, ADMIN_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing X-Api-Key header")


@app.get("/admin/debug")
async def debug_log(x_api_key: str = Header(None)):
    """View the last 20 webhook processing results."""
    await _verify_admin(x_api_key)
    return {"count": len(_debug_log), "events": list(_debug_log)}


# ---------------------------------------------------------------------------
# Email webhook (SendGrid Inbound Parse)
# ---------------------------------------------------------------------------

# Document types that count as "funding applications" for extraction
FUNDING_APP_TYPES = {
    "MCA_APPLICATION", "CREDIT_SCRUB", "FUNDING_APPLICATION",
    "TAX_DOCUMENT", "BUSINESS_DOCUMENT", "CRM_SCREENSHOT", "CREDIT_REPORT",
}


@app.post("/webhook/email")
async def handle_email_webhook(request: Request, db: Session = Depends(get_db)):
    """Process incoming emails from SendGrid Inbound Parse.

    Always returns HTTP 200 to prevent SendGrid retries.
    """
    event = {"timestamp": datetime.utcnow().isoformat(), "steps": []}
    fingerprint = None

    def log_step(step: str, detail: str = ""):
        entry = {"step": step, "detail": detail}
        event["steps"].append(entry)
        logger.info(f"[PIPELINE] {step}: {detail}")

    try:
        # ── Parse multipart form data from SendGrid ──────────────────────
        form_data = await request.form()
        log_step("RECEIVED", f"form keys={list(form_data.keys())[:10]}")

        # ── Validate sender ──────────────────────────────────────────────
        from_field = form_data.get("from", "")
        if not email_processor.validate_sender(from_field):
            log_step("REJECTED", f"sender not whitelisted: {from_field}")
            event["result"] = "rejected_sender"
            _debug_log.append(event)
            return {"status": "rejected", "reason": "sender_not_whitelisted"}

        sender_email = email_processor.get_sender_email(from_field)
        subject = form_data.get("subject", "(no subject)")
        log_step("SENDER_OK", f"from={sender_email}, subject={subject}")

        # ── Extract Message-ID → create fingerprint → check duplicate ────
        headers = form_data.get("headers", "")
        message_id = email_processor.extract_message_id(headers)
        if not message_id:
            # Fallback: use subject + sender + timestamp as message ID
            message_id = f"{sender_email}_{subject}_{datetime.utcnow().isoformat()}"
            log_step("MESSAGE_ID_FALLBACK", f"no Message-ID header, using fallback: {message_id[:50]}")
        else:
            log_step("MESSAGE_ID", message_id[:80])

        fingerprint = email_processor.create_fingerprint(message_id)
        if email_processor.is_duplicate(fingerprint, db):
            log_step("SKIPPED", f"duplicate fingerprint={fingerprint}")
            event["result"] = "skipped_duplicate"
            _debug_log.append(event)
            return {"status": "skipped", "reason": "duplicate_email", "fingerprint": fingerprint}

        log_step("FINGERPRINT", fingerprint)

        # ── Claim fingerprint (prevents race condition) ──────────────────
        placeholder = ProcessedEmail(
            fingerprint=fingerprint,
            message_id=message_id,
            sender_email=sender_email,
            contact_id=None,
            action="PROCESSING",
            confidence=None,
            document_type=None,
            processed_at=datetime.utcnow(),
        )
        db.add(placeholder)
        db.commit()
        log_step("FINGERPRINT_CLAIMED", "placeholder inserted")

        # ── Extract PDF attachments ──────────────────────────────────────
        pdf_attachments = email_processor.extract_pdf_attachments(form_data)

        if not pdf_attachments:
            log_step("SKIPPED", "no PDF attachments found")
            email_processor.mark_as_processed(
                fingerprint, message_id, sender_email,
                contact_id=None, action="SKIPPED_NO_PDFS",
                confidence=None, document_type=None, db=db,
            )
            db.commit()
            event["result"] = "skipped_no_pdfs"
            _debug_log.append(event)
            return {"status": "skipped", "reason": "no_pdf_attachments"}

        log_step("PDFS_FOUND", f"{len(pdf_attachments)} PDF(s)")

        # ── Read PDF bytes and send each to Claude ───────────────────────
        extraction_results = []  # List of (pdf_bytes, filename, extracted_data)

        for att in pdf_attachments:
            pdf_bytes = await att["file"].read()
            filename = att["filename"]
            pdf_base64 = email_processor.pdf_to_base64(pdf_bytes)

            log_step("EXTRACTING", f"sending {filename} ({len(pdf_bytes)} bytes) to Claude")
            extracted = await claude_extractor.extract(pdf_base64)

            confidence = extracted.get("confidence", 0.0)
            doc_type = extracted.get("document_type", "OTHER")
            log_step("EXTRACTED", (
                f"{filename}: confidence={confidence}, type={doc_type}, "
                f"biz_name={extracted.get('business_info', {}).get('legal_name')}"
            ))

            extraction_results.append((pdf_bytes, filename, extracted))

        # ── Separate into funding apps vs bank statements ────────────────
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
                # Treat unknown/low-confidence as bank statements (upload raw)
                bank_statements.append((pdf_bytes, filename, extracted))

        log_step("CLASSIFIED", f"{len(funding_apps)} funding app(s), {len(bank_statements)} bank statement(s)")

        if not funding_apps:
            log_step("SKIPPED", "no funding application found among attachments")
            email_processor.mark_as_processed(
                fingerprint, message_id, sender_email,
                contact_id=None, action="SKIPPED_NO_APP",
                confidence=None, document_type=None, db=db,
            )
            db.commit()
            event["result"] = "skipped_no_funding_app"
            _debug_log.append(event)
            return {"status": "skipped", "reason": "no_funding_application"}

        # ── Process funding application (highest confidence) ─────────────
        funding_apps.sort(key=lambda x: x[2].get("confidence", 0.0), reverse=True)
        best_app_bytes, best_app_filename, best_extracted = funding_apps[0]

        confidence = best_extracted.get("confidence", 0.0)
        document_type = best_extracted.get("document_type", "OTHER")

        # ── Match against existing GHL contacts ──────────────────────────
        matched_contact, match_method, match_confidence = await lead_matcher.find_match(
            best_extracted, email_id=sender_email, db=db
        )
        log_step("MATCHED", f"method={match_method}, confidence={match_confidence}, found={bool(matched_contact)}")

        contact_id: str
        action: str

        if matched_contact:
            # ── Update existing contact ──────────────────────────────────
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
        else:
            # ── Create new contact ───────────────────────────────────────
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

        # ── Upload ALL PDFs to Source Documents field ─────────────────────
        source_docs_field_id = settings.source_documents_field_id

        if contact_id and contact_id not in ("failed", "unknown") and source_docs_field_id:
            all_pdfs = list(extraction_results)  # All PDFs (apps + statements)

            for pdf_bytes, filename, _ in all_pdfs:
                upload_result = await ghl_client.upload_file_to_custom_field(
                    contact_id=contact_id,
                    custom_field_id=source_docs_field_id,
                    file_bytes=pdf_bytes,
                    filename=filename,
                    content_type="application/pdf",
                )
                if upload_result:
                    log_step("PDF_UPLOADED", f"'{filename}' uploaded to Source Documents for {contact_id}")
                else:
                    log_step("PDF_UPLOAD_FAILED", f"could not upload '{filename}' for {contact_id}")
        elif not source_docs_field_id:
            log_step("UPLOAD_SKIPPED", "SOURCE_DOCUMENTS_FIELD_ID not configured")

        # ── Record in local database ─────────────────────────────────────
        biz = best_extracted.get("business_info", {}) or {}
        owner = best_extracted.get("owner_info", {}) or {}

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

        email_processor.mark_as_processed(
            fingerprint, message_id, sender_email,
            contact_id=contact_id, action=action,
            confidence=confidence, document_type=document_type, db=db,
        )

        db.commit()
        log_step("DONE", f"action={action}, contact_id={contact_id}")

        event["result"] = f"{action}_{contact_id}"
        _debug_log.append(event)

        return {
            "status": "processed",
            "action": action,
            "contact_id": contact_id,
            "confidence": confidence,
            "document_type": document_type,
            "match_method": match_method,
            "match_confidence": match_confidence,
            "pdfs_processed": len(extraction_results),
        }

    except Exception as e:
        error_tb = traceback.format_exc()
        logger.error(f"Webhook processing error: {e}\n{error_tb}")
        log_step("ERROR", f"{type(e).__name__}: {str(e)}")
        event["result"] = f"error: {str(e)}"
        event["traceback"] = error_tb
        _debug_log.append(event)

        # Clean up the PROCESSING placeholder so the email can be retried
        try:
            if fingerprint:
                stale = db.query(ProcessedEmail).filter(
                    ProcessedEmail.fingerprint == fingerprint,
                    ProcessedEmail.action == "PROCESSING",
                ).first()
                if stale:
                    db.delete(stale)
                    db.commit()
                    logger.info(f"Removed stale PROCESSING record for {fingerprint}")
        except Exception:
            logger.warning("Could not clean up stale PROCESSING record", exc_info=True)

        # Always return 200 to SendGrid so it doesn't retry endlessly
        return {"status": "error", "error": str(e)}


# ---------------------------------------------------------------------------
# Manual cleanup endpoint
# ---------------------------------------------------------------------------

@app.post("/admin/cleanup-fingerprints")
async def cleanup_fingerprints(db: Session = Depends(get_db), x_api_key: str = Header(None)):
    """Remove old email fingerprints based on configured TTL,
    plus any stale PROCESSING records older than 10 minutes."""
    await _verify_admin(x_api_key)
    email_processor.cleanup_old_fingerprints(db)

    # Also clean up stale PROCESSING records (failed mid-pipeline)
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
