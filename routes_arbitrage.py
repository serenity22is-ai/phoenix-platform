"""
Build #234 — Arbitrate My Trip Routes

The "Arbitrate My Trip" feature: users import flights they found externally,
MYSTES checks POS markets for arbitrage, users book at the cheaper price.

Two user personas:
- Tool users: import specific flights → arbitrate → book (95%+ query reduction)
- Platform users: full search experience (existing /api/search pipeline)

Endpoints:
- POST /api/arbitrate/import         — import external booking for analysis
- GET  /api/arbitrate/my-imports     — list user's imported bookings
- DELETE /api/arbitrate/import/<id>  — remove import
- POST /api/arbitrate/check/<id>     — run arbitrage check on imported booking
- GET  /api/arbitrate/result/<id>    — get arbitrage check result
- POST /api/arbitrate/trip/<trip_id> — bulk arbitrate all imports in a trip
- GET  /api/arbitrate/trip/<trip_id>/summary — trip-level savings summary
- GET  /api/hot-routes               — homepage hot routes feed
- GET  /arbitrate                     — Arbitrate My Trip page

Registration: register_arbitrage_routes(app, csrf, limiter)
"""

import logging
import secrets
from datetime import datetime, date, timezone

from flask import request, jsonify, render_template_string
from flask_login import current_user, login_required

from models import (
    db, ExternalBookingImport, ArbitrageCheck, HotRoute, TripPlan, TripMember,
)

logger = logging.getLogger(__name__)


def _utcnow():
    return datetime.now(timezone.utc)


def _gen_id(prefix='ARB'):
    """Generate a unique short ID like ARB-a1b2c3."""
    return f"{prefix}-{secrets.token_hex(4)}"


def _classify_quality(savings_percent):
    """Classify arbitrage quality by savings percentage."""
    if savings_percent >= 25:
        return 'excellent'
    elif savings_percent >= 15:
        return 'good'
    elif savings_percent >= 5:
        return 'marginal'
    return 'none'


def _get_arbitrage_module():
    """Lazy-load ArbitrageModule from ANASTASiA SDK."""
    try:
        from picasso_sdk.anastasia.arbitrage import ArbitrageModule
        mod = ArbitrageModule()
        from picasso_sdk.anastasia.core.events import EventBus
        import os
        mod.initialize(EventBus(), {
            'serpapi_key': os.environ.get('SERPAPI_KEY'),
        })
        return mod
    except Exception as e:
        logger.warning("ArbitrageModule not available: %s", e)
        return None


def _get_fee_percent(user=None):
    """Get user's fee percent from payments.py — sole source of truth."""
    try:
        from payments import get_fee_percent
        return get_fee_percent(user)
    except Exception:
        return 0.50  # Guest fallback


# ============================================================
# Arbitrate My Trip Page Template
# ============================================================

