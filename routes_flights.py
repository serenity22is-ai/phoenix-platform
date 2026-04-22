"""
MYSTES Flights Vertical — Route Module (Build #167)

Extracted from homepage HOME_HERO to /flights.
Search UI with glass morphism design, trip type toggle, passenger selectors.
API backend stays in server.py (/api/search).

Includes:
- /flights — search page
- /flight-card/<deal_id> — shareable flight card (public, no login)
- /flight-card/<deal_id>/image — OG image card (for social previews)

Registration: register_flight_routes(app, csrf, limiter)
"""

import logging
from flask import render_template_string, request, abort
from flask_login import current_user

logger = logging.getLogger(__name__)


# ============================================================
# Flights Search Page Content
# ============================================================

FLIGHTS_SEARCH_CONTENT = '''
<style>
    .search-page { max-width: 960px; margin: 0 auto; padding: 40px 16px 60px; }

    /* Trip type toggle */
    .sf-trip-toggle { display: flex; gap: 0; margin-bottom: 18px; justify-content: center; }
    .sf-trip-btn {
        padding: 8px 20px; border: 1px solid rgba(255,255,255,0.15); background: transparent;
        color: rgba(255,255,255,0.6); font-family: var(--font-sans); font-size: 13px; font-weight: 600;
        cursor: pointer; transition: all 0.2s; letter-spacing: 0.5px;
    }
    .sf-trip-btn:first-child { border-radius: 8px 0 0 8px; }
    .sf-trip-btn:last-child { border-radius: 0 8px 8px 0; }
    .sf-trip-btn.active { background: rgba(124,58,237,0.25); border-color: rgba(124,58,237,0.5); color: #fff; }

    .sf-row { display: flex; gap: 12px; margin-bottom: 14px; flex-wrap: wrap; }
    .sf-field { flex: 1; min-width: 140px; }
    .sf-pax { display: flex; gap: 12px; flex-wrap: wrap; }
    .sf-pax .sf-field { min-width: 100px; flex: 0 1 auto; }

    /* Results */
    .search-results { max-width: 900px; margin: 0 auto; }
    .sr-loading { text-align: center; padding: 60px 20px; display: none; }
    .sr-loading p { color: var(--text-muted); font-size: 14px; margin-top: 16px; }
    .sr-error { text-align: center; padding: 40px 20px; color: #f87171; display: none; }
    .sr-summary { text-align: center; padding: 16px 0 24px; color: var(--text-muted); font-size: 14px; display: none; }

    /* Toolbar */
    .sr-toolbar {
        display: none; padding: 12px 16px; margin-bottom: 14px; gap: 14px; flex-wrap: wrap; align-items: center;
        background: var(--glass-bg); border: 1px solid var(--glass-border); border-radius: var(--radius-lg);
    }
    .sr-toolbar label { font-size: 12px; color: var(--text-muted); font-weight: 600; letter-spacing: 0.5px; text-transform: uppercase; }
    .sr-toolbar select { padding: 6px 10px; font-size: 13px; }

    /* Flight cards */
    .flight-card {
        background: var(--glass-bg-light); border: 1px solid var(--glass-border);
        border-radius: var(--radius-lg); padding: 20px 24px; margin-bottom: 14px;
        display: grid; grid-template-columns: 140px 1fr 160px; align-items: center; gap: 20px;
        transition: border-color 0.2s, background 0.2s; cursor: pointer;
    }
    .flight-card:hover { border-color: var(--glass-border-hover); background: rgba(124,58,237,0.06); }
    .fc-airline { min-width: 120px; }
    .fc-airline-name { font-weight: 700; color: var(--text-bright); font-size: 15px; }
    .fc-flight-num { font-size: 12px; color: var(--text-muted); margin-top: 2px; }
    .fc-route { display: flex; align-items: center; gap: 16px; justify-content: center; }
    .fc-endpoint { text-align: center; }
    .fc-time { font-size: 20px; font-weight: 700; color: var(--text-bright); letter-spacing: 0.5px; }
    .fc-code { font-size: 12px; color: var(--text-muted); text-transform: uppercase; margin-top: 2px; letter-spacing: 1px; }
    .fc-arrow { display: flex; flex-direction: column; align-items: center; gap: 4px; min-width: 80px; }
    .fc-line { width: 100%; height: 1px; background: rgba(255,255,255,0.15); }
    .fc-duration { font-size: 11px; color: var(--text-muted); white-space: nowrap; }
    .fc-stops { font-size: 10px; color: rgba(124,58,237,0.8); font-weight: 600; }
    .fc-price-section { text-align: right; min-width: 140px; }
    .fc-price { font-size: 24px; font-weight: 800; color: var(--text-bright); }
    .fc-savings { font-size: 12px; color: #34d399; font-weight: 600; margin-top: 2px; }
    .fc-google-price { font-size: 12px; color: var(--text-muted); text-decoration: line-through; }
    .no-results { text-align: center; padding: 60px 20px; color: var(--text-muted); display: none; }

    @media (max-width: 768px) {
        .sf-row { flex-direction: column; gap: 10px; }
        .sf-field { min-width: 100%; }
        .sf-pax { flex-direction: row; }
        .sf-pax .sf-field { min-width: 80px; flex: 1; }
        .flight-card { grid-template-columns: 1fr; gap: 12px; padding: 16px; }
        .fc-price-section { text-align: left; width: 100%; display: flex; justify-content: space-between; align-items: center; }
    }
</style>

<script>
var tripType = "oneway";
function setTripType(btn, type) {
    tripType = type;
    var btns = document.getElementsByClassName("sf-trip-btn");
    for (var i = 0; i < btns.length; i++) { btns[i].className = "sf-trip-btn"; }
    btn.className = "sf-trip-btn active";
    var wrap = document.getElementById("sfReturnWrap");
    if (wrap) wrap.style.display = (type === "roundtrip") ? "" : "none";
}
</script>

<section class="search-page">
    <div class="mystes-page-header">
        <h1>Flights</h1>
        <p>Search 102 markets for the cheapest flights</p>
    </div>

    <div class="mystes-card" style="max-width:900px;margin:0 auto 32px;">
        <div class="sf-trip-toggle" id="sfTripToggle">
            <button type="button" class="sf-trip-btn active" data-trip="oneway" onclick="setTripType(this,'oneway')">One Way</button>
            <button type="button" class="sf-trip-btn" data-trip="roundtrip" onclick="setTripType(this,'roundtrip')">Round Trip</button>
        </div>

        <div class="sf-row">
            <div class="sf-field">
                <label class="mystes-label">From</label>
                <input type="text" id="sfOrigin" class="mystes-input" placeholder="JFK, LAX, ORD..." maxlength="3" style="text-transform:uppercase;">
            </div>
            <div class="sf-field">
                <label class="mystes-label">To</label>
                <input type="text" id="sfDest" class="mystes-input" placeholder="LHR, NRT, CDG..." maxlength="3" style="text-transform:uppercase;">
            </div>
            <div class="sf-field">
                <label class="mystes-label">Departure</label>
                <input type="date" id="sfDate" class="mystes-input">
            </div>
            <div class="sf-field" id="sfReturnWrap" style="display:none;">
                <label class="mystes-label">Return</label>
                <input type="date" id="sfReturn" class="mystes-input">
            </div>
        </div>

        <div class="sf-row sf-pax">
            <div class="sf-field">
                <label class="mystes-label">Adults</label>
                <select id="sfAdults" class="mystes-select">
                    <option value="1" selected>1</option>
                    <option value="2">2</option>
                    <option value="3">3</option>
                    <option value="4">4</option>
                    <option value="5">5</option>
                    <option value="6">6</option>
                </select>
            </div>
            <div class="sf-field">
                <label class="mystes-label">Children</label>
                <select id="sfChildren" class="mystes-select">
                    <option value="0" selected>0</option>
                    <option value="1">1</option>
                    <option value="2">2</option>
                    <option value="3">3</option>
                    <option value="4">4</option>
                </select>
            </div>
            <div class="sf-field">
                <label class="mystes-label">Infants</label>
                <select id="sfInfants" class="mystes-select">
                    <option value="0" selected>0</option>
                    <option value="1">1</option>
                    <option value="2">2</option>
                </select>
            </div>
            <div class="sf-field">
                <label class="mystes-label">Cabin</label>
                <select id="sfCabin" class="mystes-select">
                    <option value="economy" selected>Economy</option>
                    <option value="premium_economy">Premium Economy</option>
                    <option value="business">Business</option>
                    <option value="first">First</option>
                </select>
            </div>
        </div>

        <div style="display:flex;justify-content:center;margin-top:20px;">
            <button class="mystes-btn mystes-btn-primary mystes-btn-lg" id="sfSearchBtn" onclick="searchFlights()" style="letter-spacing:3px;text-transform:uppercase;">Search Flights</button>
        </div>
    </div>

    <div class="search-results">
        <div class="sr-loading" id="srLoading">
            <div class="mystes-spinner" style="margin:0 auto;"></div>
            <p>Searching 102 markets for the best price...</p>
        </div>
        <div class="sr-error" id="srError"></div>
        <div class="sr-summary" id="srSummary"></div>
        <div id="srToolbar" class="sr-toolbar">
            <div class="flex-center gap-sm">
                <label>Sort:</label>
                <select id="sortSelect" onchange="sortAndFilter()" class="mystes-select" style="width:auto;padding:6px 10px;">
                    <option value="price_asc">Price (low to high)</option>
                    <option value="price_desc">Price (high to low)</option>
                    <option value="duration">Duration (shortest)</option>
                    <option value="departure">Departure (earliest)</option>
                </select>
            </div>
            <div class="flex-center gap-sm">
                <label>Stops:</label>
                <select id="stopsFilter" onchange="sortAndFilter()" class="mystes-select" style="width:auto;padding:6px 10px;">
                    <option value="any">Any</option>
                    <option value="0">Nonstop only</option>
                    <option value="1">1 stop max</option>
                </select>
            </div>
            <div class="flex-center gap-sm">
                <label>Airline:</label>
                <select id="airlineFilter" onchange="sortAndFilter()" class="mystes-select" style="width:auto;padding:6px 10px;">
                    <option value="all">All Airlines</option>
                </select>
            </div>
            <div id="srFilterCount" style="font-size:12px;color:var(--text-muted);margin-left:auto;"></div>
        </div>
        <div id="srCards"></div>
        <div class="no-results" id="srNoResults">No flights found. Try different dates or airports.</div>
    </div>
</section>

<script>
window._feePercent = {{ fee_pct }};

// Event delegation backup — catches clicks even if onclick attrs fail
(function() {
    var toggle = document.getElementById("sfTripToggle");
    if (toggle) {
        toggle.addEventListener("click", function(e) {
            var btn = e.target;
            if (btn && btn.getAttribute && btn.getAttribute("data-trip")) {
                setTripType(btn, btn.getAttribute("data-trip"));
            }
        });
    }
})();

// Set default departure date to 7 days out
(function() {
    var d = new Date(); d.setDate(d.getDate() + 7);
    var iso = d.toISOString().split("T")[0];
    document.getElementById("sfDate").value = iso;
    document.getElementById("sfDate").min = new Date().toISOString().split("T")[0];
    document.getElementById("sfReturn").min = new Date().toISOString().split("T")[0];
})();

async function searchFlights() {
    var origin = document.getElementById("sfOrigin").value.trim().toUpperCase();
    var dest = document.getElementById("sfDest").value.trim().toUpperCase();
    var date = document.getElementById("sfDate").value;
    var returnDate = tripType === "roundtrip" ? document.getElementById("sfReturn").value : null;
    var adults = parseInt(document.getElementById("sfAdults").value);
    var children = parseInt(document.getElementById("sfChildren").value);
    var infants = parseInt(document.getElementById("sfInfants").value);
    var cabin = document.getElementById("sfCabin").value;

    if (!origin || origin.length < 3) { document.getElementById("sfOrigin").focus(); return; }
    if (!dest || dest.length < 3) { document.getElementById("sfDest").focus(); return; }
    if (!date) { document.getElementById("sfDate").focus(); return; }
    if (tripType === "roundtrip" && !returnDate) { document.getElementById("sfReturn").focus(); return; }

    var btn = document.getElementById("sfSearchBtn");
    btn.disabled = true;
    btn.textContent = "Searching...";

    document.getElementById("srLoading").style.display = "block";
    document.getElementById("srError").style.display = "none";
    document.getElementById("srSummary").style.display = "none";
    document.getElementById("srCards").innerHTML = "";
    document.getElementById("srNoResults").style.display = "none";

    try {
        var body = { origin: origin, destination: dest, date: date, cabin_class: cabin, adults: adults, children: children, infants: infants };
        if (returnDate) body.return_date = returnDate;

        var resp = await fetch("/api/search", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "same-origin",
            body: JSON.stringify(body)
        });

        document.getElementById("srLoading").style.display = "none";

        if (!resp.ok) {
            var err = await resp.json().catch(function() { return {}; });
            document.getElementById("srError").textContent = err.error || "Search failed. Please try again.";
            document.getElementById("srError").style.display = "block";
            btn.disabled = false;
            btn.textContent = "Search Flights";
            return;
        }

        var data = await resp.json();
        var flights = data.flights || data.all_flights || [];

        if (!flights.length) {
            document.getElementById("srNoResults").style.display = "block";
            btn.disabled = false;
            btn.textContent = "Search Flights";
            return;
        }

        // Summary
        var summary = flights.length + " flights found";
        var proxy = data.proxy_results || {};
        if (proxy.cheapest_price_usd) {
            summary += " — best price: $" + parseFloat(proxy.cheapest_price_usd).toFixed(0);
        }
        document.getElementById("srSummary").innerHTML = summary +
            ' <button onclick="toggleAlertForm()" style="margin-left:12px;background:#7c3aed;color:white;border:none;padding:5px 14px;border-radius:6px;font-size:12px;cursor:pointer;font-weight:600;">Set Price Alert</button>';
        document.getElementById("srSummary").style.display = "block";

        // Store search params for alert creation + sort/filter
        window._lastSearch = {origin: origin, destination: dest, date: date};
        window._allFlights = flights;
        window._searchOrigin = origin;
        window._searchDest = dest;

        // Calculate MYSTES prices (wholesale + platform fee) — customer never sees wholesale
        var feePct = window._feePercent || 0.50;
        flights.forEach(function(f) {
            var wp = f.price || f.cheapest_price || 0;
            var hp = (f.deal || {}).home_price || f.google_price || 0;
            var fee = 0;
            if (hp > wp && hp > 0) {
                fee = (hp - wp) * feePct;
                if (fee > 0 && fee < 3) fee = 3;
            }
            f._mystesPrice = wp + fee;
            f._customerSavings = hp > f._mystesPrice ? hp - f._mystesPrice : 0;
            f._savingsPct = hp > 0 && f._customerSavings > 0 ? (f._customerSavings / hp * 100) : 0;
        });

        // Populate airline filter
        var airlines = {};
        flights.forEach(function(f) { var a = f.airline || "Unknown"; airlines[a] = true; });
        var airlineSelect = document.getElementById("airlineFilter");
        airlineSelect.innerHTML = '<option value="all">All Airlines</option>';
        Object.keys(airlines).sort().forEach(function(a) {
            airlineSelect.innerHTML += '<option value="' + esc(a) + '">' + esc(a) + '</option>';
        });

        // Show toolbar
        document.getElementById("srToolbar").style.display = "flex";
        document.getElementById("srToolbar").classList.add("visible");

        // Render with sort/filter
        renderFlightCards(flights);

    } catch(e) {
        document.getElementById("srLoading").style.display = "none";
        document.getElementById("srError").textContent = "Connection error. Please try again.";
        document.getElementById("srError").style.display = "block";
    }

    btn.disabled = false;
    btn.textContent = "Search Flights";
}

function esc(s) { return s ? String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;") : ""; }

// Allow Enter key to submit
document.addEventListener("keydown", function(e) {
    if (e.key === "Enter" && (e.target.id === "sfOrigin" || e.target.id === "sfDest")) searchFlights();
});

function fmtTime(t) {
    if (!t) return "--:--";
    if (t.includes("T")) t = t.split("T")[1];
    return t.substring(0, 5);
}

function parseDuration(d) {
    if (!d) return 9999;
    var h = 0, m = 0;
    var hm = d.match(/(\\d+)h/); if (hm) h = parseInt(hm[1]);
    var mm = d.match(/(\\d+)m/); if (mm) m = parseInt(mm[1]);
    return h * 60 + m;
}

function renderFlightCards(flights) {
    var origin = window._searchOrigin || "";
    var dest = window._searchDest || "";
    var html = "";
    flights.forEach(function(f) {
        var airline = f.airline || "Unknown";
        var flightNum = f.flight_number || "";
        var depTime = f.departure_time || "";
        var arrTime = f.arrival_time || "";
        var duration = f.duration || "";
        var stops = f.stops || 0;
        var stopsText = stops === 0 ? "Nonstop" : stops + " stop" + (stops > 1 ? "s" : "");
        var wholesalePrice = f.price || f.cheapest_price || 0;
        var deal = f.deal || {};
        var homePrice = deal.home_price || f.google_price || 0;
        var mystesPrice = f._mystesPrice || wholesalePrice;
        var customerSavings = f._customerSavings || 0;
        var savingsPct = f._savingsPct || 0;
        var date = (window._lastSearch || {}).date || "";

        var rawOffer = f.raw_offer || null;
        var picassoGds = f.picasso_gds || null;
        var fareId = f.fare_id || null;
        var fareSearchId = f.fare_search_id || null;
        var offerId = f.offer_id || null;
        var fd = JSON.stringify({origin: origin, destination: dest, date: date, price: wholesalePrice, title: airline + " " + flightNum, airline: airline, flight_number: flightNum, departure_time: depTime, arrival_time: arrTime, stops: stops, home_price: homePrice, arbitrage_price: wholesalePrice, savings: customerSavings, savings_pct: savingsPct, raw_offer: rawOffer, picasso_gds: picassoGds, fare_id: fareId, fare_search_id: fareSearchId, offer_id: offerId, source: f.source || null});
        html += "<div class=\\"flight-card\\" data-flight='" + fd.replace(/'/g, "&#39;") + "' onclick=\\"bookThisFlight(this)\\">";
        html += "<div class=\\"fc-airline\\"><div class=\\"fc-airline-name\\">" + esc(airline) + "</div>";
        if (flightNum) html += "<div class=\\"fc-flight-num\\">" + esc(flightNum) + "</div>";
        html += "</div>";

        var depDisplay = fmtTime(depTime);
        var arrDisplay = fmtTime(arrTime);

        html += "<div class=\\"fc-route\\">";
        html += "<div class=\\"fc-endpoint\\"><div class=\\"fc-time\\">" + esc(depDisplay) + "</div><div class=\\"fc-code\\">" + esc(origin) + "</div></div>";
        html += "<div class=\\"fc-arrow\\"><div class=\\"fc-line\\"></div><div class=\\"fc-duration\\">" + esc(duration) + "</div><div class=\\"fc-stops\\">" + stopsText + "</div></div>";
        html += "<div class=\\"fc-endpoint\\"><div class=\\"fc-time\\">" + esc(arrDisplay) + "</div><div class=\\"fc-code\\">" + esc(dest) + "</div></div>";
        html += "</div>";

        html += "<div class=\\"fc-price-section\\">";
        html += "<div class=\\"fc-price\\">$" + parseFloat(mystesPrice).toFixed(0) + "</div>";
        if (homePrice && customerSavings > 0) {
            html += "<div class=\\"fc-google-price\\">Google: $" + parseFloat(homePrice).toFixed(0) + "</div>";
            html += "<div class=\\"fc-savings\\">Save $" + parseFloat(customerSavings).toFixed(0) + " (" + parseFloat(savingsPct).toFixed(0) + "%)</div>";
        }
        html += "</div>";
        html += "<div class=\\"fc-actions\\" style=\\"display:flex;gap:6px;margin-top:8px;\\">";
        html += "<button class=\\"fc-compare-btn\\" onclick=\\"event.stopPropagation();comparePrices(this,"+fd+")\\" style=\\"background:transparent;border:1px solid rgba(255,255,255,0.2);color:#aaa;padding:4px 10px;border-radius:6px;cursor:pointer;font-size:11px;\\">Compare</button>";
        html += "<button class=\\"fc-save-btn\\" onclick=\\"event.stopPropagation();saveToFavorites("+fd+")\\" style=\\"background:transparent;border:1px solid rgba(255,255,255,0.2);color:#aaa;padding:4px 10px;border-radius:6px;cursor:pointer;font-size:11px;\\">&#9825; Save</button>";
        if (fareSearchId && fareId) {
            html += "<button onclick=\\"event.stopPropagation();showFareRules('" + fareSearchId + "','" + fareId + "')\\" style=\\"background:transparent;border:1px solid rgba(255,255,255,0.2);color:#aaa;padding:4px 10px;border-radius:6px;cursor:pointer;font-size:11px;\\">Fare Rules</button>";
        }
        html += "</div>";
        html += "</div>";
    });
    document.getElementById("srCards").innerHTML = html;
    document.getElementById("srFilterCount").textContent = flights.length + " of " + (window._allFlights || []).length + " shown";
}

function sortAndFilter() {
    var flights = (window._allFlights || []).slice();
    var sortBy = document.getElementById("sortSelect").value;
    var stopsMax = document.getElementById("stopsFilter").value;
    var airlineVal = document.getElementById("airlineFilter").value;

    // Filter
    if (stopsMax !== "any") {
        var maxStops = parseInt(stopsMax);
        flights = flights.filter(function(f) { return (f.stops || 0) <= maxStops; });
    }
    if (airlineVal !== "all") {
        flights = flights.filter(function(f) { return (f.airline || "Unknown") === airlineVal; });
    }

    // Sort
    flights.sort(function(a, b) {
        if (sortBy === "price_asc") return (a._mystesPrice || a.price || 0) - (b._mystesPrice || b.price || 0);
        if (sortBy === "price_desc") return (b._mystesPrice || b.price || 0) - (a._mystesPrice || a.price || 0);
        if (sortBy === "duration") return parseDuration(a.duration) - parseDuration(b.duration);
        if (sortBy === "departure") return (a.departure_time || "").localeCompare(b.departure_time || "");
        return 0;
    });

    renderFlightCards(flights);
}

async function bookThisFlight(card) {
    if (card.classList.contains("booking")) return;
    card.classList.add("booking");
    card.style.opacity = "0.6";
    try {
        var d = JSON.parse(card.getAttribute("data-flight"));
        var resp = await fetch("/api/v1/ai/book-flight", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            credentials: "same-origin",
            body: JSON.stringify(d)
        });
        var result = await resp.json();
        if (result.deal_id) {
            window.location.href = "/book/" + result.deal_id;
        } else if (resp.status === 401) {
            window.location.href = "/login?next=/flights";
        } else {
            card.classList.remove("booking");
            card.style.opacity = "1";
            alert(result.error || "Could not prepare booking.");
        }
    } catch(e) {
        card.classList.remove("booking");
        card.style.opacity = "1";
        alert("Booking unavailable. Please try again.");
    }
}

function toggleAlertForm() {
    var el = document.getElementById("alertFormInline");
    if (!el) {
        // Create inline alert form
        var container = document.getElementById("srSummary");
        var form = document.createElement("div");
        form.id = "alertFormInline";
        form.style.cssText = "background:white;border:1px solid #e5e7eb;border-radius:10px;padding:16px;margin-top:12px;display:flex;gap:10px;align-items:center;flex-wrap:wrap;";
        var s = window._lastSearch || {};
        form.innerHTML = '<span style="font-size:13px;color:#333;">Alert me for <strong>' + esc(s.origin||'') + ' &rarr; ' + esc(s.destination||'') + '</strong></span>' +
            '<input type="number" id="alertMaxPrice" placeholder="Max price (optional)" style="width:140px;padding:8px;border:1px solid #ddd;border-radius:6px;font-size:13px;">' +
            '<button onclick="createPriceAlert()" style="background:#7c3aed;color:white;border:none;padding:8px 18px;border-radius:6px;font-size:13px;cursor:pointer;font-weight:600;">Create Alert</button>' +
            '<button onclick="document.getElementById(\'alertFormInline\').remove()" style="background:none;border:none;color:#999;cursor:pointer;font-size:16px;">&times;</button>' +
            '<div id="alertMsg" style="width:100%;font-size:13px;display:none;"></div>';
        container.after(form);
    } else {
        el.remove();
    }
}

function createPriceAlert() {
    var s = window._lastSearch || {};
    var maxPrice = document.getElementById("alertMaxPrice").value;
    var body = {origin: s.origin, destination: s.destination};
    if (maxPrice) body.max_price_usd = parseFloat(maxPrice);
    fetch("/api/alerts", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        credentials: "same-origin",
        body: JSON.stringify(body)
    }).then(function(r) { return r.json(); })
    .then(function(data) {
        var msg = document.getElementById("alertMsg");
        if (data.error) {
            msg.style.display = "block";
            msg.style.color = "#dc2626";
            msg.textContent = data.error;
        } else {
            msg.style.display = "block";
            msg.style.color = "#059669";
            msg.textContent = "Price alert created! We'll notify you when prices drop.";
            setTimeout(function() { var f = document.getElementById("alertFormInline"); if(f) f.remove(); }, 2000);
        }
    }).catch(function() {
        var msg = document.getElementById("alertMsg");
        msg.style.display = "block";
        msg.style.color = "#dc2626";
        msg.textContent = "Please log in to set price alerts.";
    });
}

function comparePrices(btn, flightData) {
    event.stopPropagation();
    var container = btn.parentElement;
    btn.textContent = "Loading...";
    btn.disabled = true;
    fetch('/api/flight/competitors', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        credentials: 'same-origin',
        body: JSON.stringify({origin: flightData.origin, destination: flightData.destination, date: flightData.date, airline: flightData.airline})
    }).then(function(r) { return r.json(); }).then(function(data) {
        if (data.competitors && data.competitors.length) {
            var html = '<div style="margin-top:8px;padding:8px;background:rgba(0,0,0,0.3);border-radius:8px;font-size:12px;">';
            data.competitors.forEach(function(c) {
                html += '<div style="display:flex;justify-content:space-between;padding:2px 0;"><span style="color:#aaa;">' + c.name + '</span><span style="color:#f5f5f5;">$' + c.price + '</span></div>';
            });
            html += '</div>';
            container.insertAdjacentHTML('beforeend', html);
            btn.remove();
        } else {
            btn.textContent = "No data";
            btn.style.opacity = "0.5";
        }
    }).catch(function() {
        btn.textContent = "Compare";
        btn.disabled = false;
    });
}

function saveToFavorites(flightData) {
    event.stopPropagation();
    fetch('/api/save-item', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        credentials: 'same-origin',
        body: JSON.stringify({vertical: 'flight', item_data_json: JSON.stringify(flightData), price_at_save: flightData.price || 0})
    }).then(function(r) { return r.json(); }).then(function(data) {
        if (data.success) {
            event.target.innerHTML = '&#9829; Saved';
            event.target.style.color = '#ec4899';
        } else if (data.error && data.error.indexOf('log in') !== -1) {
            alert('Please log in to save items.');
        }
    }).catch(function() { alert('Please log in to save items.'); });
}

function showFareRules(fareSearchId, fareId) {
    var modal = document.getElementById('fareRulesModal');
    var content = document.getElementById('fareRulesContent');
    modal.style.display = 'flex';
    content.innerHTML = '<div style="text-align:center;padding:40px;"><div style="display:inline-block;width:32px;height:32px;border:3px solid rgba(124,58,237,0.3);border-top-color:#7c3aed;border-radius:50%;animation:spin 0.8s linear infinite;"></div><p style="color:rgba(255,255,255,0.5);margin-top:12px;">Loading fare rules...</p></div>';
    fetch('/api/picasso/fare-rules', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        credentials: 'same-origin',
        body: JSON.stringify({fare_search_id: fareSearchId, fare_id: fareId})
    }).then(function(r){ return r.json(); }).then(function(data) {
        if (!data.success || !data.rules) {
            content.innerHTML = '<div style="text-align:center;padding:30px;color:rgba(255,255,255,0.5);">Unable to load fare rules. This may not be available for all fare types.</div>';
            return;
        }
        var rules = data.rules;
        var categoryLabels = {PE:'Penalties',AP:'Advance Purchase',MN:'Minimum Stay',MX:'Maximum Stay',FL:'Flight Application',RU:'Rule Application',BG:'Baggage',CO:'Combinations',SR:'Sales Restrictions',TF:'Transfers',HI:'Higher Intermediate Point',CD:'Child Discounts'};
        var categoryColors = {PE:'rgba(239,68,68,0.15)',BG:'rgba(59,130,246,0.15)'};
        var categoryBorders = {PE:'#ef4444',BG:'#3b82f6'};
        var order = ['PE','BG','AP','MN','MX','FL','SR','CO','TF','RU','HI','CD'];
        var keys = Object.keys(rules);
        keys.sort(function(a,b){
            var ai = order.indexOf(a); var bi = order.indexOf(b);
            if (ai === -1) ai = 99; if (bi === -1) bi = 99;
            return ai - bi;
        });
        var html = '<h3 style="font-family:'Space Grotesk',sans-serif;font-size:18px;color:#f5f5f5;margin:0 0 20px;letter-spacing:2px;">FARE RULES</h3>';
        keys.forEach(function(cat){
            var rule = rules[cat];
            var label = categoryLabels[cat] || rule.title || cat;
            var bg = categoryColors[cat] || 'rgba(255,255,255,0.04)';
            var bc = categoryBorders[cat] || 'rgba(255,255,255,0.15)';
            html += '<div style="margin-bottom:12px;border-radius:10px;border:1px solid rgba(255,255,255,0.08);overflow:hidden;">';
            html += '<div onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display===\'none\'?\'block\':\'none\';this.querySelector(\'.fr-arrow\').textContent=this.nextElementSibling.style.display===\'none\'?\'\\u25B6\':\'\\u25BC\'" style="padding:12px 16px;background:' + bg + ';cursor:pointer;display:flex;justify-content:space-between;align-items:center;border-left:3px solid ' + bc + ';">';
            html += '<span style="font-weight:600;font-size:14px;color:#e2e8f0;">' + label + '</span>';
            html += '<span class="fr-arrow" style="color:rgba(255,255,255,0.4);font-size:11px;">&#9654;</span></div>';
            html += '<div style="display:none;padding:14px 16px;font-size:13px;line-height:1.6;color:rgba(255,255,255,0.7);background:rgba(0,0,0,0.2);max-height:300px;overflow-y:auto;">';
            html += (rule.text || 'No details available.').replace(/\\n/g, '<br>');
            html += '</div></div>';
        });
        if (keys.length === 0) {
            html += '<p style="color:rgba(255,255,255,0.5);text-align:center;padding:20px;">No fare rules available for this fare.</p>';
        }
        content.innerHTML = html;
    }).catch(function(err){
        content.innerHTML = '<div style="text-align:center;padding:30px;color:rgba(255,255,255,0.5);">Error loading fare rules. Please try again.</div>';
    });
}
function closeFareRules() { document.getElementById('fareRulesModal').style.display = 'none'; }
</script>

<div id="fareRulesModal" onclick="if(event.target===this)closeFareRules()" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.7);z-index:9999;display:none;justify-content:center;align-items:center;padding:20px;">
    <div style="background:rgba(15,10,25,0.98);backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);border:1px solid rgba(255,255,255,0.1);border-radius:16px;max-width:700px;width:100%;max-height:80vh;overflow-y:auto;padding:28px;position:relative;">
        <button onclick="closeFareRules()" style="position:absolute;top:14px;right:16px;background:none;border:none;color:rgba(255,255,255,0.5);font-size:20px;cursor:pointer;padding:4px 8px;">&times;</button>
        <div id="fareRulesContent"></div>
    </div>
</div>
'''


