# Environment Variables Reference

All configuration is done through environment variables. Set these in Railway (or in a `.env` file for local development).

---

## Required Variables

| Variable | Description | Example | Where to Get It |
|----------|-------------|---------|----------------|
| `CLAUDE_API_KEY` | Anthropic API key | `sk-ant-api03-xxxxx...` | [console.anthropic.com](https://console.anthropic.com) |
| `GHL_API_KEY` | GoHighLevel Private Integration key | `pit-xxxxxxxx-xxxx-...` | GHL Settings > Integrations |
| `GHL_LOCATION_ID` | Your GHL location identifier | `aBcDeFgHiJkLmNoPqRsT` | From GHL URL |
| `IMAP_HOST` | IMAP server hostname | `mail.onixcap.net` | Email provider settings |
| `IMAP_EMAIL` | Email address to monitor | `uwteam@onixcap.net` | Your lead intake email |
| `IMAP_PASSWORD` | Email password or app password | `yourpassword` | Email provider |
| `SOURCE_DOCUMENTS_FIELD_ID` | GHL custom field ID (FILE_UPLOAD type) | `CCfYyWrJaoNU1Ma0K0ID` | Run `get_field_ids.py` |

---

## Optional Variables

### IMAP Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `IMAP_PORT` | `993` | IMAP server port. 993 for SSL (standard). |

### SMTP Settings (Failure Notifications)

| Variable | Default | Description |
|----------|---------|-------------|
| `SMTP_HOST` | Not set | SMTP server hostname. Usually same as IMAP host. If not set, failure notifications are disabled. |
| `SMTP_PORT` | `587` | SMTP server port. 587 for STARTTLS (standard). |
| `NOTIFICATION_EMAIL` | Same as `IMAP_EMAIL` | Email address to receive failure notifications. |

### Security

| Variable | Default | Description |
|----------|---------|-------------|
| `ADMIN_API_KEY` | Auto-generated each boot | API key for `/admin/debug` and `/admin/cleanup-fingerprints`. Set a fixed value to persist across restarts. |

### Claude AI Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `CLAUDE_MODEL` | `claude-sonnet-4-20250514` | Which Claude model to use. |
| `CLAUDE_MAX_TOKENS` | `4000` | Maximum response length. |
| `CLAUDE_TIMEOUT` | `60` | Seconds to wait for Claude. |

### Processing Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `MIN_CONFIDENCE_THRESHOLD` | `0.25` | Minimum AI confidence (0.0-1.0) to accept an extraction. |
| `IMAGE_FINGERPRINT_TTL_HOURS` | `24` | Hours to remember processed emails for deduplication. |

### Application Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Logging verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR`. |
| `ENV` | `development` | Environment label. |
| `DEBUG` | `false` | Enable debug mode. |

### Database

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./email_ghl.db` | Database connection string. Use PostgreSQL for production. |

### Optional Services

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_URL` | Not set | Redis URL for caching. Not required. |
| `SENTRY_DSN` | Not set | Sentry error tracking. |

---

## Setting Variables in Railway

1. Go to your Railway project > service > **Variables** tab
2. Click **+ New Variable** for each
3. Railway auto-restarts on save

## Setting Variables Locally

```bash
cp .env.example .env
# Edit .env with your values
```

> **Never commit `.env` to git.** It's in `.gitignore`.
