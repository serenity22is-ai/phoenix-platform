"""
Builds #225-227 — Managed Mode, Events, Tickets, Guest Info, QR Check-In

All endpoints gated behind FeatureFlag checks (managed_mode, event_system,
guest_info_collection, qr_checkin). Admin enables flags when Phase C launches.

Endpoints:
  Managed Mode (#225):
  - PUT    /api/trips/<id>/mode            — switch trip to managed/collaborative
  - GET    /api/trips/<id>/roster          — roster dashboard (managed only)
  - POST   /api/trips/<id>/announcements   — send announcement (managed only)
  - GET    /api/trips/<id>/announcements   — list announcements
  - PUT    /api/trips/<id>/capacity        — set capacity + waitlist + deadlines
  - POST   /api/trips/<id>/waitlist/promote — promote from waitlist

  Event System (#226):
  - PUT    /api/trips/<id>/event-config    — configure event fields
  - POST   /api/trips/<id>/tiers          — create ticket tier
  - GET    /api/trips/<id>/tiers          — list ticket tiers
  - PUT    /api/trips/<id>/tiers/<tid>    — update ticket tier
  - DELETE /api/trips/<id>/tiers/<tid>    — deactivate tier
  - POST   /api/trips/<id>/tiers/<tid>/purchase — purchase ticket (assign to guest)

  Guest Info Collection (#227):
  - POST   /api/trips/<id>/guests/<gid>/info      — submit guest info
  - GET    /api/trips/<id>/guests/<gid>/info      — get guest info
  - GET    /api/trips/<id>/guest-info-summary      — admin: all guests' info
  - POST   /api/trips/<id>/guests/<gid>/plus-one  — add a plus-one
  - POST   /api/trips/<id>/guests/<gid>/checkin    — QR check-in

Registration: register_event_routes(app, csrf, limiter)
"""

import json
import logging
from datetime import datetime, timezone

from flask import request, jsonify, render_template_string
from flask_login import current_user, login_required

from models import (
    db, FeatureFlag, TripPlan, TripMember, TripGuest,
    TripAnnouncement, TicketTier, TripGuestInfo,
)

logger = logging.getLogger(__name__)


def _utcnow():
    return datetime.now(timezone.utc)


def _check_trip_access(trip_id, require_edit=False):
    """Verify current user has access to this trip. Returns (trip, error_response)."""
    trip = db.session.get(TripPlan, trip_id)
    if not trip:
        return None, (jsonify({'status': 'error', 'error': 'Trip not found'}), 404)

    if trip.creator_id == current_user.id:
        return trip, None

    member = TripMember.query.filter_by(
        trip_plan_id=trip_id, user_id=current_user.id
    ).first()
    if not member:
        guest = TripGuest.query.filter_by(
            trip_id=trip_id, user_id=current_user.id
        ).first()
        if not guest:
            return None, (jsonify({'status': 'error', 'error': 'Access denied'}), 403)
        if require_edit and guest.role in ('viewer',):
            return None, (jsonify({'status': 'error', 'error': 'Edit access required'}), 403)
        return trip, None

    if require_edit and member.role == 'viewer':
        return None, (jsonify({'status': 'error', 'error': 'Edit access required'}), 403)

    return trip, None


def _check_flag(flag_key):
    """Check if a feature flag is enabled. Returns error response if disabled."""
    if not FeatureFlag.is_flag_enabled(flag_key):
        return jsonify({
            'status': 'error',
            'error': f'Feature "{flag_key}" is not enabled. Enable via admin panel.',
        }), 403
    return None


def _is_trip_admin(trip, user_id):
    """Check if user is trip creator or has admin/owner role."""
    if trip.creator_id == user_id:
        return True
    member = TripMember.query.filter_by(
        trip_plan_id=trip.id, user_id=user_id
    ).first()
    if member and member.role in ('owner', 'editor'):
        return True
    guest = TripGuest.query.filter_by(
        trip_id=trip.id, user_id=user_id
    ).first()
    if guest and guest.role in ('owner', 'admin'):
        return True
    return False


# ============================================================
# EVENT MANAGEMENT DASHBOARD — Page Template
# ============================================================

