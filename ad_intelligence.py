"""
Ad Intelligence Pipeline — Phoenix Platform

Highest-value data extraction pipeline for the Phoenix proxy arbitrage engine.
Processes AD_INTELLIGENCE and COMPETITOR_AD_TRACK task results from CitizenSERP
nodes, normalizes ad data, aggregates across nodes for market-level intelligence,
and feeds into a commercial API for data buyers.

Pipeline flow:
    CitizenSERP Node -> Task Result -> ingest_task_result() -> normalize ->
    AdIntelligenceRecord (DB) -> query_ads / get_ad_trends / get_competitor_report
    -> Commercial API -> Data Buyers

Revenue model:
    - Per-record commercial value based on ad format
    - Tiered subscription access (starter / growth / enterprise)
    - Competitor intelligence reports as premium product
"""

import logging
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlparse
from typing import Dict, List, Optional, Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AD_DATA_VALUES = {
    "search_ad": 0.005,
    "shopping_ad": 0.008,
    "display_ad": 0.003,
    "video_ad": 0.010,
    "native_ad": 0.004,
    "competitor_ad": 0.012,
}

VERTICAL_KEYWORDS = {
    "travel": ["flight", "hotel", "cruise", "vacation", "airline", "booking"],
    "finance": ["bank", "loan", "credit", "insurance", "invest", "mortgage"],
    "ecommerce": ["buy", "shop", "deal", "discount", "sale", "price"],
    "technology": ["software", "app", "cloud", "saas", "tech", "computer"],
    "healthcare": ["health", "medical", "pharmacy", "doctor", "insurance"],
    "automotive": ["car", "auto", "vehicle", "dealer", "lease"],
    "education": ["course", "degree", "university", "learn", "training"],
    "real_estate": ["home", "property", "rent", "apartment", "realty"],
}

AD_INTEL_TIERS = {
    "ad_intel_starter": {
        "name": "Ad Intel Starter",
        "price_usd_monthly": 500,
        "queries_per_month": 1000,
        "markets": 3,
        "verticals": 2,
        "description": "Entry-level ad intelligence for small teams",
    },
    "ad_intel_growth": {
        "name": "Ad Intel Growth",
        "price_usd_monthly": 2000,
        "queries_per_month": 10000,
        "markets": 10,
        "verticals": "all",
        "description": "Scaled ad intelligence for growing businesses",
    },
    "ad_intel_enterprise": {
        "name": "Ad Intel Enterprise",
        "price_usd_monthly": 10000,
        "queries_per_month": "unlimited",
        "markets": "all",
        "verticals": "all",
        "description": "Full-access ad intelligence for enterprise data buyers",
    },
}

BID_ESTIMATES = {
    "base_cpc": {
        "search_top": 4.00,
        "search_other": 2.00,
        "shopping": 1.50,
        "display": 0.50,
        "native": 0.80,
        "video": 3.00,
    },
    "market_multipliers": {
        "US": 1.0,
        "UK": 0.9,
        "DE": 0.85,
        "JP": 0.95,
        "AU": 0.85,
        "FR": 0.80,
        "CA": 0.90,
    },
    "default_multiplier": 0.70,
}


# ---------------------------------------------------------------------------
# AdIntelligenceEngine
# ---------------------------------------------------------------------------

