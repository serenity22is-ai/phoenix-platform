"""
MYSTES Database Models

Tables:
- User: User accounts with authentication
- Deal: Cached flight deals
- Payment: XRP payment records
- Booking: User booking history
"""

import json
from datetime import datetime, timedelta, date
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
    is_helper_node = db.Column(db.Boolean, default=False)  # Opted in as residential proxy node

    # Seller onboarding attribution (which deal link brought them to Mystes)
    onboarded_from_deal_id = db.Column(db.Integer, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)

    # MYSTES AI tier (Build #72)
    ai_tier = db.Column(db.String(30), default='ai_free')
    ai_queries_used_this_month = db.Column(db.Integer, default=0)
    ai_month_reset_date = db.Column(db.DateTime, nullable=True)
    last_comparison_date = db.Column(db.Date, nullable=True)  # Build #73: daily comparison quota

    # XRPL wallet (auto-generated on signup — Build #75)
    xrpl_wallet_address = db.Column(db.String(100), unique=True, nullable=True)
    xrpl_wallet_seed_encrypted = db.Column(db.Text, nullable=True)
    xrpl_wallet_created_at = db.Column(db.DateTime, nullable=True)

    # Node referral (Build #75)
    node_referral_code = db.Column(db.String(20), unique=True, nullable=True, index=True)
    total_node_referrals = db.Column(db.Integer, default=0)
    active_node_referrals = db.Column(db.Integer, default=0)

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
        self.verification_token_expires = datetime.utcnow() + timedelta(hours=24)
        return self.verification_token

    def verify_email(self, token):
        """Verify email with token."""
        if (self.verification_token == token and
            self.verification_token_expires and
            self.verification_token_expires > datetime.utcnow()):
            self.is_verified = True
            self.verification_token = None
            self.verification_token_expires = None
            return True
        return False

    def generate_reset_token(self):
        """Generate password reset token."""
        import secrets
        self.reset_token = secrets.token_urlsafe(32)
        self.reset_token_expires = datetime.utcnow() + timedelta(hours=1)
        return self.reset_token

    def reset_password(self, token, new_password):
        """Reset password with token."""
        if (self.reset_token == token and
            self.reset_token_expires and
            self.reset_token_expires > datetime.utcnow()):
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
    expires_at = db.Column(db.DateTime)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Amadeus booking data (raw offer JSON for price_confirm + create_booking)
    amadeus_offer_data = db.Column(db.Text, nullable=True)

    # Payment compatibility (Build #85)
    payment_compatibility = db.Column(db.Text, nullable=True)  # JSON: accepted payment types for deal market

    # Hotel-specific fields (nullable — only populated for hotel deals)
    hotel_name = db.Column(db.String(300), nullable=True)
    hotel_id = db.Column(db.String(50), nullable=True)
    hotel_offer_id = db.Column(db.String(100), nullable=True)
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

    def to_dict(self):
        result = {
            'deal_id': self.deal_id,
            'deal_type': self.deal_type or 'flight',
            'airline': self.airline,
            'flight_number': self.flight_number,
            'route': f"{self.origin} → {self.destination}",
            'departure_date': self.departure_date.isoformat() if self.departure_date else None,
            'departure_time': self.departure_time,
            'home_market': self.home_market,
            'home_price_usd': self.home_price_usd,
            'arbitrage_market': self.arbitrage_market,
            'arbitrage_price_usd': self.arbitrage_price_usd,
            'gross_savings_usd': self.gross_savings_usd,
            'platform_fee_usd': self.platform_fee_usd,
            'platform_fee_xrp': self.platform_fee_xrp,
            'user_savings_usd': self.user_savings_usd,
            'savings_percent': self.savings_percent,
            'destination_tag': self.destination_tag,
            'booking_url': self.booking_url,
            'is_active': self.is_active,
            'is_multi_leg': self.is_multi_leg,
            'total_legs': self.total_legs,
        }
        if self.is_multi_leg:
            result['flight_legs'] = self.get_flight_legs()
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
    # pending, processing, verified, expired, refunded, failed

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
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

    # Hotel-specific booking fields
    guest_title = db.Column(db.String(10), nullable=True)  # MR/MS/MRS
    check_in_date = db.Column(db.Date, nullable=True)
    check_out_date = db.Column(db.Date, nullable=True)
    special_requests = db.Column(db.Text, nullable=True)
    hotel_confirmation_id = db.Column(db.String(100), nullable=True)
    provider_reference = db.Column(db.String(100), nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    booked_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)

    # Relationship
    payment = db.relationship('Payment', backref='booking', uselist=False)

    def to_dict(self):
        return {
            'id': self.id,
            'deal_id': self.deal_id,
            'passenger_name': self.passenger_name,
            'confirmation_code': self.confirmation_code,
            'status': self.status,
            'vendor_payment_status': self.vendor_payment_status,
            'fulfillment_type': self.fulfillment_type,
            'eticket_url': self.eticket_url,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'booked_at': self.booked_at.isoformat() if self.booked_at else None,
        }


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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
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


# --- P2P NETWORK MODELS ---

class HelperProfile(db.Model):
    """
    P2P helper profile — users who earn by granting Mystes browser access.
    Extends the base User model with helper-specific fields.
    """
    __tablename__ = 'helper_profiles'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False, index=True)

    # Helper status
    is_active = db.Column(db.Boolean, default=False)  # Currently accepting requests
    is_approved = db.Column(db.Boolean, default=False)  # Platform-approved
    is_online = db.Column(db.Boolean, default=False)  # App running, browser available

    # Location / market
    country_code = db.Column(db.String(2), nullable=False, index=True)  # e.g., "ES", "UK", "JP"
    zone_code = db.Column(db.String(10), nullable=True, index=True)  # e.g., "US-NE", "JP-KT" — sub-regional zone
    city = db.Column(db.String(100))
    timezone = db.Column(db.String(50))

    # Google account (for price discovery + booking)
    google_account_linked = db.Column(db.Boolean, default=False)

    # Performance stats
    total_transactions = db.Column(db.Integer, default=0)
    successful_transactions = db.Column(db.Integer, default=0)
    failed_transactions = db.Column(db.Integer, default=0)
    total_earned_rlusd = db.Column(db.Float, default=0.0)
    average_rating = db.Column(db.Float, default=5.0)

    # Availability preferences
    available_hours_start = db.Column(db.Integer, default=0)  # 0-23
    available_hours_end = db.Column(db.Integer, default=24)  # 0-24
    max_daily_transactions = db.Column(db.Integer, default=10)
    transactions_today = db.Column(db.Integer, default=0)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_active = db.Column(db.DateTime)
    last_transaction = db.Column(db.DateTime)

    # Node service / extension fields (Build #67)
    helper_token = db.Column(db.String(100), nullable=True, unique=True, index=True)
    node_id = db.Column(db.String(50), nullable=True)
    last_seen = db.Column(db.DateTime, nullable=True)

    # Fleet membership (Build #75)
    fleet_id = db.Column(db.String(50), nullable=True, index=True)

    # Relationships
    user = db.relationship('User', backref=db.backref('helper_profile', uselist=False))
    transactions = db.relationship('P2PTransaction', backref='helper', lazy='dynamic',
                                   foreign_keys='P2PTransaction.helper_id')

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'country_code': self.country_code,
            'city': self.city,
            'is_active': self.is_active,
            'is_online': self.is_online,
            'total_transactions': self.total_transactions,
            'successful_transactions': self.successful_transactions,
            'total_earned_rlusd': self.total_earned_rlusd,
            'average_rating': self.average_rating,
            'last_active': self.last_active.isoformat() if self.last_active else None,
            'helper_token': self.helper_token,
            'node_id': self.node_id,
            'last_seen': self.last_seen.isoformat() if self.last_seen else None,
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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


class P2PTransaction(db.Model):
    """
    P2P booking transaction — tracks the full lifecycle of a P2P purchase.

    Flow:
    1. Buyer requests booking → status: requested
    2. Helper matched → status: matched
    3. Buyer RLUSD locked in escrow → status: escrow_locked
    4. Helper verifies escrow on-chain → status: helper_accepted
    5. Mystes automates purchase on helper's browser → status: purchasing
    6. Booking confirmed → status: confirmed
    7. Escrow releases to helper + platform → status: completed
    """
    __tablename__ = 'p2p_transactions'

    id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(db.String(50), unique=True, nullable=False, index=True)

    # Participants
    buyer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    helper_id = db.Column(db.Integer, db.ForeignKey('helper_profiles.id'), index=True)

    # Flight details
    origin = db.Column(db.String(10))
    destination = db.Column(db.String(10))
    departure_date = db.Column(db.Date)
    airline = db.Column(db.String(50))
    flight_number = db.Column(db.String(20))

    # Pricing
    us_price_usd = db.Column(db.Float)  # Price in buyer's market
    target_price_usd = db.Column(db.Float)  # Price in helper's market
    target_price_local = db.Column(db.Float)  # Price in local currency
    target_currency = db.Column(db.String(3))
    target_market = db.Column(db.String(2))  # Market code (ES, UK, etc.)
    savings_usd = db.Column(db.Float)

    # Escrow details
    escrow_amount_rlusd = db.Column(db.Float)  # Total locked in escrow
    helper_reimbursement_rlusd = db.Column(db.Float)  # Ticket cost reimbursed to helper
    helper_earning_rlusd = db.Column(db.Float)  # Helper's cut
    platform_fee_rlusd = db.Column(db.Float)  # Mystes fee
    escrow_tx_hash = db.Column(db.String(100))  # XRPL escrow create tx
    escrow_release_tx_hash = db.Column(db.String(100))  # XRPL escrow finish tx
    escrow_sequence = db.Column(db.Integer)  # XRPL escrow sequence

    # On-chain verification
    escrow_verified_by_helper = db.Column(db.Boolean, default=False)
    escrow_verified_at = db.Column(db.DateTime)

    # Booking result
    confirmation_code = db.Column(db.String(50))
    passenger_name = db.Column(db.String(100))
    passenger_email = db.Column(db.String(255))
    eticket_url = db.Column(db.String(500))

    # Status
    status = db.Column(db.String(30), default='requested', index=True)
    # requested, matched, escrow_locked, helper_accepted, purchasing,
    # confirmed, completed, failed, cancelled, disputed

    failure_reason = db.Column(db.Text)

    # Browser session (for remote control)
    browser_session_id = db.Column(db.String(100))

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    matched_at = db.Column(db.DateTime)
    escrow_locked_at = db.Column(db.DateTime)
    purchase_started_at = db.Column(db.DateTime)
    confirmed_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    cancelled_at = db.Column(db.DateTime)

    # Relationships
    buyer = db.relationship('User', backref=db.backref('p2p_purchases', lazy='dynamic'))

    def to_dict(self):
        return {
            'transaction_id': self.transaction_id,
            'status': self.status,
            'origin': self.origin,
            'destination': self.destination,
            'departure_date': self.departure_date.isoformat() if self.departure_date else None,
            'airline': self.airline,
            'us_price_usd': self.us_price_usd,
            'target_price_usd': self.target_price_usd,
            'target_market': self.target_market,
            'savings_usd': self.savings_usd,
            'escrow_amount_rlusd': self.escrow_amount_rlusd,
            'helper_earning_rlusd': self.helper_earning_rlusd,
            'confirmation_code': self.confirmation_code,
            'escrow_tx_hash': self.escrow_tx_hash,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
        }


