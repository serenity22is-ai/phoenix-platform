"""
MYSTES Database Models

Tables:
- User: User accounts with authentication
- Deal: Cached flight deals
- Payment: XRP payment records
- Booking: User booking history
"""

import json
from datetime import datetime, timedelta, date, timezone


def _utcnow():
    """Timezone-aware UTC now — replaces deprecated datetime.now(timezone.utc)."""
    return datetime.now(timezone.utc)
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
import bcrypt

db = SQLAlchemy()


class User(UserMixin, db.Model):
    """User account model."""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=True)  # Nullable for OAuth users

    # OAuth provider IDs (Build #82 Google, Build #83 Apple/Microsoft)
    google_id = db.Column(db.String(255), unique=True, nullable=True, index=True)
    apple_id = db.Column(db.String(255), unique=True, nullable=True, index=True)
    microsoft_id = db.Column(db.String(255), unique=True, nullable=True, index=True)

    # Profile
    name = db.Column(db.String(100))
    preferred_currency = db.Column(db.String(3), default='USD')
    home_market = db.Column(db.String(2), default='US')
    preferred_language = db.Column(db.String(5), default='en')  # ISO 639-1 code (e.g., 'en', 'es', 'zh')

    # XRP wallet (optional - for refunds)
    xrp_wallet_address = db.Column(db.String(100))

    # Status
    is_active = db.Column(db.Boolean, default=True)
    is_verified = db.Column(db.Boolean, default=False)
    is_admin = db.Column(db.Boolean, default=False)

    # Email verification
    verification_token = db.Column(db.String(100), unique=True)
    verification_token_expires = db.Column(db.DateTime)

    # Password reset
    reset_token = db.Column(db.String(100), unique=True)
    reset_token_expires = db.Column(db.DateTime)

    # Commercial referral attribution
    referred_by_account_id = db.Column(db.Integer, db.ForeignKey('commercial_accounts.id'))
    referral_code_used = db.Column(db.String(20))  # The referral code that brought them in

    # Seller onboarding attribution (which deal link brought them to Mystes)
    onboarded_from_deal_id = db.Column(db.Integer, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=_utcnow)
    last_login = db.Column(db.DateTime)

    # MYSTES AI tier (Build #72)
    ai_tier = db.Column(db.String(30), default='ai_free')
    ai_queries_used_this_month = db.Column(db.Integer, default=0)
    ai_month_reset_date = db.Column(db.DateTime, nullable=True)
    last_comparison_date = db.Column(db.Date, nullable=True)  # Build #73: daily comparison quota

    # Consumer referral code (Build #170 — every user gets one)
    referral_code = db.Column(db.String(20), unique=True, nullable=True, index=True)
    referred_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    total_referrals = db.Column(db.Integer, default=0)

    # Stripe Customer (for saved payment methods — Phase 1)
    stripe_customer_id = db.Column(db.String(100), unique=True, nullable=True, index=True)

    # KYC (Build #75)
    kyc_status = db.Column(db.String(20), default='none')  # none/pending/verified/rejected
    kyc_verified_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    payments = db.relationship('Payment', backref='user', lazy='dynamic')
    bookings = db.relationship('Booking', backref='user', lazy='dynamic')
    referred_by = db.relationship('CommercialAccount', foreign_keys=[referred_by_account_id], backref='referred_users')

    def set_password(self, password):
        """Hash and set password."""
        self.password_hash = bcrypt.hashpw(
            password.encode('utf-8'),
            bcrypt.gensalt()
        ).decode('utf-8')

    def check_password(self, password):
        """Verify password."""
        if not self.password_hash:
            return False  # OAuth-only users have no password
        return bcrypt.checkpw(
            password.encode('utf-8'),
            self.password_hash.encode('utf-8')
        )

    def generate_verification_token(self):
        """Generate email verification token."""
        import secrets
        self.verification_token = secrets.token_urlsafe(32)
        self.verification_token_expires = datetime.now(timezone.utc) + timedelta(hours=24)
        return self.verification_token

    def verify_email(self, token):
        """Verify email with token."""
        if (self.verification_token == token and
            self.verification_token_expires and
            self.verification_token_expires > datetime.now(timezone.utc)):
            self.is_verified = True
            self.verification_token = None
            self.verification_token_expires = None
            return True
        return False

    def generate_reset_token(self):
        """Generate password reset token."""
        import secrets
        self.reset_token = secrets.token_urlsafe(32)
        self.reset_token_expires = datetime.now(timezone.utc) + timedelta(hours=1)
        return self.reset_token

    def reset_password(self, token, new_password):
        """Reset password with token."""
        if (self.reset_token == token and
            self.reset_token_expires and
            self.reset_token_expires > datetime.now(timezone.utc)):
            self.set_password(new_password)
            self.reset_token = None
            self.reset_token_expires = None
            return True
        return False

    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'name': self.name,
            'preferred_currency': self.preferred_currency,
            'home_market': self.home_market,
            'preferred_language': self.preferred_language,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class Deal(db.Model):
    """Cached deal model — supports flights and hotels."""
    __tablename__ = 'deals'

    id = db.Column(db.Integer, primary_key=True)
    deal_id = db.Column(db.String(20), unique=True, nullable=False, index=True)

    # Deal type discriminator
    deal_type = db.Column(db.String(20), default='flight', index=True)  # 'flight' or 'hotel'

    # Flight info (populated for flight deals)
    airline = db.Column(db.String(50))
    flight_number = db.Column(db.String(20))
    origin = db.Column(db.String(10), index=True)
    destination = db.Column(db.String(10), index=True)
    departure_date = db.Column(db.Date, index=True)
    departure_time = db.Column(db.String(10))
    arrival_time = db.Column(db.String(10))
    stops = db.Column(db.Integer, default=0)

    # Pricing
    home_market = db.Column(db.String(2))  # e.g., "US"
    home_price_usd = db.Column(db.Float)
    arbitrage_market = db.Column(db.String(2))  # e.g., "JP"
    arbitrage_price_usd = db.Column(db.Float)
    arbitrage_price_local = db.Column(db.Float)  # Price in local currency
    arbitrage_currency = db.Column(db.String(3))  # e.g., "JPY"

    # Savings
    gross_savings_usd = db.Column(db.Float)
    platform_fee_usd = db.Column(db.Float)
    platform_fee_xrp = db.Column(db.Float)
    user_savings_usd = db.Column(db.Float)
    savings_percent = db.Column(db.Float)

    # Payment details
    destination_tag = db.Column(db.Integer, index=True)

    # Booking URL
    booking_url = db.Column(db.String(500))

    # Multi-leg support
    is_multi_leg = db.Column(db.Boolean, default=False)
    flight_legs = db.Column(db.Text)  # JSON array of flight legs
    total_legs = db.Column(db.Integer, default=1)

    # Status
    is_active = db.Column(db.Boolean, default=True)
    deal_status = db.Column(db.String(20), default='available', index=True)
    # available → claimed → booked → expired → cancelled
    claimed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    claimed_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime)

    # Timestamps
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    # Amadeus booking data (raw offer JSON for price_confirm + create_booking)
    amadeus_offer_data = db.Column(db.Text, nullable=True)

    # Payment compatibility (Build #85)
    payment_compatibility = db.Column(db.Text, nullable=True)  # JSON: accepted payment types for deal market

    # Hotel-specific fields (nullable — only populated for hotel deals)
    hotel_name = db.Column(db.String(300), nullable=True)
    hotel_id = db.Column(db.String(50), nullable=True)
    hotel_offer_id = db.Column(db.String(100), nullable=True)
    hotel_prebook_id = db.Column(db.String(200), nullable=True)  # liteAPI prebookId
    city_code = db.Column(db.String(10), nullable=True, index=True)
    city_name = db.Column(db.String(100), nullable=True)
    check_in_date = db.Column(db.Date, nullable=True, index=True)
    check_out_date = db.Column(db.Date, nullable=True)
    nights = db.Column(db.Integer, nullable=True)
    rooms = db.Column(db.Integer, nullable=True)
    adults = db.Column(db.Integer, nullable=True)
    room_type = db.Column(db.String(50), nullable=True)
    bed_type = db.Column(db.String(50), nullable=True)
    star_rating = db.Column(db.Integer, nullable=True)
    price_per_night_usd = db.Column(db.Float, nullable=True)
    price_total_usd = db.Column(db.Float, nullable=True)
    amenities = db.Column(db.Text, nullable=True)  # JSON
    cancellation_policy = db.Column(db.Text, nullable=True)
    room_description = db.Column(db.Text, nullable=True)

    # Picasso / Redbox API references (critical for booking flow)
    fare_id = db.Column(db.String(100), nullable=True)  # Redbox fareId from search
    fare_search_id = db.Column(db.String(100), nullable=True)  # Redbox fareSearchId
    picasso_gds = db.Column(db.String(20), nullable=True)  # GDS: AMADEUS, AER_DC, SABRE
    fare_type = db.Column(db.String(10), nullable=True)  # PUB/NET/NEG

    # Flight detail fields (from Picasso)
    cabin_class = db.Column(db.String(20), nullable=True)  # ECONOMY/BUSINESS/FIRST
    fare_family = db.Column(db.String(100), nullable=True)  # "Basic Economy", "Main Cabin"
    baggage_info = db.Column(db.String(50), nullable=True)  # "0PC", "1x23kg"
    seat_selection_available = db.Column(db.Boolean, nullable=True)
    flight_cancellation_policy = db.Column(db.String(20), nullable=True)  # POSSIBLE/NOT_POSSIBLE/UNKNOWN
    flight_rebooking_policy = db.Column(db.String(20), nullable=True)
    ticket_deadline = db.Column(db.String(30), nullable=True)  # ISO timestamp
    duration = db.Column(db.String(20), nullable=True)  # "5h 30m"
    segments_json = db.Column(db.Text, nullable=True)  # JSON of segment details
    layovers = db.Column(db.String(200), nullable=True)  # comma-separated airport codes

    # Relationships
    payments = db.relationship('Payment', backref='deal', lazy='dynamic')
    bookings = db.relationship('Booking', backref='deal', lazy='dynamic')

    def get_flight_legs(self):
        """Get flight legs as a Python list."""
        if self.flight_legs:
            import json
            try:
                return json.loads(self.flight_legs)
            except:
                return []
        return []

    def get_segments(self):
        """Get flight segments as a Python list."""
        if self.segments_json:
            import json
            try:
                return json.loads(self.segments_json)
            except:
                return []
        return []

    def to_dict(self):
        result = {
            'deal_id': self.deal_id,
            'deal_type': self.deal_type or 'flight',
            'airline': self.airline,
            'flight_number': self.flight_number,
            'origin': self.origin,
            'destination': self.destination,
            'route': f"{self.origin} → {self.destination}",
            'departure_date': self.departure_date.isoformat() if self.departure_date else None,
            'departure_time': self.departure_time,
            'arrival_time': self.arrival_time,
            'home_market': self.home_market,
            'home_price_usd': self.home_price_usd,
            'arbitrage_market': 'MYSTES',  # B2C safe — real POS stays in DB only
            'arbitrage_price_usd': self.arbitrage_price_usd,
            'gross_savings_usd': self.gross_savings_usd,
            'platform_fee_usd': self.platform_fee_usd,
            'platform_fee_xrp': self.platform_fee_xrp,
            'user_savings_usd': self.user_savings_usd,
            'savings_percent': self.savings_percent,
            'destination_tag': self.destination_tag,
            'booking_url': self.booking_url,
            'is_active': self.is_active,
            'deal_status': self.deal_status or 'available',
            'is_multi_leg': self.is_multi_leg,
            'total_legs': self.total_legs,
            'fare_id': self.fare_id,
            'fare_search_id': self.fare_search_id,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
        }
        if self.is_multi_leg:
            result['flight_legs'] = self.get_flight_legs()
        if self.deal_type != 'hotel':
            result.update({
                'cabin_class': self.cabin_class,
                'fare_family': self.fare_family,
                'baggage_info': self.baggage_info,
                'seat_selection_available': self.seat_selection_available,
                'flight_cancellation_policy': self.flight_cancellation_policy,
                'flight_rebooking_policy': self.flight_rebooking_policy,
                'ticket_deadline': self.ticket_deadline,
                'duration': self.duration,
                'layovers': self.layovers,
            })
        if self.deal_type == 'hotel':
            result.update({
                'hotel_name': self.hotel_name,
                'hotel_id': self.hotel_id,
                'city_code': self.city_code,
                'city_name': self.city_name,
                'check_in_date': self.check_in_date.isoformat() if self.check_in_date else None,
                'check_out_date': self.check_out_date.isoformat() if self.check_out_date else None,
                'nights': self.nights,
                'rooms': self.rooms,
                'adults': self.adults,
                'room_type': self.room_type,
                'bed_type': self.bed_type,
                'star_rating': self.star_rating,
                'price_per_night_usd': self.price_per_night_usd,
                'price_total_usd': self.price_total_usd,
                'cancellation_policy': self.cancellation_policy,
                'room_description': self.room_description,
            })
        return result


