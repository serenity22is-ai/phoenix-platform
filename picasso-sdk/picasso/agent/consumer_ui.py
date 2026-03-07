"""
Consumer-Facing UI — Turnkey OTA template (Tier 3).

Complete flight search + booking frontend served as a single HTML page.
All branding, pricing, and display settings loaded from agency config.
Communicates with the hosted API via the agency's API key.

Pages:
    /              — Search form + results
    /booking       — Passenger details + booking confirmation
    /my-bookings   — Lookup existing bookings by PNR

MYSTES KYRIOS LLC — Confidential.
"""

CONSUMER_UI_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title id="page-title">Flight Search</title>
<link rel="icon" id="favicon" href="">
<style>
    @import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@600;700&family=Outfit:wght@300;400;500;600;700&family=Inter:wght@400;500;600;700&display=swap');
    * { margin: 0; padding: 0; box-sizing: border-box; }
    :root {
        --bg: #0a0612;
        --card: #14112a;
        --card-hover: #1c1838;
        --border: #2a2550;
        --text: #f0eef5;
        --text-dim: #9994b8;
        --primary: #1a1a2e;
        --accent: #6366f1;
        --accent-hover: #818cf8;
        --success: #22c55e;
        --warning: #f59e0b;
        --danger: #ef4444;
        --input-bg: #0e0b1d;
        --heading-font: 'Cinzel', serif;
        --body-font: 'Outfit', sans-serif;
    }
    body {
        font-family: var(--body-font);
        background: var(--bg);
        color: var(--text);
        line-height: 1.6;
        min-height: 100vh;
    }

    /* ===== HEADER ===== */
    .header {
        background: var(--primary);
        border-bottom: 1px solid var(--border);
        padding: 16px 32px;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    .header .logo {
        font-family: var(--heading-font);
        font-size: 22px;
        font-weight: 700;
        letter-spacing: 3px;
        color: var(--text);
        text-decoration: none;
    }
    .header .logo img { height: 32px; vertical-align: middle; margin-right: 8px; }
    .header nav { display: flex; gap: 24px; }
    .header nav a {
        color: var(--text-dim);
        text-decoration: none;
        font-size: 14px;
        font-weight: 500;
        transition: color 0.2s;
    }
    .header nav a:hover { color: var(--text); }
    .header nav a.active { color: var(--accent); }

    /* ===== HERO / SEARCH ===== */
    .hero {
        text-align: center;
        padding: 48px 24px 32px;
    }
    .hero h1 {
        font-family: var(--heading-font);
        font-size: 36px;
        font-weight: 700;
        margin-bottom: 8px;
        letter-spacing: 2px;
    }
    .hero p {
        color: var(--text-dim);
        font-size: 16px;
        max-width: 500px;
        margin: 0 auto;
    }

    .search-form {
        max-width: 900px;
        margin: 24px auto;
        background: var(--card);
        border: 1px solid var(--border);
        border-radius: 16px;
        padding: 24px;
    }
    .search-row {
        display: grid;
        grid-template-columns: 1fr 1fr 1fr 1fr auto;
        gap: 12px;
        align-items: end;
    }
    .search-row-2 {
        display: grid;
        grid-template-columns: repeat(5, 1fr);
        gap: 12px;
        margin-top: 12px;
        align-items: end;
    }
    .field { display: flex; flex-direction: column; gap: 4px; }
    .field label {
        font-size: 11px;
        font-weight: 600;
        color: var(--text-dim);
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .field input, .field select {
        background: var(--input-bg);
        border: 1px solid var(--border);
        border-radius: 10px;
        padding: 12px 14px;
        color: var(--text);
        font-size: 15px;
        font-family: var(--body-font);
        outline: none;
        transition: border 0.2s;
    }
    .field input:focus, .field select:focus { border-color: var(--accent); }
    .search-btn {
        background: var(--accent);
        color: white;
        border: none;
        border-radius: 10px;
        padding: 12px 28px;
        font-size: 15px;
        font-weight: 600;
        cursor: pointer;
        font-family: var(--body-font);
        transition: background 0.2s;
        white-space: nowrap;
    }
    .search-btn:hover { background: var(--accent-hover); }
    .search-btn:disabled { opacity: 0.6; cursor: not-allowed; }

    /* ===== RESULTS ===== */
    .results-section {
        max-width: 900px;
        margin: 0 auto;
        padding: 0 24px 48px;
    }
    .results-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 16px;
    }
    .results-header h2 {
        font-size: 18px;
        font-weight: 600;
    }
    .results-header .count {
        color: var(--text-dim);
        font-size: 14px;
    }
    .sort-bar {
        display: flex;
        gap: 8px;
        margin-bottom: 16px;
    }
    .sort-btn {
        padding: 6px 14px;
        border: 1px solid var(--border);
        border-radius: 8px;
        background: transparent;
        color: var(--text-dim);
        font-size: 13px;
        cursor: pointer;
        font-family: var(--body-font);
    }
    .sort-btn.active { background: var(--accent); color: white; border-color: var(--accent); }

    /* Flight card */
    .flight-card {
        background: var(--card);
        border: 1px solid var(--border);
        border-radius: 14px;
        padding: 20px 24px;
        margin-bottom: 12px;
        display: grid;
        grid-template-columns: 2fr 1fr 1fr;
        gap: 20px;
        align-items: center;
        transition: border-color 0.2s, transform 0.1s;
        cursor: pointer;
    }
    .flight-card:hover { border-color: var(--accent); transform: translateY(-1px); }

    .flight-route { display: flex; flex-direction: column; gap: 6px; }
    .flight-airline {
        font-size: 13px;
        font-weight: 600;
        color: var(--accent);
        display: flex;
        align-items: center;
        gap: 6px;
    }
    .flight-times {
        display: flex;
        align-items: center;
        gap: 12px;
        font-size: 20px;
        font-weight: 600;
    }
    .flight-arrow {
        flex: 1;
        height: 2px;
        background: var(--border);
        position: relative;
        min-width: 40px;
    }
    .flight-arrow::after {
        content: '';
        position: absolute;
        right: 0;
        top: -4px;
        width: 0;
        height: 0;
        border-left: 8px solid var(--border);
        border-top: 5px solid transparent;
        border-bottom: 5px solid transparent;
    }
    .flight-stops {
        text-align: center;
        font-size: 11px;
        color: var(--text-dim);
        position: absolute;
        top: -18px;
        left: 50%;
        transform: translateX(-50%);
        white-space: nowrap;
    }
    .flight-arrow-container { position: relative; flex: 1; min-width: 60px; }
    .flight-meta {
        display: flex;
        gap: 16px;
        font-size: 12px;
        color: var(--text-dim);
    }

    .flight-details {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 4px;
    }
    .flight-duration {
        font-size: 14px;
        font-weight: 500;
    }
    .flight-tags {
        display: flex;
        flex-wrap: wrap;
        gap: 4px;
        justify-content: center;
    }
    .tag {
        font-size: 10px;
        padding: 2px 8px;
        border-radius: 4px;
        background: rgba(99,102,241,0.15);
        color: var(--accent);
        font-weight: 500;
    }
    .tag.warn { background: rgba(245,158,11,0.15); color: var(--warning); }
    .tag.good { background: rgba(34,197,94,0.15); color: var(--success); }

    .flight-price {
        text-align: right;
        display: flex;
        flex-direction: column;
        gap: 4px;
    }
    .flight-price .amount {
        font-size: 24px;
        font-weight: 700;
        color: var(--text);
    }
    .flight-price .benchmark {
        font-size: 13px;
        color: var(--text-dim);
        text-decoration: line-through;
    }
    .flight-price .savings {
        font-size: 12px;
        font-weight: 600;
        color: var(--success);
    }
    .flight-price .per-pax {
        font-size: 11px;
        color: var(--text-dim);
    }
    .select-btn {
        margin-top: 8px;
        padding: 8px 20px;
        border: none;
        border-radius: 8px;
        background: var(--accent);
        color: white;
        font-size: 13px;
        font-weight: 600;
        cursor: pointer;
        font-family: var(--body-font);
    }
    .select-btn:hover { background: var(--accent-hover); }

    /* ===== BOOKING PAGE ===== */
    .booking-section {
        max-width: 700px;
        margin: 0 auto;
        padding: 24px;
    }
    .booking-card {
        background: var(--card);
        border: 1px solid var(--border);
        border-radius: 14px;
        padding: 24px;
        margin-bottom: 20px;
    }
    .booking-card h2 {
        font-size: 18px;
        font-weight: 600;
        margin-bottom: 16px;
    }
    .booking-card h3 {
        font-size: 14px;
        font-weight: 600;
        color: var(--accent);
        margin: 16px 0 8px;
    }
    .pax-form {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 12px;
    }
    .pax-form .field input, .pax-form .field select {
        width: 100%;
    }
    .booking-summary {
        display: flex;
        justify-content: space-between;
        padding: 12px 0;
        border-bottom: 1px solid var(--border);
        font-size: 14px;
    }
    .booking-summary:last-child { border-bottom: none; }
    .booking-summary .val { font-weight: 600; }
    .book-btn {
        width: 100%;
        padding: 14px;
        border: none;
        border-radius: 10px;
        background: var(--success);
        color: white;
        font-size: 16px;
        font-weight: 700;
        cursor: pointer;
        font-family: var(--body-font);
        margin-top: 16px;
        transition: opacity 0.2s;
    }
    .book-btn:hover { opacity: 0.9; }
    .book-btn:disabled { opacity: 0.5; cursor: not-allowed; }

    /* Confirmation */
    .confirmation {
        text-align: center;
        padding: 40px 24px;
    }
    .confirmation .check {
        width: 64px;
        height: 64px;
        background: var(--success);
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        margin: 0 auto 16px;
        font-size: 28px;
    }
    .pnr-box {
        background: var(--input-bg);
        border: 2px dashed var(--accent);
        border-radius: 12px;
        padding: 20px;
        margin: 16px auto;
        max-width: 300px;
    }
    .pnr-box .label { font-size: 12px; color: var(--text-dim); }
    .pnr-box .code {
        font-size: 32px;
        font-weight: 700;
        font-family: 'Courier New', monospace;
        letter-spacing: 4px;
        color: var(--accent);
        margin-top: 4px;
    }

    /* ===== AI CHAT WIDGET ===== */
    .chat-toggle {
        position: fixed;
        bottom: 24px;
        right: 24px;
        width: 56px;
        height: 56px;
        border-radius: 50%;
        background: var(--accent);
        color: white;
        border: none;
        cursor: pointer;
        font-size: 24px;
        box-shadow: 0 4px 16px rgba(99,102,241,0.4);
        z-index: 999;
        transition: transform 0.2s;
    }
    .chat-toggle:hover { transform: scale(1.1); }
    .chat-panel {
        position: fixed;
        bottom: 92px;
        right: 24px;
        width: 380px;
        height: 500px;
        background: var(--card);
        border: 1px solid var(--border);
        border-radius: 16px;
        z-index: 998;
        display: none;
        flex-direction: column;
        overflow: hidden;
        box-shadow: 0 8px 32px rgba(0,0,0,0.4);
    }
    .chat-panel.open { display: flex; }
    .chat-header {
        padding: 14px 16px;
        border-bottom: 1px solid var(--border);
        font-weight: 600;
        font-size: 14px;
        display: flex;
        justify-content: space-between;
    }
    .chat-messages {
        flex: 1;
        overflow-y: auto;
        padding: 16px;
        display: flex;
        flex-direction: column;
        gap: 12px;
    }
    .chat-msg {
        max-width: 85%;
        padding: 10px 14px;
        border-radius: 12px;
        font-size: 14px;
        line-height: 1.5;
        white-space: pre-wrap;
    }
    .chat-msg.user {
        align-self: flex-end;
        background: var(--accent);
        color: white;
        border-bottom-right-radius: 4px;
    }
    .chat-msg.assistant {
        align-self: flex-start;
        background: var(--input-bg);
        border: 1px solid var(--border);
        border-bottom-left-radius: 4px;
    }
    .chat-input-row {
        padding: 12px;
        border-top: 1px solid var(--border);
        display: flex;
        gap: 8px;
    }
    .chat-input-row input {
        flex: 1;
        background: var(--input-bg);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 10px 12px;
        color: var(--text);
        font-size: 14px;
        font-family: var(--body-font);
        outline: none;
    }
    .chat-input-row button {
        background: var(--accent);
        color: white;
        border: none;
        border-radius: 8px;
        padding: 10px 16px;
        cursor: pointer;
        font-weight: 600;
        font-family: var(--body-font);
    }

    /* ===== LOADING ===== */
    .loading { text-align: center; padding: 40px; color: var(--text-dim); }
    .spinner {
        width: 32px;
        height: 32px;
        border: 3px solid var(--border);
        border-top-color: var(--accent);
        border-radius: 50%;
        animation: spin 0.8s linear infinite;
        margin: 0 auto 12px;
    }
    @keyframes spin { to { transform: rotate(360deg); } }

    /* Skeleton cards */
    .skeleton-card {
        background: var(--card);
        border: 1px solid var(--border);
        border-radius: 14px;
        padding: 24px;
        margin-bottom: 12px;
        height: 100px;
        position: relative;
        overflow: hidden;
    }
    .skeleton-card::after {
        content: '';
        position: absolute;
        inset: 0;
        background: linear-gradient(90deg, transparent, rgba(99,102,241,0.05), transparent);
        animation: shimmer 1.5s infinite;
    }
    @keyframes shimmer { 0% { transform: translateX(-100%); } 100% { transform: translateX(100%); } }

    /* ===== TOAST ===== */
    .toast {
        position: fixed;
        bottom: 24px;
        left: 50%;
        transform: translateX(-50%) translateY(10px);
        padding: 12px 24px;
        border-radius: 10px;
        font-size: 14px;
        font-weight: 500;
        color: white;
        z-index: 1000;
        opacity: 0;
        transition: all 0.3s;
    }
    .toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }
    .toast.success { background: var(--success); }
    .toast.error { background: var(--danger); }

    /* ===== FOOTER ===== */
    .footer {
        text-align: center;
        padding: 24px;
        color: var(--text-dim);
        font-size: 12px;
        border-top: 1px solid var(--border);
        margin-top: 48px;
    }

    /* ===== RESPONSIVE ===== */
    @media (max-width: 768px) {
        .search-row { grid-template-columns: 1fr 1fr; }
        .search-row-2 { grid-template-columns: 1fr 1fr; }
        .flight-card { grid-template-columns: 1fr; gap: 12px; }
        .flight-price { text-align: left; flex-direction: row; align-items: center; gap: 12px; }
        .pax-form { grid-template-columns: 1fr; }
        .header { padding: 12px 16px; }
        .hero h1 { font-size: 24px; }
        .chat-panel { width: calc(100vw - 32px); right: 16px; bottom: 84px; }
    }