# ============================================================
# Common airport-to-city lookup (top 80 airports)
# ============================================================
AIRPORT_CITIES = {
    'JFK': 'New York', 'LGA': 'New York', 'EWR': 'Newark',
    'LAX': 'Los Angeles', 'SFO': 'San Francisco', 'ORD': 'Chicago',
    'MIA': 'Miami', 'ATL': 'Atlanta', 'DFW': 'Dallas', 'IAH': 'Houston',
    'SEA': 'Seattle', 'DEN': 'Denver', 'BOS': 'Boston', 'PHL': 'Philadelphia',
    'IAD': 'Washington DC', 'DCA': 'Washington DC', 'MSP': 'Minneapolis',
    'DTW': 'Detroit', 'CLT': 'Charlotte', 'LAS': 'Las Vegas',
    'PHX': 'Phoenix', 'MCO': 'Orlando', 'TPA': 'Tampa', 'SAN': 'San Diego',
    'PDX': 'Portland', 'SLC': 'Salt Lake City', 'BWI': 'Baltimore',
    'AUS': 'Austin', 'RDU': 'Raleigh', 'BNA': 'Nashville',
    'LHR': 'London', 'LGW': 'London', 'STN': 'London',
    'CDG': 'Paris', 'ORY': 'Paris',
    'FRA': 'Frankfurt', 'MUC': 'Munich', 'AMS': 'Amsterdam',
    'MAD': 'Madrid', 'BCN': 'Barcelona', 'FCO': 'Rome', 'MXP': 'Milan',
    'ZRH': 'Zurich', 'VIE': 'Vienna', 'CPH': 'Copenhagen',
    'OSL': 'Oslo', 'ARN': 'Stockholm', 'HEL': 'Helsinki',
    'IST': 'Istanbul', 'ATH': 'Athens', 'LIS': 'Lisbon',
    'DUB': 'Dublin', 'EDI': 'Edinburgh', 'BRU': 'Brussels',
    'NRT': 'Tokyo', 'HND': 'Tokyo', 'KIX': 'Osaka',
    'ICN': 'Seoul', 'GMP': 'Seoul',
    'PEK': 'Beijing', 'PVG': 'Shanghai', 'HKG': 'Hong Kong',
    'SIN': 'Singapore', 'BKK': 'Bangkok', 'KUL': 'Kuala Lumpur',
    'DEL': 'Delhi', 'BOM': 'Mumbai', 'SYD': 'Sydney', 'MEL': 'Melbourne',
    'AKL': 'Auckland', 'DXB': 'Dubai', 'DOH': 'Doha', 'AUH': 'Abu Dhabi',
    'JNB': 'Johannesburg', 'CPT': 'Cape Town', 'CAI': 'Cairo',
    'GRU': 'Sao Paulo', 'EZE': 'Buenos Aires', 'MEX': 'Mexico City',
    'BOG': 'Bogota', 'LIM': 'Lima', 'SCL': 'Santiago',
    'YYZ': 'Toronto', 'YVR': 'Vancouver', 'YUL': 'Montreal',
    'CUN': 'Cancun', 'SJU': 'San Juan', 'HNL': 'Honolulu',
}


