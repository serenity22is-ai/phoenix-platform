"""
Phase 2 — Trip Planner Routes (Build #166)
Collaborative trip planning for MYSTES consumer OTA.

Register in server.py:
    from routes_trips import register_trip_routes
    register_trip_routes(app, csrf, limiter)
"""

import json
import logging
import secrets
from datetime import datetime, timedelta, date, timezone

from flask import request, jsonify, render_template_string, redirect, url_for, session
from flask_login import current_user, login_required

import os
from models import db, User, TripPlan, TripMember, TripItem, TripCart, TripCartAssignment

logger = logging.getLogger(__name__)


# ============================================================
# ACCESS CONTROL HELPER
# ============================================================

def _can_access_trip(trip_id):
    """Check if current_user is the trip creator or a TripMember. Returns the TripPlan or None."""
    trip = db.session.get(TripPlan, trip_id)
    if not trip:
        return None
    if trip.creator_id == current_user.id:
        return trip
    member = TripMember.query.filter_by(
        trip_plan_id=trip_id, user_id=current_user.id
    ).first()
    if member:
        return trip
    return None


def _get_member_role(trip_id, user_id):
    """Return the role string for a user in a trip, or None."""
    member = TripMember.query.filter_by(
        trip_plan_id=trip_id, user_id=user_id
    ).first()
    return member.role if member else None


# ============================================================
# TRIPS LIST TEMPLATE
# ============================================================

TRIPS_LIST_CONTENT = """
<style>
/* ============================================
   TRIPS PAGE — Page-specific styles only
   (glass cards, forms, badges, buttons from component library)
   ============================================ */

.trips-page { max-width: 960px; margin: 0 auto; padding: 0 16px; }

/* Trip cards grid */
.trips-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
    gap: 20px;
    margin-top: 20px;
}
.trip-card {
    cursor: pointer;
    position: relative;
}
.trip-card-name {
    font-family: var(--font-brand, 'Space Grotesk', sans-serif);
    font-size: 18px;
    font-weight: 600;
    color: #f5f5f5;
    margin: 0 0 8px;
    letter-spacing: 1px;
}
.trip-card-dates {
    font-size: 13px;
    color: rgba(255,255,255,0.6);
    margin-bottom: 12px;
}
.trip-card-meta {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
}
.trip-card-destinations {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    margin-top: 12px;
}
.trip-dest-tag {
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 6px;
    padding: 3px 10px;
    font-size: 12px;
    color: rgba(255,255,255,0.6);
}
.trip-card-delete {
    position: absolute;
    top: 14px;
    right: 14px;
    background: none;
    border: none;
    color: rgba(255,255,255,0.25);
    cursor: pointer;
    font-size: 18px;
    padding: 4px 8px;
    border-radius: 6px;
    transition: all 0.2s;
    line-height: 1;
}
.trip-card-delete:hover { color: #ef4444; background: rgba(239,68,68,0.1); }

/* Create form visibility toggle */
.trip-create-form { display: none; margin-bottom: 24px; }
.trip-create-form.visible { display: block; }
.trip-form-actions { display: flex; gap: 12px; margin-top: 16px; }

/* Empty state overrides */
.trips-empty h3 {
    font-family: var(--font-brand, 'Space Grotesk', sans-serif);
    font-size: 20px;
    color: #f5f5f5;
    margin: 0 0 8px;
}
.trips-empty p { color: #aaa; font-size: 14px; margin: 0 0 24px; }

@media (max-width: 600px) {
    .trips-grid { grid-template-columns: 1fr; }
}
</style>

<div class="trips-page">
    <div class="mystes-page-header">
        <h1>MY TRIPS</h1>
        <p>Plan, collaborate, and book your group adventures</p>
    </div>

    <div style="text-align: center;">
        <button class="mystes-btn mystes-btn-gold" onclick="toggleCreateForm()">+ Create Trip</button>
    </div>

    <!-- Inline Create Form -->
    <div class="trip-create-form mystes-card" id="createForm">
        <div class="mystes-form-grid">
            <div class="full-width">
                <label class="mystes-label">Trip Name</label>
                <input type="text" class="mystes-input" id="tripName" placeholder="Summer in Greece, Tokyo Adventure..." />
            </div>
            <div>
                <label class="mystes-label">Start Date</label>
                <input type="date" class="mystes-input" id="tripStartDate" />
            </div>
            <div>
                <label class="mystes-label">End Date</label>
                <input type="date" class="mystes-input" id="tripEndDate" />
            </div>
            <div class="full-width">
                <label class="mystes-label">Destinations</label>
                <textarea class="mystes-textarea" id="tripDestinations" placeholder="Athens, Santorini, Mykonos"></textarea>
            </div>
        </div>
        <div class="trip-form-actions">
            <button class="mystes-btn mystes-btn-gold" onclick="createTrip()">Create Trip</button>
            <button class="mystes-btn mystes-btn-ghost" onclick="toggleCreateForm()">Cancel</button>
        </div>
    </div>

    {% if trips %}
    <div class="trips-grid">
        {% for trip in trips %}
        <div class="mystes-card interactive trip-card" onclick="window.location='/trips/{{ trip.id }}'">
            <button class="trip-card-delete" onclick="event.stopPropagation(); deleteTrip({{ trip.id }})" title="Delete trip">&times;</button>
            <div class="trip-card-name">{{ trip.name }}</div>
            <div class="trip-card-dates">
                {% if trip.start_date and trip.end_date %}
                    {{ trip.start_date.strftime('%b %d') }} &ndash; {{ trip.end_date.strftime('%b %d, %Y') }}
                {% elif trip.start_date %}
                    Starting {{ trip.start_date.strftime('%b %d, %Y') }}
                {% else %}
                    Dates not set
                {% endif %}
            </div>
            <div class="trip-card-meta">
                <span class="mystes-badge mystes-badge-teal">{{ trip.members.count() }} member{{ 's' if trip.members.count() != 1 else '' }}</span>
                {% if trip.status == 'draft' %}
                <span class="mystes-badge mystes-badge-neutral">{{ trip.status }}</span>
                {% elif trip.status == 'finalized' %}
                <span class="mystes-badge mystes-badge-gold">{{ trip.status }}</span>
                {% elif trip.status == 'booked' %}
                <span class="mystes-badge mystes-badge-teal">{{ trip.status }}</span>
                {% elif trip.status == 'completed' %}
                <span class="mystes-badge mystes-badge-green">{{ trip.status }}</span>
                {% else %}
                <span class="mystes-badge mystes-badge-neutral">{{ trip.status }}</span>
                {% endif %}
            </div>
            {% if trip.destinations_json %}
            <div class="trip-card-destinations">
                {% for dest in (trip.destinations_json | from_json_safe) %}
                <span class="trip-dest-tag">{{ dest }}</span>
                {% endfor %}
            </div>
            {% endif %}
        </div>
        {% endfor %}
    </div>
    {% else %}
    <div class="mystes-card mystes-empty trips-empty">
        <div class="mystes-empty-icon">&#9992;</div>
        <h3>Plan your next adventure</h3>
        <p>Create a trip to start adding flights, hotels, and activities with friends.</p>
        <button class="mystes-btn mystes-btn-gold" onclick="toggleCreateForm()">Create Your First Trip</button>
    </div>
    {% endif %}
</div>

<script>
function toggleCreateForm() {
    var form = document.getElementById('createForm');
    form.classList.toggle('visible');
    if (form.classList.contains('visible')) {
        document.getElementById('tripName').focus();
    }
}

function createTrip() {
    var name = document.getElementById('tripName').value.trim();
    if (!name) { alert('Please enter a trip name.'); return; }
    var startDate = document.getElementById('tripStartDate').value;
    var endDate = document.getElementById('tripEndDate').value;
    var destinations = document.getElementById('tripDestinations').value.trim();

    fetch('/api/trips', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            name: name,
            start_date: startDate || null,
            end_date: endDate || null,
            destinations: destinations || null
        })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.success) {
            window.location.href = data.redirect_url || '/trips/' + data.trip_id;
        } else {
            alert(data.error || 'Failed to create trip.');
        }
    })
    .catch(function(err) { alert('Error creating trip: ' + err.message); });
}

function deleteTrip(tripId) {
    if (!confirm('Delete this trip and all its items? This cannot be undone.')) return;
    fetch('/api/trips/' + tripId, {
        method: 'DELETE',
        headers: {'Content-Type': 'application/json'}
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.success) {
            window.location.reload();
        } else {
            alert(data.error || 'Failed to delete trip.');
        }
    })
    .catch(function(err) { alert('Error: ' + err.message); });
}
</script>
"""


