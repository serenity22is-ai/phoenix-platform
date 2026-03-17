"""
Mystes Node Anti-Dilution System (Build #97)

Protects the node reward pool from Sybil attacks and pool dilution by
implementing ratio caps and demand-based throttling.

Defense Strategy:
1. Ratio Cap: Dedicated nodes capped at 10% of data-generating nodes
2. Demand Cap: No more nodes than market demand requires
3. Geographic Distribution: Flag suspicious concentration
4. Escrow Period: New nodes have 30-day payout delay

Node Types:
- mobile: iOS/Android app users (HIGH data value)
- desktop: macOS/Windows/Linux desktop users (HIGH data value)
- dedicated_server: Always-on servers (uptime value only)

The key insight: Mobile/desktop nodes can't be faked at scale because
they require real human browsing behavior. Dedicated servers are easier
to spin up, so they're capped relative to real user nodes.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Ratio cap: dedicated nodes cannot exceed this fraction of data nodes
DEDICATED_TO_DATA_RATIO = 0.10  # 10%

# Minimum data nodes before dedicated cap applies (bootstrap phase)
MIN_DATA_NODES_FOR_CAP = 100

# Geographic concentration threshold (flag if >X% from single country)
GEO_CONCENTRATION_THRESHOLD = 0.40  # 40%

# New node escrow period (days before first payout eligible)
NEW_NODE_ESCROW_DAYS = 30

# Demand-based cap: GB capacity per node (estimate)
AVG_NODE_CAPACITY_GB_PER_MONTH = 50

# Suspicious onboarding spike (nodes per hour triggers review)
ONBOARDING_SPIKE_THRESHOLD = 100


# ---------------------------------------------------------------------------
# Node Type Classification
# ---------------------------------------------------------------------------

def classify_node_type(capabilities: dict) -> str:
    """Classify a node based on its capabilities.

    Args:
        capabilities: Node capabilities dict from registration

    Returns:
        'mobile', 'desktop', or 'dedicated_server'
    """
    platform = capabilities.get("platform", "").lower()
    has_extension = capabilities.get("has_extension", False)
    has_browser = capabilities.get("has_browser", False)
    has_auth_sessions = capabilities.get("has_auth_sessions", False)

    # Mobile detection (iOS/Android - future platforms)
    if platform in ("ios", "android", "mobile"):
        return "mobile"

    # Desktop with real user activity indicators
    if platform in ("windows", "macos", "linux"):
        # If they have extension or auth sessions, they're a real user
        if has_extension or has_auth_sessions:
            return "desktop"
        # If they have browser but no extension/auth, might be dedicated
        # But default to desktop for now (benefit of doubt)
        if has_browser:
            return "desktop"

    # Default: assume dedicated server (headless, no user interaction)
    return "dedicated_server"


def is_data_generating_node(node_type: str) -> bool:
    """Check if a node type generates valuable user data."""
    return node_type in ("mobile", "desktop")


# ---------------------------------------------------------------------------
# Node Counts (from registry or database)
# ---------------------------------------------------------------------------

def get_node_counts() -> Dict[str, int]:
    """Get current node counts by type.

    Returns:
        Dict with 'mobile', 'desktop', 'dedicated_server', 'total' counts
    """
    try:
        from node_registry import node_registry

        counts = {
            "mobile": 0,
            "desktop": 0,
            "dedicated_server": 0,
            "total": 0,
        }

        # Count from in-memory registry
        for node in node_registry._nodes.values():
            caps = node.capabilities.to_dict() if hasattr(node.capabilities, 'to_dict') else {}
            node_type = classify_node_type(caps)
            counts[node_type] = counts.get(node_type, 0) + 1
            counts["total"] += 1

        return counts
    except Exception as e:
        logger.error(f"Failed to get node counts: {e}")
        return {"mobile": 0, "desktop": 0, "dedicated_server": 0, "total": 0}


def get_proxy_demand_gb() -> float:
    """Get current monthly proxy demand in GB.

    Measures real demand from two sources (Build #109):
    1. BrowsingEvent ingestion volume (last 30 days)
    2. CitizenSERP task dispatches (last 30 days)

    Each browsing event ~ 5KB avg payload, each task ~ 500KB avg (screenshots + data).
    Falls back to node-count estimate if DB unavailable.

    Returns:
        Estimated monthly proxy demand in GB.
    """
    try:
        from models import db, BrowsingEvent
        from datetime import datetime, timedelta
        from sqlalchemy import func

        cutoff = datetime.utcnow() - timedelta(days=30)

        # Source 1: BrowsingEvent count (each ~ 5KB)
        event_count = BrowsingEvent.query.filter(
            BrowsingEvent.ingested_at >= cutoff
        ).count()
        events_gb = (event_count * 5) / (1024 * 1024)  # 5KB per event → GB

        # Source 2: CitizenSERP task volume (each ~ 500KB avg w/ screenshots)
        task_gb = 0.0
        try:
            from citizenserp_tasks import task_dispatcher
            stats = task_dispatcher.get_stats()
            completed = stats.get("total_completed", 0)
            task_gb = (completed * 500) / (1024 * 1024)  # 500KB per task → GB
        except ImportError:
            pass

        total_demand = events_gb + task_gb

        # If no real data yet, fall back to node-count estimate
        if total_demand < 0.01:
            from node_registry import node_registry
            active_nodes = len([n for n in node_registry._nodes.values()
                               if n.status in ("online", "idle", "busy")])
            return active_nodes * AVG_NODE_CAPACITY_GB_PER_MONTH * 0.30

        return total_demand

    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Cap Calculations
# ---------------------------------------------------------------------------

def calculate_dedicated_node_cap() -> Dict[str, any]:
    """Calculate the current cap on dedicated server nodes.

    Returns:
        Dict with:
        - ratio_cap: Max dedicated nodes based on data node ratio
        - demand_cap: Max dedicated nodes based on market demand
        - effective_cap: The lower of the two (actual limit)
        - current_dedicated: Current dedicated node count
        - headroom: How many more dedicated nodes can join
        - at_capacity: Boolean if cap is reached
    """
    counts = get_node_counts()
    data_nodes = counts["mobile"] + counts["desktop"]
    dedicated_nodes = counts["dedicated_server"]

    # Ratio cap: dedicated <= 10% of data nodes
    if data_nodes >= MIN_DATA_NODES_FOR_CAP:
        ratio_cap = int(data_nodes * DEDICATED_TO_DATA_RATIO)
    else:
        # Bootstrap phase: allow some dedicated nodes before we have many users
        ratio_cap = max(10, int(data_nodes * DEDICATED_TO_DATA_RATIO))

    # Demand cap: based on actual proxy sales volume
    demand_gb = get_proxy_demand_gb()
    if demand_gb > 0:
        demand_cap = int(demand_gb / AVG_NODE_CAPACITY_GB_PER_MONTH) + 10  # +10 buffer
    else:
        # No demand data yet, use generous default
        demand_cap = max(100, ratio_cap * 2)

    # Effective cap is the LOWER of the two
    effective_cap = min(ratio_cap, demand_cap)

    # Ensure minimum cap for bootstrap
    effective_cap = max(effective_cap, 10)

    headroom = max(0, effective_cap - dedicated_nodes)

    return {
        "ratio_cap": ratio_cap,
        "demand_cap": demand_cap,
        "effective_cap": effective_cap,
        "current_dedicated": dedicated_nodes,
        "current_data_nodes": data_nodes,
        "headroom": headroom,
        "at_capacity": headroom <= 0,
        "ratio_used": f"{dedicated_nodes}/{ratio_cap}" if ratio_cap > 0 else "0/0",
    }


# ---------------------------------------------------------------------------
# Anti-Dilution Checks
# ---------------------------------------------------------------------------

def check_onboarding_allowed(capabilities: dict, user_id: int = None) -> Tuple[bool, str]:
    """Check if a new node can be onboarded.

    Args:
        capabilities: Node capabilities from registration request
        user_id: Optional user ID for additional checks

    Returns:
        Tuple of (allowed: bool, reason: str)
    """
    node_type = classify_node_type(capabilities)

    # Data-generating nodes (mobile/desktop) are always allowed
    if is_data_generating_node(node_type):
        return True, "Data-generating nodes welcome"

    # Dedicated server nodes are subject to caps
    cap_info = calculate_dedicated_node_cap()

    if cap_info["at_capacity"]:
        return False, (
            f"Dedicated server cap reached ({cap_info['current_dedicated']}/{cap_info['effective_cap']}). "
            f"Need more mobile/desktop users to increase capacity. "
            f"Current ratio: {cap_info['current_dedicated']} dedicated / {cap_info['current_data_nodes']} data nodes."
        )

    return True, f"Dedicated node allowed ({cap_info['headroom']} slots remaining)"


def check_geographic_concentration() -> Dict[str, any]:
    """Check for suspicious geographic concentration of nodes.

    Returns:
        Dict with concentration analysis and any flags.
    """
    try:
        from node_registry import node_registry

        country_counts = {}
        total = 0

        for node in node_registry._nodes.values():
            country = node.capabilities.country_code
            country_counts[country] = country_counts.get(country, 0) + 1
            total += 1

        if total == 0:
            return {"total": 0, "flags": [], "distribution": {}}

        flags = []
        distribution = {}

        for country, count in country_counts.items():
            pct = count / total
            distribution[country] = {"count": count, "percentage": round(pct * 100, 1)}

            if pct > GEO_CONCENTRATION_THRESHOLD:
                flags.append({
                    "type": "high_concentration",
                    "country": country,
                    "percentage": round(pct * 100, 1),
                    "threshold": GEO_CONCENTRATION_THRESHOLD * 100,
                })

        return {
            "total": total,
            "flags": flags,
            "distribution": distribution,
            "healthy": len(flags) == 0,
        }
    except Exception as e:
        logger.error(f"Geographic concentration check failed: {e}")
        return {"total": 0, "flags": [], "distribution": {}, "error": str(e)}


def check_onboarding_spike() -> Dict[str, any]:
    """Check for suspicious onboarding spikes.

    Returns:
        Dict with spike analysis.
    """
    try:
        from node_registry import node_registry

        now = datetime.utcnow()
        one_hour_ago = now - timedelta(hours=1)

        recent_count = 0
        for node in node_registry._nodes.values():
            try:
                registered = datetime.fromisoformat(node.registered_at.replace('Z', '+00:00'))
                if registered.replace(tzinfo=None) >= one_hour_ago:
                    recent_count += 1
            except Exception:
                pass

        is_spike = recent_count >= ONBOARDING_SPIKE_THRESHOLD

        return {
            "nodes_last_hour": recent_count,
            "threshold": ONBOARDING_SPIKE_THRESHOLD,
            "is_spike": is_spike,
            "action_required": is_spike,
        }
    except Exception as e:
        logger.error(f"Onboarding spike check failed: {e}")
        return {"nodes_last_hour": 0, "is_spike": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Escrow / Payout Eligibility
# ---------------------------------------------------------------------------

def get_escrow_end_date(registered_at: datetime) -> datetime:
    """Calculate when a node becomes payout-eligible.

    Args:
        registered_at: When the node was first registered

    Returns:
        Datetime when escrow period ends
    """
    return registered_at + timedelta(days=NEW_NODE_ESCROW_DAYS)


def is_payout_eligible(registered_at: datetime) -> bool:
    """Check if a node has completed its escrow period.

    Args:
        registered_at: When the node was first registered

    Returns:
        True if eligible for payouts
    """
    return datetime.utcnow() >= get_escrow_end_date(registered_at)


# ---------------------------------------------------------------------------
# Admin Dashboard Data
# ---------------------------------------------------------------------------

def get_antidilution_status() -> Dict[str, any]:
    """Get full anti-dilution system status for admin dashboard.

    Returns:
        Comprehensive status dict for admin visibility.
    """
    cap_info = calculate_dedicated_node_cap()
    geo_info = check_geographic_concentration()
    spike_info = check_onboarding_spike()
    counts = get_node_counts()

    return {
        "node_counts": counts,
        "dedicated_cap": cap_info,
        "geographic": geo_info,
        "onboarding_spike": spike_info,
        "config": {
            "dedicated_ratio_limit": DEDICATED_TO_DATA_RATIO,
            "min_data_nodes_for_cap": MIN_DATA_NODES_FOR_CAP,
            "geo_concentration_threshold": GEO_CONCENTRATION_THRESHOLD,
            "escrow_days": NEW_NODE_ESCROW_DAYS,
            "spike_threshold": ONBOARDING_SPIKE_THRESHOLD,
        },
        "health": {
            "cap_healthy": not cap_info["at_capacity"],
            "geo_healthy": geo_info.get("healthy", True),
            "no_spike": not spike_info.get("is_spike", False),
            "overall": (
                not cap_info["at_capacity"]
                and geo_info.get("healthy", True)
                and not spike_info.get("is_spike", False)
            ),
        },
    }
