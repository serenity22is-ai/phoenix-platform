"""
Module Registry — Dynamic API module discovery, loading, and management.

Each API integration (Picasso, Duffel, Kiwi, Mystifly, etc.) is a module
with a knowledge card. The registry manages the lifecycle:

1. Register modules (manually or via AutoLearner)
2. Check credential status (configured vs unconfigured)
3. Load/unload modules dynamically
4. Provide module metadata to the Director for wiring

Knowledge cards are structured metadata files that teach ANASTASiA
about each API's capabilities, auth, data formats, and quirks.
The Director reads these to make intelligent routing decisions.

MYSTES KYRIOS LLC — Confidential.
"""

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("anastasia.modules.registry")


class VerticalType(str, Enum):
    """Travel verticals that modules can serve."""
    FLIGHTS = "flights"
    HOTELS = "hotels"
    CAR_RENTAL = "car_rental"
    CRUISES = "cruises"
    INSURANCE = "insurance"
    ACTIVITIES = "activities"
    TRANSFERS = "transfers"


class SourceType(str, Enum):
    """Distribution channel type."""
    GDS = "gds"                    # Amadeus, Sabre, Travelport via consolidator
    NDC = "ndc"                    # Direct airline NDC connections
    AGGREGATOR = "aggregator"      # Kiwi, TripStack — multi-source aggregation
    DIRECT = "direct"              # Direct supplier API
    WHOLESALER = "wholesaler"      # Hotelbeds, Expedia Rapid
    OTA = "ota"                    # OTA-to-OTA rates


class AuthType(str, Enum):
    """Authentication method required by the API."""
    API_KEY_HEADER = "api_key_header"        # Kiwi: apikey header
    BEARER_TOKEN = "bearer_token"            # Duffel: Authorization Bearer
    SESSION_TOKEN = "session_token"          # Picasso: cookie-based session
    OAUTH2 = "oauth2"                        # Standard OAuth2 flow
    BASIC_AUTH = "basic_auth"                # HTTP Basic
    CUSTOM = "custom"                        # Non-standard auth


@dataclass
class KnowledgeCard:
    """
    Structured metadata about an API module.

    ANASTASiA reads knowledge cards to understand:
    - What the module can do (capabilities)
    - How to authenticate (auth)
    - What data format to expect (schemas)
    - Known quirks and workarounds
    - When to prefer this module over others (routing hints)

    Knowledge cards are the bridge between the AutoLearner (which
    discovers APIs) and the Director (which wires them together).
    """
    # Identity
    module_id: str                          # Unique ID (e.g., "duffel_ndc")
    name: str                               # Display name (e.g., "Duffel NDC")
    vendor: str                             # Provider (e.g., "Duffel")
    version: str = "1.0"

    # Classification
    vertical: str = VerticalType.FLIGHTS.value
    source_type: str = SourceType.NDC.value

    # Authentication
    auth_type: str = AuthType.BEARER_TOKEN.value
    credential_env_vars: List[str] = field(default_factory=list)  # e.g. ["DUFFEL_ACCESS_TOKEN"]
    auth_notes: str = ""

    # Capabilities
    capabilities: Dict[str, bool] = field(default_factory=dict)
    # e.g. {"search": True, "book": True, "cancel": True, "change": True,
    #        "seat_map": True, "ancillaries": True, "multi_city": False,
    #        "pos_arbitrage": False, "virtual_interlining": False}

    # Coverage
    carrier_count: int = 0                  # How many carriers/suppliers
    coverage_notes: str = ""                # e.g. "300+ NDC airlines"
    geographic_focus: str = "global"        # global, regional, specific

    # Data format
    date_format: str = "YYYY-MM-DD"         # Input date format
    currency_param: str = "currency"        # How to set currency
    passenger_format: Dict[str, Any] = field(default_factory=dict)
    # e.g. {"name_fields": ["given_name", "family_name"],
    #        "gender_values": ["m", "f"], "dob_format": "YYYY-MM-DD"}

    # Pricing model
    pricing_model: str = "commission"       # commission, net_fare, markup, flat_fee
    pricing_notes: str = ""

    # Routing hints (for Director)
    priority: int = 50                      # 0-100, higher = prefer (GDS arbitrage = 100)
    strengths: List[str] = field(default_factory=list)
    # e.g. ["pos_arbitrage", "consolidator_fares", "102_country_pos"]
    weaknesses: List[str] = field(default_factory=list)
    # e.g. ["no_ndc", "session_based_auth"]
    best_for: List[str] = field(default_factory=list)
    # e.g. ["international_arbitrage", "gds_consolidator_fares"]

    # Quirks
    quirks: List[Dict[str, str]] = field(default_factory=list)
    # e.g. [{"issue": "dates must be DD/MM/YYYY", "workaround": "convert before sending"}]

    # Booking flow
    booking_steps: List[str] = field(default_factory=list)
    # e.g. ["search", "validate", "book", "confirm_payment"]
    booking_notes: str = ""

    # Status
    readiness: str = "tested"               # discovered, probed, tested, production
    confidence: float = 0.9
    last_updated: str = ""
    learned_from: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize for storage or API response."""
        return {
            "module_id": self.module_id,
            "name": self.name,
            "vendor": self.vendor,
            "version": self.version,
            "vertical": self.vertical,
            "source_type": self.source_type,
            "auth_type": self.auth_type,
            "credential_env_vars": self.credential_env_vars,
            "capabilities": self.capabilities,
            "carrier_count": self.carrier_count,
            "coverage_notes": self.coverage_notes,
            "pricing_model": self.pricing_model,
            "priority": self.priority,
            "strengths": self.strengths,
            "weaknesses": self.weaknesses,
            "best_for": self.best_for,
            "quirks": self.quirks,
            "booking_steps": self.booking_steps,
            "readiness": self.readiness,
            "confidence": self.confidence,
            "passenger_format": self.passenger_format,
            "date_format": self.date_format,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "KnowledgeCard":
        """Deserialize from storage."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def to_prompt(self) -> str:
        """Generate a natural language summary for Claude's system prompt."""
        caps = ", ".join(k for k, v in self.capabilities.items() if v)
        lines = [
            f"### {self.name} ({self.source_type.upper()})",
            f"- **Vendor**: {self.vendor}",
            f"- **Coverage**: {self.coverage_notes or f'{self.carrier_count} carriers'}",
            f"- **Capabilities**: {caps}",
            f"- **Auth**: {self.auth_type} via {', '.join(self.credential_env_vars)}",
            f"- **Pricing**: {self.pricing_model} — {self.pricing_notes}" if self.pricing_notes else f"- **Pricing**: {self.pricing_model}",
            f"- **Best for**: {', '.join(self.best_for)}" if self.best_for else "",
            f"- **Strengths**: {', '.join(self.strengths)}" if self.strengths else "",
            f"- **Date format**: {self.date_format}",
        ]
        if self.quirks:
            lines.append("- **Quirks**:")
            for q in self.quirks:
                lines.append(f"  - {q.get('issue', '')}: {q.get('workaround', '')}")
        if self.booking_steps:
            lines.append(f"- **Booking flow**: {' → '.join(self.booking_steps)}")
        return "\n".join(line for line in lines if line)


