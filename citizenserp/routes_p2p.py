"""
routes_p2p.py — Phase 2 P2P, CitizenSERP, Helper Network, Portal,
Intelligence, Node, and related routes extracted from server.py.

Extracted line ranges from server.py:
  Group A: 8235-9180  (EARN_CONTENT, /earn, PORTAL_CONTENT, /portal, Portal API, Browse data, Zone/network economics)
  Group B: 9182-9335  (NODE_YIELD_DASHBOARD_CONTENT, /node/dashboard)
  Group C: 11235-11553 (Portal AI search/providers/history/credits, Intelligence routes)
  Group D: 11654-11797 (Geographic zone API, CitizenSERP task API)
  Group E: 11802-12291 (Private market deal CRUD, Deal links, Public deal links, Share links, Contract templates)
  Group F: 12704-13596 (HELPER_DASHBOARD_CONTENT, helper routes, BROWSING_DASHBOARD_CONTENT, P2P matching/escrow/orchestrator)
  Group G: 17977-18452 (P2P_BOOK_CONTENT, P2P_STATUS_CONTENT, P2P booking page routes)
  Group H: 19073-19090, 19719-20062, 20167-20603 (admin node payout, ADMIN_P2P/HELPERS/NODE_FLEET/DISBURSEMENT, admin routes)
  Group I: 20606-21064, 21067-21111, 21154-21234, 21237-21994 (node registry, onboarding, pipelines, feedback, disputes, extension, installer, seed blocks, BYOAI, Strategy, Consent, DataMarketplace)

Usage:
    from routes_p2p import register_p2p_routes
    register_p2p_routes(app, csrf, limiter)
"""

import json
import logging
import os
import re
from datetime import datetime, timedelta, date
from functools import wraps

from flask import (
    Flask, jsonify, redirect, render_template_string, request,
    Response, flash, url_for, abort, send_file,
)
from flask_login import current_user, login_required

from models import (
    db, User, HelperProfile, P2PTransaction, P2PEscrow,
    BrowsingEvent, UserWallet, UserCard, PrivateMarketDeal,
    AISearchQuery, NodePayout,
)
from templates.base_template import BASE_TEMPLATE

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("audit")

# ---------------------------------------------------------------------------
# Shared helpers (copied from server.py so the module is self-contained)
# ---------------------------------------------------------------------------

def audit_log(action, user_id=None, **details):
    """Log a financial or security-relevant event for audit trail."""
    extra = {"action": action, "user_id": user_id, **details}
    audit_logger.info(
        f"AUDIT action={action} user={user_id} {' '.join(f'{k}={v}' for k,v in details.items())}",
        extra=extra,
    )


def is_feature_enabled(flag_key):
    """Check if a feature flag is enabled. Use this throughout the codebase."""
    try:
        from models import FeatureFlag
        return FeatureFlag.is_flag_enabled(flag_key)
    except Exception:
        # Default to False if there's any error (DB not ready, etc.)
        return False


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


# ---------------------------------------------------------------------------
# ADMIN_NAV
# ---------------------------------------------------------------------------

ADMIN_NAV = """
<nav style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:20px;padding:12px 16px;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:8px;">
    <a href="/admin" style="padding:6px 14px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:600;color:#e8e8e8;background:rgba(255,255,255,0.08);transition:background 0.2s;" onmouseover="this.style.background='rgba(124,58,237,0.3)'" onmouseout="this.style.background='rgba(255,255,255,0.08)'">Dashboard</a>
    <a href="/admin/payments" style="padding:6px 14px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:600;color:#e8e8e8;background:rgba(255,255,255,0.08);transition:background 0.2s;" onmouseover="this.style.background='rgba(124,58,237,0.3)'" onmouseout="this.style.background='rgba(255,255,255,0.08)'">Payments</a>
    <a href="/admin/users" style="padding:6px 14px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:600;color:#e8e8e8;background:rgba(255,255,255,0.08);transition:background 0.2s;" onmouseover="this.style.background='rgba(124,58,237,0.3)'" onmouseout="this.style.background='rgba(255,255,255,0.08)'">Users</a>
    <a href="/admin/deals" style="padding:6px 14px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:600;color:#e8e8e8;background:rgba(255,255,255,0.08);transition:background 0.2s;" onmouseover="this.style.background='rgba(124,58,237,0.3)'" onmouseout="this.style.background='rgba(255,255,255,0.08)'">Deals</a>
    <a href="/admin/wallet" style="padding:6px 14px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:600;color:#e8e8e8;background:rgba(255,255,255,0.08);transition:background 0.2s;" onmouseover="this.style.background='rgba(124,58,237,0.3)'" onmouseout="this.style.background='rgba(255,255,255,0.08)'">Wallet</a>
    <a href="/admin/proxies" style="padding:6px 14px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:600;color:#e8e8e8;background:rgba(255,255,255,0.08);transition:background 0.2s;" onmouseover="this.style.background='rgba(124,58,237,0.3)'" onmouseout="this.style.background='rgba(255,255,255,0.08)'">Proxies</a>
    <a href="/admin/p2p" style="padding:6px 14px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:600;color:#7c3aed;background:rgba(124,58,237,0.1);transition:background 0.2s;" onmouseover="this.style.background='rgba(124,58,237,0.3)'" onmouseout="this.style.background='rgba(124,58,237,0.1)'">P2P</a>
    <a href="/admin/helpers" style="padding:6px 14px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:600;color:#e8e8e8;background:rgba(255,255,255,0.08);transition:background 0.2s;" onmouseover="this.style.background='rgba(124,58,237,0.3)'" onmouseout="this.style.background='rgba(255,255,255,0.08)'">Helpers</a>
    <a href="/admin/tasks" style="padding:6px 14px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:600;color:#e8e8e8;background:rgba(255,255,255,0.08);transition:background 0.2s;" onmouseover="this.style.background='rgba(124,58,237,0.3)'" onmouseout="this.style.background='rgba(255,255,255,0.08)'">Tasks</a>
    <a href="/admin/nodes" style="padding:6px 14px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:600;color:#0f9d58;background:rgba(15,157,88,0.1);transition:background 0.2s;" onmouseover="this.style.background='rgba(15,157,88,0.3)'" onmouseout="this.style.background='rgba(15,157,88,0.1)'">Nodes</a>
    <a href="/admin/payouts" style="padding:6px 14px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:600;color:#e8e8e8;background:rgba(255,255,255,0.08);transition:background 0.2s;" onmouseover="this.style.background='rgba(124,58,237,0.3)'" onmouseout="this.style.background='rgba(255,255,255,0.08)'">Payouts</a>
    <a href="/admin/node-consent" style="padding:6px 14px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:600;color:#00bcd4;background:rgba(0,188,212,0.1);transition:background 0.2s;" onmouseover="this.style.background='rgba(0,188,212,0.3)'" onmouseout="this.style.background='rgba(0,188,212,0.1)'">Consent Economy</a>
    <a href="/admin/features" style="padding:6px 14px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:600;color:#ffd700;background:rgba(255,215,0,0.15);transition:background 0.2s;" onmouseover="this.style.background='rgba(255,215,0,0.3)'" onmouseout="this.style.background='rgba(255,215,0,0.15)'">Features</a>
    <a href="/admin/security" style="padding:6px 14px;border-radius:6px;text-decoration:none;font-size:13px;font-weight:600;color:#f44336;background:rgba(244,67,54,0.15);transition:background 0.2s;" onmouseover="this.style.background='rgba(244,67,54,0.3)'" onmouseout="this.style.background='rgba(244,67,54,0.15)'">Security</a>
</nav>
"""

# ---------------------------------------------------------------------------
# Rate limiter for public deal-link endpoints
# ---------------------------------------------------------------------------

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


def _node_network_check():
    """Return error response if node network is disabled. (Build #96)"""
    if not is_feature_enabled("node_onboarding"):
        return jsonify({"error": "Node network is not yet active"}), 503
    return None


# ===========================================================================
# TEMPLATE CONSTANTS
# ===========================================================================

