# Email → GHL Lead Pipeline — Build Specification

## Overview

Build a FastAPI application that receives inbound emails via SendGrid Inbound Parse webhook, extracts PDF attachments, classifies them (funding application vs. bank statement), extracts structured MCA lead data from funding applications using Claude, and creates/updates contacts in GoHighLevel (GHL).

This is a **standalone project** adapted from an existing Telegram → GHL pipeline. Several modules are carried over with minimal changes. The architecture, patterns, and GHL integration are intentionally identical.

---

## Architecture Summary

```
Email sender (e.g. fund19@protonmail.com)
    │
    ▼
Dedicated intake domain (e.g. intake@leads.clientdomain.com)
    │
    ▼
SendGrid Inbound Parse (receives email, parses attachments)
    │
    ▼  POST multipart/form-data
FastAPI  /webhook/email
    │
    ├─ Validate sender against whitelist
    ├─ Extract PDF attachments from payload
    ├─ Deduplicate by email Message-ID
    │
    ├─ For each PDF:
    │   ├─ Send to Claude for classification + extraction
    │   ├─ If FUNDING_APPLICATION / MCA_APPLICATION / CREDIT_SCRUB:
    │   │   └─ Extract structured data → match/create GHL contact
    │   └─ If BANK_STATEMENT:
    │       └─ Upload raw PDF to GHL contact's Source Documents field
    │
    └─ Return 200 to SendGrid
```

---

## One Email = One Lead

Every email contains PDFs for a single business/lead. Multiple PDFs in one email are different documents (application + bank statements) for the **same** lead. The pipeline should:

1. Process the funding application PDF **first** to extract lead data and create/match the GHL contact.
2. Then upload all bank statement PDFs to that contact's Source Documents field.

If no funding application is found among the attachments (only bank statements), log a warning and skip — we need the application to create the contact.

---

## Email Body

The email body is **ignored**. All lead data comes from the PDF attachments. Do not parse or extract any information from the email body text.

---

## Modules — What to Carry Over vs. Build New

### Carry over from Telegram pipeline (copy and adapt)

These files should be copied from the reference codebase. Changes noted below each.

#### `config/settings.py`
- **Remove:** `telegram_bot_token` field
- **Add:** `sendgrid_webhook_verification_key` (optional, for signed webhook verification)
- **Add:** `allowed_senders` — comma-separated email addresses (e.g. `"fund19@protonmail.com,broker2@gmail.com"`)
- **Add:** `source_documents_field_id` — GHL custom field ID for the Source Documents FILE_UPLOAD field (was hardcoded as `CCfYyWrJaoNU1Ma0K0ID` in Telegram pipeline; now configurable via env var `SOURCE_DOCUMENTS_FIELD_ID`)
- **Keep everything else** (claude settings, GHL settings, processing settings, database, etc.)

#### `src/ghl_client.py`
- **No changes.** Copy as-is. The entire GHL API client (search, create, update, file upload with append logic) is reused unchanged.

#### `src/lead_matcher.py`
- **Minor change:** The batch dedup logic currently uses `chat_id` (Telegram concept). Replace with `email_message_id` as the batch grouping key. Same logic otherwise — match by EIN → phone → email → business name.
- Rename parameter `chat_id` to `email_id` in `find_match()` and `_find_match_in_recent_batch()`.

#### `src/data_merger.py`
- **Change 1:** In `build_new_contact()`, change `contact["source"]` from `"Telegram MCA Pipeline"` to `"Email MCA Pipeline"`.
- **Change 2:** In `_merge_tags()`, change the base tag from `"telegram-lead"` to `"email-lead"`.
- **Change 3:** The `SOURCE_DOCS_FIELD_ID` is no longer hardcoded. The main handler will use the value from `settings.source_documents_field_id`.
- **Everything else stays identical** — same GHL custom field IDs, same merge logic, same tag generation.

#### `src/database.py`
- **No changes.** Copy as-is.

#### `src/models.py`
- **Adapt `ProcessedImage` → `ProcessedEmail`:**
  - Rename table to `processed_emails`
  - Replace `file_id` (Telegram) with `message_id` (email Message-ID header, string)
  - Replace `message_id` (int, Telegram message number) — remove, not needed
  - Replace `chat_id` with `sender_email` (string)
  - Keep: `fingerprint` (primary key), `contact_id`, `action`, `processed_at`, `confidence`, `document_type`