</style>
</head>
<body>

<!-- HEADER -->
<div class="header">
    <a href="#" class="logo" id="header-logo">FLIGHTS</a>
    <nav>
        <a href="#" class="active" onclick="showPage('search')">Search</a>
        <a href="#" onclick="showPage('mybookings')">My Bookings</a>
    </nav>
</div>

<!-- SEARCH PAGE -->
<div id="page-search">
    <div class="hero">
        <h1 id="hero-title">Find Your Flight</h1>
        <p>Search across hundreds of airlines for the best fares</p>
    </div>

    <div class="search-form">
        <div class="search-row">
            <div class="field">
                <label>From</label>
                <input type="text" id="s-origin" placeholder="JFK" maxlength="3" style="text-transform:uppercase">
            </div>
            <div class="field">
                <label>To</label>
                <input type="text" id="s-dest" placeholder="LHR" maxlength="3" style="text-transform:uppercase">
            </div>
            <div class="field">
                <label>Depart</label>
                <input type="date" id="s-depart">
            </div>
            <div class="field">
                <label>Return</label>
                <input type="date" id="s-return" placeholder="One-way">
            </div>
            <button class="search-btn" id="search-btn" onclick="searchFlights()">Search</button>
        </div>
        <div class="search-row-2">
            <div class="field">
                <label>Adults</label>
                <select id="s-adults">
                    <option value="1" selected>1</option>
                    <option value="2">2</option>
                    <option value="3">3</option>
                    <option value="4">4</option>
                </select>
            </div>
            <div class="field">
                <label>Children</label>
                <select id="s-children">
                    <option value="0" selected>0</option>
                    <option value="1">1</option>
                    <option value="2">2</option>
                    <option value="3">3</option>
                </select>
            </div>
            <div class="field">
                <label>Infants</label>
                <select id="s-infants">
                    <option value="0" selected>0</option>
                    <option value="1">1</option>
                </select>
            </div>
            <div class="field">
                <label>Cabin</label>
                <select id="s-cabin">
                    <option value="ECONOMY">Economy</option>
                    <option value="PREMIUM_ECONOMY">Premium Economy</option>
                    <option value="BUSINESS">Business</option>
                    <option value="FIRST">First</option>
                </select>
            </div>
            <div class="field">
                <label>Nonstop</label>
                <select id="s-nonstop">
                    <option value="false">Any</option>
                    <option value="true">Nonstop only</option>
                </select>
            </div>
        </div>
    </div>

    <div class="results-section" id="results-section" style="display:none">
        <div class="results-header">
            <h2 id="results-title">Results</h2>
            <span class="count" id="results-count"></span>
        </div>
        <div class="sort-bar">
            <button class="sort-btn active" onclick="sortResults('price', this)">Price</button>
            <button class="sort-btn" onclick="sortResults('duration', this)">Duration</button>
            <button class="sort-btn" onclick="sortResults('departure', this)">Departure</button>
        </div>
        <div id="results-list"></div>
    </div>