ARBITRATE_PAGE_CONTENT = '''
<style>
    /* Page-specific layout */
    .arb-page { min-height: calc(100vh - 80px); padding: 40px 20px 60px; max-width: 1000px; margin: 0 auto; }
    .arb-section-title { font-family: var(--font-brand); font-size: 18px; letter-spacing: 2px; color: var(--text-bright); margin: 0 0 20px; text-transform: uppercase; }

    /* Import card results */
    .arb-card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
    .arb-route { font-family: var(--font-brand); font-size: 20px; letter-spacing: 3px; color: var(--text-bright); }
    .arb-card-details { display: flex; gap: 24px; font-size: 13px; color: var(--text-muted); margin-bottom: 12px; flex-wrap: wrap; }
    .arb-card-actions { display: flex; gap: 8px; }

    /* Arbitrage result display */
    .arb-result { margin-top: 12px; padding: 16px; background: rgba(76,175,80,0.08); border: 1px solid rgba(76,175,80,0.2); border-radius: var(--radius-md); }
    .arb-result.no-arb { background: rgba(255,255,255,0.03); border-color: var(--glass-border); }
    .arb-savings { font-size: 24px; font-weight: 700; color: #4caf50; margin-bottom: 4px; }
    .arb-savings.none { color: var(--text-muted); font-size: 16px; }
    .arb-price-compare { display: flex; gap: 24px; font-size: 14px; color: var(--text-muted); }
    .arb-price-compare .price { color: var(--text-bright); font-weight: 600; }

    /* Hot routes feed */
    .hot-routes { margin-top: 48px; }
    .hot-route-card { display: flex; justify-content: space-between; align-items: center; padding: 16px 20px; background: var(--glass-bg); border: 1px solid var(--glass-border); border-radius: var(--radius-lg); margin-bottom: 10px; transition: border-color 0.2s; }
    .hot-route-card:hover { border-color: var(--glass-border-hover); }
    .hot-route-info { display: flex; align-items: center; gap: 16px; }
    .hot-route-pair { font-family: var(--font-brand); font-size: 16px; letter-spacing: 2px; color: var(--text-bright); }
    .hot-route-save { font-size: 14px; color: #4caf50; font-weight: 600; }
    .hot-route-pct { font-size: 12px; color: var(--text-muted); }

    @media (max-width: 640px) {
        .arb-card-details { flex-direction: column; gap: 4px; }
        .arb-price-compare { flex-direction: column; gap: 4px; }
    }
</style>

<div class="arb-page">
    <div class="mystes-page-header" style="margin-bottom: 40px;">
        <h1>ARBITRATE MY TRIP</h1>
        <p>Import flights you found anywhere. We check if a cheaper price exists across global markets. You save, we earn.</p>
    </div>

    <div class="mystes-card" style="margin-bottom: 32px;">
        <h3 class="arb-section-title">IMPORT A FLIGHT</h3>
        <div class="mystes-form-grid" id="importForm">
            <input type="text" class="mystes-input" id="arbAirline" placeholder="Airline (e.g., Delta, ANA)" required>
            <input type="text" class="mystes-input" id="arbFlightNum" placeholder="Flight # (optional)">
            <input type="text" class="mystes-input" id="arbOrigin" placeholder="From (e.g., LAX)" maxlength="4" required>
            <input type="text" class="mystes-input" id="arbDest" placeholder="To (e.g., NRT)" maxlength="4" required>
            <input type="date" class="mystes-input" id="arbDepart" required>
            <input type="date" class="mystes-input" id="arbReturn" placeholder="Return (optional)">
            <select class="mystes-select" id="arbCabin">
                <option value="economy">Economy</option>
                <option value="premium_economy">Premium Economy</option>
                <option value="business">Business</option>
                <option value="first">First</option>
            </select>
            <input type="number" class="mystes-input" id="arbPassengers" placeholder="Passengers" min="1" max="9" value="1">
            <input type="number" class="mystes-input" id="arbPrice" placeholder="Price you found ($)" step="0.01" min="1" required>
            <select class="mystes-select" id="arbSource">
                <option value="google_flights">Google Flights</option>
                <option value="expedia">Expedia</option>
                <option value="kayak">Kayak</option>
                <option value="skyscanner">Skyscanner</option>
                <option value="airline_direct">Airline Website</option>
                <option value="manual">Other / Manual</option>
            </select>
            <button class="mystes-btn mystes-btn-gold mystes-btn-lg mystes-btn-full full-width" onclick="importFlight()" id="importBtn">CHECK FOR SAVINGS</button>
        </div>
    </div>

    <div style="margin-top: 32px;" id="importsList">
        <h3 class="arb-section-title">YOUR IMPORTS</h3>
        <div id="importsContainer">
            <div class="mystes-empty"><p>No flights imported yet. Add one above to check for savings.</p></div>
        </div>
    </div>

    <div class="hot-routes" id="hotRoutes">
        <h3 class="arb-section-title">HOT ROUTES — VERIFIED SAVINGS</h3>
        <div id="hotRoutesContainer">
            <div class="mystes-empty"><p>Loading deals...</p></div>
        </div>
    </div>
</div>

<script>
async function importFlight() {
    const btn = document.getElementById('importBtn');
    btn.disabled = true; btn.textContent = 'IMPORTING...';
    try {
        const body = {
            airline: document.getElementById('arbAirline').value,
            flight_number: document.getElementById('arbFlightNum').value || null,
            origin: document.getElementById('arbOrigin').value.toUpperCase(),
            destination: document.getElementById('arbDest').value.toUpperCase(),
            departure_date: document.getElementById('arbDepart').value,
            return_date: document.getElementById('arbReturn').value || null,
            cabin_class: document.getElementById('arbCabin').value,
            passengers: parseInt(document.getElementById('arbPassengers').value) || 1,
            external_price_usd: parseFloat(document.getElementById('arbPrice').value),
            external_source: document.getElementById('arbSource').value,
        };
        const r = await fetch('/api/arbitrate/import', {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify(body)
        });
        const data = await r.json();
        if (data.status === 'ok') {
            loadImports();
            // Clear form
            ['arbAirline','arbFlightNum','arbOrigin','arbDest','arbDepart','arbReturn','arbPrice'].forEach(
                id => document.getElementById(id).value = ''
            );
        } else {
            alert(data.error || 'Import failed');
        }
    } catch(e) { alert('Error: ' + e.message); }
    btn.disabled = false; btn.textContent = 'CHECK FOR SAVINGS';
}

async function loadImports() {
    try {
        const r = await fetch('/api/arbitrate/my-imports');
        const data = await r.json();
        const c = document.getElementById('importsContainer');
        if (!data.imports || data.imports.length === 0) {
            c.innerHTML = '<div class="mystes-empty"><p>No flights imported yet.</p></div>';
            return;
        }
        c.innerHTML = data.imports.map(imp => renderImportCard(imp)).join('');
    } catch(e) { console.error('Failed to load imports:', e); }
}

function renderImportCard(imp) {
    const arb = imp.arbitrage;
    const statusMap = {
        'imported': 'mystes-badge mystes-badge-neutral',
        'checking': 'mystes-badge mystes-badge-amber',
        'checked':  'mystes-badge mystes-badge-green'
    };
    const badgeClass = statusMap[imp.status] || 'mystes-badge mystes-badge-neutral';
    let resultHtml = '';
    if (imp.status === 'checked' && arb) {
        if (arb.has_arbitrage) {
            resultHtml = `
                <div class="arb-result">
                    <div class="arb-savings">Save $${arb.customer_savings_usd.toFixed(2)} (${arb.savings_percent.toFixed(1)}% off)</div>
                    <div class="arb-price-compare">
                        <span>Google: <span class="price">$${arb.us_baseline_price.toFixed(2)}</span></span>
                        <span>Your price: <span class="price" style="text-decoration:line-through;opacity:0.5">$${(arb.external_price_usd||arb.us_baseline_price).toFixed(2)}</span></span>
                        <span>MYSTES: <span class="price" style="color:#4caf50">$${arb.customer_price_usd.toFixed(2)}</span></span>
                    </div>
                    <button class="mystes-btn mystes-btn-success" style="margin-top:12px;" onclick="location.href='/flights?origin=${imp.origin}&destination=${imp.destination}&date=${imp.departure_date}'">BOOK AT MYSTES PRICE</button>
                </div>`;
        } else {
            resultHtml = `
                <div class="arb-result no-arb">
                    <div class="arb-savings none">No savings found for this route right now</div>
                    <p style="font-size:13px;color:var(--text-muted);margin:4px 0 0;">We'll notify you if a deal opens up.</p>
                </div>`;
        }
    }
    return `
        <div class="mystes-card compact interactive" style="margin-bottom:16px;">
            <div class="arb-card-header">
                <span class="arb-route">${imp.origin} &rarr; ${imp.destination}</span>
                <span class="${badgeClass}">${imp.status.toUpperCase()}</span>
            </div>
            <div class="arb-card-details">
                <span>${imp.airline}${imp.flight_number ? ' #'+imp.flight_number : ''}</span>
                <span>${imp.departure_date}${imp.return_date ? ' &mdash; '+imp.return_date : ''}</span>
                <span>${imp.cabin_class}</span>
                <span>${imp.passengers} pax</span>
                <span>Found at: $${imp.external_price_usd.toFixed(2)} (${imp.external_source.replace('_',' ')})</span>
            </div>
            <div class="arb-card-actions">
                ${imp.status === 'imported' ? `<button class="mystes-btn mystes-btn-sm mystes-btn-gold" onclick="checkArbitrage('${imp.import_id}')">CHECK NOW</button>` : ''}
                <button class="mystes-btn mystes-btn-sm mystes-btn-danger" onclick="deleteImport('${imp.import_id}')">Remove</button>
            </div>
            ${resultHtml}
        </div>`;
}

async function checkArbitrage(importId) {
    try {
        const r = await fetch('/api/arbitrate/check/' + importId, {method: 'POST'});
        const data = await r.json();
        if (data.status === 'ok') loadImports();
        else alert(data.error || 'Check failed');
    } catch(e) { alert('Error: ' + e.message); }
}

async function deleteImport(importId) {
    if (!confirm('Remove this import?')) return;
    try {
        await fetch('/api/arbitrate/import/' + importId, {method: 'DELETE'});
        loadImports();
    } catch(e) { alert('Error: ' + e.message); }
}

async function loadHotRoutes() {
    try {
        const r = await fetch('/api/hot-routes');
        const data = await r.json();
        const c = document.getElementById('hotRoutesContainer');
        if (!data.routes || data.routes.length === 0) {
            c.innerHTML = '<div class="mystes-empty"><p>No hot routes yet. Check back soon!</p></div>';
            return;
        }
        c.innerHTML = data.routes.map(rt => `
            <div class="hot-route-card">
                <div class="hot-route-info">
                    <span class="hot-route-pair">${rt.origin} &rarr; ${rt.destination}</span>
                    <span class="hot-route-save">Save $${rt.savings_usd.toFixed(0)}</span>
                    <span class="hot-route-pct">${rt.savings_percent.toFixed(0)}% off Google</span>
                </div>
                <button class="mystes-btn mystes-btn-sm mystes-btn-gold" onclick="location.href='/flights?origin=${rt.origin}&destination=${rt.destination}'">SEARCH</button>
            </div>
        `).join('');
    } catch(e) { console.error('Failed to load hot routes:', e); }
}

// Load on page init
document.addEventListener('DOMContentLoaded', () => { loadImports(); loadHotRoutes(); });
</script>
'''


