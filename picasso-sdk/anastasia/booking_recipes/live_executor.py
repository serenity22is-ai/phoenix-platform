"""AI Live Executor — Real-time booking for airlines without recipes.

Tier 3: Per-booking AI cost (~$0.10-0.15). When no compiled recipe exists,
ANASTASiA intercepts network traffic in real-time, analyzes the booking
flow with Claude, and executes API calls dynamically.

After a successful booking, auto-generates a recipe card so future bookings
on the same airline drop to Tier 1 (zero AI cost).

Usage:
    executor = AILiveExecutor(anthropic_api_key)
    result = executor.execute(cdp_url, airline_url, passenger_data, payment_data, search_params)
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional

from .engine import RecipeExecutionResult, StepResult

logger = logging.getLogger(__name__)

LIVE_EXECUTOR_SYSTEM_PROMPT = """\
You are ANASTASiA, executing a live airline booking. You are given the current
page state and intercepted network requests. Your job is to determine the next
API call to make in the booking flow.

You have these tools:
1. FETCH: Make an HTTP request through the browser's fetch() API
2. EXTRACT: Extract a value from the page's cookies/localStorage
3. COMPLETE: Signal that the booking is complete with a confirmation code
4. ABORT: Signal that the booking cannot be completed

For each turn, analyze the current state and respond with ONE action in JSON:

For FETCH:
{"action": "fetch", "url": "...", "method": "POST", "headers": {...}, "body": {...}}

For EXTRACT:
{"action": "extract", "source": "cookie|localstorage|page", "key": "..."}

For COMPLETE:
{"action": "complete", "confirmation_code": "...", "total_charged": "...", "currency": "..."}

For ABORT:
{"action": "abort", "reason": "..."}