- **`LeadExtraction` stays the same**, no changes needed.

#### `src/claude_extractor.py`
- **Change the input type:** Instead of receiving `image_base64` + `media_type`, the `extract()` method now receives `pdf_base64` (base64-encoded PDF bytes).
- **Change the API call:** Replace the `image` content block with a `document` content block:
  ```python
  {
      "type": "document",
      "source": {
          "type": "base64",
          "media_type": "application/pdf",
          "data": pdf_base64,
      },
  }
  ```
- **Update `EXTRACTION_PROMPT`:** Same prompt, but change the opening line from "Analyze this image..." to "Analyze this PDF document...". Remove references to "image may be blurry" and similar image-specific language. Add: "This PDF is a funding application or credit scrub for an MCA lead. Extract ALL available fields."
- **Add a `classify()` method** (or combine with extract) that returns the `document_type` field. Since the extraction prompt already returns `document_type`, this can simply be the same call — process the PDF, check `document_type` in the response to determine if it's a funding app or bank statement.
- **Keep:** All retry logic, JSON parsing, empty extraction fallback.

### Build new

#### `src/email_processor.py`
This replaces `image_processor.py`. Responsible for:

1. **Parsing the SendGrid webhook payload.** SendGrid Inbound Parse sends a `multipart/form-data` POST with these key fields:
   - `from` — sender email address
   - `to` — recipient email address
   - `subject` — email subject line
   - `text` — plain text body (ignore)
   - `html` — HTML body (ignore)
   - `headers` — raw email headers (extract `Message-ID` from here)
   - `attachments` — JSON string describing attachment metadata
   - Attachment files — sent as named file fields in the multipart form

2. **Sender validation.** Extract sender email from the `from` field (may be formatted as `"Display Name <email@domain.com>"`). Parse out the raw email address and check it against `settings.allowed_senders` (comma-separated list, case-insensitive comparison).

3. **Attachment extraction.** Parse the `attachments` JSON to get metadata. For each attachment:
   - Check that `content-type` is `application/pdf` (skip non-PDFs)
   - Read the file bytes from the form data
   - Store filename and bytes in a list

4. **Deduplication.** Create a fingerprint from the email's `Message-ID` header (from the `headers` field). The Message-ID is globally unique per email, so this is a reliable dedup key. Hash it with SHA-256 and truncate to 32 chars, same pattern as the Telegram pipeline. Check against `ProcessedEmail` table.

5. **Fingerprint claiming.** Same pattern as Telegram — insert a `PROCESSING` placeholder immediately to prevent race conditions (SendGrid may retry on slow responses).

Key class structure:
```python
class EmailProcessor:
    def __init__(self):
        self.allowed_senders = [s.strip().lower() for s in settings.allowed_senders.split(",") if s.strip()]
        self.fingerprint_ttl = timedelta(hours=settings.image_fingerprint_ttl_hours)

    def validate_sender(self, from_field: str) -> bool:
        """Extract email from 'Display Name <email>' format and check whitelist."""

    def extract_message_id(self, headers: str) -> str:
        """Parse Message-ID from raw email headers string."""

    def extract_pdf_attachments(self, form_data) -> List[Dict]:
        """Return list of {'filename': str, 'content_type': str, 'bytes': bytes}"""

    def create_fingerprint(self, message_id: str) -> str:
        """SHA-256 hash of Message-ID, truncated to 32 chars."""

    def is_duplicate(self, fingerprint: str, db: Session) -> bool:
        """Check ProcessedEmail table."""

    def mark_as_processed(self, fingerprint, ..., db):
        """Update placeholder record with final status."""

    def cleanup_old_fingerprints(self, db):
        """Delete records older than TTL."""
```

#### `src/main.py` — New webhook handler

Same FastAPI app structure. Key changes:

- **Remove:** `/webhook/telegram` endpoint
- **Add:** `POST /webhook/email` endpoint
- **Keep:** `/health`, `/admin/debug`, `/admin/cleanup-fingerprints` endpoints
- **Keep:** Lifespan manager, debug log deque, admin auth

The `/webhook/email` handler flow:

