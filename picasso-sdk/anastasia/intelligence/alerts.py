"""
Alert Engine — Price alert creation, monitoring, and notification.

Manages price alerts for agencies: create target-price thresholds,
check current prices against active alerts, and publish events when
alerts trigger. Supports both "below" (price drop) and "above" (price
spike) directions. Rate-limited to one trigger per alert per 24 hours.

Alert state is persisted as JSON on disk and survives restarts.

MYSTES KYRIOS LLC — Confidential.
"""

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.events import Event, EventBus, EventType

logger = logging.getLogger(__name__)

# Rate limit: minimum seconds between triggers for the same alert
_TRIGGER_COOLDOWN_SECONDS = 86400  # 24 hours

# Threshold for automatic PRICE_DROP event (percentage)
_PRICE_DROP_THRESHOLD_PCT = 10.0

# Valid alert statuses
_VALID_STATUSES = frozenset({"active", "paused", "triggered"})

# Valid alert directions
_VALID_DIRECTIONS = frozenset({"below", "above"})


class AlertEngine:
    """
    Price alert management and monitoring engine.

    Creates and manages price alerts for agencies. Each alert monitors
    a route for a target price threshold in a given direction ("below"
    or "above"). When current prices meet the alert condition, the
    engine publishes ``EventType.PRICE_ALERT`` on the event bus.

    Additionally, any price drop exceeding 10% triggers an automatic
    ``EventType.PRICE_DROP`` event, regardless of whether a specific
    alert exists for that route.

    Alerts are persisted to a JSON file on disk and rate-limited to
    one trigger per alert per 24 hours to prevent notification spam.

    Args:
        event_bus: EventBus instance for publishing alert events.
        storage_dir: Path to the directory for persisting alert data.
                     Defaults to ``~/.anastasia/intelligence/alerts``.

    Usage:
        engine = AlertEngine(event_bus)
        alert = engine.create_alert("agency_001", "JFK-LHR", 400.0)
        triggered = engine.check_alerts({"JFK-LHR": 385.0})
    """

    def __init__(
        self,
        event_bus: EventBus,
        storage_dir: Optional[str] = None,
    ):
        self._event_bus = event_bus
        self._lock = threading.Lock()

        if storage_dir is None:
            storage_dir = os.path.join(
                os.path.expanduser("~"), ".anastasia", "intelligence", "alerts"
            )
        self._storage_dir = Path(storage_dir)
        self._storage_dir.mkdir(parents=True, exist_ok=True)

        # In-memory alert store: alert_id -> alert dict
        self._alerts: Dict[str, Dict[str, Any]] = {}

        # Previous prices for price-drop detection: route -> last_price
        self._previous_prices: Dict[str, float] = {}

        # Load persisted alerts
        self._load_alerts()

    # ------------------------------------------------------------------
    # Public API — Alert CRUD
    # ------------------------------------------------------------------

    def create_alert(
        self,
        agency_id: str,
        route: str,
        target_price: float,
        currency: str = "USD",
        direction: str = "below",
    ) -> Dict[str, Any]:
        """
        Create a new price alert.

        Args:
            agency_id: The agency creating the alert.
            route: Route identifier (e.g. ``"JFK-LHR"``).
            target_price: The price threshold to monitor.
            currency: ISO 4217 currency code. Defaults to ``"USD"``.
            direction: ``"below"`` to alert when price drops below target,
                       ``"above"`` to alert when price rises above target.
                       Defaults to ``"below"``.

        Returns:
            The created alert dict with generated ``id`` and metadata.

        Raises:
            ValueError: If direction is not ``"below"`` or ``"above"``.
        """
        direction = direction.lower().strip()
        if direction not in _VALID_DIRECTIONS:
            raise ValueError(
                f"Invalid direction '{direction}'. "
                f"Must be one of: {', '.join(sorted(_VALID_DIRECTIONS))}"
            )

        alert_id = str(uuid.uuid4())[:12]
        now = time.time()

        alert = {
            "id": alert_id,
            "agency_id": agency_id,
            "route": route.upper().strip(),
            "target_price": round(float(target_price), 2),
            "currency": currency.upper().strip(),
            "direction": direction,
            "status": "active",
            "created_at": now,
            "triggered_at": None,
            "last_triggered_at": None,
            "trigger_count": 0,
        }

        with self._lock:
            self._alerts[alert_id] = alert
            self._save_alerts()

        logger.info(
            "Created alert %s: %s %s $%.2f %s for agency %s",
            alert_id, route, direction, target_price, currency, agency_id,
        )
        return alert.copy()

    def check_alerts(
        self,
        current_prices: Dict[str, float],
    ) -> List[Dict[str, Any]]:
        """
        Check all active alerts against current prices.

        Evaluates each active alert's condition against the provided
        current prices. Triggered alerts are published to the event bus
        and their status is updated. Rate-limited to one trigger per
        alert per 24 hours.

        Also checks for price drops exceeding 10% compared to the last
        known price for each route, publishing ``PRICE_DROP`` events
        independently of specific alerts.

        Args:
            current_prices: Dict mapping route identifier to current price.

        Returns:
            List of alert dicts that were triggered in this check.
        """
        triggered = []
        now = time.time()

        with self._lock:
            for alert_id, alert in self._alerts.items():
                # Only check active alerts
                if alert["status"] != "active":
                    continue

                route = alert["route"]
                if route not in current_prices:
                    continue

                current_price = current_prices[route]
                target_price = alert["target_price"]
                direction = alert["direction"]

                # Check if condition is met
                condition_met = False
                if direction == "below" and current_price <= target_price:
                    condition_met = True
                elif direction == "above" and current_price >= target_price:
                    condition_met = True

                if not condition_met:
                    continue

                # Rate limit: max 1 trigger per 24 hours
                last_triggered = alert.get("last_triggered_at")
                if (
                    last_triggered is not None
                    and (now - last_triggered) < _TRIGGER_COOLDOWN_SECONDS
                ):
                    logger.debug(
                        "Alert %s rate-limited (last triggered %.0f sec ago)",
                        alert_id, now - last_triggered,
                    )
                    continue

                # Trigger the alert
                alert["status"] = "triggered"
                alert["triggered_at"] = now
                alert["last_triggered_at"] = now
                alert["trigger_count"] = alert.get("trigger_count", 0) + 1

                triggered.append(alert.copy())

                # Publish PRICE_ALERT event
                self._event_bus.publish(Event(
                    type=EventType.PRICE_ALERT,
                    data={
                        "alert_id": alert_id,
                        "route": route,
                        "target_price": target_price,
                        "current_price": current_price,
                        "direction": direction,
                        "currency": alert["currency"],
                        "trigger_count": alert["trigger_count"],
                    },
                    source="intelligence.alerts",
                    agency_id=alert.get("agency_id"),
                ))

                logger.info(
                    "Alert %s triggered: %s %s target=$%.2f current=$%.2f",
                    alert_id, route, direction, target_price, current_price,
                )

            # Save updated alert states
            if triggered:
                self._save_alerts()

        # Check for significant price drops (independent of alerts)
        self._check_price_drops(current_prices)

        return triggered

    def get_alerts(
        self,
        agency_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve alerts, optionally filtered by agency.

        Args:
            agency_id: If provided, only return alerts for this agency.
                       If ``None``, return all alerts.

        Returns:
            List of alert dicts, sorted by creation time descending.
        """
        with self._lock:
            if agency_id is None:
                alerts = list(self._alerts.values())
            else:
                alerts = [
                    a for a in self._alerts.values()
                    if a.get("agency_id") == agency_id
                ]

        # Sort by created_at descending (newest first)
        alerts.sort(key=lambda a: a.get("created_at", 0), reverse=True)
        return [a.copy() for a in alerts]

    def delete_alert(self, alert_id: str) -> bool:
        """
        Delete an alert by ID.

        Args:
            alert_id: The unique alert identifier.

        Returns:
            ``True`` if the alert was deleted, ``False`` if not found.
        """
        with self._lock:
            if alert_id not in self._alerts:
                return False

            del self._alerts[alert_id]
            self._save_alerts()

        logger.info("Deleted alert %s", alert_id)
        return True

    def pause_alert(self, alert_id: str) -> bool:
        """
        Pause an active or triggered alert.

        Paused alerts are not evaluated during ``check_alerts()``.

        Args:
            alert_id: The unique alert identifier.

        Returns:
            ``True`` if the alert was paused, ``False`` if not found.
        """
        with self._lock:
            alert = self._alerts.get(alert_id)
            if alert is None:
                return False

            alert["status"] = "paused"
            self._save_alerts()

        logger.info("Paused alert %s", alert_id)
        return True

    def resume_alert(self, alert_id: str) -> bool:
        """
        Resume a paused alert, setting its status back to active.

        Args:
            alert_id: The unique alert identifier.

        Returns:
            ``True`` if the alert was resumed, ``False`` if not found.
        """
        with self._lock:
            alert = self._alerts.get(alert_id)
            if alert is None:
                return False

            alert["status"] = "active"
            self._save_alerts()

        logger.info("Resumed alert %s", alert_id)
        return True

    # ------------------------------------------------------------------
    # Price drop detection
    # ------------------------------------------------------------------

    def _check_price_drops(
        self,
        current_prices: Dict[str, float],
    ) -> None:
        """
        Check for significant price drops and publish PRICE_DROP events.

        A price drop is defined as a decrease of more than 10% compared
        to the last known price for a route. This is independent of
        any specific alert configuration.

        Args:
            current_prices: Dict mapping route to current price.
        """
        for route, current_price in current_prices.items():
            previous_price = self._previous_prices.get(route)

            if previous_price is not None and previous_price > 0:
                drop_pct = (
                    (previous_price - current_price) / previous_price
                ) * 100.0

                if drop_pct >= _PRICE_DROP_THRESHOLD_PCT:
                    self._event_bus.publish(Event(
                        type=EventType.PRICE_DROP,
                        data={
                            "route": route,
                            "previous_price": round(previous_price, 2),
                            "current_price": round(current_price, 2),
                            "drop_pct": round(drop_pct, 2),
                        },
                        source="intelligence.alerts",
                    ))

                    logger.info(
                        "Price drop detected: %s $%.2f -> $%.2f (%.1f%%)",
                        route, previous_price, current_price, drop_pct,
                    )

            # Update previous price for next check
            self._previous_prices[route] = current_price

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_alerts(self) -> None:
        """Persist all alerts to disk as JSON (must hold lock)."""
        file_path = self._storage_dir / "alerts.json"
        try:
            alerts_list = list(self._alerts.values())
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(alerts_list, f, indent=2, ensure_ascii=False)
        except OSError as e:
            logger.error("Failed to save alerts to %s: %s", file_path, e)

    def _load_alerts(self) -> None:
        """Load alerts from disk into memory."""
        file_path = self._storage_dir / "alerts.json"
        if not file_path.exists():
            return

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                alerts_list = json.load(f)

            for alert in alerts_list:
                alert_id = alert.get("id")
                if alert_id:
                    self._alerts[alert_id] = alert

            logger.info(
                "Loaded %d alerts from %s", len(self._alerts), file_path
            )
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load alerts from %s: %s", file_path, e)
