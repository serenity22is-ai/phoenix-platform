"""
MYSTES B2B Business Routes — Self-service agency signup, dashboard, and billing.

B2B subscribers are power users INSIDE MYSTES with reduced fees ($49-$199/mo).
They sell THROUGH MYSTES. NO turnkey deployment. NO standalone site.
Turnkey OTA deployment is APAi-only (see /apai route in server.py).

Routes:
    GET  /business                  — Landing page (public)
    GET  /business/signup           — Signup form (login required)
    POST /business/signup           — Create account + Stripe checkout
    GET  /business/success          — Post-checkout success page
    GET  /business/dashboard        — B2B dashboard (active subscription required)
    GET  /business/billing          — Redirect to Stripe Customer Portal
    GET  /business/api-keys         — API key management
    POST /business/api-keys         — Generate new API key
    DELETE /api/business/api-keys/<id> — Revoke API key
    GET  /business/markup           — Consumer markup settings
    GET  /ref/<code>                — Referral link redirect

MYSTES KYRIOS LLC — Confidential.
"""

import json
import logging
import os
import secrets
from datetime import datetime, timezone
from functools import wraps

from flask import (
    flash, g, jsonify, redirect, render_template_string,
    request, url_for,
)
from flask_login import current_user, login_required

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# B2B Required Decorator
# ---------------------------------------------------------------------------

def b2b_required(f):
    """Decorator: require active B2B commercial account with valid subscription."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            flash("Please log in to access your business account.", "error")
            return redirect("/login")

        from models import CommercialAccount
        account = CommercialAccount.query.filter_by(
            owner_user_id=current_user.id, is_active=True
        ).first()

        if not account:
            flash("You need a business account to access this page.", "error")
            return redirect("/business/signup")

        if account.subscription_status not in ('active', 'trialing'):
            flash("Your subscription is inactive. Please update your billing.", "error")
            return redirect("/business/signup")

        g.b2b_account = account
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

BUSINESS_LANDING_CONTENT = """
<div style="max-width:800px;margin:40px auto;padding:0 20px;">
    <h1 style="font-family:'Cinzel',serif;font-size:2.2rem;color:#e8dcc8;margin-bottom:10px;">
        MYSTES for Business
    </h1>
    <p style="color:#b0a89a;font-size:1.1rem;margin-bottom:30px;">
        Travel agencies save more with B2B pricing. Lower platform fees,
        API access, and volume-based tier upgrades.
    </p>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:40px;">
        <div style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:24px;">
            <h3 style="color:#e8dcc8;font-family:'Cinzel',serif;margin-bottom:12px;">Consumer</h3>
            <div style="font-size:2rem;color:#4361ee;font-weight:700;">35%</div>
            <div style="color:#8a8278;font-size:0.9rem;">of savings per booking</div>
            <ul style="color:#b0a89a;font-size:0.9rem;margin-top:15px;padding-left:18px;">
                <li>Individual bookings</li>
                <li>Web search interface</li>
                <li>Saved payment methods</li>
            </ul>
        </div>
        <div style="background:rgba(67,97,238,0.08);border:1px solid rgba(67,97,238,0.3);border-radius:12px;padding:24px;">
            <h3 style="color:#e8dcc8;font-family:'Cinzel',serif;margin-bottom:12px;">Business</h3>
            <div style="font-size:2rem;color:#4361ee;font-weight:700;">25%</div>
            <div style="color:#8a8278;font-size:0.9rem;">of savings per booking</div>
            <div style="color:#4361ee;font-size:0.85rem;margin-top:4px;">$49/month</div>
            <ul style="color:#b0a89a;font-size:0.9rem;margin-top:15px;padding-left:18px;">
                <li>Reduced fees (25% &rarr; 15%)</li>
                <li>API key access</li>
                <li>Volume analytics</li>
                <li>POS market data (B2B only)</li>
                <li>Volume tier upgrades</li>
            </ul>
        </div>
    </div>

    <div style="text-align:center;">
        {% if current_user.is_authenticated %}
            {% if has_account %}
                <a href="/business/dashboard"
                   style="display:inline-block;padding:14px 40px;background:#4361ee;color:white;
                          text-decoration:none;border-radius:8px;font-size:1.1rem;font-weight:600;">
                    Go to Dashboard
                </a>
            {% else %}
                <a href="/business/signup"
                   style="display:inline-block;padding:14px 40px;background:#4361ee;color:white;
                          text-decoration:none;border-radius:8px;font-size:1.1rem;font-weight:600;">
                    Upgrade to Business &mdash; $49/mo
                </a>
            {% endif %}
        {% else %}
            <a href="/login"
               style="display:inline-block;padding:14px 40px;background:#4361ee;color:white;
                      text-decoration:none;border-radius:8px;font-size:1.1rem;font-weight:600;">
                Log In to Get Started
            </a>
        {% endif %}
    </div>

    <div style="margin-top:50px;padding:24px;background:rgba(255,255,255,0.03);border-radius:12px;
                border:1px solid rgba(255,255,255,0.06);">
        <h3 style="color:#e8dcc8;font-family:'Cinzel',serif;margin-bottom:12px;">
            Volume Tier Ladder
        </h3>
        <table style="width:100%;color:#b0a89a;font-size:0.9rem;border-collapse:collapse;">
            <thead>
                <tr style="border-bottom:1px solid rgba(255,255,255,0.1);">
                    <th style="text-align:left;padding:8px 0;">Tier</th>
                    <th style="text-align:left;padding:8px 0;">Tickets / 30 days</th>
                    <th style="text-align:left;padding:8px 0;">Fee</th>
                </tr>
            </thead>
            <tbody>
                <tr><td style="padding:6px 0;">Starter &mdash; $49/mo</td><td>0+</td><td>25%</td></tr>
                <tr><td style="padding:6px 0;">Growth &mdash; $99/mo</td><td>50+</td><td>20%</td></tr>
                <tr><td style="padding:6px 0;">Volume &mdash; $199/mo</td><td>500+</td><td>15%</td></tr>
            </tbody>
        </table>
        <p style="color:#8a8278;font-size:0.8rem;margin-top:10px;">
            Tiers recalculate every 30 days. Two consecutive periods below threshold = downgrade.
        </p>
    </div>

    <div style="margin-top:30px;padding:20px;background:rgba(124,58,237,0.05);border-radius:12px;
                border:1px solid rgba(124,58,237,0.15);">
        <h3 style="color:#e8dcc8;font-family:'Cinzel',serif;margin-bottom:8px;">
            Want Your Own Branded OTA?
        </h3>
        <p style="color:#b0a89a;font-size:0.9rem;">
            APAi gives you a turnkey copy of the MYSTES platform with your own brand,
            domain, and AI-powered admin terminal. Click. Pay. Deploy.
        </p>
        <a href="/apai"
           style="color:#a78bfa;font-size:0.9rem;text-decoration:underline;">
            Learn more about APAi &rarr;
        </a>
    </div>
