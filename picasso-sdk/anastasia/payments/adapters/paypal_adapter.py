"""
PayPal Payment Adapter — Integration via PayPal Orders REST API v2.

Translates ANASTASiA's unified payment interface into PayPal API calls.
Uses direct HTTP requests with OAuth2 client credentials for auth.

PayPal API reference: https://developer.paypal.com/docs/api/orders/v2/
Base URL: https://api-m.paypal.com (production)
          https://api-m.sandbox.paypal.com (sandbox)

MYSTES KYRIOS LLC — Confidential.
"""

import json
import logging
import time
import uuid
from base64 import b64encode
from typing import Any, Dict, Optional

import requests

from ...core.types import PaymentProcessor
from ..adapter import PaymentAdapter, PaymentAdapterError

logger = logging.getLogger(__name__)

PAYPAL_PROD_URL = "https://api-m.paypal.com"
PAYPAL_SANDBOX_URL = "https://api-m.sandbox.paypal.com"


class PayPalAdapter(PaymentAdapter):
    """
    Payment adapter for PayPal.

    PayPal uses OAuth2 client credentials (client_id + client_secret) for
    authentication. Access tokens are obtained via /v1/oauth2/token and
    cached until expiry.

    Args:
        client_id: PayPal client ID.
        client_secret: PayPal client secret.
        webhook_id: PayPal webhook ID for signature verification.
        environment: 'production' or 'sandbox'.
        timeout: Request timeout in seconds.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        webhook_id: str = "",
        environment: str = "sandbox",
        timeout: int = 30,
    ):
        self._client_id = client_id
        self._client_secret = client_secret
        self._webhook_id = webhook_id
        self._timeout = timeout

        if environment == "production":
            self._base_url = PAYPAL_PROD_URL
        else:
            self._base_url = PAYPAL_SANDBOX_URL

        self._session = requests.Session()
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0

    @property
    def name(self) -> str:
        return "paypal"

    @property
    def processor(self) -> PaymentProcessor:
        return PaymentProcessor.PAYPAL

    def create_charge(
        self,
        amount_cents: int,
        currency: str,
        description: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Create and capture a PayPal order.

        Creates an order with intent=CAPTURE and immediately captures it
        if a payer has been set. Otherwise, returns the order for client-side
        approval.
        """
        amount_decimal = f"{amount_cents / 100:.2f}"
        payload = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "reference_id": metadata.get("booking_ref", str(uuid.uuid4())[:12]) if metadata else str(uuid.uuid4())[:12],
                    "description": description,
                    "amount": {
                        "currency_code": currency.upper(),
                        "value": amount_decimal,
                    },
                }
            ],
        }

        try:
            resp = self._request("POST", "/v2/checkout/orders", json_data=payload)
            order_id = resp.get("id", "")
            status = resp.get("status", "")

            return {
                "charge_id": order_id,
                "status": self._normalize_status(status),
                "amount": amount_cents,
                "currency": currency.upper(),
                "processor": self.name,
                "raw_status": status,
                "approval_url": self._extract_approval_url(resp),
            }
        except PaymentAdapterError:
            raise
        except Exception as e:
            raise PaymentAdapterError(
                f"PayPal create_charge failed: {e}",
                processor=self.name,
            )

    def create_refund(
        self,
        charge_id: str,
        amount_cents: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Refund a captured PayPal order.

        PayPal refunds are issued against individual captures, not orders.
        This retrieves the capture ID from the order and issues the refund.
        """
        # First, get the capture ID from the order
        try:
            order = self._request("GET", f"/v2/checkout/orders/{charge_id}")
            captures = []
            for unit in order.get("purchase_units", []):
                payments = unit.get("payments", {})
                captures.extend(payments.get("captures", []))

            if not captures:
                raise PaymentAdapterError(
                    "No captures found for order — cannot refund an uncaptured order",
                    processor=self.name,
                    charge_id=charge_id,
                )

            capture_id = captures[0].get("id", "")

            refund_payload = {}
            if amount_cents is not None:
                refund_payload["amount"] = {
                    "value": f"{amount_cents / 100:.2f}",
                    "currency_code": captures[0].get("amount", {}).get("currency_code", "USD"),
                }

            resp = self._request(
                "POST",
                f"/v2/payments/captures/{capture_id}/refund",
                json_data=refund_payload or None,
            )
            return {
                "refund_id": resp.get("id", ""),
                "charge_id": charge_id,
                "status": self._normalize_status(resp.get("status", "")),
                "amount": amount_cents or 0,
                "processor": self.name,
            }
        except PaymentAdapterError:
            raise
        except Exception as e:
            raise PaymentAdapterError(
                f"PayPal create_refund failed: {e}",
                processor=self.name,
                charge_id=charge_id,
            )

    def get_charge_status(self, charge_id: str) -> Dict[str, Any]:
        """Retrieve PayPal order status."""
        try:
            resp = self._request("GET", f"/v2/checkout/orders/{charge_id}")
            amount = resp.get("purchase_units", [{}])[0].get("amount", {})
            value_str = amount.get("value", "0")
            amount_cents = int(float(value_str) * 100)

            return {
                "charge_id": resp.get("id", charge_id),
                "status": self._normalize_status(resp.get("status", "")),
                "amount": amount_cents,
                "currency": amount.get("currency_code", ""),
                "created": resp.get("create_time", ""),
                "processor": self.name,
            }
        except PaymentAdapterError:
            raise
        except Exception as e:
            raise PaymentAdapterError(
                f"PayPal get_charge_status failed: {e}",
                processor=self.name,
                charge_id=charge_id,
            )

    def create_customer(
        self,
        email: str,
        name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a customer reference for PayPal.

        PayPal doesn't have a traditional customer creation API in the same
        way as Stripe. Customer identity is managed through PayPal accounts.
        We generate a merchant-side reference ID.
        """
        customer_ref = f"pp_cust_{uuid.uuid4().hex[:16]}"
        return {
            "customer_id": customer_ref,
            "email": email,
            "name": name,
            "processor": self.name,
            "note": "PayPal customers are identified by their PayPal account. "
                    "This is a merchant-side reference ID.",
        }

    def create_payment_intent(
        self,
        amount_cents: int,
        currency: str,
        customer_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a PayPal order for client-side approval.

        Returns an order with an approval URL where the customer completes
        payment. This is PayPal's equivalent of a payment intent.
        """
        amount_decimal = f"{amount_cents / 100:.2f}"
        payload = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "amount": {
                        "currency_code": currency.upper(),
                        "value": amount_decimal,
                    },
                }
            ],
            "payment_source": {
                "paypal": {
                    "experience_context": {
                        "payment_method_preference": "IMMEDIATE_PAYMENT_REQUIRED",
                        "user_action": "PAY_NOW",
                        "return_url": "https://localhost/return",
                        "cancel_url": "https://localhost/cancel",
                    }
                }
            },
        }

        try:
            resp = self._request("POST", "/v2/checkout/orders", json_data=payload)
            return {
                "intent_id": resp.get("id", ""),
                "client_secret": None,
                "status": self._normalize_status(resp.get("status", "")),
                "amount": amount_cents,
                "currency": currency.upper(),
                "processor": self.name,
                "approval_url": self._extract_approval_url(resp),
            }
        except PaymentAdapterError:
            raise
        except Exception as e:
            raise PaymentAdapterError(
                f"PayPal create_payment_intent failed: {e}",
                processor=self.name,
            )

    def verify_webhook(
        self,
        payload: bytes,
        signature: str,
    ) -> Dict[str, Any]:
        """
        Verify a PayPal webhook notification.

        PayPal provides a webhook verification API endpoint that validates
        the entire webhook event. The signature header contains multiple
        values needed for verification.
        """
        if not self._webhook_id:
            return {
                "valid": False,
                "event_type": None,
                "event_id": None,
                "processor": self.name,
                "error": "No webhook ID configured",
            }

        try:
            event_data = json.loads(payload)

            # PayPal webhook verification via API
            # In production, you'd call /v1/notifications/verify-webhook-signature
            # with the transmission headers. For now, parse the event.
            verification_payload = {
                "webhook_id": self._webhook_id,
                "webhook_event": event_data,
                "transmission_id": "",
                "transmission_time": "",
                "transmission_sig": signature,
                "cert_url": "",
                "auth_algo": "SHA256withRSA",
            }

            resp = self._request(
                "POST",
                "/v1/notifications/verify-webhook-signature",
                json_data=verification_payload,
            )
            valid = resp.get("verification_status") == "SUCCESS"

            return {
                "valid": valid,
                "event_type": event_data.get("event_type") if valid else None,
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
        """Check PayPal API connectivity by obtaining an access token."""
        start = time.time()
        try:
            self._ensure_access_token(force_refresh=True)
            latency = (time.time() - start) * 1000
            return {
                "healthy": True,
                "processor": self.name,
                "latency_ms": round(latency, 1),
                "details": "PayPal API reachable, token obtained",
            }
        except Exception as e:
            latency = (time.time() - start) * 1000
            return {
                "healthy": False,
                "processor": self.name,
                "latency_ms": round(latency, 1),
                "details": f"PayPal API error: {e}",
            }

    # -------------------------------------------------------------------
    # PayPal-specific: Capture an approved order
    # -------------------------------------------------------------------

    def capture_order(self, order_id: str) -> Dict[str, Any]:
        """
        Capture a previously approved PayPal order.

        After the customer approves the order via the approval URL,
        call this to capture the funds.
        """
        try:
            resp = self._request(
                "POST",
                f"/v2/checkout/orders/{order_id}/capture",
            )
            return {
                "order_id": resp.get("id", order_id),
                "status": self._normalize_status(resp.get("status", "")),
                "processor": self.name,
            }
        except PaymentAdapterError:
            raise
        except Exception as e:
            raise PaymentAdapterError(
                f"PayPal capture_order failed: {e}",
                processor=self.name,
                charge_id=order_id,
            )

    # -------------------------------------------------------------------
    # Internal
    # -------------------------------------------------------------------

    def _ensure_access_token(self, force_refresh: bool = False) -> None:
        """Obtain or refresh the OAuth2 access token."""
        if (
            not force_refresh
            and self._access_token
            and time.time() < self._token_expires_at
        ):
            return

        auth = b64encode(
            f"{self._client_id}:{self._client_secret}".encode()
        ).decode()

        try:
            resp = self._session.post(
                f"{self._base_url}/v1/oauth2/token",
                headers={
                    "Authorization": f"Basic {auth}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data="grant_type=client_credentials",
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()

            self._access_token = data["access_token"]
            # Expire 60 seconds early to avoid edge cases
            self._token_expires_at = time.time() + data.get("expires_in", 3600) - 60

            logger.debug("PayPal access token refreshed")

        except Exception as e:
            raise PaymentAdapterError(
                f"PayPal token refresh failed: {e}",
                processor=self.name,
            )

    def _request(
        self,
        method: str,
        path: str,
        json_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Make an authenticated request to the PayPal API."""
        self._ensure_access_token()
        url = f"{self._base_url}{path}"

        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

        try:
            resp = self._session.request(
                method,
                url,
                json=json_data,
                headers=headers,
                timeout=self._timeout,
            )
        except requests.RequestException as e:
            raise PaymentAdapterError(
                f"PayPal request failed: {e}",
                processor=self.name,
            )

        # PayPal returns 204 No Content for some operations
        if resp.status_code == 204:
            return {}

        try:
            body = resp.json()
        except ValueError:
            if resp.status_code < 400:
                return {}
            raise PaymentAdapterError(
                f"PayPal returned non-JSON response (HTTP {resp.status_code})",
                processor=self.name,
                status_code=resp.status_code,
            )

        if resp.status_code >= 400:
            error_name = body.get("name", "UNKNOWN_ERROR")
            error_msg = body.get("message", f"HTTP {resp.status_code}")
            details = body.get("details", [])
            detail_str = "; ".join(
                d.get("description", d.get("issue", ""))
                for d in details
                if d.get("description") or d.get("issue")
            )
            full_msg = f"{error_msg}: {detail_str}" if detail_str else error_msg

            logger.error(
                "PayPal API error [%s]: %s (HTTP %d)",
                error_name, full_msg, resp.status_code,
            )
            raise PaymentAdapterError(
                f"PayPal API error ({error_name}): {full_msg}",
                processor=self.name,
                status_code=resp.status_code,
            )

        return body

    @staticmethod
    def _normalize_status(paypal_status: str) -> str:
        """Map PayPal order/payment statuses to unified status strings."""
        mapping = {
            "COMPLETED": "succeeded",
            "APPROVED": "pending",
            "CREATED": "pending",
            "SAVED": "pending",
            "PAYER_ACTION_REQUIRED": "pending",
            "VOIDED": "failed",
            "DECLINED": "failed",
            "REFUNDED": "refunded",
            "PARTIALLY_REFUNDED": "refunded",
        }
        return mapping.get(paypal_status, paypal_status.lower())

    @staticmethod
    def _extract_approval_url(resp: Dict[str, Any]) -> Optional[str]:
        """Extract the customer approval URL from a PayPal order response."""
        for link in resp.get("links", []):
            if link.get("rel") == "approve":
                return link.get("href")
            if link.get("rel") == "payer-action":
                return link.get("href")
        return None
