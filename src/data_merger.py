"""Smart data merging — combines extracted data with existing GHL contact data.

Maps extracted fields to exact GHL custom field IDs for the location.
"""
import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GHL Custom Field ID mapping
# ---------------------------------------------------------------------------
# These IDs come from the GHL API: GET /locations/{id}/customFields
# The key is a readable name; the value is the GHL field ID.

GHL_CUSTOM_FIELDS = {
    # Business identifiers
    "ein":                      "24QthvUKjKiEWBJr5kGN",
    "dba":                      "e34gazjAyNSaDXIWZOmq",
    "business_start_date":      "TtdjtsXprss3caSuPyXP",
    "state_of_incorporation":   "XFs2Swg2iv7eUcj18MI5",
    "industry":                 "3ZAqSshPhgXPUlLjRUNd",
    "business_phone":           "Mk6gFArjGHC91aosp0ql",

    # Owner 2
    "owner_2_name":             "6COH4V1v30QoSgruiZpO",
    "owner_2_phone":            "LddyH78lQfPPfdvVFIGk",

    # Financials
    "monthly_revenue":          "4nwh9GkL87CPx3rvYXte",
    "avg_daily_balance":        "Cwd0VoL1uJq5cyM9pfAB",
    "true_revenue_avg_3mo":     "jsqyKetf6dr66ku3vQXb",

    # Credit
    "fico_owner1":              "8xhJtYRSWIy1fxBmrO0n",
    "fico_owner2":              "SSSP2fzyfGVUMsghsaL0",

    # SSN
    "ssn_owner1":               "NEEDS_FIELD_ID",
    "ssn_owner2":               "NEEDS_FIELD_ID",

    # DOB
    "dob_owner1":               "NEEDS_FIELD_ID",
    "dob_owner2":               "NEEDS_FIELD_ID",

    # Statement numbers
    "statement_number":         "AXQyV1j0A8ByYGLvVFon",

    # Owner 1 home address
    "owner1_address":           "DUonmL5QgCisIDqFlPLy",
    "owner1_city":              "Pn4y4ppf4R5PLjJwRzcQ",
    "owner1_state":             "qAhft8fEIXB4A9fdmJLp",
    "owner1_zip":               "harMFyX4xvXghV4ksksB",

    # Metadata
    "batch_date":               "f7D788L5PQXxQHBZ1uRj",
}


def _is_valid_email(email: str) -> bool:
    """Basic email validation — must have exactly one @ with text on both sides and a dot in domain."""
    if not email or not isinstance(email, str):
        return False
    email = email.strip()
    if " " in email:
        return False
    parts = email.split("@")
    if len(parts) != 2:
        return False
    local, domain = parts
    if not local or not domain or "." not in domain:
        return False
    return True


