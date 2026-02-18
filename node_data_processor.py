"""
MYSTES Node Data Processor (Build #67)

Server-side processor for browser extension events.
Classifies, deduplicates, quality-scores, and routes browsing events
to existing data hooks (yield dashboard, ad intelligence, feedback engine).

Pipeline flow:
    Chrome Extension -> Local Node Service -> Backend API (ingest_batch)
    -> NodeDataProcessor -> validate / dedup / score / classify / persist
    -> Route to: yield_dashboard, ad_intelligence, feedback_engine

Usage:
    from node_data_processor import node_data_processor

    result = node_data_processor.ingest_batch(
        user_id=42, node_id="NODE-abc123", session_id="SESS-xyz",
        events=[
            {"event_type": "page_visit", "url": "https://example.com", "title": "Example"},
            {"event_type": "search_query", "url": "https://google.com/search?q=flights", "query": "flights"},
        ]
    )
    # result => {"accepted": 2, "rejected": 0, "duplicates": 0, ...}

    stats = node_data_processor.get_ingestion_stats(user_id=42)
    proc  = node_data_processor.get_processing_stats()
"""

import json
import logging
import hashlib
from datetime import datetime, timezone, timedelta
from collections import OrderedDict
from threading import Lock
from urllib.parse import urlparse
from uuid import uuid4

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — Commercial Values
# ---------------------------------------------------------------------------

EVENT_COMMERCIAL_VALUES = {
    "page_visit":        0.0001,
    "search_query":      0.0005,
    "ad_impression":     0.003,
    "price_observation": 0.001,
    "social_signal":     0.002,
}

# ---------------------------------------------------------------------------
# Constants — Event Type -> Yield Dashboard Data Category
# ---------------------------------------------------------------------------

EVENT_TYPE_CATEGORY_MAP = {
    "page_visit":        "browsing_data",
    "search_query":      "search_results",
    "ad_impression":     "ad_intelligence",
    "price_observation": "product_pricing",
    "social_signal":     "social_signals",
}

# ---------------------------------------------------------------------------
# Constants — Valid Event Types
# ---------------------------------------------------------------------------

VALID_EVENT_TYPES = set(EVENT_COMMERCIAL_VALUES.keys())

# ---------------------------------------------------------------------------
# Constants — Rate Limits
# ---------------------------------------------------------------------------

MAX_EVENTS_PER_MINUTE = 1000
MAX_EVENTS_PER_DAY = 50000

# ---------------------------------------------------------------------------
# Constants — Domain -> Commercial Vertical Mapping
# ---------------------------------------------------------------------------

DOMAIN_VERTICAL_MAP = {
    # Search engines
    "google.com":       "search",
    "bing.com":         "search",
    "yahoo.com":        "search",
    "duckduckgo.com":   "search",
    "baidu.com":        "search",
    "yandex.com":       "search",

    # E-commerce
    "amazon.com":       "ecommerce",
    "ebay.com":         "ecommerce",
    "walmart.com":      "ecommerce",
    "target.com":       "ecommerce",
    "bestbuy.com":      "ecommerce",
    "etsy.com":         "ecommerce",
    "shopify.com":      "ecommerce",
    "aliexpress.com":   "ecommerce",
    "wayfair.com":      "ecommerce",
    "costco.com":       "ecommerce",

    # Travel
    "booking.com":      "travel",
    "expedia.com":      "travel",
    "hotels.com":       "travel",
    "airbnb.com":       "travel",
    "tripadvisor.com":  "travel",
    "kayak.com":        "travel",
    "skyscanner.com":   "travel",
    "priceline.com":    "travel",
    "orbitz.com":       "travel",
    "vrbo.com":         "travel",

    # Social media
    "facebook.com":     "social",
    "instagram.com":    "social",
    "twitter.com":      "social",
    "x.com":            "social",
    "reddit.com":       "social",
    "linkedin.com":     "social",
    "tiktok.com":       "social",
    "pinterest.com":    "social",
    "snapchat.com":     "social",
    "threads.net":      "social",

    # Media / streaming
    "youtube.com":      "media",
    "netflix.com":      "media",
    "spotify.com":      "media",
    "twitch.tv":        "media",
    "hulu.com":         "media",
    "disneyplus.com":   "media",
    "pandora.com":      "media",

    # Real estate
    "zillow.com":       "real_estate",
    "redfin.com":       "real_estate",
    "realtor.com":      "real_estate",
    "trulia.com":       "real_estate",
    "apartments.com":   "real_estate",

    # Finance
    "chase.com":        "finance",
    "bankofamerica.com":"finance",
    "wellsfargo.com":   "finance",
    "paypal.com":       "finance",
    "coinbase.com":     "finance",
    "robinhood.com":    "finance",
    "mint.com":         "finance",

    # News
    "cnn.com":          "news",
    "bbc.com":          "news",
    "nytimes.com":      "news",
    "reuters.com":      "news",
    "bloomberg.com":    "news",
}

