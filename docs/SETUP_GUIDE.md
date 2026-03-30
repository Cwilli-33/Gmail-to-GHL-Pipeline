# Setup Guide

This guide walks you through everything you need to get the Email Lead Capture Pipeline running. No coding experience required.

**Time required:** About 30-45 minutes

---

## Overview: What You Need

| Service | What It's For | Cost | What You'll Get From It |
|---------|--------------|------|------------------------|
| **SendGrid** | Receives inbound emails and forwards to the pipeline | Free tier (100 emails/day) | Inbound Parse webhook |
| **Anthropic (Claude)** | AI that reads PDF documents | ~$0.01-0.05/PDF | API Key |
| **GoHighLevel** | Your CRM where leads are stored | Your existing subscription | API Key + Location ID |
| **Railway.app** | Hosts the application 24/7 | Free tier or ~$5/month | Public URL |
| **Your Domain** | Receives emails at a subdomain | Your existing domain | MX record on subdomain |

---

## Step 1: Get Your Claude API Key

Claude is the AI that reads your PDF attachments and extracts the data.

1. Go to [console.anthropic.com](https://console.anthropic.com)
2. Create an account (or sign in)
3. Go to **API Keys** in the left sidebar
4. Click **Create Key**
5. Name it something like "Email MCA Pipeline"
6. Copy the key — it looks like this:
   ```
   sk-ant-api03-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```
7. **Save this key** — you'll need it in Step 4

### Add Credits

1. In the Anthropic console, go to **Plans & Billing**
2. Add a payment method
3. Add at least $5 in credits to start (this will process ~100-500 PDFs)

> **Cost:** Each PDF costs roughly $0.01-0.05 to process, depending on page count. Processing 100 leads per day costs about $1-5/day.

---

## Step 2: Get Your GHL API Key and Location ID

You need a Private Integration API key from GoHighLevel.

### Create a Private Integration

1. Log into your GHL account
2. Go to **Settings** > **Integrations** > **Private Integrations** (or Marketplace > Private Integrations)
3. Click **Create Private Integration** (or **+ Create App**)
4. Name it "Email Lead Pipeline"
5. Under **Scopes**, enable:
   - `contacts.readonly`
   - `contacts.write`
   - `locations.readonly`
   - `forms.write` (needed for file uploads)
6. Click **Save** and copy the **API Key** — it starts with `pit-`:
   ```
   pit-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
   ```
7. **Save this key** — you'll need it in Step 4

### Find Your Location ID

1. In GHL, go to **Settings** > **Business Profile** (or **Company**)
2. Look at the URL in your browser — it contains your Location ID:
   ```
   https://app.gohighlevel.com/v2/location/aBcDeFgHiJkLmNoPqRsT/settings
                                              ^^^^^^^^^^^^^^^^^^^^
                                              This is your Location ID
   ```
3. **Save this ID** — you'll need it in Step 4

### Create Custom Fields in GHL

Before the pipeline can store extracted data, you need to create custom fields in your GHL location. See the **[GHL Custom Fields Guide](GHL_CUSTOM_FIELDS.md)** for the exact list of fields to create.

> **Note:** The custom field IDs will be different for each GHL location. After creating the fields, run `python scripts/get_field_ids.py` to pull their IDs and update the code. See the [Operator Guide](OPERATOR_GUIDE.md) for details.

---

## Step 3: Deploy to Railway

Railway hosts your application so it runs 24/7.

### Create Your Railway Account

1. Go to [railway.app](https://railway.app)
2. Sign up with your GitHub account (recommended) or email
3. You get $5 free credit per month on the free tier

### Deploy the Application

**Option A: Deploy from GitHub (Recommended)**

1. Fork or connect this repository to your own GitHub account
2. In Railway, click **New Project** > **Deploy from GitHub repo**
3. Select your repository
4. Railway will automatically detect the Dockerfile and start building

**Option B: Deploy with Railway CLI**

1. Install the Railway CLI: `npm install -g @railway/cli`
2. Navigate to this project folder
3. Run:
   ```bash
   railway login
   railway init
   railway up
   ```

### Configure Environment Variables

1. In your Railway project, click on your service
2. Go to the **Variables** tab
3. Add these variables one at a time:

| Variable | Value | Required? |
|----------|-------|-----------|
| `CLAUDE_API_KEY` | Your Claude API key from Step 1 | Yes |
| `GHL_API_KEY` | Your GHL Private Integration key from Step 2 | Yes |
| `GHL_LOCATION_ID` | Your GHL Location ID from Step 2 | Yes |
| `ALLOWED_SENDERS` | Comma-separated email addresses (e.g. `broker@gmail.com,fund19@protonmail.com`) | Yes |
| `SOURCE_DOCUMENTS_FIELD_ID` | GHL custom field ID for Source Documents (from `get_field_ids.py`) | Yes |
| `LOG_LEVEL` | `INFO` | No (defaults to INFO) |
| `ADMIN_API_KEY` | Any random string for admin access | No (auto-generated) |
| `MIN_CONFIDENCE_THRESHOLD` | `0.25` | No (defaults to 0.25) |

4. Railway will automatically redeploy with your new variables

### Get Your Public URL

1. In Railway, click on your service
2. Go to **Settings** > **Networking**
3. Click **Generate Domain** to get a public URL like:
   ```
   your-app-name.up.railway.app
   ```
4. **Save this URL** — you need it for Step 4

---

## Step 4: Set Up Email Receiving (SendGrid + DNS)

This is the core step — making emails flow to your pipeline.

### 4a: Create a SendGrid Account

1. Go to [signup.sendgrid.com](https://signup.sendgrid.com)
2. Sign up for a free account (no credit card required)
3. Complete email verification
4. You do NOT need to set up any email sending — we only use the receiving feature

### 4b: Add a DNS MX Record

You need to route email for a subdomain to SendGrid. This does NOT affect your regular email.

**Add this MX record in your DNS provider** (GoDaddy, Cloudflare, Namecheap, etc.):

| Type | Host / Name | Value | Priority |
|------|-------------|-------|----------|
| MX | `inbound` | `mx.sendgrid.net` | 10 |

**Examples by provider:**

- **GoDaddy:** Domains > DNS > Add Record > Type: MX, Host: `inbound`, Points to: `mx.sendgrid.net`, Priority: 10
- **Cloudflare:** DNS > Records > Add Record > Type: MX, Name: `inbound`, Mail server: `mx.sendgrid.net`, Priority: 10
- **Namecheap:** Domain List > Manage > Advanced DNS > Add Record > Type: MX, Host: `inbound`, Value: `mx.sendgrid.net`, Priority: 10

**Wait 5-15 minutes** for DNS to propagate. Verify at [mxtoolbox.com](https://mxtoolbox.com) — look up `inbound.yourdomain.com`.

### 4c: Configure SendGrid Inbound Parse

1. Log in to [app.sendgrid.com](https://app.sendgrid.com)
2. Left sidebar > **Settings** > **Inbound Parse**
3. Click **"Add Host & URL"**
4. Fill in:

| Field | Value |
|-------|-------|
| **Receiving Domain** | `inbound.yourdomain.com` |
| **Destination URL** | `https://your-app.up.railway.app/webhook/email` |
| **Spam Check** | Leave unchecked |
| **Send Raw** | Leave **unchecked** (important!) |

5. Click **Add**

---

## Step 5: Test It!

1. Send an email **from a whitelisted sender** (listed in `ALLOWED_SENDERS`) to any address at your subdomain:
   ```
   leads@inbound.yourdomain.com
   ```
   The part before `@` can be anything — SendGrid catches all mail to that subdomain.

2. **Attach a PDF** funding application to the email
3. Wait 30-60 seconds
4. Check your GHL CRM — a new contact should appear with the extracted data

### Verify the Pipeline is Running

Visit your Railway URL in a browser:
```
https://your-app.up.railway.app/health
```

You should see:
```json
{"status": "healthy", "database": "connected", "message": "Ready to process emails"}
```

---

## You're Done!

Your pipeline is now running. Every time a whitelisted sender emails a PDF to your intake address, the data is automatically extracted and appears in your GHL CRM.

### What to Do Next

- **Send more PDFs** — the pipeline handles multiple PDFs in a single email, merging data intelligently
- **Check the debug log** — visit `https://your-app.up.railway.app/admin/debug` (requires your ADMIN_API_KEY in the `X-Api-Key` header)
- **Monitor costs** — check your Anthropic dashboard for API usage
- **Read the [Troubleshooting Guide](TROUBLESHOOTING.md)** if anything isn't working

---

## How It Works Day-to-Day

- **Send emails** to `leads@inbound.yourdomain.com` (or any address @inbound.yourdomain.com)
- **One email = one lead.** Attach all documents for the same business in one email
- **Funding applications** are extracted and turned into GHL contacts
- **Bank statements** are uploaded as source documents to the contact
- **Duplicates** are handled automatically — if the business already exists in GHL, the contact is updated (not duplicated)
- **Email body is ignored** — only PDF attachments are processed

---

## Updating the Application

When you receive code updates:

1. Push the new code to your GitHub repository
2. Railway will automatically detect the change and redeploy
3. No need to change any SendGrid or DNS settings

---

## Monthly Costs Estimate

| Service | Usage | Estimated Cost |
|---------|-------|---------------|
| Railway | Hosting 24/7 | $0-5/month |
| Anthropic Claude | 100 PDFs/day | $30-150/month |
| SendGrid | 100 emails/day | Free (up to 100/day) |
| GHL | Your existing plan | No additional cost |
| Domain | Your existing domain | No additional cost |

> **Total estimated cost:** $30-155/month for moderate usage (100 leads/day)
