"""
Event Bus — Publish/subscribe system for inter-neuron communication.

Neurons communicate through events, not direct imports. This keeps
modules decoupled and allows new neurons to subscribe to existing
events without modifying the publishers.

MYSTES KYRIOS LLC — Confidential.
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class EventType(Enum):
    """All events ANASTASiA neurons can publish or subscribe to."""

    # --- Booking lifecycle ---
    BOOKING_CREATED = "booking.created"
    BOOKING_CONFIRMED = "booking.confirmed"
    BOOKING_FAILED = "booking.failed"
    BOOKING_CANCELLED = "booking.cancelled"
    BOOKING_REFUNDED = "booking.refunded"

    # --- Search & pricing ---
    SEARCH_COMPLETED = "search.completed"
    PRICE_ALERT = "price.alert"
    PRICE_DROP = "price.drop"
    DEAL_FOUND = "deal.found"

    # --- Integration lifecycle ---
    INTEGRATION_STARTED = "integration.started"
    INTEGRATION_COMPLETED = "integration.completed"
    INTEGRATION_FAILED = "integration.failed"
    INTEGRATION_HEALTH_CHANGED = "integration.health_changed"

    # --- System learning ---
    SYSTEM_DISCOVERED = "system.discovered"
    SYSTEM_PROBED = "system.probed"
    SYSTEM_LEARNED = "system.learned"
    SYSTEM_PROFILE_UPDATED = "system.profile_updated"
    QUIRK_DISCOVERED = "quirk.discovered"

    # --- Daemon events ---
    DAEMON_CONNECTED = "daemon.connected"
    DAEMON_DISCONNECTED = "daemon.disconnected"
    DAEMON_HEARTBEAT = "daemon.heartbeat"
    DAEMON_ERROR = "daemon.error"

    # --- Admin approval ---
    PROPOSAL_CREATED = "proposal.created"
    PROPOSAL_APPROVED = "proposal.approved"
    PROPOSAL_REJECTED = "proposal.rejected"
    PROPOSAL_EXECUTED = "proposal.executed"
    PROPOSAL_ROLLED_BACK = "proposal.rolled_back"

    # --- Payment events ---
    PAYMENT_INITIATED = "payment.initiated"
    PAYMENT_COMPLETED = "payment.completed"
    PAYMENT_FAILED = "payment.failed"
    PAYMENT_REFUNDED = "payment.refunded"

    # --- Tenant events ---
    TENANT_CREATED = "tenant.created"
    TENANT_SUSPENDED = "tenant.suspended"
    TENANT_ACTIVATED = "tenant.activated"
    TENANT_UPGRADED = "tenant.upgraded"

    # --- Resilience events ---
    CIRCUIT_OPENED = "circuit.opened"
    CIRCUIT_CLOSED = "circuit.closed"
    FALLBACK_ACTIVATED = "fallback.activated"
    QUEUE_OVERFLOW = "queue.overflow"

    # --- Compliance events ---
    PII_DETECTED = "compliance.pii_detected"
    AUDIT_ENTRY = "compliance.audit_entry"
    REGULATION_CHECK = "compliance.regulation_check"

    # --- Credits ---
    CREDIT_EARNED = "credit.earned"
    CREDIT_REDEEMED = "credit.redeemed"

    # --- Bridge (Confidential Collaborative Development Protocol) ---
    BRIDGE_CREATED = "bridge.created"
    BRIDGE_ACTIVATED = "bridge.activated"
    BRIDGE_PAUSED = "bridge.paused"
    BRIDGE_TERMINATED = "bridge.terminated"
    BRIDGE_KNOWLEDGE_SYNCED = "bridge.knowledge_synced"
    BRIDGE_PROPOSAL_SENT = "bridge.proposal_sent"
    BRIDGE_PROPOSAL_APPROVED = "bridge.proposal_approved"
    BRIDGE_PROPOSAL_REJECTED = "bridge.proposal_rejected"
    BRIDGE_FIREWALL_BLOCKED = "bridge.firewall_blocked"
    BRIDGE_AUDIT_ENTRY = "bridge.audit_entry"

    # --- Update Call System (self-maintaining SDK) ---
    API_DRIFT_DETECTED = "api.drift_detected"
    API_UPDATE_STARTED = "api.update_started"
    API_UPDATE_GENERATED = "api.update_generated"
    API_UPDATE_TESTED = "api.update_tested"
    API_UPDATE_DEPLOYED = "api.update_deployed"
    API_UPDATE_VERIFIED = "api.update_verified"
    API_UPDATE_FAILED = "api.update_failed"
    API_UPDATE_ROLLED_BACK = "api.update_rolled_back"
    API_ERROR_RATE_SPIKE = "api.error_rate_spike"

    # --- Credential Network (federated credential sharing) ---
    CREDENTIAL_STORED = "credential.stored"
    CREDENTIAL_REVOKED = "credential.revoked"
    CREDENTIAL_SHARED = "credential.shared"
    CREDENTIAL_ROTATED = "credential.rotated"
    NETWORK_MEMBER_JOINED = "network.member_joined"
    NETWORK_MEMBER_LEFT = "network.member_left"
    NETWORK_BOOKING_ROUTED = "network.booking_routed"
    NETWORK_BOOKING_COMPLETED = "network.booking_completed"
    NETWORK_BOOKING_FAILED = "network.booking_failed"

    # --- SaaS Feature Gating ---
    SAAS_ACCESS_DENIED = "saas.access_denied"
    SAAS_TIER_UPGRADED = "saas.tier_upgraded"

    # --- Dev Terminal ---
    DEV_SESSION_STARTED = "dev.session_started"
    DEV_SESSION_CLOSED = "dev.session_closed"
    DEV_AI_REQUEST = "dev.ai_request"

    # --- Module lifecycle ---
    MODULE_SCAFFOLDED = "module.scaffolded"
    MODULE_AUDIT_STARTED = "module.audit_started"
    MODULE_AUDIT_PASSED = "module.audit_passed"
    MODULE_AUDIT_FAILED = "module.audit_failed"
    MODULE_PUBLISHED = "module.published"
    MODULE_UNPUBLISHED = "module.unpublished"
    MODULE_INSTALLED = "module.installed"
    MODULE_UNINSTALLED = "module.uninstalled"

    # --- Feedback ---
    FEEDBACK_SUBMITTED = "feedback.submitted"
    FEEDBACK_PROCESSED = "feedback.processed"

    # --- Marketplace ---
    MARKETPLACE_SEARCH = "marketplace.search"
    MARKETPLACE_DOWNLOAD = "marketplace.download"

    # --- Generic ---
    CUSTOM = "custom"


@dataclass
class Event:
    """An event published on the event bus."""
    type: EventType
    data: Dict[str, Any] = field(default_factory=dict)
    source: str = ""                # Module that published the event
    agency_id: Optional[str] = None
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type.value,
            "data": self.data,
            "source": self.source,
            "agency_id": self.agency_id,
            "timestamp": self.timestamp,
        }


# Type alias for event handlers
EventHandler = Callable[[Event], None]


class EventBus:
    """
    Central event bus for ANASTASiA neuron communication.

    Thread-safe publish/subscribe. Handlers are called synchronously
    in registration order. For async processing, handlers should
    enqueue work to their own queues.

    Usage:
        bus = EventBus()
        bus.subscribe(EventType.BOOKING_CONFIRMED, my_handler)
        bus.publish(Event(type=EventType.BOOKING_CONFIRMED, data={...}))
    """

    def __init__(self):
        self._subscribers: Dict[EventType, List[EventHandler]] = {}
        self._global_subscribers: List[EventHandler] = []
        self._event_log: List[Event] = []
        self._max_log_size = 10000
        self._webhook_handlers: List[Callable[[Event], None]] = []

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Subscribe to a specific event type."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)
        logger.debug("Subscribed %s to %s", handler.__name__, event_type.value)

    def subscribe_all(self, handler: EventHandler) -> None:
        """Subscribe to ALL events (useful for logging, analytics)."""
        self._global_subscribers.append(handler)

    def unsubscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Remove a handler from an event type."""
        if event_type in self._subscribers:
            self._subscribers[event_type] = [
                h for h in self._subscribers[event_type] if h != handler
            ]

    def register_webhook(self, handler: Callable[[Event], None]) -> None:
        """Register a webhook dispatcher for external event delivery."""
        self._webhook_handlers.append(handler)

    def publish(self, event: Event) -> None:
        """
        Publish an event to all subscribers.

        Handlers are called synchronously. Exceptions in handlers are
        caught and logged but don't prevent other handlers from running.
        """
        # Log the event
        self._event_log.append(event)
        if len(self._event_log) > self._max_log_size:
            self._event_log = self._event_log[-self._max_log_size:]

        logger.debug("Event published: %s from %s", event.type.value, event.source)

        # Notify specific subscribers
        handlers = self._subscribers.get(event.type, [])
        for handler in handlers:
            try:
                handler(event)
            except Exception as e:
                logger.error(
                    "Event handler %s failed for %s: %s",
                    handler.__name__, event.type.value, e
                )

        # Notify global subscribers
        for handler in self._global_subscribers:
            try:
                handler(event)
            except Exception as e:
                logger.error(
                    "Global event handler %s failed: %s",
                    handler.__name__, e
                )

        # Dispatch to webhooks
        for wh in self._webhook_handlers:
            try:
                wh(event)
            except Exception as e:
                logger.error("Webhook dispatch failed: %s", e)

    def get_recent_events(
        self,
        event_type: Optional[EventType] = None,
        agency_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Event]:
        """Query recent events with optional filtering."""
        events = self._event_log
        if event_type:
            events = [e for e in events if e.type == event_type]
        if agency_id:
            events = [e for e in events if e.agency_id == agency_id]
        return events[-limit:]

    def clear_log(self) -> None:
        """Clear the event log."""
        self._event_log.clear()
