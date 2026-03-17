"""
Credential Network — Federated credential sharing and booking routing.

This is the "Mother of All Consolidators" — a decentralized network where
B2B customers share API credentials for revenue sharing. ANASTASiA routes
bookings to the optimal credential holder based on price, availability,
and coverage.

The daemon bridge handles execution: when a booking routes through
Agency X's credentials, Agency X's daemon executes the sale under
their IATA number, their accreditation. MYSTES takes a routing fee.

MYSTES KYRIOS LLC — Confidential.
"""

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..core.events import Event, EventBus, EventType

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Routing Strategy & Tier (THE PYRAMID — Build #156)
# ---------------------------------------------------------------------------

class RoutingStrategy(Enum):
    """How to prioritize credential candidates during routing."""
    BEST_PRICE = "best_price"           # Maximize arbitrage margin
    BEST_RELIABILITY = "best_reliability"  # Maximize booking success rate
    BALANCED = "balanced"               # Weighted balance of all factors


class RoutingTier(Enum):
    """
    Credential source tiers — routing tries each tier in order.

    Tier 1: Our own credentials (Picasso, liteAPI) — zero routing fee.
    Tier 2: Premium network members (90%+ reliability) — routing fee applies.
    Tier 3: Broader network (any active member) — routing fee applies.
    Tier 4: Alternate API fallback (Mystifly, Kiwi, etc.) — different model.
    Tier 5: AI escalation — human review for marginal cases.
    """
    OWN_CREDENTIALS = 1
    PREMIUM_NETWORK = 2
    BROAD_NETWORK = 3
    ALTERNATE_API = 4
    AI_ESCALATION = 5


# Minimum reliability score to qualify as "premium" (Tier 2).
PREMIUM_RELIABILITY_THRESHOLD = 0.90

# Routing fee by subscription tier — taken off the top.
# Aligns with billing.py ROUTING_FEE_PCT.
ROUTING_FEE_BY_TIER = {
    "starter": 0.0,       # Starter = our credentials only (no network routing)
    "pro": 0.05,          # 5% routing fee
    "enterprise": 0.03,   # 3% routing fee (volume discount)
}

# After routing fee, remaining margin split between parties.
# Aligns with billing.py CLIENT_PROVISIONARY_SPLIT_PCT / PORTAL_HOST_SPLIT_PCT.
CLIENT_PROVISIONARY_PCT = 0.70  # Agency that brought the customer
PORTAL_HOST_PCT = 0.30          # Credential provider that executes the booking


def get_tier_revenue_split(tier: str = "pro") -> Dict[str, float]:
    """
    Build the correct revenue split based on subscription tier.

    Per the Pyramid model (Build #156):
    - Our routing fee (platform) comes off the top: 5% Pro, 3% Enterprise.
    - Remaining splits 70/30: Client Provisionary / Portal Host.

    Keys map to existing RoutingResult.revenue_split field names:
    - platform = MYSTES routing fee
    - router   = Client Provisionary (agency bringing the sale)
    - owner    = Portal Host (credential provider executing the booking)

    Example (Pro, $200 savings):
        platform=5% → $10, router=70%×$190 → $133, owner=30%×$190 → $57
    """
    fee = ROUTING_FEE_BY_TIER.get(tier, 0.05)
    remaining = 1.0 - fee
    return {
        "platform": fee,
        "router": round(remaining * CLIENT_PROVISIONARY_PCT, 4),
        "owner": round(remaining * PORTAL_HOST_PCT, 4),
    }


# Legacy default (backward-compat for tests/code that doesn't pass tier).
DEFAULT_REVENUE_SPLIT = get_tier_revenue_split("pro")


# Recency window: only consider bookings from the last 90 days for scoring.
RECENCY_WINDOW_SECONDS = 90 * 86400  # 90 days

# Recency half-life: bookings older than this contribute half weight.
RECENCY_HALF_LIFE_SECONDS = 30 * 86400  # 30 days

# Scoring weights for candidate selection during routing.
SCORING_WEIGHTS = {
    "reliability": 0.40,
    "price": 0.30,
    "revenue_terms": 0.20,
    "volume": 0.10,
}


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class NetworkMember:
    """
    A tenant participating in the federated credential network.

    Members share API credentials they hold (GDS logins, consolidator
    access, supplier portals) and earn revenue when other members route
    bookings through those credentials.
    """
    tenant_id: str = ""
    tenant_name: str = ""
    joined_at: float = field(default_factory=time.time)
    status: str = "active"  # active, suspended, left
    credentials_shared: int = 0
    bookings_routed: int = 0       # Inbound — sales executed for network
    bookings_received: int = 0     # Outbound — bookings they sent to network
    revenue_earned_usd: float = 0.0   # From hosting credentials
    revenue_paid_usd: float = 0.0     # Platform fees paid
    coverage: Dict[str, List[str]] = field(default_factory=dict)
    # provider_id -> list of POS market codes covered
    capabilities: List[str] = field(default_factory=list)
    # Verticals: "flights", "hotels", "cars", etc.

    def to_dict(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "tenant_name": self.tenant_name,
            "joined_at": self.joined_at,
            "status": self.status,
            "credentials_shared": self.credentials_shared,
            "bookings_routed": self.bookings_routed,
            "bookings_received": self.bookings_received,
            "revenue_earned_usd": self.revenue_earned_usd,
            "revenue_paid_usd": self.revenue_paid_usd,
            "coverage": {k: list(v) for k, v in self.coverage.items()},
            "capabilities": list(self.capabilities),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "NetworkMember":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class RoutingRequest:
    """
    A request to route a booking through the credential network.

    When a tenant needs to book through a provider/POS they don't hold
    credentials for, they submit a RoutingRequest. The network finds the
    optimal credential holder and routes the booking to their daemon.
    """
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    requester_tenant_id: str = ""
    provider_id: str = ""          # Which system is needed (e.g., "redbox", "sabre")
    pos_market: Optional[str] = None   # Geographic POS code (e.g., "DK", "ES")
    vertical: str = "flights"      # "flights", "hotels", "cars"
    search_params: Dict[str, Any] = field(default_factory=dict)
    # origin, destination, dates, pax, cabin, etc.
    priority: str = "price"        # "price", "speed", "reliability"
    strategy: str = "balanced"     # RoutingStrategy value
    requester_tier: str = "pro"    # Subscription tier (determines routing fee)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "requester_tenant_id": self.requester_tenant_id,
            "provider_id": self.provider_id,
            "pos_market": self.pos_market,
            "vertical": self.vertical,
            "search_params": dict(self.search_params),
            "priority": self.priority,
            "strategy": self.strategy,
            "requester_tier": self.requester_tier,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RoutingRequest":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class RoutingResult:
    """
    The outcome of a routing decision — which credential was selected
    and the execution status of the booking.
    """
    result_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    request_id: str = ""
    requester_tenant_id: str = ""  # Who triggered the routing (client provisionary)
    credential_id: str = ""        # Which credential was selected
    owner_tenant_id: str = ""      # Credential host tenant (portal host)
    provider_id: str = ""
    pos_market: Optional[str] = None
    estimated_price: Optional[float] = None
    confidence: float = 0.0        # 0.0-1.0 routing confidence
    routing_tier: int = 0          # RoutingTier value (1-5) that fulfilled this
    revenue_split: Dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_REVENUE_SPLIT)
    )
    status: str = "pending"        # pending, executing, completed, failed
    executed_at: Optional[float] = None
    execution_result: Optional[Dict[str, Any]] = None
    # Fallback candidates — ordered list of backup credentials if primary fails
    fallback_candidates: List[str] = field(default_factory=list)
    # Index into fallback_candidates of the current attempt (0 = primary)
    attempt_index: int = 0

    def to_dict(self) -> dict:
        return {
            "result_id": self.result_id,
            "request_id": self.request_id,
            "requester_tenant_id": self.requester_tenant_id,
            "credential_id": self.credential_id,
            "owner_tenant_id": self.owner_tenant_id,
            "provider_id": self.provider_id,
            "pos_market": self.pos_market,
            "estimated_price": self.estimated_price,
            "confidence": self.confidence,
            "routing_tier": self.routing_tier,
            "revenue_split": dict(self.revenue_split),
            "status": self.status,
            "executed_at": self.executed_at,
            "execution_result": self.execution_result,
            "fallback_candidates": list(self.fallback_candidates),
            "attempt_index": self.attempt_index,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RoutingResult":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


# ---------------------------------------------------------------------------
# Credential Network
# ---------------------------------------------------------------------------

class CredentialNetwork:
    """
    Federated credential sharing and booking routing engine.

    Connects B2B customers who share API credentials for mutual benefit.
    The network maintains a registry of members, their credential coverage,
    and routes bookings to the optimal credential holder based on price,
    reliability, and revenue terms.

    Security invariant: raw credentials NEVER leave the vault. The network
    only sees metadata (provider, POS markets, capabilities) and routes
    execution requests to the owning daemon via the bridge.

    Args:
        event_bus: Shared event bus for inter-neuron communication.
        vault: CredentialVault instance for credential lookups. Typed as
               Any to avoid circular imports — the vault module is loaded
               alongside this one and may not be importable at class
               definition time.
        storage_dir: Directory for persisting network state. Defaults to
                     ~/.anastasia/network.
    """

    def __init__(
        self,
        event_bus: EventBus,
        vault: Any,
        storage_dir: Optional[str] = None,
    ) -> None:
        self._event_bus = event_bus
        self._vault = vault
        self._storage_dir = storage_dir or os.path.join(
            str(Path.home()), ".anastasia", "network"
        )

        self._members: Dict[str, NetworkMember] = {}     # tenant_id -> member
        self._results: Dict[str, RoutingResult] = {}      # result_id -> result
        self._routing_history: List[str] = []             # result_ids in order

        os.makedirs(self._storage_dir, exist_ok=True)
        os.makedirs(os.path.join(self._storage_dir, "members"), exist_ok=True)
        os.makedirs(os.path.join(self._storage_dir, "results"), exist_ok=True)
        self._load_all()

        logger.info(
            "CredentialNetwork initialized: %d members, %d routing results",
            len(self._members), len(self._results),
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def member_count(self) -> int:
        """Number of active network members."""
        return sum(1 for m in self._members.values() if m.status == "active")

    @property
    def active_routes(self) -> int:
        """Number of routing results currently in pending or executing state."""
        return sum(
            1 for r in self._results.values()
            if r.status in ("pending", "executing")
        )

    # ------------------------------------------------------------------
    # Network Membership
    # ------------------------------------------------------------------

    def join_network(
        self,
        tenant_id: str,
        tenant_name: str,
        credentials: Optional[List[Dict[str, Any]]] = None,
    ) -> NetworkMember:
        """
        Add a tenant to the credential network.

        If the tenant already exists and left previously, they are
        reactivated. Optionally registers initial credentials in the
        vault and updates coverage accordingly.

        Args:
            tenant_id: Unique tenant identifier.
            tenant_name: Human-readable tenant name.
            credentials: Optional list of credential dicts to register
                         on join. Each dict is passed to the vault's
                         store method.

        Returns:
            The newly created or reactivated NetworkMember.
        """
        # Reactivate if previously left
        if tenant_id in self._members:
            existing = self._members[tenant_id]
            if existing.status == "left":
                existing.status = "active"
                existing.tenant_name = tenant_name
                logger.info("Reactivated network member: %s", tenant_name)
            else:
                logger.info("Member %s already in network (status=%s)",
                            tenant_name, existing.status)
                return existing
            member = existing
        else:
            member = NetworkMember(
                tenant_id=tenant_id,
                tenant_name=tenant_name,
                joined_at=time.time(),
                status="active",
            )

        self._members[tenant_id] = member

        # Register initial credentials if provided
        if credentials:
            for cred in credentials:
                try:
                    self._vault.store(tenant_id=tenant_id, **cred)
                    member.credentials_shared += 1
                except Exception as e:
                    logger.warning(
                        "Failed to store credential for %s: %s", tenant_id, e
                    )

        # Recalculate coverage from vault
        self._update_coverage_from_vault(member)
        self._persist_member(member)

        # Publish event
        self._event_bus.publish(Event(
            type=EventType.CUSTOM,
            source="credential_network",
            data={
                "action": "network.member_joined",
                "tenant_id": tenant_id,
                "tenant_name": tenant_name,
                "credentials_shared": member.credentials_shared,
            },
        ))

        logger.info("Member joined network: %s (%s)", tenant_name, tenant_id)
        return member

    def leave_network(self, tenant_id: str) -> bool:
        """
        Remove a tenant from the credential network.

        Sets member status to "left" and clears their coverage. Does
        NOT delete credentials from the vault — that is the vault's
        responsibility.

        Args:
            tenant_id: The tenant to remove.

        Returns:
            True if the member was found and marked as left, False if
            the tenant was not a member.
        """
        member = self._members.get(tenant_id)
        if not member:
            logger.warning("Cannot leave: tenant %s not in network", tenant_id)
            return False

        member.status = "left"
        member.coverage = {}
        self._persist_member(member)

        self._event_bus.publish(Event(
            type=EventType.CUSTOM,
            source="credential_network",
            data={
                "action": "network.member_left",
                "tenant_id": tenant_id,
                "tenant_name": member.tenant_name,
            },
        ))

        logger.info("Member left network: %s", member.tenant_name)
        return True

    def get_member(self, tenant_id: str) -> Optional[NetworkMember]:
        """Get a network member by tenant ID, or None if not found."""
        return self._members.get(tenant_id)

    def list_members(self, status: str = "active") -> List[NetworkMember]:
        """
        List network members filtered by status.

        Args:
            status: Filter by member status. Use "all" for unfiltered.

        Returns:
            List of matching NetworkMember instances.
        """
        if status == "all":
            return list(self._members.values())
        return [m for m in self._members.values() if m.status == status]

    def update_coverage(self, tenant_id: str) -> Optional[NetworkMember]:
        """
        Recalculate a member's coverage map from their vault credentials.

        Queries the vault for all credentials owned by this tenant and
        rebuilds the provider -> POS markets mapping.

        Args:
            tenant_id: The tenant whose coverage to update.

        Returns:
            The updated NetworkMember, or None if tenant not found.
        """
        member = self._members.get(tenant_id)
        if not member:
            logger.warning("Cannot update coverage: tenant %s not found",
                           tenant_id)
            return None

        self._update_coverage_from_vault(member)
        self._persist_member(member)
        return member

    # ------------------------------------------------------------------
    # Network Discovery
    # ------------------------------------------------------------------

    def query_available_routes(
        self,
        provider_id: Optional[str] = None,
        pos_market: Optional[str] = None,
        vertical: str = "flights",
    ) -> List[Dict[str, Any]]:
        """
        Query the network for available credential routes.

        Returns metadata about which members can handle bookings for a
        given provider/POS combination. Never exposes raw credentials —
        only routing metadata.

        Args:
            provider_id: Filter by provider system (e.g., "redbox").
            pos_market: Filter by POS market code (e.g., "DK").
            vertical: Filter by travel vertical.

        Returns:
            List of route dicts with credential_id, owner info, coverage,
            and revenue split. Each route represents a potential booking
            path through the network.
        """
        routes: List[Dict[str, Any]] = []

        for member in self._members.values():
            if member.status != "active":
                continue

            # Filter by vertical capability
            if vertical and member.capabilities and vertical not in member.capabilities:
                continue

            for prov_id, markets in member.coverage.items():
                # Filter by provider
                if provider_id and prov_id != provider_id:
                    continue

                # Filter by POS market
                matched_markets = markets
                if pos_market:
                    matched_markets = [m for m in markets if m == pos_market]
                    if not matched_markets:
                        continue

                routes.append({
                    "credential_id": f"{member.tenant_id}:{prov_id}",
                    "owner_tenant_id": member.tenant_id,
                    "owner_tenant_name": member.tenant_name,
                    "provider_id": prov_id,
                    "pos_markets": matched_markets,
                    "revenue_split": dict(DEFAULT_REVENUE_SPLIT),
                    "reliability": self._calculate_reliability(member),
                    "bookings_completed": member.bookings_routed,
                })

        return routes

    def get_coverage_map(self) -> Dict[str, Dict[str, List[str]]]:
        """
        Build a network-wide coverage map.

        Returns:
            Nested dict: {provider_id: {pos_market: [tenant_ids]}}.
            Shows which members can handle which provider/POS combinations.
        """
        coverage: Dict[str, Dict[str, List[str]]] = {}

        for member in self._members.values():
            if member.status != "active":
                continue
            for provider_id, markets in member.coverage.items():
                if provider_id not in coverage:
                    coverage[provider_id] = {}
                for market in markets:
                    if market not in coverage[provider_id]:
                        coverage[provider_id][market] = []
                    if member.tenant_id not in coverage[provider_id][market]:
                        coverage[provider_id][market].append(member.tenant_id)

        return coverage

    def get_network_stats(self) -> Dict[str, Any]:
        """
        Aggregate statistics for the entire credential network.

        Returns:
            Dict with total members, credentials, bookings, and revenue.
        """
        active = [m for m in self._members.values() if m.status == "active"]
        all_members = list(self._members.values())

        total_bookings = sum(m.bookings_routed for m in all_members)
        total_revenue_earned = sum(m.revenue_earned_usd for m in all_members)
        total_revenue_paid = sum(m.revenue_paid_usd for m in all_members)
        total_credentials = sum(m.credentials_shared for m in all_members)

        # Count unique providers and markets across the network
        providers: set = set()
        markets: set = set()
        for member in active:
            for prov_id, prov_markets in member.coverage.items():
                providers.add(prov_id)
                markets.update(prov_markets)

        return {
            "total_members": len(all_members),
            "active_members": len(active),
            "total_credentials_shared": total_credentials,
            "total_bookings_routed": total_bookings,
            "total_revenue_earned_usd": round(total_revenue_earned, 2),
            "total_platform_fees_usd": round(total_revenue_paid, 2),
            "unique_providers": len(providers),
            "unique_pos_markets": len(markets),
            "active_routes": self.active_routes,
        }

    # ------------------------------------------------------------------
    # Booking Routing — Tiered Fallback Chain (THE PYRAMID)
    # ------------------------------------------------------------------

    def route_booking(self, request: RoutingRequest) -> Optional[RoutingResult]:
        """
        Route a booking to the optimal credential holder using the
        tiered fallback chain.

        Routing tiers (tried in order):
        1. OWN_CREDENTIALS: Platform-owned credentials (Picasso, liteAPI).
           Zero routing fee, highest confidence.
        2. PREMIUM_NETWORK: Pro/Enterprise members with 90%+ reliability.
           Routing fee applies (5% Pro, 3% Enterprise). High confidence.
        3. BROAD_NETWORK: Any active network member.
           Routing fee applies. Moderate confidence.
        4. ALTERNATE_API: Fallback APIs (Mystifly, Kiwi, etc.).
           Different commission model.
        5. AI_ESCALATION: Flagged for human/AI review.
           Returns result with status="escalated".

        The result includes a ranked fallback list — if the primary
        candidate fails, call ``retry_routing()`` to try the next.

        Args:
            request: The RoutingRequest describing what is needed.

        Returns:
            A RoutingResult if a suitable credential was found, or None
            if no member in the network (including fallbacks) can fulfill.
        """
        logger.info(
            "Routing booking: provider=%s pos=%s vertical=%s requester=%s "
            "strategy=%s tier=%s",
            request.provider_id, request.pos_market,
            request.vertical, request.requester_tenant_id,
            request.strategy, request.requester_tier,
        )

        # Build tiered candidate queue
        candidate_queue = self._build_candidate_queue(request)

        if not candidate_queue:
            logger.warning(
                "No candidates found for provider=%s pos=%s — "
                "consider AI escalation",
                request.provider_id, request.pos_market,
            )
            # Emit escalation event for AI/human review
            self._event_bus.publish(Event(
                type=EventType.FALLBACK_ACTIVATED,
                source="credential_network",
                data={
                    "action": "routing.escalation_needed",
                    "request_id": request.request_id,
                    "provider_id": request.provider_id,
                    "pos_market": request.pos_market,
                    "vertical": request.vertical,
                    "requester_tenant_id": request.requester_tenant_id,
                    "reason": "no_candidates_available",
                },
            ))
            return None

        # Primary candidate is the first in the queue
        primary = candidate_queue[0]
        fallback_ids = [
            c["credential_id"] for c in candidate_queue[1:6]  # Top 5 fallbacks
        ]

        # Determine revenue split based on requester's subscription tier
        revenue_split = get_tier_revenue_split(request.requester_tier)

        # If primary is OWN_CREDENTIALS (tier 1), zero routing fee
        if primary.get("routing_tier") == RoutingTier.OWN_CREDENTIALS.value:
            revenue_split = {
                "platform": 0.0,
                "router": 0.0,
                "owner": 1.0,  # We ARE the owner — all margin stays internal
            }

        result = RoutingResult(
            result_id=str(uuid.uuid4()),
            request_id=request.request_id,
            requester_tenant_id=request.requester_tenant_id,
            credential_id=primary["credential_id"],
            owner_tenant_id=primary["owner_tenant_id"],
            provider_id=primary["provider_id"],
            pos_market=request.pos_market,
            confidence=min(primary["score"], 1.0),
            routing_tier=primary.get("routing_tier", RoutingTier.BROAD_NETWORK.value),
            revenue_split=revenue_split,
            status="pending",
            fallback_candidates=fallback_ids,
            attempt_index=0,
        )

        self._results[result.result_id] = result
        self._routing_history.append(result.result_id)
        self._persist_result(result)

        # Update requester's outbound counter
        requester = self._members.get(request.requester_tenant_id)
        if requester:
            requester.bookings_received += 1
            self._persist_member(requester)

        # Publish routing event
        self._event_bus.publish(Event(
            type=EventType.CUSTOM,
            source="credential_network",
            data={
                "action": "network.booking_routed",
                "result_id": result.result_id,
                "request_id": request.request_id,
                "credential_id": result.credential_id,
                "owner_tenant_id": result.owner_tenant_id,
                "requester_tenant_id": request.requester_tenant_id,
                "provider_id": result.provider_id,
                "pos_market": result.pos_market,
                "confidence": result.confidence,
                "routing_tier": result.routing_tier,
                "fallback_count": len(fallback_ids),
            },
        ))

        logger.info(
            "Booking routed: result=%s -> owner=%s (confidence=%.2f, "
            "tier=%d, fallbacks=%d)",
            result.result_id, result.owner_tenant_id,
            result.confidence, result.routing_tier, len(fallback_ids),
        )
        return result

    def retry_routing(self, result_id: str) -> Optional[RoutingResult]:
        """
        Retry a failed routing by advancing to the next fallback candidate.

        When a booking execution fails, call this to try the next candidate
        in the fallback queue without creating a new routing request.

        Args:
            result_id: The RoutingResult that failed.

        Returns:
            Updated RoutingResult pointing to the next candidate, or None
            if all fallbacks are exhausted.
        """
        result = self._results.get(result_id)
        if not result:
            logger.warning("Cannot retry: result %s not found", result_id)
            return None

        if not result.fallback_candidates:
            logger.warning(
                "No fallback candidates for result %s — routing exhausted",
                result_id,
            )
            return None

        next_index = result.attempt_index + 1
        if next_index > len(result.fallback_candidates):
            logger.warning(
                "All %d fallback candidates exhausted for result %s",
                len(result.fallback_candidates), result_id,
            )
            # Emit escalation event
            self._event_bus.publish(Event(
                type=EventType.FALLBACK_ACTIVATED,
                source="credential_network",
                data={
                    "action": "routing.fallbacks_exhausted",
                    "result_id": result_id,
                    "request_id": result.request_id,
                    "attempts": next_index,
                },
            ))
            return None

        # Get next fallback credential
        next_cred_id = result.fallback_candidates[next_index - 1]

        # Look up candidate info from the credential ID
        # credential_id format: "tenant_id:provider_id"
        parts = next_cred_id.split(":", 1)
        if len(parts) != 2:
            logger.error("Malformed credential_id in fallback: %s", next_cred_id)
            return None

        next_owner_id, next_provider_id = parts

        # Update result to point to next candidate
        result.credential_id = next_cred_id
        result.owner_tenant_id = next_owner_id
        result.provider_id = next_provider_id
        result.attempt_index = next_index
        result.status = "pending"
        result.executed_at = None
        result.execution_result = None

        # Recalculate confidence from member reliability
        next_member = self._members.get(next_owner_id)
        if next_member:
            result.confidence = self._calculate_reliability(next_member) * 0.9
        else:
            result.confidence = 0.3

        self._persist_result(result)

        self._event_bus.publish(Event(
            type=EventType.CUSTOM,
            source="credential_network",
            data={
                "action": "network.booking_retried",
                "result_id": result_id,
                "attempt_index": next_index,
                "new_credential_id": next_cred_id,
                "new_owner_tenant_id": next_owner_id,
            },
        ))

        logger.info(
            "Routing retried: result=%s -> attempt #%d -> owner=%s",
            result_id, next_index, next_owner_id,
        )
        return result

    def _build_candidate_queue(
        self,
        request: RoutingRequest,
    ) -> List[Dict[str, Any]]:
        """
        Build a tiered, scored candidate queue for a routing request.

        Returns candidates ordered by tier (own credentials first, then
        premium network, then broad network), with scoring within each tier.

        Each candidate dict includes:
        - credential_id, owner_tenant_id, provider_id, pos_markets
        - score: 0.0-1.0 composite quality score
        - routing_tier: RoutingTier value (1-5)
        - reliability: member reliability score
        """
        # Discover all available routes
        candidates = self.query_available_routes(
            provider_id=request.provider_id,
            pos_market=request.pos_market,
            vertical=request.vertical,
        )

        # Exclude the requester (can't route to yourself)
        candidates = [
            c for c in candidates
            if c["owner_tenant_id"] != request.requester_tenant_id
        ]

        # Score and classify each candidate into tiers
        tiered: List[Tuple[int, float, Dict[str, Any]]] = []
        for candidate in candidates:
            member = self._members.get(candidate["owner_tenant_id"])
            if not member:
                continue

            score = self._score_candidate(candidate, request, member)
            reliability = candidate.get("reliability", 0.5)

            # Classify into routing tier
            if candidate["owner_tenant_id"] == "_platform":
                # Our own credentials — Tier 1
                tier = RoutingTier.OWN_CREDENTIALS.value
                score = max(score, 0.95)  # Floor at 0.95 for own creds
            elif reliability >= PREMIUM_RELIABILITY_THRESHOLD:
                # Premium network member — Tier 2
                tier = RoutingTier.PREMIUM_NETWORK.value
            else:
                # Broad network — Tier 3
                tier = RoutingTier.BROAD_NETWORK.value

            candidate["score"] = score
            candidate["routing_tier"] = tier
            tiered.append((tier, score, candidate))

        # Sort: lowest tier number first (Tier 1 > Tier 2 > Tier 3),
        # then highest score within each tier.
        tiered.sort(key=lambda x: (x[0], -x[1]))

        return [item[2] for item in tiered]

    def _score_candidate(
        self,
        candidate: Dict[str, Any],
        request: RoutingRequest,
        member: NetworkMember,
    ) -> float:
        """
        Score a routing candidate for selection.

        Enhanced scoring with recency decay — recent bookings count more
        than old ones, and market-specific reliability is factored in.

        Scoring breakdown (weights from SCORING_WEIGHTS):
        - Reliability (40%): recency-weighted completion rate.
        - Price competitiveness (30%): market breadth, priority-adjusted.
        - Revenue terms (20%): lower owner take = better for platform.
        - Recent volume (10%): activity within RECENCY_WINDOW, diminishing.

        Args:
            candidate: Route metadata dict from query_available_routes.
            request: The original routing request.
            member: The NetworkMember who owns the candidate credential.

        Returns:
            Score between 0.0 and 1.0.
        """
        strategy = request.strategy

        # --- Reliability (40%) ---
        # Use recency-weighted reliability for more accurate scoring
        reliability = self._calculate_reliability_with_recency(
            member, pos_market=request.pos_market,
        )

        # Strategy adjustment: best_reliability boosts this weight
        reliability_weight = SCORING_WEIGHTS["reliability"]
        if strategy == "best_reliability":
            reliability_weight = 0.55  # Boost to 55%

        score = reliability * reliability_weight

        # --- Price competitiveness (30%) ---
        price_score = 0.5
        if request.priority == "price" or strategy == "best_price":
            # Favor members with more POS markets (more arbitrage potential)
            market_breadth = len(candidate.get("pos_markets", []))
            price_score = min(0.3 + (market_breadth * 0.1), 1.0)
        elif request.priority == "speed":
            # Favor members with higher recent volume (warmed-up sessions)
            price_score = 0.4 if member.bookings_routed > 10 else 0.2

        price_weight = SCORING_WEIGHTS["price"]
        if strategy == "best_price":
            price_weight = 0.45  # Boost to 45%

        score += price_score * price_weight

        # --- Revenue terms (20%) ---
        # Lower owner take = more margin for platform + client provisionary
        owner_share = candidate.get("revenue_split", {}).get("owner", 0.30)
        revenue_score = 1.0 - owner_share  # Inverted: lower owner = higher score

        revenue_weight = SCORING_WEIGHTS["revenue_terms"]
        # Reduce weight if strategy isn't balanced
        if strategy in ("best_price", "best_reliability"):
            revenue_weight = 0.10

        score += revenue_score * revenue_weight

        # --- Volume (10%) ---
        # Only count recent bookings (within recency window)
        recent_bookings = self._count_recent_bookings(member)
        volume_score = min(recent_bookings / 50.0, 1.0)  # Diminish past 50

        volume_weight = SCORING_WEIGHTS["volume"]
        score += volume_score * volume_weight

        return round(min(score, 1.0), 4)

    def confirm_execution(
        self,
        result_id: str,
        execution_result: Dict[str, Any],
    ) -> Optional[RoutingResult]:
        """
        Confirm that a routed booking was successfully executed.

        Updates the routing result status, records revenue on the
        credential owner's member record, and increments booking counters.

        Args:
            result_id: The RoutingResult to confirm.
            execution_result: Dict with execution details (PNR, price,
                              booking reference, etc.).

        Returns:
            The updated RoutingResult, or None if result_id not found.
        """
        result = self._results.get(result_id)
        if not result:
            logger.warning("Cannot confirm: result %s not found", result_id)
            return None

        result.status = "completed"
        result.executed_at = time.time()
        result.execution_result = execution_result

        # Update owner member stats
        owner = self._members.get(result.owner_tenant_id)
        if owner:
            owner.bookings_routed += 1

            # Calculate and record revenue if transaction amount is provided
            tx_amount = execution_result.get("transaction_amount_usd")
            if tx_amount is not None:
                split = self.calculate_split(result, float(tx_amount))
                owner.revenue_earned_usd += split["owner_amount"]
                owner.revenue_paid_usd += split["platform_amount"]
                self._persist_member(owner)

        self._persist_result(result)

        self._event_bus.publish(Event(
            type=EventType.CUSTOM,
            source="credential_network",
            data={
                "action": "network.booking_completed",
                "result_id": result_id,
                "owner_tenant_id": result.owner_tenant_id,
                "provider_id": result.provider_id,
                "execution_result": execution_result,
            },
        ))

        logger.info("Booking execution confirmed: %s", result_id)
        return result

    def fail_execution(
        self,
        result_id: str,
        reason: str,
    ) -> Optional[RoutingResult]:
        """
        Record that a routed booking execution failed.

        Args:
            result_id: The RoutingResult that failed.
            reason: Human-readable failure reason.

        Returns:
            The updated RoutingResult, or None if result_id not found.
        """
        result = self._results.get(result_id)
        if not result:
            logger.warning("Cannot fail: result %s not found", result_id)
            return None

        result.status = "failed"
        result.executed_at = time.time()
        result.execution_result = {"error": reason}
        self._persist_result(result)

        self._event_bus.publish(Event(
            type=EventType.CUSTOM,
            source="credential_network",
            data={
                "action": "network.booking_failed",
                "result_id": result_id,
                "owner_tenant_id": result.owner_tenant_id,
                "reason": reason,
            },
        ))

        logger.warning("Booking execution failed: %s — %s", result_id, reason)
        return result

    def get_routing_history(
        self,
        tenant_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[RoutingResult]:
        """
        Retrieve routing history, optionally filtered by tenant.

        When tenant_id is provided, returns results where the tenant was
        either the credential owner or the requester.

        Args:
            tenant_id: Optional tenant filter (matches owner or requester).
            limit: Maximum number of results to return.

        Returns:
            List of RoutingResult instances, most recent first.
        """
        if tenant_id:
            filtered = [
                self._results[rid] for rid in reversed(self._routing_history)
                if rid in self._results and (
                    self._results[rid].owner_tenant_id == tenant_id
                    or self._results[rid].request_id in self._get_request_ids_for_tenant(tenant_id)
                )
            ]
        else:
            filtered = [
                self._results[rid] for rid in reversed(self._routing_history)
                if rid in self._results
            ]

        return filtered[:limit]

    # ------------------------------------------------------------------
    # Revenue
    # ------------------------------------------------------------------

    def calculate_split(
        self,
        result: RoutingResult,
        transaction_amount: float,
    ) -> Dict[str, float]:
        """
        Calculate the revenue split for a completed booking.

        Uses the revenue_split ratios from the RoutingResult to divide
        the transaction amount among owner, platform, and router.

        Args:
            result: The RoutingResult containing revenue_split ratios.
            transaction_amount: Total transaction amount in USD.

        Returns:
            Dict with owner_amount, platform_amount, and router_amount.
        """
        split = result.revenue_split
        owner_pct = split.get("owner", DEFAULT_REVENUE_SPLIT["owner"])
        platform_pct = split.get("platform", DEFAULT_REVENUE_SPLIT["platform"])
        router_pct = split.get("router", DEFAULT_REVENUE_SPLIT["router"])

        return {
            "owner_amount": round(transaction_amount * owner_pct, 2),
            "platform_amount": round(transaction_amount * platform_pct, 2),
            "router_amount": round(transaction_amount * router_pct, 2),
            "transaction_amount": round(transaction_amount, 2),
        }

    def get_revenue_summary(
        self,
        tenant_id: str,
        period: str = "month",
    ) -> Dict[str, Any]:
        """
        Revenue summary for a specific tenant.

        Args:
            tenant_id: The tenant to summarize.
            period: Time period — "month" (30 days), "week" (7 days),
                    or "all" (lifetime).

        Returns:
            Dict with earned (from hosting credentials), paid (platform
            fees), and net amounts.
        """
        member = self._members.get(tenant_id)
        if not member:
            return {"error": "tenant_not_found"}

        cutoff = self._get_period_cutoff(period)

        # Filter completed results within period where tenant was owner
        period_results = [
            self._results[rid] for rid in self._routing_history
            if rid in self._results
            and self._results[rid].owner_tenant_id == tenant_id
            and self._results[rid].status == "completed"
            and (self._results[rid].executed_at or 0) >= cutoff
        ]

        period_earned = 0.0
        period_paid = 0.0
        for result in period_results:
            tx_amount = (result.execution_result or {}).get(
                "transaction_amount_usd", 0
            )
            if tx_amount:
                split = self.calculate_split(result, float(tx_amount))
                period_earned += split["owner_amount"]
                period_paid += split["platform_amount"]

        return {
            "tenant_id": tenant_id,
            "period": period,
            "earned_usd": round(period_earned, 2),
            "paid_usd": round(period_paid, 2),
            "net_usd": round(period_earned - period_paid, 2),
            "bookings_in_period": len(period_results),
            "lifetime_earned_usd": round(member.revenue_earned_usd, 2),
            "lifetime_paid_usd": round(member.revenue_paid_usd, 2),
        }

    def get_network_revenue(self, period: str = "month") -> Dict[str, Any]:
        """
        Aggregate revenue statistics for the entire network.

        Args:
            period: Time period — "month", "week", or "all".

        Returns:
            Dict with total volume, platform revenue, and member payouts.
        """
        cutoff = self._get_period_cutoff(period)

        period_results = [
            self._results[rid] for rid in self._routing_history
            if rid in self._results
            and self._results[rid].status == "completed"
            and (self._results[rid].executed_at or 0) >= cutoff
        ]

        total_volume = 0.0
        platform_revenue = 0.0
        member_payouts = 0.0
        router_payouts = 0.0

        for result in period_results:
            tx_amount = (result.execution_result or {}).get(
                "transaction_amount_usd", 0
            )
            if tx_amount:
                split = self.calculate_split(result, float(tx_amount))
                total_volume += float(tx_amount)
                platform_revenue += split["platform_amount"]
                member_payouts += split["owner_amount"]
                router_payouts += split["router_amount"]

        return {
            "period": period,
            "total_volume_usd": round(total_volume, 2),
            "platform_revenue_usd": round(platform_revenue, 2),
            "member_payouts_usd": round(member_payouts, 2),
            "router_payouts_usd": round(router_payouts, 2),
            "bookings_completed": len(period_results),
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist_member(self, member: NetworkMember) -> None:
        """Write a member record to disk as JSON."""
        path = os.path.join(
            self._storage_dir, "members", f"{member.tenant_id}.json"
        )
        try:
            with open(path, "w") as f:
                json.dump(member.to_dict(), f, indent=2)
        except OSError as e:
            logger.error("Failed to persist member %s: %s", member.tenant_id, e)

    def _persist_result(self, result: RoutingResult) -> None:
        """Write a routing result to disk as JSON."""
        path = os.path.join(
            self._storage_dir, "results", f"{result.result_id}.json"
        )
        try:
            with open(path, "w") as f:
                json.dump(result.to_dict(), f, indent=2)
        except OSError as e:
            logger.error("Failed to persist result %s: %s", result.result_id, e)

    def _load_all(self) -> None:
        """Load all members and routing results from disk."""
        # Load members
        members_dir = os.path.join(self._storage_dir, "members")
        if os.path.isdir(members_dir):
            for filename in os.listdir(members_dir):
                if not filename.endswith(".json"):
                    continue
                path = os.path.join(members_dir, filename)
                try:
                    with open(path, "r") as f:
                        data = json.load(f)
                    member = NetworkMember.from_dict(data)
                    self._members[member.tenant_id] = member
                except (json.JSONDecodeError, OSError) as e:
                    logger.error("Failed to load member from %s: %s", path, e)

        # Load routing results
        results_dir = os.path.join(self._storage_dir, "results")
        if os.path.isdir(results_dir):
            for filename in sorted(os.listdir(results_dir)):
                if not filename.endswith(".json"):
                    continue
                path = os.path.join(results_dir, filename)
                try:
                    with open(path, "r") as f:
                        data = json.load(f)
                    result = RoutingResult.from_dict(data)
                    self._results[result.result_id] = result
                    self._routing_history.append(result.result_id)
                except (json.JSONDecodeError, OSError) as e:
                    logger.error("Failed to load result from %s: %s", path, e)

        logger.debug(
            "Loaded %d members, %d results from disk",
            len(self._members), len(self._results),
        )

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _update_coverage_from_vault(self, member: NetworkMember) -> None:
        """
        Rebuild a member's coverage map by querying the vault.

        Calls vault.list(tenant_id=member.tenant_id) to get all
        credentials, then extracts provider_id and pos_markets from
        each credential's metadata.
        """
        try:
            credentials = self._vault.list(tenant_id=member.tenant_id)
        except Exception as e:
            logger.warning(
                "Could not query vault for tenant %s: %s",
                member.tenant_id, e,
            )
            return

        coverage: Dict[str, List[str]] = {}
        capabilities: set = set()

        for cred in credentials:
            provider_id = cred.get("provider_id", "unknown")
            pos_markets = cred.get("pos_markets", [])
            vertical = cred.get("vertical", "flights")

            if provider_id not in coverage:
                coverage[provider_id] = []
            for market in pos_markets:
                if market not in coverage[provider_id]:
                    coverage[provider_id].append(market)

            capabilities.add(vertical)

        member.coverage = coverage
        member.capabilities = sorted(capabilities)
        member.credentials_shared = len(credentials)

    def _calculate_reliability(self, member: NetworkMember) -> float:
        """
        Calculate reliability score for a member based on booking history.

        Members with no history get a baseline 0.5. The score rises
        toward 1.0 as the ratio of completed bookings increases.
        """
        if member.bookings_routed == 0:
            return 0.5  # Neutral baseline for new members

        # Count completed vs failed for this member
        completed = 0
        failed = 0
        for rid in self._routing_history:
            result = self._results.get(rid)
            if not result or result.owner_tenant_id != member.tenant_id:
                continue
            if result.status == "completed":
                completed += 1
            elif result.status == "failed":
                failed += 1

        total = completed + failed
        if total == 0:
            return 0.5

        return round(completed / total, 4)

    def _calculate_reliability_with_recency(
        self,
        member: NetworkMember,
        pos_market: Optional[str] = None,
    ) -> float:
        """
        Calculate recency-weighted reliability score.

        More recent bookings contribute more weight than older ones.
        If pos_market is provided, factors in market-specific performance.

        The half-life model: a booking 30 days old contributes half the
        weight of a booking today. Bookings older than 90 days are ignored.

        Args:
            member: The network member to score.
            pos_market: Optional POS market for market-specific scoring.

        Returns:
            Reliability score between 0.0 and 1.0.
        """
        if member.bookings_routed == 0:
            return 0.5

        now = time.time()
        cutoff = now - RECENCY_WINDOW_SECONDS
        weighted_completed = 0.0
        weighted_failed = 0.0
        market_completed = 0
        market_failed = 0

        for rid in self._routing_history:
            result = self._results.get(rid)
            if not result or result.owner_tenant_id != member.tenant_id:
                continue

            # Skip results outside recency window
            result_time = result.executed_at or 0
            if result_time < cutoff:
                continue

            # Calculate recency weight (exponential decay with half-life)
            age = now - result_time
            weight = 2 ** (-age / RECENCY_HALF_LIFE_SECONDS)

            if result.status == "completed":
                weighted_completed += weight
                if pos_market and result.pos_market == pos_market:
                    market_completed += 1
            elif result.status == "failed":
                weighted_failed += weight
                if pos_market and result.pos_market == pos_market:
                    market_failed += 1

        total_weight = weighted_completed + weighted_failed
        if total_weight == 0:
            return 0.5

        # Base reliability from recency-weighted history
        base_reliability = weighted_completed / total_weight

        # If we have market-specific data, blend it in (20% weight)
        if pos_market and (market_completed + market_failed) >= 3:
            market_reliability = market_completed / (market_completed + market_failed)
            # Blend: 80% overall + 20% market-specific
            base_reliability = (base_reliability * 0.8) + (market_reliability * 0.2)

        return round(min(max(base_reliability, 0.0), 1.0), 4)

    def _count_recent_bookings(self, member: NetworkMember) -> int:
        """Count bookings for a member within the recency window."""
        cutoff = time.time() - RECENCY_WINDOW_SECONDS
        count = 0
        for rid in self._routing_history:
            result = self._results.get(rid)
            if not result or result.owner_tenant_id != member.tenant_id:
                continue
            if (result.executed_at or 0) >= cutoff:
                count += 1
        return count

    def _get_period_cutoff(self, period: str) -> float:
        """Convert a period string to a Unix timestamp cutoff."""
        now = time.time()
        if period == "week":
            return now - (7 * 86400)
        elif period == "month":
            return now - (30 * 86400)
        else:  # "all"
            return 0.0

    def _get_request_ids_for_tenant(self, tenant_id: str) -> set:
        """
        Get all request_ids where the tenant was the requester.

        Now that RoutingResult has a requester_tenant_id field, this is
        a direct lookup rather than best-effort inference.
        """
        return {
            result.request_id
            for result in self._results.values()
            if result.requester_tenant_id == tenant_id
        }
