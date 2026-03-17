"""
Phase 2/3 — XRPL, Escrow, Wallet & Crypto Payment Routes
Extracted from server.py (Build #136) to slim Phase 1 OTA.

All code preserved intact. Re-enable by adding to server.py:
    from routes_xrpl import register_xrpl_routes
    register_xrpl_routes(app, csrf, limiter)

Features gated behind feature flags:
  - xrpl_escrow: Escrow payment routes
  - xrpl_direct_payments: Direct XRP/RLUSD verification
  - Wallet/card management (P2P helper infrastructure)
"""

import logging
from datetime import datetime
from functools import wraps

from flask import request, jsonify, render_template_string, redirect, url_for, flash
from flask_login import login_required, current_user

from models import db, Deal, Payment, Booking, Escrow, UserWallet, UserCard

logger = logging.getLogger(__name__)


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
                            {% if w.is_primary %}<span style="background: #7c3aed; color: white; padding: 2px 8px; border-radius: 10px; font-size: 11px; margin-left: 8px;">Primary</span>{% endif %}
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
                            {% if c.is_primary %}<span style="background: #7c3aed; color: white; padding: 2px 8px; border-radius: 10px; font-size: 11px; margin-left: 8px;">Primary</span>{% endif %}
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
                With a verified XRPL wallet, you get universal access via MYSTES virtual card to ALL zones.
            </p>
        </div>

        <hr style="border: none; border-top: 1px solid #eee; margin: 25px 0;">

        <!-- Payment Ramp Networks (Build #86) -->
        <div style="margin-bottom: 30px;">
            <h2 style="color: #1a1a2e; margin-bottom: 5px; font-size: 20px;">Buy USDC / XRP</h2>
            <p style="color: #666; font-size: 14px; margin-bottom: 15px;">
                On-ramp to crypto through verified providers. Funds go to your connected XRPL wallet.
                Or bring your own payment method &mdash; MYSTES doesn't require you to use these.
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
                MYSTES can convert your crypto to a virtual Visa card for any merchant purchase &mdash; arbitrage deals or free browsing.
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
                            zone.status === 'partial' ? '#7c3aed' : '#c62828';
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
                if (ramp.is_user_default) badge = '<span style="background:#7c3aed;color:white;padding:2px 8px;border-radius:10px;font-size:10px;margin-left:6px;">Default</span>';
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
                            'style="display:block;text-align:center;padding:8px;background:#7c3aed;color:white;border-radius:6px;text-decoration:none;font-size:13px;font-weight:600;">' +
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


# --- ADMIN WALLET TEMPLATE ---
# Note: ADMIN_NAV is concatenated at registration time via a helper,
# since it's defined in server.py. We store the body here and prepend ADMIN_NAV
# inside register_xrpl_routes().

_ADMIN_WALLET_BODY = """
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


def register_xrpl_routes(app, csrf, limiter):
    """Register all Phase 2/3 XRPL routes on the Flask app."""
    from server import BASE_TEMPLATE, is_feature_enabled, ADMIN_NAV, trigger_booking_fulfillment, admin_required
    from main import XRPL_CONFIG, get_xrp_price
    from payments import verify_payment, PAYMENT_CONFIG

    # Build ADMIN_WALLET_CONTENT with ADMIN_NAV prepended (matches server.py pattern)
    ADMIN_WALLET_CONTENT = """
""" + ADMIN_NAV + _ADMIN_WALLET_BODY

    # --- ESCROW ROUTES ---

    @app.route("/api/escrow/create", methods=["POST"])
    @csrf.exempt
    @limiter.limit("10 per hour")
    def api_escrow_create():
        """Create an escrow payment for trustless booking. (Phase 2)"""
        if not is_feature_enabled('xrpl_escrow'):
            return jsonify({"error": "XRPL escrow payments are not available in the current release", "phase": 2}), 410

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
        """Confirm an escrow was created on-chain. (Phase 2)"""
        if not is_feature_enabled('xrpl_escrow'):
            return jsonify({"error": "XRPL escrow payments are not available in the current release", "phase": 2}), 410

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
        """Release escrow after successful booking. (Phase 2)"""
        if not is_feature_enabled('xrpl_escrow'):
            return jsonify({"error": "XRPL escrow payments are not available in the current release", "phase": 2}), 410

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
        """Cancel escrow and refund customer. (Phase 2)"""
        if not is_feature_enabled('xrpl_escrow'):
            return jsonify({"error": "XRPL escrow payments are not available in the current release", "phase": 2}), 410

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
        """Get status of an escrow payment. (Phase 2)"""
        if not is_feature_enabled('xrpl_escrow'):
            return jsonify({"error": "XRPL escrow payments are not available in the current release", "phase": 2}), 410

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

    # --- WALLET & CARD ROUTES ---

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

    # --- XRP/RLUSD VERIFY ROUTES ---

    @app.route("/pay/verify/xrp", methods=["POST"])
    @login_required
    def verify_xrp_payment_route():
        """Verify XRP payment. (Phase 2)"""
        if not is_feature_enabled('xrpl_direct_payments'):
            return jsonify({"error": "Direct XRP payments are not available in the current release", "phase": 2}), 410

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
        """Verify RLUSD payment. (Phase 2)"""
        if not is_feature_enabled('xrpl_direct_payments'):
            return jsonify({"error": "Direct RLUSD payments are not available in the current release", "phase": 2}), 410

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

    # --- ADMIN WALLET ROUTE ---

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