class Payment(db.Model):
    """Multi-method payment record model."""
    __tablename__ = 'payments'

    id = db.Column(db.Integer, primary_key=True)

    # References
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    deal_id = db.Column(db.Integer, db.ForeignKey('deals.id'), index=True)

    # Payment method: card, xrp, rlusd, crypto
    payment_method = db.Column(db.String(20), default='xrp', index=True)

    # Amount in USD
    amount_usd = db.Column(db.Float)

    # XRP/RLUSD specific fields
    destination_tag = db.Column(db.Integer, index=True)
    expected_xrp = db.Column(db.Float)
    received_xrp = db.Column(db.Float)
    xrp_usd_rate = db.Column(db.Float)  # Rate at time of payment

    # Transaction reference (tx_hash for crypto, session_id for Stripe, charge_code for Coinbase)
    tx_hash = db.Column(db.String(100), unique=True)
    sender_address = db.Column(db.String(100))

    # Stripe specific
    stripe_session_id = db.Column(db.String(100))
    stripe_payment_intent = db.Column(db.String(100))

    # Coinbase specific
    coinbase_charge_code = db.Column(db.String(50))
    coinbase_charge_id = db.Column(db.String(100))
    crypto_currency = db.Column(db.String(10))  # BTC, ETH, etc.
    crypto_amount = db.Column(db.String(50))  # Amount in crypto

    # Status
    status = db.Column(db.String(20), default='pending', index=True)
    # pending, processing, verified, fulfillment_triggered, expired, refunded, failed

    # Timestamps
    created_at = db.Column(db.DateTime, default=_utcnow)
    verified_at = db.Column(db.DateTime)
    expires_at = db.Column(db.DateTime)

    def to_dict(self):
        return {
            'id': self.id,
            'deal_id': self.deal_id,
            'payment_method': self.payment_method,
            'amount_usd': self.amount_usd,
            'destination_tag': self.destination_tag,
            'expected_xrp': self.expected_xrp,
            'received_xrp': self.received_xrp,
            'tx_hash': self.tx_hash,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'verified_at': self.verified_at.isoformat() if self.verified_at else None,
        }


class Booking(db.Model):
    """User booking history model with vendor fulfillment tracking."""
    __tablename__ = 'bookings'
    __table_args__ = (
        db.UniqueConstraint('deal_id', 'payment_id', name='uq_booking_deal_payment'),
    )

    id = db.Column(db.Integer, primary_key=True)

    # References
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    deal_id = db.Column(db.Integer, db.ForeignKey('deals.id'), index=True)
    payment_id = db.Column(db.Integer, db.ForeignKey('payments.id'))

    # Booking details
    passenger_name = db.Column(db.String(100))
    passenger_email = db.Column(db.String(255))
    confirmation_code = db.Column(db.String(50))  # Airline confirmation

    # Status
    status = db.Column(db.String(30), default='pending', index=True)
    # pending, pending_fulfillment, processing, booked, cancelled, completed, failed

    # Vendor payment tracking (for automated bookings)
    vendor_payment_status = db.Column(db.String(20), default='pending')
    # pending, processing, completed, failed
    vendor_payment_amount = db.Column(db.Float)  # Amount paid to airline
    vendor_payment_currency = db.Column(db.String(3), default='USD')
    vendor_payment_reference = db.Column(db.String(100))  # Payment reference
    vendor_payment_method = db.Column(db.String(50))  # card_on_file, virtual_card, etc.

    # Booking fulfillment
    fulfillment_type = db.Column(db.String(20), default='self_service')
    # self_service (user books via proxy), automated, manual_agent
    fulfillment_notes = db.Column(db.Text)

    # E-ticket delivery
    eticket_url = db.Column(db.String(500))
    eticket_sent = db.Column(db.Boolean, default=False)
    eticket_sent_at = db.Column(db.DateTime)

    # Picasso / Redbox booking references
    picasso_super_pnr_id = db.Column(db.String(100), nullable=True)
    picasso_cart_id = db.Column(db.String(100), nullable=True)
    pnr_locator = db.Column(db.String(20), nullable=True)  # Airline PNR from Redbox
    eticket_number = db.Column(db.String(20), nullable=True)

    # Passenger details (for automated Picasso booking)
    passenger_first_name = db.Column(db.String(100), nullable=True)
    passenger_last_name = db.Column(db.String(100), nullable=True)
    passenger_date_of_birth = db.Column(db.Date, nullable=True)
    passenger_gender = db.Column(db.String(10), nullable=True)  # MALE/FEMALE
    passenger_phone = db.Column(db.String(30), nullable=True)
    passenger_passport_number = db.Column(db.String(30), nullable=True)
    passenger_passport_expiry = db.Column(db.Date, nullable=True)
    passenger_nationality = db.Column(db.String(3), nullable=True)  # ISO country code
    passenger_title = db.Column(db.String(10), nullable=True)  # MR/MS/MRS

    # Additional passengers (JSON array for multi-pax bookings)
    additional_passengers_json = db.Column(db.Text, nullable=True)

    # Insurance (Build #174)
    insurance_policy_id = db.Column(db.String(100), nullable=True)
    insurance_plan_name = db.Column(db.String(100), nullable=True)
    insurance_amount_usd = db.Column(db.Float, nullable=True)

    # Hotel-specific booking fields
    guest_title = db.Column(db.String(10), nullable=True)  # MR/MS/MRS
    check_in_date = db.Column(db.Date, nullable=True)
    check_out_date = db.Column(db.Date, nullable=True)
    special_requests = db.Column(db.Text, nullable=True)
    hotel_confirmation_id = db.Column(db.String(100), nullable=True)
    provider_reference = db.Column(db.String(100), nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)
    booked_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)

    # Relationship
    payment = db.relationship('Payment', backref='booking', uselist=False)

    def get_additional_passengers(self):
        """Get additional passengers as a Python list."""
        if self.additional_passengers_json:
            import json
            try:
                return json.loads(self.additional_passengers_json)
            except Exception:
                return []
        return []

    def get_all_passengers(self):
        """Get all passengers (primary + additional) as a list of dicts."""
        passengers = []
        if self.passenger_first_name:
            passengers.append({
                "firstName": self.passenger_first_name,
                "lastName": self.passenger_last_name or "",
                "paxType": "ADT",
                "dateOfBirth": self.passenger_date_of_birth.isoformat() if self.passenger_date_of_birth else None,
                "gender": self.passenger_gender,
                "email": self.passenger_email,
                "phone": self.passenger_phone,
                "title": self.passenger_title,
                "passportNumber": self.passenger_passport_number,
                "passportExpiry": self.passenger_passport_expiry.isoformat() if self.passenger_passport_expiry else None,
                "nationality": self.passenger_nationality,
            })
        passengers.extend(self.get_additional_passengers())
        return passengers

    def to_dict(self):
        result = {
            'id': self.id,
            'deal_id': self.deal_id,
            'passenger_name': self.passenger_name,
            'passenger_first_name': self.passenger_first_name,
            'passenger_last_name': self.passenger_last_name,
            'confirmation_code': self.confirmation_code,
            'pnr_locator': self.pnr_locator,
            'eticket_number': self.eticket_number,
            'status': self.status,
            'vendor_payment_status': self.vendor_payment_status,
            'fulfillment_type': self.fulfillment_type,
            'eticket_url': self.eticket_url,
            'picasso_super_pnr_id': self.picasso_super_pnr_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'booked_at': self.booked_at.isoformat() if self.booked_at else None,
        }
        return result


class PriceAlert(db.Model):
    """Price alert subscription model."""
    __tablename__ = 'price_alerts'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)

    # Route
    origin = db.Column(db.String(10), index=True)
    destination = db.Column(db.String(10), index=True)

    # Alert criteria
    max_price_usd = db.Column(db.Float)  # Alert if price below this
    min_savings_percent = db.Column(db.Float, default=10.0)  # Alert if savings above this

    # Date range (optional)
    date_from = db.Column(db.Date)
    date_to = db.Column(db.Date)

    # Notification preferences
    notify_email = db.Column(db.Boolean, default=True)

    # Status
    is_active = db.Column(db.Boolean, default=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=_utcnow)
    last_triggered = db.Column(db.DateTime)

    # Relationship
    user = db.relationship('User', backref='price_alerts')

    def to_dict(self):
        return {
            'id': self.id,
            'route': f"{self.origin} → {self.destination}",
            'max_price_usd': self.max_price_usd,
            'min_savings_percent': self.min_savings_percent,
            'is_active': self.is_active,
        }


