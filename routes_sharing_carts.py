"""
Builds #228-229 — Narrative Pitch Generator + SharedCart (Pay-For-Someone)

All endpoints gated behind FeatureFlag checks (narrative_pitch, shared_cart).
Admin enables flags when Phase C launches.

Endpoints:
  Narrative Pitch (#228):
  - GET    /api/trips/<id>/narrative             — personalized narrative for current user
  - GET    /api/trips/<id>/narrative/<gid>       — narrative for specific guest (admin only)

  SharedCart (#229):
  - POST   /api/trips/<id>/carts               — create shared cart from items
  - GET    /api/trips/<id>/carts               — list carts for this trip
  - GET    /api/carts/<token>                  — view cart by token (NO AUTH — guest access)
  - PUT    /api/carts/<token>                  — update cart (builder only)
  - POST   /api/carts/<token>/share            — mark as shared + generate InviteLink
  - POST   /api/carts/<token>/pay              — record payment info (guest access)
  - DELETE /api/carts/<token>                  — delete draft cart (builder only)

Registration: register_sharing_cart_routes(app, csrf, limiter)
"""

import json
import logging
import secrets
from datetime import datetime, timezone, timedelta

from flask import request, jsonify
from flask_login import current_user, login_required

from models import (
    db, FeatureFlag, TripPlan, TripMember, TripGuest,
    ItineraryItem, SharedCart, InviteLink,
)

logger = logging.getLogger(__name__)


def _utcnow():
    return datetime.now(timezone.utc)


def _is_expired(dt):
    """Check if a datetime is in the past, handling naive/aware comparison."""
    if dt is None:
        return False
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        # Treat naive datetimes as UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt < now


def _check_flag(flag_key):
    """Return error response if flag is disabled, else None."""
    if not FeatureFlag.is_flag_enabled(flag_key):
        return jsonify({
            'status': 'error',
            'error': f'Feature "{flag_key}" is not enabled',
        }), 403
    return None


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
        if require_edit and guest.role in ('viewer', 'payer'):
            return None, (jsonify({'status': 'error', 'error': 'Edit access required'}), 403)
        return trip, None

    if require_edit and member.role == 'viewer':
        return None, (jsonify({'status': 'error', 'error': 'Edit access required'}), 403)

    return trip, None


def _generate_cart_token():
    """Generate a unique cart token."""
    for _ in range(10):
        token = secrets.token_urlsafe(12)[:16]
        if not SharedCart.query.filter_by(cart_token=token).first():
            return token
    return secrets.token_urlsafe(16)[:16]


# ================================================================
# Build #228: Narrative Pitch Generator
# ================================================================

# Template pools per item type — randomized slightly for variety
_ARRIVAL_TEMPLATES = [
    "{guests} arrive in {destination} on {date}.",
    "{guests} touch down in {destination} on {date}.",
    "{guests} land in {destination} on {date} — the adventure begins.",
    "On {date}, {guests} arrive in {destination} ready for an unforgettable trip.",
]

_HOTEL_TEMPLATES = [
    "Check into {hotel_name} and settle in for the stay.",
    "Home base: {hotel_name}. Drop the bags and get ready to explore.",
    "Settle into {hotel_name} — your home away from home.",
    "Head to {hotel_name} to check in and freshen up.",
]

_ACTIVITY_TEMPLATES = [
    "{time_prefix}{name} — a highlight of the day.",
    "{time_prefix}Time for {name}.",
    "{time_prefix}{name} is on the agenda.",
    "{time_prefix}Don't miss {name}.",
]

_RESTAURANT_TEMPLATES = [
    "{time_prefix}Grab a meal at {name}.",
    "{time_prefix}Dinner at {name} — enjoy!",
    "{time_prefix}Head to {name} for a great bite.",
]

_CAR_TEMPLATES = [
    "Pick up the rental car and hit the road.",
    "Grab the rental and start exploring on your own terms.",
]

_CUSTOM_TEMPLATES = [
    "{time_prefix}{name}.",
]

_FREE_DAY_TEMPLATES = [
    "A free day to explore {destination} at your own pace.",
    "No plans today — wander, relax, or discover something unexpected in {destination}.",
    "The day is yours. Explore {destination} however you like.",
]

_DEPARTURE_TEMPLATES = [
    "{guests} depart {destination} on {date}. Until next time!",
    "On {date}, it's time to head home from {destination}.",
    "{date}: farewell, {destination}. What a trip.",
]