</div>

<!-- BOOKING PAGE -->
<div id="page-booking" style="display:none">
    <div class="booking-section">
        <div class="booking-card">
            <h2>Selected Flight</h2>
            <div id="booking-flight-summary"></div>
        </div>

        <div class="booking-card" id="pax-section">
            <h2>Passenger Details</h2>
            <div id="pax-forms"></div>
        </div>

        <div class="booking-card">
            <h2>Price Summary</h2>
            <div id="booking-price-summary"></div>
            <button class="book-btn" id="book-btn" onclick="confirmBooking()">Confirm Booking</button>
        </div>
    </div>
</div>

<!-- CONFIRMATION PAGE -->
<div id="page-confirmation" style="display:none">
    <div class="confirmation">
        <div class="check">&#10003;</div>
        <h1 style="font-family:var(--heading-font); margin-bottom:8px">Booking Confirmed</h1>
        <p style="color:var(--text-dim); margin-bottom:24px">Your flight has been booked successfully</p>
        <div class="pnr-box">
            <div class="label">Confirmation Code</div>
            <div class="code" id="confirm-pnr">—</div>
        </div>
        <div id="confirm-details" style="max-width:500px; margin:24px auto; text-align:left"></div>
        <button class="search-btn" onclick="showPage('search')" style="margin-top:24px">Search Another Flight</button>
    </div>
