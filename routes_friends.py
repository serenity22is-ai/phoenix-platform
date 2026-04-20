"""
MYSTES Friends System — Social graph for trip planning and collections.

Register in server.py:
    from routes_friends import register_friend_routes
    register_friend_routes(app, csrf, limiter)

Routes:
    GET    /friends                          — Friends page (login required)
    POST   /api/friends/request              — Send friend request
    POST   /api/friends/<id>/accept          — Accept incoming request
    POST   /api/friends/<id>/reject          — Reject incoming request
    DELETE /api/friends/<id>                 — Unfriend
    GET    /api/friends/search?q=            — Search users (for invites)

MYSTES KYRIOS LLC — Confidential.
"""

import json
import logging
from datetime import datetime, timezone

from flask import request, jsonify, render_template_string, redirect, url_for
from flask_login import current_user, login_required

from models import db, Friendship, User

logger = logging.getLogger(__name__)


# ============================================================
# FRIENDS PAGE TEMPLATE — Premium MYSTES Design
# ============================================================

FRIENDS_CONTENT = """
<style>
/* ============================================
   FRIENDS PAGE — Page-specific layout
   ============================================ */

.friends-page { max-width: 960px; margin: 0 auto; padding: 0 16px; }

/* Add-friend form layout */
.friends-add-card { margin-bottom: 24px; }
.friends-add-card h2 {
    font-family: var(--font-brand);
    font-size: 18px;
    font-weight: 600;
    color: var(--text-bright);
    margin: 0 0 16px;
    letter-spacing: 1px;
}
.friends-add-form {
    display: flex;
    gap: 12px;
    align-items: flex-end;
}
.friends-add-form .input-group { flex: 1; }

/* Feedback message */
.friends-msg {
    margin-top: 12px;
    padding: 10px 16px;
    border-radius: var(--radius-md);
    font-size: 14px;
    display: none;
}
.friends-msg.success {
    background: rgba(34,197,94,0.12);
    border: 1px solid rgba(34,197,94,0.3);
    color: #4ade80;
    display: block;
}
.friends-msg.error {
    background: rgba(239,68,68,0.12);
    border: 1px solid rgba(239,68,68,0.3);
    color: #f87171;
    display: block;
}

/* Sections */
.friends-section { margin-bottom: 28px; }
.friends-section h2 {
    font-family: var(--font-brand);
    font-size: 18px;
    font-weight: 600;
    color: var(--text-bright);
    margin: 0 0 16px;
    letter-spacing: 1px;
}

/* Pending list layout */
.friends-pending-list {
    display: flex;
    flex-direction: column;
    gap: 10px;
}
.friends-pending-card {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    border-color: rgba(201,169,110,0.2);
}
.friends-pending-info { flex: 1; min-width: 0; }
.friends-pending-name {
    font-size: 16px;
    font-weight: 600;
    color: var(--text-bright);
    margin: 0 0 4px;
}
.friends-pending-email {
    font-size: 13px;
    color: var(--text-muted);
}
.friends-pending-actions {
    display: flex;
    gap: 8px;
    flex-shrink: 0;
}

/* Friends list layout */
.friends-list {
    display: flex;
    flex-direction: column;
    gap: 10px;
}
.friend-card {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
}
.friend-info { flex: 1; min-width: 0; }
.friend-name {
    font-size: 16px;
    font-weight: 600;
    color: var(--text-bright);
    margin: 0 0 4px;
}
.friend-meta {
    font-size: 13px;
    color: var(--text-muted);
}
.friend-meta span { margin-right: 16px; }

/* Empty state text override */
.friends-empty p {
    max-width: 400px;
    margin: 0 auto;
    line-height: 1.6;
    font-size: 15px;
}

/* Mobile responsive */
@media (max-width: 640px) {
    .friends-add-form { flex-direction: column; }
    .friends-add-form .mystes-btn { width: 100%; }
    .friends-pending-card,
    .friend-card {
        flex-direction: column;
        align-items: flex-start;
    }
    .friends-pending-actions { width: 100%; }
    .friends-pending-actions button { flex: 1; }
    .friend-card .mystes-btn { align-self: flex-end; }
}
</style>

<div class="friends-page">
    <div class="mystes-page-header">
        <h1>FRIENDS</h1>
        <p>Connect with fellow travelers on MYSTES</p>
    </div>

    <!-- Pending Requests -->
    {% if pending_requests %}
    <div class="friends-section">
        <h2>Pending Requests</h2>
        <div class="friends-pending-list">
            {% for req in pending_requests %}
            <div class="mystes-card compact friends-pending-card" id="pending-{{ req.id }}">
                <div class="friends-pending-info">
                    <div class="friends-pending-name">{{ req.requester.name or 'MYSTES User' }}</div>
                    <div class="friends-pending-email">{{ req.requester_email_masked }}</div>
                </div>
                <div class="friends-pending-actions">
                    <button class="mystes-btn mystes-btn-success mystes-btn-sm" onclick="acceptRequest({{ req.id }})">Accept</button>
                    <button class="mystes-btn mystes-btn-ghost mystes-btn-sm" onclick="rejectRequest({{ req.id }})">Reject</button>
                </div>
            </div>
            {% endfor %}
        </div>
    </div>
    {% endif %}

    <!-- Add Friend -->
    <div class="mystes-card friends-add-card">
        <h2>Add Friend</h2>
        <div class="friends-add-form">
            <div class="input-group">
                <label class="mystes-label" for="friend-email">Email Address</label>
                <input class="mystes-input" type="email" id="friend-email" placeholder="friend@example.com"
                       onkeydown="if(event.key==='Enter'){sendFriendRequest();}">
            </div>
            <button class="mystes-btn mystes-btn-gold" id="send-req-btn" onclick="sendFriendRequest()">Send Request</button>
        </div>
        <div class="friends-msg" id="friends-msg"></div>
    </div>

    <!-- Friends List -->
    <div class="friends-section">
        <h2>Your Friends</h2>
        {% if friends %}
        <div class="friends-list">
            {% for f in friends %}
            <div class="mystes-card compact friend-card" id="friend-{{ f.friendship_id }}">
                <div class="friend-info">
                    <div class="friend-name">{{ f.name or 'MYSTES User' }}</div>
                    <div class="friend-meta">
                        <span>{{ f.email_masked }}</span>
                        <span>Member since {{ f.member_since }}</span>
                    </div>
                </div>
                <button class="mystes-btn mystes-btn-danger mystes-btn-sm" onclick="unfriend({{ f.friendship_id }})">Unfriend</button>
            </div>
            {% endfor %}
        </div>
        {% else %}
        <div class="mystes-card mystes-empty friends-empty">
            <div class="mystes-empty-icon">&#x1f465;</div>
            <p>Connect with fellow travelers. Add friends to collaborate on trips and share collections.</p>
        </div>
        {% endif %}
    </div>
</div>

<script>
function sendFriendRequest() {
    const emailInput = document.getElementById('friend-email');
    const msgEl = document.getElementById('friends-msg');
    const btn = document.getElementById('send-req-btn');
    const email = emailInput.value.trim();

    if (!email) {
        msgEl.className = 'friends-msg error';
        msgEl.textContent = 'Please enter an email address.';
        return;
    }

    btn.disabled = true;
    btn.textContent = 'Sending...';
    msgEl.className = 'friends-msg';
    msgEl.style.display = 'none';

    fetch('/api/friends/request', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({email: email})
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            msgEl.className = 'friends-msg success';
            msgEl.textContent = data.message || 'Friend request sent!';
            emailInput.value = '';
        } else {
            msgEl.className = 'friends-msg error';
            msgEl.textContent = data.error || 'Something went wrong.';
        }
    })
    .catch(() => {
        msgEl.className = 'friends-msg error';
        msgEl.textContent = 'Network error. Please try again.';
    })
    .finally(() => {
        btn.disabled = false;
        btn.textContent = 'Send Request';
    });
}

function acceptRequest(id) {
    fetch('/api/friends/' + id + '/accept', {method: 'POST'})
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            location.reload();
        } else {
            alert(data.error || 'Could not accept request.');
        }
    })
    .catch(() => alert('Network error.'));
}

function rejectRequest(id) {
    fetch('/api/friends/' + id + '/reject', {method: 'POST'})
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            const card = document.getElementById('pending-' + id);
            if (card) card.remove();
        } else {
            alert(data.error || 'Could not reject request.');
        }
    })
    .catch(() => alert('Network error.'));
}

function unfriend(id) {
    if (!confirm('Remove this friend?')) return;
    fetch('/api/friends/' + id, {method: 'DELETE'})
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            const card = document.getElementById('friend-' + id);
            if (card) card.remove();
        } else {
            alert(data.error || 'Could not unfriend.');
        }
    })
    .catch(() => alert('Network error.'));
}
</script>
"""