def _pick_template(templates, seed_val):
    """Pick a template deterministically from a pool based on seed value."""
    return templates[seed_val % len(templates)]


def _format_guest_names(guest_names, perspective_name=None):
    """Format guest names from the perspective of a specific guest.

    If perspective_name is set, replace it with "You" and put it first.
    """
    if not guest_names:
        return "Everyone"

    names = list(guest_names)
    if perspective_name and perspective_name in names:
        names.remove(perspective_name)
        names = ["You"] + names

    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + f", and {names[-1]}"


def _get_destination_from_items(items):
    """Extract primary destination from flight items."""
    for item in items:
        if item.item_type == 'flight' and item.search_params_json:
            try:
                params = json.loads(item.search_params_json)
                return params.get('destination', 'your destination')
            except (json.JSONDecodeError, TypeError):
                pass
    return "your destination"


def _build_narrative(trip, guest_id=None, perspective_name=None):
    """Build a template-based day-by-day narrative for a trip.

    If guest_id is provided, personalizes for that guest's perspective.
    Returns dict with 'narrative' (full text) and 'days' (structured).
    """
    items = ItineraryItem.query.filter_by(trip_id=trip.id).order_by(
        ItineraryItem.date, ItineraryItem.position
    ).all()

    if not items:
        return {
            'narrative': f"Your trip \"{trip.name}\" is being planned. Add some items to see the story unfold!",
            'days': [],
            'item_count': 0,
        }

    # Gather all guest names for this trip
    guests = TripGuest.query.filter_by(trip_id=trip.id).all()
    all_guest_names = [g.display_name for g in guests]
    destination = _get_destination_from_items(items)

    # Group items by date
    days = {}
    dateless_items = []
    for item in items:
        if item.date:
            key = item.date.isoformat()
            if key not in days:
                days[key] = []
            days[key].append(item)
        else:
            dateless_items.append(item)

    sorted_dates = sorted(days.keys())
    narrative_parts = []
    day_structures = []

    for day_idx, date_str in enumerate(sorted_dates):
        day_items = days[date_str]
        day_lines = []
        day_label = f"Day {day_idx + 1} — {date_str}"

        for item in day_items:
            seed = item.id if item.id else day_idx
            time_prefix = f"At {item.start_time}, " if item.start_time else ""

            # Determine which guests are involved (scope-based)
            if item.scope == 'trip':
                involved = _format_guest_names(all_guest_names, perspective_name)
            elif item.scope == 'party' and item.scope_party_id:
                party_guests = TripGuest.query.filter_by(
                    trip_id=trip.id, party_id=item.scope_party_id
                ).all()
                involved = _format_guest_names(
                    [g.display_name for g in party_guests], perspective_name
                )
            elif item.scope == 'individual' and item.assigned_to_guest_id:
                assigned = db.session.get(TripGuest, item.assigned_to_guest_id)
                involved = assigned.display_name if assigned else "Someone"
                if perspective_name and involved == perspective_name:
                    involved = "You"
            else:
                involved = _format_guest_names(all_guest_names, perspective_name)

            # Generate line based on item type
            if item.item_type == 'flight':
                # First flight of trip = arrival, last = departure
                params = {}
                if item.search_params_json:
                    try:
                        params = json.loads(item.search_params_json)
                    except (json.JSONDecodeError, TypeError):
                        pass
                dest = params.get('destination', destination)
                if day_idx == 0:
                    tmpl = _pick_template(_ARRIVAL_TEMPLATES, seed)
                    line = tmpl.format(guests=involved, destination=dest, date=date_str)
                else:
                    tmpl = _pick_template(_DEPARTURE_TEMPLATES, seed)
                    line = tmpl.format(guests=involved, destination=dest, date=date_str)
            elif item.item_type == 'hotel':
                name = item.external_name or "your hotel"
                tmpl = _pick_template(_HOTEL_TEMPLATES, seed)
                line = tmpl.format(hotel_name=name)
            elif item.item_type == 'activity':
                name = item.external_name or item.notes or "an activity"
                tmpl = _pick_template(_ACTIVITY_TEMPLATES, seed)
                line = tmpl.format(time_prefix=time_prefix, name=name)
            elif item.item_type == 'restaurant':
                name = item.external_name or item.notes or "a local spot"
                tmpl = _pick_template(_RESTAURANT_TEMPLATES, seed)
                line = tmpl.format(time_prefix=time_prefix, name=name)
            elif item.item_type == 'car':
                tmpl = _pick_template(_CAR_TEMPLATES, seed)
                line = tmpl.format()
            else:
                name = item.external_name or item.notes or "something special"
                tmpl = _pick_template(_CUSTOM_TEMPLATES, seed)
                line = tmpl.format(time_prefix=time_prefix, name=name)
                # Prepend scope context for non-trip scoped items
                if item.scope == 'individual' and involved != "Everyone":
                    line = f"{involved}: {line}"

            day_lines.append(line)

        # If no items for a day but it's between start/end, it's a free day
        if not day_lines:
            tmpl = _pick_template(_FREE_DAY_TEMPLATES, day_idx)
            day_lines.append(tmpl.format(destination=destination))

        day_structures.append({
            'day_number': day_idx + 1,
            'date': date_str,
            'lines': day_lines,
        })
        narrative_parts.append(f"**{day_label}**\n" + "\n".join(day_lines))

    # Add dateless items as "Anytime" section
    if dateless_items:
        anytime_lines = []
        for item in dateless_items:
            name = item.external_name or item.notes or item.item_type
            anytime_lines.append(f"- {name}")
        narrative_parts.append("**Anytime**\n" + "\n".join(anytime_lines))
        day_structures.append({
            'day_number': None,
            'date': None,
            'lines': anytime_lines,
        })

    return {
        'narrative': "\n\n".join(narrative_parts),
        'days': day_structures,
        'item_count': len(items),
        'destination': destination,
    }


