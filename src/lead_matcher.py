"""Lead matching — multi-criteria search to prevent duplicate contacts in GHL."""
import logging
import re
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

import phonenumbers
from sqlalchemy.orm import Session

from src.ghl_client import GHLClient
from src.models import ProcessedEmail, LeadExtraction

logger = logging.getLogger(__name__)

# How far back to look for same-batch matches (handles large batches)
BATCH_WINDOW_MINUTES = 30


class LeadMatcher:
    """Searches GHL for existing contacts that match extracted lead data.

    Match priority (highest -> lowest):
        0. Recent local match — same email sender, matching extracted fields (batch dedup)
        1. EIN — unique federal identifier, near-certain match
        2. Phone — strong identifier, normalized to E.164
        3. Email — strong identifier
        4. Business name + state — fuzzy match with geographic verification
    """

    NAME_MATCH_THRESHOLD = 0.80

    def __init__(self, ghl_client: GHLClient):
        self.ghl = ghl_client

    async def find_match(
        self,
        extracted: Dict[str, Any],
        email_id: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str], int]:
        """Find the best matching GHL contact for extracted lead data.

        Args:
            extracted: Dict from ClaudeExtractor with business_info, owner_info, etc.
            email_id: Sender email address — used to detect multi-PDF leads.
            db: Database session — needed for same-batch local lookups.

        Returns:
            Tuple of (matched_contact, match_method, match_confidence).
            If no match found, returns (None, None, 0).
        """
        biz = extracted.get("business_info", {}) or {}
        owner = extracted.get("owner_info", {}) or {}

        # --- 0. Local batch dedup: check recent extractions from same email sender ---
        if email_id and db:
            contact = await self._find_match_in_recent_batch(
                email_id, db, biz, owner
            )
            if contact:
                logger.info("Matched by local batch dedup (same sender + matching fields)")
                return contact, "BATCH_DEDUP", 92

        # --- 1. Match by EIN (highest confidence) ---
        raw_ein = biz.get("ein")
        ein = self._normalize_ein(raw_ein)
        if ein:
            contact = await self._search_ein(ein)
            if contact:
                logger.info(f"Matched by EIN: {ein}")
                return contact, "EIN", 95
        elif raw_ein:
            ein_digits = self._extract_ein_digits(raw_ein)
            if ein_digits and len(ein_digits) >= 4:
                contact = await self._search_ein_partial(ein_digits, raw_ein)
                if contact:
                    logger.info(f"Matched by partial EIN: {raw_ein}")
                    return contact, "EIN_PARTIAL", 80

        # --- 2. Match by phone (business phone, then owner phone) ---
        for raw_phone in [biz.get("phone"), owner.get("phone")]:
            phone = self._normalize_phone(raw_phone)
            if phone:
                contact = await self._search_phone(phone)
                if contact:
                    logger.info(f"Matched by phone: {phone}")
                    return contact, "PHONE", 90

        # --- 3. Match by email ---
        for raw_email in [biz.get("email"), owner.get("email")]:
            email = self._normalize_email(raw_email)
            if email:
                contact = await self._search_email(email)
                if contact:
                    logger.info(f"Matched by email: {email}")
                    return contact, "EMAIL", 85

        # --- 4. Match by business name + state ---
        biz_name = biz.get("legal_name") or biz.get("dba")
        state = biz.get("state")
        if biz_name:
            contact = await self._search_business_name(biz_name, state)
            if contact:
                logger.info(f"Matched by business name: {biz_name}")
                return contact, "NAME", 70

        logger.info("No existing contact matched")
        return None, None, 0

    # -------------------------------------------------------------------------
    # Local batch dedup (handles multiple PDFs from same email)
    # -------------------------------------------------------------------------

    async def _find_match_in_recent_batch(
        self,
        email_id: str,
        db: Session,
        biz: Dict[str, Any],
        owner: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Check recently processed emails from the same sender for field-level matches.

        Returns the GHL contact if a match is found, None otherwise.
        """
        cutoff = datetime.utcnow() - timedelta(minutes=BATCH_WINDOW_MINUTES)

        # Get all recent extractions that have a contact_id
        recent_extractions = (
            db.query(LeadExtraction)
            .filter(
                LeadExtraction.contact_id.isnot(None),
                LeadExtraction.contact_id != "failed",
                LeadExtraction.created_at >= cutoff,
            )
            .order_by(LeadExtraction.created_at.desc())
            .limit(100)
            .all()
        )

        # Check ProcessedEmail for sender_email filtering
        recent_from_sender = (
            db.query(ProcessedEmail)
            .filter(
                ProcessedEmail.sender_email == email_id,
                ProcessedEmail.contact_id.isnot(None),
                ProcessedEmail.action.in_(["CREATE", "UPDATE"]),
                ProcessedEmail.processed_at >= cutoff,
            )
            .order_by(ProcessedEmail.processed_at.desc())
            .limit(100)
            .all()
        )

        # Build a set of contact_ids from this sender
        sender_contact_ids = {r.contact_id for r in recent_from_sender if r.contact_id}
        if not sender_contact_ids:
            return None

        # Filter extractions to only those from this sender
        sender_extractions = [
            e for e in recent_extractions if e.contact_id in sender_contact_ids
        ]

        if not sender_extractions:
            return None

        # Now compare current extracted fields against each recent extraction
        raw_ein = biz.get("ein")
        new_ein_digits = self._extract_ein_digits(raw_ein)

        new_phones = set()          # normalized E.164
        new_phone_digits = set()    # raw digits fallback
        for raw_phone in [biz.get("phone"), owner.get("phone")]:
            p = self._normalize_phone(raw_phone)
            if p:
                new_phones.add(p)
            if raw_phone:
                d = re.sub(r"\D", "", raw_phone)
                if len(d) >= 10:
                    new_phone_digits.add(d[-10:])

        new_emails = set()
        for raw_email in [biz.get("email"), owner.get("email")]:
            e = self._normalize_email(raw_email)
            if e:
                new_emails.add(e)

        new_biz_name = self._clean_business_name(
            biz.get("legal_name") or biz.get("dba") or ""
        )

        for ext in sender_extractions:
            # Check EIN match
            if new_ein_digits and ext.ein:
                if self._eins_match(raw_ein, ext.ein):
                    logger.info(
                        f"Batch dedup: EIN match '{raw_ein}' ~ '{ext.ein}' "
                        f"-> contact {ext.contact_id}"
                    )
                    contact = await self.ghl.get_contact(ext.contact_id)
                    if contact:
                        return contact

            # Check phone match
            if ext.owner_phone:
                ext_phone = self._normalize_phone(ext.owner_phone)
                if ext_phone and new_phones and ext_phone in new_phones:
                    logger.info(
                        f"Batch dedup: phone match {ext_phone} -> contact {ext.contact_id}"
                    )
                    contact = await self.ghl.get_contact(ext.contact_id)
                    if contact:
                        return contact
                if new_phone_digits:
                    ext_digits = re.sub(r"\D", "", ext.owner_phone)
                    if len(ext_digits) >= 10 and ext_digits[-10:] in new_phone_digits:
                        logger.info(
                            f"Batch dedup: phone digits match {ext_digits[-10:]} "
                            f"-> contact {ext.contact_id}"
                        )
                        contact = await self.ghl.get_contact(ext.contact_id)
                        if contact:
                            return contact

            # Check email match
            if new_emails and ext.owner_email:
                ext_email = self._normalize_email(ext.owner_email)
                if ext_email and ext_email in new_emails:
                    logger.info(
                        f"Batch dedup: email match {ext_email} -> contact {ext.contact_id}"
                    )
                    contact = await self.ghl.get_contact(ext.contact_id)
                    if contact:
                        return contact

            # Check business name fuzzy match
            if new_biz_name and ext.business_name:
                ext_clean = self._clean_business_name(ext.business_name)
                if ext_clean:
                    score = SequenceMatcher(
                        None, new_biz_name.lower(), ext_clean.lower()
                    ).ratio()
                    if score >= self.NAME_MATCH_THRESHOLD:
                        logger.info(
                            f"Batch dedup: name match '{new_biz_name}' ~ "
                            f"'{ext_clean}' (score={score:.2f}) -> contact {ext.contact_id}"
                        )
                        contact = await self.ghl.get_contact(ext.contact_id)
                        if contact:
                            return contact

        return None

    # -------------------------------------------------------------------------
    # GHL search helpers
    # -------------------------------------------------------------------------

    async def _search_ein(self, ein: str) -> Optional[Dict[str, Any]]:
        """Search GHL contacts by EIN (via general query search)."""
        contacts = await self.ghl.search_contacts(ein)
        for c in contacts:
            if self._contact_has_value(c, ein):
                return c
        return None

    async def _search_ein_partial(
        self, partial_digits: str, raw_ein: str
    ) -> Optional[Dict[str, Any]]:
        """Search GHL contacts using a partial EIN (e.g., last 4 digits)."""
        contacts = await self.ghl.search_contacts(partial_digits)
        for c in contacts:
            for field in ["companyName", "tags"]:
                field_val = c.get(field)
                if field_val and partial_digits in str(field_val).replace("-", ""):
                    pass

            custom_fields = c.get("customFields", c.get("customField", []))
            if isinstance(custom_fields, list):
                for cf in custom_fields:
                    cf_id = cf.get("id", cf.get("key", ""))
                    cf_val = cf.get("field_value", cf.get("value", ""))
                    if cf_id and "ein" in cf_id.lower() and cf_val:
                        if self._eins_match(raw_ein, str(cf_val)):
                            logger.info(
                                f"Partial EIN match: '{raw_ein}' ~ '{cf_val}'"
                            )
                            return c
        return None

    async def _search_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        """Search GHL contacts by normalized phone number."""
        contacts = await self.ghl.search_by_field("phone", phone)
        if contacts:
            return contacts[0]

        digits = re.sub(r"\D", "", phone)
        contacts = await self.ghl.search_contacts(digits)
        for c in contacts:
            contact_phone = self._normalize_phone(c.get("phone"))
            if contact_phone and contact_phone == phone:
                return c
        return None

    async def _search_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Search GHL contacts by email."""
        contacts = await self.ghl.search_by_field("email", email)
        if contacts:
            return contacts[0]

        contacts = await self.ghl.search_contacts(email)
        for c in contacts:
            contact_email = self._normalize_email(c.get("email"))
            if contact_email and contact_email == email:
                return c
        return None

    async def _search_business_name(
        self, name: str, state: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """Search GHL contacts by business name with fuzzy matching."""
        clean_name = self._clean_business_name(name)
        contacts = await self.ghl.search_contacts(clean_name)

        best_match = None
        best_score = 0.0

        for c in contacts:
            company = c.get("companyName", "") or ""
            clean_company = self._clean_business_name(company)
            if not clean_company:
                continue

            score = SequenceMatcher(None, clean_name.lower(), clean_company.lower()).ratio()

            if state and c.get("state", "").upper() == state.upper():
                score = min(score + 0.10, 1.0)

            if score > best_score and score >= self.NAME_MATCH_THRESHOLD:
                best_score = score
                best_match = c

        return best_match

    # -------------------------------------------------------------------------
    # Normalization helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _normalize_phone(raw: Optional[str]) -> Optional[str]:
        if not raw:
            return None
        try:
            parsed = phonenumbers.parse(raw, "US")
            if phonenumbers.is_valid_number(parsed):
                return phonenumbers.format_number(
                    parsed, phonenumbers.PhoneNumberFormat.E164
                )
        except phonenumbers.NumberParseException:
            pass
        digits = re.sub(r"\D", "", raw)
        if len(digits) == 10:
            return f"+1{digits}"
        if len(digits) == 11 and digits.startswith("1"):
            return f"+{digits}"
        return None

    @staticmethod
    def _normalize_ein(raw: Optional[str]) -> Optional[str]:
        """Normalize a full 9-digit EIN to XX-XXXXXXX format."""
        if not raw:
            return None
        digits = re.sub(r"\D", "", raw)
        if len(digits) == 9:
            return f"{digits[:2]}-{digits[2:]}"
        return None

    @staticmethod
    def _extract_ein_digits(raw: Optional[str]) -> Optional[str]:
        """Extract just the digits from any EIN representation."""
        if not raw:
            return None
        digits = re.sub(r"\D", "", raw)
        return digits if digits else None

    @staticmethod
    def _eins_match(ein_a: Optional[str], ein_b: Optional[str]) -> bool:
        """Check if two EIN values refer to the same entity."""
        if not ein_a or not ein_b:
            return False

        digits_a = re.sub(r"\D", "", ein_a)
        digits_b = re.sub(r"\D", "", ein_b)

        if not digits_a or not digits_b:
            return False

        if len(digits_a) == 9 and len(digits_b) == 9:
            return digits_a == digits_b

        if len(digits_a) == 9 and 4 <= len(digits_b) <= 9:
            return digits_a.endswith(digits_b)
        if len(digits_b) == 9 and 4 <= len(digits_a) <= 9:
            return digits_b.endswith(digits_a)

        if len(digits_a) >= 4 and len(digits_b) >= 4:
            min_len = min(len(digits_a), len(digits_b))
            return digits_a[-min_len:] == digits_b[-min_len:]

        return False

    @staticmethod
    def _normalize_email(raw: Optional[str]) -> Optional[str]:
        if not raw:
            return None
        email = raw.strip().lower()
        if "@" in email and "." in email.split("@")[-1]:
            return email
        return None

    @staticmethod
    def _clean_business_name(name: str) -> str:
        if not name:
            return ""
        cleaned = name.strip()
        suffixes = [
            r"\bllc\b", r"\binc\.?\b", r"\bcorp\.?\b", r"\bcorporation\b",
            r"\bltd\.?\b", r"\bco\.?\b", r"\bcompany\b", r"\bdba\b",
            r"\bd/b/a\b", r"\bthe\b",
        ]
        for suffix in suffixes:
            cleaned = re.sub(suffix, "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"[^\w\s]", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    @staticmethod
    def _contact_has_value(contact: Dict[str, Any], value: str) -> bool:
        value_lower = value.lower().replace("-", "")
        for field in ["companyName", "email", "phone", "name", "tags"]:
            field_val = contact.get(field)
            if field_val and value_lower in str(field_val).lower().replace("-", ""):
                return True
        custom_fields = contact.get("customFields", contact.get("customField", []))
        if isinstance(custom_fields, list):
            for cf in custom_fields:
                cf_val = cf.get("field_value", cf.get("value", ""))
                if cf_val and value_lower in str(cf_val).lower().replace("-", ""):
                    return True
        return False
