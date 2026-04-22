"""Booking Recipes — ANASTASiA's self-learning airline booking engine.

Three-tier system:
  Tier 1: Compiled recipe cards (zero AI cost, 95% of bookings)
  Tier 2: AI recipe generator (one-time cost per airline)
  Tier 3: AI live executor (fallback for unknown airlines)

Architecture doc: company_docs/direct_booking_architecture.md
"""

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.events import Event, EventBus, EventType

logger = logging.getLogger(__name__)

CARDS_DIR = Path(__file__).parent / "cards"


@dataclass
class RecipeStep:
    """A single API call in a booking recipe."""

    name: str
    method: str  # GET, POST, PUT, PATCH, DELETE
    url: str  # URL template with ${variable} placeholders
    headers: Dict[str, str] = field(default_factory=dict)
    body: Any = None  # JSON-serializable body template
    response_extract: Dict[str, str] = field(default_factory=dict)  # JSONPath extractions
    validation: Dict[str, Any] = field(default_factory=dict)
    delay_before_ms: int = 0  # Optional delay before this step
    optional: bool = False  # If True, failure doesn't abort the recipe


@dataclass
class BookingRecipe:
    """Compiled booking recipe for an airline group.

    Loaded from JSON card files in the cards/ directory.
    Executed by RecipeEngine with zero AI cost.
    """

    recipe_id: str
    airline_group: str
    airlines: List[str]  # IATA codes covered by this recipe
    base_url: str
    language_path: str = "/en/"

    # Session setup
    session_setup: Dict[str, Any] = field(default_factory=dict)

    # Ordered API call sequence
    steps: List[RecipeStep] = field(default_factory=list)

    # Card data security
    card_data_wipe: Dict[str, Any] = field(default_factory=lambda: {
        "after_step": "submit_payment",
        "on_failure": True,
        "fields": ["card_number", "card_cvv", "card_exp_month", "card_exp_year"],
    })

    # Error handling patterns
    error_patterns: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, path: Path) -> "BookingRecipe":
        """Load a recipe from a JSON card file."""
        data = json.loads(path.read_text(encoding="utf-8"))
        steps = []
        for step_data in data.get("steps", []):
            steps.append(RecipeStep(
                name=step_data["name"],
                method=step_data.get("method", "POST"),
                url=step_data["url"],
                headers=step_data.get("headers", {}),
                body=step_data.get("body"),
                response_extract=step_data.get("response_extract", {}),
                validation=step_data.get("validation", {}),
                delay_before_ms=step_data.get("delay_before_ms", 0),
                optional=step_data.get("optional", False),
            ))
        return cls(
            recipe_id=data.get("recipe_id", path.stem),
            airline_group=data.get("airline_group", "unknown"),
            airlines=data.get("airlines", []),
            base_url=data.get("base_url", ""),
            language_path=data.get("language_path", "/en/"),
            session_setup=data.get("session_setup", {}),
            steps=steps,
            card_data_wipe=data.get("card_data_wipe", {
                "after_step": "submit_payment",
                "on_failure": True,
                "fields": ["card_number", "card_cvv", "card_exp_month", "card_exp_year"],
            }),
            error_patterns=data.get("error_patterns", {}),
            metadata=data.get("metadata", {}),
        )

    def to_json(self) -> Dict[str, Any]:
        """Serialize recipe to JSON-compatible dict."""
        return {
            "recipe_id": self.recipe_id,
            "airline_group": self.airline_group,
            "airlines": self.airlines,
            "base_url": self.base_url,
            "language_path": self.language_path,
            "session_setup": self.session_setup,
            "steps": [
                {
                    "name": s.name,
                    "method": s.method,
                    "url": s.url,
                    "headers": s.headers,
                    "body": s.body,
                    "response_extract": s.response_extract,
                    "validation": s.validation,
                    "delay_before_ms": s.delay_before_ms,
                    "optional": s.optional,
                }
                for s in self.steps
            ],
            "card_data_wipe": self.card_data_wipe,
            "error_patterns": self.error_patterns,
            "metadata": self.metadata,
        }

    def covers_airline(self, iata_code: str) -> bool:
        """Check if this recipe handles the given airline."""
        return iata_code.upper() in [a.upper() for a in self.airlines]


