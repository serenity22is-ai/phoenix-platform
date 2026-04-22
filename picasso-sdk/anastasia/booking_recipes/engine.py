"""Recipe Engine — Executes compiled booking recipes via Playwright + Bright Data.

Tier 1 execution: zero AI cost. Loads a recipe card, establishes a
Bright Data Scraping Browser session, replays the airline's internal API
calls with substituted passenger/payment data.

Usage:
    engine = RecipeEngine(proxy_module)
    result = engine.execute(recipe, variables, cdp_url)
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class StepResult:
    """Result of executing a single recipe step."""

    step_name: str
    success: bool
    status_code: Optional[int] = None
    response_body: Any = None
    extracted: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    duration_ms: int = 0


@dataclass
class RecipeExecutionResult:
    """Result of a full recipe execution."""

    success: bool
    confirmation_code: Optional[str] = None
    total_charged: Optional[str] = None
    charged_currency: Optional[str] = None
    e_ticket: Optional[str] = None
    step_results: List[StepResult] = field(default_factory=list)
    error: Optional[str] = None
    total_duration_ms: int = 0
    tier: str = "tier1"  # tier1=recipe, tier3=ai_live


def _resolve_variable(template: str, variables: Dict[str, Any]) -> str:
    """Replace ${var_name} placeholders in a string with variable values."""
    if not isinstance(template, str):
        return template

    def replacer(match):
        var_name = match.group(1)
        value = variables.get(var_name, match.group(0))  # Keep original if not found
        return str(value) if value is not None else ""

    return re.sub(r"\$\{(\w+)\}", replacer, template)


def _resolve_template(obj: Any, variables: Dict[str, Any]) -> Any:
    """Recursively resolve ${var} placeholders in a JSON-like structure."""
    if isinstance(obj, str):
        return _resolve_variable(obj, variables)
    if isinstance(obj, dict):
        return {k: _resolve_template(v, variables) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_template(item, variables) for item in obj]
    return obj


def _extract_jsonpath(data: Any, path: str) -> Any:
    """Simple JSONPath extraction (supports $.field.nested[0].value).

    Not a full JSONPath implementation — covers the common patterns
    used in recipe cards.
    """
    if not path.startswith("$."):
        return None

    parts = path[2:].split(".")
    current = data

    for part in parts:
        if current is None:
            return None

        # Handle array index: field[0]
        array_match = re.match(r"(\w+)\[(\d+)\]", part)
        if array_match:
            field_name = array_match.group(1)
            index = int(array_match.group(2))
            if isinstance(current, dict):
                current = current.get(field_name)
            if isinstance(current, list) and index < len(current):
                current = current[index]
            else:
                return None
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None

    return current


class RecipeEngine:
    """Executes compiled booking recipes against airline APIs.

    Uses Playwright to establish a Scraping Browser session (for cookies/tokens),
    then replays the recipe's API calls via the browser's fetch() to maintain
    session context (cookies, CORS, anti-bot tokens).
    """

    def __init__(self):
        self._execution_count = 0

    def execute(
        self,
        recipe,  # BookingRecipe
        variables: Dict[str, Any],
        cdp_url: str,
        dry_run: bool = False,
    ) -> RecipeExecutionResult:
        """Execute a booking recipe end-to-end.

        Args:
            recipe: The BookingRecipe to execute
            variables: Passenger data, payment data, search params
            cdp_url: Bright Data Scraping Browser WebSocket URL
            dry_run: If True, stop before payment step

        Returns:
            RecipeExecutionResult with confirmation code or error
        """
        start_time = time.time()
        step_results: List[StepResult] = []
        extracted_vars = dict(variables)  # Copy — we'll accumulate extractions

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return RecipeExecutionResult(
                success=False,
                error="Playwright not installed",
                total_duration_ms=0,
            )

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.connect_over_cdp(cdp_url)
                page = browser.new_page()

                try:
                    # Phase 1: Session setup — load airline page, extract tokens
                    session_result = self._setup_session(
                        page, recipe, extracted_vars
                    )
                    if not session_result["success"]:
                        return RecipeExecutionResult(
                            success=False,
                            error=f"Session setup failed: {session_result.get('error')}",
                            step_results=step_results,
                            total_duration_ms=int((time.time() - start_time) * 1000),
                        )

                    # Merge extracted session tokens into variables
                    extracted_vars.update(session_result.get("tokens", {}))

                    # Phase 2: Execute recipe steps
                    for step in recipe.steps:
                        # Dry run: stop before payment
                        if dry_run and step.name in (
                            "submit_payment",
                            "payment",
                            "pay",
                        ):
                            logger.info(
                                "[RecipeEngine] Dry run — stopping before %s",
                                step.name,
                            )
                            break

                        step_result = self._execute_step(
                            page, step, extracted_vars, recipe
                        )
                        step_results.append(step_result)

                        if step_result.success:
                            # Accumulate extracted values for subsequent steps
                            extracted_vars.update(step_result.extracted)
                        else:
                            # Check error patterns for retry/abort
                            should_retry, should_abort = self._check_error_patterns(
                                step_result, recipe.error_patterns
                            )
                            if should_abort or not step.optional:
                                return RecipeExecutionResult(
                                    success=False,
                                    error=f"Step '{step.name}' failed: {step_result.error}",
                                    step_results=step_results,
                                    total_duration_ms=int(
                                        (time.time() - start_time) * 1000
                                    ),
                                )
                            # Optional step failed — continue

                        # Wipe card data after payment step
                        wipe_after = recipe.card_data_wipe.get("after_step", "")
                        if step.name == wipe_after:
                            self._wipe_card_data(
                                extracted_vars,
                                recipe.card_data_wipe.get("fields", []),
                            )

                finally:
                    browser.close()
                    # Always wipe card data on exit
                    if recipe.card_data_wipe.get("on_failure", True):
                        self._wipe_card_data(
                            extracted_vars,
                            recipe.card_data_wipe.get("fields", []),
                        )

        except Exception as e:
            logger.error("[RecipeEngine] Execution error: %s", e)
            # Wipe card data on any exception
            self._wipe_card_data(
                extracted_vars,
                recipe.card_data_wipe.get("fields", []),
            )
            return RecipeExecutionResult(
                success=False,
                error=str(e),
                step_results=step_results,
                total_duration_ms=int((time.time() - start_time) * 1000),
            )

        self._execution_count += 1

        # Extract final outputs
        confirmation_code = extracted_vars.get("pnr") or extracted_vars.get(
            "confirmation_code"
        )
        total_charged = extracted_vars.get("total_charged")
        charged_currency = extracted_vars.get("charged_currency")
        e_ticket = extracted_vars.get("e_ticket_number")

        return RecipeExecutionResult(
            success=bool(confirmation_code) or dry_run,
            confirmation_code=confirmation_code,
            total_charged=total_charged,
            charged_currency=charged_currency,
            e_ticket=e_ticket,
            step_results=step_results,
            total_duration_ms=int((time.time() - start_time) * 1000),
        )

    def _setup_session(
        self, page, recipe, variables: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Load the airline page and extract session tokens."""
        setup = recipe.session_setup
        if not setup:
            return {"success": True, "tokens": {}}

        load_url = _resolve_variable(
            setup.get("load_url", recipe.base_url + recipe.language_path),
            variables,
        )
        wait_for = setup.get("wait_for", "networkidle")

        try:
            page.goto(load_url, wait_until=wait_for, timeout=30000)
        except Exception as e:
            return {"success": False, "error": f"Failed to load {load_url}: {e}"}

        # Extract tokens from cookies, headers, page content
        tokens = {}
        extract_config = setup.get("extract_tokens", {})

        for token_name, config in extract_config.items():
            source = config.get("source", "cookie")

            if source == "cookie":
                cookie_name = config.get("name", token_name)
                cookies = page.context.cookies()
                for cookie in cookies:
                    if cookie.get("name") == cookie_name:
                        tokens[token_name] = cookie["value"]
                        break

            elif source == "meta":
                selector = config.get("selector", f'meta[name="{token_name}"]')
                try:
                    el = page.query_selector(selector)
                    if el:
                        tokens[token_name] = el.get_attribute("content") or ""
                except Exception:
                    pass

            elif source == "script":
                # Extract from inline script variable
                pattern = config.get("pattern", "")
                if pattern:
                    try:
                        content = page.content()
                        match = re.search(pattern, content)
                        if match:
                            tokens[token_name] = match.group(1)
                    except Exception:
                        pass

            elif source == "localstorage":
                key = config.get("key", token_name)
                try:
                    value = page.evaluate(f'localStorage.getItem("{key}")')
                    if value:
                        tokens[token_name] = value
                except Exception:
                    pass

        logger.info(
            "[RecipeEngine] Session setup: loaded %s, extracted %d tokens",
            load_url,
            len(tokens),
        )
        return {"success": True, "tokens": tokens}

    def _execute_step(
        self, page, step, variables: Dict[str, Any], recipe
    ) -> StepResult:
        """Execute a single recipe step (API call via page.evaluate fetch)."""
        step_start = time.time()

        # Resolve URL and body templates
        url = _resolve_variable(step.url, variables)
        if not url.startswith("http"):
            url = recipe.base_url.rstrip("/") + "/" + url.lstrip("/")

        headers = _resolve_template(step.headers, variables)
        body = _resolve_template(step.body, variables) if step.body else None

        # Optional delay
        if step.delay_before_ms > 0:
            time.sleep(step.delay_before_ms / 1000.0)

        try:
            # Execute fetch via Playwright page context (maintains cookies/session)
            fetch_script = self._build_fetch_script(url, step.method, headers, body)
            response_data = page.evaluate(fetch_script)

            status_code = response_data.get("status")
            response_body = response_data.get("body")

            # Parse JSON response if possible
            if isinstance(response_body, str):
                try:
                    response_body = json.loads(response_body)
                except (json.JSONDecodeError, TypeError):
                    pass

            # Validate response
            validation_error = self._validate_response(
                status_code, response_body, step.validation
            )
            if validation_error:
                return StepResult(
                    step_name=step.name,
                    success=False,
                    status_code=status_code,
                    response_body=response_body,
                    error=validation_error,
                    duration_ms=int((time.time() - step_start) * 1000),
                )

            # Extract values from response
            extracted = {}
            for var_name, json_path in step.response_extract.items():
                value = _extract_jsonpath(response_body, json_path)
                if value is not None:
                    extracted[var_name] = value

            logger.info(
                "[RecipeEngine] Step '%s' OK (HTTP %s, extracted %d vars)",
                step.name,
                status_code,
                len(extracted),
            )

            return StepResult(
                step_name=step.name,
                success=True,
                status_code=status_code,
                response_body=response_body,
                extracted=extracted,
                duration_ms=int((time.time() - step_start) * 1000),
            )

        except Exception as e:
            logger.error("[RecipeEngine] Step '%s' error: %s", step.name, e)
            return StepResult(
                step_name=step.name,
                success=False,
                error=str(e),
                duration_ms=int((time.time() - step_start) * 1000),
            )

    def _build_fetch_script(
        self,
        url: str,
        method: str,
        headers: Dict[str, str],
        body: Any,
    ) -> str:
        """Build a JavaScript fetch() call to execute in the browser context.

        This maintains the browser's session cookies, CORS tokens, and
        anti-bot state — the key advantage over direct HTTP requests.
        """
        headers_json = json.dumps(headers)
        options = {
            "method": method,
            "headers": json.loads(headers_json),
            "credentials": "include",
        }
        if body is not None:
            options["body"] = json.dumps(body)
            if "Content-Type" not in headers:
                options["headers"]["Content-Type"] = "application/json"

        options_json = json.dumps(options)
        # JavaScript fetch that returns {status, body} to Playwright
        return f"""
        async () => {{
            try {{
                const resp = await fetch({json.dumps(url)}, {options_json});
                const text = await resp.text();
                return {{ status: resp.status, body: text }};
            }} catch (err) {{
                return {{ status: 0, body: err.message }};
            }}
        }}
        """

    def _validate_response(
        self,
        status_code: Optional[int],
        body: Any,
        validation: Dict[str, Any],
    ) -> Optional[str]:
        """Validate a step response. Returns error message or None."""
        if not validation:
            return None

        # Status code validation
        expected_status = validation.get("status_code")
        if expected_status:
            if isinstance(expected_status, list):
                if status_code not in expected_status:
                    return f"Expected HTTP {expected_status}, got {status_code}"
            elif status_code != expected_status:
                return f"Expected HTTP {expected_status}, got {status_code}"

        # Required fields validation
        required = validation.get("required_fields", [])
        if required and isinstance(body, dict):
            for field_name in required:
                if _extract_jsonpath(body, f"$.{field_name}") is None:
                    if body.get(field_name) is None:
                        return f"Required field '{field_name}' missing from response"

        # Body must not contain error patterns
        body_must_not_contain = validation.get("body_must_not_contain", [])
        if body_must_not_contain and isinstance(body, (str, dict)):
            body_str = json.dumps(body) if isinstance(body, dict) else body
            for pattern in body_must_not_contain:
                if pattern.lower() in body_str.lower():
                    return f"Response contains error pattern: '{pattern}'"

        return None

    def _check_error_patterns(
        self,
        step_result: StepResult,
        error_patterns: Dict[str, Dict[str, Any]],
    ) -> Tuple[bool, bool]:
        """Check if a failed step matches known error patterns.

        Returns: (should_retry, should_abort)
        """
        for pattern_name, pattern in error_patterns.items():
            # Match by status code
            if "status" in pattern and step_result.status_code == pattern["status"]:
                return (pattern.get("retry", False), pattern.get("abort", False))

            # Match by body content
            if "body_contains" in pattern and step_result.response_body:
                body_str = (
                    json.dumps(step_result.response_body)
                    if isinstance(step_result.response_body, dict)
                    else str(step_result.response_body)
                )
                if pattern["body_contains"].lower() in body_str.lower():
                    return (pattern.get("retry", False), pattern.get("abort", True))

        return (False, False)

    def _wipe_card_data(
        self, variables: Dict[str, Any], fields: List[str]
    ) -> None:
        """Securely wipe card data from the variables dict."""
        for field_name in fields:
            if field_name in variables:
                variables[field_name] = None
        # Also wipe common card field names
        for key in list(variables.keys()):
            if any(
                term in key.lower()
                for term in ("card_number", "cvv", "card_cvv", "card_exp")
            ):
                variables[key] = None
