# Email Lead Pipeline — Client Setup Guide

This guide walks you through setting up automated email-to-CRM lead processing. Once configured, lead emails received at your inbox are automatically extracted and appear as contacts in GoHighLevel.

**Time required:** ~15 minutes
**Technical skill:** Basic (just provide email credentials)

---

## What You'll Set Up

```
Lead email arrives at your inbox (e.g. uwteam@onixcap.net)
    ↓  (detected instantly)
AI extracts lead data from PDF attachments
    ↓
Lead appears in your GoHighLevel CRM automatically
    ↓
Email moved to "Processed" folder
```

---

## Step 1: Get Your Email IMAP Settings

The pipeline connects directly to your email inbox to monitor for new leads. You need your IMAP login settings — these are the same settings you'd use to add your email to Outlook or Apple Mail.

**What you need:**

| Setting | Example | Where to Find |
|---------|---------|---------------|
| IMAP Server | `mail.onixcap.net` | Your email provider's help docs or settings page |
| IMAP Port | `993` | Almost always 993 (SSL) |
| Email Address | `uwteam@onixcap.net` | Your email address |
| Password | Your email password | If 2FA is enabled, create an "app password" |

**Common IMAP servers by provider:**
- **Gmail:** `imap.gmail.com` (requires app password if 2FA enabled)
- **Outlook/Microsoft 365:** `outlook.office365.com`
- **GoDaddy:** `imap.secureserver.net`
- **cPanel/Webmail:** Usually `mail.yourdomain.com`

> **Tip:** Search "[your email provider] IMAP settings" if you're not sure.

---

## Step 2: Get Your GHL API Key and Location ID

### Create a Private Integration

1. Log into your GHL account
2. Go to **Settings** > **Integrations** > **Private Integrations**
3. Click **Create Private Integration**
4. Name it "Email Lead Pipeline"
5. Under **Scopes**, enable:
   - `contacts.readonly`
   - `contacts.write`
   - `locations.readonly`
   - `forms.write` (needed for file uploads)
6. Click **Save** and copy the **API Key** (starts with `pit-`)

### Find Your Location ID

Look at your GHL URL:
```
https://app.gohighlevel.com/v2/location/YOUR_LOCATION_ID/settings
```

---

## Step 3: Create GHL Custom Fields

Create the custom fields listed in the [GHL Custom Fields Guide](GHL_CUSTOM_FIELDS.md). Your operator will then run a script to pull the field IDs.

---

## Step 4: Deploy to Railway

1. Go to [railway.app](https://railway.app) and sign up
2. Click **New Project** > **Deploy from GitHub repo**
3. Select the pipeline repository
4. Go to the **Variables** tab and add:

| Variable | Value |
|----------|-------|
| `CLAUDE_API_KEY` | Your Anthropic API key |
| `GHL_API_KEY` | Your GHL Private Integration key |
| `GHL_LOCATION_ID` | Your GHL Location ID |
| `IMAP_HOST` | Your IMAP server (e.g. `mail.onixcap.net`) |
| `IMAP_PORT` | `993` |
| `IMAP_EMAIL` | Your email address (e.g. `uwteam@onixcap.net`) |
| `IMAP_PASSWORD` | Your email password |
| `SOURCE_DOCUMENTS_FIELD_ID` | GHL field ID (from your operator) |
| `SMTP_HOST` | Your SMTP server (usually same as IMAP host) |
| `SMTP_PORT` | `587` |

5. Railway will deploy automatically

---

## Step 5: Verify It's Running

1. Go to **Settings** > **Networking** > **Generate Domain** to get your public URL
2. Visit `https://your-app.up.railway.app/health`
3. You should see:
   ```json
   {"status": "healthy", "imap_monitoring": true}
   ```

---

## Step 6: Test It

1. Send (or have someone send) a test email with a PDF funding application to your monitored inbox
2. Wait 30-60 seconds
3. Check GoHighLevel — the lead should appear as a new contact
4. Check your email — the processed email should be in the "Processed" folder

---

## How It Works Day-to-Day

- **Every email** in your monitored inbox is treated as a lead
- **Funding application PDFs** are extracted and turned into GHL contacts
- **Bank statement PDFs** are uploaded as source documents to the contact
- **Email body text** is saved as a note on the GHL contact
- **Subject line** is used as a fallback business name if the PDF extraction misses it
- **Processed emails** are moved to a "Processed" folder in your inbox
- **Failed emails** are moved to a "Failed" folder — check these for issues
- **Duplicates** are handled automatically — same lead = update, not duplicate

---

## Troubleshooting

### "No leads are appearing"
1. Check that the app is running: visit `/health` — `imap_monitoring` should be `true`
2. Check Railway logs for IMAP connection errors
3. Verify your IMAP credentials are correct (try logging in with an email client)

### "Email stays in inbox (not moved to Processed)"
The pipeline might be crashing before it can move the email. Check Railway logs and `/admin/debug`.

### "Lead was created but some fields are missing"
The AI extracts what it can see in the PDF. Low-quality scans or incomplete applications will have gaps.

### "I got a failure notification email"
Check the "Failed" folder in your inbox. The notification includes the reason. Common causes:
- No PDF attachment in the email
- PDF is not a funding application (only bank statements)
- GHL API error (check your API key)

---

## FAQ

**Q: Does this affect my regular email?**
A: No. The pipeline only reads and moves emails — it doesn't delete them or change anything else.

**Q: What happens to processed emails?**
A: They're moved to a "Processed" folder in your inbox. You can review them anytime.

**Q: What if the same lead email comes in twice?**
A: It's detected as a duplicate and skipped automatically.

**Q: Do I need to keep the app running 24/7?**
A: Yes — Railway handles this. The app reconnects automatically if the connection drops.
