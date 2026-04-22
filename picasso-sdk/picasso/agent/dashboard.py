"""
Admin Dashboard — Visual control panel for OTA owners.

Non-technical agency owners configure their entire OTA through this UI:
- Pricing strategy, markup percentages, cabin tiers
- Display settings (what users see)
- Branding (colors, fonts, logo, company name)
- Feature toggles
- Live preview of pricing on sample fares

Served as a single HTML page — no frontend build step, no React, no npm.
Drop it into any Flask app or serve standalone.

MYSTES KYRIOS LLC — Confidential.
"""

ADMIN_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ANASTASiA — Admin Dashboard</title>
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap');
    * { margin: 0; padding: 0; box-sizing: border-box; }
    :root {
        --bg: #0f0f1a;
        --card: #1a1a2e;
        --card-hover: #22223a;
        --border: #2a2a44;
        --text: #e8e8f0;
        --text-dim: #8888aa;
        --accent: #6366f1;
        --accent-hover: #818cf8;
        --success: #22c55e;
        --warning: #f59e0b;
        --danger: #ef4444;
        --input-bg: #12121e;
    }
    body {
        font-family: 'Inter', -apple-system, sans-serif;
        background: var(--bg);
        color: var(--text);
        line-height: 1.6;
    }

    /* Header */
    .header {
        background: var(--card);
        border-bottom: 1px solid var(--border);
        padding: 16px 32px;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    .header h1 {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 20px;
        letter-spacing: 2px;
    }
    .header .agency-name {
        color: var(--accent);
        font-weight: 600;
    }
    .header .status {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 13px;
        color: var(--text-dim);
    }
    .header .status-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: var(--success);
    }

    /* Layout */
    .container {
        max-width: 1200px;
        margin: 0 auto;
        padding: 24px;
    }
    .tabs {
        display: flex;
        gap: 4px;
        margin-bottom: 24px;
        border-bottom: 1px solid var(--border);
        padding-bottom: 0;
    }
    .tab {
        padding: 12px 20px;
        cursor: pointer;
        font-size: 14px;
        font-weight: 500;
        color: var(--text-dim);
        border-bottom: 2px solid transparent;
        transition: all 0.2s;
    }
    .tab:hover { color: var(--text); }
    .tab.active {
        color: var(--accent);
        border-bottom-color: var(--accent);
    }
    .tab-content { display: none; }
    .tab-content.active { display: block; }

    /* Cards */
    .card {
        background: var(--card);
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 24px;
        margin-bottom: 20px;
    }
    .card h2 {
        font-size: 16px;
        font-weight: 600;
        margin-bottom: 16px;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .card h3 {
        font-size: 14px;
        font-weight: 600;
        margin: 16px 0 8px;
        color: var(--text-dim);
    }

    /* Form elements */
    .form-row {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 16px;
        margin-bottom: 16px;
    }
    .form-row.three { grid-template-columns: 1fr 1fr 1fr; }
    .form-group {
        display: flex;
        flex-direction: column;
        gap: 4px;
    }
    .form-group label {
        font-size: 12px;
        font-weight: 500;
        color: var(--text-dim);
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .form-group input, .form-group select {
        background: var(--input-bg);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 10px 12px;
        color: var(--text);
        font-size: 14px;
        font-family: inherit;
        outline: none;
        transition: border-color 0.2s;
    }
    .form-group input:focus, .form-group select:focus {
        border-color: var(--accent);
    }
    .form-group input[type="color"] {
        height: 42px;
        padding: 4px;
        cursor: pointer;
    }

    /* Toggle switches */
    .toggle-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 10px 0;
        border-bottom: 1px solid var(--border);
    }
    .toggle-row:last-child { border-bottom: none; }
    .toggle-label {
        font-size: 14px;
    }
    .toggle-desc {
        font-size: 12px;
        color: var(--text-dim);
    }
    .toggle {
        position: relative;
        width: 44px;
        height: 24px;
        cursor: pointer;
    }
    .toggle input { display: none; }
    .toggle .slider {
        position: absolute;
        inset: 0;
        background: var(--border);
        border-radius: 12px;
        transition: background 0.2s;
    }
    .toggle .slider::before {
        content: '';
        position: absolute;
        width: 18px;
        height: 18px;
        left: 3px;
        top: 3px;
        background: var(--text);
        border-radius: 50%;
        transition: transform 0.2s;
    }
    .toggle input:checked + .slider { background: var(--accent); }
    .toggle input:checked + .slider::before { transform: translateX(20px); }

    /* Buttons */
    .btn {
        padding: 10px 20px;
        border: none;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.2s;
        font-family: inherit;
    }
    .btn-primary {
        background: var(--accent);
        color: white;
    }
    .btn-primary:hover { background: var(--accent-hover); }
    .btn-outline {
        background: transparent;
        color: var(--accent);
        border: 1px solid var(--accent);
    }
    .btn-outline:hover { background: rgba(99,102,241,0.1); }
    .btn-row {
        display: flex;
        gap: 12px;
        justify-content: flex-end;
        margin-top: 20px;
    }

    /* Pricing preview */
    .preview-table {
        width: 100%;
        border-collapse: collapse;
        margin-top: 12px;
        font-size: 13px;
    }
    .preview-table th {
        text-align: left;
        padding: 8px 12px;
        background: var(--input-bg);
        color: var(--text-dim);
        font-weight: 500;
        border-bottom: 1px solid var(--border);
    }
    .preview-table td {
        padding: 8px 12px;
        border-bottom: 1px solid var(--border);
    }
    .preview-table .markup { color: var(--accent); font-weight: 600; }
    .preview-table .consumer { color: var(--success); font-weight: 600; }

    /* Toast */
    .toast {
        position: fixed;
        bottom: 24px;
        right: 24px;
        padding: 14px 20px;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 500;
        color: white;
        z-index: 1000;
        opacity: 0;
        transform: translateY(10px);
        transition: all 0.3s;
    }
    .toast.show { opacity: 1; transform: translateY(0); }
    .toast.success { background: var(--success); }
    .toast.error { background: var(--danger); }

    /* Responsive */
    @media (max-width: 768px) {
        .form-row, .form-row.three { grid-template-columns: 1fr; }
        .header { padding: 12px 16px; flex-direction: column; gap: 8px; }
        .container { padding: 16px; }
    }
</style>
</head>
<body>

<div class="header">
    <h1>ADMIN DASHBOARD</h1>
    <span class="agency-name" id="agencyName">Loading...</span>
    <div class="status">
        <span class="status-dot"></span>
        <span>Connected</span>
    </div>
</div>

<div class="container">
    <div class="tabs">
        <div class="tab active" onclick="switchTab('pricing')">Pricing</div>
        <div class="tab" onclick="switchTab('display')">Display</div>
        <div class="tab" onclick="switchTab('branding')">Branding</div>
        <div class="tab" onclick="switchTab('features')">Features</div>
        <div class="tab" onclick="switchTab('analytics')">Analytics</div>
        <div class="tab" onclick="switchTab('billing')">Billing</div>
        <div class="tab" onclick="switchTab('assistant')" style="background: linear-gradient(135deg, #7c3aed, #6366f1); color: #fff; border-color: #7c3aed;">ANASTASiA</div>
    </div>

    <!-- PRICING TAB -->
    <div id="tab-pricing" class="tab-content active">
        <div class="card">
            <h2>Pricing Strategy</h2>
            <div class="form-row">
                <div class="form-group">
                    <label>Strategy</label>
                    <select id="pricing-strategy" onchange="updatePreview()">
                        <option value="flat_fee">Flat Fee Per Ticket</option>
                        <option value="percent_base">Percentage of Base Fare</option>
                        <option value="percent_total" selected>Percentage of Total Fare</option>
                        <option value="savings_split">Savings Split (vs Benchmark)</option>
                        <option value="tiered">Tiered by Cabin Class</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>Display Currency</label>
                    <select id="pricing-currency">
                        <option value="USD">USD ($)</option>
                        <option value="EUR">EUR (&euro;)</option>
                        <option value="GBP">GBP (&pound;)</option>
                        <option value="MXN">MXN (Mex$)</option>
                    </select>
                </div>
            </div>
            <div class="form-row three">
                <div class="form-group">
                    <label>Markup Percentage</label>
                    <input type="number" id="pricing-percent" value="10" step="0.5" min="0" max="100" oninput="updatePreview()">
                </div>
                <div class="form-group">
                    <label>Flat Fee ($)</label>
                    <input type="number" id="pricing-flat" value="0" step="1" min="0" max="999" oninput="updatePreview()">
                </div>
                <div class="form-group">
                    <label>Savings Split %</label>
                    <input type="number" id="pricing-split" value="25" step="5" min="0" max="100" oninput="updatePreview()">
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label>Minimum Markup ($)</label>
                    <input type="number" id="pricing-min" value="3" step="1" min="0" oninput="updatePreview()">
                </div>
                <div class="form-group">
                    <label>Maximum Markup ($)</label>
                    <input type="number" id="pricing-max" value="999" step="10" min="0" oninput="updatePreview()">
                </div>
            </div>
        </div>

        <div class="card" id="tiered-section" style="display:none">
            <h2>Cabin Class Tiers</h2>
            <p style="font-size:13px; color:var(--text-dim); margin-bottom:12px">
                Override markup percentage per cabin. Leave blank to use default.
            </p>
            <div class="form-row">
                <div class="form-group">
                    <label>Economy (%)</label>
                    <input type="number" id="tier-economy" placeholder="Use default" step="0.5" oninput="updatePreview()">
                </div>
                <div class="form-group">
                    <label>Premium Economy (%)</label>
                    <input type="number" id="tier-premium" placeholder="Use default" step="0.5" oninput="updatePreview()">
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label>Business (%)</label>
                    <input type="number" id="tier-business" placeholder="Use default" step="0.5" oninput="updatePreview()">
                </div>
                <div class="form-group">
                    <label>First (%)</label>
                    <input type="number" id="tier-first" placeholder="Use default" step="0.5" oninput="updatePreview()">
                </div>
            </div>
        </div>

        <div class="card">
            <h2>Live Pricing Preview</h2>
            <p style="font-size:13px; color:var(--text-dim); margin-bottom:8px">
                How your pricing applies to sample fares:
            </p>
            <table class="preview-table">
                <thead>
                    <tr>
                        <th>Route</th>
                        <th>Cabin</th>
                        <th>Base Fare</th>
                        <th>Tax</th>
                        <th>Cost</th>
                        <th>Your Markup</th>
                        <th>Consumer Price</th>
                    </tr>
                </thead>
                <tbody id="preview-body">
                </tbody>
            </table>
        </div>

        <div class="btn-row">
            <button class="btn btn-outline" onclick="loadConfig()">Reset</button>
            <button class="btn btn-primary" onclick="savePricing()">Save Pricing</button>
        </div>
    </div>

    <!-- DISPLAY TAB -->
    <div id="tab-display" class="tab-content">
        <div class="card">
            <h2>Search Results Display</h2>
            <div class="form-row">
                <div class="form-group">
                    <label>Results Per Page</label>
                    <input type="number" id="display-rpp" value="20" min="5" max="50">
                </div>
                <div class="form-group">
                    <label>Default Sort</label>
                    <select id="display-sort">
                        <option value="price">Price (Low to High)</option>
                        <option value="duration">Duration (Shortest)</option>
                        <option value="departure">Departure Time</option>
                        <option value="arrival">Arrival Time</option>
                    </select>
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label>Time Format</label>
                    <select id="display-time">
                        <option value="12h">12-Hour (2:30 PM)</option>
                        <option value="24h">24-Hour (14:30)</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>Date Format</label>
                    <select id="display-date">
                        <option value="MMM DD, YYYY">Mar 15, 2026</option>
                        <option value="DD/MM/YYYY">15/03/2026</option>
                        <option value="YYYY-MM-DD">2026-03-15</option>
                    </select>
                </div>
            </div>
        </div>

        <div class="card">
            <h2>Visible Information</h2>
            <div class="toggle-row">
                <div><span class="toggle-label">Show Baggage Allowance</span><br><span class="toggle-desc">Display checked bag info on results</span></div>
                <label class="toggle"><input type="checkbox" id="display-baggage" checked><span class="slider"></span></label>
            </div>
            <div class="toggle-row">
                <div><span class="toggle-label">Show Fare Family</span><br><span class="toggle-desc">Display fare name (Basic Economy, Main Cabin, etc.)</span></div>
                <label class="toggle"><input type="checkbox" id="display-fare-family" checked><span class="slider"></span></label>
            </div>
            <div class="toggle-row">
                <div><span class="toggle-label">Show Fare Rules Link</span><br><span class="toggle-desc">Let users view cancellation/change policies</span></div>
                <label class="toggle"><input type="checkbox" id="display-fare-rules" checked><span class="slider"></span></label>
            </div>
            <div class="toggle-row">
                <div><span class="toggle-label">Show Seatmap Link</span><br><span class="toggle-desc">Let users check seat availability</span></div>
                <label class="toggle"><input type="checkbox" id="display-seatmap" checked><span class="slider"></span></label>
            </div>
            <div class="toggle-row">
                <div><span class="toggle-label">Show Savings Badge</span><br><span class="toggle-desc">Display "You save $X" on results</span></div>
                <label class="toggle"><input type="checkbox" id="display-savings" checked><span class="slider"></span></label>
            </div>
            <div class="toggle-row">
                <div><span class="toggle-label">Show Benchmark Price</span><br><span class="toggle-desc">Show crossed-out "was $X" reference price</span></div>
                <label class="toggle"><input type="checkbox" id="display-benchmark" checked><span class="slider"></span></label>
            </div>
            <div class="toggle-row">
                <div><span class="toggle-label">Show GDS Source</span><br><span class="toggle-desc">Display distribution channel (Amadeus, Sabre, NDC)</span></div>
                <label class="toggle"><input type="checkbox" id="display-gds"><span class="slider"></span></label>
            </div>
        </div>
        <div class="btn-row">
            <button class="btn btn-outline" onclick="loadConfig()">Reset</button>
            <button class="btn btn-primary" onclick="saveDisplay()">Save Display Settings</button>
        </div>
    </div>

    <!-- BRANDING TAB -->
    <div id="tab-branding" class="tab-content">
        <div class="card">
            <h2>Company Identity</h2>
            <div class="form-row">
                <div class="form-group">
                    <label>Company Name</label>
                    <input type="text" id="brand-name" placeholder="Your Travel Company">
                </div>
                <div class="form-group">
                    <label>Logo URL</label>
                    <input type="text" id="brand-logo" placeholder="https://...">
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label>Support Email</label>
                    <input type="email" id="brand-email" placeholder="support@youragency.com">
                </div>
                <div class="form-group">
                    <label>Support Phone</label>
                    <input type="text" id="brand-phone" placeholder="+1 (555) 123-4567">
                </div>
            </div>
            <div class="form-group" style="margin-top:8px">
                <label>Footer Text</label>
                <input type="text" id="brand-footer" placeholder="&copy; 2026 Your Travel Company. All rights reserved.">
            </div>
        </div>

        <div class="card">
            <h2>Visual Theme</h2>
            <div class="form-row three">
                <div class="form-group">
                    <label>Primary Color</label>
                    <input type="color" id="brand-primary" value="#1a1a2e">
                </div>
                <div class="form-group">
                    <label>Accent Color</label>
                    <input type="color" id="brand-accent" value="#6366f1">
                </div>
                <div class="form-group">
                    <label>Favicon URL</label>
                    <input type="text" id="brand-favicon" placeholder="https://...">
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label>Heading Font</label>
                    <select id="brand-heading-font">
                        <option value="Space Grotesk">Space Grotesk (Geometric)</option>
                        <option value="Inter">Inter (Sans-serif)</option>
                        <option value="Playfair Display">Playfair Display (Serif)</option>
                        <option value="Montserrat">Montserrat (Sans-serif)</option>
                        <option value="Poppins">Poppins (Sans-serif)</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>Body Font</label>
                    <select id="brand-body-font">
                        <option value="Outfit">Outfit (Sans-serif)</option>
                        <option value="Inter">Inter (Sans-serif)</option>
                        <option value="Roboto">Roboto (Sans-serif)</option>
                        <option value="Lato">Lato (Sans-serif)</option>
                        <option value="Open Sans">Open Sans (Sans-serif)</option>
                    </select>
                </div>
            </div>
        </div>
        <div class="btn-row">
            <button class="btn btn-outline" onclick="loadConfig()">Reset</button>
            <button class="btn btn-primary" onclick="saveBranding()">Save Branding</button>
        </div>
    </div>

    <!-- FEATURES TAB -->
    <div id="tab-features" class="tab-content">
        <div class="card">
            <h2>Capabilities</h2>
            <div class="toggle-row">
                <div><span class="toggle-label">AI Chat Agent</span><br><span class="toggle-desc">Conversational booking assistant for your staff</span></div>
                <label class="toggle"><input type="checkbox" id="feat-chat" checked><span class="slider"></span></label>
            </div>
            <div class="toggle-row">
                <div><span class="toggle-label">Structured Search API</span><br><span class="toggle-desc">Form-based flight search for your app UI</span></div>
                <label class="toggle"><input type="checkbox" id="feat-search" checked><span class="slider"></span></label>
            </div>
            <div class="toggle-row">
                <div><span class="toggle-label">Booking Enabled</span><br><span class="toggle-desc">Allow creating actual bookings (disable for search-only mode)</span></div>
                <label class="toggle"><input type="checkbox" id="feat-booking" checked><span class="slider"></span></label>
            </div>
            <div class="toggle-row">
                <div><span class="toggle-label">Document Generation</span><br><span class="toggle-desc">Generate itineraries, confirmations, and offers as PDF</span></div>
                <label class="toggle"><input type="checkbox" id="feat-docs" checked><span class="slider"></span></label>
            </div>
            <div class="toggle-row">
                <div><span class="toggle-label">Seatmap Lookup</span><br><span class="toggle-desc">Let users check seat availability before booking</span></div>
                <label class="toggle"><input type="checkbox" id="feat-seatmap" checked><span class="slider"></span></label>
            </div>
            <div class="toggle-row">
                <div><span class="toggle-label">Booking Management</span><br><span class="toggle-desc">Search and view existing bookings by PNR</span></div>
                <label class="toggle"><input type="checkbox" id="feat-management" checked><span class="slider"></span></label>
            </div>
        </div>

        <div class="card">
            <h2>Rate Limits</h2>
            <div class="form-row">
                <div class="form-group">
                    <label>Max Daily Searches (0 = unlimited)</label>
                    <input type="number" id="feat-max-searches" value="0" min="0">
                </div>
                <div class="form-group">
                    <label>Max Daily Bookings (0 = unlimited)</label>
                    <input type="number" id="feat-max-bookings" value="0" min="0">
                </div>
            </div>
        </div>
        <div class="btn-row">
            <button class="btn btn-outline" onclick="loadConfig()">Reset</button>
            <button class="btn btn-primary" onclick="saveFeatures()">Save Features</button>
        </div>
    </div>

    <!-- ANALYTICS TAB -->
    <div id="tab-analytics" class="tab-content">
        <div class="card">
            <h2>Usage & Analytics</h2>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:16px;margin-bottom:24px;">
                <div style="background:var(--input-bg);border-radius:10px;padding:20px;text-align:center;">
                    <div style="font-size:12px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;">AI Requests</div>
                    <div style="font-size:32px;font-weight:600;" id="anMetricAi">—</div>
                    <div style="font-size:11px;color:var(--text-dim);margin-top:4px;" id="anMetricAiLimit">/ — limit</div>
                    <div style="height:4px;background:var(--border);border-radius:2px;margin-top:12px;overflow:hidden;"><div id="anBarAi" style="height:100%;width:0%;background:linear-gradient(90deg,var(--accent),#a855f7);border-radius:2px;transition:width 0.5s;"></div></div>
                </div>
                <div style="background:var(--input-bg);border-radius:10px;padding:20px;text-align:center;">
                    <div style="font-size:12px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;">Searches</div>
                    <div style="font-size:32px;font-weight:600;" id="anMetricSearches">—</div>
                    <div style="font-size:11px;color:var(--text-dim);margin-top:4px;" id="anAvgSearches">— avg/day</div>
                </div>
                <div style="background:var(--input-bg);border-radius:10px;padding:20px;text-align:center;">
                    <div style="font-size:12px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;">Bookings</div>
                    <div style="font-size:32px;font-weight:600;" id="anMetricBookings">—</div>
                    <div style="font-size:11px;color:var(--text-dim);margin-top:4px;" id="anAvgBookings">— avg/day</div>
                </div>
                <div style="background:var(--input-bg);border-radius:10px;padding:20px;text-align:center;">
                    <div style="font-size:12px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;">Error Rate</div>
                    <div style="font-size:32px;font-weight:600;" id="anMetricErrors">—</div>
                    <div style="font-size:11px;color:var(--text-dim);margin-top:4px;" id="anTotalErrors">— total errors</div>
                </div>
            </div>
        </div>
        <div class="card">
            <h2>Current Period Cost</h2>
            <div style="display:flex;flex-direction:column;gap:8px;">
                <div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border);font-size:14px;">
                    <span style="color:var(--text-dim);">Base Plan</span><span id="anCostBase">$—</span>
                </div>
                <div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border);font-size:14px;">
                    <span style="color:var(--text-dim);">Overage (<span id="anOverageCount">0</span> requests)</span><span id="anCostOverage">$—</span>
                </div>
                <div style="display:flex;justify-content:space-between;padding:12px 0 0;font-size:16px;font-weight:600;border-top:1px solid var(--accent);">
                    <span>Estimated Total</span><span id="anCostTotal">$—</span>
                </div>
            </div>
        </div>
        <div class="card">
            <h2>Error Breakdown</h2>
            <div id="anErrorCats" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px;">
                <div style="color:var(--text-dim);font-size:13px;">Loading...</div>
            </div>
        </div>
        <div class="card">
            <h2>Recent Errors</h2>
            <div id="anErrorLog" style="max-height:200px;overflow-y:auto;font-size:12px;font-family:monospace;color:var(--text-dim);">
                <div>No errors recorded.</div>
            </div>
        </div>
    </div>

    <!-- BILLING TAB -->
    <div id="tab-billing" class="tab-content">
        <div class="card">
            <h2>Subscription</h2>
            <div style="display:flex;gap:24px;align-items:flex-start;flex-wrap:wrap;">
                <div style="flex:1;min-width:250px;">
                    <div style="font-size:13px;color:var(--text-dim);margin-bottom:4px;">Current Plan</div>
                    <div style="font-size:24px;font-weight:600;font-family:'Space Grotesk',sans-serif;" id="blPlanName">—</div>
                    <div style="font-size:14px;color:var(--text-dim);margin-top:4px;" id="blPlanPrice">—</div>
                    <div style="margin-top:12px;font-size:13px;color:var(--text-dim);" id="blPlanStatus">—</div>
                </div>
                <div style="flex:1;min-width:250px;">
                    <div style="font-size:13px;color:var(--text-dim);margin-bottom:8px;">Usage This Period</div>
                    <div id="blUsageBars"></div>
                </div>
            </div>
        </div>
        <div class="card">
            <h2>Available Plans</h2>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;" id="blPlanCards"></div>
        </div>
        <div class="card">
            <h2>Billing History</h2>
            <div id="blHistory" style="font-size:13px;color:var(--text-dim);">
                <div>Usage history will appear here after your first billing period.</div>
            </div>
        </div>
    </div>

    <!-- ANASTASIA TERMINAL (UNIFIED) -->
    <div id="tab-assistant" class="tab-content">
        <div class="card" style="padding: 0; overflow: hidden; height: calc(100vh - 180px); display: grid; grid-template-columns: 260px 1fr;">
            <!-- Session Sidebar -->
            <div style="background: var(--card); border-right: 1px solid var(--border); display: flex; flex-direction: column;">
                <div style="padding: 16px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center;">
                    <h3 style="font-size: 14px; font-family: 'Space Grotesk', sans-serif;">Sessions</h3>
                    <button class="btn btn-primary" onclick="uniNewSession()" style="padding: 4px 12px; font-size: 11px;">+ New</button>
                </div>
                <div id="uni-sessions" style="flex: 1; overflow-y: auto; padding: 8px;"></div>
                <div style="padding: 12px; border-top: 1px solid var(--border); font-size: 11px; color: var(--text-dim);">
                    Total queries: <strong id="uni-total-queries" style="color: var(--accent);">0</strong>
                </div>
            </div>

            <!-- Main Chat Area -->
            <div style="display: flex; flex-direction: column; background: var(--bg);">
                <!-- Chat Header -->
                <div style="padding: 12px 20px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; flex-shrink: 0;">
                    <div style="display: flex; align-items: center; gap: 10px;">
                        <h2 style="font-size: 16px; margin-bottom: 0;">ANASTASiA</h2>
                        <span id="uni-session-title" style="font-size: 12px; color: var(--text-dim);"></span>
                        <span id="uni-session-badge" style="display: none; font-size: 10px; padding: 2px 8px; border-radius: 4px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; background: rgba(99,102,241,0.15); color: #818cf8;">dev</span>
                    </div>
                    <div style="display: flex; gap: 8px; align-items: center;">
                        <span id="uni-session-queries" style="font-size: 11px; color: var(--text-dim); padding: 4px 10px; background: var(--input-bg); border-radius: 6px;">0 queries</span>
                        <button class="btn" onclick="uniCloseSession()" style="padding: 6px 14px; font-size: 12px; background: transparent; border: 1px solid var(--border);">Close</button>
                    </div>
                </div>

                <!-- Chat Messages -->
                <div id="uni-messages" style="flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 16px;">
                    <div class="assist-msg assist-system">
                        <div style="font-size: 13px; color: var(--text-dim); line-height: 1.6;">
                            <strong style="color: var(--accent);">ANASTASiA Terminal</strong> — Your AI architect for everything.<br>
                            I know your turnkey model inside and out. I can:
                            <ul style="margin: 8px 0 0 16px; list-style: disc;">
                                <li><strong>Troubleshoot</strong> — API integration, pricing config, error diagnostics</li>
                                <li><strong>Build</strong> — Custom modules, webhook handlers, SDK extensions</li>
                                <li><strong>Configure</strong> — Pricing, branding, features, credentials</li>
                                <li><strong>Search</strong> — "Find JFK to LHR next Tuesday, business class"</li>
                                <li><strong>Deploy</strong> — Audit, test, and publish your custom code</li>
                                <li><strong>Network</strong> — Credential vault status, connection health</li>
                            </ul>
                        </div>
                    </div>
                </div>

                <!-- Quick Actions -->
                <div style="padding: 8px 20px; border-top: 1px solid rgba(255,255,255,0.04); display: flex; gap: 6px; flex-wrap: wrap; flex-shrink: 0;">
                    <button class="assist-quick" onclick="uniSend('Run integration health check')">Health Check</button>
                    <button class="assist-quick" onclick="uniSend('Show my current pricing config')">Pricing Config</button>
                    <button class="assist-quick" onclick="uniSend('Show me how to integrate the search widget')">Integration Guide</button>
                    <button class="assist-quick" onclick="uniSend('I want to create a new custom module')">Scaffold Module</button>
                    <button class="assist-quick" onclick="uniSend('List my custom modules')">My Modules</button>
                    <button class="assist-quick" onclick="uniSend('Show my credential vault status')">Vault Status</button>
                    <button class="assist-quick" onclick="uniSend('Generate a webhook handler for booking notifications')">Build Webhook</button>
                </div>

                <!-- Input Area -->
                <div style="padding: 12px 20px 16px; border-top: 1px solid var(--border); flex-shrink: 0;">
                    <div style="display: flex; gap: 8px;">
                        <textarea id="uni-input" rows="2" placeholder="Build features, troubleshoot, configure — everything happens here..."
                            style="flex: 1; padding: 10px 14px; background: var(--input-bg); border: 1px solid var(--border); border-radius: 8px; color: var(--text); font-family: inherit; font-size: 13px; resize: none; outline: none;"
                            onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();uniSendFromInput()}"></textarea>
                        <button class="btn btn-primary" onclick="uniSendFromInput()" id="uni-send-btn"
                            style="padding: 10px 20px; align-self: flex-end;">Send</button>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>

