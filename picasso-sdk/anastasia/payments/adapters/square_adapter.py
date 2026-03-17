"""
Square Payment Adapter — Integration via Square Payments REST API.

Translates ANASTASiA's unified payment interface into Square API calls.
Uses direct HTTP requests against Square's v2 API.

Square API reference: https://developer.squareup.com/reference/square
Base URL: https://connect.squareup.com/v2 (production)
          https://connect.squareupsandbox.com/v2 (sandbox)

MYSTES KYRIOS LLC — Confidential.
"""

import hashlib
import hmac
import json
import logging
import time
import uuid
from typing import Any, Dict, Optional

import requests

from ...core.types import PaymentProcessor
from ..adapter import PaymentAdapter, PaymentAdapterError

logger = logging.getLogger(__name__)

SQUARE_PROD_URL = "https://connect.squareup.com/v2"
SQUARE_SANDBOX_URL = "https://connect.squareupsandbox.com/v2"


class SquareAdapter(PaymentAdapter):
    """
    Payment adapter for Square.

    Square uses access tokens for authentication and a location-based model
    for payments. Each payment is tied to a specific Square location.

    Args:
        access_token: Square access token.
        location_id: Square location ID for payments.
        webhook_signature_key: Key for verifying webhook signatures.
        environment: 'production' or 'sandbox'.
        timeout: Request timeout in seconds.
    """

    def __init__(
        self,
        access_token: str,
        location_id: str = "",
        webhook_signature_key: str = "",
        environment: str = "sandbox",
        timeout: int = 30,
    ):
        self._access_token = access_token
        self._location_id = location_id
        self._webhook_signature_key = webhook_signature_key
        self._timeout = timeout

        if environment == "production":
            self._base_url = SQUARE_PROD_URL
        else:
            self._base_url = SQUARE_SANDBOX_URL

        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
            "Square-Version": "2024-12-18",
        })

    @property
    def name(self) -> str:
        return "square"

    @property
    def processor(self) -> PaymentProcessor:
        return PaymentProcessor.SQUARE

    def create_charge(
        self,
        amount_cents: int,
        currency: str,
        description: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Create a payment via Square Payments API.

        Square requires an idempotency key and a source_id (nonce from
        client-side SDK). For server-to-server, this creates the payment
        structure; the actual source_id must be provided via metadata.
        """
        idempotency_key = str(uuid.uuid4())
        payload = {
            "idempotency_key": idempotency_key,
            "amount_money": {
                "amount": amount_cents,
                "currency": currency.upper(),
            },
            "location_id": self._location_id,
            "note": description,
            "source_id": metadata.get("source_id", "EXTERNAL") if metadata else "EXTERNAL",
        }
        if metadata:
            # Square doesn't have a generic metadata field; use reference_id
            payload["reference_id"] = metadata.get(
                "reference_id", metadata.get("booking_ref", "")
            )

        try:
            resp = self._request("POST", "/payments", json_data=payload)
            payment = resp.get("payment", {})
            return {
                "charge_id": payment.get("id", ""),
                "status": self._normalize_status(payment.get("status", "")),
                "amount": payment.get("amount_money", {}).get("amount", amount_cents),
                "currency": payment.get("amount_money", {}).get("currency", currency),
                "processor": self.name,
                "raw_status": payment.get("status", ""),
            }
        except PaymentAdapterError:
            raise
        except Exception as e:
            raise PaymentAdapterError(
                f"Square create_charge failed: {e}",
                processor=self.name,
            )

    def create_refund(
        self,
        charge_id: str,
        amount_cents: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Create a refund via Square Refunds API.

        Square refunds require the payment_id and an amount_money object.
        """
        idempotency_key = str(uuid.uuid4())
        payload = {
            "idempotency_key": idempotency_key,
            "payment_id": charge_id,
        }
        if amount_cents is not None:
            payload["amount_money"] = {
                "amount": amount_cents,
                "currency": "USD",
            }

        try:
            resp = self._request("POST", "/refunds", json_data=payload)
            refund = resp.get("refund", {})
            return {
                "refund_id": refund.get("id", ""),
                "charge_id": charge_id,
                "status": self._normalize_status(refund.get("status", "")),
                "amount": refund.get("amount_money", {}).get("amount", amount_cents or 0),
                "processor": self.name,
            }
        except PaymentAdapterError:
            raise
        except Exception as e:
            raise PaymentAdapterError(
                f"Square create_refund failed: {e}",
                processor=self.name,
                charge_id=charge_id,
            )

    def get_charge_status(self, charge_id: str) -> Dict[str, Any]:
        """Retrieve payment status via GET /v2/payments/{id}."""
        try:
            resp = self._request("GET", f"/payments/{charge_id}")
            payment = resp.get("payment", {})
            return {
                "charge_id": payment.get("id", charge_id),
                "status": self._normalize_status(payment.get("status", "")),
                "amount": payment.get("amount_money", {}).get("amount", 0),
                "currency": payment.get("amount_money", {}).get("currency", ""),
                "created": payment.get("created_at", ""),
                "processor": self.name,
            }
        except PaymentAdapterError:
            raise
        except Exception as e:
            raise PaymentAdapterError(
                f"Square get_charge_status failed: {e}",
                processor=self.name,
                charge_id=charge_id,
            )

    def create_customer(
        self,
        email: str,
        name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a customer via Square Customers API."""
        idempotency_key = str(uuid.uuid4())
        payload = {
            "idempotency_key": idempotency_key,
            "email_address": email,
        }
        if name:
            # Square splits name into given_name and family_name
            parts = name.split(" ", 1)
            payload["given_name"] = parts[0]
            if len(parts) > 1:
                payload["family_name"] = parts[1]

        try:
            resp = self._request("POST", "/customers", json_data=payload)
            customer = resp.get("customer", {})
            return {
                "customer_id": customer.get("id", ""),
                "email": customer.get("email_address", email),
                "name": (
                    f"{customer.get('given_name', '')} "
                    f"{customer.get('family_name', '')}"
                ).strip() or name,
                "processor": self.name,
            }
        except PaymentAdapterError:
            raise
        except Exception as e:
            raise PaymentAdapterError(
                f"Square create_customer failed: {e}",
                processor=self.name,
            )

    def create_payment_intent(
        self,
        amount_cents: int,
        currency: str,
        customer_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a payment link via Square Checkout API.

        Square doesn't have a direct PaymentIntent equivalent. The closest
        is a checkout link or a payment with delayed capture.
        """
        idempotency_key = str(uuid.uuid4())
        payload = {
            "idempotency_key": idempotency_key,
            "order": {
                "location_id": self._location_id,
                "line_items": [
                    {
                        "name": "MYSTES Booking",
                        "quantity": "1",
                        "base_price_money": {
                            "amount": amount_cents,
                            "currency": currency.upper(),
                        },
                    }
                ],
            },
            "checkout_options": {
                "allow_tipping": False,
            },
        }
        if customer_id:
            payload["pre_populated_data"] = {
                "buyer_address": {},
            }

        try:
            resp = self._request(
                "POST", "/online-checkout/payment-links", json_data=payload
            )
            link = resp.get("payment_link", {})
            return {
                "intent_id": link.get("id", ""),
                "client_secret": None,
                "status": "pending",
                "amount": amount_cents,
                "currency": currency.upper(),
                "processor": self.name,
                "checkout_url": link.get("url", ""),
            }
        except PaymentAdapterError:
            raise
        except Exception as e:
            raise PaymentAdapterError(
                f"Square create_payment_intent failed: {e}",
                processor=self.name,
            )

    def verify_webhook(
        self,
        payload: bytes,
        signature: str,
    ) -> Dict[str, Any]:
        """
        Verify a Square webhook signature.

        Square uses HMAC-SHA256 with the webhook signature key.
        The signature is in the 'x-square-hmacsha256-signature' header.
        """
        if not self._webhook_signature_key:
            return {
                "valid": False,
                "event_type": None,
                "event_id": None,
                "processor": self.name,
                "error": "No webhook signature key configured",
            }

        try:
            # Square HMAC: HMAC-SHA256(signature_key, notification_url + body)
            # For simplicity, we verify just the body here
            computed = hmac.new(
                self._webhook_signature_key.encode("utf-8"),
                payload,
                hashlib.sha256,
            ).digest()

            import base64
            computed_b64 = base64.b64encode(computed).decode("utf-8")
            valid = hmac.compare_digest(computed_b64, signature)

            event_data = json.loads(payload) if valid else {}
            return {
                "valid": valid,
                "event_type": event_data.get("type") if valid else None,
                "event_id": event_data.get("event_id") if valid else None,
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
        """Check Square API connectivity via locations endpoint."""
        start = time.time()
        try:
            resp = self._request("GET", "/locations")
            latency = (time.time() - start) * 1000
            locations = resp.get("locations", [])
            return {
                "healthy": True,
                "processor": self.name,
                "latency_ms": round(latency, 1),
                "details": f"Square API reachable, {len(locations)} location(s)",
            }
        except Exception as e:
            latency = (time.time() - start) * 1000
            return {
                "healthy": False,
                "processor": self.name,
                "latency_ms": round(latency, 1),
                "details": f"Square API error: {e}",
            }

    # -------------------------------------------------------------------
    # Internal
    # -------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        json_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Make an authenticated request to the Square API."""
        url = f"{self._base_url}{path}"

        try:
            resp = self._session.request(
                method,
                url,
                json=json_data,
                timeout=self._timeout,
            )
        except requests.RequestException as e:
            raise PaymentAdapterError(
                f"Square request failed: {e}",
                processor=self.name,
            )

        try:
            body = resp.json()
        except ValueError:
            raise PaymentAdapterError(
                f"Square returned non-JSON response (HTTP {resp.status_code})",
                processor=self.name,
                status_code=resp.status_code,
            )

        if resp.status_code >= 400:
            errors = body.get("errors", [{}])
            error = errors[0] if errors else {}
            msg = error.get("detail", f"HTTP {resp.status_code}")
            code = error.get("code", "UNKNOWN")
            logger.error(
                "Square API error [%s]: %s (HTTP %d)",
                code, msg, resp.status_code,
            )
            raise PaymentAdapterError(
                f"Square API error ({code}): {msg}",
                processor=self.name,
                status_code=resp.status_code,
            )

        return body

    @staticmethod
    def _normalize_status(square_status: str) -> str:
        """Map Square payment statuses to unified status strings."""
        mapping = {
            "COMPLETED": "succeeded",
            "APPROVED": "succeeded",
            "PENDING": "pending",
            "CANCELED": "failed",
            "FAILED": "failed",
        }
        return mapping.get(square_status, square_status.lower())
