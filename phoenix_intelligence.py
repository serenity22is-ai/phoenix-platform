"""
PHOENIX Intelligence Engine

Connects Phoenix's proprietary market data to AI search and commercial APIs.
Transforms the AI from a generic LLM wrapper into a data-powered intelligence
system with access to real pricing, demand signals, and arbitrage opportunities.

Data Sources:
    SearchHistory — user search patterns, best prices, savings
    PriceHistory  — per-market price snapshots with airline granularity
    Deal          — arbitrage opportunities with home vs foreign pricing
    AncillarySnapshot — bag fees, seat prices by airline/market
    AISearchQuery — past AI queries, provider performance

Usage:
    from phoenix_intelligence import intelligence

    # Build context for AI system prompts
    context = intelligence.build_ai_context("cheapest flights to Tokyo March", market="JP")

    # Route intelligence
    profile = intelligence.get_route_intelligence("JFK", "NRT")

    # Market briefing
    briefing = intelligence.get_market_briefing("JP")
"""

import json
import logging
import re
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


# Common city names → preferred airport codes (for query parsing)
CITY_AIRPORT_MAP = {
    "new york": "JFK", "nyc": "JFK", "manhattan": "JFK",
    "los angeles": "LAX", "la": "LAX",
    "san francisco": "SFO", "sf": "SFO",
    "chicago": "ORD",
    "miami": "MIA",
    "dallas": "DFW",
    "atlanta": "ATL",
    "seattle": "SEA",
    "boston": "BOS",
    "denver": "DEN",
    "houston": "IAH",
    "london": "LHR",
    "paris": "CDG",
    "tokyo": "NRT", "narita": "NRT", "haneda": "HND",
    "osaka": "KIX",
    "seoul": "ICN",
    "beijing": "PEK",
    "shanghai": "PVG",
    "hong kong": "HKG",
    "singapore": "SIN",
    "bangkok": "BKK",
    "dubai": "DXB",
    "istanbul": "IST",
    "berlin": "BER",
    "frankfurt": "FRA",
    "munich": "MUC",
    "amsterdam": "AMS",
    "rome": "FCO",
    "milan": "MXP",
    "madrid": "MAD",
    "barcelona": "BCN",
    "lisbon": "LIS",
    "sydney": "SYD",
    "melbourne": "MEL",
    "toronto": "YYZ",
    "vancouver": "YVR",
    "mexico city": "MEX",
    "sao paulo": "GRU",
    "buenos aires": "EZE",
    "cairo": "CAI",
    "johannesburg": "JNB",
    "mumbai": "BOM",
    "delhi": "DEL",
    "nairobi": "NBO",
    "honolulu": "HNL", "hawaii": "HNL",
    "cancun": "CUN",
}


