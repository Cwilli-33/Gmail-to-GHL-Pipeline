# Operator Guide — How to Deliver & Maintain the Pipeline

Internal guide for onboarding clients and maintaining deployments.

---

## Architecture Overview

```
Client's email inbox (e.g. uwteam@onixcap.net)
    |  IMAP IDLE (persistent connection)
    v
Railway deployment (background task)
    |
    ├─ Detect new email instantly
    ├─ Parse MIME: subject, body, PDF attachments
    ├─ Send PDFs to Claude for extraction
    ├─ Match/create GHL contact
    ├─ Upload PDFs to Source Documents
    ├─ Add email body as GHL contact note
    ├─ Move email to Processed/Failed folder
    └─ Send failure notification if needed
```

**Who owns what:**
- **You:** Source code on GitHub
- **Client:** Email inbox, Railway deployment, Claude API key, GHL account

---

## Onboarding a New Client

### Step 1: Client Creates GHL Custom Fields
Send them the [GHL Custom Fields Guide](GHL_CUSTOM_FIELDS.md).

### Step 2: Pull Their Field IDs (You Do This)
```bash
python scripts/get_field_ids.py
```
Enter their GHL API key + Location ID. Update `src/data_merger.py` with the output.

### Step 3: Push the Update
```bash
git add src/data_merger.py
git commit -m "Configure GHL field IDs for [client name]"
git push origin main
```

### Step 4: Client Provides IMAP Credentials
They need: IMAP host, email, password. Same settings they'd use for Outlook/Apple Mail.

### Step 5: Client Deploys to Railway
They follow the [Client Setup Guide](CLIENT_SETUP_GUIDE.md). Set env vars in Railway.

### Step 6: Test
Have them send a test email with a PDF. Verify contact in GHL.

---

## Key Differences from Telegram Pipeline

| Aspect | Telegram Pipeline | Email Pipeline |
|--------|------------------|----------------|
| **Input** | Telegram photos (images) | IMAP emails (PDFs) |
| **Detection** | Webhook push from Telegram | IMAP IDLE (persistent connection) |
| **Claude API** | Image content block | Document content block |
| **Dedup key** | file_id + file_size | Email Message-ID |
| **Source tag** | `telegram-lead` | `email-lead` |
| **Contact source** | "Telegram MCA Pipeline" | "Email MCA Pipeline" |
| **Source Docs** | Credit scrubs only | All PDFs |
| **Email body** | N/A | Saved as GHL contact note |
| **Subject line** | N/A | Fallback business name |
| **Failure alerts** | Telegram message | Email notification via SMTP |
| **Filing** | N/A | Moved to Processed/Failed folders |
| **SSN extraction** | Full SSN | Full SSN |
| **DOB extraction** | Both owners | Both owners |
| **EIN handling** | Prefer unmasked | Prefer unmasked |

---

## Important Files

| File | What It Does | When to Edit |
|------|-------------|-------------|
| `src/data_merger.py` | GHL custom field ID mapping | Per-client onboarding |
| `src/main.py` | Pipeline orchestrator | Feature changes |
| `src/imap_client.py` | IMAP IDLE monitor + email parser | Rarely |
| `src/claude_extractor.py` | Claude extraction prompt | When changing extraction |
| `src/notifications.py` | SMTP failure alerts | Rarely |
| `src/ghl_client.py` | GHL API client + notes | Rarely |
| `config/settings.py` | Environment variable definitions | When adding settings |
| `scripts/get_field_ids.py` | Fetch GHL field IDs | Per-client onboarding |
