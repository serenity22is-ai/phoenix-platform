"""
MYSTES Multi-Payment Gateway

Accepts payments via:
- Credit/Debit Card (Stripe)
- XRP Direct (XRPL)
- RLUSD Stablecoin (XRPL)
- Any Cryptocurrency (Coinbase Commerce) - BTC, ETH, LTC, DOGE, USDC, etc.

All payments unlock the same deal access.
"""

import os
import hashlib
from datetime import datetime, timedelta
from enum import Enum

# XRPL imports
try:
    from xrpl.clients import JsonRpcClient
    from xrpl.models.requests import AccountTx
    from xrpl.utils import drops_to_xrp
    XRPL_AVAILABLE = True
except ImportError:
    XRPL_AVAILABLE = False

# Stripe imports
try:
    import stripe
    STRIPE_AVAILABLE = True
except ImportError:
    STRIPE_AVAILABLE = False
    print("Note: Stripe not installed. Run: pip install stripe")


def get_fee_percent(user=None):
    """Get platform fee percentage based on membership status.

    Priority order (Build #170):
    1. B2B agency (active subscription): account.fee_percent (25%/20%/15%)
    2. Travel+ subscriber: 35%
    3. Free member (authenticated, no subscription): 45%
    4. Guest (anonymous): 50%

    NO minimum savings threshold. NO maximum fee cap. $3 minimum fee only.
    """
    resolved = user
    if not resolved:
        try:
            from flask_login import current_user
            if current_user and current_user.is_authenticated:
                resolved = current_user
        except Exception:
            pass

    if resolved and getattr(resolved, 'is_authenticated', False):
        # B2B account takes precedence over regular member pricing
        try:
            from models import CommercialAccount
            account = CommercialAccount.query.filter_by(
                owner_user_id=resolved.id, is_active=True
            ).first()
            if account and account.subscription_status == 'active':
                return account.fee_percent / 100.0  # 25.0 → 0.25
        except Exception:
            pass

        # Travel+ subscriber gets 35%
        try:
            from models import Subscription
            sub = Subscription.query.filter_by(
                user_id=resolved.id, status='active'
            ).first()
            if sub and sub.tier == 'travel_plus':
                return 0.35  # Travel+ = 35%
        except Exception:
            pass

        return 0.45  # Free member (authenticated, no subscription) = 45%

    return 0.50  # Guest (anonymous) = 50%


def get_fee_tier_name(user=None):
    """Return human-readable tier name for display in checkout UI."""
    resolved = user
    if not resolved:
        try:
            from flask_login import current_user
            if current_user and current_user.is_authenticated:
                resolved = current_user
        except Exception:
            pass

    if resolved and getattr(resolved, 'is_authenticated', False):
        try:
            from models import CommercialAccount
            account = CommercialAccount.query.filter_by(
                owner_user_id=resolved.id, is_active=True
            ).first()
            if account and account.subscription_status == 'active':
                return f"B2B {account.current_tier.title()}"
        except Exception:
            pass

        try:
            from models import Subscription
            sub = Subscription.query.filter_by(
                user_id=resolved.id, status='active'
            ).first()
            if sub and sub.tier == 'travel_plus':
                return "Travel+"
        except Exception:
            pass

        return "Free Member"

    return "Guest"


