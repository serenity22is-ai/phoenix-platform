"""
MYSTES Email Service

Handles all email functionality:
- Email verification
- Password reset
- Price alerts
- Booking confirmations

Supports multiple backends:
- SMTP (Gmail, etc.)
- SendGrid
- Mailgun
"""

import os
import re
import secrets
from datetime import datetime, timedelta
from typing import Optional
from threading import Thread
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Email configuration
# Default sender MUST match MAIL_USERNAME (the authenticated Gmail account)
# Sending from a different domain (e.g. noreply@mystes.app) via Gmail SMTP
# causes SPF/DKIM failures → recipient servers reject with DNS errors.
_mail_username = os.environ.get("MAIL_USERNAME", "")
_default_sender = f"MYSTES <{_mail_username}>" if _mail_username else "MYSTES <noreply@mystes.app>"

EMAIL_CONFIG = {
    "enabled": os.environ.get("MAIL_ENABLED", "false").lower() == "true",
    "server": os.environ.get("MAIL_SERVER", "smtp.gmail.com"),
    "port": int(os.environ.get("MAIL_PORT", 587)),
    "use_tls": os.environ.get("MAIL_USE_TLS", "true").lower() == "true",
    "username": _mail_username,
    "password": os.environ.get("MAIL_PASSWORD"),
    "sender": os.environ.get("MAIL_DEFAULT_SENDER", _default_sender),
    "base_url": os.environ.get("BASE_URL", "http://localhost:5001"),
}


def _extract_email(addr: str) -> str:
    """Extract bare email from 'Name <email>' format for SMTP envelope."""
    match = re.search(r'<([^>]+)>', addr)
    return match.group(1) if match else addr


def generate_token(length: int = 32) -> str:
    """Generate a secure random token."""
    return secrets.token_urlsafe(length)


def send_email_async(app, msg_data: dict):
    """Send email in background thread."""
    with app.app_context():
        try:
            send_email_smtp(
                to=msg_data["to"],
                subject=msg_data["subject"],
                html_body=msg_data["html"],
                text_body=msg_data.get("text")
            )
        except Exception as e:
            print(f"Failed to send email: {e}")


def send_email_smtp(to: str, subject: str, html_body: str, text_body: str = None) -> bool:
    """
    Send email via SMTP.

    Args:
        to: Recipient email address
        subject: Email subject
        html_body: HTML content
        text_body: Plain text content (optional)

    Returns:
        True if sent successfully
    """
    if not EMAIL_CONFIG["enabled"]:
        print(f"[EMAIL DISABLED] Would send to {to}: {subject}")
        return True

    if not EMAIL_CONFIG["username"] or not EMAIL_CONFIG["password"]:
        print(f"[EMAIL NOT CONFIGURED] Would send to {to}: {subject}")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = EMAIL_CONFIG["sender"]
        msg["To"] = to

        if text_body:
            msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(EMAIL_CONFIG["server"], EMAIL_CONFIG["port"]) as server:
            if EMAIL_CONFIG["use_tls"]:
                server.starttls()
            server.login(EMAIL_CONFIG["username"], EMAIL_CONFIG["password"])
            # Use bare email for SMTP envelope (MAIL FROM) — not "Name <email>" format
            envelope_sender = _extract_email(EMAIL_CONFIG["sender"])
            server.sendmail(envelope_sender, to, msg.as_string())

        print(f"[EMAIL SENT] To: {to}, Subject: {subject}")
        return True

    except Exception as e:
        print(f"[EMAIL ERROR] {e}")
        return False


