"""
Picasso/Redbox Session Token Manager

Automatic authentication and token refresh for the Redbox flight search API.

Auth strategies (tried in order):
  A) Playwright headless browser + TOTP code  — fast, no email (primary)
  B) Playwright headless browser + email OTP via IMAP  — fallback
  Fallback) Manual PICASSO_SESSION_TOKEN from .env

Token is cached in memory and persisted to .picasso_token.json.
Thread-safe for multi-threaded web servers (e.g., gunicorn gthread).

Usage:
    from clients.redbox_auth import TokenManager

    manager = TokenManager()
    token = manager.get_token()

    # Or use with RedboxClient:
    from picasso import RedboxClient
    client = RedboxClient(
        agency_id="YOUR_AGENCY",
        branch="YOUR_BRANCH",
        token_provider=manager.get_token,
    )

Required .env:
    PICASSO_USERNAME=your_cockpit_email@gmail.com
    PICASSO_PASSWORD=your_cockpit_password
    PICASSO_TOTP_SECRET=your_32_char_base32_secret

Optional (email OTP fallback):
    PICASSO_GMAIL_IMAP_USER=your_primary_gmail@gmail.com
    PICASSO_GMAIL_APP_PASSWORD=your_16_char_app_password
"""

import json
import logging
import os
import re
import threading
import time
from typing import Optional, Dict

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("picasso.auth")

# --- Constants ---
KEYCLOAK_BASE = "https://account.picassotravel.com/realms/picasso-com"
KEYCLOAK_TOKEN_URL = f"{KEYCLOAK_BASE}/protocol/openid-connect/token"
DEFAULT_REDBOX_URL = "https://aerpackit.flightconex.de/redbox"
DEFAULT_COCKPIT_URL = "https://cockpit.thegoodconsolidator.com"

# admin-cli supports ROPC and now requires TOTP after setup
KEYCLOAK_ROPC_CLIENT_ID = "admin-cli"

# Refresh 10 minutes before estimated expiry
REFRESH_BUFFER_SECONDS = 600

# Default token lifetime: 24 hours
MAX_TOKEN_AGE_SECONDS = 86400


