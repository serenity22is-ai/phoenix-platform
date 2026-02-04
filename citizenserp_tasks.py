"""
PHOENIX CitizenSERP Task Type System

Defines typed tasks that CitizenSERP nodes can execute. Every search, browse,
or price check that goes through the network is a typed task. Task types tell
the node what to search and how to extract structured data.

Architecture:
  CitizenSERP was generic (uptime-only payouts). Now every task routed to a
  node carries a type, params, and extraction schema so nodes return structured
  data — not just raw HTML.

Task types:
  - flight_search:       Google Flights price extraction
  - hotel_search:        Hotel price extraction (Booking, Expedia, etc.)
  - product_search:      E-commerce price extraction (Amazon, eBay, etc.)
  - marketplace_browse:  Social marketplace browsing (FB Marketplace, etc.)
  - price_monitor:       Recurring price check for alerts
  - general_search:      Open-ended proxy browsing (portal sessions)

Every task pays the node. Every task feeds Phoenix's data layer.

Usage:
    from citizenserp_tasks import task_registry, task_dispatcher

    # Create a flight search task
    task = task_registry.create_task("flight_search", {
        "origin": "JFK", "destination": "NRT",
        "date": "2026-03-15", "market": "JP"
    })

    # Dispatch to best available node
    result = await task_dispatcher.dispatch(task)
"""

import asyncio
import json
import logging
import os
import secrets
import time
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


# ============================================================
# Task Type Definitions
# ============================================================

class TaskType(Enum):
    """All task types CitizenSERP nodes can execute."""
    FLIGHT_SEARCH = "flight_search"
    HOTEL_SEARCH = "hotel_search"
    PRODUCT_SEARCH = "product_search"
    MARKETPLACE_BROWSE = "marketplace_browse"
    CRUISE_SEARCH = "cruise_search"
    ECOMMERCE_SEARCH = "ecommerce_search"
    DIGITAL_SEARCH = "digital_search"
    SEARCH_ENGINE_EXTRACT = "search_engine_extract"
    PRICE_MONITOR = "price_monitor"
    GENERAL_SEARCH = "general_search"
    # Build #65 — high-value data extraction types
    AD_INTELLIGENCE = "ad_intelligence"
    PRICING_INTELLIGENCE_DEEP = "pricing_intelligence_deep"
    SOCIAL_SIGNAL_EXTRACT = "social_signal_extract"
    AUDIENCE_PROFILE_EXTRACT = "audience_profile_extract"
    RETAIL_SHELF_MONITOR = "retail_shelf_monitor"
    COMPETITOR_AD_TRACK = "competitor_ad_track"


class TaskStatus(Enum):
    """Task lifecycle states."""
    CREATED = "created"
    QUEUED = "queued"
    DISPATCHED = "dispatched"
    EXECUTING = "executing"
    EXTRACTING = "extracting"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class TaskPriority(Enum):
    """Task dispatch priority."""
    LOW = 1       # Background monitoring, batch jobs
    NORMAL = 5    # Standard user searches
    HIGH = 8      # Paid commercial API searches
    URGENT = 10   # Real-time booking, time-sensitive alerts


# ============================================================
# Task Data Classes
# ============================================================

@dataclass
class ExtractionRule:
    """Defines how to extract structured data from a page."""
    field_name: str              # Output field name (e.g. "price", "title")
    selector: str                # CSS selector to target
    attribute: str = "text"      # "text", "href", "src", or any HTML attribute
    transform: str = "none"      # "none", "number", "currency", "strip", "lower"
    required: bool = False       # Fail task if field not found
    multiple: bool = False       # Extract all matches (list) vs first match


@dataclass
class TaskDefinition:
    """Blueprint for a task type — what it does and how it extracts data."""
    task_type: TaskType
    name: str
    description: str
    default_timeout_ms: int = 60000
    max_retries: int = 2
    requires_market: bool = True     # Must specify target market/country
    requires_auth: bool = False      # Needs user's authenticated session
    extraction_rules: List[ExtractionRule] = field(default_factory=list)
    navigation_steps: List[Dict[str, Any]] = field(default_factory=list)
    payout_multiplier: float = 1.0   # Higher for complex tasks


@dataclass
class CitizenSERPTask:
    """A concrete task instance to be dispatched to a node."""
    task_id: str
    task_type: str                   # TaskType.value
    params: Dict[str, Any]
    market: str                      # Target country code (e.g. "JP", "US")
    priority: int = 5
    status: str = "created"
    timeout_ms: int = 60000
    max_retries: int = 2
    retries_used: int = 0
    payout_multiplier: float = 1.0

    # Dispatch tracking
    node_user_id: Optional[int] = None
    node_session_id: Optional[str] = None
    dispatched_at: Optional[str] = None
    completed_at: Optional[str] = None

    # Results
    result_data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    execution_time_ms: Optional[int] = None

    # Metadata
    requester_user_id: Optional[int] = None
    requester_type: str = "portal"   # "portal", "commercial", "agent", "system"
    created_at: str = ""

    def __post_init__(self):
        if not self.task_id:
            self.task_id = f"CST-{secrets.token_hex(8)}"
        if not self.created_at:
            self.created_at = datetime.utcnow().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_node_message(self) -> Dict[str, Any]:
        """Format task as message to send to a CitizenSERP node."""
        return {
            "type": "task",
            "task_id": self.task_id,
            "task_type": self.task_type,
            "params": self.params,
            "market": self.market,
            "timeout_ms": self.timeout_ms,
            "timestamp": datetime.utcnow().isoformat()
        }


@dataclass
class TaskResult:
    """Structured result returned by a node after executing a task."""
    task_id: str
    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    execution_time_ms: int = 0
    node_user_id: Optional[int] = None
    node_country: Optional[str] = None
    extracted_items: int = 0
    raw_screenshot: Optional[str] = None   # Base64 PNG for verification
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.utcnow().isoformat()


# ============================================================
# Task Registry — defines all known task types
# ============================================================

