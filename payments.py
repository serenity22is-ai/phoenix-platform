"""
PHOENIX Multi-Payment Gateway

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


class PaymentMethod(Enum):
    CARD = "card"           # Credit/Debit via Stripe
    XRP = "xrp"             # Direct XRP payment
    RLUSD = "rlusd"         # RLUSD stablecoin on XRPL
    CRYPTO = "crypto"       # Any crypto via Coinbase Commerce


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

    # Coinbase Commerce (for any cryptocurrency)
    "coinbase_api_key": os.getenv("COINBASE_COMMERCE_API_KEY", ""),
    "coinbase_webhook_secret": os.getenv("COINBASE_COMMERCE_WEBHOOK_SECRET", ""),

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


# --- PAYMENT OPTIONS GENERATOR ---

def generate_payment_options(deal_id, fee_usd, user_id=None):
    """
    Generate all available payment options for a deal.

    Args:
        deal_id: Unique deal identifier
        fee_usd: Platform fee in USD
        user_id: Optional user ID

    Returns:
        dict with payment options for each method
    """
    get_xrp_price()

    destination_tag = generate_destination_tag(deal_id, user_id)
    xrp_amount = usd_to_xrp(fee_usd)
    expires_at = datetime.utcnow() + timedelta(minutes=PAYMENT_CONFIG["payment_expiry_minutes"])

    options = {
        "deal_id": deal_id,
        "fee_usd": round(fee_usd, 2),
        "expires_at": expires_at.isoformat(),
        "expires_in_minutes": PAYMENT_CONFIG["payment_expiry_minutes"],
        "methods": {}
    }

    # --- CARD PAYMENT (Stripe) ---
    if STRIPE_AVAILABLE and PAYMENT_CONFIG["stripe_secret_key"]:
        options["methods"]["card"] = {
            "enabled": True,
            "provider": "stripe",
            "amount_usd": round(fee_usd, 2),
            "amount_cents": int(fee_usd * 100),
            "publishable_key": PAYMENT_CONFIG["stripe_publishable_key"],
            "description": f"PHOENIX Deal Access - {deal_id}",
        }
    else:
        options["methods"]["card"] = {
            "enabled": False,
            "reason": "Card payments not configured"
        }

    # --- XRP DIRECT ---
    if XRPL_AVAILABLE:
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
    else:
        options["methods"]["xrp"] = {
            "enabled": False,
            "reason": "XRP payments not available"
        }

    # --- RLUSD (Stablecoin on XRPL) ---
    if XRPL_AVAILABLE:
        options["methods"]["rlusd"] = {
            "enabled": True,
            "destination": PAYMENT_CONFIG["platform_xrp_address"],
            "destination_tag": destination_tag,
            "amount_rlusd": round(fee_usd, 2),  # 1:1 with USD
            "currency": "RLUSD",
            "issuer": PAYMENT_CONFIG["rlusd_issuer"],
            "network": PAYMENT_CONFIG["xrpl_network"],
        }
    else:
        options["methods"]["rlusd"] = {
            "enabled": False,
            "reason": "RLUSD payments not available"
        }

    # --- ANY CRYPTOCURRENCY (Coinbase Commerce) ---
    if PAYMENT_CONFIG["coinbase_api_key"]:
        options["methods"]["crypto"] = {
            "enabled": True,
            "provider": "coinbase_commerce",
            "amount_usd": round(fee_usd, 2),
            "supported_coins": ["BTC", "ETH", "LTC", "DOGE", "BCH", "USDC", "DAI", "SHIB"],
            "description": f"PHOENIX Deal Access - {deal_id}",
        }
    else:
        options["methods"]["crypto"] = {
            "enabled": False,
            "reason": "Crypto payments not configured"
        }

    return options


# --- STRIPE CARD PAYMENTS ---

def create_stripe_checkout_session(deal_id, fee_usd, user_email, success_url, cancel_url):
    """
    Create a Stripe Checkout session for card payment.

    Returns:
        dict with session_id and checkout_url
    """
    if not STRIPE_AVAILABLE or not PAYMENT_CONFIG["stripe_secret_key"]:
        return {"error": "Card payments not configured"}

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "unit_amount": int(fee_usd * 100),  # Stripe uses cents
                    "product_data": {
                        "name": "PHOENIX Deal Access",
                        "description": f"Unlock flight savings - Deal {deal_id}",
                    },
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=success_url + f"?session_id={{CHECKOUT_SESSION_ID}}&deal_id={deal_id}",
            cancel_url=cancel_url,
            customer_email=user_email,
            metadata={
                "deal_id": deal_id,
                "fee_usd": str(fee_usd),
            },
            expires_at=int((datetime.utcnow() + timedelta(minutes=30)).timestamp()),
        )

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
        dict with event details
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
                "session_id": session.id,
            }

        return {"event": event.type}

    except stripe.error.SignatureVerificationError:
        return {"error": "Invalid signature"}


# --- COINBASE COMMERCE (Any Cryptocurrency) ---

COINBASE_API_URL = "https://api.commerce.coinbase.com"


def create_coinbase_charge(deal_id, fee_usd, user_email, redirect_url, cancel_url):
    """
    Create a Coinbase Commerce charge for cryptocurrency payment.

    Supports: BTC, ETH, LTC, DOGE, BCH, USDC, DAI, SHIB, and more.

    Args:
        deal_id: Unique deal identifier
        fee_usd: Amount in USD
        user_email: Customer email
        redirect_url: URL after successful payment
        cancel_url: URL if payment cancelled

    Returns:
        dict with charge_id and hosted_url
    """
    import requests

    api_key = PAYMENT_CONFIG["coinbase_api_key"]
    if not api_key:
        return {"error": "Coinbase Commerce not configured"}

    headers = {
        "Content-Type": "application/json",
        "X-CC-Api-Key": api_key,
        "X-CC-Version": "2018-03-22"
    }

    payload = {
        "name": "PHOENIX Deal Access",
        "description": f"Unlock flight savings - Deal {deal_id}",
        "pricing_type": "fixed_price",
        "local_price": {
            "amount": str(round(fee_usd, 2)),
            "currency": "USD"
        },
        "metadata": {
            "deal_id": deal_id,
            "user_email": user_email,
            "fee_usd": str(fee_usd)
        },
        "redirect_url": redirect_url + f"?deal_id={deal_id}",
        "cancel_url": cancel_url
    }

    try:
        response = requests.post(
            f"{COINBASE_API_URL}/charges",
            json=payload,
            headers=headers,
            timeout=30
        )

        if response.status_code == 201:
            data = response.json().get("data", {})
            return {
                "charge_id": data.get("id"),
                "charge_code": data.get("code"),
                "hosted_url": data.get("hosted_url"),
                "expires_at": data.get("expires_at"),
                "supported_coins": list(data.get("addresses", {}).keys()),
            }
        else:
            return {"error": f"Coinbase API error: {response.status_code} - {response.text}"}

    except Exception as e:
        return {"error": str(e)}


def get_coinbase_charge(charge_code):
    """
    Get the status of a Coinbase Commerce charge.

    Args:
        charge_code: The charge code from create_coinbase_charge

    Returns:
        dict with charge details and status
    """
    import requests

    api_key = PAYMENT_CONFIG["coinbase_api_key"]
    if not api_key:
        return {"error": "Coinbase Commerce not configured"}

    headers = {
        "X-CC-Api-Key": api_key,
        "X-CC-Version": "2018-03-22"
    }

    try:
        response = requests.get(
            f"{COINBASE_API_URL}/charges/{charge_code}",
            headers=headers,
            timeout=30
        )

        if response.status_code == 200:
            data = response.json().get("data", {})
            timeline = data.get("timeline", [])
            latest_status = timeline[-1].get("status") if timeline else "NEW"

            # Check for confirmed payment
            payments = data.get("payments", [])
            confirmed_payment = None
            for payment in payments:
                if payment.get("status") == "CONFIRMED":
                    confirmed_payment = payment
                    break

            return {
                "charge_id": data.get("id"),
                "charge_code": data.get("code"),
                "status": latest_status,
                "metadata": data.get("metadata", {}),
                "confirmed": latest_status == "COMPLETED",
                "payment": confirmed_payment,
            }
        else:
            return {"error": f"Coinbase API error: {response.status_code}"}

    except Exception as e:
        return {"error": str(e)}


def verify_coinbase_charge(charge_code):
    """
    Verify a Coinbase Commerce charge was completed.

    Args:
        charge_code: The charge code to verify

    Returns:
        dict with verification result
    """
    result = get_coinbase_charge(charge_code)

    if "error" in result:
        return {"verified": False, "error": result["error"]}

    if result.get("confirmed") or result.get("status") == "COMPLETED":
        payment = result.get("payment", {})
        return {
            "verified": True,
            "method": "crypto",
            "deal_id": result.get("metadata", {}).get("deal_id"),
            "amount_usd": float(result.get("metadata", {}).get("fee_usd", 0)),
            "charge_code": charge_code,
            "crypto_currency": payment.get("value", {}).get("crypto", {}).get("currency"),
            "crypto_amount": payment.get("value", {}).get("crypto", {}).get("amount"),
            "tx_hash": payment.get("transaction_id"),
        }

    return {
        "verified": False,
        "status": result.get("status"),
        "error": "Payment not yet confirmed"
    }


def handle_coinbase_webhook(payload, signature):
    """
    Handle Coinbase Commerce webhook events.

    Args:
        payload: Raw request body
        signature: X-CC-Webhook-Signature header

    Returns:
        dict with event details
    """
    import hmac
    import hashlib
    import json

    webhook_secret = PAYMENT_CONFIG["coinbase_webhook_secret"]
    if not webhook_secret:
        return {"error": "Webhook secret not configured"}

    # Verify signature
    expected_sig = hmac.new(
        webhook_secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(signature, expected_sig):
        return {"error": "Invalid webhook signature"}

    try:
        data = json.loads(payload)
        event = data.get("event", {})
        event_type = event.get("type")
        charge_data = event.get("data", {})

        if event_type == "charge:confirmed":
            return {
                "event": "payment_completed",
                "deal_id": charge_data.get("metadata", {}).get("deal_id"),
                "amount_usd": float(charge_data.get("metadata", {}).get("fee_usd", 0)),
                "charge_code": charge_data.get("code"),
                "charge_id": charge_data.get("id"),
            }
        elif event_type == "charge:failed":
            return {
                "event": "payment_failed",
                "deal_id": charge_data.get("metadata", {}).get("deal_id"),
                "charge_code": charge_data.get("code"),
            }

        return {"event": event_type}

    except Exception as e:
        return {"error": str(e)}


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

    elif method == PaymentMethod.CRYPTO:
        if not charge_code:
            return {"verified": False, "error": "Charge code required for crypto payment"}
        return verify_coinbase_charge(charge_code)

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


# --- P2P ESCROW (Three-Party RLUSD) ---

class P2PEscrowStatus(Enum):
    PENDING = "pending"
    LOCKED = "locked"
    HELPER_ACCEPTED = "helper_accepted"
    PURCHASING = "purchasing"
    CONFIRMED = "confirmed"
    RELEASED = "released"
    CANCELLED = "cancelled"
    DISPUTED = "disputed"


P2P_FEE_CONFIG = {
    "helper_cut_percent": 5.0,
    "platform_cut_percent": 3.0,
    "min_helper_earning_usd": 5.0,
    "escrow_timeout_hours": int(os.getenv("ESCROW_TIMEOUT_HOURS", "24")),
}


def calculate_p2p_amounts(ticket_price_usd):
    """
    Calculate escrow breakdown for a P2P transaction.

    Returns amounts for helper reimbursement, helper earning, platform fee, and total escrow.
    """
    helper_cut = max(
        ticket_price_usd * (P2P_FEE_CONFIG["helper_cut_percent"] / 100),
        P2P_FEE_CONFIG["min_helper_earning_usd"]
    )
    platform_cut = ticket_price_usd * (P2P_FEE_CONFIG["platform_cut_percent"] / 100)
    total_escrow = ticket_price_usd + helper_cut + platform_cut

    return {
        "ticket_price_usd": round(ticket_price_usd, 2),
        "helper_reimbursement": round(ticket_price_usd, 2),
        "helper_earning": round(helper_cut, 2),
        "helper_total": round(ticket_price_usd + helper_cut, 2),
        "platform_fee": round(platform_cut, 2),
        "total_escrow_rlusd": round(total_escrow, 2),
    }


def create_p2p_escrow(buyer_address, helper_address, amounts, condition=None, fulfillment=None):
    """
    Create a P2P XRPL escrow for a three-party transaction.
    Locks buyer's RLUSD with a crypto-condition released on booking confirmation.
    """
    if not XRPL_AVAILABLE:
        return {"error": "XRPL not available"}

    import secrets

    if not condition or not fulfillment:
        fulfillment_bytes = secrets.token_bytes(32)
        fulfillment_hex = fulfillment_bytes.hex()
        condition_hex = hashlib.sha256(fulfillment_bytes).hexdigest()
    else:
        fulfillment_hex = fulfillment
        condition_hex = condition

    cancel_after = datetime.utcnow() + timedelta(
        hours=P2P_FEE_CONFIG["escrow_timeout_hours"]
    )

    escrow_id = f"p2p_{secrets.token_hex(8)}"

    return {
        "escrow_id": escrow_id,
        "buyer_address": buyer_address,
        "helper_address": helper_address,
        "platform_address": PAYMENT_CONFIG["platform_xrp_address"],
        "total_rlusd": amounts["total_escrow_rlusd"],
        "helper_amount_rlusd": amounts["helper_total"],
        "platform_amount_rlusd": amounts["platform_fee"],
        "condition": condition_hex,
        "fulfillment": fulfillment_hex,
        "cancel_after": cancel_after.isoformat(),
        "network": PAYMENT_CONFIG["xrpl_network"],
        "status": "pending",
    }


def verify_p2p_escrow_on_chain(escrow_tx_hash):
    """
    Verify a P2P escrow exists on the XRPL ledger.
    Both buyer and helper can call this to confirm funds are locked.
    """
    if not XRPL_AVAILABLE:
        return {"verified": False, "error": "XRPL not available"}

    client = get_xrpl_client()
    if not client:
        return {"verified": False, "error": "Could not connect to XRPL"}

    try:
        from xrpl.models.requests import Tx
        request = Tx(transaction=escrow_tx_hash)
        response = client.request(request)

        if not response.is_successful():
            return {"verified": False, "error": "Transaction not found on ledger"}

        tx_data = response.result
        tx_type = tx_data.get("TransactionType")

        if tx_type != "EscrowCreate":
            return {"verified": False, "error": f"Transaction is {tx_type}, not EscrowCreate"}

        amount = tx_data.get("Amount")
        if isinstance(amount, dict):
            locked_amount = float(amount.get("value", 0))
            currency = amount.get("currency", "")
        elif isinstance(amount, str):
            locked_amount = float(drops_to_xrp(amount))
            currency = "XRP"
        else:
            locked_amount = 0
            currency = "unknown"

        network = PAYMENT_CONFIG["xrpl_network"]
        if network == "testnet":
            explorer_url = f"https://testnet.xrpl.org/transactions/{escrow_tx_hash}"
        else:
            explorer_url = f"https://livenet.xrpl.org/transactions/{escrow_tx_hash}"

        return {
            "verified": True,
            "tx_hash": escrow_tx_hash,
            "sender": tx_data.get("Account"),
            "destination": tx_data.get("Destination"),
            "amount": locked_amount,
            "currency": currency,
            "condition": tx_data.get("Condition"),
            "cancel_after": tx_data.get("CancelAfter"),
            "finish_after": tx_data.get("FinishAfter"),
            "ledger_index": tx_data.get("ledger_index"),
            "explorer_url": explorer_url,
            "network": network,
        }

    except Exception as e:
        return {"verified": False, "error": str(e)}


def release_p2p_escrow(escrow_tx_hash, fulfillment, helper_address, amounts):
    """
    Release a P2P escrow after booking confirmation.
    Sends RLUSD to helper (reimbursement + cut) and platform (fee).

    In production: submits EscrowFinish transaction to XRPL with fulfillment.
    """
    if not XRPL_AVAILABLE:
        return {"error": "XRPL not available"}

    return {
        "status": "released",
        "escrow_tx_hash": escrow_tx_hash,
        "helper_address": helper_address,
        "helper_amount_rlusd": amounts["helper_total"],
        "platform_amount_rlusd": amounts["platform_fee"],
        "platform_address": PAYMENT_CONFIG["platform_xrp_address"],
    }
