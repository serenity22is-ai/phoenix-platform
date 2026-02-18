"""
MYSTES Server-Sent Events (SSE) System

Delivers real-time updates to browser clients via SSE over Redis pub/sub.

Architecture:
    Celery task → Redis PUBLISH → SSE listener → HTTP stream → Browser EventSource

Channels:
    mystes:events:user:{user_id}     — per-user events (payment, P2P status, alerts)
    mystes:events:admin              — admin dashboard updates
    mystes:events:global             — system-wide broadcasts
    mystes:events:nodes              — node network updates (registration, health)

Event Categories:
    P2P:        p2p_matched, p2p_escrow_locked, p2p_booking_confirmed, p2p_completed, p2p_failed
    Payments:   payment_verified, payment_failed, escrow_created, escrow_released, escrow_cancelled
    Alerts:     price_alert_triggered, opportunity_detected, anomaly_detected
    Nodes:      node_registered, node_offline, node_task_assigned, node_task_completed
    Disputes:   dispute_opened, dispute_under_review, dispute_resolved
    Deals:      deal_created, deal_updated, deal_expired
    System:     connected, test, heartbeat

Usage in templates:
    const es = new EventSource('/events/stream');
    es.addEventListener('p2p_matched', (e) => { ... });
    es.addEventListener('payment_verified', (e) => { ... });
    es.addEventListener('price_alert_triggered', (e) => { ... });

Usage from server:
    from event_stream import publish_event, emit_p2p_update, emit_price_alert, emit_node_event
    publish_event(f"user:{user_id}", "p2p_matched", {"transaction_id": "..."})
    emit_p2p_update(buyer_id, helper_user_id, "p2p_escrow_locked", {...})
    emit_price_alert(user_id, alert_data)
    emit_node_event("node_registered", node_data)
"""

import json
import logging
import os
import time
import threading
import queue

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


def publish_event(channel, event_type, data):
    """Publish an event to Redis pub/sub (synchronous, for use in Flask routes)."""
    try:
        import redis
        r = redis.from_url(REDIS_URL)
        payload = json.dumps({"event": event_type, "data": data})
        r.publish(f"mystes:events:{channel}", payload)
    except Exception as e:
        logger.error(f"Failed to publish event: {e}")


class SSEManager:
    """Manages SSE connections and Redis pub/sub subscriptions."""

    def __init__(self):
        self._listeners = {}  # channel -> set of queue.Queue
        self._lock = threading.Lock()
        self._pubsub_thread = None
        self._running = False

    def subscribe(self, channel):
        """Subscribe a client to a channel. Returns a Queue that yields events."""
        q = queue.Queue(maxsize=50)
        with self._lock:
            if channel not in self._listeners:
                self._listeners[channel] = set()
            self._listeners[channel].add(q)

        self._ensure_pubsub()
        return q

    def unsubscribe(self, channel, q):
        """Remove a client subscription."""
        with self._lock:
            if channel in self._listeners:
                self._listeners[channel].discard(q)
                if not self._listeners[channel]:
                    del self._listeners[channel]

    def _ensure_pubsub(self):
        """Start the Redis pub/sub listener thread if not running."""
        if self._running:
            return
        self._running = True
        self._pubsub_thread = threading.Thread(
            target=self._pubsub_loop, daemon=True, name="sse_pubsub"
        )
        self._pubsub_thread.start()

    def _pubsub_loop(self):
        """Background thread: listen on Redis pub/sub and fan out to SSE clients."""
        import redis

        while self._running:
            try:
                r = redis.from_url(REDIS_URL)
                ps = r.pubsub()
                ps.psubscribe("mystes:events:*")
                logger.info("SSE pub/sub listener started")

                for message in ps.listen():
                    if not self._running:
                        break
                    if message["type"] != "pmessage":
                        continue

                    raw_channel = message["channel"]
                    if isinstance(raw_channel, bytes):
                        raw_channel = raw_channel.decode("utf-8")

                    # Strip prefix: "mystes:events:user:123" -> "user:123"
                    channel = raw_channel.replace("mystes:events:", "", 1)

                    raw_data = message["data"]
                    if isinstance(raw_data, bytes):
                        raw_data = raw_data.decode("utf-8")

                    try:
                        payload = json.loads(raw_data)
                    except json.JSONDecodeError:
                        continue

                    event_type = payload.get("event", "message")
                    data = json.dumps(payload.get("data", {}))

                    sse_msg = f"event: {event_type}\ndata: {data}\n\n"

                    with self._lock:
                        queues = self._listeners.get(channel, set()).copy()
                        # Also deliver to "global" channel listeners
                        queues |= self._listeners.get("global", set()).copy()

                    for q in queues:
                        try:
                            q.put_nowait(sse_msg)
                        except queue.Full:
                            pass  # Client fell behind, skip

            except Exception as e:
                logger.error(f"SSE pub/sub error: {e}")
                time.sleep(5)  # Reconnect backoff

    def stop(self):
        """Stop the pub/sub listener."""
        self._running = False


# Global SSE manager instance
sse_manager = SSEManager()