Rules:
- Replace passenger/card data from the provided context, never invent data
- Maintain the session by including cookies and tokens from previous responses
- Wipe card data variables after the payment step
- Maximum 15 steps — abort if not complete by then
"""


class AILiveExecutor:
    """Executes bookings in real-time using AI to navigate unknown airline APIs.

    This is the Tier 3 fallback. When no compiled recipe exists for an airline,
    ANASTASiA analyzes intercepted network traffic and determines the correct
    API calls to make.
    """

    def __init__(self, anthropic_api_key: Optional[str] = None):
        self._api_key = anthropic_api_key
        self._model = "claude-opus-4-6"
        self._max_steps = 15

    def execute(
        self,
        cdp_url: str,
        airline_url: str,
        passenger_data: Dict[str, Any],
        payment_data: Dict[str, Any],
        search_params: Dict[str, Any],
        dry_run: bool = False,
    ) -> RecipeExecutionResult:
        """Execute a booking on an unknown airline using AI guidance.

        Args:
            cdp_url: Bright Data Scraping Browser WebSocket URL
            airline_url: Airline booking page URL
            passenger_data: Customer passenger details
            payment_data: Customer card details (wiped after payment)
            search_params: Flight search parameters (origin, dest, date, etc.)
            dry_run: Stop before payment if True

        Returns:
            RecipeExecutionResult with confirmation or error
        """
        if not self._api_key:
            import os
            self._api_key = os.environ.get("ANTHROPIC_API_KEY")

        if not self._api_key:
            return RecipeExecutionResult(
                success=False,
                error="ANTHROPIC_API_KEY required for live execution",
                tier="tier3",
            )

        start_time = time.time()
        step_results: List[StepResult] = []
        intercepted_requests: List[Dict[str, Any]] = []

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return RecipeExecutionResult(
                success=False,
                error="Playwright not installed",
                tier="tier3",
            )

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.connect_over_cdp(cdp_url)
                page = browser.new_page()

                # Intercept network requests
                def on_request(request):
                    try:
                        if request.resource_type in ("image", "stylesheet", "font"):
                            return
                        body = None
                        try:
                            body = request.post_data
                        except Exception:
                            pass
                        intercepted_requests.append({
                            "method": request.method,
                            "url": request.url,
                            "headers": dict(request.headers),
                            "body": body,
                        })
                    except Exception:
                        pass

                def on_response(response):
                    try:
                        for req in reversed(intercepted_requests):
                            if req["url"] == response.url and "status" not in req:
                                req["status"] = response.status
                                try:
                                    req["response"] = response.text()[:3000]
                                except Exception:
                                    req["response"] = None
                                break
                    except Exception:
                        pass

                page.on("request", on_request)
                page.on("response", on_response)

                try:
                    # Load the airline page
                    page.goto(airline_url, wait_until="networkidle", timeout=30000)

                    # Get initial state
                    cookies = page.context.cookies()
                    cookie_summary = [
                        {"name": c["name"], "domain": c["domain"]}
                        for c in cookies[:20]
                    ]

                    # Build context for AI
                    context = {
                        "airline_url": airline_url,
                        "passenger": passenger_data,
                        "search": search_params,
                        "cookies": cookie_summary,
                        "dry_run": dry_run,
                    }
                    # Only include payment data if not dry run
                    if not dry_run:
                        context["payment"] = payment_data

                    # Iterative AI-guided execution
                    messages = [
                        {
                            "role": "user",
                            "content": (
                                f"I've loaded {airline_url}. Here's the booking context:\n\n"
                                f"```json\n{json.dumps(context, indent=2)}\n```\n\n"
                                f"Intercepted {len(intercepted_requests)} network requests during page load.\n"
                                f"Last 5 API calls:\n"
                                f"{self._format_recent_requests(intercepted_requests[-5:])}\n\n"
                                f"What's the first API call I should make to start the booking flow?"
                            ),
                        }
                    ]

                    import anthropic

                    client = anthropic.Anthropic(api_key=self._api_key)

                    for step_num in range(self._max_steps):
                        response = client.messages.create(
                            model=self._model,
                            max_tokens=2048,
                            system=LIVE_EXECUTOR_SYSTEM_PROMPT,
                            messages=messages,
                        )

                        ai_text = response.content[0].text.strip()

                        # Parse AI action
                        try:
                            # Extract JSON from response
                            json_match = ai_text
                            if "```" in ai_text:
                                json_match = ai_text.split("```")[1]
                                if json_match.startswith("json"):
                                    json_match = json_match[4:]
                            action = json.loads(json_match.strip())
                        except json.JSONDecodeError:
                            # Try to find JSON object in the response
                            import re
                            json_pattern = re.search(r'\{[^{}]*"action"[^{}]*\}', ai_text)
                            if json_pattern:
                                action = json.loads(json_pattern.group())
                            else:
                                step_results.append(StepResult(
                                    step_name=f"ai_step_{step_num}",
                                    success=False,
                                    error=f"Could not parse AI action: {ai_text[:200]}",
                                ))
                                break

                        action_type = action.get("action")

                        if action_type == "complete":
                            step_results.append(StepResult(
                                step_name="complete",
                                success=True,
                                extracted={
                                    "pnr": action.get("confirmation_code"),
                                    "total_charged": action.get("total_charged"),
                                    "charged_currency": action.get("currency"),
                                },
                            ))

                            # Wipe payment data
                            payment_data.clear()

                            return RecipeExecutionResult(
                                success=True,
                                confirmation_code=action.get("confirmation_code"),
                                total_charged=action.get("total_charged"),
                                charged_currency=action.get("currency"),
                                step_results=step_results,
                                total_duration_ms=int((time.time() - start_time) * 1000),
                                tier="tier3",
                            )

                        elif action_type == "abort":
                            payment_data.clear()
                            return RecipeExecutionResult(
                                success=False,
                                error=action.get("reason", "AI aborted booking"),
                                step_results=step_results,
                                total_duration_ms=int((time.time() - start_time) * 1000),
                                tier="tier3",
                            )

                        elif action_type == "fetch":
                            # Execute the fetch
                            step_start = time.time()
                            fetch_result = self._execute_fetch(
                                page, action, airline_url
                            )
                            step_results.append(StepResult(
                                step_name=f"ai_fetch_{step_num}",
                                success=fetch_result.get("success", False),
                                status_code=fetch_result.get("status"),
                                response_body=fetch_result.get("body"),
                                error=fetch_result.get("error"),
                                duration_ms=int((time.time() - step_start) * 1000),
                            ))

                            # Feed result back to AI
                            messages.append({"role": "assistant", "content": ai_text})
                            messages.append({
                                "role": "user",
                                "content": (
                                    f"Fetch result:\n"
                                    f"Status: {fetch_result.get('status')}\n"
                                    f"Response: {str(fetch_result.get('body', ''))[:2000]}\n\n"
                                    f"What's the next step?"
                                ),
                            })

                        elif action_type == "extract":
                            # Extract value from page
                            value = self._extract_value(page, action)
                            messages.append({"role": "assistant", "content": ai_text})
                            messages.append({
                                "role": "user",
                                "content": f"Extracted value: {value}\n\nWhat's next?",
                            })

                    # Max steps reached
                    payment_data.clear()
                    return RecipeExecutionResult(
                        success=False,
                        error=f"Max steps ({self._max_steps}) reached without completion",
                        step_results=step_results,
                        total_duration_ms=int((time.time() - start_time) * 1000),
                        tier="tier3",
                    )

                finally:
                    browser.close()
                    payment_data.clear()

        except Exception as e:
            payment_data.clear()
            logger.error("[AILiveExecutor] Execution error: %s", e)
            return RecipeExecutionResult(
                success=False,
                error=str(e),
                step_results=step_results,
                total_duration_ms=int((time.time() - start_time) * 1000),
                tier="tier3",
            )

    def _execute_fetch(
        self, page, action: Dict[str, Any], base_url: str
    ) -> Dict[str, Any]:
        """Execute a fetch() call in the browser context."""
        url = action.get("url", "")
        if not url.startswith("http"):
            from urllib.parse import urljoin
            url = urljoin(base_url, url)

        method = action.get("method", "GET")
        headers = action.get("headers", {})
        body = action.get("body")

        options = {"method": method, "headers": headers, "credentials": "include"}
        if body is not None:
            options["body"] = json.dumps(body) if isinstance(body, dict) else body
            if "Content-Type" not in headers:
                options["headers"]["Content-Type"] = "application/json"

        try:
            result = page.evaluate(f"""
                async () => {{
                    try {{
                        const resp = await fetch({json.dumps(url)}, {json.dumps(options)});
                        const text = await resp.text();
                        return {{ success: true, status: resp.status, body: text }};
                    }} catch (err) {{
                        return {{ success: false, status: 0, body: null, error: err.message }};
                    }}
                }}
            """)
            return result
        except Exception as e:
            return {"success": False, "status": 0, "error": str(e)}

    def _extract_value(self, page, action: Dict[str, Any]) -> Any:
        """Extract a value from the page state."""
        source = action.get("source", "cookie")
        key = action.get("key", "")

        if source == "cookie":
            cookies = page.context.cookies()
            for c in cookies:
                if c.get("name") == key:
                    return c["value"]
            return None

        elif source == "localstorage":
            try:
                return page.evaluate(f'localStorage.getItem("{key}")')
            except Exception:
                return None

        elif source == "page":
            try:
                return page.evaluate(f'document.querySelector("{key}")?.textContent')
            except Exception:
                return None

        return None

    def _format_recent_requests(self, requests: List[Dict[str, Any]]) -> str:
        """Format recent requests for the AI prompt."""
        lines = []
        for req in requests:
            lines.append(
                f"  {req.get('method', '?')} {req.get('url', '?')}"
                f" → {req.get('status', '?')}"
            )
            if req.get("body"):
                lines.append(f"    Body: {str(req['body'])[:200]}")
        return "\n".join(lines) if lines else "  (none)"

    def generate_recipe_from_execution(
        self,
        step_results: List[StepResult],
        airline_url: str,
        airline_group: str,
        airlines: List[str],
    ) -> Optional[Dict[str, Any]]:
        """Auto-generate a recipe card from a successful Tier 3 execution.

        Called after a successful live booking to compile the steps into
        a reusable recipe card, so future bookings drop to Tier 1.
        """
        if not self._api_key:
            import os
            self._api_key = os.environ.get("ANTHROPIC_API_KEY")

        if not self._api_key:
            return None

        # Build the step summary
        steps_summary = []
        for sr in step_results:
            if sr.success and sr.status_code:
                steps_summary.append({
                    "name": sr.step_name,
                    "status_code": sr.status_code,
                    "response_preview": str(sr.response_body)[:500] if sr.response_body else None,
                    "extracted": sr.extracted,
                })

        prompt = f"""\
