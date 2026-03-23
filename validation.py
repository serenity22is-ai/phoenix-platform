"""
MYSTES Passenger Data Validation — Build #189

Server-side validation for passenger details submitted during booking.
Supports all verticals: flights, hotels, cars, activities.

Usage:
    from validation import validate_passenger_data
    valid, errors = validate_passenger_data(data, deal_type="flight")

MYSTES KYRIOS LLC — Confidential.
"""

import re
from datetime import datetime, date


# --- Regex patterns ---

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_DIGITS_RE = re.compile(r"\d")
PASSPORT_RE = re.compile(r"^[A-Za-z0-9]{5,20}$")
NAME_DIGITS_RE = re.compile(r"\d")
VALID_GENDERS = {"M", "F", "X"}

# Date formats to try when parsing user-submitted dates
DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d"]


def _parse_date(value):
    """Try multiple date formats. Return date object or None."""
    if not value:
        return None
    if isinstance(value, (date, datetime)):
        return value if isinstance(value, date) else value.date()
    value = str(value).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _validate_name(value, field_label):
    """Validate a name field. Returns list of error strings."""
    errors = []
    if not value or not value.strip():
        errors.append(f"{field_label} is required.")
        return errors
    name = value.strip()
    if len(name) > 100:
        errors.append(f"{field_label} must be 100 characters or fewer.")
    if NAME_DIGITS_RE.search(name):
        errors.append(f"{field_label} must not contain digits.")
    return errors


def _validate_email(value):
    """Validate email format. Returns list of error strings."""
    if not value or not value.strip():
        return ["Email is required."]
    if not EMAIL_RE.match(value.strip()):
        return ["Please enter a valid email address."]
    return []


def _validate_phone(value):
    """Validate phone number (7-15 digits). Returns list of error strings."""
    if not value or not value.strip():
        return ["Phone number is required."]
    digits = PHONE_DIGITS_RE.findall(value)
    if len(digits) < 7:
        return ["Phone number must have at least 7 digits."]
    if len(digits) > 15:
        return ["Phone number must have 15 digits or fewer."]
    return []


def _validate_dob(value):
    """Validate date of birth (must be in past). Returns list of error strings."""
    if not value:
        return ["Date of birth is required."]
    parsed = _parse_date(value)
    if parsed is None:
        return ["Date of birth must be a valid date (YYYY-MM-DD)."]
    if parsed >= date.today():
        return ["Date of birth must be in the past."]
    return []


def _validate_gender(value):
    """Validate gender (M/F/X). Returns list of error strings."""
    if not value or not value.strip():
        return ["Gender is required."]
    if value.strip().upper() not in VALID_GENDERS:
        return ["Gender must be M, F, or X."]
    return []


def _validate_passport_number(value):
    """Validate passport number if provided. Returns list of error strings."""
    if not value or not value.strip():
        return []  # Optional field
    if not PASSPORT_RE.match(value.strip()):
        return ["Passport number must be 5-20 alphanumeric characters."]
    return []


def _validate_passport_expiry(value):
    """Validate passport expiry if provided (must be 6+ months in future). Returns list of error strings."""
    if not value or not str(value).strip():
        return []  # Optional field
    parsed = _parse_date(value)
    if parsed is None:
        return ["Passport expiry must be a valid date (YYYY-MM-DD)."]
    today = date.today()
    if parsed <= today:
        return ["Passport has expired."]
    # 6-month minimum for international travel
    months_ahead = (parsed.year - today.year) * 12 + (parsed.month - today.month)
    if months_ahead < 6:
        return ["Passport must be valid for at least 6 months from today."]
    return []


def validate_passenger_data(data, deal_type="flight"):
    """
    Validate passenger data based on deal type.

    Args:
        data: dict with passenger fields (first_name, last_name, email, etc.)
        deal_type: one of 'flight', 'hotel', 'activity', 'car_rental'

    Returns:
        (valid: bool, errors: list[str])
    """
    if not data or not isinstance(data, dict):
        return False, ["No passenger data provided."]

    errors = []

    # --- Common to all verticals ---
    errors.extend(_validate_name(data.get("first_name"), "First name"))
    errors.extend(_validate_name(data.get("last_name"), "Last name"))
    errors.extend(_validate_email(data.get("email")))

    if deal_type == "hotel":
        # Hotels: name + email required, phone optional but validated if present
        phone = data.get("phone")
        if phone and phone.strip():
            errors.extend(_validate_phone(phone))
        return (len(errors) == 0, errors)

    # Activities, cars, flights all require phone
    errors.extend(_validate_phone(data.get("phone")))

    if deal_type in ("activity", "car_rental"):
        return (len(errors) == 0, errors)

    # --- Flight-specific ---
    errors.extend(_validate_dob(data.get("date_of_birth")))
    errors.extend(_validate_gender(data.get("gender")))
    errors.extend(_validate_passport_number(data.get("passport_number")))
    errors.extend(_validate_passport_expiry(data.get("passport_expiry")))

    return (len(errors) == 0, errors)
