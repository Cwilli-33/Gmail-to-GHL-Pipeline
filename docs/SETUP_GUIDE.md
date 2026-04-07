# Setup Guide

Complete setup walkthrough for the Email Lead Pipeline.

**Time required:** About 20-30 minutes

---

## Overview: What You Need

| Service | What It's For | Cost | What You'll Get From It |
|---------|--------------|------|------------------------|
| **Email Inbox** | Where leads arrive | Existing email | IMAP credentials |
| **Anthropic (Claude)** | AI that reads PDFs | ~$0.01-0.05/PDF | API Key |
| **GoHighLevel** | CRM where leads are stored | Existing subscription | API Key + Location ID |
| **Railway.app** | Hosts the application 24/7 | Free tier or ~$5/month | Public URL |

---

## Step 1: Get Your Claude API Key

1. Go to [console.anthropic.com](https://console.anthropic.com)
2. Create an account or sign in
3. Go to **API Keys** > **Create Key**
4. Name it "Email MCA Pipeline"
5. Add at least $5 in credits under **Plans & Billing**

---

## Step 2: Get Your GHL API Key and Location ID

1. GHL > **Settings** > **Integrations** > **Private Integrations** > **Create**
2. Name: "Email Lead Pipeline"
3. Scopes: `contacts.readonly`, `contacts.write`, `locations.readonly`, `forms.write`
4. Copy the API key (starts with `pit-`)
5. Get Location ID from your GHL URL

### Create Custom Fields

Create all 24 fields from the [GHL Custom Fields Guide](GHL_CUSTOM_FIELDS.md), then run:
```bash
python scripts/get_field_ids.py
```

---

## Step 3: Get Your IMAP Credentials

These are the same settings you'd use to add your email to Outlook or Apple Mail:

| Setting | How to Find |
|---------|-------------|
| IMAP Host | Check your email provider's help docs |
| IMAP Port | Almost always `993` |
| Email | Your lead intake email address |
| Password | Your email password (use app password if 2FA enabled) |
| SMTP Host | Usually same as IMAP host |
| SMTP Port | Usually `587` |

---

## Step 4: Deploy to Railway

1. Go to [railway.app](https://railway.app) and sign up
2. **New Project** > **Deploy from GitHub repo** > select this repository
3. Add environment variables (see [ENV_REFERENCE.md](ENV_REFERENCE.md))
4. **Settings** > **Networking** > **Generate Domain**
5. Visit `/health` to verify

---

## Step 5: Test

1. Send an email with a PDF funding application to your monitored inbox
2. Wait 30-60 seconds
3. Check GHL — contact should appear
4. Check your inbox — email should be in "Processed" folder

---

## Monthly Costs Estimate

| Service | Usage | Estimated Cost |
|---------|-------|---------------|
| Railway | Hosting 24/7 | $0-5/month |
| Anthropic Claude | 100 PDFs/day | $30-150/month |
| Email | Existing inbox | No additional cost |
| GHL | Existing plan | No additional cost |