```
1.  Parse multipart form data from SendGrid
2.  Validate sender → reject if not whitelisted (return 200 to prevent retries)
3.  Extract Message-ID → create fingerprint → check for duplicate
4.  Claim fingerprint (insert PROCESSING placeholder)
5.  Extract all PDF attachments
6.  If no PDFs found → log warning, return 200
7.  Send each PDF to Claude for extraction:
    - Collect results as list of (pdf_bytes, filename, extracted_data)
8.  Separate results into:
    - funding_apps: where document_type in (MCA_APPLICATION, CREDIT_SCRUB, FUNDING_APPLICATION, TAX_DOCUMENT, BUSINESS_DOCUMENT, CRM_SCREENSHOT)
    - bank_statements: where document_type == BANK_STATEMENT
    - other: anything else (treat as bank statements — upload but don't extract)
9.  Process funding application FIRST:
    - Take the highest-confidence funding app extraction
    - Run lead_matcher.find_match() against GHL
    - If match found → data_merger.merge() → ghl_client.update_contact()
    - If no match → data_merger.build_new_contact() → ghl_client.create_contact()
    - Store the contact_id
10. Upload ALL bank statement PDFs (and any "other" PDFs) to the contact's Source Documents field:
    - Use ghl_client.upload_file_to_custom_field() with settings.source_documents_field_id
    - Upload the funding application PDF(s) too (as source documents)
11. Record in database (ProcessedEmail + LeadExtraction)
12. Return 200 with processing summary
```

**Important:** Always return HTTP 200 to SendGrid, even on errors. SendGrid retries on non-2xx responses, which would cause duplicate processing. Handle errors internally and log them.

---

## SendGrid Webhook Payload Reference

SendGrid Inbound Parse POSTs `multipart/form-data` with these fields:

| Field | Type | Description |
|-------|------|-------------|
| `from` | string | Sender, e.g. `"John Doe <john@example.com>"` |
| `to` | string | Recipient |
| `subject` | string | Email subject |
| `text` | string | Plain text body (IGNORE) |
| `html` | string | HTML body (IGNORE) |
| `headers` | string | Raw email headers (parse Message-ID from here) |
| `envelope` | string | JSON with `to` and `from` arrays |
| `attachments` | string | JSON string with attachment count/info |
| `attachment1`, `attachment2`, ... | file | Actual attachment file data |

When "Send Raw" is enabled in SendGrid Inbound Parse settings, the payload instead contains a single `email` field with the full raw MIME message. **We should use the default (parsed) mode, NOT raw mode.** The parsed mode is simpler — SendGrid does the MIME parsing for us.

### Extracting attachments from parsed mode:

```python
# The 'attachments' field is a JSON string with metadata
import json
num_attachments = int(form_data.get("attachments", "0"))

# Or parse the attachment info
attachment_info = json.loads(form_data.get("attachment-info", "{}"))

# Each attachment is a file field named 'attachment1', 'attachment2', etc.
for i in range(1, num_attachments + 1):
    file = form_data.get(f"attachment{i}")
    # file is an UploadFile in FastAPI
    content = await file.read()
    filename = file.filename
    content_type = file.content_type
```

---

## Environment Variables

```bash
# --- REQUIRED ---
CLAUDE_API_KEY=your_claude_api_key
GHL_API_KEY=your_ghl_api_key
GHL_LOCATION_ID=your_ghl_location_id
ALLOWED_SENDERS=fund19@protonmail.com
SOURCE_DOCUMENTS_FIELD_ID=your_ghl_file_upload_custom_field_id

# --- OPTIONAL: Security ---
# SendGrid signs webhooks with this key (optional but recommended for production)
SENDGRID_WEBHOOK_VERIFICATION_KEY=

# Admin API key for debug/cleanup endpoints
ADMIN_API_KEY=

# --- OPTIONAL: Claude Settings ---
CLAUDE_MODEL=claude-sonnet-4-20250514
CLAUDE_MAX_TOKENS=4000
CLAUDE_TIMEOUT=60

# --- OPTIONAL: Processing ---
MIN_CONFIDENCE_THRESHOLD=0.25
IMAGE_FINGERPRINT_TTL_HOURS=24

# --- OPTIONAL: App ---
LOG_LEVEL=INFO
ENV=development
DEBUG=false
DATABASE_URL=sqlite:///./email_ghl.db
```

