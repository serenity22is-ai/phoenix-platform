"""
MYSTES Flights Vertical — Route Module (Build #167)

Extracted from homepage HOME_HERO to /flights.
Search UI with glass morphism design, trip type toggle, passenger selectors.
API backend stays in server.py (/api/search).

Registration: register_flight_routes(app, csrf, limiter)
"""

import logging
from flask import render_template_string
from flask_login import current_user

logger = logging.getLogger(__name__)


# ============================================================
# Flights Search Page Content
# ============================================================

FLIGHTS_SEARCH_CONTENT = '''
<style>
    .search-page { min-height: calc(100vh - 80px); padding: 40px 20px 60px; }
    .search-header { text-align: center; margin-bottom: 32px; opacity:0; animation: fadeInUp 0.6s var(--ease-out) 0.1s forwards; }
    .search-header h1 { font-family: var(--font-display); font-size: clamp(36px, 8vw, 72px); font-weight: 600; letter-spacing: 8px; text-transform: uppercase; color: var(--text-bright); margin: 0 0 8px; text-shadow: 0 4px 40px rgba(0,0,0,0.5); }
    .search-header p { font-size: 16px; color: var(--text-secondary); margin: 0; }

    .search-form-card {
        max-width: 900px; margin: 0 auto 32px; padding: 28px 32px;
        background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1);
        border-radius: 16px; backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);
        opacity:0; animation: fadeInUp 0.6s var(--ease-out) 0.2s forwards;
    }

    .sf-row { display: flex; gap: 12px; margin-bottom: 14px; flex-wrap: wrap; }
    .sf-field { flex: 1; min-width: 140px; }
    .sf-field label { display: block; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 1.5px; color: rgba(255,255,255,0.5); margin-bottom: 6px; font-family: var(--font-sans); }
    .sf-field input, .sf-field select {
        width: 100%; padding: 12px 14px; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12);
        border-radius: 10px; color: var(--text-bright); font-size: 15px; font-family: var(--font-sans); outline: none;
        transition: border-color 0.2s;
    }
    .sf-field input:focus, .sf-field select:focus { border-color: rgba(124,58,237,0.5); }
    .sf-field input::placeholder { color: rgba(255,255,255,0.3); }
    .sf-field select option { background: #1a1a2e; color: #fff; }

    .sf-pax { display: flex; gap: 12px; flex-wrap: wrap; }
    .sf-pax .sf-field { min-width: 100px; flex: 0 1 auto; }

    .sf-submit-row { display: flex; justify-content: center; margin-top: 20px; }
    .sf-submit {
        padding: 14px 48px; border: none; border-radius: 12px; cursor: pointer;
        font-family: var(--font-display); font-size: 15px; font-weight: 600; letter-spacing: 3px; text-transform: uppercase;
        background: linear-gradient(135deg, var(--mystes-purple), var(--mystes-deep)); color: white;
        transition: opacity 0.2s, transform 0.2s;
    }
    .sf-submit:hover { opacity: 0.9; transform: translateY(-1px); }
    .sf-submit:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }

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

    /* Results */
    .search-results { max-width: 900px; margin: 0 auto; }
    .sr-loading { text-align: center; padding: 60px 20px; display: none; }
    .sr-loading .spinner { width: 40px; height: 40px; border: 3px solid rgba(255,255,255,0.1); border-top-color: var(--mystes-purple); border-radius: 50%; animation: spin 0.8s linear infinite; margin: 0 auto 16px; }
    .sr-loading p { color: var(--text-secondary); font-size: 14px; }
    @keyframes spin { to { transform: rotate(360deg); } }

    .sr-error { text-align: center; padding: 40px 20px; color: #f87171; display: none; }
    .sr-summary { text-align: center; padding: 16px 0 24px; color: var(--text-secondary); font-size: 14px; display: none; }

    .flight-card {
        background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08);
        border-radius: 14px; padding: 20px 24px; margin-bottom: 14px;
        display: grid; grid-template-columns: 140px 1fr 160px; align-items: center; gap: 20px;
        transition: border-color 0.2s, background 0.2s; cursor: pointer;
    }
    .flight-card:hover { border-color: rgba(124,58,237,0.4); background: rgba(124,58,237,0.06); }
    .fc-airline { min-width: 120px; }
    .fc-airline-name { font-weight: 700; color: var(--text-bright); font-size: 15px; }
    .fc-flight-num { font-size: 12px; color: var(--text-secondary); margin-top: 2px; }
    .fc-route { display: flex; align-items: center; gap: 16px; justify-content: center; }
    .fc-endpoint { text-align: center; }
    .fc-time { font-size: 20px; font-weight: 700; color: var(--text-bright); letter-spacing: 0.5px; }
    .fc-code { font-size: 12px; color: var(--text-secondary); text-transform: uppercase; margin-top: 2px; letter-spacing: 1px; }
    .fc-arrow { display: flex; flex-direction: column; align-items: center; gap: 4px; min-width: 80px; position: relative; }
    .fc-line { width: 100%; height: 1px; background: rgba(255,255,255,0.15); }
    .fc-duration { font-size: 11px; color: var(--text-secondary); white-space: nowrap; }
    .fc-stops { font-size: 10px; color: rgba(124,58,237,0.8); font-weight: 600; }
    .fc-price-section { text-align: right; min-width: 140px; }
    .fc-price { font-size: 24px; font-weight: 800; color: var(--text-bright); }
    .fc-savings { font-size: 12px; color: #34d399; font-weight: 600; margin-top: 2px; }
    .fc-google-price { font-size: 12px; color: var(--text-secondary); text-decoration: line-through; }
    .fc-book-btn {
        padding: 10px 24px; border: none; border-radius: 10px; cursor: pointer;
        background: linear-gradient(135deg, var(--mystes-purple), var(--mystes-deep)); color: white;
        font-weight: 700; font-size: 13px; font-family: var(--font-sans); transition: opacity 0.2s;
    }
    .fc-book-btn:hover { opacity: 0.85; }

    .no-results { text-align: center; padding: 60px 20px; color: var(--text-secondary); display: none; }

    @keyframes fadeInUp { from { opacity:0; transform: translateY(20px); } to { opacity:1; transform: translateY(0); } }

    @media (max-width: 768px) {
        .search-form-card { padding: 20px 16px; }
        .sf-row { flex-direction: column; gap: 10px; }
        .sf-field { min-width: 100%; }
        .sf-pax { flex-direction: row; }
        .sf-pax .sf-field { min-width: 80px; flex: 1; }
        .flight-card { grid-template-columns: 1fr; gap: 12px; padding: 16px; }
        .fc-price-section { text-align: left; width: 100%; display: flex; justify-content: space-between; align-items: center; }
    }
</style>

<section class="search-page">
    <div class="search-header">
        <h1>FLIGHTS</h1>
        <p>Search 102 markets for the cheapest flights</p>
    </div>

    <div class="search-form-card">
        <div class="sf-trip-toggle">
            <button type="button" class="sf-trip-btn active" onclick="setTripType(this,&apos;oneway&apos;)">One Way</button>
            <button type="button" class="sf-trip-btn" onclick="setTripType(this,&apos;roundtrip&apos;)">Round Trip</button>
        </div>

        <div class="sf-row">
            <div class="sf-field">
                <label>From</label>
                <input type="text" id="sfOrigin" placeholder="JFK, LAX, ORD..." maxlength="3" style="text-transform:uppercase;">
            </div>
            <div class="sf-field">
                <label>To</label>
                <input type="text" id="sfDest" placeholder="LHR, NRT, CDG..." maxlength="3" style="text-transform:uppercase;">
            </div>
            <div class="sf-field">
                <label>Departure</label>
                <input type="date" id="sfDate">
            </div>
            <div class="sf-field" id="sfReturnWrap" style="display:none;">
                <label>Return</label>
                <input type="date" id="sfReturn">
            </div>
        </div>

        <div class="sf-row sf-pax">
            <div class="sf-field">
                <label>Adults</label>
                <select id="sfAdults">
                    <option value="1" selected>1</option>
                    <option value="2">2</option>
                    <option value="3">3</option>
                    <option value="4">4</option>
                    <option value="5">5</option>
                    <option value="6">6</option>
                </select>
            </div>
            <div class="sf-field">
                <label>Children</label>
                <select id="sfChildren">
                    <option value="0" selected>0</option>
                    <option value="1">1</option>
                    <option value="2">2</option>
                    <option value="3">3</option>
                    <option value="4">4</option>
                </select>
            </div>
            <div class="sf-field">
                <label>Infants</label>
                <select id="sfInfants">
                    <option value="0" selected>0</option>
                    <option value="1">1</option>
                    <option value="2">2</option>
                </select>
            </div>
            <div class="sf-field">
                <label>Cabin</label>
                <select id="sfCabin">
                    <option value="economy" selected>Economy</option>
                    <option value="premium_economy">Premium Economy</option>
                    <option value="business">Business</option>
                    <option value="first">First</option>
                </select>
            </div>
        </div>

        <div class="sf-submit-row">
            <button class="sf-submit" id="sfSearchBtn" onclick="searchFlights()">Search Flights</button>
        </div>
    </div>

    <div class="search-results">
        <div class="sr-loading" id="srLoading">
            <div class="spinner"></div>
            <p>Searching 102 markets for the best price...</p>
        </div>
        <div class="sr-error" id="srError"></div>
        <div class="sr-summary" id="srSummary"></div>
        <!-- Sort & Filter Toolbar (Build #172) -->
        <div id="srToolbar" style="display:none;background:white;border:1px solid #e5e7eb;border-radius:10px;padding:12px 16px;margin-bottom:12px;gap:12px;flex-wrap:wrap;align-items:center;">
            <div style="display:flex;align-items:center;gap:8px;">
                <label style="font-size:13px;color:#333;font-weight:600;">Sort:</label>
                <select id="sortSelect" onchange="sortAndFilter()" style="padding:6px 10px;border:1px solid #ddd;border-radius:6px;font-size:13px;">
                    <option value="price_asc">Price (low to high)</option>
                    <option value="price_desc">Price (high to low)</option>
                    <option value="duration">Duration (shortest)</option>
                    <option value="departure">Departure (earliest)</option>
                </select>
            </div>
            <div style="display:flex;align-items:center;gap:8px;">
                <label style="font-size:13px;color:#333;font-weight:600;">Stops:</label>
                <select id="stopsFilter" onchange="sortAndFilter()" style="padding:6px 10px;border:1px solid #ddd;border-radius:6px;font-size:13px;">
                    <option value="any">Any</option>
                    <option value="0">Nonstop only</option>
                    <option value="1">1 stop max</option>
                </select>
            </div>
            <div style="display:flex;align-items:center;gap:8px;">
                <label style="font-size:13px;color:#333;font-weight:600;">Airline:</label>
                <select id="airlineFilter" onchange="sortAndFilter()" style="padding:6px 10px;border:1px solid #ddd;border-radius:6px;font-size:13px;">
                    <option value="all">All Airlines</option>
                </select>
            </div>
            <div id="srFilterCount" style="font-size:12px;color:#999;margin-left:auto;"></div>
        </div>
        <div id="srCards"></div>
        <div class="no-results" id="srNoResults">No flights found. Try different dates or airports.</div>
    </div>
</section>

<script>
var tripType = "oneway";
window._feePercent = {{ fee_pct }};

function setTripType(btn, type) {
    tripType = type;
    document.querySelectorAll(".sf-trip-btn").forEach(function(b) { b.classList.remove("active"); });
    btn.classList.add("active");
    document.getElementById("sfReturnWrap").style.display = type === "roundtrip" ? "" : "none";
}

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
        var fd = JSON.stringify({origin: origin, destination: dest, date: date, price: wholesalePrice, title: airline + " " + flightNum, airline: airline, flight_number: flightNum, departure_time: depTime, arrival_time: arrTime, stops: stops, home_price: homePrice, arbitrage_price: wholesalePrice, savings: customerSavings, savings_pct: savingsPct, raw_offer: rawOffer});
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
    fetch('/api/flights/booking-options', {
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
</script>
'''


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
            title="Flights - MYSTES",
            content=rendered,
            current_user=current_user
        )

    logger.info("Flights routes registered at /flights")
