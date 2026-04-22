"""AI Recipe Generator — ANASTASiA analyzes network captures to produce booking recipes.

Tier 2: One-time AI cost per airline (~$0.50). Takes a NetworkCapture from
the recorder, sends it to Claude for analysis, and outputs a compiled
BookingRecipe card.

Usage:
    generator = AIRecipeGenerator(anthropic_api_key)
    recipe = generator.generate_from_capture(capture)
    recipe_json = recipe.to_json()
    Path("cards/lufthansa_group.json").write_text(json.dumps(recipe_json, indent=2))
"""

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

GENERATOR_SYSTEM_PROMPT = """\
You are ANASTASiA, the intelligent booking engine for MYSTES KYRIOS LLC.
Your task is to analyze a network capture from an airline booking flow and
generate a structured Booking Recipe card.

A Booking Recipe is a JSON template that describes the sequence of API calls
needed to complete a flight booking on an airline's website. The recipe will
be executed programmatically by Playwright in a Scraping Browser session.

Rules:
1. Identify the 4-6 KEY API calls in the booking flow (search → select → passengers → payment → confirm)
2. Ignore asset loads, analytics, tracking pixels, and non-booking requests
3. For each API call, extract: URL pattern, HTTP method, headers, request body template, response extraction paths
4. Replace actual passenger data with ${variable} placeholders
5. Replace actual card data with ${card_*} placeholders
6. Identify session tokens (CSRF, auth, booking tokens) and how they're obtained
7. Note any quirks (unusual field names, required headers, timing constraints)

Variable naming convention:
  Passenger: ${pax_first_name}, ${pax_last_name}, ${pax_dob}, ${pax_gender},
             ${pax_email}, ${pax_phone}, ${pax_passport_number}, ${pax_nationality},
             ${pax_passport_expiry}
  Payment:   ${card_number}, ${card_exp_month}, ${card_exp_year}, ${card_cvv},
             ${card_holder_name}
  Billing:   ${billing_address_line1}, ${billing_city}, ${billing_postal_code},
             ${billing_country}
  Search:    ${origin_iata}, ${destination_iata}, ${departure_date}, ${return_date},
             ${adult_count}, ${cabin_class}
  Extracted: ${csrf_token}, ${session_id}, ${bearer_token}, ${offer_id},
             ${booking_id}, ${booking_token}

Output format: A single JSON object matching the BookingRecipe schema.
"""