class TaskRegistry:
    """
    Central registry of task type definitions.
    Each task type has navigation steps + extraction rules.
    PhoenixAI can register new task types dynamically.
    """

    def __init__(self):
        self._definitions: Dict[str, TaskDefinition] = {}
        self._register_builtin_types()

    def _register_builtin_types(self):
        """Register the built-in task types."""

        # --- FLIGHT SEARCH ---
        self.register(TaskDefinition(
            task_type=TaskType.FLIGHT_SEARCH,
            name="Flight Price Search",
            description="Search Google Flights for prices from a specific market",
            default_timeout_ms=45000,
            max_retries=2,
            requires_market=True,
            payout_multiplier=1.0,
            navigation_steps=[
                {"command": "navigate", "params": {"url_template": "https://www.google.com/travel/flights?q=Flights+from+{origin}+to+{destination}+on+{date}&curr={currency}&hl={lang}"}},
                {"command": "wait_for", "params": {"selector": "[data-result-index]", "timeout_ms": 15000}},
                {"command": "wait_timeout", "params": {"ms": 2000}},
                {"command": "extract_all", "params": {"selector": "[data-result-index]"}},
                {"command": "screenshot", "params": {}}
            ],
            extraction_rules=[
                ExtractionRule(field_name="price", selector="[data-result-index] span[data-gs]", attribute="text", transform="currency", required=True, multiple=True),
                ExtractionRule(field_name="airline", selector="[data-result-index] .sSHqwe", attribute="text", transform="strip", multiple=True),
                ExtractionRule(field_name="duration", selector="[data-result-index] .gvkrdb", attribute="text", transform="strip", multiple=True),
                ExtractionRule(field_name="stops", selector="[data-result-index] .EfT7Ae span", attribute="text", transform="strip", multiple=True),
                ExtractionRule(field_name="departure_time", selector="[data-result-index] .mv1WYe span", attribute="text", transform="strip", multiple=True),
            ]
        ))

        # --- HOTEL SEARCH ---
        self.register(TaskDefinition(
            task_type=TaskType.HOTEL_SEARCH,
            name="Hotel Price Search",
            description="Search for hotel prices from a specific market",
            default_timeout_ms=60000,
            max_retries=2,
            requires_market=True,
            payout_multiplier=1.2,
            navigation_steps=[
                {"command": "navigate", "params": {"url_template": "https://www.google.com/travel/hotels/{destination}?q=Hotels+in+{destination}&dates={checkin}+to+{checkout}&curr={currency}&hl={lang}"}},
                {"command": "wait_for", "params": {"selector": "[data-hotel-id]", "timeout_ms": 15000}},
                {"command": "wait_timeout", "params": {"ms": 2000}},
                {"command": "extract_all", "params": {"selector": "[data-hotel-id]"}},
                {"command": "screenshot", "params": {}}
            ],
            extraction_rules=[
                ExtractionRule(field_name="hotel_name", selector="[data-hotel-id] h2", attribute="text", transform="strip", required=True, multiple=True),
                ExtractionRule(field_name="price_per_night", selector="[data-hotel-id] .kixHKb span", attribute="text", transform="currency", required=True, multiple=True),
                ExtractionRule(field_name="rating", selector="[data-hotel-id] .KFi5wf", attribute="text", transform="number", multiple=True),
                ExtractionRule(field_name="review_count", selector="[data-hotel-id] .jdzyld", attribute="text", transform="number", multiple=True),
                ExtractionRule(field_name="amenities", selector="[data-hotel-id] .HlxIlc", attribute="text", transform="strip", multiple=True),
            ]
        ))

        # --- PRODUCT SEARCH ---
        self.register(TaskDefinition(
            task_type=TaskType.PRODUCT_SEARCH,
            name="Product Price Search",
            description="Search e-commerce sites for product prices from a specific market",
            default_timeout_ms=45000,
            max_retries=2,
            requires_market=True,
            payout_multiplier=1.0,
            navigation_steps=[
                {"command": "navigate", "params": {"url_template": "https://www.google.com/search?q={query}&tbm=shop&gl={market_lower}"}},
                {"command": "wait_for", "params": {"selector": ".sh-dgr__content", "timeout_ms": 15000}},
                {"command": "wait_timeout", "params": {"ms": 1500}},
                {"command": "extract_all", "params": {"selector": ".sh-dgr__content"}},
                {"command": "screenshot", "params": {}}
            ],
            extraction_rules=[
                ExtractionRule(field_name="product_title", selector=".sh-dgr__content .Xjkr3b", attribute="text", transform="strip", required=True, multiple=True),
                ExtractionRule(field_name="price", selector=".sh-dgr__content .a8Pemb", attribute="text", transform="currency", required=True, multiple=True),
                ExtractionRule(field_name="seller", selector=".sh-dgr__content .aULzUe", attribute="text", transform="strip", multiple=True),
                ExtractionRule(field_name="rating", selector=".sh-dgr__content .Rsc7Yb", attribute="text", transform="number", multiple=True),
                ExtractionRule(field_name="link", selector=".sh-dgr__content a.shntl", attribute="href", multiple=True),
            ]
        ))

        # --- MARKETPLACE BROWSE ---
        self.register(TaskDefinition(
            task_type=TaskType.MARKETPLACE_BROWSE,
            name="Marketplace Browse",
            description="Browse social marketplace listings through proxy",
            default_timeout_ms=90000,
            max_retries=1,
            requires_market=True,
            requires_auth=True,  # User's own authenticated session
            payout_multiplier=1.5,
            navigation_steps=[
                {"command": "navigate", "params": {"url_template": "{marketplace_url}/search?query={query}&location={location}"}},
                {"command": "wait_for", "params": {"selector": "[data-testid='marketplace-feed']", "timeout_ms": 20000}},
                {"command": "wait_timeout", "params": {"ms": 3000}},
                {"command": "scroll", "params": {"direction": "down", "amount": 3}},
                {"command": "extract_all", "params": {"selector": "[data-testid='marketplace-feed'] > div"}},
                {"command": "screenshot", "params": {}}
            ],
            extraction_rules=[
                ExtractionRule(field_name="listing_title", selector="span[dir='auto']", attribute="text", transform="strip", required=True, multiple=True),
                ExtractionRule(field_name="price", selector="span[dir='auto']:first-child", attribute="text", transform="currency", required=True, multiple=True),
                ExtractionRule(field_name="location", selector="span.x1lliihq", attribute="text", transform="strip", multiple=True),
                ExtractionRule(field_name="image_url", selector="img[src*='marketplace']", attribute="src", multiple=True),
                ExtractionRule(field_name="listing_url", selector="a[href*='/marketplace/item/']", attribute="href", multiple=True),
                ExtractionRule(field_name="seller_name", selector="a[role='link'] span, .x1heor9g span", attribute="text", transform="strip", multiple=True),
                ExtractionRule(field_name="condition", selector="span:contains('New'), span:contains('Used'), span:contains('Like')", attribute="text", transform="strip", multiple=True),
                ExtractionRule(field_name="posted_date", selector="abbr[data-utime], span.timestampContent", attribute="text", transform="strip", multiple=True),
            ]
        ))

        # --- CRUISE SEARCH ---
        self.register(TaskDefinition(
            task_type=TaskType.CRUISE_SEARCH,
            name="Cruise Search",
            description="Cross-market cruise package price comparison",
            default_timeout_ms=60000,
            max_retries=2,
            requires_market=True,
            payout_multiplier=1.3,
            navigation_steps=[
                {"command": "navigate", "params": {"url_template": "https://www.google.com/travel/cruises?q={query}&gl={market_code}"}},
                {"command": "wait_for", "params": {"selector": "[data-cruise-result], [jsname], .cruise-result", "timeout_ms": 20000}},
                {"command": "wait_timeout", "params": {"ms": 5000}},
                {"command": "scroll", "params": {"direction": "down", "amount": 4}},
                {"command": "extract_all", "params": {"selector": "[data-cruise-result], .cruise-card, [jsname] .result-item"}},
                {"command": "screenshot", "params": {}}
            ],
            extraction_rules=[
                ExtractionRule(field_name="cruise_line", selector=".cruise-line-name, [data-cruise-line]", attribute="text", transform="strip", required=True, multiple=True),
                ExtractionRule(field_name="ship_name", selector=".ship-name, [data-ship]", attribute="text", transform="strip", multiple=True),
                ExtractionRule(field_name="itinerary", selector=".itinerary, [data-ports]", attribute="text", transform="strip", required=True, multiple=True),
                ExtractionRule(field_name="duration_nights", selector=".duration, [data-nights]", attribute="text", transform="number", multiple=True),
                ExtractionRule(field_name="price_per_person", selector=".price, [data-price]", attribute="text", transform="currency", required=True, multiple=True),
                ExtractionRule(field_name="departure_port", selector=".departure-port, [data-departure]", attribute="text", transform="strip", multiple=True),
                ExtractionRule(field_name="cabin_class", selector=".cabin-type, [data-cabin]", attribute="text", transform="strip", multiple=True),
            ]
        ))

        # --- ECOMMERCE SEARCH ---
        self.register(TaskDefinition(
            task_type=TaskType.ECOMMERCE_SEARCH,
            name="E-Commerce Search",
            description="Broad e-commerce product search with landed cost comparison",
            default_timeout_ms=45000,
            max_retries=2,
            requires_market=True,
            payout_multiplier=1.0,
            navigation_steps=[
                {"command": "navigate", "params": {"url_template": "https://www.google.com/search?q={query}&tbm=shop&gl={market_code}"}},
                {"command": "wait_for", "params": {"selector": ".sh-dgr__grid-result, .sh-dlr__list-result, [data-docid]", "timeout_ms": 15000}},
                {"command": "wait_timeout", "params": {"ms": 3000}},
                {"command": "scroll", "params": {"direction": "down", "amount": 3}},
                {"command": "extract_all", "params": {"selector": ".sh-dgr__grid-result, .sh-dlr__list-result, [data-docid]"}},
                {"command": "screenshot", "params": {}}
            ],
            extraction_rules=[
                ExtractionRule(field_name="product_title", selector="h3, .tAxDx, [data-name]", attribute="text", transform="strip", required=True, multiple=True),
                ExtractionRule(field_name="price", selector=".a8Pemb, .HRLxBb, [data-price]", attribute="text", transform="currency", required=True, multiple=True),
                ExtractionRule(field_name="seller", selector=".aULzUe, .IuHnof, [data-merchant]", attribute="text", transform="strip", multiple=True),
                ExtractionRule(field_name="rating", selector=".Rsc7Yb, [data-rating]", attribute="text", transform="number", multiple=True),
                ExtractionRule(field_name="category", selector=".dD8iuc, [data-category]", attribute="text", transform="strip", multiple=True),
                ExtractionRule(field_name="availability", selector=".vEjMR, [data-availability]", attribute="text", transform="strip", multiple=True),
                ExtractionRule(field_name="product_url", selector="a.shntl, a[href*='/shopping/']", attribute="href", multiple=True),
            ]
        ))

        # --- DIGITAL / SOFTWARE SEARCH ---
        self.register(TaskDefinition(
            task_type=TaskType.DIGITAL_SEARCH,
            name="Digital/Software Search",
            description="Digital goods price comparison — software, licenses, game keys",
            default_timeout_ms=30000,
            max_retries=2,
            requires_market=True,
            payout_multiplier=0.8,
            navigation_steps=[
                {"command": "navigate", "params": {"url_template": "https://www.google.com/search?q={query}+buy+digital+license&gl={market_code}"}},
                {"command": "wait_for", "params": {"selector": "#search, #rso", "timeout_ms": 10000}},
                {"command": "wait_timeout", "params": {"ms": 2000}},
                {"command": "scroll", "params": {"direction": "down", "amount": 2}},
                {"command": "extract_all", "params": {"selector": ".g, [data-hveid], .commercial-unit-desktop-top"}},
                {"command": "screenshot", "params": {}}
            ],
            extraction_rules=[
                ExtractionRule(field_name="product_title", selector="h3, .LC20lb, [data-name]", attribute="text", transform="strip", required=True, multiple=True),
                ExtractionRule(field_name="price", selector=".price, [data-price], .HRLxBb", attribute="text", transform="currency", required=True, multiple=True),
                ExtractionRule(field_name="platform", selector=".VuuXrf, cite, [data-platform]", attribute="text", transform="strip", multiple=True),
                ExtractionRule(field_name="license_type", selector="[data-license], .license-info", attribute="text", transform="strip", multiple=True),
                ExtractionRule(field_name="region_lock", selector="[data-region], .region-info", attribute="text", transform="strip", multiple=True),
                ExtractionRule(field_name="availability", selector="[data-availability], .availability", attribute="text", transform="strip", multiple=True),
                ExtractionRule(field_name="product_url", selector="a[href]:first-child, a[data-href]", attribute="href", multiple=True),
            ]
        ))

        # --- SEARCH ENGINE EXTRACT ---
        self.register(TaskDefinition(
            task_type=TaskType.SEARCH_ENGINE_EXTRACT,
            name="Search Engine Extraction",
            description="Lightweight extraction from any search engine results page",
            default_timeout_ms=30000,
            max_retries=2,
            requires_market=True,
            payout_multiplier=0.5,
            navigation_steps=[
                {"command": "navigate", "params": {"url_template": "{search_engine_url}?q={query}"}},
                {"command": "wait_for", "params": {"selector": "#search, #results, .serp, .b_results, #rso", "timeout_ms": 10000}},
                {"command": "wait_timeout", "params": {"ms": 2000}},
                {"command": "extract_all", "params": {"selector": ".g, .b_algo, .result, [data-hveid]"}},
                {"command": "screenshot", "params": {}}
            ],
            extraction_rules=[
                ExtractionRule(field_name="title", selector="h3, h2, .result-title", attribute="text", transform="strip", required=True, multiple=True),
                ExtractionRule(field_name="snippet", selector=".VwiC3b, .b_caption p, .result-snippet", attribute="text", transform="strip", multiple=True),
                ExtractionRule(field_name="url", selector="a[href]:first-child, cite", attribute="href", required=True, multiple=True),
                ExtractionRule(field_name="price", selector=".HRLxBb, [data-price], .price", attribute="text", transform="currency", multiple=True),
                ExtractionRule(field_name="position", selector="", attribute="index", transform="number", multiple=True),
            ]
        ))

        # --- PRICE MONITOR ---
        self.register(TaskDefinition(
            task_type=TaskType.PRICE_MONITOR,
            name="Price Monitor",
            description="Recurring price check for alert system",
            default_timeout_ms=30000,
            max_retries=3,
            requires_market=True,
            payout_multiplier=0.5,   # Lower payout — lightweight, high-frequency
            navigation_steps=[
                {"command": "navigate", "params": {"url_template": "{monitor_url}"}},
                {"command": "wait_for", "params": {"selector": "{price_selector}", "timeout_ms": 10000}},
                {"command": "extract_text", "params": {"selector": "{price_selector}"}},
                {"command": "screenshot", "params": {}}
            ],
            extraction_rules=[
                ExtractionRule(field_name="current_price", selector="{price_selector}", attribute="text", transform="currency", required=True),
                ExtractionRule(field_name="availability", selector="{availability_selector}", attribute="text", transform="strip"),
                ExtractionRule(field_name="last_updated", selector="{timestamp_selector}", attribute="text", transform="strip"),
            ]
        ))

        # --- GENERAL SEARCH ---
        self.register(TaskDefinition(
            task_type=TaskType.GENERAL_SEARCH,
            name="General Proxy Search",
            description="Open-ended proxy browsing session (portal)",
            default_timeout_ms=120000,
            max_retries=0,   # No retry for free-form browsing
            requires_market=True,
            payout_multiplier=0.3,   # Lowest — just proxy uptime
            navigation_steps=[],     # User-driven, no pre-defined steps
            extraction_rules=[]      # No structured extraction
        ))

        # ==========================================================
        # Build #65 — High-Value Data Extraction Task Types
        # ==========================================================

        # --- AD INTELLIGENCE (2.0x) --- highest-value task type
        self.register(TaskDefinition(
            task_type=TaskType.AD_INTELLIGENCE,
            name="Ad Intelligence Extraction",
            description="Extract ad placements, networks, bid signals, and targeting data from pages",
            default_timeout_ms=90000,
            max_retries=2,
            requires_market=True,
            payout_multiplier=2.0,
            navigation_steps=[
                {"command": "navigate", "params": {"url_template": "https://www.google.{domain}/search?q={query}&gl={market_lower}"}},
                {"command": "wait_for", "params": {"selector": "#search, #rso, .ads-ad", "timeout_ms": 15000}},
                {"command": "wait_timeout", "params": {"ms": 3000}},
                {"command": "scroll", "params": {"direction": "down", "amount": 5}},
                {"command": "extract_all", "params": {"selector": ".ads-ad, [data-text-ad], .commercial-unit-desktop-top, .pla-unit, [data-ad-slot], [id^='aswift_'], iframe[id^='google_ads']"}},
                {"command": "screenshot", "params": {}}
            ],
            extraction_rules=[
                ExtractionRule(field_name="advertiser", selector=".ads-ad .x2VHCd, [data-text-ad] .cfxYMc, .ad-title", attribute="text", transform="strip", required=True, multiple=True),
                ExtractionRule(field_name="ad_text", selector=".ads-ad .MUxGbd, [data-text-ad] .yDYNvb", attribute="text", transform="strip", multiple=True),
                ExtractionRule(field_name="ad_url", selector=".ads-ad a[data-rw], [data-text-ad] a", attribute="href", multiple=True),
                ExtractionRule(field_name="ad_position", selector=".ads-ad", attribute="data-ad-slot", transform="strip", multiple=True),
                ExtractionRule(field_name="ad_display_url", selector=".ads-ad .qzEoUe, .ad-display-url", attribute="text", transform="strip", multiple=True),
                ExtractionRule(field_name="ad_extensions", selector=".ads-ad .bOeY0b, .ad-extensions", attribute="text", transform="strip", multiple=True),
                ExtractionRule(field_name="shopping_ad_price", selector=".pla-unit .e10twf, .shopping-ad-price", attribute="text", transform="currency", multiple=True),
                ExtractionRule(field_name="shopping_ad_merchant", selector=".pla-unit .LbUacb, .shopping-ad-merchant", attribute="text", transform="strip", multiple=True),
            ]
        ))

        # --- PRICING INTELLIGENCE DEEP (1.8x) ---
        self.register(TaskDefinition(
            task_type=TaskType.PRICING_INTELLIGENCE_DEEP,
            name="Deep Pricing Intelligence",
            description="Multi-competitor deep pricing extraction with change tracking",
            default_timeout_ms=120000,
            max_retries=3,
            requires_market=True,
            payout_multiplier=1.8,
            navigation_steps=[
                {"command": "navigate", "params": {"url_template": "https://www.google.{domain}/search?q={query}+price&tbm=shop&gl={market_lower}"}},
                {"command": "wait_for", "params": {"selector": ".sh-dgr__content, [data-docid]", "timeout_ms": 15000}},
                {"command": "wait_timeout", "params": {"ms": 3000}},
                {"command": "scroll", "params": {"direction": "down", "amount": 6}},
                {"command": "extract_all", "params": {"selector": ".sh-dgr__content, .sh-dlr__list-result, [data-docid]"}},
                {"command": "screenshot", "params": {}}
            ],
            extraction_rules=[
                ExtractionRule(field_name="product_title", selector="h3, .tAxDx, [data-name]", attribute="text", transform="strip", required=True, multiple=True),
                ExtractionRule(field_name="price", selector=".a8Pemb, .HRLxBb, [data-price]", attribute="text", transform="currency", required=True, multiple=True),
                ExtractionRule(field_name="original_price", selector=".Tlae9b, .original-price, [data-original-price]", attribute="text", transform="currency", multiple=True),
                ExtractionRule(field_name="seller", selector=".aULzUe, .IuHnof, [data-merchant]", attribute="text", transform="strip", required=True, multiple=True),
                ExtractionRule(field_name="seller_rating", selector=".Rsc7Yb, [data-rating]", attribute="text", transform="number", multiple=True),
                ExtractionRule(field_name="shipping_info", selector=".vEjMR, [data-shipping]", attribute="text", transform="strip", multiple=True),
                ExtractionRule(field_name="availability", selector="[data-availability], .availability", attribute="text", transform="strip", multiple=True),
                ExtractionRule(field_name="product_url", selector="a.shntl, a[href*='/shopping/']", attribute="href", multiple=True),
                ExtractionRule(field_name="price_history_signal", selector=".price-drop, [data-price-change]", attribute="text", transform="strip", multiple=True),
            ]
        ))

        # --- SOCIAL SIGNAL EXTRACT (1.5x) ---
        self.register(TaskDefinition(
            task_type=TaskType.SOCIAL_SIGNAL_EXTRACT,
            name="Social Signal Extraction",
            description="Extract social engagement metrics, trending topics, and sentiment signals",
            default_timeout_ms=60000,
            max_retries=2,
            requires_market=True,
            payout_multiplier=1.5,
            navigation_steps=[
                {"command": "navigate", "params": {"url_template": "https://www.google.{domain}/search?q={query}&tbm=nws&gl={market_lower}"}},
                {"command": "wait_for", "params": {"selector": "#search, #rso, .SoaBEf", "timeout_ms": 12000}},
                {"command": "wait_timeout", "params": {"ms": 2000}},
                {"command": "scroll", "params": {"direction": "down", "amount": 3}},
                {"command": "extract_all", "params": {"selector": ".SoaBEf, .WlydOe, [data-hveid] .g"}},
                {"command": "screenshot", "params": {}}
            ],
            extraction_rules=[
                ExtractionRule(field_name="headline", selector=".mCBkyc, .JheGif, h3", attribute="text", transform="strip", required=True, multiple=True),
                ExtractionRule(field_name="source", selector=".NUnG9d, .CEMjEf", attribute="text", transform="strip", multiple=True),
                ExtractionRule(field_name="timestamp", selector=".OSrXXb, .WG9SHc", attribute="text", transform="strip", multiple=True),
                ExtractionRule(field_name="snippet", selector=".GI74Re, .Y3v8qd", attribute="text", transform="strip", multiple=True),
                ExtractionRule(field_name="article_url", selector="a[href]:first-child", attribute="href", multiple=True),
                ExtractionRule(field_name="image_url", selector="img.YQ4gaf, img[src*='news']", attribute="src", multiple=True),
            ]
        ))

        # --- AUDIENCE PROFILE EXTRACT (1.7x) ---
        self.register(TaskDefinition(
            task_type=TaskType.AUDIENCE_PROFILE_EXTRACT,
            name="Audience Profile Extraction",
            description="Extract anonymized audience demographics and interest data from visited sites",
            default_timeout_ms=75000,
            max_retries=2,
            requires_market=True,
            payout_multiplier=1.7,
            navigation_steps=[
                {"command": "navigate", "params": {"url_template": "https://www.google.{domain}/search?q={query}&gl={market_lower}"}},
                {"command": "wait_for", "params": {"selector": "#search, #rso", "timeout_ms": 12000}},
                {"command": "wait_timeout", "params": {"ms": 2000}},
                {"command": "scroll", "params": {"direction": "down", "amount": 4}},
                {"command": "extract_all", "params": {"selector": ".g, [data-hveid], .kp-wholepage, .knowledge-panel"}},
                {"command": "screenshot", "params": {}}
            ],
            extraction_rules=[
                ExtractionRule(field_name="content_category", selector=".kp-header .Z0LcW, .knowledge-panel h2", attribute="text", transform="strip", multiple=True),
                ExtractionRule(field_name="related_topics", selector=".k8XOCe, [data-entityname], .related-question", attribute="text", transform="strip", multiple=True),
                ExtractionRule(field_name="people_also_ask", selector=".related-question-pair .CSkcDe, [data-q]", attribute="text", transform="strip", multiple=True),
                ExtractionRule(field_name="related_searches", selector=".k8XOCe a, #brs a, .s75CSd a", attribute="text", transform="strip", multiple=True),
                ExtractionRule(field_name="content_language", selector="html", attribute="lang", transform="strip"),
                ExtractionRule(field_name="trending_interest", selector=".EPLo7e, [data-interest]", attribute="text", transform="strip", multiple=True),
            ]
        ))

        # --- RETAIL SHELF MONITOR (1.6x) ---
        self.register(TaskDefinition(
            task_type=TaskType.RETAIL_SHELF_MONITOR,
            name="Retail Shelf Monitor",
            description="Product placement, availability, and promotion tracking on retail sites",
            default_timeout_ms=90000,
            max_retries=2,
            requires_market=True,
            payout_multiplier=1.6,
            navigation_steps=[
                {"command": "navigate", "params": {"url_template": "https://www.google.{domain}/search?q={query}+buy&tbm=shop&gl={market_lower}"}},
                {"command": "wait_for", "params": {"selector": ".sh-dgr__content, [data-docid], .commercial-unit-desktop-top", "timeout_ms": 15000}},
                {"command": "wait_timeout", "params": {"ms": 3000}},
                {"command": "scroll", "params": {"direction": "down", "amount": 5}},
                {"command": "extract_all", "params": {"selector": ".sh-dgr__content, .sh-dlr__list-result, .commercial-unit-desktop-top, [data-docid]"}},
                {"command": "screenshot", "params": {}}
            ],
            extraction_rules=[
                ExtractionRule(field_name="product_title", selector="h3, .tAxDx, [data-name]", attribute="text", transform="strip", required=True, multiple=True),
                ExtractionRule(field_name="price", selector=".a8Pemb, .HRLxBb, [data-price]", attribute="text", transform="currency", required=True, multiple=True),
                ExtractionRule(field_name="seller", selector=".aULzUe, .IuHnof, [data-merchant]", attribute="text", transform="strip", multiple=True),
                ExtractionRule(field_name="in_stock", selector=".vEjMR, [data-availability]", attribute="text", transform="strip", multiple=True),
                ExtractionRule(field_name="promotion", selector=".promotional-label, .sale-badge, [data-promo]", attribute="text", transform="strip", multiple=True),
                ExtractionRule(field_name="position_rank", selector="", attribute="index", transform="number", multiple=True),
                ExtractionRule(field_name="product_image", selector="img[src*='shopping'], img[data-src]", attribute="src", multiple=True),
                ExtractionRule(field_name="product_url", selector="a.shntl, a[href*='/shopping/']", attribute="href", multiple=True),
            ]
        ))

        # --- COMPETITOR AD TRACK (1.9x) ---
        self.register(TaskDefinition(
            task_type=TaskType.COMPETITOR_AD_TRACK,
            name="Competitor Ad Tracking",
            description="Track competitor ad spend, placement, and copy across search engines",
            default_timeout_ms=90000,
            max_retries=2,
            requires_market=True,
            payout_multiplier=1.9,
            navigation_steps=[
                {"command": "navigate", "params": {"url_template": "https://www.google.{domain}/search?q={query}&gl={market_lower}"}},
                {"command": "wait_for", "params": {"selector": "#search, .ads-ad, [data-text-ad]", "timeout_ms": 15000}},
                {"command": "wait_timeout", "params": {"ms": 3000}},
                {"command": "scroll", "params": {"direction": "down", "amount": 4}},
                {"command": "extract_all", "params": {"selector": ".ads-ad, [data-text-ad], .commercial-unit-desktop-top, .pla-unit"}},
                {"command": "screenshot", "params": {}}
            ],
            extraction_rules=[
                ExtractionRule(field_name="competitor_name", selector=".ads-ad .x2VHCd, [data-text-ad] .cfxYMc", attribute="text", transform="strip", required=True, multiple=True),
                ExtractionRule(field_name="ad_headline", selector=".ads-ad .sVXRqc, [data-text-ad] h3", attribute="text", transform="strip", required=True, multiple=True),
                ExtractionRule(field_name="ad_description", selector=".ads-ad .MUxGbd, [data-text-ad] .yDYNvb", attribute="text", transform="strip", multiple=True),
                ExtractionRule(field_name="display_url", selector=".ads-ad .qzEoUe, .ads-ad cite", attribute="text", transform="strip", multiple=True),
                ExtractionRule(field_name="landing_url", selector=".ads-ad a[data-rw], [data-text-ad] a", attribute="href", multiple=True),
                ExtractionRule(field_name="ad_position", selector="", attribute="index", transform="number", multiple=True),
                ExtractionRule(field_name="ad_extensions", selector=".ads-ad .bOeY0b, .ad-sitelinks", attribute="text", transform="strip", multiple=True),
                ExtractionRule(field_name="keyword_targeted", selector="em, b", attribute="text", transform="strip", multiple=True),
            ]
        ))

    def register(self, definition: TaskDefinition):
        """Register a task type definition."""
        key = definition.task_type.value
        self._definitions[key] = definition
        logger.info(f"Registered task type: {key} ({definition.name})")

    def get(self, task_type: str) -> Optional[TaskDefinition]:
        """Get task definition by type string."""
        return self._definitions.get(task_type)

    def list_types(self) -> List[Dict[str, Any]]:
        """List all registered task types."""
        return [
            {
                "type": d.task_type.value,
                "name": d.name,
                "description": d.description,
                "requires_market": d.requires_market,
                "requires_auth": d.requires_auth,
                "payout_multiplier": d.payout_multiplier,
                "timeout_ms": d.default_timeout_ms,
            }
            for d in self._definitions.values()
        ]

    def create_task(self, task_type: str, params: Dict[str, Any],
                    market: str = "", priority: int = TaskPriority.NORMAL.value,
                    requester_user_id: int = None,
                    requester_type: str = "portal") -> CitizenSERPTask:
        """
        Create a concrete task instance from a task type + params.
        """
        definition = self._definitions.get(task_type)
        if not definition:
            raise ValueError(f"Unknown task type: {task_type}")

        if definition.requires_market and not market:
            raise ValueError(f"Task type '{task_type}' requires a target market")

        return CitizenSERPTask(
            task_id="",  # Auto-generated in __post_init__
            task_type=task_type,
            params=params,
            market=market,
            priority=priority,
            timeout_ms=definition.default_timeout_ms,
            max_retries=definition.max_retries,
            payout_multiplier=definition.payout_multiplier,
            requester_user_id=requester_user_id,
            requester_type=requester_type,
        )


