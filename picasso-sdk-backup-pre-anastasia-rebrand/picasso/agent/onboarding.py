"""
Onboarding — Self-service agency signup, config wizard, API key generation.

Flow:
    1. Agency fills out signup form (name, email, Cockpit credentials, plan)
    2. System generates API key + creates agency config
    3. Stripe subscription created (if payment method provided)
    4. Quickstart guide generated with their API key
    5. Config wizard walks through pricing, display, branding settings

MYSTES KYRIOS LLC — Confidential.
"""

import hashlib
import json
import logging
import os
import re
import time
import uuid
from typing import Optional

from .billing import BillingManager, PLANS
from .config import AgencyConfig, ConfigStore

logger = logging.getLogger(__name__)


# ============================================================================
# VALIDATION
# ============================================================================

def validate_email(email: str) -> bool:
    """Basic email validation."""
    return bool(re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email))


def validate_agency_id(agency_id: str) -> bool:
    """Validate Cockpit agency ID format (numeric string)."""
    return bool(agency_id) and agency_id.strip().isdigit()


def validate_branch(branch: str) -> bool:
    """Validate Cockpit branch format (e.g., PICL_707)."""
    return bool(re.match(r'^[A-Z]{2,10}_\d{1,5}$', branch.strip()))


def slugify(name: str) -> str:
    """Convert agency name to URL-safe slug."""
    slug = name.lower().strip()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'[\s-]+', '-', slug)
    return slug[:50]


# ============================================================================
# SIGNUP WIZARD
# ============================================================================

WIZARD_STEPS = [
    {
        "step": 1,
        "title": "Agency Information",
        "fields": [
            {"name": "agency_name", "label": "Agency Name", "type": "text", "required": True,
             "placeholder": "e.g., Acme Travel Agency"},
            {"name": "email", "label": "Billing Email", "type": "email", "required": True,
             "placeholder": "billing@acmetravel.com"},
            {"name": "contact_name", "label": "Contact Name", "type": "text", "required": True},
            {"name": "phone", "label": "Phone", "type": "tel", "required": False},
        ],
    },
    {
        "step": 2,
        "title": "Cockpit Credentials",
        "description": "Your Redbox/Cockpit API credentials from AERTiCKET. "
                       "These are securely stored and never shared.",
        "fields": [
            {"name": "agency_id", "label": "Agency ID", "type": "text", "required": True,
             "placeholder": "e.g., 629818", "help": "Your numeric agency ID from Cockpit"},
            {"name": "branch", "label": "Branch Code", "type": "text", "required": True,
             "placeholder": "e.g., PICL_707", "help": "Format: XXXX_NNN"},
            {"name": "cockpit_username", "label": "Cockpit Username", "type": "text",
             "required": False, "help": "For auto-login (optional — can use session token instead)"},
            {"name": "cockpit_password", "label": "Cockpit Password", "type": "password",
             "required": False},
            {"name": "totp_secret", "label": "TOTP Secret", "type": "password",
             "required": False, "help": "Base32 secret for 2FA auto-login"},
            {"name": "session_token", "label": "Session Token", "type": "password",
             "required": False, "help": "Manual Redbox session token (alternative to auto-login)"},
        ],
    },
    {
        "step": 3,
        "title": "Choose Your Plan",
        "description": "Select the plan that fits your needs. You can upgrade anytime.",
        "plans": True,  # Signal to render plan cards
    },
    {
        "step": 4,
        "title": "Pricing Setup",
        "description": "Configure how you mark up fares for your customers.",
        "fields": [
            {"name": "pricing_strategy", "label": "Strategy", "type": "select", "required": True,
             "options": [
                 {"value": "flat_fee", "label": "Flat Fee — Fixed amount per booking"},
                 {"value": "percent_total", "label": "Percentage of Total — % of ticket price"},
                 {"value": "percent_base", "label": "Percentage of Base — % of base fare (before tax)"},
                 {"value": "savings_split", "label": "Savings Split — % of savings vs benchmark"},
             ]},
            {"name": "markup_percent", "label": "Markup %", "type": "number", "required": False,
             "placeholder": "10", "help": "Percentage to add (for percentage strategies)"},
            {"name": "markup_flat", "label": "Flat Fee ($)", "type": "number", "required": False,
             "placeholder": "15", "help": "Fixed dollar amount to add per booking"},
        ],
    },
    {
        "step": 5,
        "title": "You're All Set!",
        "description": "Your API key has been generated. Save it securely — "
                       "it won't be shown again.",
        "completion": True,
    },
]