def calculate_savings_breakdown(retail_price, our_price, user=None, apply_share_discount=False,
                                 points_to_redeem=0):
    """Calculate the full savings breakdown for checkout display.

    Returns dict with all pricing details for the savings waterfall UI.
    """
    from flask import current_app

    savings = max(0, retail_price - our_price)
    fee_pct = get_fee_percent(user)
    tier_name = get_fee_tier_name(user)

    # Base fee
    fee = round(savings * fee_pct, 2) if savings > 0 else 0.0
    # Minimum $3 fee
    if fee > 0 and fee < 3.0:
        fee = 3.0

    # Share-to-save discount (5% off platform fee)
    share_discount = 0.0
    if apply_share_discount and fee > 0:
        share_pct = current_app.config.get('SHARE_TO_SAVE_DISCOUNT', 0.05)
        share_discount = round(fee * share_pct, 2)

    # Points redemption (1000 points = $1)
    points_value = 0.0
    if points_to_redeem > 0:
        redemption_rate = current_app.config.get('POINTS_REDEMPTION_VALUE', 0.001)
        points_value = round(points_to_redeem * redemption_rate, 2)

    final_fee = max(0, round(fee - share_discount - points_value, 2))
    customer_price = round(our_price + final_fee, 2)
    customer_savings = round(retail_price - customer_price, 2)

    # What they'd save with Travel+ (for upsell)
    travel_plus_fee = round(savings * 0.35, 2) if savings > 0 else 0.0
    if travel_plus_fee > 0 and travel_plus_fee < 3.0:
        travel_plus_fee = 3.0
    travel_plus_extra_savings = round(fee - travel_plus_fee, 2) if fee > travel_plus_fee else 0.0

    return {
        'retail_price': retail_price,
        'our_price': our_price,
        'total_savings': savings,
        'fee_percent': fee_pct,
        'fee_percent_display': int(fee_pct * 100),
        'tier_name': tier_name,
        'base_fee': fee,
        'share_discount': share_discount,
        'points_applied': points_to_redeem,
        'points_value': points_value,
        'final_fee': final_fee,
        'customer_price': customer_price,
        'customer_savings': customer_savings,
        # Upsell data
        'travel_plus_fee': travel_plus_fee,
        'travel_plus_extra_savings': travel_plus_extra_savings,
        'travel_plus_monthly': 9.99,
    }


class PaymentMethod(Enum):
    CARD = "card"           # Credit/Debit via Stripe
    XRP = "xrp"             # Direct XRP payment on XRPL
    RLUSD = "rlusd"         # RLUSD stablecoin on XRPL


class PaymentStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    VERIFIED = "verified"
    FAILED = "failed"
    EXPIRED = "expired"
    REFUNDED = "refunded"


# --- CONFIGURATION ---

PAYMENT_CONFIG = {
    # Stripe (for card payments)
    "stripe_secret_key": os.getenv("STRIPE_SECRET_KEY", ""),
    "stripe_publishable_key": os.getenv("STRIPE_PUBLISHABLE_KEY", ""),
    "stripe_webhook_secret": os.getenv("STRIPE_WEBHOOK_SECRET", ""),

    # Coinbase removed — Stripe + MoonPay only

    # XRPL
    "xrpl_network": os.getenv("XRPL_NETWORK", "testnet"),
    "xrpl_testnet_url": "https://s.altnet.rippletest.net:51234",
    "xrpl_mainnet_url": "https://xrplcluster.com",
    "platform_xrp_address": os.getenv("XRPL_WALLET_ADDRESS", "rBYk2nioyZGDndMqDSp2eMD22ZD9bNwM1d"),

    # RLUSD issuer on XRPL (Ripple's USD stablecoin)
    "rlusd_issuer": "rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De",  # RLUSD issuer address

    # Pricing
    "xrp_usd_rate": 0.50,  # Fallback, fetched live

    # Payment expiry
    "payment_expiry_minutes": 15,
}

# Initialize Stripe if available
if STRIPE_AVAILABLE and PAYMENT_CONFIG["stripe_secret_key"]:
    stripe.api_key = PAYMENT_CONFIG["stripe_secret_key"]


def get_xrp_price():
    """Fetch live XRP/USD price."""
    import requests
    try:
        response = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "ripple", "vs_currencies": "usd"},
            timeout=10
        )
        if response.status_code == 200:
            price = response.json().get("ripple", {}).get("usd")
            if price:
                PAYMENT_CONFIG["xrp_usd_rate"] = price
                return price
    except Exception:
        pass
    return PAYMENT_CONFIG["xrp_usd_rate"]


def usd_to_xrp(usd_amount):
    """Convert USD to XRP."""
    rate = PAYMENT_CONFIG["xrp_usd_rate"]
    if rate <= 0:
        rate = get_xrp_price()
    return round(usd_amount / rate, 6) if rate > 0 else None


