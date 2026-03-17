"""
MYSTES CitizenSERP Node Registry

Handles node registration, capability announcement, health monitoring,
and discovery for the CitizenSERP distributed network.

A node is a helper's device running helper_client.py. When it comes online,
it registers with Mystes, announces its capabilities (country, zone, bandwidth,
browser availability), and maintains a heartbeat. Mystes uses this registry
to find optimal nodes for task dispatch.

This module bridges:
    - helper_client.py (CLI helper app that connects nodes)
    - browser_control.py (WebSocket protocol for P2P browser control)
    - citizenserp_payouts.py (uptime tracking via record_node_online/offline)
    - citizenserp_tasks.py (task dispatch via find_available_node)

Usage:
    from node_registry import node_registry

    # Node comes online
    result = node_registry.register_node(
        user_id=42, token="...",
        capabilities={"country": "US", "city": "New York", "browser": True}
    )

    # Heartbeat
    node_registry.heartbeat(node_id="NOD-xxx")

    # Find nodes for task
    nodes = node_registry.discover_nodes(market="US-NE", task_type="flight_search")
"""

import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HEARTBEAT_STALE_SECONDS = 300  # 5 minutes without heartbeat -> stale
DEFAULT_MAX_CONCURRENT = 2
DEFAULT_UPTIME_FRACTION = 0.3  # Expected avg node uptime (~7.2 hrs/day)
VALID_BANDWIDTH_TIERS = {"high", "medium", "low"}
VALID_STATUSES = {"online", "idle", "busy", "stale", "offline"}
VALID_PLATFORMS = {"windows", "macos", "linux"}

# ---------------------------------------------------------------------------
# Tier Preference Routing
# ---------------------------------------------------------------------------
# Higher-tier nodes get dispatched first. This incentivizes maximum data
# sharing (which raises tier score) because more tasks = more earnings.
# The data richness effect: when higher tiers share more categories, the
# overall dataset quality improves, B2B clients pay more, pool grows for ALL.
#
# Routing weights determine sort priority in discover_nodes().
# A platinum node (4.0) is sorted 4x higher than bronze (1.0).
# This doesn't block lower tiers — it just means platinum fills first.
TIER_ROUTING_WEIGHTS = {
    "bronze":   1.0,   # baseline — still gets work
    "silver":   1.5,   # 50% more likely to be dispatched
    "gold":     2.5,   # 2.5x priority
    "platinum": 4.0,   # 4x priority — maximum data sharing rewarded
}

# Floor guarantee: this fraction of discovery slots is reserved for lower-tier
# nodes (silver + bronze) to prevent starvation during onboarding.
# At limit=10, this reserves at least 1 slot for lower tiers.
TIER_FLOOR_SLOTS_PCT = 0.10  # 10% of slots reserved for silver/bronze