</div>

<!-- MY BOOKINGS PAGE -->
<div id="page-mybookings" style="display:none">
    <div class="booking-section">
        <div class="booking-card">
            <h2>Look Up Booking</h2>
            <div class="pax-form">
                <div class="field">
                    <label>PNR / Confirmation Code</label>
                    <input type="text" id="lookup-pnr" placeholder="ABC123" style="text-transform:uppercase">
                </div>
                <div class="field" style="justify-content:flex-end">
                    <button class="search-btn" onclick="lookupBooking()">Look Up</button>
                </div>
            </div>
        </div>
        <div id="lookup-results"></div>
    </div>
</div>

<!-- AI CHAT WIDGET -->
<button class="chat-toggle" id="chat-toggle" onclick="toggleChat()" title="ANASTASiA">&#9993;</button>
<div class="chat-panel" id="chat-panel">
    <div class="chat-header">
        <span id="chat-title">ANASTASiA</span>
        <span style="cursor:pointer; color:var(--text-dim)" onclick="toggleChat()">&times;</span>
    </div>
    <div class="chat-messages" id="chat-messages">
        <div class="chat-msg assistant">Hi! I'm ANASTASiA. I can help you search for flights, check fare rules, or answer any travel questions. What are you looking for?</div>
    </div>
    <div class="chat-input-row">
        <input type="text" id="chat-input" placeholder="Ask about flights..." onkeydown="if(event.key==='Enter')sendChat()">
        <button onclick="sendChat()">Send</button>
    </div>