class RecipeRegistry:
    """Registry of all loaded booking recipes.

    Provides airline → recipe lookup with O(1) access.
    """

    def __init__(self):
        self._recipes: Dict[str, BookingRecipe] = {}  # recipe_id → recipe
        self._airline_index: Dict[str, str] = {}  # IATA code → recipe_id

    def register(self, recipe: BookingRecipe) -> None:
        """Register a recipe and index its airlines."""
        self._recipes[recipe.recipe_id] = recipe
        for airline in recipe.airlines:
            self._airline_index[airline.upper()] = recipe.recipe_id
        logger.info(
            "[RecipeRegistry] Registered %s covering %s",
            recipe.recipe_id,
            ", ".join(recipe.airlines),
        )

    def get_recipe(self, recipe_id: str) -> Optional[BookingRecipe]:
        """Get a recipe by its ID."""
        return self._recipes.get(recipe_id)

    def find_by_airline(self, iata_code: str) -> Optional[BookingRecipe]:
        """Find the recipe that handles a given airline."""
        recipe_id = self._airline_index.get(iata_code.upper())
        if recipe_id:
            return self._recipes.get(recipe_id)
        return None

    def has_recipe(self, iata_code: str) -> bool:
        """Check if we have a recipe for an airline."""
        return iata_code.upper() in self._airline_index

    @property
    def recipe_count(self) -> int:
        return len(self._recipes)

    @property
    def airline_count(self) -> int:
        return len(self._airline_index)

    @property
    def all_airlines(self) -> List[str]:
        return sorted(self._airline_index.keys())

    def load_from_directory(self, directory: Optional[Path] = None) -> int:
        """Load all recipe JSON files from a directory."""
        cards_dir = directory or CARDS_DIR
        if not cards_dir.exists():
            return 0
        loaded = 0
        for path in sorted(cards_dir.glob("*.json")):
            try:
                recipe = BookingRecipe.from_json(path)
                self.register(recipe)
                loaded += 1
            except Exception as e:
                logger.error("[RecipeRegistry] Failed to load %s: %s", path.name, e)
        return loaded


class BookingRecipeModule:
    """ANASTASiA neuron for booking recipe management.

    Follows the NeuronModule interface (name, version, dependencies,
    initialize, health_check, shutdown).
    """

    name = "booking_recipes"
    version = "1.0.0"
    dependencies = ["proxy", "booking_engine"]

    def __init__(self):
        self.registry = RecipeRegistry()
        self._event_bus: Optional[EventBus] = None
        self._config: Dict[str, Any] = {}
        self._initialized = False
        self._total_executions = 0
        self._total_failures = 0

    def initialize(self, event_bus: EventBus, config: Dict[str, Any]) -> None:
        """Load recipe cards and subscribe to events."""
        self._event_bus = event_bus
        self._config = config

        # Load compiled recipe cards
        cards_dir = Path(config.get("recipe_cards_dir", str(CARDS_DIR)))
        loaded = self.registry.load_from_directory(cards_dir)
        logger.info(
            "[BookingRecipes] Loaded %d recipes covering %d airlines",
            loaded,
            self.registry.airline_count,
        )
        self._initialized = True

    def health_check(self) -> Dict[str, Any]:
        return {
            "healthy": self._initialized,
            "recipes_loaded": self.registry.recipe_count,
            "airlines_covered": self.registry.airline_count,
            "total_executions": self._total_executions,
            "total_failures": self._total_failures,
            "success_rate": (
                round(
                    (self._total_executions - self._total_failures)
                    / max(self._total_executions, 1)
                    * 100,
                    1,
                )
            ),
        }

    def shutdown(self) -> None:
        self._initialized = False

    def has_recipe_for(self, airline_iata: str) -> bool:
        """Check if a compiled recipe exists for this airline."""
        return self.registry.has_recipe(airline_iata)

    def get_recipe_for(self, airline_iata: str) -> Optional[BookingRecipe]:
        """Get the recipe for an airline, if one exists."""
        return self.registry.find_by_airline(airline_iata)

    def record_execution(self, success: bool) -> None:
        """Track execution stats."""
        self._total_executions += 1
        if not success:
            self._total_failures += 1
