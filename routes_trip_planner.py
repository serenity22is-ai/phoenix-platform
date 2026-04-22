"""
Builds #221-224, #238 — Trip Planner Engine Routes

Sub-party model, itinerary items with live search params, scoping/settlement,
collaborative voting/comments/suggestions, and booking lifecycle management.

Endpoints:
  Party Management (#221):
  - POST   /api/trips/<id>/parties             — create a party
  - GET    /api/trips/<id>/parties             — list parties
  - PUT    /api/trips/<id>/parties/<pid>       — update party
  - DELETE /api/trips/<id>/parties/<pid>       — remove party

  Guest Management (#221):
  - POST   /api/trips/<id>/guests              — add guest
  - GET    /api/trips/<id>/guests              — list guests
  - PUT    /api/trips/<id>/guests/<gid>        — update guest
  - DELETE /api/trips/<id>/guests/<gid>        — remove guest
  - POST   /api/trips/<id>/guests/<gid>/rsvp   — update RSVP

  Itinerary Items (#222):
  - POST   /api/trips/<id>/itinerary           — add item
  - GET    /api/trips/<id>/itinerary           — list items (timeline)
  - PUT    /api/trips/<id>/itinerary/<iid>     — update item
  - DELETE /api/trips/<id>/itinerary/<iid>     — remove item
  - POST   /api/trips/<id>/itinerary/<iid>/status — change status

  Scoping + Settlement (#223):
  - GET    /api/trips/<id>/scope-breakdown     — cost breakdown per party
  - GET    /api/trips/<id>/settlement          — who owes what

  Voting + Comments + Suggestions (#224):
  - POST   /api/trips/<id>/itinerary/<iid>/vote       — cast/update vote
  - GET    /api/trips/<id>/itinerary/<iid>/votes       — get votes + tally
  - POST   /api/trips/<id>/itinerary/<iid>/comments    — add comment
  - GET    /api/trips/<id>/itinerary/<iid>/comments    — list comments
  - DELETE /api/trips/<id>/itinerary/<iid>/comments/<cid> — delete comment
  - GET    /api/trips/<id>/suggestions                 — list suggestions
  - POST   /api/trips/<id>/itinerary/<iid>/approve     — approve suggestion

  Booking Lifecycle (#238):
  - POST   /api/trips/<id>/itinerary/<iid>/link-booking — link booking
  - GET    /api/trips/<id>/bookings                     — list trip bookings
  - PUT    /api/bookings/<bid>/lifecycle                 — update lifecycle

Registration: register_trip_planner_routes(app, csrf, limiter)
"""

import json
import logging
from datetime import date, datetime, timezone

from flask import request, jsonify, render_template_string
from flask_login import current_user, login_required

from models import (
    db, TripPlan, TripMember, TripParty, TripGuest,
    ItineraryItem, ItineraryVote, ItemComment,
)

logger = logging.getLogger(__name__)


def _utcnow():
    return datetime.now(timezone.utc)


def _check_trip_access(trip_id, require_edit=False):
    """Verify current user has access to this trip. Returns (trip, error_response)."""
    trip = db.session.get(TripPlan, trip_id)
    if not trip:
        return None, (jsonify({'status': 'error', 'error': 'Trip not found'}), 404)

    # Owner always has access
    if trip.creator_id == current_user.id:
        return trip, None

    # Check membership
    member = TripMember.query.filter_by(
        trip_plan_id=trip_id, user_id=current_user.id
    ).first()
    if not member:
        # Check guest record
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


def _get_vote_tally(item_id):
    """Count up/down/neutral votes for an itinerary item."""
    votes = ItineraryVote.query.filter_by(item_id=item_id).all()
    tally = {'up': 0, 'down': 0, 'neutral': 0, 'total': 0, 'score': 0}
    for v in votes:
        tally['total'] += 1
        if v.vote in tally:
            tally[v.vote] += 1
    tally['score'] = tally['up'] - tally['down']
    return tally


# ============================================================
# Trip Planner Page Template (5-tab interface)
# ============================================================

