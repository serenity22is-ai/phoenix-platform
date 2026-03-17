"""
Unified Assist Agent — One AI that handles everything.

Combines:
- Flight booking (search, compare, book via Redbox API)
- Integration support (SDK setup, troubleshooting, code generation)
- Admin configuration (pricing, display, branding, features via conversation)
- System updates (SDK version checks, migration guidance)

Two execution modes:
- WEB: Admin dashboard chat — diagnostics, code gen, config changes, booking
- CLI: Local execution — all web features + direct file read/write/edit

The agent determines intent from natural language. No mode switching needed.

MYSTES KYRIOS LLC — Confidential.
"""

import fnmatch
import json
import logging
import os
import re
import subprocess
import time
from typing import Optional

import anthropic

from ..client import RedboxClient
from .knowledge_base import KNOWLEDGE_BASE
from .integration_kb import INTEGRATION_KNOWLEDGE_BASE
from .pricing import PricingModel, apply_pricing_to_results
from .security import (
    ActionType, AdminAuth, AuditLog,
    classify_action, generate_admin_token, hash_token,
)
from .tools import TOOL_DEFINITIONS
from .integration_tools import INTEGRATION_TOOL_DEFINITIONS

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
MAX_AGENT_TURNS = 20
MAX_CONVERSATION_MESSAGES = 100

# Files/dirs the agent must never touch
BLOCKED_PATTERNS = [
    ".env", ".env.*", "*.pem", "*.key", "*.cert",
    "node_modules/*", "__pycache__/*", ".git/*",
    "*.pyc", ".DS_Store", "*.sqlite", "*.db",
]

# Commands that require explicit user confirmation
DANGEROUS_COMMANDS = [
    "rm ", "rm -", "rmdir", "drop ", "delete ",
    "git push", "git reset", "git checkout .",
    "pip uninstall", "npm uninstall",
    "docker rm", "docker rmi",
]


def _is_blocked_path(path: str) -> bool:
    """Check if a file path matches the blocklist."""
    basename = os.path.basename(path)
    for pattern in BLOCKED_PATTERNS:
        if fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(basename, pattern):
            return True
    return False


def _is_dangerous_command(cmd: str) -> bool:
    """Check if a command requires confirmation."""
    cmd_lower = cmd.lower().strip()
    return any(d in cmd_lower for d in DANGEROUS_COMMANDS)