def generate_destination_tag(deal_id, user_id=None):
    """Generate unique destination tag for XRPL payments."""
    data = f"{deal_id}:{user_id or 'anon'}:{datetime.utcnow().isoformat()}"
    return abs(hash(data)) % 2147483647


# --- STRIPE CUSTOMER LIFECYCLE ---

def get_or_create_stripe_customer(user):
    """
    Get existing Stripe Customer or create one lazily.
    Stores stripe_customer_id on User model (caller must commit).

    Args:
        user: User model instance (must have id, email, name, stripe_customer_id)

    Returns:
        stripe_customer_id string, or None on failure
    """
    import logging
    logger = logging.getLogger(__name__)

    if not STRIPE_AVAILABLE or not PAYMENT_CONFIG["stripe_secret_key"]:
        return None

    if user.stripe_customer_id:
        return user.stripe_customer_id

    try:
        customer = stripe.Customer.create(
            email=user.email,
            name=getattr(user, 'name', None) or user.email,
            metadata={
                "mystes_user_id": str(user.id),
            }
        )
        user.stripe_customer_id = customer.id
        return customer.id
    except stripe.error.StripeError as e:
        logger.error(f"Stripe Customer creation failed for user {user.id}: {e}")
        return None


# --- PAYMENT OPTIONS GENERATOR ---

def generate_payment_options(deal_id, fee_usd, user_id=None,
                              include_xrp=False, include_rlusd=False,
                              include_crypto=False, include_moonpay=True):
    """
    Generate available payment options for a deal.

    Args:
        deal_id: Unique deal identifier
        fee_usd: Platform fee in USD
        user_id: Optional user ID
        include_xrp: Include XRP direct payment (Phase 2)
        include_rlusd: Include RLUSD payment (Phase 2)
        include_crypto: Include Coinbase Commerce crypto (Phase 2)
        include_moonpay: Include MoonPay on/off ramp (Phase 1)

    Returns:
        dict with payment options for each enabled method
    """
    expires_at = datetime.utcnow() + timedelta(minutes=PAYMENT_CONFIG["payment_expiry_minutes"])

    options = {
        "deal_id": deal_id,
        "fee_usd": round(fee_usd, 2),
        "expires_at": expires_at.isoformat(),
        "expires_in_minutes": PAYMENT_CONFIG["payment_expiry_minutes"],
        "methods": {}
    }

    # --- CARD PAYMENT (Stripe) — always available in Phase 1 ---
    if STRIPE_AVAILABLE and PAYMENT_CONFIG["stripe_secret_key"]:
        options["methods"]["card"] = {
            "enabled": True,
            "provider": "stripe",
            "amount_usd": round(fee_usd, 2),
            "amount_cents": int(fee_usd * 100),
            "publishable_key": PAYMENT_CONFIG["stripe_publishable_key"],
            "description": f"MYSTES Deal Access - {deal_id}",
        }
    else:
        options["methods"]["card"] = {
            "enabled": False,
            "reason": "Card payments not configured"
        }

    # --- MOONPAY (On/Off Ramp — Phase 1) ---
    if include_moonpay:
        moonpay_key = os.getenv("MOONPAY_API_KEY", "")
        if moonpay_key:
            options["methods"]["moonpay"] = {
                "enabled": True,
                "provider": "moonpay",
                "amount_usd": round(fee_usd, 2),
                "description": f"MYSTES Deal Access - {deal_id}",
                "supported_methods": ["card", "bank_transfer", "paypal", "venmo", "ach", "sepa"],
            }
        else:
            options["methods"]["moonpay"] = {
                "enabled": False,
                "reason": "MoonPay not configured"
            }

    # --- XRP DIRECT (Phase 2) ---
    if include_xrp and XRPL_AVAILABLE:
        get_xrp_price()
        destination_tag = generate_destination_tag(deal_id, user_id)
        xrp_amount = usd_to_xrp(fee_usd)
        options["methods"]["xrp"] = {
            "enabled": True,
            "destination": PAYMENT_CONFIG["platform_xrp_address"],
            "destination_tag": destination_tag,
            "amount_xrp": xrp_amount,
            "amount_usd": round(fee_usd, 2),
            "xrp_rate": PAYMENT_CONFIG["xrp_usd_rate"],
            "network": PAYMENT_CONFIG["xrpl_network"],
            "qr_data": f"xrpl:{PAYMENT_CONFIG['platform_xrp_address']}?amount={xrp_amount}&dt={destination_tag}",
        }

    # --- RLUSD Stablecoin (Phase 2) ---
    if include_rlusd and XRPL_AVAILABLE:
        destination_tag = generate_destination_tag(deal_id, user_id)
        options["methods"]["rlusd"] = {
            "enabled": True,
            "destination": PAYMENT_CONFIG["platform_xrp_address"],
            "destination_tag": destination_tag,
            "amount_rlusd": round(fee_usd, 2),
            "currency": "RLUSD",
            "issuer": PAYMENT_CONFIG["rlusd_issuer"],
            "network": PAYMENT_CONFIG["xrpl_network"],
        }

    # Coinbase removed — Stripe + MoonPay only

    return options


