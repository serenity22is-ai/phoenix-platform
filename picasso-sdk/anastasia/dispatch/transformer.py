"""
PassengerTransformer — Converts MYSTES standard form data to provider-specific format.

Reads the knowledge card's `passenger_format` field to know:
- Field names (firstName vs given_name vs name vs nameGiven)
- Gender values (Male/Female vs m/f vs null)
- Date format (YYYY-MM-DD vs DD/MM/YYYY)
- Title casing (mr vs MR vs Mr)
- Type codes (ADT vs adult)
- Contact field names (email vs emailContact, phone vs phone_number)

Zero Anthropic API cost — pure Python string mapping.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class PassengerTransformer:
    """Transform MYSTES passenger data to any provider's format using knowledge cards."""

    def transform_all(self, passenger_data: dict, card: dict) -> list:
        """
        Transform primary passenger + additional passengers.

        Args:
            passenger_data: MYSTES standard form data:
                {first_name, last_name, date_of_birth (YYYY-MM-DD),
                 gender (M/F), email, phone, title, passport_number,
                 nationality, additional_passengers: [...]}
            card: Knowledge card dict with passenger_format field.

        Returns:
            List of provider-formatted passenger dicts.
        """
        pax_format = card.get("passenger_format", {})
        passengers = []

        # Primary passenger (includes contact info)
        primary = self._transform_one(passenger_data, pax_format, is_primary=True)
        passengers.append(primary)

        # Additional passengers
        for extra in passenger_data.get("additional_passengers", []):
            pax = self._transform_one(extra, pax_format, is_primary=False)
            passengers.append(pax)

        return passengers

    def _transform_one(self, pax: dict, fmt: dict, is_primary: bool = False) -> dict:
        """Transform a single passenger using the card's passenger_format."""
        result = {}

        # --- Name fields ---
        name_fields = fmt.get("name_fields", ["first_name", "last_name"])
        first_name = pax.get("first_name", "")
        last_name = pax.get("last_name", "")

        if len(name_fields) >= 2:
            result[name_fields[0]] = first_name
            result[name_fields[1]] = last_name
        else:
            result["first_name"] = first_name
            result["last_name"] = last_name

        # --- Gender ---
        gender_raw = pax.get("gender", "").upper()
        gender_values = fmt.get("gender_values")

        if gender_values and len(gender_values) >= 2:
            # gender_values[0] = male variant, [1] = female variant
            if gender_raw in ("M", "MALE"):
                result["gender"] = gender_values[0]
            elif gender_raw in ("F", "FEMALE"):
                result["gender"] = gender_values[1]
            else:
                result["gender"] = gender_values[0]  # default to male
        # If gender_values is null (e.g. Kiwi), omit gender

        # --- Title ---
        title_field = fmt.get("title_field", "title")
        title_values = fmt.get("title_values")

        if title_values:
            # Map based on gender or input title
            input_title = pax.get("title", "").lower().rstrip(".")
            matched = False
            for tv in title_values:
                if tv.lower() == input_title:
                    result[title_field] = tv
                    matched = True
                    break
            if not matched:
                # Default based on gender
                if gender_raw in ("M", "MALE"):
                    result[title_field] = title_values[0]  # mr/MR
                else:
                    # Find ms/MS or mrs/MRS
                    for tv in title_values:
                        if tv.lower() in ("ms", "mrs"):
                            result[title_field] = tv
                            matched = True
                            break
                    if not matched:
                        result[title_field] = title_values[1] if len(title_values) > 1 else title_values[0]

        # --- Date of birth ---
        dob_raw = pax.get("date_of_birth", "")
        dob_field = fmt.get("dob_field", "date_of_birth")
        dob_format = fmt.get("dob_format", "YYYY-MM-DD")

        if dob_raw:
            result[dob_field] = self._convert_date(dob_raw, dob_format)

        # --- Passenger type ---
        type_codes = fmt.get("type_codes", [])
        type_field = fmt.get("type_field", "paxType")

        if type_codes:
            # Default to adult/ADT — caller can override for children/infants
            pax_type_hint = pax.get("passenger_type", "adult").lower()
            if pax_type_hint in ("adult", "adt"):
                result[type_field] = type_codes[0]  # ADT or adult
            elif pax_type_hint in ("child", "chd") and len(type_codes) > 1:
                result[type_field] = type_codes[1]
            elif pax_type_hint in ("infant", "inf") and len(type_codes) > 2:
                result[type_field] = type_codes[2]
            else:
                result[type_field] = type_codes[0]

        # --- Contact info (primary passenger only) ---
        if is_primary:
            contact_fields = fmt.get("contact_fields")
            if contact_fields and len(contact_fields) >= 2:
                result[contact_fields[0]] = pax.get("email", "")
                result[contact_fields[1]] = pax.get("phone", "")
            else:
                result["email"] = pax.get("email", "")
                result["phone"] = pax.get("phone", "")

        # --- Passport / nationality (pass through if present) ---
        passport = pax.get("passport_number", "")
        if passport:
            result["passportNumber"] = passport
        passport_expiry = pax.get("passport_expiry", "")
        if passport_expiry:
            result["passportExpiry"] = passport_expiry
        nationality = pax.get("nationality", "")
        if nationality:
            result["nationality"] = nationality

        # --- Reference field (AirGateway uses travelerReference) ---
        ref_field = fmt.get("reference_field")
        if ref_field:
            result[ref_field] = pax.get("traveler_reference", f"T{1}")

        return result

    def _convert_date(self, date_str: str, target_format: str) -> str:
        """
        Convert date from MYSTES standard (YYYY-MM-DD) to provider format.

        Handles: YYYY-MM-DD, DD/MM/YYYY, MM/DD/YYYY
        """
        if not date_str:
            return ""

        # Parse input — MYSTES always sends YYYY-MM-DD from HTML date inputs
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            # Try other common formats as fallback
            for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%Y%m%d"):
                try:
                    dt = datetime.strptime(date_str, fmt)
                    break
                except ValueError:
                    continue
            else:
                logger.warning(f"Cannot parse date: {date_str}")
                return date_str  # Return as-is if unparseable

        # Format to target
        format_map = {
            "YYYY-MM-DD": "%Y-%m-%d",
            "DD/MM/YYYY": "%d/%m/%Y",
            "MM/DD/YYYY": "%m/%d/%Y",
            "YYYYMMDD": "%Y%m%d",
        }

        py_format = format_map.get(target_format, "%Y-%m-%d")
        return dt.strftime(py_format)
