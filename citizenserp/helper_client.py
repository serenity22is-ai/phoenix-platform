#!/usr/bin/env python3
"""
MYSTES Helper Client v1.0.0

Standalone application that helpers run on their local machines.
Connects to the Mystes WebSocket server and allows Mystes to remotely
control a Playwright browser for flight booking arbitrage transactions.

Usage:
    python helper_client.py --token <SESSION_TOKEN>
    python helper_client.py --server ws://mystes.example.com:8765 --token <TOKEN>
    python helper_client.py --token <TOKEN> --headless --verbose

Dependencies:
    pip install websockets playwright
    playwright install chromium
"""

import argparse
import asyncio
import base64
import json
import logging
import signal
import subprocess
import sys
import time
from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CLIENT_VERSION = "1.0.0"
DEFAULT_SERVER = "ws://localhost:8765"
COMMAND_TIMEOUT_DEFAULT = 30  # seconds per command

ALLOWED_DOMAINS = {
    # Google
    "google.com", "www.google.com", "flights.google.com",
    # Aggregators
    "skyscanner.com", "www.skyscanner.com", "skyscanner.net",
    "kayak.com", "www.kayak.com",
    "momondo.com", "www.momondo.com",
    "kiwi.com", "www.kiwi.com",
    "expedia.com", "www.expedia.com",
    "booking.com", "www.booking.com",
    "trip.com", "www.trip.com",
    # Major airlines
    "aa.com", "www.aa.com",
    "delta.com", "www.delta.com",
    "united.com", "www.united.com",
    "southwest.com", "www.southwest.com",
    "jetblue.com", "www.jetblue.com",
    "spirit.com", "www.spirit.com",
    "frontierairlines.com", "www.frontierairlines.com",
    "alaskaair.com", "www.alaskaair.com",
    "britishairways.com", "www.britishairways.com",
    "lufthansa.com", "www.lufthansa.com",
    "airfrance.com", "www.airfrance.com",
    "klm.com", "www.klm.com",
    "iberia.com", "www.iberia.com",
    "vueling.com", "www.vueling.com",
    "ryanair.com", "www.ryanair.com",
    "easyjet.com", "www.easyjet.com",
    "emirates.com", "www.emirates.com",
    "qatarairways.com", "www.qatarairways.com",
    "turkishairlines.com", "www.turkishairlines.com",
    "singaporeair.com", "www.singaporeair.com",
    "cathaypacific.com", "www.cathaypacific.com",
    "ana.co.jp", "www.ana.co.jp",
    "jal.co.jp", "www.jal.co.jp",
    "avianca.com", "www.avianca.com",
    "latam.com", "www.latam.com",
    "aeromexico.com", "www.aeromexico.com",
    "aircanada.com", "www.aircanada.com",
    "westjet.com", "www.westjet.com",
    "norwegian.com", "www.norwegian.com",
    "wizzair.com", "www.wizzair.com",
}

BANNER = r"""
 ____  _   _  ___  _____ _   _ _____  __
|  _ \| | | |/ _ \| ____| \ | |_ _\ \/ /
| |_) | |_| | | | |  _| |  \| || | \  /
|  __/|  _  | |_| | |___| |\  || | /  \
|_|   |_| |_|\___/|_____|_| \_|___/_/\_\

        Helper Client v{version}
  Flight Price Arbitrage Platform
"""

logger = logging.getLogger("mystes.helper")


# ---------------------------------------------------------------------------
# Dependency checks
# ---------------------------------------------------------------------------

def check_dependencies() -> bool:
    """Verify that websockets and playwright are installed."""
    missing = []
    try:
        import websockets  # noqa: F401
    except ImportError:
        missing.append("websockets")
    try:
        import playwright  # noqa: F401
    except ImportError:
        missing.append("playwright")

    if missing:
        print(f"[ERROR] Missing packages: {', '.join(missing)}")
        print(f"        Install with:  pip install {' '.join(missing)}")
        return False
    return True


