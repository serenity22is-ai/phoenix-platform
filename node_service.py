"""
PHOENIX Local Node Service (Build #67)

Standalone daemon that bridges the Chrome extension to the Phoenix backend.
Runs a localhost HTTP server for the extension to POST events to,
and manages heartbeat, session lifecycle, and batch data upload.

Usage:
    python node_service.py --token YOUR_HELPER_TOKEN --server https://phoenix.example.com
    python node_service.py --token YOUR_HELPER_TOKEN --port 19750 --verbose
"""

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
import time
import uuid
from datetime import datetime, timezone
from collections import deque
from typing import Optional, Dict, Any, List

try:
    import aiohttp
    from aiohttp import web
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

logger = logging.getLogger("phoenix.node_service")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_PORT = 19750
DEFAULT_SERVER = "http://localhost:5000"
HEARTBEAT_INTERVAL = 60
BATCH_UPLOAD_INTERVAL = 30
CONFIG_REFRESH_INTERVAL = 300
MAX_BUFFER_SIZE = 2000
MAX_BATCH_SIZE = 500
RECONNECT_BASE_DELAY = 1
RECONNECT_MAX_DELAY = 60
VERSION = "1.0.0"

BANNER = r"""
 ____  _   _  ___  _____ _   _ _____  __
|  _ \| | | |/ _ \| ____| \ | |_ _\ \/ /
| |_) | |_| | | | |  _| |  \| || | \  /
|  __/|  _  | |_| | |___| |\  || | /  \
|_|   |_| |_|\___/|_____|_| \_|___/_/\_\

        Node Service v{version}
    Browser Extension Data Bridge
"""

DEFAULT_CONFIG = {
    "extraction_rules": {
        "search_engines": ["google.com", "bing.com", "yahoo.com", "duckduckgo.com"],
        "ad_selectors": ["[data-text-ad]", ".ads-ad", '[class*="sponsor"]'],
        "price_selectors": ['[itemprop="price"]', ".price", ".product-price"],
        "social_platforms": ["facebook.com", "twitter.com", "x.com", "reddit.com", "linkedin.com"],
    },
    "intervals": {
        "heartbeat_s": HEARTBEAT_INTERVAL,
        "batch_upload_s": BATCH_UPLOAD_INTERVAL,
        "config_refresh_s": CONFIG_REFRESH_INTERVAL,
    },
    "limits": {
        "max_events_per_batch": MAX_BATCH_SIZE,
        "max_buffer_size": MAX_BUFFER_SIZE,
        "max_url_length": 2000,
    },
    "version": VERSION,
}


# ---------------------------------------------------------------------------
# CORS middleware for localhost HTTP server
# ---------------------------------------------------------------------------

if HAS_AIOHTTP:
    @web.middleware
    async def cors_middleware(request, handler):
        """Allow cross-origin requests from Chrome extension."""
        if request.method == "OPTIONS":
            response = web.Response()
        else:
            try:
                response = await handler(request)
            except web.HTTPException as exc:
                response = exc
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Helper-Token"
        return response


# ---------------------------------------------------------------------------
# Main service class
# ---------------------------------------------------------------------------

