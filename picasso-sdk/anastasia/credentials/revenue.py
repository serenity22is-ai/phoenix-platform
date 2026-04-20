"""
Revenue Calculator — Split calculations for the federated credential network.

LOCKED REVENUE MODEL (Build #203 — corrected from Build #201):
When a booking routes through a credential host's API credentials, revenue
is split between three parties:
  - Platform (APAi): PERCENTAGE fee by APAi tier — 5%/3%/2% of transaction.
  - Router (business owner): 70% of remaining spread — acquired the customer.
  - Credential host: 30% of remaining spread — lent API access, passive income.

APAi tier routing fees (comes off margin FIRST):
  - Pro ($299/mo):        5% of transaction
  - Enterprise ($599/mo): 3% of transaction
  - Scale ($999/mo):      2% of transaction
  $3 minimum fee. NO MAXIMUM CAP.

Own credentials = 100% to owner, zero routing fee, zero split.

MYSTES KYRIOS LLC — Confidential.
"""

import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------
# LOCKED revenue model — percentage fee + 70/30 split (Build #203)
# ---------------------------------------------------------------
# APAi tier routing fees: percentage of transaction, NOT flat.
# Corrected from Build #201 flat $2.50 error.
APAI_TIER_ROUTING_FEE = {
    "pro": 0.05,           # 5% — Pro tier ($299/mo)
    "enterprise": 0.03,    # 3% — Enterprise tier ($599/mo)
    "scale": 0.02,         # 2% — Scale tier ($999/mo)
}
DEFAULT_APAI_TIER = "pro"  # Default if tier not specified

ROUTER_PCT = 0.70               # Business owner (acquired the customer)
HOST_PCT = 0.30                 # Credential host (lent API access)
MIN_PLATFORM_FEE_USD = 3.00    # $3 minimum fee. NO maximum cap.

# Legacy compatibility: expose the old name pointing to Pro tier default
FLAT_PLATFORM_FEE_USD = None    # REMOVED — use APAI_TIER_ROUTING_FEE instead

# Legacy compatibility alias (used by existing code)
DEFAULT_SPLIT = {
    "credential_host": HOST_PCT,
    "platform_fee_pct": APAI_TIER_ROUTING_FEE[DEFAULT_APAI_TIER],
    "routing_agency": ROUTER_PCT,
}


