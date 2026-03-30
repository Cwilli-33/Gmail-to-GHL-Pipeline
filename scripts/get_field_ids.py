"""
Fetch GHL custom field IDs for a client's location.

Run:  python scripts/get_field_ids.py

It will ask for the client's API key and Location ID, then print
the exact code to paste into src/data_merger.py and src/main.py.
"""
import json
import sys
try:
    import urllib.request
except ImportError:
    print("Error: Python 3 is required.")
    sys.exit(1)


# The 20 field names (display name in GHL -> key in our code)
EXPECTED_FIELDS = {
    "EIN": "ein",
    "DBA": "dba",
    "Business Start Date": "business_start_date",
    "State of Incorporation": "state_of_incorporation",
    "Industry": "industry",
    "Business Phone": "business_phone",
    "Owner 2 Name": "owner_2_name",
    "Owner 2 Phone": "owner_2_phone",
    "Monthly Revenue": "monthly_revenue",
    "Avg Daily Balance": "avg_daily_balance",
    "True Revenue Avg 3mo": "true_revenue_avg_3mo",
    "FICO Owner 1": "fico_owner1",
    "FICO Owner 2": "fico_owner2",
    "Statement Number": "statement_number",
    "Owner 1 Address": "owner1_address",
    "Owner 1 City": "owner1_city",
    "Owner 1 State": "owner1_state",
    "Owner 1 Zip": "owner1_zip",
    "Batch Date": "batch_date",
    "Source Documents": "source_documents",
}


def main():
    print("=" * 60)
    print("  GHL Custom Field ID Finder")
    print("=" * 60)
    print()
    print("You need two things from the client:")
    print("  1. Their GHL API Key (starts with pit-)")
    print("  2. Their GHL Location ID (from their GHL URL)")
    print()

    api_key = input("Paste the GHL API Key: ").strip()
    if not api_key:
        print("No API key entered. Exiting.")
        return

    location_id = input("Paste the GHL Location ID: ").strip()
    if not location_id:
        print("No Location ID entered. Exiting.")
        return

    print()
    print("Fetching custom fields...")
    print()

    url = f"https://services.leadconnectorhq.com/locations/{location_id}/customFields"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Version", "2021-07-28")
    req.add_header("Accept", "application/json")

    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"ERROR: GHL API returned {e.code}")
        if e.code == 401:
            print("  -> The API key is invalid or expired.")
        elif e.code == 404:
            print("  -> The Location ID is wrong.")
        else:
            print(f"  -> {e.read().decode()}")
        return
    except Exception as e:
        print(f"ERROR: Could not connect to GHL API: {e}")
        return

    fields = data.get("customFields", [])
    if not fields:
        print("No custom fields found in this location.")
        print("Make sure the client has created all 20 fields first.")
        return

    # Match GHL fields to our expected fields (case-insensitive)
    matched = {}
    source_docs_id = None
    ghl_lookup = {}
    for f in fields:
        ghl_lookup[f["name"].strip().lower()] = f

    print(f"Found {len(fields)} custom fields in this location.")
    print()

    missing = []
    for ghl_name, code_key in EXPECTED_FIELDS.items():
        found = ghl_lookup.get(ghl_name.strip().lower())
        if found:
            if code_key == "source_documents":
                source_docs_id = found["id"]
            else:
                matched[code_key] = found["id"]
        else:
            missing.append(ghl_name)

    # --- Print results ---

    if missing:
        print("WARNING - These fields are MISSING (client needs to create them):")
        for name in missing:
            print(f"  - {name}")
        print()

    matched_count = len(matched) + (1 if source_docs_id else 0)
    print(f"Matched {matched_count} of 20 fields.")
    print()

    # Print the dict for data_merger.py
    print("=" * 60)
    print("  STEP 1: Paste this into src/data_merger.py")
    print("  (Replace the entire GHL_CUSTOM_FIELDS dict)")
    print("=" * 60)
    print()
    print("GHL_CUSTOM_FIELDS = {")
    groups = [
        ("Business identifiers", ["ein", "dba", "business_start_date", "state_of_incorporation", "industry", "business_phone"]),
        ("Owner 2", ["owner_2_name", "owner_2_phone"]),
        ("Financials", ["monthly_revenue", "avg_daily_balance", "true_revenue_avg_3mo"]),
        ("Credit", ["fico_owner1", "fico_owner2"]),
        ("Statement numbers", ["statement_number"]),
        ("Owner 1 home address", ["owner1_address", "owner1_city", "owner1_state", "owner1_zip"]),
        ("Metadata", ["batch_date"]),
    ]
    for group_name, keys in groups:
        print(f"    # {group_name}")
        for key in keys:
            field_id = matched.get(key, "MISSING_FIELD")
            padding = " " * (24 - len(key))
            print(f'    "{key}":{padding}"{field_id}",')
        print()
    print("}")
    print()

    # Print the Source Documents ID
    print("=" * 60)
    print("  STEP 2: Set this as the SOURCE_DOCUMENTS_FIELD_ID env var")
    print("=" * 60)
    print()
    if source_docs_id:
        print(f'SOURCE_DOCUMENTS_FIELD_ID={source_docs_id}')
    else:
        print('SOURCE_DOCUMENTS_FIELD_ID=MISSING_FIELD')
        print("  -> Source Documents field not found! Client needs to create it as File Upload type.")
    print()

    print("=" * 60)
    print("  DONE!")
    print("=" * 60)
    print()
    print("After updating data_merger.py and .env, push to GitHub:")
    print("  git add src/data_merger.py .env")
    print('  git commit -m "Configure field IDs for client"')
    print("  git push origin main")
    print()
    print("The Docker image will rebuild automatically (~2 min).")
    print("Then redeploy on Railway.")


if __name__ == "__main__":
    main()