</div>

<div class="footer" id="footer-text"></div>
<div class="toast" id="toast"></div>

<script>
// ===== CONFIG =====
const API_BASE = window.OTA_API_BASE || '';
const API_KEY = window.OTA_API_KEY || '';
const headers = {'Authorization': 'Bearer ' + API_KEY, 'Content-Type': 'application/json'};

let config = {};
let currentResults = [];
let currentSearchId = '';
let selectedFlight = null;
let chatSessionId = null;

// ===== INIT =====
async function init() {
    try {
        const r = await fetch(API_BASE + '/api/v1/embed/config', {headers});
        config = await r.json();
        applyBranding(config);
    } catch (e) {
        console.warn('Config load failed:', e);
    }
    // Set default departure date to tomorrow
    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    document.getElementById('s-depart').value = tomorrow.toISOString().split('T')[0];
}

function applyBranding(cfg) {
    const b = cfg.branding || {};
    const name = b.company_name || 'Flight Search';
    document.getElementById('page-title').textContent = name;
    document.getElementById('header-logo').textContent = name.toUpperCase();
    document.getElementById('hero-title').textContent = 'Find Your Flight';
    document.getElementById('chat-title').textContent = 'ANASTASiA';
    if (b.logo_url) {
        const logo = document.getElementById('header-logo');
        logo.innerHTML = '<img src="' + b.logo_url + '" alt=""> ' + name.toUpperCase();
    }
    if (b.favicon_url) document.getElementById('favicon').href = b.favicon_url;
    if (b.primary_color) document.documentElement.style.setProperty('--primary', b.primary_color);
    if (b.accent_color) {
        document.documentElement.style.setProperty('--accent', b.accent_color);
        document.documentElement.style.setProperty('--accent-hover', b.accent_color + 'cc');
    }
    if (b.heading_font) document.documentElement.style.setProperty('--heading-font', "'" + b.heading_font + "', serif");
    if (b.body_font) document.documentElement.style.setProperty('--body-font', "'" + b.body_font + "', sans-serif");
    const footer = b.footer_text || ('&copy; ' + new Date().getFullYear() + ' ' + name);
    document.getElementById('footer-text').innerHTML = footer;

    // Hide chat if disabled
    if (cfg.features && !cfg.features.ai_chat) {
        document.getElementById('chat-toggle').style.display = 'none';
    }
}