class OnboardingManager:
    """
    Self-service onboarding for new agencies.

    Handles the full signup flow:
    1. Validate input
    2. Generate API key
    3. Create agency config
    4. Create billing subscription
    5. Generate quickstart guide
    """

    def __init__(
        self,
        config_store: ConfigStore,
        billing_manager: BillingManager,
    ):
        self.config_store = config_store
        self.billing = billing_manager

    def get_wizard_steps(self) -> list:
        """Get signup wizard step definitions (for rendering form UI)."""
        steps = []
        for step in WIZARD_STEPS:
            s = dict(step)
            if s.get("plans"):
                s["plan_options"] = self.billing.get_plans()
            steps.append(s)
        return steps

    def validate_step(self, step: int, data: dict) -> dict:
        """
        Validate a single wizard step's data.

        Returns:
            {"valid": bool, "errors": {field: message, ...}}
        """
        errors = {}

        if step == 1:
            if not data.get("agency_name", "").strip():
                errors["agency_name"] = "Agency name is required"
            if not data.get("email") or not validate_email(data["email"]):
                errors["email"] = "Valid email is required"
            if not data.get("contact_name", "").strip():
                errors["contact_name"] = "Contact name is required"

        elif step == 2:
            if not data.get("agency_id") or not validate_agency_id(data["agency_id"]):
                errors["agency_id"] = "Valid numeric agency ID is required"
            if not data.get("branch") or not validate_branch(data["branch"]):
                errors["branch"] = "Valid branch code is required (format: XXXX_NNN)"
            # Either username+password or session_token must be provided
            has_auto = data.get("cockpit_username") and data.get("cockpit_password")
            has_token = data.get("session_token")
            if not has_auto and not has_token:
                errors["session_token"] = (
                    "Either provide Cockpit username + password for auto-login, "
                    "or a manual session token"
                )

        elif step == 3:
            plan_id = data.get("plan_id", "")
            if plan_id not in PLANS:
                errors["plan_id"] = f"Invalid plan. Choose from: {', '.join(PLANS.keys())}"

        elif step == 4:
            strategy = data.get("pricing_strategy", "flat_fee")
            valid_strategies = ("flat_fee", "percent_total", "percent_base", "savings_split", "tiered")
            if strategy not in valid_strategies:
                errors["pricing_strategy"] = f"Invalid strategy. Choose from: {', '.join(valid_strategies)}"
            markup_pct = data.get("markup_percent")
            if markup_pct is not None:
                try:
                    pct = float(markup_pct)
                    if pct < 0 or pct > 100:
                        errors["markup_percent"] = "Markup must be between 0 and 100%"
                except (ValueError, TypeError):
                    errors["markup_percent"] = "Must be a number"

        return {"valid": len(errors) == 0, "errors": errors}

    def signup(self, data: dict) -> dict:
        """
        Complete signup — validates all data, creates everything.

        This is the single-call alternative to stepping through the wizard.

        Args:
            data: All signup fields:
                - agency_name (required)
                - email (required)
                - contact_name (required)
                - agency_id (required)
                - branch (required)
                - cockpit_username, cockpit_password, totp_secret, session_token
                - plan_id (default: starter)
                - pricing_strategy, markup_percent, markup_flat
                - stripe_payment_method (pm_... for Stripe)

        Returns:
            {"success": bool, "api_key": str, "agency_config": dict, ...}
        """
        # Validate all steps
        for step in (1, 2, 3, 4):
            result = self.validate_step(step, data)
            if not result["valid"]:
                return {
                    "success": False,
                    "error": "Validation failed",
                    "step": step,
                    "errors": result["errors"],
                }

        # Generate API key
        api_key = f"ana_{uuid.uuid4().hex}"
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()

        # Build pricing config
        pricing_data = {
            "strategy": data.get("pricing_strategy", "flat_fee"),
            "markup_percent": float(data.get("markup_percent", 10)),
            "markup_flat": float(data.get("markup_flat", 15)),
        }

        # Determine tier from plan
        plan_id = data.get("plan_id", "starter")
        tier_map = {"starter": "tier1", "pro": "tier2", "enterprise": "tier3"}

        # Create agency config
        agency_cfg = AgencyConfig(
            agency_id=data["agency_id"].strip(),
            branch=data["branch"].strip(),
            agency_name=data["agency_name"].strip(),
            agency_slug=slugify(data["agency_name"]),
            cockpit_username=data.get("cockpit_username", ""),
            cockpit_password=data.get("cockpit_password", ""),
            totp_secret=data.get("totp_secret", ""),
            session_token=data.get("session_token", ""),
            pricing=pricing_data,
            tier=tier_map.get(plan_id, "tier2"),
        )

        # Apply plan features to config
        plan = PLANS.get(plan_id)
        if plan:
            for feature in agency_cfg.features:
                agency_cfg.features[feature] = feature in plan.features

        # Save config
        self.config_store.save(key_hash, agency_cfg)

        # Create billing subscription
        billing_result = self.billing.create_subscription(
            key_hash=key_hash,
            plan_id=plan_id,
            email=data["email"],
            agency_name=data["agency_name"],
            stripe_payment_method=data.get("stripe_payment_method", ""),
        )

        if not billing_result.get("success"):
            # Rollback config on billing failure
            self.config_store.delete(key_hash)
            return {
                "success": False,
                "error": f"Billing setup failed: {billing_result.get('error')}",
            }

        # Generate quickstart code
        quickstart = self.generate_quickstart(api_key, agency_cfg)

        logger.info(
            f"Agency onboarded: {data['agency_name']} "
            f"(plan: {plan_id}, key: {key_hash[:8]}...)"
        )

        return {
            "success": True,
            "api_key": api_key,
            "key_hash": key_hash,
            "plan": plan_id,
            "agency_name": data["agency_name"],
            "agency_config": agency_cfg.get_admin_view(),
            "quickstart": quickstart,
            "next_steps": [
                "Save your API key securely — it won't be shown again",
                "Install the SDK: pip install anastasia-sdk[agent]",
                "Visit the ANASTASIA admin dashboard to customize your settings",
                "Try the quickstart code to verify your integration",
            ],
        }

    def generate_quickstart(self, api_key: str, config: AgencyConfig) -> dict:
        """
        Generate quickstart code snippets for the agency.

        Returns code for: Python SDK, API call, and curl.
        """
        masked_key = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else "ana_YOUR_KEY"

        python_sdk = f'''from picasso import RedboxClient

# Initialize with your Cockpit credentials
client = RedboxClient(
    agency_id="{config.agency_id}",
    branch="{config.branch}",
    token_provider=lambda: "YOUR_REDBOX_TOKEN",
)

# Search flights
results = client.search_flights(
    origin="JFK",
    destination="LHR",
    departure_date="2026-04-15",
    adults=1,
    cabin_class="ECONOMY",
)

if results["success"]:
    for flight in results["flights"][:5]:
        print(f"{{flight['airline']}} {{flight['flight_number']}} "
              f"— ${{flight['price']}} ({{flight['stops']}} stops)")
'''

        python_ai = f'''from picasso.agent import BookingAgent
from picasso import RedboxClient

client = RedboxClient(
    agency_id="{config.agency_id}",
    branch="{config.branch}",
    token_provider=lambda: "YOUR_REDBOX_TOKEN",
)

agent = BookingAgent(
    client=client,
    anthropic_api_key="YOUR_ANTHROPIC_KEY",
)

# Natural language flight search
response = agent.chat("Find me the cheapest flight from JFK to London next month")
print(response)
'''

        api_call = f'''import requests

API_KEY = "{masked_key}"
BASE_URL = "https://your-server.com"  # Your hosted instance

# Search flights via API
response = requests.post(
    f"{{BASE_URL}}/api/v1/search/flights",
    headers={{"Authorization": f"Bearer {{API_KEY}}"}},
    json={{
        "origin": "JFK",
        "destination": "LHR",
        "departure_date": "2026-04-15",
        "adults": 1,
    }},
)

data = response.json()
for flight in data["flights"][:5]:
    print(f"{{flight['airline']}} — ${{flight['consumer_price']}}")
'''

        curl_example = f'''# Search flights
curl -X POST https://your-server.com/api/v1/search/flights \\
  -H "Authorization: Bearer {masked_key}" \\
  -H "Content-Type: application/json" \\
  -d '{{"origin": "JFK", "destination": "LHR", "departure_date": "2026-04-15", "adults": 1}}'

# AI Chat
curl -X POST https://your-server.com/api/v1/chat \\
  -H "Authorization: Bearer {masked_key}" \\
  -H "Content-Type: application/json" \\
  -d '{{"message": "Find flights from New York to London next month"}}'
'''

        return {
            "python_sdk": python_sdk,
            "python_ai": python_ai,
            "api_call": api_call,
            "curl": curl_example,
            "dashboard_url": f"/admin/dashboard?key={masked_key}",
            "consumer_url": f"/app?key={masked_key}",
        }


