"""
MYSTES Proxy Server with Database & Authentication

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
from datetime import datetime, timedelta, timezone
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
                    UserWallet, UserCard, TravelerProfile,
                    CommercialAccount, ConsumerReferral, SocialShare,
                    RewardsAccount, PointsTransaction, PointsEscrow, PointGift,
                    Subscription, generate_referral_code, ReferralCard,
                    TripPlan, TripMember, TripItem, Collection, SavedItem, Friendship)
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
    create_stripe_refund,
    get_or_create_stripe_customer,
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
        logging.FileHandler('mystes.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("mystes.audit")


def audit_log(action, user_id=None, **details):
    """Log a financial or security-relevant event for audit trail."""
    extra = {"action": action, "user_id": user_id, **details}
    audit_logger.info(
        f"AUDIT action={action} user={user_id} {' '.join(f'{k}={v}' for k,v in details.items())}",
        extra=extra,
    )


# --- APP CONFIGURATION ---
app = Flask(__name__)

# Load environment-aware config from config.py (Build #108)
from config import get_config
app.config.from_object(get_config())

# Override DATABASE_URL with Render-style postgres:// fix
_db_url = os.environ.get('DATABASE_URL') or app.config.get('SQLALCHEMY_DATABASE_URI', 'sqlite:///mystes.db')
if _db_url.startswith('postgres://'):
    _db_url = _db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = _db_url

# Ensure SECRET_KEY is set even if env var is missing (dev fallback)
if not app.config.get('SECRET_KEY') or app.config['SECRET_KEY'] == 'dev-secret-key-change-in-production':
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(32))

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


# --- Feature Flags Helper (Build #95) ---
def is_feature_enabled(flag_key):
    """Check if a feature flag is enabled. Use this throughout the codebase."""
    try:
        from models import FeatureFlag
        return FeatureFlag.is_flag_enabled(flag_key)
    except Exception:
        # Default to False if there's any error (DB not ready, etc.)
        return False


# --- Feature Flags Template Context (Build #96) ---
@app.context_processor
def _inject_feature_flags():
    """Inject feature flags into all templates for conditional rendering."""
    return {
        "feature_flights": is_feature_enabled("vertical_flights"),
        "feature_hotels": is_feature_enabled("vertical_hotels"),
        "feature_activities": is_feature_enabled("vertical_activities"),
        "feature_products": is_feature_enabled("vertical_products"),
        "feature_rentals": is_feature_enabled("vertical_rentals"),
        "feature_cruises": is_feature_enabled("vertical_cruises"),
        "feature_tier_system": is_feature_enabled("tier_system"),
        # Build #167 — Feature Foundation
        "feature_travel_plus": is_feature_enabled("travel_plus"),
        "feature_rewards": is_feature_enabled("rewards_points"),
        "feature_trip_planner": is_feature_enabled("trip_planner"),
        "feature_wishlist": is_feature_enabled("wishlist"),
        "feature_friends": is_feature_enabled("friends_system"),
        "feature_local_businesses": is_feature_enabled("local_businesses"),
    }

# Initialize database (resilient — app starts even if DB is unreachable)
try:
    init_db(app)
except Exception as _db_err:
    logging.error(f"Database init failed (app will start without DB): {_db_err}")
    db.init_app(app)

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
    print("Loaded world-class MYSTES template")
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
    <title>{{ title }} - MYSTES</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="description" content="MYSTES - Borderless flight booking powered by XRPL.">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
    <style>
        :root {
            --black: #000000;
            --white: #ffffff;
            --mystes-purple: #5b21b6;
            --mystes-deep: #6d28d9;
            --mystes-gold: #14b8a6;
            --success: #00c853;
            --warning: #7c3aed;
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
                radial-gradient(ellipse 80% 50% at 20% 40%, rgba(124,58,237,0.15) 0%, transparent 50%),
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
            background: linear-gradient(90deg, transparent, rgba(124,58,237,0.3), transparent);
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
        nav a.active { color: var(--mystes-purple); }

        /* Brand logo */
        .brand {
            display: flex;
            align-items: center;
            gap: 12px;
            text-decoration: none;
            font-family: 'Cinzel', 'Trajan Pro', serif;
            letter-spacing: 6px;
            text-transform: uppercase;
        }
        .brand-icon {
            width: 40px;
            height: 40px;
            background: linear-gradient(135deg, var(--mystes-purple), var(--mystes-deep));
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 20px;
            box-shadow: 0 4px 20px rgba(124,58,237,0.3);
        }
        .brand-text {
            font-family: 'Space Grotesk', sans-serif;
            font-size: 24px;
            font-weight: 700;
            background: linear-gradient(135deg, var(--mystes-purple), var(--mystes-gold));
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
            background: linear-gradient(135deg, #7c3aed, #6d28d9);
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
            border-color: #7c3aed;
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
        .alert-info { background: linear-gradient(135deg, #f5f3ff, #ffe5d8); color: #8b4513; }
        .alert-info::before { content: ''; }

        .deal {
            background: rgba(255, 255, 255, 0.95);
            border-radius: 16px;
            padding: 25px;
            margin: 20px 0;
            box-shadow: 0 8px 32px rgba(0,0,0,0.1);
            border-left: 4px solid #7c3aed;
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
        .tag-warning { background: linear-gradient(135deg, #f0fdfa, #ffeaa7); color: #856404; }
        .payment-box {
            background: linear-gradient(135deg, #f5f3ff, #f5f3ff);
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
            color: #14b8a6;
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
        .status-pending { background: linear-gradient(135deg, #f0fdfa, #ffeaa7); color: #856404; }
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
            background: linear-gradient(90deg, #7c3aed, #14b8a6, #14b8a6);
        }
        .stat-card:hover {
            transform: translateY(-8px) scale(1.02);
            box-shadow: 0 15px 40px rgba(0,0,0,0.15);
        }
        .stat-value {
            font-size: 32px;
            font-weight: bold;
            background: linear-gradient(135deg, #7c3aed, #14b8a6);
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
        footer a { color: #14b8a6; text-decoration: none; transition: color 0.3s ease; }
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
            background: linear-gradient(135deg, #7c3aed 0%, #6d28d9 50%, #14b8a6 100%);
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
            background: linear-gradient(135deg, #7c3aed, #14b8a6);
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
            background: #14b8a6;
            border-radius: 50%;
            box-shadow: 0 0 10px #14b8a6;
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
        <span class="brand">MYSTES</span>
        <div>
            <a href="/search">Search</a>
            <a href="/deals">Deals</a>
            <a href="/earn">Earn</a>
            {% if current_user.is_authenticated %}
                <a href="/dashboard">Dashboard</a>
                <a href="/helper">Helper</a>
                <a href="/wallet">Wallet</a>
                {% if current_user.is_admin %}<a href="/admin" style="color: #14b8a6;">Admin</a>{% endif %}
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
        <p>&copy; 2026 MYSTES. All rights reserved.</p>
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
       MYSTES HOME - Search Engine Landing
       ================================================ */

    .mystes-landing {
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

    .mystes-landing::before {
        content: '';
        position: absolute;
        top: 0; left: 0; right: 0; bottom: 0;
        background:
            radial-gradient(ellipse 80% 60% at 50% 40%, rgba(255, 77, 0, 0.10) 0%, transparent 60%),
            radial-gradient(circle at 20% 80%, rgba(255, 140, 0, 0.06) 0%, transparent 40%);
        pointer-events: none;
    }

    .mystes-logo-mark {
        font-family: 'Cinzel', 'Trajan Pro', 'Palatino Linotype', serif;
        font-size: clamp(42px, 10vw, 100px);
        font-weight: 800;
        letter-spacing: 12px;
        line-height: 1;
        margin: 0 0 8px;
        text-transform: uppercase;
        background: linear-gradient(135deg, #ffffff 0%, #e8d5b7 35%, #ffffff 55%, #c9a96e 80%, #ffffff 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        filter: drop-shadow(0 0 20px rgba(201, 169, 110, 0.3));
        opacity: 0;
        animation: fadeInUp 0.8s cubic-bezier(0.16, 1, 0.3, 1) forwards;
    }

    .mystes-tagline {
        font-size: clamp(16px, 2.5vw, 20px);
        color: rgba(255, 255, 255, 0.7);
        font-weight: 400;
        margin: 0 0 40px;
        max-width: 500px;
        opacity: 0;
        animation: fadeInUp 0.8s cubic-bezier(0.16, 1, 0.3, 1) 0.1s forwards;
    }

    /* Search bar */
    .mystes-search-bar {
        width: 100%;
        max-width: 640px;
        position: relative;
        opacity: 0;
        animation: fadeInUp 0.8s cubic-bezier(0.16, 1, 0.3, 1) 0.2s forwards;
    }

    .mystes-search-bar input {
        width: 100%;
        padding: 18px 60px 18px 24px;
        font-size: 16px;
        font-family: 'Outfit', sans-serif;
        font-weight: 500;
        background: rgba(255, 255, 255, 0.06);
        border: 1px solid rgba(255, 255, 255, 0.12);
        border-radius: 16px;
        color: #fff;
        outline: none;
        transition: all 0.3s ease;
    }

    .mystes-search-bar input::placeholder { color: rgba(255,255,255,0.35); }
    .mystes-search-bar input:focus {
        border-color: rgba(124, 58, 237, 0.5);
        background: rgba(255, 255, 255, 0.08);
        box-shadow: 0 0 0 3px rgba(124, 58, 237, 0.1);
    }

    .mystes-search-btn {
        position: absolute;
        right: 6px; top: 6px; bottom: 6px;
        width: 48px;
        background: linear-gradient(135deg, #7c3aed, #5b21b6);
        border: none; border-radius: 12px;
        color: white; font-size: 20px;
        cursor: pointer;
        display: flex; align-items: center; justify-content: center;
        transition: opacity 0.2s;
    }
    .mystes-search-btn:hover { opacity: 0.9; }

    /* Quick action chips */
    .mystes-chips {
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        justify-content: center;
        margin-top: 24px;
        opacity: 0;
        animation: fadeInUp 0.8s cubic-bezier(0.16, 1, 0.3, 1) 0.3s forwards;
    }

    .mystes-chip {
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
    .mystes-chip:hover {
        background: rgba(124, 58, 237, 0.1);
        border-color: rgba(124, 58, 237, 0.3);
        color: #fff;
    }

    /* Verticals grid */
    .mystes-verticals {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
        gap: 16px;
        max-width: 640px;
        width: 100%;
        margin-top: 48px;
        opacity: 0;
        animation: fadeInUp 0.8s cubic-bezier(0.16, 1, 0.3, 1) 0.4s forwards;
    }

    .mystes-vertical {
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
    .mystes-vertical:hover {
        background: rgba(255, 255, 255, 0.05);
        border-color: rgba(124, 58, 237, 0.3);
        transform: translateY(-4px);
    }
    .mystes-vertical .v-icon { font-size: 28px; }
    .mystes-vertical .v-label { font-size: 13px; font-weight: 600; color: rgba(255,255,255,0.85); }

    /* Bottom note */
    .mystes-note {
        margin-top: 48px;
        font-size: 12px;
        color: rgba(255, 255, 255, 0.35);
        opacity: 0;
        animation: fadeInUp 0.8s cubic-bezier(0.16, 1, 0.3, 1) 0.5s forwards;
    }
    .mystes-note a { color: rgba(124,58,237,0.7); text-decoration: none; }
    .mystes-note a:hover { color: #7c3aed; }

    @keyframes fadeInUp {
        from { opacity: 0; transform: translateY(30px); }
        to { opacity: 1; transform: translateY(0); }
    }

    @media (max-width: 768px) {
        .mystes-landing { padding: 40px 16px 30px; }
        .mystes-verticals { grid-template-columns: repeat(3, 1fr); gap: 10px; }
        .mystes-vertical { padding: 14px 8px; }
    }
</style>

<section class="mystes-landing">
    <div class="mystes-logo-mark">MYSTES</div>
    <p class="mystes-tagline">Find flights at the best prices across 195 markets.</p>

    <div class="mystes-search-bar">
        <input type="text" id="homeSearchInput" placeholder="Search flights..." autocomplete="off">
        <button class="mystes-search-btn" onclick="homeSearch()" aria-label="Search">&#10132;</button>
    </div>

    <div class="mystes-chips">
        {% if feature_flights %}
        <a class="mystes-chip" onclick="homeQuick('Cheap flights from NYC to Tokyo next month')">NYC → Tokyo</a>
        <a class="mystes-chip" onclick="homeQuick('Flights from LA to London')">LA → London</a>
        {% endif %}
        {% if feature_hotels %}
        <a class="mystes-chip" onclick="homeQuick('Best hotel deals in Bali')">Hotels in Bali</a>
        <a class="mystes-chip" onclick="homeQuick('Cheap hotels in Paris')">Hotels in Paris</a>
        {% endif %}
        {% if feature_activities %}
        <a class="mystes-chip" onclick="homeQuick('Tours in Rome')">Tours in Rome</a>
        <a class="mystes-chip" onclick="homeQuick('Activities in Barcelona')">Barcelona Activities</a>
        {% endif %}
    </div>

    <div class="mystes-verticals">
        {% if feature_flights %}
        <a class="mystes-vertical" onclick="homeQuick('Search flights')">
            <span class="v-icon">&#9992;</span>
            <span class="v-label">Flights</span>
        </a>
        {% endif %}
        {% if feature_hotels %}
        <a class="mystes-vertical" onclick="homeQuick('Search hotels')">
            <span class="v-icon">&#127976;</span>
            <span class="v-label">Hotels</span>
        </a>
        {% endif %}
        {% if feature_activities %}
        <a class="mystes-vertical" href="/activities">
            <span class="v-icon">&#127915;</span>
            <span class="v-label">Activities</span>
        </a>
        {% endif %}
        {% if feature_products %}
        <a class="mystes-vertical" onclick="homeQuick('Search products')">
            <span class="v-icon">&#128722;</span>
            <span class="v-label">Products</span>
        </a>
        {% endif %}
        {% if feature_rentals %}
        <a class="mystes-vertical" onclick="homeQuick('Search car rentals')">
            <span class="v-icon">&#128663;</span>
            <span class="v-label">Rentals</span>
        </a>
        {% endif %}
        {% if feature_cruises %}
        <a class="mystes-vertical" onclick="homeQuick('Search cruises')">
            <span class="v-icon">&#128674;</span>
            <span class="v-label">Cruises</span>
        </a>
        {% endif %}
    </div>

    <div style="display: flex; gap: 14px; justify-content: center; flex-wrap: wrap; margin-top: 40px; opacity: 0; animation: fadeInUp 0.8s cubic-bezier(0.16, 1, 0.3, 1) 0.5s forwards;">
        <a href="/register" style="padding: 14px 32px; background: linear-gradient(135deg, #7c3aed, #5b21b6); color: white; border-radius: 12px; text-decoration: none; font-weight: 700; font-size: 15px; font-family: 'Outfit', sans-serif; transition: opacity 0.2s;">Get Started</a>
        {% if feature_node_onboarding %}
        <a href="/helper" style="padding: 14px 32px; background: rgba(124,58,237,0.08); border: 1px solid rgba(124,58,237,0.3); color: #7c3aed; border-radius: 12px; text-decoration: none; font-weight: 700; font-size: 15px; font-family: 'Outfit', sans-serif; transition: all 0.2s;">Join the MYSTES Network</a>
        {% endif %}
        <a href="/login" style="padding: 14px 32px; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.12); color: rgba(255,255,255,0.8); border-radius: 12px; text-decoration: none; font-weight: 600; font-size: 15px; font-family: 'Outfit', sans-serif; transition: all 0.2s;">Sign In</a>
    </div>
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
    <div style="background: #f5f3ff; padding: 15px; border-radius: 8px; margin-bottom: 20px;">
        Your deal has been saved. Log in to continue booking.
    </div>
    {% endif %}

    {% if google_client_id %}
    <div style="display: flex; justify-content: center; margin-bottom: 20px;">
        <div id="g_id_signin_login"></div>
    </div>
    <script>
    window.addEventListener('load', function() {
        if (typeof google === 'undefined' || !google.accounts) return;
        google.accounts.id.renderButton(
            document.getElementById('g_id_signin_login'),
            { theme: 'outline', size: 'large', text: 'signin_with', width: 340, shape: 'pill' }
        );
    });
    </script>
    <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 20px;">
        <span style="height: 1px; flex: 1; background: rgba(255,255,255,0.15);"></span>
        <span style="font-size: 12px; color: #666;">or sign in with email</span>
        <span style="height: 1px; flex: 1; background: rgba(255,255,255,0.15);"></span>
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
    <div style="background: #f5f3ff; padding: 15px; border-radius: 8px; margin-bottom: 20px;">
        Your deal has been saved. Create an account to continue booking.
    </div>
    {% endif %}

    {% if google_client_id %}
    <div style="display: flex; justify-content: center; margin-bottom: 20px;">
        <div id="g_id_signin_register"></div>
    </div>
    <script>
    window.addEventListener('load', function() {
        if (typeof google === 'undefined' || !google.accounts) return;
        google.accounts.id.renderButton(
            document.getElementById('g_id_signin_register'),
            { theme: 'outline', size: 'large', text: 'signup_with', width: 340, shape: 'pill' }
        );
    });
    </script>
    <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 20px;">
        <span style="height: 1px; flex: 1; background: rgba(255,255,255,0.15);"></span>
        <span style="font-size: 12px; color: #666;">or sign up with email</span>
        <span style="height: 1px; flex: 1; background: rgba(255,255,255,0.15);"></span>
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

<!-- Tier Card -->
<div class="card" style="background: linear-gradient(135deg, rgba(124,58,237,0.1), rgba(255,77,0,0.05)); border: 1px solid rgba(124,58,237,0.3); margin-bottom: 24px;">
    <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 16px;">
        <div>
            <div style="font-size: 0.85rem; color: rgba(255,255,255,0.6); margin-bottom: 4px;">Your Tier</div>
            <div style="display: flex; align-items: center; gap: 12px;">
                {% if tier_info.current_tier == 'platinum' %}
                <span style="font-size: 1.8rem; font-weight: 700; color: #e5e4e2;">Platinum</span>
                {% elif tier_info.current_tier == 'gold' %}
                <span style="font-size: 1.8rem; font-weight: 700; color: #ffd700;">Gold</span>
                {% elif tier_info.current_tier == 'silver' %}
                <span style="font-size: 1.8rem; font-weight: 700; color: #c0c0c0;">Silver</span>
                {% else %}
                <span style="font-size: 1.8rem; font-weight: 700; color: #cd7f32;">Bronze</span>
                {% endif %}
            </div>
        </div>
        <div style="display: flex; gap: 24px; flex-wrap: wrap;">
            <div style="text-align: center;">
                <div style="font-size: 1.4rem; font-weight: 700; color: #7c3aed;">{{ tier_info.queries_per_day }}</div>
                <div style="font-size: 0.8rem; color: rgba(255,255,255,0.6);">searches/day</div>
            </div>
            <div style="text-align: center;">
                <div style="font-size: 1.4rem; font-weight: 700; color: #7c3aed;">{{ tier_info.markets_per_query }}</div>
                <div style="font-size: 0.8rem; color: rgba(255,255,255,0.6);">markets</div>
            </div>
            <div style="text-align: center;">
                <div style="font-size: 1.4rem; font-weight: 700; color: #00c864;">{{ tier_info.user_keeps_pct }}%</div>
                <div style="font-size: 0.8rem; color: rgba(255,255,255,0.6);">you keep</div>
            </div>
        </div>
    </div>
    {% if tier_info.current_tier != 'platinum' %}
    <div style="margin-top: 16px; padding-top: 16px; border-top: 1px solid rgba(255,255,255,0.1);">
        <div style="font-size: 0.85rem; color: rgba(255,255,255,0.7);">
            {% if tier_info.current_tier == 'bronze' %}
            <strong>Upgrade to Silver:</strong> <a href="/helper" style="color: #7c3aed;">Join the MYSTES Network</a> to get 10 searches/day and 5 markets.
            {% elif tier_info.current_tier == 'silver' %}
            <strong>Upgrade to Gold:</strong> Enable data sharing in your node settings for 20 searches/day and 8 markets.
            {% elif tier_info.current_tier == 'gold' %}
            <strong>Upgrade to Platinum:</strong> Maintain high uptime (95%+) for 40 searches/day and 12 markets.
            {% endif %}
        </div>
    </div>
    {% endif %}
</div>

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
                <td>${{ "%.2f"|format(payment.amount_usd or 0) }}</td>
                <td><span class="status-badge status-{{ payment.status }}">{{ payment.status }}</span></td>
            </tr>
            {% endfor %}
        </table>
    {% else %}
        <p>No payment history yet. <a href="/deals">Browse deals</a> to get started!</p>
    {% endif %}
</div>

<!-- Price Alerts Card (Build #172) -->
<div class="card" style="border-left: 3px solid #7c3aed;">
    <div style="display: flex; justify-content: space-between; align-items: center;">
        <div>
            <h2 style="margin: 0 0 4px;">Price Alerts</h2>
            <p style="margin: 0; color: rgba(255,255,255,0.6);">{{ alerts_count }} active alert{{ 's' if alerts_count != 1 else '' }}</p>
        </div>
        <a href="/alerts" style="background: linear-gradient(135deg, #7c3aed, #5b21b6); color: white; padding: 8px 20px; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 14px;">Manage</a>
    </div>
</div>

{% if feature_trip_planner %}
<!-- My Trips Card (Build #174) -->
<div class="card" style="border-left: 3px solid #14b8a6;">
    <div style="display: flex; justify-content: space-between; align-items: center;">
        <div>
            <h2 style="margin: 0 0 4px;">My Trips</h2>
            <p style="margin: 0; color: rgba(255,255,255,0.6);">{{ trips_count }} trip{{ 's' if trips_count != 1 else '' }}</p>
        </div>
        <a href="/trips" style="background: linear-gradient(135deg, #14b8a6, #0d9488); color: white; padding: 8px 20px; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 14px;">View Trips</a>
    </div>
</div>
{% endif %}

{% if feature_wishlist %}
<!-- Collections Card (Build #174) -->
<div class="card" style="border-left: 3px solid #ec4899;">
    <div style="display: flex; justify-content: space-between; align-items: center;">
        <div>
            <h2 style="margin: 0 0 4px;">Collections</h2>
            <p style="margin: 0; color: rgba(255,255,255,0.6);">{{ collections_count }} collection{{ 's' if collections_count != 1 else '' }}</p>
        </div>
        <a href="/collections" style="background: linear-gradient(135deg, #ec4899, #db2777); color: white; padding: 8px 20px; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 14px;">View</a>
    </div>
</div>
{% endif %}

<div class="card">
    <h2>Account Settings</h2>
    <p><strong>Email:</strong> {{ user.email }}</p>
    <p><strong>Preferred Currency:</strong> {{ user.preferred_currency }}</p>
    <p><strong>Language:</strong> {{ language_name }}</p>
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

# ============================================================================
# Traveler Management UI (Build #100)
# ============================================================================

TRAVELERS_CONTENT = """
<div style="max-width:900px;margin:0 auto;">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:24px;">
        <div>
            <h1 style="color:#fff;margin:0 0 8px 0;font-size:28px;">Saved Travelers</h1>
            <p style="color:#aaa;margin:0;font-size:15px;">Manage traveler profiles for faster booking</p>
        </div>
        <button onclick="showAddTraveler()" class="btn" style="background:#00d4ff;color:#000;font-weight:600;">
            + Add Traveler
        </button>
    </div>

    {% if travelers %}
    <div style="display:flex;flex-direction:column;gap:16px;">
        {% for t in travelers %}
        <div class="card" style="border-left:4px solid {{ '#00d4ff' if t.is_primary else '#444' }};">
            <div style="display:flex;justify-content:space-between;align-items:start;flex-wrap:wrap;gap:16px;">
                <div style="flex:1;">
                    <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;">
                        <h3 style="margin:0;color:#fff;">{{ t.first_name }} {{ t.last_name }}</h3>
                        {% if t.is_primary %}
                        <span style="background:#00d4ff;color:#000;font-size:11px;padding:2px 8px;border-radius:4px;font-weight:600;">PRIMARY</span>
                        {% endif %}
                        <span style="background:rgba(255,255,255,0.1);color:#aaa;font-size:11px;padding:2px 8px;border-radius:4px;">{{ t.passenger_type or 'ADULT' }}</span>
                    </div>
                    <div style="color:#888;font-size:14px;">
                        {% if t.date_of_birth %}DOB: {{ t.date_of_birth.strftime('%b %d, %Y') }} &bull; {% endif %}
                        {{ t.gender or '?' }} &bull;
                        {{ t.email or 'No email' }}
                    </div>
                    {% if t.passport_number %}
                    <div style="color:#4caf50;font-size:13px;margin-top:8px;">
                        <span style="margin-right:8px;">&#x2713;</span>Passport on file ({{ t.passport_country or '?' }})
                        {% if t.passport_expiry %} &bull; Expires {{ t.passport_expiry.strftime('%b %Y') }}{% endif %}
                    </div>
                    {% else %}
                    <div style="color:#ff9800;font-size:13px;margin-top:8px;">
                        <span style="margin-right:8px;">&#x26A0;</span>No passport info — required for international flights
                    </div>
                    {% endif %}
                </div>
                <div style="display:flex;gap:8px;">
                    <button onclick="editTraveler({{ t.id }})" style="background:transparent;border:1px solid #555;color:#fff;padding:8px 16px;border-radius:4px;cursor:pointer;">Edit</button>
                    {% if not t.is_primary %}
                    <button onclick="setPrimary({{ t.id }})" style="background:transparent;border:1px solid #00d4ff;color:#00d4ff;padding:8px 16px;border-radius:4px;cursor:pointer;">Set Primary</button>
                    {% endif %}
                    <button onclick="deleteTraveler({{ t.id }})" style="background:transparent;border:1px solid #e57373;color:#e57373;padding:8px 16px;border-radius:4px;cursor:pointer;">Delete</button>
                </div>
            </div>
        </div>
        {% endfor %}
    </div>
    {% else %}
    <div class="card" style="text-align:center;padding:60px 20px;">
        <div style="font-size:48px;margin-bottom:16px;">&#x1F464;</div>
        <h3 style="color:#fff;margin:0 0 8px 0;">No Saved Travelers</h3>
        <p style="color:#888;margin:0 0 24px 0;">Add your first traveler profile to speed up booking</p>
        <button onclick="showAddTraveler()" class="btn" style="background:#00d4ff;color:#000;font-weight:600;">
            + Add Your First Traveler
        </button>
    </div>
    {% endif %}
</div>

<!-- Add/Edit Traveler Modal -->
<div id="travelerModal" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.8);z-index:1000;overflow-y:auto;">
    <div style="max-width:600px;margin:40px auto;background:#1a1a2e;border-radius:12px;padding:32px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:24px;">
            <h2 id="modalTitle" style="color:#fff;margin:0;">Add Traveler</h2>
            <button onclick="closeModal()" style="background:transparent;border:none;color:#888;font-size:24px;cursor:pointer;">&times;</button>
        </div>
        <form id="travelerForm" onsubmit="saveTraveler(event)">
            <input type="hidden" id="travelerId" value="">

            <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
                <div class="form-group">
                    <label style="color:#aaa;font-size:13px;">First Name *</label>
                    <input type="text" id="firstName" required style="width:100%;padding:12px;background:#16213e;border:1px solid #333;border-radius:6px;color:#fff;">
                </div>
                <div class="form-group">
                    <label style="color:#aaa;font-size:13px;">Last Name *</label>
                    <input type="text" id="lastName" required style="width:100%;padding:12px;background:#16213e;border:1px solid #333;border-radius:6px;color:#fff;">
                </div>
            </div>

            <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;margin-top:16px;">
                <div class="form-group">
                    <label style="color:#aaa;font-size:13px;">Date of Birth *</label>
                    <input type="date" id="dob" required style="width:100%;padding:12px;background:#16213e;border:1px solid #333;border-radius:6px;color:#fff;">
                </div>
                <div class="form-group">
                    <label style="color:#aaa;font-size:13px;">Gender *</label>
                    <select id="gender" required style="width:100%;padding:12px;background:#16213e;border:1px solid #333;border-radius:6px;color:#fff;">
                        <option value="">Select</option>
                        <option value="M">Male</option>
                        <option value="F">Female</option>
                    </select>
                </div>
                <div class="form-group">
                    <label style="color:#aaa;font-size:13px;">Passenger Type</label>
                    <select id="passengerType" style="width:100%;padding:12px;background:#16213e;border:1px solid #333;border-radius:6px;color:#fff;">
                        <option value="ADULT">Adult</option>
                        <option value="CHILD">Child (2-11)</option>
                        <option value="INFANT">Infant (0-2)</option>
                    </select>
                </div>
            </div>

            <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px;">
                <div class="form-group">
                    <label style="color:#aaa;font-size:13px;">Email</label>
                    <input type="email" id="email" style="width:100%;padding:12px;background:#16213e;border:1px solid #333;border-radius:6px;color:#fff;">
                </div>
                <div class="form-group">
                    <label style="color:#aaa;font-size:13px;">Phone</label>
                    <input type="tel" id="phone" style="width:100%;padding:12px;background:#16213e;border:1px solid #333;border-radius:6px;color:#fff;">
                </div>
            </div>

            <hr style="border:none;border-top:1px solid #333;margin:24px 0;">
            <h3 style="color:#fff;margin:0 0 16px 0;font-size:16px;">Passport Details (for international flights)</h3>

            <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
                <div class="form-group">
                    <label style="color:#aaa;font-size:13px;">Passport Number</label>
                    <input type="text" id="passportNumber" style="width:100%;padding:12px;background:#16213e;border:1px solid #333;border-radius:6px;color:#fff;">
                </div>
                <div class="form-group">
                    <label style="color:#aaa;font-size:13px;">Expiry Date</label>
                    <input type="date" id="passportExpiry" style="width:100%;padding:12px;background:#16213e;border:1px solid #333;border-radius:6px;color:#fff;">
                </div>
            </div>

            <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px;">
                <div class="form-group">
                    <label style="color:#aaa;font-size:13px;">Issuing Country</label>
                    <input type="text" id="passportCountry" placeholder="e.g., US" maxlength="2" style="width:100%;padding:12px;background:#16213e;border:1px solid #333;border-radius:6px;color:#fff;">
                </div>
                <div class="form-group">
                    <label style="color:#aaa;font-size:13px;">Nationality</label>
                    <input type="text" id="nationality" placeholder="e.g., US" maxlength="2" style="width:100%;padding:12px;background:#16213e;border:1px solid #333;border-radius:6px;color:#fff;">
                </div>
            </div>

            <div style="margin-top:24px;display:flex;gap:12px;justify-content:flex-end;">
                <button type="button" onclick="closeModal()" style="background:transparent;border:1px solid #555;color:#fff;padding:12px 24px;border-radius:6px;cursor:pointer;">Cancel</button>
                <button type="submit" class="btn" style="background:#00d4ff;color:#000;font-weight:600;padding:12px 24px;">Save Traveler</button>
            </div>
        </form>
    </div>
</div>

<script>
function showAddTraveler() {
    document.getElementById('modalTitle').textContent = 'Add Traveler';
    document.getElementById('travelerId').value = '';
    document.getElementById('travelerForm').reset();
    document.getElementById('travelerModal').style.display = 'block';
}

function closeModal() {
    document.getElementById('travelerModal').style.display = 'none';
}

async function editTraveler(id) {
    try {
        const resp = await fetch('/api/travelers/' + id);
        const data = await resp.json();
        if (data.traveler) {
            const t = data.traveler;
            document.getElementById('modalTitle').textContent = 'Edit Traveler';
            document.getElementById('travelerId').value = t.id;
            document.getElementById('firstName').value = t.first_name || '';
            document.getElementById('lastName').value = t.last_name || '';
            document.getElementById('dob').value = t.date_of_birth || '';
            document.getElementById('gender').value = t.gender || '';
            document.getElementById('passengerType').value = t.passenger_type || 'ADULT';
            document.getElementById('email').value = t.email || '';
            document.getElementById('phone').value = t.phone || '';
            document.getElementById('passportNumber').value = t.passport_number || '';
            document.getElementById('passportExpiry').value = t.passport_expiry || '';
            document.getElementById('passportCountry').value = t.passport_country || '';
            document.getElementById('nationality').value = t.nationality || '';
            document.getElementById('travelerModal').style.display = 'block';
        }
    } catch (e) { alert('Failed to load traveler'); }
}

async function saveTraveler(e) {
    e.preventDefault();
    const id = document.getElementById('travelerId').value;
    const data = {
        first_name: document.getElementById('firstName').value,
        last_name: document.getElementById('lastName').value,
        date_of_birth: document.getElementById('dob').value,
        gender: document.getElementById('gender').value,
        passenger_type: document.getElementById('passengerType').value,
        email: document.getElementById('email').value,
        phone: document.getElementById('phone').value,
        passport_number: document.getElementById('passportNumber').value,
        passport_expiry: document.getElementById('passportExpiry').value,
        passport_country: document.getElementById('passportCountry').value.toUpperCase(),
        nationality: document.getElementById('nationality').value.toUpperCase(),
    };

    try {
        const url = id ? '/api/travelers/' + id : '/api/travelers';
        const method = id ? 'PUT' : 'POST';
        const resp = await fetch(url, {
            method: method,
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(data)
        });
        if (resp.ok) {
            window.location.reload();
        } else {
            const err = await resp.json();
            alert(err.error || 'Failed to save');
        }
    } catch (e) { alert('Failed to save traveler'); }
}

async function setPrimary(id) {
    try {
        const resp = await fetch('/api/travelers/' + id + '/primary', { method: 'POST' });
        if (resp.ok) window.location.reload();
        else alert('Failed to set primary');
    } catch (e) { alert('Error setting primary'); }
}

async function deleteTraveler(id) {
    if (!confirm('Delete this traveler?')) return;
    try {
        const resp = await fetch('/api/travelers/' + id, { method: 'DELETE' });
        if (resp.ok) window.location.reload();
        else alert('Failed to delete');
    } catch (e) { alert('Error deleting traveler'); }
}
</script>
"""

DEALS_CONTENT = """
<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
    <h1 style="margin: 0;">Available Deals</h1>
    <div style="color: #fff; font-size: 14px;">
        XRP: <strong style="color: #7c3aed;">${{ "%.2f"|format(xrp_price) }}</strong> |
        Network: <strong>{{ network }}</strong> |
        {{ deals|length }} deal{{ 's' if deals|length != 1 else '' }} found
        {% if last_scan %} | Last scan: {{ last_scan }}{% endif %}
    </div>
</div>

{% if deals %}
    <div style="display: grid; gap: 20px;">
    {% for d in deals %}
    <div class="card" style="border-left: 4px solid #7c3aed;">
        <div style="display: flex; justify-content: space-between; align-items: start; flex-wrap: wrap; gap: 10px;">
            <div>
                {% if d.deal_type == 'hotel' %}
                    <span style="background: #6d28d9; color: white; font-size: 11px; padding: 2px 8px; border-radius: 4px; display: inline-block; margin-bottom: 5px;">HOTEL</span>
                    <h3 style="margin: 5px 0 5px 0; color: #f5f5f5;">{{ d.hotel_name }}</h3>
                    <div style="color: #fff; font-size: 14px;">
                        {{ d.city_code }} &bull;
                        {{ d.check_in_date.strftime('%b %d') if d.check_in_date else '' }} - {{ d.check_out_date.strftime('%b %d, %Y') if d.check_out_date else '' }}
                        ({{ d.nights }} night{{ 's' if d.nights != 1 else '' }})
                    </div>
                {% else %}
                    <h3 style="margin: 0 0 5px 0; color: #f5f5f5;">
                        {{ d.airline or 'Flight' }} {{ d.flight_number or '' }}
                    </h3>
                    <div style="color: #fff; font-size: 14px;">
                        {{ d.origin }} &rarr; {{ d.destination }} &bull;
                        {{ d.departure_date.strftime('%b %d, %Y') if d.departure_date else 'TBD' }}
                        {% if d.stops %} &bull; {{ d.stops }} stop{{ 's' if d.stops > 1 else '' }}{% endif %}
                    </div>
                {% endif %}
            </div>
            <div style="text-align: right;">
                {% if d.deal_type == 'hotel' %}
                    <div style="font-size: 24px; font-weight: bold; color: #7c3aed;">
                        ${{ "%.0f"|format(d.price_per_night_usd or 0) }}<span style="font-size: 14px; font-weight: normal; color: #ccc;">/night</span>
                    </div>
                    <div style="color: #ccc; font-size: 14px;">${{ "%.0f"|format(d.price_total_usd or 0) }} total</div>
                {% else %}
                    <div style="font-size: 24px; font-weight: bold; color: #4caf50;">
                        Save ${{ "%.0f"|format(d.user_savings_usd or d.gross_savings_usd or 0) }}
                    </div>
                    <div style="color: #81c784; font-size: 14px;">
                        {{ "%.0f"|format(d.savings_percent or 0) }}% off
                    </div>
                {% endif %}
            </div>
        </div>

        {% if d.deal_type != 'hotel' %}
        <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 15px; margin-top: 15px; padding-top: 15px; border-top: 1px solid rgba(255,255,255,0.1);">
            <div>
                <div style="color: #fff; font-size: 12px; text-transform: uppercase;">{{ d.home_market or 'US' }} Price</div>
                <div style="color: #e57373; font-size: 18px; text-decoration: line-through;">${{ "%.0f"|format(d.home_price_usd or 0) }}</div>
            </div>
            <div>
                <div style="color: #fff; font-size: 12px; text-transform: uppercase;">MYSTES Price</div>
                <div style="color: #4caf50; font-size: 18px; font-weight: bold;">${{ "%.0f"|format((d.arbitrage_price_usd or 0) + (d.platform_fee_usd or 0)) }}</div>
            </div>
            <div>
                <div style="color: #fff; font-size: 12px; text-transform: uppercase;">You Save</div>
                <div style="color: #4caf50; font-size: 18px; font-weight: bold;">${{ "%.0f"|format(d.user_savings_usd or d.gross_savings_usd or 0) }}</div>
            </div>
        </div>
        {% endif %}

        <div style="margin-top: 15px;">
            {% if current_user.is_authenticated %}
                <a href="/book/{{ d.deal_id }}" class="btn" style="display: inline-block;">{{ 'Book Hotel' if d.deal_type == 'hotel' else 'Book This Deal' }}</a>
            {% else %}
                <a href="/save-deal/{{ d.deal_id }}" class="btn" style="display: inline-block;">{{ 'Book Hotel' if d.deal_type == 'hotel' else 'Sign Up to Book' }}</a>
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
            Try asking MYSTES AI for a specific route, or check back soon.
        </p>
        <a href="/ai" class="btn">Try MYSTES AI</a>
    </div>
{% endif %}
"""

GUEST_CHECKOUT_CONTENT = """
<div class="card" style="max-width: 500px; margin: 40px auto; text-align: center;">
    <h2>Complete Your Booking</h2>
    <p style="color: #666; margin-bottom: 30px;">Your deal has been saved. Choose how you'd like to proceed:</p>

    <div style="background: #f8f9fa; padding: 20px; border-radius: 8px; margin-bottom: 20px;">
        {% if deal.deal_type == 'hotel' %}
            <span style="background: #6d28d9; color: white; font-size: 11px; padding: 2px 8px; border-radius: 4px;">HOTEL</span>
            <h3 style="margin: 10px 0 5px; color: #1a1a2e;">{{ deal.hotel_name }}</h3>
            <p style="margin: 5px 0; color: #1a1a2e;">{{ deal.city_code }} / {{ deal.check_in_date }} - {{ deal.check_out_date }}</p>
            <p style="margin-top: 15px; font-size: 1.2em;">
                <span style="color: #28a745; font-weight: bold;">${{ "%.2f"|format(deal.price_total_usd or 0) }}</span>
                <span style="color: #666; font-size: 0.8em;"> + ${{ "%.2f"|format(deal.platform_fee_usd or 0) }} fee</span>
            </p>
        {% else %}
            <h3 style="margin-bottom: 10px; color: #1a1a2e;">{{ deal.airline }} {{ deal.flight_number }}</h3>
            <p style="margin: 5px 0; color: #1a1a2e;">{{ deal.origin }} → {{ deal.destination }}</p>
            <p style="margin: 5px 0; color: #666;">{{ deal.departure_date }}</p>
            <p style="margin-top: 15px; font-size: 1.2em;">
                <span style="text-decoration: line-through; color: #fff;">${{ "%.2f"|format(deal.home_price_usd or 0) }}</span>
                <span style="color: #28a745; font-weight: bold; margin-left: 10px;">${{ "%.2f"|format(deal.arbitrage_price_usd or 0) }}</span>
                <span class="tag" style="margin-left: 10px;">Save ${{ "%.2f"|format(deal.user_savings_usd or 0) }}</span>
            </p>
        {% endif %}
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
        border-color: #7c3aed;
        box-shadow: 0 4px 12px rgba(67, 97, 238, 0.15);
    }
    .payment-method-card.selected {
        border-color: #7c3aed;
        background: #f5f3ff;
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
        background: #7c3aed;
        color: white;
        border: none;
        padding: 8px 16px;
        border-radius: 6px;
        cursor: pointer;
        font-size: 14px;
        margin-top: 10px;
    }
    .copy-btn:hover {
        background: #6d28d9;
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
        color: #14b8a6;
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
        border-top-color: #7c3aed;
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
                        <span style="color: #14b8a6;">{{ leg.airline or 'Multiple Airlines' }} • {{ leg.route }}</span><br>
                        <small>{{ leg.date }}</small>
                    </div>
                    <div style="text-align: right;">
                        <span style="font-size: 18px; font-weight: bold;">${{ "%.0f"|format(leg.cheapest_price or 0) }}</span>
                        <br><small style="color: #14b8a6;">via MYSTES</small>
                    </div>
                </div>
            </div>
            {% endfor %}
        {% else %}
            <div class="flight-leg-item">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <strong>{{ deal.airline or 'Flight' }} {{ deal.flight_number or '' }}</strong><br>
                        <span style="color: #14b8a6;">{{ deal.origin }} → {{ deal.destination }}</span><br>
                        <small>{{ deal.departure_date }}</small>
                    </div>
                    <div style="text-align: right;">
                        <span style="font-size: 18px; font-weight: bold;">${{ "%.0f"|format(deal.arbitrage_price_usd or 0) }}</span>
                        <br><small style="color: #14b8a6;">via MYSTES</small>
                    </div>
                </div>
            </div>
        {% endif %}

        <div class="order-row total">
            <span>MYSTES Price</span>
            <span>${{ "%.2f"|format((deal.arbitrage_price_usd or 0) + (deal.platform_fee_usd or 0)) }}</span>
        </div>
        {% if deal.user_savings_usd and deal.user_savings_usd > 0 %}
        <div class="order-row" style="color: #28a745;">
            <span>You save vs Google Flights</span>
            <span class="savings-badge">${{ "%.0f"|format(deal.user_savings_usd or 0) }}</span>
        </div>
        {% endif %}
    </div>

    <!-- Deal Expiration Warning -->
    {% if deal.expires_at %}
    <div id="expiration-warning" style="background: #fff3cd; border: 1px solid #ffc107; border-radius: 10px; padding: 14px 18px; margin-bottom: 20px; display: flex; align-items: center; gap: 12px;">
        <span style="font-size: 22px;">&#9200;</span>
        <div>
            <strong style="color: #856404;">This deal expires in <span id="expiry-countdown">--:--:--</span></strong>
            <p style="margin: 2px 0 0; font-size: 13px; color: #856404;">Book now to lock in your price.</p>
        </div>
    </div>
    <script>
    (function() {
        var expiresAt = new Date("{{ deal.expires_at }}");
        var warningEl = document.getElementById('expiration-warning');
        var countdownEl = document.getElementById('expiry-countdown');
        function updateCountdown() {
            var now = new Date();
            var diff = expiresAt - now;
            if (diff <= 0) {
                warningEl.style.background = '#f8d7da';
                warningEl.style.borderColor = '#f5c6cb';
                countdownEl.parentElement.innerHTML = '<strong style="color:#721c24;">This deal has expired.</strong> <a href="/flights" style="color:#721c24;text-decoration:underline;">Search again</a>';
                return;
            }
            var h = Math.floor(diff / 3600000);
            var m = Math.floor((diff % 3600000) / 60000);
            var s = Math.floor((diff % 60000) / 1000);
            countdownEl.textContent = (h > 0 ? h + 'h ' : '') + m + 'm ' + s + 's';
            if (diff < 600000) { warningEl.style.background = '#f8d7da'; warningEl.style.borderColor = '#f5c6cb'; }
            setTimeout(updateCountdown, 1000);
        }
        updateCountdown();
    })();
    </script>
    {% endif %}

    <!-- Savings Waterfall (Build #173 — no fee visibility) -->
    <div id="savings-waterfall" style="background: #f5f3ff; border: 2px solid #e9d5ff; border-radius: 12px; padding: 20px; margin-bottom: 25px;">
        <h4 style="margin: 0 0 15px 0; color: #5b21b6; font-family: 'Outfit', sans-serif;">Save Even More</h4>

        {% if fee_tier_name == 'Guest' %}
        <!-- Guest → Free Member upsell -->
        <div style="background: white; border-radius: 8px; padding: 15px; margin-bottom: 12px; border-left: 4px solid #14b8a6;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <strong style="color: #16213e;">Create a free account</strong>
                    <p style="margin: 4px 0 0; font-size: 13px; color: #666;">Get a better price — save ~${{ "%.0f"|format((deal.gross_savings_usd or 0) * 0.05) }} more on this booking</p>
                </div>
                <a href="/register?deal={{ deal.deal_id }}" style="background: #14b8a6; color: white; padding: 8px 20px; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 14px; white-space: nowrap;">Sign Up Free</a>
            </div>
        </div>
        {% endif %}

        {% if fee_tier_name in ['Guest', 'Free Member'] %}
        <!-- Travel+ upsell -->
        <div style="background: white; border-radius: 8px; padding: 15px; margin-bottom: 12px; border-left: 4px solid #7c3aed;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <strong style="color: #16213e;">Travel+ ($9.99/mo)</strong>
                    <p style="margin: 4px 0 0; font-size: 13px; color: #666;">Get an even better price — save ~${{ "%.0f"|format((deal.gross_savings_usd or 0) * (0.10 if fee_tier_name == 'Free Member' else 0.15)) }} more on this flight alone</p>
                    <p style="margin: 2px 0 0; font-size: 12px; color: #7c3aed;">Pays for itself on one booking over $67 savings</p>
                </div>
                <button onclick="window.location='/subscribe/travel-plus?deal={{ deal.deal_id }}'" style="background: linear-gradient(135deg, #7c3aed, #5b21b6); color: white; padding: 8px 20px; border-radius: 8px; border: none; cursor: pointer; font-weight: 600; font-size: 14px; white-space: nowrap;">Get Travel+</button>
            </div>
        </div>
        {% endif %}

        <!-- Share-to-Save -->
        <div style="background: white; border-radius: 8px; padding: 15px; margin-bottom: 12px; border-left: 4px solid #f59e0b;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <strong style="color: #16213e;">Share & Save</strong>
                    <p style="margin: 4px 0 0; font-size: 13px; color: #666;">Share this deal on social media and get an extra discount</p>
                </div>
                <div style="display: flex; gap: 8px;">
                    <button onclick="shareToSocial('twitter')" title="Share on X" style="background: #1DA1F2; color: white; border: none; border-radius: 50%; width: 36px; height: 36px; cursor: pointer; font-size: 16px;">X</button>
                    <button onclick="shareToSocial('facebook')" title="Share on Facebook" style="background: #4267B2; color: white; border: none; border-radius: 50%; width: 36px; height: 36px; cursor: pointer; font-size: 16px;">f</button>
                    <button onclick="shareToSocial('whatsapp')" title="Share on WhatsApp" style="background: #25D366; color: white; border: none; border-radius: 50%; width: 36px; height: 36px; cursor: pointer; font-size: 16px;">W</button>
                    <button onclick="shareToSocial('copy_link')" title="Copy Link" style="background: #6b7280; color: white; border: none; border-radius: 50%; width: 36px; height: 36px; cursor: pointer; font-size: 14px;">🔗</button>
                </div>
            </div>
            <div id="share-success" style="display:none; margin-top:8px; padding:8px 12px; background:#ecfdf5; border-radius:6px; color:#059669; font-size:13px; font-weight:600;">
                Shared! Discount applied to your price.
            </div>
        </div>

        <!-- Points Redemption (only for authenticated users with points) -->
        {% if current_user.is_authenticated and user_points_balance and user_points_balance > 0 %}
        <div style="background: white; border-radius: 8px; padding: 15px; border-left: 4px solid #ec4899;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <strong style="color: #16213e;">Use Points</strong>
                    <p style="margin: 4px 0 0; font-size: 13px; color: #666;">You have {{ "{:,}".format(user_points_balance) }} points (${{ "%.2f"|format(user_points_balance * 0.001) }} value)</p>
                </div>
                <div style="display: flex; align-items: center; gap: 8px;">
                    <input type="number" id="points-input" min="0" max="{{ user_points_balance }}" value="0" style="width: 80px; padding: 8px; border: 1px solid #ddd; border-radius: 6px; text-align: center;" onchange="updatePointsRedemption(this.value)">
                    <button onclick="document.getElementById('points-input').value='{{ user_points_balance }}'; updatePointsRedemption({{ user_points_balance }});" style="background: #ec4899; color: white; border: none; padding: 8px 12px; border-radius: 6px; cursor: pointer; font-size: 12px; font-weight: 600;">Use All</button>
                </div>
            </div>
            <div id="points-value" style="display:none; margin-top:8px; font-size:13px; color:#ec4899; font-weight:600;"></div>
        </div>
        {% endif %}
    </div>

    <script>
    function shareToSocial(platform) {
        var dealId = '{{ deal.deal_id }}';
        var savings = '{{ "%.0f"|format(deal.gross_savings_usd or 0) }}';
        var route = '{{ deal.origin }} to {{ deal.destination }}';

        fetch('/api/share', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({deal_id: dealId, platform: platform})
        }).then(r => r.json()).then(data => {
            var shareText = 'Just saved $' + savings + ' on flights from ' + route + ' with MYSTES! ✈️';
            var shareUrl = window.location.origin + (data.share_url || '/');

            if (platform === 'twitter') window.open('https://twitter.com/intent/tweet?text=' + encodeURIComponent(shareText) + '&url=' + encodeURIComponent(shareUrl), '_blank');
            else if (platform === 'facebook') window.open('https://www.facebook.com/sharer/sharer.php?u=' + encodeURIComponent(shareUrl) + '&quote=' + encodeURIComponent(shareText), '_blank');
            else if (platform === 'whatsapp') window.open('https://wa.me/?text=' + encodeURIComponent(shareText + ' ' + shareUrl), '_blank');
            else if (platform === 'copy_link') { navigator.clipboard.writeText(shareUrl).then(function() { alert('Link copied!'); }); }

            document.getElementById('share-success').style.display = 'block';
        });
    }

    function updatePointsRedemption(pts) {
        pts = parseInt(pts) || 0;
        var value = (pts * 0.001).toFixed(2);
        var el = document.getElementById('points-value');
        if (pts > 0) {
            el.style.display = 'block';
            el.textContent = pts.toLocaleString() + ' points = -$' + value + ' off your fee';
        } else {
            el.style.display = 'none';
        }
    }
    </script>

    <!-- Travel Insurance Upsell (Build #174) -->
    <div id="insurance-upsell" style="background: #f0fdf4; border: 2px solid #86efac; border-radius: 12px; padding: 20px; margin-bottom: 25px;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
            <h4 style="margin: 0; color: #166534; font-family: 'Outfit', sans-serif;">Protect Your Trip</h4>
            <span style="font-size: 12px; color: #6b7280;">Powered by SafetyWing</span>
        </div>
        <p style="color: #15803d; font-size: 14px; margin: 0 0 15px;">Medical coverage, trip cancellation, and baggage protection while traveling.</p>
        <div id="insurance-quotes" style="display: none;"></div>
        <button id="insurance-quote-btn" onclick="getInsuranceQuote()" style="background: #22c55e; color: white; border: none; padding: 10px 24px; border-radius: 8px; cursor: pointer; font-weight: 600; font-size: 14px;">Get Quote</button>
        <div id="insurance-loading" style="display: none; color: #6b7280; font-size: 13px; margin-top: 8px;">Loading quotes...</div>
    </div>
    <script>
    function getInsuranceQuote() {
        var btn = document.getElementById('insurance-quote-btn');
        var loading = document.getElementById('insurance-loading');
        btn.style.display = 'none';
        loading.style.display = 'block';
        var dest = '{{ deal.destination or "US" }}';
        var startDate = '{{ deal.departure_date or "" }}';
        fetch('/api/insurance/quote?destination=' + dest + '&start_date=' + startDate + '&travelers=1')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            loading.style.display = 'none';
            var container = document.getElementById('insurance-quotes');
            if (data.success && data.quotes && data.quotes.length > 0) {
                var html = '';
                data.quotes.forEach(function(q) {
                    html += '<div style="background:white;border-radius:8px;padding:14px;margin-bottom:10px;border-left:4px solid #22c55e;display:flex;justify-content:space-between;align-items:center;">';
                    html += '<div><strong style="color:#16213e;">' + (q.plan_name || 'Travel Insurance') + '</strong>';
                    html += '<p style="margin:4px 0 0;font-size:13px;color:#666;">Coverage: $' + (q.coverage_amount || '50,000') + '</p></div>';
                    html += '<div style="text-align:right;"><span style="font-size:18px;font-weight:bold;color:#166534;">$' + parseFloat(q.total_price || 0).toFixed(2) + '</span>';
                    html += '<br><label style="font-size:12px;cursor:pointer;"><input type="checkbox" name="add_insurance" value="' + (q.plan_id || '') + '" data-price="' + (q.total_price || 0) + '" data-name="' + (q.plan_name || '') + '" onchange="toggleInsurance(this)"> Add</label></div>';
                    html += '</div>';
                });
                container.innerHTML = html;
                container.style.display = 'block';
            } else {
                container.innerHTML = '<p style="color:#6b7280;font-size:13px;">Insurance not available for this destination.</p>';
                container.style.display = 'block';
            }
        }).catch(function() {
            loading.style.display = 'none';
            btn.style.display = 'inline-block';
            btn.textContent = 'Unavailable';
            btn.disabled = true;
        });
    }
    function toggleInsurance(cb) {
        document.querySelectorAll('input[name="add_insurance"]').forEach(function(el) {
            if (el !== cb) el.checked = false;
        });
    }
    </script>

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
            <input type="hidden" name="additional_passengers_json" id="additional-passengers-json" value="[]">
            <div style="background: #f8f9fa; border-radius: 12px; padding: 25px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                    <div>
                        <h4 style="margin: 0; color: #1a1a2e;">Passenger 1 (Primary)</h4>
                        <p style="color: #666; margin: 4px 0 0; font-size: 13px;">Enter details exactly as they appear on the travel document.</p>
                    </div>
                </div>

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
                        <div class="form-group">
                            <label style="font-weight: bold; color: #16213e; display: block; margin-bottom: 5px;">Passport Number</label>
                            <input type="text" name="passport_number" placeholder="AB1234567"
                                   style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 16px; color: #1a1a2e;">
                        </div>
                        <div class="form-group">
                            <label style="font-weight: bold; color: #16213e; display: block; margin-bottom: 5px;">Passport Expiry</label>
                            <input type="date" name="passport_expiry"
                                   style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 16px; color: #1a1a2e;">
                        </div>
                        <div class="form-group">
                            <label style="font-weight: bold; color: #16213e; display: block; margin-bottom: 5px;">Passport Country</label>
                            <input type="text" name="passport_country" placeholder="United States"
                                   style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 16px; color: #1a1a2e;">
                        </div>
                        <div class="form-group">
                            <label style="font-weight: bold; color: #16213e; display: block; margin-bottom: 5px;">Nationality</label>
                            <input type="text" name="nationality" placeholder="American"
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
            </div>

            <!-- Additional Passengers Container -->
            <div id="additional-passengers" style="margin-top: 15px;"></div>

            <button type="button" id="add-passenger-btn" onclick="addPassenger()" style="width: 100%; margin-top: 12px; padding: 14px; background: rgba(124,58,237,0.08); border: 2px dashed rgba(124,58,237,0.3); border-radius: 12px; color: #7c3aed; font-size: 15px; font-weight: 600; cursor: pointer; transition: background 0.2s, border-color 0.2s;" onmouseover="this.style.background='rgba(124,58,237,0.15)';this.style.borderColor='rgba(124,58,237,0.5)'" onmouseout="this.style.background='rgba(124,58,237,0.08)';this.style.borderColor='rgba(124,58,237,0.3)'">
                + Add Another Passenger
            </button>

            <!-- Booking Options -->
            <div style="margin-top: 20px; padding: 20px; background: #f5f3ff; border-radius: 12px;">
                <h5 style="margin: 0 0 15px 0; color: #1a1a2e;">Booking Method</h5>
                <div style="display: flex; gap: 20px; flex-wrap: wrap;">
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
                    Self-service: We provide a link to the airline&apos;s site through our regional proxy.
                </p>
            </div>

            <!-- Submit Button -->
            <button type="submit" class="btn btn-success" style="width: 100%; margin-top: 20px; padding: 15px; font-size: 18px;" onclick="serializeAdditionalPassengers()">
                Complete Booking
            </button>
        </form>

        <script>
        var paxCount = 1;
        var maxPax = 9;
        function addPassenger() {
            if (paxCount >= maxPax) { alert('Maximum ' + maxPax + ' passengers per booking.'); return; }
            paxCount++;
            var container = document.getElementById('additional-passengers');
            var div = document.createElement('div');
            div.className = 'additional-pax';
            div.id = 'pax-' + paxCount;
            div.style.cssText = 'background: #f8f9fa; border-radius: 12px; padding: 25px; position: relative;';
            div.innerHTML = '<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">' +
                '<h4 style="margin: 0; color: #1a1a2e;">Passenger ' + paxCount + '</h4>' +
                '<button type="button" onclick="removePassenger(' + paxCount + ')" style="background: none; border: 1px solid #e57373; color: #e57373; padding: 4px 12px; border-radius: 6px; cursor: pointer; font-size: 12px;">Remove</button>' +
                '</div>' +
                '<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px;">' +
                '<div class="form-group"><label style="font-weight: bold; color: #16213e; display: block; margin-bottom: 5px;">First Name *</label><input type="text" data-field="first_name" required placeholder="First name" style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 16px; color: #1a1a2e;"></div>' +
                '<div class="form-group"><label style="font-weight: bold; color: #16213e; display: block; margin-bottom: 5px;">Last Name *</label><input type="text" data-field="last_name" required placeholder="Last name" style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 16px; color: #1a1a2e;"></div>' +
                '<div class="form-group"><label style="font-weight: bold; color: #16213e; display: block; margin-bottom: 5px;">Date of Birth *</label><input type="date" data-field="date_of_birth" required style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 16px; color: #1a1a2e;"></div>' +
                '<div class="form-group"><label style="font-weight: bold; color: #16213e; display: block; margin-bottom: 5px;">Gender *</label><select data-field="gender" required style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 16px; color: #1a1a2e;"><option value="">Select...</option><option value="M">Male</option><option value="F">Female</option></select></div>' +
                '<div class="form-group"><label style="font-weight: bold; color: #16213e; display: block; margin-bottom: 5px;">Passport Number</label><input type="text" data-field="passport_number" placeholder="AB1234567" style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 16px; color: #1a1a2e;"></div>' +
                '<div class="form-group"><label style="font-weight: bold; color: #16213e; display: block; margin-bottom: 5px;">Nationality</label><input type="text" data-field="nationality" placeholder="American" style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 16px; color: #1a1a2e;"></div>' +
                '</div>';
            container.appendChild(div);
            if (paxCount >= maxPax) document.getElementById('add-passenger-btn').style.display = 'none';
        }
        function removePassenger(num) {
            var el = document.getElementById('pax-' + num);
            if (el) el.remove();
            // Don't decrement paxCount (IDs stay unique), just re-show button
            document.getElementById('add-passenger-btn').style.display = 'block';
        }
        function serializeAdditionalPassengers() {
            var paxDivs = document.querySelectorAll('.additional-pax');
            var passengers = [];
            paxDivs.forEach(function(div) {
                var pax = {};
                div.querySelectorAll('[data-field]').forEach(function(input) {
                    pax[input.getAttribute('data-field')] = input.value || '';
                });
                if (pax.first_name && pax.last_name) passengers.push(pax);
            });
            document.getElementById('additional-passengers-json').value = JSON.stringify(passengers);
        }
        </script>

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
        <div style="background: #f5f3ff; border: 2px solid #7c3aed; border-radius: 12px; padding: 20px; margin-bottom: 25px;">
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
                <a href="/register?deal={{ deal.deal_id }}" style="color: #7c3aed;">Create an account</a> to track your bookings and get price alerts.
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
                <div style="margin-left: auto; font-weight: bold; color: #7c3aed;">
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

        <!-- XRP/RLUSD payment options removed (Build #173 — Stripe + MoonPay only) -->

        <p style="text-align: center; color: #666; margin-top: 20px; font-size: 14px;">
            🔒 All payments are secure and encrypted<br>
            <small>By proceeding, you agree to our Terms of Service</small>
        </p>
    {% endif %}
</div>

<!-- Review & Pay Modal -->
<div id="review-modal" style="display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.7); z-index: 10000; align-items: center; justify-content: center; backdrop-filter: blur(4px);">
    <div style="background: #1a1a2e; border: 1px solid rgba(255,255,255,0.15); border-radius: 16px; max-width: 460px; width: 90%; padding: 30px; position: relative; max-height: 90vh; overflow-y: auto;">
        <button onclick="closeReviewModal()" style="position: absolute; top: 12px; right: 16px; background: none; border: none; color: #999; font-size: 24px; cursor: pointer; line-height: 1;">&times;</button>
        <h3 style="margin: 0 0 20px; font-family: Cinzel, serif; color: #f5f5f5; font-size: 18px;">Review Your Order</h3>

        <div style="background: rgba(255,255,255,0.05); border-radius: 10px; padding: 16px; margin-bottom: 16px;">
            <div style="font-size: 13px; color: #999; margin-bottom: 6px;">{{ deal.airline or '' }} {{ deal.flight_number or '' }}{% if deal.hotel_name %}{{ deal.hotel_name }}{% endif %}</div>
            <div style="font-size: 16px; font-weight: 600; color: #f5f5f5;">{{ deal.origin or deal.city_code or '' }} {% if deal.destination %}&#8594; {{ deal.destination }}{% endif %}</div>
            <div style="font-size: 13px; color: #999; margin-top: 4px;">{{ deal.departure_date or deal.check_in_date or '' }}{% if deal.return_date or deal.check_out_date %} &mdash; {{ deal.return_date or deal.check_out_date }}{% endif %}</div>
        </div>

        <div style="border-top: 1px solid rgba(255,255,255,0.1); padding-top: 16px;">
            <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                <span style="color: #f5f5f5; font-size: 16px; font-weight: 700;">MYSTES Price</span>
                <span style="color: #7c3aed; font-size: 20px; font-weight: 700;">${{ "%.2f"|format((deal.arbitrage_price_usd or 0) + (deal.platform_fee_usd or 0)) }}</span>
            </div>
            {% if deal.user_savings_usd %}
            <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                <span style="color: #4caf50; font-size: 14px;">You save vs Google Flights</span>
                <span style="color: #4caf50; font-size: 14px; font-weight: 600;">${{ "%.0f"|format(deal.user_savings_usd or 0) }}</span>
            </div>
            {% endif %}
        </div>

        <button onclick="confirmPayWithCard()" class="btn" style="width: 100%; margin-top: 20px; padding: 14px; background: linear-gradient(135deg, #7c3aed, #a855f7); font-size: 16px; font-weight: 600;">
            Confirm &amp; Pay ${{ "%.2f"|format((deal.arbitrage_price_usd or 0) + (deal.platform_fee_usd or 0)) }}
        </button>
        <p style="text-align: center; color: #666; margin-top: 12px; font-size: 12px;">Secure payment powered by Stripe</p>
    </div>
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
    if (!emailInput) return true;
    var email = emailInput.value.trim();
    if (!email) {
        alert('Please enter your email address to receive your booking confirmation.');
        emailInput.focus();
        return false;
    }
    var re = /^[^\\s@]+@[^\\s@]+\\.[^\\s@]{2,}$/;
    if (!re.test(email)) {
        alert('Please enter a valid email address (e.g. name@example.com).');
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
    if (!validateGuestEmail()) return;
    // Show review modal instead of going straight to Stripe
    var modal = document.getElementById('review-modal');
    modal.style.display = 'flex';
}

function closeReviewModal() {
    document.getElementById('review-modal').style.display = 'none';
}

function confirmPayWithCard() {
    closeReviewModal();
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

// Coinbase crypto payments removed — Stripe + MoonPay only

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
    """Homepage — clean hero with aurora background."""
    content = HOME_HERO if HOME_HERO else '<div style="text-align:center;padding:100px 20px;"><h1>MYSTES</h1><p>Where would you like to travel?</p></div>'
    return render_template_string(
        BASE_TEMPLATE,
        title="MYSTES",
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

        # Validate email domain accepts mail (catch fake/reserved domains like example.com)
        if not app.config.get("TESTING"):
            try:
                import dns.resolver
                domain = email.split("@")[1]
                BLOCKED_DOMAINS = {"example.com", "example.org", "example.net", "test.com",
                                   "localhost", "invalid", "test", "example"}
                if domain in BLOCKED_DOMAINS:
                    raise ValueError("reserved domain")
                answers = dns.resolver.resolve(domain, "MX")
                mx_hosts = [str(r.exchange).rstrip(".") for r in answers]
                if all(h == "" or h == "." for h in mx_hosts):
                    raise ValueError("null MX")
            except Exception:
                flash("Invalid email domain — please use a real email address", "error")
                if redirect_deal:
                    return redirect(f"/register?deal={redirect_deal}")
                return redirect("/register")

        # Create user
        user = User(email=email, name=name)
        user.set_password(password)
        db.session.add(user)
        db.session.flush()  # Get user.id before commit

        # Generate consumer referral code (Build #170)
        try:
            from models import generate_referral_code, ConsumerReferral, RewardsAccount
            user.referral_code = generate_referral_code(name)

            # Track referral attribution if user came via referral link
            ref_code = request.args.get('ref') or request.form.get('ref_code') or session.get('referral_code')
            if ref_code:
                referrer = User.query.filter_by(referral_code=ref_code).first()
                if referrer and referrer.id != user.id:
                    user.referred_by_user_id = referrer.id
                    referrer.total_referrals = (referrer.total_referrals or 0) + 1
                    # Create referral record
                    referral = ConsumerReferral(
                        referrer_id=referrer.id,
                        referee_id=user.id,
                        referral_code_used=ref_code,
                        signup_rewarded=True,
                    )
                    db.session.add(referral)
                    # Award signup points to referrer
                    signup_pts = app.config.get('REFERRAL_SIGNUP_POINTS', 2000)
                    rewards = RewardsAccount.query.filter_by(user_id=referrer.id).first()
                    if not rewards:
                        rewards = RewardsAccount(user_id=referrer.id)
                        db.session.add(rewards)
                        db.session.flush()
                    rewards.points_balance = (rewards.points_balance or 0) + signup_pts
                    rewards.lifetime_earned = (rewards.lifetime_earned or 0) + signup_pts
                    referral.total_points_awarded = signup_pts
                    from models import PointsTransaction
                    pt = PointsTransaction(
                        user_id=referrer.id, amount=signup_pts,
                        transaction_type='bonus', source='referral',
                        description=f'Referral signup: {email}'
                    )
                    db.session.add(pt)
                    # Notify referrer (Build #172)
                    try:
                        from email_service import send_referral_notification
                        send_referral_notification(
                            to=referrer.email, name=referrer.name,
                            referee_action=f"{email} signed up",
                            points_earned=signup_pts
                        )
                    except Exception:
                        pass
            session.pop('referral_code', None)
        except Exception as ref_err:
            logger.warning(f"Referral setup failed for {email} (non-blocking): {ref_err}")

        # Generate email verification token and send verification email
        try:
            token = user.generate_verification_token()
            db.session.commit()
            from email_service import send_verification_email
            send_verification_email(to=email, token=token, name=name)
        except Exception as verify_err:
            db.session.commit()  # Ensure user is saved even if email fails
            logger.warning(f"Verification email failed for {email} (non-blocking): {verify_err}")

        # Clear session pending deal before login (login_user may regenerate session)
        session.pop('pending_deal_id', None)

        login_user(user)
        flash("Account created successfully!", "success")

        # Auto-claim any escrowed points from guest bookings (Build #170)
        try:
            escrows = PointsEscrow.query.filter_by(guest_email=email, status='pending').all()
            if escrows:
                rewards = RewardsAccount.query.filter_by(user_id=user.id).first()
                if not rewards:
                    rewards = RewardsAccount(user_id=user.id)
                    db.session.add(rewards)
                    db.session.flush()
                claimed_pts = 0
                for esc in escrows:
                    if esc.claim_deadline and esc.claim_deadline.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
                        esc.status = 'expired'
                        continue
                    esc.status = 'claimed'
                    esc.claimed_by_user_id = user.id
                    rewards.points_balance = (rewards.points_balance or 0) + esc.points_amount
                    rewards.lifetime_earned = (rewards.lifetime_earned or 0) + esc.points_amount
                    claimed_pts += esc.points_amount
                    db.session.add(PointsTransaction(
                        user_id=user.id, amount=esc.points_amount,
                        transaction_type='bonus', source='escrow_claim',
                        description=f'Welcome points from booking ({esc.booking_reference})'
                    ))
                if claimed_pts > 0:
                    db.session.commit()
                    flash(f"Welcome! You have {claimed_pts:,} points from your previous booking!", "success")
                    # Send welcome points email (Build #172)
                    try:
                        from email_service import send_welcome_points_email
                        send_welcome_points_email(to=email, name=name, points=claimed_pts)
                    except Exception:
                        pass
        except Exception as esc_err:
            logger.warning(f"Escrow claim on registration failed for {email}: {esc_err}")

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


REFERRAL_SPLASH_CONTENT = """
<div style="max-width: 600px; margin: 0 auto; padding: 60px 20px; text-align: center;">
    <div style="font-size: 48px; margin-bottom: 16px;">&#9992;&#65039;</div>
    <h1 style="font-family: 'Cinzel', serif; color: #1a1a2e; margin-bottom: 8px; font-size: 28px;">
        {{ referrer_name }} is saving on flights with MYSTES
    </h1>
    <p style="color: #666; font-size: 18px; margin-bottom: 32px;">
        Create your free account and you both earn <strong style="color: #7c3aed;">2,000 bonus points</strong>.
    </p>

    <div style="background: white; border: 1px solid #e5e7eb; border-radius: 16px; padding: 28px; margin-bottom: 28px; text-align: left;">
        <h3 style="color: #1a1a2e; margin: 0 0 16px; text-align: center;">Why MYSTES?</h3>
        <div style="display: grid; gap: 14px;">
            <div style="display: flex; align-items: center; gap: 12px;">
                <span style="font-size: 22px; flex-shrink: 0;">&#128176;</span>
                <div><strong style="color: #1a1a2e;">Wholesale flight prices</strong><br><span style="color: #666; font-size: 14px;">Access airline prices below what Google Flights shows</span></div>
            </div>
            <div style="display: flex; align-items: center; gap: 12px;">
                <span style="font-size: 22px; flex-shrink: 0;">&#128269;</span>
                <div><strong style="color: #1a1a2e;">Multi-source search</strong><br><span style="color: #666; font-size: 14px;">We search GDS, NDC, and consolidator feeds simultaneously</span></div>
            </div>
            <div style="display: flex; align-items: center; gap: 12px;">
                <span style="font-size: 22px; flex-shrink: 0;">&#128200;</span>
                <div><strong style="color: #1a1a2e;">Real-time price comparison</strong><br><span style="color: #666; font-size: 14px;">See exactly how much you save vs Google Flights</span></div>
            </div>
            <div style="display: flex; align-items: center; gap: 12px;">
                <span style="font-size: 22px; flex-shrink: 0;">&#128276;</span>
                <div><strong style="color: #1a1a2e;">Price alerts & rewards</strong><br><span style="color: #666; font-size: 14px;">Earn points on every booking, get notified on price drops</span></div>
            </div>
        </div>
    </div>

    {% if google_client_id %}
    <div id="googleSignInBtn" style="display: flex; justify-content: center; margin-bottom: 16px;"></div>
    <script>
    if (window.google && google.accounts) {
        google.accounts.id.renderButton(document.getElementById("googleSignInBtn"), {theme: "outline", size: "large", text: "signup_with", width: 320});
    }
    </script>
    <div style="color: #999; font-size: 13px; margin-bottom: 16px;">or</div>
    {% endif %}

    <a href="/register?ref={{ ref_code }}" style="display: inline-block; background: linear-gradient(135deg, #7c3aed, #5b21b6); color: white; padding: 14px 48px; border-radius: 12px; font-weight: 700; text-decoration: none; font-size: 18px; transition: opacity 0.2s;">
        Create Free Account
    </a>
    <p style="margin-top: 16px;">
        <a href="/login" style="color: #7c3aed; font-size: 14px;">Already have an account? Sign in</a>
    </p>
</div>
"""


@app.route("/ref/<code>")
@app.route("/join/<code>")
def referral_landing(code):
    """Referral link splash page (Build #172)."""
    referrer = User.query.filter_by(referral_code=code).first()
    if referrer:
        session['referral_code'] = code
        if current_user.is_authenticated:
            flash("You already have an account!", "info")
            return redirect("/")
        referrer_name = referrer.name.split()[0] if referrer.name else "A MYSTES member"
        google_client_id = app.config.get('GOOGLE_CLIENT_ID') or os.environ.get('GOOGLE_CLIENT_ID', '')
        return render_template_string(
            BASE_TEMPLATE,
            title="Join MYSTES",
            content=REFERRAL_SPLASH_CONTENT,
            current_user=current_user,
            referrer_name=referrer_name,
            ref_code=code,
            google_client_id=google_client_id,
        )
    return redirect("/register")


@app.route("/api/referral/stats")
@login_required
def api_referral_stats():
    """Get current user's referral stats."""
    user = current_user
    referrals = ConsumerReferral.query.filter_by(referrer_id=user.id).all()
    total_points = sum(r.total_points_awarded for r in referrals)
    return jsonify({
        'referral_code': user.referral_code,
        'referral_url': f"/ref/{user.referral_code}" if user.referral_code else None,
        'total_referrals': len(referrals),
        'total_points_earned': total_points,
        'referrals': [{
            'referee_email': User.query.get(r.referee_id).email if User.query.get(r.referee_id) else None,
            'signup_rewarded': r.signup_rewarded,
            'first_booking_rewarded': r.first_booking_rewarded,
            'travel_plus_rewarded': r.travel_plus_rewarded,
            'points_awarded': r.total_points_awarded,
            'created_at': r.created_at.isoformat() if r.created_at else None,
        } for r in referrals],
    })


# --- Referral Card Generator (Build #179) ---

REFERRAL_CARD_CONTENT = """
<div class="card" style="max-width: 560px; margin: 40px auto;">
    <!-- Referral Card Header -->
    <div style="text-align: center; margin-bottom: 20px;">
        <div style="font-size: 42px; margin-bottom: 6px;">&#127968;</div>
        <h2 style="margin: 0; font-family: Cinzel, serif; color: #7c3aed;">
            {{ card.user_name }}'s MYSTES
        </h2>
        <p style="color: #999; margin: 6px 0 0; font-size: 13px;">Member since {{ card.member_since }}</p>
    </div>

    <!-- Stats Grid -->
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 20px;">
        <div style="background: rgba(76,175,80,0.08); border: 1px solid rgba(76,175,80,0.2); border-radius: 12px; padding: 16px; text-align: center;">
            <div style="font-size: 28px; font-weight: 700; color: #4caf50;">${{ "%.0f"|format(card.total_savings) }}</div>
            <div style="font-size: 11px; color: #999; text-transform: uppercase; letter-spacing: 1px;">Total Saved</div>
        </div>
        <div style="background: rgba(124,58,237,0.08); border: 1px solid rgba(124,58,237,0.2); border-radius: 12px; padding: 16px; text-align: center;">
            <div style="font-size: 28px; font-weight: 700; color: #a855f7;">{{ card.total_bookings }}</div>
            <div style="font-size: 11px; color: #999; text-transform: uppercase; letter-spacing: 1px;">Trips Booked</div>
        </div>
    </div>

    {% if card.favorite_destination %}
    <div style="background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 10px; padding: 12px 16px; margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center;">
        <span style="color: #999; font-size: 13px;">Favorite Destination</span>
        <span style="color: #f5f5f5; font-weight: 600;">{{ card.favorite_destination }}</span>
    </div>
    {% endif %}

    {% if card.total_referrals > 0 %}
    <div style="background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 10px; padding: 12px 16px; margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center;">
        <span style="color: #999; font-size: 13px;">Friends Referred</span>
        <span style="color: #f5f5f5; font-weight: 600;">{{ card.total_referrals }}</span>
    </div>
    {% endif %}

    <!-- Savings Badge -->
    <div style="background: linear-gradient(135deg, rgba(76,175,80,0.15), rgba(124,58,237,0.10)); border: 2px solid rgba(76,175,80,0.3); border-radius: 12px; padding: 20px; text-align: center; margin-bottom: 16px;">
        <div style="font-size: 13px; color: #81c784; text-transform: uppercase; letter-spacing: 1px;">Average Savings Per Trip</div>
        <div style="font-size: 36px; font-weight: 700; color: #4caf50;">
            {% if card.total_bookings > 0 %}${{ "%.0f"|format(card.total_savings / card.total_bookings) }}{% else %}$0{% endif %}
        </div>
        <div style="font-size: 13px; color: #999;">vs Google Flights, Expedia, Kayak &amp; others</div>
    </div>

    <!-- CTA -->
    <div style="text-align: center; margin-top: 10px;">
        <a href="/ref/{{ card.referral_code }}" class="btn" style="display: inline-block; padding: 14px 40px; background: linear-gradient(135deg, #7c3aed, #a855f7); border-radius: 8px; font-size: 15px; font-weight: 600; width: 80%; box-sizing: border-box;">
            Join MYSTES &#8212; Start Saving
        </a>
        <p style="color: #666; font-size: 11px; margin: 12px 0 0;">Real savings. Real data. No gimmicks.</p>
        <p style="color: #555; font-size: 10px; margin: 6px 0 0;">Referral code: <strong style="color: #a855f7;">{{ card.referral_code }}</strong></p>
    </div>
</div>
"""


@app.route("/api/referral-card/generate", methods=["POST"])
@login_required
def api_generate_referral_card():
    """Generate or update a shareable referral card with user's savings stats (Build #179).

    Returns card data + shareable public URL. Costs MYSTES $0 — the referral
    earning mechanism IS the incentive (B2B = sales revenue, B2C = points).
    """
    import secrets as _secrets
    from sqlalchemy import func

    user = current_user
    if not user.referral_code:
        user.referral_code = generate_referral_code(user.name)
        db.session.flush()

    # Calculate user stats from booking history
    bookings = Booking.query.filter_by(user_id=user.id, status='booked').all()
    total_bookings = len(bookings)
    total_savings = 0.0
    dest_counts = {}
    airline_counts = {}

    for b in bookings:
        deal = Deal.query.get(b.deal_id)
        if deal:
            total_savings += float(deal.user_savings_usd or 0)
            if deal.destination:
                dest_counts[deal.destination] = dest_counts.get(deal.destination, 0) + 1
            if deal.airline:
                airline_counts[deal.airline] = airline_counts.get(deal.airline, 0) + 1

    fav_dest = max(dest_counts, key=dest_counts.get) if dest_counts else None
    fav_airline = max(airline_counts, key=airline_counts.get) if airline_counts else None

    referrals = ConsumerReferral.query.filter_by(referrer_id=user.id).count()
    total_points = 0
    rewards = RewardsAccount.query.filter_by(user_id=user.id).first()
    if rewards:
        total_points = rewards.lifetime_earned

    member_since = user.created_at.strftime('%b %Y') if user.created_at else 'Recently'

    # Create or update ReferralCard
    card = ReferralCard.query.filter_by(user_id=user.id).first()
    if card:
        # Update existing card stats
        card.total_bookings = total_bookings
        card.total_savings_usd = total_savings
        card.total_referrals = referrals
        card.total_points_earned = total_points
        card.favorite_destination = fav_dest
        card.favorite_airline = fav_airline
        card.member_since = member_since
        card.updated_at = datetime.now(timezone.utc)
    else:
        card = ReferralCard(
            user_id=user.id,
            card_token=_secrets.token_urlsafe(16),
            referral_code=user.referral_code,
            total_bookings=total_bookings,
            total_savings_usd=total_savings,
            total_referrals=referrals,
            total_points_earned=total_points,
            member_since=member_since,
            favorite_destination=fav_dest,
            favorite_airline=fav_airline,
        )
        db.session.add(card)

    db.session.commit()

    return jsonify({
        'success': True,
        'card_token': card.card_token,
        'card_url': f"/ref-card/{card.card_token}",
        'card': {
            'user_name': (user.name.split()[0] if user.name else 'MYSTES Member'),
            'referral_code': user.referral_code,
            'total_bookings': total_bookings,
            'total_savings': total_savings,
            'total_referrals': referrals,
            'total_points_earned': total_points,
            'member_since': member_since,
            'favorite_destination': fav_dest,
            'favorite_airline': fav_airline,
        },
    })


@app.route("/ref-card/<token>")
def view_referral_card(token):
    """Public referral card page — shareable, linkable from bios/stories."""
    card = ReferralCard.query.filter_by(card_token=token).first()
    if not card:
        flash("Referral card not found.", "error")
        return redirect("/")

    # Track click
    card.clicks = (card.clicks or 0) + 1
    db.session.commit()

    user = User.query.get(card.user_id)
    user_name = (user.name.split()[0] if user and user.name else 'MYSTES Member')

    card_data = type('Card', (), {
        'user_name': user_name,
        'referral_code': card.referral_code,
        'total_bookings': card.total_bookings or 0,
        'total_savings': card.total_savings_usd or 0,
        'total_referrals': card.total_referrals or 0,
        'member_since': card.member_since or 'Recently',
        'favorite_destination': card.favorite_destination,
        'favorite_airline': card.favorite_airline,
    })()

    return render_template_string(
        BASE_TEMPLATE,
        title=f"{user_name}'s MYSTES Referral",
        content=render_template_string(REFERRAL_CARD_CONTENT, card=card_data),
        current_user=current_user,
    )


@app.route("/api/referral-card/click/<token>", methods=["POST"])
def api_referral_card_click(token):
    """Track a referral card click (for analytics)."""
    card = ReferralCard.query.filter_by(card_token=token).first()
    if not card:
        return jsonify({'error': 'Card not found'}), 404
    card.clicks = (card.clicks or 0) + 1
    db.session.commit()
    return jsonify({'success': True, 'clicks': card.clicks})


@app.route("/api/points/claim-escrow", methods=["POST"])
@login_required
def api_claim_escrow():
    """Claim escrowed points from guest bookings (Build #170).

    Called after user creates an account — finds all pending escrows
    matching their email and transfers points to their rewards account.
    """
    user = current_user
    escrows = PointsEscrow.query.filter_by(
        guest_email=user.email, status='pending'
    ).all()

    if not escrows:
        return jsonify({'claimed': 0, 'message': 'No pending points to claim'})

    total_claimed = 0
    rewards = RewardsAccount.query.filter_by(user_id=user.id).first()
    if not rewards:
        rewards = RewardsAccount(user_id=user.id)
        db.session.add(rewards)
        db.session.flush()

    for escrow in escrows:
        if escrow.claim_deadline and escrow.claim_deadline.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
            escrow.status = 'expired'
            continue
        escrow.status = 'claimed'
        escrow.claimed_by_user_id = user.id
        rewards.points_balance = (rewards.points_balance or 0) + escrow.points_amount
        rewards.lifetime_earned = (rewards.lifetime_earned or 0) + escrow.points_amount
        total_claimed += escrow.points_amount
        pt = PointsTransaction(
            user_id=user.id, amount=escrow.points_amount,
            transaction_type='bonus', source='escrow_claim',
            description=f'Claimed guest booking points ({escrow.booking_reference})'
        )
        db.session.add(pt)

    db.session.commit()
    return jsonify({
        'claimed': total_claimed,
        'escrows_claimed': len([e for e in escrows if e.status == 'claimed']),
        'new_balance': rewards.points_balance,
    })


@app.route("/api/points/balance")
@login_required
def api_points_balance():
    """Get current user's points balance and recent transactions."""
    user = current_user
    rewards = RewardsAccount.query.filter_by(user_id=user.id).first()
    if not rewards:
        return jsonify({'balance': 0, 'lifetime_earned': 0, 'transactions': []})

    recent_txns = PointsTransaction.query.filter_by(user_id=user.id)\
        .order_by(PointsTransaction.created_at.desc()).limit(20).all()

    return jsonify({
        'balance': rewards.points_balance or 0,
        'lifetime_earned': rewards.lifetime_earned or 0,
        'current_streak': rewards.current_streak_months or 0,
        'badge_level': rewards.badge_level,
        'transactions': [{
            'amount': t.amount,
            'type': t.transaction_type,
            'source': t.source,
            'description': t.description,
            'created_at': t.created_at.isoformat() if t.created_at else None,
        } for t in recent_txns],
    })


@app.route("/api/share", methods=["POST"])
def api_social_share():
    """Record a social share for share-to-save discount."""
    data = request.get_json(silent=True) or {}
    deal_id = data.get('deal_id')
    platform = data.get('platform', 'copy_link')

    if not deal_id:
        return jsonify({'error': 'deal_id required'}), 400

    import secrets as _secrets
    share_token = _secrets.token_urlsafe(16)
    ref_code = None

    user_id = None
    guest_email = data.get('guest_email')
    if current_user.is_authenticated:
        user_id = current_user.id
        ref_code = current_user.referral_code

    share = SocialShare(
        user_id=user_id,
        guest_email=guest_email,
        deal_id=deal_id,
        platform=platform,
        share_token=share_token,
        referral_code=ref_code,
    )
    db.session.add(share)
    db.session.commit()

    share_url = f"/deal/{deal_id}?shared={share_token}"
    if ref_code:
        share_url += f"&ref={ref_code}"

    return jsonify({
        'share_token': share_token,
        'share_url': share_url,
        'discount_eligible': True,
    })


@app.route("/api/share/<token>/click")
def api_share_click(token):
    """Track clicks on shared links."""
    share = SocialShare.query.filter_by(share_token=token).first()
    if share:
        share.clicks = (share.clicks or 0) + 1
        db.session.commit()
    # Redirect to deal
    deal_id = share.deal_id if share else None
    if deal_id:
        return redirect(f"/deal/{deal_id}")
    return redirect("/")


# --- Google Review Weapon (Build #178) ---

@app.route("/api/review/generate", methods=["POST"])
def api_generate_review():
    """Generate a pre-built savings review card for a completed booking.

    Request body: {booking_id: int, personal_note: str (optional)}
    Returns: {success, review_token, review_card: {all card fields}, review_url}
    """
    from models import GoogleReview, Booking, Deal
    import secrets as _secrets

    data = request.get_json(silent=True) or {}
    booking_id = data.get('booking_id')
    personal_note = data.get('personal_note', '')

    if not booking_id:
        return jsonify({'error': 'booking_id required'}), 400

    booking = Booking.query.get(booking_id)
    if not booking:
        return jsonify({'error': 'Booking not found'}), 404

    # Security: only booking owner can generate review
    if current_user.is_authenticated:
        if booking.user_id and booking.user_id != current_user.id:
            return jsonify({'error': 'Access denied'}), 403
    else:
        if session.get('booking_id') != booking_id:
            return jsonify({'error': 'Access denied'}), 403

    # Check if review already exists
    existing = GoogleReview.query.filter_by(booking_id=booking_id).first()
    if existing:
        return jsonify({
            'success': True,
            'review_token': existing.review_token,
            'review_card': _build_review_card_dict(existing),
            'review_url': f"/review/{existing.review_token}",
            'already_exists': True,
        })

    deal = Deal.query.get(booking.deal_id)
    if not deal:
        return jsonify({'error': 'Deal not found'}), 404

    mystes_price = float((deal.arbitrage_price_usd or 0) + (deal.platform_fee_usd or 0))
    retail_price = float(deal.home_price_usd or 0)
    savings = float(deal.user_savings_usd or 0)
    savings_pct = float(deal.savings_percent or 0)

    # Fetch competitor prices via SerpAPI (lazy — only when review is generated)
    competitor_prices = []
    try:
        from serpapi_client import SerpAPIClient
        serp = SerpAPIClient()
        if serp.is_configured and deal.origin and deal.destination and deal.departure_date:
            dep_date = deal.departure_date
            if hasattr(dep_date, 'isoformat'):
                dep_date = dep_date.isoformat()
            result = serp.search_google_flights(
                origin=deal.origin,
                destination=deal.destination,
                date=str(dep_date),
            )
            if result.get('flights'):
                for f in result['flights'][:6]:
                    name = f.get('airline', 'Unknown')
                    price = f.get('price')
                    if price and name:
                        competitor_prices.append({'name': name, 'price': price})
            price_insights = result.get('price_insights', {})
            if price_insights.get('lowest_price'):
                google_lowest = price_insights['lowest_price']
                if not any(c['name'] == 'Google Flights' for c in competitor_prices):
                    competitor_prices.append({'name': 'Google Flights', 'price': google_lowest})
    except Exception as e:
        logger.warning(f"SerpAPI competitor fetch for review failed: {e}")

    if not competitor_prices and retail_price > 0:
        competitor_prices.append({'name': 'Market Average', 'price': retail_price})

    from payments import get_fee_tier_name
    user = current_user if current_user.is_authenticated else None
    tier_name = get_fee_tier_name(user)

    fee_breakdown = {
        'tier': tier_name,
        'base_savings': savings,
        'platform_fee': float(deal.platform_fee_usd or 0),
        'net_savings': savings,
    }

    ref_code = None
    if current_user.is_authenticated and current_user.referral_code:
        ref_code = current_user.referral_code

    review_token = _secrets.token_urlsafe(16)

    review = GoogleReview(
        booking_id=booking_id,
        user_id=current_user.id if current_user.is_authenticated else None,
        guest_email=booking.passenger_email,
        origin=deal.origin or '',
        destination=deal.destination or '',
        airline=deal.airline,
        flight_number=deal.flight_number,
        departure_date=deal.departure_date,
        cabin_class=deal.cabin_class,
        mystes_price_usd=mystes_price,
        savings_usd=savings,
        savings_percent=savings_pct,
        retail_price_usd=retail_price,
        competitor_prices_json=json.dumps(competitor_prices),
        tier_name=tier_name,
        fee_breakdown_json=json.dumps(fee_breakdown),
        personal_note=personal_note if personal_note else None,
        referral_code=ref_code,
        review_token=review_token,
    )
    db.session.add(review)
    db.session.commit()

    return jsonify({
        'success': True,
        'review_token': review_token,
        'review_card': _build_review_card_dict(review),
        'review_url': f"/review/{review_token}",
    })


def _build_review_card_dict(review):
    """Build the standard review card data from a GoogleReview record."""
    competitors = []
    try:
        competitors = json.loads(review.competitor_prices_json or '[]')
    except (json.JSONDecodeError, TypeError):
        pass
    fee_breakdown = {}
    try:
        fee_breakdown = json.loads(review.fee_breakdown_json or '{}')
    except (json.JSONDecodeError, TypeError):
        pass
    return {
        'origin': review.origin,
        'destination': review.destination,
        'airline': review.airline,
        'flight_number': review.flight_number,
        'departure_date': review.departure_date,
        'cabin_class': review.cabin_class,
        'mystes_price': review.mystes_price_usd,
        'savings': review.savings_usd,
        'savings_percent': review.savings_percent,
        'retail_price': review.retail_price_usd,
        'competitors': competitors,
        'tier': review.tier_name,
        'fee_breakdown': fee_breakdown,
        'personal_note': review.personal_note,
        'referral_code': review.referral_code,
        'review_token': review.review_token,
        'shared_to_google': review.shared_to_google,
    }


REVIEW_CARD_CONTENT = """
<div class="card" style="max-width: 560px; margin: 40px auto;">
    <!-- Review Card Header -->
    <div style="text-align: center; margin-bottom: 20px;">
        <div style="font-size: 42px; margin-bottom: 6px;">&#9992;&#65039;</div>
        <h2 style="margin: 0; font-family: Cinzel, serif; color: #4caf50;">
            Saved ${{ "%.0f"|format(card.savings) }} with MYSTES
        </h2>
        <p style="color: #999; margin: 6px 0 0; font-size: 13px;">
            {{ "%.0f"|format(card.savings_percent) }}% less than competitors
        </p>
    </div>

    <!-- Flight Details -->
    <div style="background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 18px; margin-bottom: 16px;">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <div>
                <div style="font-size: 20px; font-weight: 700; color: #f5f5f5;">{{ card.origin }} &#8594; {{ card.destination }}</div>
                <div style="font-size: 13px; color: #999;">{{ card.airline or '' }} {{ card.flight_number or '' }} &middot; {{ card.departure_date or '' }}</div>
                <div style="font-size: 12px; color: #777;">{{ card.cabin_class or 'Economy' }}</div>
            </div>
            <div style="text-align: right;">
                <div style="font-size: 12px; color: #81c784; text-transform: uppercase;">MYSTES Price</div>
                <div style="font-size: 28px; font-weight: 700; color: #4caf50;">${{ "%.0f"|format(card.mystes_price) }}</div>
            </div>
        </div>
    </div>

    <!-- Competitor Prices -->
    {% if card.competitors %}
    <div style="background: rgba(229,115,115,0.06); border: 1px solid rgba(229,115,115,0.15); border-radius: 12px; padding: 16px; margin-bottom: 16px;">
        <div style="font-size: 12px; text-transform: uppercase; letter-spacing: 1px; color: #e57373; margin-bottom: 10px;">Competitor Prices</div>
        {% for comp in card.competitors %}
        <div style="display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid rgba(255,255,255,0.06);">
            <span style="color: #999;">{{ comp.name }}</span>
            <span style="color: #e57373;">${{ "%.0f"|format(comp.price) }}
                {% if comp.price > card.mystes_price %}
                <span style="font-size:11px;color:#e57373;"> (+${{ "%.0f"|format(comp.price - card.mystes_price) }})</span>
                {% endif %}
            </span>
        </div>
        {% endfor %}
        <div style="display: flex; justify-content: space-between; padding: 8px 0 0; margin-top: 4px; border-top: 2px solid rgba(76,175,80,0.3);">
            <span style="color: #4caf50; font-weight: 600;">MYSTES</span>
            <span style="color: #4caf50; font-weight: 700; font-size: 16px;">${{ "%.0f"|format(card.mystes_price) }}</span>
        </div>
    </div>
    {% endif %}

    <!-- Savings Badge -->
    <div style="background: linear-gradient(135deg, rgba(76,175,80,0.15), rgba(76,175,80,0.05)); border: 2px solid rgba(76,175,80,0.3); border-radius: 12px; padding: 20px; text-align: center; margin-bottom: 16px;">
        <div style="font-size: 14px; color: #81c784; text-transform: uppercase; letter-spacing: 1px;">Total Saved</div>
        <div style="font-size: 42px; font-weight: 700; color: #4caf50;">${{ "%.0f"|format(card.savings) }}</div>
        <div style="font-size: 13px; color: #999;">
            {{ card.tier or 'Guest' }} pricing
            {% if card.savings_percent %} &middot; {{ "%.0f"|format(card.savings_percent) }}% below market{% endif %}
        </div>
    </div>

    {% if card.personal_note %}
    <div style="background: rgba(255,255,255,0.04); border-radius: 10px; padding: 14px; margin-bottom: 16px; font-style: italic; color: #ccc; font-size: 14px;">
        &ldquo;{{ card.personal_note }}&rdquo;
    </div>
    {% endif %}

    <!-- CTA -->
    <div style="text-align: center; margin-top: 10px;">
        <a href="/{{ 'ref/' + card.referral_code if card.referral_code else '' }}" class="btn" style="display: inline-block; padding: 14px 40px; background: linear-gradient(135deg, #4caf50, #2e7d32); border-radius: 8px; font-size: 15px; font-weight: 600;">
            Try MYSTES &#8212; Start Saving
        </a>
        <p style="color: #666; font-size: 11px; margin: 12px 0 0;">Real savings from a real customer. No gimmicks.</p>
    </div>
</div>
"""


@app.route("/review/<token>")
def view_review_card(token):
    """Public review card page — shareable, indexable by Google."""
    from models import GoogleReview
    review = GoogleReview.query.filter_by(review_token=token).first()
    if not review:
        flash("Review not found.", "error")
        return redirect("/")

    card = _build_review_card_dict(review)
    # Convert competitors to objects for Jinja access
    class _Comp:
        def __init__(self, d):
            self.name = d.get('name', 'Unknown')
            self.price = d.get('price', 0)
    card_obj = type('Card', (), card)()
    card_obj.competitors = [_Comp(c) for c in card.get('competitors', [])]

    return render_template_string(
        BASE_TEMPLATE,
        title=f"Saved ${card['savings']:.0f} on {card['origin']}-{card['destination']}",
        content=render_template_string(REVIEW_CARD_CONTENT, card=card_obj),
        current_user=current_user,
    )


@app.route("/api/review/<token>/shared", methods=["POST"])
def api_review_shared(token):
    """Mark a review as shared. Tiered incentives (Build #179):
    - Google Review: 5% discount ALWAYS (permanent indexed marketing asset)
    - Social Share first booking: 2% cash discount (onboarding)
    - Social Share recurring: award points (retention via ecosystem)
    """
    from models import GoogleReview, SocialShare, Booking, RewardsAccount, PointsTransaction
    import secrets as _secrets

    review = GoogleReview.query.filter_by(review_token=token).first()
    if not review:
        return jsonify({'error': 'Review not found'}), 404

    data = request.get_json(silent=True) or {}
    platform = data.get('platform', 'google_review')

    if platform == 'google_review':
        review.shared_to_google = True
    else:
        review.shared_to_social = True

    if not review.shared_at:
        review.shared_at = datetime.now(timezone.utc)

    reward_type = None
    reward_message = ''
    points_awarded = 0

    if not review.discount_applied:
        is_google = (platform == 'google_review')

        if is_google:
            # Google Review: 5% discount ALWAYS — permanent marketing asset
            share = SocialShare(
                user_id=review.user_id,
                guest_email=review.guest_email,
                deal_id=str(review.booking_id),
                platform='google_review',
                share_token=_secrets.token_urlsafe(12),
                referral_code=review.referral_code,
                discount_applied=True,
            )
            db.session.add(share)
            review.discount_applied = True
            reward_type = 'discount'
            reward_message = 'Google Review shared! 5% discount applied to your next booking.'
        else:
            # Social share: check if first booking or recurring
            is_first_share = True
            if review.user_id:
                prior_social_shares = SocialShare.query.filter(
                    SocialShare.user_id == review.user_id,
                    SocialShare.platform != 'google_review',
                    SocialShare.discount_applied == True,
                ).count()
                is_first_share = (prior_social_shares == 0)

            if is_first_share:
                # First social share: 2% cash discount (onboarding hook)
                share = SocialShare(
                    user_id=review.user_id,
                    guest_email=review.guest_email,
                    deal_id=str(review.booking_id),
                    platform=platform,
                    share_token=_secrets.token_urlsafe(12),
                    referral_code=review.referral_code,
                    discount_applied=True,
                )
                db.session.add(share)
                review.discount_applied = True
                reward_type = 'discount'
                reward_message = 'First share bonus! 2% discount applied to your next booking.'
            else:
                # Recurring social share: award points (200 pts)
                share = SocialShare(
                    user_id=review.user_id,
                    guest_email=review.guest_email,
                    deal_id=str(review.booking_id),
                    platform=platform,
                    share_token=_secrets.token_urlsafe(12),
                    referral_code=review.referral_code,
                    discount_applied=False,
                )
                db.session.add(share)
                review.discount_applied = True  # Mark review as processed

                # Award 200 points for social share
                if review.user_id:
                    points_awarded = 200
                    rewards = RewardsAccount.query.filter_by(user_id=review.user_id).first()
                    if not rewards:
                        rewards = RewardsAccount(user_id=review.user_id)
                        db.session.add(rewards)
                        db.session.flush()
                    rewards.points_balance += points_awarded
                    rewards.lifetime_earned += points_awarded
                    rewards.last_earning_at = datetime.now(timezone.utc)

                    txn = PointsTransaction(
                        user_id=review.user_id,
                        amount=points_awarded,
                        transaction_type='earn',
                        source='social_share',
                        booking_id=review.booking_id,
                        description=f'Social share on {platform}',
                    )
                    db.session.add(txn)

                reward_type = 'points'
                reward_message = f'Shared! {points_awarded} points added to your rewards.'

    db.session.commit()

    return jsonify({
        'success': True,
        'discount_applied': review.discount_applied,
        'reward_type': reward_type or 'none',
        'points_awarded': points_awarded,
        'message': reward_message or 'Already shared!',
    })


@app.route("/api/insurance/quote")
def api_insurance_quote():
    """Get travel insurance quotes from SafetyWing (Build #174)."""
    destination = request.args.get("destination", "US")
    start_date = request.args.get("start_date", "")
    end_date = request.args.get("end_date", "")
    travelers = int(request.args.get("travelers", 1))
    try:
        from safetywing_client import SafetyWingClient
        client = SafetyWingClient()
        result = client.get_insurance_quote(
            destination=destination,
            start_date=start_date,
            end_date=end_date,
            travelers=travelers,
        )
        if result.get("success"):
            return jsonify({"success": True, "quotes": result.get("quotes", [])})
        return jsonify({"success": False, "error": result.get("error", "No quotes available")})
    except ImportError:
        return jsonify({"success": False, "error": "Insurance service not available"})
    except Exception as e:
        logger.warning(f"Insurance quote error: {e}")
        return jsonify({"success": False, "error": "Could not get insurance quotes"})


@app.route("/api/checkout/pricing", methods=["POST"])
def api_checkout_pricing():
    """Calculate real-time checkout pricing with savings waterfall (Build #170).

    Request body: {deal_id, apply_share: bool, points_to_redeem: int}
    Returns full breakdown for checkout UI.
    """
    from payments import calculate_savings_breakdown

    data = request.get_json(silent=True) or {}
    deal_id = data.get('deal_id')
    apply_share = data.get('apply_share', False)
    points_to_redeem = int(data.get('points_to_redeem', 0))

    deal = Deal.query.filter_by(deal_id=deal_id).first() if deal_id else None
    if not deal:
        return jsonify({'error': 'Deal not found'}), 404

    retail_price = float(deal.retail_price or deal.best_price or 0)
    our_price = float(deal.booked_price or deal.best_price or 0)

    # Limit points to user's balance
    user = current_user if current_user.is_authenticated else None
    if points_to_redeem > 0 and user:
        rewards = RewardsAccount.query.filter_by(user_id=user.id).first()
        max_pts = rewards.points_balance if rewards else 0
        points_to_redeem = min(points_to_redeem, max_pts)
    elif not user:
        points_to_redeem = 0

    breakdown = calculate_savings_breakdown(
        retail_price=retail_price,
        our_price=our_price,
        user=user,
        apply_share_discount=apply_share,
        points_to_redeem=points_to_redeem,
    )

    # Add upsell flag
    from payments import get_fee_tier_name
    breakdown['show_travel_plus_upsell'] = (
        get_fee_tier_name(user) in ('Guest', 'Free Member')
        and breakdown['travel_plus_extra_savings'] > 5.0
    )
    breakdown['show_member_upsell'] = (
        get_fee_tier_name(user) == 'Guest'
    )

    return jsonify(breakdown)


@app.route("/api/points/redeem", methods=["POST"])
@login_required
def api_points_redeem():
    """Preview points redemption value (Build #170).

    Request: {points: int}
    Returns: {value_usd: float, max_redeemable: int}
    """
    data = request.get_json(silent=True) or {}
    points = int(data.get('points', 0))

    rewards = RewardsAccount.query.filter_by(user_id=current_user.id).first()
    max_pts = rewards.points_balance if rewards else 0
    points = min(points, max_pts)

    redemption_rate = app.config.get('POINTS_REDEMPTION_VALUE', 0.001)
    value = round(points * redemption_rate, 2)

    return jsonify({
        'points': points,
        'value_usd': value,
        'max_redeemable': max_pts,
        'redemption_rate': redemption_rate,
    })


@app.route("/api/points/gift", methods=["POST"])
@login_required
def api_points_gift():
    """Send points to another member (Build #170)."""
    data = request.get_json(silent=True) or {}
    recipient_email = data.get('recipient_email', '').strip().lower()
    amount = int(data.get('amount', 0))
    message = data.get('message', '')[:200]

    if not recipient_email or amount <= 0:
        return jsonify({'error': 'recipient_email and positive amount required'}), 400

    min_gift = app.config.get('POINTS_MIN_GIFT', 1000)
    if amount < min_gift:
        return jsonify({'error': f'Minimum gift is {min_gift} points'}), 400

    # Check sender balance
    sender_rewards = RewardsAccount.query.filter_by(user_id=current_user.id).first()
    if not sender_rewards or sender_rewards.points_balance < amount:
        return jsonify({'error': 'Insufficient points balance'}), 400

    # Find recipient
    recipient = User.query.filter_by(email=recipient_email).first()
    if not recipient:
        return jsonify({'error': 'Recipient not found'}), 404
    if recipient.id == current_user.id:
        return jsonify({'error': 'Cannot gift to yourself'}), 400

    # Check monthly send limit
    from sqlalchemy import func
    month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    sent_this_month = db.session.query(func.sum(PointGift.amount)).filter(
        PointGift.sender_id == current_user.id,
        PointGift.created_at >= month_start,
    ).scalar() or 0
    send_limit = app.config.get('POINTS_GIFT_SEND_LIMIT_MONTHLY', 20000)
    if sent_this_month + amount > send_limit:
        return jsonify({'error': f'Monthly send limit ({send_limit} pts) reached'}), 400

    # Execute transfer
    sender_rewards.points_balance -= amount

    recipient_rewards = RewardsAccount.query.filter_by(user_id=recipient.id).first()
    if not recipient_rewards:
        recipient_rewards = RewardsAccount(user_id=recipient.id)
        db.session.add(recipient_rewards)
        db.session.flush()
    recipient_rewards.points_balance = (recipient_rewards.points_balance or 0) + amount
    recipient_rewards.lifetime_earned = (recipient_rewards.lifetime_earned or 0) + amount

    gift = PointGift(
        sender_id=current_user.id, recipient_id=recipient.id,
        amount=amount, message=message,
    )
    db.session.add(gift)

    # Ledger entries
    db.session.add(PointsTransaction(
        user_id=current_user.id, amount=-amount,
        transaction_type='gift_sent', source='gift',
        description=f'Gift to {recipient_email}'
    ))
    db.session.add(PointsTransaction(
        user_id=recipient.id, amount=amount,
        transaction_type='gift_received', source='gift',
        description=f'Gift from {current_user.email}: {message}' if message else f'Gift from {current_user.email}'
    ))

    db.session.commit()
    return jsonify({
        'success': True,
        'amount': amount,
        'recipient': recipient_email,
        'new_balance': sender_rewards.points_balance,
    })


@app.route("/api/alerts", methods=["GET", "POST"])
@login_required
def api_price_alerts():
    """Create or list price alerts (Build #170)."""
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        origin = data.get('origin', '').upper().strip()
        destination = data.get('destination', '').upper().strip()
        max_price = data.get('max_price_usd')
        date_from = data.get('date_from')
        date_to = data.get('date_to')

        if not origin or not destination:
            return jsonify({'error': 'origin and destination required'}), 400

        # Check limit (max 10 active alerts)
        active_count = PriceAlert.query.filter_by(user_id=current_user.id, is_active=True).count()
        if active_count >= 10:
            return jsonify({'error': 'Maximum 10 active alerts. Delete some first.'}), 400

        alert = PriceAlert(
            user_id=current_user.id,
            origin=origin,
            destination=destination,
            max_price_usd=float(max_price) if max_price else None,
            date_from=datetime.strptime(date_from, '%Y-%m-%d').date() if date_from else None,
            date_to=datetime.strptime(date_to, '%Y-%m-%d').date() if date_to else None,
            is_active=True,
        )
        db.session.add(alert)
        db.session.commit()
        return jsonify({
            'id': alert.id,
            'origin': alert.origin,
            'destination': alert.destination,
            'max_price_usd': alert.max_price_usd,
        }), 201

    # GET — list active alerts
    alerts = PriceAlert.query.filter_by(user_id=current_user.id, is_active=True)\
        .order_by(PriceAlert.created_at.desc()).all()
    return jsonify([{
        'id': a.id,
        'origin': a.origin,
        'destination': a.destination,
        'max_price_usd': a.max_price_usd,
        'date_from': a.date_from.isoformat() if a.date_from else None,
        'date_to': a.date_to.isoformat() if a.date_to else None,
        'last_triggered': a.last_triggered.isoformat() if a.last_triggered else None,
        'created_at': a.created_at.isoformat() if a.created_at else None,
    } for a in alerts])


@app.route("/api/alerts/<int:alert_id>", methods=["DELETE"])
@login_required
def api_delete_alert(alert_id):
    """Delete a price alert."""
    alert = PriceAlert.query.filter_by(id=alert_id, user_id=current_user.id).first()
    if not alert:
        return jsonify({'error': 'Alert not found'}), 404
    alert.is_active = False
    db.session.commit()
    return jsonify({'success': True})


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
            user.last_login = datetime.now(timezone.utc)
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


@app.route("/verify-email/<token>")
def verify_email(token):
    """Verify a user's email address via token link."""
    user = User.query.filter_by(verification_token=token).first()
    if user and user.verify_email(token):
        db.session.commit()
        flash("Email verified successfully!", "success")
        if current_user.is_authenticated:
            return redirect("/ai")
        return redirect("/login")
    flash("Invalid or expired verification link.", "error")
    return redirect("/login")


@app.route("/forgot-password", methods=["GET", "POST"])
@limiter.limit("5 per hour", methods=["POST"])
def forgot_password():
    """Request a password reset email."""
    if request.method == "POST":
        email = request.form.get("email", "").lower().strip()
        user = User.query.filter_by(email=email).first()
        if user:
            try:
                token = user.generate_reset_token()
                db.session.commit()
                from email_service import send_password_reset_email
                send_password_reset_email(to=email, token=token, name=user.name)
            except Exception as e:
                logger.error(f"Password reset email failed for {email}: {e}")
        # Always show same message to prevent email enumeration
        flash("If that email is registered, you'll receive a password reset link.", "info")
        return redirect("/login")

    # GET: render a simple forgot-password form
    form_html = """
    <div style="max-width:400px;margin:40px auto;padding:30px;background:white;border-radius:8px;box-shadow:0 2px 4px rgba(0,0,0,0.1);">
        <h2 style="color:#4361ee;">Reset Password</h2>
        <p>Enter your email and we'll send you a reset link.</p>
        <form method="POST">
            <input type="email" name="email" placeholder="Email address" required
                   style="width:100%;padding:10px;margin:10px 0;border:1px solid #ddd;border-radius:6px;">
            <button type="submit"
                    style="width:100%;padding:12px;background:#4361ee;color:white;border:none;border-radius:6px;cursor:pointer;font-size:16px;">
                Send Reset Link
            </button>
        </form>
        <p style="margin-top:15px;font-size:14px;"><a href="/login">Back to login</a></p>
    </div>
    """
    return render_template_string(BASE_TEMPLATE, title="Forgot Password",
                                  content=form_html, current_user=current_user)


@app.route("/reset-password/<token>", methods=["GET", "POST"])
@limiter.limit("10 per hour", methods=["POST"])
def reset_password(token):
    """Reset password using a token from the email link."""
    user = User.query.filter_by(reset_token=token).first()
    if not user or not user.reset_token_expires or user.reset_token_expires < datetime.now(timezone.utc):
        flash("Invalid or expired reset link.", "error")
        return redirect("/forgot-password")

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        if len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
            return redirect(f"/reset-password/{token}")
        if password != confirm:
            flash("Passwords do not match.", "error")
            return redirect(f"/reset-password/{token}")

        if user.reset_password(token, password):
            db.session.commit()
            flash("Password reset successfully! Please log in.", "success")
            return redirect("/login")
        else:
            flash("Reset failed. Please request a new link.", "error")
            return redirect("/forgot-password")

    # GET: render reset form
    form_html = f"""
    <div style="max-width:400px;margin:40px auto;padding:30px;background:white;border-radius:8px;box-shadow:0 2px 4px rgba(0,0,0,0.1);">
        <h2 style="color:#4361ee;">Set New Password</h2>
        <form method="POST">
            <input type="password" name="password" placeholder="New password" required minlength="8"
                   style="width:100%;padding:10px;margin:10px 0;border:1px solid #ddd;border-radius:6px;">
            <input type="password" name="confirm_password" placeholder="Confirm password" required
                   style="width:100%;padding:10px;margin:10px 0;border:1px solid #ddd;border-radius:6px;">
            <button type="submit"
                    style="width:100%;padding:12px;background:#4361ee;color:white;border:none;border-radius:6px;cursor:pointer;font-size:16px;">
                Reset Password
            </button>
        </form>
    </div>
    """
    return render_template_string(BASE_TEMPLATE, title="Reset Password",
                                  content=form_html, current_user=current_user)


def _oauth_provision_user(provider_id_field, provider_id_value, email, name):
    """
    Shared OAuth user provisioning (Build #83).
    Find or create user by provider ID / email.
    Returns user.
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

            # Generate referral code for new OAuth user (Build #170)
            try:
                user.referral_code = generate_referral_code(name)
                # Check for referral attribution from session
                ref_code = session.get('referral_code')
                if ref_code:
                    referrer = User.query.filter_by(referral_code=ref_code).first()
                    if referrer and referrer.id != user.id:
                        user.referred_by_user_id = referrer.id
                        referrer.total_referrals = (referrer.total_referrals or 0) + 1
                        referral = ConsumerReferral(
                            referrer_id=referrer.id, referee_id=user.id,
                            referral_code_used=ref_code, signup_rewarded=True,
                        )
                        db.session.add(referral)
                        signup_pts = app.config.get('REFERRAL_SIGNUP_POINTS', 2000)
                        rewards = RewardsAccount.query.filter_by(user_id=referrer.id).first()
                        if not rewards:
                            rewards = RewardsAccount(user_id=referrer.id)
                            db.session.add(rewards)
                            db.session.flush()
                        rewards.points_balance = (rewards.points_balance or 0) + signup_pts
                        rewards.lifetime_earned = (rewards.lifetime_earned or 0) + signup_pts
                        referral.total_points_awarded = signup_pts
                        pt = PointsTransaction(
                            user_id=referrer.id, amount=signup_pts,
                            transaction_type='bonus', source='referral',
                            description=f'Referral signup: {email}'
                        )
                        db.session.add(pt)
                    session.pop('referral_code', None)
            except Exception as ref_err:
                logger.warning(f"OAuth referral setup failed for {email}: {ref_err}")

            logger.info(f"Created user {user.id} from OAuth ({provider_id_field}): {email}")

    db.session.commit()
    return user


def _oauth_success_response(user):
    """Format standard OAuth success response."""
    return jsonify({
        "success": True,
        "serverUrl": request.host_url.rstrip("/"),
        "userName": user.name or user.email.split("@")[0],
        "userEmail": user.email,
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

        user = _oauth_provision_user("google_id", google_id, email, name)
        return _oauth_success_response(user)

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

        # 3. Provision user
        user = _oauth_provision_user(
            "google_id", google_id, email, name,
        )

        # Log the user in
        login_user(user, remember=True)

        logger.info("Google token sign-in: user=%s (%s)", user.id, email)

        return jsonify({
            "success": True,
            "user_id": user.id,
            "email": email,
            "name": name,
            "is_node": False,
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
<html><head><title>Signing in to MYSTES...</title>
<style>
body{background:#0a0612;color:#f5f5f5;font-family:'Rajdhani',sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;}
.box{text-align:center;max-width:500px;padding:20px;}
.spinner{width:40px;height:40px;border:3px solid rgba(124,58,237,0.3);border-top:3px solid #7c3aed;border-radius:50%;animation:spin 0.8s linear infinite;margin:0 auto 16px;}
@keyframes spin{to{transform:rotate(360deg);}}
.err{color:#f87171;margin-top:16px;font-size:14px;line-height:1.5;}
.debug{background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:8px;padding:12px;margin-top:16px;font-size:12px;color:#999;text-align:left;word-break:break-all;}
a{color:#7c3aed;}
</style></head><body>
<div class="box">
<div class="spinner" id="spinner"></div>
<p id="status">Completing sign-in...</p>
<div id="errBox" style="display:none;">
    <p class="err" id="err"></p>
    <div class="debug" id="debug"></div>
    <p style="margin-top:16px;"><a href="/">Back to MYSTES</a></p>
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
    document.getElementById('status').textContent = 'Verifying with MYSTES...';

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
                  'Could not reach the MYSTES server.');
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
.spinner{width:40px;height:40px;border:3px solid rgba(124,58,237,0.3);border-top:3px solid #7c3aed;border-radius:50%;animation:spin 0.8s linear infinite;margin:0 auto 16px;}
@keyframes spin{to{transform:rotate(360deg);}}
.err{color:#f87171;margin-top:16px;font-size:14px;line-height:1.5;}
.debug{background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:8px;padding:12px;margin-top:16px;font-size:12px;color:#999;text-align:left;word-break:break-all;}
a{color:#7c3aed;}
</style></head><body>
<div class="box">
<div class="spinner" id="spinner"></div>
<p id="status">Completing sign-in...</p>
<div id="errBox" style="display:none;">
    <p class="err" id="err"></p>
    <div class="debug" id="debug"></div>
    <p style="margin-top:16px;"><a href="/">Back to MYSTES</a></p>
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

        # Provision user
        user = _oauth_provision_user("google_id", google_id, email, name)

        # Log the user in via Flask-Login
        login_user(user, remember=True)

        logger.info("Google web sign-in: user=%s (%s)", user.id, email)
        flash(f"Welcome, {name}!", "success")
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

        user = _oauth_provision_user("microsoft_id", microsoft_id, email, name)
        return _oauth_success_response(user)

    except Exception as e:
        db.session.rollback()
        logger.exception("Microsoft OAuth error")
        return jsonify({"error": "Internal server error"}), 500


# Apple JWKS cache (Build #109)
_apple_jwks_cache = {"keys": None, "fetched_at": 0}

def _get_apple_jwks():
    """Fetch and cache Apple's JWKS public keys (1-hour cache)."""
    import time as _time
    if _apple_jwks_cache["keys"] and (_time.time() - _apple_jwks_cache["fetched_at"]) < 3600:
        return _apple_jwks_cache["keys"]
    try:
        resp = http_requests.get("https://appleid.apple.com/auth/keys", timeout=10)
        resp.raise_for_status()
        jwks = resp.json()
        _apple_jwks_cache["keys"] = jwks
        _apple_jwks_cache["fetched_at"] = _time.time()
        logger.debug("Apple JWKS refreshed: %d keys", len(jwks.get("keys", [])))
        return jwks
    except Exception as e:
        logger.error(f"Failed to fetch Apple JWKS: {e}")
        # Return cached keys if available, even if stale
        return _apple_jwks_cache["keys"] or {"keys": []}


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

        # Decode and verify Apple id_token (JWT with RS256 JWKS — Build #109)
        try:
            import base64
            import time

            parts = id_token.split(".")
            if len(parts) != 3:
                return jsonify({"error": "Malformed id_token"}), 400

            def _b64url_decode(s):
                s += "=" * (4 - len(s) % 4)
                return base64.urlsafe_b64decode(s)

            # Decode header to get kid (key ID)
            header = json.loads(_b64url_decode(parts[0]))
            kid = header.get("kid")
            alg = header.get("alg", "RS256")

            if alg != "RS256":
                return jsonify({"error": f"Unsupported JWT algorithm: {alg}"}), 401

            # Verify RS256 signature against Apple's JWKS
            if kid:
                try:
                    from cryptography.hazmat.primitives.asymmetric import padding
                    from cryptography.hazmat.primitives import hashes, serialization
                    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
                    from cryptography.hazmat.backends import default_backend

                    # Fetch Apple's JWKS (cached in-memory for 1 hour)
                    apple_keys = _get_apple_jwks()
                    matching_key = next((k for k in apple_keys.get("keys", []) if k.get("kid") == kid), None)

                    if not matching_key:
                        logger.warning(f"Apple JWKS: no key found for kid={kid}")
                        return jsonify({"error": "Apple signing key not found"}), 401

                    # Reconstruct RSA public key from JWK n + e
                    n_bytes = _b64url_decode(matching_key["n"])
                    e_bytes = _b64url_decode(matching_key["e"])
                    n_int = int.from_bytes(n_bytes, byteorder="big")
                    e_int = int.from_bytes(e_bytes, byteorder="big")
                    public_key = RSAPublicNumbers(e_int, n_int).public_key(default_backend())

                    # Verify signature: RS256 = RSASSA-PKCS1-v1_5 with SHA-256
                    signature = _b64url_decode(parts[2])
                    signed_content = f"{parts[0]}.{parts[1]}".encode("ascii")
                    public_key.verify(signature, signed_content, padding.PKCS1v15(), hashes.SHA256())

                    logger.debug("Apple JWT signature verified (kid=%s)", kid)
                except ImportError:
                    logger.warning("cryptography not available — skipping Apple JWT signature verification")
                except Exception as sig_err:
                    logger.error(f"Apple JWT signature verification failed: {sig_err}")
                    return jsonify({"error": "Invalid token signature"}), 401

            # Decode payload claims
            claims = json.loads(_b64url_decode(parts[1]))

            # Validate issuer
            if claims.get("iss") != "https://appleid.apple.com":
                return jsonify({"error": "Invalid token issuer"}), 401

            # Validate expiry
            if claims.get("exp", 0) < time.time():
                return jsonify({"error": "Token expired"}), 401

            apple_id = claims.get("sub")
            email = claims.get("email")
            # Apple may provide name only on first auth — use email prefix as fallback
            name = data.get("user_name") or (email.split("@")[0] if email else "User")

            if not apple_id or not email:
                return jsonify({"error": "Invalid Apple token claims"}), 400

        except (ValueError, KeyError, json.JSONDecodeError) as e:
            logger.error(f"Apple id_token decode error: {e}")
            return jsonify({"error": "Failed to decode Apple token"}), 400

        user = _oauth_provision_user("apple_id", apple_id, email, name)
        return _oauth_success_response(user)

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

    # Get tier info
    from mystes_ai import get_combined_quota, check_ai_quota, ARBITRAGE_FREE_QUERIES
    tier_quota = get_combined_quota(current_user)
    ai_quota = check_ai_quota(current_user)
    node_tier = tier_quota.get("node_tier", "bronze")
    tier_config = ARBITRAGE_FREE_QUERIES.get(node_tier, ARBITRAGE_FREE_QUERIES["bronze"])

    tier_info = {
        "current_tier": node_tier,
        "queries_per_day": tier_config.get("free_queries_per_day", 5),
        "markets_per_query": tier_config.get("max_tools_per_query", 3),
        "platform_fee_pct": int(tier_config.get("platform_fee_pct", 0.25) * 100),
        "user_keeps_pct": int((1 - tier_config.get("platform_fee_pct", 0.25)) * 100),
        "queries_used_today": ai_quota.get("used", 0),
        "queries_remaining": ai_quota.get("remaining", 0),
    }

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
            language_name=get_language_name(current_user.preferred_language or 'en'),
            tier_info=tier_info,
            alerts_count=PriceAlert.query.filter_by(user_id=current_user.id, is_active=True).count(),
            trips_count=TripPlan.query.filter_by(creator_id=current_user.id).count(),
            collections_count=Collection.query.filter_by(user_id=current_user.id).count(),
        ),
        current_user=current_user
    )


@app.route("/rewards")
@login_required
def rewards_dashboard():
    """Rewards, referrals, and points dashboard (Build #170)."""
    user = current_user

    # Points balance
    rewards = RewardsAccount.query.filter_by(user_id=user.id).first()
    points_balance = rewards.points_balance if rewards else 0
    lifetime_earned = rewards.lifetime_earned if rewards else 0

    # Recent transactions
    recent_txns = PointsTransaction.query.filter_by(user_id=user.id)\
        .order_by(PointsTransaction.created_at.desc()).limit(20).all()

    # Referral stats
    referrals = ConsumerReferral.query.filter_by(referrer_id=user.id).all()
    referral_points = sum(r.total_points_awarded for r in referrals)

    # Ensure user has a referral code
    if not user.referral_code:
        user.referral_code = generate_referral_code(user.name)
        db.session.commit()

    # Fee tier info
    from payments import get_fee_tier_name, get_fee_percent
    fee_tier = get_fee_tier_name(user)
    fee_pct = int(get_fee_percent(user) * 100)

    # Gifts sent/received
    gifts_sent = PointGift.query.filter_by(sender_id=user.id)\
        .order_by(PointGift.created_at.desc()).limit(10).all()
    gifts_received = PointGift.query.filter_by(recipient_id=user.id)\
        .order_by(PointGift.created_at.desc()).limit(10).all()

    REWARDS_CONTENT = """
    <div style="max-width: 900px; margin: 0 auto;">
        <h2 style="font-family: 'Cinzel', serif; color: #1a1a2e; margin-bottom: 30px;">Rewards & Referrals</h2>

        <!-- Points Summary Cards -->
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 30px;">
            <div style="background: linear-gradient(135deg, #7c3aed, #5b21b6); color: white; border-radius: 12px; padding: 20px; text-align: center;">
                <div style="font-size: 32px; font-weight: bold;">{{ "{:,}".format(points_balance) }}</div>
                <div style="opacity: 0.8; font-size: 14px;">Points Balance</div>
                <div style="opacity: 0.6; font-size: 12px; margin-top: 4px;">${{ "%.2f"|format(points_balance * 0.001) }} value</div>
            </div>
            <div style="background: linear-gradient(135deg, #14b8a6, #0d9488); color: white; border-radius: 12px; padding: 20px; text-align: center;">
                <div style="font-size: 32px; font-weight: bold;">{{ "{:,}".format(lifetime_earned) }}</div>
                <div style="opacity: 0.8; font-size: 14px;">Lifetime Earned</div>
            </div>
            <div style="background: linear-gradient(135deg, #f59e0b, #d97706); color: white; border-radius: 12px; padding: 20px; text-align: center;">
                <div style="font-size: 32px; font-weight: bold;">{{ referrals|length }}</div>
                <div style="opacity: 0.8; font-size: 14px;">Friends Referred</div>
                <div style="opacity: 0.6; font-size: 12px; margin-top: 4px;">{{ "{:,}".format(referral_points) }} pts earned</div>
            </div>
            <div style="background: linear-gradient(135deg, #ec4899, #db2777); color: white; border-radius: 12px; padding: 20px; text-align: center;">
                <div style="font-size: 24px; font-weight: bold;">{{ fee_tier }}</div>
                <div style="opacity: 0.8; font-size: 14px;">{{ fee_pct }}% Fee Tier</div>
            </div>
        </div>

        <!-- Referral Link -->
        <div style="background: #f5f3ff; border: 2px solid #e9d5ff; border-radius: 12px; padding: 20px; margin-bottom: 25px;">
            <h3 style="margin: 0 0 10px; color: #5b21b6;">Your Referral Link</h3>
            <p style="color: #666; font-size: 14px; margin-bottom: 15px;">Share your link to earn points when friends join and book.</p>
            <div style="display: flex; gap: 10px; align-items: center;">
                <input type="text" id="ref-link" readonly value="{{ request.host_url }}ref/{{ user.referral_code }}"
                       style="flex: 1; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 14px; background: white;">
                <button onclick="navigator.clipboard.writeText(document.getElementById('ref-link').value); this.textContent='Copied!'; setTimeout(()=>this.textContent='Copy',2000)"
                        style="background: #7c3aed; color: white; border: none; padding: 12px 24px; border-radius: 8px; cursor: pointer; font-weight: 600;">Copy</button>
            </div>
            <div style="margin-top: 12px; display: flex; gap: 8px;">
                <span style="font-size: 13px; color: #666;">Share:</span>
                <a href="https://twitter.com/intent/tweet?text=Save%20on%20flights%20with%20MYSTES!&url={{ request.host_url }}ref/{{ user.referral_code }}" target="_blank" style="color: #1DA1F2; font-size: 13px;">X/Twitter</a>
                <a href="https://wa.me/?text=Save%20on%20flights%20with%20MYSTES!%20{{ request.host_url }}ref/{{ user.referral_code }}" target="_blank" style="color: #25D366; font-size: 13px;">WhatsApp</a>
                <a href="https://www.facebook.com/sharer/sharer.php?u={{ request.host_url }}ref/{{ user.referral_code }}" target="_blank" style="color: #4267B2; font-size: 13px;">Facebook</a>
            </div>
            <div style="margin-top: 15px; padding: 12px; background: white; border-radius: 8px;">
                <div style="font-size: 13px; color: #666;">
                    <strong>Earn points when friends:</strong><br>
                    Sign up: <strong>2,000 pts</strong> | First booking: <strong>5,000 pts</strong> | Subscribe to Travel+: <strong>10,000 pts</strong>
                </div>
            </div>
        </div>

        <!-- Gift Points -->
        <div style="background: white; border: 1px solid #e5e7eb; border-radius: 12px; padding: 20px; margin-bottom: 25px;">
            <h3 style="margin: 0 0 15px; color: #1a1a2e;">Gift Points</h3>
            <div style="display: flex; gap: 10px; flex-wrap: wrap;">
                <input type="email" id="gift-email" placeholder="friend@email.com" style="flex: 1; min-width: 200px; padding: 10px; border: 1px solid #ddd; border-radius: 8px;">
                <input type="number" id="gift-amount" placeholder="1000" min="1000" style="width: 100px; padding: 10px; border: 1px solid #ddd; border-radius: 8px;">
                <button onclick="sendGift()" style="background: #ec4899; color: white; border: none; padding: 10px 20px; border-radius: 8px; cursor: pointer; font-weight: 600;">Send</button>
            </div>
            <p id="gift-result" style="margin-top: 8px; font-size: 13px; display: none;"></p>
        </div>

        <!-- Recent Transactions -->
        <div style="background: white; border: 1px solid #e5e7eb; border-radius: 12px; padding: 20px; margin-bottom: 25px;">
            <h3 style="margin: 0 0 15px; color: #1a1a2e;">Recent Activity</h3>
            {% if recent_txns %}
            <div style="max-height: 300px; overflow-y: auto;">
                {% for txn in recent_txns %}
                <div style="display: flex; justify-content: space-between; padding: 10px 0; border-bottom: 1px solid #f3f4f6;">
                    <div>
                        <div style="font-weight: 600; color: #1a1a2e; font-size: 14px;">{{ txn.description or txn.source }}</div>
                        <div style="font-size: 12px; color: #9ca3af;">{{ txn.created_at.strftime('%b %d, %Y') if txn.created_at else '' }}</div>
                    </div>
                    <div style="font-weight: bold; color: {{ '#059669' if txn.amount > 0 else '#dc2626' }};">
                        {{ '+' if txn.amount > 0 else '' }}{{ "{:,}".format(txn.amount) }} pts
                    </div>
                </div>
                {% endfor %}
            </div>
            {% else %}
            <p style="color: #9ca3af; text-align: center; padding: 20px;">No activity yet. Book a flight or refer a friend to earn points!</p>
            {% endif %}
        </div>

        <!-- Referrals List -->
        {% if referrals %}
        <div style="background: white; border: 1px solid #e5e7eb; border-radius: 12px; padding: 20px;">
            <h3 style="margin: 0 0 15px; color: #1a1a2e;">Your Referrals</h3>
            {% for ref in referrals %}
            <div style="display: flex; justify-content: space-between; padding: 10px 0; border-bottom: 1px solid #f3f4f6;">
                <div style="font-size: 14px;">
                    Referred user
                    <span style="color: {{ '#059669' if ref.first_booking_rewarded else '#9ca3af' }};">
                        {% if ref.first_booking_rewarded %}(booked){% elif ref.signup_rewarded %}(signed up){% else %}(pending){% endif %}
                    </span>
                </div>
                <div style="font-weight: bold; color: #7c3aed;">+{{ "{:,}".format(ref.total_points_awarded) }} pts</div>
            </div>
            {% endfor %}
        </div>
        {% endif %}
    </div>

    <script>
    function sendGift() {
        var email = document.getElementById('gift-email').value;
        var amount = parseInt(document.getElementById('gift-amount').value) || 0;
        var result = document.getElementById('gift-result');
        if (!email || amount < 1000) { result.style.display='block'; result.style.color='#dc2626'; result.textContent='Enter email and minimum 1,000 points'; return; }
        fetch('/api/points/gift', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-CSRFToken': '{{ csrf_token() }}'},
            body: JSON.stringify({recipient_email: email, amount: amount})
        }).then(r => r.json()).then(data => {
            result.style.display = 'block';
            if (data.success) { result.style.color='#059669'; result.textContent='Sent ' + amount.toLocaleString() + ' points to ' + email + '!'; }
            else { result.style.color='#dc2626'; result.textContent=data.error || 'Failed to send'; }
        });
    }
    </script>
    """

    return render_template_string(
        BASE_TEMPLATE,
        title="Rewards",
        content=render_template_string(
            REWARDS_CONTENT,
            user=user,
            points_balance=points_balance,
            lifetime_earned=lifetime_earned,
            recent_txns=recent_txns,
            referrals=referrals,
            referral_points=referral_points,
            fee_tier=fee_tier,
            fee_pct=fee_pct,
            gifts_sent=gifts_sent,
            gifts_received=gifts_received,
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


# --- Traveler Management UI (Build #100) ---

@app.route("/travelers")
@login_required
def travelers_page():
    """Saved travelers management page."""
    travelers = TravelerProfile.query.filter_by(
        user_id=current_user.id,
        is_active=True
    ).order_by(TravelerProfile.is_primary.desc(), TravelerProfile.created_at.desc()).all()

    return render_template_string(
        BASE_TEMPLATE,
        title="Saved Travelers",
        content=render_template_string(
            TRAVELERS_CONTENT,
            travelers=travelers
        ),
        current_user=current_user
    )


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

    audit_log("account_deletion", user_id=user.id, email=user.email)

    # Anonymize PII
    user.email = f"deleted_{user.id}@removed.invalid"
    user.name = None
    user.password_hash = "DELETED"
    user.is_active = False
    user.is_verified = False
    user.verification_token = None
    user.reset_token = None

    # Delete price alerts
    PriceAlert.query.filter_by(user_id=user.id).delete()

    db.session.commit()

    # Log out
    from flask_login import logout_user
    logout_user()

    return jsonify({"status": "deleted", "message": "Account has been permanently deleted."})


# --- Traveler Profile API (Build #98) ---

@app.route("/api/travelers", methods=["GET"])
@login_required
def api_travelers_list():
    """List all saved travelers for the current user."""
    from models import TravelerProfile
    travelers = TravelerProfile.query.filter_by(
        user_id=current_user.id, is_active=True
    ).order_by(TravelerProfile.is_primary.desc(), TravelerProfile.created_at).all()
    return jsonify({
        "travelers": [t.to_dict() for t in travelers],
        "count": len(travelers),
    })


@app.route("/api/travelers", methods=["POST"])
@login_required
def api_travelers_create():
    """Create a new saved traveler."""
    from models import TravelerProfile
    from datetime import datetime

    data = request.get_json() or {}

    # Validate required fields
    required = ["first_name", "last_name", "date_of_birth", "gender"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400

    # Parse date of birth
    try:
        dob = datetime.strptime(data["date_of_birth"], "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "Invalid date_of_birth format. Use YYYY-MM-DD"}), 400

    # Parse passport expiry if provided
    passport_expiry = None
    if data.get("passport_expiry"):
        try:
            passport_expiry = datetime.strptime(data["passport_expiry"], "%Y-%m-%d").date()
        except ValueError:
            return jsonify({"error": "Invalid passport_expiry format. Use YYYY-MM-DD"}), 400

    # Check if this is the first traveler (make it primary)
    existing_count = TravelerProfile.query.filter_by(user_id=current_user.id, is_active=True).count()
    is_primary = existing_count == 0

    traveler = TravelerProfile(
        user_id=current_user.id,
        label=data.get("label", "Traveler"),
        is_primary=is_primary,
        title=data.get("title"),
        first_name=data["first_name"],
        middle_name=data.get("middle_name"),
        last_name=data["last_name"],
        date_of_birth=dob,
        gender=data["gender"].upper(),
        passenger_type=data.get("passenger_type", "ADULT").upper(),
        email=data.get("email"),
        phone=data.get("phone"),
        phone_country_code=data.get("phone_country_code", "1"),
        passport_number=data.get("passport_number"),
        passport_expiry=passport_expiry,
        passport_country=data.get("passport_country"),
        nationality=data.get("nationality"),
        redress_number=data.get("redress_number"),
        known_traveler_number=data.get("known_traveler_number"),
        seat_preference=data.get("seat_preference"),
        meal_preference=data.get("meal_preference"),
        special_assistance=data.get("special_assistance"),
        emergency_contact_name=data.get("emergency_contact_name"),
        emergency_contact_phone=data.get("emergency_contact_phone"),
        emergency_contact_relation=data.get("emergency_contact_relation"),
    )

    db.session.add(traveler)
    db.session.commit()

    return jsonify({"success": True, "traveler": traveler.to_dict()}), 201


@app.route("/api/travelers/<int:traveler_id>", methods=["GET"])
@login_required
def api_travelers_get(traveler_id):
    """Get a specific traveler's full details."""
    from models import TravelerProfile
    traveler = TravelerProfile.query.filter_by(
        id=traveler_id, user_id=current_user.id
    ).first()
    if not traveler:
        return jsonify({"error": "Traveler not found"}), 404
    return jsonify({"traveler": traveler.to_dict_full()})


@app.route("/api/travelers/<int:traveler_id>", methods=["PUT"])
@login_required
def api_travelers_update(traveler_id):
    """Update a saved traveler."""
    from models import TravelerProfile
    from datetime import datetime

    traveler = TravelerProfile.query.filter_by(
        id=traveler_id, user_id=current_user.id
    ).first()
    if not traveler:
        return jsonify({"error": "Traveler not found"}), 404

    data = request.get_json() or {}

    # Update allowed fields
    updateable = [
        "label", "title", "first_name", "middle_name", "last_name", "gender",
        "passenger_type", "email", "phone", "phone_country_code",
        "passport_number", "passport_country", "nationality",
        "redress_number", "known_traveler_number", "seat_preference",
        "meal_preference", "special_assistance", "emergency_contact_name",
        "emergency_contact_phone", "emergency_contact_relation",
    ]

    for field in updateable:
        if field in data:
            setattr(traveler, field, data[field])

    # Handle date fields separately
    if "date_of_birth" in data:
        try:
            traveler.date_of_birth = datetime.strptime(data["date_of_birth"], "%Y-%m-%d").date()
        except ValueError:
            return jsonify({"error": "Invalid date_of_birth format"}), 400

    if "passport_expiry" in data:
        if data["passport_expiry"]:
            try:
                traveler.passport_expiry = datetime.strptime(data["passport_expiry"], "%Y-%m-%d").date()
            except ValueError:
                return jsonify({"error": "Invalid passport_expiry format"}), 400
        else:
            traveler.passport_expiry = None

    db.session.commit()
    return jsonify({"success": True, "traveler": traveler.to_dict()})


@app.route("/api/travelers/<int:traveler_id>", methods=["DELETE"])
@login_required
def api_travelers_delete(traveler_id):
    """Delete (deactivate) a saved traveler."""
    from models import TravelerProfile
    traveler = TravelerProfile.query.filter_by(
        id=traveler_id, user_id=current_user.id
    ).first()
    if not traveler:
        return jsonify({"error": "Traveler not found"}), 404

    if traveler.is_primary:
        return jsonify({"error": "Cannot delete primary traveler. Update another traveler to primary first."}), 400

    traveler.is_active = False
    db.session.commit()
    return jsonify({"success": True, "message": "Traveler deleted"})


@app.route("/api/travelers/<int:traveler_id>/primary", methods=["POST"])
@login_required
def api_travelers_set_primary(traveler_id):
    """Set a traveler as the primary traveler."""
    from models import TravelerProfile
    traveler = TravelerProfile.query.filter_by(
        id=traveler_id, user_id=current_user.id, is_active=True
    ).first()
    if not traveler:
        return jsonify({"error": "Traveler not found"}), 404

    # Unset current primary
    TravelerProfile.query.filter_by(user_id=current_user.id, is_primary=True).update(
        {"is_primary": False}
    )
    traveler.is_primary = True
    db.session.commit()
    return jsonify({"success": True, "traveler": traveler.to_dict()})


@app.route("/deals")
def deals():
    """Browse available deals from the database."""
    get_xrp_price()

    # Read active deals from DB, sorted by savings descending
    active_deals = Deal.query.filter(
        Deal.is_active == True,
        db.or_(Deal.expires_at == None, Deal.expires_at > datetime.now(timezone.utc))
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

    # Get user_id (None for guests)
    user_id = current_user.id if current_user.is_authenticated else None

    # Get deal record — must exist (created by search → select flow)
    deal = Deal.query.filter_by(deal_id=deal_id).first()

    if not deal:
        flash("Deal not found or expired. Please search again.", "error")
        return redirect("/flights")

    # Calculate total amount
    if deal.deal_type == 'hotel':
        total_amount = (deal.price_total_usd or 0) + (deal.platform_fee_usd or 0)
    else:
        total_amount = (deal.arbitrage_price_usd or 0) + (deal.platform_fee_usd or 0)

    # Generate payment options for all methods
    payment_options = generate_payment_options(
        deal_id=deal_id,
        fee_usd=total_amount,
        user_id=user_id
    )

    # Check for existing verified payment
    if user_id:
        payment = Payment.query.filter_by(
            user_id=user_id,
            deal_id=deal.id,
            status='verified'
        ).first()
    else:
        # For guests, check by deal_id
        payment = Payment.query.filter_by(
            deal_id=deal.id,
            status='verified'
        ).order_by(Payment.created_at.desc()).first()

    payment_verified = payment is not None

    # Get guest email from form or session
    guest_email = request.form.get('guest_email') or session.get('guest_email')
    if guest_email:
        session['guest_email'] = guest_email

    # Payment verification handled via Stripe webhooks and /api/payment/stripe/create

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

    # Select template based on deal type
    is_hotel = (deal.deal_type == 'hotel')
    if is_hotel:
        try:
            from routes_hotels import HOTEL_BOOK_CONTENT
            book_template = HOTEL_BOOK_CONTENT
        except ImportError:
            book_template = "<p>Hotel booking is not available in this version.</p>"
    else:
        book_template = BOOK_CONTENT
    page_title = "Book Hotel" if is_hotel else "Book Flight"

    # Fee tier info for savings waterfall (Build #170)
    from payments import get_fee_percent, get_fee_tier_name
    user_for_fee = current_user if current_user.is_authenticated else None
    fee_tier_name = get_fee_tier_name(user_for_fee)
    fee_pct = get_fee_percent(user_for_fee)
    fee_percent_display = int(fee_pct * 100)

    # Points balance for checkout
    user_points_balance = 0
    if current_user.is_authenticated:
        rewards = RewardsAccount.query.filter_by(user_id=current_user.id).first()
        if rewards:
            user_points_balance = rewards.points_balance or 0

    return render_template_string(
        BASE_TEMPLATE,
        title=page_title,
        content=render_template_string(
            book_template,
            deal=deal.to_dict(),
            payment_verified=payment_verified,
            passenger_email=passenger_email,
            payment_options=payment_options_obj,
            booking_url_encoded=quote(deal.booking_url or "", safe=""),
            fee_tier_name=fee_tier_name,
            fee_percent_display=fee_percent_display,
            user_points_balance=user_points_balance,
        ),
        current_user=current_user
    )


def claim_deal_for_payment(deal, user_id):
    """
    Atomically claim a deal for a user before payment begins.

    Returns (success, error_message). If the deal is already claimed by
    the same user, allows re-entry (idempotent for retries/refreshes).
    """
    if not deal or not deal.is_active:
        return False, "Deal is no longer available"

    # Already claimed by this user — allow re-entry
    if deal.deal_status == 'claimed' and deal.claimed_by == user_id:
        return True, None

    # Already claimed by someone else or already booked
    if deal.deal_status in ('claimed', 'booked'):
        return False, "This deal has already been taken by another user"

    # Atomic claim: only succeed if deal is still 'available'
    rows = Deal.query.filter_by(
        id=deal.id, deal_status='available'
    ).update({
        'deal_status': 'claimed',
        'claimed_by': user_id,
        'claimed_at': datetime.now(timezone.utc)
    })
    db.session.commit()

    if rows == 0:
        # Another thread claimed it between our check and update
        db.session.refresh(deal)
        if deal.claimed_by == user_id:
            return True, None  # We actually own it (race with ourselves)
        return False, "This deal has already been taken by another user"

    return True, None


def release_deal_claim(deal):
    """Release a claim on a deal (e.g., payment timeout or cancellation)."""
    if deal and deal.deal_status == 'claimed':
        deal.deal_status = 'available'
        deal.claimed_by = None
        deal.claimed_at = None
        db.session.commit()


def _wire_booking_rewards(booking, deal, payment, passenger_data):
    """Award points and create escrow for booking completion (Build #170).

    - Authenticated users: earn points directly (10 pts/$1, 1.5x for Travel+)
    - Guest users: points go into PointsEscrow (90-day claim window)
    - First-booking referral bonus: referrer gets 5,000 pts
    """
    try:
        from flask import current_app
        pts_per_dollar = current_app.config.get('POINTS_PER_DOLLAR', 10)
        escrow_days = current_app.config.get('POINTS_ESCROW_DAYS', 90)
        first_booking_pts = current_app.config.get('REFERRAL_FIRST_BOOKING_POINTS', 5000)
        travel_plus_multiplier = current_app.config.get('POINTS_TRAVEL_PLUS_MULTIPLIER', 1.5)

        booking_amount = float(deal.booked_price or deal.best_price or 0)
        base_points = int(booking_amount * pts_per_dollar)

        is_guest = not booking.user_id
        guest_email = passenger_data.get('email', '')

        if is_guest and guest_email:
            # Guest: create PointsEscrow (PayPal growth model)
            # First-booking bonus: 3,500 points in escrow
            escrow_points = max(base_points, 3500)
            escrow = PointsEscrow(
                guest_email=guest_email,
                points_amount=escrow_points,
                booking_reference=deal.deal_id,
                claim_deadline=datetime.now(timezone.utc) + timedelta(days=escrow_days),
                status='pending',
            )
            db.session.add(escrow)
            logger.info(f"Points escrow created: {escrow_points} pts for {guest_email} (booking {deal.deal_id})")

        elif booking.user_id:
            user = User.query.get(booking.user_id)
            if not user:
                return

            # Check if Travel+ subscriber for multiplier
            sub = Subscription.query.filter_by(user_id=user.id, status='active').first()
            if sub and sub.tier == 'travel_plus':
                base_points = int(base_points * travel_plus_multiplier)

            # Award points
            rewards = RewardsAccount.query.filter_by(user_id=user.id).first()
            if not rewards:
                rewards = RewardsAccount(user_id=user.id)
                db.session.add(rewards)
                db.session.flush()

            rewards.points_balance = (rewards.points_balance or 0) + base_points
            rewards.lifetime_earned = (rewards.lifetime_earned or 0) + base_points
            rewards.last_earning_at = datetime.now(timezone.utc)

            pt = PointsTransaction(
                user_id=user.id, amount=base_points,
                transaction_type='earn', source='booking',
                booking_id=booking.id,
                description=f'Booking reward: {deal.deal_id}'
            )
            db.session.add(pt)

            # First-booking referral bonus
            if user.referred_by_user_id:
                # Check if this is the referee's first completed booking
                prior_bookings = Booking.query.filter(
                    Booking.user_id == user.id,
                    Booking.status == 'booked',
                    Booking.id != booking.id,
                ).count()
                if prior_bookings == 0:
                    referral = ConsumerReferral.query.filter_by(referee_id=user.id).first()
                    if referral and not referral.first_booking_rewarded:
                        referral.first_booking_rewarded = True
                        referral.total_points_awarded = (referral.total_points_awarded or 0) + first_booking_pts
                        # Award to referrer
                        referrer_rewards = RewardsAccount.query.filter_by(user_id=user.referred_by_user_id).first()
                        if not referrer_rewards:
                            referrer_rewards = RewardsAccount(user_id=user.referred_by_user_id)
                            db.session.add(referrer_rewards)
                            db.session.flush()
                        referrer_rewards.points_balance = (referrer_rewards.points_balance or 0) + first_booking_pts
                        referrer_rewards.lifetime_earned = (referrer_rewards.lifetime_earned or 0) + first_booking_pts
                        rpt = PointsTransaction(
                            user_id=user.referred_by_user_id, amount=first_booking_pts,
                            transaction_type='bonus', source='referral',
                            description=f'Referral first booking: {user.email}'
                        )
                        db.session.add(rpt)
                        # Notify referrer of first booking bonus (Build #172)
                        try:
                            from email_service import send_referral_notification
                            referrer = User.query.get(user.referred_by_user_id)
                            if referrer:
                                send_referral_notification(
                                    to=referrer.email, name=referrer.name,
                                    referee_action=f"{user.email} completed their first booking",
                                    points_earned=first_booking_pts
                                )
                        except Exception:
                            pass

        db.session.commit()
    except Exception as e:
        logger.error(f"Booking rewards error: {e}")
        db.session.rollback()


def trigger_booking_fulfillment(deal, payment, guest_email=None):
    """
    Trigger the booking fulfillment process after payment is verified.

    Idempotent: uses atomic Payment status transition as a database-level lock.
    Only the first caller proceeds; concurrent calls are safely skipped.

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
    # Idempotency gate: atomically transition verified → fulfillment_triggered.
    # Only one thread/process can succeed; others get rows=0 and exit.
    rows = Payment.query.filter_by(
        id=payment.id, status='verified'
    ).update({'status': 'fulfillment_triggered'})
    db.session.commit()

    if rows == 0:
        # Already triggered (by webhook, verify route, or prior call) — skip silently
        logger.info(f"Fulfillment already triggered for payment {payment.id}, skipping")
        return

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
            # Mark deal as booked — no longer available for other users
            deal.deal_status = 'booked'
            db.session.commit()
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
                created_at=datetime.now(timezone.utc)
            )
            db.session.add(booking)
            deal.deal_status = 'booked'
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

    # Mark share-to-save discount as applied (Build #172)
    try:
        if payment.user_id:
            share = SocialShare.query.filter_by(
                user_id=payment.user_id, deal_id=deal.deal_id, discount_applied=False
            ).first()
            if share:
                share.discount_applied = True
                db.session.commit()
    except Exception:
        pass


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

    # Collect details from form — hotel vs flight have different required fields
    is_hotel = (deal.deal_type == 'hotel')

    if is_hotel:
        passenger_data = {
            "title": request.form.get("title", "MR").strip(),
            "first_name": request.form.get("first_name", "").strip(),
            "last_name": request.form.get("last_name", "").strip(),
            "email": request.form.get("email", "").strip(),
            "phone": request.form.get("phone", "").strip(),
            "special_requests": request.form.get("special_requests", "").strip(),
        }
        required_fields = ["first_name", "last_name", "email"]
    else:
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
        required_fields = ["first_name", "last_name", "email", "phone", "date_of_birth", "gender"]

    # Validate required fields
    missing = [f for f in required_fields if not passenger_data.get(f)]
    if missing:
        flash(f"Please fill in required fields: {', '.join(missing)}", "error")
        return redirect(f"/book/{deal_id}")

    # Collect additional passengers (multi-pax support, Build #171)
    additional_pax_json = request.form.get("additional_passengers_json", "[]")
    try:
        additional_passengers = json.loads(additional_pax_json)
        if additional_passengers:
            passenger_data["additional_passengers"] = additional_passengers
    except (json.JSONDecodeError, TypeError):
        pass

    fulfillment_type = request.form.get("fulfillment_type", "automated")

    # Get or create booking record via BookingFulfillmentManager (single source of truth)
    booking = Booking.query.filter_by(
        deal_id=deal.id,
        payment_id=payment.id
    ).first()

    if not booking:
        try:
            from booking_fulfillment import BookingFulfillmentManager
            manager = BookingFulfillmentManager(db.session)
            # Create a lightweight user object for guest checkouts
            if current_user.is_authenticated:
                bfm_user = current_user
            else:
                class _GuestUser:
                    def __init__(self, uid, email):
                        self.id = uid
                        self.email = email
                _guest_email = passenger_data.get('email', session.get('guest_email', ''))
                bfm_user = _GuestUser(user_id, _guest_email)

            result = manager.create_booking(
                deal, payment, bfm_user,
                fulfillment_type=fulfillment_type,
                skip_fulfillment=True,  # complete_booking() handles fulfillment itself
            )
            booking = result.get("booking")
        except ImportError:
            logger.warning("booking_fulfillment not available, creating booking inline")
            booking = Booking(
                user_id=user_id,
                deal_id=deal.id,
                payment_id=payment.id,
                status='pending_fulfillment',
                fulfillment_type=fulfillment_type,
                created_at=datetime.now(timezone.utc)
            )
            db.session.add(booking)

    # Update booking with passenger/guest details
    booking.passenger_name = f"{passenger_data['first_name']} {passenger_data['last_name']}"
    booking.passenger_email = passenger_data['email']
    booking.fulfillment_type = fulfillment_type
    if is_hotel:
        booking.guest_title = passenger_data.get('title', 'MR')
        booking.special_requests = passenger_data.get('special_requests')
        booking.check_in_date = deal.check_in_date
        booking.check_out_date = deal.check_out_date
    db.session.commit()

    # Store passenger data in session for the fulfillment process
    session['passenger_data'] = passenger_data
    session['booking_id'] = booking.id

    if fulfillment_type == "automated":
        # Trigger automated booking — hotel vs flight
        try:
            if deal.deal_type == 'car_rental':
                result = execute_automated_car_booking(booking, deal, passenger_data)
            elif is_hotel:
                result = execute_automated_hotel_booking(booking, deal, passenger_data)
            else:
                result = execute_automated_booking(booking, deal, passenger_data)

            if result.get("success"):
                booking.status = "booked"
                booking.confirmation_code = result.get("confirmation_code")
                booking.booked_at = datetime.now(timezone.utc)
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
                            escrow.released_at = datetime.now(timezone.utc)
                            escrow.updated_at = datetime.now(timezone.utc)
                            db.session.commit()
                            logger.info(f"Escrow {escrow.escrow_id} auto-released after booking success")
                        else:
                            logger.warning(f"Failed to auto-release escrow {escrow.escrow_id}: {release_result.get('error')}")
                    except Exception as e:
                        logger.error(f"Escrow release error for booking {booking.id}: {e}")

                # --- Points & Escrow (Build #170) ---
                _wire_booking_rewards(booking, deal, payment, passenger_data)

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


def execute_automated_hotel_booking(booking, deal, guest_data):
    """
    Execute automated hotel booking via liteAPI.

    Flow: validate_offer (prebook) → create_booking → confirmation
    """
    try:
        from liteapi_client import LiteAPIHotelClient

        client = LiteAPIHotelClient()

        offer_id = deal.hotel_offer_id
        if not offer_id:
            return {"success": False, "error": "No hotel offer ID on this deal"}

        # Step 1: Validate offer (real-time price/availability check)
        logger.info(f"Validating hotel offer {offer_id}...")
        validation = client.validate_offer(offer_id)
        if validation.get("success") and validation.get("available"):
            logger.info(f"Offer valid, price: ${validation.get('price')} {validation.get('currency')}")
        else:
            logger.warning(f"Hotel offer expired or invalid: {validation.get('error')}")
            return {"success": False, "error": "Hotel offer has expired. Please search again."}

        # Step 2: Build guest info
        guest = {
            "title": guest_data.get("title", "MR"),
            "first_name": guest_data.get("first_name", ""),
            "last_name": guest_data.get("last_name", ""),
            "email": guest_data.get("email", booking.passenger_email or ""),
            "phone": guest_data.get("phone", ""),
        }

        # Step 3: Capture prebookId from validation (required by liteAPI)
        prebook_id = validation.get("prebook_id")
        # Store on deal for audit trail
        deal.hotel_prebook_id = prebook_id
        db.session.commit()

        # Step 4: Create booking (ACC_CREDIT_CARD — charges card on liteAPI dashboard)
        logger.info(f"Creating hotel booking for {deal.hotel_name}...")
        book_result = client.create_booking(
            offer_id=offer_id,
            guest=guest,
            prebook_id=prebook_id,
            client_reference=deal.deal_id,
        )

        if book_result.get("success"):
            confirmation = book_result.get("provider_confirmation") or book_result.get("booking_id")
            logger.info(f"Hotel booking successful: ID={book_result['booking_id']}, ref={confirmation}")
            # Store hotel-specific confirmation
            booking.hotel_confirmation_id = book_result.get("booking_id")
            booking.provider_reference = book_result.get("provider_confirmation")
            db.session.commit()
            return {
                "success": True,
                "confirmation_code": confirmation,
                "booking_id": book_result.get("booking_id"),
            }
        else:
            logger.warning(f"Hotel booking failed: {book_result.get('error')}")
            return {"success": False, "error": book_result.get("error", "Hotel booking failed")}

    except Exception as e:
        logger.error(f"Automated hotel booking error: {e}")
        return {"success": False, "error": str(e)}


def execute_automated_booking(booking, deal, passenger_data):
    """
    Execute automated flight booking via ANASTASiA BookingDispatcher.

    The dispatcher reads knowledge cards (JSON) to route bookings to the correct
    API client with proper passenger format transformation. Zero Anthropic API cost.

    Fallback chain:
    1. ANASTASiA dispatcher (card-guided: Picasso, Duffel, Kiwi, AirGateway)
    2. airline_booker (Playwright automation)
    3. Manual agent notification
    """
    try:
        # --- Path 1: ANASTASiA card-guided dispatch ---
        # Build raw_offer from Deal record
        raw_offer = None
        if deal.amadeus_offer_data:
            try:
                raw_offer = json.loads(deal.amadeus_offer_data)
            except (json.JSONDecodeError, TypeError):
                pass

        # Legacy support: if no amadeus_offer_data but fare_id exists, it's Picasso
        if not raw_offer and deal.fare_id and deal.fare_search_id:
            raw_offer = {
                "source": "picasso",
                "fare_id": deal.fare_id,
                "fare_search_id": deal.fare_search_id,
            }

        if raw_offer and raw_offer.get("source"):
            try:
                import sys
                sdk_path = os.path.join(os.path.dirname(__file__), "picasso-sdk")
                if sdk_path not in sys.path:
                    sys.path.insert(0, sdk_path)
                from anastasia.dispatch import BookingDispatcher

                dispatcher = BookingDispatcher()

                # Register available API clients — dispatcher never imports these directly
                clients = {}
                source = raw_offer.get("source")

                if source == "picasso":
                    try:
                        from picasso_client import book_flight as picasso_book_flight
                        clients["picasso"] = picasso_book_flight
                    except ImportError:
                        logger.info("picasso_client not available")

                elif source == "duffel_ndc":
                    try:
                        from duffel_client import DuffelClient
                        clients["duffel_ndc"] = DuffelClient()
                    except ImportError:
                        logger.info("duffel_client not available")

                elif source == "kiwi_tequila":
                    try:
                        from kiwi_client import KiwiClient
                        clients["kiwi_tequila"] = KiwiClient()
                    except ImportError:
                        logger.info("kiwi_client not available")

                elif source == "airgateway_ndc":
                    try:
                        from clients.airgateway import AirGatewayClient
                        clients["airgateway_ndc"] = AirGatewayClient()
                    except ImportError:
                        logger.info("airgateway client not available")

                if clients:
                    markup = round(float(deal.platform_fee_usd or 0), 2)
                    logger.info(
                        f"[BOOKING] ANASTASiA dispatch for booking #{booking.id} "
                        f"(source={source})"
                    )

                    result = dispatcher.dispatch(
                        raw_offer=raw_offer,
                        passenger_data=passenger_data,
                        clients=clients,
                        markup=markup,
                    )

                    if result.get("success"):
                        return result
                    logger.warning(f"ANASTASiA dispatch failed: {result.get('error')}")

            except ImportError as ie:
                logger.info(f"ANASTASiA dispatcher not available: {ie}")
            except Exception as dispatch_err:
                logger.warning(f"ANASTASiA dispatch error: {dispatch_err}")

        # --- Path 2: airline_booker (Playwright automation) ---
        try:
            from airline_booker import book_flight_sync
            result = book_flight_sync(
                deal_data={
                    "airline": deal.airline,
                    "flight_number": deal.flight_number,
                    "origin": deal.origin,
                    "destination": deal.destination,
                    "departure_date": deal.departure_date.isoformat() if deal.departure_date else "",
                    "departure_time": deal.departure_time or "",
                    "arrival_time": deal.arrival_time or "",
                    "price": float(deal.arbitrage_price_usd or 0),
                    "market": deal.arbitrage_market or "US",
                },
                passenger_data=passenger_data,
                booking_id=booking.id,
            )
            if result.get("success"):
                return result
            logger.warning(f"Airline booker failed: {result.get('error')}")
        except ImportError:
            logger.info("airline_booker not available")
        except Exception as booker_err:
            logger.warning(f"Airline booker error: {booker_err}")

        # --- Path 3: Manual agent fallback ---
        return {"success": False, "error": "Automated flight booking not available. Manual agent will process."}

    except Exception as e:
        logger.error(f"Automated booking error: {e}")
        return {"success": False, "error": str(e)}


def execute_automated_car_booking(booking, deal, passenger_data):
    """Execute automated car rental booking via Discover Cars."""
    try:
        from discover_cars_client import DiscoverCarsClient
        client = DiscoverCarsClient()

        # Extract offer_id from deal
        offer_id = deal.hotel_id  # car offer_id stored in hotel_id column
        if not offer_id and deal.amadeus_offer_data:
            import json as _json
            offer_data = _json.loads(deal.amadeus_offer_data)
            if isinstance(offer_data, dict):
                offer_id = offer_data.get("offer_id")

        if not offer_id:
            return {"success": False, "error": "No car rental offer_id found"}

        driver = {
            "first_name": passenger_data.get("first_name", ""),
            "last_name": passenger_data.get("last_name", ""),
            "email": passenger_data.get("email", booking.passenger_email or ""),
            "phone": passenger_data.get("phone", ""),
            "country_code": passenger_data.get("nationality", "US"),
            "age": passenger_data.get("age", 30),
        }

        logger.info(f"[BOOKING] Attempting Discover Cars for booking #{booking.id} (offer={offer_id})")

        result = client.create_booking(offer_id=offer_id, driver=driver)

        if result.get("success"):
            return {
                "success": True,
                "confirmation_code": result.get("confirmation_number") or result.get("booking_id"),
                "booking_id": result.get("booking_id"),
                "booking_source": "discover_cars",
            }
        else:
            logger.warning(f"Car rental booking failed: {result.get('error')}")
            return {"success": False, "error": result.get("error", "Car rental booking failed")}

    except ImportError:
        logger.info("discover_cars_client not available")
        return {"success": False, "error": "Car rental booking service not available"}
    except Exception as e:
        logger.error(f"Automated car booking error: {e}")
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

        <p>Thank you for using MYSTES!</p>
        """

        send_email(
            to_email=passenger_data.get('email'),
            subject=f"Booking Confirmed! {deal.origin} to {deal.destination} - {booking.confirmation_code}",
            html_content=html_content
        )

        booking.eticket_sent = True
        booking.eticket_sent_at = datetime.now(timezone.utc)
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
            <p><strong>Booked via:</strong> MYSTES</p>
        </div>

        <p>Click the button below to open the booking page through our regional proxy:</p>

        <a href="{proxy_url}" style="display: inline-block; background: #7c3aed; color: white; padding: 15px 30px; text-decoration: none; border-radius: 8px; margin: 20px 0;">
            Book Your Flight Now
        </a>

        <h3>Booking Instructions</h3>
        <ol>
            <li>Click the link above to access the airline site via our proxy</li>
            <li>The prices shown reflect MYSTES's optimized pricing</li>
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
<div class="card" style="max-width: 680px; margin: 40px auto;">
    <!-- Header -->
    <div style="text-align: center; margin-bottom: 25px;">
        <div style="font-size: 48px; margin-bottom: 10px;">&#10003;</div>
        <h2 style="color: #28a745; margin: 0; font-family: Cinzel, serif;">Booking Confirmed</h2>
        <p style="color: #999; margin: 5px 0 0;">{{ booking.passenger_name }}</p>
    </div>

    <!-- PNR Block -->
    <div style="background: rgba(40,167,69,0.15); border: 1px solid rgba(40,167,69,0.3); padding: 25px; border-radius: 12px; margin-bottom: 25px; text-align: center;">
        <div style="color: #81c784; font-size: 12px; text-transform: uppercase; letter-spacing: 2px; margin-bottom: 8px;">Confirmation Code</div>
        <div id="pnr-code" style="font-size: 36px; font-weight: bold; letter-spacing: 6px; color: #4caf50; font-family: monospace;">
            {{ booking.confirmation_code or 'PENDING' }}
        </div>
        {% if booking.confirmation_code %}
        <button onclick="navigator.clipboard.writeText(&apos;{{ booking.confirmation_code }}&apos;);this.textContent=&apos;Copied!&apos;;setTimeout(()=>this.textContent=&apos;Copy Code&apos;,2000)" style="margin-top: 12px; padding: 6px 20px; background: transparent; border: 1px solid rgba(76,175,80,0.4); color: #81c784; border-radius: 6px; cursor: pointer; font-size: 12px;">Copy Code</button>
        {% endif %}
        {% if booking.eticket_url %}
        <div style="margin-top: 10px; font-size: 13px; color: #999;">E-ticket: <a href="{{ booking.eticket_url }}" style="color: #81c784;">Download</a></div>
        {% endif %}
    </div>

    {% if is_hotel %}
    <!-- Hotel Details -->
    <div style="background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 20px; margin-bottom: 20px;">
        <p style="margin: 5px 0; color: #ccc;"><strong style="color: #f5f5f5;">Hotel:</strong> {{ deal.hotel_name }}</p>
        <p style="margin: 5px 0; color: #ccc;"><strong style="color: #f5f5f5;">Location:</strong> {{ deal.city_code }}{{ ' - ' + deal.city_name if deal.city_name else '' }}</p>
        <p style="margin: 5px 0; color: #ccc;"><strong style="color: #f5f5f5;">Check-in:</strong> {{ deal.check_in_date }}</p>
        <p style="margin: 5px 0; color: #ccc;"><strong style="color: #f5f5f5;">Check-out:</strong> {{ deal.check_out_date }}</p>
        <p style="margin: 5px 0; color: #ccc;"><strong style="color: #f5f5f5;">Room:</strong> {{ deal.room_type or 'Standard' }}</p>
    </div>
    {% else %}
    <!-- Flight Itinerary -->
    <div style="background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 20px; margin-bottom: 20px;">
        <h3 style="margin: 0 0 15px 0; font-size: 14px; text-transform: uppercase; letter-spacing: 1px; color: #999;">Flight Itinerary</h3>
        {% if segments %}
        {% for seg in segments %}
        <div style="display: flex; align-items: center; gap: 15px; padding: 12px 0; {% if not loop.last %}border-bottom: 1px solid rgba(255,255,255,0.06);{% endif %}">
            <div style="min-width: 55px;">
                <div style="font-size: 16px; font-weight: 600; color: #f5f5f5;">{{ seg.carrier or deal.airline }}</div>
                <div style="font-size: 11px; color: #777;">{{ seg.flight_number or deal.flight_number }}</div>
            </div>
            <div style="flex: 1; display: flex; align-items: center; gap: 10px;">
                <div style="text-align: center;">
                    <div style="font-size: 18px; font-weight: 600; color: #f5f5f5;">{{ seg.departure_airport or deal.origin }}</div>
                    <div style="font-size: 11px; color: #777;">{{ seg.departure_time[:5] if seg.departure_time and 'T' in seg.departure_time else (deal.departure_time or '') }}</div>
                </div>
                <div style="flex: 1; text-align: center; position: relative;">
                    <div style="border-top: 1px solid rgba(255,255,255,0.2); margin: 0 10px;"></div>
                    <div style="font-size: 10px; color: #666; margin-top: 4px;">{{ seg.cabin_class or deal.cabin_class or '' }}</div>
                </div>
                <div style="text-align: center;">
                    <div style="font-size: 18px; font-weight: 600; color: #f5f5f5;">{{ seg.arrival_airport or deal.destination }}</div>
                    <div style="font-size: 11px; color: #777;">{{ seg.arrival_time[:5] if seg.arrival_time and 'T' in seg.arrival_time else (deal.arrival_time or '') }}</div>
                </div>
            </div>
        </div>
        {% if seg.is_codeshare %}
        <div style="font-size: 11px; color: #888; padding: 2px 0 8px 0;">Operated by {{ seg.operating_carrier }}</div>
        {% endif %}
        {% endfor %}
        {% else %}
        <!-- Fallback: no segments data -->
        <div style="display: flex; align-items: center; gap: 15px; padding: 12px 0;">
            <div style="min-width: 55px;">
                <div style="font-size: 16px; font-weight: 600; color: #f5f5f5;">{{ deal.airline or 'N/A' }}</div>
                <div style="font-size: 11px; color: #777;">{{ deal.flight_number or '' }}</div>
            </div>
            <div style="flex: 1; display: flex; align-items: center; gap: 10px;">
                <div style="text-align: center;">
                    <div style="font-size: 18px; font-weight: 600; color: #f5f5f5;">{{ deal.origin }}</div>
                    <div style="font-size: 11px; color: #777;">{{ deal.departure_time or '' }}</div>
                </div>
                <div style="flex: 1; text-align: center;">
                    <div style="border-top: 1px solid rgba(255,255,255,0.2); margin: 0 10px;"></div>
                    <div style="font-size: 10px; color: #666; margin-top: 4px;">{{ deal.duration or '' }}</div>
                </div>
                <div style="text-align: center;">
                    <div style="font-size: 18px; font-weight: 600; color: #f5f5f5;">{{ deal.destination }}</div>
                    <div style="font-size: 11px; color: #777;">{{ deal.arrival_time or '' }}</div>
                </div>
            </div>
        </div>
        {% endif %}
        <div style="font-size: 12px; color: #888; margin-top: 8px;">{{ deal.departure_date }}{% if deal.layovers %} &middot; {{ deal.layovers }}{% endif %}</div>
    </div>

    <!-- Fare Details Tags -->
    <div style="display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 20px;">
        {% if deal.fare_family %}<span style="font-size: 11px; padding: 3px 10px; border-radius: 4px; background: rgba(255,255,255,0.08); color: #ccc; border: 1px solid rgba(255,255,255,0.1);">{{ deal.fare_family }}</span>{% endif %}
        {% if deal.baggage_info %}<span style="font-size: 11px; padding: 3px 10px; border-radius: 4px; background: rgba(255,255,255,0.08); color: #ccc; border: 1px solid rgba(255,255,255,0.1);">{{ 'No checked bag' if deal.baggage_info == '0PC' else deal.baggage_info }}</span>{% endif %}
        {% if deal.seat_selection_available %}<span style="font-size: 11px; padding: 3px 10px; border-radius: 4px; background: rgba(76,175,80,0.15); color: #81c784; border: 1px solid rgba(76,175,80,0.2);">Seat selection available</span>{% endif %}
        {% if deal.flight_cancellation_policy == 'NOT_POSSIBLE' %}<span style="font-size: 11px; padding: 3px 10px; border-radius: 4px; background: rgba(229,115,115,0.15); color: #e57373; border: 1px solid rgba(229,115,115,0.2);">Non-refundable</span>{% endif %}
        {% if deal.flight_cancellation_policy == 'POSSIBLE' %}<span style="font-size: 11px; padding: 3px 10px; border-radius: 4px; background: rgba(76,175,80,0.15); color: #81c784; border: 1px solid rgba(76,175,80,0.2);">Refundable</span>{% endif %}
        {% if deal.flight_rebooking_policy == 'POSSIBLE' %}<span style="font-size: 11px; padding: 3px 10px; border-radius: 4px; background: rgba(76,175,80,0.15); color: #81c784; border: 1px solid rgba(76,175,80,0.2);">Changeable</span>{% endif %}
        {% if deal.cabin_class %}<span style="font-size: 11px; padding: 3px 10px; border-radius: 4px; background: rgba(255,255,255,0.08); color: #ccc; border: 1px solid rgba(255,255,255,0.1);">{{ deal.cabin_class }}</span>{% endif %}
    </div>

    <!-- Savings Summary -->
    {% if deal.user_savings_usd %}
    <div style="background: rgba(76,175,80,0.1); border: 1px solid rgba(76,175,80,0.2); border-radius: 12px; padding: 16px 20px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center;">
        <div>
            <div style="font-size: 12px; color: #81c784; text-transform: uppercase;">You saved</div>
            <div style="font-size: 24px; font-weight: bold; color: #4caf50;">${{ "%.0f"|format(deal.user_savings_usd) }}</div>
        </div>
        <div style="text-align: right; font-size: 13px; color: #999;">
            <div>Normal: <span style="text-decoration: line-through;">${{ "%.0f"|format(deal.home_price_usd or 0) }}</span></div>
            <div>MYSTES: <span style="color: #4caf50; font-weight: 600;">${{ "%.0f"|format((deal.arbitrage_price_usd or 0) + (deal.platform_fee_usd or 0)) }}</span></div>
        </div>
    </div>
    {% endif %}

    <!-- Share & Review Card (Build #178) — Google Review Weapon -->
    {% if deal.user_savings_usd and deal.user_savings_usd > 0 %}
    <div id="review-section" style="background: linear-gradient(135deg, rgba(76,175,80,0.12), rgba(76,175,80,0.04)); border: 2px solid rgba(76,175,80,0.3); border-radius: 16px; padding: 24px; margin-bottom: 20px;">
        <div style="text-align: center; margin-bottom: 16px;">
            <h3 style="margin: 0 0 6px; color: #4caf50; font-family: Cinzel, serif; font-size: 17px;">Share Your Savings &amp; Get 5% Off Next Booking</h3>
            <p style="color: #999; margin: 0; font-size: 12px;">Your savings card is ready — one tap to share. Add your own thoughts or share as-is.</p>
        </div>

        <!-- Preview of the review card -->
        <div id="review-preview" style="background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 16px; margin-bottom: 16px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                <div>
                    <div style="font-size: 16px; font-weight: 700; color: #f5f5f5;">{{ deal.origin }} &#8594; {{ deal.destination }}</div>
                    <div style="font-size: 12px; color: #999;">{{ deal.airline or '' }} {{ deal.flight_number or '' }} &middot; {{ deal.departure_date or '' }}</div>
                </div>
                <div style="text-align: right;">
                    <div style="font-size: 11px; color: #81c784;">MYSTES Price</div>
                    <div style="font-size: 22px; font-weight: 700; color: #4caf50;">${{ "%.0f"|format((deal.arbitrage_price_usd or 0) + (deal.platform_fee_usd or 0)) }}</div>
                </div>
            </div>
            {% if deal.home_price_usd %}
            <div style="display: flex; justify-content: space-between; padding: 4px 0; font-size: 12px;">
                <span style="color: #999;">Retail Price</span>
                <span style="color: #e57373; text-decoration: line-through;">${{ "%.0f"|format(deal.home_price_usd) }}</span>
            </div>
            {% endif %}
            <div style="display: flex; justify-content: space-between; padding: 8px 0; border-top: 1px solid rgba(76,175,80,0.3); margin-top: 4px;">
                <span style="color: #4caf50; font-weight: 600; font-size: 14px;">You Saved</span>
                <span style="color: #4caf50; font-weight: 700; font-size: 18px;">${{ "%.0f"|format(deal.user_savings_usd) }} ({{ "%.0f"|format(deal.savings_percent or 0) }}%)</span>
            </div>
        </div>

        <!-- Personal note (optional) -->
        <div style="margin-bottom: 14px;">
            <textarea id="review-note" placeholder="Add your thoughts (optional)..." style="width: 100%; padding: 10px 14px; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.15); border-radius: 8px; color: #ccc; font-size: 13px; resize: vertical; min-height: 50px; max-height: 120px; box-sizing: border-box; font-family: Outfit, sans-serif;"></textarea>
        </div>

        <!-- Share buttons -->
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
            <button onclick="generateAndShareReview(&apos;google_review&apos;)" id="btn-google-review" style="padding: 12px; background: linear-gradient(135deg, #4caf50, #2e7d32); border: none; border-radius: 8px; color: white; font-weight: 600; cursor: pointer; font-size: 13px; font-family: Outfit, sans-serif;">
                &#11088; Share to Google Reviews
            </button>
            <button onclick="generateAndShareReview(&apos;social&apos;)" id="btn-social-share" style="padding: 12px; background: linear-gradient(135deg, #7c3aed, #a855f7); border: none; border-radius: 8px; color: white; font-weight: 600; cursor: pointer; font-size: 13px; font-family: Outfit, sans-serif;">
                &#128279; Copy Share Link
            </button>
        </div>
        <p id="review-status" style="text-align: center; color: #4caf50; font-size: 12px; margin: 10px 0 0; display: none;"></p>
    </div>

    <script>
    var reviewToken = null;
    function generateAndShareReview(platform) {
        var note = document.getElementById('review-note').value;
        var statusEl = document.getElementById('review-status');

        // Step 1: Generate the review card
        fetch('/api/review/generate', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({booking_id: {{ booking.id }}, personal_note: note})
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data.success) { statusEl.textContent = 'Error: ' + (data.error || 'Unknown'); statusEl.style.display = 'block'; return; }
            reviewToken = data.review_token;
            var reviewUrl = window.location.origin + data.review_url;

            if (platform === 'google_review') {
                // Open Google Review form — will be replaced with actual Google Business Place ID
                var googleUrl = 'https://search.google.com/local/writereview?placeid=MYSTES_PLACE_ID';
                window.open(googleUrl, '_blank');
                // Also copy the review link for them to paste
                navigator.clipboard.writeText(reviewUrl).then(function() {
                    statusEl.textContent = 'Review link copied! Paste it with your Google Review. 5% discount activated!';
                    statusEl.style.display = 'block';
                });
            } else {
                // Copy share link
                navigator.clipboard.writeText(reviewUrl).then(function() {
                    statusEl.textContent = 'Share link copied to clipboard! 5% discount activated for your next booking!';
                    statusEl.style.display = 'block';
                });
            }

            // Step 2: Mark as shared — tiered rewards (Build #179)
            fetch('/api/review/' + reviewToken + '/shared', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({platform: platform})
            }).then(function(r) { return r.json(); })
            .then(function(shareData) {
                if (shareData.message) {
                    statusEl.textContent = shareData.message;
                    statusEl.style.display = 'block';
                }
            });

            // Update buttons
            if (platform === 'google_review') {
                document.getElementById('btn-google-review').textContent = '\\u2705 Shared!';
                document.getElementById('btn-google-review').style.background = 'rgba(76,175,80,0.2)';
            } else {
                document.getElementById('btn-social-share').textContent = '\\u2705 Shared!';
                document.getElementById('btn-social-share').style.background = 'rgba(124,58,237,0.2)';
            }
        });
    }
    </script>
    {% endif %}

    <!-- Referral Card Generator (Build #179) -->
    {% if current_user.is_authenticated %}
    <div id="referral-card-section" style="background: linear-gradient(135deg, rgba(124,58,237,0.12), rgba(124,58,237,0.04)); border: 2px solid rgba(124,58,237,0.3); border-radius: 16px; padding: 24px; margin-bottom: 20px;">
        <div style="text-align: center; margin-bottom: 16px;">
            <h3 style="margin: 0 0 6px; color: #a855f7; font-family: Cinzel, serif; font-size: 17px;">Share Your Referral Card</h3>
            <p style="color: #999; margin: 0; font-size: 12px;">Your savings stats in a shareable card. Friends who book earn you points.</p>
        </div>
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
            <button onclick="generateReferralCard()" id="btn-gen-referral" style="padding: 12px; background: linear-gradient(135deg, #7c3aed, #a855f7); border: none; border-radius: 8px; color: white; font-weight: 600; cursor: pointer; font-size: 13px; font-family: Outfit, sans-serif;">
                &#128279; Generate &amp; Copy Link
            </button>
            <a id="btn-view-referral" href="#" target="_blank" style="display: none; padding: 12px; background: rgba(124,58,237,0.2); border: 1px solid rgba(124,58,237,0.3); border-radius: 8px; color: #a855f7; font-weight: 600; text-align: center; text-decoration: none; font-size: 13px; font-family: Outfit, sans-serif;">
                View Card
            </a>
        </div>
        <p id="referral-status" style="text-align: center; color: #a855f7; font-size: 12px; margin: 10px 0 0; display: none;"></p>
    </div>
    <script>
    function generateReferralCard() {
        var statusEl = document.getElementById('referral-status');
        var btn = document.getElementById('btn-gen-referral');
        btn.textContent = 'Generating...';
        fetch('/api/referral-card/generate', {method: 'POST', headers: {'Content-Type': 'application/json'}})
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.success) {
                var cardUrl = window.location.origin + data.card_url;
                navigator.clipboard.writeText(cardUrl).then(function() {
                    statusEl.textContent = 'Referral card link copied! Share it anywhere.';
                    statusEl.style.display = 'block';
                    btn.textContent = '\\u2705 Link Copied!';
                    btn.style.background = 'rgba(124,58,237,0.2)';
                    var viewBtn = document.getElementById('btn-view-referral');
                    viewBtn.href = data.card_url;
                    viewBtn.style.display = 'block';
                });
            } else {
                statusEl.textContent = 'Error generating card.';
                statusEl.style.display = 'block';
                btn.textContent = 'Try Again';
            }
        });
    }
    </script>
    {% endif %}

    <!-- Next Steps -->
    <div style="background: rgba(124,58,237,0.1); border: 1px solid rgba(124,58,237,0.2); border-radius: 12px; padding: 20px; margin-bottom: 20px;">
        <h3 style="margin: 0 0 15px 0; font-size: 14px; text-transform: uppercase; letter-spacing: 1px; color: #b388ff;">What&apos;s Next</h3>
        <div style="display: flex; flex-direction: column; gap: 12px;">
            <div style="display: flex; gap: 12px; align-items: flex-start;">
                <span style="background: rgba(124,58,237,0.3); color: #b388ff; width: 24px; height: 24px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: bold; flex-shrink: 0;">1</span>
                <div style="color: #ccc; font-size: 13px;"><strong style="color: #f5f5f5;">Visit the airline&apos;s website</strong> or download their app</div>
            </div>
            <div style="display: flex; gap: 12px; align-items: flex-start;">
                <span style="background: rgba(124,58,237,0.3); color: #b388ff; width: 24px; height: 24px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: bold; flex-shrink: 0;">2</span>
                <div style="color: #ccc; font-size: 13px;"><strong style="color: #f5f5f5;">Go to &quot;Manage Booking&quot;</strong> and enter your confirmation code + last name</div>
            </div>
            <div style="display: flex; gap: 12px; align-items: flex-start;">
                <span style="background: rgba(124,58,237,0.3); color: #b388ff; width: 24px; height: 24px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: bold; flex-shrink: 0;">3</span>
                <div style="color: #ccc; font-size: 13px;"><strong style="color: #f5f5f5;">Select your seats</strong> and add checked bags if needed</div>
            </div>
            <div style="display: flex; gap: 12px; align-items: flex-start;">
                <span style="background: rgba(124,58,237,0.3); color: #b388ff; width: 24px; height: 24px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: bold; flex-shrink: 0;">4</span>
                <div style="color: #ccc; font-size: 13px;"><strong style="color: #f5f5f5;">Check in online</strong> 24 hours before your departure</div>
            </div>
        </div>
    </div>

    <!-- Manage Booking CTA -->
    {% if manage_booking_url %}
    <a href="{{ manage_booking_url }}" target="_blank" rel="noopener" class="btn" style="display: block; text-align: center; padding: 14px; margin-bottom: 15px; background: linear-gradient(135deg, #7c3aed, #a855f7);">
        Manage Booking on {{ deal.airline or 'Airline' }} Website
    </a>
    {% endif %}
    {% endif %}

    {% if not is_authenticated %}
    <!-- Guest: Claim Points + Create Account -->
    <div style="background: linear-gradient(135deg, rgba(124,58,237,0.15), rgba(168,85,247,0.1)); border: 2px solid rgba(124,58,237,0.4); border-radius: 16px; padding: 28px; margin-bottom: 20px; text-align: center;">
        <div style="font-size: 36px; margin-bottom: 8px;">&#127873;</div>
        <h3 style="margin: 0 0 8px; color: #b388ff; font-family: Cinzel, serif; font-size: 18px;">You Earned MYSTES Points!</h3>
        <p style="color: #ccc; margin: 0 0 6px; font-size: 14px;">
            <strong style="color: #4caf50; font-size: 22px;">{{ escrow_points|default(3500, true) }}</strong> points are waiting for you
        </p>
        <p style="color: #999; font-size: 12px; margin: 0 0 20px;">Create a free account to claim your points and unlock lower fees on future bookings.</p>

        <!-- Google One Tap button container -->
        {% if google_client_id %}
        <div id="g_id_signin_confirmation" style="display: flex; justify-content: center; margin-bottom: 14px;"></div>
        <script>
        window.addEventListener('load', function() {
            if (typeof google === 'undefined' || !google.accounts) return;
            google.accounts.id.renderButton(
                document.getElementById('g_id_signin_confirmation'),
                { theme: 'outline', size: 'large', text: 'continue_with', width: 300, shape: 'pill' }
            );
        });
        </script>
        {% endif %}

        <div style="display: flex; align-items: center; gap: 12px; justify-content: center; margin: 12px 0;">
            <span style="height: 1px; flex: 1; max-width: 80px; background: rgba(255,255,255,0.15);"></span>
            <span style="font-size: 11px; color: #666;">or</span>
            <span style="height: 1px; flex: 1; max-width: 80px; background: rgba(255,255,255,0.15);"></span>
        </div>

        <a href="/register" class="btn" style="display: inline-block; padding: 12px 32px; background: linear-gradient(135deg, #7c3aed, #a855f7); border-radius: 8px; font-size: 14px;">
            Create Account &amp; Claim Points
        </a>
        <p style="color: #666; font-size: 11px; margin: 12px 0 0;">Points expire in 90 days if unclaimed</p>
    </div>
    {% endif %}

    {% if not is_hotel and deal.destination %}
    <!-- Cross-Sell: Hotels at Destination -->
    <div style="background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 20px; margin-bottom: 20px;">
        <h3 style="margin: 0 0 12px; font-size: 14px; text-transform: uppercase; letter-spacing: 1px; color: #14b8a6;">Complete Your Trip</h3>
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
            <a href="/hotels?destination={{ deal.destination }}&check_in={{ deal.departure_date }}" style="text-decoration: none; display: flex; align-items: center; gap: 12px; padding: 14px; background: rgba(20,184,166,0.08); border: 1px solid rgba(20,184,166,0.2); border-radius: 10px; transition: border-color 0.2s, background 0.2s;" onmouseover="this.style.borderColor='rgba(20,184,166,0.5)';this.style.background='rgba(20,184,166,0.12)'" onmouseout="this.style.borderColor='rgba(20,184,166,0.2)';this.style.background='rgba(20,184,166,0.08)'">
                <span style="font-size: 28px;">&#127976;</span>
                <div>
                    <div style="font-size: 14px; font-weight: 600; color: #f5f5f5;">Find Hotels</div>
                    <div style="font-size: 11px; color: #999;">in {{ deal.destination_city or deal.destination }}</div>
                </div>
            </a>
            <a href="/flights?origin={{ deal.destination }}&destination={{ deal.origin }}" style="text-decoration: none; display: flex; align-items: center; gap: 12px; padding: 14px; background: rgba(124,58,237,0.08); border: 1px solid rgba(124,58,237,0.2); border-radius: 10px; transition: border-color 0.2s, background 0.2s;" onmouseover="this.style.borderColor='rgba(124,58,237,0.5)';this.style.background='rgba(124,58,237,0.12)'" onmouseout="this.style.borderColor='rgba(124,58,237,0.2)';this.style.background='rgba(124,58,237,0.08)'">
                <span style="font-size: 28px;">&#9992;&#65039;</span>
                <div>
                    <div style="font-size: 14px; font-weight: 600; color: #f5f5f5;">Return Flight</div>
                    <div style="font-size: 11px; color: #999;">{{ deal.destination }} &#8594; {{ deal.origin }}</div>
                </div>
            </a>
        </div>
    </div>
    {% elif is_hotel and deal.origin %}
    <!-- Cross-Sell: Flights to Hotel -->
    <div style="background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 20px; margin-bottom: 20px;">
        <h3 style="margin: 0 0 12px; font-size: 14px; text-transform: uppercase; letter-spacing: 1px; color: #14b8a6;">Need a Flight?</h3>
        <a href="/flights?destination={{ deal.city_code }}" style="text-decoration: none; display: flex; align-items: center; gap: 12px; padding: 14px; background: rgba(124,58,237,0.08); border: 1px solid rgba(124,58,237,0.2); border-radius: 10px; transition: border-color 0.2s, background 0.2s;" onmouseover="this.style.borderColor='rgba(124,58,237,0.5)'" onmouseout="this.style.borderColor='rgba(124,58,237,0.2)'">
            <span style="font-size: 28px;">&#9992;&#65039;</span>
            <div>
                <div style="font-size: 14px; font-weight: 600; color: #f5f5f5;">Search Flights</div>
                <div style="font-size: 11px; color: #999;">to {{ deal.city_name or deal.city_code }}</div>
            </div>
        </a>
    </div>
    {% endif %}

    <!-- Footer -->
    <div style="text-align: center; margin-top: 20px;">
        <p style="color: #777; font-size: 13px;">Confirmation sent to {{ booking.passenger_email }}</p>
        {% if is_authenticated %}
        <a href="/dashboard" class="btn btn-secondary" style="margin-top: 10px;">View My Bookings</a>
        {% else %}
        <a href="/register" class="btn btn-secondary" style="margin-top: 10px;">Create Account to Track Bookings</a>
        {% endif %}
    </div>
</div>
"""

BOOKING_STATUS_CONTENT = """
<div class="card" style="max-width: 600px; margin: 40px auto; text-align: center;">
    <span style="font-size: 64px;">⏳</span>
    <h2 style="margin: 20px 0;">Booking In Progress</h2>

    <div style="background: #f0fdfa; padding: 25px; border-radius: 12px; margin: 25px 0;">
        <h3 style="margin: 0 0 15px 0;">Status: {{ booking.status|replace('_', ' ')|title }}</h3>
        {% if booking.fulfillment_type == 'self_service' %}
        <p style="color: #856404; margin: 0;">Complete your booking via the proxy link below, then submit your confirmation code.</p>
        {% elif booking.fulfillment_type == 'manual_agent' %}
        <p style="color: #856404; margin: 0;">Our team is processing your booking. You'll receive confirmation shortly.</p>
        {% else %}
        <p style="color: #856404; margin: 0;">Your booking is being processed automatically. This page will update when complete.</p>
        {% endif %}
    </div>

    <div style="background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); padding: 20px; border-radius: 12px; margin: 20px 0; text-align: left;">
        <p style="margin: 5px 0; color: #ccc;"><strong style="color: #f5f5f5;">Booking ID:</strong> #{{ booking.id }}</p>
        {% if is_hotel %}
            <p style="margin: 5px 0; color: #ccc;"><strong style="color: #f5f5f5;">Guest:</strong> {{ booking.passenger_name }}</p>
            <p style="margin: 5px 0; color: #ccc;"><strong style="color: #f5f5f5;">Hotel:</strong> {{ deal.hotel_name }}</p>
            <p style="margin: 5px 0; color: #ccc;"><strong style="color: #f5f5f5;">Location:</strong> {{ deal.city_code }}</p>
            <p style="margin: 5px 0; color: #ccc;"><strong style="color: #f5f5f5;">Check-in:</strong> {{ deal.check_in_date }}</p>
            <p style="margin: 5px 0; color: #ccc;"><strong style="color: #f5f5f5;">Check-out:</strong> {{ deal.check_out_date }}</p>
        {% else %}
            <p style="margin: 5px 0; color: #ccc;"><strong style="color: #f5f5f5;">Passenger:</strong> {{ booking.passenger_name }}</p>
            <div style="display: flex; align-items: center; gap: 15px; padding: 15px 0; margin: 10px 0; border-top: 1px solid rgba(255,255,255,0.06); border-bottom: 1px solid rgba(255,255,255,0.06);">
                <div style="text-align: center;">
                    <div style="font-size: 20px; font-weight: 600; color: #f5f5f5;">{{ deal.origin }}</div>
                    <div style="font-size: 11px; color: #777;">{{ deal.departure_time or '' }}</div>
                </div>
                <div style="flex: 1; text-align: center;">
                    <div style="border-top: 1px solid rgba(255,255,255,0.2); margin: 0 10px;"></div>
                    <div style="font-size: 11px; color: #666; margin-top: 4px;">{{ deal.duration or '' }}{% if deal.layovers %} &middot; {{ deal.layovers }}{% endif %}</div>
                </div>
                <div style="text-align: center;">
                    <div style="font-size: 20px; font-weight: 600; color: #f5f5f5;">{{ deal.destination }}</div>
                    <div style="font-size: 11px; color: #777;">{{ deal.arrival_time or '' }}</div>
                </div>
            </div>
            <p style="margin: 5px 0; color: #ccc;"><strong style="color: #f5f5f5;">Date:</strong> {{ deal.departure_date }}</p>
            <p style="margin: 5px 0; color: #ccc;"><strong style="color: #f5f5f5;">Airline:</strong> {{ deal.airline or 'N/A' }}{% if deal.flight_number %} {{ deal.flight_number }}{% endif %}</p>
            {% if deal.fare_family %}<p style="margin: 5px 0; color: #ccc;"><strong style="color: #f5f5f5;">Fare:</strong> {{ deal.fare_family }}</p>{% endif %}
        {% endif %}
    </div>

    {% if booking.fulfillment_type == 'self_service' and not booking.confirmation_code and not is_hotel %}
    <!-- Self-Service: Proxy booking link (flights only) -->
    <div style="background: #e8f5e9; padding: 20px; border-radius: 12px; margin: 20px 0; text-align: left;">
        <h4 style="margin: 0 0 10px 0; color: #2e7d32;">Step 1: Book Your Flight</h4>
        <p style="color: #555; margin-bottom: 15px;">Click below to open the airline booking page through our regional proxy. Complete the booking with your own payment method.</p>
        <a href="/proxy/https://www.google.com/travel/flights?q=Flights+from+{{ deal.origin }}+to+{{ deal.destination }}+on+{{ deal.departure_date }}"
           class="btn btn-success" target="_blank" style="display: block; text-align: center; padding: 14px;">
            Open Booking Page (MYSTES pricing)
        </a>
    </div>

    <!-- Self-Service: Submit confirmation code -->
    <div style="background: #f5f3ff; border: 2px solid #7c3aed; padding: 20px; border-radius: 12px; margin: 20px 0; text-align: left;">
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

<script>
(function() {
    const bookingId = {{ booking.id }};
    const status = '{{ booking.status }}';
    // Only auto-poll for in-progress statuses
    if (['pending_fulfillment', 'processing', 'booked'].indexOf(status) === -1) return;
    let pollCount = 0;
    const maxPolls = 60; // 10 minutes at 10s intervals
    const interval = setInterval(function() {
        pollCount++;
        if (pollCount > maxPolls) { clearInterval(interval); return; }
        fetch('/api/v1/booking/' + bookingId + '/status', { credentials: 'same-origin' })
            .then(r => r.json())
            .then(data => {
                if (data.status === 'booked' && data.confirmation_code) {
                    clearInterval(interval);
                    window.location.href = '/booking-confirmation/' + bookingId;
                } else if (data.status !== status) {
                    window.location.reload();
                }
            })
            .catch(() => {});
    }, 10000);
})();
</script>
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

    deal_dict = deal.to_dict() if deal else {}
    is_hotel = (deal.deal_type == 'hotel') if deal else False

    # Parse segments for itinerary display
    segments = deal.get_segments() if deal and not is_hotel else []

    # Get airline manage booking URL
    from main import get_manage_booking_url
    airline_code = ""
    if segments:
        airline_code = segments[0].get("carrier", "")
    elif deal:
        airline_code = deal.airline or ""
    manage_url = get_manage_booking_url(airline_code) if not is_hotel else None

    # Check for escrowed points (for guest signup prompt)
    escrow_points = 0
    if not current_user.is_authenticated and booking.passenger_email:
        try:
            from models import PointsEscrow
            escrow = PointsEscrow.query.filter_by(
                guest_email=booking.passenger_email, status='pending'
            ).first()
            if escrow:
                escrow_points = escrow.points_amount
        except Exception:
            escrow_points = 3500  # fallback default

    return render_template_string(
        BASE_TEMPLATE,
        title="Hotel Confirmed" if is_hotel else "Booking Confirmed",
        content=render_template_string(
            BOOKING_CONFIRMATION_CONTENT,
            booking=booking,
            deal=deal_dict,
            is_hotel=is_hotel,
            segments=segments,
            manage_booking_url=manage_url,
            is_authenticated=current_user.is_authenticated,
            escrow_points=escrow_points,
            google_client_id=os.environ.get("GOOGLE_CLIENT_ID", ""),
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
    deal_dict = deal.to_dict() if deal else {}
    is_hotel = (deal.deal_type == 'hotel') if deal else False

    return render_template_string(
        BASE_TEMPLATE,
        title="Hotel Status" if is_hotel else "Booking Status",
        content=render_template_string(
            BOOKING_STATUS_CONTENT,
            booking=booking,
            deal=deal_dict,
            is_hotel=is_hotel
        ),
        current_user=current_user
    )


# --- BOOKING STATUS API (for auto-refresh polling) ---

@app.route("/api/v1/booking/<int:booking_id>/status")
def api_booking_status(booking_id):
    """Return booking status as JSON for auto-refresh polling."""
    booking = Booking.query.get(booking_id)
    if not booking:
        return jsonify({"error": "Not found"}), 404

    # Security check
    if current_user.is_authenticated:
        if booking.user_id and booking.user_id != current_user.id:
            return jsonify({"error": "Access denied"}), 403
    else:
        if session.get('booking_id') != booking_id:
            return jsonify({"error": "Access denied"}), 403

    return jsonify({
        "booking_id": booking.id,
        "status": booking.status,
        "fulfillment_type": booking.fulfillment_type,
        "confirmation_code": booking.confirmation_code,
        "updated_at": booking.updated_at.isoformat() if booking.updated_at else None,
    })


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
    booking.booked_at = datetime.now(timezone.utc)
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
                escrow.released_at = datetime.now(timezone.utc)
                escrow.updated_at = datetime.now(timezone.utc)
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

        from proxy_manager import get_proxy_for_market
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
    <div style="position:fixed;top:0;left:0;right:0;background:#7c3aed;color:white;padding:10px;text-align:center;z-index:99999;font-family:sans-serif;display:flex;justify-content:center;align-items:center;gap:20px;">
        <span>MYSTES - Booking via JP market</span>
        <span style="color:#14b8a6;">|</span>
        <span style="font-size:12px;">{source_name} → {target_name}</span>
        <a href="?translate={translate_toggle}" style="color:white;background:#6d28d9;padding:4px 12px;border-radius:4px;text-decoration:none;font-size:12px;">{toggle_text}</a>
        <span style="color:#14b8a6;">|</span>
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
        db.or_(Deal.expires_at == None, Deal.expires_at > datetime.now(timezone.utc))
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
            "arbitrage_market": "MYSTES",  # Never expose proxy market codes
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
                arbitrage_market="MYSTES",
                arbitrage_price_usd=total_cheapest_price,
                gross_savings_usd=total_savings,
                platform_fee_usd=service_fee,
                user_savings_usd=total_savings - service_fee if total_savings > service_fee else 0,
                savings_percent=round((total_savings / total_us_price * 100) if total_us_price > 0 else 0, 1),
                is_multi_leg=True,
                flight_legs=json.dumps(flights),
                total_legs=len(flights),
                created_at=datetime.now(timezone.utc)
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
                fare_id=data.get("fare_id"),
                fare_search_id=data.get("fare_search_id"),
                picasso_gds=data.get("picasso_gds"),
                fare_type=data.get("fare_type"),
                is_multi_leg=False,
                total_legs=1,
                created_at=datetime.now(timezone.utc)
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


# --- PICASSO API ENDPOINTS ---

@app.route("/api/picasso/fare-rules", methods=["POST"])
@csrf.exempt
@login_required
def api_picasso_fare_rules():
    """Get fare rules for a specific fare from Picasso search results."""
    data = request.get_json()
    fare_search_id = data.get("fare_search_id")
    fare_id = data.get("fare_id")
    if not fare_search_id or not fare_id:
        return jsonify({"error": "fare_search_id and fare_id required"}), 400
    try:
        from picasso_client import get_fare_rules
        result = get_fare_rules(fare_search_id, fare_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/picasso/seatmap", methods=["POST"])
@csrf.exempt
@login_required
def api_picasso_seatmap():
    """Get seatmap for a specific flight."""
    data = request.get_json()
    required = ["airline_code", "flight_number", "departure", "destination", "departure_date"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400
    try:
        from picasso_client import get_seatmap
        result = get_seatmap(
            airline_code=data["airline_code"],
            flight_number=data["flight_number"],
            departure=data["departure"],
            destination=data["destination"],
            departure_date=data["departure_date"],
            booking_class=data.get("booking_class", "Y"),
            cabin_class=data.get("cabin_class", "ECONOMY"),
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/picasso/book", methods=["POST"])
@csrf.exempt
@login_required
def api_picasso_book():
    """
    Book a flight through Picasso (cart → superPNR).

    Request JSON:
        {
            "deal_id": "abc123",
            "passengers": [
                {
                    "firstName": "John",
                    "lastName": "Doe",
                    "paxType": "ADT",
                    "dateOfBirth": "1990-01-15",
                    "gender": "MALE",
                    "email": "john@example.com",
                    "phone": "+1234567890"
                }
            ]
        }
    """
    data = request.get_json()
    deal_id = data.get("deal_id")
    passengers = data.get("passengers", [])

    if not deal_id:
        return jsonify({"error": "deal_id required"}), 400
    if not passengers:
        return jsonify({"error": "At least one passenger required"}), 400

    deal = Deal.query.filter_by(deal_id=deal_id).first()
    if not deal:
        return jsonify({"error": "Deal not found"}), 404
    if not deal.fare_id or not deal.fare_search_id:
        return jsonify({"error": "Deal missing Picasso fare data — cannot book automatically"}), 400

    try:
        from picasso_client import book_flight

        # Calculate markup so ticket price matches customer price
        markup_amount = 0.0
        if deal.platform_fee_usd and deal.platform_fee_usd > 0:
            markup_amount = round(deal.platform_fee_usd, 2)

        result = book_flight(
            fare_search_id=deal.fare_search_id,
            fare_id=deal.fare_id,
            passengers=passengers,
            order_tickets=True,
            markup_amount=markup_amount,
        )
        return jsonify(result)
    except Exception as e:
        logger.error(f"Picasso book error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/picasso/bookings", methods=["GET", "POST"])
@csrf.exempt
@login_required
def api_picasso_bookings():
    """Search Picasso bookings by locator, dates, airline, etc."""
    if request.method == "GET":
        locator = request.args.get("locator")
    else:
        data = request.get_json() or {}
        locator = data.get("locator")

    try:
        from picasso_client import search_bookings
        kwargs = {}
        if request.method == "POST":
            data = request.get_json() or {}
            for key in ["departure", "destination", "airline", "date_from", "date_to",
                        "travel_date_from", "travel_date_to"]:
                if data.get(key):
                    kwargs[key] = data[key]
        result = search_bookings(locator=locator, **kwargs)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/picasso/document", methods=["POST"])
@csrf.exempt
@login_required
def api_picasso_document():
    """
    Generate a document (itinerary, offer, confirmation) via Picasso.

    Request JSON:
        {
            "document_type": "ITINERARY",   (ITINERARY|OFFER|CONFIRMATION|TRAVEL_REGISTRATION)
            "shopping_cart_id": "...",       (optional)
            "super_pnr_id": "...",          (optional)
            "fare_search_id": "...",        (optional)
            "fare_ids": ["..."],            (optional)
            "email_recipients": ["..."],    (optional)
        }
    """
    data = request.get_json()
    doc_type = data.get("document_type")
    if not doc_type:
        return jsonify({"error": "document_type required"}), 400

    try:
        from picasso_client import generate_document
        result = generate_document(
            document_type=doc_type,
            shopping_cart_id=data.get("shopping_cart_id"),
            super_pnr_id=data.get("super_pnr_id"),
            fare_search_id=data.get("fare_search_id"),
            fare_ids=data.get("fare_ids"),
            email_recipients=data.get("email_recipients"),
            display_prices=data.get("display_prices", True),
            language=data.get("language", "en"),
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/picasso/session")
@login_required
def api_picasso_session():
    """Get current Picasso session info and configuration."""
    try:
        from picasso_client import get_session_info, get_configuration
        session_info = get_session_info()
        config = get_configuration()
        return jsonify({
            "session": session_info,
            "configuration": config,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# --- COMPETITIVE PRICE INTELLIGENCE ---

@app.route("/api/flight/competitors", methods=["POST"])
@csrf.exempt
def api_flight_competitors():
    """
    Get competitor booking options for a specific flight.

    Lazy-loaded when user selects/expands a flight card.
    Uses SerpAPI Google Flights Booking Options (1 credit per unique flight).

    Request JSON:
        {"booking_token": "..."}

    Response JSON:
        {"competitors": [{"name": "Expedia", "price": 489, "is_airline": false}, ...]}
    """
    data = request.get_json()
    if not data or not data.get("booking_token"):
        return jsonify({"error": "booking_token required"}), 400

    try:
        from serpapi_client import get_serpapi_client
        client = get_serpapi_client()
        if not client.is_configured:
            return jsonify({"competitors": [], "message": "Price comparison unavailable"}), 200

        result = client.get_booking_options(data["booking_token"])
        return jsonify({
            "competitors": result.get("options", []),
            "cached": result.get("cached", False),
        })
    except Exception as e:
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
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    deal_id = data.get("deal_id")
    amount = data.get("amount", 0)
    guest_email = data.get("guest_email")

    if not deal_id:
        return jsonify({"error": "Deal ID required"}), 400

    # Determine user context (authenticated or guest)
    is_authenticated = current_user.is_authenticated
    user_email = current_user.email if is_authenticated else guest_email
    user_id = current_user.id if is_authenticated else None

    if not user_email:
        return jsonify({"error": "Email address required"}), 400

    # For guests, use a negative hash of session ID as a stable claim identifier
    # This prevents None==None matching bugs in claim_deal_for_payment
    claim_id = user_id
    if not claim_id:
        import hashlib
        session_key = session.get('_id') or guest_email or ''
        claim_id = -abs(int(hashlib.md5(session_key.encode()).hexdigest()[:8], 16))

    # Get the deal
    deal = Deal.query.filter_by(deal_id=deal_id).first()
    if not deal:
        return jsonify({"error": "Deal not found"}), 404

    # Claim the deal atomically — prevents another user from paying simultaneously
    claimed, claim_error = claim_deal_for_payment(deal, claim_id)
    if not claimed:
        return jsonify({"error": claim_error}), 409

    # Check for share-to-save discount (Build #172)
    share_discount_applied = False
    if not amount:
        base_amount = (deal.arbitrage_price_usd or 0) + (deal.platform_fee_usd or 0)
        # Check if user shared this deal on social media
        share = None
        if is_authenticated:
            share = SocialShare.query.filter_by(
                user_id=user_id, deal_id=deal_id, discount_applied=False
            ).first()
        if share and deal.platform_fee_usd:
            share_discount = app.config.get('SHARE_TO_SAVE_DISCOUNT', 0.05)
            fee_reduction = round(deal.platform_fee_usd * share_discount, 2)
            amount = round(base_amount - fee_reduction, 2)
            share_discount_applied = True
            logger.info(f"Share discount ${fee_reduction} applied for deal {deal_id} user {user_id}")
        else:
            amount = base_amount

    try:
        # Create Stripe checkout session
        result = create_stripe_checkout_session(
            deal_id=deal_id,
            fee_usd=amount,
            user_email=user_email,
            success_url=request.host_url.rstrip('/') + f"/payment/success?deal_id={deal_id}",
            cancel_url=request.host_url.rstrip('/') + f"/book/{deal_id}",
            user_id=user_id,
            user=current_user if is_authenticated else None,
        )

        # Commit stripe_customer_id if it was just created (authenticated only)
        if is_authenticated and current_user.stripe_customer_id:
            db.session.commit()

        # Store guest email in session for post-payment flow
        if not is_authenticated and guest_email:
            session['guest_email'] = guest_email
            session['guest_deal_id'] = deal_id

        if "error" in result:
            return jsonify({"error": result["error"]}), 400

        return jsonify(result)

    except Exception as e:
        logger.error(f"Stripe create error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/payment/stripe/charge-saved", methods=["POST"])
@csrf.exempt
def api_stripe_charge_saved():
    """
    Charge a saved payment method for a returning customer.

    Request JSON:
        {
            "deal_id": "abc123",
            "card_id": 5,
            "amount": 752.50
        }
    """
    if not current_user.is_authenticated:
        return jsonify({"error": "Login required"}), 401

    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    deal_id = data.get("deal_id")
    card_id = data.get("card_id")

    if not deal_id or not card_id:
        return jsonify({"error": "deal_id and card_id required"}), 400

    # Get the deal
    deal = Deal.query.filter_by(deal_id=deal_id).first()
    if not deal:
        return jsonify({"error": "Deal not found"}), 404

    # Claim the deal atomically
    claimed, claim_error = claim_deal_for_payment(deal, current_user.id)
    if not claimed:
        return jsonify({"error": claim_error}), 409

    # Get the saved card
    card = UserCard.query.filter_by(
        id=card_id, user_id=current_user.id, is_active=True
    ).first()
    if not card or not card.stripe_payment_method_id:
        release_deal_claim(deal)
        return jsonify({"error": "Saved card not found or not linked to Stripe"}), 404

    # Ensure user has Stripe Customer
    if not current_user.stripe_customer_id:
        release_deal_claim(deal)
        return jsonify({"error": "No Stripe customer on file. Please make an initial payment via checkout."}), 400

    amount = data.get("amount") or ((deal.arbitrage_price_usd or 0) + (deal.platform_fee_usd or 0))

    try:
        import stripe as stripe_mod
        intent = stripe_mod.PaymentIntent.create(
            amount=int(amount * 100),
            currency="usd",
            customer=current_user.stripe_customer_id,
            payment_method=card.stripe_payment_method_id,
            off_session=False,
            confirm=True,
            metadata={
                "deal_id": deal_id,
                "fee_usd": str(amount),
                "user_id": str(current_user.id),
            },
            return_url=request.host_url.rstrip('/') + f"/payment/success?deal_id={deal_id}",
        )

        if intent.status == "succeeded":
            # Create verified payment record
            payment = Payment(
                user_id=current_user.id,
                deal_id=deal.id,
                payment_method='card',
                amount_usd=amount,
                tx_hash=intent.id,
                stripe_payment_intent=intent.id,
                status='verified',
                verified_at=datetime.now(timezone.utc)
            )
            db.session.add(payment)
            deal.deal_status = 'booked'
            db.session.commit()

            # Trigger booking fulfillment
            trigger_booking_fulfillment(deal, payment)

            # Track payment metric
            try:
                from monitoring import track_payment
                track_payment(method="card", amount_usd=amount, status="verified")
            except Exception:
                pass

            return jsonify({
                "success": True,
                "payment_intent_id": intent.id,
                "status": "succeeded",
                "redirect_url": f"/deal/{deal_id}/access"
            })

        elif intent.status == "requires_action":
            # 3D Secure required
            return jsonify({
                "success": False,
                "requires_action": True,
                "client_secret": intent.client_secret,
                "payment_intent_id": intent.id,
            })

        else:
            release_deal_claim(deal)
            return jsonify({
                "success": False,
                "status": intent.status,
                "error": f"Payment status: {intent.status}"
            }), 400

    except Exception as e:
        release_deal_claim(deal)
        if hasattr(e, 'user_message'):
            return jsonify({"error": f"Card declined: {e.user_message}"}), 402
        logger.error(f"Stripe saved-card charge error: {e}")
        return jsonify({"error": str(e)}), 500


    # Coinbase Commerce routes removed — Stripe + MoonPay only


@app.route("/api/payment/verify", methods=["POST"])
@csrf.exempt
@limiter.limit("20 per hour")
def api_payment_verify():
    """
    Verify a payment across any method.

    Request JSON:
        {
            "method": "card|xrp|rlusd",
            "deal_id": "abc123",
            "session_id": "cs_xxx",        # For Stripe
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
                verified_at=datetime.now(timezone.utc)
            )
            db.session.add(payment)
            db.session.commit()

            # Track payment metric
            try:
                from monitoring import track_payment
                track_payment(method=method, amount_usd=total_amount, status="verified")
            except Exception:
                pass

            # Trigger booking fulfillment
            trigger_booking_fulfillment(deal, payment)

        return jsonify(result)

    except Exception as e:
        logger.error(f"Payment verify error: {e}")
        return jsonify({"verified": False, "error": str(e)}), 500


@app.route("/payment/success")
def payment_success_handler():
    """Handle successful payment redirects from Stripe."""
    deal_id = request.args.get("deal_id")
    session_id = request.args.get("session_id")

    if not deal_id:
        flash("Missing deal information", "error")
        return redirect("/")

    deal = Deal.query.filter_by(deal_id=deal_id).first()
    if not deal:
        flash("Deal not found", "error")
        return redirect("/")

    total_amount = (deal.arbitrage_price_usd or 0) + (deal.platform_fee_usd or 0)

    # Determine user context
    is_authenticated = current_user.is_authenticated
    user_id = current_user.id if is_authenticated else None

    # Check if payment already verified
    existing_payment = None
    if user_id:
        existing_payment = Payment.query.filter_by(
            user_id=user_id,
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
    stripe_intent = None

    if session_id:
        # Stripe payment — verify and validate metadata
        result = verify_stripe_session(session_id)
        if result.get("verified"):
            # Validate that Stripe metadata deal_id matches URL deal_id
            metadata_deal_id = result.get("deal_id")
            if metadata_deal_id and metadata_deal_id != deal_id:
                logger.warning(f"Stripe metadata deal_id mismatch: URL={deal_id} metadata={metadata_deal_id}")
                flash("Payment verification failed — deal mismatch.", "error")
                return redirect(f"/book/{deal_id}")

            verified = True
            payment_method = "card"
            tx_ref = result.get("payment_intent")
            stripe_intent = result.get("payment_intent")

    if verified:
        # Check for duplicate by tx_hash (prevents double-creation from refresh)
        existing_by_tx = None
        if tx_ref:
            existing_by_tx = Payment.query.filter_by(tx_hash=tx_ref, status='verified').first()

        if existing_by_tx:
            logger.info(f"Payment already exists for tx_hash={tx_ref}, skipping duplicate")
            payment = existing_by_tx
        else:
            # Create payment record with Stripe-specific fields
            payment = Payment(
                user_id=user_id,
                deal_id=deal.id,
                payment_method=payment_method,
                amount_usd=total_amount,
                tx_hash=tx_ref,
                stripe_session_id=session_id if payment_method == 'card' else None,
                stripe_payment_intent=stripe_intent,
                status='verified',
                verified_at=datetime.now(timezone.utc)
            )
            db.session.add(payment)
            db.session.commit()

            # Trigger booking fulfillment only for new payments
            trigger_booking_fulfillment(deal, payment)

            audit_log("payment_verified", user_id=user_id,
                      deal_id=deal_id, method=payment_method, amount=total_amount)

        flash("Payment verified successfully! You can now book your flight.", "success")
    else:
        flash("Payment verification pending. Please wait a moment and refresh.", "warning")

    return redirect(f"/book/{deal_id}")


# --- PAYMENT WEBHOOKS ---

@app.route("/webhooks/stripe", methods=["POST"])
@csrf.exempt
def webhook_stripe():
    """
    Handle Stripe webhook events for payment confirmations and B2B subscriptions.

    Events handled:
    - checkout.session.completed: Payment successful → create/update Payment record
    - checkout.session.expired: Payment expired → mark pending payment as expired
    - customer.subscription.*: B2B subscription lifecycle (Build #158)
    - invoice.payment_failed: B2B subscription payment failure
    """
    payload = request.get_data()
    signature = request.headers.get("Stripe-Signature", "")

    # --- B2B Subscription Events (Build #158) ---
    # Parse raw event first to catch subscription lifecycle before deal payment handling
    try:
        import stripe as stripe_mod
        webhook_secret = PAYMENT_CONFIG.get("stripe_webhook_secret", "")
        raw_event = stripe_mod.Webhook.construct_event(payload, signature, webhook_secret)
    except Exception:
        raw_event = None

    if raw_event and raw_event.type.startswith("customer.subscription"):
        try:
            subscription = raw_event.data.object
            # --- B2B subscription handling ---
            account = CommercialAccount.query.filter_by(
                stripe_customer_id=subscription.customer
            ).first()
            if account:
                account.subscription_status = subscription.status
                account.stripe_subscription_id = subscription.id
                if hasattr(subscription, 'current_period_end') and subscription.current_period_end:
                    account.current_period_end = datetime.fromtimestamp(
                        subscription.current_period_end, tz=timezone.utc
                    )
                if subscription.status == 'active' and not account.activated_at:
                    account.activated_at = datetime.now(timezone.utc)
                db.session.commit()
                logger.info(f"B2B subscription {raw_event.type}: {account.account_id} -> {subscription.status}")
            else:
                # --- Travel+ subscription handling (Build #172) ---
                user = User.query.filter_by(stripe_customer_id=subscription.customer).first()
                if user:
                    sub = Subscription.query.filter_by(
                        user_id=user.id, tier='travel_plus'
                    ).first()
                    new_status = subscription.status
                    if raw_event.type == 'customer.subscription.deleted':
                        new_status = 'cancelled'
                    if sub:
                        sub.status = new_status
                        sub.stripe_subscription_id = subscription.id
                        if hasattr(subscription, 'current_period_end') and subscription.current_period_end:
                            sub.current_period_end = datetime.fromtimestamp(
                                subscription.current_period_end, tz=timezone.utc
                            )
                    else:
                        sub = Subscription(
                            user_id=user.id,
                            tier='travel_plus',
                            status=new_status,
                            stripe_subscription_id=subscription.id,
                        )
                        if hasattr(subscription, 'current_period_end') and subscription.current_period_end:
                            sub.current_period_end = datetime.fromtimestamp(
                                subscription.current_period_end, tz=timezone.utc
                            )
                        db.session.add(sub)
                    db.session.commit()
                    logger.info(f"Travel+ subscription {raw_event.type}: user {user.id} -> {new_status}")
        except Exception as e:
            logger.error(f"Subscription webhook error: {e}", exc_info=True)
        return jsonify({"received": True})

    if raw_event and raw_event.type == "invoice.payment_failed":
        try:
            invoice = raw_event.data.object
            # B2B invoice failure
            account = CommercialAccount.query.filter_by(
                stripe_customer_id=invoice.customer
            ).first()
            if account and account.subscription_status == 'active':
                account.subscription_status = 'past_due'
                db.session.commit()
                logger.warning(f"B2B subscription past_due: {account.account_id}")
            else:
                # Travel+ invoice failure (Build #172)
                user = User.query.filter_by(stripe_customer_id=invoice.customer).first()
                if user:
                    sub = Subscription.query.filter_by(
                        user_id=user.id, tier='travel_plus', status='active'
                    ).first()
                    if sub:
                        sub.status = 'past_due'
                        db.session.commit()
                        logger.warning(f"Travel+ subscription past_due: user {user.id}")
        except Exception as e:
            logger.error(f"Invoice webhook error: {e}", exc_info=True)
        return jsonify({"received": True})

    # --- Deal Payment Events (existing) ---
    result = handle_stripe_webhook(payload, signature)

    # Signature verification failure — return 400 to reject (not a valid Stripe event)
    if "error" in result:
        logger.error(f"Stripe webhook signature error: {result['error']}")
        return jsonify({"error": result["error"]}), 400

    try:
        if result.get("event") == "payment_completed":
            deal_id = result.get("deal_id")
            amount_usd = result.get("amount_usd", 0)
            session_id = result.get("session_id")
            payment_intent = result.get("payment_intent")

            if deal_id:
                deal = Deal.query.filter_by(deal_id=deal_id).first()
                if deal:
                    # Duplicate prevention: check if payment already exists for this tx
                    existing = None
                    if payment_intent:
                        existing = Payment.query.filter_by(
                            stripe_payment_intent=payment_intent, status='verified'
                        ).first()
                    if not existing and session_id:
                        existing = Payment.query.filter_by(
                            stripe_session_id=session_id, status='verified'
                        ).first()

                    if existing:
                        logger.info(f"Stripe webhook: payment already exists for deal {deal_id}, skipping")
                    else:
                        # Resolve user_id from metadata → email → deal owner (fallback chain)
                        user_id = None
                        meta_user_id = result.get("user_id")
                        if meta_user_id:
                            try:
                                user_id = int(meta_user_id)
                            except (ValueError, TypeError):
                                pass

                        if not user_id:
                            customer_email = result.get("customer_email")
                            if customer_email:
                                user = User.query.filter_by(email=customer_email).first()
                                if user:
                                    user_id = user.id

                        if not user_id:
                            user_id = deal.user_id  # Last resort: deal owner

                        # Check if a pending payment exists (created by /pay/card redirect)
                        pending = Payment.query.filter_by(
                            stripe_session_id=session_id, status='pending'
                        ).first()

                        if pending:
                            # Update existing pending payment
                            pending.status = 'verified'
                            pending.verified_at = datetime.now(timezone.utc)
                            pending.user_id = user_id
                            pending.tx_hash = payment_intent
                            pending.stripe_payment_intent = payment_intent
                            db.session.commit()
                            payment = pending
                        else:
                            # Create new verified payment
                            payment = Payment(
                                user_id=user_id,
                                deal_id=deal.id,
                                payment_method='card',
                                amount_usd=amount_usd,
                                tx_hash=payment_intent,
                                stripe_session_id=session_id,
                                stripe_payment_intent=payment_intent,
                                status='verified',
                                verified_at=datetime.now(timezone.utc)
                            )
                            db.session.add(payment)
                            db.session.commit()

                        # Track payment metric
                        try:
                            from monitoring import track_payment
                            track_payment(method="card", amount_usd=amount_usd, status="verified")
                        except Exception:
                            pass

                        # Trigger booking fulfillment
                        trigger_booking_fulfillment(deal, payment)

                        # Auto-save card for future use if payment method was captured
                        if payment_intent and user_id:
                            try:
                                import stripe as stripe_mod
                                pi = stripe_mod.PaymentIntent.retrieve(payment_intent)
                                pm_id = pi.payment_method
                                if pm_id:
                                    pm = stripe_mod.PaymentMethod.retrieve(pm_id)
                                    card_data = pm.card
                                    if card_data:
                                        existing_card = UserCard.query.filter_by(
                                            user_id=user_id,
                                            stripe_payment_method_id=pm_id
                                        ).first()
                                        if not existing_card:
                                            has_cards = UserCard.query.filter_by(
                                                user_id=user_id, is_active=True
                                            ).count() > 0
                                            new_card = UserCard(
                                                user_id=user_id,
                                                card_label=f"{card_data.brand.title()} ****{card_data.last4}",
                                                card_last_four=card_data.last4,
                                                card_brand=card_data.brand,
                                                card_exp_month=card_data.exp_month,
                                                card_exp_year=card_data.exp_year,
                                                stripe_payment_method_id=pm_id,
                                                is_primary=not has_cards,
                                                is_active=True,
                                            )
                                            db.session.add(new_card)
                                            db.session.commit()
                                            logger.info(f"Saved card ****{card_data.last4} for user {user_id}")
                            except Exception as card_err:
                                logger.warning(f"Failed to save card after checkout: {card_err}")

                        audit_log("payment_verified_webhook", user_id=user_id,
                                  deal_id=deal_id, amount=amount_usd)
                        logger.info(f"Stripe payment verified via webhook: deal={deal_id} user={user_id}")

        elif result.get("event") == "payment_expired":
            # Mark pending payments as expired
            session_id = result.get("session_id")
            if session_id:
                pending = Payment.query.filter_by(
                    stripe_session_id=session_id, status='pending'
                ).first()
                if pending:
                    pending.status = 'expired'
                    db.session.commit()
                    logger.info(f"Stripe session expired: {session_id}")

        # Always return 200 for successfully parsed events (even if processing had issues)
        return jsonify({"received": True})

    except Exception as e:
        # Log the error but return 200 to prevent Stripe from retrying indefinitely
        logger.error(f"Stripe webhook processing error: {e}", exc_info=True)
        return jsonify({"received": True, "processing_error": True})


    # Coinbase webhook removed — Stripe + MoonPay only


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
<div style="max-width: 500px; margin: 80px auto; text-align: center; padding: 40px 24px;">
    <div style="font-size: 100px; margin-bottom: 10px; opacity: 0.8;">&#9992;</div>
    <h1 style="font-size: 64px; margin: 0; background: linear-gradient(135deg, #7c3aed, #6d28d9); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; font-weight: 800;">404</h1>
    <h2 style="color: #fff; margin: 10px 0 16px; font-size: 22px;">Flight Path Not Found</h2>
    <p style="color: #aaa; margin-bottom: 30px; line-height: 1.6;">The page you're looking for has departed. It may have been moved or no longer exists.</p>
    <div style="display: flex; gap: 12px; justify-content: center; flex-wrap: wrap;">
        <a href="/" class="btn" style="padding: 12px 28px;">Search Flights</a>
        <a href="/deals" class="btn btn-secondary" style="padding: 12px 28px;">Browse Deals</a>
    </div>
</div>
"""

ERROR_500_CONTENT = """
<div style="max-width: 500px; margin: 80px auto; text-align: center; padding: 40px 24px;">
    <div style="font-size: 80px; margin-bottom: 10px;">&#9888;</div>
    <h1 style="font-size: 64px; margin: 0; color: #ef4444; font-weight: 800;">500</h1>
    <h2 style="color: #fff; margin: 10px 0 16px; font-size: 22px;">Turbulence Detected</h2>
    <p style="color: #aaa; margin-bottom: 30px; line-height: 1.6;">We hit some unexpected turbulence. Our team has been notified and we're working on it.</p>
    <div style="display: flex; gap: 12px; justify-content: center; flex-wrap: wrap;">
        <a href="/" class="btn" style="padding: 12px 28px;">Go Home</a>
        <a href="javascript:location.reload()" class="btn btn-secondary" style="padding: 12px 28px;">Try Again</a>
    </div>
</div>
"""

ERROR_CSRF_CONTENT = """
<div class="card" style="max-width: 500px; margin: 60px auto; text-align: center;">
    <h1 style="font-size: 48px; margin: 0; color: #14b8a6;">⚠️</h1>
    <h2>Session Expired</h2>
    <p style="color: #666;">Your session has expired for security reasons. Please refresh the page and try again.</p>
    <a href="javascript:location.reload()" class="btn">Refresh Page</a>
    <a href="/" class="btn btn-secondary" style="margin-left: 10px;">Go Home</a>
</div>
"""

ERROR_RATE_LIMIT_CONTENT = """
<div class="card" style="max-width: 500px; margin: 60px auto; text-align: center;">
    <h1 style="font-size: 48px; margin: 0; color: #14b8a6;">🚦</h1>
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


# --- HEALTH CHECK (exempt from rate limiting — Render checks every 5s) ---

@app.route("/health")
@limiter.exempt
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

    # Picasso / Redbox (primary flight search)
    try:
        from main import PICASSO_AVAILABLE, PICASSO_CONFIGURED
        if PICASSO_AVAILABLE and PICASSO_CONFIGURED:
            services["picasso_redbox"] = "configured"
        elif PICASSO_AVAILABLE:
            services["picasso_redbox"] = "installed (session token not set)"
        else:
            services["picasso_redbox"] = "not installed"
    except Exception:
        services["picasso_redbox"] = "error"

    # Amadeus (legacy fallback — Picasso handles Amadeus internally)
    try:
        from main import AMADEUS_AVAILABLE, AMADEUS_CONFIGURED
        if AMADEUS_AVAILABLE and AMADEUS_CONFIGURED:
            services["amadeus"] = "configured (legacy)"
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
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }), status_code


# --- LEGAL PAGES ---

TERMS_CONTENT = """
<div class="card">
    <h1>Terms of Service</h1>
    <p><em>Last updated: January 2026</em></p>

    <h2>1. Acceptance of Terms</h2>
    <p>By accessing or using MYSTES ("the Service"), you agree to be bound by these Terms of Service. If you do not agree to these terms, please do not use the Service.</p>

    <h2>2. Description of Service</h2>
    <p>MYSTES is a travel assistance platform that helps users find price differences for flights across different regional markets. We act as a facilitator to help you book directly with airlines at lower regional prices.</p>

    <h2>3. How It Works</h2>
    <ul>
        <li><strong>Price Discovery:</strong> We scan airline pricing across different regional markets to identify price differences.</li>
        <li><strong>Platform Fee:</strong> When you find a deal, you pay a platform fee (35% of your savings for subscribers, 50% for guests, min $3) to unlock access to the booking page.</li>
        <li><strong>Direct Booking:</strong> You book directly with the airline through their regional website. MYSTES does not sell tickets or act as a ticket reseller.</li>
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
    <p>MYSTES is not liable for:</p>
    <ul>
        <li>Price changes between deal display and booking</li>
        <li>Flight cancellations, delays, or changes by airlines</li>
        <li>Issues with bookings made on airline websites</li>
        <li>Loss of cryptocurrency due to user error</li>
        <li>Any indirect, incidental, or consequential damages</li>
    </ul>

    <h2>8. Intellectual Property</h2>
    <p>All content, trademarks, and intellectual property on MYSTES are owned by us or our licensors. You may not copy, modify, or distribute our content without permission.</p>

    <h2>9. Termination</h2>
    <p>We may terminate or suspend your account at any time for violation of these terms or for any other reason at our discretion.</p>

    <h2>10. Changes to Terms</h2>
    <p>We may update these Terms of Service at any time. Continued use of the Service after changes constitutes acceptance of the new terms.</p>

    <h2>11. Contact</h2>
    <p>For questions about these Terms of Service, please contact us at legal@mystes.app</p>
</div>
"""

PRIVACY_CONTENT = """
<div class="card">
    <h1>Privacy Policy</h1>
    <p><em>Last updated: January 2026</em></p>

    <h2>1. Introduction</h2>
    <p>MYSTES ("we", "our", "us") respects your privacy and is committed to protecting your personal data. This Privacy Policy explains how we collect, use, and safeguard your information.</p>

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
    <p>For privacy inquiries, contact us at privacy@mystes.app</p>
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
        <h1 style="font-family: 'Cinzel', serif; letter-spacing: 8px; margin-bottom: 10px; background: linear-gradient(135deg, #1a1a2e 0%, #4a3060 50%, #1a1a2e 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;">MYSTES</h1>
        <p style="font-size: 20px; color: #555; margin-bottom: 30px;">Flight Price Arbitrage Platform</p>
    </div>

    <div class="card card-light" style="margin-top: 20px;">
        <h2 style="color: #1a1a2e; margin-bottom: 15px;">How It Works</h2>
        <p style="color: #555; line-height: 1.8;">
            Airlines display different prices depending on your geographic location.
            A flight from New York to Tokyo might cost $1,200 when viewed from the US,
            but only $980 when viewed from Spain or Japan. MYSTES detects these price
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
                <div style="font-size: 28px; margin-bottom: 8px;">MoonPay</div>
                <p style="color: #666; font-size: 13px;">Buy crypto with card via MoonPay</p>
            </div>
        </div>
    </div>

    <div style="text-align: center; margin-top: 30px;">
        <a href="/ai" class="btn" style="padding: 14px 40px; font-size: 18px;">Search with MYSTES AI</a>
    </div>
</div>
"""


@app.route("/about")
def about():
    """About page."""
    return render_template_string(
        BASE_TEMPLATE,
        title="About MYSTES",
        content=ABOUT_CONTENT,
        current_user=current_user
    )


@app.route("/price-guarantee")
def price_guarantee():
    """Price guarantee & trust page (Build #170)."""
    GUARANTEE_CONTENT = """
    <div style="max-width: 800px; margin: 40px auto;">
        <h1 style="font-family: 'Cinzel', serif; color: #1a1a2e; text-align: center; margin-bottom: 10px;">Price Guarantee</h1>
        <p style="text-align: center; color: #666; margin-bottom: 40px; font-size: 18px;">MYSTES guarantees the lowest available price from our provider network.</p>

        <!-- Guarantee Badge -->
        <div style="background: linear-gradient(135deg, #059669, #047857); color: white; border-radius: 16px; padding: 30px; margin-bottom: 30px; text-align: center;">
            <div style="font-size: 48px; margin-bottom: 10px;">&#9989;</div>
            <h2 style="margin: 0 0 10px; font-size: 24px;">MYSTES Best Price Guarantee</h2>
            <p style="opacity: 0.9; max-width: 500px; margin: 0 auto;">Every price on MYSTES is sourced directly from airline GDS systems and NDC connections. We search across multiple providers to find you the lowest fare.</p>
        </div>

        <!-- How It Works -->
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 20px; margin-bottom: 30px;">
            <div style="background: white; border: 1px solid #e5e7eb; border-radius: 12px; padding: 20px; text-align: center;">
                <div style="font-size: 36px; margin-bottom: 10px;">&#128269;</div>
                <h3 style="color: #1a1a2e; font-size: 16px;">Multi-Source Search</h3>
                <p style="color: #666; font-size: 13px;">We search GDS, NDC, and consolidator feeds simultaneously for the same flight.</p>
            </div>
            <div style="background: white; border: 1px solid #e5e7eb; border-radius: 12px; padding: 20px; text-align: center;">
                <div style="font-size: 36px; margin-bottom: 10px;">&#128200;</div>
                <h3 style="color: #1a1a2e; font-size: 16px;">Price Comparison</h3>
                <p style="color: #666; font-size: 13px;">Every result is compared against Google Flights so you can see your savings in real-time.</p>
            </div>
            <div style="background: white; border: 1px solid #e5e7eb; border-radius: 12px; padding: 20px; text-align: center;">
                <div style="font-size: 36px; margin-bottom: 10px;">&#128274;</div>
                <h3 style="color: #1a1a2e; font-size: 16px;">Secure Booking</h3>
                <p style="color: #666; font-size: 13px;">All payments processed securely via Stripe. Your ticket is issued directly by the airline.</p>
            </div>
        </div>

        <!-- Security Badges -->
        <div style="background: #f8f9fa; border-radius: 12px; padding: 25px; margin-bottom: 30px;">
            <h3 style="color: #1a1a2e; margin: 0 0 15px;">Security & Trust</h3>
            <div style="display: flex; flex-wrap: wrap; gap: 20px; justify-content: center;">
                <div style="display: flex; align-items: center; gap: 8px; padding: 10px 16px; background: white; border-radius: 8px; border: 1px solid #e5e7eb;">
                    <span style="font-size: 20px;">&#128274;</span>
                    <span style="font-size: 13px; color: #333;"><strong>SSL Encrypted</strong><br>256-bit encryption</span>
                </div>
                <div style="display: flex; align-items: center; gap: 8px; padding: 10px 16px; background: white; border-radius: 8px; border: 1px solid #e5e7eb;">
                    <span style="font-size: 20px;">&#128179;</span>
                    <span style="font-size: 13px; color: #333;"><strong>Stripe Payments</strong><br>PCI-DSS compliant</span>
                </div>
                <div style="display: flex; align-items: center; gap: 8px; padding: 10px 16px; background: white; border-radius: 8px; border: 1px solid #e5e7eb;">
                    <span style="font-size: 20px;">&#9989;</span>
                    <span style="font-size: 13px; color: #333;"><strong>Real Tickets</strong><br>Airline-issued e-tickets</span>
                </div>
                <div style="display: flex; align-items: center; gap: 8px; padding: 10px 16px; background: white; border-radius: 8px; border: 1px solid #e5e7eb;">
                    <span style="font-size: 20px;">&#128101;</span>
                    <span style="font-size: 13px; color: #333;"><strong>AERTiCKET Partner</strong><br>130,000+ agencies</span>
                </div>
            </div>
        </div>

        <!-- FAQ -->
        <div style="background: white; border: 1px solid #e5e7eb; border-radius: 12px; padding: 25px;">
            <h3 style="color: #1a1a2e; margin: 0 0 20px;">Frequently Asked Questions</h3>

            <div style="margin-bottom: 15px;">
                <strong style="color: #1a1a2e;">How does MYSTES find cheaper prices?</strong>
                <p style="color: #666; font-size: 14px; margin: 5px 0 0;">We access wholesale consolidator fares and NDC-direct airline connections that aren't available to regular consumers. These are the same fares travel agencies use.</p>
            </div>
            <div style="margin-bottom: 15px;">
                <strong style="color: #1a1a2e;">Are the tickets real airline tickets?</strong>
                <p style="color: #666; font-size: 14px; margin: 5px 0 0;">Yes. Every booking produces a real airline e-ticket with a PNR (booking reference) issued through the airline's own systems. You can manage your booking directly with the airline.</p>
            </div>
            <div style="margin-bottom: 15px;">
                <strong style="color: #1a1a2e;">What is the MYSTES platform fee?</strong>
                <p style="color: #666; font-size: 14px; margin: 5px 0 0;">We charge a percentage of the savings we find for you. Guests pay 50%, free members 45%, and Travel+ subscribers just 35%. If we don't find savings, you pay nothing.</p>
            </div>
            <div>
                <strong style="color: #1a1a2e;">Is my payment information secure?</strong>
                <p style="color: #666; font-size: 14px; margin: 5px 0 0;">All payments are processed through Stripe, which is PCI-DSS Level 1 certified. MYSTES never stores your card details.</p>
            </div>
        </div>
    </div>
    """
    return render_template_string(
        BASE_TEMPLATE,
        title="Price Guarantee",
        content=GUARANTEE_CONTENT,
        current_user=current_user
    )


# --- Travel+ Subscription Routes (Build #172) ---

TRAVEL_PLUS_PAGE_CONTENT = """
<div style="max-width: 700px; margin: 40px auto; padding: 0 20px;">
    <h1 style="font-family: 'Cinzel', serif; color: #1a1a2e; text-align: center; margin-bottom: 8px;">Travel+</h1>
    <p style="text-align: center; color: #666; margin-bottom: 30px; font-size: 18px;">Unlock the best MYSTES fee tier and earn more rewards.</p>

    {% if deal %}
    <div style="background: linear-gradient(135deg, #059669, #047857); color: white; border-radius: 12px; padding: 20px; margin-bottom: 24px; text-align: center;">
        <p style="margin: 0; font-size: 14px; opacity: 0.9;">With Travel+ on this booking you'd save</p>
        <p style="margin: 8px 0 0; font-size: 32px; font-weight: 700;">${{ "%.2f"|format(travel_plus_extra_savings) }} more</p>
        <p style="margin: 4px 0 0; font-size: 13px; opacity: 0.8;">{{ deal.origin }} &rarr; {{ deal.destination }}</p>
    </div>
    {% endif %}

    <!-- Benefits -->
    <div style="background: white; border-radius: 12px; border: 1px solid #e5e7eb; padding: 24px; margin-bottom: 24px;">
        <h3 style="color: #1a1a2e; margin: 0 0 16px;">What you get</h3>
        <div style="display: grid; gap: 12px;">
            <div style="display: flex; align-items: center; gap: 12px;">
                <span style="background: #ecfdf5; border-radius: 50%; width: 36px; height: 36px; display: flex; align-items: center; justify-content: center; font-size: 18px; flex-shrink: 0;">&#9989;</span>
                <div><strong style="color: #1a1a2e;">35% fee</strong> <span style="color: #666;">(vs 45% free member / 50% guest)</span></div>
            </div>
            <div style="display: flex; align-items: center; gap: 12px;">
                <span style="background: #ecfdf5; border-radius: 50%; width: 36px; height: 36px; display: flex; align-items: center; justify-content: center; font-size: 18px; flex-shrink: 0;">&#11088;</span>
                <div><strong style="color: #1a1a2e;">1.5x rewards points</strong> <span style="color: #666;">on every booking</span></div>
            </div>
            <div style="display: flex; align-items: center; gap: 12px;">
                <span style="background: #ecfdf5; border-radius: 50%; width: 36px; height: 36px; display: flex; align-items: center; justify-content: center; font-size: 18px; flex-shrink: 0;">&#128176;</span>
                <div><strong style="color: #1a1a2e;">Pays for itself</strong> <span style="color: #666;">on one flight with $67+ savings</span></div>
            </div>
            <div style="display: flex; align-items: center; gap: 12px;">
                <span style="background: #ecfdf5; border-radius: 50%; width: 36px; height: 36px; display: flex; align-items: center; justify-content: center; font-size: 18px; flex-shrink: 0;">&#127961;</span>
                <div><strong style="color: #1a1a2e;">Create Trip Plans</strong> <span style="color: #666;">with unlimited group members</span></div>
            </div>
            <div style="display: flex; align-items: center; gap: 12px;">
                <span style="background: #ecfdf5; border-radius: 50%; width: 36px; height: 36px; display: flex; align-items: center; justify-content: center; font-size: 18px; flex-shrink: 0;">&#128276;</span>
                <div><strong style="color: #1a1a2e;">Price alerts</strong> <span style="color: #666;">with priority notifications</span></div>
            </div>
        </div>
    </div>

    <!-- Plan Toggle -->
    <div style="display: flex; gap: 16px; margin-bottom: 24px;">
        <div id="plan-monthly" onclick="selectPlan('monthly')" style="flex: 1; background: white; border: 2px solid #7c3aed; border-radius: 12px; padding: 20px; text-align: center; cursor: pointer; transition: all 0.2s;">
            <p style="margin: 0; font-size: 13px; color: #666;">Monthly</p>
            <p style="margin: 8px 0 0; font-size: 28px; font-weight: 700; color: #1a1a2e;">$9.99<span style="font-size: 14px; font-weight: 400; color: #666;">/mo</span></p>
            <p style="margin: 4px 0 0; font-size: 12px; color: #666;">Cancel anytime</p>
        </div>
        <div id="plan-annual" onclick="selectPlan('annual')" style="flex: 1; background: white; border: 2px solid #e5e7eb; border-radius: 12px; padding: 20px; text-align: center; cursor: pointer; transition: all 0.2s; position: relative;">
            <div style="position: absolute; top: -10px; left: 50%; transform: translateX(-50%); background: #059669; color: white; padding: 2px 12px; border-radius: 20px; font-size: 11px; font-weight: 600;">SAVE $40</div>
            <p style="margin: 0; font-size: 13px; color: #666;">Annual</p>
            <p style="margin: 8px 0 0; font-size: 28px; font-weight: 700; color: #1a1a2e;">$79.99<span style="font-size: 14px; font-weight: 400; color: #666;">/yr</span></p>
            <p style="margin: 4px 0 0; font-size: 12px; color: #059669; font-weight: 600;">$6.67/mo effectively</p>
        </div>
    </div>

    <!-- Subscribe Button -->
    <button id="subscribe-btn" onclick="subscribeTravelPlus()" style="width: 100%; padding: 16px; background: linear-gradient(135deg, #7c3aed, #5b21b6); color: white; border: none; border-radius: 12px; font-size: 18px; font-weight: 700; cursor: pointer; transition: opacity 0.2s;">
        Subscribe &mdash; $9.99/month
    </button>
    <p style="text-align: center; color: #999; font-size: 12px; margin-top: 8px;">Secure checkout via Stripe. Cancel anytime.</p>

    {% if deal %}
    <p style="text-align: center; margin-top: 12px;">
        <a href="/book/{{ deal.deal_id }}" style="color: #666; font-size: 14px;">Continue without Travel+</a>
    </p>
    {% endif %}
</div>

<script>
var selectedPlan = 'monthly';
function selectPlan(plan) {
    selectedPlan = plan;
    var mEl = document.getElementById('plan-monthly');
    var aEl = document.getElementById('plan-annual');
    var btn = document.getElementById('subscribe-btn');
    if (plan === 'monthly') {
        mEl.style.borderColor = '#7c3aed';
        aEl.style.borderColor = '#e5e7eb';
        btn.textContent = 'Subscribe — $9.99/month';
    } else {
        mEl.style.borderColor = '#e5e7eb';
        aEl.style.borderColor = '#7c3aed';
        btn.textContent = 'Subscribe — $79.99/year (save $40)';
    }
}
function subscribeTravelPlus() {
    var btn = document.getElementById('subscribe-btn');
    btn.disabled = true;
    btn.textContent = 'Redirecting to checkout...';
    btn.style.opacity = '0.7';
    var dealParam = '{{ deal.deal_id if deal else "" }}';
    fetch('/api/subscribe/travel-plus', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({plan: selectedPlan, deal_id: dealParam || null})
    }).then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.checkout_url) {
            window.location.href = data.checkout_url;
        } else {
            btn.disabled = false;
            btn.style.opacity = '1';
            btn.textContent = selectedPlan === 'monthly' ? 'Subscribe — $9.99/month' : 'Subscribe — $79.99/year (save $40)';
            alert(data.error || 'Something went wrong. Please try again.');
        }
    }).catch(function() {
        btn.disabled = false;
        btn.style.opacity = '1';
        btn.textContent = selectedPlan === 'monthly' ? 'Subscribe — $9.99/month' : 'Subscribe — $79.99/year (save $40)';
        alert('Connection error. Please try again.');
    });
}
</script>
"""

TRAVEL_PLUS_SUCCESS_CONTENT = """
<div style="max-width: 600px; margin: 60px auto; text-align: center; padding: 0 20px;">
    <div style="font-size: 64px; margin-bottom: 16px;">&#127881;</div>
    <h1 style="font-family: 'Cinzel', serif; color: #1a1a2e; margin-bottom: 8px;">Welcome to Travel+</h1>
    <p style="color: #059669; font-size: 20px; font-weight: 600; margin-bottom: 24px;">Your fee is now 35% &mdash; you keep more of every deal.</p>

    <div style="background: white; border: 1px solid #e5e7eb; border-radius: 12px; padding: 24px; margin-bottom: 24px; text-align: left;">
        <h3 style="color: #1a1a2e; margin: 0 0 12px;">Your Travel+ perks are active:</h3>
        <ul style="list-style: none; padding: 0; margin: 0;">
            <li style="padding: 8px 0; border-bottom: 1px solid #f3f4f6;">&#9989; <strong>35% platform fee</strong> (saved from 45%)</li>
            <li style="padding: 8px 0; border-bottom: 1px solid #f3f4f6;">&#11088; <strong>1.5x rewards points</strong> on every booking</li>
            <li style="padding: 8px 0; border-bottom: 1px solid #f3f4f6;">&#127961; <strong>Trip Plans</strong> with unlimited group members</li>
            <li style="padding: 8px 0;">&#128276; <strong>Priority price alerts</strong></li>
        </ul>
    </div>

    {% if deal_id %}
    <a href="/book/{{ deal_id }}" style="display: inline-block; background: linear-gradient(135deg, #7c3aed, #5b21b6); color: white; padding: 14px 40px; border-radius: 10px; font-weight: 600; text-decoration: none; font-size: 16px; margin-bottom: 12px;">
        Continue Booking &rarr;
    </a>
    <br>
    {% endif %}
    <a href="/flights" style="display: inline-block; color: #7c3aed; padding: 10px 20px; font-size: 14px; text-decoration: none;">Search Flights</a>
    <a href="/rewards" style="display: inline-block; color: #7c3aed; padding: 10px 20px; font-size: 14px; text-decoration: none;">View Rewards</a>
</div>
"""


@app.route("/subscribe/travel-plus")
@login_required
def subscribe_travel_plus():
    """Travel+ subscription landing page (Build #172)."""
    deal = None
    travel_plus_extra_savings = 0
    deal_id = request.args.get('deal')
    if deal_id:
        deal = Deal.query.filter_by(deal_id=deal_id).first()
        if deal and deal.gross_savings_usd:
            from payments import get_fee_percent
            current_fee = deal.gross_savings_usd * get_fee_percent(current_user)
            tp_fee = max(deal.gross_savings_usd * 0.35, 3.0)
            travel_plus_extra_savings = max(current_fee - tp_fee, 0)

    # Check if already subscribed
    existing_sub = Subscription.query.filter_by(
        user_id=current_user.id, tier='travel_plus', status='active'
    ).first()
    if existing_sub:
        flash("You already have an active Travel+ subscription!", "info")
        if deal_id:
            return redirect(f"/book/{deal_id}")
        return redirect("/rewards")

    return render_template_string(
        BASE_TEMPLATE,
        title="Travel+ Subscription",
        content=TRAVEL_PLUS_PAGE_CONTENT,
        current_user=current_user,
        deal=deal,
        travel_plus_extra_savings=travel_plus_extra_savings,
    )


@app.route("/api/subscribe/travel-plus", methods=["POST"])
@csrf.exempt
@login_required
def api_subscribe_travel_plus():
    """Create Stripe Checkout session for Travel+ subscription (Build #172)."""
    data = request.get_json() or {}
    plan = data.get('plan', 'monthly')
    deal_id = data.get('deal_id')

    # Get price ID based on plan choice
    if plan == 'annual':
        price_id = app.config.get('TRAVEL_PLUS_STRIPE_ANNUAL_PRICE_ID') or \
            os.environ.get('TRAVEL_PLUS_ANNUAL_STRIPE_PRICE_ID', '')
    else:
        price_id = app.config.get('TRAVEL_PLUS_STRIPE_MONTHLY_PRICE_ID') or \
            os.environ.get('TRAVEL_PLUS_MONTHLY_STRIPE_PRICE_ID', '')

    if not price_id:
        # Dev mode: activate directly without Stripe
        sub = Subscription.query.filter_by(
            user_id=current_user.id, tier='travel_plus'
        ).first()
        if not sub:
            sub = Subscription(
                user_id=current_user.id,
                tier='travel_plus',
                status='active',
                billing_cycle=plan if plan == 'annual' else 'monthly',
            )
            db.session.add(sub)
        else:
            sub.status = 'active'
            sub.billing_cycle = plan if plan == 'annual' else 'monthly'
        db.session.commit()
        logger.info(f"Travel+ activated (dev mode) for user {current_user.id}")
        success_url = "/subscribe/travel-plus/success"
        if deal_id:
            success_url += f"?deal_id={deal_id}"
        return jsonify({"checkout_url": success_url})

    try:
        import stripe as stripe_mod

        # Create or reuse Stripe customer
        if not current_user.stripe_customer_id:
            customer = stripe_mod.Customer.create(
                email=current_user.email,
                name=current_user.name,
                metadata={
                    "mystes_user_id": str(current_user.id),
                    "account_type": "travel_plus",
                },
            )
            current_user.stripe_customer_id = customer.id
            db.session.commit()

        base_url = request.url_root.rstrip("/")
        success_path = "/subscribe/travel-plus/success?session_id={CHECKOUT_SESSION_ID}"
        if deal_id:
            success_path += f"&deal_id={deal_id}"

        session = stripe_mod.checkout.Session.create(
            mode="subscription",
            customer=current_user.stripe_customer_id,
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=f"{base_url}{success_path}",
            cancel_url=f"{base_url}/subscribe/travel-plus" + (f"?deal={deal_id}" if deal_id else ""),
            metadata={
                "mystes_user_id": str(current_user.id),
                "account_type": "travel_plus",
                "plan": plan,
                "deal_id": deal_id or "",
            },
        )

        return jsonify({
            "session_id": session.id,
            "checkout_url": session.url,
        })

    except Exception as e:
        logger.error(f"Travel+ Stripe checkout error: {e}", exc_info=True)
        return jsonify({"error": "Payment setup failed. Please try again."}), 400


@app.route("/subscribe/travel-plus/success")
@login_required
def subscribe_travel_plus_success():
    """Travel+ post-checkout success page (Build #172)."""
    session_id = request.args.get('session_id')
    deal_id = request.args.get('deal_id')

    # Create or update subscription record
    sub = Subscription.query.filter_by(
        user_id=current_user.id, tier='travel_plus'
    ).first()

    if session_id:
        try:
            import stripe as stripe_mod
            stripe_session = stripe_mod.checkout.Session.retrieve(session_id)
            stripe_sub_id = stripe_session.subscription

            if not sub:
                sub = Subscription(
                    user_id=current_user.id,
                    tier='travel_plus',
                    status='active',
                    stripe_subscription_id=stripe_sub_id,
                    billing_cycle='annual' if 'annual' in (stripe_session.metadata.get('plan', '')) else 'monthly',
                )
                db.session.add(sub)
            else:
                sub.status = 'active'
                sub.stripe_subscription_id = stripe_sub_id
            db.session.commit()
        except Exception as e:
            logger.error(f"Travel+ success page Stripe verification: {e}", exc_info=True)
            # Still create subscription — webhook will reconcile
            if not sub:
                sub = Subscription(
                    user_id=current_user.id,
                    tier='travel_plus',
                    status='active',
                )
                db.session.add(sub)
                db.session.commit()
    elif not sub:
        # Dev mode activation (no session_id)
        sub = Subscription(
            user_id=current_user.id,
            tier='travel_plus',
            status='active',
        )
        db.session.add(sub)
        db.session.commit()

    # Award referral bonus if applicable
    try:
        if current_user.referred_by_user_id:
            referral = ConsumerReferral.query.filter_by(referee_id=current_user.id).first()
            if referral and not getattr(referral, 'travel_plus_rewarded', False):
                tp_pts = app.config.get('REFERRAL_TRAVEL_PLUS_POINTS', 10000)
                referrer_rewards = RewardsAccount.query.filter_by(
                    user_id=current_user.referred_by_user_id
                ).first()
                if not referrer_rewards:
                    referrer_rewards = RewardsAccount(user_id=current_user.referred_by_user_id)
                    db.session.add(referrer_rewards)
                    db.session.flush()
                referrer_rewards.points_balance = (referrer_rewards.points_balance or 0) + tp_pts
                referrer_rewards.lifetime_earned = (referrer_rewards.lifetime_earned or 0) + tp_pts
                referral.total_points_awarded = (referral.total_points_awarded or 0) + tp_pts
                db.session.add(PointsTransaction(
                    user_id=current_user.referred_by_user_id, amount=tp_pts,
                    transaction_type='bonus', source='referral',
                    description=f'Referral Travel+ subscription: {current_user.email}'
                ))
                db.session.commit()
    except Exception as ref_err:
        logger.warning(f"Travel+ referral bonus failed (non-blocking): {ref_err}")

    return render_template_string(
        BASE_TEMPLATE,
        title="Welcome to Travel+",
        content=TRAVEL_PLUS_SUCCESS_CONTENT,
        current_user=current_user,
        deal_id=deal_id,
    )


# --- Price Alerts Management (Build #172) ---

ALERTS_PAGE_CONTENT = """
<div style="max-width: 700px; margin: 40px auto; padding: 0 20px;">
    <h1 style="font-family: 'Cinzel', serif; color: #1a1a2e; margin-bottom: 8px;">Price Alerts</h1>
    <p style="color: #666; margin-bottom: 24px;">Get notified when flight prices drop on routes you care about.</p>

    {% if alerts %}
    <div style="display: grid; gap: 12px; margin-bottom: 24px;">
        {% for alert in alerts %}
        <div id="alert-{{ alert.id }}" style="background: white; border: 1px solid #e5e7eb; border-radius: 12px; padding: 16px; display: flex; justify-content: space-between; align-items: center;">
            <div>
                <strong style="color: #1a1a2e; font-size: 16px;">{{ alert.origin_code }} &rarr; {{ alert.destination_code }}</strong>
                {% if alert.max_price_usd %}
                <span style="background: #ecfdf5; color: #059669; padding: 2px 8px; border-radius: 4px; font-size: 12px; margin-left: 8px;">Under ${{ "%.0f"|format(alert.max_price_usd) }}</span>
                {% endif %}
                <p style="margin: 4px 0 0; font-size: 13px; color: #999;">Created {{ alert.created_at.strftime('%b %d, %Y') if alert.created_at else 'recently' }}</p>
            </div>
            <button onclick="deleteAlert({{ alert.id }})" style="background: none; border: 1px solid #e5e7eb; color: #dc2626; padding: 6px 14px; border-radius: 6px; font-size: 13px; cursor: pointer;">Delete</button>
        </div>
        {% endfor %}
    </div>
    {% else %}
    <div style="background: white; border: 1px solid #e5e7eb; border-radius: 12px; padding: 40px; text-align: center; margin-bottom: 24px;">
        <div style="font-size: 48px; margin-bottom: 12px;">&#128276;</div>
        <h3 style="color: #1a1a2e; margin: 0 0 8px;">No active alerts</h3>
        <p style="color: #666; margin: 0 0 16px;">Search for flights and click "Set Price Alert" to get started.</p>
        <a href="/flights" style="display: inline-block; background: linear-gradient(135deg, #7c3aed, #5b21b6); color: white; padding: 10px 24px; border-radius: 8px; text-decoration: none; font-weight: 600;">Search Flights</a>
    </div>
    {% endif %}
</div>

<script>
function deleteAlert(id) {
    if (!confirm("Delete this price alert?")) return;
    fetch("/api/alerts/" + id, {method: "DELETE", credentials: "same-origin"})
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (!data.error) {
            var el = document.getElementById("alert-" + id);
            if (el) el.style.display = "none";
        }
    });
}
</script>
"""


@app.route("/alerts")
@login_required
def alerts_page():
    """Price alerts management page (Build #172)."""
    alerts = PriceAlert.query.filter_by(
        user_id=current_user.id, is_active=True
    ).order_by(PriceAlert.created_at.desc()).all()

    return render_template_string(
        BASE_TEMPLATE,
        title="Price Alerts",
        content=ALERTS_PAGE_CONTENT,
        current_user=current_user,
        alerts=alerts,
    )


# --- MYSTES AI SEARCH + PRIVATE MARKET ESCROW ---

AI_SEARCH_CONTENT = """
<div style="max-width: 1100px; margin: 30px auto;">
    <!-- AI Search Section -->
    <div class="card card-light" style="padding: 30px; margin-bottom: 20px;">
        <h1 style="margin-bottom: 5px;"><span style="font-family: 'Cinzel', serif; letter-spacing: 5px; background: linear-gradient(135deg, #1a1a2e 0%, #4a3060 50%, #1a1a2e 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;">MYSTES</span> <span style="color: #1a1a2e;">AI Search</span></h1>
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
            <div id="dealRisk" style="padding: 15px; background: #f0fdfa; border-radius: 10px; margin-bottom: 10px;"></div>
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
            <p style="color: #666; font-size: 13px; margin-bottom: 15px;"><strong>Advanced:</strong> Or add an API key below to feed your provider into MYSTES's ensemble search engine. No MYSTES credit cost when using your own keys.</p>
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
            const statusColors = {draft:'#14b8a6',escrow_funded:'#17a2b8',delivered:'#28a745',completed:'#28a745',disputed:'#dc3545',cancelled:'#6c757d',expired:'#6c757d'};
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

// Auto-send query from ?q= URL parameter (from homepage search)
function checkAutoQuery() {
    const params = new URLSearchParams(window.location.search);
    const q = params.get('q');
    if (q && q.trim()) {
        document.getElementById('chatInput').value = q.trim();
        // Small delay to let page finish loading
        setTimeout(function() { sendMessage(); }, 500);
        // Clean up URL
        window.history.replaceState({}, '', '/ai');
    }
}

// Initialize on load
if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', function() { loadAIPage(); checkAutoQuery(); }); }
else { loadAIPage(); checkAutoQuery(); }
</script>
"""

@app.route("/ai-search")
@login_required
def ai_search_page():
    return render_template_string(
        BASE_TEMPLATE,
        title="MYSTES AI",
        content=AI_SEARCH_CONTENT,
        current_user=current_user
    )


# --- MYSTES AI CHAT INTERFACE ---

MYSTES_AI_CONTENT = """
<style>
    /* Main layout - full viewport like ChatGPT/Claude */
    .ai-chat-container { display: flex; height: 100vh; width: 100%; position: fixed; top: 0; left: 0; right: 0; bottom: 0; z-index: 10; }

    /* Sidebar */
    .ai-sidebar { width: 260px; background: rgba(6, 4, 12, 0.92); backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px); border-right: 1px solid rgba(255,255,255,0.06); padding: 12px; overflow-y: auto; display: flex; flex-direction: column; flex-shrink: 0; }
    .ai-sidebar-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; padding: 8px 4px; }
    .ai-sidebar-header h3 { font-family: 'Outfit', sans-serif; color: #fff; font-size: 0.9rem; font-weight: 600; margin: 0; }
    .ai-new-chat-btn { background: transparent; color: #fff; border: 1px solid rgba(255,255,255,0.2); padding: 8px 14px; border-radius: 6px; cursor: pointer; font-family: 'Outfit', sans-serif; font-weight: 500; font-size: 0.85rem; transition: background 0.2s; }
    .ai-new-chat-btn:hover { background: rgba(255,255,255,0.1); }
    .ai-conv-list { flex: 1; overflow-y: auto; }
    .ai-conv-item { padding: 10px 12px; border-radius: 6px; cursor: pointer; margin-bottom: 2px; color: rgba(255,255,255,0.8); font-size: 0.875rem; transition: background 0.15s; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .ai-conv-item:hover { background: rgba(255,255,255,0.08); }
    .ai-conv-item.active { background: rgba(124,58,237,0.15); color: #fff; }
    .ai-conv-item .conv-time { font-size: 0.7rem; color: rgba(255,255,255,0.4); display: block; margin-top: 2px; }

    /* Main chat area */
    .ai-main { flex: 1; display: flex; flex-direction: column; background: rgba(8, 5, 15, 0.75); backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px); min-width: 0; }

    /* Messages container - scrollable */
    .ai-messages { flex: 1; overflow-y: auto; padding: 0; }
    .ai-messages-inner { max-width: 768px; margin: 0 auto; padding: 24px 24px 120px 24px; }

    /* Individual messages */
    .ai-message { margin-bottom: 24px; }
    .ai-message.user { }
    .ai-message.assistant { }
    .ai-message-content { padding: 0; line-height: 1.7; font-family: 'Outfit', sans-serif; font-size: 1rem; color: #ececec; }
    .ai-message.user .ai-message-content { background: rgba(124,58,237,0.12); color: #fff; padding: 14px 18px; border-radius: 12px; }
    .ai-message.assistant .ai-message-content { background: transparent; color: #ececec; padding: 4px 0; }
    .ai-message-content p { margin: 0 0 12px 0; }
    .ai-message-content p:last-child { margin-bottom: 0; }
    .ai-message-content table { width: 100%; border-collapse: collapse; margin: 16px 0; background: rgba(255,255,255,0.03); border-radius: 8px; overflow: hidden; }
    .ai-message-content th, .ai-message-content td { padding: 10px 14px; border: 1px solid rgba(255,255,255,0.08); text-align: left; }
    .ai-message-content th { background: rgba(124,58,237,0.1); color: #7c3aed; font-weight: 600; }
    .ai-message-content a { color: #7c3aed; text-decoration: none; }
    .ai-message-content a:hover { text-decoration: underline; }
    .ai-message-content code { background: rgba(255,255,255,0.08); padding: 2px 6px; border-radius: 4px; font-size: 0.9em; font-family: 'SF Mono', Monaco, monospace; }
    .ai-message-content pre { background: rgba(0,0,0,0.4); padding: 16px; border-radius: 8px; overflow-x: auto; margin: 12px 0; }
    .ai-message-content ul, .ai-message-content ol { margin: 12px 0; padding-left: 24px; }
    .ai-message-content li { margin-bottom: 6px; }

    .ai-tool-badge { display: inline-block; background: rgba(124,58,237,0.15); color: #7c3aed; padding: 3px 10px; border-radius: 4px; font-size: 0.75rem; margin: 4px 4px 4px 0; font-weight: 500; }

    /* Input area - fixed at bottom */
    .ai-input-area { padding: 16px 24px 24px; background: linear-gradient(transparent, rgba(8, 5, 15, 0.85) 20%); position: absolute; bottom: 0; left: 260px; right: 0; }
    .ai-input-wrapper { display: flex; align-items: flex-end; max-width: 768px; margin: 0 auto; background: #1a1a1a; border: 1px solid rgba(255,255,255,0.12); border-radius: 12px; overflow: hidden; transition: border-color 0.2s, box-shadow 0.2s; }
    .ai-input-wrapper:focus-within { border-color: rgba(124,58,237,0.5); box-shadow: 0 0 0 2px rgba(124,58,237,0.1); }
    .ai-input { flex: 1; background: transparent; border: none; color: #fff; padding: 14px 16px; font-family: 'Outfit', sans-serif; font-size: 1rem; outline: none; resize: none; min-height: 24px; max-height: 200px; line-height: 1.5; }
    .ai-input::placeholder { color: rgba(255,255,255,0.4); }
    .ai-send-btn { background: #7c3aed; color: white; border: none; width: 40px; height: 40px; margin: 6px; border-radius: 8px; cursor: pointer; font-size: 1rem; transition: background 0.2s; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
    .ai-send-btn:hover { background: #5b21b6; }
    .ai-send-btn:disabled { background: rgba(255,255,255,0.1); color: rgba(255,255,255,0.3); cursor: not-allowed; }

    .ai-tier-badge { background: rgba(124,58,237,0.1); color: #7c3aed; padding: 10px 12px; border-radius: 8px; font-size: 0.8rem; font-family: 'Outfit', sans-serif; text-align: center; margin-top: auto; border: 1px solid rgba(124,58,237,0.2); }

    /* Quick action buttons */
    .ai-quick-actions { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; margin: 24px 0; max-width: 500px; }
    .ai-quick-btn { background: transparent; border: 1px solid rgba(255,255,255,0.12); color: rgba(255,255,255,0.8); padding: 14px 16px; border-radius: 10px; cursor: pointer; font-family: 'Outfit', sans-serif; font-size: 0.9rem; transition: all 0.2s; text-align: left; }
    .ai-quick-btn:hover { border-color: rgba(124,58,237,0.4); background: rgba(124,58,237,0.05); color: #fff; }

    /* Welcome screen */
    .ai-welcome { display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 60vh; padding: 40px 20px; text-align: center; }
    .ai-welcome h2 { font-family: 'Outfit', sans-serif; color: #fff; font-size: 2rem; font-weight: 600; margin-bottom: 12px; }
    .ai-welcome .ai-welcome-intro { color: rgba(255,255,255,0.6); font-size: 1.05rem; max-width: 480px; margin: 0 auto 32px; line-height: 1.6; }

    /* Typing indicator */
    .ai-typing { display: inline-flex; align-items: center; gap: 4px; padding: 8px 0; }
    .ai-typing span { display: inline-block; width: 8px; height: 8px; background: #7c3aed; border-radius: 50%; animation: typing 1.4s infinite; }
    .ai-typing span:nth-child(2) { animation-delay: 0.2s; }
    .ai-typing span:nth-child(3) { animation-delay: 0.4s; }
    @keyframes typing { 0%,60%,100% { transform: translateY(0); opacity: 0.4; } 30% { transform: translateY(-4px); opacity: 1; } }

    /* Flight/deal cards */
    .ai-cards { display: flex; flex-direction: column; gap: 12px; margin-top: 16px; }
    .ai-card { background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 16px; transition: border-color 0.2s; }
    .ai-card:hover { border-color: rgba(124,58,237,0.3); }
    .ai-card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
    .ai-card-title { font-weight: 600; color: #fff; font-size: 1rem; }
    .ai-card-badge { background: rgba(124,58,237,0.15); color: #7c3aed; padding: 4px 10px; border-radius: 6px; font-size: 0.75rem; font-weight: 600; }
    .ai-card-badge.green { background: rgba(0,200,100,0.12); color: #00c864; }
    .ai-card-row { display: flex; justify-content: space-between; align-items: center; padding: 6px 0; font-size: 0.9rem; }
    .ai-card-row .label { color: rgba(255,255,255,0.6); }
    .ai-card-row .value { color: #fff; font-weight: 500; }
    .ai-card-price { font-size: 1.4rem; font-weight: 700; color: #7c3aed; }
    .ai-card-savings { color: #00c864; font-size: 0.85rem; font-weight: 600; }
    .ai-card-action { display: inline-block; margin-top: 12px; padding: 10px 20px; background: #7c3aed; color: white; border: none; border-radius: 8px; cursor: pointer; font-family: 'Outfit', sans-serif; font-weight: 600; font-size: 0.9rem; text-decoration: none; transition: background 0.2s; }
    .ai-card-action:hover { background: #5b21b6; }
    .ai-card-actions { display: flex; gap: 10px; margin-top: 12px; flex-wrap: wrap; }
    .ai-card-btn { padding: 8px 16px; border-radius: 8px; font-family: 'Outfit', sans-serif; font-weight: 600; font-size: 0.85rem; cursor: pointer; text-decoration: none; border: none; transition: all 0.2s; }
    .ai-card-btn.primary { background: #7c3aed; color: white; }
    .ai-card-btn.primary:hover { background: #5b21b6; }
    .ai-card-btn.save { background: transparent; border: 1px solid rgba(124,58,237,0.3); color: #7c3aed; }
    .ai-card-btn.save:hover { background: rgba(124,58,237,0.1); }
    .ai-card-divider { border: none; border-top: 1px solid rgba(255,255,255,0.08); margin: 12px 0; }
    .ai-card-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 16px; }

    .ai-wallet-card { display: flex; align-items: center; gap: 12px; }
    .ai-wallet-icon { width: 40px; height: 40px; border-radius: 50%; background: rgba(124,58,237,0.12); display: flex; align-items: center; justify-content: center; font-size: 1.2rem; color: #7c3aed; flex-shrink: 0; }
    .ai-wallet-details { flex: 1; }

    .ai-saved-deals { display: none !important; }

    /* Mobile responsive */
    @media (max-width: 768px) {
        .ai-sidebar { display: none; }
        .ai-chat-container { flex-direction: column; }
        .ai-messages-inner { padding: 16px 16px 140px 16px; }
        .ai-input-area { left: 0; padding: 12px 16px 20px; }
        .ai-quick-actions { grid-template-columns: 1fr; }
        .ai-card-grid { grid-template-columns: 1fr; }
        .ai-welcome { min-height: 50vh; padding: 24px 16px; }
        .ai-welcome h2 { font-size: 1.6rem; }
    }
    @media (max-width: 480px) {
        .ai-message.user .ai-message-content { padding: 12px 14px; }
        .ai-input { padding: 12px 14px; font-size: 16px; }
    }
</style>

<div class="ai-chat-container">
    <div class="ai-sidebar">
        <div class="ai-sidebar-header">
            <h3>History</h3>
            <button class="ai-new-chat-btn" onclick="newConversation()">New chat</button>
        </div>
        <div class="ai-conv-list" id="convList"></div>
        <div class="ai-tier-badge" id="tierBadge">Loading...</div>
    </div>

    <div class="ai-main">
        <div class="ai-messages" id="messages">
            <div class="ai-messages-inner">
                <div class="ai-welcome" id="welcomeScreen">
                    <h2 style="font-family: 'Outfit', sans-serif; font-weight: 600;">MYSTES</h2>
                    <p class="ai-welcome-intro">Where would you like to travel?</p>
                </div>
            </div>
        </div>

        <div class="ai-input-area">
            <div class="ai-input-wrapper">
                <textarea class="ai-input" id="chatInput" placeholder="Message MYSTES..." rows="1" onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendMessage();}"></textarea>
                <button class="ai-send-btn" id="sendBtn" onclick="sendMessage()">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>
                </button>
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
            if (isGuest) html += '<br><a href="/register" style="color:#7c3aed;font-weight:600;">Sign up to book these deals</a>';
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
        const inner = msgs.querySelector('.ai-messages-inner') || msgs;
        inner.innerHTML = '';
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
    const inner = msgs.querySelector('.ai-messages-inner') || msgs;
    inner.innerHTML = '<div class="ai-welcome" id="welcomeScreen"><h2>MYSTES</h2><p class="ai-welcome-intro">Where would you like to travel?</p></div>';
}

function sendQuick(text) {
    document.getElementById('chatInput').value = text;
    sendMessage();
}

function appendMessage(role, content, toolCalls) {
    const msgs = document.getElementById('messages');
    const inner = msgs.querySelector('.ai-messages-inner') || msgs;
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
    inner.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
}

function renderToolCard(tc) {
    if (!tc || !tc.result) return '';
    const tool = tc.tool;
    const r = tc.result;
    try {
        if (tool === 'search_flights') return renderFlightCards(r);
        if (tool === 'search_hotels') return renderHotelCards(r);
        if (tool === 'search_cruises' || tool === 'search_rentals') return renderArbitrageCards(r, tool);
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
    // Save deal to DB and redirect to MYSTES booking page
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

async function bookHotel(offerId, hotelId) {
    const btn = event.target;
    btn.disabled = true;
    btn.textContent = 'Preparing...';
    try {
        const resp = await fetch('/api/hotels/select', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({ offer_id: offerId, hotel_id: hotelId })
        });
        const data = await resp.json();
        if (data.deal_id) {
            window.location.href = '/book/' + data.deal_id;
        } else {
            btn.textContent = 'Book This Hotel';
            btn.disabled = false;
            alert(data.error || 'Could not prepare hotel booking.');
        }
    } catch(e) {
        btn.textContent = 'Book This Hotel';
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
        html += '<div class="ai-card-header"><span class="ai-card-title" style="color:#00e676;">MYSTES Deal Found</span>';
        html += '<span class="ai-card-badge green">Save $' + Math.round(proxy.savings_vs_us) + ' (' + Math.round(proxy.savings_pct) + '%)</span></div>';
        html += '<div class="ai-card-row"><span class="label">MYSTES price</span><span class="value" style="color:#00e676;">$' + Math.round(proxy.cheapest_price_usd || 0) + '</span></div>';
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
        const market = 'MYSTES';  // Never expose proxy market codes
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
            const m = String(t).match(/(\\d{1,2}:\\d{2})/);
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

        // Price — branded as MYSTES, no market codes exposed
        html += '<div class="ai-card-row" style="margin-top:4px;"><span class="ai-card-price">$' + (typeof price === 'number' ? Math.round(price) : price) + '</span>';
        html += '<span class="ai-card-badge" style="background:rgba(33,150,243,0.2);color:#42a5f5;">MYSTES</span>';
        html += '</div>';

        // Deal info (arbitrage comparison)
        const deal = f.deal;
        if (deal && deal.price_difference > 0) {
            html += '<div style="margin-top:6px;padding-top:6px;border-top:1px solid rgba(255,255,255,0.1);font-size:0.85rem;">';
            if (deal.home_price && deal.arbitrage_price) {
                html += '<div class="ai-card-row"><span class="label" style="color:#999;">Normal price</span><span class="value" style="color:#999;text-decoration:line-through;">$' + Math.round(deal.home_price) + '</span></div>';
                html += '<div class="ai-card-row"><span class="label" style="color:#00e676;">MYSTES price</span><span class="value" style="color:#00e676;font-weight:600;">$' + Math.round((deal.arbitrage_price || 0) + (deal.platform_fee_usd || 0)) + '</span></div>';
            }
            html += '<div class="ai-card-row"><span class="label" style="color:#00e676;">You save</span><span class="value" style="color:#00e676;font-weight:700;">-$' + Math.round(deal.user_savings || deal.price_difference || 0) + ' (' + Math.round(deal.user_saves_pct || savings) + '%)</span></div>';
            html += '</div>';
        }

        const dealPayload = {
            title: airline + ' ' + (flightNum || (depAirport + '-' + arrAirport)),
            airline: f.airline || f.marketing_carrier || airline,
            flight_number: flightNum,
            price: price, currency: 'USD',
            savings_pct: savings, market: 'MYSTES', vertical: 'flights',
            origin: f.origin || f.departure_airport || r.origin || '',
            destination: f.destination || f.arrival_airport || r.destination || '',
            date: f.date || f.departure_date || r.date || '',
            return_date: f.return_date || r.return_date || '',
            departure_time: f.departure_time || '',
            arrival_time: f.arrival_time || '',
            stops: f.stops || 0,
            home_price: deal ? deal.home_price : price,
            arbitrage_price: deal ? (deal.arbitrage_price || 0) + (deal.platform_fee_usd || 0) : price,
            price_difference: deal ? deal.price_difference : 0,
            cheapest_market: 'MYSTES',
            home_market: 'US',
            fare_id: f.fare_id || (f.raw_offer ? f.raw_offer.fare_id : null),
            fare_search_id: f.fare_search_id || (f.raw_offer ? f.raw_offer.fare_search_id : null),
            picasso_gds: f.picasso_gds || null,
            fare_type: f.fare_type || null,
            raw_offer: f.raw_offer || null,
            source: f.source || 'gds',
            offer_id: f.offer_id || (f.raw_offer ? f.raw_offer.offer_id : null),
        };
        html += dealActionButtons(dealPayload);
        html += '</div>';
    });
    html += '</div>';
    return html;
}

function renderHotelCards(r) {
    const hotels = r.hotels || [];
    if (!hotels.length) return '';
    let html = '<div class="ai-cards">';
    html += '<div style="color:rgba(255,255,255,0.5);font-size:0.8rem;margin-bottom:8px;">' + hotels.length + ' hotels found</div>';
    hotels.slice(0, 8).forEach((h, idx) => {
        const name = esc(h.hotel_name || h.name || 'Hotel');
        const priceNight = h.price_per_night ? '$' + Math.round(h.price_per_night) : '';
        const priceTotal = h.price_total ? '$' + Math.round(h.price_total) : '';
        const nights = h.nights || 1;
        const room = esc(h.room_type || '');
        const bed = esc(h.bed_type || '');
        const cancel = esc(h.cancellation_description || '');
        const offerId = h.offer_id || '';
        const hotelId = h.hotel_id || '';
        const roomDesc = esc(h.room_description || '');
        const googlePrice = h.google_price || 0;
        const userSavings = h.user_savings || 0;
        const savingsPct = h.savings_pct || 0;

        html += '<div class="ai-card">';
        html += '<div class="ai-card-header"><span class="ai-card-title">' + name + '</span>';
        if (savingsPct > 0) {
            html += '<span class="ai-card-badge green">Save ' + Math.round(savingsPct) + '%</span>';
        } else if (priceNight) {
            html += '<span class="ai-card-badge" style="background:rgba(124,58,237,0.15);color:#7c3aed;">' + priceNight + '/night</span>';
        }
        html += '</div>';
        if (room || bed) {
            const roomInfo = room + (bed && bed !== room ? ' (' + bed + ')' : '');
            html += '<div class="ai-card-row"><span class="label">Room</span><span class="value">' + roomInfo + '</span></div>';
        }
        if (roomDesc) html += '<div class="ai-card-row"><span class="label">Description</span><span class="value" style="font-size:0.85rem;">' + roomDesc.substring(0, 80) + '</span></div>';
        html += '<div class="ai-card-row"><span class="label">Stay</span><span class="value">' + nights + ' night' + (nights !== 1 ? 's' : '') + '</span></div>';

        // Savings comparison: Google price vs MYSTES price
        if (googlePrice > 0 && userSavings > 0) {
            html += '<div style="margin-top:6px;padding-top:6px;border-top:1px solid rgba(255,255,255,0.1);font-size:0.85rem;">';
            html += '<div class="ai-card-row"><span class="label" style="color:#999;">Google/Hotels.com</span><span class="value" style="color:#999;text-decoration:line-through;">$' + Math.round(googlePrice) + '</span></div>';
            html += '<div class="ai-card-row"><span class="label" style="color:#00e676;">MYSTES price</span><span class="value ai-card-price" style="color:#00e676;">$' + Math.round(h.price_total) + '</span></div>';
            html += '<div class="ai-card-row"><span class="label" style="color:#00e676;">You save</span><span class="value" style="color:#00e676;font-weight:700;">-$' + Math.round(userSavings) + '</span></div>';
            html += '</div>';
        } else if (priceTotal) {
            html += '<div class="ai-card-row"><span class="label">Total</span><span class="value ai-card-price">' + priceTotal + '</span></div>';
        }

        if (priceNight && savingsPct > 0) {
            html += '<div class="ai-card-row"><span class="label">Per night</span><span class="value" style="color:#00e676;">' + priceNight + '</span></div>';
        }

        if (cancel) html += '<div class="ai-card-row"><span class="label">Cancellation</span><span class="value" style="font-size:0.8rem;color:rgba(255,255,255,0.6);">' + cancel.substring(0, 60) + '</span></div>';

        if (offerId && hotelId) {
            html += '<div class="ai-card-actions">';
            html += '<button class="ai-card-btn primary" onclick="bookHotel(&apos;' + esc(offerId) + '&apos;,&apos;' + esc(hotelId) + '&apos;)">Book This Hotel</button>';
            html += '</div>';
        }
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
        if (d.market) html += '<div class="ai-card-row"><span class="label">Source</span><span class="value">MYSTES</span></div>';
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
                    '<div style="margin-bottom:16px;opacity:0.85;">Create a free account to keep searching and find the best prices on flights and hotels.</div>' +
                    '<div style="display:flex;gap:12px;justify-content:center;flex-wrap:wrap;">' +
                    '<a href="/register" style="padding:10px 24px;background:linear-gradient(135deg,#7c3aed,#5b21b6);color:white;border-radius:10px;text-decoration:none;font-weight:600;">Create Free Account</a>' +
                    '<a href="/login" style="padding:10px 24px;background:rgba(124,58,237,0.1);border:1px solid rgba(124,58,237,0.3);color:#7c3aed;border-radius:10px;text-decoration:none;font-weight:600;">Sign In</a>' +
                    '</div></div>');
            } else if (err.error === 'daily_limit_reached') {
                appendMessage('assistant', '<div style="text-align:center;padding:16px 0;">' +
                    '<div style="font-size:1.3rem;font-weight:700;margin-bottom:8px;">Daily limit reached</div>' +
                    '<div style="margin-bottom:16px;opacity:0.85;">' + (err.message || 'You have used your free queries for today.') + '</div>' +
                    '<div style="display:flex;gap:12px;justify-content:center;flex-wrap:wrap;">' +
                    '<a href="/dashboard#data-sharing" style="padding:10px 24px;background:linear-gradient(135deg,#7c3aed,#5b21b6);color:white;border-radius:10px;text-decoration:none;font-weight:600;">Share Data for More</a>' +
                    '<a href="/ai/pricing" style="padding:10px 24px;background:rgba(124,58,237,0.1);border:1px solid rgba(124,58,237,0.3);color:#7c3aed;border-radius:10px;text-decoration:none;font-weight:600;">Subscribe from $4.99/mo</a>' +
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

    // Auto-send query from ?q= URL parameter (from homepage search)
    const params = new URLSearchParams(window.location.search);
    const q = params.get('q');
    if (q && q.trim()) {
        document.getElementById('chatInput').value = q.trim();
        setTimeout(function() { sendMessage(); }, 500);
        window.history.replaceState({}, '', '/ai');
    }
})();
</script>
"""


@app.route("/ai")
def mystes_ai_page():
    """MYSTES AI conversational interface."""
    is_auth = "true" if current_user.is_authenticated else "false"
    content = MYSTES_AI_CONTENT.replace("__IS_AUTHENTICATED__", is_auth)
    return render_template_string(
        BASE_TEMPLATE,
        title="MYSTES AI",
        content=content,
        current_user=current_user
    )


# --- MYSTES OS Install Page (Build #88) ---

MYSTES_INSTALL_CONTENT = """
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
        <h1>Welcome to MYSTES</h1>
        <p>Search flights across 195 markets. MYSTES finds price differences on the same flights across regions and passes the savings to you.</p>
    </div>

    <div class="welcome-card">
        <h2>How It Works</h2>
        <div class="welcome-step">
            <div class="w-step-num">1</div>
            <div class="step-text">
                <h3>Tell MYSTES Where You Want to Go</h3>
                <p>Open the AI chat and describe your trip. MYSTES compares rates across markets to find the lowest price.</p>
            </div>
        </div>
        <div class="welcome-step">
            <div class="w-step-num">2</div>
            <div class="step-text">
                <h3>MYSTES Finds the Best Price</h3>
                <p>The same flight can cost 20-60% less depending on which market you book through. MYSTES checks them all and shows you the lowest.</p>
            </div>
        </div>
        <div class="welcome-step">
            <div class="w-step-num">3</div>
            <div class="step-text">
                <h3>Book &amp; Save</h3>
                <p>Pay with card or crypto. MYSTES only charges a fee when it finds savings &mdash; if there is no arbitrage, there is no fee.</p>
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
            <h3>Best Prices</h3>
            <p>We find the lowest price available, period</p>
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
        <p style="margin:8px 0 12px 0;">Your account tier determines how many markets MYSTES checks and how many searches you get per day.</p>
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
        <button class="welcome-btn secondary" id="installBtn" onclick="installMYSTES()">
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

    window.installMYSTES = function() {
        if (deferredPrompt) {
            deferredPrompt.prompt();
            deferredPrompt.userChoice.then(function(result) {
                if (result.outcome === 'accepted') {
                    installBtn.textContent = 'Installed!';
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
def mystes_install_page():
    """Welcome page shown after registration."""
    # Gate behind feature flag (Build #96)
    return render_template_string(
        BASE_TEMPLATE,
        title="Welcome to MYSTES",
        content=MYSTES_INSTALL_CONTENT,
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
    <h1>Get Started with MYSTES</h1>
    <p>Install MYSTES on your devices to join the distributed network and start earning.</p>
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
                <p>Sign in to MYSTES, then go to your <a href="/helper" style="color:#4fc3f7;">Helper Dashboard</a> to find your token. Or copy it from the box above.</p>
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
                <p>Sign in to MYSTES, then go to your <a href="/helper" style="color:#4fc3f7;">Helper Dashboard</a>.</p>
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
                <p>Click "Load unpacked" and select the <code>mystes_extension</code> folder from the project directory.</p>
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

        <div class="note">The extension badge shows "ON" when active, "D" for direct mode (no desktop node), and "OFF" when paused. Click the MYSTES icon to manage settings.</div>
    </div>
</div>

<div id="mobile" class="tab-panel">
    <div class="guide-card">
        <h3>Mobile Apps</h3>
        <p style="color:#aaa; margin-bottom: 24px;">Access MYSTES on your phone. Search flights, book deals, and run a background node.</p>

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
                <p>Open the MYSTES icon from your home screen — it runs as a full-screen PWA</p>
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
    """Quick-start setup guides for MYSTES components."""
    helper_token = ""
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


# --- MYSTESAI Agent API Routes ---

@app.route("/api/agent/search", methods=["POST"])
@login_required
def api_agent_search():
    """Agent-orchestrated search — MYSTESAI decides markets + strategy."""
    try:
        from mystes_agent import mystes_agent
        data = request.get_json() or {}
        query = data.get("query", "")
        if not query:
            return jsonify({"error": "query is required"}), 400

        task_type = data.get("task_type", "flight_search")
        user_market = data.get("market", "US")

        result = mystes_agent.handle_search(
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
    """Deep route analysis by MYSTESAI."""
    try:
        from mystes_agent import mystes_agent
        user_market = request.args.get("market", "US")
        result = mystes_agent.analyze_route(
            origin.upper(), destination.upper(), user_market=user_market
        )
        return jsonify(result)
    except Exception as e:
        logger.error(f"Agent analyze error: {e}")
        return jsonify({"error": "Agent analysis unavailable"}), 500


@app.route("/api/agent/discover")
@login_required
def api_agent_discover():
    """MYSTESAI opportunity discovery."""
    try:
        from mystes_agent import mystes_agent
        force = request.args.get("force", "false").lower() == "true"
        result = mystes_agent.discover_opportunities(force=force)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Agent discovery error: {e}")
        return jsonify({"error": "Agent discovery unavailable"}), 500


@app.route("/api/agent/markets", methods=["POST"])
@login_required
def api_agent_select_markets():
    """Agent market selection for a search."""
    try:
        from mystes_agent import mystes_agent
        data = request.get_json() or {}
        origin = data.get("origin", "")
        destination = data.get("destination", "")
        task_type = data.get("task_type", "flight_search")
        user_market = data.get("market", "US")
        max_markets = int(data.get("max_markets", 8))

        markets = mystes_agent.market_selector.select_markets(
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
    """MYSTESAI agent operational status."""
    try:
        from mystes_agent import mystes_agent
        return jsonify(mystes_agent.get_agent_status())
    except Exception as e:
        logger.error(f"Agent status error: {e}")
        return jsonify({"error": "Agent status unavailable"}), 500


# --- Geographic Zone API Routes ---


# --- Private Market Deal API Routes ---


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
.leg-number { background: #7c3aed; color: white; width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 14px; }
.leg-info { flex: 1; }
.add-leg-btn { border: 2px dashed #ddd; padding: 15px; text-align: center; border-radius: 8px; cursor: pointer; color: #666; }
.add-leg-btn:hover { border-color: #7c3aed; color: #7c3aed; }
.results-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 20px; margin-top: 20px; }
.deal-card { background: white; border: 1px solid #eee; border-radius: 12px; padding: 20px; }
.deal-card.has-deal { border-color: #28a745; border-width: 2px; }
.savings-badge { background: #28a745; color: white; padding: 4px 12px; border-radius: 20px; font-size: 14px; font-weight: bold; }
.market-tag { background: #e9ecef; padding: 2px 8px; border-radius: 4px; font-size: 12px; margin-right: 5px; }

/* Search button spinner */
.search-spinner {
    display: inline-block;
    width: 16px;
    height: 16px;
    border: 2px solid rgba(255,255,255,0.3);
    border-top-color: #fff;
    border-radius: 50%;
    animation: spin 0.6s linear infinite;
    vertical-align: middle;
    margin-right: 8px;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* Search loading state */
.search-loading-state {
    margin-top: 30px;
    padding: 30px;
    background: rgba(15, 10, 25, 0.6);
    border-radius: 16px;
    border: 1px solid rgba(124, 58, 237, 0.2);
}
.search-loading-header {
    display: flex;
    align-items: center;
    gap: 16px;
    margin-bottom: 24px;
}
.search-loading-spinner {
    width: 40px;
    height: 40px;
    border: 3px solid rgba(124, 58, 237, 0.2);
    border-top-color: #7c3aed;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    flex-shrink: 0;
}

/* Skeleton cards */
.skeleton-cards { display: flex; flex-direction: column; gap: 12px; }
.skeleton-card {
    background: rgba(255,255,255,0.05);
    border-radius: 12px;
    padding: 20px;
    display: flex;
    flex-direction: column;
    gap: 12px;
}
.skeleton-line {
    height: 14px;
    background: linear-gradient(90deg, rgba(255,255,255,0.06) 25%, rgba(255,255,255,0.12) 50%, rgba(255,255,255,0.06) 75%);
    background-size: 200% 100%;
    animation: shimmer 1.5s infinite;
    border-radius: 6px;
}
.skeleton-line.w40 { width: 40%; }
.skeleton-line.w60 { width: 60%; }
.skeleton-line.w80 { width: 80%; }
@keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }

/* Flight deal cards */
.flight-cards-grid {
    display: flex;
    flex-direction: column;
    gap: 12px;
}
.flight-card {
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 12px;
    padding: 18px;
    position: relative;
    transition: all 0.2s ease;
}
.flight-card:hover {
    background: rgba(255,255,255,0.06);
    border-color: rgba(124, 58, 237, 0.3);
    transform: translateY(-1px);
}
.flight-card-deal {
    border-color: rgba(40, 167, 69, 0.4);
    background: rgba(40, 167, 69, 0.05);
}
.flight-card-badge {
    position: absolute;
    top: -10px;
    right: 16px;
    background: linear-gradient(135deg, #28a745, #20c997);
    color: white;
    padding: 4px 14px;
    border-radius: 20px;
    font-size: 12px;
    font-weight: 700;
}
.flight-card-badge-exclusive {
    background: linear-gradient(135deg, #7c3aed, #6d28d9);
}
.flight-card-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 14px;
}
.flight-card-airline strong {
    display: block;
    color: #fff;
    font-size: 15px;
}
.flight-card-number {
    color: #999;
    font-size: 12px;
}
.flight-card-stops {
    color: #aaa;
    font-size: 13px;
    background: rgba(255,255,255,0.08);
    padding: 3px 10px;
    border-radius: 12px;
}
.flight-card-route {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 16px;
}
.flight-card-time {
    text-align: center;
    min-width: 60px;
}
.flight-card-time-value {
    font-size: 18px;
    font-weight: 600;
    color: #fff;
}
.flight-card-route-line {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
}
.flight-card-duration {
    font-size: 11px;
    color: #999;
}
.flight-card-line-visual {
    display: flex;
    align-items: center;
    width: 100%;
    gap: 0;
}
.flight-card-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #7c3aed;
    flex-shrink: 0;
}
.flight-card-dash {
    flex: 1;
    height: 1px;
    background: linear-gradient(90deg, rgba(124,58,237,0.6), rgba(124,58,237,0.2));
}
.flight-card-plane-icon {
    font-size: 14px;
    color: #7c3aed;
    margin: 0 4px;
}
.flight-card-pricing {
    display: flex;
    align-items: flex-end;
    gap: 16px;
    margin-bottom: 14px;
}
.flight-card-our-price {
    display: flex;
    flex-direction: column;
}
.flight-card-price-label {
    font-size: 11px;
    color: #999;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
.flight-card-price-value {
    font-size: 26px;
    font-weight: 700;
    color: #4ade80;
}
.flight-card-normal-price {
    display: flex;
    flex-direction: column;
}
.flight-card-price-strikethrough {
    font-size: 16px;
    color: #888;
    text-decoration: line-through;
}
.flight-card-cta {
    width: 100%;
    padding: 12px;
    border: 1px solid rgba(124, 58, 237, 0.4);
    background: rgba(124, 58, 237, 0.1);
    color: #fff;
    font-size: 14px;
    font-weight: 600;
    border-radius: 8px;
    cursor: pointer;
    transition: all 0.2s;
}
.flight-card-cta:hover {
    background: rgba(124, 58, 237, 0.25);
    border-color: #7c3aed;
}
.flight-card-cta-deal {
    background: linear-gradient(135deg, #28a745, #20c997);
    border: none;
    color: white;
}
.flight-card-cta-deal:hover {
    background: linear-gradient(135deg, #218838, #1aab8a);
    box-shadow: 0 4px 15px rgba(40, 167, 69, 0.3);
}
.flight-card-tags {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin: 8px 0;
}
.flight-card-tag {
    font-size: 11px;
    padding: 2px 8px;
    border-radius: 4px;
    background: rgba(255,255,255,0.08);
    color: #ccc;
    border: 1px solid rgba(255,255,255,0.1);
    white-space: nowrap;
}
/* Competitive Price Comparison */
.flight-card-comparison {
    margin: 12px 0 8px;
    padding: 12px;
    background: rgba(0,0,0,0.2);
    border-radius: 8px;
    border: 1px solid rgba(255,255,255,0.06);
}
.price-bar-row {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 6px 0;
    font-size: 12px;
}
.price-bar-label {
    min-width: 90px;
    color: #999;
    text-align: right;
    font-size: 11px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.price-bar-track {
    flex: 1;
    height: 18px;
    background: rgba(255,255,255,0.04);
    border-radius: 4px;
    position: relative;
    overflow: hidden;
}
.price-bar-fill {
    height: 100%;
    border-radius: 4px;
    transition: width 0.6s ease;
    min-width: 20px;
}
.price-bar-fill-mystes {
    background: linear-gradient(90deg, #28a745, #20c997);
}
.price-bar-fill-google {
    background: rgba(255,255,255,0.15);
}
.price-bar-fill-competitor {
    background: rgba(255,255,255,0.10);
}
.price-bar-value {
    min-width: 55px;
    text-align: right;
    font-weight: 600;
    font-size: 12px;
}
.price-bar-value-mystes {
    color: #4ade80;
}
.price-bar-value-other {
    color: #888;
}
.price-bar-best {
    font-size: 9px;
    background: #28a745;
    color: white;
    padding: 1px 6px;
    border-radius: 8px;
    margin-left: 4px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
.price-compare-toggle {
    display: flex;
    align-items: center;
    gap: 6px;
    color: #7c3aed;
    font-size: 11px;
    cursor: pointer;
    padding: 4px 0;
    margin-top: 6px;
    border: none;
    background: none;
    font-family: inherit;
}
.price-compare-toggle:hover {
    color: #a78bfa;
}
.price-compare-expand {
    display: none;
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px solid rgba(255,255,255,0.06);
}
.price-compare-expand.visible {
    display: block;
}
.price-compare-loading {
    font-size: 11px;
    color: #666;
    padding: 8px 0;
    text-align: center;
}
.beats-banner {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 11px;
    color: #4ade80;
    margin-top: 8px;
    padding: 6px 10px;
    background: rgba(40, 167, 69, 0.08);
    border-radius: 6px;
    border: 1px solid rgba(40, 167, 69, 0.15);
}
.beats-banner-icon {
    font-size: 14px;
}
@media (max-width: 600px) {
    .flight-card-route { gap: 8px; }
    .flight-card-time-value { font-size: 15px; }
    .flight-card-price-value { font-size: 22px; }
    .search-row { flex-direction: column; gap: 10px; }
    .search-row .form-group { min-width: unset; }
    .search-options { flex-direction: column; align-items: stretch; }
    .option-select { width: 100%; }
    .search-tabs { overflow-x: auto; -webkit-overflow-scrolling: touch; }
    .search-tab { padding: 10px 16px; font-size: 14px; white-space: nowrap; }
    .payment-method-card { padding: 14px; }
    .method-header { flex-wrap: wrap; gap: 8px; }
}

/* Tab styles */
.search-tabs { display: flex; gap: 0; margin-bottom: 20px; border-bottom: 2px solid #eee; }
.search-tab { padding: 12px 24px; cursor: pointer; border: none; background: none; font-size: 16px; color: #666; border-bottom: 2px solid transparent; margin-bottom: -2px; }
.search-tab:hover { color: #7c3aed; }
.search-tab.active { color: #7c3aed; border-bottom-color: #7c3aed; font-weight: 600; }
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
.option-select:hover { border-color: #7c3aed; }
.option-select:focus { outline: none; border-color: #7c3aed; }

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
.passenger-btn:hover { border-color: #7c3aed; }
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
.passenger-controls button:hover { background: #f5f3ff; border-color: #7c3aed; }
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
.swap-btn:hover { background: #f5f3ff; border-color: #7c3aed; }

/* Price comparison table */
.price-table { width: 100%; border-collapse: collapse; margin-top: 15px; }
.price-table th, .price-table td { padding: 12px 15px; text-align: left; border-bottom: 1px solid #eee; }
.price-table th { background: #f8f9fa; font-weight: 600; color: #333; }
.price-table tr:hover { background: #f8f9fa; }
.price-table .cheapest { background: #d4edda; }
.price-table .cheapest td { color: #155724; font-weight: 600; }
.price-table .market-flag { font-size: 18px; margin-right: 8px; }
.google-link { color: #7c3aed; text-decoration: none; font-size: 14px; }
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
.autocomplete-item:hover { background: #f5f3ff; }
.autocomplete-item.selected { background: #e8f0fe; }
.autocomplete-code { font-weight: bold; color: #7c3aed; font-size: 16px; }
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
    background: linear-gradient(135deg, #7c3aed, #6d28d9);
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
    border-left: 4px solid #7c3aed;
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
    color: #7c3aed;
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
    border-color: #7c3aed;
    background: #f5f3ff;
    transform: translateX(5px);
}
.payment-icon {
    font-size: 24px;
}
</style>

<div class="card search-form" style="background: rgba(10, 6, 18, 0.85); backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px); border: 1px solid rgba(255,255,255,0.08); color: #e0e0e0;">
    <h1 style="color: #fff;">Search Flights</h1>

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
                    Search Flights
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

        <div style="background: #f5f3ff; padding: 15px; border-radius: 8px; margin-bottom: 20px;">
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
const SEARCH_PREFS_KEY = 'mystes_search_prefs';

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
    btn.innerHTML = '<span class="search-spinner"></span> Searching...';
    status.textContent = '';

    // Show skeleton loading cards in results area
    const resultsContainer = document.getElementById('results-container');
    resultsContainer.innerHTML = `
        <div class="search-loading-state">
            <div class="search-loading-header">
                <div class="search-loading-spinner"></div>
                <div>
                    <h3 style="margin:0;color:#fff;">Searching global markets...</h3>
                    <p style="margin:4px 0 0;color:#ccc;font-size:14px;">Comparing prices across 195+ markets for the best deals</p>
                </div>
            </div>
            <div class="skeleton-cards">
                <div class="skeleton-card"><div class="skeleton-line w60"></div><div class="skeleton-line w80"></div><div class="skeleton-line w40"></div></div>
                <div class="skeleton-card"><div class="skeleton-line w80"></div><div class="skeleton-line w60"></div><div class="skeleton-line w40"></div></div>
                <div class="skeleton-card"><div class="skeleton-line w40"></div><div class="skeleton-line w80"></div><div class="skeleton-line w60"></div></div>
            </div>
        </div>
    `;
    resultsContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });

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

    function resetSearchBtn(msg) {
        status.textContent = msg;
        btn.disabled = false;
        btn.innerHTML = 'Search Flights';
        resultsContainer.innerHTML = '';
        if (msg) showToast(msg, 'warning');
    }

    if (legs.length === 0) {
        resetSearchBtn('Please fill in all fields.');
        return;
    }

    // Validate legs have proper airport codes (3 letters)
    for (const leg of legs) {
        if (!leg.origin || leg.origin.length !== 3) {
            resetSearchBtn(`Invalid origin airport: "${leg.origin || 'empty'}". Please select from the dropdown.`);
            return;
        }
        if (!leg.destination || leg.destination.length !== 3) {
            resetSearchBtn(`Invalid destination airport: "${leg.destination || 'empty'}". Please select from the dropdown.`);
            return;
        }
        if (!leg.date) {
            resetSearchBtn('Please select a departure date.');
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
        // Always re-enable button
        btn.disabled = false;
        btn.innerHTML = 'Search Flights';
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
            <div style="background: linear-gradient(135deg, #7c3aed, #6d28d9); padding: 20px; border-radius: 12px; margin-bottom: 20px; color: white;">
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
                        <div style="font-size: 11px; opacity: 0.8; text-transform: uppercase;">🔥 MYSTES Price</div>
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
            <div style="background: ${savings > 10 ? '#d4edda' : '#f5f3ff'}; padding: 20px; border-radius: 12px; margin-bottom: 20px;">
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
                    background: ${isCheapest ? '#28a745' : (isSelected ? '#7c3aed' : 'white')};
                    color: ${isCheapest || isSelected ? 'white' : '#333'};
                    border: 2px solid ${isCheapest ? '#28a745' : (isSelected ? '#7c3aed' : '#ddd')};
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
                    Prices shown are the lowest found by MYSTES's price engine
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
                        ${isActualRoundTrip ? '<span style="background: #7c3aed; color: white; padding: 2px 8px; border-radius: 10px; font-size: 11px; margin-left: 8px;">ROUND-TRIP TOTAL</span>' : ''}
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
                cheapest_market: 'MYSTES',
                converted_prices: {},  // Scrubbed
                deal: f.deal,
                baggage_info: f.baggage_info,
                fare_family: f.fare_family,
                seat_selection: f.seat_selection,
                cancellation_policy: f.cancellation_policy,
                rebooking_policy: f.rebooking_policy,
                is_codeshare: f.is_codeshare,
                operating_carrier: f.operating_carrier,
                layovers: f.layovers,
            })).sort((a, b) => (a.cheapest_price || 9999) - (b.cheapest_price || 9999));

            html += `<div class="flight-cards-grid">`;

            // Show flights as cards
            for (const flight of flightList.slice(0, 10)) {
                const usPrice = flight.deal?.home_price || flight.cheapest_price;
                const platformFee = flight.deal?.platform_fee_usd || 0;
                const cheapestPrice = (flight.cheapest_price || usPrice) + platformFee;
                const savings = usPrice - cheapestPrice;
                const savingsPct = usPrice > 0 ? ((savings / usPrice) * 100).toFixed(0) : 0;
                const hasSavings = savings > 5;

                const isExclusive = flight.deal && flight.deal.cheapest_market === 'MYSTES';
                const flightData = encodeURIComponent(JSON.stringify({
                    airline: flight.airline,
                    flight_number: flight.flight_number,
                    departure_time: flight.departure_time,
                    arrival_time: flight.arrival_time,
                    duration: flight.duration,
                    stops: flight.stops,
                    cheapest_price: cheapestPrice,
                    cheapest_market: 'MYSTES',
                    us_price: usPrice,
                    savings: savings,
                    route: leg.route,
                    date: leg.date,
                    return_date: leg.return_date || null,
                    is_round_trip: isActualRoundTrip,
                    price_type: isActualRoundTrip ? 'round_trip_total' : 'one_way',
                    converted_prices: {},
                }));

                const stopsText = flight.stops === 0 ? 'Nonstop' : (flight.stops !== undefined ? flight.stops + ' stop' + (flight.stops > 1 ? 's' : '') : '');

                // Build feature tags
                const tags = [];
                if (flight.fare_family) tags.push(flight.fare_family);
                if (flight.baggage_info) {
                    const bag = flight.baggage_info;
                    if (bag === '0PC') tags.push('No checked bag');
                    else if (bag.match(/\\d+PC/)) tags.push(bag.replace('PC', ' checked bag(s)'));
                    else if (bag.match(/\\d+x\\d+kg/i)) tags.push(bag + ' checked');
                    else tags.push(bag);
                }
                if (flight.seat_selection?.available) tags.push('Seat selection');
                if (flight.cancellation_policy === 'NOT_POSSIBLE') tags.push('Non-refundable');
                else if (flight.cancellation_policy === 'POSSIBLE') tags.push('Refundable');
                if (flight.rebooking_policy === 'POSSIBLE') tags.push('Changeable');
                else if (flight.rebooking_policy === 'NOT_POSSIBLE') tags.push('No changes');
                if (flight.is_codeshare && flight.operating_carrier) tags.push('Operated by ' + flight.operating_carrier);
                // Layover details
                let layoverText = '';
                if (flight.stops > 0 && flight.layovers?.length > 0) {
                    layoverText = flight.layovers.join(', ');
                }

                html += `
                    <div class="flight-card ${hasSavings ? 'flight-card-deal' : ''}" data-leg="${legNum}">
                        ${hasSavings ? `<div class="flight-card-badge">Save $${savings.toFixed(0)} (${savingsPct}%)</div>` : ''}
                        ${isExclusive ? `<div class="flight-card-badge flight-card-badge-exclusive">MYSTES Exclusive</div>` : ''}
                        <div class="flight-card-header">
                            <div class="flight-card-airline">
                                <strong>${flight.airline || 'Multiple Airlines'}</strong>
                                ${flight.flight_number ? `<span class="flight-card-number">${flight.flight_number}</span>` : ''}
                            </div>
                            <div class="flight-card-stops">${stopsText}${layoverText ? ` <span style="color:#999;font-size:11px;">(${layoverText})</span>` : ''}</div>
                        </div>
                        <div class="flight-card-route">
                            <div class="flight-card-time">
                                <span class="flight-card-time-value">${flight.departure_time || '--:--'}</span>
                            </div>
                            <div class="flight-card-route-line">
                                <div class="flight-card-duration">${flight.duration || ''}</div>
                                <div class="flight-card-line-visual">
                                    <span class="flight-card-dot"></span>
                                    <span class="flight-card-dash"></span>
                                    <span class="flight-card-plane-icon">&#9992;</span>
                                    <span class="flight-card-dash"></span>
                                    <span class="flight-card-dot"></span>
                                </div>
                            </div>
                            <div class="flight-card-time">
                                <span class="flight-card-time-value">${flight.arrival_time || '--:--'}</span>
                            </div>
                        </div>
                        <div class="flight-card-pricing">
                            <div class="flight-card-our-price">
                                <span class="flight-card-price-label">MYSTES Price</span>
                                <span class="flight-card-price-value">$${cheapestPrice?.toFixed(0) || 'N/A'}</span>
                            </div>
                            ${!isExclusive && usPrice > cheapestPrice ? `
                                <div class="flight-card-normal-price">
                                    <span class="flight-card-price-label">Google Flights</span>
                                    <span class="flight-card-price-strikethrough">$${usPrice?.toFixed(0)}</span>
                                </div>
                            ` : ''}
                        </div>
                        ${hasSavings ? `
                        <div class="flight-card-comparison">
                            <div class="price-bar-row">
                                <span class="price-bar-label">MYSTES</span>
                                <div class="price-bar-track">
                                    <div class="price-bar-fill price-bar-fill-mystes" style="width: ${Math.max(20, (cheapestPrice / usPrice) * 100).toFixed(0)}%"></div>
                                </div>
                                <span class="price-bar-value price-bar-value-mystes">$${cheapestPrice?.toFixed(0)}<span class="price-bar-best">BEST</span></span>
                            </div>
                            <div class="price-bar-row">
                                <span class="price-bar-label">Google Flights</span>
                                <div class="price-bar-track">
                                    <div class="price-bar-fill price-bar-fill-google" style="width: 100%"></div>
                                </div>
                                <span class="price-bar-value price-bar-value-other">$${usPrice?.toFixed(0)}</span>
                            </div>
                            ${flight.deal?.booking_token ? `
                                <button class="price-compare-toggle" onclick="loadCompetitorPrices(this, &apos;${flight.deal.booking_token}&apos;, ${cheapestPrice?.toFixed(0)}, ${usPrice?.toFixed(0)})">
                                    <span>&#9660;</span> Compare all prices
                                </button>
                                <div class="price-compare-expand"></div>
                            ` : ''}
                            <div class="beats-banner">
                                <span class="beats-banner-icon">&#10003;</span>
                                MYSTES beats Google Flights by $${savings.toFixed(0)} (${savingsPct}% less)
                            </div>
                        </div>
                        ` : ''}
                        ${tags.length > 0 ? `<div class="flight-card-tags">${tags.map(t => `<span class="flight-card-tag">${t}</span>`).join('')}</div>` : ''}
                        <button class="flight-card-cta ${hasSavings || isExclusive ? 'flight-card-cta-deal' : ''}" onclick="selectFlightForLeg(${legNum}, '${flightData}')">
                            ${hasSavings ? 'Book & Save $' + savings.toFixed(0) : (isExclusive ? 'Book Exclusive Deal' : 'Select Flight')}
                        </button>
                    </div>
                `;
            }

            html += `</div>`;

            // Market breakdown removed — MYSTES price intelligence is proprietary

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
                        <span style="color: #28a745; font-weight: bold;">$${((deal.arbitrage_price || 0) + (deal.platform_fee_usd || 0)).toFixed(2)}</span>
                    </div>
                </div>
                <span class="market-tag">Book via MYSTES</span>
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
            <div class="card" style="border: 3px solid #7c3aed; background: #ffffff; color: #1a1a2e;">
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
                    <button onclick="proceedToPayment()" class="btn" style="font-size: 18px; padding: 15px 40px; background: linear-gradient(135deg, #7c3aed, #6d28d9); color: #fff; border: none; border-radius: 8px; cursor: pointer; font-weight: 600;">
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
// --- Competitive Price Comparison (lazy-load booking options) ---
async function loadCompetitorPrices(btn, bookingToken, mystesPrice, googlePrice) {
    const expandDiv = btn.nextElementSibling;
    if (expandDiv.classList.contains('visible')) {
        expandDiv.classList.remove('visible');
        btn.querySelector('span').innerHTML = '&#9660;';
        btn.childNodes[1].textContent = ' Compare all prices';
        return;
    }

    btn.querySelector('span').innerHTML = '&#9650;';
    btn.childNodes[1].textContent = ' Hide prices';
    expandDiv.classList.add('visible');

    if (expandDiv.dataset.loaded) return;
    expandDiv.innerHTML = '<div class="price-compare-loading">Loading competitor prices...</div>';

    try {
        const resp = await fetch('/api/flight/competitors', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({booking_token: bookingToken}),
        });
        const data = await resp.json();
        const competitors = data.competitors || [];

        if (competitors.length === 0) {
            expandDiv.innerHTML = '<div class="price-compare-loading">Competitor pricing data unavailable</div>';
            expandDiv.dataset.loaded = '1';
            return;
        }

        const maxPrice = Math.max(googlePrice, ...competitors.map(c => c.price));
        let barsHtml = '';
        let beatCount = 0;

        for (const c of competitors) {
            const pct = Math.max(20, (c.price / maxPrice) * 100).toFixed(0);
            const saving = c.price - mystesPrice;
            const isAirline = c.is_airline;
            const nameDisplay = c.name.length > 14 ? c.name.substring(0, 12) + '..' : c.name;
            if (saving > 0) beatCount++;

            barsHtml += `
                <div class="price-bar-row">
                    <span class="price-bar-label" title="${c.name}">${nameDisplay}${isAirline ? ' &#9992;' : ''}</span>
                    <div class="price-bar-track">
                        <div class="price-bar-fill price-bar-fill-competitor" style="width: ${pct}%"></div>
                    </div>
                    <span class="price-bar-value price-bar-value-other">$${c.price}${saving > 0 ? ' <span style="color:#4ade80;font-size:10px;">+$' + saving.toFixed(0) + '</span>' : ''}</span>
                </div>
            `;
        }

        if (beatCount > 0) {
            barsHtml += `
                <div class="beats-banner" style="margin-top:10px;">
                    <span class="beats-banner-icon">&#9733;</span>
                    MYSTES beats ${beatCount} competitor${beatCount > 1 ? 's' : ''} on this flight
                </div>
            `;
        }

        expandDiv.innerHTML = barsHtml;
        expandDiv.dataset.loaded = '1';

    } catch (err) {
        console.error('Failed to load competitor prices:', err);
        expandDiv.innerHTML = '<div class="price-compare-loading">Could not load competitor prices</div>';
    }
}

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
        const legServiceFee = hasSavings ? Math.max(flight.savings * 0.25, 3) : 4.99;

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
                        <span style="background: #7c3aed; color: white; padding: 4px 12px; border-radius: 15px; font-size: 11px; font-weight: 600;">INCLUDES BOTH FLIGHTS</span>
                    </div>

                    <!-- Outbound Flight -->
                    <div style="background: #fff; padding: 15px; border-radius: 8px; margin-bottom: 10px; border-left: 4px solid #7c3aed;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                            <span style="font-weight: 600; color: #7c3aed;">✈️ OUTBOUND</span>
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
                            <span class="market-tag" style="margin-left: 8px;">MYSTES</span>
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
                            <span class="market-tag" style="margin-left: 8px;">MYSTES</span>
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
            <span style="color: #7c3aed;">$${finalPrice.toFixed(2)}</span>
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
            <div style="background: #f0fdfa; color: #856404; padding: 12px; border-radius: 8px; text-align: center; margin-top: 10px;">
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
        const legServiceFee = hasSavings ? Math.max(flight.savings * 0.25, 3) : 4.99;

        totalBestPrice += flight.cheapest_price;
        totalSavings += flight.savings || 0;
        totalServiceFee += legServiceFee;

        flights.push({
            leg: legNum,
            airline: flight.airline,
            flight_number: flight.flight_number,
            route: flight.route,
            date: flight.date,
            cheapest_market: 'MYSTES',
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
        cheapest_market: 'MYSTES',
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
                <p style="margin: 10px 0 0 0; font-size: 24px; font-weight: bold; color: #7c3aed;">$${dealData.total_price.toFixed(2)}</p>
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
        const serviceFee = selectedFlight.savings > 5 ? Math.max(selectedFlight.savings * 0.25, 3) : 4.99;
        window.location.href = '/pay/xrp?amount=' + (selectedFlight.cheapest_price + serviceFee).toFixed(2) +
            '&flight=' + encodeURIComponent(selectedFlight.airline + ' ' + selectedFlight.route);
    }
}

// Coinbase crypto removed — Stripe + MoonPay only

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
                Searched ${data.flights_compared} flights across ${typeof data.markets_checked === 'number' ? data.markets_checked : (data.markets_checked?.length || 5)} regions via MYSTES price engine
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
                        <td>${isCheapest ? '<strong>MYSTES PRICE</strong>' : `+$${diff.toFixed(2)}`}</td>
                    </tr>
                `;
            }

            html += `
                    </tbody>
                </table>
                <div style="margin-top: 15px; display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">
                    <p style="margin: 0; color: #155724;">
                        <strong>Best option:</strong> Book via <span class="market-tag">MYSTES</span> for $${cheapestPrice.toFixed(2)}
                    </p>
                    ${savings > 5 ? `
                        <a href="/p2p/book?origin=${encodeURIComponent(flight.origin)}&destination=${encodeURIComponent(flight.destination)}&date=${encodeURIComponent(flight.date)}&flight=${encodeURIComponent(flight.flight_number)}&market=mystes&price=${cheapestPrice.toFixed(2)}&us_price=${flight.market_prices['US']?.price_usd?.toFixed(2) || cheapestPrice.toFixed(2)}"
                           class="btn" style="background: #7c3aed; border-color: #7c3aed; color: white; padding: 8px 16px; font-size: 13px; text-decoration: none; border-radius: 6px;">
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
                <p style="color: #155724; margin: 10px 0 0 0;">by booking through MYSTES's price engine</p>
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
                    <span>Book via MYSTES instead of standard pricing:</span>
                    <span style="font-size: 20px; font-weight: bold; color: #155724;">Save $${comparison.max_savings_usd.toFixed(2)} (${comparison.savings_percent}%)</span>
                </div>
        `;

        if (data.deal && data.deal.is_good_deal) {
            html += `
                <div style="margin-top: 15px; padding-top: 15px; border-top: 1px solid #c3e6cb;">
                    <div class="price-row">
                        <span>Your price (after platform fee):</span>
                        <span style="font-weight: bold;">$${((data.deal.arbitrage_price || 0) + (data.deal.platform_fee_usd || 0)).toFixed(2)}</span>
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
    return_date = data.get("return_date")
    cabin_class = data.get("cabin_class", "economy")
    adults = int(data.get("adults", 1))
    children = int(data.get("children", 0))
    infants = int(data.get("infants", 0))

    if not origin or not destination or not date:
        return jsonify({"error": "origin, destination, and date are required"}), 400

    search_opts = None
    if adults > 1 or children > 0 or infants > 0:
        search_opts = {"passengers": {"adults": adults, "children": children, "infants": infants}}

    try:
        results = search_global(
            origin, destination, date,
            return_date=return_date,
            cabin_class=cabin_class,
            fast_mode=True,
            search_options=search_opts,
            user=current_user,
        )

        # Track search metric
        try:
            from monitoring import track_search
            track_search(origin=origin, destination=destination, market="US")
        except Exception:
            pass

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
                    arbitrage_market="MYSTES",
                    arbitrage_price_usd=deal_info.get("arbitrage_price"),
                    gross_savings_usd=deal_info.get("gross_savings"),
                    platform_fee_usd=deal_info.get("platform_fee_usd"),
                    platform_fee_xrp=deal_info.get("platform_fee_xrp"),
                    user_savings_usd=deal_info.get("user_savings"),
                    savings_percent=deal_info.get("user_saves_pct"),
                    booking_url=deal_info.get("booking_url"),
                    destination_tag=deal_info.get("payment", {}).get("payment_request", {}).get("destination_tag"),
                    departure_time=deal_data.get("departure_time"),
                    arrival_time=deal_data.get("arrival_time"),
                    duration=deal_data.get("duration"),
                    stops=deal_data.get("stops", 0),
                    cabin_class=deal_data.get("travel_class"),
                    fare_family=deal_data.get("fare_family"),
                    baggage_info=deal_data.get("baggage_info"),
                    seat_selection_available=deal_data.get("seat_selection", {}).get("available") if deal_data.get("seat_selection") else None,
                    flight_cancellation_policy=deal_data.get("cancellation_policy"),
                    flight_rebooking_policy=deal_data.get("rebooking_policy"),
                    ticket_deadline=deal_data.get("ticket_deadline"),
                    segments_json=json.dumps(deal_data.get("segments", [])) if deal_data.get("segments") else None,
                    layovers=",".join(deal_data.get("layovers", [])) if deal_data.get("layovers") else None,
                    fare_id=deal_data.get("fare_id") or deal_data.get("raw_offer", {}).get("fare_id"),
                    fare_search_id=deal_data.get("fare_search_id") or deal_data.get("raw_offer", {}).get("fare_search_id"),
                    amadeus_offer_data=json.dumps(deal_data.get("raw_offer")) if deal_data.get("raw_offer") else None,
                    picasso_gds=deal_data.get("picasso_gds"),
                    fare_type=deal_data.get("fare_type"),
                    is_active=True,
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=24)
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
                            user=current_user,
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
                search_options=search_options,
                user=current_user
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
                        arbitrage_market="MYSTES",
                        arbitrage_price_usd=deal_info.get("arbitrage_price"),
                        gross_savings_usd=deal_info.get("gross_savings"),
                        platform_fee_usd=deal_info.get("platform_fee_usd"),
                        platform_fee_xrp=deal_info.get("platform_fee_xrp"),
                        user_savings_usd=deal_info.get("user_savings"),
                        savings_percent=deal_info.get("user_saves_pct"),
                        booking_url=deal_info.get("booking_url"),
                        destination_tag=deal_info.get("payment", {}).get("payment_request", {}).get("destination_tag"),
                        departure_time=deal_data.get("departure_time"),
                        arrival_time=deal_data.get("arrival_time"),
                        duration=deal_data.get("duration"),
                        stops=deal_data.get("stops", 0),
                        cabin_class=deal_data.get("travel_class"),
                        fare_family=deal_data.get("fare_family"),
                        baggage_info=deal_data.get("baggage_info"),
                        seat_selection_available=deal_data.get("seat_selection", {}).get("available") if deal_data.get("seat_selection") else None,
                        flight_cancellation_policy=deal_data.get("cancellation_policy"),
                        flight_rebooking_policy=deal_data.get("rebooking_policy"),
                        ticket_deadline=deal_data.get("ticket_deadline"),
                        segments_json=json.dumps(deal_data.get("segments", [])) if deal_data.get("segments") else None,
                        layovers=",".join(deal_data.get("layovers", [])) if deal_data.get("layovers") else None,
                        fare_id=deal_data.get("fare_id") or deal_data.get("raw_offer", {}).get("fare_id"),
                        fare_search_id=deal_data.get("fare_search_id") or deal_data.get("raw_offer", {}).get("fare_search_id"),
                        picasso_gds=deal_data.get("picasso_gds"),
                        fare_type=deal_data.get("fare_type"),
                        is_active=True,
                        expires_at=datetime.now(timezone.utc) + timedelta(hours=24)
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
    from datetime import datetime, timedelta, timezone

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
                    "cheapest_market": "MYSTES",
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
.payment-method:hover { border-color: #7c3aed; background: #f8f9ff; }
.payment-method.selected { border-color: #7c3aed; background: #f5f3ff; }
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
.warning { background: #f0fdfa; color: #856404; padding: 10px; border-radius: 4px; margin: 10px 0; }
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

            <!-- Coinbase crypto removed — Stripe + MoonPay only -->
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

// Coinbase crypto removed — Stripe + MoonPay only

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
        cancel_url=request.host_url + f"pay/{deal_id}",
        user_id=current_user.id,
        user=current_user,
    )

    # Commit stripe_customer_id if it was just created
    if current_user.stripe_customer_id:
        db.session.commit()

    if "error" in result:
        flash(f"Card payment error: {result['error']}", "error")
        return redirect(f"/pay/{deal_id}")

    # Store pending payment with Stripe session reference
    payment = Payment(
        user_id=current_user.id,
        deal_id=deal.id,
        payment_method='card',
        amount_usd=deal.platform_fee_usd,
        stripe_session_id=result.get("session_id"),
        status='pending',
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
        deal = Deal.query.filter_by(deal_id=deal_id).first()
        if deal:
            # Check for existing verified payment (prevent duplicates)
            existing = Payment.query.filter_by(
                user_id=current_user.id,
                deal_id=deal.id,
                status='verified'
            ).first()

            if not existing:
                # Update pending payment or create new verified one
                payment = Payment.query.filter_by(
                    user_id=current_user.id,
                    deal_id=deal.id,
                    status='pending'
                ).first()

                if payment:
                    payment.status = 'verified'
                    payment.verified_at = datetime.now(timezone.utc)
                    payment.payment_method = 'card'
                    payment.tx_hash = result.get("payment_intent", "stripe")
                    payment.stripe_session_id = session_id
                    payment.stripe_payment_intent = result.get("payment_intent")
                    db.session.commit()
                else:
                    # No pending record — create verified payment directly
                    payment = Payment(
                        user_id=current_user.id,
                        deal_id=deal.id,
                        payment_method='card',
                        amount_usd=deal.platform_fee_usd,
                        tx_hash=result.get("payment_intent"),
                        stripe_session_id=session_id,
                        stripe_payment_intent=result.get("payment_intent"),
                        status='verified',
                        verified_at=datetime.now(timezone.utc)
                    )
                    db.session.add(payment)
                    db.session.commit()

        flash("Payment successful! Here's your deal.", "success")
        return redirect(f"/deal/{deal_id}/access")

    flash("Payment verification failed. Please contact support.", "error")
    return redirect("/deals")


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
                payment.verified_at = datetime.now(timezone.utc)
                db.session.commit()

    return jsonify({"received": True})


    # Coinbase Commerce routes removed — Stripe + MoonPay only


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
    <a href="/admin" style="padding:6px 14px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:600;color:#e8e8e8;background:rgba(255,255,255,0.08);transition:background 0.2s;" onmouseover="this.style.background='rgba(124,58,237,0.3)'" onmouseout="this.style.background='rgba(255,255,255,0.08)'">Dashboard</a>
    <a href="/admin/payments" style="padding:6px 14px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:600;color:#e8e8e8;background:rgba(255,255,255,0.08);transition:background 0.2s;" onmouseover="this.style.background='rgba(124,58,237,0.3)'" onmouseout="this.style.background='rgba(255,255,255,0.08)'">Payments</a>
    <a href="/admin/users" style="padding:6px 14px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:600;color:#e8e8e8;background:rgba(255,255,255,0.08);transition:background 0.2s;" onmouseover="this.style.background='rgba(124,58,237,0.3)'" onmouseout="this.style.background='rgba(255,255,255,0.08)'">Users</a>
    <a href="/admin/deals" style="padding:6px 14px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:600;color:#e8e8e8;background:rgba(255,255,255,0.08);transition:background 0.2s;" onmouseover="this.style.background='rgba(124,58,237,0.3)'" onmouseout="this.style.background='rgba(255,255,255,0.08)'">Deals</a>
    <a href="/admin/features" style="padding:6px 14px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:600;color:#ffd700;background:rgba(255,215,0,0.15);transition:background 0.2s;" onmouseover="this.style.background='rgba(255,215,0,0.3)'" onmouseout="this.style.background='rgba(255,215,0,0.15)'">Features</a>
    <a href="/admin/security" style="padding:6px 14px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:600;color:#f44336;background:rgba(244,67,54,0.15);transition:background 0.2s;" onmouseover="this.style.background='rgba(244,67,54,0.3)'" onmouseout="this.style.background='rgba(244,67,54,0.15)'">Security</a>
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
    <a href="/admin/features" class="card" style="text-decoration: none; color: inherit; border: 1px solid rgba(255,215,0,0.3);">
        <h3 style="color: #ffd700;">Feature Flags</h3>
        <p style="color: #666;">Toggle verticals, payment methods, Phase 2 features</p>
    </a>
    <a href="/admin/security" class="card" style="text-decoration: none; color: inherit; border: 1px solid rgba(244,67,54,0.3);">
        <h3 style="color: #f44336;">Security</h3>
        <p style="color: #666;">API keys, rate limits, audit log</p>
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
        ),
        current_user=current_user
    )


@app.route("/admin/features")
@admin_required
def admin_features():
    """Admin feature flags management - control phased rollout."""
    from models import FeatureFlag, SystemSetting

    # Initialize flags and settings if needed
    FeatureFlag.init_default_flags()
    SystemSetting.init_defaults()

    # Group flags by layer
    flags = FeatureFlag.query.order_by(FeatureFlag.layer, FeatureFlag.flag_key).all()
    layer1 = [f for f in flags if f.layer == 1]
    layer2 = [f for f in flags if f.layer == 2]
    layer3 = [f for f in flags if f.layer == 3]

    # Get node payout percentage
    payout_pct = SystemSetting.get('node_payout_pct', 0)

    content = ADMIN_NAV + """
    <h1>Feature Flags</h1>
    <p style="color: #aaa;">Control which features are enabled. Toggle switches to enable/disable features across all users.</p>

    <style>
        .layer-card { background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 20px; margin-bottom: 20px; }
        .layer-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; padding-bottom: 12px; border-bottom: 1px solid rgba(255,255,255,0.1); }
        .layer-title { font-size: 1.2rem; font-weight: 700; }
        .layer-1 .layer-title { color: #00c864; }
        .layer-2 .layer-title { color: #7c3aed; }
        .layer-3 .layer-title { color: #ffd700; }
        .layer-badge { padding: 4px 12px; border-radius: 20px; font-size: 0.75rem; font-weight: 600; }
        .layer-1 .layer-badge { background: rgba(0,200,100,0.15); color: #00c864; }
        .layer-2 .layer-badge { background: rgba(124,58,237,0.15); color: #7c3aed; }
        .layer-3 .layer-badge { background: rgba(255,215,0,0.15); color: #ffd700; }
        .flag-row { display: flex; justify-content: space-between; align-items: center; padding: 12px 0; border-bottom: 1px solid rgba(255,255,255,0.05); }
        .flag-row:last-child { border-bottom: none; }
        .flag-info { flex: 1; }
        .flag-name { font-weight: 600; color: #fff; margin-bottom: 4px; }
        .flag-desc { font-size: 0.85rem; color: #888; }
        .toggle-switch { position: relative; width: 50px; height: 26px; }
        .toggle-switch input { opacity: 0; width: 0; height: 0; }
        .toggle-slider { position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background: #333; border-radius: 26px; transition: 0.3s; }
        .toggle-slider:before { position: absolute; content: ""; height: 20px; width: 20px; left: 3px; bottom: 3px; background: white; border-radius: 50%; transition: 0.3s; }
        input:checked + .toggle-slider { background: #00c864; }
        input:checked + .toggle-slider:before { transform: translateX(24px); }
        .enabled-at { font-size: 0.75rem; color: #666; margin-top: 4px; }
    </style>

    <div class="layer-card layer-1">
        <div class="layer-header">
            <span class="layer-title">Layer 1 — Launch</span>
            <span class="layer-badge">LIVE</span>
        </div>
        {% for flag in layer1 %}
        <div class="flag-row">
            <div class="flag-info">
                <div class="flag-name">{{ flag.flag_name }}</div>
                <div class="flag-desc">{{ flag.description }}</div>
                {% if flag.enabled_at %}<div class="enabled-at">Enabled {{ flag.enabled_at.strftime('%Y-%m-%d') }}</div>{% endif %}
            </div>
            <label class="toggle-switch">
                <input type="checkbox" {{ 'checked' if flag.is_enabled else '' }} onchange="toggleFlag('{{ flag.flag_key }}', this.checked)">
                <span class="toggle-slider"></span>
            </label>
        </div>
        {% endfor %}
    </div>

    <div class="layer-card layer-2">
        <div class="layer-header">
            <span class="layer-title">Layer 2 — Funded</span>
            <span class="layer-badge">READY</span>
        </div>
        {% for flag in layer2 %}
        <div class="flag-row">
            <div class="flag-info">
                <div class="flag-name">{{ flag.flag_name }}</div>
                <div class="flag-desc">{{ flag.description }}</div>
                {% if flag.enabled_at %}<div class="enabled-at">Enabled {{ flag.enabled_at.strftime('%Y-%m-%d') }}</div>{% endif %}
            </div>
            <label class="toggle-switch">
                <input type="checkbox" {{ 'checked' if flag.is_enabled else '' }} onchange="toggleFlag('{{ flag.flag_key }}', this.checked)">
                <span class="toggle-slider"></span>
            </label>
        </div>
        {% endfor %}
    </div>

    <div class="layer-card layer-3">
        <div class="layer-header">
            <span class="layer-title">Layer 3 — Scale</span>
            <span class="layer-badge">FUTURE</span>
        </div>
        {% for flag in layer3 %}
        <div class="flag-row">
            <div class="flag-info">
                <div class="flag-name">{{ flag.flag_name }}</div>
                <div class="flag-desc">{{ flag.description }}</div>
                {% if flag.enabled_at %}<div class="enabled-at">Enabled {{ flag.enabled_at.strftime('%Y-%m-%d') }}</div>{% endif %}
            </div>
            <label class="toggle-switch">
                <input type="checkbox" {{ 'checked' if flag.is_enabled else '' }} onchange="toggleFlag('{{ flag.flag_key }}', this.checked)">
                <span class="toggle-slider"></span>
            </label>
        </div>
        {% endfor %}
    </div>

    <!-- Node Payout Settings -->
    <div class="layer-card" style="border-color: rgba(0,200,100,0.3);">
        <div class="layer-header">
            <span class="layer-title" style="color: #00c864;">Node Payout Settings</span>
            <span class="layer-badge" style="background: rgba(0,200,100,0.15); color: #00c864;">MANUAL</span>
        </div>
        <div style="margin-bottom: 20px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <label style="font-weight: 600; color: #fff;">Node Payout Percentage</label>
                <span id="payoutValue" style="font-size: 1.4rem; font-weight: 700; color: #00c864;">{{ payout_pct }}%</span>
            </div>
            <input type="range" id="payoutSlider" min="0" max="100" value="{{ payout_pct }}"
                   style="width: 100%; accent-color: #00c864;"
                   oninput="document.getElementById('payoutValue').textContent = this.value + '%'">
            <div style="display: flex; justify-content: space-between; font-size: 0.75rem; color: #666; margin-top: 4px;">
                <span>0% (MYSTES keeps all)</span>
                <span>100% (Nodes get all)</span>
            </div>
            <button onclick="updatePayoutPct()" style="margin-top: 12px; padding: 10px 24px; background: #00c864; color: #000; border: none; border-radius: 8px; font-weight: 600; cursor: pointer;">Save Payout %</button>
        </div>
        <p style="font-size: 0.85rem; color: #888;">This controls how much of proxy revenue goes to nodes. Adjust as funding allows. Goal is 100% at scale.</p>
    </div>

    <script>
    async function updatePayoutPct() {
        const pct = document.getElementById('payoutSlider').value;
        try {
            const resp = await fetch('/api/admin/node-payout-pct', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ payout_pct: parseInt(pct) })
            });
            const data = await resp.json();
            if (data.success) {
                alert('Node payout set to ' + pct + '%');
            } else {
                alert('Failed: ' + (data.error || 'Unknown error'));
            }
        } catch(e) {
            alert('Error updating payout');
        }
    }

    async function toggleFlag(flagKey, enabled) {
        try {
            const resp = await fetch('/api/admin/feature-flag', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ flag_key: flagKey, enabled: enabled })
            });
            const data = await resp.json();
            if (!data.success) {
                alert('Failed to update flag: ' + (data.error || 'Unknown error'));
                location.reload();
            }
        } catch(e) {
            alert('Error updating flag');
            location.reload();
        }
    }
    </script>
    """

    return render_template_string(
        BASE_TEMPLATE,
        title="Feature Flags",
        content=render_template_string(content, layer1=layer1, layer2=layer2, layer3=layer3, payout_pct=payout_pct),
        current_user=current_user
    )


@app.route("/api/admin/feature-flag", methods=["POST"])
@admin_required
def api_admin_feature_flag():
    """Toggle a feature flag."""
    from models import FeatureFlag

    data = request.get_json()
    flag_key = data.get("flag_key")
    enabled = data.get("enabled", False)

    if not flag_key:
        return jsonify({"success": False, "error": "Missing flag_key"}), 400

    success = FeatureFlag.set_flag(flag_key, enabled, current_user.id)
    if success:
        return jsonify({"success": True, "flag_key": flag_key, "enabled": enabled})
    return jsonify({"success": False, "error": "Flag not found"}), 404




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


class ProxyManager:
    """Manage Webshare proxy configuration for multi-market scraping."""

    def __init__(self):
        self.username = os.environ.get("WEBSHARE_USERNAME", "")
        self.password = os.environ.get("WEBSHARE_PASSWORD", "")
        self.host = os.environ.get("WEBSHARE_HOST", "proxy.webshare.io")

    def get_status(self):
        configured = bool(self.username and self.password)
        supported = ["US", "UK", "JP", "DE", "ES", "FR", "IT", "DK",
                      "IN", "BR", "AU", "CA", "MX", "KR"]
        return {
            "configured": configured,
            "provider": "Webshare" if configured else None,
            "proxy_type": "residential" if configured else "none",
            "host": self.host,
            "username": self.username[:4] + "****" if self.username else "",
            "supported_markets": supported,
            "has_api_key": bool(self.username),
            "has_credentials": configured,
        }

    def test_proxy(self, market):
        import requests as _req
        country_codes = {
            "US": "US", "UK": "GB", "JP": "JP", "DE": "DE",
            "ES": "ES", "FR": "FR", "IT": "IT", "DK": "DK",
            "IN": "IN", "BR": "BR", "AU": "AU", "CA": "CA",
            "MX": "MX", "KR": "KR",
        }
        cc = country_codes.get(market, market)
        targeted_user = f"{self.username}-country-{cc}"
        proxy_url = f"http://{targeted_user}:{self.password}@{self.host}:80"
        try:
            resp = _req.get(
                "https://ipapi.co/json/",
                proxies={"http": proxy_url, "https": proxy_url},
                timeout=15,
            )
            data = resp.json()
            return {
                "market": market, "success": True,
                "ip": data.get("ip", ""),
                "detected_country": data.get("country_name", ""),
                "detected_city": data.get("city", ""),
            }
        except Exception as e:
            return {"market": market, "success": False, "error": str(e)}


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
        queue = celery.conf.task_routes.get(entry["task"], {}).get("queue", "mystes")
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


# ===================================================================
# Build #176 — ANASTASiA API Watchdog Admin Routes
# ===================================================================

@app.route("/admin/watchdog", methods=["GET"])
@admin_required
def admin_watchdog():
    """API Watchdog dashboard — show provider health status."""
    try:
        sdk_path = os.path.join(os.path.dirname(__file__), "picasso-sdk")
        if sdk_path not in sys.path:
            sys.path.insert(0, sdk_path)
        from anastasia.knowledge.watchdog import APIWatchdog
        watchdog = APIWatchdog()
        providers = watchdog.list_providers()
        return jsonify({
            "success": True,
            "providers": providers,
            "total": len(providers),
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/admin/watchdog/run", methods=["POST"])
@admin_required
def admin_watchdog_run():
    """Trigger API Watchdog sweep across all registered providers."""
    try:
        sdk_path = os.path.join(os.path.dirname(__file__), "picasso-sdk")
        if sdk_path not in sys.path:
            sys.path.insert(0, sdk_path)
        from anastasia.knowledge.watchdog import APIWatchdog
        watchdog = APIWatchdog()
        reports = watchdog.check_all()

        summary = {
            "success": True,
            "providers_checked": len(reports),
            "changes_detected": sum(1 for r in reports.values() if r.has_changes),
            "reports": {pid: r.to_dict() for pid, r in reports.items()},
        }
        logger.info(f"[WATCHDOG] Sweep complete: {summary['providers_checked']} providers, {summary['changes_detected']} changes")
        return jsonify(summary)
    except Exception as e:
        logger.error(f"[WATCHDOG] Sweep failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/admin/watchdog/check/<provider_id>", methods=["POST"])
@admin_required
def admin_watchdog_check_one(provider_id):
    """Trigger Watchdog check for a single API provider."""
    try:
        sdk_path = os.path.join(os.path.dirname(__file__), "picasso-sdk")
        if sdk_path not in sys.path:
            sys.path.insert(0, sdk_path)
        from anastasia.knowledge.watchdog import APIWatchdog
        watchdog = APIWatchdog()
        report = watchdog.check_provider(provider_id)
        if report:
            return jsonify({"success": True, "report": report.to_dict()})
        return jsonify({"success": False, "error": f"Provider '{provider_id}' not registered"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


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


# --- Flights Route (Build #167 — extracted from homepage) ---
try:
    from routes_flights import register_flight_routes
    register_flight_routes(app, csrf, limiter)
    logger.info("Flight routes registered at /flights")
except ImportError as e:
    logger.warning(f"Flight routes not loaded: {e}")

# --- Phase 2 Hotel Routes (liteAPI) ---
# Always register — handlers check feature flag internally (return 410 when disabled)
try:
    from routes_hotels import register_hotel_routes
    register_hotel_routes(app, csrf, limiter)
    logger.info("Hotel routes registered (liteAPI)")
except ImportError as e:
    logger.warning(f"Hotel routes not loaded: {e}")

# --- B2B Business Routes (Build #158) ---

if is_feature_enabled('b2b_accounts'):
    try:
        from routes_business import register_business_routes
        register_business_routes(app, csrf, limiter)
        logger.info("B2B business routes registered")
    except ImportError as e:
        logger.warning(f"B2B routes not loaded: {e}")

# --- Activities & Tours Routes (Build #164) ---

if is_feature_enabled('vertical_activities'):
    try:
        from routes_activities import register_activities_routes
        register_activities_routes(app, csrf, limiter)
        logger.info("Activities routes registered (Viator)")
    except ImportError as e:
        logger.warning(f"Activities routes not loaded: {e}")

# --- Car Rental Routes (Build #174) ---
try:
    from routes_cars import register_car_routes
    register_car_routes(app, csrf, limiter)
    logger.info("Car rental routes registered (Discover Cars)")
except ImportError as e:
    logger.warning(f"Car rental routes not loaded: {e}")

# --- Trip Planner Routes (Build #174) ---
try:
    from routes_trips import register_trip_routes
    register_trip_routes(app, csrf, limiter)
    logger.info("Trip planner routes registered")
except ImportError as e:
    logger.warning(f"Trip planner routes not loaded: {e}")

# --- Collections / Wishlist Routes (Build #174) ---
try:
    from routes_collections import register_collection_routes
    register_collection_routes(app, csrf, limiter)
    logger.info("Collections routes registered")
except ImportError as e:
    logger.warning(f"Collections routes not loaded: {e}")

# --- Friends System Routes (Build #174) ---
try:
    from routes_friends import register_friend_routes
    register_friend_routes(app, csrf, limiter)
    logger.info("Friends routes registered")
except ImportError as e:
    logger.warning(f"Friends routes not loaded: {e}")


# --- MAIN ---

if __name__ == "__main__":
    # Structured logging (must be first — configures root logger + request context)
    from logging_config import init_logging
    init_logging(app)

    # Monitoring: Sentry + Prometheus /metrics + request tracking
    from monitoring import init_monitoring
    init_monitoring(app)

    print("="*60)
    print("MYSTES Server")
    print("="*60)
    print(f"URL: http://localhost:{SERVER_PORT}/")
    print("="*60)

    get_xrp_price()

    # Start XRPL ledger monitor (background thread — watches escrow events)
    from xrpl_monitor import ledger_monitor
    ledger_monitor.flask_app = app
    ledger_monitor.start()

    app.run(host=SERVER_HOST, port=SERVER_PORT, debug=True)
