"""
Payments Neuron — Detects and adapts to customer payment systems.

ANASTASiA NEVER replaces a customer's existing payment infrastructure.
Instead, it detects what payment processor they use (Stripe, Adyen,
Square, PayPal, Braintree, etc.) and creates an adapter so it can say
"charge $X for booking Y" — and the adapter translates that into the
customer's payment API calls.

Architecture:
    PaymentDetector  — Scans code/config/deps to identify the processor
    PaymentAdapter   — Abstract interface every adapter implements
    AdapterRegistry  — Manages adapters, auto-detection, lookup
    ReconciliationEngine — Tracks transactions, flags discrepancies
    PaymentsModule   — NeuronModule lifecycle (init, health, shutdown)

Usage:
    from anastasia.payments import PaymentsModule, AdapterRegistry

    module = PaymentsModule()
    module.initialize(event_bus, config)

    adapter = module.registry.detect_and_get({"server.py": code})
    adapter.create_charge(5000, "usd", "Flight JFK-LHR booking")

MYSTES KYRIOS LLC — Confidential.
"""

import logging
from typing import Any, Dict, List

from ..core.events import EventBus, Event, EventType
from ..core.registry import NeuronModule
from ..core.types import PaymentProcessor

from .adapter import AdapterRegistry, PaymentAdapter, PaymentAdapterError
from .detector import PaymentDetector
from .reconciliation import ReconciliationEngine
from .adapters import (
    AdyenAdapter,
    BraintreeAdapter,
    PayPalAdapter,
    SquareAdapter,
    StripeAdapter,
)

logger = logging.getLogger(__name__)


