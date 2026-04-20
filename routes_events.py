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

from flask import request, jsonify
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


def register_event_routes(app, csrf, limiter):
    """Register managed mode + event routes (Builds #225-227)."""

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
