"""
Braintree Payment Adapter — Integration via Braintree Gateway REST API.

Translates ANASTASiA's unified payment interface into Braintree API calls.
Uses direct HTTP requests with Braintree's XML/JSON API.

Braintree (a PayPal subsidiary) uses a merchant ID + public/private key
pair for authentication via HTTP Basic Auth.

Braintree API reference: https://developer.paypal.com/braintree/docs/reference/overview
Base URL: https://api.braintreegateway.com (production)
          https://api.sandbox.braintreegateway.com (sandbox)

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

BRAINTREE_PROD_URL = "https://api.braintreegateway.com"
BRAINTREE_SANDBOX_URL = "https://api.sandbox.braintreegateway.com"


class BraintreeAdapter(PaymentAdapter):
    """
    Payment adapter for Braintree.

    Braintree uses a three-part credential system: merchant_id, public_key,
    and private_key. Authentication is HTTP Basic Auth with public_key as
    username and private_key as password.

    Braintree's native API uses XML, but the GraphQL API uses JSON.
    This adapter uses the GraphQL API for cleaner integration.

    Args:
        merchant_id: Braintree merchant ID.
        public_key: Braintree public key (used as HTTP Basic Auth username).
        private_key: Braintree private key (used as HTTP Basic Auth password).
        environment: 'production' or 'sandbox'.
        timeout: Request timeout in seconds.
    """

    def __init__(
        self,
        merchant_id: str,
        public_key: str,
        private_key: str,
        environment: str = "sandbox",
        timeout: int = 30,
    ):
        self._merchant_id = merchant_id
        self._public_key = public_key
        self._private_key = private_key
        self._timeout = timeout

        if environment == "production":
            self._base_url = f"{BRAINTREE_PROD_URL}/merchants/{merchant_id}"
            self._graphql_url = "https://payments.braintree-api.com/graphql"
        else:
            self._base_url = f"{BRAINTREE_SANDBOX_URL}/merchants/{merchant_id}"
            self._graphql_url = "https://payments.sandbox.braintree-api.com/graphql"

        self._session = requests.Session()
        self._session.auth = (self._public_key, self._private_key)
        self._session.headers.update({
            "Content-Type": "application/json",
            "Braintree-Version": "2024-12-01",
        })

    @property
    def name(self) -> str:
        return "braintree"

    @property
    def processor(self) -> PaymentProcessor:
        return PaymentProcessor.BRAINTREE

    def create_charge(
        self,
        amount_cents: int,
        currency: str,
        description: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Create a transaction via Braintree GraphQL API.

        Uses the chargePaymentMethod mutation. Requires a payment_method_id
        (nonce or vaulted token) in metadata.
        """
        amount_decimal = f"{amount_cents / 100:.2f}"
        payment_method_id = (
            metadata.get("payment_method_id", "fake-valid-nonce")
            if metadata else "fake-valid-nonce"
        )

        query = """
        mutation ChargePaymentMethod($input: ChargePaymentMethodInput!) {
            chargePaymentMethod(input: $input) {
                transaction {
                    id
                    status
                    amount { value currencyCode }
                }
            }
        }
        """
        variables = {
            "input": {
                "paymentMethodId": payment_method_id,
                "transaction": {
                    "amount": amount_decimal,
                    "orderId": metadata.get("booking_ref", "") if metadata else "",
                },
            }
        }

        try:
            resp = self._graphql_request(query, variables)
            txn_data = (
                resp.get("data", {})
                .get("chargePaymentMethod", {})
                .get("transaction", {})
            )
            return {
                "charge_id": txn_data.get("id", ""),
                "status": self._normalize_status(txn_data.get("status", "")),
                "amount": amount_cents,
                "currency": txn_data.get("amount", {}).get("currencyCode", currency),
                "processor": self.name,
                "raw_status": txn_data.get("status", ""),
            }
        except PaymentAdapterError:
            raise
        except Exception as e:
            raise PaymentAdapterError(
                f"Braintree create_charge failed: {e}",
                processor=self.name,
            )

    def create_refund(
        self,
        charge_id: str,
        amount_cents: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Refund a Braintree transaction via GraphQL API.

        Uses the refundTransaction mutation.
        """
        query = """
        mutation RefundTransaction($input: RefundTransactionInput!) {
            refundTransaction(input: $input) {
                refund {
                    id
                    status
                    amount { value }
                }
            }
        }
        """
        variables: Dict[str, Any] = {
            "input": {
                "transactionId": charge_id,
            }
        }
        if amount_cents is not None:
            variables["input"]["amount"] = f"{amount_cents / 100:.2f}"

        try:
            resp = self._graphql_request(query, variables)
            refund_data = (
                resp.get("data", {})
                .get("refundTransaction", {})
                .get("refund", {})
            )
            return {
                "refund_id": refund_data.get("id", ""),
                "charge_id": charge_id,
                "status": self._normalize_status(refund_data.get("status", "")),
                "amount": amount_cents or 0,
                "processor": self.name,
            }
        except PaymentAdapterError:
            raise
        except Exception as e:
            raise PaymentAdapterError(
                f"Braintree create_refund failed: {e}",
                processor=self.name,
                charge_id=charge_id,
            )

    def get_charge_status(self, charge_id: str) -> Dict[str, Any]:
        """
        Get transaction status via Braintree GraphQL search.

        Uses the search query to find the transaction by ID.
        """
        query = """
        query SearchTransaction($input: TransactionSearchInput!) {
            search {
                transactions(input: $input) {
                    edges {
                        node {
                            id
                            status
                            amount { value currencyCode }
                            createdAt
                        }
                    }
                }
            }
        }
        """
        variables = {
            "input": {
                "id": {"is": charge_id},
            }
        }

        try:
            resp = self._graphql_request(query, variables)
            edges = (
                resp.get("data", {})
                .get("search", {})
                .get("transactions", {})
                .get("edges", [])
            )

            if not edges:
                return {
                    "charge_id": charge_id,
                    "status": "unknown",
                    "amount": 0,
                    "currency": "",
                    "created": 0,
                    "processor": self.name,
                    "note": "Transaction not found",
                }

            node = edges[0].get("node", {})
            amount_val = node.get("amount", {}).get("value", "0")
            return {
                "charge_id": node.get("id", charge_id),
                "status": self._normalize_status(node.get("status", "")),
                "amount": int(float(amount_val) * 100),
                "currency": node.get("amount", {}).get("currencyCode", ""),
                "created": node.get("createdAt", ""),
                "processor": self.name,
            }
        except PaymentAdapterError:
            raise
        except Exception as e:
            raise PaymentAdapterError(
                f"Braintree get_charge_status failed: {e}",
                processor=self.name,
                charge_id=charge_id,
            )

    def create_customer(
        self,
        email: str,
        name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a customer in the Braintree Vault via GraphQL.

        Uses the createCustomer mutation.
        """
        query = """
        mutation CreateCustomer($input: CreateCustomerInput!) {
            createCustomer(input: $input) {
                customer {
                    id
                    email
                    firstName
                    lastName
                }
            }
        }
        """
        variables: Dict[str, Any] = {
            "input": {
                "customer": {
                    "email": email,
                }
            }
        }
        if name:
            parts = name.split(" ", 1)
            variables["input"]["customer"]["firstName"] = parts[0]
            if len(parts) > 1:
                variables["input"]["customer"]["lastName"] = parts[1]

        try:
            resp = self._graphql_request(query, variables)
            customer = (
                resp.get("data", {})
                .get("createCustomer", {})
                .get("customer", {})
            )
            full_name = (
                f"{customer.get('firstName', '')} "
                f"{customer.get('lastName', '')}"
            ).strip()
            return {
                "customer_id": customer.get("id", ""),
                "email": customer.get("email", email),
                "name": full_name or name,
                "processor": self.name,
            }
        except PaymentAdapterError:
            raise
        except Exception as e:
            raise PaymentAdapterError(
                f"Braintree create_customer failed: {e}",
                processor=self.name,
            )

    def create_payment_intent(
        self,
        amount_cents: int,
        currency: str,
        customer_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate a client token for Drop-in UI / Hosted Fields.

        Braintree uses client tokens instead of payment intents. The client
        token is used by the browser-side SDK to tokenize payment methods.
        """
        query = """
        mutation CreateClientToken($input: CreateClientTokenInput) {
            createClientToken(input: $input) {
                clientToken
            }
        }
        """
        variables: Dict[str, Any] = {"input": {}}
        if customer_id:
            variables["input"]["clientToken"] = {
                "customerId": customer_id,
            }

        try:
            resp = self._graphql_request(query, variables)
            client_token = (
                resp.get("data", {})
                .get("createClientToken", {})
                .get("clientToken", "")
            )
            return {
                "intent_id": f"bt_intent_{uuid.uuid4().hex[:12]}",
                "client_secret": client_token,
                "status": "pending",
                "amount": amount_cents,
                "currency": currency.upper(),
                "processor": self.name,
            }
        except PaymentAdapterError:
            raise
        except Exception as e:
            raise PaymentAdapterError(
                f"Braintree create_payment_intent failed: {e}",
                processor=self.name,
            )

    def verify_webhook(
        self,
        payload: bytes,
        signature: str,
    ) -> Dict[str, Any]:
        """
        Verify a Braintree webhook notification.

        Braintree webhooks use a bt_signature + bt_payload pair.
        Verification requires matching the signature against the
        public key using SHA-1 HMAC.
        """
        try:
            # Braintree signature format: "public_key|signature_hash"
            if "|" not in signature:
                return {
                    "valid": False,
                    "event_type": None,
                    "event_id": None,
                    "processor": self.name,
                    "error": "Invalid signature format (missing pipe separator)",
                }

            sig_public_key, sig_hash = signature.split("|", 1)

            if sig_public_key != self._public_key:
                return {
                    "valid": False,
                    "event_type": None,
                    "event_id": None,
                    "processor": self.name,
                    "error": "Public key mismatch",
                }

            # Compute HMAC-SHA1 of the payload
            computed = hmac.new(
                self._private_key.encode("utf-8"),
                payload,
                hashlib.sha1,
            ).hexdigest()

            valid = hmac.compare_digest(computed, sig_hash)

            # Braintree payloads are base64-encoded XML; try to parse event type
            event_type = None
            event_id = None
            if valid:
                try:
                    import base64
                    decoded = base64.b64decode(payload).decode("utf-8")
                    # Simple XML extraction for kind and id
                    if "<kind>" in decoded:
                        event_type = decoded.split("<kind>")[1].split("</kind>")[0]
                    if "<id>" in decoded:
                        event_id = decoded.split("<id>")[1].split("</id>")[0]
                except Exception:
                    pass

            return {
                "valid": valid,
                "event_type": event_type,
                "event_id": event_id,
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
        """Check Braintree API connectivity via a ping query."""
        start = time.time()
        try:
            query = "query { ping }"
            self._graphql_request(query, {})
            latency = (time.time() - start) * 1000
            return {
                "healthy": True,
                "processor": self.name,
                "latency_ms": round(latency, 1),
                "details": "Braintree GraphQL API reachable",
            }
        except Exception as e:
            latency = (time.time() - start) * 1000
            return {
                "healthy": False,
                "processor": self.name,
                "latency_ms": round(latency, 1),
                "details": f"Braintree API error: {e}",
            }

    # -------------------------------------------------------------------
    # Internal
    # -------------------------------------------------------------------

    def _graphql_request(
        self,
        query: str,
        variables: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Make an authenticated GraphQL request to Braintree."""
        payload = {
            "query": query,
            "variables": variables,
        }

        try:
            resp = self._session.post(
                self._graphql_url,
                json=payload,
                timeout=self._timeout,
            )
        except requests.RequestException as e:
            raise PaymentAdapterError(
                f"Braintree request failed: {e}",
                processor=self.name,
            )

        try:
            body = resp.json()
        except ValueError:
            raise PaymentAdapterError(
                f"Braintree returned non-JSON response (HTTP {resp.status_code})",
                processor=self.name,
                status_code=resp.status_code,
            )

        if resp.status_code >= 400:
            errors = body.get("errors", [{}])
            error = errors[0] if errors else {}
            msg = error.get("message", f"HTTP {resp.status_code}")
            logger.error(
                "Braintree GraphQL error: %s (HTTP %d)",
                msg, resp.status_code,
            )
            raise PaymentAdapterError(
                f"Braintree GraphQL error: {msg}",
                processor=self.name,
                status_code=resp.status_code,
            )

        # GraphQL can return 200 with errors
        if body.get("errors"):
            errors = body["errors"]
            msg = errors[0].get("message", "Unknown GraphQL error")
            logger.error("Braintree GraphQL error: %s", msg)
            raise PaymentAdapterError(
                f"Braintree GraphQL error: {msg}",
                processor=self.name,
            )

        return body

    @staticmethod
    def _normalize_status(braintree_status: str) -> str:
        """Map Braintree transaction statuses to unified status strings."""
        mapping = {
            "SUBMITTED_FOR_SETTLEMENT": "succeeded",
            "SETTLED": "succeeded",
            "SETTLING": "succeeded",
            "AUTHORIZED": "pending",
            "AUTHORIZING": "pending",
            "SETTLEMENT_PENDING": "pending",
            "VOIDED": "failed",
            "FAILED": "failed",
            "PROCESSOR_DECLINED": "failed",
            "GATEWAY_REJECTED": "failed",
            "SETTLEMENT_DECLINED": "failed",
        }
        return mapping.get(braintree_status, braintree_status.lower())
