"""
Builds #235-237 — Corporate Workspaces (Travel+ Business)

"Slack for Travel" — companies buy per-seat travel management for employees.
Admin controls, travel policies, approval workflows, book-on-behalf, export.

Build #235 — Workspace Model + Admin + Roles + Invites:
  POST   /api/workspaces                          — create workspace
  GET    /api/workspaces                          — list my workspaces
  GET    /api/workspaces/<slug>                   — get workspace detail
  PUT    /api/workspaces/<slug>                   — update workspace settings
  POST   /api/workspaces/<slug>/members           — invite member (by email)
  GET    /api/workspaces/<slug>/members           — list members
  PUT    /api/workspaces/<slug>/members/<mid>     — update member role/type/dept
  DELETE /api/workspaces/<slug>/members/<mid>     — remove member
  POST   /api/workspaces/join/<code>              — join via invite code

Build #236 — Travel Policies + Approval Workflows + Expense Tags:
  POST   /api/workspaces/<slug>/policies          — create policy
  GET    /api/workspaces/<slug>/policies          — list policies
  PUT    /api/workspaces/<slug>/policies/<pid>    — update policy
  DELETE /api/workspaces/<slug>/policies/<pid>    — delete policy
  POST   /api/workspaces/<slug>/approvals         — request approval
  GET    /api/workspaces/<slug>/approvals         — list approvals (filtered)
  PUT    /api/workspaces/<slug>/approvals/<aid>   — approve or deny

Build #237 — Corporate Dashboard + Book-on-Behalf + Export:
  GET    /api/workspaces/<slug>/dashboard         — spending summary + charts
  POST   /api/workspaces/<slug>/book-on-behalf    — book for another member
  GET    /api/workspaces/<slug>/bookings          — all workspace bookings
  GET    /api/workspaces/<slug>/export             — CSV export of bookings

Registration: register_corporate_routes(app, csrf, limiter)
"""

import csv
import io
import json
import logging
import secrets
from datetime import datetime, timezone

from flask import request, jsonify, Response, render_template_string, redirect, url_for
from flask_login import current_user, login_required

from models import (
    db, User, Booking, FeatureFlag, TripPlan, TripMember, ItineraryItem,
    Workspace, WorkspaceMember, TravelPolicy, BookingApproval,
)

logger = logging.getLogger(__name__)


def _utcnow():
    return datetime.now(timezone.utc)


def _check_flag(flag_key):
    """Return error response if flag is disabled, else None."""
    if not FeatureFlag.is_flag_enabled(flag_key):
        return jsonify({
            'status': 'error',
            'error': f'Feature "{flag_key}" is not enabled',
        }), 403
    return None


def _get_workspace(slug):
    """Fetch workspace by slug, return (workspace, error_response)."""
    ws = Workspace.query.filter_by(slug=slug, is_active=True).first()
    if not ws:
        return None, (jsonify({'status': 'error', 'error': 'Workspace not found'}), 404)
    return ws, None


def _get_membership(ws):
    """Get current user's membership in workspace, return (member, error_response)."""
    member = WorkspaceMember.query.filter_by(
        workspace_id=ws.id, user_id=current_user.id, is_active=True
    ).first()
    if not member:
        return None, (jsonify({'status': 'error', 'error': 'Not a workspace member'}), 403)
    return member, None


def _require_admin(ws):
    """Require admin role in workspace. Returns (member, error_response)."""
    member, err = _get_membership(ws)
    if err:
        return None, err
    if member.role != 'admin':
        return None, (jsonify({'status': 'error', 'error': 'Admin role required'}), 403)
    return member, None


def _require_admin_or_manager(ws):
    """Require admin or travel_manager role."""
    member, err = _get_membership(ws)
    if err:
        return None, err
    if not member.is_admin_or_manager():
        return None, (jsonify({'status': 'error', 'error': 'Admin or travel manager role required'}), 403)
    return member, None


def _generate_invite_code():
    """Generate a unique workspace invite code."""
    for _ in range(10):
        code = f"WS-{secrets.token_hex(4).upper()}"
        if not Workspace.query.filter_by(invite_code=code).first():
            return code
    return f"WS-{secrets.token_hex(6).upper()}"


def _generate_slug(name):
    """Generate a URL-safe slug from workspace name."""
    import re
    slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')[:40]
    if not slug:
        slug = 'workspace'
    base = slug
    counter = 1
    while Workspace.query.filter_by(slug=slug).first():
        slug = f"{base}-{counter}"
        counter += 1
    return slug


# ══════════════════════════════════════════════════════════════
# PAGE TEMPLATES — Corporate Workspace UI (Build #238)
# ══════════════════════════════════════════════════════════════

CORPORATE_LIST_TEMPLATE = """
<style>
/* ============================================
   CORPORATE WORKSPACES — /corporate
   ============================================ */
.corporate-page { max-width: 1060px; margin: 0 auto; padding: 0 16px; }

.corporate-header {
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 24px; flex-wrap: wrap; gap: 12px;
}
.corporate-header h1 {
    font-family: 'Space Grotesk', sans-serif;
    font-size: 28px; font-weight: 700; color: #f5f5f5; margin: 0;
}

/* Workspace grid */
.ws-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: 20px; margin-bottom: 32px;
}
.ws-card {
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 16px; padding: 24px;
    backdrop-filter: blur(12px);
    cursor: pointer; transition: border-color 0.2s, transform 0.15s;
    text-decoration: none; display: block; color: inherit;
}
.ws-card:hover { border-color: rgba(20,184,166,0.4); transform: translateY(-2px); }
.ws-card-top { display: flex; align-items: center; gap: 14px; margin-bottom: 14px; }
.ws-logo {
    width: 48px; height: 48px; border-radius: 12px;
    display: flex; align-items: center; justify-content: center;
    font-family: 'Space Grotesk', sans-serif; font-size: 22px; font-weight: 700;
    color: #fff; flex-shrink: 0;
}
.ws-logo.teal { background: linear-gradient(135deg, #0d9488, #14b8a6); }
.ws-logo.purple { background: linear-gradient(135deg, #6d28d9, #7c3aed); }
.ws-logo.gold { background: linear-gradient(135deg, #b8941f, #C9A96E); }
.ws-card-name {
    font-family: 'Space Grotesk', sans-serif; font-size: 18px; font-weight: 600; color: #f5f5f5;
}
.ws-card-domain { font-size: 13px; color: rgba(255,255,255,0.45); margin-top: 2px; }
.ws-card-meta { display: flex; gap: 10px; flex-wrap: wrap; }
.ws-badge {
    display: inline-flex; align-items: center; gap: 4px;
    padding: 4px 10px; border-radius: 8px; font-size: 12px; font-weight: 600;
}
.ws-badge.role-admin { background: rgba(124,58,237,0.2); color: #a78bfa; }
.ws-badge.role-travel_manager { background: rgba(20,184,166,0.2); color: #5eead4; }
.ws-badge.role-member { background: rgba(255,255,255,0.08); color: rgba(255,255,255,0.6); }
.ws-badge.tier { background: rgba(201,169,110,0.15); color: #C9A96E; }
.ws-badge.members { background: rgba(255,255,255,0.06); color: rgba(255,255,255,0.55); }
.ws-badge .badge-icon { font-size: 13px; }

/* Action bar */
.ws-actions {
    display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 28px;
}
.ws-action-btn {
    background: linear-gradient(135deg, #14b8a6, #0d9488); color: #fff;
    border: none; border-radius: 10px; padding: 10px 20px;
    font-family: 'Outfit', sans-serif; font-size: 14px; font-weight: 600;
    cursor: pointer; transition: opacity 0.2s;
}
.ws-action-btn:hover { opacity: 0.85; }
.ws-action-btn.secondary {
    background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12);
}
.ws-action-btn.secondary:hover { border-color: rgba(255,255,255,0.25); }

/* Forms */
.ws-form-panel {
    background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1);
    border-radius: 16px; padding: 24px; margin-bottom: 24px;
    display: none; backdrop-filter: blur(12px);
}
.ws-form-panel.visible { display: block; }
.ws-form-panel h3 {
    font-family: 'Space Grotesk', sans-serif; font-size: 18px; color: #f5f5f5; margin: 0 0 16px;
}
.ws-form-row { display: flex; gap: 12px; margin-bottom: 12px; flex-wrap: wrap; }
.ws-input {
    background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12);
    border-radius: 10px; padding: 10px 14px; color: #f5f5f5; font-size: 14px;
    font-family: 'Outfit', sans-serif; flex: 1; min-width: 180px;
}
.ws-input:focus { outline: none; border-color: #14b8a6; }
.ws-input::placeholder { color: rgba(255,255,255,0.3); }
select.ws-input { cursor: pointer; }
select.ws-input option { background: #1a1028; color: #f5f5f5; }

/* Join bar */
.ws-join-bar { display: flex; gap: 10px; align-items: center; }

/* Empty state */
.ws-empty {
    text-align: center; padding: 60px 20px;
    color: rgba(255,255,255,0.4); font-size: 15px;
}
.ws-empty-icon { font-size: 48px; margin-bottom: 12px; opacity: 0.3; }

/* Toast */
.ws-toast {
    position: fixed; bottom: 24px; right: 24px;
    background: rgba(20,184,166,0.95); color: #fff; padding: 12px 20px;
    border-radius: 10px; font-size: 14px; font-weight: 600;
    z-index: 9999; opacity: 0; transition: opacity 0.3s;
    pointer-events: none;
}
.ws-toast.error { background: rgba(239,68,68,0.95); }
.ws-toast.show { opacity: 1; }
</style>

<div class="corporate-page">
    <div class="corporate-header">
        <h1>Corporate Workspaces</h1>
    </div>

    <!-- Action buttons -->
    <div class="ws-actions">
        <button class="ws-action-btn" onclick="togglePanel('createPanel')">+ Create Workspace</button>
        <button class="ws-action-btn secondary" onclick="togglePanel('joinPanel')">Join with Code</button>
    </div>

    <!-- Create workspace form -->
    <div id="createPanel" class="ws-form-panel">
        <h3>Create a New Workspace</h3>
        <div class="ws-form-row">
            <input type="text" id="createName" class="ws-input" placeholder="Workspace name" maxlength="200">
            <input type="text" id="createDomain" class="ws-input" placeholder="Company domain (optional)" maxlength="255">
        </div>
        <div class="ws-form-row">
            <select id="createTier" class="ws-input" style="max-width:220px;">
                <option value="starter">Starter ($4.99/seat)</option>
                <option value="pro">Pro ($3.99/seat)</option>
                <option value="enterprise">Enterprise ($2.99/seat)</option>
            </select>
            <button class="ws-action-btn" onclick="createWorkspace()" id="createBtn">Create</button>
        </div>
    </div>

    <!-- Join workspace form -->
    <div id="joinPanel" class="ws-form-panel">
        <h3>Join a Workspace</h3>
        <div class="ws-join-bar">
            <input type="text" id="joinCode" class="ws-input" placeholder="Enter invite code (e.g. WS-A1B2C3D4)" style="max-width:320px;">
            <button class="ws-action-btn" onclick="joinWorkspace()" id="joinBtn">Join</button>
        </div>
    </div>

    <!-- Workspaces grid -->
    <div id="wsGrid" class="ws-grid"></div>
    <div id="wsEmpty" class="ws-empty" style="display:none;">
        <div class="ws-empty-icon">&#9965;</div>
        <div>No workspaces yet. Create one or join with an invite code.</div>
    </div>
</div>

<div id="wsToast" class="ws-toast"></div>

<script>
(function() {
    var csrfToken = document.querySelector('meta[name="csrf-token"]') ? document.querySelector('meta[name="csrf-token"]').content : '';
    var workspaces = [];

    function toast(msg, isError) {
        var el = document.getElementById('wsToast');
        el.textContent = msg;
        el.className = 'ws-toast show' + (isError ? ' error' : '');
        setTimeout(function() { el.className = 'ws-toast'; }, 3000);
    }

    function togglePanel(id) {
        var panel = document.getElementById(id);
        var isVis = panel.classList.contains('visible');
        document.querySelectorAll('.ws-form-panel').forEach(function(p) { p.classList.remove('visible'); });
        if (!isVis) panel.classList.add('visible');
    }
    window.togglePanel = togglePanel;

    function tierColors(tier) {
        if (tier === 'enterprise') return 'gold';
        if (tier === 'pro') return 'purple';
        return 'teal';
    }

    function roleLabel(role) {
        if (role === 'admin') return 'Admin';
        if (role === 'travel_manager') return 'Manager';
        return 'Member';
    }

    function renderWorkspaces() {
        var grid = document.getElementById('wsGrid');
        var empty = document.getElementById('wsEmpty');
        if (!workspaces.length) {
            grid.innerHTML = '';
            empty.style.display = 'block';
            return;
        }
        empty.style.display = 'none';
        var html = '';
        for (var i = 0; i < workspaces.length; i++) {
            var ws = workspaces[i];
            var initial = (ws.name || '?').charAt(0).toUpperCase();
            var colorClass = tierColors(ws.tier);
            html += '<a class="ws-card" href="/corporate/' + encodeURIComponent(ws.slug) + '">';
            html += '<div class="ws-card-top">';
            html += '<div class="ws-logo ' + colorClass + '">' + initial + '</div>';
            html += '<div>';
            html += '<div class="ws-card-name">' + (ws.name || 'Workspace') + '</div>';
            if (ws.company_domain) {
                html += '<div class="ws-card-domain">' + ws.company_domain + '</div>';
            }
            html += '</div></div>';
            html += '<div class="ws-card-meta">';
            html += '<span class="ws-badge role-' + (ws.my_role || 'member') + '">' + roleLabel(ws.my_role) + '</span>';
            html += '<span class="ws-badge tier">' + (ws.tier || 'starter').charAt(0).toUpperCase() + (ws.tier || 'starter').slice(1) + '</span>';
            html += '<span class="ws-badge members"><span class="badge-icon">&#9679;</span> ' + (ws.seat_count || 0) + ' member' + ((ws.seat_count || 0) !== 1 ? 's' : '') + '</span>';
            html += '</div></a>';
        }
        grid.innerHTML = html;
    }

    function loadWorkspaces() {
        fetch('/api/workspaces', {
            headers: { 'X-CSRFToken': csrfToken }
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.status === 'ok') {
                workspaces = data.workspaces || [];
                renderWorkspaces();
            }
        })
        .catch(function() { toast('Failed to load workspaces', true); });
    }

    function createWorkspace() {
        var name = document.getElementById('createName').value.trim();
        if (!name) { toast('Workspace name is required', true); return; }
        var btn = document.getElementById('createBtn');
        btn.disabled = true; btn.textContent = 'Creating...';
        fetch('/api/workspaces', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
            body: JSON.stringify({
                name: name,
                company_domain: document.getElementById('createDomain').value.trim(),
                tier: document.getElementById('createTier').value
            })
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            btn.disabled = false; btn.textContent = 'Create';
            if (data.status === 'ok') {
                toast('Workspace created');
                document.getElementById('createName').value = '';
                document.getElementById('createDomain').value = '';
                document.getElementById('createPanel').classList.remove('visible');
                loadWorkspaces();
            } else {
                toast(data.error || 'Failed to create', true);
            }
        })
        .catch(function() { btn.disabled = false; btn.textContent = 'Create'; toast('Network error', true); });
    }
    window.createWorkspace = createWorkspace;

    function joinWorkspace() {
        var code = document.getElementById('joinCode').value.trim();
        if (!code) { toast('Enter an invite code', true); return; }
        var btn = document.getElementById('joinBtn');
        btn.disabled = true; btn.textContent = 'Joining...';
        fetch('/api/workspaces/join/' + encodeURIComponent(code), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken }
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            btn.disabled = false; btn.textContent = 'Join';
            if (data.status === 'ok') {
                toast('Joined workspace');
                document.getElementById('joinCode').value = '';
                document.getElementById('joinPanel').classList.remove('visible');
                loadWorkspaces();
            } else {
                toast(data.error || 'Failed to join', true);
            }
        })
        .catch(function() { btn.disabled = false; btn.textContent = 'Join'; toast('Network error', true); });
    }
    window.joinWorkspace = joinWorkspace;

    loadWorkspaces();
})();
</script>
"""


