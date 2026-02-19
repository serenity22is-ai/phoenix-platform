"""
MYSTES Booking Fulfillment System

Handles the complete flow from customer payment to ticket delivery:
1. Customer pays us (Card, XRP, RLUSD, Crypto)
2. We purchase the ticket from the airline at the arbitrage price
3. We send the e-ticket/confirmation to the customer

Fulfillment Types:
- self_service: Customer books via our proxy (current MVP approach)
- automated: System books automatically via airline API (future)
- manual_agent: Human agent books on behalf of customer (hybrid approach)
"""

import os
import logging
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class FulfillmentType(Enum):
    SELF_SERVICE = "self_service"       # Customer books via proxy
    AUTOMATED = "automated"             # Automated API booking
    MANUAL_AGENT = "manual_agent"       # Human agent books


class BookingStatus(Enum):
    PENDING = "pending"                         # Initial state
    PENDING_FULFILLMENT = "pending_fulfillment" # Payment verified, awaiting booking
    PROCESSING = "processing"                   # Booking in progress
    BOOKED = "booked"                          # Ticket purchased
    TICKET_SENT = "ticket_sent"                # E-ticket delivered
    COMPLETED = "completed"                    # Fully complete
    FAILED = "failed"                          # Booking failed
    CANCELLED = "cancelled"                    # Customer cancelled
    REFUNDED = "refunded"                      # Refund processed


class VendorPaymentStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


# --- CONFIGURATION ---

FULFILLMENT_CONFIG = {
    # Default fulfillment type for new bookings
    "default_type": FulfillmentType.SELF_SERVICE.value,

    # Virtual card provider for automated bookings (future)
    "virtual_card_provider": os.getenv("VIRTUAL_CARD_PROVIDER", ""),  # stripe_issuing, privacy, marqeta
    "virtual_card_api_key": os.getenv("VIRTUAL_CARD_API_KEY", ""),

    # Email settings
    "send_booking_emails": True,
    "support_email": os.getenv("SUPPORT_EMAIL", "support@mystes.com"),

    # Booking timeout (how long to wait for self-service completion)
    "self_service_timeout_hours": 24,

    # Auto-refund if booking not completed
    "auto_refund_on_timeout": False,
}


# --- BOOKING FULFILLMENT MANAGER ---