---

## Deployment

Same Railway setup as the Telegram pipeline:
- Single `Dockerfile` (same as existing, no changes needed)
- `railway.toml` for deployment config
- Environment variables set in Railway dashboard
- Public URL provided by Railway → used as the SendGrid Inbound Parse webhook URL

The endpoint URL configured in SendGrid will be:
```
https://your-app.railway.app/webhook/email
```

---

## File Structure

```
email-ghl-pipeline/
├── config/
│   ├── __init__.py
│   └── settings.py              # Adapted (remove telegram, add email settings)
├── src/
│   ├── __init__.py
│   ├── main.py                  # New webhook handler for /webhook/email
│   ├── email_processor.py       # NEW — replaces image_processor.py
│   ├── claude_extractor.py      # Adapted (PDF input instead of image)
│   ├── ghl_client.py            # Unchanged from Telegram pipeline
│   ├── lead_matcher.py          # Minor adapt (chat_id → email_id)
│   ├── data_merger.py           # Minor adapt (source tag, configurable field ID)
│   ├── models.py                # Adapted (ProcessedImage → ProcessedEmail)
│   └── database.py              # Unchanged
├── docs/
│   ├── SETUP_GUIDE.md           # SendGrid + DNS setup walkthrough
│   ├── ENV_REFERENCE.md         # All env vars documented
│   └── TROUBLESHOOTING.md       # Common issues
├── scripts/
│   └── get_field_ids.py         # Unchanged from Telegram pipeline
├── tests/
│   └── test_placeholder.py
├── .env.example
├── .gitignore
├── .dockerignore
├── Dockerfile
├── docker-compose.yml
├── railway.toml
├── requirements.txt
└── README.md
```

---

## Requirements Changes

Same as Telegram pipeline **except:**
- **Remove:** No Telegram-specific dependencies (there weren't any — httpx was used)
- **Keep all existing dependencies** (fastapi, uvicorn, httpx, anthropic, sqlalchemy, phonenumbers, etc.)

No new dependencies needed. SendGrid's webhook is just a standard HTTP POST — no SDK required.

---

## Key Design Decisions Documented

1. **SendGrid Inbound Parse** (not Gmail API) — webhook-based, no OAuth, no polling, provider-agnostic. Email arrives → SendGrid POSTs to our endpoint → we process.

2. **One email = one lead.** All PDFs in a single email belong to the same business.

3. **Sender whitelist via env var.** `ALLOWED_SENDERS` is a comma-separated list. Case-insensitive matching. Reject (silently, return 200) any email from an unlisted sender.

4. **Email body is ignored.** All data comes from PDF attachments.

5. **PDF classification is done by Claude.** The extraction prompt already returns `document_type`. No separate classification step — extract first, then branch on the type.

6. **Funding application processed first** to establish the GHL contact. Bank statements uploaded after.

7. **Source Documents field ID is configurable** via `SOURCE_DOCUMENTS_FIELD_ID` env var (not hardcoded).

8. **Same GHL custom field IDs** as the Telegram pipeline — identical `GHL_CUSTOM_FIELDS` mapping in `data_merger.py`.

9. **Always return 200 to SendGrid.** Handle all errors internally. Log failures but never return 4xx/5xx which would trigger SendGrid retries.

10. **Dedup by email Message-ID header.** Globally unique, reliable, no hash collisions.

---

## Testing Plan

1. **Unit tests:** Mock SendGrid payload parsing, sender validation, PDF extraction, Claude responses.
2. **Integration test:** Send a test email to the intake address with sample PDFs. Verify GHL contact creation and file uploads.
3. **Edge cases:**
   - Email with no attachments → skip gracefully
   - Email with only bank statements (no funding app) → log warning, skip
   - Email with non-PDF attachments (images, docs) → skip non-PDFs
   - Duplicate email (same Message-ID) → skip as duplicate
   - Email from non-whitelisted sender → reject silently
   - Claude extraction returns low confidence → skip per threshold
   - Multiple funding app PDFs in one email → use highest confidence extraction

---

## Reference: Existing Telegram Pipeline Source

The reference codebase to copy shared modules from is the `tg-ghl-pipeline-source.zip` previously provided. The exact file contents should be used as the starting point for all "carry over" modules listed above.
