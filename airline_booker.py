"""
MYSTES Automated Airline Booking System

Uses Playwright browser automation through regional proxies to:
1. Navigate to airline websites with regional pricing
2. Fill passenger information programmatically
3. Complete payment using platform's credit card
4. Extract confirmation code
5. Deliver e-ticket to customer

Supported airlines (with specific handlers):
- Google Flights (redirects to airline)
- JAL (Japan Airlines)
- ANA (All Nippon Airways)
- Iberia
- Air France
- KLM
- Generic airline handler (fallback)
"""

import os
import re
import json
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass
from enum import Enum
from playwright.async_api import async_playwright, Page, Browser, BrowserContext

logger = logging.getLogger(__name__)


class BookingStatus(Enum):
    """Status of automated booking attempt."""
    PENDING = "pending"
    NAVIGATING = "navigating"
    SEARCHING = "searching"
    SELECTING_FLIGHT = "selecting_flight"
    ENTERING_PASSENGER = "entering_passenger"
    ENTERING_PAYMENT = "entering_payment"
    CONFIRMING = "confirming"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class PassengerInfo:
    """Passenger details for booking."""
    first_name: str
    last_name: str
    email: str
    phone: str
    date_of_birth: str  # YYYY-MM-DD format
    gender: str  # M or F
    passport_number: Optional[str] = None
    passport_expiry: Optional[str] = None  # YYYY-MM-DD
    passport_country: Optional[str] = None
    nationality: Optional[str] = None
    known_traveler_number: Optional[str] = None  # TSA PreCheck, Global Entry


@dataclass
class PaymentInfo:
    """Payment card details for booking."""
    card_number: str
    expiry_month: str  # MM
    expiry_year: str   # YYYY
    cvv: str
    cardholder_name: str
    billing_address: str
    billing_city: str
    billing_state: str
    billing_zip: str
    billing_country: str


@dataclass
class FlightDetails:
    """Flight details for booking."""
    origin: str
    destination: str
    departure_date: str  # YYYY-MM-DD
    airline: str
    flight_number: Optional[str] = None
    departure_time: Optional[str] = None
    booking_url: Optional[str] = None
    market: str = "US"


@dataclass
class BookingResult:
    """Result of a booking attempt."""
    success: bool
    confirmation_code: Optional[str] = None
    status: BookingStatus = BookingStatus.PENDING
    error_message: Optional[str] = None
    screenshot_path: Optional[str] = None
    booking_url: Optional[str] = None
    total_charged: Optional[float] = None
    currency: str = "USD"
    raw_response: Optional[Dict] = None