<style>
    .assist-msg {
        max-width: 85%;
        padding: 12px 16px;
        border-radius: 12px;
        font-size: 13px;
        line-height: 1.6;
        word-wrap: break-word;
    }
    .assist-msg.assist-user {
        align-self: flex-end;
        background: var(--accent);
        color: #fff;
        border-bottom-right-radius: 4px;
    }
    .assist-msg.assist-bot {
        align-self: flex-start;
        background: var(--card-hover);
        border: 1px solid var(--border);
        border-bottom-left-radius: 4px;
    }
    .assist-msg.assist-system {
        align-self: center;
        background: rgba(99, 102, 241, 0.08);
        border: 1px solid rgba(99, 102, 241, 0.15);
        max-width: 95%;
    }
    .assist-msg pre {
        background: #0a0a14;
        border: 1px solid var(--border);
        border-radius: 6px;
        padding: 10px 14px;
        margin: 8px 0;
        overflow-x: auto;
        font-size: 12px;
        line-height: 1.5;
    }
    .assist-msg code {
        background: rgba(255,255,255,0.08);
        padding: 1px 5px;
        border-radius: 3px;
        font-size: 12px;
    }
    .assist-msg pre code {
        background: none;
        padding: 0;
    }
    .assist-msg ul, .assist-msg ol {
        margin: 6px 0 6px 18px;
    }
    .assist-msg strong {
        color: #fff;
    }
    .assist-quick {
        padding: 4px 12px;
        font-size: 11px;
        background: var(--input-bg);
        border: 1px solid var(--border);
        color: var(--text-dim);
        border-radius: 14px;
        cursor: pointer;
        transition: all 0.2s;
    }
    .assist-quick:hover {
        background: var(--card-hover);
        color: var(--text);
        border-color: var(--accent);
    }
    .assist-typing {
        align-self: flex-start;
        padding: 12px 16px;
        background: var(--card-hover);
        border: 1px solid var(--border);
        border-radius: 12px;
        border-bottom-left-radius: 4px;
        font-size: 13px;
        color: var(--text-dim);
    }
    .assist-typing .dots span {
        animation: blink 1.4s infinite;
        animation-fill-mode: both;
        font-size: 18px;
    }
    .assist-typing .dots span:nth-child(2) { animation-delay: 0.2s; }
    .assist-typing .dots span:nth-child(3) { animation-delay: 0.4s; }
    @keyframes blink { 0%,80%,100% { opacity: 0; } 40% { opacity: 1; } }