# ============================================================
# Shareable Flight Card Page (PUBLIC — no login required)
# ============================================================

FLIGHT_CARD_PAGE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{{ og_title }}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="description" content="{{ og_description }}">

    <!-- OpenGraph — deal-specific for social sharing -->
    <meta property="og:title" content="{{ og_title }}">
    <meta property="og:description" content="{{ og_description }}">
    <meta property="og:type" content="website">
    <meta property="og:url" content="{{ og_url }}">
    <meta property="og:image" content="{{ og_image }}">
    <meta property="og:site_name" content="MYSTES">
    <meta property="og:locale" content="en_US">

    <!-- Twitter Card -->
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="{{ og_title }}">
    <meta name="twitter:description" content="{{ og_description }}">
    <meta name="twitter:image" content="{{ og_image }}">

    <meta name="theme-color" content="#7c3aed">
    <link rel="icon" type="image/svg+xml" href="/static/favicon-eyes.svg?v=3">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Outfit:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">

    <style>
        :root {
            --deep-space: #0a0612;
            --text-bright: #ffffff;
            --text-muted: #cccccc;
            --accent-teal: #14b8a6;
            --accent-gold: #C9A96E;
            --accent-purple: #7c3aed;
            --glass-bg: rgba(255,255,255,0.04);
            --glass-border: rgba(255,255,255,0.08);
            --font-brand: 'Space Grotesk', sans-serif;
            --font-body: 'Outfit', sans-serif;
        }

        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

        html {
            -webkit-font-smoothing: antialiased;
            background: var(--deep-space);
        }

        body {
            font-family: var(--font-body);
            color: var(--text-bright);
            min-height: 100vh;
            background: var(--deep-space);
            background-image:
                radial-gradient(ellipse at 20% 50%, rgba(124,58,237,0.08) 0%, transparent 50%),
                radial-gradient(ellipse at 80% 20%, rgba(20,184,166,0.06) 0%, transparent 50%);
            display: flex;
            flex-direction: column;
            align-items: center;
        }

        /* ---- Minimal Nav ---- */
        .card-nav {
            width: 100%;
            max-width: 1200px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 20px 24px;
        }
        .card-nav-brand {
            font-family: var(--font-brand);
            font-size: 18px;
            font-weight: 700;
            letter-spacing: 5px;
            text-transform: uppercase;
            text-decoration: none;
            background: linear-gradient(135deg, #fff 0%, #e8d5b7 40%, #fff 60%, #c9a96e 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        .card-nav-link {
            font-size: 13px;
            color: var(--text-muted);
            text-decoration: none;
            font-weight: 500;
            letter-spacing: 0.5px;
            transition: color 0.2s;
        }
        .card-nav-link:hover { color: var(--text-bright); }

        /* ---- Card Container ---- */
        .share-card-wrap {
            flex: 1;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px 16px 60px;
            width: 100%;
        }

        .share-card {
            width: 100%;
            max-width: 520px;
            background: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 20px;
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            overflow: hidden;
        }

        /* ---- Airline Header ---- */
        .sc-airline-header {
            display: flex;
            align-items: center;
            gap: 14px;
            padding: 24px 28px 0;
        }
        .sc-airline-logo {
            width: 48px;
            height: 48px;
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-family: var(--font-brand);
            font-weight: 700;
            font-size: 16px;
            color: #fff;
            letter-spacing: 1px;
            flex-shrink: 0;
        }
        .sc-airline-name {
            font-family: var(--font-brand);
            font-size: 16px;
            font-weight: 600;
            color: var(--text-bright);
            letter-spacing: 0.5px;
        }
        .sc-flight-num {
            font-size: 12px;
            color: var(--text-muted);
            margin-top: 2px;
            letter-spacing: 0.5px;
        }

        /* ---- Route Display ---- */
        .sc-route {
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 28px 28px 8px;
            gap: 20px;
        }
        .sc-endpoint {
            text-align: center;
            flex: 0 0 auto;
        }
        .sc-iata {
            font-family: var(--font-brand);
            font-size: 38px;
            font-weight: 700;
            color: var(--text-bright);
            letter-spacing: 2px;
            line-height: 1;
        }
        .sc-city {
            font-size: 13px;
            color: var(--text-muted);
            margin-top: 6px;
            letter-spacing: 0.3px;
        }
        .sc-arrow {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 6px;
            flex: 1;
            min-width: 80px;
            max-width: 140px;
        }
        .sc-arrow-line {
            width: 100%;
            height: 1px;
            background: linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.2) 20%, rgba(255,255,255,0.2) 80%, transparent 100%);
            position: relative;
        }
        .sc-arrow-line::after {
            content: '';
            position: absolute;
            right: -2px;
            top: -4px;
            width: 8px;
            height: 8px;
            border-top: 1px solid rgba(255,255,255,0.3);
            border-right: 1px solid rgba(255,255,255,0.3);
            transform: rotate(45deg);
        }
        .sc-plane-icon {
            font-size: 18px;
            color: rgba(255,255,255,0.3);
            line-height: 1;
        }

        /* ---- Date Row ---- */
        .sc-dates {
            display: flex;
            justify-content: center;
            gap: 32px;
            padding: 16px 28px;
        }
        .sc-date-item {
            text-align: center;
        }
        .sc-date-label {
            font-size: 10px;
            color: rgba(255,255,255,0.4);
            text-transform: uppercase;
            letter-spacing: 1.5px;
            font-weight: 600;
            margin-bottom: 4px;
        }
        .sc-date-value {
            font-size: 14px;
            color: var(--text-bright);
            font-weight: 500;
        }

        /* ---- Price Display ---- */
        .sc-price-section {
            text-align: center;
            padding: 20px 28px;
            border-top: 1px solid rgba(255,255,255,0.06);
            border-bottom: 1px solid rgba(255,255,255,0.06);
            background: rgba(255,255,255,0.015);
        }
        .sc-price-row {
            display: flex;
            align-items: baseline;
            justify-content: center;
            gap: 8px;
        }
        .sc-price {
            font-family: var(--font-brand);
            font-size: 44px;
            font-weight: 700;
            color: var(--accent-teal);
            letter-spacing: -1px;
            line-height: 1;
        }
        .sc-price-label {
            font-size: 13px;
            color: var(--text-muted);
            font-weight: 400;
        }
        .sc-original-price {
            font-size: 16px;
            color: rgba(255,255,255,0.35);
            text-decoration: line-through;
            margin-top: 8px;
        }
        .sc-savings-badge {
            display: inline-block;
            margin-top: 10px;
            padding: 5px 14px;
            background: rgba(201,169,110,0.12);
            border: 1px solid rgba(201,169,110,0.25);
            border-radius: 100px;
            font-size: 12px;
            font-weight: 600;
            color: var(--accent-gold);
            letter-spacing: 0.5px;
        }

        /* ---- Flight Details ---- */
        .sc-details {
            display: flex;
            justify-content: center;
            gap: 24px;
            padding: 18px 28px;
            flex-wrap: wrap;
        }
        .sc-detail-item {
            text-align: center;
        }
        .sc-detail-label {
            font-size: 10px;
            color: rgba(255,255,255,0.35);
            text-transform: uppercase;
            letter-spacing: 1.2px;
            font-weight: 600;
            margin-bottom: 4px;
        }
        .sc-detail-value {
            font-size: 14px;
            color: var(--text-bright);
            font-weight: 500;
        }

        /* ---- CTA Button ---- */
        .sc-cta {
            padding: 0 28px 24px;
        }
        .sc-book-btn {
            display: block;
            width: 100%;
            padding: 16px;
            background: linear-gradient(135deg, var(--accent-teal) 0%, #0d9488 100%);
            border: none;
            border-radius: 12px;
            color: #fff;
            font-family: var(--font-brand);
            font-size: 15px;
            font-weight: 700;
            letter-spacing: 2px;
            text-transform: uppercase;
            cursor: pointer;
            text-align: center;
            text-decoration: none;
            transition: transform 0.15s ease, box-shadow 0.15s ease;
        }
        .sc-book-btn:hover {
            transform: translateY(-1px);
            box-shadow: 0 8px 24px rgba(20,184,166,0.25);
        }

        /* ---- Share Row ---- */
        .sc-share-row {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 12px;
            padding: 0 28px 24px;
            flex-wrap: wrap;
        }
        .sc-share-btn {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 8px 16px;
            background: rgba(255,255,255,0.06);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 8px;
            color: var(--text-muted);
            font-size: 12px;
            font-weight: 500;
            cursor: pointer;
            text-decoration: none;
            transition: background 0.15s, color 0.15s, border-color 0.15s;
            font-family: var(--font-body);
        }
        .sc-share-btn:hover {
            background: rgba(255,255,255,0.1);
            color: var(--text-bright);
            border-color: rgba(255,255,255,0.2);
        }
        .sc-share-btn.copied {
            background: rgba(20,184,166,0.15);
            border-color: rgba(20,184,166,0.3);
            color: var(--accent-teal);
        }

        /* ---- Footer ---- */
        .card-footer {
            text-align: center;
            padding: 20px 24px 32px;
            font-size: 12px;
            color: rgba(255,255,255,0.25);
            letter-spacing: 0.3px;
        }
        .card-footer a {
            color: rgba(255,255,255,0.4);
            text-decoration: none;
        }
        .card-footer a:hover { color: var(--text-bright); }

        /* ---- Responsive ---- */
        @media (max-width: 560px) {
            .sc-iata { font-size: 30px; }
            .sc-price { font-size: 36px; }
            .sc-route { gap: 14px; padding: 24px 20px 8px; }
            .sc-airline-header, .sc-dates, .sc-details, .sc-cta, .sc-share-row { padding-left: 20px; padding-right: 20px; }
            .sc-price-section { padding: 18px 20px; }
        }
    </style>
</head>
<body>

    <!-- Minimal nav -->
    <nav class="card-nav">
        <a href="/" class="card-nav-brand">MYSTES</a>
        <a href="/flights" class="card-nav-link">Search Flights</a>
    </nav>

    <div class="share-card-wrap">
        <div class="share-card">

            <!-- Airline header -->
            <div class="sc-airline-header">
                <div class="sc-airline-logo" style="background: {{ airline_color }};">{{ airline_initials }}</div>
                <div>
                    <div class="sc-airline-name">{{ airline }}</div>
                    {% if flight_number %}<div class="sc-flight-num">{{ flight_number }}</div>{% endif %}
                </div>
            </div>

            <!-- Route -->
            <div class="sc-route">
                <div class="sc-endpoint">
                    <div class="sc-iata">{{ origin }}</div>
                    <div class="sc-city">{{ origin_city }}</div>
                </div>
                <div class="sc-arrow">
                    <div class="sc-plane-icon">&#9992;</div>
                    <div class="sc-arrow-line"></div>
                </div>
                <div class="sc-endpoint">
                    <div class="sc-iata">{{ destination }}</div>
                    <div class="sc-city">{{ destination_city }}</div>
                </div>
            </div>

            <!-- Dates -->
            <div class="sc-dates">
                <div class="sc-date-item">
                    <div class="sc-date-label">Departure</div>
                    <div class="sc-date-value">{{ departure_date_display }}</div>
                </div>
                {% if departure_time %}
                <div class="sc-date-item">
                    <div class="sc-date-label">Time</div>
                    <div class="sc-date-value">{{ departure_time }}</div>
                </div>
                {% endif %}
            </div>

            <!-- Price -->
            <div class="sc-price-section">
                <div class="sc-price-row">
                    <div class="sc-price">${{ price_display }}</div>
                    <div class="sc-price-label">per person</div>
                </div>
                {% if has_savings %}
                <div class="sc-original-price">${{ original_price_display }}</div>
                <div class="sc-savings-badge">Save ${{ savings_display }} ({{ savings_pct_display }}%)</div>
                {% endif %}
            </div>

            <!-- Flight details -->
            <div class="sc-details">
                {% if cabin_display %}
                <div class="sc-detail-item">
                    <div class="sc-detail-label">Cabin</div>
                    <div class="sc-detail-value">{{ cabin_display }}</div>
                </div>
                {% endif %}
                <div class="sc-detail-item">
                    <div class="sc-detail-label">Stops</div>
                    <div class="sc-detail-value">{{ stops_display }}</div>
                </div>
                {% if duration %}
                <div class="sc-detail-item">
                    <div class="sc-detail-label">Duration</div>
                    <div class="sc-detail-value">{{ duration }}</div>
                </div>
                {% endif %}
                {% if baggage_info %}
                <div class="sc-detail-item">
                    <div class="sc-detail-label">Baggage</div>
                    <div class="sc-detail-value">{{ baggage_info }}</div>
                </div>
                {% endif %}
            </div>

            <!-- CTA -->
            <div class="sc-cta">
                <a href="/book/{{ deal_id }}" class="sc-book-btn" id="bookBtn">Book This Flight</a>
            </div>

            <!-- Share row -->
            <div class="sc-share-row">
                <button class="sc-share-btn" id="copyLinkBtn" onclick="copyCardLink()">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>
                    Copy Link
                </button>
                <a class="sc-share-btn" href="https://twitter.com/intent/tweet?text={{ share_text_encoded }}&url={{ share_url_encoded }}" target="_blank" rel="noopener">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>
                    Share on X
                </a>
                <a class="sc-share-btn" href="https://wa.me/?text={{ share_text_encoded }}%20{{ share_url_encoded }}" target="_blank" rel="noopener">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/></svg>
                    WhatsApp
                </a>
            </div>

        </div>
    </div>

    <footer class="card-footer">
        Found on <a href="/">MYSTES</a> &mdash; AI-powered travel intelligence across 102 markets
    </footer>

    <script>
    function copyCardLink() {
        var url = window.location.href;
        var btn = document.getElementById("copyLinkBtn");
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(url).then(function() {
                btn.classList.add("copied");
                btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg> Copied!';
                setTimeout(function() {
                    btn.classList.remove("copied");
                    btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg> Copy Link';
                }, 2000);
            });
        } else {
            // Fallback for older browsers
            var input = document.createElement("input");
            input.value = url;
            document.body.appendChild(input);
            input.select();
            document.execCommand("copy");
            document.body.removeChild(input);
            btn.classList.add("copied");
            btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg> Copied!';
            setTimeout(function() {
                btn.classList.remove("copied");
                btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg> Copy Link';
            }, 2000);
        }
    }

    // Track share event
    (function() {
        var dealId = {{ deal_db_id }};
        if (dealId) {
            fetch("/api/flights/" + dealId + "/share", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                credentials: "same-origin",
                body: JSON.stringify({action: "view"})
            }).catch(function() {});
        }
    })();
    </script>