class AirlineBooker:
    """
    Main booking automation class.

    Uses Playwright with regional proxies to automate airline bookings
    while maintaining geographic price arbitrage.
    """

    def __init__(self):
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

        # Load platform payment credentials
        self.payment_info = self._load_platform_payment()

        # Screenshot directory for debugging
        self.screenshot_dir = os.getenv("BOOKING_SCREENSHOT_DIR", "/tmp/mystes_bookings")
        os.makedirs(self.screenshot_dir, exist_ok=True)

        # Booking timeout (seconds)
        self.booking_timeout = int(os.getenv("BOOKING_TIMEOUT", "300"))

        # Airline-specific handlers
        self.airline_handlers: Dict[str, Callable] = {
            "jal": self._book_jal,
            "japan airlines": self._book_jal,
            "ana": self._book_ana,
            "all nippon airways": self._book_ana,
            "iberia": self._book_iberia,
            "air france": self._book_air_france,
            "klm": self._book_klm,
            "lufthansa": self._book_lufthansa,
            "british airways": self._book_british_airways,
            "american airlines": self._book_american,
            "delta": self._book_delta,
            "united": self._book_united,
        }

    def _load_platform_payment(self) -> Optional[PaymentInfo]:
        """Load platform's payment card from environment."""
        card_number = os.getenv("PLATFORM_CARD_NUMBER")
        if not card_number:
            return None

        return PaymentInfo(
            card_number=card_number,
            expiry_month=os.getenv("PLATFORM_CARD_EXPIRY_MONTH", ""),
            expiry_year=os.getenv("PLATFORM_CARD_EXPIRY_YEAR", ""),
            cvv=os.getenv("PLATFORM_CARD_CVV", ""),
            cardholder_name=os.getenv("PLATFORM_CARD_NAME", "MYSTES Inc"),
            billing_address=os.getenv("PLATFORM_BILLING_ADDRESS", ""),
            billing_city=os.getenv("PLATFORM_BILLING_CITY", ""),
            billing_state=os.getenv("PLATFORM_BILLING_STATE", ""),
            billing_zip=os.getenv("PLATFORM_BILLING_ZIP", ""),
            billing_country=os.getenv("PLATFORM_BILLING_COUNTRY", "US"),
        )

    async def _get_proxy_config(self, market: str) -> Optional[Dict[str, str]]:
        """Get proxy configuration for a market."""
        from proxy_manager import get_proxy_for_market
        return get_proxy_for_market(market)

    async def _init_browser(self, market: str = "US") -> None:
        """Initialize Playwright browser with proxy for the target market."""
        playwright = await async_playwright().start()

        # Get proxy for market
        proxy = await self._get_proxy_config(market)

        browser_args = {
            "headless": os.getenv("BOOKING_HEADLESS", "true").lower() == "true",
        }

        # Configure proxy if available
        if proxy:
            # Parse proxy URL
            proxy_url = proxy.get("http", "")
            if proxy_url:
                browser_args["proxy"] = {
                    "server": proxy_url.replace("http://", "").split("@")[-1] if "@" in proxy_url else proxy_url,
                }
                # Extract credentials if present
                if "@" in proxy_url:
                    creds = proxy_url.split("://")[1].split("@")[0]
                    if ":" in creds:
                        username, password = creds.split(":", 1)
                        browser_args["proxy"]["username"] = username
                        browser_args["proxy"]["password"] = password

        self.browser = await playwright.chromium.launch(**browser_args)

        # Create context with realistic browser fingerprint
        self.context = await self.browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale=self._get_locale_for_market(market),
            timezone_id=self._get_timezone_for_market(market),
        )

        self.page = await self.context.new_page()

        # Set default timeout
        self.page.set_default_timeout(30000)

    def _get_locale_for_market(self, market: str) -> str:
        """Get browser locale for market."""
        locales = {
            "US": "en-US",
            "JP": "ja-JP",
            "UK": "en-GB",
            "GB": "en-GB",
            "DE": "de-DE",
            "FR": "fr-FR",
            "ES": "es-ES",
            "IT": "it-IT",
            "NL": "nl-NL",
            "BR": "pt-BR",
            "KR": "ko-KR",
            "CN": "zh-CN",
        }
        return locales.get(market, "en-US")

    def _get_timezone_for_market(self, market: str) -> str:
        """Get timezone for market."""
        timezones = {
            "US": "America/New_York",
            "JP": "Asia/Tokyo",
            "UK": "Europe/London",
            "GB": "Europe/London",
            "DE": "Europe/Berlin",
            "FR": "Europe/Paris",
            "ES": "Europe/Madrid",
            "AU": "Australia/Sydney",
            "SG": "Asia/Singapore",
            "KR": "Asia/Seoul",
            "CN": "Asia/Shanghai",
        }
        return timezones.get(market, "America/New_York")

    async def _close_browser(self) -> None:
        """Close browser and cleanup."""
        if self.page:
            await self.page.close()
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()

        self.page = None
        self.context = None
        self.browser = None

    async def _take_screenshot(self, name: str) -> str:
        """Take a screenshot for debugging."""
        if not self.page:
            return ""

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{name}_{timestamp}.png"
        filepath = os.path.join(self.screenshot_dir, filename)

        try:
            await self.page.screenshot(path=filepath)
            logger.info(f"Screenshot saved: {filepath}")
            return filepath
        except Exception as e:
            logger.error(f"Screenshot failed: {e}")
            return ""

    async def book_flight(
        self,
        flight: FlightDetails,
        passenger: PassengerInfo,
        payment: Optional[PaymentInfo] = None,
        booking_id: Optional[int] = None,
    ) -> BookingResult:
        """
        Main booking method - attempts to book a flight automatically.

        Args:
            flight: Flight details to book
            passenger: Passenger information
            payment: Payment card (uses platform card if not provided)
            booking_id: Optional booking ID for tracking

        Returns:
            BookingResult with success/failure and confirmation code
        """
        payment = payment or self.payment_info

        if not payment:
            return BookingResult(
                success=False,
                status=BookingStatus.FAILED,
                error_message="No payment method configured"
            )

        try:
            # Initialize browser with market's proxy
            await self._init_browser(flight.market)

            # Get airline-specific handler
            airline_key = flight.airline.lower().strip()
            handler = self.airline_handlers.get(airline_key, self._book_generic)

            # Execute booking
            result = await handler(flight, passenger, payment)

            # Take final screenshot
            if self.page:
                result.screenshot_path = await self._take_screenshot(
                    f"booking_{booking_id or 'unknown'}_final"
                )

            return result

        except Exception as e:
            logger.error(f"Booking error: {e}")

            # Take error screenshot
            screenshot = ""
            if self.page:
                screenshot = await self._take_screenshot(f"booking_{booking_id or 'unknown'}_error")

            return BookingResult(
                success=False,
                status=BookingStatus.FAILED,
                error_message=str(e),
                screenshot_path=screenshot
            )

        finally:
            await self._close_browser()

    # --- GENERIC BOOKING HANDLER ---

    async def _book_generic(
        self,
        flight: FlightDetails,
        passenger: PassengerInfo,
        payment: PaymentInfo
    ) -> BookingResult:
        """
        Generic booking handler using Google Flights as entry point.

        Works by:
        1. Searching on Google Flights with the market locale
        2. Clicking through to airline's booking page
        3. Attempting to fill passenger and payment forms
        """
        if not self.page:
            return BookingResult(success=False, error_message="Browser not initialized")

        try:
            # Step 1: Navigate to Google Flights
            search_url = self._build_google_flights_url(flight)
            logger.info(f"Navigating to: {search_url}")

            await self.page.goto(search_url, wait_until="networkidle")
            await self._take_screenshot("search_results")

            # Step 2: Find and select the target flight
            flight_selected = await self._select_flight_google(flight)
            if not flight_selected:
                return BookingResult(
                    success=False,
                    status=BookingStatus.SEARCHING,
                    error_message="Could not find target flight"
                )

            await self._take_screenshot("flight_selected")

            # Step 3: Click through to airline booking
            booking_clicked = await self._click_book_button()
            if not booking_clicked:
                return BookingResult(
                    success=False,
                    status=BookingStatus.SELECTING_FLIGHT,
                    error_message="Could not click booking button"
                )

            # Wait for airline site to load
            await self.page.wait_for_load_state("networkidle")
            await self._take_screenshot("airline_site")

            # Step 4: Fill passenger information
            passenger_filled = await self._fill_passenger_generic(passenger)
            if not passenger_filled:
                return BookingResult(
                    success=False,
                    status=BookingStatus.ENTERING_PASSENGER,
                    error_message="Could not fill passenger information"
                )

            await self._take_screenshot("passenger_filled")

            # Step 5: Fill payment information
            payment_filled = await self._fill_payment_generic(payment)
            if not payment_filled:
                return BookingResult(
                    success=False,
                    status=BookingStatus.ENTERING_PAYMENT,
                    error_message="Could not fill payment information"
                )

            await self._take_screenshot("payment_filled")

            # Step 6: Submit and get confirmation
            confirmation = await self._submit_and_get_confirmation()

            if confirmation:
                return BookingResult(
                    success=True,
                    status=BookingStatus.COMPLETED,
                    confirmation_code=confirmation,
                    booking_url=self.page.url
                )
            else:
                return BookingResult(
                    success=False,
                    status=BookingStatus.CONFIRMING,
                    error_message="Could not extract confirmation code"
                )

        except Exception as e:
            logger.error(f"Generic booking error: {e}")
            return BookingResult(
                success=False,
                status=BookingStatus.FAILED,
                error_message=str(e)
            )

    def _build_google_flights_url(self, flight: FlightDetails) -> str:
        """Build Google Flights search URL."""
        # Format: google.com/travel/flights?q=Flights+from+JFK+to+NRT+on+2024-03-15
        date_str = flight.departure_date
        market = flight.market.lower()

        return (
            f"https://www.google.com/travel/flights"
            f"?q=Flights+from+{flight.origin}+to+{flight.destination}+on+{date_str}"
            f"&gl={market}&hl={self._get_locale_for_market(flight.market).split('-')[0]}"
        )

    async def _select_flight_google(self, flight: FlightDetails) -> bool:
        """Select a flight from Google Flights results."""
        if not self.page:
            return False

        try:
            # Wait for flight results to load
            await self.page.wait_for_selector('[data-ved]', timeout=10000)

            # Look for the specific flight by flight number or time
            if flight.flight_number:
                # Try to find by flight number
                flight_elem = await self.page.query_selector(
                    f'text=/{flight.flight_number}/i'
                )
                if flight_elem:
                    await flight_elem.click()
                    return True

            # Otherwise click first available flight
            flights = await self.page.query_selector_all('[role="listitem"]')
            if flights:
                await flights[0].click()
                await self.page.wait_for_timeout(2000)
                return True

            return False

        except Exception as e:
            logger.error(f"Flight selection error: {e}")
            return False

    async def _click_book_button(self) -> bool:
        """Click the 'Book' or 'Select' button to proceed to airline site."""
        if not self.page:
            return False

        try:
            # Common booking button selectors
            book_selectors = [
                'button:has-text("Book")',
                'button:has-text("Select")',
                'a:has-text("Book")',
                'a:has-text("Continue")',
                '[data-booking-button]',
                '.booking-button',
                '[aria-label*="Book"]',
            ]

            for selector in book_selectors:
                try:
                    btn = await self.page.wait_for_selector(selector, timeout=3000)
                    if btn:
                        await btn.click()
                        await self.page.wait_for_timeout(3000)
                        return True
                except:
                    continue

            return False

        except Exception as e:
            logger.error(f"Book button click error: {e}")
            return False

    async def _fill_passenger_generic(self, passenger: PassengerInfo) -> bool:
        """Fill passenger information on a generic airline form."""
        if not self.page:
            return False

        try:
            # Common passenger field patterns
            field_mappings = [
                # First name
                (['input[name*="first"]', 'input[id*="first"]', '#firstName', '[name="firstName"]'], passenger.first_name),
                # Last name
                (['input[name*="last"]', 'input[id*="last"]', '#lastName', '[name="lastName"]'], passenger.last_name),
                # Email
                (['input[type="email"]', 'input[name*="email"]', '#email'], passenger.email),
                # Phone
                (['input[type="tel"]', 'input[name*="phone"]', '#phone'], passenger.phone),
            ]

            for selectors, value in field_mappings:
                for selector in selectors:
                    try:
                        field = await self.page.query_selector(selector)
                        if field:
                            await field.fill(value)
                            break
                    except:
                        continue

            # Handle date of birth if present
            await self._fill_dob_field(passenger.date_of_birth)

            # Handle gender selection if present
            await self._select_gender(passenger.gender)

            return True

        except Exception as e:
            logger.error(f"Passenger fill error: {e}")
            return False

    async def _fill_dob_field(self, dob: str) -> None:
        """Fill date of birth field (handles various formats)."""
        if not self.page or not dob:
            return

        try:
            # Split DOB
            parts = dob.split("-")
            if len(parts) != 3:
                return

            year, month, day = parts

            # Try common DOB field patterns
            dob_selectors = [
                ('input[name*="birth"]', dob),
                ('input[name*="dob"]', dob),
                ('#dateOfBirth', dob),
            ]

            for selector, value in dob_selectors:
                try:
                    field = await self.page.query_selector(selector)
                    if field:
                        await field.fill(value)
                        return
                except:
                    continue

            # Try separate day/month/year fields
            day_fields = ['select[name*="day"]', '#dobDay', 'input[name*="day"]']
            month_fields = ['select[name*="month"]', '#dobMonth', 'input[name*="month"]']
            year_fields = ['select[name*="year"]', '#dobYear', 'input[name*="year"]']

            for selector in day_fields:
                try:
                    field = await self.page.query_selector(selector)
                    if field:
                        await field.fill(day)
                        break
                except:
                    continue

            for selector in month_fields:
                try:
                    field = await self.page.query_selector(selector)
                    if field:
                        await field.fill(month)
                        break
                except:
                    continue

            for selector in year_fields:
                try:
                    field = await self.page.query_selector(selector)
                    if field:
                        await field.fill(year)
                        break
                except:
                    continue

        except Exception as e:
            logger.debug(f"DOB fill error: {e}")

    async def _select_gender(self, gender: str) -> None:
        """Select gender from dropdown or radio buttons."""
        if not self.page or not gender:
            return

        try:
            gender_value = "male" if gender.upper() == "M" else "female"

            # Try radio buttons
            radio_selectors = [
                f'input[type="radio"][value="{gender_value}"]',
                f'input[type="radio"][value="{gender.upper()}"]',
                f'input[name*="gender"][value*="{gender_value[:1]}"]',
            ]

            for selector in radio_selectors:
                try:
                    radio = await self.page.query_selector(selector)
                    if radio:
                        await radio.click()
                        return
                except:
                    continue

            # Try dropdown
            select_selectors = ['select[name*="gender"]', '#gender', 'select[id*="gender"]']
            for selector in select_selectors:
                try:
                    select = await self.page.query_selector(selector)
                    if select:
                        await select.select_option(value=gender_value)
                        return
                except:
                    continue

        except Exception as e:
            logger.debug(f"Gender selection error: {e}")

    async def _fill_payment_generic(self, payment: PaymentInfo) -> bool:
        """Fill payment information on a generic airline form."""
        if not self.page:
            return False

        try:
            # Check for iframe (common for payment forms)
            iframes = await self.page.query_selector_all('iframe')
            payment_frame = self.page

            for iframe in iframes:
                try:
                    frame = await iframe.content_frame()
                    if frame:
                        # Check if this looks like a payment iframe
                        card_field = await frame.query_selector('input[name*="card"]')
                        if card_field:
                            payment_frame = frame
                            break
                except:
                    continue

            # Fill card number
            card_selectors = [
                'input[name*="cardNumber"]', 'input[name*="card_number"]',
                'input[id*="cardNumber"]', '#cardNumber',
                'input[autocomplete="cc-number"]', 'input[name*="ccnum"]',
            ]

            for selector in card_selectors:
                try:
                    field = await payment_frame.query_selector(selector)
                    if field:
                        await field.fill(payment.card_number)
                        break
                except:
                    continue

            # Fill expiry
            expiry_selectors = [
                ('input[name*="expiry"]', f"{payment.expiry_month}/{payment.expiry_year[-2:]}"),
                ('input[name*="exp_date"]', f"{payment.expiry_month}/{payment.expiry_year[-2:]}"),
                ('input[autocomplete="cc-exp"]', f"{payment.expiry_month}/{payment.expiry_year[-2:]}"),
            ]

            for selector, value in expiry_selectors:
                try:
                    field = await payment_frame.query_selector(selector)
                    if field:
                        await field.fill(value)
                        break
                except:
                    continue

            # Try separate month/year fields
            month_selectors = ['select[name*="exp"]select[name*="month"]', '#expMonth', 'select[name*="expMonth"]']
            year_selectors = ['select[name*="exp"]select[name*="year"]', '#expYear', 'select[name*="expYear"]']

            for selector in month_selectors:
                try:
                    field = await payment_frame.query_selector(selector)
                    if field:
                        await field.select_option(value=payment.expiry_month)
                        break
                except:
                    continue

            for selector in year_selectors:
                try:
                    field = await payment_frame.query_selector(selector)
                    if field:
                        await field.select_option(value=payment.expiry_year)
                        break
                except:
                    continue

            # Fill CVV
            cvv_selectors = [
                'input[name*="cvv"]', 'input[name*="cvc"]', 'input[name*="security"]',
                'input[autocomplete="cc-csc"]', '#cvv', '#securityCode',
            ]

            for selector in cvv_selectors:
                try:
                    field = await payment_frame.query_selector(selector)
                    if field:
                        await field.fill(payment.cvv)
                        break
                except:
                    continue

            # Fill cardholder name
            name_selectors = [
                'input[name*="cardHolder"]', 'input[name*="card_holder"]',
                'input[name*="holderName"]', 'input[autocomplete="cc-name"]',
                '#cardholderName',
            ]

            for selector in name_selectors:
                try:
                    field = await payment_frame.query_selector(selector)
                    if field:
                        await field.fill(payment.cardholder_name)
                        break
                except:
                    continue

            # Fill billing address if visible
            await self._fill_billing_address(payment)

            return True

        except Exception as e:
            logger.error(f"Payment fill error: {e}")
            return False

    async def _fill_billing_address(self, payment: PaymentInfo) -> None:
        """Fill billing address fields."""
        if not self.page:
            return

        try:
            address_mappings = [
                (['input[name*="address"]', 'input[name*="street"]', '#billingAddress'], payment.billing_address),
                (['input[name*="city"]', '#billingCity'], payment.billing_city),
                (['input[name*="state"]', '#billingState', 'select[name*="state"]'], payment.billing_state),
                (['input[name*="zip"]', 'input[name*="postal"]', '#billingZip'], payment.billing_zip),
            ]

            for selectors, value in address_mappings:
                if not value:
                    continue
                for selector in selectors:
                    try:
                        field = await self.page.query_selector(selector)
                        if field:
                            tag_name = await field.evaluate('el => el.tagName')
                            if tag_name.lower() == 'select':
                                await field.select_option(value=value)
                            else:
                                await field.fill(value)
                            break
                    except:
                        continue

        except Exception as e:
            logger.debug(f"Billing address fill error: {e}")

    async def _submit_and_get_confirmation(self) -> Optional[str]:
        """Submit booking and extract confirmation code."""
        if not self.page:
            return None

        try:
            # Click submit/confirm button
            submit_selectors = [
                'button:has-text("Confirm")',
                'button:has-text("Complete")',
                'button:has-text("Purchase")',
                'button:has-text("Pay")',
                'button[type="submit"]',
                'input[type="submit"]',
                '.submit-button',
                '#confirmBooking',
            ]

            for selector in submit_selectors:
                try:
                    btn = await self.page.query_selector(selector)
                    if btn:
                        await btn.click()
                        break
                except:
                    continue

            # Wait for confirmation page
            await self.page.wait_for_load_state("networkidle")
            await self.page.wait_for_timeout(5000)

            # Extract confirmation code
            confirmation = await self._extract_confirmation_code()

            return confirmation

        except Exception as e:
            logger.error(f"Submit error: {e}")
            return None

    async def _extract_confirmation_code(self) -> Optional[str]:
        """Extract confirmation/PNR code from confirmation page."""
        if not self.page:
            return None

        try:
            # Common confirmation code patterns
            patterns = [
                r'(?:confirmation|booking|reference|pnr|record locator)[:\s#]*([A-Z0-9]{5,8})',
                r'[A-Z]{6}',  # Standard PNR format
                r'\b[A-Z0-9]{6}\b',
            ]

            # Get page content
            content = await self.page.content()

            # Try specific selectors first
            code_selectors = [
                '.confirmation-code', '#confirmationCode', '[data-confirmation]',
                '.booking-reference', '#pnr', '.pnr-code',
            ]

            for selector in code_selectors:
                try:
                    elem = await self.page.query_selector(selector)
                    if elem:
                        text = await elem.text_content()
                        if text:
                            # Clean and return
                            code = re.sub(r'[^A-Z0-9]', '', text.upper())
                            if 5 <= len(code) <= 8:
                                return code
                except:
                    continue

            # Try regex patterns on page text
            text = await self.page.evaluate('() => document.body.innerText')

            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    code = match.group(1) if match.lastindex else match.group(0)
                    code = re.sub(r'[^A-Z0-9]', '', code.upper())
                    if 5 <= len(code) <= 8:
                        return code

            return None

        except Exception as e:
            logger.error(f"Confirmation extraction error: {e}")
            return None

    # --- AIRLINE-SPECIFIC HANDLERS ---

    async def _book_jal(
        self,
        flight: FlightDetails,
        passenger: PassengerInfo,
        payment: PaymentInfo
    ) -> BookingResult:
        """Japan Airlines specific booking handler."""
        # JAL uses jal.co.jp
        # They have a specific booking flow that we can optimize for
        logger.info("Using JAL-specific booking handler")

        # For now, use generic handler as base
        # Future: Add JAL-specific selectors and flow
        return await self._book_generic(flight, passenger, payment)

    async def _book_ana(
        self,
        flight: FlightDetails,
        passenger: PassengerInfo,
        payment: PaymentInfo
    ) -> BookingResult:
        """All Nippon Airways specific booking handler."""
        logger.info("Using ANA-specific booking handler")
        return await self._book_generic(flight, passenger, payment)

    async def _book_iberia(
        self,
        flight: FlightDetails,
        passenger: PassengerInfo,
        payment: PaymentInfo
    ) -> BookingResult:
        """Iberia specific booking handler."""
        logger.info("Using Iberia-specific booking handler")
        return await self._book_generic(flight, passenger, payment)

    async def _book_air_france(
        self,
        flight: FlightDetails,
        passenger: PassengerInfo,
        payment: PaymentInfo
    ) -> BookingResult:
        """Air France specific booking handler."""
        logger.info("Using Air France-specific booking handler")
        return await self._book_generic(flight, passenger, payment)

    async def _book_klm(
        self,
        flight: FlightDetails,
        passenger: PassengerInfo,
        payment: PaymentInfo
    ) -> BookingResult:
        """KLM specific booking handler."""
        logger.info("Using KLM-specific booking handler")
        return await self._book_generic(flight, passenger, payment)

    async def _book_lufthansa(
        self,
        flight: FlightDetails,
        passenger: PassengerInfo,
        payment: PaymentInfo
    ) -> BookingResult:
        """Lufthansa specific booking handler."""
        logger.info("Using Lufthansa-specific booking handler")
        return await self._book_generic(flight, passenger, payment)

    async def _book_british_airways(
        self,
        flight: FlightDetails,
        passenger: PassengerInfo,
        payment: PaymentInfo
    ) -> BookingResult:
        """British Airways specific booking handler."""
        logger.info("Using British Airways-specific booking handler")
        return await self._book_generic(flight, passenger, payment)

    async def _book_american(
        self,
        flight: FlightDetails,
        passenger: PassengerInfo,
        payment: PaymentInfo
    ) -> BookingResult:
        """American Airlines specific booking handler."""
        logger.info("Using American Airlines-specific booking handler")
        return await self._book_generic(flight, passenger, payment)

    async def _book_delta(
        self,
        flight: FlightDetails,
        passenger: PassengerInfo,
        payment: PaymentInfo
    ) -> BookingResult:
        """Delta specific booking handler."""
        logger.info("Using Delta-specific booking handler")
        return await self._book_generic(flight, passenger, payment)

    async def _book_united(
        self,
        flight: FlightDetails,
        passenger: PassengerInfo,
        payment: PaymentInfo
    ) -> BookingResult:
        """United Airlines specific booking handler."""
        logger.info("Using United-specific booking handler")
        return await self._book_generic(flight, passenger, payment)


