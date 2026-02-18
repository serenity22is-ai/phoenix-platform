"""
MYSTES Data Marketplace Engine (Build #74)

Core engine for the Mystes Data Marketplace — a tiered API that exposes
aggregated, privacy-safe data products derived from the Mystes network.

Products span six categories:
    - AI Benchmarking (provider win rates, model comparisons, strategy insights)
    - Geographic Pricing (route pricing, price history, ancillary fees, arbitrage)
    - SERP Intelligence (search-engine result feeds, trends, geographic variance)
    - Ad Intelligence (ad inventory, competitor reports, market trends)
    - Browsing Intelligence (domain-level aggregated reports, trends)
    - Network Intelligence (node stats, proxy performance)

Privacy guarantees:
    Every _query_* method strips user_id, email, raw query text, full URLs,
    and API keys before returning data.  BrowsingEvent exposes domain +
    data_category + quality_score ONLY.  AISearchQuery exposes aggregated
    metrics only — never raw content.

Usage:
    from data_marketplace import data_marketplace, register_data_marketplace_routes

    register_data_marketplace_routes(app)

    result = data_marketplace.query_product(account, "route_pricing",
                                            filters={"origin": "JFK"})
"""

import csv
import hashlib
import hmac
import io
import json
import logging
import os
import secrets
import statistics
import tempfile
import time
from datetime import datetime, timedelta
from functools import wraps

import requests as http_requests
from flask import Blueprint, request, g, jsonify
from sqlalchemy import func, cast, Date