</style>

<div class="toast" id="toast"></div>

<script>
const API_BASE = window.ADMIN_API_BASE || '';
const API_KEY = window.ADMIN_API_KEY || '';
const headers = {
    'Authorization': 'Bearer ' + API_KEY,
    'Content-Type': 'application/json',
};

// Tab switching
function switchTab(name) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    event.target.classList.add('active');
    document.getElementById('tab-' + name).classList.add('active');
}

// Toast notifications
function showToast(msg, type) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.className = 'toast ' + type + ' show';
    setTimeout(() => t.classList.remove('show'), 3000);
}

// Load current config
async function loadConfig() {
    try {
        const r = await fetch(API_BASE + '/api/v1/admin/config', {headers});
        const data = await r.json();

        document.getElementById('agencyName').textContent = data.agency_name || 'Agency';

        // Pricing
        if (data.pricing) {
            const p = data.pricing;
            document.getElementById('pricing-strategy').value = p.strategy || 'percent_total';
            document.getElementById('pricing-percent').value = p.markup_percent || 10;
            document.getElementById('pricing-flat').value = p.markup_flat || 0;
            document.getElementById('pricing-split').value = p.savings_split_percent || 25;
            document.getElementById('pricing-min').value = p.min_markup || 0;
            document.getElementById('pricing-max').value = p.max_markup || 999;
            document.getElementById('pricing-currency').value = p.display_currency || 'USD';
            if (p.cabin_tiers) {
                if (p.cabin_tiers.ECONOMY) document.getElementById('tier-economy').value = p.cabin_tiers.ECONOMY.percent;
                if (p.cabin_tiers.PREMIUM_ECONOMY) document.getElementById('tier-premium').value = p.cabin_tiers.PREMIUM_ECONOMY.percent;
                if (p.cabin_tiers.BUSINESS) document.getElementById('tier-business').value = p.cabin_tiers.BUSINESS.percent;
                if (p.cabin_tiers.FIRST) document.getElementById('tier-first').value = p.cabin_tiers.FIRST.percent;
            }
        }

        // Display
        if (data.display) {
            const d = data.display;
            document.getElementById('display-rpp').value = d.results_per_page || 20;
            document.getElementById('display-sort').value = d.default_sort || 'price';
            document.getElementById('display-time').value = d.time_format || '12h';
            document.getElementById('display-date').value = d.date_format || 'MMM DD, YYYY';
            document.getElementById('display-baggage').checked = d.show_baggage !== false;
            document.getElementById('display-fare-family').checked = d.show_fare_family !== false;
            document.getElementById('display-fare-rules').checked = d.show_fare_rules_link !== false;
            document.getElementById('display-seatmap').checked = d.show_seatmap_link !== false;
            document.getElementById('display-savings').checked = d.show_savings !== false;
            document.getElementById('display-benchmark').checked = d.show_benchmark_price !== false;
            document.getElementById('display-gds').checked = d.show_gds_source === true;
        }

        // Branding
        if (data.branding) {
            const b = data.branding;
            document.getElementById('brand-name').value = b.company_name || '';
            document.getElementById('brand-logo').value = b.logo_url || '';
            document.getElementById('brand-email').value = b.support_email || '';
            document.getElementById('brand-phone').value = b.support_phone || '';
            document.getElementById('brand-footer').value = b.footer_text || '';
            document.getElementById('brand-primary').value = b.primary_color || '#1a1a2e';
            document.getElementById('brand-accent').value = b.accent_color || '#6366f1';
            document.getElementById('brand-favicon').value = b.favicon_url || '';
            document.getElementById('brand-heading-font').value = b.heading_font || 'Space Grotesk';
            document.getElementById('brand-body-font').value = b.body_font || 'Outfit';
        }

        // Features
        if (data.features) {
            const f = data.features;
            document.getElementById('feat-chat').checked = f.ai_chat !== false;
            document.getElementById('feat-search').checked = f.structured_search !== false;
            document.getElementById('feat-booking').checked = f.booking_enabled !== false;
            document.getElementById('feat-docs').checked = f.document_generation !== false;
            document.getElementById('feat-seatmap').checked = f.seatmap !== false;
            document.getElementById('feat-management').checked = f.booking_management !== false;
            document.getElementById('feat-max-searches').value = f.max_daily_searches || 0;
            document.getElementById('feat-max-bookings').value = f.max_daily_bookings || 0;
        }

        updatePreview();
    } catch (e) {
        showToast('Failed to load config: ' + e.message, 'error');
    }
}

