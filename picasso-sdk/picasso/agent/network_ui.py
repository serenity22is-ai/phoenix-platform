"""
Network UI — Credential Network dashboard panels for the APAi admin dashboard.

Three new tabs injected into the admin dashboard:
  - Network: Browse directory, manage connections, provider profile, terms cards
  - Terminal: ANASTASiA Terminal for dev sessions (AI architect)
  - Modules: Custom SDK module lifecycle (draft → audit → deploy → publish)

Uses the same CSS variables, card styles, and API pattern as the existing
dashboard tabs. No external dependencies.

MYSTES KYRIOS LLC — Confidential.
"""

# =====================================================================
# NETWORK TAB — My Network, Directory, Connections, Terms
# =====================================================================

NETWORK_TAB_HTML = """
    <!-- NETWORK TAB -->
    <div id="tab-network" class="tab-content">
        <!-- Sub-tabs within Network -->
        <div style="display:flex;gap:4px;margin-bottom:20px;border-bottom:1px solid var(--border);padding-bottom:0;">
            <div class="net-subtab active" onclick="switchNetTab('overview')" data-net="overview">Overview</div>
            <div class="net-subtab" onclick="switchNetTab('directory')" data-net="directory">Directory</div>
            <div class="net-subtab" onclick="switchNetTab('connections')" data-net="connections">Connections</div>
            <div class="net-subtab" onclick="switchNetTab('terms')" data-net="terms">My Terms</div>
            <div class="net-subtab" onclick="switchNetTab('profile')" data-net="profile">My Profile</div>
            <div class="net-subtab" onclick="switchNetTab('audit')" data-net="audit">Audit Trail</div>
        </div>

        <!-- OVERVIEW -->
        <div id="net-overview" class="net-content active">
            <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:16px;margin-bottom:24px;">
                <div class="card" style="text-align:center;padding:24px;">
                    <div style="font-size:32px;font-weight:700;color:var(--accent);" id="net-stat-active">0</div>
                    <div style="font-size:12px;color:var(--text-dim);margin-top:4px;">Active Connections</div>
                </div>
                <div class="card" style="text-align:center;padding:24px;">
                    <div style="font-size:32px;font-weight:700;color:var(--success);" id="net-stat-pending">0</div>
                    <div style="font-size:12px;color:var(--text-dim);margin-top:4px;">Pending Requests</div>
                </div>
                <div class="card" style="text-align:center;padding:24px;">
                    <div style="font-size:32px;font-weight:700;color:var(--accent);" id="net-stat-queries">0</div>
                    <div style="font-size:12px;color:var(--text-dim);margin-top:4px;">Queries This Month</div>
                </div>
                <div class="card" style="text-align:center;padding:24px;">
                    <div style="font-size:32px;font-weight:700;color:var(--success);" id="net-stat-revenue">$0</div>
                    <div style="font-size:12px;color:var(--text-dim);margin-top:4px;">Revenue This Month</div>
                </div>
            </div>

            <!-- Health -->
            <div class="card">
                <h2 style="font-size:16px;margin-bottom:16px;">Connection Health</h2>
                <div id="net-health" style="display:flex;gap:12px;">
                    <span class="health-badge green"><span class="health-dot green"></span> <span id="net-health-green">0</span> Healthy</span>
                    <span class="health-badge yellow"><span class="health-dot yellow"></span> <span id="net-health-yellow">0</span> Warning</span>
                    <span class="health-badge red"><span class="health-dot red"></span> <span id="net-health-red">0</span> Critical</span>
                </div>
            </div>

            <!-- Revenue Split -->
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px;">
                <div class="card">
                    <h2 style="font-size:14px;color:var(--text-dim);margin-bottom:12px;">As Router (your searches, their credentials)</h2>
                    <div style="font-size:24px;font-weight:600;" id="net-rev-router-amt">$0.00</div>
                    <div style="font-size:12px;color:var(--text-dim);margin-top:4px;"><span id="net-rev-router-q">0</span> queries &middot; <span id="net-rev-router-b">0</span> bookings</div>
                </div>
                <div class="card">
                    <h2 style="font-size:14px;color:var(--text-dim);margin-bottom:12px;">As Host (their searches, your credentials)</h2>
                    <div style="font-size:24px;font-weight:600;" id="net-rev-host-amt">$0.00</div>
                    <div style="font-size:12px;color:var(--text-dim);margin-top:4px;"><span id="net-rev-host-q">0</span> queries &middot; <span id="net-rev-host-b">0</span> bookings</div>
                </div>
            </div>

            <!-- Vault usage & Tier taste preview -->
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px;">
                <div class="card">
                    <h2 style="font-size:14px;color:var(--text-dim);margin-bottom:12px;">Credential Vault</h2>
                    <div style="font-size:16px;font-weight:600;" id="net-vault-usage">0 / 3 credentials</div>
                    <div style="font-size:11px;color:var(--text-dim);margin-top:4px;">Add credentials in the My Terms tab</div>
                </div>
                <div class="card" id="net-taste-preview" style="display:none;">
                </div>
            </div>
        </div>

        <!-- DIRECTORY -->
        <div id="net-directory" class="net-content">
            <div class="card">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
                    <h2 style="font-size:16px;">Provider Directory</h2>
                    <div style="display:flex;gap:8px;">
                        <input type="text" id="net-dir-search" placeholder="Search providers..."
                            style="padding:8px 12px;background:var(--input-bg);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:13px;width:200px;"
                            onkeyup="if(event.key==='Enter')loadDirectory()">
                        <select id="net-dir-tier" style="padding:8px;background:var(--input-bg);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:13px;" onchange="loadDirectory()">
                            <option value="">All Tiers</option>
                            <option value="pro">Pro</option>
                            <option value="enterprise">Enterprise</option>
                            <option value="scale">Scale</option>
                        </select>
                        <button class="btn btn-primary" onclick="loadDirectory()" style="padding:8px 16px;font-size:13px;">Search</button>
                    </div>
                </div>
                <div id="net-dir-results" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px;">
                    <div style="color:var(--text-dim);font-size:13px;">Loading directory...</div>
                </div>
                <div id="net-dir-pagination" style="display:flex;justify-content:center;gap:8px;margin-top:16px;"></div>
            </div>
        </div>

        <!-- CONNECTIONS -->
        <div id="net-connections" class="net-content">
            <div class="card">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
                    <h2 style="font-size:16px;">My Connections</h2>
                    <div style="display:flex;gap:8px;">
                        <select id="net-conn-role" style="padding:8px;background:var(--input-bg);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:13px;" onchange="loadConnections()">
                            <option value="">All</option>
                            <option value="requester">As Router</option>
                            <option value="provider">As Host</option>
                        </select>
                        <select id="net-conn-status" style="padding:8px;background:var(--input-bg);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:13px;" onchange="loadConnections()">
                            <option value="">All Status</option>
                            <option value="active">Active</option>
                            <option value="pending">Pending</option>
                            <option value="paused">Paused</option>
                        </select>
                    </div>
                </div>
                <div id="net-conn-list"></div>
            </div>
        </div>

        <!-- MY TERMS -->
        <div id="net-terms" class="net-content">
            <div class="card">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
                    <h2 style="font-size:16px;">My Terms Cards</h2>
                    <button class="btn btn-primary" onclick="showCreateTerms()" style="padding:8px 16px;font-size:13px;">+ New Terms Card</button>
                </div>
                <div id="net-terms-list"></div>
            </div>

            <!-- Create/Edit Terms Modal -->
            <div id="net-terms-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:1000;display:none;align-items:center;justify-content:center;">
                <div style="background:var(--card);border:1px solid var(--border);border-radius:16px;width:90%;max-width:700px;max-height:90vh;overflow-y:auto;padding:32px;">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:24px;">
                        <h2 id="net-terms-modal-title" style="font-size:18px;">New Terms Card</h2>
                        <button onclick="hideTermsModal()" style="background:none;border:none;color:var(--text-dim);font-size:20px;cursor:pointer;">&times;</button>
                    </div>
                    <input type="hidden" id="tm-edit-id" value="">

                    <!-- Credential Info -->
                    <div style="margin-bottom:20px;">
                        <div class="form-row">
                            <div class="form-group"><label>Credential Label</label><input type="text" id="tm-label" placeholder="e.g. Amadeus GDS — EU"></div>
                            <div class="form-group"><label>Type</label>
                                <select id="tm-type"><option value="gds">GDS</option><option value="ndc">NDC</option><option value="direct_booking_bridge">Direct Booking Bridge</option><option value="hotel">Hotel</option><option value="car">Car</option></select>
                            </div>
                            <div class="form-group"><label>Provider System</label>
                                <select id="tm-system"><option value="amadeus">Amadeus</option><option value="sabre">Sabre</option><option value="duffel">Duffel</option><option value="airgateway">AirGateway</option><option value="liteapi">liteAPI</option><option value="other">Other</option></select>
                            </div>
                        </div>
                    </div>

                    <!-- Pricing Section -->
                    <details open style="margin-bottom:16px;"><summary style="font-weight:600;color:var(--accent);cursor:pointer;margin-bottom:12px;">Pricing</summary>
                        <div class="form-row">
                            <div class="form-group"><label>Per-Query Fee (USD)</label><input type="number" id="tm-query-fee" step="0.01" value="0.00"></div>
                            <div class="form-group"><label>Router Split %</label><input type="number" id="tm-router-pct" value="70" min="0" max="100"></div>
                            <div class="form-group"><label>Host Split %</label><input type="number" id="tm-host-pct" value="30" min="0" max="100"></div>
                        </div>
                        <div class="form-row">
                            <div class="form-group"><label>Min Booking Value (USD)</label><input type="number" id="tm-min-booking" step="1" value=""></div>
                            <div class="form-group"><label>Min Margin (USD)</label><input type="number" id="tm-min-margin" step="1" value=""></div>
                        </div>
                    </details>

                    <!-- Coverage Section -->
                    <details style="margin-bottom:16px;"><summary style="font-weight:600;color:var(--accent);cursor:pointer;margin-bottom:12px;">Coverage</summary>
                        <div class="form-row">
                            <div class="form-group"><label>Markets Included (comma-separated)</label><input type="text" id="tm-markets-in" placeholder="US, DE, GB"></div>
                            <div class="form-group"><label>Markets Excluded</label><input type="text" id="tm-markets-ex" placeholder="RU, BY"></div>
                        </div>
                        <div class="form-row">
                            <div class="form-group"><label>Airlines Included</label><input type="text" id="tm-airlines-in" placeholder="LH, BA or ALL"></div>
                            <div class="form-group"><label>Airlines Excluded</label><input type="text" id="tm-airlines-ex" placeholder="FR, W6"></div>
                        </div>
                        <div class="form-row">
                            <div class="form-group"><label>Cabin Classes</label><input type="text" id="tm-cabins" placeholder="economy, business"></div>
                            <div class="form-group"><label>Trip Types</label><input type="text" id="tm-trips" placeholder="one-way, round-trip"></div>
                        </div>
                    </details>

                    <!-- Limits Section -->
                    <details style="margin-bottom:16px;"><summary style="font-weight:600;color:var(--accent);cursor:pointer;margin-bottom:12px;">Operational Limits</summary>
                        <div class="form-row">
                            <div class="form-group"><label>Max Queries / Day</label><input type="number" id="tm-max-qday" value=""></div>
                            <div class="form-group"><label>Max Queries / Hour</label><input type="number" id="tm-max-qhr" value=""></div>
                            <div class="form-group"><label>Max Bookings / Day</label><input type="number" id="tm-max-bday" value=""></div>
                        </div>
                        <div class="form-row">
                            <div class="form-group"><label>Response Time SLA (sec)</label><input type="number" id="tm-sla" step="0.5" value="8.0"></div>
                            <div class="form-group"><label>Auto-Pause Error Rate %</label><input type="number" id="tm-err-rate" step="1" value="15"></div>
                        </div>
                    </details>

                    <!-- Relationship Section -->
                    <details style="margin-bottom:16px;"><summary style="font-weight:600;color:var(--accent);cursor:pointer;margin-bottom:12px;">Relationship</summary>
                        <div class="form-row">
                            <div class="form-group"><label>Trial Period (days)</label><input type="number" id="tm-trial" value="0"></div>
                            <div class="form-group"><label>Notice Period (days)</label><input type="number" id="tm-notice" value="30"></div>
                            <div class="form-group"><label>Min Monthly Volume</label><input type="number" id="tm-min-vol" value=""></div>
                        </div>
                        <div class="form-row">
                            <div class="form-group"><label><input type="checkbox" id="tm-exclusive"> Exclusive Access</label></div>
                            <div class="form-group"><label><input type="checkbox" id="tm-auto-renew" checked> Auto-Renew</label></div>
                        </div>
                    </details>

                    <!-- Arbitrage Section -->
                    <details style="margin-bottom:16px;"><summary style="font-weight:600;color:var(--accent);cursor:pointer;margin-bottom:12px;">Arbitrage Permissions</summary>
                        <div class="form-row">
                            <div class="form-group"><label><input type="checkbox" id="tm-pos-arb" checked> Allow POS Arbitrage</label></div>
                            <div class="form-group"><label>Markup Cap %</label><input type="number" id="tm-markup-cap" step="1" value="" placeholder="No cap"></div>
                            <div class="form-group"><label>Price Visibility</label>
                                <select id="tm-visibility"><option value="blind">Blind</option><option value="transparent">Transparent</option></select>
                            </div>
                        </div>
                    </details>

                    <div style="display:flex;gap:12px;margin-top:20px;">
                        <label style="display:flex;align-items:center;gap:8px;font-size:13px;"><input type="checkbox" id="tm-published"> Publish immediately</label>
                    </div>
                    <div style="display:flex;gap:12px;margin-top:20px;justify-content:flex-end;">
                        <button class="btn" onclick="hideTermsModal()" style="padding:10px 24px;">Cancel</button>
                        <button class="btn btn-primary" onclick="saveTermsCard()" style="padding:10px 24px;">Save Terms Card</button>
                    </div>
                </div>
            </div>
        </div>

        <!-- MY PROFILE -->
        <div id="net-profile" class="net-content">
            <div class="card">
                <h2 style="font-size:16px;margin-bottom:16px;">My Provider Profile</h2>
                <div class="form-row">
                    <div class="form-group"><label>Display Name</label><input type="text" id="np-name" placeholder="Your OTA name"></div>
                    <div class="form-group"><label>Contact Email</label><input type="email" id="np-email" placeholder="contact@your-ota.com"></div>
                </div>
                <div class="form-group"><label>Description</label><textarea id="np-desc" rows="3" placeholder="What credentials do you offer? What markets do you cover?" style="width:100%;padding:8px 12px;background:var(--input-bg);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:13px;resize:vertical;"></textarea></div>
                <div class="form-row">
                    <div class="form-group"><label>Logo URL</label><input type="url" id="np-logo" placeholder="https://..."></div>
                    <div class="form-group"><label>Website URL</label><input type="url" id="np-website" placeholder="https://your-ota.com"></div>
                </div>
                <div class="form-row" style="margin-top:12px;">
                    <div class="form-group"><label><input type="checkbox" id="np-visible" checked> Visible in Directory</label></div>
                    <div class="form-group"><label><input type="checkbox" id="np-accepting" checked> Accepting Connections</label></div>
                </div>
                <div style="margin-top:20px;display:flex;justify-content:flex-end;">
                    <button class="btn btn-primary" onclick="saveProfile()" style="padding:10px 24px;">Save Profile</button>
                </div>
            </div>
        </div>

        <!-- AUDIT TRAIL -->
        <div id="net-audit" class="net-content">
            <div class="card">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
                    <h2 style="font-size:16px;">Transaction Audit Trail</h2>
                    <div style="display:flex;gap:8px;">
                        <select id="net-audit-type" style="padding:8px;background:var(--input-bg);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:13px;" onchange="loadAudit()">
                            <option value="">All Events</option>
                            <option value="search">Searches</option>
                            <option value="booking">Bookings</option>
                            <option value="failure">Failures</option>
                        </select>
                    </div>
                </div>
                <div id="net-audit-table" style="overflow-x:auto;">
                    <table style="width:100%;border-collapse:collapse;font-size:13px;">
                        <thead><tr style="border-bottom:1px solid var(--border);color:var(--text-dim);text-align:left;">
                            <th style="padding:8px;">Time</th><th style="padding:8px;">Type</th><th style="padding:8px;">Route</th>
                            <th style="padding:8px;">Fee</th><th style="padding:8px;">Amount</th><th style="padding:8px;">Status</th>
                        </tr></thead>
                        <tbody id="net-audit-body"></tbody>
                    </table>
                </div>
                <div id="net-audit-pagination" style="display:flex;justify-content:center;gap:8px;margin-top:12px;"></div>
            </div>
        </div>
    </div>
"""

