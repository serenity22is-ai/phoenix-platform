"""
PHOENIX AI Agent Orchestrator

The brain of Phoenix. PhoenixAI decides WHAT to search, WHERE to search,
and HOW to interpret results — without human decision-making.

Architecture:
    PhoenixAI reads its own intelligence data (via intelligence routes/tools),
    dispatches CitizenSERP tasks to nodes across markets, aggregates results,
    and feeds them through the AI ensemble for analysis.

    Three coexisting AI systems:
    1. Search pipeline (tool) — user-driven, already built
    2. BYOAI via proxy (infrastructure) — user's own AI, already built
    3. Agent mode (THIS) — PhoenixAI makes autonomous decisions

    The agent doesn't "learn" via LLM training. Phoenix's database IS the memory.
    More searches → richer data → better AI context → smarter decisions.

Tools available to the agent:
    Each /api/intelligence/* route is a callable tool:
    - route_intelligence(origin, dest)    → pricing by market, trends
    - market_briefing(market)             → popular routes, savings
    - platform_stats()                    → search volume, coverage
    - p2p_network()                       → helper coverage, capacity
    - node_network()                      → CitizenSERP node availability
    - proxy_usage()                       → which sites/markets active
    - ai_analytics()                      → provider performance
    - alert_demand()                      → most-watched routes
    - price_timeline(origin, dest)        → historical pricing
    - airline_comparison(origin, dest)    → airline-level pricing

Usage:
    from phoenix_agent import phoenix_agent

    # Agent handles a search request end-to-end
    result = phoenix_agent.handle_search(
        query="cheapest flights JFK to Tokyo in March",
        user_id=42
    )

    # Agent discovers new arbitrage opportunities autonomously
    opportunities = phoenix_agent.discover_opportunities()

    # Agent decides which markets to search for a route
    markets = phoenix_agent.select_markets("JFK", "NRT")
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)


# ============================================================
# Agent Configuration
# ============================================================

AGENT_CONFIG = {
    # Market selection
    "max_markets_per_search": int(os.getenv("AGENT_MAX_MARKETS", "8")),
    "min_market_confidence": float(os.getenv("AGENT_MIN_CONFIDENCE", "0.3")),

    # Task dispatch
    "max_concurrent_tasks": int(os.getenv("AGENT_MAX_TASKS", "20")),
    "task_timeout_seconds": int(os.getenv("AGENT_TASK_TIMEOUT", "60")),

    # Discovery
    "discovery_interval_hours": int(os.getenv("AGENT_DISCOVERY_INTERVAL", "6")),
    "min_savings_threshold_pct": float(os.getenv("AGENT_MIN_SAVINGS_PCT", "5.0")),

    # AI ensemble
    "use_ensemble_for_analysis": True,
    "max_ensemble_providers": 5,
}


# ============================================================
# Agent Tool Definitions — wraps intelligence routes
# ============================================================

class AgentTools:
    """
    Wraps PhoenixIntelligence methods as callable agent tools.
    Each tool returns structured data the agent uses for decision-making.
    """

    def __init__(self):
        self._intelligence = None
        self._tracker = None

    @property
    def intelligence(self):
        if self._intelligence is None:
            try:
                from phoenix_intelligence import intelligence
                self._intelligence = intelligence
            except ImportError:
                logger.error("phoenix_intelligence not available")
        return self._intelligence

    @property
    def tracker(self):
        if self._tracker is None:
            try:
                from search_tracker import search_tracker
                self._tracker = search_tracker
            except ImportError:
                logger.error("search_tracker not available")
        return self._tracker

    def route_intelligence(self, origin: str, destination: str) -> Dict[str, Any]:
        """Get multi-market pricing data for a route."""
        try:
            if self.intelligence:
                return self.intelligence.get_route_intelligence(origin, destination)
            return {"error": "intelligence not available"}
        except Exception as e:
            return {"error": str(e)}

    def market_briefing(self, market: str) -> Dict[str, Any]:
        """Get market overview — popular routes, savings, demand."""
        try:
            if self.intelligence:
                return self.intelligence.get_market_briefing(market)
            return {"error": "intelligence not available"}
        except Exception as e:
            return {"error": str(e)}

    def platform_stats(self) -> Dict[str, Any]:
        """Get platform-wide statistics."""
        try:
            if self.intelligence:
                return self.intelligence.get_platform_stats()
            return {"error": "intelligence not available"}
        except Exception as e:
            return {"error": str(e)}

    def p2p_network(self) -> Dict[str, Any]:
        """Get P2P helper network coverage and capacity."""
        try:
            if self.intelligence:
                return self.intelligence.get_p2p_network()
            return {"error": "intelligence not available"}
        except Exception as e:
            return {"error": str(e)}

    def node_network(self) -> Dict[str, Any]:
        """Get CitizenSERP node network status."""
        try:
            if self.intelligence:
                return self.intelligence.get_node_network()
            return {"error": "intelligence not available"}
        except Exception as e:
            return {"error": str(e)}

    def proxy_usage(self, days_back: int = 7) -> Dict[str, Any]:
        """Get proxy portal usage patterns."""
        try:
            if self.intelligence:
                return self.intelligence.get_proxy_usage(days_back)
            return {"error": "intelligence not available"}
        except Exception as e:
            return {"error": str(e)}

    def ai_analytics(self) -> Dict[str, Any]:
        """Get AI provider performance data."""
        try:
            if self.intelligence:
                return self.intelligence.get_ai_analytics()
            return {"error": "intelligence not available"}
        except Exception as e:
            return {"error": str(e)}

    def alert_demand(self, limit: int = 20) -> Dict[str, Any]:
        """Get price alert demand signals — most-watched routes."""
        try:
            if self.intelligence:
                return self.intelligence.get_alert_demand(limit)
            return {"error": "intelligence not available"}
        except Exception as e:
            return {"error": str(e)}

    def price_timeline(self, origin: str, destination: str, days: int = 30) -> Dict[str, Any]:
        """Get historical price timeline for a route."""
        try:
            if self.intelligence:
                return self.intelligence.get_price_timeline(origin, destination, days)
            return {"error": "intelligence not available"}
        except Exception as e:
            return {"error": str(e)}

    def airline_comparison(self, origin: str, destination: str) -> Dict[str, Any]:
        """Get airline-level competitive pricing."""
        try:
            if self.intelligence:
                return self.intelligence.get_airline_comparison(origin, destination)
            return {"error": "intelligence not available"}
        except Exception as e:
            return {"error": str(e)}

    def p2p_savings(self, days: int = 30) -> Dict[str, Any]:
        """Get top savings routes from P2P transactions."""
        try:
            if self.intelligence:
                return self.intelligence.get_p2p_savings(days)
            return {"error": "intelligence not available"}
        except Exception as e:
            return {"error": str(e)}

    def get_popular_routes(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get most-searched routes from search history."""
        try:
            if self.tracker:
                return self.tracker.get_popular_routes(limit=limit)
            return []
        except Exception as e:
            logger.error(f"Error getting popular routes: {e}")
            return []