I just completed a successful live booking on {airline_url}.
Here are the steps that worked:

{json.dumps(steps_summary, indent=2)}

Generate a BookingRecipe JSON card from these steps so future bookings
can execute without AI. Use standard ${{variable}} placeholders.

Airline group: {airline_group}
Airlines: {json.dumps(airlines)}
Base URL: {airline_url}

Return ONLY the JSON object.
"""

        try:
            import anthropic

            client = anthropic.Anthropic(api_key=self._api_key)
            response = client.messages.create(
                model=self._model,
                max_tokens=4096,
                system=GENERATOR_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )

            content = response.content[0].text.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

            recipe_data = json.loads(content)
            recipe_data.setdefault("recipe_id", f"{airline_group}_recipe")
            recipe_data.setdefault("airline_group", airline_group)
            recipe_data.setdefault("airlines", airlines)
            recipe_data.setdefault("metadata", {})
            recipe_data["metadata"]["created_by"] = "anastasia_live_executor_autogen"
            recipe_data["metadata"]["created_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")

            logger.info(
                "[AILiveExecutor] Auto-generated recipe for %s (%d steps)",
                airline_group,
                len(recipe_data.get("steps", [])),
            )
            return recipe_data

        except Exception as e:
            logger.error("[AILiveExecutor] Recipe auto-generation failed: %s", e)
            return None


# Import from generator module for the system prompt
from .generator import GENERATOR_SYSTEM_PROMPT  # noqa: E402