// Pricing preview
const SAMPLE_FARES = [
    {route: 'JFK → LHR', cabin: 'ECONOMY', base: 131, tax: 199, fee: 0},
    {route: 'LAX → CDG', cabin: 'ECONOMY', base: 280, tax: 220, fee: 10},
    {route: 'MIA → LHR', cabin: 'BUSINESS', base: 1800, tax: 350, fee: 15},
    {route: 'JFK → NRT', cabin: 'FIRST', base: 4500, tax: 400, fee: 20},
    {route: 'JFK → LAX', cabin: 'ECONOMY', base: 89, tax: 42, fee: 0},
];

function updatePreview() {
    const strategy = document.getElementById('pricing-strategy').value;
    const pct = parseFloat(document.getElementById('pricing-percent').value) || 0;
    const flat = parseFloat(document.getElementById('pricing-flat').value) || 0;
    const split = parseFloat(document.getElementById('pricing-split').value) || 25;
    const min = parseFloat(document.getElementById('pricing-min').value) || 0;
    const max = parseFloat(document.getElementById('pricing-max').value) || 999;

    // Show/hide tiered section
    document.getElementById('tiered-section').style.display =
        (strategy === 'tiered') ? 'block' : 'none';

    const tiers = {};
    const te = document.getElementById('tier-economy').value;
    const tp = document.getElementById('tier-premium').value;
    const tb = document.getElementById('tier-business').value;
    const tf = document.getElementById('tier-first').value;
    if (te) tiers['ECONOMY'] = parseFloat(te);
    if (tp) tiers['PREMIUM_ECONOMY'] = parseFloat(tp);
    if (tb) tiers['BUSINESS'] = parseFloat(tb);
    if (tf) tiers['FIRST'] = parseFloat(tf);

    const tbody = document.getElementById('preview-body');
    tbody.innerHTML = '';

    SAMPLE_FARES.forEach(fare => {
        const cost = fare.base + fare.tax + fare.fee;
        let markup = 0;
        const cabinPct = (strategy === 'tiered' && tiers[fare.cabin] !== undefined)
            ? tiers[fare.cabin] : pct;

        if (strategy === 'flat_fee') markup = flat;
        else if (strategy === 'percent_base') markup = fare.base * (cabinPct / 100) + flat;
        else if (strategy === 'percent_total') markup = cost * (cabinPct / 100) + flat;
        else if (strategy === 'savings_split') {
            const bench = cost * 1.15; // Simulated 15% savings
            markup = (bench - cost) * (split / 100);
        }
        else if (strategy === 'tiered') markup = cost * (cabinPct / 100) + flat;

        markup = Math.max(min, Math.min(max, markup));
        markup = Math.round(markup * 100) / 100;
        const consumer = Math.round((cost + markup) * 100) / 100;

        const tr = document.createElement('tr');
        tr.innerHTML = '<td>' + fare.route + '</td>' +
            '<td>' + fare.cabin + '</td>' +
            '<td>$' + fare.base.toFixed(2) + '</td>' +
            '<td>$' + fare.tax.toFixed(2) + '</td>' +
            '<td>$' + cost.toFixed(2) + '</td>' +
            '<td class="markup">+$' + markup.toFixed(2) + '</td>' +
            '<td class="consumer">$' + consumer.toFixed(2) + '</td>';
        tbody.appendChild(tr);
    });
}