CORPORATE_DETAIL_TEMPLATE = """
<style>
/* ============================================
   CORPORATE WORKSPACE DETAIL — /corporate/<slug>
   5-tab layout: Dashboard, Members, Policies, Approvals, Bookings
   ============================================ */
.corp-detail { max-width: 1100px; margin: 0 auto; padding: 0 16px; }

/* Workspace header */
.corp-ws-header {
    display: flex; align-items: center; gap: 16px; margin-bottom: 20px; flex-wrap: wrap;
}
.corp-ws-logo {
    width: 56px; height: 56px; border-radius: 14px;
    display: flex; align-items: center; justify-content: center;
    font-family: 'Space Grotesk', sans-serif; font-size: 26px; font-weight: 700; color: #fff;
}
.corp-ws-logo.teal { background: linear-gradient(135deg, #0d9488, #14b8a6); }
.corp-ws-logo.purple { background: linear-gradient(135deg, #6d28d9, #7c3aed); }
.corp-ws-logo.gold { background: linear-gradient(135deg, #b8941f, #C9A96E); }
.corp-ws-title {
    font-family: 'Space Grotesk', sans-serif; font-size: 26px; font-weight: 700; color: #f5f5f5; margin: 0;
}
.corp-ws-subtitle { font-size: 13px; color: rgba(255,255,255,0.4); margin-top: 2px; }
.corp-back-link {
    color: rgba(255,255,255,0.45); text-decoration: none; font-size: 13px;
    margin-bottom: 16px; display: inline-block;
}
.corp-back-link:hover { color: #14b8a6; }

/* Tabs */
.corp-tabs {
    display: flex; gap: 0; border-bottom: 1px solid rgba(255,255,255,0.08);
    margin-bottom: 24px; overflow-x: auto;
}
.corp-tab {
    padding: 10px 20px; font-family: 'Outfit', sans-serif; font-size: 14px; font-weight: 600;
    color: rgba(255,255,255,0.45); cursor: pointer; border-bottom: 2px solid transparent;
    transition: color 0.2s, border-color 0.2s; white-space: nowrap; background: none; border-top: none; border-left: none; border-right: none;
}
.corp-tab:hover { color: rgba(255,255,255,0.7); }
.corp-tab.active { color: #14b8a6; border-bottom-color: #14b8a6; }
.corp-tab-panel { display: none; }
.corp-tab-panel.active { display: block; }

/* Stat cards */
.corp-stats {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 16px; margin-bottom: 28px;
}
.corp-stat-card {
    background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08);
    border-radius: 14px; padding: 20px; backdrop-filter: blur(12px); text-align: center;
}
.corp-stat-value {
    font-family: 'Space Grotesk', sans-serif; font-size: 28px; font-weight: 700; color: #14b8a6;
}
.corp-stat-value.gold { color: #C9A96E; }
.corp-stat-value.purple { color: #a78bfa; }
.corp-stat-label {
    font-size: 12px; color: rgba(255,255,255,0.4); margin-top: 4px; text-transform: uppercase; letter-spacing: 0.5px;
}

/* Bar chart (dept spend) */
.corp-chart { margin-bottom: 28px; }
.corp-chart-title {
    font-family: 'Space Grotesk', sans-serif; font-size: 16px; font-weight: 600;
    color: #f5f5f5; margin-bottom: 12px;
}
.corp-bar-row {
    display: flex; align-items: center; gap: 12px; margin-bottom: 8px;
}
.corp-bar-label {
    width: 120px; font-size: 13px; color: rgba(255,255,255,0.6); text-align: right;
    flex-shrink: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.corp-bar-track {
    flex: 1; height: 24px; background: rgba(255,255,255,0.04); border-radius: 6px; overflow: hidden;
}
.corp-bar-fill {
    height: 100%; background: linear-gradient(90deg, #14b8a6, #0d9488); border-radius: 6px;
    display: flex; align-items: center; padding-left: 8px;
    font-size: 12px; font-weight: 600; color: #fff; min-width: 40px; transition: width 0.5s;
}

/* Tables */
.corp-table-wrap {
    background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08);
    border-radius: 14px; overflow: hidden; margin-bottom: 20px;
}
.corp-table {
    width: 100%; border-collapse: collapse; font-size: 13px;
}
.corp-table th {
    text-align: left; padding: 12px 16px; font-size: 11px; text-transform: uppercase;
    letter-spacing: 0.5px; color: rgba(255,255,255,0.4);
    border-bottom: 1px solid rgba(255,255,255,0.06);
    font-weight: 600;
}
.corp-table td {
    padding: 12px 16px; color: rgba(255,255,255,0.75);
    border-bottom: 1px solid rgba(255,255,255,0.04);
}
.corp-table tr:last-child td { border-bottom: none; }
.corp-table tr:hover td { background: rgba(255,255,255,0.02); }

/* Badges */
.cbadge {
    display: inline-block; padding: 3px 10px; border-radius: 8px;
    font-size: 11px; font-weight: 600;
}
.cbadge-admin { background: rgba(124,58,237,0.2); color: #a78bfa; }
.cbadge-travel_manager { background: rgba(20,184,166,0.2); color: #5eead4; }
.cbadge-member { background: rgba(255,255,255,0.08); color: rgba(255,255,255,0.6); }
.cbadge-employee { background: rgba(59,130,246,0.15); color: #93c5fd; }
.cbadge-contractor { background: rgba(245,158,11,0.15); color: #fcd34d; }
.cbadge-affiliate { background: rgba(201,169,110,0.15); color: #C9A96E; }
.cbadge-pending { background: rgba(245,158,11,0.15); color: #fcd34d; }
.cbadge-approved { background: rgba(34,197,94,0.15); color: #86efac; }
.cbadge-denied { background: rgba(239,68,68,0.15); color: #fca5a5; }
.cbadge-booked { background: rgba(20,184,166,0.15); color: #5eead4; }
.cbadge-completed { background: rgba(34,197,94,0.15); color: #86efac; }

/* Glass card generic */
.corp-glass {
    background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08);
    border-radius: 14px; padding: 20px; backdrop-filter: blur(12px); margin-bottom: 16px;
}

/* Action buttons */
.corp-btn {
    background: linear-gradient(135deg, #14b8a6, #0d9488); color: #fff;
    border: none; border-radius: 8px; padding: 8px 16px;
    font-family: 'Outfit', sans-serif; font-size: 13px; font-weight: 600;
    cursor: pointer; transition: opacity 0.2s;
}
.corp-btn:hover { opacity: 0.85; }
.corp-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.corp-btn.small { padding: 5px 12px; font-size: 12px; }
.corp-btn.danger { background: linear-gradient(135deg, #ef4444, #dc2626); }
.corp-btn.secondary {
    background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12);
}
.corp-btn.ghost {
    background: none; border: 1px solid rgba(255,255,255,0.12); color: rgba(255,255,255,0.6);
}
.corp-btn.ghost:hover { border-color: rgba(255,255,255,0.25); }

/* Inline forms */
.corp-form-row { display: flex; gap: 10px; margin-bottom: 10px; flex-wrap: wrap; align-items: center; }
.corp-input {
    background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12);
    border-radius: 8px; padding: 8px 12px; color: #f5f5f5; font-size: 13px;
    font-family: 'Outfit', sans-serif;
}
.corp-input:focus { outline: none; border-color: #14b8a6; }
.corp-input::placeholder { color: rgba(255,255,255,0.3); }
select.corp-input { cursor: pointer; }
select.corp-input option { background: #1a1028; color: #f5f5f5; }
textarea.corp-input { resize: vertical; min-height: 60px; }

/* Inline form panels */
.corp-inline-form {
    background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.1);
    border-radius: 12px; padding: 16px; margin-bottom: 16px; display: none;
}
.corp-inline-form.visible { display: block; }
.corp-inline-form h4 {
    font-family: 'Space Grotesk', sans-serif; font-size: 15px; color: #f5f5f5; margin: 0 0 12px;
}

/* Filter pills */
.corp-filters { display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }
.corp-pill {
    padding: 6px 14px; border-radius: 20px; font-size: 12px; font-weight: 600;
    cursor: pointer; transition: all 0.2s;
    background: rgba(255,255,255,0.06); color: rgba(255,255,255,0.5);
    border: 1px solid rgba(255,255,255,0.08);
}
.corp-pill:hover { color: rgba(255,255,255,0.8); }
.corp-pill.active { background: rgba(20,184,166,0.2); color: #14b8a6; border-color: rgba(20,184,166,0.3); }

/* Policy cards grid */
.corp-policy-grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 16px; margin-bottom: 16px;
}
.corp-policy-card {
    background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08);
    border-radius: 14px; padding: 18px; backdrop-filter: blur(12px);
}
.corp-policy-name {
    font-family: 'Space Grotesk', sans-serif; font-size: 16px; font-weight: 600;
    color: #f5f5f5; margin-bottom: 8px;
}
.corp-policy-detail { font-size: 12px; color: rgba(255,255,255,0.5); margin-bottom: 4px; }
.corp-policy-actions { display: flex; gap: 8px; margin-top: 12px; }

/* Approval cards */
.corp-approval-card {
    background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08);
    border-radius: 14px; padding: 18px; backdrop-filter: blur(12px); margin-bottom: 12px;
}
.corp-approval-top { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px; flex-wrap: wrap; gap: 8px; }
.corp-approval-requester {
    font-family: 'Space Grotesk', sans-serif; font-size: 15px; font-weight: 600; color: #f5f5f5;
}
.corp-approval-detail { font-size: 13px; color: rgba(255,255,255,0.5); margin-bottom: 4px; }
.corp-approval-actions { display: flex; gap: 8px; margin-top: 12px; align-items: center; flex-wrap: wrap; }

/* Bookings filter bar */
.corp-book-bar { display: flex; gap: 10px; margin-bottom: 16px; flex-wrap: wrap; align-items: center; }

/* Empty states */
.corp-empty {
    text-align: center; padding: 40px 20px;
    color: rgba(255,255,255,0.35); font-size: 14px;
}

/* Invite code display */
.corp-invite-code {
    font-family: 'Space Grotesk', monospace; font-size: 16px; font-weight: 700;
    color: #14b8a6; letter-spacing: 1px;
    background: rgba(20,184,166,0.1); padding: 8px 16px; border-radius: 8px;
    display: inline-block; cursor: pointer;
}
.corp-invite-code:hover { background: rgba(20,184,166,0.2); }

/* Toast */
.corp-toast {
    position: fixed; bottom: 24px; right: 24px;
    background: rgba(20,184,166,0.95); color: #fff; padding: 12px 20px;
    border-radius: 10px; font-size: 14px; font-weight: 600;
    z-index: 9999; opacity: 0; transition: opacity 0.3s;
    pointer-events: none;
}
.corp-toast.error { background: rgba(239,68,68,0.95); }
.corp-toast.show { opacity: 1; }

/* Responsive */
@media (max-width: 600px) {
    .corp-stats { grid-template-columns: 1fr 1fr; }
    .corp-ws-header { flex-direction: column; align-items: flex-start; }
    .corp-bar-label { width: 80px; font-size: 11px; }
}
</style>

<div class="corp-detail">
    <a class="corp-back-link" href="/corporate">&larr; All Workspaces</a>

    <div class="corp-ws-header">
        <div class="corp-ws-logo {{ ws_color }}" id="wsLogo">{{ ws_initial }}</div>
        <div>
            <h1 class="corp-ws-title" id="wsName">{{ workspace.name }}</h1>
            <div class="corp-ws-subtitle">
                <span id="wsDomain">{{ workspace.company_domain or '' }}</span>
                {% if workspace.invite_code %}
                &middot; Invite: <span class="corp-invite-code" onclick="copyInvite()" title="Click to copy">{{ workspace.invite_code }}</span>
                {% endif %}
            </div>
        </div>
    </div>

    <!-- Tabs -->
    <div class="corp-tabs">
        <button class="corp-tab active" data-tab="dashboard" onclick="switchTab('dashboard')">Dashboard</button>
        <button class="corp-tab" data-tab="members" onclick="switchTab('members')">Members</button>
        <button class="corp-tab" data-tab="policies" onclick="switchTab('policies')">Policies</button>
        <button class="corp-tab" data-tab="approvals" onclick="switchTab('approvals')">Approvals</button>
        <button class="corp-tab" data-tab="bookings" onclick="switchTab('bookings')">Bookings</button>
    </div>

    <!-- ═══════════════════════════════════════
         TAB 1: DASHBOARD
         ═══════════════════════════════════════ -->
    <div class="corp-tab-panel active" id="panel-dashboard">
        <div class="corp-stats" id="dashStats"></div>
        <div class="corp-chart" id="dashChart"></div>
        <div id="dashRecent"></div>
    </div>

    <!-- ═══════════════════════════════════════
         TAB 2: MEMBERS
         ═══════════════════════════════════════ -->
    <div class="corp-tab-panel" id="panel-members">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px; flex-wrap:wrap; gap:8px;">
            <h3 style="font-family:'Space Grotesk',sans-serif; font-size:18px; color:#f5f5f5; margin:0;">Team Members</h3>
            <button class="corp-btn" onclick="toggleInviteForm()">+ Invite Member</button>
        </div>
        <div id="inviteForm" class="corp-inline-form">
            <h4>Invite a Member</h4>
            <div class="corp-form-row">
                <input type="email" id="invEmail" class="corp-input" placeholder="Email address" style="flex:2; min-width:200px;">
                <select id="invRole" class="corp-input">
                    <option value="member">Member</option>
                    <option value="travel_manager">Travel Manager</option>
                    <option value="admin">Admin</option>
                </select>
            </div>
            <div class="corp-form-row">
                <input type="text" id="invDept" class="corp-input" placeholder="Department (optional)" style="flex:2; min-width:200px;">
                <select id="invType" class="corp-input">
                    <option value="employee">Employee</option>
                    <option value="contractor">Contractor</option>
                    <option value="affiliate">Affiliate</option>
                </select>
                <button class="corp-btn" onclick="inviteMember()" id="invBtn">Send Invite</button>
            </div>
        </div>
        <div class="corp-table-wrap">
            <table class="corp-table" id="membersTable">
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Email</th>
                        <th>Role</th>
                        <th>Department</th>
                        <th>Type</th>
                        <th></th>
                    </tr>
                </thead>
                <tbody id="membersBody"></tbody>
            </table>
        </div>
        <div id="membersEmpty" class="corp-empty" style="display:none;">No members found.</div>
    </div>

    <!-- ═══════════════════════════════════════
         TAB 3: POLICIES
         ═══════════════════════════════════════ -->
    <div class="corp-tab-panel" id="panel-policies">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px; flex-wrap:wrap; gap:8px;">
            <h3 style="font-family:'Space Grotesk',sans-serif; font-size:18px; color:#f5f5f5; margin:0;">Travel Policies</h3>
            <button class="corp-btn" onclick="togglePolicyForm()">+ Add Policy</button>
        </div>
        <div id="policyForm" class="corp-inline-form">
            <h4>Create Travel Policy</h4>
            <div class="corp-form-row">
                <input type="text" id="polName" class="corp-input" placeholder="Policy name" style="flex:2;">
                <input type="text" id="polDept" class="corp-input" placeholder="Department scope (optional)">
            </div>
            <div class="corp-form-row">
                <input type="number" id="polMaxFlight" class="corp-input" placeholder="Max flight $" style="width:130px;" min="0">
                <input type="number" id="polMaxHotel" class="corp-input" placeholder="Max hotel/night $" style="width:130px;" min="0">
                <input type="number" id="polThreshold" class="corp-input" placeholder="Approval threshold $" style="width:150px;" min="0">
            </div>
            <div class="corp-form-row">
                <select id="polCabin" class="corp-input" style="width:160px;">
                    <option value="">Any cabin</option>
                    <option value="economy">Economy</option>
                    <option value="premium_economy">Premium Economy</option>
                    <option value="business">Business</option>
                    <option value="first">First</option>
                </select>
                <button class="corp-btn" onclick="createPolicy()" id="polBtn">Create Policy</button>
            </div>
        </div>
        <div class="corp-policy-grid" id="policiesGrid"></div>
        <div id="policiesEmpty" class="corp-empty" style="display:none;">No travel policies yet.</div>
    </div>

    <!-- ═══════════════════════════════════════
         TAB 4: APPROVALS
         ═══════════════════════════════════════ -->
    <div class="corp-tab-panel" id="panel-approvals">
        <h3 style="font-family:'Space Grotesk',sans-serif; font-size:18px; color:#f5f5f5; margin:0 0 16px;">Booking Approvals</h3>
        <div class="corp-filters" id="approvalFilters">
            <button class="corp-pill active" data-status="" onclick="filterApprovals('')">All</button>
            <button class="corp-pill" data-status="pending" onclick="filterApprovals('pending')">Pending</button>
            <button class="corp-pill" data-status="approved" onclick="filterApprovals('approved')">Approved</button>
            <button class="corp-pill" data-status="denied" onclick="filterApprovals('denied')">Denied</button>
        </div>
        <div id="approvalsList"></div>
        <div id="approvalsEmpty" class="corp-empty" style="display:none;">No approval requests found.</div>
    </div>

    <!-- ═══════════════════════════════════════
         TAB 5: BOOKINGS
         ═══════════════════════════════════════ -->
    <div class="corp-tab-panel" id="panel-bookings">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px; flex-wrap:wrap; gap:8px;">
            <h3 style="font-family:'Space Grotesk',sans-serif; font-size:18px; color:#f5f5f5; margin:0;">Workspace Bookings</h3>
            <div style="display:flex; gap:8px; flex-wrap:wrap;">
                <button class="corp-btn secondary" onclick="toggleBookOnBehalf()">Book on Behalf</button>
                <button class="corp-btn ghost" onclick="exportCSV()">Export CSV</button>
            </div>
        </div>
        <div id="bobForm" class="corp-inline-form">
            <h4>Book on Behalf of a Member</h4>
            <div class="corp-form-row">
                <select id="bobMember" class="corp-input" style="flex:2; min-width:200px;">
                    <option value="">Select member...</option>
                </select>
                <input type="text" id="bobTripName" class="corp-input" placeholder="Trip name" style="flex:2; min-width:180px;">
                <button class="corp-btn" onclick="bookOnBehalf()" id="bobBtn">Create Trip</button>
            </div>
        </div>
        <div class="corp-table-wrap">
            <table class="corp-table" id="bookingsTable">
                <thead>
                    <tr>
                        <th>Employee</th>
                        <th>Department</th>
                        <th>Status</th>
                        <th>Amount</th>
                        <th>Confirmation</th>
                        <th>Date</th>
                    </tr>
                </thead>
                <tbody id="bookingsBody"></tbody>
            </table>
        </div>
        <div id="bookingsEmpty" class="corp-empty" style="display:none;">No bookings yet.</div>
    </div>
</div>

<div id="corpToast" class="corp-toast"></div>

<script>
(function() {
    var SLUG = '{{ workspace.slug }}';
    var MY_ROLE = '{{ my_role }}';
    var csrfToken = document.querySelector('meta[name="csrf-token"]') ? document.querySelector('meta[name="csrf-token"]').content : '';
    var currentApprovalFilter = '';
    var membersCache = [];

    /* ── Utilities ────────────────────────── */
    function toast(msg, isError) {
        var el = document.getElementById('corpToast');
        el.textContent = msg;
        el.className = 'corp-toast show' + (isError ? ' error' : '');
        setTimeout(function() { el.className = 'corp-toast'; }, 3000);
    }

    function esc(s) { var d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }

    function fmtUSD(n) {
        if (n === null || n === undefined) return '--';
        return '$' + Number(n).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
    }

    function fmtDate(iso) {
        if (!iso) return '--';
        var d = new Date(iso);
        return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    }

    function apiFetch(path, opts) {
        opts = opts || {};
        opts.headers = opts.headers || {};
        opts.headers['X-CSRFToken'] = csrfToken;
        if (opts.body && !opts.headers['Content-Type']) {
            opts.headers['Content-Type'] = 'application/json';
        }
        return fetch(path, opts).then(function(r) { return r.json(); });
    }

    function copyInvite() {
        var code = '{{ workspace.invite_code or "" }}';
        if (navigator.clipboard && code) {
            navigator.clipboard.writeText(code);
            toast('Invite code copied');
        }
    }
    window.copyInvite = copyInvite;

    /* ── Tab switching ─────────────────────── */
    function switchTab(name) {
        document.querySelectorAll('.corp-tab').forEach(function(t) {
            t.classList.toggle('active', t.getAttribute('data-tab') === name);
        });
        document.querySelectorAll('.corp-tab-panel').forEach(function(p) {
            p.classList.toggle('active', p.id === 'panel-' + name);
        });
        if (name === 'dashboard') loadDashboard();
        if (name === 'members') loadMembers();
        if (name === 'policies') loadPolicies();
        if (name === 'approvals') loadApprovals();
        if (name === 'bookings') loadBookings();
    }
    window.switchTab = switchTab;

    /* ═══════════════════════════════════════
       TAB 1: DASHBOARD
       ═══════════════════════════════════════ */
    function loadDashboard() {
        apiFetch('/api/workspaces/' + SLUG + '/dashboard')
        .then(function(data) {
            if (data.status !== 'ok') { toast(data.error || 'Failed to load', true); return; }
            var d = data.dashboard;
            renderDashStats(d);
            renderDeptChart(d.bookings.by_department);
            renderRecentBookings();
        })
        .catch(function() { toast('Dashboard load failed', true); });
    }

    function renderDashStats(d) {
        var html = '';
        html += '<div class="corp-stat-card"><div class="corp-stat-value">' + d.members.total + '</div><div class="corp-stat-label">Members</div></div>';
        html += '<div class="corp-stat-card"><div class="corp-stat-value">' + d.bookings.total + '</div><div class="corp-stat-label">Total Bookings</div></div>';
        html += '<div class="corp-stat-card"><div class="corp-stat-value gold">' + fmtUSD(d.bookings.total_spend_usd) + '</div><div class="corp-stat-label">Total Spend</div></div>';
        html += '<div class="corp-stat-card"><div class="corp-stat-value purple">' + d.pending_approvals + '</div><div class="corp-stat-label">Pending Approvals</div></div>';
        document.getElementById('dashStats').innerHTML = html;
    }

    function renderDeptChart(byDept) {
        var el = document.getElementById('dashChart');
        if (!byDept || Object.keys(byDept).length === 0) {
            el.innerHTML = '<div class="corp-chart-title">Spend by Department</div><div class="corp-empty">No spending data yet</div>';
            return;
        }
        var maxVal = 0;
        var keys = Object.keys(byDept);
        for (var i = 0; i < keys.length; i++) {
            if (byDept[keys[i]] > maxVal) maxVal = byDept[keys[i]];
        }
        if (maxVal === 0) maxVal = 1;
        var html = '<div class="corp-chart-title">Spend by Department</div>';
        for (var j = 0; j < keys.length; j++) {
            var pct = Math.round((byDept[keys[j]] / maxVal) * 100);
            if (pct < 5) pct = 5;
            html += '<div class="corp-bar-row">';
            html += '<div class="corp-bar-label">' + esc(keys[j] || 'Unassigned') + '</div>';
            html += '<div class="corp-bar-track"><div class="corp-bar-fill" style="width:' + pct + '%">' + fmtUSD(byDept[keys[j]]) + '</div></div>';
            html += '</div>';
        }
        el.innerHTML = html;
    }

    function renderRecentBookings() {
        apiFetch('/api/workspaces/' + SLUG + '/bookings')
        .then(function(data) {
            if (data.status !== 'ok') return;
            var bks = (data.bookings || []).slice(0, 5);
            var el = document.getElementById('dashRecent');
            if (!bks.length) { el.innerHTML = ''; return; }
            var html = '<div class="corp-chart-title">Recent Bookings</div>';
            html += '<div class="corp-table-wrap"><table class="corp-table"><thead><tr><th>Employee</th><th>Status</th><th>Amount</th><th>Date</th></tr></thead><tbody>';
            for (var i = 0; i < bks.length; i++) {
                var b = bks[i];
                html += '<tr>';
                html += '<td>' + esc(b.user_name || 'Unknown') + '</td>';
                html += '<td><span class="cbadge cbadge-' + (b.status || 'booked') + '">' + esc(b.status || '') + '</span></td>';
                html += '<td>' + fmtUSD(b.vendor_payment_amount) + '</td>';
                html += '<td>' + fmtDate(b.created_at) + '</td>';
                html += '</tr>';
            }
            html += '</tbody></table></div>';
            el.innerHTML = html;
        });
    }

    /* ═══════════════════════════════════════
       TAB 2: MEMBERS
       ═══════════════════════════════════════ */
    function toggleInviteForm() {
        document.getElementById('inviteForm').classList.toggle('visible');
    }
    window.toggleInviteForm = toggleInviteForm;

    function loadMembers() {
        apiFetch('/api/workspaces/' + SLUG + '/members')
        .then(function(data) {
            if (data.status !== 'ok') { toast(data.error || 'Failed', true); return; }
            membersCache = data.members || [];
            renderMembers(membersCache);
        });
    }

    function renderMembers(members) {
        var tbody = document.getElementById('membersBody');
        var empty = document.getElementById('membersEmpty');
        if (!members.length) { tbody.innerHTML = ''; empty.style.display = 'block'; return; }
        empty.style.display = 'none';
        var html = '';
        for (var i = 0; i < members.length; i++) {
            var m = members[i];
            html += '<tr data-mid="' + m.id + '">';
            html += '<td style="font-weight:600; color:#f5f5f5;">' + esc(m.user_name || 'Unknown') + '</td>';
            html += '<td>' + esc(m.user_email || '') + '</td>';
            html += '<td><span class="cbadge cbadge-' + m.role + '">' + esc(formatRole(m.role)) + '</span></td>';
            html += '<td>' + esc(m.department || '--') + '</td>';
            html += '<td><span class="cbadge cbadge-' + m.member_type + '">' + esc(m.member_type || '') + '</span></td>';
            html += '<td>';
            if (MY_ROLE === 'admin') {
                html += '<button class="corp-btn small danger" onclick="removeMember(' + m.id + ')" title="Remove">Remove</button>';
            }
            html += '</td></tr>';
        }
        tbody.innerHTML = html;
    }

    function formatRole(r) {
        if (r === 'admin') return 'Admin';
        if (r === 'travel_manager') return 'Manager';
        return 'Member';
    }

    function inviteMember() {
        var email = document.getElementById('invEmail').value.trim();
        if (!email) { toast('Email is required', true); return; }
        var btn = document.getElementById('invBtn');
        btn.disabled = true; btn.textContent = 'Inviting...';
        apiFetch('/api/workspaces/' + SLUG + '/members', {
            method: 'POST',
            body: JSON.stringify({
                email: email,
                role: document.getElementById('invRole').value,
                department: document.getElementById('invDept').value.trim(),
                member_type: document.getElementById('invType').value
            })
        })
        .then(function(data) {
            btn.disabled = false; btn.textContent = 'Send Invite';
            if (data.status === 'ok') {
                toast('Member invited');
                document.getElementById('invEmail').value = '';
                document.getElementById('invDept').value = '';
                document.getElementById('inviteForm').classList.remove('visible');
                loadMembers();
            } else {
                toast(data.error || 'Failed', true);
            }
        })
        .catch(function() { btn.disabled = false; btn.textContent = 'Send Invite'; toast('Network error', true); });
    }
    window.inviteMember = inviteMember;

    function removeMember(mid) {
        if (!confirm('Remove this member from the workspace?')) return;
        apiFetch('/api/workspaces/' + SLUG + '/members/' + mid, { method: 'DELETE' })
        .then(function(data) {
            if (data.status === 'ok') { toast('Member removed'); loadMembers(); }
            else { toast(data.error || 'Failed', true); }
        })
        .catch(function() { toast('Network error', true); });
    }
    window.removeMember = removeMember;

    /* ═══════════════════════════════════════
       TAB 3: POLICIES
       ═══════════════════════════════════════ */
    function togglePolicyForm() {
        document.getElementById('policyForm').classList.toggle('visible');
    }
    window.togglePolicyForm = togglePolicyForm;

    function loadPolicies() {
        apiFetch('/api/workspaces/' + SLUG + '/policies')
        .then(function(data) {
            if (data.status !== 'ok') { toast(data.error || 'Failed', true); return; }
            renderPolicies(data.policies || []);
        });
    }

    function renderPolicies(policies) {
        var grid = document.getElementById('policiesGrid');
        var empty = document.getElementById('policiesEmpty');
        if (!policies.length) { grid.innerHTML = ''; empty.style.display = 'block'; return; }
        empty.style.display = 'none';
        var html = '';
        for (var i = 0; i < policies.length; i++) {
            var p = policies[i];
            html += '<div class="corp-policy-card">';
            html += '<div class="corp-policy-name">' + esc(p.name) + '</div>';
            if (p.applies_to_department) {
                html += '<div class="corp-policy-detail">Department: ' + esc(p.applies_to_department) + '</div>';
            }
            if (p.max_flight_usd) {
                html += '<div class="corp-policy-detail">Max flight: ' + fmtUSD(p.max_flight_usd) + '</div>';
            }
            if (p.max_hotel_per_night_usd) {
                html += '<div class="corp-policy-detail">Max hotel/night: ' + fmtUSD(p.max_hotel_per_night_usd) + '</div>';
            }
            if (p.max_total_trip_usd) {
                html += '<div class="corp-policy-detail">Max trip total: ' + fmtUSD(p.max_total_trip_usd) + '</div>';
            }
            if (p.approval_threshold_usd) {
                html += '<div class="corp-policy-detail">Approval above: ' + fmtUSD(p.approval_threshold_usd) + '</div>';
            }
            if (p.preferred_cabin) {
                html += '<div class="corp-policy-detail">Cabin: ' + esc(p.preferred_cabin.replace('_', ' ')) + '</div>';
            }
            html += '<div class="corp-policy-detail" style="margin-top:6px;"><span class="cbadge cbadge-approved">Active</span></div>';
            if (MY_ROLE === 'admin') {
                html += '<div class="corp-policy-actions">';
                html += '<button class="corp-btn small danger" onclick="deletePolicy(' + p.id + ')">Delete</button>';
                html += '</div>';
            }
            html += '</div>';
        }
        grid.innerHTML = html;
    }

    function createPolicy() {
        var name = document.getElementById('polName').value.trim();
        if (!name) { toast('Policy name required', true); return; }
        var btn = document.getElementById('polBtn');
        btn.disabled = true; btn.textContent = 'Creating...';
        var body = { name: name };
        var dept = document.getElementById('polDept').value.trim();
        if (dept) body.applies_to_department = dept;
        var maxF = document.getElementById('polMaxFlight').value;
        if (maxF) body.max_flight_usd = parseFloat(maxF);
        var maxH = document.getElementById('polMaxHotel').value;
        if (maxH) body.max_hotel_per_night_usd = parseFloat(maxH);
        var thresh = document.getElementById('polThreshold').value;
        if (thresh) body.approval_threshold_usd = parseFloat(thresh);
        var cabin = document.getElementById('polCabin').value;
        if (cabin) body.preferred_cabin = cabin;

        apiFetch('/api/workspaces/' + SLUG + '/policies', {
            method: 'POST',
            body: JSON.stringify(body)
        })
        .then(function(data) {
            btn.disabled = false; btn.textContent = 'Create Policy';
            if (data.status === 'ok') {
                toast('Policy created');
                document.getElementById('polName').value = '';
                document.getElementById('polDept').value = '';
                document.getElementById('polMaxFlight').value = '';
                document.getElementById('polMaxHotel').value = '';
                document.getElementById('polThreshold').value = '';
                document.getElementById('polCabin').value = '';
                document.getElementById('policyForm').classList.remove('visible');
                loadPolicies();
            } else {
                toast(data.error || 'Failed', true);
            }
        })
        .catch(function() { btn.disabled = false; btn.textContent = 'Create Policy'; toast('Network error', true); });
    }
    window.createPolicy = createPolicy;

    function deletePolicy(pid) {
        if (!confirm('Delete this policy?')) return;
        apiFetch('/api/workspaces/' + SLUG + '/policies/' + pid, { method: 'DELETE' })
        .then(function(data) {
            if (data.status === 'ok') { toast('Policy deleted'); loadPolicies(); }
            else { toast(data.error || 'Failed', true); }
        })
        .catch(function() { toast('Network error', true); });
    }
    window.deletePolicy = deletePolicy;

    /* ═══════════════════════════════════════
       TAB 4: APPROVALS
       ═══════════════════════════════════════ */
    function filterApprovals(status) {
        currentApprovalFilter = status;
        document.querySelectorAll('#approvalFilters .corp-pill').forEach(function(p) {
            p.classList.toggle('active', p.getAttribute('data-status') === status);
        });
        loadApprovals();
    }
    window.filterApprovals = filterApprovals;

    function loadApprovals() {
        var url = '/api/workspaces/' + SLUG + '/approvals';
        if (currentApprovalFilter) url += '?status=' + currentApprovalFilter;
        apiFetch(url)
        .then(function(data) {
            if (data.status !== 'ok') { toast(data.error || 'Failed', true); return; }
            renderApprovals(data.approvals || []);
        });
    }

    function renderApprovals(approvals) {
        var el = document.getElementById('approvalsList');
        var empty = document.getElementById('approvalsEmpty');
        if (!approvals.length) { el.innerHTML = ''; empty.style.display = 'block'; return; }
        empty.style.display = 'none';
        var html = '';
        for (var i = 0; i < approvals.length; i++) {
            var a = approvals[i];
            html += '<div class="corp-approval-card">';
            html += '<div class="corp-approval-top">';
            html += '<div>';
            html += '<div class="corp-approval-requester">' + esc(a.requester_name || 'Unknown') + '</div>';
            html += '<div class="corp-approval-detail">' + esc(a.booking_type || '') + ' &middot; ' + fmtUSD(a.estimated_cost_usd) + '</div>';
            if (a.description) {
                html += '<div class="corp-approval-detail">' + esc(a.description) + '</div>';
            }
            if (a.policy_reason) {
                html += '<div class="corp-approval-detail" style="color:#fcd34d;">' + esc(a.policy_reason) + '</div>';
            }
            if (a.department) {
                html += '<div class="corp-approval-detail">Dept: ' + esc(a.department) + '</div>';
            }
            html += '</div>';
            html += '<span class="cbadge cbadge-' + a.status + '">' + esc(a.status) + '</span>';
            html += '</div>';

            if (a.status === 'pending' && (MY_ROLE === 'admin' || MY_ROLE === 'travel_manager')) {
                html += '<div class="corp-approval-actions">';
                html += '<textarea class="corp-input" id="note-' + a.id + '" placeholder="Note (optional)" style="flex:2; min-width:180px; min-height:36px; height:36px;"></textarea>';
                html += '<button class="corp-btn small" onclick="decideApproval(' + a.id + ',\'approved\')">Approve</button>';
                html += '<button class="corp-btn small danger" onclick="decideApproval(' + a.id + ',\'denied\')">Deny</button>';
                html += '</div>';
            }
            if (a.approver_name && a.status !== 'pending') {
                html += '<div class="corp-approval-detail" style="margin-top:8px;">Decided by ' + esc(a.approver_name) + (a.approver_note ? ': ' + esc(a.approver_note) : '') + '</div>';
            }
            html += '</div>';
        }
        el.innerHTML = html;
    }

    function decideApproval(aid, decision) {
        var noteEl = document.getElementById('note-' + aid);
        var note = noteEl ? noteEl.value.trim() : '';
        apiFetch('/api/workspaces/' + SLUG + '/approvals/' + aid, {
            method: 'PUT',
            body: JSON.stringify({ decision: decision, note: note })
        })
        .then(function(data) {
            if (data.status === 'ok') {
                toast('Request ' + decision);
                loadApprovals();
            } else {
                toast(data.error || 'Failed', true);
            }
        })
        .catch(function() { toast('Network error', true); });
    }
    window.decideApproval = decideApproval;

    /* ═══════════════════════════════════════
       TAB 5: BOOKINGS
       ═══════════════════════════════════════ */
    function toggleBookOnBehalf() {
        var form = document.getElementById('bobForm');
        form.classList.toggle('visible');
        if (form.classList.contains('visible')) populateBobMembers();
    }
    window.toggleBookOnBehalf = toggleBookOnBehalf;

    function populateBobMembers() {
        apiFetch('/api/workspaces/' + SLUG + '/members')
        .then(function(data) {
            if (data.status !== 'ok') return;
            var sel = document.getElementById('bobMember');
            sel.innerHTML = '<option value="">Select member...</option>';
            var members = data.members || [];
            for (var i = 0; i < members.length; i++) {
                var m = members[i];
                sel.innerHTML += '<option value="' + m.user_id + '">' + esc(m.user_name || m.user_email) + '</option>';
            }
        });
    }

    function loadBookings() {
        apiFetch('/api/workspaces/' + SLUG + '/bookings')
        .then(function(data) {
            if (data.status !== 'ok') { toast(data.error || 'Failed', true); return; }
            renderBookings(data.bookings || []);
        });
    }

    function renderBookings(bookings) {
        var tbody = document.getElementById('bookingsBody');
        var empty = document.getElementById('bookingsEmpty');
        if (!bookings.length) { tbody.innerHTML = ''; empty.style.display = 'block'; return; }
        empty.style.display = 'none';
        var html = '';
        for (var i = 0; i < bookings.length; i++) {
            var b = bookings[i];
            html += '<tr>';
            html += '<td style="font-weight:600; color:#f5f5f5;">' + esc(b.user_name || 'Unknown') + '</td>';
            html += '<td>' + esc(b.department || '--') + '</td>';
            html += '<td><span class="cbadge cbadge-' + (b.status || 'booked') + '">' + esc(b.status || '') + '</span></td>';
            html += '<td>' + fmtUSD(b.vendor_payment_amount) + '</td>';
            html += '<td style="font-family:monospace; font-size:12px;">' + esc(b.confirmation_code || '--') + '</td>';
            html += '<td>' + fmtDate(b.created_at) + '</td>';
            html += '</tr>';
        }
        tbody.innerHTML = html;
    }

    function bookOnBehalf() {
        var userId = document.getElementById('bobMember').value;
        var tripName = document.getElementById('bobTripName').value.trim();
        if (!userId) { toast('Select a member', true); return; }
        if (!tripName) { toast('Trip name required', true); return; }
        var btn = document.getElementById('bobBtn');
        btn.disabled = true; btn.textContent = 'Creating...';
        apiFetch('/api/workspaces/' + SLUG + '/book-on-behalf', {
            method: 'POST',
            body: JSON.stringify({ for_user_id: parseInt(userId), trip_name: tripName })
        })
        .then(function(data) {
            btn.disabled = false; btn.textContent = 'Create Trip';
            if (data.status === 'ok') {
                toast('Trip created for ' + (data.for_user_name || 'member'));
                document.getElementById('bobTripName').value = '';
                document.getElementById('bobForm').classList.remove('visible');
            } else {
                toast(data.error || 'Failed', true);
            }
        })
        .catch(function() { btn.disabled = false; btn.textContent = 'Create Trip'; toast('Network error', true); });
    }
    window.bookOnBehalf = bookOnBehalf;

    function exportCSV() {
        window.location.href = '/api/workspaces/' + SLUG + '/export';
    }
    window.exportCSV = exportCSV;

    /* ── Initial load ─────────────────────── */
    loadDashboard();
})();
</script>
"""


