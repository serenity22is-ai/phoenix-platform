"""
MYSTES Insurance Routes — Build #186

Travel insurance vertical powered by SafetyWing via ANASTASiA InsuranceNeuron.
Cross-sell on every flight/hotel booking. Standalone search page.

Routes:
    GET  /insurance              — Search page
    POST /api/insurance/search   — Get quotes
    POST /api/insurance/select   — Select plan → create Deal
    POST /api/insurance/plans    — List available plans

MYSTES KYRIOS LLC — Confidential.
"""

import json
import logging
from datetime import datetime, timezone
from flask import (
    jsonify, redirect, render_template_string,
    request, url_for,
)
from flask_login import current_user, login_required

logger = logging.getLogger(__name__)


# ============================================================
# Search Page Template
# ============================================================

INSURANCE_SEARCH_CONTENT = """
<style>
.ins-page { max-width: 900px; margin: 0 auto; padding: 0 20px 40px; animation: fadeInUp 0.6s ease-out both; }
.ins-form-card { margin-bottom: 24px; animation: fadeInUp 0.6s ease-out 0.15s both; }
.ins-results-header { font-family: var(--font-brand, 'Space Grotesk', sans-serif); font-size: 1.3rem; color: var(--text-bright, #e2e8f0); margin-bottom: 16px; letter-spacing: 2px; }
.ins-quote-card { border-left: 4px solid var(--accent-purple); margin-bottom: 14px; animation: fadeInUp 0.5s ease-out both; }
.ins-quote-inner { display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 12px; }
.ins-quote-detail { flex: 1; min-width: 200px; }
.ins-quote-detail h3 { color: var(--text-bright, #f5f5f5); font-size: 17px; font-weight: 600; margin: 0 0 6px; }
.ins-quote-detail p { color: var(--text-muted, rgba(255,255,255,0.5)); font-size: 13px; margin: 0 0 10px; }
.ins-quote-price { text-align: right; flex-shrink: 0; }
.ins-quote-price .price-amount { font-size: 28px; font-weight: 800; color: #4ade80; }
.ins-quote-price .price-currency { font-size: 12px; color: var(--text-muted, rgba(255,255,255,0.4)); margin-bottom: 10px; }
.ins-skel-card { background: var(--glass-bg); border: 1px solid rgba(124, 58, 237, 0.15); border-radius: var(--radius-lg); padding: 22px; margin-bottom: 14px; }
.ins-skel-line { height: 14px; border-radius: var(--radius-sm); margin-bottom: 10px; }
.ins-loading-text { text-align: center; color: var(--text-muted, rgba(255,255,255,0.4)); margin-top: 16px; display: flex; align-items: center; justify-content: center; gap: 10px; }
@media (max-width: 700px) { .ins-quote-inner { flex-direction: column; gap: 12px; } }
</style>

<div class="ins-page">
    <div class="mystes-page-header">
        <h1>Travel Insurance</h1>
        <p>Coverage for nomads & travelers worldwide &mdash; powered by SafetyWing</p>
    </div>

    <div class="mystes-card ins-form-card">
        <div class="mystes-form-grid">
            <div>
                <label class="mystes-label">Destination Country</label>
                <input type="text" id="insuranceDestination" class="mystes-input"
                       placeholder="e.g. France, Thailand, Japan" list="ins-countries" />
                <datalist id="ins-countries">
                    <option value="United States"><option value="United Kingdom"><option value="France">
                    <option value="Germany"><option value="Spain"><option value="Italy"><option value="Japan">
                    <option value="Thailand"><option value="Australia"><option value="Canada">
                    <option value="Mexico"><option value="Brazil"><option value="India">
                    <option value="South Korea"><option value="Portugal"><option value="Greece">
                    <option value="Turkey"><option value="Colombia"><option value="Morocco">
                    <option value="Indonesia"><option value="Vietnam"><option value="Costa Rica">
                </datalist>
            </div>
            <div>
                <label class="mystes-label">Travelers</label>
                <select id="insuranceTravelers" class="mystes-select">
                    <option value="1">1 Traveler</option>
                    <option value="2" selected>2 Travelers</option>
                    <option value="3">3 Travelers</option>
                    <option value="4">4 Travelers</option>
                    <option value="5">5 Travelers</option>
                </select>
            </div>
            <div>
                <label class="mystes-label">Start Date</label>
                <input type="date" id="insuranceStartDate" class="mystes-input" />
            </div>
            <div>
                <label class="mystes-label">End Date</label>
                <input type="date" id="insuranceEndDate" class="mystes-input" />
            </div>
        </div>
        <button onclick="searchInsurance()" id="insuranceSearchBtn"
                class="mystes-btn mystes-btn-primary mystes-btn-lg mystes-btn-full" style="margin-top:20px;letter-spacing:2px;text-transform:uppercase;">
            Get Quotes
        </button>
    </div>

    <div id="insuranceLoading" style="display:none;">
        <div class="ins-skel-card"><div class="ins-skel-line mystes-skeleton" style="width:60%"></div><div class="ins-skel-line mystes-skeleton" style="width:40%"></div><div class="ins-skel-line mystes-skeleton" style="width:80%"></div></div>
        <div class="ins-skel-card"><div class="ins-skel-line mystes-skeleton" style="width:50%"></div><div class="ins-skel-line mystes-skeleton" style="width:70%"></div><div class="ins-skel-line mystes-skeleton" style="width:45%"></div></div>
        <div class="ins-skel-card"><div class="ins-skel-line mystes-skeleton" style="width:65%"></div><div class="ins-skel-line mystes-skeleton" style="width:35%"></div><div class="ins-skel-line mystes-skeleton" style="width:55%"></div></div>
        <p class="ins-loading-text">
            <span class="mystes-spinner mystes-spinner-sm"></span>
            Getting quotes from SafetyWing...
        </p>
    </div>

    <div id="insuranceResults" style="display:none;">
        <h2 class="ins-results-header">Available Plans</h2>
        <div id="insuranceQuotesList"></div>
    </div>
</div>

<script>
(function(){
    var d = new Date();
    d.setDate(d.getDate() + 1);
    var s = d.toISOString().split('T')[0];
    document.getElementById('insuranceStartDate').value = s;
    document.getElementById('insuranceStartDate').min = s;
    var e = new Date(d);
    e.setDate(e.getDate() + 14);
    document.getElementById('insuranceEndDate').value = e.toISOString().split('T')[0];
    document.getElementById('insuranceEndDate').min = s;
})();

function searchInsurance() {
    var dest = document.getElementById('insuranceDestination').value.trim();
    var travelers = parseInt(document.getElementById('insuranceTravelers').value);
    var startDate = document.getElementById('insuranceStartDate').value;
    var endDate = document.getElementById('insuranceEndDate').value;
    if (!dest || !startDate || !endDate) {
        if (window.showToast) showToast('Please fill in destination, start date, and end date', 'warning');
        else alert('Please fill in destination, start date, and end date');
        return;
    }
    var btn = document.getElementById('insuranceSearchBtn');
    btn.disabled = true; btn.textContent = 'Searching...';
    document.getElementById('insuranceLoading').style.display = 'block';
    document.getElementById('insuranceResults').style.display = 'none';

    var csrfToken = document.querySelector('meta[name="csrf-token"]');
    var headers = {'Content-Type': 'application/json'};
    if (csrfToken) headers['X-CSRFToken'] = csrfToken.content;

    fetch('/api/insurance/search', {
        method: 'POST', headers: headers, credentials: 'same-origin',
        body: JSON.stringify({destination: dest, start_date: startDate, end_date: endDate, travelers: travelers})
    })
    .then(function(r){ return r.json(); })
    .then(function(data) {
        document.getElementById('insuranceLoading').style.display = 'none';
        btn.disabled = false; btn.textContent = 'Get Quotes';
        if (data.success && data.quotes && data.quotes.length > 0) {
            document.getElementById('insuranceResults').style.display = 'block';
            renderQuotes(data.quotes);
        } else {
            document.getElementById('insuranceResults').style.display = 'block';
            document.getElementById('insuranceQuotesList').innerHTML =
                '<div class="mystes-empty"><div class="mystes-empty-icon">&#128722;</div><p>No quotes available for this destination.<br>Try different dates or destination.</p></div>';
        }
    })
    .catch(function(err) {
        document.getElementById('insuranceLoading').style.display = 'none';
        btn.disabled = false; btn.textContent = 'Get Quotes';
        if (window.showToast) showToast('Error getting quotes: ' + err.message, 'error');
        else alert('Error getting quotes: ' + err.message);
    });
}

function renderQuotes(quotes) {
    var container = document.getElementById('insuranceQuotesList');
    var html = '';
    quotes.forEach(function(q, i) {
        var delay = (i * 0.08).toFixed(2);
        html += '<div class="mystes-card interactive ins-quote-card" style="animation-delay:' + delay + 's">';
        html += '<div class="ins-quote-inner">';
        html += '<div class="ins-quote-detail">';
        html += '<h3>' + (q.plan_name || 'SafetyWing Plan') + '</h3>';
        html += '<p>' + q.start_date + ' to ' + q.end_date + ' &bull; ' + q.travelers + ' traveler(s)</p>';
        html += '<div style="display:flex;flex-wrap:wrap;gap:4px">';
        if (q.coverage_amount) html += '<span class="mystes-badge mystes-badge-purple">Coverage: $' + Number(q.coverage_amount).toLocaleString() + '</span>';
        if (q.deductible !== undefined && q.deductible !== null) html += '<span class="mystes-badge mystes-badge-amber">Deductible: $' + q.deductible + '</span>';
        if (q.price_per_day > 0) html += '<span class="mystes-badge mystes-badge-teal">$' + q.price_per_day.toFixed(2) + '/day</span>';
        html += '</div></div>';
        html += '<div class="ins-quote-price">';
        html += '<div class="price-amount">$' + (q.total_price || 0).toFixed(2) + '</div>';
        html += '<div class="price-currency">' + (q.currency || 'USD') + ' total</div>';
        html += '<button onclick="selectInsurance(' + i + ')" class="mystes-btn mystes-btn-primary mystes-btn-sm">Select Plan</button>';
        html += '</div></div></div>';
    });
    container.innerHTML = html;
    window._insuranceQuotes = quotes;
}

function selectInsurance(index) {
    var quote = window._insuranceQuotes[index];
    if (!quote) return;
    var btns = document.querySelectorAll('.ins-quote-card .mystes-btn');
    btns.forEach(function(b){ b.disabled = true; b.textContent = 'Loading...'; });
    var csrfToken = document.querySelector('meta[name="csrf-token"]');
    var headers = {'Content-Type': 'application/json'};
    if (csrfToken) headers['X-CSRFToken'] = csrfToken.content;
    fetch('/api/insurance/select', {
        method: 'POST', headers: headers, credentials: 'same-origin',
        body: JSON.stringify({quote: quote})
    })
    .then(function(r){ return r.json(); })
    .then(function(data) {
        if (data.success && data.deal_id) {
            window.location.href = '/book/' + data.deal_id;
        } else {
            btns.forEach(function(b){ b.disabled = false; b.textContent = 'Select Plan'; });
            if (window.showToast) showToast(data.error || 'Failed to select plan', 'error');
            else alert(data.error || 'Failed to select plan');
        }
    })
    .catch(function(err){
        btns.forEach(function(b){ b.disabled = false; b.textContent = 'Select Plan'; });
        if (window.showToast) showToast('Error: ' + err.message, 'error');
        else alert('Error: ' + err.message);
    });
}
</script>
"""