# =====================================================================
# TERMINAL TAB — ANASTASiA Terminal (AI Architect)
# =====================================================================

TERMINAL_TAB_HTML = """
    <!-- TERMINAL TAB -->
    <div id="tab-terminal" class="tab-content">
        <div style="display:grid;grid-template-columns:260px 1fr;gap:0;height:calc(100vh - 180px);">
            <!-- Session Sidebar -->
            <div style="background:var(--card);border-right:1px solid var(--border);display:flex;flex-direction:column;">
                <div style="padding:16px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;">
                    <h3 style="font-size:14px;font-family:'Space Grotesk',sans-serif;">Sessions</h3>
                    <button class="btn btn-primary" onclick="termNewSession()" style="padding:4px 12px;font-size:11px;">+ New</button>
                </div>
                <div id="term-sessions" style="flex:1;overflow-y:auto;padding:8px;"></div>
                <div style="padding:12px;border-top:1px solid var(--border);font-size:11px;color:var(--text-dim);">
                    Queries used: <strong id="term-total-queries" style="color:var(--accent);">0</strong>
                </div>
            </div>

            <!-- Terminal Main -->
            <div style="display:flex;flex-direction:column;background:var(--bg);">
                <!-- Terminal Header -->
                <div style="padding:12px 20px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;flex-shrink:0;">
                    <div>
                        <span style="font-family:'Space Grotesk',sans-serif;font-size:14px;color:var(--accent);">ANASTASiA Terminal</span>
                        <span id="term-session-title" style="font-size:12px;color:var(--text-dim);margin-left:8px;"></span>
                    </div>
                    <div style="display:flex;gap:8px;align-items:center;">
                        <span id="term-session-queries" style="font-size:11px;color:var(--text-dim);padding:4px 10px;background:var(--input-bg);border-radius:6px;">0 queries</span>
                        <button class="btn" onclick="termCloseSession()" style="padding:4px 12px;font-size:11px;background:transparent;border:1px solid var(--border);">Close Session</button>
                    </div>
                </div>

                <!-- Messages Area -->
                <div id="term-messages" style="flex:1;overflow-y:auto;padding:20px;display:flex;flex-direction:column;gap:16px;">
                    <div class="assist-msg assist-system" style="align-self:flex-start;max-width:85%;padding:16px;background:var(--card);border:1px solid var(--border);border-radius:12px;">
                        <div style="font-size:13px;color:var(--text-dim);line-height:1.6;">
                            <strong style="color:var(--accent);">ANASTASiA Terminal</strong> — Your AI architect.<br>
                            I know your turnkey model inside and out. I can:
                            <ul style="margin:8px 0 0 16px;list-style:disc;">
                                <li>Troubleshoot API integration issues</li>
                                <li>Build custom features and SDK modules</li>
                                <li>Audit and deploy your custom code</li>
                                <li>Configure pricing, branding, credentials</li>
                                <li>Generate integration code for your stack</li>
                            </ul>
                        </div>
                    </div>
                </div>

                <!-- Quick Actions -->
                <div style="padding:8px 20px;border-top:1px solid rgba(255,255,255,0.04);display:flex;gap:6px;flex-wrap:wrap;flex-shrink:0;">
                    <button class="assist-quick" onclick="termSend('Run health check on my deployment')">Health Check</button>
                    <button class="assist-quick" onclick="termSend('Show my credential vault status')">Vault Status</button>
                    <button class="assist-quick" onclick="termSend('List my custom modules')">My Modules</button>
                    <button class="assist-quick" onclick="termSend('Generate a webhook handler for booking notifications')">Build Webhook</button>
                </div>

                <!-- Input -->
                <div style="padding:12px 20px 16px;border-top:1px solid var(--border);flex-shrink:0;">
                    <div style="display:flex;gap:8px;">
                        <textarea id="term-input" rows="2" placeholder="Build features, troubleshoot, deploy — everything happens here..."
                            style="flex:1;padding:10px 14px;background:var(--input-bg);border:1px solid var(--border);border-radius:8px;color:var(--text);font-family:inherit;font-size:13px;resize:none;outline:none;"
                            onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();termSendFromInput()}"></textarea>
                        <button class="btn btn-primary" onclick="termSendFromInput()" style="padding:10px 20px;align-self:flex-end;">Send</button>
                    </div>
                </div>
            </div>
        </div>
    </div>
"""

