"""
Agent Orchestrator — Connects Claude API tool_use decisions to SDK method calls.

This is the agentic loop:
1. User sends a message
2. Claude processes it with knowledge base + tools
3. If Claude returns tool_use → execute SDK method → feed result back
4. Repeat until Claude returns a text response (no more tool calls)
5. Return the final text to the user

MYSTES KYRIOS LLC — Confidential.
"""

import json
import logging
import time
from typing import Optional

import anthropic

from ..client import RedboxClient
from .knowledge_base import KNOWLEDGE_BASE
from .pricing import PricingModel, apply_pricing_to_results
from .tools import TOOL_DEFINITIONS

logger = logging.getLogger(__name__)

# Default model — Haiku for cost efficiency at scale
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
MAX_AGENT_TURNS = 15  # Safety limit on tool-use loops
MAX_CONVERSATION_MESSAGES = 100  # Trim old messages beyond this


class BookingAgent:
    """
    Conversational flight booking agent powered by Claude + Redbox SDK.

    Usage:
        client = RedboxClient(agency_id="...", branch="...", token_provider=...)
        agent = BookingAgent(client=client, anthropic_api_key="sk-ant-...")
        response = agent.chat("Find me flights from JFK to London next Tuesday")
    """

    def __init__(
        self,
        client: RedboxClient,
        anthropic_api_key: str,
        model: str = DEFAULT_MODEL,
        agency_name: Optional[str] = None,
        pricing: Optional[PricingModel] = None,
        system_prompt_extra: Optional[str] = None,
    ):
        """
        Initialize the booking agent.

        Args:
            client: Configured RedboxClient instance with valid authentication
            anthropic_api_key: Anthropic API key for Claude calls
            model: Claude model ID (default: Haiku for cost efficiency)
            agency_name: Optional agency name for personalized responses
            pricing: Optional PricingModel — when set, agent applies agency pricing to results
            system_prompt_extra: Optional additional instructions appended to knowledge base
        """
        self.client = client
        self.anthropic = anthropic.Anthropic(api_key=anthropic_api_key)
        self.model = model
        self.conversation: list = []
        self.agency_name = agency_name
        self.pricing = pricing

        # Build system prompt
        self.system_prompt = KNOWLEDGE_BASE
        if agency_name:
            self.system_prompt += f"\n\nYou are assisting staff at {agency_name}."
        if pricing:
            self.system_prompt += f"""

## AGENCY PRICING MODEL
This agency uses the following pricing configuration. When displaying prices to the user,
show the consumer_price (after agency markup), NOT the raw Redbox fare.
- Strategy: {pricing.strategy}
- Markup: {pricing.markup_percent}% + ${pricing.markup_flat} flat
- Min markup: ${pricing.min_markup} / Max: ${pricing.max_markup}
- Currency: {pricing.display_currency}
The search results you receive will already have agency pricing applied (consumer_price field).
Always use consumer_price when showing prices to the user."""
        if system_prompt_extra:
            self.system_prompt += f"\n\n{system_prompt_extra}"

        # Usage tracking
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_requests = 0

    def chat(self, user_message: str) -> str:
        """
        Send a user message and get the agent's response.

        The agent may make multiple SDK calls (tool use loops) before
        returning a final text response.

        Args:
            user_message: The user's natural language message

        Returns:
            The agent's text response
        """
        self.conversation.append({
            "role": "user",
            "content": user_message,
        })

        # Trim conversation if too long
        self._trim_conversation()

        response_text = ""
        turns = 0

        while turns < MAX_AGENT_TURNS:
            turns += 1

            # Call Claude
            try:
                response = self.anthropic.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=[{
                        "type": "text",
                        "text": self.system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }],
                    tools=TOOL_DEFINITIONS,
                    messages=self.conversation,
                )
            except anthropic.APIError as e:
                logger.error(f"Anthropic API error: {e}")
                error_msg = "I'm having trouble connecting to my AI service. Please try again in a moment."
                self.conversation.append({
                    "role": "assistant",
                    "content": error_msg,
                })
                return error_msg

            # Track usage
            self.total_input_tokens += response.usage.input_tokens
            self.total_output_tokens += response.usage.output_tokens
            self.total_requests += 1

            # Check stop reason
            if response.stop_reason == "end_turn":
                # Claude finished — extract text and return
                response_text = self._extract_text(response.content)
                self.conversation.append({
                    "role": "assistant",
                    "content": response.content,
                })
                return response_text

            elif response.stop_reason == "tool_use":
                # Claude wants to call tools — execute them
                self.conversation.append({
                    "role": "assistant",
                    "content": response.content,
                })

                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        result = self._execute_tool(block.name, block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result, default=str),
                        })

                self.conversation.append({
                    "role": "user",
                    "content": tool_results,
                })

            else:
                # Unexpected stop reason
                logger.warning(f"Unexpected stop_reason: {response.stop_reason}")
                response_text = self._extract_text(response.content)
                if response_text:
                    self.conversation.append({
                        "role": "assistant",
                        "content": response.content,
                    })
                    return response_text
                break

        # Safety: max turns reached
        fallback = "I've completed my analysis. Is there anything specific you'd like me to help with?"
        self.conversation.append({
            "role": "assistant",
            "content": fallback,
        })
        return fallback

    def _execute_tool(self, tool_name: str, tool_input: dict) -> dict:
        """
        Route a tool call to the corresponding SDK method.

        Args:
            tool_name: Name of the tool (matches TOOL_DEFINITIONS)
            tool_input: Input parameters from Claude

        Returns:
            SDK method result dict
        """
        logger.info(f"Executing tool: {tool_name}")
        logger.debug(f"Tool input: {json.dumps(tool_input, default=str)}")

        start = time.time()

        try:
            if tool_name == "search_airports":
                result = self.client.search_airports(
                    query=tool_input["query"],
                    max_results=tool_input.get("max_results", 10),
                )
                # search_airports returns a list, wrap it
                result = {"success": True, "airports": result, "count": len(result)}

            elif tool_name == "search_flights":
                result = self.client.search_flights(
                    origin=tool_input["origin"],
                    destination=tool_input["destination"],
                    departure_date=tool_input["departure_date"],
                    return_date=tool_input.get("return_date"),
                    adults=tool_input.get("adults", 1),
                    children=tool_input.get("children", 0),
                    infants=tool_input.get("infants", 0),
                    cabin_class=tool_input.get("cabin_class", "ECONOMY"),
                    max_results=tool_input.get("max_results", 20),
                    nonstop_only=tool_input.get("nonstop_only", False),
                )
                # Apply agency pricing if configured
                if self.pricing and result.get("success") and result.get("flights"):
                    result["flights"] = apply_pricing_to_results(
                        result["flights"], self.pricing)

            elif tool_name == "get_search_results":
                result = self.client.get_search_results(
                    fare_search_id=tool_input["fare_search_id"],
                    page_number=tool_input.get("page_number", 1),
                    results_per_page=tool_input.get("results_per_page", 20),
                    sorting_criteria=tool_input.get("sorting_criteria"),
                    filter_criteria=tool_input.get("filter_criteria"),
                )
                # Apply agency pricing if configured
                if self.pricing and result.get("success") and result.get("flights"):
                    result["flights"] = apply_pricing_to_results(
                        result["flights"], self.pricing)

            elif tool_name == "get_fare_rules":
                result = self.client.get_fare_rules(
                    fare_search_id=tool_input["fare_search_id"],
                    fare_id=tool_input["fare_id"],
                )

            elif tool_name == "get_seatmap":
                result = self.client.get_seatmap(
                    airline_code=tool_input["airline_code"],
                    flight_number=tool_input["flight_number"],
                    departure=tool_input["departure"],
                    destination=tool_input["destination"],
                    departure_date=tool_input["departure_date"],
                    booking_class=tool_input.get("booking_class", "Y"),
                    cabin_class=tool_input.get("cabin_class", "ECONOMY"),
                )

            elif tool_name == "book_flight":
                result = self.client.book_flight(
                    fare_search_id=tool_input["fare_search_id"],
                    fare_id=tool_input["fare_id"],
                    passengers=tool_input["passengers"],
                    order_tickets=tool_input.get("order_tickets", True),
                    markup_amount=tool_input.get("markup_amount", 0),
                )

            elif tool_name == "search_bookings":
                result = self.client.search_bookings(
                    locator=tool_input.get("locator"),
                    departure=tool_input.get("departure"),
                    destination=tool_input.get("destination"),
                    airline=tool_input.get("airline"),
                    date_from=tool_input.get("date_from"),
                    date_to=tool_input.get("date_to"),
                    travel_date_from=tool_input.get("travel_date_from"),
                    travel_date_to=tool_input.get("travel_date_to"),
                )

            elif tool_name == "generate_document":
                result = self.client.generate_document(
                    document_type=tool_input["document_type"],
                    shopping_cart_id=tool_input.get("shopping_cart_id"),
                    super_pnr_id=tool_input.get("super_pnr_id"),
                    fare_search_id=tool_input.get("fare_search_id"),
                    fare_ids=tool_input.get("fare_ids"),
                    display_prices=tool_input.get("display_prices", True),
                    language=tool_input.get("language", "en"),
                    email_recipients=tool_input.get("email_recipients"),
                )

            elif tool_name == "search_profiles":
                result = self.client.search_profiles(
                    search_term=tool_input["search_term"],
                )

            elif tool_name == "get_shopping_cart":
                result = self.client.get_shopping_cart()

            elif tool_name == "get_extras":
                result = self.client.get_extras(
                    fare_search_id=tool_input["fare_search_id"],
                    fare_id=tool_input["fare_id"],
                )

            elif tool_name == "book_flight_with_extras":
                # Build extra cart items from structured input
                extra_items = []

                # Insurance
                ins = tool_input.get("insurance")
                if ins:
                    extra_items.append(RedboxClient.build_insurance_item(
                        insurance_id=ins["insurance_id"],
                        plan_name=ins.get("plan_name", ""),
                        passenger_indices=ins.get("passenger_indices"),
                        fare_id=tool_input["fare_id"],
                    ))

                # Ancillaries
                for anc in tool_input.get("ancillaries", []):
                    extra_items.append(RedboxClient.build_ancillary_item(
                        ancillary_id=anc["ancillary_id"],
                        service_type=anc["service_type"],
                        quantity=anc.get("quantity", 1),
                        passenger_indices=anc.get("passenger_indices"),
                    ))

                # Seat selections
                for seat in tool_input.get("seat_selections", []):
                    extra_items.append(RedboxClient.build_seat_item(
                        seat_number=seat["seat_number"],
                        segment_id=seat["segment_id"],
                        passenger_index=seat.get("passenger_index", 0),
                    ))

                # Handle FF numbers in passenger data
                passengers = tool_input["passengers"]
                for i, pax in enumerate(passengers):
                    ff_num = pax.pop("frequentFlyerNumber", None)
                    ff_airline = pax.pop("frequentFlyerAirline", None)
                    if ff_num and ff_airline:
                        extra_items.append(RedboxClient.build_frequent_flyer_item(
                            ff_number=ff_num,
                            airline_code=ff_airline,
                            passenger_index=i,
                        ))

                result = self.client.book_flight(
                    fare_search_id=tool_input["fare_search_id"],
                    fare_id=tool_input["fare_id"],
                    passengers=passengers,
                    order_tickets=tool_input.get("order_tickets", True),
                    markup_amount=tool_input.get("markup_amount", 0),
                    extra_cart_items=extra_items if extra_items else None,
                )

            elif tool_name == "get_booking_details":
                result = self.client.get_booking_details(
                    super_pnr_id=tool_input["super_pnr_id"],
                )

            elif tool_name == "cancel_booking":
                result = self.client.cancel_booking(
                    super_pnr_id=tool_input["super_pnr_id"],
                    reason=tool_input.get("reason", ""),
                )

            elif tool_name == "void_ticket":
                result = self.client.void_ticket(
                    super_pnr_id=tool_input["super_pnr_id"],
                )

            elif tool_name == "request_refund":
                result = self.client.request_refund(
                    super_pnr_id=tool_input["super_pnr_id"],
                    refund_type=tool_input.get("refund_type", "FULL"),
                    amount=tool_input.get("amount"),
                    reason=tool_input.get("reason", ""),
                )

            else:
                result = {"success": False, "error": f"Unknown tool: {tool_name}"}

        except Exception as e:
            logger.error(f"Tool execution error ({tool_name}): {e}")
            result = {"success": False, "error": str(e)}

        elapsed = time.time() - start
        logger.info(f"Tool {tool_name} completed in {elapsed:.2f}s — success: {result.get('success', 'N/A')}")

        return result

    def _extract_text(self, content_blocks) -> str:
        """Extract text from Claude response content blocks."""
        parts = []
        for block in content_blocks:
            if hasattr(block, "text"):
                parts.append(block.text)
        return "\n".join(parts)

    def _trim_conversation(self):
        """Trim conversation history to prevent context overflow."""
        if len(self.conversation) > MAX_CONVERSATION_MESSAGES:
            # Keep first 2 messages (initial context) and last N
            keep = MAX_CONVERSATION_MESSAGES - 2
            self.conversation = self.conversation[:2] + self.conversation[-keep:]

    def reset(self):
        """Clear conversation history and start fresh."""
        self.conversation = []

    def get_usage(self) -> dict:
        """
        Get cumulative token usage stats.

        Returns:
            Dict with input_tokens, output_tokens, total_requests,
            and estimated_cost_usd (based on Haiku pricing).
        """
        # Haiku 4.5 pricing: $0.80/MTok input, $4/MTok output
        # With prompt caching: $0.08/MTok cached input
        input_cost = (self.total_input_tokens / 1_000_000) * 0.80
        output_cost = (self.total_output_tokens / 1_000_000) * 4.00
        return {
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
            "total_requests": self.total_requests,
            "estimated_cost_usd": round(input_cost + output_cost, 4),
        }