# ============================================================
# Country Code Resolution
# ============================================================

_COUNTRY_CODES = {
    "france": "FR", "germany": "DE", "spain": "ES", "italy": "IT",
    "united kingdom": "GB", "uk": "GB", "japan": "JP", "thailand": "TH",
    "mexico": "MX", "canada": "CA", "australia": "AU", "brazil": "BR",
    "india": "IN", "colombia": "CO", "portugal": "PT", "greece": "GR",
    "turkey": "TR", "indonesia": "ID", "bali": "ID", "vietnam": "VN",
    "south korea": "KR", "korea": "KR", "costa rica": "CR",
    "united states": "US", "us": "US", "usa": "US",
}


def _resolve_country_code(destination):
    """Resolve freetext destination to ISO country code."""
    d = destination.strip().lower()
    if len(d) == 2:
        return d.upper()
    return _COUNTRY_CODES.get(d, d[:2].upper())


# ============================================================
# Route Registration
# ============================================================

def register_insurance_routes(app, csrf, limiter):
    """Register insurance vertical routes on the Flask app."""
    from server import BASE_TEMPLATE, is_feature_enabled

    @app.route("/insurance")
    def insurance():
        """Insurance search page."""
        return render_template_string(
            BASE_TEMPLATE,
            title="Travel Insurance",
            content=render_template_string(INSURANCE_SEARCH_CONTENT, current_user=current_user),
            current_user=current_user,
        )

    @app.route("/api/insurance/search", methods=["POST"])
    @csrf.exempt
    def api_insurance_search():
        """Get insurance quotes via SafetyWing."""
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400

        destination = data.get("destination", "").strip()
        start_date = data.get("start_date")
        end_date = data.get("end_date")
        travelers = data.get("travelers", 1)

        if not destination:
            return jsonify({"success": False, "error": "Destination required"}), 400
        if not start_date or not end_date:
            return jsonify({"success": False, "error": "Start and end dates required"}), 400

        country_code = _resolve_country_code(destination)

        try:
            from safetywing_client import SafetyWingClient

            client = SafetyWingClient()
            if not client.is_configured():
                return jsonify({"success": False, "error": "Insurance not configured", "quotes": []})

            # ANASTASiA InsuranceNeuron dispatch — fallback to direct client
            _used_neuron = False
            result = None
            try:
                from anastasia.verticals.insurance import InsuranceNeuron
                from anastasia.core.events import EventBus
                _neuron = InsuranceNeuron()
                _neuron.initialize(EventBus(), {"insurance_enabled": True})
                result = _neuron.search(
                    destination_country=country_code,
                    start_date=start_date,
                    end_date=end_date,
                    travelers=travelers,
                    client=client,
                )
                _used_neuron = result.get("success", False)
            except Exception as _neuron_err:
                logger.debug("[ANASTASiA] InsuranceNeuron unavailable: %s", _neuron_err)

            if not _used_neuron:
                result = client.get_quote(
                    destination_country=country_code,
                    start_date=start_date,
                    end_date=end_date,
                    travelers=travelers,
                )

            if not result or not result.get("success"):
                return jsonify({
                    "success": False,
                    "error": result.get("error", "No quotes available") if result else "Search failed",
                    "quotes": [],
                })

            quotes = result.get("quotes", [])

            # Attach raw_offer if not already present (for direct client results)
            for q in quotes:
                if "raw_offer" not in q:
                    q["raw_offer"] = {
                        "source": "safetywing",
                        "quote_id": q.get("quote_id", ""),
                        "plan_name": q.get("plan_name", ""),
                        "destination": country_code,
                        "start_date": start_date,
                        "end_date": end_date,
                        "travelers": travelers,
                    }

            return jsonify({
                "success": True,
                "quotes": quotes,
                "source": "safetywing",
                "neuron_used": _used_neuron,
            })

        except ImportError:
            return jsonify({"success": False, "error": "SafetyWing client not available", "quotes": []})
        except Exception as e:
            logger.error("Insurance search error: %s", e)
            return jsonify({"success": False, "error": "Search failed", "quotes": []})

    @app.route("/api/insurance/select", methods=["POST"])
    @csrf.exempt
    @login_required
    def api_insurance_select():
        """Select an insurance plan and create a Deal for checkout."""
        from models import db, Deal
        import secrets as _secrets

        data = request.get_json()
        if not data or "quote" not in data:
            return jsonify({"success": False, "error": "No quote selected"}), 400

        quote = data["quote"]
        total_price = float(quote.get("total_price", 0))

        if total_price <= 0:
            return jsonify({"success": False, "error": "Invalid price"}), 400

        # Calculate platform fee
        from payments import get_fee_percent
        fee_pct = get_fee_percent(current_user)
        platform_fee = max(3.0, total_price * (fee_pct / 100.0))

        deal = Deal(
            deal_id=f"INS_{_secrets.token_hex(8).upper()}",
            deal_type="insurance",
            is_active=True,
            claimed_by=current_user.id,
            claimed_at=datetime.now(timezone.utc),
            deal_status="claimed",
            arbitrage_price_usd=total_price,
            platform_fee_usd=platform_fee,
            amadeus_offer_data=json.dumps({
                "quote": quote,
                "destination": quote.get("destination"),
                "start_date": quote.get("start_date"),
                "end_date": quote.get("end_date"),
                "travelers": quote.get("travelers"),
                "plan_name": quote.get("plan_name", "SafetyWing"),
                "raw_offer": quote.get("raw_offer"),
            }),
        )
        db.session.add(deal)
        db.session.commit()

        logger.info("Insurance deal created: %s ($%.2f + $%.2f fee)", deal.deal_id, total_price, platform_fee)

        return jsonify({
            "success": True,
            "deal_id": deal.deal_id,
            "total_price": total_price,
            "platform_fee": platform_fee,
        })

    @app.route("/api/insurance/plans", methods=["POST"])
    @csrf.exempt
    def api_insurance_plans():
        """List available insurance plans."""
        try:
            from safetywing_client import SafetyWingClient
            client = SafetyWingClient()
            if not client.is_configured():
                return jsonify({"success": False, "error": "Insurance not configured", "plans": []})
            return jsonify(client.get_plans())
        except ImportError:
            return jsonify({"success": False, "error": "SafetyWing client not available", "plans": []})
        except Exception as e:
            logger.error("Insurance plans error: %s", e)
            return jsonify({"success": False, "error": "Failed to load plans", "plans": []})
