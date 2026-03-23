"""
MYSTES Push Notification Routes — Build #188

Handles device token registration from Capacitor native apps
and admin-only push notification sending (stub for FCM/APNs).

Routes:
    POST /api/push/register  — Upsert device token (CSRF exempt for native)
    POST /api/push/send      — Admin-only send notification (stub)

MYSTES KYRIOS LLC — Confidential.
"""

import logging
from datetime import datetime, timezone

from flask import jsonify, request, session

logger = logging.getLogger(__name__)


def register_push_routes(app, csrf, limiter):
    """Register push notification routes."""

    @app.route("/api/push/register", methods=["POST"])
    @csrf.exempt
    @limiter.limit("30/minute")
    def push_register_token():
        """
        Register or update a device push token.

        Body (JSON):
            token: FCM/APNs token string (required)
            platform: ios | android | web (required)

        CSRF exempt — called from native Capacitor app.
        """
        from models import db, DeviceToken

        data = request.get_json(silent=True) or {}
        token = data.get("token", "").strip()
        platform = data.get("platform", "").strip().lower()

        if not token:
            return jsonify({"error": "Token required"}), 400
        if platform not in ("ios", "android", "web"):
            return jsonify({"error": "Platform must be ios, android, or web"}), 400

        # Get user_id from session if logged in
        user_id = session.get("user_id") or session.get("_user_id")

        # Upsert: update if token exists, create if not
        existing = DeviceToken.query.filter_by(token=token).first()
        if existing:
            existing.platform = platform
            existing.is_active = True
            existing.updated_at = datetime.now(timezone.utc)
            if user_id:
                existing.user_id = user_id
            db.session.commit()
            logger.debug("Push token updated: %s (%s)", token[:20], platform)
            return jsonify({"registered": True, "updated": True})

        device = DeviceToken(
            token=token,
            platform=platform,
            user_id=user_id,
            is_active=True,
        )
        db.session.add(device)
        db.session.commit()
        logger.info("Push token registered: %s (%s)", token[:20], platform)
        return jsonify({"registered": True, "updated": False})

    @app.route("/api/push/send", methods=["POST"])
    @csrf.exempt
    def push_send_notification():
        """
        Admin-only: queue a push notification for delivery.

        Stub implementation — records intent but does not call FCM/APNs.
        Full integration is a future build.

        Body (JSON):
            title: Notification title (required)
            body: Notification body (required)
            user_id: Target user (optional, null = broadcast)
            data: Extra data payload (optional)
        """
        from models import User

        # Admin check
        user_id = session.get("user_id") or session.get("_user_id")
        if not user_id:
            return jsonify({"error": "Authentication required"}), 401

        user = User.query.get(user_id)
        if not user or not getattr(user, 'is_admin', False):
            return jsonify({"error": "Admin access required"}), 403

        data = request.get_json(silent=True) or {}
        title = data.get("title", "").strip()
        body = data.get("body", "").strip()

        if not title or not body:
            return jsonify({"error": "Title and body required"}), 400

        # Stub: log intent, return queued status
        target = data.get("user_id", "broadcast")
        logger.info("Push notification queued: title='%s' target=%s", title, target)

        return jsonify({
            "queued": True,
            "title": title,
            "target": target,
            "note": "FCM/APNs integration pending — notification recorded but not delivered",
        })