class Escrow(db.Model):
    """
    XRPL Escrow payment model for trustless bookings.

    Flow:
    1. Customer creates escrow with crypto-condition
    2. MYSTES books the flight
    3. On success: Release escrow with fulfillment
    4. On failure: Cancel escrow after timeout
    """
    __tablename__ = 'escrows'

    id = db.Column(db.Integer, primary_key=True)
    escrow_id = db.Column(db.String(50), unique=True, nullable=False, index=True)

    # References
    booking_id = db.Column(db.Integer, db.ForeignKey('bookings.id'), index=True)
    deal_id = db.Column(db.String(20), index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)

    # XRPL details
    sender_address = db.Column(db.String(100), nullable=False)  # Customer wallet
    destination_address = db.Column(db.String(100), nullable=False)  # Platform wallet
    amount_xrp = db.Column(db.Float, nullable=False)
    amount_drops = db.Column(db.String(20))

    # Escrow transaction details
    sequence = db.Column(db.Integer)  # EscrowCreate sequence number
    condition = db.Column(db.String(200))  # Crypto-condition (public)
    fulfillment = db.Column(db.String(200))  # Fulfillment (secret until release)

    # Transaction hashes
    create_tx_hash = db.Column(db.String(100))
    finish_tx_hash = db.Column(db.String(100))
    cancel_tx_hash = db.Column(db.String(100))

    # Timing
    cancel_after = db.Column(db.DateTime)  # When escrow can be cancelled
    finish_after = db.Column(db.DateTime)  # Earliest release time (optional)

    # Status: pending, released, cancelled, expired
    status = db.Column(db.String(20), default='pending', index=True)

    # Booking result
    confirmation_code = db.Column(db.String(50))  # Airline confirmation if released
    failure_reason = db.Column(db.Text)  # Reason if cancelled

    # Timestamps
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)
    released_at = db.Column(db.DateTime)
    cancelled_at = db.Column(db.DateTime)

    # Relationships
    booking = db.relationship('Booking', backref='escrow', uselist=False)
    user = db.relationship('User', backref='escrows')

    def to_dict(self):
        return {
            'id': self.id,
            'escrow_id': self.escrow_id,
            'booking_id': self.booking_id,
            'sender_address': self.sender_address,
            'amount_xrp': self.amount_xrp,
            'status': self.status,
            'condition': self.condition,
            'cancel_after': self.cancel_after.isoformat() if self.cancel_after else None,
            'create_tx_hash': self.create_tx_hash,
            'finish_tx_hash': self.finish_tx_hash,
            'cancel_tx_hash': self.cancel_tx_hash,
            'confirmation_code': self.confirmation_code,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
class UserWallet(db.Model):
    """
    XRPL wallet linked to a user profile.
    Users can have multiple wallets but one primary.
    """
    __tablename__ = 'user_wallets'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    # Wallet details
    wallet_address = db.Column(db.String(100), nullable=False, index=True)
    wallet_label = db.Column(db.String(50), default='Primary')  # User-friendly label
    is_primary = db.Column(db.Boolean, default=True)

    # Verification
    is_verified = db.Column(db.Boolean, default=False)
    verification_tx_hash = db.Column(db.String(100))  # Micro-payment verification

    # Timestamps
    created_at = db.Column(db.DateTime, default=_utcnow)
    last_used = db.Column(db.DateTime)

    # Relationships
    user = db.relationship('User', backref=db.backref('wallets', lazy='dynamic'))

    def to_dict(self):
        return {
            'id': self.id,
            'wallet_address': self.wallet_address,
            'wallet_label': self.wallet_label,
            'is_primary': self.is_primary,
            'is_verified': self.is_verified,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class UserCard(db.Model):
    """
    Payment card linked to a user profile.
    Used by helpers to front ticket purchases.
    Card numbers are NOT stored — only last 4 digits and token reference.
    """
    __tablename__ = 'user_cards'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    # Card display info (no full card numbers stored)
    card_label = db.Column(db.String(50), default='Primary Card')
    card_last_four = db.Column(db.String(4))
    card_brand = db.Column(db.String(20))  # visa, mastercard, amex
    card_exp_month = db.Column(db.Integer)
    card_exp_year = db.Column(db.Integer)

    # Tokenized reference (from Stripe or payment processor)
    stripe_payment_method_id = db.Column(db.String(100))

    # Billing
    billing_name = db.Column(db.String(100))
    billing_country = db.Column(db.String(2))

    # Status
    is_active = db.Column(db.Boolean, default=True)
    is_primary = db.Column(db.Boolean, default=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=_utcnow)

    # Relationships
    user = db.relationship('User', backref=db.backref('cards', lazy='dynamic'))

    def to_dict(self):
        return {
            'id': self.id,
            'card_label': self.card_label,
            'card_last_four': self.card_last_four,
            'card_brand': self.card_brand,
            'card_exp_month': self.card_exp_month,
            'card_exp_year': self.card_exp_year,
            'billing_country': self.billing_country,
            'is_primary': self.is_primary,
            'is_active': self.is_active,
        }


class TravelerProfile(db.Model):
    """
    Saved traveler profiles for booking. (Build #98)

    Users can save multiple travelers (self, family, colleagues) with all
    data required for IATA/APIS compliance. This enables:
    - Multi-passenger bookings
    - Booking for someone else
    - Pre-filled checkout for returning users

    Fields align with Amadeus Flight Orders API and IATA APIS requirements.
    """
    __tablename__ = 'traveler_profiles'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    # Profile metadata
    label = db.Column(db.String(50), default='Primary Traveler')  # "Me", "Spouse", "Child 1"
    is_primary = db.Column(db.Boolean, default=False)  # Is this the account owner?
    is_active = db.Column(db.Boolean, default=True)

    # Required identity fields (IATA standard)
    title = db.Column(db.String(10))  # MR, MRS, MS, MISS, DR
    first_name = db.Column(db.String(100), nullable=False)
    middle_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100), nullable=False)
    date_of_birth = db.Column(db.Date, nullable=False)
    gender = db.Column(db.String(10), nullable=False)  # MALE, FEMALE

    # Passenger type
    passenger_type = db.Column(db.String(10), default='ADULT')  # ADULT, CHILD, INFANT

    # Contact info
    email = db.Column(db.String(255))
    phone = db.Column(db.String(30))  # With country code, e.g., +1-555-123-4567
    phone_country_code = db.Column(db.String(5), default='1')  # Just the code, e.g., "1" for US

    # Travel document (APIS - required for international)
    passport_number = db.Column(db.String(50))
    passport_expiry = db.Column(db.Date)
    passport_country = db.Column(db.String(2))  # ISO 2-letter, e.g., "US"
    nationality = db.Column(db.String(2))  # ISO 2-letter

    # US-specific (TSA requirements)
    redress_number = db.Column(db.String(20))  # DHS Redress Number
    known_traveler_number = db.Column(db.String(20))  # TSA PreCheck / Global Entry

    # Frequent flyer programs (JSON: {"AA": "123456", "UA": "789012"})
    frequent_flyer_numbers = db.Column(db.Text)  # JSON string

    # Preferences
    seat_preference = db.Column(db.String(20))  # WINDOW, AISLE, MIDDLE
    meal_preference = db.Column(db.String(30))  # VEGETARIAN, VEGAN, KOSHER, HALAL, etc.
    special_assistance = db.Column(db.String(100))  # WHEELCHAIR, OXYGEN, etc.

    # Emergency contact
    emergency_contact_name = db.Column(db.String(100))
    emergency_contact_phone = db.Column(db.String(30))
    emergency_contact_relation = db.Column(db.String(30))  # SPOUSE, PARENT, FRIEND

    # Timestamps
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    # Relationships
    user = db.relationship('User', backref=db.backref('travelers', lazy='dynamic'))

    def get_frequent_flyer(self, airline_code):
        """Get frequent flyer number for a specific airline."""
        import json
        if not self.frequent_flyer_numbers:
            return None
        try:
            ff = json.loads(self.frequent_flyer_numbers)
            return ff.get(airline_code.upper())
        except Exception:
            return None

    def set_frequent_flyer(self, airline_code, number):
        """Set frequent flyer number for a specific airline."""
        import json
        try:
            ff = json.loads(self.frequent_flyer_numbers or '{}')
        except Exception:
            ff = {}
        ff[airline_code.upper()] = number
        self.frequent_flyer_numbers = json.dumps(ff)

    def to_amadeus_traveler(self, traveler_id="1"):
        """Convert to Amadeus Flight Orders API traveler format."""
        traveler_obj = {
            "id": traveler_id,
            "dateOfBirth": self.date_of_birth.strftime("%Y-%m-%d") if self.date_of_birth else "1990-01-01",
            "name": {
                "firstName": (self.first_name or "").upper(),
                "lastName": (self.last_name or "").upper(),
            },
            "gender": (self.gender or "MALE").upper(),
            "contact": {
                "emailAddress": self.email or "",
                "phones": [{
                    "deviceType": "MOBILE",
                    "countryCallingCode": self.phone_country_code or "1",
                    "number": (self.phone or "").replace("+", "").replace("-", "").replace(" ", ""),
                }],
            },
        }

        # Add middle name if present
        if self.middle_name:
            traveler_obj["name"]["secondLastName"] = self.middle_name.upper()

        # Add passport/document for international flights
        if self.passport_number:
            traveler_obj["documents"] = [{
                "documentType": "PASSPORT",
                "number": self.passport_number,
                "expiryDate": self.passport_expiry.strftime("%Y-%m-%d") if self.passport_expiry else "2030-01-01",
                "issuanceCountry": self.passport_country or "US",
                "nationality": self.nationality or "US",
                "holder": True,
            }]

        # Add TSA numbers if present (for US flights)
        if self.redress_number or self.known_traveler_number:
            traveler_obj["loyaltyPrograms"] = []
            # Note: These are handled differently in real APIS, simplified here

        return traveler_obj

    def to_dict(self):
        return {
            'id': self.id,
            'label': self.label,
            'is_primary': self.is_primary,
            'title': self.title,
            'first_name': self.first_name,
            'middle_name': self.middle_name,
            'last_name': self.last_name,
            'full_name': f"{self.first_name} {self.last_name}",
            'date_of_birth': self.date_of_birth.isoformat() if self.date_of_birth else None,
            'gender': self.gender,
            'passenger_type': self.passenger_type,
            'email': self.email,
            'phone': self.phone,
            'has_passport': bool(self.passport_number),
            'passport_country': self.passport_country,
            'nationality': self.nationality,
            'seat_preference': self.seat_preference,
            'meal_preference': self.meal_preference,
            'has_tsa_precheck': bool(self.known_traveler_number),
        }

    def to_dict_full(self):
        """Full dict including sensitive data (for user's own profile view)."""
        d = self.to_dict()
        d.update({
            'passport_number': self.passport_number,
            'passport_expiry': self.passport_expiry.isoformat() if self.passport_expiry else None,
            'redress_number': self.redress_number,
            'known_traveler_number': self.known_traveler_number,
            'frequent_flyer_numbers': self.frequent_flyer_numbers,
            'special_assistance': self.special_assistance,
            'emergency_contact_name': self.emergency_contact_name,
            'emergency_contact_phone': self.emergency_contact_phone,
            'emergency_contact_relation': self.emergency_contact_relation,
        })
        return d

    @staticmethod
    def create_from_user(user):
        """Create a primary traveler profile from user account data."""
        return TravelerProfile(
            user_id=user.id,
            label="Me",
            is_primary=True,
            first_name=user.name.split()[0] if user.name else "",
            last_name=" ".join(user.name.split()[1:]) if user.name and len(user.name.split()) > 1 else "",
            email=user.email,
            gender="MALE",  # Default, user should update
            date_of_birth=None,  # User must provide
        )


class SearchHistory(db.Model):
    """Persistent record of user searches for analytics and re-search."""
    __tablename__ = 'search_history'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)

    # Route
    origin = db.Column(db.String(10), nullable=False, index=True)
    destination = db.Column(db.String(10), nullable=False, index=True)
    departure_date = db.Column(db.Date, nullable=False)
    return_date = db.Column(db.Date)
    cabin_class = db.Column(db.String(20), default='economy')

    # Results summary
    results_count = db.Column(db.Integer, default=0)
    best_price_usd = db.Column(db.Float)
    best_market = db.Column(db.String(2))
    us_price_usd = db.Column(db.Float)
    max_savings_usd = db.Column(db.Float)
    max_savings_percent = db.Column(db.Float)

    # Search metadata
    search_method = db.Column(db.String(20))  # hybrid, proxy_only, amadeus
    search_duration_ms = db.Column(db.Integer)
    markets_searched = db.Column(db.Text)  # JSON list of market codes

    created_at = db.Column(db.DateTime, default=_utcnow)

    user = db.relationship('User', backref='search_history')

    def to_dict(self):
        return {
            'id': self.id,
            'route': f"{self.origin} → {self.destination}",
            'departure_date': self.departure_date.isoformat() if self.departure_date else None,
            'return_date': self.return_date.isoformat() if self.return_date else None,
            'cabin_class': self.cabin_class,
            'best_price_usd': self.best_price_usd,
            'best_market': self.best_market,
            'us_price_usd': self.us_price_usd,
            'max_savings_usd': self.max_savings_usd,
            'max_savings_percent': self.max_savings_percent,
            'results_count': self.results_count,
            'searched_at': self.created_at.isoformat() if self.created_at else None,
        }


class PriceHistory(db.Model):
    """Historical price snapshots for route/date/market combos."""
    __tablename__ = 'price_history'

    id = db.Column(db.Integer, primary_key=True)

    # Route
    origin = db.Column(db.String(10), nullable=False, index=True)
    destination = db.Column(db.String(10), nullable=False, index=True)
    departure_date = db.Column(db.Date, nullable=False, index=True)
    cabin_class = db.Column(db.String(20), default='economy')

    # Price data
    market = db.Column(db.String(2), nullable=False, index=True)  # e.g. "US", "ES", "JP"
    price_usd = db.Column(db.Float, nullable=False)
    price_local = db.Column(db.Float)
    local_currency = db.Column(db.String(3))
    airline = db.Column(db.String(50))

    # Snapshot context
    source = db.Column(db.String(20))  # proxy, amadeus, hybrid
    recorded_at = db.Column(db.DateTime, default=_utcnow, index=True)

    __table_args__ = (
        db.Index('ix_price_history_route_date',
                 'origin', 'destination', 'departure_date', 'market'),
    )

    def to_dict(self):
        return {
            'origin': self.origin,
            'destination': self.destination,
            'departure_date': self.departure_date.isoformat() if self.departure_date else None,
            'market': self.market,
            'price_usd': self.price_usd,
            'airline': self.airline,
            'recorded_at': self.recorded_at.isoformat() if self.recorded_at else None,
        }