def register_corporate_routes(app, csrf, limiter):
    """Register corporate workspace routes (Builds #235-238)."""
    from server import BASE_TEMPLATE, is_feature_enabled

    # ══════════════════════════════════════════════════
    # BUILD #238 — PAGE ROUTES (Corporate Workspace UI)
    # ══════════════════════════════════════════════════

    @app.route('/corporate')
    @login_required
    def corporate_workspaces_page():
        """Corporate workspaces list page."""
        if not is_feature_enabled('corporate_workspaces'):
            return redirect(url_for('home'))
        return render_template_string(
            BASE_TEMPLATE,
            title='Corporate Workspaces',
            content=render_template_string(CORPORATE_LIST_TEMPLATE),
            current_user=current_user,
        )

    @app.route('/corporate/<slug>')
    @login_required
    def corporate_workspace_detail_page(slug):
        """Corporate workspace detail page with 5 tabs."""
        if not is_feature_enabled('corporate_workspaces'):
            return redirect(url_for('home'))

        ws, err = _get_workspace(slug)
        if err:
            return redirect(url_for('corporate_workspaces_page'))

        member, err = _get_membership(ws)
        if err:
            return redirect(url_for('corporate_workspaces_page'))

        # Determine color class for logo
        tier_colors = {'enterprise': 'gold', 'pro': 'purple', 'starter': 'teal'}
        ws_color = tier_colors.get(ws.tier, 'teal')
        ws_initial = (ws.name or '?')[0].upper()

        return render_template_string(
            BASE_TEMPLATE,
            title=ws.name + ' — Workspace',
            content=render_template_string(
                CORPORATE_DETAIL_TEMPLATE,
                workspace=ws,
                my_role=member.role,
                ws_color=ws_color,
                ws_initial=ws_initial,
            ),
            current_user=current_user,
        )

    # ══════════════════════════════════════════════════
    # BUILD #235 — WORKSPACE MODEL + ADMIN + ROLES
    # ══════════════════════════════════════════════════

    @app.route('/api/workspaces', methods=['POST'])
    @login_required
    def create_workspace():
        """Create a new corporate workspace. Creator becomes admin."""
        blocked = _check_flag('corporate_workspaces')
        if blocked:
            return blocked

        data = request.get_json(silent=True) or {}
        name = (data.get('name') or '').strip()
        if not name:
            return jsonify({'status': 'error', 'error': 'Workspace name required'}), 400

        tier = data.get('tier', 'starter')
        if tier not in Workspace.TIERS:
            return jsonify({'status': 'error', 'error': f'Invalid tier. Must be one of: {", ".join(Workspace.TIERS)}'}), 400

        max_seats = {'starter': 25, 'pro': 100, 'enterprise': 9999}.get(tier, 25)

        ws = Workspace(
            name=name,
            slug=_generate_slug(name),
            owner_user_id=current_user.id,
            company_domain=data.get('company_domain', '').strip() or None,
            company_logo_url=data.get('company_logo_url', '').strip() or None,
            industry=data.get('industry', '').strip() or None,
            tier=tier,
            max_seats=max_seats,
            invite_code=_generate_invite_code(),
            domain_auto_join=bool(data.get('domain_auto_join', False)),
        )
        db.session.add(ws)
        db.session.flush()

        # Creator is auto-enrolled as admin employee
        member = WorkspaceMember(
            workspace_id=ws.id,
            user_id=current_user.id,
            role='admin',
            member_type='employee',
            invited_by_user_id=current_user.id,
        )
        db.session.add(member)
        db.session.commit()

        logger.info("Workspace created: %s (slug=%s) by user %s", name, ws.slug, current_user.id)
        return jsonify({
            'status': 'ok',
            'workspace': ws.to_dict(include_stats=True),
        })

    @app.route('/api/workspaces', methods=['GET'])
    @login_required
    def list_workspaces():
        """List workspaces the current user belongs to."""
        blocked = _check_flag('corporate_workspaces')
        if blocked:
            return blocked

        memberships = WorkspaceMember.query.filter_by(
            user_id=current_user.id, is_active=True
        ).all()

        result = []
        for m in memberships:
            ws = Workspace.query.get(m.workspace_id)
            if ws and ws.is_active:
                d = ws.to_dict(include_stats=True)
                d['my_role'] = m.role
                d['my_member_type'] = m.member_type
                result.append(d)

        return jsonify({'status': 'ok', 'workspaces': result})

    @app.route('/api/workspaces/<slug>', methods=['GET'])
    @login_required
    def get_workspace(slug):
        """Get workspace details (members only)."""
        blocked = _check_flag('corporate_workspaces')
        if blocked:
            return blocked

        ws, err = _get_workspace(slug)
        if err:
            return err

        member, err = _get_membership(ws)
        if err:
            return err

        d = ws.to_dict(include_stats=True)
        d['my_role'] = member.role
        d['my_member_type'] = member.member_type
        d['my_department'] = member.department
        return jsonify({'status': 'ok', 'workspace': d})

    @app.route('/api/workspaces/<slug>', methods=['PUT'])
    @login_required
    def update_workspace(slug):
        """Update workspace settings (admin only)."""
        blocked = _check_flag('corporate_workspaces')
        if blocked:
            return blocked

        ws, err = _get_workspace(slug)
        if err:
            return err
        _, err = _require_admin(ws)
        if err:
            return err

        data = request.get_json(silent=True) or {}

        if 'name' in data and data['name'].strip():
            ws.name = data['name'].strip()
        if 'company_domain' in data:
            ws.company_domain = data['company_domain'].strip() or None
        if 'company_logo_url' in data:
            ws.company_logo_url = data['company_logo_url'].strip() or None
        if 'industry' in data:
            ws.industry = data['industry'].strip() or None
        if 'domain_auto_join' in data:
            ws.domain_auto_join = bool(data['domain_auto_join'])
        if 'tier' in data and data['tier'] in Workspace.TIERS:
            ws.tier = data['tier']
            ws.max_seats = {'starter': 25, 'pro': 100, 'enterprise': 9999}.get(ws.tier, 25)

        db.session.commit()
        return jsonify({'status': 'ok', 'workspace': ws.to_dict(include_stats=True)})

    # ── Member Management ──

    @app.route('/api/workspaces/<slug>/members', methods=['POST'])
    @login_required
    def invite_workspace_member(slug):
        """Invite a member to the workspace (admin or travel_manager)."""
        blocked = _check_flag('corporate_workspaces')
        if blocked:
            return blocked

        ws, err = _get_workspace(slug)
        if err:
            return err
        _, err = _require_admin_or_manager(ws)
        if err:
            return err

        data = request.get_json(silent=True) or {}
        email = (data.get('email') or '').strip().lower()
        if not email:
            return jsonify({'status': 'error', 'error': 'Email required'}), 400

        # Check seat limit
        if ws.seat_count() >= ws.max_seats:
            return jsonify({'status': 'error', 'error': f'Seat limit reached ({ws.max_seats})'}), 400

        # Find or validate user
        user = User.query.filter_by(email=email).first()
        if not user:
            return jsonify({'status': 'error', 'error': 'User not found. They must create a MYSTES account first.'}), 404

        # Check not already a member
        existing = WorkspaceMember.query.filter_by(
            workspace_id=ws.id, user_id=user.id
        ).first()
        if existing:
            if existing.is_active:
                return jsonify({'status': 'error', 'error': 'User is already a member'}), 409
            # Re-activate
            existing.is_active = True
            existing.role = data.get('role', 'member')
            existing.member_type = data.get('member_type', 'employee')
            existing.department = data.get('department', '').strip() or None
            db.session.commit()
            return jsonify({'status': 'ok', 'member': existing.to_dict()})

        role = data.get('role', 'member')
        if role not in WorkspaceMember.ROLES:
            role = 'member'
        member_type = data.get('member_type', 'employee')
        if member_type not in WorkspaceMember.MEMBER_TYPES:
            member_type = 'employee'

        member = WorkspaceMember(
            workspace_id=ws.id,
            user_id=user.id,
            role=role,
            member_type=member_type,
            department=data.get('department', '').strip() or None,
            invited_by_user_id=current_user.id,
        )
        db.session.add(member)
        db.session.commit()

        logger.info("Workspace member added: user=%s ws=%s role=%s", user.id, ws.slug, role)
        return jsonify({'status': 'ok', 'member': member.to_dict()})

    @app.route('/api/workspaces/<slug>/members', methods=['GET'])
    @login_required
    def list_workspace_members(slug):
        """List all workspace members (any member can view)."""
        blocked = _check_flag('corporate_workspaces')
        if blocked:
            return blocked

        ws, err = _get_workspace(slug)
        if err:
            return err
        _, err = _get_membership(ws)
        if err:
            return err

        members = WorkspaceMember.query.filter_by(
            workspace_id=ws.id, is_active=True
        ).order_by(WorkspaceMember.role, WorkspaceMember.joined_at).all()

        return jsonify({
            'status': 'ok',
            'members': [m.to_dict() for m in members],
            'total': len(members),
        })

    @app.route('/api/workspaces/<slug>/members/<int:member_id>', methods=['PUT'])
    @login_required
    def update_workspace_member(slug, member_id):
        """Update member role, type, or department (admin only)."""
        blocked = _check_flag('corporate_workspaces')
        if blocked:
            return blocked

        ws, err = _get_workspace(slug)
        if err:
            return err
        _, err = _require_admin(ws)
        if err:
            return err

        member = WorkspaceMember.query.filter_by(
            id=member_id, workspace_id=ws.id
        ).first()
        if not member:
            return jsonify({'status': 'error', 'error': 'Member not found'}), 404

        # Cannot demote the workspace owner
        if member.user_id == ws.owner_user_id and member.role == 'admin':
            data = request.get_json(silent=True) or {}
            if data.get('role') and data['role'] != 'admin':
                return jsonify({'status': 'error', 'error': 'Cannot demote workspace owner'}), 400

        data = request.get_json(silent=True) or {}
        if 'role' in data and data['role'] in WorkspaceMember.ROLES:
            member.role = data['role']
        if 'member_type' in data and data['member_type'] in WorkspaceMember.MEMBER_TYPES:
            member.member_type = data['member_type']
        if 'department' in data:
            member.department = data['department'].strip() or None

        db.session.commit()
        return jsonify({'status': 'ok', 'member': member.to_dict()})

    @app.route('/api/workspaces/<slug>/members/<int:member_id>', methods=['DELETE'])
    @login_required
    def remove_workspace_member(slug, member_id):
        """Remove member from workspace (admin only, cannot remove owner)."""
        blocked = _check_flag('corporate_workspaces')
        if blocked:
            return blocked

        ws, err = _get_workspace(slug)
        if err:
            return err
        _, err = _require_admin(ws)
        if err:
            return err

        member = WorkspaceMember.query.filter_by(
            id=member_id, workspace_id=ws.id
        ).first()
        if not member:
            return jsonify({'status': 'error', 'error': 'Member not found'}), 404

        if member.user_id == ws.owner_user_id:
            return jsonify({'status': 'error', 'error': 'Cannot remove workspace owner'}), 400

        member.is_active = False
        db.session.commit()
        return jsonify({'status': 'ok', 'message': 'Member removed'})

    @app.route('/api/workspaces/join/<code>', methods=['POST'])
    @login_required
    def join_workspace_by_code(code):
        """Join a workspace via invite code."""
        blocked = _check_flag('corporate_workspaces')
        if blocked:
            return blocked

        ws = Workspace.query.filter_by(invite_code=code, is_active=True).first()
        if not ws:
            return jsonify({'status': 'error', 'error': 'Invalid invite code'}), 404

        # Check seat limit
        if ws.seat_count() >= ws.max_seats:
            return jsonify({'status': 'error', 'error': 'Workspace is full'}), 400

        # Already member?
        existing = WorkspaceMember.query.filter_by(
            workspace_id=ws.id, user_id=current_user.id
        ).first()
        if existing:
            if existing.is_active:
                return jsonify({'status': 'error', 'error': 'Already a member'}), 409
            existing.is_active = True
            db.session.commit()
            return jsonify({'status': 'ok', 'workspace': ws.to_dict(), 'member': existing.to_dict()})

        member = WorkspaceMember(
            workspace_id=ws.id,
            user_id=current_user.id,
            role='member',
            member_type='employee',
        )
        db.session.add(member)
        db.session.commit()

        return jsonify({'status': 'ok', 'workspace': ws.to_dict(), 'member': member.to_dict()})

    # ══════════════════════════════════════════════════
    # BUILD #236 — TRAVEL POLICIES + APPROVALS
    # ══════════════════════════════════════════════════

    @app.route('/api/workspaces/<slug>/policies', methods=['POST'])
    @login_required
    def create_travel_policy(slug):
        """Create a travel policy (admin only)."""
        blocked = _check_flag('travel_policies')
        if blocked:
            return blocked

        ws, err = _get_workspace(slug)
        if err:
            return err
        _, err = _require_admin(ws)
        if err:
            return err

        data = request.get_json(silent=True) or {}
        name = (data.get('name') or '').strip()
        if not name:
            return jsonify({'status': 'error', 'error': 'Policy name required'}), 400

        policy = TravelPolicy(
            workspace_id=ws.id,
            name=name,
            description=data.get('description', '').strip() or None,
            max_flight_usd=data.get('max_flight_usd'),
            max_hotel_per_night_usd=data.get('max_hotel_per_night_usd'),
            max_total_trip_usd=data.get('max_total_trip_usd'),
            preferred_airlines=data.get('preferred_airlines', '').strip() or None,
            preferred_cabin=data.get('preferred_cabin', '').strip() or None,
            blackout_dates_json=json.dumps(data['blackout_dates']) if data.get('blackout_dates') else None,
            approval_threshold_usd=data.get('approval_threshold_usd'),
            advance_booking_days=data.get('advance_booking_days'),
            applies_to_department=data.get('applies_to_department', '').strip() or None,
            applies_to_member_type=data.get('applies_to_member_type', '').strip() or None,
            created_by_user_id=current_user.id,
        )
        db.session.add(policy)
        db.session.commit()

        return jsonify({'status': 'ok', 'policy': policy.to_dict()})

    @app.route('/api/workspaces/<slug>/policies', methods=['GET'])
    @login_required
    def list_travel_policies(slug):
        """List all active travel policies in workspace (any member)."""
        blocked = _check_flag('travel_policies')
        if blocked:
            return blocked

        ws, err = _get_workspace(slug)
        if err:
            return err
        _, err = _get_membership(ws)
        if err:
            return err

        policies = TravelPolicy.query.filter_by(
            workspace_id=ws.id, is_active=True
        ).order_by(TravelPolicy.created_at).all()

        return jsonify({
            'status': 'ok',
            'policies': [p.to_dict() for p in policies],
        })

    @app.route('/api/workspaces/<slug>/policies/<int:policy_id>', methods=['PUT'])
    @login_required
    def update_travel_policy(slug, policy_id):
        """Update a travel policy (admin only)."""
        blocked = _check_flag('travel_policies')
        if blocked:
            return blocked

        ws, err = _get_workspace(slug)
        if err:
            return err
        _, err = _require_admin(ws)
        if err:
            return err

        policy = TravelPolicy.query.filter_by(id=policy_id, workspace_id=ws.id).first()
        if not policy:
            return jsonify({'status': 'error', 'error': 'Policy not found'}), 404

        data = request.get_json(silent=True) or {}
        for field in ['name', 'description', 'preferred_airlines', 'preferred_cabin',
                       'applies_to_department', 'applies_to_member_type']:
            if field in data:
                setattr(policy, field, (data[field] or '').strip() or None)
        for field in ['max_flight_usd', 'max_hotel_per_night_usd', 'max_total_trip_usd',
                       'approval_threshold_usd', 'advance_booking_days']:
            if field in data:
                setattr(policy, field, data[field])
        if 'blackout_dates' in data:
            policy.blackout_dates_json = json.dumps(data['blackout_dates']) if data['blackout_dates'] else None

        db.session.commit()
        return jsonify({'status': 'ok', 'policy': policy.to_dict()})

    @app.route('/api/workspaces/<slug>/policies/<int:policy_id>', methods=['DELETE'])
    @login_required
    def delete_travel_policy(slug, policy_id):
        """Delete a travel policy (admin only, soft delete)."""
        blocked = _check_flag('travel_policies')
        if blocked:
            return blocked

        ws, err = _get_workspace(slug)
        if err:
            return err
        _, err = _require_admin(ws)
        if err:
            return err

        policy = TravelPolicy.query.filter_by(id=policy_id, workspace_id=ws.id).first()
        if not policy:
            return jsonify({'status': 'error', 'error': 'Policy not found'}), 404

        policy.is_active = False
        db.session.commit()
        return jsonify({'status': 'ok', 'message': 'Policy deleted'})

    # ── Approval Workflow ──

    @app.route('/api/workspaces/<slug>/approvals', methods=['POST'])
    @login_required
    def request_booking_approval(slug):
        """Request approval for a booking that exceeds policy thresholds."""
        blocked = _check_flag('travel_policies')
        if blocked:
            return blocked

        ws, err = _get_workspace(slug)
        if err:
            return err
        member, err = _get_membership(ws)
        if err:
            return err

        data = request.get_json(silent=True) or {}
        booking_type = (data.get('booking_type') or '').strip()
        estimated_cost = data.get('estimated_cost_usd')

        if not booking_type:
            return jsonify({'status': 'error', 'error': 'booking_type required'}), 400
        if estimated_cost is None or estimated_cost < 0:
            return jsonify({'status': 'error', 'error': 'estimated_cost_usd required'}), 400

        # Find applicable policy to record why approval is needed
        policy_id = None
        policy_reason = None
        policies = TravelPolicy.query.filter_by(workspace_id=ws.id, is_active=True).all()
        for p in policies:
            # Check department scope
            if p.applies_to_department and p.applies_to_department != member.department:
                continue
            if p.applies_to_member_type and p.applies_to_member_type != member.member_type:
                continue
            # Check threshold
            if p.approval_threshold_usd and estimated_cost > p.approval_threshold_usd:
                policy_id = p.id
                policy_reason = f"Exceeds approval threshold (${p.approval_threshold_usd:.0f}) per '{p.name}'"
                break
            if booking_type == 'flight' and p.max_flight_usd and estimated_cost > p.max_flight_usd:
                policy_id = p.id
                policy_reason = f"Exceeds max flight cost (${p.max_flight_usd:.0f}) per '{p.name}'"
                break
            if booking_type == 'hotel' and p.max_hotel_per_night_usd:
                per_night = data.get('per_night_usd', estimated_cost)
                if per_night > p.max_hotel_per_night_usd:
                    policy_id = p.id
                    policy_reason = f"Exceeds max hotel per night (${p.max_hotel_per_night_usd:.0f}) per '{p.name}'"
                    break

        approval = BookingApproval(
            workspace_id=ws.id,
            requester_user_id=current_user.id,
            booking_type=booking_type,
            description=data.get('description', '').strip() or None,
            estimated_cost_usd=estimated_cost,
            trip_id=data.get('trip_id'),
            itinerary_item_id=data.get('itinerary_item_id'),
            policy_id=policy_id,
            policy_reason=policy_reason,
            expense_tag=data.get('expense_tag', '').strip() or None,
            department=member.department,
            is_business=data.get('is_business', True),
        )
        db.session.add(approval)
        db.session.commit()

        return jsonify({'status': 'ok', 'approval': approval.to_dict()})

    @app.route('/api/workspaces/<slug>/approvals', methods=['GET'])
    @login_required
    def list_booking_approvals(slug):
        """List booking approvals (admin/manager sees all, members see own)."""
        blocked = _check_flag('travel_policies')
        if blocked:
            return blocked

        ws, err = _get_workspace(slug)
        if err:
            return err
        member, err = _get_membership(ws)
        if err:
            return err

        query = BookingApproval.query.filter_by(workspace_id=ws.id)

        # Members only see their own
        if not member.is_admin_or_manager():
            query = query.filter_by(requester_user_id=current_user.id)

        # Optional status filter
        status_filter = request.args.get('status')
        if status_filter and status_filter in BookingApproval.STATUSES:
            query = query.filter_by(status=status_filter)

        approvals = query.order_by(BookingApproval.created_at.desc()).limit(100).all()
        return jsonify({
            'status': 'ok',
            'approvals': [a.to_dict() for a in approvals],
        })

    @app.route('/api/workspaces/<slug>/approvals/<int:approval_id>', methods=['PUT'])
    @login_required
    def decide_booking_approval(slug, approval_id):
        """Approve or deny a booking request (admin or travel_manager)."""
        blocked = _check_flag('travel_policies')
        if blocked:
            return blocked

        ws, err = _get_workspace(slug)
        if err:
            return err
        _, err = _require_admin_or_manager(ws)
        if err:
            return err

        approval = BookingApproval.query.filter_by(
            id=approval_id, workspace_id=ws.id
        ).first()
        if not approval:
            return jsonify({'status': 'error', 'error': 'Approval not found'}), 404

        if approval.status != 'pending':
            return jsonify({'status': 'error', 'error': f'Already {approval.status}'}), 400

        data = request.get_json(silent=True) or {}
        decision = (data.get('decision') or '').strip()
        if decision not in ('approved', 'denied'):
            return jsonify({'status': 'error', 'error': 'Decision must be "approved" or "denied"'}), 400

        approval.status = decision
        approval.approver_user_id = current_user.id
        approval.approver_note = data.get('note', '').strip() or None
        approval.decided_at = _utcnow()
        db.session.commit()

        logger.info("Booking approval %s: id=%d ws=%s by user=%s",
                     decision, approval.id, slug, current_user.id)
        return jsonify({'status': 'ok', 'approval': approval.to_dict()})

    # ══════════════════════════════════════════════════
    # BUILD #237 — DASHBOARD + BOOK-ON-BEHALF + EXPORT
    # ══════════════════════════════════════════════════

    @app.route('/api/workspaces/<slug>/dashboard', methods=['GET'])
    @login_required
    def workspace_dashboard(slug):
        """Corporate dashboard — spending summary, member stats, approval queue."""
        blocked = _check_flag('corporate_dashboard')
        if blocked:
            return blocked

        ws, err = _get_workspace(slug)
        if err:
            return err
        member, err = _get_membership(ws)
        if err:
            return err

        # Only admin/manager sees full dashboard
        is_elevated = member.is_admin_or_manager()

        # Member count by role
        members_q = WorkspaceMember.query.filter_by(workspace_id=ws.id, is_active=True)
        total_members = members_q.count()
        admins = members_q.filter_by(role='admin').count()
        managers = members_q.filter_by(role='travel_manager').count()

        # Booking stats — bookings from workspace members
        member_user_ids = [m.user_id for m in members_q.all()]

        total_bookings = 0
        total_spend = 0.0
        bookings_by_type = {}
        bookings_by_dept = {}

        if member_user_ids:
            bookings = Booking.query.filter(
                Booking.user_id.in_(member_user_ids),
                Booking.status.in_(['booked', 'completed']),
            ).all()
            total_bookings = len(bookings)
            for b in bookings:
                cost = b.vendor_payment_amount or 0
                total_spend += cost
                # Categorize (simplified — real impl would use expense tags)
                btype = 'flight'  # Default
                bookings_by_type[btype] = bookings_by_type.get(btype, 0) + 1

                # By department
                bm = WorkspaceMember.query.filter_by(
                    workspace_id=ws.id, user_id=b.user_id
                ).first()
                dept = bm.department if bm else 'Unassigned'
                bookings_by_dept[dept] = bookings_by_dept.get(dept, 0) + cost

        # Pending approvals count
        pending_approvals = BookingApproval.query.filter_by(
            workspace_id=ws.id, status='pending'
        ).count() if is_elevated else 0

        dashboard = {
            'workspace': ws.to_dict(include_stats=True),
            'members': {
                'total': total_members,
                'admins': admins,
                'travel_managers': managers,
                'regular_members': total_members - admins - managers,
            },
            'bookings': {
                'total': total_bookings,
                'total_spend_usd': round(total_spend, 2),
                'by_type': bookings_by_type,
                'by_department': {k: round(v, 2) for k, v in bookings_by_dept.items()},
            },
            'pending_approvals': pending_approvals,
            'tier_info': {
                'tier': ws.tier,
                'fee_percent': ws.fee_percent(),
                'per_seat_price': ws.per_seat_price(),
                'monthly_seat_cost': round(ws.per_seat_price() * total_members, 2),
                'base_cost': 9.99,
                'total_monthly': round(9.99 + ws.per_seat_price() * total_members, 2),
            },
        }

        return jsonify({'status': 'ok', 'dashboard': dashboard})

    @app.route('/api/workspaces/<slug>/book-on-behalf', methods=['POST'])
    @login_required
    def book_on_behalf(slug):
        """Admin/manager books a trip on behalf of another member.

        Creates a trip plan with the target member as owner, and the
        current user as the admin that initiated it.
        """
        blocked = _check_flag('corporate_dashboard')
        if blocked:
            return blocked

        ws, err = _get_workspace(slug)
        if err:
            return err
        _, err = _require_admin_or_manager(ws)
        if err:
            return err

        data = request.get_json(silent=True) or {}
        target_user_id = data.get('for_user_id')
        trip_name = (data.get('trip_name') or '').strip()

        if not target_user_id:
            return jsonify({'status': 'error', 'error': 'for_user_id required'}), 400
        if not trip_name:
            return jsonify({'status': 'error', 'error': 'trip_name required'}), 400

        # Verify target is a workspace member
        target_member = WorkspaceMember.query.filter_by(
            workspace_id=ws.id, user_id=target_user_id, is_active=True
        ).first()
        if not target_member:
            return jsonify({'status': 'error', 'error': 'Target user is not a workspace member'}), 404

        # Create trip owned by target, managed by current user
        trip = TripPlan(
            creator_id=target_user_id,
            name=trip_name,
            status='draft',
        )
        db.session.add(trip)
        db.session.flush()

        # Target is owner
        owner_member = TripMember(
            trip_plan_id=trip.id,
            user_id=target_user_id,
            role='owner',
            invitation_status='accepted',
            joined_at=_utcnow(),
        )
        db.session.add(owner_member)

        # Current user (admin/manager) is editor
        if current_user.id != target_user_id:
            admin_member = TripMember(
                trip_plan_id=trip.id,
                user_id=current_user.id,
                role='editor',
                invitation_status='accepted',
                joined_at=_utcnow(),
            )
            db.session.add(admin_member)

        db.session.commit()

        logger.info("Book-on-behalf: trip=%d for user=%d by admin=%d ws=%s",
                     trip.id, target_user_id, current_user.id, slug)
        return jsonify({
            'status': 'ok',
            'trip_id': trip.id,
            'trip_name': trip.name,
            'for_user_id': target_user_id,
            'for_user_name': target_member.user.name if target_member.user else None,
        })

    @app.route('/api/workspaces/<slug>/bookings', methods=['GET'])
    @login_required
    def workspace_bookings(slug):
        """List all bookings by workspace members (admin/manager: all, member: own)."""
        blocked = _check_flag('corporate_dashboard')
        if blocked:
            return blocked

        ws, err = _get_workspace(slug)
        if err:
            return err
        member, err = _get_membership(ws)
        if err:
            return err

        if member.is_admin_or_manager():
            member_ids = [m.user_id for m in WorkspaceMember.query.filter_by(
                workspace_id=ws.id, is_active=True
            ).all()]
        else:
            member_ids = [current_user.id]

        bookings = Booking.query.filter(
            Booking.user_id.in_(member_ids)
        ).order_by(Booking.created_at.desc()).limit(200).all()

        result = []
        for b in bookings:
            wm = WorkspaceMember.query.filter_by(
                workspace_id=ws.id, user_id=b.user_id
            ).first()
            result.append({
                'booking_id': b.id,
                'user_id': b.user_id,
                'user_name': b.user.name if b.user else None,
                'department': wm.department if wm else None,
                'status': b.status,
                'confirmation_code': b.confirmation_code,
                'vendor_payment_amount': b.vendor_payment_amount,
                'vendor_payment_currency': b.vendor_payment_currency,
                'created_at': b.created_at.isoformat() if b.created_at else None,
            })

        return jsonify({'status': 'ok', 'bookings': result, 'total': len(result)})

    @app.route('/api/workspaces/<slug>/export', methods=['GET'])
    @login_required
    def export_workspace_bookings(slug):
        """Export workspace bookings as CSV (admin/manager only)."""
        blocked = _check_flag('corporate_dashboard')
        if blocked:
            return blocked

        ws, err = _get_workspace(slug)
        if err:
            return err
        _, err = _require_admin_or_manager(ws)
        if err:
            return err

        member_ids = [m.user_id for m in WorkspaceMember.query.filter_by(
            workspace_id=ws.id, is_active=True
        ).all()]

        bookings = Booking.query.filter(
            Booking.user_id.in_(member_ids)
        ).order_by(Booking.created_at.desc()).all()

        # Build CSV
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            'Booking ID', 'Employee', 'Email', 'Department', 'Status',
            'Confirmation Code', 'Amount', 'Currency', 'Date',
        ])

        for b in bookings:
            wm = WorkspaceMember.query.filter_by(
                workspace_id=ws.id, user_id=b.user_id
            ).first()
            writer.writerow([
                b.id,
                b.user.name if b.user else '',
                b.user.email if b.user else '',
                wm.department if wm else '',
                b.status,
                b.confirmation_code or '',
                b.vendor_payment_amount or 0,
                b.vendor_payment_currency or 'USD',
                b.created_at.isoformat() if b.created_at else '',
            ])

        csv_data = output.getvalue()
        output.close()

        return Response(
            csv_data,
            mimetype='text/csv',
            headers={
                'Content-Disposition': f'attachment; filename={ws.slug}-bookings.csv',
            },
        )