# ============================================================
# Market Selection Engine
# ============================================================

class MarketSelector:
    """
    Decides which markets to search for a given route or product.
    Uses intelligence data to pick markets most likely to have savings.
    """

    # Default priority markets (historical best savings)
    PRIORITY_MARKETS = [
        "JP", "IN", "BR", "MX", "TR", "PL", "TH", "VN",
        "ID", "PH", "EG", "CO", "PE", "AR", "NG",
        "MY", "SA", "ZA", "RO"
    ]

    # Always include the user's home market for baseline pricing
    BASELINE_MARKETS = ["US", "GB", "DE"]

    def __init__(self, tools: AgentTools):
        self.tools = tools

    def select_markets(self, origin: str = None, destination: str = None,
                       task_type: str = "flight_search",
                       max_markets: int = None,
                       user_market: str = "US") -> List[Dict[str, Any]]:
        """
        Select best markets to search, ranked by expected savings.

        Returns list of {market, confidence, reason} dicts.
        """
        if max_markets is None:
            max_markets = AGENT_CONFIG["max_markets_per_search"]

        candidates = []

        # 1. Always include baseline (user's home market)
        candidates.append({
            "market": user_market,
            "confidence": 1.0,
            "reason": "user_home_market"
        })

        # 2. Check route intelligence if we have origin/dest
        if origin and destination:
            route_data = self.tools.route_intelligence(origin, destination)
            if "error" not in route_data and "markets" in route_data:
                for mkt_data in route_data.get("markets", []):
                    mkt_code = mkt_data.get("market", "")
                    if mkt_code and mkt_code != user_market:
                        savings = mkt_data.get("savings_pct", 0)
                        candidates.append({
                            "market": mkt_code,
                            "confidence": min(1.0, savings / 20.0) if savings > 0 else 0.4,
                            "reason": f"route_history_{savings:.0f}pct_savings"
                        })

        # 3. Check P2P network for node availability
        network_data = self.tools.node_network()
        available_markets = set()
        if "error" not in network_data:
            nodes_by_country = network_data.get("nodes_by_country", {})
            available_markets = set(nodes_by_country.keys())

        # 4. Add priority markets that have active nodes
        for mkt in self.PRIORITY_MARKETS:
            if mkt in available_markets and not any(c["market"] == mkt for c in candidates):
                candidates.append({
                    "market": mkt,
                    "confidence": 0.5,
                    "reason": "priority_market_with_node"
                })

        # 5. Add priority markets without nodes (lower confidence — will use proxy)
        for mkt in self.PRIORITY_MARKETS:
            if not any(c["market"] == mkt for c in candidates):
                candidates.append({
                    "market": mkt,
                    "confidence": 0.3,
                    "reason": "priority_market_proxy_only"
                })

        # 6. Filter by minimum confidence
        min_conf = AGENT_CONFIG["min_market_confidence"]
        candidates = [c for c in candidates if c["confidence"] >= min_conf]

        # 7. Sort by confidence descending, take top N
        candidates.sort(key=lambda x: x["confidence"], reverse=True)
        return candidates[:max_markets]

    def select_zones(self, origin: str = None, destination: str = None,
                     user_market: str = "US",
                     max_zones: int = None) -> List[Dict[str, Any]]:
        """
        Zone-level market selection. Returns zone codes instead of country codes.
        Falls back to country-level when zone data isn't available.

        Key feature: includes intra-country zones for the user's home market
        to capture domestic price discrimination.
        """
        if max_zones is None:
            max_zones = AGENT_CONFIG["max_markets_per_search"] * 2  # More zones than markets

        try:
            from geographic_zones import (
                get_zones_for_country, resolve_market, is_zone_code,
                get_zone_for_city
            )
        except ImportError:
            # Fallback to country-level selection
            markets = self.select_markets(origin, destination, user_market=user_market)
            return markets

        candidates = []

        # 1. Add multiple zones within user's home country (intra-country arbitrage)
        home_zones = get_zones_for_country(user_market)
        for zone in home_zones:
            candidates.append({
                "market": zone.zone_code,
                "confidence": 0.7,
                "reason": f"home_country_zone_{zone.name}",
                "zone": True,
            })

        # 2. Get country-level selections, expand to zones where possible
        country_markets = self.select_markets(
            origin, destination, user_market=user_market,
            max_markets=AGENT_CONFIG["max_markets_per_search"],
        )
        for cm in country_markets:
            mkt = cm["market"]
            if mkt == user_market:
                continue  # Already added zones above
            foreign_zones = get_zones_for_country(mkt)
            if foreign_zones:
                # Add top zone(s) from each foreign country (major tier first)
                major_zones = [z for z in foreign_zones if z.population_tier == "major"]
                if major_zones:
                    for z in major_zones[:2]:
                        candidates.append({
                            "market": z.zone_code,
                            "confidence": cm["confidence"],
                            "reason": f"{cm['reason']}_zone_{z.name}",
                            "zone": True,
                        })
                else:
                    # Use first zone for smaller countries
                    candidates.append({
                        "market": foreign_zones[0].zone_code,
                        "confidence": cm["confidence"],
                        "reason": f"{cm['reason']}_zone_{foreign_zones[0].name}",
                        "zone": True,
                    })
            else:
                # No zones defined — keep country code
                candidates.append({**cm, "zone": False})

        # 3. Check node network for zone-level availability
        network_data = self.tools.node_network()
        if "error" not in network_data:
            nodes_by_zone = network_data.get("nodes_by_zone", {})
            # Boost confidence for zones with active nodes
            for c in candidates:
                if c["market"] in nodes_by_zone:
                    c["confidence"] = min(1.0, c["confidence"] + 0.2)
                    c["reason"] += "_node_available"

        # Deduplicate by market code
        seen = set()
        unique = []
        for c in candidates:
            if c["market"] not in seen:
                seen.add(c["market"])
                unique.append(c)

        # Sort and limit
        min_conf = AGENT_CONFIG["min_market_confidence"]
        unique = [c for c in unique if c["confidence"] >= min_conf]
        unique.sort(key=lambda x: x["confidence"], reverse=True)
        return unique[:max_zones]

    def select_markets_for_product(self, query: str,
                                    product_category: str = "general",
                                    max_markets: int = None) -> List[Dict[str, Any]]:
        """
        Select markets for product/service searches.
        Different logic — uses proxy usage patterns and market pricing data.
        """
        if max_markets is None:
            max_markets = AGENT_CONFIG["max_markets_per_search"]

        candidates = []

        # Check which markets have active proxy usage (demand signal)
        proxy_data = self.tools.proxy_usage(days_back=7)
        if "error" not in proxy_data:
            for country_data in proxy_data.get("top_countries", []):
                mkt = country_data.get("country", "")
                sessions = country_data.get("sessions", 0)
                if mkt:
                    candidates.append({
                        "market": mkt,
                        "confidence": min(1.0, sessions / 100.0),
                        "reason": f"active_proxy_usage_{sessions}_sessions"
                    })

        # Add priority markets for product arbitrage
        # Lower-income markets tend to have lower product prices
        product_priority = ["IN", "BR", "MX", "TR", "PL", "VN", "TH", "PH", "ID", "EG"]
        for mkt in product_priority:
            if not any(c["market"] == mkt for c in candidates):
                candidates.append({
                    "market": mkt,
                    "confidence": 0.4,
                    "reason": "product_arbitrage_priority"
                })

        # Always include US/GB/JP as reference
        for mkt in ["US", "GB", "JP"]:
            if not any(c["market"] == mkt for c in candidates):
                candidates.append({
                    "market": mkt,
                    "confidence": 0.8,
                    "reason": "reference_market"
                })

        candidates.sort(key=lambda x: x["confidence"], reverse=True)
        return candidates[:max_markets]