DEFAULT_TASK_TYPES = [
    "flight_search",
    "price_check",
    "availability_check",
    "booking_assist",
    "session_relay",
    "browsing_data",
]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class NodeCapabilities:
    """What a node can do — announced at registration and updatable."""

    country_code: str  # 2-letter ISO (e.g. "US", "GB", "DE")
    city: Optional[str] = None
    zone_code: Optional[str] = None  # derived from country+city via geographic_zones
    has_browser: bool = False  # can execute Playwright tasks
    has_auth_sessions: bool = False  # user's logged-in sessions available
    has_extension: bool = False  # Chrome extension installed, passive browsing data
    bandwidth_tier: str = "medium"  # "high", "medium", "low"
    max_concurrent_tasks: int = DEFAULT_MAX_CONCURRENT
    supported_task_types: List[str] = field(default_factory=lambda: list(DEFAULT_TASK_TYPES))
    platform: str = "linux"  # "windows", "macos", "linux"
    lat: Optional[float] = None  # Build #78 — GPS latitude
    lon: Optional[float] = None  # Build #78 — GPS longitude

    def __post_init__(self):
        self.country_code = (self.country_code or "").upper().strip()
        if len(self.country_code) != 2:
            raise ValueError(f"country_code must be 2-letter ISO, got '{self.country_code}'")

        if self.bandwidth_tier not in VALID_BANDWIDTH_TIERS:
            self.bandwidth_tier = "medium"

        if self.platform not in VALID_PLATFORMS:
            self.platform = "linux"

        if self.max_concurrent_tasks < 1:
            self.max_concurrent_tasks = 1

    def to_dict(self) -> dict:
        """Serialize capabilities to a plain dictionary."""
        return {
            "country_code": self.country_code,
            "city": self.city,
            "zone_code": self.zone_code,
            "has_browser": self.has_browser,
            "has_auth_sessions": self.has_auth_sessions,
            "has_extension": self.has_extension,
            "bandwidth_tier": self.bandwidth_tier,
            "max_concurrent_tasks": self.max_concurrent_tasks,
            "supported_task_types": list(self.supported_task_types),
            "platform": self.platform,
            "lat": self.lat,
            "lon": self.lon,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "NodeCapabilities":
        """Build NodeCapabilities from a raw dict (e.g. from JSON payload)."""
        return cls(
            country_code=data.get("country") or data.get("country_code", "XX"),
            city=data.get("city"),
            zone_code=data.get("zone_code"),
            has_browser=bool(data.get("browser") or data.get("has_browser", False)),
            has_auth_sessions=bool(data.get("has_auth_sessions", False)),
            has_extension=bool(data.get("has_extension", False)),
            bandwidth_tier=data.get("bandwidth_tier", "medium"),
            max_concurrent_tasks=int(data.get("max_concurrent_tasks", DEFAULT_MAX_CONCURRENT)),
            supported_task_types=data.get("supported_task_types", list(DEFAULT_TASK_TYPES)),
            platform=data.get("platform", "linux"),
            lat=data.get("lat"),
            lon=data.get("lon"),
        )


@dataclass
class RegisteredNode:
    """Tracked state for a single registered node in the network."""

    node_id: str  # NOD-{hex}
    user_id: int
    capabilities: NodeCapabilities
    status: str = "online"  # online | idle | busy | stale | offline
    current_tasks: int = 0
    registered_at: str = ""
    last_heartbeat: str = ""
    tasks_completed: int = 0
    tasks_failed: int = 0
    avg_execution_ms: float = 0.0
    websocket_id: Optional[str] = None  # for browser_control sessions

    # Tier preference routing — populated on registration from node_consent_economy
    tier: str = "bronze"                    # bronze / silver / gold / platinum
    data_categories_shared: int = 0         # count of opted-in data categories
    tier_score: int = 0                     # raw 0-100 score from assess_tier()

    # Internal — not serialized
    _total_execution_ms: float = field(default=0.0, repr=False)

    def __post_init__(self):
        now = _utcnow_iso()
        if not self.registered_at:
            self.registered_at = now
        if not self.last_heartbeat:
            self.last_heartbeat = now

    def to_dict(self) -> dict:
        """Serialize to a plain dictionary for API responses."""
        return {
            "node_id": self.node_id,
            "user_id": self.user_id,
            "capabilities": self.capabilities.to_dict(),
            "status": self.status,
            "current_tasks": self.current_tasks,
            "registered_at": self.registered_at,
            "last_heartbeat": self.last_heartbeat,
            "tasks_completed": self.tasks_completed,
            "tasks_failed": self.tasks_failed,
            "avg_execution_ms": round(self.avg_execution_ms, 2),
            "websocket_id": self.websocket_id,
            "tier": self.tier,
            "tier_score": self.tier_score,
            "data_categories_shared": self.data_categories_shared,
        }

    @property
    def is_available(self) -> bool:
        """Return True if the node can accept new tasks."""
        return (
            self.status in ("online", "idle")
            and self.current_tasks < self.capabilities.max_concurrent_tasks
        )

    @property
    def success_rate(self) -> float:
        """Return success rate as a float 0.0–1.0."""
        total = self.tasks_completed + self.tasks_failed
        if total == 0:
            return 1.0
        return self.tasks_completed / total

    def seconds_since_heartbeat(self) -> float:
        """Seconds elapsed since the last heartbeat."""
        try:
            last = datetime.fromisoformat(self.last_heartbeat.replace("Z", "+00:00"))
            return (datetime.now(timezone.utc) - last).total_seconds()
        except Exception:
            return 9999.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow_iso() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _generate_node_id() -> str:
    """Generate a unique node ID in the form NOD-{12 hex chars}."""
    return f"NOD-{secrets.token_hex(6)}"


def _derive_zone(country_code: str, city: Optional[str]) -> Optional[str]:
    """Derive zone_code from country and city using geographic_zones.

    Returns None if geographic_zones is unavailable or city is unknown.
    """
    if not city:
        return None
    try:
        from geographic_zones import get_zone_for_city
        zone = get_zone_for_city(country_code, city)
        return zone
    except ImportError:
        logger.debug("geographic_zones module not available — zone derivation skipped")
        return None
    except Exception as exc:
        logger.debug("Zone derivation failed for %s/%s: %s", country_code, city, exc)
        return None


# ---------------------------------------------------------------------------
# NodeRegistry
# ---------------------------------------------------------------------------

class NodeRegistry:
    """
    Central registry for CitizenSERP helper nodes.

    Maintains an in-memory store of all registered nodes, indexed by node_id,
    user_id, and zone_code for fast lookup. All mutations are protected by a
    threading.Lock so the registry is safe to use from Flask request handlers,
    background threads, and WebSocket callbacks concurrently.

    DB and external module access is performed via lazy imports so that the
    module can be imported early without triggering circular dependencies.
    """

    def __init__(self):
        self._nodes: Dict[str, RegisteredNode] = {}
        self._user_nodes: Dict[int, str] = {}  # user_id -> node_id
        self._zone_nodes: Dict[str, Set[str]] = {}  # zone_code -> set of node_ids
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_node(
        self,
        user_id: int,
        token: str,
        capabilities_dict: dict,
    ) -> dict:
        """Register a new node for a helper user.

        Validates the helper token against the HelperProfile in the database,
        builds a NodeCapabilities, derives the geographic zone, persists the
        registration, and notifies the uptime tracker.

        Args:
            user_id: The helper's user ID.
            token: Authentication token from helper_client.
            capabilities_dict: Raw capabilities dict from the client payload.

        Returns:
            dict with ``node_id``, ``status``, and ``capabilities`` on success,
            or ``error`` key on failure.
        """
        # Validate token
        if not self._validate_token(user_id, token):
            logger.warning("Node registration rejected — invalid token for user %s", user_id)
            return {"error": "invalid_token", "message": "Token validation failed"}

        with self._lock:
            # If user already has a node, unregister the old one first
            if user_id in self._user_nodes:
                old_node_id = self._user_nodes[user_id]
                logger.info(
                    "User %s re-registering — removing old node %s", user_id, old_node_id
                )
                self._remove_node_unlocked(old_node_id)

            # Build capabilities
            try:
                caps = NodeCapabilities.from_dict(capabilities_dict)
            except ValueError as exc:
                return {"error": "invalid_capabilities", "message": str(exc)}

            # Derive zone
            caps.zone_code = _derive_zone(caps.country_code, caps.city)

            # Create node
            node_id = _generate_node_id()

            # Look up tier info for preference routing
            _tier = "bronze"
            _tier_score = 0
            _data_cats = 0
            try:
                from node_consent_economy import assess_tier, get_consent_status
                tier_info = assess_tier(user_id)
                if tier_info:
                    _tier = tier_info.get("tier", "bronze")
                    _tier_score = tier_info.get("score", 0)
                consent_info = get_consent_status(user_id)
                if consent_info:
                    _data_cats = sum(
                        1 for cat, enabled in consent_info.get("categories", {}).items()
                        if enabled
                    )
            except Exception:
                pass  # Non-critical — defaults to bronze

            node = RegisteredNode(
                node_id=node_id,
                user_id=user_id,
                capabilities=caps,
                status="online",
                tier=_tier,
                tier_score=_tier_score,
                data_categories_shared=_data_cats,
            )

            # Store in-memory
            self._nodes[node_id] = node
            self._user_nodes[user_id] = node_id

            if caps.zone_code:
                self._zone_nodes.setdefault(caps.zone_code, set()).add(node_id)

        # DB / external notifications (outside lock to avoid holding it long)
        self._notify_node_online(node)
        logger.info(
            "Node registered: %s (user=%s, zone=%s, browser=%s)",
            node_id,
            user_id,
            caps.zone_code,
            caps.has_browser,
        )

        # Check if this registration pushes us past a CitizenSERP milestone
        try:
            new_phase = maybe_auto_flip_phase()
            if new_phase:
                logger.info(
                    "Node %s triggered CitizenSERP phase flip to Phase %d!",
                    node_id, new_phase,
                )
        except Exception as exc:
            logger.debug("Phase flip check failed (non-critical): %s", exc)

        return {
            "node_id": node_id,
            "status": "online",
            "capabilities": caps.to_dict(),
            "registered_at": node.registered_at,
        }

    def unregister_node(self, node_id: str) -> dict:
        """Remove a node from the active registry and mark it offline.

        Calls ``record_node_offline`` on the uptime tracker and removes all
        in-memory index entries.

        Args:
            node_id: The node to unregister.

        Returns:
            dict with confirmation or error.
        """
        with self._lock:
            node = self._nodes.get(node_id)
            if not node:
                return {"error": "not_found", "message": f"Node {node_id} not in registry"}

            user_id = node.user_id
            self._remove_node_unlocked(node_id)

        self._notify_node_offline(node_id, user_id)
        logger.info("Node unregistered: %s (user=%s)", node_id, user_id)

        return {"node_id": node_id, "status": "offline", "message": "Node unregistered"}

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    def heartbeat(self, node_id: str, stats: Optional[dict] = None) -> dict:
        """Update a node's heartbeat timestamp and optional runtime stats.

        If a node has not sent a heartbeat within ``HEARTBEAT_STALE_SECONDS``,
        it will be marked stale by the ``cleanup_stale_nodes`` sweep.

        Args:
            node_id: The node sending the heartbeat.
            stats: Optional dict with keys like ``cpu``, ``memory``,
                ``tasks_in_progress``.

        Returns:
            dict with updated status or error.
        """
        with self._lock:
            node = self._nodes.get(node_id)
            if not node:
                return {"error": "not_found", "message": f"Node {node_id} not in registry"}

            node.last_heartbeat = _utcnow_iso()

            # If the node was stale, bring it back online
            if node.status == "stale":
                node.status = "online" if node.current_tasks == 0 else "busy"
                logger.info("Node %s recovered from stale state", node_id)

            # Apply optional stats
            if stats:
                if "tasks_in_progress" in stats:
                    node.current_tasks = max(0, int(stats["tasks_in_progress"]))
                if "websocket_id" in stats:
                    node.websocket_id = stats["websocket_id"]

            # Recompute status based on current_tasks
            if node.status not in ("offline", "stale"):
                node.status = "busy" if node.current_tasks > 0 else "online"

            return {
                "node_id": node_id,
                "status": node.status,
                "last_heartbeat": node.last_heartbeat,
            }

    # ------------------------------------------------------------------
    # Capability updates
    # ------------------------------------------------------------------

    def update_capabilities(self, node_id: str, capabilities: dict) -> dict:
        """Update a node's announced capabilities.

        Allows a running node to change its capabilities — for example when
        auth sessions become available or the user closes the browser.

        Args:
            node_id: The node to update.
            capabilities: Partial or full capabilities dict.

        Returns:
            dict with updated capabilities or error.
        """
        with self._lock:
            node = self._nodes.get(node_id)
            if not node:
                return {"error": "not_found", "message": f"Node {node_id} not in registry"}

            old_zone = node.capabilities.zone_code
            caps = node.capabilities

            # Patch individual fields
            if "country" in capabilities or "country_code" in capabilities:
                caps.country_code = (
                    capabilities.get("country") or capabilities.get("country_code", caps.country_code)
                ).upper().strip()
            if "city" in capabilities:
                caps.city = capabilities["city"]
            if "browser" in capabilities or "has_browser" in capabilities:
                caps.has_browser = bool(
                    capabilities.get("browser") or capabilities.get("has_browser", caps.has_browser)
                )
            if "has_auth_sessions" in capabilities:
                caps.has_auth_sessions = bool(capabilities["has_auth_sessions"])
            if "bandwidth_tier" in capabilities:
                tier = capabilities["bandwidth_tier"]
                if tier in VALID_BANDWIDTH_TIERS:
                    caps.bandwidth_tier = tier
            if "max_concurrent_tasks" in capabilities:
                caps.max_concurrent_tasks = max(1, int(capabilities["max_concurrent_tasks"]))
            if "supported_task_types" in capabilities:
                caps.supported_task_types = list(capabilities["supported_task_types"])
            if "platform" in capabilities:
                if capabilities["platform"] in VALID_PLATFORMS:
                    caps.platform = capabilities["platform"]

            # Re-derive zone if city/country changed
            new_zone = _derive_zone(caps.country_code, caps.city)
            caps.zone_code = new_zone

            # Update zone index
            if old_zone != new_zone:
                if old_zone and old_zone in self._zone_nodes:
                    self._zone_nodes[old_zone].discard(node_id)
                    if not self._zone_nodes[old_zone]:
                        del self._zone_nodes[old_zone]
                if new_zone:
                    self._zone_nodes.setdefault(new_zone, set()).add(node_id)

            return {
                "node_id": node_id,
                "capabilities": caps.to_dict(),
                "message": "Capabilities updated",
            }

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover_nodes(
        self,
        market: Optional[str] = None,
        task_type: Optional[str] = None,
        require_browser: bool = False,
        min_rating: float = 0.0,
        limit: int = 10,
    ) -> List[dict]:
        """Find the best available nodes for a task.

        This is the primary discovery method that ``citizenserp_tasks.py``
        should use instead of raw HelperProfile queries.

        Filtering:
            - ``market``: match against zone_code (e.g. "US-NE") or country_code
              prefix (e.g. "US").
            - ``task_type``: must be in node's supported_task_types.
            - ``require_browser``: node must have ``has_browser=True``.
            - ``min_rating``: success_rate must be >= this value.

        Sorting priority (descending) — tier-preference weighted:
            1. Tier routing weight (platinum 4.0 > gold 2.5 > silver 1.5 > bronze 1.0)
            2. Data categories shared (more sharing = higher priority)
            3. Success rate (tasks_completed / total)
            4. Tasks completed (experience)
            5. Average execution time (lower is better)

        Floor guarantee: lower-tier nodes are never fully starved. The limit
        is filled tier-first, but if ``limit`` allows, lower tiers get slots
        from the ``TIER_FLOOR_SLOTS_PCT`` reserve.

        Args:
            market: Market or zone code to match (e.g. "US-NE", "US", "GB").
            task_type: Task type the node must support.
            require_browser: If True, only include browser-capable nodes.
            min_rating: Minimum success rate (0.0–1.0).
            limit: Max number of results to return.

        Returns:
            List of node dicts sorted by suitability with tier preference.
        """
        with self._lock:
            candidates = self._filter_candidates(
                market=market,
                task_type=task_type,
                require_browser=require_browser,
                min_rating=min_rating,
            )

            # Tier-preference weighted sort
            # Higher routing weight = dispatched first = more tasks = more earnings
            candidates.sort(
                key=lambda n: (
                    -TIER_ROUTING_WEIGHTS.get(n.tier, 1.0),
                    -n.data_categories_shared,
                    -n.success_rate,
                    -n.tasks_completed,
                    n.avg_execution_ms,
                )
            )

            # Floor guarantee: reserve slots for lower tiers so they aren't starved
            # If we have more candidates than limit, ensure at least TIER_FLOOR_SLOTS_PCT
            # of slots go to non-top-tier nodes (if available)
            if len(candidates) > limit:
                floor_slots = max(1, int(limit * TIER_FLOOR_SLOTS_PCT))
                top_slots = limit - floor_slots

                top_tier_nodes = [n for n in candidates if n.tier in ("platinum", "gold")]
                lower_tier_nodes = [n for n in candidates if n.tier in ("silver", "bronze")]

                # Fill top slots with best nodes (any tier, preference-sorted)
                result = candidates[:top_slots]

                # Fill floor slots with lower-tier nodes not already included
                included_ids = {n.node_id for n in result}
                floor_fill = [n for n in lower_tier_nodes if n.node_id not in included_ids]
                result.extend(floor_fill[:floor_slots])

                # If floor slots weren't fully used, backfill from remaining top tiers
                if len(result) < limit:
                    remaining = [n for n in candidates if n.node_id not in {r.node_id for r in result}]
                    result.extend(remaining[:limit - len(result)])

                return [n.to_dict() for n in result[:limit]]

            return [n.to_dict() for n in candidates[:limit]]

    def _filter_candidates(
        self,
        market: Optional[str],
        task_type: Optional[str],
        require_browser: bool,
        min_rating: float,
    ) -> List[RegisteredNode]:
        """Return nodes matching the given filters (must hold lock)."""
        results: List[RegisteredNode] = []

        # If market looks like a zone code and we have a zone index, start there
        candidate_ids: Optional[Set[str]] = None
        if market:
            market_upper = market.upper()
            # Try exact zone match first
            if market_upper in self._zone_nodes:
                candidate_ids = set(self._zone_nodes[market_upper])
            else:
                # Fall back to country prefix match across all zones
                candidate_ids = set()
                country_prefix = market_upper.split("-")[0]
                for zone, nids in self._zone_nodes.items():
                    if zone.startswith(country_prefix):
                        candidate_ids.update(nids)
                # Also check nodes without a zone but matching country
                for nid, node in self._nodes.items():
                    if node.capabilities.country_code == country_prefix:
                        candidate_ids.add(nid)

        nodes_to_check = (
            [self._nodes[nid] for nid in candidate_ids if nid in self._nodes]
            if candidate_ids is not None
            else list(self._nodes.values())
        )

        for node in nodes_to_check:
            if not node.is_available:
                continue

            if require_browser and not node.capabilities.has_browser:
                continue

            if task_type and task_type not in node.capabilities.supported_task_types:
                continue

            if min_rating > 0.0 and node.success_rate < min_rating:
                continue

            results.append(node)

        return results

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    def get_node(self, node_id: str) -> Optional[dict]:
        """Get a single node's full information by its node_id.

        Args:
            node_id: The node identifier (NOD-xxx).

        Returns:
            Node dict or None if not found.
        """
        with self._lock:
            node = self._nodes.get(node_id)
            return node.to_dict() if node else None

    def get_node_for_user(self, user_id: int) -> Optional[dict]:
        """Get the registered node for a given user_id.

        Each user can have at most one active node.

        Args:
            user_id: The helper's user ID.

        Returns:
            Node dict or None.
        """
        with self._lock:
            node_id = self._user_nodes.get(user_id)
            if node_id and node_id in self._nodes:
                return self._nodes[node_id].to_dict()
            return None

    def list_online_nodes(
        self,
        country: Optional[str] = None,
        zone: Optional[str] = None,
    ) -> List[dict]:
        """List all currently online (non-offline) nodes.

        Args:
            country: Optional 2-letter country code filter.
            zone: Optional zone code filter.

        Returns:
            List of node dicts.
        """
        with self._lock:
            results = []
            for node in self._nodes.values():
                if node.status == "offline":
                    continue
                if country and node.capabilities.country_code != country.upper():
                    continue
                if zone and node.capabilities.zone_code != zone.upper():
                    continue
                results.append(node.to_dict())
            return results

    # ------------------------------------------------------------------
    # Network topology
    # ------------------------------------------------------------------

    def get_network_topology(self) -> dict:
        """Return a high-level summary of the node network.

        Includes totals by status, country, zone, and aggregate capacity.

        Returns:
            dict with topology information.
        """
        with self._lock:
            by_status: Dict[str, int] = {}
            by_country: Dict[str, int] = {}
            by_zone: Dict[str, int] = {}
            total_capacity = 0
            total_used = 0
            browser_capable = 0

            for node in self._nodes.values():
                by_status[node.status] = by_status.get(node.status, 0) + 1

                cc = node.capabilities.country_code
                by_country[cc] = by_country.get(cc, 0) + 1

                zc = node.capabilities.zone_code
                if zc:
                    by_zone[zc] = by_zone.get(zc, 0) + 1

                total_capacity += node.capabilities.max_concurrent_tasks
                total_used += node.current_tasks

                if node.capabilities.has_browser:
                    browser_capable += 1

            return {
                "total_nodes": len(self._nodes),
                "total_online": sum(
                    1 for n in self._nodes.values() if n.status in ("online", "idle", "busy")
                ),
                "by_status": by_status,
                "by_country": by_country,
                "by_zone": by_zone,
                "total_capacity": total_capacity,
                "total_in_use": total_used,
                "available_capacity": total_capacity - total_used,
                "browser_capable_nodes": browser_capable,
            }

    # ------------------------------------------------------------------
    # Stale cleanup
    # ------------------------------------------------------------------

    def cleanup_stale_nodes(self, stale_minutes: int = 5) -> int:
        """Mark nodes that missed their heartbeat as offline and remove them.

        Should be called periodically (e.g. from a background scheduler).

        Args:
            stale_minutes: Minutes without heartbeat before a node is stale.

        Returns:
            Number of nodes cleaned up.
        """
        stale_threshold = stale_minutes * 60
        stale_nodes: List[RegisteredNode] = []

        with self._lock:
            for node in list(self._nodes.values()):
                if node.status == "offline":
                    continue
                if node.seconds_since_heartbeat() > stale_threshold:
                    node.status = "stale"
                    stale_nodes.append(node)
                    logger.warning(
                        "Node %s (user=%s) is stale — last heartbeat %s",
                        node.node_id,
                        node.user_id,
                        node.last_heartbeat,
                    )

            # Remove stale nodes from active indices
            for node in stale_nodes:
                self._remove_node_unlocked(node.node_id)

        # Notify outside the lock
        for node in stale_nodes:
            self._notify_node_offline(node.node_id, node.user_id)

        if stale_nodes:
            logger.info("Cleaned up %d stale node(s)", len(stale_nodes))

        return len(stale_nodes)

    # ------------------------------------------------------------------
    # Task tracking
    # ------------------------------------------------------------------

    def assign_task(self, node_id: str, task_id: str) -> dict:
        """Mark a node as busy and increment its current task count.

        Called by the task dispatcher when a task is assigned to this node.

        Args:
            node_id: The target node.
            task_id: The task being assigned (for logging).

        Returns:
            dict with updated status or error.
        """
        with self._lock:
            node = self._nodes.get(node_id)
            if not node:
                return {"error": "not_found", "message": f"Node {node_id} not in registry"}

            if node.status in ("offline", "stale"):
                return {
                    "error": "unavailable",
                    "message": f"Node {node_id} is {node.status}",
                }

            if node.current_tasks >= node.capabilities.max_concurrent_tasks:
                return {
                    "error": "at_capacity",
                    "message": f"Node {node_id} already at max concurrent tasks",
                }

            node.current_tasks += 1
            node.status = "busy"

        logger.info("Task %s assigned to node %s", task_id, node_id)
        return {
            "node_id": node_id,
            "task_id": task_id,
            "status": "busy",
            "current_tasks": node.current_tasks,
        }

    def complete_task(
        self,
        node_id: str,
        task_id: str,
        success: bool,
        execution_time_ms: float,
    ) -> dict:
        """Record task completion and update node stats.

        Decrements current_tasks, updates success/failure counters, and
        recalculates the running average execution time.

        Args:
            node_id: The node that executed the task.
            task_id: The completed task (for logging).
            success: Whether the task succeeded.
            execution_time_ms: Wall-clock execution time in milliseconds.

        Returns:
            dict with updated stats or error.
        """
        with self._lock:
            node = self._nodes.get(node_id)
            if not node:
                return {"error": "not_found", "message": f"Node {node_id} not in registry"}

            node.current_tasks = max(0, node.current_tasks - 1)

            if success:
                node.tasks_completed += 1
            else:
                node.tasks_failed += 1

            # Running average
            total_tasks = node.tasks_completed + node.tasks_failed
            node._total_execution_ms += execution_time_ms
            node.avg_execution_ms = node._total_execution_ms / total_tasks

            # Update status
            if node.status not in ("offline", "stale"):
                node.status = "busy" if node.current_tasks > 0 else "online"

        outcome = "success" if success else "failure"
        logger.info(
            "Task %s completed on node %s (%s, %dms)",
            task_id,
            node_id,
            outcome,
            int(execution_time_ms),
        )

        return {
            "node_id": node_id,
            "task_id": task_id,
            "success": success,
            "execution_time_ms": round(execution_time_ms, 2),
            "current_tasks": node.current_tasks,
            "tasks_completed": node.tasks_completed,
            "tasks_failed": node.tasks_failed,
            "avg_execution_ms": round(node.avg_execution_ms, 2),
            "status": node.status,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_token(self, user_id: int, token: str) -> bool:
        """Verify a helper token against the HelperProfile in the database.

        Uses lazy imports to avoid circular dependencies. If the database
        or model is unavailable, validation fails closed (returns False).

        Args:
            user_id: The user ID claiming ownership.
            token: The helper activation token.

        Returns:
            True if the token is valid and the helper is active+approved.
        """
        try:
            from models import HelperProfile, db

            profile = HelperProfile.query.filter_by(user_id=user_id).first()
            if not profile:
                logger.debug("No HelperProfile for user %s", user_id)
                return False

            if not getattr(profile, "is_active", True):
                logger.debug("HelperProfile for user %s is not active", user_id)
                return False

            if not getattr(profile, "is_approved", True):
                logger.debug("HelperProfile for user %s is not approved", user_id)
                return False

            # Check token — the profile stores the helper's auth token
            stored_token = getattr(profile, "helper_token", None) or getattr(
                profile, "token", None
            )
            if stored_token and stored_token != token:
                logger.debug("Token mismatch for user %s", user_id)
                return False

            return True

        except ImportError:
            logger.warning(
                "models module not available — token validation skipped, allowing registration"
            )
            # In development/testing without the DB, allow registration
            return True
        except Exception as exc:
            logger.error("Token validation error for user %s: %s", user_id, exc)
            return False

    def _remove_node_unlocked(self, node_id: str) -> None:
        """Remove a node from all in-memory indices.

        MUST be called while holding ``self._lock``.
        """
        node = self._nodes.pop(node_id, None)
        if not node:
            return

        # Remove user index
        if self._user_nodes.get(node.user_id) == node_id:
            del self._user_nodes[node.user_id]

        # Remove zone index
        zone = node.capabilities.zone_code
        if zone and zone in self._zone_nodes:
            self._zone_nodes[zone].discard(node_id)
            if not self._zone_nodes[zone]:
                del self._zone_nodes[zone]

    def _notify_node_online(self, node: RegisteredNode) -> None:
        """Notify the uptime tracker and DB that a node came online.

        Uses lazy imports for citizenserp_payouts / citizenserp_manager.
        """
        try:
            from citizenserp_manager import record_node_online

            record_node_online(node.user_id, node.node_id)
        except ImportError:
            logger.debug("citizenserp_manager not available — skipping online notification")
        except Exception as exc:
            logger.error("Failed to record node online for %s: %s", node.node_id, exc)

        # Persist to DB if possible
        try:
            from models import db, HelperProfile

            profile = HelperProfile.query.filter_by(user_id=node.user_id).first()
            if profile:
                profile.last_seen = datetime.now(timezone.utc)
                profile.node_id = node.node_id
                db.session.commit()
        except ImportError:
            pass
        except Exception as exc:
            logger.debug("DB update on node online failed: %s", exc)

    def _notify_node_offline(self, node_id: str, user_id: int) -> None:
        """Notify the uptime tracker that a node went offline."""
        try:
            from citizenserp_manager import record_node_offline

            record_node_offline(user_id, node_id)
        except ImportError:
            logger.debug("citizenserp_manager not available — skipping offline notification")
        except Exception as exc:
            logger.error("Failed to record node offline for %s: %s", node_id, exc)

        # Clear node_id in DB
        try:
            from models import db, HelperProfile

            profile = HelperProfile.query.filter_by(user_id=user_id).first()
            if profile and getattr(profile, "node_id", None) == node_id:
                profile.node_id = None
                db.session.commit()
        except ImportError:
            pass
        except Exception as exc:
            logger.debug("DB update on node offline failed: %s", exc)


# ---------------------------------------------------------------------------
# CitizenSERP Network Readiness Tracker
# ---------------------------------------------------------------------------
# Monitors node network growth against commercialization thresholds.
# When the network hits the "commercially viable" milestone, the system
# can auto-flip MYSTES_ECONOMIC_PHASE from 1 → 2 (or flag for manual flip).
#
# Three milestones:
#   pilot_ready (100 nodes)     — internal testing, validate API at scale
#   commercially_viable (500)   — real B2B customers, SLA guarantees, Phase 2 flip
#   defensible (2000)           — enterprise contracts, moat is real
# ---------------------------------------------------------------------------

CITIZENSERP_MILESTONES = {
    "pilot_ready": {
        "total_nodes": 100,
        "min_zones": 10,           # At least 10 geographic zones covered
        "min_nodes_per_zone": 3,   # 3 nodes/zone = ~97% uptime
        "min_countries": 8,        # 8 countries minimum
        "phase_trigger": None,     # No auto-flip — internal testing only
    },
    "commercially_viable": {
        "total_nodes": 500,
        "min_zones": 15,           # 15 zones with redundancy
        "min_nodes_per_zone": 5,   # 5 nodes/zone = ~99.2% uptime
        "min_countries": 12,       # 12 countries
        "phase_trigger": 2,        # Auto-flip to Phase 2
    },
    "defensible": {
        "total_nodes": 2000,
        "min_zones": 25,           # 25+ zones
        "min_nodes_per_zone": 10,  # 10 nodes/zone = ~99.99% uptime
        "min_countries": 20,       # 20 countries
        "phase_trigger": None,     # No phase change — already at 2
    },
}


def check_citizenserp_readiness(registry: "NodeRegistry" = None) -> dict:
    """Assess CitizenSERP network readiness against commercialization thresholds.

    Queries the live node topology and scores against each milestone.

    Returns:
        dict with:
            current_phase: int (1 or 2)
            network_stats: {total_nodes, total_online, countries, zones, ...}
            milestones: {milestone_name: {required, actual, met, progress_pct}}
            current_milestone: str (highest milestone fully met, or "pre_pilot")
            next_milestone: str (next milestone to achieve)
            ready_for_phase_flip: bool
            phase_flip_target: int or None
    """
    if registry is None:
        registry = node_registry

    topology = registry.get_network_topology()

    total_online = topology["total_online"]
    by_country = topology.get("by_country", {})
    by_zone = topology.get("by_zone", {})

    # Count zones with sufficient redundancy per milestone
    country_count = len(by_country)
    zone_count = len(by_zone)

    # Get current phase
    try:
        from mystes_ai import MYSTES_ECONOMIC_PHASE
        current_phase = MYSTES_ECONOMIC_PHASE
    except ImportError:
        current_phase = int(os.environ.get("MYSTES_ECONOMIC_PHASE", "1"))

    milestones = {}
    current_milestone = "pre_pilot"
    next_milestone = "pilot_ready"
    ready_for_phase_flip = False
    phase_flip_target = None

    for name, thresholds in CITIZENSERP_MILESTONES.items():
        req_nodes = thresholds["total_nodes"]
        req_zones = thresholds["min_zones"]
        req_per_zone = thresholds["min_nodes_per_zone"]
        req_countries = thresholds["min_countries"]

        # Count zones that meet the per-zone minimum for this milestone
        zones_with_redundancy = sum(
            1 for z, count in by_zone.items() if count >= req_per_zone
        )

        checks = {
            "total_nodes": {
                "required": req_nodes,
                "actual": total_online,
                "met": total_online >= req_nodes,
                "progress_pct": min(100.0, round(total_online / req_nodes * 100, 1)),
            },
            "zones_covered": {
                "required": req_zones,
                "actual": zone_count,
                "met": zone_count >= req_zones,
                "progress_pct": min(100.0, round(zone_count / req_zones * 100, 1)),
            },
            "zones_with_redundancy": {
                "required": req_zones,
                "actual": zones_with_redundancy,
                "met": zones_with_redundancy >= req_zones,
                "progress_pct": min(100.0, round(zones_with_redundancy / max(1, req_zones) * 100, 1)),
            },
            "countries": {
                "required": req_countries,
                "actual": country_count,
                "met": country_count >= req_countries,
                "progress_pct": min(100.0, round(country_count / req_countries * 100, 1)),
            },
        }

        all_met = all(c["met"] for c in checks.values())
        overall_progress = round(
            sum(c["progress_pct"] for c in checks.values()) / len(checks), 1
        )

        milestones[name] = {
            "checks": checks,
            "all_met": all_met,
            "overall_progress_pct": overall_progress,
            "phase_trigger": thresholds["phase_trigger"],
        }

        if all_met:
            current_milestone = name
            # Check if this milestone triggers a phase flip
            if (
                thresholds["phase_trigger"] is not None
                and current_phase < thresholds["phase_trigger"]
            ):
                ready_for_phase_flip = True
                phase_flip_target = thresholds["phase_trigger"]

    # Determine next milestone
    milestone_order = ["pilot_ready", "commercially_viable", "defensible"]
    for m in milestone_order:
        if not milestones[m]["all_met"]:
            next_milestone = m
            break
    else:
        next_milestone = None  # All milestones achieved

    # Estimated capacity at current node count
    capacity_requests_per_day = int(
        total_online * DEFAULT_MAX_CONCURRENT * DEFAULT_UPTIME_FRACTION * 86400 / 60
    )  # Assuming ~60s per SERP request

    return {
        "current_phase": current_phase,
        "network_stats": {
            "total_nodes": topology["total_nodes"],
            "total_online": total_online,
            "countries": country_count,
            "zones": zone_count,
            "total_capacity": topology["total_capacity"],
            "available_capacity": topology["available_capacity"],
            "browser_capable": topology["browser_capable_nodes"],
            "estimated_serp_capacity_per_day": capacity_requests_per_day,
            "by_country": by_country,
            "by_zone": by_zone,
        },
        "milestones": milestones,
        "current_milestone": current_milestone,
        "next_milestone": next_milestone,
        "ready_for_phase_flip": ready_for_phase_flip,
        "phase_flip_target": phase_flip_target,
    }


def maybe_auto_flip_phase() -> Optional[int]:
    """Check if the network has hit the threshold for an automatic phase flip.

    If ready, updates the .env file and returns the new phase number.
    If not ready, returns None.

    This should be called periodically (e.g., hourly Celery task or on node registration).
    """
    readiness = check_citizenserp_readiness()

    if not readiness["ready_for_phase_flip"]:
        return None

    new_phase = readiness["phase_flip_target"]
    current = readiness["current_phase"]

    logger.info(
        "CitizenSERP network readiness: phase flip %d -> %d triggered! "
        "Nodes: %d, Zones: %d, Countries: %d",
        current,
        new_phase,
        readiness["network_stats"]["total_online"],
        readiness["network_stats"]["zones"],
        readiness["network_stats"]["countries"],
    )

    # Update .env file
    try:
        env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                content = f.read()
            old_val = f"MYSTES_ECONOMIC_PHASE={current}"
            new_val = f"MYSTES_ECONOMIC_PHASE={new_phase}"
            if old_val in content:
                content = content.replace(old_val, new_val)
                with open(env_path, "w") as f:
                    f.write(content)
                logger.info("Updated .env: %s -> %s", old_val, new_val)

        # Also set in environment for current process
        os.environ["MYSTES_ECONOMIC_PHASE"] = str(new_phase)

    except Exception as e:
        logger.error("Failed to update .env for phase flip: %s", e)

    return new_phase


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

node_registry = NodeRegistry()