def ensure_playwright_browsers() -> bool:
    """Install Playwright Chromium browser if not already present."""
    print("[*] Checking Playwright browsers ...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            print("[+] Playwright Chromium is ready.")
            return True
        else:
            print(f"[ERROR] Playwright install failed:\n{result.stderr}")
            return False
    except FileNotFoundError:
        print("[ERROR] Could not run 'playwright install'. Is playwright on PATH?")
        return False
    except subprocess.TimeoutExpired:
        print("[ERROR] Playwright browser install timed out.")
        return False


# ---------------------------------------------------------------------------
# Domain allowlist check
# ---------------------------------------------------------------------------

def is_domain_allowed(url: str) -> bool:
    """Return True if the URL's host is in the allowlist."""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if host in ALLOWED_DOMAINS:
            return True
        for allowed in ALLOWED_DOMAINS:
            if host.endswith("." + allowed):
                return True
        return False
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Status printer
# ---------------------------------------------------------------------------

def status(msg: str) -> None:
    """Print a timestamped status line visible to the helper."""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"  [{ts}] {msg}")


# ---------------------------------------------------------------------------
# Helper client
# ---------------------------------------------------------------------------

class MystesHelperClient:
    """
    Connects to the Mystes WebSocket server, launches a local Playwright
    browser, and executes remote commands sent by the Mystes orchestrator.
    """

    def __init__(
        self,
        server_url: str,
        auth_token: str,
        headless: bool = False,
    ):
        self.server_url = server_url
        self.auth_token = auth_token
        self.headless = headless

        self.session_id: Optional[str] = None
        self.browser = None
        self.page = None
        self._running = False
        self._commands_executed = 0
        self._commands_failed = 0

    async def run(self) -> None:
        """Main entry point: connect, authenticate, process commands."""
        try:
            import websockets
            from playwright.async_api import async_playwright
        except ImportError as exc:
            logger.error("Missing dependency: %s", exc)
            return

        self._running = True
        status(f"Connecting to {self.server_url} ...")

        try:
            async with websockets.connect(
                self.server_url,
                ping_interval=30,
                ping_timeout=10,
                close_timeout=5,
            ) as ws:
                # Authenticate
                auth_msg = json.dumps({
                    "type": "auth",
                    "token": self.auth_token,
                    "client_version": CLIENT_VERSION,
                    "timestamp": datetime.utcnow().isoformat(),
                })
                await ws.send(auth_msg)

                raw = await asyncio.wait_for(ws.recv(), timeout=15)
                reply = json.loads(raw)

                if not reply.get("success"):
                    status(f"Authentication FAILED: {reply.get('error', 'unknown')}")
                    return

                self.session_id = reply.get("session_id", "?")
                status(f"Authenticated -- session {self.session_id}")

                # Launch browser
                status("Launching browser ...")
                async with async_playwright() as pw:
                    self.browser = await pw.chromium.launch(
                        headless=self.headless,
                        args=["--disable-blink-features=AutomationControlled"],
                    )
                    self.page = await self.browser.new_page()
                    status("Browser ready. Waiting for commands from Mystes ...")

                    try:
                        await self._command_loop(ws)
                    finally:
                        status("Closing browser ...")
                        await self.browser.close()

        except asyncio.CancelledError:
            status("Session cancelled.")
        except ConnectionRefusedError:
            status(f"Could not connect to {self.server_url} -- is the server running?")
        except Exception as exc:
            logger.exception("Unexpected error")
            status(f"Error: {exc}")
        finally:
            self._running = False
            self._print_summary()

    async def _command_loop(self, ws) -> None:
        """Receive and dispatch messages from the server."""
        while self._running:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=30)
            except asyncio.TimeoutError:
                await ws.send(json.dumps({
                    "type": "ping",
                    "timestamp": datetime.utcnow().isoformat(),
                }))
                continue

            msg = json.loads(raw)
            msg_type = msg.get("type")

            if msg_type == "command":
                response = await self._handle_command(msg)
                await ws.send(json.dumps(response))

            elif msg_type == "pong":
                logger.debug("Heartbeat OK")

            elif msg_type == "status":
                s = msg.get("status", "")
                status(f"Session status: {s}")
                if s in ("completed", "cancelled", "failed"):
                    status(f"Session ended ({s}).")
                    self._running = False

            elif msg_type == "error":
                status(f"Server error: {msg.get('error', 'unknown')}")
                if msg.get("fatal"):
                    status("Fatal error -- disconnecting.")
                    self._running = False

            else:
                logger.debug("Unknown message type: %s", msg_type)

    async def _handle_command(self, msg: dict) -> dict:
        """Execute a single browser command and return a response dict."""
        command_id = msg.get("command_id", "")
        command = msg.get("command", "")
        params = msg.get("params", {})
        timeout_s = msg.get("timeout_ms", COMMAND_TIMEOUT_DEFAULT * 1000) / 1000.0

        logger.debug("CMD %s  %s  params=%s", command_id, command, params)
        status(f"Executing: {command}")

        start = time.monotonic()
        try:
            data = await asyncio.wait_for(
                self._dispatch(command, params),
                timeout=timeout_s,
            )
            elapsed_ms = int((time.monotonic() - start) * 1000)
            self._commands_executed += 1
            status(f"  -> OK ({elapsed_ms} ms)")
            return self._response(command_id, True, data=data, elapsed=elapsed_ms)

        except asyncio.TimeoutError:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            self._commands_failed += 1
            status("  -> TIMEOUT")
            return self._response(command_id, False, error=f"Command timed out after {timeout_s:.0f}s", elapsed=elapsed_ms)

        except Exception as exc:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            self._commands_failed += 1
            status(f"  -> FAILED: {exc}")
            return self._response(command_id, False, error=str(exc), elapsed=elapsed_ms)

    async def _dispatch(self, command: str, params: Dict[str, Any]) -> dict:
        """Route a command string to the appropriate Playwright action."""

        if command == "navigate":
            url = params["url"]
            if not is_domain_allowed(url):
                raise PermissionError(f"Domain not in allowlist: {urlparse(url).hostname}")
            status(f"  Navigating to {url}")
            await self.page.goto(url, wait_until="domcontentloaded")
            return {"url": self.page.url}

        if command == "click":
            await self.page.click(params["selector"])
            return {"clicked": True}

        if command == "type_text":
            await self.page.fill(params["selector"], params["text"])
            return {"typed": True}

        if command == "extract_text":
            selector = params.get("selector", "body")
            el = await self.page.query_selector(selector)
            if el:
                text = await el.inner_text()
                return {"text": text[:5000]}
            return {"text": None, "not_found": True}

        if command == "extract_all":
            selector = params.get("selector", "body")
            elements = await self.page.query_selector_all(selector)
            texts = []
            for el in elements[:50]:
                texts.append((await el.inner_text())[:1000])
            return {"texts": texts, "count": len(texts)}

        if command == "screenshot":
            raw_bytes = await self.page.screenshot(
                full_page=params.get("full_page", False),
            )
            return {
                "screenshot": base64.b64encode(raw_bytes).decode(),
                "format": "png",
            }

        if command == "wait_for":
            selector = params.get("selector", "body")
            timeout_ms = params.get("timeout_ms", 10000)
            await self.page.wait_for_selector(selector, timeout=timeout_ms)
            return {"found": True}

        if command == "wait_timeout":
            ms = params.get("ms", 1000)
            await asyncio.sleep(ms / 1000.0)
            return {"waited": True}

        if command == "scroll":
            direction = params.get("direction", "down")
            amount = params.get("amount", 500)
            delta = amount if direction == "down" else -amount
            await self.page.evaluate(f"window.scrollBy(0, {delta})")
            return {"scrolled": True}

        if command == "select":
            await self.page.select_option(params["selector"], params["value"])
            return {"selected": True}

        if command == "execute_js":
            result = await self.page.evaluate(params["script"])
            return {"result": result}

        if command == "extract_html":
            selector = params.get("selector", "body")
            el = await self.page.query_selector(selector)
            if el:
                html = await el.inner_html()
                return {"html": html[:10000]}
            return {"html": None, "not_found": True}

        if command == "check_exists":
            el = await self.page.query_selector(params["selector"])
            return {"exists": el is not None}

        if command == "check_element":
            el = await self.page.query_selector(params["selector"])
            if el:
                visible = await el.is_visible()
                enabled = await el.is_enabled()
                return {"exists": True, "visible": visible, "enabled": enabled}
            return {"exists": False, "visible": False, "enabled": False}

        if command == "fill_form":
            fields = params.get("fields", {})
            filled = 0
            for selector, value in fields.items():
                await self.page.fill(selector, value)
                filled += 1
            return {"filled": filled}

        if command == "get_url":
            return {"url": self.page.url}

        if command == "get_attribute":
            el = await self.page.query_selector(params["selector"])
            if el:
                attr = await el.get_attribute(params.get("attribute", "href"))
                return {"value": attr}
            return {"value": None, "not_found": True}

        if command == "ping":
            return {"pong": True}

        if command == "close":
            self._running = False
            return {"closed": True}

        raise ValueError(f"Unknown command: {command}")

    @staticmethod
    def _response(
        command_id: str,
        success: bool,
        data: Optional[dict] = None,
        error: Optional[str] = None,
        elapsed: int = 0,
    ) -> dict:
        return {
            "type": "response",
            "command_id": command_id,
            "success": success,
            "data": data or {},
            "error": error,
            "execution_time_ms": elapsed,
            "timestamp": datetime.utcnow().isoformat(),
        }

    def _print_summary(self) -> None:
        print()
        print("=" * 48)
        print("  Session Summary")
        print(f"    Session ID : {self.session_id or 'N/A'}")
        print(f"    Commands OK: {self._commands_executed}")
        print(f"    Failed     : {self._commands_failed}")
        print("=" * 48)

    def stop(self) -> None:
        """Signal graceful shutdown."""
        self._running = False


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mystes Helper Client -- run on your machine to participate in P2P flight bookings.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Example:\n  python helper_client.py --token abc123 --server ws://mystes.example.com:8765",
    )
    parser.add_argument(
        "--server", default=DEFAULT_SERVER,
        help=f"Mystes WebSocket server URL (default: {DEFAULT_SERVER})",
    )
    parser.add_argument(
        "--token", required=True,
        help="Session authentication token provided by Mystes",
    )
    parser.add_argument(
        "--headless", action="store_true", default=False,
        help="Run the browser in headless mode (default: visible so you can watch)",
    )
    parser.add_argument(
        "--verbose", action="store_true", default=False,
        help="Enable debug-level logging",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    print(BANNER.format(version=CLIENT_VERSION))
    print(f"  Server  : {args.server}")
    print(f"  Token   : {args.token[:12]}{'*' * max(0, len(args.token) - 12)}")
    print(f"  Headless: {'yes' if args.headless else 'no (you will see the browser)'}")
    print()

    if not check_dependencies():
        sys.exit(1)

    if not ensure_playwright_browsers():
        sys.exit(1)

    print()

    client = MystesHelperClient(
        server_url=args.server,
        auth_token=args.token,
        headless=args.headless,
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _shutdown_handler():
        status("Ctrl+C received -- shutting down gracefully ...")
        client.stop()

    try:
        loop.add_signal_handler(signal.SIGINT, _shutdown_handler)
        loop.add_signal_handler(signal.SIGTERM, _shutdown_handler)
    except NotImplementedError:
        pass

    try:
        loop.run_until_complete(client.run())
    except KeyboardInterrupt:
        _shutdown_handler()
    finally:
        loop.close()

    print("\nMystes Helper Client stopped. Goodbye.")


if __name__ == "__main__":
    main()