class DataMerger:
    """Merges newly extracted lead data with an existing GHL contact.

    Rules:
        - Never overwrite existing data with empty/null values.
        - For numeric fields (revenue, credit score), prefer the higher or newer value.
        - For tags, append new tags without duplicating existing ones.
        - Custom fields are mapped by exact GHL field IDs.
    """

    def merge(
        self,
        existing_contact: Dict[str, Any],
        extracted: Dict[str, Any],
        match_method: str,
        match_confidence: int,
    ) -> Dict[str, Any]:
        """Produce a GHL-compatible update payload by merging extracted data into
        an existing contact."""
        biz = extracted.get("business_info", {}) or {}
        owner = extracted.get("owner_info", {}) or {}
        owner2 = extracted.get("owner2_info", {}) or {}
        fin = extracted.get("financial_info", {}) or {}
        credit = extracted.get("credit_info", {}) or {}
        mca = extracted.get("mca_info", {}) or {}

        update: Dict[str, Any] = {}

        update.update(self._merge_standard_fields(existing_contact, biz, owner))

        update["tags"] = self._merge_tags(
            existing_contact.get("tags", []),
            extracted,
            match_method,
        )

        custom = self._build_custom_fields(
            existing_contact, biz, owner, owner2, fin, credit, mca, extracted
        )
        if custom:
            update["customFields"] = self._format_custom_fields(custom)

        logger.info(
            f"Merged data for contact (match={match_method}, confidence={match_confidence}): "
            f"{len(update)} top-level fields, {len(custom)} custom fields"
        )

        return update

    def build_new_contact(self, extracted: Dict[str, Any]) -> Dict[str, Any]:
        """Build a GHL contact payload from scratch using only extracted data."""
        biz = extracted.get("business_info", {}) or {}
        owner = extracted.get("owner_info", {}) or {}
        owner2 = extracted.get("owner2_info", {}) or {}
        fin = extracted.get("financial_info", {}) or {}
        credit = extracted.get("credit_info", {}) or {}
        mca = extracted.get("mca_info", {}) or {}

        contact: Dict[str, Any] = {}

        # Name
        first = owner.get("first_name") or ""
        last = owner.get("last_name") or ""
        if not first and not last and owner.get("full_name"):
            parts = owner["full_name"].strip().split(None, 1)
            first = parts[0] if parts else ""
            last = parts[1] if len(parts) > 1 else ""

        if first:
            contact["firstName"] = first
        if last:
            contact["lastName"] = last

        # Contact info — prefer owner phone/email, fall back to business
        phone = owner.get("phone") or biz.get("phone")
        email = owner.get("email") or biz.get("email")
        if phone:
            contact["phone"] = self._clean_phone(phone)
        if email and _is_valid_email(email):
            contact["email"] = email.strip().lower()

        # Business details
        company = biz.get("legal_name") or biz.get("dba")
        if company:
            contact["companyName"] = company
        if biz.get("website"):
            contact["website"] = biz["website"]
        if biz.get("address"):
            contact["address1"] = biz["address"]
        if biz.get("city"):
            contact["city"] = biz["city"]
        if biz.get("state"):
            contact["state"] = biz["state"]
        if biz.get("zip_code"):
            contact["postalCode"] = biz["zip_code"]

        # Tags
        contact["tags"] = self._merge_tags([], extracted, None)

        # Source
        contact["source"] = "Email MCA Pipeline"

        # Custom fields
        custom = self._build_custom_fields(
            {}, biz, owner, owner2, fin, credit, mca, extracted
        )
        if custom:
            contact["customFields"] = self._format_custom_fields(custom)

        return contact

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _merge_standard_fields(
        self,
        existing: Dict[str, Any],
        biz: Dict[str, Any],
        owner: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Merge top-level GHL standard fields, never overwriting with empty values."""
        update: Dict[str, Any] = {}

        first = owner.get("first_name")
        last = owner.get("last_name")
        if not first and not last and owner.get("full_name"):
            parts = owner["full_name"].strip().split(None, 1)
            first = parts[0] if parts else None
            last = parts[1] if len(parts) > 1 else None

        self._set_if_better(update, existing, "firstName", first)
        self._set_if_better(update, existing, "lastName", last)

        phone = owner.get("phone") or biz.get("phone")
        email = owner.get("email") or biz.get("email")
        if phone:
            phone = self._clean_phone(phone)
        if email and _is_valid_email(email):
            email = email.strip().lower()
        else:
            email = None

        self._set_if_better(update, existing, "phone", phone)
        self._set_if_better(update, existing, "email", email)

        company = biz.get("legal_name") or biz.get("dba")
        self._set_if_better(update, existing, "companyName", company)
        self._set_if_better(update, existing, "website", biz.get("website"))
        self._set_if_better(update, existing, "address1", biz.get("address"))
        self._set_if_better(update, existing, "city", biz.get("city"))
        self._set_if_better(update, existing, "state", biz.get("state"))
        self._set_if_better(update, existing, "postalCode", biz.get("zip_code"))

        return update

    def _build_custom_fields(
        self,
        existing: Dict[str, Any],
        biz: Dict[str, Any],
        owner: Dict[str, Any],
        owner2: Dict[str, Any],
        fin: Dict[str, Any],
        credit: Dict[str, Any],
        mca: Dict[str, Any],
        extracted: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build a dict of {ghl_field_id: value} for custom fields."""
        custom: Dict[str, Any] = {}
        existing_custom = self._existing_custom_map(existing)

        # --- Business identifiers ---
        # EIN: prefer full unmasked values over masked ones
        new_ein = biz.get("ein")
        if new_ein:
            existing_ein = existing_custom.get(GHL_CUSTOM_FIELDS.get("ein", ""), "")
            new_is_masked = bool(re.search(r"[xX*]{2,}", str(new_ein)))
            existing_is_masked = bool(re.search(r"[xX*]{2,}", str(existing_ein))) if existing_ein else True
            # Only set if: new is unmasked, OR existing is empty/masked
            if not new_is_masked or not existing_ein or existing_is_masked:
                self._set_custom(custom, "ein", new_ein)

        self._set_custom(custom, "dba", biz.get("dba"))
        self._set_custom(custom, "business_start_date", biz.get("start_date"))
        self._set_custom(custom, "state_of_incorporation", biz.get("state_of_incorporation"))
        self._set_custom(custom, "industry", biz.get("industry"))
        self._set_custom(custom, "business_phone", biz.get("phone"))

        # --- Owner 2 ---
        self._set_custom(custom, "owner_2_name", owner2.get("full_name"))
        self._set_custom(custom, "owner_2_phone", owner2.get("phone"))

        # --- Financials (prefer higher revenue, newer values) ---
        self._set_custom_numeric_prefer_higher(
            custom, existing_custom, "monthly_revenue", fin.get("monthly_revenue")
        )
        self._set_custom_numeric(custom, existing_custom, "avg_daily_balance", fin.get("avg_daily_balance"))
        self._set_custom_numeric_prefer_higher(
            custom, existing_custom, "true_revenue_avg_3mo", fin.get("true_revenue_avg_3mo")
        )

        # --- Credit info ---
        self._set_custom_numeric(custom, existing_custom, "fico_owner1", credit.get("fico_owner1"))
        self._set_custom_numeric(
            custom, existing_custom, "fico_owner2",
            credit.get("fico_owner2") or owner2.get("fico")
        )

        # --- SSN ---
        self._set_custom(custom, "ssn_owner1", owner.get("ssn"))
        self._set_custom(custom, "ssn_owner2", owner2.get("ssn"))

        # --- DOB ---
        self._set_custom(custom, "dob_owner1", owner.get("dob"))
        self._set_custom(custom, "dob_owner2", owner2.get("dob"))

        # Statement numbers — accumulate across documents, don't overwrite
        new_stmts = extracted.get("statement_numbers")
        if new_stmts:
            existing_stmts = existing_custom.get(GHL_CUSTOM_FIELDS.get("statement_number", ""), "")
            merged = self._merge_statement_numbers(existing_stmts, new_stmts)
            if merged:
                ghl_id = GHL_CUSTOM_FIELDS.get("statement_number")
                if ghl_id:
                    custom[ghl_id] = merged

        # --- Owner 1 home address ---
        self._set_custom(custom, "owner1_address", owner.get("home_address"))
        self._set_custom(custom, "owner1_city", owner.get("home_city"))
        self._set_custom(custom, "owner1_state", owner.get("home_state"))
        self._set_custom(custom, "owner1_zip", owner.get("home_zip"))

        # --- Metadata ---
        custom[GHL_CUSTOM_FIELDS["batch_date"]] = datetime.utcnow().strftime("%Y%m%d")

        return custom

    def _merge_tags(
        self,
        existing_tags: Any,
        extracted: Dict[str, Any],
        match_method: Optional[str],
    ) -> List[str]:
        """Build a deduplicated tag list combining existing and new tags."""
        tags: List[str] = []
        if isinstance(existing_tags, list):
            tags = [t for t in existing_tags if isinstance(t, str)]
        elif isinstance(existing_tags, str):
            tags = [t.strip() for t in existing_tags.split(",") if t.strip()]

        new_tags = ["email-lead"]

        doc_type = extracted.get("document_type", "")
        if doc_type:
            new_tags.append(f"doc-{doc_type.lower()}")

        if match_method:
            new_tags.append(f"matched-{match_method.lower()}")

        mca = extracted.get("mca_info", {}) or {}
        has_positions = mca.get("has_existing_positions")
        if isinstance(has_positions, str):
            has_positions = has_positions.lower() not in ("false", "no", "none", "0", "")
        if has_positions:
            new_tags.append("existing-mca")

        fin = extracted.get("financial_info", {}) or {}
        rev = self._to_float(fin.get("monthly_revenue"))
        if rev and rev >= 50000:
            new_tags.append("high-revenue")

        credit = extracted.get("credit_info", {}) or {}
        fico = self._to_float(credit.get("fico_owner1"))
        if fico:
            if fico >= 700:
                new_tags.append("fico-700+")
            elif fico < 550:
                new_tags.append("fico-sub550")

        seen = {t.lower() for t in tags}
        for t in new_tags:
            if t.lower() not in seen:
                tags.append(t)
                seen.add(t.lower())

        return tags

    # -------------------------------------------------------------------------
    # Custom field helpers
    # -------------------------------------------------------------------------

    def _set_custom(self, custom: Dict, field_name: str, value: Any) -> None:
        """Set a custom field by name (maps to GHL ID) if value is non-empty."""
        if not value:
            return
        ghl_id = GHL_CUSTOM_FIELDS.get(field_name)
        if ghl_id and not ghl_id.startswith("NEEDS_"):
            custom[ghl_id] = str(value)

    def _set_custom_numeric(
        self, custom: Dict, existing_custom: Dict, field_name: str, value: Any
    ) -> None:
        new_val = self._to_float(value)
        if new_val is None:
            return
        ghl_id = GHL_CUSTOM_FIELDS.get(field_name)
        if ghl_id:
            custom[ghl_id] = str(new_val)

    def _set_custom_numeric_prefer_higher(
        self, custom: Dict, existing_custom: Dict, field_name: str, value: Any
    ) -> None:
        new_val = self._to_float(value)
        if new_val is None:
            return
        ghl_id = GHL_CUSTOM_FIELDS.get(field_name)
        if not ghl_id:
            return
        existing_val = self._to_float(existing_custom.get(ghl_id))
        if existing_val and existing_val > new_val:
            return
        custom[ghl_id] = str(new_val)

    @staticmethod
    def _format_custom_fields(custom: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [
            {"id": k, "field_value": v}
            for k, v in custom.items()
            if v is not None
        ]

    @staticmethod
    def _set_if_better(update, existing, key, new_value):
        if not new_value:
            return
        existing_val = existing.get(key)
        if not existing_val:
            update[key] = new_value

    @staticmethod
    def _existing_custom_map(contact: Dict[str, Any]) -> Dict[str, str]:
        result: Dict[str, str] = {}
        custom_fields = contact.get("customFields", contact.get("customField", []))
        if isinstance(custom_fields, list):
            for cf in custom_fields:
                fid = cf.get("id", "")
                fval = cf.get("field_value", cf.get("value", ""))
                if fid and fval:
                    result[fid] = str(fval)
        return result

    @staticmethod
    def _to_float(val: Any) -> Optional[float]:
        if val is None:
            return None
        try:
            if isinstance(val, str):
                cleaned = val.replace("$", "").replace(",", "").replace("%", "").strip()
                return float(cleaned) if cleaned else None
            return float(val)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _merge_statement_numbers(existing: str, new: str) -> str:
        seen = set()
        result = []
        for raw in [new, existing]:
            if not raw:
                continue
            for item in raw.split(","):
                item = item.strip()
                if item and item not in seen:
                    seen.add(item)
                    result.append(item)
        return ", ".join(result)

    @staticmethod
    def _clean_phone(raw: str) -> str:
        digits = re.sub(r"\D", "", raw)
        if len(digits) == 10:
            return f"+1{digits}"
        if len(digits) == 11 and digits.startswith("1"):
            return f"+{digits}"
        return raw