class CommercialAccount(db.Model):
    """
    Commercial entity onboarded to Mystes (travel agency, OTA, corporate travel desk).

    Fee model:
    - Fee = savings × fee_percent — no minimum fee, no charge if no savings found
    - Only charged on completed bookings, not searches
    - Rate tier determined by rolling 30-day completed ticket volume
    - Rate cuts suspend if volume drops below tier threshold for 2 consecutive periods

    Referral system:
    - Each account gets a unique referral_code (e.g. "APEXTRAVEL")
    - Clients who sign up via /join/<code> are attributed to this account
    - Referred users expand the network
    """
    __tablename__ = 'commercial_accounts'

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    contact_email = db.Column(db.String(255), nullable=False)
    contact_name = db.Column(db.String(100))
    company_website = db.Column(db.String(255))

    # Owning user (admin of this commercial account)
    owner_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)

    # Current fee tier (recalculated by usage tracker)
    current_tier = db.Column(db.String(20), default='starter', nullable=False)
    fee_percent = db.Column(db.Float, default=20.0, nullable=False)

    # Volume tracking (rolling 30-day window)
    tickets_last_30d = db.Column(db.Integer, default=0)
    revenue_last_30d_usd = db.Column(db.Float, default=0.0)
    total_tickets = db.Column(db.Integer, default=0)
    total_revenue_usd = db.Column(db.Float, default=0.0)

    # Tier retention: consecutive periods below threshold = tier downgrade
    periods_below_threshold = db.Column(db.Integer, default=0)

    # Referral system
    referral_code = db.Column(db.String(20), unique=True, index=True)  # e.g. "APEXTRAVEL"
    total_referred_users = db.Column(db.Integer, default=0)

    # Access controls
    is_active = db.Column(db.Boolean, default=True)
    max_daily_searches = db.Column(db.Integer, default=500)
    max_concurrent_searches = db.Column(db.Integer, default=10)

    # Stripe subscription (B2B monthly billing — Build #158)
    stripe_customer_id = db.Column(db.String(100), unique=True, nullable=True, index=True)
    stripe_subscription_id = db.Column(db.String(100), unique=True, nullable=True)
    subscription_status = db.Column(db.String(20), default='none')  # none/active/past_due/canceled
    subscription_plan = db.Column(db.String(30), default='b2b_starter')
    current_period_end = db.Column(db.DateTime, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=_utcnow)
    activated_at = db.Column(db.DateTime)
    suspended_at = db.Column(db.DateTime)
    last_tier_review = db.Column(db.DateTime)

    # Relationships
    owner = db.relationship('User', foreign_keys=[owner_user_id], backref='commercial_accounts')

    def to_dict(self):
        return {
            'account_id': self.account_id,
            'name': self.name,
            'contact_email': self.contact_email,
            'current_tier': self.current_tier,
            'fee_percent': self.fee_percent,
            'tickets_last_30d': self.tickets_last_30d,
            'revenue_last_30d_usd': round(self.revenue_last_30d_usd, 2),
            'total_tickets': self.total_tickets,
            'total_revenue_usd': round(self.total_revenue_usd, 2),
            'is_active': self.is_active,
            'referral_code': self.referral_code,
            'total_referred_users': self.total_referred_users or 0,
            'subscription_status': self.subscription_status,
            'subscription_plan': self.subscription_plan,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class CommercialAPIKey(db.Model):
    """API keys for commercial account programmatic access."""
    __tablename__ = 'commercial_api_keys'

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('commercial_accounts.id'), nullable=False, index=True)

    key_prefix = db.Column(db.String(8), nullable=False)  # First 8 chars (for display: "phx_abc1...")
    key_hash = db.Column(db.String(128), nullable=False)   # bcrypt hash of full key
    label = db.Column(db.String(100), default='Default')

    # Permissions
    scopes = db.Column(db.Text)  # JSON list: ["search", "book", "p2p", "analytics"]
    is_active = db.Column(db.Boolean, default=True)

    # Usage tracking
    last_used_at = db.Column(db.DateTime)
    total_requests = db.Column(db.Integer, default=0)

    # Timestamps
    created_at = db.Column(db.DateTime, default=_utcnow)
    expires_at = db.Column(db.DateTime)

    # Relationships
    account = db.relationship('CommercialAccount', backref='api_keys')

    def to_dict(self):
        return {
            'id': self.id,
            'key_prefix': f"phx_{self.key_prefix}...",
            'label': self.label,
            'scopes': self.scopes,
            'is_active': self.is_active,
            'last_used_at': self.last_used_at.isoformat() if self.last_used_at else None,
            'total_requests': self.total_requests,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class CommercialTransaction(db.Model):
    """
    Tracks every completed booking through a commercial account.

    Fee is calculated and recorded here on completion.
    Only completed transactions incur fees — searches are free (within quota).
    """
    __tablename__ = 'commercial_transactions'

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('commercial_accounts.id'), nullable=False, index=True)

    # Reference to the underlying booking
    booking_id = db.Column(db.Integer, db.ForeignKey('bookings.id'))

    # Pricing
    retail_price_usd = db.Column(db.Float, nullable=False)   # US market price
    booked_price_usd = db.Column(db.Float, nullable=False)   # Actual price paid
    savings_usd = db.Column(db.Float, nullable=False)         # retail - booked
    savings_percent = db.Column(db.Float)

    # Fee calculation (percentage of savings only — no minimum fee)
    fee_percent_applied = db.Column(db.Float, nullable=False)  # Tier rate at time of transaction
    fee_amount_usd = db.Column(db.Float, nullable=False)       # savings × fee_percent

    # Route info
    origin = db.Column(db.String(10))
    destination = db.Column(db.String(10))
    market_used = db.Column(db.String(2))

    # Status
    status = db.Column(db.String(20), default='completed', index=True)

    created_at = db.Column(db.DateTime, default=_utcnow)

    # Relationships
    account = db.relationship('CommercialAccount', backref='transactions')

    def to_dict(self):
        return {
            'retail_price_usd': self.retail_price_usd,
            'booked_price_usd': self.booked_price_usd,
            'savings_usd': round(self.savings_usd, 2),
            'savings_percent': self.savings_percent,
            'fee_amount_usd': round(self.fee_amount_usd, 2),
            'fee_percent_applied': self.fee_percent_applied,
            'origin': self.origin,
            'destination': self.destination,
            'market_used': self.market_used,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class AirlineClient(db.Model):
    """
    Airline subscriber to Mystes intelligence platform.

    SEPARATE from CommercialAccount — different customer type, pricing model.
    Airlines pay flat monthly subscription ($100K-500K/mo) for competitive
    pricing intelligence, ancillary optimization data, and demand signals.
    Data-only service — NO booking capability.
    """
    __tablename__ = 'airline_clients'

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.String(50), unique=True, nullable=False, index=True)

    # Airline identity
    iata_code = db.Column(db.String(3), nullable=False, index=True)
    airline_name = db.Column(db.String(200), nullable=False)
    contact_email = db.Column(db.String(255), nullable=False)
    contact_name = db.Column(db.String(100))

    # Subscription tier: basic ($100K), pro ($250K), enterprise ($500K)
    subscription_tier = db.Column(db.String(30), default='basic', nullable=False)
    monthly_fee_usd = db.Column(db.Float, nullable=False)

    # Data access scope (JSON)
    routes_subscribed = db.Column(db.Text)       # ["JFK-*", "LAX-LHR"]
    data_scopes = db.Column(db.Text)             # ["pricing", "ancillary", "demand", "alerts", "reports"]
    competitor_airlines = db.Column(db.Text)      # ["AA", "DL", "BA"]
    markets_subscribed = db.Column(db.Text)       # ["US", "UK", "JP"]

    # Contract
    contract_start = db.Column(db.Date)
    contract_end = db.Column(db.Date)
    is_active = db.Column(db.Boolean, default=True)

    # Usage tracking
    api_calls_this_month = db.Column(db.Integer, default=0)
    api_calls_total = db.Column(db.Integer, default=0)
    reports_generated = db.Column(db.Integer, default=0)

    # Timestamps
    created_at = db.Column(db.DateTime, default=_utcnow)
    activated_at = db.Column(db.DateTime)
    suspended_at = db.Column(db.DateTime)

    # Relationships
    api_keys = db.relationship('AirlineAPIKey', backref='client', lazy='dynamic')
    reports = db.relationship('AirlineReport', backref='client', lazy='dynamic')
    alerts = db.relationship('AirlineAlert', backref='client', lazy='dynamic')

    def to_dict(self):
        return {
            'client_id': self.client_id,
            'iata_code': self.iata_code,
            'airline_name': self.airline_name,
            'subscription_tier': self.subscription_tier,
            'monthly_fee_usd': self.monthly_fee_usd,
            'is_active': self.is_active,
            'contract_start': self.contract_start.isoformat() if self.contract_start else None,
            'contract_end': self.contract_end.isoformat() if self.contract_end else None,
            'api_calls_this_month': self.api_calls_this_month or 0,
            'api_calls_total': self.api_calls_total or 0,
            'reports_generated': self.reports_generated or 0,
            'routes_subscribed': json.loads(self.routes_subscribed) if self.routes_subscribed else [],
            'competitor_airlines': json.loads(self.competitor_airlines) if self.competitor_airlines else [],
            'markets_subscribed': json.loads(self.markets_subscribed) if self.markets_subscribed else [],
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class AirlineAPIKey(db.Model):
    """API keys for airline intelligence access. Separate from CommercialAPIKey."""
    __tablename__ = 'airline_api_keys'

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('airline_clients.id'), nullable=False, index=True)

    key_prefix = db.Column(db.String(8), nullable=False)
    key_hash = db.Column(db.String(128), nullable=False)
    label = db.Column(db.String(100), default='Production')

    # Scopes: pricing, ancillary, demand, alerts, reports
    scopes = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)

    last_used_at = db.Column(db.DateTime)
    total_requests = db.Column(db.Integer, default=0)

    created_at = db.Column(db.DateTime, default=_utcnow)
    expires_at = db.Column(db.DateTime)

    def to_dict(self):
        return {
            'id': self.id,
            'key_prefix': f"air_{self.key_prefix}...",
            'label': self.label,
            'scopes': json.loads(self.scopes) if self.scopes else [],
            'is_active': self.is_active,
            'last_used_at': self.last_used_at.isoformat() if self.last_used_at else None,
            'total_requests': self.total_requests or 0,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class AirlineReport(db.Model):
    """Generated intelligence reports for airline clients."""
    __tablename__ = 'airline_reports'

    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    client_id = db.Column(db.Integer, db.ForeignKey('airline_clients.id'), nullable=False, index=True)

    # Report metadata
    report_type = db.Column(db.String(30), nullable=False, index=True)
    # pricing_daily, pricing_weekly, ancillary_weekly, demand_monthly, competitor_analysis
    period_start = db.Column(db.Date, nullable=False)
    period_end = db.Column(db.Date, nullable=False)

    # Report data (cached JSON)
    report_data = db.Column(db.Text)
    summary = db.Column(db.Text)

    # Metrics
    routes_analyzed = db.Column(db.Integer)
    markets_analyzed = db.Column(db.Integer)
    data_points = db.Column(db.Integer)

    # Status: generating, completed, failed
    status = db.Column(db.String(20), default='generating', index=True)
    error_message = db.Column(db.Text)

    generated_at = db.Column(db.DateTime, default=_utcnow, index=True)

    def to_dict(self):
        return {
            'report_id': self.report_id,
            'report_type': self.report_type,
            'period_start': self.period_start.isoformat(),
            'period_end': self.period_end.isoformat(),
            'summary': self.summary,
            'routes_analyzed': self.routes_analyzed,
            'markets_analyzed': self.markets_analyzed,
            'data_points': self.data_points,
            'status': self.status,
            'generated_at': self.generated_at.isoformat() if self.generated_at else None,
        }


class AirlineAlert(db.Model):
    """Configurable competitive alerts for airline clients."""
    __tablename__ = 'airline_alerts'

    id = db.Column(db.Integer, primary_key=True)
    alert_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    client_id = db.Column(db.Integer, db.ForeignKey('airline_clients.id'), nullable=False, index=True)

    # Alert type: price_drop, price_spike, demand_surge, new_route, ancillary_change
    alert_type = db.Column(db.String(30), nullable=False, index=True)

    # Target scope
    route_pattern = db.Column(db.String(50))      # "JFK-LHR" or "JFK-*"
    competitor_iata = db.Column(db.String(3))
    market = db.Column(db.String(2))

    # Trigger thresholds
    price_change_pct = db.Column(db.Float)
    price_change_usd = db.Column(db.Float)
    demand_change_pct = db.Column(db.Float)

    # Notification config
    notify_email = db.Column(db.Boolean, default=True)
    notify_webhook = db.Column(db.String(500))
    notify_sse = db.Column(db.Boolean, default=True)

    is_active = db.Column(db.Boolean, default=True)
    last_triggered = db.Column(db.DateTime)
    trigger_count = db.Column(db.Integer, default=0)

    created_at = db.Column(db.DateTime, default=_utcnow)

    def to_dict(self):
        return {
            'alert_id': self.alert_id,
            'alert_type': self.alert_type,
            'route_pattern': self.route_pattern,
            'competitor_iata': self.competitor_iata,
            'market': self.market,
            'price_change_pct': self.price_change_pct,
            'price_change_usd': self.price_change_usd,
            'demand_change_pct': self.demand_change_pct,
            'is_active': self.is_active,
            'last_triggered': self.last_triggered.isoformat() if self.last_triggered else None,
            'trigger_count': self.trigger_count or 0,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class AncillarySnapshot(db.Model):
    """
    Persistent ancillary pricing data (bags, seats, upgrades) per route/market/date.

    Amadeus returns baggage info but it's not currently persisted.
    This model captures and stores it for airline intelligence analytics.
    """
    __tablename__ = 'ancillary_snapshots'

    id = db.Column(db.Integer, primary_key=True)

    origin = db.Column(db.String(10), nullable=False, index=True)
    destination = db.Column(db.String(10), nullable=False, index=True)
    departure_date = db.Column(db.Date, nullable=False, index=True)
    market = db.Column(db.String(2), nullable=False, index=True)
    airline = db.Column(db.String(50), index=True)

    # Baggage pricing
    checked_bag_1_price_local = db.Column(db.Float)
    checked_bag_1_price_usd = db.Column(db.Float)
    checked_bag_2_price_local = db.Column(db.Float)
    checked_bag_2_price_usd = db.Column(db.Float)
    carry_on_included = db.Column(db.Boolean)

    # Baggage allowances
    checked_bag_weight_kg = db.Column(db.Integer)
    checked_bag_count_included = db.Column(db.Integer)

    # Seat selection pricing
    seat_selection_min_price_local = db.Column(db.Float)
    seat_selection_max_price_local = db.Column(db.Float)
    seat_selection_min_price_usd = db.Column(db.Float)
    seat_selection_max_price_usd = db.Column(db.Float)

    # Upgrade pricing
    upgrade_to_premium_economy_usd = db.Column(db.Float)
    upgrade_to_business_usd = db.Column(db.Float)

    local_currency = db.Column(db.String(3))
    source = db.Column(db.String(20))          # amadeus, scraped
    data_quality = db.Column(db.String(20))    # complete, partial, estimated

    recorded_at = db.Column(db.DateTime, default=_utcnow, index=True)

    __table_args__ = (
        db.Index('ix_ancillary_route_date_market',
                 'origin', 'destination', 'departure_date', 'market'),
    )

    def to_dict(self):
        return {
            'origin': self.origin,
            'destination': self.destination,
            'departure_date': self.departure_date.isoformat() if self.departure_date else None,
            'market': self.market,
            'airline': self.airline,
            'checked_bag_1_price_usd': self.checked_bag_1_price_usd,
            'checked_bag_2_price_usd': self.checked_bag_2_price_usd,
            'carry_on_included': self.carry_on_included,
            'checked_bag_count_included': self.checked_bag_count_included,
            'checked_bag_weight_kg': self.checked_bag_weight_kg,
            'seat_selection_range_usd': {
                'min': self.seat_selection_min_price_usd,
                'max': self.seat_selection_max_price_usd,
            } if self.seat_selection_min_price_usd else None,
            'recorded_at': self.recorded_at.isoformat() if self.recorded_at else None,
        }


class CompetitorPricing(db.Model):
    """
    Aggregated competitive pricing view — airline vs airline per route/market.

    Materialized daily from PriceHistory for fast airline intelligence queries.
    """
    __tablename__ = 'competitor_pricing'

    id = db.Column(db.Integer, primary_key=True)

    origin = db.Column(db.String(10), nullable=False, index=True)
    destination = db.Column(db.String(10), nullable=False, index=True)
    market = db.Column(db.String(2), nullable=False, index=True)

    snapshot_date = db.Column(db.Date, nullable=False, index=True)

    airline_iata = db.Column(db.String(3), nullable=False, index=True)
    avg_price_usd = db.Column(db.Float, nullable=False)
    min_price_usd = db.Column(db.Float)
    max_price_usd = db.Column(db.Float)
    sample_count = db.Column(db.Integer)

    market_rank = db.Column(db.Integer)
    price_vs_market_avg_pct = db.Column(db.Float)

    calculated_at = db.Column(db.DateTime, default=_utcnow, index=True)

    __table_args__ = (
        db.Index('ix_competitor_route_date_airline',
                 'origin', 'destination', 'snapshot_date', 'airline_iata'),
    )

    def to_dict(self):
        return {
            'origin': self.origin,
            'destination': self.destination,
            'market': self.market,
            'snapshot_date': self.snapshot_date.isoformat() if self.snapshot_date else None,
            'airline_iata': self.airline_iata,
            'avg_price_usd': round(self.avg_price_usd, 2),
            'min_price_usd': round(self.min_price_usd, 2) if self.min_price_usd else None,
            'max_price_usd': round(self.max_price_usd, 2) if self.max_price_usd else None,
            'sample_count': self.sample_count,
            'market_rank': self.market_rank,
            'price_vs_market_avg_pct': round(self.price_vs_market_avg_pct, 1) if self.price_vs_market_avg_pct else None,
        }
class FlightPriceRecord(db.Model):
    """Structured flight price observation from a specific market."""
    __tablename__ = 'flight_price_records'

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.String(50), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    market = db.Column(db.String(5), nullable=False, index=True)
    origin = db.Column(db.String(10), nullable=False, index=True)
    destination = db.Column(db.String(10), nullable=False, index=True)
    departure_date = db.Column(db.Date, nullable=False, index=True)
    return_date = db.Column(db.Date, nullable=True)
    airline = db.Column(db.String(100), nullable=True, index=True)
    price_usd = db.Column(db.Float, nullable=False)
    price_local = db.Column(db.Float, nullable=True)
    currency = db.Column(db.String(5), nullable=True)
    stops = db.Column(db.Integer, default=0)
    duration_minutes = db.Column(db.Integer, nullable=True)
    cabin_class = db.Column(db.String(20), default='economy')
    observed_at = db.Column(db.DateTime, default=_utcnow, index=True)

    __table_args__ = (
        db.Index('ix_flight_route_date', 'origin', 'destination', 'departure_date'),
        db.Index('ix_flight_market_route', 'market', 'origin', 'destination'),
    )

    def to_dict(self):
        return {
            'task_id': self.task_id,
            'market': self.market,
            'origin': self.origin,
            'destination': self.destination,
            'departure_date': self.departure_date.isoformat() if self.departure_date else None,
            'return_date': self.return_date.isoformat() if self.return_date else None,
            'airline': self.airline,
            'price_usd': round(self.price_usd, 2),
            'price_local': self.price_local,
            'currency': self.currency,
            'stops': self.stops,
            'duration_minutes': self.duration_minutes,
            'cabin_class': self.cabin_class,
            'observed_at': self.observed_at.isoformat() if self.observed_at else None,
        }


class HotelPriceRecord(db.Model):
    """Structured hotel price observation from a specific market."""
    __tablename__ = 'hotel_price_records'

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.String(50), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    market = db.Column(db.String(5), nullable=False, index=True)
    hotel_name = db.Column(db.String(300), nullable=False, index=True)
    location = db.Column(db.String(200), nullable=True)
    checkin_date = db.Column(db.Date, nullable=True)
    checkout_date = db.Column(db.Date, nullable=True)
    price_per_night_usd = db.Column(db.Float, nullable=False)
    price_per_night_local = db.Column(db.Float, nullable=True)
    currency = db.Column(db.String(5), nullable=True)
    rating = db.Column(db.Float, nullable=True)
    star_rating = db.Column(db.Integer, nullable=True)
    amenities = db.Column(db.Text, nullable=True)  # JSON list
    source_platform = db.Column(db.String(100), nullable=True)
    observed_at = db.Column(db.DateTime, default=_utcnow, index=True)

    __table_args__ = (
        db.Index('ix_hotel_name_market', 'hotel_name', 'market'),
        db.Index('ix_hotel_location', 'location'),
    )

    def to_dict(self):
        return {
            'task_id': self.task_id,
            'market': self.market,
            'hotel_name': self.hotel_name,
            'location': self.location,
            'checkin_date': self.checkin_date.isoformat() if self.checkin_date else None,
            'checkout_date': self.checkout_date.isoformat() if self.checkout_date else None,
            'price_per_night_usd': round(self.price_per_night_usd, 2),
            'price_per_night_local': self.price_per_night_local,
            'currency': self.currency,
            'rating': self.rating,
            'star_rating': self.star_rating,
            'amenities': json.loads(self.amenities) if self.amenities else [],
            'source_platform': self.source_platform,
            'observed_at': self.observed_at.isoformat() if self.observed_at else None,
        }


class CruisePriceRecord(db.Model):
    """Structured cruise price observation from a specific market."""
    __tablename__ = 'cruise_price_records'

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.String(50), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    market = db.Column(db.String(5), nullable=False, index=True)
    cruise_line = db.Column(db.String(100), nullable=False, index=True)
    ship_name = db.Column(db.String(200), nullable=True)
    itinerary = db.Column(db.String(500), nullable=True)
    departure_port = db.Column(db.String(100), nullable=True, index=True)
    departure_date = db.Column(db.Date, nullable=True, index=True)
    duration_nights = db.Column(db.Integer, nullable=True)
    cabin_type = db.Column(db.String(50), nullable=True)
    price_usd = db.Column(db.Float, nullable=False)
    price_local = db.Column(db.Float, nullable=True)
    currency = db.Column(db.String(5), nullable=True)
    price_per_night_usd = db.Column(db.Float, nullable=True)
    observed_at = db.Column(db.DateTime, default=_utcnow, index=True)

    __table_args__ = (
        db.Index('ix_cruise_line_market', 'cruise_line', 'market'),
        db.Index('ix_cruise_port_date', 'departure_port', 'departure_date'),
    )

    def to_dict(self):
        return {
            'task_id': self.task_id,
            'market': self.market,
            'cruise_line': self.cruise_line,
            'ship_name': self.ship_name,
            'itinerary': self.itinerary,
            'departure_port': self.departure_port,
            'departure_date': self.departure_date.isoformat() if self.departure_date else None,
            'duration_nights': self.duration_nights,
            'cabin_type': self.cabin_type,
            'price_usd': round(self.price_usd, 2),
            'price_per_night_usd': round(self.price_per_night_usd, 2) if self.price_per_night_usd else None,
            'observed_at': self.observed_at.isoformat() if self.observed_at else None,
        }


class ProductPriceRecord(db.Model):
    """Structured product/e-commerce price observation from a specific market."""
    __tablename__ = 'product_price_records'

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.String(50), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    market = db.Column(db.String(5), nullable=False, index=True)
    product_title = db.Column(db.String(500), nullable=False)
    category = db.Column(db.String(50), nullable=True, index=True)
    seller = db.Column(db.String(200), nullable=True)
    platform = db.Column(db.String(100), nullable=True, index=True)
    price_usd = db.Column(db.Float, nullable=False)
    price_local = db.Column(db.Float, nullable=True)
    currency = db.Column(db.String(5), nullable=True)
    rating = db.Column(db.Float, nullable=True)
    availability = db.Column(db.String(50), nullable=True)
    product_url = db.Column(db.String(500), nullable=True)
    is_ecommerce = db.Column(db.Boolean, default=False)
    shipping_estimate_usd = db.Column(db.Float, nullable=True)
    landed_cost_usd = db.Column(db.Float, nullable=True)
    observed_at = db.Column(db.DateTime, default=_utcnow, index=True)

    __table_args__ = (
        db.Index('ix_product_category_market', 'category', 'market'),
        db.Index('ix_product_platform_market', 'platform', 'market'),
    )

    def to_dict(self):
        return {
            'task_id': self.task_id,
            'market': self.market,
            'product_title': self.product_title,
            'category': self.category,
            'seller': self.seller,
            'platform': self.platform,
            'price_usd': round(self.price_usd, 2),
            'price_local': self.price_local,
            'currency': self.currency,
            'rating': self.rating,
            'availability': self.availability,
            'product_url': self.product_url,
            'is_ecommerce': self.is_ecommerce,
            'shipping_estimate_usd': self.shipping_estimate_usd,
            'landed_cost_usd': round(self.landed_cost_usd, 2) if self.landed_cost_usd else None,
            'observed_at': self.observed_at.isoformat() if self.observed_at else None,
        }


class MarketplaceListingRecord(db.Model):
    """Structured marketplace listing observation."""
    __tablename__ = 'marketplace_listing_records'

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.String(50), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    market = db.Column(db.String(5), nullable=False, index=True)
    listing_title = db.Column(db.String(500), nullable=False)
    price_usd = db.Column(db.Float, nullable=False)
    price_local = db.Column(db.Float, nullable=True)
    currency = db.Column(db.String(5), nullable=True)
    location = db.Column(db.String(200), nullable=True, index=True)
    seller_name = db.Column(db.String(200), nullable=True)
    condition = db.Column(db.String(50), nullable=True)
    listing_url = db.Column(db.String(500), nullable=True)
    image_url = db.Column(db.String(500), nullable=True)
    is_bargain = db.Column(db.Boolean, default=False, index=True)
    pct_of_median = db.Column(db.Float, nullable=True)
    observed_at = db.Column(db.DateTime, default=_utcnow, index=True)

    __table_args__ = (
        db.Index('ix_mktplace_market_location', 'market', 'location'),
        db.Index('ix_mktplace_bargains', 'is_bargain', 'observed_at'),
    )

    def to_dict(self):
        return {
            'task_id': self.task_id,
            'market': self.market,
            'listing_title': self.listing_title,
            'price_usd': round(self.price_usd, 2),
            'price_local': self.price_local,
            'currency': self.currency,
            'location': self.location,
            'seller_name': self.seller_name,
            'condition': self.condition,
            'listing_url': self.listing_url,
            'is_bargain': self.is_bargain,
            'pct_of_median': self.pct_of_median,
            'observed_at': self.observed_at.isoformat() if self.observed_at else None,
        }


class AISearchQuery(db.Model):
    """Record of an AI ensemble search query."""
    __tablename__ = 'ai_search_queries'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    query_text = db.Column(db.Text, nullable=False)
    market = db.Column(db.String(5), nullable=True)
    providers_queried = db.Column(db.Text, nullable=True)  # JSON list of provider keys
    best_provider = db.Column(db.String(50), nullable=True)
    best_model = db.Column(db.String(100), nullable=True)
    best_response = db.Column(db.Text, nullable=True)
    all_responses = db.Column(db.Text, nullable=True)  # JSON array of all provider responses
    total_tokens = db.Column(db.Integer, default=0)
    response_time_ms = db.Column(db.Integer, default=0)
    credits_used = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=_utcnow)

    user = db.relationship('User', backref=db.backref('ai_queries', lazy='dynamic'))

    __table_args__ = (
        db.Index('ix_ai_search_user_created', 'user_id', 'created_at'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'query_text': self.query_text,
            'market': self.market,
            'best_provider': self.best_provider,
            'best_model': self.best_model,
            'best_response': self.best_response,
            'all_responses': json.loads(self.all_responses) if self.all_responses else [],
            'total_tokens': self.total_tokens,
            'response_time_ms': self.response_time_ms,
            'credits_used': self.credits_used,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class UserAIProvider(db.Model):
    """User-provided API keys for AI providers (BYOAI)."""
    __tablename__ = 'user_ai_providers'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    provider_key = db.Column(db.String(50), nullable=False)  # e.g. "openai", "anthropic", "ollama"
    api_key_encrypted = db.Column(db.String(500), nullable=True)  # encrypted at rest; null for ollama
    custom_model = db.Column(db.String(200), nullable=True)
    custom_endpoint = db.Column(db.String(500), nullable=True)  # for ollama custom host
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=_utcnow)

    user = db.relationship('User', backref=db.backref('ai_providers', lazy='dynamic'))

    __table_args__ = (
        db.UniqueConstraint('user_id', 'provider_key', name='uq_user_ai_provider'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'provider_key': self.provider_key,
            'custom_model': self.custom_model,
            'custom_endpoint': self.custom_endpoint,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            # Never expose api_key_encrypted
        }


class AIConversation(db.Model):
    """Multi-turn MYSTES AI conversation session (Build #72)."""
    __tablename__ = 'ai_conversations'

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=True)
    message_count = db.Column(db.Integer, default=0)
    total_credits_used = db.Column(db.Float, default=0.0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=_utcnow)
    last_message_at = db.Column(db.DateTime, default=_utcnow)

    user = db.relationship('User', backref=db.backref('ai_conversations', lazy='dynamic'))

    __table_args__ = (
        db.Index('ix_ai_conv_user_last', 'user_id', 'last_message_at'),
    )

    def to_dict(self):
        return {
            'conversation_id': self.conversation_id,
            'title': self.title,
            'message_count': self.message_count,
            'total_credits_used': round(self.total_credits_used, 4),
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_message_at': self.last_message_at.isoformat() if self.last_message_at else None,
        }


class AIMessage(db.Model):
    """Individual message in a MYSTES AI conversation (Build #72)."""
    __tablename__ = 'ai_messages'

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.String(50), db.ForeignKey('ai_conversations.conversation_id'), nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False)  # 'user', 'assistant', 'tool_result'
    content = db.Column(db.Text, nullable=False)
    tool_calls = db.Column(db.Text, nullable=True)  # JSON: [{tool, args, result}]
    credits_used = db.Column(db.Float, default=0.0)
    model_used = db.Column(db.String(50), nullable=True)
    response_time_ms = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=_utcnow)

    conversation = db.relationship('AIConversation', backref=db.backref('messages', lazy='dynamic'))

    __table_args__ = (
        db.Index('ix_ai_msg_conv_created', 'conversation_id', 'created_at'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'conversation_id': self.conversation_id,
            'role': self.role,
            'content': self.content,
            'tool_calls': json.loads(self.tool_calls) if self.tool_calls else None,
            'credits_used': round(self.credits_used, 4),
            'model_used': self.model_used,
            'response_time_ms': self.response_time_ms,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


# ============================================================
# Strategy Learner Models (Build #73)
# ============================================================

class StrategyObservation(db.Model):
    """Records anonymized metadata from every search — ensemble, BYOAI, MystesAI, SERP.
    Never stores raw user content; only structural patterns and quality signals."""
    __tablename__ = 'strategy_observations'

    id = db.Column(db.Integer, primary_key=True)
    observation_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    source_type = db.Column(db.String(30), nullable=False)  # 'ensemble', 'mystes_ai', 'byoai', 'serp'
    provider_key = db.Column(db.String(50), nullable=True)  # which LLM provider
    query_category = db.Column(db.String(50), nullable=False)  # 'flights', 'hotels', 'products', 'serp', 'general'
    query_structure = db.Column(db.Text, nullable=True)  # JSON: anonymized query pattern
    source_sites = db.Column(db.Text, nullable=True)  # JSON: list of domains discovered
    strategies_detected = db.Column(db.Text, nullable=True)  # JSON: market selection, date flex, etc.
    result_count = db.Column(db.Integer, default=0)
    result_quality_score = db.Column(db.Float, default=0.0)  # 0-100
    markets_searched = db.Column(db.Text, nullable=True)  # JSON: list of market codes
    response_time_ms = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=_utcnow)

    __table_args__ = (
        db.Index('ix_strat_obs_source', 'source_type'),
        db.Index('ix_strat_obs_category', 'query_category'),
        db.Index('ix_strat_obs_created', 'created_at'),
    )

    def to_dict(self):
        return {
            'observation_id': self.observation_id,
            'source_type': self.source_type,
            'provider_key': self.provider_key,
            'query_category': self.query_category,
            'query_structure': json.loads(self.query_structure) if self.query_structure else None,
            'source_sites': json.loads(self.source_sites) if self.source_sites else [],
            'strategies_detected': json.loads(self.strategies_detected) if self.strategies_detected else [],
            'result_count': self.result_count,
            'result_quality_score': round(self.result_quality_score, 1),
            'markets_searched': json.loads(self.markets_searched) if self.markets_searched else [],
            'response_time_ms': self.response_time_ms,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class StrategyInsight(db.Model):
    """Aggregated insights derived from observations — effective patterns, sites, market combos."""
    __tablename__ = 'strategy_insights'

    id = db.Column(db.Integer, primary_key=True)
    insight_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    category = db.Column(db.String(50), nullable=False)  # 'flights', 'hotels', 'products', 'serp', 'general'
    insight_type = db.Column(db.String(50), nullable=False)  # 'query_pattern', 'source_site', 'market_combo', 'strategy'
    insight_data = db.Column(db.Text, nullable=False)  # JSON payload
    confidence_score = db.Column(db.Float, default=0.0)  # 0-1.0
    observation_count = db.Column(db.Integer, default=0)  # how many observations support this
    effectiveness_score = db.Column(db.Float, default=0.0)  # measured impact
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        db.Index('ix_strat_ins_category', 'category'),
        db.Index('ix_strat_ins_type', 'insight_type'),
        db.Index('ix_strat_ins_active', 'is_active'),
    )

    def to_dict(self):
        return {
            'insight_id': self.insight_id,
            'category': self.category,
            'insight_type': self.insight_type,
            'insight_data': json.loads(self.insight_data) if self.insight_data else {},
            'confidence_score': round(self.confidence_score, 3),
            'observation_count': self.observation_count,
            'effectiveness_score': round(self.effectiveness_score, 3),
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class TripBundle(db.Model):
    """
    A trip bundle combining flights + hotels + transfers into a single
    package with a reduced platform fee.

    Lifecycle:
        draft → payment_pending → booking → booked / partial / failed → cancelled
    """
    __tablename__ = 'trip_bundles'

    id = db.Column(db.Integer, primary_key=True)
    bundle_uuid = db.Column(db.String(36), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    # Pricing
    total_amount_usd = db.Column(db.Float, default=0.0)
    total_savings_usd = db.Column(db.Float, default=0.0)
    bundle_fee_usd = db.Column(db.Float, default=0.0)
    bundle_discount_pct = db.Column(db.Float, default=0.40)
    currency = db.Column(db.String(3), default='USD')

    # Status: draft, payment_pending, booking, booked, partial, failed, cancelled
    status = db.Column(db.String(20), default='draft')

    # Trip details (denormalized for display)
    origin = db.Column(db.String(10))
    destination = db.Column(db.String(10))
    departure_date = db.Column(db.Date, nullable=True)
    return_date = db.Column(db.Date, nullable=True)
    adults = db.Column(db.Integer, default=1)

    created_at = db.Column(db.DateTime, default=_utcnow)
    booked_at = db.Column(db.DateTime, nullable=True)

    items = db.relationship('BundleItem', backref='bundle', lazy='dynamic')

    def to_dict(self):
        return {
            'id': self.id,
            'bundle_uuid': self.bundle_uuid,
            'user_id': self.user_id,
            'total_amount_usd': round(self.total_amount_usd, 2),
            'total_savings_usd': round(self.total_savings_usd, 2),
            'bundle_fee_usd': round(self.bundle_fee_usd, 2),
            'bundle_discount_pct': self.bundle_discount_pct,
            'currency': self.currency,
            'status': self.status,
            'origin': self.origin,
            'destination': self.destination,
            'departure_date': self.departure_date.isoformat() if self.departure_date else None,
            'return_date': self.return_date.isoformat() if self.return_date else None,
            'adults': self.adults,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'booked_at': self.booked_at.isoformat() if self.booked_at else None,
            'items': [item.to_dict() for item in self.items],
        }


class BundleItem(db.Model):
    """
    Individual component of a TripBundle — one flight, hotel, or transfer.

    Lifecycle:
        selected → validating → booking → booked / failed
    """
    __tablename__ = 'bundle_items'

    id = db.Column(db.Integer, primary_key=True)
    bundle_id = db.Column(db.Integer, db.ForeignKey('trip_bundles.id'), nullable=False)

    # Type: flight, hotel, transfer
    item_type = db.Column(db.String(20), nullable=False)

    # Amadeus offer data (JSON)
    offer_data = db.Column(db.Text)
    offer_id = db.Column(db.String(100))

    # Pricing for this component
    price_usd = db.Column(db.Float, default=0.0)
    currency = db.Column(db.String(3), default='USD')
    price_local = db.Column(db.Float, default=0.0)

    # Booking result (after book_bundle)
    booking_id = db.Column(db.Integer, db.ForeignKey('bookings.id'), nullable=True)
    amadeus_order_id = db.Column(db.String(100), nullable=True)
    confirmation_code = db.Column(db.String(100), nullable=True)

    # Status: selected, validating, booking, booked, failed
    status = db.Column(db.String(20), default='selected')

    # Timestamps
    created_at = db.Column(db.DateTime, default=_utcnow)
    booked_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'bundle_id': self.bundle_id,
            'item_type': self.item_type,
            'offer_id': self.offer_id,
            'price_usd': round(self.price_usd, 2),
            'currency': self.currency,
            'price_local': round(self.price_local, 2),
            'amadeus_order_id': self.amadeus_order_id,
            'confirmation_code': self.confirmation_code,
            'status': self.status,
            'booked_at': self.booked_at.isoformat() if self.booked_at else None,
        }


class FeatureFlag(db.Model):
    """Admin-controlled feature flags for phased rollout. (Build #95)

    Layer 1 (Launch): Flights, Hotels, Tier System, B2B, Travel+, Rewards, Trip Planner
    Layer 2 (Funded): Activities, Products, Rentals, Cruises, Local Businesses
    """
    __tablename__ = 'feature_flags'

    id = db.Column(db.Integer, primary_key=True)
    flag_key = db.Column(db.String(50), unique=True, nullable=False, index=True)
    flag_name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    layer = db.Column(db.Integer, default=1)  # 1, 2, or 3
    is_enabled = db.Column(db.Boolean, default=False)

    # Metadata
    enabled_at = db.Column(db.DateTime, nullable=True)
    enabled_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    def to_dict(self):
        return {
            'flag_key': self.flag_key,
            'flag_name': self.flag_name,
            'description': self.description,
            'layer': self.layer,
            'is_enabled': self.is_enabled,
            'enabled_at': self.enabled_at.isoformat() if self.enabled_at else None,
        }

    @classmethod
    def is_flag_enabled(cls, flag_key):
        """Check if a feature flag is enabled."""
        flag = cls.query.filter_by(flag_key=flag_key).first()
        return flag.is_enabled if flag else False

    @classmethod
    def get_all_flags(cls):
        """Get all feature flags grouped by layer."""
        flags = cls.query.order_by(cls.layer, cls.flag_key).all()
        return [f.to_dict() for f in flags]

    @classmethod
    def set_flag(cls, flag_key, enabled, admin_id=None):
        """Enable or disable a feature flag."""
        flag = cls.query.filter_by(flag_key=flag_key).first()
        if flag:
            flag.is_enabled = enabled
            if enabled:
                flag.enabled_at = datetime.now(timezone.utc)
                flag.enabled_by = admin_id
            else:
                flag.enabled_at = None
                flag.enabled_by = None
            db.session.commit()
            return True
        return False

    @classmethod
    def init_default_flags(cls):
        """Initialize default feature flags if they don't exist."""
        default_flags = [
            # Layer 1 - Launch
            ('vertical_flights', 'Flights Vertical', 'Search and book flights via Amadeus', 1, True),
            ('vertical_hotels', 'Hotels Vertical', 'Search and book hotels via liteAPI', 1, True),
            ('tier_system', 'Tier System', 'Bronze/Silver/Gold/Platinum user tiers', 1, True),
            ('b2b_accounts', 'B2B Accounts', 'Allow agencies to sign up for B2B accounts', 1, True),
            ('travel_plus', 'Travel+ Subscription', 'Travel+ consumer subscription tier', 1, True),
            ('rewards_points', 'Rewards Points', 'MYSTES rewards points system', 1, True),
            ('trip_planner', 'Trip Planner', 'Collaborative trip planning', 2, False),
            ('wishlist', 'Wishlist & Collections', 'Save items and create collections', 2, False),
            ('friends_system', 'Friends System', 'Add friends and plan together', 2, False),

            # Layer 2 - Funded (admin-enabled only until flights perfected)
            ('local_businesses', 'Local Businesses', 'Restaurant and venue listings', 2, False),
            ('vertical_activities', 'Activities Vertical', 'Tours and activities via Viator', 2, False),
            ('vertical_products', 'Products Vertical', 'Price comparison for physical products', 2, False),
            ('vertical_rentals', 'Rentals Vertical', 'Car and vacation rentals', 2, False),
            ('vertical_cruises', 'Cruises Vertical', 'Cruise booking and comparison', 2, False),
        ]

        for flag_key, name, desc, layer, enabled in default_flags:
            existing = cls.query.filter_by(flag_key=flag_key).first()
            if not existing:
                flag = cls(
                    flag_key=flag_key,
                    flag_name=name,
                    description=desc,
                    layer=layer,
                    is_enabled=enabled,
                    enabled_at=datetime.now(timezone.utc) if enabled else None,
                )
                db.session.add(flag)

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()


class SystemSetting(db.Model):
    """Admin-controlled system settings. (Build #95)"""
    __tablename__ = 'system_settings'

    id = db.Column(db.Integer, primary_key=True)
    setting_key = db.Column(db.String(50), unique=True, nullable=False, index=True)
    setting_value = db.Column(db.Text, nullable=True)
    setting_type = db.Column(db.String(20), default='string')  # string, int, float, bool, json
    description = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    @classmethod
    def get(cls, key, default=None):
        """Get a setting value."""
        setting = cls.query.filter_by(setting_key=key).first()
        if not setting:
            return default
        if setting.setting_type == 'int':
            return int(setting.setting_value) if setting.setting_value else default
        if setting.setting_type == 'float':
            return float(setting.setting_value) if setting.setting_value else default
        if setting.setting_type == 'bool':
            return setting.setting_value.lower() in ('true', '1', 'yes') if setting.setting_value else default
        if setting.setting_type == 'json':
            import json
            return json.loads(setting.setting_value) if setting.setting_value else default
        return setting.setting_value

    @classmethod
    def set(cls, key, value, setting_type='string', description=None, admin_id=None):
        """Set a setting value."""
        setting = cls.query.filter_by(setting_key=key).first()
        if setting:
            setting.setting_value = str(value)
            setting.updated_by = admin_id
        else:
            setting = cls(
                setting_key=key,
                setting_value=str(value),
                setting_type=setting_type,
                description=description,
                updated_by=admin_id,
            )
            db.session.add(setting)
        try:
            db.session.commit()
            return True
        except Exception:
            db.session.rollback()
            return False

    @classmethod
    def init_defaults(cls):
        """Initialize default system settings."""
        defaults = [
            ('node_payout_pct', '0', 'int', 'Percentage of proxy revenue paid to nodes (0-100)'),
        ]
        for key, value, stype, desc in defaults:
            if not cls.query.filter_by(setting_key=key).first():
                setting = cls(setting_key=key, setting_value=value, setting_type=stype, description=desc)
                db.session.add(setting)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()


# ============================================================
# Build #167 — Feature Foundation Models
# Subscription, Rewards, Trip Planner, Social, Wishlist, Local Business
# Each module is a pluggable vertical — sellable via ANASTASiA turnkey.
# ============================================================


class Subscription(db.Model):
    """Travel+ and B2B subscription tracking."""
    __tablename__ = 'subscriptions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    tier = db.Column(db.String(30), nullable=False, default='free')  # free/travel_plus/b2b_starter/b2b_growth/b2b_volume
    stripe_subscription_id = db.Column(db.String(255), unique=True, nullable=True)
    stripe_price_id = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='active')  # active/cancelled/past_due/trialing
    billing_cycle = db.Column(db.String(10), default='monthly')  # monthly/annual
    current_period_start = db.Column(db.DateTime, nullable=True)
    current_period_end = db.Column(db.DateTime, nullable=True)
    cancelled_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=_utcnow)

    user = db.relationship('User', backref=db.backref('subscriptions', lazy='dynamic'))

    def is_active(self):
        return self.status == 'active'

    def to_dict(self):
        return {
            'id': self.id,
            'tier': self.tier,
            'status': self.status,
            'billing_cycle': self.billing_cycle,
            'current_period_end': self.current_period_end.isoformat() if self.current_period_end else None,
        }


