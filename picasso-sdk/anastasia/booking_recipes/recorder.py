"""Network Recorder — Captures airline API calls during a manual booking flow.

Used by developers to record a booking flow once per airline. The captured
network traffic is then analyzed by the AI Recipe Generator to produce
a compiled Booking Recipe card.

Usage:
    recorder = NetworkRecorder()
    capture = recorder.record(cdp_url, airline_url, duration_seconds=300)
    capture.save("captures/lufthansa_2026-04-21.json")
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# URL patterns that indicate an API call (as opposed to an asset)
API_URL_PATTERNS = [
    r"/api/",
    r"/rest/",
    r"/graphql",
]

# URL patterns that are specifically booking-related
BOOKING_URL_PATTERNS = [
    r"/booking",
    r"/order",
    r"/passenger",
    r"/payment",
    r"/confirm",
    r"/offer",
    r"/fare",
    r"/flight",
    r"/search",
    r"/cart",
    r"/checkout",
    r"/reserve",
    r"/select",
    r"/ancillar",
    r"/seat",
    r"/baggage",
    r"/service",
]

# Content types that indicate API calls (not assets)
API_CONTENT_TYPES = [
    "application/json",
    "application/graphql",
    "application/x-www-form-urlencoded",
    "text/json",
]

# Ignore these resource types
IGNORE_RESOURCE_TYPES = {"image", "stylesheet", "font", "media", "manifest"}


@dataclass
class CapturedRequest:
    """A single captured network request."""

    timestamp: float
    method: str
    url: str
    headers: Dict[str, str]
    body: Optional[str]  # POST body (JSON string or form data)
    resource_type: str

    # Response data
    status_code: Optional[int] = None
    response_headers: Dict[str, str] = field(default_factory=dict)
    response_body: Optional[str] = None

    # Classification
    is_api_call: bool = False
    is_booking_related: bool = False
    category: str = "unknown"  # search, select, passenger, payment, confirm, other

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "method": self.method,
            "url": self.url,
            "headers": self.headers,
            "body": self.body,
            "resource_type": self.resource_type,
            "status_code": self.status_code,
            "response_headers": self.response_headers,
            "response_body": self.response_body,
            "is_api_call": self.is_api_call,
            "is_booking_related": self.is_booking_related,
            "category": self.category,
        }


@dataclass
class NetworkCapture:
    """Complete capture of a booking flow's network traffic."""

    airline: str
    base_url: str
    captured_at: str  # ISO timestamp
    duration_seconds: float
    requests: List[CapturedRequest] = field(default_factory=list)
    cookies: List[Dict[str, Any]] = field(default_factory=list)
    local_storage: Dict[str, str] = field(default_factory=dict)

    @property
    def api_requests(self) -> List[CapturedRequest]:
        """Filter to API calls only."""
        return [r for r in self.requests if r.is_api_call]

    @property
    def booking_requests(self) -> List[CapturedRequest]:
        """Filter to booking-related API calls."""
        return [r for r in self.requests if r.is_booking_related]

    def save(self, path: str) -> None:
        """Save capture to JSON file."""
        output = {
            "airline": self.airline,
            "base_url": self.base_url,
            "captured_at": self.captured_at,
            "duration_seconds": self.duration_seconds,
            "total_requests": len(self.requests),
            "api_requests": len(self.api_requests),
            "booking_requests": len(self.booking_requests),
            "cookies": self.cookies,
            "local_storage": self.local_storage,
            "requests": [r.to_dict() for r in self.requests],
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(output, indent=2), encoding="utf-8")
        logger.info(
            "[NetworkRecorder] Saved capture: %d total, %d API, %d booking-related → %s",
            len(self.requests),
            len(self.api_requests),
            len(self.booking_requests),
            path,
        )

    @classmethod
    def load(cls, path: str) -> "NetworkCapture":
        """Load a capture from JSON file."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        requests = []
        for r in data.get("requests", []):
            requests.append(CapturedRequest(
                timestamp=r["timestamp"],
                method=r["method"],
                url=r["url"],
                headers=r.get("headers", {}),
                body=r.get("body"),
                resource_type=r.get("resource_type", "other"),
                status_code=r.get("status_code"),
                response_headers=r.get("response_headers", {}),
                response_body=r.get("response_body"),
                is_api_call=r.get("is_api_call", False),
                is_booking_related=r.get("is_booking_related", False),
                category=r.get("category", "unknown"),
            ))
        return cls(
            airline=data.get("airline", "unknown"),
            base_url=data.get("base_url", ""),
            captured_at=data.get("captured_at", ""),
            duration_seconds=data.get("duration_seconds", 0),
            requests=requests,
            cookies=data.get("cookies", []),
            local_storage=data.get("local_storage", {}),
        )


def _classify_request(url: str, method: str, body: Optional[str]) -> str:
    """Classify a request into a booking flow category."""
    url_lower = url.lower()

    if any(p in url_lower for p in ("/search", "/offer", "/fare", "/avail")):
        return "search"
    if any(p in url_lower for p in ("/select", "/choose", "/cart/add")):
        return "select"
    if any(p in url_lower for p in ("/passenger", "/traveler", "/pax", "/contact")):
        return "passenger"
    if any(p in url_lower for p in ("/seat", "/baggage", "/ancillar", "/service", "/extra")):
        return "extras"
    if any(p in url_lower for p in ("/payment", "/pay", "/card", "/checkout")):
        return "payment"
    if any(p in url_lower for p in ("/confirm", "/complete", "/finalize", "/submit", "/book")):
        return "confirm"

    # Check body content for clues
    if body:
        body_lower = body.lower()
        if any(p in body_lower for p in ("firstname", "first_name", "givenname", "given_name")):
            return "passenger"
        if any(p in body_lower for p in ("cardnumber", "card_number", "creditcard")):
            return "payment"

    return "other"


def _is_api_call(
    url: str,
    method: str,
    content_type: str,
    resource_type: str,
) -> bool:
    """Determine if a request is an API call (not an asset load)."""
    if resource_type in IGNORE_RESOURCE_TYPES:
        return False
    if method in ("POST", "PUT", "PATCH", "DELETE"):
        return True
    if any(ct in content_type.lower() for ct in API_CONTENT_TYPES):
        return True
    all_patterns = API_URL_PATTERNS + BOOKING_URL_PATTERNS
    if any(re.search(p, url, re.IGNORECASE) for p in all_patterns):
        return True
    return False


def _is_booking_related(url: str, method: str, body: Optional[str]) -> bool:
    """Check if a request is related to the booking flow."""
    if any(re.search(p, url, re.IGNORECASE) for p in BOOKING_URL_PATTERNS):
        return True
    if method in ("POST", "PUT", "PATCH") and body:
        # Check if body contains booking-related fields
        body_lower = body.lower()
        booking_terms = [
            "passenger", "traveler", "firstname", "lastname",
            "card", "payment", "booking", "order", "offer",
            "departure", "arrival", "flight", "cabin",
        ]
        if any(term in body_lower for term in booking_terms):
            return True
    return False


class NetworkRecorder:
    """Records network traffic during a manual booking flow.

    Connects to a Bright Data Scraping Browser via CDP, navigates to
    the airline site, and captures all network requests while the
    developer manually completes a booking flow.
    """

    def record(
        self,
        cdp_url: str,
        airline_url: str,
        airline_name: str = "unknown",
        duration_seconds: int = 300,
    ) -> NetworkCapture:
        """Record network traffic during a manual booking flow.

        Args:
            cdp_url: Bright Data Scraping Browser WebSocket URL
            airline_url: Airline homepage/booking page URL
            airline_name: Airline identifier for the capture
            duration_seconds: Maximum recording duration

        Returns:
            NetworkCapture with all intercepted requests
        """
        from playwright.sync_api import sync_playwright

        captured: List[CapturedRequest] = []
        base_domain = urlparse(airline_url).netloc
        start_time = time.time()

        def on_request(request):
            """Capture outgoing requests."""
            try:
                content_type = request.headers.get("content-type", "")
                resource_type = request.resource_type

                if not _is_api_call(
                    request.url, request.method, content_type, resource_type
                ):
                    return

                body = None
                try:
                    body = request.post_data
                except Exception:
                    pass

                is_booking = _is_booking_related(request.url, request.method, body)
                category = _classify_request(request.url, request.method, body)

                captured.append(CapturedRequest(
                    timestamp=time.time() - start_time,
                    method=request.method,
                    url=request.url,
                    headers=dict(request.headers),
                    body=body,
                    resource_type=resource_type,
                    is_api_call=True,
                    is_booking_related=is_booking,
                    category=category,
                ))
            except Exception as e:
                logger.debug("[Recorder] Request capture error: %s", e)

        def on_response(response):
            """Capture response data for the most recent matching request."""
            try:
                # Find the matching request in captured list
                for req in reversed(captured):
                    if req.url == response.url and req.status_code is None:
                        req.status_code = response.status
                        req.response_headers = dict(response.headers)
                        try:
                            req.response_body = response.text()
                        except Exception:
                            pass
                        break
            except Exception as e:
                logger.debug("[Recorder] Response capture error: %s", e)

        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(cdp_url)
            page = browser.new_page()

            # Attach listeners
            page.on("request", on_request)
            page.on("response", on_response)

            # Navigate to airline
            page.goto(airline_url, wait_until="networkidle", timeout=30000)

            # Wait for the developer to complete the booking flow
            # (or until duration expires)
            logger.info(
                "[Recorder] Recording started on %s. Duration: %ds. "
                "Complete the booking flow in the browser.",
                airline_url,
                duration_seconds,
            )

            # Poll until duration expires or we detect a confirmation page
            end_time = start_time + duration_seconds
            while time.time() < end_time:
                time.sleep(1)
                # Check if we've captured a confirmation step
                confirm_requests = [
                    r for r in captured if r.category == "confirm" and r.status_code
                ]
                if confirm_requests:
                    logger.info("[Recorder] Detected confirmation — stopping early.")
                    # Give a few more seconds for final responses
                    time.sleep(3)
                    break

            # Capture cookies and localStorage
            cookies = page.context.cookies()
            local_storage = {}
            try:
                local_storage = page.evaluate("""
                    () => {
                        const items = {};
                        for (let i = 0; i < localStorage.length; i++) {
                            const key = localStorage.key(i);
                            items[key] = localStorage.getItem(key);
                        }
                        return items;
                    }
                """)
            except Exception:
                pass

            browser.close()

        from datetime import datetime, timezone

        capture = NetworkCapture(
            airline=airline_name,
            base_url=airline_url,
            captured_at=datetime.now(timezone.utc).isoformat(),
            duration_seconds=time.time() - start_time,
            requests=captured,
            cookies=cookies,
            local_storage=local_storage,
        )

        logger.info(
            "[Recorder] Capture complete: %d requests (%d API, %d booking-related)",
            len(captured),
            len(capture.api_requests),
            len(capture.booking_requests),
        )

        return capture