</body>
</html>
'''


# ============================================================
# Flight Card Image — OG preview (minimal, no actions)
# ============================================================

FLIGHT_CARD_IMAGE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=1200, initial-scale=1.0">
    <style>
        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

        @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Outfit:wght@300;400;500;600;700;800&display=swap');

        body {
            font-family: 'Outfit', sans-serif;
            background: #0a0612;
            background-image:
                radial-gradient(ellipse at 25% 50%, rgba(124,58,237,0.12) 0%, transparent 50%),
                radial-gradient(ellipse at 75% 30%, rgba(20,184,166,0.08) 0%, transparent 50%);
            width: 1200px;
            height: 630px;
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
        }

        .og-card {
            width: 1040px;
            background: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 28px;
            padding: 48px 56px;
            backdrop-filter: blur(12px);
        }

        /* Brand */
        .og-brand {
            font-family: 'Space Grotesk', sans-serif;
            font-size: 16px;
            font-weight: 700;
            letter-spacing: 5px;
            text-transform: uppercase;
            color: #C9A96E;
            margin-bottom: 32px;
        }

        /* Airline */
        .og-airline-row {
            display: flex;
            align-items: center;
            gap: 16px;
            margin-bottom: 28px;
        }
        .og-airline-logo {
            width: 52px;
            height: 52px;
            border-radius: 14px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-family: 'Space Grotesk', sans-serif;
            font-weight: 700;
            font-size: 17px;
            color: #fff;
            letter-spacing: 1px;
        }
        .og-airline-name {
            font-family: 'Space Grotesk', sans-serif;
            font-size: 20px;
            font-weight: 600;
            color: #ffffff;
        }
        .og-flight-num {
            font-size: 14px;
            color: #cccccc;
            margin-top: 2px;
        }

        /* Route */
        .og-route {
            display: flex;
            align-items: center;
            gap: 36px;
            margin-bottom: 28px;
        }
        .og-iata {
            font-family: 'Space Grotesk', sans-serif;
            font-size: 64px;
            font-weight: 700;
            color: #ffffff;
            letter-spacing: 3px;
            line-height: 1;
        }
        .og-city {
            font-size: 16px;
            color: #cccccc;
            margin-top: 6px;
        }
        .og-arrow-block {
            flex: 1;
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 8px;
        }
        .og-plane {
            font-size: 24px;
            color: rgba(255,255,255,0.3);
        }
        .og-arrow-line {
            width: 100%;
            max-width: 200px;
            height: 1px;
            background: linear-gradient(90deg, transparent, rgba(255,255,255,0.25), transparent);
        }

        /* Bottom row: price + details */
        .og-bottom {
            display: flex;
            align-items: flex-end;
            justify-content: space-between;
        }

        /* Price */
        .og-price-block {}
        .og-price {
            font-family: 'Space Grotesk', sans-serif;
            font-size: 56px;
            font-weight: 700;
            color: #14b8a6;
            letter-spacing: -1px;
            line-height: 1;
        }
        .og-price-label {
            font-size: 16px;
            color: #cccccc;
            margin-top: 6px;
        }
        .og-original-price {
            font-size: 18px;
            color: rgba(255,255,255,0.3);
            text-decoration: line-through;
            margin-top: 8px;
        }
        .og-savings-badge {
            display: inline-block;
            margin-top: 10px;
            padding: 6px 16px;
            background: rgba(201,169,110,0.12);
            border: 1px solid rgba(201,169,110,0.3);
            border-radius: 100px;
            font-size: 14px;
            font-weight: 600;
            color: #C9A96E;
            letter-spacing: 0.5px;
        }

        /* Details */
        .og-details {
            display: flex;
            gap: 36px;
            text-align: center;
        }
        .og-detail-label {
            font-size: 11px;
            color: rgba(255,255,255,0.35);
            text-transform: uppercase;
            letter-spacing: 1.5px;
            font-weight: 600;
            margin-bottom: 4px;
        }
        .og-detail-value {
            font-size: 16px;
            color: #ffffff;
            font-weight: 500;
        }
    </style>
</head>
<body>
    <div class="og-card">
        <div class="og-brand">MYSTES</div>

        <div class="og-airline-row">
            <div class="og-airline-logo" style="background: {{ airline_color }};">{{ airline_initials }}</div>
            <div>
                <div class="og-airline-name">{{ airline }}</div>
                {% if flight_number %}<div class="og-flight-num">{{ flight_number }}</div>{% endif %}
            </div>
        </div>

        <div class="og-route">
            <div>
                <div class="og-iata">{{ origin }}</div>
                <div class="og-city">{{ origin_city }}</div>
            </div>
            <div class="og-arrow-block">
                <div class="og-plane">&#9992;</div>
                <div class="og-arrow-line"></div>
            </div>
            <div>
                <div class="og-iata">{{ destination }}</div>
                <div class="og-city">{{ destination_city }}</div>
            </div>
        </div>

        <div class="og-bottom">
            <div class="og-price-block">
                <div class="og-price">${{ price_display }}</div>
                <div class="og-price-label">per person &middot; {{ departure_date_display }}</div>
                {% if has_savings %}
                <div class="og-original-price">${{ original_price_display }}</div>
                <div class="og-savings-badge">Save ${{ savings_display }} ({{ savings_pct_display }}%)</div>
                {% endif %}
            </div>
            <div class="og-details">
                {% if cabin_display %}
                <div>
                    <div class="og-detail-label">Cabin</div>
                    <div class="og-detail-value">{{ cabin_display }}</div>
                </div>
                {% endif %}
                <div>
                    <div class="og-detail-label">Stops</div>
                    <div class="og-detail-value">{{ stops_display }}</div>
                </div>
                {% if duration %}
                <div>
                    <div class="og-detail-label">Duration</div>
                    <div class="og-detail-value">{{ duration }}</div>
                </div>
                {% endif %}
            </div>
        </div>
    </div>
</body>
</html>
'''