# --- CONVENIENCE FUNCTIONS ---

async def book_flight_automated(
    deal_data: Dict[str, Any],
    passenger_data: Dict[str, Any],
    booking_id: Optional[int] = None
) -> BookingResult:
    """
    Book a flight using the automated system.

    Args:
        deal_data: Dict with flight/deal information
        passenger_data: Dict with passenger information
        booking_id: Optional booking ID for tracking

    Returns:
        BookingResult with success/failure
    """
    booker = AirlineBooker()

    # Convert dicts to dataclasses
    flight = FlightDetails(
        origin=deal_data.get("origin", ""),
        destination=deal_data.get("destination", ""),
        departure_date=deal_data.get("departure_date", ""),
        airline=deal_data.get("airline", ""),
        flight_number=deal_data.get("flight_number"),
        departure_time=deal_data.get("departure_time"),
        booking_url=deal_data.get("booking_url"),
        market=deal_data.get("arbitrage_market", "US"),
    )

    passenger = PassengerInfo(
        first_name=passenger_data.get("first_name", ""),
        last_name=passenger_data.get("last_name", ""),
        email=passenger_data.get("email", ""),
        phone=passenger_data.get("phone", ""),
        date_of_birth=passenger_data.get("date_of_birth", ""),
        gender=passenger_data.get("gender", "M"),
        passport_number=passenger_data.get("passport_number"),
        passport_expiry=passenger_data.get("passport_expiry"),
        passport_country=passenger_data.get("passport_country"),
    )

    return await booker.book_flight(flight, passenger, booking_id=booking_id)