# =====================================================================
# MODULES TAB — Custom SDK Modules
# =====================================================================

MODULES_TAB_HTML = """
    <!-- MODULES TAB -->
    <div id="tab-modules" class="tab-content">
        <div class="card">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;">
                <h2 style="font-size:16px;">Custom SDK Modules</h2>
                <button class="btn btn-primary" onclick="termSend('I want to create a new custom module')" style="padding:8px 16px;font-size:13px;">+ New Module (via Terminal)</button>
            </div>
            <p style="font-size:13px;color:var(--text-dim);margin-bottom:20px;">
                Build custom features via the ANASTASiA Terminal. She'll audit your code for security and compatibility, then deploy it to your turnkey model.
            </p>
            <div id="mod-list" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px;"></div>
            <div id="mod-empty" style="text-align:center;padding:40px;color:var(--text-dim);font-size:13px;">
                No custom modules yet. Use the ANASTASiA Terminal to build your first one.
            </div>
        </div>
    </div>
"""

# =====================================================================
# CSS for Network UI
# =====================================================================

NETWORK_CSS = """
<style>
    /* Network sub-tabs */
    .net-subtab {
        padding: 10px 16px;
        cursor: pointer;
        font-size: 13px;
        font-weight: 500;
        color: var(--text-dim);
        border-bottom: 2px solid transparent;
        transition: all 0.2s;
    }
    .net-subtab:hover { color: var(--text); }
    .net-subtab.active {
        color: var(--accent);
        border-bottom-color: var(--accent);
    }
    .net-content { display: none; }
    .net-content.active { display: block; }

    /* Health badges */
    .health-badge {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 6px 14px;
        border-radius: 20px;
        font-size: 12px;
        font-weight: 500;
    }
    .health-badge.green { background: rgba(34,197,94,0.1); color: #22c55e; }
    .health-badge.yellow { background: rgba(245,158,11,0.1); color: #f59e0b; }
    .health-badge.red { background: rgba(239,68,68,0.1); color: #ef4444; }
    .health-dot {
        width: 8px; height: 8px; border-radius: 50%;
    }
    .health-dot.green { background: #22c55e; }
    .health-dot.yellow { background: #f59e0b; }
    .health-dot.red { background: #ef4444; }

    /* Provider cards in directory */
    .provider-card {
        background: var(--card);
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 20px;
        transition: border-color 0.2s;
    }
    .provider-card:hover {
        border-color: var(--accent);
    }
    .provider-card .tier-badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 10px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    .tier-badge.pro { background: rgba(99,102,241,0.15); color: #818cf8; }
    .tier-badge.enterprise { background: rgba(168,85,247,0.15); color: #a855f7; }
    .tier-badge.scale { background: rgba(34,197,94,0.15); color: #22c55e; }

    /* Connection cards */
    .conn-card {
        background: var(--card);
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 16px 20px;
        margin-bottom: 12px;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    .conn-card .status-pill {
        padding: 4px 10px;
        border-radius: 12px;
        font-size: 11px;
        font-weight: 600;
    }
    .status-pill.active { background: rgba(34,197,94,0.15); color: #22c55e; }
    .status-pill.pending { background: rgba(245,158,11,0.15); color: #f59e0b; }
    .status-pill.paused { background: rgba(99,102,241,0.15); color: #818cf8; }

    /* Terms cards */
    .terms-card-item {
        background: var(--card);
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 16px 20px;
        margin-bottom: 12px;
    }
    .terms-card-item.published { border-left: 3px solid var(--success); }
    .terms-card-item.draft { border-left: 3px solid var(--text-dim); }

    /* Terminal session items */
    .term-session-item {
        padding: 10px 12px;
        border-radius: 8px;
        cursor: pointer;
        font-size: 13px;
        color: var(--text-dim);
        margin-bottom: 4px;
        transition: background 0.15s;
    }
    .term-session-item:hover { background: var(--card-hover); }
    .term-session-item.active { background: var(--card-hover); color: var(--text); border-left: 2px solid var(--accent); }

    /* Module cards */
    .module-card {
        background: var(--card);
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 20px;
    }
    .module-status {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 10px;
        font-weight: 600;
        text-transform: uppercase;
    }
    .module-status.draft { background: rgba(136,136,170,0.15); color: #8888aa; }
    .module-status.auditing { background: rgba(245,158,11,0.15); color: #f59e0b; }
    .module-status.sandbox { background: rgba(99,102,241,0.15); color: #818cf8; }
    .module-status.deployed { background: rgba(34,197,94,0.15); color: #22c55e; }
    .module-status.published { background: rgba(34,197,94,0.25); color: #22c55e; }
    .module-status.rejected { background: rgba(239,68,68,0.15); color: #ef4444; }
</style>
"""