class AISession(db.Model):
    """Pay-per-session AI for free users ($2.99)."""
    __tablename__ = 'ai_sessions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    stripe_payment_id = db.Column(db.String(255), nullable=True)
    paid_at = db.Column(db.DateTime, default=_utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    messages_used = db.Column(db.Integer, default=0)
    max_messages = db.Column(db.Integer, default=30)
    is_active = db.Column(db.Boolean, default=True)

    user = db.relationship('User', backref=db.backref('ai_sessions', lazy='dynamic'))

    def has_messages_left(self):
        return self.messages_used < self.max_messages

    def is_expired(self):
        exp = self.expires_at
        if exp and exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) > exp


class RewardsAccount(db.Model):
    """One per user — tracks points balance and streaks."""
    __tablename__ = 'rewards_accounts'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False)
    points_balance = db.Column(db.Integer, default=0)
    lifetime_earned = db.Column(db.Integer, default=0)
    lifetime_redeemed = db.Column(db.Integer, default=0)
    current_streak_months = db.Column(db.Integer, default=0)
    longest_streak_months = db.Column(db.Integer, default=0)
    badge_level = db.Column(db.String(20), default='none')  # none/gold/platinum
    last_earning_at = db.Column(db.DateTime, nullable=True)
    points_expire_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=_utcnow)

    user = db.relationship('User', backref=db.backref('rewards_account', uselist=False))

    def to_dict(self):
        return {
            'points_balance': self.points_balance,
            'lifetime_earned': self.lifetime_earned,
            'current_streak_months': self.current_streak_months,
            'badge_level': self.badge_level,
            'points_expire_at': self.points_expire_at.isoformat() if self.points_expire_at else None,
        }


