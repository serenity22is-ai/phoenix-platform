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
   FRIENDS PAGE — Dark OTA aesthetic
   ============================================ */

.friends-page { max-width: 960px; margin: 0 auto; padding: 0 16px; }

.friends-page-header {
    text-align: center;
    padding: 40px 0 10px;
}
.friends-page-header h1 {
    font-family: var(--font-brand, 'Cinzel', serif);
    font-size: 32px;
    font-weight: 700;
    letter-spacing: 4px;
    color: var(--text-bright, #f5f5f5);
    margin: 0 0 8px;
}
.friends-page-header p {
    color: var(--text-secondary, #aaa);
    font-size: 15px;
    margin: 0;
}

/* Add friend card */
.friends-add-card {
    background: rgba(10, 6, 18, 0.85);
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 16px;
    padding: 28px;
    margin-bottom: 24px;
}
.friends-add-card h2 {
    font-family: var(--font-brand, 'Cinzel', serif);
    font-size: 18px;
    font-weight: 600;
    color: #f5f5f5;
    margin: 0 0 16px;
    letter-spacing: 1px;
}
.friends-add-form {
    display: flex;
    gap: 12px;
    align-items: flex-end;
}
.friends-add-form .input-group {
    flex: 1;
}
.friends-add-form label {
    display: block;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.5px;
    text-transform: uppercase;
    color: var(--text-secondary, #aaa);
    margin-bottom: 6px;
    font-family: var(--font-body, 'Outfit', sans-serif);
}
.friends-add-form input {
    width: 100%;
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.12);
    color: #f5f5f5;
    border-radius: 10px;
    padding: 12px 16px;
    font-size: 15px;
    font-family: var(--font-body, 'Outfit', sans-serif);
    outline: none;
    transition: border-color 0.2s;
    box-sizing: border-box;
}
.friends-add-form input:focus {
    border-color: rgba(201,164,74,0.5);
}
.friends-add-form input::placeholder {
    color: rgba(255,255,255,0.3);
}
.friends-send-btn {
    background: #c9a44a;
    color: #000;
    border: none;
    border-radius: 10px;
    padding: 12px 24px;
    font-size: 14px;
    font-weight: 600;
    font-family: var(--font-body, 'Outfit', sans-serif);
    cursor: pointer;
    transition: all 0.2s;
    white-space: nowrap;
}
.friends-send-btn:hover {
    background: #d4af55;
    transform: translateY(-1px);
}
.friends-send-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
    transform: none;
}
.friends-msg {
    margin-top: 12px;
    padding: 10px 16px;
    border-radius: 10px;
    font-size: 14px;
    display: none;
    font-family: var(--font-body, 'Outfit', sans-serif);
}
.friends-msg.success {
    background: rgba(76,175,80,0.12);
    border: 1px solid rgba(76,175,80,0.3);
    color: #4caf50;
    display: block;
}
.friends-msg.error {
    background: rgba(244,67,54,0.12);
    border: 1px solid rgba(244,67,54,0.3);
    color: #f44336;
    display: block;
}

/* Pending requests section */
.friends-section {
    margin-bottom: 28px;
}
.friends-section h2 {
    font-family: var(--font-brand, 'Cinzel', serif);
    font-size: 18px;
    font-weight: 600;
    color: #f5f5f5;
    margin: 0 0 16px;
    letter-spacing: 1px;
}
.friends-pending-list {
    display: flex;
    flex-direction: column;
    gap: 10px;
}
.friends-pending-card {
    background: rgba(10, 6, 18, 0.85);
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    border: 1px solid rgba(201,164,74,0.2);
    border-radius: 16px;
    padding: 20px 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
}
.friends-pending-info {
    flex: 1;
    min-width: 0;
}
.friends-pending-name {
    font-size: 16px;
    font-weight: 600;
    color: #f5f5f5;
    margin: 0 0 4px;
    font-family: var(--font-body, 'Outfit', sans-serif);
}
.friends-pending-email {
    font-size: 13px;
    color: rgba(255,255,255,0.6);
    font-family: var(--font-body, 'Outfit', sans-serif);
}
.friends-pending-actions {
    display: flex;
    gap: 8px;
    flex-shrink: 0;
}
.friends-accept-btn {
    background: rgba(76,175,80,0.15);
    color: #4caf50;
    border: 1px solid rgba(76,175,80,0.3);
    border-radius: 10px;
    padding: 8px 18px;
    font-size: 13px;
    font-weight: 600;
    font-family: var(--font-body, 'Outfit', sans-serif);
    cursor: pointer;
    transition: all 0.2s;
}
.friends-accept-btn:hover {
    background: rgba(76,175,80,0.25);
    border-color: #4caf50;
}
.friends-reject-btn {
    background: rgba(255,255,255,0.06);
    color: #aaa;
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 10px;
    padding: 8px 18px;
    font-size: 13px;
    font-weight: 600;
    font-family: var(--font-body, 'Outfit', sans-serif);
    cursor: pointer;
    transition: all 0.2s;
}
.friends-reject-btn:hover {
    background: rgba(244,67,54,0.12);
    border-color: rgba(244,67,54,0.3);
    color: #f44336;
}

/* Friends list */
.friends-list {
    display: flex;
    flex-direction: column;
    gap: 10px;
}
.friend-card {
    background: rgba(10, 6, 18, 0.85);
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 16px;
    padding: 20px 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    transition: border-color 0.2s;
}
.friend-card:hover {
    border-color: rgba(255,255,255,0.15);
}
.friend-info {
    flex: 1;
    min-width: 0;
}
.friend-name {
    font-size: 16px;
    font-weight: 600;
    color: #f5f5f5;
    margin: 0 0 4px;
    font-family: var(--font-body, 'Outfit', sans-serif);
}
.friend-meta {
    font-size: 13px;
    color: rgba(255,255,255,0.6);
    font-family: var(--font-body, 'Outfit', sans-serif);
}
.friend-meta span {
    margin-right: 16px;
}
.friend-unfriend-btn {
    background: transparent;
    color: #aaa;
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 10px;
    padding: 6px 14px;
    font-size: 12px;
    font-weight: 600;
    font-family: var(--font-body, 'Outfit', sans-serif);
    cursor: pointer;
    transition: all 0.2s;
    flex-shrink: 0;
}
.friend-unfriend-btn:hover {
    background: rgba(244,67,54,0.12);
    border-color: rgba(244,67,54,0.3);
    color: #f44336;
}

/* Empty state */
.friends-empty {
    text-align: center;
    padding: 60px 20px;
    background: rgba(10, 6, 18, 0.85);
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 16px;
}
.friends-empty-icon {
    font-size: 48px;
    opacity: 0.3;
    margin-bottom: 16px;
}
.friends-empty p {
    color: rgba(255,255,255,0.6);
    font-size: 15px;
    max-width: 400px;
    margin: 0 auto;
    line-height: 1.6;
    font-family: var(--font-body, 'Outfit', sans-serif);
}

/* Mobile responsive */
@media (max-width: 640px) {
    .friends-add-form {
        flex-direction: column;
    }
    .friends-send-btn {
        width: 100%;
    }
    .friends-pending-card,
    .friend-card {
        flex-direction: column;
        align-items: flex-start;
    }
    .friends-pending-actions {
        width: 100%;
    }
    .friends-pending-actions button {
        flex: 1;
    }
    .friend-unfriend-btn {
        align-self: flex-end;
    }
}
</style>

<div class="friends-page">
    <div class="friends-page-header">
        <h1>FRIENDS</h1>
        <p>Connect with fellow travelers on MYSTES</p>
    </div>

    <!-- Pending Requests -->
    {% if pending_requests %}
    <div class="friends-section">
        <h2>Pending Requests</h2>
        <div class="friends-pending-list">
            {% for req in pending_requests %}
            <div class="friends-pending-card" id="pending-{{ req.id }}">
                <div class="friends-pending-info">
                    <div class="friends-pending-name">{{ req.requester.name or 'MYSTES User' }}</div>
                    <div class="friends-pending-email">{{ req.requester_email_masked }}</div>
                </div>
                <div class="friends-pending-actions">
                    <button class="friends-accept-btn" onclick="acceptRequest({{ req.id }})">Accept</button>
                    <button class="friends-reject-btn" onclick="rejectRequest({{ req.id }})">Reject</button>
                </div>
            </div>
            {% endfor %}
        </div>
    </div>
    {% endif %}

    <!-- Add Friend -->
    <div class="friends-add-card">
        <h2>Add Friend</h2>
        <div class="friends-add-form">
            <div class="input-group">
                <label for="friend-email">Email Address</label>
                <input type="email" id="friend-email" placeholder="friend@example.com"
                       onkeydown="if(event.key==='Enter'){sendFriendRequest();}">
            </div>
            <button class="friends-send-btn" id="send-req-btn" onclick="sendFriendRequest()">Send Request</button>
        </div>
        <div class="friends-msg" id="friends-msg"></div>
    </div>

    <!-- Friends List -->
    <div class="friends-section">
        <h2>Your Friends</h2>
        {% if friends %}
        <div class="friends-list">
            {% for f in friends %}
            <div class="friend-card" id="friend-{{ f.friendship_id }}">
                <div class="friend-info">
                    <div class="friend-name">{{ f.name or 'MYSTES User' }}</div>
                    <div class="friend-meta">
                        <span>{{ f.email_masked }}</span>
                        <span>Member since {{ f.member_since }}</span>
                    </div>
                </div>
                <button class="friend-unfriend-btn" onclick="unfriend({{ f.friendship_id }})">Unfriend</button>
            </div>
            {% endfor %}
        </div>
        {% else %}
        <div class="friends-empty">
            <div class="friends-empty-icon">&#x1f465;</div>
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