class P2PEscrow(db.Model):
    """
    P2P-specific XRPL escrow for three-party transactions.
    Extends the base Escrow model with P2P-specific fields.

    Unlike standard escrow (buyer → platform), P2P escrow releases to:
    - Helper wallet (reimbursement + earning cut)
    - Platform wallet (fee)
    """
    __tablename__ = 'p2p_escrows'

    id = db.Column(db.Integer, primary_key=True)
    escrow_id = db.Column(db.String(50), unique=True, nullable=False, index=True)

    # References
    p2p_transaction_id = db.Column(db.Integer, db.ForeignKey('p2p_transactions.id'), index=True)

    # Participants
    buyer_address = db.Column(db.String(100), nullable=False)  # Buyer's XRPL wallet
    helper_address = db.Column(db.String(100))  # Helper's XRPL wallet (set on match)
    platform_address = db.Column(db.String(100), nullable=False)  # Mystes wallet

    # Amounts
    total_rlusd = db.Column(db.Float, nullable=False)  # Total locked
    helper_amount_rlusd = db.Column(db.Float)  # Reimbursement + cut for helper
    platform_amount_rlusd = db.Column(db.Float)  # Platform fee

    # XRPL transaction details
    create_tx_hash = db.Column(db.String(100))
    create_sequence = db.Column(db.Integer)
    condition = db.Column(db.String(200))
    fulfillment = db.Column(db.String(200))

    # Release transactions (two payments on escrow finish)
    helper_release_tx_hash = db.Column(db.String(100))
    platform_release_tx_hash = db.Column(db.String(100))

    # Cancel transaction
    cancel_tx_hash = db.Column(db.String(100))

    # Timing
    cancel_after = db.Column(db.DateTime)
    finish_after = db.Column(db.DateTime)

    # On-chain verification
    on_chain_verified = db.Column(db.Boolean, default=False)
    ledger_index = db.Column(db.Integer)  # XRPL ledger index for verification

    # Status: pending, locked, released, cancelled, expired, disputed
    status = db.Column(db.String(20), default='pending', index=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    locked_at = db.Column(db.DateTime)
    released_at = db.Column(db.DateTime)
    cancelled_at = db.Column(db.DateTime)

    # Relationships
    p2p_transaction = db.relationship('P2PTransaction',
                                      backref=db.backref('escrow', uselist=False))

    def to_dict(self):
        return {
            'escrow_id': self.escrow_id,
            'status': self.status,
            'buyer_address': self.buyer_address,
            'helper_address': self.helper_address,
            'total_rlusd': self.total_rlusd,
            'helper_amount_rlusd': self.helper_amount_rlusd,
            'platform_amount_rlusd': self.platform_amount_rlusd,
            'create_tx_hash': self.create_tx_hash,
            'on_chain_verified': self.on_chain_verified,
            'cancel_after': self.cancel_after.isoformat() if self.cancel_after else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class Dispute(db.Model):
    """
    Dispute resolution for P2P transactions.

    Flow:
        opened → under_review → (resolved_buyer | resolved_helper | resolved_split | escalated)

    Either buyer or helper can open a dispute. Admin reviews evidence and resolves.
    """
    __tablename__ = 'disputes'

    id = db.Column(db.Integer, primary_key=True)
    dispute_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    p2p_transaction_id = db.Column(db.Integer, db.ForeignKey('p2p_transactions.id'), index=True)

    # Parties
    opened_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    assigned_admin_id = db.Column(db.Integer, db.ForeignKey('users.id'))

    # Dispute details
    reason = db.Column(db.String(50), nullable=False)  # wrong_ticket, no_ticket, price_mismatch, fraud, other
    description = db.Column(db.Text, nullable=False)
    evidence_urls = db.Column(db.Text)  # JSON list of uploaded evidence URLs

    # Resolution
    status = db.Column(db.String(30), default='opened', nullable=False, index=True)
    resolution_type = db.Column(db.String(30))  # resolved_buyer, resolved_helper, resolved_split, escalated
    resolution_notes = db.Column(db.Text)
    refund_amount_rlusd = db.Column(db.Float)
    refund_tx_hash = db.Column(db.String(100))

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    resolved_at = db.Column(db.DateTime)

    # Relationships
    p2p_transaction = db.relationship('P2PTransaction', backref='disputes')
    opened_by = db.relationship('User', foreign_keys=[opened_by_user_id], backref='disputes_opened')
    assigned_admin = db.relationship('User', foreign_keys=[assigned_admin_id])

    def to_dict(self):
        return {
            'dispute_id': self.dispute_id,
            'transaction_id': self.p2p_transaction.transaction_id if self.p2p_transaction else None,
            'reason': self.reason,
            'description': self.description,
            'status': self.status,
            'resolution_type': self.resolution_type,
            'resolution_notes': self.resolution_notes,
            'refund_amount_rlusd': self.refund_amount_rlusd,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None,
        }


class DisputeMessage(db.Model):
    """Messages in a dispute thread (buyer, helper, or admin)."""
    __tablename__ = 'dispute_messages'

    id = db.Column(db.Integer, primary_key=True)
    dispute_id = db.Column(db.Integer, db.ForeignKey('disputes.id'), nullable=False, index=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    message = db.Column(db.Text, nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    attachment_url = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    dispute = db.relationship('Dispute', backref='messages')
    sender = db.relationship('User')

    def to_dict(self):
        return {
            'sender_id': self.sender_id,
            'sender_name': self.sender.username if self.sender else None,
            'message': self.message,
            'is_admin': self.is_admin,
            'attachment_url': self.attachment_url,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


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

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

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
    - Referred users can become P2P helper nodes, expanding the network
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
    total_referred_helpers = db.Column(db.Integer, default=0)  # How many referred users became helper nodes

    # SERP API tier
    serp_tier = db.Column(db.String(20), default='serp_free')
    serp_monthly_credits = db.Column(db.Integer, default=100)
    serp_credits_used_this_month = db.Column(db.Float, default=0.0)
    serp_month_reset_date = db.Column(db.DateTime, nullable=True)

    # Browsing Data tier (Build #70)
    browsing_tier = db.Column(db.String(30), default='browsing_free')
    browsing_events_used_this_month = db.Column(db.Integer, default=0)
    browsing_month_reset_date = db.Column(db.DateTime, nullable=True)

    # Data Marketplace tier (Build #74)
    data_marketplace_tier = db.Column(db.String(30), default='data_free')
    data_queries_used_this_month = db.Column(db.Integer, default=0)
    data_month_reset_date = db.Column(db.DateTime, nullable=True)

    # Access controls
    is_active = db.Column(db.Boolean, default=True)
    p2p_enabled = db.Column(db.Boolean, default=True)
    max_daily_searches = db.Column(db.Integer, default=500)
    max_concurrent_searches = db.Column(db.Integer, default=10)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
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
            'p2p_enabled': self.p2p_enabled,
            'referral_code': self.referral_code,
            'total_referred_users': self.total_referred_users or 0,
            'total_referred_helpers': self.total_referred_helpers or 0,
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
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

    # Reference to the underlying booking/P2P transaction
    booking_id = db.Column(db.Integer, db.ForeignKey('bookings.id'))
    p2p_transaction_id = db.Column(db.Integer, db.ForeignKey('p2p_transactions.id'))

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

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
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

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
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

    generated_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

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

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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

    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

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

    calculated_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

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


# ============================================================
# CitizenSERP Node Payout Models
# ============================================================

class NodeSession(db.Model):
    """Individual node uptime session. Tracks when a residential proxy node goes online/offline."""
    __tablename__ = 'node_sessions'

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # Session timing
    start_time = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    end_time = db.Column(db.DateTime, nullable=True)
    duration_minutes = db.Column(db.Float, nullable=True)

    # Node identity
    wallet_address = db.Column(db.String(100), nullable=False)
    ip_country = db.Column(db.String(2), nullable=True, index=True)
    ip_zone = db.Column(db.String(10), nullable=True, index=True)  # e.g., "US-NE" — sub-regional zone

    # On-chain attestation
    xrpl_attestation_tx = db.Column(db.String(100), nullable=True)
    attestation_ledger_index = db.Column(db.Integer, nullable=True)

    # Status: active, closed, stale
    status = db.Column(db.String(20), default='active', index=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('node_sessions', lazy='dynamic'))

    __table_args__ = (
        db.Index('ix_node_sessions_user_status', 'user_id', 'status'),
        db.Index('ix_node_sessions_start_end', 'start_time', 'end_time'),
    )

    def to_dict(self):
        return {
            'session_id': self.session_id,
            'user_id': self.user_id,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'duration_minutes': round(self.duration_minutes, 1) if self.duration_minutes else None,
            'ip_country': self.ip_country,
            'status': self.status,
            'xrpl_attestation_tx': self.xrpl_attestation_tx,
        }


class NodePayoutEpoch(db.Model):
    """A single payout period (daily). Captures revenue pool and distribution metrics."""
    __tablename__ = 'node_payout_epochs'

    id = db.Column(db.Integer, primary_key=True)
    epoch_id = db.Column(db.String(50), unique=True, nullable=False, index=True)

    # Period
    period_start = db.Column(db.DateTime, nullable=False)
    period_end = db.Column(db.DateTime, nullable=False)

    # Revenue pool
    total_revenue_pool_usd = db.Column(db.Float, nullable=False)
    payout_percentage = db.Column(db.Float, nullable=False)
    total_payout_pool_usd = db.Column(db.Float, nullable=False)

    # Distribution metrics
    total_node_hours = db.Column(db.Float, nullable=False)
    rate_per_hour_usd = db.Column(db.Float, nullable=False)
    nodes_paid = db.Column(db.Integer, default=0)

    # Status: calculating, calculated, distributing, completed, failed
    status = db.Column(db.String(20), default='calculating', index=True)

    distribution_tx_batch = db.Column(db.String(100), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            'epoch_id': self.epoch_id,
            'period_start': self.period_start.isoformat() if self.period_start else None,
            'period_end': self.period_end.isoformat() if self.period_end else None,
            'total_revenue_pool_usd': round(self.total_revenue_pool_usd, 2),
            'payout_percentage': self.payout_percentage,
            'total_payout_pool_usd': round(self.total_payout_pool_usd, 2),
            'total_node_hours': round(self.total_node_hours, 1),
            'rate_per_hour_usd': round(self.rate_per_hour_usd, 6),
            'nodes_paid': self.nodes_paid,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
        }


class NodePayout(db.Model):
    """Individual payout record per node per epoch."""
    __tablename__ = 'node_payouts'

    id = db.Column(db.Integer, primary_key=True)
    epoch_id = db.Column(db.Integer, db.ForeignKey('node_payout_epochs.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    wallet_address = db.Column(db.String(100), nullable=False)
    uptime_hours = db.Column(db.Float, nullable=False)
    payout_amount_rlusd = db.Column(db.Float, nullable=False)

    # XRPL transaction
    tx_hash = db.Column(db.String(100), nullable=True)
    status = db.Column(db.String(20), default='pending', index=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    paid_at = db.Column(db.DateTime, nullable=True)

    epoch = db.relationship('NodePayoutEpoch', backref=db.backref('payouts', lazy='dynamic'))
    user = db.relationship('User', backref=db.backref('node_payouts', lazy='dynamic'))

    __table_args__ = (
        db.Index('ix_node_payouts_epoch_user', 'epoch_id', 'user_id', unique=True),
    )

    def to_dict(self):
        return {
            'epoch_id': self.epoch_id,
            'user_id': self.user_id,
            'wallet_address': self.wallet_address,
            'uptime_hours': round(self.uptime_hours, 2),
            'payout_amount_rlusd': round(self.payout_amount_rlusd, 6),
            'tx_hash': self.tx_hash,
            'status': self.status,
            'paid_at': self.paid_at.isoformat() if self.paid_at else None,
        }


# ============================================================
# Node Data Extraction Tracking (Build #65)
# ============================================================

class NodeDataExtraction(db.Model):
    """Per-task data extraction record — tracks what data categories
    a node extracted during a task and the commercial value attributed.
    Links to NodeSession for per-session yield visibility."""
    __tablename__ = 'node_data_extractions'

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('node_sessions.id'), nullable=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    task_id = db.Column(db.String(50), nullable=False, index=True)
    task_type = db.Column(db.String(50), nullable=False, index=True)

    # Data category extracted
    # Categories: "flight_pricing", "hotel_pricing", "product_pricing",
    # "ad_intelligence", "social_signals", "audience_data",
    # "retail_shelf", "competitor_ads", "deep_pricing", "search_results"
    data_category = db.Column(db.String(50), nullable=False, index=True)

    # Volume metrics
    records_extracted = db.Column(db.Integer, default=0)
    data_points = db.Column(db.Integer, default=0)
    data_size_bytes = db.Column(db.Integer, default=0)

    # Commercial value attribution
    commercial_value_usd = db.Column(db.Float, default=0.0)
    payout_multiplier = db.Column(db.Float, default=1.0)
    payout_earned_rlusd = db.Column(db.Float, default=0.0)

    # Quality score (0-100)
    quality_score = db.Column(db.Integer, default=50)

    # Extraction metadata (JSON)
    extraction_metadata = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    session = db.relationship('NodeSession', backref=db.backref('data_extractions', lazy='dynamic'))
    user = db.relationship('User', backref=db.backref('data_extractions', lazy='dynamic'))

    __table_args__ = (
        db.Index('ix_node_data_ext_user_category', 'user_id', 'data_category'),
        db.Index('ix_node_data_ext_created', 'created_at'),
    )

    def to_dict(self):
        return {
            'task_id': self.task_id,
            'task_type': self.task_type,
            'data_category': self.data_category,
            'records_extracted': self.records_extracted,
            'data_points': self.data_points,
            'data_size_bytes': self.data_size_bytes,
            'commercial_value_usd': round(self.commercial_value_usd, 4),
            'payout_multiplier': self.payout_multiplier,
            'payout_earned_rlusd': round(self.payout_earned_rlusd, 6),
            'quality_score': self.quality_score,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class AdIntelligenceRecord(db.Model):
    """Individual ad intelligence data point extracted by a node.
    Stores normalized ad data with commercial value attribution for
    the ad intelligence pipeline and commercial API."""
    __tablename__ = 'ad_intelligence_records'

    id = db.Column(db.Integer, primary_key=True)
    record_id = db.Column(db.String(50), unique=True, nullable=False, index=True)

    # Source
    task_id = db.Column(db.String(50), nullable=False, index=True)
    node_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    market = db.Column(db.String(5), nullable=False, index=True)
    source_url = db.Column(db.String(500), nullable=True)

    # Ad data
    advertiser = db.Column(db.String(200), nullable=True, index=True)
    ad_network = db.Column(db.String(100), nullable=True, index=True)
    ad_format = db.Column(db.String(50), nullable=True)  # display, search, video, native, shopping
    ad_position = db.Column(db.String(50), nullable=True)  # top, sidebar, inline, bottom
    ad_text = db.Column(db.Text, nullable=True)
    ad_destination_url = db.Column(db.String(500), nullable=True)
    ad_image_hash = db.Column(db.String(64), nullable=True)  # SHA256 of ad creative

    # Bid / targeting signals
    estimated_bid_usd = db.Column(db.Float, nullable=True)
    targeting_keywords = db.Column(db.Text, nullable=True)  # JSON list
    targeting_demographics = db.Column(db.Text, nullable=True)  # JSON
    targeting_geo = db.Column(db.String(50), nullable=True)

    # Vertical / industry
    vertical = db.Column(db.String(50), nullable=True, index=True)
    sub_vertical = db.Column(db.String(50), nullable=True)

    # Commercial value
    commercial_value_usd = db.Column(db.Float, default=0.0)
    is_sold = db.Column(db.Boolean, default=False)

    # Quality / confidence
    confidence_score = db.Column(db.Float, default=0.5)

    # Timestamps
    observed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    node_user = db.relationship('User', backref=db.backref('ad_extractions', lazy='dynamic'))

    __table_args__ = (
        db.Index('ix_ad_intel_advertiser_market', 'advertiser', 'market'),
        db.Index('ix_ad_intel_vertical_observed', 'vertical', 'observed_at'),
        db.Index('ix_ad_intel_network_observed', 'ad_network', 'observed_at'),
    )

    def to_dict(self):
        return {
            'record_id': self.record_id,
            'market': self.market,
            'advertiser': self.advertiser,
            'ad_network': self.ad_network,
            'ad_format': self.ad_format,
            'ad_position': self.ad_position,
            'ad_text': self.ad_text,
            'ad_destination_url': self.ad_destination_url,
            'estimated_bid_usd': self.estimated_bid_usd,
            'targeting_keywords': json.loads(self.targeting_keywords) if self.targeting_keywords else [],
            'targeting_demographics': json.loads(self.targeting_demographics) if self.targeting_demographics else {},
            'targeting_geo': self.targeting_geo,
            'vertical': self.vertical,
            'sub_vertical': self.sub_vertical,
            'commercial_value_usd': round(self.commercial_value_usd, 4),
            'is_sold': self.is_sold,
            'confidence_score': self.confidence_score,
            'observed_at': self.observed_at.isoformat() if self.observed_at else None,
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
    observed_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

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
    observed_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

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
    observed_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

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
    observed_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

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
    observed_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

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


class BrowsingEvent(db.Model):
    """
    Browser extension event — passive data captured from node browsing.
    Events flow: extension → local service → backend API → processor → hooks.
    """
    __tablename__ = 'browsing_events'

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    node_id = db.Column(db.String(50), nullable=True, index=True)
    session_id = db.Column(db.String(50), nullable=True)

    # Event classification
    event_type = db.Column(db.String(30), nullable=False)  # page_visit | search_query | ad_impression | price_observation | social_signal
    url = db.Column(db.String(2000), nullable=True)
    domain = db.Column(db.String(200), nullable=True, index=True)
    title = db.Column(db.String(500), nullable=True)
    event_data = db.Column(db.Text, nullable=True)  # JSON payload

    # Processing state
    is_processed = db.Column(db.Boolean, server_default='0')
    processing_result = db.Column(db.String(20), nullable=True)  # routed | duplicate | low_quality | error

    # Commercial value
    commercial_value_usd = db.Column(db.Float, server_default='0.0')
    data_category = db.Column(db.String(50), nullable=True)
    quality_score = db.Column(db.Integer, server_default='50')

    # Timestamps
    captured_at = db.Column(db.DateTime, nullable=True)  # When extension captured it
    ingested_at = db.Column(db.DateTime, default=datetime.utcnow)  # When backend received it
    processed_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.Index('ix_browsing_evt_user_type', 'user_id', 'event_type'),
        db.Index('ix_browsing_evt_captured', 'captured_at'),
        db.Index('ix_browsing_evt_processed', 'is_processed', 'ingested_at'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'event_id': self.event_id,
            'user_id': self.user_id,
            'node_id': self.node_id,
            'event_type': self.event_type,
            'url': self.url,
            'domain': self.domain,
            'title': self.title,
            'is_processed': self.is_processed,
            'processing_result': self.processing_result,
            'commercial_value_usd': self.commercial_value_usd,
            'data_category': self.data_category,
            'quality_score': self.quality_score,
            'captured_at': self.captured_at.isoformat() if self.captured_at else None,
            'ingested_at': self.ingested_at.isoformat() if self.ingested_at else None,
            'processed_at': self.processed_at.isoformat() if self.processed_at else None,
        }


class DataQualityFeedback(db.Model):
    """
    Commercial buyer feedback on browsing data quality (Build #69).
    Links back to BrowsingEvent via event_id and tracks per-node ratings.
    """
    __tablename__ = 'data_quality_feedback'

    id = db.Column(db.Integer, primary_key=True)
    feedback_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    event_id = db.Column(db.String(50), db.ForeignKey('browsing_events.event_id'), nullable=False)
    account_id = db.Column(db.Integer, nullable=False, index=True)
    node_id = db.Column(db.String(50), nullable=True, index=True)
    rating = db.Column(db.String(10), nullable=False)  # good, neutral, poor
    comment = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.Index('ix_dqf_event_id', 'event_id'),
        db.Index('ix_dqf_node_rating', 'node_id', 'rating'),
    )


class ProxySession(db.Model):
    """User proxy session for cross-market browsing via the Proxy Portal."""
    __tablename__ = 'proxy_sessions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    country_code = db.Column(db.String(5), nullable=False)
    target_site = db.Column(db.String(200), nullable=True)

    # Proxy connection details
    proxy_host = db.Column(db.String(200), nullable=False)
    proxy_port = db.Column(db.String(10), nullable=False)
    proxy_username = db.Column(db.String(200), nullable=False)
    proxy_password = db.Column(db.String(200), nullable=False)
    protocol = db.Column(db.String(10), default='socks5')

    # Lifecycle
    status = db.Column(db.String(20), default='active', index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    ended_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User', backref=db.backref('proxy_sessions', lazy='dynamic'))

    __table_args__ = (
        db.Index('ix_proxy_sessions_user_status', 'user_id', 'status'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'country_code': self.country_code,
            'target_site': self.target_site,
            'proxy_host': self.proxy_host,
            'proxy_port': self.proxy_port,
            'proxy_username': self.proxy_username,
            'protocol': self.protocol,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'ended_at': self.ended_at.isoformat() if self.ended_at else None,
        }

    @property
    def is_expired(self):
        return datetime.utcnow() > self.expires_at if self.expires_at else False


# ---------------------------------------------------------------------------
# Build #90 — Free Browse Sessions (node-based, replaces Webshare proxies)
# ---------------------------------------------------------------------------

class BrowseSession(db.Model):
    """User browse session through a CitizenSERP node.

    The user opens their own browser through the Mystes portal into a
    network node.  Mystes acts as a monitoring window — passively observing
    data (price observations, search queries, ad impressions) at zero cost.
    Browsing is unlimited; no quota is consumed.
    """
    __tablename__ = 'browse_sessions'

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    node_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    zone_code = db.Column(db.String(10), nullable=False, index=True)
    country_code = db.Column(db.String(5), nullable=True)
    target_site = db.Column(db.String(200), nullable=True)

    # Session type — 'free_browse' (unmetered) for now; extensible later
    session_type = db.Column(db.String(20), default='free_browse')

    # Lifecycle
    status = db.Column(db.String(20), default='active', index=True)
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    ended_at = db.Column(db.DateTime, nullable=True)
    last_activity = db.Column(db.DateTime, default=datetime.utcnow)
    duration_seconds = db.Column(db.Integer, nullable=True)

    # Data generated during session (passive monitoring)
    events_captured = db.Column(db.Integer, default=0)
    data_value_usd = db.Column(db.Float, default=0.0)
    pages_visited = db.Column(db.Integer, default=0)
    price_observations_count = db.Column(db.Integer, default=0)

    # Relationships
    user = db.relationship('User', foreign_keys=[user_id],
                           backref=db.backref('browse_sessions', lazy='dynamic'))
    node_user = db.relationship('User', foreign_keys=[node_user_id])

    __table_args__ = (
        db.Index('ix_browse_sessions_user_status', 'user_id', 'status'),
        db.Index('ix_browse_sessions_node_status', 'node_user_id', 'status'),
        db.Index('ix_browse_sessions_zone', 'zone_code', 'status'),
    )

    def to_dict(self):
        return {
            'session_id': self.session_id,
            'zone_code': self.zone_code,
            'country_code': self.country_code,
            'target_site': self.target_site,
            'session_type': self.session_type,
            'status': self.status,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'ended_at': self.ended_at.isoformat() if self.ended_at else None,
            'last_activity': self.last_activity.isoformat() if self.last_activity else None,
            'duration_seconds': self.duration_seconds,
            'events_captured': self.events_captured,
            'data_value_usd': round(self.data_value_usd or 0, 4),
            'pages_visited': self.pages_visited,
            'price_observations_count': self.price_observations_count,
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_message_at = db.Column(db.DateTime, default=datetime.utcnow)

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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


class PrivateMarketDeal(db.Model):
    """Private market deal with XRPL escrow — trustless P2P transactions."""
    __tablename__ = 'private_market_deals'

    id = db.Column(db.Integer, primary_key=True)
    buyer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    seller_wallet = db.Column(db.String(100), nullable=True)  # Nullable: set when seller accepts link
    item_description = db.Column(db.Text, nullable=False)
    agreed_price_rlusd = db.Column(db.Float, nullable=False)
    market = db.Column(db.String(5), nullable=True)
    deal_type = db.Column(db.String(20), default='goods')  # goods, services, vehicle, other

    # Deal link (shareable P2P link for sellers without Mystes accounts)
    link_token = db.Column(db.String(64), unique=True, nullable=True, index=True)
    seller_email = db.Column(db.String(256), nullable=True)
    seller_name = db.Column(db.String(200), nullable=True)
    link_expires_at = db.Column(db.DateTime, nullable=True)
    seller_accepted_at = db.Column(db.DateTime, nullable=True)
    link_viewed_at = db.Column(db.DateTime, nullable=True)

    # XRPL escrow
    escrow_tx_hash = db.Column(db.String(200), nullable=True)
    escrow_sequence = db.Column(db.Integer, nullable=True)
    escrow_condition = db.Column(db.String(500), nullable=True)
    escrow_fulfillment = db.Column(db.String(500), nullable=True)

    # Fees and AI assessment
    escrow_fee_rlusd = db.Column(db.Float, default=0.0)
    ai_fair_value_estimate = db.Column(db.Float, nullable=True)
    risk_score = db.Column(db.Integer, default=5)  # 1-10, 10 = highest risk

    # Status
    status = db.Column(db.String(20), default='draft', index=True)
    # draft → link_sent → seller_accepted → escrow_funded → delivered → completed
    # draft → cancelled | link_sent → expired
    # escrow_funded → disputed → completed/cancelled

    # Deadlines
    delivery_deadline = db.Column(db.DateTime, nullable=True)
    dispute_window_end = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)

    buyer = db.relationship('User', backref=db.backref('private_deals', lazy='dynamic'))

    __table_args__ = (
        db.Index('ix_private_deals_buyer_status', 'buyer_id', 'status'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'buyer_id': self.buyer_id,
            'seller_wallet': self.seller_wallet,
            'seller_email': self.seller_email,
            'seller_name': self.seller_name,
            'item_description': self.item_description,
            'agreed_price_rlusd': self.agreed_price_rlusd,
            'market': self.market,
            'deal_type': self.deal_type,
            'escrow_tx_hash': self.escrow_tx_hash,
            'escrow_fee_rlusd': self.escrow_fee_rlusd,
            'ai_fair_value_estimate': self.ai_fair_value_estimate,
            'risk_score': self.risk_score,
            'status': self.status,
            'link_token': self.link_token,
            'link_url': f"/deal/link/{self.link_token}" if self.link_token else None,
            'link_expires_at': self.link_expires_at.isoformat() if self.link_expires_at else None,
            'is_link_expired': (self.link_expires_at < datetime.utcnow()) if self.link_expires_at else False,
            'link_viewed_at': self.link_viewed_at.isoformat() if self.link_viewed_at else None,
            'seller_accepted_at': self.seller_accepted_at.isoformat() if self.seller_accepted_at else None,
            'delivery_deadline': self.delivery_deadline.isoformat() if self.delivery_deadline else None,
            'dispute_window_end': self.dispute_window_end.isoformat() if self.dispute_window_end else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
        }


# ============================================================
# SERP API Models
# ============================================================

class SERPAPIQuery(db.Model):
    """Per-query tracking for the residential SERP API service."""
    __tablename__ = 'serp_api_queries'

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('commercial_accounts.id'), nullable=False, index=True)
    query_id = db.Column(db.String(50), unique=True, nullable=False, index=True)

    # Query parameters
    engine = db.Column(db.String(30), nullable=False)
    market = db.Column(db.String(5), nullable=False)
    query_text = db.Column(db.Text, nullable=False)
    options = db.Column(db.Text, nullable=True)  # JSON

    # Credits & status
    credits_used = db.Column(db.Float, nullable=False, default=1.0)
    status = db.Column(db.String(20), nullable=False, default='pending', index=True)
    # pending, processing, completed, failed, expired

    # Result
    result = db.Column(db.Text, nullable=True)  # JSON
    error_message = db.Column(db.Text, nullable=True)

    # Execution metadata
    node_id = db.Column(db.String(50), nullable=True)
    callback_url = db.Column(db.String(500), nullable=True)
    callback_status = db.Column(db.String(20), nullable=True)
    response_time_ms = db.Column(db.Integer, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    account = db.relationship('CommercialAccount', backref=db.backref('serp_queries', lazy='dynamic'))

    __table_args__ = (
        db.Index('ix_serp_queries_account_status', 'account_id', 'status'),
    )

    def to_dict(self):
        return {
            'query_id': self.query_id,
            'engine': self.engine,
            'market': self.market,
            'query_text': self.query_text,
            'options': json.loads(self.options) if self.options else None,
            'credits_used': self.credits_used,
            'status': self.status,
            'result': json.loads(self.result) if self.result else None,
            'error_message': self.error_message,
            'node_id': self.node_id,
            'response_time_ms': self.response_time_ms,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
        }


class SERPAPIUsageSummary(db.Model):
    """Daily usage aggregates for SERP API accounts."""
    __tablename__ = 'serp_api_usage_summaries'

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('commercial_accounts.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)

    # Metrics
    total_queries = db.Column(db.Integer, nullable=False, default=0)
    total_credits = db.Column(db.Float, nullable=False, default=0)
    successful_queries = db.Column(db.Integer, nullable=False, default=0)
    failed_queries = db.Column(db.Integer, nullable=False, default=0)
    avg_response_time_ms = db.Column(db.Integer, nullable=True)

    # Breakdown (JSON)
    engines_used = db.Column(db.Text, nullable=True)
    markets_used = db.Column(db.Text, nullable=True)

    # Relationships
    account = db.relationship('CommercialAccount', backref=db.backref('serp_usage', lazy='dynamic'))

    __table_args__ = (
        db.UniqueConstraint('account_id', 'date', name='uq_serp_usage_account_date'),
    )

    def to_dict(self):
        return {
            'date': self.date.isoformat() if self.date else None,
            'total_queries': self.total_queries,
            'total_credits': round(self.total_credits, 2),
            'successful_queries': self.successful_queries,
            'failed_queries': self.failed_queries,
            'avg_response_time_ms': self.avg_response_time_ms,
            'engines_used': json.loads(self.engines_used) if self.engines_used else [],
            'markets_used': json.loads(self.markets_used) if self.markets_used else [],
        }


# ============================================================
# Data Marketplace Models (Build #74)
# ============================================================

class DataProduct(db.Model):
    """Catalog entry for a sellable data product."""
    __tablename__ = 'data_products'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.String(80), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    category = db.Column(db.String(50), nullable=False, index=True)
    data_source_config = db.Column(db.Text, nullable=False)  # JSON: model, aggregation, etc.
    delivery_formats = db.Column(db.Text, nullable=False)  # JSON: ["json_api", "csv_export", ...]
    pricing_model = db.Column(db.String(30), nullable=False)  # per_query, subscription, per_record
    credit_cost_per_query = db.Column(db.Float, default=1.0)
    min_tier = db.Column(db.String(30), default='data_free')
    sample_limit = db.Column(db.Integer, default=10)
    available_fields = db.Column(db.Text, nullable=True)  # JSON: list of field names
    supported_filters = db.Column(db.Text, nullable=True)  # JSON: list of filter params
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'product_id': self.product_id,
            'name': self.name,
            'description': self.description,
            'category': self.category,
            'delivery_formats': json.loads(self.delivery_formats) if self.delivery_formats else [],
            'pricing_model': self.pricing_model,
            'credit_cost_per_query': self.credit_cost_per_query,
            'min_tier': self.min_tier,
            'sample_limit': self.sample_limit,
            'available_fields': json.loads(self.available_fields) if self.available_fields else [],
            'supported_filters': json.loads(self.supported_filters) if self.supported_filters else [],
            'is_active': self.is_active,
        }


class DataSubscription(db.Model):
    """Links a CommercialAccount to a data marketplace tier + add-ons."""
    __tablename__ = 'data_subscriptions'

    id = db.Column(db.Integer, primary_key=True)
    subscription_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    account_id = db.Column(db.Integer, db.ForeignKey('commercial_accounts.id'), nullable=False, index=True)
    tier = db.Column(db.String(30), nullable=False, default='data_free')
    selected_products = db.Column(db.Text, nullable=True)  # JSON: list of product_ids (starter: max 3)
    addons = db.Column(db.Text, nullable=True)  # JSON: list of addon keys
    queries_used_this_period = db.Column(db.Integer, default=0)
    period_start = db.Column(db.DateTime, nullable=True)
    period_end = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), default='active')  # active, paused, cancelled, expired
    monthly_price_usd = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    account = db.relationship('CommercialAccount', backref=db.backref('data_subscriptions', lazy='dynamic'))

    __table_args__ = (
        db.Index('ix_data_sub_account_status', 'account_id', 'status'),
    )

    def to_dict(self):
        return {
            'subscription_id': self.subscription_id,
            'account_id': self.account_id,
            'tier': self.tier,
            'selected_products': json.loads(self.selected_products) if self.selected_products else [],
            'addons': json.loads(self.addons) if self.addons else [],
            'queries_used_this_period': self.queries_used_this_period,
            'period_start': self.period_start.isoformat() if self.period_start else None,
            'period_end': self.period_end.isoformat() if self.period_end else None,
            'status': self.status,
            'monthly_price_usd': self.monthly_price_usd,
        }


class DataExport(db.Model):
    """Bulk export request for CSV/JSON download."""
    __tablename__ = 'data_exports'

    id = db.Column(db.Integer, primary_key=True)
    export_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    account_id = db.Column(db.Integer, db.ForeignKey('commercial_accounts.id'), nullable=False, index=True)
    product_id = db.Column(db.String(80), nullable=False)
    format = db.Column(db.String(10), nullable=False, default='csv')
    filters = db.Column(db.Text, nullable=True)  # JSON
    status = db.Column(db.String(20), default='pending', index=True)
    total_records = db.Column(db.Integer, nullable=True)
    file_size_bytes = db.Column(db.Integer, nullable=True)
    download_url = db.Column(db.String(500), nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)

    account = db.relationship('CommercialAccount', backref=db.backref('data_exports', lazy='dynamic'))

    def to_dict(self):
        return {
            'export_id': self.export_id,
            'product_id': self.product_id,
            'format': self.format,
            'status': self.status,
            'total_records': self.total_records,
            'file_size_bytes': self.file_size_bytes,
            'download_url': self.download_url,
            'error_message': self.error_message,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
        }


class DataWebhook(db.Model):
    """Webhook subscription for real-time data streaming."""
    __tablename__ = 'data_webhooks'

    id = db.Column(db.Integer, primary_key=True)
    webhook_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    account_id = db.Column(db.Integer, db.ForeignKey('commercial_accounts.id'), nullable=False, index=True)
    product_id = db.Column(db.String(80), nullable=False)
    callback_url = db.Column(db.String(500), nullable=False)
    secret = db.Column(db.String(128), nullable=False)
    filters = db.Column(db.Text, nullable=True)  # JSON
    is_active = db.Column(db.Boolean, default=True)
    consecutive_failures = db.Column(db.Integer, default=0)
    last_delivery_at = db.Column(db.DateTime, nullable=True)
    last_delivery_status = db.Column(db.Integer, nullable=True)
    total_deliveries = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    account = db.relationship('CommercialAccount', backref=db.backref('data_webhooks', lazy='dynamic'))

    def to_dict(self):
        return {
            'webhook_id': self.webhook_id,
            'product_id': self.product_id,
            'callback_url': self.callback_url,
            'filters': json.loads(self.filters) if self.filters else {},
            'is_active': self.is_active,
            'total_deliveries': self.total_deliveries,
            'last_delivery_at': self.last_delivery_at.isoformat() if self.last_delivery_at else None,
            'last_delivery_status': self.last_delivery_status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class DataUsageRecord(db.Model):
    """Per-query usage tracking for data marketplace billing."""
    __tablename__ = 'data_usage_records'

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('commercial_accounts.id'), nullable=False, index=True)
    product_id = db.Column(db.String(80), nullable=False, index=True)
    query_type = db.Column(db.String(20), nullable=False)  # api_query, sample, export, webhook
    records_returned = db.Column(db.Integer, default=0)
    credits_consumed = db.Column(db.Float, default=0.0)
    filters_used = db.Column(db.Text, nullable=True)  # JSON
    response_time_ms = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    account = db.relationship('CommercialAccount', backref=db.backref('data_usage_records', lazy='dynamic'))

    __table_args__ = (
        db.Index('ix_data_usage_account_product', 'account_id', 'product_id'),
        db.Index('ix_data_usage_created', 'created_at'),
    )


class NodeConsentProfile(db.Model):
    """Per-user consent config and tier state. Created on signup. (Build #75)"""
    __tablename__ = 'node_consent_profiles'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False, index=True)
    node_id = db.Column(db.String(50), nullable=True)

    # Data consent toggles
    consent_location = db.Column(db.Boolean, default=True)  # Required baseline
    consent_search_queries = db.Column(db.Boolean, default=False)
    consent_price_observations = db.Column(db.Boolean, default=False)
    consent_ad_impressions = db.Column(db.Boolean, default=False)
    consent_social_signals = db.Column(db.Boolean, default=False)
    consent_browsing_data = db.Column(db.Boolean, default=False)
    consent_business_data = db.Column(db.Boolean, default=False)

    # Tier state
    current_tier = db.Column(db.String(20), default='bronze')
    tier_score = db.Column(db.Float, default=0.0)
    data_share_score = db.Column(db.Float, default=0.0)
    referral_score = db.Column(db.Float, default=0.0)
    quality_score = db.Column(db.Float, default=0.0)
    longevity_score = db.Column(db.Float, default=0.0)

    # Tier benefits (cached from last assessment)
    payout_multiplier = db.Column(db.Float, default=1.0)
    arbitrage_fee_discount = db.Column(db.Float, default=0.0)
    mystes_suite_access = db.Column(db.Boolean, default=False)

    # Background service
    background_service_enabled = db.Column(db.Boolean, default=False)
    background_service_hours_target = db.Column(db.Integer, default=8)

    # Assessment
    last_tier_assessment = db.Column(db.DateTime, nullable=True)
    next_tier_threshold = db.Column(db.Float, default=25.0)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('consent_profile', uselist=False))

    def to_dict(self):
        return {
            'user_id': self.user_id,
            'node_id': self.node_id,
            'consent': {
                'location': self.consent_location,
                'search_queries': self.consent_search_queries,
                'price_observations': self.consent_price_observations,
                'ad_impressions': self.consent_ad_impressions,
                'social_signals': self.consent_social_signals,
                'browsing_data': self.consent_browsing_data,
                'business_data': self.consent_business_data,
            },
            'tier': {
                'current': self.current_tier,
                'score': round(self.tier_score, 2),
                'breakdown': {
                    'data_share': round(self.data_share_score, 2),
                    'referral': round(self.referral_score, 2),
                    'quality': round(self.quality_score, 2),
                    'longevity': round(self.longevity_score, 2),
                },
                'next_threshold': self.next_tier_threshold,
            },
            'benefits': {
                'payout_multiplier': self.payout_multiplier,
                'arbitrage_fee_discount': self.arbitrage_fee_discount,
                'mystes_suite_access': self.mystes_suite_access,
            },
            'last_assessment': self.last_tier_assessment.isoformat() if self.last_tier_assessment else None,
        }


class NodeReferral(db.Model):
    """Per-referral tracking with activation and churn detection. (Build #75)"""
    __tablename__ = 'node_referrals'

    id = db.Column(db.Integer, primary_key=True)
    referral_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    referrer_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    referee_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    referral_code = db.Column(db.String(20), nullable=False, index=True)

    # Activation
    is_activated = db.Column(db.Boolean, default=False)
    activated_at = db.Column(db.DateTime, nullable=True)

    # Performance
    referee_total_earnings = db.Column(db.Float, default=0.0)
    referee_current_tier = db.Column(db.String(20), default='bronze')
    referee_sessions_count = db.Column(db.Integer, default=0)

    # Anti-gaming
    is_churned = db.Column(db.Boolean, default=False)
    churned_at = db.Column(db.DateTime, nullable=True)
    clawback_applied = db.Column(db.Boolean, default=False)

    # Bonus
    activation_bonus_paid = db.Column(db.Boolean, default=False)
    activation_bonus_amount = db.Column(db.Float, default=0.50)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    referrer = db.relationship('User', foreign_keys=[referrer_user_id], backref=db.backref('referrals_made', lazy='dynamic'))
    referee = db.relationship('User', foreign_keys=[referee_user_id], backref=db.backref('referred_by_node', uselist=False))

    def to_dict(self):
        return {
            'referral_id': self.referral_id,
            'referrer_user_id': self.referrer_user_id,
            'referee_user_id': self.referee_user_id,
            'referral_code': self.referral_code,
            'is_activated': self.is_activated,
            'activated_at': self.activated_at.isoformat() if self.activated_at else None,
            'referee_total_earnings': round(self.referee_total_earnings, 6),
            'referee_current_tier': self.referee_current_tier,
            'referee_sessions_count': self.referee_sessions_count,
            'is_churned': self.is_churned,
            'activation_bonus_paid': self.activation_bonus_paid,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class NodeTierHistory(db.Model):
    """Audit trail for tier changes. (Build #75)"""
    __tablename__ = 'node_tier_history'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    previous_tier = db.Column(db.String(20), nullable=False)
    new_tier = db.Column(db.String(20), nullable=False)
    tier_score = db.Column(db.Float, nullable=False)
    data_share_score = db.Column(db.Float, default=0.0)
    referral_score = db.Column(db.Float, default=0.0)
    quality_score = db.Column(db.Float, default=0.0)
    longevity_score = db.Column(db.Float, default=0.0)
    reason = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('tier_history', lazy='dynamic'))

    def to_dict(self):
        return {
            'previous_tier': self.previous_tier,
            'new_tier': self.new_tier,
            'tier_score': round(self.tier_score, 2),
            'breakdown': {
                'data_share': round(self.data_share_score, 2),
                'referral': round(self.referral_score, 2),
                'quality': round(self.quality_score, 2),
                'longevity': round(self.longevity_score, 2),
            },
            'reason': self.reason,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class FleetAccount(db.Model):
    """Commercial fleet management. (Build #75)"""
    __tablename__ = 'fleet_accounts'

    id = db.Column(db.Integer, primary_key=True)
    fleet_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    commercial_account_id = db.Column(db.Integer, db.ForeignKey('commercial_accounts.id'), nullable=True, index=True)
    name = db.Column(db.String(200), nullable=False)
    contact_email = db.Column(db.String(255), nullable=False)

    # Node counts
    max_nodes = db.Column(db.Integer, default=100)
    active_node_count = db.Column(db.Integer, default=0)
    total_node_count = db.Column(db.Integer, default=0)

    # Fleet-level benefits
    arbitrage_rate_discount = db.Column(db.Float, default=0.0)
    data_marketplace_revenue_share = db.Column(db.Float, default=0.0)
    priority_payout = db.Column(db.Boolean, default=False)

    # Enrollment
    enrollment_key = db.Column(db.String(50), unique=True, nullable=False)

    # Aggregate stats
    total_earnings_usd = db.Column(db.Float, default=0.0)
    total_data_events = db.Column(db.Integer, default=0)

    # Status
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    commercial_account = db.relationship('CommercialAccount', backref=db.backref('fleet_accounts', lazy='dynamic'))

    def to_dict(self):
        return {
            'fleet_id': self.fleet_id,
            'name': self.name,
            'contact_email': self.contact_email,
            'max_nodes': self.max_nodes,
            'active_node_count': self.active_node_count,
            'total_node_count': self.total_node_count,
            'benefits': {
                'arbitrage_rate_discount': self.arbitrage_rate_discount,
                'data_marketplace_revenue_share': self.data_marketplace_revenue_share,
                'priority_payout': self.priority_payout,
            },
            'enrollment_key': self.enrollment_key,
            'total_earnings_usd': round(self.total_earnings_usd, 2),
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class RevenueAllocation(db.Model):
    """Per-booking fee allocation ledger — divides arbitrage fee. (Build #75)"""
    __tablename__ = 'revenue_allocations'

    id = db.Column(db.Integer, primary_key=True)
    allocation_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    deal_id = db.Column(db.String(20), db.ForeignKey('deals.deal_id'), nullable=True, index=True)
    booking_id = db.Column(db.Integer, db.ForeignKey('bookings.id'), nullable=True)

    # Fee
    total_fee_usd = db.Column(db.Float, nullable=False)

    # Serving node
    node_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    node_tier = db.Column(db.String(20), nullable=True)
    node_share_pct = db.Column(db.Float, default=0.0)
    node_share_usd = db.Column(db.Float, default=0.0)

    # Referrer
    referrer_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    referral_share_usd = db.Column(db.Float, default=0.0)

    # Platform
    infra_share_usd = db.Column(db.Float, default=0.0)
    platform_profit_usd = db.Column(db.Float, default=0.0)

    # Payout status
    node_payout_status = db.Column(db.String(20), default='pending')  # pending/queued/paid
    referrer_payout_status = db.Column(db.String(20), default='na')  # pending/queued/paid/na

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    node_user = db.relationship('User', foreign_keys=[node_user_id], backref=db.backref('revenue_allocations', lazy='dynamic'))
    referrer_user = db.relationship('User', foreign_keys=[referrer_user_id])

    def to_dict(self):
        return {
            'allocation_id': self.allocation_id,
            'deal_id': self.deal_id,
            'total_fee_usd': round(self.total_fee_usd, 2),
            'node_user_id': self.node_user_id,
            'node_tier': self.node_tier,
            'node_share_pct': self.node_share_pct,
            'node_share_usd': round(self.node_share_usd, 4),
            'referrer_user_id': self.referrer_user_id,
            'referral_share_usd': round(self.referral_share_usd, 4),
            'infra_share_usd': round(self.infra_share_usd, 4),
            'platform_profit_usd': round(self.platform_profit_usd, 4),
            'node_payout_status': self.node_payout_status,
            'referrer_payout_status': self.referrer_payout_status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class CryptoConversion(db.Model):
    """Per-conversion record for multi-crypto -> XRP/RLUSD. (Build #75)"""
    __tablename__ = 'crypto_conversions'

    id = db.Column(db.Integer, primary_key=True)
    conversion_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    # Source
    source_currency = db.Column(db.String(10), nullable=False)  # BTC, ETH, LTC, etc.
    source_amount = db.Column(db.Float, nullable=False)
    source_tx_hash = db.Column(db.String(200), nullable=True)

    # Target
    target_currency = db.Column(db.String(10), default='XRP')
    target_amount = db.Column(db.Float, nullable=True)
    conversion_rate = db.Column(db.Float, nullable=True)

    # Fees
    convenience_fee_pct = db.Column(db.Float, default=0.025)  # 2.5% default
    convenience_fee_usd = db.Column(db.Float, default=0.0)

    # Conversion vehicle
    conversion_vehicle = db.Column(db.String(50), default='coinbase')
    vehicle_tx_id = db.Column(db.String(200), nullable=True)

    # Status
    status = db.Column(db.String(20), default='pending_deposit')  # pending_deposit/converting/pre_funded/completed/failed
    pre_funded = db.Column(db.Boolean, default=False)
    pre_fund_tx_hash = db.Column(db.String(200), nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User', backref=db.backref('crypto_conversions', lazy='dynamic'))

    def to_dict(self):
        return {
            'conversion_id': self.conversion_id,
            'user_id': self.user_id,
            'source_currency': self.source_currency,
            'source_amount': self.source_amount,
            'target_currency': self.target_currency,
            'target_amount': self.target_amount,
            'conversion_rate': self.conversion_rate,
            'convenience_fee_pct': self.convenience_fee_pct,
            'convenience_fee_usd': round(self.convenience_fee_usd, 4) if self.convenience_fee_usd else 0,
            'conversion_vehicle': self.conversion_vehicle,
            'status': self.status,
            'pre_funded': self.pre_funded,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
        }


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Build #78 — Location-Aware Pricing Zones
# ---------------------------------------------------------------------------

class PricingZone(db.Model):
    """Auto-discovered geographic pricing zone.

    Hierarchy: country → region → city → district → micro.
    Seeded from geographic_zones.ZONE_REGISTRY, refined by node density.
    """
    __tablename__ = 'pricing_zones'

    id = db.Column(db.Integer, primary_key=True)
    zone_id = db.Column(db.String(30), unique=True, nullable=False, index=True)
    parent_zone_id = db.Column(db.String(30), nullable=True, index=True)
    resolution = db.Column(db.String(20), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    country_code = db.Column(db.String(2), nullable=False, index=True)
    lat_center = db.Column(db.Float, nullable=False)
    lon_center = db.Column(db.Float, nullable=False)
    radius_km = db.Column(db.Float, nullable=False)
    active_node_count = db.Column(db.Integer, default=0)
    total_observations = db.Column(db.Integer, default=0)
    density_score = db.Column(db.Float, default=0.0)
    avg_price_deviation_pct = db.Column(db.Float, nullable=True)
    is_seeded = db.Column(db.Boolean, default=False)
    is_auto_discovered = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.Index('ix_pricing_zone_country_res', 'country_code', 'resolution'),
        db.Index('ix_pricing_zone_latlon', 'lat_center', 'lon_center'),
    )

    def to_dict(self):
        return {
            'zone_id': self.zone_id,
            'parent_zone_id': self.parent_zone_id,
            'resolution': self.resolution,
            'name': self.name,
            'country_code': self.country_code,
            'lat_center': self.lat_center,
            'lon_center': self.lon_center,
            'radius_km': self.radius_km,
            'active_node_count': self.active_node_count,
            'total_observations': self.total_observations,
            'density_score': self.density_score,
            'avg_price_deviation_pct': self.avg_price_deviation_pct,
            'is_seeded': self.is_seeded,
            'is_auto_discovered': self.is_auto_discovered,
            'is_active': self.is_active,
        }


class PriceObservation(db.Model):
    """Location-tagged price data point — the core primitive for the
    spatial-temporal pricing index."""
    __tablename__ = 'price_observations'

    id = db.Column(db.Integer, primary_key=True)
    observation_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    zone_id = db.Column(db.String(30), nullable=True, index=True)
    node_id = db.Column(db.String(50), nullable=True, index=True)
    lat = db.Column(db.Float, nullable=True)
    lon = db.Column(db.Float, nullable=True)
    country_code = db.Column(db.String(2), nullable=False, index=True)
    vertical = db.Column(db.String(20), nullable=False, index=True)
    item_key = db.Column(db.String(300), nullable=False, index=True)
    price_usd = db.Column(db.Float, nullable=False)
    price_local = db.Column(db.Float, nullable=True)
    currency = db.Column(db.String(5), nullable=True)
    is_promoted = db.Column(db.Boolean, default=False)
    promotion_type = db.Column(db.String(50), nullable=True)
    source_tier = db.Column(db.Integer, nullable=True)
    source_url = db.Column(db.String(500), nullable=True)
    observed_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        db.Index('ix_obs_vertical_item', 'vertical', 'item_key'),
        db.Index('ix_obs_zone_time', 'zone_id', 'observed_at'),
        db.Index('ix_obs_country_vertical', 'country_code', 'vertical'),
    )

    def to_dict(self):
        return {
            'observation_id': self.observation_id,
            'zone_id': self.zone_id,
            'node_id': self.node_id,
            'country_code': self.country_code,
            'vertical': self.vertical,
            'item_key': self.item_key,
            'price_usd': self.price_usd,
            'price_local': self.price_local,
            'currency': self.currency,
            'is_promoted': self.is_promoted,
            'promotion_type': self.promotion_type,
            'source_tier': self.source_tier,
            'observed_at': self.observed_at.isoformat() if self.observed_at else None,
        }


class NodeLocationHistory(db.Model):
    """Location pings from nodes (consent-gated).

    Used for zone auto-discovery clustering and node location verification.
    """
    __tablename__ = 'node_location_history'

    id = db.Column(db.Integer, primary_key=True)
    node_id = db.Column(db.String(50), nullable=False, index=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    lat = db.Column(db.Float, nullable=False)
    lon = db.Column(db.Float, nullable=False)
    accuracy_m = db.Column(db.Float, nullable=True)
    source = db.Column(db.String(20), nullable=False)
    resolved_zone_id = db.Column(db.String(30), nullable=True, index=True)
    country_code = db.Column(db.String(2), nullable=True)
    city = db.Column(db.String(100), nullable=True)
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        db.Index('ix_node_loc_latlon', 'lat', 'lon'),
        db.Index('ix_node_loc_node_time', 'node_id', 'recorded_at'),
    )

    def to_dict(self):
        return {
            'node_id': self.node_id,
            'user_id': self.user_id,
            'lat': self.lat,
            'lon': self.lon,
            'accuracy_m': self.accuracy_m,
            'source': self.source,
            'resolved_zone_id': self.resolved_zone_id,
            'country_code': self.country_code,
            'city': self.city,
            'recorded_at': self.recorded_at.isoformat() if self.recorded_at else None,
        }


# ---------------------------------------------------------------------------
# Build #79 — Autonomous Data Harvesting Scheduler
# ---------------------------------------------------------------------------

class HarvestExecution(db.Model):
    """Tracks each autonomous harvest batch execution."""
    __tablename__ = 'harvest_executions'

    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.String(30), unique=True, nullable=False, index=True)
    execution_type = db.Column(db.String(30), nullable=False, index=True)
    vertical = db.Column(db.String(20), nullable=True)
    zones_targeted = db.Column(db.Text, nullable=True)
    tasks_generated = db.Column(db.Integer, default=0)
    tasks_dispatched = db.Column(db.Integer, default=0)
    tasks_completed = db.Column(db.Integer, default=0)
    tasks_failed = db.Column(db.Integer, default=0)
    observations_collected = db.Column(db.Integer, default=0)
    total_payout_usd = db.Column(db.Float, default=0.0)
    avg_quality_score = db.Column(db.Float, nullable=True)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.Index('ix_harvest_executions_type_created', 'execution_type', 'created_at'),
    )

    def to_dict(self):
        return {
            'batch_id': self.batch_id,
            'execution_type': self.execution_type,
            'vertical': self.vertical,
            'zones_targeted': json.loads(self.zones_targeted) if self.zones_targeted else [],
            'tasks_generated': self.tasks_generated,
            'tasks_dispatched': self.tasks_dispatched,
            'tasks_completed': self.tasks_completed,
            'tasks_failed': self.tasks_failed,
            'observations_collected': self.observations_collected,
            'total_payout_usd': self.total_payout_usd,
            'avg_quality_score': self.avg_quality_score,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class StandingOrder(db.Model):
    """Commercial buyer standing order for continuous data harvesting."""
    __tablename__ = 'standing_orders'

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.String(30), unique=True, nullable=False, index=True)
    account_id = db.Column(db.Integer, db.ForeignKey('commercial_accounts.id'), nullable=False, index=True)
    vertical = db.Column(db.String(20), nullable=False, index=True)
    filters = db.Column(db.Text, nullable=True)
    zone_ids = db.Column(db.Text, nullable=True)
    refresh_interval_hours = db.Column(db.Integer, default=6)
    max_tasks_per_cycle = db.Column(db.Integer, default=10)
    price_per_observation_usd = db.Column(db.Float, default=0.01)
    max_spend_per_day_usd = db.Column(db.Float, default=50.0)
    is_active = db.Column(db.Boolean, default=True)
    last_executed_at = db.Column(db.DateTime, nullable=True)
    total_observations_delivered = db.Column(db.Integer, default=0)
    total_spent_usd = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.Index('ix_standing_orders_active_vertical', 'is_active', 'vertical'),
    )

    def to_dict(self):
        return {
            'order_id': self.order_id,
            'account_id': self.account_id,
            'vertical': self.vertical,
            'filters': json.loads(self.filters) if self.filters else {},
            'zone_ids': json.loads(self.zone_ids) if self.zone_ids else [],
            'refresh_interval_hours': self.refresh_interval_hours,
            'max_tasks_per_cycle': self.max_tasks_per_cycle,
            'price_per_observation_usd': self.price_per_observation_usd,
            'max_spend_per_day_usd': self.max_spend_per_day_usd,
            'is_active': self.is_active,
            'last_executed_at': self.last_executed_at.isoformat() if self.last_executed_at else None,
            'total_observations_delivered': self.total_observations_delivered,
            'total_spent_usd': self.total_spent_usd,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class HarvestBudget(db.Model):
    """Per-zone per-vertical harvest rate limit budget."""
    __tablename__ = 'harvest_budgets'

    id = db.Column(db.Integer, primary_key=True)
    zone_id = db.Column(db.String(30), nullable=False, index=True)
    vertical = db.Column(db.String(20), nullable=False, index=True)
    max_tasks_per_hour = db.Column(db.Integer, default=20)
    max_tasks_per_day = db.Column(db.Integer, default=200)
    tasks_this_hour = db.Column(db.Integer, default=0)
    tasks_today = db.Column(db.Integer, default=0)
    hour_reset_at = db.Column(db.DateTime, nullable=True)
    day_reset_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.UniqueConstraint('zone_id', 'vertical', name='uq_harvest_budget_zone_vertical'),
        db.Index('ix_harvest_budgets_zone_vertical', 'zone_id', 'vertical'),
    )

    def to_dict(self):
        return {
            'zone_id': self.zone_id,
            'vertical': self.vertical,
            'max_tasks_per_hour': self.max_tasks_per_hour,
            'max_tasks_per_day': self.max_tasks_per_day,
            'tasks_this_hour': self.tasks_this_hour,
            'tasks_today': self.tasks_today,
            'hour_reset_at': self.hour_reset_at.isoformat() if self.hour_reset_at else None,
            'day_reset_at': self.day_reset_at.isoformat() if self.day_reset_at else None,
        }


# ============================================================
# Payment Zone Compatibility (Build #85)
# ============================================================

class PaymentZoneRule(db.Model):
    """Payment compatibility rule: card brand X issued in country Y accepted in country Z."""
    __tablename__ = 'payment_zone_rules'

    id = db.Column(db.Integer, primary_key=True)
    payment_type = db.Column(db.String(20), nullable=False, index=True)
    issuing_country = db.Column(db.String(2), nullable=False, index=True)  # ISO or '*'
    merchant_country = db.Column(db.String(2), nullable=False, index=True)  # ISO or '*'
    acceptance_level = db.Column(db.String(10), nullable=False, default='high')
    vertical = db.Column(db.String(20), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.Index('idx_pzr_lookup', 'payment_type', 'issuing_country',
                 'merchant_country', 'is_active'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'payment_type': self.payment_type,
            'issuing_country': self.issuing_country,
            'merchant_country': self.merchant_country,
            'acceptance_level': self.acceptance_level,
            'vertical': self.vertical,
            'notes': self.notes,
            'is_active': self.is_active,
        }


class PaymentInteropGroup(db.Model):
    """Named group of countries with shared payment interoperability."""
    __tablename__ = 'payment_interop_groups'

    id = db.Column(db.Integer, primary_key=True)
    group_code = db.Column(db.String(30), unique=True, nullable=False, index=True)
    group_name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    countries = db.Column(db.Text, nullable=False)  # JSON array of 2-letter codes
    payment_types = db.Column(db.Text, nullable=False)  # JSON array of card brands
    default_acceptance = db.Column(db.String(10), default='high')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def get_countries(self):
        try:
            return json.loads(self.countries)
        except Exception:
            return []

    def get_payment_types(self):
        try:
            return json.loads(self.payment_types)
        except Exception:
            return []

    def to_dict(self):
        return {
            'group_code': self.group_code,
            'group_name': self.group_name,
            'description': self.description,
            'countries': self.get_countries(),
            'payment_types': self.get_payment_types(),
            'default_acceptance': self.default_acceptance,
            'is_active': self.is_active,
        }


class RampProvider(db.Model):
    """On-ramp/off-ramp provider configuration (Build #86)."""
    __tablename__ = 'ramp_providers'

    id = db.Column(db.Integer, primary_key=True)
    provider_code = db.Column(db.String(30), unique=True, nullable=False, index=True)
    provider_name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    widget_base_url = db.Column(db.String(500))
    widget_type = db.Column(db.String(20), default='redirect')
    supported_countries = db.Column(db.Text)
    supported_fiat_methods = db.Column(db.Text)
    supported_crypto_out = db.Column(db.Text)
    fee_estimate_pct = db.Column(db.Float, default=0.0)
    kyc_required = db.Column(db.Boolean, default=True)
    api_key_env_var = db.Column(db.String(50))
    priority = db.Column(db.Integer, default=10)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_supported_countries(self):
        import json
        try:
            return json.loads(self.supported_countries) if self.supported_countries else []
        except (json.JSONDecodeError, TypeError):
            return []

    def get_supported_fiat_methods(self):
        import json
        try:
            return json.loads(self.supported_fiat_methods) if self.supported_fiat_methods else []
        except (json.JSONDecodeError, TypeError):
            return []

    def get_supported_crypto_out(self):
        import json
        try:
            return json.loads(self.supported_crypto_out) if self.supported_crypto_out else []
        except (json.JSONDecodeError, TypeError):
            return []

    def to_dict(self):
        return {
            'provider_code': self.provider_code,
            'provider_name': self.provider_name,
            'description': self.description,
            'widget_base_url': self.widget_base_url,
            'widget_type': self.widget_type,
            'supported_countries': self.get_supported_countries(),
            'supported_fiat_methods': self.get_supported_fiat_methods(),
            'supported_crypto_out': self.get_supported_crypto_out(),
            'fee_estimate_pct': self.fee_estimate_pct,
            'kyc_required': self.kyc_required,
            'priority': self.priority,
            'is_active': self.is_active,
        }


class VirtualCardTransaction(db.Model):
    """Lifecycle tracking for crypto -> USDC -> virtual card -> vendor (Build #86)."""
    __tablename__ = 'virtual_card_transactions'

    id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    source_currency = db.Column(db.String(10))
    source_amount = db.Column(db.Float)
    source_tx_hash = db.Column(db.String(100))

    usdc_amount = db.Column(db.Float)
    usdc_settled_at = db.Column(db.DateTime)

    stripe_card_id = db.Column(db.String(100))
    card_funded_amount = db.Column(db.Float)
    card_funded_at = db.Column(db.DateTime)

    merchant_country = db.Column(db.String(2))
    merchant_name = db.Column(db.String(200))
    charge_amount_usd = db.Column(db.Float)
    charge_currency = db.Column(db.String(3))
    charge_amount_local = db.Column(db.Float)
    charged_at = db.Column(db.DateTime)

    deal_id = db.Column(db.String(50), nullable=True)
    deal_type = db.Column(db.String(20))
    purchase_context = db.Column(db.String(20), default='browsing')

    status = db.Column(db.String(30), default='initiated', index=True)
    failure_reason = db.Column(db.Text)
    fx_spread_pct = db.Column(db.Float)
    total_fees_usd = db.Column(db.Float)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)

    user = db.relationship('User', backref=db.backref('virtual_card_transactions', lazy='dynamic'))

    def to_dict(self):
        return {
            'transaction_id': self.transaction_id,
            'user_id': self.user_id,
            'source_currency': self.source_currency,
            'source_amount': self.source_amount,
            'usdc_amount': self.usdc_amount,
            'merchant_country': self.merchant_country,
            'merchant_name': self.merchant_name,
            'charge_amount_usd': self.charge_amount_usd,
            'charge_currency': self.charge_currency,
            'deal_id': self.deal_id,
            'purchase_context': self.purchase_context,
            'status': self.status,
            'fx_spread_pct': self.fx_spread_pct,
            'total_fees_usd': self.total_fees_usd,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
        }


class UserRampPreference(db.Model):
    """User's preferred on-ramp provider (Build #86)."""
    __tablename__ = 'user_ramp_preferences'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    provider_code = db.Column(db.String(30), nullable=False)
    is_default = db.Column(db.Boolean, default=False)
    last_used_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('ramp_preferences', lazy='dynamic'))

    def to_dict(self):
        return {
            'provider_code': self.provider_code,
            'is_default': self.is_default,
            'last_used_at': self.last_used_at.isoformat() if self.last_used_at else None,
        }


# ---------------------------------------------------------------------------
# Build #90 — Zone Economics Snapshots (hot zone tracking)
# ---------------------------------------------------------------------------

class ZoneEconomicsSnapshot(db.Model):
    """Daily snapshot of per-zone economic metrics.

    Pre-computed hourly by a Celery task.  Powers the node earnings
    dashboard, opportunity scores, and hot-zone onboarding ads.
    """
    __tablename__ = 'zone_economics_snapshots'

    id = db.Column(db.Integer, primary_key=True)
    zone_code = db.Column(db.String(10), nullable=False, index=True)
    snapshot_date = db.Column(db.Date, nullable=False, index=True)

    # Supply
    active_nodes = db.Column(db.Integer, default=0)
    total_node_hours = db.Column(db.Float, default=0.0)

    # Demand
    arbitrage_queries_served = db.Column(db.Integer, default=0)
    browse_sessions_served = db.Column(db.Integer, default=0)
    total_tasks = db.Column(db.Integer, default=0)

    # Revenue
    arbitrage_fee_revenue_usd = db.Column(db.Float, default=0.0)
    browse_data_revenue_usd = db.Column(db.Float, default=0.0)
    total_revenue_usd = db.Column(db.Float, default=0.0)

    # Per-node economics
    avg_earnings_per_node_usd = db.Column(db.Float, default=0.0)
    top_node_earnings_usd = db.Column(db.Float, default=0.0)

    # Signals
    demand_supply_ratio = db.Column(db.Float, default=0.0)
    saturation_score = db.Column(db.Float, default=0.0)
    opportunity_score = db.Column(db.Integer, default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('zone_code', 'snapshot_date',
                            name='uq_zone_economics_zone_date'),
    )

    def to_dict(self):
        return {
            'zone_code': self.zone_code,
            'snapshot_date': self.snapshot_date.isoformat() if self.snapshot_date else None,
            'active_nodes': self.active_nodes,
            'total_node_hours': round(self.total_node_hours, 1),
            'arbitrage_queries_served': self.arbitrage_queries_served,
            'browse_sessions_served': self.browse_sessions_served,
            'total_tasks': self.total_tasks,
            'arbitrage_fee_revenue_usd': round(self.arbitrage_fee_revenue_usd, 2),
            'browse_data_revenue_usd': round(self.browse_data_revenue_usd, 2),
            'total_revenue_usd': round(self.total_revenue_usd, 2),
            'avg_earnings_per_node_usd': round(self.avg_earnings_per_node_usd, 2),
            'top_node_earnings_usd': round(self.top_node_earnings_usd, 2),
            'demand_supply_ratio': round(self.demand_supply_ratio, 2),
            'saturation_score': round(self.saturation_score, 2),
            'opportunity_score': self.opportunity_score,
        }


# ============================================================
# Trip Bundle Models — Multi-Vertical Package Booking
# ============================================================

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

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
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

    Layer 1 (Launch): Flights, Hotels, Tier System, Proxy B2B Sales
    Layer 2 (Funded): Products, Rentals, Cruises, Node Payments
    Layer 3 (Scale): Own SERP, Data Marketplace, 100% Node Revenue
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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
                flag.enabled_at = datetime.utcnow()
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
            ('vertical_hotels', 'Hotels Vertical', 'Search and book hotels via Amadeus', 1, True),
            ('tier_system', 'Tier System', 'Bronze/Silver/Gold/Platinum user tiers', 1, True),
            ('node_onboarding', 'Node Onboarding', 'Allow users to join the Mystes Network', 1, True),
            ('proxy_b2b_sales', 'Proxy B2B Sales', 'Sell proxy access to enterprise customers', 1, True),

            # Layer 2 - Funded
            ('vertical_products', 'Products Vertical', 'Price comparison for physical products', 2, False),
            ('vertical_rentals', 'Rentals Vertical', 'Car and vacation rentals', 2, False),
            ('vertical_cruises', 'Cruises Vertical', 'Cruise booking and comparison', 2, False),
            ('node_network_active', 'Node Network Active', 'Use node network for user searches', 2, False),
            ('node_payments', 'Node Payments', 'Pay nodes for bandwidth/proxy usage', 2, False),

            # Layer 3 - Scale
            ('citizenserp_active', 'CitizenSERP Active', 'Use own SERP infrastructure', 3, False),
            ('data_marketplace', 'Data Marketplace', 'Sell browsing data to enterprises', 3, False),
            ('arbitrage_rewards', 'Arbitrage Rewards', 'Nodes earn from arbitrage discoveries', 3, False),
            ('full_node_revenue', 'Full Node Revenue', '100% proxy revenue to nodes', 3, False),
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
                    enabled_at=datetime.utcnow() if enabled else None,
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
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
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


def init_db(app):
    """Initialize database with Flask app."""
    db.init_app(app)
    with app.app_context():
        db.create_all()
        # Initialize default feature flags and system settings
        FeatureFlag.init_default_flags()
        SystemSetting.init_defaults()
        print("Database initialized successfully!")