@dataclass
class RevenueRecord:
    """A single revenue event from a routed booking."""

    record_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    route_result_id: str = ""
    credential_id: str = ""
    owner_tenant_id: str = ""    # Credential host
    router_tenant_id: str = ""   # Agency that sourced customer
    provider_id: str = ""
    transaction_amount_usd: float = 0.0
    apai_tier: str = DEFAULT_APAI_TIER
    split_ratios: Dict[str, float] = field(default_factory=lambda: {
        "credential_host": HOST_PCT,
        "platform_fee_pct": APAI_TIER_ROUTING_FEE[DEFAULT_APAI_TIER],
        "routing_agency": ROUTER_PCT,
    })
    owner_amount_usd: float = 0.0
    platform_amount_usd: float = 0.0
    router_amount_usd: float = 0.0
    currency: str = "USD"
    period: str = ""             # "2026-03" for monthly aggregation
    created_at: float = field(default_factory=time.time)
    status: str = "pending"      # pending, settled, disputed

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "RevenueRecord":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class RevenueCalculator:
    """
    Calculates and tracks revenue splits for the credential network.

    LOCKED MODEL (Build #203): Platform takes PERCENTAGE fee by APAi tier.
    5% (Pro) / 3% (Enterprise) / 2% (Scale) of transaction. $3 minimum.
    NO maximum cap. Remaining splits 70/30 (router/host).
    Own credentials = 100% to owner, zero fee.
    """

    def __init__(self, storage_dir: Optional[str] = None):
        self._storage_dir = Path(
            storage_dir or Path.home() / ".anastasia" / "revenue"
        )
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._records: Dict[str, RevenueRecord] = {}
        self._load_all()

    # ------------------------------------------------------------------
    # Split Calculation
    # ------------------------------------------------------------------

    def calculate_split(
        self,
        transaction_amount: float,
        custom_split: Optional[Dict[str, float]] = None,
        apai_tier: str = DEFAULT_APAI_TIER,
        is_own_credentials: bool = False,
    ) -> Dict[str, float]:
        """
        Calculate revenue split amounts for a transaction.

        Args:
            transaction_amount: Total transaction in USD.
            custom_split: Optional override ratios (router/host percentages).
            apai_tier: APAi tier ("pro"/"enterprise"/"scale") — determines fee %.
            is_own_credentials: If True, 100% to owner, zero fee.

        Returns:
            Dict with owner_amount, platform_amount, router_amount, ratios.
        """
        # Own credentials = 100% to owner, zero routing
        if is_own_credentials:
            return {
                "transaction_amount": transaction_amount,
                "owner_amount": round(transaction_amount, 2),
                "platform_amount": 0.0,
                "router_amount": 0.0,
                "apai_tier": apai_tier,
                "ratios": {"credential_host": 1.0, "platform": 0.0, "routing_agency": 0.0},
            }

        # Platform fee: percentage of transaction by APAi tier
        tier_key = apai_tier.lower() if apai_tier else DEFAULT_APAI_TIER
        fee_pct = APAI_TIER_ROUTING_FEE.get(tier_key, APAI_TIER_ROUTING_FEE[DEFAULT_APAI_TIER])
        raw_fee = transaction_amount * fee_pct

        # $3 minimum fee, NO maximum cap (corrected 4+ times — NEVER add a cap)
        platform_fee = max(raw_fee, MIN_PLATFORM_FEE_USD)

        # Remaining amount splits between router and host
        remaining = max(transaction_amount - platform_fee, 0.0)

        if custom_split:
            router_pct = custom_split.get("routing_agency", ROUTER_PCT)
            host_pct = custom_split.get("credential_host", HOST_PCT)
            # Normalize if they don't sum to 1.0
            total_pct = router_pct + host_pct
            if total_pct > 0 and abs(total_pct - 1.0) > 0.01:
                router_pct = router_pct / total_pct
                host_pct = host_pct / total_pct
        else:
            router_pct = ROUTER_PCT
            host_pct = HOST_PCT

        router = round(remaining * router_pct, 2)
        owner = round(remaining * host_pct, 2)

        return {
            "transaction_amount": transaction_amount,
            "owner_amount": owner,
            "platform_amount": round(platform_fee, 2),
            "router_amount": router,
            "apai_tier": tier_key,
            "ratios": {
                "credential_host": host_pct,
                "platform_fee_pct": fee_pct,
                "routing_agency": router_pct,
            },
        }

    def record_revenue(
        self,
        route_result_id: str,
        credential_id: str,
        owner_tenant_id: str,
        router_tenant_id: str,
        provider_id: str,
        transaction_amount: float,
        custom_split: Optional[Dict[str, float]] = None,
        apai_tier: str = DEFAULT_APAI_TIER,
        is_own_credentials: bool = False,
    ) -> RevenueRecord:
        """
        Record a revenue event from a routed booking.

        Calculates split, creates RevenueRecord, persists to disk.
        """
        split = self.calculate_split(
            transaction_amount, custom_split,
            apai_tier=apai_tier,
            is_own_credentials=is_own_credentials,
        )
        now = time.time()
        period = time.strftime("%Y-%m", time.localtime(now))

        record = RevenueRecord(
            route_result_id=route_result_id,
            credential_id=credential_id,
            owner_tenant_id=owner_tenant_id,
            router_tenant_id=router_tenant_id,
            provider_id=provider_id,
            transaction_amount_usd=transaction_amount,
            apai_tier=split.get("apai_tier", apai_tier),
            split_ratios=split["ratios"],
            owner_amount_usd=split["owner_amount"],
            platform_amount_usd=split["platform_amount"],
            router_amount_usd=split["router_amount"],
            period=period,
            created_at=now,
            status="pending",
        )

        self._records[record.record_id] = record
        self._persist(record)

        logger.info(
            "Revenue recorded: $%.2f split — host=$%.2f, platform=$%.2f, router=$%.2f",
            transaction_amount,
            record.owner_amount_usd,
            record.platform_amount_usd,
            record.router_amount_usd,
        )

        return record

    def settle_record(self, record_id: str) -> Optional[RevenueRecord]:
        """Mark a revenue record as settled (payment disbursed)."""
        record = self._records.get(record_id)
        if not record:
            return None
        record.status = "settled"
        self._persist(record)
        return record

    # ------------------------------------------------------------------
    # Revenue Queries
    # ------------------------------------------------------------------

    def get_tenant_summary(
        self,
        tenant_id: str,
        period: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get revenue summary for a tenant (as credential host or router).

        Returns earned (from hosting creds), paid (routing fees), net.
        """
        if not period:
            period = time.strftime("%Y-%m")

        earned_as_host = 0.0
        earned_as_router = 0.0
        platform_fees = 0.0
        transaction_count = 0

        for r in self._records.values():
            if r.period != period:
                continue
            if r.owner_tenant_id == tenant_id:
                earned_as_host += r.owner_amount_usd
                transaction_count += 1
            if r.router_tenant_id == tenant_id:
                earned_as_router += r.router_amount_usd
            if r.owner_tenant_id == tenant_id or r.router_tenant_id == tenant_id:
                platform_fees += r.platform_amount_usd

        return {
            "tenant_id": tenant_id,
            "period": period,
            "earned_as_host": round(earned_as_host, 2),
            "earned_as_router": round(earned_as_router, 2),
            "total_earned": round(earned_as_host + earned_as_router, 2),
            "platform_fees": round(platform_fees, 2),
            "transactions": transaction_count,
        }

    def get_network_revenue(
        self,
        period: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get platform-wide revenue summary.

        Returns total volume, platform revenue, member payouts.
        """
        if not period:
            period = time.strftime("%Y-%m")

        total_volume = 0.0
        platform_revenue = 0.0
        host_payouts = 0.0
        router_payouts = 0.0
        transaction_count = 0

        for r in self._records.values():
            if r.period != period:
                continue
            total_volume += r.transaction_amount_usd
            platform_revenue += r.platform_amount_usd
            host_payouts += r.owner_amount_usd
            router_payouts += r.router_amount_usd
            transaction_count += 1

        return {
            "period": period,
            "total_volume_usd": round(total_volume, 2),
            "platform_revenue_usd": round(platform_revenue, 2),
            "host_payouts_usd": round(host_payouts, 2),
            "router_payouts_usd": round(router_payouts, 2),
            "transactions": transaction_count,
            "avg_transaction_usd": round(
                total_volume / transaction_count, 2
            ) if transaction_count > 0 else 0.0,
        }

    def estimate_annual_value(self, tenant_id: str) -> Dict[str, Any]:
        """
        Project annual revenue based on recent monthly performance.

        Uses the most recent period with data for projection.
        """
        current_period = time.strftime("%Y-%m")
        summary = self.get_tenant_summary(tenant_id, current_period)

        return {
            "tenant_id": tenant_id,
            "monthly_earned": summary["total_earned"],
            "projected_annual": round(summary["total_earned"] * 12, 2),
            "monthly_transactions": summary["transactions"],
            "projected_annual_transactions": summary["transactions"] * 12,
            "based_on_period": current_period,
        }

    def get_records(
        self,
        tenant_id: Optional[str] = None,
        period: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[RevenueRecord]:
        """Query revenue records with optional filters."""
        results = list(self._records.values())

        if tenant_id:
            results = [
                r for r in results
                if r.owner_tenant_id == tenant_id
                or r.router_tenant_id == tenant_id
            ]
        if period:
            results = [r for r in results if r.period == period]
        if status:
            results = [r for r in results if r.status == status]

        results.sort(key=lambda r: r.created_at, reverse=True)
        return results[:limit]

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist(self, record: RevenueRecord) -> None:
        """Write a revenue record to disk."""
        path = self._storage_dir / f"{record.record_id}.json"
        path.write_text(json.dumps(record.to_dict(), indent=2))

    def _load_all(self) -> None:
        """Load all revenue records from disk."""
        for path in self._storage_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text())
                record = RevenueRecord.from_dict(data)
                self._records[record.record_id] = record
            except Exception as e:
                logger.warning("Failed to load revenue record %s: %s", path.name, e)

        if self._records:
            logger.info("Loaded %d revenue records", len(self._records))

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @property
    def record_count(self) -> int:
        return len(self._records)

    def get_stats(self) -> Dict[str, Any]:
        """Aggregate revenue statistics."""
        by_status = {}
        by_provider = {}
        total_volume = 0.0

        for r in self._records.values():
            by_status[r.status] = by_status.get(r.status, 0) + 1
            by_provider[r.provider_id] = by_provider.get(r.provider_id, 0) + 1
            total_volume += r.transaction_amount_usd

        return {
            "total_records": len(self._records),
            "total_volume_usd": round(total_volume, 2),
            "by_status": by_status,
            "by_provider": by_provider,
        }