EVENTS_PAGE_CONTENT = '''
<style>
    /* ============================================
       EVENTS DASHBOARD — Page-specific styles
       ============================================ */
    .ev-page { max-width: 1060px; margin: 0 auto; padding: 0 16px 80px; }

    /* Tab navigation */
    .ev-tabs {
        display: flex; gap: 0; margin-bottom: 32px;
        border-bottom: 1px solid rgba(255,255,255,0.08);
        overflow-x: auto; -webkit-overflow-scrolling: touch;
    }
    .ev-tab {
        padding: 14px 22px; font-size: 13px; letter-spacing: 1.5px;
        text-transform: uppercase; color: rgba(255,255,255,0.45);
        cursor: pointer; white-space: nowrap; position: relative;
        transition: color 0.2s; font-family: var(--font-brand, 'Space Grotesk', sans-serif);
        background: none; border: none;
    }
    .ev-tab:hover { color: rgba(255,255,255,0.7); }
    .ev-tab.active { color: #14b8a6; }
    .ev-tab.active::after {
        content: ''; position: absolute; bottom: -1px; left: 0; right: 0;
        height: 2px; background: #14b8a6; border-radius: 2px 2px 0 0;
    }
    .ev-panel { display: none; }
    .ev-panel.active { display: block; }

    /* Mode toggle switch */
    .ev-mode-row { display: flex; align-items: center; gap: 16px; margin-bottom: 28px; }
    .ev-mode-label { font-size: 14px; color: rgba(255,255,255,0.5); letter-spacing: 0.5px; }
    .ev-mode-label.active-label { color: #f5f5f5; font-weight: 600; }
    .ev-switch {
        position: relative; width: 52px; height: 28px; cursor: pointer;
        background: rgba(255,255,255,0.08); border-radius: 14px; transition: background 0.3s;
        border: 1px solid rgba(255,255,255,0.1); flex-shrink: 0;
    }
    .ev-switch.on { background: rgba(20,184,166,0.3); border-color: rgba(20,184,166,0.5); }
    .ev-switch-dot {
        position: absolute; top: 3px; left: 3px; width: 20px; height: 20px;
        background: #fff; border-radius: 50%; transition: transform 0.3s;
    }
    .ev-switch.on .ev-switch-dot { transform: translateX(24px); }

    /* Form sections */
    .ev-form-section { margin-bottom: 28px; }
    .ev-form-section-title {
        font-family: var(--font-brand, 'Space Grotesk', sans-serif);
        font-size: 12px; letter-spacing: 2px; text-transform: uppercase;
        color: rgba(255,255,255,0.4); margin: 0 0 14px;
    }
    .ev-form-grid {
        display: grid; grid-template-columns: 1fr 1fr; gap: 14px;
    }
    .ev-form-full { grid-column: 1 / -1; }
    .ev-input, .ev-select, .ev-textarea {
        width: 100%; padding: 12px 16px; font-size: 14px; color: #f5f5f5;
        background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1);
        border-radius: 10px; outline: none; transition: border-color 0.2s;
        font-family: 'Outfit', sans-serif;
    }
    .ev-input:focus, .ev-select:focus, .ev-textarea:focus {
        border-color: rgba(20,184,166,0.5);
    }
    .ev-textarea { min-height: 90px; resize: vertical; }
    .ev-select { appearance: none; background-image: url("data:image/svg+xml,%3Csvg width='10' height='6' viewBox='0 0 10 6' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M1 1l4 4 4-4' stroke='%23888' fill='none' stroke-width='1.5'/%3E%3C/svg%3E"); background-repeat: no-repeat; background-position: right 14px center; padding-right: 36px; }
    .ev-select option { background: #1a1025; color: #f5f5f5; }

    /* Stat cards row */
    .ev-stats {
        display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
        gap: 12px; margin-bottom: 28px;
    }
    .ev-stat-card {
        background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08);
        border-radius: 14px; padding: 18px 16px; text-align: center;
    }
    .ev-stat-num {
        font-family: var(--font-brand, 'Space Grotesk', sans-serif);
        font-size: 28px; font-weight: 700; color: #f5f5f5; line-height: 1;
    }
    .ev-stat-num.teal { color: #14b8a6; }
    .ev-stat-num.gold { color: #C9A96E; }
    .ev-stat-num.purple { color: #7c3aed; }
    .ev-stat-label { font-size: 11px; letter-spacing: 1.5px; text-transform: uppercase; color: rgba(255,255,255,0.4); margin-top: 6px; }

    /* Tier cards */
    .ev-tiers-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; margin-bottom: 24px; }
    .ev-tier-card {
        background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08);
        border-radius: 16px; padding: 22px; position: relative;
        backdrop-filter: blur(12px); transition: border-color 0.2s;
    }
    .ev-tier-card:hover { border-color: rgba(255,255,255,0.15); }
    .ev-tier-name { font-family: var(--font-brand, 'Space Grotesk', sans-serif); font-size: 16px; font-weight: 600; color: #f5f5f5; margin-bottom: 4px; }
    .ev-tier-price { font-size: 22px; font-weight: 700; color: #14b8a6; margin-bottom: 12px; }
    .ev-tier-price .free { color: #C9A96E; }
    .ev-cap-bar { height: 6px; background: rgba(255,255,255,0.06); border-radius: 3px; overflow: hidden; margin-bottom: 6px; }
    .ev-cap-fill { height: 100%; background: linear-gradient(90deg, #14b8a6, #7c3aed); border-radius: 3px; transition: width 0.4s ease; }
    .ev-cap-text { font-size: 11px; color: rgba(255,255,255,0.4); margin-bottom: 12px; }
    .ev-tier-includes { list-style: none; padding: 0; margin: 0 0 16px; }
    .ev-tier-includes li { font-size: 13px; color: rgba(255,255,255,0.6); padding: 3px 0 3px 18px; position: relative; }
    .ev-tier-includes li::before { content: '\\2713'; position: absolute; left: 0; color: #14b8a6; font-size: 12px; }
    .ev-tier-actions { display: flex; gap: 8px; }
    .ev-tier-inactive { opacity: 0.4; }

    /* Roster table */
    .ev-roster-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; }
    .ev-roster-table { width: 100%; border-collapse: collapse; font-size: 13px; }
    .ev-roster-table th {
        text-align: left; padding: 10px 14px; font-size: 11px; letter-spacing: 1.5px;
        text-transform: uppercase; color: rgba(255,255,255,0.35); border-bottom: 1px solid rgba(255,255,255,0.08);
        font-family: var(--font-brand, 'Space Grotesk', sans-serif);
    }
    .ev-roster-table td { padding: 12px 14px; color: rgba(255,255,255,0.8); border-bottom: 1px solid rgba(255,255,255,0.04); }
    .ev-roster-table tr:hover td { background: rgba(255,255,255,0.02); }

    /* Badges */
    .ev-badge {
        display: inline-block; padding: 3px 10px; border-radius: 20px; font-size: 11px;
        letter-spacing: 0.5px; font-weight: 600; text-transform: uppercase;
    }
    .ev-badge-green { background: rgba(20,184,166,0.15); color: #14b8a6; }
    .ev-badge-gold { background: rgba(201,169,110,0.15); color: #C9A96E; }
    .ev-badge-purple { background: rgba(124,58,237,0.15); color: #a78bfa; }
    .ev-badge-red { background: rgba(239,68,68,0.12); color: #f87171; }
    .ev-badge-gray { background: rgba(255,255,255,0.06); color: rgba(255,255,255,0.4); }
    .ev-badge-amber { background: rgba(245,158,11,0.12); color: #fbbf24; }

    /* Roster filter row */
    .ev-filter-row { display: flex; gap: 10px; margin-bottom: 18px; flex-wrap: wrap; align-items: center; }
    .ev-filter-input {
        flex: 1; min-width: 180px; padding: 10px 14px; font-size: 13px; color: #f5f5f5;
        background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1);
        border-radius: 10px; outline: none;
    }
    .ev-filter-input:focus { border-color: rgba(20,184,166,0.4); }

    /* Announcement feed */
    .ev-ann-card {
        background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08);
        border-radius: 14px; padding: 18px 20px; margin-bottom: 14px;
    }
    .ev-ann-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
    .ev-ann-sender { font-size: 13px; font-weight: 600; color: #f5f5f5; }
    .ev-ann-time { font-size: 11px; color: rgba(255,255,255,0.3); }
    .ev-ann-body { font-size: 14px; color: rgba(255,255,255,0.7); line-height: 1.6; white-space: pre-wrap; }

    /* Buttons */
    .ev-btn {
        display: inline-flex; align-items: center; justify-content: center; gap: 6px;
        padding: 10px 20px; font-size: 13px; font-weight: 600; letter-spacing: 0.5px;
        border: none; border-radius: 10px; cursor: pointer; transition: all 0.2s;
        font-family: 'Outfit', sans-serif;
    }
    .ev-btn-teal { background: rgba(20,184,166,0.15); color: #14b8a6; border: 1px solid rgba(20,184,166,0.3); }
    .ev-btn-teal:hover { background: rgba(20,184,166,0.25); }
    .ev-btn-gold { background: rgba(201,169,110,0.15); color: #C9A96E; border: 1px solid rgba(201,169,110,0.3); }
    .ev-btn-gold:hover { background: rgba(201,169,110,0.25); }
    .ev-btn-purple { background: rgba(124,58,237,0.15); color: #a78bfa; border: 1px solid rgba(124,58,237,0.3); }
    .ev-btn-purple:hover { background: rgba(124,58,237,0.25); }
    .ev-btn-red { background: rgba(239,68,68,0.1); color: #f87171; border: 1px solid rgba(239,68,68,0.2); }
    .ev-btn-red:hover { background: rgba(239,68,68,0.2); }
    .ev-btn-sm { padding: 6px 14px; font-size: 12px; }
    .ev-btn:disabled { opacity: 0.4; cursor: not-allowed; }

    /* Guest info table */
    .ev-info-table { width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 16px; }
    .ev-info-table th { text-align: left; padding: 8px 12px; font-size: 11px; letter-spacing: 1.5px; text-transform: uppercase; color: rgba(255,255,255,0.35); border-bottom: 1px solid rgba(255,255,255,0.08); }
    .ev-info-table td { padding: 10px 12px; color: rgba(255,255,255,0.7); border-bottom: 1px solid rgba(255,255,255,0.04); }

    /* Empty state */
    .ev-empty { text-align: center; padding: 48px 20px; color: rgba(255,255,255,0.3); font-size: 14px; }
    .ev-empty-icon { font-size: 32px; margin-bottom: 12px; opacity: 0.4; }

    /* Toast notification */
    .ev-toast {
        position: fixed; bottom: 24px; right: 24px; padding: 14px 24px;
        background: rgba(20,184,166,0.95); color: #fff; border-radius: 10px;
        font-size: 13px; font-weight: 600; z-index: 9999;
        transform: translateY(80px); opacity: 0; transition: all 0.3s ease;
    }
    .ev-toast.show { transform: translateY(0); opacity: 1; }
    .ev-toast.error { background: rgba(239,68,68,0.95); }

    @media (max-width: 640px) {
        .ev-form-grid { grid-template-columns: 1fr; }
        .ev-tiers-grid { grid-template-columns: 1fr; }
        .ev-stats { grid-template-columns: repeat(2, 1fr); }
        .ev-tabs { gap: 0; }
        .ev-tab { padding: 12px 14px; font-size: 11px; }
    }
</style>

<div class="ev-page">
    <div style="margin-bottom: 32px;">
        <div style="display:flex; gap:12px; align-items:center;">
            <a href="/trips/{{ trip_id }}" style="font-size:13px; color:rgba(255,255,255,0.4); text-decoration:none; letter-spacing:0.5px;">&#8592; Back to Trip</a>
            <span style="color:rgba(255,255,255,0.15);">|</span>
            <a href="/trips/{{ trip_id }}/plan" style="font-size:13px; color:#14b8a6; text-decoration:none; letter-spacing:0.5px;">&#9776; Planner</a>
        </div>
        <h1 style="font-family: var(--font-brand, 'Space Grotesk', sans-serif); font-size: 28px; color: #f5f5f5; margin: 8px 0 4px; letter-spacing: 1px;">EVENT DASHBOARD</h1>
        <p id="evTripName" style="font-size: 14px; color: rgba(255,255,255,0.4);"></p>
    </div>

    <!-- Tab navigation -->
    <div class="ev-tabs" id="evTabs">
        <button class="ev-tab active" data-tab="setup" onclick="switchTab('setup')">Setup</button>
        <button class="ev-tab" data-tab="tickets" onclick="switchTab('tickets')">Tickets</button>
        <button class="ev-tab" data-tab="roster" onclick="switchTab('roster')">Roster</button>
        <button class="ev-tab" data-tab="announcements" onclick="switchTab('announcements')">Announcements</button>
        <button class="ev-tab" data-tab="guestinfo" onclick="switchTab('guestinfo')">Guest Info</button>
    </div>

    <!-- ============================= TAB 1: SETUP ============================= -->
    <div class="ev-panel active" id="panel-setup">

        <!-- Mode toggle -->
        <div style="background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 16px; padding: 24px; margin-bottom: 24px; backdrop-filter: blur(12px);">
            <div class="ev-form-section-title">Trip Mode</div>
            <div class="ev-mode-row">
                <span class="ev-mode-label" id="lblCollab">Collaborative</span>
                <div class="ev-switch" id="modeSwitch" onclick="toggleMode()">
                    <div class="ev-switch-dot"></div>
                </div>
                <span class="ev-mode-label" id="lblManaged">Managed</span>
            </div>
            <p style="font-size: 12px; color: rgba(255,255,255,0.3); margin: 0;">
                <strong>Collaborative</strong>: everyone edits the trip together. <strong>Managed</strong>: you control the roster, tickets, and announcements.
            </p>
        </div>

        <!-- Event config form -->
        <div style="background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 16px; padding: 24px; margin-bottom: 24px; backdrop-filter: blur(12px);">
            <div class="ev-form-section-title">Event Details</div>
            <div class="ev-form-grid">
                <input type="text" class="ev-input" id="cfgEventName" placeholder="Event name">
                <input type="text" class="ev-input" id="cfgVenue" placeholder="Venue name">
                <input type="text" class="ev-input ev-form-full" id="cfgVenueAddr" placeholder="Venue address">
                <textarea class="ev-textarea ev-form-full" id="cfgDescription" placeholder="Event description"></textarea>
                <div>
                    <label style="font-size: 11px; color: rgba(255,255,255,0.35); letter-spacing: 1px; text-transform: uppercase; display: block; margin-bottom: 6px;">Registration Type</label>
                    <select class="ev-select" id="cfgRegType">
                        <option value="invite_only">Invite Only</option>
                        <option value="public">Public</option>
                    </select>
                </div>
                <div></div>
            </div>
            <button class="ev-btn ev-btn-teal" style="margin-top: 18px;" onclick="saveEventConfig()" id="btnSaveConfig">Save Event Config</button>
        </div>

        <!-- Capacity settings -->
        <div style="background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 16px; padding: 24px; backdrop-filter: blur(12px);">
            <div class="ev-form-section-title">Capacity &amp; Deadlines</div>
            <div class="ev-form-grid">
                <div>
                    <label style="font-size: 11px; color: rgba(255,255,255,0.35); letter-spacing: 1px; text-transform: uppercase; display: block; margin-bottom: 6px;">Max Capacity</label>
                    <input type="number" class="ev-input" id="cfgCapacity" placeholder="Unlimited" min="1">
                </div>
                <div style="display: flex; align-items: center; gap: 12px; padding-top: 20px;">
                    <div class="ev-switch" id="waitlistSwitch" onclick="toggleWaitlist()" style="width: 44px; height: 24px;">
                        <div class="ev-switch-dot" style="width: 18px; height: 18px; top: 2px; left: 2px;"></div>
                    </div>
                    <span style="font-size: 13px; color: rgba(255,255,255,0.6);">Enable Waitlist</span>
                </div>
                <div>
                    <label style="font-size: 11px; color: rgba(255,255,255,0.35); letter-spacing: 1px; text-transform: uppercase; display: block; margin-bottom: 6px;">Registration Deadline</label>
                    <input type="datetime-local" class="ev-input" id="cfgRegDeadline">
                </div>
                <div>
                    <label style="font-size: 11px; color: rgba(255,255,255,0.35); letter-spacing: 1px; text-transform: uppercase; display: block; margin-bottom: 6px;">Payment Deadline</label>
                    <input type="datetime-local" class="ev-input" id="cfgPayDeadline">
                </div>
            </div>
            <button class="ev-btn ev-btn-teal" style="margin-top: 18px;" onclick="saveCapacity()" id="btnSaveCap">Save Capacity Settings</button>
        </div>
    </div>

    <!-- ============================= TAB 2: TICKETS ============================= -->
    <div class="ev-panel" id="panel-tickets">

        <div class="ev-tiers-grid" id="tiersGrid">
            <div class="ev-empty"><div class="ev-empty-icon">&#127915;</div>No ticket tiers yet</div>
        </div>

        <!-- Add tier form -->
        <div style="background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 16px; padding: 24px; backdrop-filter: blur(12px);">
            <div class="ev-form-section-title">Add Ticket Tier</div>
            <div class="ev-form-grid">
                <input type="text" class="ev-input" id="tierName" placeholder="Tier name (e.g. General Admission)">
                <input type="number" class="ev-input" id="tierPrice" placeholder="Price (USD)" step="0.01" min="0">
                <input type="number" class="ev-input" id="tierCapacity" placeholder="Capacity (leave blank = unlimited)" min="1">
                <div></div>
                <textarea class="ev-textarea ev-form-full" id="tierInclusions" placeholder="What's included (one item per line)"></textarea>
            </div>
            <button class="ev-btn ev-btn-gold" style="margin-top: 18px;" onclick="addTier()" id="btnAddTier">+ Add Tier</button>
        </div>
    </div>

    <!-- ============================= TAB 3: ROSTER ============================= -->
    <div class="ev-panel" id="panel-roster">

        <div class="ev-stats" id="rosterStats">
            <div class="ev-stat-card"><div class="ev-stat-num" id="statTotal">--</div><div class="ev-stat-label">Total Guests</div></div>
            <div class="ev-stat-card"><div class="ev-stat-num teal" id="statConfirmed">--</div><div class="ev-stat-label">Confirmed</div></div>
            <div class="ev-stat-card"><div class="ev-stat-num gold" id="statWaitlisted">--</div><div class="ev-stat-label">Waitlisted</div></div>
            <div class="ev-stat-card"><div class="ev-stat-num purple" id="statPaid">--</div><div class="ev-stat-label">Paid</div></div>
            <div class="ev-stat-card"><div class="ev-stat-num" id="statCheckedIn">--</div><div class="ev-stat-label">Checked In</div></div>
        </div>

        <div class="ev-filter-row">
            <input type="text" class="ev-filter-input" id="rosterSearch" placeholder="Filter by name..." oninput="filterRoster()">
            <select class="ev-select" id="rosterFilter" style="min-width: 140px; flex: 0;" onchange="filterRoster()">
                <option value="all">All Guests</option>
                <option value="attending">Confirmed</option>
                <option value="waitlisted">Waitlisted</option>
                <option value="invited">Invited</option>
                <option value="declined">Declined</option>
            </select>
            <button class="ev-btn ev-btn-gold ev-btn-sm" onclick="promoteNext()" id="btnPromote">Promote from Waitlist</button>
        </div>

        <div class="ev-roster-wrap">
            <table class="ev-roster-table" id="rosterTable">
                <thead>
                    <tr>
                        <th>Guest</th>
                        <th>Tier</th>
                        <th>RSVP</th>
                        <th>Payment</th>
                        <th>Check-in</th>
                        <th></th>
                    </tr>
                </thead>
                <tbody id="rosterBody">
                    <tr><td colspan="6" class="ev-empty">Loading roster...</td></tr>
                </tbody>
            </table>
        </div>
    </div>

    <!-- ============================= TAB 4: ANNOUNCEMENTS ============================= -->
    <div class="ev-panel" id="panel-announcements">

        <!-- Composer -->
        <div style="background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 16px; padding: 24px; margin-bottom: 28px; backdrop-filter: blur(12px);">
            <div class="ev-form-section-title">New Announcement</div>
            <textarea class="ev-textarea" id="annBody" placeholder="Write your announcement..." style="margin-bottom: 12px;"></textarea>
            <div style="display: flex; gap: 12px; align-items: center; flex-wrap: wrap;">
                <select class="ev-select" id="annAudience" style="width: auto; min-width: 160px;">
                    <option value="all">All Guests</option>
                    <option value="confirmed_only">Confirmed Only</option>
                    <option value="pending_only">Pending Only</option>
                    <option value="waitlisted_only">Waitlisted Only</option>
                </select>
                <button class="ev-btn ev-btn-teal" onclick="sendAnnouncement()" id="btnSendAnn">Send Announcement</button>
            </div>
        </div>

        <!-- Feed -->
        <div id="annFeed">
            <div class="ev-empty"><div class="ev-empty-icon">&#128227;</div>No announcements yet</div>
        </div>
    </div>

    <!-- ============================= TAB 5: GUEST INFO ============================= -->
    <div class="ev-panel" id="panel-guestinfo">

        <!-- Admin summary -->
        <div style="background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 16px; padding: 24px; margin-bottom: 24px; backdrop-filter: blur(12px);">
            <div class="ev-form-section-title">Guest Info Summary</div>
            <p style="font-size: 12px; color: rgba(255,255,255,0.3); margin: 0 0 16px;">Collected fields from all guests. Click a row to edit.</p>
            <div class="ev-roster-wrap">
                <table class="ev-info-table" id="infoTable">
                    <thead id="infoTableHead">
                        <tr><th>Guest</th></tr>
                    </thead>
                    <tbody id="infoTableBody">
                        <tr><td class="ev-empty">Loading guest info...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>

        <!-- Per-guest info form (shown on click) -->
        <div id="guestInfoEditor" style="display: none; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 16px; padding: 24px; backdrop-filter: blur(12px);">
            <div class="ev-form-section-title">Edit Guest Info &mdash; <span id="editGuestName"></span></div>
            <div class="ev-form-grid" id="guestInfoFields"></div>
            <button class="ev-btn ev-btn-teal" style="margin-top: 16px;" onclick="saveGuestInfo()" id="btnSaveInfo">Save Guest Info</button>
        </div>
    </div>
</div>

<!-- Toast -->
<div class="ev-toast" id="evToast"></div>

<script>
var TRIP_ID = {{ trip_id }};
var currentTab = 'setup';
var rosterData = [];
var tiersData = [];
var editingGuestId = null;

/* ---- CSRF ---- */
function csrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.content : '';
}

function api(url, opts) {
    opts = opts || {};
    opts.headers = opts.headers || {};
    opts.headers['Content-Type'] = 'application/json';
    var tok = csrfToken();
    if (tok) opts.headers['X-CSRFToken'] = tok;
    opts.credentials = 'same-origin';
    return fetch(url, opts).then(function(r) { return r.json(); });
}

/* ---- Toast ---- */
function toast(msg, isError) {
    var el = document.getElementById('evToast');
    el.textContent = msg;
    el.className = 'ev-toast show' + (isError ? ' error' : '');
    setTimeout(function() { el.className = 'ev-toast'; }, 3000);
}

/* ---- Tab switching ---- */
function switchTab(tab) {
    currentTab = tab;
    var tabs = document.querySelectorAll('.ev-tab');
    var panels = document.querySelectorAll('.ev-panel');
    for (var i = 0; i < tabs.length; i++) {
        tabs[i].classList.toggle('active', tabs[i].getAttribute('data-tab') === tab);
    }
    for (var j = 0; j < panels.length; j++) {
        panels[j].classList.toggle('active', panels[j].id === 'panel-' + tab);
    }
    if (tab === 'roster') loadRoster();
    if (tab === 'tickets') loadTiers();
    if (tab === 'announcements') loadAnnouncements();
    if (tab === 'guestinfo') loadGuestInfoSummary();
}

/* ============================================================
   TAB 1: SETUP
   ============================================================ */

function loadTripConfig() {
    api('/api/trips/' + TRIP_ID + '/tiers').then(function() {});
    /* Populate mode from trip data if available */
    api('/api/trips/' + TRIP_ID + '/roster').then(function(data) {
        if (data.status === 'ok') {
            updateModeUI(data.summary);
        }
    }).catch(function() {});
}

function updateModeUI(summary) {
    if (summary && summary.capacity !== undefined) {
        var capEl = document.getElementById('cfgCapacity');
        if (summary.capacity) capEl.value = summary.capacity;
    }
}

function toggleMode() {
    var sw = document.getElementById('modeSwitch');
    var isManaged = sw.classList.contains('on');
    var newMode = isManaged ? 'collaborative' : 'managed';
    api('/api/trips/' + TRIP_ID + '/mode', {
        method: 'PUT',
        body: JSON.stringify({ mode: newMode })
    }).then(function(data) {
        if (data.status === 'ok') {
            setModeSwitch(data.mode === 'managed');
            toast('Mode: ' + data.mode);
        } else {
            toast(data.error || 'Failed to change mode', true);
        }
    }).catch(function() { toast('Network error', true); });
}

function setModeSwitch(isManaged) {
    var sw = document.getElementById('modeSwitch');
    sw.classList.toggle('on', isManaged);
    document.getElementById('lblCollab').classList.toggle('active-label', !isManaged);
    document.getElementById('lblManaged').classList.toggle('active-label', isManaged);
}

function toggleWaitlist() {
    var sw = document.getElementById('waitlistSwitch');
    sw.classList.toggle('on');
}

function saveEventConfig() {
    var btn = document.getElementById('btnSaveConfig');
    btn.disabled = true; btn.textContent = 'Saving...';
    var body = {
        event_name: document.getElementById('cfgEventName').value,
        venue_name: document.getElementById('cfgVenue').value,
        venue_address: document.getElementById('cfgVenueAddr').value,
        event_description: document.getElementById('cfgDescription').value,
        registration_type: document.getElementById('cfgRegType').value
    };
    api('/api/trips/' + TRIP_ID + '/event-config', {
        method: 'PUT', body: JSON.stringify(body)
    }).then(function(data) {
        btn.disabled = false; btn.textContent = 'Save Event Config';
        if (data.status === 'ok') {
            toast('Event config saved');
            if (data.trip && data.trip.event_name) {
                document.getElementById('evTripName').textContent = data.trip.event_name;
            }
        } else {
            toast(data.error || 'Save failed', true);
        }
    }).catch(function() { btn.disabled = false; btn.textContent = 'Save Event Config'; toast('Network error', true); });
}

function saveCapacity() {
    var btn = document.getElementById('btnSaveCap');
    btn.disabled = true; btn.textContent = 'Saving...';
    var capVal = document.getElementById('cfgCapacity').value;
    var body = {
        capacity: capVal ? parseInt(capVal) : null,
        waitlist_enabled: document.getElementById('waitlistSwitch').classList.contains('on'),
        registration_deadline: document.getElementById('cfgRegDeadline').value || null,
        payment_deadline: document.getElementById('cfgPayDeadline').value || null
    };
    api('/api/trips/' + TRIP_ID + '/capacity', {
        method: 'PUT', body: JSON.stringify(body)
    }).then(function(data) {
        btn.disabled = false; btn.textContent = 'Save Capacity Settings';
        if (data.status === 'ok') {
            toast('Capacity settings saved');
        } else {
            toast(data.error || 'Save failed', true);
        }
    }).catch(function() { btn.disabled = false; btn.textContent = 'Save Capacity Settings'; toast('Network error', true); });
}

/* ============================================================
   TAB 2: TICKETS
   ============================================================ */

function loadTiers() {
    api('/api/trips/' + TRIP_ID + '/tiers').then(function(data) {
        if (data.status === 'ok') {
            tiersData = data.tiers || [];
            renderTiers();
        }
    }).catch(function() {});
}

function renderTiers() {
    var grid = document.getElementById('tiersGrid');
    if (!tiersData.length) {
        grid.innerHTML = '<div class="ev-empty"><div class="ev-empty-icon">&#127915;</div>No ticket tiers yet. Create one below.</div>';
        return;
    }
    var html = '';
    for (var i = 0; i < tiersData.length; i++) {
        var t = tiersData[i];
        var priceStr = t.price_usd > 0 ? ('$' + t.price_usd.toFixed(2)) : '<span class="free">FREE</span>';
        var capPct = (t.capacity && t.capacity > 0) ? Math.min(100, Math.round((t.sold_count / t.capacity) * 100)) : 0;
        var capText = t.capacity ? (t.sold_count + ' / ' + t.capacity + ' sold') : (t.sold_count + ' sold (unlimited)');
        var includes = [];
        if (t.includes_travel) includes.push('Travel included');
        if (t.includes_accommodation) includes.push('Accommodation included');
        /* Parse included_items if present */
        var inclList = '';
        if (includes.length) {
            inclList = '<ul class="ev-tier-includes">';
            for (var k = 0; k < includes.length; k++) {
                inclList += '<li>' + includes[k] + '</li>';
            }
            inclList += '</ul>';
        }
        var inactiveClass = t.is_active ? '' : ' ev-tier-inactive';
        html += '<div class="ev-tier-card' + inactiveClass + '">' +
            '<div class="ev-tier-name">' + escHtml(t.name) + '</div>' +
            '<div class="ev-tier-price">' + priceStr + '</div>' +
            '<div class="ev-cap-bar"><div class="ev-cap-fill" style="width:' + capPct + '%"></div></div>' +
            '<div class="ev-cap-text">' + capText + (t.is_sold_out ? ' &mdash; <strong style="color:#f87171;">SOLD OUT</strong>' : '') + '</div>' +
            (t.description ? '<p style="font-size:13px;color:rgba(255,255,255,0.5);margin:0 0 10px;">' + escHtml(t.description) + '</p>' : '') +
            inclList +
            (!t.is_active ? '<div style="margin-bottom:10px;"><span class="ev-badge ev-badge-gray">INACTIVE</span></div>' : '') +
            '<div class="ev-tier-actions">' +
                '<button class="ev-btn ev-btn-purple ev-btn-sm" onclick="editTier(' + t.id + ')">Edit</button>' +
                (t.is_active ? '<button class="ev-btn ev-btn-red ev-btn-sm" onclick="deleteTier(' + t.id + ')">Deactivate</button>' : '') +
            '</div>' +
        '</div>';
    }
    grid.innerHTML = html;
}

function addTier() {
    var btn = document.getElementById('btnAddTier');
    btn.disabled = true; btn.textContent = 'Adding...';
    var inclText = document.getElementById('tierInclusions').value.trim();
    var inclArr = inclText ? inclText.split('\\n').filter(function(l) { return l.trim(); }) : [];
    var body = {
        name: document.getElementById('tierName').value.trim(),
        price_usd: parseFloat(document.getElementById('tierPrice').value) || 0,
        capacity: document.getElementById('tierCapacity').value ? parseInt(document.getElementById('tierCapacity').value) : null,
        included_items: inclArr.length ? inclArr : null
    };
    if (!body.name) { toast('Tier name is required', true); btn.disabled = false; btn.textContent = '+ Add Tier'; return; }
    api('/api/trips/' + TRIP_ID + '/tiers', {
        method: 'POST', body: JSON.stringify(body)
    }).then(function(data) {
        btn.disabled = false; btn.textContent = '+ Add Tier';
        if (data.status === 'ok') {
            toast('Tier created');
            document.getElementById('tierName').value = '';
            document.getElementById('tierPrice').value = '';
            document.getElementById('tierCapacity').value = '';
            document.getElementById('tierInclusions').value = '';
            loadTiers();
        } else {
            toast(data.error || 'Failed to create tier', true);
        }
    }).catch(function() { btn.disabled = false; btn.textContent = '+ Add Tier'; toast('Network error', true); });
}

function editTier(tierId) {
    var tier = null;
    for (var i = 0; i < tiersData.length; i++) {
        if (tiersData[i].id === tierId) { tier = tiersData[i]; break; }
    }
    if (!tier) return;
    var newName = prompt('Tier name:', tier.name);
    if (newName === null) return;
    var newPrice = prompt('Price (USD):', tier.price_usd);
    if (newPrice === null) return;
    var newCap = prompt('Capacity (blank = unlimited):', tier.capacity || '');
    var body = { name: newName.trim() || tier.name };
    var p = parseFloat(newPrice);
    if (!isNaN(p) && p >= 0) body.price_usd = p;
    body.capacity = newCap ? parseInt(newCap) : null;
    api('/api/trips/' + TRIP_ID + '/tiers/' + tierId, {
        method: 'PUT', body: JSON.stringify(body)
    }).then(function(data) {
        if (data.status === 'ok') { toast('Tier updated'); loadTiers(); }
        else toast(data.error || 'Update failed', true);
    }).catch(function() { toast('Network error', true); });
}

function deleteTier(tierId) {
    if (!confirm('Deactivate this tier? Existing ticket holders are preserved.')) return;
    api('/api/trips/' + TRIP_ID + '/tiers/' + tierId, {
        method: 'DELETE'
    }).then(function(data) {
        if (data.status === 'ok') { toast('Tier deactivated'); loadTiers(); }
        else toast(data.error || 'Failed', true);
    }).catch(function() { toast('Network error', true); });
}

/* ============================================================
   TAB 3: ROSTER
   ============================================================ */

function loadRoster() {
    api('/api/trips/' + TRIP_ID + '/roster').then(function(data) {
        if (data.status === 'ok') {
            rosterData = data.roster || [];
            updateRosterStats(data.summary);
            renderRoster(rosterData);
        }
    }).catch(function() {});
}

function updateRosterStats(s) {
    document.getElementById('statTotal').textContent = s.total || 0;
    document.getElementById('statConfirmed').textContent = s.confirmed || 0;
    document.getElementById('statWaitlisted').textContent = s.waitlisted || 0;
    document.getElementById('statPaid').textContent = s.paid || 0;
    document.getElementById('statCheckedIn').textContent = s.checked_in || 0;
}

function renderRoster(guests) {
    var tbody = document.getElementById('rosterBody');
    if (!guests.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="ev-empty">No guests yet.</td></tr>';
        return;
    }
    var html = '';
    for (var i = 0; i < guests.length; i++) {
        var g = guests[i];
        var rsvpBadge = rsvpBadgeHtml(g.rsvp_status);
        var payBadge = paymentBadgeHtml(g.payment_status);
        var checkinHtml = g.checked_in ? '<span class="ev-badge ev-badge-green">IN</span>' :
            '<button class="ev-btn ev-btn-teal ev-btn-sm" onclick="checkinGuest(' + g.id + ')">Check In</button>';
        var tierName = g.ticket_tier_name || '<span style="color:rgba(255,255,255,0.25);">--</span>';
        var plusOne = g.plus_one_of ? ' <span style="font-size:10px;color:rgba(255,255,255,0.3);">(+1)</span>' : '';
        html += '<tr data-name="' + escAttr(g.display_name || '') + '" data-rsvp="' + escAttr(g.rsvp_status || '') + '">' +
            '<td>' + escHtml(g.display_name || 'Guest #' + g.id) + plusOne + '</td>' +
            '<td>' + tierName + '</td>' +
            '<td>' + rsvpBadge + '</td>' +
            '<td>' + payBadge + '</td>' +
            '<td>' + checkinHtml + '</td>' +
            '<td>' +
                (g.rsvp_status === 'waitlisted' ? '<button class="ev-btn ev-btn-gold ev-btn-sm" onclick="promoteGuest(' + g.id + ')">Promote</button>' : '') +
            '</td>' +
        '</tr>';
    }
    tbody.innerHTML = html;
}

function rsvpBadgeHtml(status) {
    var map = {
        'attending': 'ev-badge-green', 'waitlisted': 'ev-badge-amber',
        'invited': 'ev-badge-gray', 'declined': 'ev-badge-red',
        'maybe': 'ev-badge-purple', 'viewed': 'ev-badge-gray', 'expired': 'ev-badge-red'
    };
    var cls = map[status] || 'ev-badge-gray';
    return '<span class="ev-badge ' + cls + '">' + escHtml(status || 'unknown') + '</span>';
}

function paymentBadgeHtml(status) {
    var map = { 'paid': 'ev-badge-green', 'partial': 'ev-badge-amber', 'unpaid': 'ev-badge-gray', 'comped': 'ev-badge-purple' };
    var cls = map[status] || 'ev-badge-gray';
    return '<span class="ev-badge ' + cls + '">' + escHtml(status || 'unpaid') + '</span>';
}

function filterRoster() {
    var search = document.getElementById('rosterSearch').value.toLowerCase();
    var filter = document.getElementById('rosterFilter').value;
    var rows = document.querySelectorAll('#rosterBody tr[data-name]');
    for (var i = 0; i < rows.length; i++) {
        var name = (rows[i].getAttribute('data-name') || '').toLowerCase();
        var rsvp = rows[i].getAttribute('data-rsvp') || '';
        var matchSearch = !search || name.indexOf(search) !== -1;
        var matchFilter = filter === 'all' || rsvp === filter;
        rows[i].style.display = (matchSearch && matchFilter) ? '' : 'none';
    }
}

function promoteNext() {
    api('/api/trips/' + TRIP_ID + '/waitlist/promote', {
        method: 'POST', body: JSON.stringify({})
    }).then(function(data) {
        if (data.status === 'ok') { toast('Guest promoted: ' + (data.guest.display_name || 'Guest')); loadRoster(); }
        else toast(data.error || 'No waitlisted guests', true);
    }).catch(function() { toast('Network error', true); });
}

function promoteGuest(guestId) {
    api('/api/trips/' + TRIP_ID + '/waitlist/promote', {
        method: 'POST', body: JSON.stringify({ guest_id: guestId })
    }).then(function(data) {
        if (data.status === 'ok') { toast('Guest promoted'); loadRoster(); }
        else toast(data.error || 'Promote failed', true);
    }).catch(function() { toast('Network error', true); });
}

function checkinGuest(guestId) {
    api('/api/trips/' + TRIP_ID + '/guests/' + guestId + '/checkin', {
        method: 'POST', body: JSON.stringify({})
    }).then(function(data) {
        if (data.status === 'ok') {
            toast('Checked in' + (data.checkin_progress ? ' (' + data.checkin_progress + ')' : ''));
            loadRoster();
        } else {
            toast(data.error || 'Check-in failed', true);
        }
    }).catch(function() { toast('Network error', true); });
}

/* ============================================================
   TAB 4: ANNOUNCEMENTS
   ============================================================ */

function loadAnnouncements() {
    api('/api/trips/' + TRIP_ID + '/announcements').then(function(data) {
        if (data.status === 'ok') {
            renderAnnouncements(data.announcements || []);
        }
    }).catch(function() {});
}

function renderAnnouncements(list) {
    var container = document.getElementById('annFeed');
    if (!list.length) {
        container.innerHTML = '<div class="ev-empty"><div class="ev-empty-icon">&#128227;</div>No announcements yet. Send the first one above.</div>';
        return;
    }
    var html = '';
    for (var i = 0; i < list.length; i++) {
        var a = list[i];
        var timeStr = a.sent_at ? formatTime(a.sent_at) : '';
        var audienceBadge = a.audience !== 'all' ? ' <span class="ev-badge ev-badge-purple">' + escHtml(a.audience.replace('_', ' ')) + '</span>' : '';
        html += '<div class="ev-ann-card">' +
            '<div class="ev-ann-header">' +
                '<span class="ev-ann-sender">' + escHtml(a.sender_name || 'Admin') + audienceBadge + '</span>' +
                '<span class="ev-ann-time">' + escHtml(timeStr) + '</span>' +
            '</div>' +
            '<div class="ev-ann-body">' + escHtml(a.body) + '</div>' +
        '</div>';
    }
    container.innerHTML = html;
}

function sendAnnouncement() {
    var btn = document.getElementById('btnSendAnn');
    var body = document.getElementById('annBody').value.trim();
    if (!body) { toast('Write something first', true); return; }
    btn.disabled = true; btn.textContent = 'Sending...';
    api('/api/trips/' + TRIP_ID + '/announcements', {
        method: 'POST',
        body: JSON.stringify({
            body: body,
            audience: document.getElementById('annAudience').value
        })
    }).then(function(data) {
        btn.disabled = false; btn.textContent = 'Send Announcement';
        if (data.status === 'ok') {
            toast('Announcement sent');
            document.getElementById('annBody').value = '';
            loadAnnouncements();
        } else {
            toast(data.error || 'Send failed', true);
        }
    }).catch(function() { btn.disabled = false; btn.textContent = 'Send Announcement'; toast('Network error', true); });
}

/* ============================================================
   TAB 5: GUEST INFO
   ============================================================ */

var INFO_FIELDS = ['dietary_restrictions', 'emergency_contact', 'passport_number', 'tshirt_size', 'notes'];

function loadGuestInfoSummary() {
    api('/api/trips/' + TRIP_ID + '/guest-info-summary').then(function(data) {
        if (data.status === 'ok') {
            renderGuestInfoSummary(data.summary || []);
        } else {
            document.getElementById('infoTableBody').innerHTML = '<tr><td class="ev-empty">Admin access required to view guest info.</td></tr>';
        }
    }).catch(function() {});
}

function renderGuestInfoSummary(summary) {
    /* Discover all field keys across all guests */
    var allKeys = {};
    for (var i = 0; i < summary.length; i++) {
        var fields = summary[i].fields || {};
        for (var k in fields) {
            if (fields.hasOwnProperty(k)) allKeys[k] = true;
        }
    }
    /* Ensure default keys are in header */
    for (var d = 0; d < INFO_FIELDS.length; d++) { allKeys[INFO_FIELDS[d]] = true; }
    var keys = Object.keys(allKeys).sort();

    /* Render header */
    var thead = '<tr><th>Guest</th>';
    for (var h = 0; h < keys.length; h++) {
        thead += '<th>' + escHtml(keys[h].replace(/_/g, ' ')) + '</th>';
    }
    thead += '</tr>';
    document.getElementById('infoTableHead').innerHTML = thead;

    /* Render rows */
    if (!summary.length) {
        document.getElementById('infoTableBody').innerHTML = '<tr><td colspan="' + (keys.length + 1) + '" class="ev-empty">No guests found.</td></tr>';
        return;
    }
    var html = '';
    for (var r = 0; r < summary.length; r++) {
        var s = summary[r];
        html += '<tr style="cursor:pointer;" onclick="openGuestInfoEditor(' + s.guest_id + ', ' + escAttr(JSON.stringify(s.display_name || '')) + ')">';
        html += '<td style="font-weight:600;color:#f5f5f5;">' + escHtml(s.display_name || 'Guest #' + s.guest_id) + '</td>';
        for (var c = 0; c < keys.length; c++) {
            var val = (s.fields && s.fields[keys[c]]) || '';
            html += '<td>' + (val ? escHtml(val) : '<span style="color:rgba(255,255,255,0.15);">--</span>') + '</td>';
        }
        html += '</tr>';
    }
    document.getElementById('infoTableBody').innerHTML = html;
}

function openGuestInfoEditor(guestId, name) {
    editingGuestId = guestId;
    document.getElementById('editGuestName').textContent = name || 'Guest #' + guestId;
    document.getElementById('guestInfoEditor').style.display = 'block';
    /* Load current values */
    api('/api/trips/' + TRIP_ID + '/guests/' + guestId + '/info').then(function(data) {
        var fields = (data.status === 'ok') ? (data.fields || {}) : {};
        var container = document.getElementById('guestInfoFields');
        var html = '';
        for (var i = 0; i < INFO_FIELDS.length; i++) {
            var key = INFO_FIELDS[i];
            var label = key.replace(/_/g, ' ');
            var val = fields[key] || '';
            html += '<div>' +
                '<label style="font-size:11px;color:rgba(255,255,255,0.35);letter-spacing:1px;text-transform:uppercase;display:block;margin-bottom:6px;">' + escHtml(label) + '</label>' +
                '<input type="text" class="ev-input" data-field="' + escAttr(key) + '" value="' + escAttr(val) + '">' +
            '</div>';
        }
        container.innerHTML = html;
    }).catch(function() {});
}

function saveGuestInfo() {
    if (!editingGuestId) return;
    var btn = document.getElementById('btnSaveInfo');
    btn.disabled = true; btn.textContent = 'Saving...';
    var inputs = document.querySelectorAll('#guestInfoFields input[data-field]');
    var fields = {};
    for (var i = 0; i < inputs.length; i++) {
        fields[inputs[i].getAttribute('data-field')] = inputs[i].value;
    }
    api('/api/trips/' + TRIP_ID + '/guests/' + editingGuestId + '/info', {
        method: 'POST', body: JSON.stringify({ fields: fields })
    }).then(function(data) {
        btn.disabled = false; btn.textContent = 'Save Guest Info';
        if (data.status === 'ok') {
            toast('Guest info saved');
            loadGuestInfoSummary();
        } else {
            toast(data.error || 'Save failed', true);
        }
    }).catch(function() { btn.disabled = false; btn.textContent = 'Save Guest Info'; toast('Network error', true); });
}

/* ---- Utilities ---- */

function escHtml(s) {
    if (!s) return '';
    var d = document.createElement('div');
    d.appendChild(document.createTextNode(s));
    return d.innerHTML;
}

function escAttr(s) {
    return String(s || '').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/'/g,'&#39;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function formatTime(iso) {
    try {
        var d = new Date(iso);
        var now = new Date();
        var diff = now - d;
        if (diff < 60000) return 'just now';
        if (diff < 3600000) return Math.floor(diff / 60000) + 'm ago';
        if (diff < 86400000) return Math.floor(diff / 3600000) + 'h ago';
        return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    } catch(e) { return iso || ''; }
}

/* ---- Init ---- */
document.addEventListener('DOMContentLoaded', function() {
    loadTripConfig();
});
</script>
'''


