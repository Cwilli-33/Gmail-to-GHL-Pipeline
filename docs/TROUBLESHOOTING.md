# Troubleshooting Guide

Common issues and how to fix them.

---

## Quick Health Check

Before diving into specific issues, verify the basics:

1. **Is the app running?** Visit `https://your-app.up.railway.app/health`
   - Should return: `{"status": "healthy", "imap_monitoring": true}`
   - If `imap_monitoring` is `false`, IMAP credentials are missing or wrong
   - If it doesn't load at all, the app is down — check Railway deployment logs

2. **Is IMAP connected?** Check Railway logs for:
   - `IMAP connected and watching INBOX for uwteam@onixcap.net` — working
   - `IMAP monitor error` — connection problem (check credentials)

---

## Emails Arriving but No Leads in GHL

### IMAP isn't connecting

**Symptoms:** No new contacts in GHL. Health check shows `"imap_monitoring": false`.

**Check:**
1. Are IMAP credentials correct? (`IMAP_HOST`, `IMAP_EMAIL`, `IMAP_PASSWORD`)
2. Is the IMAP port correct? (993 for SSL, which is standard)
3. If using Gmail: did you generate an **app password**? Regular passwords don't work
4. Check Railway logs for specific IMAP error messages
5. Test credentials by adding the email to Outlook or Apple Mail — if it works there, it should work here

### IMAP connects but emails aren't detected

**Symptoms:** IMAP shows connected in logs, but new emails aren't triggering processing.

**Check:**
1. Is the email arriving in the **Inbox** folder? The monitor only watches Inbox
2. Check Railway logs for IDLE loop activity
3. Try redeploying — IMAP IDLE connections can sometimes drop silently

### Email is detected but extraction fails

**Symptoms:** Debug log shows the email was received but processing failed.

**Check:**
1. Is the PDF a valid funding application? Emails with only bank statements are skipped
2. Is the PDF readable? Corrupted or encrypted PDFs will fail
3. Check `MIN_CONFIDENCE_THRESHOLD` — default 0.25 is lenient. Lower it if too many PDFs are being rejected
4. Check Railway logs for Claude API errors

### Contact created but data is wrong or missing

**Symptoms:** Contact appears in GHL but fields are empty or incorrect.

**Check:**
1. Are custom field IDs correct in `src/data_merger.py`? Run `python scripts/get_field_ids.py` to verify
2. Did you create all 24 custom fields in GHL? Missing fields cause data to be silently dropped
3. Is the Source Documents field created as **File Upload** type?

---

## Error: Claude API Key Invalid

**Symptoms:** Railway logs show `401 Unauthorized` or `authentication_error` from Claude.