# ============================================================
# Market Configuration — currency + language per country
# ============================================================

MARKET_CONFIG = {
    "US": {"currency": "USD", "lang": "en", "domain": "google.com"},
    "GB": {"currency": "GBP", "lang": "en", "domain": "google.co.uk"},
    "JP": {"currency": "JPY", "lang": "ja", "domain": "google.co.jp"},
    "DE": {"currency": "EUR", "lang": "de", "domain": "google.de"},
    "FR": {"currency": "EUR", "lang": "fr", "domain": "google.fr"},
    "ES": {"currency": "EUR", "lang": "es", "domain": "google.es"},
    "IT": {"currency": "EUR", "lang": "it", "domain": "google.it"},
    "BR": {"currency": "BRL", "lang": "pt", "domain": "google.com.br"},
    "IN": {"currency": "INR", "lang": "en", "domain": "google.co.in"},
    "AU": {"currency": "AUD", "lang": "en", "domain": "google.com.au"},
    "CA": {"currency": "CAD", "lang": "en", "domain": "google.ca"},
    "MX": {"currency": "MXN", "lang": "es", "domain": "google.com.mx"},
    "KR": {"currency": "KRW", "lang": "ko", "domain": "google.co.kr"},
    "SG": {"currency": "SGD", "lang": "en", "domain": "google.com.sg"},
    "HK": {"currency": "HKD", "lang": "zh", "domain": "google.com.hk"},
    "TH": {"currency": "THB", "lang": "th", "domain": "google.co.th"},
    "MY": {"currency": "MYR", "lang": "ms", "domain": "google.com.my"},
    "PH": {"currency": "PHP", "lang": "en", "domain": "google.com.ph"},
    "ID": {"currency": "IDR", "lang": "id", "domain": "google.co.id"},
    "VN": {"currency": "VND", "lang": "vi", "domain": "google.com.vn"},
    "TR": {"currency": "TRY", "lang": "tr", "domain": "google.com.tr"},
    "AE": {"currency": "AED", "lang": "en", "domain": "google.ae"},
    "SA": {"currency": "SAR", "lang": "ar", "domain": "google.com.sa"},
    "ZA": {"currency": "ZAR", "lang": "en", "domain": "google.co.za"},
    "NG": {"currency": "NGN", "lang": "en", "domain": "google.com.ng"},
    "EG": {"currency": "EGP", "lang": "ar", "domain": "google.com.eg"},
    "PL": {"currency": "PLN", "lang": "pl", "domain": "google.pl"},
    "SE": {"currency": "SEK", "lang": "sv", "domain": "google.se"},
    "NO": {"currency": "NOK", "lang": "no", "domain": "google.no"},
    "DK": {"currency": "DKK", "lang": "da", "domain": "google.dk"},
    "FI": {"currency": "EUR", "lang": "fi", "domain": "google.fi"},
    "NL": {"currency": "EUR", "lang": "nl", "domain": "google.nl"},
    "CH": {"currency": "CHF", "lang": "de", "domain": "google.ch"},
    "AT": {"currency": "EUR", "lang": "de", "domain": "google.at"},
    "PT": {"currency": "EUR", "lang": "pt", "domain": "google.pt"},
    "GR": {"currency": "EUR", "lang": "el", "domain": "google.gr"},
    "CZ": {"currency": "CZK", "lang": "cs", "domain": "google.cz"},
    "RO": {"currency": "RON", "lang": "ro", "domain": "google.ro"},
    "CL": {"currency": "CLP", "lang": "es", "domain": "google.cl"},
    "CO": {"currency": "COP", "lang": "es", "domain": "google.com.co"},
    "AR": {"currency": "ARS", "lang": "es", "domain": "google.com.ar"},
    "PE": {"currency": "PEN", "lang": "es", "domain": "google.com.pe"},
    "NZ": {"currency": "NZD", "lang": "en", "domain": "google.co.nz"},
    "IE": {"currency": "EUR", "lang": "en", "domain": "google.ie"},
    "IL": {"currency": "ILS", "lang": "he", "domain": "google.co.il"},
}