def register_sse_routes(app):
    """Register SSE endpoints on the Flask app."""
    from flask import Response, request, g
    from flask_login import current_user, login_required

    @app.route("/events/stream")
    @login_required
    def sse_stream():
        """SSE endpoint — streams events for the authenticated user."""
        user_channel = f"user:{current_user.id}"
        channels = [user_channel]

        if current_user.is_admin:
            channels.append("admin")

        queues_and_channels = []
        for ch in channels:
            q = sse_manager.subscribe(ch)
            queues_and_channels.append((ch, q))

        def generate():
            # Initial connection confirmation
            yield f"event: connected\ndata: {json.dumps({'channels': channels})}\n\n"

            # Heartbeat + event loop
            try:
                while True:
                    has_data = False
                    for ch, q in queues_and_channels:
                        try:
                            msg = q.get(timeout=0.1)
                            yield msg
                            has_data = True
                        except queue.Empty:
                            pass

                    if not has_data:
                        # Send heartbeat every ~15 seconds
                        yield f": heartbeat {int(time.time())}\n\n"
                        time.sleep(15)
            except GeneratorExit:
                pass
            finally:
                for ch, q in queues_and_channels:
                    sse_manager.unsubscribe(ch, q)

        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @app.route("/events/test")
    @login_required
    def sse_test():
        """Test endpoint: send a test event to the current user."""
        publish_event(
            f"user:{current_user.id}",
            "test",
            {"message": "SSE connection working", "timestamp": int(time.time())},
        )
        return {"ok": True, "channel": f"user:{current_user.id}"}


# ============================================================
# Typed Event Emitters — convenience functions for common events
# ============================================================

def emit_p2p_update(buyer_id, helper_user_id, event_type, data):
    """
    Emit P2P status update to both buyer and helper simultaneously.

    Event types: p2p_matched, p2p_escrow_locked, p2p_booking_confirmed,
                 p2p_completed, p2p_failed, p2p_cancelled
    """
    data["timestamp"] = int(time.time())
    data["category"] = "p2p"
    publish_event(f"user:{buyer_id}", event_type, data)
    if helper_user_id and helper_user_id != buyer_id:
        publish_event(f"user:{helper_user_id}", event_type, data)
    publish_event("admin", event_type, data)


def emit_payment_event(user_id, event_type, data):
    """
    Emit payment status update.

    Event types: payment_verified, payment_failed, escrow_created,
                 escrow_released, escrow_cancelled
    """
    data["timestamp"] = int(time.time())
    data["category"] = "payment"
    publish_event(f"user:{user_id}", event_type, data)
    publish_event("admin", event_type, data)


def emit_price_alert(user_id, alert_data):
    """
    Emit price alert trigger notification.

    alert_data should contain: alert_id, origin, destination, current_price,
    threshold_price, savings_pct
    """
    alert_data["timestamp"] = int(time.time())
    alert_data["category"] = "alert"
    publish_event(f"user:{user_id}", "price_alert_triggered", alert_data)


def emit_opportunity(data):
    """
    Emit newly detected arbitrage opportunity to global channel.

    data should contain: type, route/product, markets, savings_pct, confidence
    """
    data["timestamp"] = int(time.time())
    data["category"] = "opportunity"
    publish_event("global", "opportunity_detected", data)
    publish_event("admin", "opportunity_detected", data)


def emit_anomaly(data):
    """
    Emit price anomaly detection to admin channel.

    data should contain: route, market, direction (spike/drop),
    deviation_pct, current_price, avg_price
    """
    data["timestamp"] = int(time.time())
    data["category"] = "anomaly"
    publish_event("admin", "anomaly_detected", data)


def emit_node_event(event_type, data):
    """
    Emit node network event.

    Event types: node_registered, node_offline, node_task_assigned,
                 node_task_completed, node_stale
    """
    data["timestamp"] = int(time.time())
    data["category"] = "node"
    publish_event("nodes", event_type, data)
    publish_event("admin", event_type, data)
    # Also notify the node owner
    user_id = data.get("user_id")
    if user_id:
        publish_event(f"user:{user_id}", event_type, data)


def emit_extension_event(user_id, event_type, data):
    """
    Emit browser extension data event to user + nodes channels.

    Event types: extension_data_ingested, extension_connected, extension_disconnected
    """
    data["timestamp"] = int(time.time())
    data["category"] = "extension"
    publish_event(f"user:{user_id}", event_type, data)
    publish_event("nodes", event_type, data)


def emit_dispute_event(buyer_id, helper_user_id, event_type, data):
    """
    Emit dispute lifecycle event to both parties + admin.

    Event types: dispute_opened, dispute_under_review, dispute_resolved,
                 dispute_auto_resolved, dispute_escalated
    """
    data["timestamp"] = int(time.time())
    data["category"] = "dispute"
    publish_event(f"user:{buyer_id}", event_type, data)
    if helper_user_id and helper_user_id != buyer_id:
        publish_event(f"user:{helper_user_id}", event_type, data)
    publish_event("admin", event_type, data)


def emit_deal_event(event_type, data, user_id=None):
    """
    Emit deal lifecycle event.

    Event types: deal_created, deal_updated, deal_expired, deal_booked
    """
    data["timestamp"] = int(time.time())
    data["category"] = "deal"
    if user_id:
        publish_event(f"user:{user_id}", event_type, data)
    publish_event("global", event_type, data)


def emit_ai_response(user_id, chunk_data):
    """
    Emit MYSTES AI response chunk for streaming chat (Build #72).

    chunk_data should contain: conversation_id, chunk_type (text|tool_start|tool_result|done),
    content (text chunk or tool data)
    """
    chunk_data["timestamp"] = int(time.time())
    chunk_data["category"] = "ai"
    publish_event(f"user:{user_id}", "ai_response_chunk", chunk_data)


def emit_system_broadcast(event_type, data):
    """
    Emit system-wide broadcast event.

    For: maintenance notices, feature announcements, network status changes.
    """
    data["timestamp"] = int(time.time())
    data["category"] = "system"
    publish_event("global", event_type, data)
    publish_event("admin", event_type, data)