</div>
"""


BUSINESS_SIGNUP_CONTENT = """
<div style="max-width:500px;margin:40px auto;padding:0 20px;">
    <h1 style="font-family:'Cinzel',serif;font-size:1.8rem;color:#e8dcc8;margin-bottom:8px;">
        Create Business Account
    </h1>
    <p style="color:#8a8278;font-size:0.9rem;margin-bottom:24px;">
        $49/month &mdash; cancel anytime. Platform fee drops from 35% to 25% immediately.
    </p>

    <form method="POST" action="/business/signup" style="display:flex;flex-direction:column;gap:12px;">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">

        <label style="color:#b0a89a;font-size:0.9rem;">Company Name *</label>
        <input type="text" name="company_name" required placeholder="Apex Travel Agency"
               style="padding:10px;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.12);
                      border-radius:6px;color:#e8dcc8;font-size:1rem;">

        <label style="color:#b0a89a;font-size:0.9rem;">Business Email *</label>
        <input type="email" name="contact_email" required placeholder="ops@apextravel.com"
               value="{{ current_user.email }}"
               style="padding:10px;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.12);
                      border-radius:6px;color:#e8dcc8;font-size:1rem;">

        <label style="color:#b0a89a;font-size:0.9rem;">Contact Name</label>
        <input type="text" name="contact_name" placeholder="Jane Doe"
               value="{{ current_user.name or '' }}"
               style="padding:10px;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.12);
                      border-radius:6px;color:#e8dcc8;font-size:1rem;">

        <label style="color:#b0a89a;font-size:0.9rem;">Website</label>
        <input type="url" name="company_website" placeholder="https://apextravel.com"
               style="padding:10px;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.12);
                      border-radius:6px;color:#e8dcc8;font-size:1rem;">

        <button type="submit"
                style="margin-top:8px;padding:14px;background:#4361ee;color:white;border:none;
                       border-radius:8px;font-size:1.05rem;font-weight:600;cursor:pointer;">
            Continue to Payment &mdash; $49/mo
        </button>
    </form>

    <p style="color:#8a8278;font-size:0.8rem;margin-top:16px;text-align:center;">
        Secure checkout via Stripe. Cancel anytime from your billing page.
    </p>
</div>
"""


BUSINESS_SUCCESS_CONTENT = """
<div style="max-width:500px;margin:60px auto;text-align:center;padding:0 20px;">
    <div style="font-size:3rem;margin-bottom:16px;">&#10003;</div>
    <h1 style="font-family:'Cinzel',serif;font-size:1.8rem;color:#e8dcc8;margin-bottom:12px;">
        Welcome to MYSTES Business
    </h1>
    <p style="color:#b0a89a;font-size:1rem;margin-bottom:24px;">
        Your subscription is active. Platform fees are now <strong style="color:#4361ee;">25%</strong>
        of savings on every booking.
    </p>
    <a href="/business/dashboard"
       style="display:inline-block;padding:14px 32px;background:#4361ee;color:white;
              text-decoration:none;border-radius:8px;font-size:1rem;font-weight:600;">
        Go to Dashboard
    </a>
