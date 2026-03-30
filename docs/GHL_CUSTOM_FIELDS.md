# GHL Custom Fields Reference

This document covers the 20 custom fields needed in your GHL location for the pipeline to store extracted lead data.

---

## What the Client Does

The client creates these fields in their GHL UI (point-and-click, no terminal). They follow the instructions below and let you know when they're done.

## What You (the Operator) Do

Once the client confirms the fields are created, run:

```bash
python scripts/get_field_ids.py
```

Paste the client's GHL API Key and Location ID when prompted. The script prints:
1. The exact `GHL_CUSTOM_FIELDS` dict to paste into `src/data_merger.py`
2. The `SOURCE_DOCUMENTS_FIELD_ID` to set as an environment variable

See the [Operator Guide](OPERATOR_GUIDE.md) for the full walkthrough.

---

## Required Custom Fields

Create all of the following custom fields in your GHL location under **Settings > Custom Fields**. The **Field Type** must match exactly.

### Business Information

| # | Field Name | Field Type | What It Stores |
|---|-----------|-----------|----------------|
| 1 | EIN | Single Line | Federal EIN (XX-XXXXXXX format) |
| 2 | DBA | Single Line | "Doing Business As" name |
| 3 | Business Start Date | Single Line | Date business was started/incorporated |
| 4 | State of Incorporation | Single Line | 2-letter state code |
| 5 | Industry | Single Line | Business type (Restaurant, Trucking, etc.) |
| 6 | Business Phone | Phone | Business phone number |

### Owner 2 (Second Owner/Partner)

| # | Field Name | Field Type | What It Stores |
|---|-----------|-----------|----------------|
| 7 | Owner 2 Name | Single Line | Second owner/partner full name |
| 8 | Owner 2 Phone | Phone | Second owner phone number |

### Financial Information

| # | Field Name | Field Type | What It Stores |
|---|-----------|-----------|----------------|
| 9 | Monthly Revenue | Single Line | Average monthly revenue/deposits |
| 10 | Avg Daily Balance | Single Line | Average daily bank balance |
| 11 | True Revenue Avg 3mo | Single Line | 3-month average true revenue |

### Credit Information

| # | Field Name | Field Type | What It Stores |
|---|-----------|-----------|----------------|
| 12 | FICO Owner 1 | Single Line | Primary owner credit score |
| 13 | FICO Owner 2 | Single Line | Second owner credit score |

### Statement Numbers

| # | Field Name | Field Type | What It Stores |
|---|-----------|-----------|----------------|
| 14 | Statement Number | Single Line | Masked account/statement identifiers |

### Owner 1 Home Address

| # | Field Name | Field Type | What It Stores |
|---|-----------|-----------|----------------|
| 15 | Owner 1 Address | Single Line | Owner home street address |
| 16 | Owner 1 City | Single Line | Owner home city |
| 17 | Owner 1 State | Single Line | Owner home state (2-letter code) |
| 18 | Owner 1 Zip | Single Line | Owner home ZIP code |

### Pipeline Metadata

| # | Field Name | Field Type | What It Stores |
|---|-----------|-----------|----------------|
| 19 | Batch Date | Single Line | Date the lead was processed (YYYYMMDD) |

### Source Documents (File Upload)

| # | Field Name | Field Type | What It Stores |
|---|-----------|-----------|----------------|
| 20 | Source Documents | **File Upload** | Original PDF documents (applications + bank statements) |

> **Important:** The "Source Documents" field MUST be created as **File Upload** type. All PDFs from each email (funding applications and bank statements) are uploaded here.

---

## Auto-Generated Tags

The pipeline automatically adds tags to contacts — no custom field setup needed:

| Tag | When Applied |
|-----|-------------|
| `email-lead` | Every contact from the pipeline |
| `doc-credit_scrub` | Credit scrub document detected |
| `doc-mca_application` | MCA application detected |
| `doc-bank_statement` | Bank statement detected |
| `doc-credit_report` | Credit report detected |
| `doc-funding_application` | Funding application detected |
| `existing-mca` | Lead has existing MCA positions |
| `high-revenue` | Monthly revenue >= $50,000 |
| `fico-700+` | Owner FICO score 700 or above |
| `fico-sub550` | Owner FICO score below 550 |
| `matched-ein` | Matched to existing contact by EIN |
| `matched-phone` | Matched to existing contact by phone |
| `matched-email` | Matched to existing contact by email |
| `matched-name` | Matched to existing contact by business name |
| `matched-batch_dedup` | Matched to a recent contact from the same sender |

---

## How Standard GHL Fields Are Used

In addition to the 20 custom fields above, the pipeline also writes to these built-in GHL contact fields:

| GHL Field | Source |
|-----------|--------|
| `firstName` | Owner first name |
| `lastName` | Owner last name |
| `phone` | Owner phone (falls back to business phone) |
| `email` | Owner email (falls back to business email) |
| `companyName` | Business legal name or DBA |
| `website` | Business website |
| `address1` | Business street address |
| `city` | Business city |
| `state` | Business state |
| `postalCode` | Business ZIP code |
| `source` | Set to "Email MCA Pipeline" |
| `tags` | Auto-generated tags (see above) |
