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

from flask import request, jsonify
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