class PointsTransaction(db.Model):
    """Ledger of all point movements."""
    __tablename__ = 'points_transactions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    amount = db.Column(db.Integer, nullable=False)  # positive = earn, negative = redeem/expire
    transaction_type = db.Column(db.String(20), nullable=False)  # earn/redeem/bonus/expire/gift_sent/gift_received
    source = db.Column(db.String(30), nullable=True)  # booking/referral/review/streak/bundle_bonus/first_booking/welcome
    booking_id = db.Column(db.Integer, nullable=True)
    description = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=_utcnow)

    user = db.relationship('User', backref=db.backref('points_transactions', lazy='dynamic'))


class PointGift(db.Model):
    """Gift transfers between members."""
    __tablename__ = 'point_gifts'

    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    recipient_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    amount = db.Column(db.Integer, nullable=False)
    message = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=_utcnow)

    sender = db.relationship('User', foreign_keys=[sender_id], backref=db.backref('gifts_sent', lazy='dynamic'))
    recipient = db.relationship('User', foreign_keys=[recipient_id], backref=db.backref('gifts_received', lazy='dynamic'))


class PointsEscrow(db.Model):
    """Guest booking point holds — 90-day claim window (PayPal growth model)."""
    __tablename__ = 'points_escrow'

    id = db.Column(db.Integer, primary_key=True)
    guest_email = db.Column(db.String(255), nullable=False, index=True)
    points_amount = db.Column(db.Integer, nullable=False)
    booking_reference = db.Column(db.String(100), nullable=True)
    claimed_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    claim_deadline = db.Column(db.DateTime, nullable=False)
    reminder_sent_30d = db.Column(db.Boolean, default=False)
    reminder_sent_60d = db.Column(db.Boolean, default=False)
    reminder_sent_80d = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(20), default='pending')  # pending/claimed/expired
    created_at = db.Column(db.DateTime, default=_utcnow)