# ============================================================================
# SIGNUP FORM HTML
# ============================================================================

SIGNUP_FORM_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ANASTASIA — Get Started</title>
<link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@400;600&family=Outfit:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: 'Outfit', sans-serif;
    background: #0a0612;
    color: #f5f5f5;
    min-height: 100vh;
}
.container {
    max-width: 680px;
    margin: 0 auto;
    padding: 40px 24px;
}
h1 {
    font-family: 'Cinzel', serif;
    font-size: 28px;
    text-align: center;
    margin-bottom: 8px;
    background: linear-gradient(135deg, #6366f1, #a855f7);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}
.subtitle {
    text-align: center;
    color: #999;
    margin-bottom: 40px;
    font-size: 14px;
}
.step-indicator {
    display: flex;
    justify-content: center;
    gap: 8px;
    margin-bottom: 32px;
}
.step-dot {
    width: 10px; height: 10px;
    border-radius: 50%;
    background: #333;
    transition: background 0.3s;
}
.step-dot.active { background: #6366f1; }
.step-dot.done { background: #22c55e; }
.form-card {
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 12px;
    padding: 32px;
    margin-bottom: 24px;
}
.form-card h2 {
    font-family: 'Cinzel', serif;
    font-size: 20px;
    margin-bottom: 8px;
}
.form-card .desc {
    color: #999;
    font-size: 13px;
    margin-bottom: 24px;
    line-height: 1.5;
}
.field {
    margin-bottom: 20px;
}
.field label {
    display: block;
    font-size: 13px;
    font-weight: 500;
    margin-bottom: 6px;
    color: #ccc;
}
.field input, .field select {
    width: 100%;
    padding: 10px 14px;
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 8px;
    color: #f5f5f5;
    font-family: 'Outfit', sans-serif;
    font-size: 14px;
    outline: none;
    transition: border-color 0.2s;
}
.field input:focus, .field select:focus {
    border-color: #6366f1;
}
.field .help {
    font-size: 11px;
    color: #666;
    margin-top: 4px;
}
.field .error {
    font-size: 11px;
    color: #ef4444;
    margin-top: 4px;
}
.plan-cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 16px;
    margin-bottom: 24px;
}
.plan-card {
    background: rgba(255,255,255,0.04);
    border: 2px solid rgba(255,255,255,0.08);
    border-radius: 12px;
    padding: 20px;
    cursor: pointer;
    transition: border-color 0.2s, transform 0.1s;
    text-align: center;
}
.plan-card:hover { border-color: #6366f1; transform: translateY(-2px); }
.plan-card.selected { border-color: #6366f1; background: rgba(99,102,241,0.1); }
.plan-card h3 {
    font-family: 'Cinzel', serif;
    font-size: 18px;
    margin-bottom: 4px;
}
.plan-card .price {
    font-size: 28px;
    font-weight: 600;
    color: #6366f1;
}
.plan-card .price span { font-size: 14px; color: #999; }
.plan-card .limit {
    font-size: 12px;
    color: #999;
    margin-top: 8px;
}
.plan-card ul {
    list-style: none;
    margin-top: 12px;
    font-size: 12px;
    color: #ccc;
    text-align: left;
}
.plan-card ul li { padding: 3px 0; }
.plan-card ul li::before { content: "\\2713 "; color: #22c55e; }
.btn-row {
    display: flex;
    justify-content: space-between;
    gap: 12px;
}
.btn {
    padding: 12px 28px;
    border: none;
    border-radius: 8px;
    font-family: 'Outfit', sans-serif;
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
    transition: opacity 0.2s;
}
.btn:hover { opacity: 0.85; }
.btn-primary {
    background: linear-gradient(135deg, #6366f1, #a855f7);
    color: white;
    flex: 1;
}
.btn-secondary {
    background: rgba(255,255,255,0.08);
    color: #ccc;
}
.btn:disabled { opacity: 0.4; cursor: not-allowed; }
.api-key-box {
    background: rgba(34, 197, 94, 0.1);
    border: 1px solid rgba(34, 197, 94, 0.3);
    border-radius: 8px;
    padding: 16px;
    margin: 16px 0;
    text-align: center;
}
.api-key-box code {
    font-size: 16px;
    font-family: monospace;
    color: #22c55e;
    word-break: break-all;
    user-select: all;
}
.api-key-box .warning {
    font-size: 11px;
    color: #f59e0b;
    margin-top: 8px;
}
.code-block {
    background: #1a1a2e;
    border-radius: 8px;
    padding: 16px;
    margin: 12px 0;
    overflow-x: auto;
    position: relative;
}
.code-block code {
    font-size: 12px;
    color: #e2e8f0;
    white-space: pre;
    font-family: 'SF Mono', 'Fira Code', monospace;
}
.code-block .copy-btn {
    position: absolute;
    top: 8px;
    right: 8px;
    padding: 4px 12px;
    background: rgba(255,255,255,0.1);
    border: none;
    border-radius: 4px;
    color: #999;
    font-size: 11px;
    cursor: pointer;
}
.next-steps {
    margin-top: 24px;
}
.next-steps ol {
    padding-left: 20px;
    color: #ccc;
    font-size: 14px;
    line-height: 2;
}
.hidden { display: none; }
</style>
</head>
<body>
<div class="container">
    <h1>ANASTASIA</h1>
    <p class="subtitle">AI-Powered Flight Booking Platform — Get Started in 5 Minutes</p>

    <div class="step-indicator" id="stepIndicator"></div>

    <div id="wizardContainer"></div>

    <div class="btn-row" id="btnRow">
        <button class="btn btn-secondary hidden" id="btnBack" onclick="prevStep()">Back</button>
        <button class="btn btn-primary" id="btnNext" onclick="nextStep()">Continue</button>
    </div>
</div>

<script>
const API_BASE = window.ONBOARD_API_BASE || '';
let currentStep = 1;
const totalSteps = 5;
let formData = {};
let signupResult = null;

function renderStepIndicator() {
    const el = document.getElementById('stepIndicator');
    el.innerHTML = '';
    for (let i = 1; i <= totalSteps; i++) {
        const dot = document.createElement('div');
        dot.className = 'step-dot' + (i === currentStep ? ' active' : '') + (i < currentStep ? ' done' : '');
        el.appendChild(dot);
    }
}

function renderStep() {
    renderStepIndicator();
    const container = document.getElementById('wizardContainer');
    const btnBack = document.getElementById('btnBack');
    const btnNext = document.getElementById('btnNext');

    btnBack.classList.toggle('hidden', currentStep === 1);
    btnNext.textContent = currentStep === 4 ? 'Create Account' : currentStep === 5 ? 'Open Dashboard' : 'Continue';

    if (currentStep === 1) {
        container.innerHTML = `
            <div class="form-card">
                <h2>Agency Information</h2>
                <div class="field"><label>Agency Name *</label>
                    <input id="agency_name" value="${formData.agency_name||''}" placeholder="e.g., Acme Travel Agency">
                </div>
                <div class="field"><label>Billing Email *</label>
                    <input id="email" type="email" value="${formData.email||''}" placeholder="billing@acmetravel.com">
                </div>
                <div class="field"><label>Contact Name *</label>
                    <input id="contact_name" value="${formData.contact_name||''}" placeholder="John Smith">
                </div>
                <div class="field"><label>Phone</label>
                    <input id="phone" type="tel" value="${formData.phone||''}" placeholder="+1 (555) 000-0000">
                </div>
            </div>`;
    } else if (currentStep === 2) {
        container.innerHTML = `
            <div class="form-card">
                <h2>Cockpit Credentials</h2>
                <p class="desc">Your Redbox/Cockpit API credentials from AERTiCKET. Securely stored, never shared.</p>
                <div class="field"><label>Agency ID *</label>
                    <input id="agency_id" value="${formData.agency_id||''}" placeholder="e.g., 629818">
                    <div class="help">Your numeric agency ID from Cockpit</div>
                </div>
                <div class="field"><label>Branch Code *</label>
                    <input id="branch" value="${formData.branch||''}" placeholder="e.g., PICL_707">
                    <div class="help">Format: XXXX_NNN</div>
                </div>
                <div class="field"><label>Cockpit Username</label>
                    <input id="cockpit_username" value="${formData.cockpit_username||''}" placeholder="For auto-login">
                </div>
                <div class="field"><label>Cockpit Password</label>
                    <input id="cockpit_password" type="password" value="${formData.cockpit_password||''}">
                </div>
                <div class="field"><label>TOTP Secret</label>
                    <input id="totp_secret" type="password" value="${formData.totp_secret||''}" placeholder="Base32 secret for 2FA">
                </div>
                <div class="field"><label>Session Token</label>
                    <input id="session_token" type="password" value="${formData.session_token||''}" placeholder="Alternative to auto-login">
                    <div class="help">Provide either username+password OR session token</div>
                </div>
            </div>`;
    } else if (currentStep === 3) {
        container.innerHTML = `
            <div class="form-card">
                <h2>Choose Your Plan</h2>
                <p class="desc">Select the plan that fits your needs. Upgrade or downgrade anytime.</p>
                <div class="plan-cards">
                    <div class="plan-card ${formData.plan_id==='starter'?'selected':''}" onclick="selectPlan('starter')">
                        <h3>Starter</h3>
                        <div class="price">$249<span>/mo</span></div>
                        <div class="limit">2,000 AI requests/mo</div>
                        <ul><li>AI Chat</li><li>Flight Search</li><li>Config Dashboard</li><li>Fare Rules + Seatmaps</li></ul>
                    </div>
                    <div class="plan-card ${formData.plan_id==='pro'||!formData.plan_id?'selected':''}" onclick="selectPlan('pro')">
                        <h3>Pro</h3>
                        <div class="price">$599<span>/mo</span></div>
                        <div class="limit">10,000 AI requests/mo</div>
                        <ul><li>Everything in Starter</li><li>Booking + Ticketing</li><li>Auto-Heal Daemon</li><li>Audit Trail</li><li>Insurance + Extras</li></ul>
                    </div>
                    <div class="plan-card ${formData.plan_id==='enterprise'?'selected':''}" onclick="selectPlan('enterprise')">
                        <h3>Enterprise</h3>
                        <div class="price">$1,499<span>/mo</span></div>
                        <div class="limit">50,000 AI requests/mo</div>
                        <ul><li>Everything in Pro</li><li>Consumer UI Template</li><li>White-Label Branding</li><li>Webhooks</li><li>Priority Support</li></ul>
                    </div>
                </div>
            </div>`;
    } else if (currentStep === 4) {
        container.innerHTML = `
            <div class="form-card">
                <h2>Pricing Setup</h2>
                <p class="desc">How do you want to mark up fares for your customers?</p>
                <div class="field"><label>Pricing Strategy</label>
                    <select id="pricing_strategy">
                        <option value="flat_fee" ${formData.pricing_strategy==='flat_fee'?'selected':''}>Flat Fee — Fixed amount per booking</option>
                        <option value="percent_total" ${formData.pricing_strategy==='percent_total'?'selected':''}>Percentage of Total Price</option>
                        <option value="percent_base" ${formData.pricing_strategy==='percent_base'?'selected':''}>Percentage of Base Fare</option>
                        <option value="savings_split" ${formData.pricing_strategy==='savings_split'?'selected':''}>Savings Split</option>
                    </select>
                </div>
                <div class="field"><label>Markup Percentage (%)</label>
                    <input id="markup_percent" type="number" value="${formData.markup_percent||'10'}" min="0" max="100" step="0.5">
                </div>
                <div class="field"><label>Flat Fee ($)</label>
                    <input id="markup_flat" type="number" value="${formData.markup_flat||'15'}" min="0" max="999" step="0.5">
                </div>
            </div>`;
    } else if (currentStep === 5 && signupResult) {
        container.innerHTML = `
            <div class="form-card">
                <h2 style="color:#22c55e">Account Created!</h2>
                <p class="desc">Welcome to ANASTASIA, ${signupResult.agency_name}.</p>
                <div class="api-key-box">
                    <div style="font-size:12px;color:#999;margin-bottom:8px">Your API Key</div>
                    <code>${signupResult.api_key}</code>
                    <div class="warning">Save this key securely — it will not be shown again.</div>
                </div>
                <div class="next-steps">
                    <h3 style="margin-bottom:8px">Next Steps</h3>
                    <ol>${signupResult.next_steps.map(s=>'<li>'+s+'</li>').join('')}</ol>
                </div>
                <h3 style="margin-top:24px;margin-bottom:8px">Quick Start</h3>
                <div class="code-block"><code>${escapeHtml(signupResult.quickstart.python_sdk)}</code></div>
            </div>`;
    }
}

function collectStepData() {
    const fields = document.querySelectorAll('.form-card input, .form-card select');
    fields.forEach(f => { if (f.id) formData[f.id] = f.value; });
}

function selectPlan(planId) {
    formData.plan_id = planId;
    document.querySelectorAll('.plan-card').forEach(c => c.classList.remove('selected'));
    event.currentTarget.classList.add('selected');
}

async function nextStep() {
    collectStepData();
    if (currentStep === 4) {
        // Submit signup
        document.getElementById('btnNext').disabled = true;
        document.getElementById('btnNext').textContent = 'Creating...';
        try {
            const resp = await fetch(API_BASE + '/api/v1/onboard/signup', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(formData),
            });
            signupResult = await resp.json();
            if (!signupResult.success) {
                alert('Error: ' + (signupResult.error || JSON.stringify(signupResult.errors)));
                document.getElementById('btnNext').disabled = false;
                document.getElementById('btnNext').textContent = 'Create Account';
                return;
            }
        } catch(e) {
            alert('Network error: ' + e.message);
            document.getElementById('btnNext').disabled = false;
            document.getElementById('btnNext').textContent = 'Create Account';
            return;
        }
    }
    if (currentStep === 5 && signupResult) {
        window.location.href = signupResult.quickstart.dashboard_url;
        return;
    }
    if (currentStep < totalSteps) { currentStep++; renderStep(); }
}

function prevStep() {
    if (currentStep > 1) { collectStepData(); currentStep--; renderStep(); }
}

function escapeHtml(s) {
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// Init
formData.plan_id = formData.plan_id || 'pro';
formData.pricing_strategy = formData.pricing_strategy || 'flat_fee';
renderStep();
</script>
</body>
</html>"""