// ===== PAGE NAVIGATION =====
function showPage(name) {
    ['search','booking','confirmation','mybookings'].forEach(p => {
        document.getElementById('page-' + p).style.display = (p === name) ? 'block' : 'none';
    });
    document.querySelectorAll('.header nav a').forEach(a => a.classList.remove('active'));
}

// ===== SEARCH =====
async function searchFlights() {
    const origin = document.getElementById('s-origin').value.trim().toUpperCase();
    const dest = document.getElementById('s-dest').value.trim().toUpperCase();
    const depart = document.getElementById('s-depart').value;
    if (!origin || !dest || !depart) { showToast('Please fill in origin, destination, and departure date', 'error'); return; }

    const btn = document.getElementById('search-btn');
    btn.disabled = true;
    btn.textContent = 'Searching...';

    const section = document.getElementById('results-section');
    section.style.display = 'block';
    document.getElementById('results-list').innerHTML =
        '<div class="skeleton-card"></div><div class="skeleton-card"></div><div class="skeleton-card"></div>';

    const body = {
        origin, destination: dest, departure_date: depart,
        return_date: document.getElementById('s-return').value || null,
        adults: parseInt(document.getElementById('s-adults').value),
        children: parseInt(document.getElementById('s-children').value),
        infants: parseInt(document.getElementById('s-infants').value),
        cabin_class: document.getElementById('s-cabin').value,
        nonstop_only: document.getElementById('s-nonstop').value === 'true',
        max_results: 20,
        sort: 'price',
    };

    try {
        const r = await fetch(API_BASE + '/api/v1/search/flights', {method: 'POST', headers, body: JSON.stringify(body)});
        const data = await r.json();
        if (!data.success) throw new Error(data.error || 'Search failed');
        currentResults = data.flights || [];
        currentSearchId = data.fare_search_id;
        document.getElementById('results-title').textContent = origin + ' → ' + dest;
        document.getElementById('results-count').textContent = data.total_results + ' flights found';
        renderResults(currentResults);
    } catch (e) {
        document.getElementById('results-list').innerHTML = '<div class="loading">' + e.message + '</div>';
    }
    btn.disabled = false;
    btn.textContent = 'Search';
}

function renderResults(flights) {
    const list = document.getElementById('results-list');
    if (!flights.length) { list.innerHTML = '<div class="loading">No flights found. Try different dates or airports.</div>'; return; }

    const d = config.display || {};
    const sym = d.currency_symbol || '$';

    list.innerHTML = flights.map((f, i) => {
        const dep = f.departure_time || '--:--';
        const arr = f.arrival_time || '--:--';
        const dur = f.duration_formatted || (f.duration_minutes ? Math.floor(f.duration_minutes/60)+'h '+f.duration_minutes%60+'m' : '—');
        const stops = f.stops === 0 ? 'Nonstop' : f.stops + ' stop' + (f.stops > 1 ? 's' : '');
        const price = f.consumer_price || f.price || 0;
        const bag = f.baggage || 'N/A';
        const fare = f.fare_family || '';

        let savingsHtml = '';
        if (d.show_savings !== false && f.savings_vs_benchmark > 0) {
            savingsHtml = '<div class="savings">Save ' + sym + f.savings_vs_benchmark.toFixed(0) + '</div>';
        }
        let benchHtml = '';
        if (d.show_benchmark_price !== false && f.savings_vs_benchmark > 0) {
            benchHtml = '<div class="benchmark">' + sym + (price + f.savings_vs_benchmark).toFixed(0) + '</div>';
        }

        let tagsHtml = '';
        if (d.show_baggage !== false) tagsHtml += '<span class="tag">' + bag + '</span>';
        if (d.show_fare_family !== false && fare) tagsHtml += '<span class="tag">' + fare + '</span>';
        if (f.cancellation_policy === 'POSSIBLE') tagsHtml += '<span class="tag good">Refundable</span>';
        if (f.cancellation_policy === 'NOT_POSSIBLE') tagsHtml += '<span class="tag warn">Non-refundable</span>';

        return '<div class="flight-card" onclick="selectFlight('+i+')">' +
            '<div class="flight-route">' +
                '<div class="flight-airline">' + (f.airline || 'Airline') + '</div>' +
                '<div class="flight-times">' +
                    '<span>' + dep + '</span>' +
                    '<div class="flight-arrow-container"><div class="flight-arrow"><div class="flight-stops">' + stops + '</div></div></div>' +
                    '<span>' + arr + '</span>' +
                '</div>' +
                '<div class="flight-meta"><span>' + dur + '</span></div>' +
            '</div>' +
            '<div class="flight-details"><div class="flight-tags">' + tagsHtml + '</div></div>' +
            '<div class="flight-price">' +
                benchHtml + savingsHtml +
                '<div class="amount">' + sym + price.toFixed(0) + '</div>' +
                '<div class="per-pax">per person</div>' +
                '<button class="select-btn">Select</button>' +
            '</div></div>';
    }).join('');
}