# ============================================================
# PhoenixAI Agent — the brain
# ============================================================

class PhoenixAgent:
    """
    The autonomous intelligence layer of Phoenix.

    Capabilities:
    - handle_search(): End-to-end search orchestration
    - discover_opportunities(): Find new arbitrage patterns
    - analyze_route(): Deep route analysis with recommendations
    - select_markets(): Intelligent market selection
    - get_agent_status(): Current capabilities and coverage
    """

    def __init__(self):
        self.tools = AgentTools()
        self.market_selector = MarketSelector(self.tools)
        self._executor = ThreadPoolExecutor(max_workers=AGENT_CONFIG["max_concurrent_tasks"])
        self._discovery_cache = {}
        self._last_discovery = None

    # ----------------------------------------------------------
    # Core: End-to-end search orchestration
    # ----------------------------------------------------------

    def handle_search(self, query: str, user_id: int = None,
                      task_type: str = "flight_search",
                      user_market: str = "US",
                      params: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Agent-orchestrated search. PhoenixAI decides:
        1. Which task type to use
        2. Which markets to search
        3. How to dispatch to CitizenSERP nodes
        4. How to aggregate and rank results
        5. What AI analysis to provide

        Returns comprehensive result with prices, analysis, and recommendations.
        """
        start_time = time.time()
        if params is None:
            params = {}

        # Step 1: Parse the query to understand intent
        intent = self._parse_query_intent(query, task_type)

        # Route universal search to its own orchestrator
        if intent["task_type"] == "universal_search":
            return self.universal_search(query, user_id, user_market, params)

        # Step 2: Select markets based on intelligence
        if intent.get("origin") and intent.get("destination"):
            markets = self.market_selector.select_markets(
                origin=intent["origin"],
                destination=intent["destination"],
                task_type=intent["task_type"],
                user_market=user_market,
            )
        else:
            markets = self.market_selector.select_markets_for_product(
                query=query,
                product_category=intent.get("category", "general"),
            )

        # Step 3: Dispatch tasks to CitizenSERP nodes
        from citizenserp_tasks import task_dispatcher, task_registry

        task_params = {**params, **intent.get("params", {})}
        market_codes = [m["market"] for m in markets]

        dispatch_result = task_dispatcher.dispatch_multi_market(
            task_type=intent["task_type"],
            params=task_params,
            markets=market_codes,
            requester_user_id=user_id,
            requester_type="agent",
        )

        # Step 4: Gather intelligence context
        context = self._gather_context(intent)

        # Step 5: Build response
        elapsed_ms = int((time.time() - start_time) * 1000)

        return {
            "agent_search": True,
            "query": query,
            "intent": intent,
            "markets_selected": markets,
            "dispatch": dispatch_result,
            "context": context,
            "recommendations": self._generate_recommendations(intent, markets, context),
            "elapsed_ms": elapsed_ms,
            "timestamp": datetime.utcnow().isoformat(),
        }

    def _parse_query_intent(self, query: str, default_type: str = "flight_search") -> Dict[str, Any]:
        """
        Parse a natural language query to determine intent.
        Extracts: task_type, origin, destination, dates, category.
        """
        query_lower = query.lower()
        intent = {
            "task_type": default_type,
            "query": query,
            "params": {},
        }

        # Detect task type from query keywords — check new verticals FIRST
        if any(w in query_lower for w in ["cruise", "cruises", "sailing", "carnival", "royal caribbean", "cruise line"]):
            intent["task_type"] = "cruise_search"
        elif any(w in query_lower for w in ["software", "license", "subscription", "steam", "digital", "download",
                                             "app store", "game key", "activation", "serial key"]):
            intent["task_type"] = "digital_search"
        elif any(w in query_lower for w in ["buy", "shop", "order", "amazon", "ebay", "fashion", "electronics",
                                             "clothing", "furniture", "appliance", "sneakers"]):
            intent["task_type"] = "ecommerce_search"
        elif any(w in query_lower for w in ["compare everything", "find best", "search everything",
                                             "cheapest overall", "universal search", "search all"]):
            intent["task_type"] = "universal_search"
        elif any(w in query_lower for w in ["flight", "fly", "airline", "airport"]):
            intent["task_type"] = "flight_search"
        elif any(w in query_lower for w in ["hotel", "stay", "accommodation", "hostel", "airbnb"]):
            intent["task_type"] = "hotel_search"
        elif any(w in query_lower for w in ["price", "product", "compare price"]):
            intent["task_type"] = "product_search"
        elif any(w in query_lower for w in ["marketplace", "facebook", "craigslist", "listing"]):
            intent["task_type"] = "marketplace_browse"
        elif any(w in query_lower for w in ["monitor", "alert", "track", "watch"]):
            intent["task_type"] = "price_monitor"

        # Extract airport codes (3 uppercase letters)
        import re
        airport_pattern = r'\b([A-Z]{3})\b'
        airports = re.findall(airport_pattern, query)
        if len(airports) >= 2:
            intent["origin"] = airports[0]
            intent["destination"] = airports[1]
            intent["params"]["origin"] = airports[0]
            intent["params"]["destination"] = airports[1]

        # Try city-to-airport mapping
        if "origin" not in intent:
            try:
                from phoenix_intelligence import PhoenixIntelligence
                city_map = PhoenixIntelligence.CITY_AIRPORT_MAP
                for city, code in city_map.items():
                    if city in query_lower:
                        if "origin" not in intent:
                            intent["origin"] = code
                            intent["params"]["origin"] = code
                        elif "destination" not in intent:
                            intent["destination"] = code
                            intent["params"]["destination"] = code
            except (ImportError, AttributeError):
                pass

        # Extract dates (basic patterns)
        date_patterns = [
            r'(\d{4}-\d{2}-\d{2})',                    # 2026-03-15
            r'((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d{1,2})',  # March 15
        ]
        for pattern in date_patterns:
            dates = re.findall(pattern, query_lower)
            if dates:
                intent["params"]["date"] = dates[0]
                if len(dates) > 1:
                    intent["params"]["return_date"] = dates[1]
                break

        # Extract product query (everything that's not an airport/date)
        if intent["task_type"] in ("product_search", "marketplace_browse",
                                    "ecommerce_search", "digital_search",
                                    "cruise_search", "universal_search"):
            intent["params"]["query"] = query

        return intent

    def _gather_context(self, intent: Dict[str, Any]) -> Dict[str, Any]:
        """Gather intelligence context relevant to the search intent."""
        context = {}

        try:
            origin = intent.get("origin")
            dest = intent.get("destination")

            if origin and dest:
                # Route-specific intelligence
                context["route"] = self.tools.route_intelligence(origin, dest)
                context["price_history"] = self.tools.price_timeline(origin, dest, days=14)
                context["airlines"] = self.tools.airline_comparison(origin, dest)

            # Platform-wide context
            context["platform"] = self.tools.platform_stats()
            context["node_network"] = self.tools.node_network()

        except Exception as e:
            logger.error(f"Error gathering context: {e}")
            context["error"] = str(e)

        return context

    def _generate_recommendations(self, intent: Dict[str, Any],
                                    markets: List[Dict[str, Any]],
                                    context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate agent recommendations based on gathered data."""
        recommendations = []

        # Market recommendation
        if markets:
            best_market = markets[0]
            recommendations.append({
                "type": "market",
                "priority": "high",
                "message": f"Search {best_market['market']} first — {best_market['reason']}",
                "confidence": best_market["confidence"],
            })

        # Route intelligence
        route_data = context.get("route", {})
        if route_data and "error" not in route_data:
            savings = route_data.get("max_savings_pct", 0)
            if savings > 10:
                recommendations.append({
                    "type": "savings",
                    "priority": "high",
                    "message": f"Historical savings up to {savings:.0f}% on this route",
                    "confidence": 0.8,
                })

        # Price trend
        history = context.get("price_history", {})
        if history and "error" not in history:
            trend = history.get("trend", "stable")
            if trend == "falling":
                recommendations.append({
                    "type": "timing",
                    "priority": "medium",
                    "message": "Prices trending downward — consider waiting",
                    "confidence": 0.6,
                })
            elif trend == "rising":
                recommendations.append({
                    "type": "timing",
                    "priority": "high",
                    "message": "Prices trending upward — book soon",
                    "confidence": 0.7,
                })

        # Node availability
        node_data = context.get("node_network", {})
        if node_data and "error" not in node_data:
            nodes_online = node_data.get("nodes_online", 0)
            if nodes_online == 0:
                recommendations.append({
                    "type": "coverage",
                    "priority": "low",
                    "message": "No CitizenSERP nodes online — using proxy fallback",
                    "confidence": 1.0,
                })
            elif nodes_online < 5:
                recommendations.append({
                    "type": "coverage",
                    "priority": "medium",
                    "message": f"Limited node coverage ({nodes_online} online) — results may be partial",
                    "confidence": 0.9,
                })

        return recommendations

    # ----------------------------------------------------------
    # Discovery: Find new arbitrage opportunities
    # ----------------------------------------------------------

    def discover_opportunities(self, force: bool = False) -> Dict[str, Any]:
        """
        Autonomous opportunity discovery.
        PhoenixAI reads its own telemetry and finds new patterns.

        Runs on schedule (every N hours) or on-demand.
        """
        now = datetime.utcnow()
        interval = timedelta(hours=AGENT_CONFIG["discovery_interval_hours"])

        if not force and self._last_discovery and (now - self._last_discovery) < interval:
            return {
                "cached": True,
                "last_run": self._last_discovery.isoformat(),
                "opportunities": self._discovery_cache.get("opportunities", []),
            }

        logger.info("PhoenixAI: Starting opportunity discovery...")
        opportunities = []

        # 1. High-demand routes with no recent searches
        try:
            alert_data = self.tools.alert_demand(limit=30)
            if "error" not in alert_data:
                watched_routes = alert_data.get("watched_routes", [])
                for route in watched_routes:
                    if route.get("alert_count", 0) >= 3:
                        opportunities.append({
                            "type": "high_demand_route",
                            "origin": route.get("origin"),
                            "destination": route.get("dest"),
                            "demand_signal": route.get("alert_count"),
                            "avg_price_threshold": route.get("avg_price_threshold"),
                            "action": "dispatch_price_monitor",
                            "priority": "high",
                        })
        except Exception as e:
            logger.error(f"Discovery error (alerts): {e}")

        # 2. Top P2P savings routes — replicate for more users
        try:
            savings_data = self.tools.p2p_savings(days=30)
            if "error" not in savings_data:
                top_routes = savings_data.get("top_routes", [])
                for route in top_routes:
                    if route.get("avg_savings_pct", 0) > AGENT_CONFIG["min_savings_threshold_pct"]:
                        opportunities.append({
                            "type": "proven_savings_route",
                            "origin": route.get("origin"),
                            "destination": route.get("dest"),
                            "market": route.get("market"),
                            "avg_savings_pct": route.get("avg_savings_pct"),
                            "transaction_count": route.get("transaction_count"),
                            "action": "promote_route",
                            "priority": "medium",
                        })
        except Exception as e:
            logger.error(f"Discovery error (savings): {e}")

        # 3. Markets with nodes but low search volume — underutilized
        try:
            node_data = self.tools.node_network()
            platform_data = self.tools.platform_stats()
            if "error" not in node_data and "error" not in platform_data:
                nodes_by_country = node_data.get("nodes_by_country", {})
                for country, count in nodes_by_country.items():
                    if count >= 2:  # Has nodes
                        opportunities.append({
                            "type": "underutilized_market",
                            "market": country,
                            "node_count": count,
                            "action": "explore_market",
                            "priority": "low",
                        })
        except Exception as e:
            logger.error(f"Discovery error (markets): {e}")

        # 4. Proxy usage patterns — sites with heavy usage but no structured extraction
        try:
            proxy_data = self.tools.proxy_usage(days_back=7)
            if "error" not in proxy_data:
                top_sites = proxy_data.get("top_sites", [])
                known_verticals = {"google.com/travel", "booking.com", "expedia.com", "amazon.com"}
                for site_data in top_sites:
                    site = site_data.get("site", "")
                    sessions = site_data.get("sessions", 0)
                    if sessions > 10 and not any(kv in site for kv in known_verticals):
                        opportunities.append({
                            "type": "new_vertical_signal",
                            "site": site,
                            "sessions": sessions,
                            "action": "create_task_type",
                            "priority": "medium",
                        })
        except Exception as e:
            logger.error(f"Discovery error (proxy): {e}")

        # 5. Intra-country arbitrage — zones within the same country showing price variance
        try:
            from geographic_zones import get_zones_for_country, get_all_countries
            node_data = self.tools.node_network()
            if "error" not in node_data:
                nodes_by_zone = node_data.get("nodes_by_zone", {})
                for country in get_all_countries():
                    zones = get_zones_for_country(country)
                    zones_with_nodes = [z for z in zones if z.zone_code in nodes_by_zone]
                    if len(zones_with_nodes) >= 2:
                        opportunities.append({
                            "type": "intra_country_arbitrage",
                            "country": country,
                            "zones_covered": [z.zone_code for z in zones_with_nodes],
                            "zone_count": len(zones_with_nodes),
                            "action": "compare_intra_country_prices",
                            "priority": "high",
                        })
        except (ImportError, Exception) as e:
            logger.error(f"Discovery error (intra-country): {e}")

        # 6. Cruise demand — travel searches mentioning cruise lines or ports
        try:
            proxy_data = self.tools.proxy_usage(days_back=7)
            if "error" not in proxy_data:
                cruise_sites = ["carnival.com", "royalcaribbean.com", "ncl.com",
                                "msccruises.com", "princess.com", "hollandamerica.com"]
                for site_data in proxy_data.get("top_sites", []):
                    site = site_data.get("site", "")
                    sessions = site_data.get("sessions", 0)
                    if sessions > 5 and any(cs in site for cs in cruise_sites):
                        opportunities.append({
                            "type": "cruise_demand_signal",
                            "site": site,
                            "sessions": sessions,
                            "action": "dispatch_cruise_search",
                            "priority": "medium",
                        })
        except Exception as e:
            logger.error(f"Discovery error (cruise demand): {e}")

        # 7. Digital goods demand — searches for software, game keys, subscriptions
        try:
            proxy_data = self.tools.proxy_usage(days_back=7)
            if "error" not in proxy_data:
                digital_sites = ["store.steampowered.com", "cdkeys.com", "g2a.com",
                                 "humblebundle.com", "greenmangaming.com", "gog.com"]
                for site_data in proxy_data.get("top_sites", []):
                    site = site_data.get("site", "")
                    sessions = site_data.get("sessions", 0)
                    if sessions > 5 and any(ds in site for ds in digital_sites):
                        opportunities.append({
                            "type": "digital_demand_signal",
                            "site": site,
                            "sessions": sessions,
                            "action": "dispatch_digital_search",
                            "priority": "medium",
                        })
        except Exception as e:
            logger.error(f"Discovery error (digital demand): {e}")

        # Cache results
        self._discovery_cache = {
            "opportunities": opportunities,
            "discovered_at": now.isoformat(),
            "total": len(opportunities),
            "by_type": {},
        }
        for opp in opportunities:
            t = opp["type"]
            self._discovery_cache["by_type"][t] = self._discovery_cache["by_type"].get(t, 0) + 1

        self._last_discovery = now

        logger.info(f"PhoenixAI: Discovered {len(opportunities)} opportunities")

        return {
            "cached": False,
            "discovered_at": now.isoformat(),
            "opportunities": opportunities,
            "total": len(opportunities),
            "by_type": self._discovery_cache["by_type"],
        }

    # ----------------------------------------------------------
    # Route Analysis
    # ----------------------------------------------------------

    def analyze_route(self, origin: str, destination: str,
                      user_market: str = "US") -> Dict[str, Any]:
        """
        Deep analysis of a route. Combines all intelligence tools.
        """
        start_time = time.time()

        # Gather all data in parallel
        futures = {}
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures["route"] = executor.submit(self.tools.route_intelligence, origin, destination)
            futures["history"] = executor.submit(self.tools.price_timeline, origin, destination, 30)
            futures["airlines"] = executor.submit(self.tools.airline_comparison, origin, destination)
            futures["p2p"] = executor.submit(self.tools.p2p_savings, 30)
            futures["alerts"] = executor.submit(self.tools.alert_demand, 30)
            futures["nodes"] = executor.submit(self.tools.node_network)

        data = {}
        for key, future in futures.items():
            try:
                data[key] = future.result(timeout=10)
            except Exception as e:
                data[key] = {"error": str(e)}

        # Select best markets for this route
        markets = self.market_selector.select_markets(
            origin=origin, destination=destination,
            task_type="flight_search", user_market=user_market,
        )

        # Build analysis
        analysis = {
            "route": f"{origin} → {destination}",
            "markets_recommended": markets,
            "intelligence": data["route"] if "error" not in data.get("route", {}) else None,
            "price_history": data["history"] if "error" not in data.get("history", {}) else None,
            "airline_comparison": data["airlines"] if "error" not in data.get("airlines", {}) else None,
            "recommendations": self._generate_recommendations(
                {"origin": origin, "destination": destination, "task_type": "flight_search"},
                markets,
                data,
            ),
            "coverage": {
                "nodes_online": data.get("nodes", {}).get("nodes_online", 0),
                "markets_with_nodes": len(data.get("nodes", {}).get("nodes_by_country", {})),
            },
            "elapsed_ms": int((time.time() - start_time) * 1000),
            "timestamp": datetime.utcnow().isoformat(),
        }

        return analysis

    # ----------------------------------------------------------
    # Agent Status
    # ----------------------------------------------------------

    def get_agent_status(self) -> Dict[str, Any]:
        """Get current agent capabilities and operational status."""
        from citizenserp_tasks import task_dispatcher, task_registry

        # Tool availability check
        tools_status = {}
        tool_checks = {
            "intelligence": lambda: self.tools.intelligence is not None,
            "tracker": lambda: self.tools.tracker is not None,
        }
        for name, check in tool_checks.items():
            try:
                tools_status[name] = "available" if check() else "unavailable"
            except Exception:
                tools_status[name] = "error"

        return {
            "agent": "PhoenixAI",
            "version": "1.0.0",
            "status": "active",
            "capabilities": [
                "flight_search", "hotel_search", "product_search",
                "marketplace_browse", "price_monitor", "general_search",
                "cruise_search", "ecommerce_search", "digital_search",
                "universal_search", "search_engine_extract",
                "opportunity_discovery", "route_analysis", "market_selection",
            ],
            "task_types": task_registry.list_types(),
            "dispatcher_stats": task_dispatcher.get_stats(),
            "tools": tools_status,
            "config": {
                "max_markets_per_search": AGENT_CONFIG["max_markets_per_search"],
                "max_concurrent_tasks": AGENT_CONFIG["max_concurrent_tasks"],
                "discovery_interval_hours": AGENT_CONFIG["discovery_interval_hours"],
            },
            "last_discovery": self._last_discovery.isoformat() if self._last_discovery else None,
            "timestamp": datetime.utcnow().isoformat(),
        }

    # ----------------------------------------------------------
    # Multi-vertical search
    # ----------------------------------------------------------

    def search_flights(self, origin: str, destination: str, date: str,
                       user_id: int = None, user_market: str = "US") -> Dict[str, Any]:
        """Agent-orchestrated flight search across markets."""
        return self.handle_search(
            query=f"flights from {origin} to {destination} on {date}",
            user_id=user_id,
            task_type="flight_search",
            user_market=user_market,
            params={
                "origin": origin,
                "destination": destination,
                "date": date,
            },
        )

    def search_product(self, query: str, user_id: int = None,
                       user_market: str = "US") -> Dict[str, Any]:
        """Agent-orchestrated product price comparison across markets."""
        return self.handle_search(
            query=query,
            user_id=user_id,
            task_type="product_search",
            user_market=user_market,
            params={"query": query},
        )

    def search_hotel(self, destination: str, checkin: str, checkout: str,
                     user_id: int = None, user_market: str = "US") -> Dict[str, Any]:
        """Agent-orchestrated hotel search across markets."""
        return self.handle_search(
            query=f"hotels in {destination}",
            user_id=user_id,
            task_type="hotel_search",
            user_market=user_market,
            params={
                "destination": destination,
                "checkin": checkin,
                "checkout": checkout,
            },
        )

    def browse_marketplace(self, marketplace_url: str, query: str,
                            market: str, user_id: int = None) -> Dict[str, Any]:
        """Agent-orchestrated marketplace browsing via proxy."""
        return self.handle_search(
            query=f"marketplace {query}",
            user_id=user_id,
            task_type="marketplace_browse",
            user_market=market,
            params={
                "marketplace_url": marketplace_url,
                "query": query,
            },
        )

    def search_cruise(self, query: str, user_id: int = None,
                      user_market: str = "US") -> Dict[str, Any]:
        """Agent-orchestrated cruise search across markets."""
        return self.handle_search(
            query=query,
            user_id=user_id,
            task_type="cruise_search",
            user_market=user_market,
            params={"query": query},
        )

    def search_ecommerce(self, query: str, user_id: int = None,
                         user_market: str = "US",
                         destination_country: str = "US") -> Dict[str, Any]:
        """Agent-orchestrated e-commerce search with landed cost comparison."""
        return self.handle_search(
            query=query,
            user_id=user_id,
            task_type="ecommerce_search",
            user_market=user_market,
            params={"query": query, "destination_country": destination_country},
        )

    def search_digital(self, query: str, user_id: int = None,
                       user_market: str = "US") -> Dict[str, Any]:
        """Agent-orchestrated digital goods / software search."""
        return self.handle_search(
            query=query,
            user_id=user_id,
            task_type="digital_search",
            user_market=user_market,
            params={"query": query},
        )

    # ----------------------------------------------------------
    # Universal Search — smart hybrid orchestrator
    # ----------------------------------------------------------

    # Maps a primary vertical to 1-2 related verticals for cross-search
    VERTICAL_MAP = {
        "flight_search":    ["hotel_search", "cruise_search"],
        "hotel_search":     ["flight_search", "cruise_search"],
        "cruise_search":    ["flight_search", "hotel_search"],
        "product_search":   ["ecommerce_search", "digital_search"],
        "ecommerce_search": ["product_search", "digital_search"],
        "digital_search":   ["ecommerce_search", "product_search"],
    }

    def universal_search(self, query: str, user_id: int = None,
                         user_market: str = "US",
                         params: dict = None) -> Dict[str, Any]:
        """
        Smart hybrid universal search.

        Auto-detects the primary vertical from the query, then dispatches
        that vertical plus 1-2 related verticals concurrently. Merges results
        and surfaces the best opportunities across all verticals.
        """
        start_time = time.time()
        if params is None:
            params = {}

        # Detect primary vertical (re-parse but exclude "universal_search" result)
        query_lower = query.lower()
        primary = "ecommerce_search"  # default fallback

        if any(w in query_lower for w in ["flight", "fly", "airline", "airport", "trip to"]):
            primary = "flight_search"
        elif any(w in query_lower for w in ["hotel", "stay", "accommodation"]):
            primary = "hotel_search"
        elif any(w in query_lower for w in ["cruise", "cruises", "sailing"]):
            primary = "cruise_search"
        elif any(w in query_lower for w in ["software", "license", "steam", "digital", "game key"]):
            primary = "digital_search"
        elif any(w in query_lower for w in ["buy", "shop", "order", "amazon", "ebay"]):
            primary = "ecommerce_search"
        elif any(w in query_lower for w in ["product", "compare price"]):
            primary = "product_search"

        # Get related verticals
        related = self.VERTICAL_MAP.get(primary, [])[:2]
        all_verticals = [primary] + related

        logger.info(f"Universal search: primary={primary}, related={related}")

        # Dispatch all verticals concurrently
        results_by_vertical = {}
        with ThreadPoolExecutor(max_workers=len(all_verticals)) as executor:
            futures = {}
            for vertical in all_verticals:
                futures[vertical] = executor.submit(
                    self.handle_search,
                    query=query,
                    user_id=user_id,
                    task_type=vertical,
                    user_market=user_market,
                    params=params,
                )

            for vertical, future in futures.items():
                try:
                    results_by_vertical[vertical] = future.result(
                        timeout=AGENT_CONFIG["task_timeout_seconds"] + 10
                    )
                except Exception as e:
                    logger.error(f"Universal search vertical {vertical} error: {e}")
                    results_by_vertical[vertical] = {"error": str(e)}

        # Extract best opportunities across all verticals
        best_opportunities = []
        for vertical, result in results_by_vertical.items():
            if "error" in result:
                continue
            dispatch = result.get("dispatch", {})
            if isinstance(dispatch, dict):
                opp = {
                    "vertical": vertical,
                    "markets_searched": len(result.get("markets_selected", [])),
                    "query": query,
                }
                best_opportunities.append(opp)

        elapsed_ms = int((time.time() - start_time) * 1000)

        return {
            "agent_search": True,
            "universal_search": True,
            "query": query,
            "primary_vertical": primary,
            "secondary_verticals": related,
            "results_by_vertical": results_by_vertical,
            "best_opportunities": best_opportunities,
            "verticals_dispatched": len(all_verticals),
            "elapsed_ms": elapsed_ms,
            "timestamp": datetime.utcnow().isoformat(),
        }


# ============================================================
# Module-level singleton
# ============================================================

phoenix_agent = PhoenixAgent()
