# Email → GHL Lead Pipeline

Automated MCA (Merchant Cash Advance) lead processing pipeline. Receives inbound emails via SendGrid, extracts structured data from PDF attachments using Claude AI, and creates/updates contacts in GoHighLevel CRM.

---

## How It Works

```
Broker sends email with PDF attachment
    ↓
SendGrid Inbound Parse receives the email
    ↓
POST webhook/email → FastAPI application
    ↓
Validate sender → Extract PDFs → Send to Claude AI
    ↓
Claude extracts: business name, EIN, owner info, financials, credit scores
    ↓
Match against existing GHL contacts (EIN → phone → email → name)
    ↓
Create or update GHL contact with extracted data
    ↓
Upload all PDFs to Source Documents field
```

## Key Features

- **PDF extraction** — Claude AI reads funding applications, credit scrubs, and MCA documents
- **Smart matching** — Prevents duplicate contacts using EIN, phone, email, and fuzzy name matching
- **Batch dedup** — Multiple PDFs in one email are recognized as the same lead
- **Source document storage** — All PDFs uploaded to GHL contact's file field
- **Auto-tagging** — Contacts tagged by document type, revenue tier, FICO range, and match method
- **Sender whitelist** — Only approved email addresses are processed
- **Always-on** — Deployed on Railway, processes emails 24/7

## Tech Stack

- **Python 3.11** + **FastAPI**
- **Anthropic Claude API** (PDF document extraction)
- **GoHighLevel v2 API** (CRM integration)
- **SendGrid Inbound Parse** (email receiving)
- **SQLAlchemy** + SQLite/PostgreSQL (deduplication tracking)

---

## Quick Start

```bash
# Clone the repo
git clone git@github.com:Cwilli-33/Gmail-to-GHL-Pipeline.git
cd Gmail-to-GHL-Pipeline

# Set up environment
cp .env.example .env
# Edit .env with your API keys

# Install dependencies
pip install -r requirements.txt

# Run locally
python -m src.main
```

## Documentation

| Document | Description |
|----------|-------------|
| [Setup Guide](docs/SETUP_GUIDE.md) | Full setup walkthrough (30-45 min) |
| [Client Setup Guide](docs/CLIENT_SETUP_GUIDE.md) | Simplified guide for end clients (SendGrid + DNS only) |
| [Environment Variables](docs/ENV_REFERENCE.md) | All configuration options |
| [GHL Custom Fields](docs/GHL_CUSTOM_FIELDS.md) | 20 custom fields to create in GHL |
| [Operator Guide](docs/OPERATOR_GUIDE.md) | Internal guide for onboarding clients |
| [Troubleshooting](docs/TROUBLESHOOTING.md) | Common issues and fixes |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/webhook/email` | SendGrid Inbound Parse webhook |
| `GET` | `/health` | Health check |
| `GET` | `/admin/debug` | Last 20 webhook events (requires API key) |
| `POST` | `/admin/cleanup-fingerprints` | Clean up stale records (requires API key) |

## Project Structure

```
├── config/
│   └── settings.py          # Environment variable configuration
├── src/
│   ├── main.py              # FastAPI app + webhook handler
│   ├── email_processor.py   # SendGrid payload parsing + sender validation
│   ├── claude_extractor.py  # Claude AI PDF extraction
│   ├── ghl_client.py        # GoHighLevel API client
│   ├── lead_matcher.py      # Contact matching logic
│   ├── data_merger.py       # Smart data merging + GHL field mapping
│   ├── models.py            # Database models
│   └── database.py          # Database connection
├── scripts/
│   └── get_field_ids.py     # Fetch GHL custom field IDs
├── docs/                    # Documentation
├── tests/                   # Test suite
├── Dockerfile               # Production container
├── docker-compose.yml       # Local development
└── railway.toml             # Railway deployment config
```