# ============================================================
# TRIP DETAIL TEMPLATE
# ============================================================

TRIP_DETAIL_CONTENT = """
<style>
/* ============================================
   TRIP DETAIL — Page-specific styles only
   (glass cards, forms, badges, buttons from component library)
   ============================================ */

.trip-detail { max-width: 960px; margin: 0 auto; padding: 0 16px; }

/* Trip header */
.trip-header { margin: 24px 0; }
.trip-header-top {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
    flex-wrap: wrap;
}
.trip-title-editable {
    font-family: var(--font-brand, 'Space Grotesk', sans-serif);
    font-size: 28px;
    font-weight: 700;
    letter-spacing: 2px;
    color: #f5f5f5;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 4px 8px;
    transition: all 0.3s;
    width: 100%;
    max-width: 500px;
}
.trip-title-editable:hover { border-color: rgba(255,255,255,0.12); }
.trip-title-editable:focus {
    outline: none;
    border-color: #14b8a6;
    background: rgba(255,255,255,0.05);
}
.trip-header-dates {
    color: rgba(255,255,255,0.6);
    font-size: 14px;
    margin-top: 8px;
}
.trip-header-meta {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-top: 12px;
}
.trip-member-avatars {
    display: flex;
    gap: 0;
    margin-top: 12px;
}
.trip-member-avatar {
    width: 36px;
    height: 36px;
    border-radius: 50%;
    background: rgba(20, 184, 166, 0.2);
    border: 2px solid rgba(10, 6, 18, 0.9);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 13px;
    font-weight: 700;
    color: #14b8a6;
    margin-left: -8px;
}
.trip-member-avatar:first-child { margin-left: 0; }

/* Layout: itinerary + sidebar */
.trip-layout {
    display: grid;
    grid-template-columns: 1fr 280px;
    gap: 24px;
    align-items: flex-start;
}
@media (max-width: 768px) {
    .trip-layout { grid-template-columns: 1fr; }
}

/* Day columns */
.trip-itinerary { display: flex; flex-direction: column; gap: 20px; }
.trip-day-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 14px;
    padding-bottom: 10px;
    border-bottom: 1px solid rgba(255,255,255,0.06);
}
.trip-day-label {
    font-family: var(--font-brand, 'Space Grotesk', sans-serif);
    font-size: 16px;
    font-weight: 600;
    color: #f5f5f5;
    letter-spacing: 1px;
}
.trip-day-date {
    font-size: 12px;
    color: rgba(255,255,255,0.4);
}
.trip-add-item-btn {
    font-size: 12px;
    color: #14b8a6;
    background: rgba(20, 184, 166, 0.1);
    border: 1px solid rgba(20, 184, 166, 0.25);
    border-radius: 8px;
    padding: 5px 12px;
    cursor: pointer;
    transition: all 0.2s;
    text-decoration: none;
    display: inline-block;
}
.trip-add-item-btn:hover {
    background: rgba(20, 184, 166, 0.2);
    border-color: rgba(20, 184, 166, 0.5);
}

/* Item cards */
.trip-item-list { display: flex; flex-direction: column; gap: 10px; }
.trip-item-card {
    display: flex;
    align-items: center;
    gap: 12px;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 12px;
    padding: 14px;
    transition: all 0.2s;
}
.trip-item-card:hover { border-color: rgba(255,255,255,0.12); }
.trip-item-icon {
    width: 38px;
    height: 38px;
    border-radius: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 18px;
    flex-shrink: 0;
}
.trip-item-icon.flight { background: rgba(99,102,241,0.15); color: #818cf8; }
.trip-item-icon.hotel { background: rgba(168,85,247,0.15); color: #c084fc; }
.trip-item-icon.car { background: rgba(251,191,36,0.15); color: #fbbf24; }
.trip-item-icon.activity { background: rgba(20,184,166,0.15); color: #14b8a6; }
.trip-item-icon.event { background: rgba(244,114,182,0.15); color: #f472b6; }
.trip-item-icon.dining { background: rgba(251,146,60,0.15); color: #fb923c; }
.trip-item-info { flex: 1; min-width: 0; }
.trip-item-title {
    font-size: 14px;
    font-weight: 600;
    color: #f5f5f5;
    margin: 0 0 3px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.trip-item-subtitle {
    font-size: 12px;
    color: rgba(255,255,255,0.5);
}
.trip-item-price {
    font-size: 15px;
    font-weight: 700;
    color: #c9a44a;
    white-space: nowrap;
}
.trip-item-actions {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-shrink: 0;
}
.trip-vote-btn {
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 8px;
    padding: 4px 8px;
    cursor: pointer;
    font-size: 13px;
    color: rgba(255,255,255,0.5);
    transition: all 0.2s;
    display: flex;
    align-items: center;
    gap: 3px;
}
.trip-vote-btn:hover { border-color: rgba(255,255,255,0.25); color: #f5f5f5; }
.trip-vote-btn.voted-up { background: rgba(34,197,94,0.15); border-color: rgba(34,197,94,0.3); color: #22c55e; }
.trip-vote-btn.voted-down { background: rgba(239,68,68,0.15); border-color: rgba(239,68,68,0.3); color: #ef4444; }
.trip-item-remove {
    background: none;
    border: none;
    color: rgba(255,255,255,0.2);
    cursor: pointer;
    font-size: 18px;
    padding: 2px 6px;
    border-radius: 6px;
    transition: all 0.2s;
    line-height: 1;
}
.trip-item-remove:hover { color: #ef4444; background: rgba(239,68,68,0.1); }
.trip-day-empty {
    text-align: center;
    padding: 20px;
    color: rgba(255,255,255,0.3);
    font-size: 13px;
}

/* Members sidebar */
.trip-sidebar {
    display: flex;
    flex-direction: column;
    gap: 20px;
}
.trip-sidebar-title {
    font-family: var(--font-brand, 'Space Grotesk', sans-serif);
    font-size: 14px;
    font-weight: 600;
    letter-spacing: 1px;
    color: #f5f5f5;
    margin: 0 0 14px;
    text-transform: uppercase;
}
.trip-member-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 0;
    border-bottom: 1px solid rgba(255,255,255,0.04);
}
.trip-member-row:last-child { border-bottom: none; }
.trip-member-name {
    font-size: 14px;
    color: #f5f5f5;
    flex: 1;
}
.trip-member-role {
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    padding: 2px 8px;
    border-radius: 4px;
}
.trip-member-role.owner { background: rgba(201,164,74,0.2); color: #c9a44a; }
.trip-member-role.editor { background: rgba(20,184,166,0.2); color: #14b8a6; }
.trip-member-role.viewer { background: rgba(255,255,255,0.08); color: #aaa; }

.trip-invite-section { margin-top: 12px; }
.trip-invite-row {
    display: flex;
    gap: 8px;
}

/* Cart summary */
.trip-cart-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 0;
    font-size: 14px;
    color: rgba(255,255,255,0.6);
}
.trip-cart-row.total {
    border-top: 1px solid rgba(255,255,255,0.10);
    margin-top: 8px;
    padding-top: 12px;
    font-size: 18px;
    font-weight: 700;
    color: #f5f5f5;
}
.trip-cart-value { color: #c9a44a; font-weight: 600; }
.trip-cart-value.total { font-size: 20px; }

/* Add item dropdown */
.trip-add-dropdown {
    display: none;
    position: absolute;
    background: rgba(15, 10, 25, 0.95);
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 12px;
    padding: 8px;
    z-index: 100;
    min-width: 180px;
    box-shadow: 0 12px 40px rgba(0,0,0,0.5);
}
.trip-add-dropdown.visible { display: block; }
.trip-add-dropdown a {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 14px;
    border-radius: 8px;
    color: #f5f5f5;
    text-decoration: none;
    font-size: 14px;
    transition: background 0.2s;
}
.trip-add-dropdown a:hover { background: rgba(255,255,255,0.08); }
.trip-add-dropdown a span.icon { font-size: 16px; width: 20px; text-align: center; }
</style>

<div class="trip-detail">
    <!-- Header -->
    <div class="mystes-card trip-header">
        <div class="trip-header-top">
            <div>
                <input class="trip-title-editable" id="tripTitle"
                       value="{{ trip.name }}"
                       onblur="updateTripField('name', this.value)"
                       onkeydown="if(event.key==='Enter'){this.blur();}" />
                <div class="trip-header-dates">
                    {% if trip.start_date and trip.end_date %}
                        {{ trip.start_date.strftime('%B %d') }} &ndash; {{ trip.end_date.strftime('%B %d, %Y') }}
                        &middot; {{ (trip.end_date - trip.start_date).days + 1 }} days
                    {% elif trip.start_date %}
                        Starting {{ trip.start_date.strftime('%B %d, %Y') }}
                    {% else %}
                        <span style="color:rgba(255,255,255,0.3)">Dates not set</span>
                    {% endif %}
                </div>
            </div>
            {% if trip.status == 'draft' %}
            <span class="mystes-badge mystes-badge-neutral">{{ trip.status }}</span>
            {% elif trip.status == 'finalized' %}
            <span class="mystes-badge mystes-badge-gold">{{ trip.status }}</span>
            {% elif trip.status == 'booked' %}
            <span class="mystes-badge mystes-badge-teal">{{ trip.status }}</span>
            {% elif trip.status == 'completed' %}
            <span class="mystes-badge mystes-badge-green">{{ trip.status }}</span>
            {% else %}
            <span class="mystes-badge mystes-badge-neutral">{{ trip.status }}</span>
            {% endif %}
        </div>
        <div class="trip-member-avatars">
            {% for m in members %}
            <div class="trip-member-avatar" title="{{ m.user.name or m.user.email }}">
                {{ (m.user.name or m.user.email)[:1] | upper }}
            </div>
            {% endfor %}
        </div>
        <div style="display:flex; gap:10px; margin-top:14px; flex-wrap:wrap;">
            <a href="/trips/{{ trip.id }}/plan" style="padding:8px 18px; background:rgba(20,184,166,0.15); border:1px solid rgba(20,184,166,0.3); border-radius:10px; color:#14b8a6; font-size:13px; font-weight:600; text-decoration:none; letter-spacing:0.5px; transition:all 0.2s;">&#9776; Trip Planner</a>
            <a href="/trips/{{ trip.id }}/events" style="padding:8px 18px; background:rgba(124,58,237,0.12); border:1px solid rgba(124,58,237,0.3); border-radius:10px; color:#a78bfa; font-size:13px; font-weight:600; text-decoration:none; letter-spacing:0.5px; transition:all 0.2s;">&#9734; Events</a>
        </div>
    </div>

    <!-- Main layout -->
    <div class="trip-layout">
        <!-- Itinerary column -->
        <div class="trip-itinerary">
            {% if trip.start_date and trip.end_date %}
                {% set num_days = (trip.end_date - trip.start_date).days + 1 %}
            {% else %}
                {% set num_days = 1 %}
            {% endif %}

            {% for day_offset in range(num_days) %}
            {% if trip.start_date %}
                {% set day_num = day_offset + 1 %}
            {% else %}
                {% set day_num = 1 %}
            {% endif %}
            <div class="mystes-card">
                <div class="trip-day-header">
                    <div>
                        <span class="trip-day-label">Day {{ day_num }}</span>
                        {% if trip.start_date %}
                        <span class="trip-day-date">
                            {{ (trip.start_date + timedelta_fn(days=day_offset)).strftime('%a, %b %d') }}
                        </span>
                        {% endif %}
                    </div>
                    <div style="position:relative;">
                        <button class="trip-add-item-btn" onclick="toggleAddDropdown(this, {{ trip.id }}, {{ day_num }})">
                            + Add Item
                        </button>
                        <div class="trip-add-dropdown" id="addDrop-{{ day_num }}">
                            <a href="/flights?trip_id={{ trip.id }}&day={{ day_num }}">
                                <span class="icon">&#9992;</span> Flight
                            </a>
                            <a href="/hotels?trip_id={{ trip.id }}&day={{ day_num }}">
                                <span class="icon">&#127976;</span> Hotel
                            </a>
                            <a href="/cars?trip_id={{ trip.id }}&day={{ day_num }}">
                                <span class="icon">&#128663;</span> Car Rental
                            </a>
                            <a href="/activities?trip_id={{ trip.id }}&day={{ day_num }}">
                                <span class="icon">&#127907;</span> Activity
                            </a>
                        </div>
                    </div>
                </div>
                <div class="trip-item-list">
                    {% set day_items = items_by_day.get(day_num, []) %}
                    {% if day_items %}
                        {% for item in day_items %}
                        {% set idata = item.item_data_json | from_json_safe_obj %}
                        {% set votes = item.votes_json | from_json_safe_obj if item.votes_json else {} %}
                        {% set up_count = votes.values() | select('equalto', 'up') | list | length %}
                        {% set down_count = votes.values() | select('equalto', 'down') | list | length %}
                        {% set my_vote = votes.get(current_user_id | string, '') %}
                        <div class="trip-item-card">
                            <div class="trip-item-icon {{ item.vertical }}">
                                {% if item.vertical == 'flight' %}&#9992;{% elif item.vertical == 'hotel' %}&#127976;{% elif item.vertical == 'car' %}&#128663;{% elif item.vertical == 'activity' %}&#127907;{% elif item.vertical == 'event' %}&#127915;{% elif item.vertical == 'dining' %}&#127860;{% else %}&#128205;{% endif %}
                            </div>
                            <div class="trip-item-info">
                                <div class="trip-item-title">{{ idata.get('title', idata.get('name', item.vertical | title)) }}</div>
                                <div class="trip-item-subtitle">{{ idata.get('subtitle', idata.get('description', '')) | truncate(60) }}</div>
                            </div>
                            {% if idata.get('price') %}
                            <div class="trip-item-price">${{ '%.2f' | format(idata.get('price', 0) | float) }}</div>
                            {% endif %}
                            <div class="trip-item-actions">
                                <button class="trip-vote-btn {{ 'voted-up' if my_vote == 'up' else '' }}"
                                        onclick="event.stopPropagation(); voteOnItem({{ trip.id }}, {{ item.id }}, 'up')">
                                    &#128077; <span>{{ up_count }}</span>
                                </button>
                                <button class="trip-vote-btn {{ 'voted-down' if my_vote == 'down' else '' }}"
                                        onclick="event.stopPropagation(); voteOnItem({{ trip.id }}, {{ item.id }}, 'down')">
                                    &#128078; <span>{{ down_count }}</span>
                                </button>
                                <button class="trip-item-remove"
                                        onclick="event.stopPropagation(); removeItem({{ trip.id }}, {{ item.id }})"
                                        title="Remove item">&times;</button>
                            </div>
                        </div>
                        {% endfor %}
                    {% else %}
                        <div class="trip-day-empty">No items yet &mdash; add flights, hotels, or activities</div>
                    {% endif %}
                </div>
            </div>
            {% endfor %}
        </div>

        <!-- Sidebar -->
        <div class="trip-sidebar">
            <!-- Members -->
            <div class="mystes-card">
                <div class="trip-sidebar-title">Members</div>
                {% for m in members %}
                <div class="trip-member-row">
                    <div class="trip-member-avatar" style="width:30px;height:30px;font-size:12px;margin-left:0;">
                        {{ (m.user.name or m.user.email)[:1] | upper }}
                    </div>
                    <span class="trip-member-name">{{ m.user.name or m.user.email }}</span>
                    <span class="trip-member-role {{ m.role }}">{{ m.role }}</span>
                </div>
                {% endfor %}

                <div class="trip-invite-section">
                    <div class="trip-invite-row">
                        <input class="mystes-input" id="inviteEmail"
                               placeholder="friend@email.com"
                               onkeydown="if(event.key==='Enter') inviteFriend({{ trip.id }});" />
                        <button class="mystes-btn mystes-btn-success mystes-btn-sm" onclick="inviteFriend({{ trip.id }})">Invite</button>
                    </div>
                </div>
            </div>

            <!-- Cart summary -->
            <div class="mystes-card">
                <div class="trip-sidebar-title">Trip Summary</div>
                <div class="trip-cart-row">
                    <span>Items</span>
                    <span class="trip-cart-value" id="cartItemCount">{{ cart_data.item_count }}</span>
                </div>
                <div class="trip-cart-row">
                    <span>Total Cost</span>
                    <span class="trip-cart-value" id="cartTotal">${{ '%.2f' | format(cart_data.total_cost) }}</span>
                </div>
                {% if cart_data.member_count > 1 %}
                <div class="trip-cart-row">
                    <span>Per Person ({{ cart_data.member_count }})</span>
                    <span class="trip-cart-value" id="cartPerPerson">${{ '%.2f' | format(cart_data.per_person) }}</span>
                </div>
                {% endif %}
                <div class="trip-cart-row total">
                    <span>Total</span>
                    <span class="trip-cart-value total">${{ '%.2f' | format(cart_data.total_cost) }}</span>
                </div>
                <button class="mystes-btn mystes-btn-gold mystes-btn-full" onclick="tripCheckout()" title="One person pays, split later" style="margin-top:16px;">Checkout All</button>
            </div>
        </div>
    </div>

    <!-- Bottom cart — Balances (Build #209) -->
    <div class="mystes-card" id="balances-section" style="margin-top:30px;margin-bottom:40px;">
        <div id="balances-content" style="text-align:center;color:rgba(255,255,255,0.3);font-size:13px;">
            Checkout to see split balances.
        </div>
    </div>
</div>

<script>
var TRIP_ID = {{ trip.id }};

function updateTripField(field, value) {
    var body = {};
    body[field] = value;
    fetch('/api/trips/' + TRIP_ID, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body)
    }).then(function(r) { return r.json(); })
    .then(function(data) {
        if (!data.success) { alert(data.error || 'Update failed.'); }
    });
}

function toggleAddDropdown(btn, tripId, dayNum) {
    var drop = document.getElementById('addDrop-' + dayNum);
    // Close all others
    document.querySelectorAll('.trip-add-dropdown.visible').forEach(function(el) {
        if (el !== drop) el.classList.remove('visible');
    });
    drop.classList.toggle('visible');
}

// Close dropdowns on outside click
document.addEventListener('click', function(e) {
    if (!e.target.closest('.trip-add-item-btn') && !e.target.closest('.trip-add-dropdown')) {
        document.querySelectorAll('.trip-add-dropdown.visible').forEach(function(el) {
            el.classList.remove('visible');
        });
    }
});

function removeItem(tripId, itemId) {
    if (!confirm('Remove this item from the trip?')) return;
    fetch('/api/trips/' + tripId + '/items/' + itemId, {
        method: 'DELETE',
        headers: {'Content-Type': 'application/json'}
    }).then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.success) { window.location.reload(); }
        else { alert(data.error || 'Failed to remove item.'); }
    });
}

function voteOnItem(tripId, itemId, vote) {
    fetch('/api/trips/' + tripId + '/items/' + itemId + '/vote', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({vote: vote})
    }).then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.success) { window.location.reload(); }
        else { alert(data.error || 'Vote failed.'); }
    });
}

function inviteFriend(tripId) {
    var emailInput = document.getElementById('inviteEmail');
    var email = emailInput.value.trim();
    if (!email) { alert('Enter an email address.'); return; }
    fetch('/api/trips/' + tripId + '/invite', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({email: email})
    }).then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.success) {
            emailInput.value = '';
            window.location.reload();
        } else {
            alert(data.error || 'Invite failed.');
        }
    });
}

/* Trip Checkout + Settle Up (Build #209) */
function tripCheckout() {
    if (!confirm('Checkout this trip? You will pay the full service fee and can request reimbursement from group members.')) return;
    fetch('/api/trips/' + TRIP_ID + '/checkout', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({})
    }).then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.success) {
            alert('Trip booked! Service fee: $' + data.total_service_fee.toFixed(2) + ' ($' + data.per_person.toFixed(2) + '/person)');
            loadBalances();
            window.location.reload();
        } else {
            alert(data.error || 'Checkout failed.');
        }
    });
}

function loadBalances() {
    fetch('/api/trips/' + TRIP_ID + '/balances')
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (!data.success || !data.checked_out) return;
        var el = document.getElementById('balances-content');
        var html = '<div style="text-align:left;padding:10px;">';
        html += '<div style="color:#a855f7;font-weight:600;margin-bottom:8px;">Balances — $' + data.total_service_fee.toFixed(2) + ' total</div>';
        data.balances.forEach(function(b) {
            var color = b.status === 'paid' ? '#22c55e' : (b.status === 'requested' ? '#f59e0b' : '#999');
            html += '<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid rgba(255,255,255,0.05);">';
            html += '<span style="color:#ddd;">' + b.name + (b.is_payer ? ' (payer)' : '') + '</span>';
            html += '<span style="color:' + color + ';">$' + b.amount_owed.toFixed(2) + ' — ' + b.status + '</span>';
            html += '</div>';
        });
        html += '</div>';
        el.innerHTML = html;
    });
}
loadBalances();
</script>
"""