# --- STRIPE CARD PAYMENTS ---

def create_stripe_checkout_session(deal_id, fee_usd, user_email, success_url, cancel_url,
                                    user_id=None, user=None):
    """
    Create a Stripe Checkout session for card payment.

    Args:
        deal_id: Deal identifier
        fee_usd: Amount in USD
        user_email: Customer email
        success_url: Redirect URL after payment
        cancel_url: Redirect URL on cancel
        user_id: User ID (stored in metadata for webhook attribution)
        user: User model instance (if provided, creates/uses Stripe Customer for saved cards)

    Returns:
        dict with session_id and checkout_url
    """
    if not STRIPE_AVAILABLE or not PAYMENT_CONFIG["stripe_secret_key"]:
        return {"error": "Card payments not configured"}

    try:
        metadata = {
            "deal_id": deal_id,
            "fee_usd": str(fee_usd),
        }
        if user_id is not None:
            metadata["user_id"] = str(user_id)

        session_params = {
            "payment_method_types": ["card"],
            "line_items": [{
                "price_data": {
                    "currency": "usd",
                    "unit_amount": int(fee_usd * 100),
                    "product_data": {
                        "name": "MYSTES Deal Access",
                        "description": f"Unlock flight savings - Deal {deal_id}",
                    },
                },
                "quantity": 1,
            }],
            "mode": "payment",
            "success_url": success_url + f"?session_id={{CHECKOUT_SESSION_ID}}&deal_id={deal_id}",
            "cancel_url": cancel_url,
            "metadata": metadata,
            "expires_at": int((datetime.utcnow() + timedelta(minutes=30)).timestamp()),
        }

        # Resolve Stripe Customer for saved-card support
        customer_id = None
        if user:
            customer_id = get_or_create_stripe_customer(user)

        if customer_id:
            session_params["customer"] = customer_id
            session_params["payment_intent_data"] = {
                "setup_future_usage": "on_session",
            }
        else:
            session_params["customer_email"] = user_email

        session = stripe.checkout.Session.create(**session_params)

        return {
            "session_id": session.id,
            "checkout_url": session.url,
            "publishable_key": PAYMENT_CONFIG["stripe_publishable_key"],
        }
    except stripe.error.StripeError as e:
        return {"error": str(e)}


def verify_stripe_session(session_id):
    """
    Verify a Stripe checkout session was completed.

    Returns:
        dict with verification result
    """
    if not STRIPE_AVAILABLE:
        return {"verified": False, "error": "Stripe not available"}

    try:
        session = stripe.checkout.Session.retrieve(session_id)

        if session.payment_status == "paid":
            return {
                "verified": True,
                "deal_id": session.metadata.get("deal_id"),
                "amount_usd": float(session.metadata.get("fee_usd", 0)),
                "payment_intent": session.payment_intent,
                "customer_email": session.customer_email,
            }
        else:
            return {
                "verified": False,
                "status": session.payment_status,
            }
    except stripe.error.StripeError as e:
        return {"verified": False, "error": str(e)}