@dataclass
class APIModule:
    """
    A registered API module — the client, knowledge card, and tools bundled together.

    The registry manages these. The Director reads knowledge cards to wire them.
    """
    knowledge_card: KnowledgeCard
    client_factory: Optional[Callable] = None  # Callable that creates a client instance
    client_instance: Any = None                # Cached client instance
    tools: List[dict] = field(default_factory=list)  # Claude tool definitions
    knowledge_prompt: str = ""                 # System prompt addendum for Claude
    is_configured: bool = False                # Whether credentials are valid
    is_loaded: bool = False                    # Whether client is instantiated

    def check_configured(self) -> bool:
        """Check if all required credentials are set."""
        for env_var in self.knowledge_card.credential_env_vars:
            val = os.environ.get(env_var, "")
            if not val or len(val) < 5:
                self.is_configured = False
                return False
        self.is_configured = True
        return True

    def load(self) -> bool:
        """Instantiate the client if configured."""
        if not self.check_configured():
            return False
        if self.client_factory and not self.client_instance:
            try:
                self.client_instance = self.client_factory()
                self.is_loaded = True
                logger.info("Module %s loaded successfully", self.knowledge_card.module_id)
                return True
            except Exception as e:
                logger.error("Failed to load module %s: %s", self.knowledge_card.module_id, e)
                return False
        return self.is_loaded

    def unload(self):
        """Release client resources."""
        self.client_instance = None
        self.is_loaded = False


