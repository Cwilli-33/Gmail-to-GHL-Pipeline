# Operator Guide — How to Deliver & Maintain the Pipeline

This is your internal guide for onboarding a client and maintaining their deployment.

---

## Architecture Overview

```
Email sender (whitelisted address)
    |
    v
Client's intake subdomain (e.g. inbound.clientdomain.com)
    |  MX record → mx.sendgrid.net
    v
Client's SendGrid account (Inbound Parse)
    |  POST multipart/form-data
    v
Railway deployment (POST /webhook/email)
    |
    ├─ Validate sender against ALLOWED_SENDERS
    ├─ Extract PDF attachments
    ├─ Deduplicate by Message-ID
    ├─ Send each PDF to Claude for extraction
    ├─ Classify: funding app vs bank statement
    ├─ Match/create GHL contact from funding app
    └─ Upload ALL PDFs to Source Documents field
```

**Who owns what:**
- **You:** Source code on GitHub
- **Client:** Their SendGrid account, domain/DNS, Railway deployment, Claude API key, GHL account

---

## Onboarding a New Client

### Step 1: Client Creates GHL Custom Fields

Send the client the [GHL Custom Fields Guide](GHL_CUSTOM_FIELDS.md).

Tell them:
> "Create these 20 custom fields in your GHL location, then let me know when you're done. I'll handle the rest."

### Step 2: Pull Their Field IDs (You Do This)

Once the client confirms the fields are created, you need their **GHL API Key** and **Location ID**.

Run this from your project folder:

```bash
python scripts/get_field_ids.py
```

It will ask you to paste the client's API key and Location ID, then it prints:
1. The exact `GHL_CUSTOM_FIELDS` dict to paste into `src/data_merger.py`
2. The `SOURCE_DOCUMENTS_FIELD_ID` to set as an environment variable

If any fields are missing, it tells you which ones the client still needs to create.

### Step 3: Update the Code

1. Copy the `GHL_CUSTOM_FIELDS = { ... }` block from the script output
2. Open `src/data_merger.py` and replace the entire `GHL_CUSTOM_FIELDS` dict with it
3. Note the `SOURCE_DOCUMENTS_FIELD_ID` — the client will set this as an env var

### Step 4: Push the Update

```bash
git add src/data_merger.py
git commit -m "Configure GHL field IDs for [client name]"
git push origin main
```

Railway will auto-redeploy.

### Step 5: Client Sets Up SendGrid + DNS

Send the client the [Client Setup Guide](CLIENT_SETUP_GUIDE.md).

They need to:
1. Create a free SendGrid account
2. Add one MX record to their domain (`inbound` → `mx.sendgrid.net`)
3. Configure SendGrid Inbound Parse with their subdomain + your Railway webhook URL

### Step 6: Client Sets Environment Variables

The client sets these in their Railway deployment:

| Variable | Where They Get It |
|----------|------------------|
| `CLAUDE_API_KEY` | Their Anthropic account |
| `GHL_API_KEY` | Their GHL Private Integration |
| `GHL_LOCATION_ID` | Their GHL URL |
| `ALLOWED_SENDERS` | Their list of sender emails |
| `SOURCE_DOCUMENTS_FIELD_ID` | From your `get_field_ids.py` output |

### Step 7: Test

Have the client send a test email with a PDF from their whitelisted sender address to their intake subdomain. Verify:
1. Contact appears in GHL
2. Data is in the correct fields
3. Source document PDF is attached

---

## Pushing Updates

When you update the pipeline code:

1. Make your changes in the source code
2. Push to `main`
3. Railway auto-redeploys (if connected to GitHub)
4. If not auto-deploying, tell the client:
   > "We pushed an update. In Railway, click your service > Deployments > Redeploy."

---

## Monitoring a Client's Deployment

You don't have direct access to their Railway logs, but you can ask them to:

1. **Check health:** Visit `https://their-app.up.railway.app/health`
2. **Check debug log:**
   ```bash
   curl -H "X-Api-Key: THEIR_ADMIN_KEY" https://their-app.up.railway.app/admin/debug
   ```
3. **Clean up stuck records:**
   ```bash
   curl -X POST -H "X-Api-Key: THEIR_ADMIN_KEY" https://their-app.up.railway.app/admin/cleanup-fingerprints
   ```

---

## Adding/Removing Whitelisted Senders

To change who can send emails to the pipeline:

1. In Railway, update the `ALLOWED_SENDERS` environment variable
2. Comma-separated, case-insensitive: `fund19@protonmail.com,newbroker@gmail.com`
3. Railway auto-restarts with the new list

---

## Important Files Reference

| File | What It Does | When to Edit |
|------|-------------|-------------|
| `src/data_merger.py` | GHL custom field ID mapping + merge logic | Per-client onboarding |
| `src/main.py` | Webhook handler + full pipeline orchestration | Rarely — feature changes |
| `src/claude_extractor.py` | Claude extraction prompt for PDFs | When changing what gets extracted |
| `src/email_processor.py` | SendGrid webhook parsing + sender validation | Rarely |
| `src/ghl_client.py` | GHL API client with connection pooling + file upload | Rarely |
| `src/lead_matcher.py` | Contact matching logic (EIN, phone, email, name) | Rarely |
| `config/settings.py` | All environment variable definitions | When adding new settings |
| `scripts/get_field_ids.py` | Fetch GHL custom field IDs for a location | Per-client onboarding |

---

## Key Differences from Telegram Pipeline

If you're familiar with the TG-to-GHL pipeline, here's what changed:

| Aspect | Telegram Pipeline | Email Pipeline |
|--------|------------------|----------------|
| **Input** | Telegram photos (images) | SendGrid emails (PDFs) |
| **Claude API** | Image content block | Document content block |
| **Dedup key** | file_id + file_size | Email Message-ID header |
| **Batch grouping** | chat_id (Telegram chat) | sender_email |
| **Source tag** | `telegram-lead` | `email-lead` |
| **Contact source** | "Telegram MCA Pipeline" | "Email MCA Pipeline" |
| **Source Docs upload** | Credit scrubs only | All PDFs (apps + statements) |
| **Source Docs field ID** | Hardcoded in main.py | Configurable via env var |
| **DB table** | `processed_images` | `processed_emails` |
| **Webhook** | `/webhook/telegram` | `/webhook/email` |

---

## Credentials Reference

These are YOUR credentials — never share them with the client:

| Credential | Where It's Used | Where It's Stored |
|-----------|----------------|-------------------|
| GitHub SSH key | Pushing code | `~/.ssh/id_ed25519` |
| GitHub repo access | Source code management | github.com/Cwilli-33/Gmail-to-GHL-Pipeline |

These are the CLIENT's credentials — they manage them:

| Credential | They Set In |
|-----------|------------|
| CLAUDE_API_KEY | Railway env vars |
| GHL_API_KEY | Railway env vars |
| GHL_LOCATION_ID | Railway env vars |
| ALLOWED_SENDERS | Railway env vars |
| SOURCE_DOCUMENTS_FIELD_ID | Railway env vars |
| ADMIN_API_KEY | Railway env vars (optional) |
| SendGrid account | Their SendGrid dashboard |
| Domain DNS | Their DNS provider |