def handle_stripe_webhook(payload, signature):
    """
    Handle Stripe webhook events.

    Returns:
        dict with event details including user-identifying data
    """
    if not STRIPE_AVAILABLE:
        return {"error": "Stripe not available"}

    try:
        event = stripe.Webhook.construct_event(
            payload,
            signature,
            PAYMENT_CONFIG["stripe_webhook_secret"]
        )

        if event.type == "checkout.session.completed":
            session = event.data.object
            return {
                "event": "payment_completed",
                "deal_id": session.metadata.get("deal_id"),
                "amount_usd": float(session.metadata.get("fee_usd", 0)),
                "user_id": session.metadata.get("user_id"),
                "session_id": session.id,
                "payment_intent": session.payment_intent,
                "customer_email": session.customer_email,
            }

        elif event.type == "checkout.session.expired":
            session = event.data.object
            return {
                "event": "payment_expired",
                "deal_id": session.metadata.get("deal_id"),
                "session_id": session.id,
                "customer_email": session.customer_email,
            }

        return {"event": event.type}

    except stripe.error.SignatureVerificationError:
        return {"error": "Invalid signature"}


def create_stripe_refund(payment_intent_id, amount_cents=None, reason="requested_by_customer"):
    """
    Create a Stripe refund for a payment.

    Args:
        payment_intent_id: The Stripe payment intent ID (pi_xxx)
        amount_cents: Amount to refund in cents. None = full refund.
        reason: One of 'duplicate', 'fraudulent', 'requested_by_customer'

    Returns:
        dict with refund result
    """
    if not STRIPE_AVAILABLE or not PAYMENT_CONFIG["stripe_secret_key"]:
        return {"error": "Stripe not configured"}

    try:
        refund_params = {
            "payment_intent": payment_intent_id,
            "reason": reason,
        }
        if amount_cents is not None:
            refund_params["amount"] = amount_cents

        refund = stripe.Refund.create(**refund_params)

        return {
            "success": True,
            "refund_id": refund.id,
            "amount": refund.amount,
            "status": refund.status,
            "currency": refund.currency,
        }
    except stripe.error.StripeError as e:
        return {"error": str(e)}


# Coinbase Commerce section removed — Stripe + MoonPay only


def _coinbase_removed():
    """Coinbase Commerce has been permanently removed. Stripe + MoonPay only."""
    return {"error": "Coinbase Commerce is not available"}


# Legacy aliases for any remaining references
def create_coinbase_charge(*args, **kwargs):
    return _coinbase_removed()


def verify_coinbase_charge(*args, **kwargs):
    return _coinbase_removed()


def handle_coinbase_webhook(*args, **kwargs):
    return _coinbase_removed()


    # Original Coinbase functions removed


# --- XRPL PAYMENTS (XRP & RLUSD) ---

def get_xrpl_client():
    """Get XRPL client for the configured network."""
    if not XRPL_AVAILABLE:
        return None

    if PAYMENT_CONFIG["xrpl_network"] == "testnet":
        return JsonRpcClient(PAYMENT_CONFIG["xrpl_testnet_url"])
    return JsonRpcClient(PAYMENT_CONFIG["xrpl_mainnet_url"])


def verify_xrp_payment(destination_tag, expected_xrp, tolerance=0.01):
    """
    Verify XRP payment was received.

    Args:
        destination_tag: The destination tag to look for
        expected_xrp: Expected XRP amount
        tolerance: Acceptable variance

    Returns:
        dict with verification result
    """
    if not XRPL_AVAILABLE:
        return {"verified": False, "error": "XRPL not available"}

    client = get_xrpl_client()
    if not client:
        return {"verified": False, "error": "Could not connect to XRPL"}

    try:
        request = AccountTx(
            account=PAYMENT_CONFIG["platform_xrp_address"],
            limit=50
        )
        response = client.request(request)

        if not response.is_successful():
            return {"verified": False, "error": "Failed to query transactions"}

        for tx in response.result.get("transactions", []):
            tx_data = tx.get("tx", {})

            if tx_data.get("TransactionType") != "Payment":
                continue
            if tx_data.get("Destination") != PAYMENT_CONFIG["platform_xrp_address"]:
                continue
            if tx_data.get("DestinationTag") != destination_tag:
                continue

            # Check if it's XRP (not issued currency)
            amount = tx_data.get("Amount")
            if isinstance(amount, str):  # XRP amount is a string of drops
                amount_xrp = float(drops_to_xrp(amount))
                if abs(amount_xrp - expected_xrp) <= tolerance:
                    return {
                        "verified": True,
                        "method": "xrp",
                        "tx_hash": tx_data.get("hash"),
                        "amount_xrp": amount_xrp,
                        "sender": tx_data.get("Account"),
                    }

        return {"verified": False, "error": "Payment not found"}

    except Exception as e:
        return {"verified": False, "error": str(e)}