// Save functions
async function savePricing() {
    const strategy = document.getElementById('pricing-strategy').value;
    const body = {
        strategy,
        markup_percent: parseFloat(document.getElementById('pricing-percent').value) || 0,
        markup_flat: parseFloat(document.getElementById('pricing-flat').value) || 0,
        savings_split_percent: parseFloat(document.getElementById('pricing-split').value) || 25,
        min_markup: parseFloat(document.getElementById('pricing-min').value) || 0,
        max_markup: parseFloat(document.getElementById('pricing-max').value) || 999,
        display_currency: document.getElementById('pricing-currency').value,
    };
    if (strategy === 'tiered') {
        body.cabin_tiers = {};
        const te = document.getElementById('tier-economy').value;
        const tp = document.getElementById('tier-premium').value;
        const tb = document.getElementById('tier-business').value;
        const tf = document.getElementById('tier-first').value;
        if (te) body.cabin_tiers.ECONOMY = {percent: parseFloat(te)};
        if (tp) body.cabin_tiers.PREMIUM_ECONOMY = {percent: parseFloat(tp)};
        if (tb) body.cabin_tiers.BUSINESS = {percent: parseFloat(tb)};
        if (tf) body.cabin_tiers.FIRST = {percent: parseFloat(tf)};
    }
    try {
        const r = await fetch(API_BASE + '/api/v1/admin/config/pricing', {method: 'PUT', headers, body: JSON.stringify(body)});
        const data = await r.json();
        if (data.success) showToast('Pricing saved successfully', 'success');
        else showToast('Error: ' + (data.error || 'Unknown'), 'error');
    } catch (e) { showToast('Save failed: ' + e.message, 'error'); }
}