# --- EARN WITH MYSTES (P2P Helper Network) ---

EARN_CONTENT = """
<div style="max-width: 900px; margin: 40px auto;">

    <!-- Hero Section -->
    <div class="card card-light" style="text-align: center; padding: 50px 40px; background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%); color: white; border: none;">
        <p style="font-size: 12px; color: #7c3aed; text-transform: uppercase; letter-spacing: 3px; margin-bottom: 8px;">The Citizen SerpAPI</p>
        <h1 style="color: #7c3aed; margin-bottom: 10px; font-size: 36px;">Earn With MYSTES</h1>
        <p style="font-size: 22px; color: #fff; margin-bottom: 20px;">Turn your Google account into passive income</p>
        <p style="font-size: 16px; color: #fff; max-width: 600px; margin: 0 auto; line-height: 1.7;">
            Earn XRP every time MYSTES uses your account to find and book cheaper flights
            for travelers worldwide. You provide access. We handle everything else.
        </p>
    </div>

    <!-- The Mission -->
    <div class="card card-light" style="margin-top: 20px; background: #0d1117; color: white; border: 1px solid #30363d;">
        <h2 style="color: #7c3aed; margin-bottom: 15px;">The Honest API</h2>
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
        <p style="color: #7c3aed; line-height: 1.8; font-size: 16px; font-weight: bold; margin-top: 15px;">
            MYSTES is the people's data network. We don't scrape data to sell to corporations.
            We use it to save travelers money &mdash; and we pay <em>you</em> for access instead of data farms.
        </p>
    </div>

    <!-- The Pitch: Take Back Your Data -->
    <div class="card card-light" style="margin-top: 20px; border-left: 4px solid #7c3aed;">
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
        <p style="color: #7c3aed; line-height: 1.8; font-size: 16px; font-weight: bold; margin-top: 15px;">
            MYSTES flips this system. Instead of corporations profiting from your data, <em>you</em> profit from it.
        </p>
    </div>

    <!-- How It Works -->
    <div class="card card-light" style="margin-top: 20px;">
        <h2 style="color: #1a1a2e; margin-bottom: 20px;">How Earning Works</h2>

        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 20px;">
            <div style="text-align: center; padding: 25px 15px; background: #f8f9fa; border-radius: 12px;">
                <div style="font-size: 36px; margin-bottom: 10px; color: #7c3aed;">1</div>
                <h4 style="color: #1a1a2e; margin-bottom: 8px;">Sign Up as a Helper</h4>
                <p style="color: #666; font-size: 14px; line-height: 1.6;">
                    Connect your XRPL wallet and grant MYSTES temporary access to your browser session. Your Google account stays yours.
                </p>
            </div>
            <div style="text-align: center; padding: 25px 15px; background: #f8f9fa; border-radius: 12px;">
                <div style="font-size: 36px; margin-bottom: 10px; color: #7c3aed;">2</div>
                <h4 style="color: #1a1a2e; margin-bottom: 8px;">MYSTES Does the Work</h4>
                <p style="color: #666; font-size: 14px; line-height: 1.6;">
                    When a traveler needs a flight booked through your region, MYSTES remotely handles the search and purchase through your browser. You don't lift a finger.
                </p>
            </div>
            <div style="text-align: center; padding: 25px 15px; background: #f8f9fa; border-radius: 12px;">
                <div style="font-size: 36px; margin-bottom: 10px; color: #7c3aed;">3</div>
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
                <h4 style="color: #2e7d32; margin-bottom: 8px;">The MYSTES Way</h4>
                <ul style="color: #666; font-size: 14px; line-height: 2; list-style: none; padding: 0; margin: 0;">
                    <li>You control access to your account</li>
                    <li>You earn from every transaction through your region</li>
                    <li>Real users replace expensive data farms</li>
                    <li>Savings go to travelers, earnings go to you</li>
                </ul>
            </div>
        </div>

        <p style="color: #555; line-height: 1.8; font-size: 15px; margin-top: 20px;">
            MYSTES doesn't need data centers or proxy farms. <strong>You are the network.</strong>
            Every helper with a Google account in a different country is a real endpoint that corporations
            cannot distinguish from organic traffic. Instead of paying data infrastructure companies,
            MYSTES pays <em>you</em> directly for access to networks that already exist &mdash; yours.
        </p>
        <p style="color: #555; line-height: 1.8; font-size: 15px;">
            When enough people join, this becomes a private, decentralized data network that no corporation
            can shut down. No proxy IPs to block. No data centers to subpoena. Just real people,
            running MYSTES passively, proving every day that the prices you see are not the prices
            that exist. <strong>Our data. Our profit.</strong>
        </p>
    </div>

    <!-- Trustless Payments -->
    <div class="card card-light" style="margin-top: 20px;">
        <h2 style="color: #1a1a2e; margin-bottom: 15px;">Trustless Payments on XRPL</h2>
        <p style="color: #555; line-height: 1.8; font-size: 15px;">
            You never have to trust MYSTES with your money &mdash; and we never have to trust you either.
            Everything runs through <strong>on-chain XRPL escrow</strong> that both parties can verify
            independently on the public ledger.
        </p>

        <div style="background: #f8f9fa; border-radius: 12px; padding: 25px; margin-top: 15px;">
            <div style="display: flex; flex-direction: column; gap: 12px;">
                <div style="display: flex; align-items: center; gap: 12px;">
                    <span style="background: #7c3aed; color: white; width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 14px; font-weight: bold; flex-shrink: 0;">1</span>
                    <span style="color: #555; font-size: 14px;">Traveler converts USD to RLUSD (1:1 stablecoin) and locks it in escrow</span>
                </div>
                <div style="display: flex; align-items: center; gap: 12px;">
                    <span style="background: #7c3aed; color: white; width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 14px; font-weight: bold; flex-shrink: 0;">2</span>
                    <span style="color: #555; font-size: 14px;">You verify the escrow is locked on-chain &mdash; visible on the XRPL ledger</span>
                </div>
                <div style="display: flex; align-items: center; gap: 12px;">
                    <span style="background: #7c3aed; color: white; width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 14px; font-weight: bold; flex-shrink: 0;">3</span>
                    <span style="color: #555; font-size: 14px;">You front the ticket purchase with your card (escrow guarantees reimbursement)</span>
                </div>
                <div style="display: flex; align-items: center; gap: 12px;">
                    <span style="background: #7c3aed; color: white; width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 14px; font-weight: bold; flex-shrink: 0;">4</span>
                    <span style="color: #555; font-size: 14px;">Booking confirms &rarr; escrow releases RLUSD to your wallet (reimbursement + your cut)</span>
                </div>
                <div style="display: flex; align-items: center; gap: 12px;">
                    <span style="background: #7c3aed; color: white; width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 14px; font-weight: bold; flex-shrink: 0;">5</span>
                    <span style="color: #555; font-size: 14px;">Use your RLUSD to book your own discounted flights &mdash; or cash out via any exchange</span>
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
                <p style="color: #555; font-size: 13px; margin-top: 8px;">Spend your RLUSD directly on discounted flights through MYSTES</p>
            </div>
        </div>
        <p style="color: #555; line-height: 1.8; font-size: 15px; margin-top: 20px;">
            Your earnings circulate in the MYSTES ecosystem. Use RLUSD to book your own flights at
            arbitrage prices, convert to XRP for other uses, or cash out to your local currency through
            Binance, Kraken, Uphold, or any major exchange.
        </p>
    </div>

    <!-- The Bigger Picture -->
    <div class="card card-light" style="margin-top: 20px; border-left: 4px solid #7c3aed;">
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
            MYSTES is the honest alternative. We don't sell data to corporations &mdash; we use it to
            save travelers money. And instead of routing through anonymous proxy farms,
            <strong>we pay real people directly</strong> for the access that data companies have
            been taking for free. MYSTES is a citizen-powered API that proves what the institutions
            won't admit: <strong>the prices you see are not the prices that exist.</strong>
        </p>
        <p style="color: #555; line-height: 1.8; font-size: 15px;">
            Every MYSTES helper is proof that the system is rigged &mdash; and that it doesn't have to be.
            The more people join, the more transparent the market becomes, and the harder it is
            for anyone to stop. This isn't just an app. It's a decentralized data network
            controlled by the people who power it.
        </p>
    </div>

    <!-- Data Sovereignty Pitch -->
    <div class="card card-light" style="margin-top: 20px; background: linear-gradient(135deg, #1a1a2e, #16213e); color: white; border: none;">
        <h2 style="color: #7c3aed; margin-bottom: 15px;">Take Back Your Data</h2>
        <p style="color: #fff; line-height: 1.8; font-size: 15px;">
            Every day, airlines use geographic price discrimination to overcharge millions of travelers.
            They use <em>your</em> IP address, <em>your</em> cookies, and <em>your</em> search patterns to determine
            how much they can charge you. The institutions profit. You don't.
        </p>
        <p style="color: #fff; line-height: 1.8; font-size: 15px;">
            MYSTES changes the equation. By joining the network, your Google account and local market access
            become a tool for global price transparency. Instead of data farms and proxy infrastructure
            profiting from internet access, <strong style="color: #7c3aed;">real people earn real money</strong>
            by contributing what they already have &mdash; a browser, an internet connection, and a location.
        </p>
        <p style="color: #fff; line-height: 1.8; font-size: 15px;">
            This isn't just about saving money on flights. It's about building a network where
            <strong style="color: #7c3aed;">consumers benefit from their own data</strong> instead of handing it
            to institutions for free. Every helper in the MYSTES network is a statement: our data, our profit.
        </p>
    </div>

    <!-- FAQ -->
    <div class="card card-light" style="margin-top: 20px;">
        <h2 style="color: #1a1a2e; margin-bottom: 20px;">Common Questions</h2>

        <div style="border-bottom: 1px solid #eee; padding-bottom: 15px; margin-bottom: 15px;">
            <h4 style="color: #1a1a2e; margin-bottom: 6px;">Do I have to do anything during a booking?</h4>
            <p style="color: #666; font-size: 14px; line-height: 1.7;">
                No. MYSTES handles everything remotely. When you're matched with a booking request,
                MYSTES takes temporary control of your browser session through the MYSTES app.
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
                MYSTES flights, convert to XRP on-ledger, or cash out to local currency through
                Binance, Kraken, Uphold, or other major exchanges.
            </p>
        </div>

        <div>
            <h4 style="color: #1a1a2e; margin-bottom: 6px;">Why use real people instead of proxy servers?</h4>
            <p style="color: #666; font-size: 14px; line-height: 1.7;">
                Proxy servers can be detected and blocked by airlines and Google. A real person with a
                real Google account, real browsing history, and a real IP address is indistinguishable
                from any other customer. MYSTES pays you directly for this access instead of paying
                data center companies for proxy infrastructure.
            </p>
        </div>
    </div>

    <!-- CTA -->
    <div style="text-align: center; margin-top: 30px; margin-bottom: 20px;">
        <a href="/register" class="btn" style="padding: 16px 50px; font-size: 18px; background: #7c3aed; color: white; border-radius: 8px; text-decoration: none; display: inline-block;">
            Start Earning With MYSTES
        </a>
        <p style="color: #fff; font-size: 13px; margin-top: 12px;">
            Connect your wallet. Grant access. Get paid.
        </p>
    </div>
</div>
"""


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
    .portal-hero .accent { color: #7c3aed; }
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
    .market-card:hover { border-color: #7c3aed; transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
    .market-card.selected { border-color: #7c3aed; background: #f5f3ff; }
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
    .cat-tab:hover { border-color: #7c3aed; }
    .cat-tab.active { background: #7c3aed; color: #fff; border-color: #7c3aed; }

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
        background: #7c3aed;
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
    .proxy-details h4 { color: #7c3aed; margin: 0 0 12px 0; }
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
    Stay logged into your own accounts — MYSTES just changes where the platform thinks you are.</p>
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
            <p>MYSTES allocates a sticky residential IP in your chosen country. You get proxy credentials valid for up to 4 hours.</p>
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
            <p>Your browser traffic routes through a residential IP in that country. Marketplaces see a local user. You stay logged into your own accounts (Facebook, Google, etc.) — MYSTES just changes the geographic routing.</p>
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
    <a href="/earn" style="display: inline-block; padding: 14px 32px; background: #7c3aed; color: #fff; border-radius: 8px; text-decoration: none; font-weight: 600;">Learn How to Earn</a>
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


# --- CitizenSERP Node Yield Dashboard ---

NODE_YIELD_DASHBOARD_CONTENT = """
<style>
    .yield-dashboard { max-width: 900px; margin: 0 auto; }
    .yield-header { text-align: center; margin-bottom: 30px; }
    .yield-header h1 { font-family: 'Cinzel', serif; letter-spacing: 5px; color: #c9a96e; font-size: 1.8rem; }
    .yield-header p { color: rgba(255,255,255,0.6); margin-top: 8px; }

    .yield-stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 30px; }
    .yield-stat-card {
        background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.08);
        border-radius: 12px; padding: 20px; text-align: center;
    }
    .yield-stat-card .stat-value { font-size: 1.8rem; font-weight: 700; color: #00e676; }
    .yield-stat-card .stat-label { color: rgba(255,255,255,0.5); font-size: 0.85rem; margin-top: 4px; }
    .yield-stat-card.offline .stat-value { color: #ff5252; }

    .yield-section { background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06);
        border-radius: 12px; padding: 24px; margin-bottom: 20px; }
    .yield-section h2 { color: #c9a96e; font-size: 1.1rem; margin-bottom: 16px; font-family: 'Cinzel', serif; letter-spacing: 2px; }

    .category-row { display: flex; justify-content: space-between; align-items: center;
        padding: 10px 0; border-bottom: 1px solid rgba(255,255,255,0.05); }
    .category-row:last-child { border-bottom: none; }
    .category-name { color: rgba(255,255,255,0.8); font-size: 0.9rem; }
    .category-value { color: #00e676; font-weight: 600; }
    .category-bar { height: 4px; background: rgba(255,255,255,0.1); border-radius: 2px; margin-top: 4px; }
    .category-bar-fill { height: 100%; background: linear-gradient(90deg, #00e676, #c9a96e); border-radius: 2px; }

    .suggestion-card { background: rgba(0,230,118,0.05); border: 1px solid rgba(0,230,118,0.15);
        border-radius: 8px; padding: 14px; margin-bottom: 10px; }
    .suggestion-card .est { color: #00e676; font-weight: 600; }

    .yield-score-ring { width: 100px; height: 100px; margin: 0 auto 12px; position: relative; }
    .yield-score-value { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
        font-size: 1.6rem; font-weight: 700; color: #c9a96e; }

    .yield-cta { text-align: center; margin-top: 30px; }
    .yield-cta a { display: inline-block; padding: 14px 32px; background: linear-gradient(135deg, #c9a96e, #e8d5b7);
        color: #0a0612; font-weight: 700; border-radius: 8px; text-decoration: none; font-family: 'Cinzel', serif;
        letter-spacing: 2px; }
</style>

<div class="yield-dashboard" id="yieldDash">
    <div class="yield-header">
        <h1>NODE YIELD DASHBOARD</h1>
        <p>Your CitizenSERP earnings at a glance</p>
    </div>

    <div class="yield-stats" id="yieldStats">
        <div class="yield-stat-card"><div class="stat-value" id="statStatus">--</div><div class="stat-label">Status</div></div>
        <div class="yield-stat-card"><div class="stat-value" id="statToday">$0.00</div><div class="stat-label">Today</div></div>
        <div class="yield-stat-card"><div class="stat-value" id="statWeek">$0.00</div><div class="stat-label">This Week</div></div>
        <div class="yield-stat-card"><div class="stat-value" id="statTotal">$0.00</div><div class="stat-label">All Time</div></div>
    </div>

    <div class="yield-section">
        <h2>EARNINGS BY CATEGORY</h2>
        <div id="categoryBreakdown"><p style="color:rgba(255,255,255,0.4);">Loading...</p></div>
    </div>

    <div class="yield-section">
        <h2>YIELD OPTIMIZER</h2>
        <p style="color:rgba(255,255,255,0.5);font-size:0.9rem;margin-bottom:12px;">Enable more data categories to increase your earnings</p>
        <div id="yieldSuggestions"><p style="color:rgba(255,255,255,0.4);">Loading...</p></div>
    </div>

    <div class="yield-section">
        <h2>NETWORK PROJECTIONS</h2>
        <p style="color:rgba(255,255,255,0.5);font-size:0.9rem;margin-bottom:12px;">Estimated monthly earnings by tier at current network size</p>
        <div id="tierProjections"><p style="color:rgba(255,255,255,0.4);">Loading...</p></div>
    </div>

    <div class="yield-cta">
        <a href="/earn">LEARN HOW TO EARN MORE</a>
    </div>
</div>

<script>
(function() {
    async function loadDashboard() {
        try {
            // Load yield summary
            const summaryResp = await fetch('/api/zones/leaderboard');
            if (summaryResp.ok) {
                const data = await summaryResp.json();
                const net = data.network_totals || {};
                document.getElementById('statStatus').textContent = net.total_nodes > 0 ? 'Online' : 'Offline';
                document.getElementById('statStatus').parentElement.className = net.total_nodes > 0 ? 'yield-stat-card' : 'yield-stat-card offline';
            }
        } catch(e) { console.warn('Dashboard load error:', e); }

        try {
            // Load earnings projection for all tiers
            const projResp = await fetch('/api/network/earnings-projection?nodes=500&tier=bronze');
            if (projResp.ok) {
                const proj = await projResp.json();
                const comp = proj.comparison?.all_tiers || {};
                let tierHtml = '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;">';
                ['bronze','silver','gold','platinum'].forEach(t => {
                    const monthly = comp[t] || 0;
                    tierHtml += '<div style="text-align:center;padding:12px;background:rgba(255,255,255,0.03);border-radius:8px;">';
                    tierHtml += '<div style="color:rgba(255,255,255,0.5);font-size:0.8rem;text-transform:uppercase;letter-spacing:1px;">' + t + '</div>';
                    tierHtml += '<div style="color:#00e676;font-size:1.2rem;font-weight:700;margin-top:4px;">$' + monthly.toFixed(2) + '/mo</div>';
                    tierHtml += '</div>';
                });
                tierHtml += '</div>';
                document.getElementById('tierProjections').innerHTML = tierHtml;

                // Category breakdown from projection
                const exclusive = proj.exclusive_products || [];
                let catHtml = '';
                exclusive.filter(p => p.unlocked).forEach(p => {
                    const pct = proj.earnings.exclusive_monthly_usd > 0 ? (p.monthly_usd / proj.earnings.exclusive_monthly_usd * 100) : 0;
                    catHtml += '<div class="category-row"><span class="category-name">' + p.display_name + '</span>';
                    catHtml += '<span class="category-value">$' + p.monthly_usd.toFixed(2) + '/mo</span></div>';
                    catHtml += '<div class="category-bar"><div class="category-bar-fill" style="width:' + Math.min(pct, 100) + '%"></div></div>';
                });
                if (catHtml) document.getElementById('categoryBreakdown').innerHTML = catHtml;

                // Suggestions for locked products
                const locked = exclusive.filter(p => !p.unlocked);
                if (locked.length > 0) {
                    let sugHtml = '';
                    locked.slice(0, 3).forEach(p => {
                        sugHtml += '<div class="suggestion-card">';
                        sugHtml += '<strong>' + p.display_name + '</strong>';
                        sugHtml += '<div style="color:rgba(255,255,255,0.5);font-size:0.85rem;margin-top:4px;">' + (p.description || 'Unlocks at ' + (p.unlocks_at_nodes || '?') + ' nodes') + '</div>';
                        sugHtml += '</div>';
                    });
                    document.getElementById('yieldSuggestions').innerHTML = sugHtml;
                } else {
                    document.getElementById('yieldSuggestions').innerHTML = '<p style="color:#00e676;">All data categories unlocked!</p>';
                }
            }
        } catch(e) { console.warn('Projection load error:', e); }
    }
    loadDashboard();
})();
</script>
"""


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
    .chart-bar { width: 100%; min-width: 20px; max-width: 40px; background: linear-gradient(180deg, #7c3aed, #6d28d9); border-radius: 4px 4px 0 0; transition: height 0.3s ease; position: relative; }
    .chart-bar:hover { opacity: 0.85; }
    .chart-bar-label { font-size: 10px; color: #fff; margin-top: 6px; }
    .chart-bar-value { font-size: 9px; color: #666; position: absolute; top: -16px; left: 50%; transform: translateX(-50%); white-space: nowrap; }
    .earnings-summary { display: flex; gap: 20px; flex-wrap: wrap; margin-top: 12px; }
    .earnings-period { padding: 10px 16px; background: white; border: 1px solid #eee; border-radius: 8px; }
    .earnings-period strong { display: block; color: #7c3aed; font-size: 18px; }
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
            <h2 style="color: #1a1a2e; margin-bottom: 10px;">Become a MYSTES Helper</h2>
            <p style="color: #666; margin-bottom: 20px; max-width: 500px; margin-left: auto; margin-right: auto;">
                Earn RLUSD by allowing MYSTES to use your browser session for flight bookings in your market.
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
                <div class="helper-stat-value" style="color: #7c3aed;">{{ helper.total_earned_rlusd | round(2) }}</div>
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
                    <p>When active, MYSTES may use your browser session for bookings.</p>
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
                <p style="color: #fff; font-style: italic; padding: 20px 0;">No transactions yet. Once MYSTES matches you with a booking request, it will appear here.</p>
            {% endif %}
        </div>

        {% endif %}

        <!-- Quick Links -->
        <div class="quick-links">
            <a href="/wallet" class="btn" style="padding: 10px 20px; font-size: 14px; background: #1a1a2e; color: white; border-radius: 8px; text-decoration: none;">Manage Wallet</a>
            <a href="/p2p/my-bookings" class="btn" style="padding: 10px 20px; font-size: 14px; background: #f0f0f0; color: #333; border-radius: 8px; text-decoration: none;">My Bookings</a>
            <a href="/earn" style="padding: 10px 20px; font-size: 14px; color: #7c3aed; text-decoration: none;">Learn More</a>
        </div>
    </div>
</div>
"""


# --- BROWSING DASHBOARD ---

BROWSING_DASHBOARD_CONTENT = """
<div style="max-width: 900px; margin: 0 auto; padding: 30px 20px;">
    <h2 style="color: #7c3aed; margin-bottom: 5px;">Browser Extension Dashboard</h2>
    <p style="color: #fff; margin-bottom: 25px;">Passive browsing data earnings from the MYSTES Chrome extension.</p>

    <!-- Connection Status -->
    <div style="background: rgba(35,41,47,0.6); border-radius: 12px; padding: 20px; margin-bottom: 20px; border: 1px solid rgba(124,58,237,0.2);">
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
        <div style="font-size: 15px; font-weight: 600; color: #7c3aed; margin-bottom: 12px;">Helper Token</div>
        {% if helper and helper.helper_token %}
            <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
                <code id="token-display" style="background: #1a1a2e; padding: 8px 14px; border-radius: 6px; color: #fff; font-size: 13px; word-break: break-all;">{{ helper.helper_token }}</code>
                <button onclick="navigator.clipboard.writeText(document.getElementById('token-display').textContent).then(()=>{this.textContent='Copied!';setTimeout(()=>{this.textContent='Copy'},1500)})" style="padding: 8px 16px; background: #7c3aed; color: white; border: none; border-radius: 6px; cursor: pointer; font-size: 13px;">Copy</button>
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
            <div style="font-size: 24px; font-weight: 700; color: #7c3aed;">{{ '%.4f' | format(stats.totals.total_value_usd) }}</div>
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
        <div style="font-size: 15px; font-weight: 600; color: #7c3aed; margin-bottom: 15px;">Event Breakdown (7 days)</div>
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
                    <td style="padding: 10px 0; color: #7c3aed; text-align: right;">${{ '%.4f' | format(data.value_usd) }}</td>
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
        <div style="font-size: 15px; font-weight: 600; color: #7c3aed; margin-bottom: 12px;">Quick Setup</div>
        <ol style="color: #fff; line-height: 1.8; padding-left: 20px; margin: 0;">
            <li>Generate a helper token above (if you haven't already)</li>
            <li>Install the MYSTES Chrome extension from <code style="background: #1a1a2e; padding: 2px 6px; border-radius: 3px;">chrome://extensions</code> (load unpacked)</li>
            <li>Open extension options and paste your helper token</li>
            <li>Start the local node service: <code style="background: #1a1a2e; padding: 2px 6px; border-radius: 3px;">python node_service.py --token YOUR_TOKEN</code></li>
            <li>Browse normally — data is captured passively and you earn micropayments</li>
        </ol>
    </div>
</div>
"""


# --- P2P BOOKING FLOW ---

P2P_BOOK_CONTENT = """
<style>
.p2p-hero { background: linear-gradient(135deg, #1a0a2e 0%, #0d1b2a 50%, #1b2838 100%); padding: 40px; border-radius: 16px; color: white; margin-bottom: 30px; }
.p2p-hero h1 { margin: 0 0 10px 0; font-size: 28px; }
.p2p-hero .subtitle { color: #fff; font-size: 16px; }
.p2p-step { display: flex; gap: 20px; margin-bottom: 30px; }
.p2p-step-number { width: 40px; height: 40px; border-radius: 50%; background: #7c3aed; color: white; display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 18px; flex-shrink: 0; }
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
.escrow-info h3 { color: #7c3aed; margin-top: 0; }
.escrow-row { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,0.1); }
.escrow-row:last-child { border-bottom: none; }
.passenger-form .form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-bottom: 15px; }
.passenger-form label { display: block; font-size: 13px; color: #666; margin-bottom: 4px; }
.passenger-form input { width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 6px; font-size: 14px; box-sizing: border-box; }
.passenger-form input:focus { outline: none; border-color: #7c3aed; }
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
            <p>A verified helper in the {{ market }} market grants MYSTES temporary browser access. MYSTES automates the booking on their device.</p>
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
        <span style="color: #7c3aed;">{{ "%.2f"|format(total_escrow) }} RLUSD</span>
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

        <div style="margin-top: 15px; padding: 15px; background: #f0fdfa; border-radius: 8px; color: #664d03;">
            <strong>XRPL Wallet Required:</strong> You need an XRPL wallet with at least {{ "%.2f"|format(total_escrow) }} RLUSD to lock in escrow.
            {% if not current_user.is_authenticated %}
                <br><a href="/login" style="color: #7c3aed;">Log in</a> or <a href="/register" style="color: #7c3aed;">create an account</a> to continue.
            {% endif %}
        </div>

        <button type="submit" class="btn" style="width: 100%; margin-top: 20px; padding: 15px; font-size: 18px; background: #7c3aed; border-color: #7c3aed;">
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
.timeline-step.active .dot { background: #7c3aed; border-color: #7c3aed; animation: pulse 2s infinite; }
.timeline-step.failed .dot { background: #dc3545; border-color: #dc3545; }
.timeline-step h4 { margin: 0 0 4px 0; }
.timeline-step p { margin: 0; color: #666; font-size: 14px; }
.timeline-step .time { color: #fff; font-size: 12px; }
@keyframes pulse { 0%, 100% { box-shadow: 0 0 0 0 rgba(124,58,237,0.4); } 50% { box-shadow: 0 0 0 8px rgba(124,58,237,0); } }
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
            {% else %}background: #f0fdfa; color: #664d03;{% endif %}">
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


# --- ADMIN P2P ---

ADMIN_P2P_CONTENT = """
""" + ADMIN_NAV + """
<h1 style="color: #7c3aed;">P2P Network Management</h1>

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
                        {% else %}background: #f0fdfa; color: #664d03;{% endif %}">
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
                        {% else %}background: #f0fdfa; color: #664d03;{% endif %}">
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


# --- ADMIN NODE FLEET ---

ADMIN_NODE_FLEET_CONTENT = ADMIN_NAV + """
<h1 style="color: #7c3aed;">Node Fleet Dashboard</h1>
<p style="color: #fff;">Real-time monitoring of the MYSTES node network and browsing data pipeline.</p>

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
        <div class="stat-value" style="font-size:28px;font-weight:700;color:#7c3aed;">{{ fleet.with_tokens }}</div>
        <div class="stat-label" style="font-size:11px;color:#999;margin-top:4px;">With Tokens</div>
    </div>
    <div class="stat-card" style="background:rgba(35,41,47,0.6);border-radius:10px;padding:16px;text-align:center;border:1px solid rgba(255,255,255,0.05);">
        <div class="stat-value" style="font-size:28px;font-weight:700;color:#ddd;">{{ fleet.with_extension }}</div>
        <div class="stat-label" style="font-size:11px;color:#999;margin-top:4px;">Extension Connected</div>
    </div>
</div>

<!-- Data Pipeline Stats -->
<div style="background:rgba(35,41,47,0.6);border-radius:12px;padding:20px;margin-bottom:20px;border:1px solid rgba(255,255,255,0.05);">
    <div style="font-size:15px;font-weight:600;color:#7c3aed;margin-bottom:15px;">Data Pipeline (7 days)</div>
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
    <div style="font-size:15px;font-weight:600;color:#7c3aed;margin-bottom:15px;">Event Type Distribution</div>
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
                <td style="padding:10px 0;color:#7c3aed;text-align:right;">${{ '%.4f' | format(et.value) }}</td>
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
    <div style="font-size:15px;font-weight:600;color:#7c3aed;margin-bottom:15px;">Top Contributing Nodes (7 days)</div>
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
                <td style="padding:10px 0;color:#7c3aed;text-align:right;">${{ '%.4f' | format(node.value) }}</td>
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
    <div style="font-size:15px;font-weight:600;color:#7c3aed;margin-bottom:15px;">Processor Runtime</div>
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


# --- ADMIN DISBURSEMENT ---

ADMIN_DISBURSEMENT_CONTENT = ADMIN_NAV + """
<h1 style="color:#f5f5f5;margin-bottom:8px;">RLUSD Disbursement Dashboard</h1>
<p style="color:#999;margin-bottom:24px;">Payout processing, epoch management, and XRPL transaction monitoring.</p>

<!-- Summary Cards -->
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-bottom:24px;">
    <div style="background:rgba(255,255,255,0.05);padding:16px;border-radius:10px;border:1px solid rgba(255,255,255,0.1);">
        <div style="font-size:11px;color:#999;text-transform:uppercase;">Pending Payouts</div>
        <div style="font-size:28px;font-weight:700;color:#7c3aed;">{{ stats.pending_count }}</div>
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
        <div style="font-size:28px;font-weight:700;color:#7c3aed;">{{ "%.2f"|format(stats.total_disbursed) }}</div>
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
    <td style="padding:8px;text-align:right;color:#7c3aed;font-weight:600;">{{ "%.4f"|format(p.amount) }}</td>
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
<div style="margin-top:32px;padding:20px;background:rgba(124,58,237,0.05);border:1px solid rgba(124,58,237,0.2);border-radius:10px;">
    <h4 style="color:#7c3aed;margin:0 0 8px;">Manual Epoch Trigger</h4>
    <p style="color:#999;font-size:13px;margin:0 0 12px;">Manually trigger a new payout epoch for today. This will calculate node uptime, create payout records, and queue them for XRPL disbursement.</p>
    <form method="POST" action="/admin/payouts/trigger-epoch" style="display:inline;">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <button type="submit" style="padding:8px 20px;background:#7c3aed;color:#fff;border:none;border-radius:6px;cursor:pointer;font-weight:600;" onclick="return confirm('Trigger new payout epoch for today?')">Trigger Epoch</button>
    </form>
</div>
"""


# --- BYOAI SETTINGS ---

BYOAI_SETTINGS_CONTENT = """
<div style="max-width:900px;margin:0 auto;">
    <div style="margin-bottom:30px;">
        <h1 style="color:#fff;margin:0 0 8px 0;font-size:28px;">AI Provider Settings</h1>
        <p style="color:#aaa;margin:0;font-size:15px;">Bring Your Own AI (BYOAI) — connect your personal AI provider keys for flight search intelligence, or use MYSTESAI for optimized results.</p>
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

    <!-- MYSTESAI Comparison -->
    <div style="background:#16213e;border:1px solid rgba(0,212,255,0.2);border-radius:12px;padding:24px;margin-bottom:24px;">
        <h2 style="color:#00d4ff;margin:0 0 16px 0;font-size:20px;">MYSTESAI Comparison</h2>
        {% if comparison_stats %}
        <div style="background:rgba(0,212,255,0.08);border:1px solid rgba(0,212,255,0.15);border-radius:8px;padding:16px;margin-bottom:16px;">
            <p style="color:#fff;margin:0 0 8px 0;font-size:15px;font-weight:600;">Last Comparison Results</p>
            <p style="color:#00e676;margin:0;font-size:14px;">MYSTESAI found {{ comparison_stats.additional_pct }}% more results</p>
            <div style="display:flex;gap:20px;margin-top:10px;">
                <span style="color:#aaa;font-size:13px;">Your results: <strong style="color:#fff;">{{ comparison_stats.user_count }}</strong></span>
                <span style="color:#aaa;font-size:13px;">MYSTESAI results: <strong style="color:#00d4ff;">{{ comparison_stats.mystes_count }}</strong></span>
            </div>
        </div>
        {% endif %}
        <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;">
            <button onclick="runComparison()" id="compareBtn" style="padding:12px 24px;background:#00d4ff;color:#1a1a2e;border:none;border-radius:8px;cursor:pointer;font-size:14px;font-weight:600;" {% if not can_compare %}disabled style="opacity:0.5;cursor:not-allowed;"{% endif %}>Compare with MYSTESAI</button>
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

    <!-- Why MYSTESAI -->
    <div style="background:linear-gradient(135deg,#16213e 0%,#1a1a3e 100%);border:1px solid rgba(0,212,255,0.15);border-radius:12px;padding:24px;">
        <h2 style="color:#fff;margin:0 0 16px 0;font-size:20px;">Why MYSTESAI?</h2>
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
        html += '<tr style="border-bottom:1px solid rgba(255,255,255,0.1);"><th style="text-align:left;padding:8px;color:#aaa;">Metric</th><th style="text-align:left;padding:8px;color:#aaa;">BYOAI</th><th style="text-align:left;padding:8px;color:#aaa;">MYSTESAI</th></tr>';
        if (data.user_count !== undefined) {
            html += '<tr style="border-bottom:1px solid rgba(255,255,255,0.05);"><td style="padding:8px;">Results Found</td><td style="padding:8px;">' + (data.user_count || 0) + '</td><td style="padding:8px;color:#00d4ff;">' + (data.mystes_count || 0) + '</td></tr>';
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


# --- ADMIN STRATEGY ---

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
            <div style="height:100%;border-radius:4px;width:{{ pct }}%;background:{% if source_name == 'ensemble' %}#00d4ff{% elif source_name == 'byoai' %}#00e676{% elif source_name == 'mystes_ai' %}#ff9800{% elif source_name == 'serp' %}#ba68c8{% else %}#888{% endif %};"></div>
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


# --- DATA MARKETPLACE ADMIN ---

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
            <div style="color:#7c3aed;font-size:28px;font-weight:700;">{{ stats.total_products|default(22) }}</div>
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
                        <td style="padding:10px;color:#7c3aed;font-size:13px;text-align:right;">{{ record.credits_consumed }}</td>
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
            <div style="color:#7c3aed;font-size:32px;font-weight:700;">{{ stats.pending_exports|default(0) }}</div>
            <div style="color:#aaa;font-size:13px;margin-top:4px;">{{ stats.completed_exports|default(0) }} completed</div>
        </div>
    </div>
</div>
"""


# --- NODE CONSENT ADMIN ---

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
            <div style="color:#7c3aed;font-size:32px;font-weight:700;">{{ "%.1f"|format(stats.avg_tier_score|default(0)) }}</div>
        </div>
        <div style="background:#16213e;border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:24px;">
            <h2 style="color:#fff;margin:0 0 16px 0;font-size:18px;">Total Allocated</h2>
            <div style="color:#7c3aed;font-size:32px;font-weight:700;">${{ "%.2f"|format(stats.total_fees_allocated|default(0)) }}</div>
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
                    <span style="color:#aaa;">Platform Profit</span><span style="color:#7c3aed;font-weight:600;">${{ "%.2f"|format(stats.total_platform_profit|default(0)) }}</span>
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
                    <span style="color:#aaa;">Bonuses Paid</span><span style="color:#7c3aed;font-weight:600;">${{ "%.2f"|format(stats.total_referral_bonuses|default(0)) }}</span>
                </div>
            </div>
        </div>
    </div>
</div>
"""


# ===========================================================================
# ROUTE REGISTRATION
# ===========================================================================

def register_p2p_routes(app, csrf, limiter):
    """Register all Phase 2 P2P, CitizenSERP, helper, portal, intelligence,
    node, and admin routes onto the Flask app."""

    @app.route("/earn")
    def earn():
        """Earn with MYSTES - P2P helper network pitch page."""
        return render_template_string(
            BASE_TEMPLATE,
            title="Earn With MYSTES",
            content=EARN_CONTENT,
            current_user=current_user
        )


    @app.route("/portal")
    @login_required
    def portal():
        """Proxy Portal - Universal market access gateway."""
        return render_template_string(
            BASE_TEMPLATE,
            title="Proxy Portal — MYSTES",
            content=PORTAL_CONTENT,
            current_user=current_user
        )


    @app.route("/api/portal/session", methods=["POST"])
    @login_required
    def api_portal_create_session():
        """Create a Free Browse session through a CitizenSERP node.

        Build #90 — unmetered.  User's own browser through a node;
        MYSTES monitors passively.
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



    @app.route("/node/dashboard")
    @login_required
    def node_yield_dashboard_page():
        """CitizenSERP node yield dashboard — shows earnings, categories, and optimization."""
        return render_template_string(
            BASE_TEMPLATE,
            title="Node Yield Dashboard",
            content=NODE_YIELD_DASHBOARD_CONTENT,
            current_user=current_user,
        )


    @app.route("/api/portal/ai/search", methods=["POST"])
    @login_required
    @limiter.limit("30/day")
    def api_ai_search():
        """Ensemble AI search — queries multiple providers in parallel."""
        from ai_search import mystes_ai
        data = request.get_json() or {}
        query = data.get("query", "").strip()
        if not query:
            return jsonify({"error": "Query required"}), 400
        if len(query) > 2000:
            return jsonify({"error": "Query too long (max 2000 chars)"}), 400

        market = data.get("market")
        providers = data.get("providers")  # optional list of provider keys

        result = mystes_ai.search(
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
        from ai_search import mystes_ai, AI_PROVIDERS
        platform = mystes_ai.get_platform_providers()
        user_provs = mystes_ai.get_user_providers(current_user.id)

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
        from ai_search import mystes_ai
        data = request.get_json() or {}
        provider = data.get("provider", "").strip()
        api_key = data.get("api_key")
        model = data.get("model")

        if not provider:
            return jsonify({"error": "Provider required"}), 400

        result = mystes_ai.add_user_provider(
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
        from ai_search import mystes_ai
        success = mystes_ai.remove_user_provider(current_user.id, provider)
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
        from ai_search import mystes_ai, FREE_QUERIES_PER_DAY
        from models import AISearchQuery
        balance = mystes_ai.get_user_credits(current_user.id)
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
            from mystes_intelligence import intelligence
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
            from mystes_intelligence import intelligence
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
            from mystes_intelligence import intelligence
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
            from mystes_intelligence import intelligence
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
            from mystes_intelligence import intelligence
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
            from mystes_intelligence import intelligence
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
            from mystes_intelligence import intelligence
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
            from mystes_intelligence import intelligence
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
            from mystes_intelligence import intelligence
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
            from mystes_intelligence import intelligence
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
            from mystes_intelligence import intelligence
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
            from mystes_intelligence import intelligence
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
            from mystes_intelligence import intelligence
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
            from mystes_intelligence import intelligence
            days = int(request.args.get("days", 7))
            data = intelligence.get_airline_comparison(origin.upper(), dest.upper(), days_back=days)
            return jsonify(data)
        except Exception as e:
            logger.error(f"Airline intelligence error: {e}")
            return jsonify({"error": "Intelligence unavailable"}), 500



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


    @app.route("/api/portal/deal/create", methods=["POST"])
    @login_required
    def api_deal_create():
        """Create a private market deal draft with AI assessment."""
        from ai_search import mystes_ai
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
        contract = mystes_ai.build_deal_contract(current_user.id, data)

        # Create deal record
        deal = mystes_ai.create_private_deal(current_user.id, data, contract)

        return jsonify({"deal": deal.to_dict(), "contract": contract})


    @app.route("/api/portal/deal/<int:deal_id>/fund", methods=["POST"])
    @login_required
    def api_deal_fund(deal_id):
        """Fund XRPL escrow for a private market deal."""
        from ai_search import mystes_ai
        result = mystes_ai.fund_deal_escrow(deal_id, current_user.id)
        if result.get("error"):
            return jsonify(result), 400
        return jsonify(result)


    @app.route("/api/portal/deal/<int:deal_id>/confirm-delivery", methods=["POST"])
    @login_required
    def api_deal_confirm(deal_id):
        """Buyer confirms delivery — releases escrow."""
        from ai_search import mystes_ai
        result = mystes_ai.confirm_delivery(deal_id, current_user.id)
        if result.get("error"):
            return jsonify(result), 400
        return jsonify(result)


    @app.route("/api/portal/deal/<int:deal_id>/dispute", methods=["POST"])
    @login_required
    def api_deal_dispute(deal_id):
        """Open dispute on a funded deal — escrow holds."""
        from ai_search import mystes_ai
        data = request.get_json() or {}
        result = mystes_ai.dispute_deal(deal_id, current_user.id, reason=data.get("reason", ""))
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
        from ai_search import mystes_ai
        data = request.get_json() or {}

        expiration_days = int(data.get("expiration_days", 7))
        if expiration_days < 1 or expiration_days > 30:
            return jsonify({"error": "Expiration must be between 1 and 30 days"}), 400

        result = mystes_ai.generate_deal_link(deal_id, current_user.id, expiration_days)
        if result.get("error"):
            return jsonify(result), 400
        return jsonify(result)


    @app.route("/api/portal/deal/<int:deal_id>/send-link", methods=["POST"])
    @login_required
    def api_deal_send_link(deal_id):
        """Send deal link to seller via email."""
        from ai_search import mystes_ai
        result = mystes_ai.send_deal_link_email(deal_id, current_user.id)
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
        from ai_search import mystes_ai

        mystes_ai.mark_deal_link_viewed(link_token)
        result = mystes_ai.get_deal_by_link_token(link_token)

        if result.get("error"):
            return f"""<!DOCTYPE html>
    <html><head><title>Deal Link — MYSTES</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>body{{font-family:-apple-system,sans-serif;background:#f5f7fa;padding:40px}}
    .c{{max-width:600px;margin:0 auto;background:#fff;border-radius:12px;padding:40px;box-shadow:0 2px 8px rgba(0,0,0,.1)}}
    .e{{color:#d32f2f}}</style></head>
    <body><div class="c"><h1 style="color:#4361ee">MYSTES</h1>
    <p class="e">{result['error']}</p></div></body></html>""", 404

        d = result["deal"]
        already_accepted = d["status"] == "seller_accepted"

        accept_form = ""
        if not already_accepted:
            accept_form = f"""
            <div style="background:#f0fdfa;border:1px solid #ffeaa7;padding:20px;border-radius:8px;margin:20px 0">
                <h4 style="margin-top:0;color:#856404">How MYSTES Escrow Works</h4>
                <ol style="padding-left:20px;color:#856404">
                    <li>You provide your XRPL wallet address below</li>
                    <li>The buyer creates an on-chain escrow with the funds</li>
                    <li>You can verify the locked funds on the XRPL ledger</li>
                    <li>Complete the transaction (deliver the item/service)</li>
                    <li>Buyer confirms delivery</li>
                    <li>Escrow releases payment to your wallet automatically</li>
                </ol>
                <p style="margin-bottom:0;color:#856404;font-weight:bold">
                    MYSTES takes a fee but is NOT liable for physical goods execution.
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
                        '<h3 style="margin-top:0;color:#1a1a2e">Create a MYSTES Account</h3>'+
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
    <html><head><title>Deal Proposal — MYSTES</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
    body{{font-family:-apple-system,BlinkMacSystemFont,sans-serif;
        background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);padding:20px;margin:0}}
    .c{{max-width:700px;margin:40px auto;background:#fff;border-radius:16px;padding:40px;
        box-shadow:0 10px 30px rgba(0,0,0,.2)}}
    </style></head>
    <body><div class="c">
        <div style="color:#4361ee;font-size:28px;font-weight:bold;margin-bottom:30px">MYSTES</div>
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

        from ai_search import mystes_ai

        data = request.get_json() or {}
        seller_wallet = (data.get("seller_wallet") or "").strip()
        seller_name = (data.get("seller_name") or "").strip()

        if not seller_wallet:
            return jsonify({"error": "Wallet address is required"}), 400

        result = mystes_ai.accept_deal_link(link_token, seller_wallet, seller_name)
        if result.get("error"):
            return jsonify(result), 400
        return jsonify(result)


    @app.route("/deal/link/<link_token>/signup", methods=["POST"])
    def public_deal_link_signup(link_token):
        """PUBLIC: Seller creates a MYSTES account from the deal acceptance page.

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
            ref_code = f"MYSTES_{current_user.id}"

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


    @app.route("/helper")
    @login_required
    def helper_dashboard():
        """Helper dashboard — P2P earning profile."""
        # Gate behind feature flag (Build #96)
        if not is_feature_enabled("node_onboarding"):
            flash("Node network coming soon.", "info")
            return redirect("/dashboard")
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
        <h2 style="color: #7c3aed; margin-bottom: 5px;">Browser Extension Dashboard</h2>
        <p style="color: #fff; margin-bottom: 25px;">Passive browsing data earnings from the MYSTES Chrome extension.</p>

        <!-- Connection Status -->
        <div style="background: rgba(35,41,47,0.6); border-radius: 12px; padding: 20px; margin-bottom: 20px; border: 1px solid rgba(124,58,237,0.2);">
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
            <div style="font-size: 15px; font-weight: 600; color: #7c3aed; margin-bottom: 12px;">Helper Token</div>
            {% if helper and helper.helper_token %}
                <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
                    <code id="token-display" style="background: #1a1a2e; padding: 8px 14px; border-radius: 6px; color: #fff; font-size: 13px; word-break: break-all;">{{ helper.helper_token }}</code>
                    <button onclick="navigator.clipboard.writeText(document.getElementById('token-display').textContent).then(()=>{this.textContent='Copied!';setTimeout(()=>{this.textContent='Copy'},1500)})" style="padding: 8px 16px; background: #7c3aed; color: white; border: none; border-radius: 6px; cursor: pointer; font-size: 13px;">Copy</button>
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
                <div style="font-size: 24px; font-weight: 700; color: #7c3aed;">{{ '%.4f' | format(stats.totals.total_value_usd) }}</div>
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
            <div style="font-size: 15px; font-weight: 600; color: #7c3aed; margin-bottom: 15px;">Event Breakdown (7 days)</div>
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
                        <td style="padding: 10px 0; color: #7c3aed; text-align: right;">${{ '%.4f' | format(data.value_usd) }}</td>
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
            <div style="font-size: 15px; font-weight: 600; color: #7c3aed; margin-bottom: 12px;">Quick Setup</div>
            <ol style="color: #fff; line-height: 1.8; padding-left: 20px; margin: 0;">
                <li>Generate a helper token above (if you haven't already)</li>
                <li>Install the MYSTES Chrome extension from <code style="background: #1a1a2e; padding: 2px 6px; border-radius: 3px;">chrome://extensions</code> (load unpacked)</li>
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
            }.get(t.status, '#f0fdfa')
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


    @app.route("/api/admin/node-payout-pct", methods=["POST"])
    @admin_required
    def api_admin_node_payout_pct():
        """Set node payout percentage."""
        from models import SystemSetting

        data = request.get_json()
        payout_pct = data.get("payout_pct")

        if payout_pct is None:
            return jsonify({"success": False, "error": "Missing payout_pct"}), 400

        payout_pct = max(0, min(100, int(payout_pct)))  # Clamp to 0-100
        success = SystemSetting.set('node_payout_pct', payout_pct, 'int', admin_id=current_user.id)
        if success:
            return jsonify({"success": True, "payout_pct": payout_pct})
        return jsonify({"success": False, "error": "Failed to update"}), 500



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


    @app.route("/api/nodes/register", methods=["POST"])
    @login_required
    def api_node_register():
        """Register a helper node in the CitizenSERP network."""
        check = _node_network_check()
        if check:
            return check
        try:
            from node_registry import node_registry
            from node_antidilution import check_onboarding_allowed
            data = request.get_json() or {}
            capabilities = data.get("capabilities", {})

            # Anti-dilution check (Build #97)
            allowed, reason = check_onboarding_allowed(capabilities, current_user.id)
            if not allowed:
                return jsonify({
                    "error": "capacity_limit",
                    "message": reason,
                    "hint": "Install the mobile app or desktop extension to join as a data-generating node."
                }), 503

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
        check = _node_network_check()
        if check:
            return check
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
        check = _node_network_check()
        if check:
            return check
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
        check = _node_network_check()
        if check:
            return check
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
        check = _node_network_check()
        if check:
            return check
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
        check = _node_network_check()
        if check:
            return check
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


    @app.route("/api/node/onboard", methods=["POST"])
    @login_required
    def api_node_onboard():
        """One-shot node onboarding — creates helper profile, generates token,
        registers node, and marks Google account linked.

        POST JSON body (all optional):
            country_code: 2-letter ISO (default: "US")
            city: city name
            zone_code: sub-regional zone (e.g. "US-NE")
            platform: 'mobile', 'desktop', 'windows', 'macos', 'linux'
            has_extension: bool
            has_browser: bool

        Returns helper_token + node instructions.
        """
        check = _node_network_check()
        if check:
            return check
        import secrets as _secrets
        try:
            data = request.get_json(silent=True) or {}

            # Anti-dilution check (Build #97)
            from node_antidilution import check_onboarding_allowed
            capabilities = {
                "platform": data.get("platform", "linux"),
                "has_extension": data.get("has_extension", False),
                "has_browser": data.get("has_browser", False),
                "has_auth_sessions": data.get("has_auth_sessions", False),
            }
            allowed, reason = check_onboarding_allowed(capabilities, current_user.id)
            if not allowed:
                return jsonify({
                    "error": "capacity_limit",
                    "message": reason,
                    "hint": "Install the mobile app or desktop extension to join as a data-generating node."
                }), 503
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


    @app.route("/extension/updates.xml")
    def extension_updates_xml():
        """Serve Chrome extension update manifest for self-hosted auto-update."""
        import glob as glob_mod
        update_file = os.path.join(app.root_path, "mystes_extension", "dist", "update.xml")
        if not os.path.exists(update_file):
            # Generate on-the-fly from manifest version
            manifest_path = os.path.join(app.root_path, "mystes_extension", "manifest.json")
            if not os.path.exists(manifest_path):
                return Response("Extension not built", status=404, content_type="text/plain")
            with open(manifest_path) as f:
                manifest = json.loads(f.read())
            version = manifest.get("version", "1.0.0")
            ext_id = "mystes-node-extension"
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
        dist_dir = os.path.join(app.root_path, "mystes_extension", "dist")
        zip_name = f"mystes_extension_v{version}.zip"
        zip_path = os.path.join(dist_dir, zip_name)
        if not os.path.exists(zip_path):
            # Try without v prefix
            zip_name = f"mystes_extension_{version}.zip"
            zip_path = os.path.join(dist_dir, zip_name)
        if not os.path.exists(zip_path):
            return jsonify({"error": f"Version {version} not found"}), 404
        from flask import send_file
        return send_file(zip_path, mimetype="application/zip", as_attachment=True, download_name=zip_name)


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
                f'# MYSTES Node Service Installer\n'
                f'# Run this in PowerShell as Administrator\n'
                f'$Token = "{token}"\n'
                f'$Server = "{server_url}"\n'
                f'Invoke-WebRequest -Uri "$Server/static/scripts/install-node-service.ps1" '
                f'-OutFile "$env:TEMP\\install-mystes-node.ps1"\n'
                f'& "$env:TEMP\\install-mystes-node.ps1" -Token $Token -Server $Server\n'
            )
            return Response(
                script,
                mimetype="text/plain",
                headers={"Content-Disposition": "attachment; filename=install-mystes-node.ps1"},
            )
        else:
            # Return bash one-liner
            script = (
                f'#!/bin/bash\n'
                f'# MYSTES Node Service Installer\n'
                f'TOKEN="{token}"\n'
                f'SERVER="{server_url}"\n'
                f'curl -sSL "$SERVER/static/scripts/install-node-service.sh" | '
                f'bash -s -- --token "$TOKEN" --server "$SERVER"\n'
            )
            return Response(
                script,
                mimetype="text/plain",
                headers={"Content-Disposition": f"attachment; filename=install-mystes-node.sh"},
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

    @app.route("/settings/ai-providers")
    @login_required
    def settings_ai_providers():
        """BYOAI settings page — manage personal AI provider keys."""
        from ai_search import mystes_ai, AI_PROVIDERS
        platform = mystes_ai.get_platform_providers()
        user_provs = mystes_ai.get_user_providers(current_user.id)

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
        from ai_search import mystes_ai
        data = request.get_json() or {}
        provider = data.get("provider", "").strip()
        api_key = data.get("api_key", "").strip()

        if not provider or not api_key:
            return jsonify({"error": "Provider and API key required"}), 400

        # Quick test: try a minimal API call
        try:
            result = mystes_ai._call_provider(
                provider,
                [{"role": "system", "content": "Reply with OK"}, {"role": "user", "content": "Test"}],
                api_key=api_key,
                provider_info=mystes_ai.providers.get(provider, {})
            )
            if result and result.get("response"):
                return jsonify({"ok": True, "message": f"{provider} is working correctly"})
            return jsonify({"error": "Provider returned empty response"}), 400
        except Exception as e:
            return jsonify({"error": f"Test failed: {str(e)}"}), 400



    @app.route("/api/v1/ai/compare", methods=["POST"])
    @login_required
    def api_ai_compare():
        """Run MYSTESAI comparison against BYOAI/user search results."""
        from strategy_learner import strategy_learner

        data = request.get_json() or {}
        byoai_results = data.get("byoai_results", [])
        query_params = data.get("query_params", {})

        if not byoai_results and not query_params:
            return jsonify({"error": "Results or query params required"}), 400

        # Check daily comparison quota
        today = datetime.utcnow().date()
        if current_user.ai_tier == 'ai_free' and current_user.last_comparison_date == today:
            return jsonify({"error": "Daily comparison limit reached. Upgrade to MYSTESAI for unlimited comparisons."}), 429

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
            BASE_TEMPLATE,
            title="Data Marketplace - Admin",
            content=render_template_string(DATA_MARKETPLACE_ADMIN_CONTENT, stats=stats),
            current_user=current_user,
        )