function sortResults(by, el) {
    document.querySelectorAll('.sort-btn').forEach(b => b.classList.remove('active'));
    el.classList.add('active');
    const sorted = [...currentResults];
    if (by === 'price') sorted.sort((a,b) => (a.consumer_price||a.price||0) - (b.consumer_price||b.price||0));
    else if (by === 'duration') sorted.sort((a,b) => (a.duration_minutes||9999) - (b.duration_minutes||9999));
    else if (by === 'departure') sorted.sort((a,b) => (a.departure_time||'').localeCompare(b.departure_time||''));
    renderResults(sorted);
}

// ===== BOOKING FLOW =====
function selectFlight(idx) {
    selectedFlight = currentResults[idx];
    showPage('booking');

    const f = selectedFlight;
    const sym = (config.display || {}).currency_symbol || '$';
    const price = f.consumer_price || f.price || 0;
    const dep = f.departure_time || '--:--';
    const arr = f.arrival_time || '--:--';

    document.getElementById('booking-flight-summary').innerHTML =
        '<div class="booking-summary"><span>' + (f.airline||'Airline') + '</span><span class="val">' + dep + ' → ' + arr + '</span></div>' +
        '<div class="booking-summary"><span>Duration</span><span class="val">' + (f.duration_formatted || '—') + '</span></div>' +
        '<div class="booking-summary"><span>Stops</span><span class="val">' + (f.stops === 0 ? 'Nonstop' : f.stops) + '</span></div>' +
        '<div class="booking-summary"><span>Cabin</span><span class="val">' + (f.cabin_class || 'Economy') + '</span></div>' +
        '<div class="booking-summary"><span>Baggage</span><span class="val">' + (f.baggage || 'N/A') + '</span></div>';

    // Build passenger forms
    const adults = parseInt(document.getElementById('s-adults').value) || 1;
    const children = parseInt(document.getElementById('s-children').value) || 0;
    const infants = parseInt(document.getElementById('s-infants').value) || 0;
    let formsHtml = '';
    let paxNum = 0;
    for (let i = 0; i < adults; i++) {
        formsHtml += paxFormHtml(paxNum++, 'Adult ' + (i+1), 'ADT');
    }
    for (let i = 0; i < children; i++) {
        formsHtml += paxFormHtml(paxNum++, 'Child ' + (i+1), 'CHD');
    }
    for (let i = 0; i < infants; i++) {
        formsHtml += paxFormHtml(paxNum++, 'Infant ' + (i+1), 'INF');
    }
    document.getElementById('pax-forms').innerHTML = formsHtml;

    const totalPax = adults + children + infants;
    document.getElementById('booking-price-summary').innerHTML =
        '<div class="booking-summary"><span>Price per person</span><span class="val">' + sym + price.toFixed(2) + '</span></div>' +
        '<div class="booking-summary"><span>Passengers</span><span class="val">' + totalPax + '</span></div>' +
        '<div class="booking-summary" style="font-size:18px"><span>Total</span><span class="val" style="color:var(--success)">' + sym + (price * totalPax).toFixed(2) + '</span></div>';
}

function paxFormHtml(idx, label, paxType) {
    return '<h3>' + label + '</h3>' +
        '<input type="hidden" id="pax-type-'+idx+'" value="'+paxType+'">' +
        '<div class="pax-form">' +
            '<div class="field"><label>First Name</label><input type="text" id="pax-first-'+idx+'" required></div>' +
            '<div class="field"><label>Last Name</label><input type="text" id="pax-last-'+idx+'" required></div>' +
            '<div class="field"><label>Date of Birth</label><input type="date" id="pax-dob-'+idx+'" required></div>' +
            '<div class="field"><label>Gender</label><select id="pax-gender-'+idx+'"><option value="Male">Male</option><option value="Female">Female</option></select></div>' +
            '<div class="field"><label>Email</label><input type="email" id="pax-email-'+idx+'"></div>' +
            '<div class="field"><label>Phone</label><input type="tel" id="pax-phone-'+idx+'" placeholder="+1..."></div>' +
        '</div>';
}