# =====================================================================
# JavaScript for Network UI
# =====================================================================

NETWORK_JS = """
<script>
// ===================================================================
// NETWORK TAB JS
// ===================================================================

function switchNetTab(name) {
    document.querySelectorAll('.net-subtab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.net-content').forEach(t => t.classList.remove('active'));
    document.querySelector('[data-net="'+name+'"]').classList.add('active');
    document.getElementById('net-'+name).classList.add('active');
    if (name === 'overview') loadNetworkStats();
    if (name === 'directory') loadDirectory();
    if (name === 'connections') loadConnections();
    if (name === 'terms') loadTermsCards();
    if (name === 'profile') loadProfile();
    if (name === 'audit') loadAudit();
}

let currentTier = 'pro';
let lockedFeatures = [];

async function loadNetworkStats() {
    try {
        const r = await fetch(API_BASE + '/api/v1/network/stats', {headers});
        const data = await r.json();
        document.getElementById('net-stat-active').textContent = data.connections.active;
        document.getElementById('net-stat-pending').textContent = data.connections.pending;
        const m = data.this_month;
        document.getElementById('net-stat-queries').textContent = (m.as_router.queries + m.as_host.queries).toLocaleString();
        document.getElementById('net-stat-revenue').textContent = '$' + (m.as_router.revenue_usd + m.as_host.revenue_usd).toFixed(2);
        document.getElementById('net-rev-router-amt').textContent = '$' + m.as_router.revenue_usd.toFixed(2);
        document.getElementById('net-rev-router-q').textContent = m.as_router.queries;
        document.getElementById('net-rev-router-b').textContent = m.as_router.bookings;
        document.getElementById('net-rev-host-amt').textContent = '$' + m.as_host.revenue_usd.toFixed(2);
        document.getElementById('net-rev-host-q').textContent = m.as_host.queries;
        document.getElementById('net-rev-host-b').textContent = m.as_host.bookings;
        const h = data.health || {};
        document.getElementById('net-health-green').textContent = h.green || 0;
        document.getElementById('net-health-yellow').textContent = h.yellow || 0;
        document.getElementById('net-health-red').textContent = h.red || 0;

        // Capture tier info for taste strategy
        if (data.tier) {
            currentTier = data.tier.tier || 'pro';
            lockedFeatures = data.tier.features_locked || [];
            renderTastePreview();
        }

        // Show vault usage
        const limits = data.tier && data.tier.limits || {};
        const vaultMax = limits.credential_vault_max || 3;
        const vaultCurrent = data.published_terms_cards || 0;
        const vaultEl = document.getElementById('net-vault-usage');
        if (vaultEl) {
            vaultEl.textContent = vaultMax === 0
                ? vaultCurrent + ' credentials (unlimited)'
                : vaultCurrent + ' / ' + vaultMax + ' credentials';
        }
    } catch(e) { console.error('Network stats error:', e); }
}

function renderTastePreview() {
    const el = document.getElementById('net-taste-preview');
    if (!el || !lockedFeatures.length) {
        if (el) el.style.display = 'none';
        return;
    }
    el.style.display = 'block';
    el.innerHTML = '<div style="font-size:12px;font-weight:600;color:var(--text-dim);margin-bottom:10px;letter-spacing:0.5px;">AVAILABLE ON UPGRADE</div>' +
        lockedFeatures.map(f =>
            '<div style="display:flex;align-items:center;gap:8px;padding:5px 0;opacity:0.45;">' +
            '<span style="color:var(--text-dim);font-size:12px;">&#128274;</span>' +
            '<span style="font-size:12px;color:var(--text-dim);">' + esc(f.label) + '</span>' +
            '<span style="margin-left:auto;font-size:10px;padding:2px 8px;border-radius:4px;' +
            'background:rgba(99,102,241,0.1);color:var(--accent);">' + f.requires + '</span></div>'
        ).join('');
}

async function loadDirectory(page) {
    page = page || 1;
    const search = document.getElementById('net-dir-search').value;
    const tier = document.getElementById('net-dir-tier').value;
    let url = API_BASE + '/api/v1/network/directory?page=' + page + '&per_page=12';
    if (search) url += '&search=' + encodeURIComponent(search);
    if (tier) url += '&tier=' + tier;
    try {
        const r = await fetch(url, {headers});
        const data = await r.json();
        const el = document.getElementById('net-dir-results');
        if (!data.providers.length) {
            el.innerHTML = '<div style="color:var(--text-dim);font-size:13px;grid-column:1/-1;text-align:center;padding:40px;">No providers found matching your criteria.</div>';
            return;
        }
        el.innerHTML = data.providers.map(p => `
            <div class="provider-card">
                <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px;">
                    <div>
                        <div style="font-weight:600;font-size:15px;">${esc(p.display_name)}</div>
                        <span class="tier-badge ${p.apai_tier}">${p.apai_tier}</span>
                    </div>
                    ${p.reputation_score ? '<div style="color:var(--warning);font-size:13px;">★ '+p.reputation_score.toFixed(1)+'</div>' : ''}
                </div>
                <div style="font-size:12px;color:var(--text-dim);margin-bottom:12px;">${esc(p.description||'No description')}</div>
                <div style="display:flex;gap:12px;font-size:11px;color:var(--text-dim);margin-bottom:12px;">
                    <span>${p.total_connections||0} connections</span>
                    <span>${p.total_bookings_routed||0} bookings</span>
                    ${p.avg_response_time_ms ? '<span>'+Math.round(p.avg_response_time_ms)+'ms avg</span>' : ''}
                </div>
                <div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:12px;">
                    ${(p.credentials_summary||[]).map(c => '<span style="padding:2px 8px;background:var(--input-bg);border-radius:4px;font-size:10px;color:var(--text-dim);">'+esc(c.system||c.type)+'</span>').join('')}
                </div>
                <button class="btn btn-primary" onclick="viewProvider(${p.id})" style="width:100%;padding:8px;font-size:12px;">View & Connect</button>
            </div>
        `).join('');
        // Pagination
        const pg = document.getElementById('net-dir-pagination');
        if (data.pages > 1) {
            pg.innerHTML = Array.from({length: data.pages}, (_, i) =>
                '<button class="btn'+(i+1===page?' btn-primary':'')+'" onclick="loadDirectory('+(i+1)+')" style="padding:4px 10px;font-size:12px;">'+(i+1)+'</button>'
            ).join('');
        } else { pg.innerHTML = ''; }
    } catch(e) { console.error('Directory error:', e); }
}

async function viewProvider(id) {
    try {
        const r = await fetch(API_BASE + '/api/v1/network/profile/' + id, {headers});
        const p = await r.json();
        const cards = (p.terms_cards||[]).filter(c => c.is_published);
        let html = '<div style="margin-bottom:16px;"><strong>'+esc(p.display_name)+'</strong> <span class="tier-badge '+p.apai_tier+'">'+p.apai_tier+'</span></div>';
        html += '<div style="font-size:13px;color:var(--text-dim);margin-bottom:16px;">'+esc(p.description||'')+'</div>';
        if (!cards.length) {
            html += '<p style="color:var(--text-dim);font-size:13px;">No published terms cards available.</p>';
        } else {
            html += '<h3 style="font-size:14px;margin-bottom:12px;">Available Credentials</h3>';
            cards.forEach(c => {
                html += '<div class="terms-card-item published" style="margin-bottom:8px;">';
                html += '<div style="font-weight:600;font-size:13px;">'+esc(c.credential_label)+'</div>';
                html += '<div style="font-size:12px;color:var(--text-dim);margin:4px 0;">'+c.credential_type+' &middot; '+c.provider_system+'</div>';
                html += '<div style="font-size:12px;color:var(--text-dim);">Query fee: $'+c.pricing.per_query_fee_usd.toFixed(2)+' &middot; Split: '+c.pricing.revenue_split.router_pct+'% / '+c.pricing.revenue_split.host_pct+'%</div>';
                html += '<div style="font-size:11px;color:var(--text-dim);margin-top:4px;">Markets: '+(c.coverage.markets_included.join(', ')||'All')+'</div>';
                html += '<button class="btn btn-primary" onclick="requestConnection('+id+','+c.id+')" style="margin-top:8px;padding:6px 16px;font-size:11px;">Request Connection</button>';
                html += '</div>';
            });
        }
        // Show in a simple modal
        const modal = document.getElementById('net-terms-modal');
        modal.querySelector('div > div').innerHTML = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:24px;"><h2 style="font-size:18px;">Provider Details</h2><button onclick="hideTermsModal()" style="background:none;border:none;color:var(--text-dim);font-size:20px;cursor:pointer;">&times;</button></div>' + html;
        modal.style.display = 'flex';
    } catch(e) { console.error('View provider error:', e); }
}

async function requestConnection(profileId, termsId) {
    const msg = prompt('Optional message to the provider:');
    try {
        const r = await fetch(API_BASE + '/api/v1/network/connections', {
            method: 'POST', headers,
            body: JSON.stringify({provider_profile_id: profileId, terms_card_id: termsId, message: msg||''})
        });
        const data = await r.json();
        if (r.ok) { showToast('Connection requested!', 'success'); hideTermsModal(); loadConnections(); }
        else showToast(data.error || 'Failed', 'error');
    } catch(e) { showToast('Error: '+e.message, 'error'); }
}

async function loadConnections() {
    const role = document.getElementById('net-conn-role').value;
    const status = document.getElementById('net-conn-status').value;
    let url = API_BASE + '/api/v1/network/connections?';
    if (role) url += 'role=' + role + '&';
    if (status) url += 'status=' + status;
    try {
        const r = await fetch(url, {headers});
        const data = await r.json();
        const el = document.getElementById('net-conn-list');
        if (!data.connections.length) {
            el.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text-dim);font-size:13px;">No connections found.</div>';
            return;
        }
        el.innerHTML = data.connections.map(c => {
            let actions = '';
            if (c.status === 'pending' && c.role === 'provider') {
                actions = '<button class="btn btn-primary" onclick="connAction('+c.id+\\',"accept\\')" style="padding:4px 12px;font-size:11px;">Accept</button> <button class="btn" onclick="connAction('+c.id+\\',"reject\\')" style="padding:4px 12px;font-size:11px;">Reject</button>';
            } else if (c.status === 'active') {
                actions = '<button class="btn" onclick="connAction('+c.id+\\',"pause\\')" style="padding:4px 12px;font-size:11px;">Pause</button> <button class="btn" onclick="connDisconnect('+c.id+')" style="padding:4px 12px;font-size:11px;color:var(--danger);">Disconnect</button>';
            } else if (c.status === 'paused') {
                actions = '<button class="btn btn-primary" onclick="connAction('+c.id+\\',"resume\\')" style="padding:4px 12px;font-size:11px;">Resume</button> <button class="btn" onclick="connDisconnect('+c.id+')" style="padding:4px 12px;font-size:11px;color:var(--danger);">Disconnect</button>';
            }
            const ts = c.terms_summary || {};
            return '<div class="conn-card"><div><div style="font-weight:500;font-size:14px;">'+(c.role==='requester'?'→ '+c.provider_key_hash:'← '+c.requester_key_hash)+'</div><div style="font-size:12px;color:var(--text-dim);">'+esc(ts.credential_label||'')+(ts.provider_system?' ('+ts.provider_system+')':'')+'</div><div style="font-size:11px;color:var(--text-dim);margin-top:4px;">'+c.stats.queries_this_month+' queries &middot; '+c.stats.bookings_this_month+' bookings &middot; $'+c.stats.revenue_earned_this_month_usd.toFixed(2)+' earned</div></div><div style="display:flex;align-items:center;gap:12px;"><span class="status-pill '+c.status+'">'+c.status+'</span><span class="health-dot '+c.health+'" title="Health: '+c.health+'"></span>'+actions+'</div></div>';
        }).join('');
    } catch(e) { console.error('Connections error:', e); }
}

async function connAction(id, action) {
    try {
        const r = await fetch(API_BASE + '/api/v1/network/connections/' + id + '/' + action, {method:'POST', headers});
        if (r.ok) { showToast('Connection ' + action + 'ed', 'success'); loadConnections(); loadNetworkStats(); }
        else { const d = await r.json(); showToast(d.error||'Failed', 'error'); }
    } catch(e) { showToast('Error: '+e.message, 'error'); }
}

async function connDisconnect(id) {
    if (!confirm('Disconnect this connection?')) return;
    try {
        const r = await fetch(API_BASE + '/api/v1/network/connections/' + id, {method:'DELETE', headers});
        if (r.ok) { showToast('Disconnected', 'success'); loadConnections(); loadNetworkStats(); }
    } catch(e) { showToast('Error: '+e.message, 'error'); }
}

async function loadTermsCards() {
    try {
        const r = await fetch(API_BASE + '/api/v1/network/terms', {headers});
        const data = await r.json();
        const el = document.getElementById('net-terms-list');
        if (!data.terms_cards.length) {
            el.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text-dim);font-size:13px;">No terms cards yet. Create one to list your credentials on the network.</div>';
            return;
        }
        el.innerHTML = data.terms_cards.map(c =>
            '<div class="terms-card-item '+(c.is_published?'published':'draft')+'">' +
            '<div style="display:flex;justify-content:space-between;align-items:flex-start;">' +
            '<div><div style="font-weight:600;font-size:14px;">'+esc(c.credential_label)+'</div><div style="font-size:12px;color:var(--text-dim);margin-top:2px;">'+c.credential_type+' &middot; '+c.provider_system+'</div></div>' +
            '<div style="display:flex;gap:6px;"><span style="font-size:11px;color:'+(c.is_published?'var(--success)':'var(--text-dim)')+';">'+(c.is_published?'Published':'Draft')+'</span></div></div>' +
            '<div style="display:flex;gap:16px;margin-top:8px;font-size:12px;color:var(--text-dim);">' +
            '<span>$'+c.pricing.per_query_fee_usd.toFixed(2)+'/query</span>' +
            '<span>'+c.pricing.revenue_split.router_pct+'% / '+c.pricing.revenue_split.host_pct+'% split</span>' +
            '<span>'+(c.coverage.markets_included.join(', ')||'All markets')+'</span></div>' +
            '<div style="margin-top:10px;display:flex;gap:8px;"><button class="btn" onclick="editTermsCard('+c.id+')" style="padding:4px 12px;font-size:11px;">Edit</button><button class="btn" onclick="deleteTermsCard('+c.id+')" style="padding:4px 12px;font-size:11px;color:var(--danger);">Delete</button></div></div>'
        ).join('');
    } catch(e) { console.error('Terms error:', e); }
}

function showCreateTerms() {
    document.getElementById('tm-edit-id').value = '';
    document.getElementById('net-terms-modal-title').textContent = 'New Terms Card';
    // Reset form
    ['tm-label','tm-query-fee','tm-router-pct','tm-host-pct','tm-min-booking','tm-min-margin','tm-markets-in','tm-markets-ex','tm-airlines-in','tm-airlines-ex','tm-cabins','tm-trips','tm-max-qday','tm-max-qhr','tm-max-bday','tm-sla','tm-err-rate','tm-trial','tm-notice','tm-min-vol','tm-markup-cap'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = el.defaultValue || '';
    });
    document.getElementById('tm-type').value = 'gds';
    document.getElementById('tm-system').value = 'amadeus';
    document.getElementById('tm-exclusive').checked = false;
    document.getElementById('tm-auto-renew').checked = true;
    document.getElementById('tm-pos-arb').checked = true;
    document.getElementById('tm-published').checked = false;
    document.getElementById('net-terms-modal').style.display = 'flex';
}

function hideTermsModal() {
    document.getElementById('net-terms-modal').style.display = 'none';
}

function parseCSV(val) { return (val||'').split(',').map(s=>s.trim()).filter(Boolean); }

async function saveTermsCard() {
    const editId = document.getElementById('tm-edit-id').value;
    const body = {
        credential_label: document.getElementById('tm-label').value,
        credential_type: document.getElementById('tm-type').value,
        provider_system: document.getElementById('tm-system').value,
        pricing: {
            per_query_fee_usd: parseFloat(document.getElementById('tm-query-fee').value)||0,
            revenue_split: {
                router_pct: parseFloat(document.getElementById('tm-router-pct').value)||70,
                host_pct: parseFloat(document.getElementById('tm-host-pct').value)||30,
            },
            min_booking_value_usd: parseFloat(document.getElementById('tm-min-booking').value)||null,
            min_margin_usd: parseFloat(document.getElementById('tm-min-margin').value)||null,
        },
        coverage: {
            markets_included: parseCSV(document.getElementById('tm-markets-in').value),
            markets_excluded: parseCSV(document.getElementById('tm-markets-ex').value),
            airlines_included: parseCSV(document.getElementById('tm-airlines-in').value),
            airlines_excluded: parseCSV(document.getElementById('tm-airlines-ex').value),
            cabin_classes: parseCSV(document.getElementById('tm-cabins').value),
            trip_types: parseCSV(document.getElementById('tm-trips').value),
        },
        limits: {
            max_queries_per_day: parseInt(document.getElementById('tm-max-qday').value)||null,
            max_queries_per_hour: parseInt(document.getElementById('tm-max-qhr').value)||null,
            max_bookings_per_day: parseInt(document.getElementById('tm-max-bday').value)||null,
            response_time_sla_sec: parseFloat(document.getElementById('tm-sla').value)||8.0,
            auto_pause_error_rate_pct: parseFloat(document.getElementById('tm-err-rate').value)||15,
        },
        relationship: {
            is_exclusive: document.getElementById('tm-exclusive').checked,
            auto_renew: document.getElementById('tm-auto-renew').checked,
            trial_period_days: parseInt(document.getElementById('tm-trial').value)||0,
            notice_period_days: parseInt(document.getElementById('tm-notice').value)||30,
            min_monthly_volume: parseInt(document.getElementById('tm-min-vol').value)||null,
        },
        arbitrage: {
            allow_pos_arbitrage: document.getElementById('tm-pos-arb').checked,
            markup_cap_pct: parseFloat(document.getElementById('tm-markup-cap').value)||null,
            price_visibility: document.getElementById('tm-visibility').value,
        },
        is_published: document.getElementById('tm-published').checked,
    };
    const method = editId ? 'PUT' : 'POST';
    const url = API_BASE + '/api/v1/network/terms' + (editId ? '/' + editId : '');
    try {
        const r = await fetch(url, {method, headers, body: JSON.stringify(body)});
        const data = await r.json();
        if (r.ok) { showToast('Terms card saved!', 'success'); hideTermsModal(); loadTermsCards(); }
        else showToast(data.error || 'Failed to save', 'error');
    } catch(e) { showToast('Error: '+e.message, 'error'); }
}

async function editTermsCard(id) {
    // Fetch current terms and populate modal
    try {
        const r = await fetch(API_BASE + '/api/v1/network/terms', {headers});
        const data = await r.json();
        const card = data.terms_cards.find(c => c.id === id);
        if (!card) return;
        document.getElementById('tm-edit-id').value = id;
        document.getElementById('net-terms-modal-title').textContent = 'Edit Terms Card';
        document.getElementById('tm-label').value = card.credential_label;
        document.getElementById('tm-type').value = card.credential_type;
        document.getElementById('tm-system').value = card.provider_system;
        document.getElementById('tm-query-fee').value = card.pricing.per_query_fee_usd;
        document.getElementById('tm-router-pct').value = card.pricing.revenue_split.router_pct;
        document.getElementById('tm-host-pct').value = card.pricing.revenue_split.host_pct;
        document.getElementById('tm-min-booking').value = card.pricing.min_booking_value_usd||'';
        document.getElementById('tm-min-margin').value = card.pricing.min_margin_usd||'';
        document.getElementById('tm-markets-in').value = (card.coverage.markets_included||[]).join(', ');
        document.getElementById('tm-markets-ex').value = (card.coverage.markets_excluded||[]).join(', ');
        document.getElementById('tm-airlines-in').value = (card.coverage.airlines_included||[]).join(', ');
        document.getElementById('tm-airlines-ex').value = (card.coverage.airlines_excluded||[]).join(', ');
        document.getElementById('tm-cabins').value = (card.coverage.cabin_classes||[]).join(', ');
        document.getElementById('tm-trips').value = (card.coverage.trip_types||[]).join(', ');
        document.getElementById('tm-max-qday').value = card.limits.max_queries_per_day||'';
        document.getElementById('tm-max-qhr').value = card.limits.max_queries_per_hour||'';
        document.getElementById('tm-max-bday').value = card.limits.max_bookings_per_day||'';
        document.getElementById('tm-sla').value = card.limits.response_time_sla_sec;
        document.getElementById('tm-err-rate').value = card.limits.auto_pause_error_rate_pct;
        document.getElementById('tm-trial').value = card.relationship.trial_period_days;
        document.getElementById('tm-notice').value = card.relationship.notice_period_days;
        document.getElementById('tm-min-vol').value = card.relationship.min_monthly_volume||'';
        document.getElementById('tm-exclusive').checked = card.relationship.is_exclusive;
        document.getElementById('tm-auto-renew').checked = card.relationship.auto_renew;
        document.getElementById('tm-pos-arb').checked = card.arbitrage.allow_pos_arbitrage;
        document.getElementById('tm-markup-cap').value = card.arbitrage.markup_cap_pct||'';
        document.getElementById('tm-visibility').value = card.arbitrage.price_visibility;
        document.getElementById('tm-published').checked = card.is_published;
        document.getElementById('net-terms-modal').style.display = 'flex';
    } catch(e) { showToast('Error loading card: '+e.message, 'error'); }
}

async function deleteTermsCard(id) {
    if (!confirm('Delete this terms card?')) return;
    try {
        const r = await fetch(API_BASE + '/api/v1/network/terms/' + id, {method:'DELETE', headers});
        const data = await r.json();
        if (r.ok) { showToast('Deleted', 'success'); loadTermsCards(); }
        else showToast(data.error || 'Failed', 'error');
    } catch(e) { showToast('Error: '+e.message, 'error'); }
}

async function loadProfile() {
    try {
        const r = await fetch(API_BASE + '/api/v1/network/profile', {headers});
        const data = await r.json();
        document.getElementById('np-name').value = data.display_name || '';
        document.getElementById('np-email').value = data.contact_email || '';
        document.getElementById('np-desc').value = data.description || '';
        document.getElementById('np-logo').value = data.logo_url || '';
        document.getElementById('np-website').value = data.website_url || '';
        document.getElementById('np-visible').checked = data.is_accepting_connections !== false;
        document.getElementById('np-accepting').checked = data.is_accepting_connections !== false;
    } catch(e) { console.error('Profile load error:', e); }
}

async function saveProfile() {
    try {
        const r = await fetch(API_BASE + '/api/v1/network/profile', {
            method: 'PUT', headers,
            body: JSON.stringify({
                display_name: document.getElementById('np-name').value,
                contact_email: document.getElementById('np-email').value,
                description: document.getElementById('np-desc').value,
                logo_url: document.getElementById('np-logo').value,
                website_url: document.getElementById('np-website').value,
                is_visible: document.getElementById('np-visible').checked,
                is_accepting_connections: document.getElementById('np-accepting').checked,
            })
        });
        if (r.ok) showToast('Profile saved!', 'success');
        else { const d = await r.json(); showToast(d.error||'Failed', 'error'); }
    } catch(e) { showToast('Error: '+e.message, 'error'); }
}

async function loadAudit(page) {
    page = page || 1;
    const type = document.getElementById('net-audit-type').value;
    let url = API_BASE + '/api/v1/network/audit?page=' + page + '&per_page=25';
    if (type) url += '&event_type=' + type;
    try {
        const r = await fetch(url, {headers});
        const data = await r.json();

        // Tier gate — show upgrade prompt if locked
        if (r.status === 403 && data.upgrade_required) {
            const tbody = document.getElementById('net-audit-body');
            tbody.innerHTML = '<tr><td colspan="6" style="padding:40px;text-align:center;">' +
                '<div style="font-size:14px;color:var(--text-dim);margin-bottom:8px;">&#128274; ' + esc(data.error) + '</div>' +
                '<div style="font-size:12px;color:var(--text-dim);opacity:0.7;">Upgrade to Enterprise to access the full transaction audit trail.</div></td></tr>';
            return;
        }

        const tbody = document.getElementById('net-audit-body');
        if (!data.events || !data.events.length) {
            tbody.innerHTML = '<tr><td colspan="6" style="padding:20px;text-align:center;color:var(--text-dim);font-size:13px;">No events yet.</td></tr>';
            return;
        }
        tbody.innerHTML = data.events.map(e => {
            const time = e.created_at ? new Date(e.created_at).toLocaleString() : '-';
            return '<tr style="border-bottom:1px solid var(--border);">' +
                '<td style="padding:8px;">'+time+'</td>' +
                '<td style="padding:8px;"><span class="status-pill '+(e.success?'active':'')+'">'+e.event_type+'</span></td>' +
                '<td style="padding:8px;">'+(e.route||'-')+'</td>' +
                '<td style="padding:8px;">$'+e.query_fee_usd.toFixed(4)+'</td>' +
                '<td style="padding:8px;">'+(e.transaction_amount_usd ? '$'+e.transaction_amount_usd.toFixed(2) : '-')+'</td>' +
                '<td style="padding:8px;">'+(e.success ? '<span style="color:var(--success);">OK</span>' : '<span style="color:var(--danger);">FAIL</span>')+'</td></tr>';
        }).join('');
    } catch(e) { console.error('Audit error:', e); }
}

// ===================================================================
// TERMINAL TAB JS
// ===================================================================

let termCurrentSession = null;

async function termNewSession() {
    try {
        const r = await fetch(API_BASE + '/api/v1/dev/sessions', {method:'POST', headers, body:'{}'});
        const data = await r.json();
        if (data.session_id) {
            termCurrentSession = data.session_id;
            document.getElementById('term-session-title').textContent = 'New Session';
            document.getElementById('term-messages').innerHTML = '<div class="assist-msg assist-system" style="align-self:flex-start;max-width:85%;padding:16px;background:var(--card);border:1px solid var(--border);border-radius:12px;"><div style="font-size:13px;color:var(--text-dim);">Session started. How can I help?</div></div>';
            loadTermSessions();
        }
    } catch(e) { showToast('Failed to create session: '+e.message, 'error'); }
}

async function termCloseSession() {
    if (!termCurrentSession) return;
    try {
        await fetch(API_BASE + '/api/v1/dev/sessions/' + termCurrentSession + '/close', {method:'POST', headers});
        termCurrentSession = null;
        loadTermSessions();
    } catch(e) {}
}

async function loadTermSessions() {
    try {
        const r = await fetch(API_BASE + '/api/v1/dev/sessions', {headers});
        const data = await r.json();
        const sessions = data.sessions || [];
        const el = document.getElementById('term-sessions');
        let totalQ = 0;
        el.innerHTML = sessions.map(s => {
            totalQ += s.queries_used||0;
            return '<div class="term-session-item'+(s.session_id===termCurrentSession?' active':'')+'" onclick="termLoadSession(\\''+s.session_id+'\\')">' +
                '<div style="font-size:12px;font-weight:500;">'+(s.title||'Untitled')+'</div>' +
                '<div style="font-size:10px;color:var(--text-dim);margin-top:2px;">'+s.message_count+' messages &middot; '+s.queries_used+' queries</div></div>';
        }).join('');
        document.getElementById('term-total-queries').textContent = totalQ;
    } catch(e) {}
}

function termLoadSession(sessionId) {
    termCurrentSession = sessionId;
    document.querySelectorAll('.term-session-item').forEach(el => el.classList.remove('active'));
    // Load session messages (via existing dev session endpoint)
    loadTermSessions();
}

function termSendFromInput() {
    const input = document.getElementById('term-input');
    const msg = input.value.trim();
    if (!msg) return;
    input.value = '';
    termSend(msg);
}

async function termSend(msg) {
    if (!termCurrentSession) await termNewSession();
    if (!termCurrentSession) return;

    // Add user message
    const msgEl = document.getElementById('term-messages');
    msgEl.innerHTML += '<div class="assist-msg assist-user" style="align-self:flex-end;max-width:85%;padding:12px 16px;background:var(--accent);color:#fff;border-radius:12px;border-bottom-right-radius:4px;font-size:13px;">'+esc(msg)+'</div>';
    msgEl.scrollTop = msgEl.scrollHeight;

    // Send to API
    try {
        const r = await fetch(API_BASE + '/api/v1/dev/sessions/' + termCurrentSession + '/message', {
            method: 'POST', headers,
            body: JSON.stringify({message: msg})
        });
        const data = await r.json();
        const reply = data.response || data.message || 'No response';
        msgEl.innerHTML += '<div class="assist-msg assist-bot" style="align-self:flex-start;max-width:85%;padding:12px 16px;background:var(--card-hover);border:1px solid var(--border);border-radius:12px;border-bottom-left-radius:4px;font-size:13px;line-height:1.6;white-space:pre-wrap;">'+esc(reply)+'</div>';
        msgEl.scrollTop = msgEl.scrollHeight;
        // Update query count
        if (data.queries_used !== undefined) {
            document.getElementById('term-session-queries').textContent = data.queries_used + ' queries';
        }
    } catch(e) {
        msgEl.innerHTML += '<div class="assist-msg" style="align-self:flex-start;max-width:85%;padding:12px;color:var(--danger);font-size:13px;">Error: '+esc(e.message)+'</div>';
    }
}

// ===================================================================
// MODULES TAB JS
// ===================================================================

async function loadModules() {
    try {
        const r = await fetch(API_BASE + '/api/v1/dev/modules', {headers});
        const data = await r.json();
        const modules = data.modules || [];
        const list = document.getElementById('mod-list');
        const empty = document.getElementById('mod-empty');
        if (!modules.length) { list.innerHTML = ''; empty.style.display = 'block'; return; }
        empty.style.display = 'none';
        list.innerHTML = modules.map(m =>
            '<div class="module-card">' +
            '<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px;">' +
            '<div style="font-weight:600;font-size:14px;">'+esc(m.name)+'</div>' +
            '<span class="module-status '+m.status+'">'+m.status+'</span></div>' +
            '<div style="font-size:12px;color:var(--text-dim);margin-bottom:8px;">'+esc(m.description||'')+'</div>' +
            '<div style="display:flex;gap:12px;font-size:11px;color:var(--text-dim);">' +
            '<span>v'+m.version+'</span><span>'+m.module_type+'</span>' +
            (m.marketplace_installs>0?'<span>'+m.marketplace_installs+' installs</span>':'') +
            '</div></div>'
        ).join('');
    } catch(e) { console.error('Modules error:', e); }
}

// Escape HTML
function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

</script>
"""