def get_market_config(market: str) -> Dict[str, str]:
    """Get currency/language/domain config for a market or zone.
    Zone codes (e.g. 'US-NE') inherit from their parent country ('US').
    """
    code = market.upper()
    # Direct match (country code)
    if code in MARKET_CONFIG:
        return MARKET_CONFIG[code]
    # Zone code — extract country prefix
    if "-" in code:
        country = code.split("-")[0]
        if country in MARKET_CONFIG:
            return MARKET_CONFIG[country]
    return {"currency": "USD", "lang": "en", "domain": "google.com"}


# ============================================================
# Task Dispatcher — routes tasks to available CitizenSERP nodes
# ============================================================

class TaskDispatcher:
    """
    Routes CitizenSERP tasks to available nodes.

    Responsibilities:
    - Find best available node for a task (by market + capability)
    - Track dispatched tasks and their status
    - Handle retries on failure
    - Aggregate results from multi-market dispatches
    - Record task completion for payout calculation
    """

    def __init__(self):
        self._active_tasks: Dict[str, CitizenSERPTask] = {}
        self._task_results: Dict[str, TaskResult] = {}
        self._stats = {
            "total_dispatched": 0,
            "total_completed": 0,
            "total_failed": 0,
            "total_timed_out": 0,
            "by_type": {},
        }

    def find_available_node(self, market: str, task_type: str = None) -> Optional[Dict[str, Any]]:
        """
        Find the best available CitizenSERP node for a given market or zone.

        Accepts both:
        - Country codes: "US" → any node in the US
        - Zone codes: "US-NE" → nodes in US Northeast (zone_code match or city match)

        Strategy:
        1. Try node_registry.discover_nodes() first (in-memory, fast)
        2. Fall back to DB queries if registry is empty (cold start)
        """
        code = market.upper()

        # --- Strategy 1: Node Registry (in-memory, preferred) ---
        try:
            from node_registry import node_registry
            nodes = node_registry.discover_nodes(
                market=code, task_type=task_type, limit=5
            )
            if nodes:
                best = nodes[0]
                logger.debug(f"Registry found node {best['node_id']} for {code}")
                return {
                    "user_id": best["user_id"],
                    "country_code": best.get("country_code", ""),
                    "zone_code": best.get("zone_code", ""),
                    "wallet_address": best.get("wallet_address", ""),
                    "rating": best.get("success_rate", 0.0),
                    "successful_transactions": best.get("tasks_completed", 0),
                    "node_id": best["node_id"],
                }
        except Exception as e:
            logger.debug(f"Registry lookup skipped: {e}")

        # --- Strategy 2: DB Fallback (cold start / registry empty) ---
        try:
            from models import db, HelperProfile, UserWallet

            is_zone = "-" in code

            if is_zone:
                # Zone-level search: match by zone_code first
                helpers = HelperProfile.query.filter(
                    HelperProfile.zone_code == code,
                    HelperProfile.is_active == True,
                    HelperProfile.is_approved == True,
                    HelperProfile.is_online == True,
                ).order_by(
                    HelperProfile.average_rating.desc(),
                    HelperProfile.successful_transactions.desc(),
                ).all()

                # Fallback: if no zone-tagged nodes, try city matching
                if not helpers:
                    try:
                        from geographic_zones import get_zone
                        zone = get_zone(code)
                        if zone and zone.cities:
                            country = code.split("-")[0]
                            helpers = HelperProfile.query.filter(
                                HelperProfile.country_code == country,
                                HelperProfile.is_active == True,
                                HelperProfile.is_approved == True,
                                HelperProfile.is_online == True,
                                db.func.lower(HelperProfile.city).in_(zone.cities),
                            ).order_by(
                                HelperProfile.average_rating.desc(),
                                HelperProfile.successful_transactions.desc(),
                            ).all()
                    except ImportError:
                        pass

                # Final fallback: any node in the country
                if not helpers:
                    country = code.split("-")[0]
                    helpers = HelperProfile.query.filter_by(
                        country_code=country,
                        is_active=True,
                        is_approved=True,
                        is_online=True,
                    ).order_by(
                        HelperProfile.average_rating.desc(),
                        HelperProfile.successful_transactions.desc(),
                    ).all()
                    if helpers:
                        logger.info(f"Zone {code}: no zone nodes, falling back to country {country}")
            else:
                # Country-level search (original behavior)
                helpers = HelperProfile.query.filter_by(
                    country_code=code,
                    is_active=True,
                    is_approved=True,
                    is_online=True,
                ).order_by(
                    HelperProfile.average_rating.desc(),
                    HelperProfile.successful_transactions.desc(),
                ).all()

            if not helpers:
                logger.warning(f"No nodes available in market {market}")
                return None

            # Find first helper with a verified wallet and available quota
            for helper in helpers:
                wallet = UserWallet.query.filter_by(
                    user_id=helper.user_id,
                    is_primary=True,
                    is_verified=True
                ).first()
                if wallet:
                    if helper.transactions_today < helper.max_daily_transactions:
                        return {
                            "user_id": helper.user_id,
                            "country_code": helper.country_code,
                            "zone_code": helper.zone_code,
                            "wallet_address": wallet.wallet_address,
                            "rating": float(helper.average_rating),
                            "successful_transactions": helper.successful_transactions,
                        }

            logger.warning(f"No eligible nodes in market {market} (all at quota or no wallet)")
            return None

        except Exception as e:
            logger.error(f"Error finding node for market {market}: {e}")
            return None

    def dispatch(self, task: CitizenSERPTask) -> Optional[str]:
        """
        Dispatch a task to the best available node.
        Returns task_id if dispatched, None if no node available.
        """
        node = self.find_available_node(task.market, task.task_type)
        if not node:
            task.status = TaskStatus.FAILED.value
            task.error = f"No available nodes in market {task.market}"
            logger.warning(f"Task {task.task_id} failed: {task.error}")
            return None

        task.node_user_id = node["user_id"]
        task.status = TaskStatus.DISPATCHED.value
        task.dispatched_at = datetime.utcnow().isoformat()

        self._active_tasks[task.task_id] = task
        self._stats["total_dispatched"] += 1
        type_key = task.task_type
        self._stats["by_type"].setdefault(type_key, {"dispatched": 0, "completed": 0, "failed": 0})
        self._stats["by_type"][type_key]["dispatched"] += 1

        logger.info(
            f"Task {task.task_id} ({task.task_type}) dispatched to node "
            f"{node['user_id']} in {task.market}"
        )
        return task.task_id

    async def dispatch_and_wait(
        self, task: "CitizenSERPTask", timeout_ms: int = 60_000,
    ) -> Optional[Any]:
        """Dispatch a task and asynchronously wait for its result.

        Polls ``_task_results`` until the task completes or *timeout_ms*
        elapses.  Used by the data-source resolver's async callers.

        Returns the :class:`TaskResult` on success, ``None`` on timeout
        or failure.
        """
        task_id = self.dispatch(task)
        if not task_id:
            return None

        timeout_s = timeout_ms / 1000.0
        poll_interval = 0.5
        start = time.time()

        while (time.time() - start) < timeout_s:
            result = self._task_results.get(task_id)
            if result is not None:
                return result

            task_obj = self._active_tasks.get(task_id)
            if task_obj and task_obj.status in ("failed", "timed_out", "cancelled"):
                return None

            await asyncio.sleep(poll_interval)

        return None  # Timeout

    def dispatch_multi_market(self, task_type: str, params: Dict[str, Any],
                               markets: List[str], priority: int = TaskPriority.NORMAL.value,
                               requester_user_id: int = None,
                               requester_type: str = "portal") -> Dict[str, Any]:
        """
        Dispatch the same task to multiple markets simultaneously.
        Returns {task_ids: [...], dispatched: N, failed_markets: [...]}
        """
        task_ids = []
        failed_markets = []

        for market in markets:
            try:
                task = task_registry.create_task(
                    task_type=task_type,
                    params=params,
                    market=market,
                    priority=priority,
                    requester_user_id=requester_user_id,
                    requester_type=requester_type,
                )
                result = self.dispatch(task)
                if result:
                    task_ids.append(result)
                else:
                    failed_markets.append(market)
            except Exception as e:
                logger.error(f"Failed to dispatch to market {market}: {e}")
                failed_markets.append(market)

        return {
            "task_ids": task_ids,
            "dispatched": len(task_ids),
            "failed_markets": failed_markets,
            "total_markets": len(markets),
        }

    def record_result(self, task_id: str, result: TaskResult):
        """Record the result of a completed task."""
        task = self._active_tasks.get(task_id)
        if not task:
            logger.warning(f"Result for unknown task: {task_id}")
            return

        task.result_data = result.data
        task.execution_time_ms = result.execution_time_ms
        task.completed_at = datetime.utcnow().isoformat()

        if result.success:
            task.status = TaskStatus.COMPLETED.value
            self._stats["total_completed"] += 1
            type_key = task.task_type
            if type_key in self._stats["by_type"]:
                self._stats["by_type"][type_key]["completed"] += 1
        else:
            # Check if we should retry
            if task.retries_used < task.max_retries:
                task.retries_used += 1
                task.status = TaskStatus.QUEUED.value
                task.error = result.error
                logger.info(f"Task {task_id} retry {task.retries_used}/{task.max_retries}: {result.error}")
                # Re-dispatch
                self.dispatch(task)
                return
            else:
                task.status = TaskStatus.FAILED.value
                task.error = result.error
                self._stats["total_failed"] += 1
                type_key = task.task_type
                if type_key in self._stats["by_type"]:
                    self._stats["by_type"][type_key]["failed"] += 1

        self._task_results[task_id] = result

        # Record for payout calculation
        self._record_node_task_completion(task, result)

        logger.info(
            f"Task {task_id} {'completed' if result.success else 'failed'} "
            f"in {result.execution_time_ms}ms"
        )

    def _record_node_task_completion(self, task: CitizenSERPTask, result: TaskResult):
        """Record task completion for node payout tracking + feed intelligence."""
        if not task.node_user_id:
            return

        try:
            logger.debug(
                f"Node {task.node_user_id} completed {task.task_type} task "
                f"({task.payout_multiplier}x multiplier)"
            )
        except Exception as e:
            logger.error(f"Error recording node task: {e}")

        if not result.success:
            return

        # Feed intelligence feedback loop with task results
        try:
            from intelligence_feedback import feedback_engine
            feedback_engine.ingest_task_result(task.to_dict(), asdict(result))
        except Exception as e:
            logger.debug(f"Feedback ingestion skipped: {e}")

        # Process results through vertical pipeline
        try:
            from vertical_pipelines import pipeline_manager
            if result.data and isinstance(result.data, dict):
                results_list = result.data.get("results", [])
                if results_list:
                    processed = pipeline_manager.process(
                        task.task_type, results_list, task.market
                    )
                    if processed and not processed.get("error"):
                        self._task_results[task.task_id] = TaskResult(
                            success=True,
                            data={**result.data, "pipeline": processed},
                            execution_time_ms=result.execution_time_ms,
                        )
        except Exception as e:
            logger.debug(f"Pipeline processing skipped: {e}")

        # Notify node registry of task completion
        try:
            from node_registry import node_registry
            node_registry.complete_task(task.node_user_id, task.task_id)
        except Exception as e:
            logger.debug(f"Node registry update skipped: {e}")

        # Record data extraction for yield dashboard (Build #65)
        try:
            from node_yield_dashboard import yield_dashboard
            if result.data and isinstance(result.data, dict):
                items = result.data.get("results", [])
                yield_dashboard.record_extraction(
                    user_id=task.node_user_id,
                    session_id=None,
                    task_id=task.task_id,
                    task_type=task.task_type,
                    records_extracted=len(items) if isinstance(items, list) else result.extracted_items,
                    data_points=sum(len(item) for item in items) if isinstance(items, list) else 0,
                    quality_score=70,
                )
        except Exception as e:
            logger.debug(f"Yield dashboard recording skipped: {e}")

        # Feed ad intelligence pipeline (Build #65)
        if task.task_type in ("ad_intelligence", "competitor_ad_track"):
            try:
                from ad_intelligence import ad_intelligence_engine
                ad_intelligence_engine.ingest_task_result(task.to_dict(), asdict(result))
            except Exception as e:
                logger.debug(f"Ad intelligence ingestion skipped: {e}")

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get task status and result."""
        task = self._active_tasks.get(task_id)
        if not task:
            return None
        d = task.to_dict()
        result = self._task_results.get(task_id)
        if result:
            d["result"] = asdict(result)
        return d

    def get_active_tasks(self, market: str = None, task_type: str = None) -> List[Dict[str, Any]]:
        """List active tasks, optionally filtered."""
        tasks = []
        for task in self._active_tasks.values():
            if task.status in (TaskStatus.COMPLETED.value, TaskStatus.FAILED.value,
                               TaskStatus.CANCELLED.value, TaskStatus.TIMED_OUT.value):
                continue
            if market and task.market != market.upper():
                continue
            if task_type and task.task_type != task_type:
                continue
            tasks.append(task.to_dict())
        return tasks

    def get_stats(self) -> Dict[str, Any]:
        """Get dispatcher statistics."""
        return {
            **self._stats,
            "active_tasks": len([
                t for t in self._active_tasks.values()
                if t.status not in (TaskStatus.COMPLETED.value, TaskStatus.FAILED.value,
                                    TaskStatus.CANCELLED.value, TaskStatus.TIMED_OUT.value)
            ]),
        }

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a pending/dispatched task."""
        task = self._active_tasks.get(task_id)
        if not task:
            return False
        if task.status in (TaskStatus.COMPLETED.value, TaskStatus.FAILED.value):
            return False
        task.status = TaskStatus.CANCELLED.value
        task.completed_at = datetime.utcnow().isoformat()
        return True

    def cleanup_stale(self, max_age_minutes: int = 30):
        """Remove stale tasks that exceeded their timeout."""
        now = datetime.utcnow()
        stale_ids = []
        for task_id, task in self._active_tasks.items():
            if task.status in (TaskStatus.COMPLETED.value, TaskStatus.FAILED.value,
                               TaskStatus.CANCELLED.value, TaskStatus.TIMED_OUT.value):
                # Clean up old completed tasks (keep for 1 hour)
                if task.completed_at:
                    try:
                        completed = datetime.fromisoformat(task.completed_at)
                        if (now - completed).total_seconds() > 3600:
                            stale_ids.append(task_id)
                    except (ValueError, TypeError):
                        pass
                continue
            # Check dispatched time for active tasks
            if task.dispatched_at:
                try:
                    dispatched = datetime.fromisoformat(task.dispatched_at)
                    if (now - dispatched).total_seconds() > max_age_minutes * 60:
                        task.status = TaskStatus.TIMED_OUT.value
                        task.completed_at = now.isoformat()
                        self._stats["total_timed_out"] += 1
                        stale_ids.append(task_id)
                        logger.warning(f"Task {task_id} timed out after {max_age_minutes}m")
                except (ValueError, TypeError):
                    pass

        for task_id in stale_ids:
            self._task_results.pop(task_id, None)
            self._active_tasks.pop(task_id, None)

        if stale_ids:
            logger.info(f"Cleaned up {len(stale_ids)} stale tasks")


# ============================================================
# Module-level singletons
# ============================================================

task_registry = TaskRegistry()
task_dispatcher = TaskDispatcher()