class PhoenixNodeService:
    """
    Local node service daemon.

    Manages:
    - Localhost HTTP server for extension communication
    - Backend REST API client for auth, heartbeat, data upload
    - Event buffering and batch upload
    - Session lifecycle
    - Reconnection with exponential backoff
    """

    def __init__(
        self,
        server_url: str,
        helper_token: str,
        port: int = DEFAULT_PORT,
        proxy_mode: str = "direct",
        verbose: bool = False,
    ):
        self.server_url = server_url.rstrip("/")
        self.helper_token = helper_token
        self.port = port
        self.proxy_mode = proxy_mode
        self.verbose = verbose

        # State
        self.node_id: Optional[str] = None
        self.session_id: Optional[str] = None
        self._event_buffer: deque = deque(maxlen=MAX_BUFFER_SIZE)
        self._running = False
        self._authenticated = False
        self._connected = False
        self._start_time: Optional[float] = None

        # Counters
        self._events_sent = 0
        self._events_captured = 0
        self._earnings_today = 0.0
        self._upload_errors = 0

        # Config
        self._last_config: Optional[Dict] = None

        # Location (Build #78)
        self._last_known_location: Optional[Dict] = None

        # Reconnect
        self._reconnect_delay = RECONNECT_BASE_DELAY

        # HTTP client + server
        self._http_session: Optional[aiohttp.ClientSession] = None
        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        """Main entry point — authenticate, start session, run loops."""
        self._running = True
        self._start_time = time.time()
        logger.info("Starting Phoenix Node Service on port %d", self.port)
        logger.info("Backend: %s", self.server_url)

        # Create HTTP client session
        headers = {
            "X-Helper-Token": self.helper_token,
            "Content-Type": "application/json",
            "User-Agent": f"PhoenixNodeService/{VERSION}",
        }
        self._http_session = aiohttp.ClientSession(headers=headers)

        try:
            # Authenticate with backend
            authenticated = await self._authenticate()
            if not authenticated:
                logger.error("Authentication failed — retrying in background")
                asyncio.ensure_future(self._reconnect())
            else:
                # Start session
                await self._start_session()
                # Fetch initial config
                await self._fetch_config()

            # Start localhost HTTP server
            await self._setup_localhost_server()
            logger.info("Localhost HTTP server running on http://127.0.0.1:%d", self.port)

            # Launch background loops
            tasks = [
                asyncio.ensure_future(self._heartbeat_loop()),
                asyncio.ensure_future(self._batch_upload_loop()),
                asyncio.ensure_future(self._config_refresh_loop()),
            ]

            # Wait until stopped
            while self._running:
                await asyncio.sleep(1)

            # Cancel background tasks
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        except Exception as exc:
            logger.exception("Fatal error in node service: %s", exc)
        finally:
            await self._cleanup()

    async def stop(self):
        """Graceful shutdown."""
        if not self._running:
            return
        logger.info("Stopping Phoenix Node Service...")
        self._running = False

        # Flush remaining buffer
        if len(self._event_buffer) > 0:
            logger.info("Flushing %d remaining events...", len(self._event_buffer))
            await self._flush_buffer()

        # End session
        if self._connected and self.session_id:
            await self._end_session()

        self._log_summary()

    async def _cleanup(self):
        """Close HTTP connections and stop local server."""
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()

        if self._runner:
            await self._runner.cleanup()

        logger.info("Cleanup complete")

    def _log_summary(self):
        """Print final stats."""
        uptime = int(time.time() - self._start_time) if self._start_time else 0
        hours = uptime // 3600
        minutes = (uptime % 3600) // 60
        logger.info("=== Session Summary ===")
        logger.info("  Uptime: %dh %dm", hours, minutes)
        logger.info("  Events captured: %d", self._events_captured)
        logger.info("  Events sent: %d", self._events_sent)
        logger.info("  Upload errors: %d", self._upload_errors)
        logger.info("  Earnings today: $%.6f RLUSD", self._earnings_today)
        logger.info("=======================")

    # ------------------------------------------------------------------
    # Backend communication
    # ------------------------------------------------------------------

    async def _authenticate(self) -> bool:
        """POST /api/v1/node/auth — authenticate with the backend."""
        try:
            url = f"{self.server_url}/api/v1/node/auth"
            payload = {"helper_token": self.helper_token}
            async with self._http_session.post(url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    self.node_id = data.get("node_id")
                    self._authenticated = True
                    self._reconnect_delay = RECONNECT_BASE_DELAY
                    logger.info("Authenticated — node_id=%s", self.node_id)
                    return True
                else:
                    body = await resp.text()
                    logger.error("Auth failed (HTTP %d): %s", resp.status, body)
                    return False
        except aiohttp.ClientError as exc:
            logger.error("Auth request failed: %s", exc)
            return False
        except Exception as exc:
            logger.error("Unexpected auth error: %s", exc)
            return False

    async def _start_session(self):
        """POST /api/v1/node/session/start — begin a browsing session."""
        if not self._authenticated or not self.node_id:
            return
        try:
            url = f"{self.server_url}/api/v1/node/session/start"
            payload = {"node_id": self.node_id}
            async with self._http_session.post(url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    self.session_id = data.get("session_id")
                    self._connected = True
                    logger.info("Session started — session_id=%s", self.session_id)
                else:
                    body = await resp.text()
                    logger.warning("Session start failed (HTTP %d): %s", resp.status, body)
        except Exception as exc:
            logger.warning("Session start error: %s", exc)

    async def _end_session(self):
        """POST /api/v1/node/session/end — close the browsing session."""
        try:
            url = f"{self.server_url}/api/v1/node/session/end"
            payload = {
                "node_id": self.node_id,
                "session_id": self.session_id,
            }
            async with self._http_session.post(url, json=payload) as resp:
                if resp.status == 200:
                    logger.info("Session ended")
                else:
                    body = await resp.text()
                    logger.warning("Session end failed (HTTP %d): %s", resp.status, body)
        except Exception as exc:
            logger.warning("Session end error: %s", exc)
        finally:
            self.session_id = None
            self._connected = False

    async def _fetch_config(self):
        """GET /api/v1/node/config — fetch extraction configuration."""
        try:
            url = f"{self.server_url}/api/v1/node/config"
            async with self._http_session.get(url) as resp:
                if resp.status == 200:
                    self._last_config = await resp.json()
                    logger.debug("Config refreshed")
                else:
                    logger.warning("Config fetch failed (HTTP %d)", resp.status)
        except Exception as exc:
            logger.debug("Config fetch error: %s", exc)

    # ------------------------------------------------------------------
    # Background loops
    # ------------------------------------------------------------------

    async def _heartbeat_loop(self):
        """Send periodic heartbeats to the backend."""
        while self._running:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                if not self._running:
                    break
                if not self._authenticated:
                    continue

                url = f"{self.server_url}/api/v1/node/heartbeat"
                uptime_s = int(time.time() - self._start_time) if self._start_time else 0
                payload = {
                    "node_id": self.node_id,
                    "uptime_s": uptime_s,
                    "events_buffered": len(self._event_buffer),
                    "version": VERSION,
                }
                # Build #78 — attach location if available
                if self._last_known_location:
                    payload["location"] = self._last_known_location
                async with self._http_session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        self._reconnect_delay = RECONNECT_BASE_DELAY
                        logger.debug("Heartbeat OK")
                    else:
                        logger.warning("Heartbeat failed (HTTP %d)", resp.status)
                        if resp.status in (401, 403):
                            self._authenticated = False
                            self._connected = False
                            asyncio.ensure_future(self._reconnect())

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Heartbeat error: %s", exc)
                if not self._connected:
                    asyncio.ensure_future(self._reconnect())

    async def _batch_upload_loop(self):
        """Periodically drain event buffer and upload to backend."""
        while self._running:
            try:
                await asyncio.sleep(BATCH_UPLOAD_INTERVAL)
                if not self._running:
                    break
                await self._flush_buffer()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Batch upload loop error: %s", exc)

    async def _flush_buffer(self):
        """Drain up to MAX_BATCH_SIZE events and POST to backend."""
        if len(self._event_buffer) == 0:
            return
        if not self._authenticated or not self._connected:
            return

        # Drain events
        batch = []
        while self._event_buffer and len(batch) < MAX_BATCH_SIZE:
            batch.append(self._event_buffer.popleft())

        if not batch:
            return

        try:
            url = f"{self.server_url}/api/v1/node/data/ingest"
            payload = {
                "node_id": self.node_id,
                "session_id": self.session_id,
                "events": batch,
            }
            async with self._http_session.post(url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    accepted = data.get("accepted", len(batch))
                    value_usd = data.get("value_usd", 0.0)
                    self._events_sent += accepted
                    self._earnings_today += value_usd
                    logger.info(
                        "Uploaded %d events (accepted=%d, value=$%.6f)",
                        len(batch), accepted, value_usd,
                    )
                else:
                    body = await resp.text()
                    logger.warning("Upload failed (HTTP %d): %s", resp.status, body)
                    self._upload_errors += 1
                    # Put events back at front of buffer
                    for event in reversed(batch):
                        self._event_buffer.appendleft(event)
        except Exception as exc:
            logger.warning("Upload error: %s", exc)
            self._upload_errors += 1
            # Put events back
            for event in reversed(batch):
                self._event_buffer.appendleft(event)

    async def _config_refresh_loop(self):
        """Periodically refresh extraction config from backend."""
        while self._running:
            try:
                await asyncio.sleep(CONFIG_REFRESH_INTERVAL)
                if not self._running:
                    break
                await self._fetch_config()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("Config refresh error: %s", exc)

    # ------------------------------------------------------------------
    # Reconnection
    # ------------------------------------------------------------------

    async def _reconnect(self):
        """Reconnect with exponential backoff."""
        while self._running and not self._connected:
            logger.info(
                "Reconnecting in %ds...", self._reconnect_delay,
            )
            await asyncio.sleep(self._reconnect_delay)
            if not self._running:
                break

            authenticated = await self._authenticate()
            if authenticated:
                await self._start_session()
                await self._fetch_config()
                logger.info("Reconnected successfully")
                break
            else:
                self._reconnect_delay = min(
                    self._reconnect_delay * 2, RECONNECT_MAX_DELAY,
                )

    # ------------------------------------------------------------------
    # Localhost HTTP server handlers
    # ------------------------------------------------------------------

    async def _handle_status(self, request):
        """GET /status — return service status for extension popup."""
        uptime_s = int(time.time() - self._start_time) if self._start_time else 0
        data = {
            "connected": self._connected,
            "authenticated": self._authenticated,
            "node_id": self.node_id,
            "session_id": self.session_id,
            "events_buffered": len(self._event_buffer),
            "events_captured": self._events_captured,
            "events_sent": self._events_sent,
            "uptime_s": uptime_s,
            "earnings_today": round(self._earnings_today, 6),
            "version": VERSION,
        }
        return web.json_response(data)

    async def _handle_events(self, request):
        """POST /events — receive events from Chrome extension."""
        try:
            body = await request.json()
        except Exception:
            return web.json_response(
                {"error": "Invalid JSON"}, status=400,
            )

        events = body.get("events", [])
        if not isinstance(events, list):
            return web.json_response(
                {"error": "events must be a list"}, status=400,
            )

        accepted = 0
        for event in events:
            if isinstance(event, dict):
                self._event_buffer.append(event)
                accepted += 1
                self._events_captured += 1

        return web.json_response({
            "accepted": accepted,
            "buffered": len(self._event_buffer),
        })

    async def _handle_config(self, request):
        """GET /config — return extraction config for extension."""
        config = self._last_config or DEFAULT_CONFIG
        return web.json_response(config)

    async def _handle_proxy_pac(self, request):
        """GET /proxy.pac — return PAC file for proxy routing."""
        if self.proxy_mode == "pac":
            pac_script = """
function FindProxyForURL(url, host) {
    // Route through Phoenix proxy for data collection
    if (shExpMatch(host, "*.google.com") ||
        shExpMatch(host, "*.bing.com") ||
        shExpMatch(host, "*.amazon.com") ||
        shExpMatch(host, "*.booking.com") ||
        shExpMatch(host, "*.expedia.com")) {
        return "PROXY 127.0.0.1:%d";
    }
    return "DIRECT";
}
""" % self.port
        else:
            pac_script = """
function FindProxyForURL(url, host) {
    return "DIRECT";
}
"""
        return web.Response(
            text=pac_script.strip(),
            content_type="application/x-ns-proxy-autoconfig",
        )

    async def _handle_location(self, request):
        """POST /location — from Chrome extension (consent-gated, Build #78)."""
        try:
            body = await request.json()
            lat = body.get("lat")
            lon = body.get("lon")
            if lat is None or lon is None:
                return web.json_response({"error": "lat and lon required"}, status=400)
            self._last_known_location = {
                "lat": float(lat),
                "lon": float(lon),
                "accuracy_m": body.get("accuracy_m"),
                "source": body.get("source", "gps"),
            }
            logger.debug("Location updated: %.4f, %.4f (%s)",
                         lat, lon, self._last_known_location["source"])
            return web.json_response({"status": "ok"})
        except Exception as exc:
            logger.warning("Location update error: %s", exc)
            return web.json_response({"error": str(exc)}, status=400)

    async def _handle_stop(self, request):
        """POST /stop — trigger graceful shutdown."""
        logger.info("Stop requested via localhost API")
        self._running = False
        return web.json_response({"status": "stopping"})

    # ------------------------------------------------------------------
    # Localhost server setup
    # ------------------------------------------------------------------

    async def _setup_localhost_server(self):
        """Create and start the localhost aiohttp server."""
        self._app = web.Application(middlewares=[cors_middleware])
        self._app.router.add_get("/status", self._handle_status)
        self._app.router.add_post("/events", self._handle_events)
        self._app.router.add_get("/config", self._handle_config)
        self._app.router.add_get("/proxy.pac", self._handle_proxy_pac)
        self._app.router.add_post("/location", self._handle_location)
        self._app.router.add_post("/stop", self._handle_stop)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", self.port)
        await site.start()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _run_installer(args):
    """Delegate to install-node-service.sh / .ps1 with the provided args."""
    import subprocess
    import platform as _platform

    script_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts")

    system = _platform.system()
    if system == "Windows":
        script = os.path.join(script_dir, "install-node-service.ps1")
        cmd_args = ["powershell", "-ExecutionPolicy", "Bypass", "-File", script]
    else:
        script = os.path.join(script_dir, "install-node-service.sh")
        cmd_args = ["bash", script]

    if args.install:
        if not args.token:
            print("ERROR: --token is required for --install")
            sys.exit(1)
        cmd_args.extend(["--token", args.token, "--server", args.server])
    elif args.uninstall:
        cmd_args.append("--uninstall")
    elif args.status:
        cmd_args.append("--status")

    if not os.path.exists(script):
        print(f"ERROR: Installer script not found at {script}")
        sys.exit(1)

    result = subprocess.run(cmd_args)
    sys.exit(result.returncode)


def main():
    """Parse arguments and start the node service."""
    if not HAS_AIOHTTP:
        print("ERROR: aiohttp is required. Install with: pip install aiohttp")
        sys.exit(1)

    parser = argparse.ArgumentParser(
        description="Phoenix Node Service — local daemon for browser extension",
    )
    parser.add_argument(
        "--token",
        help="Helper token for authentication",
    )
    parser.add_argument(
        "--server", default=DEFAULT_SERVER,
        help=f"Phoenix backend URL (default: {DEFAULT_SERVER})",
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT,
        help=f"Local HTTP port (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--proxy-mode", choices=["direct", "pac", "system"],
        default="direct",
        help="Proxy routing mode (default: direct)",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Enable debug logging",
    )
    # Service management flags (Build #91)
    parser.add_argument(
        "--install", action="store_true",
        help="Install as a system service (LaunchAgent/systemd/Task Scheduler)",
    )
    parser.add_argument(
        "--uninstall", action="store_true",
        help="Remove the system service",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Check system service status",
    )
    args = parser.parse_args()

    # Handle service management commands (Build #91)
    if args.install or args.uninstall or args.status:
        _run_installer(args)
        return

    # Normal daemon mode requires --token
    if not args.token:
        parser.error("--token is required (or use --install/--uninstall/--status)")

    # Setup logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    print(BANNER.format(version=VERSION))

    service = PhoenixNodeService(
        server_url=args.server,
        helper_token=args.token,
        port=args.port,
        proxy_mode=args.proxy_mode,
        verbose=args.verbose,
    )

    # Signal handlers
    loop = asyncio.new_event_loop()

    def signal_handler():
        logger.info("Shutdown signal received")
        asyncio.ensure_future(service.stop(), loop=loop)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    try:
        loop.run_until_complete(service.start())
    except KeyboardInterrupt:
        loop.run_until_complete(service.stop())
    finally:
        loop.close()
        logger.info("Node service exited")


if __name__ == "__main__":
    main()