class AssistAgent:
    """
    Unified assistant that handles booking, integration, and admin tasks.

    Usage:
        # Web mode (admin dashboard chat)
        agent = AssistAgent(
            client=client,
            anthropic_api_key="sk-ant-...",
            mode="web",
        )

        # CLI mode (local file access)
        agent = AssistAgent(
            client=client,
            anthropic_api_key="sk-ant-...",
            mode="cli",
            project_root="/path/to/customer/project",
        )

        response = agent.chat("My search endpoint returns a 500 error")
    """

    def __init__(
        self,
        client: RedboxClient,
        anthropic_api_key: str,
        model: str = DEFAULT_MODEL,
        mode: str = "web",              # "web" or "cli"
        agency_name: Optional[str] = None,
        pricing: Optional[PricingModel] = None,
        agency_config: Optional[dict] = None,
        project_root: Optional[str] = None,
        on_confirm: Optional[callable] = None,
        admin_auth: Optional[AdminAuth] = None,
        audit_log: Optional[AuditLog] = None,
        session_id: Optional[str] = None,
        system_prompt_extra: Optional[str] = None,
    ):
        """
        Initialize the unified assistant.

        Args:
            client: Configured RedboxClient instance
            anthropic_api_key: Anthropic API key
            model: Claude model ID
            mode: "web" (dashboard chat) or "cli" (local file access)
            agency_name: Agency name for personalized responses
            pricing: PricingModel for agency markup
            agency_config: Full agency config dict (for config tools)
            project_root: Absolute path to customer's project (CLI mode)
            on_confirm: Callback for user confirmation on destructive actions.
                        Signature: on_confirm(action_description: str) -> bool
            admin_auth: AdminAuth instance for code mutation authorization.
                        If None, all code changes are allowed (dev mode).
            audit_log: AuditLog instance for recording all actions.
                        If None, no audit trail (dev mode).
            session_id: Session identifier for auth + audit tracking.
            system_prompt_extra: Additional instructions
        """
        self.client = client
        self.anthropic_client = anthropic.Anthropic(api_key=anthropic_api_key)
        self.model = model
        self.mode = mode
        self.conversation: list = []
        self.agency_name = agency_name
        self.pricing = pricing
        self.agency_config = agency_config or {}
        self.project_root = os.path.abspath(project_root) if project_root else None
        self.on_confirm = on_confirm or (lambda desc: True)

        # Security
        self.admin_auth = admin_auth
        self.audit = audit_log
        self.session_id = session_id

        # Build combined system prompt
        self.system_prompt = self._build_system_prompt(system_prompt_extra)

        # Build combined tool list
        self.tools = self._build_tools()

        # Usage tracking
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_requests = 0

        # Config change log
        self.config_changes: list = []

    def _build_system_prompt(self, extra: Optional[str] = None) -> str:
        """Build the combined system prompt."""
        prompt = KNOWLEDGE_BASE + "\n" + INTEGRATION_KNOWLEDGE_BASE

        if self.agency_name:
            prompt += f"\n\nYou are ANASTASIA, the AI booking agent for {self.agency_name}."

        if self.pricing:
            prompt += f"""

## AGENCY PRICING MODEL
- Strategy: {self.pricing.strategy}
- Markup: {self.pricing.markup_percent}% + ${self.pricing.markup_flat} flat
- Min: ${self.pricing.min_markup} / Max: ${self.pricing.max_markup}
- Currency: {self.pricing.display_currency}
Search results have agency pricing applied. Use consumer_price when showing prices."""

        prompt += f"""

## EXECUTION MODE: {self.mode.upper()}
{"You have direct access to the customer's project files. Use read_file, write_file, edit_file, search_code, list_files, and run_command to work on their code." if self.mode == "cli" else "You are in web chat mode. You cannot directly access files. Instead, provide code blocks that the admin can copy-paste, or generate complete integration code with generate_integration_code."}

## IMPORTANT BEHAVIOR RULES
- Determine intent from the user's message. Don't ask which mode to use — just handle it.
- If they mention an error, diagnose it immediately.
- If they ask about flights, search for flights.
- If they ask to change settings, update the config.
- If they need integration help, provide framework-specific code.
- Be concise. These are operators running businesses, not students.
- When generating code, always provide complete working examples.
- In CLI mode, always read the relevant file before editing it.
- Never touch .env files, credentials, or node_modules.
- Code changes (write_file, edit_file, run_command) require admin authorization.
  If a tool returns requires_auth=true, tell the user they need to provide their admin token.
  In CLI mode: they run /auth <token>. In web mode: they paste the token in chat.
- Read-only operations (read_file, search_code, list_files, diagnostics) never require auth.
- Operational actions (flight search, config changes, health checks) never require auth.
"""

        if extra:
            prompt += f"\n{extra}"

        return prompt

    def _build_tools(self) -> list:
        """Build the combined tool list based on mode."""
        tools = list(TOOL_DEFINITIONS)  # All booking tools

        for tool in INTEGRATION_TOOL_DEFINITIONS:
            # Skip file operation tools in web mode
            if self.mode == "web" and tool["name"] in (
                "read_file", "write_file", "edit_file",
                "search_code", "list_files", "run_command",
            ):
                continue
            tools.append(tool)

        return tools

    def chat(self, user_message: str) -> str:
        """
        Send a message and get the agent's response.

        The agent may make multiple tool calls before returning.

        Args:
            user_message: Natural language message from the admin

        Returns:
            The agent's text response
        """
        self.conversation.append({
            "role": "user",
            "content": user_message,
        })

        self._trim_conversation()

        turns = 0
        while turns < MAX_AGENT_TURNS:
            turns += 1

            try:
                response = self.anthropic_client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=[{
                        "type": "text",
                        "text": self.system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }],
                    tools=self.tools,
                    messages=self.conversation,
                )
            except anthropic.APIError as e:
                logger.error(f"Anthropic API error: {e}")
                error_msg = "I'm having trouble connecting. Please try again."
                self.conversation.append({
                    "role": "assistant",
                    "content": error_msg,
                })
                return error_msg

            self.total_input_tokens += response.usage.input_tokens
            self.total_output_tokens += response.usage.output_tokens
            self.total_requests += 1

            if response.stop_reason == "end_turn":
                text = self._extract_text(response.content)
                self.conversation.append({
                    "role": "assistant",
                    "content": response.content,
                })
                return text

            elif response.stop_reason == "tool_use":
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
                text = self._extract_text(response.content)
                if text:
                    self.conversation.append({
                        "role": "assistant",
                        "content": response.content,
                    })
                    return text
                break

        fallback = "I've completed my analysis. What else can I help with?"
        self.conversation.append({
            "role": "assistant",
            "content": fallback,
        })
        return fallback

    def authorize_admin(self, token: str) -> bool:
        """
        Authorize this session for code mutations.

        Args:
            token: The admin auth token (adm_...)

        Returns:
            True if authorized, False if token is invalid.
        """
        if not self.admin_auth:
            return True  # No auth configured = dev mode
        if not self.session_id:
            return False
        return self.admin_auth.authorize(self.session_id, token)

    def _execute_tool(self, tool_name: str, tool_input: dict) -> dict:
        """Route a tool call to the corresponding handler, with security gating."""
        logger.info(f"Executing tool: {tool_name}")
        start = time.time()

        # Security gate: check action classification
        action_type = classify_action(tool_name, tool_input)

        if action_type == ActionType.CODE_MUTATION:
            # Code mutations require admin auth
            if self.admin_auth and self.session_id:
                if not self.admin_auth.is_authorized(self.session_id):
                    self._audit_action(
                        action_type, tool_name, tool_input,
                        False, "Blocked: admin auth required",
                    )
                    return {
                        "success": False,
                        "error": "This action requires admin authorization. "
                                 "Please provide your admin token to proceed with code changes.",
                        "requires_auth": True,
                    }

        try:
            # ============== BOOKING TOOLS ==============
            if tool_name == "search_airports":
                result = self.client.search_airports(
                    query=tool_input["query"],
                    max_results=tool_input.get("max_results", 10),
                )
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

                # FF numbers from passenger data
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

            # ============== FILE OPERATIONS (CLI only) ==============
            elif tool_name == "read_file":
                result = self._tool_read_file(tool_input)

            elif tool_name == "write_file":
                result = self._tool_write_file(tool_input)

            elif tool_name == "edit_file":
                result = self._tool_edit_file(tool_input)

            elif tool_name == "search_code":
                result = self._tool_search_code(tool_input)

            elif tool_name == "list_files":
                result = self._tool_list_files(tool_input)

            elif tool_name == "run_command":
                result = self._tool_run_command(tool_input)

            # ============== DIAGNOSTICS ==============
            elif tool_name == "diagnose_error":
                result = self._tool_diagnose_error(tool_input)

            elif tool_name == "generate_integration_code":
                result = self._tool_generate_integration_code(tool_input)

            elif tool_name == "check_integration_health":
                result = self._tool_check_health(tool_input)

            # ============== ADMIN CONFIG ==============
            elif tool_name == "update_agency_config":
                result = self._tool_update_config(tool_input)

            elif tool_name == "get_agency_config":
                result = self._tool_get_config(tool_input)

            elif tool_name == "get_sdk_version":
                from .. import __version__
                result = {
                    "success": True,
                    "current_version": __version__,
                    "package": "picasso-redbox-sdk",
                }

            else:
                result = {"success": False, "error": f"Unknown tool: {tool_name}"}

        except Exception as e:
            logger.error(f"Tool execution error ({tool_name}): {e}")
            result = {"success": False, "error": str(e)}

        elapsed = time.time() - start
        logger.info(f"Tool {tool_name} completed in {elapsed:.2f}s")

        # Audit log
        self._audit_action(
            action_type, tool_name, tool_input,
            result.get("success", False),
        )

        return result

    def _audit_action(
        self, action_type: str, tool_name: str, tool_input: dict,
        success: bool, notes: Optional[str] = None,
    ):
        """Record an action to the audit log if configured."""
        if self.audit:
            self.audit.record(
                action_type=action_type,
                tool_name=tool_name,
                tool_input=tool_input,
                result_success=success,
                session_id=self.session_id,
                triggered_by="user",
                notes=notes,
            )

    # ================================================================
    # FILE OPERATION IMPLEMENTATIONS
    # ================================================================

    def _resolve_path(self, relative_path: str) -> Optional[str]:
        """Resolve a relative path to absolute, with security checks."""
        if not self.project_root:
            return None

        # Normalize and resolve
        abs_path = os.path.normpath(
            os.path.join(self.project_root, relative_path)
        )

        # Ensure path stays within project root (prevent traversal)
        if not abs_path.startswith(self.project_root):
            return None

        # Check blocklist
        rel = os.path.relpath(abs_path, self.project_root)
        if _is_blocked_path(rel):
            return None

        return abs_path

    def _tool_read_file(self, inp: dict) -> dict:
        if self.mode != "cli":
            return {"success": False, "error": "File operations require CLI mode"}

        abs_path = self._resolve_path(inp["path"])
        if not abs_path:
            return {"success": False, "error": f"Path blocked or outside project: {inp['path']}"}

        if not os.path.isfile(abs_path):
            return {"success": False, "error": f"File not found: {inp['path']}"}

        try:
            with open(abs_path, "r", errors="replace") as f:
                lines = f.readlines()
        except Exception as e:
            return {"success": False, "error": str(e)}

        start = inp.get("start_line", 1) - 1
        end = inp.get("end_line", len(lines))
        selected = lines[max(0, start):end]

        numbered = ""
        for i, line in enumerate(selected, start=start + 1):
            numbered += f"{i:4d} | {line}"

        return {
            "success": True,
            "path": inp["path"],
            "total_lines": len(lines),
            "showing": f"lines {start + 1}-{min(end, len(lines))}",
            "content": numbered,
        }

    def _tool_write_file(self, inp: dict) -> dict:
        if self.mode != "cli":
            return {"success": False, "error": "File operations require CLI mode"}

        abs_path = self._resolve_path(inp["path"])
        if not abs_path:
            return {"success": False, "error": f"Path blocked or outside project: {inp['path']}"}

        # Confirm with user
        desc = inp.get("description", f"Write file: {inp['path']}")
        if not self.on_confirm(f"Write file: {inp['path']} — {desc}"):
            return {"success": False, "error": "User declined the file write"}

        try:
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            with open(abs_path, "w") as f:
                f.write(inp["content"])
        except Exception as e:
            return {"success": False, "error": str(e)}

        return {
            "success": True,
            "path": inp["path"],
            "bytes_written": len(inp["content"]),
        }

    def _tool_edit_file(self, inp: dict) -> dict:
        if self.mode != "cli":
            return {"success": False, "error": "File operations require CLI mode"}

        abs_path = self._resolve_path(inp["path"])
        if not abs_path:
            return {"success": False, "error": f"Path blocked or outside project: {inp['path']}"}

        if not os.path.isfile(abs_path):
            return {"success": False, "error": f"File not found: {inp['path']}"}

        try:
            with open(abs_path, "r") as f:
                content = f.read()
        except Exception as e:
            return {"success": False, "error": str(e)}

        old = inp["old_string"]
        new = inp["new_string"]

        count = content.count(old)
        if count == 0:
            return {"success": False, "error": "old_string not found in file"}
        if count > 1:
            return {"success": False, "error": f"old_string found {count} times — must be unique. Provide more context."}

        # Confirm
        if not self.on_confirm(f"Edit {inp['path']}: replace '{old[:60]}...' with '{new[:60]}...'"):
            return {"success": False, "error": "User declined the edit"}

        content = content.replace(old, new, 1)
        with open(abs_path, "w") as f:
            f.write(content)

        return {
            "success": True,
            "path": inp["path"],
            "replaced": True,
        }

    def _tool_search_code(self, inp: dict) -> dict:
        if self.mode != "cli":
            return {"success": False, "error": "File operations require CLI mode"}
        if not self.project_root:
            return {"success": False, "error": "No project root set"}

        pattern = inp["pattern"]
        file_pattern = inp.get("file_pattern", "*")
        max_results = inp.get("max_results", 30)

        matches = []
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
        except re.error:
            # Fall back to literal search
            compiled = re.compile(re.escape(pattern), re.IGNORECASE)

        for root, dirs, files in os.walk(self.project_root):
            # Skip blocked directories
            dirs[:] = [d for d in dirs if d not in (
                "node_modules", "__pycache__", ".git", ".venv",
                "venv", "env", ".tox", "dist", "build",
            )]

            for fname in files:
                if file_pattern != "*" and not fnmatch.fnmatch(fname, file_pattern):
                    continue

                fpath = os.path.join(root, fname)
                rel = os.path.relpath(fpath, self.project_root)

                if _is_blocked_path(rel):
                    continue

                try:
                    with open(fpath, "r", errors="replace") as f:
                        for i, line in enumerate(f, 1):
                            if compiled.search(line):
                                matches.append({
                                    "file": rel,
                                    "line": i,
                                    "text": line.rstrip()[:200],
                                })
                                if len(matches) >= max_results:
                                    break
                except (OSError, UnicodeDecodeError):
                    continue

                if len(matches) >= max_results:
                    break
            if len(matches) >= max_results:
                break

        return {
            "success": True,
            "pattern": pattern,
            "matches": matches,
            "count": len(matches),
            "truncated": len(matches) >= max_results,
        }

    def _tool_list_files(self, inp: dict) -> dict:
        if self.mode != "cli":
            return {"success": False, "error": "File operations require CLI mode"}
        if not self.project_root:
            return {"success": False, "error": "No project root set"}

        rel_path = inp.get("path", ".")
        abs_path = self._resolve_path(rel_path) or self.project_root
        max_depth = inp.get("max_depth", 3)
        file_pattern = inp.get("pattern")

        entries = []

        def walk(path: str, depth: int, prefix: str = ""):
            if depth > max_depth:
                return
            try:
                items = sorted(os.listdir(path))
            except OSError:
                return

            for item in items:
                full = os.path.join(path, item)
                rel = os.path.relpath(full, self.project_root)

                if item in ("node_modules", "__pycache__", ".git", ".venv", "venv"):
                    entries.append(f"{prefix}{item}/ [skipped]")
                    continue

                if os.path.isdir(full):
                    entries.append(f"{prefix}{item}/")
                    walk(full, depth + 1, prefix + "  ")
                else:
                    if file_pattern and not fnmatch.fnmatch(item, file_pattern):
                        continue
                    size = os.path.getsize(full)
                    entries.append(f"{prefix}{item} ({size:,} bytes)")

        walk(abs_path, 0)

        return {
            "success": True,
            "path": rel_path,
            "entries": entries[:200],  # Cap output
            "count": len(entries),
        }

    def _tool_run_command(self, inp: dict) -> dict:
        if self.mode != "cli":
            return {"success": False, "error": "Command execution requires CLI mode"}
        if not self.project_root:
            return {"success": False, "error": "No project root set"}

        cmd = inp["command"]
        desc = inp.get("description", cmd)

        # Confirm dangerous commands
        if _is_dangerous_command(cmd):
            if not self.on_confirm(f"Run potentially destructive command: {cmd}"):
                return {"success": False, "error": "User declined the command"}

        try:
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=60,
            )
            return {
                "success": result.returncode == 0,
                "command": cmd,
                "return_code": result.returncode,
                "stdout": result.stdout[:5000],
                "stderr": result.stderr[:2000],
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"Command timed out after 60s: {cmd}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ================================================================
    # DIAGNOSTIC IMPLEMENTATIONS
    # ================================================================

    def _tool_diagnose_error(self, inp: dict) -> dict:
        """
        Structured error diagnosis. The AI will use this result
        to formulate a natural language response.
        """
        error = inp["error_text"]
        context = inp.get("context", "")

        diagnosis = {
            "success": True,
            "error_text": error[:2000],
            "context": context[:500],
        }

        # Quick pattern matching for common errors
        error_lower = error.lower()

        if "modulenotfounderror" in error_lower or "importerror" in error_lower:
            diagnosis["category"] = "missing_dependency"
            if "picasso" in error_lower:
                diagnosis["quick_fix"] = "pip install picasso-redbox-sdk[all]"
            elif "anthropic" in error_lower:
                diagnosis["quick_fix"] = "pip install picasso-redbox-sdk[agent]"
            elif "flask" in error_lower:
                diagnosis["quick_fix"] = "pip install picasso-redbox-sdk[agent]"

        elif "401" in error or "unauthorized" in error_lower:
            diagnosis["category"] = "authentication"
            diagnosis["quick_fix"] = "Check API key in Authorization header. Format: 'Bearer mys_your_key'"

        elif "403" in error or "forbidden" in error_lower:
            diagnosis["category"] = "authorization"
            diagnosis["quick_fix"] = "API key may be deactivated. Contact admin for a new key."

        elif "cors" in error_lower or "access-control-allow-origin" in error_lower:
            diagnosis["category"] = "cors"
            diagnosis["quick_fix"] = "Route API calls through your backend. Browser → Your Server → ANASTASIA API. Never call the API directly from browser JS."

        elif "connectionerror" in error_lower or "econnrefused" in error_lower:
            diagnosis["category"] = "connectivity"
            diagnosis["quick_fix"] = "Check that the API server is running and the base URL is correct."

        elif "fare_verification_failed" in error_lower:
            diagnosis["category"] = "stale_fare"
            diagnosis["quick_fix"] = "The fare expired. Run a new search — flight prices are live."

        elif "timeout" in error_lower:
            diagnosis["category"] = "timeout"
            diagnosis["quick_fix"] = "The request took too long. Try again. If persistent, reduce max_results or check network."

        elif "json" in error_lower and ("decode" in error_lower or "parse" in error_lower):
            diagnosis["category"] = "response_parsing"
            diagnosis["quick_fix"] = "The API returned unexpected content. Check the URL path includes /api/v1/ prefix."

        else:
            diagnosis["category"] = "unknown"
            diagnosis["quick_fix"] = None

        return diagnosis

    def _tool_generate_integration_code(self, inp: dict) -> dict:
        """Return metadata — Claude will generate the actual code."""
        return {
            "success": True,
            "framework": inp["framework"],
            "feature": inp["feature"],
            "api_base": inp.get("api_base", "https://your-server.com"),
            "options": inp.get("options", {}),
            "note": "Generate complete, working code for this framework and feature. Include all imports, error handling, and comments.",
        }

    def _tool_check_health(self, inp: dict) -> dict:
        """Run integration health checks."""
        results = {}
        api_base = inp.get("api_base", "")
        api_key = inp.get("api_key", "")
        checks = inp.get("checks", ["all"])

        if "all" in checks:
            checks = ["connectivity", "auth", "search", "config"]

        if "connectivity" in checks:
            if api_base:
                try:
                    import urllib.request
                    req = urllib.request.Request(f"{api_base}/api/v1/health")
                    resp = urllib.request.urlopen(req, timeout=10)
                    results["connectivity"] = {
                        "status": "pass",
                        "response_code": resp.getcode(),
                    }
                except Exception as e:
                    results["connectivity"] = {
                        "status": "fail",
                        "error": str(e),
                    }
            else:
                results["connectivity"] = {
                    "status": "skip",
                    "reason": "No api_base provided",
                }

        if "auth" in checks:
            if api_base and api_key:
                try:
                    import urllib.request
                    req = urllib.request.Request(
                        f"{api_base}/api/v1/admin/config",
                        headers={"Authorization": f"Bearer {api_key}"},
                    )
                    resp = urllib.request.urlopen(req, timeout=10)
                    results["auth"] = {
                        "status": "pass",
                        "response_code": resp.getcode(),
                    }
                except Exception as e:
                    results["auth"] = {
                        "status": "fail",
                        "error": str(e),
                    }
            else:
                results["auth"] = {
                    "status": "skip",
                    "reason": "Need api_base and api_key",
                }

        if "search" in checks:
            try:
                airports = self.client.search_airports("JFK", max_results=1)
                results["search"] = {
                    "status": "pass" if airports else "fail",
                    "airport_search": bool(airports),
                }
            except Exception as e:
                results["search"] = {
                    "status": "fail",
                    "error": str(e),
                }

        if "config" in checks:
            results["config"] = {
                "status": "pass",
                "agency_name": self.agency_name or "Not set",
                "mode": self.mode,
                "pricing_strategy": self.pricing.strategy if self.pricing else "Not configured",
                "tools_available": len(self.tools),
            }

        return {
            "success": True,
            "checks": results,
            "overall": "pass" if all(
                r.get("status") in ("pass", "skip") for r in results.values()
            ) else "fail",
        }

    # ================================================================
    # ADMIN CONFIG IMPLEMENTATIONS
    # ================================================================

    def _tool_update_config(self, inp: dict) -> dict:
        """Update agency config section."""
        section = inp["section"]
        updates = inp["updates"]

        if section == "pricing" and self.pricing:
            for key, val in updates.items():
                if hasattr(self.pricing, key):
                    setattr(self.pricing, key, val)
            self.config_changes.append({
                "section": "pricing",
                "updates": updates,
                "timestamp": time.time(),
            })
            return {
                "success": True,
                "section": "pricing",
                "updated": updates,
                "current": self.pricing.to_dict(),
            }

        elif section in ("display", "branding", "features"):
            if section in self.agency_config:
                self.agency_config[section].update(updates)
            else:
                self.agency_config[section] = updates

            self.config_changes.append({
                "section": section,
                "updates": updates,
                "timestamp": time.time(),
            })
            return {
                "success": True,
                "section": section,
                "updated": updates,
                "current": self.agency_config.get(section, {}),
            }

        return {"success": False, "error": f"Unknown config section: {section}"}

    def _tool_get_config(self, inp: dict) -> dict:
        """Get current agency config."""
        section = inp.get("section", "all")

        if section == "all":
            return {
                "success": True,
                "pricing": self.pricing.to_dict() if self.pricing else None,
                "display": self.agency_config.get("display", {}),
                "branding": self.agency_config.get("branding", {}),
                "features": self.agency_config.get("features", {}),
            }
        elif section == "pricing":
            return {
                "success": True,
                "pricing": self.pricing.to_dict() if self.pricing else None,
            }
        elif section in ("display", "branding", "features"):
            return {
                "success": True,
                section: self.agency_config.get(section, {}),
            }

        return {"success": False, "error": f"Unknown section: {section}"}

    # ================================================================
    # UTILITY
    # ================================================================

    def _extract_text(self, content_blocks) -> str:
        parts = []
        for block in content_blocks:
            if hasattr(block, "text"):
                parts.append(block.text)
        return "\n".join(parts)

    def _trim_conversation(self):
        if len(self.conversation) > MAX_CONVERSATION_MESSAGES:
            keep = MAX_CONVERSATION_MESSAGES - 2
            self.conversation = self.conversation[:2] + self.conversation[-keep:]

    def reset(self):
        """Clear conversation and start fresh."""
        self.conversation = []
        self.config_changes = []

    def get_usage(self) -> dict:
        input_cost = (self.total_input_tokens / 1_000_000) * 0.80
        output_cost = (self.total_output_tokens / 1_000_000) * 4.00
        return {
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
            "total_requests": self.total_requests,
            "estimated_cost_usd": round(input_cost + output_cost, 4),
            "config_changes": len(self.config_changes),
        }

    def get_pending_config_changes(self) -> list:
        """Get config changes made during this session (for persistence)."""
        return self.config_changes