def register_event_routes(app, csrf, limiter):
    """Register managed mode + event routes (Builds #225-227)."""
    from server import BASE_TEMPLATE

    # ──────────────────────────────────────────────
    # PAGE: /trips/<trip_id>/events — Event Dashboard
    # ──────────────────────────────────────────────

    @app.route('/trips/<int:trip_id>/events')
    @login_required
    def event_dashboard(trip_id):
        """Event management dashboard — 5-tab UI for managed mode / events."""
        trip, err = _check_trip_access(trip_id)
        if err:
            return err
        return render_template_string(
            BASE_TEMPLATE,
            title='Event Dashboard',
            content=render_template_string(
                EVENTS_PAGE_CONTENT,
                trip_id=trip_id,
            ),
            current_user=current_user,
        )

    # ──────────────────────────────────────────────
    # MANAGED MODE (Build #225)
    # ──────────────────────────────────────────────

    @app.route('/api/trips/<int:trip_id>/mode', methods=['PUT'])
    @login_required
    def set_trip_mode(trip_id):
        """Switch trip between collaborative and managed mode."""
        flag_err = _check_flag('managed_mode')
        if flag_err:
            return flag_err

        trip, err = _check_trip_access(trip_id, require_edit=True)
        if err:
            return err

        if not _is_trip_admin(trip, current_user.id):
            return jsonify({'status': 'error', 'error': 'Only owner/admin can change mode'}), 403

        data = request.get_json(silent=True) or {}
        new_mode = data.get('mode', '')
        if new_mode not in ('collaborative', 'managed'):
            return jsonify({'status': 'error', 'error': 'mode must be collaborative or managed'}), 400

        trip.mode = new_mode
        db.session.commit()
        return jsonify({'status': 'ok', 'mode': trip.mode})

    @app.route('/api/trips/<int:trip_id>/roster')
    @login_required
    def trip_roster(trip_id):
        """Roster dashboard — shows all guests with RSVP, payment, ticket status."""
        flag_err = _check_flag('managed_mode')
        if flag_err:
            return flag_err

        trip, err = _check_trip_access(trip_id)
        if err:
            return err

        guests = TripGuest.query.filter_by(trip_id=trip_id).order_by(TripGuest.created_at).all()

        roster = []
        for g in guests:
            entry = g.to_dict()
            entry['ticket_tier_name'] = None
            if g.ticket_tier_id:
                tier = db.session.get(TicketTier, g.ticket_tier_id)
                entry['ticket_tier_name'] = tier.name if tier else None
            entry['checked_in'] = g.checked_in_at is not None
            entry['plus_one_of'] = g.plus_one_of_guest_id
            roster.append(entry)

        confirmed = sum(1 for g in guests if g.rsvp_status == 'attending')
        waitlisted = sum(1 for g in guests if g.rsvp_status == 'waitlisted')
        paid = sum(1 for g in guests if g.payment_status == 'paid')
        checked_in = sum(1 for g in guests if g.checked_in_at is not None)

        return jsonify({
            'status': 'ok',
            'roster': roster,
            'summary': {
                'total': len(guests),
                'confirmed': confirmed,
                'waitlisted': waitlisted,
                'paid': paid,
                'checked_in': checked_in,
                'capacity': trip.capacity,
                'spots_remaining': (trip.capacity - confirmed) if trip.capacity else None,
            },
        })

    @app.route('/api/trips/<int:trip_id>/announcements', methods=['POST'])
    @login_required
    def send_announcement(trip_id):
        """Send announcement to trip guests (managed mode, admin only)."""
        flag_err = _check_flag('managed_mode')
        if flag_err:
            return flag_err

        trip, err = _check_trip_access(trip_id)
        if err:
            return err

        if not _is_trip_admin(trip, current_user.id):
            return jsonify({'status': 'error', 'error': 'Only owner/admin can send announcements'}), 403

        data = request.get_json(silent=True) or {}
        body = (data.get('body') or '').strip()
        if not body:
            return jsonify({'status': 'error', 'error': 'Announcement body required'}), 400

        audience = data.get('audience', 'all')
        if audience not in TripAnnouncement.AUDIENCES:
            audience = 'all'

        announcement = TripAnnouncement(
            trip_id=trip_id,
            sender_user_id=current_user.id,
            body=body,
            audience=audience,
        )
        db.session.add(announcement)
        db.session.commit()

        return jsonify({'status': 'ok', 'announcement': announcement.to_dict()})

    @app.route('/api/trips/<int:trip_id>/announcements')
    @login_required
    def list_announcements(trip_id):
        """List all announcements for a trip."""
        flag_err = _check_flag('managed_mode')
        if flag_err:
            return flag_err

        trip, err = _check_trip_access(trip_id)
        if err:
            return err

        announcements = TripAnnouncement.query.filter_by(
            trip_id=trip_id
        ).order_by(TripAnnouncement.sent_at.desc()).all()

        return jsonify({
            'status': 'ok',
            'announcements': [a.to_dict() for a in announcements],
            'count': len(announcements),
        })

    @app.route('/api/trips/<int:trip_id>/capacity', methods=['PUT'])
    @login_required
    def set_trip_capacity(trip_id):
        """Set capacity, waitlist, and deadline settings."""
        flag_err = _check_flag('managed_mode')
        if flag_err:
            return flag_err

        trip, err = _check_trip_access(trip_id, require_edit=True)
        if err:
            return err

        if not _is_trip_admin(trip, current_user.id):
            return jsonify({'status': 'error', 'error': 'Only owner/admin can set capacity'}), 403

        data = request.get_json(silent=True) or {}

        if 'capacity' in data:
            trip.capacity = data['capacity']  # null = unlimited
        if 'waitlist_enabled' in data:
            trip.waitlist_enabled = bool(data['waitlist_enabled'])
        if 'registration_deadline' in data:
            try:
                trip.registration_deadline = (
                    datetime.fromisoformat(data['registration_deadline'])
                    if data['registration_deadline'] else None
                )
            except (ValueError, TypeError):
                pass
        if 'payment_deadline' in data:
            try:
                trip.payment_deadline = (
                    datetime.fromisoformat(data['payment_deadline'])
                    if data['payment_deadline'] else None
                )
            except (ValueError, TypeError):
                pass

        db.session.commit()
        return jsonify({
            'status': 'ok',
            'capacity': trip.capacity,
            'waitlist_enabled': trip.waitlist_enabled,
            'registration_deadline': trip.registration_deadline.isoformat() if trip.registration_deadline else None,
            'payment_deadline': trip.payment_deadline.isoformat() if trip.payment_deadline else None,
        })

    @app.route('/api/trips/<int:trip_id>/waitlist/promote', methods=['POST'])
    @login_required
    def promote_from_waitlist(trip_id):
        """Promote the next waitlisted guest to attending."""
        flag_err = _check_flag('managed_mode')
        if flag_err:
            return flag_err

        trip, err = _check_trip_access(trip_id, require_edit=True)
        if err:
            return err

        if not _is_trip_admin(trip, current_user.id):
            return jsonify({'status': 'error', 'error': 'Only owner/admin can promote'}), 403

        data = request.get_json(silent=True) or {}
        guest_id = data.get('guest_id')

        if guest_id:
            guest = TripGuest.query.filter_by(
                id=guest_id, trip_id=trip_id, rsvp_status='waitlisted'
            ).first()
        else:
            # Promote oldest waitlisted guest
            guest = TripGuest.query.filter_by(
                trip_id=trip_id, rsvp_status='waitlisted'
            ).order_by(TripGuest.created_at).first()

        if not guest:
            return jsonify({'status': 'error', 'error': 'No waitlisted guests found'}), 404

        # Check capacity
        if trip.capacity:
            confirmed = TripGuest.query.filter_by(
                trip_id=trip_id, rsvp_status='attending'
            ).count()
            if confirmed >= trip.capacity:
                return jsonify({'status': 'error', 'error': 'Trip is at capacity'}), 400

        guest.rsvp_status = 'attending'
        db.session.commit()
        return jsonify({'status': 'ok', 'guest': guest.to_dict()})

    # ──────────────────────────────────────────────
    # EVENT SYSTEM (Build #226)
    # ──────────────────────────────────────────────

    @app.route('/api/trips/<int:trip_id>/event-config', methods=['PUT'])
    @login_required
    def configure_event(trip_id):
        """Configure trip as event (set event fields)."""
        flag_err = _check_flag('event_system')
        if flag_err:
            return flag_err

        trip, err = _check_trip_access(trip_id, require_edit=True)
        if err:
            return err

        if not _is_trip_admin(trip, current_user.id):
            return jsonify({'status': 'error', 'error': 'Only owner/admin can configure events'}), 403

        data = request.get_json(silent=True) or {}

        trip.trip_type = 'event'
        trip.mode = 'managed'  # Events are always managed

        for field in ('event_name', 'venue_name', 'venue_address', 'venue_url',
                      'event_description', 'organizer_stripe_connect_id'):
            if field in data:
                setattr(trip, field, data[field])

        if 'registration_type' in data:
            if data['registration_type'] in ('invite_only', 'public'):
                trip.registration_type = data['registration_type']

        db.session.commit()

        return jsonify({
            'status': 'ok',
            'trip': trip.to_dict(),
        })

    @app.route('/api/trips/<int:trip_id>/tiers', methods=['POST'])
    @login_required
    def create_ticket_tier(trip_id):
        """Create a ticket tier for an event."""
        flag_err = _check_flag('event_system')
        if flag_err:
            return flag_err

        trip, err = _check_trip_access(trip_id, require_edit=True)
        if err:
            return err

        if not _is_trip_admin(trip, current_user.id):
            return jsonify({'status': 'error', 'error': 'Only owner/admin can create tiers'}), 403

        data = request.get_json(silent=True) or {}
        name = (data.get('name') or '').strip()
        if not name:
            return jsonify({'status': 'error', 'error': 'Tier name required'}), 400

        price = data.get('price_usd', 0.0)
        if not isinstance(price, (int, float)) or price < 0:
            return jsonify({'status': 'error', 'error': 'price_usd must be >= 0'}), 400

        tier = TicketTier(
            trip_id=trip_id,
            name=name,
            description=data.get('description'),
            price_usd=price,
            capacity=data.get('capacity'),
            includes_travel=data.get('includes_travel', False),
            includes_accommodation=data.get('includes_accommodation', False),
            included_items_json=json.dumps(data['included_items']) if data.get('included_items') else None,
            position=data.get('position', 0),
        )
        db.session.add(tier)
        db.session.commit()

        return jsonify({'status': 'ok', 'tier': tier.to_dict()})

    @app.route('/api/trips/<int:trip_id>/tiers')
    @login_required
    def list_ticket_tiers(trip_id):
        """List ticket tiers for a trip/event."""
        flag_err = _check_flag('event_system')
        if flag_err:
            return flag_err

        trip, err = _check_trip_access(trip_id)
        if err:
            return err

        tiers = TicketTier.query.filter_by(
            trip_id=trip_id
        ).order_by(TicketTier.position).all()

        return jsonify({
            'status': 'ok',
            'tiers': [t.to_dict() for t in tiers],
            'count': len(tiers),
        })

    @app.route('/api/trips/<int:trip_id>/tiers/<int:tier_id>', methods=['PUT'])
    @login_required
    def update_ticket_tier(trip_id, tier_id):
        """Update a ticket tier."""
        flag_err = _check_flag('event_system')
        if flag_err:
            return flag_err

        trip, err = _check_trip_access(trip_id, require_edit=True)
        if err:
            return err

        if not _is_trip_admin(trip, current_user.id):
            return jsonify({'status': 'error', 'error': 'Only owner/admin can update tiers'}), 403

        tier = TicketTier.query.filter_by(id=tier_id, trip_id=trip_id).first()
        if not tier:
            return jsonify({'status': 'error', 'error': 'Tier not found'}), 404

        data = request.get_json(silent=True) or {}
        for field in ('name', 'description', 'capacity', 'includes_travel',
                      'includes_accommodation', 'position'):
            if field in data:
                setattr(tier, field, data[field])
        if 'price_usd' in data:
            price = data['price_usd']
            if isinstance(price, (int, float)) and price >= 0:
                tier.price_usd = price

        db.session.commit()
        return jsonify({'status': 'ok', 'tier': tier.to_dict()})

    @app.route('/api/trips/<int:trip_id>/tiers/<int:tier_id>', methods=['DELETE'])
    @login_required
    def deactivate_ticket_tier(trip_id, tier_id):
        """Deactivate a ticket tier (soft delete — preserves sold ticket data)."""
        flag_err = _check_flag('event_system')
        if flag_err:
            return flag_err

        trip, err = _check_trip_access(trip_id, require_edit=True)
        if err:
            return err

        if not _is_trip_admin(trip, current_user.id):
            return jsonify({'status': 'error', 'error': 'Only owner/admin can deactivate tiers'}), 403

        tier = TicketTier.query.filter_by(id=tier_id, trip_id=trip_id).first()
        if not tier:
            return jsonify({'status': 'error', 'error': 'Tier not found'}), 404

        tier.is_active = False
        db.session.commit()
        return jsonify({'status': 'ok'})

    @app.route('/api/trips/<int:trip_id>/tiers/<int:tier_id>/purchase', methods=['POST'])
    @login_required
    def purchase_ticket(trip_id, tier_id):
        """Assign a ticket tier to a guest (purchase/register)."""
        flag_err = _check_flag('event_system')
        if flag_err:
            return flag_err

        trip, err = _check_trip_access(trip_id)
        if err:
            return err

        tier = TicketTier.query.filter_by(id=tier_id, trip_id=trip_id, is_active=True).first()
        if not tier:
            return jsonify({'status': 'error', 'error': 'Tier not found or inactive'}), 404

        if tier.is_sold_out:
            # Check waitlist
            if trip.waitlist_enabled:
                guest = TripGuest.query.filter_by(
                    trip_id=trip_id, user_id=current_user.id
                ).first()
                if guest:
                    guest.rsvp_status = 'waitlisted'
                    guest.ticket_tier_id = tier.id
                    db.session.commit()
                    return jsonify({'status': 'ok', 'waitlisted': True, 'guest': guest.to_dict()})
            return jsonify({'status': 'error', 'error': 'Tier is sold out'}), 400

        data = request.get_json(silent=True) or {}
        guest_id = data.get('guest_id')

        if guest_id:
            guest = TripGuest.query.filter_by(id=guest_id, trip_id=trip_id).first()
        else:
            guest = TripGuest.query.filter_by(
                trip_id=trip_id, user_id=current_user.id
            ).first()

        if not guest:
            return jsonify({'status': 'error', 'error': 'Guest not found'}), 404

        guest.ticket_tier_id = tier.id
        guest.rsvp_status = 'attending'
        tier.sold_count = (tier.sold_count or 0) + 1
        db.session.commit()

        return jsonify({
            'status': 'ok',
            'guest': guest.to_dict(),
            'tier': tier.to_dict(),
        })

    # ──────────────────────────────────────────────
    # GUEST INFO COLLECTION (Build #227)
    # ──────────────────────────────────────────────

    @app.route('/api/trips/<int:trip_id>/guests/<int:guest_id>/info', methods=['POST'])
    @login_required
    def submit_guest_info(trip_id, guest_id):
        """Submit or update guest info fields (key-value pairs)."""
        flag_err = _check_flag('guest_info_collection')
        if flag_err:
            return flag_err

        trip, err = _check_trip_access(trip_id)
        if err:
            return err

        guest = TripGuest.query.filter_by(id=guest_id, trip_id=trip_id).first()
        if not guest:
            return jsonify({'status': 'error', 'error': 'Guest not found'}), 404

        # Only the guest themselves or admin can submit info
        is_self = guest.user_id == current_user.id
        is_admin = _is_trip_admin(trip, current_user.id)
        if not is_self and not is_admin:
            return jsonify({'status': 'error', 'error': 'Only the guest or admin can submit info'}), 403

        data = request.get_json(silent=True) or {}
        fields = data.get('fields', {})
        if not fields or not isinstance(fields, dict):
            return jsonify({'status': 'error', 'error': 'fields dict required'}), 400

        saved = []
        for key, value in fields.items():
            key = str(key).strip()[:50]
            if not key:
                continue
            existing = TripGuestInfo.query.filter_by(
                guest_id=guest_id, field_key=key
            ).first()
            if existing:
                existing.field_value = str(value) if value is not None else None
                existing.submitted_at = _utcnow()
                saved.append(existing.to_dict())
            else:
                info = TripGuestInfo(
                    guest_id=guest_id,
                    field_key=key,
                    field_value=str(value) if value is not None else None,
                )
                db.session.add(info)
                saved.append({'guest_id': guest_id, 'field_key': key, 'field_value': str(value) if value is not None else None})

        db.session.commit()
        return jsonify({'status': 'ok', 'fields': saved, 'count': len(saved)})

    @app.route('/api/trips/<int:trip_id>/guests/<int:guest_id>/info')
    @login_required
    def get_guest_info(trip_id, guest_id):
        """Get all info fields for a specific guest."""
        flag_err = _check_flag('guest_info_collection')
        if flag_err:
            return flag_err

        trip, err = _check_trip_access(trip_id)
        if err:
            return err

        guest = TripGuest.query.filter_by(id=guest_id, trip_id=trip_id).first()
        if not guest:
            return jsonify({'status': 'error', 'error': 'Guest not found'}), 404

        infos = TripGuestInfo.query.filter_by(guest_id=guest_id).all()
        return jsonify({
            'status': 'ok',
            'guest_id': guest_id,
            'fields': {i.field_key: i.field_value for i in infos},
            'count': len(infos),
        })

    @app.route('/api/trips/<int:trip_id>/guest-info-summary')
    @login_required
    def guest_info_summary(trip_id):
        """Admin view: all guests' submitted info for the trip."""
        flag_err = _check_flag('guest_info_collection')
        if flag_err:
            return flag_err

        trip, err = _check_trip_access(trip_id)
        if err:
            return err

        if not _is_trip_admin(trip, current_user.id):
            return jsonify({'status': 'error', 'error': 'Admin access required'}), 403

        guests = TripGuest.query.filter_by(trip_id=trip_id).all()
        summary = []
        for g in guests:
            infos = TripGuestInfo.query.filter_by(guest_id=g.id).all()
            summary.append({
                'guest_id': g.id,
                'display_name': g.display_name,
                'fields': {i.field_key: i.field_value for i in infos},
            })

        return jsonify({
            'status': 'ok',
            'summary': summary,
            'guest_count': len(summary),
        })

    @app.route('/api/trips/<int:trip_id>/guests/<int:guest_id>/plus-one', methods=['POST'])
    @login_required
    def add_plus_one(trip_id, guest_id):
        """Add a plus-one linked to an existing guest."""
        flag_err = _check_flag('guest_info_collection')
        if flag_err:
            return flag_err

        trip, err = _check_trip_access(trip_id)
        if err:
            return err

        primary_guest = TripGuest.query.filter_by(id=guest_id, trip_id=trip_id).first()
        if not primary_guest:
            return jsonify({'status': 'error', 'error': 'Guest not found'}), 404

        # Only the guest themselves or admin can add plus-one
        is_self = primary_guest.user_id == current_user.id
        is_admin = _is_trip_admin(trip, current_user.id)
        if not is_self and not is_admin:
            return jsonify({'status': 'error', 'error': 'Only the guest or admin can add plus-ones'}), 403

        data = request.get_json(silent=True) or {}
        display_name = (data.get('display_name') or '').strip()
        if not display_name:
            return jsonify({'status': 'error', 'error': 'display_name required'}), 400

        # Check capacity
        if trip.capacity:
            confirmed = TripGuest.query.filter_by(
                trip_id=trip_id, rsvp_status='attending'
            ).count()
            if confirmed >= trip.capacity:
                return jsonify({'status': 'error', 'error': 'Trip is at capacity'}), 400

        plus_one = TripGuest(
            trip_id=trip_id,
            party_id=primary_guest.party_id,  # Same party as primary
            display_name=display_name,
            email=data.get('email'),
            role='viewer',
            rsvp_status='attending',
            plus_one_of_guest_id=primary_guest.id,
            ticket_tier_id=primary_guest.ticket_tier_id,  # Same tier as primary
        )
        db.session.add(plus_one)
        db.session.commit()

        return jsonify({'status': 'ok', 'guest': plus_one.to_dict()})

    @app.route('/api/trips/<int:trip_id>/guests/<int:guest_id>/checkin', methods=['POST'])
    @login_required
    def qr_checkin(trip_id, guest_id):
        """Mark guest as checked in (QR scan at event)."""
        flag_err = _check_flag('qr_checkin')
        if flag_err:
            return flag_err

        trip, err = _check_trip_access(trip_id)
        if err:
            return err

        if not _is_trip_admin(trip, current_user.id):
            return jsonify({'status': 'error', 'error': 'Only admin can check in guests'}), 403

        guest = TripGuest.query.filter_by(id=guest_id, trip_id=trip_id).first()
        if not guest:
            return jsonify({'status': 'error', 'error': 'Guest not found'}), 404

        if guest.checked_in_at:
            return jsonify({
                'status': 'ok',
                'already_checked_in': True,
                'checked_in_at': guest.checked_in_at.isoformat(),
            })

        guest.checked_in_at = _utcnow()
        db.session.commit()

        # Count check-ins
        total = TripGuest.query.filter_by(trip_id=trip_id, rsvp_status='attending').count()
        checked_in = TripGuest.query.filter(
            TripGuest.trip_id == trip_id,
            TripGuest.checked_in_at.isnot(None),
        ).count()

        return jsonify({
            'status': 'ok',
            'guest': guest.to_dict(),
            'checked_in_at': guest.checked_in_at.isoformat(),
            'checkin_progress': f'{checked_in}/{total}',
        })

    logger.info("Event routes registered (Builds #225-227)")