def send_verification_email(to: str, token: str, name: str = None) -> bool:
    """Send email verification link."""
    verify_url = f"{EMAIL_CONFIG['base_url']}/verify-email/{token}"
    greeting = f"Hi {name}," if name else "Hi,"

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #f5f7fa; padding: 40px; }}
            .container {{ max-width: 500px; margin: 0 auto; background: white; border-radius: 8px; padding: 40px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            .logo {{ color: #4361ee; font-size: 24px; font-weight: bold; margin-bottom: 20px; }}
            .button {{ display: inline-block; background: #4361ee; color: white; padding: 12px 30px; text-decoration: none; border-radius: 6px; margin: 20px 0; }}
            .footer {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid #eee; font-size: 12px; color: #666; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="logo">MYSTES</div>
            <p>{greeting}</p>
            <p>Thanks for signing up! Please verify your email address to complete your registration.</p>
            <a href="{verify_url}" class="button">Verify Email</a>
            <p style="font-size: 14px; color: #666;">Or copy this link: {verify_url}</p>
            <p>This link expires in 24 hours.</p>
            <div class="footer">
                <p>If you didn't create an account, you can safely ignore this email.</p>
                <p>MYSTES - Save money on international flights</p>
            </div>
        </div>
    </body>
    </html>
    """

    text = f"""
    {greeting}

    Thanks for signing up for MYSTES!

    Please verify your email by clicking this link:
    {verify_url}

    This link expires in 24 hours.

    If you didn't create an account, you can safely ignore this email.
    """

    return send_email_smtp(to, "Verify your MYSTES account", html, text)


def send_password_reset_email(to: str, token: str, name: str = None) -> bool:
    """Send password reset link."""
    reset_url = f"{EMAIL_CONFIG['base_url']}/reset-password/{token}"
    greeting = f"Hi {name}," if name else "Hi,"

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #f5f7fa; padding: 40px; }}
            .container {{ max-width: 500px; margin: 0 auto; background: white; border-radius: 8px; padding: 40px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            .logo {{ color: #4361ee; font-size: 24px; font-weight: bold; margin-bottom: 20px; }}
            .button {{ display: inline-block; background: #4361ee; color: white; padding: 12px 30px; text-decoration: none; border-radius: 6px; margin: 20px 0; }}
            .footer {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid #eee; font-size: 12px; color: #666; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="logo">MYSTES</div>
            <p>{greeting}</p>
            <p>We received a request to reset your password. Click the button below to choose a new password.</p>
            <a href="{reset_url}" class="button">Reset Password</a>
            <p style="font-size: 14px; color: #666;">Or copy this link: {reset_url}</p>
            <p>This link expires in 1 hour.</p>
            <div class="footer">
                <p>If you didn't request a password reset, you can safely ignore this email.</p>
                <p>MYSTES - Save money on international flights</p>
            </div>
        </div>
    </body>
    </html>
    """

    text = f"""
    {greeting}

    We received a request to reset your MYSTES password.

    Click this link to reset your password:
    {reset_url}

    This link expires in 1 hour.

    If you didn't request this, you can safely ignore this email.
    """

    return send_email_smtp(to, "Reset your MYSTES password", html, text)


def send_price_alert_email(to: str, deals: list, name: str = None) -> bool:
    """Send price alert notification."""
    greeting = f"Hi {name}," if name else "Hi,"

    deals_html = ""
    for deal in deals:
        deals_html += f"""
        <div style="border: 1px solid #eee; border-radius: 6px; padding: 15px; margin: 10px 0;">
            <strong>{deal.get('route', 'N/A')}</strong> - {deal.get('airline', 'N/A')}<br>
            <span style="color: #0f9d58; font-weight: bold;">Save ${deal.get('savings', 0):.2f}</span>
            ({deal.get('savings_pct', 0):.0f}% off)<br>
            <small>Book from {deal.get('market', 'JP')} market: ${deal.get('price', 0):.2f}</small>
        </div>
        """

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #f5f7fa; padding: 40px; }}
            .container {{ max-width: 500px; margin: 0 auto; background: white; border-radius: 8px; padding: 40px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            .logo {{ color: #4361ee; font-size: 24px; font-weight: bold; margin-bottom: 20px; }}
            .button {{ display: inline-block; background: #4361ee; color: white; padding: 12px 30px; text-decoration: none; border-radius: 6px; margin: 20px 0; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="logo">MYSTES</div>
            <p>{greeting}</p>
            <p>Great news! We found some deals matching your price alerts:</p>
            {deals_html}
            <a href="{EMAIL_CONFIG['base_url']}/deals" class="button">View All Deals</a>
        </div>
    </body>
    </html>
    """

    return send_email_smtp(to, f"Price Alert: {len(deals)} deals found!", html)


def send_booking_confirmation_email(to: str, booking: dict, name: str = None) -> bool:
    """Send booking confirmation."""
    greeting = f"Hi {name}," if name else "Hi,"

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #f5f7fa; padding: 40px; }}
            .container {{ max-width: 500px; margin: 0 auto; background: white; border-radius: 8px; padding: 40px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            .logo {{ color: #4361ee; font-size: 24px; font-weight: bold; margin-bottom: 20px; }}
            .details {{ background: #f0f4ff; padding: 20px; border-radius: 6px; margin: 20px 0; }}
            .savings {{ color: #0f9d58; font-size: 24px; font-weight: bold; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="logo">MYSTES</div>
            <p>{greeting}</p>
            <p>Your payment has been verified! Here are your booking details:</p>
            <div class="details">
                <p><strong>Route:</strong> {booking.get('route', 'N/A')}</p>
                <p><strong>Airline:</strong> {booking.get('airline', 'N/A')}</p>
                <p><strong>Date:</strong> {booking.get('date', 'N/A')}</p>
                <p><strong>Platform Fee Paid:</strong> {booking.get('fee_xrp', 0):.2f} XRP</p>
                <p class="savings">You saved: ${booking.get('savings', 0):.2f}</p>
            </div>
            <p>You can now access the airline booking page to complete your reservation.</p>
            <a href="{EMAIL_CONFIG['base_url']}/book/{booking.get('deal_id', '')}" style="display: inline-block; background: #4361ee; color: white; padding: 12px 30px; text-decoration: none; border-radius: 6px;">Complete Booking</a>
        </div>
    </body>
    </html>
    """

    return send_email_smtp(to, "MYSTES - Payment Verified!", html)


def send_email(to_email: str, subject: str, html_content: str, text_content: str = None) -> bool:
    """
    Generic email sending function.

    Args:
        to_email: Recipient email address
        subject: Email subject line
        html_content: HTML body content
        text_content: Plain text content (optional)

    Returns:
        True if sent successfully
    """
    # Wrap HTML content in standard template
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #f5f7fa; padding: 40px; }}
            .container {{ max-width: 600px; margin: 0 auto; background: white; border-radius: 8px; padding: 40px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            .logo {{ color: #4361ee; font-size: 24px; font-weight: bold; margin-bottom: 20px; }}
            .footer {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid #eee; font-size: 12px; color: #666; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="logo">MYSTES</div>
            {html_content}
            <div class="footer">
                <p>MYSTES - Save money on international flights</p>
                <p><a href="{EMAIL_CONFIG['base_url']}">Visit MYSTES</a></p>
            </div>
        </div>
    </body>
    </html>
    """

    return send_email_smtp(to_email, subject, html, text_content)


def send_booking_confirmation(user_email: str, deal, booking) -> bool:
    """
    Send booking confirmation after payment is verified.

    Args:
        user_email: Customer email
        deal: Deal model instance
        booking: Booking model instance

    Returns:
        True if sent successfully
    """
    # Build flight legs info
    legs_html = ""
    if deal.is_multi_leg and deal.flight_legs:
        import json
        try:
            legs = json.loads(deal.flight_legs) if isinstance(deal.flight_legs, str) else deal.flight_legs
            for i, leg in enumerate(legs):
                legs_html += f"""
                <div style="background: #f8f9fa; padding: 12px; border-radius: 6px; margin: 8px 0;">
                    <strong>Leg {i+1}:</strong> {leg.get('route', 'N/A')}<br>
                    <span style="color: #666;">Date: {leg.get('date', 'N/A')} | Market: {leg.get('cheapest_market', 'N/A')}</span>
                </div>
                """
        except:
            pass
    else:
        legs_html = f"""
        <div style="background: #f8f9fa; padding: 12px; border-radius: 6px;">
            <strong>{deal.airline or 'Flight'} {deal.flight_number or ''}</strong><br>
            <span>{deal.origin} → {deal.destination}</span><br>
            <span style="color: #666;">Date: {deal.departure_date}</span>
        </div>
        """

    html_content = f"""
    <h2 style="color: #28a745;">Payment Confirmed!</h2>
    <p>Great news! Your payment has been verified and your booking is being processed.</p>

    <div style="background: #d4edda; border: 1px solid #c3e6cb; padding: 20px; border-radius: 8px; margin: 20px 0;">
        <h3 style="margin-top: 0; color: #155724;">Booking Reference: #{booking.id}</h3>
        <p style="margin-bottom: 0;">Status: <strong>{booking.status.replace('_', ' ').title()}</strong></p>
    </div>

    <h3>Flight Details</h3>
    {legs_html}

    <div style="margin-top: 20px;">
        <p><strong>Total Paid:</strong> ${(deal.arbitrage_price_usd or 0) + (deal.platform_fee_usd or 0):.2f}</p>
        <p style="color: #28a745;"><strong>Your Savings:</strong> ${deal.gross_savings_usd or deal.user_savings_usd or 0:.2f}</p>
    </div>

    <h3>Next Steps</h3>
    <p>Click the button below to access your booking page and complete your reservation:</p>

    <a href="{EMAIL_CONFIG['base_url']}/book/{deal.deal_id}"
       style="display: inline-block; background: #4361ee; color: white; padding: 15px 30px;
              text-decoration: none; border-radius: 8px; font-weight: bold; margin: 15px 0;">
        Complete Your Booking
    </a>

    <p style="color: #666; font-size: 14px; margin-top: 20px;">
        Need help? Reply to this email or contact our support team.
    </p>
    """

    return send_email(
        to_email=user_email,
        subject=f"Payment Confirmed - {deal.origin} to {deal.destination}",
        html_content=html_content
    )


def send_booking_instructions(user_email: str, deal, booking_urls: list) -> bool:
    """
    Send self-service booking instructions.

    Args:
        user_email: Customer email
        deal: Deal model instance
        booking_urls: List of booking URL dicts

    Returns:
        True if sent successfully
    """
    # Build booking links
    links_html = ""
    for url_info in booking_urls:
        links_html += f"""
        <div style="background: #f8f9fa; padding: 15px; border-radius: 8px; margin: 10px 0;">
            <strong>Leg {url_info.get('leg', 1)}: {url_info.get('route', 'N/A')}</strong><br>
            <span style="color: #666;">Date: {url_info.get('date', 'N/A')} | Market: {url_info.get('market', 'N/A')}</span><br>
            <a href="{EMAIL_CONFIG['base_url']}{url_info.get('proxy_url', '')}"
               style="display: inline-block; margin-top: 10px; background: #4361ee; color: white;
                      padding: 10px 20px; text-decoration: none; border-radius: 5px;">
                Book This Flight
            </a>
        </div>
        """

    html_content = f"""
    <h2>Complete Your Flight Booking</h2>
    <p>Your payment has been verified! Please complete your booking within 24 hours.</p>

    <h3>Your Flights</h3>
    {links_html}

    <div style="background: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 8px; margin: 20px 0;">
        <h4 style="margin-top: 0; color: #856404;">Important Instructions</h4>
        <ol style="margin-bottom: 0; padding-left: 20px;">
            <li>Click the booking links above (they'll open through our proxy)</li>
            <li>The prices shown will reflect the regional market discount</li>
            <li>Complete the booking using your own credit card on the airline's site</li>
            <li>Save your confirmation code</li>
        </ol>
    </div>

    <p style="color: #28a745; font-weight: bold;">
        You're saving ${deal.gross_savings_usd or deal.user_savings_usd or 0:.2f} on this booking!
    </p>

    <p style="color: #666; font-size: 14px;">
        If you have any issues, reply to this email or contact support.
    </p>
    """

    return send_email(
        to_email=user_email,
        subject=f"Complete Your Booking - {deal.origin} to {deal.destination}",
        html_content=html_content
    )


def send_ticket_confirmation(user_email: str, deal, booking, confirmation_code: str) -> bool:
    """
    Send final ticket confirmation with airline confirmation code.

    Args:
        user_email: Customer email
        deal: Deal model instance
        booking: Booking model instance
        confirmation_code: Airline confirmation code

    Returns:
        True if sent successfully
    """
    # Build itinerary rows from segments
    segments = deal.get_segments() if hasattr(deal, 'get_segments') else []
    itinerary_html = ""
    if segments:
        for seg in segments:
            dep = seg.get("departure_airport", deal.origin or "")
            arr = seg.get("arrival_airport", deal.destination or "")
            carrier = seg.get("carrier_name") or seg.get("carrier", deal.airline or "")
            fnum = seg.get("flight_number", "")
            itinerary_html += f"""
            <tr>
                <td style="padding: 8px; border-bottom: 1px solid #eee;">{carrier} {fnum}</td>
                <td style="padding: 8px; border-bottom: 1px solid #eee;">{dep} → {arr}</td>
            </tr>"""
    else:
        itinerary_html = f"""
        <tr>
            <td style="padding: 8px;">{deal.airline or 'N/A'} {deal.flight_number or ''}</td>
            <td style="padding: 8px;">{deal.origin} → {deal.destination}</td>
        </tr>"""

    # Get manage booking URL
    try:
        from main import get_manage_booking_url
        manage_url = get_manage_booking_url(deal.airline or "")
    except Exception:
        manage_url = "https://www.google.com/travel/flights"

    # Fare detail tags
    fare_tags = []
    if getattr(deal, 'fare_family', None):
        fare_tags.append(deal.fare_family)
    if getattr(deal, 'baggage_info', None):
        bag = deal.baggage_info
        fare_tags.append("No checked bag" if bag == "0PC" else bag)
    if getattr(deal, 'seat_selection_available', None):
        fare_tags.append("Seat selection available")
    if getattr(deal, 'flight_cancellation_policy', None) == 'NOT_POSSIBLE':
        fare_tags.append("Non-refundable")
    fare_line = " · ".join(fare_tags) if fare_tags else ""

    savings = deal.user_savings_usd or deal.gross_savings_usd or 0

    html_content = f"""
    <h2 style="color: #28a745;">Your Ticket is Confirmed!</h2>

    <div style="background: #d4edda; border: 1px solid #c3e6cb; padding: 25px; border-radius: 8px; margin: 20px 0; text-align: center;">
        <p style="margin: 0; font-size: 14px; color: #155724;">Confirmation Code</p>
        <p style="margin: 10px 0; font-size: 32px; font-weight: bold; color: #155724; letter-spacing: 4px;">
            {confirmation_code}
        </p>
    </div>

    <h3>Flight Itinerary</h3>
    <table style="width: 100%; border-collapse: collapse; background: #f8f9fa; border-radius: 8px;">
        <tr style="background: #e9ecef;">
            <th style="padding: 10px; text-align: left;">Flight</th>
            <th style="padding: 10px; text-align: left;">Route</th>
        </tr>
        {itinerary_html}
    </table>
    <p style="color: #666; font-size: 13px; margin-top: 8px;">
        {deal.departure_date or ''} · {deal.duration or ''}
        {(' · ' + fare_line) if fare_line else ''}
    </p>

    {'<p style="color: #28a745; font-size: 18px; margin-top: 15px;"><strong>You saved $' + f"{savings:.0f}" + ' with MYSTES!</strong></p>' if savings else ''}

    <h3>What's Next</h3>
    <ol style="line-height: 2;">
        <li><strong>Visit <a href="{manage_url}">{deal.airline or 'the airline'}'s website</a></strong> or download their app</li>
        <li>Go to <strong>"Manage Booking"</strong> and enter your confirmation code + last name</li>
        <li><strong>Select your seats</strong> and add checked bags if needed</li>
        <li><strong>Check in online</strong> 24 hours before departure</li>
    </ol>

    <div style="text-align: center; margin: 25px 0;">
        <a href="{manage_url}" style="display: inline-block; padding: 12px 30px; background: #28a745; color: white; text-decoration: none; border-radius: 6px; font-weight: bold;">
            Manage Your Booking
        </a>
    </div>

    <p style="color: #666; font-size: 14px;">
        Have a great flight! Thank you for using MYSTES.
    </p>
    """

    return send_email(
        to_email=user_email,
        subject=f"Ticket Confirmed: {confirmation_code} - {deal.origin} to {deal.destination}",
        html_content=html_content
    )


# --- ESCROW & REWARDS EMAILS (Build #170) ---

def send_escrow_reminder(to: str, points_amount: int, booking_ref: str,
                          days_remaining: int, claim_url: str = None) -> bool:
    """Remind guest to create account and claim escrowed points."""
    claim_url = claim_url or "https://mystes.app/register"
    html = f"""
    <div style="max-width:600px;margin:0 auto;font-family:'Outfit',Arial,sans-serif;background:#f8f9fa;padding:30px;">
        <div style="text-align:center;margin-bottom:25px;">
            <h1 style="font-family:'Cinzel',serif;color:#1a1a2e;margin:0;">MYSTES</h1>
        </div>
        <div style="background:white;border-radius:12px;padding:30px;">
            <h2 style="color:#7c3aed;margin:0 0 15px;">You have {points_amount:,} points waiting!</h2>
            <p style="color:#333;line-height:1.6;">
                You earned <strong>{points_amount:,} MYSTES points</strong> from your flight booking
                (ref: {booking_ref}). Create a free account to claim them before they expire!
            </p>
            <p style="color:#666;font-size:14px;">
                <strong>{days_remaining} days remaining</strong> to claim your points.
                Points are worth ${points_amount * 0.001:.2f} toward your next booking.
            </p>
            <div style="text-align:center;margin:25px 0;">
                <a href="{claim_url}" style="background:linear-gradient(135deg,#7c3aed,#5b21b6);color:white;padding:14px 40px;border-radius:10px;text-decoration:none;font-weight:700;font-size:16px;">
                    Claim Your Points
                </a>
            </div>
            <p style="color:#999;font-size:12px;text-align:center;">
                Your points will expire if not claimed within {days_remaining} days.
            </p>
        </div>
    </div>
    """
    return send_email(to, f"You have {points_amount:,} MYSTES points waiting!", html)


def send_referral_notification(to: str, name: str, referee_action: str,
                                points_earned: int) -> bool:
    """Notify referrer when their referral completes a milestone."""
    greeting = f"Hi {name}," if name else "Hi,"
    html = f"""
    <div style="max-width:600px;margin:0 auto;font-family:'Outfit',Arial,sans-serif;background:#f8f9fa;padding:30px;">
        <div style="text-align:center;margin-bottom:25px;">
            <h1 style="font-family:'Cinzel',serif;color:#1a1a2e;margin:0;">MYSTES</h1>
        </div>
        <div style="background:white;border-radius:12px;padding:30px;">
            <h2 style="color:#14b8a6;margin:0 0 15px;">You earned {points_earned:,} points!</h2>
            <p style="color:#333;line-height:1.6;">
                {greeting} Your referral just {referee_action}!
                You've earned <strong>{points_earned:,} MYSTES points</strong>.
            </p>
            <div style="background:#f5f3ff;border-radius:8px;padding:15px;margin:20px 0;">
                <strong style="color:#7c3aed;">Points earned: +{points_earned:,}</strong><br>
                <span style="color:#666;font-size:13px;">Worth ${points_earned * 0.001:.2f} toward your next booking</span>
            </div>
            <div style="text-align:center;margin:20px 0;">
                <a href="https://mystes.app/rewards" style="background:#7c3aed;color:white;padding:12px 30px;border-radius:8px;text-decoration:none;font-weight:600;">
                    View Rewards
                </a>
            </div>
        </div>
    </div>
    """
    return send_email(to, f"You earned {points_earned:,} points from a referral!", html)


def send_welcome_points_email(to: str, name: str, points: int) -> bool:
    """Welcome email when user creates account and claims escrow points."""
    greeting = f"Hi {name}!" if name else "Welcome!"
    html = f"""
    <div style="max-width:600px;margin:0 auto;font-family:'Outfit',Arial,sans-serif;background:#f8f9fa;padding:30px;">
        <div style="text-align:center;margin-bottom:25px;">
            <h1 style="font-family:'Cinzel',serif;color:#1a1a2e;margin:0;">MYSTES</h1>
        </div>
        <div style="background:white;border-radius:12px;padding:30px;">
            <h2 style="color:#7c3aed;margin:0 0 15px;">{greeting} Welcome to MYSTES!</h2>
            <p style="color:#333;line-height:1.6;">
                You've claimed <strong>{points:,} MYSTES points</strong> from your booking.
                Use them to save even more on your next flight!
            </p>
            <div style="background:linear-gradient(135deg,#7c3aed,#5b21b6);color:white;border-radius:12px;padding:20px;margin:20px 0;text-align:center;">
                <div style="font-size:36px;font-weight:bold;">{points:,}</div>
                <div style="opacity:0.8;">Points Balance (${points * 0.001:.2f} value)</div>
            </div>
            <p style="color:#666;font-size:14px;">
                <strong>How to earn more:</strong><br>
                Book flights (+10 pts per $1) | Refer friends (+2,000-10,000 pts) | Subscribe to Travel+ (1.5x multiplier)
            </p>
        </div>
    </div>
    """
    return send_email(to, f"Welcome! You have {points:,} MYSTES points", html)


# --- P2P NETWORK EMAILS ---

def send_p2p_escrow_locked(to: str, name: str = None, transaction: dict = None) -> bool:
    """Notify buyer that their RLUSD is locked in escrow."""
    transaction = transaction or {}
    greeting = f"Hi {name}," if name else "Hi,"

    html_content = f"""
    <h2>Escrow Locked - Your Funds Are Secure</h2>
    <p>{greeting}</p>
    <p>Your RLUSD has been locked in escrow on the XRPL ledger for your P2P booking.</p>

    <div style="background: #e8f5e9; border: 1px solid #c8e6c9; padding: 20px; border-radius: 8px; margin: 20px 0;">
        <h3 style="margin-top: 0; color: #2e7d32;">Escrow Details</h3>
        <p><strong>Amount Locked:</strong> {transaction.get('total_rlusd', 0):.2f} RLUSD</p>
        <p><strong>Route:</strong> {transaction.get('origin', '')} → {transaction.get('destination', '')}</p>
        <p><strong>Market:</strong> {transaction.get('target_market', '')} (savings: ${transaction.get('savings_usd', 0):.2f})</p>
        <p><strong>Escrow ID:</strong> {transaction.get('escrow_id', '')}</p>
    </div>

    <h3>What Happens Next</h3>
    <ol>
        <li>A helper in {transaction.get('target_market', 'the target market')} will verify the escrow on-chain</li>
        <li>Mystes will automate the purchase through the helper's browser</li>
        <li>Once confirmed, your escrow releases to the helper and platform</li>
        <li>You receive your booking confirmation</li>
    </ol>

    <p style="color: #666; font-size: 14px;">
        Your funds are protected by XRPL smart contract escrow. If the booking fails,
        the escrow cancels and your RLUSD is returned automatically.
    </p>
    """

    return send_email(to, "Escrow Locked - P2P Booking in Progress", html_content)


def send_p2p_helper_matched(to: str, name: str = None, transaction: dict = None) -> bool:
    """Notify helper they've been matched to a transaction."""
    transaction = transaction or {}
    greeting = f"Hi {name}," if name else "Hi,"

    html_content = f"""
    <h2>New P2P Booking Assignment</h2>
    <p>{greeting}</p>
    <p>You've been matched to a new P2P booking! A buyer needs your help purchasing a flight in your market.</p>

    <div style="background: #fff3e0; border: 1px solid #ffe0b2; padding: 20px; border-radius: 8px; margin: 20px 0;">
        <h3 style="margin-top: 0; color: #e65100;">Transaction Details</h3>
        <p><strong>Route:</strong> {transaction.get('origin', '')} → {transaction.get('destination', '')}</p>
        <p><strong>Date:</strong> {transaction.get('departure_date', '')}</p>
        <p><strong>Airline:</strong> {transaction.get('airline', '')}</p>
        <p><strong>Your Earning:</strong> {transaction.get('helper_earning_rlusd', 0):.2f} RLUSD</p>
        <p><strong>Escrow Amount:</strong> {transaction.get('total_rlusd', 0):.2f} RLUSD (locked on-chain)</p>
    </div>

    <h3>Next Steps</h3>
    <ol>
        <li>Verify the escrow is locked on-chain (check the XRPL explorer)</li>
        <li>Accept the transaction in your Mystes dashboard</li>
        <li>Launch the Mystes Helper app to connect your browser</li>
        <li>Mystes will automate the purchase - you just watch</li>
        <li>Escrow releases to your wallet on confirmation</li>
    </ol>

    <p style="color: #2e7d32; font-weight: bold;">
        You'll earn {transaction.get('helper_earning_rlusd', 0):.2f} RLUSD for this transaction!
    </p>
    """

    return send_email(to, f"New P2P Booking - Earn {transaction.get('helper_earning_rlusd', 0):.2f} RLUSD", html_content)


def send_p2p_booking_confirmed(to: str, name: str = None, transaction: dict = None) -> bool:
    """Notify buyer that the P2P booking is confirmed."""
    transaction = transaction or {}
    greeting = f"Hi {name}," if name else "Hi,"

    html_content = f"""
    <h2 style="color: #2e7d32;">P2P Booking Confirmed!</h2>
    <p>{greeting}</p>
    <p>Your flight has been booked through the Mystes P2P network!</p>

    <div style="background: #e8f5e9; border: 1px solid #c8e6c9; padding: 25px; border-radius: 8px; margin: 20px 0; text-align: center;">
        <p style="margin: 0; font-size: 14px; color: #2e7d32;">Confirmation Code</p>
        <p style="margin: 10px 0; font-size: 28px; font-weight: bold; color: #1b5e20; letter-spacing: 2px;">
            {transaction.get('confirmation_code', 'N/A')}
        </p>
    </div>

    <div style="background: #f5f5f5; padding: 20px; border-radius: 8px; margin: 20px 0;">
        <h3 style="margin-top: 0;">Flight Details</h3>
        <p><strong>Route:</strong> {transaction.get('origin', '')} → {transaction.get('destination', '')}</p>
        <p><strong>Date:</strong> {transaction.get('departure_date', '')}</p>
        <p><strong>Airline:</strong> {transaction.get('airline', '')}</p>
        <p style="color: #2e7d32; font-size: 18px; font-weight: bold;">
            You saved ${transaction.get('savings_usd', 0):.2f} with Mystes P2P!
        </p>
    </div>

    <h3>What's Next</h3>
    <ul>
        <li>Check your email for the e-ticket from {transaction.get('airline', 'the airline')}</li>
        <li>Use the confirmation code above to manage your booking</li>
        <li>Your RLUSD escrow has been released to the helper and platform</li>
    </ul>
    """

    return send_email(
        to,
        f"Booking Confirmed: {transaction.get('confirmation_code', '')} - "
        f"{transaction.get('origin', '')} to {transaction.get('destination', '')}",
        html_content,
    )


def send_p2p_helper_payment(to: str, name: str = None, transaction: dict = None) -> bool:
    """Notify helper that escrow has released and they've been paid."""
    transaction = transaction or {}
    greeting = f"Hi {name}," if name else "Hi,"

    html_content = f"""
    <h2 style="color: #2e7d32;">Payment Received!</h2>
    <p>{greeting}</p>
    <p>The P2P booking has been confirmed and your RLUSD payment has been released from escrow.</p>

    <div style="background: #e8f5e9; border: 1px solid #c8e6c9; padding: 25px; border-radius: 8px; margin: 20px 0; text-align: center;">
        <p style="margin: 0; font-size: 14px; color: #2e7d32;">You Earned</p>
        <p style="margin: 10px 0; font-size: 28px; font-weight: bold; color: #1b5e20;">
            +{transaction.get('earning_rlusd', 0):.2f} RLUSD
        </p>
    </div>

    <div style="background: #f5f5f5; padding: 20px; border-radius: 8px; margin: 20px 0;">
        <h3 style="margin-top: 0;">Payment Breakdown</h3>
        <p><strong>Ticket Reimbursement:</strong> {transaction.get('reimbursement_rlusd', 0):.2f} RLUSD</p>
        <p><strong>Your Earning (cut):</strong> {transaction.get('earning_rlusd', 0):.2f} RLUSD</p>
        <p><strong>Total Received:</strong> {transaction.get('total_rlusd', 0):.2f} RLUSD</p>
        <p><strong>Transaction:</strong> {transaction.get('transaction_id', '')}</p>
    </div>

    <p>Your RLUSD is now in your connected wallet. You can:</p>
    <ul>
        <li>Use RLUSD for your own Mystes flights</li>
        <li>Convert to XRP on the XRPL DEX</li>
        <li>Cash out via Coinbase Commerce</li>
    </ul>

    <p>Thanks for being part of the Citizen Data Network!</p>
    """

    return send_email(to, f"Payment: +{transaction.get('earning_rlusd', 0):.2f} RLUSD earned", html_content)


def send_p2p_transaction_failed(to: str, name: str = None, transaction: dict = None) -> bool:
    """Notify buyer that the P2P transaction failed."""
    transaction = transaction or {}
    greeting = f"Hi {name}," if name else "Hi,"

    html_content = f"""
    <h2>P2P Booking Update</h2>
    <p>{greeting}</p>
    <p>Unfortunately, your P2P booking could not be completed.</p>

    <div style="background: #ffebee; border: 1px solid #ffcdd2; padding: 20px; border-radius: 8px; margin: 20px 0;">
        <p><strong>Route:</strong> {transaction.get('origin', '')} → {transaction.get('destination', '')}</p>
        <p><strong>Reason:</strong> {transaction.get('reason', 'Booking could not be completed')}</p>
    </div>

    <h3>Your Funds</h3>
    <p>Your RLUSD escrow will be automatically returned to your wallet once the
    escrow timeout expires. No action needed on your part — the XRPL smart contract
    handles the refund automatically.</p>

    <h3>What You Can Do</h3>
    <ul>
        <li>Try the booking again (another helper may be available)</li>
        <li>Use System 1 (proxy booking) as an alternative</li>
        <li>Contact support if you need assistance</li>
    </ul>

    <p style="color: #666; font-size: 14px;">
        We apologize for the inconvenience. Your funds are always protected by on-chain escrow.
    </p>
    """

    return send_email(to, f"P2P Booking Update - {transaction.get('origin', '')} to {transaction.get('destination', '')}", html_content)


def send_p2p_escrow_refunded(to: str, name: str = None, amount_rlusd: float = 0) -> bool:
    """Notify buyer that their escrow has been refunded."""
    greeting = f"Hi {name}," if name else "Hi,"

    html_content = f"""
    <h2>Escrow Refunded</h2>
    <p>{greeting}</p>
    <p>Your RLUSD escrow has been cancelled and the funds returned to your wallet.</p>

    <div style="background: #e3f2fd; border: 1px solid #bbdefb; padding: 25px; border-radius: 8px; margin: 20px 0; text-align: center;">
        <p style="margin: 0; font-size: 14px; color: #1565c0;">Refunded</p>
        <p style="margin: 10px 0; font-size: 28px; font-weight: bold; color: #0d47a1;">
            {amount_rlusd:.2f} RLUSD
        </p>
    </div>

    <p>The RLUSD has been returned to your connected XRPL wallet. You can verify
    the transaction on the XRPL explorer.</p>

    <p style="color: #666; font-size: 14px;">
        Ready to try again? Search for flights and we'll find you the best deal.
    </p>
    """

    return send_email(to, f"Escrow Refunded: {amount_rlusd:.2f} RLUSD Returned", html_content)


# --- ANASTASiA DEV PORTAL EMAILS (Build #184) ---

def send_devportal_welcome(to: str, name: str = None) -> bool:
    """Welcome email for new APAi admin portal accounts."""
    greeting = f"Hi {name}!" if name else "Welcome!"
    html = f"""
    <div style="max-width:600px;margin:0 auto;font-family:'Outfit',Arial,sans-serif;background:#0d0d1a;padding:30px;">
        <div style="text-align:center;margin-bottom:25px;">
            <h1 style="font-family:'Cinzel',serif;color:#b388ff;margin:0;font-size:28px;">ANASTASiA</h1>
            <p style="color:#8a8278;font-size:12px;letter-spacing:3px;text-transform:uppercase;margin:4px 0;">APAi Admin Portal</p>
        </div>
        <div style="background:#1a1a2e;border:1px solid rgba(179,136,255,0.2);border-radius:12px;padding:30px;">
            <h2 style="color:#b388ff;margin:0 0 15px;">{greeting}</h2>
            <p style="color:#d0c8bc;line-height:1.6;">
                Your APAi admin portal account is ready. You now have access to
                ANASTASiA &mdash; your AI development platform.
            </p>
            <div style="background:rgba(179,136,255,0.08);border:1px solid rgba(179,136,255,0.2);border-radius:10px;padding:20px;margin:20px 0;">
                <p style="color:#e8dcc8;margin:0 0 8px;font-weight:600;">What you can do:</p>
                <ul style="color:#b0a89a;margin:0;padding-left:18px;line-height:1.8;">
                    <li>Build full-stack applications, APIs, and integrations</li>
                    <li>Write, review, and debug code in any language</li>
                    <li>Customize your turnkey OTA template</li>
                    <li>Manage your dev team and usage</li>
                </ul>
            </div>
            <div style="text-align:center;margin-top:25px;">
                <a href="{EMAIL_CONFIG['base_url']}/apai/admin/terminal"
                   style="background:linear-gradient(135deg,#7c3aed,#b388ff);color:#fff;padding:14px 32px;border-radius:8px;text-decoration:none;font-weight:600;display:inline-block;">
                    Open Terminal
                </a>
            </div>
        </div>
    </div>
    """
    return send_email(to, "Welcome to APAi Admin Portal", html)


def send_team_invitation_email(to: str, name: str = None, inviter_name: str = None,
                                temp_password: str = None, company: str = None) -> bool:
    """Send team member invitation email with temp password.

    Build #195 — APAi admin portal team invitations.
    Admin provisions team member, this email is sent with login credentials.
    """
    greeting = f"Hi {name}," if name else "Hi,"
    inviter_text = f"<strong>{inviter_name}</strong> has" if inviter_name else "Your team admin has"
    company_text = f" at <strong>{company}</strong>" if company else ""
    html = f"""
    <div style="max-width:600px;margin:0 auto;font-family:'Outfit',Arial,sans-serif;background:#0d0d1a;padding:30px;">
        <div style="text-align:center;margin-bottom:25px;">
            <h1 style="font-family:'Cinzel',serif;color:#b388ff;margin:0;font-size:28px;">ANASTASiA</h1>
            <p style="color:#8a8278;font-size:12px;letter-spacing:3px;text-transform:uppercase;margin:4px 0;">APAi Admin Portal</p>
        </div>
        <div style="background:#1a1a2e;border:1px solid rgba(179,136,255,0.2);border-radius:12px;padding:30px;">
            <h2 style="color:#b388ff;margin:0 0 15px;">{greeting}</h2>
            <p style="color:#d0c8bc;line-height:1.6;">
                {inviter_text} added you to their APAi dev team{company_text}.
                You now have access to the ANASTASiA development terminal.
            </p>
            <div style="background:rgba(179,136,255,0.08);border:1px solid rgba(179,136,255,0.2);border-radius:10px;padding:20px;margin:20px 0;">
                <p style="color:#e8dcc8;margin:0 0 8px;font-weight:600;">Your login credentials:</p>
                <p style="color:#b0a89a;margin:4px 0;">Email: <strong style="color:#e8dcc8;">{to}</strong></p>
                <p style="color:#b0a89a;margin:4px 0;">Temporary password: <strong style="color:#e8dcc8;">{temp_password}</strong></p>
                <p style="color:#f59e0b;font-size:0.85rem;margin-top:12px;">Please change your password after your first login.</p>
            </div>
            <div style="text-align:center;margin-top:25px;">
                <a href="{EMAIL_CONFIG['base_url']}/apai/admin/login"
                   style="background:linear-gradient(135deg,#7c3aed,#b388ff);color:#fff;padding:14px 32px;border-radius:8px;text-decoration:none;font-weight:600;display:inline-block;">
                    Log In to APAi
                </a>
            </div>
            <p style="color:#666;font-size:13px;margin-top:20px;text-align:center;">
                All queries count against your team's subscription pool.
            </p>
        </div>
    </div>
    """
    return send_email_smtp(to, "You've been added to an APAi dev team", html)


# --- Build #191: Social Notification Emails ---

def send_friend_request_email(to: str, from_name: str, to_name: str = None) -> bool:
    """Notify user of a new friend request."""
    greeting = f"Hi {to_name}," if to_name else "Hi,"
    html = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;max-width:500px;margin:0 auto;background:#0f0a19;border-radius:12px;padding:40px;color:#e2e8f0;">
        <div style="font-family:'Cinzel',serif;font-size:20px;color:#7c3aed;margin-bottom:20px;letter-spacing:4px;">MYSTES</div>
        <p>{greeting}</p>
        <p><strong>{from_name}</strong> sent you a friend request on MYSTES.</p>
        <p>Accept the request to start sharing trips, collections, and travel plans together.</p>
        <div style="text-align:center;margin:24px 0;">
            <a href="{EMAIL_CONFIG['base_url']}/friends"
               style="background:linear-gradient(135deg,#7c3aed,#a855f7);color:#fff;padding:14px 32px;border-radius:8px;text-decoration:none;font-weight:600;display:inline-block;">
                View Request
            </a>
        </div>
        <p style="color:#666;font-size:12px;margin-top:20px;">MYSTES KYRIOS LLC</p>
    </div>
    """
    return send_email_smtp(to, f"{from_name} wants to be your friend on MYSTES", html)


def send_trip_invite_email(to: str, inviter_name: str, trip_name: str, trip_id: int, to_name: str = None) -> bool:
    """Notify user of a trip planner invitation."""
    greeting = f"Hi {to_name}," if to_name else "Hi,"
    html = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;max-width:500px;margin:0 auto;background:#0f0a19;border-radius:12px;padding:40px;color:#e2e8f0;">
        <div style="font-family:'Cinzel',serif;font-size:20px;color:#7c3aed;margin-bottom:20px;letter-spacing:4px;">MYSTES</div>
        <p>{greeting}</p>
        <p><strong>{inviter_name}</strong> invited you to collaborate on a trip:</p>
        <div style="background:rgba(124,58,237,0.08);border:1px solid rgba(124,58,237,0.2);border-radius:10px;padding:20px;margin:16px 0;text-align:center;">
            <div style="font-family:'Cinzel',serif;font-size:18px;color:#e2e8f0;letter-spacing:2px;">{trip_name}</div>
        </div>
        <p>Join to add flights, hotels, activities, and more. Vote on options and plan together.</p>
        <div style="text-align:center;margin:24px 0;">
            <a href="{EMAIL_CONFIG['base_url']}/trips/{trip_id}"
               style="background:linear-gradient(135deg,#7c3aed,#a855f7);color:#fff;padding:14px 32px;border-radius:8px;text-decoration:none;font-weight:600;display:inline-block;">
                View Trip
            </a>
        </div>
        <p style="color:#666;font-size:12px;margin-top:20px;">MYSTES KYRIOS LLC</p>
    </div>
    """
    return send_email_smtp(to, f"You're invited to \"{trip_name}\" on MYSTES", html)


def send_collection_shared_email(to: str, sharer_name: str, collection_name: str, share_slug: str, to_name: str = None) -> bool:
    """Notify user when a collection is shared with them."""
    greeting = f"Hi {to_name}," if to_name else "Hi,"
    html = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;max-width:500px;margin:0 auto;background:#0f0a19;border-radius:12px;padding:40px;color:#e2e8f0;">
        <div style="font-family:'Cinzel',serif;font-size:20px;color:#7c3aed;margin-bottom:20px;letter-spacing:4px;">MYSTES</div>
        <p>{greeting}</p>
        <p><strong>{sharer_name}</strong> shared a travel collection with you:</p>
        <div style="background:rgba(20,184,166,0.08);border:1px solid rgba(20,184,166,0.2);border-radius:10px;padding:20px;margin:16px 0;text-align:center;">
            <div style="font-family:'Cinzel',serif;font-size:18px;color:#e2e8f0;letter-spacing:2px;">{collection_name}</div>
        </div>
        <div style="text-align:center;margin:24px 0;">
            <a href="{EMAIL_CONFIG['base_url']}/c/{share_slug}"
               style="background:linear-gradient(135deg,#14b8a6,#0d9488);color:#fff;padding:14px 32px;border-radius:8px;text-decoration:none;font-weight:600;display:inline-block;">
                View Collection
            </a>
        </div>
        <p style="color:#666;font-size:12px;margin-top:20px;">MYSTES KYRIOS LLC</p>
    </div>
    """
    return send_email_smtp(to, f"{sharer_name} shared \"{collection_name}\" with you", html)


def send_cancellation_email(to: str, to_name: str = None, booking_ref: str = "",
                            route_info: str = "", refund_amount: float = 0) -> bool:
    """Send booking cancellation confirmation email."""
    greeting = f"Hi {to_name}," if to_name else "Hi,"
    refund_line = f"<p>A refund of <strong>${refund_amount:.2f}</strong> will be returned to your original payment method within 5-10 business days.</p>" if refund_amount > 0 else ""
    html = f"""
    <div style="font-family:'Outfit',sans-serif;max-width:500px;margin:0 auto;background:#0a0612;color:#e2e8f0;padding:40px 30px;border-radius:16px;">
        <div style="font-family:'Cinzel',serif;font-size:20px;color:#7c3aed;margin-bottom:20px;letter-spacing:4px;">MYSTES</div>
        <p>{greeting}</p>
        <p>Your booking has been cancelled.</p>
        <div style="background:rgba(239,68,68,0.08);border:1px solid rgba(239,68,68,0.2);border-radius:10px;padding:20px;margin:16px 0;text-align:center;">
            <div style="font-size:12px;color:#999;text-transform:uppercase;letter-spacing:2px;margin-bottom:6px;">Cancelled Booking</div>
            <div style="font-family:monospace;font-size:22px;color:#f87171;letter-spacing:4px;">{booking_ref}</div>
            <div style="font-size:14px;color:#ccc;margin-top:8px;">{route_info}</div>
        </div>
        {refund_line}
        <div style="text-align:center;margin:24px 0;">
            <a href="{EMAIL_CONFIG['base_url']}/flights"
               style="background:linear-gradient(135deg,#7c3aed,#5b21b6);color:#fff;padding:14px 32px;border-radius:8px;text-decoration:none;font-weight:600;display:inline-block;">
                Search New Flights
            </a>
        </div>
        <p style="color:#666;font-size:12px;margin-top:20px;">MYSTES KYRIOS LLC</p>
    </div>
    """
    return send_email_smtp(to, "MYSTES — Booking Cancelled", html)