def get_network_tabs_html():
    """Return the three tab button HTML strings."""
    return (
        '<div class="tab" onclick="switchTab(\'network\')">Network</div>'
        '<div class="tab" onclick="switchTab(\'terminal\')" '
        'style="background:linear-gradient(135deg,#7c3aed,#4f46e5);'
        'color:#fff;border-color:#7c3aed;">Terminal</div>'
        '<div class="tab" onclick="switchTab(\'modules\')">Modules</div>'
    )


def inject_network_ui(dashboard_html):
    """
    Inject network, terminal, and modules tabs into the admin dashboard HTML.

    Inserts:
      1. Three new tab buttons after the ANASTASiA tab button
      2. NETWORK_CSS before </head>
      3. Three tab-content divs before the closing </div> of .container
      4. NETWORK_JS before </body>
      5. Lazy-load hooks in the switchTab override

    Returns the modified HTML string.
    """
    html = dashboard_html

    # 1. Add tab buttons after the ANASTASiA tab
    anastasia_tab = (
        '<div class="tab" onclick="switchTab(\'assistant\')" '
        'style="background: linear-gradient(135deg, #7c3aed, #6366f1); '
        'color: #fff; border-color: #7c3aed;">ANASTASiA</div>'
    )
    html = html.replace(
        anastasia_tab,
        anastasia_tab + '\n        ' + get_network_tabs_html(),
    )

    # 2. Inject CSS before </head>
    html = html.replace('</head>', NETWORK_CSS + '\n</head>')

    # 3. Inject tab content divs before the closing </div> of .container
    # The container ends right before the first <style> after the tabs
    # We insert after the assistant tab closing </div>
    assistant_end = '    <!-- ASSISTANT TAB -->'
    # Actually, insert all three tab contents right before </div>\n\n<style>
    # which marks the end of the .container and start of assist-msg styles
    insert_marker = '</div>\n\n<style>\n    .assist-msg {'
    html = html.replace(
        insert_marker,
        NETWORK_TAB_HTML + TERMINAL_TAB_HTML + MODULES_TAB_HTML
        + '\n</div>\n\n<style>\n    .assist-msg {',
    )

    # 4. Inject JS before </body>
    html = html.replace('</body>', NETWORK_JS + '\n</body>')

    # 5. Add lazy-load hooks to switchTab override
    old_override = """switchTab = function(name) {
    _origSwitchTab(name);
    if (name === 'analytics') loadAnalytics();
    if (name === 'billing') loadBilling();
};"""
    new_override = """switchTab = function(name) {
    _origSwitchTab(name);
    if (name === 'analytics') loadAnalytics();
    if (name === 'billing') loadBilling();
    if (name === 'network') loadNetworkStats();
    if (name === 'terminal') loadTermSessions();
    if (name === 'modules') loadModules();
};"""
    html = html.replace(old_override, new_override)

    return html
