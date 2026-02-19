"""
MYSTES AI Chat API Routes (Build #72)

Registers Flask routes for the MYSTES AI conversational interface.
Handles chat sessions, conversation management, tier info, and pricing.

Usage:
    from mystes_ai_api import register_mystes_ai_routes
    register_mystes_ai_routes(app)
"""

import json
import logging
import secrets
from datetime import datetime

from flask import request, jsonify, g, make_response, session
from flask_login import login_required, current_user

logger = logging.getLogger(__name__)


def register_mystes_ai_routes(app, csrf=None):
    """Register MYSTES AI chat API endpoints on the Flask app."""

    # ==================================================================
    # POST /api/v1/ai/chat — Main chat endpoint
    # ==================================================================

    # ------------------------------------------------------------------
    # Guest (unauthenticated) free trial: 3 searches with 5 proxies each
    # ------------------------------------------------------------------
    FREE_GUEST_QUERIES = 3
    GUEST_TIER_CONFIG = {
        "name": "Guest Trial",
        "max_tools_per_query": 5,   # 5 proxy markets per query
        "max_context_messages": 6,
    }

    @app.route("/api/v1/ai/chat", methods=["POST"])
    def ai_chat():
        """Send a message to MYSTES AI and receive a response.

        Supports both authenticated users and guest users (up to 3 free queries).

        POST body: {
            "message": "Find me cheap flights to Tokyo",
            "conversation_id": "conv_abc123" (optional — creates new if omitted)
        }

        Returns:
            200: {conversation_id, response, usage}
            429: Quota or rate limit exceeded / guest limit reached
        """
        from models import db, AIConversation, AIMessage
        from mystes_ai import (
            mystes_ai, check_ai_quota, check_ai_rate_limit,
            record_ai_usage, get_ai_tier, get_combined_quota,
            ARBITRAGE_SUBSCRIPTION_TIERS, ARBITRAGE_FREE_QUERIES,
        )

        data = request.get_json()
        if not data or not data.get("message"):
            return jsonify({"error": "message is required"}), 400

        message = data["message"].strip()
        if not message:
            return jsonify({"error": "message cannot be empty"}), 400

        is_guest = not current_user.is_authenticated

        # --- Guest free trial logic ---
        if is_guest:
            guest_used = session.get("guest_queries_used", 0)
            if guest_used >= FREE_GUEST_QUERIES:
                return jsonify({
                    "error": "free_trial_exhausted",
                    "message": "You've used all 3 free searches. Create a free account to keep searching and unlock more features.",
                    "queries_used": guest_used,
                    "queries_allowed": FREE_GUEST_QUERIES,
                    "signup_url": "/register",
                    "login_url": "/login",
                }), 429

        # --- Authenticated user checks ---
        if not is_guest:
            user_id = current_user.id
            conversation_id = data.get("conversation_id")

            # --- Quota check ---
            quota = check_ai_quota(current_user)
            if not quota.get("allowed", False):
                node_tier = quota.get("node_tier", "bronze")
                return jsonify({
                    "error": "daily_limit_reached",
                    "message": f"You've used your free queries for today. Share more data to unlock more searches, or subscribe from $4.99/mo.",
                    "quota": quota,
                    "node_tier": node_tier,
                    "upgrade_url": "/ai/pricing",
                    "data_sharing_url": "/dashboard#data-sharing",
                }), 429

            # --- Rate limit check ---
            rate = check_ai_rate_limit(current_user)
            if not rate.get("allowed", False):
                return jsonify({
                    "error": "AI rate limit exceeded",
                    "rate_limit": rate,
                    "retry_after_seconds": rate.get("retry_after_seconds", 60),
                }), 429
        else:
            user_id = "guest"
            conversation_id = session.get("guest_conversation_id")

        # --- Get or create conversation ---
        try:
            if not is_guest:
                if conversation_id:
                    conversation = AIConversation.query.filter_by(
                        conversation_id=conversation_id,
                        user_id=user_id,
                        is_active=True,
                    ).first()
                    if not conversation:
                        return jsonify({"error": "Conversation not found"}), 404
                else:
                    conversation_id = f"conv_{secrets.token_hex(12)}"
                    conversation = AIConversation(
                        conversation_id=conversation_id,
                        user_id=user_id,
                        title=message[:100],
                        message_count=0,
                        total_credits_used=0.0,
                        is_active=True,
                    )
                    db.session.add(conversation)
                    db.session.flush()
            else:
                # Guest: use session-based conversation, no DB persistence
                if not conversation_id:
                    conversation_id = f"conv_guest_{secrets.token_hex(12)}"
                    session["guest_conversation_id"] = conversation_id
                conversation = None

            # --- Resolve tier config ---
            if is_guest:
                tier_config = GUEST_TIER_CONFIG
            else:
                combined = get_combined_quota(current_user)
                tier_config = {
                    "max_tools_per_query": combined["effective_tools"],
                    "max_context_messages": combined["effective_context"],
                }

            # --- Call MYSTES AI ---
            result = mystes_ai.chat(
                user_id=user_id,
                conversation_id=conversation_id,
                user_message=message,
                tier_config=tier_config,
            )

            # --- Persist messages (authenticated users only) ---
            if not is_guest:
                user_msg = AIMessage(
                    conversation_id=conversation_id,
                    role="user",
                    content=message,
                    credits_used=0.0,
                )
                db.session.add(user_msg)

                assistant_content = result.get("content", "")
                tool_calls_raw = result.get("tool_calls")
                tool_calls_json = json.dumps(tool_calls_raw) if tool_calls_raw else None
                model_used = result.get("model_used")
                response_time_ms = result.get("response_time_ms")
                credits_used = result.get("credits_used", 1.0)

                assistant_msg = AIMessage(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=assistant_content,
                    tool_calls=tool_calls_json,
                    credits_used=credits_used,
                    model_used=model_used,
                    response_time_ms=response_time_ms,
                )
                db.session.add(assistant_msg)

                conversation.message_count = (conversation.message_count or 0) + 2
                conversation.total_credits_used = (conversation.total_credits_used or 0.0) + credits_used
                conversation.last_message_at = datetime.utcnow()

                if not conversation.title or conversation.message_count <= 2:
                    conversation.title = message[:100]

                db.session.commit()

                try:
                    record_ai_usage(current_user, credits_used)
                except Exception as e:
                    logger.warning("Failed to record AI usage for user %s: %s", user_id, e)
            else:
                # Guest: increment free query counter
                assistant_content = result.get("content", "")
                tool_calls_raw = result.get("tool_calls")
                model_used = result.get("model_used")
                response_time_ms = result.get("response_time_ms")
                credits_used = result.get("credits_used", 1.0)

                guest_used = session.get("guest_queries_used", 0) + 1
                session["guest_queries_used"] = guest_used

            # --- Cache hotel search results in session for booking flow ---
            # When AI search_hotels returns results, cache them so /api/hotels/select works
            if tool_calls_raw:
                for tc in (tool_calls_raw if isinstance(tool_calls_raw, list) else []):
                    if tc.get("tool") == "search_hotels" and isinstance(tc.get("result"), dict):
                        hotels = tc["result"].get("hotels", [])
                        if hotels:
                            session['hotel_search_results'] = {
                                h.get("offer_id"): h for h in hotels if h.get("offer_id")
                            }

            # --- SSE push: emit AI response for real-time dashboard (Build #107) ---
            try:
                from event_stream import emit_ai_response
                emit_ai_response(user_id, {
                    "conversation_id": conversation_id,
                    "chunk_type": "done",
                    "content": assistant_content[:500] if assistant_content else "",
                    "tool_calls_count": len(tool_calls_raw) if tool_calls_raw else 0,
                    "model_used": model_used,
                    "response_time_ms": response_time_ms,
                })
            except Exception:
                pass  # SSE is best-effort

            # --- Strategy observation hook (Build #73) ---
            try:
                from strategy_learner import strategy_learner
                strategy_learner.record_observation(
                    source_type='mystes_ai',
                    provider_key='claude-sonnet',
                    query_category='general',
                    query_params={'message_length': len(message)},
                    results={'content': assistant_content[:200], 'tool_calls': tool_calls_raw},
                    response_time_ms=response_time_ms,
                )
            except Exception:
                pass  # Never block chat on learner failure

            # --- Build response ---
            if is_guest:
                remaining = FREE_GUEST_QUERIES - session.get("guest_queries_used", 0)
                usage_info = {
                    "queries_used": session.get("guest_queries_used", 0),
                    "queries_remaining": max(remaining, 0),
                    "is_guest": True,
                }
            else:
                updated_quota = check_ai_quota(current_user)
                usage_info = {
                    "queries_used": updated_quota.get("used", 0),
                    "queries_remaining": updated_quota.get("remaining", 0),
                    "node_tier": updated_quota.get("node_tier", "bronze"),
                    "node_free_per_day": updated_quota.get("node_free_per_day", 3),
                }

            resp_data = {
                "conversation_id": conversation_id,
                "response": {
                    "role": "assistant",
                    "content": assistant_content,
                    "tool_calls": tool_calls_raw,
                    "model_used": model_used,
                    "response_time_ms": response_time_ms,
                },
                "usage": usage_info,
            }

            return jsonify(resp_data)

        except Exception as e:
            db.session.rollback()
            logger.exception("AI chat error for user %s: %s", user_id, e)
            return jsonify({"error": "AI chat failed. Please try again."}), 500

    # ==================================================================
    # GET /api/v1/ai/conversations — List conversations
    # ==================================================================

    @app.route("/api/v1/ai/conversations", methods=["GET"])
    @login_required
    def ai_list_conversations():
        """List the current user's active AI conversations.

        Query params:
            ?limit=20 (default 20, max 100)

        Returns:
            {"conversations": [...]}
        """
        from models import AIConversation

        limit = request.args.get("limit", 20, type=int)
        limit = max(1, min(limit, 100))

        conversations = AIConversation.query.filter_by(
            user_id=current_user.id,
            is_active=True,
        ).order_by(
            AIConversation.last_message_at.desc()
        ).limit(limit).all()

        return jsonify({
            "conversations": [conv.to_dict() for conv in conversations],
        })

    # ==================================================================
    # GET /api/v1/ai/conversations/<conversation_id> — Get with messages
    # ==================================================================

    @app.route("/api/v1/ai/conversations/<conversation_id>", methods=["GET"])
    @login_required
    def ai_get_conversation(conversation_id):
        """Get a conversation and all its messages.

        Returns:
            {"conversation": {...}, "messages": [...]}
        """
        from models import AIConversation, AIMessage

        conversation = AIConversation.query.filter_by(
            conversation_id=conversation_id,
            user_id=current_user.id,
        ).first()

        if not conversation:
            return jsonify({"error": "Conversation not found"}), 404

        messages = AIMessage.query.filter_by(
            conversation_id=conversation_id,
        ).order_by(
            AIMessage.created_at.asc()
        ).all()

        return jsonify({
            "conversation": conversation.to_dict(),
            "messages": [msg.to_dict() for msg in messages],
        })

    # ==================================================================
    # DELETE /api/v1/ai/conversations/<conversation_id> — Soft-delete
    # ==================================================================

    @app.route("/api/v1/ai/conversations/<conversation_id>", methods=["DELETE"])
    @login_required
    def ai_delete_conversation(conversation_id):
        """Soft-delete a conversation (set is_active = False).

        Returns:
            {"status": "deleted"}
        """
        from models import db, AIConversation

        conversation = AIConversation.query.filter_by(
            conversation_id=conversation_id,
            user_id=current_user.id,
        ).first()

        if not conversation:
            return jsonify({"error": "Conversation not found"}), 404

        conversation.is_active = False
        db.session.commit()

        return jsonify({"status": "deleted"})

    # ==================================================================
    # POST /api/v1/ai/conversations — Create new empty conversation
    # ==================================================================

    @app.route("/api/v1/ai/conversations", methods=["POST"])
    @login_required
    def ai_create_conversation():
        """Create a new empty AI conversation.

        Returns:
            {"conversation_id": "conv_...", "status": "created"}
        """
        from models import db, AIConversation

        conversation_id = f"conv_{secrets.token_hex(12)}"
        conversation = AIConversation(
            conversation_id=conversation_id,
            user_id=current_user.id,
            message_count=0,
            total_credits_used=0.0,
            is_active=True,
        )
        db.session.add(conversation)
        db.session.commit()

        return jsonify({
            "conversation_id": conversation_id,
            "status": "created",
        }), 201

    # ==================================================================
    # GET /api/v1/ai/tier — Get user's AI tier + usage
    # ==================================================================

    @app.route("/api/v1/ai/tier", methods=["GET"])
    def ai_tier_info():
        """Get the current user's AI tier, usage, and node discount status.

        For guests, returns free trial info.

        Returns:
            {tier, usage, quota, node_discount, ...}
        """
        if not current_user.is_authenticated:
            guest_used = session.get("guest_queries_used", 0)
            remaining = max(FREE_GUEST_QUERIES - guest_used, 0)
            return jsonify({
                "tier": "guest_trial",
                "tier_name": "Free Trial",
                "is_guest": True,
                "usage": {
                    "queries_used": guest_used,
                    "queries_remaining": remaining,
                    "queries_allowed": FREE_GUEST_QUERIES,
                },
            })

        from mystes_ai import get_ai_tier_info

        info = get_ai_tier_info(current_user)
        return jsonify(info)

    # ==================================================================
    # GET /api/v1/ai/pricing — Public AI tier pricing (no auth required)
    # ==================================================================

    @app.route("/api/v1/ai/pricing", methods=["GET"])
    def ai_pricing():
        """Get all AI tier options and pricing.

        Public endpoint — no authentication required.
        If the user is authenticated, includes personalised node discount info.

        Returns:
            {"tiers": {...}, "node_discount_pct": 25}
        """
        from mystes_ai import get_all_ai_tiers

        # Determine if the request has an authenticated user
        user = None
        try:
            if current_user and current_user.is_authenticated:
                user = current_user
        except Exception:
            pass

        tiers = get_all_ai_tiers(user=user)

        return jsonify({
            "tiers": tiers,
            "node_discount_pct": 25,
        })

    # ==================================================================
    # POST /api/v1/ai/save-deal — Save a deal to session (guests + auth)
    # ==================================================================

    @app.route("/api/v1/ai/save-deal", methods=["POST"])
    def ai_save_deal():
        """Save a deal from search results for later booking.

        Stores in session for guests, persists through registration.
        Max 5 saved deals per session.
        """
        data = request.get_json()
        if not data:
            return jsonify({"error": "No deal data provided"}), 400

        saved = session.get("saved_deals", [])
        deal_entry = {
            "title": data.get("title", "Saved Deal"),
            "price": data.get("price"),
            "currency": data.get("currency", "USD"),
            "savings_pct": data.get("savings_pct", 0),
            "market": data.get("market", ""),
            "vertical": data.get("vertical", ""),
            "details": data.get("details", {}),
            "saved_at": datetime.utcnow().isoformat(),
        }

        # Max 5 saved deals
        if len(saved) >= 5:
            saved = saved[-4:]  # Keep last 4, add new one
        saved.append(deal_entry)
        session["saved_deals"] = saved

        return jsonify({
            "saved": True,
            "deal_count": len(saved),
            "message": f"Deal saved! You have {len(saved)} saved deal{'s' if len(saved) != 1 else ''}.",
        })

    # ==================================================================
    # GET /api/v1/ai/saved-deals — Retrieve saved deals
    # ==================================================================

    @app.route("/api/v1/ai/saved-deals", methods=["GET"])
    def ai_get_saved_deals():
        """Get saved deals from session."""
        saved = session.get("saved_deals", [])
        return jsonify({
            "deals": saved,
            "count": len(saved),
        })

    # ==================================================================
    # POST /api/v1/ai/book-flight — Create deal and redirect to booking page
    # ==================================================================

    @app.route("/api/v1/ai/book-flight", methods=["POST"])
    def ai_book_flight():
        """Create a Deal record from flight card data and return deal_id for booking.

        The frontend sends the flight data from the AI chat card.
        We persist it as a Deal with the raw Amadeus offer data
        so the booking executor can use it for price_confirm + create_booking.
        """
        from models import Deal, db
        import hashlib

        if not current_user.is_authenticated:
            return jsonify({"error": "Please sign in to book flights"}), 401

        data = request.get_json()
        if not data:
            return jsonify({"error": "No flight data provided"}), 400

        # Generate a unique deal_id
        origin = data.get("origin", "")
        destination = data.get("destination", "")
        date = data.get("date", "")
        price = data.get("price", 0)
        airline = data.get("title", "").split(" ")[0] if data.get("title") else ""

        deal_hash = hashlib.md5(
            f"{origin}{destination}{date}{price}{airline}{datetime.utcnow().timestamp()}".encode()
        ).hexdigest()[:12]
        deal_id = f"PX{deal_hash.upper()}"

        # Parse the date
        departure_date = None
        if date:
            try:
                departure_date = datetime.strptime(date, "%Y-%m-%d").date()
            except ValueError:
                try:
                    departure_date = datetime.strptime(date, "%b %d, %Y").date()
                except ValueError:
                    pass

        # Get pricing info from deal data
        home_price = float(data.get("home_price", 0) or price or 0)
        arbitrage_price = float(data.get("arbitrage_price", 0) or price or 0)
        savings = float(data.get("savings", 0) or data.get("price_difference", 0) or 0)
        if savings == 0 and home_price > arbitrage_price:
            savings = home_price - arbitrage_price
        platform_fee = round(savings * 0.25, 2) if savings > 0 else 0
        savings_pct = float(data.get("savings_pct", 0) or 0)

        # Store Amadeus raw offer if present
        amadeus_offer_json = None
        raw_offer = data.get("raw_offer")
        if raw_offer:
            amadeus_offer_json = json.dumps(raw_offer)

        # Get flight number from title (e.g., "American AA 1234")
        title = data.get("title", "")
        flight_number = data.get("flight_number", "")
        if not flight_number and " " in title:
            parts = title.split(" ", 1)
            if len(parts) > 1:
                flight_number = parts[1]

        try:
            # Check if deal already exists
            existing = Deal.query.filter_by(deal_id=deal_id).first()
            if existing:
                return jsonify({"deal_id": existing.deal_id})

            destination_tag = abs(hash(deal_id)) % 2147483647

            deal = Deal(
                deal_id=deal_id,
                airline=airline or data.get("airline", ""),
                flight_number=flight_number,
                origin=origin,
                destination=destination,
                departure_date=departure_date,
                departure_time=data.get("departure_time", ""),
                arrival_time=data.get("arrival_time", ""),
                stops=int(data.get("stops", 0) or 0),
                home_market=data.get("home_market", "US"),
                home_price_usd=home_price if home_price > 0 else arbitrage_price,
                arbitrage_market=data.get("market", data.get("cheapest_market", "US")),
                arbitrage_price_usd=arbitrage_price if arbitrage_price > 0 else home_price,
                gross_savings_usd=savings,
                platform_fee_usd=platform_fee,
                user_savings_usd=round(savings - platform_fee, 2) if savings > 0 else 0,
                savings_percent=savings_pct,
                destination_tag=destination_tag,
                amadeus_offer_data=amadeus_offer_json,
                is_active=True,
                expires_at=datetime.utcnow() + __import__('datetime').timedelta(hours=24),
            )
            db.session.add(deal)
            db.session.commit()

            logger.info(f"Created deal {deal_id} for booking: {origin}->{destination} ${arbitrage_price}")
            return jsonify({"deal_id": deal_id})

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error creating deal for booking: {e}")
            return jsonify({"error": "Could not prepare booking"}), 500

    # Exempt JSON API endpoints from CSRF (they use session auth, not form submission)
    if csrf is not None:
        csrf.exempt(ai_chat)
        csrf.exempt(ai_create_conversation)
        csrf.exempt(ai_delete_conversation)
        csrf.exempt(ai_save_deal)
        csrf.exempt(ai_book_flight)