**Fix:**
1. Verify `CLAUDE_API_KEY` starts with `sk-ant-api03-`
2. Check credits at [console.anthropic.com](https://console.anthropic.com)
3. Regenerate the key if it was revoked
4. Restart Railway deployment after updating

---

## Error: GHL API Errors

### 401 Unauthorized

**Cause:** GHL API key is invalid or expired.

**Fix:**
1. Verify `GHL_API_KEY` starts with `pit-`
2. Check the Private Integration is still active in GHL settings
3. Verify scopes: `contacts.readonly`, `contacts.write`, `locations.readonly`, `forms.write`

### 422 Unprocessable Entity

**Cause:** Data format issue — usually a phone number or email in the wrong format.

**What to do:** Usually harmless. The contact is still created but the bad field is skipped. Check Railway logs for specifics.

### 429 Too Many Requests

**Cause:** GHL rate limit hit.

**What to do:** Built-in retry logic handles this automatically (up to 3 retries with exponential backoff).

---

## SSN Issues

### Masked SSN overwrote a full SSN

**This should not happen.** The pipeline has masking protection — a masked SSN (`XXX-XX-6789`) will never overwrite a full SSN (`123-45-6789`) already in GHL. Check Railway logs for:
- `SSN/sensitive field 'ssn_owner1': SKIPPED masked value — full value already exists in GHL`

If a full SSN was overwritten, check the extraction logs to see what Claude returned.

### SSN not being extracted

**Check:**
1. Is the PDF a funding application (not a credit scrub)? SSNs are typically only on applications
2. Check Railway logs for `ssn_owner1=YES/NO` in the EXTRACTED_FIELDS step
3. The SSN might be in a hard-to-read section — try a clearer scan

---

## Duplicate Contacts in GHL

**Possible causes:**
1. **Different PDFs, different data** — matching uses EIN, phone, email, and business name. If none match, a new contact is created
2. **Matching data not visible** — if extracted phone/email doesn't match what's in GHL

**How matching works (priority order):**
1. Recent batch dedup (same sender, recent timeframe, matching fields)
2. EIN match (most reliable)
3. Phone number match
4. Email match
5. Business name + state match (fuzzy)

---

## Source Documents Not Uploading

**Check:**
1. Is `SOURCE_DOCUMENTS_FIELD_ID` set in Railway environment variables?
2. Is the Source Documents field created as **File Upload** type (not Single Line)?
3. Run `python scripts/get_field_ids.py` to verify the field ID
4. Check Railway logs for `PDF_UPLOAD_FAILED` entries
5. Verify GHL Private Integration has the `forms.write` scope

---

## Email Body Not Appearing as Notes

**Check:**
1. Did the email have a plain text body? HTML-only emails may not have extractable text
2. Check Railway logs for `NOTE_CREATED` or `NOTE_FAILED` entries
3. In GHL, notes appear under the contact's **Notes** tab, not on the main card

---

## Processed/Failed Folders

### Emails not moving to Processed folder

**Check:**
1. The IMAP account needs permission to create folders and move messages
2. Check Railway logs for `Moved email UID ... to Processed` or folder creation errors
3. Some email providers restrict folder creation — check provider docs

### Email went to Failed folder

This means processing failed for this email. Check:
1. The failure notification email for the specific reason
2. Railway logs or `/admin/debug` for the error details
3. Common reasons: no PDF attachment, no funding application found, GHL API error

---

## Failure Notifications Not Sending

**Check:**
1. Is `SMTP_HOST` set? Notifications are disabled without it
2. Is `SMTP_PORT` correct? (587 for STARTTLS is standard)
3. SMTP uses the same `IMAP_EMAIL` and `IMAP_PASSWORD` credentials
4. If using Gmail: the app password works for both IMAP and SMTP
5. Check Railway logs for `Could not send failure notification` errors

---

## Railway Deployment Issues

### App keeps restarting

**Check:**
1. Railway logs for crash errors
2. All required variables are set (CLAUDE_API_KEY, GHL_API_KEY, GHL_LOCATION_ID, IMAP_HOST, IMAP_EMAIL, IMAP_PASSWORD)
3. IMAP connection failures will cause reconnect attempts (this is normal, not a crash)

### IMAP keeps reconnecting

**Normal behavior.** IMAP IDLE connections time out after ~5 minutes. The app automatically reconnects. You'll see periodic `Reconnecting` messages in logs — this is expected.

---

## Debug Endpoint

View the last 20 processing events:

```
GET https://your-app.up.railway.app/admin/debug
Header: X-Api-Key: {YOUR_ADMIN_API_KEY}
```

**If you didn't set `ADMIN_API_KEY`:** Check Railway logs on startup for:
```
Auto-generated ADMIN_API_KEY: xxxxxxxxxx
```

---

## Cleanup Stale Records

```
POST https://your-app.up.railway.app/admin/cleanup-fingerprints
Header: X-Api-Key: {YOUR_ADMIN_API_KEY}
```

Removes old fingerprint records and stale PROCESSING placeholders older than 10 minutes.

---

## Getting Help

If you're stuck:

1. **Check Railway logs** — detailed step-by-step logging for every email
2. **Use `/admin/debug`** — last 20 events with full error details
3. **Check the Processed/Failed folders** in the email inbox
4. **Verify one piece at a time:**
   - Health endpoint works? (`/health`)
   - IMAP connected? (check logs)
   - API keys correct?
   - Custom fields created? (all 24)
   - Source Documents field is File Upload type?