class PaymentsModule(NeuronModule):
    """
    Payments neuron module for ANASTASiA.

    Manages payment adapter lifecycle: detection, registration,
    initialization, health checks, and shutdown.

    Dependencies:
        - knowledge: Uses system profiles to understand customer payment setup.

    Config keys:
        - payments.log_dir: Directory for transaction logs (default: data/payments/logs)
        - payments.stripe.api_key: Stripe secret key
        - payments.stripe.webhook_secret: Stripe webhook secret
        - payments.adyen.api_key: Adyen API key
        - payments.adyen.merchant_account: Adyen merchant account
        - payments.adyen.hmac_key: Adyen HMAC key
        - payments.square.access_token: Square access token
        - payments.square.location_id: Square location ID
        - payments.paypal.client_id: PayPal client ID
        - payments.paypal.client_secret: PayPal client secret
        - payments.braintree.merchant_id: Braintree merchant ID
        - payments.braintree.public_key: Braintree public key
        - payments.braintree.private_key: Braintree private key
    """

    def __init__(self):
        self._registry = AdapterRegistry()
        self._reconciliation: ReconciliationEngine | None = None
        self._event_bus: EventBus | None = None
        self._initialized = False

    @property
    def name(self) -> str:
        return "payments"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def dependencies(self) -> List[str]:
        return ["knowledge"]

    @property
    def registry(self) -> AdapterRegistry:
        """Access the adapter registry."""
        return self._registry

    @property
    def reconciliation(self) -> ReconciliationEngine | None:
        """Access the reconciliation engine (available after initialize)."""
        return self._reconciliation

    def initialize(self, event_bus: EventBus, config: Dict[str, Any]) -> None:
        """
        Initialize the payments module.

        Reads config to register adapters for any processor that has
        credentials configured. Sets up the reconciliation engine.
        """
        self._event_bus = event_bus
        payments_config = config.get("payments", {})

        # Initialize reconciliation engine
        log_dir = payments_config.get("log_dir", "data/payments/logs")
        self._reconciliation = ReconciliationEngine(
            event_bus=event_bus,
            log_dir=log_dir,
        )

        # Register adapters for configured processors
        self._register_configured_adapters(payments_config)

        self._initialized = True
        logger.info(
            "Payments module initialized with %d adapter(s)",
            len(self._registry.list_adapters()),
        )

    def health_check(self) -> Dict[str, Any]:
        """
        Check health of all registered payment adapters.

        Returns:
            {
                "healthy": bool,
                "details": str,
                "adapters": [adapter health dicts],
                "adapter_count": int,
            }
        """
        if not self._initialized:
            return {
                "healthy": False,
                "details": "Payments module not initialized",
                "adapters": [],
                "adapter_count": 0,
            }

        adapter_health = self._registry.list_adapters()
        all_healthy = all(a.get("healthy", False) for a in adapter_health)

        return {
            "healthy": all_healthy or len(adapter_health) == 0,
            "details": (
                f"{len(adapter_health)} adapter(s) registered"
                if adapter_health
                else "No adapters registered (detection pending)"
            ),
            "adapters": adapter_health,
            "adapter_count": len(adapter_health),
        }

    def shutdown(self) -> None:
        """Flush reconciliation logs and cleanup."""
        if self._reconciliation:
            self._reconciliation.flush()
        self._initialized = False
        logger.info("Payments module shut down")

    # -------------------------------------------------------------------
    # Event-publishing payment operations
    # -------------------------------------------------------------------

    def process_payment(
        self,
        processor_name: str,
        amount_cents: int,
        currency: str,
        description: str,
        metadata: Dict[str, Any] | None = None,
        agency_id: str | None = None,
    ) -> Dict[str, Any]:
        """
        Process a payment through the named adapter AND publish events.

        Publishes PAYMENT_INITIATED before the charge and PAYMENT_COMPLETED
        or PAYMENT_FAILED after. This is the correct entry point for all
        payment operations — it ensures compliance gets audit events.

        Args:
            processor_name: Adapter name (e.g., "stripe", "paypal").
            amount_cents: Amount in cents.
            currency: ISO currency code.
            description: Payment description.
            metadata: Optional metadata dict.
            agency_id: Agency for event scoping.

        Returns:
            Adapter charge result dict.
        """
        adapter = self._registry.get(processor_name)
        if not adapter:
            raise PaymentAdapterError(
                f"No adapter registered for '{processor_name}'",
                processor=processor_name,
            )

        payment_data = {
            "processor": processor_name,
            "amount": amount_cents,
            "currency": currency,
            "description": description,
        }

        # Publish PAYMENT_INITIATED
        if self._event_bus:
            self._event_bus.publish(Event(
                type=EventType.PAYMENT_INITIATED,
                source="payments",
                data=payment_data,
                agency_id=agency_id,
            ))

        try:
            result = adapter.create_charge(
                amount_cents=amount_cents,
                currency=currency,
                description=description,
                metadata=metadata,
            )

            # Publish PAYMENT_COMPLETED
            if self._event_bus:
                self._event_bus.publish(Event(
                    type=EventType.PAYMENT_COMPLETED,
                    source="payments",
                    data={
                        **payment_data,
                        "charge_id": result.get("charge_id", ""),
                        "status": result.get("status", ""),
                    },
                    agency_id=agency_id,
                ))

            # Record in reconciliation
            if self._reconciliation:
                self._reconciliation.record_transaction(
                    processor=processor_name,
                    charge_id=result.get("charge_id", ""),
                    amount_cents=amount_cents,
                    currency=currency,
                    status=result.get("status", ""),
                )

            return result

        except Exception as e:
            # Publish PAYMENT_FAILED
            if self._event_bus:
                self._event_bus.publish(Event(
                    type=EventType.PAYMENT_FAILED,
                    source="payments",
                    data={**payment_data, "error": str(e)},
                    agency_id=agency_id,
                ))
            raise

    def process_refund(
        self,
        processor_name: str,
        charge_id: str,
        amount_cents: int | None = None,
        agency_id: str | None = None,
    ) -> Dict[str, Any]:
        """
        Process a refund through the named adapter AND publish events.

        Publishes PAYMENT_REFUNDED on success.

        Args:
            processor_name: Adapter name.
            charge_id: Original charge ID.
            amount_cents: Partial refund amount (None = full).
            agency_id: Agency for event scoping.

        Returns:
            Adapter refund result dict.
        """
        adapter = self._registry.get(processor_name)
        if not adapter:
            raise PaymentAdapterError(
                f"No adapter registered for '{processor_name}'",
                processor=processor_name,
            )

        result = adapter.create_refund(charge_id, amount_cents)

        if self._event_bus:
            self._event_bus.publish(Event(
                type=EventType.PAYMENT_REFUNDED,
                source="payments",
                data={
                    "processor": processor_name,
                    "charge_id": charge_id,
                    "refund_id": result.get("refund_id", ""),
                    "amount": amount_cents,
                    "status": result.get("status", ""),
                },
                agency_id=agency_id,
            ))

        return result

    # -------------------------------------------------------------------
    # Internal
    # -------------------------------------------------------------------

    def _register_configured_adapters(
        self, config: Dict[str, Any]
    ) -> None:
        """Register adapters for processors that have credentials in config."""

        # Stripe
        stripe_cfg = config.get("stripe", {})
        if stripe_cfg.get("api_key"):
            try:
                adapter = StripeAdapter(
                    api_key=stripe_cfg["api_key"],
                    webhook_secret=stripe_cfg.get("webhook_secret", ""),
                )
                self._registry.register(adapter)
            except Exception as e:
                logger.error("Failed to register Stripe adapter: %s", e)

        # Adyen
        adyen_cfg = config.get("adyen", {})
        if adyen_cfg.get("api_key"):
            try:
                adapter = AdyenAdapter(
                    api_key=adyen_cfg["api_key"],
                    merchant_account=adyen_cfg.get("merchant_account", ""),
                    hmac_key=adyen_cfg.get("hmac_key", ""),
                    live_prefix=adyen_cfg.get("live_prefix", ""),
                    environment=adyen_cfg.get("environment", "test"),
                )
                self._registry.register(adapter)
            except Exception as e:
                logger.error("Failed to register Adyen adapter: %s", e)

        # Square
        square_cfg = config.get("square", {})
        if square_cfg.get("access_token"):
            try:
                adapter = SquareAdapter(
                    access_token=square_cfg["access_token"],
                    location_id=square_cfg.get("location_id", ""),
                    webhook_signature_key=square_cfg.get("webhook_signature_key", ""),
                    environment=square_cfg.get("environment", "sandbox"),
                )
                self._registry.register(adapter)
            except Exception as e:
                logger.error("Failed to register Square adapter: %s", e)

        # PayPal
        paypal_cfg = config.get("paypal", {})
        if paypal_cfg.get("client_id") and paypal_cfg.get("client_secret"):
            try:
                adapter = PayPalAdapter(
                    client_id=paypal_cfg["client_id"],
                    client_secret=paypal_cfg["client_secret"],
                    webhook_id=paypal_cfg.get("webhook_id", ""),
                    environment=paypal_cfg.get("environment", "sandbox"),
                )
                self._registry.register(adapter)
            except Exception as e:
                logger.error("Failed to register PayPal adapter: %s", e)

        # Braintree
        braintree_cfg = config.get("braintree", {})
        if braintree_cfg.get("merchant_id"):
            try:
                adapter = BraintreeAdapter(
                    merchant_id=braintree_cfg["merchant_id"],
                    public_key=braintree_cfg.get("public_key", ""),
                    private_key=braintree_cfg.get("private_key", ""),
                    environment=braintree_cfg.get("environment", "sandbox"),
                )
                self._registry.register(adapter)
            except Exception as e:
                logger.error("Failed to register Braintree adapter: %s", e)


__all__ = [
    "PaymentsModule",
    "PaymentDetector",
    "PaymentAdapter",
    "PaymentAdapterError",
    "AdapterRegistry",
    "ReconciliationEngine",
]