def _airline_color(airline_name):
    """Generate a consistent color for an airline based on its name hash."""
    colors = [
        '#6366f1', '#8b5cf6', '#a855f7', '#d946ef',
        '#ec4899', '#f43f5e', '#ef4444', '#f97316',
        '#eab308', '#84cc16', '#22c55e', '#14b8a6',
        '#06b6d4', '#0ea5e9', '#3b82f6', '#6366f1',
    ]
    h = 0
    for c in (airline_name or 'XX'):
        h = (h * 31 + ord(c)) & 0xFFFFFFFF
    return colors[h % len(colors)]


def _airline_initials(airline_name):
    """Extract 2-letter initials from airline name."""
    if not airline_name:
        return '??'
    parts = airline_name.strip().split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return airline_name[:2].upper()


def _format_cabin(cabin_class):
    """Format cabin class for display (ECONOMY -> Economy)."""
    if not cabin_class:
        return None
    mapping = {
        'ECONOMY': 'Economy', 'economy': 'Economy',
        'PREMIUM_ECONOMY': 'Premium Economy', 'premium_economy': 'Premium Economy',
        'BUSINESS': 'Business', 'business': 'Business',
        'FIRST': 'First Class', 'first': 'First Class',
    }
    return mapping.get(cabin_class, cabin_class.replace('_', ' ').title())