class BookingFulfillmentManager:
    """
    Manages the booking fulfillment process.

    Flow:
    1. Customer selects flights and pays
    2. Payment verified -> creates Booking with status='pending_fulfillment'
    3. Based on fulfillment_type:
       - self_service: Send booking instructions, user completes on proxy
       - automated: Purchase ticket programmatically
       - manual_agent: Queue for human agent
    4. Track vendor payment (actual ticket purchase)
    5. Deliver e-ticket to customer
    """

    def __init__(self, db_session):
        self.db = db_session

    def create_booking(self, deal, payment, user, fulfillment_type: str = None,
                       skip_fulfillment: bool = False) -> Dict[str, Any]:
        """
        Create a new booking after payment verification.

        Args:
            deal: The Deal model instance
            payment: The Payment model instance
            user: The User model instance
            fulfillment_type: Override default fulfillment type
            skip_fulfillment: If True, create booking record only (caller handles fulfillment)

        Returns:
            dict with booking details and 'booking' key containing the model instance
        """
        from models import Booking

        fulfillment_type = fulfillment_type or FULFILLMENT_CONFIG["default_type"]

        # Check if booking already exists
        existing = Booking.query.filter_by(
            user_id=getattr(user, 'id', None),
            deal_id=deal.id,
            payment_id=payment.id
        ).first()

        if existing:
            return {
                "success": True,
                "booking_id": existing.id,
                "booking": existing,
                "status": existing.status,
                "message": "Booking already exists"
            }

        # Create new booking
        booking = Booking(
            user_id=getattr(user, 'id', None),
            deal_id=deal.id,
            payment_id=payment.id,
            passenger_email=getattr(user, 'email', None),
            status=BookingStatus.PENDING_FULFILLMENT.value,
            fulfillment_type=fulfillment_type,
            vendor_payment_amount=deal.arbitrage_price_usd,
            vendor_payment_currency="USD",
            created_at=datetime.utcnow()
        )

        self.db.add(booking)
        self.db.commit()

        logger.info(f"Created booking {booking.id} for deal {deal.deal_id}, fulfillment: {fulfillment_type}")

        if skip_fulfillment:
            return {
                "success": True,
                "booking_id": booking.id,
                "booking": booking,
                "status": booking.status,
                "fulfillment_type": fulfillment_type,
            }

        # Initiate fulfillment based on type
        result = self._initiate_fulfillment(booking, deal, user)

        return {
            "success": True,
            "booking_id": booking.id,
            "booking": booking,
            "status": booking.status,
            "fulfillment_type": fulfillment_type,
            **result
        }

    def _initiate_fulfillment(self, booking, deal, user) -> Dict[str, Any]:
        """
        Initiate the appropriate fulfillment process.
        """
        if booking.fulfillment_type == FulfillmentType.SELF_SERVICE.value:
            return self._fulfillment_self_service(booking, deal, user)
        elif booking.fulfillment_type == FulfillmentType.AUTOMATED.value:
            return self._fulfillment_automated(booking, deal, user)
        elif booking.fulfillment_type == FulfillmentType.MANUAL_AGENT.value:
            return self._fulfillment_manual_agent(booking, deal, user)
        else:
            return {"message": "Unknown fulfillment type"}

    def _fulfillment_self_service(self, booking, deal, user) -> Dict[str, Any]:
        """
        Self-service fulfillment: Customer books via proxy.

        Steps:
        1. Send email with booking instructions
        2. Provide proxy links to airline booking pages
        3. Customer completes booking themselves
        4. They save confirmation code in our system
        """
        # Build booking URLs
        booking_urls = self._generate_booking_urls(deal)

        # Send booking instructions email
        self._send_booking_instructions_email(user, deal, booking, booking_urls)

        # Update booking status
        booking.status = BookingStatus.PROCESSING.value
        booking.fulfillment_notes = f"Self-service booking initiated. Instructions sent to {user.email}"
        self.db.commit()

        return {
            "message": "Booking instructions sent to your email",
            "booking_urls": booking_urls,
            "expires_in_hours": FULFILLMENT_CONFIG["self_service_timeout_hours"]
        }

    def _fulfillment_automated(self, booking, deal, user) -> Dict[str, Any]:
        """
        Automated fulfillment: System purchases ticket programmatically.

        This requires:
        1. Airline API access (GDS like Amadeus, Sabre, Travelport)
        2. OR Virtual credit card for web automation

        For MVP, this is a placeholder that falls back to manual_agent.
        """
        logger.info(f"Automated fulfillment requested for booking {booking.id}")

        # Check if we have automated booking capability
        has_automation = self._check_automation_availability(deal)

        if not has_automation:
            # Fall back to manual agent
            booking.fulfillment_type = FulfillmentType.MANUAL_AGENT.value
            booking.fulfillment_notes = "Automated booking unavailable, queued for manual processing"
            self.db.commit()
            return self._fulfillment_manual_agent(booking, deal, user)

        # Attempt automated booking
        try:
            result = self._execute_automated_booking(booking, deal, user)

            if result.get("success"):
                booking.status = BookingStatus.BOOKED.value
                booking.confirmation_code = result.get("confirmation_code")
                booking.vendor_payment_status = VendorPaymentStatus.COMPLETED.value
                booking.vendor_payment_reference = result.get("payment_reference")
                booking.booked_at = datetime.utcnow()
                self.db.commit()

                # Send confirmation email
                self._send_booking_confirmation_email(user, deal, booking)

                return {
                    "message": "Booking completed successfully!",
                    "confirmation_code": booking.confirmation_code
                }
            else:
                # Fall back to manual
                booking.fulfillment_type = FulfillmentType.MANUAL_AGENT.value
                booking.fulfillment_notes = f"Automated booking failed: {result.get('error')}"
                self.db.commit()
                return self._fulfillment_manual_agent(booking, deal, user)

        except Exception as e:
            logger.error(f"Automated booking error: {e}")
            booking.fulfillment_type = FulfillmentType.MANUAL_AGENT.value
            booking.fulfillment_notes = f"Automated booking error: {str(e)}"
            self.db.commit()
            return self._fulfillment_manual_agent(booking, deal, user)

    def _fulfillment_manual_agent(self, booking, deal, user) -> Dict[str, Any]:
        """
        Manual agent fulfillment: Queue for human agent to book.

        This is the fallback for when automation isn't available.
        An agent will book the ticket and update the system.
        """
        # Queue for agent
        booking.status = BookingStatus.PROCESSING.value
        booking.fulfillment_notes = f"Queued for manual booking at {datetime.utcnow().isoformat()}"
        self.db.commit()

        # Notify agents (in production, this would be Slack/email/queue)
        self._notify_agents_new_booking(booking, deal, user)

        # Send customer notification
        self._send_processing_notification_email(user, deal, booking)

        return {
            "message": "Your booking is being processed by our team. You'll receive confirmation within 2-4 hours.",
            "estimated_completion": "2-4 hours"
        }

    def _check_automation_availability(self, deal) -> bool:
        """
        Check if automated booking is available for this deal.
        """
        import os
        has_payment_config = bool(os.getenv("PLATFORM_CARD_NUMBER"))

        # Hotels: can be booked via Amadeus API directly (no proxy needed)
        if getattr(deal, 'deal_type', 'flight') == 'hotel':
            has_offer_id = bool(getattr(deal, 'hotel_offer_id', None))
            logger.info(f"Hotel automation check - payment: {has_payment_config}, offer_id: {has_offer_id}")
            return has_payment_config and has_offer_id

        # Flights: need proxy + payment config
        from proxy_manager import is_proxy_configured
        has_proxy = is_proxy_configured()

        supported_airlines = [
            "jal", "japan airlines", "ana", "all nippon airways",
            "iberia", "air france", "klm", "lufthansa",
            "british airways", "american airlines", "delta", "united"
        ]
        airline_supported = deal.airline and deal.airline.lower() in supported_airlines

        logger.info(f"Automation check - payment: {has_payment_config}, proxy: {has_proxy}, airline: {airline_supported}")

        return has_payment_config and has_proxy

    def _execute_automated_booking(self, booking, deal, user) -> Dict[str, Any]:
        """
        Execute an automated booking using Playwright browser automation.

        Flow:
        1. Get passenger details from booking
        2. Use AirlineBooker to navigate airline site via proxy
        3. Fill passenger and payment information
        4. Complete booking and capture confirmation code
        """
        try:
            from airline_booker import book_flight_sync

            # Prepare deal data
            deal_data = {
                "origin": deal.origin,
                "destination": deal.destination,
                "departure_date": deal.departure_date.isoformat() if deal.departure_date else "",
                "airline": deal.airline or "",
                "flight_number": deal.flight_number,
                "departure_time": deal.departure_time,
                "booking_url": deal.booking_url,
                "arbitrage_market": deal.arbitrage_market or "US",
            }

            # Get passenger data from booking
            # Parse passenger name into first/last
            name_parts = (booking.passenger_name or "Guest User").split(" ", 1)
            first_name = name_parts[0]
            last_name = name_parts[1] if len(name_parts) > 1 else ""

            passenger_data = {
                "first_name": first_name,
                "last_name": last_name,
                "email": booking.passenger_email or user.email,
                "phone": "",  # Would need to be stored in booking
                "date_of_birth": "",  # Would need to be stored
                "gender": "M",  # Would need to be stored
            }

            logger.info(f"Executing automated booking for {deal.airline} flight to {deal.destination}")

            # Execute the automated booking
            result = book_flight_sync(deal_data, passenger_data, booking.id)

            if result.success:
                logger.info(f"Automated booking successful: {result.confirmation_code}")
                return {
                    "success": True,
                    "confirmation_code": result.confirmation_code,
                    "payment_reference": result.booking_url,
                }
            else:
                logger.warning(f"Automated booking failed: {result.error_message}")
                return {
                    "success": False,
                    "error": result.error_message or "Booking failed"
                }

        except ImportError as e:
            logger.error(f"airline_booker module not available: {e}")
            return {
                "success": False,
                "error": "Automated booking system not available"
            }
        except Exception as e:
            logger.error(f"Automated booking execution error: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def _generate_booking_urls(self, deal) -> list:
        """
        Generate booking URLs for self-service fulfillment.
        """
        urls = []

        if deal.is_multi_leg and deal.flight_legs:
            import json
            try:
                legs = json.loads(deal.flight_legs) if isinstance(deal.flight_legs, str) else deal.flight_legs
                for i, leg in enumerate(legs):
                    route = leg.get("route", "")
                    parts = route.split(" → ") if " → " in route else route.split(" to ")
                    origin = parts[0] if parts else deal.origin
                    dest = parts[-1] if len(parts) > 1 else deal.destination
                    date = leg.get("date", "")
                    market = leg.get("cheapest_market", deal.arbitrage_market or "US")

                    url = f"https://www.google.com/travel/flights?q=Flights+from+{origin}+to+{dest}+on+{date}&gl={market.lower()}"
                    urls.append({
                        "leg": i + 1,
                        "route": route,
                        "date": date,
                        "market": market,
                        "url": url,
                        "proxy_url": f"/proxy/{url}"
                    })
            except:
                pass
        else:
            market = deal.arbitrage_market or "US"
            date = deal.departure_date.isoformat() if deal.departure_date else ""
            url = f"https://www.google.com/travel/flights?q=Flights+from+{deal.origin}+to+{deal.destination}+on+{date}&gl={market.lower()}"
            urls.append({
                "leg": 1,
                "route": f"{deal.origin} → {deal.destination}",
                "date": date,
                "market": market,
                "url": url,
                "proxy_url": f"/proxy/{url}"
            })

        return urls

    def _send_booking_instructions_email(self, user, deal, booking, booking_urls):
        """Send email with booking instructions."""
        try:
            from email_service import send_email

            # Build leg list for email
            legs_html = ""
            for url_info in booking_urls:
                legs_html += f"""
                <div style="margin-bottom: 15px; padding: 15px; background: #f8f9fa; border-radius: 8px;">
                    <strong>Leg {url_info['leg']}: {url_info['route']}</strong><br>
                    <span style="color: #666;">Date: {url_info['date']} | Market: {url_info['market']}</span><br>
                    <a href="{url_info['proxy_url']}" style="display: inline-block; margin-top: 10px; background: #4361ee; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">
                        Book This Flight
                    </a>
                </div>
                """

            html_content = f"""
            <h2>Complete Your Flight Booking</h2>
            <p>Hi {user.name or 'there'},</p>
            <p>Your payment has been verified! Please complete your booking within 24 hours.</p>

            <h3>Your Flights</h3>
            {legs_html}

            <h3>Important Instructions</h3>
            <ol>
                <li>Click the booking links above (they'll open through our proxy)</li>
                <li>The prices shown will reflect the {deal.arbitrage_market or 'regional'} market discount</li>
                <li>Complete the booking using your own credit card on the airline's site</li>
                <li>Save your confirmation code</li>
            </ol>

            <p>You're saving <strong>${deal.user_savings_usd or 0:.2f}</strong> on this booking!</p>

            <p style="color: #666; font-size: 14px;">
                If you have any issues, reply to this email or contact support.
            </p>
            """

            send_email(
                to_email=user.email,
                subject=f"Complete Your Booking - {deal.origin} to {deal.destination}",
                html_content=html_content
            )

            logger.info(f"Booking instructions sent to {user.email}")

        except Exception as e:
            logger.error(f"Failed to send booking instructions email: {e}")

    def _send_booking_confirmation_email(self, user, deal, booking):
        """Send email with booking confirmation."""
        try:
            from email_service import send_email

            html_content = f"""
            <h2>Booking Confirmed!</h2>
            <p>Hi {user.name or 'there'},</p>
            <p>Great news! Your flight has been booked.</p>

            <div style="background: #d4edda; padding: 20px; border-radius: 8px; margin: 20px 0;">
                <h3 style="margin-top: 0;">Confirmation Code: {booking.confirmation_code}</h3>
                <p><strong>Route:</strong> {deal.origin} → {deal.destination}</p>
                <p><strong>Airline:</strong> {deal.airline}</p>
                <p><strong>Date:</strong> {deal.departure_date}</p>
            </div>

            <p>You saved <strong>${deal.user_savings_usd or 0:.2f}</strong> on this booking!</p>

            <p style="color: #666;">
                Your e-ticket will be sent separately by the airline.
                Check your email (including spam folder) for confirmation from {deal.airline or 'the airline'}.
            </p>
            """

            send_email(
                to_email=user.email,
                subject=f"Booking Confirmed! - {deal.origin} to {deal.destination}",
                html_content=html_content
            )

        except Exception as e:
            logger.error(f"Failed to send confirmation email: {e}")

    def _send_processing_notification_email(self, user, deal, booking):
        """Send email notifying customer their booking is being processed."""
        try:
            from email_service import send_email

            html_content = f"""
            <h2>Your Booking is Being Processed</h2>
            <p>Hi {user.name or 'there'},</p>
            <p>Your payment has been received and we're now processing your booking.</p>

            <div style="background: #fff3cd; padding: 20px; border-radius: 8px; margin: 20px 0;">
                <p><strong>Route:</strong> {deal.origin} → {deal.destination}</p>
                <p><strong>Date:</strong> {deal.departure_date}</p>
                <p><strong>Status:</strong> Processing</p>
            </div>

            <p>Our team is booking your flight at the best available price.
            You'll receive your confirmation within <strong>2-4 hours</strong>.</p>

            <p>You're saving <strong>${deal.user_savings_usd or 0:.2f}</strong> on this booking!</p>
            """

            send_email(
                to_email=user.email,
                subject=f"Booking in Progress - {deal.origin} to {deal.destination}",
                html_content=html_content
            )

        except Exception as e:
            logger.error(f"Failed to send processing notification: {e}")

    def _notify_agents_new_booking(self, booking, deal, user):
        """
        Notify agents about a new booking that needs manual processing.
        In production, this would send to Slack, internal queue, etc.
        """
        logger.info(f"[AGENT NOTIFICATION] New booking #{booking.id} requires manual processing")
        logger.info(f"  Deal: {deal.deal_id}")
        logger.info(f"  Route: {deal.origin} → {deal.destination}")
        logger.info(f"  Customer: {user.email}")
        logger.info(f"  Amount to pay airline: ${deal.arbitrage_price_usd:.2f}")

    def update_booking_confirmation(self, booking_id: int, confirmation_code: str,
                                   eticket_url: str = None) -> Dict[str, Any]:
        """
        Update a booking with confirmation details (used by agents or automated systems).

        Args:
            booking_id: The booking ID
            confirmation_code: Airline confirmation code
            eticket_url: URL to e-ticket PDF (optional)

        Returns:
            dict with result
        """
        from models import Booking

        booking = Booking.query.get(booking_id)
        if not booking:
            return {"success": False, "error": "Booking not found"}

        booking.confirmation_code = confirmation_code
        booking.status = BookingStatus.BOOKED.value
        booking.vendor_payment_status = VendorPaymentStatus.COMPLETED.value
        booking.booked_at = datetime.utcnow()

        if eticket_url:
            booking.eticket_url = eticket_url

        self.db.commit()

        # Send confirmation email
        from models import User, Deal
        user = User.query.get(booking.user_id)
        deal = Deal.query.get(booking.deal_id)

        if user and deal:
            self._send_booking_confirmation_email(user, deal, booking)

        return {
            "success": True,
            "booking_id": booking_id,
            "status": booking.status
        }

    def mark_ticket_sent(self, booking_id: int) -> Dict[str, Any]:
        """Mark that the e-ticket has been sent to customer."""
        from models import Booking

        booking = Booking.query.get(booking_id)
        if not booking:
            return {"success": False, "error": "Booking not found"}

        booking.eticket_sent = True
        booking.eticket_sent_at = datetime.utcnow()
        booking.status = BookingStatus.TICKET_SENT.value
        self.db.commit()

        return {"success": True}

    def complete_booking(self, booking_id: int) -> Dict[str, Any]:
        """Mark a booking as fully completed."""
        from models import Booking

        booking = Booking.query.get(booking_id)
        if not booking:
            return {"success": False, "error": "Booking not found"}

        booking.status = BookingStatus.COMPLETED.value
        booking.completed_at = datetime.utcnow()
        self.db.commit()

        return {"success": True}


# --- CONVENIENCE FUNCTIONS ---

def process_booking_fulfillment(deal, payment, user, db_session):
    """
    Main entry point for booking fulfillment after payment.

    Called by the payment success handler.
    """
    manager = BookingFulfillmentManager(db_session)
    return manager.create_booking(deal, payment, user)


def update_booking_with_confirmation(booking_id: int, confirmation_code: str,
                                    eticket_url: str = None, db_session=None):
    """
    Update a booking with airline confirmation.

    Used by agents or admin interface.
    """
    if db_session is None:
        from models import db
        db_session = db.session

    manager = BookingFulfillmentManager(db_session)
    return manager.update_booking_confirmation(booking_id, confirmation_code, eticket_url)


# --- CLI FOR TESTING ---

if __name__ == "__main__":
    print("MYSTES Booking Fulfillment System")
    print("=" * 50)
    print(f"Default fulfillment type: {FULFILLMENT_CONFIG['default_type']}")
    print(f"Self-service timeout: {FULFILLMENT_CONFIG['self_service_timeout_hours']} hours")
    print(f"Support email: {FULFILLMENT_CONFIG['support_email']}")
