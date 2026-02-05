"""
PHOENIX Proxy Server with Database & Authentication

Features:
- User registration and login with email verification
- XRP payment verification gate
- Deal caching in database
- Proxy to airline booking sites with translation
- Rate limiting and CSRF protection
- Price alerts

Run with: python3 server.py (development)
Run with: gunicorn -w 4 -b 0.0.0.0:5001 server:app (production)
"""

import os
import secrets
import logging
import json
from datetime import datetime, timedelta
from functools import wraps
from threading import Thread

from flask import Flask, request, Response, jsonify, redirect, render_template_string, url_for, flash, session, abort, send_from_directory
from flask_cors import CORS
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_wtf.csrf import CSRFProtect, CSRFError
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
import requests as http_requests
from urllib.parse import urljoin, urlparse, quote, unquote
import re

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Import from local modules
from models import (db, init_db, User, Deal, Payment, Booking, PriceAlert, Escrow,
                    HelperProfile, UserWallet, UserCard, P2PTransaction, P2PEscrow,
                    NodeConsentProfile, RevenueAllocation)
from translation import (
    translate_html, translate_text, translate_form_data,
    detect_language, detect_language_from_html,
    SUPPORTED_LANGUAGES, get_language_name, get_translation_script
)
from main import (
    compare_markets,
    fetch_flights_direct,
    extract_flights,
    generate_dates,
    get_xrp_price,
    verify_payment as verify_xrp_payment,
    calculate_deal,
    search_flight_number,
    search_with_direct_scraping,
    DIRECT_SCRAPER_AVAILABLE,
    MARKETS,
    DESTINATIONS,
    ORIGIN,
    START_DATE,
    END_DATE,
    DISPLAY_CURRENCY,
    XRPL_CONFIG,
)
from payments import (
    generate_payment_options,
    create_stripe_checkout_session,
    verify_stripe_session,
    create_coinbase_charge,
    verify_coinbase_charge,
    handle_coinbase_webhook,
    verify_payment,
    handle_stripe_webhook,
    PaymentMethod,
    PaymentStatus,
    PAYMENT_CONFIG,
    get_xrp_price as refresh_xrp_price,
)
from search import (
    search_global,
    search_round_trip,
    search_multi_city,
    search_airports,
    Itinerary,
    select_markets_for_route,
    AIRPORT_COUNTRY_MAP,
)
# proxy_manager removed (Build #89 — Google-native architecture)
# Stub constants for any remaining references
MARKET_TO_COUNTRY_CODE = {}
from airports import search_airports, get_airport, AIRPORTS

# --- LOGGING ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('phoenix.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("phoenix.audit")


def audit_log(action, user_id=None, **details):
    """Log a financial or security-relevant event for audit trail."""
    extra = {"action": action, "user_id": user_id, **details}
    audit_logger.info(
        f"AUDIT action={action} user={user_id} {' '.join(f'{k}={v}' for k,v in details.items())}",
        extra=extra,
    )


# --- APP CONFIGURATION ---
app = Flask(__name__)

# Core config
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(32))
_db_url = os.environ.get('DATABASE_URL', 'sqlite:///phoenix.db')
if _db_url.startswith('postgres://'):
    _db_url = _db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = _db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Session config
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FLASK_ENV') == 'production'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

# Email config (for SendGrid, Mailgun, or SMTP)
app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'true').lower() == 'true'
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER', 'noreply@phoenix.app')

# CSRF config
app.config['WTF_CSRF_TIME_LIMIT'] = 3600  # 1 hour

CORS(app, supports_credentials=True)

# Initialize CSRF protection
csrf = CSRFProtect(app)

# Initialize rate limiter
_rate_limit_storage = os.environ.get("RATELIMIT_STORAGE_URL", "memory://")
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["300 per day", "60 per hour"],
    storage_uri=_rate_limit_storage,
)

# --- Security Headers ---
@app.after_request
def _set_security_headers(response):
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.is_secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


# --- Node Client Template Context (Build #91) ---
@app.context_processor
def _inject_node_context():
    """Inject helper_token and consent JSON for the node client auto-init."""
    ctx = {"helper_token_for_node": "", "node_consent_json": "{}"}
    try:
        from flask_login import current_user as _cu
        if _cu.is_authenticated and getattr(_cu, "is_helper_node", False):
            from models import HelperProfile, NodeConsentProfile
            hp = HelperProfile.query.filter_by(user_id=_cu.id).first()
            if hp and hp.helper_token:
                ctx["helper_token_for_node"] = hp.helper_token
            ncp = NodeConsentProfile.query.filter_by(
                user_id=_cu.id
            ).first()
            if ncp:
                import json as _json
                ctx["node_consent_json"] = _json.dumps({
                    "search_queries": getattr(ncp, "consent_search_queries", False),
                    "price_observations": getattr(ncp, "consent_price_observations", False),
                    "ad_impressions": getattr(ncp, "consent_ad_impressions", False),
                    "social_signals": getattr(ncp, "consent_social_signals", False),
                    "browsing_data": getattr(ncp, "consent_browsing_data", False),
                    "business_data": getattr(ncp, "consent_business_data", False),
                })
    except Exception:
        pass
    return ctx

# Initialize database
init_db(app)

# Initialize Flask-Migrate for database migrations
migrate = Migrate(app, db)

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- CONFIGURATION ---
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 5001
BASE_URL = f"http://localhost:{SERVER_PORT}"

ALLOWED_PROXY_DOMAINS = [
    "jal.co.jp", "ana.co.jp", "united.com", "aa.com", "google.com"
]

# --- HTML TEMPLATES ---
# Import world-class SpaceX/Porsche-inspired template
try:
    from templates.base_template import BASE_TEMPLATE, HOME_HERO
    print("Loaded world-class PHOENIX template")
    # Inject google_client_id into all template renders (Build #91)
    app.jinja_env.globals['google_client_id'] = os.environ.get("GOOGLE_CLIENT_ID", "")
except ImportError:
    HOME_HERO = None
    # Fallback to inline template if import fails
    pass

# Fallback inline template (used if import fails)
_FALLBACK_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>{{ title }} - PHOENIX</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="description" content="PHOENIX - Borderless flight booking powered by XRPL.">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
    <style>
        :root {
            --black: #000000;
            --white: #ffffff;
            --phoenix-orange: #ff4d00;
            --phoenix-amber: #ff8c00;
            --phoenix-gold: #ffc107;
            --success: #00c853;
            --warning: #ff9100;
            --error: #ff1744;

            /* HIGH CONTRAST text colors */
            --text-primary: #f5f5f5;
            --text-secondary: #d8d8e0;
            --text-muted: #b8b8c8;
            --glass-bg: rgba(255, 255, 255, 0.08);
            --glass-border: rgba(255, 255, 255, 0.12);
        }

        * { box-sizing: border-box; margin: 0; padding: 0; }

        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: var(--black);
            color: var(--white);
            min-height: 100vh;
            line-height: 1.5;
        }

        .bg-mesh {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            pointer-events: none;
            z-index: 0;
            background:
                radial-gradient(ellipse 80% 50% at 20% 40%, rgba(255,107,53,0.15) 0%, transparent 50%),
                radial-gradient(ellipse 60% 40% at 80% 20%, rgba(247,147,26,0.1) 0%, transparent 50%),
                radial-gradient(ellipse 50% 30% at 40% 80%, rgba(255,200,55,0.08) 0%, transparent 50%),
                radial-gradient(ellipse 100% 100% at 50% 0%, rgba(26,26,46,0.5) 0%, transparent 60%);
        }

        /* Floating globe grid */
        .globe-grid {
            position: fixed;
            top: 50%;
            right: -200px;
            width: 600px;
            height: 600px;
            transform: translateY(-50%);
            opacity: 0.03;
            pointer-events: none;
            z-index: 0;
        }
        .globe-grid svg { width: 100%; height: 100%; }

        /* Connection lines animation */
        .connection-lines {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            pointer-events: none;
            z-index: 0;
            overflow: hidden;
        }
        .conn-line {
            position: absolute;
            height: 1px;
            background: linear-gradient(90deg, transparent, rgba(255,107,53,0.3), transparent);
            animation: pulse-line 4s ease-in-out infinite;
        }
        .conn-line:nth-child(1) { top: 20%; width: 40%; left: 10%; animation-delay: 0s; }
        .conn-line:nth-child(2) { top: 35%; width: 30%; left: 50%; animation-delay: 1s; }
        .conn-line:nth-child(3) { top: 55%; width: 50%; left: 5%; animation-delay: 2s; }
        .conn-line:nth-child(4) { top: 70%; width: 35%; left: 40%; animation-delay: 0.5s; }
        .conn-line:nth-child(5) { top: 85%; width: 25%; left: 60%; animation-delay: 1.5s; }
        @keyframes pulse-line {
            0%, 100% { opacity: 0; transform: scaleX(0.5); }
            50% { opacity: 1; transform: scaleX(1); }
        }

        /* Phoenix flame particles */
        .particles {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            pointer-events: none;
            z-index: 1;
            overflow: hidden;
        }
        .particle {
            position: absolute;
            width: 4px;
            height: 4px;
            background: var(--phoenix-orange);
            border-radius: 50%;
            filter: blur(1px);
            animation: rise 8s ease-in infinite;
        }
        .particle:nth-child(1) { left: 10%; animation-delay: 0s; }
        .particle:nth-child(2) { left: 25%; animation-delay: 1.5s; background: var(--phoenix-amber); }
        .particle:nth-child(3) { left: 40%; animation-delay: 3s; }
        .particle:nth-child(4) { left: 55%; animation-delay: 0.5s; background: var(--phoenix-gold); }
        .particle:nth-child(5) { left: 70%; animation-delay: 2s; }
        .particle:nth-child(6) { left: 85%; animation-delay: 4s; background: var(--phoenix-amber); }
        @keyframes rise {
            0% { bottom: -10px; opacity: 0; }
            10% { opacity: 0.8; }
            90% { opacity: 0.3; }
            100% { bottom: 100%; opacity: 0; }
        }

        .container { max-width: 1100px; margin: 0 auto; padding: 20px; position: relative; z-index: 10; }

        /* Navigation */
        nav {
            background: rgba(10,10,15,0.8);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            padding: 16px 32px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            position: sticky;
            top: 0;
            z-index: 1000;
            border-bottom: 1px solid var(--glass-border);
        }
        .nav-links { display: flex; align-items: center; gap: 8px; }
        nav a {
            color: var(--text-secondary);
            text-decoration: none;
            padding: 8px 16px;
            font-weight: 500;
            font-size: 14px;
            border-radius: 8px;
            transition: all 0.2s ease;
        }
        nav a:hover {
            color: var(--text-primary);
            background: var(--glass-bg);
        }
        nav a.active { color: var(--phoenix-orange); }

        /* Brand logo */
        .brand {
            display: flex;
            align-items: center;
            gap: 12px;
            text-decoration: none;
        }
        .brand-icon {
            width: 40px;
            height: 40px;
            background: linear-gradient(135deg, var(--phoenix-orange), var(--phoenix-amber));
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 20px;
            box-shadow: 0 4px 20px rgba(255,107,53,0.3);
        }
        .brand-text {
            font-family: 'Space Grotesk', sans-serif;
            font-size: 24px;
            font-weight: 700;
            background: linear-gradient(135deg, var(--phoenix-orange), var(--phoenix-gold));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            letter-spacing: -0.5px;
        }
        .brand-tagline {
            font-size: 10px;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 2px;
            margin-top: -2px;
        }

        /* XRPL Badge */
        .xrpl-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: linear-gradient(135deg, rgba(35,41,47,0.8), rgba(35,41,47,0.4));
            border: 1px solid rgba(255,255,255,0.1);
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 600;
            color: var(--text-secondary);
            margin-left: 16px;
        }
        .xrpl-badge::before {
            content: '';
            width: 8px;
            height: 8px;
            background: var(--success);
            border-radius: 50%;
            animation: pulse-dot 2s ease-in-out infinite;
        }
        @keyframes pulse-dot {
            0%, 100% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.5; transform: scale(1.2); }
        }

        /* Modern buttons with animation */
        .btn {
            background: linear-gradient(135deg, #ff6b35, #ff8c00);
            color: white;
            padding: 12px 28px;
            border: none;
            border-radius: 30px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            text-decoration: none;
            display: inline-block;
            transition: all 0.3s ease;
            box-shadow: 0 4px 15px rgba(67, 97, 238, 0.4);
            position: relative;
            overflow: hidden;
        }
        .btn::before {
            content: '';
            position: absolute;
            top: 0;
            left: -100%;
            width: 100%;
            height: 100%;
            background: linear-gradient(90deg, transparent, rgba(255,255,255,0.3), transparent);
            transition: left 0.5s ease;
        }
        .btn:hover::before { left: 100%; }
        .btn:hover {
            transform: translateY(-3px);
            box-shadow: 0 8px 25px rgba(67, 97, 238, 0.5);
        }
        .btn-secondary { background: linear-gradient(135deg, #6c757d, #5a6268); box-shadow: 0 4px 15px rgba(108, 117, 125, 0.4); }
        .btn-success { background: linear-gradient(135deg, #0f9d58, #0d8a4c); box-shadow: 0 4px 15px rgba(15, 157, 88, 0.4); }

        /* Glass cards */
        .card {
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
            border-radius: 16px;
            padding: 25px;
            margin: 20px 0;
            box-shadow: 0 8px 32px rgba(0,0,0,0.1);
            border: 1px solid rgba(255,255,255,0.2);
            transition: transform 0.3s ease, box-shadow 0.3s ease;
            color: #1a1a2e; /* Dark text for contrast on white background */
        }
        .card:hover {
            transform: translateY(-5px);
            box-shadow: 0 12px 40px rgba(0,0,0,0.15);
        }

        .form-group { margin-bottom: 18px; }
        .form-group label { display: block; margin-bottom: 8px; font-weight: 600; color: #374151; }
        .form-group input, .form-group select {
            width: 100%;
            padding: 12px 16px;
            border: 2px solid #e5e7eb;
            border-radius: 10px;
            font-size: 14px;
            transition: all 0.3s ease;
            background: white;
            color: #1a1a2e; /* Dark text for contrast on white inputs */
        }
        .form-group input:focus, .form-group select:focus {
            outline: none;
            border-color: #ff6b35;
            box-shadow: 0 0 0 4px rgba(67, 97, 238, 0.1);
        }

        /* Animated alerts */
        .alert {
            padding: 16px 20px;
            border-radius: 12px;
            margin-bottom: 15px;
            animation: slideIn 0.3s ease;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        @keyframes slideIn {
            from { opacity: 0; transform: translateY(-10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .alert-success { background: linear-gradient(135deg, #d4edda, #c3e6cb); color: #155724; }
        .alert-success::before { content: ''; }
        .alert-error { background: linear-gradient(135deg, #f8d7da, #f5c6cb); color: #721c24; }
        .alert-error::before { content: ''; }
        .alert-info { background: linear-gradient(135deg, #fff5f0, #ffe5d8); color: #8b4513; }
        .alert-info::before { content: ''; }

        .deal {
            background: rgba(255, 255, 255, 0.95);
            border-radius: 16px;
            padding: 25px;
            margin: 20px 0;
            box-shadow: 0 8px 32px rgba(0,0,0,0.1);
            border-left: 4px solid #ff6b35;
            transition: all 0.3s ease;
        }
        .deal:hover { transform: translateX(5px); }
        .deal-header {
            font-size: 20px;
            font-weight: bold;
            color: #16213e;
            margin-bottom: 15px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .deal-header::before { content: ''; font-size: 24px; }
        .price-row { display: flex; justify-content: space-between; margin: 10px 0; padding: 8px 0; border-bottom: 1px solid #f0f0f0; }
        .savings {
            color: #0f9d58;
            font-weight: bold;
            display: flex;
            align-items: center;
            gap: 5px;
        }
        .savings::before { content: ''; }

        .tag {
            background: linear-gradient(135deg, #e8f5e9, #c8e6c9);
            color: #2e7d32;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
        }
        .tag-warning { background: linear-gradient(135deg, #fff3cd, #ffeaa7); color: #856404; }
        .payment-box {
            background: linear-gradient(135deg, #fff8f5, #fff5f0);
            padding: 20px;
            border-radius: 12px;
            margin-top: 15px;
            border: 1px solid rgba(67, 97, 238, 0.2);
        }
        .xrp-address {
            font-family: 'SF Mono', Monaco, monospace;
            font-size: 13px;
            word-break: break-all;
            background: #1a1a2e;
            color: #ffc107;
            padding: 12px;
            border-radius: 8px;
            margin: 10px 0;
        }

        .status-badge {
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .status-pending { background: linear-gradient(135deg, #fff3cd, #ffeaa7); color: #856404; }
        .status-verified { background: linear-gradient(135deg, #d4edda, #c3e6cb); color: #155724; }
        .status-expired { background: linear-gradient(135deg, #f8d7da, #f5c6cb); color: #721c24; }

        hr { border: none; border-top: 2px solid rgba(0,0,0,0.05); margin: 25px 0; }

        /* Animated stats */
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 20px;
            margin: 25px 0;
        }
        .stat-card {
            background: rgba(255, 255, 255, 0.95);
            color: #1a1a2e;
            padding: 25px;
            border-radius: 16px;
            text-align: center;
            box-shadow: 0 8px 32px rgba(0,0,0,0.1);
            transition: all 0.3s ease;
            position: relative;
            overflow: hidden;
        }
        .stat-card::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 4px;
            background: linear-gradient(90deg, #ff6b35, #ffc107, #ffc107);
        }
        .stat-card:hover {
            transform: translateY(-8px) scale(1.02);
            box-shadow: 0 15px 40px rgba(0,0,0,0.15);
        }
        .stat-value {
            font-size: 32px;
            font-weight: bold;
            background: linear-gradient(135deg, #ff6b35, #ffc107);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        .stat-label { color: #666; font-size: 14px; margin-top: 5px; font-weight: 500; }

        /* Footer */
        footer {
            background: rgba(26, 26, 46, 0.9);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            text-align: center;
            padding: 40px 20px;
            color: rgba(255,255,255,0.85);
            font-size: 14px;
            margin-top: 60px;
            position: relative;
            z-index: 2;
        }
        footer a { color: #ffc107; text-decoration: none; transition: color 0.3s ease; }
        footer a:hover { color: #fff; }
        footer p { margin: 10px 0; }

        /* Pulse animation for important elements */
        @keyframes pulse {
            0%, 100% { transform: scale(1); }
            50% { transform: scale(1.05); }
        }
        .pulse { animation: pulse 2s ease-in-out infinite; }

        /* Click plane animation */
        .click-plane {
            position: fixed;
            font-size: 24px;
            pointer-events: none;
            z-index: 9999;
            animation: flyAway 1s ease-out forwards;
            filter: drop-shadow(2px 2px 3px rgba(0,0,0,0.3));
        }
        @keyframes flyAway {
            0% {
                opacity: 1;
                transform: translate(0, 0) rotate(-45deg) scale(1);
            }
            100% {
                opacity: 0;
                transform: translate(150px, -150px) rotate(-45deg) scale(0.3);
            }
        }

        /* Loading screen */
        .loading-screen {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #1a1a2e 100%);
            z-index: 10000;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            transition: opacity 0.5s ease, visibility 0.5s ease;
        }
        .loading-screen.hidden {
            opacity: 0;
            visibility: hidden;
        }
        .loading-screen h2 {
            color: white;
            font-size: 28px;
            margin-bottom: 30px;
            animation: fadeInOut 2s ease-in-out infinite;
        }
        @keyframes fadeInOut {
            0%, 100% { opacity: 0.5; }
            50% { opacity: 1; }
        }

        /* Globe animation */
        .globe-container {
            position: relative;
            width: 200px;
            height: 200px;
            margin-bottom: 30px;
        }
        .globe {
            width: 150px;
            height: 150px;
            border-radius: 50%;
            background: linear-gradient(135deg, #ff6b35 0%, #ff8c00 50%, #ffc107 100%);
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            box-shadow:
                inset -20px -20px 40px rgba(0,0,0,0.3),
                inset 20px 20px 40px rgba(255,255,255,0.1),
                0 0 60px rgba(67, 97, 238, 0.5);
            overflow: hidden;
        }
        .globe::before {
            content: '';
            position: absolute;
            width: 200%;
            height: 100%;
            background: repeating-linear-gradient(
                90deg,
                transparent 0px,
                transparent 30px,
                rgba(255,255,255,0.1) 30px,
                rgba(255,255,255,0.1) 32px
            );
            animation: rotateGlobe 8s linear infinite;
        }
        .globe::after {
            content: '';
            position: absolute;
            width: 100%;
            height: 200%;
            top: -50%;
            background: repeating-linear-gradient(
                0deg,
                transparent 0px,
                transparent 25px,
                rgba(255,255,255,0.08) 25px,
                rgba(255,255,255,0.08) 27px
            );
        }
        @keyframes rotateGlobe {
            0% { transform: translateX(0); }
            100% { transform: translateX(-50%); }
        }

        /* Orbiting plane around globe */
        .orbit-plane {
            position: absolute;
            width: 100%;
            height: 100%;
            top: 0;
            left: 0;
            animation: orbitSpin 3s linear infinite;
        }
        .orbit-plane::before {
            content: '✈';
            position: absolute;
            font-size: 28px;
            top: -5px;
            left: 50%;
            transform: translateX(-50%) rotate(90deg);
            filter: drop-shadow(0 0 10px rgba(255,255,255,0.8));
        }
        @keyframes orbitSpin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }

        /* Flight path dots */
        .flight-path {
            position: absolute;
            width: 180px;
            height: 180px;
            border: 2px dashed rgba(255,255,255,0.2);
            border-radius: 50%;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
        }

        /* Loading dots */
        .loading-dots {
            display: flex;
            gap: 8px;
        }
        .loading-dots span {
            width: 12px;
            height: 12px;
            background: linear-gradient(135deg, #ff6b35, #ffc107);
            border-radius: 50%;
            animation: bounce 1.4s ease-in-out infinite;
        }
        .loading-dots span:nth-child(1) { animation-delay: 0s; }
        .loading-dots span:nth-child(2) { animation-delay: 0.2s; }
        .loading-dots span:nth-child(3) { animation-delay: 0.4s; }
        @keyframes bounce {
            0%, 80%, 100% { transform: scale(0.6); opacity: 0.5; }
            40% { transform: scale(1); opacity: 1; }
        }

        /* Destination markers on globe */
        .globe-markers {
            position: absolute;
            width: 150px;
            height: 150px;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            animation: rotateMarkers 15s linear infinite;
        }
        .marker {
            position: absolute;
            width: 8px;
            height: 8px;
            background: #ffc107;
            border-radius: 50%;
            box-shadow: 0 0 10px #ffc107;
        }
        .marker:nth-child(1) { top: 20%; left: 30%; }
        .marker:nth-child(2) { top: 40%; left: 70%; }
        .marker:nth-child(3) { top: 60%; left: 20%; }
        .marker:nth-child(4) { top: 35%; left: 50%; }
        .marker:nth-child(5) { top: 70%; left: 60%; }
        @keyframes rotateMarkers {
            0% { transform: translate(-50%, -50%) rotateY(0deg); }
            100% { transform: translate(-50%, -50%) rotateY(360deg); }
        }

        /* Responsive adjustments */
        @media (max-width: 768px) {
            nav { flex-direction: column; gap: 15px; }
            nav div { display: flex; flex-wrap: wrap; justify-content: center; }
            nav a { margin: 5px 10px; }
            .airplane { display: none; }
        }
    </style>
</head>
<body>
    <!-- Animated background elements -->
    <div class="clouds">
        <div class="cloud cloud-1"></div>
        <div class="cloud cloud-2"></div>
        <div class="cloud cloud-3"></div>
        <div class="cloud cloud-4"></div>
    </div>
    <div class="airplane">&#9992;</div>
    <div class="airplane airplane-2">&#9992;</div>

    <!-- Loading Screen -->
    <div class="loading-screen" id="loadingScreen">
        <div class="globe-container">
            <div class="flight-path"></div>
            <div class="globe">
                <div class="globe-markers">
                    <div class="marker"></div>
                    <div class="marker"></div>
                    <div class="marker"></div>
                    <div class="marker"></div>
                    <div class="marker"></div>
                </div>
            </div>
            <div class="orbit-plane"></div>
        </div>
        <h2>Finding the best flight deals...</h2>
        <div class="loading-dots">
            <span></span>
            <span></span>
            <span></span>
        </div>
    </div>

    <nav>
        <span class="brand">PHOENIX</span>
        <div>
            <a href="/search">Search</a>
            <a href="/deals">Deals</a>
            <a href="/earn">Earn</a>
            {% if current_user.is_authenticated %}
                <a href="/dashboard">Dashboard</a>
                <a href="/helper">Helper</a>
                <a href="/wallet">Wallet</a>
                {% if current_user.is_admin %}<a href="/admin" style="color: #ffc107;">Admin</a>{% endif %}
                <a href="/logout">Logout</a>
            {% else %}
                <a href="/login">Login</a>
                <a href="/register">Register</a>
            {% endif %}
        </div>
    </nav>
    <div class="container">
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        {{ content | safe }}
    </div>
    <footer>
        <p>&copy; 2026 PHOENIX. All rights reserved.</p>
        <p>
            <a href="/terms">Terms of Service</a> |
            <a href="/privacy">Privacy Policy</a>
        </p>
    </footer>

    <script>
        // Hide loading screen on page load
        window.addEventListener('load', function() {
            setTimeout(function() {
                document.getElementById('loadingScreen').classList.add('hidden');
            }, 800);
        });

        // Click plane animation
        document.addEventListener('click', function(e) {
            // Don't trigger on input fields or buttons
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'BUTTON' ||
                e.target.tagName === 'A' || e.target.tagName === 'SELECT' ||
                e.target.tagName === 'TEXTAREA') {
                return;
            }

            const plane = document.createElement('div');
            plane.className = 'click-plane';
            plane.innerHTML = '&#9992;';
            plane.style.left = e.clientX + 'px';
            plane.style.top = e.clientY + 'px';
            document.body.appendChild(plane);

            // Remove after animation completes
            setTimeout(function() {
                plane.remove();
            }, 1000);
        });

        // Show loading screen for searches (global function)
        window.showLoadingScreen = function(message) {
            const loader = document.getElementById('loadingScreen');
            const h2 = loader.querySelector('h2');
            if (message) h2.textContent = message;
            loader.classList.remove('hidden');
        };

        window.hideLoadingScreen = function() {
            document.getElementById('loadingScreen').classList.add('hidden');
        };
    </script>
</body>
</html>
"""

HOME_CONTENT = """
<style>
    /* ================================================
       PHOENIX HOME - Search Engine Landing
       ================================================ */

    .phoenix-landing {
        min-height: calc(100vh - 100px);
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        text-align: center;
        padding: 60px 20px 40px;
        position: relative;
        overflow: hidden;
    }

    .phoenix-landing::before {
        content: '';
        position: absolute;
        top: 0; left: 0; right: 0; bottom: 0;
        background:
            radial-gradient(ellipse 80% 60% at 50% 40%, rgba(255, 77, 0, 0.10) 0%, transparent 60%),
            radial-gradient(circle at 20% 80%, rgba(255, 140, 0, 0.06) 0%, transparent 40%);
        pointer-events: none;
    }

    .phoenix-logo-mark {
        font-size: clamp(48px, 12vw, 120px);
        font-weight: 900;
        letter-spacing: -3px;
        line-height: 1;
        margin: 0 0 8px;
        background: linear-gradient(135deg, #ff4d00 0%, #ff8c00 50%, #ffc107 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        opacity: 0;
        animation: fadeInUp 0.8s cubic-bezier(0.16, 1, 0.3, 1) forwards;
    }

    .phoenix-tagline {
        font-size: clamp(16px, 2.5vw, 20px);
        color: rgba(255, 255, 255, 0.7);
        font-weight: 400;
        margin: 0 0 40px;
        max-width: 500px;
        opacity: 0;
        animation: fadeInUp 0.8s cubic-bezier(0.16, 1, 0.3, 1) 0.1s forwards;
    }

    /* Search bar */
    .phoenix-search-bar {
        width: 100%;
        max-width: 640px;
        position: relative;
        opacity: 0;
        animation: fadeInUp 0.8s cubic-bezier(0.16, 1, 0.3, 1) 0.2s forwards;
    }

    .phoenix-search-bar input {
        width: 100%;
        padding: 18px 60px 18px 24px;
        font-size: 16px;
        font-family: 'Rajdhani', sans-serif;
        font-weight: 500;
        background: rgba(255, 255, 255, 0.06);
        border: 1px solid rgba(255, 255, 255, 0.12);
        border-radius: 16px;
        color: #fff;
        outline: none;
        transition: all 0.3s ease;
    }

    .phoenix-search-bar input::placeholder { color: rgba(255,255,255,0.35); }
    .phoenix-search-bar input:focus {
        border-color: rgba(255, 107, 53, 0.5);
        background: rgba(255, 255, 255, 0.08);
        box-shadow: 0 0 0 3px rgba(255, 107, 53, 0.1);
    }

    .phoenix-search-btn {
        position: absolute;
        right: 6px; top: 6px; bottom: 6px;
        width: 48px;
        background: linear-gradient(135deg, #ff6b35, #ff4d00);
        border: none; border-radius: 12px;
        color: white; font-size: 20px;
        cursor: pointer;
        display: flex; align-items: center; justify-content: center;
        transition: opacity 0.2s;
    }
    .phoenix-search-btn:hover { opacity: 0.9; }

    /* Quick action chips */
    .phoenix-chips {
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        justify-content: center;
        margin-top: 24px;
        opacity: 0;
        animation: fadeInUp 0.8s cubic-bezier(0.16, 1, 0.3, 1) 0.3s forwards;
    }

    .phoenix-chip {
        padding: 8px 18px;
        background: rgba(255, 255, 255, 0.04);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 100px;
        color: rgba(255, 255, 255, 0.8);
        font-size: 13px;
        font-weight: 500;
        cursor: pointer;
        text-decoration: none;
        transition: all 0.25s ease;
    }
    .phoenix-chip:hover {
        background: rgba(255, 107, 53, 0.1);
        border-color: rgba(255, 107, 53, 0.3);
        color: #fff;
    }

    /* Verticals grid */
    .phoenix-verticals {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
        gap: 16px;
        max-width: 640px;
        width: 100%;
        margin-top: 48px;
        opacity: 0;
        animation: fadeInUp 0.8s cubic-bezier(0.16, 1, 0.3, 1) 0.4s forwards;
    }

    .phoenix-vertical {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 8px;
        padding: 20px 12px;
        background: rgba(255, 255, 255, 0.02);
        border: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: 14px;
        cursor: pointer;
        text-decoration: none;
        color: inherit;
        transition: all 0.3s ease;
    }
    .phoenix-vertical:hover {
        background: rgba(255, 255, 255, 0.05);
        border-color: rgba(255, 107, 53, 0.3);
        transform: translateY(-4px);
    }
    .phoenix-vertical .v-icon { font-size: 28px; }
    .phoenix-vertical .v-label { font-size: 13px; font-weight: 600; color: rgba(255,255,255,0.85); }

    /* Bottom note */
    .phoenix-note {
        margin-top: 48px;
        font-size: 12px;
        color: rgba(255, 255, 255, 0.35);
        opacity: 0;
        animation: fadeInUp 0.8s cubic-bezier(0.16, 1, 0.3, 1) 0.5s forwards;
    }
    .phoenix-note a { color: rgba(255,107,53,0.7); text-decoration: none; }
    .phoenix-note a:hover { color: #ff6b35; }

    @keyframes fadeInUp {
        from { opacity: 0; transform: translateY(30px); }
        to { opacity: 1; transform: translateY(0); }
    }

    @media (max-width: 768px) {
        .phoenix-landing { padding: 40px 16px 30px; }
        .phoenix-verticals { grid-template-columns: repeat(3, 1fr); gap: 10px; }
        .phoenix-vertical { padding: 14px 8px; }
    }
</style>

<section class="phoenix-landing">
    <div class="phoenix-logo-mark">PHOENIX</div>
    <p class="phoenix-tagline">Search anything. Compare prices across 195 markets. Save on every purchase.</p>

    <div class="phoenix-search-bar">
        <input type="text" id="homeSearchInput" placeholder="Search flights, hotels, products, rentals..." autocomplete="off">
        <button class="phoenix-search-btn" onclick="homeSearch()" aria-label="Search">&#10132;</button>
    </div>

    <div class="phoenix-chips">
        <a class="phoenix-chip" onclick="homeQuick('Cheap flights from NYC to Tokyo next month')">Cheap flights to Tokyo</a>
        <a class="phoenix-chip" onclick="homeQuick('Best hotel deals in Bali')">Hotels in Bali</a>
        <a class="phoenix-chip" onclick="homeQuick('Compare MacBook prices across countries')">MacBook prices</a>
        <a class="phoenix-chip" onclick="homeQuick('Cruise deals in the Mediterranean')">Mediterranean cruises</a>
    </div>

    <div class="phoenix-verticals">
        <a class="phoenix-vertical" onclick="homeQuick('Search flights')">
            <span class="v-icon">&#9992;</span>
            <span class="v-label">Flights</span>
        </a>
        <a class="phoenix-vertical" onclick="homeQuick('Search hotels')">
            <span class="v-icon">&#127976;</span>
            <span class="v-label">Hotels</span>
        </a>
        <a class="phoenix-vertical" onclick="homeQuick('Search products')">
            <span class="v-icon">&#128722;</span>
            <span class="v-label">Products</span>
        </a>
        <a class="phoenix-vertical" onclick="homeQuick('Search rentals')">
            <span class="v-icon">&#128663;</span>
            <span class="v-label">Rentals</span>
        </a>
        <a class="phoenix-vertical" onclick="homeQuick('Search cruises')">
            <span class="v-icon">&#128674;</span>
            <span class="v-label">Cruises</span>
        </a>
    </div>

    <div style="display: flex; gap: 14px; justify-content: center; flex-wrap: wrap; margin-top: 40px; opacity: 0; animation: fadeInUp 0.8s cubic-bezier(0.16, 1, 0.3, 1) 0.5s forwards;">
        <a href="/register" style="padding: 14px 32px; background: linear-gradient(135deg, #ff6b35, #ff4d00); color: white; border-radius: 12px; text-decoration: none; font-weight: 700; font-size: 15px; font-family: 'Rajdhani', sans-serif; transition: opacity 0.2s;">Register Now</a>
        <a href="/helper" style="padding: 14px 32px; background: rgba(255,107,53,0.08); border: 1px solid rgba(255,107,53,0.3); color: #ff6b35; border-radius: 12px; text-decoration: none; font-weight: 700; font-size: 15px; font-family: 'Rajdhani', sans-serif; transition: all 0.2s;">Onboard as Node</a>
        <a href="/login" style="padding: 14px 32px; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.12); color: rgba(255,255,255,0.8); border-radius: 12px; text-decoration: none; font-weight: 600; font-size: 15px; font-family: 'Rajdhani', sans-serif; transition: all 0.2s;">Sign In</a>
    </div>

    <p class="phoenix-note">Powered by AI proxy network &amp; XRPL &middot; Earn XRP by running a <a href="/helper">helper node</a></p>
</section>

<script>
function homeSearch() {
    const q = document.getElementById('homeSearchInput').value.trim();
    if (!q) return;
    // Redirect to login with the query stored, or to /ai if logged in
    window.location.href = '/login?next=/ai&q=' + encodeURIComponent(q);
}
function homeQuick(q) {
    window.location.href = '/login?next=/ai&q=' + encodeURIComponent(q);
}
document.getElementById('homeSearchInput').addEventListener('keydown', function(e) {
    if (e.key === 'Enter') homeSearch();
});
</script>
"""

LOGIN_CONTENT = """
<div class="card" style="max-width: 400px; margin: 40px auto;">
    <h2>Login</h2>
    {% if pending_deal %}
    <div style="background: #fff5f0; padding: 15px; border-radius: 8px; margin-bottom: 20px;">
        Your deal has been saved. Log in to continue booking.
    </div>
    {% endif %}
    <form method="POST">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        {% if pending_deal %}
        <input type="hidden" name="pending_deal_id" value="{{ pending_deal }}">
        {% endif %}
        <div class="form-group">
            <label>Email</label>
            <input type="email" name="email" required>
        </div>
        <div class="form-group">
            <label>Password</label>
            <input type="password" name="password" required>
        </div>
        <button type="submit" class="btn" style="width: 100%;">Login</button>
    </form>
    <p style="margin-top: 15px; text-align: center;">
        Don't have an account? <a href="/register{% if pending_deal %}?deal={{ pending_deal }}{% endif %}">Register</a>
    </p>
    {% if pending_deal %}
    <p style="margin-top: 10px; text-align: center;">
        <a href="/book/{{ pending_deal }}?guest=true" style="color: #666;">Continue as guest instead</a>
    </p>
    {% endif %}
</div>
"""

REGISTER_CONTENT = """
<div class="card" style="max-width: 400px; margin: 40px auto;">
    <h2>Create Account</h2>
    {% if pending_deal %}
    <div style="background: #fff5f0; padding: 15px; border-radius: 8px; margin-bottom: 20px;">
        Your deal has been saved. Create an account to continue booking.
    </div>
    {% endif %}
    <form method="POST">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        {% if pending_deal %}
        <input type="hidden" name="pending_deal_id" value="{{ pending_deal }}">
        {% endif %}
        <div class="form-group">
            <label>Name</label>
            <input type="text" name="name" required>
        </div>
        <div class="form-group">
            <label>Email</label>
            <input type="email" name="email" required>
        </div>
        <div class="form-group">
            <label>Password</label>
            <input type="password" name="password" required minlength="8">
        </div>
        <div class="form-group">
            <label>XRP Wallet Address (optional, for refunds)</label>
            <input type="text" name="xrp_wallet" placeholder="rXXXXXX...">
        </div>
        <button type="submit" class="btn" style="width: 100%;">Create Account</button>
    </form>
    <p style="margin-top: 15px; text-align: center;">
        Already have an account? <a href="/login{% if pending_deal %}?deal={{ pending_deal }}{% endif %}">Login</a>
    </p>
    {% if pending_deal %}
    <p style="margin-top: 10px; text-align: center;">
        <a href="/book/{{ pending_deal }}?guest=true" style="color: #666;">Continue as guest instead</a>
    </p>
    {% endif %}
</div>
"""

DASHBOARD_CONTENT = """
<h1>Welcome, {{ user.name or user.email }}!</h1>

<div class="stats">
    <div class="stat-card">
        <div class="stat-value">{{ payments_count }}</div>
        <div class="stat-label">Payments</div>
    </div>
    <div class="stat-card">
        <div class="stat-value">{{ bookings_count }}</div>
        <div class="stat-label">Bookings</div>
    </div>
    <div class="stat-card">
        <div class="stat-value">${{ "%.2f"|format(total_savings) }}</div>
        <div class="stat-label">Total Saved</div>
    </div>
</div>

<div class="card">
    <h2>Recent Activity</h2>
    {% if recent_payments %}
        <table style="width: 100%; border-collapse: collapse;">
            <tr style="text-align: left; border-bottom: 1px solid #eee;">
                <th style="padding: 10px;">Date</th>
                <th>Amount</th>
                <th>Status</th>
            </tr>
            {% for payment in recent_payments %}
            <tr style="border-bottom: 1px solid #eee;">
                <td style="padding: 10px;">{{ payment.created_at.strftime('%Y-%m-%d %H:%M') }}</td>
                <td>{{ "%.2f"|format(payment.expected_xrp) }} XRP</td>
                <td><span class="status-badge status-{{ payment.status }}">{{ payment.status }}</span></td>
            </tr>
            {% endfor %}
        </table>
    {% else %}
        <p>No payment history yet. <a href="/deals">Browse deals</a> to get started!</p>
    {% endif %}
</div>

<div class="card">
    <h2>Account Settings</h2>
    <p><strong>Email:</strong> {{ user.email }}</p>
    <p><strong>Preferred Currency:</strong> {{ user.preferred_currency }}</p>
    <p><strong>Language:</strong> {{ language_name }}</p>
    <p><strong>XRP Wallet:</strong> {{ user.xrp_wallet_address or 'Not set' }}</p>
    <br>
    <a href="/settings" class="btn btn-secondary">Edit Settings</a>
</div>
"""

SETTINGS_CONTENT = """
<h1>Account Settings</h1>

<div class="card">
    <form method="POST">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <div class="form-group">
            <label for="name">Display Name</label>
            <input type="text" id="name" name="name" value="{{ user.name or '' }}" placeholder="Your name">
        </div>

        <div class="form-group">
            <label for="preferred_currency">Preferred Currency</label>
            <select id="preferred_currency" name="preferred_currency" style="width:100%;padding:10px;border:1px solid #ddd;border-radius:4px;color:#1a1a2e;">
                {% for code, name in currencies %}
                <option value="{{ code }}" {{ 'selected' if user.preferred_currency == code else '' }}>{{ name }} ({{ code }})</option>
                {% endfor %}
            </select>
        </div>

        <div class="form-group">
            <label for="preferred_language">Translation Language</label>
            <select id="preferred_language" name="preferred_language" style="width:100%;padding:10px;border:1px solid #ddd;border-radius:4px;color:#1a1a2e;">
                {% for code, name in languages %}
                <option value="{{ code }}" {{ 'selected' if user.preferred_language == code else '' }}>{{ name }}</option>
                {% endfor %}
            </select>
            <small style="color:#666;display:block;margin-top:5px;">Foreign airline websites will be translated to this language</small>
        </div>

        <div class="form-group">
            <label for="home_market">Home Market</label>
            <select id="home_market" name="home_market" style="width:100%;padding:10px;border:1px solid #ddd;border-radius:4px;color:#1a1a2e;">
                <option value="US" {{ 'selected' if user.home_market == 'US' else '' }}>United States</option>
                <option value="JP" {{ 'selected' if user.home_market == 'JP' else '' }}>Japan</option>
                <option value="GB" {{ 'selected' if user.home_market == 'GB' else '' }}>United Kingdom</option>
                <option value="DE" {{ 'selected' if user.home_market == 'DE' else '' }}>Germany</option>
                <option value="FR" {{ 'selected' if user.home_market == 'FR' else '' }}>France</option>
            </select>
            <small style="color:#666;display:block;margin-top:5px;">Your home market for price comparisons</small>
        </div>

        <div class="form-group">
            <label for="xrp_wallet">XRP Wallet Address (Optional)</label>
            <input type="text" id="xrp_wallet" name="xrp_wallet" value="{{ user.xrp_wallet_address or '' }}" placeholder="rXXX... (for refunds)">
            <small style="color:#666;display:block;margin-top:5px;">Used for refunds if a deal expires after payment</small>
        </div>

        <hr>

        <button type="submit" class="btn">Save Changes</button>
        <a href="/dashboard" class="btn btn-secondary" style="margin-left:10px;">Cancel</a>
    </form>
</div>

<div class="card">
    <h2>Change Password</h2>
    <form method="POST" action="/settings/password">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <div class="form-group">
            <label for="current_password">Current Password</label>
            <input type="password" id="current_password" name="current_password" required>
        </div>
        <div class="form-group">
            <label for="new_password">New Password</label>
            <input type="password" id="new_password" name="new_password" required minlength="8">
        </div>
        <div class="form-group">
            <label for="confirm_password">Confirm New Password</label>
            <input type="password" id="confirm_password" name="confirm_password" required minlength="8">
        </div>
        <button type="submit" class="btn">Update Password</button>
    </form>
</div>
"""

DEALS_CONTENT = """
<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
    <h1 style="margin: 0;">Available Deals</h1>
    <div style="color: #fff; font-size: 14px;">
        XRP: <strong style="color: #ff6b35;">${{ "%.2f"|format(xrp_price) }}</strong> |
        Network: <strong>{{ network }}</strong> |
        {{ deals|length }} deal{{ 's' if deals|length != 1 else '' }} found
        {% if last_scan %} | Last scan: {{ last_scan }}{% endif %}
    </div>
</div>

{% if deals %}
    <div style="display: grid; gap: 20px;">
    {% for d in deals %}
    <div class="card" style="border-left: 4px solid #ff6b35;">
        <div style="display: flex; justify-content: space-between; align-items: start; flex-wrap: wrap; gap: 10px;">
            <div>
                <h3 style="margin: 0 0 5px 0; color: #f5f5f5;">
                    {{ d.airline or 'Flight' }} {{ d.flight_number or '' }}
                </h3>
                <div style="color: #fff; font-size: 14px;">
                    {{ d.origin }} &rarr; {{ d.destination }} &bull;
                    {{ d.departure_date.strftime('%b %d, %Y') if d.departure_date else 'TBD' }}
                    {% if d.stops %} &bull; {{ d.stops }} stop{{ 's' if d.stops > 1 else '' }}{% endif %}
                </div>
            </div>
            <div style="text-align: right;">
                <div style="font-size: 24px; font-weight: bold; color: #4caf50;">
                    Save ${{ "%.0f"|format(d.gross_savings_usd or d.user_savings_usd or 0) }}
                </div>
                <div style="color: #81c784; font-size: 14px;">
                    {{ "%.0f"|format(d.savings_percent or 0) }}% off
                </div>
            </div>
        </div>

        <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 15px; margin-top: 15px; padding-top: 15px; border-top: 1px solid rgba(255,255,255,0.1);">
            <div>
                <div style="color: #fff; font-size: 12px; text-transform: uppercase;">{{ d.home_market or 'US' }} Price</div>
                <div style="color: #e57373; font-size: 18px; text-decoration: line-through;">${{ "%.0f"|format(d.home_price_usd or 0) }}</div>
            </div>
            <div>
                <div style="color: #fff; font-size: 12px; text-transform: uppercase;">Phoenix Price</div>
                <div style="color: #4caf50; font-size: 18px; font-weight: bold;">${{ "%.0f"|format(d.arbitrage_price_usd or 0) }}</div>
            </div>
            <div>
                <div style="color: #fff; font-size: 12px; text-transform: uppercase;">You Save</div>
                <div style="color: #4caf50; font-size: 18px; font-weight: bold;">${{ "%.0f"|format(d.gross_savings_usd or d.user_savings_usd or 0) }}</div>
            </div>
        </div>

        <div style="margin-top: 15px;">
            {% if current_user.is_authenticated %}
                <a href="/book/{{ d.deal_id }}" class="btn" style="display: inline-block;">Book This Deal</a>
            {% else %}
                <a href="/save-deal/{{ d.deal_id }}" class="btn" style="display: inline-block;">Sign Up to Book</a>
            {% endif %}
            <span style="color: #fff; font-size: 12px; margin-left: 10px;">
                Expires {{ d.expires_at.strftime('%b %d %H:%M UTC') if d.expires_at else 'in 24h' }}
            </span>
        </div>
    </div>
    {% endfor %}
    </div>
{% else %}
    <div class="card" style="text-align: center; padding: 60px 20px;">
        <h2 style="color: #f5f5f5; margin-bottom: 10px;">No Active Deals Right Now</h2>
        <p style="color: #fff; max-width: 500px; margin: 0 auto 20px;">
            Deals are generated when our system finds price differences across global markets.
            Try searching for a specific route, or check back soon.
        </p>
        <a href="/search" class="btn">Search Flights</a>
    </div>
{% endif %}
"""

GUEST_CHECKOUT_CONTENT = """
<div class="card" style="max-width: 500px; margin: 40px auto; text-align: center;">
    <h2>Complete Your Booking</h2>
    <p style="color: #666; margin-bottom: 30px;">Your deal has been saved. Choose how you'd like to proceed:</p>

    <div style="background: #f8f9fa; padding: 20px; border-radius: 8px; margin-bottom: 20px;">
        <h3 style="margin-bottom: 10px; color: #1a1a2e;">{{ deal.airline }} {{ deal.flight_number }}</h3>
        <p style="margin: 5px 0; color: #1a1a2e;">{{ deal.origin }} → {{ deal.destination }}</p>
        <p style="margin: 5px 0; color: #666;">{{ deal.departure_date }}</p>
        <p style="margin-top: 15px; font-size: 1.2em;">
            <span style="text-decoration: line-through; color: #fff;">${{ "%.2f"|format(deal.home_price_usd or 0) }}</span>
            <span style="color: #28a745; font-weight: bold; margin-left: 10px;">${{ "%.2f"|format(deal.arbitrage_price_usd or 0) }}</span>
            <span class="tag" style="margin-left: 10px;">Save ${{ "%.2f"|format(deal.user_savings_usd or 0) }}</span>
        </p>
    </div>

    <div style="display: flex; flex-direction: column; gap: 15px;">
        <a href="/register?deal={{ deal_id }}" class="btn" style="padding: 15px 30px; font-size: 1.1em;">
            Create Account
            <small style="display: block; font-weight: normal; font-size: 0.8em; margin-top: 5px;">Track bookings, save preferences, faster checkout</small>
        </a>

        <a href="/login?deal={{ deal_id }}" class="btn btn-secondary" style="padding: 15px 30px;">
            Sign In
            <small style="display: block; font-weight: normal; font-size: 0.8em; margin-top: 5px;">Already have an account?</small>
        </a>

        <hr style="margin: 10px 0; border: none; border-top: 1px solid #eee;">

        <a href="/book/{{ deal_id }}?guest=true" class="btn" style="padding: 15px 30px; background: #6c757d;">
            Continue as Guest
            <small style="display: block; font-weight: normal; font-size: 0.8em; margin-top: 5px;">No account required - just enter your details</small>
        </a>
    </div>

    <p style="margin-top: 20px; font-size: 0.9em; color: #666;">
        Creating an account lets you track your booking history, receive price alerts, and checkout faster next time.
    </p>
</div>
"""

BOOK_CONTENT = """
<style>
    .payment-method-card {
        border: 2px solid #e9ecef;
        border-radius: 12px;
        padding: 20px;
        margin-bottom: 15px;
        cursor: pointer;
        transition: all 0.2s ease;
        background: white;
    }
    .payment-method-card:hover {
        border-color: #ff6b35;
        box-shadow: 0 4px 12px rgba(67, 97, 238, 0.15);
    }
    .payment-method-card.selected {
        border-color: #ff6b35;
        background: #fff8f5;
    }
    .payment-method-card .method-header {
        display: flex;
        align-items: center;
        gap: 15px;
        margin-bottom: 10px;
    }
    .payment-method-card .method-icon {
        font-size: 32px;
        width: 50px;
        text-align: center;
    }
    .payment-method-card .method-title {
        font-weight: bold;
        font-size: 18px;
        color: #16213e;
    }
    .payment-method-card .method-subtitle {
        color: #666;
        font-size: 14px;
    }
    .payment-details-panel {
        display: none;
        background: #f8f9fa;
        border-radius: 8px;
        padding: 20px;
        margin-top: 15px;
    }
    .payment-details-panel.active {
        display: block;
    }
    .crypto-address-box {
        background: white;
        border: 1px solid #ddd;
        border-radius: 8px;
        padding: 15px;
        font-family: monospace;
        font-size: 14px;
        word-break: break-all;
        margin: 10px 0;
    }
    .copy-btn {
        background: #ff6b35;
        color: white;
        border: none;
        padding: 8px 16px;
        border-radius: 6px;
        cursor: pointer;
        font-size: 14px;
        margin-top: 10px;
    }
    .copy-btn:hover {
        background: #ff8c00;
    }
    .order-summary {
        background: linear-gradient(135deg, #16213e 0%, #1a1a2e 100%);
        color: white;
        border-radius: 12px;
        padding: 25px;
        margin-bottom: 25px;
    }
    .order-summary h3 {
        margin: 0 0 20px 0;
        color: #ffc107;
    }
    .order-row {
        display: flex;
        justify-content: space-between;
        padding: 8px 0;
        border-bottom: 1px solid rgba(255,255,255,0.1);
    }
    .order-row:last-child {
        border-bottom: none;
    }
    .order-row.total {
        font-size: 20px;
        font-weight: bold;
        padding-top: 15px;
        margin-top: 10px;
        border-top: 2px solid rgba(255,255,255,0.3);
    }
    .savings-badge {
        background: #28a745;
        color: white;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 14px;
        font-weight: bold;
    }
    .flight-leg-item {
        background: rgba(255,255,255,0.1);
        border-radius: 8px;
        padding: 12px 15px;
        margin-bottom: 10px;
    }
    .processing-overlay {
        display: none;
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0,0,0,0.7);
        z-index: 9999;
        justify-content: center;
        align-items: center;
    }
    .processing-overlay.active {
        display: flex;
    }
    .processing-box {
        background: white;
        border-radius: 16px;
        padding: 40px;
        text-align: center;
        max-width: 400px;
    }
    .spinner {
        width: 50px;
        height: 50px;
        border: 4px solid #e9ecef;
        border-top-color: #ff6b35;
        border-radius: 50%;
        animation: spin 1s linear infinite;
        margin: 0 auto 20px;
    }
    @keyframes spin {
        to { transform: rotate(360deg); }
    }
</style>

<div class="card card-light" style="max-width: 800px; margin: 40px auto;">
    <h2 style="text-align: center; margin-bottom: 25px; color: #1a1a2e;">Complete Your Booking</h2>

    <!-- Order Summary -->
    <div class="order-summary">
        <h3>Order Summary</h3>

        {% if deal.is_multi_leg and deal.flight_legs %}
            {% for leg in deal.flight_legs %}
            <div class="flight-leg-item">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <strong>{{ leg.is_outbound and '🛫 Outbound' or (leg.is_return and '🛬 Return' or ('Leg ' ~ loop.index)) }}</strong><br>
                        <span style="color: #ffc107;">{{ leg.airline or 'Multiple Airlines' }} • {{ leg.route }}</span><br>
                        <small>{{ leg.date }}</small>
                    </div>
                    <div style="text-align: right;">
                        <span style="font-size: 18px; font-weight: bold;">${{ "%.0f"|format(leg.cheapest_price or 0) }}</span>
                        <br><small style="color: #ffc107;">via Phoenix</small>
                    </div>
                </div>
            </div>
            {% endfor %}
        {% else %}
            <div class="flight-leg-item">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <strong>{{ deal.airline or 'Flight' }} {{ deal.flight_number or '' }}</strong><br>
                        <span style="color: #ffc107;">{{ deal.origin }} → {{ deal.destination }}</span><br>
                        <small>{{ deal.departure_date }}</small>
                    </div>
                    <div style="text-align: right;">
                        <span style="font-size: 18px; font-weight: bold;">${{ "%.0f"|format(deal.arbitrage_price_usd or 0) }}</span>
                        <br><small style="color: #ffc107;">via Phoenix</small>
                    </div>
                </div>
            </div>
        {% endif %}

        <div class="order-row">
            <span>Flight{{ 's' if deal.is_multi_leg else '' }} Subtotal</span>
            <span>${{ "%.2f"|format(deal.arbitrage_price_usd or 0) }}</span>
        </div>
        {% if deal.gross_savings_usd and deal.gross_savings_usd > 0 %}
        <div class="order-row" style="color: #28a745;">
            <span>Your Savings</span>
            <span class="savings-badge">-${{ "%.0f"|format(deal.gross_savings_usd or 0) }}</span>
        </div>
        {% endif %}
        <div class="order-row total">
            <span>Total Due</span>
            <span>${{ "%.2f"|format((deal.arbitrage_price_usd or 0) + (deal.platform_fee_usd or 0)) }}</span>
        </div>
    </div>

    {% if payment_verified %}
        <!-- Payment Complete - Collect Passenger Details -->
        <div class="alert alert-success" style="text-align: center; padding: 25px;">
            <span style="font-size: 48px;">✅</span>
            <h3 style="margin: 15px 0;">Payment Verified!</h3>
            <p>Your payment has been confirmed. Please provide passenger details to complete your booking.</p>
        </div>

        <!-- Passenger Details Form -->
        <form id="passenger-form" action="/complete-booking/{{ deal.deal_id }}" method="POST" style="margin-top: 20px;">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
            <div style="background: #f8f9fa; border-radius: 12px; padding: 25px;">
                <h4 style="margin: 0 0 20px 0; color: #1a1a2e;">Passenger Information</h4>
                <p style="color: #666; margin-bottom: 20px;">Enter passenger details exactly as they appear on the travel document.</p>

                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px;">
                    <!-- First Name -->
                    <div class="form-group">
                        <label style="font-weight: bold; color: #16213e; display: block; margin-bottom: 5px;">First Name *</label>
                        <input type="text" name="first_name" required
                               placeholder="John"
                               style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 16px; color: #1a1a2e;">
                    </div>

                    <!-- Last Name -->
                    <div class="form-group">
                        <label style="font-weight: bold; color: #16213e; display: block; margin-bottom: 5px;">Last Name *</label>
                        <input type="text" name="last_name" required
                               placeholder="Doe"
                               style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 16px; color: #1a1a2e;">
                    </div>

                    <!-- Email -->
                    <div class="form-group">
                        <label style="font-weight: bold; color: #16213e; display: block; margin-bottom: 5px;">Email *</label>
                        <input type="email" name="email" required
                               value="{{ passenger_email or '' }}"
                               placeholder="john.doe@email.com"
                               style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 16px; color: #1a1a2e;">
                    </div>

                    <!-- Phone -->
                    <div class="form-group">
                        <label style="font-weight: bold; color: #16213e; display: block; margin-bottom: 5px;">Phone Number *</label>
                        <input type="tel" name="phone" required
                               placeholder="+1 555-123-4567"
                               style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 16px; color: #1a1a2e;">
                    </div>

                    <!-- Date of Birth -->
                    <div class="form-group">
                        <label style="font-weight: bold; color: #16213e; display: block; margin-bottom: 5px;">Date of Birth *</label>
                        <input type="date" name="date_of_birth" required
                               style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 16px; color: #1a1a2e;">
                    </div>

                    <!-- Gender -->
                    <div class="form-group">
                        <label style="font-weight: bold; color: #16213e; display: block; margin-bottom: 5px;">Gender *</label>
                        <select name="gender" required
                                style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 16px; color: #1a1a2e;">
                            <option value="">Select...</option>
                            <option value="M">Male</option>
                            <option value="F">Female</option>
                        </select>
                    </div>
                </div>

                <!-- International Flight - Passport Details -->
                <div style="margin-top: 25px; padding-top: 20px; border-top: 1px solid #ddd;">
                    <h5 style="margin: 0 0 15px 0; color: #16213e;">Passport Information (for international flights)</h5>

                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px;">
                        <!-- Passport Number -->
                        <div class="form-group">
                            <label style="font-weight: bold; color: #16213e; display: block; margin-bottom: 5px;">Passport Number</label>
                            <input type="text" name="passport_number"
                                   placeholder="AB1234567"
                                   style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 16px; color: #1a1a2e;">
                        </div>

                        <!-- Passport Expiry -->
                        <div class="form-group">
                            <label style="font-weight: bold; color: #16213e; display: block; margin-bottom: 5px;">Passport Expiry</label>
                            <input type="date" name="passport_expiry"
                                   style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 16px; color: #1a1a2e;">
                        </div>

                        <!-- Passport Country -->
                        <div class="form-group">
                            <label style="font-weight: bold; color: #16213e; display: block; margin-bottom: 5px;">Passport Country</label>
                            <input type="text" name="passport_country"
                                   placeholder="United States"
                                   style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 16px; color: #1a1a2e;">
                        </div>

                        <!-- Nationality -->
                        <div class="form-group">
                            <label style="font-weight: bold; color: #16213e; display: block; margin-bottom: 5px;">Nationality</label>
                            <input type="text" name="nationality"
                                   placeholder="American"
                                   style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 16px; color: #1a1a2e;">
                        </div>
                    </div>
                </div>

                <!-- Known Traveler Number (optional) -->
                <div style="margin-top: 20px;">
                    <div class="form-group">
                        <label style="font-weight: bold; color: #16213e; display: block; margin-bottom: 5px;">Known Traveler Number (optional)</label>
                        <input type="text" name="known_traveler_number"
                               placeholder="TSA PreCheck or Global Entry number"
                               style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 16px; color: #1a1a2e;">
                        <small style="color: #666;">TSA PreCheck, Global Entry, NEXUS, or SENTRI</small>
                    </div>
                </div>

                <!-- Booking Options -->
                <div style="margin-top: 25px; padding: 20px; background: #fff5f0; border-radius: 8px;">
                    <h5 style="margin: 0 0 15px 0;">Booking Method</h5>
                    <div style="display: flex; gap: 20px;">
                        <label style="display: flex; align-items: center; cursor: pointer;">
                            <input type="radio" name="fulfillment_type" value="automated" checked style="margin-right: 10px;">
                            <span><strong>Automated Booking</strong> - We book for you (recommended)</span>
                        </label>
                        <label style="display: flex; align-items: center; cursor: pointer;">
                            <input type="radio" name="fulfillment_type" value="self_service" style="margin-right: 10px;">
                            <span><strong>Self-Service</strong> - Book via proxy yourself</span>
                        </label>
                    </div>
                    <p style="margin-top: 10px; font-size: 13px; color: #666;">
                        Automated booking: Our system completes the booking and sends you the confirmation.<br>
                        Self-service: We provide a link to the airline's site through our regional proxy.
                    </p>
                </div>

                <!-- Submit Button -->
                <button type="submit" class="btn btn-success" style="width: 100%; margin-top: 25px; padding: 15px; font-size: 18px;">
                    Complete Booking
                </button>
            </div>
        </form>

        <!-- Self-Service Fallback Links (hidden by default) -->
        <div id="self-service-links" style="display: none; background: #f8f9fa; border-radius: 12px; padding: 20px; margin-top: 20px;">
            <h4 style="margin: 0 0 15px 0;">Book via Proxy</h4>
            <p style="color: #666; margin-bottom: 15px;">Click below to open the booking page through our regional proxy.</p>

            {% if deal.is_multi_leg and deal.flight_legs %}
                {% for leg in deal.flight_legs %}
                <a href="/proxy/https://www.google.com/travel/flights?q=Flights+from+{{ leg.route.split(' → ')[0] if ' → ' in leg.route else leg.route.split(' to ')[0] }}+to+{{ leg.route.split(' → ')[-1] if ' → ' in leg.route else leg.route.split(' to ')[-1] }}+on+{{ leg.date }}" class="btn btn-success" target="_blank" style="display: block; margin-bottom: 10px; text-align: center;">
                    {{ leg.is_outbound and 'Book Outbound' or (leg.is_return and 'Book Return' or ('Book Leg ' ~ loop.index)) }}: {{ leg.route }}
                </a>
                {% endfor %}
            {% else %}
                <a href="/proxy/https://www.google.com/travel/flights?q=Flights+from+{{ deal.origin }}+to+{{ deal.destination }}+on+{{ deal.departure_date }}" class="btn btn-success" target="_blank" style="display: block; text-align: center;">
                    Open Booking Page
                </a>
            {% endif %}
        </div>

        <script>
            // Show/hide self-service links based on fulfillment type selection
            document.querySelectorAll('input[name="fulfillment_type"]').forEach(function(radio) {
                radio.addEventListener('change', function() {
                    var selfServiceLinks = document.getElementById('self-service-links');
                    var passengerForm = document.getElementById('passenger-form');
                    if (this.value === 'self_service') {
                        selfServiceLinks.style.display = 'block';
                    } else {
                        selfServiceLinks.style.display = 'none';
                    }
                });
            });
        </script>

    {% else %}
        <!-- Guest Email Collection (for non-authenticated users) -->
        {% if not current_user.is_authenticated %}
        <div style="background: #fff8f5; border: 2px solid #ff6b35; border-radius: 12px; padding: 20px; margin-bottom: 25px;">
            <h4 style="margin: 0 0 15px 0; color: #16213e;">Guest Checkout</h4>
            <p style="color: #666; margin-bottom: 15px;">Enter your email to receive your booking confirmation and e-ticket.</p>
            <div class="form-group" style="margin-bottom: 0;">
                <label for="guest_email" style="font-weight: bold; color: #16213e;">Email Address *</label>
                <input type="email" id="guest_email" name="guest_email" required
                       value="{{ session.get('guest_email', '') }}"
                       placeholder="your@email.com"
                       style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 16px;"
                       onchange="saveGuestEmail(this.value)">
            </div>
            <p style="margin-top: 10px; font-size: 12px; color: #666;">
                <a href="/register?deal={{ deal.deal_id }}" style="color: #ff6b35;">Create an account</a> to track your bookings and get price alerts.
            </p>
        </div>
        {% endif %}

        <!-- Payment Selection -->
        <h3 style="margin-bottom: 20px;">Choose Payment Method</h3>

        <!-- Credit Card -->
        <div class="payment-method-card" onclick="selectPayment('card')" id="method-card">
            <div class="method-header">
                <span class="method-icon">💳</span>
                <div>
                    <div class="method-title">Credit or Debit Card</div>
                    <div class="method-subtitle">Visa, Mastercard, American Express</div>
                </div>
                <div style="margin-left: auto; font-weight: bold; color: #ff6b35;">
                    ${{ "%.2f"|format((deal.arbitrage_price_usd or 0) + (deal.platform_fee_usd or 0)) }}
                </div>
            </div>
            <div class="payment-details-panel" id="details-card">
                <p>Secure payment powered by Stripe. You'll be redirected to complete your payment.</p>
                <button class="btn" onclick="payWithCard(event)" style="width: 100%; margin-top: 10px;">
                    Pay ${{ "%.2f"|format((deal.arbitrage_price_usd or 0) + (deal.platform_fee_usd or 0)) }} with Card
                </button>
            </div>
        </div>

        <!-- XRP Direct -->
        <div class="payment-method-card" onclick="selectPayment('xrp')" id="method-xrp">
            <div class="method-header">
                <span class="method-icon">⚡</span>
                <div>
                    <div class="method-title">XRP (Direct)</div>
                    <div class="method-subtitle">Pay directly on XRPL • Instant settlement</div>
                </div>
                <div style="margin-left: auto; font-weight: bold; color: #ff6b35;">
                    {{ "%.4f"|format(payment_options.methods.xrp.amount_xrp or 0) }} XRP
                </div>
            </div>
            <div class="payment-details-panel" id="details-xrp">
                <p><strong>Send exactly:</strong></p>
                <div class="crypto-address-box">
                    {{ "%.6f"|format(payment_options.methods.xrp.amount_xrp or 0) }} XRP
                </div>
                <p><strong>To address:</strong></p>
                <div class="crypto-address-box" id="xrp-address">
                    {{ payment_options.methods.xrp.destination or platform_wallet }}
                </div>
                <button class="copy-btn" onclick="copyToClipboard('xrp-address', event)">📋 Copy Address</button>

                <p style="margin-top: 15px;"><strong>⚠️ IMPORTANT - Destination Tag:</strong></p>
                <div class="crypto-address-box" style="background: #fff3cd; border-color: #ffc107;" id="xrp-tag">
                    {{ payment_options.methods.xrp.destination_tag or deal.destination_tag }}
                </div>
                <button class="copy-btn" onclick="copyToClipboard('xrp-tag', event)">📋 Copy Tag</button>

                <div style="background: #f8d7da; color: #721c24; padding: 12px; border-radius: 8px; margin-top: 15px;">
                    <strong>Warning:</strong> You MUST include the destination tag. Payments without it cannot be credited to your account.
                </div>

                <p style="margin-top: 15px; color: #666;">Network: {{ network }}</p>

                <form method="POST" style="margin-top: 15px;" onsubmit="return validateGuestEmail()">
                    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                    <input type="hidden" name="payment_method" value="xrp">
                    <input type="hidden" name="guest_email" id="xrp_guest_email" value="">
                    <button type="submit" class="btn" style="width: 100%;" onclick="document.getElementById('xrp_guest_email').value = getGuestEmail();">
                        ✓ I've Sent the Payment - Verify Now
                    </button>
                </form>
            </div>
        </div>

        <!-- RLUSD Stablecoin -->
        <div class="payment-method-card" onclick="selectPayment('rlusd')" id="method-rlusd">
            <div class="method-header">
                <span class="method-icon">💵</span>
                <div>
                    <div class="method-title">RLUSD Stablecoin</div>
                    <div class="method-subtitle">Ripple's USD stablecoin on XRPL • 1:1 with USD</div>
                </div>
                <div style="margin-left: auto; font-weight: bold; color: #ff6b35;">
                    ${{ "%.2f"|format((deal.arbitrage_price_usd or 0) + (deal.platform_fee_usd or 0)) }} RLUSD
                </div>
            </div>
            <div class="payment-details-panel" id="details-rlusd">
                <p><strong>Send exactly:</strong></p>
                <div class="crypto-address-box">
                    {{ "%.2f"|format((deal.arbitrage_price_usd or 0) + (deal.platform_fee_usd or 0)) }} RLUSD
                </div>
                <p><strong>To address:</strong></p>
                <div class="crypto-address-box" id="rlusd-address">
                    {{ payment_options.methods.rlusd.destination or platform_wallet }}
                </div>
                <button class="copy-btn" onclick="copyToClipboard('rlusd-address', event)">📋 Copy Address</button>

                <p style="margin-top: 15px;"><strong>⚠️ Destination Tag:</strong></p>
                <div class="crypto-address-box" style="background: #fff3cd;" id="rlusd-tag">
                    {{ payment_options.methods.rlusd.destination_tag or deal.destination_tag }}
                </div>
                <button class="copy-btn" onclick="copyToClipboard('rlusd-tag', event)">📋 Copy Tag</button>

                <form method="POST" style="margin-top: 15px;" onsubmit="return validateGuestEmail()">
                    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                    <input type="hidden" name="payment_method" value="rlusd">
                    <input type="hidden" name="guest_email" id="rlusd_guest_email" value="">
                    <button type="submit" class="btn" style="width: 100%;" onclick="document.getElementById('rlusd_guest_email').value = getGuestEmail();">
                        ✓ I've Sent RLUSD - Verify Now
                    </button>
                </form>
            </div>
        </div>

        <!-- Any Cryptocurrency -->
        <div class="payment-method-card" onclick="selectPayment('crypto')" id="method-crypto">
            <div class="method-header">
                <span class="method-icon">🪙</span>
                <div>
                    <div class="method-title">Other Cryptocurrency</div>
                    <div class="method-subtitle">Bitcoin, Ethereum, Litecoin, Dogecoin, USDC & more</div>
                </div>
                <div style="margin-left: auto; font-weight: bold; color: #ff6b35;">
                    ${{ "%.2f"|format((deal.arbitrage_price_usd or 0) + (deal.platform_fee_usd or 0)) }}
                </div>
            </div>
            <div class="payment-details-panel" id="details-crypto">
                <p>Pay with any major cryptocurrency via Coinbase Commerce:</p>
                <div style="display: flex; gap: 10px; flex-wrap: wrap; margin: 15px 0;">
                    <span style="background: #f7931a; color: white; padding: 5px 12px; border-radius: 20px;">₿ Bitcoin</span>
                    <span style="background: #627eea; color: white; padding: 5px 12px; border-radius: 20px;">Ξ Ethereum</span>
                    <span style="background: #345d9d; color: white; padding: 5px 12px; border-radius: 20px;">Ł Litecoin</span>
                    <span style="background: #c3a634; color: white; padding: 5px 12px; border-radius: 20px;">Ð Dogecoin</span>
                    <span style="background: #2775ca; color: white; padding: 5px 12px; border-radius: 20px;">USDC</span>
                </div>
                <button class="btn" onclick="payWithCrypto(event)" style="width: 100%;">
                    Pay with Cryptocurrency
                </button>
            </div>
        </div>

        <p style="text-align: center; color: #666; margin-top: 20px; font-size: 14px;">
            🔒 All payments are secure and encrypted<br>
            <small>By proceeding, you agree to our Terms of Service</small>
        </p>
    {% endif %}
</div>

<!-- Processing Overlay -->
<div class="processing-overlay" id="processing-overlay">
    <div class="processing-box">
        <div class="spinner"></div>
        <h3 id="processing-title">Processing Payment...</h3>
        <p id="processing-message">Please wait while we verify your payment.</p>
    </div>
</div>

<script>
const dealId = "{{ deal.deal_id }}";
const totalAmount = {{ (deal.arbitrage_price_usd or 0) + (deal.platform_fee_usd or 0) }};
let guestEmail = "{{ session.get('guest_email', '') }}";

function saveGuestEmail(email) {
    guestEmail = email;
    // Save to session via quick API call
    fetch('/api/save-guest-email', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email })
    });
}

function getGuestEmail() {
    const emailInput = document.getElementById('guest_email');
    return emailInput ? emailInput.value : guestEmail;
}

function validateGuestEmail() {
    const emailInput = document.getElementById('guest_email');
    if (emailInput && !emailInput.value) {
        alert('Please enter your email address to receive your booking confirmation.');
        emailInput.focus();
        return false;
    }
    return true;
}

function selectPayment(method) {
    // Remove selected from all
    document.querySelectorAll('.payment-method-card').forEach(c => c.classList.remove('selected'));
    document.querySelectorAll('.payment-details-panel').forEach(p => p.classList.remove('active'));

    // Select this one
    document.getElementById('method-' + method).classList.add('selected');
    document.getElementById('details-' + method).classList.add('active');
}

function copyToClipboard(elementId, event) {
    event.stopPropagation();
    const text = document.getElementById(elementId).innerText.trim();
    navigator.clipboard.writeText(text).then(() => {
        const btn = event.target;
        const originalText = btn.innerText;
        btn.innerText = '✓ Copied!';
        setTimeout(() => btn.innerText = originalText, 2000);
    });
}

function showProcessing(title, message) {
    document.getElementById('processing-title').innerText = title;
    document.getElementById('processing-message').innerText = message;
    document.getElementById('processing-overlay').classList.add('active');
}

function hideProcessing() {
    document.getElementById('processing-overlay').classList.remove('active');
}

function payWithCard(event) {
    event.stopPropagation();

    // Validate guest email if not authenticated
    if (!validateGuestEmail()) return;

    showProcessing('Redirecting to Checkout...', 'You will be redirected to our secure payment page.');

    fetch('/api/payment/stripe/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            deal_id: dealId,
            amount: totalAmount,
            guest_email: getGuestEmail()
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.checkout_url) {
            window.location.href = data.checkout_url;
        } else {
            hideProcessing();
            alert('Error: ' + (data.error || 'Could not create checkout session'));
        }
    })
    .catch(err => {
        hideProcessing();
        alert('Error connecting to payment service. Please try again.');
    });
}

function payWithCrypto(event) {
    event.stopPropagation();

    // Validate guest email if not authenticated
    if (!validateGuestEmail()) return;

    showProcessing('Creating Crypto Payment...', 'You will be redirected to Coinbase Commerce.');

    fetch('/api/payment/coinbase/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            deal_id: dealId,
            amount: totalAmount,
            guest_email: getGuestEmail()
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.hosted_url) {
            window.location.href = data.hosted_url;
        } else {
            hideProcessing();
            alert('Error: ' + (data.error || 'Could not create crypto payment'));
        }
    })
    .catch(err => {
        hideProcessing();
        alert('Error connecting to payment service. Please try again.');
    });
}

// Auto-expand first payment method
document.addEventListener('DOMContentLoaded', function() {
    selectPayment('card');
});
</script>
"""


# --- PWA ASSETS ---

@app.route("/service-worker.js")
def service_worker():
    """Serve service worker from root scope."""
    return send_from_directory(
        os.path.join(app.root_path, "static"),
        "service-worker.js",
        mimetype="application/javascript",
    )


@app.route("/favicon.ico")
def favicon():
    """Serve favicon."""
    return send_from_directory(
        os.path.join(app.root_path, "static"),
        "favicon.ico",
        mimetype="image/x-icon",
    )


# --- ROUTES ---

@app.route("/")
def home():
    """Homepage IS Phoenix AI for everyone."""
    is_auth = "true" if current_user.is_authenticated else "false"
    content = PHOENIX_AI_CONTENT.replace("__IS_AUTHENTICATED__", is_auth)
    return render_template_string(
        BASE_TEMPLATE,
        title="Phoenix AI",
        content=content,
        current_user=current_user
    )


@app.route("/register", methods=["GET", "POST"])
@limiter.limit("10 per hour", methods=["POST"])
def register():
    """User registration."""
    if current_user.is_authenticated:
        return redirect("/ai")

    # Get deal from URL param or session (retrieve BEFORE login_user changes session)
    deal_from_url = request.args.get('deal')
    pending_deal = deal_from_url or session.get('pending_deal_id')

    if request.method == "POST":
        email = request.form.get("email", "").lower().strip()
        password = request.form.get("password", "")
        name = request.form.get("name", "").strip()
        xrp_wallet = request.form.get("xrp_wallet", "").strip()

        # Get pending deal from hidden form field (in case session was cleared)
        pending_deal_form = request.form.get('pending_deal_id')
        redirect_deal = pending_deal or pending_deal_form

        # Validation
        if User.query.filter_by(email=email).first():
            flash("Email already registered", "error")
            if redirect_deal:
                return redirect(f"/register?deal={redirect_deal}")
            return redirect("/register")

        if len(password) < 8:
            flash("Password must be at least 8 characters", "error")
            if redirect_deal:
                return redirect(f"/register?deal={redirect_deal}")
            return redirect("/register")

        # Create user — all users are proxy nodes
        user = User(email=email, name=name, xrp_wallet_address=xrp_wallet or None)
        user.is_helper_node = True
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        # Create HelperProfile with helper_token for node service / extension auth
        try:
            helper = HelperProfile(
                user_id=user.id,
                is_active=True,
                is_approved=True,
                country_code=user.home_market or "US",
                helper_token=secrets.token_urlsafe(48),
                node_id=f"NOD-{secrets.token_hex(8)}",
            )
            db.session.add(helper)
            db.session.commit()
        except Exception as hp_err:
            logger.warning(f"HelperProfile creation failed for user {user.id} (non-blocking): {hp_err}")

        # --- Node Consent Economy: Auto-onboard new user as node ---
        try:
            from node_consent_economy import node_consent_economy
            onboard_result = node_consent_economy.onboard_new_user(user.id)
            if onboard_result.get("success"):
                logger.info(f"Node onboarded for user {user.id}: wallet={onboard_result.get('wallet_address', 'N/A')}")
            else:
                logger.warning(f"Node onboarding partial for user {user.id}: {onboard_result.get('error', 'unknown')}")
        except Exception as onboard_err:
            logger.warning(f"Node onboarding failed for user {user.id} (non-blocking): {onboard_err}")

        # Clear session pending deal before login (login_user may regenerate session)
        session.pop('pending_deal_id', None)

        login_user(user)
        flash("Account created successfully!", "success")

        # Redirect to pending deal if exists
        if redirect_deal:
            flash("Redirecting you to your saved deal!", "info")
            return redirect(f"/book/{redirect_deal}")

        return redirect("/install")

    return render_template_string(
        BASE_TEMPLATE,
        title="Register",
        content=render_template_string(
            REGISTER_CONTENT,
            pending_deal=pending_deal,
            current_user=current_user
        ),
        pending_deal=pending_deal,
        current_user=current_user
    )


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("15 per hour", methods=["POST"])
def login():
    """User login."""
    if current_user.is_authenticated:
        return redirect("/ai")

    # Get deal from URL param or session (retrieve BEFORE login_user changes session)
    deal_from_url = request.args.get('deal')
    pending_deal = deal_from_url or session.get('pending_deal_id')

    if request.method == "POST":
        email = request.form.get("email", "").lower().strip()
        password = request.form.get("password", "")

        # Get pending deal from hidden form field (in case session was cleared)
        pending_deal_form = request.form.get('pending_deal_id')
        redirect_deal = pending_deal or pending_deal_form

        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            user.last_login = datetime.utcnow()
            db.session.commit()

            # Clear session pending deal before login (login_user may regenerate session)
            session.pop('pending_deal_id', None)

            login_user(user)
            flash("Welcome back!", "success")

            # Redirect to pending deal if exists
            if redirect_deal:
                flash("Redirecting you to your saved deal!", "info")
                return redirect(f"/book/{redirect_deal}")

            return redirect("/ai")
        else:
            flash("Invalid email or password", "error")
            if redirect_deal:
                return redirect(f"/login?deal={redirect_deal}")

    return render_template_string(
        BASE_TEMPLATE,
        title="Login",
        content=render_template_string(
            LOGIN_CONTENT,
            pending_deal=pending_deal,
            current_user=current_user
        ),
        pending_deal=pending_deal,
        current_user=current_user
    )


def _oauth_provision_user(provider_id_field, provider_id_value, email, name):
    """
    Shared OAuth user provisioning (Build #83).
    Find or create user by provider ID / email, ensure HelperProfile,
    return (user, helper, consent_profile).
    """
    # Find by provider ID
    user = User.query.filter(getattr(User, provider_id_field) == provider_id_value).first()

    if not user:
        # Check if email already exists (account linking)
        user = User.query.filter_by(email=email).first()
        if user:
            setattr(user, provider_id_field, provider_id_value)
            if not user.name:
                user.name = name
            logger.info(f"Linked user {user.id} to {provider_id_field}={provider_id_value}")
        else:
            # Create new user — generate a random bcrypt hash since
            # the column is NOT NULL (OAuth users sign in via provider)
            import bcrypt as _bcrypt
            _rand_pw = secrets.token_urlsafe(32).encode('utf-8')
            _pw_hash = _bcrypt.hashpw(_rand_pw, _bcrypt.gensalt()).decode('utf-8')
            user = User(
                email=email,
                name=name,
                password_hash=_pw_hash,
                is_active=True,
                is_verified=True,
            )
            setattr(user, provider_id_field, provider_id_value)
            db.session.add(user)
            db.session.flush()
            logger.info(f"Created user {user.id} from OAuth ({provider_id_field}): {email}")

            # Auto-onboard node
            try:
                from node_consent_economy import node_consent_economy
                node_consent_economy.onboard_new_user(user.id)
            except Exception as e:
                logger.error(f"Auto-onboarding failed for user {user.id}: {e}")

    # Create or ensure HelperProfile with token
    helper = HelperProfile.query.filter_by(user_id=user.id).first()
    if not helper:
        helper = HelperProfile(
            user_id=user.id,
            is_active=True,
            is_approved=True,
            country_code="US",
            helper_token=secrets.token_urlsafe(48),
            node_id=f"NOD-{secrets.token_hex(8)}",
        )
        db.session.add(helper)
    else:
        if not helper.helper_token:
            helper.helper_token = secrets.token_urlsafe(48)
        if not helper.node_id:
            helper.node_id = f"NOD-{secrets.token_hex(8)}"
        if not helper.is_active:
            helper.is_active = True

    db.session.commit()

    # Get consent profile if exists
    consent_profile = None
    try:
        from models import NodeConsentProfile
        profile = NodeConsentProfile.query.filter_by(user_id=user.id).first()
        if profile:
            consent_profile = {
                "consent_search_queries": profile.consent_search_queries,
                "consent_price_observations": profile.consent_price_observations,
                "consent_ad_impressions": profile.consent_ad_impressions,
                "consent_social_signals": profile.consent_social_signals,
                "consent_browsing_data": profile.consent_browsing_data,
                "consent_business_data": profile.consent_business_data,
                "current_tier": profile.current_tier,
                "tier_score": profile.tier_score,
                "payout_multiplier": profile.payout_multiplier,
            }
    except Exception as e:
        logger.warning(f"Failed to fetch consent profile: {e}")

    return user, helper, consent_profile


def _oauth_success_response(user, helper, consent_profile):
    """Format standard OAuth success response."""
    return jsonify({
        "success": True,
        "serverUrl": request.host_url.rstrip("/"),
        "helperToken": helper.helper_token,
        "nodeId": helper.node_id,
        "userName": user.name or user.email.split("@")[0],
        "userEmail": user.email,
        "xrplWallet": user.xrpl_wallet_address,
        "consentProfile": consent_profile,
    }), 200


@app.route("/api/v1/auth/google", methods=["POST"])
@limiter.limit("20 per hour")
def api_auth_google():
    """
    Google OAuth authentication for Chrome extension (Build #82).
    Accepts Google access token, validates via Google userinfo API,
    provisions user + node, returns credentials.
    """
    try:
        data = request.get_json()
        if not data or not data.get("access_token"):
            return jsonify({"error": "access_token required"}), 400

        # Validate Google access token by fetching userinfo
        try:
            google_resp = http_requests.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {data['access_token']}"},
                timeout=10,
            )
            if google_resp.status_code != 200:
                return jsonify({"error": "Invalid Google access token"}), 401

            userinfo = google_resp.json()
            google_id = userinfo.get("id")
            email = userinfo.get("email")
            name = userinfo.get("name", email.split("@")[0] if email else "User")

            if not google_id or not email:
                return jsonify({"error": "Invalid Google userinfo response"}), 400
        except http_requests.exceptions.RequestException as e:
            logger.error(f"Google userinfo request failed: {e}")
            return jsonify({"error": "Failed to verify Google token"}), 502

        user, helper, consent_profile = _oauth_provision_user("google_id", google_id, email, name)
        return _oauth_success_response(user, helper, consent_profile)

    except Exception as e:
        db.session.rollback()
        logger.exception("Google OAuth error")
        return jsonify({"error": "Internal server error"}), 500


# --- Google Sign-In for Web (Build #91 — one-click onboarding) ---

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")


@app.route("/auth/google/token", methods=["POST"])
@csrf.exempt
@limiter.limit("30 per hour")
def auth_google_token():
    """Handle Google Sign-In via access token from GSI token client.

    The client-side JS obtains an access_token via
    google.accounts.oauth2.initTokenClient (popup flow).
    We verify the token with Google's userinfo API, then provision
    the user + node and log them in.

    No redirect URIs or client_secret needed.
    """
    import requests as _requests

    data = request.get_json(silent=True) or {}
    access_token = data.get("access_token")
    if not access_token:
        return jsonify({"error": "No access_token provided"}), 400

    try:
        # 1. Verify the token and get user info from Google
        userinfo_resp = _requests.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        if userinfo_resp.status_code != 200:
            logger.warning("Google userinfo failed: %s", userinfo_resp.text)
            return jsonify({"error": "Invalid access token"}), 401

        userinfo = userinfo_resp.json()
        google_id = userinfo.get("sub")
        email = userinfo.get("email")
        name = userinfo.get("name", (email or "User").split("@")[0])

        if not google_id or not email:
            return jsonify({"error": "Could not retrieve Google account info"}), 400

        # 2. Double-check: verify the token was issued for our client_id
        tokeninfo_resp = _requests.get(
            f"https://oauth2.googleapis.com/tokeninfo?access_token={access_token}",
            timeout=10,
        )
        if tokeninfo_resp.status_code == 200:
            tokeninfo = tokeninfo_resp.json()
            aud = tokeninfo.get("aud") or tokeninfo.get("azp", "")
            if aud and aud != GOOGLE_CLIENT_ID:
                logger.warning("Token audience mismatch: %s vs %s", aud, GOOGLE_CLIENT_ID)
                return jsonify({"error": "Token was not issued for this application"}), 401

        # 3. Provision user, helper profile, and node
        user, helper, consent_profile = _oauth_provision_user(
            "google_id", google_id, email, name,
        )

        # Mark Google linked on helper
        if helper and not helper.google_account_linked:
            helper.google_account_linked = True
            db.session.commit()

        # Auto-onboard as node
        if not user.is_helper_node:
            user.is_helper_node = True
            db.session.commit()

        # Log the user in
        login_user(user, remember=True)

        logger.info("Google token sign-in: user=%s (%s)", user.id, email)

        return jsonify({
            "success": True,
            "user_id": user.id,
            "email": email,
            "name": name,
            "is_node": user.is_helper_node,
            "redirect": url_for("home"),
        })

    except Exception as e:
        db.session.rollback()
        import traceback
        traceback.print_exc()
        logger.exception("Google token sign-in error: %s", e)
        return jsonify({"error": "Sign-in failed. Please try again."}), 500


@app.route("/auth/google/start")
def auth_google_start():
    """Redirect the user to Google's OAuth 2.0 authorization endpoint.

    Uses the implicit grant (response_type=token) so we only need
    the client_id — no client_secret required.  Works in every browser
    because it's a standard full-page redirect, not a popup.

    Google returns an access_token in the URL fragment of the landing page.
    The landing page JS reads it and POSTs to /auth/google/token.
    """
    nonce = secrets.token_urlsafe(32)
    session["google_oauth_nonce"] = nonce

    # Build the redirect URI — must match what's registered in Google Console
    redirect_uri = request.host_url.rstrip("/") + "/auth/google/landing"

    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "token",
        "scope": "openid email profile",
        "include_granted_scopes": "true",
        "state": nonce,
        "prompt": "select_account",
    }
    from urllib.parse import urlencode
    google_auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    return redirect(google_auth_url)


@app.route("/auth/google/landing")
def auth_google_landing():
    """Landing page for Google OAuth implicit flow.

    Google redirects here with #access_token=... in the URL fragment.
    This page reads the fragment, POSTs the token to /auth/google/token,
    and redirects the user to the home page on success.
    """
    return '''<!DOCTYPE html>
<html><head><title>Signing in to Phoenix...</title>
<style>
body{background:#0a0612;color:#f5f5f5;font-family:'Rajdhani',sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;}
.box{text-align:center;max-width:500px;padding:20px;}
.spinner{width:40px;height:40px;border:3px solid rgba(255,107,53,0.3);border-top:3px solid #ff6b35;border-radius:50%;animation:spin 0.8s linear infinite;margin:0 auto 16px;}
@keyframes spin{to{transform:rotate(360deg);}}
.err{color:#f87171;margin-top:16px;font-size:14px;line-height:1.5;}
.debug{background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:8px;padding:12px;margin-top:16px;font-size:12px;color:#999;text-align:left;word-break:break-all;}
a{color:#ff6b35;}
</style></head><body>
<div class="box">
<div class="spinner" id="spinner"></div>
<p id="status">Completing sign-in...</p>
<div id="errBox" style="display:none;">
    <p class="err" id="err"></p>
    <div class="debug" id="debug"></div>
    <p style="margin-top:16px;"><a href="/">Back to Phoenix</a></p>
</div>
</div>
<script>
(function(){
    var fragmentStr = window.location.hash.substring(1);
    var queryStr = window.location.search;

    function showError(msg, detail) {
        document.getElementById('spinner').style.display = 'none';
        document.getElementById('status').style.display = 'none';
        document.getElementById('err').textContent = msg;
        document.getElementById('debug').textContent = detail || '';
        document.getElementById('errBox').style.display = 'block';
    }

    // Check query params for errors
    var qParams = new URLSearchParams(queryStr);
    if (qParams.get('error')) {
        showError('Google returned an error: ' + qParams.get('error'),
                  qParams.get('error_description') || '');
        return;
    }

    // Parse fragment
    if (!fragmentStr) {
        showError('No authentication data received from Google.',
                  'The URL fragment is empty. This means Google did not return a token. ' +
                  'Make sure the redirect URI http://localhost:5001/auth/google/landing ' +
                  'is added to Authorized redirect URIs in Google Cloud Console.');
        return;
    }

    var fParams = {};
    fragmentStr.split('&').forEach(function(part){
        var kv = part.split('=');
        if(kv[0]) fParams[decodeURIComponent(kv[0])] = decodeURIComponent(kv[1] || '');
    });

    if (fParams['error']) {
        showError('Google returned an error: ' + fParams['error'],
                  fParams['error_description'] || '');
        return;
    }

    var accessToken = fParams['access_token'];
    if (!accessToken) {
        showError('No access_token in Google response.',
                  'Received: ' + Object.keys(fParams).join(', '));
        return;
    }

    // POST the access token to our server
    document.getElementById('status').textContent = 'Verifying with Phoenix...';

    fetch('/auth/google/token', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({access_token: accessToken}),
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.success) {
            document.getElementById('status').textContent = 'Welcome! Redirecting...';
            window.location.href = data.redirect || '/';
        } else {
            showError('Sign-in failed: ' + (data.error || 'Unknown error'), '');
        }
    })
    .catch(function(err) {
        showError('Network error: ' + err.message,
                  'Could not reach the Phoenix server.');
    });
})();
</script>
</body></html>'''


@app.route("/auth/google/redirect")
def auth_google_redirect():
    """Landing page for Google's OAuth redirect.

    Google sends the id_token in the URL fragment (#id_token=...).
    Fragments are not sent to the server, so this page uses a small
    JS snippet to extract it and POST it to /auth/google/callback.

    Google may also return errors in query params (e.g. ?error=access_denied).
    """
    # Check for server-visible errors (query params)
    error = request.args.get("error")
    error_desc = request.args.get("error_description", "")
    if error:
        logger.warning("Google OAuth error (query): %s — %s", error, error_desc)

    return '''<!DOCTYPE html>
<html><head><title>Signing in...</title>
<style>
body{background:#0a0612;color:#f5f5f5;font-family:'Rajdhani',sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;}
.box{text-align:center;max-width:500px;padding:20px;}
.spinner{width:40px;height:40px;border:3px solid rgba(255,107,53,0.3);border-top:3px solid #ff6b35;border-radius:50%;animation:spin 0.8s linear infinite;margin:0 auto 16px;}
@keyframes spin{to{transform:rotate(360deg);}}
.err{color:#f87171;margin-top:16px;font-size:14px;line-height:1.5;}
.debug{background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:8px;padding:12px;margin-top:16px;font-size:12px;color:#999;text-align:left;word-break:break-all;}
a{color:#ff6b35;}
</style></head><body>
<div class="box">
<div class="spinner" id="spinner"></div>
<p id="status">Completing sign-in...</p>
<div id="errBox" style="display:none;">
    <p class="err" id="err"></p>
    <div class="debug" id="debug"></div>
    <p style="margin-top:16px;"><a href="/">Back to Phoenix</a></p>
</div>
</div>
<script>
(function(){
    // Collect ALL data for diagnostics
    var queryStr = window.location.search;
    var fragmentStr = window.location.hash.substring(1);
    var fullUrl = window.location.href;

    function showError(msg, detail) {
        document.getElementById('spinner').style.display = 'none';
        document.getElementById('status').style.display = 'none';
        document.getElementById('err').textContent = msg;
        document.getElementById('debug').textContent = 'URL query: ' + queryStr + '\\nURL fragment: ' + (fragmentStr || '(empty)') + '\\n\\n' + (detail || '');
        document.getElementById('errBox').style.display = 'block';
    }

    // Check query params for errors first (Google sends some errors here)
    var qParams = {};
    queryStr.replace('?','').split('&').forEach(function(part){
        var kv = part.split('=');
        if(kv[0]) qParams[decodeURIComponent(kv[0])] = decodeURIComponent(kv[1] || '');
    });
    if (qParams['error']) {
        showError('Google returned an error: ' + qParams['error'],
                  'Description: ' + (qParams['error_description'] || 'none'));
        return;
    }

    // Check fragment for id_token or errors
    if (!fragmentStr) {
        showError('No authentication data received from Google.',
                  'This usually means Google did not redirect back properly. Make sure:\\n' +
                  '1. You completed the Google sign-in\\n' +
                  '2. The OAuth consent screen is configured in Google Cloud Console');
        return;
    }

    var fParams = {};
    fragmentStr.split('&').forEach(function(part){
        var kv = part.split('=');
        if(kv[0]) fParams[decodeURIComponent(kv[0])] = decodeURIComponent(kv[1] || '');
    });

    if (fParams['error']) {
        showError('Google returned an error: ' + fParams['error'],
                  'Description: ' + (fParams['error_description'] || 'none'));
        return;
    }

    var idToken = fParams['id_token'];
    if (!idToken) {
        showError('No id_token in Google response.',
                  'Received keys: ' + Object.keys(fParams).join(', '));
        return;
    }

    // Success — POST the id_token to our callback
    var form = document.createElement('form');
    form.method = 'POST';
    form.action = '/auth/google/callback';
    var input = document.createElement('input');
    input.type = 'hidden';
    input.name = 'credential';
    input.value = idToken;
    form.appendChild(input);
    document.body.appendChild(form);
    form.submit();
})();
</script>
</body></html>'''


@app.route("/auth/google/callback", methods=["POST"])
@csrf.exempt
@limiter.limit("30 per hour")
def auth_google_web_callback():
    """Handle Google Identity Services credential callback.

    The GSI JS library POSTs a JWT ``credential`` after the user
    authenticates via the one-tap prompt or Sign-In button.  We decode
    it, provision the user + node, log them in, and redirect home.
    """
    import json as _json
    import base64

    credential = request.form.get("credential") or (request.get_json(silent=True) or {}).get("credential")
    if not credential:
        flash("Google sign-in failed — no credential received.", "error")
        return redirect(url_for("login"))

    try:
        # Decode the JWT payload (middle segment). We trust Google's
        # signature because we specified our client_id in the GSI init.
        parts = credential.split(".")
        if len(parts) < 2:
            raise ValueError("Malformed JWT")

        payload = parts[1]
        # Fix padding
        payload += "=" * (4 - len(payload) % 4)
        decoded = _json.loads(base64.urlsafe_b64decode(payload))

        google_id = decoded.get("sub")
        email = decoded.get("email")
        name = decoded.get("name", (email or "User").split("@")[0])

        if not google_id or not email:
            raise ValueError("Missing sub or email in Google JWT")

        # Provision user, helper profile, and node
        user, helper, consent_profile = _oauth_provision_user("google_id", google_id, email, name)

        # Mark Google linked on helper
        if helper and not helper.google_account_linked:
            helper.google_account_linked = True
            db.session.commit()

        # Auto-onboard as node if not already
        if not user.is_helper_node:
            user.is_helper_node = True
            db.session.commit()

        # Log the user in via Flask-Login
        login_user(user, remember=True)

        logger.info("Google web sign-in: user=%s (%s)", user.id, email)
        flash(f"Welcome, {name}! Your node is active.", "success")
        return redirect(url_for("home"))

    except Exception as e:
        db.session.rollback()
        import traceback
        traceback.print_exc()
        print(f"[GOOGLE AUTH ERROR] {e}", flush=True)
        logger.exception("Google web sign-in error: %s", e)
        flash("Google sign-in failed. Please try again.", "error")
        return redirect(url_for("login"))


@app.route("/api/v1/auth/microsoft", methods=["POST"])
@limiter.limit("20 per hour")
def api_auth_microsoft():
    """
    Microsoft OAuth authentication (Build #83).
    Accepts Microsoft access token, validates via Microsoft Graph API,
    provisions user + node, returns credentials.
    """
    try:
        data = request.get_json()
        if not data or not data.get("access_token"):
            return jsonify({"error": "access_token required"}), 400

        # Validate Microsoft token via Graph API
        try:
            ms_resp = http_requests.get(
                "https://graph.microsoft.com/v1.0/me",
                headers={"Authorization": f"Bearer {data['access_token']}"},
                timeout=10,
            )
            if ms_resp.status_code != 200:
                return jsonify({"error": "Invalid Microsoft access token"}), 401

            userinfo = ms_resp.json()
            microsoft_id = userinfo.get("id")
            email = userinfo.get("mail") or userinfo.get("userPrincipalName")
            name = userinfo.get("displayName", email.split("@")[0] if email else "User")

            if not microsoft_id or not email:
                return jsonify({"error": "Invalid Microsoft userinfo response"}), 400
        except http_requests.exceptions.RequestException as e:
            logger.error(f"Microsoft Graph request failed: {e}")
            return jsonify({"error": "Failed to verify Microsoft token"}), 502

        user, helper, consent_profile = _oauth_provision_user("microsoft_id", microsoft_id, email, name)
        return _oauth_success_response(user, helper, consent_profile)

    except Exception as e:
        db.session.rollback()
        logger.exception("Microsoft OAuth error")
        return jsonify({"error": "Internal server error"}), 500


@app.route("/api/v1/auth/apple", methods=["POST"])
@limiter.limit("20 per hour")
def api_auth_apple():
    """
    Apple Sign-In authentication (Build #83).
    Accepts Apple id_token (JWT), decodes and validates claims,
    provisions user + node, returns credentials.

    Apple id_tokens contain: sub (Apple user ID), email, email_verified.
    Full JWKS signature verification should be enabled for production
    by fetching keys from https://appleid.apple.com/auth/keys
    """
    try:
        data = request.get_json()
        if not data or not data.get("id_token"):
            return jsonify({"error": "id_token required"}), 400

        id_token = data["id_token"]

        # Decode Apple id_token (JWT)
        # Format: header.payload.signature — each base64url-encoded
        try:
            import base64

            parts = id_token.split(".")
            if len(parts) != 3:
                return jsonify({"error": "Malformed id_token"}), 400

            # Decode payload (part 1) — add padding as needed
            payload_b64 = parts[1]
            payload_b64 += "=" * (4 - len(payload_b64) % 4)
            payload_bytes = base64.urlsafe_b64decode(payload_b64)
            claims = json.loads(payload_bytes)

            # Validate issuer and audience
            if claims.get("iss") != "https://appleid.apple.com":
                return jsonify({"error": "Invalid token issuer"}), 401

            import time
            if claims.get("exp", 0) < time.time():
                return jsonify({"error": "Token expired"}), 401

            apple_id = claims.get("sub")
            email = claims.get("email")
            # Apple may provide name only on first auth — use email prefix as fallback
            name = data.get("user_name") or (email.split("@")[0] if email else "User")

            if not apple_id or not email:
                return jsonify({"error": "Invalid Apple token claims"}), 400

            # TODO: For production, verify JWT signature against Apple's JWKS
            # keys = http_requests.get("https://appleid.apple.com/auth/keys").json()
            # Use matching kid from JWT header to verify RS256 signature

        except (ValueError, KeyError, json.JSONDecodeError) as e:
            logger.error(f"Apple id_token decode error: {e}")
            return jsonify({"error": "Failed to decode Apple token"}), 400

        user, helper, consent_profile = _oauth_provision_user("apple_id", apple_id, email, name)
        return _oauth_success_response(user, helper, consent_profile)

    except Exception as e:
        db.session.rollback()
        logger.exception("Apple OAuth error")
        return jsonify({"error": "Internal server error"}), 500


@app.route("/logout")
@login_required
def logout():
    """User logout."""
    logout_user()
    flash("You have been logged out", "info")
    return redirect("/")


@app.route("/dashboard")
@login_required
def dashboard():
    """User dashboard."""
    payments = current_user.payments.order_by(Payment.created_at.desc()).limit(10).all()
    bookings = current_user.bookings.all()

    # Calculate total savings
    verified_payments = current_user.payments.filter_by(status='verified').all()
    total_savings = sum(
        p.deal.user_savings_usd for p in verified_payments
        if p.deal and p.deal.user_savings_usd
    )

    return render_template_string(
        BASE_TEMPLATE,
        title="Dashboard",
        content=render_template_string(
            DASHBOARD_CONTENT,
            user=current_user,
            payments_count=current_user.payments.count(),
            bookings_count=current_user.bookings.count(),
            total_savings=total_savings,
            recent_payments=payments,
            language_name=get_language_name(current_user.preferred_language or 'en')
        ),
        current_user=current_user
    )


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    """User settings page."""
    if request.method == "POST":
        # Update user settings
        current_user.name = request.form.get("name", "").strip() or None
        current_user.preferred_currency = request.form.get("preferred_currency", "USD")
        current_user.preferred_language = request.form.get("preferred_language", "en")
        current_user.home_market = request.form.get("home_market", "US")
        current_user.xrp_wallet_address = request.form.get("xrp_wallet", "").strip() or None

        db.session.commit()
        flash("Settings updated successfully!", "success")
        return redirect("/settings")

    # Available currencies
    currencies = [
        ("USD", "US Dollar"),
        ("EUR", "Euro"),
        ("GBP", "British Pound"),
        ("JPY", "Japanese Yen"),
        ("CAD", "Canadian Dollar"),
        ("AUD", "Australian Dollar"),
    ]

    return render_template_string(
        BASE_TEMPLATE,
        title="Settings",
        content=render_template_string(
            SETTINGS_CONTENT,
            user=current_user,
            currencies=currencies,
            languages=list(SUPPORTED_LANGUAGES.items())
        ),
        current_user=current_user
    )


@app.route("/settings/password", methods=["POST"])
@login_required
def change_password():
    """Change user password."""
    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")

    if not current_user.check_password(current_password):
        flash("Current password is incorrect", "error")
        return redirect("/settings")

    if new_password != confirm_password:
        flash("New passwords do not match", "error")
        return redirect("/settings")

    if len(new_password) < 8:
        flash("New password must be at least 8 characters", "error")
        return redirect("/settings")

    current_user.set_password(new_password)
    db.session.commit()
    flash("Password updated successfully!", "success")
    return redirect("/settings")


# --- GDPR Data Rights ---

@app.route("/api/account/export")
@login_required
@limiter.limit("3 per day")
def api_account_export():
    """GDPR Article 20 — Export all personal data as JSON."""
    user = User.query.get(current_user.id)

    # Core profile
    export = {
        "profile": {
            "email": user.email,
            "name": user.name,
            "preferred_currency": user.preferred_currency,
            "home_market": user.home_market,
            "preferred_language": user.preferred_language,
            "xrp_wallet_address": user.xrp_wallet_address,
            "is_helper_node": user.is_helper_node,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "last_login": user.last_login.isoformat() if user.last_login else None,
        },
    }

    # Payments
    payments = Payment.query.filter_by(user_id=user.id).all()
    export["payments"] = [
        {
            "amount_usd": p.amount_usd,
            "payment_method": p.payment_method,
            "status": p.status,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in payments
    ]

    # Wallets
    wallets = UserWallet.query.filter_by(user_id=user.id).all()
    export["wallets"] = [
        {
            "wallet_address": w.wallet_address,
            "label": w.label,
            "is_primary": w.is_primary,
            "created_at": w.created_at.isoformat() if w.created_at else None,
        }
        for w in wallets
    ]

    # P2P transactions (as buyer)
    p2p_txs = P2PTransaction.query.filter_by(buyer_id=user.id).all()
    export["p2p_transactions"] = [
        {
            "transaction_id": t.transaction_id,
            "status": t.status,
            "origin": t.origin,
            "destination": t.destination,
            "target_market": t.target_market,
            "us_price_usd": t.us_price_usd,
            "target_price_usd": t.target_price_usd,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in p2p_txs
    ]

    # Price alerts
    alerts = PriceAlert.query.filter_by(user_id=user.id).all()
    export["price_alerts"] = [
        {
            "origin": a.origin,
            "destination": a.destination,
            "max_price_usd": a.max_price_usd,
            "is_active": a.is_active,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in alerts
    ]

    # Helper profile
    helper = HelperProfile.query.filter_by(user_id=user.id).first()
    if helper:
        export["helper_profile"] = {
            "country_code": helper.country_code,
            "wallet_address": helper.wallet_address,
            "is_approved": helper.is_approved,
            "successful_transactions": helper.successful_transactions,
            "total_earned_rlusd": str(helper.total_earned_rlusd) if helper.total_earned_rlusd else "0",
            "created_at": helper.created_at.isoformat() if helper.created_at else None,
        }

    audit_log("data_export", user_id=user.id)
    return jsonify(export)


@app.route("/api/account/delete", methods=["POST"])
@login_required
@limiter.limit("1 per day")
def api_account_delete():
    """GDPR Article 17 — Right to erasure. Anonymize and deactivate account."""
    user = User.query.get(current_user.id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    # Check for active P2P transactions (cannot delete mid-transaction)
    active_p2p = P2PTransaction.query.filter_by(buyer_id=user.id).filter(
        P2PTransaction.status.in_(["requested", "matched", "escrow_locked", "purchasing"])
    ).count()
    if active_p2p > 0:
        return jsonify({
            "error": "Cannot delete account with active P2P transactions. "
                     "Please wait for all transactions to complete or cancel them first.",
            "active_transactions": active_p2p,
        }), 400

    audit_log("account_deletion", user_id=user.id, email=user.email)

    # Anonymize PII
    user.email = f"deleted_{user.id}@removed.invalid"
    user.name = None
    user.password_hash = "DELETED"
    user.xrp_wallet_address = None
    user.is_active = False
    user.is_verified = False
    user.verification_token = None
    user.reset_token = None

    # Deactivate helper profile
    helper = HelperProfile.query.filter_by(user_id=user.id).first()
    if helper:
        helper.is_active = False
        helper.is_approved = False
        helper.wallet_address = None

    # Delete wallets
    UserWallet.query.filter_by(user_id=user.id).delete()

    # Delete price alerts
    PriceAlert.query.filter_by(user_id=user.id).delete()

    # Close node sessions
    from models import NodeSession
    NodeSession.query.filter_by(user_id=user.id, status="active").update(
        {"status": "closed", "end_time": datetime.utcnow()}
    )

    db.session.commit()

    # Log out
    from flask_login import logout_user
    logout_user()

    return jsonify({"status": "deleted", "message": "Account has been permanently deleted."})


@app.route("/deals")
def deals():
    """Browse available deals from the database."""
    get_xrp_price()

    # Read active deals from DB, sorted by savings descending
    active_deals = Deal.query.filter(
        Deal.is_active == True,
        db.or_(Deal.expires_at == None, Deal.expires_at > datetime.utcnow())
    ).order_by(Deal.user_savings_usd.desc()).limit(50).all()

    # Get last scan time from most recently created deal
    last_scan = None
    if active_deals:
        newest = max(active_deals, key=lambda d: d.created_at or datetime.min)
        last_scan = newest.created_at.strftime("%b %d %H:%M UTC") if newest.created_at else None

    return render_template_string(
        BASE_TEMPLATE,
        title="Deals",
        content=render_template_string(
            DEALS_CONTENT,
            deals=active_deals,
            xrp_price=XRPL_CONFIG["xrp_usd_rate"],
            network=XRPL_CONFIG["network"].upper(),
            last_scan=last_scan,
            current_user=current_user
        ),
        current_user=current_user
    )


@app.route("/save-deal/<deal_id>")
def save_deal_for_guest(deal_id):
    """Save a deal selection and show choice page (signup, login, or guest checkout)."""
    if current_user.is_authenticated:
        return redirect(f"/book/{deal_id}")

    # Store the deal in session for after signup/login
    session['pending_deal_id'] = deal_id

    # Get deal info for the choice page
    deal = Deal.query.filter_by(deal_id=deal_id).first()
    if not deal:
        # Create minimal deal info for display
        deal = type('Deal', (), {
            'airline': 'Flight',
            'flight_number': '',
            'origin': 'Origin',
            'destination': 'Destination',
            'departure_date': 'Selected Date',
            'home_price_usd': 0,
            'arbitrage_price_usd': 0,
            'user_savings_usd': 0
        })()

    return render_template_string(
        BASE_TEMPLATE,
        title="Complete Booking",
        content=render_template_string(
            GUEST_CHECKOUT_CONTENT,
            deal=deal,
            deal_id=deal_id,
            current_user=current_user
        ),
        current_user=current_user
    )


@app.route("/book/<deal_id>", methods=["GET", "POST"])
def book(deal_id):
    """Book a deal (payment verification gate) - supports multiple payment methods and guest checkout."""
    # Check if this is a guest checkout
    is_guest = request.args.get('guest') == 'true' or session.get('guest_checkout')

    # If not authenticated and not guest, redirect to save-deal choice page
    if not current_user.is_authenticated and not is_guest:
        return redirect(f"/save-deal/{deal_id}")

    # Mark session as guest checkout if applicable
    if is_guest and not current_user.is_authenticated:
        session['guest_checkout'] = True
        session['guest_deal_id'] = deal_id

    get_xrp_price()
    refresh_xrp_price()  # Update XRP price for payments

    # Get user_id (None for guests)
    user_id = current_user.id if current_user.is_authenticated else None

    # Get or create deal record
    deal = Deal.query.filter_by(deal_id=deal_id).first()

    if not deal:
        # Create a placeholder deal for demo
        destination_tag = abs(hash(deal_id)) % 2147483647
        deal = Deal(
            deal_id=deal_id,
            airline="JAL",
            flight_number="61",
            origin="LAX",
            destination="HND",
            departure_date=datetime.now().date(),
            home_market="US",
            home_price_usd=850.00,
            arbitrage_market="JP",
            arbitrage_price_usd=720.00,
            gross_savings_usd=130.00,
            platform_fee_usd=32.50,
            platform_fee_xrp=32.50 / XRPL_CONFIG["xrp_usd_rate"],
            user_savings_usd=97.50,
            savings_percent=11.5,
            destination_tag=destination_tag,
            booking_url="https://www.jal.co.jp/jp/ja/",
            is_active=True
        )
        db.session.add(deal)
        db.session.commit()

    # Ensure deal has destination_tag
    if not deal.destination_tag:
        deal.destination_tag = abs(hash(deal_id)) % 2147483647
        db.session.commit()

    # Calculate total amount (flight + service fee)
    total_amount = (deal.arbitrage_price_usd or 0) + (deal.platform_fee_usd or 0)

    # Generate payment options for all methods
    payment_options = generate_payment_options(
        deal_id=deal_id,
        fee_usd=total_amount,
        user_id=user_id
    )

    # Override destination_tag with deal's tag for consistency
    if payment_options.get("methods", {}).get("xrp"):
        payment_options["methods"]["xrp"]["destination_tag"] = deal.destination_tag
    if payment_options.get("methods", {}).get("rlusd"):
        payment_options["methods"]["rlusd"]["destination_tag"] = deal.destination_tag

    # Check for existing verified payment (for authenticated users)
    # For guests, check by destination_tag since they don't have a user_id
    if user_id:
        payment = Payment.query.filter_by(
            user_id=user_id,
            deal_id=deal.id,
            status='verified'
        ).first()
    else:
        # For guests, check by destination_tag
        payment = Payment.query.filter_by(
            deal_id=deal.id,
            destination_tag=deal.destination_tag,
            status='verified'
        ).order_by(Payment.created_at.desc()).first()

    payment_verified = payment is not None

    # Get guest email from form or session
    guest_email = request.form.get('guest_email') or session.get('guest_email')
    if guest_email:
        session['guest_email'] = guest_email

    if request.method == "POST" and not payment_verified:
        payment_method = request.form.get("payment_method", "xrp")

        if payment_method == "xrp":
            # Check for XRP payment on XRPL
            expected_xrp = payment_options.get("methods", {}).get("xrp", {}).get("amount_xrp", 0)
            result = verify_xrp_payment(deal.destination_tag, expected_xrp)

            if result.get('verified'):
                payment = Payment(
                    user_id=user_id,
                    deal_id=deal.id,
                    payment_method='xrp',
                    destination_tag=deal.destination_tag,
                    expected_xrp=expected_xrp,
                    received_xrp=result.get('amount_xrp'),
                    xrp_usd_rate=XRPL_CONFIG["xrp_usd_rate"],
                    tx_hash=result.get('tx_hash'),
                    sender_address=result.get('sender'),
                    amount_usd=total_amount,
                    status='verified',
                    verified_at=datetime.utcnow()
                )
                db.session.add(payment)
                db.session.commit()
                payment_verified = True
                flash("XRP payment verified! You can now access the booking page.", "success")

                # Trigger booking fulfillment
                trigger_booking_fulfillment(deal, payment, guest_email=guest_email)
            else:
                flash(f"XRP payment not found yet. {result.get('error', '')}", "error")

        elif payment_method == "rlusd":
            # Check for RLUSD payment on XRPL
            from payments import verify_rlusd_payment
            result = verify_rlusd_payment(deal.destination_tag, total_amount)

            if result.get('verified'):
                payment = Payment(
                    user_id=user_id,
                    deal_id=deal.id,
                    payment_method='rlusd',
                    destination_tag=deal.destination_tag,
                    amount_usd=total_amount,
                    tx_hash=result.get('tx_hash'),
                    sender_address=result.get('sender'),
                    status='verified',
                    verified_at=datetime.utcnow()
                )
                db.session.add(payment)
                db.session.commit()
                payment_verified = True
                flash("RLUSD payment verified! You can now access the booking page.", "success")

                # Trigger booking fulfillment
                trigger_booking_fulfillment(deal, payment, guest_email=guest_email)
            else:
                flash(f"RLUSD payment not found yet. {result.get('error', '')}", "error")

    # Convert payment_options to a dict-like object for template
    class DotDict(dict):
        __getattr__ = dict.get
        __setattr__ = dict.__setitem__

    def to_dot_dict(d):
        if isinstance(d, dict):
            return DotDict({k: to_dot_dict(v) for k, v in d.items()})
        return d

    payment_options_obj = to_dot_dict(payment_options)

    # Get passenger email from session or user
    passenger_email = guest_email
    if not passenger_email and current_user.is_authenticated:
        passenger_email = current_user.email

    return render_template_string(
        BASE_TEMPLATE,
        title="Book Flight",
        content=render_template_string(
            BOOK_CONTENT,
            deal=deal.to_dict(),
            payment_verified=payment_verified,
            passenger_email=passenger_email,
            payment_options=payment_options_obj,
            booking_url_encoded=quote(deal.booking_url or "", safe=""),
            platform_wallet=XRPL_CONFIG["platform_wallet_address"],
            network=XRPL_CONFIG["network"].upper()
        ),
        current_user=current_user
    )


def trigger_booking_fulfillment(deal, payment, guest_email=None):
    """
    Trigger the booking fulfillment process after payment is verified.

    This initiates the full fulfillment flow:
    1. Creates a booking record
    2. Determines fulfillment type (self-service, automated, manual)
    3. Sends appropriate emails
    4. Queues vendor payment if automated

    Args:
        deal: The Deal object
        payment: The Payment object
        guest_email: Email for guest checkouts (when user is not authenticated)
    """
    try:
        from booking_fulfillment import BookingFulfillmentManager

        # Get the user (may be None for guests)
        user = User.query.get(payment.user_id) if payment.user_id else None

        # For guests, create a minimal user-like object
        if not user and guest_email:
            class GuestUser:
                def __init__(self, email):
                    self.id = None
                    self.email = email
                    self.name = "Guest"
                    self.preferred_language = "en"
            user = GuestUser(guest_email)
        elif not user:
            logger.error(f"No user found and no guest email for payment {payment.id}")
            return

        # Use the fulfillment manager
        manager = BookingFulfillmentManager(db.session)
        result = manager.create_booking(deal, payment, user)

        if result.get("success"):
            logger.info(f"Booking fulfillment initiated: {result}")
        else:
            logger.error(f"Booking fulfillment failed: {result}")

    except ImportError:
        # Fallback if booking_fulfillment module not available
        logger.warning("booking_fulfillment module not available, using fallback")
        try:
            # Create a basic booking record
            booking = Booking(
                user_id=payment.user_id,
                deal_id=deal.id,
                payment_id=payment.id,
                passenger_email=guest_email,  # Store guest email
                status='pending_fulfillment',
                created_at=datetime.utcnow()
            )
            db.session.add(booking)
            db.session.commit()

            # Determine recipient email
            recipient_email = guest_email
            if not recipient_email and payment.user_id:
                user = User.query.get(payment.user_id)
                if user:
                    recipient_email = user.email

            # Send confirmation email
            if recipient_email:
                from email_service import send_booking_confirmation
                send_booking_confirmation(
                    user_email=recipient_email,
                    deal=deal,
                    booking=booking
                )
            logger.info(f"Booking fulfillment triggered (fallback) for deal {deal.deal_id}")

        except Exception as e:
            logger.error(f"Fallback booking fulfillment error: {e}")

    except Exception as e:
        logger.error(f"Error triggering booking fulfillment: {e}")


# --- COMPLETE BOOKING ROUTE ---

@app.route("/complete-booking/<deal_id>", methods=["POST"])
def complete_booking(deal_id):
    """
    Process passenger details and complete the booking.

    This route handles:
    1. Collecting passenger information from the form
    2. Triggering automated or self-service booking based on user choice
    3. Redirecting to confirmation page
    """
    # Check authentication or guest checkout
    is_guest = session.get('guest_checkout')
    if not current_user.is_authenticated and not is_guest:
        flash("Please complete checkout first.", "error")
        return redirect(f"/book/{deal_id}")

    # Get the deal
    deal = Deal.query.filter_by(deal_id=deal_id).first()
    if not deal:
        flash("Deal not found.", "error")
        return redirect("/")

    # Verify payment exists
    user_id = current_user.id if current_user.is_authenticated else None
    if user_id:
        payment = Payment.query.filter_by(
            user_id=user_id,
            deal_id=deal.id,
            status='verified'
        ).first()
    else:
        payment = Payment.query.filter_by(
            deal_id=deal.id,
            destination_tag=deal.destination_tag,
            status='verified'
        ).order_by(Payment.created_at.desc()).first()

    if not payment:
        flash("Payment not verified. Please complete payment first.", "error")
        return redirect(f"/book/{deal_id}")

    # Collect passenger details from form
    passenger_data = {
        "first_name": request.form.get("first_name", "").strip(),
        "last_name": request.form.get("last_name", "").strip(),
        "email": request.form.get("email", "").strip(),
        "phone": request.form.get("phone", "").strip(),
        "date_of_birth": request.form.get("date_of_birth", ""),
        "gender": request.form.get("gender", ""),
        "passport_number": request.form.get("passport_number", "").strip(),
        "passport_expiry": request.form.get("passport_expiry", ""),
        "passport_country": request.form.get("passport_country", "").strip(),
        "nationality": request.form.get("nationality", "").strip(),
        "known_traveler_number": request.form.get("known_traveler_number", "").strip(),
    }

    # Validate required fields
    required_fields = ["first_name", "last_name", "email", "phone", "date_of_birth", "gender"]
    missing = [f for f in required_fields if not passenger_data.get(f)]
    if missing:
        flash(f"Please fill in required fields: {', '.join(missing)}", "error")
        return redirect(f"/book/{deal_id}")

    fulfillment_type = request.form.get("fulfillment_type", "automated")

    # Get or create booking record
    booking = Booking.query.filter_by(
        deal_id=deal.id,
        payment_id=payment.id
    ).first()

    if not booking:
        booking = Booking(
            user_id=user_id,
            deal_id=deal.id,
            payment_id=payment.id,
            status='pending_fulfillment',
            fulfillment_type=fulfillment_type,
            created_at=datetime.utcnow()
        )
        db.session.add(booking)

    # Update booking with passenger details
    booking.passenger_name = f"{passenger_data['first_name']} {passenger_data['last_name']}"
    booking.passenger_email = passenger_data['email']
    booking.fulfillment_type = fulfillment_type
    db.session.commit()

    # Store passenger data in session for the fulfillment process
    session['passenger_data'] = passenger_data
    session['booking_id'] = booking.id

    if fulfillment_type == "automated":
        # Trigger automated booking
        try:
            result = execute_automated_booking(booking, deal, passenger_data)

            if result.get("success"):
                booking.status = "booked"
                booking.confirmation_code = result.get("confirmation_code")
                booking.booked_at = datetime.utcnow()
                db.session.commit()

                # Release escrow if this booking has one
                escrow = Escrow.query.filter_by(booking_id=booking.id, status='pending').first()
                if escrow:
                    try:
                        from xrpl_escrow import XRPLEscrowManager, EscrowPayment, EscrowStatus
                        manager = XRPLEscrowManager()

                        # Reconstruct escrow in manager
                        manager._escrows[escrow.escrow_id] = EscrowPayment(
                            escrow_id=escrow.escrow_id,
                            booking_id=escrow.booking_id or 0,
                            deal_id=escrow.deal_id,
                            sender_address=escrow.sender_address,
                            destination_address=escrow.destination_address,
                            amount_xrp=escrow.amount_xrp,
                            amount_drops=escrow.amount_drops,
                            sequence=escrow.sequence,
                            condition=escrow.condition,
                            fulfillment=escrow.fulfillment,
                            cancel_after=escrow.cancel_after,
                            finish_after=escrow.finish_after,
                            status=EscrowStatus.PENDING,
                            create_tx_hash=escrow.create_tx_hash,
                            finish_tx_hash=None,
                            cancel_tx_hash=None,
                            created_at=escrow.created_at,
                            updated_at=escrow.updated_at,
                        )

                        release_result = manager.release_escrow(
                            escrow_id=escrow.escrow_id,
                            confirmation_code=result.get("confirmation_code"),
                        )

                        if release_result.get("success"):
                            escrow.status = "released"
                            escrow.finish_tx_hash = release_result.get("tx_hash")
                            escrow.confirmation_code = result.get("confirmation_code")
                            escrow.released_at = datetime.utcnow()
                            escrow.updated_at = datetime.utcnow()
                            db.session.commit()
                            logger.info(f"Escrow {escrow.escrow_id} auto-released after booking success")
                        else:
                            logger.warning(f"Failed to auto-release escrow {escrow.escrow_id}: {release_result.get('error')}")
                    except Exception as e:
                        logger.error(f"Escrow release error for booking {booking.id}: {e}")

                # --- Node Consent Economy: Allocate booking fee ---
                try:
                    from node_consent_economy import node_consent_economy
                    fee_usd = deal.platform_fee_usd or 0
                    if fee_usd > 0 and current_user.is_authenticated:
                        allocation = node_consent_economy.allocate_booking_fee(
                            deal_id=deal.deal_id,
                            fee_usd=float(fee_usd),
                            serving_node_user_id=current_user.id,
                            booking_id=booking.id
                        )
                        if allocation.get("success"):
                            logger.info(f"Fee allocation created for deal {deal.deal_id}: ${fee_usd:.2f}")
                except Exception as alloc_err:
                    logger.warning(f"Fee allocation failed for booking {booking.id} (non-blocking): {alloc_err}")

                # Send confirmation email
                send_booking_confirmation_email(booking, deal, passenger_data)

                flash(f"Booking completed! Confirmation code: {result.get('confirmation_code')}", "success")
                return redirect(f"/booking-confirmation/{booking.id}")
            else:
                # Automated booking failed, fall back to manual agent
                booking.status = "processing"
                booking.fulfillment_type = "manual_agent"
                booking.fulfillment_notes = f"Automated booking failed: {result.get('error')}. Queued for manual processing."
                db.session.commit()

                # Notify agents
                notify_agents_for_booking(booking, deal, passenger_data)

                flash("Your booking is being processed by our team. You'll receive confirmation shortly.", "info")
                return redirect(f"/booking-status/{booking.id}")

        except Exception as e:
            logger.error(f"Automated booking error: {e}")
            booking.status = "processing"
            booking.fulfillment_type = "manual_agent"
            booking.fulfillment_notes = f"Automated booking exception: {str(e)}"
            db.session.commit()

            flash("Your booking is being processed by our team. You'll receive confirmation shortly.", "info")
            return redirect(f"/booking-status/{booking.id}")

    else:
        # Self-service: redirect to booking status page with proxy links
        booking.status = "pending_fulfillment"
        booking.fulfillment_type = "self_service"
        booking.fulfillment_notes = "Self-service booking - awaiting customer completion via proxy"
        db.session.commit()

        # Store booking_id in session so guest users can access status page
        session['booking_id'] = booking.id

        # Send booking instructions email
        send_self_service_instructions(booking, deal, passenger_data)

        flash("Complete your booking via the proxy link, then submit your confirmation code.", "info")
        return redirect(f"/booking-status/{booking.id}")


def execute_automated_booking(booking, deal, passenger_data):
    """
    Execute automated booking using Amadeus Flight Orders API.

    Flow: price_confirm → create_booking → PNR
    The user never sees the source page. Phoenix handles everything server-side.

    Returns dict with success status, confirmation code (PNR), and order details.
    """
    try:
        from amadeus_client import AmadeusClient
        import json

        client = AmadeusClient()
        if not client.is_configured():
            logger.error("Amadeus API not configured for booking")
            return {"success": False, "error": "Booking system not configured"}

        # Get the raw Amadeus offer stored on the deal
        raw_offer = None
        if deal.amadeus_offer_data:
            try:
                raw_offer = json.loads(deal.amadeus_offer_data)
            except json.JSONDecodeError:
                logger.error(f"Invalid amadeus_offer_data on deal {deal.deal_id}")

        if not raw_offer:
            # Fallback: re-search and find matching offer
            logger.info(f"No stored offer for deal {deal.deal_id}, re-searching...")
            result = client.search_flights(
                origin=deal.origin,
                destination=deal.destination,
                departure_date=deal.departure_date.isoformat() if deal.departure_date else "",
                adults=1,
                max_results=15,
            )
            if result.get("success") and result.get("flights"):
                # Find matching flight by airline + flight number or closest price
                for flight in result["flights"]:
                    if flight.get("raw_offer"):
                        fn = flight.get("flight_number", "")
                        carrier = flight.get("airline", "")
                        if (deal.flight_number and fn and deal.flight_number in fn) or \
                           (deal.airline and carrier and deal.airline == carrier):
                            raw_offer = flight["raw_offer"]
                            break
                # If no exact match, use first offer as fallback
                if not raw_offer and result["flights"][0].get("raw_offer"):
                    raw_offer = result["flights"][0]["raw_offer"]

        if not raw_offer:
            return {"success": False, "error": "Could not find matching flight offer for booking"}

        # Step 1: Price confirmation
        logger.info(f"Confirming price for deal {deal.deal_id}...")
        price_result = client.price_confirm(raw_offer)
        if price_result.get("success"):
            confirmed_offer = price_result["confirmed_offer"]
            logger.info(f"Price confirmed: ${price_result['confirmed_price']} (was ${price_result['original_price']})")
        else:
            # Try booking with original offer if price confirm fails
            logger.warning(f"Price confirm failed: {price_result.get('error')}, attempting booking with original offer")
            confirmed_offer = raw_offer

        # Step 2: Build traveler data from passenger_data
        traveler = {
            "first_name": passenger_data.get("first_name", ""),
            "last_name": passenger_data.get("last_name", ""),
            "date_of_birth": passenger_data.get("date_of_birth", "1990-01-01"),
            "gender": passenger_data.get("gender", "MALE"),
            "email": passenger_data.get("email", booking.passenger_email or ""),
            "phone": passenger_data.get("phone", ""),
            "passport_number": passenger_data.get("passport_number"),
            "passport_expiry": passenger_data.get("passport_expiry"),
            "passport_country": passenger_data.get("passport_country", "US"),
            "nationality": passenger_data.get("nationality", "US"),
        }

        # Step 3: Create booking
        logger.info(f"Creating flight order for {deal.airline} {deal.flight_number} to {deal.destination}...")
        book_result = client.create_booking(confirmed_offer, traveler)

        if book_result.get("success"):
            logger.info(f"Booking successful! PNR={book_result['pnr']}, price=${book_result['price']}")
            return {
                "success": True,
                "confirmation_code": book_result["pnr"],
                "order_id": book_result.get("order_id"),
                "segments": book_result.get("segments", []),
                "booked_price": book_result.get("price"),
                "currency": book_result.get("currency", "USD"),
            }
        else:
            logger.warning(f"Booking failed: {book_result.get('error')}")
            return {
                "success": False,
                "error": book_result.get("error", "Booking failed"),
            }

    except Exception as e:
        logger.error(f"Automated booking error: {e}")
        return {"success": False, "error": str(e)}


def send_booking_confirmation_email(booking, deal, passenger_data):
    """Send booking confirmation email with e-ticket."""
    try:
        from email_service import send_email

        html_content = f"""
        <h2>Booking Confirmed!</h2>
        <p>Hi {passenger_data.get('first_name', 'there')},</p>
        <p>Great news! Your flight has been booked successfully.</p>

        <div style="background: #d4edda; padding: 20px; border-radius: 8px; margin: 20px 0;">
            <h3 style="margin-top: 0; color: #155724;">Confirmation Code: {booking.confirmation_code}</h3>
            <p><strong>Passenger:</strong> {passenger_data.get('first_name')} {passenger_data.get('last_name')}</p>
            <p><strong>Route:</strong> {deal.origin} to {deal.destination}</p>
            <p><strong>Airline:</strong> {deal.airline or 'N/A'}</p>
            <p><strong>Flight:</strong> {deal.flight_number or 'See confirmation'}</p>
            <p><strong>Date:</strong> {deal.departure_date}</p>
        </div>

        <p>You saved <strong>${(deal.user_savings_usd or 0):.2f}</strong> on this booking!</p>

        <p style="color: #666; font-size: 14px;">
            Your e-ticket will be sent separately by the airline to {passenger_data.get('email')}.
            Please check your email (including spam) for confirmation from {deal.airline or 'the airline'}.
        </p>

        <p>Thank you for using PHOENIX!</p>
        """

        send_email(
            to_email=passenger_data.get('email'),
            subject=f"Booking Confirmed! {deal.origin} to {deal.destination} - {booking.confirmation_code}",
            html_content=html_content
        )

        booking.eticket_sent = True
        booking.eticket_sent_at = datetime.utcnow()
        db.session.commit()

        logger.info(f"Confirmation email sent for booking {booking.id}")

    except Exception as e:
        logger.error(f"Failed to send confirmation email: {e}")


def send_self_service_instructions(booking, deal, passenger_data):
    """Send self-service booking instructions."""
    try:
        from email_service import send_email

        market = deal.arbitrage_market or 'us'
        proxy_url = f"/proxy/https://www.google.com/travel/flights?q=Flights+from+{deal.origin}+to+{deal.destination}+on+{deal.departure_date}&gl={market.lower()}"

        html_content = f"""
        <h2>Complete Your Flight Booking</h2>
        <p>Hi {passenger_data.get('first_name', 'there')},</p>
        <p>Your payment has been verified. Please complete your booking within 24 hours.</p>

        <div style="background: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0;">
            <h3>Your Flight Details</h3>
            <p><strong>Route:</strong> {deal.origin} to {deal.destination}</p>
            <p><strong>Date:</strong> {deal.departure_date}</p>
            <p><strong>Booked via:</strong> Phoenix</p>
        </div>

        <p>Click the button below to open the booking page through our regional proxy:</p>

        <a href="{proxy_url}" style="display: inline-block; background: #ff6b35; color: white; padding: 15px 30px; text-decoration: none; border-radius: 8px; margin: 20px 0;">
            Book Your Flight Now
        </a>

        <h3>Booking Instructions</h3>
        <ol>
            <li>Click the link above to access the airline site via our proxy</li>
            <li>The prices shown reflect Phoenix's optimized pricing</li>
            <li>Complete your booking with your own credit card</li>
            <li>Save your confirmation number</li>
        </ol>

        <p>You're saving <strong>${(deal.user_savings_usd or 0):.2f}</strong> on this booking!</p>
        """

        send_email(
            to_email=passenger_data.get('email'),
            subject=f"Complete Your Booking - {deal.origin} to {deal.destination}",
            html_content=html_content
        )

        logger.info(f"Self-service instructions sent for booking {booking.id}")

    except Exception as e:
        logger.error(f"Failed to send self-service instructions: {e}")


def notify_agents_for_booking(booking, deal, passenger_data):
    """Notify agents about a booking that needs manual processing."""
    logger.info(f"[AGENT NOTIFICATION] Manual booking needed for #{booking.id}")
    logger.info(f"  Passenger: {passenger_data.get('first_name')} {passenger_data.get('last_name')}")
    logger.info(f"  Email: {passenger_data.get('email')}")
    logger.info(f"  Route: {deal.origin} to {deal.destination}")
    logger.info(f"  Date: {deal.departure_date}")
    logger.info(f"  Airline: {deal.airline}")
    logger.info(f"  Market: {deal.arbitrage_market}")
    # In production, send to Slack, internal dashboard, etc.


# --- BOOKING STATUS AND CONFIRMATION PAGES ---

BOOKING_CONFIRMATION_CONTENT = """
<div class="card" style="max-width: 600px; margin: 40px auto; text-align: center;">
    <span style="font-size: 64px;">🎉</span>
    <h2 style="color: #28a745; margin: 20px 0;">Booking Confirmed!</h2>

    <div style="background: #d4edda; padding: 25px; border-radius: 12px; margin: 25px 0;">
        <h3 style="margin: 0 0 15px 0;">Confirmation Code</h3>
        <div style="font-size: 32px; font-weight: bold; letter-spacing: 4px; color: #155724;">
            {{ booking.confirmation_code or 'PENDING' }}
        </div>
    </div>

    <div style="text-align: left; background: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0;">
        <p><strong>Passenger:</strong> {{ booking.passenger_name }}</p>
        <p><strong>Route:</strong> {{ deal.origin }} → {{ deal.destination }}</p>
        <p><strong>Date:</strong> {{ deal.departure_date }}</p>
        <p><strong>Airline:</strong> {{ deal.airline or 'N/A' }}</p>
        {% if deal.user_savings_usd %}
        <p style="color: #28a745;"><strong>You saved:</strong> ${{ "%.2f"|format(deal.user_savings_usd) }}</p>
        {% endif %}
    </div>

    <p style="color: #666;">A confirmation email has been sent to {{ booking.passenger_email }}.</p>

    <a href="/dashboard" class="btn" style="margin-top: 20px;">View My Bookings</a>
</div>
"""

BOOKING_STATUS_CONTENT = """
<div class="card" style="max-width: 600px; margin: 40px auto; text-align: center;">
    <span style="font-size: 64px;">⏳</span>
    <h2 style="margin: 20px 0;">Booking In Progress</h2>

    <div style="background: #fff3cd; padding: 25px; border-radius: 12px; margin: 25px 0;">
        <h3 style="margin: 0 0 15px 0;">Status: {{ booking.status|replace('_', ' ')|title }}</h3>
        {% if booking.fulfillment_type == 'self_service' %}
        <p style="color: #856404; margin: 0;">Complete your booking via the proxy link below, then submit your confirmation code.</p>
        {% elif booking.fulfillment_type == 'manual_agent' %}
        <p style="color: #856404; margin: 0;">Our team is processing your booking. You'll receive confirmation shortly.</p>
        {% else %}
        <p style="color: #856404; margin: 0;">Your booking is being processed automatically. This page will update when complete.</p>
        {% endif %}
    </div>

    <div style="text-align: left; background: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0;">
        <p><strong>Booking ID:</strong> #{{ booking.id }}</p>
        <p><strong>Passenger:</strong> {{ booking.passenger_name }}</p>
        <p><strong>Route:</strong> {{ deal.origin }} → {{ deal.destination }}</p>
        <p><strong>Date:</strong> {{ deal.departure_date }}</p>
        <p><strong>Fulfillment:</strong> {{ booking.fulfillment_type|replace('_', ' ')|title }}</p>
    </div>

    {% if booking.fulfillment_type == 'self_service' and not booking.confirmation_code %}
    <!-- Self-Service: Proxy booking link -->
    <div style="background: #e8f5e9; padding: 20px; border-radius: 12px; margin: 20px 0; text-align: left;">
        <h4 style="margin: 0 0 10px 0; color: #2e7d32;">Step 1: Book Your Flight</h4>
        <p style="color: #555; margin-bottom: 15px;">Click below to open the airline booking page through our regional proxy. Complete the booking with your own payment method.</p>
        <a href="/proxy/https://www.google.com/travel/flights?q=Flights+from+{{ deal.origin }}+to+{{ deal.destination }}+on+{{ deal.departure_date }}"
           class="btn btn-success" target="_blank" style="display: block; text-align: center; padding: 14px;">
            Open Booking Page (Phoenix pricing)
        </a>
    </div>

    <!-- Self-Service: Submit confirmation code -->
    <div style="background: #fff8f5; border: 2px solid #ff6b35; padding: 20px; border-radius: 12px; margin: 20px 0; text-align: left;">
        <h4 style="margin: 0 0 10px 0; color: #e65100;">Step 2: Submit Your Confirmation Code</h4>
        <p style="color: #555; margin-bottom: 15px;">After you've completed booking on the airline site, enter your confirmation code below.</p>
        <form action="/submit-confirmation/{{ booking.id }}" method="POST">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
            <div style="display: flex; gap: 10px;">
                <input type="text" name="confirmation_code" required
                       placeholder="e.g. ABC123"
                       pattern="[A-Za-z0-9]{4,10}"
                       title="Confirmation codes are typically 4-10 alphanumeric characters"
                       style="flex: 1; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 18px; text-transform: uppercase; letter-spacing: 2px; color: #1a1a2e;">
                <button type="submit" class="btn" style="padding: 12px 24px; white-space: nowrap;">
                    Submit Code
                </button>
            </div>
        </form>
    </div>
    {% endif %}

    {% if booking.fulfillment_notes %}
    <div style="text-align: left; background: #f0f0f0; padding: 15px; border-radius: 8px; margin: 15px 0;">
        <p style="margin: 0; color: #666; font-size: 13px;"><strong>Notes:</strong> {{ booking.fulfillment_notes }}</p>
    </div>
    {% endif %}

    <p style="color: #666;">We'll send a confirmation email to {{ booking.passenger_email }} once complete.</p>

    <div style="margin-top: 25px;">
        <a href="/booking-status/{{ booking.id }}" class="btn" style="margin-right: 10px;">Refresh Status</a>
        <a href="/dashboard" class="btn btn-secondary">Go to Dashboard</a>
    </div>
</div>
"""


@app.route("/booking-confirmation/<int:booking_id>")
def booking_confirmation(booking_id):
    """Show booking confirmation page."""
    booking = Booking.query.get(booking_id)
    if not booking:
        flash("Booking not found.", "error")
        return redirect("/")

    # Security check - only allow owner to view
    if current_user.is_authenticated:
        if booking.user_id and booking.user_id != current_user.id:
            flash("Access denied.", "error")
            return redirect("/")
    else:
        # For guests, check session
        if session.get('booking_id') != booking_id:
            flash("Access denied.", "error")
            return redirect("/")

    deal = Deal.query.get(booking.deal_id)

    return render_template_string(
        BASE_TEMPLATE,
        title="Booking Confirmed",
        content=render_template_string(
            BOOKING_CONFIRMATION_CONTENT,
            booking=booking,
            deal=deal.to_dict() if deal else {}
        ),
        current_user=current_user
    )


@app.route("/booking-status/<int:booking_id>")
def booking_status(booking_id):
    """Show booking status page for pending bookings."""
    booking = Booking.query.get(booking_id)
    if not booking:
        flash("Booking not found.", "error")
        return redirect("/")

    # Security check
    if current_user.is_authenticated:
        if booking.user_id and booking.user_id != current_user.id:
            flash("Access denied.", "error")
            return redirect("/")
    else:
        if session.get('booking_id') != booking_id:
            flash("Access denied.", "error")
            return redirect("/")

    # If booking is complete, redirect to confirmation
    if booking.status == "booked" and booking.confirmation_code:
        return redirect(f"/booking-confirmation/{booking_id}")

    deal = Deal.query.get(booking.deal_id)

    return render_template_string(
        BASE_TEMPLATE,
        title="Booking Status",
        content=render_template_string(
            BOOKING_STATUS_CONTENT,
            booking=booking,
            deal=deal.to_dict() if deal else {}
        ),
        current_user=current_user
    )


# --- SUBMIT CONFIRMATION CODE (Self-Service Booking) ---

@app.route("/submit-confirmation/<int:booking_id>", methods=["POST"])
def submit_confirmation(booking_id):
    """
    Allow self-service users to submit their airline confirmation code.

    After a user books via the proxy link, they return here to enter
    their confirmation code. This completes the booking flow and
    releases any escrow.
    """
    booking = Booking.query.get(booking_id)
    if not booking:
        flash("Booking not found.", "error")
        return redirect("/")

    # Security check - only allow owner or session holder
    if current_user.is_authenticated:
        if booking.user_id and booking.user_id != current_user.id:
            flash("Access denied.", "error")
            return redirect("/")
    else:
        if session.get('booking_id') != booking_id:
            flash("Access denied.", "error")
            return redirect("/")

    confirmation_code = request.form.get("confirmation_code", "").strip().upper()
    if not confirmation_code or len(confirmation_code) < 4:
        flash("Please enter a valid confirmation code (at least 4 characters).", "error")
        return redirect(f"/booking-status/{booking_id}")

    # Update booking with confirmation code
    booking.confirmation_code = confirmation_code
    booking.status = "booked"
    booking.booked_at = datetime.utcnow()
    booking.fulfillment_notes = f"Self-service booking completed. Confirmation: {confirmation_code}"
    db.session.commit()

    # Release escrow if one exists for this booking
    escrow = Escrow.query.filter_by(booking_id=booking.id, status='pending').first()
    if escrow:
        try:
            from xrpl_escrow import XRPLEscrowManager, EscrowPayment, EscrowStatus
            manager = XRPLEscrowManager()

            manager._escrows[escrow.escrow_id] = EscrowPayment(
                escrow_id=escrow.escrow_id,
                booking_id=escrow.booking_id or 0,
                deal_id=escrow.deal_id,
                sender_address=escrow.sender_address,
                destination_address=escrow.destination_address,
                amount_xrp=escrow.amount_xrp,
                amount_drops=escrow.amount_drops,
                sequence=escrow.sequence,
                condition=escrow.condition,
                fulfillment=escrow.fulfillment,
                cancel_after=escrow.cancel_after,
                finish_after=escrow.finish_after,
                status=EscrowStatus.PENDING,
                create_tx_hash=escrow.create_tx_hash,
                finish_tx_hash=None,
                cancel_tx_hash=None,
                created_at=escrow.created_at,
                updated_at=escrow.updated_at,
            )

            release_result = manager.release_escrow(
                escrow_id=escrow.escrow_id,
                confirmation_code=confirmation_code,
            )

            if release_result.get("success"):
                escrow.status = "released"
                escrow.finish_tx_hash = release_result.get("tx_hash")
                escrow.confirmation_code = confirmation_code
                escrow.released_at = datetime.utcnow()
                escrow.updated_at = datetime.utcnow()
                db.session.commit()
                logger.info(f"Escrow {escrow.escrow_id} released after self-service confirmation")
            else:
                logger.warning(f"Failed to release escrow {escrow.escrow_id}: {release_result.get('error')}")
        except Exception as e:
            logger.error(f"Escrow release error for booking {booking.id}: {e}")

    # Send confirmation email
    deal = Deal.query.get(booking.deal_id)
    if deal and booking.passenger_email:
        try:
            send_booking_confirmation_email(booking, deal, {
                "email": booking.passenger_email,
                "first_name": booking.passenger_name.split()[0] if booking.passenger_name else "",
                "last_name": booking.passenger_name.split()[-1] if booking.passenger_name else "",
            })
        except Exception as e:
            logger.error(f"Failed to send confirmation email for booking {booking.id}: {e}")

    flash(f"Booking confirmed! Your confirmation code: {confirmation_code}", "success")
    return redirect(f"/booking-confirmation/{booking_id}")


# --- TRIP BUNDLE ROUTES ---

@app.route("/api/bundle/search", methods=["POST"])
def api_bundle_search():
    """
    Search flights + hotels + transfers in one call.
    Returns results from all three Amadeus verticals.
    No auth required (search is free).
    """
    from trip_bundle import bundle_manager

    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "JSON body required"}), 400

    origin = data.get("origin", "").upper()
    destination = data.get("destination", "").upper()
    departure_date = data.get("departure_date")

    if not origin or not destination or not departure_date:
        return jsonify({
            "success": False,
            "error": "origin, destination, and departure_date are required",
        }), 400

    result = bundle_manager.search_bundle(
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        return_date=data.get("return_date"),
        adults=data.get("adults", 1),
        cabin_class=data.get("cabin_class", "ECONOMY"),
        city_code=data.get("city_code"),
        check_in=data.get("check_in"),
        check_out=data.get("check_out"),
        rooms=data.get("rooms", 1),
        hotel_ratings=data.get("hotel_ratings"),
        max_hotels=data.get("max_hotels", 20),
        airport_code=data.get("airport_code"),
        transfer_type=data.get("transfer_type", "PRIVATE"),
        currency=data.get("currency", "USD"),
    )
    return jsonify(result)


@app.route("/api/bundle/create", methods=["POST"])
@login_required
def api_bundle_create():
    """
    Lock selected offers into a trip bundle.
    Requires at least 2 components (flight, hotel, transfer).
    Returns bundle_uuid and pricing breakdown.
    """
    from trip_bundle import bundle_manager

    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "JSON body required"}), 400

    result = bundle_manager.create_bundle(
        user_id=current_user.id,
        flight_offer=data.get("flight_offer"),
        hotel_offer_id=data.get("hotel_offer_id"),
        transfer_offer_id=data.get("transfer_offer_id"),
        flight_price_usd=data.get("flight_price_usd", 0),
        hotel_price_usd=data.get("hotel_price_usd", 0),
        transfer_price_usd=data.get("transfer_price_usd", 0),
        flight_savings_usd=data.get("flight_savings_usd", 0),
        hotel_savings_usd=data.get("hotel_savings_usd", 0),
        transfer_savings_usd=data.get("transfer_savings_usd", 0),
        origin=data.get("origin", ""),
        destination=data.get("destination", ""),
        departure_date=data.get("departure_date"),
        return_date=data.get("return_date"),
        adults=data.get("adults", 1),
        currency=data.get("currency", "USD"),
        completed_transactions=getattr(current_user, 'completed_transactions', 0),
    )

    if not result.get("success"):
        return jsonify(result), 400
    return jsonify(result)


@app.route("/api/bundle/<bundle_uuid>/book", methods=["POST"])
@login_required
def api_bundle_book(bundle_uuid):
    """
    Execute all Amadeus bookings for a bundle.
    Flight → Hotel → Transfer, sequential.
    Partial failures preserved — user decides on cancellation.
    """
    from trip_bundle import bundle_manager
    from models import TripBundle

    bundle = TripBundle.query.filter_by(bundle_uuid=bundle_uuid).first()
    if not bundle:
        return jsonify({"success": False, "error": "Bundle not found"}), 404

    if bundle.user_id != current_user.id:
        return jsonify({"success": False, "error": "Access denied"}), 403

    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "JSON body required"}), 400

    traveler = data.get("traveler", {})
    if not traveler.get("first_name") or not traveler.get("last_name"):
        return jsonify({"success": False, "error": "Traveler first_name and last_name required"}), 400
    if not traveler.get("email"):
        return jsonify({"success": False, "error": "Traveler email required"}), 400

    result = bundle_manager.book_bundle(
        bundle_id=bundle.id,
        traveler=traveler,
        payment=data.get("payment"),
    )
    return jsonify(result)


@app.route("/api/bundle/<bundle_uuid>", methods=["GET"])
@login_required
def api_bundle_get(bundle_uuid):
    """Get bundle details and component statuses."""
    from trip_bundle import bundle_manager
    from models import TripBundle

    bundle = TripBundle.query.filter_by(bundle_uuid=bundle_uuid).first()
    if not bundle:
        return jsonify({"success": False, "error": "Bundle not found"}), 404

    if bundle.user_id != current_user.id:
        return jsonify({"success": False, "error": "Access denied"}), 403

    return jsonify(bundle_manager.get_bundle(bundle_uuid))


# --- PROXY ROUTES ---

@app.route("/proxy/<path:encoded_url>", methods=["GET", "POST"])
@login_required
def proxy(encoded_url):
    """
    Proxy requests to airline sites with bidirectional translation.

    GET: Fetches page, translates content to user's language, injects live translation JS
    POST: Translates form inputs to site's language, forwards to airline site
    """
    try:
        target_url = unquote(encoded_url)
        parsed = urlparse(target_url)

        if not any(domain in parsed.netloc for domain in ALLOWED_PROXY_DOMAINS):
            return jsonify({"error": f"Domain not allowed: {parsed.netloc}"}), 403

        proxies = get_proxy_for_market("JP")

        user_language = current_user.preferred_language or 'en'

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ja,en;q=0.9",
        }

        if request.method == "POST":
            # Handle form submission with translation
            form_data = request.form.to_dict()

            # Detect site language from referer or default to Japanese for JP sites
            site_lang = "ja" if ".jp" in parsed.netloc or ".co.jp" in parsed.netloc else "en"

            # Translate form inputs from user's language to site's language
            if user_language != site_lang:
                form_data = translate_form_data(form_data, user_language, site_lang)

            # Forward the translated form to the target site
            resp = http_requests.post(
                target_url,
                data=form_data,
                headers=headers,
                proxies=proxies,
                timeout=30,
                allow_redirects=False
            )

            # Handle redirects by rewriting Location header
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("Location", "")
                if location:
                    # Make redirect URL absolute and proxy it
                    if not location.startswith("http"):
                        location = urljoin(target_url, location)
                    if any(d in location for d in ALLOWED_PROXY_DOMAINS):
                        location = f"/proxy/{quote(location, safe='')}"
                    response = redirect(location, code=resp.status_code)
                    return response
        else:
            # GET request
            resp = http_requests.get(target_url, headers=headers, proxies=proxies, timeout=30)

        content_type = resp.headers.get("Content-Type", "text/html")

        if "text/html" in content_type:
            # Get translation settings
            translate_enabled = request.args.get('translate', 'auto')

            # Detect source language from HTML
            source_lang = detect_language_from_html(resp.text)

            # Rewrite URLs and add banner
            content = rewrite_urls(resp.text, target_url, source_lang, user_language, translate_enabled)

            # Inject live translation JavaScript for form inputs
            if source_lang != user_language:
                translation_script = get_translation_script(source_lang, user_language, "/api/translate")
                content = content.replace("</body>", f"{translation_script}</body>", 1)

            # Apply page content translation if enabled
            if translate_enabled != 'off' and source_lang != user_language:
                if translate_enabled == 'on' or (translate_enabled == 'auto' and source_lang != user_language):
                    content = translate_html(content, source=source_lang, target=user_language)
        else:
            content = resp.content

        response = Response(content, status=resp.status_code)
        response.headers["Content-Type"] = content_type
        return response

    except Exception as e:
        return jsonify({"error": str(e)}), 500


def rewrite_urls(html_content, base_url, source_lang='ja', target_lang='en', translate_mode='auto'):
    """Rewrite URLs in HTML to route through proxy with translation controls."""
    parsed_base = urlparse(base_url)
    base_domain = f"{parsed_base.scheme}://{parsed_base.netloc}"

    # Determine translation status for banner display
    is_translating = translate_mode == 'on' or (translate_mode == 'auto' and source_lang != target_lang)
    translate_toggle = 'off' if is_translating else 'on'
    toggle_text = 'View Original' if is_translating else 'Translate Page'
    source_name = get_language_name(source_lang)
    target_name = get_language_name(target_lang)

    # Add proxy banner with translation controls
    banner = f'''
    <div style="position:fixed;top:0;left:0;right:0;background:#ff6b35;color:white;padding:10px;text-align:center;z-index:99999;font-family:sans-serif;display:flex;justify-content:center;align-items:center;gap:20px;">
        <span>PHOENIX - Booking via JP market</span>
        <span style="color:#ffc107;">|</span>
        <span style="font-size:12px;">{source_name} → {target_name}</span>
        <a href="?translate={translate_toggle}" style="color:white;background:#ff8c00;padding:4px 12px;border-radius:4px;text-decoration:none;font-size:12px;">{toggle_text}</a>
        <span style="color:#ffc107;">|</span>
        <a href="/deals" style="color:white;">Back to Deals</a>
    </div>
    <div style="height:50px;"></div>
    '''
    html_content = html_content.replace("<body>", f"<body>{banner}", 1)

    # Rewrite URLs (preserve translate mode in proxied links)
    def rewrite_link(m):
        attr, url = m.group(1), m.group(2)
        if any(d in url for d in ALLOWED_PROXY_DOMAINS):
            proxied = f'/proxy/{quote(url, safe="")}'
            if translate_mode != 'auto':
                proxied += f'?translate={translate_mode}'
            return f'{attr}="{proxied}"'
        return m.group(0)

    html_content = re.sub(
        r'(href|src|action)="(https?://[^"]+)"',
        rewrite_link,
        html_content
    )

    return html_content


# --- API ROUTES ---

@app.route("/api/save-guest-email", methods=["POST"])
def save_guest_email():
    """Save guest email to session for checkout."""
    data = request.get_json()
    email = data.get('email', '').strip()
    if email:
        session['guest_email'] = email
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'No email provided'})


@app.route("/api/deals")
def api_deals():
    """JSON API for deals — reads from database."""
    get_xrp_price()

    active_deals = Deal.query.filter(
        Deal.is_active == True,
        db.or_(Deal.expires_at == None, Deal.expires_at > datetime.utcnow())
    ).order_by(Deal.user_savings_usd.desc()).limit(50).all()

    return jsonify({
        "deals": [{
            "deal_id": d.deal_id,
            "airline": d.airline,
            "flight_number": d.flight_number,
            "origin": d.origin,
            "destination": d.destination,
            "departure_date": d.departure_date.isoformat() if d.departure_date else None,
            "home_market": d.home_market,
            "home_price_usd": d.home_price_usd,
            "arbitrage_market": "Phoenix",  # Never expose proxy market codes
            "arbitrage_price_usd": d.arbitrage_price_usd,
            "gross_savings_usd": d.gross_savings_usd,
            "platform_fee_usd": d.platform_fee_usd,
            "user_savings_usd": d.user_savings_usd,
            "savings_percent": d.savings_percent,
            "booking_url": d.booking_url,
            "expires_at": d.expires_at.isoformat() if d.expires_at else None,
        } for d in active_deals],
        "xrp_price": XRPL_CONFIG["xrp_usd_rate"],
        "count": len(active_deals)
    })


@app.route("/api/deals/create", methods=["POST"])
@csrf.exempt
def api_create_deal():
    """Create a deal from selected flights for checkout (supports multi-leg)."""
    data = request.get_json()

    if not data:
        return jsonify({"error": "No data provided"}), 400

    try:
        # Generate unique deal ID
        deal_id = secrets.token_hex(8)

        # Check if this is a multi-leg deal
        flights = data.get("flights", [])
        is_multi_leg = data.get("is_multi_leg", False) or len(flights) > 1

        if is_multi_leg and flights:
            # Multi-leg deal - store all flight legs
            first_flight = flights[0]
            last_flight = flights[-1]

            # Extract first/last leg info for summary
            first_route = first_flight.get("route", "").split(" → ")
            last_route = last_flight.get("route", "").split(" → ")
            origin = first_route[0] if first_route else ""
            destination = last_route[-1] if last_route else ""

            # Parse first departure date
            departure_date = None
            first_date_str = first_flight.get("date", "")
            if first_date_str:
                try:
                    departure_date = datetime.strptime(first_date_str.split(",")[0].strip(), "%Y-%m-%d").date()
                except:
                    pass

            # Totals from data
            total_cheapest_price = float(data.get("total_cheapest_price", 0))
            total_us_price = float(data.get("total_us_price", 0))
            total_savings = float(data.get("total_savings", 0))
            service_fee = float(data.get("service_fee", 0))
            total_price = float(data.get("total_price", 0))

            # Create multi-leg deal
            deal = Deal(
                deal_id=deal_id,
                airline=", ".join(set(f.get("airline", "Various") for f in flights)),
                flight_number=", ".join(filter(None, (f.get("flight_number") for f in flights))),
                origin=origin,
                destination=destination,
                departure_date=departure_date,
                home_market="US",
                home_price_usd=total_us_price,
                arbitrage_market=first_flight.get("cheapest_market", "US"),
                arbitrage_price_usd=total_cheapest_price,
                gross_savings_usd=total_savings,
                platform_fee_usd=service_fee,
                user_savings_usd=total_savings - service_fee if total_savings > service_fee else 0,
                savings_percent=round((total_savings / total_us_price * 100) if total_us_price > 0 else 0, 1),
                is_multi_leg=True,
                flight_legs=json.dumps(flights),
                total_legs=len(flights),
                created_at=datetime.utcnow()
            )
        else:
            # Single flight deal (legacy behavior)
            airline = data.get("airline", "Multiple Airlines")
            flight_number = data.get("flight_number", "")
            route = data.get("route", "")
            route_parts = route.split(" → ") if route else ["", ""]
            origin = route_parts[0] if len(route_parts) > 0 else ""
            destination = route_parts[-1] if len(route_parts) > 1 else ""
            date_str = data.get("date", "")
            cheapest_market = data.get("cheapest_market", "US")
            cheapest_price = float(data.get("cheapest_price", 0))
            us_price = float(data.get("us_price", 0))
            savings = float(data.get("savings", 0))
            service_fee = float(data.get("service_fee", 0))
            total_price = float(data.get("total_price", 0))

            # Parse date
            departure_date = None
            if date_str:
                try:
                    departure_date = datetime.strptime(date_str.split(",")[0].strip(), "%Y-%m-%d").date()
                except:
                    pass

            # Calculate user savings (after platform fee)
            user_savings = savings - service_fee if savings > service_fee else 0

            # Create single-leg deal
            deal = Deal(
                deal_id=deal_id,
                airline=airline,
                flight_number=flight_number,
                origin=origin,
                destination=destination,
                departure_date=departure_date,
                home_market="US",
                home_price_usd=us_price,
                arbitrage_market=cheapest_market,
                arbitrage_price_usd=cheapest_price,
                gross_savings_usd=savings,
                platform_fee_usd=service_fee,
                user_savings_usd=user_savings,
                savings_percent=round((savings / us_price * 100) if us_price > 0 else 0, 1),
                is_multi_leg=False,
                total_legs=1,
                created_at=datetime.utcnow()
            )

        db.session.add(deal)
        db.session.commit()

        # Store in session for guest users
        if not current_user.is_authenticated:
            session['pending_deal'] = deal_id

        return jsonify({
            "success": True,
            "deal_id": deal_id,
            "total_price": total_price if is_multi_leg else float(data.get("total_price", 0)),
            "is_multi_leg": is_multi_leg,
            "total_legs": len(flights) if is_multi_leg else 1,
            "redirect_url": f"/save-deal/{deal_id}"
        })

    except Exception as e:
        logging.error(f"Error creating deal: {e}")
        return jsonify({"error": str(e)}), 500


# --- PAYMENT API ENDPOINTS ---

@app.route("/api/payment/stripe/create", methods=["POST"])
@csrf.exempt
def api_stripe_create():
    """
    Create a Stripe Checkout session for card payment.

    Request JSON:
        {
            "deal_id": "abc123",
            "amount": 752.50
        }

    Response JSON:
        {
            "session_id": "cs_xxx",
            "checkout_url": "https://checkout.stripe.com/...",
            "publishable_key": "pk_xxx"
        }
    """
    if not current_user.is_authenticated:
        return jsonify({"error": "Login required"}), 401

    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    deal_id = data.get("deal_id")
    amount = data.get("amount", 0)

    if not deal_id:
        return jsonify({"error": "Deal ID required"}), 400

    # Get the deal
    deal = Deal.query.filter_by(deal_id=deal_id).first()
    if not deal:
        return jsonify({"error": "Deal not found"}), 404

    # Calculate total if not provided
    if not amount:
        amount = (deal.arbitrage_price_usd or 0) + (deal.platform_fee_usd or 0)

    try:
        # Create Stripe checkout session
        result = create_stripe_checkout_session(
            deal_id=deal_id,
            fee_usd=amount,
            user_email=current_user.email,
            success_url=request.host_url.rstrip('/') + f"/payment/success?deal_id={deal_id}",
            cancel_url=request.host_url.rstrip('/') + f"/book/{deal_id}"
        )

        if "error" in result:
            return jsonify({"error": result["error"]}), 400

        return jsonify(result)

    except Exception as e:
        logger.error(f"Stripe create error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/payment/coinbase/create", methods=["POST"])
@csrf.exempt
def api_coinbase_create():
    """
    Create a Coinbase Commerce charge for cryptocurrency payment.

    Supports: BTC, ETH, LTC, DOGE, BCH, USDC, DAI, SHIB, and more.

    Request JSON:
        {
            "deal_id": "abc123",
            "amount": 752.50
        }

    Response JSON:
        {
            "charge_id": "xxx",
            "charge_code": "ABC123",
            "hosted_url": "https://commerce.coinbase.com/charges/...",
            "supported_coins": ["BTC", "ETH", ...]
        }
    """
    if not current_user.is_authenticated:
        return jsonify({"error": "Login required"}), 401

    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    deal_id = data.get("deal_id")
    amount = data.get("amount", 0)

    if not deal_id:
        return jsonify({"error": "Deal ID required"}), 400

    # Get the deal
    deal = Deal.query.filter_by(deal_id=deal_id).first()
    if not deal:
        return jsonify({"error": "Deal not found"}), 404

    # Calculate total if not provided
    if not amount:
        amount = (deal.arbitrage_price_usd or 0) + (deal.platform_fee_usd or 0)

    try:
        # Create Coinbase Commerce charge
        result = create_coinbase_charge(
            deal_id=deal_id,
            fee_usd=amount,
            user_email=current_user.email,
            redirect_url=request.host_url.rstrip('/') + f"/payment/success",
            cancel_url=request.host_url.rstrip('/') + f"/book/{deal_id}"
        )

        if "error" in result:
            return jsonify({"error": result["error"]}), 400

        # Store charge code in session for verification
        session[f'coinbase_charge_{deal_id}'] = result.get('charge_code')

        return jsonify(result)

    except Exception as e:
        logger.error(f"Coinbase create error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/payment/verify", methods=["POST"])
@csrf.exempt
@limiter.limit("20 per hour")
def api_payment_verify():
    """
    Verify a payment across any method.

    Request JSON:
        {
            "method": "card|xrp|rlusd|crypto",
            "deal_id": "abc123",
            "session_id": "cs_xxx",        # For Stripe
            "charge_code": "ABC123",       # For Coinbase
            "destination_tag": 12345       # For XRP/RLUSD
        }

    Response JSON:
        {
            "verified": true/false,
            "deal_id": "abc123",
            "amount_usd": 752.50,
            "tx_hash": "...",
            "error": "..." (if not verified)
        }
    """
    if not current_user.is_authenticated:
        return jsonify({"error": "Login required"}), 401

    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    method = data.get("method")
    deal_id = data.get("deal_id")

    if not method or not deal_id:
        return jsonify({"error": "Method and deal_id required"}), 400

    # Get the deal
    deal = Deal.query.filter_by(deal_id=deal_id).first()
    if not deal:
        return jsonify({"error": "Deal not found"}), 404

    total_amount = (deal.arbitrage_price_usd or 0) + (deal.platform_fee_usd or 0)

    try:
        result = verify_payment(
            method=method,
            deal_id=deal_id,
            session_id=data.get("session_id"),
            charge_code=data.get("charge_code"),
            destination_tag=data.get("destination_tag", deal.destination_tag),
            expected_amount=total_amount if method in ["rlusd", "card"] else None
        )

        if result.get("verified"):
            # Create payment record
            payment = Payment(
                user_id=current_user.id,
                deal_id=deal.id,
                payment_method=method,
                amount_usd=total_amount,
                tx_hash=result.get("tx_hash") or result.get("payment_intent") or result.get("charge_code"),
                status='verified',
                verified_at=datetime.utcnow()
            )
            db.session.add(payment)
            db.session.commit()

            # Trigger booking fulfillment
            trigger_booking_fulfillment(deal, payment)

        return jsonify(result)

    except Exception as e:
        logger.error(f"Payment verify error: {e}")
        return jsonify({"verified": False, "error": str(e)}), 500


@app.route("/payment/success")
@login_required
def payment_success_handler():
    """Handle successful payment redirects from Stripe/Coinbase."""
    deal_id = request.args.get("deal_id")
    session_id = request.args.get("session_id")
    charge_code = request.args.get("charge_code")

    if not deal_id:
        flash("Missing deal information", "error")
        return redirect("/dashboard")

    deal = Deal.query.filter_by(deal_id=deal_id).first()
    if not deal:
        flash("Deal not found", "error")
        return redirect("/dashboard")

    total_amount = (deal.arbitrage_price_usd or 0) + (deal.platform_fee_usd or 0)

    # Check if payment already verified
    existing_payment = Payment.query.filter_by(
        user_id=current_user.id,
        deal_id=deal.id,
        status='verified'
    ).first()

    if existing_payment:
        flash("Payment already verified!", "success")
        return redirect(f"/book/{deal_id}")

    # Verify the payment based on what params we have
    verified = False
    payment_method = None
    tx_ref = None

    if session_id:
        # Stripe payment
        result = verify_stripe_session(session_id)
        if result.get("verified"):
            verified = True
            payment_method = "card"
            tx_ref = result.get("payment_intent")

    elif charge_code or session.get(f'coinbase_charge_{deal_id}'):
        # Coinbase payment
        code = charge_code or session.get(f'coinbase_charge_{deal_id}')
        result = verify_coinbase_charge(code)
        if result.get("verified"):
            verified = True
            payment_method = "crypto"
            tx_ref = result.get("charge_code")

    if verified:
        # Create payment record
        payment = Payment(
            user_id=current_user.id,
            deal_id=deal.id,
            payment_method=payment_method,
            amount_usd=total_amount,
            tx_hash=tx_ref,
            status='verified',
            verified_at=datetime.utcnow()
        )
        db.session.add(payment)
        db.session.commit()

        # Trigger booking fulfillment
        trigger_booking_fulfillment(deal, payment)

        flash("Payment verified successfully! You can now book your flight.", "success")
    else:
        flash("Payment verification pending. Please wait a moment and refresh.", "warning")

    return redirect(f"/book/{deal_id}")


# --- ESCROW PAYMENT API ---

@app.route("/api/escrow/create", methods=["POST"])
@csrf.exempt
@limiter.limit("10 per hour")
def api_escrow_create():
    """
    Create an escrow payment for trustless booking.

    Request JSON:
        {
            "deal_id": "abc123",
            "sender_address": "rXXX...",  # Customer's XRP wallet
            "amount_xrp": 100.0           # Optional, calculates from deal if not provided
        }

    Response JSON:
        {
            "success": true,
            "escrow_id": "ESC-123-ABCD",
            "amount_xrp": 100.0,
            "destination": "rPlatformWallet...",
            "condition": "A025...",
            "transaction": { ... },        # Unsigned EscrowCreate tx
            "cancel_after": "2024-01-15T12:00:00"
        }
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    deal_id = data.get("deal_id")
    sender_address = data.get("sender_address")

    if not deal_id or not sender_address:
        return jsonify({"error": "deal_id and sender_address required"}), 400

    # Get the deal
    deal = Deal.query.filter_by(deal_id=deal_id).first()
    if not deal:
        return jsonify({"error": "Deal not found"}), 404

    # Calculate amount in XRP
    total_usd = (deal.arbitrage_price_usd or 0) + (deal.platform_fee_usd or 0)
    xrp_rate = XRPL_CONFIG.get("xrp_usd_rate", 2.50)
    amount_xrp = data.get("amount_xrp") or (total_usd / xrp_rate)

    try:
        from xrpl_escrow import XRPLEscrowManager

        manager = XRPLEscrowManager()

        # Create escrow payment details
        result = manager.create_escrow_payment(
            booking_id=0,  # Will be set when booking is created
            deal_id=deal_id,
            amount_xrp=amount_xrp,
            sender_address=sender_address,
        )

        if result.get("success"):
            # Store escrow in database
            user_id = current_user.id if current_user.is_authenticated else None

            escrow = Escrow(
                escrow_id=result.get("escrow_id"),
                deal_id=deal_id,
                user_id=user_id,
                sender_address=sender_address,
                destination_address=result.get("destination"),
                amount_xrp=amount_xrp,
                amount_drops=result.get("amount_drops"),
                condition=result.get("condition"),
                fulfillment=manager._escrows[result.get("escrow_id")].fulfillment,
                cancel_after=datetime.fromisoformat(result.get("cancel_after")),
                status="pending",
            )
            db.session.add(escrow)
            db.session.commit()

            # Don't expose fulfillment to client
            result.pop("fulfillment", None)

        return jsonify(result)

    except Exception as e:
        logger.error(f"Escrow creation error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/escrow/confirm", methods=["POST"])
@csrf.exempt
def api_escrow_confirm():
    """
    Confirm an escrow was created on-chain.

    Request JSON:
        {
            "escrow_id": "ESC-123-ABCD",
            "tx_hash": "ABC123...",
            "sequence": 12345
        }

    Response JSON:
        {
            "success": true,
            "escrow_id": "ESC-123-ABCD",
            "status": "confirmed",
            "message": "Escrow confirmed. Booking will proceed."
        }
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    escrow_id = data.get("escrow_id")
    tx_hash = data.get("tx_hash")
    sequence = data.get("sequence")

    if not all([escrow_id, tx_hash, sequence]):
        return jsonify({"error": "escrow_id, tx_hash, and sequence required"}), 400

    # Get escrow from database
    escrow = Escrow.query.filter_by(escrow_id=escrow_id).first()
    if not escrow:
        return jsonify({"error": "Escrow not found"}), 404

    try:
        from xrpl_escrow import XRPLEscrowManager

        manager = XRPLEscrowManager()

        # Recreate escrow in manager's memory
        manager._escrows[escrow_id] = type('EscrowPayment', (), {
            'escrow_id': escrow.escrow_id,
            'condition': escrow.condition,
            'amount_drops': escrow.amount_drops,
            'sender_address': escrow.sender_address,
            'sequence': sequence,
            'status': type('EscrowStatus', (), {'PENDING': type('', (), {'value': 'pending'})()})().PENDING,
        })()

        result = manager.confirm_escrow_created(
            escrow_id=escrow_id,
            tx_hash=tx_hash,
            sequence=sequence,
        )

        if result.get("success"):
            # Update database
            escrow.create_tx_hash = tx_hash
            escrow.sequence = sequence
            escrow.updated_at = datetime.utcnow()
            db.session.commit()

            # Create booking and trigger fulfillment
            deal = Deal.query.filter_by(deal_id=escrow.deal_id).first()
            if deal:
                # Create a payment record for tracking
                payment = Payment(
                    user_id=escrow.user_id,
                    deal_id=deal.id,
                    payment_method='escrow',
                    amount_usd=escrow.amount_xrp * XRPL_CONFIG.get("xrp_usd_rate", 2.50),
                    destination_tag=int(escrow.escrow_id.split('-')[1]) if '-' in escrow.escrow_id else 0,
                    expected_xrp=escrow.amount_xrp,
                    tx_hash=tx_hash,
                    status='verified',
                    verified_at=datetime.utcnow()
                )
                db.session.add(payment)
                db.session.commit()

                # Create the booking record directly so we can link the escrow
                booking = Booking(
                    user_id=escrow.user_id,
                    deal_id=deal.id,
                    payment_id=payment.id,
                    status='pending_fulfillment',
                    fulfillment_type='automated',
                )
                db.session.add(booking)
                db.session.commit()

                # Link escrow to booking
                escrow.booking_id = booking.id
                db.session.commit()

                # Trigger booking automation
                trigger_booking_fulfillment(deal, payment)

        return jsonify(result)

    except Exception as e:
        logger.error(f"Escrow confirmation error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/escrow/release", methods=["POST"])
@csrf.exempt
def api_escrow_release():
    """
    Release escrow after successful booking (admin/system only).

    Request JSON:
        {
            "escrow_id": "ESC-123-ABCD",
            "confirmation_code": "ABC123"
        }
    """
    # Check admin or system access
    if not current_user.is_authenticated or not current_user.is_admin:
        return jsonify({"error": "Admin access required"}), 403

    data = request.get_json()
    escrow_id = data.get("escrow_id")
    confirmation_code = data.get("confirmation_code")

    if not escrow_id or not confirmation_code:
        return jsonify({"error": "escrow_id and confirmation_code required"}), 400

    escrow = Escrow.query.filter_by(escrow_id=escrow_id).first()
    if not escrow:
        return jsonify({"error": "Escrow not found"}), 404

    try:
        from xrpl_escrow import XRPLEscrowManager, EscrowPayment, EscrowStatus

        manager = XRPLEscrowManager()

        # Reconstruct escrow in manager
        manager._escrows[escrow_id] = EscrowPayment(
            escrow_id=escrow.escrow_id,
            booking_id=escrow.booking_id or 0,
            deal_id=escrow.deal_id,
            sender_address=escrow.sender_address,
            destination_address=escrow.destination_address,
            amount_xrp=escrow.amount_xrp,
            amount_drops=escrow.amount_drops,
            sequence=escrow.sequence,
            condition=escrow.condition,
            fulfillment=escrow.fulfillment,
            cancel_after=escrow.cancel_after,
            finish_after=escrow.finish_after,
            status=EscrowStatus.PENDING,
            create_tx_hash=escrow.create_tx_hash,
            finish_tx_hash=None,
            cancel_tx_hash=None,
            created_at=escrow.created_at,
            updated_at=escrow.updated_at,
        )

        result = manager.release_escrow(
            escrow_id=escrow_id,
            confirmation_code=confirmation_code,
        )

        if result.get("success"):
            escrow.status = "released"
            escrow.finish_tx_hash = result.get("tx_hash")
            escrow.confirmation_code = confirmation_code
            escrow.released_at = datetime.utcnow()
            escrow.updated_at = datetime.utcnow()
            db.session.commit()
            try:
                from event_stream import emit_payment_event
                emit_payment_event(escrow.user_id, "escrow_released", {
                    "escrow_id": escrow.escrow_id,
                    "amount": str(escrow.amount_rlusd),
                })
            except Exception:
                pass

        return jsonify(result)

    except Exception as e:
        logger.error(f"Escrow release error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/escrow/cancel", methods=["POST"])
@csrf.exempt
def api_escrow_cancel():
    """
    Cancel escrow and refund customer (after timeout).

    Request JSON:
        {
            "escrow_id": "ESC-123-ABCD",
            "reason": "Booking failed"
        }
    """
    data = request.get_json()
    escrow_id = data.get("escrow_id")
    reason = data.get("reason", "Booking failed")

    if not escrow_id:
        return jsonify({"error": "escrow_id required"}), 400

    escrow = Escrow.query.filter_by(escrow_id=escrow_id).first()
    if not escrow:
        return jsonify({"error": "Escrow not found"}), 404

    # Check ownership
    if current_user.is_authenticated and escrow.user_id:
        if escrow.user_id != current_user.id and not current_user.is_admin:
            return jsonify({"error": "Not authorized"}), 403

    try:
        from xrpl_escrow import XRPLEscrowManager, EscrowPayment, EscrowStatus

        manager = XRPLEscrowManager()

        # Reconstruct escrow in manager
        manager._escrows[escrow_id] = EscrowPayment(
            escrow_id=escrow.escrow_id,
            booking_id=escrow.booking_id or 0,
            deal_id=escrow.deal_id,
            sender_address=escrow.sender_address,
            destination_address=escrow.destination_address,
            amount_xrp=escrow.amount_xrp,
            amount_drops=escrow.amount_drops,
            sequence=escrow.sequence,
            condition=escrow.condition,
            fulfillment=escrow.fulfillment,
            cancel_after=escrow.cancel_after,
            finish_after=escrow.finish_after,
            status=EscrowStatus.PENDING,
            create_tx_hash=escrow.create_tx_hash,
            finish_tx_hash=None,
            cancel_tx_hash=None,
            created_at=escrow.created_at,
            updated_at=escrow.updated_at,
        )

        result = manager.cancel_escrow(
            escrow_id=escrow_id,
            reason=reason,
        )

        if result.get("success"):
            escrow.status = "cancelled"
            escrow.cancel_tx_hash = result.get("tx_hash")
            escrow.failure_reason = reason
            escrow.cancelled_at = datetime.utcnow()
            escrow.updated_at = datetime.utcnow()
            db.session.commit()
            try:
                from event_stream import emit_payment_event
                emit_payment_event(escrow.user_id, "escrow_cancelled", {
                    "escrow_id": escrow.escrow_id,
                    "reason": reason,
                })
            except Exception:
                pass

        return jsonify(result)

    except Exception as e:
        logger.error(f"Escrow cancel error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/escrow/<escrow_id>", methods=["GET"])
def api_escrow_status(escrow_id):
    """Get status of an escrow payment."""
    escrow = Escrow.query.filter_by(escrow_id=escrow_id).first()
    if not escrow:
        return jsonify({"error": "Escrow not found"}), 404

    # Check if expired
    if escrow.status == "pending" and escrow.cancel_after and datetime.utcnow() > escrow.cancel_after:
        escrow.status = "expired"
        db.session.commit()

    return jsonify({
        "success": True,
        "escrow": escrow.to_dict(),
    })


# --- PAYMENT WEBHOOKS ---

@app.route("/webhooks/stripe", methods=["POST"])
@csrf.exempt
def webhook_stripe():
    """
    Handle Stripe webhook events for payment confirmations.

    Events handled:
    - checkout.session.completed: Payment successful
    - checkout.session.expired: Payment expired
    """
    payload = request.get_data()
    signature = request.headers.get("Stripe-Signature", "")

    try:
        result = handle_stripe_webhook(payload, signature)

        if "error" in result:
            logger.error(f"Stripe webhook error: {result['error']}")
            return jsonify({"error": result["error"]}), 400

        if result.get("event") == "payment_completed":
            deal_id = result.get("deal_id")
            amount_usd = result.get("amount_usd", 0)

            if deal_id:
                deal = Deal.query.filter_by(deal_id=deal_id).first()
                if deal:
                    # Find user from session metadata or create anonymous payment
                    # For webhook, we may not have user context, so use deal owner
                    payment = Payment(
                        deal_id=deal.id,
                        payment_method='card',
                        amount_usd=amount_usd,
                        tx_hash=result.get("session_id"),
                        status='verified',
                        verified_at=datetime.utcnow()
                    )
                    db.session.add(payment)
                    db.session.commit()

                    logger.info(f"Stripe payment verified via webhook for deal {deal_id}")

        return jsonify({"received": True})

    except Exception as e:
        logger.error(f"Stripe webhook exception: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/webhooks/coinbase", methods=["POST"])
@csrf.exempt
def webhook_coinbase():
    """
    Handle Coinbase Commerce webhook events for crypto payment confirmations.

    Events handled:
    - charge:confirmed: Payment confirmed on blockchain
    - charge:failed: Payment failed or expired
    """
    payload = request.get_data()
    signature = request.headers.get("X-CC-Webhook-Signature", "")

    try:
        result = handle_coinbase_webhook(payload, signature)

        if "error" in result:
            logger.error(f"Coinbase webhook error: {result['error']}")
            return jsonify({"error": result["error"]}), 400

        if result.get("event") == "payment_completed":
            deal_id = result.get("deal_id")
            amount_usd = result.get("amount_usd", 0)

            if deal_id:
                deal = Deal.query.filter_by(deal_id=deal_id).first()
                if deal:
                    payment = Payment(
                        deal_id=deal.id,
                        payment_method='crypto',
                        amount_usd=amount_usd,
                        tx_hash=result.get("charge_code"),
                        status='verified',
                        verified_at=datetime.utcnow()
                    )
                    db.session.add(payment)
                    db.session.commit()

                    logger.info(f"Coinbase payment verified via webhook for deal {deal_id}")
                    audit_log("payment_verified", user_id=deal.user_id,
                              method="coinbase", deal_id=deal_id,
                              amount_usd=amount_usd)

        return jsonify({"received": True})

    except Exception as e:
        logger.error(f"Coinbase webhook exception: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/translate", methods=["POST"])
def api_translate():
    """
    Translation API endpoint for live form input translation.

    Receives text from the injected JavaScript and returns translated text.
    Used for bidirectional translation of user inputs on proxied pages.

    Request JSON:
        {
            "text": "text to translate",
            "source": "source language code",
            "target": "target language code"
        }

    Response JSON:
        {
            "translated": "translated text",
            "source": "detected or provided source language",
            "target": "target language"
        }
    """
    try:
        data = request.get_json()

        if not data or 'text' not in data:
            return jsonify({"error": "Missing 'text' field"}), 400

        text = data.get('text', '')
        source = data.get('source', 'auto')
        target = data.get('target', 'en')

        if not text.strip():
            return jsonify({"translated": text, "source": source, "target": target})

        # Auto-detect source if needed
        if source == 'auto':
            source = detect_language(text)

        # Translate
        translated = translate_text(text, source=source, target=target)

        return jsonify({
            "translated": translated,
            "source": source,
            "target": target,
            "original": text
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/languages")
def api_languages():
    """
    Get list of supported languages.

    Response JSON:
        {
            "languages": {"en": "English", "ja": "Japanese", ...},
            "count": 50
        }
    """
    return jsonify({
        "languages": SUPPORTED_LANGUAGES,
        "count": len(SUPPORTED_LANGUAGES)
    })


# --- ERROR HANDLERS ---

ERROR_404_CONTENT = """
<div class="card" style="max-width: 500px; margin: 60px auto; text-align: center;">
    <h1 style="font-size: 72px; margin: 0; color: #ff6b35;">404</h1>
    <h2>Page Not Found</h2>
    <p style="color: #666;">The page you're looking for doesn't exist or has been moved.</p>
    <a href="/" class="btn">Go Home</a>
    <a href="/deals" class="btn btn-secondary" style="margin-left: 10px;">Browse Deals</a>
</div>
"""

ERROR_500_CONTENT = """
<div class="card" style="max-width: 500px; margin: 60px auto; text-align: center;">
    <h1 style="font-size: 72px; margin: 0; color: #dc3545;">500</h1>
    <h2>Something Went Wrong</h2>
    <p style="color: #666;">We're experiencing technical difficulties. Please try again later.</p>
    <a href="/" class="btn">Go Home</a>
    <a href="javascript:location.reload()" class="btn btn-secondary" style="margin-left: 10px;">Try Again</a>
</div>
"""

ERROR_CSRF_CONTENT = """
<div class="card" style="max-width: 500px; margin: 60px auto; text-align: center;">
    <h1 style="font-size: 48px; margin: 0; color: #ffc107;">⚠️</h1>
    <h2>Session Expired</h2>
    <p style="color: #666;">Your session has expired for security reasons. Please refresh the page and try again.</p>
    <a href="javascript:location.reload()" class="btn">Refresh Page</a>
    <a href="/" class="btn btn-secondary" style="margin-left: 10px;">Go Home</a>
</div>
"""

ERROR_RATE_LIMIT_CONTENT = """
<div class="card" style="max-width: 500px; margin: 60px auto; text-align: center;">
    <h1 style="font-size: 48px; margin: 0; color: #ffc107;">🚦</h1>
    <h2>Too Many Requests</h2>
    <p style="color: #666;">You've made too many requests. Please wait a moment before trying again.</p>
    <a href="/" class="btn">Go Home</a>
</div>
"""


@app.errorhandler(404)
def not_found_error(error):
    """Handle 404 errors."""
    logger.warning(f"404 error: {request.url}")
    return render_template_string(
        BASE_TEMPLATE,
        title="Page Not Found",
        content=ERROR_404_CONTENT,
        current_user=current_user
    ), 404


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors."""
    logger.error(f"500 error: {error}")
    db.session.rollback()
    return render_template_string(
        BASE_TEMPLATE,
        title="Server Error",
        content=ERROR_500_CONTENT,
        current_user=current_user
    ), 500


@app.errorhandler(CSRFError)
def csrf_error(error):
    """Handle CSRF token errors."""
    logger.warning(f"CSRF error: {error.description}")
    return render_template_string(
        BASE_TEMPLATE,
        title="Session Expired",
        content=ERROR_CSRF_CONTENT,
        current_user=current_user
    ), 400


@app.errorhandler(429)
def rate_limit_error(error):
    """Handle rate limit errors."""
    logger.warning(f"Rate limit exceeded: {request.remote_addr}")
    return render_template_string(
        BASE_TEMPLATE,
        title="Rate Limited",
        content=ERROR_RATE_LIMIT_CONTENT,
        current_user=current_user
    ), 429


# --- HEALTH CHECK ---

@app.route("/health")
def health_check():
    """Health check endpoint for load balancers and monitoring."""
    services = {}

    # Database
    try:
        db.session.execute(db.text("SELECT 1"))
        services["database"] = "healthy"
    except Exception as e:
        services["database"] = f"unhealthy: {str(e)}"
        logger.error(f"Health check - DB failed: {e}")

    # XRPL connection
    try:
        from payments import XRPL_AVAILABLE, PAYMENT_CONFIG
        services["xrpl"] = "available" if XRPL_AVAILABLE else "not installed"
        services["xrpl_network"] = PAYMENT_CONFIG.get("xrpl_network", "unknown")
    except Exception:
        services["xrpl"] = "error"

    # Stripe
    try:
        from payments import STRIPE_AVAILABLE, PAYMENT_CONFIG as PAY_CFG
        services["stripe"] = "configured" if (STRIPE_AVAILABLE and PAY_CFG.get("stripe_secret_key")) else "not configured"
    except Exception:
        services["stripe"] = "error"

    # Proxy scraper
    try:
        from main import DIRECT_SCRAPER_AVAILABLE
        services["proxy_scraper"] = "available" if DIRECT_SCRAPER_AVAILABLE else "not available"
    except Exception:
        services["proxy_scraper"] = "error"

    # Amadeus
    try:
        from main import AMADEUS_AVAILABLE, AMADEUS_CONFIGURED
        if AMADEUS_AVAILABLE and AMADEUS_CONFIGURED:
            services["amadeus"] = "configured"
        elif AMADEUS_AVAILABLE:
            services["amadeus"] = "installed (keys not set)"
        else:
            services["amadeus"] = "not installed"
    except Exception:
        services["amadeus"] = "error"

    # Browser control — removed (Build #89)
    services["browser_control"] = "removed"

    # Email
    try:
        from email_service import EMAIL_CONFIG
        services["email"] = "enabled" if EMAIL_CONFIG.get("enabled") else "disabled"
    except Exception:
        services["email"] = "error"

    # Overall status
    overall = "healthy" if services.get("database") == "healthy" else "unhealthy"
    status_code = 200 if overall == "healthy" else 503

    return jsonify({
        "status": overall,
        "version": "1.1.0",
        "services": services,
        "timestamp": datetime.utcnow().isoformat(),
    }), status_code


# --- LEGAL PAGES ---

TERMS_CONTENT = """
<div class="card">
    <h1>Terms of Service</h1>
    <p><em>Last updated: January 2026</em></p>

    <h2>1. Acceptance of Terms</h2>
    <p>By accessing or using PHOENIX ("the Service"), you agree to be bound by these Terms of Service. If you do not agree to these terms, please do not use the Service.</p>

    <h2>2. Description of Service</h2>
    <p>PHOENIX is a travel assistance platform that helps users find price differences for flights across different regional markets. We act as a facilitator to help you book directly with airlines at lower regional prices.</p>

    <h2>3. How It Works</h2>
    <ul>
        <li><strong>Price Discovery:</strong> We scan airline pricing across different regional markets to identify price differences.</li>
        <li><strong>Platform Fee:</strong> When you find a deal, you pay a platform fee (25% of your savings, capped at $50) in XRP cryptocurrency to unlock access to the booking page.</li>
        <li><strong>Direct Booking:</strong> You book directly with the airline through their regional website. PHOENIX does not sell tickets or act as a ticket reseller.</li>
    </ul>

    <h2>4. User Responsibilities</h2>
    <p>You are responsible for:</p>
    <ul>
        <li>Providing accurate information when creating an account</li>
        <li>Maintaining the security of your account credentials</li>
        <li>Ensuring you meet all visa, passport, and travel requirements</li>
        <li>Completing your booking directly with the airline</li>
        <li>Understanding that prices may change between when you view a deal and when you complete booking</li>
    </ul>

    <h2>5. Payment Terms</h2>
    <ul>
        <li>Platform fees are paid in XRP cryptocurrency on the XRP Ledger</li>
        <li>Payments are non-refundable once verified, except as required by law</li>
        <li>You are responsible for any cryptocurrency transaction fees</li>
        <li>Payment verification typically occurs within seconds but may take longer during network congestion</li>
    </ul>

    <h2>6. No Guarantee of Availability</h2>
    <p>Flight prices and availability are controlled by airlines and may change at any time. We do not guarantee that any deal will still be available when you attempt to book. Deals shown are based on cached data and may not reflect real-time pricing.</p>

    <h2>7. Limitation of Liability</h2>
    <p>PHOENIX is not liable for:</p>
    <ul>
        <li>Price changes between deal display and booking</li>
        <li>Flight cancellations, delays, or changes by airlines</li>
        <li>Issues with bookings made on airline websites</li>
        <li>Loss of cryptocurrency due to user error</li>
        <li>Any indirect, incidental, or consequential damages</li>
    </ul>

    <h2>8. Intellectual Property</h2>
    <p>All content, trademarks, and intellectual property on PHOENIX are owned by us or our licensors. You may not copy, modify, or distribute our content without permission.</p>

    <h2>9. Termination</h2>
    <p>We may terminate or suspend your account at any time for violation of these terms or for any other reason at our discretion.</p>

    <h2>10. Changes to Terms</h2>
    <p>We may update these Terms of Service at any time. Continued use of the Service after changes constitutes acceptance of the new terms.</p>

    <h2>11. Contact</h2>
    <p>For questions about these Terms of Service, please contact us at legal@phoenix.app</p>
</div>
"""

PRIVACY_CONTENT = """
<div class="card">
    <h1>Privacy Policy</h1>
    <p><em>Last updated: January 2026</em></p>

    <h2>1. Introduction</h2>
    <p>PHOENIX ("we", "our", "us") respects your privacy and is committed to protecting your personal data. This Privacy Policy explains how we collect, use, and safeguard your information.</p>

    <h2>2. Information We Collect</h2>

    <h3>2.1 Account Information</h3>
    <ul>
        <li>Email address (required)</li>
        <li>Name (optional)</li>
        <li>Password (stored securely hashed)</li>
        <li>XRP wallet address (optional, for refunds)</li>
        <li>Preferred language and currency settings</li>
    </ul>

    <h3>2.2 Transaction Data</h3>
    <ul>
        <li>XRP payment records (destination tags, amounts, transaction hashes)</li>
        <li>Deal access history</li>
        <li>Booking attempts (we do not store airline booking details)</li>
    </ul>

    <h3>2.3 Technical Data</h3>
    <ul>
        <li>IP address</li>
        <li>Browser type and version</li>
        <li>Device information</li>
        <li>Usage patterns and preferences</li>
    </ul>

    <h2>3. How We Use Your Information</h2>
    <p>We use your data to:</p>
    <ul>
        <li>Provide and improve our Service</li>
        <li>Verify payments and unlock deal access</li>
        <li>Send service notifications and price alerts (if opted in)</li>
        <li>Prevent fraud and abuse</li>
        <li>Comply with legal obligations</li>
    </ul>

    <h2>4. Data Sharing</h2>
    <p>We do not sell your personal data. We may share data with:</p>
    <ul>
        <li><strong>Service providers:</strong> For hosting, analytics, and email services</li>
        <li><strong>Legal authorities:</strong> When required by law or to protect our rights</li>
    </ul>
    <p>When you access airline websites through our proxy, the airline's own privacy policy applies to data you provide to them.</p>

    <h2>5. Cryptocurrency Transactions</h2>
    <p>XRP transactions occur on the public XRP Ledger blockchain. Transaction data on the blockchain is publicly visible and cannot be deleted. We only store the minimum transaction data needed to verify payments.</p>

    <h2>6. Data Retention</h2>
    <ul>
        <li>Account data: Retained while your account is active, deleted upon request</li>
        <li>Transaction records: Retained for 7 years for legal compliance</li>
        <li>Technical logs: Retained for 90 days</li>
    </ul>

    <h2>7. Your Rights</h2>
    <p>You have the right to:</p>
    <ul>
        <li>Access your personal data</li>
        <li>Correct inaccurate data</li>
        <li>Delete your account (except transaction records required by law)</li>
        <li>Export your data</li>
        <li>Opt out of marketing communications</li>
    </ul>

    <h2>8. Security</h2>
    <p>We implement industry-standard security measures including:</p>
    <ul>
        <li>Password hashing with bcrypt</li>
        <li>HTTPS encryption for all connections</li>
        <li>CSRF protection</li>
        <li>Rate limiting to prevent abuse</li>
    </ul>

    <h2>9. Cookies</h2>
    <p>We use essential cookies for:</p>
    <ul>
        <li>Session management</li>
        <li>Authentication</li>
        <li>Security (CSRF tokens)</li>
    </ul>
    <p>We do not use tracking or advertising cookies.</p>

    <h2>10. International Transfers</h2>
    <p>Your data may be processed in countries outside your residence. We ensure appropriate safeguards are in place for such transfers.</p>

    <h2>11. Children's Privacy</h2>
    <p>Our Service is not intended for users under 18. We do not knowingly collect data from minors.</p>

    <h2>12. Changes to This Policy</h2>
    <p>We may update this Privacy Policy periodically. We will notify you of significant changes via email or through the Service.</p>

    <h2>13. Contact</h2>
    <p>For privacy inquiries, contact us at privacy@phoenix.app</p>
</div>
"""


@app.route("/terms")
def terms():
    """Terms of Service page."""
    return render_template_string(
        BASE_TEMPLATE,
        title="Terms of Service",
        content=TERMS_CONTENT,
        current_user=current_user
    )


@app.route("/privacy")
def privacy():
    """Privacy Policy page."""
    return render_template_string(
        BASE_TEMPLATE,
        title="Privacy Policy",
        content=PRIVACY_CONTENT,
        current_user=current_user
    )


ABOUT_CONTENT = """
<div style="max-width: 800px; margin: 40px auto;">
    <div class="card card-light" style="text-align: center; padding: 40px;">
        <h1 style="color: #ff6b35; margin-bottom: 10px;">PHOENIX</h1>
        <p style="font-size: 20px; color: #555; margin-bottom: 30px;">Flight Price Arbitrage Platform</p>
    </div>

    <div class="card card-light" style="margin-top: 20px;">
        <h2 style="color: #1a1a2e; margin-bottom: 15px;">How It Works</h2>
        <p style="color: #555; line-height: 1.8;">
            Airlines display different prices depending on your geographic location.
            A flight from New York to Tokyo might cost $1,200 when viewed from the US,
            but only $980 when viewed from Spain or Japan. PHOENIX detects these price
            differences in real-time and helps you book at the lowest available price.
        </p>

        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-top: 25px;">
            <div style="text-align: center; padding: 20px; background: #f8f9fa; border-radius: 12px;">
                <div style="font-size: 36px; margin-bottom: 10px;">1</div>
                <h4 style="color: #1a1a2e;">Search</h4>
                <p style="color: #666; font-size: 14px;">We scan flight prices across multiple regional markets simultaneously.</p>
            </div>
            <div style="text-align: center; padding: 20px; background: #f8f9fa; border-radius: 12px;">
                <div style="font-size: 36px; margin-bottom: 10px;">2</div>
                <h4 style="color: #1a1a2e;">Compare</h4>
                <p style="color: #666; font-size: 14px;">Our engine matches identical flights and identifies price differences.</p>
            </div>
            <div style="text-align: center; padding: 20px; background: #f8f9fa; border-radius: 12px;">
                <div style="font-size: 36px; margin-bottom: 10px;">3</div>
                <h4 style="color: #1a1a2e;">Save</h4>
                <p style="color: #666; font-size: 14px;">Book through the cheapest market and keep the savings.</p>
            </div>
        </div>
    </div>

    <div class="card card-light" style="margin-top: 20px;">
        <h2 style="color: #1a1a2e; margin-bottom: 15px;">Markets We Monitor</h2>
        <p style="color: #555; line-height: 1.8;">
            We monitor flight prices across Google Flights regional domains including the US, UK,
            Spain, Germany, France, Japan, Australia, and more. Each market can show different prices
            for the exact same flight on the exact same airline.
        </p>
        <div style="display: flex; flex-wrap: wrap; gap: 8px; margin-top: 15px;">
            <span style="background: #e3f2fd; color: #1565c0; padding: 6px 14px; border-radius: 20px; font-size: 14px;">US</span>
            <span style="background: #e8f5e9; color: #2e7d32; padding: 6px 14px; border-radius: 20px; font-size: 14px;">UK</span>
            <span style="background: #fff3e0; color: #e65100; padding: 6px 14px; border-radius: 20px; font-size: 14px;">Spain</span>
            <span style="background: #fce4ec; color: #c62828; padding: 6px 14px; border-radius: 20px; font-size: 14px;">Germany</span>
            <span style="background: #e0f2f1; color: #00695c; padding: 6px 14px; border-radius: 20px; font-size: 14px;">France</span>
            <span style="background: #f3e5f5; color: #6a1b9a; padding: 6px 14px; border-radius: 20px; font-size: 14px;">Japan</span>
            <span style="background: #e8eaf6; color: #283593; padding: 6px 14px; border-radius: 20px; font-size: 14px;">Australia</span>
            <span style="background: #efebe9; color: #4e342e; padding: 6px 14px; border-radius: 20px; font-size: 14px;">+ More</span>
        </div>
    </div>

    <div class="card card-light" style="margin-top: 20px;">
        <h2 style="color: #1a1a2e; margin-bottom: 15px;">Payment Options</h2>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 15px;">
            <div style="background: #f8f9fa; padding: 20px; border-radius: 12px; text-align: center;">
                <div style="font-size: 28px; margin-bottom: 8px;">XRP</div>
                <p style="color: #666; font-size: 13px;">Fast, low-fee crypto payments on the XRP Ledger</p>
            </div>
            <div style="background: #f8f9fa; padding: 20px; border-radius: 12px; text-align: center;">
                <div style="font-size: 28px; margin-bottom: 8px;">RLUSD</div>
                <p style="color: #666; font-size: 13px;">Ripple USD stablecoin for price stability</p>
            </div>
            <div style="background: #f8f9fa; padding: 20px; border-radius: 12px; text-align: center;">
                <div style="font-size: 28px; margin-bottom: 8px;">Card</div>
                <p style="color: #666; font-size: 13px;">Credit/debit via Stripe secure checkout</p>
            </div>
            <div style="background: #f8f9fa; padding: 20px; border-radius: 12px; text-align: center;">
                <div style="font-size: 28px; margin-bottom: 8px;">Crypto</div>
                <p style="color: #666; font-size: 13px;">BTC, ETH, USDC via Coinbase Commerce</p>
            </div>
        </div>
    </div>

    <div style="text-align: center; margin-top: 30px;">
        <a href="/search" class="btn" style="padding: 14px 40px; font-size: 18px;">Start Searching Flights</a>
    </div>
</div>
"""


@app.route("/about")
def about():
    """About page."""
    return render_template_string(
        BASE_TEMPLATE,
        title="About PHOENIX",
        content=ABOUT_CONTENT,
        current_user=current_user
    )


# --- EARN WITH PHOENIX (P2P Helper Network) ---

EARN_CONTENT = """
<div style="max-width: 900px; margin: 40px auto;">

    <!-- Hero Section -->
    <div class="card card-light" style="text-align: center; padding: 50px 40px; background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%); color: white; border: none;">
        <p style="font-size: 12px; color: #ff6b35; text-transform: uppercase; letter-spacing: 3px; margin-bottom: 8px;">The Citizen SerpAPI</p>
        <h1 style="color: #ff6b35; margin-bottom: 10px; font-size: 36px;">Earn With PHOENIX</h1>
        <p style="font-size: 22px; color: #fff; margin-bottom: 20px;">Turn your Google account into passive income</p>
        <p style="font-size: 16px; color: #fff; max-width: 600px; margin: 0 auto; line-height: 1.7;">
            Earn XRP every time Phoenix uses your account to find and book cheaper flights
            for travelers worldwide. You provide access. We handle everything else.
        </p>
    </div>

    <!-- The Mission -->
    <div class="card card-light" style="margin-top: 20px; background: #0d1117; color: white; border: 1px solid #30363d;">
        <h2 style="color: #ff6b35; margin-bottom: 15px;">The Honest API</h2>
        <p style="color: #fff; line-height: 1.8; font-size: 15px;">
            Google, Expedia, and every major travel platform serve you different prices based on where you are.
            Not different flights &mdash; <strong style="color: white;">different prices for the exact same seat</strong>.
            They use your IP address, your cookies, and your location to calculate how much they can charge you.
            This data is never shared with you. You never see what someone in Spain pays for the same flight.
        </p>
        <p style="color: #fff; line-height: 1.8; font-size: 15px;">
            Companies like SerpAPI sell access to this hidden data for thousands of dollars a month &mdash;
            to hedge funds, to corporations, to anyone with money. They scrape it from the same internet you use,
            through the same infrastructure you pay for, and they profit. You get nothing.
        </p>
        <p style="color: #ff6b35; line-height: 1.8; font-size: 16px; font-weight: bold; margin-top: 15px;">
            Phoenix is the people's data network. We don't scrape data to sell to corporations.
            We use it to save travelers money &mdash; and we pay <em>you</em> for access instead of data farms.
        </p>
    </div>

    <!-- The Pitch: Take Back Your Data -->
    <div class="card card-light" style="margin-top: 20px; border-left: 4px solid #ff6b35;">
        <h2 style="color: #1a1a2e; margin-bottom: 15px;">Your Data Has Value. You Should Profit From It.</h2>
        <p style="color: #555; line-height: 1.8; font-size: 15px;">
            Right now, airlines and tech companies use <strong>your location, your browsing habits, and your search history</strong>
            to charge you more for flights. They know where you live. They know when you're desperate to travel.
            And they price accordingly.
        </p>
        <p style="color: #555; line-height: 1.8; font-size: 15px;">
            Meanwhile, the same flight costs less when viewed from a different country &mdash; sometimes
            <strong>10-25% less</strong> for the exact same seat. The airlines pocket the difference.
            You never even know it happened.
        </p>
        <p style="color: #ff6b35; line-height: 1.8; font-size: 16px; font-weight: bold; margin-top: 15px;">
            Phoenix flips this system. Instead of corporations profiting from your data, <em>you</em> profit from it.
        </p>
    </div>

    <!-- How It Works -->
    <div class="card card-light" style="margin-top: 20px;">
        <h2 style="color: #1a1a2e; margin-bottom: 20px;">How Earning Works</h2>

        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 20px;">
            <div style="text-align: center; padding: 25px 15px; background: #f8f9fa; border-radius: 12px;">
                <div style="font-size: 36px; margin-bottom: 10px; color: #ff6b35;">1</div>
                <h4 style="color: #1a1a2e; margin-bottom: 8px;">Sign Up as a Helper</h4>
                <p style="color: #666; font-size: 14px; line-height: 1.6;">
                    Connect your XRPL wallet and grant Phoenix temporary access to your browser session. Your Google account stays yours.
                </p>
            </div>
            <div style="text-align: center; padding: 25px 15px; background: #f8f9fa; border-radius: 12px;">
                <div style="font-size: 36px; margin-bottom: 10px; color: #ff6b35;">2</div>
                <h4 style="color: #1a1a2e; margin-bottom: 8px;">Phoenix Does the Work</h4>
                <p style="color: #666; font-size: 14px; line-height: 1.6;">
                    When a traveler needs a flight booked through your region, Phoenix remotely handles the search and purchase through your browser. You don't lift a finger.
                </p>
            </div>
            <div style="text-align: center; padding: 25px 15px; background: #f8f9fa; border-radius: 12px;">
                <div style="font-size: 36px; margin-bottom: 10px; color: #ff6b35;">3</div>
                <h4 style="color: #1a1a2e; margin-bottom: 8px;">Get Paid in XRP</h4>
                <p style="color: #666; font-size: 14px; line-height: 1.6;">
                    Funds are locked in an on-chain XRPL escrow <em>before</em> any purchase. When the booking confirms, RLUSD releases directly to your wallet. Trustless. Instant.
                </p>
            </div>
        </div>
    </div>

    <!-- Why This Is Different -->
    <div class="card card-light" style="margin-top: 20px;">
        <h2 style="color: #1a1a2e; margin-bottom: 15px;">Why This Is Different</h2>

        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-top: 15px;">
            <div style="background: #fef2f2; padding: 20px; border-radius: 12px;">
                <h4 style="color: #c62828; margin-bottom: 8px;">The Old Way</h4>
                <ul style="color: #666; font-size: 14px; line-height: 2; list-style: none; padding: 0; margin: 0;">
                    <li>Corporations harvest your data for free</li>
                    <li>Airlines charge you more based on your location</li>
                    <li>Data centers and proxy farms profit from access</li>
                    <li>You pay the highest price and get nothing back</li>
                </ul>
            </div>
            <div style="background: #f1f8e9; padding: 20px; border-radius: 12px;">
                <h4 style="color: #2e7d32; margin-bottom: 8px;">The Phoenix Way</h4>
                <ul style="color: #666; font-size: 14px; line-height: 2; list-style: none; padding: 0; margin: 0;">
                    <li>You control access to your account</li>
                    <li>You earn from every transaction through your region</li>
                    <li>Real users replace expensive data farms</li>
                    <li>Savings go to travelers, earnings go to you</li>
                </ul>
            </div>
        </div>

        <p style="color: #555; line-height: 1.8; font-size: 15px; margin-top: 20px;">
            Phoenix doesn't need data centers or proxy farms. <strong>You are the network.</strong>
            Every helper with a Google account in a different country is a real endpoint that corporations
            cannot distinguish from organic traffic. Instead of paying data infrastructure companies,
            Phoenix pays <em>you</em> directly for access to networks that already exist &mdash; yours.
        </p>
        <p style="color: #555; line-height: 1.8; font-size: 15px;">
            When enough people join, this becomes a private, decentralized data network that no corporation
            can shut down. No proxy IPs to block. No data centers to subpoena. Just real people,
            running Phoenix passively, proving every day that the prices you see are not the prices
            that exist. <strong>Our data. Our profit.</strong>
        </p>
    </div>

    <!-- Trustless Payments -->
    <div class="card card-light" style="margin-top: 20px;">
        <h2 style="color: #1a1a2e; margin-bottom: 15px;">Trustless Payments on XRPL</h2>
        <p style="color: #555; line-height: 1.8; font-size: 15px;">
            You never have to trust Phoenix with your money &mdash; and we never have to trust you either.
            Everything runs through <strong>on-chain XRPL escrow</strong> that both parties can verify
            independently on the public ledger.
        </p>

        <div style="background: #f8f9fa; border-radius: 12px; padding: 25px; margin-top: 15px;">
            <div style="display: flex; flex-direction: column; gap: 12px;">
                <div style="display: flex; align-items: center; gap: 12px;">
                    <span style="background: #ff6b35; color: white; width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 14px; font-weight: bold; flex-shrink: 0;">1</span>
                    <span style="color: #555; font-size: 14px;">Traveler converts USD to RLUSD (1:1 stablecoin) and locks it in escrow</span>
                </div>
                <div style="display: flex; align-items: center; gap: 12px;">
                    <span style="background: #ff6b35; color: white; width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 14px; font-weight: bold; flex-shrink: 0;">2</span>
                    <span style="color: #555; font-size: 14px;">You verify the escrow is locked on-chain &mdash; visible on the XRPL ledger</span>
                </div>
                <div style="display: flex; align-items: center; gap: 12px;">
                    <span style="background: #ff6b35; color: white; width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 14px; font-weight: bold; flex-shrink: 0;">3</span>
                    <span style="color: #555; font-size: 14px;">You front the ticket purchase with your card (escrow guarantees reimbursement)</span>
                </div>
                <div style="display: flex; align-items: center; gap: 12px;">
                    <span style="background: #ff6b35; color: white; width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 14px; font-weight: bold; flex-shrink: 0;">4</span>
                    <span style="color: #555; font-size: 14px;">Booking confirms &rarr; escrow releases RLUSD to your wallet (reimbursement + your cut)</span>
                </div>
                <div style="display: flex; align-items: center; gap: 12px;">
                    <span style="background: #ff6b35; color: white; width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 14px; font-weight: bold; flex-shrink: 0;">5</span>
                    <span style="color: #555; font-size: 14px;">Use your RLUSD to book your own discounted flights &mdash; or cash out via Coinbase</span>
                </div>
            </div>
        </div>

        <p style="color: #fff; font-size: 13px; margin-top: 12px; text-align: center;">
            No middleman. No trust required. The smart contract handles everything.
        </p>
    </div>

    <!-- What You Earn -->
    <div class="card card-light" style="margin-top: 20px;">
        <h2 style="color: #1a1a2e; margin-bottom: 15px;">What You Earn</h2>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px;">
            <div style="background: linear-gradient(135deg, #fff3e0, #ffe0b2); padding: 25px; border-radius: 12px; text-align: center;">
                <div style="font-size: 32px; font-weight: bold; color: #e65100;">RLUSD</div>
                <p style="color: #555; font-size: 13px; margin-top: 8px;">Full reimbursement for ticket cost + your earning cut, paid in Ripple USD stablecoin</p>
            </div>
            <div style="background: linear-gradient(135deg, #e3f2fd, #bbdefb); padding: 25px; border-radius: 12px; text-align: center;">
                <div style="font-size: 32px; font-weight: bold; color: #1565c0;">XRP</div>
                <p style="color: #555; font-size: 13px; margin-top: 8px;">Convert RLUSD to XRP instantly on XRPL with near-zero fees</p>
            </div>
            <div style="background: linear-gradient(135deg, #e8f5e9, #c8e6c9); padding: 25px; border-radius: 12px; text-align: center;">
                <div style="font-size: 32px; font-weight: bold; color: #2e7d32;">Flights</div>
                <p style="color: #555; font-size: 13px; margin-top: 8px;">Spend your RLUSD directly on discounted flights through Phoenix</p>
            </div>
        </div>
        <p style="color: #555; line-height: 1.8; font-size: 15px; margin-top: 20px;">
            Your earnings circulate in the Phoenix ecosystem. Use RLUSD to book your own flights at
            arbitrage prices, convert to XRP for other uses, or cash out to your local currency through
            Coinbase Commerce, Binance, Kraken, Uphold, or any major exchange.
        </p>
    </div>

    <!-- The Bigger Picture -->
    <div class="card card-light" style="margin-top: 20px; border-left: 4px solid #ff6b35;">
        <h2 style="color: #1a1a2e; margin-bottom: 15px;">The Bigger Picture: A Citizen Data Network</h2>
        <p style="color: #555; line-height: 1.8; font-size: 15px;">
            Google knows the flight from JFK to London costs $847 from your apartment in New York
            and $744 from a caf&eacute; in Madrid. They serve both prices simultaneously, every second
            of every day. They never tell you the cheaper one exists.
        </p>
        <p style="color: #555; line-height: 1.8; font-size: 15px;">
            Data companies like SerpAPI, Bright Data, and Oxylabs profit by selling access to this
            hidden pricing data &mdash; scraped through proxy infrastructure built on the same
            residential networks you pay for. They charge corporations thousands per month.
            The people whose connections make it possible earn nothing.
        </p>
        <p style="color: #555; line-height: 1.8; font-size: 15px;">
            Phoenix is the honest alternative. We don't sell data to corporations &mdash; we use it to
            save travelers money. And instead of routing through anonymous proxy farms,
            <strong>we pay real people directly</strong> for the access that data companies have
            been taking for free. Phoenix is a citizen-powered API that proves what the institutions
            won't admit: <strong>the prices you see are not the prices that exist.</strong>
        </p>
        <p style="color: #555; line-height: 1.8; font-size: 15px;">
            Every Phoenix helper is proof that the system is rigged &mdash; and that it doesn't have to be.
            The more people join, the more transparent the market becomes, and the harder it is
            for anyone to stop. This isn't just an app. It's a decentralized data network
            controlled by the people who power it.
        </p>
    </div>

    <!-- Data Sovereignty Pitch -->
    <div class="card card-light" style="margin-top: 20px; background: linear-gradient(135deg, #1a1a2e, #16213e); color: white; border: none;">
        <h2 style="color: #ff6b35; margin-bottom: 15px;">Take Back Your Data</h2>
        <p style="color: #fff; line-height: 1.8; font-size: 15px;">
            Every day, airlines use geographic price discrimination to overcharge millions of travelers.
            They use <em>your</em> IP address, <em>your</em> cookies, and <em>your</em> search patterns to determine
            how much they can charge you. The institutions profit. You don't.
        </p>
        <p style="color: #fff; line-height: 1.8; font-size: 15px;">
            Phoenix changes the equation. By joining the network, your Google account and local market access
            become a tool for global price transparency. Instead of data farms and proxy infrastructure
            profiting from internet access, <strong style="color: #ff6b35;">real people earn real money</strong>
            by contributing what they already have &mdash; a browser, an internet connection, and a location.
        </p>
        <p style="color: #fff; line-height: 1.8; font-size: 15px;">
            This isn't just about saving money on flights. It's about building a network where
            <strong style="color: #ff6b35;">consumers benefit from their own data</strong> instead of handing it
            to institutions for free. Every helper in the Phoenix network is a statement: our data, our profit.
        </p>
    </div>

    <!-- FAQ -->
    <div class="card card-light" style="margin-top: 20px;">
        <h2 style="color: #1a1a2e; margin-bottom: 20px;">Common Questions</h2>

        <div style="border-bottom: 1px solid #eee; padding-bottom: 15px; margin-bottom: 15px;">
            <h4 style="color: #1a1a2e; margin-bottom: 6px;">Do I have to do anything during a booking?</h4>
            <p style="color: #666; font-size: 14px; line-height: 1.7;">
                No. Phoenix handles everything remotely. When you're matched with a booking request,
                Phoenix takes temporary control of your browser session through the Phoenix app.
                The same automation that powers our proxy system runs on your device instead.
                You just need the app open.
            </p>
        </div>

        <div style="border-bottom: 1px solid #eee; padding-bottom: 15px; margin-bottom: 15px;">
            <h4 style="color: #1a1a2e; margin-bottom: 6px;">Is my money safe?</h4>
            <p style="color: #666; font-size: 14px; line-height: 1.7;">
                Yes. The traveler's RLUSD is locked in an XRPL escrow smart contract before you
                front any purchase. You can verify the escrow on-chain yourself. The funds release
                to your wallet automatically when the booking is confirmed. If anything goes wrong,
                the escrow has a timeout that returns funds to the traveler.
            </p>
        </div>

        <div style="border-bottom: 1px solid #eee; padding-bottom: 15px; margin-bottom: 15px;">
            <h4 style="color: #1a1a2e; margin-bottom: 6px;">What do I need to get started?</h4>
            <p style="color: #666; font-size: 14px; line-height: 1.7;">
                An XRPL wallet (for receiving RLUSD payments), a payment card (for fronting ticket purchases),
                and a Google account. Sign up, connect your wallet and card, and you're ready to earn.
            </p>
        </div>

        <div style="border-bottom: 1px solid #eee; padding-bottom: 15px; margin-bottom: 15px;">
            <h4 style="color: #1a1a2e; margin-bottom: 6px;">How do I cash out my earnings?</h4>
            <p style="color: #666; font-size: 14px; line-height: 1.7;">
                Your earnings arrive as RLUSD in your XRPL wallet. You can spend RLUSD on your own
                Phoenix flights, convert to XRP on-ledger, or cash out to local currency through
                Coinbase, Binance, Kraken, Uphold, or other major exchanges.
            </p>
        </div>

        <div>
            <h4 style="color: #1a1a2e; margin-bottom: 6px;">Why use real people instead of proxy servers?</h4>
            <p style="color: #666; font-size: 14px; line-height: 1.7;">
                Proxy servers can be detected and blocked by airlines and Google. A real person with a
                real Google account, real browsing history, and a real IP address is indistinguishable
                from any other customer. Phoenix pays you directly for this access instead of paying
                data center companies for proxy infrastructure.
            </p>
        </div>
    </div>

    <!-- CTA -->
    <div style="text-align: center; margin-top: 30px; margin-bottom: 20px;">
        <a href="/register" class="btn" style="padding: 16px 50px; font-size: 18px; background: #ff6b35; color: white; border-radius: 8px; text-decoration: none; display: inline-block;">
            Start Earning With Phoenix
        </a>
        <p style="color: #fff; font-size: 13px; margin-top: 12px;">
            Connect your wallet. Grant access. Get paid.
        </p>
    </div>
</div>
"""


@app.route("/earn")
def earn():
    """Earn with Phoenix - P2P helper network pitch page."""
    return render_template_string(
        BASE_TEMPLATE,
        title="Earn With PHOENIX",
        content=EARN_CONTENT,
        current_user=current_user
    )


# --- PROXY PORTAL ---

PORTAL_CONTENT = """
<style>
    .portal-hero {
        text-align: center;
        padding: 60px 20px;
        background: linear-gradient(135deg, #0f3460 0%, #1a1a2e 50%, #16213e 100%);
        border-radius: 16px;
        margin-bottom: 40px;
    }
    .portal-hero h1 {
        font-size: 2.5rem;
        color: #fff;
        margin-bottom: 10px;
    }
    .portal-hero .accent { color: #ff6b35; }
    .portal-hero p { color: #fff; font-size: 1.1rem; max-width: 600px; margin: 0 auto; }

    .portal-section { margin-bottom: 40px; }
    .portal-section h2 { color: #1a1a2e; font-size: 1.5rem; margin-bottom: 20px; }

    .market-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
        gap: 12px;
    }
    .market-card {
        background: #fff;
        border: 2px solid #e8e8e8;
        border-radius: 12px;
        padding: 15px 10px;
        text-align: center;
        cursor: pointer;
        transition: all 0.2s ease;
    }
    .market-card:hover { border-color: #ff6b35; transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
    .market-card.selected { border-color: #ff6b35; background: #fff5f0; }
    .market-card .flag { font-size: 2rem; display: block; margin-bottom: 5px; }
    .market-card .name { font-size: 0.85rem; font-weight: 600; color: #1a1a2e; }
    .market-card .count { font-size: 0.75rem; color: #fff; margin-top: 3px; }

    .category-tabs {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        margin-bottom: 20px;
    }
    .cat-tab {
        padding: 8px 16px;
        border-radius: 20px;
        border: 1px solid #ddd;
        background: #fff;
        cursor: pointer;
        font-size: 0.85rem;
        font-weight: 500;
        transition: all 0.2s;
    }
    .cat-tab:hover { border-color: #ff6b35; }
    .cat-tab.active { background: #ff6b35; color: #fff; border-color: #ff6b35; }

    .app-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
        gap: 16px;
    }
    .app-card {
        background: #fff;
        border: 1px solid #e8e8e8;
        border-radius: 12px;
        padding: 20px;
        transition: all 0.2s;
    }
    .app-card:hover { box-shadow: 0 4px 16px rgba(0,0,0,0.08); }
    .app-card h4 { margin: 0 0 5px 0; color: #1a1a2e; font-size: 1rem; }
    .app-card .desc { color: #666; font-size: 0.85rem; margin-bottom: 12px; }
    .app-card .regions { display: flex; gap: 4px; flex-wrap: wrap; margin-bottom: 12px; }
    .app-card .region-tag { font-size: 0.7rem; background: #f0f0f0; padding: 2px 8px; border-radius: 10px; color: #555; }
    .app-card .browse-btn {
        display: inline-block;
        padding: 8px 16px;
        background: #ff6b35;
        color: #fff;
        border: none;
        border-radius: 8px;
        font-size: 0.85rem;
        cursor: pointer;
        text-decoration: none;
        font-weight: 500;
    }
    .app-card .browse-btn:hover { background: #e55a2b; }
    .app-card .browse-btn:disabled { background: #ccc; cursor: not-allowed; }

    .session-panel {
        background: #f8f9fa;
        border: 2px solid #e8e8e8;
        border-radius: 12px;
        padding: 25px;
        margin-bottom: 30px;
    }
    .session-panel h3 { margin: 0 0 15px 0; color: #1a1a2e; }
    .session-item {
        background: #fff;
        border: 1px solid #ddd;
        border-radius: 8px;
        padding: 15px;
        margin-bottom: 10px;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    .session-info { flex: 1; }
    .session-info .country { font-weight: 600; color: #1a1a2e; }
    .session-info .details { font-size: 0.8rem; color: #666; font-family: monospace; margin-top: 5px; }
    .session-info .expiry { font-size: 0.8rem; color: #fff; margin-top: 3px; }
    .end-btn {
        padding: 6px 14px;
        background: #dc3545;
        color: #fff;
        border: none;
        border-radius: 6px;
        cursor: pointer;
        font-size: 0.8rem;
    }
    .end-btn:hover { background: #c82333; }

    .proxy-details {
        background: #1a1a2e;
        border-radius: 8px;
        padding: 20px;
        margin-top: 15px;
        color: #fff;
    }
    .proxy-details h4 { color: #ff6b35; margin: 0 0 12px 0; }
    .proxy-details .cred-row {
        display: flex;
        justify-content: space-between;
        padding: 6px 0;
        border-bottom: 1px solid #2a2a4e;
        font-family: monospace;
        font-size: 0.85rem;
    }
    .proxy-details .cred-label { color: #fff; }
    .proxy-details .cred-value { color: #4fc3f7; }

    .setup-guide {
        background: #fff;
        border: 1px solid #e8e8e8;
        border-radius: 12px;
        padding: 25px;
    }
    .setup-guide h3 { color: #1a1a2e; margin: 0 0 15px 0; }
    .setup-step { padding: 12px 0; border-bottom: 1px solid #f0f0f0; }
    .setup-step:last-child { border-bottom: none; }
    .setup-step h4 { color: #1a1a2e; margin: 0 0 8px 0; font-size: 0.95rem; cursor: pointer; }
    .setup-step p { color: #666; font-size: 0.85rem; margin: 0; line-height: 1.6; }
    .setup-step code { background: #f0f0f0; padding: 2px 6px; border-radius: 4px; font-size: 0.8rem; }

    .no-market { text-align: center; padding: 40px; color: #fff; }

    @media (max-width: 768px) {
        .portal-hero h1 { font-size: 1.8rem; }
        .market-grid { grid-template-columns: repeat(auto-fill, minmax(100px, 1fr)); }
        .app-grid { grid-template-columns: 1fr; }
        .session-item { flex-direction: column; gap: 10px; }
    }
</style>

<div class="portal-hero">
    <h1>Access <span class="accent">Any Market</span> in the World</h1>
    <p>Browse foreign marketplaces through residential proxy gateways.
    Stay logged into your own accounts — Phoenix just changes where the platform thinks you are.</p>
</div>

<!-- Active Sessions -->
<div id="activeSessions" class="session-panel" style="display: none;">
    <h3>Active Proxy Sessions</h3>
    <div id="sessionList"></div>
</div>

<!-- Market Selector -->
<div class="portal-section">
    <h2>Select a Market</h2>
    <div id="marketGrid" class="market-grid">
        <div style="padding: 20px; color: #fff;">Loading markets...</div>
    </div>
</div>

<!-- App Directory -->
<div class="portal-section" id="appSection" style="display: none;">
    <h2 id="appSectionTitle">Apps & Sites</h2>
    <div id="categoryTabs" class="category-tabs"></div>
    <div id="appGrid" class="app-grid"></div>
</div>

<!-- Setup Guide -->
<div class="portal-section">
    <div class="setup-guide">
        <h3>How to Use Your Proxy Session</h3>
        <div class="setup-step">
            <h4>1. Select a market above and click "Start Browsing"</h4>
            <p>Phoenix allocates a sticky residential IP in your chosen country. You get proxy credentials valid for up to 4 hours.</p>
        </div>
        <div class="setup-step">
            <h4>2. Configure your browser's proxy settings</h4>
            <p><strong>Chrome:</strong> Settings → System → Open proxy settings → Use <code>SOCKS5</code> with the host and port shown.<br>
            <strong>Firefox:</strong> Settings → General → Network Settings → Manual proxy → SOCKS Host with the credentials shown.<br>
            <strong>macOS:</strong> System Settings → Network → Wi-Fi → Proxies → SOCKS Proxy → Enter host and port.<br>
            <strong>Recommended:</strong> Use a separate browser profile so your main browsing isn't affected.</p>
        </div>
        <div class="setup-step">
            <h4>3. Browse any site as if you're local</h4>
            <p>Your browser traffic routes through a residential IP in that country. Marketplaces see a local user. You stay logged into your own accounts (Facebook, Google, etc.) — Phoenix just changes the geographic routing.</p>
        </div>
        <div class="setup-step">
            <h4>4. Contact sellers directly</h4>
            <p>Since you're logged into your own accounts, use the platform's built-in messaging (Facebook Messenger, WhatsApp, etc.) to communicate with sellers. No intermediary needed.</p>
        </div>
    </div>
</div>

<!-- Earn CTA -->
<div style="text-align: center; margin: 40px 0; padding: 40px; background: linear-gradient(135deg, #0f3460, #1a1a2e); border-radius: 16px;">
    <h2 style="color: #fff; margin-bottom: 10px;">Power the Network</h2>
    <p style="color: #fff; margin-bottom: 20px;">Earn RLUSD by contributing your connection as a proxy node.</p>
    <a href="/earn" style="display: inline-block; padding: 14px 32px; background: #ff6b35; color: #fff; border-radius: 8px; text-decoration: none; font-weight: 600;">Learn How to Earn</a>
</div>

<script>
let selectedMarket = null;
let allMarkets = [];
let allApps = {};
let activeSessions = [];

async function loadPortal() {
    // Load markets
    try {
        const res = await fetch('/api/portal/markets');
        allMarkets = await res.json();
        renderMarkets();
    } catch(e) { console.error('Failed to load markets', e); }

    // Load active sessions
    await loadSessions();
}

function renderMarkets() {
    const grid = document.getElementById('marketGrid');
    grid.innerHTML = allMarkets.map(m => `
        <div class="market-card ${selectedMarket === m.code ? 'selected' : ''}"
             onclick="selectMarket('${m.code}')">
            <span class="flag">${m.flag}</span>
            <span class="name">${m.name}</span>
            <span class="count">${m.app_count} apps</span>
        </div>
    `).join('');
}

async function selectMarket(code) {
    selectedMarket = code;
    renderMarkets();

    const section = document.getElementById('appSection');
    const market = allMarkets.find(m => m.code === code);
    document.getElementById('appSectionTitle').textContent = `Apps & Sites in ${market ? market.name : code}`;
    section.style.display = 'block';

    // Load apps for market
    try {
        const res = await fetch(`/api/portal/apps?market=${code}`);
        allApps = await res.json();
        renderApps();
    } catch(e) { console.error('Failed to load apps', e); }
}

function renderApps(filterCategory) {
    // Tabs
    const tabs = document.getElementById('categoryTabs');
    const categories = Object.keys(allApps);
    tabs.innerHTML = `<span class="cat-tab ${!filterCategory ? 'active' : ''}" onclick="renderApps()">All</span>` +
        categories.map(key => `
            <span class="cat-tab ${filterCategory === key ? 'active' : ''}"
                  onclick="renderApps('${key}')">${allApps[key].icon} ${allApps[key].name}</span>
        `).join('');

    // Cards
    const grid = document.getElementById('appGrid');
    let sites = [];
    const catsToShow = filterCategory ? [filterCategory] : categories;
    for (const key of catsToShow) {
        if (allApps[key]) {
            for (const site of allApps[key].sites) {
                sites.push({...site, category: allApps[key].name});
            }
        }
    }

    if (!sites.length) {
        grid.innerHTML = '<div class="no-market">No apps available for this market and category.</div>';
        return;
    }

    grid.innerHTML = sites.map(site => `
        <div class="app-card">
            <h4>${site.name}</h4>
            <div class="desc">${site.desc}</div>
            <div class="regions">${site.regions.map(r =>
                r === '*' ? '<span class="region-tag">Global</span>' :
                '<span class="region-tag">' + r + '</span>'
            ).join('')}</div>
            <button class="browse-btn" onclick="startSession('${selectedMarket}', '${site.name}')">
                Browse via ${selectedMarket}
            </button>
        </div>
    `).join('');
}

async function startSession(country, siteName) {
    try {
        const res = await fetch('/api/portal/session', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({country_code: country, target_site: siteName || null}),
        });
        const data = await res.json();
        if (data.error) { alert(data.error); return; }
        await loadSessions();
        // Scroll to active sessions
        document.getElementById('activeSessions').scrollIntoView({behavior: 'smooth'});
    } catch(e) { alert('Failed to create session'); }
}

async function loadSessions() {
    try {
        const res = await fetch('/api/portal/sessions');
        activeSessions = await res.json();
        renderSessions();
    } catch(e) { console.error('Failed to load sessions', e); }
}

function renderSessions() {
    const panel = document.getElementById('activeSessions');
    const list = document.getElementById('sessionList');

    if (!activeSessions.length) {
        panel.style.display = 'none';
        return;
    }
    panel.style.display = 'block';

    list.innerHTML = activeSessions.map(s => {
        const market = allMarkets.find(m => m.code === s.country_code);
        const flag = market ? market.flag : '';
        const name = market ? market.name : s.country_code;
        const expiresAt = new Date(s.expires_at);
        const remaining = Math.max(0, Math.round((expiresAt - Date.now()) / 60000));

        return `
        <div class="session-item">
            <div class="session-info">
                <div class="country">${flag} ${name} ${s.target_site ? '— ' + s.target_site : ''}</div>
                <div class="expiry">Expires in ${remaining} minutes</div>
            </div>
            <div style="display: flex; gap: 8px; align-items: center;">
                <button class="browse-btn" style="font-size: 0.75rem; padding: 6px 12px;"
                    onclick="showCredentials(${s.id})">Show Credentials</button>
                <button class="end-btn" onclick="endSession(${s.id})">End</button>
            </div>
        </div>
        <div id="creds-${s.id}" class="proxy-details" style="display: none;">
            <h4>Proxy Credentials</h4>
            <div class="cred-row"><span class="cred-label">Protocol</span><span class="cred-value">${s.protocol.toUpperCase()}</span></div>
            <div class="cred-row"><span class="cred-label">Host</span><span class="cred-value">${s.proxy_host}</span></div>
            <div class="cred-row"><span class="cred-label">Port</span><span class="cred-value">${s.proxy_port}</span></div>
            <div class="cred-row"><span class="cred-label">Username</span><span class="cred-value">${s.proxy_username}</span></div>
            <div class="cred-row"><span class="cred-label">Password</span><span class="cred-value">Shown on creation only</span></div>
        </div>`;
    }).join('');
}

function showCredentials(id) {
    const el = document.getElementById('creds-' + id);
    el.style.display = el.style.display === 'none' ? 'block' : 'none';
}

async function endSession(id) {
    if (!confirm('End this proxy session?')) return;
    try {
        await fetch(`/api/portal/session/${id}`, {method: 'DELETE'});
        await loadSessions();
    } catch(e) { alert('Failed to end session'); }
}

document.addEventListener('DOMContentLoaded', loadPortal);
</script>
"""


@app.route("/portal")
@login_required
def portal():
    """Proxy Portal - Universal market access gateway."""
    return render_template_string(
        BASE_TEMPLATE,
        title="Proxy Portal — PHOENIX",
        content=PORTAL_CONTENT,
        current_user=current_user
    )


@app.route("/api/portal/session", methods=["POST"])
@login_required
def api_portal_create_session():
    """Create a Free Browse session through a CitizenSERP node.

    Build #90 — unmetered.  User's own browser through a node;
    Phoenix monitors passively.
    """
    from free_browse_portal import browse_portal_manager

    data = request.get_json(silent=True) or {}
    zone_code = data.get("zone_code") or data.get("country_code")
    target_site = data.get("target_site")

    if not zone_code:
        return jsonify({"error": "zone_code (or country_code) is required"}), 400

    result = browse_portal_manager.create_browse_session(
        user_id=current_user.id,
        zone_code=zone_code.upper(),
        target_site=target_site,
    )

    if "error" in result:
        return jsonify(result), 400

    return jsonify(result)


@app.route("/api/portal/sessions")
@login_required
def api_portal_sessions():
    """List active Free Browse sessions for the current user."""
    from free_browse_portal import browse_portal_manager
    sessions = browse_portal_manager.get_active_sessions(current_user.id)
    return jsonify(sessions)


@app.route("/api/portal/session/<int:session_id>", methods=["DELETE"])
@login_required
def api_portal_end_session(session_id):
    """End a Free Browse session."""
    from free_browse_portal import browse_portal_manager
    result = browse_portal_manager.end_browse_session(session_id, current_user.id)
    if "error" in result:
        return jsonify(result), 404
    return jsonify(result)


@app.route("/api/portal/markets")
@login_required
def api_portal_markets():
    """Available zones with node availability for Free Browse."""
    from free_browse_portal import browse_portal_manager
    return jsonify(browse_portal_manager.get_available_zones())


@app.route("/api/portal/apps")
@login_required
def api_portal_apps():
    """App directory filtered by market and/or category."""
    from free_browse_portal import browse_portal_manager, PORTAL_APP_DIRECTORY

    market = request.args.get("market")
    category = request.args.get("category")

    if market:
        apps = browse_portal_manager.get_apps_for_market(market.upper())
    elif category:
        cat = browse_portal_manager.get_apps_by_category(category)
        if cat:
            apps = {category: cat}
        else:
            apps = {}
    else:
        apps = dict(PORTAL_APP_DIRECTORY)

    return jsonify(apps)


# --- Free Browse Data Ingestion (Build #90) ---

@app.route("/api/browse/event", methods=["POST"])
@login_required
def api_browse_event():
    """Ingest a browsing event from a Free Browse session.

    Called by the monitoring JavaScript in the portal iframe.
    Each event becomes a BrowsingEvent record feeding the data
    marketplace.
    """
    from free_browse_portal import browse_portal_manager

    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id")
    event_type = data.get("event_type", "page_visit")

    if not session_id:
        return jsonify({"error": "session_id is required"}), 400

    result = browse_portal_manager.ingest_browse_event(
        session_id=session_id,
        event_type=event_type,
        url=data.get("url", ""),
        domain=data.get("domain", ""),
        title=data.get("title", ""),
        event_data=data.get("event_data"),
    )

    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@app.route("/api/browse/heartbeat", methods=["POST"])
@login_required
def api_browse_heartbeat():
    """Keep a Free Browse session alive."""
    from free_browse_portal import browse_portal_manager

    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id")
    if not session_id:
        return jsonify({"error": "session_id is required"}), 400

    result = browse_portal_manager.heartbeat(session_id)
    if "error" in result:
        return jsonify(result), 404
    return jsonify(result)


# --- Hot Zone Economics & Node Earnings Dashboard (Build #90) ---

@app.route("/api/zones/leaderboard")
def api_zone_leaderboard():
    """Public endpoint — top zones by avg earnings per node.

    Powers the onboarding ad: "Nodes in Tokyo earned $223/month."
    """
    from node_yield_dashboard import yield_dashboard
    return jsonify(yield_dashboard.get_zone_earnings_leaderboard())


@app.route("/api/zones/<zone_code>/economics")
def api_zone_economics(zone_code):
    """Public endpoint — detailed zone economics."""
    from node_yield_dashboard import yield_dashboard
    return jsonify(yield_dashboard.get_zone_earnings_detail(zone_code.upper()))


@app.route("/api/zones/<zone_code>/estimate")
def api_zone_estimate(zone_code):
    """Public endpoint — estimated earnings for a new node in this zone."""
    from node_yield_dashboard import yield_dashboard
    tier = request.args.get("tier", "bronze")
    return jsonify(yield_dashboard.get_estimated_earnings(zone_code.upper(), tier))


@app.route("/api/network/heatmap")
def api_network_heatmap():
    """Public endpoint — zone data for map visualization.

    Returns per-zone: lat, lon, active_nodes, avg_earnings,
    opportunity_score, saturation.
    """
    from node_yield_dashboard import yield_dashboard
    return jsonify(yield_dashboard.get_network_heatmap())


@app.route("/api/network/scaling")
def api_network_scaling():
    """Public endpoint — network scaling proof metrics."""
    from hot_zone_economics import hot_zone_engine
    return jsonify(hot_zone_engine.compute_network_scaling_metrics())


@app.route("/api/network/earnings-projection")
def api_earnings_projection():
    """Public endpoint — projected per-node earnings at any network size.

    Query params:
        nodes: Network size (default: current online count or 500)
        tier: Node tier (bronze/silver/gold/platinum, default: bronze)
        uptime: Daily uptime hours (optional, uses tier default)

    Returns detailed per-product earnings breakdown.
    """
    try:
        from node_yield_dashboard import project_node_earnings
        from node_registry import node_registry

        # Default to current network size, fallback to 500 (commercially viable)
        topology = node_registry.get_network_topology()
        default_nodes = max(topology.get("total_online", 0), 500)

        nodes = request.args.get("nodes", default_nodes, type=int)
        tier = request.args.get("tier", "bronze")
        uptime = request.args.get("uptime", None, type=float)

        nodes = max(1, min(nodes, 10_000_000_000))  # Sanity bounds

        return jsonify(project_node_earnings(nodes, tier, uptime))
    except Exception as e:
        logger.error(f"Earnings projection error: {e}")
        return jsonify({"error": "Projection unavailable"}), 500


@app.route("/api/network/earnings-all-scales")
def api_earnings_all_scales():
    """Public endpoint — earnings projections across all network milestones.

    Query params:
        tier: Node tier to project for (default: platinum)

    Returns earnings at: 10, 100, 500, 2K, 10K, 100K, 1M, 10M, 72M, 1B nodes.
    Powers the pitch deck and onboarding visualizations.
    """
    try:
        from node_yield_dashboard import project_all_scales
        tier = request.args.get("tier", "platinum")
        return jsonify(project_all_scales(tier))
    except Exception as e:
        logger.error(f"All-scales projection error: {e}")
        return jsonify({"error": "Projection unavailable"}), 500


# --- PHOENIX AI SEARCH + PRIVATE MARKET ESCROW ---

AI_SEARCH_CONTENT = """
<div style="max-width: 1100px; margin: 30px auto;">
    <!-- AI Search Section -->
    <div class="card card-light" style="padding: 30px; margin-bottom: 20px;">
        <h1 style="color: #1a1a2e; margin-bottom: 5px;">Phoenix AI Search</h1>
        <p style="color: #666; margin-bottom: 20px;">Multi-provider ensemble — queries multiple AI models simultaneously for the best answer. Or <a href="/portal" style="color: #667eea;">use your own AI subscription</a> through the proxy portal — log in with your credentials and your AI accesses market data from any region.</p>

        <!-- Search Bar -->
        <div style="display: flex; gap: 10px; margin-bottom: 15px;">
            <input type="text" id="aiSearchInput" placeholder="Search anything across markets..."
                style="flex:1; padding: 14px 18px; border: 2px solid #e0e0e0; border-radius: 10px; font-size: 16px; outline: none;"
                onkeydown="if(event.key==='Enter')aiSearch()">
            <select id="aiMarketSelect" style="padding: 14px; border: 2px solid #e0e0e0; border-radius: 10px; min-width: 120px;">
                <option value="">Any Market</option>
            </select>
            <button onclick="aiSearch()" style="padding: 14px 28px; background: linear-gradient(135deg, #667eea, #764ba2); color: white; border: none; border-radius: 10px; font-weight: 600; cursor: pointer;">Search</button>
        </div>

        <!-- Provider Badges -->
        <div id="aiProviderBadges" style="display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 15px;"></div>

        <!-- Credits Display -->
        <div id="aiCreditsBar" style="display: flex; justify-content: space-between; align-items: center; padding: 8px 14px; background: #f8f9fa; border-radius: 8px; font-size: 13px; color: #666; margin-bottom: 15px;">
            <span>Credits: <strong id="aiCreditBalance">--</strong> RLUSD</span>
            <span>Free queries today: <strong id="aiFreeRemaining">--</strong></span>
            <a href="/portal" style="padding: 6px 14px; background: #28a745; color: white; border: none; border-radius: 6px; font-size: 12px; cursor: pointer; text-decoration: none; display: inline-block;">Use Your Own AI via Proxy</a>
            <button onclick="showAddProvider()" style="padding: 6px 14px; background: #6c757d; color: white; border: none; border-radius: 6px; font-size: 12px; cursor: pointer; margin-left: 5px;">+ Add API Key</button>
        </div>

        <!-- Results Area -->
        <div id="aiResults" style="display: none;">
            <div id="aiBestResponse" style="padding: 20px; background: #f0f4ff; border-radius: 10px; border-left: 4px solid #667eea; margin-bottom: 15px;">
                <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                    <span style="font-weight: 600; color: #667eea;" id="aiBestProvider">--</span>
                    <span style="font-size: 12px; color: #fff;" id="aiBestTime">--</span>
                </div>
                <div id="aiBestText" style="line-height: 1.6; white-space: pre-wrap;"></div>
            </div>
            <details style="margin-bottom: 15px;">
                <summary style="cursor: pointer; font-weight: 600; color: #666; padding: 8px 0;">All Provider Responses (<span id="aiResponseCount">0</span>)</summary>
                <div id="aiAllResponses" style="margin-top: 10px;"></div>
            </details>
        </div>
        <div id="aiSearching" style="display: none; text-align: center; padding: 30px; color: #fff;">
            <div style="font-size: 24px; margin-bottom: 10px;">Querying AI providers...</div>
            <div style="font-size: 13px;">Searching across multiple models simultaneously</div>
        </div>

        <!-- Query History -->
        <details id="aiHistorySection" style="margin-top: 10px;">
            <summary style="cursor: pointer; font-weight: 600; color: #666; padding: 8px 0;">Recent Queries</summary>
            <div id="aiHistory" style="margin-top: 10px;"></div>
        </details>
    </div>

    <!-- Private Market Deal Section -->
    <div class="card card-light" style="padding: 30px; margin-bottom: 20px;">
        <h2 style="color: #1a1a2e; margin-bottom: 5px;">Private Market Escrow</h2>
        <p style="color: #666; margin-bottom: 20px;">Trustless XRPL smart contracts for person-to-person transactions — optional but safer than direct payment</p>

        <div id="dealForm" style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-bottom: 20px;">
            <div>
                <label style="font-size: 13px; color: #666; display: block; margin-bottom: 4px;">Item Description</label>
                <input type="text" id="dealItem" placeholder="e.g. 2019 Toyota Supra RZ, 45k km"
                    style="width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 8px;">
            </div>
            <div>
                <label style="font-size: 13px; color: #666; display: block; margin-bottom: 4px;">Agreed Price (RLUSD)</label>
                <input type="number" id="dealPrice" placeholder="15000"
                    style="width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 8px;">
            </div>
            <div>
                <label style="font-size: 13px; color: #666; display: block; margin-bottom: 4px;">Seller Wallet (XRPL)</label>
                <input type="text" id="dealSellerWallet" placeholder="rXXXXXXXXXXXXXXXX"
                    style="width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 8px;">
            </div>
            <div>
                <label style="font-size: 13px; color: #666; display: block; margin-bottom: 4px;">Deal Type</label>
                <select id="dealType" style="width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 8px;">
                    <option value="goods">Physical Goods</option>
                    <option value="vehicle">Vehicle</option>
                    <option value="services">Services</option>
                    <option value="other">Other</option>
                </select>
            </div>
            <div>
                <label style="font-size: 13px; color: #666; display: block; margin-bottom: 4px;">Delivery Deadline (days)</label>
                <input type="number" id="dealDeadline" value="14" min="1" max="90"
                    style="width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 8px;">
            </div>
            <div>
                <label style="font-size: 13px; color: #666; display: block; margin-bottom: 4px;">Market</label>
                <select id="dealMarket" style="width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 8px;">
                    <option value="">Any</option>
                </select>
            </div>
        </div>
        <button onclick="createDeal()" style="padding: 12px 24px; background: linear-gradient(135deg, #f093fb, #f5576c); color: white; border: none; border-radius: 8px; font-weight: 600; cursor: pointer;">Build Smart Contract</button>

        <!-- Deal Contract Result -->
        <div id="dealResult" style="display: none; margin-top: 20px;">
            <h3 style="color: #1a1a2e;">Contract Terms</h3>
            <div id="dealTerms" style="padding: 15px; background: #f8f9fa; border-radius: 10px; margin-bottom: 10px;"></div>
            <div id="dealRisk" style="padding: 15px; background: #fff3cd; border-radius: 10px; margin-bottom: 10px;"></div>
            <button id="dealFundBtn" onclick="fundDeal()" style="padding: 12px 24px; background: #28a745; color: white; border: none; border-radius: 8px; font-weight: 600; cursor: pointer;">Fund Escrow on XRPL</button>
        </div>

        <!-- Active Deals -->
        <div style="margin-top: 20px;">
            <h3 style="color: #1a1a2e; margin-bottom: 10px;">Your Deals</h3>
            <div id="dealsList"></div>
        </div>
    </div>

    <!-- Add Provider Modal -->
    <div id="addProviderModal" style="display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); z-index: 1000; align-items: center; justify-content: center;">
        <div style="background: white; border-radius: 12px; padding: 30px; max-width: 500px; width: 90%; max-height: 80vh; overflow-y: auto;">
            <h3 style="margin-bottom: 15px;">Add API Key to Ensemble</h3>
            <p style="color: #666; font-size: 13px; margin-bottom: 10px;"><strong>Recommended:</strong> Use <a href="/portal" style="color: #667eea;">the Proxy Portal</a> to access your AI with your own subscription — just log in through the proxy and your AI sees the market data from that region. No API key needed.</p>
            <p style="color: #666; font-size: 13px; margin-bottom: 15px;"><strong>Advanced:</strong> Or add an API key below to feed your provider into Phoenix's ensemble search engine. No Phoenix credit cost when using your own keys.</p>
            <select id="addProviderKey" style="width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 8px; margin-bottom: 10px;">
                <option value="">Select provider...</option>
                <option value="anthropic">Claude (Anthropic)</option>
                <option value="openai">ChatGPT (OpenAI)</option>
                <option value="xai">Grok (xAI)</option>
                <option value="deepseek">DeepSeek</option>
                <option value="google">Gemini (Google)</option>
                <option value="mistral">Mistral</option>
                <option value="cohere">Cohere</option>
                <option value="huggingface">HuggingFace</option>
                <option value="ollama">Ollama (Local)</option>
            </select>
            <input type="password" id="addProviderApiKey" placeholder="API Key (not needed for Ollama)"
                style="width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 8px; margin-bottom: 10px;">
            <input type="text" id="addProviderModel" placeholder="Custom model (optional)"
                style="width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 8px; margin-bottom: 15px;">
            <div style="display: flex; gap: 10px;">
                <button onclick="addProvider()" style="flex:1; padding: 10px; background: #667eea; color: white; border: none; border-radius: 8px; cursor: pointer;">Add Provider</button>
                <button onclick="hideAddProvider()" style="flex:1; padding: 10px; background: #eee; border: none; border-radius: 8px; cursor: pointer;">Cancel</button>
            </div>
        </div>
    </div>
</div>

<script>
let currentDealId = null;

async function loadAIPage() {
    loadProviders();
    loadCredits();
    loadAIHistory();
    loadDeals();
    // Populate market selects
    try {
        const resp = await fetch('/api/portal/markets');
        const markets = await resp.json();
        const selects = [document.getElementById('aiMarketSelect'), document.getElementById('dealMarket')];
        selects.forEach(sel => {
            if (!sel) return;
            Object.entries(markets).forEach(([code, info]) => {
                const opt = document.createElement('option');
                opt.value = code;
                opt.textContent = (info.flag || '') + ' ' + (info.name || code);
                sel.appendChild(opt);
            });
        });
    } catch(e) {}
}

async function loadProviders() {
    try {
        const resp = await fetch('/api/portal/ai/providers');
        const data = await resp.json();
        const container = document.getElementById('aiProviderBadges');
        if (!container) return;
        container.innerHTML = '';
        Object.entries(data.providers || {}).forEach(([key, info]) => {
            const badge = document.createElement('span');
            badge.style.cssText = 'padding: 4px 10px; border-radius: 12px; font-size: 12px; font-weight: 500;';
            badge.style.background = info.available ? '#d4edda' : '#e9ecef';
            badge.style.color = info.available ? '#155724' : '#999';
            badge.textContent = info.name || key;
            container.appendChild(badge);
        });
    } catch(e) {}
}

async function loadCredits() {
    try {
        const resp = await fetch('/api/portal/ai/credits');
        const data = await resp.json();
        const bal = document.getElementById('aiCreditBalance');
        const free = document.getElementById('aiFreeRemaining');
        if (bal) bal.textContent = (data.balance || 0).toFixed(4);
        if (free) free.textContent = data.free_remaining || 0;
    } catch(e) {}
}

async function aiSearch() {
    const query = document.getElementById('aiSearchInput').value.trim();
    if (!query) return;
    const market = document.getElementById('aiMarketSelect').value;

    document.getElementById('aiResults').style.display = 'none';
    document.getElementById('aiSearching').style.display = 'block';

    try {
        const resp = await fetch('/api/portal/ai/search', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({query, market: market || null})
        });
        const data = await resp.json();
        document.getElementById('aiSearching').style.display = 'none';

        if (data.error) {
            alert(data.error);
            return;
        }

        document.getElementById('aiResults').style.display = 'block';
        document.getElementById('aiBestProvider').textContent = (data.best_provider || '') + ' / ' + (data.best_model || '');
        document.getElementById('aiBestTime').textContent = (data.response_time_ms || 0) + 'ms total';
        document.getElementById('aiBestText').textContent = data.best_response || '';
        document.getElementById('aiResponseCount').textContent = (data.all_responses || []).length;

        const allDiv = document.getElementById('aiAllResponses');
        allDiv.innerHTML = '';
        (data.all_responses || []).forEach(r => {
            const div = document.createElement('div');
            div.style.cssText = 'padding: 12px; background: #f8f9fa; border-radius: 8px; margin-bottom: 8px;';
            div.innerHTML = '<div style="display:flex;justify-content:space-between;margin-bottom:6px;">' +
                '<strong style="color:#667eea;">' + (r.provider || '') + ' / ' + (r.model || '') + '</strong>' +
                '<span style="font-size:12px;color:#999;">' + (r.time_ms || 0) + 'ms | score: ' + (r.score || 0) + '</span></div>' +
                '<div style="white-space:pre-wrap;font-size:14px;">' + (r.response || '').replace(/</g,'&lt;') + '</div>';
            allDiv.appendChild(div);
        });

        loadCredits();
        loadAIHistory();
    } catch(e) {
        document.getElementById('aiSearching').style.display = 'none';
        alert('Search failed: ' + e.message);
    }
}

async function loadAIHistory() {
    try {
        const resp = await fetch('/api/portal/ai/history');
        const data = await resp.json();
        const container = document.getElementById('aiHistory');
        if (!container) return;
        container.innerHTML = '';
        (data.queries || []).slice(0, 10).forEach(q => {
            const div = document.createElement('div');
            div.style.cssText = 'padding: 8px 12px; border-bottom: 1px solid #eee; cursor: pointer;';
            div.innerHTML = '<span style="font-weight:500;">' + (q.query_text || '').substring(0, 60) + '</span>' +
                '<span style="float:right;font-size:12px;color:#999;">' + (q.best_provider || '') + ' | ' + (q.credits_used || 0) + ' RLUSD</span>';
            div.onclick = () => { document.getElementById('aiSearchInput').value = q.query_text; aiSearch(); };
            container.appendChild(div);
        });
    } catch(e) {}
}

function showAddProvider() { document.getElementById('addProviderModal').style.display = 'flex'; }
function hideAddProvider() { document.getElementById('addProviderModal').style.display = 'none'; }

async function addProvider() {
    const provider = document.getElementById('addProviderKey').value;
    if (!provider) return alert('Select a provider');
    const api_key = document.getElementById('addProviderApiKey').value;
    const model = document.getElementById('addProviderModel').value;

    try {
        const resp = await fetch('/api/portal/ai/providers', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({provider, api_key: api_key || null, model: model || null})
        });
        const data = await resp.json();
        if (data.error) { alert(data.error); return; }
        hideAddProvider();
        loadProviders();
    } catch(e) { alert('Failed: ' + e.message); }
}

async function createDeal() {
    const details = {
        item_description: document.getElementById('dealItem').value,
        agreed_price: document.getElementById('dealPrice').value,
        seller_wallet: document.getElementById('dealSellerWallet').value,
        deal_type: document.getElementById('dealType').value,
        deadline_days: document.getElementById('dealDeadline').value,
        market: document.getElementById('dealMarket').value || null
    };
    if (!details.item_description || !details.agreed_price || !details.seller_wallet) {
        return alert('Fill in item, price, and seller wallet');
    }
    try {
        const resp = await fetch('/api/portal/deal/create', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(details)
        });
        const data = await resp.json();
        if (data.error) { alert(data.error); return; }
        currentDealId = data.deal.id;
        document.getElementById('dealResult').style.display = 'block';
        const terms = data.contract.escrow_terms;
        const risk = data.contract.risk_assessment;
        document.getElementById('dealTerms').innerHTML =
            '<p><strong>Item:</strong> ' + terms.item + '</p>' +
            '<p><strong>Price:</strong> ' + terms.price_rlusd + ' RLUSD</p>' +
            '<p><strong>Escrow Fee:</strong> ' + terms.fee_rlusd + ' RLUSD</p>' +
            '<p><strong>Total:</strong> ' + terms.total_rlusd + ' RLUSD</p>' +
            '<p><strong>Delivery:</strong> ' + terms.delivery_deadline_days + ' days | Dispute window: ' + terms.dispute_window_days + ' days</p>';
        document.getElementById('dealRisk').innerHTML =
            '<p><strong>Risk Score:</strong> ' + risk.score + '/10</p>' +
            (risk.fair_value_estimate ? '<p><strong>AI Fair Value Estimate:</strong> $' + risk.fair_value_estimate + '</p>' : '') +
            (risk.factors.length ? '<p><strong>Risk Factors:</strong> ' + risk.factors.join('; ') + '</p>' : '<p style="color:#28a745;">No significant risk factors detected</p>');
        loadDeals();
    } catch(e) { alert('Failed: ' + e.message); }
}

async function fundDeal() {
    if (!currentDealId) return;
    if (!confirm('Fund escrow on XRPL? This will lock your RLUSD until delivery is confirmed.')) return;
    try {
        const resp = await fetch('/api/portal/deal/' + currentDealId + '/fund', {method:'POST'});
        const data = await resp.json();
        if (data.error) { alert(data.error); return; }
        alert('Escrow funded! TX: ' + (data.tx_hash || 'pending'));
        loadDeals();
    } catch(e) { alert('Failed: ' + e.message); }
}

async function confirmDelivery(dealId) {
    if (!confirm('Confirm delivery? This releases the escrow to the seller.')) return;
    try {
        const resp = await fetch('/api/portal/deal/' + dealId + '/confirm-delivery', {method:'POST'});
        const data = await resp.json();
        if (data.error) { alert(data.error); return; }
        alert('Deal completed! Escrow released.');
        loadDeals();
    } catch(e) { alert('Failed: ' + e.message); }
}

async function disputeDeal(dealId) {
    const reason = prompt('Reason for dispute:');
    if (!reason) return;
    try {
        const resp = await fetch('/api/portal/deal/' + dealId + '/dispute', {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({reason})
        });
        const data = await resp.json();
        if (data.error) { alert(data.error); return; }
        alert('Dispute opened. Escrow is held until resolution.');
        loadDeals();
    } catch(e) { alert('Failed: ' + e.message); }
}

async function loadDeals() {
    try {
        const resp = await fetch('/api/portal/deals');
        const data = await resp.json();
        const container = document.getElementById('dealsList');
        if (!container) return;
        container.innerHTML = '';
        (data.deals || []).forEach(d => {
            const statusColors = {draft:'#ffc107',escrow_funded:'#17a2b8',delivered:'#28a745',completed:'#28a745',disputed:'#dc3545',cancelled:'#6c757d',expired:'#6c757d'};
            const div = document.createElement('div');
            div.style.cssText = 'padding: 12px; border: 1px solid #eee; border-radius: 8px; margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center;';
            let actions = '';
            if (d.status === 'escrow_funded') {
                actions = '<button onclick="confirmDelivery('+d.id+')" style="padding:6px 12px;background:#28a745;color:white;border:none;border-radius:6px;margin-right:5px;cursor:pointer;">Confirm Delivery</button>' +
                          '<button onclick="disputeDeal('+d.id+')" style="padding:6px 12px;background:#dc3545;color:white;border:none;border-radius:6px;cursor:pointer;">Dispute</button>';
            }
            div.innerHTML = '<div><strong>' + (d.item_description || '').substring(0,40) + '</strong><br>' +
                '<span style="font-size:12px;color:#999;">' + d.agreed_price_rlusd + ' RLUSD | Fee: ' + d.escrow_fee_rlusd + '</span></div>' +
                '<div style="display:flex;align-items:center;gap:10px;">' +
                '<span style="padding:4px 10px;border-radius:12px;font-size:12px;background:' + (statusColors[d.status]||'#eee') + ';color:white;">' + d.status + '</span>' +
                actions + '</div>';
            container.appendChild(div);
        });
        if (!(data.deals || []).length) container.innerHTML = '<p style="color:#999;font-size:13px;">No deals yet. Use the form above to create a trustless escrow for your next private market transaction.</p>';
    } catch(e) {}
}

// Initialize on load
if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', loadAIPage); }
else { loadAIPage(); }
</script>
"""

@app.route("/ai-search")
@login_required
def ai_search_page():
    return render_template_string(
        BASE_TEMPLATE,
        title="Phoenix AI",
        content=AI_SEARCH_CONTENT,
        current_user=current_user
    )


# --- PHOENIX AI CHAT INTERFACE ---

PHOENIX_AI_CONTENT = """
<style>
    .ai-chat-container { display: flex; height: calc(100vh - 80px); max-width: 1400px; margin: 0 auto; }
    .ai-sidebar { width: 280px; background: rgba(20,20,20,0.9); border-right: 1px solid rgba(255,107,53,0.2); padding: 20px; overflow-y: auto; display: flex; flex-direction: column; }
    .ai-sidebar-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
    .ai-sidebar-header h3 { font-family: 'Cinzel', serif; color: #ff6b35; font-size: 1.1rem; margin: 0; }
    .ai-new-chat-btn { background: linear-gradient(135deg, #ff6b35, #ff4d00); color: white; border: none; padding: 8px 16px; border-radius: 8px; cursor: pointer; font-family: 'Rajdhani', sans-serif; font-weight: 600; }
    .ai-new-chat-btn:hover { transform: scale(1.05); }
    .ai-conv-list { flex: 1; overflow-y: auto; }
    .ai-conv-item { padding: 10px 12px; border-radius: 8px; cursor: pointer; margin-bottom: 4px; color: #fff; font-size: 0.9rem; transition: background 0.2s; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .ai-conv-item:hover, .ai-conv-item.active { background: rgba(255,107,53,0.15); color: #fff; }
    .ai-conv-item .conv-time { font-size: 0.75rem; color: #666; display: block; }

    .ai-main { flex: 1; display: flex; flex-direction: column; background: rgba(10,10,10,0.95); }
    .ai-messages { flex: 1; overflow-y: auto; padding: 20px 40px; }
    .ai-message { margin-bottom: 24px; max-width: 800px; }
    .ai-message.user { margin-left: auto; }
    .ai-message.assistant { margin-right: auto; }
    .ai-message-content { padding: 16px 20px; border-radius: 16px; line-height: 1.6; font-family: 'Rajdhani', sans-serif; font-size: 1.05rem; }
    .ai-message.user .ai-message-content { background: linear-gradient(135deg, #ff6b35, #ff4d00); color: white; border-bottom-right-radius: 4px; }
    .ai-message.assistant .ai-message-content { background: rgba(40,40,40,0.9); color: #e0e0e0; border: 1px solid rgba(255,107,53,0.15); border-bottom-left-radius: 4px; }
    .ai-message-content table { width: 100%; border-collapse: collapse; margin: 12px 0; }
    .ai-message-content th, .ai-message-content td { padding: 8px 12px; border: 1px solid rgba(255,107,53,0.2); text-align: left; }
    .ai-message-content th { background: rgba(255,107,53,0.1); color: #ff6b35; }
    .ai-message-content a { color: #ff6b35; text-decoration: underline; }
    .ai-message-content code { background: rgba(0,0,0,0.3); padding: 2px 6px; border-radius: 4px; font-size: 0.9em; }
    .ai-message-content pre { background: rgba(0,0,0,0.4); padding: 12px; border-radius: 8px; overflow-x: auto; }

    .ai-tool-badge { display: inline-block; background: rgba(255,107,53,0.2); color: #ff6b35; padding: 2px 8px; border-radius: 4px; font-size: 0.8rem; margin: 4px 2px; }

    .ai-input-area { padding: 20px 40px; border-top: 1px solid rgba(255,107,53,0.15); background: rgba(15,15,15,0.95); }
    .ai-input-wrapper { display: flex; max-width: 800px; margin: 0 auto; background: rgba(30,30,30,0.9); border: 1px solid rgba(255,107,53,0.3); border-radius: 16px; overflow: hidden; }
    .ai-input-wrapper:focus-within { border-color: #ff6b35; box-shadow: 0 0 20px rgba(255,107,53,0.15); }
    .ai-input { flex: 1; background: transparent; border: none; color: #f5f5f5; padding: 16px 20px; font-family: 'Rajdhani', sans-serif; font-size: 1.05rem; outline: none; resize: none; max-height: 120px; }
    .ai-input::placeholder { color: #666; }
    .ai-send-btn { background: linear-gradient(135deg, #ff6b35, #ff4d00); color: white; border: none; padding: 16px 24px; cursor: pointer; font-size: 1.1rem; transition: opacity 0.2s; }
    .ai-send-btn:hover { opacity: 0.9; }
    .ai-send-btn:disabled { opacity: 0.4; cursor: not-allowed; }

    .ai-tier-badge { position: absolute; top: 10px; right: 20px; background: rgba(255,107,53,0.15); color: #ff6b35; padding: 4px 12px; border-radius: 20px; font-size: 0.8rem; font-family: 'Rajdhani', sans-serif; }

    .ai-quick-actions { display: flex; gap: 8px; justify-content: center; margin: 20px 0; flex-wrap: wrap; }
    .ai-quick-btn { background: rgba(30,30,30,0.8); border: 1px solid rgba(255,107,53,0.2); color: #fff; padding: 8px 16px; border-radius: 20px; cursor: pointer; font-family: 'Rajdhani', sans-serif; font-size: 0.9rem; transition: all 0.2s; }
    .ai-quick-btn:hover { border-color: #ff6b35; color: #ff6b35; background: rgba(255,107,53,0.1); }

    .ai-welcome { text-align: center; padding: 40px 20px; }
    .ai-welcome h2 { font-family: 'Cinzel', serif; color: #ff6b35; font-size: 2rem; margin-bottom: 16px; }
    .ai-welcome .ai-welcome-intro { color: #fff; font-size: 0.95rem; max-width: 560px; margin: 0 auto 12px; line-height: 1.7; text-align: left; }
    .ai-welcome .ai-welcome-invite { color: #ff6b35; font-size: 0.95rem; max-width: 560px; margin: 0 auto 28px; line-height: 1.6; font-weight: 600; }

    .ai-typing { display: inline-block; }
    .ai-typing span { display: inline-block; width: 8px; height: 8px; background: #ff6b35; border-radius: 50%; margin: 0 2px; animation: typing 1.4s infinite; }
    .ai-typing span:nth-child(2) { animation-delay: 0.2s; }
    .ai-typing span:nth-child(3) { animation-delay: 0.4s; }
    @keyframes typing { 0%,60%,100% { transform: translateY(0); } 30% { transform: translateY(-8px); } }

    /* Rich card styles */
    .ai-cards { display: flex; flex-direction: column; gap: 10px; margin-top: 12px; }
    .ai-card { background: rgba(20,20,20,0.9); border: 1px solid rgba(255,107,53,0.25); border-radius: 12px; padding: 14px 16px; transition: border-color 0.2s; }
    .ai-card:hover { border-color: rgba(255,107,53,0.5); }
    .ai-card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
    .ai-card-title { font-weight: 700; color: #f5f5f5; font-size: 1rem; }
    .ai-card-badge { background: rgba(255,107,53,0.2); color: #ff6b35; padding: 2px 8px; border-radius: 6px; font-size: 0.8rem; font-weight: 600; }
    .ai-card-badge.green { background: rgba(0,200,100,0.15); color: #00c864; }
    .ai-card-row { display: flex; justify-content: space-between; align-items: center; padding: 4px 0; font-size: 0.92rem; color: #fff; }
    .ai-card-row .label { color: #fff; }
    .ai-card-row .value { color: #e0e0e0; font-weight: 600; }
    .ai-card-price { font-size: 1.3rem; font-weight: 700; color: #ff6b35; }
    .ai-card-savings { color: #00c864; font-size: 0.85rem; font-weight: 600; }
    .ai-card-action { display: inline-block; margin-top: 8px; padding: 6px 16px; background: linear-gradient(135deg, #ff6b35, #ff4d00); color: white; border: none; border-radius: 8px; cursor: pointer; font-family: 'Rajdhani', sans-serif; font-weight: 600; font-size: 0.9rem; text-decoration: none; }
    .ai-card-action:hover { opacity: 0.9; }
    .ai-card-actions { display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap; }
    .ai-card-btn { padding: 6px 14px; border-radius: 8px; font-family: 'Rajdhani', sans-serif; font-weight: 600; font-size: 0.85rem; cursor: pointer; text-decoration: none; border: none; transition: opacity 0.2s; }
    .ai-card-btn.primary { background: linear-gradient(135deg, #ff6b35, #ff4d00); color: white; }
    .ai-card-btn.save { background: rgba(255,107,53,0.1); border: 1px solid rgba(255,107,53,0.3); color: #ff6b35; }
    .ai-card-btn:hover { opacity: 0.85; }
    .ai-card-divider { border: none; border-top: 1px solid rgba(255,107,53,0.1); margin: 8px 0; }
    .ai-card-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 12px; }
    @media (max-width: 600px) { .ai-card-grid { grid-template-columns: 1fr; } }

    .ai-wallet-card { display: flex; align-items: center; gap: 12px; }
    .ai-wallet-icon { width: 36px; height: 36px; border-radius: 50%; background: rgba(255,107,53,0.15); display: flex; align-items: center; justify-content: center; font-size: 1.2rem; color: #ff6b35; flex-shrink: 0; }
    .ai-wallet-details { flex: 1; }

    @media (max-width: 768px) {
        .ai-sidebar { display: none; }
        .ai-messages { padding: 15px; }
        .ai-input-area { padding: 15px; }
    }
</style>

<div class="ai-chat-container" style="position: relative;">
    <div class="ai-tier-badge" id="tierBadge">Loading...</div>
    <div class="ai-saved-deals" id="savedDealsBar" style="display:none;align-items:center;gap:6px;padding:4px 12px;background:rgba(255,107,53,0.1);border-radius:8px;font-size:0.85rem;color:#ff6b35;cursor:pointer;" onclick="showSavedDeals()"><span id="savedDealsCounter">0</span> saved deals</div>

    <div class="ai-sidebar">
        <div class="ai-sidebar-header">
            <h3>Conversations</h3>
            <button class="ai-new-chat-btn" onclick="newConversation()">+ New</button>
        </div>
        <div class="ai-conv-list" id="convList"></div>
    </div>

    <div class="ai-main">
        <div class="ai-messages" id="messages">
            <div class="ai-welcome" id="welcomeScreen">
                <h2>Phoenix AI</h2>
                <p class="ai-welcome-intro">
                    Phoenix is an intelligent arbitrage engine. Prices for flights, hotels, products, rentals, and cruises vary dramatically depending on which country you book from. Phoenix uses a global proxy network to search across 195 markets simultaneously, finds where the price is lowest, and helps you purchase at that price — regardless of where you are.
                </p>
                <p class="ai-welcome-intro">
                    You can search for anything by describing what you want, or paste a link to a specific product, listing, or booking page. Phoenix will compare that item across markets and show you where the best deal is. The more you search, the smarter Phoenix gets at finding arbitrage patterns.
                </p>
                <p class="ai-welcome-intro">
                    Want to earn? <a href="/helper" style="color:#ff6b35;">Become a Helper Node</a> — contribute your local browsing to the Phoenix proxy network and earn XRP for every request you serve. The network grows stronger with every node.
                </p>
                <p class="ai-welcome-invite">
                    Try a search below, paste a link to something you want to buy, or invite others to join.
                </p>
                <div class="ai-quick-actions">
                    <button class="ai-quick-btn" onclick="sendQuick('Find the cheapest flights from NYC to Tokyo next month')">Flights to Tokyo</button>
                    <button class="ai-quick-btn" onclick="sendQuick('Compare hotel prices in Bali across different markets')">Hotels in Bali</button>
                    <button class="ai-quick-btn" onclick="sendQuick('Compare MacBook Pro prices across countries')">MacBook prices</button>
                    <button class="ai-quick-btn" onclick="sendQuick('Find cruise deals in the Mediterranean')">Med cruises</button>
                    <button class="ai-quick-btn" onclick="sendQuick('Show me trending arbitrage opportunities right now')">Trending deals</button>
                    <button class="ai-quick-btn" onclick="sendQuick('How do I become a helper node and start earning?')">Become a node</button>
                </div>
                <div style="margin-top: 20px; display: flex; gap: 12px; justify-content: center; flex-wrap: wrap;">
                    <a href="/register" style="padding: 10px 24px; background: linear-gradient(135deg, #ff6b35, #ff4d00); color: white; border-radius: 10px; text-decoration: none; font-weight: 600; font-size: 0.9rem; font-family: 'Rajdhani', sans-serif;">Invite a Friend</a>
                    <a href="/helper" style="padding: 10px 24px; background: rgba(255,107,53,0.1); border: 1px solid rgba(255,107,53,0.3); color: #ff6b35; border-radius: 10px; text-decoration: none; font-weight: 600; font-size: 0.9rem; font-family: 'Rajdhani', sans-serif;">Onboard as Node</a>
                </div>
            </div>
        </div>

        <div class="ai-input-area">
            <div class="ai-input-wrapper">
                <textarea class="ai-input" id="chatInput" placeholder="Ask Phoenix AI anything..." rows="1" onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendMessage();}"></textarea>
                <button class="ai-send-btn" id="sendBtn" onclick="sendMessage()">&#10148;</button>
            </div>
        </div>
    </div>
</div>

<script>
let currentConvId = null;
let isProcessing = false;
const isGuest = !__IS_AUTHENTICATED__;

async function saveDeal(dealData) {
    try {
        const resp = await fetch('/api/v1/ai/save-deal', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify(dealData)
        });
        const data = await resp.json();
        if (data.saved) {
            const counter = document.getElementById('savedDealsCounter');
            if (counter) {
                counter.textContent = data.deal_count;
                counter.parentElement.style.display = 'flex';
            }
        }
    } catch(e) { console.warn('Save deal failed', e); }
}

async function showSavedDeals() {
    try {
        const resp = await fetch('/api/v1/ai/saved-deals', { credentials: 'same-origin' });
        const data = await resp.json();
        if (data.deals && data.deals.length) {
            let html = '<strong>Your Saved Deals:</strong><br>';
            data.deals.forEach((d, i) => {
                html += (i+1) + '. ' + esc(d.title) + ' — ' + esc(d.currency || 'USD') + ' ' + (d.price || '?');
                if (d.savings_pct > 0) html += ' (Save ' + Math.round(d.savings_pct) + '%)';
                html += '<br>';
            });
            if (isGuest) html += '<br><a href="/register" style="color:#ff6b35;font-weight:600;">Sign up to book these deals</a>';
            appendMessage('assistant', html);
        } else {
            appendMessage('assistant', 'No saved deals yet. Search for something and click "Save Deal" on any result.');
        }
    } catch(e) { appendMessage('assistant', 'Could not load saved deals.'); }
}

async function loadSavedDealsCount() {
    try {
        const resp = await fetch('/api/v1/ai/saved-deals', { credentials: 'same-origin' });
        const data = await resp.json();
        if (data.count > 0) {
            document.getElementById('savedDealsCounter').textContent = data.count;
            document.getElementById('savedDealsBar').style.display = 'flex';
        }
    } catch(e) {}
}

async function loadConversations() {
    try {
        const resp = await fetch('/api/v1/ai/conversations');
        const data = await resp.json();
        const list = document.getElementById('convList');
        list.innerHTML = '';
        (data.conversations || []).forEach(c => {
            const div = document.createElement('div');
            div.className = 'ai-conv-item' + (c.conversation_id === currentConvId ? ' active' : '');
            div.innerHTML = (c.title || 'New conversation') + '<span class="conv-time">' + new Date(c.last_message_at).toLocaleDateString() + '</span>';
            div.onclick = () => loadConversation(c.conversation_id);
            list.appendChild(div);
        });
    } catch(e) { console.error('Failed to load conversations:', e); }
}

async function loadConversation(convId) {
    currentConvId = convId;
    try {
        const resp = await fetch('/api/v1/ai/conversations/' + convId);
        const data = await resp.json();
        const msgs = document.getElementById('messages');
        msgs.innerHTML = '';
        (data.messages || []).forEach(m => {
            appendMessage(m.role, m.content, m.tool_calls);
        });
        msgs.scrollTop = msgs.scrollHeight;
        loadConversations();
    } catch(e) { console.error('Failed to load conversation:', e); }
}

function newConversation() {
    currentConvId = null;
    const msgs = document.getElementById('messages');
    msgs.innerHTML = document.getElementById('welcomeScreen') ? '' : '';
    // Re-add welcome screen
    msgs.innerHTML = '<div class="ai-welcome" id="welcomeScreen"><h2>Phoenix AI</h2><p class="ai-welcome-intro">Phoenix is an intelligent arbitrage engine. Prices for flights, hotels, products, rentals, and cruises vary dramatically depending on which country you book from. Phoenix uses a global proxy network to search across 195 markets simultaneously, finds where the price is lowest, and helps you purchase at that price.</p><p class="ai-welcome-intro">You can search for anything by describing what you want, or paste a link to a specific product, listing, or booking page. Phoenix will compare that item across markets and show you where the best deal is.</p><p class="ai-welcome-intro">Want to earn? <a href="/helper" style="color:#ff6b35;">Become a Helper Node</a> \u2014 contribute your local browsing to the Phoenix proxy network and earn XRP for every request you serve.</p><p class="ai-welcome-invite">Try a search below, paste a link to something you want to buy, or invite others to join.</p><div class="ai-quick-actions"><button class="ai-quick-btn" onclick="sendQuick(&#39;Find the cheapest flights from NYC to Tokyo next month&#39;)">Flights to Tokyo</button><button class="ai-quick-btn" onclick="sendQuick(&#39;Compare hotel prices in Bali across different markets&#39;)">Hotels in Bali</button><button class="ai-quick-btn" onclick="sendQuick(&#39;Compare MacBook Pro prices across countries&#39;)">MacBook prices</button><button class="ai-quick-btn" onclick="sendQuick(&#39;Find cruise deals in the Mediterranean&#39;)">Med cruises</button><button class="ai-quick-btn" onclick="sendQuick(&#39;Show me trending arbitrage opportunities right now&#39;)">Trending deals</button><button class="ai-quick-btn" onclick="sendQuick(&#39;How do I become a helper node and start earning?&#39;)">Become a node</button></div><div style="margin-top:20px;display:flex;gap:12px;justify-content:center;flex-wrap:wrap;"><a href="/register" style="padding:10px 24px;background:linear-gradient(135deg,#ff6b35,#ff4d00);color:white;border-radius:10px;text-decoration:none;font-weight:600;font-size:0.9rem;">Invite a Friend</a><a href="/helper" style="padding:10px 24px;background:rgba(255,107,53,0.1);border:1px solid rgba(255,107,53,0.3);color:#ff6b35;border-radius:10px;text-decoration:none;font-weight:600;font-size:0.9rem;">Onboard as Node</a></div></div>';
}

function sendQuick(text) {
    document.getElementById('chatInput').value = text;
    sendMessage();
}

function appendMessage(role, content, toolCalls) {
    const msgs = document.getElementById('messages');
    const welcome = document.getElementById('welcomeScreen');
    if (welcome) welcome.remove();

    const div = document.createElement('div');
    div.className = 'ai-message ' + role;

    let toolBadges = '';
    let richCards = '';
    if (toolCalls && Array.isArray(toolCalls)) {
        toolBadges = toolCalls.map(t => '<span class="ai-tool-badge">' + (t.tool || t.name || 'tool') + '</span>').join(' ');
        richCards = toolCalls.map(t => renderToolCard(t)).filter(Boolean).join('');
    }

    div.innerHTML = '<div class="ai-message-content">' + (toolBadges ? toolBadges + '<br>' : '') + formatContent(content) + richCards + '</div>';
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
}

function renderToolCard(tc) {
    if (!tc || !tc.result) return '';
    const tool = tc.tool;
    const r = tc.result;
    try {
        if (tool === 'search_flights') return renderFlightCards(r);
        if (tool === 'search_hotels' || tool === 'search_cruises' || tool === 'search_rentals') return renderArbitrageCards(r, tool);
        if (tool === 'get_deals' || tool === 'discover_opportunities') return renderDealCards(r);
        if (tool === 'get_wallet_info') return renderWalletCard(r);
        if (tool === 'get_my_dashboard') return renderDashboardCard(r);
        if (tool === 'get_my_transactions') return renderTransactionsCard(r);
        if (tool === 'get_helper_status') return renderHelperCard(r);
        if (tool === 'get_node_status') return renderNodeCard(r);
        if (tool === 'get_earnings') return renderEarningsCard(r);
        if (tool === 'get_trending') return renderTrendingCards(r);
        if (tool === 'create_proxy_session') return renderProxyCard(r);
        if (tool === 'get_ramp_providers') return renderRampCards(r);
    } catch(e) { console.warn('Card render failed for', tool, e); }
    return '';
}

function esc(s) { return s ? String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;') : ''; }

function dealActionButtons(dealData) {
    const d = JSON.stringify(dealData).replace(/'/g, "\\'").replace(/"/g, '&quot;');
    const dSafe = d.replace(/&quot;/g, "'");
    if (isGuest) {
        return '<div class="ai-card-actions">' +
            '<button class="ai-card-btn save" onclick="saveDeal(' + dSafe + ')">Save Deal</button>' +
            '<a href="/register" class="ai-card-btn primary">Sign Up to Book</a>' +
            '</div>';
    }
    return '<div class="ai-card-actions">' +
        '<button class="ai-card-btn save" onclick="saveDeal(' + dSafe + ')">Save Deal</button>' +
        '<button class="ai-card-btn primary" onclick="bookFlight(' + dSafe + ')">Book Flight</button>' +
        '</div>';
}

async function bookFlight(dealData) {
    // Save deal to DB and redirect to Phoenix booking page
    const btn = event.target;
    btn.disabled = true;
    btn.textContent = 'Preparing...';
    try {
        const resp = await fetch('/api/v1/ai/book-flight', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify(dealData)
        });
        const data = await resp.json();
        if (data.deal_id) {
            window.location.href = '/book/' + data.deal_id;
        } else {
            btn.textContent = 'Book Flight';
            btn.disabled = false;
            alert(data.error || 'Could not prepare booking. Please try again.');
        }
    } catch(e) {
        btn.textContent = 'Book Flight';
        btn.disabled = false;
        alert('Booking service unavailable. Please try again.');
    }
}

function renderFlightCards(r) {
    const flights = r.flights || r.all_flights || r.results || [];
    if (!flights.length) return '';
    let html = '';

    // Price comparison header if available
    const proxy = r.proxy_results || {};
    if (proxy.savings_vs_us > 0) {
        html += '<div class="ai-card" style="border-left:3px solid #00e676;margin-bottom:12px;">';
        html += '<div class="ai-card-header"><span class="ai-card-title" style="color:#00e676;">Phoenix Deal Found</span>';
        html += '<span class="ai-card-badge green">Save $' + Math.round(proxy.savings_vs_us) + ' (' + Math.round(proxy.savings_pct) + '%)</span></div>';
        html += '<div class="ai-card-row"><span class="label">Phoenix price</span><span class="value" style="color:#00e676;">$' + Math.round(proxy.cheapest_price_usd || 0) + '</span></div>';
        html += '<div class="ai-card-row"><span class="label">Regions compared</span><span class="value">' + (typeof proxy.markets_checked === 'number' ? proxy.markets_checked : (proxy.markets_checked || []).length || '5') + '</span></div>';
        html += '</div>';
    }

    // Sort flights: best deals first (highest savings), then by cheapest price
    flights.sort((a, b) => {
        const aSave = (a.deal && a.deal.price_difference) || a.savings_pct || 0;
        const bSave = (b.deal && b.deal.price_difference) || b.savings_pct || 0;
        if (bSave !== aSave) return bSave - aSave;
        const aP = a.cheapest_price || a.price || a.amount || 9999;
        const bP = b.cheapest_price || b.price || b.amount || 9999;
        return aP - bP;
    });

    // Show flight count
    html += '<div style="color:#999;font-size:0.82rem;margin-bottom:8px;">' + flights.length + ' flights found</div>';

    html += '<div class="ai-cards">';
    flights.forEach((f, idx) => {
        const airline = esc(f.airline || f.carrier || 'Unknown');
        const price = f.cheapest_price || f.price || f.amount || '';
        const market = 'Phoenix';  // Never expose proxy market codes
        const stops = f.stops != null ? (f.stops === 0 ? 'Nonstop' : f.stops + ' stop' + (f.stops !== 1 ? 's' : '')) : '';
        const duration = esc(f.duration || '');
        const savings = f.savings_pct || f.savings_percent || 0;
        const flightNum = esc(f.flight_number || '');

        // Format departure/arrival with airport codes
        const depAirport = f.segments && f.segments.length ? esc(f.segments[0].departure_airport || '') : esc(f.origin || '');
        const arrAirport = f.segments && f.segments.length ? esc(f.segments[f.segments.length - 1].arrival_airport || '') : esc(f.destination || '');

        // Format times - extract just HH:MM from ISO datetime
        function fmtTime(t) {
            if (!t) return '';
            const m = String(t).match(/(\d{1,2}:\d{2})/);
            return m ? m[1] : t;
        }
        const depTime = fmtTime(f.departure_time || f.departure || '');
        const arrTime = fmtTime(f.arrival_time || '');

        html += '<div class="ai-card">';

        // Header: airline + flight number + savings badge
        html += '<div class="ai-card-header"><span class="ai-card-title">' + airline + (flightNum ? ' <span style="color:#aaa;font-weight:400;font-size:0.88rem;">' + flightNum + '</span>' : '') + '</span>';
        if (savings > 0) html += '<span class="ai-card-badge green">Save ' + Math.round(savings) + '%</span>';
        html += '</div>';

        // Route line: departure airport/time → arrival airport/time
        if (depTime || arrTime) {
            html += '<div class="ai-card-row" style="font-size:0.95rem;">';
            html += '<span class="value" style="letter-spacing:0.3px;">';
            html += '<strong>' + depAirport + '</strong> ' + depTime;
            html += ' → ';
            html += '<strong>' + arrAirport + '</strong> ' + arrTime;
            html += '</span></div>';
        } else {
            html += '<div class="ai-card-row"><span class="label">Route</span><span class="value">' + depAirport + ' → ' + arrAirport + '</span></div>';
        }

        // Duration + stops on one line
        if (stops || duration) {
            html += '<div class="ai-card-row"><span class="label">' + stops + '</span><span class="value">' + duration + '</span></div>';
        }

        // Layover details (from Amadeus)
        const layovers = f.layovers || [];
        if (layovers.length > 0) {
            const layoverParts = layovers.map(l => esc(l.airport || '?') + ' (' + esc(l.duration_formatted || '?') + ')');
            html += '<div class="ai-card-row"><span class="label" style="color:#ff9800;">Layover</span><span class="value" style="color:#ff9800;font-size:0.85rem;">' + layoverParts.join(', ') + '</span></div>';
        }

        // Aircraft type
        const aircraft = f.airplane || '';
        if (aircraft) {
            html += '<div class="ai-card-row"><span class="label">Aircraft</span><span class="value" style="color:#999;font-size:0.82rem;">' + esc(aircraft) + '</span></div>';
        }

        // Baggage info
        if (f.baggage_info) {
            html += '<div class="ai-card-row"><span class="label">Baggage</span><span class="value" style="color:#999;font-size:0.82rem;">' + esc(f.baggage_info) + '</span></div>';
        }

        // Price — branded as Phoenix, no market codes exposed
        html += '<div class="ai-card-row" style="margin-top:4px;"><span class="ai-card-price">$' + (typeof price === 'number' ? Math.round(price) : price) + '</span>';
        html += '<span class="ai-card-badge" style="background:rgba(33,150,243,0.2);color:#42a5f5;">Phoenix</span>';
        html += '</div>';

        // Deal info (arbitrage comparison)
        const deal = f.deal;
        if (deal && deal.price_difference > 0) {
            html += '<div style="margin-top:6px;padding-top:6px;border-top:1px solid rgba(255,255,255,0.1);font-size:0.85rem;">';
            if (deal.home_price && deal.arbitrage_price) {
                html += '<div class="ai-card-row"><span class="label" style="color:#999;">Normal price</span><span class="value" style="color:#999;text-decoration:line-through;">$' + Math.round(deal.home_price) + '</span></div>';
                html += '<div class="ai-card-row"><span class="label" style="color:#00e676;">Phoenix price</span><span class="value" style="color:#00e676;font-weight:600;">$' + Math.round(deal.arbitrage_price) + '</span></div>';
            }
            html += '<div class="ai-card-row"><span class="label" style="color:#00e676;">You save</span><span class="value" style="color:#00e676;font-weight:700;">-$' + Math.round(deal.price_difference) + ' (' + Math.round(deal.user_saves_pct || savings) + '%)</span></div>';
            html += '</div>';
        }

        const dealPayload = {
            title: airline + ' ' + (flightNum || (depAirport + '-' + arrAirport)),
            airline: f.airline || f.marketing_carrier || airline,
            flight_number: flightNum,
            price: price, currency: 'USD',
            savings_pct: savings, market: 'Phoenix', vertical: 'flights',
            origin: f.origin || f.departure_airport || r.origin || '',
            destination: f.destination || f.arrival_airport || r.destination || '',
            date: f.date || f.departure_date || r.date || '',
            return_date: f.return_date || r.return_date || '',
            departure_time: f.departure_time || '',
            arrival_time: f.arrival_time || '',
            stops: f.stops || 0,
            home_price: deal ? deal.home_price : price,
            arbitrage_price: deal ? deal.arbitrage_price : price,
            price_difference: deal ? deal.price_difference : 0,
            cheapest_market: 'Phoenix',
            home_market: 'US',
            raw_offer: f.raw_offer || null,
        };
        html += dealActionButtons(dealPayload);
        html += '</div>';
    });
    html += '</div>';
    return html;
}

function renderArbitrageCards(r, tool) {
    const items = r.results || r.deals || [];
    if (!items.length) return '';
    const label = tool === 'search_hotels' ? 'Hotel' : tool === 'search_cruises' ? 'Cruise' : 'Rental';
    let html = '<div class="ai-cards">';
    items.slice(0, 5).forEach(item => {
        const name = esc(item.name || item.title || label);
        const price = item.price || item.amount || '';
        const savings = item.savings_pct || item.savings_percent || 0;
        html += '<div class="ai-card"><div class="ai-card-header"><span class="ai-card-title">' + name + '</span>';
        if (savings > 0) html += '<span class="ai-card-badge green">Save ' + Math.round(savings) + '%</span>';
        html += '</div>';
        if (price) html += '<div class="ai-card-row"><span class="ai-card-price">' + esc(item.currency || 'USD') + ' ' + price + '</span></div>';
        if (item.location) html += '<div class="ai-card-row"><span class="label">Location</span><span class="value">' + esc(item.location) + '</span></div>';
        if (item.market) html += '<div class="ai-card-row"><span class="label">Market</span><span class="value">' + esc(item.market) + '</span></div>';
        html += dealActionButtons({title: name, price: price, currency: item.currency || 'USD', savings_pct: savings, market: item.market || '', vertical: label.toLowerCase() + 's'});
        html += '</div>';
    });
    html += '</div>';
    return html;
}

function renderDealCards(r) {
    const deals = r.deals || r.opportunities || r.results || [];
    if (!deals.length) return '';
    let html = '<div class="ai-cards">';
    deals.slice(0, 5).forEach(d => {
        const title = esc(d.title || d.route || d.name || 'Deal');
        const savings = d.savings_pct || d.savings_percent || d.savings || 0;
        html += '<div class="ai-card"><div class="ai-card-header"><span class="ai-card-title">' + title + '</span>';
        if (savings > 0) html += '<span class="ai-card-badge green">' + Math.round(savings) + '% off</span>';
        html += '</div>';
        if (d.price) html += '<div class="ai-card-row"><span class="ai-card-price">' + esc(d.currency || 'USD') + ' ' + d.price + '</span></div>';
        if (d.market) html += '<div class="ai-card-row"><span class="label">Source</span><span class="value">Phoenix</span></div>';
        if (d.vertical) html += '<div class="ai-card-row"><span class="label">Type</span><span class="value">' + esc(d.vertical) + '</span></div>';
        html += dealActionButtons({title: d.title || d.name || 'Deal', price: d.price, currency: d.currency || 'USD', savings_pct: savings, market: d.market || '', vertical: d.vertical || ''});
        html += '</div>';
    });
    html += '</div>';
    return html;
}

function renderWalletCard(r) {
    let html = '<div class="ai-cards">';
    const wallets = r.wallets || [];
    const cards = r.cards || [];
    if (wallets.length) {
        wallets.forEach(w => {
            html += '<div class="ai-card"><div class="ai-wallet-card"><div class="ai-wallet-icon">&#9670;</div><div class="ai-wallet-details">';
            html += '<div class="ai-card-title">' + esc(w.type || 'Wallet') + '</div>';
            html += '<div class="ai-card-row"><span class="label">Address</span><span class="value" style="font-size:0.82rem;word-break:break-all;">' + esc(w.address || '') + '</span></div>';
            if (w.balance != null) html += '<div class="ai-card-row"><span class="label">Balance</span><span class="value">' + w.balance + ' ' + esc(w.currency || 'XRP') + '</span></div>';
            html += '</div></div></div>';
        });
    }
    if (cards.length) {
        cards.forEach(c => {
            html += '<div class="ai-card"><div class="ai-wallet-card"><div class="ai-wallet-icon">&#9646;</div><div class="ai-wallet-details">';
            html += '<div class="ai-card-title">' + esc(c.type || 'Card') + ' ••' + esc(c.last4 || '****') + '</div>';
            if (c.zones) html += '<div class="ai-card-row"><span class="label">Zones</span><span class="value">' + esc(c.zones) + '</span></div>';
            html += '</div></div></div>';
        });
    }
    if (r.zone_coverage) {
        html += '<div class="ai-card"><div class="ai-card-header"><span class="ai-card-title">Zone Coverage</span></div>';
        html += '<div class="ai-card-row"><span class="label">Markets Reachable</span><span class="value">' + esc(r.zone_coverage) + '</span></div></div>';
    }
    if (!wallets.length && !cards.length && !r.zone_coverage) {
        html += '<div class="ai-card"><div class="ai-card-title">No wallets or cards connected</div><a href="/wallet" class="ai-card-action">Set Up Wallet</a></div>';
    }
    html += '</div>';
    return html;
}

function renderDashboardCard(r) {
    let html = '<div class="ai-card-grid">';
    const stats = [
        ['Bookings', r.total_bookings || r.bookings || 0],
        ['Total Saved', (r.total_savings || r.savings || '$0')],
        ['Transactions', r.total_transactions || r.transactions || 0],
        ['Queries Used', r.queries_used || 0],
    ];
    stats.forEach(([label, val]) => {
        html += '<div class="ai-card"><div class="ai-card-row"><span class="label">' + label + '</span><span class="ai-card-price" style="font-size:1.1rem;">' + val + '</span></div></div>';
    });
    html += '</div>';
    return html;
}

function renderTransactionsCard(r) {
    const txns = r.transactions || [];
    if (!txns.length) return '<div class="ai-cards"><div class="ai-card"><div class="ai-card-title">No recent transactions</div></div></div>';
    let html = '<div class="ai-cards">';
    txns.slice(0, 5).forEach(t => {
        html += '<div class="ai-card"><div class="ai-card-header"><span class="ai-card-title">' + esc(t.type || t.description || 'Transaction') + '</span>';
        html += '<span class="ai-card-badge">' + esc(t.status || '') + '</span></div>';
        if (t.amount) html += '<div class="ai-card-row"><span class="label">Amount</span><span class="value">' + esc(t.currency || '') + ' ' + t.amount + '</span></div>';
        if (t.date) html += '<div class="ai-card-row"><span class="label">Date</span><span class="value">' + esc(t.date) + '</span></div>';
        html += '</div>';
    });
    html += '</div>';
    return html;
}

function renderHelperCard(r) {
    let html = '<div class="ai-cards"><div class="ai-card">';
    html += '<div class="ai-card-header"><span class="ai-card-title">Helper Profile</span>';
    html += '<span class="ai-card-badge">' + esc(r.status || 'inactive') + '</span></div>';
    if (r.earnings != null) html += '<div class="ai-card-row"><span class="label">Earnings</span><span class="ai-card-price" style="font-size:1.1rem;">' + r.earnings + ' ' + esc(r.currency || 'XRP') + '</span></div>';
    if (r.tasks_completed != null) html += '<div class="ai-card-row"><span class="label">Tasks Done</span><span class="value">' + r.tasks_completed + '</span></div>';
    if (r.rating != null) html += '<div class="ai-card-row"><span class="label">Rating</span><span class="value">' + r.rating + '</span></div>';
    html += '</div></div>';
    return html;
}

function renderNodeCard(r) {
    let html = '<div class="ai-cards"><div class="ai-card">';
    html += '<div class="ai-card-header"><span class="ai-card-title">Node Status</span>';
    html += '<span class="ai-card-badge ' + (r.is_online ? 'green' : '') + '">' + (r.is_online ? 'Online' : 'Offline') + '</span></div>';
    if (r.uptime) html += '<div class="ai-card-row"><span class="label">Uptime</span><span class="value">' + esc(r.uptime) + '</span></div>';
    if (r.requests_served != null) html += '<div class="ai-card-row"><span class="label">Requests Served</span><span class="value">' + r.requests_served + '</span></div>';
    html += '</div></div>';
    return html;
}

function renderEarningsCard(r) {
    let html = '<div class="ai-cards"><div class="ai-card">';
    html += '<div class="ai-card-header"><span class="ai-card-title">Earnings Summary</span></div>';
    if (r.total != null) html += '<div class="ai-card-row"><span class="label">Total</span><span class="ai-card-price" style="font-size:1.1rem;">' + r.total + ' ' + esc(r.currency || 'XRP') + '</span></div>';
    if (r.this_month != null) html += '<div class="ai-card-row"><span class="label">This Month</span><span class="value">' + r.this_month + '</span></div>';
    if (r.pending != null) html += '<div class="ai-card-row"><span class="label">Pending</span><span class="value">' + r.pending + '</span></div>';
    html += '</div></div>';
    return html;
}

function renderTrendingCards(r) {
    const routes = r.routes || r.trending || r.results || [];
    if (!routes.length) return '';
    let html = '<div class="ai-cards">';
    routes.slice(0, 5).forEach(rt => {
        html += '<div class="ai-card"><div class="ai-card-header"><span class="ai-card-title">' + esc(rt.route || rt.origin + ' → ' + rt.destination || '') + '</span>';
        if (rt.savings_pct) html += '<span class="ai-card-badge green">' + Math.round(rt.savings_pct) + '% savings</span>';
        html += '</div>';
        if (rt.avg_price) html += '<div class="ai-card-row"><span class="label">Avg Price</span><span class="value">' + esc(rt.currency || 'USD') + ' ' + rt.avg_price + '</span></div>';
        if (rt.market) html += '<div class="ai-card-row"><span class="label">Best Market</span><span class="value">' + esc(rt.market) + '</span></div>';
        html += '</div>';
    });
    html += '</div>';
    return html;
}

function renderProxyCard(r) {
    if (r.error) return '';
    let html = '<div class="ai-cards"><div class="ai-card">';
    html += '<div class="ai-card-header"><span class="ai-card-title">Proxy Session Active</span><span class="ai-card-badge green">Connected</span></div>';
    if (r.country) html += '<div class="ai-card-row"><span class="label">Market</span><span class="value">' + esc(r.country) + '</span></div>';
    if (r.session_id) html += '<div class="ai-card-row"><span class="label">Session</span><span class="value" style="font-size:0.82rem;">' + esc(r.session_id) + '</span></div>';
    if (r.ip) html += '<div class="ai-card-row"><span class="label">IP</span><span class="value">' + esc(r.ip) + '</span></div>';
    html += '<a href="/portal" class="ai-card-action">Open Portal</a>';
    html += '</div></div>';
    return html;
}

function renderRampCards(r) {
    const providers = r.providers || r.ramps || [];
    if (!providers.length) return '';
    let html = '<div class="ai-cards">';
    providers.slice(0, 5).forEach(p => {
        html += '<div class="ai-card"><div class="ai-card-header"><span class="ai-card-title">' + esc(p.name || 'Provider') + '</span>';
        if (p.fee_pct != null) html += '<span class="ai-card-badge">' + p.fee_pct + '% fee</span>';
        html += '</div>';
        if (p.currencies) html += '<div class="ai-card-row"><span class="label">Currencies</span><span class="value">' + esc(p.currencies) + '</span></div>';
        if (p.methods) html += '<div class="ai-card-row"><span class="label">Methods</span><span class="value">' + esc(p.methods) + '</span></div>';
        html += '</div>';
    });
    html += '</div>';
    return html;
}

function formatContent(text) {
    if (!text) return '';
    // Basic markdown-like formatting
    return text
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/\\*\\*(.*?)\\*\\*/g, '<strong>$1</strong>')
        .replace(/\\*(.*?)\\*/g, '<em>$1</em>')
        .replace(/`([^`]+)`/g, '<code>$1</code>')
        .replace(/\\n/g, '<br>');
}

async function sendMessage() {
    if (isProcessing) return;
    const input = document.getElementById('chatInput');
    const text = input.value.trim();
    if (!text) return;

    input.value = '';
    input.style.height = 'auto';
    isProcessing = true;
    document.getElementById('sendBtn').disabled = true;

    appendMessage('user', text);

    // Show typing indicator
    const msgs = document.getElementById('messages');
    const typing = document.createElement('div');
    typing.className = 'ai-message assistant';
    typing.id = 'typingIndicator';
    typing.innerHTML = '<div class="ai-message-content"><div class="ai-typing"><span></span><span></span><span></span></div></div>';
    msgs.appendChild(typing);
    msgs.scrollTop = msgs.scrollHeight;

    try {
        const body = { message: text };
        if (currentConvId) body.conversation_id = currentConvId;

        const resp = await fetch('/api/v1/ai/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify(body)
        });

        const typingEl = document.getElementById('typingIndicator');
        if (typingEl) typingEl.remove();

        const contentType = resp.headers.get('content-type') || '';
        if (!contentType.includes('application/json')) {
            appendMessage('assistant', 'Something went wrong. Please refresh and try again.');
        } else if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            if (err.error === 'free_trial_exhausted') {
                appendMessage('assistant', '<div style="text-align:center;padding:16px 0;">' +
                    '<div style="font-size:1.3rem;font-weight:700;margin-bottom:8px;">You\\'ve used all 3 free searches</div>' +
                    '<div style="margin-bottom:16px;opacity:0.85;">Create a free account to keep searching and unlock unlimited arbitrage across flights, hotels, products, rentals, and cruises.</div>' +
                    '<div style="display:flex;gap:12px;justify-content:center;flex-wrap:wrap;">' +
                    '<a href="/register" style="padding:10px 24px;background:linear-gradient(135deg,#ff6b35,#ff4d00);color:white;border-radius:10px;text-decoration:none;font-weight:600;">Create Free Account</a>' +
                    '<a href="/login" style="padding:10px 24px;background:rgba(255,107,53,0.1);border:1px solid rgba(255,107,53,0.3);color:#ff6b35;border-radius:10px;text-decoration:none;font-weight:600;">Sign In</a>' +
                    '</div></div>');
            } else if (err.error === 'daily_limit_reached') {
                appendMessage('assistant', '<div style="text-align:center;padding:16px 0;">' +
                    '<div style="font-size:1.3rem;font-weight:700;margin-bottom:8px;">Daily limit reached</div>' +
                    '<div style="margin-bottom:16px;opacity:0.85;">' + (err.message || 'You have used your free queries for today.') + '</div>' +
                    '<div style="display:flex;gap:12px;justify-content:center;flex-wrap:wrap;">' +
                    '<a href="/dashboard#data-sharing" style="padding:10px 24px;background:linear-gradient(135deg,#ff6b35,#ff4d00);color:white;border-radius:10px;text-decoration:none;font-weight:600;">Share Data for More</a>' +
                    '<a href="/ai/pricing" style="padding:10px 24px;background:rgba(255,107,53,0.1);border:1px solid rgba(255,107,53,0.3);color:#ff6b35;border-radius:10px;text-decoration:none;font-weight:600;">Subscribe from $4.99/mo</a>' +
                    '</div></div>');
            } else {
                appendMessage('assistant', 'Error: ' + (err.error || 'Request failed'));
            }
        } else {
            const data = await resp.json();
            currentConvId = data.conversation_id;
            const r = data.response || {};
            appendMessage('assistant', r.content || 'No response', r.tool_calls);

            // Update tier badge
            if (data.usage) {
                const badge = document.getElementById('tierBadge');
                const remaining = data.usage.queries_remaining;
                if (data.usage.is_guest) {
                    badge.textContent = remaining + ' free ' + (remaining === 1 ? 'search' : 'searches') + ' left';
                } else if (data.usage.node_tier) {
                    const tier = data.usage.node_tier.charAt(0).toUpperCase() + data.usage.node_tier.slice(1);
                    badge.textContent = tier + ' Node: ' + (remaining === 'unlimited' ? 'Unlimited' : remaining + ' left');
                } else {
                    badge.textContent = (remaining === 'unlimited' ? 'Unlimited' : remaining + ' queries left');
                }
            }
        }

        loadConversations();
    } catch(e) {
        const typingEl = document.getElementById('typingIndicator');
        if (typingEl) typingEl.remove();
        appendMessage('assistant', 'Connection error. Please try again.');
    }

    isProcessing = false;
    document.getElementById('sendBtn').disabled = false;
    document.getElementById('chatInput').focus();
}

// Auto-resize textarea
document.getElementById('chatInput').addEventListener('input', function() {
    this.style.height = 'auto';
    this.style.height = Math.min(this.scrollHeight, 120) + 'px';
});

// Load tier info and conversations on page load
(async function() {
    try {
        const tierResp = await fetch('/api/v1/ai/tier', { credentials: 'same-origin' });
        if (tierResp.ok) {
            const tierData = await tierResp.json();
            const badge = document.getElementById('tierBadge');
            if (tierData.is_guest) {
                const r = tierData.usage ? tierData.usage.queries_remaining : 3;
                badge.textContent = r + ' free ' + (r === 1 ? 'search' : 'searches') + ' left';
            } else if (tierData.node_tier) {
                const nt = tierData.node_tier.charAt(0).toUpperCase() + tierData.node_tier.slice(1);
                const remaining = tierData.usage ? tierData.usage.queries_remaining : '?';
                const sub = tierData.tier_name && tierData.tier_name !== 'Node Free' ? ' + ' + tierData.tier_name : '';
                badge.textContent = nt + ' Node' + sub + ': ' + (remaining === 'unlimited' ? 'Unlimited' : tierData.node_free_per_day + '/day');
            } else {
                const remaining = tierData.queries_remaining;
                badge.textContent = tierData.tier_name + ': ' + (remaining === 'unlimited' ? 'Unlimited' : remaining + ' queries left');
            }
        }
    } catch(e) {}
    if (document.cookie.indexOf('session') !== -1 || document.cookie.indexOf('remember_token') !== -1) {
        loadConversations();
    }
    loadSavedDealsCount();
})();
</script>
"""


@app.route("/ai")
def phoenix_ai_page():
    """Phoenix AI conversational interface."""
    is_auth = "true" if current_user.is_authenticated else "false"
    content = PHOENIX_AI_CONTENT.replace("__IS_AUTHENTICATED__", is_auth)
    return render_template_string(
        BASE_TEMPLATE,
        title="Phoenix AI",
        content=content,
        current_user=current_user
    )


# --- Phoenix OS Install Page (Build #88) ---

PHOENIX_INSTALL_CONTENT = """
<style>
.welcome-container {
    max-width: 640px;
    margin: 0 auto;
    padding: 2rem 1.5rem;
    color: #e0e0e0;
}
.welcome-hero {
    text-align: center;
    margin-bottom: 2.5rem;
}
.welcome-hero h1 {
    font-size: 2rem;
    color: #ff6b00;
    margin-bottom: 0.5rem;
}
.welcome-hero p {
    color: #fff;
    font-size: 1rem;
    line-height: 1.6;
    max-width: 520px;
    margin: 0 auto;
}
.welcome-card {
    background: #1a1a2e;
    border: 1px solid #2a2a4a;
    border-radius: 14px;
    padding: 1.5rem;
    margin-bottom: 1.25rem;
}
.welcome-card h2 {
    font-size: 1.1rem;
    color: #ff6b00;
    margin: 0 0 1rem 0;
}
.welcome-step {
    display: flex;
    align-items: flex-start;
    gap: 0.75rem;
    margin-bottom: 1rem;
    padding-bottom: 1rem;
    border-bottom: 1px solid #2a2a3e;
}
.welcome-step:last-child {
    margin-bottom: 0;
    padding-bottom: 0;
    border-bottom: none;
}
.w-step-num {
    flex-shrink: 0;
    width: 28px;
    height: 28px;
    border-radius: 50%;
    background: #ff6b00;
    color: #000;
    font-weight: 700;
    font-size: 0.85rem;
    display: flex;
    align-items: center;
    justify-content: center;
}
.step-text h3 {
    font-size: 0.95rem;
    color: #fff;
    margin: 0 0 0.25rem 0;
}
.step-text p {
    font-size: 0.85rem;
    color: #fff;
    margin: 0;
    line-height: 1.4;
}
.feature-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
    margin-bottom: 1.25rem;
}
.feature-item {
    background: #1a1a2e;
    border: 1px solid #2a2a4a;
    border-radius: 12px;
    padding: 1.1rem;
    text-align: center;
}
.feature-item .feat-icon {
    font-size: 1.6rem;
    margin-bottom: 6px;
}
.feature-item h3 {
    font-size: 0.85rem;
    color: #fff;
    margin: 0 0 4px 0;
}
.feature-item p {
    font-size: 0.75rem;
    color: #fff;
    margin: 0;
    line-height: 1.3;
}
.tier-preview {
    background: #0d1b2a;
    border: 1px solid #1b3a5c;
    border-radius: 12px;
    padding: 1.25rem;
    margin-bottom: 1.25rem;
    font-size: 0.85rem;
    color: #8ab4f8;
    line-height: 1.5;
}
.tier-preview strong { color: #fff; }
.tier-preview .tier-row {
    display: flex;
    justify-content: space-between;
    padding: 6px 0;
    border-bottom: 1px solid rgba(138,180,248,0.15);
}
.tier-preview .tier-row:last-child { border-bottom: none; }
.tier-preview .tier-name { font-weight: 600; }
.welcome-actions {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    margin-top: 1.5rem;
}
.welcome-btn {
    display: block;
    width: 100%;
    padding: 0.9rem;
    border: none;
    border-radius: 10px;
    font-size: 1rem;
    font-weight: 600;
    cursor: pointer;
    text-align: center;
    text-decoration: none;
    transition: opacity 0.2s;
}
.welcome-btn:hover { opacity: 0.9; }
.welcome-btn.primary {
    background: linear-gradient(135deg, #ff6b00, #ff8c33);
    color: #000;
}
.welcome-btn.secondary {
    background: #2a2a3e;
    color: #fff;
    border: 1px solid #444;
}
@media (max-width: 480px) {
    .feature-grid { grid-template-columns: 1fr; }
}
</style>

<div class="welcome-container">
    <div class="welcome-hero">
        <h1>Welcome to Phoenix</h1>
        <p>You now have access to wholesale flight pricing across 195 markets. Phoenix finds price differences on the same flights across regions and passes the savings to you.</p>
    </div>

    <div class="welcome-card">
        <h2>How It Works</h2>
        <div class="welcome-step">
            <div class="w-step-num">1</div>
            <div class="step-text">
                <h3>Tell Phoenix Where You Want to Go</h3>
                <p>Open the AI chat and describe your trip. Phoenix searches wholesale pricing databases and compares rates across markets.</p>
            </div>
        </div>
        <div class="welcome-step">
            <div class="w-step-num">2</div>
            <div class="step-text">
                <h3>Phoenix Finds the Best Price</h3>
                <p>The same flight can cost 20-60% less depending on which market you book through. Phoenix checks them all and shows you the lowest.</p>
            </div>
        </div>
        <div class="welcome-step">
            <div class="w-step-num">3</div>
            <div class="step-text">
                <h3>Book &amp; Save</h3>
                <p>Pay with card or crypto. Phoenix only charges a fee when it finds savings &mdash; if there is no arbitrage, there is no fee.</p>
            </div>
        </div>
    </div>

    <div class="feature-grid">
        <div class="feature-item">
            <div class="feat-icon">&#x2708;</div>
            <h3>195 Markets</h3>
            <p>Every search checks pricing across global markets simultaneously</p>
        </div>
        <div class="feature-item">
            <div class="feat-icon">&#x1F4B0;</div>
            <h3>Wholesale Rates</h3>
            <p>Access the same GDS pricing travel agents use</p>
        </div>
        <div class="feature-item">
            <div class="feat-icon">&#x1F916;</div>
            <h3>AI-Powered</h3>
            <p>Conversational search &mdash; just describe your trip</p>
        </div>
        <div class="feature-item">
            <div class="feat-icon">&#x1F512;</div>
            <h3>Pay Your Way</h3>
            <p>Card, crypto, or RLUSD &mdash; your choice</p>
        </div>
    </div>

    <div class="tier-preview">
        <strong>Your Search Tier</strong>
        <p style="margin:8px 0 12px 0;">Your account tier determines how many markets Phoenix checks and how many searches you get per day.</p>
        <div class="tier-row">
            <span class="tier-name" style="color:#cd7f32;">Bronze</span>
            <span>10 searches / day &middot; 5 markets</span>
        </div>
        <div class="tier-row">
            <span class="tier-name" style="color:#c0c0c0;">Silver</span>
            <span>20 searches / day &middot; 8 markets</span>
        </div>
        <div class="tier-row">
            <span class="tier-name" style="color:#ffd700;">Gold</span>
            <span>40 searches / day &middot; 12 markets</span>
        </div>
        <div class="tier-row">
            <span class="tier-name" style="color:#e5e4e2;">Platinum</span>
            <span>Unlimited &middot; All markets</span>
        </div>
    </div>

    <div class="welcome-actions">
        <a href="/ai" class="welcome-btn primary">Start Searching</a>
        <button class="welcome-btn secondary" id="installBtn" onclick="installPhoenix()">
            Install App on This Device
        </button>
    </div>
</div>

<script>
(function() {
    var deferredPrompt = null;
    var installBtn = document.getElementById('installBtn');

    window.addEventListener('beforeinstallprompt', function(e) {
        e.preventDefault();
        deferredPrompt = e;
    });

    if (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches) {
        installBtn.textContent = 'App Installed';
        installBtn.style.opacity = '0.5';
        installBtn.disabled = true;
    }

    window.installPhoenix = function() {
        if (deferredPrompt) {
            deferredPrompt.prompt();
            deferredPrompt.userChoice.then(function(result) {
                if (result.outcome === 'accepted') {
                    installBtn.textContent = 'Installed\!';
                    setTimeout(function() { window.location.href = '/ai'; }, 1000);
                }
                deferredPrompt = null;
            });
        } else {
            var ua = navigator.userAgent || '';
            var msg = '';
            if (/iPhone|iPad|iPod/.test(ua)) {
test </b> end
                msg = 'Tap Share, then Add to Home Screen.';
            } else if (/Android/.test(ua)) {
                msg = 'Tap the menu, then Add to Home Screen or Install App.';
            } else {
                msg = 'Use your browser menu to install this site as an app.';
            }
            var el = document.createElement('p');
            el.style.cssText = 'text-align:center;color:#8ab4f8;font-size:0.85rem;margin-top:8px';
            el.innerHTML = msg;
            installBtn.parentNode.insertBefore(el, installBtn.nextSibling);
        }
    };

    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/service-worker.js').catch(function(){});
    }
})();
</script>
"""


@app.route("/install")
@login_required
def phoenix_install_page():
    """Welcome page shown after registration."""
    return render_template_string(
        BASE_TEMPLATE,
        title="Welcome to Phoenix",
        content=PHOENIX_INSTALL_CONTENT,
        current_user=current_user
    )


# --- Setup Guides ---

SETUP_GUIDES_CONTENT = """
<style>
.setup-hero { text-align: center; margin-bottom: 40px; }
.setup-hero h1 { font-size: 2.2em; margin-bottom: 10px; }
.setup-hero p { color: #fff; font-size: 1.1em; }
.tab-buttons { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 24px; border-bottom: 2px solid #333; padding-bottom: 12px; }
.tab-btn { background: transparent; border: 1px solid #444; color: #fff; padding: 10px 20px; border-radius: 8px 8px 0 0; cursor: pointer; font-size: 14px; transition: all 0.2s; }
.tab-btn:hover { background: #1a1a2e; color: #fff; }
.tab-btn.active { background: #ff6b00; border-color: #ff6b00; color: #fff; font-weight: 600; }
.tab-panel { display: none; }
.tab-panel.active { display: block; }
.guide-card { background: #1a1a2e; border: 1px solid #2a2a4a; border-radius: 12px; padding: 28px; margin-bottom: 20px; }
.guide-card h3 { color: #ff6b00; margin-top: 0; font-size: 1.3em; }
.step { display: flex; gap: 16px; margin-bottom: 20px; align-items: flex-start; }
.step-num { background: #ff6b00; color: #fff; width: 32px; height: 32px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: 700; flex-shrink: 0; }
.step-content { flex: 1; }
.step-content p { margin: 0 0 8px 0; color: #fff; }
.code-block { background: #0d0d1a; border: 1px solid #333; border-radius: 8px; padding: 14px 18px; font-family: monospace; font-size: 13px; color: #4fc3f7; overflow-x: auto; position: relative; margin: 8px 0; word-break: break-all; }
.copy-btn { position: absolute; top: 8px; right: 8px; background: #333; color: #fff; border: none; padding: 4px 10px; border-radius: 4px; cursor: pointer; font-size: 11px; }
.copy-btn:hover { background: #ff6b00; color: #fff; }
.token-box { background: #0d0d1a; border: 2px solid #ff6b00; border-radius: 8px; padding: 16px; margin: 16px 0; text-align: center; }
.token-box code { color: #4fc3f7; font-size: 14px; word-break: break-all; }
.token-box .label { color: #fff; font-size: 12px; margin-bottom: 6px; }
.note { background: #1a1a0d; border-left: 3px solid #ff6b00; padding: 12px 16px; margin: 12px 0; border-radius: 0 8px 8px 0; color: #fff; font-size: 13px; }
</style>

<div class="setup-hero">
    <h1>Get Started with Phoenix</h1>
    <p>Install Phoenix on your devices to join the distributed network and start earning.</p>
</div>

{% if helper_token %}
<div class="token-box">
    <div class="label">YOUR HELPER TOKEN</div>
    <code id="user-token">{{ helper_token }}</code>
    <br><br>
    <button class="copy-btn" onclick="navigator.clipboard.writeText(document.getElementById('user-token').textContent);this.textContent='Copied!'">Copy Token</button>
</div>
{% endif %}

<div class="tab-buttons">
    <button class="tab-btn active" onclick="showTab('desktop-mac')">Desktop (macOS/Linux)</button>
    <button class="tab-btn" onclick="showTab('desktop-win')">Desktop (Windows)</button>
    <button class="tab-btn" onclick="showTab('extension')">Chrome Extension</button>
    <button class="tab-btn" onclick="showTab('mobile')">Mobile Apps</button>
</div>

<div id="desktop-mac" class="tab-panel active">
    <div class="guide-card">
        <h3>Desktop Node — macOS &amp; Linux</h3>
        <p style="color:#aaa; margin-bottom: 24px;">Run a persistent background node on your computer. Earns rewards 24/7.</p>

        <div class="step">
            <div class="step-num">1</div>
            <div class="step-content">
                <p><strong>Get your Helper Token</strong></p>
                <p>Sign in to Phoenix, then go to your <a href="/helper" style="color:#4fc3f7;">Helper Dashboard</a> to find your token. Or copy it from the box above.</p>
            </div>
        </div>

        <div class="step">
            <div class="step-num">2</div>
            <div class="step-content">
                <p><strong>Make sure Python 3 is installed</strong></p>
                <div class="code-block">python3 --version<button class="copy-btn" onclick="navigator.clipboard.writeText('python3 --version');this.textContent='Copied!'">Copy</button></div>
                <p>If not installed: <a href="https://python.org/downloads" style="color:#4fc3f7;">python.org/downloads</a></p>
            </div>
        </div>

        <div class="step">
            <div class="step-num">3</div>
            <div class="step-content">
                <p><strong>Install the node service</strong></p>
                <div class="code-block">pip3 install aiohttp &amp;&amp; curl -sL https://phoenix-web-nj67.onrender.com/static/install-node.sh | bash -s -- --token YOUR_TOKEN --server https://phoenix-web-nj67.onrender.com<button class="copy-btn" onclick="navigator.clipboard.writeText('pip3 install aiohttp && curl -sL https://phoenix-web-nj67.onrender.com/static/install-node.sh | bash -s -- --token YOUR_TOKEN --server https://phoenix-web-nj67.onrender.com');">Copy</button></div>
                <p style="color:#888; font-size:13px;">Replace <code>YOUR_TOKEN</code> with the token from step 1.</p>
            </div>
        </div>

        <div class="step">
            <div class="step-num">4</div>
            <div class="step-content">
                <p><strong>Check status</strong></p>
                <div class="code-block">curl -s http://localhost:19750/status<button class="copy-btn" onclick="navigator.clipboard.writeText('curl -s http://localhost:19750/status');">Copy</button></div>
            </div>
        </div>

        <div class="note">The node runs as a background service (LaunchAgent on macOS, systemd on Linux). It starts automatically on login and restarts if it crashes.</div>
    </div>
</div>

<div id="desktop-win" class="tab-panel">
    <div class="guide-card">
        <h3>Desktop Node — Windows</h3>
        <p style="color:#aaa; margin-bottom: 24px;">Run a persistent background node via Windows Task Scheduler.</p>

        <div class="step">
            <div class="step-num">1</div>
            <div class="step-content">
                <p><strong>Get your Helper Token</strong></p>
                <p>Sign in to Phoenix, then go to your <a href="/helper" style="color:#4fc3f7;">Helper Dashboard</a>.</p>
            </div>
        </div>

        <div class="step">
            <div class="step-num">2</div>
            <div class="step-content">
                <p><strong>Install Python 3</strong></p>
                <p>Download from <a href="https://python.org/downloads" style="color:#4fc3f7;">python.org/downloads</a>. Check "Add to PATH" during install.</p>
            </div>
        </div>

        <div class="step">
            <div class="step-num">3</div>
            <div class="step-content">
                <p><strong>Open PowerShell as Administrator and run:</strong></p>
                <div class="code-block">pip install aiohttp; Invoke-WebRequest -Uri "https://phoenix-web-nj67.onrender.com/static/install-node.ps1" -OutFile install-node.ps1; .\\install-node.ps1 -Token YOUR_TOKEN -Server https://phoenix-web-nj67.onrender.com<button class="copy-btn" onclick="navigator.clipboard.writeText('pip install aiohttp; Invoke-WebRequest -Uri &quot;https://phoenix-web-nj67.onrender.com/static/install-node.ps1&quot; -OutFile install-node.ps1; .\\\\install-node.ps1 -Token YOUR_TOKEN -Server https://phoenix-web-nj67.onrender.com');">Copy</button></div>
            </div>
        </div>

        <div class="step">
            <div class="step-num">4</div>
            <div class="step-content">
                <p><strong>Check status</strong></p>
                <div class="code-block">.\\install-node.ps1 -Status<button class="copy-btn" onclick="navigator.clipboard.writeText('.\\\\install-node.ps1 -Status');">Copy</button></div>
            </div>
        </div>
    </div>
</div>

<div id="extension" class="tab-panel">
    <div class="guide-card">
        <h3>Chrome Extension</h3>
        <p style="color:#aaa; margin-bottom: 24px;">Earn rewards while browsing. The extension collects anonymous price and search data you choose to share.</p>

        <div class="step">
            <div class="step-num">1</div>
            <div class="step-content">
                <p><strong>Install the extension</strong></p>
                <p>Open Chrome and go to <code>chrome://extensions</code>. Enable "Developer mode" (top right toggle).</p>
            </div>
        </div>

        <div class="step">
            <div class="step-num">2</div>
            <div class="step-content">
                <p><strong>Load the extension</strong></p>
                <p>Click "Load unpacked" and select the <code>phoenix_extension</code> folder from the project directory.</p>
            </div>
        </div>

        <div class="step">
            <div class="step-num">3</div>
            <div class="step-content">
                <p><strong>Complete onboarding</strong></p>
                <p>The extension will open an onboarding page. Sign in with Google, Microsoft, or Apple — or paste your Helper Token manually.</p>
            </div>
        </div>

        <div class="step">
            <div class="step-num">4</div>
            <div class="step-content">
                <p><strong>Choose what to share</strong></p>
                <p>Select which data categories you want to share. Each category earns different reward points. You can change this anytime.</p>
            </div>
        </div>

        <div class="note">The extension badge shows "ON" when active, "D" for direct mode (no desktop node), and "OFF" when paused. Click the Phoenix icon to manage settings.</div>
    </div>
</div>

<div id="mobile" class="tab-panel">
    <div class="guide-card">
        <h3>Mobile Apps</h3>
        <p style="color:#aaa; margin-bottom: 24px;">Access Phoenix on your phone. Search flights, book deals, and run a background node.</p>

        <h4 style="color:#fff; margin-top:24px;">iPhone (iOS)</h4>
        <div class="step">
            <div class="step-num">1</div>
            <div class="step-content">
                <p>Open Safari and visit <a href="https://phoenix-web-nj67.onrender.com" style="color:#4fc3f7;">phoenix-web-nj67.onrender.com</a></p>
            </div>
        </div>
        <div class="step">
            <div class="step-num">2</div>
            <div class="step-content">
                <p>Tap the <strong>Share</strong> button, then <strong>"Add to Home Screen"</strong></p>
            </div>
        </div>
        <div class="step">
            <div class="step-num">3</div>
            <div class="step-content">
                <p>Open the Phoenix icon from your home screen — it runs as a full-screen PWA</p>
            </div>
        </div>

        <h4 style="color:#fff; margin-top:24px;">Android</h4>
        <div class="step">
            <div class="step-num">1</div>
            <div class="step-content">
                <p>Open Chrome and visit <a href="https://phoenix-web-nj67.onrender.com" style="color:#4fc3f7;">phoenix-web-nj67.onrender.com</a></p>
            </div>
        </div>
        <div class="step">
            <div class="step-num">2</div>
            <div class="step-content">
                <p>Tap the <strong>menu (three dots)</strong>, then <strong>"Add to Home Screen"</strong> or <strong>"Install App"</strong></p>
            </div>
        </div>
        <div class="step">
            <div class="step-num">3</div>
            <div class="step-content">
                <p>Open from your home screen — the app runs in standalone mode</p>
            </div>
        </div>

        <div class="note">The native Capacitor builds (installed on your devices) also work and will receive updates as you push new code.</div>
    </div>
</div>

<script>
function showTab(id) {
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.getElementById(id).classList.add('active');
    event.target.classList.add('active');
}
</script>
"""


@app.route("/setup")
def setup_guides():
    """Quick-start setup guides for Phoenix components."""
    helper_token = ""
    if current_user.is_authenticated:
        helper = HelperProfile.query.filter_by(user_id=current_user.id).first()
        if helper and helper.helper_token:
            helper_token = helper.helper_token
    return render_template_string(
        BASE_TEMPLATE,
        title="Setup Guides",
        content=render_template_string(
            SETUP_GUIDES_CONTENT,
            helper_token=helper_token,
            current_user=current_user,
        ),
        current_user=current_user,
    )


# --- AI Search API Routes ---

@app.route("/api/portal/ai/search", methods=["POST"])
@login_required
@limiter.limit("30/day")
def api_ai_search():
    """Ensemble AI search — queries multiple providers in parallel."""
    from ai_search import phoenix_ai
    data = request.get_json() or {}
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"error": "Query required"}), 400
    if len(query) > 2000:
        return jsonify({"error": "Query too long (max 2000 chars)"}), 400

    market = data.get("market")
    providers = data.get("providers")  # optional list of provider keys

    result = phoenix_ai.search(
        user_id=current_user.id,
        query=query,
        market=market,
        providers=providers,
    )
    if result.get("error"):
        return jsonify(result), 400
    return jsonify(result)


@app.route("/api/portal/ai/providers")
@login_required
def api_ai_providers():
    """List available AI providers (platform + user's custom)."""
    from ai_search import phoenix_ai, AI_PROVIDERS
    platform = phoenix_ai.get_platform_providers()
    user_provs = phoenix_ai.get_user_providers(current_user.id)

    providers = {}
    for key, info in AI_PROVIDERS.items():
        providers[key] = {
            "name": info["name"],
            "strengths": info.get("strengths", ""),
            "available": key in platform or key in user_provs,
            "source": "user" if key in user_provs else ("platform" if key in platform else None),
        }
    return jsonify({"providers": providers})


@app.route("/api/portal/ai/providers", methods=["POST"])
@login_required
def api_ai_add_provider():
    """User adds custom API key for an AI provider."""
    from ai_search import phoenix_ai
    data = request.get_json() or {}
    provider = data.get("provider", "").strip()
    api_key = data.get("api_key")
    model = data.get("model")

    if not provider:
        return jsonify({"error": "Provider required"}), 400

    result = phoenix_ai.add_user_provider(
        user_id=current_user.id,
        provider_key=provider,
        api_key=api_key,
        custom_model=model,
    )
    if isinstance(result, dict) and result.get("error"):
        return jsonify(result), 400
    return jsonify({"ok": True, "provider": result})


@app.route("/api/portal/ai/providers/<provider>", methods=["DELETE"])
@login_required
def api_ai_remove_provider(provider):
    """User removes their custom API key for a provider."""
    from ai_search import phoenix_ai
    success = phoenix_ai.remove_user_provider(current_user.id, provider)
    if not success:
        return jsonify({"error": "Provider not found"}), 404
    return jsonify({"ok": True})


@app.route("/api/portal/ai/history")
@login_required
def api_ai_history():
    """User's AI search query history."""
    from models import AISearchQuery
    queries = AISearchQuery.query.filter_by(
        user_id=current_user.id
    ).order_by(AISearchQuery.created_at.desc()).limit(50).all()
    return jsonify({"queries": [q.to_dict() for q in queries]})


@app.route("/api/portal/ai/credits")
@login_required
def api_ai_credits():
    """User's AI credit balance and free query count."""
    from ai_search import phoenix_ai, FREE_QUERIES_PER_DAY
    from models import AISearchQuery
    balance = phoenix_ai.get_user_credits(current_user.id)
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_count = AISearchQuery.query.filter(
        AISearchQuery.user_id == current_user.id,
        AISearchQuery.created_at >= today_start,
    ).count()
    return jsonify({
        "balance": balance,
        "free_remaining": max(0, FREE_QUERIES_PER_DAY - today_count),
        "cost_per_query": 0.001,
    })


# --- Intelligence API Routes (Portal) ---

@app.route("/api/intelligence/route/<origin>/<destination>")
@login_required
def api_intelligence_route(origin, destination):
    """Route intelligence profile: multi-market pricing, trends, demand."""
    try:
        from phoenix_intelligence import intelligence
        data = intelligence.get_route_intelligence(
            origin.upper(), destination.upper(),
            days_back=int(request.args.get("days", 30)),
        )
        return jsonify(data)
    except Exception as e:
        logger.error(f"Route intelligence error: {e}")
        return jsonify({"error": "Intelligence unavailable"}), 500


@app.route("/api/intelligence/market/<market>")
@login_required
def api_intelligence_market(market):
    """Market briefing: popular routes, savings, volatility."""
    try:
        from phoenix_intelligence import intelligence
        data = intelligence.get_market_briefing(
            market.upper(),
            days_back=int(request.args.get("days", 7)),
        )
        return jsonify(data)
    except Exception as e:
        logger.error(f"Market intelligence error: {e}")
        return jsonify({"error": "Intelligence unavailable"}), 500


@app.route("/api/intelligence/trending")
@login_required
def api_intelligence_trending():
    """Trending routes and detected anomalies."""
    try:
        from phoenix_intelligence import intelligence
        anomalies = intelligence.detect_anomalies(
            days=int(request.args.get("days", 7)),
        )
        stats = intelligence.get_platform_stats()
        return jsonify({"anomalies": anomalies, "platform": stats})
    except Exception as e:
        logger.error(f"Trending intelligence error: {e}")
        return jsonify({"error": "Intelligence unavailable"}), 500


@app.route("/api/intelligence/platform")
@login_required
def api_intelligence_platform():
    """Platform-wide stats: searches, routes, markets, savings."""
    try:
        from phoenix_intelligence import intelligence
        data = intelligence.get_platform_stats()
        provider_perf = intelligence.get_provider_performance(
            days_back=int(request.args.get("days", 30)),
        )
        data["ai_providers"] = provider_perf
        return jsonify(data)
    except Exception as e:
        logger.error(f"Platform intelligence error: {e}")
        return jsonify({"error": "Intelligence unavailable"}), 500


# --- Phase 2 Intelligence Routes ---

@app.route("/api/intelligence/p2p/network")
@login_required
def api_intelligence_p2p_network():
    """P2P network health: helpers, transactions, disputes."""
    try:
        from phoenix_intelligence import intelligence
        days = int(request.args.get("days", 30))
        data = intelligence.get_p2p_network(days_back=days)
        return jsonify(data)
    except Exception as e:
        logger.error(f"P2P network intelligence error: {e}")
        return jsonify({"error": "Intelligence unavailable"}), 500


@app.route("/api/intelligence/p2p/savings")
@login_required
def api_intelligence_p2p_savings():
    """Top P2P savings routes."""
    try:
        from phoenix_intelligence import intelligence
        days = int(request.args.get("days", 30))
        limit = int(request.args.get("limit", 10))
        data = intelligence.get_p2p_savings(days_back=days, limit=limit)
        return jsonify(data)
    except Exception as e:
        logger.error(f"P2P savings intelligence error: {e}")
        return jsonify({"error": "Intelligence unavailable"}), 500


@app.route("/api/intelligence/nodes")
@login_required
def api_intelligence_nodes():
    """CitizenSERP node network stats."""
    try:
        from phoenix_intelligence import intelligence
        data = intelligence.get_node_network()
        return jsonify(data)
    except Exception as e:
        logger.error(f"Node network intelligence error: {e}")
        return jsonify({"error": "Intelligence unavailable"}), 500


@app.route("/api/intelligence/proxy")
@login_required
def api_intelligence_proxy():
    """Proxy portal usage stats."""
    try:
        from phoenix_intelligence import intelligence
        days = int(request.args.get("days", 7))
        data = intelligence.get_proxy_usage(days_back=days)
        return jsonify(data)
    except Exception as e:
        logger.error(f"Proxy intelligence error: {e}")
        return jsonify({"error": "Intelligence unavailable"}), 500


@app.route("/api/intelligence/ai")
@login_required
def api_intelligence_ai():
    """AI provider analytics and query trends."""
    try:
        from phoenix_intelligence import intelligence
        days = int(request.args.get("days", 30))
        data = intelligence.get_ai_analytics(days_back=days)
        return jsonify(data)
    except Exception as e:
        logger.error(f"AI analytics intelligence error: {e}")
        return jsonify({"error": "Intelligence unavailable"}), 500


@app.route("/api/intelligence/alerts")
@login_required
def api_intelligence_alerts():
    """Price alert demand signals."""
    try:
        from phoenix_intelligence import intelligence
        limit = int(request.args.get("limit", 20))
        data = intelligence.get_alert_demand(limit=limit)
        return jsonify(data)
    except Exception as e:
        logger.error(f"Alert demand intelligence error: {e}")
        return jsonify({"error": "Intelligence unavailable"}), 500


@app.route("/api/intelligence/deals")
@login_required
def api_intelligence_deals():
    """Private market deal analytics."""
    try:
        from phoenix_intelligence import intelligence
        days = int(request.args.get("days", 30))
        data = intelligence.get_private_market_stats(days_back=days)
        return jsonify(data)
    except Exception as e:
        logger.error(f"Deal intelligence error: {e}")
        return jsonify({"error": "Intelligence unavailable"}), 500


@app.route("/api/intelligence/payments")
@login_required
def api_intelligence_payments():
    """Payment method distribution and revenue."""
    try:
        from phoenix_intelligence import intelligence
        days = int(request.args.get("days", 30))
        data = intelligence.get_payment_analytics(days_back=days)
        return jsonify(data)
    except Exception as e:
        logger.error(f"Payment intelligence error: {e}")
        return jsonify({"error": "Intelligence unavailable"}), 500


@app.route("/api/intelligence/price-history/<origin>/<dest>")
@login_required
def api_intelligence_price_history(origin, dest):
    """Day-by-day price timeline for a route."""
    try:
        from phoenix_intelligence import intelligence
        days = int(request.args.get("days", 30))
        data = intelligence.get_price_timeline(origin.upper(), dest.upper(), days_back=days)
        return jsonify(data)
    except Exception as e:
        logger.error(f"Price history intelligence error: {e}")
        return jsonify({"error": "Intelligence unavailable"}), 500


@app.route("/api/intelligence/airlines/<origin>/<dest>")
@login_required
def api_intelligence_airlines(origin, dest):
    """Airline competitive pricing for a route."""
    try:
        from phoenix_intelligence import intelligence
        days = int(request.args.get("days", 7))
        data = intelligence.get_airline_comparison(origin.upper(), dest.upper(), days_back=days)
        return jsonify(data)
    except Exception as e:
        logger.error(f"Airline intelligence error: {e}")
        return jsonify({"error": "Intelligence unavailable"}), 500


# --- PhoenixAI Agent API Routes ---

@app.route("/api/agent/search", methods=["POST"])
@login_required
def api_agent_search():
    """Agent-orchestrated search — PhoenixAI decides markets + strategy."""
    try:
        from phoenix_agent import phoenix_agent
        data = request.get_json() or {}
        query = data.get("query", "")
        if not query:
            return jsonify({"error": "query is required"}), 400

        task_type = data.get("task_type", "flight_search")
        user_market = data.get("market", "US")

        result = phoenix_agent.handle_search(
            query=query,
            user_id=current_user.id,
            task_type=task_type,
            user_market=user_market,
            params=data.get("params", {}),
        )
        return jsonify(result)
    except Exception as e:
        logger.error(f"Agent search error: {e}")
        return jsonify({"error": "Agent search unavailable"}), 500


@app.route("/api/agent/analyze/<origin>/<destination>")
@login_required
def api_agent_analyze_route(origin, destination):
    """Deep route analysis by PhoenixAI."""
    try:
        from phoenix_agent import phoenix_agent
        user_market = request.args.get("market", "US")
        result = phoenix_agent.analyze_route(
            origin.upper(), destination.upper(), user_market=user_market
        )
        return jsonify(result)
    except Exception as e:
        logger.error(f"Agent analyze error: {e}")
        return jsonify({"error": "Agent analysis unavailable"}), 500


@app.route("/api/agent/discover")
@login_required
def api_agent_discover():
    """PhoenixAI opportunity discovery."""
    try:
        from phoenix_agent import phoenix_agent
        force = request.args.get("force", "false").lower() == "true"
        result = phoenix_agent.discover_opportunities(force=force)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Agent discovery error: {e}")
        return jsonify({"error": "Agent discovery unavailable"}), 500


@app.route("/api/agent/markets", methods=["POST"])
@login_required
def api_agent_select_markets():
    """Agent market selection for a search."""
    try:
        from phoenix_agent import phoenix_agent
        data = request.get_json() or {}
        origin = data.get("origin", "")
        destination = data.get("destination", "")
        task_type = data.get("task_type", "flight_search")
        user_market = data.get("market", "US")
        max_markets = int(data.get("max_markets", 8))

        markets = phoenix_agent.market_selector.select_markets(
            origin=origin.upper() if origin else None,
            destination=destination.upper() if destination else None,
            task_type=task_type,
            max_markets=max_markets,
            user_market=user_market,
        )
        return jsonify({"markets": markets, "count": len(markets)})
    except Exception as e:
        logger.error(f"Agent market selection error: {e}")
        return jsonify({"error": "Market selection unavailable"}), 500


@app.route("/api/agent/status")
@login_required
def api_agent_status():
    """PhoenixAI agent operational status."""
    try:
        from phoenix_agent import phoenix_agent
        return jsonify(phoenix_agent.get_agent_status())
    except Exception as e:
        logger.error(f"Agent status error: {e}")
        return jsonify({"error": "Agent status unavailable"}), 500


# --- Geographic Zone API Routes ---

@app.route("/api/zones")
@login_required
def api_zones_list():
    """List all geographic zones with node coverage counts."""
    try:
        from geographic_zones import get_zone_summary
        summary = get_zone_summary()
        try:
            from citizenserp_payouts import citizenserp_manager
            stats = citizenserp_manager.get_network_stats()
            summary["nodes_by_zone"] = stats.get("nodes_by_zone", {})
            summary["nodes_by_country"] = stats.get("nodes_by_country", {})
        except Exception:
            summary["nodes_by_zone"] = {}
            summary["nodes_by_country"] = {}
        return jsonify(summary)
    except Exception as e:
        logger.error(f"Zones list error: {e}")
        return jsonify({"error": "Zone data unavailable"}), 500


@app.route("/api/zones/<country>")
@login_required
def api_zones_for_country(country):
    """List zones for a specific country with node counts."""
    try:
        from geographic_zones import get_zones_for_country
        zones = get_zones_for_country(country.upper())
        if not zones:
            return jsonify({"error": f"No zones defined for {country.upper()}"}), 404
        node_counts = {}
        try:
            from citizenserp_payouts import citizenserp_manager
            stats = citizenserp_manager.get_network_stats()
            node_counts = stats.get("nodes_by_zone", {})
        except Exception:
            pass
        return jsonify({
            "country": country.upper(),
            "zones": [
                {
                    "zone_code": z.zone_code,
                    "name": z.name,
                    "cities": z.cities,
                    "timezone": z.timezone,
                    "population_tier": z.population_tier,
                    "nodes_online": node_counts.get(z.zone_code, 0),
                }
                for z in zones
            ],
            "total_zones": len(zones),
        })
    except Exception as e:
        logger.error(f"Country zones error: {e}")
        return jsonify({"error": "Zone data unavailable"}), 500


# --- CitizenSERP Task API Routes ---

@app.route("/api/tasks/types")
@login_required
def api_task_types():
    """List all registered CitizenSERP task types."""
    try:
        from citizenserp_tasks import task_registry
        return jsonify({"task_types": task_registry.list_types()})
    except Exception as e:
        logger.error(f"Task types error: {e}")
        return jsonify({"error": "Task types unavailable"}), 500


@app.route("/api/tasks/dispatch", methods=["POST"])
@login_required
def api_task_dispatch():
    """Dispatch a CitizenSERP task to a node."""
    try:
        from citizenserp_tasks import task_registry, task_dispatcher
        data = request.get_json() or {}
        task_type = data.get("task_type", "")
        market = data.get("market", "")
        params = data.get("params", {})

        if not task_type or not market:
            return jsonify({"error": "task_type and market are required"}), 400

        task = task_registry.create_task(
            task_type=task_type,
            params=params,
            market=market,
            requester_user_id=current_user.id,
            requester_type="portal",
        )
        task_id = task_dispatcher.dispatch(task)
        if task_id:
            return jsonify({"task_id": task_id, "status": "dispatched", "market": market})
        else:
            return jsonify({"error": f"No nodes available in market {market}"}), 503
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"Task dispatch error: {e}")
        return jsonify({"error": "Task dispatch unavailable"}), 500


@app.route("/api/tasks/<task_id>")
@login_required
def api_task_status(task_id):
    """Get status of a dispatched task."""
    try:
        from citizenserp_tasks import task_dispatcher
        task = task_dispatcher.get_task(task_id)
        if not task:
            return jsonify({"error": "Task not found"}), 404
        return jsonify(task)
    except Exception as e:
        logger.error(f"Task status error: {e}")
        return jsonify({"error": "Task status unavailable"}), 500


@app.route("/api/tasks/active")
@login_required
def api_tasks_active():
    """List active CitizenSERP tasks."""
    try:
        from citizenserp_tasks import task_dispatcher
        market = request.args.get("market")
        task_type = request.args.get("type")
        tasks = task_dispatcher.get_active_tasks(market=market, task_type=task_type)
        return jsonify({"tasks": tasks, "count": len(tasks)})
    except Exception as e:
        logger.error(f"Active tasks error: {e}")
        return jsonify({"error": "Task list unavailable"}), 500


@app.route("/api/tasks/stats")
@login_required
def api_tasks_stats():
    """CitizenSERP task dispatcher statistics."""
    try:
        from citizenserp_tasks import task_dispatcher
        return jsonify(task_dispatcher.get_stats())
    except Exception as e:
        logger.error(f"Task stats error: {e}")
        return jsonify({"error": "Task stats unavailable"}), 500


# --- Private Market Deal API Routes ---

@app.route("/api/portal/deal/create", methods=["POST"])
@login_required
def api_deal_create():
    """Create a private market deal draft with AI assessment."""
    from ai_search import phoenix_ai
    data = request.get_json() or {}

    required = ["item_description", "agreed_price"]
    for field in required:
        if not data.get(field):
            return jsonify({"error": f"{field} is required"}), 400

    try:
        price = float(data["agreed_price"])
        if price <= 0:
            return jsonify({"error": "Price must be positive"}), 400
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid price"}), 400

    # Build contract terms via AI
    contract = phoenix_ai.build_deal_contract(current_user.id, data)

    # Create deal record
    deal = phoenix_ai.create_private_deal(current_user.id, data, contract)

    return jsonify({"deal": deal.to_dict(), "contract": contract})


@app.route("/api/portal/deal/<int:deal_id>/fund", methods=["POST"])
@login_required
def api_deal_fund(deal_id):
    """Fund XRPL escrow for a private market deal."""
    from ai_search import phoenix_ai
    result = phoenix_ai.fund_deal_escrow(deal_id, current_user.id)
    if result.get("error"):
        return jsonify(result), 400
    return jsonify(result)


@app.route("/api/portal/deal/<int:deal_id>/confirm-delivery", methods=["POST"])
@login_required
def api_deal_confirm(deal_id):
    """Buyer confirms delivery — releases escrow."""
    from ai_search import phoenix_ai
    result = phoenix_ai.confirm_delivery(deal_id, current_user.id)
    if result.get("error"):
        return jsonify(result), 400
    return jsonify(result)


@app.route("/api/portal/deal/<int:deal_id>/dispute", methods=["POST"])
@login_required
def api_deal_dispute(deal_id):
    """Open dispute on a funded deal — escrow holds."""
    from ai_search import phoenix_ai
    data = request.get_json() or {}
    result = phoenix_ai.dispute_deal(deal_id, current_user.id, reason=data.get("reason", ""))
    if result.get("error"):
        return jsonify(result), 400
    try:
        from event_stream import emit_dispute_event
        emit_dispute_event(current_user.id, None, "dispute_opened", {
            "deal_id": deal_id,
            "reason": data.get("reason", ""),
        })
    except Exception:
        pass
    return jsonify(result)


@app.route("/api/portal/deals")
@login_required
def api_deal_list():
    """List user's private market deals."""
    from models import PrivateMarketDeal
    deals = PrivateMarketDeal.query.filter_by(
        buyer_id=current_user.id
    ).order_by(PrivateMarketDeal.created_at.desc()).limit(50).all()
    return jsonify({"deals": [d.to_dict() for d in deals]})


@app.route("/api/portal/deal/<int:deal_id>")
@login_required
def api_deal_detail(deal_id):
    """Get deal detail with escrow status."""
    from models import PrivateMarketDeal
    deal = PrivateMarketDeal.query.filter_by(
        id=deal_id, buyer_id=current_user.id
    ).first()
    if not deal:
        return jsonify({"error": "Deal not found"}), 404
    return jsonify({"deal": deal.to_dict()})


# --- Private P2P Deal Link Routes ---

@app.route("/api/portal/deal/<int:deal_id>/generate-link", methods=["POST"])
@login_required
def api_deal_generate_link(deal_id):
    """Generate a shareable link for a deal. Buyer sends this to the seller."""
    from ai_search import phoenix_ai
    data = request.get_json() or {}

    expiration_days = int(data.get("expiration_days", 7))
    if expiration_days < 1 or expiration_days > 30:
        return jsonify({"error": "Expiration must be between 1 and 30 days"}), 400

    result = phoenix_ai.generate_deal_link(deal_id, current_user.id, expiration_days)
    if result.get("error"):
        return jsonify(result), 400
    return jsonify(result)


@app.route("/api/portal/deal/<int:deal_id>/send-link", methods=["POST"])
@login_required
def api_deal_send_link(deal_id):
    """Send deal link to seller via email."""
    from ai_search import phoenix_ai
    result = phoenix_ai.send_deal_link_email(deal_id, current_user.id)
    if result.get("error"):
        return jsonify(result), 400
    return jsonify(result)


@app.route("/api/portal/deal/<int:deal_id>/link-status")
@login_required
def api_deal_link_status(deal_id):
    """Check deal link status — viewed, accepted, expired."""
    from models import PrivateMarketDeal
    deal = PrivateMarketDeal.query.filter_by(
        id=deal_id, buyer_id=current_user.id
    ).first()
    if not deal:
        return jsonify({"error": "Deal not found"}), 404
    return jsonify({
        "deal_id": deal.id,
        "link_token": deal.link_token,
        "link_url": f"/deal/link/{deal.link_token}" if deal.link_token else None,
        "link_expires_at": deal.link_expires_at.isoformat() if deal.link_expires_at else None,
        "is_expired": (deal.link_expires_at < datetime.utcnow()) if deal.link_expires_at else False,
        "link_viewed_at": deal.link_viewed_at.isoformat() if deal.link_viewed_at else None,
        "seller_accepted_at": deal.seller_accepted_at.isoformat() if deal.seller_accepted_at else None,
        "seller_wallet": deal.seller_wallet,
        "status": deal.status,
    })


# --- Public Deal Link Routes (NO AUTH — seller-facing) ---

# Simple rate limiter for public endpoints
_deal_link_rate = {}

def _check_rate_limit(key, max_requests=3, window=60):
    """Return True if request is allowed, False if rate-limited."""
    import time as _time
    now = _time.time()
    if key not in _deal_link_rate:
        _deal_link_rate[key] = []
    _deal_link_rate[key] = [t for t in _deal_link_rate[key] if now - t < window]
    if len(_deal_link_rate[key]) >= max_requests:
        return False
    _deal_link_rate[key].append(now)
    return True


@app.route("/deal/link/<link_token>")
def public_deal_link_view(link_token):
    """PUBLIC: Seller views deal terms via shareable link. No auth required."""
    from ai_search import phoenix_ai

    phoenix_ai.mark_deal_link_viewed(link_token)
    result = phoenix_ai.get_deal_by_link_token(link_token)

    if result.get("error"):
        return f"""<!DOCTYPE html>
<html><head><title>Deal Link — PHOENIX</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{{font-family:-apple-system,sans-serif;background:#f5f7fa;padding:40px}}
.c{{max-width:600px;margin:0 auto;background:#fff;border-radius:12px;padding:40px;box-shadow:0 2px 8px rgba(0,0,0,.1)}}
.e{{color:#d32f2f}}</style></head>
<body><div class="c"><h1 style="color:#4361ee">PHOENIX</h1>
<p class="e">{result['error']}</p></div></body></html>""", 404

    d = result["deal"]
    already_accepted = d["status"] == "seller_accepted"

    accept_form = ""
    if not already_accepted:
        accept_form = f"""
        <div style="background:#fff3cd;border:1px solid #ffeaa7;padding:20px;border-radius:8px;margin:20px 0">
            <h4 style="margin-top:0;color:#856404">How PHOENIX Escrow Works</h4>
            <ol style="padding-left:20px;color:#856404">
                <li>You provide your XRPL wallet address below</li>
                <li>The buyer creates an on-chain escrow with the funds</li>
                <li>You can verify the locked funds on the XRPL ledger</li>
                <li>Complete the transaction (deliver the item/service)</li>
                <li>Buyer confirms delivery</li>
                <li>Escrow releases payment to your wallet automatically</li>
            </ol>
            <p style="margin-bottom:0;color:#856404;font-weight:bold">
                Phoenix takes a fee but is NOT liable for physical goods execution.
                This is a peer-to-peer escrow service.</p>
        </div>
        <form id="af">
            <div style="margin:20px 0"><label style="display:block;margin-bottom:8px;font-weight:600">
                Your XRPL Wallet Address *</label>
                <input type="text" id="wallet" placeholder="r..."
                    style="width:100%;padding:12px;border:2px solid #e0e0e0;border-radius:8px;font-size:16px;box-sizing:border-box" required>
                <small style="color:#666">Must start with 'r' (25-35 characters)</small>
            </div>
            <div style="margin:20px 0"><label style="display:block;margin-bottom:8px;font-weight:600">
                Your Name (Optional)</label>
                <input type="text" id="sname" placeholder="Your name"
                    style="width:100%;padding:12px;border:2px solid #e0e0e0;border-radius:8px;font-size:16px;box-sizing:border-box">
            </div>
            <div id="msg"></div>
            <button type="submit" style="background:#4361ee;color:#fff;padding:15px 40px;border:none;
                border-radius:8px;font-size:18px;font-weight:bold;cursor:pointer;width:100%;margin-top:10px">
                Accept Deal &amp; Provide Wallet</button>
        </form>
        <script>
        document.getElementById('af').addEventListener('submit',async e=>{{
            e.preventDefault();
            const btn=e.target.querySelector('button'),msg=document.getElementById('msg');
            btn.disabled=true;btn.textContent='Submitting...';msg.innerHTML='';
            try{{
                const res=await fetch('/deal/link/{link_token}/accept',{{
                    method:'POST',headers:{{'Content-Type':'application/json'}},
                    body:JSON.stringify({{seller_wallet:document.getElementById('wallet').value,
                        seller_name:document.getElementById('sname').value}})
                }});
                const data=await res.json();
                if(data.ok){{
                    msg.innerHTML='<div style="color:#2e7d32;padding:10px;background:#e8f5e9;border-radius:8px;margin-bottom:20px"><strong>Deal accepted!</strong> The buyer will now fund the escrow.</div>'+
                    '<div style="background:#f0f4ff;padding:25px;border-radius:12px;border-left:4px solid #4361ee">'+
                    '<h3 style="margin-top:0;color:#1a1a2e">Create a PHOENIX Account</h3>'+
                    '<p style="color:#666">Track this deal and future transactions. Your wallet is already linked.</p>'+
                    '<div style="margin:15px 0"><label style="display:block;margin-bottom:5px;font-weight:600">Email *</label>'+
                    '<input type="email" id="su_email" style="width:100%;padding:10px;border:2px solid #e0e0e0;border-radius:8px;font-size:15px;box-sizing:border-box" required></div>'+
                    '<div style="margin:15px 0"><label style="display:block;margin-bottom:5px;font-weight:600">Password *</label>'+
                    '<input type="password" id="su_pass" minlength="8" style="width:100%;padding:10px;border:2px solid #e0e0e0;border-radius:8px;font-size:15px;box-sizing:border-box" required></div>'+
                    '<div id="su_msg"></div>'+
                    '<button onclick="doSignup()" style="background:#4361ee;color:#fff;padding:12px 30px;border:none;border-radius:8px;font-size:16px;font-weight:bold;cursor:pointer;width:100%;margin-top:10px">Create Account</button>'+
                    '<p style="color:#999;font-size:12px;margin-top:10px;text-align:center">Optional — you can skip this step</p></div>';
                    e.target.style.display='none';
                }}else{{
                    msg.innerHTML='<div style="color:#d32f2f;padding:10px;background:#ffebee;border-radius:8px"><strong>Error:</strong> '+(data.error||'Failed')+'</div>';
                    btn.disabled=false;btn.textContent='Accept Deal & Provide Wallet';
                }}
            }}catch(err){{
                msg.innerHTML='<div style="color:#d32f2f;padding:10px;background:#ffebee;border-radius:8px">Network error. Please try again.</div>';
                btn.disabled=false;btn.textContent='Accept Deal & Provide Wallet';
            }}
        }});
        async function doSignup(){{
            const em=document.getElementById('su_email').value;
            const pw=document.getElementById('su_pass').value;
            const sm=document.getElementById('su_msg');
            if(!em||!pw){{sm.innerHTML='<div style="color:#d32f2f;padding:8px;background:#ffebee;border-radius:6px">Email and password required</div>';return;}}
            if(pw.length<8){{sm.innerHTML='<div style="color:#d32f2f;padding:8px;background:#ffebee;border-radius:6px">Password must be 8+ characters</div>';return;}}
            try{{
                const r=await fetch('/deal/link/{link_token}/signup',{{
                    method:'POST',headers:{{'Content-Type':'application/json'}},
                    body:JSON.stringify({{email:em,password:pw,name:document.getElementById('sname')?.value||''}})
                }});
                const d=await r.json();
                if(d.ok){{sm.innerHTML='<div style="color:#2e7d32;padding:10px;background:#e8f5e9;border-radius:8px"><strong>Account created!</strong> You can now <a href="/login" style="color:#4361ee;font-weight:bold">log in</a> to track your deal.</div>';}}
                else{{sm.innerHTML='<div style="color:#d32f2f;padding:8px;background:#ffebee;border-radius:6px">'+(d.error||'Failed')+'</div>';}}
            }}catch(e){{sm.innerHTML='<div style="color:#d32f2f;padding:8px;background:#ffebee;border-radius:6px">Network error</div>';}}
        }}
        </script>"""
    else:
        accept_form = f"""
        <div style="background:#d4edda;border:1px solid #c3e6cb;padding:20px;border-radius:8px;text-align:center;margin:20px 0">
            <h3 style="color:#155724;margin:0">Deal Accepted</h3>
            <p>You accepted this deal on {d['seller_accepted_at'] or 'N/A'}.</p>
            <p>Waiting for the buyer to fund the escrow...</p>
        </div>"""

    return f"""<!DOCTYPE html>
<html><head><title>Deal Proposal — PHOENIX</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,sans-serif;
    background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);padding:20px;margin:0}}
.c{{max-width:700px;margin:40px auto;background:#fff;border-radius:16px;padding:40px;
    box-shadow:0 10px 30px rgba(0,0,0,.2)}}
</style></head>
<body><div class="c">
    <div style="color:#4361ee;font-size:28px;font-weight:bold;margin-bottom:30px">PHOENIX</div>
    <h1>Deal Proposal</h1>
    <p>You've received a secure escrow deal proposal from <strong>{d['buyer_name']}</strong>.</p>

    <div style="background:#f0f4ff;padding:25px;border-radius:12px;margin:20px 0;border-left:4px solid #4361ee">
        <h3 style="margin-top:0;color:#1a1a2e">Item Description</h3>
        <p>{d['item_description']}</p>
        <p><strong>Market:</strong> {d['market'] or 'N/A'}</p>
        <p><strong>Type:</strong> {d['deal_type']}</p>
        <p><strong>Delivery Deadline:</strong> {d['delivery_deadline_days'] or 'N/A'} days from escrow funding</p>
    </div>

    <div style="font-size:32px;font-weight:bold;color:#2e7d32;margin:20px 0">
        {d['total_rlusd']:.2f} RLUSD</div>
    <p style="color:#666;font-size:14px">
        Price: {d['agreed_price_rlusd']:.2f} RLUSD + Platform Fee: {d['escrow_fee_rlusd']:.2f} RLUSD</p>

    {accept_form}

    <p style="color:#999;font-size:12px;margin-top:40px;text-align:center">
        Link expires: {d['link_expires_at'] or 'N/A'}</p>
</div></body></html>"""


@app.route("/deal/link/<link_token>/accept", methods=["POST"])
def public_deal_link_accept(link_token):
    """PUBLIC: Seller accepts deal and provides XRPL wallet. No auth. Rate-limited."""
    if not _check_rate_limit(request.remote_addr, max_requests=3, window=60):
        return jsonify({"error": "Rate limit exceeded. Please wait and try again."}), 429

    from ai_search import phoenix_ai

    data = request.get_json() or {}
    seller_wallet = (data.get("seller_wallet") or "").strip()
    seller_name = (data.get("seller_name") or "").strip()

    if not seller_wallet:
        return jsonify({"error": "Wallet address is required"}), 400

    result = phoenix_ai.accept_deal_link(link_token, seller_wallet, seller_name)
    if result.get("error"):
        return jsonify(result), 400
    return jsonify(result)


@app.route("/deal/link/<link_token>/signup", methods=["POST"])
def public_deal_link_signup(link_token):
    """PUBLIC: Seller creates a PHOENIX account from the deal acceptance page.

    Onboards the seller with their wallet pre-linked. The deal brought them here.
    """
    if not _check_rate_limit(f"signup:{request.remote_addr}", max_requests=3, window=300):
        return jsonify({"error": "Rate limit exceeded. Please wait."}), 429

    from models import PrivateMarketDeal, User, UserWallet, db as appdb

    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password", "")
    name = (data.get("name") or "").strip()

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400

    deal = PrivateMarketDeal.query.filter_by(link_token=link_token).first()
    if not deal:
        return jsonify({"error": "Deal not found"}), 404

    # Check if email already registered
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "Email already registered. Please log in instead."}), 409

    try:
        user = User(
            email=email,
            name=name or deal.seller_name or "",
            is_verified=True,
            onboarded_from_deal_id=deal.id,
        )
        user.set_password(password)
        appdb.session.add(user)
        appdb.session.flush()

        # Link seller's wallet as primary
        if deal.seller_wallet:
            wallet = UserWallet(
                user_id=user.id,
                wallet_address=deal.seller_wallet,
                wallet_type="xrpl",
                is_primary=True,
                is_verified=True,
                label="XRPL Wallet (from deal)",
            )
            appdb.session.add(wallet)

        appdb.session.commit()

        logger.info(f"Seller onboarded from deal {deal.id}: user {user.id} ({email})")
        return jsonify({
            "ok": True,
            "message": "Account created! You can now log in to track your deal.",
            "user_id": user.id,
        })

    except Exception as e:
        appdb.session.rollback()
        logger.error(f"Seller signup failed: {e}")
        return jsonify({"error": "Account creation failed. Please try again."}), 500


# --- Share Links & Contract Templates API ---

@app.route("/api/portal/deal/<int:deal_id>/share-links")
@login_required
def api_deal_share_links(deal_id):
    """Get multi-platform share links for a deal."""
    from models import PrivateMarketDeal
    from share_links import generate_deal_share_links

    deal = PrivateMarketDeal.query.filter_by(
        id=deal_id, buyer_id=current_user.id
    ).first()
    if not deal:
        return jsonify({"error": "Deal not found"}), 404
    if not deal.link_token:
        return jsonify({"error": "No link generated for this deal yet"}), 400

    base_url = os.environ.get("BASE_URL", "http://localhost:5001")
    share = generate_deal_share_links(deal.to_dict(), base_url)

    return jsonify({
        "deal_id": deal.id,
        "link_url": f"/deal/link/{deal.link_token}",
        "full_url": f"{base_url}/deal/link/{deal.link_token}",
        "share_links": share,
    })


@app.route("/api/referral/share-links")
@login_required
def api_referral_share_links():
    """Get multi-platform share links for the user's referral code."""
    from share_links import generate_referral_share_links

    # Check if user has a commercial account with a referral code
    ref_code = None
    user_name = current_user.name or current_user.email

    if hasattr(current_user, 'referral_code_used') and current_user.referral_code_used:
        ref_code = current_user.referral_code_used

    # Try commercial account referral code
    if not ref_code:
        try:
            from models import CommercialAccount
            account = CommercialAccount.query.filter_by(
                owner_user_id=current_user.id
            ).first()
            if account and account.referral_code:
                ref_code = account.referral_code
        except Exception:
            pass

    # Generate a personal referral code if none exists
    if not ref_code:
        ref_code = f"PHOENIX_{current_user.id}"

    base_url = os.environ.get("BASE_URL", "http://localhost:5001")
    share = generate_referral_share_links(ref_code, user_name, base_url)

    return jsonify({
        "referral_code": ref_code,
        "referral_url": f"{base_url}/join/{ref_code}",
        "share_links": share,
    })


@app.route("/api/share/platforms")
def api_share_platforms():
    """List all supported share platforms (no auth required)."""
    from share_links import get_platform_list
    return jsonify({"platforms": get_platform_list()})


@app.route("/api/contracts/templates")
def api_contract_templates():
    """List all available smart contract templates (no auth required)."""
    from share_links import get_contract_templates
    return jsonify({"templates": get_contract_templates()})


@app.route("/api/contracts/templates/<template_id>")
def api_contract_template_detail(template_id):
    """Get a specific contract template."""
    from share_links import get_template
    template = get_template(template_id)
    if not template:
        return jsonify({"error": "Template not found"}), 404
    return jsonify({"template": template})


# --- WALLET & CARD ONBOARDING ---

WALLET_CONTENT = """
<div style="max-width: 800px; margin: 40px auto;">
    <div class="card card-light" style="padding: 30px;">
        <h1 style="color: #1a1a2e; margin-bottom: 5px;">Wallet & Payments</h1>
        <p style="color: #666; margin-bottom: 30px;">Manage your XRPL wallets and payment cards</p>

        <!-- XRPL Wallets Section -->
        <div style="margin-bottom: 30px;">
            <h2 style="color: #1a1a2e; margin-bottom: 15px; font-size: 20px;">XRPL Wallets</h2>
            <p style="color: #666; font-size: 14px; margin-bottom: 15px;">
                Connect your XRPL wallet to deposit RLUSD for escrow and receive earnings.
            </p>

            <div id="wallets-list">
                {% if wallets %}
                    {% for w in wallets %}
                    <div style="display: flex; justify-content: space-between; align-items: center; padding: 15px; background: #f8f9fa; border-radius: 8px; margin-bottom: 10px;">
                        <div>
                            <strong style="color: #1a1a2e;">{{ w.wallet_label }}</strong>
                            {% if w.is_primary %}<span style="background: #ff6b35; color: white; padding: 2px 8px; border-radius: 10px; font-size: 11px; margin-left: 8px;">Primary</span>{% endif %}
                            <br><code style="font-size: 13px; color: #666;">{{ w.wallet_address }}</code>
                            {% if w.is_verified %}
                                <span style="color: #2e7d32; font-size: 12px; margin-left: 8px;">Verified</span>
                            {% else %}
                                <span style="color: #e65100; font-size: 12px; margin-left: 8px;">Unverified</span>
                            {% endif %}
                        </div>
                        <form method="POST" action="/wallet/remove" style="margin: 0;">
                            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                            <input type="hidden" name="wallet_id" value="{{ w.id }}">
                            <button type="submit" style="background: none; border: none; color: #c62828; cursor: pointer; font-size: 13px;">Remove</button>
                        </form>
                    </div>
                    {% endfor %}
                {% else %}
                    <p style="color: #fff; font-style: italic;">No wallets connected yet.</p>
                {% endif %}
            </div>

            <form method="POST" action="/wallet/add" style="margin-top: 15px;">
                <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                <div style="display: flex; gap: 10px;">
                    <input type="text" name="wallet_address" placeholder="rXXXXXXXXXXXXXXXXXXXXX..." required
                           style="flex: 1; padding: 10px 14px; border: 1px solid #ddd; border-radius: 8px; font-family: monospace;">
                    <input type="text" name="wallet_label" placeholder="Label (optional)" value="Primary"
                           style="width: 150px; padding: 10px 14px; border: 1px solid #ddd; border-radius: 8px;">
                    <button type="submit" class="btn" style="padding: 10px 20px;">Add Wallet</button>
                </div>
            </form>
        </div>

        <hr style="border: none; border-top: 1px solid #eee; margin: 25px 0;">

        <!-- Payment Cards Section -->
        <div style="margin-bottom: 30px;">
            <h2 style="color: #1a1a2e; margin-bottom: 15px; font-size: 20px;">Payment Cards</h2>
            <p style="color: #666; font-size: 14px; margin-bottom: 15px;">
                Add a card to front ticket purchases as a helper. Card details are tokenized — we never store full card numbers.
            </p>

            <div id="cards-list">
                {% if cards %}
                    {% for c in cards %}
                    <div style="display: flex; justify-content: space-between; align-items: center; padding: 15px; background: #f8f9fa; border-radius: 8px; margin-bottom: 10px;">
                        <div>
                            <strong style="color: #1a1a2e;">{{ c.card_label }}</strong>
                            {% if c.is_primary %}<span style="background: #ff6b35; color: white; padding: 2px 8px; border-radius: 10px; font-size: 11px; margin-left: 8px;">Primary</span>{% endif %}
                            <br><span style="color: #666; font-size: 14px;">{{ c.card_brand | upper }} ending in {{ c.card_last_four }} &mdash; expires {{ c.card_exp_month }}/{{ c.card_exp_year }}</span>
                        </div>
                        <form method="POST" action="/card/remove" style="margin: 0;">
                            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                            <input type="hidden" name="card_id" value="{{ c.id }}">
                            <button type="submit" style="background: none; border: none; color: #c62828; cursor: pointer; font-size: 13px;">Remove</button>
                        </form>
                    </div>
                    {% endfor %}
                {% else %}
                    <p style="color: #fff; font-style: italic;">No cards added yet.</p>
                {% endif %}
            </div>

            <form method="POST" action="/card/add" style="margin-top: 15px;">
                <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
                    <input type="text" name="card_label" placeholder="Card label" value="Primary Card"
                           style="padding: 10px 14px; border: 1px solid #ddd; border-radius: 8px;">
                    <input type="text" name="card_last_four" placeholder="Last 4 digits" maxlength="4" required
                           style="padding: 10px 14px; border: 1px solid #ddd; border-radius: 8px;">
                    <select name="card_brand" style="padding: 10px 14px; border: 1px solid #ddd; border-radius: 8px;">
                        <option value="visa">Visa</option>
                        <option value="mastercard">Mastercard</option>
                        <option value="amex">American Express</option>
                        <option value="discover">Discover</option>
                    </select>
                    <div style="display: flex; gap: 10px;">
                        <input type="number" name="card_exp_month" placeholder="MM" min="1" max="12" required
                               style="flex: 1; padding: 10px 14px; border: 1px solid #ddd; border-radius: 8px;">
                        <input type="number" name="card_exp_year" placeholder="YYYY" min="2025" max="2040" required
                               style="flex: 1; padding: 10px 14px; border: 1px solid #ddd; border-radius: 8px;">
                    </div>
                    <input type="text" name="billing_name" placeholder="Name on card" required
                           style="padding: 10px 14px; border: 1px solid #ddd; border-radius: 8px;">
                    <input type="text" name="billing_country" placeholder="Country code (US, UK, ES...)" maxlength="2" required
                           style="padding: 10px 14px; border: 1px solid #ddd; border-radius: 8px;">
                </div>
                <button type="submit" class="btn" style="margin-top: 10px; padding: 10px 20px;">Add Card</button>
            </form>
        </div>

        <hr style="border: none; border-top: 1px solid #eee; margin: 25px 0;">

        <!-- Zone Availability (Build #86) -->
        <div style="margin-bottom: 30px;">
            <h2 style="color: #1a1a2e; margin-bottom: 5px; font-size: 20px;">Your Arbitrage & Shopping Reach</h2>
            <p style="color: #666; font-size: 14px; margin-bottom: 15px;">
                Markets accessible with your current payment setup. Add cards or verify your wallet to expand coverage.
            </p>
            <div id="zone-availability" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px;">
                <p style="color: #fff; font-style: italic;">Loading zone availability...</p>
            </div>
            <p id="zone-crypto-note" style="display: none; color: #2e7d32; font-size: 13px; margin-top: 12px;">
                With a verified XRPL wallet, you get universal access via Phoenix virtual card to ALL zones.
            </p>
        </div>

        <hr style="border: none; border-top: 1px solid #eee; margin: 25px 0;">

        <!-- Payment Ramp Networks (Build #86) -->
        <div style="margin-bottom: 30px;">
            <h2 style="color: #1a1a2e; margin-bottom: 5px; font-size: 20px;">Buy USDC / XRP</h2>
            <p style="color: #666; font-size: 14px; margin-bottom: 15px;">
                On-ramp to crypto through verified providers. Funds go to your connected XRPL wallet.
                Or bring your own payment method &mdash; Phoenix doesn't require you to use these.
            </p>
            <div id="ramp-providers" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px;">
                <p style="color: #fff; font-style: italic;">Loading ramp providers...</p>
            </div>

            <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
            <details>
                <summary style="color: #666; cursor: pointer; font-size: 14px;">Other exchanges (manual transfer)</summary>
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-top: 12px;">
                    <a href="https://www.coinbase.com" target="_blank" rel="noopener" style="text-decoration: none;">
                        <div style="background: #f8f9fa; padding: 14px; border-radius: 10px; text-align: center;">
                            <strong style="color: #1a1a2e; font-size: 14px;">Coinbase</strong>
                            <p style="color: #666; font-size: 11px; margin-top: 4px;">US, EU, UK</p>
                        </div>
                    </a>
                    <a href="https://www.binance.com" target="_blank" rel="noopener" style="text-decoration: none;">
                        <div style="background: #f8f9fa; padding: 14px; border-radius: 10px; text-align: center;">
                            <strong style="color: #1a1a2e; font-size: 14px;">Binance</strong>
                            <p style="color: #666; font-size: 11px; margin-top: 4px;">Global</p>
                        </div>
                    </a>
                    <a href="https://www.kraken.com" target="_blank" rel="noopener" style="text-decoration: none;">
                        <div style="background: #f8f9fa; padding: 14px; border-radius: 10px; text-align: center;">
                            <strong style="color: #1a1a2e; font-size: 14px;">Kraken</strong>
                            <p style="color: #666; font-size: 11px; margin-top: 4px;">US, EU</p>
                        </div>
                    </a>
                    <a href="https://uphold.com" target="_blank" rel="noopener" style="text-decoration: none;">
                        <div style="background: #f8f9fa; padding: 14px; border-radius: 10px; text-align: center;">
                            <strong style="color: #1a1a2e; font-size: 14px;">Uphold</strong>
                            <p style="color: #666; font-size: 11px; margin-top: 4px;">XRP Direct</p>
                        </div>
                    </a>
                    <a href="https://www.bitstamp.net" target="_blank" rel="noopener" style="text-decoration: none;">
                        <div style="background: #f8f9fa; padding: 14px; border-radius: 10px; text-align: center;">
                            <strong style="color: #1a1a2e; font-size: 14px;">Bitstamp</strong>
                            <p style="color: #666; font-size: 11px; margin-top: 4px;">EU, Global</p>
                        </div>
                    </a>
                    <a href="https://crypto.com" target="_blank" rel="noopener" style="text-decoration: none;">
                        <div style="background: #f8f9fa; padding: 14px; border-radius: 10px; text-align: center;">
                            <strong style="color: #1a1a2e; font-size: 14px;">Crypto.com</strong>
                            <p style="color: #666; font-size: 11px; margin-top: 4px;">Global</p>
                        </div>
                    </a>
                </div>
                <p style="color: #fff; font-size: 12px; margin-top: 10px;">
                    Purchase XRP or RLUSD on any exchange, then send to your connected XRPL wallet address above.
                </p>
            </details>
        </div>

        <!-- Virtual Card Pipeline (Build #86) -->
        {% if has_verified_wallet %}
        <hr style="border: none; border-top: 1px solid #eee; margin: 25px 0;">
        <div>
            <h2 style="color: #1a1a2e; margin-bottom: 5px; font-size: 20px;">Virtual Card Pipeline</h2>
            <p style="color: #666; font-size: 14px; margin-bottom: 15px;">
                Phoenix can convert your crypto to a virtual Visa card for any merchant purchase &mdash; arbitrage deals or free browsing.
            </p>
            <div style="display: flex; gap: 0; align-items: center; flex-wrap: wrap;">
                <div style="flex:1; min-width:100px; text-align:center; padding:14px 8px; background:#e3f2fd; border-radius:8px 0 0 8px;">
                    <strong style="font-size:13px; color:#1565c0;">XRP / RLUSD</strong><br>
                    <span style="font-size:11px; color:#666;">Your wallet</span>
                </div>
                <div style="padding:0 6px; color:#999; font-size:18px;">&#8594;</div>
                <div style="flex:1; min-width:100px; text-align:center; padding:14px 8px; background:#fff3e0;">
                    <strong style="font-size:13px; color:#e65100;">USDC</strong><br>
                    <span style="font-size:11px; color:#666;">Settlement</span>
                </div>
                <div style="padding:0 6px; color:#999; font-size:18px;">&#8594;</div>
                <div style="flex:1; min-width:100px; text-align:center; padding:14px 8px; background:#e8f5e9;">
                    <strong style="font-size:13px; color:#2e7d32;">Virtual Visa</strong><br>
                    <span style="font-size:11px; color:#666;">Stripe Issuing</span>
                </div>
                <div style="padding:0 6px; color:#999; font-size:18px;">&#8594;</div>
                <div style="flex:1; min-width:100px; text-align:center; padding:14px 8px; background:#f3e5f5; border-radius:0 8px 8px 0;">
                    <strong style="font-size:13px; color:#7b1fa2;">Any Vendor</strong><br>
                    <span style="font-size:11px; color:#666;">All markets</span>
                </div>
            </div>
            <p style="color: #fff; font-size: 12px; margin-top: 12px;">
                Est. total cost: ~0.5-1% (crypto to USDC) + card network fees. Unlocks ALL markets worldwide.
            </p>
        </div>
        {% endif %}
    </div>
</div>

<script>
document.addEventListener('DOMContentLoaded', function() {
    // Zone availability
    fetch('/api/payment/zone-availability')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data.success) return;
            var container = document.getElementById('zone-availability');
            container.innerHTML = '';
            var hasVirtualCard = false;
            data.zones.forEach(function(zone) {
                var color = zone.status === 'full' ? '#2e7d32' :
                            zone.status === 'partial' ? '#ff6b35' : '#c62828';
                var hasCrypto = zone.methods.some(function(m) { return m === 'virtual_card' || m === 'xrp' || m === 'rlusd'; });
                if (hasCrypto) hasVirtualCard = true;
                var fxLabel = hasCrypto ? '~' + zone.fx_estimate.crypto_spread_pct + '%' : '~' + zone.fx_estimate.card_spread_pct + '%';
                container.innerHTML +=
                    '<div style="background:#f8f9fa;padding:18px;border-radius:10px;border-left:4px solid ' + color + ';">' +
                        '<strong style="color:#1a1a2e;">' + zone.group_name + '</strong>' +
                        '<p style="font-size:13px;color:#666;margin:4px 0 8px;">' + zone.reachable_countries + '/' + zone.total_countries + ' countries</p>' +
                        '<div style="background:#e0e0e0;height:6px;border-radius:3px;">' +
                            '<div style="background:' + color + ';height:100%;width:' + zone.coverage_pct + '%;border-radius:3px;"></div>' +
                        '</div>' +
                        '<p style="font-size:12px;color:#999;margin-top:8px;">Est. FX: ' + fxLabel + '</p>' +
                    '</div>';
            });
            if (hasVirtualCard) {
                var note = document.getElementById('zone-crypto-note');
                if (note) note.style.display = 'block';
            }
        })
        .catch(function() {
            var c = document.getElementById('zone-availability');
            if (c) c.innerHTML = '<p style="color:#999;">Unable to load zone data.</p>';
        });

    // Ramp providers
    fetch('/api/payment/ramps')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data.success) return;
            var container = document.getElementById('ramp-providers');
            container.innerHTML = '';
            data.ramps.forEach(function(ramp) {
                var badge = '';
                if (ramp.is_best_for_country) badge = '<span style="background:#2e7d32;color:white;padding:2px 8px;border-radius:10px;font-size:10px;margin-left:6px;">Best for you</span>';
                if (ramp.is_user_default) badge = '<span style="background:#ff6b35;color:white;padding:2px 8px;border-radius:10px;font-size:10px;margin-left:6px;">Default</span>';
                var feeLabel = ramp.fee_estimate_pct === 0 ? 'Zero fee' : '~' + ramp.fee_estimate_pct + '% fee';
                var cryptos = (ramp.supported_crypto_out || ['USDC']).join(', ');
                container.innerHTML +=
                    '<div style="background:#f8f9fa;padding:18px;border-radius:10px;">' +
                        '<div style="display:flex;align-items:center;flex-wrap:wrap;">' +
                            '<strong style="color:#1a1a2e;font-size:15px;">' + ramp.provider_name + '</strong>' + badge +
                        '</div>' +
                        '<p style="color:#666;font-size:12px;margin:4px 0 8px;">' + (ramp.description || '') + '</p>' +
                        '<p style="color:#999;font-size:11px;margin-bottom:10px;">' + feeLabel + ' &middot; ' + (ramp.fiat_methods_summary || '') + '</p>' +
                        '<a href="/api/payment/ramps/' + ramp.provider_code + '/widget-url?crypto=USDC" target="_blank" ' +
                            'style="display:block;text-align:center;padding:8px;background:#ff6b35;color:white;border-radius:6px;text-decoration:none;font-size:13px;font-weight:600;">' +
                            'Buy ' + cryptos +
                        '</a>' +
                    '</div>';
            });
        })
        .catch(function() {
            var c = document.getElementById('ramp-providers');
            if (c) c.innerHTML = '<p style="color:#999;">Unable to load ramp providers.</p>';
        });
});
</script>
"""


@app.route("/wallet")
@login_required
def wallet_page():
    """Wallet and card management page."""
    wallets = UserWallet.query.filter_by(user_id=current_user.id).all()
    cards = UserCard.query.filter_by(user_id=current_user.id, is_active=True).all()
    has_verified_wallet = (
        any(w.is_verified for w in wallets)
        or bool(getattr(current_user, 'xrpl_wallet_address', None))
    )
    return render_template_string(
        BASE_TEMPLATE,
        title="Wallet & Payments",
        content=render_template_string(
            WALLET_CONTENT,
            current_user=current_user,
            wallets=[w.to_dict() | {'id': w.id} for w in wallets],
            cards=[c.to_dict() | {'id': c.id} for c in cards],
            has_verified_wallet=has_verified_wallet,
        ),
        current_user=current_user,
    )


@app.route("/wallet/add", methods=["POST"])
@login_required
def wallet_add():
    """Add an XRPL wallet."""
    address = request.form.get("wallet_address", "").strip()
    label = request.form.get("wallet_label", "Primary").strip()

    if not address or not address.startswith("r") or len(address) < 25:
        flash("Invalid XRPL wallet address.", "error")
        return redirect(url_for("wallet_page"))

    existing = UserWallet.query.filter_by(user_id=current_user.id, wallet_address=address).first()
    if existing:
        flash("This wallet is already connected.", "warning")
        return redirect(url_for("wallet_page"))

    # If this is the first wallet, make it primary
    has_wallets = UserWallet.query.filter_by(user_id=current_user.id).count() > 0

    wallet = UserWallet(
        user_id=current_user.id,
        wallet_address=address,
        wallet_label=label,
        is_primary=not has_wallets,
    )
    db.session.add(wallet)

    # Also update the legacy xrp_wallet_address on User if no primary set
    if not has_wallets:
        current_user.xrp_wallet_address = address

    db.session.commit()
    flash(f"Wallet added: {address[:8]}...{address[-4:]}", "success")
    return redirect(url_for("wallet_page"))


@app.route("/wallet/remove", methods=["POST"])
@login_required
def wallet_remove():
    """Remove an XRPL wallet."""
    wallet_id = request.form.get("wallet_id", type=int)
    wallet = UserWallet.query.filter_by(id=wallet_id, user_id=current_user.id).first()
    if wallet:
        db.session.delete(wallet)
        db.session.commit()
        flash("Wallet removed.", "success")
    return redirect(url_for("wallet_page"))


@app.route("/card/add", methods=["POST"])
@login_required
def card_add():
    """Add a payment card (last 4 digits only — no full card storage)."""
    last_four = request.form.get("card_last_four", "").strip()
    if not last_four or len(last_four) != 4 or not last_four.isdigit():
        flash("Please enter the last 4 digits of your card.", "error")
        return redirect(url_for("wallet_page"))

    has_cards = UserCard.query.filter_by(user_id=current_user.id, is_active=True).count() > 0

    card = UserCard(
        user_id=current_user.id,
        card_label=request.form.get("card_label", "Primary Card").strip(),
        card_last_four=last_four,
        card_brand=request.form.get("card_brand", "visa"),
        card_exp_month=request.form.get("card_exp_month", type=int),
        card_exp_year=request.form.get("card_exp_year", type=int),
        billing_name=request.form.get("billing_name", "").strip(),
        billing_country=request.form.get("billing_country", "US").strip().upper(),
        is_primary=not has_cards,
    )
    db.session.add(card)
    db.session.commit()
    flash(f"Card added: ****{last_four}", "success")
    return redirect(url_for("wallet_page"))


@app.route("/card/remove", methods=["POST"])
@login_required
def card_remove():
    """Remove a payment card."""
    card_id = request.form.get("card_id", type=int)
    card = UserCard.query.filter_by(id=card_id, user_id=current_user.id).first()
    if card:
        card.is_active = False
        db.session.commit()
        flash("Card removed.", "success")
    return redirect(url_for("wallet_page"))


# --- HELPER DASHBOARD ---

HELPER_DASHBOARD_CONTENT = """
<style>
    .helper-page { max-width: 960px; margin: 40px auto; }
    .helper-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 25px; flex-wrap: wrap; gap: 10px; }
    .helper-status { padding: 6px 16px; border-radius: 20px; font-size: 14px; font-weight: 600; color: white; }
    .helper-status.active { background: #2e7d32; }
    .helper-status.inactive { background: #666; }
    .helper-status.pending { background: #e65100; }
    .helper-stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin-bottom: 25px; }
    .helper-stat { background: #f8f9fa; padding: 20px 15px; border-radius: 10px; text-align: center; }
    .helper-stat-value { font-size: 26px; font-weight: bold; }
    .helper-stat-label { color: #666; font-size: 12px; margin-top: 4px; text-transform: uppercase; letter-spacing: 0.5px; }
    .helper-section { margin-bottom: 25px; }
    .helper-section-title { color: #1a1a2e; font-size: 16px; font-weight: 700; margin-bottom: 12px; letter-spacing: 0.5px; text-transform: uppercase; }
    .earnings-chart { background: #f8f9fa; border-radius: 10px; padding: 20px; margin-bottom: 20px; }
    .chart-bars { display: flex; align-items: flex-end; gap: 4px; height: 120px; padding-top: 10px; }
    .chart-bar-wrapper { flex: 1; display: flex; flex-direction: column; align-items: center; height: 100%; justify-content: flex-end; }
    .chart-bar { width: 100%; min-width: 20px; max-width: 40px; background: linear-gradient(180deg, #ff6b35, #ff8c00); border-radius: 4px 4px 0 0; transition: height 0.3s ease; position: relative; }
    .chart-bar:hover { opacity: 0.85; }
    .chart-bar-label { font-size: 10px; color: #fff; margin-top: 6px; }
    .chart-bar-value { font-size: 9px; color: #666; position: absolute; top: -16px; left: 50%; transform: translateX(-50%); white-space: nowrap; }
    .earnings-summary { display: flex; gap: 20px; flex-wrap: wrap; margin-top: 12px; }
    .earnings-period { padding: 10px 16px; background: white; border: 1px solid #eee; border-radius: 8px; }
    .earnings-period strong { display: block; color: #ff6b35; font-size: 18px; }
    .earnings-period span { color: #666; font-size: 12px; }
    .toggle-row { display: flex; justify-content: space-between; align-items: center; padding: 15px; background: #f8f9fa; border-radius: 10px; margin-bottom: 12px; }
    .toggle-row .label strong { color: #1a1a2e; }
    .toggle-row .label p { color: #666; font-size: 13px; margin: 0; }
    .avail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    .avail-field label { display: block; color: #555; font-size: 12px; margin-bottom: 4px; text-transform: uppercase; }
    .avail-field select, .avail-field input { padding: 8px 12px; border: 1px solid #ddd; border-radius: 8px; width: 100%; font-size: 14px; }
    .tx-item { display: flex; justify-content: space-between; align-items: center; padding: 12px 15px; border-bottom: 1px solid #eee; }
    .tx-item:last-child { border-bottom: none; }
    .tx-route { color: #1a1a2e; font-weight: 600; }
    .tx-airline { color: #666; font-size: 13px; margin-left: 8px; }
    .tx-date { color: #fff; font-size: 12px; }
    .tx-earning { color: #2e7d32; font-weight: bold; }
    .tx-badge { font-size: 11px; padding: 2px 8px; border-radius: 10px; font-weight: 500; }
    .tx-badge.completed { background: #e8f5e9; color: #2e7d32; }
    .tx-badge.failed, .tx-badge.cancelled { background: #fef2f2; color: #c62828; }
    .tx-badge.in-progress { background: #fff3e0; color: #e65100; }
    .success-rate-bar { height: 8px; background: #eee; border-radius: 4px; overflow: hidden; margin-top: 8px; }
    .success-rate-fill { height: 100%; background: linear-gradient(90deg, #2e7d32, #4caf50); border-radius: 4px; }
    .quick-links { display: flex; gap: 10px; margin-top: 25px; flex-wrap: wrap; }
    @media (max-width: 768px) {
        .helper-stats { grid-template-columns: repeat(2, 1fr); }
        .avail-grid { grid-template-columns: 1fr; }
        .tx-item { flex-direction: column; align-items: flex-start; gap: 8px; }
    }
</style>

<div class="helper-page">
    <div class="card card-light" style="padding: 30px;">
        <div class="helper-header">
            <div>
                <h1 style="color: #1a1a2e; margin-bottom: 5px;">Helper Dashboard</h1>
                <p style="color: #666;">Manage your P2P earning profile</p>
            </div>
            {% if helper and helper.is_approved and helper.is_active %}
                <span class="helper-status active">Active</span>
            {% elif helper and not helper.is_approved %}
                <span class="helper-status pending">Pending Approval</span>
            {% else %}
                <span class="helper-status inactive">Inactive</span>
            {% endif %}
        </div>

        {% if not helper %}
        <!-- Sign up as helper -->
        <div style="text-align: center; padding: 40px 20px; background: #f8f9fa; border-radius: 12px;">
            <h2 style="color: #1a1a2e; margin-bottom: 10px;">Become a Phoenix Helper</h2>
            <p style="color: #666; margin-bottom: 20px; max-width: 500px; margin-left: auto; margin-right: auto;">
                Earn RLUSD by allowing Phoenix to use your browser session for flight bookings in your market.
                You earn 5% of every ticket price booked through you.
            </p>
            <form method="POST" action="/helper/activate">
                <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                <div style="display: flex; gap: 10px; justify-content: center; margin-bottom: 15px; flex-wrap: wrap;">
                    <select name="country_code" required style="padding: 10px 14px; border: 1px solid #ddd; border-radius: 8px; min-width: 200px;">
                        <option value="">Select your country...</option>
                        <option value="US">United States</option>
                        <option value="GB">United Kingdom</option>
                        <option value="ES">Spain</option>
                        <option value="DE">Germany</option>
                        <option value="FR">France</option>
                        <option value="IT">Italy</option>
                        <option value="NL">Netherlands</option>
                        <option value="PL">Poland</option>
                        <option value="JP">Japan</option>
                        <option value="KR">South Korea</option>
                        <option value="AU">Australia</option>
                        <option value="IN">India</option>
                        <option value="SG">Singapore</option>
                        <option value="BR">Brazil</option>
                        <option value="MX">Mexico</option>
                        <option value="CA">Canada</option>
                        <option value="AE">UAE</option>
                        <option value="ZA">South Africa</option>
                        <option value="TH">Thailand</option>
                        <option value="TR">Turkey</option>
                        <option value="CO">Colombia</option>
                        <option value="PH">Philippines</option>
                        <option value="NG">Nigeria</option>
                        <option value="IE">Ireland</option>
                    </select>
                    <input type="text" name="city" placeholder="Your city (optional)" style="padding: 10px 14px; border: 1px solid #ddd; border-radius: 8px;">
                </div>
                <button type="submit" class="btn btn-primary" style="padding: 12px 30px; font-size: 16px;">Activate Helper Profile</button>
            </form>
        </div>

        {% else %}
        <!-- Stats Grid -->
        <div class="helper-stats">
            <div class="helper-stat">
                <div class="helper-stat-value" style="color: #ff6b35;">{{ helper.total_earned_rlusd | round(2) }}</div>
                <div class="helper-stat-label">RLUSD Earned</div>
            </div>
            <div class="helper-stat">
                <div class="helper-stat-value" style="color: #1a1a2e;">{{ helper.successful_transactions }}</div>
                <div class="helper-stat-label">Completed</div>
            </div>
            <div class="helper-stat">
                <div class="helper-stat-value" style="color: #2e7d32;">{{ helper.average_rating | round(1) }}</div>
                <div class="helper-stat-label">Rating</div>
            </div>
            <div class="helper-stat">
                <div class="helper-stat-value" style="color: #1565c0;">{{ helper.country_code }}</div>
                <div class="helper-stat-label">Market</div>
            </div>
            <div class="helper-stat">
                <div class="helper-stat-value" style="color: #333;">
                    {% if helper.total_transactions > 0 %}
                        {{ ((helper.successful_transactions / helper.total_transactions) * 100) | round(0) }}%
                    {% else %}
                        --
                    {% endif %}
                </div>
                <div class="helper-stat-label">Success Rate</div>
                {% if helper.total_transactions > 0 %}
                <div class="success-rate-bar">
                    <div class="success-rate-fill" style="width: {{ ((helper.successful_transactions / helper.total_transactions) * 100) | round(0) }}%;"></div>
                </div>
                {% endif %}
            </div>
            <div class="helper-stat">
                <div class="helper-stat-value" style="color: #666;">{{ helper.transactions_today }}</div>
                <div class="helper-stat-label">Today</div>
            </div>
        </div>

        <!-- Earnings Chart -->
        <div class="helper-section">
            <div class="helper-section-title">Earnings Overview</div>
            <div class="earnings-chart">
                <div class="chart-bars" id="earningsChart">
                    {% for day in earnings_by_day %}
                    <div class="chart-bar-wrapper">
                        <div class="chart-bar" style="height: {{ day.height }}%;">
                            {% if day.amount > 0 %}<span class="chart-bar-value">{{ day.amount | round(0) }}</span>{% endif %}
                        </div>
                        <span class="chart-bar-label">{{ day.label }}</span>
                    </div>
                    {% endfor %}
                </div>
                <div class="earnings-summary">
                    <div class="earnings-period">
                        <strong>{{ earnings_7d | round(2) }} RLUSD</strong>
                        <span>Last 7 Days</span>
                    </div>
                    <div class="earnings-period">
                        <strong>{{ earnings_30d | round(2) }} RLUSD</strong>
                        <span>Last 30 Days</span>
                    </div>
                    <div class="earnings-period">
                        <strong>{{ helper.total_earned_rlusd | round(2) }} RLUSD</strong>
                        <span>All Time</span>
                    </div>
                </div>
            </div>
        </div>

        <!-- Status Controls -->
        <div class="helper-section">
            <div class="helper-section-title">Status</div>
            <div class="toggle-row">
                <div class="label">
                    <strong>Accepting Requests</strong>
                    <p>When active, Phoenix may use your browser session for bookings.</p>
                </div>
                <form method="POST" action="/helper/toggle">
                    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                    {% if helper.is_active %}
                        <button type="submit" class="btn" style="background: #c62828; color: white; padding: 8px 20px; border: none; border-radius: 8px; cursor: pointer;">Pause</button>
                    {% else %}
                        <button type="submit" class="btn btn-primary" style="padding: 8px 20px;">Activate</button>
                    {% endif %}
                </form>
            </div>

            {% if not helper.is_approved %}
            <div style="background: #fff3e0; border: 1px solid #ffe0b2; padding: 15px; border-radius: 10px; margin-bottom: 12px;">
                <strong style="color: #e65100;">Pending Admin Approval</strong>
                <p style="color: #bf360c; font-size: 13px; margin: 4px 0 0;">Your helper profile is under review. You'll be notified when approved.</p>
            </div>
            {% endif %}
        </div>

        <!-- Availability Settings -->
        <div class="helper-section">
            <div class="helper-section-title">Availability</div>
            <form method="POST" action="/helper/availability" style="background: #f8f9fa; padding: 20px; border-radius: 10px;">
                <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                <div class="avail-grid">
                    <div class="avail-field">
                        <label>Available From</label>
                        <select name="available_hours_start">
                            {% for h in range(24) %}
                            <option value="{{ h }}" {% if helper.available_hours_start == h %}selected{% endif %}>{{ '%02d:00' % h }}</option>
                            {% endfor %}
                        </select>
                    </div>
                    <div class="avail-field">
                        <label>Available Until</label>
                        <select name="available_hours_end">
                            {% for h in range(1, 25) %}
                            <option value="{{ h }}" {% if helper.available_hours_end == h %}selected{% endif %}>{{ '%02d:00' % h if h < 24 else '24:00 (midnight)' }}</option>
                            {% endfor %}
                        </select>
                    </div>
                    <div class="avail-field">
                        <label>Max Daily Transactions</label>
                        <input type="number" name="max_daily_transactions" value="{{ helper.max_daily_transactions }}" min="1" max="50">
                    </div>
                    <div class="avail-field">
                        <label>City</label>
                        <input type="text" name="city" value="{{ helper.city or '' }}" placeholder="Your city">
                    </div>
                </div>
                <button type="submit" class="btn btn-primary" style="margin-top: 15px; padding: 8px 24px; font-size: 14px;">Save Availability</button>
            </form>
        </div>

        <!-- Recent Transactions -->
        <div class="helper-section">
            <div class="helper-section-title">Recent Transactions</div>
            {% if transactions %}
                {% for t in transactions %}
                <div class="tx-item">
                    <div>
                        <span class="tx-route">{{ t.origin }} &rarr; {{ t.destination }}</span>
                        <span class="tx-airline">{{ t.airline or 'Unknown' }}</span>
                        <br><span class="tx-date">{{ t.created_at.strftime('%b %d, %Y %H:%M') if t.created_at else '' }}</span>
                    </div>
                    <div style="text-align: right;">
                        <div class="tx-earning">+{{ t.helper_earning_rlusd | round(2) if t.helper_earning_rlusd else '0.00' }} RLUSD</div>
                        <span class="tx-badge {% if t.status == 'completed' %}completed{% elif t.status in ('failed', 'cancelled') %}failed{% else %}in-progress{% endif %}">{{ t.status }}</span>
                    </div>
                </div>
                {% endfor %}
            {% else %}
                <p style="color: #fff; font-style: italic; padding: 20px 0;">No transactions yet. Once Phoenix matches you with a booking request, it will appear here.</p>
            {% endif %}
        </div>

        {% endif %}

        <!-- Quick Links -->
        <div class="quick-links">
            <a href="/wallet" class="btn" style="padding: 10px 20px; font-size: 14px; background: #1a1a2e; color: white; border-radius: 8px; text-decoration: none;">Manage Wallet</a>
            <a href="/p2p/my-bookings" class="btn" style="padding: 10px 20px; font-size: 14px; background: #f0f0f0; color: #333; border-radius: 8px; text-decoration: none;">My Bookings</a>
            <a href="/earn" style="padding: 10px 20px; font-size: 14px; color: #ff6b35; text-decoration: none;">Learn More</a>
        </div>
    </div>
</div>
"""


@app.route("/helper")
@login_required
def helper_dashboard():
    """Helper dashboard — P2P earning profile."""
    helper = HelperProfile.query.filter_by(user_id=current_user.id).first()
    transactions = []
    earnings_by_day = []
    earnings_7d = 0.0
    earnings_30d = 0.0

    if helper:
        transactions = P2PTransaction.query.filter_by(helper_id=helper.id)\
            .order_by(P2PTransaction.created_at.desc()).limit(20).all()

        # Build earnings chart data (last 14 days)
        from datetime import date, timedelta as td
        today = date.today()
        day_earnings = {}
        for i in range(14):
            d = today - td(days=13 - i)
            day_earnings[d] = 0.0

        completed_txs = P2PTransaction.query.filter_by(
            helper_id=helper.id, status="completed"
        ).filter(P2PTransaction.completed_at >= datetime.utcnow() - td(days=30)).all()

        for t in completed_txs:
            if t.completed_at and t.helper_earning_rlusd:
                d = t.completed_at.date()
                if d in day_earnings:
                    day_earnings[d] += t.helper_earning_rlusd
                days_ago = (today - d).days
                if days_ago < 7:
                    earnings_7d += t.helper_earning_rlusd
                earnings_30d += t.helper_earning_rlusd

        max_earning = max(day_earnings.values()) if day_earnings else 1
        if max_earning == 0:
            max_earning = 1
        for d in sorted(day_earnings.keys()):
            earnings_by_day.append({
                "label": d.strftime("%d"),
                "amount": round(day_earnings[d], 2),
                "height": max(5, int((day_earnings[d] / max_earning) * 100)) if day_earnings[d] > 0 else 3,
            })

    return render_template_string(
        BASE_TEMPLATE,
        title="Helper Dashboard",
        content=render_template_string(
            HELPER_DASHBOARD_CONTENT,
            current_user=current_user,
            helper=helper,
            transactions=transactions,
            earnings_by_day=earnings_by_day,
            earnings_7d=earnings_7d,
            earnings_30d=earnings_30d,
        ),
        current_user=current_user,
    )


@app.route("/helper/activate", methods=["POST"])
@login_required
def helper_activate():
    """Create or reactivate a helper profile."""
    country_code = request.form.get("country_code", "").strip().upper()
    city = request.form.get("city", "").strip()

    if not country_code or len(country_code) != 2:
        flash("Please select your country.", "error")
        return redirect(url_for("helper_dashboard"))

    # Check prerequisites
    has_wallet = UserWallet.query.filter_by(user_id=current_user.id).count() > 0
    has_card = UserCard.query.filter_by(user_id=current_user.id, is_active=True).count() > 0

    if not has_wallet:
        flash("Please connect an XRPL wallet first.", "warning")
        return redirect(url_for("wallet_page"))

    if not has_card:
        flash("Please add a payment card first.", "warning")
        return redirect(url_for("wallet_page"))

    helper = HelperProfile.query.filter_by(user_id=current_user.id).first()
    if helper:
        helper.is_active = True
        helper.country_code = country_code
        if city:
            helper.city = city
    else:
        helper = HelperProfile(
            user_id=current_user.id,
            country_code=country_code,
            city=city or None,
            is_active=True,
            is_approved=True,  # Auto-approve for now
        )
        db.session.add(helper)

    db.session.commit()
    flash("Helper profile activated! You can now earn from P2P bookings.", "success")
    return redirect(url_for("helper_dashboard"))


@app.route("/helper/toggle", methods=["POST"])
@login_required
def helper_toggle():
    """Toggle helper active status and CitizenSERP node session."""
    helper = HelperProfile.query.filter_by(user_id=current_user.id).first()
    if helper:
        helper.is_active = not helper.is_active
        db.session.commit()

        # Wire CitizenSERP node session lifecycle
        try:
            from citizenserp_payouts import citizenserp_manager
            if helper.is_active:
                # Node going online — start session
                wallet = UserWallet.query.filter_by(
                    user_id=current_user.id, is_primary=True
                ).first()
                wallet_addr = wallet.wallet_address if wallet else None
                citizenserp_manager.record_node_online(
                    user_id=current_user.id,
                    wallet_address=wallet_addr,
                    ip_country=helper.country_code,
                )
            else:
                # Node going offline — end session
                citizenserp_manager.record_node_offline(user_id=current_user.id)
        except Exception as e:
            logger.warning(f"CitizenSERP node session update failed (non-blocking): {e}")

        status = "activated" if helper.is_active else "paused"
        flash(f"Helper profile {status}.", "success")
    return redirect(url_for("helper_dashboard"))


@app.route("/helper/availability", methods=["POST"])
@login_required
def helper_availability():
    """Update helper availability settings."""
    helper = HelperProfile.query.filter_by(user_id=current_user.id).first()
    if helper:
        try:
            helper.available_hours_start = int(request.form.get("available_hours_start", 0))
            helper.available_hours_end = int(request.form.get("available_hours_end", 24))
            helper.max_daily_transactions = max(1, min(50, int(request.form.get("max_daily_transactions", 10))))
            city = request.form.get("city", "").strip()
            if city:
                helper.city = city
            db.session.commit()
            flash("Availability settings updated.", "success")
        except (ValueError, TypeError):
            flash("Invalid input.", "error")
    return redirect(url_for("helper_dashboard"))


@app.route("/helper/token/generate", methods=["POST"])
@login_required
def helper_token_generate():
    """Generate or regenerate a helper token for node service / extension auth."""
    import secrets
    helper = HelperProfile.query.filter_by(user_id=current_user.id).first()
    if not helper:
        flash("Activate your helper profile first.", "warning")
        return redirect(url_for("helper_dashboard"))
    if not helper.is_active:
        flash("Your helper profile must be active to generate a token.", "warning")
        return redirect(url_for("helper_dashboard"))

    helper.helper_token = secrets.token_urlsafe(48)
    db.session.commit()
    flash("Helper token generated. Copy it now — it won't be shown in full again.", "success")
    return redirect(url_for("helper_dashboard"))


@app.route("/helper/token", methods=["GET"])
@login_required
def helper_token_view():
    """Return the current helper token as JSON (for copy-to-clipboard)."""
    helper = HelperProfile.query.filter_by(user_id=current_user.id).first()
    if not helper or not helper.helper_token:
        return jsonify({"error": "No helper token found"}), 404
    return jsonify({"helper_token": helper.helper_token})


BROWSING_DASHBOARD_CONTENT = """
<div style="max-width: 900px; margin: 0 auto; padding: 30px 20px;">
    <h2 style="color: #ff6b35; margin-bottom: 5px;">Browser Extension Dashboard</h2>
    <p style="color: #fff; margin-bottom: 25px;">Passive browsing data earnings from the Phoenix Chrome extension.</p>

    <!-- Connection Status -->
    <div style="background: rgba(35,41,47,0.6); border-radius: 12px; padding: 20px; margin-bottom: 20px; border: 1px solid rgba(255,107,53,0.2);">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 15px;">
            <div>
                <div style="font-size: 13px; color: #fff;">Extension Status</div>
                {% if helper and helper.helper_token %}
                    <div style="color: #0f9d58; font-weight: 600;">
                        <span style="display: inline-block; width: 8px; height: 8px; background: #0f9d58; border-radius: 50%; margin-right: 6px;"></span>
                        Token Active
                    </div>
                {% else %}
                    <div style="color: #f44336;">
                        <span style="display: inline-block; width: 8px; height: 8px; background: #f44336; border-radius: 50%; margin-right: 6px;"></span>
                        No Token — Generate one below
                    </div>
                {% endif %}
            </div>
            <div>
                <div style="font-size: 13px; color: #fff;">Node ID</div>
                <div style="font-family: monospace; color: #fff;">{{ helper.node_id or '—' }}</div>
            </div>
            <div>
                <div style="font-size: 13px; color: #fff;">Last Seen</div>
                <div style="color: #fff;">{{ helper.last_seen.strftime('%b %d, %H:%M UTC') if helper and helper.last_seen else '—' }}</div>
            </div>
        </div>
    </div>

    <!-- Token Management -->
    <div style="background: rgba(35,41,47,0.6); border-radius: 12px; padding: 20px; margin-bottom: 20px; border: 1px solid rgba(255,255,255,0.05);">
        <div style="font-size: 15px; font-weight: 600; color: #ff6b35; margin-bottom: 12px;">Helper Token</div>
        {% if helper and helper.helper_token %}
            <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
                <code id="token-display" style="background: #1a1a2e; padding: 8px 14px; border-radius: 6px; color: #fff; font-size: 13px; word-break: break-all;">{{ helper.helper_token }}</code>
                <button onclick="navigator.clipboard.writeText(document.getElementById('token-display').textContent).then(()=>{this.textContent='Copied!';setTimeout(()=>{this.textContent='Copy'},1500)})" style="padding: 8px 16px; background: #ff6b35; color: white; border: none; border-radius: 6px; cursor: pointer; font-size: 13px;">Copy</button>
            </div>
            <p style="color: #fff; font-size: 12px; margin-top: 8px;">Use this token in the extension options or node service CLI.</p>
            <form action="/helper/token/generate" method="POST" style="margin-top: 10px;">
                <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                <button type="submit" style="padding: 6px 14px; background: transparent; color: #f44336; border: 1px solid #f44336; border-radius: 6px; cursor: pointer; font-size: 12px;" onclick="return confirm('This will invalidate your current token. Continue?')">Regenerate Token</button>
            </form>
        {% else %}
            <form action="/helper/token/generate" method="POST">
                <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                <button type="submit" class="btn btn-primary" style="padding: 10px 24px;">Generate Token</button>
            </form>
        {% endif %}
    </div>

    <!-- Earnings Summary -->
    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 15px; margin-bottom: 20px;">
        <div style="background: rgba(35,41,47,0.6); border-radius: 12px; padding: 18px; text-align: center; border: 1px solid rgba(255,255,255,0.05);">
            <div style="font-size: 24px; font-weight: 700; color: #ff6b35;">{{ '%.4f' | format(stats.totals.total_value_usd) }}</div>
            <div style="font-size: 12px; color: #fff; margin-top: 4px;">Total Earnings (USD)</div>
        </div>
        <div style="background: rgba(35,41,47,0.6); border-radius: 12px; padding: 18px; text-align: center; border: 1px solid rgba(255,255,255,0.05);">
            <div style="font-size: 24px; font-weight: 700; color: #fff;">{{ stats.totals.total_events }}</div>
            <div style="font-size: 12px; color: #fff; margin-top: 4px;">Total Events (7d)</div>
        </div>
        <div style="background: rgba(35,41,47,0.6); border-radius: 12px; padding: 18px; text-align: center; border: 1px solid rgba(255,255,255,0.05);">
            <div style="font-size: 24px; font-weight: 700; color: #fff;">{{ stats.totals.avg_events_per_day }}</div>
            <div style="font-size: 12px; color: #fff; margin-top: 4px;">Avg Events/Day</div>
        </div>
        <div style="background: rgba(35,41,47,0.6); border-radius: 12px; padding: 18px; text-align: center; border: 1px solid rgba(255,255,255,0.05);">
            <div style="font-size: 24px; font-weight: 700; color: #fff;">{{ stats.totals.avg_quality }}</div>
            <div style="font-size: 12px; color: #fff; margin-top: 4px;">Avg Quality Score</div>
        </div>
    </div>

    <!-- Per-Type Breakdown -->
    <div style="background: rgba(35,41,47,0.6); border-radius: 12px; padding: 20px; margin-bottom: 20px; border: 1px solid rgba(255,255,255,0.05);">
        <div style="font-size: 15px; font-weight: 600; color: #ff6b35; margin-bottom: 15px;">Event Breakdown (7 days)</div>
        <table style="width: 100%; border-collapse: collapse;">
            <thead>
                <tr style="border-bottom: 1px solid rgba(255,255,255,0.1);">
                    <th style="text-align: left; padding: 8px 0; color: #fff; font-size: 12px;">Type</th>
                    <th style="text-align: right; padding: 8px 0; color: #fff; font-size: 12px;">Count</th>
                    <th style="text-align: right; padding: 8px 0; color: #fff; font-size: 12px;">Value (USD)</th>
                    <th style="text-align: right; padding: 8px 0; color: #fff; font-size: 12px;">Avg Quality</th>
                </tr>
            </thead>
            <tbody>
                {% for etype, data in stats.per_type.items() %}
                <tr style="border-bottom: 1px solid rgba(255,255,255,0.05);">
                    <td style="padding: 10px 0; color: #fff;">{{ etype | replace('_', ' ') | title }}</td>
                    <td style="padding: 10px 0; color: #fff; text-align: right;">{{ data.count }}</td>
                    <td style="padding: 10px 0; color: #ff6b35; text-align: right;">${{ '%.4f' | format(data.value_usd) }}</td>
                    <td style="padding: 10px 0; color: #fff; text-align: right;">{{ data.avg_quality }}/100</td>
                </tr>
                {% endfor %}
                {% if not stats.per_type %}
                <tr>
                    <td colspan="4" style="padding: 20px 0; color: #fff; font-style: italic; text-align: center;">No browsing events captured yet. Install the extension and start browsing!</td>
                </tr>
                {% endif %}
            </tbody>
        </table>
    </div>

    <!-- Setup Instructions -->
    <div style="background: rgba(35,41,47,0.6); border-radius: 12px; padding: 20px; border: 1px solid rgba(255,255,255,0.05);">
        <div style="font-size: 15px; font-weight: 600; color: #ff6b35; margin-bottom: 12px;">Quick Setup</div>
        <ol style="color: #fff; line-height: 1.8; padding-left: 20px; margin: 0;">
            <li>Generate a helper token above (if you haven't already)</li>
            <li>Install the Phoenix Chrome extension from <code style="background: #1a1a2e; padding: 2px 6px; border-radius: 3px;">chrome://extensions</code> (load unpacked)</li>
            <li>Open extension options and paste your helper token</li>
            <li>Start the local node service: <code style="background: #1a1a2e; padding: 2px 6px; border-radius: 3px;">python node_service.py --token YOUR_TOKEN</code></li>
            <li>Browse normally — data is captured passively and you earn micropayments</li>
        </ol>
    </div>
</div>
"""


@app.route("/helper/browsing")
@login_required
def helper_browsing_dashboard():
    """Browsing data dashboard — extension status + passive earnings."""
    helper = HelperProfile.query.filter_by(user_id=current_user.id).first()

    # Default stats structure
    stats = {
        "per_type": {},
        "totals": {
            "total_events": 0,
            "total_value_usd": 0.0,
            "avg_events_per_day": 0.0,
            "avg_quality": 0.0,
        },
        "period_days": 7,
    }

    if helper:
        try:
            from node_data_processor import node_data_processor
            stats = node_data_processor.get_ingestion_stats(
                user_id=current_user.id, days_back=7
            )
        except Exception:
            pass

    return render_template_string(
        BASE_TEMPLATE,
        title="Browsing Dashboard",
        content=render_template_string(
            BROWSING_DASHBOARD_CONTENT,
            current_user=current_user,
            helper=helper,
            stats=stats,
        ),
        current_user=current_user,
    )


# --- P2P MATCHING API ---

@app.route("/api/p2p/match", methods=["POST"])
@login_required
@limiter.limit("30 per hour")
def api_p2p_match():
    """
    Find available helpers for a target market.

    POST body: { "target_market": "ES", "flight_price_usd": 744.12 }
    Returns: list of available helpers in that market
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    target_market = data.get("target_market", "").upper()
    if not target_market:
        return jsonify({"error": "target_market required"}), 400

    helpers = HelperProfile.query.filter_by(
        country_code=target_market,
        is_active=True,
        is_approved=True,
    ).order_by(
        HelperProfile.average_rating.desc(),
        HelperProfile.successful_transactions.desc(),
    ).limit(10).all()

    return jsonify({
        "target_market": target_market,
        "available_helpers": len(helpers),
        "helpers": [h.to_dict() for h in helpers],
    })


@app.route("/api/p2p/escrow/verify/<tx_hash>")
def api_p2p_escrow_verify(tx_hash):
    """
    Verify an escrow on-chain via XRPL ledger.
    Returns escrow status from the database + XRPL explorer link.
    """
    escrow = P2PEscrow.query.filter_by(create_tx_hash=tx_hash).first()
    if not escrow:
        return jsonify({"error": "Escrow not found"}), 404

    network = os.getenv("XRPL_NETWORK", "testnet")
    if network == "testnet":
        explorer_url = f"https://testnet.xrpl.org/transactions/{tx_hash}"
    else:
        explorer_url = f"https://livenet.xrpl.org/transactions/{tx_hash}"

    return jsonify({
        "escrow": escrow.to_dict(),
        "explorer_url": explorer_url,
        "on_chain_verified": escrow.on_chain_verified,
        "network": network,
    })


# --- P2P ORCHESTRATOR API ---

@app.route("/api/p2p/book", methods=["POST"])
@login_required
@limiter.limit("10 per hour")
def api_p2p_book():
    """
    Initiate a full P2P booking workflow.

    POST body: {
        "origin": "JFK",
        "destination": "LAX",
        "departure_date": "2026-03-01",
        "airline": "Delta",
        "flight_number": "DL123",
        "us_price_usd": 240.00,
        "target_price_usd": 208.00,
        "target_price_local": 192.00,
        "target_currency": "EUR",
        "target_market": "ES"
    }
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    required = ["origin", "destination", "departure_date", "target_price_usd", "target_market"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    # Get buyer's primary wallet
    buyer_wallet = UserWallet.query.filter_by(
        user_id=current_user.id, is_primary=True
    ).first()

    if not buyer_wallet:
        return jsonify({
            "error": "No wallet connected. Add an XRPL wallet in your Wallet page first."
        }), 400

    try:
        from p2p_orchestrator import get_orchestrator
        orchestrator = get_orchestrator(db.session)

        result = orchestrator.run_full_workflow(
            buyer_id=current_user.id,
            buyer_wallet_address=buyer_wallet.wallet_address,
            origin=data.get("origin", ""),
            destination=data.get("destination", ""),
            departure_date=data.get("departure_date", ""),
            airline=data.get("airline", ""),
            flight_number=data.get("flight_number", ""),
            us_price_usd=float(data.get("us_price_usd", 0)),
            target_price_usd=float(data.get("target_price_usd", 0)),
            target_price_local=float(data.get("target_price_local", 0)),
            target_currency=data.get("target_currency", ""),
            target_market=data.get("target_market", ""),
        )

        status_code = 200 if result.get("success") else 400
        if result.get("success"):
            audit_log("p2p_book", user_id=current_user.id,
                      transaction_id=result.get("transaction_id"),
                      target_market=data.get("target_market"),
                      amount_usd=data.get("target_price_usd"))
        return jsonify(result), status_code

    except Exception as e:
        logger.error(f"P2P booking error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/p2p/transaction/<transaction_id>")
@login_required
def api_p2p_transaction_status(transaction_id):
    """Get the status of a P2P transaction."""
    from p2p_orchestrator import get_orchestrator
    orchestrator = get_orchestrator(db.session)

    result = orchestrator.get_transaction_status(transaction_id)

    if "error" in result:
        return jsonify(result), 404

    # Verify the caller is the buyer or assigned helper
    tx = P2PTransaction.query.filter_by(transaction_id=transaction_id).first()
    if tx:
        helper = HelperProfile.query.filter_by(user_id=current_user.id).first()
        is_buyer = tx.buyer_id == current_user.id
        is_helper = helper and tx.helper_id == helper.id
        is_admin = getattr(current_user, 'is_admin', False)

        if not (is_buyer or is_helper or is_admin):
            return jsonify({"error": "Not authorized"}), 403

    return jsonify(result)


@app.route("/api/p2p/transaction/<transaction_id>/verify", methods=["POST"])
@login_required
def api_p2p_helper_verify(transaction_id):
    """Helper verifies the escrow and accepts the transaction."""
    from p2p_orchestrator import get_orchestrator
    orchestrator = get_orchestrator(db.session)

    result = orchestrator.helper_verify_escrow(transaction_id, current_user.id)

    status_code = 200 if result.get("success") else 400
    return jsonify(result), status_code


@app.route("/api/p2p/transaction/<transaction_id>/session", methods=["POST"])
@login_required
def api_p2p_create_session(transaction_id):
    """Create a browser control session for the transaction."""
    from p2p_orchestrator import get_orchestrator
    orchestrator = get_orchestrator(db.session)

    result = orchestrator.create_browser_session(transaction_id)

    status_code = 200 if result.get("success") else 400
    return jsonify(result), status_code


@app.route("/api/p2p/transaction/<transaction_id>/purchase", methods=["POST"])
@login_required
def api_p2p_start_purchase(transaction_id):
    """Start the automated purchase on the helper's browser."""
    from p2p_orchestrator import get_orchestrator
    orchestrator = get_orchestrator(db.session)

    result = orchestrator.start_purchase(transaction_id)

    status_code = 200 if result.get("success") else 400
    return jsonify(result), status_code


@app.route("/api/p2p/transaction/<transaction_id>/confirm", methods=["POST"])
@login_required
def api_p2p_confirm(transaction_id):
    """Confirm booking and release escrow."""
    data = request.get_json() or {}

    from p2p_orchestrator import get_orchestrator
    orchestrator = get_orchestrator(db.session)

    # Confirm booking
    confirm_result = orchestrator.confirm_booking(
        transaction_id=transaction_id,
        confirmation_code=data.get("confirmation_code", ""),
        passenger_name=data.get("passenger_name"),
        passenger_email=data.get("passenger_email"),
        eticket_url=data.get("eticket_url"),
    )

    if not confirm_result.get("success"):
        return jsonify(confirm_result), 400

    # Release escrow
    release_result = orchestrator.release_escrow(transaction_id)

    return jsonify({
        "booking_confirmed": True,
        "escrow_released": release_result.get("success", False),
        "confirmation_code": confirm_result.get("confirmation_code"),
        "helper_paid_rlusd": release_result.get("helper_paid_rlusd"),
        "status": "completed",
    })


@app.route("/api/p2p/transaction/<transaction_id>/cancel", methods=["POST"])
@login_required
def api_p2p_cancel(transaction_id):
    """Cancel a P2P transaction."""
    from p2p_orchestrator import get_orchestrator
    orchestrator = get_orchestrator(db.session)

    result = orchestrator.cancel_transaction(transaction_id, "buyer")

    status_code = 200 if result.get("success") else 400
    return jsonify(result), status_code


@app.route("/api/p2p/my-transactions")
@login_required
def api_p2p_my_transactions():
    """Get all P2P transactions for the current user (as buyer)."""
    from p2p_orchestrator import get_orchestrator
    orchestrator = get_orchestrator(db.session)

    transactions = orchestrator.get_buyer_transactions(current_user.id)
    return jsonify({"transactions": transactions})


@app.route("/api/p2p/browser-session/<session_id>")
@login_required
def api_p2p_browser_session(session_id):
    """Get browser control session status — removed (Build #89)."""
    return jsonify({"error": "Browser control removed — use node-based browsing"}), 410


# --- GLOBAL SEARCH & ITINERARY API ---

# Store itineraries in session (in production, use database)
itineraries = {}

SEARCH_PAGE_CONTENT = """
<style>
.search-form { max-width: 900px; margin: 0 auto; }
.search-row { display: flex; gap: 15px; margin-bottom: 15px; flex-wrap: wrap; }
.search-row .form-group { flex: 1; min-width: 150px; position: relative; }
.leg-card { background: #f8f9fa; padding: 15px; border-radius: 8px; margin-bottom: 10px; }
.leg-header { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.leg-number { background: #ff6b35; color: white; width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 14px; }
.leg-info { flex: 1; }
.add-leg-btn { border: 2px dashed #ddd; padding: 15px; text-align: center; border-radius: 8px; cursor: pointer; color: #666; }
.add-leg-btn:hover { border-color: #ff6b35; color: #ff6b35; }
.results-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 20px; margin-top: 20px; }
.deal-card { background: white; border: 1px solid #eee; border-radius: 12px; padding: 20px; }
.deal-card.has-deal { border-color: #28a745; border-width: 2px; }
.savings-badge { background: #28a745; color: white; padding: 4px 12px; border-radius: 20px; font-size: 14px; font-weight: bold; }
.market-tag { background: #e9ecef; padding: 2px 8px; border-radius: 4px; font-size: 12px; margin-right: 5px; }

/* Tab styles */
.search-tabs { display: flex; gap: 0; margin-bottom: 20px; border-bottom: 2px solid #eee; }
.search-tab { padding: 12px 24px; cursor: pointer; border: none; background: none; font-size: 16px; color: #666; border-bottom: 2px solid transparent; margin-bottom: -2px; }
.search-tab:hover { color: #ff6b35; }
.search-tab.active { color: #ff6b35; border-bottom-color: #ff6b35; font-weight: 600; }
.tab-content { display: none; }
.tab-content.active { display: block; }

/* Search options bar (Google-style) */
.search-options { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 20px; align-items: center; }
.option-select {
    padding: 8px 12px;
    border: 1px solid #ddd;
    border-radius: 20px;
    background: white;
    font-size: 14px;
    cursor: pointer;
    min-width: 120px;
}
.option-select:hover { border-color: #ff6b35; }
.option-select:focus { outline: none; border-color: #ff6b35; }

/* Passenger dropdown */
.passenger-dropdown { position: relative; display: inline-block; }
.passenger-btn {
    padding: 8px 16px;
    border: 1px solid #ddd;
    border-radius: 20px;
    background: white;
    font-size: 14px;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 8px;
}
.passenger-btn:hover { border-color: #ff6b35; }
.passenger-menu {
    display: none;
    position: absolute;
    top: 100%;
    left: 0;
    background: white;
    border: 1px solid #ddd;
    border-radius: 8px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    padding: 15px;
    z-index: 1000;
    min-width: 280px;
    margin-top: 5px;
}
.passenger-menu.show { display: block; }
.passenger-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 10px 0;
    border-bottom: 1px solid #eee;
}
.passenger-row:last-child { border-bottom: none; }
.passenger-label { font-size: 14px; }
.passenger-label small { display: block; color: #666; font-size: 12px; }
.passenger-controls { display: flex; align-items: center; gap: 12px; }
.passenger-controls button {
    width: 32px;
    height: 32px;
    border: 1px solid #ddd;
    border-radius: 50%;
    background: white;
    font-size: 18px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
}
.passenger-controls button:hover { background: #fff8f5; border-color: #ff6b35; }
.passenger-controls button:disabled { opacity: 0.5; cursor: not-allowed; }
.passenger-controls span { min-width: 20px; text-align: center; font-weight: 600; }

/* Swap button */
.swap-btn {
    width: 36px;
    height: 36px;
    border: 1px solid #ddd;
    border-radius: 50%;
    background: white;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 16px;
    margin: 0 -5px;
    z-index: 1;
    position: relative;
}
.swap-btn:hover { background: #fff8f5; border-color: #ff6b35; }

/* Price comparison table */
.price-table { width: 100%; border-collapse: collapse; margin-top: 15px; }
.price-table th, .price-table td { padding: 12px 15px; text-align: left; border-bottom: 1px solid #eee; }
.price-table th { background: #f8f9fa; font-weight: 600; color: #333; }
.price-table tr:hover { background: #f8f9fa; }
.price-table .cheapest { background: #d4edda; }
.price-table .cheapest td { color: #155724; font-weight: 600; }
.price-table .market-flag { font-size: 18px; margin-right: 8px; }
.google-link { color: #ff6b35; text-decoration: none; font-size: 14px; }
.google-link:hover { text-decoration: underline; }

/* Autocomplete styles */
.autocomplete-dropdown {
    position: absolute;
    top: 100%;
    left: 0;
    right: 0;
    background: white;
    color: #1a1a2e;
    border: 1px solid #ddd;
    border-radius: 8px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    z-index: 1000;
    max-height: 300px;
    overflow-y: auto;
    display: none;
}
.autocomplete-item {
    padding: 12px 15px;
    cursor: pointer;
    border-bottom: 1px solid #eee;
}
.autocomplete-item:last-child { border-bottom: none; }
.autocomplete-item:hover { background: #fff8f5; }
.autocomplete-item.selected { background: #e8f0fe; }
.autocomplete-code { font-weight: bold; color: #ff6b35; font-size: 16px; }
.autocomplete-city { color: #333; }
.autocomplete-country { color: #666; font-size: 13px; }
.airport-input { position: relative; }
.airport-display {
    font-size: 12px;
    color: #666;
    margin-top: 4px;
    min-height: 18px;
}

/* Flight fields row */
.flight-fields { display: flex; gap: 0; align-items: flex-end; flex-wrap: wrap; }
.flight-fields .form-group { flex: 1; min-width: 140px; }
.flight-fields .form-group input {
    border-radius: 0;
    border-right: none;
}
.flight-fields .form-group:first-child input { border-radius: 8px 0 0 8px; }
.flight-fields .form-group:last-child input { border-radius: 0 8px 8px 0; border-right: 1px solid #ddd; }
.flight-fields .form-group.date-field { max-width: 160px; }

/* Return date conditional */
#return-date-group { display: none; }
#return-date-group.show { display: block; }

/* Enhanced results table */
.price-table { font-size: 14px; }
.price-table th { background: #e9ecef; }
.price-table td { vertical-align: middle; }
details summary { padding: 10px 0; }
details[open] summary { border-bottom: 1px solid #eee; margin-bottom: 10px; }

/* Calendar results */
#calendar-results-container .price-table tr.cheapest td {
    background: #d4edda;
    font-weight: bold;
}

/* Select flight button */
.select-flight-btn {
    background: linear-gradient(135deg, #ff6b35, #ff8c00);
    border: none;
    color: white;
    border-radius: 20px;
    cursor: pointer;
    font-weight: 600;
    transition: all 0.3s ease;
}
.select-flight-btn:hover {
    transform: scale(1.05);
    box-shadow: 0 4px 15px rgba(67, 97, 238, 0.4);
}
tr.cheapest .select-flight-btn {
    background: linear-gradient(135deg, #28a745, #20903b);
}

/* Selected flight row styling */
tr.selected-flight {
    background: linear-gradient(135deg, rgba(67, 97, 238, 0.15), rgba(76, 201, 240, 0.15)) !important;
    border-left: 4px solid #ff6b35;
    position: relative;
    animation: selectPulse 0.3s ease;
}
tr.selected-flight td {
    background: transparent !important;
}
tr.selected-flight td:first-child::before {
    content: '\\2713';
    position: absolute;
    left: 8px;
    color: #ff6b35;
    font-weight: bold;
    font-size: 16px;
}
tr.selected-flight .select-flight-btn {
    background: linear-gradient(135deg, #6c757d, #5a6268);
}
tr.selected-flight .select-flight-btn::after {
    content: ' \\2713';
}
@keyframes selectPulse {
    0% { transform: scale(1); }
    50% { transform: scale(1.01); background: rgba(67, 97, 238, 0.25); }
    100% { transform: scale(1); }
}

/* Checkout panel */
.checkout-panel {
    margin-top: 20px;
    animation: slideUp 0.4s ease;
}
@keyframes slideUp {
    from { opacity: 0; transform: translateY(30px); }
    to { opacity: 1; transform: translateY(0); }
}

/* Payment modal */
.payment-modal {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    z-index: 10001;
    display: flex;
    align-items: center;
    justify-content: center;
}
.payment-modal-overlay {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: rgba(0, 0, 0, 0.6);
    backdrop-filter: blur(5px);
}
.payment-modal-content {
    position: relative;
    background: white;
    padding: 30px;
    border-radius: 20px;
    max-width: 450px;
    width: 90%;
    box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
    animation: modalPop 0.3s ease;
}
@keyframes modalPop {
    from { opacity: 0; transform: scale(0.9); }
    to { opacity: 1; transform: scale(1); }
}
.payment-modal-close {
    position: absolute;
    top: 15px;
    right: 20px;
    background: none;
    border: none;
    font-size: 28px;
    cursor: pointer;
    color: #666;
    transition: color 0.3s;
}
.payment-modal-close:hover { color: #333; }

.payment-options {
    display: flex;
    flex-direction: column;
    gap: 12px;
}
.payment-option-btn {
    display: flex;
    align-items: center;
    gap: 15px;
    padding: 15px 20px;
    border: 2px solid #e5e7eb;
    border-radius: 12px;
    background: white;
    cursor: pointer;
    font-size: 16px;
    font-weight: 500;
    transition: all 0.3s ease;
}
.payment-option-btn:hover {
    border-color: #ff6b35;
    background: #fff8f5;
    transform: translateX(5px);
}
.payment-icon {
    font-size: 24px;
}
</style>

<div class="card search-form">
    <h1>Global Flight Search</h1>
    <p style="color: #666; margin-bottom: 15px;">Compare prices across 40+ regional markets to find the best deals.</p>

    <!-- Search Tabs -->
    <div class="search-tabs">
        <button type="button" class="search-tab active" onclick="switchTab('route')">Route Search</button>
        <button type="button" class="search-tab" onclick="switchTab('import')">Import Itinerary</button>
        <button type="button" class="search-tab" onclick="switchTab('calendar')">Price Calendar</button>
        <button type="button" class="search-tab" onclick="switchTab('flight')">Flight Number</button>
    </div>

    <!-- Route Search Tab -->
    <div id="tab-route" class="tab-content active">
        <form id="search-form" onsubmit="return searchFlights(event)">

            <!-- Search Options Bar (Google-style) -->
            <div class="search-options">
                <select name="trip_type" id="trip-type" class="option-select" onchange="handleTripTypeChange()">
                    <option value="one_way">One way</option>
                    <option value="round_trip">Round trip</option>
                    <option value="multi_city">Multi-city</option>
                </select>

                <div class="passenger-dropdown">
                    <button type="button" class="passenger-btn" onclick="togglePassengerMenu()">
                        <span id="passenger-summary">1 passenger</span>
                        <span style="font-size: 10px;">▼</span>
                    </button>
                    <div class="passenger-menu" id="passenger-menu">
                        <div class="passenger-row">
                            <div class="passenger-label">Adults<small>Age 12+</small></div>
                            <div class="passenger-controls">
                                <button type="button" onclick="adjustPassenger('adults', -1)">−</button>
                                <span id="adults-count">1</span>
                                <button type="button" onclick="adjustPassenger('adults', 1)">+</button>
                            </div>
                        </div>
                        <div class="passenger-row">
                            <div class="passenger-label">Children<small>Age 2-11</small></div>
                            <div class="passenger-controls">
                                <button type="button" onclick="adjustPassenger('children', -1)">−</button>
                                <span id="children-count">0</span>
                                <button type="button" onclick="adjustPassenger('children', 1)">+</button>
                            </div>
                        </div>
                        <div class="passenger-row">
                            <div class="passenger-label">Infants<small>In seat</small></div>
                            <div class="passenger-controls">
                                <button type="button" onclick="adjustPassenger('infants_seat', -1)">−</button>
                                <span id="infants_seat-count">0</span>
                                <button type="button" onclick="adjustPassenger('infants_seat', 1)">+</button>
                            </div>
                        </div>
                        <div class="passenger-row">
                            <div class="passenger-label">Infants<small>On lap</small></div>
                            <div class="passenger-controls">
                                <button type="button" onclick="adjustPassenger('infants_lap', -1)">−</button>
                                <span id="infants_lap-count">0</span>
                                <button type="button" onclick="adjustPassenger('infants_lap', 1)">+</button>
                            </div>
                        </div>
                        <button type="button" class="btn" style="width: 100%; margin-top: 10px;" onclick="togglePassengerMenu()">Done</button>
                    </div>
                </div>
                <input type="hidden" name="adults" id="adults-input" value="1">
                <input type="hidden" name="children" id="children-input" value="0">
                <input type="hidden" name="infants_seat" id="infants_seat-input" value="0">
                <input type="hidden" name="infants_lap" id="infants_lap-input" value="0">

                <select name="cabin_class" id="cabin-class" class="option-select">
                    <option value="economy">Economy</option>
                    <option value="premium_economy">Premium Economy</option>
                    <option value="business">Business</option>
                    <option value="first">First Class</option>
                    <option value="all">All Classes</option>
                </select>

                <select name="stops" class="option-select">
                    <option value="any">Any stops</option>
                    <option value="nonstop">Nonstop only</option>
                    <option value="1">1 stop or fewer</option>
                    <option value="2">2 stops or fewer</option>
                </select>

                <label class="flexible-dates-toggle" style="display: flex; align-items: center; gap: 8px; padding: 8px 12px; background: #f8f9fa; border-radius: 20px; cursor: pointer; font-size: 14px;">
                    <input type="checkbox" name="flexible_dates" id="flexible-dates" style="width: 16px; height: 16px;" onchange="toggleFlexDaysSelector()">
                    <span>Flexible +/-</span>
                    <select name="flex_days" id="flex-days" class="option-select" style="min-width: 80px; padding: 4px 8px; font-size: 13px;">
                        <option value="1">1 day</option>
                        <option value="2">2 days</option>
                        <option value="3" selected>3 days</option>
                        <option value="5">5 days</option>
                        <option value="7">7 days</option>
                    </select>
                </label>
            </div>

            <!-- Single/Round Trip Flight Fields -->
            <div id="single-flight-container">
                <div class="search-row" style="align-items: flex-end;">
                    <div class="form-group airport-input" style="flex: 2;">
                        <label>From</label>
                        <input type="text" name="origin" id="main-origin" class="airport-search" data-field="origin" data-leg="main"
                               placeholder="City or airport..." autocomplete="off" required>
                        <div class="autocomplete-dropdown" id="dropdown-origin-main"></div>
                        <div class="airport-display" id="display-origin-main"></div>
                    </div>

                    <button type="button" class="swap-btn" onclick="swapAirports()" title="Swap origin and destination">⇄</button>

                    <div class="form-group airport-input" style="flex: 2;">
                        <label>To</label>
                        <input type="text" name="destination" id="main-destination" class="airport-search" data-field="destination" data-leg="main"
                               placeholder="City or airport..." autocomplete="off" required>
                        <div class="autocomplete-dropdown" id="dropdown-destination-main"></div>
                        <div class="airport-display" id="display-destination-main"></div>
                    </div>

                    <div class="form-group date-field">
                        <label>Departure</label>
                        <input type="date" name="departure_date" id="departure-date" required>
                    </div>

                    <div class="form-group date-field" id="return-date-group">
                        <label>Return</label>
                        <input type="date" name="return_date" id="return-date">
                    </div>
                </div>
            </div>

            <!-- Multi-city Flight Fields -->
            <div id="multi-city-container" style="display: none;">
                <div id="legs-container">
                    <div class="leg-card" data-leg="1">
                        <div class="leg-header">
                            <div class="leg-number">1</div>
                            <span style="color: #666; font-size: 14px;">Flight 1</span>
                        </div>
                        <div class="search-row">
                            <div class="form-group airport-input">
                                <label>From</label>
                                <input type="text" name="origin_1" class="airport-search" data-field="origin" data-leg="1"
                                       placeholder="City or airport..." autocomplete="off">
                                <div class="autocomplete-dropdown" id="dropdown-origin-1"></div>
                            </div>
                            <div class="form-group airport-input">
                                <label>To</label>
                                <input type="text" name="destination_1" class="airport-search" data-field="destination" data-leg="1"
                                       placeholder="City or airport..." autocomplete="off">
                                <div class="autocomplete-dropdown" id="dropdown-destination-1"></div>
                            </div>
                            <div class="form-group" style="max-width: 160px;">
                                <label>Date</label>
                                <input type="date" name="date_1">
                            </div>
                        </div>
                    </div>
                </div>
                <div class="add-leg-btn" onclick="addLeg()">+ Add another flight</div>
            </div>

            <div style="margin-top: 20px;">
                <button type="submit" class="btn" id="search-btn" style="padding: 14px 32px; font-size: 16px;">
                    Search All Markets
                </button>
                <span id="search-status" style="margin-left: 15px; color: #666;"></span>
            </div>
        </form>
    </div>

    <!-- Import Itinerary Tab -->
    <div id="tab-import" class="tab-content">
        <p style="color: #666; margin-bottom: 20px;">
            Import your Google Flights itinerary to compare prices across 16+ regional markets.
            Paste flight details from your booking confirmation or enter them manually.
        </p>

        <div style="background: #fff5f0; padding: 15px; border-radius: 8px; margin-bottom: 20px;">
            <strong>How it works:</strong>
            <ol style="margin: 10px 0 0 20px; color: #333;">
                <li>Find your flight on Google Flights</li>
                <li>Copy the flight details (flight number, route, date)</li>
                <li>Paste or enter them below</li>
                <li>We'll search the same flight across 16+ country markets via proxy servers</li>
                <li>See where you can book it cheaper!</li>
            </ol>
        </div>

        <form id="import-form" onsubmit="return compareImportedItinerary(event)">
            <!-- Option 1: Paste itinerary text -->
            <div class="form-group" style="margin-bottom: 20px;">
                <label style="font-weight: 600;">Option 1: Paste Your Itinerary</label>
                <textarea name="itinerary_text" id="itinerary-text" rows="6"
                    placeholder="Paste your flight confirmation email or Google Flights details here...

Example:
Flight 1: AA 123 - Los Angeles (LAX) to New York (JFK) - Mar 15, 2026
Flight 2: AA 456 - New York (JFK) to Los Angeles (LAX) - Mar 22, 2026"
                    style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-family: inherit;"></textarea>
                <small style="color: #666;">We'll automatically extract flight numbers, routes, and dates.</small>
            </div>

            <div style="text-align: center; margin: 20px 0; color: #666; font-weight: bold;">— OR —</div>

            <!-- Option 2: Manual entry -->
            <div style="margin-bottom: 20px;">
                <label style="font-weight: 600;">Option 2: Enter Flights Manually</label>
                <div id="import-flights-container">
                    <div class="leg-card import-flight-entry" data-index="0">
                        <div class="leg-header">
                            <div class="leg-number">1</div>
                            <span style="color: #666; font-size: 14px;">Flight 1</span>
                            <button type="button" class="remove-flight-btn" onclick="removeImportFlight(0)" style="margin-left: auto; background: none; border: none; color: #dc3545; cursor: pointer; font-size: 18px;" title="Remove flight">×</button>
                        </div>
                        <div class="search-row">
                            <div class="form-group">
                                <label>Flight Number</label>
                                <input type="text" name="flight_0" class="import-flight-number" placeholder="e.g., AA 123" style="text-transform: uppercase;">
                            </div>
                            <div class="form-group airport-input">
                                <label>From</label>
                                <input type="text" name="origin_0" class="airport-search import-origin" data-field="import_origin" data-leg="import0" placeholder="LAX" autocomplete="off">
                                <div class="autocomplete-dropdown" id="dropdown-import_origin-import0"></div>
                            </div>
                            <div class="form-group airport-input">
                                <label>To</label>
                                <input type="text" name="destination_0" class="airport-search import-destination" data-field="import_destination" data-leg="import0" placeholder="JFK" autocomplete="off">
                                <div class="autocomplete-dropdown" id="dropdown-import_destination-import0"></div>
                            </div>
                            <div class="form-group" style="max-width: 160px;">
                                <label>Date</label>
                                <input type="date" name="date_0" class="import-date">
                            </div>
                        </div>
                    </div>
                </div>
                <div class="add-leg-btn" onclick="addImportFlight()">+ Add another flight</div>
            </div>

            <!-- Markets to check -->
            <div style="margin-bottom: 20px;">
                <label style="font-weight: 600;">Markets to Compare</label>
                <p style="color: #666; font-size: 14px; margin-bottom: 10px;">Select which regional markets to search via proxy:</p>
                <div style="display: flex; flex-wrap: wrap; gap: 10px;">
                    <label style="display: flex; align-items: center; gap: 5px; padding: 8px 12px; background: #f8f9fa; border-radius: 6px; cursor: pointer;">
                        <input type="checkbox" name="markets" value="US" checked> US
                    </label>
                    <label style="display: flex; align-items: center; gap: 5px; padding: 8px 12px; background: #f8f9fa; border-radius: 6px; cursor: pointer;">
                        <input type="checkbox" name="markets" value="UK" checked> UK
                    </label>
                    <label style="display: flex; align-items: center; gap: 5px; padding: 8px 12px; background: #f8f9fa; border-radius: 6px; cursor: pointer;">
                        <input type="checkbox" name="markets" value="DE" checked> Germany
                    </label>
                    <label style="display: flex; align-items: center; gap: 5px; padding: 8px 12px; background: #f8f9fa; border-radius: 6px; cursor: pointer;">
                        <input type="checkbox" name="markets" value="ES" checked> Spain
                    </label>
                    <label style="display: flex; align-items: center; gap: 5px; padding: 8px 12px; background: #f8f9fa; border-radius: 6px; cursor: pointer;">
                        <input type="checkbox" name="markets" value="FR" checked> France
                    </label>
                    <label style="display: flex; align-items: center; gap: 5px; padding: 8px 12px; background: #f8f9fa; border-radius: 6px; cursor: pointer;">
                        <input type="checkbox" name="markets" value="JP" checked> Japan
                    </label>
                    <label style="display: flex; align-items: center; gap: 5px; padding: 8px 12px; background: #f8f9fa; border-radius: 6px; cursor: pointer;">
                        <input type="checkbox" name="markets" value="AU"> Australia
                    </label>
                    <label style="display: flex; align-items: center; gap: 5px; padding: 8px 12px; background: #f8f9fa; border-radius: 6px; cursor: pointer;">
                        <input type="checkbox" name="markets" value="IN"> India
                    </label>
                    <label style="display: flex; align-items: center; gap: 5px; padding: 8px 12px; background: #f8f9fa; border-radius: 6px; cursor: pointer;">
                        <input type="checkbox" name="markets" value="BR"> Brazil
                    </label>
                    <label style="display: flex; align-items: center; gap: 5px; padding: 8px 12px; background: #f8f9fa; border-radius: 6px; cursor: pointer;">
                        <input type="checkbox" name="markets" value="MX"> Mexico
                    </label>
                    <label style="display: flex; align-items: center; gap: 5px; padding: 8px 12px; background: #f8f9fa; border-radius: 6px; cursor: pointer;">
                        <input type="checkbox" name="markets" value="SG"> Singapore
                    </label>
                    <label style="display: flex; align-items: center; gap: 5px; padding: 8px 12px; background: #f8f9fa; border-radius: 6px; cursor: pointer;">
                        <input type="checkbox" name="markets" value="KR"> South Korea
                    </label>
                </div>
            </div>

            <div style="margin-top: 20px;">
                <button type="submit" class="btn" id="import-search-btn" style="padding: 14px 32px; font-size: 16px;">
                    Compare Prices Across Markets
                </button>
                <span id="import-search-status" style="margin-left: 15px; color: #666;"></span>
            </div>
        </form>
    </div>

    <div id="import-results-container"></div>

    <!-- Price Calendar Tab -->
    <div id="tab-calendar" class="tab-content">
        <p style="color: #666; margin-bottom: 20px;">Find the cheapest dates to fly - like Google Flights' price calendar. Shows best prices across a date range.</p>

        <form id="calendar-search-form" onsubmit="return searchCalendar(event)">
            <div class="search-row">
                <div class="form-group airport-input" style="flex: 2;">
                    <label>From</label>
                    <input type="text" name="cal_origin" class="airport-search" data-field="cal_origin" data-leg="cal"
                           placeholder="City or airport..." autocomplete="off" required>
                    <div class="autocomplete-dropdown" id="dropdown-cal_origin-cal"></div>
                </div>
                <div class="form-group airport-input" style="flex: 2;">
                    <label>To</label>
                    <input type="text" name="cal_destination" class="airport-search" data-field="cal_destination" data-leg="cal"
                           placeholder="City or airport..." autocomplete="off" required>
                    <div class="autocomplete-dropdown" id="dropdown-cal_destination-cal"></div>
                </div>
            </div>
            <div class="search-row">
                <div class="form-group">
                    <label>Start Date</label>
                    <input type="date" name="cal_start_date" id="cal-start-date" required>
                </div>
                <div class="form-group">
                    <label>End Date</label>
                    <input type="date" name="cal_end_date" id="cal-end-date" required>
                </div>
            </div>
            <div style="margin-top: 20px;">
                <button type="submit" class="btn" id="calendar-search-btn">Find Cheapest Dates</button>
                <span id="calendar-search-status" style="margin-left: 15px; color: #666;"></span>
            </div>
        </form>
    </div>

    <!-- Flight Number Search Tab -->
    <div id="tab-flight" class="tab-content">
        <p style="color: #666; margin-bottom: 20px;">Compare prices for a specific flight across different regional markets. Enter a flight number like "LL 2624" or "AA 123".</p>

        <form id="flight-search-form" onsubmit="return searchFlightNumber(event)">
            <div class="search-row">
                <div class="form-group">
                    <label>Flight Number</label>
                    <input type="text" name="flight_number" placeholder="e.g., AA 123, LL 2624" required style="font-size: 18px; text-transform: uppercase;">
                </div>
            </div>
            <div class="search-row">
                <div class="form-group airport-input">
                    <label>From</label>
                    <input type="text" name="fn_origin" class="airport-search" data-field="fn_origin" data-leg="fn"
                           placeholder="Origin airport..." autocomplete="off" required>
                    <div class="autocomplete-dropdown" id="dropdown-fn_origin-fn"></div>
                </div>
                <div class="form-group airport-input">
                    <label>To</label>
                    <input type="text" name="fn_destination" class="airport-search" data-field="fn_destination" data-leg="fn"
                           placeholder="Destination airport..." autocomplete="off" required>
                    <div class="autocomplete-dropdown" id="dropdown-fn_destination-fn"></div>
                </div>
                <div class="form-group">
                    <label>Date</label>
                    <input type="date" name="fn_date" required>
                </div>
            </div>
            <div style="margin-top: 20px;">
                <button type="submit" class="btn" id="flight-search-btn">Compare Prices Across Markets</button>
                <span id="flight-search-status" style="margin-left: 15px; color: #666;"></span>
            </div>
        </form>
    </div>
</div>

<div id="results-container"></div>
<div id="calendar-results-container"></div>
<div id="flight-results-container"></div>

<script>
// Set auth status for client-side rendering
window.isAuthenticated = {{ 'true' if current_user.is_authenticated else 'false' }};
let legCount = 1;
let searchTimeout = null;
let selectedIndex = -1;

// Passenger counts
let passengers = { adults: 1, children: 0, infants_seat: 0, infants_lap: 0 };

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    initAutocomplete();
    handleTripTypeChange();
    setMinDates();
    restoreSearchPreferences();  // Auto-fill from previous search
    setupAutoSave();  // Save preferences on field changes
});

// Auto-save preferences when fields change
function setupAutoSave() {
    // Debounce save function
    let saveTimer = null;
    function debouncedSave() {
        clearTimeout(saveTimer);
        saveTimer = setTimeout(saveSearchPreferences, 500);
    }

    // Watch all important form fields
    const watchSelectors = [
        '#trip-type', '#cabin-class', '[name="stops"]',
        '#flexible-dates', '#flex-days',
        '#main-origin', '#main-destination',
        '#departure-date', '#return-date',
        '#flight-number-input', '#flight-origin',
        '#flight-destination', '#flight-date',
        '[name^="origin_"]', '[name^="destination_"]', '[name^="date_"]'
    ];

    watchSelectors.forEach(selector => {
        document.querySelectorAll(selector).forEach(el => {
            el.addEventListener('change', debouncedSave);
            el.addEventListener('blur', debouncedSave);
        });
    });

    // Also save on tab switch
    document.querySelectorAll('.search-tab').forEach(tab => {
        tab.addEventListener('click', () => setTimeout(saveSearchPreferences, 100));
    });
}

// ===============================
// AUTO-SAVE/RESTORE SEARCH PREFERENCES
// ===============================
const SEARCH_PREFS_KEY = 'phoenix_search_prefs';

function saveSearchPreferences() {
    try {
        const prefs = {
            tripType: document.getElementById('trip-type')?.value,
            cabinClass: document.getElementById('cabin-class')?.value,
            stops: document.querySelector('[name="stops"]')?.value,
            flexibleDates: document.getElementById('flexible-dates')?.checked,
            flexDays: document.getElementById('flex-days')?.value,
            passengers: { ...passengers },

            // Main flight fields
            origin: document.getElementById('main-origin')?.value,
            destination: document.getElementById('main-destination')?.value,
            departureDate: document.getElementById('departure-date')?.value,
            returnDate: document.getElementById('return-date')?.value,

            // Multi-city legs
            multiCityLegs: [],

            // Flight number search
            flightNumber: document.getElementById('flight-number-input')?.value,
            flightOrigin: document.getElementById('flight-origin')?.value,
            flightDestination: document.getElementById('flight-destination')?.value,
            flightDate: document.getElementById('flight-date')?.value,

            // Timestamp for expiry
            savedAt: Date.now()
        };

        // Save multi-city legs if present
        document.querySelectorAll('#legs-container .leg-card').forEach(card => {
            const num = card.dataset.leg;
            prefs.multiCityLegs.push({
                origin: document.querySelector(`[name="origin_${num}"]`)?.value,
                destination: document.querySelector(`[name="destination_${num}"]`)?.value,
                date: document.querySelector(`[name="date_${num}"]`)?.value
            });
        });

        localStorage.setItem(SEARCH_PREFS_KEY, JSON.stringify(prefs));
        console.log('Search preferences saved');
    } catch (e) {
        console.warn('Could not save search preferences:', e);
    }
}

function restoreSearchPreferences() {
    try {
        const saved = localStorage.getItem(SEARCH_PREFS_KEY);
        if (!saved) return;

        const prefs = JSON.parse(saved);

        // Check if preferences are older than 24 hours
        const maxAge = 24 * 60 * 60 * 1000;
        if (Date.now() - prefs.savedAt > maxAge) {
            localStorage.removeItem(SEARCH_PREFS_KEY);
            return;
        }

        console.log('Restoring search preferences...');

        // Restore trip type first (affects form layout)
        if (prefs.tripType && document.getElementById('trip-type')) {
            document.getElementById('trip-type').value = prefs.tripType;
            handleTripTypeChange();
        }

        // Restore options
        if (prefs.cabinClass) {
            const cabinSelect = document.getElementById('cabin-class');
            if (cabinSelect) cabinSelect.value = prefs.cabinClass;
        }
        if (prefs.stops) {
            const stopsSelect = document.querySelector('[name="stops"]');
            if (stopsSelect) stopsSelect.value = prefs.stops;
        }
        if (prefs.flexibleDates !== undefined) {
            const flexCheck = document.getElementById('flexible-dates');
            if (flexCheck) {
                flexCheck.checked = prefs.flexibleDates;
                toggleFlexDaysSelector();
            }
        }
        if (prefs.flexDays) {
            const flexDays = document.getElementById('flex-days');
            if (flexDays) flexDays.value = prefs.flexDays;
        }

        // Restore passengers
        if (prefs.passengers) {
            passengers = { ...prefs.passengers };
            Object.keys(passengers).forEach(type => {
                const countEl = document.getElementById(`${type}-count`);
                const inputEl = document.getElementById(`${type}-input`);
                if (countEl) countEl.textContent = passengers[type];
                if (inputEl) inputEl.value = passengers[type];
            });
            updatePassengerSummary();
        }

        // Restore main flight fields
        if (prefs.origin) {
            document.getElementById('main-origin').value = prefs.origin;
        }
        if (prefs.destination) {
            document.getElementById('main-destination').value = prefs.destination;
        }
        if (prefs.departureDate) {
            document.getElementById('departure-date').value = prefs.departureDate;
        }
        if (prefs.returnDate) {
            document.getElementById('return-date').value = prefs.returnDate;
        }

        // Restore flight number tab
        if (prefs.flightNumber) {
            const fnInput = document.getElementById('flight-number-input');
            if (fnInput) fnInput.value = prefs.flightNumber;
        }
        if (prefs.flightOrigin) {
            const foInput = document.getElementById('flight-origin');
            if (foInput) foInput.value = prefs.flightOrigin;
        }
        if (prefs.flightDestination) {
            const fdInput = document.getElementById('flight-destination');
            if (fdInput) fdInput.value = prefs.flightDestination;
        }
        if (prefs.flightDate) {
            const dateInput = document.getElementById('flight-date');
            if (dateInput) dateInput.value = prefs.flightDate;
        }

        // Restore multi-city legs (if more than the default 1)
        if (prefs.multiCityLegs && prefs.multiCityLegs.length > 1) {
            // Add additional legs
            for (let i = 1; i < prefs.multiCityLegs.length; i++) {
                addLeg();
            }
            // Fill in all legs
            prefs.multiCityLegs.forEach((leg, idx) => {
                const num = idx + 1;
                if (leg.origin) {
                    const el = document.querySelector(`[name="origin_${num}"]`);
                    if (el) el.value = leg.origin;
                }
                if (leg.destination) {
                    const el = document.querySelector(`[name="destination_${num}"]`);
                    if (el) el.value = leg.destination;
                }
                if (leg.date) {
                    const el = document.querySelector(`[name="date_${num}"]`);
                    if (el) el.value = leg.date;
                }
            });
        } else if (prefs.multiCityLegs && prefs.multiCityLegs.length === 1) {
            // First leg only
            const leg = prefs.multiCityLegs[0];
            if (leg.origin) {
                const el = document.querySelector('[name="origin_1"]');
                if (el) el.value = leg.origin;
            }
            if (leg.destination) {
                const el = document.querySelector('[name="destination_1"]');
                if (el) el.value = leg.destination;
            }
            if (leg.date) {
                const el = document.querySelector('[name="date_1"]');
                if (el) el.value = leg.date;
            }
        }

        console.log('Search preferences restored');
    } catch (e) {
        console.warn('Could not restore search preferences:', e);
    }
}

// Update passenger summary text
function updatePassengerSummary() {
    const total = passengers.adults + passengers.children + passengers.infants_seat + passengers.infants_lap;
    document.getElementById('passenger-summary').textContent = total === 1 ? '1 passenger' : `${total} passengers`;
}

// Set minimum dates to today
function setMinDates() {
    const today = new Date().toISOString().split('T')[0];
    document.querySelectorAll('input[type="date"]').forEach(input => {
        input.min = today;
    });
}

// Trip type change handler
function handleTripTypeChange() {
    const tripType = document.getElementById('trip-type').value;
    const singleContainer = document.getElementById('single-flight-container');
    const multiContainer = document.getElementById('multi-city-container');
    const returnDateGroup = document.getElementById('return-date-group');
    const returnDateInput = document.getElementById('return-date');

    if (tripType === 'multi_city') {
        singleContainer.style.display = 'none';
        multiContainer.style.display = 'block';
        // Make multi-city inputs required
        document.querySelectorAll('#multi-city-container input').forEach(i => {
            if (i.type !== 'hidden') i.required = true;
        });
        document.querySelectorAll('#single-flight-container input').forEach(i => i.required = false);
    } else {
        singleContainer.style.display = 'block';
        multiContainer.style.display = 'none';
        // Make single flight inputs required
        document.querySelectorAll('#single-flight-container input:not(#return-date)').forEach(i => i.required = true);
        document.querySelectorAll('#multi-city-container input').forEach(i => i.required = false);

        if (tripType === 'round_trip') {
            returnDateGroup.classList.add('show');
            returnDateInput.required = true;
        } else {
            returnDateGroup.classList.remove('show');
            returnDateInput.required = false;
        }
    }
}

// Passenger menu toggle
function togglePassengerMenu() {
    document.getElementById('passenger-menu').classList.toggle('show');
}

// Close passenger menu when clicking outside
document.addEventListener('click', (e) => {
    const dropdown = document.querySelector('.passenger-dropdown');
    if (dropdown && !dropdown.contains(e.target)) {
        document.getElementById('passenger-menu').classList.remove('show');
    }
});

// Adjust passenger count
function adjustPassenger(type, delta) {
    const newValue = passengers[type] + delta;
    const totalPassengers = passengers.adults + passengers.children + passengers.infants_seat;

    // Validation
    if (type === 'adults' && newValue < 1) return; // At least 1 adult
    if (newValue < 0) return;
    if (type !== 'infants_lap' && totalPassengers + delta > 9) return; // Max 9 passengers
    if (type === 'infants_lap' && newValue > passengers.adults) return; // Lap infants <= adults

    passengers[type] = newValue;

    // Update display
    document.getElementById(`${type}-count`).textContent = newValue;
    document.getElementById(`${type}-input`).value = newValue;
    updatePassengerSummary();
}

// Update passenger summary text
function updatePassengerSummary() {
    const total = passengers.adults + passengers.children + passengers.infants_seat + passengers.infants_lap;
    const text = total === 1 ? '1 passenger' : `${total} passengers`;
    document.getElementById('passenger-summary').textContent = text;
}

// Swap origin and destination
function swapAirports() {
    const originInput = document.getElementById('main-origin');
    const destInput = document.getElementById('main-destination');
    const originDisplay = document.getElementById('display-origin-main');
    const destDisplay = document.getElementById('display-destination-main');

    const tempValue = originInput.value;
    const tempDisplay = originDisplay.textContent;

    originInput.value = destInput.value;
    originDisplay.textContent = destDisplay.textContent;

    destInput.value = tempValue;
    destDisplay.textContent = tempDisplay;
}

function initAutocomplete() {
    document.querySelectorAll('.airport-search').forEach(input => {
        input.addEventListener('input', handleAirportInput);
        input.addEventListener('keydown', handleKeydown);
        input.addEventListener('blur', () => {
            setTimeout(() => hideDropdown(input), 200);
        });
        input.addEventListener('focus', () => {
            if (input.value.length >= 2) handleAirportInput({ target: input });
        });
    });
}

async function handleAirportInput(e) {
    const input = e.target;
    const query = input.value.trim();
    const field = input.dataset.field;
    const leg = input.dataset.leg;
    const dropdown = document.getElementById(`dropdown-${field}-${leg}`);

    if (query.length < 2) {
        hideDropdown(input);
        return;
    }

    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(async () => {
        try {
            const response = await fetch(`/api/airports?q=${encodeURIComponent(query)}`);
            const data = await response.json();

            if (data.airports && data.airports.length > 0) {
                showDropdown(input, data.airports);
            } else {
                hideDropdown(input);
            }
        } catch (err) {
            console.error('Airport search failed:', err);
        }
    }, 150);
}

function showDropdown(input, airports) {
    const field = input.dataset.field;
    const leg = input.dataset.leg;
    const dropdown = document.getElementById(`dropdown-${field}-${leg}`);

    selectedIndex = -1;
    dropdown.innerHTML = airports.map((a, i) => `
        <div class="autocomplete-item" data-code="${a.code}" data-index="${i}">
            <span class="autocomplete-code">${a.code}</span>
            <span class="autocomplete-city">${a.city}</span><br>
            <span class="autocomplete-country">${a.name} - ${a.country}</span>
        </div>
    `).join('');

    dropdown.style.display = 'block';

    dropdown.querySelectorAll('.autocomplete-item').forEach(item => {
        item.addEventListener('click', () => selectAirport(input, item.dataset.code, airports));
    });
}

function hideDropdown(input) {
    const field = input.dataset.field;
    const leg = input.dataset.leg;
    const dropdown = document.getElementById(`dropdown-${field}-${leg}`);
    if (dropdown) dropdown.style.display = 'none';
}

function selectAirport(input, code, airports) {
    const field = input.dataset.field;
    const leg = input.dataset.leg;
    const display = document.getElementById(`display-${field}-${leg}`);

    input.value = code;

    const airport = airports.find(a => a.code === code);
    if (airport && display) {
        display.textContent = `${airport.city}, ${airport.country}`;
    }

    hideDropdown(input);

    // Move to next field
    const nextField = field === 'origin' ? `destination_${leg}` : `date_${leg}`;
    const nextInput = document.querySelector(`[name="${nextField}"]`);
    if (nextInput) nextInput.focus();
}

function handleKeydown(e) {
    const input = e.target;
    const field = input.dataset.field;
    const leg = input.dataset.leg;
    const dropdown = document.getElementById(`dropdown-${field}-${leg}`);
    const items = dropdown.querySelectorAll('.autocomplete-item');

    if (dropdown.style.display === 'none' || items.length === 0) return;

    if (e.key === 'ArrowDown') {
        e.preventDefault();
        selectedIndex = Math.min(selectedIndex + 1, items.length - 1);
        updateSelection(items);
    } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        selectedIndex = Math.max(selectedIndex - 1, 0);
        updateSelection(items);
    } else if (e.key === 'Enter' && selectedIndex >= 0) {
        e.preventDefault();
        const selected = items[selectedIndex];
        if (selected) {
            // Reconstruct airports array from dropdown
            const airports = Array.from(items).map(item => ({
                code: item.dataset.code,
                city: item.querySelector('.autocomplete-city').textContent,
                country: item.querySelector('.autocomplete-country').textContent.split(' - ').pop()
            }));
            selectAirport(input, selected.dataset.code, airports);
        }
    } else if (e.key === 'Escape') {
        hideDropdown(input);
    }
}

function updateSelection(items) {
    items.forEach((item, i) => {
        item.classList.toggle('selected', i === selectedIndex);
        if (i === selectedIndex) item.scrollIntoView({ block: 'nearest' });
    });
}

function addLeg() {
    legCount++;
    const container = document.getElementById('legs-container');
    const legHtml = `
        <div class="leg-card" data-leg="${legCount}">
            <div class="leg-number">${legCount}</div>
            <div class="leg-info">
                <div class="search-row">
                    <div class="form-group airport-input">
                        <label>From</label>
                        <input type="text" name="origin_${legCount}" class="airport-search" data-field="origin" data-leg="${legCount}"
                               placeholder="City or airport code..." autocomplete="off" required>
                        <div class="autocomplete-dropdown" id="dropdown-origin-${legCount}"></div>
                        <div class="airport-display" id="display-origin-${legCount}"></div>
                    </div>
                    <div class="form-group airport-input">
                        <label>To</label>
                        <input type="text" name="destination_${legCount}" class="airport-search" data-field="destination" data-leg="${legCount}"
                               placeholder="City or airport code..." autocomplete="off" required>
                        <div class="autocomplete-dropdown" id="dropdown-destination-${legCount}"></div>
                        <div class="airport-display" id="display-destination-${legCount}"></div>
                    </div>
                    <div class="form-group">
                        <label>Date</label>
                        <input type="date" name="date_${legCount}" required>
                    </div>
                    <button type="button" class="btn btn-secondary" onclick="removeLeg(${legCount})" style="align-self: end;">✕</button>
                </div>
            </div>
        </div>
    `;
    container.insertAdjacentHTML('beforeend', legHtml);
    // Initialize autocomplete on new inputs
    initAutocomplete();
}

function removeLeg(num) {
    document.querySelector(`.leg-card[data-leg="${num}"]`).remove();
}

async function searchFlights(e) {
    e.preventDefault();

    // Save preferences before search (in case of failure)
    saveSearchPreferences();

    const form = document.getElementById('search-form');
    const btn = document.getElementById('search-btn');
    const status = document.getElementById('search-status');

    console.log('Search started');
    btn.disabled = true;
    status.textContent = 'Searching markets...';

    // Show loading screen
    if (window.showLoadingScreen) {
        window.showLoadingScreen('Searching global markets for the best deals...');
    }

    const tripType = document.getElementById('trip-type').value;
    const cabinClass = form.querySelector('[name="cabin_class"]').value;
    const stops = form.querySelector('[name="stops"]').value;
    const flexibleDates = document.getElementById('flexible-dates')?.checked || false;
    const flexDays = parseInt(document.getElementById('flex-days')?.value || '3');

    // Build legs based on trip type
    const legs = [];

    if (tripType === 'multi_city') {
        // Multi-city: collect all leg cards
        document.querySelectorAll('#legs-container .leg-card').forEach(card => {
            const num = card.dataset.leg;
            const origin = form.querySelector(`[name="origin_${num}"]`)?.value?.toUpperCase();
            const dest = form.querySelector(`[name="destination_${num}"]`)?.value?.toUpperCase();
            const date = form.querySelector(`[name="date_${num}"]`)?.value;
            if (origin && dest && date) {
                legs.push({ origin, destination: dest, date });
            }
        });
    } else {
        // One-way or Round-trip
        const origin = document.getElementById('main-origin').value.toUpperCase();
        const destination = document.getElementById('main-destination').value.toUpperCase();
        const departureDate = document.getElementById('departure-date').value;

        legs.push({ origin, destination, date: departureDate });

        if (tripType === 'round_trip') {
            const returnDate = document.getElementById('return-date').value;
            if (returnDate) {
                legs.push({ origin: destination, destination: origin, date: returnDate });
            }
        }
    }

    // Build search options
    const searchOptions = {
        legs,
        name: 'My Search',
        trip_type: tripType,
        passengers: {
            adults: passengers.adults,
            children: passengers.children,
            infants_seat: passengers.infants_seat,
            infants_lap: passengers.infants_lap
        },
        cabin_class: cabinClass,
        stops: stops,
        flexible_dates: flexibleDates,
        flex_days: flexDays
    };

    console.log('Search options:', searchOptions);
    console.log('Legs:', legs);

    if (legs.length === 0) {
        status.textContent = 'Please fill in all fields.';
        btn.disabled = false;
        if (window.hideLoadingScreen) window.hideLoadingScreen();
        return;
    }

    // Validate legs have proper airport codes (3 letters)
    for (const leg of legs) {
        if (!leg.origin || leg.origin.length !== 3) {
            status.textContent = `Invalid origin airport: "${leg.origin || 'empty'}". Please select from the dropdown.`;
            btn.disabled = false;
            if (window.hideLoadingScreen) window.hideLoadingScreen();
            return;
        }
        if (!leg.destination || leg.destination.length !== 3) {
            status.textContent = `Invalid destination airport: "${leg.destination || 'empty'}". Please select from the dropdown.`;
            btn.disabled = false;
            if (window.hideLoadingScreen) window.hideLoadingScreen();
            return;
        }
        if (!leg.date) {
            status.textContent = 'Please select a departure date.';
            btn.disabled = false;
            if (window.hideLoadingScreen) window.hideLoadingScreen();
            return;
        }
    }

    console.log('Validated legs:', legs);

    try {
        const response = await fetch('/api/search/itinerary', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(searchOptions)
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();
        console.log('Search results:', data);

        displayResults(data, searchOptions);
        status.textContent = `Found ${data.summary?.legs_with_deals || 0} deals!`;
    } catch (err) {
        status.textContent = 'Search failed: ' + err.message;
        console.error('Search error:', err);
        document.getElementById('results-container').innerHTML = `
            <div class="card" style="margin-top: 20px; border-left: 4px solid #dc3545;">
                <h3 style="color: #dc3545;">Search Error</h3>
                <p>${err.message}</p>
                <p style="color: #666;">Please try again. Your search preferences have been saved.</p>
            </div>
        `;
    } finally {
        // Always hide loading screen and re-enable button
        if (window.hideLoadingScreen) {
            window.hideLoadingScreen();
        }
        btn.disabled = false;
        console.log('Search completed');
    }
}

function displayResults(data) {
    console.log('displayResults called with:', data);
    const container = document.getElementById('results-container');

    if (!container) {
        console.error('results-container not found!');
        return;
    }

    if (!data || !data.leg_results) {
        console.error('Invalid data - no leg_results:', data);
        container.innerHTML = '<div class="card"><h3>No results found</h3><p>Try adjusting your search criteria.</p></div>';
        return;
    }

    console.log('Rendering', data.leg_results.length, 'leg results');

    let html = `
        <div class="card" style="margin-top: 20px;">
            <h2>Search Results</h2>
            <div class="stats" style="margin-bottom: 20px;">
                <div class="stat-card">
                    <div class="stat-value">${data.summary?.total_legs || 0}</div>
                    <div class="stat-label">Routes</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">${data.summary?.total_flights_found || 0}</div>
                    <div class="stat-label">Flights Found</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">${data.summary?.legs_with_deals || 0}</div>
                    <div class="stat-label">With Arbitrage</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">${typeof data.summary?.markets_checked === 'number' ? data.summary.markets_checked : (data.summary?.markets_checked?.length || 5)}</div>
                    <div class="stat-label">Regions Compared</div>
                </div>
            </div>
    `;

    // Display round-trip info banner
    if (data.is_round_trip || data.summary?.is_round_trip) {
        const isActualRoundTrip = data.is_actual_round_trip || data.summary?.is_actual_round_trip;
        const outboundDate = data.summary?.date || data.leg_results?.[0]?.date || '';
        const returnDate = data.summary?.return_date || data.leg_results?.[0]?.return_date || '';

        html += `
            <div style="background: linear-gradient(135deg, #ff6b35, #ff8c00); padding: 20px; border-radius: 12px; margin-bottom: 20px; color: white;">
                <div style="display: flex; align-items: flex-start; gap: 15px;">
                    <div style="font-size: 32px;">🔄</div>
                    <div style="flex: 1;">
                        <strong style="font-size: 18px; display: block; margin-bottom: 8px;">Round-Trip Packages</strong>
                        <p style="margin: 0; font-size: 14px; line-height: 1.5;">
                            Each price below is the <strong>total round-trip fare</strong> including:
                        </p>
                        <div style="display: flex; gap: 20px; margin-top: 10px; flex-wrap: wrap;">
                            <div style="background: rgba(255,255,255,0.2); padding: 8px 15px; border-radius: 8px;">
                                <span style="font-size: 12px; opacity: 0.9;">OUTBOUND</span>
                                <strong style="display: block;">${outboundDate || 'Departure date'}</strong>
                            </div>
                            <div style="font-size: 20px; display: flex; align-items: center;">↔</div>
                            <div style="background: rgba(255,255,255,0.2); padding: 8px 15px; border-radius: 8px;">
                                <span style="font-size: 12px; opacity: 0.9;">RETURN</span>
                                <strong style="display: block;">${returnDate || 'Return date'}</strong>
                            </div>
                        </div>
                        <p style="margin: 12px 0 0 0; font-size: 13px; opacity: 0.9;">
                            💡 <em>Return flight times determined by airline when you complete booking</em>
                        </p>
                    </div>
                </div>
            </div>
        `;
    }

    // Display proxy-verified savings banner if available
    const proxyResults = data.leg_results?.[0]?.proxy_results;
    if (proxyResults && proxyResults.savings_vs_us > 10) {
        html += `
            <div style="background: linear-gradient(135deg, #28a745, #20c997); padding: 20px; border-radius: 12px; margin-bottom: 20px; color: white;">
                <div style="display: flex; align-items: center; gap: 15px; flex-wrap: wrap;">
                    <div style="font-size: 40px;">🎯</div>
                    <div style="flex: 1;">
                        <h3 style="margin: 0; font-size: 20px;">Google Flights Price Comparison</h3>
                        <p style="margin: 5px 0 0 0; opacity: 0.9;">
                            Same flights, different prices - scraped live from Google Flights via regional proxies
                        </p>
                    </div>
                    <div style="text-align: right;">
                        <div style="font-size: 32px; font-weight: bold;">Save $${proxyResults.savings_vs_us.toFixed(0)}</div>
                        <div style="font-size: 14px; opacity: 0.9;">${proxyResults.savings_pct?.toFixed(0) || 0}% less than your region</div>
                    </div>
                </div>
                <div style="display: flex; gap: 15px; margin-top: 15px; padding-top: 15px; border-top: 1px solid rgba(255,255,255,0.3); flex-wrap: wrap;">
                    <div style="flex: 1; text-align: center; min-width: 150px;">
                        <div style="font-size: 11px; opacity: 0.8; text-transform: uppercase;">📍 Standard Price</div>
                        <div style="font-size: 11px; opacity: 0.7;">What you'd normally pay</div>
                        <div style="font-size: 20px; font-weight: bold; text-decoration: line-through; opacity: 0.8;">$${(proxyResults.savings_vs_us + proxyResults.cheapest_price_usd)?.toFixed(0) || 'N/A'}</div>
                    </div>
                    <div style="flex: 1; text-align: center; min-width: 150px; background: rgba(255,255,255,0.2); border-radius: 8px; padding: 8px;">
                        <div style="font-size: 11px; opacity: 0.8; text-transform: uppercase;">🔥 Phoenix Price</div>
                        <div style="font-size: 11px; opacity: 0.7;">Powered by global price intelligence</div>
                        <div style="font-size: 20px; font-weight: bold;">$${proxyResults.cheapest_price_usd?.toFixed(0) || 'N/A'}</div>
                    </div>
                </div>
            </div>
        `;
    }

    // Display flexible dates comparison if available
    if (data.flexible_dates && data.flexible_dates.dates?.length > 0) {
        const flex = data.flexible_dates;
        const savings = flex.potential_savings || 0;

        html += `
            <div style="background: ${savings > 10 ? '#d4edda' : '#fff5f0'}; padding: 20px; border-radius: 12px; margin-bottom: 20px;">
                <h3 style="margin: 0 0 15px 0; ${savings > 10 ? 'color: #155724;' : ''}">
                    ${savings > 10 ? '💰 Better dates available!' : '📅 Flexible Date Comparison'}
                </h3>
                ${savings > 10 ? `
                    <p style="color: #155724; font-size: 16px; margin-bottom: 15px;">
                        Save <strong>$${savings.toFixed(0)}</strong> by flying on <strong>${flex.cheapest_date.date}</strong> instead!
                    </p>
                ` : ''}
                <div style="display: flex; gap: 10px; flex-wrap: wrap; justify-content: center;">
        `;

        for (const day of flex.dates) {
            const isCheapest = day.date === flex.cheapest_date?.date;
            const isSelected = day.is_selected;

            html += `
                <div style="
                    padding: 12px 16px;
                    border-radius: 8px;
                    text-align: center;
                    min-width: 80px;
                    background: ${isCheapest ? '#28a745' : (isSelected ? '#ff6b35' : 'white')};
                    color: ${isCheapest || isSelected ? 'white' : '#333'};
                    border: 2px solid ${isCheapest ? '#28a745' : (isSelected ? '#ff6b35' : '#ddd')};
                    ${isCheapest ? 'transform: scale(1.05);' : ''}
                ">
                    <div style="font-size: 12px; opacity: 0.8;">${day.day}</div>
                    <div style="font-size: 14px; font-weight: 600;">${day.date.slice(5)}</div>
                    <div style="font-size: 16px; font-weight: bold; margin-top: 4px;">$${day.price_usd?.toFixed(0) || 'N/A'}</div>
                    ${isCheapest ? '<div style="font-size: 10px; margin-top: 2px;">CHEAPEST</div>' : ''}
                    ${isSelected && !isCheapest ? '<div style="font-size: 10px; margin-top: 2px;">Selected</div>' : ''}
                </div>
            `;
        }

        html += `
                </div>
                <p style="text-align: center; margin-top: 15px; color: #666; font-size: 13px;">
                    Prices shown are the lowest found by Phoenix's price engine
                </p>
            </div>
        `;
    }

    // Track total legs for multi-leg validation
    totalLegs = (data.leg_results || []).length;
    selectedFlights = {};  // Reset selections on new search

    for (const leg of (data.leg_results || [])) {
        const hasDeal = leg.deal !== null;
        const allFlights = leg.all_flights || [];
        const deal = leg.deal?.deal || {};
        const legNum = leg.leg;

        // Determine leg label for round-trips
        let legLabel = `Leg ${legNum}`;
        let legIcon = '✈️';
        const isActualRoundTrip = data.is_actual_round_trip || data.summary?.is_actual_round_trip || leg.is_round_trip;
        if (data.is_round_trip || data.summary?.is_round_trip) {
            if (isActualRoundTrip && leg.is_outbound && leg.is_return) {
                // This is an actual round-trip with combined pricing
                legLabel = 'Round-Trip Flight';
                legIcon = '🔄';
            } else if (leg.is_outbound) {
                legLabel = 'Outbound Flight';
                legIcon = '🛫';
            } else if (leg.is_return) {
                legLabel = 'Return Flight';
                legIcon = '🛬';
            }
        }

        // Format date display - show both dates for round-trip
        const dateDisplay = (isActualRoundTrip && leg.return_date)
            ? `${leg.date} → ${leg.return_date}`
            : leg.date;

        // Format route display
        const routeDisplay = leg.route_display || leg.route;

        html += `
            <div style="background: #f8f9fa; padding: 20px; border-radius: 12px; margin-bottom: 20px;" data-leg="${legNum}">
                <div id="leg-${legNum}-header" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; flex-wrap: wrap; gap: 10px;">
                    <div>
                        <h3 style="margin: 0;">${legIcon} ${legLabel}: ${routeDisplay}</h3>
                        <span style="color: #666;">${dateDisplay}</span>
                        ${isActualRoundTrip ? '<span style="background: #ff6b35; color: white; padding: 2px 8px; border-radius: 10px; font-size: 11px; margin-left: 8px;">ROUND-TRIP TOTAL</span>' : ''}
                    </div>
                    <div style="display: flex; align-items: center; gap: 10px;">
                        ${hasDeal ? `<span class="savings-badge">Save up to $${leg.savings?.toFixed(2) || '0'}</span>` : ''}
                    </div>
                </div>
        `;

        // Show all flights with market comparison table
        if (allFlights.length > 0) {
            // Flights already have converted_prices dict with market prices
            const flightList = allFlights.map(f => ({
                airline: f.airline,
                flight_number: f.flight_number,
                departure_time: f.departure_time,
                arrival_time: f.arrival_time,
                duration: f.duration,
                stops: f.stops,
                cheapest_price: f.cheapest_price,
                cheapest_market: 'Phoenix',
                converted_prices: {},  // Scrubbed
                deal: f.deal
            })).sort((a, b) => (a.cheapest_price || 9999) - (b.cheapest_price || 9999));

            // Determine price column header based on trip type
            const priceColHeader = isActualRoundTrip ? 'Best Round-Trip' : 'Best Price';
            const usPriceHeader = isActualRoundTrip ? 'Google US' : 'Google US';

            html += `
                <table class="price-table">
                    <thead>
                        <tr>
                            <th>Flight</th>
                            <th>Time</th>
                            <th>Duration</th>
                            <th>Stops</th>
                            <th>${priceColHeader}</th>
                            <th>Source</th>
                            <th>Normal Price</th>
                            <th>Savings</th>
                            <th>Action</th>
                        </tr>
                    </thead>
                    <tbody>
            `;

            // Show flights
            for (const flight of flightList.slice(0, 10)) {
                const usPrice = flight.deal?.home_price || flight.cheapest_price;
                const cheapestPrice = flight.cheapest_price || usPrice;
                const savings = usPrice - cheapestPrice;
                const savingsPct = usPrice > 0 ? ((savings / usPrice) * 100).toFixed(0) : 0;
                const hasSavings = savings > 5;

                const isExclusive = flight.deal && flight.deal.cheapest_market === 'Phoenix';
                const flightData = encodeURIComponent(JSON.stringify({
                    airline: flight.airline,
                    flight_number: flight.flight_number,
                    departure_time: flight.departure_time,
                    arrival_time: flight.arrival_time,
                    duration: flight.duration,
                    stops: flight.stops,
                    cheapest_price: cheapestPrice,
                    cheapest_market: 'Phoenix',
                    us_price: usPrice,
                    savings: savings,
                    route: leg.route,
                    date: leg.date,
                    return_date: leg.return_date || null,
                    is_round_trip: isActualRoundTrip,
                    price_type: isActualRoundTrip ? 'round_trip_total' : 'one_way',
                    converted_prices: {},
                }));

                const flightRowId = `${(flight.airline || 'unknown').replace(/\\s/g, '_')}_${(flight.flight_number || 'unknown').replace(/\\s/g, '_')}`;

                html += `
                    <tr class="${hasSavings ? 'cheapest' : ''}" data-flight-id="${flightRowId}" data-leg="${legNum}">
                        <td>
                            <strong>${flight.airline || 'Multiple'}</strong>
                            ${flight.flight_number ? `<br><span style="color: #666; font-size: 12px;">${flight.flight_number}</span>` : ''}
                            ${isExclusive ? `<br><span style="background: #ff6b35; color: white; font-size: 10px; padding: 2px 6px; border-radius: 4px;">🔥 Phoenix Exclusive</span>` : ''}
                        </td>
                        <td>${flight.departure_time || 'N/A'} - ${flight.arrival_time || 'N/A'}</td>
                        <td>${flight.duration || 'N/A'}</td>
                        <td>${flight.stops === 0 ? 'Nonstop' : (flight.stops !== undefined ? flight.stops + ' stop' + (flight.stops > 1 ? 's' : '') : 'N/A')}</td>
                        <td style="font-weight: bold; color: #28a745;">$${cheapestPrice?.toFixed(0) || 'N/A'}</td>
                        <td><span class="market-tag">Phoenix</span></td>
                        <td>${isExclusive ? '<span style="color: #fff; font-size: 11px;">Not available</span>' : `$${usPrice?.toFixed(0) || 'N/A'}`}</td>
                        <td>${hasSavings ? `<span style="color: #28a745; font-weight: bold;">$${savings.toFixed(0)} (${savingsPct}%)</span>` : (isExclusive ? `<span style="color: #ff6b35; font-weight: bold;">Exclusive Deal</span>` : '<span style="color: #fff;">-</span>')}</td>
                        <td>
                            <button class="btn select-flight-btn" onclick="selectFlightForLeg(${legNum}, '${flightData}')" style="padding: 8px 16px; font-size: 12px;">
                                ${hasSavings || isExclusive ? 'Book & Save' : 'Select'}
                            </button>
                        </td>
                    </tr>
                `;
            }

            html += `
                    </tbody>
                </table>
            `;

            // Market breakdown removed — Phoenix price intelligence is proprietary

        } else if (hasDeal) {
            // Fallback to old deal display if no all_flights data
            html += `
                <div style="margin: 10px 0;">
                    <strong>${leg.deal.airline || 'Multiple Airlines'}</strong>
                    ${leg.deal.flight_number ? `<span style="color: #666;">${leg.deal.flight_number}</span>` : ''}
                </div>
                <div style="display: flex; gap: 20px; margin: 15px 0;">
                    <div>
                        <span style="color: #666;">Normal price:</span>
                        <span style="text-decoration: line-through; color: #fff;">$${deal.home_price?.toFixed(2) || 'N/A'}</span>
                    </div>
                    <div>
                        <span style="color: #666;">Our price:</span>
                        <span style="color: #28a745; font-weight: bold;">$${deal.arbitrage_price?.toFixed(2) || 'N/A'}</span>
                    </div>
                </div>
                <span class="market-tag">Book via Phoenix</span>
            `;
        } else {
            html += `
                <p style="color: #666; margin: 15px 0;">No flights found for this route. Try different dates or airports.</p>
            `;
        }

        html += `</div>`;
    }

    // Google Flights link
    if (data.leg_results?.length > 0) {
        const firstLeg = data.leg_results[0];
        const route = firstLeg.route?.split(' → ') || ['', ''];
        const googleUrl = `https://www.google.com/travel/flights?q=${route[0]}%20to%20${route[1]}%20${firstLeg.date}`;
        html += `
            <p style="margin-top: 15px; text-align: center;">
                <a href="${googleUrl}" target="_blank" class="google-link">Compare on Google Flights →</a>
            </p>
        `;
    }

    html += `</div>`;

    // Add checkout panel placeholder
    html += `
        <div id="checkout-panel" class="checkout-panel" style="display: none;">
            <div class="card" style="border: 3px solid #ff6b35; background: #ffffff; color: #1a1a2e;">
                <div style="display: flex; justify-content: space-between; align-items: start;">
                    <h2 style="margin: 0 0 20px 0; display: flex; align-items: center; gap: 10px; color: #1a1a2e;">
                        <span style="font-size: 28px;">✈️</span> Flight Selected
                    </h2>
                    <button onclick="closeCheckout()" style="background: none; border: none; font-size: 24px; cursor: pointer; color: #333;">×</button>
                </div>

                <div id="selected-flight-details" style="color: #1a1a2e;"></div>

                <div style="background: #f8f9fa; padding: 20px; border-radius: 12px; margin: 20px 0; color: #1a1a2e;">
                    <h3 style="margin: 0 0 15px 0; color: #1a1a2e;">Price Breakdown</h3>
                    <div id="price-breakdown"></div>
                </div>

                <div style="text-align: center; margin-top: 20px;">
                    <button onclick="proceedToPayment()" class="btn" style="font-size: 18px; padding: 15px 40px; background: linear-gradient(135deg, #ff6b35, #ff8c00); color: #fff; border: none; border-radius: 8px; cursor: pointer; font-weight: 600;">
                        Proceed to Checkout →
                    </button>
                    <p style="color: #555; font-size: 13px; margin-top: 10px;">
                        You'll be redirected to complete your booking
                    </p>
                </div>
            </div>
        </div>
    `;

    container.innerHTML = html;
}

// Multi-leg flight selection storage
let selectedFlights = {};  // { leg1: flight, leg2: flight, ... }
let totalLegs = 0;

// Flight selection handler - now supports multi-leg
function selectFlightForLeg(legNum, encodedData) {
    try {
        const flight = JSON.parse(decodeURIComponent(encodedData));
        flight.leg = legNum;
        selectedFlights[legNum] = flight;

        console.log('Flight selected for leg', legNum, ':', flight);
        console.log('Selected flights now:', selectedFlights);

        // Update the button to show selected state
        updateLegSelectionUI(legNum, flight);

        // Update checkout panel
        updateCheckoutPanel();

    } catch (err) {
        console.error('Error selecting flight:', err);
        console.error('Encoded data was:', encodedData);
        alert('Error selecting flight. Please try again.');
    }
}

// Legacy single-flight selection (calls multi-leg with leg 1)
function selectFlight(encodedData) {
    selectFlightForLeg(1, encodedData);
}

// Update UI to show which flight is selected for a leg
function updateLegSelectionUI(legNum, flight) {
    // Remove selected class from all rows in this leg
    document.querySelectorAll(`[data-leg="${legNum}"] tr`).forEach(row => {
        row.classList.remove('selected-flight');
    });

    // Add selected class to the selected flight's row
    const flightId = `${flight.airline}_${flight.flight_number}`.replace(/\\s/g, '_');
    const selectedRow = document.querySelector(`[data-flight-id="${flightId}"][data-leg="${legNum}"]`);
    if (selectedRow) {
        selectedRow.classList.add('selected-flight');
    }

    // Update the leg header to show selection
    const legHeader = document.querySelector(`#leg-${legNum}-header`);
    if (legHeader) {
        const existingBadge = legHeader.querySelector('.leg-selected-badge');
        if (existingBadge) existingBadge.remove();

        const badge = document.createElement('span');
        badge.className = 'leg-selected-badge';
        badge.innerHTML = `✓ ${flight.airline} selected`;
        badge.style.cssText = 'background: #28a745; color: white; padding: 4px 10px; border-radius: 12px; font-size: 12px; margin-left: 10px;';
        legHeader.appendChild(badge);
    }
}

// Update the checkout panel with all selected flights
function updateCheckoutPanel() {
    console.log('updateCheckoutPanel called with selectedFlights:', selectedFlights);

    const panel = document.getElementById('checkout-panel');
    const selectedCount = Object.keys(selectedFlights).length;

    console.log('Selected count:', selectedCount);

    if (selectedCount === 0) {
        panel.style.display = 'none';
        return;
    }

    panel.style.display = 'block';

    // Calculate totals across all selected flights
    let totalUsPrice = 0;
    let totalBestPrice = 0;
    let totalSavings = 0;
    let totalServiceFee = 0;

    // Build flight details HTML for all selected legs
    let detailsHtml = '';

    // Sort by leg number
    const sortedLegs = Object.keys(selectedFlights).sort((a, b) => a - b);

    for (const legNum of sortedLegs) {
        const flight = selectedFlights[legNum];
        const hasSavings = flight.savings > 5;
        const legServiceFee = hasSavings ? Math.min(flight.savings * 0.25, 50) : 4.99;

        totalUsPrice += flight.us_price || flight.cheapest_price;
        totalBestPrice += flight.cheapest_price;
        totalSavings += flight.savings || 0;
        totalServiceFee += legServiceFee;

        // Format date display for round-trip vs one-way
        const isRoundTrip = flight.is_round_trip || flight.price_type === 'round_trip_total';
        const dateDisplay = (isRoundTrip && flight.return_date)
            ? `${flight.date} → ${flight.return_date}`
            : flight.date;
        const priceLabel = isRoundTrip ? 'Round-trip price' : 'Best price';

        // Build the details HTML
        if (isRoundTrip) {
            // Round-trip display with separate outbound/return sections
            detailsHtml += `
                <div style="background: #f8f9fa; padding: 20px; border-radius: 12px; margin-bottom: 15px; color: #1a1a2e; border: 1px solid #e0e0e0;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                        <h4 style="margin: 0; color: #1a1a2e; font-size: 18px;">
                            🔄 Round-Trip: ${flight.route || 'Flight'}
                        </h4>
                        <span style="background: #ff6b35; color: white; padding: 4px 12px; border-radius: 15px; font-size: 11px; font-weight: 600;">INCLUDES BOTH FLIGHTS</span>
                    </div>

                    <!-- Outbound Flight -->
                    <div style="background: #fff; padding: 15px; border-radius: 8px; margin-bottom: 10px; border-left: 4px solid #ff6b35;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                            <span style="font-weight: 600; color: #ff6b35;">✈️ OUTBOUND</span>
                            <span style="color: #555; font-size: 14px;">${flight.date || 'Departure date'}</span>
                        </div>
                        <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px;">
                            <div>
                                <p style="color: #fff; margin: 0; font-size: 11px; text-transform: uppercase;">Airline</p>
                                <p style="font-weight: 600; margin: 2px 0 0 0; color: #1a1a2e;">${flight.airline || 'Multiple'}</p>
                            </div>
                            <div>
                                <p style="color: #fff; margin: 0; font-size: 11px; text-transform: uppercase;">Departure</p>
                                <p style="font-weight: 600; margin: 2px 0 0 0; color: #1a1a2e;">${flight.departure_time || 'TBD'}</p>
                            </div>
                            <div>
                                <p style="color: #fff; margin: 0; font-size: 11px; text-transform: uppercase;">Duration</p>
                                <p style="font-weight: 600; margin: 2px 0 0 0; color: #1a1a2e;">${flight.duration || 'N/A'}</p>
                            </div>
                        </div>
                    </div>

                    <!-- Return Flight -->
                    <div style="background: #fff; padding: 15px; border-radius: 8px; margin-bottom: 15px; border-left: 4px solid #28a745;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                            <span style="font-weight: 600; color: #28a745;">✈️ RETURN</span>
                            <span style="color: #555; font-size: 14px;">${flight.return_date || 'Return date'}</span>
                        </div>
                        <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px;">
                            <div>
                                <p style="color: #fff; margin: 0; font-size: 11px; text-transform: uppercase;">Airline</p>
                                <p style="font-weight: 600; margin: 2px 0 0 0; color: #1a1a2e;">${flight.airline || 'Multiple'}</p>
                            </div>
                            <div>
                                <p style="color: #fff; margin: 0; font-size: 11px; text-transform: uppercase;">Departure</p>
                                <p style="font-weight: 600; margin: 2px 0 0 0; color: #1a1a2e;">Confirmed at booking</p>
                            </div>
                            <div>
                                <p style="color: #fff; margin: 0; font-size: 11px; text-transform: uppercase;">Duration</p>
                                <p style="font-weight: 600; margin: 2px 0 0 0; color: #1a1a2e;">~${flight.duration || 'Similar'}</p>
                            </div>
                        </div>
                    </div>

                    <div style="display: flex; justify-content: space-between; align-items: center; padding-top: 12px; border-top: 2px solid #e0e0e0;">
                        <div>
                            <span style="color: #555; font-size: 13px;">Total round-trip via</span>
                            <span class="market-tag" style="margin-left: 8px;">Phoenix</span>
                        </div>
                        <span style="font-size: 24px; font-weight: bold; color: #28a745;">$${flight.cheapest_price?.toFixed(2) || 'N/A'}</span>
                    </div>
                </div>
            `;
        } else {
            // One-way display
            detailsHtml += `
                <div style="background: #f8f9fa; padding: 20px; border-radius: 12px; margin-bottom: 15px; color: #1a1a2e; border: 1px solid #e0e0e0;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                        <h4 style="margin: 0; color: #1a1a2e; font-size: 18px;">
                            ✈️ ${flight.route || 'Flight Details'}
                        </h4>
                    </div>
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-bottom: 15px;">
                        <div>
                            <p style="color: #777; margin: 0 0 4px 0; font-size: 12px; text-transform: uppercase; font-weight: 600;">Airline</p>
                            <p style="font-size: 16px; font-weight: bold; margin: 0; color: #1a1a2e;">${flight.airline || 'Multiple Airlines'}</p>
                            ${flight.flight_number ? `<p style="font-size: 13px; color: #555; margin: 2px 0 0 0;">${flight.flight_number}</p>` : ''}
                        </div>
                        <div>
                            <p style="color: #777; margin: 0 0 4px 0; font-size: 12px; text-transform: uppercase; font-weight: 600;">Date</p>
                            <p style="font-size: 16px; font-weight: 600; margin: 0; color: #1a1a2e;">${flight.date || 'N/A'}</p>
                        </div>
                        <div>
                            <p style="color: #777; margin: 0 0 4px 0; font-size: 12px; text-transform: uppercase; font-weight: 600;">Departure</p>
                            <p style="font-size: 16px; margin: 0; color: #1a1a2e;">${flight.departure_time || 'See booking'}</p>
                        </div>
                        <div>
                            <p style="color: #777; margin: 0 0 4px 0; font-size: 12px; text-transform: uppercase; font-weight: 600;">Arrival</p>
                            <p style="font-size: 16px; margin: 0; color: #1a1a2e;">${flight.arrival_time || 'See booking'}</p>
                        </div>
                        <div>
                            <p style="color: #777; margin: 0 0 4px 0; font-size: 12px; text-transform: uppercase; font-weight: 600;">Duration</p>
                            <p style="font-size: 16px; margin: 0; color: #1a1a2e;">${flight.duration || 'N/A'}</p>
                        </div>
                        <div>
                            <p style="color: #777; margin: 0 0 4px 0; font-size: 12px; text-transform: uppercase; font-weight: 600;">Stops</p>
                            <p style="font-size: 16px; margin: 0; color: #1a1a2e;">${flight.stops === 0 ? 'Nonstop' : (flight.stops ? flight.stops + ' stop(s)' : 'N/A')}</p>
                        </div>
                    </div>
                    <div style="display: flex; justify-content: space-between; align-items: center; padding-top: 12px; border-top: 2px solid #e0e0e0;">
                        <div>
                            <span style="color: #555; font-size: 13px;">Best price via</span>
                            <span class="market-tag" style="margin-left: 8px;">Phoenix</span>
                        </div>
                        <span style="font-size: 24px; font-weight: bold; color: #28a745;">$${flight.cheapest_price?.toFixed(2) || 'N/A'}</span>
                    </div>
                </div>
            `;
        }
    }

    console.log('Setting flight details HTML:', detailsHtml.substring(0, 200) + '...');
    const detailsContainer = document.getElementById('selected-flight-details');
    if (detailsContainer) {
        detailsContainer.innerHTML = detailsHtml;
    } else {
        console.error('selected-flight-details element not found!');
    }

    // Build price breakdown
    const finalPrice = totalBestPrice + totalServiceFee;
    const netSavings = totalSavings - totalServiceFee;

    let priceHtml = '';

    if (sortedLegs.length > 1) {
        // Multi-leg summary
        priceHtml += `
            <div style="background: #f0f0f0; padding: 12px; border-radius: 8px; margin-bottom: 15px; color: #1a1a2e;">
                <strong>${sortedLegs.length} flights selected</strong>
                <span style="float: right;">${sortedLegs.map(l => `Leg ${l}`).join(' + ')}</span>
            </div>
        `;
    }

    priceHtml += `
        <div class="price-row" style="display: flex; justify-content: space-between; padding: 10px 0; border-bottom: 1px solid #ddd; color: #333;">
            <span>US Market Total</span>
            <span style="text-decoration: ${totalSavings > 5 ? 'line-through' : 'none'}; color: ${totalSavings > 5 ? '#888' : '#1a1a2e'};">$${totalUsPrice.toFixed(2)}</span>
        </div>
    `;

    if (totalSavings > 5) {
        priceHtml += `
            <div class="price-row" style="display: flex; justify-content: space-between; padding: 10px 0; border-bottom: 1px solid #ddd; color: #333;">
                <span>Best Price (via optimal markets)</span>
                <span style="color: #28a745; font-weight: bold;">$${totalBestPrice.toFixed(2)}</span>
            </div>
            <div class="price-row" style="display: flex; justify-content: space-between; padding: 10px 0; border-bottom: 1px solid #ddd; color: #28a745;">
                <span>Total Savings</span>
                <span style="font-weight: bold;">-$${totalSavings.toFixed(2)} (${((totalSavings / totalUsPrice) * 100).toFixed(0)}%)</span>
            </div>
        `;
    }

    priceHtml += `
        <div class="price-row" style="display: flex; justify-content: space-between; padding: 10px 0; border-bottom: 1px solid #ddd; color: #333;">
            <span>Service Fee</span>
            <span>$${totalServiceFee.toFixed(2)}</span>
        </div>
        <div class="price-row" style="display: flex; justify-content: space-between; padding: 15px 0; font-size: 22px; font-weight: bold; color: #1a1a2e;">
            <span>Total</span>
            <span style="color: #ff6b35;">$${finalPrice.toFixed(2)}</span>
        </div>
    `;

    if (netSavings > 0) {
        priceHtml += `
            <div style="background: #d4edda; color: #155724; padding: 12px; border-radius: 8px; text-align: center; margin-top: 10px;">
                <strong>🎉 You're saving $${netSavings.toFixed(2)} compared to booking directly!</strong>
            </div>
        `;
    }

    // Show warning if not all legs are selected
    if (totalLegs > 0 && selectedCount < totalLegs) {
        priceHtml += `
            <div style="background: #fff3cd; color: #856404; padding: 12px; border-radius: 8px; text-align: center; margin-top: 10px;">
                <strong>⚠️ Select flights for all ${totalLegs} legs to complete your booking</strong>
            </div>
        `;
    }

    document.getElementById('price-breakdown').innerHTML = priceHtml;

    // Scroll to checkout panel
    panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function closeCheckout() {
    const panel = document.getElementById('checkout-panel');
    panel.style.display = 'none';
    selectedFlights = {};

    // Remove all selection badges
    document.querySelectorAll('.leg-selected-badge').forEach(b => b.remove());
    document.querySelectorAll('.selected-flight').forEach(r => r.classList.remove('selected-flight'));
}

function removeFlightFromCheckout(legNum) {
    delete selectedFlights[legNum];

    // Remove selection UI for this leg
    const legHeader = document.querySelector(`#leg-${legNum}-header`);
    if (legHeader) {
        const badge = legHeader.querySelector('.leg-selected-badge');
        if (badge) badge.remove();
    }

    updateCheckoutPanel();
}

function proceedToPayment() {
    const selectedCount = Object.keys(selectedFlights).length;

    if (selectedCount === 0) {
        alert('Please select at least one flight.');
        return;
    }

    // Check if all legs are selected for multi-leg trips
    if (totalLegs > 1 && selectedCount < totalLegs) {
        const proceed = confirm(`You've only selected ${selectedCount} of ${totalLegs} flights. Continue anyway?`);
        if (!proceed) return;
    }

    // Calculate totals
    let totalBestPrice = 0;
    let totalSavings = 0;
    let totalServiceFee = 0;
    const flights = [];

    for (const legNum of Object.keys(selectedFlights).sort((a, b) => a - b)) {
        const flight = selectedFlights[legNum];
        const hasSavings = flight.savings > 5;
        const legServiceFee = hasSavings ? Math.min(flight.savings * 0.25, 50) : 4.99;

        totalBestPrice += flight.cheapest_price;
        totalSavings += flight.savings || 0;
        totalServiceFee += legServiceFee;

        flights.push({
            leg: legNum,
            airline: flight.airline,
            flight_number: flight.flight_number,
            route: flight.route,
            date: flight.date,
            cheapest_market: 'Phoenix',
            cheapest_price: flight.cheapest_price,
            us_price: flight.us_price,
            savings: flight.savings
        });
    }

    const totalPrice = totalBestPrice + totalServiceFee;

    // Store flights in session storage
    sessionStorage.setItem('selectedFlights', JSON.stringify(flights));

    // Create combined deal data
    const dealData = {
        flights: flights,
        is_multi_leg: flights.length > 1,
        total_cheapest_price: totalBestPrice,
        total_us_price: flights.reduce((sum, f) => sum + (f.us_price || f.cheapest_price), 0),
        total_savings: totalSavings,
        service_fee: totalServiceFee,
        total_price: totalPrice,
        // For single flights, include legacy fields
        airline: flights[0]?.airline,
        flight_number: flights[0]?.flight_number,
        route: flights.map(f => f.route).join(' | '),
        date: flights.map(f => f.date).join(', '),
        cheapest_market: 'Phoenix',
        cheapest_price: totalBestPrice,
        us_price: flights.reduce((sum, f) => sum + (f.us_price || f.cheapest_price), 0),
        savings: totalSavings
    };

    // Show loading screen
    if (window.showLoadingScreen) {
        window.showLoadingScreen('Preparing your booking...');
    }

    // Create deal and redirect to payment
    fetch('/api/deals/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(dealData)
    })
    .then(response => response.json())
    .then(data => {
        if (window.hideLoadingScreen) window.hideLoadingScreen();

        if (data.deal_id) {
            // Use save-deal route which handles both guests and logged-in users
            window.location.href = '/save-deal/' + data.deal_id;
        } else if (data.error) {
            alert('Error: ' + data.error);
        } else {
            // Fallback: show payment options in modal
            showPaymentModal(dealData);
        }
    })
    .catch(err => {
        if (window.hideLoadingScreen) window.hideLoadingScreen();
        console.error('Error creating deal:', err);
        // Fallback: show payment options
        showPaymentModal(dealData);
    });
}

function showPaymentModal(dealData) {
    const modal = document.createElement('div');
    modal.className = 'payment-modal';
    modal.innerHTML = `
        <div class="payment-modal-overlay" onclick="closePaymentModal()"></div>
        <div class="payment-modal-content">
            <button class="payment-modal-close" onclick="closePaymentModal()">×</button>
            <h2 style="margin: 0 0 20px 0;">💳 Choose Payment Method</h2>

            <div style="background: #f8f9fa; padding: 15px; border-radius: 8px; margin-bottom: 20px;">
                <p style="margin: 0;"><strong>${dealData.airline}</strong> ${dealData.flight_number || ''}</p>
                <p style="margin: 5px 0; color: #666;">${dealData.route} • ${dealData.date}</p>
                <p style="margin: 10px 0 0 0; font-size: 24px; font-weight: bold; color: #ff6b35;">$${dealData.total_price.toFixed(2)}</p>
            </div>

            <div class="payment-options">
                <button onclick="payWithCard()" class="payment-option-btn">
                    <span class="payment-icon">💳</span>
                    <span>Credit/Debit Card</span>
                </button>
                <button onclick="payWithXRP()" class="payment-option-btn">
                    <span class="payment-icon">💎</span>
                    <span>XRP / RLUSD</span>
                </button>
                <button onclick="payWithCrypto()" class="payment-option-btn">
                    <span class="payment-icon">🪙</span>
                    <span>Crypto (BTC, ETH)</span>
                </button>
            </div>

            <p style="text-align: center; color: #666; font-size: 13px; margin-top: 20px;">
                After payment, you'll receive booking instructions via email
            </p>
        </div>
    `;
    document.body.appendChild(modal);
}

function closePaymentModal() {
    const modal = document.querySelector('.payment-modal');
    if (modal) modal.remove();
}

function payWithCard() {
    alert('Card payment integration coming soon! For now, please use XRP or contact support.');
}

function payWithXRP() {
    closePaymentModal();
    if (selectedFlight) {
        const serviceFee = selectedFlight.savings > 5 ? Math.min(selectedFlight.savings * 0.25, 50) : 4.99;
        window.location.href = '/pay/xrp?amount=' + (selectedFlight.cheapest_price + serviceFee).toFixed(2) +
            '&flight=' + encodeURIComponent(selectedFlight.airline + ' ' + selectedFlight.route);
    }
}

function payWithCrypto() {
    alert('Crypto payment via Coinbase Commerce coming soon!');
}

// Tab switching
function switchTab(tab) {
    document.querySelectorAll('.search-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));

    document.querySelector(`[onclick="switchTab('${tab}')"]`).classList.add('active');
    document.getElementById(`tab-${tab}`).classList.add('active');

    // Clear results when switching tabs
    document.getElementById('results-container').innerHTML = '';
    document.getElementById('import-results-container').innerHTML = '';
    document.getElementById('calendar-results-container').innerHTML = '';
    document.getElementById('flight-results-container').innerHTML = '';

    // Close checkout panel when switching tabs
    const checkoutPanel = document.getElementById('checkout-panel');
    if (checkoutPanel) checkoutPanel.style.display = 'none';
}

// Import itinerary functions
let importFlightCount = 1;

function addImportFlight() {
    const container = document.getElementById('import-flights-container');
    const index = importFlightCount;

    const html = `
        <div class="leg-card import-flight-entry" data-index="${index}">
            <div class="leg-header">
                <div class="leg-number">${index + 1}</div>
                <span style="color: #666; font-size: 14px;">Flight ${index + 1}</span>
                <button type="button" class="remove-flight-btn" onclick="removeImportFlight(${index})" style="margin-left: auto; background: none; border: none; color: #dc3545; cursor: pointer; font-size: 18px;" title="Remove flight">×</button>
            </div>
            <div class="search-row">
                <div class="form-group">
                    <label>Flight Number</label>
                    <input type="text" name="flight_${index}" class="import-flight-number" placeholder="e.g., AA 123" style="text-transform: uppercase;">
                </div>
                <div class="form-group airport-input">
                    <label>From</label>
                    <input type="text" name="origin_${index}" class="airport-search import-origin" data-field="import_origin" data-leg="import${index}" placeholder="LAX" autocomplete="off">
                    <div class="autocomplete-dropdown" id="dropdown-import_origin-import${index}"></div>
                </div>
                <div class="form-group airport-input">
                    <label>To</label>
                    <input type="text" name="destination_${index}" class="airport-search import-destination" data-field="import_destination" data-leg="import${index}" placeholder="JFK" autocomplete="off">
                    <div class="autocomplete-dropdown" id="dropdown-import_destination-import${index}"></div>
                </div>
                <div class="form-group" style="max-width: 160px;">
                    <label>Date</label>
                    <input type="date" name="date_${index}" class="import-date">
                </div>
            </div>
        </div>
    `;

    container.insertAdjacentHTML('beforeend', html);
    importFlightCount++;

    // Re-init autocomplete for new fields
    initAutocomplete();
}

function removeImportFlight(index) {
    const entry = document.querySelector(`.import-flight-entry[data-index="${index}"]`);
    if (entry && document.querySelectorAll('.import-flight-entry').length > 1) {
        entry.remove();
        updateImportFlightNumbers();
    }
}

function updateImportFlightNumbers() {
    document.querySelectorAll('.import-flight-entry').forEach((entry, i) => {
        entry.querySelector('.leg-number').textContent = i + 1;
        entry.querySelector('.leg-header span').textContent = `Flight ${i + 1}`;
    });
}

// Parse itinerary text to extract flights
function parseItineraryText(text) {
    const flights = [];

    // Common patterns in booking confirmations
    const patterns = [
        // Pattern: "AA 123 LAX-JFK Mar 15, 2026" or "AA123 LAX to JFK 2026-03-15"
        /([A-Z]{2})\\s*(\\d{1,4})\\s+([A-Z]{3})\\s*[-→to]+\\s*([A-Z]{3})\\s+(\\d{4}-\\d{2}-\\d{2}|\\w+\\s+\\d{1,2},?\\s+\\d{4})/gi,
        // Pattern: "Flight: AA 123" with separate lines for route and date
        /Flight[:\\s]+([A-Z]{2})\\s*(\\d{1,4})/gi,
    ];

    // Try first pattern
    const regex1 = /([A-Z]{2})\\s*(\\d{1,4})\\s+([A-Z]{3})\\s*[-→to]+\\s*([A-Z]{3})\\s+(\\d{4}-\\d{2}-\\d{2}|\\w+\\s+\\d{1,2},?\\s*\\d{4})/gi;
    let match;
    while ((match = regex1.exec(text)) !== null) {
        flights.push({
            flight_number: match[1] + ' ' + match[2],
            origin: match[3],
            destination: match[4],
            date: parseDate(match[5])
        });
    }

    // If no matches, try simpler extraction
    if (flights.length === 0) {
        // Look for flight numbers
        const flightNums = text.match(/[A-Z]{2}\\s*\\d{1,4}/g) || [];
        const airports = text.match(/\\b[A-Z]{3}\\b/g) || [];
        const dates = text.match(/\\d{4}-\\d{2}-\\d{2}|\\w+\\s+\\d{1,2},?\\s*\\d{4}/g) || [];

        if (flightNums.length > 0 && airports.length >= 2) {
            flights.push({
                flight_number: flightNums[0].replace(/\\s+/g, ' '),
                origin: airports[0],
                destination: airports[1],
                date: dates[0] ? parseDate(dates[0]) : ''
            });
        }
    }

    return flights;
}

function parseDate(dateStr) {
    if (!dateStr) return '';

    // If already in YYYY-MM-DD format
    if (/^\\d{4}-\\d{2}-\\d{2}$/.test(dateStr)) {
        return dateStr;
    }

    // Parse "Mar 15, 2026" or "March 15 2026" format
    try {
        const date = new Date(dateStr);
        if (!isNaN(date)) {
            return date.toISOString().split('T')[0];
        }
    } catch (e) {}

    return '';
}

async function compareImportedItinerary(e) {
    e.preventDefault();

    const btn = document.getElementById('import-search-btn');
    const status = document.getElementById('import-search-status');
    const container = document.getElementById('import-results-container');

    btn.disabled = true;
    status.textContent = 'Searching across markets... This may take a moment.';
    container.innerHTML = '';

    // Get flights from either text or manual entry
    let flights = [];
    const itineraryText = document.getElementById('itinerary-text').value.trim();

    if (itineraryText) {
        // Parse from pasted text
        flights = parseItineraryText(itineraryText);
        if (flights.length === 0) {
            status.textContent = 'Could not parse itinerary. Please use manual entry.';
            btn.disabled = false;
            return;
        }
    } else {
        // Get from manual entry
        document.querySelectorAll('.import-flight-entry').forEach(entry => {
            const flightNum = entry.querySelector('.import-flight-number')?.value.trim().toUpperCase();
            const origin = entry.querySelector('.import-origin')?.value.trim().toUpperCase();
            const destination = entry.querySelector('.import-destination')?.value.trim().toUpperCase();
            const date = entry.querySelector('.import-date')?.value;

            if (flightNum && origin && destination && date) {
                flights.push({
                    flight_number: flightNum,
                    origin: origin,
                    destination: destination,
                    date: date
                });
            }
        });
    }

    if (flights.length === 0) {
        status.textContent = 'Please enter at least one flight.';
        btn.disabled = false;
        return;
    }

    // Get selected markets
    const selectedMarkets = [];
    document.querySelectorAll('input[name="markets"]:checked').forEach(cb => {
        selectedMarkets.push(cb.value);
    });

    if (selectedMarkets.length === 0) {
        status.textContent = 'Please select at least one market to compare.';
        btn.disabled = false;
        return;
    }

    try {
        const response = await fetch('/api/search/compare-itinerary', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                flights: flights,
                markets: selectedMarkets
            })
        });

        const data = await response.json();

        if (data.error) {
            status.textContent = data.error;
        } else {
            displayImportResults(data);
            status.textContent = `Compared ${data.flights_compared} flights across ${typeof data.markets_checked === 'number' ? data.markets_checked : (data.markets_checked?.length || 5)} regions`;
        }
    } catch (err) {
        status.textContent = 'Search failed: ' + err.message;
        console.error(err);
    }

    btn.disabled = false;
}

function displayImportResults(data) {
    const container = document.getElementById('import-results-container');

    if (!data.results || data.results.length === 0) {
        container.innerHTML = `
            <div class="card" style="margin-top: 20px;">
                <h2>No Results</h2>
                <p style="color: #666;">Could not find pricing for these flights. Please verify the flight numbers and dates.</p>
            </div>
        `;
        return;
    }

    let totalSavings = 0;
    let html = `
        <div class="card" style="margin-top: 20px;">
            <h2>Price Comparison Results</h2>
            <p style="color: #666; margin-bottom: 20px;">
                Searched ${data.flights_compared} flights across ${typeof data.markets_checked === 'number' ? data.markets_checked : (data.markets_checked?.length || 5)} regions via Phoenix price engine
            </p>
    `;

    for (const flight of data.results) {
        const hasPrices = flight.market_prices && Object.keys(flight.market_prices).length > 0;
        const savings = flight.savings_usd || 0;
        totalSavings += savings;

        html += `
            <div style="background: #f8f9fa; padding: 20px; border-radius: 12px; margin-bottom: 20px; ${savings > 10 ? 'border: 2px solid #28a745;' : ''}">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                    <div>
                        <h3 style="margin: 0;">${flight.flight_number}</h3>
                        <span style="color: #666;">${flight.origin} → ${flight.destination} | ${flight.date}</span>
                    </div>
                    ${savings > 0 ? `<span class="savings-badge">Save $${savings.toFixed(2)}</span>` : ''}
                </div>
        `;

        if (hasPrices) {
            // Sort markets by price
            const sortedMarkets = Object.entries(flight.market_prices)
                .sort((a, b) => a[1].price_usd - b[1].price_usd);

            const cheapestMarket = sortedMarkets[0][0];
            const cheapestPrice = sortedMarkets[0][1].price_usd;

            html += `
                <table class="price-table">
                    <thead>
                        <tr>
                            <th>Market</th>
                            <th>Local Price</th>
                            <th>USD Equivalent</th>
                            <th>vs Cheapest</th>
                        </tr>
                    </thead>
                    <tbody>
            `;

            for (const [market, priceData] of sortedMarkets) {
                const diff = priceData.price_usd - cheapestPrice;
                const isCheapest = diff < 0.01;

                html += `
                    <tr class="${isCheapest ? 'cheapest' : ''}">
                        <td><span class="market-tag">Region ${market === 'US' ? '(Your area)' : ''}</span></td>
                        <td>$${priceData.price_usd?.toFixed(2) || 'N/A'}</td>
                        <td>$${priceData.price_usd?.toFixed(2) || 'N/A'}</td>
                        <td>${isCheapest ? '<strong>PHOENIX PRICE</strong>' : `+$${diff.toFixed(2)}`}</td>
                    </tr>
                `;
            }

            html += `
                    </tbody>
                </table>
                <div style="margin-top: 15px; display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">
                    <p style="margin: 0; color: #155724;">
                        <strong>Best option:</strong> Book via <span class="market-tag">Phoenix</span> for $${cheapestPrice.toFixed(2)}
                    </p>
                    ${savings > 5 ? `
                        <a href="/p2p/book?origin=${encodeURIComponent(flight.origin)}&destination=${encodeURIComponent(flight.destination)}&date=${encodeURIComponent(flight.date)}&flight=${encodeURIComponent(flight.flight_number)}&market=phoenix&price=${cheapestPrice.toFixed(2)}&us_price=${flight.market_prices['US']?.price_usd?.toFixed(2) || cheapestPrice.toFixed(2)}"
                           class="btn" style="background: #ff6b35; border-color: #ff6b35; color: white; padding: 8px 16px; font-size: 13px; text-decoration: none; border-radius: 6px;">
                            Book via P2P Network — Save $${savings.toFixed(2)}
                        </a>
                    ` : ''}
                </div>
            `;
        } else {
            html += `<p style="color: #666;">Flight not found in checked markets.</p>`;
        }

        html += `</div>`;
    }

    // Summary
    if (totalSavings > 0) {
        html += `
            <div style="background: #d4edda; padding: 20px; border-radius: 12px; text-align: center;">
                <h3 style="color: #155724; margin: 0;">Total Potential Savings: $${totalSavings.toFixed(2)}</h3>
                <p style="color: #155724; margin: 10px 0 0 0;">by booking through Phoenix's price engine</p>
            </div>
        `;
    }

    html += `</div>`;
    container.innerHTML = html;
}

// Calendar search
async function searchCalendar(e) {
    e.preventDefault();
    const form = document.getElementById('calendar-search-form');
    const btn = document.getElementById('calendar-search-btn');
    const status = document.getElementById('calendar-search-status');
    const container = document.getElementById('calendar-results-container');

    btn.disabled = true;
    status.textContent = 'Searching dates... This may take a moment.';
    container.innerHTML = '';

    const origin = form.querySelector('[name="cal_origin"]').value.trim().toUpperCase();
    const destination = form.querySelector('[name="cal_destination"]').value.trim().toUpperCase();
    const startDate = form.querySelector('[name="cal_start_date"]').value;
    const endDate = form.querySelector('[name="cal_end_date"]').value;

    try {
        const response = await fetch('/api/search/calendar', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                origin, destination,
                start_date: startDate,
                end_date: endDate,
                passengers: { adults: 1 },
                cabin_class: 'economy'
            })
        });
        const data = await response.json();

        if (data.error) {
            status.textContent = data.error;
        } else {
            displayCalendarResults(data);
            status.textContent = `Checked ${data.dates_checked} dates`;
        }
    } catch (err) {
        status.textContent = 'Search failed. Please try again.';
        console.error(err);
    }

    btn.disabled = false;
}

function displayCalendarResults(data) {
    const container = document.getElementById('calendar-results-container');

    if (!data.prices || data.prices.length === 0) {
        container.innerHTML = `
            <div class="card" style="margin-top: 20px;">
                <h2>No Prices Found</h2>
                <p style="color: #666;">Could not find prices for this route. Try different dates or airports.</p>
            </div>
        `;
        return;
    }

    const cheapest = data.cheapest_date;

    let html = `
        <div class="card" style="margin-top: 20px;">
            <h2>Price Calendar: ${data.origin} → ${data.destination}</h2>
            ${cheapest ? `
                <div style="background: #d4edda; padding: 15px; border-radius: 8px; margin-bottom: 20px;">
                    <strong style="color: #155724; font-size: 18px;">Cheapest: ${cheapest.date}</strong><br>
                    <span style="color: #155724; font-size: 24px; font-weight: bold;">$${cheapest.price_usd}</span>
                    <span style="color: #666; margin-left: 10px;">via ${cheapest.best_market} market</span>
                </div>
            ` : ''}
            <table class="price-table">
                <thead>
                    <tr>
                        <th>Date</th>
                        <th>Day</th>
                        <th>Price (USD)</th>
                        <th>Best Market</th>
                    </tr>
                </thead>
                <tbody>
    `;

    for (const day of data.prices) {
        const date = new Date(day.date + 'T12:00:00');
        const dayName = date.toLocaleDateString('en-US', { weekday: 'short' });
        const isCheapest = cheapest && day.date === cheapest.date;

        html += `
            <tr class="${isCheapest ? 'cheapest' : ''}">
                <td>${day.date}</td>
                <td>${dayName}</td>
                <td>$${day.price_usd.toFixed(2)}</td>
                <td><span class="market-tag">${day.best_market}</span></td>
            </tr>
        `;
    }

    html += `
                </tbody>
            </table>
            <p style="margin-top: 15px; color: #666; font-size: 13px;">
                Prices shown are lowest found across US and Spain markets.
                Use Route Search for full market comparison.
            </p>
        </div>
    `;

    container.innerHTML = html;
}

// Flight number search
async function searchFlightNumber(e) {
    e.preventDefault();

    // Save preferences before search (in case of failure)
    saveSearchPreferences();

    const form = document.getElementById('flight-search-form');
    const btn = document.getElementById('flight-search-btn');
    const status = document.getElementById('flight-search-status');
    const container = document.getElementById('flight-results-container');

    btn.disabled = true;
    status.textContent = 'Searching markets...';
    container.innerHTML = '';

    // Show loading screen
    if (window.showLoadingScreen) {
        window.showLoadingScreen('Comparing flight prices across global markets...');
    }

    const flightNumber = form.querySelector('[name="flight_number"]').value.trim().toUpperCase();
    const origin = form.querySelector('[name="fn_origin"]').value.trim().toUpperCase();
    const destination = form.querySelector('[name="fn_destination"]').value.trim().toUpperCase();
    const date = form.querySelector('[name="fn_date"]').value;

    try {
        const response = await fetch('/api/search/flight', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ flight_number: flightNumber, origin, destination, date })
        });
        const data = await response.json();

        displayFlightComparison(data, flightNumber);

        if (data.found && data.comparison) {
            status.textContent = `Found — compared across ${typeof data.comparison.markets_checked === 'number' ? data.comparison.markets_checked : (data.comparison.markets_checked?.length || 5)} regions`;
        } else if (data.found) {
            status.textContent = 'Flight found but limited market data';
        } else {
            status.textContent = 'Flight not found';
        }
    } catch (err) {
        status.textContent = 'Search failed. Please try again.';
        console.error(err);
    }

    // Hide loading screen
    if (window.hideLoadingScreen) {
        window.hideLoadingScreen();
    }
    btn.disabled = false;
}

function displayFlightComparison(data, flightNumber) {
    const container = document.getElementById('flight-results-container');

    if (!data.found) {
        container.innerHTML = `
            <div class="card" style="margin-top: 20px;">
                <h2>Flight Not Found</h2>
                <p style="color: #666;">${data.error || 'Could not find this flight. Please check the flight number, route, and date.'}</p>
            </div>
        `;
        return;
    }

    const flight = data.flight;
    const comparison = data.comparison;
    const prices = data.market_prices;

    // Market flags for display
    const marketFlags = {
        'US': '🇺🇸', 'UK': '🇬🇧', 'GB': '🇬🇧', 'ES': '🇪🇸', 'FR': '🇫🇷',
        'DE': '🇩🇪', 'IT': '🇮🇹', 'JP': '🇯🇵', 'AU': '🇦🇺', 'CA': '🇨🇦',
        'IN': '🇮🇳', 'SG': '🇸🇬', 'BR': '🇧🇷', 'MX': '🇲🇽', 'NL': '🇳🇱'
    };

    let html = `
        <div class="card" style="margin-top: 20px;">
            <h2>Price Comparison: ${flight.airline} ${flight.flight_number}</h2>
            <p style="color: #666;">
                ${flight.origin} → ${flight.destination} on ${flight.date}
                ${flight.departure_time ? `| Departs ${flight.departure_time}` : ''}
                ${flight.stops !== undefined ? `| ${flight.stops === 0 ? 'Nonstop' : flight.stops + ' stop(s)'}` : ''}
            </p>

            ${data.google_flights_url ? `
                <p><a href="${data.google_flights_url}" target="_blank" class="google-link">View on Google Flights →</a></p>
            ` : ''}

            <table class="price-table">
                <thead>
                    <tr>
                        <th>Market</th>
                        <th>Local Price</th>
                        <th>USD Equivalent</th>
                        <th>vs Cheapest</th>
                    </tr>
                </thead>
                <tbody>
    `;

    // Sort markets by USD price
    const sortedMarkets = Object.entries(prices)
        .filter(([_, p]) => p.price_usd)
        .sort((a, b) => a[1].price_usd - b[1].price_usd);

    const cheapestPrice = sortedMarkets.length > 0 ? sortedMarkets[0][1].price_usd : 0;

    for (const [market, priceData] of sortedMarkets) {
        const isCheapest = priceData.price_usd === cheapestPrice;
        const diff = priceData.price_usd - cheapestPrice;
        const flag = marketFlags[market] || '';

        html += `
            <tr class="${isCheapest ? 'cheapest' : ''}">
                <td><span class="market-flag">${flag}</span>${market}</td>
                <td>${priceData.original_price} ${priceData.original_currency}</td>
                <td>$${priceData.price_usd.toFixed(2)}</td>
                <td>${isCheapest ? '<strong>CHEAPEST</strong>' : `+$${diff.toFixed(2)}`}</td>
            </tr>
        `;
    }

    html += `
                </tbody>
            </table>
    `;

    // Show savings summary if there's a deal
    if (comparison && comparison.max_savings_usd > 0) {
        html += `
            <div style="background: #d4edda; padding: 15px; border-radius: 8px; margin-top: 20px;">
                <h3 style="margin: 0 0 10px 0; color: #155724;">Savings Available!</h3>
                <div class="price-row">
                    <span>Book via Phoenix instead of standard pricing:</span>
                    <span style="font-size: 20px; font-weight: bold; color: #155724;">Save $${comparison.max_savings_usd.toFixed(2)} (${comparison.savings_percent}%)</span>
                </div>
        `;

        if (data.deal && data.deal.is_good_deal) {
            html += `
                <div style="margin-top: 15px; padding-top: 15px; border-top: 1px solid #c3e6cb;">
                    <div class="price-row">
                        <span>Your price (after 25% platform fee):</span>
                        <span style="font-weight: bold;">$${data.deal.arbitrage_price.toFixed(2)}</span>
                    </div>
                    <div class="price-row">
                        <span>You save:</span>
                        <span style="color: #155724; font-weight: bold;">$${data.deal.user_savings.toFixed(2)}</span>
                    </div>
                </div>
            `;
        }

        html += `</div>`;
    }

    html += `</div>`;
    container.innerHTML = html;
}
</script>
"""


@app.route("/search")
def search_page():
    """Global flight search page."""
    # Render the search content first to process Jinja variables
    rendered_content = render_template_string(
        SEARCH_PAGE_CONTENT,
        current_user=current_user
    )
    return render_template_string(
        BASE_TEMPLATE,
        title="Search Flights",
        content=rendered_content,
        current_user=current_user
    )


@app.route("/api/search", methods=["POST"])
@csrf.exempt
@limiter.limit("10 per minute")
def api_search():
    """
    API endpoint for single flight search.

    Request body:
    {
        "origin": "LAX",
        "destination": "HND",
        "date": "2026-03-15"
    }
    """
    data = request.get_json()
    origin = data.get("origin", "").upper()
    destination = data.get("destination", "").upper()
    date = data.get("date")

    if not origin or not destination or not date:
        return jsonify({"error": "origin, destination, and date are required"}), 400

    try:
        results = search_global(origin, destination, date, fast_mode=True)

        # Store deals in database
        for deal_data in results.get("deals", []):
            deal_info = deal_data.get("deal", {})
            existing = Deal.query.filter_by(deal_id=deal_info.get("deal_id")).first()
            if not existing and deal_info.get("deal_id"):
                deal = Deal(
                    deal_id=deal_info.get("deal_id"),
                    airline=deal_data.get("airline"),
                    flight_number=deal_data.get("flight_number"),
                    origin=origin,
                    destination=destination,
                    departure_date=datetime.strptime(date, "%Y-%m-%d").date(),
                    home_market="US",
                    home_price_usd=deal_info.get("home_price"),
                    arbitrage_market=deal_data.get("cheapest_market"),
                    arbitrage_price_usd=deal_info.get("arbitrage_price"),
                    gross_savings_usd=deal_info.get("gross_savings"),
                    platform_fee_usd=deal_info.get("platform_fee_usd"),
                    platform_fee_xrp=deal_info.get("platform_fee_xrp"),
                    user_savings_usd=deal_info.get("user_savings"),
                    savings_percent=deal_info.get("user_saves_pct"),
                    booking_url=deal_info.get("booking_url"),
                    destination_tag=deal_info.get("payment", {}).get("payment_request", {}).get("destination_tag"),
                    is_active=True,
                    expires_at=datetime.utcnow() + timedelta(hours=24)
                )
                db.session.add(deal)

        db.session.commit()

        # Record search for analytics + airline intelligence data pipeline
        try:
            from search_tracker import tracker
            tracker.record_search(
                user_id=current_user.id if current_user.is_authenticated else None,
                origin=origin,
                destination=destination,
                departure_date=date,
                results=results.get("deals", []) if isinstance(results, dict) else results,
                method="api",
                markets_searched=results.get("markets_searched") if isinstance(results, dict) else None,
            )
        except Exception as track_err:
            logger.warning(f"Search tracking failed (non-blocking): {track_err}")

        # --- Node Consent Economy: Record platform search activity ---
        if current_user.is_authenticated:
            try:
                from node_consent_economy import node_consent_economy
                node_consent_economy.record_platform_activity(
                    user_id=current_user.id,
                    activity_type='platform_search',
                    metadata={'origin': origin, 'destination': destination, 'date': date,
                              'results_count': len(results.get('deals', [])) if isinstance(results, dict) else 0}
                )
            except Exception:
                pass  # Non-blocking

        return jsonify(results)

    except Exception as e:
        logger.error(f"Search error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/search/itinerary", methods=["POST"])
@csrf.exempt
@limiter.limit("5 per minute")
def api_search_itinerary():
    """
    API endpoint for multi-flight itinerary search.

    Request body:
    {
        "name": "My Trip",
        "trip_type": "round_trip",  // one_way, round_trip, multi_city
        "passengers": {"adults": 1, "children": 0, "infants_seat": 0, "infants_lap": 0},
        "cabin_class": "economy",   // economy, premium_economy, business, first
        "stops": "any",             // any, nonstop, 1, 2
        "legs": [
            {"origin": "LAX", "destination": "HND", "date": "2026-03-01"},
            {"origin": "HND", "destination": "LAX", "date": "2026-03-10"}
        ]
    }
    """
    data = request.get_json()
    name = data.get("name", "My Trip")
    legs = data.get("legs", [])

    # New search options
    trip_type = data.get("trip_type", "one_way")
    passengers = data.get("passengers", {"adults": 1, "children": 0, "infants_seat": 0, "infants_lap": 0})
    cabin_class = data.get("cabin_class", "economy")
    # Handle "all" classes - default to economy as primary search
    if cabin_class == "all":
        cabin_class = "economy"
    stops = data.get("stops", "any")
    flexible_dates = data.get("flexible_dates", False)
    flex_days = min(data.get("flex_days", 3), 7)  # Cap at 7 days max

    if not legs:
        return jsonify({"error": "At least one leg is required"}), 400

    if len(legs) > 8:
        return jsonify({"error": "Maximum 8 legs per itinerary"}), 400

    # Build search options to pass to search functions
    search_options = {
        "passengers": passengers,
        "cabin_class": cabin_class,
        "stops": stops,
        "trip_type": trip_type
    }

    try:
        # If flexible dates enabled, search nearby dates too
        flexible_results = None
        if flexible_dates and len(legs) == 1:
            leg = legs[0]
            origin = leg.get("origin", "").upper()
            destination = leg.get("destination", "").upper()
            base_date = datetime.strptime(leg.get("date"), "%Y-%m-%d")

            # Use direct scraping with proxies if available
            date_prices = []

            # Flexible date search — google_flights_scraper and amadeus_client
            # removed (Build #89). Will be re-implemented via Google Travel
            # node-based search.
            # For now, flexible date search uses search_global per date.
            if not date_prices:
                for offset_d in range(-flex_days, flex_days + 1):
                    check_date = base_date + timedelta(days=offset_d)
                    date_str = check_date.strftime("%Y-%m-%d")
                    try:
                        flex_result = search_global(
                            origin=origin,
                            destination=destination,
                            date=date_str,
                            fast_mode=True,
                        )
                        if isinstance(flex_result, dict) and flex_result.get("deals"):
                            prices_list = [
                                d.get("best_price") or d.get("price_usd", 0)
                                for d in flex_result["deals"]
                                if d.get("best_price") or d.get("price_usd")
                            ]
                            if prices_list:
                                best_price = min(prices_list)
                                date_prices.append({
                                    "date": date_str,
                                    "day": check_date.strftime("%a"),
                                    "price_usd": round(best_price, 2),
                                    "best_market": "US",
                                    "is_selected": offset_d == 0,
                                    "proxy_scraped": False,
                                })
                    except Exception as e:
                        logger.warning(f"Flexible date search failed for {date_str}: {e}")

            # Find cheapest and calculate savings
            if date_prices:
                cheapest = min(date_prices, key=lambda x: x["price_usd"])
                selected = next((d for d in date_prices if d["is_selected"]), None)

                flexible_results = {
                    "dates": date_prices,
                    "cheapest_date": cheapest,
                    "selected_date": selected,
                    "potential_savings": round(selected["price_usd"] - cheapest["price_usd"], 2) if selected and cheapest else 0
                }

        # Check if this is a round-trip that should be searched as a single query
        is_round_trip_search = (
            trip_type == "round_trip" and
            len(legs) == 2 and
            legs[0].get("origin", "").upper() == legs[1].get("destination", "").upper() and
            legs[0].get("destination", "").upper() == legs[1].get("origin", "").upper()
        )

        if is_round_trip_search:
            # Search as ACTUAL ROUND-TRIP to get proper round-trip pricing from Google Flights
            # DO NOT search as two one-ways - that shows ~double the price!
            logger.info("Searching round-trip with actual round-trip pricing...")
            outbound_origin = legs[0].get("origin", "").upper()
            outbound_dest = legs[0].get("destination", "").upper()
            outbound_date = legs[0].get("date")
            return_date = legs[1].get("date")

            from search import search_global

            # SINGLE round-trip search with return_date - this gets the correct combined price
            logger.info(f"Searching round-trip: {outbound_origin} ↔ {outbound_dest} ({outbound_date} → {return_date})")
            round_trip_results = search_global(
                origin=outbound_origin,
                destination=outbound_dest,
                date=outbound_date,
                return_date=return_date,  # ACTUAL round-trip search!
                fast_mode=True,
                search_options=search_options
            )

            # Get the best deal from round-trip results
            best_deal = round_trip_results.get("deals", [{}])[0] if round_trip_results.get("deals") else None
            total_savings = best_deal.get("deal", {}).get("user_savings", 0) if best_deal else 0

            # Format results - present as a single round-trip with TOTAL price
            # Each flight in all_flights already has the round-trip total price
            results = {
                "itinerary_id": f"rt_{outbound_origin}_{outbound_dest}_{outbound_date}",
                "name": name,
                "is_round_trip": True,
                "is_actual_round_trip": True,  # Flag to indicate prices are round-trip totals
                "outbound_date": outbound_date,
                "return_date": return_date,
                "leg_results": [
                    {
                        "leg": 1,
                        "route": f"{outbound_origin} ↔ {outbound_dest}",
                        "route_display": f"{outbound_origin} → {outbound_dest} → {outbound_origin}",
                        "date": outbound_date,
                        "return_date": return_date,
                        "is_round_trip": True,
                        "is_outbound": True,
                        "is_return": True,
                        "deal": best_deal,
                        "savings": total_savings,
                        "all_flights": round_trip_results.get("all_flights", []),
                        "markets_checked": round_trip_results.get("markets_checked", []),
                        "proxy_results": round_trip_results.get("proxy_results"),
                        "price_type": "round_trip_total",  # Indicates price is for entire round-trip
                    }
                ],
                "summary": {
                    "total_legs": 1,  # Single round-trip = 1 leg to select
                    "total_flights_found": round_trip_results.get("total_flights", 0) or 0,
                    "legs_with_deals": 1 if round_trip_results.get("deals") else 0,
                    "total_user_savings": total_savings,
                    "markets_checked": round_trip_results.get("markets_checked", []),
                    "is_round_trip": True,
                    "is_actual_round_trip": True,
                    "price_type": "round_trip_total"
                }
            }

            # Add flexible dates if available
            if flexible_results:
                results["flexible_dates"] = flexible_results

            return jsonify(results)

        # Standard multi-leg search (one-way or multi-city)
        # Build itinerary
        itinerary = Itinerary(name=name)
        for leg in legs:
            origin = leg.get("origin", "").upper()
            destination = leg.get("destination", "").upper()
            date = leg.get("date")

            if origin and destination and date:
                itinerary.add_leg(origin, destination, date)

        # Search all legs with options
        results = itinerary.search_all_legs(fast_mode=True, search_options=search_options)

        # Add flexible dates data to results
        if flexible_results:
            results["flexible_dates"] = flexible_results

        # Store itinerary
        itineraries[results["itinerary_id"]] = itinerary

        # Store deals in database
        for leg_result in results.get("leg_results", []):
            deal_data = leg_result.get("deal")
            if deal_data:
                deal_info = deal_data.get("deal", {})
                existing = Deal.query.filter_by(deal_id=deal_info.get("deal_id")).first()
                if not existing and deal_info.get("deal_id"):
                    leg_info = itinerary.legs[leg_result["leg"] - 1]
                    deal = Deal(
                        deal_id=deal_info.get("deal_id"),
                        airline=deal_data.get("airline"),
                        flight_number=deal_data.get("flight_number"),
                        origin=leg_info.origin,
                        destination=leg_info.destination,
                        departure_date=datetime.strptime(leg_info.date, "%Y-%m-%d").date(),
                        home_market="US",
                        home_price_usd=deal_info.get("home_price"),
                        arbitrage_market=deal_data.get("cheapest_market"),
                        arbitrage_price_usd=deal_info.get("arbitrage_price"),
                        gross_savings_usd=deal_info.get("gross_savings"),
                        platform_fee_usd=deal_info.get("platform_fee_usd"),
                        platform_fee_xrp=deal_info.get("platform_fee_xrp"),
                        user_savings_usd=deal_info.get("user_savings"),
                        savings_percent=deal_info.get("user_saves_pct"),
                        booking_url=deal_info.get("booking_url"),
                        destination_tag=deal_info.get("payment", {}).get("payment_request", {}).get("destination_tag"),
                        is_active=True,
                        expires_at=datetime.utcnow() + timedelta(hours=24)
                    )
                    db.session.add(deal)

        db.session.commit()

        return jsonify(results)

    except Exception as e:
        logger.error(f"Itinerary search error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/airports", methods=["GET"])
def api_airports():
    """Search for airports by code or city name."""
    query = request.args.get("q", "")
    if len(query) < 2:
        return jsonify({"airports": []})

    results = search_airports(query)
    return jsonify({"airports": results})


@app.route("/api/markets/<origin>/<destination>")
def api_markets_for_route(origin, destination):
    """Get recommended markets to check for a route."""
    markets = select_markets_for_route(origin.upper(), destination.upper())
    return jsonify({
        "origin": origin.upper(),
        "destination": destination.upper(),
        "markets": markets,
        "count": len(markets)
    })


@app.route("/api/search/flight", methods=["POST"])
@csrf.exempt
@limiter.limit("10 per minute")
def api_search_flight_number():
    """
    Search for a specific flight number across markets.

    Request body:
    {
        "flight_number": "AA 123",
        "origin": "LAX",
        "destination": "JFK",
        "date": "2026-03-15"
    }
    """
    data = request.get_json()
    flight_number = data.get("flight_number", "").strip()
    origin = data.get("origin", "").upper()
    destination = data.get("destination", "").upper()
    date = data.get("date")

    if not flight_number:
        return jsonify({"error": "flight_number is required"}), 400
    if not origin or not destination:
        return jsonify({"error": "origin and destination are required"}), 400
    if not date:
        return jsonify({"error": "date is required"}), 400

    try:
        results = search_flight_number(flight_number, origin, destination, date)
        return jsonify(results)
    except Exception as e:
        logger.error(f"Flight number search error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/search/calendar", methods=["POST"])
@csrf.exempt
@limiter.limit("3 per minute")
def api_search_calendar():
    """
    Search for cheapest prices across a date range (like Google Flights calendar).

    Request body:
    {
        "origin": "LAX",
        "destination": "BCN",
        "start_date": "2026-03-01",
        "end_date": "2026-03-14",
        "passengers": {"adults": 1},
        "cabin_class": "economy"
    }

    Returns prices for each date in the range.
    """
    from datetime import datetime, timedelta

    data = request.get_json()
    origin = data.get("origin", "").upper()
    destination = data.get("destination", "").upper()
    start_date = data.get("start_date")
    end_date = data.get("end_date")
    passengers = data.get("passengers", {"adults": 1})
    cabin_class = data.get("cabin_class", "economy")

    if not origin or not destination:
        return jsonify({"error": "origin and destination are required"}), 400
    if not start_date or not end_date:
        return jsonify({"error": "start_date and end_date are required"}), 400

    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")

        # Limit to 14 days max
        if (end - start).days > 14:
            end = start + timedelta(days=14)

        # Build search options
        search_options = {
            "passengers": passengers,
            "cabin_class": cabin_class,
            "stops": "any"
        }

        # Search each date (we'll sample key dates to limit API calls)
        date_prices = []
        current = start
        dates_to_check = []

        while current <= end:
            dates_to_check.append(current.strftime("%Y-%m-%d"))
            current += timedelta(days=1)

        # Limit to every other day if range is long
        if len(dates_to_check) > 7:
            dates_to_check = dates_to_check[::2] + ([dates_to_check[-1]] if len(dates_to_check) % 2 == 0 else [])

        # Use a single market for calendar (US) to reduce API calls
        from main import fetch_flights_direct, extract_flights, PRIORITY_MARKETS

        for date_str in dates_to_check:
            # Check US and cheapest EU market
            markets_to_check = [
                {"label": "US", "currency": "USD", "gl": "us", "hl": "en"},
                {"label": "ES", "currency": "EUR", "gl": "es", "hl": "es"},
            ]

            best_price = None
            best_market = None

            for market in markets_to_check:
                results = fetch_flights_direct(origin, destination, date_str, market, search_options=search_options)
                flights = extract_flights(results, market, origin, destination, date_str)

                if flights:
                    # Get cheapest flight price
                    for f in flights:
                        price_usd = f.get("price_usd", f.get("price", 0))
                        if best_price is None or price_usd < best_price:
                            best_price = price_usd
                            best_market = market["label"]

            if best_price:
                date_prices.append({
                    "date": date_str,
                    "price_usd": round(best_price, 2),
                    "best_market": best_market
                })

        # Find cheapest date
        cheapest = min(date_prices, key=lambda x: x["price_usd"]) if date_prices else None

        return jsonify({
            "origin": origin,
            "destination": destination,
            "date_range": {"start": start_date, "end": end_date},
            "prices": date_prices,
            "cheapest_date": cheapest,
            "dates_checked": len(date_prices)
        })

    except Exception as e:
        logger.error(f"Calendar search error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/search/compare-itinerary", methods=["POST"])
@csrf.exempt
@limiter.limit("3 per minute")
def api_compare_itinerary():
    """
    Compare an imported itinerary across multiple regional markets.

    This endpoint searches for specific flights across different country markets
    using proxy/VPN routing to find regional pricing differences.

    Request body:
    {
        "flights": [
            {
                "flight_number": "AA 123",
                "origin": "LAX",
                "destination": "JFK",
                "date": "2026-03-15"
            }
        ],
        "markets": ["US", "UK", "DE", "ES", "FR", "JP"]
    }

    Returns price comparison for each flight across selected markets.
    """
    from main import search_flight_number, PRIORITY_MARKETS

    data = request.get_json()
    flights = data.get("flights", [])
    selected_markets = data.get("markets", ["US", "UK", "DE", "ES", "FR", "JP"])

    if not flights:
        return jsonify({"error": "No flights provided"}), 400

    if len(flights) > 10:
        return jsonify({"error": "Maximum 10 flights per comparison"}), 400

    # Build market configs for selected markets
    market_configs = [m for m in PRIORITY_MARKETS if m["label"] in selected_markets]

    # If no matching markets, use defaults
    if not market_configs:
        market_configs = PRIORITY_MARKETS[:6]

    results = []
    total_savings = 0

    for flight in flights:
        flight_number = flight.get("flight_number", "").strip()
        origin = flight.get("origin", "").upper()
        destination = flight.get("destination", "").upper()
        date = flight.get("date", "")

        if not flight_number or not origin or not destination or not date:
            results.append({
                "flight_number": flight_number or "Unknown",
                "origin": origin,
                "destination": destination,
                "date": date,
                "error": "Missing required fields",
                "market_prices": {},
                "savings_usd": 0
            })
            continue

        try:
            # Search this flight across markets
            search_result = search_flight_number(
                flight_number=flight_number,
                origin=origin,
                destination=destination,
                date=date,
                markets=market_configs
            )

            if search_result.get("found") and search_result.get("market_prices"):
                market_prices = search_result["market_prices"]
                comparison = search_result.get("comparison", {})

                # Calculate savings vs US price
                us_price = market_prices.get("US", {}).get("price_usd", 0)
                cheapest_price = comparison.get("cheapest_price_usd", us_price) if comparison else us_price
                savings = us_price - cheapest_price if us_price > cheapest_price else 0

                total_savings += savings

                results.append({
                    "flight_number": flight_number,
                    "origin": origin,
                    "destination": destination,
                    "date": date,
                    "airline": search_result.get("flight", {}).get("airline", ""),
                    "market_prices": {},  # Scrubbed
                    "cheapest_market": "Phoenix",
                    "cheapest_price_usd": cheapest_price,
                    "us_price_usd": us_price,
                    "savings_usd": round(savings, 2)
                })
            else:
                results.append({
                    "flight_number": flight_number,
                    "origin": origin,
                    "destination": destination,
                    "date": date,
                    "error": "Flight not found in markets",
                    "market_prices": {},
                    "savings_usd": 0
                })

        except Exception as e:
            logger.error(f"Error searching flight {flight_number}: {e}")
            results.append({
                "flight_number": flight_number,
                "origin": origin,
                "destination": destination,
                "date": date,
                "error": str(e),
                "market_prices": {},
                "savings_usd": 0
            })

    return jsonify({
        "results": results,
        "flights_compared": len(flights),
        "markets_checked": len(selected_markets) if isinstance(selected_markets, list) else selected_markets,
        "total_savings_usd": round(total_savings, 2)
    })


@app.route("/api/search/direct", methods=["POST"])
@csrf.exempt
@limiter.limit("5 per minute")
def api_search_direct():
    """
    Search flights using DIRECT Google Flights scraping with residential proxies.

    This uses Playwright + residential proxies to get
    REAL regional pricing by appearing as a user in each country.

    Request body:
    {
        "origin": "LAX",
        "destination": "BCN",
        "date": "2026-03-15",
        "markets": ["US", "ES", "UK", "DE"],  // Optional, defaults to priority markets
        "cabin_class": "economy"  // Optional: economy, premium_economy, business, first
    }

    Returns real regional pricing from each market via proxy.
    """
    if not DIRECT_SCRAPER_AVAILABLE:
        return jsonify({
            "error": "Direct scraper not available",
            "message": "Install playwright: pip install playwright && playwright install chromium",
            "fallback": "Use /api/search for Amadeus-based search"
        }), 503

    data = request.get_json()
    origin = data.get("origin", "").upper()
    destination = data.get("destination", "").upper()
    date = data.get("date")
    markets = data.get("markets", ["US", "ES", "UK", "DE", "FR", "JP"])
    cabin_class = data.get("cabin_class", "economy")

    if not origin or not destination:
        return jsonify({"error": "origin and destination are required"}), 400
    if not date:
        return jsonify({"error": "date is required"}), 400

    # Limit markets to prevent abuse
    if len(markets) > 10:
        markets = markets[:10]

    try:
        results = search_with_direct_scraping(
            origin=origin,
            destination=destination,
            date=date,
            markets=markets,
            cabin_class=cabin_class
        )

        return jsonify({
            "success": True,
            "method": "direct_scraping",
            "proxy_based": True,
            "note": "Prices from actual Google Flights via residential proxies",
            **results
        })

    except Exception as e:
        logger.error(f"Direct scraping error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/scraper/status", methods=["GET"])
def api_scraper_status():
    """Check search infrastructure status (Build #89 — Google-native)."""
    return jsonify({
        "architecture": "google_native",
        "direct_scraper_available": DIRECT_SCRAPER_AVAILABLE,
        "proxy_configured": False,
        "note": "Transitioning to Google-native node-based search",
    })


# --- MULTI-PAYMENT GATEWAY ---

PAYMENT_PAGE_CONTENT = """
<style>
.payment-options { max-width: 500px; margin: 0 auto; }
.payment-methods { display: flex; flex-direction: column; gap: 15px; }
.payment-method {
    display: flex; align-items: center; gap: 15px;
    padding: 20px; border: 2px solid #eee; border-radius: 12px;
    transition: all 0.2s;
}
.payment-method:hover { border-color: #ff6b35; background: #f8f9ff; }
.payment-method.selected { border-color: #ff6b35; background: #fff8f5; }
.method-icon { font-size: 32px; }
.method-info { flex: 1; }
.method-info strong { display: block; margin-bottom: 4px; }
.method-info span { color: #666; font-size: 14px; }
.xrp-details, .rlusd-details { display: none; margin-top: 20px; padding: 20px; background: #f8f9fa; border-radius: 8px; }
.xrp-details.show, .rlusd-details.show { display: block; }
.copy-field {
    display: flex; align-items: center; gap: 10px;
    background: white; padding: 10px; border-radius: 4px; margin: 10px 0;
    border: 1px solid #ddd;
}
.copy-field code { flex: 1; word-break: break-all; font-size: 13px; }
.copy-btn { padding: 5px 10px; font-size: 12px; cursor: pointer; }
.warning { background: #fff3cd; color: #856404; padding: 10px; border-radius: 4px; margin: 10px 0; }
.deal-summary { background: #e8f5e9; padding: 15px; border-radius: 8px; margin-bottom: 20px; }
</style>

<div class="card">
    <h1>Complete Your Payment</h1>

    <div class="deal-summary">
        <h3 style="margin: 0 0 10px 0;">{{ deal.airline }} {{ deal.flight_number }} - {{ deal.route }}</h3>
        <div class="price-row">
            <span>Your Savings:</span>
            <span><strong>${{ "%.2f"|format(deal.user_savings_usd) }}</strong></span>
        </div>
        <div class="price-row">
            <span>Platform Fee:</span>
            <span><strong>${{ "%.2f"|format(deal.platform_fee_usd) }}</strong></span>
        </div>
    </div>

    <div class="payment-options">
        <p style="color: #666; margin-bottom: 20px;">Choose how you'd like to pay:</p>

        <div class="payment-methods">
            {% if options.methods.card.enabled %}
            <div class="payment-method" onclick="selectMethod('card')">
                <div class="method-icon">💳</div>
                <div class="method-info">
                    <strong>Credit/Debit Card</strong>
                    <span>${{ "%.2f"|format(options.fee_usd) }} USD - Instant</span>
                </div>
                <button class="btn" id="card-btn" onclick="payWithCard(event)">Pay Now</button>
            </div>
            {% endif %}

            {% if options.methods.xrp.enabled %}
            <div class="payment-method" onclick="selectMethod('xrp')">
                <div class="method-icon">⚡</div>
                <div class="method-info">
                    <strong>XRP</strong>
                    <span>{{ "%.4f"|format(options.methods.xrp.amount_xrp) }} XRP (≈${{ "%.2f"|format(options.fee_usd) }})</span>
                </div>
                <button class="btn btn-secondary" id="xrp-btn" onclick="showXrpDetails(event)">Select</button>
            </div>
            {% endif %}

            {% if options.methods.rlusd.enabled %}
            <div class="payment-method" onclick="selectMethod('rlusd')">
                <div class="method-icon">💵</div>
                <div class="method-info">
                    <strong>RLUSD Stablecoin</strong>
                    <span>{{ "%.2f"|format(options.fee_usd) }} RLUSD (1:1 USD)</span>
                </div>
                <button class="btn btn-secondary" id="rlusd-btn" onclick="showRlusdDetails(event)">Select</button>
            </div>
            {% endif %}

            {% if options.methods.crypto.enabled %}
            <div class="payment-method" onclick="selectMethod('crypto')">
                <div class="method-icon">🪙</div>
                <div class="method-info">
                    <strong>Other Crypto</strong>
                    <span>BTC, ETH, LTC, DOGE, USDC & more - ${{ "%.2f"|format(options.fee_usd) }}</span>
                </div>
                <button class="btn btn-secondary" id="crypto-btn" onclick="payWithCrypto(event)">Pay with Crypto</button>
            </div>
            {% endif %}
        </div>

        <!-- XRP Payment Details -->
        <div class="xrp-details" id="xrp-details">
            <h3>Pay with XRP</h3>
            <p>Send exactly <strong>{{ "%.4f"|format(options.methods.xrp.amount_xrp) }} XRP</strong> to:</p>

            <div class="copy-field">
                <code id="xrp-address">{{ options.methods.xrp.destination }}</code>
                <button class="copy-btn btn-secondary" onclick="copyToClipboard('xrp-address')">Copy</button>
            </div>

            <div class="warning">
                <strong>IMPORTANT:</strong> Include this Destination Tag:
                <div class="copy-field" style="margin-top: 8px;">
                    <code id="xrp-tag">{{ options.methods.xrp.destination_tag }}</code>
                    <button class="copy-btn btn-secondary" onclick="copyToClipboard('xrp-tag')">Copy</button>
                </div>
                Without the tag, your payment cannot be matched to your account!
            </div>

            <p style="color: #666; font-size: 14px;">
                Network: {{ options.methods.xrp.network|upper }}<br>
                Rate: ${{ "%.4f"|format(options.methods.xrp.xrp_rate) }}/XRP
            </p>

            <button class="btn" onclick="checkXrpPayment()" style="width: 100%; margin-top: 15px;">
                I've Sent the Payment - Verify
            </button>
        </div>

        <!-- RLUSD Payment Details -->
        <div class="rlusd-details" id="rlusd-details">
            <h3>Pay with RLUSD</h3>
            <p>Send exactly <strong>{{ "%.2f"|format(options.fee_usd) }} RLUSD</strong> to:</p>

            <div class="copy-field">
                <code id="rlusd-address">{{ options.methods.rlusd.destination }}</code>
                <button class="copy-btn btn-secondary" onclick="copyToClipboard('rlusd-address')">Copy</button>
            </div>

            <div class="warning">
                <strong>IMPORTANT:</strong> Include this Destination Tag:
                <div class="copy-field" style="margin-top: 8px;">
                    <code id="rlusd-tag">{{ options.methods.rlusd.destination_tag }}</code>
                    <button class="copy-btn btn-secondary" onclick="copyToClipboard('rlusd-tag')">Copy</button>
                </div>
            </div>

            <p style="color: #666; font-size: 14px;">
                RLUSD is Ripple's USD stablecoin on the XRP Ledger (1:1 with USD)
            </p>

            <button class="btn" onclick="checkRlusdPayment()" style="width: 100%; margin-top: 15px;">
                I've Sent the Payment - Verify
            </button>
        </div>
    </div>
</div>

<script>
const dealId = "{{ deal.deal_id }}";
const destinationTag = {{ options.methods.xrp.destination_tag if options.methods.xrp.enabled else 0 }};
const expectedXrp = {{ options.methods.xrp.amount_xrp if options.methods.xrp.enabled else 0 }};
const expectedRlusd = {{ options.fee_usd }};

function selectMethod(method) {
    document.querySelectorAll('.payment-method').forEach(el => el.classList.remove('selected'));
    event.currentTarget.classList.add('selected');
}

function payWithCard(e) {
    e.stopPropagation();
    // Redirect to Stripe checkout
    window.location.href = '/pay/card/' + dealId;
}

function showXrpDetails(e) {
    e.stopPropagation();
    document.getElementById('xrp-details').classList.add('show');
    document.getElementById('rlusd-details').classList.remove('show');
}

function showRlusdDetails(e) {
    e.stopPropagation();
    document.getElementById('rlusd-details').classList.add('show');
    document.getElementById('xrp-details').classList.remove('show');
}

function payWithCrypto(e) {
    e.stopPropagation();
    // Redirect to Coinbase Commerce checkout
    window.location.href = '/pay/crypto/' + dealId;
}

function copyToClipboard(elementId) {
    const text = document.getElementById(elementId).innerText;
    navigator.clipboard.writeText(text).then(() => {
        alert('Copied to clipboard!');
    });
}

function checkXrpPayment() {
    fetch('/pay/verify/xrp', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            deal_id: dealId,
            destination_tag: destinationTag,
            expected_amount: expectedXrp
        })
    })
    .then(r => r.json())
    .then(data => {
        if (data.verified) {
            alert('Payment verified! Redirecting to your deal...');
            window.location.href = '/deal/' + dealId + '/access';
        } else {
            alert('Payment not found yet. Please wait a moment and try again.');
        }
    });
}

function checkRlusdPayment() {
    fetch('/pay/verify/rlusd', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            deal_id: dealId,
            destination_tag: destinationTag,
            expected_amount: expectedRlusd
        })
    })
    .then(r => r.json())
    .then(data => {
        if (data.verified) {
            alert('Payment verified! Redirecting to your deal...');
            window.location.href = '/deal/' + dealId + '/access';
        } else {
            alert('Payment not found yet. Please wait a moment and try again.');
        }
    });
}
</script>
"""


@app.route("/pay/<deal_id>")
@login_required
def payment_page(deal_id):
    """Show multi-payment options for a deal."""
    deal = Deal.query.filter_by(deal_id=deal_id, is_active=True).first()
    if not deal:
        flash("Deal not found or expired.", "error")
        return redirect("/deals")

    # Check if already paid
    existing_payment = Payment.query.filter_by(
        user_id=current_user.id,
        deal_id=deal.id,
        status='verified'
    ).first()

    if existing_payment:
        flash("You've already paid for this deal!", "success")
        return redirect(f"/deal/{deal_id}/access")

    # Generate payment options
    refresh_xrp_price()
    options = generate_payment_options(
        deal_id=deal_id,
        fee_usd=deal.platform_fee_usd,
        user_id=current_user.id
    )

    return render_template_string(
        BASE_TEMPLATE,
        title="Payment",
        content=render_template_string(
            PAYMENT_PAGE_CONTENT,
            deal=deal,
            options=options
        ),
        current_user=current_user
    )


@app.route("/pay/card/<deal_id>")
@login_required
def pay_with_card(deal_id):
    """Create Stripe checkout session and redirect."""
    deal = Deal.query.filter_by(deal_id=deal_id, is_active=True).first()
    if not deal:
        flash("Deal not found or expired.", "error")
        return redirect("/deals")

    result = create_stripe_checkout_session(
        deal_id=deal_id,
        fee_usd=deal.platform_fee_usd,
        user_email=current_user.email,
        success_url=request.host_url + "pay/success",
        cancel_url=request.host_url + f"pay/{deal_id}"
    )

    if "error" in result:
        flash(f"Card payment error: {result['error']}", "error")
        return redirect(f"/pay/{deal_id}")

    # Store pending payment
    payment = Payment(
        user_id=current_user.id,
        deal_id=deal.id,
        expected_xrp=0,  # Card payment, no XRP
        status='pending',
        destination_tag=0
    )
    db.session.add(payment)
    db.session.commit()

    return redirect(result["checkout_url"])


@app.route("/pay/success")
@login_required
def payment_success():
    """Handle successful Stripe payment."""
    session_id = request.args.get("session_id")
    deal_id = request.args.get("deal_id")

    if not session_id:
        flash("Invalid payment session.", "error")
        return redirect("/deals")

    result = verify_stripe_session(session_id)

    if result.get("verified"):
        # Update payment record
        deal = Deal.query.filter_by(deal_id=deal_id).first()
        if deal:
            payment = Payment.query.filter_by(
                user_id=current_user.id,
                deal_id=deal.id,
                status='pending'
            ).first()

            if payment:
                payment.status = 'verified'
                payment.verified_at = datetime.utcnow()
                payment.tx_hash = result.get("payment_intent", "stripe")
                db.session.commit()

        flash("Payment successful! Here's your deal.", "success")
        return redirect(f"/deal/{deal_id}/access")

    flash("Payment verification failed. Please contact support.", "error")
    return redirect("/deals")


@app.route("/pay/verify/xrp", methods=["POST"])
@login_required
def verify_xrp_payment_route():
    """Verify XRP payment."""
    data = request.get_json()
    deal_id = data.get("deal_id")
    destination_tag = data.get("destination_tag")
    expected_amount = data.get("expected_amount")

    result = verify_payment(
        method="xrp",
        destination_tag=destination_tag,
        expected_amount=expected_amount,
        deal_id=deal_id
    )

    if result.get("verified"):
        # Store verified payment
        deal = Deal.query.filter_by(deal_id=deal_id).first()
        if deal:
            payment = Payment(
                user_id=current_user.id,
                deal_id=deal.id,
                destination_tag=destination_tag,
                expected_xrp=expected_amount,
                received_xrp=result.get("amount_xrp", expected_amount),
                xrp_usd_rate=PAYMENT_CONFIG.get("xrp_usd_rate", 0.5),
                tx_hash=result.get("tx_hash"),
                sender_address=result.get("sender"),
                status='verified',
                verified_at=datetime.utcnow()
            )
            db.session.add(payment)
            db.session.commit()

    return jsonify(result)


@app.route("/pay/verify/rlusd", methods=["POST"])
@login_required
def verify_rlusd_payment_route():
    """Verify RLUSD payment."""
    data = request.get_json()
    deal_id = data.get("deal_id")
    destination_tag = data.get("destination_tag")
    expected_amount = data.get("expected_amount")

    result = verify_payment(
        method="rlusd",
        destination_tag=destination_tag,
        expected_amount=expected_amount,
        deal_id=deal_id
    )

    if result.get("verified"):
        # Store verified payment
        deal = Deal.query.filter_by(deal_id=deal_id).first()
        if deal:
            payment = Payment(
                user_id=current_user.id,
                deal_id=deal.id,
                destination_tag=destination_tag,
                expected_xrp=0,  # RLUSD, not XRP
                received_xrp=0,
                xrp_usd_rate=1.0,  # RLUSD is 1:1 USD
                tx_hash=result.get("tx_hash"),
                sender_address=result.get("sender"),
                status='verified',
                verified_at=datetime.utcnow()
            )
            db.session.add(payment)
            db.session.commit()

    return jsonify(result)


@app.route("/pay/webhook/stripe", methods=["POST"])
def stripe_webhook():
    """Handle Stripe webhook events."""
    payload = request.get_data()
    signature = request.headers.get("Stripe-Signature")

    result = handle_stripe_webhook(payload, signature)

    if result.get("event") == "payment_completed":
        deal_id = result.get("deal_id")
        deal = Deal.query.filter_by(deal_id=deal_id).first()

        if deal:
            # Find and update pending payment
            payment = Payment.query.filter_by(
                deal_id=deal.id,
                status='pending'
            ).first()

            if payment:
                payment.status = 'verified'
                payment.verified_at = datetime.utcnow()
                db.session.commit()

    return jsonify({"received": True})


# --- COINBASE COMMERCE CRYPTO PAYMENTS ---

@app.route("/pay/crypto/<deal_id>")
@login_required
def pay_with_crypto(deal_id):
    """Create Coinbase Commerce charge and redirect."""
    deal = Deal.query.filter_by(deal_id=deal_id, is_active=True).first()
    if not deal:
        flash("Deal not found or expired.", "error")
        return redirect("/deals")

    result = create_coinbase_charge(
        deal_id=deal_id,
        fee_usd=deal.platform_fee_usd,
        user_email=current_user.email,
        redirect_url=request.host_url + "pay/crypto/success",
        cancel_url=request.host_url + f"pay/{deal_id}"
    )

    if "error" in result:
        flash(f"Crypto payment error: {result['error']}", "error")
        return redirect(f"/pay/{deal_id}")

    # Store pending payment with charge code
    payment = Payment(
        user_id=current_user.id,
        deal_id=deal.id,
        expected_xrp=0,  # Crypto payment, tracked differently
        status='pending',
        destination_tag=0,
        tx_hash=result.get("charge_code")  # Store charge code temporarily
    )
    db.session.add(payment)
    db.session.commit()

    # Redirect to Coinbase Commerce hosted checkout
    return redirect(result["hosted_url"])


@app.route("/pay/crypto/success")
@login_required
def crypto_payment_success():
    """Handle successful Coinbase Commerce payment."""
    deal_id = request.args.get("deal_id")

    if not deal_id:
        flash("Invalid payment session.", "error")
        return redirect("/deals")

    # Find the pending payment with charge code
    deal = Deal.query.filter_by(deal_id=deal_id).first()
    if deal:
        payment = Payment.query.filter_by(
            user_id=current_user.id,
            deal_id=deal.id,
            status='pending'
        ).first()

        if payment and payment.tx_hash:
            # Verify the charge
            result = verify_coinbase_charge(payment.tx_hash)

            if result.get("verified"):
                payment.status = 'verified'
                payment.verified_at = datetime.utcnow()
                db.session.commit()

                flash("Crypto payment successful! Here's your deal.", "success")
                return redirect(f"/deal/{deal_id}/access")

    flash("Payment verification pending. It may take a few minutes to confirm.", "info")
    return redirect(f"/pay/{deal_id}")


@app.route("/pay/verify/crypto", methods=["POST"])
@login_required
def verify_crypto_payment_route():
    """Verify Coinbase Commerce payment."""
    data = request.get_json()
    charge_code = data.get("charge_code")
    deal_id = data.get("deal_id")

    result = verify_coinbase_charge(charge_code)

    if result.get("verified"):
        # Update payment record
        deal = Deal.query.filter_by(deal_id=deal_id).first()
        if deal:
            payment = Payment.query.filter_by(
                user_id=current_user.id,
                deal_id=deal.id,
                status='pending'
            ).first()

            if payment:
                payment.status = 'verified'
                payment.verified_at = datetime.utcnow()
                payment.tx_hash = result.get("tx_hash", charge_code)
                db.session.commit()

    return jsonify(result)


@app.route("/pay/webhook/coinbase", methods=["POST"])
def coinbase_webhook():
    """Handle Coinbase Commerce webhook events."""
    payload = request.get_data()
    signature = request.headers.get("X-CC-Webhook-Signature", "")

    result = handle_coinbase_webhook(payload, signature)

    if result.get("event") == "payment_completed":
        deal_id = result.get("deal_id")
        charge_code = result.get("charge_code")

        deal = Deal.query.filter_by(deal_id=deal_id).first()
        if deal:
            # Find payment by charge code
            payment = Payment.query.filter_by(
                deal_id=deal.id,
                tx_hash=charge_code,
                status='pending'
            ).first()

            if payment:
                payment.status = 'verified'
                payment.verified_at = datetime.utcnow()
                db.session.commit()
                logger.info(f"Coinbase webhook: Payment verified for deal {deal_id}")

    return jsonify({"received": True})


# --- P2P BOOKING FLOW ---

P2P_BOOK_CONTENT = """
<style>
.p2p-hero { background: linear-gradient(135deg, #1a0a2e 0%, #0d1b2a 50%, #1b2838 100%); padding: 40px; border-radius: 16px; color: white; margin-bottom: 30px; }
.p2p-hero h1 { margin: 0 0 10px 0; font-size: 28px; }
.p2p-hero .subtitle { color: #fff; font-size: 16px; }
.p2p-step { display: flex; gap: 20px; margin-bottom: 30px; }
.p2p-step-number { width: 40px; height: 40px; border-radius: 50%; background: #ff6b35; color: white; display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 18px; flex-shrink: 0; }
.p2p-step-content { flex: 1; }
.p2p-step-content h3 { margin: 5px 0 8px 0; }
.p2p-step-content p { color: #666; margin: 0; }
.flight-summary { background: #f8f9fa; padding: 20px; border-radius: 12px; margin-bottom: 20px; }
.flight-summary .route { font-size: 24px; font-weight: bold; margin-bottom: 5px; }
.flight-summary .details { color: #666; }
.price-compare { display: flex; gap: 20px; margin: 20px 0; }
.price-box { flex: 1; padding: 15px; border-radius: 8px; text-align: center; }
.price-box.us { background: #f8d7da; }
.price-box.target { background: #d4edda; border: 2px solid #28a745; }
.price-box .label { font-size: 13px; color: #666; margin-bottom: 5px; }
.price-box .amount { font-size: 28px; font-weight: bold; }
.price-box.target .amount { color: #155724; }
.escrow-info { background: linear-gradient(135deg, #1a0a2e, #0d1b2a); padding: 20px; border-radius: 12px; color: white; margin: 20px 0; }
.escrow-info h3 { color: #ff6b35; margin-top: 0; }
.escrow-row { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,0.1); }
.escrow-row:last-child { border-bottom: none; }
.passenger-form .form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-bottom: 15px; }
.passenger-form label { display: block; font-size: 13px; color: #666; margin-bottom: 4px; }
.passenger-form input { width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 6px; font-size: 14px; box-sizing: border-box; }
.passenger-form input:focus { outline: none; border-color: #ff6b35; }
</style>

<div class="p2p-hero">
    <h1>Book via P2P Network</h1>
    <p class="subtitle">A verified helper in the <span class="market-tag" style="background: rgba(255,255,255,0.2);">{{ market }}</span> market will book this flight for you at the local price. Secured by XRPL escrow.</p>
</div>

<div class="flight-summary">
    <div class="route">{{ origin }} → {{ destination }}</div>
    <div class="details">{{ flight_number }} | {{ date }}</div>
</div>

<div class="price-compare">
    <div class="price-box us">
        <div class="label">US Price</div>
        <div class="amount">${{ us_price }}</div>
    </div>
    <div class="price-box target">
        <div class="label">{{ market }} Market Price</div>
        <div class="amount">${{ target_price }}</div>
    </div>
</div>

<div style="text-align: center; margin: 15px 0;">
    <span class="savings-badge" style="font-size: 18px; padding: 8px 20px;">You Save ${{ "%.2f"|format(savings) }}</span>
</div>

<div class="card" style="margin-top: 30px;">
    <h2>How P2P Booking Works</h2>
    <div class="p2p-step">
        <div class="p2p-step-number">1</div>
        <div class="p2p-step-content">
            <h3>Lock RLUSD in Escrow</h3>
            <p>Your funds are locked in a trustless XRPL smart contract. Both you and the helper can verify on-chain.</p>
        </div>
    </div>
    <div class="p2p-step">
        <div class="p2p-step-number">2</div>
        <div class="p2p-step-content">
            <h3>Helper Books Your Flight</h3>
            <p>A verified helper in the {{ market }} market grants Phoenix temporary browser access. Phoenix automates the booking on their device.</p>
        </div>
    </div>
    <div class="p2p-step">
        <div class="p2p-step-number">3</div>
        <div class="p2p-step-content">
            <h3>Confirmation & Payment</h3>
            <p>Once booking is confirmed, escrow releases — helper gets reimbursed + 5% cut, you get your ticket at the foreign price.</p>
        </div>
    </div>
</div>

<div class="escrow-info">
    <h3>Escrow Breakdown</h3>
    <div class="escrow-row">
        <span>Flight cost ({{ market }} price)</span>
        <span>{{ "%.2f"|format(target_price_float) }} RLUSD</span>
    </div>
    <div class="escrow-row">
        <span>Helper cut (5%)</span>
        <span>{{ "%.2f"|format(helper_cut) }} RLUSD</span>
    </div>
    <div class="escrow-row">
        <span>Platform fee (3%)</span>
        <span>{{ "%.2f"|format(platform_fee) }} RLUSD</span>
    </div>
    <div class="escrow-row" style="font-weight: bold; font-size: 18px; padding-top: 12px; border-top: 2px solid rgba(255,255,255,0.3);">
        <span>Total Escrow Amount</span>
        <span style="color: #ff6b35;">{{ "%.2f"|format(total_escrow) }} RLUSD</span>
    </div>
</div>

<div class="card" style="margin-top: 30px;">
    <h2>Passenger Details</h2>
    <form method="POST" action="/p2p/book/confirm" class="passenger-form">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <input type="hidden" name="origin" value="{{ origin }}">
        <input type="hidden" name="destination" value="{{ destination }}">
        <input type="hidden" name="date" value="{{ date }}">
        <input type="hidden" name="flight_number" value="{{ flight_number }}">
        <input type="hidden" name="market" value="{{ market }}">
        <input type="hidden" name="target_price" value="{{ target_price }}">
        <input type="hidden" name="us_price" value="{{ us_price }}">

        <div class="form-row">
            <div>
                <label>First Name (as on passport)</label>
                <input type="text" name="first_name" required>
            </div>
            <div>
                <label>Last Name (as on passport)</label>
                <input type="text" name="last_name" required>
            </div>
        </div>
        <div class="form-row">
            <div>
                <label>Email (for e-ticket delivery)</label>
                <input type="email" name="email" required value="{{ current_user.email if current_user.is_authenticated else '' }}">
            </div>
            <div>
                <label>Phone Number</label>
                <input type="tel" name="phone">
            </div>
        </div>
        <div class="form-row">
            <div>
                <label>Date of Birth</label>
                <input type="date" name="dob">
            </div>
            <div>
                <label>Passport/ID Number (optional)</label>
                <input type="text" name="passport">
            </div>
        </div>

        <div style="margin-top: 15px; padding: 15px; background: #fff3cd; border-radius: 8px; color: #664d03;">
            <strong>XRPL Wallet Required:</strong> You need an XRPL wallet with at least {{ "%.2f"|format(total_escrow) }} RLUSD to lock in escrow.
            {% if not current_user.is_authenticated %}
                <br><a href="/login" style="color: #ff6b35;">Log in</a> or <a href="/register" style="color: #ff6b35;">create an account</a> to continue.
            {% endif %}
        </div>

        <button type="submit" class="btn" style="width: 100%; margin-top: 20px; padding: 15px; font-size: 18px; background: #ff6b35; border-color: #ff6b35;">
            Proceed to XRPL Escrow — {{ "%.2f"|format(total_escrow) }} RLUSD
        </button>
    </form>
</div>

<div class="card" style="margin-top: 20px; background: #f0f7ff;">
    <p style="text-align: center; color: #004085; margin: 0;">
        Secured by <strong>XRPL Escrow</strong> — funds are locked on-chain and only release on confirmed booking.
        <br><small>Both buyer and helper can independently verify the escrow on the XRP Ledger.</small>
    </p>
</div>
"""

P2P_STATUS_CONTENT = """
<style>
.status-timeline { position: relative; padding-left: 40px; margin: 30px 0; }
.status-timeline::before { content: ''; position: absolute; left: 15px; top: 0; bottom: 0; width: 2px; background: #ddd; }
.timeline-step { position: relative; margin-bottom: 25px; }
.timeline-step .dot { position: absolute; left: -33px; width: 16px; height: 16px; border-radius: 50%; border: 2px solid #ddd; background: white; }
.timeline-step.completed .dot { background: #28a745; border-color: #28a745; }
.timeline-step.active .dot { background: #ff6b35; border-color: #ff6b35; animation: pulse 2s infinite; }
.timeline-step.failed .dot { background: #dc3545; border-color: #dc3545; }
.timeline-step h4 { margin: 0 0 4px 0; }
.timeline-step p { margin: 0; color: #666; font-size: 14px; }
.timeline-step .time { color: #fff; font-size: 12px; }
@keyframes pulse { 0%, 100% { box-shadow: 0 0 0 0 rgba(255,107,53,0.4); } 50% { box-shadow: 0 0 0 8px rgba(255,107,53,0); } }
</style>

<h1>P2P Transaction Status</h1>

<div class="flight-summary" style="background: #f8f9fa; padding: 20px; border-radius: 12px;">
    <div style="font-size: 24px; font-weight: bold;">{{ transaction.origin }} → {{ transaction.destination }}</div>
    <div style="color: #666;">{{ transaction.airline or '' }} {{ transaction.flight_number or '' }} | {{ transaction.departure_date }}</div>
    <div style="margin-top: 10px;">
        <span style="padding: 4px 12px; border-radius: 20px; font-size: 14px; font-weight: 600;
            {% if transaction.status == 'completed' %}background: #d4edda; color: #155724;
            {% elif transaction.status == 'failed' %}background: #f8d7da; color: #842029;
            {% elif transaction.status == 'cancelled' %}background: #e2e3e5; color: #41464b;
            {% else %}background: #fff3cd; color: #664d03;{% endif %}">
            {{ transaction.status|upper }}
        </span>
        <span style="color: #666; margin-left: 10px;">ID: {{ transaction.transaction_id[:12] }}...</span>
    </div>
</div>

<div class="card" style="margin-top: 20px;">
    <h2>Transaction Timeline</h2>
    <div class="status-timeline">
        {% set steps = [
            ('Requested', transaction.created_at, 'requested'),
            ('Helper Matched', transaction.matched_at, 'matched'),
            ('Escrow Locked', transaction.escrow_locked_at, 'escrow_locked'),
            ('Helper Accepted', transaction.escrow_verified_at, 'helper_accepted'),
            ('Purchase Started', transaction.purchase_started_at, 'purchasing'),
            ('Booking Confirmed', transaction.confirmed_at, 'confirmed'),
            ('Completed', transaction.completed_at, 'completed')
        ] %}
        {% set status_order = ['requested', 'matched', 'escrow_locked', 'helper_accepted', 'purchasing', 'confirmed', 'completed'] %}
        {% set current_idx = status_order.index(transaction.status) if transaction.status in status_order else -1 %}
        {% for label, timestamp, step_status in steps %}
            {% set step_idx = loop.index0 %}
            <div class="timeline-step {{ 'completed' if step_idx < current_idx else ('active' if step_idx == current_idx else ('failed' if transaction.status in ['failed', 'cancelled'] and step_idx == current_idx else '')) }}">
                <div class="dot"></div>
                <h4>{{ label }}</h4>
                {% if timestamp %}
                    <p class="time">{{ timestamp.strftime('%Y-%m-%d %H:%M UTC') }}</p>
                {% endif %}
            </div>
        {% endfor %}
    </div>
</div>

{% if transaction.status == 'completed' and transaction.confirmation_code %}
<div class="card" style="margin-top: 20px; border: 2px solid #28a745;">
    <h2 style="color: #28a745;">Booking Confirmed</h2>
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px;">
        <div>
            <div style="color: #666; font-size: 13px;">Confirmation Code</div>
            <div style="font-size: 24px; font-weight: bold; font-family: monospace;">{{ transaction.confirmation_code }}</div>
        </div>
        <div>
            <div style="color: #666; font-size: 13px;">Passenger</div>
            <div style="font-size: 18px;">{{ transaction.passenger_name }}</div>
        </div>
    </div>
    {% if transaction.eticket_url %}
        <a href="{{ transaction.eticket_url }}" target="_blank" class="btn" style="margin-top: 15px; display: inline-block;">Download E-Ticket</a>
    {% endif %}
</div>
{% endif %}

<div class="card" style="margin-top: 20px;">
    <h2>Financial Summary</h2>
    <div class="price-row">
        <span>US Market Price:</span>
        <span>${{ "%.2f"|format(transaction.us_price_usd or 0) }}</span>
    </div>
    <div class="price-row">
        <span>{{ transaction.target_market }} Market Price:</span>
        <span>${{ "%.2f"|format(transaction.target_price_usd or 0) }}</span>
    </div>
    <div class="price-row" style="color: #28a745; font-weight: bold;">
        <span>Your Savings:</span>
        <span>${{ "%.2f"|format(transaction.savings_usd or 0) }}</span>
    </div>
    <hr>
    <div class="price-row">
        <span>Escrow Amount:</span>
        <span>{{ "%.2f"|format(transaction.escrow_amount_rlusd or 0) }} RLUSD</span>
    </div>
    {% if transaction.escrow_tx_hash %}
    <div class="price-row">
        <span>Escrow TX:</span>
        <span style="font-family: monospace; font-size: 12px;">
            <a href="https://testnet.xrpscan.com/tx/{{ transaction.escrow_tx_hash }}" target="_blank">
                {{ transaction.escrow_tx_hash[:16] }}...
            </a>
        </span>
    </div>
    {% endif %}
</div>

{% if transaction.status not in ['completed', 'failed', 'cancelled'] %}
<div style="text-align: center; margin-top: 20px;">
    <form method="POST" action="/p2p/cancel/{{ transaction.transaction_id }}" style="display: inline;">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <button type="submit" class="btn btn-secondary" onclick="return confirm('Cancel this P2P booking?');">Cancel Transaction</button>
    </form>
</div>
{% endif %}

<script>
{% if transaction.status not in ['completed', 'failed', 'cancelled'] %}
// Auto-refresh every 15 seconds for active transactions
setTimeout(() => location.reload(), 15000);
{% endif %}
</script>
"""


@app.route("/p2p/book")
@login_required
def p2p_book_page():
    """P2P booking page — shows flight details, escrow breakdown, and passenger form."""
    origin = request.args.get('origin', '')
    destination = request.args.get('destination', '')
    date = request.args.get('date', '')
    flight_number = request.args.get('flight', '')
    market = request.args.get('market', '')
    target_price = request.args.get('price', '0')
    us_price = request.args.get('us_price', target_price)

    target_price_float = float(target_price)
    us_price_float = float(us_price)
    savings = us_price_float - target_price_float

    # Calculate escrow amounts (same as payments.py calculate_p2p_amounts)
    helper_cut = target_price_float * 0.05
    platform_fee = target_price_float * 0.03
    total_escrow = target_price_float + helper_cut + platform_fee

    return render_template_string(
        BASE_TEMPLATE,
        title="Book via P2P",
        content=render_template_string(
            P2P_BOOK_CONTENT,
            origin=origin,
            destination=destination,
            date=date,
            flight_number=flight_number,
            market=market,
            target_price=target_price,
            us_price=us_price,
            target_price_float=target_price_float,
            savings=savings,
            helper_cut=helper_cut,
            platform_fee=platform_fee,
            total_escrow=total_escrow
        ),
        current_user=current_user
    )


@app.route("/p2p/book/confirm", methods=["POST"])
@login_required
def p2p_book_confirm():
    """Process P2P booking request — creates transaction and initiates workflow."""
    from p2p_orchestrator import get_orchestrator

    origin = request.form.get('origin')
    destination = request.form.get('destination')
    date = request.form.get('date')
    flight_number = request.form.get('flight_number')
    market = request.form.get('market')
    target_price = float(request.form.get('target_price', 0))
    us_price = float(request.form.get('us_price', 0))
    first_name = request.form.get('first_name', '')
    last_name = request.form.get('last_name', '')
    email = request.form.get('email', '')

    # Get buyer's wallet
    wallet = UserWallet.query.filter_by(user_id=current_user.id, is_primary=True).first()
    if not wallet:
        wallet = UserWallet.query.filter_by(user_id=current_user.id).first()

    if not wallet:
        flash("Please add an XRPL wallet to your account first.", "error")
        return redirect("/wallet")

    flight_data = {
        'origin': origin,
        'destination': destination,
        'departure_date': date,
        'flight_number': flight_number,
        'target_market': market,
        'target_price_usd': target_price,
        'us_price_usd': us_price,
        'passenger_name': f"{first_name} {last_name}",
        'passenger_email': email,
    }

    orchestrator = get_orchestrator(db.session)
    result = orchestrator.run_full_workflow(
        buyer_id=current_user.id,
        buyer_wallet_address=wallet.wallet_address,
        flight_data=flight_data
    )

    if result.get('success'):
        flash("P2P booking initiated! Your funds will be locked in escrow.", "success")
        return redirect(f"/p2p/status/{result['transaction_id']}")
    else:
        flash(f"Failed to initiate P2P booking: {result.get('error', 'Unknown error')}", "error")
        return redirect("/search")


@app.route("/p2p/status/<transaction_id>")
@login_required
def p2p_status_page(transaction_id):
    """View P2P transaction status with timeline."""
    transaction = P2PTransaction.query.filter_by(transaction_id=transaction_id).first_or_404()

    # Only allow buyer or admin to view
    if transaction.buyer_id != current_user.id and not current_user.is_admin:
        abort(403)

    return render_template_string(
        BASE_TEMPLATE,
        title="P2P Booking Status",
        content=render_template_string(
            P2P_STATUS_CONTENT,
            transaction=transaction
        ),
        current_user=current_user
    )


@app.route("/p2p/cancel/<transaction_id>", methods=["POST"])
@login_required
def p2p_cancel(transaction_id):
    """Cancel a P2P transaction."""
    from p2p_orchestrator import get_orchestrator

    transaction = P2PTransaction.query.filter_by(transaction_id=transaction_id).first_or_404()

    if transaction.buyer_id != current_user.id and not current_user.is_admin:
        abort(403)

    orchestrator = get_orchestrator(db.session)
    result = orchestrator.cancel_transaction(transaction_id, cancelled_by='buyer')

    if result.get('success'):
        flash("Transaction cancelled. Any escrowed funds will be returned.", "info")
    else:
        flash(f"Could not cancel: {result.get('error', 'Unknown error')}", "error")

    return redirect(f"/p2p/status/{transaction_id}")


@app.route("/p2p/my-bookings")
@login_required
def p2p_my_bookings():
    """View all P2P bookings for the current user."""
    transactions = P2PTransaction.query.filter_by(buyer_id=current_user.id).order_by(
        P2PTransaction.created_at.desc()
    ).all()

    rows = ""
    for t in transactions:
        status_color = {
            'completed': '#d4edda', 'failed': '#f8d7da', 'cancelled': '#e2e3e5'
        }.get(t.status, '#fff3cd')
        status_text_color = {
            'completed': '#155724', 'failed': '#842029', 'cancelled': '#41464b'
        }.get(t.status, '#664d03')

        rows += f"""
        <tr style="border-bottom: 1px solid #eee; cursor: pointer;" onclick="location.href='/p2p/status/{t.transaction_id}'">
            <td style="padding: 12px;">{t.origin} → {t.destination}</td>
            <td>{t.departure_date or 'N/A'}</td>
            <td><span class="market-tag">{t.target_market or 'N/A'}</span></td>
            <td style="color: #28a745;">${(t.savings_usd or 0):.2f}</td>
            <td>{(t.escrow_amount_rlusd or 0):.2f} RLUSD</td>
            <td><span style="padding: 2px 8px; border-radius: 12px; font-size: 12px; font-weight: 600; background: {status_color}; color: {status_text_color};">{t.status}</span></td>
            <td>{t.confirmation_code or '-'}</td>
        </tr>
        """

    content = f"""
    <h1>My P2P Bookings</h1>
    <p style="color: #666;">Click any booking to view full details and status.</p>

    <div class="card">
        {'<table style="width: 100%; border-collapse: collapse;"><tr style="text-align: left; border-bottom: 2px solid #eee;"><th style="padding: 12px;">Route</th><th>Date</th><th>Market</th><th>Savings</th><th>Escrow</th><th>Status</th><th>Confirmation</th></tr>' + rows + '</table>' if transactions else '<p style="color: #666;">No P2P bookings yet. <a href="/search">Search for flights</a> to find savings.</p>'}
    </div>
    """

    return render_template_string(
        BASE_TEMPLATE,
        title="My P2P Bookings",
        content=content,
        current_user=current_user
    )


# --- ADMIN DASHBOARD ---

def admin_required(f):
    """Decorator to require admin access."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash("Please log in to access this page.", "error")
            return redirect("/login")
        if not current_user.is_admin:
            flash("Admin access required.", "error")
            return redirect("/dashboard")
        return f(*args, **kwargs)
    return decorated_function


ADMIN_NAV = """
<nav style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:20px;padding:12px 16px;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:8px;">
    <a href="/admin" style="padding:6px 14px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:600;color:#e8e8e8;background:rgba(255,255,255,0.08);transition:background 0.2s;" onmouseover="this.style.background='rgba(255,107,53,0.3)'" onmouseout="this.style.background='rgba(255,255,255,0.08)'">Dashboard</a>
    <a href="/admin/payments" style="padding:6px 14px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:600;color:#e8e8e8;background:rgba(255,255,255,0.08);transition:background 0.2s;" onmouseover="this.style.background='rgba(255,107,53,0.3)'" onmouseout="this.style.background='rgba(255,255,255,0.08)'">Payments</a>
    <a href="/admin/users" style="padding:6px 14px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:600;color:#e8e8e8;background:rgba(255,255,255,0.08);transition:background 0.2s;" onmouseover="this.style.background='rgba(255,107,53,0.3)'" onmouseout="this.style.background='rgba(255,255,255,0.08)'">Users</a>
    <a href="/admin/deals" style="padding:6px 14px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:600;color:#e8e8e8;background:rgba(255,255,255,0.08);transition:background 0.2s;" onmouseover="this.style.background='rgba(255,107,53,0.3)'" onmouseout="this.style.background='rgba(255,255,255,0.08)'">Deals</a>
    <a href="/admin/wallet" style="padding:6px 14px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:600;color:#e8e8e8;background:rgba(255,255,255,0.08);transition:background 0.2s;" onmouseover="this.style.background='rgba(255,107,53,0.3)'" onmouseout="this.style.background='rgba(255,255,255,0.08)'">Wallet</a>
    <a href="/admin/proxies" style="padding:6px 14px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:600;color:#e8e8e8;background:rgba(255,255,255,0.08);transition:background 0.2s;" onmouseover="this.style.background='rgba(255,107,53,0.3)'" onmouseout="this.style.background='rgba(255,255,255,0.08)'">Proxies</a>
    <a href="/admin/p2p" style="padding:6px 14px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:600;color:#ff6b35;background:rgba(255,107,53,0.1);transition:background 0.2s;" onmouseover="this.style.background='rgba(255,107,53,0.3)'" onmouseout="this.style.background='rgba(255,107,53,0.1)'">P2P</a>
    <a href="/admin/helpers" style="padding:6px 14px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:600;color:#e8e8e8;background:rgba(255,255,255,0.08);transition:background 0.2s;" onmouseover="this.style.background='rgba(255,107,53,0.3)'" onmouseout="this.style.background='rgba(255,255,255,0.08)'">Helpers</a>
    <a href="/admin/tasks" style="padding:6px 14px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:600;color:#e8e8e8;background:rgba(255,255,255,0.08);transition:background 0.2s;" onmouseover="this.style.background='rgba(255,107,53,0.3)'" onmouseout="this.style.background='rgba(255,255,255,0.08)'">Tasks</a>
    <a href="/admin/nodes" style="padding:6px 14px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:600;color:#0f9d58;background:rgba(15,157,88,0.1);transition:background 0.2s;" onmouseover="this.style.background='rgba(15,157,88,0.3)'" onmouseout="this.style.background='rgba(15,157,88,0.1)'">Nodes</a>
    <a href="/admin/payouts" style="padding:6px 14px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:600;color:#e8e8e8;background:rgba(255,255,255,0.08);transition:background 0.2s;" onmouseover="this.style.background='rgba(255,107,53,0.3)'" onmouseout="this.style.background='rgba(255,255,255,0.08)'">Payouts</a>
    <a href="/admin/node-consent" style="padding:6px 14px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:600;color:#00bcd4;background:rgba(0,188,212,0.1);transition:background 0.2s;" onmouseover="this.style.background='rgba(0,188,212,0.3)'" onmouseout="this.style.background='rgba(0,188,212,0.1)'">Consent Economy</a>
</nav>
"""

ADMIN_DASHBOARD_CONTENT = """
""" + ADMIN_NAV + """
<h1>Admin Dashboard</h1>
<p style="color: #666;">Welcome, {{ user.name or user.email }}. Here's your business overview.</p>

<div class="stats">
    <div class="stat-card">
        <div class="stat-value">{{ "%.4f"|format(total_xrp_received) }}</div>
        <div class="stat-label">Total XRP Received</div>
    </div>
    <div class="stat-card">
        <div class="stat-value">${{ "%.2f"|format(total_usd_value) }}</div>
        <div class="stat-label">USD Value (current rate)</div>
    </div>
    <div class="stat-card">
        <div class="stat-value">{{ verified_payments }}</div>
        <div class="stat-label">Verified Payments</div>
    </div>
    <div class="stat-card">
        <div class="stat-value">{{ total_users }}</div>
        <div class="stat-label">Total Users</div>
    </div>
</div>

<div class="stats">
    <div class="stat-card">
        <div class="stat-value">{{ pending_payments }}</div>
        <div class="stat-label">Pending Payments</div>
    </div>
    <div class="stat-card">
        <div class="stat-value">{{ active_deals }}</div>
        <div class="stat-label">Active Deals</div>
    </div>
    <div class="stat-card">
        <div class="stat-value">${{ "%.2f"|format(xrp_price) }}</div>
        <div class="stat-label">XRP Price</div>
    </div>
    <div class="stat-card">
        <div class="stat-value">{{ network }}</div>
        <div class="stat-label">Network</div>
    </div>
</div>

<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-top: 20px;">
    <a href="/admin/payments" class="card" style="text-decoration: none; color: inherit;">
        <h3>Payment Monitor</h3>
        <p style="color: #666;">View all payments, filter by status, export data</p>
    </a>
    <a href="/admin/users" class="card" style="text-decoration: none; color: inherit;">
        <h3>User Management</h3>
        <p style="color: #666;">View users, manage accounts, see activity</p>
    </a>
    <a href="/admin/deals" class="card" style="text-decoration: none; color: inherit;">
        <h3>Deal Management</h3>
        <p style="color: #666;">View active deals, expire deals, manage listings</p>
    </a>
    <a href="/admin/wallet" class="card" style="text-decoration: none; color: inherit;">
        <h3>Wallet Info</h3>
        <p style="color: #666;">View wallet balance, recent transactions</p>
    </a>
    <a href="/admin/proxies" class="card" style="text-decoration: none; color: inherit;">
        <h3>Proxy Config</h3>
        <p style="color: #666;">Manage regional proxies, test connections</p>
    </a>
    <a href="/admin/p2p" class="card" style="text-decoration: none; color: inherit; border: 1px solid #ff6b35;">
        <h3 style="color: #ff6b35;">P2P Network</h3>
        <p style="color: #666;">Manage helpers, transactions, escrows</p>
    </a>
    <a href="/admin/helpers" class="card" style="text-decoration: none; color: inherit;">
        <h3>Helper Approvals</h3>
        <p style="color: #666;">Review and approve helper applications</p>
    </a>
</div>

<div class="card" style="margin-top: 20px;">
    <h2>Recent Payments</h2>
    {% if recent_payments %}
        <table style="width: 100%; border-collapse: collapse;">
            <tr style="text-align: left; border-bottom: 2px solid #eee;">
                <th style="padding: 10px;">Date</th>
                <th>User</th>
                <th>Amount (XRP)</th>
                <th>USD Value</th>
                <th>TX Hash</th>
                <th>Status</th>
            </tr>
            {% for payment in recent_payments %}
            <tr style="border-bottom: 1px solid #eee;">
                <td style="padding: 10px;">{{ payment.created_at.strftime('%Y-%m-%d %H:%M') if payment.created_at else 'N/A' }}</td>
                <td>{{ payment.user.email if payment.user else 'Unknown' }}</td>
                <td>{{ "%.4f"|format(payment.received_xrp or payment.expected_xrp or 0) }}</td>
                <td>${{ "%.2f"|format((payment.received_xrp or payment.expected_xrp or 0) * xrp_price) }}</td>
                <td style="font-family: monospace; font-size: 11px;">{{ (payment.tx_hash[:16] + '...') if payment.tx_hash else 'Pending' }}</td>
                <td><span class="status-badge status-{{ payment.status }}">{{ payment.status }}</span></td>
            </tr>
            {% endfor %}
        </table>
        <p style="margin-top: 15px;"><a href="/admin/payments">View all payments →</a></p>
    {% else %}
        <p style="color: #666;">No payments yet. Payments will appear here as users pay for deals.</p>
    {% endif %}
</div>

<div class="card" style="margin-top: 20px;">
    <h2>Today's Summary</h2>
    <div class="price-row">
        <span>Payments today:</span>
        <span><strong>{{ today_payments }}</strong></span>
    </div>
    <div class="price-row">
        <span>XRP received today:</span>
        <span><strong>{{ "%.4f"|format(today_xrp) }} XRP</strong></span>
    </div>
    <div class="price-row">
        <span>New users today:</span>
        <span><strong>{{ today_users }}</strong></span>
    </div>
</div>

<div class="card" style="margin-top: 20px; border-left: 4px solid #ff6b35;">
    <h2 style="color: #ff6b35;">P2P Network Overview</h2>
    <div class="stats">
        <div class="stat-card">
            <div class="stat-value">{{ p2p_active_helpers }}</div>
            <div class="stat-label">Active Helpers</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{{ p2p_pending_helpers }}</div>
            <div class="stat-label">Pending Approval</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{{ p2p_total_transactions }}</div>
            <div class="stat-label">P2P Transactions</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{{ "%.2f"|format(p2p_total_rlusd) }}</div>
            <div class="stat-label">RLUSD Volume</div>
        </div>
    </div>
    <p style="margin-top: 10px;"><a href="/admin/p2p">Manage P2P Network →</a></p>
</div>
"""

ADMIN_PAYMENTS_CONTENT = """
""" + ADMIN_NAV + """
<h1>Payment Monitor</h1>

<div class="card">
    <h2>Filter Payments</h2>
    <form method="GET" style="display: flex; gap: 15px; flex-wrap: wrap; align-items: end;">
        <div class="form-group" style="margin: 0;">
            <label>Status</label>
            <select name="status" style="padding: 8px; border: 1px solid #ddd; border-radius: 4px;">
                <option value="">All</option>
                <option value="verified" {{ 'selected' if filter_status == 'verified' else '' }}>Verified</option>
                <option value="pending" {{ 'selected' if filter_status == 'pending' else '' }}>Pending</option>
                <option value="expired" {{ 'selected' if filter_status == 'expired' else '' }}>Expired</option>
            </select>
        </div>
        <button type="submit" class="btn">Filter</button>
        <a href="/admin/payments/export?status={{ filter_status or '' }}" class="btn btn-secondary">Export CSV</a>
    </form>
</div>

<div class="card">
    <h2>Payments ({{ payments|length }} total)</h2>
    {% if payments %}
        <table style="width: 100%; border-collapse: collapse;">
            <tr style="text-align: left; border-bottom: 2px solid #eee;">
                <th style="padding: 10px;">ID</th>
                <th>Date</th>
                <th>User</th>
                <th>Deal</th>
                <th>Expected</th>
                <th>Received</th>
                <th>TX Hash</th>
                <th>Status</th>
            </tr>
            {% for payment in payments %}
            <tr style="border-bottom: 1px solid #eee;">
                <td style="padding: 10px;">#{{ payment.id }}</td>
                <td>{{ payment.created_at.strftime('%Y-%m-%d %H:%M') if payment.created_at else 'N/A' }}</td>
                <td>{{ payment.user.email if payment.user else 'N/A' }}</td>
                <td>{{ payment.deal.deal_id if payment.deal else 'N/A' }}</td>
                <td>{{ "%.4f"|format(payment.expected_xrp or 0) }} XRP</td>
                <td>{{ "%.4f"|format(payment.received_xrp or 0) }} XRP</td>
                <td style="font-family: monospace; font-size: 11px;">
                    {% if payment.tx_hash %}
                        <a href="https://{{ 'testnet.' if network == 'TESTNET' else '' }}xrpscan.com/tx/{{ payment.tx_hash }}" target="_blank">
                            {{ payment.tx_hash[:12] }}...
                        </a>
                    {% else %}
                        -
                    {% endif %}
                </td>
                <td><span class="status-badge status-{{ payment.status }}">{{ payment.status }}</span></td>
            </tr>
            {% endfor %}
        </table>
    {% else %}
        <p style="color: #666;">No payments found matching your criteria.</p>
    {% endif %}
</div>

<div class="card">
    <h2>Payment Statistics</h2>
    <div class="price-row">
        <span>Total verified:</span>
        <span><strong>{{ "%.4f"|format(total_verified_xrp) }} XRP</strong> (${{ "%.2f"|format(total_verified_xrp * xrp_price) }})</span>
    </div>
    <div class="price-row">
        <span>Pending verification:</span>
        <span><strong>{{ "%.4f"|format(total_pending_xrp) }} XRP</strong></span>
    </div>
    <div class="price-row">
        <span>Expired (missed):</span>
        <span><strong>{{ "%.4f"|format(total_expired_xrp) }} XRP</strong></span>
    </div>
</div>
"""

ADMIN_USERS_CONTENT = """
""" + ADMIN_NAV + """
<h1>User Management</h1>

<div class="card">
    <h2>All Users ({{ users|length }} total)</h2>
    {% if users %}
        <table style="width: 100%; border-collapse: collapse;">
            <tr style="text-align: left; border-bottom: 2px solid #eee;">
                <th style="padding: 10px;">ID</th>
                <th>Email</th>
                <th>Name</th>
                <th>Joined</th>
                <th>Last Login</th>
                <th>Payments</th>
                <th>Total XRP</th>
                <th>Status</th>
            </tr>
            {% for user in users %}
            <tr style="border-bottom: 1px solid #eee;">
                <td style="padding: 10px;">#{{ user.id }}</td>
                <td>{{ user.email }}</td>
                <td>{{ user.name or '-' }}</td>
                <td>{{ user.created_at.strftime('%Y-%m-%d') if user.created_at else 'N/A' }}</td>
                <td>{{ user.last_login.strftime('%Y-%m-%d %H:%M') if user.last_login else 'Never' }}</td>
                <td>{{ user.payments.count() }}</td>
                <td>{{ "%.4f"|format(user.payments.filter_by(status='verified').with_entities(db.func.sum(Payment.received_xrp)).scalar() or 0) }}</td>
                <td>
                    {% if user.is_admin %}<span class="tag">Admin</span>{% endif %}
                    {% if user.is_verified %}<span class="tag" style="background:#d4edda;color:#155724;">Verified</span>{% endif %}
                    {% if not user.is_active %}<span class="tag tag-warning">Inactive</span>{% endif %}
                </td>
            </tr>
            {% endfor %}
        </table>
    {% else %}
        <p style="color: #666;">No users found.</p>
    {% endif %}
</div>
"""

ADMIN_WALLET_CONTENT = """
""" + ADMIN_NAV + """
<h1>Wallet Information</h1>

<div class="card">
    <h2>Platform Wallet</h2>
    <div class="price-row">
        <span>Address:</span>
        <span style="font-family: monospace;">{{ wallet_address }}</span>
    </div>
    <div class="price-row">
        <span>Network:</span>
        <span><strong>{{ network }}</strong></span>
    </div>
    <div class="price-row">
        <span>Current XRP Price:</span>
        <span><strong>${{ "%.4f"|format(xrp_price) }}</strong></span>
    </div>
    <hr>
    <div class="price-row">
        <span>Total XRP Received (verified):</span>
        <span><strong>{{ "%.4f"|format(total_received) }} XRP</strong></span>
    </div>
    <div class="price-row">
        <span>Current USD Value:</span>
        <span><strong>${{ "%.2f"|format(total_received * xrp_price) }}</strong></span>
    </div>
</div>

<div class="card">
    <h2>Quick Links</h2>
    <p>
        <a href="https://{{ 'testnet.' if network == 'TESTNET' else '' }}xrpscan.com/account/{{ wallet_address }}" target="_blank" class="btn">
            View on XRPScan
        </a>
        <a href="https://{{ 'testnet.' if network == 'TESTNET' else '' }}bithomp.com/explorer/{{ wallet_address }}" target="_blank" class="btn btn-secondary">
            View on Bithomp
        </a>
    </p>
</div>

<div class="card">
    <h2>Security Reminder</h2>
    <p style="color: #666;">
        Your wallet seed is stored in your <code>.env</code> file. For production:
    </p>
    <ul style="color: #666;">
        <li>Never share your seed phrase</li>
        <li>Consider using a hardware wallet for large balances</li>
        <li>Set up automatic sweeps to cold storage</li>
        <li>Enable 2FA on any exchange accounts</li>
    </ul>
</div>
"""


@app.route("/admin")
@admin_required
def admin_dashboard():
    """Admin dashboard with overview stats."""
    from sqlalchemy import func
    from datetime import date

    get_xrp_price()
    today = date.today()

    # Calculate stats
    total_xrp = db.session.query(func.sum(Payment.received_xrp)).filter_by(status='verified').scalar() or 0
    verified_count = Payment.query.filter_by(status='verified').count()
    pending_count = Payment.query.filter_by(status='pending').count()
    total_users = User.query.count()
    active_deals = Deal.query.filter_by(is_active=True).count()

    # Today's stats
    today_payments = Payment.query.filter(
        func.date(Payment.created_at) == today
    ).count()
    today_xrp = db.session.query(func.sum(Payment.received_xrp)).filter(
        Payment.status == 'verified',
        func.date(Payment.verified_at) == today
    ).scalar() or 0
    today_users = User.query.filter(
        func.date(User.created_at) == today
    ).count()

    # Recent payments
    recent_payments = Payment.query.order_by(Payment.created_at.desc()).limit(10).all()

    # P2P stats
    p2p_active_helpers = HelperProfile.query.filter_by(is_active=True, is_approved=True).count()
    p2p_pending_helpers = HelperProfile.query.filter_by(is_approved=False).filter(HelperProfile.country_code.isnot(None)).count()
    p2p_total_transactions = P2PTransaction.query.count()
    p2p_total_rlusd = db.session.query(func.sum(P2PTransaction.escrow_amount_rlusd)).filter(
        P2PTransaction.status == 'completed'
    ).scalar() or 0

    return render_template_string(
        BASE_TEMPLATE,
        title="Admin Dashboard",
        content=render_template_string(
            ADMIN_DASHBOARD_CONTENT,
            user=current_user,
            total_xrp_received=total_xrp,
            total_usd_value=total_xrp * XRPL_CONFIG["xrp_usd_rate"],
            verified_payments=verified_count,
            pending_payments=pending_count,
            total_users=total_users,
            active_deals=active_deals,
            xrp_price=XRPL_CONFIG["xrp_usd_rate"],
            network=XRPL_CONFIG["network"].upper(),
            recent_payments=recent_payments,
            today_payments=today_payments,
            today_xrp=today_xrp,
            today_users=today_users,
            p2p_active_helpers=p2p_active_helpers,
            p2p_pending_helpers=p2p_pending_helpers,
            p2p_total_transactions=p2p_total_transactions,
            p2p_total_rlusd=p2p_total_rlusd
        ),
        current_user=current_user
    )


@app.route("/admin/payments")
@admin_required
def admin_payments():
    """View all payments with filtering."""
    from sqlalchemy import func

    get_xrp_price()
    filter_status = request.args.get('status', '')

    query = Payment.query.order_by(Payment.created_at.desc())
    if filter_status:
        query = query.filter_by(status=filter_status)

    payments = query.all()

    # Stats
    total_verified = db.session.query(func.sum(Payment.received_xrp)).filter_by(status='verified').scalar() or 0
    total_pending = db.session.query(func.sum(Payment.expected_xrp)).filter_by(status='pending').scalar() or 0
    total_expired = db.session.query(func.sum(Payment.expected_xrp)).filter_by(status='expired').scalar() or 0

    return render_template_string(
        BASE_TEMPLATE,
        title="Payment Monitor",
        content=render_template_string(
            ADMIN_PAYMENTS_CONTENT,
            payments=payments,
            filter_status=filter_status,
            total_verified_xrp=total_verified,
            total_pending_xrp=total_pending,
            total_expired_xrp=total_expired,
            xrp_price=XRPL_CONFIG["xrp_usd_rate"],
            network=XRPL_CONFIG["network"].upper()
        ),
        current_user=current_user
    )


@app.route("/admin/payments/export")
@admin_required
def admin_payments_export():
    """Export payments as CSV."""
    import csv
    from io import StringIO

    filter_status = request.args.get('status', '')

    query = Payment.query.order_by(Payment.created_at.desc())
    if filter_status:
        query = query.filter_by(status=filter_status)

    payments = query.all()

    # Create CSV
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Date', 'User Email', 'Deal ID', 'Expected XRP', 'Received XRP', 'USD Rate', 'TX Hash', 'Sender', 'Status', 'Verified At'])

    for p in payments:
        writer.writerow([
            p.id,
            p.created_at.isoformat() if p.created_at else '',
            p.user.email if p.user else '',
            p.deal.deal_id if p.deal else '',
            p.expected_xrp or 0,
            p.received_xrp or 0,
            p.xrp_usd_rate or 0,
            p.tx_hash or '',
            p.sender_address or '',
            p.status,
            p.verified_at.isoformat() if p.verified_at else ''
        ])

    response = Response(output.getvalue(), mimetype='text/csv')
    response.headers['Content-Disposition'] = f'attachment; filename=payments_{filter_status or "all"}_{datetime.now().strftime("%Y%m%d")}.csv'
    return response


@app.route("/admin/users")
@admin_required
def admin_users():
    """View all users."""
    users = User.query.order_by(User.created_at.desc()).all()

    return render_template_string(
        BASE_TEMPLATE,
        title="User Management",
        content=render_template_string(
            ADMIN_USERS_CONTENT,
            users=users,
            db=db,
            Payment=Payment
        ),
        current_user=current_user
    )


@app.route("/admin/deals")
@admin_required
def admin_deals():
    """View all deals."""
    from flask_wtf.csrf import generate_csrf
    csrf_tok = generate_csrf()

    active_deals = Deal.query.filter_by(is_active=True).order_by(Deal.created_at.desc()).all()
    inactive_deals = Deal.query.filter_by(is_active=False).order_by(Deal.created_at.desc()).limit(20).all()

    content = ADMIN_NAV + f"""
    <h1>Deal Management</h1>

    <div class="card" style="margin-bottom: 20px;">
        <h2>Deal Scanner</h2>
        <p style="color: #fff;">Trigger a background scan to search popular routes and populate deals.</p>
        <form method="POST" action="/admin/deals/scan" style="display: inline;">
            <input type="hidden" name="csrf_token" value="{csrf_tok}">
            <button type="submit" class="btn" style="margin-right: 10px;">Run Quick Scan (3 routes)</button>
        </form>
        <form method="POST" action="/admin/deals/scan?full=1" style="display: inline;">
            <input type="hidden" name="csrf_token" value="{csrf_tok}">
            <button type="submit" class="btn btn-secondary">Run Full Scan (all routes)</button>
        </form>
    </div>

    <div class="card">
        <h2>Active Deals ({len(active_deals)})</h2>
        {''.join(['<div style="border-bottom: 1px solid #eee; padding: 10px 0;"><strong>' + str(d.airline) + ' ' + str(d.flight_number) + '</strong> | ' + str(d.origin) + ' &rarr; ' + str(d.destination) + ' | ' + str(d.departure_date) + '<br><span style="color: #666;">Savings: $' + format(d.user_savings_usd or 0, '.2f') + ' (' + format(d.savings_percent or 0, '.0f') + '%) | Fee: $' + format(d.platform_fee_usd or 0, '.2f') + '</span></div>' for d in active_deals]) if active_deals else '<p style="color: #666;">No active deals. Run a scan to populate.</p>'}
    </div>

    <div class="card">
        <h2>Recent Inactive Deals</h2>
        {''.join(['<div style="border-bottom: 1px solid #eee; padding: 10px 0;"><strong>' + str(d.airline) + ' ' + str(d.flight_number) + '</strong> | ' + str(d.origin) + ' &rarr; ' + str(d.destination) + '<br><span style="color: #fff;">Expired</span></div>' for d in inactive_deals]) if inactive_deals else '<p style="color: #666;">No inactive deals.</p>'}
    </div>
    """

    return render_template_string(
        BASE_TEMPLATE,
        title="Deal Management",
        content=content,
        current_user=current_user
    )


@app.route("/admin/deals/scan", methods=["POST"])
@admin_required
def admin_deal_scan():
    """Trigger a deal generation scan."""
    is_full = request.args.get("full") == "1"
    try:
        from deal_generator import run_deal_scan
        stats = run_deal_scan(max_routes=None if is_full else 3)
        flash(
            f"Scan complete: {stats['searches_succeeded']} searches, "
            f"{stats['deals_new']} new deals, {stats['deals_updated']} updated",
            "success"
        )
    except Exception as e:
        logger.exception("Deal scan failed")
        flash(f"Scan failed: {e}", "error")
    return redirect("/admin/deals")


@app.route("/admin/wallet")
@admin_required
def admin_wallet():
    """View wallet information."""
    from sqlalchemy import func

    get_xrp_price()
    total_received = db.session.query(func.sum(Payment.received_xrp)).filter_by(status='verified').scalar() or 0

    return render_template_string(
        BASE_TEMPLATE,
        title="Wallet Info",
        content=render_template_string(
            ADMIN_WALLET_CONTENT,
            wallet_address=XRPL_CONFIG["platform_wallet_address"],
            network=XRPL_CONFIG["network"].upper(),
            xrp_price=XRPL_CONFIG["xrp_usd_rate"],
            total_received=total_received
        ),
        current_user=current_user
    )


@app.route("/admin/proxies")
@admin_required
def admin_proxies():
    """View and manage proxy configuration."""
    manager = ProxyManager()
    status = manager.get_status()

    content = ADMIN_NAV + f"""
    <h1>Proxy Configuration</h1>

    <div class="stats-grid">
        <div class="stat-card">
            <div class="stat-value">{'✓' if status['configured'] else '✗'}</div>
            <div class="stat-label">Configured</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{status['provider'] or 'None'}</div>
            <div class="stat-label">Provider</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{status['proxy_type']}</div>
            <div class="stat-label">Proxy Type</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{len(status['supported_markets'])}</div>
            <div class="stat-label">Markets</div>
        </div>
    </div>

    <h2>Configuration Status</h2>
    <table>
        <tr><th>Setting</th><th>Value</th></tr>
        <tr><td>API Key</td><td>{'Set' if status['has_api_key'] else 'Not set'}</td></tr>
        <tr><td>Credentials</td><td>{'Set' if status['has_credentials'] else 'Not set'}</td></tr>
        <tr><td>Host</td><td>{status['host'] or 'Not configured'}</td></tr>
    </table>

    {'<div class="alert alert-warning">⚠️ Proxies not configured. Set WEBSHARE_USERNAME and WEBSHARE_PASSWORD in .env</div>' if not status['configured'] else ''}

    <h2>Test Proxy Connections</h2>
    <p>Test proxy connections to verify they're working correctly.</p>

    <form action="/admin/proxies/test" method="post" style="margin: 20px 0;">
        <label>Markets to test:</label><br>
        <select name="markets" multiple style="width: 200px; height: 150px; margin: 10px 0;">
            {''.join(f'<option value="{m}" {"selected" if m in ["US", "JP", "UK", "DE"] else ""}>{m}</option>' for m in list(MARKET_TO_COUNTRY_CODE.keys())[:20])}
        </select><br>
        <button type="submit" class="btn">Test Selected Proxies</button>
    </form>
    """

    return render_template_string(
        BASE_TEMPLATE,
        title="Proxy Config",
        content=content,
        current_user=current_user
    )


@app.route("/admin/proxies/test", methods=["POST"])
@admin_required
def admin_proxies_test():
    """Test proxy connections."""
    markets = request.form.getlist("markets")
    if not markets:
        markets = ["US", "JP", "UK", "DE"]

    manager = ProxyManager()
    results = []

    for market in markets[:10]:  # Limit to 10 at a time
        result = manager.test_proxy(market)
        results.append(result)

    # Build results table
    rows = ""
    success_count = 0
    for r in results:
        if r["success"]:
            success_count += 1
            rows += f"""
            <tr style="background: #d4edda;">
                <td>{r['market']}</td>
                <td>✓ Connected</td>
                <td>{r.get('detected_country', 'Unknown')}</td>
                <td>{r.get('detected_city', '')}</td>
                <td><code>{r.get('ip', '')}</code></td>
            </tr>
            """
        else:
            rows += f"""
            <tr style="background: #f8d7da;">
                <td>{r['market']}</td>
                <td>✗ Failed</td>
                <td colspan="3">{r.get('error', 'Unknown error')}</td>
            </tr>
            """

    content = f"""
    <h1>Proxy Test Results</h1>
    <p><a href="/admin/proxies">← Back to Proxy Config</a></p>

    <div class="alert {'alert-success' if success_count == len(results) else 'alert-warning'}">
        {success_count}/{len(results)} proxies connected successfully
    </div>

    <table>
        <tr>
            <th>Market</th>
            <th>Status</th>
            <th>Country</th>
            <th>City</th>
            <th>IP</th>
        </tr>
        {rows}
    </table>

    <p style="margin-top: 20px;">
        <a href="/admin/proxies" class="btn">Back to Config</a>
    </p>
    """

    return render_template_string(
        BASE_TEMPLATE,
        title="Proxy Test",
        content=content,
        current_user=current_user
    )


@app.route("/api/proxies/status")
@login_required
def api_proxy_status():
    """API endpoint for proxy status."""
    manager = ProxyManager()
    return jsonify(manager.get_status())


# --- P2P ADMIN PAGES ---

ADMIN_P2P_CONTENT = """
""" + ADMIN_NAV + """
<h1 style="color: #ff6b35;">P2P Network Management</h1>

<div class="stats">
    <div class="stat-card">
        <div class="stat-value">{{ active_helpers }}</div>
        <div class="stat-label">Active Helpers</div>
    </div>
    <div class="stat-card">
        <div class="stat-value">{{ total_helpers }}</div>
        <div class="stat-label">Total Helpers</div>
    </div>
    <div class="stat-card">
        <div class="stat-value">{{ total_transactions }}</div>
        <div class="stat-label">Total Transactions</div>
    </div>
    <div class="stat-card">
        <div class="stat-value">{{ completed_transactions }}</div>
        <div class="stat-label">Completed</div>
    </div>
</div>

<div class="stats">
    <div class="stat-card">
        <div class="stat-value">{{ "%.2f"|format(total_rlusd_volume) }}</div>
        <div class="stat-label">RLUSD Volume</div>
    </div>
    <div class="stat-card">
        <div class="stat-value">{{ "%.2f"|format(total_platform_fees) }}</div>
        <div class="stat-label">Platform Fees (RLUSD)</div>
    </div>
    <div class="stat-card">
        <div class="stat-value">{{ "%.2f"|format(total_helper_earnings) }}</div>
        <div class="stat-label">Helper Earnings (RLUSD)</div>
    </div>
    <div class="stat-card">
        <div class="stat-value">${{ "%.2f"|format(total_savings) }}</div>
        <div class="stat-label">Total User Savings</div>
    </div>
</div>

<div class="card" style="margin-top: 20px;">
    <h2>Recent P2P Transactions</h2>
    {% if transactions %}
        <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
            <tr style="text-align: left; border-bottom: 2px solid #eee;">
                <th style="padding: 10px;">ID</th>
                <th>Date</th>
                <th>Route</th>
                <th>Market</th>
                <th>Savings</th>
                <th>Escrow</th>
                <th>Helper</th>
                <th>Status</th>
            </tr>
            {% for t in transactions %}
            <tr style="border-bottom: 1px solid #eee;">
                <td style="padding: 10px; font-family: monospace; font-size: 12px;">{{ t.transaction_id[:8] }}...</td>
                <td>{{ t.created_at.strftime('%m/%d %H:%M') if t.created_at else 'N/A' }}</td>
                <td>{{ t.origin }} → {{ t.destination }}</td>
                <td><span class="market-tag">{{ t.target_market }}</span></td>
                <td style="color: #28a745;">${{ "%.2f"|format(t.savings_usd or 0) }}</td>
                <td>{{ "%.2f"|format(t.escrow_amount_rlusd or 0) }} RLUSD</td>
                <td>{{ t.helper.user.email[:15] if t.helper and t.helper.user else 'Unmatched' }}...</td>
                <td>
                    <span style="padding: 2px 8px; border-radius: 12px; font-size: 12px; font-weight: 600;
                        {% if t.status == 'completed' %}background: #d4edda; color: #155724;
                        {% elif t.status == 'failed' %}background: #f8d7da; color: #842029;
                        {% elif t.status == 'cancelled' %}background: #e2e3e5; color: #41464b;
                        {% else %}background: #fff3cd; color: #664d03;{% endif %}">
                        {{ t.status }}
                    </span>
                </td>
            </tr>
            {% endfor %}
        </table>
    {% else %}
        <p style="color: #666;">No P2P transactions yet.</p>
    {% endif %}
</div>

<div class="card" style="margin-top: 20px;">
    <h2>Active Escrows</h2>
    {% if escrows %}
        <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
            <tr style="text-align: left; border-bottom: 2px solid #eee;">
                <th style="padding: 10px;">Escrow ID</th>
                <th>Amount</th>
                <th>Helper Cut</th>
                <th>Platform Fee</th>
                <th>On-Chain</th>
                <th>Status</th>
            </tr>
            {% for e in escrows %}
            <tr style="border-bottom: 1px solid #eee;">
                <td style="padding: 10px; font-family: monospace; font-size: 12px;">{{ e.escrow_id[:10] }}...</td>
                <td>{{ "%.2f"|format(e.total_rlusd or 0) }} RLUSD</td>
                <td>{{ "%.2f"|format(e.helper_amount_rlusd or 0) }}</td>
                <td>{{ "%.2f"|format(e.platform_amount_rlusd or 0) }}</td>
                <td>{{ 'Verified' if e.on_chain_verified else 'Pending' }}</td>
                <td>
                    <span style="padding: 2px 8px; border-radius: 12px; font-size: 12px; font-weight: 600;
                        {% if e.status == 'released' %}background: #d4edda; color: #155724;
                        {% elif e.status == 'locked' %}background: #cce5ff; color: #004085;
                        {% elif e.status == 'cancelled' %}background: #f8d7da; color: #842029;
                        {% else %}background: #fff3cd; color: #664d03;{% endif %}">
                        {{ e.status }}
                    </span>
                </td>
            </tr>
            {% endfor %}
        </table>
    {% else %}
        <p style="color: #666;">No escrows yet.</p>
    {% endif %}
</div>

<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-top: 20px;">
    <div class="card">
        <h3>Top Markets</h3>
        {% for market, count in top_markets %}
            <div class="price-row">
                <span><span class="market-tag">{{ market }}</span></span>
                <span><strong>{{ count }}</strong> transactions</span>
            </div>
        {% endfor %}
        {% if not top_markets %}<p style="color: #666;">No data yet.</p>{% endif %}
    </div>
    <div class="card">
        <h3>Top Helpers</h3>
        {% for helper in top_helpers %}
            <div class="price-row">
                <span>{{ helper.user.email[:20] if helper.user else 'Unknown' }} ({{ helper.country_code }})</span>
                <span><strong>{{ helper.successful_transactions }}</strong> completed | {{ "%.1f"|format(helper.average_rating) }} rating</span>
            </div>
        {% endfor %}
        {% if not top_helpers %}<p style="color: #666;">No helpers yet.</p>{% endif %}
    </div>
</div>
"""

ADMIN_HELPERS_CONTENT = """
""" + ADMIN_NAV + """
<h1>Helper Approvals</h1>

<div class="card">
    <h2>Pending Approval ({{ pending|length }})</h2>
    {% if pending %}
        <table style="width: 100%; border-collapse: collapse;">
            <tr style="text-align: left; border-bottom: 2px solid #eee;">
                <th style="padding: 10px;">User</th>
                <th>Country</th>
                <th>City</th>
                <th>Applied</th>
                <th>Actions</th>
            </tr>
            {% for h in pending %}
            <tr style="border-bottom: 1px solid #eee;">
                <td style="padding: 10px;">{{ h.user.email if h.user else 'Unknown' }}</td>
                <td><span class="market-tag">{{ h.country_code }}</span></td>
                <td>{{ h.city or '-' }}</td>
                <td>{{ h.created_at.strftime('%Y-%m-%d') if h.created_at else 'N/A' }}</td>
                <td>
                    <form method="POST" action="/admin/helpers/approve/{{ h.id }}" style="display: inline;">
                        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                        <button type="submit" class="btn" style="padding: 4px 12px; font-size: 12px; background: #28a745; border-color: #28a745;">Approve</button>
                    </form>
                    <form method="POST" action="/admin/helpers/reject/{{ h.id }}" style="display: inline;">
                        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                        <button type="submit" class="btn btn-secondary" style="padding: 4px 12px; font-size: 12px;">Reject</button>
                    </form>
                </td>
            </tr>
            {% endfor %}
        </table>
    {% else %}
        <p style="color: #666;">No pending helper applications.</p>
    {% endif %}
</div>

<div class="card" style="margin-top: 20px;">
    <h2>Approved Helpers ({{ approved|length }})</h2>
    {% if approved %}
        <table style="width: 100%; border-collapse: collapse;">
            <tr style="text-align: left; border-bottom: 2px solid #eee;">
                <th style="padding: 10px;">User</th>
                <th>Country</th>
                <th>Status</th>
                <th>Transactions</th>
                <th>Earned (RLUSD)</th>
                <th>Rating</th>
                <th>Actions</th>
            </tr>
            {% for h in approved %}
            <tr style="border-bottom: 1px solid #eee;">
                <td style="padding: 10px;">{{ h.user.email if h.user else 'Unknown' }}</td>
                <td><span class="market-tag">{{ h.country_code }}</span></td>
                <td>
                    {% if h.is_active %}
                        <span style="color: #28a745; font-weight: 600;">Active</span>
                    {% else %}
                        <span style="color: #fff;">Paused</span>
                    {% endif %}
                </td>
                <td>{{ h.successful_transactions }}/{{ h.total_transactions }}</td>
                <td>{{ "%.2f"|format(h.total_earned_rlusd) }}</td>
                <td>{{ "%.1f"|format(h.average_rating) }}/5</td>
                <td>
                    <form method="POST" action="/admin/helpers/suspend/{{ h.id }}" style="display: inline;">
                        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                        <button type="submit" class="btn btn-secondary" style="padding: 4px 12px; font-size: 12px;">
                            {{ 'Unsuspend' if not h.is_approved else 'Suspend' }}
                        </button>
                    </form>
                </td>
            </tr>
            {% endfor %}
        </table>
    {% else %}
        <p style="color: #666;">No approved helpers yet.</p>
    {% endif %}
</div>
"""


@app.route("/admin/p2p")
@admin_required
def admin_p2p():
    """P2P network management dashboard."""
    from sqlalchemy import func

    active_helpers = HelperProfile.query.filter_by(is_active=True, is_approved=True).count()
    total_helpers = HelperProfile.query.count()
    total_transactions = P2PTransaction.query.count()
    completed_transactions = P2PTransaction.query.filter_by(status='completed').count()

    total_rlusd_volume = db.session.query(func.sum(P2PTransaction.escrow_amount_rlusd)).filter(
        P2PTransaction.status == 'completed'
    ).scalar() or 0
    total_platform_fees = db.session.query(func.sum(P2PTransaction.platform_fee_rlusd)).filter(
        P2PTransaction.status == 'completed'
    ).scalar() or 0
    total_helper_earnings = db.session.query(func.sum(P2PTransaction.helper_earning_rlusd)).filter(
        P2PTransaction.status == 'completed'
    ).scalar() or 0
    total_savings = db.session.query(func.sum(P2PTransaction.savings_usd)).filter(
        P2PTransaction.status == 'completed'
    ).scalar() or 0

    transactions = P2PTransaction.query.order_by(P2PTransaction.created_at.desc()).limit(50).all()
    escrows = P2PEscrow.query.filter(P2PEscrow.status.in_(['pending', 'locked'])).order_by(P2PEscrow.created_at.desc()).all()

    # Top markets
    top_markets_query = db.session.query(
        P2PTransaction.target_market,
        func.count(P2PTransaction.id)
    ).group_by(P2PTransaction.target_market).order_by(func.count(P2PTransaction.id).desc()).limit(10).all()

    top_helpers = HelperProfile.query.filter_by(is_approved=True).order_by(
        HelperProfile.successful_transactions.desc()
    ).limit(5).all()

    return render_template_string(
        BASE_TEMPLATE,
        title="P2P Network",
        content=render_template_string(
            ADMIN_P2P_CONTENT,
            active_helpers=active_helpers,
            total_helpers=total_helpers,
            total_transactions=total_transactions,
            completed_transactions=completed_transactions,
            total_rlusd_volume=total_rlusd_volume,
            total_platform_fees=total_platform_fees,
            total_helper_earnings=total_helper_earnings,
            total_savings=total_savings,
            transactions=transactions,
            escrows=escrows,
            top_markets=top_markets_query,
            top_helpers=top_helpers
        ),
        current_user=current_user
    )


@app.route("/admin/helpers")
@admin_required
def admin_helpers():
    """Helper approval management."""
    pending = HelperProfile.query.filter_by(is_approved=False).filter(
        HelperProfile.country_code.isnot(None)
    ).order_by(HelperProfile.created_at.desc()).all()

    approved = HelperProfile.query.filter_by(is_approved=True).order_by(
        HelperProfile.successful_transactions.desc()
    ).all()

    return render_template_string(
        BASE_TEMPLATE,
        title="Helper Approvals",
        content=render_template_string(
            ADMIN_HELPERS_CONTENT,
            pending=pending,
            approved=approved
        ),
        current_user=current_user
    )


@app.route("/admin/helpers/approve/<int:helper_id>", methods=["POST"])
@admin_required
def admin_approve_helper(helper_id):
    """Approve a helper application."""
    helper = HelperProfile.query.get_or_404(helper_id)
    helper.is_approved = True
    helper.is_active = True
    db.session.commit()
    flash(f"Helper {helper.user.email if helper.user else helper_id} approved.", "success")
    return redirect("/admin/helpers")


@app.route("/admin/helpers/reject/<int:helper_id>", methods=["POST"])
@admin_required
def admin_reject_helper(helper_id):
    """Reject a helper application."""
    helper = HelperProfile.query.get_or_404(helper_id)
    db.session.delete(helper)
    db.session.commit()
    flash("Helper application rejected.", "info")
    return redirect("/admin/helpers")


@app.route("/admin/helpers/suspend/<int:helper_id>", methods=["POST"])
@admin_required
def admin_suspend_helper(helper_id):
    """Suspend or unsuspend a helper."""
    helper = HelperProfile.query.get_or_404(helper_id)
    helper.is_approved = not helper.is_approved
    if not helper.is_approved:
        helper.is_active = False
    db.session.commit()
    action = "unsuspended" if helper.is_approved else "suspended"
    flash(f"Helper {action}.", "info")
    return redirect("/admin/helpers")


# --- Celery Task Admin Dashboard ---

@app.route("/admin/tasks")
@admin_required
def admin_tasks():
    """Celery task dashboard — schedule, recent results, manual triggers."""
    from celery_app import celery

    # Build schedule info
    schedule = []
    for name, entry in celery.conf.beat_schedule.items():
        sched = entry.get("schedule")
        if hasattr(sched, "run_every"):
            interval = f"every {int(sched.run_every.total_seconds())}s"
        elif hasattr(sched, "second"):
            interval = f"every {int(sched.total_seconds())}s"
        elif isinstance(sched, (int, float)):
            interval = f"every {int(sched)}s"
        else:
            interval = str(sched)

        task_name = entry["task"].replace("celery_app.", "")
        queue = celery.conf.task_routes.get(entry["task"], {}).get("queue", "phoenix")
        schedule.append({
            "name": name,
            "task": task_name,
            "schedule": interval,
            "queue": queue,
        })

    # Inspect active workers
    inspector = celery.control.inspect(timeout=2.0)
    active = {}
    reserved = {}
    stats = {}
    try:
        active = inspector.active() or {}
        reserved = inspector.reserved() or {}
        stats = inspector.stats() or {}
    except Exception:
        pass

    workers = []
    for worker_name, worker_stats in stats.items():
        workers.append({
            "name": worker_name,
            "active_tasks": len(active.get(worker_name, [])),
            "reserved_tasks": len(reserved.get(worker_name, [])),
            "total_tasks": worker_stats.get("total", {}).get("celery_app", 0),
            "pool": worker_stats.get("pool", {}).get("implementation", "unknown"),
            "concurrency": worker_stats.get("pool", {}).get("max-concurrency", 0),
        })

    return jsonify({
        "schedule": sorted(schedule, key=lambda s: s["name"]),
        "workers": workers,
        "active_tasks": {k: len(v) for k, v in active.items()},
        "reserved_tasks": {k: len(v) for k, v in reserved.items()},
    })


@app.route("/admin/tasks/trigger/<task_name>", methods=["POST"])
@admin_required
def admin_trigger_task(task_name):
    """Manually trigger a Celery task by name."""
    from celery_app import celery

    # Only allow triggering known tasks
    allowed_tasks = {name.replace("celery_app.", "") for name in celery.conf.task_routes}
    if task_name not in allowed_tasks:
        return jsonify({"error": f"Unknown task: {task_name}"}), 404

    full_name = f"celery_app.{task_name}"
    result = celery.send_task(full_name)
    logger.info(f"Admin {current_user.email} triggered task {task_name} (id={result.id})")

    return jsonify({
        "triggered": task_name,
        "task_id": result.id,
        "status": "queued",
    })


@app.route("/admin/tasks/result/<task_id>")
@admin_required
def admin_task_result(task_id):
    """Check the result of a triggered task."""
    from celery_app import celery
    result = celery.AsyncResult(task_id)
    response = {
        "task_id": task_id,
        "status": result.status,
        "ready": result.ready(),
    }
    if result.ready():
        try:
            response["result"] = result.result
        except Exception as e:
            response["error"] = str(e)
    return jsonify(response)


# --- Admin Node Fleet Dashboard (Build #69) ---

ADMIN_NODE_FLEET_CONTENT = ADMIN_NAV + """
<h1 style="color: #ff6b35;">Node Fleet Dashboard</h1>
<p style="color: #fff;">Real-time monitoring of the Phoenix node network and browsing data pipeline.</p>

<!-- Fleet Summary -->
<div class="stats-grid" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:24px;">
    <div class="stat-card" style="background:rgba(35,41,47,0.6);border-radius:10px;padding:16px;text-align:center;border:1px solid rgba(255,255,255,0.05);">
        <div class="stat-value" style="font-size:28px;font-weight:700;color:#0f9d58;">{{ fleet.active_nodes }}</div>
        <div class="stat-label" style="font-size:11px;color:#999;margin-top:4px;">Active Nodes</div>
    </div>
    <div class="stat-card" style="background:rgba(35,41,47,0.6);border-radius:10px;padding:16px;text-align:center;border:1px solid rgba(255,255,255,0.05);">
        <div class="stat-value" style="font-size:28px;font-weight:700;color:#ddd;">{{ fleet.total_helpers }}</div>
        <div class="stat-label" style="font-size:11px;color:#999;margin-top:4px;">Total Helpers</div>
    </div>
    <div class="stat-card" style="background:rgba(35,41,47,0.6);border-radius:10px;padding:16px;text-align:center;border:1px solid rgba(255,255,255,0.05);">
        <div class="stat-value" style="font-size:28px;font-weight:700;color:#ff6b35;">{{ fleet.with_tokens }}</div>
        <div class="stat-label" style="font-size:11px;color:#999;margin-top:4px;">With Tokens</div>
    </div>
    <div class="stat-card" style="background:rgba(35,41,47,0.6);border-radius:10px;padding:16px;text-align:center;border:1px solid rgba(255,255,255,0.05);">
        <div class="stat-value" style="font-size:28px;font-weight:700;color:#ddd;">{{ fleet.with_extension }}</div>
        <div class="stat-label" style="font-size:11px;color:#999;margin-top:4px;">Extension Connected</div>
    </div>
</div>

<!-- Data Pipeline Stats -->
<div style="background:rgba(35,41,47,0.6);border-radius:12px;padding:20px;margin-bottom:20px;border:1px solid rgba(255,255,255,0.05);">
    <div style="font-size:15px;font-weight:600;color:#ff6b35;margin-bottom:15px;">Data Pipeline (7 days)</div>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;">
        <div style="text-align:center;">
            <div style="font-size:22px;font-weight:700;color:#ddd;">{{ pipeline.total_events }}</div>
            <div style="font-size:11px;color:#999;">Total Events</div>
        </div>
        <div style="text-align:center;">
            <div style="font-size:22px;font-weight:700;color:#0f9d58;">${{ '%.4f' | format(pipeline.total_value) }}</div>
            <div style="font-size:11px;color:#999;">Total Value</div>
        </div>
        <div style="text-align:center;">
            <div style="font-size:22px;font-weight:700;color:#ddd;">{{ pipeline.avg_quality }}</div>
            <div style="font-size:11px;color:#999;">Avg Quality</div>
        </div>
        <div style="text-align:center;">
            <div style="font-size:22px;font-weight:700;color:#ddd;">{{ pipeline.unique_domains }}</div>
            <div style="font-size:11px;color:#999;">Unique Domains</div>
        </div>
        <div style="text-align:center;">
            <div style="font-size:22px;font-weight:700;color:#ddd;">{{ pipeline.events_per_day }}</div>
            <div style="font-size:11px;color:#999;">Events/Day</div>
        </div>
    </div>
</div>

<!-- Event Type Distribution -->
<div style="background:rgba(35,41,47,0.6);border-radius:12px;padding:20px;margin-bottom:20px;border:1px solid rgba(255,255,255,0.05);">
    <div style="font-size:15px;font-weight:600;color:#ff6b35;margin-bottom:15px;">Event Type Distribution</div>
    <table style="width:100%;border-collapse:collapse;">
        <thead>
            <tr style="border-bottom:1px solid rgba(255,255,255,0.1);">
                <th style="text-align:left;padding:8px 0;color:#999;font-size:12px;">Event Type</th>
                <th style="text-align:right;padding:8px 0;color:#999;font-size:12px;">Count</th>
                <th style="text-align:right;padding:8px 0;color:#999;font-size:12px;">Value (USD)</th>
                <th style="text-align:right;padding:8px 0;color:#999;font-size:12px;">Avg Quality</th>
                <th style="text-align:right;padding:8px 0;color:#999;font-size:12px;">% of Total</th>
            </tr>
        </thead>
        <tbody>
            {% for et in event_types %}
            <tr style="border-bottom:1px solid rgba(255,255,255,0.05);">
                <td style="padding:10px 0;color:#ddd;">{{ et.type | replace('_', ' ') | title }}</td>
                <td style="padding:10px 0;color:#ddd;text-align:right;">{{ et.count }}</td>
                <td style="padding:10px 0;color:#ff6b35;text-align:right;">${{ '%.4f' | format(et.value) }}</td>
                <td style="padding:10px 0;color:#ddd;text-align:right;">{{ et.quality }}/100</td>
                <td style="padding:10px 0;color:#ddd;text-align:right;">{{ et.pct }}%</td>
            </tr>
            {% endfor %}
            {% if not event_types %}
            <tr><td colspan="5" style="padding:20px;color:#888;font-style:italic;text-align:center;">No events in the last 7 days</td></tr>
            {% endif %}
        </tbody>
    </table>
</div>

<!-- Top Nodes -->
<div style="background:rgba(35,41,47,0.6);border-radius:12px;padding:20px;margin-bottom:20px;border:1px solid rgba(255,255,255,0.05);">
    <div style="font-size:15px;font-weight:600;color:#ff6b35;margin-bottom:15px;">Top Contributing Nodes (7 days)</div>
    <table style="width:100%;border-collapse:collapse;">
        <thead>
            <tr style="border-bottom:1px solid rgba(255,255,255,0.1);">
                <th style="text-align:left;padding:8px 0;color:#999;font-size:12px;">User</th>
                <th style="text-align:left;padding:8px 0;color:#999;font-size:12px;">Country</th>
                <th style="text-align:right;padding:8px 0;color:#999;font-size:12px;">Events</th>
                <th style="text-align:right;padding:8px 0;color:#999;font-size:12px;">Value (USD)</th>
                <th style="text-align:right;padding:8px 0;color:#999;font-size:12px;">Last Seen</th>
            </tr>
        </thead>
        <tbody>
            {% for node in top_nodes %}
            <tr style="border-bottom:1px solid rgba(255,255,255,0.05);">
                <td style="padding:10px 0;color:#ddd;">{{ node.email }}</td>
                <td style="padding:10px 0;color:#ddd;">{{ node.country }}</td>
                <td style="padding:10px 0;color:#ddd;text-align:right;">{{ node.events }}</td>
                <td style="padding:10px 0;color:#ff6b35;text-align:right;">${{ '%.4f' | format(node.value) }}</td>
                <td style="padding:10px 0;color:#999;text-align:right;">{{ node.last_seen }}</td>
            </tr>
            {% endfor %}
            {% if not top_nodes %}
            <tr><td colspan="5" style="padding:20px;color:#888;font-style:italic;text-align:center;">No node activity yet</td></tr>
            {% endif %}
        </tbody>
    </table>
</div>

<!-- Processor Stats -->
<div style="background:rgba(35,41,47,0.6);border-radius:12px;padding:20px;border:1px solid rgba(255,255,255,0.05);">
    <div style="font-size:15px;font-weight:600;color:#ff6b35;margin-bottom:15px;">Processor Runtime</div>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;">
        <div>
            <div style="font-size:11px;color:#999;">Total Ingested</div>
            <div style="font-size:18px;font-weight:600;color:#ddd;">{{ proc.throughput.total_ingested }}</div>
        </div>
        <div>
            <div style="font-size:11px;color:#999;">Total Duplicates</div>
            <div style="font-size:18px;font-weight:600;color:#ddd;">{{ proc.throughput.total_duplicates }}</div>
        </div>
        <div>
            <div style="font-size:11px;color:#999;">Total Rejected</div>
            <div style="font-size:18px;font-weight:600;color:#ddd;">{{ proc.throughput.total_rejected }}</div>
        </div>
        <div>
            <div style="font-size:11px;color:#999;">Total Routed</div>
            <div style="font-size:18px;font-weight:600;color:#0f9d58;">{{ proc.throughput.total_routed }}</div>
        </div>
        <div>
            <div style="font-size:11px;color:#999;">Dedup Cache Usage</div>
            <div style="font-size:18px;font-weight:600;color:#ddd;">{{ proc.dedup_cache.utilisation_pct }}%</div>
        </div>
        <div>
            <div style="font-size:11px;color:#999;">Cache Hit Rate</div>
            <div style="font-size:18px;font-weight:600;color:#ddd;">{{ '%.1f' | format(proc.dedup_cache.hit_rate * 100) }}%</div>
        </div>
        <div>
            <div style="font-size:11px;color:#999;">Active Nodes (rate)</div>
            <div style="font-size:18px;font-weight:600;color:#ddd;">{{ proc.rate_limits.active_nodes }}</div>
        </div>
    </div>
</div>
"""


@app.route("/admin/nodes")
@admin_required
def admin_node_fleet():
    """Admin node fleet monitoring dashboard."""
    from sqlalchemy import func

    # Fleet summary
    total_helpers = HelperProfile.query.filter_by(is_active=True).count()
    with_tokens = HelperProfile.query.filter(
        HelperProfile.is_active == True,
        HelperProfile.helper_token.isnot(None),
    ).count()
    # "Active" = last_seen within 10 minutes
    ten_min_ago = datetime.utcnow() - timedelta(minutes=10)
    active_nodes = HelperProfile.query.filter(
        HelperProfile.is_active == True,
        HelperProfile.last_seen >= ten_min_ago,
    ).count()
    with_extension = HelperProfile.query.filter(
        HelperProfile.is_active == True,
        HelperProfile.node_id.isnot(None),
    ).count()

    fleet = {
        "total_helpers": total_helpers,
        "active_nodes": active_nodes,
        "with_tokens": with_tokens,
        "with_extension": with_extension,
    }

    # Pipeline stats (7 days)
    cutoff = datetime.utcnow() - timedelta(days=7)
    pipeline_total = BrowsingEvent.query.filter(BrowsingEvent.ingested_at >= cutoff).count()
    pipeline_value = db.session.query(
        func.sum(BrowsingEvent.commercial_value_usd)
    ).filter(BrowsingEvent.ingested_at >= cutoff).scalar() or 0
    pipeline_quality = db.session.query(
        func.avg(BrowsingEvent.quality_score)
    ).filter(BrowsingEvent.ingested_at >= cutoff).scalar() or 0
    unique_domains = db.session.query(
        func.count(func.distinct(BrowsingEvent.domain))
    ).filter(
        BrowsingEvent.ingested_at >= cutoff,
        BrowsingEvent.domain.isnot(None),
    ).scalar() or 0

    pipeline = {
        "total_events": pipeline_total,
        "total_value": float(pipeline_value),
        "avg_quality": round(float(pipeline_quality), 1),
        "unique_domains": unique_domains,
        "events_per_day": round(pipeline_total / 7, 1) if pipeline_total else 0,
    }

    # Event type distribution
    type_rows = db.session.query(
        BrowsingEvent.event_type,
        func.count(BrowsingEvent.id).label("cnt"),
        func.sum(BrowsingEvent.commercial_value_usd).label("val"),
        func.avg(BrowsingEvent.quality_score).label("avg_q"),
    ).filter(
        BrowsingEvent.ingested_at >= cutoff,
    ).group_by(BrowsingEvent.event_type).all()

    event_types = []
    for row in type_rows:
        pct = round(row.cnt / pipeline_total * 100, 1) if pipeline_total > 0 else 0
        event_types.append({
            "type": row.event_type or "unknown",
            "count": row.cnt,
            "value": float(row.val or 0),
            "quality": round(float(row.avg_q or 0), 1),
            "pct": pct,
        })

    # Top contributing nodes
    top_rows = db.session.query(
        BrowsingEvent.user_id,
        func.count(BrowsingEvent.id).label("cnt"),
        func.sum(BrowsingEvent.commercial_value_usd).label("val"),
    ).filter(
        BrowsingEvent.ingested_at >= cutoff,
    ).group_by(BrowsingEvent.user_id).order_by(
        func.count(BrowsingEvent.id).desc()
    ).limit(15).all()

    top_nodes = []
    for row in top_rows:
        user = User.query.get(row.user_id)
        helper = HelperProfile.query.filter_by(user_id=row.user_id).first()
        top_nodes.append({
            "email": user.email if user else f"user:{row.user_id}",
            "country": helper.country_code if helper else "—",
            "events": row.cnt,
            "value": float(row.val or 0),
            "last_seen": helper.last_seen.strftime("%b %d %H:%M") if helper and helper.last_seen else "—",
        })

    # Processor runtime stats
    try:
        from node_data_processor import node_data_processor
        proc = node_data_processor.get_processing_stats()
    except Exception:
        proc = {
            "throughput": {"total_ingested": 0, "total_duplicates": 0, "total_rejected": 0, "total_routed": 0},
            "dedup_cache": {"utilisation_pct": 0, "hit_rate": 0},
            "rate_limits": {"active_nodes": 0},
        }

    return render_template_string(
        BASE_TEMPLATE,
        title="Node Fleet Dashboard",
        content=render_template_string(
            ADMIN_NODE_FLEET_CONTENT,
            current_user=current_user,
            fleet=fleet,
            pipeline=pipeline,
            event_types=event_types,
            top_nodes=top_nodes,
            proc=proc,
        ),
        current_user=current_user,
    )


ADMIN_DISBURSEMENT_CONTENT = ADMIN_NAV + """
<h1 style="color:#f5f5f5;margin-bottom:8px;">RLUSD Disbursement Dashboard</h1>
<p style="color:#999;margin-bottom:24px;">Payout processing, epoch management, and XRPL transaction monitoring.</p>

<!-- Summary Cards -->
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-bottom:24px;">
    <div style="background:rgba(255,255,255,0.05);padding:16px;border-radius:10px;border:1px solid rgba(255,255,255,0.1);">
        <div style="font-size:11px;color:#999;text-transform:uppercase;">Pending Payouts</div>
        <div style="font-size:28px;font-weight:700;color:#ff6b35;">{{ stats.pending_count }}</div>
        <div style="font-size:12px;color:#666;">{{ "%.2f"|format(stats.pending_value) }} RLUSD</div>
    </div>
    <div style="background:rgba(255,255,255,0.05);padding:16px;border-radius:10px;border:1px solid rgba(255,255,255,0.1);">
        <div style="font-size:11px;color:#999;text-transform:uppercase;">Sent (Awaiting Confirm)</div>
        <div style="font-size:28px;font-weight:700;color:#f4b400;">{{ stats.sent_count }}</div>
        <div style="font-size:12px;color:#666;">{{ "%.2f"|format(stats.sent_value) }} RLUSD</div>
    </div>
    <div style="background:rgba(255,255,255,0.05);padding:16px;border-radius:10px;border:1px solid rgba(255,255,255,0.1);">
        <div style="font-size:11px;color:#999;text-transform:uppercase;">Confirmed</div>
        <div style="font-size:28px;font-weight:700;color:#0f9d58;">{{ stats.confirmed_count }}</div>
        <div style="font-size:12px;color:#666;">{{ "%.2f"|format(stats.confirmed_value) }} RLUSD</div>
    </div>
    <div style="background:rgba(255,255,255,0.05);padding:16px;border-radius:10px;border:1px solid rgba(255,255,255,0.1);">
        <div style="font-size:11px;color:#999;text-transform:uppercase;">Failed</div>
        <div style="font-size:28px;font-weight:700;color:#db4437;">{{ stats.failed_count }}</div>
        <div style="font-size:12px;color:#666;">{{ "%.2f"|format(stats.failed_value) }} RLUSD</div>
    </div>
</div>

<!-- Epoch Info -->
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-bottom:24px;">
    <div style="background:rgba(255,255,255,0.05);padding:16px;border-radius:10px;border:1px solid rgba(255,255,255,0.1);">
        <div style="font-size:11px;color:#999;text-transform:uppercase;">Total Epochs</div>
        <div style="font-size:28px;font-weight:700;color:#e8e8e8;">{{ stats.total_epochs }}</div>
    </div>
    <div style="background:rgba(255,255,255,0.05);padding:16px;border-radius:10px;border:1px solid rgba(255,255,255,0.1);">
        <div style="font-size:11px;color:#999;text-transform:uppercase;">Completed Epochs</div>
        <div style="font-size:28px;font-weight:700;color:#0f9d58;">{{ stats.completed_epochs }}</div>
    </div>
    <div style="background:rgba(255,255,255,0.05);padding:16px;border-radius:10px;border:1px solid rgba(255,255,255,0.1);">
        <div style="font-size:11px;color:#999;text-transform:uppercase;">Completion Rate</div>
        <div style="font-size:28px;font-weight:700;color:#4285f4;">{{ "%.0f"|format(stats.epoch_completion_pct) }}%</div>
    </div>
    <div style="background:rgba(255,255,255,0.05);padding:16px;border-radius:10px;border:1px solid rgba(255,255,255,0.1);">
        <div style="font-size:11px;color:#999;text-transform:uppercase;">Total Disbursed</div>
        <div style="font-size:28px;font-weight:700;color:#ff6b35;">{{ "%.2f"|format(stats.total_disbursed) }}</div>
        <div style="font-size:12px;color:#666;">RLUSD all-time</div>
    </div>
</div>

<!-- Recent Payouts Table -->
<h3 style="color:#f5f5f5;margin:24px 0 12px;">Recent Payouts</h3>
<div style="overflow-x:auto;">
<table style="width:100%;border-collapse:collapse;font-size:13px;">
<thead>
<tr style="border-bottom:1px solid rgba(255,255,255,0.1);">
    <th style="padding:10px 8px;text-align:left;color:#999;">User</th>
    <th style="padding:10px 8px;text-align:left;color:#999;">Wallet</th>
    <th style="padding:10px 8px;text-align:right;color:#999;">Amount</th>
    <th style="padding:10px 8px;text-align:center;color:#999;">Status</th>
    <th style="padding:10px 8px;text-align:left;color:#999;">TX Hash</th>
    <th style="padding:10px 8px;text-align:left;color:#999;">Created</th>
</tr>
</thead>
<tbody>
{% for p in recent_payouts %}
<tr style="border-bottom:1px solid rgba(255,255,255,0.05);">
    <td style="padding:8px;color:#e8e8e8;">{{ p.email }}</td>
    <td style="padding:8px;color:#999;font-family:monospace;font-size:11px;">{{ p.wallet[:12] }}…</td>
    <td style="padding:8px;text-align:right;color:#ff6b35;font-weight:600;">{{ "%.4f"|format(p.amount) }}</td>
    <td style="padding:8px;text-align:center;">
        {% if p.status == 'confirmed' %}<span style="color:#0f9d58;">✓ Confirmed</span>
        {% elif p.status == 'sent' %}<span style="color:#f4b400;">⏳ Sent</span>
        {% elif p.status == 'pending' %}<span style="color:#999;">○ Pending</span>
        {% elif p.status == 'failed' %}<span style="color:#db4437;">✗ Failed</span>
        {% else %}<span style="color:#666;">{{ p.status }}</span>{% endif %}
    </td>
    <td style="padding:8px;color:#999;font-family:monospace;font-size:11px;">{{ p.tx_hash[:16] if p.tx_hash else '—' }}</td>
    <td style="padding:8px;color:#666;">{{ p.created }}</td>
</tr>
{% endfor %}
{% if not recent_payouts %}
<tr><td colspan="6" style="padding:20px;text-align:center;color:#666;">No payouts yet.</td></tr>
{% endif %}
</tbody>
</table>
</div>

<!-- Manual Trigger -->
<div style="margin-top:32px;padding:20px;background:rgba(255,107,53,0.05);border:1px solid rgba(255,107,53,0.2);border-radius:10px;">
    <h4 style="color:#ff6b35;margin:0 0 8px;">Manual Epoch Trigger</h4>
    <p style="color:#999;font-size:13px;margin:0 0 12px;">Manually trigger a new payout epoch for today. This will calculate node uptime, create payout records, and queue them for XRPL disbursement.</p>
    <form method="POST" action="/admin/payouts/trigger-epoch" style="display:inline;">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <button type="submit" style="padding:8px 20px;background:#ff6b35;color:#fff;border:none;border-radius:6px;cursor:pointer;font-weight:600;" onclick="return confirm('Trigger new payout epoch for today?')">Trigger Epoch</button>
    </form>
</div>
"""


@app.route("/admin/payouts")
@admin_required
def admin_payouts():
    """Admin RLUSD disbursement dashboard."""
    # Get disbursement stats
    try:
        from payout_disbursement import disbursement_worker
        stats = disbursement_worker.get_disbursement_stats()
    except Exception:
        stats = {
            "pending_count": 0, "pending_value": 0,
            "sent_count": 0, "sent_value": 0,
            "confirmed_count": 0, "confirmed_value": 0,
            "failed_count": 0, "failed_value": 0,
            "total_epochs": 0, "completed_epochs": 0,
            "epoch_completion_pct": 0, "total_disbursed": 0,
        }

    # Recent payouts
    recent_payouts = []
    try:
        from models import NodePayout
        payouts = NodePayout.query.order_by(NodePayout.id.desc()).limit(25).all()
        for p in payouts:
            user = User.query.get(p.user_id)
            recent_payouts.append({
                "email": user.email if user else f"user:{p.user_id}",
                "wallet": p.wallet_address or "—",
                "amount": p.payout_amount_rlusd,
                "status": p.status,
                "tx_hash": p.tx_hash or "",
                "created": p.created_at.strftime("%b %d %H:%M") if p.created_at else "—",
            })
    except Exception:
        pass

    return render_template_string(
        BASE_TEMPLATE,
        title="RLUSD Disbursement",
        content=render_template_string(
            ADMIN_DISBURSEMENT_CONTENT,
            current_user=current_user,
            stats=stats,
            recent_payouts=recent_payouts,
        ),
        current_user=current_user,
    )


@app.route("/admin/payouts/trigger-epoch", methods=["POST"])
@admin_required
def admin_trigger_epoch():
    """Manually trigger a new payout epoch."""
    try:
        from payout_disbursement import disbursement_worker
        result = disbursement_worker.trigger_epoch_and_disburse()
        if "error" in result:
            flash(f"Epoch error: {result['error']}", "warning")
        else:
            flash(f"Epoch triggered: {result.get('epoch_id', 'unknown')} — {result.get('nodes_eligible', 0)} nodes eligible", "success")
    except Exception as e:
        flash(f"Failed to trigger epoch: {e}", "error")
    return redirect(url_for("admin_payouts"))


# --- Node Registry API Routes ---

@app.route("/api/nodes/register", methods=["POST"])
@login_required
def api_node_register():
    """Register a helper node in the CitizenSERP network."""
    try:
        from node_registry import node_registry
        data = request.get_json() or {}
        capabilities = data.get("capabilities", {})
        result = node_registry.register_node(
            user_id=current_user.id,
            capabilities=capabilities,
        )
        if result.get("error"):
            return jsonify(result), 400
        return jsonify(result)
    except Exception as e:
        logger.error(f"Node register error: {e}")
        return jsonify({"error": "Node registration failed"}), 500


@app.route("/api/nodes/heartbeat", methods=["POST"])
@login_required
def api_node_heartbeat():
    """Node heartbeat — keeps node alive in the registry."""
    try:
        from node_registry import node_registry
        data = request.get_json() or {}
        node_id = data.get("node_id", "")
        if not node_id:
            return jsonify({"error": "node_id required"}), 400
        result = node_registry.heartbeat(node_id)
        if result.get("error"):
            return jsonify(result), 404
        return jsonify(result)
    except Exception as e:
        logger.error(f"Node heartbeat error: {e}")
        return jsonify({"error": "Heartbeat failed"}), 500


@app.route("/api/nodes/unregister", methods=["POST"])
@login_required
def api_node_unregister():
    """Unregister a node from the network."""
    try:
        from node_registry import node_registry
        data = request.get_json() or {}
        node_id = data.get("node_id", "")
        if not node_id:
            return jsonify({"error": "node_id required"}), 400
        result = node_registry.unregister_node(node_id)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Node unregister error: {e}")
        return jsonify({"error": "Unregister failed"}), 500


@app.route("/api/nodes/discover")
@login_required
def api_nodes_discover():
    """Discover available nodes, optionally filtered by zone/country/task type."""
    try:
        from node_registry import node_registry
        zone = request.args.get("zone")
        country = request.args.get("country")
        task_type = request.args.get("task_type")
        nodes = node_registry.discover_nodes(
            zone=zone, country=country, task_type=task_type
        )
        return jsonify({"nodes": nodes, "count": len(nodes)})
    except Exception as e:
        logger.error(f"Node discover error: {e}")
        return jsonify({"error": "Node discovery unavailable"}), 500


@app.route("/api/nodes/topology")
@login_required
def api_nodes_topology():
    """Get network topology — node counts by zone, country, status."""
    try:
        from node_registry import node_registry
        return jsonify(node_registry.get_network_topology())
    except Exception as e:
        logger.error(f"Node topology error: {e}")
        return jsonify({"error": "Topology unavailable"}), 500


@app.route("/api/nodes/my")
@login_required
def api_nodes_my():
    """Get the current user's registered node(s)."""
    try:
        from node_registry import node_registry
        node = node_registry.get_node_for_user(current_user.id)
        if not node:
            return jsonify({"registered": False})
        return jsonify({"registered": True, "node": node})
    except Exception as e:
        logger.error(f"My node error: {e}")
        return jsonify({"error": "Node lookup failed"}), 500


@app.route("/api/network/readiness")
@login_required
def api_network_readiness():
    """CitizenSERP network readiness — milestone progress and phase status.

    Returns current milestone, next target, progress percentages,
    and whether the network has hit the threshold for Phase 2 activation.
    Admin-only: full zone/country breakdown. Regular users: summary only.
    """
    try:
        from node_registry import check_citizenserp_readiness
        readiness = check_citizenserp_readiness()

        # Non-admin users get a summary (no zone/country breakdown — OPSEC)
        is_admin = getattr(current_user, "is_admin", False)
        if not is_admin:
            readiness["network_stats"].pop("by_country", None)
            readiness["network_stats"].pop("by_zone", None)

        return jsonify(readiness)
    except Exception as e:
        logger.error(f"Network readiness error: {e}")
        return jsonify({"error": "Readiness check unavailable"}), 500


# --- Node Self-Onboarding (Build #91) ---

@app.route("/api/node/onboard", methods=["POST"])
@login_required
def api_node_onboard():
    """One-shot node onboarding — creates helper profile, generates token,
    registers node, and marks Google account linked.

    POST JSON body (all optional):
        country_code: 2-letter ISO (default: "US")
        city: city name
        zone_code: sub-regional zone (e.g. "US-NE")

    Returns helper_token + node instructions.
    """
    import secrets as _secrets
    try:
        data = request.get_json(silent=True) or {}
        country_code = (data.get("country_code") or "US").strip().upper()[:2]
        city = (data.get("city") or "").strip() or None
        zone_code = (data.get("zone_code") or "").strip() or None

        # Derive zone from city if not provided
        if not zone_code and city:
            try:
                from geographic_zones import get_zone_for_city
                zone = get_zone_for_city(city)
                if zone:
                    zone_code = zone.zone_code
            except Exception:
                pass

        # Step 1 — HelperProfile (create or reactivate)
        helper = HelperProfile.query.filter_by(user_id=current_user.id).first()
        if helper:
            helper.is_active = True
            helper.is_approved = True
            helper.country_code = country_code
            if city:
                helper.city = city
            if zone_code:
                helper.zone_code = zone_code
        else:
            helper = HelperProfile(
                user_id=current_user.id,
                country_code=country_code,
                city=city,
                zone_code=zone_code,
                is_active=True,
                is_approved=True,
            )
            db.session.add(helper)

        # Step 2 — Generate helper token if missing
        if not helper.helper_token:
            helper.helper_token = _secrets.token_urlsafe(48)

        # Step 3 — Mark Google account linked (user logged in via OAuth)
        if current_user.google_id:
            helper.google_account_linked = True

        # Step 4 — Flag user as helper node
        current_user.is_helper_node = True

        db.session.commit()

        # Step 5 — Register node in the live registry
        node_result = {}
        try:
            from node_registry import node_registry
            node_result = node_registry.register_node(
                user_id=current_user.id,
                token=helper.helper_token,
                capabilities_dict={
                    "country_code": country_code,
                    "city": city,
                    "zone_code": zone_code,
                    "has_browser": True,
                    "has_auth_sessions": helper.google_account_linked,
                    "max_concurrent_tasks": 2,
                    "supported_task_types": [
                        "flight_search", "hotel_search", "cruise_search",
                        "product_search", "general_search",
                    ],
                },
            )
        except Exception as e:
            logger.warning(f"Node registry registration failed (non-blocking): {e}")
            node_result = {"warning": "Registry unavailable — node will register on first heartbeat"}

        # Step 6 — Start CitizenSERP payout session
        try:
            from citizenserp_payouts import citizenserp_manager
            wallet = UserWallet.query.filter_by(
                user_id=current_user.id, is_primary=True, is_verified=True
            ).first()
            if wallet:
                citizenserp_manager.record_node_online(
                    user_id=current_user.id,
                    wallet_address=wallet.wallet_address,
                    ip_country=country_code,
                    ip_zone=zone_code,
                )
        except Exception as e:
            logger.warning(f"CitizenSERP session start failed (non-blocking): {e}")

        return jsonify({
            "success": True,
            "helper_token": helper.helper_token,
            "node_id": node_result.get("node_id") or helper.node_id,
            "country_code": country_code,
            "zone_code": zone_code,
            "google_linked": helper.google_account_linked,
            "next_steps": [
                f"Run: python3 helper_client.py --token {helper.helper_token}",
                "The Playwright browser will launch — log into Google if not already",
                "Your node is now live and accepting search tasks",
            ],
        })

    except Exception as e:
        logger.exception(f"Node onboarding error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# --- Vertical Pipeline API Routes ---

@app.route("/api/pipelines/verticals")
@login_required
def api_pipeline_verticals():
    """List supported verticals with pipeline descriptions."""
    try:
        from vertical_pipelines import pipeline_manager
        return jsonify({
            "verticals": pipeline_manager.get_supported_verticals(),
        })
    except Exception as e:
        logger.error(f"Pipeline verticals error: {e}")
        return jsonify({"error": "Pipeline info unavailable"}), 500


@app.route("/api/pipelines/process", methods=["POST"])
@login_required
def api_pipeline_process():
    """Process search results through a vertical pipeline."""
    try:
        from vertical_pipelines import pipeline_manager
        data = request.get_json() or {}
        task_type = data.get("task_type", "")
        results = data.get("results", [])
        user_market = data.get("user_market", "US")

        if not task_type or not results:
            return jsonify({"error": "task_type and results are required"}), 400

        processed = pipeline_manager.process(task_type, results, user_market)
        return jsonify(processed)
    except Exception as e:
        logger.error(f"Pipeline process error: {e}")
        return jsonify({"error": "Pipeline processing failed"}), 500


# --- Intelligence Feedback API Routes ---

@app.route("/api/feedback/stats")
@login_required
def api_feedback_stats():
    """Get intelligence feedback engine statistics."""
    try:
        from intelligence_feedback import feedback_engine
        return jsonify(feedback_engine.get_feedback_stats())
    except Exception as e:
        logger.error(f"Feedback stats error: {e}")
        return jsonify({"error": "Feedback stats unavailable"}), 500


@app.route("/api/feedback/anomalies")
@login_required
def api_feedback_anomalies():
    """Get recently detected price anomalies."""
    try:
        from intelligence_feedback import feedback_engine
        limit = request.args.get("limit", 50, type=int)
        anomalies = feedback_engine.get_recent_anomalies(limit=limit)
        return jsonify({"anomalies": anomalies, "count": len(anomalies)})
    except Exception as e:
        logger.error(f"Feedback anomalies error: {e}")
        return jsonify({"error": "Anomaly data unavailable"}), 500


@app.route("/api/feedback/route-cache/<origin>/<destination>")
@login_required
def api_feedback_route_cache(origin, destination):
    """Get cached route intelligence for a specific route."""
    try:
        from intelligence_feedback import feedback_engine
        cache = feedback_engine.get_route_cache(origin.upper(), destination.upper())
        if not cache:
            return jsonify({"error": "No cached data for this route"}), 404
        return jsonify(cache)
    except Exception as e:
        logger.error(f"Route cache error: {e}")
        return jsonify({"error": "Route cache unavailable"}), 500


# --- Dispute Arbitration API Routes ---

@app.route("/api/disputes/<int:dispute_id>/auto-evaluate", methods=["POST"])
@login_required
def api_dispute_auto_evaluate(dispute_id):
    """Run automated 6-factor evaluation on a dispute."""
    try:
        from dispute_resolution import dispute_engine
        result = dispute_engine.auto_evaluate(dispute_id)
        if result.get("error"):
            return jsonify(result), 400
        return jsonify(result)
    except Exception as e:
        logger.error(f"Dispute auto-evaluate error: {e}")
        return jsonify({"error": "Auto-evaluation failed"}), 500


@app.route("/api/disputes/<int:dispute_id>/auto-resolve", methods=["POST"])
@login_required
def api_dispute_auto_resolve(dispute_id):
    """Auto-resolve a dispute if confidence threshold is met."""
    try:
        from dispute_resolution import dispute_engine
        result = dispute_engine.auto_resolve(dispute_id)
        if result.get("error"):
            return jsonify(result), 400
        return jsonify(result)
    except Exception as e:
        logger.error(f"Dispute auto-resolve error: {e}")
        return jsonify({"error": "Auto-resolve failed"}), 500


@app.route("/api/disputes/<int:dispute_id>/evidence", methods=["POST"])
@login_required
def api_dispute_add_evidence(dispute_id):
    """Add evidence to an open dispute."""
    try:
        from dispute_resolution import dispute_engine
        data = request.get_json() or {}
        evidence_type = data.get("evidence_type", "other")
        content = data.get("content", "")
        if not content:
            return jsonify({"error": "Evidence content is required"}), 400
        result = dispute_engine.add_evidence(
            dispute_id=dispute_id,
            submitted_by=current_user.id,
            evidence_type=evidence_type,
            content=content,
        )
        if result.get("error"):
            return jsonify(result), 400
        return jsonify(result)
    except Exception as e:
        logger.error(f"Dispute evidence error: {e}")
        return jsonify({"error": "Evidence submission failed"}), 500


@app.route("/api/disputes/analytics")
@login_required
def api_dispute_analytics():
    """Get dispute resolution analytics (admin-level)."""
    try:
        from dispute_resolution import dispute_engine
        analytics = dispute_engine.get_dispute_analytics()
        return jsonify(analytics)
    except Exception as e:
        logger.error(f"Dispute analytics error: {e}")
        return jsonify({"error": "Dispute analytics unavailable"}), 500


# --- Extension auto-update server (Build #70) ---

@app.route("/extension/updates.xml")
def extension_updates_xml():
    """Serve Chrome extension update manifest for self-hosted auto-update."""
    import glob as glob_mod
    update_file = os.path.join(app.root_path, "phoenix_extension", "dist", "update.xml")
    if not os.path.exists(update_file):
        # Generate on-the-fly from manifest version
        manifest_path = os.path.join(app.root_path, "phoenix_extension", "manifest.json")
        if not os.path.exists(manifest_path):
            return Response("Extension not built", status=404, content_type="text/plain")
        with open(manifest_path) as f:
            manifest = json.loads(f.read())
        version = manifest.get("version", "1.0.0")
        ext_id = "phoenix-node-extension"
        base_url = request.host_url.rstrip("/")
        xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<gupdate xmlns="http://www.google.com/update2/response" protocol="2.0">
  <app appid="{ext_id}">
    <updatecheck codebase="{base_url}/extension/download/{version}" version="{version}" />
  </app>
</gupdate>'''
        return Response(xml, content_type="application/xml")
    with open(update_file) as f:
        return Response(f.read(), content_type="application/xml")


@app.route("/extension/download/<version>")
def extension_download(version):
    """Serve Chrome extension ZIP for a specific version."""
    import re
    if not re.match(r'^[\d.]+$', version):
        return jsonify({"error": "Invalid version format"}), 400
    dist_dir = os.path.join(app.root_path, "phoenix_extension", "dist")
    zip_name = f"phoenix_extension_v{version}.zip"
    zip_path = os.path.join(dist_dir, zip_name)
    if not os.path.exists(zip_path):
        # Try without v prefix
        zip_name = f"phoenix_extension_{version}.zip"
        zip_path = os.path.join(dist_dir, zip_name)
    if not os.path.exists(zip_path):
        return jsonify({"error": f"Version {version} not found"}), 404
    from flask import send_file
    return send_file(zip_path, mimetype="application/zip", as_attachment=True, download_name=zip_name)


# --- Register commercial & airline intelligence routes ---

from commercial_auth import register_commercial_routes
register_commercial_routes(app)

from airline_auth import register_airline_routes
register_airline_routes(app)

# --- Register SSE & XRPL monitor routes ---

from event_stream import register_sse_routes
register_sse_routes(app)

from xrpl_monitor import register_monitor_routes
register_monitor_routes(app)

from node_service_api import register_node_service_routes
register_node_service_routes(app)

from phoenix_ai_api import register_phoenix_ai_routes
register_phoenix_ai_routes(app, csrf=csrf)

from data_marketplace import register_data_marketplace_routes
register_data_marketplace_routes(app)

# --- Node Consent Economy routes (Build #75) ---
from node_consent_api import register_node_consent_routes
register_node_consent_routes(app)

# --- Universal Arbitrage Market Tool routes (Build #76) ---
from arbitrage_api import arbitrage_bp
app.register_blueprint(arbitrage_bp)
csrf.exempt(arbitrage_bp)

# --- Payment Zone Compatibility Layer (Build #85) ---
from payment_compatibility_api import payment_compat_bp
app.register_blueprint(payment_compat_bp)
csrf.exempt(payment_compat_bp)

# --- Node Service Installer Endpoint (Build #91) ---
@app.route("/api/v1/node/installer", methods=["GET"])
@login_required
def node_installer_download():
    """Return a personalized installer script with the user's helper_token.

    Query params:
      os: macos | linux | windows (default: auto-detect from User-Agent)
    """
    import platform as _platform
    from models import HelperProfile

    helper = HelperProfile.query.filter_by(user_id=current_user.id).first()
    if not helper or not helper.helper_token:
        return jsonify({"error": "No helper token found. Complete onboarding first."}), 404

    # Determine target OS
    target_os = request.args.get("os", "").lower()
    if target_os not in ("macos", "linux", "windows"):
        ua = request.headers.get("User-Agent", "").lower()
        if "windows" in ua:
            target_os = "windows"
        elif "mac" in ua:
            target_os = "macos"
        else:
            target_os = "linux"

    server_url = request.url_root.rstrip("/")
    token = helper.helper_token

    if target_os == "windows":
        # Return PowerShell one-liner
        script = (
            f'# Phoenix Node Service Installer\n'
            f'# Run this in PowerShell as Administrator\n'
            f'$Token = "{token}"\n'
            f'$Server = "{server_url}"\n'
            f'Invoke-WebRequest -Uri "$Server/static/scripts/install-node-service.ps1" '
            f'-OutFile "$env:TEMP\\install-phoenix-node.ps1"\n'
            f'& "$env:TEMP\\install-phoenix-node.ps1" -Token $Token -Server $Server\n'
        )
        return Response(
            script,
            mimetype="text/plain",
            headers={"Content-Disposition": "attachment; filename=install-phoenix-node.ps1"},
        )
    else:
        # Return bash one-liner
        script = (
            f'#!/bin/bash\n'
            f'# Phoenix Node Service Installer\n'
            f'TOKEN="{token}"\n'
            f'SERVER="{server_url}"\n'
            f'curl -sSL "$SERVER/static/scripts/install-node-service.sh" | '
            f'bash -s -- --token "$TOKEN" --server "$SERVER"\n'
        )
        return Response(
            script,
            mimetype="text/plain",
            headers={"Content-Disposition": f"attachment; filename=install-phoenix-node.sh"},
        )

# Seed default payment compatibility rules if table is empty
try:
    with app.app_context():
        from payment_compatibility import payment_compat_engine
        from models import PaymentZoneRule
        if PaymentZoneRule.query.first() is None:
            payment_compat_engine.seed_default_rules()
except Exception:
    pass

# Seed default ramp providers if table is empty (Build #86)
try:
    with app.app_context():
        from payment_ramps import ramp_engine
        from models import RampProvider
        if RampProvider.query.first() is None:
            ramp_engine.seed_default_providers()
except Exception:
    pass

# --- Strategy Learner Templates & Routes (Build #73) ---

BYOAI_SETTINGS_CONTENT = """
<div style="max-width:900px;margin:0 auto;">
    <div style="margin-bottom:30px;">
        <h1 style="color:#fff;margin:0 0 8px 0;font-size:28px;">AI Provider Settings</h1>
        <p style="color:#aaa;margin:0;font-size:15px;">Bring Your Own AI (BYOAI) — connect your personal AI provider keys for flight search intelligence, or use PhoenixAI for optimized results.</p>
    </div>

    <!-- Current Providers -->
    <div style="background:#16213e;border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:24px;margin-bottom:24px;">
        <h2 style="color:#fff;margin:0 0 16px 0;font-size:20px;">Current Providers</h2>
        {% if providers %}
        <div style="display:flex;flex-direction:column;gap:12px;">
            {% for key, prov in providers.items() %}
            <div style="display:flex;align-items:center;justify-content:space-between;padding:14px 18px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:8px;">
                <div style="display:flex;align-items:center;gap:12px;">
                    {% if prov.available %}
                    <span style="width:10px;height:10px;border-radius:50%;background:#00e676;display:inline-block;"></span>
                    {% else %}
                    <span style="width:10px;height:10px;border-radius:50%;background:#555;display:inline-block;"></span>
                    {% endif %}
                    <div>
                        <span style="color:#fff;font-weight:600;font-size:15px;">{{ prov.name }}</span>
                        {% if prov.source %}
                        <span style="color:#00d4ff;font-size:12px;margin-left:8px;padding:2px 8px;background:rgba(0,212,255,0.1);border-radius:4px;">{{ prov.source }}</span>
                        {% endif %}
                        {% if prov.strengths %}
                        <p style="color:#888;margin:4px 0 0 0;font-size:13px;">{{ prov.strengths }}</p>
                        {% endif %}
                    </div>
                </div>
                {% if prov.source == 'user' %}
                <button onclick="removeProvider('{{ key }}')" style="background:rgba(255,82,82,0.15);color:#ff5252;border:1px solid rgba(255,82,82,0.3);padding:6px 14px;border-radius:6px;cursor:pointer;font-size:13px;">Remove</button>
                {% endif %}
            </div>
            {% endfor %}
        </div>
        {% else %}
        <p style="color:#888;">No providers configured yet.</p>
        {% endif %}
    </div>

    <!-- Add Provider Form -->
    <div style="background:#16213e;border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:24px;margin-bottom:24px;">
        <h2 style="color:#fff;margin:0 0 16px 0;font-size:20px;">Add AI Provider</h2>
        <div style="display:flex;flex-direction:column;gap:14px;">
            <div>
                <label style="color:#ccc;font-size:13px;display:block;margin-bottom:6px;">Provider</label>
                <select id="addProviderKey" style="width:100%;padding:10px 14px;background:#1a1a2e;color:#fff;border:1px solid rgba(255,255,255,0.15);border-radius:8px;font-size:14px;">
                    <option value="">Select a provider...</option>
                    <option value="anthropic">Anthropic (Claude)</option>
                    <option value="openai">OpenAI (GPT)</option>
                    <option value="google">Google (Gemini)</option>
                    <option value="mistral">Mistral AI</option>
                    <option value="xai">xAI (Grok)</option>
                    <option value="deepseek">DeepSeek</option>
                    <option value="cohere">Cohere</option>
                    <option value="huggingface">Hugging Face</option>
                </select>
            </div>
            <div>
                <label style="color:#ccc;font-size:13px;display:block;margin-bottom:6px;">API Key</label>
                <input type="password" id="addProviderApiKey" placeholder="sk-..." style="width:100%;padding:10px 14px;background:#1a1a2e;color:#fff;border:1px solid rgba(255,255,255,0.15);border-radius:8px;font-size:14px;box-sizing:border-box;">
            </div>
            <div>
                <label style="color:#ccc;font-size:13px;display:block;margin-bottom:6px;">Custom Model (optional)</label>
                <input type="text" id="addProviderModel" placeholder="e.g. claude-3-opus-20240229" style="width:100%;padding:10px 14px;background:#1a1a2e;color:#fff;border:1px solid rgba(255,255,255,0.15);border-radius:8px;font-size:14px;box-sizing:border-box;">
            </div>
            <div style="display:flex;gap:10px;">
                <button onclick="testProvider()" style="padding:10px 20px;background:rgba(0,212,255,0.15);color:#00d4ff;border:1px solid rgba(0,212,255,0.3);border-radius:8px;cursor:pointer;font-size:14px;font-weight:600;">Test Connection</button>
                <button onclick="addProvider()" style="padding:10px 20px;background:#00d4ff;color:#1a1a2e;border:none;border-radius:8px;cursor:pointer;font-size:14px;font-weight:600;">Test &amp; Save</button>
            </div>
            <div id="testResult" style="display:none;padding:10px 14px;border-radius:8px;font-size:13px;margin-top:4px;"></div>
        </div>
    </div>

    <!-- PhoenixAI Comparison -->
    <div style="background:#16213e;border:1px solid rgba(0,212,255,0.2);border-radius:12px;padding:24px;margin-bottom:24px;">
        <h2 style="color:#00d4ff;margin:0 0 16px 0;font-size:20px;">PhoenixAI Comparison</h2>
        {% if comparison_stats %}
        <div style="background:rgba(0,212,255,0.08);border:1px solid rgba(0,212,255,0.15);border-radius:8px;padding:16px;margin-bottom:16px;">
            <p style="color:#fff;margin:0 0 8px 0;font-size:15px;font-weight:600;">Last Comparison Results</p>
            <p style="color:#00e676;margin:0;font-size:14px;">PhoenixAI found {{ comparison_stats.additional_pct }}% more results</p>
            <div style="display:flex;gap:20px;margin-top:10px;">
                <span style="color:#aaa;font-size:13px;">Your results: <strong style="color:#fff;">{{ comparison_stats.user_count }}</strong></span>
                <span style="color:#aaa;font-size:13px;">PhoenixAI results: <strong style="color:#00d4ff;">{{ comparison_stats.phoenix_count }}</strong></span>
            </div>
        </div>
        {% endif %}
        <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;">
            <button onclick="runComparison()" id="compareBtn" style="padding:12px 24px;background:#00d4ff;color:#1a1a2e;border:none;border-radius:8px;cursor:pointer;font-size:14px;font-weight:600;" {% if not can_compare %}disabled style="opacity:0.5;cursor:not-allowed;"{% endif %}>Compare with PhoenixAI</button>
            <span style="color:#888;font-size:13px;">
                {% if comparisons_remaining == -1 %}
                    Unlimited comparisons (Pro)
                {% elif comparisons_remaining > 0 %}
                    {{ comparisons_remaining }} free comparison{{ 's' if comparisons_remaining != 1 else '' }} remaining today
                {% else %}
                    Daily comparison used — upgrade for unlimited
                {% endif %}
            </span>
        </div>
        <div id="comparisonResult" style="display:none;margin-top:16px;"></div>
        <div id="comparisonLoading" style="display:none;margin-top:16px;color:#aaa;font-size:14px;">Running comparison... this may take a moment.</div>
    </div>

    <!-- Why PhoenixAI -->
    <div style="background:linear-gradient(135deg,#16213e 0%,#1a1a3e 100%);border:1px solid rgba(0,212,255,0.15);border-radius:12px;padding:24px;">
        <h2 style="color:#fff;margin:0 0 16px 0;font-size:20px;">Why PhoenixAI?</h2>
        <ul style="color:#ccc;font-size:14px;line-height:2;padding-left:20px;margin:0;">
            <li><strong style="color:#00d4ff;">Learned Strategies</strong> — Continuously learns the best search strategies from thousands of queries</li>
            <li><strong style="color:#00d4ff;">Multi-Market Proxy Access</strong> — Searches across multiple market proxies simultaneously for wider coverage</li>
            <li><strong style="color:#00d4ff;">Collective Intelligence</strong> — Benefits from patterns discovered across all users, not just your own searches</li>
            <li><strong style="color:#00d4ff;">Zero Configuration</strong> — No API keys needed, no model selection, just results</li>
            <li><strong style="color:#00d4ff;">Strategy Optimization</strong> — Automatically applies the most effective search approach for each route and date</li>
        </ul>
    </div>
</div>

<script>
function getCsrfToken() {
    const meta = document.querySelector('meta[name=csrf-token]');
    if (meta) return meta.content;
    const cookies = document.cookie.split(';');
    for (let c of cookies) {
        c = c.trim();
        if (c.startsWith('csrf_token=')) return c.substring(11);
    }
    return '';
}

async function addProvider() {
    const provider = document.getElementById('addProviderKey').value;
    if (!provider) return alert('Select a provider');
    const api_key = document.getElementById('addProviderApiKey').value;
    const model = document.getElementById('addProviderModel').value;
    if (!api_key) return alert('API key is required');

    try {
        const resp = await fetch('/api/portal/ai/providers', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken()},
            body: JSON.stringify({provider, api_key, model: model || null})
        });
        const data = await resp.json();
        if (data.error) { alert(data.error); return; }
        alert('Provider saved successfully!');
        location.reload();
    } catch(e) { alert('Failed: ' + e.message); }
}

async function removeProvider(key) {
    if (!confirm('Remove this provider?')) return;
    try {
        const resp = await fetch('/api/portal/ai/providers/' + key, {
            method: 'DELETE',
            headers: {'X-CSRFToken': getCsrfToken()}
        });
        const data = await resp.json();
        if (data.error) { alert(data.error); return; }
        location.reload();
    } catch(e) { alert('Failed: ' + e.message); }
}

async function testProvider() {
    const provider = document.getElementById('addProviderKey').value;
    const api_key = document.getElementById('addProviderApiKey').value;
    if (!provider || !api_key) return alert('Select a provider and enter an API key');

    const resultDiv = document.getElementById('testResult');
    resultDiv.style.display = 'block';
    resultDiv.style.background = 'rgba(255,255,255,0.05)';
    resultDiv.style.color = '#aaa';
    resultDiv.textContent = 'Testing connection...';

    try {
        const resp = await fetch('/api/portal/ai/providers/test', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken()},
            body: JSON.stringify({provider, api_key})
        });
        const data = await resp.json();
        if (data.ok) {
            resultDiv.style.background = 'rgba(0,230,118,0.1)';
            resultDiv.style.color = '#00e676';
            resultDiv.textContent = data.message;
        } else {
            resultDiv.style.background = 'rgba(255,82,82,0.1)';
            resultDiv.style.color = '#ff5252';
            resultDiv.textContent = data.error || 'Test failed';
        }
    } catch(e) {
        resultDiv.style.background = 'rgba(255,82,82,0.1)';
        resultDiv.style.color = '#ff5252';
        resultDiv.textContent = 'Connection failed: ' + e.message;
    }
}

async function runComparison() {
    const btn = document.getElementById('compareBtn');
    const loading = document.getElementById('comparisonLoading');
    const result = document.getElementById('comparisonResult');

    btn.disabled = true;
    btn.style.opacity = '0.5';
    loading.style.display = 'block';
    result.style.display = 'none';

    try {
        const resp = await fetch('/api/v1/ai/compare', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken()},
            body: JSON.stringify({query_params: {}, byoai_results: []})
        });
        const data = await resp.json();
        loading.style.display = 'none';

        if (data.error) {
            result.style.display = 'block';
            result.innerHTML = '<div style="background:rgba(255,82,82,0.1);border:1px solid rgba(255,82,82,0.2);border-radius:8px;padding:14px;color:#ff5252;">' + data.error + '</div>';
            return;
        }

        let html = '<div style="background:rgba(0,212,255,0.08);border:1px solid rgba(0,212,255,0.15);border-radius:8px;padding:16px;">';
        html += '<h3 style="color:#00d4ff;margin:0 0 12px 0;">Comparison Results</h3>';
        html += '<table style="width:100%;border-collapse:collapse;color:#fff;font-size:13px;">';
        html += '<tr style="border-bottom:1px solid rgba(255,255,255,0.1);"><th style="text-align:left;padding:8px;color:#aaa;">Metric</th><th style="text-align:left;padding:8px;color:#aaa;">BYOAI</th><th style="text-align:left;padding:8px;color:#aaa;">PhoenixAI</th></tr>';
        if (data.user_count !== undefined) {
            html += '<tr style="border-bottom:1px solid rgba(255,255,255,0.05);"><td style="padding:8px;">Results Found</td><td style="padding:8px;">' + (data.user_count || 0) + '</td><td style="padding:8px;color:#00d4ff;">' + (data.phoenix_count || 0) + '</td></tr>';
        }
        if (data.additional_pct !== undefined) {
            html += '<tr><td style="padding:8px;">Additional Coverage</td><td style="padding:8px;">—</td><td style="padding:8px;color:#00e676;">+' + data.additional_pct + '%</td></tr>';
        }
        html += '</table></div>';
        result.style.display = 'block';
        result.innerHTML = html;
    } catch(e) {
        loading.style.display = 'none';
        result.style.display = 'block';
        result.innerHTML = '<div style="background:rgba(255,82,82,0.1);border:1px solid rgba(255,82,82,0.2);border-radius:8px;padding:14px;color:#ff5252;">Comparison failed: ' + e.message + '</div>';
    } finally {
        btn.disabled = false;
        btn.style.opacity = '1';
    }
}
</script>
"""

ADMIN_STRATEGY_CONTENT = """
""" + ADMIN_NAV + """
<h1 style="color:#fff;margin:0 0 8px 0;">Strategy Learner Dashboard</h1>
<p style="color:#888;margin:0 0 24px 0;">Monitor AI strategy learning, observations, and insights.</p>

{% if stats.get('error') %}
<div style="background:rgba(255,82,82,0.1);border:1px solid rgba(255,82,82,0.2);border-radius:8px;padding:16px;color:#ff5252;margin-bottom:20px;">
    Error loading stats: {{ stats.error }}
</div>
{% else %}

<!-- Overview Cards -->
<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:24px;">
    <div style="background:#16213e;border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:20px;text-align:center;">
        <div style="color:#00d4ff;font-size:32px;font-weight:700;">{{ stats.get('total_observations', 0) }}</div>
        <div style="color:#aaa;font-size:13px;margin-top:6px;">Total Observations</div>
    </div>
    <div style="background:#16213e;border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:20px;text-align:center;">
        <div style="color:#00e676;font-size:32px;font-weight:700;">{{ stats.get('active_insights', 0) }}</div>
        <div style="color:#aaa;font-size:13px;margin-top:6px;">Active Insights</div>
    </div>
    <div style="background:#16213e;border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:20px;text-align:center;">
        <div style="color:#ff9800;font-size:32px;font-weight:700;">{{ "%.1f"|format(stats.get('avg_quality_score', 0)) }}</div>
        <div style="color:#aaa;font-size:13px;margin-top:6px;">Avg Quality Score</div>
    </div>
    <div style="background:#16213e;border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:20px;text-align:center;">
        <div style="color:#ba68c8;font-size:32px;font-weight:700;">{{ stats.get('observations_24h', 0) }}</div>
        <div style="color:#aaa;font-size:13px;margin-top:6px;">Observations (24h)</div>
    </div>
</div>

<!-- Observations by Source -->
<div style="background:#16213e;border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:24px;margin-bottom:24px;">
    <h2 style="color:#fff;margin:0 0 16px 0;font-size:18px;">Observations by Source</h2>
    {% set sources = stats.get('by_source', {}) %}
    {% set total_obs = stats.get('total_observations', 1) %}
    {% for source_name, source_count in sources.items() %}
    {% set pct = (source_count / total_obs * 100) if total_obs > 0 else 0 %}
    <div style="margin-bottom:12px;">
        <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
            <span style="color:#ccc;font-size:13px;">{{ source_name }}</span>
            <span style="color:#aaa;font-size:13px;">{{ source_count }} ({{ "%.1f"|format(pct) }}%)</span>
        </div>
        <div style="background:rgba(255,255,255,0.08);border-radius:4px;height:8px;overflow:hidden;">
            <div style="height:100%;border-radius:4px;width:{{ pct }}%;background:{% if source_name == 'ensemble' %}#00d4ff{% elif source_name == 'byoai' %}#00e676{% elif source_name == 'phoenix_ai' %}#ff9800{% elif source_name == 'serp' %}#ba68c8{% else %}#888{% endif %};"></div>
        </div>
    </div>
    {% endfor %}
    {% if not sources %}
    <p style="color:#888;font-size:13px;">No observation data yet.</p>
    {% endif %}
</div>

<div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-bottom:24px;">
    <!-- Top Strategy Sites -->
    <div style="background:#16213e;border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:24px;">
        <h2 style="color:#fff;margin:0 0 16px 0;font-size:18px;">Top Strategy Sites</h2>
        {% if stats.get('top_sites') %}
        <table style="width:100%;border-collapse:collapse;">
            <tr style="border-bottom:1px solid rgba(255,255,255,0.1);">
                <th style="text-align:left;padding:8px;color:#aaa;font-size:12px;font-weight:600;">Rank</th>
                <th style="text-align:left;padding:8px;color:#aaa;font-size:12px;font-weight:600;">Domain</th>
                <th style="text-align:left;padding:8px;color:#aaa;font-size:12px;font-weight:600;">Category</th>
                <th style="text-align:right;padding:8px;color:#aaa;font-size:12px;font-weight:600;">Effectiveness</th>
                <th style="text-align:right;padding:8px;color:#aaa;font-size:12px;font-weight:600;">Observations</th>
            </tr>
            {% for site in stats.top_sites[:10] %}
            <tr style="border-bottom:1px solid rgba(255,255,255,0.05);">
                <td style="padding:8px;color:#888;font-size:13px;">#{{ loop.index }}</td>
                <td style="padding:8px;color:#fff;font-size:13px;">{{ site.domain }}</td>
                <td style="padding:8px;color:#aaa;font-size:13px;">{{ site.category or '—' }}</td>
                <td style="padding:8px;text-align:right;color:#00e676;font-size:13px;font-weight:600;">{{ "%.1f"|format(site.effectiveness) }}%</td>
                <td style="padding:8px;text-align:right;color:#aaa;font-size:13px;">{{ site.observation_count }}</td>
            </tr>
            {% endfor %}
        </table>
        {% else %}
        <p style="color:#888;font-size:13px;">No site data yet.</p>
        {% endif %}
    </div>

    <!-- Top Strategies -->
    <div style="background:#16213e;border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:24px;">
        <h2 style="color:#fff;margin:0 0 16px 0;font-size:18px;">Top Strategies</h2>
        {% if stats.get('top_strategies') %}
        <table style="width:100%;border-collapse:collapse;">
            <tr style="border-bottom:1px solid rgba(255,255,255,0.1);">
                <th style="text-align:left;padding:8px;color:#aaa;font-size:12px;font-weight:600;">Strategy</th>
                <th style="text-align:left;padding:8px;color:#aaa;font-size:12px;font-weight:600;">Category</th>
                <th style="text-align:right;padding:8px;color:#aaa;font-size:12px;font-weight:600;">Effectiveness</th>
                <th style="text-align:right;padding:8px;color:#aaa;font-size:12px;font-weight:600;">Usage Rate</th>
            </tr>
            {% for strat in stats.top_strategies[:10] %}
            <tr style="border-bottom:1px solid rgba(255,255,255,0.05);">
                <td style="padding:8px;color:#fff;font-size:13px;">{{ strat.name }}</td>
                <td style="padding:8px;color:#aaa;font-size:13px;">{{ strat.category or '—' }}</td>
                <td style="padding:8px;text-align:right;color:#00d4ff;font-size:13px;font-weight:600;">{{ "%.1f"|format(strat.effectiveness) }}%</td>
                <td style="padding:8px;text-align:right;color:#aaa;font-size:13px;">{{ "%.1f"|format(strat.usage_rate) }}%</td>
            </tr>
            {% endfor %}
        </table>
        {% else %}
        <p style="color:#888;font-size:13px;">No strategy data yet.</p>
        {% endif %}
    </div>
</div>

<!-- Comparison Stats -->
<div style="background:#16213e;border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:24px;margin-bottom:24px;">
    <h2 style="color:#fff;margin:0 0 16px 0;font-size:18px;">Comparison Stats</h2>
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px;">
        <div style="background:rgba(0,212,255,0.08);border-radius:8px;padding:16px;text-align:center;">
            <div style="color:#00d4ff;font-size:28px;font-weight:700;">{{ "%.1f"|format(stats.get('comparison_win_rate', 0)) }}%</div>
            <div style="color:#aaa;font-size:13px;margin-top:4px;">Win Rate</div>
        </div>
        <div style="background:rgba(0,230,118,0.08);border-radius:8px;padding:16px;text-align:center;">
            <div style="color:#00e676;font-size:28px;font-weight:700;">{{ stats.get('total_comparisons', 0) }}</div>
            <div style="color:#aaa;font-size:13px;margin-top:4px;">Total Comparisons</div>
        </div>
        <div style="background:rgba(255,152,0,0.08);border-radius:8px;padding:16px;text-align:center;">
            <div style="color:#ff9800;font-size:28px;font-weight:700;">{{ "%.1f"|format(stats.get('avg_additional_results', 0)) }}</div>
            <div style="color:#aaa;font-size:13px;margin-top:4px;">Avg Additional Results</div>
        </div>
    </div>
</div>

<!-- Aggregate Button -->
<div style="text-align:center;margin-bottom:24px;">
    <form method="POST" action="/admin/strategy/aggregate" style="display:inline;">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <button type="submit" style="padding:12px 32px;background:#00d4ff;color:#1a1a2e;border:none;border-radius:8px;cursor:pointer;font-size:15px;font-weight:600;">Trigger Aggregation</button>
    </form>
    <p style="color:#888;font-size:12px;margin-top:8px;">Manually run strategy insight aggregation from collected observations.</p>
</div>

{% endif %}
"""


@app.route("/settings/ai-providers")
@login_required
def settings_ai_providers():
    """BYOAI settings page — manage personal AI provider keys."""
    from ai_search import phoenix_ai, AI_PROVIDERS
    platform = phoenix_ai.get_platform_providers()
    user_provs = phoenix_ai.get_user_providers(current_user.id)

    providers = {}
    for key, info in AI_PROVIDERS.items():
        providers[key] = {
            "name": info["name"],
            "strengths": info.get("strengths", ""),
            "available": key in platform or key in user_provs,
            "source": "user" if key in user_provs else ("platform" if key in platform else None),
        }

    # Comparison stats
    comparison_stats = None
    today = datetime.utcnow().date()
    can_compare = (current_user.last_comparison_date != today) or (current_user.ai_tier != 'ai_free')
    comparisons_remaining = 0 if current_user.last_comparison_date == today and current_user.ai_tier == 'ai_free' else 1
    if current_user.ai_tier != 'ai_free':
        comparisons_remaining = -1  # unlimited

    return render_template_string(
        BASE_TEMPLATE,
        title="AI Provider Settings",
        content=render_template_string(
            BYOAI_SETTINGS_CONTENT,
            providers=providers,
            comparison_stats=comparison_stats,
            can_compare=can_compare,
            comparisons_remaining=comparisons_remaining,
        ),
        current_user=current_user
    )


@app.route("/api/portal/ai/providers/test", methods=["POST"])
@login_required
def api_ai_test_provider():
    """Test an AI provider API key before saving."""
    from ai_search import phoenix_ai
    data = request.get_json() or {}
    provider = data.get("provider", "").strip()
    api_key = data.get("api_key", "").strip()

    if not provider or not api_key:
        return jsonify({"error": "Provider and API key required"}), 400

    # Quick test: try a minimal API call
    try:
        result = phoenix_ai._call_provider(
            provider,
            [{"role": "system", "content": "Reply with OK"}, {"role": "user", "content": "Test"}],
            api_key=api_key,
            provider_info=phoenix_ai.providers.get(provider, {})
        )
        if result and result.get("response"):
            return jsonify({"ok": True, "message": f"{provider} is working correctly"})
        return jsonify({"error": "Provider returned empty response"}), 400
    except Exception as e:
        return jsonify({"error": f"Test failed: {str(e)}"}), 400


@app.route("/api/v1/ai/compare", methods=["POST"])
@login_required
def api_ai_compare():
    """Run PhoenixAI comparison against BYOAI/user search results."""
    from strategy_learner import strategy_learner

    data = request.get_json() or {}
    byoai_results = data.get("byoai_results", [])
    query_params = data.get("query_params", {})

    if not byoai_results and not query_params:
        return jsonify({"error": "Results or query params required"}), 400

    # Check daily comparison quota
    today = datetime.utcnow().date()
    if current_user.ai_tier == 'ai_free' and current_user.last_comparison_date == today:
        return jsonify({"error": "Daily comparison limit reached. Upgrade to PhoenixAI for unlimited comparisons."}), 429

    # Run comparison
    result = strategy_learner.run_comparison(
        user_id=current_user.id,
        byoai_results=byoai_results,
        query_params=query_params,
    )

    # Update comparison date
    current_user.last_comparison_date = today
    db.session.commit()

    return jsonify(result)


@app.route("/api/v1/ai/compare/status")
@login_required
def api_ai_compare_status():
    """Check daily comparison quota."""
    today = datetime.utcnow().date()
    if current_user.ai_tier == 'ai_free':
        used = 1 if current_user.last_comparison_date == today else 0
        return jsonify({"remaining": 1 - used, "limit": 1, "tier": current_user.ai_tier})
    return jsonify({"remaining": -1, "limit": -1, "tier": current_user.ai_tier})


@app.route("/admin/strategy")
@admin_required
def admin_strategy():
    """Admin strategy learner dashboard."""
    try:
        from strategy_learner import strategy_learner
        stats = strategy_learner.get_learner_stats()
    except Exception as e:
        logger.error(f"Strategy stats error: {e}")
        stats = {"error": str(e)}

    return render_template_string(
        BASE_TEMPLATE,
        title="Strategy Learner",
        content=render_template_string(ADMIN_STRATEGY_CONTENT, stats=stats),
        current_user=current_user
    )


@app.route("/admin/strategy/aggregate", methods=["POST"])
@admin_required
def admin_strategy_aggregate():
    """Manually trigger strategy insight aggregation."""
    try:
        from strategy_learner import strategy_learner
        result = strategy_learner.aggregate_insights()
        flash(f"Aggregation complete: {result.get('insights_created', 0)} created, {result.get('insights_updated', 0)} updated", "success")
    except Exception as e:
        flash(f"Aggregation failed: {e}", "error")
    return redirect(url_for("admin_strategy"))


# --- Data Marketplace Admin Dashboard (Build #74) ---

DATA_MARKETPLACE_ADMIN_CONTENT = """
<div style="max-width:1200px;margin:0 auto;">
    <div style="margin-bottom:30px;display:flex;justify-content:space-between;align-items:center;">
        <div>
            <h1 style="color:#fff;margin:0 0 8px 0;font-size:28px;">Data Marketplace</h1>
            <p style="color:#aaa;margin:0;font-size:15px;">Enterprise data products revenue &amp; usage dashboard</p>
        </div>
        <div style="display:flex;gap:12px;">
            <a href="/api/v1/data/catalog" target="_blank" style="padding:10px 20px;background:rgba(0,212,255,0.15);color:#00d4ff;border:1px solid rgba(0,212,255,0.3);border-radius:8px;text-decoration:none;font-size:14px;">View Catalog API</a>
        </div>
    </div>

    <!-- Revenue Overview -->
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:24px;">
        <div style="background:#16213e;border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:20px;text-align:center;">
            <div style="color:#aaa;font-size:13px;margin-bottom:8px;">Monthly Revenue</div>
            <div style="color:#00e676;font-size:28px;font-weight:700;">${{ stats.monthly_revenue|default('0') }}</div>
        </div>
        <div style="background:#16213e;border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:20px;text-align:center;">
            <div style="color:#aaa;font-size:13px;margin-bottom:8px;">Active Subscribers</div>
            <div style="color:#00d4ff;font-size:28px;font-weight:700;">{{ stats.active_subscribers|default(0) }}</div>
        </div>
        <div style="background:#16213e;border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:20px;text-align:center;">
            <div style="color:#aaa;font-size:13px;margin-bottom:8px;">Queries Today</div>
            <div style="color:#fff;font-size:28px;font-weight:700;">{{ stats.queries_today|default(0) }}</div>
        </div>
        <div style="background:#16213e;border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:20px;text-align:center;">
            <div style="color:#aaa;font-size:13px;margin-bottom:8px;">Data Products</div>
            <div style="color:#ff9100;font-size:28px;font-weight:700;">{{ stats.total_products|default(22) }}</div>
        </div>
    </div>

    <!-- Tier Breakdown -->
    <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:16px;margin-bottom:24px;">
        <div style="background:#16213e;border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:24px;">
            <h2 style="color:#fff;margin:0 0 16px 0;font-size:18px;">Subscribers by Tier</h2>
            {% for tier_name, tier_count in stats.get('tier_breakdown', {}).items() %}
            <div style="display:flex;justify-content:space-between;padding:10px 0;border-bottom:1px solid rgba(255,255,255,0.05);">
                <span style="color:#ccc;font-size:14px;">{{ tier_name }}</span>
                <span style="color:#00d4ff;font-weight:600;">{{ tier_count }}</span>
            </div>
            {% endfor %}
            {% if not stats.get('tier_breakdown') %}
            <p style="color:#666;font-size:14px;">No subscribers yet</p>
            {% endif %}
        </div>
        <div style="background:#16213e;border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:24px;">
            <h2 style="color:#fff;margin:0 0 16px 0;font-size:18px;">Top Products (by queries)</h2>
            {% for prod in stats.get('top_products', [])[:8] %}
            <div style="display:flex;justify-content:space-between;padding:10px 0;border-bottom:1px solid rgba(255,255,255,0.05);">
                <span style="color:#ccc;font-size:14px;">{{ prod.product_id }}</span>
                <span style="color:#00e676;font-weight:600;">{{ prod.query_count }}</span>
            </div>
            {% endfor %}
            {% if not stats.get('top_products') %}
            <p style="color:#666;font-size:14px;">No queries yet</p>
            {% endif %}
        </div>
    </div>

    <!-- Recent Activity -->
    <div style="background:#16213e;border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:24px;margin-bottom:24px;">
        <h2 style="color:#fff;margin:0 0 16px 0;font-size:18px;">Recent API Activity</h2>
        <div style="overflow-x:auto;">
            <table style="width:100%;border-collapse:collapse;">
                <thead>
                    <tr style="border-bottom:1px solid rgba(255,255,255,0.1);">
                        <th style="text-align:left;padding:10px;color:#aaa;font-size:13px;">Time</th>
                        <th style="text-align:left;padding:10px;color:#aaa;font-size:13px;">Account</th>
                        <th style="text-align:left;padding:10px;color:#aaa;font-size:13px;">Product</th>
                        <th style="text-align:left;padding:10px;color:#aaa;font-size:13px;">Type</th>
                        <th style="text-align:right;padding:10px;color:#aaa;font-size:13px;">Records</th>
                        <th style="text-align:right;padding:10px;color:#aaa;font-size:13px;">Credits</th>
                    </tr>
                </thead>
                <tbody>
                    {% for record in stats.get('recent_activity', [])[:20] %}
                    <tr style="border-bottom:1px solid rgba(255,255,255,0.05);">
                        <td style="padding:10px;color:#888;font-size:13px;">{{ record.created_at }}</td>
                        <td style="padding:10px;color:#ccc;font-size:13px;">{{ record.account_id }}</td>
                        <td style="padding:10px;color:#00d4ff;font-size:13px;">{{ record.product_id }}</td>
                        <td style="padding:10px;color:#ccc;font-size:13px;">{{ record.query_type }}</td>
                        <td style="padding:10px;color:#fff;font-size:13px;text-align:right;">{{ record.records_returned }}</td>
                        <td style="padding:10px;color:#ff9100;font-size:13px;text-align:right;">{{ record.credits_consumed }}</td>
                    </tr>
                    {% endfor %}
                    {% if not stats.get('recent_activity') %}
                    <tr><td colspan="6" style="padding:20px;color:#666;text-align:center;font-size:14px;">No activity yet</td></tr>
                    {% endif %}
                </tbody>
            </table>
        </div>
    </div>

    <!-- Active Webhooks & Exports -->
    <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:16px;">
        <div style="background:#16213e;border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:24px;">
            <h2 style="color:#fff;margin:0 0 16px 0;font-size:18px;">Active Webhooks</h2>
            <div style="color:#00d4ff;font-size:32px;font-weight:700;">{{ stats.active_webhooks|default(0) }}</div>
            <div style="color:#aaa;font-size:13px;margin-top:4px;">{{ stats.total_deliveries|default(0) }} total deliveries</div>
        </div>
        <div style="background:#16213e;border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:24px;">
            <h2 style="color:#fff;margin:0 0 16px 0;font-size:18px;">Pending Exports</h2>
            <div style="color:#ff9100;font-size:32px;font-weight:700;">{{ stats.pending_exports|default(0) }}</div>
            <div style="color:#aaa;font-size:13px;margin-top:4px;">{{ stats.completed_exports|default(0) }} completed</div>
        </div>
    </div>
</div>
"""


# --- Node Consent Economy Admin Dashboard (Build #75) ---

NODE_CONSENT_ADMIN_CONTENT = ADMIN_NAV + """
<div style="max-width:1200px;margin:0 auto;">
    <h1 style="color:#fff;margin:0 0 8px 0;font-size:28px;">Node Consent Economy</h1>
    <p style="color:#aaa;margin:0 0 24px 0;font-size:15px;">Performance-based tier system, consent management, and fee allocation overview.</p>

    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-bottom:24px;">
        <div style="background:#16213e;border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:24px;">
            <h2 style="color:#fff;margin:0 0 16px 0;font-size:18px;">Total Nodes</h2>
            <div style="color:#00e676;font-size:32px;font-weight:700;">{{ stats.total_nodes|default(0) }}</div>
        </div>
        <div style="background:#16213e;border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:24px;">
            <h2 style="color:#fff;margin:0 0 16px 0;font-size:18px;">Active Nodes</h2>
            <div style="color:#00bcd4;font-size:32px;font-weight:700;">{{ stats.active_nodes|default(0) }}</div>
        </div>
        <div style="background:#16213e;border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:24px;">
            <h2 style="color:#fff;margin:0 0 16px 0;font-size:18px;">Avg Tier Score</h2>
            <div style="color:#ff9100;font-size:32px;font-weight:700;">{{ "%.1f"|format(stats.avg_tier_score|default(0)) }}</div>
        </div>
        <div style="background:#16213e;border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:24px;">
            <h2 style="color:#fff;margin:0 0 16px 0;font-size:18px;">Total Allocated</h2>
            <div style="color:#ff6b35;font-size:32px;font-weight:700;">${{ "%.2f"|format(stats.total_fees_allocated|default(0)) }}</div>
        </div>
    </div>

    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-bottom:24px;">
        {% for tier_name, tier_count in (stats.tier_distribution or {}).items() %}
        <div style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:8px;padding:16px;text-align:center;">
            <div style="color:#aaa;font-size:12px;text-transform:uppercase;margin-bottom:4px;">{{ tier_name }}</div>
            <div style="color:#fff;font-size:24px;font-weight:700;">{{ tier_count }}</div>
        </div>
        {% endfor %}
    </div>

    <div style="background:#16213e;border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:24px;margin-bottom:24px;">
        <h2 style="color:#fff;margin:0 0 16px 0;font-size:18px;">Consent Categories Opted-In</h2>
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:8px;">
            {% for cat, count in (stats.consent_categories or {}).items() %}
            <div style="display:flex;justify-content:space-between;padding:8px 12px;background:rgba(255,255,255,0.04);border-radius:6px;">
                <span style="color:#aaa;font-size:13px;">{{ cat }}</span>
                <span style="color:#fff;font-weight:600;">{{ count }}</span>
            </div>
            {% endfor %}
        </div>
    </div>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
        <div style="background:#16213e;border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:24px;">
            <h2 style="color:#fff;margin:0 0 16px 0;font-size:18px;">Revenue Allocation</h2>
            <div style="display:flex;flex-direction:column;gap:8px;">
                <div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid rgba(255,255,255,0.06);">
                    <span style="color:#aaa;">Total Allocations</span><span style="color:#fff;font-weight:600;">{{ stats.total_allocations|default(0) }}</span>
                </div>
                <div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid rgba(255,255,255,0.06);">
                    <span style="color:#aaa;">Node Payouts</span><span style="color:#00e676;font-weight:600;">${{ "%.2f"|format(stats.total_node_payouts|default(0)) }}</span>
                </div>
                <div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid rgba(255,255,255,0.06);">
                    <span style="color:#aaa;">Referral Payouts</span><span style="color:#00bcd4;font-weight:600;">${{ "%.2f"|format(stats.total_referral_payouts|default(0)) }}</span>
                </div>
                <div style="display:flex;justify-content:space-between;padding:8px 0;">
                    <span style="color:#aaa;">Platform Profit</span><span style="color:#ff6b35;font-weight:600;">${{ "%.2f"|format(stats.total_platform_profit|default(0)) }}</span>
                </div>
            </div>
        </div>
        <div style="background:#16213e;border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:24px;">
            <h2 style="color:#fff;margin:0 0 16px 0;font-size:18px;">Referrals</h2>
            <div style="display:flex;flex-direction:column;gap:8px;">
                <div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid rgba(255,255,255,0.06);">
                    <span style="color:#aaa;">Total Referrals</span><span style="color:#fff;font-weight:600;">{{ stats.total_referrals|default(0) }}</span>
                </div>
                <div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid rgba(255,255,255,0.06);">
                    <span style="color:#aaa;">Active</span><span style="color:#00e676;font-weight:600;">{{ stats.active_referrals|default(0) }}</span>
                </div>
                <div style="display:flex;justify-content:space-between;padding:8px 0;">
                    <span style="color:#aaa;">Bonuses Paid</span><span style="color:#ff9100;font-weight:600;">${{ "%.2f"|format(stats.total_referral_bonuses|default(0)) }}</span>
                </div>
            </div>
        </div>
    </div>
</div>
"""


@app.route("/admin/node-consent")
@admin_required
def admin_node_consent():
    """Node consent economy admin dashboard."""
    try:
        from node_consent_economy import node_consent_economy
        stats = node_consent_economy.get_consent_economy_dashboard()
    except Exception as e:
        logger.error(f"Node consent dashboard error: {e}")
        stats = {"error": str(e)}

    return render_template_string(
        BASE_TEMPLATE,
        title="Node Consent Economy - Admin",
        content=render_template_string(NODE_CONSENT_ADMIN_CONTENT, stats=stats),
        current_user=current_user
    )


@app.route("/admin/data-marketplace")
@admin_required
def admin_data_marketplace():
    """Data marketplace admin dashboard."""
    try:
        from data_marketplace import data_marketplace
        stats = data_marketplace.get_admin_dashboard_data()
    except Exception as e:
        stats = {"error": str(e)}

    return render_template_string(
        ADMIN_SHELL.replace("{{CONTENT}}", DATA_MARKETPLACE_ADMIN_CONTENT),
        stats=stats,
    )


# --- Arbitrage Market Tool Admin (Build #76) ---

@app.route("/admin/arbitrage")
@admin_required
def admin_arbitrage():
    """Universal arbitrage market tool admin dashboard."""
    from datetime import datetime
    stats = {}
    try:
        stats['flight_deals_active'] = Deal.query.filter_by(is_active=True).count()
        # Hotel, cruise, rental, package deal models removed (Build #89)
        stats['hotel_deals_active'] = 0
        stats['hotel_deals_total'] = 0
        stats['cruise_deals_active'] = 0
        stats['cruise_deals_total'] = 0
        stats['rental_deals_active'] = 0
        stats['rental_deals_total'] = 0
        stats['package_deals_active'] = 0
        stats['package_deals_total'] = 0
        stats['top_hotel_deals'] = []
        stats['top_cruise_deals'] = []
        stats['top_rental_deals'] = []

    except Exception as e:
        logger.error(f"Arbitrage admin dashboard error: {e}")
        stats['error'] = str(e)

    content = f"""
    <div style="max-width:1200px;margin:0 auto;">
        <h1 style="color:#fff;margin-bottom:24px;">Universal Arbitrage Market Tool</h1>
        <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:16px;margin-bottom:32px;">
            <div style="background:#1e1e2e;padding:20px;border-radius:12px;text-align:center;">
                <div style="font-size:28px;font-weight:700;color:#1a73e8;">{stats.get('flight_deals_active', 0)}</div>
                <div style="color:#888;font-size:13px;">Flight Deals</div>
            </div>
            <div style="background:#1e1e2e;padding:20px;border-radius:12px;text-align:center;">
                <div style="font-size:28px;font-weight:700;color:#00e676;">{stats.get('hotel_deals_active', 0)}</div>
                <div style="color:#888;font-size:13px;">Hotel Deals</div>
            </div>
            <div style="background:#1e1e2e;padding:20px;border-radius:12px;text-align:center;">
                <div style="font-size:28px;font-weight:700;color:#ff9800;">{stats.get('cruise_deals_active', 0)}</div>
                <div style="color:#888;font-size:13px;">Cruise Deals</div>
            </div>
            <div style="background:#1e1e2e;padding:20px;border-radius:12px;text-align:center;">
                <div style="font-size:28px;font-weight:700;color:#e040fb;">{stats.get('rental_deals_active', 0)}</div>
                <div style="color:#888;font-size:13px;">Rental Deals</div>
            </div>
            <div style="background:#1e1e2e;padding:20px;border-radius:12px;text-align:center;">
                <div style="font-size:28px;font-weight:700;color:#fff;">{stats.get('package_deals_active', 0)}</div>
                <div style="color:#888;font-size:13px;">Packages</div>
            </div>
        </div>
        <div style="background:#1e1e2e;padding:20px;border-radius:12px;">
            <h3 style="color:#fff;margin:0 0 16px;">Deal Scanner</h3>
            <form method="POST" action="/admin/arbitrage/scan">
                <button type="submit" name="vertical" value="all" style="background:#1a73e8;color:#fff;border:none;padding:10px 24px;border-radius:8px;cursor:pointer;margin-right:8px;">Scan All Verticals</button>
                <button type="submit" name="vertical" value="hotels" style="background:#00e676;color:#000;border:none;padding:10px 24px;border-radius:8px;cursor:pointer;margin-right:8px;">Scan Hotels</button>
                <button type="submit" name="vertical" value="cruises" style="background:#ff9800;color:#000;border:none;padding:10px 24px;border-radius:8px;cursor:pointer;margin-right:8px;">Scan Cruises</button>
                <button type="submit" name="vertical" value="rentals" style="background:#e040fb;color:#000;border:none;padding:10px 24px;border-radius:8px;cursor:pointer;">Scan Rentals</button>
            </form>
        </div>
    </div>
    """
    return render_template_string(BASE_TEMPLATE, title="Arbitrage Market Tool - Admin", content=content, current_user=current_user)


@app.route("/admin/arbitrage/scan", methods=["POST"])
@admin_required
def admin_arbitrage_scan():
    """Trigger a deal scan for a specific vertical."""
    vertical = request.form.get("vertical", "all")
    try:
        from arbitrage_deal_generator import ArbitrageDealGenerator
        generator = ArbitrageDealGenerator()
        if vertical == "hotels":
            stats = generator.scan_hotels(max_destinations=3)
        elif vertical == "cruises":
            stats = generator.scan_cruises(max_configs=2)
        elif vertical == "rentals":
            stats = generator.scan_rentals(max_locations=3)
        else:
            stats = generator.run_full_scan(max_per_vertical=3)
        flash(f"Scan complete: {json.dumps(stats, default=str)[:200]}", "success")
    except Exception as e:
        flash(f"Scan failed: {e}", "error")
    return redirect("/admin/arbitrage")


# --- Harvest Scheduler Admin (Build #79) ---

@app.route("/api/admin/harvest/status")
@admin_required
def admin_harvest_status():
    """Get autonomous harvest performance summary."""
    hours_back = request.args.get("hours_back", 24, type=int)
    try:
        from harvest_scheduler import harvest_scheduler
        performance = harvest_scheduler.get_harvest_performance(hours_back=hours_back)
        return jsonify(performance)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/harvest/gaps")
@admin_required
def admin_harvest_gaps():
    """Get current observation gaps across pricing zones."""
    hours_back = request.args.get("hours_back", 24, type=int)
    try:
        from pricing_zones import zone_engine
        gaps = zone_engine.get_observation_gaps(hours_back=hours_back)
        return jsonify({"gaps": gaps, "total": len(gaps)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/harvest/budgets")
@admin_required
def admin_harvest_budgets():
    """Get harvest budget utilization."""
    try:
        from harvest_scheduler import harvest_scheduler
        utilization = harvest_scheduler.get_budget_utilization()
        return jsonify(utilization)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/harvest/trigger", methods=["POST"])
@admin_required
def admin_harvest_trigger():
    """Manually trigger a harvest cycle."""
    try:
        from harvest_scheduler import harvest_scheduler
        result = harvest_scheduler.run_harvest_cycle()
        return jsonify({
            "cycle_id": result.cycle_id,
            "dispatched": result.tasks_dispatched,
            "gaps": result.gaps_identified,
            "standing_orders": result.standing_orders_processed,
            "duration_ms": result.duration_ms,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/standing-orders", methods=["GET"])
@admin_required
def admin_list_standing_orders():
    """List all standing orders."""
    try:
        from models import StandingOrder
        orders = StandingOrder.query.order_by(StandingOrder.created_at.desc()).all()
        return jsonify({"orders": [o.to_dict() for o in orders], "total": len(orders)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/standing-orders", methods=["POST"])
@admin_required
def admin_create_standing_order():
    """Create a new standing order."""
    data = request.get_json(silent=True) or {}
    try:
        from harvest_scheduler import harvest_scheduler
        result = harvest_scheduler.create_standing_order(
            account_id=data.get("account_id", 0),
            vertical=data.get("vertical", "flight"),
            filters=data.get("filters", {}),
            zone_ids=data.get("zone_ids", []),
            refresh_interval_hours=data.get("refresh_interval_hours", 6),
            max_tasks_per_cycle=data.get("max_tasks_per_cycle", 10),
            price_per_observation_usd=data.get("price_per_observation_usd", 0.01),
            max_spend_per_day_usd=data.get("max_spend_per_day_usd", 50.0),
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/standing-orders/<order_id>", methods=["GET"])
@admin_required
def admin_get_standing_order(order_id):
    """Get a specific standing order."""
    try:
        from harvest_scheduler import harvest_scheduler
        result = harvest_scheduler.get_standing_order_status(order_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/standing-orders/<order_id>/pause", methods=["POST"])
@admin_required
def admin_pause_standing_order(order_id):
    """Pause a standing order."""
    try:
        from harvest_scheduler import harvest_scheduler
        success = harvest_scheduler.pause_standing_order(order_id)
        return jsonify({"paused": success})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/standing-orders/<order_id>/resume", methods=["POST"])
@admin_required
def admin_resume_standing_order(order_id):
    """Resume a paused standing order."""
    try:
        from harvest_scheduler import harvest_scheduler
        success = harvest_scheduler.resume_standing_order(order_id)
        return jsonify({"resumed": success})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ===================================================================
# Build #80 — Strategy Learning Admin Routes
# ===================================================================

@app.route("/api/admin/strategy/insights")
@admin_required
def admin_strategy_insights():
    """Get active strategy insights summary."""
    try:
        from strategy_learner import strategy_learner
        stats = strategy_learner.get_learner_stats()
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/strategy/effectiveness")
@admin_required
def admin_strategy_effectiveness():
    """Get strategy effectiveness comparison (enhanced vs baseline)."""
    try:
        from strategy_learner import strategy_learner
        hours = request.args.get("hours_back", 168, type=int)
        result = strategy_learner.evaluate_strategy_effectiveness(hours_back=hours)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/strategy/aggregate", methods=["POST"])
@admin_required
def api_admin_strategy_aggregate():
    """Manually trigger strategy insight aggregation (API endpoint)."""
    try:
        from strategy_learner import strategy_learner
        result = strategy_learner.aggregate_insights(
            min_observations=5, lookback_hours=168
        )
        eff = strategy_learner.evaluate_strategy_effectiveness(hours_back=168)
        return jsonify({**result, "effectiveness": eff})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# --- Arbitrage Search Page (Build #76) ---

@app.route("/arbitrage")
def arbitrage_search_page():
    """Universal arbitrage search page."""
    return render_template_string(open("templates/arbitrage_search.html").read() if os.path.exists("templates/arbitrage_search.html") else "<h1>Arbitrage Search</h1><p>Template not found</p>")


# --- MAIN ---

if __name__ == "__main__":
    # Structured logging (must be first — configures root logger + request context)
    from logging_config import init_logging
    init_logging(app)

    # Monitoring: Sentry + Prometheus /metrics + request tracking
    from monitoring import init_monitoring
    init_monitoring(app)

    print("="*60)
    print("PHOENIX Server")
    print("="*60)
    print(f"URL: http://localhost:{SERVER_PORT}/")
    print("="*60)

    get_xrp_price()

    # Start XRPL ledger monitor (background thread — watches escrow events)
    from xrpl_monitor import ledger_monitor
    ledger_monitor.flask_app = app
    ledger_monitor.start()

    app.run(host=SERVER_HOST, port=SERVER_PORT, debug=True)