class AdIntelligenceEngine:
    """Core engine for ad intelligence data ingestion, normalization, and querying.

    Processes raw task results from CitizenSERP nodes, creates normalized
    AdIntelligenceRecord entries, and exposes query/analytics methods consumed
    by the commercial API layer.
    """

    def __init__(self):
        self.logger = logging.getLogger("phoenix.ad_intelligence")
        self.logger.info("AdIntelligenceEngine initialized")

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def ingest_task_result(self, task: Dict, result: Dict) -> Dict:
        """Ingest a completed AD_INTELLIGENCE or COMPETITOR_AD_TRACK task result.

        Validates the task type, extracts raw ad records from the result payload,
        normalizes each record, bulk-creates AdIntelligenceRecord rows, and logs
        a single NodeDataExtraction for the task.

        Args:
            task: Task metadata dict with keys task_id, task_type, market,
                  node_user_id, source_url, etc.
            result: Raw result payload from the CitizenSERP node containing
                    data.results list.

        Returns:
            Summary dict with ingested count, records_created, and
            commercial_value_usd.
        """
        from models import db, AdIntelligenceRecord, NodeDataExtraction

        task_type = task.get("task_type", "")
        if task_type not in ("ad_intelligence", "competitor_ad_track"):
            self.logger.warning(
                "Unsupported task_type '%s' for ad intelligence pipeline", task_type
            )
            return {"ingested": 0, "records_created": 0, "commercial_value_usd": 0.0}

        task_id = task.get("task_id", "unknown")
        market = task.get("market", "US")
        node_user_id = task.get("node_user_id", 0)
        source_url = task.get("source_url", "")

        raw_ads = result.get("data", {}).get("results", [])
        if not raw_ads:
            self.logger.info("Task %s returned zero ad results", task_id)
            return {"ingested": 0, "records_created": 0, "commercial_value_usd": 0.0}

        normalized_records: List[Dict] = []
        total_commercial_value = 0.0

        for raw in raw_ads:
            try:
                record_data = self._normalize_ad_record(
                    raw=raw,
                    market=market,
                    task_id=task_id,
                    node_user_id=node_user_id,
                )
                record_data["source_url"] = source_url
                normalized_records.append(record_data)
                total_commercial_value += record_data.get("commercial_value_usd", 0.0)
            except Exception as exc:
                self.logger.error(
                    "Failed to normalize ad record in task %s: %s", task_id, exc
                )

        records_created = 0
        try:
            for rec in normalized_records:
                ad_record = AdIntelligenceRecord(**rec)
                db.session.add(ad_record)
                records_created += 1

            # Create a single NodeDataExtraction for the whole task
            data_category = (
                "competitor_ads" if task_type == "competitor_ad_track" else "ad_intelligence"
            )
            total_data_points = sum(
                self._count_data_points(r) for r in normalized_records
            )
            total_size_bytes = sum(
                len(str(r).encode("utf-8")) for r in normalized_records
            )

            payout_multiplier = 1.5 if data_category == "competitor_ads" else 1.0
            payout_earned = total_commercial_value * payout_multiplier * 0.3

            extraction = NodeDataExtraction(
                session_id=task.get("session_id"),
                user_id=node_user_id,
                task_id=task_id,
                task_type=task_type,
                data_category=data_category,
                records_extracted=records_created,
                data_points=total_data_points,
                data_size_bytes=total_size_bytes,
                commercial_value_usd=total_commercial_value,
                payout_multiplier=payout_multiplier,
                payout_earned_rlusd=payout_earned,
                quality_score=self._compute_quality_score(normalized_records),
                extraction_metadata={
                    "market": market,
                    "source_url": source_url,
                    "ad_formats": list(
                        {r.get("ad_format", "unknown") for r in normalized_records}
                    ),
                },
                created_at=datetime.utcnow(),
            )
            db.session.add(extraction)
            db.session.commit()

            self.logger.info(
                "Ingested %d ad records for task %s (value=$%.4f)",
                records_created,
                task_id,
                total_commercial_value,
            )
        except Exception as exc:
            db.session.rollback()
            self.logger.error("DB error ingesting task %s: %s", task_id, exc)
            return {"ingested": 0, "records_created": 0, "commercial_value_usd": 0.0}

        return {
            "ingested": len(raw_ads),
            "records_created": records_created,
            "commercial_value_usd": round(total_commercial_value, 6),
        }

    # ------------------------------------------------------------------
    # Normalization helpers
    # ------------------------------------------------------------------

    def _normalize_ad_record(
        self, raw: Dict, market: str, task_id: str, node_user_id: int
    ) -> Dict:
        """Normalize a single raw ad dict into a flat record suitable for
        AdIntelligenceRecord creation.

        Args:
            raw: Raw ad data dict from the node result.
            market: Two-letter market code (e.g. 'US').
            task_id: Parent task identifier.
            node_user_id: User ID of the node that produced the data.

        Returns:
            Dict of column values for AdIntelligenceRecord.
        """
        record_id = "AI-" + secrets.token_hex(12)

        ad_format = self._classify_ad_format(raw)
        ad_url = raw.get("ad_url", raw.get("destination_url", raw.get("url", "")))
        advertiser = raw.get("advertiser", self._extract_domain(ad_url))

        ad_text = raw.get("ad_text", raw.get("title", raw.get("description", "")))
        vertical = self._classify_vertical(ad_text)
        sub_vertical = raw.get("sub_vertical", "")

        position = raw.get("position", raw.get("ad_position", "search_other"))
        estimated_bid = self._estimate_bid(ad_format, position, market)

        # Commercial value based on format
        format_key = f"{ad_format}_ad" if not ad_format.endswith("_ad") else ad_format
        if format_key not in AD_DATA_VALUES:
            format_key = f"{ad_format}_ad"
        commercial_value = AD_DATA_VALUES.get(format_key, 0.003)

        # If the task is competitor tracking, use competitor_ad value
        if raw.get("is_competitor", False):
            commercial_value = AD_DATA_VALUES.get("competitor_ad", 0.012)

        confidence_score = self._compute_confidence(raw, ad_text, ad_url, advertiser)

        observed_at = raw.get("observed_at")
        if observed_at and isinstance(observed_at, str):
            try:
                observed_at = datetime.fromisoformat(observed_at)
            except (ValueError, TypeError):
                observed_at = datetime.utcnow()
        elif not observed_at:
            observed_at = datetime.utcnow()

        return {
            "record_id": record_id,
            "task_id": task_id,
            "node_user_id": node_user_id,
            "market": market,
            "source_url": "",
            "advertiser": advertiser,
            "ad_network": raw.get("ad_network", raw.get("network", "google_ads")),
            "ad_format": ad_format,
            "ad_position": position,
            "ad_text": ad_text,
            "ad_destination_url": ad_url,
            "ad_image_hash": raw.get("image_hash", raw.get("ad_image_hash", "")),
            "estimated_bid_usd": round(estimated_bid, 4),
            "targeting_keywords": raw.get("targeting_keywords", raw.get("keywords", [])),
            "targeting_demographics": raw.get("targeting_demographics", {}),
            "targeting_geo": raw.get("targeting_geo", market),
            "vertical": vertical,
            "sub_vertical": sub_vertical,
            "commercial_value_usd": round(commercial_value, 6),
            "is_sold": False,
            "confidence_score": round(confidence_score, 3),
            "observed_at": observed_at,
            "created_at": datetime.utcnow(),
        }

    def _classify_vertical(self, text: str) -> str:
        """Classify ad text into a vertical based on keyword matching.

        Scans the lowercased text for keywords defined in VERTICAL_KEYWORDS
        and returns the first matching vertical. Falls back to 'general'.

        Args:
            text: Ad text or title to classify.

        Returns:
            Vertical string (e.g. 'travel', 'finance', 'general').
        """
        if not text:
            return "general"

        lower_text = text.lower()
        for vertical, keywords in VERTICAL_KEYWORDS.items():
            for keyword in keywords:
                if keyword in lower_text:
                    return vertical
        return "general"

    def _classify_ad_format(self, raw: Dict) -> str:
        """Determine ad format from raw data signals.

        Uses heuristic checks for shopping price, video indicators, native
        flags, and display markers. Defaults to 'search'.

        Args:
            raw: Raw ad data dict.

        Returns:
            Format string: 'shopping', 'video', 'native', 'display', or 'search'.
        """
        # Explicit format override
        explicit = raw.get("ad_format", raw.get("format", ""))
        if explicit:
            normalized = explicit.lower().replace(" ", "_").replace("-", "_")
            if normalized in ("shopping", "shopping_ad"):
                return "shopping"
            if normalized in ("video", "video_ad"):
                return "video"
            if normalized in ("native", "native_ad"):
                return "native"
            if normalized in ("display", "display_ad"):
                return "display"
            if normalized in ("search", "search_ad"):
                return "search"

        # Shopping indicators
        if raw.get("shopping_ad_price") or raw.get("price") or raw.get("product_price"):
            return "shopping"

        # Video indicators
        if raw.get("video_url") or raw.get("is_video") or raw.get("video_duration"):
            return "video"

        # Native indicators
        if raw.get("is_native") or raw.get("native_placement") or raw.get("sponsored_content"):
            return "native"

        # Display indicators
        if raw.get("banner_size") or raw.get("is_display") or raw.get("image_url"):
            return "display"

        return "search"

    def _estimate_bid(self, ad_format: str, position: str, market: str) -> float:
        """Estimate CPC bid for an ad based on format, position, and market.

        Looks up the base CPC from BID_ESTIMATES and applies a market-specific
        multiplier.

        Args:
            ad_format: Ad format string (search, shopping, display, native, video).
            position: Position identifier (e.g. 'search_top', 'search_other').
            market: Two-letter market code.

        Returns:
            Estimated CPC in USD.
        """
        base_cpc_map = BID_ESTIMATES["base_cpc"]

        # Map ad_format + position to a base CPC key
        if ad_format == "search":
            if position and "top" in str(position).lower():
                base_key = "search_top"
            else:
                base_key = "search_other"
        elif ad_format == "shopping":
            base_key = "shopping"
        elif ad_format == "display":
            base_key = "display"
        elif ad_format == "native":
            base_key = "native"
        elif ad_format == "video":
            base_key = "video"
        else:
            base_key = "search_other"

        base_cpc = base_cpc_map.get(base_key, 1.00)

        multiplier = BID_ESTIMATES["market_multipliers"].get(
            market, BID_ESTIMATES["default_multiplier"]
        )

        return round(base_cpc * multiplier, 4)

    def _extract_domain(self, url: str) -> str:
        """Extract a clean domain from a URL string.

        Strips the 'www.' prefix and returns the bare domain.

        Args:
            url: Full URL string.

        Returns:
            Domain string or 'unknown' if parsing fails.
        """
        if not url:
            return "unknown"
        try:
            parsed = urlparse(url)
            domain = parsed.netloc or parsed.path.split("/")[0]
            if domain.startswith("www."):
                domain = domain[4:]
            return domain if domain else "unknown"
        except Exception:
            return "unknown"

    def _compute_confidence(
        self, raw: Dict, ad_text: str, ad_url: str, advertiser: str
    ) -> float:
        """Compute a confidence score (0.0–1.0) for the extracted ad record.

        Awards points for each available field: text, URL, advertiser,
        targeting data, image hash, ad network, and position info.

        Args:
            raw: Raw ad data dict.
            ad_text: Normalized ad text.
            ad_url: Destination URL.
            advertiser: Resolved advertiser name.

        Returns:
            Float confidence score between 0.0 and 1.0.
        """
        score = 0.0
        checks = 0
        total_checks = 7

        # Ad text present and non-trivial
        if ad_text and len(ad_text) > 10:
            score += 1.0
        checks += 1

        # Destination URL present
        if ad_url and ad_url.startswith("http"):
            score += 1.0
        checks += 1

        # Advertiser resolved beyond 'unknown'
        if advertiser and advertiser != "unknown":
            score += 1.0
        checks += 1

        # Targeting keywords available
        if raw.get("targeting_keywords") or raw.get("keywords"):
            score += 1.0
        checks += 1

        # Image hash available
        if raw.get("image_hash") or raw.get("ad_image_hash"):
            score += 1.0
        checks += 1

        # Ad network identified
        if raw.get("ad_network") or raw.get("network"):
            score += 1.0
        checks += 1

        # Position information present
        if raw.get("position") or raw.get("ad_position"):
            score += 1.0
        checks += 1

        return round(score / total_checks, 3) if total_checks > 0 else 0.5

    def _count_data_points(self, record: Dict) -> int:
        """Count the number of non-empty data points in a normalized record.

        Used for NodeDataExtraction.data_points aggregation.

        Args:
            record: Normalized record dict.

        Returns:
            Integer count of non-empty fields.
        """
        count = 0
        for key, value in record.items():
            if value is not None and value != "" and value != [] and value != {}:
                count += 1
        return count

    def _compute_quality_score(self, records: List[Dict]) -> int:
        """Compute an overall quality score (0–100) for a batch of records.

        Based on average confidence scores and data completeness across
        the full batch.

        Args:
            records: List of normalized record dicts.

        Returns:
            Integer quality score from 0 to 100.
        """
        if not records:
            return 0

        avg_confidence = sum(
            r.get("confidence_score", 0.5) for r in records
        ) / len(records)

        avg_data_points = sum(
            self._count_data_points(r) for r in records
        ) / len(records)

        # Normalize data points (max ~25 fields)
        data_completeness = min(avg_data_points / 25.0, 1.0)

        raw_score = (avg_confidence * 0.6 + data_completeness * 0.4) * 100
        return max(0, min(100, int(round(raw_score))))

    # ------------------------------------------------------------------
    # Query / Analytics
    # ------------------------------------------------------------------

    def query_ads(
        self,
        market: Optional[str] = None,
        vertical: Optional[str] = None,
        advertiser: Optional[str] = None,
        ad_network: Optional[str] = None,
        days_back: int = 7,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict:
        """Query ad intelligence records with optional filters.

        Builds a SQLAlchemy query on AdIntelligenceRecord, applying date
        cutoff and optional market/vertical/advertiser/ad_network filters.

        Args:
            market: Two-letter market code filter.
            vertical: Vertical name filter.
            advertiser: Advertiser substring (LIKE) filter.
            ad_network: Ad network name filter.
            days_back: Number of days to look back from now.
            limit: Maximum records to return.
            offset: Pagination offset.

        Returns:
            Dict with total count, records list, applied filters, and
            pagination info.
        """
        from models import db, AdIntelligenceRecord

        cutoff = datetime.utcnow() - timedelta(days=days_back)
        query = AdIntelligenceRecord.query.filter(
            AdIntelligenceRecord.observed_at >= cutoff
        )

        if market:
            query = query.filter(AdIntelligenceRecord.market == market)
        if vertical:
            query = query.filter(AdIntelligenceRecord.vertical == vertical)
        if advertiser:
            query = query.filter(
                AdIntelligenceRecord.advertiser.ilike(f"%{advertiser}%")
            )
        if ad_network:
            query = query.filter(AdIntelligenceRecord.ad_network == ad_network)

        total = query.count()
        records = (
            query.order_by(AdIntelligenceRecord.observed_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

        return {
            "total": total,
            "records": [self._record_to_dict(r) for r in records],
            "filters": {
                "market": market,
                "vertical": vertical,
                "advertiser": advertiser,
                "ad_network": ad_network,
                "days_back": days_back,
            },
            "pagination": {
                "limit": limit,
                "offset": offset,
            },
        }

    def get_ad_trends(
        self,
        market: Optional[str] = None,
        vertical: Optional[str] = None,
        days_back: int = 30,
        granularity: str = "daily",
    ) -> Dict:
        """Compute ad intelligence trends over a time period.

        Groups ad records by date, calculates daily volume and estimated
        spend, identifies top advertisers, and provides format distribution.
        Supports daily or weekly granularity.

        Args:
            market: Optional market filter.
            vertical: Optional vertical filter.
            days_back: Lookback window in days.
            granularity: 'daily' or 'weekly'.

        Returns:
            Trend data dict with data_points, top_advertisers, and
            format_distribution.
        """
        from models import db, AdIntelligenceRecord
        from sqlalchemy import func

        cutoff = datetime.utcnow() - timedelta(days=days_back)
        base_query = db.session.query(AdIntelligenceRecord).filter(
            AdIntelligenceRecord.observed_at >= cutoff
        )

        if market:
            base_query = base_query.filter(AdIntelligenceRecord.market == market)
        if vertical:
            base_query = base_query.filter(AdIntelligenceRecord.vertical == vertical)

        # Daily aggregation
        daily_stats = (
            db.session.query(
                func.date(AdIntelligenceRecord.observed_at).label("day"),
                func.count(AdIntelligenceRecord.id).label("volume"),
                func.sum(AdIntelligenceRecord.estimated_bid_usd).label("estimated_spend"),
            )
            .filter(AdIntelligenceRecord.observed_at >= cutoff)
        )

        if market:
            daily_stats = daily_stats.filter(AdIntelligenceRecord.market == market)
        if vertical:
            daily_stats = daily_stats.filter(AdIntelligenceRecord.vertical == vertical)

        daily_stats = daily_stats.group_by(
            func.date(AdIntelligenceRecord.observed_at)
        ).order_by(func.date(AdIntelligenceRecord.observed_at)).all()

        data_points = []
        for row in daily_stats:
            data_points.append({
                "date": str(row.day),
                "volume": row.volume or 0,
                "estimated_spend": round(float(row.estimated_spend or 0), 2),
            })

        # Aggregate into weeks if requested
        if granularity == "weekly" and data_points:
            weekly_points = []
            week_bucket: Dict[str, Any] = {}
            for dp in data_points:
                try:
                    dt = datetime.strptime(dp["date"], "%Y-%m-%d")
                except (ValueError, TypeError):
                    continue
                week_start = dt - timedelta(days=dt.weekday())
                week_key = week_start.strftime("%Y-%m-%d")
                if week_key not in week_bucket:
                    week_bucket[week_key] = {"volume": 0, "estimated_spend": 0.0}
                week_bucket[week_key]["volume"] += dp["volume"]
                week_bucket[week_key]["estimated_spend"] += dp["estimated_spend"]

            for week_key in sorted(week_bucket.keys()):
                weekly_points.append({
                    "week_start": week_key,
                    "volume": week_bucket[week_key]["volume"],
                    "estimated_spend": round(
                        week_bucket[week_key]["estimated_spend"], 2
                    ),
                })
            data_points = weekly_points

        # Top advertisers
        top_advertisers_query = (
            db.session.query(
                AdIntelligenceRecord.advertiser,
                func.count(AdIntelligenceRecord.id).label("ad_count"),
                func.sum(AdIntelligenceRecord.estimated_bid_usd).label("total_spend"),
            )
            .filter(AdIntelligenceRecord.observed_at >= cutoff)
        )
        if market:
            top_advertisers_query = top_advertisers_query.filter(
                AdIntelligenceRecord.market == market
            )
        if vertical:
            top_advertisers_query = top_advertisers_query.filter(
                AdIntelligenceRecord.vertical == vertical
            )
        top_advertisers_rows = (
            top_advertisers_query.group_by(AdIntelligenceRecord.advertiser)
            .order_by(func.count(AdIntelligenceRecord.id).desc())
            .limit(20)
            .all()
        )

        top_advertisers = [
            {
                "advertiser": row.advertiser,
                "ad_count": row.ad_count,
                "total_spend": round(float(row.total_spend or 0), 2),
            }
            for row in top_advertisers_rows
        ]

        # Format distribution
        format_dist_query = (
            db.session.query(
                AdIntelligenceRecord.ad_format,
                func.count(AdIntelligenceRecord.id).label("count"),
            )
            .filter(AdIntelligenceRecord.observed_at >= cutoff)
        )
        if market:
            format_dist_query = format_dist_query.filter(
                AdIntelligenceRecord.market == market
            )
        if vertical:
            format_dist_query = format_dist_query.filter(
                AdIntelligenceRecord.vertical == vertical
            )
        format_dist_rows = format_dist_query.group_by(
            AdIntelligenceRecord.ad_format
        ).all()

        format_distribution = {
            row.ad_format: row.count for row in format_dist_rows
        }

        end_date = datetime.utcnow()
        start_date = cutoff

        return {
            "period": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
            },
            "granularity": granularity,
            "data_points": data_points,
            "top_advertisers": top_advertisers,
            "format_distribution": format_distribution,
        }

    def get_competitor_report(
        self,
        advertiser: Optional[str] = None,
        vertical: Optional[str] = None,
        market: Optional[str] = None,
        days_back: int = 30,
    ) -> Dict:
        """Generate a competitor intelligence report.

        Analyzes a specific advertiser's ad activity, calculates spend
        estimates, ad copy variations, position distribution, market
        presence, and identifies competing advertisers in the same vertical.

        Args:
            advertiser: Advertiser name to report on.
            vertical: Vertical filter.
            market: Market filter.
            days_back: Lookback window.

        Returns:
            Competitor report dict with stats, competitors list, position
            distribution, and market presence.
        """
        from models import db, AdIntelligenceRecord
        from sqlalchemy import func

        cutoff = datetime.utcnow() - timedelta(days=days_back)

        query = db.session.query(AdIntelligenceRecord).filter(
            AdIntelligenceRecord.observed_at >= cutoff
        )

        if advertiser:
            query = query.filter(
                AdIntelligenceRecord.advertiser.ilike(f"%{advertiser}%")
            )
        if vertical:
            query = query.filter(AdIntelligenceRecord.vertical == vertical)
        if market:
            query = query.filter(AdIntelligenceRecord.market == market)

        records = query.all()

        if not records:
            return {
                "advertiser": advertiser or "all",
                "period_days": days_back,
                "stats": {
                    "total_ads_observed": 0,
                    "estimated_total_spend": 0.0,
                    "ad_copy_variations": 0,
                    "active_days": 0,
                },
                "competitors": [],
                "position_distribution": {},
                "market_presence": [],
            }

        total_ads_observed = len(records)
        estimated_total_spend = sum(r.estimated_bid_usd or 0.0 for r in records)
        ad_texts = {r.ad_text for r in records if r.ad_text}
        ad_copy_variations = len(ad_texts)

        active_dates = {r.observed_at.date() for r in records if r.observed_at}
        active_days = len(active_dates)

        # Position distribution
        position_counts: Dict[str, int] = {}
        for r in records:
            pos = r.ad_position or "unknown"
            position_counts[pos] = position_counts.get(pos, 0) + 1

        # Market presence
        markets_seen = list({r.market for r in records if r.market})

        # Determine the primary vertical for competitor lookup
        vertical_counts: Dict[str, int] = {}
        for r in records:
            v = r.vertical or "general"
            vertical_counts[v] = vertical_counts.get(v, 0) + 1
        primary_vertical = max(vertical_counts, key=vertical_counts.get) if vertical_counts else "general"

        # Find competing advertisers in the same vertical
        competitors_query = (
            db.session.query(
                AdIntelligenceRecord.advertiser,
                func.count(AdIntelligenceRecord.id).label("ad_count"),
                func.sum(AdIntelligenceRecord.estimated_bid_usd).label("total_spend"),
            )
            .filter(
                AdIntelligenceRecord.observed_at >= cutoff,
                AdIntelligenceRecord.vertical == primary_vertical,
            )
        )
        if advertiser:
            competitors_query = competitors_query.filter(
                ~AdIntelligenceRecord.advertiser.ilike(f"%{advertiser}%")
            )
        if market:
            competitors_query = competitors_query.filter(
                AdIntelligenceRecord.market == market
            )

        competitor_rows = (
            competitors_query.group_by(AdIntelligenceRecord.advertiser)
            .order_by(func.count(AdIntelligenceRecord.id).desc())
            .limit(15)
            .all()
        )

        competitors = [
            {
                "advertiser": row.advertiser,
                "ad_count": row.ad_count,
                "estimated_spend": round(float(row.total_spend or 0), 2),
            }
            for row in competitor_rows
        ]

        return {
            "advertiser": advertiser or "all",
            "period_days": days_back,
            "stats": {
                "total_ads_observed": total_ads_observed,
                "estimated_total_spend": round(estimated_total_spend, 2),
                "ad_copy_variations": ad_copy_variations,
                "active_days": active_days,
            },
            "competitors": competitors,
            "position_distribution": position_counts,
            "market_presence": markets_seen,
        }

    def get_revenue_stats(self, days_back: int = 30) -> Dict:
        """Aggregate revenue statistics for the ad intelligence pipeline.

        Calculates total records, commercial value, sold counts, and realized
        revenue. Provides breakdowns by vertical and market.

        Args:
            days_back: Lookback window in days.

        Returns:
            Revenue stats dict with totals and breakdowns.
        """
        from models import db, AdIntelligenceRecord
        from sqlalchemy import func

        cutoff = datetime.utcnow() - timedelta(days=days_back)

        # Overall aggregates
        totals = (
            db.session.query(
                func.count(AdIntelligenceRecord.id).label("total_records"),
                func.sum(AdIntelligenceRecord.commercial_value_usd).label(
                    "total_commercial_value"
                ),
                func.sum(
                    db.case(
                        (AdIntelligenceRecord.is_sold == True, 1),  # noqa: E712
                        else_=0,
                    )
                ).label("sold_count"),
                func.sum(
                    db.case(
                        (
                            AdIntelligenceRecord.is_sold == True,  # noqa: E712
                            AdIntelligenceRecord.commercial_value_usd,
                        ),
                        else_=0,
                    )
                ).label("revenue_realized"),
            )
            .filter(AdIntelligenceRecord.observed_at >= cutoff)
            .first()
        )

        total_records = totals.total_records or 0
        total_commercial_value = round(float(totals.total_commercial_value or 0), 4)
        sold_count = totals.sold_count or 0
        revenue_realized = round(float(totals.revenue_realized or 0), 4)

        # Breakdown by vertical
        vertical_rows = (
            db.session.query(
                AdIntelligenceRecord.vertical,
                func.count(AdIntelligenceRecord.id).label("count"),
                func.sum(AdIntelligenceRecord.commercial_value_usd).label("value"),
                func.sum(
                    db.case(
                        (
                            AdIntelligenceRecord.is_sold == True,  # noqa: E712
                            AdIntelligenceRecord.commercial_value_usd,
                        ),
                        else_=0,
                    )
                ).label("revenue"),
            )
            .filter(AdIntelligenceRecord.observed_at >= cutoff)
            .group_by(AdIntelligenceRecord.vertical)
            .all()
        )

        vertical_breakdown = [
            {
                "vertical": row.vertical or "general",
                "records": row.count,
                "commercial_value": round(float(row.value or 0), 4),
                "revenue_realized": round(float(row.revenue or 0), 4),
            }
            for row in vertical_rows
        ]

        # Breakdown by market
        market_rows = (
            db.session.query(
                AdIntelligenceRecord.market,
                func.count(AdIntelligenceRecord.id).label("count"),
                func.sum(AdIntelligenceRecord.commercial_value_usd).label("value"),
                func.sum(
                    db.case(
                        (
                            AdIntelligenceRecord.is_sold == True,  # noqa: E712
                            AdIntelligenceRecord.commercial_value_usd,
                        ),
                        else_=0,
                    )
                ).label("revenue"),
            )
            .filter(AdIntelligenceRecord.observed_at >= cutoff)
            .group_by(AdIntelligenceRecord.market)
            .all()
        )

        market_breakdown = [
            {
                "market": row.market or "unknown",
                "records": row.count,
                "commercial_value": round(float(row.value or 0), 4),
                "revenue_realized": round(float(row.revenue or 0), 4),
            }
            for row in market_rows
        ]

        return {
            "period_days": days_back,
            "total_records": total_records,
            "total_commercial_value": total_commercial_value,
            "sold_count": sold_count,
            "revenue_realized": revenue_realized,
            "sell_through_rate": round(sold_count / total_records, 4) if total_records else 0.0,
            "vertical_breakdown": vertical_breakdown,
            "market_breakdown": market_breakdown,
        }

    def get_monthly_revenue(self) -> float:
        """Calculate total ad intelligence revenue for the current calendar month.

        Combines realized per-record revenue (is_sold records) with subscription
        tier revenue from CommercialAccount entries.

        Returns:
            Total monthly revenue in USD.
        """
        from models import db, AdIntelligenceRecord

        now = datetime.utcnow()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        from sqlalchemy import func

        sold_revenue = (
            db.session.query(
                func.sum(AdIntelligenceRecord.commercial_value_usd)
            )
            .filter(
                AdIntelligenceRecord.is_sold == True,  # noqa: E712
                AdIntelligenceRecord.observed_at >= month_start,
            )
            .scalar()
        )
        total = float(sold_revenue or 0.0)

        # Add subscription tier revenue from CommercialAccount if available
        try:
            from models import CommercialAccount

            active_subs = (
                CommercialAccount.query.filter(
                    CommercialAccount.is_active == True,  # noqa: E712
                    CommercialAccount.plan_id.in_(list(AD_INTEL_TIERS.keys())),
                ).all()
            )
            for sub in active_subs:
                tier_info = AD_INTEL_TIERS.get(sub.plan_id, {})
                total += tier_info.get("price_usd_monthly", 0)
        except (ImportError, Exception) as exc:
            self.logger.debug(
                "CommercialAccount not available for subscription revenue: %s", exc
            )

        return round(total, 2)

    def get_pricing_info(self) -> Dict:
        """Return the ad intelligence subscription tier pricing information.

        Returns:
            Copy of the AD_INTEL_TIERS dict describing available plans.
        """
        return dict(AD_INTEL_TIERS)

    # ------------------------------------------------------------------
    # Internal serialization
    # ------------------------------------------------------------------

    def _record_to_dict(self, record) -> Dict:
        """Convert an AdIntelligenceRecord ORM instance to a plain dict.

        Handles datetime serialization and JSON field passthrough.

        Args:
            record: AdIntelligenceRecord instance.

        Returns:
            Dict representation suitable for JSON serialization.
        """
        try:
            return record.to_dict()
        except (AttributeError, Exception):
            return {
                "record_id": record.record_id,
                "task_id": record.task_id,
                "market": record.market,
                "advertiser": record.advertiser,
                "ad_network": record.ad_network,
                "ad_format": record.ad_format,
                "ad_position": record.ad_position,
                "ad_text": record.ad_text,
                "ad_destination_url": record.ad_destination_url,
                "estimated_bid_usd": record.estimated_bid_usd,
                "targeting_keywords": record.targeting_keywords,
                "targeting_geo": record.targeting_geo,
                "vertical": record.vertical,
                "sub_vertical": record.sub_vertical,
                "commercial_value_usd": record.commercial_value_usd,
                "is_sold": record.is_sold,
                "confidence_score": record.confidence_score,
                "observed_at": (
                    record.observed_at.isoformat() if record.observed_at else None
                ),
                "created_at": (
                    record.created_at.isoformat() if record.created_at else None
                ),
            }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

ad_intelligence_engine = AdIntelligenceEngine()
