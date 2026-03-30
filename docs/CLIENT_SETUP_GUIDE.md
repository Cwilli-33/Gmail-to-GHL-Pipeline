# Email Lead Pipeline — Client Setup Guide

This guide walks you through setting up automated email-to-CRM lead processing. Once configured, you receive PDF funding applications at a dedicated email address and leads are automatically created in GoHighLevel.

**Time required:** ~15 minutes
**Technical skill:** Basic (DNS + SendGrid account)

---

## What You'll Set Up

```
Lead PDF emailed to:  leads@inbound.yourdomain.com
                          ↓
SendGrid catches it and forwards to the processing server
                          ↓
AI extracts lead data from the PDF
                          ↓
Lead appears in your GoHighLevel CRM automatically
```

---

## Step 1: Get Your Railway Webhook URL

Your pipeline is deployed on Railway. You need its public URL for SendGrid configuration.

1. Log into [railway.app](https://railway.app)
2. Click on your pipeline service
3. Go to **Settings** > **Networking** > **Public Networking**
4. If you don't have a domain yet, click **Generate Domain**
5. Your URL will look like: `https://your-app-name-production.up.railway.app`
6. Your webhook URL is that domain + `/webhook/email`:
   ```
   https://your-app-name-production.up.railway.app/webhook/email
   ```
7. **Save this URL** — you'll need it in Step 4

---

## Step 2: Create a Free SendGrid Account

1. Go to [https://signup.sendgrid.com](https://signup.sendgrid.com)
2. Sign up for a **free account** (no credit card required)
3. Complete email verification
4. You do NOT need to set up any sending — we only use the receiving feature

---

## Step 3: Add a DNS Record to Your Domain

You need to add **one MX record** to a subdomain of your domain. This tells email servers to route mail for that subdomain to SendGrid.

**Important:** Use a subdomain (like `inbound`) — do NOT add this to your main domain or it will break your regular email.

### The record to add:

| Type | Host / Name | Value | Priority |
|------|-------------|-------|----------|
| MX   | `inbound`   | `mx.sendgrid.net` | 10 |

### Where to add it:

Go to wherever you manage your domain's DNS. Common providers:

- **GoDaddy:** Domains → DNS → Add Record
- **Cloudflare:** DNS → Records → Add Record
- **Namecheap:** Domain List → Manage → Advanced DNS → Add Record
- **Google Domains:** DNS → Custom Records → Manage

### Examples by provider:

**GoDaddy:**
- Type: MX
- Host: `inbound`
- Points to: `mx.sendgrid.net`
- Priority: 10
- TTL: 1 Hour

**Cloudflare:**
- Type: MX
- Name: `inbound`
- Mail server: `mx.sendgrid.net`
- Priority: 10

**Namecheap:**
- Type: MX Record
- Host: `inbound`
- Value: `mx.sendgrid.net`
- Priority: 10

### Verify it worked:

Wait 5–15 minutes, then check by going to [https://mxtoolbox.com](https://mxtoolbox.com) and entering `inbound.yourdomain.com`. You should see `mx.sendgrid.net` listed.

---

## Step 4: Configure SendGrid Inbound Parse

1. Log in to [https://app.sendgrid.com](https://app.sendgrid.com)
2. In the left sidebar, click **Settings**
3. Click **Inbound Parse**
4. Click **"Add Host & URL"**
5. Fill in:

| Field | Value |
|-------|-------|
| **Receiving Domain** | `inbound.yourdomain.com` (replace with your actual domain) |
| **Destination URL** | Your webhook URL from Step 1 (e.g. `https://your-app-name-production.up.railway.app/webhook/email`) |
| **Spam Check** | Leave unchecked |
| **Send Raw** | Leave unchecked |

6. Click **Add**

---

## Step 5: Whitelist Your Sender Email(s)

The system only processes emails from approved senders (for security). You configure this in your Railway deployment.

1. Go to [railway.app](https://railway.app) and open your pipeline service
2. Go to the **Variables** tab
3. Find (or create) the `ALLOWED_SENDERS` variable
4. Set it to the email address(es) you'll be receiving leads from, separated by commas:
   ```
   fund19@protonmail.com,broker@company.com
   ```
5. Railway will automatically restart with the new whitelist

---

## Step 6: Test It

1. From a whitelisted email address, compose a new email
2. **To:** `leads@inbound.yourdomain.com` (the part before @ can be anything)
3. **Attach** a PDF funding application
4. **Send** the email
5. Wait 30–60 seconds
6. Check GoHighLevel — the lead should appear as a new contact

---

## How to Use It Day-to-Day

- **Receive lead PDFs** at `leads@inbound.yourdomain.com` (or any address @inbound.yourdomain.com)
- **One email = one lead.** All documents for the same business should be in one email
- **Funding applications** are extracted and turned into GHL contacts
- **Bank statements** are uploaded as source documents to the contact
- **Duplicates** are handled automatically — if the business already exists in GHL, the contact is updated (not duplicated)
- **Email body is ignored** — only PDF attachments are processed

---

## Troubleshooting

### "I sent an email but no lead appeared"

1. **Check the sender:** Only whitelisted email addresses are processed. Make sure the email came from an address listed in your `ALLOWED_SENDERS` variable in Railway.
2. **Check the attachment:** Only PDF files are processed. Images, Word docs, and other formats are skipped.
3. **Check DNS:** Go to [mxtoolbox.com](https://mxtoolbox.com) and look up `inbound.yourdomain.com`. If no MX record shows, your DNS isn't set up yet.
4. **Wait a few minutes:** DNS changes can take up to 15 minutes. SendGrid processing takes 10–30 seconds.

### "The lead was created but some fields are missing"

The system extracts what it can see in the PDF. If the PDF is low quality, scanned poorly, or missing fields, those will be blank in GHL. The more complete the funding application, the better the extraction.

### "I got a duplicate contact"

The system tries hard to match existing contacts by EIN, phone, email, and business name. If the PDF has very little data, it may not find the match. You can merge duplicates manually in GHL.

---

## FAQ

**Q: Can I use any email address before the @?**
A: Yes. `leads@inbound...`, `apps@inbound...`, `anything@inbound...` — they all work.

**Q: Does this affect my regular email?**
A: No. The MX record is only on the `inbound` subdomain. Your regular `@yourdomain.com` email is untouched.

**Q: Is there a limit on how many emails I can receive?**
A: SendGrid's free plan allows up to 100 inbound emails per day. Paid plans have higher limits.

**Q: What types of PDFs work?**
A: Funding applications, credit scrubs, MCA applications, and similar business documents. Bank statements are detected and uploaded as source documents.

**Q: Can multiple people send leads to the same address?**
A: Yes, as long as each sender's email is in your `ALLOWED_SENDERS` list in Railway.
