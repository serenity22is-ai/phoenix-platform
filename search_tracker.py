"""
MYSTES Search History & Price Tracking

Records search results for analytics, re-search, and historical price trends.
Integrates with the search pipeline to capture data automatically.

Usage:
    from search_tracker import tracker

    # Record a completed search
    tracker.record_search(
        user_id=1,
        origin="JFK", destination="NRT",
        departure_date="2026-03-15",
        results=search_results,
        method="hybrid",
        duration_ms=4500,
    )

    # Query price history
    history = tracker.get_price_history("JFK", "NRT", "2026-03-15")

    # Get user's recent searches
    recent = tracker.get_recent_searches(user_id=1, limit=20)

    # Price trend for a route
    trend = tracker.get_price_trend("JFK", "NRT", days=30)
"""

import json
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class SearchTracker:
    """Records and queries search history and price snapshots."""

    def record_search(self, user_id, origin, destination, departure_date,
                      results, cabin_class="economy", return_date=None,
                      method=None, duration_ms=None, markets_searched=None):
        """
        Record a search and extract price snapshots from results.

        Args:
            results: List of flight result dicts from the search pipeline.
                     Each should have at minimum: price_usd, market.
        """
        try:
            from models import db, SearchHistory, PriceHistory

            # Parse date if string
            if isinstance(departure_date, str):
                departure_date = date.fromisoformat(departure_date)
            if isinstance(return_date, str):
                return_date = date.fromisoformat(return_date)

            # Summarize results
            best_price = None
            best_market = None
            us_price = None
            for r in (results or []):
                price = r.get("price_usd") or r.get("price")
                if price is None:
                    continue
                price = float(price)
                mkt = r.get("market", "US")

                if mkt == "US":
                    us_price = price
                if best_price is None or price < best_price:
                    best_price = price
                    best_market = mkt

            savings_usd = None
            savings_pct = None
            if us_price and best_price and us_price > best_price:
                savings_usd = round(us_price - best_price, 2)
                savings_pct = round((savings_usd / us_price) * 100, 1)

            # Create search history record
            sh = SearchHistory(
                user_id=user_id,
                origin=origin.upper(),
                destination=destination.upper(),
                departure_date=departure_date,
                return_date=return_date,
                cabin_class=cabin_class,
                results_count=len(results or []),
                best_price_usd=best_price,
                best_market=best_market,
                us_price_usd=us_price,
                max_savings_usd=savings_usd,
                max_savings_percent=savings_pct,
                search_method=method,
                search_duration_ms=duration_ms,
                markets_searched=json.dumps(markets_searched) if markets_searched else None,
            )
            db.session.add(sh)

            # Record individual price snapshots
            seen = set()  # Avoid duplicates for same market+airline
            for r in (results or []):
                price = r.get("price_usd") or r.get("price")
                mkt = r.get("market", "US")
                airline = r.get("airline", "")
                key = (mkt, airline)
                if price is None or key in seen:
                    continue
                seen.add(key)

                ph = PriceHistory(
                    origin=origin.upper(),
                    destination=destination.upper(),
                    departure_date=departure_date,
                    cabin_class=cabin_class,
                    market=mkt,
                    price_usd=float(price),
                    price_local=r.get("price_local"),
                    local_currency=r.get("currency"),
                    airline=airline[:50] if airline else None,
                    source=method,
                )
                db.session.add(ph)

            db.session.commit()
            logger.debug(
                f"Recorded search: {origin}-{destination} {departure_date} "
                f"({len(results or [])} results, best=${best_price})"
            )
        except Exception as e:
            logger.error(f"Failed to record search: {e}")
            try:
                from models import db
                db.session.rollback()
            except Exception:
                pass

    def get_recent_searches(self, user_id, limit=20):
        """Get a user's recent searches."""
        try:
            from models import SearchHistory
            searches = (
                SearchHistory.query
                .filter_by(user_id=user_id)
                .order_by(SearchHistory.created_at.desc())
                .limit(limit)
                .all()
            )
            return [s.to_dict() for s in searches]
        except Exception as e:
            logger.error(f"Failed to get recent searches: {e}")
            return []

    def get_popular_routes(self, days=7, limit=10):
        """Get the most searched routes in the last N days."""
        try:
            from models import db, SearchHistory
            cutoff = datetime.utcnow() - timedelta(days=days)
            results = (
                db.session.query(
                    SearchHistory.origin,
                    SearchHistory.destination,
                    db.func.count(SearchHistory.id).label("search_count"),
                    db.func.avg(SearchHistory.best_price_usd).label("avg_best_price"),
                    db.func.avg(SearchHistory.max_savings_percent).label("avg_savings_pct"),
                )
                .filter(SearchHistory.created_at >= cutoff)
                .group_by(SearchHistory.origin, SearchHistory.destination)
                .order_by(db.text("search_count DESC"))
                .limit(limit)
                .all()
            )
            return [
                {
                    "origin": r.origin,
                    "destination": r.destination,
                    "search_count": r.search_count,
                    "avg_best_price": round(r.avg_best_price, 2) if r.avg_best_price else None,
                    "avg_savings_pct": round(r.avg_savings_pct, 1) if r.avg_savings_pct else None,
                }
                for r in results
            ]
        except Exception as e:
            logger.error(f"Failed to get popular routes: {e}")
            return []

    def get_price_history(self, origin, destination, departure_date,
                          market=None, days_back=30):
        """Get historical price snapshots for a route."""
        try:
            from models import PriceHistory
            query = PriceHistory.query.filter_by(
                origin=origin.upper(),
                destination=destination.upper(),
            )

            if isinstance(departure_date, str):
                departure_date = date.fromisoformat(departure_date)
            query = query.filter_by(departure_date=departure_date)

            if market:
                query = query.filter_by(market=market.upper())

            cutoff = datetime.utcnow() - timedelta(days=days_back)
            query = query.filter(PriceHistory.recorded_at >= cutoff)

            records = query.order_by(PriceHistory.recorded_at.asc()).all()
            return [r.to_dict() for r in records]
        except Exception as e:
            logger.error(f"Failed to get price history: {e}")
            return []

    def get_price_trend(self, origin, destination, days=30, cabin_class="economy"):
        """
        Get aggregated price trend for a route across all departure dates.

        Returns daily average prices per market.
        """
        try:
            from models import db, PriceHistory
            cutoff = datetime.utcnow() - timedelta(days=days)

            results = (
                db.session.query(
                    db.func.date(PriceHistory.recorded_at).label("day"),
                    PriceHistory.market,
                    db.func.avg(PriceHistory.price_usd).label("avg_price"),
                    db.func.min(PriceHistory.price_usd).label("min_price"),
                    db.func.count(PriceHistory.id).label("samples"),
                )
                .filter(
                    PriceHistory.origin == origin.upper(),
                    PriceHistory.destination == destination.upper(),
                    PriceHistory.cabin_class == cabin_class,
                    PriceHistory.recorded_at >= cutoff,
                )
                .group_by(db.func.date(PriceHistory.recorded_at), PriceHistory.market)
                .order_by(db.text("day ASC"))
                .all()
            )

            trend = {}
            for r in results:
                day_str = str(r.day)
                if day_str not in trend:
                    trend[day_str] = {}
                trend[day_str][r.market] = {
                    "avg_price": round(r.avg_price, 2),
                    "min_price": round(r.min_price, 2),
                    "samples": r.samples,
                }

            return trend
        except Exception as e:
            logger.error(f"Failed to get price trend: {e}")
            return {}

    def get_route_stats(self, origin, destination, days=30):
        """Get summary statistics for a route."""
        try:
            from models import db, PriceHistory
            cutoff = datetime.utcnow() - timedelta(days=days)

            results = (
                db.session.query(
                    PriceHistory.market,
                    db.func.avg(PriceHistory.price_usd).label("avg_price"),
                    db.func.min(PriceHistory.price_usd).label("min_price"),
                    db.func.max(PriceHistory.price_usd).label("max_price"),
                    db.func.count(PriceHistory.id).label("samples"),
                )
                .filter(
                    PriceHistory.origin == origin.upper(),
                    PriceHistory.destination == destination.upper(),
                    PriceHistory.recorded_at >= cutoff,
                )
                .group_by(PriceHistory.market)
                .all()
            )

            markets = {}
            for r in results:
                markets[r.market] = {
                    "avg_price": round(r.avg_price, 2),
                    "min_price": round(r.min_price, 2),
                    "max_price": round(r.max_price, 2),
                    "samples": r.samples,
                }

            return {
                "origin": origin.upper(),
                "destination": destination.upper(),
                "days": days,
                "markets": markets,
            }
        except Exception as e:
            logger.error(f"Failed to get route stats: {e}")
            return {}


# Global tracker instance
tracker = SearchTracker()
