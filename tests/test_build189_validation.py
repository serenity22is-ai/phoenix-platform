"""
MYSTES Build #189 — Passenger Validation Tests

Tests:
    - Flight passenger validation (email, DOB, passport, phone, gender)
    - Hotel passenger validation (simpler rules)
    - Car rental passenger validation
    - Edge cases (future DOB, expired passport, short phone)

Run: pytest tests/test_build189_validation.py -v
MYSTES KYRIOS LLC — Confidential.
"""

import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from validation import validate_passenger_data


# ============================================================
# Flight Passenger Validation
# ============================================================

class TestFlightPassengerValidation:
    """Test flight passenger data validation."""

    def test_valid_flight_passenger(self):
        """Complete valid flight passenger data passes."""
        data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john@example.com",
            "phone": "+1-555-123-4567",
            "date_of_birth": "1990-05-15",
            "gender": "M",
        }
        valid, errors = validate_passenger_data(data, deal_type="flight")
        assert valid is True
        assert errors == []

    def test_missing_first_name(self):
        """Missing first name is caught."""
        data = {
            "first_name": "",
            "last_name": "Doe",
            "email": "john@example.com",
            "phone": "5551234567",
            "date_of_birth": "1990-05-15",
            "gender": "M",
        }
        valid, errors = validate_passenger_data(data, deal_type="flight")
        assert valid is False
        assert any("First name" in e for e in errors)

    def test_invalid_email(self):
        """Invalid email format is rejected."""
        data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": "not-an-email",
            "phone": "5551234567",
            "date_of_birth": "1990-05-15",
            "gender": "M",
        }
        valid, errors = validate_passenger_data(data, deal_type="flight")
        assert valid is False
        assert any("email" in e.lower() for e in errors)

    def test_future_dob_rejected(self):
        """Date of birth in the future is rejected."""
        future = (date.today() + timedelta(days=30)).isoformat()
        data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john@example.com",
            "phone": "5551234567",
            "date_of_birth": future,
            "gender": "M",
        }
        valid, errors = validate_passenger_data(data, deal_type="flight")
        assert valid is False
        assert any("past" in e.lower() for e in errors)

    def test_invalid_dob_format(self):
        """Unparseable DOB is rejected."""
        data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john@example.com",
            "phone": "5551234567",
            "date_of_birth": "not-a-date",
            "gender": "M",
        }
        valid, errors = validate_passenger_data(data, deal_type="flight")
        assert valid is False
        assert any("date" in e.lower() for e in errors)

    def test_invalid_gender(self):
        """Invalid gender value is rejected."""
        data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john@example.com",
            "phone": "5551234567",
            "date_of_birth": "1990-05-15",
            "gender": "Z",
        }
        valid, errors = validate_passenger_data(data, deal_type="flight")
        assert valid is False
        assert any("Gender" in e for e in errors)

    def test_short_phone_rejected(self):
        """Phone with too few digits is rejected."""
        data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john@example.com",
            "phone": "12345",
            "date_of_birth": "1990-05-15",
            "gender": "M",
        }
        valid, errors = validate_passenger_data(data, deal_type="flight")
        assert valid is False
        assert any("7 digits" in e for e in errors)

    def test_expired_passport_rejected(self):
        """Passport with past expiry is rejected."""
        past = (date.today() - timedelta(days=30)).isoformat()
        data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john@example.com",
            "phone": "5551234567",
            "date_of_birth": "1990-05-15",
            "gender": "M",
            "passport_number": "AB1234567",
            "passport_expiry": past,
        }
        valid, errors = validate_passenger_data(data, deal_type="flight")
        assert valid is False
        assert any("expired" in e.lower() for e in errors)

    def test_passport_expiry_less_than_6_months(self):
        """Passport expiring in less than 6 months is rejected."""
        soon = (date.today() + timedelta(days=90)).isoformat()
        data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john@example.com",
            "phone": "5551234567",
            "date_of_birth": "1990-05-15",
            "gender": "M",
            "passport_number": "AB1234567",
            "passport_expiry": soon,
        }
        valid, errors = validate_passenger_data(data, deal_type="flight")
        assert valid is False
        assert any("6 months" in e for e in errors)

    def test_valid_passport_passes(self):
        """Valid passport number and expiry passes."""
        future = (date.today() + timedelta(days=365)).isoformat()
        data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john@example.com",
            "phone": "5551234567",
            "date_of_birth": "1990-05-15",
            "gender": "F",
            "passport_number": "AB1234567",
            "passport_expiry": future,
        }
        valid, errors = validate_passenger_data(data, deal_type="flight")
        assert valid is True

    def test_name_with_digits_rejected(self):
        """Name containing digits is rejected."""
        data = {
            "first_name": "John123",
            "last_name": "Doe",
            "email": "john@example.com",
            "phone": "5551234567",
            "date_of_birth": "1990-05-15",
            "gender": "M",
        }
        valid, errors = validate_passenger_data(data, deal_type="flight")
        assert valid is False
        assert any("digits" in e.lower() for e in errors)

    def test_no_data_provided(self):
        """None or empty dict is rejected."""
        valid, errors = validate_passenger_data(None, deal_type="flight")
        assert valid is False
        valid2, errors2 = validate_passenger_data({}, deal_type="flight")
        assert valid2 is False


# ============================================================
# Hotel Passenger Validation
# ============================================================

class TestHotelPassengerValidation:
    """Test hotel guest validation (simpler rules)."""

    def test_valid_hotel_guest(self):
        """Valid hotel guest data passes."""
        data = {
            "first_name": "Jane",
            "last_name": "Smith",
            "email": "jane@hotel.com",
        }
        valid, errors = validate_passenger_data(data, deal_type="hotel")
        assert valid is True

    def test_hotel_phone_optional(self):
        """Phone is optional for hotels but validated if present."""
        data = {
            "first_name": "Jane",
            "last_name": "Smith",
            "email": "jane@hotel.com",
            "phone": "12",  # Too short
        }
        valid, errors = validate_passenger_data(data, deal_type="hotel")
        assert valid is False
        assert any("7 digits" in e for e in errors)

    def test_hotel_no_dob_required(self):
        """Hotels don't require DOB or gender."""
        data = {
            "first_name": "Jane",
            "last_name": "Smith",
            "email": "jane@hotel.com",
        }
        valid, errors = validate_passenger_data(data, deal_type="hotel")
        assert valid is True
        assert errors == []


# ============================================================
# Car Rental Passenger Validation
# ============================================================

class TestCarPassengerValidation:
    """Test car rental driver validation."""

    def test_valid_car_driver(self):
        """Valid car rental driver passes."""
        data = {
            "first_name": "Bob",
            "last_name": "Driver",
            "email": "bob@cars.com",
            "phone": "5559876543",
        }
        valid, errors = validate_passenger_data(data, deal_type="car_rental")
        assert valid is True

    def test_car_requires_phone(self):
        """Car rental requires phone."""
        data = {
            "first_name": "Bob",
            "last_name": "Driver",
            "email": "bob@cars.com",
        }
        valid, errors = validate_passenger_data(data, deal_type="car_rental")
        assert valid is False
        assert any("phone" in e.lower() for e in errors)
