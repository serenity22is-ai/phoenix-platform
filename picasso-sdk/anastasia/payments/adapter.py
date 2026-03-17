"""
Payment Adapter — Abstract base class and adapter registry.

Defines the interface every payment adapter must implement and provides
the AdapterRegistry for managing adapter lifecycle. ANASTASiA uses the
registry to detect a customer's payment system and get the right adapter.

ANASTASiA NEVER replaces the customer's payment system — it adapts to it.
The adapter translates ANASTASiA's unified "charge $X for booking Y" into
the customer's specific payment API calls.

MYSTES KYRIOS LLC — Confidential.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from ..core.types import PaymentProcessor
from .detector import PaymentDetector

logger = logging.getLogger(__name__)


class PaymentAdapter(ABC):
    """
    Abstract base class for all payment adapters.

    Each adapter wraps a specific payment processor's API (Stripe, Adyen,
    Square, etc.) behind a unified interface. ANASTASiA uses this interface
    to execute payment operations without knowing the underlying processor.

    Implementations use the ``requests`` library for HTTP calls rather than
    processor-specific SDKs, keeping the dependency footprint minimal.

    Subclass contract:
        - Implement all abstract methods and properties.
        - Return standardized dict formats from each method.
        - Raise ``PaymentAdapterError`` for recoverable errors.
        - Log all API interactions at DEBUG level.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Human-readable adapter name (e.g., 'stripe', 'adyen').

        Must be unique across all registered adapters.
        """
        ...

    @property
    @abstractmethod
    def processor(self) -> PaymentProcessor:
        """The PaymentProcessor enum value this adapter handles."""
        ...

    @abstractmethod
    def create_charge(
        self,
        amount_cents: int,
        currency: str,
        description: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Create a payment charge.

        Args:
            amount_cents: Amount in the smallest currency unit (e.g., cents).
            currency: ISO 4217 currency code (e.g., 'usd', 'eur').
            description: Human-readable description for the charge.
            metadata: Optional key-value pairs attached to the charge.

        Returns:
            {
                "charge_id": str,
                "status": str,       # "succeeded", "pending", "failed"
                "amount": int,       # amount_cents echoed back
                "currency": str,
                "processor": str,    # adapter name
            }
        """
        ...

    @abstractmethod
    def create_refund(
        self,
        charge_id: str,
        amount_cents: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Create a full or partial refund.

        Args:
            charge_id: The charge/payment identifier to refund.
            amount_cents: If None, full refund. Otherwise partial amount.

        Returns:
            {
                "refund_id": str,
                "charge_id": str,
                "status": str,       # "succeeded", "pending", "failed"
                "amount": int,       # refunded amount in cents
                "processor": str,
            }
        """
        ...

    @abstractmethod
    def get_charge_status(self, charge_id: str) -> Dict[str, Any]:
        """
        Retrieve current status of a charge.

        Args:
            charge_id: The charge/payment identifier.

        Returns:
            {
                "charge_id": str,
                "status": str,
                "amount": int,
                "currency": str,
                "created": int,      # Unix timestamp
                "processor": str,
            }
        """
        ...

    @abstractmethod
    def create_customer(
        self,
        email: str,
        name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a customer record in the payment system.

        Args:
            email: Customer email address.
            name: Optional customer name.

        Returns:
            {
                "customer_id": str,
                "email": str,
                "name": str or None,
                "processor": str,
            }
        """
        ...

    @abstractmethod
    def create_payment_intent(
        self,
        amount_cents: int,
        currency: str,
        customer_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a payment intent (pre-authorization / payment session).

        Args:
            amount_cents: Amount in smallest currency unit.
            currency: ISO 4217 currency code.
            customer_id: Optional customer identifier.

        Returns:
            {
                "intent_id": str,
                "client_secret": str or None,
                "status": str,
                "amount": int,
                "currency": str,
                "processor": str,
            }
        """
        ...

    @abstractmethod
    def verify_webhook(
        self,
        payload: bytes,
        signature: str,
    ) -> Dict[str, Any]:
        """
        Verify the authenticity of an incoming webhook.

        Args:
            payload: Raw request body bytes.
            signature: Signature header value from the webhook request.

        Returns:
            {
                "valid": bool,
                "event_type": str or None,
                "event_id": str or None,
                "processor": str,
            }
        """
        ...

    @abstractmethod
    def health_check(self) -> Dict[str, Any]:
        """
        Check connectivity to the payment processor.

        Returns:
            {
                "healthy": bool,
                "processor": str,
                "latency_ms": float or None,
                "details": str,
            }
        """
        ...


class PaymentAdapterError(Exception):
    """Raised when a payment adapter operation fails."""

    def __init__(
        self,
        message: str,
        processor: str = "",
        charge_id: str = "",
        status_code: int = 0,
    ):
        self.processor = processor
        self.charge_id = charge_id
        self.status_code = status_code
        super().__init__(message)


class AdapterRegistry:
    """
    Registry for payment adapters.

    Manages adapter registration, lookup by processor or name, and
    automatic detection-based adapter selection.

    Usage:
        registry = AdapterRegistry()
        registry.register(StripeAdapter(api_key="sk_..."))
        adapter = registry.get(PaymentProcessor.STRIPE)
        adapter.create_charge(1000, "usd", "Flight booking")

    Auto-detection:
        adapter = registry.detect_and_get({"server.py": code, ".env": env})
    """

    def __init__(self):
        self._adapters: Dict[PaymentProcessor, PaymentAdapter] = {}
        self._name_index: Dict[str, PaymentAdapter] = {}
        self._detector = PaymentDetector()

    def register(self, adapter: PaymentAdapter) -> None:
        """
        Register a payment adapter.

        Args:
            adapter: An initialized PaymentAdapter instance.

        Raises:
            ValueError: If an adapter with the same name is already registered.
        """
        if adapter.processor in self._adapters:
            logger.warning(
                "Replacing existing adapter for processor '%s'",
                adapter.processor.value,
            )

        self._adapters[adapter.processor] = adapter
        self._name_index[adapter.name] = adapter
        logger.info(
            "Registered payment adapter: %s (%s)",
            adapter.name, adapter.processor.value,
        )

    def get(self, processor: PaymentProcessor) -> Optional[PaymentAdapter]:
        """
        Get an adapter by payment processor enum.

        Args:
            processor: PaymentProcessor enum value.

        Returns:
            The registered PaymentAdapter, or None if not found.
        """
        adapter = self._adapters.get(processor)
        if not adapter:
            logger.warning(
                "No adapter registered for processor: %s", processor.value
            )
        return adapter

    def get_by_name(self, name: str) -> Optional[PaymentAdapter]:
        """
        Get an adapter by its string name.

        Args:
            name: Adapter name (e.g., 'stripe', 'adyen').

        Returns:
            The registered PaymentAdapter, or None if not found.
        """
        adapter = self._name_index.get(name)
        if not adapter:
            logger.warning("No adapter registered with name: %s", name)
        return adapter

    def list_adapters(self) -> List[Dict[str, Any]]:
        """
        List all registered adapters with their metadata.

        Returns:
            List of dicts with adapter info:
            [{"name": str, "processor": str, "healthy": bool}, ...]
        """
        result = []
        for adapter in self._adapters.values():
            try:
                health = adapter.health_check()
                healthy = health.get("healthy", False)
            except Exception:
                healthy = False

            result.append({
                "name": adapter.name,
                "processor": adapter.processor.value,
                "healthy": healthy,
            })
        return result

    def detect_and_get(
        self, files: Dict[str, str]
    ) -> Optional[PaymentAdapter]:
        """
        Detect the payment processor from code files and return its adapter.

        Runs the full detection pipeline (code, config, dependencies) and
        returns the adapter for the best-match processor if one is registered.

        Args:
            files: Dict mapping filename -> file content.

        Returns:
            The matching PaymentAdapter, or None if detection fails or
            no adapter is registered for the detected processor.
        """
        processor, confidence = self._detector.detect_all(files)

        if processor == PaymentProcessor.UNKNOWN:
            logger.info("Could not detect payment processor from provided files")
            return None

        logger.info(
            "Auto-detected payment processor: %s (confidence=%.2f)",
            processor.value, confidence,
        )

        adapter = self.get(processor)
        if not adapter:
            logger.warning(
                "Detected processor '%s' but no adapter is registered for it",
                processor.value,
            )
        return adapter

    @property
    def detector(self) -> PaymentDetector:
        """Access the underlying PaymentDetector instance."""
        return self._detector