# ============================================================
# Route Registration
# ============================================================

def _mask_email(email):
    """Mask email for privacy display: j***@example.com"""
    if not email or '@' not in email:
        return '***'
    local, domain = email.rsplit('@', 1)
    if len(local) <= 1:
        masked_local = local[0] + '***'
    else:
        masked_local = local[0] + '***'
    return f"{masked_local}@{domain}"


def register_friend_routes(app, csrf, limiter):
    """Register all friend routes on the Flask app."""
    from server import BASE_TEMPLATE, is_feature_enabled

    # ------------------------------------------------------------------
    # Friends Page
    # ------------------------------------------------------------------

    @app.route("/friends")
    @login_required
    def friends_page():
        """Friends page — list friends, pending requests, add new."""
        if not is_feature_enabled("friends_system"):
            return redirect(url_for("home"))

        me = current_user.id

        # Accepted friendships (either direction)
        accepted = Friendship.query.filter(
            Friendship.status == 'accepted',
            db.or_(
                Friendship.requester_id == me,
                Friendship.addressee_id == me,
            )
        ).all()

        # Pending incoming requests
        pending = Friendship.query.filter(
            Friendship.addressee_id == me,
            Friendship.status == 'pending',
        ).all()

        # Build pending request display objects
        pending_requests = []
        for req in pending:
            req.requester_email_masked = _mask_email(req.requester.email)
            pending_requests.append(req)

        # Build friend display objects
        friends = []
        for f in accepted:
            friend_user = f.addressee if f.requester_id == me else f.requester
            friends.append({
                'friendship_id': f.id,
                'name': friend_user.name or 'MYSTES User',
                'email_masked': _mask_email(friend_user.email),
                'member_since': friend_user.created_at.strftime('%b %Y') if friend_user.created_at else 'N/A',
            })

        return render_template_string(
            BASE_TEMPLATE,
            title="Friends",
            content=render_template_string(
                FRIENDS_CONTENT,
                pending_requests=pending_requests,
                friends=friends,
                current_user=current_user,
            ),
            current_user=current_user,
        )

    # ------------------------------------------------------------------
    # API: Send Friend Request
    # ------------------------------------------------------------------

    @app.route("/api/friends/request", methods=["POST"])
    @csrf.exempt
    @login_required
    def api_friend_request():
        """Send a friend request by email."""
        data = request.get_json()
        if not data or not data.get("email"):
            return jsonify({"success": False, "error": "Email is required."}), 400

        email = data["email"].strip().lower()

        # Cannot friend yourself
        if email == current_user.email.lower():
            return jsonify({"success": False, "error": "You cannot send a friend request to yourself."}), 400

        # Look up target user
        target = User.query.filter(db.func.lower(User.email) == email).first()
        if not target:
            return jsonify({"success": False, "error": "No MYSTES account found with that email."}), 404

        me = current_user.id

        # Check for existing friendship in either direction
        existing = Friendship.query.filter(
            db.or_(
                db.and_(Friendship.requester_id == me, Friendship.addressee_id == target.id),
                db.and_(Friendship.requester_id == target.id, Friendship.addressee_id == me),
            )
        ).first()

        if existing:
            if existing.status == 'accepted':
                return jsonify({"success": False, "error": "You are already friends."}), 409
            elif existing.status == 'pending':
                return jsonify({"success": False, "error": "A friend request is already pending."}), 409
            elif existing.status == 'blocked':
                return jsonify({"success": False, "error": "Unable to send request."}), 403

        friendship = Friendship(
            requester_id=me,
            addressee_id=target.id,
            status='pending',
        )
        db.session.add(friendship)
        db.session.commit()
        logger.info(f"Friend request sent: user {me} -> user {target.id}")

        # Send email notification (best-effort, non-blocking)
        try:
            from email_service import send_friend_request_email
            send_friend_request_email(
                to=target.email,
                from_name=current_user.name or current_user.email,
                to_name=target.name,
            )
        except Exception as _email_err:
            logger.debug("Friend request email failed (non-critical): %s", _email_err)

        return jsonify({"success": True, "message": "Friend request sent!"}), 201

    # ------------------------------------------------------------------
    # API: Accept Friend Request
    # ------------------------------------------------------------------

    @app.route("/api/friends/<int:friendship_id>/accept", methods=["POST"])
    @csrf.exempt
    @login_required
    def api_friend_accept(friendship_id):
        """Accept an incoming friend request."""
        friendship = Friendship.query.get(friendship_id)
        if not friendship:
            return jsonify({"success": False, "error": "Request not found."}), 404

        if friendship.addressee_id != current_user.id:
            return jsonify({"success": False, "error": "Not authorized."}), 403

        if friendship.status != 'pending':
            return jsonify({"success": False, "error": "Request is not pending."}), 400

        friendship.status = 'accepted'
        friendship.accepted_at = datetime.now(timezone.utc)
        db.session.commit()
        logger.info(f"Friend request accepted: friendship {friendship_id}")

        return jsonify({"success": True, "message": "Friend request accepted!"})

    # ------------------------------------------------------------------
    # API: Reject Friend Request
    # ------------------------------------------------------------------

    @app.route("/api/friends/<int:friendship_id>/reject", methods=["POST"])
    @csrf.exempt
    @login_required
    def api_friend_reject(friendship_id):
        """Reject an incoming friend request."""
        friendship = Friendship.query.get(friendship_id)
        if not friendship:
            return jsonify({"success": False, "error": "Request not found."}), 404

        if friendship.addressee_id != current_user.id:
            return jsonify({"success": False, "error": "Not authorized."}), 403

        if friendship.status != 'pending':
            return jsonify({"success": False, "error": "Request is not pending."}), 400

        db.session.delete(friendship)
        db.session.commit()
        logger.info(f"Friend request rejected: friendship {friendship_id}")

        return jsonify({"success": True, "message": "Request rejected."})

    # ------------------------------------------------------------------
    # API: Unfriend
    # ------------------------------------------------------------------

    @app.route("/api/friends/<int:friendship_id>", methods=["DELETE"])
    @csrf.exempt
    @login_required
    def api_friend_delete(friendship_id):
        """Remove a friendship (either party can unfriend)."""
        friendship = Friendship.query.get(friendship_id)
        if not friendship:
            return jsonify({"success": False, "error": "Friendship not found."}), 404

        me = current_user.id
        if friendship.requester_id != me and friendship.addressee_id != me:
            return jsonify({"success": False, "error": "Not authorized."}), 403

        db.session.delete(friendship)
        db.session.commit()
        logger.info(f"Unfriended: friendship {friendship_id} by user {me}")

        return jsonify({"success": True, "message": "Friend removed."})

    # ------------------------------------------------------------------
    # API: Search Users (for trip invites / friend add)
    # ------------------------------------------------------------------

    @app.route("/api/friends/search")
    @csrf.exempt
    @login_required
    def api_friends_search():
        """Search users by name or email. Returns max 10, excludes existing friends."""
        q = request.args.get("q", "").strip()
        if not q or len(q) < 2:
            return jsonify({"users": []})

        me = current_user.id
        search_term = f"%{q}%"

        # Find matching users (not self)
        matches = User.query.filter(
            User.id != me,
            User.is_active == True,
            db.or_(
                User.name.ilike(search_term),
                User.email.ilike(search_term),
            )
        ).limit(20).all()

        # Get IDs of existing friends/pending to exclude
        existing = Friendship.query.filter(
            db.or_(
                Friendship.requester_id == me,
                Friendship.addressee_id == me,
            )
        ).all()

        excluded_ids = set()
        for f in existing:
            if f.requester_id == me:
                excluded_ids.add(f.addressee_id)
            else:
                excluded_ids.add(f.requester_id)

        results = []
        for user in matches:
            if user.id in excluded_ids:
                continue
            results.append({
                'id': user.id,
                'name': user.name or 'MYSTES User',
                'email_masked': _mask_email(user.email),
            })
            if len(results) >= 10:
                break

        return jsonify({"users": results})

    # ------------------------------------------------------------------
    # API: Block/Unblock Friend (Build #185)
    # ------------------------------------------------------------------

    @app.route("/api/friends/<int:friendship_id>/block", methods=["POST"])
    @csrf.exempt
    @login_required
    def api_friends_block(friendship_id):
        """Block a user. Changes friendship status to 'blocked'."""
        friendship = Friendship.query.get(friendship_id)
        if not friendship:
            return jsonify({"success": False, "error": "Friendship not found."}), 404

        me = current_user.id
        if friendship.requester_id != me and friendship.addressee_id != me:
            return jsonify({"success": False, "error": "Not your friendship."}), 403

        friendship.status = "blocked"
        db.session.commit()

        return jsonify({"success": True, "message": "User blocked."})

    @app.route("/api/friends/<int:friendship_id>/unblock", methods=["POST"])
    @csrf.exempt
    @login_required
    def api_friends_unblock(friendship_id):
        """Unblock a user. Removes the friendship entirely (they can re-request)."""
        friendship = Friendship.query.get(friendship_id)
        if not friendship:
            return jsonify({"success": False, "error": "Friendship not found."}), 404

        me = current_user.id
        if friendship.requester_id != me and friendship.addressee_id != me:
            return jsonify({"success": False, "error": "Not your friendship."}), 403

        if friendship.status != "blocked":
            return jsonify({"success": False, "error": "Not blocked."}), 400

        db.session.delete(friendship)
        db.session.commit()

        return jsonify({"success": True, "message": "User unblocked."})

    # ------------------------------------------------------------------
    # API: Friends Activity Feed (Build #185)
    # ------------------------------------------------------------------

    @app.route("/api/friends/activity")
    @csrf.exempt
    @login_required
    def api_friends_activity():
        """Get recent activity from friends (bookings, collections, trips)."""
        me = current_user.id

        # Get friend IDs
        friendships = Friendship.query.filter(
            Friendship.status == "accepted",
            db.or_(
                Friendship.requester_id == me,
                Friendship.addressee_id == me,
            )
        ).all()

        friend_ids = set()
        for f in friendships:
            friend_ids.add(f.requester_id if f.addressee_id == me else f.addressee_id)

        if not friend_ids:
            return jsonify({"activity": []})

        activity = []

        # Recent bookings from friends
        try:
            from models import Booking, Deal
            bookings = Booking.query.filter(
                Booking.user_id.in_(friend_ids),
                Booking.status.in_(["booked", "confirmed", "completed"]),
            ).order_by(Booking.created_at.desc()).limit(10).all()

            for b in bookings:
                user = db.session.get(User, b.user_id)
                deal = db.session.get(Deal, b.deal_id) if b.deal_id else None
                activity.append({
                    "type": "booking",
                    "user_name": user.name or "Friend" if user else "Friend",
                    "destination": deal.destination if deal else None,
                    "airline": deal.airline if deal else None,
                    "vertical": deal.deal_type if deal else "flight",
                    "created_at": b.created_at.isoformat() if b.created_at else None,
                })
        except Exception as e:
            logger.debug("Friend activity feed (bookings) failed: %s", e)

        # Recent shared collections from friends
        try:
            from models import Collection
            collections = Collection.query.filter(
                Collection.user_id.in_(friend_ids),
                Collection.is_shared == True,
            ).order_by(Collection.updated_at.desc()).limit(10).all()

            for c in collections:
                user = db.session.get(User, c.user_id)
                activity.append({
                    "type": "collection",
                    "user_name": user.name or "Friend" if user else "Friend",
                    "title": c.name,
                    "share_slug": c.share_slug,
                    "created_at": c.updated_at.isoformat() if c.updated_at else None,
                })
        except Exception as e:
            logger.debug("Friend activity feed (collections) failed: %s", e)

        # Sort by time
        activity.sort(key=lambda x: x.get("created_at") or "", reverse=True)

        return jsonify({"activity": activity[:20]})

    # ------------------------------------------------------------------
    # API: Set Companion Nickname (Build #220)
    # ------------------------------------------------------------------

    @app.route("/api/friends/<int:friendship_id>/nickname", methods=["POST"])
    @csrf.exempt
    @login_required
    def api_friends_set_nickname(friendship_id):
        """Set a nickname for a travel companion."""
        friendship = db.session.get(Friendship, friendship_id)
        if not friendship:
            return jsonify({"success": False, "error": "Not found"}), 404

        me = current_user.id
        if friendship.requester_id != me and friendship.addressee_id != me:
            return jsonify({"success": False, "error": "Not your friendship"}), 403

        data = request.get_json(silent=True) or {}
        nickname = (data.get("nickname") or "").strip()
        if len(nickname) > 50:
            nickname = nickname[:50]

        friendship.nickname = nickname or None
        db.session.commit()

        return jsonify({"success": True, "nickname": friendship.nickname})

    # ------------------------------------------------------------------
    # API: Get Companions with Trip Stats (Build #220)
    # ------------------------------------------------------------------

    @app.route("/api/friends/companions")
    @csrf.exempt
    @login_required
    def api_friends_companions():
        """List accepted friends with companion details (nickname, trip count)."""
        me = current_user.id
        friendships = Friendship.query.filter(
            Friendship.status == "accepted",
            db.or_(
                Friendship.requester_id == me,
                Friendship.addressee_id == me,
            )
        ).order_by(Friendship.trips_together_count.desc()).all()

        companions = []
        for f in friendships:
            companion_id = f.addressee_id if f.requester_id == me else f.requester_id
            companion_user = db.session.get(User, companion_id)
            companions.append({
                "friendship_id": f.id,
                "user_id": companion_id,
                "name": companion_user.name if companion_user else "Unknown",
                "email": companion_user.email if companion_user else None,
                "nickname": f.nickname,
                "trips_together": f.trips_together_count or 0,
                "first_trip_at": f.first_trip_together_at.isoformat() if f.first_trip_together_at else None,
                "since": f.accepted_at.isoformat() if f.accepted_at else f.created_at.isoformat(),
            })

        return jsonify({"companions": companions, "count": len(companions)})

    logger.info("Friends + Companions routes registered (Build #220 enhanced)")