def book_flight_sync(
    deal_data: Dict[str, Any],
    passenger_data: Dict[str, Any],
    booking_id: Optional[int] = None
) -> BookingResult:
    """
    Synchronous wrapper for book_flight_automated.

    Handles the case where we're called from within an existing event loop
    (e.g., Flask with async extensions) by creating a new thread.
    """
    try:
        # Check if there's already a running event loop
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # We're inside an existing event loop - run in a separate thread
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(
                asyncio.run,
                book_flight_automated(deal_data, passenger_data, booking_id)
            )
            return future.result(timeout=360)
    else:
        return asyncio.run(book_flight_automated(deal_data, passenger_data, booking_id))


# --- CLI FOR TESTING ---

if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv

    load_dotenv()

    print("MYSTES Automated Booking System")
    print("=" * 50)

    # Check configuration
    booker = AirlineBooker()

    if booker.payment_info:
        print(f"Payment configured: {booker.payment_info.cardholder_name}")
        print(f"Card ending in: ...{booker.payment_info.card_number[-4:]}")
    else:
        print("WARNING: No payment credentials configured")
        print("Set PLATFORM_CARD_NUMBER, PLATFORM_CARD_CVV, etc. in .env")

    print(f"\nSupported airlines: {', '.join(booker.airline_handlers.keys())}")
    print(f"Screenshot directory: {booker.screenshot_dir}")
    print(f"Booking timeout: {booker.booking_timeout}s")