def _format_date(d):
    """Format a date object for display."""
    if not d:
        return 'TBD'
    try:
        months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        return f"{months[d.month - 1]} {d.day}, {d.year}"
    except Exception:
        return str(d)


def _build_card_context(deal):
    """Build template context dict from a Deal model instance."""
    from urllib.parse import quote

    origin = deal.origin or '???'
    destination = deal.destination or '???'
    airline = deal.airline or 'Unknown Airline'
    origin_city = AIRPORT_CITIES.get(origin.upper(), origin)
    destination_city = AIRPORT_CITIES.get(destination.upper(), destination)

    # Price: use arbitrage_price_usd (our selling price) or home_price_usd
    price = deal.arbitrage_price_usd or deal.home_price_usd or 0
    home_price = deal.home_price_usd or 0
    savings = deal.user_savings_usd or 0
    savings_pct = deal.savings_percent or 0
    has_savings = savings > 0 and home_price > price

    # Stops display
    stops = deal.stops or 0
    if stops == 0:
        stops_display = 'Nonstop'
    elif stops == 1:
        stops_display = '1 stop'
    else:
        stops_display = f'{stops} stops'

    cabin_display = _format_cabin(deal.cabin_class)
    departure_date_display = _format_date(deal.departure_date)

    # OG meta values
    price_str = f'${price:,.0f}' if price else 'See Price'
    og_title = f'{origin} to {destination} from {price_str} | MYSTES'

    desc_parts = []
    if cabin_display:
        desc_parts.append(cabin_display)
    desc_parts.append(stops_display)
    if deal.duration:
        desc_parts.append(deal.duration)
    og_description = ', '.join(desc_parts) + '. Book now on MYSTES.'

    # Share text for social
    share_text = f'Check out this flight: {origin} to {destination} from {price_str}'
    if has_savings:
        share_text += f' (save ${savings:,.0f}!)'

    base_url = request.url_root.rstrip('/')
    card_url = f'{base_url}/flight-card/{deal.id}'
    image_url = f'{base_url}/flight-card/{deal.id}/image'

    return {
        'deal_id': deal.deal_id,
        'deal_db_id': deal.id,
        'airline': airline,
        'airline_initials': _airline_initials(airline),
        'airline_color': _airline_color(airline),
        'flight_number': deal.flight_number or '',
        'origin': origin,
        'destination': destination,
        'origin_city': origin_city,
        'destination_city': destination_city,
        'departure_date_display': departure_date_display,
        'departure_time': deal.departure_time or '',
        'price_display': f'{price:,.0f}' if price else '0',
        'original_price_display': f'{home_price:,.0f}' if home_price else '',
        'has_savings': has_savings,
        'savings_display': f'{savings:,.0f}' if savings else '0',
        'savings_pct_display': f'{savings_pct:.0f}' if savings_pct else '0',
        'cabin_display': cabin_display,
        'stops_display': stops_display,
        'duration': deal.duration or '',
        'baggage_info': deal.baggage_info or '',
        'og_title': og_title,
        'og_description': og_description,
        'og_url': card_url,
        'og_image': image_url,
        'share_text_encoded': quote(share_text),
        'share_url_encoded': quote(card_url),
    }