class ModuleRegistry:
    """
    Central registry for all API modules.

    Manages module lifecycle: register, discover, load, unload.
    Provides the Module Director with the catalog of available modules
    and their knowledge cards for intelligent routing.

    Thread-safe for concurrent access.
    """

    def __init__(self, storage_dir: Optional[str] = None):
        self._modules: Dict[str, APIModule] = {}
        self._lock = threading.Lock()
        self._storage_dir = Path(storage_dir) if storage_dir else None
        if self._storage_dir:
            self._storage_dir.mkdir(parents=True, exist_ok=True)

    def register(self, module: APIModule) -> None:
        """Register an API module."""
        with self._lock:
            mid = module.knowledge_card.module_id
            self._modules[mid] = module
            module.check_configured()
            logger.info(
                "Registered module: %s (%s) — configured: %s",
                mid, module.knowledge_card.name, module.is_configured,
            )
            if self._storage_dir:
                self._save_card(module.knowledge_card)

    def unregister(self, module_id: str) -> bool:
        """Remove a module from the registry."""
        with self._lock:
            if module_id in self._modules:
                self._modules[module_id].unload()
                del self._modules[module_id]
                return True
            return False

    def get(self, module_id: str) -> Optional[APIModule]:
        """Get a module by ID."""
        return self._modules.get(module_id)

    def get_card(self, module_id: str) -> Optional[KnowledgeCard]:
        """Get a module's knowledge card."""
        mod = self._modules.get(module_id)
        return mod.knowledge_card if mod else None

    def list_modules(
        self,
        vertical: Optional[str] = None,
        configured_only: bool = False,
        source_type: Optional[str] = None,
    ) -> List[APIModule]:
        """List modules with optional filters."""
        modules = list(self._modules.values())
        if vertical:
            modules = [m for m in modules if m.knowledge_card.vertical == vertical]
        if source_type:
            modules = [m for m in modules if m.knowledge_card.source_type == source_type]
        if configured_only:
            modules = [m for m in modules if m.is_configured]
        return sorted(modules, key=lambda m: m.knowledge_card.priority, reverse=True)

    def list_configured(self, vertical: Optional[str] = None) -> List[APIModule]:
        """List only modules with valid credentials."""
        return self.list_modules(vertical=vertical, configured_only=True)

    def list_cards(self, vertical: Optional[str] = None) -> List[KnowledgeCard]:
        """List all knowledge cards."""
        modules = self.list_modules(vertical=vertical)
        return [m.knowledge_card for m in modules]

    def refresh_credentials(self) -> Dict[str, bool]:
        """Re-check all module credentials. Returns {module_id: is_configured}."""
        results = {}
        with self._lock:
            for mid, mod in self._modules.items():
                mod.check_configured()
                results[mid] = mod.is_configured
        return results

    def load_all_configured(self) -> List[str]:
        """Load all configured modules. Returns list of loaded module IDs."""
        loaded = []
        for mid, mod in self._modules.items():
            if mod.check_configured() and mod.load():
                loaded.append(mid)
        return loaded

    def get_tools(self, configured_only: bool = True) -> List[dict]:
        """Get all Claude tool definitions from configured modules."""
        tools = []
        for mod in self._modules.values():
            if configured_only and not mod.is_configured:
                continue
            tools.extend(mod.tools)
        return tools

    def get_knowledge_prompts(self, configured_only: bool = True) -> str:
        """Get combined knowledge prompts from configured modules."""
        prompts = []
        for mod in self._modules.values():
            if configured_only and not mod.is_configured:
                continue
            if mod.knowledge_prompt:
                prompts.append(mod.knowledge_prompt)
        return "\n".join(prompts)

    def get_status(self) -> Dict[str, dict]:
        """Get status of all modules."""
        status = {}
        for mid, mod in self._modules.items():
            card = mod.knowledge_card
            status[mid] = {
                "name": card.name,
                "vertical": card.vertical,
                "source_type": card.source_type,
                "configured": mod.is_configured,
                "loaded": mod.is_loaded,
                "priority": card.priority,
                "carrier_count": card.carrier_count,
                "readiness": card.readiness,
                "credentials": {
                    env: "SET" if os.environ.get(env) else "MISSING"
                    for env in card.credential_env_vars
                },
            }
        return status

    def to_dashboard(self) -> str:
        """Generate a text dashboard showing all modules and their status."""
        lines = ["Module Registry Dashboard", "=" * 50]
        for mid, mod in sorted(self._modules.items()):
            card = mod.knowledge_card
            status = "● LIVE" if mod.is_configured else "○ OFF"
            creds = ", ".join(card.credential_env_vars)
            lines.append(
                f"  {status}  {card.name:<25} {card.source_type:<12} "
                f"{card.carrier_count:>5} carriers  [{creds}]"
            )
        return "\n".join(lines)

    def _save_card(self, card: KnowledgeCard) -> None:
        """Persist a knowledge card to disk."""
        if not self._storage_dir:
            return
        path = self._storage_dir / f"{card.module_id}.json"
        try:
            path.write_text(json.dumps(card.to_dict(), indent=2))
        except Exception as e:
            logger.error("Failed to save card %s: %s", card.module_id, e)

    def load_cards_from_disk(self) -> int:
        """Load knowledge cards from storage directory."""
        if not self._storage_dir or not self._storage_dir.exists():
            return 0
        count = 0
        for path in self._storage_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text())
                card = KnowledgeCard.from_dict(data)
                if card.module_id not in self._modules:
                    self._modules[card.module_id] = APIModule(knowledge_card=card)
                    count += 1
            except Exception as e:
                logger.warning("Failed to load card %s: %s", path.name, e)
        return count