from models import (
    db,
    DataProduct,
    DataSubscription,
    DataExport,
    DataWebhook,
    DataUsageRecord,
    CommercialAccount,
    Deal,
    PriceHistory,
    AncillarySnapshot,
    SearchHistory,
    CompetitorPricing,
    AISearchQuery,
    UserAIProvider,
    StrategyObservation,
    StrategyInsight,
    SERPAPIQuery,
    AdIntelligenceRecord,
    BrowsingEvent,
    HelperProfile,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tier & pricing definitions
# ---------------------------------------------------------------------------

DATA_MARKETPLACE_TIERS = {
    "data_free": {
        "price": 0,
        "queries": 100,
        "products": 0,
        "days": 7,
        "results": 10,
        "csv": False,
        "webhooks": False,
    },
    "data_starter": {
        "price": 499,
        "queries": 10_000,
        "products": 3,
        "days": 30,
        "results": 500,
        "csv": False,
        "webhooks": False,
    },
    "data_professional": {
        "price": 2499,
        "queries": 100_000,
        "products": -1,
        "days": 90,
        "results": 2000,
        "csv": True,
        "webhooks": False,
    },
    "data_enterprise": {
        "price": 9999,
        "queries": -1,
        "products": -1,
        "days": 365,
        "results": 10_000,
        "csv": True,
        "webhooks": True,
    },
}

AI_BENCHMARK_ADDON = {"price": 999, "key": "ai_benchmarking"}

TIER_ORDER = ["data_free", "data_starter", "data_professional", "data_enterprise"]

# ---------------------------------------------------------------------------
# Product catalog (22 products across 6 categories)
# ---------------------------------------------------------------------------

PRODUCT_CATALOG = {
    # --- AI Benchmarking (requires ai_benchmarking addon) ---
    "ai_provider_benchmark": {
        "name": "AI Provider Benchmark",
        "description": "Provider win rates, response times, and quality scores aggregated across the MYSTES AI ensemble.",
        "category": "ai_benchmarking",
        "min_tier": "data_starter",
        "credit_cost": 2.0,
        "available_fields": ["provider", "win_rate", "avg_response_time_ms", "avg_quality_score", "total_queries", "period"],
        "supported_filters": ["provider", "category", "date_from", "date_to"],
    },
    "ai_model_comparison": {
        "name": "AI Model Comparison",
        "description": "Head-to-head provider comparisons from multi-provider ensemble queries.",
        "category": "ai_benchmarking",
        "min_tier": "data_starter",
        "credit_cost": 3.0,
        "available_fields": ["provider_a", "provider_b", "provider_a_wins", "provider_b_wins", "total_comparisons", "avg_quality_delta"],
        "supported_filters": ["provider", "category", "date_from", "date_to"],
    },
    "ai_strategy_effectiveness": {
        "name": "AI Strategy Effectiveness",
        "description": "Strategy type effectiveness scores derived from the Mystes Strategy Learner.",
        "category": "ai_benchmarking",
        "min_tier": "data_starter",
        "credit_cost": 2.0,
        "available_fields": ["strategy_type", "category", "effectiveness_score", "confidence", "observation_count"],
        "supported_filters": ["category", "insight_type", "min_confidence"],
    },
    "ai_query_patterns": {
        "name": "AI Query Patterns",
        "description": "Query structure patterns and frequencies from the Strategy Observation pipeline.",
        "category": "ai_benchmarking",
        "min_tier": "data_starter",
        "credit_cost": 1.5,
        "available_fields": ["source_type", "query_category", "query_structure", "result_count", "result_quality_score", "markets_searched"],
        "supported_filters": ["source_type", "query_category", "date_from", "date_to"],
    },
    "ai_provider_adoption": {
        "name": "AI Provider Adoption",
        "description": "Aggregated provider usage shares across the Mystes network (no individual user data).",
        "category": "ai_benchmarking",
        "min_tier": "data_starter",
        "credit_cost": 1.0,
        "available_fields": ["provider_key", "active_users", "total_share_pct"],
        "supported_filters": ["provider_key"],
    },
    # --- Geographic Pricing ---
    "route_pricing": {
        "name": "Route Pricing",
        "description": "Current route pricing across global markets from active Mystes deals.",
        "category": "geographic_pricing",
        "min_tier": "data_starter",
        "credit_cost": 1.0,
        "available_fields": ["origin", "destination", "airline", "home_market", "home_price_usd", "arbitrage_market", "arbitrage_price_usd", "savings_percent"],
        "supported_filters": ["origin", "destination", "airline", "home_market", "arbitrage_market", "min_savings"],
    },
    "price_history_feed": {
        "name": "Price History Feed",
        "description": "Historical price time series for route/market combinations.",
        "category": "geographic_pricing",
        "min_tier": "data_starter",
        "credit_cost": 1.0,
        "available_fields": ["origin", "destination", "market", "price_usd", "airline", "cabin_class", "recorded_at"],
        "supported_filters": ["origin", "destination", "market", "airline", "date_from", "date_to"],
    },
    "ancillary_fee_database": {
        "name": "Ancillary Fee Database",
        "description": "Airline ancillary fees (bags, seats, upgrades) by route and market.",
        "category": "geographic_pricing",
        "min_tier": "data_starter",
        "credit_cost": 1.0,
        "available_fields": ["origin", "destination", "market", "airline", "checked_bag_1_price_usd", "checked_bag_2_price_usd", "seat_selection_range_usd"],
        "supported_filters": ["origin", "destination", "market", "airline"],
    },
    "arbitrage_opportunities": {
        "name": "Arbitrage Opportunities",
        "description": "Active arbitrage deals with real-time savings data.",
        "category": "geographic_pricing",
        "min_tier": "data_starter",
        "credit_cost": 2.0,
        "available_fields": ["origin", "destination", "airline", "home_price_usd", "arbitrage_price_usd", "gross_savings_usd", "savings_percent", "expires_at"],
        "supported_filters": ["origin", "destination", "min_savings", "airline"],
    },
    "market_briefings": {
        "name": "Market Briefings",
        "description": "Market summary reports aggregated from search activity and deal flow.",
        "category": "geographic_pricing",
        "min_tier": "data_starter",
        "credit_cost": 3.0,
        "available_fields": ["market", "total_searches", "total_deals", "avg_savings_pct", "top_routes", "period"],
        "supported_filters": ["market", "date_from", "date_to"],
    },
    "demand_signals": {
        "name": "Demand Signals",
        "description": "Search volume and trend data for routes and markets.",
        "category": "geographic_pricing",
        "min_tier": "data_starter",
        "credit_cost": 1.5,
        "available_fields": ["origin", "destination", "search_count", "avg_best_price", "period"],
        "supported_filters": ["origin", "destination", "date_from", "date_to"],
    },
    "competitor_pricing": {
        "name": "Competitor Pricing",
        "description": "Competitive airline pricing data aggregated by route and market.",
        "category": "geographic_pricing",
        "min_tier": "data_starter",
        "credit_cost": 2.0,
        "available_fields": ["origin", "destination", "market", "airline_iata", "avg_price_usd", "min_price_usd", "max_price_usd", "market_rank"],
        "supported_filters": ["origin", "destination", "market", "airline_iata", "date_from", "date_to"],
    },
    # --- SERP Intelligence ---
    "serp_results_feed": {
        "name": "SERP Results Feed",
        "description": "Search engine result page data across engines and markets.",
        "category": "serp_intelligence",
        "min_tier": "data_professional",
        "credit_cost": 2.0,
        "available_fields": ["engine", "market", "status", "credits_used", "response_time_ms", "created_at"],
        "supported_filters": ["engine", "market", "status", "date_from", "date_to"],
    },
    "serp_trends": {
        "name": "SERP Trends",
        "description": "SERP trend analysis — volume, response times, and success rates over time.",
        "category": "serp_intelligence",
        "min_tier": "data_professional",
        "credit_cost": 2.5,
        "available_fields": ["period", "engine", "market", "query_count", "avg_response_time_ms", "success_rate"],
        "supported_filters": ["engine", "market", "date_from", "date_to"],
    },
    "serp_geographic_variance": {
        "name": "SERP Geographic Variance",
        "description": "Cross-market SERP differences and geographic variance analysis.",
        "category": "serp_intelligence",
        "min_tier": "data_professional",
        "credit_cost": 3.0,
        "available_fields": ["market", "engine", "avg_response_time_ms", "success_rate", "total_queries"],
        "supported_filters": ["engine", "date_from", "date_to"],
    },
    # --- Ad Intelligence ---
    "ad_inventory_feed": {
        "name": "Ad Inventory Feed",
        "description": "Ad inventory data captured across the Mystes node network.",
        "category": "ad_intelligence",
        "min_tier": "data_professional",
        "credit_cost": 2.0,
        "available_fields": ["market", "advertiser", "ad_network", "ad_format", "ad_position", "vertical", "estimated_bid_usd", "observed_at"],
        "supported_filters": ["market", "advertiser", "ad_network", "vertical", "date_from", "date_to"],
    },
    "ad_competitor_reports": {
        "name": "Ad Competitor Reports",
        "description": "Competitor ad spend and placement reports by vertical and market.",
        "category": "ad_intelligence",
        "min_tier": "data_professional",
        "credit_cost": 3.0,
        "available_fields": ["advertiser", "market", "vertical", "total_ads", "avg_bid_usd", "top_networks", "top_formats"],
        "supported_filters": ["advertiser", "market", "vertical", "date_from", "date_to"],
    },
    "ad_market_trends": {
        "name": "Ad Market Trends",
        "description": "Ad market trend analysis — spend patterns, format shifts, network distributions.",
        "category": "ad_intelligence",
        "min_tier": "data_professional",
        "credit_cost": 2.5,
        "available_fields": ["period", "market", "vertical", "total_ads", "avg_bid_usd", "top_advertisers"],
        "supported_filters": ["market", "vertical", "date_from", "date_to"],
    },
    # --- Browsing Intelligence (PRIVACY: domain + category only) ---
    "browsing_event_stream": {
        "name": "Browsing Event Stream",
        "description": "Anonymized browsing events — domain and category level only. NO urls, titles, or PII.",
        "category": "browsing_intelligence",
        "min_tier": "data_enterprise",
        "credit_cost": 1.0,
        "available_fields": ["domain", "data_category", "quality_score", "event_type", "captured_at"],
        "supported_filters": ["domain", "data_category", "event_type", "min_quality", "date_from", "date_to"],
    },
    "browsing_domain_reports": {
        "name": "Browsing Domain Reports",
        "description": "Domain-level aggregated browsing reports with quality metrics.",
        "category": "browsing_intelligence",
        "min_tier": "data_enterprise",
        "credit_cost": 2.0,
        "available_fields": ["domain", "total_events", "avg_quality_score", "top_categories", "event_type_distribution"],
        "supported_filters": ["domain", "data_category", "date_from", "date_to"],
    },
    "browsing_trends": {
        "name": "Browsing Trends",
        "description": "Browsing trend analysis — domain popularity, category shifts, quality distributions.",
        "category": "browsing_intelligence",
        "min_tier": "data_enterprise",
        "credit_cost": 2.5,
        "available_fields": ["period", "top_domains", "top_categories", "avg_quality", "total_events"],
        "supported_filters": ["data_category", "date_from", "date_to"],
    },
    # --- Network Intelligence ---
    "node_network_stats": {
        "name": "Node Network Stats",
        "description": "Aggregated network node statistics — uptime, geographic distribution, performance.",
        "category": "network_intelligence",
        "min_tier": "data_professional",
        "credit_cost": 1.5,
        "available_fields": ["country_code", "total_nodes", "active_nodes", "avg_success_rate", "avg_rating"],
        "supported_filters": ["country_code", "is_active"],
    },
    "proxy_performance": {
        "name": "Proxy Performance",
        "description": "Proxy success rates, response times, and performance metrics by region.",
        "category": "network_intelligence",
        "min_tier": "data_professional",
        "credit_cost": 1.5,
        "available_fields": ["country_code", "total_transactions", "success_rate", "avg_earned_rlusd"],
        "supported_filters": ["country_code"],
    },
}

# ---------------------------------------------------------------------------
# Helper: tier-level check
# ---------------------------------------------------------------------------

def _tier_index(tier_key):
    """Return numeric index for a tier key (higher = more access)."""
    try:
        return TIER_ORDER.index(tier_key)
    except ValueError:
        return 0


# ===========================================================================
# DataMarketplaceEngine
# ===========================================================================

class DataMarketplaceEngine:
    """Core engine for the Mystes Data Marketplace.

    Provides catalog browsing, access control, product queries,
    bulk exports, webhook subscriptions, and the MYSTES AI Benchmark report.
    """

    def __init__(self):
        logger.info("DataMarketplaceEngine initialised")

    # ------------------------------------------------------------------
    # Catalog
    # ------------------------------------------------------------------

    def get_catalog(self, category=None):
        """Return the full product catalog, optionally filtered by category.

        Returns:
            dict with ``products`` list and ``total`` count.
        """
        products = []
        for pid, meta in PRODUCT_CATALOG.items():
            if category and meta["category"] != category:
                continue
            products.append({
                "product_id": pid,
                **meta,
            })
        return {"products": products, "total": len(products)}

    def get_product(self, product_id):
        """Return metadata for a single product, or None if unknown."""
        meta = PRODUCT_CATALOG.get(product_id)
        if meta is None:
            return None
        return {"product_id": product_id, **meta}

    def get_pricing(self):
        """Return tier definitions and addon pricing."""
        return {
            "tiers": DATA_MARKETPLACE_TIERS,
            "addons": {"ai_benchmarking": AI_BENCHMARK_ADDON},
            "tier_order": TIER_ORDER,
        }

    # ------------------------------------------------------------------
    # Access control
    # ------------------------------------------------------------------

    def check_product_access(self, account, product_id):
        """Check whether *account*'s tier allows access to *product_id*.

        Returns:
            dict with ``allowed`` (bool) and ``reason`` (str).
        """
        meta = PRODUCT_CATALOG.get(product_id)
        if meta is None:
            return {"allowed": False, "reason": f"Unknown product: {product_id}"}

        # Resolve the subscription for this account
        sub = self._get_active_subscription(account)
        if sub is None:
            return {"allowed": False, "reason": "No active data marketplace subscription"}

        tier_key = sub.tier or "data_free"
        required_tier = meta["min_tier"]

        # Tier-level gate
        if _tier_index(tier_key) < _tier_index(required_tier):
            return {
                "allowed": False,
                "reason": f"Product requires {required_tier} tier or above (current: {tier_key})",
            }

        # AI benchmarking products require the addon
        if meta["category"] == "ai_benchmarking":
            addons = json.loads(sub.addons) if sub.addons else []
            if AI_BENCHMARK_ADDON["key"] not in addons:
                return {
                    "allowed": False,
                    "reason": "AI Benchmarking add-on required for this product",
                }

        # Starter tier: max N selected products
        tier_def = DATA_MARKETPLACE_TIERS.get(tier_key, {})
        max_products = tier_def.get("products", 0)
        if max_products > 0:
            selected = json.loads(sub.selected_products) if sub.selected_products else []
            if product_id not in selected and len(selected) >= max_products:
                return {
                    "allowed": False,
                    "reason": f"Starter tier limited to {max_products} selected products. "
                              f"Current selections: {selected}",
                }

        return {"allowed": True, "reason": "ok"}

    def check_quota(self, account):
        """Check whether *account* has remaining query quota.

        Resets the monthly counter automatically when past the reset date.

        Returns:
            dict with ``allowed``, ``remaining``, ``limit``.
        """
        sub = self._get_active_subscription(account)
        if sub is None:
            return {"allowed": False, "remaining": 0, "limit": 0}

        tier_key = sub.tier or "data_free"
        tier_def = DATA_MARKETPLACE_TIERS.get(tier_key, {})
        query_limit = tier_def.get("queries", 0)

        # Auto-reset
        now = datetime.utcnow()
        if sub.period_end and now > sub.period_end:
            sub.queries_used_this_period = 0
            sub.period_start = now
            days = tier_def.get("days", 30)
            sub.period_end = now + timedelta(days=days)
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()

        used = sub.queries_used_this_period or 0

        # -1 means unlimited
        if query_limit == -1:
            return {"allowed": True, "remaining": -1, "limit": -1}

        remaining = max(0, query_limit - used)
        return {
            "allowed": remaining > 0,
            "remaining": remaining,
            "limit": query_limit,
        }

    def record_usage(self, account, product_id, query_type, records_returned, credits):
        """Record a usage event and increment the subscription counter."""
        try:
            usage = DataUsageRecord(
                account_id=account.id,
                product_id=product_id,
                query_type=query_type,
                records_returned=records_returned,
                credits_consumed=credits,
            )
            db.session.add(usage)

            sub = self._get_active_subscription(account)
            if sub:
                sub.queries_used_this_period = (sub.queries_used_this_period or 0) + 1

            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception("Failed to record usage for account %s", account.id)

    # ------------------------------------------------------------------
    # Data queries
    # ------------------------------------------------------------------

    def query_product(self, account, product_id, filters=None, limit=100, offset=0):
        """Main entry point for querying a data product.

        Performs access checks, quota checks, dispatches to the appropriate
        ``_query_*`` method, records usage, and returns the result.
        """
        # Access check
        access = self.check_product_access(account, product_id)
        if not access["allowed"]:
            return {"error": access["reason"]}, 403

        # Quota check
        quota = self.check_quota(account)
        if not quota["allowed"]:
            return {"error": "Query quota exhausted", "quota": quota}, 429

        # Resolve tier constraints
        sub = self._get_active_subscription(account)
        tier_key = sub.tier if sub else "data_free"
        tier_def = DATA_MARKETPLACE_TIERS.get(tier_key, {})
        max_results = tier_def.get("results", 10)
        max_days = tier_def.get("days", 7)

        limit = min(limit, max_results)

        # Dispatch to _query_<product_id> method
        method_name = f"_query_{product_id}"
        method = getattr(self, method_name, None)
        if method is None:
            return {"error": f"No query handler for product: {product_id}"}, 500

        start_ts = time.time()
        try:
            result = method(filters or {}, limit, offset, max_days)
        except Exception:
            logger.exception("Query failed for product %s", product_id)
            return {"error": "Internal query error"}, 500
        elapsed_ms = int((time.time() - start_ts) * 1000)

        # Record usage
        meta = PRODUCT_CATALOG.get(product_id, {})
        records_returned = len(result.get("data", []))
        self.record_usage(
            account,
            product_id,
            query_type="api_query",
            records_returned=records_returned,
            credits=meta.get("credit_cost", 1.0),
        )

        result["product_id"] = product_id
        result["query_time_ms"] = elapsed_ms
        result["limit"] = limit
        result["offset"] = offset
        return result, 200

    def get_sample(self, product_id):
        """Return a free sample (up to 10 rows) for *product_id*, no auth required."""
        meta = PRODUCT_CATALOG.get(product_id)
        if meta is None:
            return {"error": f"Unknown product: {product_id}"}

        method_name = f"_query_{product_id}"
        method = getattr(self, method_name, None)
        if method is None:
            return {"error": "Sample not available for this product"}

        try:
            result = method({}, limit=10, offset=0, max_days=7)
        except Exception:
            logger.exception("Sample query failed for %s", product_id)
            result = {"data": [], "total": 0}

        return {
            "product_id": product_id,
            "sample": True,
            "data": result.get("data", [])[:10],
            "total_available": result.get("total", 0),
            "note": "This is a free sample. Subscribe for full access.",
        }

    # ------------------------------------------------------------------
    # Private query methods — AI Benchmarking
    # ------------------------------------------------------------------

    def _query_ai_provider_benchmark(self, filters, limit, offset, max_days):
        """Provider-level aggregated stats from AISearchQuery."""
        try:
            cutoff = datetime.utcnow() - timedelta(days=max_days)
            q = db.session.query(
                AISearchQuery.best_provider,
                func.count(AISearchQuery.id).label("total_queries"),
                func.avg(AISearchQuery.response_time_ms).label("avg_response_time_ms"),
            ).filter(
                AISearchQuery.created_at >= cutoff,
                AISearchQuery.best_provider.isnot(None),
            )

            if filters.get("provider"):
                q = q.filter(AISearchQuery.best_provider == filters["provider"])

            q = q.group_by(AISearchQuery.best_provider)
            total = q.count()
            rows = q.offset(offset).limit(limit).all()

            # Calculate win rates
            total_all = db.session.query(func.count(AISearchQuery.id)).filter(
                AISearchQuery.created_at >= cutoff,
                AISearchQuery.best_provider.isnot(None),
            ).scalar() or 1

            data = []
            for row in rows:
                data.append({
                    "provider": row[0],
                    "total_queries": row[1],
                    "win_rate": round(row[1] / total_all * 100, 2),
                    "avg_response_time_ms": round(row[2], 1) if row[2] else None,
                    "period_days": max_days,
                })
            return {"data": data, "total": total}
        except Exception:
            logger.exception("_query_ai_provider_benchmark failed")
            return {"data": [], "total": 0}

    def _query_ai_model_comparison(self, filters, limit, offset, max_days):
        """Head-to-head comparisons from AISearchQuery.all_responses JSON field."""
        try:
            cutoff = datetime.utcnow() - timedelta(days=max_days)
            queries = AISearchQuery.query.filter(
                AISearchQuery.created_at >= cutoff,
                AISearchQuery.all_responses.isnot(None),
            ).order_by(AISearchQuery.created_at.desc()).limit(500).all()

            pair_stats = {}
            for q in queries:
                try:
                    responses = json.loads(q.all_responses) if q.all_responses else []
                except (json.JSONDecodeError, TypeError):
                    continue
                providers = [r.get("provider") for r in responses if r.get("provider")]
                winner = q.best_provider
                for i, pa in enumerate(providers):
                    for pb in providers[i + 1:]:
                        key = tuple(sorted([pa, pb]))
                        if key not in pair_stats:
                            pair_stats[key] = {"a": key[0], "b": key[1], "a_wins": 0, "b_wins": 0, "total": 0}
                        pair_stats[key]["total"] += 1
                        if winner == key[0]:
                            pair_stats[key]["a_wins"] += 1
                        elif winner == key[1]:
                            pair_stats[key]["b_wins"] += 1

            data = list(pair_stats.values())
            for d in data:
                d["provider_a"] = d.pop("a")
                d["provider_b"] = d.pop("b")
                d["provider_a_wins"] = d.pop("a_wins")
                d["provider_b_wins"] = d.pop("b_wins")
                d["total_comparisons"] = d.pop("total")

            total = len(data)
            data = data[offset: offset + limit]
            return {"data": data, "total": total}
        except Exception:
            logger.exception("_query_ai_model_comparison failed")
            return {"data": [], "total": 0}

    def _query_ai_strategy_effectiveness(self, filters, limit, offset, max_days):
        """Strategy effectiveness from StrategyInsight."""
        try:
            cutoff = datetime.utcnow() - timedelta(days=max_days)
            q = StrategyInsight.query.filter(
                StrategyInsight.is_active.is_(True),
                StrategyInsight.created_at >= cutoff,
            )
            if filters.get("category"):
                q = q.filter(StrategyInsight.category == filters["category"])
            if filters.get("insight_type"):
                q = q.filter(StrategyInsight.insight_type == filters["insight_type"])
            if filters.get("min_confidence"):
                q = q.filter(StrategyInsight.confidence_score >= float(filters["min_confidence"]))

            q = q.order_by(StrategyInsight.effectiveness_score.desc())
            total = q.count()
            rows = q.offset(offset).limit(limit).all()

            data = []
            for r in rows:
                data.append({
                    "insight_id": r.insight_id,
                    "category": r.category,
                    "insight_type": r.insight_type,
                    "effectiveness_score": round(r.effectiveness_score, 3),
                    "confidence": round(r.confidence_score, 3),
                    "observation_count": r.observation_count,
                })
            return {"data": data, "total": total}
        except Exception:
            logger.exception("_query_ai_strategy_effectiveness failed")
            return {"data": [], "total": 0}

    def _query_ai_query_patterns(self, filters, limit, offset, max_days):
        """Query structure patterns from StrategyObservation."""
        try:
            cutoff = datetime.utcnow() - timedelta(days=max_days)
            q = StrategyObservation.query.filter(StrategyObservation.created_at >= cutoff)

            if filters.get("source_type"):
                q = q.filter(StrategyObservation.source_type == filters["source_type"])
            if filters.get("query_category"):
                q = q.filter(StrategyObservation.query_category == filters["query_category"])

            q = q.order_by(StrategyObservation.created_at.desc())
            total = q.count()
            rows = q.offset(offset).limit(limit).all()

            data = []
            for r in rows:
                data.append({
                    "observation_id": r.observation_id,
                    "source_type": r.source_type,
                    "query_category": r.query_category,
                    "query_structure": json.loads(r.query_structure) if r.query_structure else None,
                    "result_count": r.result_count,
                    "result_quality_score": round(r.result_quality_score, 1),
                    "markets_searched": json.loads(r.markets_searched) if r.markets_searched else [],
                    "response_time_ms": r.response_time_ms,
                    # PRIVACY: no user_id, no raw query text
                })
            return {"data": data, "total": total}
        except Exception:
            logger.exception("_query_ai_query_patterns failed")
            return {"data": [], "total": 0}

    def _query_ai_provider_adoption(self, filters, limit, offset, max_days):
        """Aggregated provider adoption from UserAIProvider (no individual user data)."""
        try:
            q = db.session.query(
                UserAIProvider.provider_key,
                func.count(UserAIProvider.id).label("active_users"),
            ).filter(UserAIProvider.is_active.is_(True))

            if filters.get("provider_key"):
                q = q.filter(UserAIProvider.provider_key == filters["provider_key"])

            q = q.group_by(UserAIProvider.provider_key)
            rows = q.all()

            total_users = sum(r[1] for r in rows) or 1
            data = []
            for r in rows:
                data.append({
                    "provider_key": r[0],
                    "active_users": r[1],
                    "total_share_pct": round(r[1] / total_users * 100, 2),
                    # PRIVACY: no user_id, no API keys
                })
            total = len(data)
            data = data[offset: offset + limit]
            return {"data": data, "total": total}
        except Exception:
            logger.exception("_query_ai_provider_adoption failed")
            return {"data": [], "total": 0}

    # ------------------------------------------------------------------
    # Private query methods — Geographic Pricing
    # ------------------------------------------------------------------

    def _query_route_pricing(self, filters, limit, offset, max_days):
        """Current route pricing from Deal model."""
        try:
            cutoff = datetime.utcnow() - timedelta(days=max_days)
            q = Deal.query.filter(
                Deal.is_active.is_(True),
                Deal.created_at >= cutoff,
            )
            if filters.get("origin"):
                q = q.filter(Deal.origin == filters["origin"].upper())
            if filters.get("destination"):
                q = q.filter(Deal.destination == filters["destination"].upper())
            if filters.get("airline"):
                q = q.filter(Deal.airline.ilike(f"%{filters['airline']}%"))
            if filters.get("home_market"):
                q = q.filter(Deal.home_market == filters["home_market"].upper())
            if filters.get("arbitrage_market"):
                q = q.filter(Deal.arbitrage_market == filters["arbitrage_market"].upper())
            if filters.get("min_savings"):
                q = q.filter(Deal.savings_percent >= float(filters["min_savings"]))

            q = q.order_by(Deal.savings_percent.desc())
            total = q.count()
            rows = q.offset(offset).limit(limit).all()

            data = []
            for d in rows:
                data.append({
                    "origin": d.origin,
                    "destination": d.destination,
                    "airline": d.airline,
                    "home_market": d.home_market,
                    "home_price_usd": d.home_price_usd,
                    "arbitrage_market": d.arbitrage_market,
                    "arbitrage_price_usd": d.arbitrage_price_usd,
                    "savings_percent": round(d.savings_percent, 1) if d.savings_percent else None,
                    "departure_date": d.departure_date.isoformat() if d.departure_date else None,
                    # PRIVACY: no deal_id, no booking_url, no destination_tag
                })
            return {"data": data, "total": total}
        except Exception:
            logger.exception("_query_route_pricing failed")
            return {"data": [], "total": 0}

    def _query_price_history_feed(self, filters, limit, offset, max_days):
        """Historical price time series from PriceHistory."""
        try:
            cutoff = datetime.utcnow() - timedelta(days=max_days)
            q = PriceHistory.query.filter(PriceHistory.recorded_at >= cutoff)

            if filters.get("origin"):
                q = q.filter(PriceHistory.origin == filters["origin"].upper())
            if filters.get("destination"):
                q = q.filter(PriceHistory.destination == filters["destination"].upper())
            if filters.get("market"):
                q = q.filter(PriceHistory.market == filters["market"].upper())
            if filters.get("airline"):
                q = q.filter(PriceHistory.airline.ilike(f"%{filters['airline']}%"))

            q = q.order_by(PriceHistory.recorded_at.desc())
            total = q.count()
            rows = q.offset(offset).limit(limit).all()

            data = [r.to_dict() for r in rows]
            return {"data": data, "total": total}
        except Exception:
            logger.exception("_query_price_history_feed failed")
            return {"data": [], "total": 0}

    def _query_ancillary_fee_database(self, filters, limit, offset, max_days):
        """Ancillary fee data from AncillarySnapshot."""
        try:
            cutoff = datetime.utcnow() - timedelta(days=max_days)
            q = AncillarySnapshot.query.filter(AncillarySnapshot.recorded_at >= cutoff)

            if filters.get("origin"):
                q = q.filter(AncillarySnapshot.origin == filters["origin"].upper())
            if filters.get("destination"):
                q = q.filter(AncillarySnapshot.destination == filters["destination"].upper())
            if filters.get("market"):
                q = q.filter(AncillarySnapshot.market == filters["market"].upper())
            if filters.get("airline"):
                q = q.filter(AncillarySnapshot.airline.ilike(f"%{filters['airline']}%"))

            q = q.order_by(AncillarySnapshot.recorded_at.desc())
            total = q.count()
            rows = q.offset(offset).limit(limit).all()

            data = [r.to_dict() for r in rows]
            return {"data": data, "total": total}
        except Exception:
            logger.exception("_query_ancillary_fee_database failed")
            return {"data": [], "total": 0}

    def _query_arbitrage_opportunities(self, filters, limit, offset, max_days):
        """Active arbitrage deals with savings data."""
        try:
            cutoff = datetime.utcnow() - timedelta(days=max_days)
            q = Deal.query.filter(
                Deal.is_active.is_(True),
                Deal.gross_savings_usd > 0,
                Deal.created_at >= cutoff,
            )
            if filters.get("origin"):
                q = q.filter(Deal.origin == filters["origin"].upper())
            if filters.get("destination"):
                q = q.filter(Deal.destination == filters["destination"].upper())
            if filters.get("min_savings"):
                q = q.filter(Deal.savings_percent >= float(filters["min_savings"]))
            if filters.get("airline"):
                q = q.filter(Deal.airline.ilike(f"%{filters['airline']}%"))

            q = q.order_by(Deal.gross_savings_usd.desc())
            total = q.count()
            rows = q.offset(offset).limit(limit).all()

            data = []
            for d in rows:
                data.append({
                    "origin": d.origin,
                    "destination": d.destination,
                    "airline": d.airline,
                    "home_price_usd": d.home_price_usd,
                    "arbitrage_price_usd": d.arbitrage_price_usd,
                    "gross_savings_usd": round(d.gross_savings_usd, 2) if d.gross_savings_usd else None,
                    "savings_percent": round(d.savings_percent, 1) if d.savings_percent else None,
                    "departure_date": d.departure_date.isoformat() if d.departure_date else None,
                    "expires_at": d.expires_at.isoformat() if d.expires_at else None,
                    # PRIVACY: no deal_id, no booking_url
                })
            return {"data": data, "total": total}
        except Exception:
            logger.exception("_query_arbitrage_opportunities failed")
            return {"data": [], "total": 0}

    def _query_market_briefings(self, filters, limit, offset, max_days):
        """Aggregated market summary from SearchHistory + Deal."""
        try:
            cutoff = datetime.utcnow() - timedelta(days=max_days)

            # Search volume per market
            search_q = db.session.query(
                SearchHistory.origin,
                func.count(SearchHistory.id).label("search_count"),
                func.avg(SearchHistory.max_savings_percent).label("avg_savings_pct"),
            ).filter(SearchHistory.created_at >= cutoff)

            if filters.get("market"):
                search_q = search_q.filter(SearchHistory.origin == filters["market"].upper())

            search_q = search_q.group_by(SearchHistory.origin)
            search_rows = search_q.all()

            # Deal count per origin
            deal_q = db.session.query(
                Deal.origin,
                func.count(Deal.id).label("deal_count"),
            ).filter(
                Deal.is_active.is_(True),
                Deal.created_at >= cutoff,
            ).group_by(Deal.origin)
            deal_map = {r[0]: r[1] for r in deal_q.all()}

            data = []
            for row in search_rows:
                market = row[0]
                data.append({
                    "market": market,
                    "total_searches": row[1],
                    "avg_savings_pct": round(row[2], 1) if row[2] else 0,
                    "total_deals": deal_map.get(market, 0),
                    "period_days": max_days,
                })

            data.sort(key=lambda x: x["total_searches"], reverse=True)
            total = len(data)
            data = data[offset: offset + limit]
            return {"data": data, "total": total}
        except Exception:
            logger.exception("_query_market_briefings failed")
            return {"data": [], "total": 0}

    def _query_demand_signals(self, filters, limit, offset, max_days):
        """Search volume trends from SearchHistory."""
        try:
            cutoff = datetime.utcnow() - timedelta(days=max_days)
            q = db.session.query(
                SearchHistory.origin,
                SearchHistory.destination,
                func.count(SearchHistory.id).label("search_count"),
                func.avg(SearchHistory.best_price_usd).label("avg_best_price"),
            ).filter(SearchHistory.created_at >= cutoff)

            if filters.get("origin"):
                q = q.filter(SearchHistory.origin == filters["origin"].upper())
            if filters.get("destination"):
                q = q.filter(SearchHistory.destination == filters["destination"].upper())

            q = q.group_by(SearchHistory.origin, SearchHistory.destination)
            q = q.order_by(func.count(SearchHistory.id).desc())

            rows = q.all()
            total = len(rows)
            rows = rows[offset: offset + limit]

            data = []
            for r in rows:
                data.append({
                    "origin": r[0],
                    "destination": r[1],
                    "search_count": r[2],
                    "avg_best_price": round(r[3], 2) if r[3] else None,
                    "period_days": max_days,
                    # PRIVACY: no user_id
                })
            return {"data": data, "total": total}
        except Exception:
            logger.exception("_query_demand_signals failed")
            return {"data": [], "total": 0}

    def _query_competitor_pricing(self, filters, limit, offset, max_days):
        """Competitive pricing data from CompetitorPricing."""
        try:
            cutoff = datetime.utcnow() - timedelta(days=max_days)
            q = CompetitorPricing.query.filter(CompetitorPricing.calculated_at >= cutoff)

            if filters.get("origin"):
                q = q.filter(CompetitorPricing.origin == filters["origin"].upper())
            if filters.get("destination"):
                q = q.filter(CompetitorPricing.destination == filters["destination"].upper())
            if filters.get("market"):
                q = q.filter(CompetitorPricing.market == filters["market"].upper())
            if filters.get("airline_iata"):
                q = q.filter(CompetitorPricing.airline_iata == filters["airline_iata"].upper())

            q = q.order_by(CompetitorPricing.calculated_at.desc())
            total = q.count()
            rows = q.offset(offset).limit(limit).all()

            data = [r.to_dict() for r in rows]
            return {"data": data, "total": total}
        except Exception:
            logger.exception("_query_competitor_pricing failed")
            return {"data": [], "total": 0}

    # ------------------------------------------------------------------
    # Private query methods — SERP Intelligence
    # ------------------------------------------------------------------

    def _query_serp_results_feed(self, filters, limit, offset, max_days):
        """SERP results from SERPAPIQuery (no raw query text or results)."""
        try:
            cutoff = datetime.utcnow() - timedelta(days=max_days)
            q = SERPAPIQuery.query.filter(SERPAPIQuery.created_at >= cutoff)

            if filters.get("engine"):
                q = q.filter(SERPAPIQuery.engine == filters["engine"])
            if filters.get("market"):
                q = q.filter(SERPAPIQuery.market == filters["market"].upper())
            if filters.get("status"):
                q = q.filter(SERPAPIQuery.status == filters["status"])

            q = q.order_by(SERPAPIQuery.created_at.desc())
            total = q.count()
            rows = q.offset(offset).limit(limit).all()

            data = []
            for r in rows:
                data.append({
                    "engine": r.engine,
                    "market": r.market,
                    "status": r.status,
                    "credits_used": r.credits_used,
                    "response_time_ms": r.response_time_ms,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    # PRIVACY: no query_text, no raw result, no account_id
                })
            return {"data": data, "total": total}
        except Exception:
            logger.exception("_query_serp_results_feed failed")
            return {"data": [], "total": 0}

    def _query_serp_trends(self, filters, limit, offset, max_days):
        """Aggregated SERP trends from SERPAPIQuery."""
        try:
            cutoff = datetime.utcnow() - timedelta(days=max_days)
            q = db.session.query(
                cast(SERPAPIQuery.created_at, Date).label("period"),
                SERPAPIQuery.engine,
                SERPAPIQuery.market,
                func.count(SERPAPIQuery.id).label("query_count"),
                func.avg(SERPAPIQuery.response_time_ms).label("avg_response_time_ms"),
            ).filter(SERPAPIQuery.created_at >= cutoff)

            if filters.get("engine"):
                q = q.filter(SERPAPIQuery.engine == filters["engine"])
            if filters.get("market"):
                q = q.filter(SERPAPIQuery.market == filters["market"].upper())

            q = q.group_by("period", SERPAPIQuery.engine, SERPAPIQuery.market)
            q = q.order_by(func.count(SERPAPIQuery.id).desc())

            rows = q.all()
            total = len(rows)
            rows = rows[offset: offset + limit]

            # Calculate success rate per group
            data = []
            for r in rows:
                total_for_group = r[3] or 1
                success_q = SERPAPIQuery.query.filter(
                    cast(SERPAPIQuery.created_at, Date) == r[0],
                    SERPAPIQuery.engine == r[1],
                    SERPAPIQuery.market == r[2],
                    SERPAPIQuery.status == "completed",
                ).count()
                data.append({
                    "period": r[0].isoformat() if r[0] else None,
                    "engine": r[1],
                    "market": r[2],
                    "query_count": r[3],
                    "avg_response_time_ms": round(r[4], 1) if r[4] else None,
                    "success_rate": round(success_q / total_for_group * 100, 1),
                })
            return {"data": data, "total": total}
        except Exception:
            logger.exception("_query_serp_trends failed")
            return {"data": [], "total": 0}

    def _query_serp_geographic_variance(self, filters, limit, offset, max_days):
        """Cross-market SERP comparison."""
        try:
            cutoff = datetime.utcnow() - timedelta(days=max_days)
            q = db.session.query(
                SERPAPIQuery.market,
                SERPAPIQuery.engine,
                func.count(SERPAPIQuery.id).label("total_queries"),
                func.avg(SERPAPIQuery.response_time_ms).label("avg_response_time_ms"),
            ).filter(SERPAPIQuery.created_at >= cutoff)

            if filters.get("engine"):
                q = q.filter(SERPAPIQuery.engine == filters["engine"])

            q = q.group_by(SERPAPIQuery.market, SERPAPIQuery.engine)
            rows = q.all()

            data = []
            for r in rows:
                total_for_group = r[2] or 1
                success_count = SERPAPIQuery.query.filter(
                    SERPAPIQuery.market == r[0],
                    SERPAPIQuery.engine == r[1],
                    SERPAPIQuery.status == "completed",
                    SERPAPIQuery.created_at >= cutoff,
                ).count()
                data.append({
                    "market": r[0],
                    "engine": r[1],
                    "total_queries": r[2],
                    "avg_response_time_ms": round(r[3], 1) if r[3] else None,
                    "success_rate": round(success_count / total_for_group * 100, 1),
                })

            total = len(data)
            data = data[offset: offset + limit]
            return {"data": data, "total": total}
        except Exception:
            logger.exception("_query_serp_geographic_variance failed")
            return {"data": [], "total": 0}

    # ------------------------------------------------------------------
    # Private query methods — Ad Intelligence
    # ------------------------------------------------------------------

    def _query_ad_inventory_feed(self, filters, limit, offset, max_days):
        """Ad inventory data from AdIntelligenceRecord."""
        try:
            cutoff = datetime.utcnow() - timedelta(days=max_days)
            q = AdIntelligenceRecord.query.filter(AdIntelligenceRecord.observed_at >= cutoff)

            if filters.get("market"):
                q = q.filter(AdIntelligenceRecord.market == filters["market"].upper())
            if filters.get("advertiser"):
                q = q.filter(AdIntelligenceRecord.advertiser.ilike(f"%{filters['advertiser']}%"))
            if filters.get("ad_network"):
                q = q.filter(AdIntelligenceRecord.ad_network == filters["ad_network"])
            if filters.get("vertical"):
                q = q.filter(AdIntelligenceRecord.vertical == filters["vertical"])

            q = q.order_by(AdIntelligenceRecord.observed_at.desc())
            total = q.count()
            rows = q.offset(offset).limit(limit).all()

            data = []
            for r in rows:
                data.append({
                    "market": r.market,
                    "advertiser": r.advertiser,
                    "ad_network": r.ad_network,
                    "ad_format": r.ad_format,
                    "ad_position": r.ad_position,
                    "vertical": r.vertical,
                    "estimated_bid_usd": r.estimated_bid_usd,
                    "observed_at": r.observed_at.isoformat() if r.observed_at else None,
                    # PRIVACY: no source_url, no ad_destination_url, no node_user_id, no ad_text
                })
            return {"data": data, "total": total}
        except Exception:
            logger.exception("_query_ad_inventory_feed failed")
            return {"data": [], "total": 0}

    def _query_ad_competitor_reports(self, filters, limit, offset, max_days):
        """Aggregated competitor ad reports."""
        try:
            cutoff = datetime.utcnow() - timedelta(days=max_days)
            q = db.session.query(
                AdIntelligenceRecord.advertiser,
                AdIntelligenceRecord.market,
                AdIntelligenceRecord.vertical,
                func.count(AdIntelligenceRecord.id).label("total_ads"),
                func.avg(AdIntelligenceRecord.estimated_bid_usd).label("avg_bid_usd"),
            ).filter(
                AdIntelligenceRecord.observed_at >= cutoff,
                AdIntelligenceRecord.advertiser.isnot(None),
            )

            if filters.get("advertiser"):
                q = q.filter(AdIntelligenceRecord.advertiser.ilike(f"%{filters['advertiser']}%"))
            if filters.get("market"):
                q = q.filter(AdIntelligenceRecord.market == filters["market"].upper())
            if filters.get("vertical"):
                q = q.filter(AdIntelligenceRecord.vertical == filters["vertical"])

            q = q.group_by(
                AdIntelligenceRecord.advertiser,
                AdIntelligenceRecord.market,
                AdIntelligenceRecord.vertical,
            )
            q = q.order_by(func.count(AdIntelligenceRecord.id).desc())

            rows = q.all()
            total = len(rows)
            rows = rows[offset: offset + limit]

            data = []
            for r in rows:
                data.append({
                    "advertiser": r[0],
                    "market": r[1],
                    "vertical": r[2],
                    "total_ads": r[3],
                    "avg_bid_usd": round(r[4], 2) if r[4] else None,
                })
            return {"data": data, "total": total}
        except Exception:
            logger.exception("_query_ad_competitor_reports failed")
            return {"data": [], "total": 0}

    def _query_ad_market_trends(self, filters, limit, offset, max_days):
        """Ad market trend analysis."""
        try:
            cutoff = datetime.utcnow() - timedelta(days=max_days)
            q = db.session.query(
                cast(AdIntelligenceRecord.observed_at, Date).label("period"),
                AdIntelligenceRecord.market,
                AdIntelligenceRecord.vertical,
                func.count(AdIntelligenceRecord.id).label("total_ads"),
                func.avg(AdIntelligenceRecord.estimated_bid_usd).label("avg_bid_usd"),
            ).filter(AdIntelligenceRecord.observed_at >= cutoff)

            if filters.get("market"):
                q = q.filter(AdIntelligenceRecord.market == filters["market"].upper())
            if filters.get("vertical"):
                q = q.filter(AdIntelligenceRecord.vertical == filters["vertical"])

            q = q.group_by("period", AdIntelligenceRecord.market, AdIntelligenceRecord.vertical)
            q = q.order_by(func.count(AdIntelligenceRecord.id).desc())

            rows = q.all()
            total = len(rows)
            rows = rows[offset: offset + limit]

            data = []
            for r in rows:
                data.append({
                    "period": r[0].isoformat() if r[0] else None,
                    "market": r[1],
                    "vertical": r[2],
                    "total_ads": r[3],
                    "avg_bid_usd": round(r[4], 2) if r[4] else None,
                })
            return {"data": data, "total": total}
        except Exception:
            logger.exception("_query_ad_market_trends failed")
            return {"data": [], "total": 0}

    # ------------------------------------------------------------------
    # Private query methods — Browsing Intelligence
    # PRIVACY: domain + data_category + quality_score ONLY
    # ------------------------------------------------------------------

    def _query_browsing_event_stream(self, filters, limit, offset, max_days):
        """Browsing events — expose domain, data_category, quality_score ONLY."""
        try:
            cutoff = datetime.utcnow() - timedelta(days=max_days)
            q = BrowsingEvent.query.filter(BrowsingEvent.ingested_at >= cutoff)

            if filters.get("domain"):
                q = q.filter(BrowsingEvent.domain == filters["domain"])
            if filters.get("data_category"):
                q = q.filter(BrowsingEvent.data_category == filters["data_category"])
            if filters.get("event_type"):
                q = q.filter(BrowsingEvent.event_type == filters["event_type"])
            if filters.get("min_quality"):
                q = q.filter(BrowsingEvent.quality_score >= int(filters["min_quality"]))

            q = q.order_by(BrowsingEvent.ingested_at.desc())
            total = q.count()
            rows = q.offset(offset).limit(limit).all()

            data = []
            for r in rows:
                data.append({
                    "domain": r.domain,
                    "data_category": r.data_category,
                    "quality_score": r.quality_score,
                    "event_type": r.event_type,
                    "captured_at": r.captured_at.isoformat() if r.captured_at else None,
                    # PRIVACY: NO url, NO title, NO user_id, NO event_data, NO node_id
                })
            return {"data": data, "total": total}
        except Exception:
            logger.exception("_query_browsing_event_stream failed")
            return {"data": [], "total": 0}

    def _query_browsing_domain_reports(self, filters, limit, offset, max_days):
        """Aggregated domain-level browsing reports."""
        try:
            cutoff = datetime.utcnow() - timedelta(days=max_days)
            q = db.session.query(
                BrowsingEvent.domain,
                func.count(BrowsingEvent.id).label("total_events"),
                func.avg(BrowsingEvent.quality_score).label("avg_quality_score"),
            ).filter(
                BrowsingEvent.ingested_at >= cutoff,
                BrowsingEvent.domain.isnot(None),
            )

            if filters.get("domain"):
                q = q.filter(BrowsingEvent.domain == filters["domain"])
            if filters.get("data_category"):
                q = q.filter(BrowsingEvent.data_category == filters["data_category"])

            q = q.group_by(BrowsingEvent.domain)
            q = q.order_by(func.count(BrowsingEvent.id).desc())

            rows = q.all()
            total = len(rows)
            rows = rows[offset: offset + limit]

            data = []
            for r in rows:
                # Fetch category distribution for this domain
                cat_q = db.session.query(
                    BrowsingEvent.data_category,
                    func.count(BrowsingEvent.id),
                ).filter(
                    BrowsingEvent.domain == r[0],
                    BrowsingEvent.ingested_at >= cutoff,
                ).group_by(BrowsingEvent.data_category).all()

                evt_q = db.session.query(
                    BrowsingEvent.event_type,
                    func.count(BrowsingEvent.id),
                ).filter(
                    BrowsingEvent.domain == r[0],
                    BrowsingEvent.ingested_at >= cutoff,
                ).group_by(BrowsingEvent.event_type).all()

                data.append({
                    "domain": r[0],
                    "total_events": r[1],
                    "avg_quality_score": round(r[2], 1) if r[2] else None,
                    "top_categories": {c: cnt for c, cnt in cat_q if c},
                    "event_type_distribution": {e: cnt for e, cnt in evt_q if e},
                    # PRIVACY: NO urls, NO titles, NO user data
                })
            return {"data": data, "total": total}
        except Exception:
            logger.exception("_query_browsing_domain_reports failed")
            return {"data": [], "total": 0}

    def _query_browsing_trends(self, filters, limit, offset, max_days):
        """Browsing trend aggregations."""
        try:
            cutoff = datetime.utcnow() - timedelta(days=max_days)
            q = db.session.query(
                cast(BrowsingEvent.ingested_at, Date).label("period"),
                func.count(BrowsingEvent.id).label("total_events"),
                func.avg(BrowsingEvent.quality_score).label("avg_quality"),
            ).filter(BrowsingEvent.ingested_at >= cutoff)

            if filters.get("data_category"):
                q = q.filter(BrowsingEvent.data_category == filters["data_category"])

            q = q.group_by("period")
            q = q.order_by(cast(BrowsingEvent.ingested_at, Date).desc())

            rows = q.all()
            total = len(rows)
            rows = rows[offset: offset + limit]

            # Top domains for the period
            top_domains_q = db.session.query(
                BrowsingEvent.domain,
                func.count(BrowsingEvent.id).label("cnt"),
            ).filter(
                BrowsingEvent.ingested_at >= cutoff,
                BrowsingEvent.domain.isnot(None),
            ).group_by(BrowsingEvent.domain).order_by(
                func.count(BrowsingEvent.id).desc()
            ).limit(20).all()

            top_cats_q = db.session.query(
                BrowsingEvent.data_category,
                func.count(BrowsingEvent.id).label("cnt"),
            ).filter(
                BrowsingEvent.ingested_at >= cutoff,
                BrowsingEvent.data_category.isnot(None),
            ).group_by(BrowsingEvent.data_category).order_by(
                func.count(BrowsingEvent.id).desc()
            ).limit(20).all()

            data = []
            for r in rows:
                data.append({
                    "period": r[0].isoformat() if r[0] else None,
                    "total_events": r[1],
                    "avg_quality": round(r[2], 1) if r[2] else None,
                })

            return {
                "data": data,
                "total": total,
                "top_domains": {d: c for d, c in top_domains_q if d},
                "top_categories": {c: cnt for c, cnt in top_cats_q if c},
            }
        except Exception:
            logger.exception("_query_browsing_trends failed")
            return {"data": [], "total": 0}

    # ------------------------------------------------------------------
    # Private query methods — Network Intelligence
    # ------------------------------------------------------------------

    def _query_node_network_stats(self, filters, limit, offset, max_days):
        """Aggregated node network statistics from HelperProfile."""
        try:
            q = db.session.query(
                HelperProfile.country_code,
                func.count(HelperProfile.id).label("total_nodes"),
                func.sum(
                    func.cast(HelperProfile.is_active, db.Integer)
                ).label("active_nodes"),
                func.avg(HelperProfile.average_rating).label("avg_rating"),
            )

            if filters.get("country_code"):
                q = q.filter(HelperProfile.country_code == filters["country_code"].upper())
            if filters.get("is_active") is not None:
                q = q.filter(HelperProfile.is_active.is_(filters["is_active"] in (True, "true", "1")))

            q = q.group_by(HelperProfile.country_code)
            q = q.order_by(func.count(HelperProfile.id).desc())

            rows = q.all()
            total = len(rows)
            rows = rows[offset: offset + limit]

            data = []
            for r in rows:
                total_nodes = r[1] or 1
                active = r[2] or 0
                data.append({
                    "country_code": r[0],
                    "total_nodes": r[1],
                    "active_nodes": int(active),
                    "active_rate_pct": round(active / total_nodes * 100, 1),
                    "avg_rating": round(r[3], 2) if r[3] else None,
                    # PRIVACY: no user_id, no node_id, no helper_token
                })
            return {"data": data, "total": total}
        except Exception:
            logger.exception("_query_node_network_stats failed")
            return {"data": [], "total": 0}

    def _query_proxy_performance(self, filters, limit, offset, max_days):
        """Proxy performance metrics from HelperProfile."""
        try:
            q = db.session.query(
                HelperProfile.country_code,
                func.sum(HelperProfile.total_transactions).label("total_transactions"),
                func.sum(HelperProfile.successful_transactions).label("successful"),
                func.avg(HelperProfile.total_earned_rlusd).label("avg_earned_rlusd"),
            ).filter(HelperProfile.total_transactions > 0)

            if filters.get("country_code"):
                q = q.filter(HelperProfile.country_code == filters["country_code"].upper())

            q = q.group_by(HelperProfile.country_code)
            q = q.order_by(func.sum(HelperProfile.total_transactions).desc())

            rows = q.all()
            total = len(rows)
            rows = rows[offset: offset + limit]

            data = []
            for r in rows:
                total_tx = r[1] or 1
                successful = r[2] or 0
                data.append({
                    "country_code": r[0],
                    "total_transactions": r[1],
                    "success_rate": round(successful / total_tx * 100, 1),
                    "avg_earned_rlusd": round(r[3], 4) if r[3] else 0,
                    # PRIVACY: no user_id, no node_id
                })
            return {"data": data, "total": total}
        except Exception:
            logger.exception("_query_proxy_performance failed")
            return {"data": [], "total": 0}

    # ------------------------------------------------------------------
    # Exports
    # ------------------------------------------------------------------

    def request_export(self, account, product_id, fmt="csv", filters=None):
        """Create a bulk export request.

        Returns:
            dict with ``export_id`` and ``status``.
        """
        # Access check
        access = self.check_product_access(account, product_id)
        if not access["allowed"]:
            return {"error": access["reason"]}

        # CSV export requires professional+ tier
        sub = self._get_active_subscription(account)
        tier_key = sub.tier if sub else "data_free"
        tier_def = DATA_MARKETPLACE_TIERS.get(tier_key, {})
        if fmt == "csv" and not tier_def.get("csv"):
            return {"error": f"CSV export requires data_professional tier or above (current: {tier_key})"}

        export_id = f"EXP{secrets.token_hex(8).upper()}"
        try:
            export = DataExport(
                export_id=export_id,
                account_id=account.id,
                product_id=product_id,
                format=fmt,
                filters=json.dumps(filters) if filters else None,
                status="pending",
                expires_at=datetime.utcnow() + timedelta(hours=24),
            )
            db.session.add(export)
            db.session.commit()

            return {
                "export_id": export_id,
                "status": "pending",
                "product_id": product_id,
                "format": fmt,
                "message": "Export queued. Poll GET /api/v1/data/exports/<export_id> for status.",
            }
        except Exception:
            db.session.rollback()
            logger.exception("Failed to create export for account %s", account.id)
            return {"error": "Failed to create export request"}

    def get_export_status(self, export_id, account):
        """Check the status of an export request."""
        export = DataExport.query.filter_by(export_id=export_id, account_id=account.id).first()
        if not export:
            return None
        return export.to_dict()

    def process_export(self, export_id):
        """Background job: process an export request, generate file, set download_url."""
        export = DataExport.query.filter_by(export_id=export_id).first()
        if not export:
            logger.warning("Export %s not found", export_id)
            return

        export.status = "processing"
        export.started_at = datetime.utcnow()
        db.session.commit()

        try:
            # Resolve the account to get tier constraints
            account = CommercialAccount.query.get(export.account_id)
            sub = self._get_active_subscription(account) if account else None
            tier_key = sub.tier if sub else "data_free"
            tier_def = DATA_MARKETPLACE_TIERS.get(tier_key, {})
            max_days = tier_def.get("days", 7)

            filters = json.loads(export.filters) if export.filters else {}

            method_name = f"_query_{export.product_id}"
            method = getattr(self, method_name, None)
            if method is None:
                raise ValueError(f"No query handler for {export.product_id}")

            # Query with a large limit for export
            result = method(filters, limit=50_000, offset=0, max_days=max_days)
            data = result.get("data", [])

            # Generate file
            export_dir = os.path.join(tempfile.gettempdir(), "mystes_exports")
            os.makedirs(export_dir, exist_ok=True)

            if export.format == "csv" and data:
                filepath = os.path.join(export_dir, f"{export_id}.csv")
                with open(filepath, "w", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=data[0].keys())
                    writer.writeheader()
                    writer.writerows(data)
            else:
                filepath = os.path.join(export_dir, f"{export_id}.json")
                with open(filepath, "w") as f:
                    json.dump(data, f, indent=2, default=str)

            file_size = os.path.getsize(filepath)

            export.status = "completed"
            export.completed_at = datetime.utcnow()
            export.total_records = len(data)
            export.file_size_bytes = file_size
            export.download_url = f"/exports/{export_id}.{export.format}"
            db.session.commit()

            logger.info("Export %s completed: %d records, %d bytes", export_id, len(data), file_size)

        except Exception as exc:
            export.status = "failed"
            export.error_message = str(exc)[:500]
            export.completed_at = datetime.utcnow()
            db.session.commit()
            logger.exception("Export %s failed", export_id)

    # ------------------------------------------------------------------
    # Webhooks
    # ------------------------------------------------------------------

    def create_webhook(self, account, product_id, callback_url, filters=None):
        """Create a webhook subscription for *product_id*.

        Returns:
            dict with ``webhook_id`` and ``secret``.
        """
        # Enterprise tier required
        sub = self._get_active_subscription(account)
        tier_key = sub.tier if sub else "data_free"
        tier_def = DATA_MARKETPLACE_TIERS.get(tier_key, {})
        if not tier_def.get("webhooks"):
            return {"error": f"Webhooks require data_enterprise tier (current: {tier_key})"}

        # Validate product
        access = self.check_product_access(account, product_id)
        if not access["allowed"]:
            return {"error": access["reason"]}

        webhook_id = f"WH{secrets.token_hex(8).upper()}"
        webhook_secret = secrets.token_hex(32)

        try:
            wh = DataWebhook(
                webhook_id=webhook_id,
                account_id=account.id,
                product_id=product_id,
                callback_url=callback_url,
                secret=webhook_secret,
                filters=json.dumps(filters) if filters else None,
                is_active=True,
            )
            db.session.add(wh)
            db.session.commit()

            return {
                "webhook_id": webhook_id,
                "secret": webhook_secret,
                "product_id": product_id,
                "callback_url": callback_url,
                "message": "Webhook created. Store the secret — it will not be shown again.",
            }
        except Exception:
            db.session.rollback()
            logger.exception("Failed to create webhook for account %s", account.id)
            return {"error": "Failed to create webhook"}

    def delete_webhook(self, webhook_id, account):
        """Delete (deactivate) a webhook subscription."""
        wh = DataWebhook.query.filter_by(webhook_id=webhook_id, account_id=account.id).first()
        if not wh:
            return {"error": "Webhook not found"}

        wh.is_active = False
        try:
            db.session.commit()
            return {"webhook_id": webhook_id, "status": "deleted"}
        except Exception:
            db.session.rollback()
            return {"error": "Failed to delete webhook"}

    def list_webhooks(self, account):
        """List all webhooks for *account*."""
        webhooks = DataWebhook.query.filter_by(account_id=account.id, is_active=True).all()
        return {
            "webhooks": [wh.to_dict() for wh in webhooks],
            "total": len(webhooks),
        }

    def deliver_webhook(self, webhook_id, payload):
        """Deliver *payload* to a webhook URL with HMAC-SHA256 signature.

        Disables the webhook after 5 consecutive failures.
        """
        wh = DataWebhook.query.filter_by(webhook_id=webhook_id, is_active=True).first()
        if not wh:
            logger.warning("Webhook %s not found or inactive", webhook_id)
            return

        body = json.dumps(payload, default=str)
        signature = hmac.new(
            wh.secret.encode("utf-8"),
            body.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        headers = {
            "Content-Type": "application/json",
            "X-Mystes-Signature": signature,
            "X-Mystes-Webhook-Id": webhook_id,
        }

        try:
            resp = http_requests.post(
                wh.callback_url,
                data=body,
                headers=headers,
                timeout=10,
            )
            wh.last_delivery_at = datetime.utcnow()
            wh.last_delivery_status = resp.status_code
            wh.total_deliveries = (wh.total_deliveries or 0) + 1

            if 200 <= resp.status_code < 300:
                wh.consecutive_failures = 0
            else:
                wh.consecutive_failures = (wh.consecutive_failures or 0) + 1
                logger.warning(
                    "Webhook %s delivery returned %d (failures: %d)",
                    webhook_id, resp.status_code, wh.consecutive_failures,
                )
        except Exception as exc:
            wh.consecutive_failures = (wh.consecutive_failures or 0) + 1
            wh.last_delivery_at = datetime.utcnow()
            logger.warning("Webhook %s delivery failed: %s (failures: %d)", webhook_id, exc, wh.consecutive_failures)

        # Disable after 5 consecutive failures
        if (wh.consecutive_failures or 0) >= 5:
            wh.is_active = False
            logger.warning("Webhook %s disabled after 5 consecutive failures", webhook_id)

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()

    # ------------------------------------------------------------------
    # AI Benchmark Report
    # ------------------------------------------------------------------

    def generate_ai_benchmark_report(self, period_days=30):
        """Generate the MYSTES AI Index monthly report.

        Includes provider rankings, category breakdown, response time
        distributions, quality scores, strategy effectiveness, monthly
        trends, and a composite MYSTES AI Index score.
        """
        cutoff = datetime.utcnow() - timedelta(days=period_days)

        try:
            # --- Provider Rankings (win rates) ---
            provider_q = db.session.query(
                AISearchQuery.best_provider,
                func.count(AISearchQuery.id).label("wins"),
                func.avg(AISearchQuery.response_time_ms).label("avg_rt"),
            ).filter(
                AISearchQuery.created_at >= cutoff,
                AISearchQuery.best_provider.isnot(None),
            ).group_by(AISearchQuery.best_provider).all()

            total_queries = sum(r[1] for r in provider_q) or 1
            provider_rankings = []
            for r in provider_q:
                provider_rankings.append({
                    "provider": r[0],
                    "wins": r[1],
                    "win_rate": round(r[1] / total_queries * 100, 2),
                    "avg_response_time_ms": round(r[2], 1) if r[2] else None,
                })
            provider_rankings.sort(key=lambda x: x["win_rate"], reverse=True)

            # --- Response Time Distributions ---
            rt_rows = db.session.query(AISearchQuery.response_time_ms).filter(
                AISearchQuery.created_at >= cutoff,
                AISearchQuery.response_time_ms.isnot(None),
            ).all()
            rt_values = sorted([r[0] for r in rt_rows if r[0]])
            rt_distribution = {}
            if rt_values:
                rt_distribution = {
                    "p50": rt_values[len(rt_values) // 2],
                    "p90": rt_values[int(len(rt_values) * 0.9)],
                    "p99": rt_values[int(len(rt_values) * 0.99)],
                    "mean": round(statistics.mean(rt_values), 1),
                }

            # --- Strategy Effectiveness ---
            strategies = StrategyInsight.query.filter(
                StrategyInsight.is_active.is_(True),
                StrategyInsight.created_at >= cutoff,
            ).order_by(StrategyInsight.effectiveness_score.desc()).limit(20).all()

            strategy_rankings = []
            for s in strategies:
                strategy_rankings.append({
                    "category": s.category,
                    "insight_type": s.insight_type,
                    "effectiveness_score": round(s.effectiveness_score, 3),
                    "confidence": round(s.confidence_score, 3),
                    "observations": s.observation_count,
                })

            # --- Monthly Trends (daily aggregation) ---
            daily_q = db.session.query(
                cast(AISearchQuery.created_at, Date).label("day"),
                func.count(AISearchQuery.id).label("queries"),
                func.avg(AISearchQuery.response_time_ms).label("avg_rt"),
            ).filter(
                AISearchQuery.created_at >= cutoff,
            ).group_by("day").order_by("day").all()

            monthly_trends = []
            for r in daily_q:
                monthly_trends.append({
                    "date": r[0].isoformat() if r[0] else None,
                    "queries": r[1],
                    "avg_response_time_ms": round(r[2], 1) if r[2] else None,
                })

            # --- Composite MYSTES AI Index ---
            # Weighted score: 40% win-rate spread, 30% response time, 30% strategy effectiveness
            top_win_rate = provider_rankings[0]["win_rate"] if provider_rankings else 0
            avg_rt = rt_distribution.get("mean", 5000)
            avg_effectiveness = (
                statistics.mean([s["effectiveness_score"] for s in strategy_rankings])
                if strategy_rankings else 0
            )

            # Normalize: win_rate out of 100, rt inversely (lower=better, max 10s), effectiveness out of 100
            win_component = min(top_win_rate, 100)
            rt_component = max(0, 100 - (avg_rt / 100))  # 0ms=100, 10000ms=0
            eff_component = min(avg_effectiveness * 100, 100)

            mystes_ai_index = round(
                0.4 * win_component + 0.3 * rt_component + 0.3 * eff_component, 2
            )

            return {
                "report_type": "mystes_ai_index",
                "period_days": period_days,
                "generated_at": datetime.utcnow().isoformat(),
                "total_queries_analyzed": total_queries,
                "provider_rankings": provider_rankings,
                "response_time_distribution": rt_distribution,
                "strategy_effectiveness": strategy_rankings,
                "monthly_trends": monthly_trends,
                "mystes_ai_index": mystes_ai_index,
            }
        except Exception:
            logger.exception("generate_ai_benchmark_report failed")
            return {
                "report_type": "mystes_ai_index",
                "error": "Report generation failed",
                "generated_at": datetime.utcnow().isoformat(),
            }

    # ------------------------------------------------------------------
    # Admin Dashboard
    # ------------------------------------------------------------------

    def get_admin_dashboard_data(self):
        """Dashboard data: revenue, subscribers, top products, usage trends."""
        try:
            now = datetime.utcnow()
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

            # Active subscriptions
            total_subs = DataSubscription.query.filter_by(status="active").count()

            # Revenue (sum of monthly_price_usd for active subs)
            monthly_revenue = db.session.query(
                func.coalesce(func.sum(DataSubscription.monthly_price_usd), 0)
            ).filter(DataSubscription.status == "active").scalar()

            # Tier breakdown
            tier_breakdown = db.session.query(
                DataSubscription.tier,
                func.count(DataSubscription.id),
            ).filter(DataSubscription.status == "active").group_by(DataSubscription.tier).all()

            # Top products by usage this month
            top_products_q = db.session.query(
                DataUsageRecord.product_id,
                func.count(DataUsageRecord.id).label("query_count"),
                func.sum(DataUsageRecord.credits_consumed).label("total_credits"),
            ).filter(
                DataUsageRecord.created_at >= month_start,
            ).group_by(DataUsageRecord.product_id).order_by(
                func.count(DataUsageRecord.id).desc()
            ).limit(10).all()

            top_products = []
            for r in top_products_q:
                meta = PRODUCT_CATALOG.get(r[0], {})
                top_products.append({
                    "product_id": r[0],
                    "name": meta.get("name", r[0]),
                    "query_count": r[1],
                    "total_credits": round(r[2], 2) if r[2] else 0,
                })

            # Usage trend (last 30 days, daily)
            cutoff_30d = now - timedelta(days=30)
            daily_usage = db.session.query(
                cast(DataUsageRecord.created_at, Date).label("day"),
                func.count(DataUsageRecord.id).label("queries"),
            ).filter(
                DataUsageRecord.created_at >= cutoff_30d,
            ).group_by("day").order_by("day").all()

            return {
                "total_active_subscriptions": total_subs,
                "monthly_revenue_usd": round(float(monthly_revenue), 2),
                "tier_breakdown": {t: c for t, c in tier_breakdown},
                "top_products": top_products,
                "daily_usage_30d": [
                    {"date": r[0].isoformat() if r[0] else None, "queries": r[1]}
                    for r in daily_usage
                ],
                "generated_at": now.isoformat(),
            }
        except Exception:
            logger.exception("get_admin_dashboard_data failed")
            return {"error": "Dashboard data generation failed"}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_active_subscription(self, account):
        """Return the active DataSubscription for *account*, or None."""
        if account is None:
            return None
        try:
            return DataSubscription.query.filter_by(
                account_id=account.id,
                status="active",
            ).first()
        except Exception:
            return None


# ===========================================================================
# Module-level singleton
# ===========================================================================

data_marketplace = DataMarketplaceEngine()


# ===========================================================================
# Route registration
# ===========================================================================

def register_data_marketplace_routes(app):
    """Register all data marketplace API routes on the Flask app."""
    from commercial_auth import require_api_key

    # ------------------------------------------------------------------
    # Public endpoints (no auth)
    # ------------------------------------------------------------------

    @app.route("/api/v1/data/catalog", methods=["GET"])
    def data_marketplace_catalog():
        """Public catalog — list all data products, optionally filtered by category."""
        category = request.args.get("category")
        return jsonify(data_marketplace.get_catalog(category=category))

    @app.route("/api/v1/data/pricing", methods=["GET"])
    def data_marketplace_pricing():
        """Public pricing — tier definitions and addon pricing."""
        return jsonify(data_marketplace.get_pricing())

    @app.route("/api/v1/data/<product_id>/sample", methods=["GET"])
    def data_marketplace_sample(product_id):
        """Public sample — free 10-row sample for any product."""
        result = data_marketplace.get_sample(product_id)
        if "error" in result:
            return jsonify(result), 404
        return jsonify(result)

    # ------------------------------------------------------------------
    # Authenticated endpoints (API key required, scope: data_marketplace)
    # ------------------------------------------------------------------

    @app.route("/api/v1/data/<product_id>", methods=["GET"])
    @require_api_key(scope="data_marketplace")
    def data_marketplace_query(product_id):
        """Query a data product. Requires data_marketplace API key scope."""
        account = g.commercial_account
        filters = {}
        for key in request.args:
            if key not in ("limit", "offset"):
                filters[key] = request.args.get(key)

        limit = min(int(request.args.get("limit", 100)), 10_000)
        offset = int(request.args.get("offset", 0))

        result = data_marketplace.query_product(
            account, product_id, filters=filters, limit=limit, offset=offset,
        )

        if isinstance(result, tuple):
            return jsonify(result[0]), result[1]
        return jsonify(result)

    @app.route("/api/v1/data/export", methods=["POST"])
    @require_api_key(scope="data_marketplace")
    def data_marketplace_export():
        """Request a bulk export (CSV or JSON)."""
        account = g.commercial_account
        data = request.get_json()
        if not data or not data.get("product_id"):
            return jsonify({"error": "product_id required"}), 400

        result = data_marketplace.request_export(
            account,
            product_id=data["product_id"],
            fmt=data.get("format", "csv"),
            filters=data.get("filters"),
        )

        if "error" in result:
            return jsonify(result), 400
        return jsonify(result), 202

    @app.route("/api/v1/data/exports/<export_id>", methods=["GET"])
    @require_api_key(scope="data_marketplace")
    def data_marketplace_export_status(export_id):
        """Check export status."""
        account = g.commercial_account
        result = data_marketplace.get_export_status(export_id, account)
        if result is None:
            return jsonify({"error": "Export not found"}), 404
        return jsonify(result)

    @app.route("/api/v1/data/webhook", methods=["POST"])
    @require_api_key(scope="data_marketplace")
    def data_marketplace_create_webhook():
        """Create a webhook subscription."""
        account = g.commercial_account
        data = request.get_json()
        if not data or not data.get("product_id") or not data.get("callback_url"):
            return jsonify({"error": "product_id and callback_url required"}), 400

        result = data_marketplace.create_webhook(
            account,
            product_id=data["product_id"],
            callback_url=data["callback_url"],
            filters=data.get("filters"),
        )

        if "error" in result:
            return jsonify(result), 400
        return jsonify(result), 201

    @app.route("/api/v1/data/webhook/<webhook_id>", methods=["DELETE"])
    @require_api_key(scope="data_marketplace")
    def data_marketplace_delete_webhook(webhook_id):
        """Delete a webhook subscription."""
        account = g.commercial_account
        result = data_marketplace.delete_webhook(webhook_id, account)
        if "error" in result:
            return jsonify(result), 404
        return jsonify(result)

    @app.route("/api/v1/data/webhooks", methods=["GET"])
    @require_api_key(scope="data_marketplace")
    def data_marketplace_list_webhooks():
        """List all active webhooks for the authenticated account."""
        account = g.commercial_account
        return jsonify(data_marketplace.list_webhooks(account))

    @app.route("/api/v1/data/usage", methods=["GET"])
    @require_api_key(scope="data_marketplace")
    def data_marketplace_usage():
        """Return usage stats for the authenticated account."""
        account = g.commercial_account
        days = int(request.args.get("days", 30))
        cutoff = datetime.utcnow() - timedelta(days=days)

        try:
            # Total queries
            total_queries = DataUsageRecord.query.filter(
                DataUsageRecord.account_id == account.id,
                DataUsageRecord.created_at >= cutoff,
            ).count()

            # Total credits
            total_credits = db.session.query(
                func.coalesce(func.sum(DataUsageRecord.credits_consumed), 0)
            ).filter(
                DataUsageRecord.account_id == account.id,
                DataUsageRecord.created_at >= cutoff,
            ).scalar()

            # Per-product breakdown
            product_usage = db.session.query(
                DataUsageRecord.product_id,
                func.count(DataUsageRecord.id).label("queries"),
                func.sum(DataUsageRecord.credits_consumed).label("credits"),
                func.sum(DataUsageRecord.records_returned).label("records"),
            ).filter(
                DataUsageRecord.account_id == account.id,
                DataUsageRecord.created_at >= cutoff,
            ).group_by(DataUsageRecord.product_id).all()

            # Quota info
            quota = data_marketplace.check_quota(account)

            return jsonify({
                "period_days": days,
                "total_queries": total_queries,
                "total_credits": round(float(total_credits), 2),
                "quota": quota,
                "by_product": [
                    {
                        "product_id": r[0],
                        "queries": r[1],
                        "credits": round(r[2], 2) if r[2] else 0,
                        "records": r[3] or 0,
                    }
                    for r in product_usage
                ],
            })
        except Exception:
            logger.exception("Usage stats failed for account %s", account.id)
            return jsonify({"error": "Failed to fetch usage stats"}), 500

    @app.route("/api/v1/data/ai-benchmark-report", methods=["GET"])
    @require_api_key(scope="data_marketplace")
    def data_marketplace_ai_benchmark_report():
        """Generate the MYSTES AI Index benchmark report.

        Requires the ai_benchmarking addon on the account's subscription.
        """
        account = g.commercial_account

        # Check addon access
        sub = data_marketplace._get_active_subscription(account)
        if sub is None:
            return jsonify({"error": "No active data marketplace subscription"}), 403

        addons = json.loads(sub.addons) if sub.addons else []
        if AI_BENCHMARK_ADDON["key"] not in addons:
            return jsonify({
                "error": "AI Benchmarking add-on required",
                "addon": AI_BENCHMARK_ADDON,
            }), 403

        period_days = int(request.args.get("period_days", 30))
        period_days = min(max(period_days, 7), 365)

        report = data_marketplace.generate_ai_benchmark_report(period_days=period_days)
        return jsonify(report)

    logger.info("Data Marketplace routes registered")