</div>
"""


BUSINESS_DASHBOARD_CONTENT = """
<div style="max-width:900px;margin:30px auto;padding:0 20px;">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:24px;">
        <h1 style="font-family:'Cinzel',serif;font-size:1.8rem;color:#e8dcc8;margin:0;">
            Business Dashboard
        </h1>
        <span style="color:#8a8278;font-size:0.85rem;">{{ account.account_id }}</span>
    </div>

    <!-- Account Summary -->
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin-bottom:30px;">
        <div style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);
                    border-radius:10px;padding:18px;">
            <div style="color:#8a8278;font-size:0.8rem;text-transform:uppercase;">Company</div>
            <div style="color:#e8dcc8;font-size:1.1rem;margin-top:4px;">{{ account.name }}</div>
        </div>
        <div style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);
                    border-radius:10px;padding:18px;">
            <div style="color:#8a8278;font-size:0.8rem;text-transform:uppercase;">Tier</div>
            <div style="color:#4361ee;font-size:1.1rem;font-weight:600;margin-top:4px;text-transform:capitalize;">
                {{ account.current_tier }}
            </div>
        </div>
        <div style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);
                    border-radius:10px;padding:18px;">
            <div style="color:#8a8278;font-size:0.8rem;text-transform:uppercase;">Fee Rate</div>
            <div style="color:#e8dcc8;font-size:1.1rem;margin-top:4px;">{{ account.fee_percent }}%</div>
        </div>
        <div style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);
                    border-radius:10px;padding:18px;">
            <div style="color:#8a8278;font-size:0.8rem;text-transform:uppercase;">Subscription</div>
            <div style="color:{% if account.subscription_status == 'active' %}#22c55e{% else %}#ef4444{% endif %};
                        font-size:1.1rem;margin-top:4px;text-transform:capitalize;">
                {{ account.subscription_status }}
            </div>
        </div>
    </div>

    <!-- Volume Stats -->
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-bottom:30px;">
        <div style="background:rgba(67,97,238,0.06);border:1px solid rgba(67,97,238,0.15);
                    border-radius:10px;padding:18px;">
            <div style="color:#8a8278;font-size:0.8rem;text-transform:uppercase;">Tickets (30d)</div>
            <div style="color:#e8dcc8;font-size:1.6rem;font-weight:700;margin-top:4px;">
                {{ account.tickets_last_30d }}
            </div>
        </div>
        <div style="background:rgba(67,97,238,0.06);border:1px solid rgba(67,97,238,0.15);
                    border-radius:10px;padding:18px;">
            <div style="color:#8a8278;font-size:0.8rem;text-transform:uppercase;">Total Tickets</div>
            <div style="color:#e8dcc8;font-size:1.6rem;font-weight:700;margin-top:4px;">
                {{ account.total_tickets }}
            </div>
        </div>
        <div style="background:rgba(67,97,238,0.06);border:1px solid rgba(67,97,238,0.15);
                    border-radius:10px;padding:18px;">
            <div style="color:#8a8278;font-size:0.8rem;text-transform:uppercase;">Revenue (30d)</div>
            <div style="color:#e8dcc8;font-size:1.6rem;font-weight:700;margin-top:4px;">
                ${{ "%.2f"|format(account.revenue_last_30d_usd) }}
            </div>
        </div>
        <div style="background:rgba(67,97,238,0.06);border:1px solid rgba(67,97,238,0.15);
                    border-radius:10px;padding:18px;">
            <div style="color:#8a8278;font-size:0.8rem;text-transform:uppercase;">Total Revenue</div>
            <div style="color:#e8dcc8;font-size:1.6rem;font-weight:700;margin-top:4px;">
                ${{ "%.2f"|format(account.total_revenue_usd) }}
            </div>
        </div>
    </div>

    <!-- Quick Links -->
    <div style="display:flex;gap:12px;margin-bottom:30px;flex-wrap:wrap;">
        <a href="/business/billing"
           style="padding:10px 20px;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);
                  border-radius:8px;color:#b0a89a;text-decoration:none;font-size:0.9rem;">
            Manage Billing
        </a>
        <a href="/business/api-keys"
           style="padding:10px 20px;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);
                  border-radius:8px;color:#b0a89a;text-decoration:none;font-size:0.9rem;">
            API Keys ({{ api_key_count }})
        </a>
        <a href="/business/markup"
           style="padding:10px 20px;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);
                  border-radius:8px;color:#b0a89a;text-decoration:none;font-size:0.9rem;">
            Pricing &amp; Markup
        </a>
        <a href="/apai"
           style="padding:10px 20px;background:rgba(124,58,237,0.1);border:1px solid rgba(124,58,237,0.2);
                  border-radius:8px;color:#a855f7;text-decoration:none;font-size:0.9rem;">
            Upgrade to APAi
        </a>
        <a href="/flights"
           style="padding:10px 20px;background:rgba(67,97,238,0.1);border:1px solid rgba(67,97,238,0.2);
                  border-radius:8px;color:#4361ee;text-decoration:none;font-size:0.9rem;">
            Search Flights
        </a>
    </div>

    <!-- Referral Code -->
    {% if account.referral_code %}
    <div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);
                border-radius:10px;padding:18px;margin-bottom:30px;">
        <div style="color:#8a8278;font-size:0.8rem;text-transform:uppercase;margin-bottom:6px;">
            Referral Code
        </div>
        <div style="display:flex;align-items:center;gap:12px;">
            <code style="color:#4361ee;font-size:1.1rem;background:rgba(67,97,238,0.08);
                         padding:6px 14px;border-radius:6px;">{{ account.referral_code }}</code>
            <span style="color:#8a8278;font-size:0.85rem;">
                {{ account.total_referred_users or 0 }} users referred
            </span>
        </div>
    </div>
    {% endif %}

    <!-- Recent Transactions -->
    <h2 style="font-family:'Cinzel',serif;font-size:1.3rem;color:#e8dcc8;margin-bottom:12px;">
        Recent Transactions
    </h2>
    {% if transactions %}
    <div style="overflow-x:auto;">
        <table style="width:100%;color:#b0a89a;font-size:0.85rem;border-collapse:collapse;">
            <thead>
                <tr style="border-bottom:1px solid rgba(255,255,255,0.1);text-align:left;">
                    <th style="padding:8px 6px;">Date</th>
                    <th style="padding:8px 6px;">Route</th>
                    <th style="padding:8px 6px;">Market</th>
                    <th style="padding:8px 6px;">Retail</th>
                    <th style="padding:8px 6px;">Booked</th>
                    <th style="padding:8px 6px;">Savings</th>
                    <th style="padding:8px 6px;">Fee</th>
                </tr>
            </thead>
            <tbody>
                {% for tx in transactions %}
                <tr style="border-bottom:1px solid rgba(255,255,255,0.04);">
                    <td style="padding:6px;">{{ tx.created_at.strftime('%m/%d') if tx.created_at else '-' }}</td>
                    <td style="padding:6px;">{{ tx.origin or '?' }}&rarr;{{ tx.destination or '?' }}</td>
                    <td style="padding:6px;">{{ tx.market_used or '-' }}</td>
                    <td style="padding:6px;">${{ "%.0f"|format(tx.retail_price_usd) }}</td>
                    <td style="padding:6px;">${{ "%.0f"|format(tx.booked_price_usd) }}</td>
                    <td style="padding:6px;color:#22c55e;">${{ "%.0f"|format(tx.savings_usd) }}</td>
                    <td style="padding:6px;">${{ "%.2f"|format(tx.fee_amount_usd) }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    {% else %}
    <p style="color:#8a8278;font-size:0.9rem;">No transactions yet. Search and book flights to get started.</p>
    {% endif %}

    <!-- ANASTASiA SDK Upgrade -->
    <div style="margin-top:40px;padding:20px;background:rgba(67,97,238,0.05);border-radius:12px;
                border:1px solid rgba(67,97,238,0.15);">
        <h3 style="color:#e8dcc8;font-family:'Cinzel',serif;margin-bottom:8px;">
            Scale with ANASTASiA SDK
        </h3>
        <p style="color:#b0a89a;font-size:0.9rem;">
            White-label flight search, AI booking agents, multi-POS arbitrage, and full API access.
            Build your own OTA powered by ANASTASiA.
        </p>
        <a href="https://anastasia-api.onrender.com/signup"
           target="_blank"
           style="display:inline-block;margin-top:8px;padding:10px 20px;background:rgba(67,97,238,0.15);
                  border:1px solid rgba(67,97,238,0.3);border-radius:8px;color:#4361ee;
                  text-decoration:none;font-size:0.9rem;">
            Explore ANASTASiA SDK &rarr;
        </a>
    </div>
</div>
"""


BUSINESS_API_KEYS_CONTENT = """
<div style="max-width:700px;margin:30px auto;padding:0 20px;">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:24px;">
        <h1 style="font-family:'Cinzel',serif;font-size:1.6rem;color:#e8dcc8;margin:0;">API Keys</h1>
        <a href="/business/dashboard" style="color:#8a8278;font-size:0.85rem;text-decoration:none;">&larr; Dashboard</a>
    </div>

    <!-- Generate New Key -->
    <form method="POST" action="/business/api-keys" style="margin-bottom:30px;">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <div style="display:flex;gap:10px;align-items:end;">
            <div style="flex:1;">
                <label style="color:#b0a89a;font-size:0.85rem;display:block;margin-bottom:4px;">Key Label</label>
                <input type="text" name="label" placeholder="Production" value="Default"
                       style="width:100%;padding:10px;background:rgba(255,255,255,0.06);
                              border:1px solid rgba(255,255,255,0.12);border-radius:6px;
                              color:#e8dcc8;font-size:0.95rem;">
            </div>
            <button type="submit"
                    style="padding:10px 20px;background:#4361ee;color:white;border:none;
                           border-radius:6px;font-size:0.95rem;cursor:pointer;white-space:nowrap;">
                Generate Key
            </button>
        </div>
    </form>

    {% if new_key %}
    <div style="background:rgba(34,197,94,0.08);border:1px solid rgba(34,197,94,0.3);
                border-radius:10px;padding:16px;margin-bottom:24px;">
        <div style="color:#22c55e;font-size:0.85rem;font-weight:600;margin-bottom:6px;">
            New API Key Generated &mdash; Copy it now, it won&apos;t be shown again!
        </div>
        <code style="color:#e8dcc8;font-size:0.9rem;word-break:break-all;
                     background:rgba(0,0,0,0.3);padding:8px 12px;border-radius:6px;
                     display:block;">{{ new_key }}</code>
    </div>
    {% endif %}

    <!-- Existing Keys -->
    {% if api_keys %}
    <div style="display:flex;flex-direction:column;gap:10px;">
        {% for key in api_keys %}
        <div style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);
                    border-radius:10px;padding:14px;display:flex;justify-content:space-between;align-items:center;">
            <div>
                <div style="color:#e8dcc8;font-size:0.95rem;">
                    <code>{{ key.key_prefix }}...</code>
                    <span style="color:#8a8278;margin-left:8px;">{{ key.label }}</span>
                </div>
                <div style="color:#8a8278;font-size:0.8rem;margin-top:3px;">
                    {{ key.total_requests }} requests
                    {% if key.last_used_at %} &middot; Last used {{ key.last_used_at.strftime('%b %d') }}{% endif %}
                    &middot; Created {{ key.created_at.strftime('%b %d, %Y') if key.created_at else 'N/A' }}
                </div>
            </div>
            <div>
                {% if key.is_active %}
                <form method="POST" action="/api/business/api-keys/{{ key.id }}/revoke"
                      style="display:inline;" onsubmit="return confirm('Revoke this API key?');">
                    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                    <button type="submit"
                            style="padding:6px 14px;background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.3);
                                   border-radius:6px;color:#ef4444;font-size:0.8rem;cursor:pointer;">
                        Revoke
                    </button>
                </form>
                {% else %}
                <span style="color:#8a8278;font-size:0.8rem;">Revoked</span>
                {% endif %}
            </div>
        </div>
        {% endfor %}
    </div>
    {% else %}
    <p style="color:#8a8278;font-size:0.9rem;">No API keys yet. Generate one to integrate with the MYSTES API.</p>
    {% endif %}
