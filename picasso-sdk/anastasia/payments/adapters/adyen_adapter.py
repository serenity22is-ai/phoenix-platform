"""
Adyen Payment Adapter — Integration via Adyen Checkout REST API.

Translates ANASTASiA's unified payment interface into Adyen API calls.
Uses direct HTTP requests against Adyen's Checkout API v71.

Adyen API reference: https://docs.adyen.com/api-explorer/Checkout/71/overview
Base URL: https://checkout-test.adyen.com (test) / https://checkout-live.adyen.com (live)

MYSTES KYRIOS LLC — Confidential.
"""

import hashlib
import hmac
import json
import logging
import time
import uuid
from base64 import b64encode, b64decode
from typing import Any, Dict, Optional

import requests

from ...core.types import PaymentProcessor
from ..adapter import PaymentAdapter, PaymentAdapterError

logger = logging.getLogger(__name__)

ADYEN_TEST_URL = "https://checkout-test.adyen.com/v71"
ADYEN_LIVE_URL = "https://{live_prefix}-checkout-live.adyenpayments.com/checkout/v71"


class AdyenAdapter(PaymentAdapter):
    """
    Payment adapter for Adyen.

    Adyen uses merchant accounts and API keys for authentication, with
    HMAC-SHA256 for webhook verification.

    Args:
        api_key: Adyen API key.
        merchant_account: Adyen merchant account name.
        hmac_key: HMAC key for webhook signature verification.
        live_prefix: Live URL prefix (required for production).
        environment: 'test' or 'live'.
        timeout: Request timeout in seconds.
    """

    def __init__(
        self,
        api_key: str,
        merchant_account: str,
        hmac_key: str = "",
        live_prefix: str = "",
        environment: str = "test",
        timeout: int = 30,
    ):
        self._api_key = api_key
        self._merchant_account = merchant_account
        self._hmac_key = hmac_key
        self._live_prefix = live_prefix
        self._environment = environment
        self._timeout = timeout

        if environment == "live" and live_prefix:
            self._base_url = ADYEN_LIVE_URL.format(live_prefix=live_prefix)
        else:
            self._base_url = ADYEN_TEST_URL

        self._session = requests.Session()
        self._session.headers.update({
            "X-API-Key": self._api_key,
            "Content-Type": "application/json",
        })

    @property
    def name(self) -> str:
        return "adyen"

    @property
    def processor(self) -> PaymentProcessor:
        return PaymentProcessor.ADYEN

    def create_charge(
        self,
        amount_cents: int,
        currency: str,
        description: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Create a payment via Adyen /payments endpoint.

        Uses server-to-server flow with a payment method (scheme).
        """
        reference = f"anastasia_{uuid.uuid4().hex[:16]}"
        payload = {
            "merchantAccount": self._merchant_account,
            "amount": {
                "value": amount_cents,
                "currency": currency.upper(),
            },
            "reference": reference,
            "description": description,
            "paymentMethod": {"type": "scheme"},
            "returnUrl": "https://localhost/return",
            "metadata": metadata or {},
        }

        try:
            resp = self._request("POST", "/payments", json_data=payload)
            result_code = resp.get("resultCode", "")
            return {
                "charge_id": resp.get("pspReference", reference),
                "status": self._normalize_status(result_code),
                "amount": amount_cents,
                "currency": currency.upper(),
                "processor": self.name,
                "raw_status": result_code,
                "reference": reference,
            }
        except PaymentAdapterError:
            raise
        except Exception as e:
            raise PaymentAdapterError(
                f"Adyen create_charge failed: {e}",
                processor=self.name,
            )

    def create_refund(
        self,
        charge_id: str,
        amount_cents: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Create a refund via Adyen Checkout /payments/{id}/refunds.

        Adyen requires the original pspReference and merchant account.
        """
        payload = {
            "merchantAccount": self._merchant_account,
            "reference": f"refund_{uuid.uuid4().hex[:12]}",
        }
        if amount_cents is not None:
            payload["amount"] = {
                "value": amount_cents,
                "currency": "USD",  # Will be overridden by original charge
            }

        try:
            resp = self._request(
                "POST",
                f"/payments/{charge_id}/refunds",
                json_data=payload,
            )
            return {
                "refund_id": resp.get("pspReference", ""),
                "charge_id": charge_id,
                "status": self._normalize_status(resp.get("status", "received")),
                "amount": amount_cents or 0,
                "processor": self.name,
            }
        except PaymentAdapterError:
            raise
        except Exception as e:
            raise PaymentAdapterError(
                f"Adyen create_refund failed: {e}",
                processor=self.name,
                charge_id=charge_id,
            )

    def get_charge_status(self, charge_id: str) -> Dict[str, Any]:
        """
        Get payment details. Uses Adyen Management API or stored state.

        Note: Adyen's Checkout API does not have a direct GET /payments/{id}.
        Status is typically received via webhooks. This attempts to use the
        data endpoint if available.
        """
        # Adyen doesn't provide a simple GET endpoint for payment status.
        # In production, status tracking relies on webhook notifications.
        # We return a placeholder that indicates webhook-based tracking.
        logger.info(
            "Adyen status check for %s — Adyen uses webhook-based status. "
            "Check notification records.",
            charge_id,
        )
        return {
            "charge_id": charge_id,
            "status": "pending",
            "amount": 0,
            "currency": "",
            "created": 0,
            "processor": self.name,
            "note": "Adyen uses webhook-based status updates. "
                    "Check notification records for current status.",
        }

    def create_customer(
        self,
        email: str,
        name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a shopper reference in Adyen.

        Adyen doesn't have a dedicated customer creation endpoint.
        Shoppers are created implicitly during payment with a shopperReference.
        """
        shopper_ref = f"shopper_{uuid.uuid4().hex[:16]}"
        return {
            "customer_id": shopper_ref,
            "email": email,
            "name": name,
            "processor": self.name,
            "note": "Adyen shoppers are created implicitly during payment. "
                    "Use this shopperReference in payment requests.",
        }

    def create_payment_intent(
        self,
        amount_cents: int,
        currency: str,
        customer_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a payment session via Adyen /sessions endpoint.

        Adyen's sessions API is the equivalent of Stripe's PaymentIntents.
        """
        reference = f"session_{uuid.uuid4().hex[:16]}"
        payload = {
            "merchantAccount": self._merchant_account,
            "amount": {
                "value": amount_cents,
                "currency": currency.upper(),
            },
            "reference": reference,
            "returnUrl": "https://localhost/return",
            "countryCode": "US",
        }
        if customer_id:
            payload["shopperReference"] = customer_id

        try:
            resp = self._request("POST", "/sessions", json_data=payload)
            return {
                "intent_id": resp.get("id", ""),
                "client_secret": resp.get("sessionData", ""),
                "status": "pending",
                "amount": amount_cents,
                "currency": currency.upper(),
                "processor": self.name,
                "reference": reference,
            }
        except PaymentAdapterError:
            raise
        except Exception as e:
            raise PaymentAdapterError(
                f"Adyen create_payment_intent failed: {e}",
                processor=self.name,
            )

    def verify_webhook(
        self,
        payload: bytes,
        signature: str,
    ) -> Dict[str, Any]:
        """
        Verify Adyen webhook HMAC signature.

        Adyen signs notification items with HMAC-SHA256 using the HMAC key.
        """
        if not self._hmac_key:
            return {
                "valid": False,
                "event_type": None,
                "event_id": None,
                "processor": self.name,
                "error": "No HMAC key configured",
            }

        try:
            data = json.loads(payload)
            items = (
                data.get("notificationItems", [{}])
            )
            if not items:
                return {
                    "valid": False,
                    "event_type": None,
                    "event_id": None,
                    "processor": self.name,
                    "error": "No notification items in payload",
                }

            item = items[0].get("NotificationRequestItem", {})

            # Build the signing string
            # Format: pspReference:originalReference:merchantAccountCode:
            #         merchantReference:amount.value:amount.currency:eventCode
            signing_parts = [
                item.get("pspReference", ""),
                item.get("originalReference", ""),
                item.get("merchantAccountCode", ""),
                item.get("merchantReference", ""),
                str(item.get("amount", {}).get("value", "")),
                item.get("amount", {}).get("currency", ""),
                item.get("eventCode", ""),
            ]
            signing_string = ":".join(signing_parts)

            hmac_key_bytes = bytes.fromhex(self._hmac_key)
            computed = b64encode(
                hmac.new(
                    hmac_key_bytes,
                    signing_string.encode("utf-8"),
                    hashlib.sha256,
                ).digest()
            ).decode("utf-8")

            additional_data = item.get("additionalData", {})
            received_hmac = additional_data.get("hmacSignature", "")
            valid = hmac.compare_digest(computed, received_hmac)

            return {
                "valid": valid,
                "event_type": item.get("eventCode") if valid else None,
                "event_id": item.get("pspReference") if valid else None,
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
        """Check Adyen API connectivity via /paymentMethods."""
        start = time.time()
        try:
            payload = {
                "merchantAccount": self._merchant_account,
                "countryCode": "US",
            }
            self._request("POST", "/paymentMethods", json_data=payload)
            latency = (time.time() - start) * 1000
            return {
                "healthy": True,
                "processor": self.name,
                "latency_ms": round(latency, 1),
                "details": "Adyen API reachable",
                "environment": self._environment,
            }
        except Exception as e:
            latency = (time.time() - start) * 1000
            return {
                "healthy": False,
                "processor": self.name,
                "latency_ms": round(latency, 1),
                "details": f"Adyen API error: {e}",
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
        """Make an authenticated request to the Adyen API."""
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
                f"Adyen request failed: {e}",
                processor=self.name,
            )

        try:
            body = resp.json()
        except ValueError:
            raise PaymentAdapterError(
                f"Adyen returned non-JSON response (HTTP {resp.status_code})",
                processor=self.name,
                status_code=resp.status_code,
            )

        if resp.status_code >= 400:
            msg = body.get("message", f"HTTP {resp.status_code}")
            error_code = body.get("errorCode", "unknown")
            logger.error(
                "Adyen API error [%s]: %s (HTTP %d)",
                error_code, msg, resp.status_code,
            )
            raise PaymentAdapterError(
                f"Adyen API error ({error_code}): {msg}",
                processor=self.name,
                status_code=resp.status_code,
            )

        return body

    @staticmethod
    def _normalize_status(adyen_status: str) -> str:
        """Map Adyen result codes to unified status strings."""
        mapping = {
            "Authorised": "succeeded",
            "Refused": "failed",
            "Error": "failed",
            "Cancelled": "failed",
            "Pending": "pending",
            "Received": "pending",
            "RedirectShopper": "pending",
            "IdentifyShopper": "pending",
            "ChallengeShopper": "pending",
            "PresentToShopper": "pending",
            "received": "pending",
        }
        return mapping.get(adyen_status, adyen_status.lower())