# ================================================================
# Route Registration
# ================================================================

def register_sharing_cart_routes(app, csrf, limiter):
    """Register narrative pitch + shared cart routes (Builds #228-229)."""

    # ──────────────────────────────────────────────
    # NARRATIVE PITCH (Build #228)
    # ──────────────────────────────────────────────

    @app.route('/api/trips/<int:trip_id>/narrative', methods=['GET'])
    @login_required
    def get_trip_narrative(trip_id):
        """Generate personalized narrative for current user's guest perspective."""
        flag_err = _check_flag('narrative_pitch')
        if flag_err:
            return flag_err

        trip, err = _check_trip_access(trip_id)
        if err:
            return err

        # Find current user's guest record for personalization
        guest = TripGuest.query.filter_by(
            trip_id=trip_id, user_id=current_user.id
        ).first()
        perspective_name = guest.display_name if guest else current_user.name

        result = _build_narrative(trip, perspective_name=perspective_name)
        return jsonify({
            'status': 'ok',
            'trip_id': trip_id,
            'trip_name': trip.name,
            'perspective': perspective_name,
            **result,
        })

    @app.route('/api/trips/<int:trip_id>/narrative/<int:guest_id>', methods=['GET'])
    @login_required
    def get_guest_narrative(trip_id, guest_id):
        """Generate narrative from a specific guest's perspective (admin only)."""
        flag_err = _check_flag('narrative_pitch')
        if flag_err:
            return flag_err

        trip, err = _check_trip_access(trip_id)
        if err:
            return err

        # Only trip creator can view other guests' narratives
        if trip.creator_id != current_user.id:
            return jsonify({'status': 'error', 'error': 'Only trip creator can view guest narratives'}), 403

        guest = db.session.get(TripGuest, guest_id)
        if not guest or guest.trip_id != trip_id:
            return jsonify({'status': 'error', 'error': 'Guest not found'}), 404

        result = _build_narrative(trip, guest_id=guest.id, perspective_name=guest.display_name)
        return jsonify({
            'status': 'ok',
            'trip_id': trip_id,
            'trip_name': trip.name,
            'guest_id': guest_id,
            'perspective': guest.display_name,
            **result,
        })

    # ──────────────────────────────────────────────
    # SHARED CART (Build #229)
    # ──────────────────────────────────────────────

    @app.route('/api/trips/<int:trip_id>/carts', methods=['POST'])
    @login_required
    def create_shared_cart(trip_id):
        """Create a shared cart from trip itinerary items."""
        flag_err = _check_flag('shared_cart')
        if flag_err:
            return flag_err

        trip, err = _check_trip_access(trip_id, require_edit=True)
        if err:
            return err

        data = request.get_json(silent=True) or {}
        title = data.get('title', '').strip()
        if not title:
            return jsonify({'status': 'error', 'error': 'title is required'}), 400

        # Validate item_ids if provided
        item_ids = data.get('item_ids', [])
        items_snapshot = []
        total = 0.0
        for iid in item_ids:
            item = db.session.get(ItineraryItem, iid)
            if item and item.trip_id == trip_id:
                price = item.cached_price_usd or item.external_cost_usd or 0.0
                items_snapshot.append({
                    'item_id': item.id,
                    'item_type': item.item_type,
                    'name': item.external_name or item.notes or item.item_type,
                    'price_usd': round(price, 2),
                    'date': item.date.isoformat() if item.date else None,
                })
                total += price

        # Allow empty carts (items added later)
        message = data.get('message', '').strip() or None
        expires_hours = data.get('expires_hours', 72)
        try:
            expires_hours = int(expires_hours)
        except (ValueError, TypeError):
            expires_hours = 72

        cart = SharedCart(
            cart_token=_generate_cart_token(),
            trip_id=trip_id,
            builder_user_id=current_user.id,
            title=title,
            message=message,
            items_json=json.dumps(items_snapshot),
            reprice_at_checkout=data.get('reprice_at_checkout', True),
            total_estimated_usd=round(total, 2),
            payment_status='draft',
            expires_at=_utcnow() + timedelta(hours=expires_hours),
        )
        db.session.add(cart)
        db.session.commit()

        return jsonify({
            'status': 'ok',
            'cart': cart.to_dict(include_message=True),
        })

    @app.route('/api/trips/<int:trip_id>/carts', methods=['GET'])
    @login_required
    def list_shared_carts(trip_id):
        """List shared carts for this trip."""
        flag_err = _check_flag('shared_cart')
        if flag_err:
            return flag_err

        trip, err = _check_trip_access(trip_id)
        if err:
            return err

        carts = SharedCart.query.filter_by(trip_id=trip_id).order_by(
            SharedCart.created_at.desc()
        ).all()

        return jsonify({
            'status': 'ok',
            'carts': [c.to_dict() for c in carts],
            'count': len(carts),
        })

    @app.route('/api/carts/<token>', methods=['GET'])
    def view_shared_cart(token):
        """View a shared cart by token — NO AUTH REQUIRED (guest access).

        This is the endpoint payers see when they click the shared link.
        Only shows cart details for shared/repriced status carts.
        """
        cart = SharedCart.query.filter_by(cart_token=token).first()
        if not cart:
            return jsonify({'status': 'error', 'error': 'Cart not found'}), 404

        # Check expiry
        if _is_expired(cart.expires_at):
            if cart.payment_status not in ('paid',):
                cart.payment_status = 'expired'
                db.session.commit()
            return jsonify({'status': 'error', 'error': 'Cart has expired'}), 410

        # Draft carts are only visible to builder
        if cart.payment_status == 'draft':
            if not current_user.is_authenticated or current_user.id != cart.builder_user_id:
                return jsonify({'status': 'error', 'error': 'Cart not yet shared'}), 403

        return jsonify({
            'status': 'ok',
            'cart': cart.to_dict(include_message=True),
            'builder_name': cart.builder.name if cart.builder else None,
        })

    @app.route('/api/carts/<token>', methods=['PUT'])
    @login_required
    def update_shared_cart(token):
        """Update a shared cart (builder only, draft/shared only)."""
        flag_err = _check_flag('shared_cart')
        if flag_err:
            return flag_err

        cart = SharedCart.query.filter_by(cart_token=token).first()
        if not cart:
            return jsonify({'status': 'error', 'error': 'Cart not found'}), 404
        if cart.builder_user_id != current_user.id:
            return jsonify({'status': 'error', 'error': 'Only cart builder can update'}), 403
        if cart.payment_status in ('paid', 'expired'):
            return jsonify({'status': 'error', 'error': f'Cannot update {cart.payment_status} cart'}), 400

        data = request.get_json(silent=True) or {}

        if 'title' in data:
            title = data['title'].strip()
            if title:
                cart.title = title
        if 'message' in data:
            cart.message = data['message'].strip() or None
        if 'reprice_at_checkout' in data:
            cart.reprice_at_checkout = bool(data['reprice_at_checkout'])

        # Update items if provided
        if 'item_ids' in data:
            items_snapshot = []
            total = 0.0
            for iid in data['item_ids']:
                item = db.session.get(ItineraryItem, iid)
                if item and item.trip_id == cart.trip_id:
                    price = item.cached_price_usd or item.external_cost_usd or 0.0
                    items_snapshot.append({
                        'item_id': item.id,
                        'item_type': item.item_type,
                        'name': item.external_name or item.notes or item.item_type,
                        'price_usd': round(price, 2),
                        'date': item.date.isoformat() if item.date else None,
                    })
                    total += price
            cart.items_json = json.dumps(items_snapshot)
            cart.total_estimated_usd = round(total, 2)

        db.session.commit()
        return jsonify({'status': 'ok', 'cart': cart.to_dict(include_message=True)})

    @app.route('/api/carts/<token>/share', methods=['POST'])
    @login_required
    def share_cart(token):
        """Mark cart as shared and generate an InviteLink for guest payment."""
        flag_err = _check_flag('shared_cart')
        if flag_err:
            return flag_err

        cart = SharedCart.query.filter_by(cart_token=token).first()
        if not cart:
            return jsonify({'status': 'error', 'error': 'Cart not found'}), 404
        if cart.builder_user_id != current_user.id:
            return jsonify({'status': 'error', 'error': 'Only cart builder can share'}), 403
        if cart.payment_status not in ('draft', 'shared'):
            return jsonify({'status': 'error', 'error': f'Cannot share {cart.payment_status} cart'}), 400

        cart.payment_status = 'shared'

        # Create InviteLink of type cart_checkout
        invite = InviteLink(
            token=secrets.token_urlsafe(8)[:10],
            link_type='cart_checkout',
            object_id=cart.id,
            sender_user_id=current_user.id,
            permissions='can_pay',
            message=cart.message,
            referral_code=getattr(current_user, 'referral_code', None),
        )
        db.session.add(invite)
        db.session.commit()

        return jsonify({
            'status': 'ok',
            'cart': cart.to_dict(),
            'share_token': invite.token,
            'share_url': f"/i/{invite.token}",
        })

    @app.route('/api/carts/<token>/pay', methods=['POST'])
    def pay_shared_cart(token):
        """Record payer info for a shared cart (NO AUTH — guest access).

        In production, this would create a Stripe Checkout session.
        For now, records payer info and marks as paid.
        """
        cart = SharedCart.query.filter_by(cart_token=token).first()
        if not cart:
            return jsonify({'status': 'error', 'error': 'Cart not found'}), 404

        if cart.payment_status not in ('shared', 'repriced'):
            return jsonify({
                'status': 'error',
                'error': f'Cart is {cart.payment_status}, cannot pay',
            }), 400

        # Check expiry
        if _is_expired(cart.expires_at):
            cart.payment_status = 'expired'
            db.session.commit()
            return jsonify({'status': 'error', 'error': 'Cart has expired'}), 410

        data = request.get_json(silent=True) or {}
        payer_email = data.get('payer_email', '').strip()
        payer_name = data.get('payer_name', '').strip()

        if not payer_email:
            return jsonify({'status': 'error', 'error': 'payer_email is required'}), 400

        cart.payer_email = payer_email
        cart.payer_name = payer_name or None
        cart.payment_status = 'paid'
        cart.paid_at = _utcnow()
        # In production: cart.stripe_session_id = stripe_session.id
        db.session.commit()

        return jsonify({
            'status': 'ok',
            'cart': cart.to_dict(),
            'message': 'Payment recorded. Booking will be processed under the trip builder\'s account.',
        })

    @app.route('/api/carts/<token>', methods=['DELETE'])
    @login_required
    def delete_shared_cart(token):
        """Delete a draft cart (builder only)."""
        flag_err = _check_flag('shared_cart')
        if flag_err:
            return flag_err

        cart = SharedCart.query.filter_by(cart_token=token).first()
        if not cart:
            return jsonify({'status': 'error', 'error': 'Cart not found'}), 404
        if cart.builder_user_id != current_user.id:
            return jsonify({'status': 'error', 'error': 'Only cart builder can delete'}), 403
        if cart.payment_status not in ('draft',):
            return jsonify({'status': 'error', 'error': 'Can only delete draft carts'}), 400

        db.session.delete(cart)
        db.session.commit()
        return jsonify({'status': 'ok', 'message': 'Cart deleted'})