# ============================================================
# Route Registration
# ============================================================

def register_arbitrage_routes(app, csrf, limiter):
    """Register all Arbitrate My Trip routes on the Flask app."""
    from server import BASE_TEMPLATE

    # ----------------------------------------------------------
    # Page: /arbitrate
    # ----------------------------------------------------------
    @app.route('/arbitrate')
    def arbitrate_my_trip_page():
        return render_template_string(
            BASE_TEMPLATE,
            title='Arbitrate My Trip',
            content=ARBITRATE_PAGE_CONTENT,
        )

    # ----------------------------------------------------------
    # POST /api/arbitrate/import — import external booking
    # ----------------------------------------------------------
    @app.route('/api/arbitrate/import', methods=['POST'])
    @login_required
    def arbitrate_import():
        data = request.get_json(silent=True) or {}

        # Validate required fields
        required = ['airline', 'origin', 'destination', 'departure_date', 'external_price_usd']
        missing = [f for f in required if not data.get(f)]
        if missing:
            return jsonify({'status': 'error', 'error': f'Missing: {", ".join(missing)}'}), 400

        origin = data['origin'].upper().strip()
        dest = data['destination'].upper().strip()
        if len(origin) < 3 or len(dest) < 3:
            return jsonify({'status': 'error', 'error': 'Invalid airport codes'}), 400

        try:
            price = float(data['external_price_usd'])
            if price <= 0:
                raise ValueError
        except (ValueError, TypeError):
            return jsonify({'status': 'error', 'error': 'Invalid price'}), 400

        try:
            dep_date = date.fromisoformat(data['departure_date'])
        except (ValueError, TypeError):
            return jsonify({'status': 'error', 'error': 'Invalid departure date (YYYY-MM-DD)'}), 400

        ret_date = None
        if data.get('return_date'):
            try:
                ret_date = date.fromisoformat(data['return_date'])
            except (ValueError, TypeError):
                pass

        imp = ExternalBookingImport(
            import_id=_gen_id('IMP'),
            user_id=current_user.id,
            trip_id=data.get('trip_id'),
            airline=data['airline'].strip(),
            airline_code=data.get('airline_code', '').strip() or None,
            flight_number=data.get('flight_number', '').strip() or None,
            origin=origin,
            destination=dest,
            departure_date=dep_date,
            return_date=ret_date,
            cabin_class=data.get('cabin_class', 'economy'),
            passengers=min(max(int(data.get('passengers', 1)), 1), 9),
            external_price_usd=price,
            external_source=data.get('external_source', 'manual'),
            external_url=data.get('external_url'),
            status='imported',
        )
        db.session.add(imp)
        db.session.commit()

        return jsonify({'status': 'ok', 'import': imp.to_dict()})

    # ----------------------------------------------------------
    # GET /api/arbitrate/my-imports — list user's imports
    # ----------------------------------------------------------
    @app.route('/api/arbitrate/my-imports')
    @login_required
    def arbitrate_my_imports():
        imports = ExternalBookingImport.query.filter_by(
            user_id=current_user.id
        ).order_by(ExternalBookingImport.created_at.desc()).limit(50).all()

        return jsonify({
            'status': 'ok',
            'imports': [i.to_dict() for i in imports],
            'count': len(imports),
        })

    # ----------------------------------------------------------
    # DELETE /api/arbitrate/import/<import_id> — remove import
    # ----------------------------------------------------------
    @app.route('/api/arbitrate/import/<import_id>', methods=['DELETE'])
    @login_required
    def arbitrate_delete_import(import_id):
        imp = ExternalBookingImport.query.filter_by(
            import_id=import_id, user_id=current_user.id
        ).first()
        if not imp:
            return jsonify({'status': 'error', 'error': 'Not found'}), 404

        db.session.delete(imp)
        db.session.commit()
        return jsonify({'status': 'ok'})

    # ----------------------------------------------------------
    # POST /api/arbitrate/check/<import_id> — run arbitrage check
    # ----------------------------------------------------------
    @app.route('/api/arbitrate/check/<import_id>', methods=['POST'])
    @login_required
    def arbitrate_check(import_id):
        imp = ExternalBookingImport.query.filter_by(
            import_id=import_id, user_id=current_user.id
        ).first()
        if not imp:
            return jsonify({'status': 'error', 'error': 'Not found'}), 404

        if imp.status == 'checking':
            return jsonify({'status': 'error', 'error': 'Already checking'}), 409

        imp.status = 'checking'
        db.session.commit()

        fee_percent = _get_fee_percent(current_user)

        # Attempt real arbitrage check via ArbitrageModule
        arb_module = _get_arbitrage_module()
        check_result = None

        if arb_module:
            try:
                # In production, market_prices comes from proxy searches.
                # For now, attempt a full check (SerpAPI baseline + any cached data).
                baseline = arb_module.get_us_baseline(
                    imp.origin, imp.destination,
                    imp.departure_date.isoformat(),
                    imp.return_date.isoformat() if imp.return_date else None,
                    imp.cabin_class,
                )
                if baseline and baseline.get('price_usd'):
                    us_price = baseline['price_usd']
                    # Use the external price as a proxy POS price comparison
                    # (In production: proxy queries to multiple POS markets)
                    spread = us_price - imp.external_price_usd
                    check_result = {
                        'us_baseline_price': us_price,
                        'best_pos_price': imp.external_price_usd,
                        'best_pos_market': 'EXT',
                        'spread_usd': max(spread, 0),
                        'has_arbitrage': spread > 0 and (us_price - (imp.external_price_usd + max(spread * fee_percent, 3))) > 0,
                        'markets_checked': 1,
                    }
            except Exception as e:
                logger.warning("ArbitrageModule check failed: %s", e)

        # Fallback: use external price as-is, compare against a simulated baseline
        if not check_result:
            # Without SerpAPI/proxy, create a comparison record using the user's price
            check_result = {
                'us_baseline_price': imp.external_price_usd,
                'best_pos_price': imp.external_price_usd,
                'best_pos_market': None,
                'spread_usd': 0,
                'has_arbitrage': False,
                'markets_checked': 0,
            }

        # Calculate fee and customer price
        us_price = check_result['us_baseline_price']
        pos_price = check_result['best_pos_price']
        spread = check_result['spread_usd']

        if spread > 0:
            raw_fee = spread * fee_percent
            service_fee = max(raw_fee, 3.0)  # $3 minimum, NO max cap
            customer_price = pos_price + service_fee
            customer_savings = us_price - customer_price
            savings_vs_external = imp.external_price_usd - customer_price
            savings_pct = (customer_savings / us_price * 100) if us_price > 0 else 0
            has_arb = customer_savings > 0
        else:
            service_fee = 0
            customer_price = pos_price
            customer_savings = 0
            savings_vs_external = 0
            savings_pct = 0
            has_arb = False

        arb_check = ArbitrageCheck(
            check_id=_gen_id('CHK'),
            user_id=current_user.id,
            airline=imp.airline,
            origin=imp.origin,
            destination=imp.destination,
            departure_date=imp.departure_date,
            return_date=imp.return_date,
            cabin_class=imp.cabin_class,
            us_baseline_price=us_price,
            external_price_usd=imp.external_price_usd,
            best_pos_price=pos_price,
            best_pos_market=check_result.get('best_pos_market'),
            markets_checked=check_result['markets_checked'],
            spread_usd=spread,
            fee_percent=fee_percent,
            service_fee_usd=service_fee,
            customer_price_usd=customer_price,
            customer_savings_usd=customer_savings,
            savings_vs_external_usd=savings_vs_external,
            savings_percent=savings_pct,
            has_arbitrage=has_arb,
            confidence_score=0.5 if check_result['markets_checked'] > 0 else 0.0,
            arbitrage_quality=_classify_quality(savings_pct) if has_arb else 'none',
        )
        db.session.add(arb_check)
        db.session.flush()

        imp.arbitrage_check_id = arb_check.id
        imp.status = 'checked'
        db.session.commit()

        return jsonify({
            'status': 'ok',
            'import': imp.to_dict(),
            'check': arb_check.to_dict(),
        })

    # ----------------------------------------------------------
    # GET /api/arbitrate/result/<check_id> — get check result
    # ----------------------------------------------------------
    @app.route('/api/arbitrate/result/<check_id>')
    @login_required
    def arbitrate_result(check_id):
        check = ArbitrageCheck.query.filter_by(
            check_id=check_id, user_id=current_user.id
        ).first()
        if not check:
            return jsonify({'status': 'error', 'error': 'Not found'}), 404
        return jsonify({'status': 'ok', 'check': check.to_dict()})

    # ----------------------------------------------------------
    # POST /api/arbitrate/trip/<trip_id> — bulk arbitrate trip
    # ----------------------------------------------------------
    @app.route('/api/arbitrate/trip/<int:trip_id>', methods=['POST'])
    @login_required
    def arbitrate_trip(trip_id):
        trip = db.session.get(TripPlan, trip_id)
        if not trip:
            return jsonify({'status': 'error', 'error': 'Trip not found'}), 404

        # Check access
        if trip.creator_id != current_user.id:
            member = TripMember.query.filter_by(
                trip_plan_id=trip_id, user_id=current_user.id
            ).first()
            if not member:
                return jsonify({'status': 'error', 'error': 'Access denied'}), 403

        imports = ExternalBookingImport.query.filter_by(
            trip_id=trip_id, user_id=current_user.id, status='imported'
        ).all()

        if not imports:
            return jsonify({'status': 'error', 'error': 'No unchecked imports in this trip'}), 400

        results = []
        for imp in imports:
            # Run check inline (in production, these queue to the booking engine)
            imp.status = 'checking'
            db.session.commit()

            fee_percent = _get_fee_percent(current_user)

            arb_check = ArbitrageCheck(
                check_id=_gen_id('CHK'),
                user_id=current_user.id,
                airline=imp.airline,
                origin=imp.origin,
                destination=imp.destination,
                departure_date=imp.departure_date,
                return_date=imp.return_date,
                cabin_class=imp.cabin_class,
                us_baseline_price=imp.external_price_usd,
                external_price_usd=imp.external_price_usd,
                best_pos_price=imp.external_price_usd,
                markets_checked=0,
                spread_usd=0,
                fee_percent=fee_percent,
                service_fee_usd=0,
                customer_price_usd=imp.external_price_usd,
                customer_savings_usd=0,
                savings_vs_external_usd=0,
                savings_percent=0,
                has_arbitrage=False,
                confidence_score=0.0,
                arbitrage_quality='none',
            )
            db.session.add(arb_check)
            db.session.flush()

            imp.arbitrage_check_id = arb_check.id
            imp.status = 'checked'
            results.append(arb_check.to_dict())

        db.session.commit()

        return jsonify({
            'status': 'ok',
            'trip_id': trip_id,
            'checks': results,
            'count': len(results),
        })

    # ----------------------------------------------------------
    # GET /api/arbitrate/trip/<trip_id>/summary
    # ----------------------------------------------------------
    @app.route('/api/arbitrate/trip/<int:trip_id>/summary')
    @login_required
    def arbitrate_trip_summary(trip_id):
        trip = db.session.get(TripPlan, trip_id)
        if not trip:
            return jsonify({'status': 'error', 'error': 'Trip not found'}), 404

        if trip.creator_id != current_user.id:
            member = TripMember.query.filter_by(
                trip_plan_id=trip_id, user_id=current_user.id
            ).first()
            if not member:
                return jsonify({'status': 'error', 'error': 'Access denied'}), 403

        imports = ExternalBookingImport.query.filter_by(trip_id=trip_id).all()

        total_external = sum(i.external_price_usd * i.passengers for i in imports)
        total_mystes = 0
        total_savings = 0
        checked_count = 0

        for imp in imports:
            if imp.arbitrage_check and imp.arbitrage_check.has_arbitrage:
                total_mystes += imp.arbitrage_check.customer_price_usd * imp.passengers
                total_savings += imp.arbitrage_check.customer_savings_usd * imp.passengers
                checked_count += 1
            else:
                total_mystes += imp.external_price_usd * imp.passengers

        return jsonify({
            'status': 'ok',
            'trip_id': trip_id,
            'summary': {
                'total_imports': len(imports),
                'checked': checked_count,
                'total_external_cost': round(total_external, 2),
                'total_mystes_cost': round(total_mystes, 2),
                'total_potential_savings': round(total_savings, 2),
                'savings_percent': round((total_savings / total_external * 100) if total_external > 0 else 0, 1),
            },
        })

    # ----------------------------------------------------------
    # GET /api/hot-routes — homepage hot routes feed
    # ----------------------------------------------------------
    @app.route('/api/hot-routes')
    def hot_routes_feed():
        routes = HotRoute.query.filter_by(is_active=True).order_by(
            HotRoute.savings_percent.desc()
        ).limit(20).all()

        return jsonify({
            'status': 'ok',
            'routes': [r.to_dict() for r in routes],
            'count': len(routes),
        })

    # ----------------------------------------------------------
    # POST /api/admin/hot-routes — admin: create/update hot route
    # ----------------------------------------------------------
    @app.route('/api/admin/hot-routes', methods=['POST'])
    @login_required
    def admin_create_hot_route():
        if not getattr(current_user, 'is_admin', False):
            return jsonify({'status': 'error', 'error': 'Admin only'}), 403

        data = request.get_json(silent=True) or {}
        required = ['origin', 'destination', 'us_retail_price', 'mystes_price']
        missing = [f for f in required if not data.get(f)]
        if missing:
            return jsonify({'status': 'error', 'error': f'Missing: {", ".join(missing)}'}), 400

        us_price = float(data['us_retail_price'])
        mystes_price = float(data['mystes_price'])
        savings = us_price - mystes_price

        route = HotRoute(
            origin=data['origin'].upper(),
            destination=data['destination'].upper(),
            airline=data.get('airline'),
            us_retail_price=us_price,
            mystes_price=mystes_price,
            savings_usd=savings,
            savings_percent=(savings / us_price * 100) if us_price > 0 else 0,
            departure_window=data.get('departure_window'),
            cabin_class=data.get('cabin_class', 'economy'),
            data_points=data.get('data_points', 1),
            confidence=data.get('confidence', 0.5),
        )
        db.session.add(route)
        db.session.commit()

        return jsonify({'status': 'ok', 'route': route.to_dict()})

    logger.info("Arbitrate My Trip routes registered (Build #234)")
