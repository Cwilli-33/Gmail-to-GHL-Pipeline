# Troubleshooting Guide

Common issues and how to fix them.

---

## Quick Health Check

Before diving into specific issues, verify the basics:

1. **Is the app running?** Visit `https://your-app.up.railway.app/health`
   - Should return: `{"status": "healthy"}`
   - If it doesn't load, the app is down — check Railway deployment logs

2. **Is DNS configured?** Look up your subdomain at [mxtoolbox.com](https://mxtoolbox.com)
   - Enter `inbound.yourdomain.com`
   - Should show `mx.sendgrid.net` as the MX record
   - If nothing shows, your DNS isn't configured yet

3. **Is SendGrid configured?** Log into SendGrid > Settings > Inbound Parse
   - Your receiving domain and destination URL should be listed
   - Destination URL should be `https://your-app.up.railway.app/webhook/email`

---

## Emails Sent but Nothing Happens in GHL

### SendGrid isn't receiving the email

**Symptoms:** No new contacts appear in GHL. No entries in the debug log.

**Check:**
1. Did you add the MX record for the correct subdomain? Verify at [mxtoolbox.com](https://mxtoolbox.com)
2. Is the MX record pointing to `mx.sendgrid.net` (not something else)?
3. Wait 15+ minutes — DNS propagation can take time
4. Are you sending to the correct subdomain? (e.g., `leads@inbound.yourdomain.com`, NOT `leads@yourdomain.com`)

### SendGrid receives the email but the webhook fails

**Symptoms:** No debug log entries. SendGrid may show failed deliveries in Activity Feed.

**Check:**
1. Is the Destination URL correct in SendGrid Inbound Parse settings? It should be:
   ```
   https://your-app.up.railway.app/webhook/email
   ```
2. Is "Send Raw" **unchecked**? The pipeline uses parsed mode, not raw mode.
3. Is the Railway app running? Check `/health`

### The webhook fires but the email is rejected

**Symptoms:** Debug log shows `REJECTED: sender not whitelisted`

**Fix:**
1. Check your `ALLOWED_SENDERS` environment variable in Railway
2. Make sure it includes the exact email address you're sending from
3. The comparison is case-insensitive, but the email must match exactly
4. Multiple senders are comma-separated: `broker@gmail.com,fund19@protonmail.com`
5. If the sender uses a "Display Name" format like `"John Doe <john@example.com>"`, the pipeline extracts just the email part — this should work automatically

### The email is processed but extraction fails

**Symptoms:** Debug log shows `SKIPPED: low confidence` or extraction errors.

**Check:**
1. Is the PDF a valid funding application? Bank-statement-only emails are skipped
2. Is the PDF readable? Scanned/blurry PDFs get low confidence scores
3. Check your `MIN_CONFIDENCE_THRESHOLD` — default is 0.25 (pretty lenient). Lower it if too many PDFs are being skipped

### The email is processed but GHL contact is wrong

**Symptoms:** Contact is created but data is in the wrong fields or missing.

**Check:**
1. Are your custom field IDs correct in `src/data_merger.py`? Each field ID must match your GHL location exactly
2. Did you create all 20 custom fields? Missing fields cause data to be silently dropped
3. Check the Source Documents field — is it created as **File Upload** type?

---

## Error: Claude API Key Invalid

**Symptoms:** Railway logs show `401 Unauthorized` or `authentication_error` from Claude.

**Fix:**
1. Verify your `CLAUDE_API_KEY` environment variable starts with `sk-ant-api03-`
2. Check your Anthropic account has credits: [console.anthropic.com](https://console.anthropic.com)
3. Make sure the key hasn't been revoked — generate a new one if needed
4. Restart the Railway deployment after updating the variable

---

## Error: GHL API Errors

### 401 Unauthorized

**Cause:** GHL API key is invalid or expired.

**Fix:**
1. Verify `GHL_API_KEY` starts with `pit-` (Private Integration Token)
2. Check that the Private Integration is still active in your GHL settings
3. Verify the integration has the required scopes: `contacts.readonly`, `contacts.write`, `locations.readonly`, `forms.write`

### 422 Unprocessable Entity

**Cause:** Data format issue — usually a phone number or email in the wrong format.

**What to do:** This is usually harmless. The contact will still be created, but the specific field that caused the error will be skipped. Check Railway logs for the specific field.

### 429 Too Many Requests

**Cause:** You're hitting GHL's rate limit.

**What to do:** The pipeline has built-in retry logic with exponential backoff. It will automatically retry up to 3 times. If you're processing a very high volume of emails quickly, the retries should handle it.

---

## Duplicate Contacts in GHL

**Symptoms:** The same lead appears multiple times in GHL.

**Possible causes:**
1. **Different PDFs, different data** — The pipeline matches by EIN, phone, email, and business name. If none of these match between two PDFs, it creates separate contacts
2. **Matching data not visible** — If the extracted phone/email doesn't match what's already in GHL (different formatting, different number), a new contact is created

**How the matching works (in priority order):**
1. Recent batch dedup (same sender, recent timeframe, matching fields)
2. EIN match (most reliable)
3. Phone number match
4. Email match
5. Business name + state match (fuzzy)

**To reduce duplicates:** Send all documents for the same lead in a single email. The pipeline processes the funding application first, then uploads all other PDFs as source documents to the same contact.

---

## Source Documents Not Uploading

**Symptoms:** Contact is created/updated but no files appear in the Source Documents field.

**Check:**
1. Is the `SOURCE_DOCUMENTS_FIELD_ID` environment variable set correctly?
2. Is the Source Documents custom field created as **File Upload** type (not Single Line or Text)?
3. Run `python scripts/get_field_ids.py` to verify the field ID
4. Check Railway logs for `PDF_UPLOAD_FAILED` entries
5. Verify your GHL Private Integration has the `forms.write` scope

---

## Only Bank Statements, No Funding App

**Symptoms:** Email contains only bank statements (no funding application). Debug log shows `SKIPPED: no funding application found`.

**This is expected behavior.** The pipeline needs a funding application to extract lead data and create the GHL contact. Bank statements alone don't have enough structured data.

**Fix:** Make sure to include the funding application PDF in the same email as the bank statements.

---

## Railway Deployment Issues

### App keeps restarting

**Check:**
1. Railway logs for crash errors
2. All required environment variables are set (CLAUDE_API_KEY, GHL_API_KEY, GHL_LOCATION_ID, ALLOWED_SENDERS, SOURCE_DOCUMENTS_FIELD_ID)
3. If any required variable is missing, the app may fail to process but should still start

### App is slow / timing out

The health check at `/health` must respond within 30 seconds. If the app is slow to start, Railway may kill it.

**Typical startup time:** 5-10 seconds. If it takes longer, check the logs for database initialization issues.

### Deployment fails to build

**Common causes:**
1. `requirements.txt` has a package that can't be installed — check the build logs
2. Dockerfile syntax error — should be unlikely if you haven't modified it

---

## Debug Endpoint

The pipeline has a built-in debug endpoint that shows the last 20 webhook events:

```
GET https://your-app.up.railway.app/admin/debug
Header: X-Api-Key: {YOUR_ADMIN_API_KEY}
```

This returns a JSON log of every email received, including all processing steps, errors, and outcomes.

**If you didn't set `ADMIN_API_KEY`:** The app auto-generates one on each startup and prints it in the Railway logs. Look for:
```
Auto-generated ADMIN_API_KEY (set env var to persist): xxxxxxxxxx
```

---

## Cleanup Stale Records

If the pipeline crashed mid-processing, it may leave "PROCESSING" placeholder records that block the same email from being retried. To clean these up:

```
POST https://your-app.up.railway.app/admin/cleanup-fingerprints
Header: X-Api-Key: {YOUR_ADMIN_API_KEY}
```

This removes:
- Old fingerprint records (based on TTL setting)
- Stale "PROCESSING" records older than 10 minutes

---

## Getting Help

If you're stuck:

1. **Check Railway logs** — they contain detailed step-by-step logging for every email processed
2. **Use the debug endpoint** — `/admin/debug` shows the last 20 events with full error details
3. **Test with a simple PDF** — try a clear, well-formatted funding application
4. **Verify one piece at a time:**
   - Health endpoint works? (`/health`)
   - DNS configured? (mxtoolbox.com)
   - SendGrid Inbound Parse configured?
   - Sender is whitelisted?
   - API keys are correct?
   - Custom fields are created?