class TripPlan(db.Model):
    """Collaborative trip planning workspace."""
    __tablename__ = 'trip_plans'

    id = db.Column(db.Integer, primary_key=True)
    creator_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    cover_image = db.Column(db.String(500), nullable=True)
    status = db.Column(db.String(20), default='draft')  # draft/finalized/booked/completed
    destinations_json = db.Column(db.Text, nullable=True)  # JSON array of destinations
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)
    is_template = db.Column(db.Boolean, default=False)
    template_copies_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    creator = db.relationship('User', backref=db.backref('trip_plans', lazy='dynamic'))
    members = db.relationship('TripMember', backref='trip_plan', lazy='dynamic', cascade='all, delete-orphan')
    items = db.relationship('TripItem', backref='trip_plan', lazy='dynamic', cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'status': self.status,
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'member_count': self.members.count(),
            'item_count': self.items.count(),
        }


class TripMember(db.Model):
    """Who's in the trip."""
    __tablename__ = 'trip_members'

    id = db.Column(db.Integer, primary_key=True)
    trip_plan_id = db.Column(db.Integer, db.ForeignKey('trip_plans.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    role = db.Column(db.String(10), nullable=False, default='viewer')  # owner/editor/viewer
    budget_cap = db.Column(db.Float, nullable=True)
    invitation_status = db.Column(db.String(10), default='pending')  # pending/accepted/declined
    invited_at = db.Column(db.DateTime, default=_utcnow)
    joined_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User', backref=db.backref('trip_memberships', lazy='dynamic'))

    __table_args__ = (
        db.UniqueConstraint('trip_plan_id', 'user_id', name='uq_trip_member'),
    )


class TripItem(db.Model):
    """Items added to trip (flights, hotels, activities, events, dining)."""
    __tablename__ = 'trip_items'

    id = db.Column(db.Integer, primary_key=True)
    trip_plan_id = db.Column(db.Integer, db.ForeignKey('trip_plans.id'), nullable=False, index=True)
    added_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    vertical = db.Column(db.String(20), nullable=False)  # flight/hotel/activity/car/event/dining
    item_data_json = db.Column(db.Text, nullable=True)  # JSON — provider data, pricing, details
    destination_index = db.Column(db.Integer, default=0)
    day_number = db.Column(db.Integer, nullable=True)
    is_alternative = db.Column(db.Boolean, default=False)
    alternative_group_id = db.Column(db.String(50), nullable=True)
    votes_json = db.Column(db.Text, nullable=True)  # JSON {user_id: "up"/"down"}
    status = db.Column(db.String(20), default='proposed')  # proposed/approved/booked/cancelled
    created_at = db.Column(db.DateTime, default=_utcnow)

    added_by = db.relationship('User', backref=db.backref('trip_items_added', lazy='dynamic'))


class TripCart(db.Model):
    """Checkout state for a trip."""
    __tablename__ = 'trip_carts'

    id = db.Column(db.Integer, primary_key=True)
    trip_plan_id = db.Column(db.Integer, db.ForeignKey('trip_plans.id'), nullable=False, index=True)
    status = db.Column(db.String(20), default='open')  # open/checkout/paid/partial
    total_amount = db.Column(db.Float, default=0.0)
    currency = db.Column(db.String(3), default='USD')
    per_person_breakdown_json = db.Column(db.Text, nullable=True)
    finalized_at = db.Column(db.DateTime, nullable=True)

    trip_plan = db.relationship('TripPlan', backref=db.backref('carts', lazy='dynamic'))
    assignments = db.relationship('TripCartAssignment', backref='cart', lazy='dynamic', cascade='all, delete-orphan')


class TripCartAssignment(db.Model):
    """Who uses / who pays per item — the core of split payments."""
    __tablename__ = 'trip_cart_assignments'

    id = db.Column(db.Integer, primary_key=True)
    trip_cart_id = db.Column(db.Integer, db.ForeignKey('trip_carts.id'), nullable=False, index=True)
    trip_item_id = db.Column(db.Integer, db.ForeignKey('trip_items.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)     # who's USING this
    payer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)     # who's PAYING
    split_method = db.Column(db.String(15), default='even')  # even/custom/single/percentage
    amount_owed = db.Column(db.Float, default=0.0)
    percentage = db.Column(db.Float, nullable=True)
    payment_status = db.Column(db.String(20), default='pending')  # pending/approved/paid/refunded
    stripe_payment_intent_id = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=_utcnow)

    user = db.relationship('User', foreign_keys=[user_id])
    payer = db.relationship('User', foreign_keys=[payer_id])
    trip_item = db.relationship('TripItem', backref=db.backref('assignments', lazy='dynamic'))


class TripReceipt(db.Model):
    """Structured receipt per person — PDF export, expense categories."""
    __tablename__ = 'trip_receipts'

    id = db.Column(db.Integer, primary_key=True)
    trip_plan_id = db.Column(db.Integer, db.ForeignKey('trip_plans.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    trip_cart_assignment_id = db.Column(db.Integer, db.ForeignKey('trip_cart_assignments.id'), nullable=True)
    receipt_number = db.Column(db.String(20), unique=True, nullable=False)  # MYS-YYYY-NNNNN
    items_json = db.Column(db.Text, nullable=True)
    subtotal = db.Column(db.Float, default=0.0)
    savings = db.Column(db.Float, default=0.0)
    points_applied = db.Column(db.Integer, default=0)
    total_charged = db.Column(db.Float, default=0.0)
    payment_method_last4 = db.Column(db.String(4), nullable=True)
    company_name = db.Column(db.String(200), nullable=True)  # for business receipts
    pdf_url = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=_utcnow)

    user = db.relationship('User', backref=db.backref('trip_receipts', lazy='dynamic'))


class Friendship(db.Model):
    """Friends system — social graph for trip planning and referrals."""
    __tablename__ = 'friendships'

    id = db.Column(db.Integer, primary_key=True)
    requester_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    addressee_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    status = db.Column(db.String(10), default='pending')  # pending/accepted/blocked
    created_at = db.Column(db.DateTime, default=_utcnow)
    accepted_at = db.Column(db.DateTime, nullable=True)

    requester = db.relationship('User', foreign_keys=[requester_id], backref=db.backref('friend_requests_sent', lazy='dynamic'))
    addressee = db.relationship('User', foreign_keys=[addressee_id], backref=db.backref('friend_requests_received', lazy='dynamic'))

    __table_args__ = (
        db.UniqueConstraint('requester_id', 'addressee_id', name='uq_friendship'),
    )


class Collection(db.Model):
    """Wishlist folders — organize saved items by trip or theme."""
    __tablename__ = 'collections'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    cover_image = db.Column(db.String(500), nullable=True)
    is_shared = db.Column(db.Boolean, default=False)
    share_slug = db.Column(db.String(50), unique=True, nullable=True)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    user = db.relationship('User', backref=db.backref('collections', lazy='dynamic'))
    items = db.relationship('SavedItem', backref='collection', lazy='dynamic')


class SavedItem(db.Model):
    """Saved search results — Airbnb-style wishlist across all verticals."""
    __tablename__ = 'saved_items'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    collection_id = db.Column(db.Integer, db.ForeignKey('collections.id'), nullable=True)
    vertical = db.Column(db.String(20), nullable=False)  # flight/hotel/activity/car/dining
    item_data_json = db.Column(db.Text, nullable=True)  # JSON — route, hotel_id, dates, price, provider
    price_at_save = db.Column(db.Float, nullable=True)
    current_price = db.Column(db.Float, nullable=True)
    price_alert_enabled = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    user = db.relationship('User', backref=db.backref('saved_items', lazy='dynamic'))


class LocalBusiness(db.Model):
    """Restaurants, venues, event spaces — free listings, booking commission."""
    __tablename__ = 'local_businesses'

    id = db.Column(db.Integer, primary_key=True)
    owner_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    business_name = db.Column(db.String(200), nullable=False)
    business_type = db.Column(db.String(30), nullable=False)  # restaurant/venue/event_space/tour_guide/other
    description = db.Column(db.Text, nullable=True)
    address = db.Column(db.String(500), nullable=True)
    city = db.Column(db.String(100), nullable=True, index=True)
    country = db.Column(db.String(2), nullable=True)
    phone = db.Column(db.String(30), nullable=True)
    email = db.Column(db.String(255), nullable=True)
    website = db.Column(db.String(500), nullable=True)
    hours_json = db.Column(db.Text, nullable=True)  # JSON opening hours
    menu_url = db.Column(db.String(500), nullable=True)
    capacity = db.Column(db.Integer, nullable=True)
    price_range = db.Column(db.Integer, default=2)  # 1-4 ($-$$$$)
    tags_json = db.Column(db.Text, nullable=True)  # JSON array of tags
    photos_json = db.Column(db.Text, nullable=True)  # JSON array of photo URLs
    is_featured = db.Column(db.Boolean, default=False)
    commission_percent = db.Column(db.Float, default=15.0)
    is_verified = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    owner = db.relationship('User', backref=db.backref('local_businesses', lazy='dynamic'))

    def to_dict(self):
        return {
            'id': self.id,
            'business_name': self.business_name,
            'business_type': self.business_type,
            'city': self.city,
            'price_range': self.price_range,
            'is_featured': self.is_featured,
            'is_verified': self.is_verified,
        }


class ConsumerReferral(db.Model):
    """Tracks consumer-to-consumer referral events and point awards (Build #170)."""
    __tablename__ = 'consumer_referrals'

    id = db.Column(db.Integer, primary_key=True)
    referrer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    referee_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    referral_code_used = db.Column(db.String(20), nullable=False)
    # Milestone tracking
    signup_rewarded = db.Column(db.Boolean, default=False)
    first_booking_rewarded = db.Column(db.Boolean, default=False)
    travel_plus_rewarded = db.Column(db.Boolean, default=False)
    # Points awarded to referrer
    total_points_awarded = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=_utcnow)

    referrer = db.relationship('User', foreign_keys=[referrer_id],
                               backref=db.backref('referrals_made', lazy='dynamic'))
    referee = db.relationship('User', foreign_keys=[referee_id],
                              backref=db.backref('referred_by_rel', uselist=False,
                                                 foreign_keys=[referee_id]))

    __table_args__ = (
        db.UniqueConstraint('referee_id', name='uq_consumer_referral_referee'),
    )


class SocialShare(db.Model):
    """Tracks social shares for share-to-save discount (Build #170)."""
    __tablename__ = 'social_shares'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    guest_email = db.Column(db.String(255), nullable=True)
    deal_id = db.Column(db.String(20), nullable=False)
    platform = db.Column(db.String(20), nullable=False)  # twitter/facebook/whatsapp/copy_link
    share_token = db.Column(db.String(50), unique=True, nullable=False)
    referral_code = db.Column(db.String(20), nullable=True)
    clicks = db.Column(db.Integer, default=0)
    discount_applied = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=_utcnow)

    user = db.relationship('User', backref=db.backref('social_shares', lazy='dynamic'))


class GoogleReview(db.Model):
    """Pre-generated savings review card for Google Reviews (Build #178).

    Every booking generates a standard review card with real flight data,
    MYSTES price, competitor prices, and full savings breakdown. Customer
    taps 'Share & Review' — the card IS the review. Optional personal note.
    """
    __tablename__ = 'google_reviews'

    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey('bookings.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    guest_email = db.Column(db.String(255), nullable=True)

    # Flight/deal data baked into the card
    origin = db.Column(db.String(10), nullable=False)
    destination = db.Column(db.String(10), nullable=False)
    airline = db.Column(db.String(100), nullable=True)
    flight_number = db.Column(db.String(20), nullable=True)
    departure_date = db.Column(db.String(20), nullable=True)
    cabin_class = db.Column(db.String(30), nullable=True)

    # Pricing data
    mystes_price_usd = db.Column(db.Float, nullable=False)
    savings_usd = db.Column(db.Float, nullable=False, default=0)
    savings_percent = db.Column(db.Float, nullable=False, default=0)
    retail_price_usd = db.Column(db.Float, nullable=True)

    # Competitor prices (JSON: [{"name": "Expedia", "price": 487}, ...])
    competitor_prices_json = db.Column(db.Text, nullable=True)

    # Tier/discount breakdown
    tier_name = db.Column(db.String(30), nullable=True)
    fee_breakdown_json = db.Column(db.Text, nullable=True)

    # User content
    personal_note = db.Column(db.Text, nullable=True)
    referral_code = db.Column(db.String(20), nullable=True)

    # Review lifecycle
    review_token = db.Column(db.String(50), unique=True, nullable=False)
    shared_to_google = db.Column(db.Boolean, default=False)
    shared_to_social = db.Column(db.Boolean, default=False)
    discount_applied = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=_utcnow)
    shared_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    booking = db.relationship('Booking', backref=db.backref('google_review', uselist=False))
    user = db.relationship('User', backref=db.backref('google_reviews', lazy='dynamic'))


class ReferralCard(db.Model):
    """Pre-generated referral card for sharing (Build #179).

    Shareable visual card showing user's savings history + referral link.
    B2B: earns sales revenue. B2C: earns points. Costs MYSTES $0.
    Posted to social bios, stories, DMs — self-incentivizing.
    """
    __tablename__ = 'referral_cards'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False)
    card_token = db.Column(db.String(50), unique=True, nullable=False)
    referral_code = db.Column(db.String(20), nullable=False)

    # Aggregate stats (updated on each generation)
    total_bookings = db.Column(db.Integer, default=0)
    total_savings_usd = db.Column(db.Float, default=0.0)
    total_referrals = db.Column(db.Integer, default=0)
    total_points_earned = db.Column(db.Integer, default=0)
    member_since = db.Column(db.String(20), nullable=True)
    favorite_destination = db.Column(db.String(50), nullable=True)
    favorite_airline = db.Column(db.String(100), nullable=True)

    # Card metadata
    clicks = db.Column(db.Integer, default=0)
    conversions = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    user = db.relationship('User', backref=db.backref('referral_card', uselist=False))


def generate_referral_code(user_name=None):
    """Generate a unique consumer referral code like MYS-ABCD1234."""
    import secrets
    import re
    prefix = 'MYS'
    if user_name:
        clean = re.sub(r'[^A-Z]', '', user_name.upper())[:4]
        if len(clean) >= 2:
            prefix = clean

    for _ in range(10):
        code = f"{prefix}-{secrets.token_hex(3).upper()}"
        existing = User.query.filter_by(referral_code=code).first()
        if not existing:
            return code
    # Fallback
    return f"MYS-{secrets.token_hex(4).upper()}"


def init_db(app):
    """Initialize database with Flask app."""
    db.init_app(app)
    with app.app_context():
        db.create_all()
        # Initialize default feature flags and system settings
        FeatureFlag.init_default_flags()
        SystemSetting.init_defaults()
        print("Database initialized successfully!")