def register_flight_routes(app, csrf, limiter):
    """Register flights vertical routes."""
    from templates.base_template import BASE_TEMPLATE

    @app.route("/flights")
    def flights_page():
        """Flights search page — extracted from homepage (Build #167)."""
        from models import FeatureFlag
        if not FeatureFlag.is_flag_enabled('vertical_flights'):
            return "Flights vertical is not currently available.", 410

        from payments import get_fee_percent
        fee_pct = get_fee_percent()

        rendered = render_template_string(
            FLIGHTS_SEARCH_CONTENT,
            current_user=current_user,
            fee_pct=fee_pct
        )
        return render_template_string(
            BASE_TEMPLATE,
            title="Flights",
            content=rendered,
            current_user=current_user
        )

    # ----------------------------------------------------------
    # Shareable Flight Card (PUBLIC — no login)
    # ----------------------------------------------------------
    @app.route("/flight-card/<int:deal_id>")
    def flight_card_page(deal_id):
        """Public shareable flight card with OG meta tags for social sharing."""
        from models import Deal
        deal = Deal.query.get(deal_id)
        if not deal or deal.deal_type != 'flight':
            abort(404)

        ctx = _build_card_context(deal)
        return render_template_string(FLIGHT_CARD_PAGE, **ctx)

    # ----------------------------------------------------------
    # Flight Card OG Image (PUBLIC — for social preview)
    # ----------------------------------------------------------
    @app.route("/flight-card/<int:deal_id>/image")
    def flight_card_image(deal_id):
        """Minimal card page for social platform OG image preview."""
        from models import Deal
        deal = Deal.query.get(deal_id)
        if not deal or deal.deal_type != 'flight':
            abort(404)

        ctx = _build_card_context(deal)
        return render_template_string(FLIGHT_CARD_IMAGE, **ctx)

    logger.info("Flights routes registered at /flights, /flight-card/<id>, /flight-card/<id>/image")