class TokenManager:
    """
    Thread-safe session token manager for Picasso/Redbox API.

    Handles automatic login, caching, persistence, and retry.
    Uses a double-check locking pattern for thread safety.

    Args:
        username: Cockpit login email. Defaults to PICASSO_USERNAME env var.
        password: Cockpit login password. Defaults to PICASSO_PASSWORD env var.
        totp_secret: Base32 TOTP secret for 2FA. Defaults to PICASSO_TOTP_SECRET env var.
        manual_token: Static fallback token. Defaults to PICASSO_SESSION_TOKEN env var.
        token_file: Path to persist token JSON. Defaults to .picasso_token.json
            in the current directory.
        redbox_url: Redbox API base URL.
        cockpit_url: Cockpit portal URL.
        gmail_imap_user: Gmail address for email OTP fallback.
        gmail_app_password: Gmail app password for IMAP access.
    """

    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        totp_secret: Optional[str] = None,
        manual_token: Optional[str] = None,
        token_file: Optional[str] = None,
        redbox_url: Optional[str] = None,
        cockpit_url: Optional[str] = None,
        gmail_imap_user: Optional[str] = None,
        gmail_app_password: Optional[str] = None,
    ):
        self._lock = threading.Lock()
        self._token: Optional[str] = None
        self._token_obtained_at: Optional[float] = None
        self._token_expires_at: Optional[float] = None
        self._working_strategy: Optional[str] = None
        self._consecutive_failures: int = 0

        # Credentials
        self._username = username or os.environ.get("PICASSO_USERNAME", "")
        self._password = password or os.environ.get("PICASSO_PASSWORD", "")
        self._totp_secret = totp_secret or os.environ.get("PICASSO_TOTP_SECRET", "")
        self._gmail_app_password = gmail_app_password or os.environ.get("PICASSO_GMAIL_APP_PASSWORD", "")
        self._gmail_imap_user = gmail_imap_user or os.environ.get("PICASSO_GMAIL_IMAP_USER", self._username)

        # Fallback manual token
        self._manual_token = manual_token or os.environ.get("PICASSO_SESSION_TOKEN", "")

        # URLs
        self._redbox_url = redbox_url or os.environ.get("PICASSO_REDBOX_URL", DEFAULT_REDBOX_URL)
        self._cockpit_url = cockpit_url or os.environ.get("PICASSO_COCKPIT_URL", DEFAULT_COCKPIT_URL)

        # Token persistence
        self._token_file = token_file or os.path.join(os.getcwd(), ".picasso_token.json")

        # Load persisted token on init
        self._load_persisted_token()

    # ----------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------

    def get_token(self) -> str:
        """
        Return a valid Redbox session token.

        Fast path: cached token still valid (no lock).
        Slow path: acquire lock, refresh via strategy chain.
        Fallback: manual PICASSO_SESSION_TOKEN.
        """
        # Fast path — cached token not near expiry
        if self._token and self._token_expires_at:
            if time.time() < self._token_expires_at - REFRESH_BUFFER_SECONDS:
                return self._token

        # Slow path — need to refresh
        with self._lock:
            # Double-check after acquiring lock
            if self._token and self._token_expires_at:
                if time.time() < self._token_expires_at - REFRESH_BUFFER_SECONDS:
                    return self._token

            # Auto-refresh if credentials are configured
            if self._username and self._password:
                new_token = self._refresh_token()
                if new_token:
                    self._consecutive_failures = 0
                    return new_token

                self._consecutive_failures += 1
                logger.warning(
                    f"Auto-login failed (attempt #{self._consecutive_failures}). "
                    f"Falling back to manual token."
                )

            # Fallback — manual token
            if self._manual_token:
                self._token = self._manual_token
                self._token_obtained_at = time.time()
                self._token_expires_at = time.time() + MAX_TOKEN_AGE_SECONDS
                return self._token

            logger.error(
                "No token available. "
                "Set PICASSO_USERNAME+PICASSO_PASSWORD or PICASSO_SESSION_TOKEN in .env"
            )
            return ""

    def invalidate(self):
        """Mark current token as expired (e.g., on 401/403 from Redbox)."""
        with self._lock:
            self._token_expires_at = 0
            logger.info("Token invalidated — will refresh on next request")

    def check_token_health(self) -> Dict:
        """
        Test the current token against the Redbox API.

        Returns:
            Dict with 'healthy' (bool) and 'detail' (str).
        """
        token = self._token or self._manual_token
        if not token:
            return {"healthy": False, "detail": "No token available"}

        try:
            response = requests.post(
                f"{self._redbox_url}/api/{token}/availableFare",
                json={
                    "segmentList": [{
                        "departure": "JFK",
                        "destination": "LHR",
                        "departureDate": "2026-12-01",
                    }],
                    "passengerTypeCountList": [{"type": "ADT", "count": 1}],
                    "cabinClassList": ["ECONOMY"],
                    "fareCharacteristicList": ["PUB"],
                    "nonStopFlightsOnly": False,
                },
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                timeout=20,
            )
            if response.status_code == 200:
                data = response.json()
                n = data.get("numberOfResults", 0)
                return {"healthy": True, "detail": f"Token valid \u2014 {n} fares returned"}
            else:
                return {
                    "healthy": False,
                    "detail": f"HTTP {response.status_code}: {response.text[:100]}",
                }
        except Exception as e:
            return {"healthy": False, "detail": f"Connection error: {e}"}

    def is_auto_configured(self) -> bool:
        """Check if auto-login credentials are set."""
        return bool(self._username and self._password)

    def get_status(self) -> dict:
        """Return diagnostic info for health checks."""
        return {
            "auto_configured": self.is_auto_configured(),
            "totp_configured": bool(self._totp_secret),
            "email_otp_configured": bool(self._gmail_app_password),
            "has_token": bool(self._token),
            "token_age_seconds": (
                int(time.time() - self._token_obtained_at)
                if self._token_obtained_at
                else None
            ),
            "working_strategy": self._working_strategy,
            "consecutive_failures": self._consecutive_failures,
            "manual_token_set": bool(self._manual_token),
        }

    # ----------------------------------------------------------------
    # Keycloak helpers
    # ----------------------------------------------------------------

    def keycloak_get_jwt(self) -> Optional[str]:
        """
        Get a Keycloak JWT via admin-cli ROPC + TOTP.

        Useful for Account API operations. Returns None if TOTP is not configured.
        """
        if not self._totp_secret:
            return None

        try:
            import pyotp

            totp = pyotp.TOTP(self._totp_secret)
            code = totp.now()

            response = requests.post(
                KEYCLOAK_TOKEN_URL,
                data={
                    "grant_type": "password",
                    "client_id": KEYCLOAK_ROPC_CLIENT_ID,
                    "username": self._username,
                    "password": self._password,
                    "totp": code,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=15,
            )
            if response.status_code == 200:
                data = response.json()
                if "access_token" in data:
                    return data["access_token"]
            logger.debug(f"Keycloak ROPC: HTTP {response.status_code}")
        except ImportError:
            logger.warning("pyotp not installed \u2014 pip install picasso-redbox-sdk[auth]")
        except requests.RequestException as e:
            logger.debug(f"Keycloak ROPC error: {e}")
        return None

    # ----------------------------------------------------------------
    # Refresh orchestration
    # ----------------------------------------------------------------

    def _refresh_token(self) -> Optional[str]:
        """Try each strategy in order. Returns token or None."""
        strategies = [
            ("playwright_totp", self._strategy_playwright_totp),
            ("playwright_email_otp", self._strategy_playwright_email_otp),
        ]

        # If a strategy worked before, try it first
        if self._working_strategy:
            strategies.sort(key=lambda s: 0 if s[0] == self._working_strategy else 1)

        for name, strategy_fn in strategies:
            try:
                logger.info(f"Trying strategy: {name}")
                token = strategy_fn()
                if token and len(token) >= 20:
                    self._token = token
                    self._token_obtained_at = time.time()
                    self._token_expires_at = time.time() + MAX_TOKEN_AGE_SECONDS
                    self._working_strategy = name
                    self._persist_token()
                    logger.info(f"Strategy {name} succeeded (token len={len(token)})")
                    return token
            except Exception as e:
                logger.warning(f"Strategy {name} failed: {e}")

        return None

    # ----------------------------------------------------------------
    # Strategy A: Playwright + TOTP (primary)
    # ----------------------------------------------------------------

    def _strategy_playwright_totp(self) -> Optional[str]:
        """Headless Chromium login with password + TOTP code."""
        if not self._totp_secret:
            logger.info("Skipping TOTP strategy \u2014 PICASSO_TOTP_SECRET not set")
            return None

        try:
            import pyotp
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            logger.warning(f"Missing dependency for TOTP auth: {e}")
            logger.info("Install with: pip install picasso-redbox-sdk[auth]")
            return None

        logger.info("Browser login with TOTP...")

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            try:
                context = browser.new_context(
                    viewport={"width": 1920, "height": 1080},
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                )
                page = context.new_page()

                # Step 1: Navigate to Cockpit -> Keycloak login
                page.goto(self._cockpit_url, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(2000)

                # Step 2: Fill username + password
                self._browser_fill_field(
                    page, self._username,
                    ['input[name="username"]', "#username", 'input[type="email"]'],
                )
                self._browser_fill_field(
                    page, self._password,
                    ['input[name="password"]', "#password", 'input[type="password"]'],
                )

                # Step 3: Submit
                self._browser_click_submit(page)
                page.wait_for_load_state("networkidle", timeout=30000)
                page.wait_for_timeout(3000)

                # Step 4: Enter TOTP code
                body = page.inner_text("body")[:500].lower()
                if "one-time code" in body or "authenticator" in body:
                    totp = pyotp.TOTP(self._totp_secret)
                    code = totp.now()
                    logger.info("Entering TOTP code")

                    self._browser_fill_field(
                        page, code,
                        ['input[name="otp"]', 'input[name="totp"]', 'input[type="text"]'],
                    )
                    self._browser_click_submit(page)
                    page.wait_for_load_state("networkidle", timeout=30000)
                    page.wait_for_timeout(5000)

                # Step 5: Should be on Cockpit — get Redbox token
                if "account.picassotravel.com" in page.url:
                    logger.warning(f"Still on Keycloak after TOTP: {page.inner_text('body')[:100]}")
                    return None

                logger.info(f"Logged into Cockpit: {page.url[:80]}")
                return self._get_redbox_token(context, page)

            finally:
                browser.close()

    # ----------------------------------------------------------------
    # Strategy B: Playwright + email OTP (fallback)
    # ----------------------------------------------------------------

    def _strategy_playwright_email_otp(self) -> Optional[str]:
        """Headless Chromium login using email OTP via IMAP."""
        if not self._gmail_app_password:
            logger.info("Skipping email OTP strategy \u2014 PICASSO_GMAIL_APP_PASSWORD not set")
            return None

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return None

        logger.info("Browser login with email OTP...")

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            try:
                context = browser.new_context(
                    viewport={"width": 1920, "height": 1080},
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                )
                page = context.new_page()

                page.goto(self._cockpit_url, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(2000)

                # Snapshot mailbox before login
                baseline_uid = self._get_uidnext()

                # Fill credentials and submit
                self._browser_fill_field(
                    page, self._username,
                    ['input[name="username"]', "#username", 'input[type="email"]'],
                )
                self._browser_fill_field(
                    page, self._password,
                    ['input[name="password"]', "#password", 'input[type="password"]'],
                )
                self._browser_click_submit(page)
                page.wait_for_load_state("networkidle", timeout=30000)
                page.wait_for_timeout(3000)

                # Handle email OTP
                body = page.inner_text("body")[:500].lower()
                if "one-time code" in body:
                    logger.info("Email OTP challenge detected")
                    otp = self._read_email_otp(after_uid=baseline_uid)
                    if not otp:
                        return None

                    self._browser_fill_field(
                        page, otp,
                        ['input[name="otp"]', 'input[name="code"]', 'input[type="text"]'],
                    )
                    self._browser_click_submit(page)
                    page.wait_for_load_state("networkidle", timeout=30000)
                    page.wait_for_timeout(5000)

                if "account.picassotravel.com" in page.url:
                    return None

                return self._get_redbox_token(context, page)

            finally:
                browser.close()

    # ----------------------------------------------------------------
    # Redbox token extraction
    # ----------------------------------------------------------------

    def _get_redbox_token(self, context, page) -> Optional[str]:
        """Extract redbox-session-token from cookies or URL after login."""
        token = self._extract_cookie_token(context)
        if token:
            return token

        # Navigate to Redbox to trigger SSO and get the cookie
        logger.info("Navigating to Redbox for session cookie...")
        page.goto(self._redbox_url, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(3000)

        token = self._extract_cookie_token(context)
        if token:
            return token

        # Check URL path for token
        match = re.search(r'/api/([a-zA-Z0-9]{20,})/', page.url)
        if match:
            token = match.group(1)
            logger.info(f"Token from URL (len={len(token)})")
            return token

        cookies = context.cookies()
        cookie_info = [f"{c['name']}@{c['domain']}" for c in cookies]
        logger.warning(f"Logged in but no redbox-session-token. Cookies: {cookie_info}")
        return None

    def _extract_cookie_token(self, context) -> Optional[str]:
        """Extract redbox-session-token from browser cookies."""
        for cookie in context.cookies():
            if cookie["name"] == "redbox-session-token":
                token = cookie["value"]
                logger.info(f"Got session token (len={len(token)}) from {cookie.get('domain', '?')}")
                return token
        return None

    # ----------------------------------------------------------------
    # Browser helpers
    # ----------------------------------------------------------------

    @staticmethod
    def _browser_fill_field(page, value, selectors) -> bool:
        """Fill a form field using multiple selector fallbacks."""
        for sel in selectors:
            try:
                el = page.locator(sel)
                if el.count() > 0 and el.first.is_visible():
                    el.first.fill(value)
                    return True
            except Exception:
                pass
        return False

    @staticmethod
    def _browser_click_submit(page) -> bool:
        """Click a submit button."""
        for sel in ['button[type="submit"]', "#kc-login", 'input[type="submit"]']:
            try:
                btn = page.locator(sel)
                if btn.count() > 0 and btn.first.is_visible():
                    btn.first.click()
                    return True
            except Exception:
                pass
        return False

    # ----------------------------------------------------------------
    # Email OTP helpers (Gmail IMAP — fallback)
    # ----------------------------------------------------------------

    def _imap_connect(self):
        """Create and return an authenticated IMAP connection."""
        import imaplib
        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        mail.login(self._gmail_imap_user, self._gmail_app_password)
        return mail

    def _get_uidnext(self) -> int:
        """Get UIDNEXT from inbox — the UID the next email will receive."""
        try:
            mail = self._imap_connect()
            _, data = mail.status("INBOX", "(UIDNEXT)")
            match = re.search(r"UIDNEXT (\d+)", data[0].decode())
            mail.logout()
            if match:
                return int(match.group(1))
        except Exception as e:
            logger.debug(f"Could not get UIDNEXT: {e}")
        return 0

    def _read_email_otp(
        self, after_uid: int = 0, max_wait_seconds: int = 60
    ) -> Optional[str]:
        """Read Keycloak OTP from Gmail via IMAP. Only checks UIDs >= after_uid."""
        import imaplib
        import email as email_lib

        if not after_uid:
            return None

        logger.info(f"Waiting for OTP email (UID >= {after_uid})...")

        start = time.time()
        while time.time() - start < max_wait_seconds:
            try:
                mail = self._imap_connect()
                mail.select("INBOX")
                _, data = mail.uid("search", None, f"UID {after_uid}:*")
                uids = [u for u in data[0].split() if int(u) >= after_uid]

                for uid in uids:
                    _, msg_data = mail.uid("fetch", uid, "(RFC822)")
                    msg = email_lib.message_from_bytes(msg_data[0][1])
                    sender = msg.get("From", "").lower()

                    if "no-reply" not in sender and "picasso" not in sender:
                        continue

                    body = self._extract_email_body(msg)
                    match = re.search(r'\b(\d{6})\b', body)
                    if match:
                        code = match.group(1)
                        logger.info(f"Got OTP: {code}")
                        mail.uid("store", uid, "+FLAGS", "\\Seen")
                        mail.logout()
                        return code

                mail.logout()
                time.sleep(3)

            except imaplib.IMAP4.error as e:
                logger.warning(f"IMAP error: {e}")
                return None
            except Exception as e:
                logger.warning(f"Email error: {e}")
                time.sleep(3)

        return None

    @staticmethod
    def _extract_email_body(msg) -> str:
        """Extract text body from an email message."""
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() in ("text/plain", "text/html"):
                    payload = part.get_payload(decode=True)
                    if payload:
                        body += payload.decode("utf-8", errors="ignore")
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                body = payload.decode("utf-8", errors="ignore")
        return body

    # ----------------------------------------------------------------
    # Token persistence
    # ----------------------------------------------------------------

    def _persist_token(self):
        """Save current token to .picasso_token.json."""
        try:
            data = {
                "token": self._token,
                "obtained_at": self._token_obtained_at,
                "expires_at": self._token_expires_at,
                "strategy": self._working_strategy,
            }
            with open(self._token_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to persist token: {e}")

    def _load_persisted_token(self):
        """Load token from .picasso_token.json if still valid."""
        try:
            if not os.path.exists(self._token_file):
                return

            with open(self._token_file, "r") as f:
                data = json.load(f)

            token = data.get("token", "")
            expires_at = data.get("expires_at", 0)
            obtained_at = data.get("obtained_at", 0)

            if token and expires_at > time.time() + REFRESH_BUFFER_SECONDS:
                self._token = token
                self._token_obtained_at = obtained_at
                self._token_expires_at = expires_at
                self._working_strategy = data.get("strategy")

                age_mins = int((time.time() - obtained_at) / 60)
                logger.info(f"Loaded persisted token (age: {age_mins}m, strategy: {self._working_strategy})")
            else:
                logger.debug("Persisted token expired, will refresh")
        except Exception as e:
            logger.debug(f"Could not load persisted token: {e}")
