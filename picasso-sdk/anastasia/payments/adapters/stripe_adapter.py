"""
Stripe Payment Adapter — Full integration via Stripe REST API.

This is ANASTASiA's most complete adapter, as Stripe is the primary payment
processor for MYSTES KYRIOS LLC. Uses ``requests`` for HTTP calls against
the Stripe API rather than the official SDK, keeping dependencies minimal.

Stripe API reference: https://stripe.com/docs/api
Base URL: https://api.stripe.com/v1

MYSTES KYRIOS LLC — Confidential.
"""

import hashlib
import hmac
import json
import logging
import time
from typing import Any, Dict, Optional

import requests

from ...core.types import PaymentProcessor
from ..adapter import PaymentAdapter, PaymentAdapterError

logger = logging.getLogger(__name__)

# Stripe API version to pin for consistent behavior
STRIPE_API_VERSION = "2024-12-18.acacia"
STRIPE_BASE_URL = "https://api.stripe.com/v1"


class StripeAdapter(PaymentAdapter):
    """
    Payment adapter for Stripe.

    Translates ANASTASiA's unified payment interface into Stripe API calls.
    Uses direct HTTP requests with Stripe's form-encoded API format.

    Args:
        api_key: Stripe secret key (sk_live_... or sk_test_...).
        webhook_secret: Stripe webhook endpoint secret (whsec_...).
        api_version: Stripe API version to use. Defaults to pinned version.
        timeout: Request timeout in seconds.

    Usage:
        adapter = StripeAdapter(api_key="sk_test_...", webhook_secret="whsec_...")
        result = adapter.create_charge(5000, "usd", "Flight JFK-LHR")
    """

    def __init__(
        self,
        api_key: str,
        webhook_secret: str = "",
        api_version: str = STRIPE_API_VERSION,
        timeout: int = 30,
    ):
        self._api_key = api_key
        self._webhook_secret = webhook_secret
        self._api_version = api_version
        self._timeout = timeout
        self._session = requests.Session()
        self._session.auth = (self._api_key, "")
        self._session.headers.update({
            "Stripe-Version": self._api_version,
            "Content-Type": "application/x-www-form-urlencoded",
        })

    @property
    def name(self) -> str:
        return "stripe"

    @property
    def processor(self) -> PaymentProcessor:
        return PaymentProcessor.STRIPE

    def create_charge(
        self,
        amount_cents: int,
        currency: str,
        description: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Create a charge via Stripe PaymentIntents API.

        Stripe deprecated the Charges API for new integrations.
        This creates a PaymentIntent with automatic confirmation.
        """
        payload = {
            "amount": amount_cents,
            "currency": currency.lower(),
            "description": description,
            "confirm": "true",
            "automatic_payment_methods[enabled]": "true",
            "automatic_payment_methods[allow_redirects]": "never",
        }

        if metadata:
            for key, value in metadata.items():
                payload[f"metadata[{key}]"] = str(value)

        try:
            resp = self._request("POST", "/payment_intents", data=payload)
            return {
                "charge_id": resp.get("id", ""),
                "status": self._normalize_status(resp.get("status", "")),
                "amount": resp.get("amount", amount_cents),
                "currency": resp.get("currency", currency),
                "processor": self.name,
                "raw_status": resp.get("status", ""),
                "client_secret": resp.get("client_secret", ""),
            }
        except PaymentAdapterError:
            raise
        except Exception as e:
            raise PaymentAdapterError(
                f"Stripe create_charge failed: {e}",
                processor=self.name,
            )

    def create_refund(
        self,
        charge_id: str,
        amount_cents: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Create a full or partial refund.

        Args:
            charge_id: The PaymentIntent ID (pi_...) to refund.
            amount_cents: Partial refund amount. None for full refund.
        """
        payload = {"payment_intent": charge_id}
        if amount_cents is not None:
            payload["amount"] = str(amount_cents)

        try:
            resp = self._request("POST", "/refunds", data=payload)
            return {
                "refund_id": resp.get("id", ""),
                "charge_id": charge_id,
                "status": self._normalize_status(resp.get("status", "")),
                "amount": resp.get("amount", amount_cents or 0),
                "processor": self.name,
            }
        except PaymentAdapterError:
            raise
        except Exception as e:
            raise PaymentAdapterError(
                f"Stripe create_refund failed: {e}",
                processor=self.name,
                charge_id=charge_id,
            )

    def get_charge_status(self, charge_id: str) -> Dict[str, Any]:
        """Retrieve a PaymentIntent's current status."""
        try:
            resp = self._request("GET", f"/payment_intents/{charge_id}")
            return {
                "charge_id": resp.get("id", charge_id),
                "status": self._normalize_status(resp.get("status", "")),
                "amount": resp.get("amount", 0),
                "currency": resp.get("currency", ""),
                "created": resp.get("created", 0),
                "processor": self.name,
                "raw_status": resp.get("status", ""),
            }
        except PaymentAdapterError:
            raise
        except Exception as e:
            raise PaymentAdapterError(
                f"Stripe get_charge_status failed: {e}",
                processor=self.name,
                charge_id=charge_id,
            )

    def create_customer(
        self,
        email: str,
        name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a Stripe customer."""
        payload = {"email": email}
        if name:
            payload["name"] = name

        try:
            resp = self._request("POST", "/customers", data=payload)
            return {
                "customer_id": resp.get("id", ""),
                "email": resp.get("email", email),
                "name": resp.get("name"),
                "processor": self.name,
            }
        except PaymentAdapterError:
            raise
        except Exception as e:
            raise PaymentAdapterError(
                f"Stripe create_customer failed: {e}",
                processor=self.name,
            )

    def create_payment_intent(
        self,
        amount_cents: int,
        currency: str,
        customer_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a PaymentIntent without confirming it.

        Returns a client_secret for client-side confirmation (Stripe.js).
        """
        payload = {
            "amount": str(amount_cents),
            "currency": currency.lower(),
            "automatic_payment_methods[enabled]": "true",
        }
        if customer_id:
            payload["customer"] = customer_id

        try:
            resp = self._request("POST", "/payment_intents", data=payload)
            return {
                "intent_id": resp.get("id", ""),
                "client_secret": resp.get("client_secret", ""),
                "status": self._normalize_status(resp.get("status", "")),
                "amount": resp.get("amount", amount_cents),
                "currency": resp.get("currency", currency),
                "processor": self.name,
            }
        except PaymentAdapterError:
            raise
        except Exception as e:
            raise PaymentAdapterError(
                f"Stripe create_payment_intent failed: {e}",
                processor=self.name,
            )

    def verify_webhook(
        self,
        payload: bytes,
        signature: str,
    ) -> Dict[str, Any]:
        """
        Verify a Stripe webhook signature.

        Uses Stripe's v1 signature scheme (HMAC-SHA256 with timestamp).
        """
        if not self._webhook_secret:
            return {
                "valid": False,
                "event_type": None,
                "event_id": None,
                "processor": self.name,
                "error": "No webhook secret configured",
            }

        try:
            # Parse Stripe signature header: t=timestamp,v1=signature
            parts = {}
            for item in signature.split(","):
                key, _, value = item.partition("=")
                parts[key.strip()] = value.strip()

            timestamp = parts.get("t", "")
            sig_v1 = parts.get("v1", "")

            if not timestamp or not sig_v1:
                return {
                    "valid": False,
                    "event_type": None,
                    "event_id": None,
                    "processor": self.name,
                    "error": "Invalid signature format",
                }

            # Compute expected signature
            signed_payload = f"{timestamp}.".encode() + payload
            expected = hmac.new(
                self._webhook_secret.encode(),
                signed_payload,
                hashlib.sha256,
            ).hexdigest()

            valid = hmac.compare_digest(expected, sig_v1)

            # Check timestamp tolerance (5 minutes)
            if valid:
                age = abs(time.time() - int(timestamp))
                if age > 300:
                    valid = False

            # Parse event data
            event_data = json.loads(payload) if valid else {}

            return {
                "valid": valid,
                "event_type": event_data.get("type") if valid else None,
                "event_id": event_data.get("id") if valid else None,
                "processor": self.name,
            }
        except Exception as e:
            return {
                "valid": False,
                "event_type": None,
                "event_id": None,
                "processor": self.name,
                "error": str(e),
            }

    def health_check(self) -> Dict[str, Any]:
        """
        Check Stripe API connectivity by listing zero charges.

        Uses GET /v1/balance which requires only the secret key and is
        lightweight.
        """
        start = time.time()
        try:
            resp = self._request("GET", "/balance")
            latency = (time.time() - start) * 1000

            return {
                "healthy": True,
                "processor": self.name,
                "latency_ms": round(latency, 1),
                "details": "Stripe API reachable",
                "livemode": resp.get("livemode", False),
            }
        except Exception as e:
            latency = (time.time() - start) * 1000
            return {
                "healthy": False,
                "processor": self.name,
                "latency_ms": round(latency, 1),
                "details": f"Stripe API error: {e}",
            }

    # -------------------------------------------------------------------
    # Stripe-specific methods
    # -------------------------------------------------------------------

    def create_checkout_session(
        self,
        amount_cents: int,
        currency: str,
        success_url: str,
        cancel_url: str,
        customer_email: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Create a Stripe Checkout session (hosted payment page).

        This is the simplest integration path — redirect the customer
        to Stripe's hosted checkout page.
        """
        payload = {
            "mode": "payment",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "line_items[0][price_data][currency]": currency.lower(),
            "line_items[0][price_data][unit_amount]": str(amount_cents),
            "line_items[0][price_data][product_data][name]": "MYSTES Booking",
            "line_items[0][quantity]": "1",
        }
        if customer_email:
            payload["customer_email"] = customer_email
        if metadata:
            for key, value in metadata.items():
                payload[f"metadata[{key}]"] = str(value)

        resp = self._request("POST", "/checkout/sessions", data=payload)
        return {
            "session_id": resp.get("id", ""),
            "url": resp.get("url", ""),
            "processor": self.name,
        }

    def list_payment_methods(
        self,
        customer_id: str,
        type: str = "card",
    ) -> Dict[str, Any]:
        """List a customer's saved payment methods."""
        resp = self._request(
            "GET",
            f"/customers/{customer_id}/payment_methods",
            params={"type": type},
        )
        methods = resp.get("data", [])
        return {
            "customer_id": customer_id,
            "payment_methods": [
                {
                    "id": m.get("id"),
                    "type": m.get("type"),
                    "card_brand": m.get("card", {}).get("brand"),
                    "card_last4": m.get("card", {}).get("last4"),
                    "card_exp": (
                        f"{m.get('card', {}).get('exp_month', '')}/"
                        f"{m.get('card', {}).get('exp_year', '')}"
                    ),
                }
                for m in methods
            ],
            "processor": self.name,
        }

    # -------------------------------------------------------------------
    # Internal HTTP helpers
    # -------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Make an authenticated request to the Stripe API.

        Args:
            method: HTTP method (GET, POST, DELETE).
            path: API path (e.g., '/payment_intents').
            data: Form-encoded body data.
            params: Query parameters.

        Returns:
            Parsed JSON response.

        Raises:
            PaymentAdapterError: On HTTP or API errors.
        """
        url = f"{STRIPE_BASE_URL}{path}"

        try:
            resp = self._session.request(
                method,
                url,
                data=data,
                params=params,
                timeout=self._timeout,
            )
        except requests.RequestException as e:
            raise PaymentAdapterError(
                f"Stripe request failed: {e}",
                processor=self.name,
                status_code=0,
            )

        try:
            body = resp.json()
        except ValueError:
            raise PaymentAdapterError(
                f"Stripe returned non-JSON response (HTTP {resp.status_code})",
                processor=self.name,
                status_code=resp.status_code,
            )

        if resp.status_code >= 400:
            error = body.get("error", {})
            msg = error.get("message", f"HTTP {resp.status_code}")
            err_type = error.get("type", "api_error")
            logger.error(
                "Stripe API error [%s]: %s (HTTP %d)",
                err_type, msg, resp.status_code,
            )
            raise PaymentAdapterError(
                f"Stripe API error ({err_type}): {msg}",
                processor=self.name,
                status_code=resp.status_code,
            )

        return body

    @staticmethod
    def _normalize_status(stripe_status: str) -> str:
        """Map Stripe-specific statuses to unified status strings."""
        mapping = {
            "succeeded": "succeeded",
            "requires_payment_method": "pending",
            "requires_confirmation": "pending",
            "requires_action": "pending",
            "processing": "pending",
            "requires_capture": "pending",
            "canceled": "failed",
            "failed": "failed",
        }
        return mapping.get(stripe_status, stripe_status)