</div>
"""


# ---------------------------------------------------------------------------
# Route Registration
# ---------------------------------------------------------------------------

def register_business_routes(app, csrf, limiter):
    """Register all B2B business routes on the Flask app."""

    from server import BASE_TEMPLATE

    # ------------------------------------------------------------------
    # Landing Page (public)
    # ------------------------------------------------------------------

    @app.route("/business")
    def business_landing():
        """B2B landing page — marketing + signup CTA."""
        from models import CommercialAccount
        has_account = False
        if current_user.is_authenticated:
            acct = CommercialAccount.query.filter_by(
                owner_user_id=current_user.id, is_active=True
            ).first()
            if acct and acct.subscription_status == 'active':
                return redirect("/business/dashboard")
            has_account = acct is not None

        return render_template_string(
            BASE_TEMPLATE, title="MYSTES for Business",
            content=render_template_string(
                BUSINESS_LANDING_CONTENT,
                current_user=current_user,
                has_account=has_account,
            ),
            current_user=current_user,
        )

    # ------------------------------------------------------------------
    # Signup
    # ------------------------------------------------------------------

    @app.route("/business/signup", methods=["GET", "POST"])
    @login_required
    @limiter.limit("5 per hour", methods=["POST"])
    def business_signup():
        """B2B signup: create CommercialAccount + redirect to Stripe checkout."""
        from models import db, CommercialAccount

        # If already has active account, go to dashboard
        existing = CommercialAccount.query.filter_by(
            owner_user_id=current_user.id, is_active=True
        ).first()
        if existing and existing.subscription_status == 'active':
            return redirect("/business/dashboard")

        if request.method == "GET":
            return render_template_string(
                BASE_TEMPLATE, title="Business Signup",
                content=render_template_string(
                    BUSINESS_SIGNUP_CONTENT, current_user=current_user,
                ),
                current_user=current_user,
            )

        # POST — create account and start Stripe checkout
        company_name = request.form.get("company_name", "").strip()
        contact_email = request.form.get("contact_email", "").strip().lower()
        contact_name = request.form.get("contact_name", "").strip()
        company_website = request.form.get("company_website", "").strip()

        if not company_name:
            flash("Company name is required.", "error")
            return redirect("/business/signup")
        if not contact_email:
            flash("Business email is required.", "error")
            return redirect("/business/signup")

        # Reuse existing account if it exists (e.g. previous failed checkout)
        account = existing
        if not account:
            from commercial import CommercialManager
            manager = CommercialManager()
            result = manager.create_account(
                name=company_name,
                contact_email=contact_email,
                owner_user_id=current_user.id,
                contact_name=contact_name,
                company_website=company_website,
            )
            if "error" in result:
                flash(result["error"], "error")
                return redirect("/business/signup")

            account = CommercialAccount.query.filter_by(
                account_id=result["account_id"]
            ).first()
        else:
            # Update existing account details
            account.name = company_name
            account.contact_email = contact_email
            account.contact_name = contact_name
            account.company_website = company_website
            db.session.commit()

        # Create Stripe subscription checkout
        try:
            import stripe as stripe_mod

            price_id = app.config.get("B2B_STRIPE_PRICE_ID") or os.environ.get("B2B_STARTER_STRIPE_PRICE_ID", "")
            if not price_id:
                # No Stripe price configured — activate directly (sandbox/dev mode)
                account.subscription_status = "active"
                account.activated_at = datetime.now(timezone.utc)
                db.session.commit()
                flash("Business account activated (dev mode).", "success")
                return redirect("/business/dashboard")

            # Create or reuse Stripe Customer for the commercial account
            if not account.stripe_customer_id:
                customer = stripe_mod.Customer.create(
                    email=contact_email,
                    name=company_name,
                    metadata={
                        "mystes_account_id": account.account_id,
                        "mystes_user_id": str(current_user.id),
                        "account_type": "b2b",
                    },
                )
                account.stripe_customer_id = customer.id
                db.session.commit()

            base_url = request.url_root.rstrip("/")
            session = stripe_mod.checkout.Session.create(
                mode="subscription",
                customer=account.stripe_customer_id,
                line_items=[{"price": price_id, "quantity": 1}],
                success_url=f"{base_url}/business/success?session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=f"{base_url}/business/signup",
                metadata={
                    "mystes_account_id": account.account_id,
                    "account_type": "b2b",
                },
            )

            account.subscription_status = "pending"
            db.session.commit()

            return redirect(session.url)

        except Exception as e:
            logger.error(f"Stripe checkout error: {e}", exc_info=True)
            flash("Payment setup failed. Please try again.", "error")
            return redirect("/business/signup")

    # ------------------------------------------------------------------
    # Post-Checkout Success
    # ------------------------------------------------------------------

    @app.route("/business/success")
    @login_required
    def business_success():
        """Landing page after successful Stripe checkout."""
        from models import db, CommercialAccount

        # Verify subscription is active (webhook may have already set it)
        account = CommercialAccount.query.filter_by(
            owner_user_id=current_user.id, is_active=True
        ).first()

        if account and account.subscription_status not in ('active', 'trialing'):
            # Try to verify with Stripe directly (webhook may be delayed)
            session_id = request.args.get("session_id")
            if session_id:
                try:
                    import stripe as stripe_mod
                    session = stripe_mod.checkout.Session.retrieve(session_id)
                    if session.subscription:
                        sub = stripe_mod.Subscription.retrieve(session.subscription)
                        account.stripe_subscription_id = sub.id
                        account.subscription_status = sub.status
                        if hasattr(sub, 'current_period_end') and sub.current_period_end:
                            account.current_period_end = datetime.fromtimestamp(
                                sub.current_period_end, tz=timezone.utc,
                            )
                        if not account.activated_at:
                            account.activated_at = datetime.now(timezone.utc)
                        db.session.commit()
                        logger.info(f"B2B subscription verified via session: {account.account_id}")
                except Exception as e:
                    logger.warning(f"Could not verify subscription on success page: {e}")

        return render_template_string(
            BASE_TEMPLATE, title="Welcome to MYSTES Business",
            content=BUSINESS_SUCCESS_CONTENT,
            current_user=current_user,
        )

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    @app.route("/business/dashboard")
    @login_required
    @b2b_required
    def business_dashboard():
        """B2B dashboard — account overview, volume stats, recent transactions."""
        from models import CommercialTransaction, CommercialAPIKey

        account = g.b2b_account

        # Recent transactions
        transactions = CommercialTransaction.query.filter_by(
            account_id=account.id
        ).order_by(CommercialTransaction.created_at.desc()).limit(20).all()

        # API key count
        api_key_count = CommercialAPIKey.query.filter_by(
            account_id=account.id, is_active=True
        ).count()

        return render_template_string(
            BASE_TEMPLATE, title="Business Dashboard",
            content=render_template_string(
                BUSINESS_DASHBOARD_CONTENT,
                account=account,
                transactions=transactions,
                api_key_count=api_key_count,
                current_user=current_user,
            ),
            current_user=current_user,
        )

    # ------------------------------------------------------------------
    # Billing (Stripe Customer Portal redirect)
    # ------------------------------------------------------------------

    @app.route("/business/billing")
    @login_required
    @b2b_required
    def business_billing():
        """Redirect to Stripe Customer Portal for subscription management."""
        account = g.b2b_account

        if not account.stripe_customer_id:
            flash("No billing account found. Contact support.", "error")
            return redirect("/business/dashboard")

        try:
            import stripe as stripe_mod
            base_url = request.url_root.rstrip("/")
            portal = stripe_mod.billing_portal.Session.create(
                customer=account.stripe_customer_id,
                return_url=f"{base_url}/business/dashboard",
            )
            return redirect(portal.url)
        except Exception as e:
            logger.error(f"Stripe portal error: {e}", exc_info=True)
            flash("Could not open billing portal. Please try again.", "error")
            return redirect("/business/dashboard")

    # ------------------------------------------------------------------
    # API Keys
    # ------------------------------------------------------------------

    @app.route("/business/api-keys", methods=["GET", "POST"])
    @login_required
    @b2b_required
    def business_api_keys():
        """View and generate API keys."""
        from models import db, CommercialAPIKey

        account = g.b2b_account
        new_key = None

        if request.method == "POST":
            label = request.form.get("label", "Default").strip() or "Default"

            from commercial import CommercialManager
            manager = CommercialManager()
            result = manager.create_api_key(
                account_id=account.account_id,
                label=label,
                scopes=["search", "book", "analytics"],
            )

            if "error" in result:
                flash(result["error"], "error")
            else:
                new_key = result["api_key"]
                flash("API key generated. Copy it now — it won't be shown again.", "success")

        api_keys = CommercialAPIKey.query.filter_by(
            account_id=account.id
        ).order_by(CommercialAPIKey.created_at.desc()).all()

        return render_template_string(
            BASE_TEMPLATE, title="API Keys",
            content=render_template_string(
                BUSINESS_API_KEYS_CONTENT,
                account=account,
                api_keys=api_keys,
                new_key=new_key,
                current_user=current_user,
            ),
            current_user=current_user,
        )

    @app.route("/api/business/api-keys/<int:key_id>/revoke", methods=["POST"])
    @login_required
    @b2b_required
    def business_revoke_api_key(key_id):
        """Revoke an API key."""
        from models import db, CommercialAPIKey

        account = g.b2b_account
        api_key = CommercialAPIKey.query.filter_by(
            id=key_id, account_id=account.id
        ).first()

        if not api_key:
            flash("API key not found.", "error")
            return redirect("/business/api-keys")

        api_key.is_active = False
        db.session.commit()
        flash("API key revoked.", "success")
        return redirect("/business/api-keys")

    # ------------------------------------------------------------------
    # Analytics API (Build #185)
    # ------------------------------------------------------------------

    @app.route("/api/business/analytics")
    @csrf.exempt
    @login_required
    @b2b_required
    def business_analytics():
        """Get B2B analytics data for charts and dashboards."""
        from models import CommercialTransaction
        account = g.b2b_account

        # Get all transactions
        txns = CommercialTransaction.query.filter_by(
            account_id=account.id, status="completed"
        ).order_by(CommercialTransaction.created_at.desc()).all()

        # Aggregate by month
        monthly = {}
        route_stats = {}
        total_savings = 0.0
        total_fees = 0.0
        total_revenue = 0.0

        for tx in txns:
            month_key = tx.created_at.strftime("%Y-%m") if tx.created_at else "unknown"
            if month_key not in monthly:
                monthly[month_key] = {"tickets": 0, "revenue": 0.0, "savings": 0.0, "fees": 0.0}
            monthly[month_key]["tickets"] += 1
            monthly[month_key]["revenue"] += tx.booked_price_usd or 0
            monthly[month_key]["savings"] += tx.savings_usd or 0
            monthly[month_key]["fees"] += tx.fee_amount_usd or 0

            # Route breakdown
            route = f"{tx.origin or '?'}-{tx.destination or '?'}"
            if route not in route_stats:
                route_stats[route] = {"tickets": 0, "revenue": 0.0, "avg_savings_pct": 0.0}
            route_stats[route]["tickets"] += 1
            route_stats[route]["revenue"] += tx.booked_price_usd or 0

            total_savings += tx.savings_usd or 0
            total_fees += tx.fee_amount_usd or 0
            total_revenue += tx.booked_price_usd or 0

        # Calculate average savings per route
        for route in route_stats:
            route_txns = [t for t in txns if f"{t.origin or '?'}-{t.destination or '?'}" == route]
            if route_txns:
                avg_pct = sum((t.savings_percent or 0) for t in route_txns) / len(route_txns)
                route_stats[route]["avg_savings_pct"] = round(avg_pct, 1)

        # Tier progress
        tier_thresholds = {
            "starter": {"next": "professional", "tickets_needed": 50},
            "professional": {"next": "enterprise", "tickets_needed": 500},
            "enterprise": {"next": "partner", "tickets_needed": 5000},
            "partner": {"next": None, "tickets_needed": 0},
        }
        current_tier = account.current_tier or "starter"
        progress = tier_thresholds.get(current_tier, tier_thresholds["starter"])
        tickets_30d = account.tickets_last_30d or 0
        tickets_to_next = max(0, progress["tickets_needed"] - tickets_30d) if progress["next"] else 0

        # Sort monthly by key
        monthly_sorted = [
            {"month": k, **v} for k, v in sorted(monthly.items())
        ]

        # Top routes by ticket count
        top_routes = sorted(
            [{"route": k, **v} for k, v in route_stats.items()],
            key=lambda x: x["tickets"], reverse=True
        )[:10]

        return jsonify({
            "account_id": account.account_id,
            "tier": current_tier,
            "fee_percent": account.fee_percent,
            "tier_progress": {
                "current": current_tier,
                "next_tier": progress["next"],
                "tickets_30d": tickets_30d,
                "tickets_needed": progress["tickets_needed"],
                "tickets_remaining": tickets_to_next,
                "progress_pct": min(100, round(tickets_30d / max(progress["tickets_needed"], 1) * 100, 1)),
            },
            "totals": {
                "transactions": len(txns),
                "revenue_usd": round(total_revenue, 2),
                "savings_usd": round(total_savings, 2),
                "fees_usd": round(total_fees, 2),
                "net_savings_usd": round(total_savings - total_fees, 2),
            },
            "monthly": monthly_sorted,
            "top_routes": top_routes,
            "markup": {
                "percent": account.consumer_markup_percent,
                "flat_usd": account.consumer_markup_flat_usd,
                "referral_link_enabled": account.referral_link_enabled,
                "referral_code": account.referral_code,
            },
        })

    # ------------------------------------------------------------------
    # Markup Settings (Build #185)
    # ------------------------------------------------------------------

    @app.route("/business/markup", methods=["GET", "POST"])
    @login_required
    @b2b_required
    def business_markup():
        """Consumer markup settings — B2B sellers set their own pricing."""
        from models import db
        from server import BASE_TEMPLATE
        account = g.b2b_account

        if request.method == "POST":
            try:
                markup_pct = float(request.form.get("markup_percent", 0))
                markup_flat = float(request.form.get("markup_flat_usd", 0))
                referral_enabled = request.form.get("referral_link_enabled") == "on"

                # Enforce bounds (0-50%)
                markup_pct = max(0.0, min(50.0, markup_pct))
                markup_flat = max(0.0, min(100.0, markup_flat))

                account.consumer_markup_percent = markup_pct
                account.consumer_markup_flat_usd = markup_flat
                account.referral_link_enabled = referral_enabled
                db.session.commit()
                flash("Markup settings saved.", "success")
            except (ValueError, TypeError):
                flash("Invalid markup values.", "error")

            return redirect("/business/markup")

        markup_content = """
