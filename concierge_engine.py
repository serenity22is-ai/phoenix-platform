"""
Knowledge Card Concierge — Zero-cost deterministic chat engine.

Pure Python decision-tree that reads JSON flow definitions and returns
structured responses. No AI API calls. Zero Anthropic cost.

The concierge surfaces as a chat bubble on every page, guiding users
through search verticals and features. Subscribers can escalate to
live AI chat at /ai.

MYSTES KYRIOS LLC — Confidential.
"""

import json
import os
import logging
from typing import Dict, Optional

logger = logging.getLogger("mystes.concierge")

_FLOWS_DIR = os.path.join(os.path.dirname(__file__), "concierge_flows")

# Keyword → flow_id mapping for freetext matching
_KEYWORD_MAP = {
    "flight": "flight_search",
    "fly": "flight_search",
    "plane": "flight_search",
    "airline": "flight_search",
    "hotel": "hotel_search",
    "stay": "hotel_search",
    "accommodation": "hotel_search",
    "room": "hotel_search",
    "car": "car_search",
    "rental": "car_search",
    "drive": "car_search",
    "activity": "activity_search",
    "tour": "activity_search",
    "experience": "activity_search",
    "things to do": "activity_search",
    "insurance": "insurance_info",
    "protect": "insurance_info",
    "coverage": "insurance_info",
    "trip": "trip_planner_intro",
    "plan": "trip_planner_intro",
    "itinerary": "trip_planner_intro",
    "friend": "trip_planner_intro",
    "group": "trip_planner_intro",
    "help": "welcome",
    "hi": "welcome",
    "hello": "welcome",
}


class ConciergeEngine:
    """Zero-cost deterministic concierge. Reads JSON flows, returns structured responses."""

    def __init__(self, flows_dir: Optional[str] = None, cross_sell_engine=None):
        self.flows: Dict[str, dict] = {}
        self._cross_sell_engine = cross_sell_engine
        self._load_flows(flows_dir or _FLOWS_DIR)

    def _load_flows(self, flows_dir: str) -> None:
        """Load all flow definition JSON files."""
        if not os.path.isdir(flows_dir):
            logger.warning("Concierge flows directory not found: %s", flows_dir)
            return

        for fname in sorted(os.listdir(flows_dir)):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(flows_dir, fname)
            try:
                with open(path) as f:
                    flow = json.load(f)
                flow_id = flow.get("flow_id", fname.replace(".json", ""))
                self.flows[flow_id] = flow
            except Exception as e:
                logger.warning("Failed to load flow %s: %s", fname, e)

        logger.info("Concierge loaded %d flows", len(self.flows))

    def process(
        self,
        flow_id: str = "welcome",
        selected_option: Optional[str] = None,
        freetext: Optional[str] = None,
        page_context: Optional[Dict] = None,
    ) -> dict:
        """
        Process a concierge interaction step.

        Args:
            flow_id: Current flow to render (default: welcome)
            selected_option: ID of the option the user selected
            freetext: Free-text input from the user
            page_context: Page context from frontend {vertical, destination, date, ...}

        Returns:
            {flow_id, type, message, options, redirect_url, cross_sell}
        """
        # Freetext matching takes priority
        if freetext and not selected_option:
            return self._match_freetext(freetext, page_context=page_context)

        # Navigate via selected option
        if selected_option:
            flow = self.flows.get(flow_id, {})
            for option in flow.get("options", []):
                if option.get("id") == selected_option:
                    if option.get("redirect_url"):
                        return {
                            "flow_id": flow_id,
                            "type": "redirect",
                            "message": option.get("label", ""),
                            "redirect_url": option["redirect_url"],
                        }
                    if option.get("next_flow"):
                        return self._render_flow(option["next_flow"], page_context=page_context)
            # Option not found — re-render current flow
            return self._render_flow(flow_id, page_context=page_context)

        return self._render_flow(flow_id, page_context=page_context)

    def _match_freetext(self, text: str, page_context: Optional[Dict] = None) -> dict:
        """Match freetext to a flow via keyword lookup."""
        lower = text.lower().strip()

        for keyword, target_flow in _KEYWORD_MAP.items():
            if keyword in lower:
                return self._render_flow(target_flow, page_context=page_context)

        # No match — offer escalation
        return {
            "flow_id": "no_match",
            "type": "escalation",
            "message": "I'm not sure what you're looking for. Would you like to chat with our AI assistant?",
            "options": [
                {"id": "ai_chat", "label": "Chat with AI", "redirect_url": "/ai"},
                {"id": "start_over", "label": "Start over", "next_flow": "welcome"},
            ],
        }

    def _render_flow(self, flow_id: str, page_context: Optional[Dict] = None) -> dict:
        """Render a flow step as a response dict."""
        flow = self.flows.get(flow_id)
        if not flow:
            return self._render_flow("welcome", page_context=page_context) if flow_id != "welcome" else {
                "flow_id": "welcome",
                "type": "question",
                "message": "Welcome to MYSTES! What are you looking for?",
                "options": [
                    {"id": "flights", "label": "Flights", "next_flow": "flight_search"},
                    {"id": "hotels", "label": "Hotels", "next_flow": "hotel_search"},
                    {"id": "cars", "label": "Car Rentals", "next_flow": "car_search"},
                    {"id": "activities", "label": "Activities", "next_flow": "activity_search"},
                ],
            }

        # Dynamic cross-sell from engine, fallback to static JSON
        cross_sell = None
        if self._cross_sell_engine:
            vertical = self._flow_to_vertical(flow.get("flow_id", flow_id))
            destination = (page_context or {}).get("destination", "")
            date = (page_context or {}).get("date", "")
            rec = self._cross_sell_engine.for_concierge(vertical, destination=destination, date=date)
            if rec:
                cross_sell = {
                    "message": rec["subtitle"],
                    "link": rec["url"],
                    "vertical": rec["vertical"],
                    "icon": rec["icon"],
                }
        if not cross_sell:
            cross_sell = flow.get("cross_sell")

        return {
            "flow_id": flow.get("flow_id", flow_id),
            "type": flow.get("type", "question"),
            "message": flow.get("message", ""),
            "options": flow.get("options", []),
            "redirect_url": flow.get("redirect_url"),
            "cross_sell": cross_sell,
        }

    @staticmethod
    def _flow_to_vertical(flow_id: str) -> str:
        """Map flow_id to vertical name for CrossSellEngine."""
        mapping = {
            "flight_search": "flight",
            "hotel_search": "hotel",
            "car_search": "car",
            "activity_search": "activity",
            "insurance_info": "insurance",
        }
        return mapping.get(flow_id, "")