def verify_rlusd_payment(destination_tag, expected_amount, tolerance=0.01):
    """
    Verify RLUSD stablecoin payment was received.

    Args:
        destination_tag: The destination tag to look for
        expected_amount: Expected RLUSD amount
        tolerance: Acceptable variance

    Returns:
        dict with verification result
    """
    if not XRPL_AVAILABLE:
        return {"verified": False, "error": "XRPL not available"}

    client = get_xrpl_client()
    if not client:
        return {"verified": False, "error": "Could not connect to XRPL"}

    try:
        request = AccountTx(
            account=PAYMENT_CONFIG["platform_xrp_address"],
            limit=50
        )
        response = client.request(request)

        if not response.is_successful():
            return {"verified": False, "error": "Failed to query transactions"}

        for tx in response.result.get("transactions", []):
            tx_data = tx.get("tx", {})

            if tx_data.get("TransactionType") != "Payment":
                continue
            if tx_data.get("Destination") != PAYMENT_CONFIG["platform_xrp_address"]:
                continue
            if tx_data.get("DestinationTag") != destination_tag:
                continue

            # Check if it's RLUSD (issued currency)
            amount = tx_data.get("Amount")
            if isinstance(amount, dict):  # Issued currency is a dict
                if amount.get("currency") == "RLUSD" or amount.get("currency") == "524C555344000000000000000000000000000000":
                    amount_value = float(amount.get("value", 0))
                    if abs(amount_value - expected_amount) <= tolerance:
                        return {
                            "verified": True,
                            "method": "rlusd",
                            "tx_hash": tx_data.get("hash"),
                            "amount_rlusd": amount_value,
                            "sender": tx_data.get("Account"),
                        }

        return {"verified": False, "error": "Payment not found"}

    except Exception as e:
        return {"verified": False, "error": str(e)}


# --- UNIFIED PAYMENT VERIFICATION ---

def verify_payment(method, destination_tag=None, expected_amount=None,
                   session_id=None, deal_id=None, charge_code=None):
    """
    Unified payment verification across all methods.

    Args:
        method: PaymentMethod enum or string
        destination_tag: For XRP/RLUSD payments
        expected_amount: Expected amount (XRP for xrp, USD for rlusd/card)
        session_id: For Stripe card payments
        charge_code: For Coinbase Commerce crypto payments
        deal_id: Deal identifier

    Returns:
        dict with verification result
    """
    if isinstance(method, str):
        method = PaymentMethod(method)

    if method == PaymentMethod.CARD:
        if not session_id:
            return {"verified": False, "error": "Session ID required for card payment"}
        return verify_stripe_session(session_id)

    elif method == PaymentMethod.XRP:
        if not destination_tag or not expected_amount:
            return {"verified": False, "error": "Destination tag and amount required"}
        return verify_xrp_payment(destination_tag, expected_amount)

    elif method == PaymentMethod.RLUSD:
        if not destination_tag or not expected_amount:
            return {"verified": False, "error": "Destination tag and amount required"}
        return verify_rlusd_payment(destination_tag, expected_amount)

    # Coinbase CRYPTO method removed — Stripe + MoonPay only

    return {"verified": False, "error": f"Unknown payment method: {method}"}


# --- PAYMENT DISPLAY HELPERS ---