async function saveDisplay() {
    const body = {
        results_per_page: parseInt(document.getElementById('display-rpp').value) || 20,
        default_sort: document.getElementById('display-sort').value,
        time_format: document.getElementById('display-time').value,
        date_format: document.getElementById('display-date').value,
        show_baggage: document.getElementById('display-baggage').checked,
        show_fare_family: document.getElementById('display-fare-family').checked,
        show_fare_rules_link: document.getElementById('display-fare-rules').checked,
        show_seatmap_link: document.getElementById('display-seatmap').checked,
        show_savings: document.getElementById('display-savings').checked,
        show_benchmark_price: document.getElementById('display-benchmark').checked,
        show_gds_source: document.getElementById('display-gds').checked,
    };
    try {
        const r = await fetch(API_BASE + '/api/v1/admin/config/display', {method: 'PUT', headers, body: JSON.stringify(body)});
        const data = await r.json();
        if (data.success) showToast('Display settings saved', 'success');
        else showToast('Error: ' + (data.error || 'Unknown'), 'error');
    } catch (e) { showToast('Save failed: ' + e.message, 'error'); }
}

async function saveBranding() {
    const body = {
        company_name: document.getElementById('brand-name').value,
        logo_url: document.getElementById('brand-logo').value,
        support_email: document.getElementById('brand-email').value,
        support_phone: document.getElementById('brand-phone').value,
        footer_text: document.getElementById('brand-footer').value,
        primary_color: document.getElementById('brand-primary').value,
        accent_color: document.getElementById('brand-accent').value,
        favicon_url: document.getElementById('brand-favicon').value,
        heading_font: document.getElementById('brand-heading-font').value,
        body_font: document.getElementById('brand-body-font').value,
    };
    try {
        const r = await fetch(API_BASE + '/api/v1/admin/config/branding', {method: 'PUT', headers, body: JSON.stringify(body)});
        const data = await r.json();
        if (data.success) showToast('Branding saved', 'success');
        else showToast('Error: ' + (data.error || 'Unknown'), 'error');
    } catch (e) { showToast('Save failed: ' + e.message, 'error'); }
}