async function confirmBooking() {
    const btn = document.getElementById('book-btn');
    btn.disabled = true;
    btn.textContent = 'Booking...';

    // Collect passengers
    const passengers = [];
    let idx = 0;
    while (document.getElementById('pax-type-' + idx)) {
        const first = document.getElementById('pax-first-' + idx).value.trim();
        const last = document.getElementById('pax-last-' + idx).value.trim();
        if (!first || !last) { showToast('Please fill in all passenger names', 'error'); btn.disabled = false; btn.textContent = 'Confirm Booking'; return; }
        passengers.push({
            firstName: first,
            lastName: last,
            paxType: document.getElementById('pax-type-' + idx).value,
            dateOfBirth: document.getElementById('pax-dob-' + idx).value,
            gender: document.getElementById('pax-gender-' + idx).value,
            email: document.getElementById('pax-email-' + idx).value,
            phone: document.getElementById('pax-phone-' + idx).value,
        });
        idx++;
    }

    try {
        const r = await fetch(API_BASE + '/api/v1/booking/create', {
            method: 'POST', headers,
            body: JSON.stringify({
                fare_search_id: currentSearchId,
                fare_id: selectedFlight.fare_id,
                passengers,
                order_tickets: true,
            }),
        });
        const data = await r.json();
        if (!data.success) throw new Error(data.error || 'Booking failed');

        // Show confirmation
        document.getElementById('confirm-pnr').textContent = data.pnr || data.locator || '—';
        document.getElementById('confirm-details').innerHTML =
            '<div class="booking-summary"><span>Status</span><span class="val" style="color:var(--success)">' + (data.status || 'Confirmed') + '</span></div>' +
            '<div class="booking-summary"><span>SuperPNR</span><span class="val">' + (data.super_pnr_id || '—') + '</span></div>';
        showPage('confirmation');
    } catch (e) {
        showToast(e.message, 'error');
    }
    btn.disabled = false;
    btn.textContent = 'Confirm Booking';
}

// ===== MY BOOKINGS =====
async function lookupBooking() {
    const pnr = document.getElementById('lookup-pnr').value.trim().toUpperCase();
    if (!pnr) { showToast('Enter a PNR code', 'error'); return; }

    const container = document.getElementById('lookup-results');
    container.innerHTML = '<div class="loading"><div class="spinner"></div>Looking up...</div>';

    try {
        const r = await fetch(API_BASE + '/api/v1/booking/search', {
            method: 'POST', headers,
            body: JSON.stringify({locator: pnr}),
        });
        const data = await r.json();
        if (!data.success) throw new Error(data.error || 'Lookup failed');

        const bookings = data.bookings || [];
        if (!bookings.length) { container.innerHTML = '<div class="booking-card"><p>No booking found for ' + pnr + '</p></div>'; return; }
        container.innerHTML = bookings.map(b =>
            '<div class="booking-card">' +
                '<div class="booking-summary"><span>PNR</span><span class="val">' + (b.locator || pnr) + '</span></div>' +
                '<div class="booking-summary"><span>Status</span><span class="val">' + (b.status || '—') + '</span></div>' +
                '<div class="booking-summary"><span>Route</span><span class="val">' + (b.departure || '—') + ' → ' + (b.destination || '—') + '</span></div>' +
            '</div>'
        ).join('');
    } catch (e) {
        container.innerHTML = '<div class="booking-card"><p style="color:var(--danger)">' + e.message + '</p></div>';
    }
}

// ===== AI CHAT =====
function toggleChat() {
    const panel = document.getElementById('chat-panel');
    panel.classList.toggle('open');
    if (panel.classList.contains('open')) document.getElementById('chat-input').focus();
}

async function sendChat() {
    const input = document.getElementById('chat-input');
    const msg = input.value.trim();
    if (!msg) return;
    input.value = '';

    const messages = document.getElementById('chat-messages');
    messages.innerHTML += '<div class="chat-msg user">' + escapeHtml(msg) + '</div>';
    messages.scrollTop = messages.scrollHeight;

    // Typing indicator
    const typing = document.createElement('div');
    typing.className = 'chat-msg assistant';
    typing.textContent = '...';
    typing.id = 'typing';
    messages.appendChild(typing);
    messages.scrollTop = messages.scrollHeight;

    try {
        const r = await fetch(API_BASE + '/api/v1/chat', {
            method: 'POST', headers,
            body: JSON.stringify({message: msg, session_id: chatSessionId}),
        });
        const data = await r.json();
        chatSessionId = data.session_id;
        typing.remove();
        messages.innerHTML += '<div class="chat-msg assistant">' + escapeHtml(data.response || data.error || 'No response') + '</div>';
    } catch (e) {
        typing.remove();
        messages.innerHTML += '<div class="chat-msg assistant" style="color:var(--danger)">Connection error. Please try again.</div>';
    }
    messages.scrollTop = messages.scrollHeight;
}

function escapeHtml(s) {
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ===== TOAST =====
function showToast(msg, type) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.className = 'toast ' + type + ' show';
    setTimeout(() => t.classList.remove('show'), 3000);
}

// ===== INIT =====
init();
</script>
</body>
</html>"""