class PhoenixIntelligence:
    """
    Intelligence layer bridging Phoenix data to AI and commercial APIs.
    Every method uses lazy imports and try/except for resilience.
    """

    # ─────────────────────────────────────────────────────────
    # CORE: AI Context Builder
    # ─────────────────────────────────────────────────────────

    def build_ai_context(self, query, market=None):
        """
        Build rich context string from Phoenix data for AI system prompts.

        This is the main entry point — called by ai_search.py to inject
        Phoenix intelligence into every LLM query.

        Returns:
            Formatted context string with relevant market intelligence,
            or a minimal fallback if no data is available.
        """
        parts = []

        # 1. Parse query for airport codes and dates
        flight_ctx = self.get_flight_context(query)

        # 2. If route detected, add route intelligence
        origin = flight_ctx.get("origin")
        dest = flight_ctx.get("destination")
        if origin and dest:
            route_intel = self.get_route_intelligence(origin, dest)
            if route_intel and not route_intel.get("error"):
                parts.append(self._format_route_context(route_intel))

        # 3. Market briefing (if market specified or inferred from destination)
        target_market = market
        if not target_market and dest:
            target_market = self._airport_to_market(dest)
        if target_market:
            brief = self.get_market_briefing(target_market, days_back=7)
            if brief and not brief.get("error") and brief.get("total_searches", 0) > 0:
                parts.append(self._format_market_context(brief))

        # 4. Trending snapshot
        trending = self._get_trending_snapshot(days=3, limit=3)
        if trending and trending.get("popular_routes"):
            parts.append(self._format_trending_context(trending))

        # 5. Platform stats (one-liner)
        stats = self.get_platform_stats()
        if stats and stats.get("total_searches", 0) > 0:
            parts.append(
                f"Phoenix platform: {stats['total_searches']:,} searches tracked, "
                f"{stats.get('routes_tracked', 0)} routes, "
                f"{stats.get('markets_active', 0)} markets, "
                f"${stats.get('total_savings_generated_usd', 0):,.0f} total savings identified."
            )

        if parts:
            return "PHOENIX MARKET INTELLIGENCE (proprietary data):\n\n" + "\n\n".join(parts)

        # Fallback — still provide geographic context from portal
        return self._fallback_market_context(market)

    # ─────────────────────────────────────────────────────────
    # Query Parser
    # ─────────────────────────────────────────────────────────

    def get_flight_context(self, query):
        """
        Parse natural language query for flight-related entities.

        Extracts airport codes (JFK, LAX) and city names (Tokyo → NRT).
        Returns dict with origin, destination, departure_month, query_type.
        """
        result = {"query_type": None, "origin": None, "destination": None}
        query_upper = query.upper().strip()
        query_lower = query.lower()

        # 1. Extract explicit 3-letter airport codes
        codes = re.findall(r'\b([A-Z]{3})\b', query_upper)
        # Filter to known airports only
        known_codes = []
        try:
            from airports import AIRPORTS
            known_codes = [c for c in codes if c in AIRPORTS]
        except ImportError:
            known_codes = codes[:2]

        if len(known_codes) >= 2:
            result["origin"] = known_codes[0]
            result["destination"] = known_codes[1]
            result["query_type"] = "flight_search"
        elif len(known_codes) == 1:
            result["destination"] = known_codes[0]
            result["query_type"] = "flight_search"

        # 2. If no codes found, try city name matching
        if not result["destination"]:
            # Check for "to <city>" or "from <city>" patterns
            to_match = re.search(r'\bto\s+([a-z\s]+?)(?:\s+in\s+|\s+on\s+|\s+for\s+|\s*$)', query_lower)
            from_match = re.search(r'\bfrom\s+([a-z\s]+?)(?:\s+to\s+|\s+in\s+|\s+on\s+|\s*$)', query_lower)

            if from_match:
                city = from_match.group(1).strip()
                code = CITY_AIRPORT_MAP.get(city)
                if code:
                    result["origin"] = code

            if to_match:
                city = to_match.group(1).strip()
                code = CITY_AIRPORT_MAP.get(city)
                if code:
                    result["destination"] = code
                    result["query_type"] = "flight_search"

            # Fallback: check if any city name appears in query
            if not result["destination"]:
                for city, code in CITY_AIRPORT_MAP.items():
                    if city in query_lower and len(city) > 2:
                        if not result["destination"]:
                            result["destination"] = code
                            result["query_type"] = "flight_search"
                        elif not result["origin"] and code != result["destination"]:
                            result["origin"] = code

        # 3. Extract month/date references
        months = {
            "january": 1, "february": 2, "march": 3, "april": 4,
            "may": 5, "june": 6, "july": 7, "august": 8,
            "september": 9, "october": 10, "november": 11, "december": 12,
            "jan": 1, "feb": 2, "mar": 3, "apr": 4,
            "jun": 6, "jul": 7, "aug": 8, "sep": 9,
            "oct": 10, "nov": 11, "dec": 12,
        }
        for month_name, month_num in months.items():
            if month_name in query_lower:
                year = datetime.now().year
                if month_num < datetime.now().month:
                    year += 1
                result["departure_month"] = f"{year}-{month_num:02d}"
                break

        return result

    # ─────────────────────────────────────────────────────────
    # Route Intelligence
    # ─────────────────────────────────────────────────────────

    def get_route_intelligence(self, origin, destination, days_back=30):
        """
        Complete intelligence profile for a route.

        Returns:
            {
                origin, destination, days_analyzed,
                markets: [{market, avg_price_usd, min_price_usd, max_price_usd, samples}],
                price_spread_usd, best_booking_market,
                price_trend_direction: "rising"|"falling"|"stable",
                demand_level: {level, searches_last_7d},
                recent_deals: [{deal_id, arbitrage_market, price, savings_pct}]
            }
        """
        try:
            from search_tracker import tracker
            from models import Deal

            origin = origin.upper()
            destination = destination.upper()

            # 1. Multi-market pricing
            route_stats = tracker.get_route_stats(origin, destination, days=days_back)
            markets_list = []
            if route_stats and route_stats.get("markets"):
                for mkt, stats in route_stats["markets"].items():
                    markets_list.append({
                        "market": mkt,
                        "avg_price_usd": round(stats["avg_price"], 2),
                        "min_price_usd": round(stats["min_price"], 2),
                        "max_price_usd": round(stats["max_price"], 2),
                        "samples": stats["samples"],
                    })
                markets_list.sort(key=lambda m: m["avg_price_usd"])

            if not markets_list:
                return {"error": "No pricing data for this route", "origin": origin, "destination": destination}

            cheapest = markets_list[0]
            most_expensive = markets_list[-1]
            spread = round(most_expensive["avg_price_usd"] - cheapest["avg_price_usd"], 2)

            # 2. Price trend
            trend = self._calculate_price_trend(origin, destination, days_back)

            # 3. Demand
            demand = self._calculate_demand_level(origin, destination)

            # 4. Recent deals
            cutoff = datetime.utcnow() - timedelta(days=days_back)
            deals = Deal.query.filter(
                Deal.origin == origin,
                Deal.destination == destination,
                Deal.created_at >= cutoff,
                Deal.is_active == True,
            ).order_by(Deal.savings_percent.desc()).limit(5).all()

            deals_list = []
            for d in deals:
                deals_list.append({
                    "deal_id": d.deal_id,
                    "arbitrage_market": d.arbitrage_market,
                    "arbitrage_price_usd": d.arbitrage_price_usd,
                    "home_price_usd": d.home_price_usd,
                    "savings_usd": d.gross_savings_usd,
                    "savings_percent": d.savings_percent,
                    "airline": d.airline,
                    "departure_date": d.departure_date.isoformat() if d.departure_date else None,
                })

            return {
                "origin": origin,
                "destination": destination,
                "days_analyzed": days_back,
                "markets": markets_list,
                "markets_tracked": len(markets_list),
                "cheapest_market": cheapest["market"],
                "most_expensive_market": most_expensive["market"],
                "price_spread_usd": spread,
                "best_booking_market": cheapest["market"],
                "price_trend_direction": trend,
                "demand_level": demand,
                "recent_deals": deals_list,
            }

        except Exception as e:
            logger.error(f"get_route_intelligence failed for {origin}-{destination}: {e}")
            return {"error": str(e)}

    def _calculate_price_trend(self, origin, destination, days_back=30):
        """Compare recent prices vs prior period → rising/falling/stable."""
        try:
            from search_tracker import tracker

            trend_data = tracker.get_price_trend(origin, destination, days=days_back)
            if not trend_data:
                return "unknown"

            all_dates = sorted(trend_data.keys())
            if len(all_dates) < 4:
                return "insufficient_data"

            mid = len(all_dates) // 2
            early_prices = []
            recent_prices = []

            for d in all_dates[:mid]:
                for mkt_data in trend_data[d].values():
                    early_prices.append(mkt_data["avg_price"])

            for d in all_dates[mid:]:
                for mkt_data in trend_data[d].values():
                    recent_prices.append(mkt_data["avg_price"])

            if not early_prices or not recent_prices:
                return "unknown"

            early_avg = sum(early_prices) / len(early_prices)
            recent_avg = sum(recent_prices) / len(recent_prices)
            change_pct = ((recent_avg - early_avg) / early_avg) * 100 if early_avg > 0 else 0

            if change_pct > 5:
                return "rising"
            elif change_pct < -5:
                return "falling"
            return "stable"

        except Exception as e:
            logger.debug(f"_calculate_price_trend failed: {e}")
            return "unknown"

    def _calculate_demand_level(self, origin, destination):
        """Search volume in last 7 days → high/medium/low/none."""
        try:
            from models import SearchHistory

            cutoff = datetime.utcnow() - timedelta(days=7)
            count = SearchHistory.query.filter(
                SearchHistory.origin == origin,
                SearchHistory.destination == destination,
                SearchHistory.created_at >= cutoff,
            ).count()

            if count >= 50:
                level = "high"
            elif count >= 10:
                level = "medium"
            elif count > 0:
                level = "low"
            else:
                level = "none"

            return {"level": level, "searches_last_7d": count}

        except Exception as e:
            logger.debug(f"_calculate_demand_level failed: {e}")
            return {"level": "unknown", "searches_last_7d": 0}

    # ─────────────────────────────────────────────────────────
    # Market Briefing
    # ─────────────────────────────────────────────────────────

    def get_market_briefing(self, market, days_back=7):
        """
        Activity summary for a geographic market.

        Returns:
            {market, popular_routes[], avg_savings_pct, price_movements,
             demand_trend, total_searches}
        """
        try:
            from models import db, SearchHistory, PriceHistory

            market = market.upper()
            cutoff = datetime.utcnow() - timedelta(days=days_back)

            # Popular routes where this market is cheapest
            popular = db.session.query(
                SearchHistory.origin,
                SearchHistory.destination,
                db.func.count(SearchHistory.id).label("searches"),
            ).filter(
                SearchHistory.best_market == market,
                SearchHistory.created_at >= cutoff,
            ).group_by(
                SearchHistory.origin, SearchHistory.destination,
            ).order_by(db.text("searches DESC")).limit(5).all()

            popular_routes = [
                {"route": f"{r.origin}-{r.destination}", "searches": r.searches}
                for r in popular
            ]

            # Average savings
            avg_savings = db.session.query(
                db.func.avg(SearchHistory.max_savings_percent)
            ).filter(
                SearchHistory.best_market == market,
                SearchHistory.created_at >= cutoff,
                SearchHistory.max_savings_percent.isnot(None),
            ).scalar()
            avg_savings_pct = round(avg_savings, 1) if avg_savings else None

            # Total searches
            total = SearchHistory.query.filter(
                SearchHistory.best_market == market,
                SearchHistory.created_at >= cutoff,
            ).count()

            # Price volatility
            price_samples = PriceHistory.query.filter(
                PriceHistory.market == market,
                PriceHistory.recorded_at >= cutoff,
            ).with_entities(PriceHistory.price_usd).limit(500).all()

            price_movements = "insufficient_data"
            if price_samples and len(price_samples) > 10:
                prices = [p.price_usd for p in price_samples if p.price_usd]
                if prices:
                    avg_p = sum(prices) / len(prices)
                    std = (sum((p - avg_p) ** 2 for p in prices) / len(prices)) ** 0.5
                    cv = std / avg_p if avg_p > 0 else 0
                    price_movements = "volatile" if cv > 0.2 else "stable"

            # Demand trend (early vs recent half)
            mid_date = cutoff + timedelta(days=days_back // 2)
            early = SearchHistory.query.filter(
                SearchHistory.best_market == market,
                SearchHistory.created_at >= cutoff,
                SearchHistory.created_at < mid_date,
            ).count()
            recent = SearchHistory.query.filter(
                SearchHistory.best_market == market,
                SearchHistory.created_at >= mid_date,
            ).count()

            if early > 0:
                change = ((recent - early) / early) * 100
                demand_trend = "rising" if change > 20 else ("falling" if change < -20 else "stable")
            else:
                demand_trend = "new_market" if recent > 0 else "no_data"

            return {
                "market": market,
                "days_analyzed": days_back,
                "popular_routes": popular_routes,
                "avg_savings_pct": avg_savings_pct,
                "price_movements": price_movements,
                "demand_trend": demand_trend,
                "total_searches": total,
            }

        except Exception as e:
            logger.error(f"get_market_briefing failed for {market}: {e}")
            return {"error": str(e)}

    # ─────────────────────────────────────────────────────────
    # Platform Stats
    # ─────────────────────────────────────────────────────────

    def get_platform_stats(self):
        """High-level platform-wide statistics."""
        try:
            from models import db, SearchHistory, Deal, PriceHistory

            total_searches = SearchHistory.query.count()

            routes_tracked = db.session.query(
                db.func.count(db.distinct(
                    db.func.concat(SearchHistory.origin, "-", SearchHistory.destination)
                ))
            ).scalar() or 0

            cutoff_30d = datetime.utcnow() - timedelta(days=30)
            markets_active = db.session.query(
                db.func.count(db.distinct(PriceHistory.market))
            ).filter(PriceHistory.recorded_at >= cutoff_30d).scalar() or 0

            total_savings = db.session.query(
                db.func.sum(Deal.gross_savings_usd)
            ).filter(Deal.is_active == True).scalar() or 0.0

            avg_savings = db.session.query(
                db.func.avg(SearchHistory.max_savings_percent)
            ).filter(
                SearchHistory.max_savings_percent.isnot(None),
                SearchHistory.max_savings_percent > 0,
            ).scalar() or 0.0

            active_deals = Deal.query.filter_by(is_active=True).count()

            return {
                "total_searches": total_searches,
                "routes_tracked": routes_tracked,
                "markets_active": markets_active,
                "total_savings_generated_usd": round(total_savings, 2),
                "avg_savings_pct": round(avg_savings, 1),
                "active_deals": active_deals,
            }

        except Exception as e:
            logger.error(f"get_platform_stats failed: {e}")
            return {}

    # ─────────────────────────────────────────────────────────
    # Anomaly Detection
    # ─────────────────────────────────────────────────────────

    def detect_anomalies(self, days=7):
        """
        Detect price anomalies, new deals, and demand surges.

        Returns:
            {new_deals[], demand_surges[]}
        """
        try:
            from models import db, SearchHistory, Deal

            cutoff = datetime.utcnow() - timedelta(days=days)
            anomalies = {"new_deals": [], "demand_surges": []}

            # New high-savings deals
            new_deals = Deal.query.filter(
                Deal.created_at >= cutoff,
                Deal.is_active == True,
                Deal.savings_percent >= 10,
            ).order_by(Deal.savings_percent.desc()).limit(10).all()

            anomalies["new_deals"] = [{
                "route": f"{d.origin}-{d.destination}",
                "market": d.arbitrage_market,
                "savings_pct": d.savings_percent,
                "price_usd": d.arbitrage_price_usd,
                "airline": d.airline,
            } for d in new_deals]

            # Demand surges: compare last 3 days vs prior period
            recent_cutoff = datetime.utcnow() - timedelta(days=3)

            recent_popular = db.session.query(
                SearchHistory.origin,
                SearchHistory.destination,
                db.func.count(SearchHistory.id).label("count"),
            ).filter(
                SearchHistory.created_at >= recent_cutoff,
            ).group_by(
                SearchHistory.origin, SearchHistory.destination,
            ).order_by(db.text("count DESC")).limit(10).all()

            for route in recent_popular:
                prior_count = SearchHistory.query.filter(
                    SearchHistory.origin == route.origin,
                    SearchHistory.destination == route.destination,
                    SearchHistory.created_at >= cutoff,
                    SearchHistory.created_at < recent_cutoff,
                ).count()

                if prior_count > 0:
                    change_pct = ((route.count - prior_count) / prior_count) * 100
                    if change_pct > 50:
                        anomalies["demand_surges"].append({
                            "route": f"{route.origin}-{route.destination}",
                            "recent_searches": route.count,
                            "prior_searches": prior_count,
                            "change_pct": round(change_pct, 1),
                        })

            return anomalies

        except Exception as e:
            logger.error(f"detect_anomalies failed: {e}")
            return {"new_deals": [], "demand_surges": []}

    # ─────────────────────────────────────────────────────────
    # AI Provider Performance
    # ─────────────────────────────────────────────────────────

    def get_provider_performance(self, days_back=30):
        """
        Which AI providers win most often, from AISearchQuery data.

        Returns:
            {providers: {provider_key: {total_queries, best_response_count,
             win_rate, avg_response_time_ms}}}
        """
        try:
            from models import AISearchQuery

            cutoff = datetime.utcnow() - timedelta(days=days_back)
            queries = AISearchQuery.query.filter(
                AISearchQuery.created_at >= cutoff,
            ).all()

            stats = {}
            for q in queries:
                best = q.best_provider
                if not best:
                    continue

                try:
                    providers_queried = json.loads(q.providers_queried) if q.providers_queried else []
                except (json.JSONDecodeError, TypeError):
                    providers_queried = []

                for provider in providers_queried:
                    if provider not in stats:
                        stats[provider] = {
                            "total_queries": 0,
                            "best_response_count": 0,
                            "total_time_ms": 0,
                            "time_samples": 0,
                        }
                    stats[provider]["total_queries"] += 1
                    if provider == best:
                        stats[provider]["best_response_count"] += 1

                    # Extract per-provider timing
                    try:
                        all_resp = json.loads(q.all_responses) if q.all_responses else []
                        for resp in all_resp:
                            if resp.get("provider") == provider and resp.get("time_ms"):
                                stats[provider]["total_time_ms"] += resp["time_ms"]
                                stats[provider]["time_samples"] += 1
                    except (json.JSONDecodeError, TypeError):
                        pass

            result = {}
            for provider, s in stats.items():
                total = s["total_queries"]
                wins = s["best_response_count"]
                avg_time = s["total_time_ms"] / s["time_samples"] if s["time_samples"] > 0 else 0
                result[provider] = {
                    "total_queries": total,
                    "best_response_count": wins,
                    "win_rate": round(wins / total, 3) if total > 0 else 0,
                    "avg_response_time_ms": round(avg_time),
                }

            sorted_result = dict(sorted(result.items(), key=lambda x: x[1]["win_rate"], reverse=True))
            return {"providers": sorted_result}

        except Exception as e:
            logger.error(f"get_provider_performance failed: {e}")
            return {"providers": {}}

    # ─────────────────────────────────────────────────────────
    # Context Formatting Helpers
    # ─────────────────────────────────────────────────────────

    def _format_route_context(self, route_intel):
        """Format route intelligence for AI prompt injection."""
        origin = route_intel.get("origin", "")
        dest = route_intel.get("destination", "")
        lines = [f"Route {origin} → {dest} (last {route_intel.get('days_analyzed', 30)} days):"]

        markets = route_intel.get("markets", [])
        if markets:
            cheapest = markets[0]
            lines.append(
                f"  Cheapest market: {cheapest['market']} — "
                f"${cheapest['avg_price_usd']:.0f} avg, ${cheapest['min_price_usd']:.0f} min "
                f"({cheapest['samples']} data points)"
            )
            if len(markets) > 1:
                expensive = markets[-1]
                lines.append(
                    f"  Most expensive: {expensive['market']} — "
                    f"${expensive['avg_price_usd']:.0f} avg"
                )
                lines.append(
                    f"  Price spread: ${route_intel.get('price_spread_usd', 0):.0f} "
                    f"across {len(markets)} markets"
                )

        demand = route_intel.get("demand_level", {})
        if demand.get("level") and demand["level"] != "unknown":
            lines.append(f"  Demand: {demand['level']} ({demand.get('searches_last_7d', 0)} searches last 7 days)")

        trend = route_intel.get("price_trend_direction")
        if trend and trend not in ("unknown", "insufficient_data"):
            lines.append(f"  Price trend: {trend}")

        deals = route_intel.get("recent_deals", [])
        if deals:
            best = deals[0]
            lines.append(
                f"  Best active deal: {best.get('airline', 'Unknown')} via {best['arbitrage_market']} "
                f"at ${best['arbitrage_price_usd']:.0f} "
                f"({best['savings_percent']:.1f}% savings vs US ${best.get('home_price_usd', 0):.0f})"
            )

        return "\n".join(lines)

    def _format_market_context(self, brief):
        """Format market briefing for AI prompt injection."""
        market = brief.get("market", "")
        lines = [f"Market {market} overview:"]

        popular = brief.get("popular_routes", [])
        if popular:
            route_strs = [f"{r['route']} ({r['searches']} searches)" for r in popular[:3]]
            lines.append(f"  Popular routes: {', '.join(route_strs)}")

        if brief.get("avg_savings_pct"):
            lines.append(f"  Average savings: {brief['avg_savings_pct']:.1f}%")

        if brief.get("demand_trend") and brief["demand_trend"] != "no_data":
            lines.append(f"  Demand trend: {brief['demand_trend']}")

        if brief.get("price_movements") not in (None, "insufficient_data"):
            lines.append(f"  Pricing: {brief['price_movements']}")

        return "\n".join(lines)

    def _format_trending_context(self, trending):
        """Format trending data for AI prompt injection."""
        lines = ["Trending on Phoenix:"]

        popular = trending.get("popular_routes", [])
        if popular:
            lines.append(
                "  Hot routes: " + ", ".join(r["route"] for r in popular)
            )

        deals = trending.get("new_deals", [])
        if deals:
            lines.append(
                f"  {len(deals)} new deals found (up to {deals[0].get('savings_pct', 0):.0f}% savings)"
            )

        return "\n".join(lines)

    def _get_trending_snapshot(self, days=3, limit=5):
        """Quick snapshot of popular routes and new deals."""
        try:
            from search_tracker import tracker

            popular = tracker.get_popular_routes(days=days, limit=limit)
            anomalies = self.detect_anomalies(days=days)

            return {
                "popular_routes": [
                    {"route": f"{r['origin']}-{r['destination']}", "searches": r["search_count"]}
                    for r in popular
                ],
                "new_deals": anomalies.get("new_deals", [])[:3],
            }
        except Exception as e:
            logger.debug(f"_get_trending_snapshot failed: {e}")
            return {}

    def _airport_to_market(self, airport_code):
        """Map airport code to market/country code."""
        try:
            from airports import AIRPORTS
            airport = AIRPORTS.get(airport_code.upper())
            if airport:
                return airport.get("country_code")
        except ImportError:
            pass
        return None

    def _fallback_market_context(self, market):
        """Minimal geographic context when no Phoenix data exists."""
        try:
            from proxy_portal import COUNTRY_INFO, PORTAL_APP_DIRECTORY
            if market and market.upper() in COUNTRY_INFO:
                info = COUNTRY_INFO[market.upper()]
                sites = []
                for cat_data in PORTAL_APP_DIRECTORY.values():
                    for site in cat_data.get("sites", []):
                        if "*" in site.get("regions", []) or market.upper() in site.get("regions", []):
                            sites.append(site["name"])
                return (
                    f"Geographic market: {info['name']} ({market.upper()}). "
                    f"Available platforms: {', '.join(sites[:10])}."
                )
        except ImportError:
            pass
        return ""

    # ─── Phase 2: Extended Intelligence Methods ───────────────────────

    def get_p2p_network(self, days_back=30):
        """P2P network health: helper coverage, transaction funnel, disputes."""
        try:
            from models import db, HelperProfile, P2PTransaction, Dispute
            from datetime import datetime, timedelta
            from sqlalchemy import func

            cutoff = datetime.utcnow() - timedelta(days=days_back)

            # Helper stats
            total_helpers = db.session.query(func.count(HelperProfile.id)).scalar() or 0
            approved_helpers = db.session.query(func.count(HelperProfile.id)).filter(
                HelperProfile.is_approved == True
            ).scalar() or 0
            online_helpers = db.session.query(func.count(HelperProfile.id)).filter(
                HelperProfile.is_online == True
            ).scalar() or 0
            by_country = dict(
                db.session.query(
                    HelperProfile.country_code, func.count(HelperProfile.id)
                ).group_by(HelperProfile.country_code).all()
            )

            # Transaction funnel
            txn_base = db.session.query(P2PTransaction).filter(P2PTransaction.created_at >= cutoff)
            total_txns = txn_base.count()
            status_counts = dict(
                db.session.query(
                    P2PTransaction.status, func.count(P2PTransaction.id)
                ).filter(P2PTransaction.created_at >= cutoff)
                .group_by(P2PTransaction.status).all()
            )
            completed = status_counts.get('completed', 0)
            avg_savings = db.session.query(
                func.avg(P2PTransaction.savings_usd)
            ).filter(
                P2PTransaction.created_at >= cutoff,
                P2PTransaction.status == 'completed'
            ).scalar()
            total_savings = db.session.query(
                func.sum(P2PTransaction.savings_usd)
            ).filter(
                P2PTransaction.created_at >= cutoff,
                P2PTransaction.status == 'completed'
            ).scalar()

            # Disputes
            total_disputes = db.session.query(func.count(Dispute.id)).filter(
                Dispute.created_at >= cutoff
            ).scalar() or 0
            resolution_breakdown = dict(
                db.session.query(
                    Dispute.resolution, func.count(Dispute.id)
                ).filter(Dispute.created_at >= cutoff)
                .group_by(Dispute.resolution).all()
            )
            dispute_rate = round(total_disputes / max(total_txns, 1) * 100, 2)

            return {
                "helpers": {
                    "total": total_helpers,
                    "approved": approved_helpers,
                    "online": online_helpers,
                    "by_country": by_country
                },
                "transactions": {
                    "total": total_txns,
                    "by_status": status_counts,
                    "completed": completed,
                    "dispute_rate_pct": dispute_rate,
                    "total_savings_usd": round(total_savings or 0, 2),
                    "avg_savings_usd": round(avg_savings or 0, 2)
                },
                "disputes": {
                    "total": total_disputes,
                    "resolution_breakdown": resolution_breakdown
                },
                "days_back": days_back
            }
        except Exception as e:
            return {"error": str(e)}

    def get_p2p_savings(self, days_back=30, limit=10):
        """Top P2P savings routes by market."""
        try:
            from models import db, P2PTransaction
            from datetime import datetime, timedelta
            from sqlalchemy import func

            cutoff = datetime.utcnow() - timedelta(days=days_back)

            rows = db.session.query(
                P2PTransaction.origin,
                P2PTransaction.destination,
                P2PTransaction.target_market,
                func.avg(P2PTransaction.savings_usd).label('avg_savings_usd'),
                func.avg(P2PTransaction.savings_percent).label('avg_savings_pct'),
                func.count(P2PTransaction.id).label('txn_count')
            ).filter(
                P2PTransaction.created_at >= cutoff,
                P2PTransaction.status == 'completed'
            ).group_by(
                P2PTransaction.origin,
                P2PTransaction.destination,
                P2PTransaction.target_market
            ).order_by(func.avg(P2PTransaction.savings_usd).desc()).limit(limit).all()

            total_savings = db.session.query(
                func.sum(P2PTransaction.savings_usd)
            ).filter(
                P2PTransaction.created_at >= cutoff,
                P2PTransaction.status == 'completed'
            ).scalar()

            return {
                "top_routes": [
                    {
                        "origin": r.origin,
                        "destination": r.destination,
                        "market": r.target_market,
                        "avg_savings_usd": round(r.avg_savings_usd or 0, 2),
                        "avg_savings_pct": round(r.avg_savings_pct or 0, 1),
                        "transaction_count": r.txn_count
                    } for r in rows
                ],
                "total_savings_usd": round(total_savings or 0, 2),
                "days_back": days_back
            }
        except Exception as e:
            return {"error": str(e)}

    def get_node_network(self):
        """CitizenSERP node network stats."""
        try:
            from citizenserp_payouts import citizenserp_manager
            stats = citizenserp_manager.get_network_stats()
            return stats if stats else {"error": "No node data available"}
        except Exception as e:
            return {"error": str(e)}

    def get_proxy_usage(self, days_back=7):
        """Proxy portal usage stats."""
        try:
            from proxy_portal import portal_manager
            from models import db, ProxySession
            from datetime import datetime, timedelta
            from sqlalchemy import func

            cutoff = datetime.utcnow() - timedelta(days=days_back)

            # Aggregate stats from portal manager
            portal_stats = portal_manager.get_portal_stats() if hasattr(portal_manager, 'get_portal_stats') else {}

            # Top target sites
            top_sites = db.session.query(
                ProxySession.target_site,
                func.count(ProxySession.id).label('count')
            ).filter(
                ProxySession.created_at >= cutoff
            ).group_by(ProxySession.target_site).order_by(
                func.count(ProxySession.id).desc()
            ).limit(10).all()

            # Sessions by country
            by_country = dict(
                db.session.query(
                    ProxySession.country_code,
                    func.count(ProxySession.id)
                ).filter(
                    ProxySession.created_at >= cutoff
                ).group_by(ProxySession.country_code).all()
            )

            total_sessions = db.session.query(func.count(ProxySession.id)).filter(
                ProxySession.created_at >= cutoff
            ).scalar() or 0

            return {
                "total_sessions": total_sessions,
                "top_sites": [{"site": s.target_site, "count": s.count} for s in top_sites],
                "by_country": by_country,
                "portal_stats": portal_stats,
                "days_back": days_back
            }
        except Exception as e:
            return {"error": str(e)}

    def get_ai_analytics(self, days_back=30):
        """AI provider analytics: query volume, BYOAI adoption, market trends."""
        try:
            from models import db, AISearchQuery, UserAIProvider
            from datetime import datetime, timedelta
            from sqlalchemy import func

            cutoff = datetime.utcnow() - timedelta(days=days_back)

            # Base provider performance
            provider_perf = self.get_provider_performance()

            # Daily query volume
            daily_volume = db.session.query(
                func.date(AISearchQuery.created_at).label('date'),
                func.count(AISearchQuery.id).label('count')
            ).filter(
                AISearchQuery.created_at >= cutoff
            ).group_by(func.date(AISearchQuery.created_at)).order_by(
                func.date(AISearchQuery.created_at)
            ).all()

            # BYOAI adoption
            byoai_adoption = dict(
                db.session.query(
                    UserAIProvider.provider_key,
                    func.count(UserAIProvider.id)
                ).filter(UserAIProvider.is_active == True)
                .group_by(UserAIProvider.provider_key).all()
            )

            # Top queried markets
            top_markets = db.session.query(
                AISearchQuery.market,
                func.count(AISearchQuery.id).label('queries')
            ).filter(
                AISearchQuery.created_at >= cutoff,
                AISearchQuery.market.isnot(None)
            ).group_by(AISearchQuery.market).order_by(
                func.count(AISearchQuery.id).desc()
            ).limit(10).all()

            # Totals
            total_queries = db.session.query(func.count(AISearchQuery.id)).filter(
                AISearchQuery.created_at >= cutoff
            ).scalar() or 0
            total_credits = db.session.query(func.sum(AISearchQuery.credits_used)).filter(
                AISearchQuery.created_at >= cutoff
            ).scalar() or 0

            return {
                "providers": provider_perf,
                "daily_volume": [{"date": str(d.date), "count": d.count} for d in daily_volume],
                "byoai_adoption": byoai_adoption,
                "top_markets": [{"market": m.market, "queries": m.queries} for m in top_markets],
                "total_queries": total_queries,
                "total_credits_used": round(total_credits, 2),
                "days_back": days_back
            }
        except Exception as e:
            return {"error": str(e)}

    def get_alert_demand(self, limit=20):
        """Price alert demand signals: most-watched routes and price sensitivity."""
        try:
            from models import db, PriceAlert
            from sqlalchemy import func

            # Most-watched routes
            watched = db.session.query(
                PriceAlert.origin,
                PriceAlert.destination,
                func.count(PriceAlert.id).label('alert_count'),
                func.avg(PriceAlert.max_price_usd).label('avg_price_threshold'),
                func.avg(PriceAlert.min_savings_percent).label('avg_savings_threshold')
            ).filter(
                PriceAlert.is_active == True
            ).group_by(
                PriceAlert.origin, PriceAlert.destination
            ).order_by(func.count(PriceAlert.id).desc()).limit(limit).all()

            total_active = db.session.query(func.count(PriceAlert.id)).filter(
                PriceAlert.is_active == True
            ).scalar() or 0

            return {
                "watched_routes": [
                    {
                        "origin": w.origin,
                        "destination": w.destination,
                        "alert_count": w.alert_count,
                        "avg_price_threshold": round(w.avg_price_threshold or 0, 2),
                        "avg_savings_threshold": round(w.avg_savings_threshold or 0, 1)
                    } for w in watched
                ],
                "total_active_alerts": total_active
            }
        except Exception as e:
            return {"error": str(e)}

    def get_private_market_stats(self, days_back=30):
        """Private market deal analytics."""
        try:
            from models import db, PrivateMarketDeal
            from datetime import datetime, timedelta
            from sqlalchemy import func

            cutoff = datetime.utcnow() - timedelta(days=days_back)

            base = db.session.query(PrivateMarketDeal).filter(
                PrivateMarketDeal.created_at >= cutoff
            )
            total = base.count()

            by_status = dict(
                db.session.query(
                    PrivateMarketDeal.status, func.count(PrivateMarketDeal.id)
                ).filter(PrivateMarketDeal.created_at >= cutoff)
                .group_by(PrivateMarketDeal.status).all()
            )
            by_type = dict(
                db.session.query(
                    PrivateMarketDeal.deal_type, func.count(PrivateMarketDeal.id)
                ).filter(PrivateMarketDeal.created_at >= cutoff)
                .group_by(PrivateMarketDeal.deal_type).all()
            )

            avg_price = db.session.query(
                func.avg(PrivateMarketDeal.agreed_price_rlusd)
            ).filter(PrivateMarketDeal.created_at >= cutoff).scalar()

            avg_risk = db.session.query(
                func.avg(PrivateMarketDeal.risk_score)
            ).filter(PrivateMarketDeal.created_at >= cutoff).scalar()

            total_fees = db.session.query(
                func.sum(PrivateMarketDeal.escrow_fee_rlusd)
            ).filter(PrivateMarketDeal.created_at >= cutoff).scalar()

            completed = by_status.get('completed', 0)
            completion_rate = round(completed / max(total, 1) * 100, 1)

            return {
                "deals": {
                    "total": total,
                    "by_status": by_status,
                    "by_type": by_type
                },
                "avg_deal_size_rlusd": round(avg_price or 0, 2),
                "avg_risk_score": round(avg_risk or 0, 1),
                "completion_rate_pct": completion_rate,
                "total_escrow_fees_rlusd": round(total_fees or 0, 2),
                "days_back": days_back
            }
        except Exception as e:
            return {"error": str(e)}

    def get_payment_analytics(self, days_back=30):
        """Payment method distribution and revenue trends."""
        try:
            from models import db, Payment
            from datetime import datetime, timedelta
            from sqlalchemy import func

            cutoff = datetime.utcnow() - timedelta(days=days_back)

            # By payment method
            by_method_rows = db.session.query(
                Payment.payment_method,
                func.count(Payment.id).label('count'),
                func.sum(Payment.amount_usd).label('total_usd')
            ).filter(
                Payment.created_at >= cutoff,
                Payment.verified == True
            ).group_by(Payment.payment_method).all()

            by_method = {
                r.payment_method: {
                    "count": r.count,
                    "total_usd": round(r.total_usd or 0, 2)
                } for r in by_method_rows
            }

            # Daily revenue
            daily_revenue = db.session.query(
                func.date(Payment.created_at).label('date'),
                func.sum(Payment.amount_usd).label('usd')
            ).filter(
                Payment.created_at >= cutoff,
                Payment.verified == True
            ).group_by(func.date(Payment.created_at)).order_by(
                func.date(Payment.created_at)
            ).all()

            total_revenue = db.session.query(
                func.sum(Payment.amount_usd)
            ).filter(
                Payment.created_at >= cutoff,
                Payment.verified == True
            ).scalar()

            total_payments = db.session.query(func.count(Payment.id)).filter(
                Payment.created_at >= cutoff
            ).scalar() or 0
            verified_payments = db.session.query(func.count(Payment.id)).filter(
                Payment.created_at >= cutoff,
                Payment.verified == True
            ).scalar() or 0
            conversion_rate = round(verified_payments / max(total_payments, 1) * 100, 1)

            return {
                "total_revenue_usd": round(total_revenue or 0, 2),
                "by_method": by_method,
                "daily_revenue": [{"date": str(d.date), "usd": round(d.usd or 0, 2)} for d in daily_revenue],
                "conversion_rate_pct": conversion_rate,
                "days_back": days_back
            }
        except Exception as e:
            return {"error": str(e)}

    def get_price_timeline(self, origin, destination, days_back=30):
        """Day-by-day price timeline for a route across markets."""
        try:
            from search_tracker import tracker
            timeline = tracker.get_price_trend(origin, destination, days=days_back)
            return {
                "origin": origin,
                "destination": destination,
                "days_back": days_back,
                "timeline": timeline if timeline else {}
            }
        except Exception as e:
            return {"error": str(e)}

    def get_airline_comparison(self, origin, destination, days_back=7):
        """Airline competitive pricing and ancillary fees for a route."""
        try:
            from models import db, CompetitorPricing, AncillarySnapshot
            from datetime import datetime, timedelta
            from sqlalchemy import func

            cutoff = datetime.utcnow() - timedelta(days=days_back)
            route_key = f"{origin}-{destination}"

            # Per-airline pricing
            airline_prices = db.session.query(
                CompetitorPricing.airline_iata,
                func.avg(CompetitorPricing.price_usd).label('avg_price'),
                func.min(CompetitorPricing.price_usd).label('min_price')
            ).filter(
                CompetitorPricing.route == route_key,
                CompetitorPricing.snapshot_date >= cutoff
            ).group_by(CompetitorPricing.airline_iata).order_by(
                func.avg(CompetitorPricing.price_usd)
            ).all()

            # Ancillary fees
            ancillary = {}
            anc_rows = db.session.query(AncillarySnapshot).filter(
                AncillarySnapshot.route == route_key,
                AncillarySnapshot.snapshot_date >= cutoff
            ).all()
            for row in anc_rows:
                ancillary[row.airline_iata] = {
                    "bag_1_fee": row.bag_1_fee,
                    "seat_min": row.seat_min_fee
                }

            airlines = []
            for idx, ap in enumerate(airline_prices):
                anc = ancillary.get(ap.airline_iata, {})
                bag_fee = anc.get("bag_1_fee", 0) or 0
                seat_fee = anc.get("seat_min", 0) or 0
                airlines.append({
                    "airline_iata": ap.airline_iata,
                    "avg_price": round(ap.avg_price or 0, 2),
                    "min_price": round(ap.min_price or 0, 2),
                    "market_rank": idx + 1,
                    "bag_1_fee": round(bag_fee, 2),
                    "seat_min": round(seat_fee, 2),
                    "total_cost_estimate": round((ap.avg_price or 0) + bag_fee + seat_fee, 2)
                })

            cheapest = airlines[0]["airline_iata"] if airlines else None
            best_value = min(airlines, key=lambda a: a["total_cost_estimate"])["airline_iata"] if airlines else None

            return {
                "route": route_key,
                "airlines": airlines,
                "cheapest_airline": cheapest,
                "best_value_airline": best_value,
                "days_back": days_back
            }
        except Exception as e:
            return {"error": str(e)}


# Global instance
intelligence = PhoenixIntelligence()