<div style="max-width:700px;margin:30px auto;padding:0 20px;">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:24px;">
        <h1 style="font-family:'Cinzel',serif;font-size:1.6rem;color:#e8dcc8;margin:0;">Pricing & Markup</h1>
        <a href="/business/dashboard" style="color:#8a8278;font-size:0.85rem;text-decoration:none;">&larr; Dashboard</a>
    </div>

    <div style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);
                border-radius:12px;padding:24px;margin-bottom:24px;">
        <div style="color:#8a8278;font-size:0.8rem;text-transform:uppercase;margin-bottom:4px;">
            Your Platform Fee (set by tier)
        </div>
        <div style="color:#4361ee;font-size:1.8rem;font-weight:700;">{{ account.fee_percent }}%</div>
        <div style="color:#8a8278;font-size:0.85rem;margin-top:4px;">
            This is the MYSTES platform fee on savings. Your consumer markup is added ON TOP.
        </div>
    </div>

    <form method="POST" action="/business/markup">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">

        <div style="background:rgba(67,97,238,0.06);border:1px solid rgba(67,97,238,0.15);
                    border-radius:12px;padding:24px;margin-bottom:20px;">
            <h3 style="color:#e8dcc8;font-family:'Cinzel',serif;margin:0 0 16px;">Consumer Markup</h3>
            <p style="color:#8a8278;font-size:0.85rem;margin-bottom:16px;">
                Set the markup your consumers see on top of the MYSTES price.
                This is YOUR revenue on each sale via your referral link.
            </p>

            <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
                <div>
                    <label style="color:#b0a89a;font-size:0.85rem;display:block;margin-bottom:4px;">
                        Percentage Markup (0-50%)
                    </label>
                    <input type="number" name="markup_percent" step="0.5" min="0" max="50"
                           value="{{ account.consumer_markup_percent }}"
                           style="width:100%;padding:10px;background:rgba(255,255,255,0.06);
                                  border:1px solid rgba(255,255,255,0.12);border-radius:6px;
                                  color:#e8dcc8;font-size:1rem;">
                </div>
                <div>
                    <label style="color:#b0a89a;font-size:0.85rem;display:block;margin-bottom:4px;">
                        Flat Markup per Ticket ($0-100)
                    </label>
                    <input type="number" name="markup_flat_usd" step="1" min="0" max="100"
                           value="{{ account.consumer_markup_flat_usd }}"
                           style="width:100%;padding:10px;background:rgba(255,255,255,0.06);
                                  border:1px solid rgba(255,255,255,0.12);border-radius:6px;
                                  color:#e8dcc8;font-size:1rem;">
                </div>
            </div>
        </div>

        <div style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);
                    border-radius:12px;padding:24px;margin-bottom:20px;">
            <h3 style="color:#e8dcc8;font-family:'Cinzel',serif;margin:0 0 12px;">Referral Link</h3>
            <label style="display:flex;align-items:center;gap:10px;cursor:pointer;">
                <input type="checkbox" name="referral_link_enabled"
                       {{ 'checked' if account.referral_link_enabled else '' }}
                       style="width:18px;height:18px;">
                <span style="color:#b0a89a;font-size:0.9rem;">
                    Enable referral link selling (consumers book through your link)
                </span>
            </label>
            {% if account.referral_code %}
            <div style="margin-top:12px;padding:10px 14px;background:rgba(0,0,0,0.3);border-radius:6px;">
                <code style="color:#4361ee;font-size:0.9rem;">
                    {{ base_url }}/ref/{{ account.referral_code }}
                </code>
            </div>
            {% endif %}
        </div>

        <button type="submit"
                style="width:100%;padding:14px;background:#4361ee;color:white;border:none;
                       border-radius:8px;font-size:1.05rem;font-weight:600;cursor:pointer;">
            Save Markup Settings
        </button>
    </form>

    <div style="margin-top:24px;padding:16px;background:rgba(34,197,94,0.06);border:1px solid rgba(34,197,94,0.15);
                border-radius:10px;">
        <div style="color:#22c55e;font-size:0.85rem;font-weight:600;margin-bottom:6px;">
            Revenue Example
        </div>
        <div style="color:#b0a89a;font-size:0.85rem;">
            Flight costs $500 wholesale, Google shows $700. Savings = $200.<br>
            MYSTES fee ({{ account.fee_percent }}%) = ${{ "%.0f"|format(200 * account.fee_percent / 100) }}.
            {% if account.consumer_markup_percent > 0 %}
            Your markup ({{ account.consumer_markup_percent }}%) = ${{ "%.0f"|format(500 * account.consumer_markup_percent / 100) }}.
            {% endif %}
            {% if account.consumer_markup_flat_usd > 0 %}
            Flat markup = ${{ "%.0f"|format(account.consumer_markup_flat_usd) }}.
            {% endif %}
        </div>
    </div>
</div>
"""

        import os
        base_url = os.environ.get("BASE_URL", request.url_root.rstrip("/"))

        return render_template_string(
            BASE_TEMPLATE, title="Pricing & Markup",
            content=render_template_string(
                markup_content,
                account=account,
                base_url=base_url,
                current_user=current_user,
            ),
            current_user=current_user,
        )

    # ------------------------------------------------------------------
    # Referral Link Redirect (Build #185)
    # ------------------------------------------------------------------

    @app.route("/ref/<referral_code>")
    def referral_redirect(referral_code):
        """Redirect from B2B referral link — tracks source in session."""
        from models import CommercialAccount
        account = CommercialAccount.query.filter_by(
            referral_code=referral_code.upper(), is_active=True
        ).first()

        if not account:
            return redirect("/")

        session["referral_source"] = account.account_id
        session["referral_markup_pct"] = account.consumer_markup_percent
        session["referral_markup_flat"] = account.consumer_markup_flat_usd

        return redirect("/flights")

    # ------------------------------------------------------------------
    # Template Deployment REMOVED (Build #193)
    # Deployment is APAi-only — see /apai/deploy in server.py
    # B2B subscribers operate INSIDE MYSTES. No turnkey. No standalone site.
    # ------------------------------------------------------------------

