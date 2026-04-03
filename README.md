# Email → GHL Lead Pipeline

Automated MCA (Merchant Cash Advance) lead processing pipeline. Monitors an email inbox via IMAP, extracts structured data from PDF attachments using Claude AI, and creates/updates contacts in GoHighLevel CRM.

---

## How It Works

```
Lead email arrives at monitored inbox (e.g. uwteam@onixcap.net)
    ↓  (instant detection via IMAP IDLE)
Extract PDFs + email subject + email body
    ↓
Claude AI extracts: business name, EIN, SSN, DOB, owner info, financials, credit scores
    ↓
Match against existing GHL contacts (EIN → phone → email → name)
    ↓
Create or update GHL contact with extracted data
    ↓
Upload all PDFs (apps + bank statements) to Source Documents field
    ↓
Add email body context as a GHL contact note
    ↓
Move email to "Processed" folder (or "Failed" on error)
```

## Key Features

- **IMAP IDLE** — instant email detection, no polling delay
- **PDF extraction** — Claude AI reads funding applications, credit scrubs, and MCA documents
- **Full PII extraction** — SSN, DOB, EIN (full unmasked when visible)
- **Smart matching** — prevents duplicate contacts via EIN, phone, email, fuzzy name
- **Source document storage** — all PDFs uploaded to GHL contact's file field
- **Email body → GHL Notes** — context from the email body saved as a contact note
- **Subject line fallback** — uses email subject as business name if extraction misses it
- **Failure notifications** — sends email alert when processing fails
- **Auto-filing** — processed emails moved to "Processed" folder, failures to "Failed"
- **Auto-tagging** — contacts tagged by document type, revenue tier, FICO range, match method

## Tech Stack

- **Python 3.11** + **FastAPI**
- **Anthropic Claude API** (PDF document extraction)
- **GoHighLevel v2 API** (CRM integration)
- **IMAP IDLE** via `aioimaplib` (real-time email monitoring)
- **SMTP** via `aiosmtplib` (failure notifications)
- **SQLAlchemy** + SQLite/PostgreSQL (deduplication tracking)

---

## Quick Start

```bash
# Clone the repo
git clone git@github.com:Cwilli-33/Gmail-to-GHL-Pipeline.git
cd Gmail-to-GHL-Pipeline

# Set up environment
cp .env.example .env
# Edit .env with your API keys and IMAP credentials

# Install dependencies
pip install -r requirements.txt

# Run
python -m src.main
```

## Documentation

| Document | Description |
|----------|-------------|
| [Setup Guide](docs/SETUP_GUIDE.md) | Full setup walkthrough |
| [Client Setup Guide](docs/CLIENT_SETUP_GUIDE.md) | Simplified guide for end clients |
| [Environment Variables](docs/ENV_REFERENCE.md) | All configuration options |
| [GHL Custom Fields](docs/GHL_CUSTOM_FIELDS.md) | Custom fields to create in GHL |
| [Operator Guide](docs/OPERATOR_GUIDE.md) | Internal guide for onboarding clients |
| [Troubleshooting](docs/TROUBLESHOOTING.md) | Common issues and fixes |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check + IMAP status |
| `GET` | `/admin/debug` | Last 20 processing events (requires API key) |
| `POST` | `/admin/cleanup-fingerprints` | Clean up stale records (requires API key) |

## Project Structure

```
├── config/
│   └── settings.py            # Environment variable configuration
├── src/
│   ├── main.py                # FastAPI app + pipeline orchestrator
│   ├── imap_client.py         # IMAP IDLE monitor + email parser
│   ├── claude_extractor.py    # Claude AI PDF extraction
│   ├── ghl_client.py          # GoHighLevel API client + notes
│   ├── lead_matcher.py        # Contact matching logic
│   ├── data_merger.py         # Smart data merging + GHL field mapping
│   ├── notifications.py       # SMTP failure notifications
│   ├── models.py              # Database models
│   └── database.py            # Database connection
├── scripts/
│   └── get_field_ids.py       # Fetch GHL custom field IDs
├── docs/                      # Documentation
├── tests/                     # Test suite
├── Dockerfile                 # Production container
├── docker-compose.yml         # Local development
└── railway.toml               # Railway deployment config
```