async function saveFeatures() {
    const body = {
        ai_chat: document.getElementById('feat-chat').checked,
        structured_search: document.getElementById('feat-search').checked,
        booking_enabled: document.getElementById('feat-booking').checked,
        document_generation: document.getElementById('feat-docs').checked,
        seatmap: document.getElementById('feat-seatmap').checked,
        booking_management: document.getElementById('feat-management').checked,
        max_daily_searches: parseInt(document.getElementById('feat-max-searches').value) || 0,
        max_daily_bookings: parseInt(document.getElementById('feat-max-bookings').value) || 0,
    };
    try {
        const r = await fetch(API_BASE + '/api/v1/admin/config/features', {method: 'PUT', headers, body: JSON.stringify(body)});
        const data = await r.json();
        if (data.success) showToast('Features saved', 'success');
        else showToast('Error: ' + (data.error || 'Unknown'), 'error');
    } catch (e) { showToast('Save failed: ' + e.message, 'error'); }
}

// ================================================================
// UNIFIED ANASTASIA TERMINAL
// ================================================================

let uniCurrentSession = null;
let uniBusy = false;

function uniFormatMessage(text) {
    text = text.replace(/```(\w*)\n([\s\S]*?)```/g, function(m, lang, code) {
        return '<pre><code>' + code.replace(/</g, '&lt;').replace(/>/g, '&gt;') + '</code></pre>';
    });
    text = text.replace(/`([^`]+)`/g, '<code>$1</code>');
    text = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    text = text.replace(/\*([^*]+)\*/g, '<em>$1</em>');
    text = text.replace(/^- (.+)$/gm, '<li>$1</li>');
    text = text.replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>');
    text = text.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');
    text = text.replace(/\n\n/g, '<br><br>');
    text = text.replace(/\n/g, '<br>');
    return text;
}

function uniAddMessage(role, text) {
    var container = document.getElementById('uni-messages');
    var div = document.createElement('div');
    div.className = 'assist-msg assist-' + role;
    if (role === 'bot') {
        div.innerHTML = uniFormatMessage(text);
    } else {
        div.textContent = text;
    }
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

function uniShowTyping() {
    var container = document.getElementById('uni-messages');
    var div = document.createElement('div');
    div.className = 'assist-typing';
    div.id = 'uni-typing';
    div.innerHTML = '<span class="dots"><span>.</span><span>.</span><span>.</span></span>';
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

function uniRemoveTyping() {
    var el = document.getElementById('uni-typing');
    if (el) el.remove();
}

async function uniNewSession() {
    try {
        var r = await fetch(API_BASE + '/api/v1/dev/sessions', {method: 'POST', headers, body: '{}'});
        var data = await r.json();
        if (data.session_id) {
            uniCurrentSession = data.session_id;
            document.getElementById('uni-session-title').textContent = 'New Session';
            document.getElementById('uni-session-badge').style.display = 'inline';
            document.getElementById('uni-messages').innerHTML =
                '<div class="assist-msg assist-system"><div style="font-size:13px;color:var(--text-dim);line-height:1.6;">' +
                '<strong style="color:var(--accent);">New session started.</strong> Build, troubleshoot, configure, or search — just ask.</div></div>';
            document.getElementById('uni-session-queries').textContent = '0 queries';
            uniLoadSessions();
        }
    } catch(e) { showToast('Failed to create session: ' + e.message, 'error'); }
}

async function uniCloseSession() {
    if (!uniCurrentSession) return;
    try {
        await fetch(API_BASE + '/api/v1/dev/sessions/' + uniCurrentSession + '/close', {method: 'POST', headers});
    } catch(e) {}
    uniCurrentSession = null;
    document.getElementById('uni-session-title').textContent = '';
    document.getElementById('uni-session-badge').style.display = 'none';
    document.getElementById('uni-messages').innerHTML =
        '<div class="assist-msg assist-system"><div style="font-size:13px;color:var(--text-dim);line-height:1.6;">' +
        '<strong style="color:var(--accent);">ANASTASiA Terminal</strong> — Click <strong>+ New</strong> or just type to start.</div></div>';
    uniLoadSessions();
    showToast('Session closed', 'success');
}

async function uniLoadSessions() {
    try {
        var r = await fetch(API_BASE + '/api/v1/dev/sessions', {headers});
        var data = await r.json();
        var sessions = data.sessions || [];
        var el = document.getElementById('uni-sessions');
        var totalQ = 0;
        el.innerHTML = sessions.map(function(s) {
            totalQ += s.queries_used || 0;
            return '<div class="term-session-item' + (s.session_id === uniCurrentSession ? ' active' : '') +
                '" onclick="uniSwitchSession(\'' + s.session_id + '\')">' +
                '<div style="font-size:12px;font-weight:500;">' + (s.title || 'Untitled') + '</div>' +
                '<div style="font-size:10px;color:var(--text-dim);margin-top:2px;">' +
                s.message_count + ' msgs &middot; ' + s.queries_used + ' queries</div></div>';
        }).join('');
        document.getElementById('uni-total-queries').textContent = totalQ;
    } catch(e) {}
}

function uniSwitchSession(sessionId) {
    uniCurrentSession = sessionId;
    document.getElementById('uni-session-title').textContent = sessionId.substring(0, 8) + '...';
    document.getElementById('uni-session-badge').style.display = 'inline';
    document.getElementById('uni-messages').innerHTML =
        '<div class="assist-msg assist-system"><div style="font-size:13px;color:var(--text-dim);">Session loaded. Continue where you left off.</div></div>';
    uniLoadSessions();
}

function uniSendFromInput() {
    var input = document.getElementById('uni-input');
    var msg = input.value.trim();
    if (msg) {
        uniSend(msg);
        input.value = '';
    }
}

async function uniSend(message) {
    if (uniBusy || !message.trim()) return;
    uniBusy = true;

    var btn = document.getElementById('uni-send-btn');
    btn.disabled = true;
    btn.textContent = '...';

    uniAddMessage('user', message);
    uniShowTyping();

    // Auto-create session if none exists
    if (!uniCurrentSession) {
        try {
            var cr = await fetch(API_BASE + '/api/v1/dev/sessions', {method: 'POST', headers, body: '{}'});
            var cd = await cr.json();
            if (cd.session_id) {
                uniCurrentSession = cd.session_id;
                document.getElementById('uni-session-title').textContent = 'New Session';
                document.getElementById('uni-session-badge').style.display = 'inline';
                uniLoadSessions();
            }
        } catch(e) {
            uniRemoveTyping();
            uniAddMessage('bot', 'Failed to create session: ' + e.message);
            btn.disabled = false;
            btn.textContent = 'Send';
            uniBusy = false;
            return;
        }
    }

    try {
        var r = await fetch(API_BASE + '/api/v1/dev/sessions/' + uniCurrentSession + '/message', {
            method: 'POST', headers,
            body: JSON.stringify({message: message})
        });
        var data = await r.json();

        uniRemoveTyping();

        if (data.error) {
            uniAddMessage('bot', 'Error: ' + data.error);
        } else {
            uniAddMessage('bot', data.response || data.message || 'No response');
            if (data.queries_used !== undefined) {
                document.getElementById('uni-session-queries').textContent = data.queries_used + ' queries';
            }
            if (data.config_changed) {
                loadConfig();
                showToast('Config updated via terminal', 'success');
            }
        }
    } catch(e) {
        uniRemoveTyping();
        uniAddMessage('bot', 'Connection error: ' + e.message);
    }

    btn.disabled = false;
    btn.textContent = 'Send';
    uniBusy = false;
}

// ============== ANALYTICS TAB ==============
async function loadAnalytics() {
    try {
        const r = await fetch(API_BASE + '/api/v1/analytics/dashboard', {headers});
        const data = await r.json();
        const u = data.usage || {};
        const avg = data.daily_average || {};
        const e = data.errors || {};
        const c = data.cost || {};
        const bl = data.billing || {};
        const aiUsage = (bl.usage||{}).ai_requests||{};

        document.getElementById('anMetricAi').textContent = (u.ai_requests||0).toLocaleString();
        document.getElementById('anMetricSearches').textContent = (u.searches||0).toLocaleString();
        document.getElementById('anMetricBookings').textContent = (u.bookings||0).toLocaleString();
        document.getElementById('anMetricErrors').textContent = (e.rate_pct||0)+'%';
        document.getElementById('anTotalErrors').textContent = (e.total||0)+' total errors';
        document.getElementById('anAvgSearches').textContent = (avg.searches||0)+' avg/day';
        document.getElementById('anAvgBookings').textContent = (avg.bookings||0)+' avg/day';

        const limit = aiUsage.limit||0;
        if (limit>0) {
            document.getElementById('anMetricAiLimit').textContent = '/ '+limit.toLocaleString()+' limit';
            const pct = Math.min(100,((u.ai_requests||0)/limit)*100);
            document.getElementById('anBarAi').style.width = pct+'%';
            if (pct>90) document.getElementById('anBarAi').style.background='var(--danger)';
        }

        document.getElementById('anCostBase').textContent = '$'+(c.base_cost||0).toFixed(2);
        document.getElementById('anCostOverage').textContent = '$'+(c.overage_cost||0).toFixed(2);
        document.getElementById('anOverageCount').textContent = (c.overage_requests||0).toLocaleString();
        document.getElementById('anCostTotal').textContent = '$'+(c.total_estimated||0).toFixed(2);

        const cats = e.by_category||{};
        document.getElementById('anErrorCats').innerHTML = Object.entries(cats).map(([cat,count]) =>
            '<div style="display:flex;justify-content:space-between;padding:8px 12px;background:var(--input-bg);border-radius:6px;font-size:13px;"><span style="color:var(--text-dim);">'+cat+'</span><span style="font-weight:500;'+(count>10?'color:var(--danger)':'')+'">'+(count||0)+'</span></div>'
        ).join('') || '<div style="color:var(--success);font-size:13px;">No errors this period</div>';

        const recent = (e.recent||[]);
        document.getElementById('anErrorLog').innerHTML = recent.length===0
            ? '<div style="color:var(--success);">No errors recorded this period.</div>'
            : recent.map(err => '<div style="padding:6px 0;border-bottom:1px solid var(--border);">'+new Date(err.timestamp*1000).toLocaleString()+' <span style="padding:1px 6px;border-radius:3px;font-size:10px;background:rgba(99,102,241,0.2);color:var(--accent);">'+err.category+'</span> '+err.endpoint+' — '+(err.message||'')+'</div>').join('');
    } catch(err) { console.error('Analytics load error:', err); }
}

// ============== BILLING TAB ==============
async function loadBilling() {
    try {
        const r = await fetch(API_BASE + '/api/v1/billing/subscription', {headers});
        const sub = await r.json();
        document.getElementById('blPlanName').textContent = sub.plan_name||'No Plan';
        document.getElementById('blPlanPrice').textContent = sub.plan_id ? '$'+(sub.billing_info||{}).base_cost+'/mo' : 'Not subscribed';
        document.getElementById('blPlanStatus').textContent = 'Status: '+(sub.status||'none');

        const usage = sub.usage||{};
        const barsEl = document.getElementById('blUsageBars');
        barsEl.innerHTML = '';
        for (const [key, val] of Object.entries(usage)) {
            const pct = val.limit>0 ? Math.min(100,(val.used/val.limit)*100) : 0;
            barsEl.innerHTML += '<div style="margin-bottom:12px;"><div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:4px;"><span style="color:var(--text-dim);">'+key.replace(/_/g,' ')+'</span><span>'+val.used+(val.limit>0?' / '+val.limit:'')+'</span></div><div style="height:6px;background:var(--border);border-radius:3px;overflow:hidden;"><div style="height:100%;width:'+pct+'%;background:'+( pct>90?'var(--danger)':'var(--accent)')+';border-radius:3px;transition:width 0.3s;"></div></div></div>';
        }
    } catch(err) { console.error('Billing load error:', err); }

    // Load plans
    try {
        const r = await fetch(API_BASE + '/api/v1/billing/plans', {headers});
        const data = await r.json();
        const plans = data.plans||[];
        document.getElementById('blPlanCards').innerHTML = plans.map(p =>
            '<div style="background:var(--input-bg);border:1px solid var(--border);border-radius:12px;padding:24px;text-align:center;">' +
            '<div style="font-family:Space Grotesk,sans-serif;font-size:18px;">'+p.name+'</div>' +
            '<div style="font-size:28px;font-weight:600;color:var(--accent);margin:8px 0;">$'+p.price_monthly+'<span style="font-size:14px;color:var(--text-dim);">/mo</span></div>' +
            '<div style="font-size:12px;color:var(--text-dim);">'+((p.limits||{}).ai_requests_per_month||0).toLocaleString()+' AI requests/mo</div>' +
            '<ul style="list-style:none;margin-top:12px;font-size:12px;color:var(--text-dim);text-align:left;">' +
            (p.features||[]).slice(0,6).map(f=>'<li style="padding:2px 0;">&#10003; '+f.replace(/_/g,' ')+'</li>').join('') +
            '</ul></div>'
        ).join('');
    } catch(err) { console.error('Plans load error:', err); }
}

// Override switchTab to lazy-load tabs
const _origSwitchTab = switchTab;
switchTab = function(name) {
    _origSwitchTab(name);
    if (name === 'analytics') loadAnalytics();
    if (name === 'billing') loadBilling();
    if (name === 'assistant') uniLoadSessions();
};

// Initialize
loadConfig();
</script>
</body>
</html>"""