TRIP_PLANNER_PAGE = '''
<style>
    /* ── Trip Planner Layout ── */
    .tp-page { min-height: calc(100vh - 80px); padding: 32px 20px 80px; max-width: 1100px; margin: 0 auto; }
    .tp-header { margin-bottom: 32px; }
    .tp-header h1 { font-family: 'Space Grotesk', var(--font-brand, sans-serif); font-size: 28px; font-weight: 700; color: #fff; margin: 0 0 6px; letter-spacing: 1px; }
    .tp-header .tp-subtitle { font-size: 14px; color: #ccc; margin: 0; }
    .tp-header .tp-meta { display: flex; gap: 16px; margin-top: 12px; flex-wrap: wrap; }
    .tp-header .tp-meta-item { font-size: 12px; color: #aaa; display: flex; align-items: center; gap: 4px; }
    .tp-header .tp-meta-item span { color: #14b8a6; font-weight: 600; }

    /* ── Tab Navigation ── */
    .tp-tabs { display: flex; gap: 4px; margin-bottom: 28px; border-bottom: 1px solid rgba(255,255,255,0.06); padding-bottom: 0; overflow-x: auto; -webkit-overflow-scrolling: touch; }
    .tp-tab { padding: 12px 20px; font-size: 13px; font-weight: 600; color: #999; cursor: pointer; border-bottom: 2px solid transparent; transition: all 0.2s; white-space: nowrap; letter-spacing: 0.5px; text-transform: uppercase; font-family: 'Space Grotesk', var(--font-brand, sans-serif); background: none; border-top: none; border-left: none; border-right: none; }
    .tp-tab:hover { color: #ddd; }
    .tp-tab.active { color: #14b8a6; border-bottom-color: #14b8a6; }
    .tp-tab-panel { display: none; }
    .tp-tab-panel.active { display: block; }

    /* ── Glass Cards ── */
    .tp-card { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 16px; padding: 24px; margin-bottom: 16px; backdrop-filter: blur(12px); transition: border-color 0.2s; }
    .tp-card:hover { border-color: rgba(255,255,255,0.14); }
    .tp-card-sm { padding: 16px; margin-bottom: 10px; border-radius: 12px; }
    .tp-card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
    .tp-card-title { font-family: 'Space Grotesk', var(--font-brand, sans-serif); font-size: 16px; font-weight: 600; color: #fff; letter-spacing: 1px; text-transform: uppercase; }

    /* ── Buttons ── */
    .tp-btn { display: inline-flex; align-items: center; gap: 6px; padding: 10px 20px; border-radius: 10px; font-size: 13px; font-weight: 600; cursor: pointer; border: none; transition: all 0.2s; font-family: 'Outfit', var(--font-body, sans-serif); }
    .tp-btn:disabled { opacity: 0.5; cursor: not-allowed; }
    .tp-btn-teal { background: #14b8a6; color: #fff; }
    .tp-btn-teal:hover:not(:disabled) { background: #0d9488; transform: translateY(-1px); }
    .tp-btn-gold { background: linear-gradient(135deg, #C9A96E, #b8963f); color: #fff; }
    .tp-btn-gold:hover:not(:disabled) { background: linear-gradient(135deg, #d4b87a, #c4a24e); transform: translateY(-1px); }
    .tp-btn-ghost { background: rgba(255,255,255,0.06); color: #ccc; border: 1px solid rgba(255,255,255,0.1); }
    .tp-btn-ghost:hover:not(:disabled) { background: rgba(255,255,255,0.1); color: #fff; }
    .tp-btn-danger { background: rgba(239,68,68,0.15); color: #ef4444; border: 1px solid rgba(239,68,68,0.2); }
    .tp-btn-danger:hover:not(:disabled) { background: rgba(239,68,68,0.25); }
    .tp-btn-sm { padding: 6px 12px; font-size: 12px; border-radius: 8px; }
    .tp-btn-icon { width: 32px; height: 32px; padding: 0; display: inline-flex; align-items: center; justify-content: center; border-radius: 8px; }

    /* ── Form Elements ── */
    .tp-input, .tp-select { width: 100%; padding: 10px 14px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 10px; color: #fff; font-size: 14px; font-family: 'Outfit', var(--font-body, sans-serif); outline: none; transition: border-color 0.2s; box-sizing: border-box; }
    .tp-input:focus, .tp-select:focus { border-color: #14b8a6; }
    .tp-input::placeholder { color: #666; }
    .tp-select option { background: #1a1a2e; color: #fff; }
    .tp-textarea { width: 100%; padding: 10px 14px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 10px; color: #fff; font-size: 14px; font-family: 'Outfit', var(--font-body, sans-serif); outline: none; resize: vertical; min-height: 60px; transition: border-color 0.2s; box-sizing: border-box; }
    .tp-textarea:focus { border-color: #14b8a6; }
    .tp-form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 16px; }
    .tp-form-grid .full-width { grid-column: 1 / -1; }
    .tp-form-row { display: flex; gap: 12px; margin-bottom: 12px; align-items: flex-end; }
    .tp-form-group { display: flex; flex-direction: column; gap: 4px; flex: 1; }
    .tp-form-label { font-size: 11px; color: #999; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600; }

    /* ── Badges ── */
    .tp-badge { display: inline-flex; align-items: center; padding: 3px 10px; border-radius: 20px; font-size: 11px; font-weight: 600; letter-spacing: 0.3px; }
    .tp-badge-teal { background: rgba(20,184,166,0.15); color: #14b8a6; }
    .tp-badge-gold { background: rgba(201,169,110,0.15); color: #C9A96E; }
    .tp-badge-purple { background: rgba(124,58,237,0.15); color: #a78bfa; }
    .tp-badge-green { background: rgba(34,197,94,0.15); color: #22c55e; }
    .tp-badge-red { background: rgba(239,68,68,0.15); color: #ef4444; }
    .tp-badge-orange { background: rgba(249,115,22,0.15); color: #f97316; }
    .tp-badge-gray { background: rgba(255,255,255,0.06); color: #999; }
    .tp-badge-blue { background: rgba(59,130,246,0.15); color: #60a5fa; }

    /* ── Timeline (Itinerary) ── */
    .tp-timeline { position: relative; padding-left: 32px; }
    .tp-timeline::before { content: ''; position: absolute; left: 11px; top: 0; bottom: 0; width: 2px; background: rgba(255,255,255,0.06); }
    .tp-timeline-item { position: relative; margin-bottom: 16px; }
    .tp-timeline-dot { position: absolute; left: -32px; top: 20px; width: 22px; height: 22px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 11px; z-index: 1; }
    .tp-timeline-dot.flight { background: rgba(59,130,246,0.2); color: #60a5fa; }
    .tp-timeline-dot.hotel { background: rgba(124,58,237,0.2); color: #a78bfa; }
    .tp-timeline-dot.activity { background: rgba(34,197,94,0.2); color: #22c55e; }
    .tp-timeline-dot.transport { background: rgba(249,115,22,0.2); color: #f97316; }
    .tp-timeline-dot.meal { background: rgba(201,169,110,0.2); color: #C9A96E; }
    .tp-timeline-dot.restaurant { background: rgba(201,169,110,0.2); color: #C9A96E; }
    .tp-timeline-dot.car { background: rgba(249,115,22,0.2); color: #f97316; }
    .tp-timeline-dot.custom { background: rgba(255,255,255,0.1); color: #999; }

    .tp-item-card { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 14px; padding: 18px; transition: border-color 0.2s; }
    .tp-item-card:hover { border-color: rgba(255,255,255,0.14); }
    .tp-item-top { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px; }
    .tp-item-title { font-size: 15px; font-weight: 600; color: #fff; }
    .tp-item-time { font-size: 12px; color: #999; margin-bottom: 2px; }
    .tp-item-notes { font-size: 13px; color: #aaa; margin-top: 6px; line-height: 1.5; }
    .tp-item-footer { display: flex; justify-content: space-between; align-items: center; margin-top: 12px; padding-top: 10px; border-top: 1px solid rgba(255,255,255,0.04); }
    .tp-item-badges { display: flex; gap: 6px; flex-wrap: wrap; }
    .tp-item-actions { display: flex; gap: 4px; align-items: center; }

    /* ── Votes ── */
    .tp-vote-group { display: flex; align-items: center; gap: 2px; }
    .tp-vote-btn { width: 28px; height: 28px; border-radius: 6px; border: none; background: rgba(255,255,255,0.04); color: #777; cursor: pointer; display: flex; align-items: center; justify-content: center; font-size: 14px; transition: all 0.2s; }
    .tp-vote-btn:hover { background: rgba(255,255,255,0.08); color: #fff; }
    .tp-vote-btn.voted-up { background: rgba(34,197,94,0.15); color: #22c55e; }
    .tp-vote-btn.voted-down { background: rgba(239,68,68,0.15); color: #ef4444; }
    .tp-vote-count { font-size: 13px; font-weight: 600; color: #ccc; min-width: 24px; text-align: center; }
    .tp-comment-count { font-size: 12px; color: #777; cursor: pointer; display: flex; align-items: center; gap: 3px; }
    .tp-comment-count:hover { color: #14b8a6; }

    /* ── Date Divider ── */
    .tp-date-divider { font-family: 'Space Grotesk', var(--font-brand, sans-serif); font-size: 13px; font-weight: 600; color: #14b8a6; letter-spacing: 1px; text-transform: uppercase; margin-bottom: 12px; margin-top: 20px; padding: 6px 0; }
    .tp-date-divider:first-child { margin-top: 0; }

    /* ── Party & Guest ── */
    .tp-party-card { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 14px; padding: 20px; margin-bottom: 16px; }
    .tp-party-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
    .tp-party-name { font-family: 'Space Grotesk', var(--font-brand, sans-serif); font-size: 16px; font-weight: 600; color: #fff; }
    .tp-party-meta { font-size: 12px; color: #999; display: flex; gap: 12px; }
    .tp-guest-table { width: 100%; border-collapse: collapse; }
    .tp-guest-table th { font-size: 11px; color: #666; text-transform: uppercase; letter-spacing: 0.5px; padding: 8px 12px; text-align: left; border-bottom: 1px solid rgba(255,255,255,0.06); font-weight: 600; }
    .tp-guest-table td { font-size: 13px; color: #ccc; padding: 10px 12px; border-bottom: 1px solid rgba(255,255,255,0.03); }
    .tp-guest-table tr:hover td { background: rgba(255,255,255,0.02); }
    .tp-rsvp-btn { padding: 3px 8px; border-radius: 6px; border: none; font-size: 11px; cursor: pointer; font-weight: 600; transition: all 0.15s; }
    .tp-rsvp-attending { background: rgba(34,197,94,0.15); color: #22c55e; }
    .tp-rsvp-declined { background: rgba(239,68,68,0.15); color: #ef4444; }
    .tp-rsvp-maybe { background: rgba(249,115,22,0.15); color: #f97316; }
    .tp-rsvp-pending { background: rgba(255,255,255,0.06); color: #999; }

    /* ── Voting Tab ── */
    .tp-suggestion-card { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 14px; padding: 20px; margin-bottom: 16px; }
    .tp-vote-bar { height: 6px; border-radius: 3px; background: rgba(255,255,255,0.06); overflow: hidden; margin: 10px 0; display: flex; }
    .tp-vote-bar-up { background: #22c55e; height: 100%; transition: width 0.3s; }
    .tp-vote-bar-down { background: #ef4444; height: 100%; transition: width 0.3s; }
    .tp-vote-summary { display: flex; justify-content: space-between; font-size: 12px; color: #999; }

    /* ── Comments ── */
    .tp-comments-section { margin-top: 12px; padding-top: 12px; border-top: 1px solid rgba(255,255,255,0.04); }
    .tp-comment { padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,0.03); }
    .tp-comment:last-child { border-bottom: none; }
    .tp-comment-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
    .tp-comment-author { font-size: 12px; font-weight: 600; color: #14b8a6; }
    .tp-comment-time { font-size: 11px; color: #666; }
    .tp-comment-body { font-size: 13px; color: #ccc; line-height: 1.5; }
    .tp-comment-form { display: flex; gap: 8px; margin-top: 10px; }
    .tp-comment-form input { flex: 1; }
    .tp-comments-toggle { cursor: pointer; font-size: 12px; color: #14b8a6; margin-top: 6px; }

    /* ── Settlement Tab ── */
    .tp-settlement-summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 28px; }
    .tp-stat-card { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 14px; padding: 20px; text-align: center; }
    .tp-stat-value { font-family: 'Space Grotesk', var(--font-brand, sans-serif); font-size: 28px; font-weight: 700; color: #14b8a6; }
    .tp-stat-label { font-size: 12px; color: #999; text-transform: uppercase; letter-spacing: 0.5px; margin-top: 4px; }
    .tp-budget-bar { height: 8px; border-radius: 4px; background: rgba(255,255,255,0.06); overflow: hidden; margin-top: 8px; }
    .tp-budget-fill { height: 100%; border-radius: 4px; transition: width 0.3s; }
    .tp-settlement-table { width: 100%; border-collapse: collapse; }
    .tp-settlement-table th { font-size: 11px; color: #666; text-transform: uppercase; letter-spacing: 0.5px; padding: 10px 14px; text-align: left; border-bottom: 1px solid rgba(255,255,255,0.06); font-weight: 600; }
    .tp-settlement-table td { font-size: 14px; color: #ccc; padding: 12px 14px; border-bottom: 1px solid rgba(255,255,255,0.03); }

    /* ── Bookings Tab ── */
    .tp-booking-card { display: flex; justify-content: space-between; align-items: center; padding: 16px 20px; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; margin-bottom: 10px; transition: border-color 0.2s; }
    .tp-booking-card:hover { border-color: rgba(255,255,255,0.14); }
    .tp-booking-info { display: flex; flex-direction: column; gap: 4px; }
    .tp-booking-name { font-size: 14px; font-weight: 600; color: #fff; }
    .tp-booking-code { font-size: 12px; color: #14b8a6; font-family: monospace; }
    .tp-booking-date { font-size: 12px; color: #777; }

    /* ── Modal / Inline Form ── */
    .tp-form-panel { display: none; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.1); border-radius: 14px; padding: 24px; margin-bottom: 20px; }
    .tp-form-panel.open { display: block; animation: tp-slide-in 0.25s ease-out; }
    @keyframes tp-slide-in { from { opacity: 0; transform: translateY(-8px); } to { opacity: 1; transform: translateY(0); } }

    /* ── Empty State ── */
    .tp-empty { text-align: center; padding: 60px 20px; color: #666; }
    .tp-empty-icon { font-size: 48px; margin-bottom: 16px; opacity: 0.4; }
    .tp-empty-text { font-size: 15px; color: #999; margin-bottom: 20px; }

    /* ── Loading ── */
    .tp-loading { text-align: center; padding: 40px; color: #666; }
    .tp-spinner { display: inline-block; width: 24px; height: 24px; border: 2px solid rgba(255,255,255,0.1); border-top-color: #14b8a6; border-radius: 50%; animation: tp-spin 0.8s linear infinite; }
    @keyframes tp-spin { to { transform: rotate(360deg); } }

    /* ── Responsive ── */
    @media (max-width: 640px) {
        .tp-page { padding: 20px 14px 60px; }
        .tp-form-grid { grid-template-columns: 1fr; }
        .tp-form-row { flex-direction: column; }
        .tp-tabs { gap: 0; }
        .tp-tab { padding: 10px 14px; font-size: 12px; }
        .tp-item-top { flex-direction: column; gap: 6px; }
        .tp-item-footer { flex-direction: column; gap: 8px; align-items: flex-start; }
        .tp-settlement-summary { grid-template-columns: 1fr; }
        .tp-booking-card { flex-direction: column; gap: 10px; align-items: flex-start; }
    }
</style>

<div class="tp-page">
    <!-- Back navigation -->
    <div style="display:flex; gap:12px; margin-bottom:16px; align-items:center;">
        <a href="/trips/{{ trip.id }}" style="font-size:13px; color:rgba(255,255,255,0.4); text-decoration:none; letter-spacing:0.5px;">&#8592; Back to Trip</a>
        <span style="color:rgba(255,255,255,0.15);">|</span>
        <a href="/trips/{{ trip.id }}/events" style="font-size:13px; color:#a78bfa; text-decoration:none; letter-spacing:0.5px;">&#9734; Events</a>
    </div>
    <!-- Header -->
    <div class="tp-header">
        <h1>{{ trip.name }}</h1>
        <p class="tp-subtitle">{{ trip.description or 'Plan your trip collaboratively' }}</p>
        <div class="tp-meta">
            <div class="tp-meta-item">Status: <span id="tripStatus">{{ trip.status or 'draft' }}</span></div>
            {% if trip.start_date %}
            <div class="tp-meta-item">From: <span>{{ trip.start_date }}</span></div>
            {% endif %}
            {% if trip.end_date %}
            <div class="tp-meta-item">To: <span>{{ trip.end_date }}</span></div>
            {% endif %}
            <div class="tp-meta-item">Total: <span id="tripTotalCost">$0</span></div>
        </div>
    </div>

    <!-- Tab Navigation -->
    <div class="tp-tabs">
        <button class="tp-tab active" data-tab="itinerary">Itinerary</button>
        <button class="tp-tab" data-tab="parties">Parties & Guests</button>
        <button class="tp-tab" data-tab="voting">Voting</button>
        <button class="tp-tab" data-tab="settlement">Settlement</button>
        <button class="tp-tab" data-tab="bookings">Bookings</button>
    </div>

    <!-- ═══════════════════════════════════════════ -->
    <!-- TAB 1: ITINERARY                           -->
    <!-- ═══════════════════════════════════════════ -->
    <div class="tp-tab-panel active" id="panel-itinerary">
        <div class="tp-card-header">
            <div class="tp-card-title">ITINERARY</div>
            <button class="tp-btn tp-btn-teal tp-btn-sm" onclick="toggleAddItem()">+ Add Item</button>
        </div>

        <!-- Add Item Form -->
        <div class="tp-form-panel" id="addItemForm">
            <div class="tp-form-grid">
                <div class="tp-form-group">
                    <label class="tp-form-label">Type</label>
                    <select class="tp-select" id="itemType">
                        <option value="flight">Flight</option>
                        <option value="hotel">Hotel</option>
                        <option value="activity">Activity</option>
                        <option value="car">Car / Transport</option>
                        <option value="restaurant">Restaurant / Meal</option>
                        <option value="custom">Custom</option>
                    </select>
                </div>
                <div class="tp-form-group">
                    <label class="tp-form-label">Date</label>
                    <input type="date" class="tp-input" id="itemDate">
                </div>
                <div class="tp-form-group">
                    <label class="tp-form-label">Start Time</label>
                    <input type="time" class="tp-input" id="itemStartTime">
                </div>
                <div class="tp-form-group">
                    <label class="tp-form-label">End Time</label>
                    <input type="time" class="tp-input" id="itemEndTime">
                </div>
                <div class="tp-form-group full-width">
                    <label class="tp-form-label">Title / Name</label>
                    <input type="text" class="tp-input" id="itemName" placeholder="e.g. Flight LAX to NRT, Hotel Shinjuku...">
                </div>
                <div class="tp-form-group">
                    <label class="tp-form-label">Scope</label>
                    <select class="tp-select" id="itemScope">
                        <option value="trip">Entire Trip</option>
                        <option value="party">Party</option>
                        <option value="individual">Individual</option>
                        <option value="custom">Custom</option>
                    </select>
                </div>
                <div class="tp-form-group">
                    <label class="tp-form-label">Est. Cost (USD)</label>
                    <input type="number" class="tp-input" id="itemCost" placeholder="0.00" step="0.01" min="0">
                </div>
                <div class="tp-form-group full-width">
                    <label class="tp-form-label">Notes</label>
                    <textarea class="tp-textarea" id="itemNotes" placeholder="Optional notes..."></textarea>
                </div>
                <div class="full-width" style="display:flex;gap:8px;justify-content:flex-end;">
                    <button class="tp-btn tp-btn-ghost tp-btn-sm" onclick="toggleAddItem()">Cancel</button>
                    <button class="tp-btn tp-btn-teal tp-btn-sm" onclick="saveItem()" id="saveItemBtn">Add to Itinerary</button>
                </div>
            </div>
        </div>

        <div id="itineraryTimeline" class="tp-loading">
            <div class="tp-spinner"></div>
        </div>
    </div>

    <!-- ═══════════════════════════════════════════ -->
    <!-- TAB 2: PARTIES & GUESTS                    -->
    <!-- ═══════════════════════════════════════════ -->
    <div class="tp-tab-panel" id="panel-parties">
        <div class="tp-card-header">
            <div class="tp-card-title">PARTIES & GUESTS</div>
            <div style="display:flex;gap:8px;">
                <button class="tp-btn tp-btn-teal tp-btn-sm" onclick="toggleAddParty()">+ Add Party</button>
                <button class="tp-btn tp-btn-gold tp-btn-sm" onclick="toggleAddGuest()">+ Add Guest</button>
            </div>
        </div>

        <!-- Add Party Form -->
        <div class="tp-form-panel" id="addPartyForm">
            <div class="tp-form-grid">
                <div class="tp-form-group">
                    <label class="tp-form-label">Party Name</label>
                    <input type="text" class="tp-input" id="partyName" placeholder="e.g. Family, Friends Group A">
                </div>
                <div class="tp-form-group">
                    <label class="tp-form-label">Type</label>
                    <select class="tp-select" id="partyType">
                        <option value="attendee">Attendee</option>
                        <option value="vendor">Vendor</option>
                        <option value="sponsor">Sponsor</option>
                    </select>
                </div>
                <div class="tp-form-group">
                    <label class="tp-form-label">Budget (USD)</label>
                    <input type="number" class="tp-input" id="partyBudget" placeholder="Optional" step="0.01" min="0">
                </div>
                <div class="tp-form-group" style="display:flex;align-items:flex-end;">
                    <div style="display:flex;gap:8px;">
                        <button class="tp-btn tp-btn-ghost tp-btn-sm" onclick="toggleAddParty()">Cancel</button>
                        <button class="tp-btn tp-btn-teal tp-btn-sm" onclick="saveParty()">Create Party</button>
                    </div>
                </div>
            </div>
        </div>

        <!-- Add Guest Form -->
        <div class="tp-form-panel" id="addGuestForm">
            <div class="tp-form-grid">
                <div class="tp-form-group">
                    <label class="tp-form-label">Name</label>
                    <input type="text" class="tp-input" id="guestName" placeholder="Display name">
                </div>
                <div class="tp-form-group">
                    <label class="tp-form-label">Email</label>
                    <input type="email" class="tp-input" id="guestEmail" placeholder="Optional email">
                </div>
                <div class="tp-form-group">
                    <label class="tp-form-label">Party</label>
                    <select class="tp-select" id="guestParty"><option value="">No party</option></select>
                </div>
                <div class="tp-form-group">
                    <label class="tp-form-label">Role</label>
                    <select class="tp-select" id="guestRole">
                        <option value="viewer">Viewer</option>
                        <option value="editor">Editor</option>
                        <option value="admin">Admin</option>
                    </select>
                </div>
                <div class="full-width" style="display:flex;gap:8px;justify-content:flex-end;">
                    <button class="tp-btn tp-btn-ghost tp-btn-sm" onclick="toggleAddGuest()">Cancel</button>
                    <button class="tp-btn tp-btn-gold tp-btn-sm" onclick="saveGuest()">Add Guest</button>
                </div>
            </div>
        </div>

        <div id="partiesContainer" class="tp-loading">
            <div class="tp-spinner"></div>
        </div>
    </div>

    <!-- ═══════════════════════════════════════════ -->
    <!-- TAB 3: VOTING                              -->
    <!-- ═══════════════════════════════════════════ -->
    <div class="tp-tab-panel" id="panel-voting">
        <div class="tp-card-header">
            <div class="tp-card-title">SUGGESTIONS & VOTING</div>
        </div>
        <div id="votingContainer" class="tp-loading">
            <div class="tp-spinner"></div>
        </div>
    </div>

    <!-- ═══════════════════════════════════════════ -->
    <!-- TAB 4: SETTLEMENT                          -->
    <!-- ═══════════════════════════════════════════ -->
    <div class="tp-tab-panel" id="panel-settlement">
        <div class="tp-card-header">
            <div class="tp-card-title">COST SETTLEMENT</div>
        </div>
        <div id="settlementContainer" class="tp-loading">
            <div class="tp-spinner"></div>
        </div>
    </div>

    <!-- ═══════════════════════════════════════════ -->
    <!-- TAB 5: BOOKINGS                            -->
    <!-- ═══════════════════════════════════════════ -->
    <div class="tp-tab-panel" id="panel-bookings">
        <div class="tp-card-header">
            <div class="tp-card-title">LINKED BOOKINGS</div>
        </div>
        <div id="bookingsContainer" class="tp-loading">
            <div class="tp-spinner"></div>
        </div>
    </div>
</div>

<script>
(function() {
    var TRIP_ID = {{ trip.id }};
    var IS_OWNER = {{ 'true' if is_owner else 'false' }};
    var CSRF = document.querySelector('meta[name="csrf-token"]').content;
    var BASE = '/api/trips/' + TRIP_ID;

    // ── State ──
    var state = {
        items: [],
        parties: [],
        guests: [],
        suggestions: [],
        breakdown: [],
        settlements: [],
        bookings: [],
        editingItemId: null
    };

    var TYPE_ICONS = {
        flight: '&#9992;',
        hotel: '&#127968;',
        activity: '&#9978;',
        car: '&#128663;',
        transport: '&#128663;',
        restaurant: '&#127860;',
        meal: '&#127860;',
        custom: '&#9733;'
    };

    var STATUS_BADGES = {
        suggested: 'tp-badge-orange',
        approved: 'tp-badge-teal',
        locked: 'tp-badge-purple',
        booked: 'tp-badge-green',
        cancelled: 'tp-badge-red'
    };

    var SCOPE_BADGES = {
        trip: 'tp-badge-blue',
        party: 'tp-badge-purple',
        individual: 'tp-badge-gold',
        custom: 'tp-badge-gray'
    };

    var RSVP_CLASSES = {
        attending: 'tp-rsvp-attending',
        declined: 'tp-rsvp-declined',
        maybe: 'tp-rsvp-maybe',
        pending: 'tp-rsvp-pending'
    };

    // ── API Helpers ──
    function apiFetch(url, opts) {
        opts = opts || {};
        opts.headers = opts.headers || {};
        opts.headers['Content-Type'] = 'application/json';
        opts.headers['X-CSRFToken'] = CSRF;
        if (!opts.credentials) opts.credentials = 'same-origin';
        return fetch(url, opts).then(function(r) { return r.json(); });
    }

    function apiGet(url) { return apiFetch(url); }
    function apiPost(url, body) { return apiFetch(url, { method: 'POST', body: JSON.stringify(body) }); }
    function apiPut(url, body) { return apiFetch(url, { method: 'PUT', body: JSON.stringify(body) }); }
    function apiDelete(url) { return apiFetch(url, { method: 'DELETE' }); }

    // ── Tab Switching ──
    var tabs = document.querySelectorAll('.tp-tab');
    var panels = document.querySelectorAll('.tp-tab-panel');

    function switchTab(tabName) {
        for (var i = 0; i < tabs.length; i++) {
            tabs[i].classList.toggle('active', tabs[i].getAttribute('data-tab') === tabName);
        }
        for (var j = 0; j < panels.length; j++) {
            panels[j].classList.toggle('active', panels[j].id === 'panel-' + tabName);
        }
        if (tabName === 'itinerary') loadItinerary();
        if (tabName === 'parties') loadParties();
        if (tabName === 'voting') loadVoting();
        if (tabName === 'settlement') loadSettlement();
        if (tabName === 'bookings') loadBookings();
    }

    for (var t = 0; t < tabs.length; t++) {
        tabs[t].addEventListener('click', function() { switchTab(this.getAttribute('data-tab')); });
    }

    // ── Utility ──
    function esc(s) { if (!s) return ''; var d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
    function formatDate(d) { if (!d) return ''; try { var dt = new Date(d + 'T00:00:00'); return dt.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' }); } catch(e) { return d; } }
    function formatTime(t) { if (!t) return ''; var parts = t.split(':'); var h = parseInt(parts[0]); var m = parts[1]; var ampm = h >= 12 ? 'PM' : 'AM'; if (h > 12) h -= 12; if (h === 0) h = 12; return h + ':' + m + ' ' + ampm; }
    function formatCurrency(n) { if (n === null || n === undefined) return '--'; return '$' + parseFloat(n).toFixed(2).replace(/\\d(?=(\\d{3})+\\.)/g, '$&,'); }
    function timeAgo(iso) { if (!iso) return ''; var s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000); if (s < 60) return 'just now'; if (s < 3600) return Math.floor(s/60) + 'm ago'; if (s < 86400) return Math.floor(s/3600) + 'h ago'; return Math.floor(s/86400) + 'd ago'; }

    // ═══════════════════════════════════════
    // TAB 1: ITINERARY
    // ═══════════════════════════════════════

    function loadItinerary() {
        apiGet(BASE + '/itinerary').then(function(data) {
            if (data.status !== 'ok') return;
            state.items = data.items || [];
            var totalEl = document.getElementById('tripTotalCost');
            if (totalEl) totalEl.textContent = formatCurrency(data.total_estimated_usd || 0);
            renderItinerary();
        });
    }

    function renderItinerary() {
        var container = document.getElementById('itineraryTimeline');
        if (!state.items.length) {
            container.innerHTML = '<div class="tp-empty"><div class="tp-empty-icon">&#128506;</div><div class="tp-empty-text">No itinerary items yet. Add your first item to get started.</div></div>';
            return;
        }

        // Group items by date
        var grouped = {};
        var noDate = [];
        state.items.forEach(function(item) {
            if (item.date) {
                if (!grouped[item.date]) grouped[item.date] = [];
                grouped[item.date].push(item);
            } else {
                noDate.push(item);
            }
        });

        var dates = Object.keys(grouped).sort();
        var html = '<div class="tp-timeline">';

        dates.forEach(function(dt) {
            html += '<div class="tp-date-divider">' + formatDate(dt) + '</div>';
            grouped[dt].forEach(function(item) { html += renderItemCard(item); });
        });

        if (noDate.length) {
            html += '<div class="tp-date-divider">Unscheduled</div>';
            noDate.forEach(function(item) { html += renderItemCard(item); });
        }

        html += '</div>';
        container.innerHTML = html;
    }

    function renderItemCard(item) {
        var typeIcon = TYPE_ICONS[item.item_type] || TYPE_ICONS.custom;
        var statusClass = STATUS_BADGES[item.status] || 'tp-badge-gray';
        var scopeClass = SCOPE_BADGES[item.scope] || 'tp-badge-gray';
        var itemName = item.external_name || item.notes || (item.item_type.charAt(0).toUpperCase() + item.item_type.slice(1));
        var timeStr = '';
        if (item.start_time) { timeStr = formatTime(item.start_time); if (item.end_time) timeStr += ' - ' + formatTime(item.end_time); }
        var costStr = (item.cached_price_usd || item.external_cost_usd) ? formatCurrency(item.cached_price_usd || item.external_cost_usd) : '';

        var h = '<div class="tp-timeline-item">';
        h += '<div class="tp-timeline-dot ' + esc(item.item_type) + '">' + typeIcon + '</div>';
        h += '<div class="tp-item-card">';
        h += '<div class="tp-item-top">';
        h += '<div>';
        if (timeStr) h += '<div class="tp-item-time">' + esc(timeStr) + '</div>';
        h += '<div class="tp-item-title">' + esc(itemName) + '</div>';
        h += '</div>';
        if (costStr) h += '<div style="font-size:16px;font-weight:700;color:#14b8a6;">' + costStr + '</div>';
        h += '</div>';

        if (item.notes && item.external_name) {
            h += '<div class="tp-item-notes">' + esc(item.notes) + '</div>';
        }

        h += '<div class="tp-item-footer">';
        h += '<div class="tp-item-badges">';
        h += '<span class="tp-badge ' + statusClass + '">' + esc(item.status) + '</span>';
        h += '<span class="tp-badge ' + scopeClass + '">' + esc(item.scope) + '</span>';
        h += '</div>';
        h += '<div class="tp-item-actions">';
        // Vote buttons
        h += '<div class="tp-vote-group">';
        h += '<button class="tp-vote-btn" onclick="window._tp.voteItem(' + item.id + ',\'up\')" title="Upvote">&#9650;</button>';
        h += '<span class="tp-vote-count" id="vote-count-' + item.id + '">0</span>';
        h += '<button class="tp-vote-btn" onclick="window._tp.voteItem(' + item.id + ',\'down\')" title="Downvote">&#9660;</button>';
        h += '</div>';
        // Comment count
        h += '<span class="tp-comment-count" onclick="window._tp.toggleComments(' + item.id + ')" title="Comments">&#128172; <span id="comment-count-' + item.id + '">0</span></span>';
        // Actions
        h += '<button class="tp-btn tp-btn-ghost tp-btn-sm tp-btn-icon" onclick="window._tp.editItem(' + item.id + ')" title="Edit">&#9998;</button>';
        h += '<button class="tp-btn tp-btn-danger tp-btn-sm tp-btn-icon" onclick="window._tp.deleteItem(' + item.id + ')" title="Delete">&#10005;</button>';
        // Status dropdown
        h += '<select class="tp-select" style="width:auto;padding:4px 8px;font-size:11px;border-radius:6px;" onchange="window._tp.changeStatus(' + item.id + ',this.value)">';
        ['suggested','approved','locked','booked','cancelled'].forEach(function(s) {
            h += '<option value="' + s + '"' + (s === item.status ? ' selected' : '') + '>' + s + '</option>';
        });
        h += '</select>';
        h += '</div>';
        h += '</div>';

        // Inline comments area (hidden by default)
        h += '<div class="tp-comments-section" id="comments-' + item.id + '" style="display:none;"><div class="tp-loading" id="comments-list-' + item.id + '">Loading...</div>';
        h += '<div class="tp-comment-form"><input class="tp-input" id="comment-input-' + item.id + '" placeholder="Write a comment..." style="font-size:12px;padding:6px 10px;"><button class="tp-btn tp-btn-teal tp-btn-sm" onclick="window._tp.addComment(' + item.id + ')">Post</button></div>';
        h += '</div>';

        h += '</div></div>';
        return h;
    }

    // Load vote tallies for visible items
    function loadVoteTallies() {
        state.items.forEach(function(item) {
            apiGet(BASE + '/itinerary/' + item.id + '/votes').then(function(data) {
                if (data.status !== 'ok') return;
                var el = document.getElementById('vote-count-' + item.id);
                if (el) el.textContent = data.tally.score;
            });
            apiGet(BASE + '/itinerary/' + item.id + '/comments').then(function(data) {
                if (data.status !== 'ok') return;
                var el = document.getElementById('comment-count-' + item.id);
                if (el) el.textContent = data.count;
            });
        });
    }

    window._tp = {};

    window._tp.voteItem = function(itemId, vote) {
        apiPost(BASE + '/itinerary/' + itemId + '/vote', { vote: vote }).then(function(data) {
            if (data.status !== 'ok') return;
            var el = document.getElementById('vote-count-' + itemId);
            if (el) el.textContent = data.tally.score;
        });
    };

    window._tp.changeStatus = function(itemId, newStatus) {
        apiPost(BASE + '/itinerary/' + itemId + '/status', { status: newStatus }).then(function(data) {
            if (data.status === 'ok') loadItinerary();
        });
    };

    window._tp.editItem = function(itemId) {
        var item = null;
        state.items.forEach(function(i) { if (i.id === itemId) item = i; });
        if (!item) return;

        state.editingItemId = itemId;
        document.getElementById('itemType').value = item.item_type || 'custom';
        document.getElementById('itemDate').value = item.date || '';
        document.getElementById('itemStartTime').value = item.start_time || '';
        document.getElementById('itemEndTime').value = item.end_time || '';
        document.getElementById('itemName').value = item.external_name || item.notes || '';
        document.getElementById('itemScope').value = item.scope || 'trip';
        document.getElementById('itemCost').value = item.external_cost_usd || item.cached_price_usd || '';
        document.getElementById('itemNotes').value = item.notes || '';
        document.getElementById('saveItemBtn').textContent = 'Update Item';

        var form = document.getElementById('addItemForm');
        form.classList.add('open');
    };

    window._tp.deleteItem = function(itemId) {
        if (!confirm('Remove this item from the itinerary?')) return;
        apiDelete(BASE + '/itinerary/' + itemId).then(function(data) {
            if (data.status === 'ok') loadItinerary();
        });
    };

    window._tp.toggleComments = function(itemId) {
        var section = document.getElementById('comments-' + itemId);
        if (!section) return;
        var isHidden = section.style.display === 'none';
        section.style.display = isHidden ? 'block' : 'none';
        if (isHidden) loadComments(itemId);
    };

    function loadComments(itemId) {
        var listEl = document.getElementById('comments-list-' + itemId);
        apiGet(BASE + '/itinerary/' + itemId + '/comments').then(function(data) {
            if (data.status !== 'ok') return;
            if (!data.comments.length) {
                listEl.innerHTML = '<div style="font-size:12px;color:#666;padding:8px 0;">No comments yet.</div>';
                return;
            }
            var h = '';
            data.comments.forEach(function(c) {
                h += '<div class="tp-comment">';
                h += '<div class="tp-comment-header"><span class="tp-comment-author">Guest #' + c.guest_id + '</span>';
                h += '<span class="tp-comment-time">' + timeAgo(c.created_at) + '</span></div>';
                h += '<div class="tp-comment-body">' + esc(c.body) + '</div>';
                h += '</div>';
            });
            listEl.innerHTML = h;
        });
    }

    window._tp.addComment = function(itemId) {
        var input = document.getElementById('comment-input-' + itemId);
        var body = (input.value || '').trim();
        if (!body) return;
        apiPost(BASE + '/itinerary/' + itemId + '/comments', { body: body }).then(function(data) {
            if (data.status === 'ok') {
                input.value = '';
                loadComments(itemId);
                // Update count
                var el = document.getElementById('comment-count-' + itemId);
                if (el) el.textContent = parseInt(el.textContent || '0') + 1;
            }
        });
    };

    // Toggle / Save item form
    window.toggleAddItem = function() {
        var form = document.getElementById('addItemForm');
        var isOpen = form.classList.contains('open');
        if (isOpen) {
            form.classList.remove('open');
            clearItemForm();
        } else {
            form.classList.add('open');
        }
    };

    function clearItemForm() {
        state.editingItemId = null;
        document.getElementById('itemType').value = 'flight';
        document.getElementById('itemDate').value = '';
        document.getElementById('itemStartTime').value = '';
        document.getElementById('itemEndTime').value = '';
        document.getElementById('itemName').value = '';
        document.getElementById('itemScope').value = 'trip';
        document.getElementById('itemCost').value = '';
        document.getElementById('itemNotes').value = '';
        document.getElementById('saveItemBtn').textContent = 'Add to Itinerary';
    }

    window.saveItem = function() {
        var nameVal = document.getElementById('itemName').value.trim();
        var payload = {
            item_type: document.getElementById('itemType').value,
            date: document.getElementById('itemDate').value || null,
            start_time: document.getElementById('itemStartTime').value || null,
            end_time: document.getElementById('itemEndTime').value || null,
            external_name: nameVal || null,
            scope: document.getElementById('itemScope').value,
            external_cost_usd: parseFloat(document.getElementById('itemCost').value) || null,
            notes: document.getElementById('itemNotes').value.trim() || null
        };

        if (!nameVal && !payload.notes) {
            alert('Please enter a title or notes for this item.');
            return;
        }

        if (state.editingItemId) {
            apiPut(BASE + '/itinerary/' + state.editingItemId, payload).then(function(data) {
                if (data.status === 'ok') {
                    toggleAddItem();
                    loadItinerary();
                } else {
                    alert(data.error || 'Failed to update item');
                }
            });
        } else {
            apiPost(BASE + '/itinerary', payload).then(function(data) {
                if (data.status === 'ok') {
                    toggleAddItem();
                    loadItinerary();
                } else {
                    alert(data.error || 'Failed to add item');
                }
            });
        }
    };

    // ═══════════════════════════════════════
    // TAB 2: PARTIES & GUESTS
    // ═══════════════════════════════════════

    function loadParties() {
        Promise.all([
            apiGet(BASE + '/parties'),
            apiGet(BASE + '/guests')
        ]).then(function(results) {
            if (results[0].status === 'ok') state.parties = results[0].parties || [];
            if (results[1].status === 'ok') state.guests = results[1].guests || [];
            renderParties();
            updateGuestPartyDropdown();
        });
    }

    function updateGuestPartyDropdown() {
        var sel = document.getElementById('guestParty');
        if (!sel) return;
        var html = '<option value="">No party</option>';
        state.parties.forEach(function(p) {
            html += '<option value="' + p.id + '">' + esc(p.name) + '</option>';
        });
        sel.innerHTML = html;
    }

    function renderParties() {
        var container = document.getElementById('partiesContainer');
        if (!state.parties.length && !state.guests.length) {
            container.innerHTML = '<div class="tp-empty"><div class="tp-empty-icon">&#128101;</div><div class="tp-empty-text">No parties or guests yet. Create a party to organize your group.</div></div>';
            return;
        }

        var html = '';

        // Render each party with its guests
        state.parties.forEach(function(party) {
            var partyGuests = state.guests.filter(function(g) { return g.party_id === party.id; });
            html += '<div class="tp-party-card">';
            html += '<div class="tp-party-header">';
            html += '<div>';
            html += '<div class="tp-party-name">' + esc(party.name) + '</div>';
            html += '<div class="tp-party-meta">';
            html += '<span class="tp-badge tp-badge-purple">' + esc(party.party_type) + '</span>';
            if (party.budget_usd) html += '<span>' + formatCurrency(party.budget_usd) + ' budget</span>';
            html += '<span>' + partyGuests.length + ' guest' + (partyGuests.length !== 1 ? 's' : '') + '</span>';
            html += '</div></div>';
            html += '<div style="display:flex;gap:4px;">';
            html += '<button class="tp-btn tp-btn-ghost tp-btn-sm tp-btn-icon" onclick="window._tp.editParty(' + party.id + ')" title="Edit">&#9998;</button>';
            html += '<button class="tp-btn tp-btn-danger tp-btn-sm tp-btn-icon" onclick="window._tp.deleteParty(' + party.id + ')" title="Delete">&#10005;</button>';
            html += '</div></div>';

            if (partyGuests.length) {
                html += '<table class="tp-guest-table"><thead><tr><th>Name</th><th>Email</th><th>Role</th><th>RSVP</th><th></th></tr></thead><tbody>';
                partyGuests.forEach(function(g) {
                    html += renderGuestRow(g);
                });
                html += '</tbody></table>';
            }
            html += '</div>';
        });

        // Unassigned guests
        var unassigned = state.guests.filter(function(g) { return !g.party_id; });
        if (unassigned.length) {
            html += '<div class="tp-party-card">';
            html += '<div class="tp-party-header"><div class="tp-party-name" style="color:#999;">Unassigned Guests</div></div>';
            html += '<table class="tp-guest-table"><thead><tr><th>Name</th><th>Email</th><th>Role</th><th>RSVP</th><th></th></tr></thead><tbody>';
            unassigned.forEach(function(g) { html += renderGuestRow(g); });
            html += '</tbody></table></div>';
        }

        container.innerHTML = html;
    }

    function renderGuestRow(g) {
        var rsvp = g.rsvp_status || 'pending';
        var rsvpClass = RSVP_CLASSES[rsvp] || 'tp-rsvp-pending';
        var h = '<tr>';
        h += '<td style="font-weight:600;color:#fff;">' + esc(g.display_name) + '</td>';
        h += '<td>' + esc(g.email || '--') + '</td>';
        h += '<td><span class="tp-badge tp-badge-gray">' + esc(g.role || 'viewer') + '</span></td>';
        h += '<td>';
        h += '<div style="display:flex;gap:3px;">';
        ['attending','maybe','declined','pending'].forEach(function(status) {
            var cls = (status === rsvp) ? RSVP_CLASSES[status] : 'tp-rsvp-pending';
            h += '<button class="tp-rsvp-btn ' + cls + '" onclick="window._tp.setRSVP(' + g.id + ',\'' + status + '\')" style="' + (status === rsvp ? 'opacity:1;' : 'opacity:0.4;') + '">' + status.charAt(0).toUpperCase() + status.slice(1) + '</button>';
        });
        h += '</div></td>';
        h += '<td><button class="tp-btn tp-btn-danger tp-btn-sm tp-btn-icon" onclick="window._tp.deleteGuest(' + g.id + ')" title="Remove">&#10005;</button></td>';
        h += '</tr>';
        return h;
    }

    // Party form
    window.toggleAddParty = function() {
        var form = document.getElementById('addPartyForm');
        form.classList.toggle('open');
    };

    window.saveParty = function() {
        var name = document.getElementById('partyName').value.trim();
        if (!name) { alert('Party name is required.'); return; }
        apiPost(BASE + '/parties', {
            name: name,
            party_type: document.getElementById('partyType').value,
            budget_usd: parseFloat(document.getElementById('partyBudget').value) || null
        }).then(function(data) {
            if (data.status === 'ok') {
                toggleAddParty();
                document.getElementById('partyName').value = '';
                document.getElementById('partyBudget').value = '';
                loadParties();
            } else { alert(data.error || 'Failed to create party'); }
        });
    };

    window._tp.editParty = function(partyId) {
        var party = null;
        state.parties.forEach(function(p) { if (p.id === partyId) party = p; });
        if (!party) return;
        var newName = prompt('Party name:', party.name);
        if (newName === null) return;
        apiPut(BASE + '/parties/' + partyId, { name: newName.trim() || party.name }).then(function(data) {
            if (data.status === 'ok') loadParties();
        });
    };

    window._tp.deleteParty = function(partyId) {
        if (!confirm('Delete this party? Guests will be unassigned but not removed.')) return;
        apiDelete(BASE + '/parties/' + partyId).then(function(data) {
            if (data.status === 'ok') loadParties();
        });
    };

    // Guest form
    window.toggleAddGuest = function() {
        var form = document.getElementById('addGuestForm');
        form.classList.toggle('open');
    };

    window.saveGuest = function() {
        var name = document.getElementById('guestName').value.trim();
        if (!name) { alert('Guest name is required.'); return; }
        var partyVal = document.getElementById('guestParty').value;
        apiPost(BASE + '/guests', {
            display_name: name,
            email: document.getElementById('guestEmail').value.trim() || null,
            party_id: partyVal ? parseInt(partyVal) : null,
            role: document.getElementById('guestRole').value
        }).then(function(data) {
            if (data.status === 'ok') {
                toggleAddGuest();
                document.getElementById('guestName').value = '';
                document.getElementById('guestEmail').value = '';
                loadParties();
            } else { alert(data.error || 'Failed to add guest'); }
        });
    };

    window._tp.setRSVP = function(guestId, status) {
        apiPost(BASE + '/guests/' + guestId + '/rsvp', { rsvp_status: status }).then(function(data) {
            if (data.status === 'ok') loadParties();
        });
    };

    window._tp.deleteGuest = function(guestId) {
        if (!confirm('Remove this guest?')) return;
        apiDelete(BASE + '/guests/' + guestId).then(function(data) {
            if (data.status === 'ok') loadParties();
        });
    };

    // ═══════════════════════════════════════
    // TAB 3: VOTING
    // ═══════════════════════════════════════

    function loadVoting() {
        apiGet(BASE + '/suggestions').then(function(data) {
            if (data.status !== 'ok') return;
            state.suggestions = data.suggestions || [];
            renderVoting();
        });
    }

    function renderVoting() {
        var container = document.getElementById('votingContainer');
        if (!state.suggestions.length) {
            container.innerHTML = '<div class="tp-empty"><div class="tp-empty-icon">&#128499;</div><div class="tp-empty-text">No pending suggestions. Items with "suggested" status will appear here for voting.</div></div>';
            return;
        }

        var html = '';
        state.suggestions.forEach(function(item) {
            var tally = item.tally || { up: 0, down: 0, score: 0, total: 0 };
            var total = tally.up + tally.down;
            var upPct = total > 0 ? Math.round((tally.up / total) * 100) : 50;
            var downPct = total > 0 ? Math.round((tally.down / total) * 100) : 50;
            var itemName = item.external_name || item.notes || (item.item_type.charAt(0).toUpperCase() + item.item_type.slice(1));
            var typeIcon = TYPE_ICONS[item.item_type] || TYPE_ICONS.custom;

            html += '<div class="tp-suggestion-card">';
            html += '<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px;">';
            html += '<div style="display:flex;gap:10px;align-items:center;">';
            html += '<span style="font-size:20px;">' + typeIcon + '</span>';
            html += '<div>';
            html += '<div style="font-size:15px;font-weight:600;color:#fff;">' + esc(itemName) + '</div>';
            if (item.date) html += '<div style="font-size:12px;color:#999;">' + formatDate(item.date) + '</div>';
            html += '</div></div>';
            // Vote buttons
            html += '<div class="tp-vote-group">';
            html += '<button class="tp-vote-btn" onclick="window._tp.voteSuggestion(' + item.id + ',\'up\')" title="Upvote" style="width:36px;height:36px;font-size:16px;">&#9650;</button>';
            html += '<span class="tp-vote-count" id="suggest-score-' + item.id + '" style="font-size:16px;">' + tally.score + '</span>';
            html += '<button class="tp-vote-btn" onclick="window._tp.voteSuggestion(' + item.id + ',\'down\')" title="Downvote" style="width:36px;height:36px;font-size:16px;">&#9660;</button>';
            html += '</div></div>';

            if (item.notes) html += '<div style="font-size:13px;color:#aaa;margin-bottom:10px;">' + esc(item.notes) + '</div>';

            // Vote bar
            html += '<div class="tp-vote-bar">';
            if (total > 0) {
                html += '<div class="tp-vote-bar-up" style="width:' + upPct + '%;"></div>';
                html += '<div class="tp-vote-bar-down" style="width:' + downPct + '%;"></div>';
            } else {
                html += '<div class="tp-vote-bar-up" style="width:50%;opacity:0.3;"></div>';
                html += '<div class="tp-vote-bar-down" style="width:50%;opacity:0.3;"></div>';
            }
            html += '</div>';
            html += '<div class="tp-vote-summary"><span>' + tally.up + ' upvote' + (tally.up !== 1 ? 's' : '') + '</span><span>' + tally.down + ' downvote' + (tally.down !== 1 ? 's' : '') + '</span></div>';

            // Approve button (owner only)
            if (IS_OWNER) {
                html += '<div style="margin-top:14px;display:flex;gap:8px;">';
                html += '<button class="tp-btn tp-btn-teal tp-btn-sm" onclick="window._tp.approveSuggestion(' + item.id + ')">Approve</button>';
                html += '<button class="tp-btn tp-btn-danger tp-btn-sm" onclick="window._tp.rejectSuggestion(' + item.id + ')">Reject</button>';
                html += '</div>';
            }

            // Comments
            html += '<div style="margin-top:12px;">';
            html += '<div class="tp-comments-toggle" onclick="window._tp.toggleVoteComments(' + item.id + ')">&#128172; View / Add Comments</div>';
            html += '<div id="vote-comments-' + item.id + '" style="display:none;">';
            html += '<div id="vote-comments-list-' + item.id + '">Loading...</div>';
            html += '<div class="tp-comment-form"><input class="tp-input" id="vote-comment-input-' + item.id + '" placeholder="Add a comment..." style="font-size:12px;padding:6px 10px;"><button class="tp-btn tp-btn-teal tp-btn-sm" onclick="window._tp.addVoteComment(' + item.id + ')">Post</button></div>';
            html += '</div></div>';

            html += '</div>';
        });

        container.innerHTML = html;
    }

    window._tp.voteSuggestion = function(itemId, vote) {
        apiPost(BASE + '/itinerary/' + itemId + '/vote', { vote: vote }).then(function(data) {
            if (data.status === 'ok') {
                var el = document.getElementById('suggest-score-' + itemId);
                if (el) el.textContent = data.tally.score;
                loadVoting(); // Refresh to update bars
            }
        });
    };

    window._tp.approveSuggestion = function(itemId) {
        apiPost(BASE + '/itinerary/' + itemId + '/approve', {}).then(function(data) {
            if (data.status === 'ok') loadVoting();
            else alert(data.error || 'Failed to approve');
        });
    };

    window._tp.rejectSuggestion = function(itemId) {
        apiPost(BASE + '/itinerary/' + itemId + '/status', { status: 'cancelled' }).then(function(data) {
            if (data.status === 'ok') loadVoting();
        });
    };

    window._tp.toggleVoteComments = function(itemId) {
        var section = document.getElementById('vote-comments-' + itemId);
        if (!section) return;
        var isHidden = section.style.display === 'none';
        section.style.display = isHidden ? 'block' : 'none';
        if (isHidden) {
            apiGet(BASE + '/itinerary/' + itemId + '/comments').then(function(data) {
                var listEl = document.getElementById('vote-comments-list-' + itemId);
                if (data.status !== 'ok' || !data.comments.length) {
                    listEl.innerHTML = '<div style="font-size:12px;color:#666;padding:8px 0;">No comments yet.</div>';
                    return;
                }
                var h = '';
                data.comments.forEach(function(c) {
                    h += '<div class="tp-comment"><div class="tp-comment-header"><span class="tp-comment-author">Guest #' + c.guest_id + '</span><span class="tp-comment-time">' + timeAgo(c.created_at) + '</span></div>';
                    h += '<div class="tp-comment-body">' + esc(c.body) + '</div></div>';
                });
                listEl.innerHTML = h;
            });
        }
    };

    window._tp.addVoteComment = function(itemId) {
        var input = document.getElementById('vote-comment-input-' + itemId);
        var body = (input.value || '').trim();
        if (!body) return;
        apiPost(BASE + '/itinerary/' + itemId + '/comments', { body: body }).then(function(data) {
            if (data.status === 'ok') { input.value = ''; window._tp.toggleVoteComments(itemId); window._tp.toggleVoteComments(itemId); }
        });
    };

    // ═══════════════════════════════════════
    // TAB 4: SETTLEMENT
    // ═══════════════════════════════════════

    function loadSettlement() {
        Promise.all([
            apiGet(BASE + '/scope-breakdown'),
            apiGet(BASE + '/settlement')
        ]).then(function(results) {
            var bd = results[0];
            var st = results[1];
            if (bd.status === 'ok') state.breakdown = bd.breakdown || [];
            if (st.status === 'ok') state.settlements = st.settlements || [];
            renderSettlement(bd, st);
        });
    }

    function renderSettlement(bdData, stData) {
        var container = document.getElementById('settlementContainer');
        var totalCost = (stData.status === 'ok' ? stData.total_trip_cost : 0) || 0;
        var partyCount = (bdData.status === 'ok' ? bdData.party_count : 0) || 0;
        var unassigned = (bdData.status === 'ok' ? bdData.unassigned_cost : 0) || 0;

        if (!totalCost && !state.breakdown.length && !state.settlements.length) {
            container.innerHTML = '<div class="tp-empty"><div class="tp-empty-icon">&#128176;</div><div class="tp-empty-text">No costs to settle yet. Add itinerary items with costs to see the breakdown.</div></div>';
            return;
        }

        var html = '';

        // Summary stats
        html += '<div class="tp-settlement-summary">';
        html += '<div class="tp-stat-card"><div class="tp-stat-value">' + formatCurrency(totalCost) + '</div><div class="tp-stat-label">Total Trip Cost</div></div>';
        html += '<div class="tp-stat-card"><div class="tp-stat-value">' + partyCount + '</div><div class="tp-stat-label">Parties</div></div>';
        if (unassigned > 0) html += '<div class="tp-stat-card"><div class="tp-stat-value" style="color:#f97316;">' + formatCurrency(unassigned) + '</div><div class="tp-stat-label">Unassigned Costs</div></div>';
        html += '</div>';

        // Per-party breakdown
        if (state.breakdown.length) {
            html += '<div class="tp-card" style="margin-bottom:24px;">';
            html += '<div class="tp-card-title" style="margin-bottom:16px;">PARTY BREAKDOWN</div>';
            state.breakdown.forEach(function(b) {
                var budgetPct = b.budget_usd ? Math.min(100, Math.round((b.total_cost / b.budget_usd) * 100)) : 0;
                var barColor = b.over_budget ? '#ef4444' : '#14b8a6';
                html += '<div style="padding:14px 0;border-bottom:1px solid rgba(255,255,255,0.04);">';
                html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">';
                html += '<div style="font-weight:600;color:#fff;">' + esc(b.party_name) + '</div>';
                html += '<div style="font-weight:700;color:#14b8a6;">' + formatCurrency(b.total_cost) + '</div>';
                html += '</div>';
                if (b.budget_usd) {
                    html += '<div style="display:flex;justify-content:space-between;font-size:12px;color:#999;margin-bottom:4px;">';
                    html += '<span>Budget: ' + formatCurrency(b.budget_usd) + '</span>';
                    html += '<span' + (b.over_budget ? ' style="color:#ef4444;font-weight:600;"' : '') + '>' + budgetPct + '% used</span>';
                    html += '</div>';
                    html += '<div class="tp-budget-bar"><div class="tp-budget-fill" style="width:' + budgetPct + '%;background:' + barColor + ';"></div></div>';
                }
                html += '</div>';
            });
            html += '</div>';
        }

        // Settlement table
        if (state.settlements.length) {
            html += '<div class="tp-card">';
            html += '<div class="tp-card-title" style="margin-bottom:16px;">SETTLEMENT</div>';
            html += '<table class="tp-settlement-table"><thead><tr><th>Party</th><th>Payer</th><th>Amount Owed</th><th>Status</th></tr></thead><tbody>';
            state.settlements.forEach(function(s) {
                var statusBadge = s.payment_status === 'paid' ? 'tp-badge-green' : 'tp-badge-orange';
                html += '<tr>';
                html += '<td style="font-weight:600;color:#fff;">' + esc(s.party_name) + '</td>';
                html += '<td>' + esc(s.payer_name) + '</td>';
                html += '<td style="font-weight:700;color:#14b8a6;">' + formatCurrency(s.total_owed) + '</td>';
                html += '<td><span class="tp-badge ' + statusBadge + '">' + esc(s.payment_status || 'unpaid') + '</span></td>';
                html += '</tr>';
            });
            html += '</tbody></table></div>';
        }

        container.innerHTML = html;
    }

    // ═══════════════════════════════════════
    // TAB 5: BOOKINGS
    // ═══════════════════════════════════════

    function loadBookings() {
        apiGet(BASE + '/bookings').then(function(data) {
            if (data.status !== 'ok') return;
            state.bookings = data.bookings || [];
            renderBookings();
        });
    }

    function renderBookings() {
        var container = document.getElementById('bookingsContainer');
        if (!state.bookings.length) {
            container.innerHTML = '<div class="tp-empty"><div class="tp-empty-icon">&#128203;</div><div class="tp-empty-text">No bookings linked yet. Book itinerary items through MYSTES to track them here.</div></div>';
            return;
        }

        var LIFECYCLE_BADGES = {
            active: 'tp-badge-green',
            schedule_changed: 'tp-badge-orange',
            cancelled: 'tp-badge-red',
            completed: 'tp-badge-teal'
        };

        var html = '';
        state.bookings.forEach(function(b) {
            var lifecycleClass = LIFECYCLE_BADGES[b.lifecycle_status] || 'tp-badge-gray';
            html += '<div class="tp-booking-card">';
            html += '<div class="tp-booking-info">';
            html += '<div class="tp-booking-name">' + esc(b.item_type ? b.item_type.charAt(0).toUpperCase() + b.item_type.slice(1) : 'Booking') + ' (Item #' + b.item_id + ')</div>';
            if (b.confirmation_code) html += '<div class="tp-booking-code">' + esc(b.confirmation_code) + '</div>';
            if (b.airline_confirmation) html += '<div class="tp-booking-code">Airline: ' + esc(b.airline_confirmation) + '</div>';
            if (b.booked_at) html += '<div class="tp-booking-date">Booked: ' + timeAgo(b.booked_at) + '</div>';
            html += '</div>';
            html += '<div style="display:flex;gap:8px;align-items:center;">';
            html += '<span class="tp-badge ' + lifecycleClass + '">' + esc(b.lifecycle_status || b.status || 'active') + '</span>';
            html += '</div>';
            html += '</div>';
        });

        container.innerHTML = html;
    }

    // ═══════════════════════════════════════
    // INITIAL LOAD
    // ═══════════════════════════════════════
    loadItinerary();
    setTimeout(function() { loadVoteTallies(); }, 300);
})();
</script>
'''