class AIRecipeGenerator:
    """Generates booking recipe cards from network captures using Claude.

    This is the Tier 2 mechanism — one-time AI cost per airline to analyze
    a recorded booking flow and produce a compiled recipe card.
    """

    def __init__(self, anthropic_api_key: Optional[str] = None):
        self._api_key = anthropic_api_key
        self._model = "claude-opus-4-6"

    def generate_from_capture(
        self,
        capture,  # NetworkCapture
        airline_group: str = "",
        airlines: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Analyze a network capture and generate a booking recipe.

        Args:
            capture: NetworkCapture from the recorder
            airline_group: Group name (e.g., "lufthansa_group")
            airlines: List of IATA codes covered

        Returns:
            Recipe dict (ready to save as JSON card)
        """
        if not self._api_key:
            import os
            self._api_key = os.environ.get("ANTHROPIC_API_KEY")

        if not self._api_key:
            raise RuntimeError("ANTHROPIC_API_KEY required for recipe generation")

        # Prepare the capture summary for Claude
        capture_summary = self._prepare_capture_summary(capture)

        prompt = f"""\
Analyze this network capture from a booking flow on {capture.airline}'s website
and generate a BookingRecipe JSON card.

Airline group: {airline_group or capture.airline}
Airlines: {json.dumps(airlines or [capture.airline])}
Base URL: {capture.base_url}

## Network Capture Summary

Total requests captured: {len(capture.requests)}
API requests: {len(capture.api_requests)}
Booking-related requests: {len(capture.booking_requests)}

### Booking-Related API Calls (chronological):

{capture_summary}

### Session Cookies:
{json.dumps([{{"name": c.get("name"), "domain": c.get("domain")}} for c in capture.cookies[:20]], indent=2)}

## Task

Generate a complete BookingRecipe JSON with:
1. session_setup: How to load the page and extract tokens
2. steps: The ordered API call sequence (search → select → passengers → payment → confirm)
3. error_patterns: Common error responses and how to handle them
4. card_data_wipe: When to wipe sensitive card data
5. metadata: Generation metadata

Replace all actual values with ${{variable}} placeholders using the standard naming convention.

Return ONLY the JSON object, no markdown code blocks, no explanation.
"""

        try:
            import anthropic

            client = anthropic.Anthropic(api_key=self._api_key)
            response = client.messages.create(
                model=self._model,
                max_tokens=8192,
                system=GENERATOR_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )

            # Parse the response
            content = response.content[0].text.strip()
            # Remove markdown code blocks if present
            if content.startswith("```"):
                content = content.split("\n", 1)[1]
                if content.endswith("```"):
                    content = content.rsplit("```", 1)[0]
                content = content.strip()

            recipe_data = json.loads(content)

            # Ensure required fields
            recipe_data.setdefault("recipe_id", f"{airline_group or capture.airline}_recipe")
            recipe_data.setdefault("airline_group", airline_group or capture.airline)
            recipe_data.setdefault("airlines", airlines or [capture.airline])
            recipe_data.setdefault("base_url", capture.base_url)
            recipe_data.setdefault("metadata", {})
            recipe_data["metadata"]["created_by"] = "anastasia_recipe_generator"
            recipe_data["metadata"]["created_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
            recipe_data["metadata"]["source_capture"] = capture.captured_at
            recipe_data["metadata"]["model"] = self._model

            logger.info(
                "[AIRecipeGenerator] Generated recipe '%s' with %d steps",
                recipe_data["recipe_id"],
                len(recipe_data.get("steps", [])),
            )

            return recipe_data

        except json.JSONDecodeError as e:
            logger.error("[AIRecipeGenerator] Failed to parse AI response: %s", e)
            raise RuntimeError(f"AI generated invalid JSON: {e}")
        except Exception as e:
            logger.error("[AIRecipeGenerator] Generation failed: %s", e)
            raise

    def _prepare_capture_summary(self, capture) -> str:
        """Format booking-related requests for the AI prompt."""
        lines = []
        for i, req in enumerate(capture.booking_requests, 1):
            lines.append(f"### Request {i}: [{req.category.upper()}]")
            lines.append(f"  Method: {req.method}")
            lines.append(f"  URL: {req.url}")
            lines.append(f"  Status: {req.status_code}")
            lines.append(f"  Timestamp: {req.timestamp:.1f}s")

            # Show relevant headers (skip common ones)
            interesting_headers = {
                k: v
                for k, v in req.headers.items()
                if k.lower()
                in (
                    "content-type",
                    "authorization",
                    "x-csrf-token",
                    "x-requested-with",
                    "x-api-key",
                    "x-booking-token",
                    "accept",
                )
            }
            if interesting_headers:
                lines.append(f"  Headers: {json.dumps(interesting_headers)}")

            # Show request body (truncated)
            if req.body:
                body_preview = req.body[:2000]
                lines.append(f"  Body: {body_preview}")

            # Show response body (truncated)
            if req.response_body:
                resp_preview = req.response_body[:2000]
                lines.append(f"  Response: {resp_preview}")

            lines.append("")

        return "\n".join(lines)

    def save_recipe(
        self, recipe_data: Dict[str, Any], output_dir: Optional[Path] = None
    ) -> Path:
        """Save a generated recipe to the cards directory."""
        from . import CARDS_DIR

        cards_dir = output_dir or CARDS_DIR
        cards_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{recipe_data['recipe_id']}.json"
        path = cards_dir / filename
        path.write_text(json.dumps(recipe_data, indent=2), encoding="utf-8")

        logger.info("[AIRecipeGenerator] Saved recipe → %s", path)
        return path