def format_payment_options_html(options):
    """
    Generate HTML for payment options selection.

    Args:
        options: Result from generate_payment_options()

    Returns:
        HTML string
    """
    fee_usd = options["fee_usd"]
    methods = options["methods"]

    html = f"""
    <div class="payment-options">
        <h3>Pay ${fee_usd:.2f} to unlock this deal</h3>
        <p style="color: #666; margin-bottom: 20px;">Choose your preferred payment method:</p>

        <div class="payment-methods">
    """

    # Card option
    if methods.get("card", {}).get("enabled"):
        html += f"""
            <div class="payment-method" data-method="card">
                <div class="method-icon">💳</div>
                <div class="method-info">
                    <strong>Credit/Debit Card</strong>
                    <span>${fee_usd:.2f} USD</span>
                </div>
                <button class="btn" onclick="payWithCard()">Pay with Card</button>
            </div>
        """

    # XRP option
    if methods.get("xrp", {}).get("enabled"):
        xrp = methods["xrp"]
        html += f"""
            <div class="payment-method" data-method="xrp">
                <div class="method-icon">⚡</div>
                <div class="method-info">
                    <strong>XRP</strong>
                    <span>{xrp['amount_xrp']:.4f} XRP (≈${fee_usd:.2f})</span>
                </div>
                <button class="btn btn-secondary" onclick="showXrpPayment()">Pay with XRP</button>
            </div>
        """

    # RLUSD option
    if methods.get("rlusd", {}).get("enabled"):
        html += f"""
            <div class="payment-method" data-method="rlusd">
                <div class="method-icon">💵</div>
                <div class="method-info">
                    <strong>RLUSD Stablecoin</strong>
                    <span>{fee_usd:.2f} RLUSD (1:1 USD)</span>
                </div>
                <button class="btn btn-secondary" onclick="showRlusdPayment()">Pay with RLUSD</button>
            </div>
        """

    html += """
        </div>
        <p style="color: #999; font-size: 12px; margin-top: 15px;">
            All payment methods provide instant access once confirmed.
        </p>
    </div>
    """

    return html


def get_payment_instructions(method, options):
    """
    Get human-readable payment instructions for a method.

    Args:
        method: Payment method string
        options: Result from generate_payment_options()

    Returns:
        dict with instructions
    """
    methods = options["methods"]

    if method == "card":
        return {
            "title": "Pay with Card",
            "instructions": [
                "Click 'Pay with Card' to open secure checkout",
                "Enter your card details",
                "Complete payment",
                "You'll be redirected back automatically"
            ]
        }

    elif method == "xrp":
        xrp = methods.get("xrp", {})
        return {
            "title": "Pay with XRP",
            "instructions": [
                f"Send exactly {xrp.get('amount_xrp', 0):.4f} XRP",
                f"To address: {xrp.get('destination', '')}",
                f"IMPORTANT: Include destination tag: {xrp.get('destination_tag', '')}",
                "Payment will be verified automatically within seconds"
            ],
            "warning": "Sending without the destination tag may result in lost funds!"
        }

    elif method == "rlusd":
        rlusd = methods.get("rlusd", {})
        return {
            "title": "Pay with RLUSD",
            "instructions": [
                f"Send exactly {rlusd.get('amount_rlusd', 0):.2f} RLUSD",
                f"To address: {rlusd.get('destination', '')}",
                f"IMPORTANT: Include destination tag: {rlusd.get('destination_tag', '')}",
                "RLUSD is Ripple's USD stablecoin on XRPL"
            ],
            "warning": "Sending without the destination tag may result in lost funds!"
        }

    elif method == "crypto":
        crypto = methods.get("crypto", {})
        coins = crypto.get("supported_coins", [])
        return {
            "title": "Pay with Cryptocurrency",
            "instructions": [
                "Click 'Pay with Crypto' to open Coinbase Commerce checkout",
                f"Choose from: {', '.join(coins[:5])}{'...' if len(coins) > 5 else ''}",
                "Send payment from your wallet",
                "You'll be redirected back once confirmed"
            ],
            "note": "Supports Bitcoin, Ethereum, Litecoin, Dogecoin, USDC, and more!"
        }

    return {"title": "Unknown Method", "instructions": []}