def register_trip_planner_routes(app, csrf, limiter):
    """Register trip planner routes (Builds #221-224, #238)."""

    # ──────────────────────────────────────────────
    # PARTY MANAGEMENT (Build #221)
    # ──────────────────────────────────────────────

    @app.route('/api/trips/<int:trip_id>/parties', methods=['POST'])
    @login_required
    def create_party(trip_id):
        trip, err = _check_trip_access(trip_id, require_edit=True)
        if err:
            return err

        data = request.get_json(silent=True) or {}
        name = (data.get('name') or '').strip()
        if not name:
            return jsonify({'status': 'error', 'error': 'Party name required'}), 400

        party = TripParty(
            trip_id=trip_id,
            name=name,
            party_type=data.get('party_type', 'attendee'),
            budget_usd=data.get('budget_usd'),
        )
        db.session.add(party)
        db.session.commit()

        return jsonify({'status': 'ok', 'party': party.to_dict()})

    @app.route('/api/trips/<int:trip_id>/parties')
    @login_required
    def list_parties(trip_id):
        trip, err = _check_trip_access(trip_id)
        if err:
            return err

        parties = TripParty.query.filter_by(trip_id=trip_id).order_by(TripParty.created_at).all()
        return jsonify({
            'status': 'ok',
            'parties': [p.to_dict() for p in parties],
            'count': len(parties),
        })

    @app.route('/api/trips/<int:trip_id>/parties/<int:party_id>', methods=['PUT'])
    @login_required
    def update_party(trip_id, party_id):
        trip, err = _check_trip_access(trip_id, require_edit=True)
        if err:
            return err

        party = TripParty.query.filter_by(id=party_id, trip_id=trip_id).first()
        if not party:
            return jsonify({'status': 'error', 'error': 'Party not found'}), 404

        data = request.get_json(silent=True) or {}
        if 'name' in data:
            party.name = (data['name'] or '').strip() or party.name
        if 'party_type' in data:
            party.party_type = data['party_type']
        if 'budget_usd' in data:
            party.budget_usd = data['budget_usd']
        if 'payer_guest_id' in data:
            party.payer_guest_id = data['payer_guest_id']

        db.session.commit()
        return jsonify({'status': 'ok', 'party': party.to_dict()})

    @app.route('/api/trips/<int:trip_id>/parties/<int:party_id>', methods=['DELETE'])
    @login_required
    def delete_party(trip_id, party_id):
        trip, err = _check_trip_access(trip_id, require_edit=True)
        if err:
            return err

        party = TripParty.query.filter_by(id=party_id, trip_id=trip_id).first()
        if not party:
            return jsonify({'status': 'error', 'error': 'Party not found'}), 404

        # Unlink guests from this party (don't delete them)
        TripGuest.query.filter_by(party_id=party_id).update({'party_id': None})
        db.session.delete(party)
        db.session.commit()
        return jsonify({'status': 'ok'})

    # ──────────────────────────────────────────────
    # GUEST MANAGEMENT (Build #221)
    # ──────────────────────────────────────────────

    @app.route('/api/trips/<int:trip_id>/guests', methods=['POST'])
    @login_required
    def add_guest(trip_id):
        trip, err = _check_trip_access(trip_id, require_edit=True)
        if err:
            return err

        data = request.get_json(silent=True) or {}
        display_name = (data.get('display_name') or '').strip()
        if not display_name:
            return jsonify({'status': 'error', 'error': 'display_name required'}), 400

        guest = TripGuest(
            trip_id=trip_id,
            party_id=data.get('party_id'),
            user_id=data.get('user_id'),
            display_name=display_name,
            email=data.get('email'),
            phone=data.get('phone'),
            role=data.get('role', 'viewer'),
            arrival_date=_parse_date(data.get('arrival_date')),
            departure_date=_parse_date(data.get('departure_date')),
            nationality=data.get('nationality'),
        )
        db.session.add(guest)
        db.session.commit()

        return jsonify({'status': 'ok', 'guest': guest.to_dict()})

    @app.route('/api/trips/<int:trip_id>/guests')
    @login_required
    def list_guests(trip_id):
        trip, err = _check_trip_access(trip_id)
        if err:
            return err

        guests = TripGuest.query.filter_by(trip_id=trip_id).order_by(TripGuest.created_at).all()
        return jsonify({
            'status': 'ok',
            'guests': [g.to_dict() for g in guests],
            'count': len(guests),
        })

    @app.route('/api/trips/<int:trip_id>/guests/<int:guest_id>', methods=['PUT'])
    @login_required
    def update_guest(trip_id, guest_id):
        trip, err = _check_trip_access(trip_id, require_edit=True)
        if err:
            return err

        guest = TripGuest.query.filter_by(id=guest_id, trip_id=trip_id).first()
        if not guest:
            return jsonify({'status': 'error', 'error': 'Guest not found'}), 404

        data = request.get_json(silent=True) or {}
        for field in ('display_name', 'email', 'phone', 'role', 'nationality'):
            if field in data:
                setattr(guest, field, data[field])
        if 'party_id' in data:
            guest.party_id = data['party_id']
        if 'arrival_date' in data:
            guest.arrival_date = _parse_date(data['arrival_date'])
        if 'departure_date' in data:
            guest.departure_date = _parse_date(data['departure_date'])

        db.session.commit()
        return jsonify({'status': 'ok', 'guest': guest.to_dict()})

    @app.route('/api/trips/<int:trip_id>/guests/<int:guest_id>', methods=['DELETE'])
    @login_required
    def delete_guest(trip_id, guest_id):
        trip, err = _check_trip_access(trip_id, require_edit=True)
        if err:
            return err

        guest = TripGuest.query.filter_by(id=guest_id, trip_id=trip_id).first()
        if not guest:
            return jsonify({'status': 'error', 'error': 'Guest not found'}), 404

        db.session.delete(guest)
        db.session.commit()
        return jsonify({'status': 'ok'})

    @app.route('/api/trips/<int:trip_id>/guests/<int:guest_id>/rsvp', methods=['POST'])
    @login_required
    def update_guest_rsvp(trip_id, guest_id):
        trip, err = _check_trip_access(trip_id)
        if err:
            return err

        guest = TripGuest.query.filter_by(id=guest_id, trip_id=trip_id).first()
        if not guest:
            return jsonify({'status': 'error', 'error': 'Guest not found'}), 404

        # Only the guest themselves or trip admins can update RSVP
        is_self = guest.user_id == current_user.id
        is_admin = trip.creator_id == current_user.id
        if not is_self and not is_admin:
            return jsonify({'status': 'error', 'error': 'Only the guest or admin can RSVP'}), 403

        data = request.get_json(silent=True) or {}
        new_status = data.get('rsvp_status', '')
        if new_status not in TripGuest.RSVP_STATUSES:
            return jsonify({'status': 'error', 'error': f'Invalid RSVP status. Valid: {", ".join(TripGuest.RSVP_STATUSES)}'}), 400

        guest.rsvp_status = new_status
        db.session.commit()
        return jsonify({'status': 'ok', 'guest': guest.to_dict()})

    # ──────────────────────────────────────────────
    # ITINERARY ITEMS (Build #222)
    # ──────────────────────────────────────────────

    @app.route('/api/trips/<int:trip_id>/itinerary', methods=['POST'])
    @login_required
    def add_itinerary_item(trip_id):
        trip, err = _check_trip_access(trip_id, require_edit=True)
        if err:
            return err

        data = request.get_json(silent=True) or {}
        item_type = data.get('item_type', '')
        if item_type not in ItineraryItem.ITEM_TYPES:
            return jsonify({'status': 'error', 'error': f'Invalid item_type. Valid: {", ".join(ItineraryItem.ITEM_TYPES)}'}), 400

        # Find the suggesting guest
        suggesting_guest = TripGuest.query.filter_by(
            trip_id=trip_id, user_id=current_user.id
        ).first()

        item = ItineraryItem(
            trip_id=trip_id,
            item_type=item_type,
            position=data.get('position', 0),
            date=_parse_date(data.get('date')),
            start_time=data.get('start_time'),
            end_time=data.get('end_time'),
            scope=data.get('scope', 'trip'),
            scope_party_id=data.get('scope_party_id'),
            scope_guest_ids_json=json.dumps(data['scope_guest_ids']) if data.get('scope_guest_ids') else None,
            search_params_json=json.dumps(data['search_params']) if data.get('search_params') else None,
            status=data.get('status', 'suggested'),
            booking_source=data.get('booking_source', 'mystes'),
            external_name=data.get('external_name'),
            external_url=data.get('external_url'),
            external_confirmation=data.get('external_confirmation'),
            external_cost_usd=data.get('external_cost_usd'),
            suggested_by_guest_id=suggesting_guest.id if suggesting_guest else None,
            assigned_to_guest_id=data.get('assigned_to_guest_id'),
            notes=data.get('notes'),
            is_private=data.get('is_private', False),
        )
        db.session.add(item)
        db.session.commit()

        return jsonify({'status': 'ok', 'item': item.to_dict()})

    @app.route('/api/trips/<int:trip_id>/itinerary')
    @login_required
    def list_itinerary(trip_id):
        trip, err = _check_trip_access(trip_id)
        if err:
            return err

        items = ItineraryItem.query.filter_by(trip_id=trip_id).order_by(
            ItineraryItem.date, ItineraryItem.position
        ).all()

        return jsonify({
            'status': 'ok',
            'items': [i.to_dict() for i in items],
            'count': len(items),
            'booked_count': sum(1 for i in items if i.status == 'booked'),
            'total_estimated_usd': sum(
                (i.cached_price_usd or i.external_cost_usd or 0) for i in items
            ),
        })

    @app.route('/api/trips/<int:trip_id>/itinerary/<int:item_id>', methods=['PUT'])
    @login_required
    def update_itinerary_item(trip_id, item_id):
        trip, err = _check_trip_access(trip_id, require_edit=True)
        if err:
            return err

        item = ItineraryItem.query.filter_by(id=item_id, trip_id=trip_id).first()
        if not item:
            return jsonify({'status': 'error', 'error': 'Item not found'}), 404

        data = request.get_json(silent=True) or {}

        for field in ('item_type', 'position', 'start_time', 'end_time', 'scope',
                      'scope_party_id', 'booking_source', 'external_name',
                      'external_url', 'external_confirmation', 'notes', 'is_private',
                      'assigned_to_guest_id', 'cached_price_usd'):
            if field in data:
                setattr(item, field, data[field])

        if 'date' in data:
            item.date = _parse_date(data['date'])
        if 'search_params' in data:
            item.search_params_json = json.dumps(data['search_params']) if data['search_params'] else None
        if 'scope_guest_ids' in data:
            item.scope_guest_ids_json = json.dumps(data['scope_guest_ids']) if data['scope_guest_ids'] else None
        if 'external_cost_usd' in data:
            item.external_cost_usd = data['external_cost_usd']

        db.session.commit()
        return jsonify({'status': 'ok', 'item': item.to_dict()})

    @app.route('/api/trips/<int:trip_id>/itinerary/<int:item_id>', methods=['DELETE'])
    @login_required
    def delete_itinerary_item(trip_id, item_id):
        trip, err = _check_trip_access(trip_id, require_edit=True)
        if err:
            return err

        item = ItineraryItem.query.filter_by(id=item_id, trip_id=trip_id).first()
        if not item:
            return jsonify({'status': 'error', 'error': 'Item not found'}), 404

        db.session.delete(item)
        db.session.commit()
        return jsonify({'status': 'ok'})

    @app.route('/api/trips/<int:trip_id>/itinerary/<int:item_id>/status', methods=['POST'])
    @login_required
    def update_itinerary_status(trip_id, item_id):
        trip, err = _check_trip_access(trip_id, require_edit=True)
        if err:
            return err

        item = ItineraryItem.query.filter_by(id=item_id, trip_id=trip_id).first()
        if not item:
            return jsonify({'status': 'error', 'error': 'Item not found'}), 404

        data = request.get_json(silent=True) or {}
        new_status = data.get('status', '')
        if new_status not in ItineraryItem.STATUSES:
            return jsonify({'status': 'error', 'error': f'Invalid status. Valid: {", ".join(ItineraryItem.STATUSES)}'}), 400

        item.status = new_status
        db.session.commit()
        return jsonify({'status': 'ok', 'item': item.to_dict()})

    # ──────────────────────────────────────────────
    # SCOPING + SETTLEMENT (Build #223)
    # ──────────────────────────────────────────────

    @app.route('/api/trips/<int:trip_id>/scope-breakdown')
    @login_required
    def scope_breakdown(trip_id):
        """Cost breakdown per party based on item scopes."""
        trip, err = _check_trip_access(trip_id)
        if err:
            return err

        items = ItineraryItem.query.filter_by(trip_id=trip_id).all()
        parties = TripParty.query.filter_by(trip_id=trip_id).all()
        guests = TripGuest.query.filter_by(trip_id=trip_id).all()

        party_map = {p.id: p for p in parties}
        guest_party_map = {g.id: g.party_id for g in guests}
        party_costs = {p.id: 0.0 for p in parties}
        unassigned_cost = 0.0

        for item in items:
            cost = item.cached_price_usd or item.external_cost_usd or 0
            if cost <= 0:
                continue

            if item.scope == 'party' and item.scope_party_id:
                # Entire cost goes to one party
                if item.scope_party_id in party_costs:
                    party_costs[item.scope_party_id] += cost
                else:
                    unassigned_cost += cost

            elif item.scope == 'individual' and item.assigned_to_guest_id:
                # Cost to the guest's party
                pid = guest_party_map.get(item.assigned_to_guest_id)
                if pid and pid in party_costs:
                    party_costs[pid] += cost
                else:
                    unassigned_cost += cost

            elif item.scope == 'custom' and item.scope_guest_ids_json:
                # Split across involved guests' parties
                guest_ids = json.loads(item.scope_guest_ids_json)
                involved_parties = set()
                for gid in guest_ids:
                    pid = guest_party_map.get(gid)
                    if pid:
                        involved_parties.add(pid)
                if involved_parties:
                    per_party = cost / len(involved_parties)
                    for pid in involved_parties:
                        party_costs[pid] += per_party
                else:
                    unassigned_cost += cost

            elif item.scope == 'trip':
                # Split equally across all parties
                if parties:
                    per_party = cost / len(parties)
                    for pid in party_costs:
                        party_costs[pid] += per_party
                else:
                    unassigned_cost += cost
            else:
                unassigned_cost += cost

        breakdown = []
        for p in parties:
            breakdown.append({
                'party_id': p.id,
                'party_name': p.name,
                'payer_guest_id': p.payer_guest_id,
                'total_cost': round(party_costs.get(p.id, 0), 2),
                'budget_usd': p.budget_usd,
                'over_budget': (
                    party_costs.get(p.id, 0) > p.budget_usd
                    if p.budget_usd else False
                ),
            })

        return jsonify({
            'status': 'ok',
            'breakdown': breakdown,
            'unassigned_cost': round(unassigned_cost, 2),
            'total_cost': round(sum(party_costs.values()) + unassigned_cost, 2),
            'party_count': len(parties),
        })

    @app.route('/api/trips/<int:trip_id>/settlement')
    @login_required
    def settlement(trip_id):
        """Calculate who owes what based on scope breakdown + payment status."""
        trip, err = _check_trip_access(trip_id)
        if err:
            return err

        items = ItineraryItem.query.filter_by(trip_id=trip_id).all()
        parties = TripParty.query.filter_by(trip_id=trip_id).all()
        guests = TripGuest.query.filter_by(trip_id=trip_id).all()

        guest_map = {g.id: g for g in guests}
        guest_party_map = {g.id: g.party_id for g in guests}
        party_costs = {p.id: 0.0 for p in parties}

        # Calculate party costs (same logic as scope-breakdown)
        for item in items:
            cost = item.cached_price_usd or item.external_cost_usd or 0
            if cost <= 0:
                continue

            if item.scope == 'party' and item.scope_party_id in party_costs:
                party_costs[item.scope_party_id] += cost
            elif item.scope == 'individual' and item.assigned_to_guest_id:
                pid = guest_party_map.get(item.assigned_to_guest_id)
                if pid and pid in party_costs:
                    party_costs[pid] += cost
            elif item.scope == 'custom' and item.scope_guest_ids_json:
                guest_ids = json.loads(item.scope_guest_ids_json)
                involved = {guest_party_map.get(gid) for gid in guest_ids} - {None}
                if involved:
                    per_party = cost / len(involved)
                    for pid in involved:
                        if pid in party_costs:
                            party_costs[pid] += per_party
            elif item.scope == 'trip' and parties:
                per_party = cost / len(parties)
                for pid in party_costs:
                    party_costs[pid] += per_party

        # Build settlement records per party
        settlements = []
        for p in parties:
            payer = guest_map.get(p.payer_guest_id)
            owed = round(party_costs.get(p.id, 0), 2)
            settlements.append({
                'party_id': p.id,
                'party_name': p.name,
                'payer_guest_id': p.payer_guest_id,
                'payer_name': payer.display_name if payer else 'Unassigned',
                'total_owed': owed,
                'payment_status': payer.payment_status if payer else 'unpaid',
            })

        return jsonify({
            'status': 'ok',
            'settlements': settlements,
            'total_trip_cost': round(sum(party_costs.values()), 2),
        })

    # ──────────────────────────────────────────────
    # VOTING (Build #224)
    # ──────────────────────────────────────────────

    @app.route('/api/trips/<int:trip_id>/itinerary/<int:item_id>/vote', methods=['POST'])
    @login_required
    def vote_on_item(trip_id, item_id):
        """Cast or update a vote on an itinerary item."""
        trip, err = _check_trip_access(trip_id)
        if err:
            return err

        item = ItineraryItem.query.filter_by(id=item_id, trip_id=trip_id).first()
        if not item:
            return jsonify({'status': 'error', 'error': 'Item not found'}), 404

        # Find the guest record for current user
        guest = TripGuest.query.filter_by(
            trip_id=trip_id, user_id=current_user.id
        ).first()
        if not guest:
            return jsonify({'status': 'error', 'error': 'You must be a guest to vote'}), 403

        data = request.get_json(silent=True) or {}
        vote_value = data.get('vote', '')
        if vote_value not in ('up', 'down', 'neutral'):
            return jsonify({'status': 'error', 'error': 'vote must be up/down/neutral'}), 400

        # Upsert: update if exists, create if not
        existing = ItineraryVote.query.filter_by(
            item_id=item_id, guest_id=guest.id
        ).first()

        if existing:
            existing.vote = vote_value
            existing.comment = data.get('comment', existing.comment)
        else:
            vote = ItineraryVote(
                item_id=item_id,
                guest_id=guest.id,
                vote=vote_value,
                comment=data.get('comment'),
            )
            db.session.add(vote)

        db.session.commit()

        # Return vote tally
        tally = _get_vote_tally(item_id)
        return jsonify({'status': 'ok', 'tally': tally})

    @app.route('/api/trips/<int:trip_id>/itinerary/<int:item_id>/votes')
    @login_required
    def get_item_votes(trip_id, item_id):
        """Get all votes on an itinerary item with tally."""
        trip, err = _check_trip_access(trip_id)
        if err:
            return err

        item = ItineraryItem.query.filter_by(id=item_id, trip_id=trip_id).first()
        if not item:
            return jsonify({'status': 'error', 'error': 'Item not found'}), 404

        votes = ItineraryVote.query.filter_by(item_id=item_id).all()
        tally = _get_vote_tally(item_id)

        return jsonify({
            'status': 'ok',
            'votes': [
                {
                    'guest_id': v.guest_id,
                    'vote': v.vote,
                    'comment': v.comment,
                    'created_at': v.created_at.isoformat() if v.created_at else None,
                }
                for v in votes
            ],
            'tally': tally,
        })

    # ──────────────────────────────────────────────
    # COMMENTS (Build #224)
    # ──────────────────────────────────────────────

    @app.route('/api/trips/<int:trip_id>/itinerary/<int:item_id>/comments', methods=['POST'])
    @login_required
    def add_item_comment(trip_id, item_id):
        """Add a comment to an itinerary item."""
        trip, err = _check_trip_access(trip_id)
        if err:
            return err

        item = ItineraryItem.query.filter_by(id=item_id, trip_id=trip_id).first()
        if not item:
            return jsonify({'status': 'error', 'error': 'Item not found'}), 404

        guest = TripGuest.query.filter_by(
            trip_id=trip_id, user_id=current_user.id
        ).first()
        if not guest:
            return jsonify({'status': 'error', 'error': 'You must be a guest to comment'}), 403

        data = request.get_json(silent=True) or {}
        body = (data.get('body') or '').strip()
        if not body:
            return jsonify({'status': 'error', 'error': 'Comment body required'}), 400

        # Validate parent_comment_id if threading
        parent_id = data.get('parent_comment_id')
        if parent_id:
            parent = ItemComment.query.filter_by(id=parent_id, item_id=item_id).first()
            if not parent:
                return jsonify({'status': 'error', 'error': 'Parent comment not found'}), 404

        comment = ItemComment(
            item_id=item_id,
            guest_id=guest.id,
            body=body,
            parent_comment_id=parent_id,
        )
        db.session.add(comment)
        db.session.commit()

        return jsonify({
            'status': 'ok',
            'comment': {
                'id': comment.id,
                'item_id': comment.item_id,
                'guest_id': comment.guest_id,
                'body': comment.body,
                'parent_comment_id': comment.parent_comment_id,
                'created_at': comment.created_at.isoformat() if comment.created_at else None,
            },
        })

    @app.route('/api/trips/<int:trip_id>/itinerary/<int:item_id>/comments')
    @login_required
    def list_item_comments(trip_id, item_id):
        """List all comments on an itinerary item (threaded)."""
        trip, err = _check_trip_access(trip_id)
        if err:
            return err

        item = ItineraryItem.query.filter_by(id=item_id, trip_id=trip_id).first()
        if not item:
            return jsonify({'status': 'error', 'error': 'Item not found'}), 404

        comments = ItemComment.query.filter_by(item_id=item_id).order_by(
            ItemComment.created_at
        ).all()

        return jsonify({
            'status': 'ok',
            'comments': [
                {
                    'id': c.id,
                    'guest_id': c.guest_id,
                    'body': c.body,
                    'parent_comment_id': c.parent_comment_id,
                    'created_at': c.created_at.isoformat() if c.created_at else None,
                }
                for c in comments
            ],
            'count': len(comments),
        })

    @app.route('/api/trips/<int:trip_id>/itinerary/<int:item_id>/comments/<int:comment_id>', methods=['DELETE'])
    @login_required
    def delete_item_comment(trip_id, item_id, comment_id):
        """Delete own comment (or admin can delete any)."""
        trip, err = _check_trip_access(trip_id)
        if err:
            return err

        comment = ItemComment.query.filter_by(id=comment_id, item_id=item_id).first()
        if not comment:
            return jsonify({'status': 'error', 'error': 'Comment not found'}), 404

        # Only the commenter or trip admin can delete
        guest = TripGuest.query.filter_by(
            trip_id=trip_id, user_id=current_user.id
        ).first()
        is_own = guest and guest.id == comment.guest_id
        is_admin = trip.creator_id == current_user.id
        if not is_own and not is_admin:
            return jsonify({'status': 'error', 'error': 'Can only delete your own comments'}), 403

        db.session.delete(comment)
        db.session.commit()
        return jsonify({'status': 'ok'})

    # ──────────────────────────────────────────────
    # SUGGESTION FLOW (Build #224)
    # ──────────────────────────────────────────────

    @app.route('/api/trips/<int:trip_id>/suggestions')
    @login_required
    def list_suggestions(trip_id):
        """List items in 'suggested' status awaiting approval."""
        trip, err = _check_trip_access(trip_id)
        if err:
            return err

        items = ItineraryItem.query.filter_by(
            trip_id=trip_id, status='suggested'
        ).order_by(ItineraryItem.created_at).all()

        results = []
        for item in items:
            d = item.to_dict()
            d['tally'] = _get_vote_tally(item.id)
            results.append(d)

        return jsonify({
            'status': 'ok',
            'suggestions': results,
            'count': len(results),
        })

    @app.route('/api/trips/<int:trip_id>/itinerary/<int:item_id>/approve', methods=['POST'])
    @login_required
    def approve_suggestion(trip_id, item_id):
        """Approve a suggested item (owner/admin only). Moves to 'approved'."""
        trip, err = _check_trip_access(trip_id, require_edit=True)
        if err:
            return err

        # Only trip creator can approve
        if trip.creator_id != current_user.id:
            member = TripMember.query.filter_by(
                trip_plan_id=trip_id, user_id=current_user.id
            ).first()
            if not member or member.role not in ('owner', 'editor'):
                return jsonify({'status': 'error', 'error': 'Only owner/admin can approve'}), 403

        item = ItineraryItem.query.filter_by(id=item_id, trip_id=trip_id).first()
        if not item:
            return jsonify({'status': 'error', 'error': 'Item not found'}), 404

        if item.status != 'suggested':
            return jsonify({'status': 'error', 'error': f'Cannot approve item in "{item.status}" status'}), 400

        item.status = 'approved'
        db.session.commit()
        return jsonify({'status': 'ok', 'item': item.to_dict()})

    # ──────────────────────────────────────────────
    # BOOKING LIFECYCLE (Build #238)
    # ──────────────────────────────────────────────

    @app.route('/api/trips/<int:trip_id>/itinerary/<int:item_id>/link-booking', methods=['POST'])
    @login_required
    def link_booking_to_item(trip_id, item_id):
        """Link an existing Booking record to an itinerary item."""
        trip, err = _check_trip_access(trip_id, require_edit=True)
        if err:
            return err

        item = ItineraryItem.query.filter_by(id=item_id, trip_id=trip_id).first()
        if not item:
            return jsonify({'status': 'error', 'error': 'Item not found'}), 404

        data = request.get_json(silent=True) or {}
        booking_id = data.get('booking_id')
        if not booking_id:
            return jsonify({'status': 'error', 'error': 'booking_id required'}), 400

        from models import Booking
        booking = db.session.get(Booking, booking_id)
        if not booking:
            return jsonify({'status': 'error', 'error': 'Booking not found'}), 404

        item.booking_id = booking.id
        item.status = 'booked'
        item.cached_price_usd = booking.vendor_payment_amount
        db.session.commit()

        return jsonify({'status': 'ok', 'item': item.to_dict()})

    @app.route('/api/trips/<int:trip_id>/bookings')
    @login_required
    def trip_bookings(trip_id):
        """List all bookings linked to itinerary items in this trip."""
        trip, err = _check_trip_access(trip_id)
        if err:
            return err

        from models import Booking

        items = ItineraryItem.query.filter(
            ItineraryItem.trip_id == trip_id,
            ItineraryItem.booking_id.isnot(None),
        ).all()

        results = []
        for item in items:
            booking = db.session.get(Booking, item.booking_id)
            if booking:
                results.append({
                    'item_id': item.id,
                    'item_type': item.item_type,
                    'booking_id': booking.id,
                    'status': booking.status,
                    'lifecycle_status': booking.booking_lifecycle_status,
                    'confirmation_code': booking.confirmation_code,
                    'airline_confirmation': booking.airline_confirmation,
                    'check_in_opens': booking.check_in_opens.isoformat() if booking.check_in_opens else None,
                    'last_status_check': booking.last_status_check.isoformat() if booking.last_status_check else None,
                    'booked_at': booking.booked_at.isoformat() if booking.booked_at else None,
                })

        return jsonify({
            'status': 'ok',
            'bookings': results,
            'count': len(results),
        })

    @app.route('/api/bookings/<int:booking_id>/lifecycle', methods=['PUT'])
    @login_required
    def update_booking_lifecycle(booking_id):
        """Update booking lifecycle status (schedule change, cancellation, etc.)."""
        from models import Booking

        booking = db.session.get(Booking, booking_id)
        if not booking:
            return jsonify({'status': 'error', 'error': 'Booking not found'}), 404

        if booking.user_id != current_user.id and not getattr(current_user, 'is_admin', False):
            return jsonify({'status': 'error', 'error': 'Access denied'}), 403

        data = request.get_json(silent=True) or {}

        valid_statuses = ('active', 'schedule_changed', 'cancelled', 'completed')
        if 'lifecycle_status' in data:
            if data['lifecycle_status'] not in valid_statuses:
                return jsonify({'status': 'error', 'error': f'Invalid status. Valid: {", ".join(valid_statuses)}'}), 400
            booking.booking_lifecycle_status = data['lifecycle_status']

        if 'airline_confirmation' in data:
            booking.airline_confirmation = data['airline_confirmation']
        if 'check_in_opens' in data:
            try:
                booking.check_in_opens = datetime.fromisoformat(data['check_in_opens'])
            except (ValueError, TypeError):
                pass
        if 'rebooking_credit_usd' in data:
            booking.rebooking_credit_usd = data['rebooking_credit_usd']

        booking.last_status_check = _utcnow()
        booking.status_check_count = (booking.status_check_count or 0) + 1
        db.session.commit()

        return jsonify({
            'status': 'ok',
            'booking': {
                'id': booking.id,
                'lifecycle_status': booking.booking_lifecycle_status,
                'airline_confirmation': booking.airline_confirmation,
                'check_in_opens': booking.check_in_opens.isoformat() if booking.check_in_opens else None,
                'last_status_check': booking.last_status_check.isoformat() if booking.last_status_check else None,
                'status_check_count': booking.status_check_count,
                'rebooking_credit_usd': booking.rebooking_credit_usd,
            },
        })

    # ──────────────────────────────────────────────
    # TRIP PLANNER PAGE (UI)
    # ──────────────────────────────────────────────

    @app.route('/trips/<int:trip_id>/plan')
    @login_required
    def trip_planner_page(trip_id):
        """Trip Planner — 5-tab collaborative planning interface."""
        from server import BASE_TEMPLATE

        trip, err = _check_trip_access(trip_id)
        if err:
            return err

        is_owner = (trip.creator_id == current_user.id)

        return render_template_string(
            BASE_TEMPLATE,
            title=trip.name + ' - Trip Planner',
            content=render_template_string(
                TRIP_PLANNER_PAGE,
                trip=trip,
                is_owner=is_owner,
                current_user=current_user,
            ),
            current_user=current_user,
        )

    logger.info("Trip planner routes registered (Builds #221-224, #238)")


def _parse_date(val):
    """Parse a date string (YYYY-MM-DD) to a date object, or None."""
    if not val:
        return None
    if isinstance(val, date):
        return val
    try:
        return date.fromisoformat(val)
    except (ValueError, TypeError):
        return None