# ---------------------------------------------------------------------------
# Constants — Event Schema (required fields beyond base)
# ---------------------------------------------------------------------------

EVENT_SCHEMA = {
    "page_visit":        [],
    "search_query":      ["query"],
    "ad_impression":     ["advertiser", "ad_text"],  # either one suffices
    "price_observation": ["product_title", "price"],
    "social_signal":     ["platform"],
}

# ---------------------------------------------------------------------------
# Processor class
# ---------------------------------------------------------------------------


class NodeDataProcessor:
    """
    Central processor for all browser extension data flowing into Mystes.

    Responsibilities:
    - Validate incoming events against schema
    - Deduplicate using in-memory LRU cache
    - Quality-score each event
    - Persist to BrowsingEvent model
    - Route to downstream hooks (yield_dashboard, ad_intelligence, feedback_engine)
    - Track rate limits per node
    """

    def __init__(self, dedup_cache_size=50000):
        self._dedup_cache_size = dedup_cache_size
        self._dedup_cache = OrderedDict()
        self._dedup_lock = Lock()

        # {node_id: {"minute": (count, minute_ts), "day": (count, day_ts)}}
        self._rate_counters = {}
        self._rate_lock = Lock()

        # Stats counters
        self._total_ingested = 0
        self._total_duplicates = 0
        self._total_rejected = 0
        self._total_routed = 0
        self._cache_hits = 0
        self._cache_checks = 0

        logger.info(
            "NodeDataProcessor initialized — dedup_cache_size=%d, "
            "rate_limit=%d/min %d/day",
            dedup_cache_size, MAX_EVENTS_PER_MINUTE, MAX_EVENTS_PER_DAY,
        )

    # ------------------------------------------------------------------
    # Public: Batch Ingestion
    # ------------------------------------------------------------------

    def ingest_batch(self, user_id, node_id, session_id, events):
        """
        Ingest a batch of browsing events from the Chrome extension via the
        local node service.

        Parameters
        ----------
        user_id : int
            The authenticated user / node-operator ID.
        node_id : str
            Node identifier (e.g. "NODE-a1b2c3").
        session_id : str
            Browsing session identifier.
        events : list[dict]
            Raw event dicts from the extension payload.

        Returns
        -------
        dict
            Summary with keys: accepted, rejected, duplicates, errors,
            value_usd, details.
        """
        # Lazy imports for Flask app context
        from models import db

        accepted = 0
        rejected = 0
        duplicates = 0
        errors = 0
        total_value = 0.0
        details = []
        persisted_events = []

        for idx, event_dict in enumerate(events):
            event_detail = {"index": idx, "event_type": event_dict.get("event_type")}

            try:
                # --- Rate limit ---
                if not self._check_rate_limit(node_id):
                    rejected += 1
                    event_detail["status"] = "rejected"
                    event_detail["reason"] = "rate_limit_exceeded"
                    details.append(event_detail)
                    continue

                # --- Validate ---
                valid, reason = self._validate_event(event_dict)
                if not valid:
                    rejected += 1
                    self._total_rejected += 1
                    event_detail["status"] = "rejected"
                    event_detail["reason"] = reason
                    details.append(event_detail)
                    continue

                # --- Consent filter (Build #75) ---
                try:
                    from models import NodeConsentProfile
                    consent_profile = NodeConsentProfile.query.filter_by(user_id=user_id).first()
                    if consent_profile:
                        etype = event_dict.get("event_type", "")
                        consent_map = {
                            "search_query": consent_profile.consent_search_queries,
                            "price_observation": consent_profile.consent_price_observations,
                            "ad_impression": consent_profile.consent_ad_impressions,
                            "social_signal": consent_profile.consent_social_signals,
                            "page_visit": consent_profile.consent_browsing_data,
                            "browsing": consent_profile.consent_browsing_data,
                            "business_data": consent_profile.consent_business_data,
                        }
                        consented = consent_map.get(etype, True)
                        if not consented:
                            rejected += 1
                            event_detail["status"] = "rejected"
                            event_detail["reason"] = "consent_not_granted"
                            details.append(event_detail)
                            continue
                except Exception:
                    pass  # Consent check failure is non-blocking

                # --- Deduplicate ---
                captured_at_raw = event_dict.get("captured_at")
                if captured_at_raw:
                    try:
                        captured_at = datetime.fromisoformat(
                            str(captured_at_raw).replace("Z", "+00:00")
                        )
                    except (ValueError, TypeError):
                        captured_at = datetime.now(timezone.utc)
                else:
                    captured_at = datetime.now(timezone.utc)

                if self._deduplicate(user_id, event_dict["url"],
                                     event_dict["event_type"], captured_at):
                    duplicates += 1
                    self._total_duplicates += 1
                    event_detail["status"] = "duplicate"
                    details.append(event_detail)
                    continue

                # --- Quality score ---
                quality = self._quality_score(event_dict)

                # --- Classify domain ---
                data_category = self._classify_event_category(event_dict)

                # --- Calculate commercial value ---
                value_usd = self._calculate_value(
                    event_dict["event_type"], quality
                )

                # --- Persist ---
                browsing_event = self._persist_event(
                    user_id=user_id,
                    node_id=node_id,
                    session_id=session_id,
                    event_dict=event_dict,
                    quality=quality,
                    value_usd=value_usd,
                    data_category=data_category,
                    captured_at=captured_at,
                )
                persisted_events.append((browsing_event, event_dict))

                # --- Route ---
                route_result = self._route_event(browsing_event, event_dict)

                # Update persisted event with processing result
                browsing_event.is_processed = True
                browsing_event.processing_result = route_result
                browsing_event.processed_at = datetime.now(timezone.utc)

                accepted += 1
                total_value += value_usd
                self._total_ingested += 1

                event_detail["status"] = "accepted"
                event_detail["quality"] = quality
                event_detail["value_usd"] = round(value_usd, 6)
                event_detail["data_category"] = data_category
                event_detail["route_result"] = route_result

            except Exception as exc:
                errors += 1
                logger.exception(
                    "Error processing event %d for user %s: %s",
                    idx, user_id, exc,
                )
                event_detail["status"] = "error"
                event_detail["reason"] = str(exc)[:200]

            details.append(event_detail)

        # --- Batch commit ---
        if persisted_events:
            try:
                db.session.commit()
                logger.info(
                    "Committed %d browsing events for user=%s node=%s "
                    "(value=$%.4f)",
                    len(persisted_events), user_id, node_id, total_value,
                )
            except Exception as exc:
                db.session.rollback()
                logger.exception(
                    "DB commit failed for batch user=%s node=%s: %s",
                    user_id, node_id, exc,
                )
                # Downgrade accepted to errors
                errors += accepted
                accepted = 0
                total_value = 0.0
                for d in details:
                    if d.get("status") == "accepted":
                        d["status"] = "error"
                        d["reason"] = "db_commit_failed"

        return {
            "accepted": accepted,
            "rejected": rejected,
            "duplicates": duplicates,
            "errors": errors,
            "value_usd": round(total_value, 6),
            "details": details,
        }

    # ------------------------------------------------------------------
    # Rate Limiting
    # ------------------------------------------------------------------

    def _check_rate_limit(self, node_id):
        """
        Thread-safe check against per-minute and per-day rate limits.

        Returns True if the event is allowed, False if rate-limited.
        Counters automatically reset when the minute or day rolls over.
        """
        now = datetime.now(timezone.utc)
        current_minute = now.replace(second=0, microsecond=0)
        current_day = now.replace(hour=0, minute=0, second=0, microsecond=0)

        with self._rate_lock:
            if node_id not in self._rate_counters:
                self._rate_counters[node_id] = {
                    "minute": (1, current_minute),
                    "day": (1, current_day),
                }
                return True

            counters = self._rate_counters[node_id]

            # --- Minute counter ---
            min_count, min_ts = counters["minute"]
            if min_ts < current_minute:
                # New minute — reset
                min_count = 1
                min_ts = current_minute
            else:
                min_count += 1

            if min_count > MAX_EVENTS_PER_MINUTE:
                logger.warning(
                    "Rate limit (minute) exceeded for node %s: %d/%d",
                    node_id, min_count, MAX_EVENTS_PER_MINUTE,
                )
                return False

            # --- Day counter ---
            day_count, day_ts = counters["day"]
            if day_ts < current_day:
                day_count = 1
                day_ts = current_day
            else:
                day_count += 1

            if day_count > MAX_EVENTS_PER_DAY:
                logger.warning(
                    "Rate limit (day) exceeded for node %s: %d/%d",
                    node_id, day_count, MAX_EVENTS_PER_DAY,
                )
                return False

            # Update
            counters["minute"] = (min_count, min_ts)
            counters["day"] = (day_count, day_ts)
            return True

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate_event(self, event_dict):
        """
        Validate an event dict against the expected schema.

        Returns
        -------
        tuple(bool, str)
            (True, "") if valid, (False, "reason") otherwise.
        """
        event_type = event_dict.get("event_type")
        if not event_type or event_type not in VALID_EVENT_TYPES:
            return (False, f"invalid_event_type: {event_type}")

        url = event_dict.get("url")
        if not url or not isinstance(url, str) or len(url.strip()) == 0:
            return (False, "missing_or_empty_url")

        # URL length sanity check
        if len(url) > 4000:
            return (False, "url_too_long")

        # Event-type-specific required fields
        required_fields = EVENT_SCHEMA.get(event_type, [])

        if event_type == "ad_impression":
            # For ad_impression, we need at least one of advertiser or ad_text
            has_advertiser = bool(event_dict.get("advertiser"))
            has_ad_text = bool(event_dict.get("ad_text"))
            if not has_advertiser and not has_ad_text:
                return (False, "ad_impression requires advertiser or ad_text")
        else:
            for field in required_fields:
                val = event_dict.get(field)
                if val is None or (isinstance(val, str) and len(val.strip()) == 0):
                    return (False, f"missing_required_field: {field}")

        return (True, "")

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    def _deduplicate(self, user_id, url, event_type, captured_at):
        """
        Check if this event is a duplicate using an in-memory LRU cache.

        Key is built from (user_id, url, event_type, hour_bucket). Events
        within the same hour with identical parameters are considered
        duplicates.

        Returns True if duplicate, False if new.
        """
        # Build hour bucket for dedup window
        hour_bucket = captured_at.strftime("%Y%m%d%H")

        raw_key = f"{user_id}|{url}|{event_type}|{hour_bucket}"
        dedup_key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:24]

        with self._dedup_lock:
            self._cache_checks += 1

            if dedup_key in self._dedup_cache:
                # Move to end (most recently seen)
                self._dedup_cache.move_to_end(dedup_key)
                self._cache_hits += 1
                return True

            # Not a duplicate — insert
            self._dedup_cache[dedup_key] = True

            # Evict oldest if cache is full
            while len(self._dedup_cache) > self._dedup_cache_size:
                self._dedup_cache.popitem(last=False)

            return False

    # ------------------------------------------------------------------
    # Quality Scoring
    # ------------------------------------------------------------------

    def _quality_score(self, event_dict):
        """
        Compute a quality score (0-100) for an event based on data
        richness and completeness.

        Scoring breakdown:
            Base:               30 points
            Title present:     +20 (title exists and len > 5)
            Rich event_data:   +15 (event_data has 3+ fields)
            HTTPS URL:         +10
            Classified domain: +10 (domain in DOMAIN_VERTICAL_MAP)
            Type-specific:     +15 (rich type-specific data)
        """
        score = 30

        # Title present and meaningful
        title = event_dict.get("title", "")
        if title and len(str(title)) > 5:
            score += 20

        # Rich event_data
        event_data = event_dict.get("event_data")
        if event_data:
            if isinstance(event_data, dict):
                data_fields = event_data
            elif isinstance(event_data, str):
                try:
                    data_fields = json.loads(event_data)
                except (json.JSONDecodeError, TypeError):
                    data_fields = {}
            else:
                data_fields = {}
            if isinstance(data_fields, dict) and len(data_fields) >= 3:
                score += 15

        # HTTPS
        url = event_dict.get("url", "")
        if url.startswith("https://"):
            score += 10

        # Classified domain
        vertical = self._classify_domain(url)
        if vertical != "other":
            score += 10

        # Type-specific richness
        event_type = event_dict.get("event_type")
        score += self._type_specific_quality_bonus(event_type, event_dict)

        return min(score, 100)

    def _type_specific_quality_bonus(self, event_type, event_dict):
        """
        Return up to 15 bonus points for type-specific data richness.
        """
        if event_type == "ad_impression":
            has_advertiser = bool(event_dict.get("advertiser"))
            has_destination = bool(event_dict.get("destination_url"))
            has_ad_text = bool(event_dict.get("ad_text"))
            count = sum([has_advertiser, has_destination, has_ad_text])
            if count >= 2:
                return 15
            elif count == 1:
                return 8
            return 0

        elif event_type == "search_query":
            query = event_dict.get("query", "")
            has_results_count = bool(event_dict.get("results_count"))
            has_position = bool(event_dict.get("position"))
            bonus = 0
            if query and len(str(query)) > 3:
                bonus += 8
            if has_results_count or has_position:
                bonus += 7
            return min(bonus, 15)

        elif event_type == "price_observation":
            has_price = bool(event_dict.get("price"))
            has_currency = bool(event_dict.get("currency"))
            has_product = bool(event_dict.get("product_title"))
            count = sum([has_price, has_currency, has_product])
            if count >= 3:
                return 15
            elif count >= 2:
                return 10
            return 5

        elif event_type == "social_signal":
            has_platform = bool(event_dict.get("platform"))
            has_engagement = bool(event_dict.get("engagement_count"))
            has_content_type = bool(event_dict.get("content_type"))
            count = sum([has_platform, has_engagement, has_content_type])
            if count >= 2:
                return 15
            elif count == 1:
                return 8
            return 0

        elif event_type == "page_visit":
            has_referrer = bool(event_dict.get("referrer"))
            has_duration = bool(event_dict.get("duration_ms"))
            if has_referrer and has_duration:
                return 15
            elif has_referrer or has_duration:
                return 8
            return 0

        return 0

    # ------------------------------------------------------------------
    # Domain Classification
    # ------------------------------------------------------------------

    def _classify_domain(self, url):
        """
        Extract the domain from *url* and look it up in
        DOMAIN_VERTICAL_MAP.

        Returns the vertical string (e.g. "search", "ecommerce") or
        "other" if not mapped.
        """
        try:
            parsed = urlparse(url)
            domain = (parsed.hostname or "").lower()
            # Strip www. prefix
            if domain.startswith("www."):
                domain = domain[4:]
            return DOMAIN_VERTICAL_MAP.get(domain, "other")
        except Exception:
            return "other"

    def _classify_event_category(self, event_dict):
        """
        Determine the yield dashboard data category for an event.

        Uses EVENT_TYPE_CATEGORY_MAP for the primary mapping, but can
        upgrade based on domain vertical (e.g. a page_visit to
        booking.com might be reclassified as travel-related browsing).
        """
        event_type = event_dict.get("event_type", "page_visit")
        base_category = EVENT_TYPE_CATEGORY_MAP.get(event_type, "browsing_data")

        # For page_visit, check if domain vertical gives us a more
        # specific category
        if event_type == "page_visit":
            url = event_dict.get("url", "")
            vertical = self._classify_domain(url)
            if vertical == "travel":
                return "flight_pricing"
            elif vertical == "ecommerce":
                return "product_pricing"
            elif vertical == "social":
                return "social_signals"

        return base_category

    # ------------------------------------------------------------------
    # Commercial Value Calculation
    # ------------------------------------------------------------------

    def _calculate_value(self, event_type, quality_score):
        """
        Calculate the commercial value in USD for a single event.

        Value = base_rate * max(quality_multiplier, 0.3)

        A minimum multiplier of 0.3 ensures even low-quality events
        retain 30% of the base commercial value.
        """
        base = EVENT_COMMERCIAL_VALUES.get(event_type, 0.0001)
        multiplier = quality_score / 100.0
        return base * max(multiplier, 0.3)

    # ------------------------------------------------------------------
    # Event Routing
    # ------------------------------------------------------------------

    def _route_event(self, browsing_event, event_dict):
        """
        Route a processed event to the appropriate downstream hooks.

        Routing rules:
        - ad_impression     -> ad_intelligence.ingest_ad_from_extension()
        - search_query      -> feedback_engine.record_search_observation()
        - price_observation -> feedback_engine.record_price_observation()
        - ALL types         -> yield_dashboard.record_extraction()

        Each call is wrapped in try/except so a failure in one hook
        does not prevent other hooks from receiving the event.

        Returns "routed" on success, "error" on any failure.
        """
        event_type = event_dict.get("event_type")
        had_error = False

        # --- Type-specific routing ---
        if event_type == "ad_impression":
            try:
                from ad_intelligence import ad_intelligence_pipeline
                ad_intelligence_pipeline.ingest_ad_from_extension(event_dict)
                self._total_routed += 1
            except Exception as exc:
                logger.warning(
                    "Failed to route ad_impression to ad_intelligence: %s", exc
                )
                had_error = True

        elif event_type == "search_query":
            try:
                from feedback_engine import feedback_engine
                feedback_engine.record_search_observation(event_dict)
                self._total_routed += 1
            except Exception as exc:
                logger.warning(
                    "Failed to route search_query to feedback_engine: %s", exc
                )
                had_error = True

        elif event_type == "price_observation":
            try:
                from feedback_engine import feedback_engine
                feedback_engine.record_price_observation(event_dict)
                self._total_routed += 1
            except Exception as exc:
                logger.warning(
                    "Failed to route price_observation to feedback_engine: %s",
                    exc,
                )
                had_error = True

        # --- Universal routing: yield dashboard ---
        try:
            from node_yield_dashboard import yield_dashboard
            data_category = EVENT_TYPE_CATEGORY_MAP.get(
                event_type, "browsing_data"
            )
            yield_dashboard.record_extraction(
                user_id=browsing_event.user_id,
                session_id=browsing_event.session_id,
                task_id=browsing_event.event_id,
                task_type=event_type,
                records_extracted=1,
                data_points=len(event_dict),
                data_size_bytes=len(json.dumps(event_dict, default=str)),
                quality_score=browsing_event.quality_score,
            )
        except Exception as exc:
            logger.warning(
                "Failed to route event %s to yield_dashboard: %s",
                browsing_event.event_id, exc,
            )
            had_error = True

        return "error" if had_error else "routed"

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist_event(self, user_id, node_id, session_id, event_dict,
                       quality, value_usd, data_category, captured_at=None):
        """
        Create a BrowsingEvent model instance and add it to the session
        (without committing — batch commit happens in ingest_batch).

        Returns the new BrowsingEvent instance.
        """
        from models import db, BrowsingEvent

        event_id = f"EVT-{uuid4().hex[:12]}"
        url = event_dict.get("url", "")

        # Extract domain
        try:
            parsed = urlparse(url)
            domain = (parsed.hostname or "").lower()
            if domain.startswith("www."):
                domain = domain[4:]
        except Exception:
            domain = ""

        # Build event_data JSON — everything except the standard fields
        standard_fields = {"event_type", "url", "title", "captured_at"}
        extra_data = {
            k: v for k, v in event_dict.items() if k not in standard_fields
        }
        event_data_json = json.dumps(extra_data, default=str) if extra_data else None

        event = BrowsingEvent(
            event_id=event_id,
            user_id=user_id,
            node_id=node_id,
            session_id=session_id,
            event_type=event_dict.get("event_type"),
            url=url[:2000],
            domain=domain[:200] if domain else None,
            title=(event_dict.get("title") or "")[:500] or None,
            event_data=event_data_json,
            is_processed=False,
            processing_result=None,
            commercial_value_usd=value_usd,
            data_category=data_category,
            quality_score=quality,
            captured_at=captured_at or datetime.now(timezone.utc),
            ingested_at=datetime.now(timezone.utc),
        )

        db.session.add(event)
        return event

    # ------------------------------------------------------------------
    # Public: Ingestion Stats
    # ------------------------------------------------------------------

    def get_ingestion_stats(self, user_id, days_back=7):
        """
        Query the BrowsingEvent table to produce per-type ingestion
        statistics for the given user over the last *days_back* days.

        Returns
        -------
        dict
            {
                "per_type": {
                    "page_visit": {"count": N, "value_usd": F, "avg_quality": F},
                    ...
                },
                "totals": {
                    "total_events": N,
                    "total_value_usd": F,
                    "avg_events_per_day": F,
                    "avg_quality": F,
                },
                "period_days": days_back,
            }
        """
        from models import db, BrowsingEvent
        from sqlalchemy import func

        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

        rows = (
            db.session.query(
                BrowsingEvent.event_type,
                func.count(BrowsingEvent.id).label("cnt"),
                func.sum(BrowsingEvent.commercial_value_usd).label("total_val"),
                func.avg(BrowsingEvent.quality_score).label("avg_q"),
            )
            .filter(
                BrowsingEvent.user_id == user_id,
                BrowsingEvent.ingested_at >= cutoff,
            )
            .group_by(BrowsingEvent.event_type)
            .all()
        )

        per_type = {}
        total_events = 0
        total_value = 0.0
        quality_sum = 0.0
        quality_count = 0

        for row in rows:
            et = row.event_type or "unknown"
            cnt = row.cnt or 0
            val = float(row.total_val or 0.0)
            avg_q = float(row.avg_q or 0.0)

            per_type[et] = {
                "count": cnt,
                "value_usd": round(val, 6),
                "avg_quality": round(avg_q, 1),
            }
            total_events += cnt
            total_value += val
            quality_sum += avg_q * cnt
            quality_count += cnt

        avg_quality = round(quality_sum / quality_count, 1) if quality_count else 0.0
        avg_per_day = round(total_events / max(days_back, 1), 1)

        return {
            "per_type": per_type,
            "totals": {
                "total_events": total_events,
                "total_value_usd": round(total_value, 6),
                "avg_events_per_day": avg_per_day,
                "avg_quality": avg_quality,
            },
            "period_days": days_back,
        }

    # ------------------------------------------------------------------
    # Public: Processing / Runtime Stats
    # ------------------------------------------------------------------

    def get_processing_stats(self):
        """
        Return internal processor stats: rate counters, dedup cache
        utilisation, cache hit rate, and throughput counters.

        Returns
        -------
        dict
        """
        with self._dedup_lock:
            cache_size = len(self._dedup_cache)
            cache_max = self._dedup_cache_size
            cache_checks = self._cache_checks
            cache_hits = self._cache_hits

        cache_hit_rate = (
            round(cache_hits / cache_checks, 4) if cache_checks > 0 else 0.0
        )

        with self._rate_lock:
            active_nodes = len(self._rate_counters)
            rate_snapshot = {}
            for nid, counters in self._rate_counters.items():
                rate_snapshot[nid] = {
                    "minute_count": counters["minute"][0],
                    "minute_ts": counters["minute"][1].isoformat(),
                    "day_count": counters["day"][0],
                    "day_ts": counters["day"][1].isoformat(),
                }

        return {
            "dedup_cache": {
                "size": cache_size,
                "max_size": cache_max,
                "utilisation_pct": round(
                    (cache_size / cache_max) * 100, 1
                ) if cache_max > 0 else 0.0,
                "checks": cache_checks,
                "hits": cache_hits,
                "hit_rate": cache_hit_rate,
            },
            "throughput": {
                "total_ingested": self._total_ingested,
                "total_duplicates": self._total_duplicates,
                "total_rejected": self._total_rejected,
                "total_routed": self._total_routed,
            },
            "rate_limits": {
                "active_nodes": active_nodes,
                "max_per_minute": MAX_EVENTS_PER_MINUTE,
                "max_per_day": MAX_EVENTS_PER_DAY,
                "node_counters": rate_snapshot,
            },
        }

    # ------------------------------------------------------------------
    # Public: Background Processing of Pending Events
    # ------------------------------------------------------------------

    def process_pending_events(self, batch_size=200):
        """
        Pick up BrowsingEvents with is_processed=False, route them through
        the downstream hooks, and mark them processed.

        Called by the background task worker (tasks.py).  Returns the number
        of events processed in this run.
        """
        from models import db, BrowsingEvent

        pending = (
            BrowsingEvent.query
            .filter_by(is_processed=False)
            .order_by(BrowsingEvent.ingested_at.asc())
            .limit(batch_size)
            .all()
        )

        if not pending:
            return 0

        processed = 0
        for event in pending:
            try:
                # Reconstruct event_dict from stored data
                event_dict = {
                    "event_type": event.event_type,
                    "url": event.url or "",
                    "title": event.title or "",
                }
                if event.event_data:
                    try:
                        extra = json.loads(event.event_data)
                        event_dict.update(extra)
                    except (json.JSONDecodeError, TypeError):
                        pass

                route_result = self._route_event(event, event_dict)

                event.is_processed = True
                event.processing_result = route_result
                event.processed_at = datetime.now(timezone.utc)
                processed += 1

            except Exception as exc:
                logger.exception(
                    "Background processing failed for event %s: %s",
                    event.event_id, exc,
                )
                event.is_processed = True
                event.processing_result = "error"
                event.processed_at = datetime.now(timezone.utc)

        try:
            db.session.commit()
            if processed:
                logger.info(
                    "Background processor: routed %d/%d pending events",
                    processed, len(pending),
                )
        except Exception as exc:
            db.session.rollback()
            logger.exception("Background processor commit failed: %s", exc)
            return 0

        return processed

    # ------------------------------------------------------------------
    # Public: Commercial API — Browsing Data Queries
    # ------------------------------------------------------------------

    def query_browsing_events(self, event_type=None, domain=None,
                              data_category=None, min_quality=0,
                              days_back=7, limit=100, offset=0):
        """
        Query browsing events for commercial data buyers.
        Returns paginated results with aggregated stats.
        """
        from models import BrowsingEvent
        from sqlalchemy import func

        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

        query = BrowsingEvent.query.filter(
            BrowsingEvent.ingested_at >= cutoff,
            BrowsingEvent.is_processed == True,
            BrowsingEvent.quality_score >= min_quality,
        )
        if event_type:
            query = query.filter(BrowsingEvent.event_type == event_type)
        if domain:
            query = query.filter(BrowsingEvent.domain.ilike(f"%{domain}%"))
        if data_category:
            query = query.filter(BrowsingEvent.data_category == data_category)

        total = query.count()
        records = (
            query.order_by(BrowsingEvent.ingested_at.desc())
            .offset(offset).limit(limit).all()
        )

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "events": [
                {
                    "event_id": e.event_id,
                    "event_type": e.event_type,
                    "domain": e.domain,
                    "title": e.title,
                    "data_category": e.data_category,
                    "quality_score": e.quality_score,
                    "commercial_value_usd": e.commercial_value_usd,
                    "captured_at": e.captured_at.isoformat() if e.captured_at else None,
                    "ingested_at": e.ingested_at.isoformat() if e.ingested_at else None,
                }
                for e in records
            ],
        }

    def get_browsing_trends(self, event_type=None, domain=None,
                            days_back=30, granularity="daily"):
        """
        Browsing data trends — time-series counts, top domains, event type
        distribution. For commercial data buyers.
        """
        from models import db, BrowsingEvent
        from sqlalchemy import func

        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

        base = BrowsingEvent.query.filter(
            BrowsingEvent.ingested_at >= cutoff,
            BrowsingEvent.is_processed == True,
        )
        if event_type:
            base = base.filter(BrowsingEvent.event_type == event_type)
        if domain:
            base = base.filter(BrowsingEvent.domain.ilike(f"%{domain}%"))

        # Time series
        if granularity == "weekly":
            date_trunc = func.strftime('%Y-W%W', BrowsingEvent.ingested_at)
        else:
            date_trunc = func.date(BrowsingEvent.ingested_at)

        time_series = (
            db.session.query(
                date_trunc.label("period"),
                func.count(BrowsingEvent.id).label("count"),
                func.sum(BrowsingEvent.commercial_value_usd).label("value"),
                func.avg(BrowsingEvent.quality_score).label("avg_quality"),
            )
            .filter(
                BrowsingEvent.ingested_at >= cutoff,
                BrowsingEvent.is_processed == True,
            )
            .group_by("period")
            .order_by(date_trunc.desc())
            .limit(90)
            .all()
        )

        # Top domains
        top_domains = (
            db.session.query(
                BrowsingEvent.domain,
                func.count(BrowsingEvent.id).label("count"),
                func.sum(BrowsingEvent.commercial_value_usd).label("value"),
            )
            .filter(
                BrowsingEvent.ingested_at >= cutoff,
                BrowsingEvent.is_processed == True,
                BrowsingEvent.domain.isnot(None),
            )
            .group_by(BrowsingEvent.domain)
            .order_by(func.count(BrowsingEvent.id).desc())
            .limit(20)
            .all()
        )

        # Event type distribution
        type_dist = (
            db.session.query(
                BrowsingEvent.event_type,
                func.count(BrowsingEvent.id).label("count"),
                func.sum(BrowsingEvent.commercial_value_usd).label("value"),
            )
            .filter(
                BrowsingEvent.ingested_at >= cutoff,
                BrowsingEvent.is_processed == True,
            )
            .group_by(BrowsingEvent.event_type)
            .all()
        )

        return {
            "days_back": days_back,
            "granularity": granularity,
            "time_series": [
                {
                    "period": str(row.period),
                    "count": row.count,
                    "value_usd": round(float(row.value or 0), 6),
                    "avg_quality": round(float(row.avg_quality or 0), 1),
                }
                for row in time_series
            ],
            "top_domains": [
                {
                    "domain": row.domain,
                    "count": row.count,
                    "value_usd": round(float(row.value or 0), 6),
                }
                for row in top_domains
            ],
            "event_type_distribution": [
                {
                    "event_type": row.event_type,
                    "count": row.count,
                    "value_usd": round(float(row.value or 0), 6),
                }
                for row in type_dist
            ],
        }

    def get_browsing_domain_report(self, domain, days_back=30):
        """
        Deep-dive report for a specific domain — event breakdown, quality
        trends, hourly distribution. For commercial data buyers.
        """
        from models import db, BrowsingEvent
        from sqlalchemy import func

        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

        base = BrowsingEvent.query.filter(
            BrowsingEvent.ingested_at >= cutoff,
            BrowsingEvent.is_processed == True,
            BrowsingEvent.domain == domain,
        )

        total = base.count()
        total_value = db.session.query(
            func.sum(BrowsingEvent.commercial_value_usd)
        ).filter(
            BrowsingEvent.ingested_at >= cutoff,
            BrowsingEvent.is_processed == True,
            BrowsingEvent.domain == domain,
        ).scalar() or 0

        avg_quality = db.session.query(
            func.avg(BrowsingEvent.quality_score)
        ).filter(
            BrowsingEvent.ingested_at >= cutoff,
            BrowsingEvent.is_processed == True,
            BrowsingEvent.domain == domain,
        ).scalar() or 0

        # Event type breakdown
        by_type = (
            db.session.query(
                BrowsingEvent.event_type,
                func.count(BrowsingEvent.id).label("count"),
                func.sum(BrowsingEvent.commercial_value_usd).label("value"),
                func.avg(BrowsingEvent.quality_score).label("avg_q"),
            )
            .filter(
                BrowsingEvent.ingested_at >= cutoff,
                BrowsingEvent.is_processed == True,
                BrowsingEvent.domain == domain,
            )
            .group_by(BrowsingEvent.event_type)
            .all()
        )

        # Daily trend
        daily = (
            db.session.query(
                func.date(BrowsingEvent.ingested_at).label("day"),
                func.count(BrowsingEvent.id).label("count"),
            )
            .filter(
                BrowsingEvent.ingested_at >= cutoff,
                BrowsingEvent.is_processed == True,
                BrowsingEvent.domain == domain,
            )
            .group_by("day")
            .order_by(func.date(BrowsingEvent.ingested_at).desc())
            .limit(30)
            .all()
        )

        vertical = DOMAIN_VERTICAL_MAP.get(domain, "other")

        return {
            "domain": domain,
            "vertical": vertical,
            "days_back": days_back,
            "total_events": total,
            "total_value_usd": round(float(total_value), 6),
            "avg_quality": round(float(avg_quality), 1),
            "by_event_type": [
                {
                    "event_type": row.event_type,
                    "count": row.count,
                    "value_usd": round(float(row.value or 0), 6),
                    "avg_quality": round(float(row.avg_q or 0), 1),
                }
                for row in by_type
            ],
            "daily_trend": [
                {"date": str(row.day), "count": row.count}
                for row in daily
            ],
        }

    # ------------------------------------------------------------------
    # Public: Reset (for testing)
    # ------------------------------------------------------------------

    def reset(self):
        """
        Clear all in-memory state. Intended for test fixtures.
        """
        with self._dedup_lock:
            self._dedup_cache.clear()
            self._cache_checks = 0
            self._cache_hits = 0

        with self._rate_lock:
            self._rate_counters.clear()

        self._total_ingested = 0
        self._total_duplicates = 0
        self._total_rejected = 0
        self._total_routed = 0

        logger.info("NodeDataProcessor state reset")


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

node_data_processor = NodeDataProcessor()