# ============================================================
# ROUTE REGISTRATION
# ============================================================

def register_trip_routes(app, csrf, limiter):
    """Register all trip planner routes on the Flask app."""
    from server import BASE_TEMPLATE, is_feature_enabled

    # ---- Jinja Filters for templates ----
    @app.template_filter('from_json_safe')
    def from_json_safe(value):
        """Parse JSON string to list, return empty list on failure."""
        if not value:
            return []
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, TypeError):
            return []

    @app.template_filter('from_json_safe_obj')
    def from_json_safe_obj(value):
        """Parse JSON string to dict, return empty dict on failure."""
        if not value:
            return {}
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    # ------------------------------------------------------------------
    # 1. GET /trips — Trips list page
    # ------------------------------------------------------------------
    @app.route("/trips")
    @login_required
    def trips_list():
        """Trip planner list page."""
        if not is_feature_enabled("trip_planner"):
            return redirect(url_for("home"))

        # Trips where user is creator OR a member
        owned = TripPlan.query.filter_by(creator_id=current_user.id).all()
        member_of_ids = [
            tm.trip_plan_id for tm in
            TripMember.query.filter_by(user_id=current_user.id).all()
        ]
        member_trips = TripPlan.query.filter(
            TripPlan.id.in_(member_of_ids)
        ).all() if member_of_ids else []

        # Deduplicate (owner is also a member)
        seen = set()
        trips = []
        for t in owned + member_trips:
            if t.id not in seen:
                seen.add(t.id)
                trips.append(t)

        # Sort by most recent first
        trips.sort(key=lambda t: t.created_at or datetime.min, reverse=True)

        return render_template_string(
            BASE_TEMPLATE,
            title="My Trips",
            content=render_template_string(
                TRIPS_LIST_CONTENT,
                trips=trips,
                current_user=current_user,
            ),
            current_user=current_user,
        )

    # ------------------------------------------------------------------
    # 2. POST /api/trips — Create trip
    # ------------------------------------------------------------------
    @app.route("/api/trips", methods=["POST"])
    @csrf.exempt
    @login_required
    def api_create_trip():
        """Create a new trip plan."""
        data = request.get_json(silent=True) or {}
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"success": False, "error": "Trip name is required."}), 400

        start_date = None
        end_date = None
        if data.get("start_date"):
            try:
                start_date = date.fromisoformat(data["start_date"])
            except (ValueError, TypeError):
                return jsonify({"success": False, "error": "Invalid start date."}), 400
        if data.get("end_date"):
            try:
                end_date = date.fromisoformat(data["end_date"])
            except (ValueError, TypeError):
                return jsonify({"success": False, "error": "Invalid end date."}), 400

        if start_date and end_date and end_date < start_date:
            return jsonify({"success": False, "error": "End date must be after start date."}), 400

        # Parse destinations: comma-separated string → JSON array
        destinations_raw = (data.get("destinations") or "").strip()
        destinations_json = None
        if destinations_raw:
            dest_list = [d.strip() for d in destinations_raw.split(",") if d.strip()]
            destinations_json = json.dumps(dest_list)

        trip = TripPlan(
            creator_id=current_user.id,
            name=name,
            start_date=start_date,
            end_date=end_date,
            destinations_json=destinations_json,
            status="draft",
        )
        db.session.add(trip)
        db.session.flush()  # Get the trip.id

        # Add creator as owner member
        owner_member = TripMember(
            trip_plan_id=trip.id,
            user_id=current_user.id,
            role="owner",
            invitation_status="accepted",
            joined_at=datetime.utcnow(),
        )
        db.session.add(owner_member)
        db.session.commit()

        logger.info("Trip created: id=%d name=%s by user=%d", trip.id, name, current_user.id)
        return jsonify({
            "success": True,
            "trip_id": trip.id,
            "redirect_url": f"/trips/{trip.id}",
        })

    # ------------------------------------------------------------------
    # 3. GET /trips/<trip_id> — Trip detail page
    # ------------------------------------------------------------------
    @app.route("/trips/<int:trip_id>")
    @login_required
    def trip_detail(trip_id):
        """Trip detail / itinerary page."""
        if not is_feature_enabled("trip_planner"):
            return redirect(url_for("home"))

        trip = _can_access_trip(trip_id)
        if not trip:
            return redirect(url_for("trips_list"))

        members = TripMember.query.filter_by(trip_plan_id=trip_id).all()
        items = TripItem.query.filter_by(trip_plan_id=trip_id).order_by(TripItem.day_number, TripItem.created_at).all()

        # Group items by day_number
        items_by_day = {}
        for item in items:
            day = item.day_number or 1
            if day not in items_by_day:
                items_by_day[day] = []
            items_by_day[day].append(item)

        # Compute cart data
        total_cost = 0.0
        item_count = len(items)
        for item in items:
            try:
                idata = json.loads(item.item_data_json) if item.item_data_json else {}
                total_cost += float(idata.get("price", 0))
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

        member_count = len(members)
        per_person = total_cost / member_count if member_count > 0 else total_cost
        cart_data = {
            "item_count": item_count,
            "total_cost": total_cost,
            "member_count": member_count,
            "per_person": per_person,
        }

        return render_template_string(
            BASE_TEMPLATE,
            title=trip.name,
            content=render_template_string(
                TRIP_DETAIL_CONTENT,
                trip=trip,
                items=items,
                items_by_day=items_by_day,
                members=members,
                cart_data=cart_data,
                current_user=current_user,
                current_user_id=current_user.id,
                timedelta_fn=timedelta,
            ),
            current_user=current_user,
        )

    # ------------------------------------------------------------------
    # 4. PUT /api/trips/<trip_id> — Update trip
    # ------------------------------------------------------------------
    @app.route("/api/trips/<int:trip_id>", methods=["PUT"])
    @csrf.exempt
    @login_required
    def api_update_trip(trip_id):
        """Update trip name, dates, or status. Owner or editor only."""
        trip = _can_access_trip(trip_id)
        if not trip:
            return jsonify({"success": False, "error": "Trip not found or access denied."}), 404

        role = _get_member_role(trip_id, current_user.id)
        if role not in ("owner", "editor") and trip.creator_id != current_user.id:
            return jsonify({"success": False, "error": "Only owners and editors can update trips."}), 403

        data = request.get_json(silent=True) or {}

        if "name" in data:
            name = (data["name"] or "").strip()
            if name:
                trip.name = name

        if "start_date" in data:
            if data["start_date"]:
                try:
                    trip.start_date = date.fromisoformat(data["start_date"])
                except (ValueError, TypeError):
                    return jsonify({"success": False, "error": "Invalid start date."}), 400
            else:
                trip.start_date = None

        if "end_date" in data:
            if data["end_date"]:
                try:
                    trip.end_date = date.fromisoformat(data["end_date"])
                except (ValueError, TypeError):
                    return jsonify({"success": False, "error": "Invalid end date."}), 400
            else:
                trip.end_date = None

        if "status" in data:
            allowed = ("draft", "finalized", "booked", "completed")
            if data["status"] in allowed:
                trip.status = data["status"]

        if "destinations" in data:
            raw = (data["destinations"] or "").strip()
            if raw:
                dest_list = [d.strip() for d in raw.split(",") if d.strip()]
                trip.destinations_json = json.dumps(dest_list)
            else:
                trip.destinations_json = None

        db.session.commit()
        logger.info("Trip updated: id=%d by user=%d", trip_id, current_user.id)
        return jsonify({"success": True})

    # ------------------------------------------------------------------
    # 5. DELETE /api/trips/<trip_id> — Delete trip
    # ------------------------------------------------------------------
    @app.route("/api/trips/<int:trip_id>", methods=["DELETE"])
    @csrf.exempt
    @login_required
    def api_delete_trip(trip_id):
        """Delete trip. Owner only."""
        trip = _can_access_trip(trip_id)
        if not trip:
            return jsonify({"success": False, "error": "Trip not found or access denied."}), 404

        if trip.creator_id != current_user.id:
            return jsonify({"success": False, "error": "Only the trip owner can delete it."}), 403

        db.session.delete(trip)
        db.session.commit()
        logger.info("Trip deleted: id=%d by user=%d", trip_id, current_user.id)
        return jsonify({"success": True})

    # ------------------------------------------------------------------
    # 6. POST /api/trips/<trip_id>/items — Add item to trip
    # ------------------------------------------------------------------
    @app.route("/api/trips/<int:trip_id>/items", methods=["POST"])
    @csrf.exempt
    @login_required
    def api_add_trip_item(trip_id):
        """Add an item (flight, hotel, car, activity) to a trip day."""
        trip = _can_access_trip(trip_id)
        if not trip:
            return jsonify({"success": False, "error": "Trip not found or access denied."}), 404

        data = request.get_json(silent=True) or {}
        vertical = (data.get("vertical") or "").strip().lower()
        if vertical not in ("flight", "hotel", "car", "activity", "event", "dining"):
            return jsonify({"success": False, "error": "Invalid vertical. Must be one of: flight, hotel, car, activity, event, dining."}), 400

        item_data = data.get("item_data_json")
        if isinstance(item_data, dict):
            item_data_str = json.dumps(item_data)
        elif isinstance(item_data, str):
            # Validate it is valid JSON
            try:
                json.loads(item_data)
                item_data_str = item_data
            except json.JSONDecodeError:
                return jsonify({"success": False, "error": "item_data_json must be valid JSON."}), 400
        else:
            item_data_str = json.dumps({})

        day_number = data.get("day_number")
        if day_number is not None:
            try:
                day_number = int(day_number)
            except (ValueError, TypeError):
                day_number = 1
        else:
            day_number = 1

        item = TripItem(
            trip_plan_id=trip_id,
            added_by_user_id=current_user.id,
            vertical=vertical,
            item_data_json=item_data_str,
            day_number=day_number,
            votes_json=json.dumps({}),
            status="proposed",
        )
        db.session.add(item)
        db.session.commit()

        logger.info("Trip item added: trip=%d item=%d vertical=%s by user=%d", trip_id, item.id, vertical, current_user.id)
        return jsonify({"success": True, "item_id": item.id})

    # ------------------------------------------------------------------
    # 7. DELETE /api/trips/<trip_id>/items/<item_id> — Remove item
    # ------------------------------------------------------------------
    @app.route("/api/trips/<int:trip_id>/items/<int:item_id>", methods=["DELETE"])
    @csrf.exempt
    @login_required
    def api_remove_trip_item(trip_id, item_id):
        """Remove an item from a trip. Must be a member."""
        trip = _can_access_trip(trip_id)
        if not trip:
            return jsonify({"success": False, "error": "Trip not found or access denied."}), 404

        item = TripItem.query.filter_by(id=item_id, trip_plan_id=trip_id).first()
        if not item:
            return jsonify({"success": False, "error": "Item not found."}), 404

        db.session.delete(item)
        db.session.commit()
        logger.info("Trip item removed: trip=%d item=%d by user=%d", trip_id, item_id, current_user.id)
        return jsonify({"success": True})

    # ------------------------------------------------------------------
    # 8. POST /api/trips/<trip_id>/items/<item_id>/vote — Vote on item
    # ------------------------------------------------------------------
    @app.route("/api/trips/<int:trip_id>/items/<int:item_id>/vote", methods=["POST"])
    @csrf.exempt
    @login_required
    def api_vote_trip_item(trip_id, item_id):
        """Vote up or down on a trip item."""
        trip = _can_access_trip(trip_id)
        if not trip:
            return jsonify({"success": False, "error": "Trip not found or access denied."}), 404

        item = TripItem.query.filter_by(id=item_id, trip_plan_id=trip_id).first()
        if not item:
            return jsonify({"success": False, "error": "Item not found."}), 404

        data = request.get_json(silent=True) or {}
        vote = data.get("vote")
        if vote not in ("up", "down"):
            return jsonify({"success": False, "error": "Vote must be 'up' or 'down'."}), 400

        # Load existing votes
        try:
            votes = json.loads(item.votes_json) if item.votes_json else {}
        except (json.JSONDecodeError, TypeError):
            votes = {}

        user_key = str(current_user.id)

        # Toggle: if user already voted same way, remove vote
        if votes.get(user_key) == vote:
            del votes[user_key]
        else:
            votes[user_key] = vote

        item.votes_json = json.dumps(votes)
        db.session.commit()

        # Compute counts for response
        up_count = sum(1 for v in votes.values() if v == "up")
        down_count = sum(1 for v in votes.values() if v == "down")

        return jsonify({
            "success": True,
            "votes": {"up": up_count, "down": down_count},
            "my_vote": votes.get(user_key),
        })

    # ------------------------------------------------------------------
    # 9. POST /api/trips/<trip_id>/invite — Invite friend
    # ------------------------------------------------------------------
    @app.route("/api/trips/<int:trip_id>/invite", methods=["POST"])
    @csrf.exempt
    @login_required
    def api_invite_trip_member(trip_id):
        """Invite a friend to a trip by email or user_id."""
        trip = _can_access_trip(trip_id)
        if not trip:
            return jsonify({"success": False, "error": "Trip not found or access denied."}), 404

        data = request.get_json(silent=True) or {}
        from models import User

        target_user = None

        if data.get("user_id"):
            target_user = db.session.get(User, int(data["user_id"]))
        elif data.get("email"):
            email = data["email"].strip().lower()
            target_user = User.query.filter_by(email=email).first()

        if not target_user:
            return jsonify({"success": False, "error": "User not found. They need a MYSTES account first."}), 404

        if target_user.id == current_user.id:
            return jsonify({"success": False, "error": "You are already in this trip."}), 400

        # Check if already a member
        existing = TripMember.query.filter_by(
            trip_plan_id=trip_id, user_id=target_user.id
        ).first()
        if existing:
            return jsonify({"success": False, "error": "This person is already a member of the trip."}), 400

        member = TripMember(
            trip_plan_id=trip_id,
            user_id=target_user.id,
            role="editor",
            invitation_status="pending",
        )
        db.session.add(member)
        db.session.commit()

        logger.info("Trip invite: trip=%d invited_user=%d by user=%d", trip_id, target_user.id, current_user.id)

        # Send email notification (best-effort, non-blocking)
        try:
            from email_service import send_trip_invite_email
            send_trip_invite_email(
                to=target_user.email,
                inviter_name=current_user.name or current_user.email,
                trip_name=trip.name,
                trip_id=trip_id,
                to_name=target_user.name,
            )
        except Exception as _email_err:
            logger.debug("Trip invite email failed (non-critical): %s", _email_err)

        return jsonify({
            "success": True,
            "member_id": member.id,
            "user_name": target_user.name or target_user.email,
        })

    # ------------------------------------------------------------------
    # 10. GET /api/trips/<trip_id>/cart — Compute trip cart
    # ------------------------------------------------------------------
    @app.route("/api/trips/<int:trip_id>/cart")
    @csrf.exempt
    @login_required
    def api_trip_cart(trip_id):
        """Compute trip cart: sum all item prices, divide per person."""
        trip = _can_access_trip(trip_id)
        if not trip:
            return jsonify({"success": False, "error": "Trip not found or access denied."}), 404

        items = TripItem.query.filter_by(trip_plan_id=trip_id).all()
        members = TripMember.query.filter_by(trip_plan_id=trip_id).all()

        total_cost = 0.0
        item_details = []
        for item in items:
            try:
                idata = json.loads(item.item_data_json) if item.item_data_json else {}
                price = float(idata.get("price", 0))
            except (json.JSONDecodeError, TypeError, ValueError):
                price = 0.0
            total_cost += price
            item_details.append({
                "id": item.id,
                "vertical": item.vertical,
                "day_number": item.day_number,
                "price": price,
                "title": idata.get("title", idata.get("name", item.vertical)),
            })

        member_count = len(members)
        per_person = total_cost / member_count if member_count > 0 else total_cost

        return jsonify({
            "success": True,
            "trip_id": trip_id,
            "item_count": len(items),
            "total_cost": round(total_cost, 2),
            "member_count": member_count,
            "per_person": round(per_person, 2),
            "currency": "USD",
            "items": item_details,
        })

    # ------------------------------------------------------------------
    # 11. POST /api/trips/<trip_id>/duplicate — Duplicate trip (Build #185)
    # ------------------------------------------------------------------
    @app.route("/api/trips/<int:trip_id>/duplicate", methods=["POST"])
    @csrf.exempt
    @login_required
    def api_trip_duplicate(trip_id):
        """Duplicate a trip as a new draft (template copy)."""
        trip = _can_access_trip(trip_id)
        if not trip:
            return jsonify({"success": False, "error": "Trip not found or access denied."}), 404

        new_trip = TripPlan(
            creator_id=current_user.id,
            name=f"{trip.name} (Copy)",
            description=trip.description,
            destinations_json=trip.destinations_json,
            status="draft",
        )
        db.session.add(new_trip)
        db.session.flush()

        # Copy owner as member
        owner_member = TripMember(
            trip_plan_id=new_trip.id,
            user_id=current_user.id,
            role="owner",
            invitation_status="accepted",
            joined_at=datetime.now(),
        )
        db.session.add(owner_member)

        # Copy all items
        items = TripItem.query.filter_by(trip_plan_id=trip_id).all()
        for item in items:
            new_item = TripItem(
                trip_plan_id=new_trip.id,
                added_by_user_id=current_user.id,
                vertical=item.vertical,
                item_data_json=item.item_data_json,
                destination_index=item.destination_index,
                day_number=item.day_number,
                status="proposed",
            )
            db.session.add(new_item)

        # Increment template copy count on source
        if trip.is_template:
            trip.template_copies_count = (trip.template_copies_count or 0) + 1

        db.session.commit()

        return jsonify({
            "success": True,
            "trip_id": new_trip.id,
            "name": new_trip.name,
        })

    # ------------------------------------------------------------------
    # 12. GET /api/trips/<trip_id>/budget — Budget check (Build #185)
    # ------------------------------------------------------------------
    @app.route("/api/trips/<int:trip_id>/budget")
    @csrf.exempt
    @login_required
    def api_trip_budget(trip_id):
        """Check trip budget status per member."""
        trip = _can_access_trip(trip_id)
        if not trip:
            return jsonify({"success": False, "error": "Trip not found or access denied."}), 404

        items = TripItem.query.filter_by(trip_plan_id=trip_id).all()
        members = TripMember.query.filter_by(trip_plan_id=trip_id).all()

        total_cost = 0.0
        for item in items:
            try:
                idata = json.loads(item.item_data_json) if item.item_data_json else {}
                total_cost += float(idata.get("price", 0))
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

        member_count = len(members) or 1
        per_person = total_cost / member_count

        budget_status = []
        for member in members:
            cap = member.budget_cap
            over_budget = cap is not None and per_person > cap
            budget_status.append({
                "user_id": member.user_id,
                "role": member.role,
                "budget_cap": cap,
                "share": round(per_person, 2),
                "over_budget": over_budget,
            })

        return jsonify({
            "success": True,
            "trip_id": trip_id,
            "total_cost": round(total_cost, 2),
            "per_person": round(per_person, 2),
            "member_budgets": budget_status,
            "any_over_budget": any(b["over_budget"] for b in budget_status),
        })

    # ------------------------------------------------------------------
    # 13. GET /api/trips/<trip_id>/activity — Trip activity feed (Build #185)
    # ------------------------------------------------------------------
    @app.route("/api/trips/<int:trip_id>/activity")
    @csrf.exempt
    @login_required
    def api_trip_activity(trip_id):
        """Get trip activity feed (recent items, votes, members)."""
        trip = _can_access_trip(trip_id)
        if not trip:
            return jsonify({"success": False, "error": "Trip not found or access denied."}), 404

        from models import User

        # Recent items (last 20)
        items = TripItem.query.filter_by(trip_plan_id=trip_id)\
            .order_by(TripItem.created_at.desc()).limit(20).all()

        activity = []
        for item in items:
            user = db.session.get(User, item.added_by_user_id)
            idata = {}
            try:
                idata = json.loads(item.item_data_json) if item.item_data_json else {}
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
            activity.append({
                "type": "item_added",
                "user_name": user.name or user.email if user else "Unknown",
                "vertical": item.vertical,
                "title": idata.get("title", idata.get("name", item.vertical)),
                "day_number": item.day_number,
                "status": item.status,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            })

        # Recent members
        members = TripMember.query.filter_by(trip_plan_id=trip_id)\
            .order_by(TripMember.invited_at.desc()).all()
        for member in members:
            user = db.session.get(User, member.user_id)
            activity.append({
                "type": "member_joined" if member.invitation_status == "accepted" else "member_invited",
                "user_name": user.name or user.email if user else "Unknown",
                "role": member.role,
                "created_at": (member.joined_at or member.invited_at).isoformat() if (member.joined_at or member.invited_at) else None,
            })

        # Sort by time
        activity.sort(key=lambda x: x.get("created_at") or "", reverse=True)

        return jsonify({"success": True, "activity": activity[:30]})

    # ------------------------------------------------------------------
    # 14. PUT /api/trips/<trip_id>/items/<item_id>/status — Update item status (Build #185)
    # ------------------------------------------------------------------
    @app.route("/api/trips/<int:trip_id>/items/<int:item_id>/status", methods=["PUT"])
    @csrf.exempt
    @login_required
    def api_trip_item_status(trip_id, item_id):
        """Update a trip item's status (proposed/approved/booked/cancelled)."""
        trip = _can_access_trip(trip_id)
        if not trip:
            return jsonify({"success": False, "error": "Trip not found or access denied."}), 404

        item = TripItem.query.filter_by(id=item_id, trip_plan_id=trip_id).first()
        if not item:
            return jsonify({"success": False, "error": "Item not found."}), 404

        # Only owner/editor can change status
        role = _get_member_role(trip_id, current_user.id)
        if trip.creator_id != current_user.id and role not in ("owner", "editor"):
            return jsonify({"success": False, "error": "Only trip owners and editors can change item status."}), 403

        data = request.get_json(silent=True) or {}
        new_status = data.get("status")
        if new_status not in ("proposed", "approved", "booked", "cancelled"):
            return jsonify({"success": False, "error": "Invalid status."}), 400

        item.status = new_status
        db.session.commit()

        return jsonify({"success": True, "item_id": item.id, "status": new_status})

    # ------------------------------------------------------------------
    # 15. POST /api/trips/<trip_id>/checkout — One person pays all (Build #209)
    # ------------------------------------------------------------------
    @app.route("/api/trips/<int:trip_id>/checkout", methods=["POST"])
    @csrf.exempt
    @login_required
    def api_trip_checkout(trip_id):
        """Trip checkout: one person pays, splits tracked for reimbursement (Build #209).

        Proxy booking = single cardholder on airline end.
        Splitting operates ONLY on the MYSTES service fee layer.
        """
        from payments import get_fee_percent

        trip = _can_access_trip(trip_id)
        if not trip:
            return jsonify({"success": False, "error": "Trip not found or access denied."}), 404

        if trip.status not in ('draft', 'finalized'):
            return jsonify({"success": False, "error": f"Trip already in status: {trip.status}"}), 400

        items = TripItem.query.filter_by(trip_plan_id=trip_id).all()
        if not items:
            return jsonify({"success": False, "error": "No items in trip."}), 400

        members = TripMember.query.filter_by(trip_plan_id=trip_id).all()
        member_count = max(len(members), 1)

        # Calculate total cost
        total_cost = 0.0
        for item in items:
            try:
                idata = json.loads(item.item_data_json) if item.item_data_json else {}
                price = float(idata.get("price", 0))
            except (json.JSONDecodeError, TypeError, ValueError):
                price = 0.0
            total_cost += price

        # Calculate service fee
        user = current_user
        fee_pct = get_fee_percent(user)

        # Service fee on total savings, $3 min, NO max cap
        total_savings = 0.0
        for item in items:
            try:
                idata = json.loads(item.item_data_json) if item.item_data_json else {}
                savings = float(idata.get("savings", 0))
            except (json.JSONDecodeError, TypeError, ValueError):
                savings = 0.0
            total_savings += savings

        if total_savings > 0:
            service_fee = max(total_savings * fee_pct, 3.0)
        else:
            service_fee = max(total_cost * fee_pct, 3.0)
        service_fee = round(service_fee, 2)

        per_person_fee = round(service_fee / member_count, 2)

        # Create TripCart
        cart = TripCart(
            trip_plan_id=trip_id,
            status='checkout',
            total_amount=service_fee,
        )
        db.session.add(cart)
        db.session.flush()

        # Create TripCartAssignment for each member
        for member in members:
            is_payer = (member.user_id == current_user.id)
            assignment = TripCartAssignment(
                trip_cart_id=cart.id,
                trip_item_id=items[0].id,
                user_id=member.user_id,
                payer_id=current_user.id,
                split_method='even',
                amount_owed=per_person_fee,
                percentage=round(100.0 / member_count, 2),
                payment_status='paid' if is_payer else 'pending',
            )
            db.session.add(assignment)

        # If only member is the payer, handle solo trips
        if member_count == 1 or (member_count == len([m for m in members if m.user_id == current_user.id])):
            cart.status = 'paid'

        # Stripe PaymentIntent for full service fee
        data = request.get_json(silent=True) or {}
        payment_method_id = data.get("payment_method_id")

        stripe_pi_id = None
        if payment_method_id and service_fee > 0:
            try:
                import stripe
                stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
                pi = stripe.PaymentIntent.create(
                    amount=int(service_fee * 100),
                    currency="usd",
                    payment_method=payment_method_id,
                    confirm=True,
                    description=f"MYSTES trip — {trip.name}",
                    metadata={"trip_id": str(trip_id), "type": "trip_checkout"},
                    automatic_payment_methods={"enabled": True, "allow_redirects": "never"},
                )
                stripe_pi_id = pi.id
                cart.status = 'paid'
            except Exception as stripe_err:
                logger.error("[TripCheckout] Stripe: %s", stripe_err)
                cart.status = 'checkout'
                db.session.commit()
                return jsonify({"success": False, "error": "Payment failed"}), 402

        trip.status = 'booked'
        cart.finalized_at = datetime.now(timezone.utc)
        db.session.commit()

        # Build balance sheet
        balances = []
        for member in members:
            assignment = TripCartAssignment.query.filter_by(
                trip_cart_id=cart.id, user_id=member.user_id
            ).first()
            user_obj = User.query.get(member.user_id)
            balances.append({
                "user_id": member.user_id,
                "name": user_obj.name if user_obj else "Unknown",
                "amount_owed": assignment.amount_owed if assignment else 0,
                "status": assignment.payment_status if assignment else "pending",
            })

        return jsonify({
            "success": True,
            "trip_id": trip_id,
            "cart_id": cart.id,
            "total_service_fee": service_fee,
            "per_person": per_person_fee,
            "member_count": member_count,
            "stripe_pi_id": stripe_pi_id,
            "balances": balances,
        })

    # ------------------------------------------------------------------
    # 16. POST /api/trips/<trip_id>/settle-up/request — Send payment requests (Build #209)
    # ------------------------------------------------------------------
    @app.route("/api/trips/<int:trip_id>/settle-up/request", methods=["POST"])
    @csrf.exempt
    @login_required
    def api_trip_settle_request(trip_id):
        """Send settle-up payment requests to trip members (Build #209)."""
        trip = _can_access_trip(trip_id)
        if not trip:
            return jsonify({"success": False, "error": "Trip not found or access denied."}), 404

        cart = TripCart.query.filter_by(trip_plan_id=trip_id).order_by(TripCart.id.desc()).first()
        if not cart:
            return jsonify({"success": False, "error": "No checkout found for this trip."}), 404

        # Find unpaid assignments where current user is the payer
        assignments = TripCartAssignment.query.filter_by(
            trip_cart_id=cart.id, payer_id=current_user.id
        ).filter(
            TripCartAssignment.payment_status.in_(['pending']),
            TripCartAssignment.user_id != current_user.id,
        ).all()

        requested_count = 0
        for assignment in assignments:
            assignment.payment_status = 'requested'
            requested_count += 1

        db.session.commit()

        return jsonify({
            "success": True,
            "requested_count": requested_count,
        })

    # ------------------------------------------------------------------
    # 17. POST /api/trips/<trip_id>/settle-up/pay — Member pays their share (Build #209)
    # ------------------------------------------------------------------
    @app.route("/api/trips/<int:trip_id>/settle-up/pay", methods=["POST"])
    @csrf.exempt
    @login_required
    def api_trip_settle_pay(trip_id):
        """Member pays their share of the trip service fee (Build #209).

        Money goes to MYSTES. Payer reimbursement = future Stripe Connect feature.
        """
        trip = _can_access_trip(trip_id)
        if not trip:
            return jsonify({"success": False, "error": "Trip not found or access denied."}), 404

        cart = TripCart.query.filter_by(trip_plan_id=trip_id).order_by(TripCart.id.desc()).first()
        if not cart:
            return jsonify({"success": False, "error": "No checkout found."}), 404

        # Find this user's unpaid assignments
        assignments = TripCartAssignment.query.filter_by(
            trip_cart_id=cart.id, user_id=current_user.id,
        ).filter(
            TripCartAssignment.payment_status.in_(['pending', 'requested']),
        ).all()

        if not assignments:
            return jsonify({"success": False, "error": "No pending balance found."}), 400

        total_owed = sum(a.amount_owed for a in assignments)
        total_owed = round(total_owed, 2)

        data = request.get_json(silent=True) or {}
        payment_method_id = data.get("payment_method_id")

        if not payment_method_id:
            return jsonify({"success": False, "error": "payment_method_id required"}), 400

        # Charge via Stripe
        try:
            import stripe
            stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
            pi = stripe.PaymentIntent.create(
                amount=int(total_owed * 100),
                currency="usd",
                payment_method=payment_method_id,
                confirm=True,
                description=f"MYSTES trip settle-up — {trip.name}",
                metadata={"trip_id": str(trip_id), "user_id": str(current_user.id), "type": "settle_up"},
                automatic_payment_methods={"enabled": True, "allow_redirects": "never"},
            )

            for assignment in assignments:
                assignment.payment_status = 'paid'
                assignment.stripe_payment_intent_id = pi.id

            db.session.commit()

            return jsonify({
                "success": True,
                "amount_paid": total_owed,
                "stripe_pi_id": pi.id,
            })
        except Exception as stripe_err:
            logger.error("[TripSettleUp] Stripe: %s", stripe_err)
            return jsonify({"success": False, "error": "Payment failed"}), 402

    # ------------------------------------------------------------------
    # 18. GET /api/trips/<trip_id>/balances — Who owes what (Build #209)
    # ------------------------------------------------------------------
    @app.route("/api/trips/<int:trip_id>/balances")
    @csrf.exempt
    @login_required
    def api_trip_balances(trip_id):
        """Get balance sheet for trip — who owes what (Build #209)."""
        trip = _can_access_trip(trip_id)
        if not trip:
            return jsonify({"success": False, "error": "Trip not found or access denied."}), 404

        cart = TripCart.query.filter_by(trip_plan_id=trip_id).order_by(TripCart.id.desc()).first()
        if not cart:
            return jsonify({
                "success": True,
                "trip_id": trip_id,
                "checked_out": False,
                "total_service_fee": 0,
                "balances": [],
            })

        assignments = TripCartAssignment.query.filter_by(trip_cart_id=cart.id).all()
        members = TripMember.query.filter_by(trip_plan_id=trip_id).all()
        member_count = max(len(members), 1)
        per_person = round(cart.total_amount / member_count, 2) if cart.total_amount else 0

        balances = []
        for assignment in assignments:
            user_obj = User.query.get(assignment.user_id)
            balances.append({
                "user_id": assignment.user_id,
                "name": user_obj.name if user_obj else "Unknown",
                "amount_owed": round(assignment.amount_owed, 2),
                "status": assignment.payment_status,
                "is_payer": assignment.payer_id == assignment.user_id,
            })

        payer = User.query.get(assignments[0].payer_id) if assignments else None

        return jsonify({
            "success": True,
            "trip_id": trip_id,
            "checked_out": True,
            "total_service_fee": round(cart.total_amount, 2),
            "per_person": per_person,
            "payer": {
                "user_id": payer.id if payer else None,
                "name": payer.name if payer else "Unknown",
            },
            "balances": balances,
        })

    logger.info("Trip planner routes registered (incl. Build #209 splitting)")
