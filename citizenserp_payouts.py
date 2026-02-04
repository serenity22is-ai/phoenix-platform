"""
PHOENIX CitizenSERP Payout Manager

Distributes airline SaaS subscription revenue to residential proxy node operators
proportional to their verified uptime hours via XRPL micropayments.

Two income streams per node:
1. Variable: % of booking savings (P2P escrow system - already built)
2. Fixed: CitizenSERP micropayments from airline SaaS revenue pool (THIS module)

The fixed stream hedges against savings compression at market maturity.
When arbitrage margins shrink, CitizenSERP revenue provides steady baseline
income that prevents node attrition.

Flywheel: more airline subscribers -> more CitizenSERP revenue pool ->
higher node payouts -> more nodes join -> better data -> more subscribers

Usage:
    from citizenserp_payouts import citizenserp_manager

    # Record node coming online
    citizenserp_manager.record_node_online(user_id=42, wallet_address="rXXX...", ip_country="US")

    # Record node going offline
    citizenserp_manager.record_node_offline(user_id=42)

    # Calculate daily payout distribution
    citizenserp_manager.calculate_epoch_payouts()

    # Execute XRPL payments
    citizenserp_manager.distribute_payouts(epoch_id="EPOCH-2026-01-29")
"""

import json
import logging
import os
import secrets
from datetime import datetime, timedelta, date

logger = logging.getLogger(__name__)


# ============================================================
# Configuration
# ============================================================

CITIZENSERP_CONFIG = {
    "payout_percentage": float(os.getenv("CITIZENSERP_PAYOUT_PCT", "10.0")),
    "min_payout_rlusd": float(os.getenv("CITIZENSERP_MIN_PAYOUT", "0.01")),
    "heartbeat_stale_minutes": 15,
    "attestation_batch_size": 50,
    "max_payout_batch_size": 100,
    "rlusd_issuer": "rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De",
}


# ============================================================
# CitizenSERP Payout Manager
# ============================================================

class CitizenSERPPayoutManager:
    """Manages node uptime tracking, payout calculation, and XRPL distribution."""

    def __init__(self):
        self.config = CITIZENSERP_CONFIG

    # ----------------------------------------------------------
    # Node Session Management
    # ----------------------------------------------------------

    def record_node_online(self, user_id, wallet_address, ip_country=None, ip_zone=None):
        """Record a node coming online. Creates a new uptime session.
        ip_zone: optional sub-regional zone code (e.g. 'US-NE'). Auto-derived if not provided.
        """
        from models import db, NodeSession, User, UserWallet

        user = User.query.get(user_id)
        if not user:
            return {"error": "User not found"}
        if not user.is_helper_node:
            return {"error": "User is not registered as a helper node"}

        wallet = UserWallet.query.filter_by(
            user_id=user_id,
            wallet_address=wallet_address,
            is_verified=True,
        ).first()
        if not wallet:
            return {"error": "Wallet not verified"}

        # Auto-derive zone from helper profile if not provided
        if not ip_zone and ip_country:
            try:
                from models import HelperProfile
                helper = HelperProfile.query.filter_by(user_id=user_id).first()
                if helper and helper.zone_code:
                    ip_zone = helper.zone_code
                elif helper and helper.city:
                    try:
                        from geographic_zones import get_zone_for_city
                        zone = get_zone_for_city(helper.city)
                        if zone:
                            ip_zone = zone.zone_code
                            # Update helper profile with derived zone
                            helper.zone_code = ip_zone
                    except ImportError:
                        pass
            except Exception:
                pass

        # Close any existing active session for this user
        active = NodeSession.query.filter_by(
            user_id=user_id,
            status='active',
        ).all()
        for session in active:
            session.end_time = datetime.utcnow()
            session.duration_minutes = (session.end_time - session.start_time).total_seconds() / 60
            session.status = 'closed'

        session_id = f"NS-{secrets.token_hex(8)}"
        session = NodeSession(
            session_id=session_id,
            user_id=user_id,
            wallet_address=wallet_address,
            ip_country=ip_country,
            ip_zone=ip_zone,
            start_time=datetime.utcnow(),
            status='active',
        )
        db.session.add(session)
        db.session.commit()

        logger.info(f"Node online: user={user_id}, session={session_id}, country={ip_country}, zone={ip_zone}")
        return session.to_dict()

    def record_node_offline(self, user_id, session_id=None):
        """Record a node going offline. Closes the active session."""
        from models import db, NodeSession

        if session_id:
            session = NodeSession.query.filter_by(
                session_id=session_id,
                user_id=user_id,
                status='active',
            ).first()
        else:
            session = NodeSession.query.filter_by(
                user_id=user_id,
                status='active',
            ).order_by(NodeSession.start_time.desc()).first()

        if not session:
            return {"error": "No active session found"}

        session.end_time = datetime.utcnow()
        session.duration_minutes = (session.end_time - session.start_time).total_seconds() / 60
        session.status = 'closed'
        db.session.commit()

        logger.info(f"Node offline: user={user_id}, session={session.session_id}, "
                     f"duration={session.duration_minutes:.1f}min")
        return session.to_dict()

    def close_stale_sessions(self):
        """Close sessions with no heartbeat within the stale threshold."""
        from models import db, NodeSession

        stale_cutoff = datetime.utcnow() - timedelta(
            minutes=self.config["heartbeat_stale_minutes"]
        )

        stale_sessions = NodeSession.query.filter(
            NodeSession.status == 'active',
            NodeSession.start_time < stale_cutoff,
            NodeSession.xrpl_attestation_tx.is_(None),
        ).all()

        # Also check sessions that HAVE attestations but the attestation is old
        attested_stale = NodeSession.query.filter(
            NodeSession.status == 'active',
            NodeSession.created_at < stale_cutoff,
        ).all()

        all_stale = {s.id: s for s in stale_sessions}
        for s in attested_stale:
            all_stale[s.id] = s

        closed = 0
        for session in all_stale.values():
            session.end_time = datetime.utcnow()
            session.duration_minutes = (session.end_time - session.start_time).total_seconds() / 60
            session.status = 'stale'
            closed += 1

        if closed > 0:
            db.session.commit()
            logger.info(f"Closed {closed} stale node sessions")

        return closed

    def refresh_heartbeats(self, active_user_ids):
        """Update sessions based on confirmed online nodes."""
        from models import db, NodeSession, UserWallet

        if not active_user_ids:
            return

        # Find active sessions for users NOT in the active list -> mark stale
        orphan_sessions = NodeSession.query.filter(
            NodeSession.status == 'active',
            ~NodeSession.user_id.in_(active_user_ids),
        ).all()

        for session in orphan_sessions:
            session.end_time = datetime.utcnow()
            session.duration_minutes = (session.end_time - session.start_time).total_seconds() / 60
            session.status = 'stale'

        # For users in the active list without an active session, create one
        existing_active = set(
            row[0] for row in db.session.query(NodeSession.user_id).filter(
                NodeSession.status == 'active',
                NodeSession.user_id.in_(active_user_ids),
            ).all()
        )

        new_sessions = 0
        for uid in active_user_ids:
            if uid not in existing_active:
                wallet = UserWallet.query.filter_by(
                    user_id=uid,
                    is_primary=True,
                    is_verified=True,
                ).first()
                if wallet:
                    session = NodeSession(
                        session_id=f"NS-{secrets.token_hex(8)}",
                        user_id=uid,
                        wallet_address=wallet.wallet_address,
                        start_time=datetime.utcnow(),
                        status='active',
                    )
                    db.session.add(session)
                    new_sessions += 1

        if orphan_sessions or new_sessions:
            db.session.commit()

    # ----------------------------------------------------------
    # Uptime Queries
    # ----------------------------------------------------------

    def get_node_uptime(self, user_id, days_back=30):
        """Get node uptime statistics for a user."""
        from models import db, NodeSession, NodePayout

        cutoff = datetime.utcnow() - timedelta(days=days_back)

        sessions = NodeSession.query.filter(
            NodeSession.user_id == user_id,
            NodeSession.start_time >= cutoff,
            NodeSession.status.in_(['closed', 'stale', 'active']),
        ).all()

        total_minutes = 0
        longest_minutes = 0

        for s in sessions:
            if s.status == 'active':
                minutes = (datetime.utcnow() - s.start_time).total_seconds() / 60
            else:
                minutes = s.duration_minutes or 0
            total_minutes += minutes
            longest_minutes = max(longest_minutes, minutes)

        # Total earnings
        total_earned = db.session.query(
            db.func.sum(NodePayout.payout_amount_rlusd)
        ).filter(
            NodePayout.user_id == user_id,
            NodePayout.status == 'confirmed',
        ).scalar() or 0

        # Earnings in period
        period_earned = db.session.query(
            db.func.sum(NodePayout.payout_amount_rlusd)
        ).filter(
            NodePayout.user_id == user_id,
            NodePayout.status == 'confirmed',
            NodePayout.paid_at >= cutoff,
        ).scalar() or 0

        # Current session
        current_session = NodeSession.query.filter_by(
            user_id=user_id,
            status='active',
        ).first()

        return {
            "user_id": user_id,
            "days": days_back,
            "total_hours": round(total_minutes / 60, 2),
            "session_count": len(sessions),
            "avg_session_hours": round((total_minutes / 60) / max(len(sessions), 1), 2),
            "longest_session_hours": round(longest_minutes / 60, 2),
            "earnings_period_rlusd": round(period_earned, 6),
            "earnings_total_rlusd": round(total_earned, 6),
            "currently_online": current_session is not None,
            "current_session_id": current_session.session_id if current_session else None,
        }

    # ----------------------------------------------------------
    # Epoch Payout Calculation
    # ----------------------------------------------------------

    def calculate_epoch_payouts(self, payout_percentage=None, target_date=None):
        """Calculate payout distribution for a given day (defaults to yesterday)."""
        from models import db, NodeSession, NodePayoutEpoch, NodePayout, AirlineClient, HelperProfile, NodeConsentProfile

        if payout_percentage is None:
            payout_percentage = self.config["payout_percentage"]

        if target_date is None:
            target_date = date.today() - timedelta(days=1)

        epoch_id = f"EPOCH-{target_date.isoformat()}"

        # Check if epoch already exists
        existing = NodePayoutEpoch.query.filter_by(epoch_id=epoch_id).first()
        if existing:
            return {"error": f"Epoch {epoch_id} already calculated", "epoch": existing.to_dict()}

        # Calculate revenue pool from active airline clients
        period_start = datetime.combine(target_date, datetime.min.time())
        period_end = period_start + timedelta(days=1)

        active_clients = AirlineClient.query.filter_by(is_active=True).all()
        airline_monthly_revenue = sum(c.monthly_fee_usd for c in active_clients)

        # Include SERP API subscription revenue in payout pool
        serp_monthly_revenue = 0.0
        try:
            from models import CommercialAccount
            from serp_api import SERP_TIERS
            serp_accounts = CommercialAccount.query.filter(
                CommercialAccount.serp_tier != 'serp_free',
                CommercialAccount.is_active == True,
            ).all()
            serp_monthly_revenue = sum(
                SERP_TIERS.get(a.serp_tier, {}).get("monthly_price", 0)
                for a in serp_accounts
            )
        except Exception:
            pass  # SERP API module not yet available

        # Include ad intelligence revenue in payout pool (Build #65)
        ad_intel_monthly_revenue = 0.0
        try:
            from ad_intelligence import ad_intelligence_engine
            ad_intel_monthly_revenue = ad_intelligence_engine.get_monthly_revenue()
        except Exception:
            pass  # Ad intelligence module not yet available

        # Include browsing data buyer revenue in payout pool (Build #70)
        browsing_data_monthly_revenue = 0.0
        try:
            from models import CommercialAccount, CommercialAPIKey
            browsing_accounts = CommercialAccount.query.filter(
                CommercialAccount.is_active == True,
                CommercialAccount.browsing_tier.isnot(None),
                CommercialAccount.browsing_tier != 'browsing_free',
            ).all()
            from browsing_tiers import BROWSING_TIERS
            browsing_data_monthly_revenue = sum(
                BROWSING_TIERS.get(a.browsing_tier, {}).get("monthly_price", 0)
                for a in browsing_accounts
            )
        except Exception:
            pass  # Browsing tier module not yet available

        # Include free browse data value in payout pool (Build #90 flywheel)
        # Sum commercial value from browsing events captured during free browse sessions
        browse_event_daily_revenue = 0.0
        try:
            from models import BrowsingEvent
            browse_event_daily_revenue = db.session.query(
                db.func.sum(BrowsingEvent.commercial_value_usd)
            ).filter(
                BrowsingEvent.captured_at >= period_start,
                BrowsingEvent.captured_at < period_end,
            ).scalar() or 0.0
        except Exception:
            pass  # BrowsingEvent model not yet populated

        total_monthly_revenue = (
            airline_monthly_revenue + serp_monthly_revenue
            + ad_intel_monthly_revenue + browsing_data_monthly_revenue
        )
        daily_revenue = (total_monthly_revenue / 30.0) + browse_event_daily_revenue
        payout_pool = daily_revenue * (payout_percentage / 100.0)

        if payout_pool <= 0:
            logger.info(f"No revenue for epoch {epoch_id}")
            return {"error": "No revenue to distribute", "epoch_id": epoch_id}

        # Calculate per-node uptime hours in epoch window
        sessions = NodeSession.query.filter(
            NodeSession.start_time < period_end,
            db.or_(
                NodeSession.end_time >= period_start,
                db.and_(NodeSession.end_time.is_(None), NodeSession.status == 'active'),
            ),
            NodeSession.status.in_(['active', 'closed', 'stale']),
        ).all()

        # Aggregate hours per user, clamped to epoch window
        user_hours = {}
        user_wallets = {}

        for s in sessions:
            effective_start = max(s.start_time, period_start)
            effective_end = min(s.end_time or period_end, period_end)

            if effective_end <= effective_start:
                continue

            hours = (effective_end - effective_start).total_seconds() / 3600.0

            if s.user_id not in user_hours:
                user_hours[s.user_id] = 0
                user_wallets[s.user_id] = s.wallet_address
            user_hours[s.user_id] += hours

        # Apply quality score multipliers from buyer feedback (Build #70)
        quality_multipliers = {}
        try:
            from data_quality_feedback import quality_feedback_engine
            for user_id in user_hours:
                helper = HelperProfile.query.filter_by(user_id=user_id, is_active=True).first()
                if helper and helper.node_id:
                    quality_multipliers[user_id] = quality_feedback_engine.get_node_adjustment(helper.node_id)
                else:
                    quality_multipliers[user_id] = 1.0
        except Exception:
            for user_id in user_hours:
                quality_multipliers[user_id] = 1.0

        # Apply consent tier payout multipliers (Build #84)
        # Bronze 1.0x, Silver 1.15x, Gold 1.30x, Platinum 1.50x
        tier_multipliers = {}
        for user_id in user_hours:
            consent_profile = NodeConsentProfile.query.filter_by(user_id=user_id).first()
            tier_multipliers[user_id] = consent_profile.payout_multiplier if consent_profile else 1.0

        # Apply hot-zone surge multipliers (Build #90)
        # Nodes in zones with >2× average 15-min query volume earn up to 2× payout
        surge_multipliers = self.get_zone_surge_multipliers()
        user_surge = {}
        for user_id in user_hours:
            # Find the zone for this user's active session
            node_session = NodeSession.query.filter_by(
                user_id=user_id, status='active',
            ).first() or NodeSession.query.filter(
                NodeSession.user_id == user_id,
                NodeSession.start_time >= period_start,
            ).order_by(NodeSession.start_time.desc()).first()
            zone = node_session.ip_zone if node_session else None
            user_surge[user_id] = surge_multipliers.get(zone, 1.0) if zone else 1.0

        # Weighted hours = uptime_hours × quality × tier × surge
        user_weighted_hours = {
            uid: hours * quality_multipliers.get(uid, 1.0)
                       * tier_multipliers.get(uid, 1.0)
                       * user_surge.get(uid, 1.0)
            for uid, hours in user_hours.items()
        }
        total_weighted_hours = sum(user_weighted_hours.values())

        if total_weighted_hours <= 0:
            logger.info(f"No node uptime for epoch {epoch_id}")
            return {"error": "No node uptime recorded", "epoch_id": epoch_id}

        rate_per_hour = payout_pool / total_weighted_hours

        # Create epoch record
        epoch = NodePayoutEpoch(
            epoch_id=epoch_id,
            period_start=period_start,
            period_end=period_end,
            total_revenue_pool_usd=daily_revenue,
            payout_percentage=payout_percentage,
            total_payout_pool_usd=payout_pool,
            total_node_hours=sum(user_hours.values()),
            rate_per_hour_usd=rate_per_hour,
            status='calculating',
        )
        db.session.add(epoch)
        db.session.flush()

        # Create individual payout records
        min_payout = self.config["min_payout_rlusd"]
        nodes_eligible = 0
        nodes_skipped = 0

        for user_id, hours in user_hours.items():
            weighted = user_weighted_hours[user_id]
            payout_amount = weighted * rate_per_hour

            if payout_amount < min_payout:
                nodes_skipped += 1
                continue

            payout = NodePayout(
                epoch_id=epoch.id,
                user_id=user_id,
                wallet_address=user_wallets[user_id],
                uptime_hours=hours,
                payout_amount_rlusd=payout_amount,
                status='pending',
            )
            db.session.add(payout)
            nodes_eligible += 1

        epoch.nodes_paid = nodes_eligible
        epoch.status = 'calculated'
        db.session.commit()

        logger.info(
            f"Epoch {epoch_id}: pool=${payout_pool:.2f}, "
            f"rate=${rate_per_hour:.6f}/hr, "
            f"nodes={nodes_eligible} (skipped {nodes_skipped} below minimum)"
        )

        return {
            "epoch_id": epoch_id,
            "daily_revenue_usd": round(daily_revenue, 2),
            "payout_percentage": payout_percentage,
            "payout_pool_usd": round(payout_pool, 2),
            "total_node_hours": round(sum(user_hours.values()), 1),
            "total_weighted_hours": round(total_weighted_hours, 1),
            "rate_per_weighted_hour_usd": round(rate_per_hour, 6),
            "nodes_eligible": nodes_eligible,
            "nodes_skipped_below_minimum": nodes_skipped,
            "active_airline_clients": len(active_clients),
            "browsing_data_revenue": round(browsing_data_monthly_revenue / 30.0, 2),
            "browse_event_revenue": round(browse_event_daily_revenue, 4),
            "quality_adjusted": any(v != 1.0 for v in quality_multipliers.values()),
            "tier_adjusted": any(v != 1.0 for v in tier_multipliers.values()),
            "surge_adjusted": any(v != 1.0 for v in user_surge.values()),
            "surge_zones": {z: m for z, m in surge_multipliers.items() if m > 1.0},
            "status": "calculated",
        }

    # ----------------------------------------------------------
    # XRPL Distribution
    # ----------------------------------------------------------

    def distribute_payouts(self, epoch_id):
        """Execute XRPL RLUSD payments for a calculated epoch."""
        from models import db, NodePayoutEpoch, NodePayout, HelperProfile

        epoch = NodePayoutEpoch.query.filter_by(epoch_id=epoch_id).first()
        if not epoch:
            return {"error": f"Epoch {epoch_id} not found"}
        if epoch.status != 'calculated':
            return {"error": f"Epoch status is '{epoch.status}', expected 'calculated'"}

        epoch.status = 'distributing'
        batch_id = f"BATCH-{secrets.token_hex(6)}"
        epoch.distribution_tx_batch = batch_id
        db.session.commit()

        wallet_seed = os.getenv("XRPL_WALLET_SEED")
        wallet_address = os.getenv("XRPL_WALLET_ADDRESS")
        xrpl_network = os.getenv("XRPL_NETWORK", "testnet")

        if not wallet_seed or not wallet_address:
            epoch.status = 'failed'
            db.session.commit()
            return {"error": "XRPL wallet not configured"}

        # XRPL client setup
        try:
            from xrpl.clients import JsonRpcClient
            from xrpl.wallet import Wallet
            from xrpl.models.transactions import Payment, Memo
            from xrpl.models.amounts import IssuedCurrencyAmount
            from xrpl.transaction import sign, submit_and_wait

            networks = {
                "mainnet": "https://xrplcluster.com",
                "testnet": "https://s.altnet.rippletest.net:51234",
            }
            client = JsonRpcClient(networks.get(xrpl_network, networks["testnet"]))
            wallet = Wallet.from_seed(wallet_seed)

        except ImportError:
            logger.warning("xrpl library not available, simulating payouts")
            client = None
            wallet = None

        # Process payouts in batches
        payouts = NodePayout.query.filter_by(
            epoch_id=epoch.id,
            status='pending',
        ).all()

        batch_size = self.config["max_payout_batch_size"]
        success_count = 0
        fail_count = 0

        for i in range(0, len(payouts), batch_size):
            batch = payouts[i:i + batch_size]

            for payout in batch:
                try:
                    if client and wallet:
                        payment_tx = Payment(
                            account=wallet.address,
                            destination=payout.wallet_address,
                            amount=IssuedCurrencyAmount(
                                currency="RLUSD",
                                issuer=self.config["rlusd_issuer"],
                                value=str(round(payout.payout_amount_rlusd, 6)),
                            ),
                            memos=[Memo(
                                memo_type=bytes("citizenserp_payout", "utf-8").hex(),
                                memo_data=bytes(json.dumps({
                                    "epoch": epoch.epoch_id,
                                    "hours": round(payout.uptime_hours, 2),
                                    "batch": batch_id,
                                }), "utf-8").hex(),
                            )],
                        )
                        signed_tx = sign(payment_tx, wallet)
                        response = submit_and_wait(signed_tx, client)

                        tx_hash = response.result.get("hash", "")
                        payout.tx_hash = tx_hash
                        payout.status = 'confirmed'
                        payout.paid_at = datetime.utcnow()
                    else:
                        # Simulation mode (no XRPL library)
                        payout.tx_hash = f"SIM-{secrets.token_hex(16)}"
                        payout.status = 'confirmed'
                        payout.paid_at = datetime.utcnow()

                    # Update helper earnings
                    helper = HelperProfile.query.filter_by(user_id=payout.user_id).first()
                    if helper:
                        helper.total_earned_rlusd = (helper.total_earned_rlusd or 0) + payout.payout_amount_rlusd

                    success_count += 1

                except Exception as e:
                    logger.error(f"Payout failed for user {payout.user_id}: {e}")
                    payout.status = 'failed'
                    fail_count += 1

            db.session.commit()

        # Finalize epoch
        if fail_count > len(payouts) * 0.5:
            epoch.status = 'failed'
        else:
            epoch.status = 'completed'
        epoch.completed_at = datetime.utcnow()
        epoch.nodes_paid = success_count
        db.session.commit()

        logger.info(
            f"Distribution {epoch_id}: {success_count} succeeded, {fail_count} failed"
        )

        return {
            "epoch_id": epoch_id,
            "batch_id": batch_id,
            "total_payouts": len(payouts),
            "success": success_count,
            "failed": fail_count,
            "status": epoch.status,
        }

    # ----------------------------------------------------------
    # On-Chain Uptime Attestation
    # ----------------------------------------------------------

    def submit_uptime_attestation(self, user_ids_batch):
        """Submit on-chain attestation proving nodes were verified online."""
        from models import db, NodeSession

        wallet_seed = os.getenv("XRPL_WALLET_SEED")
        wallet_address = os.getenv("XRPL_WALLET_ADDRESS")
        xrpl_network = os.getenv("XRPL_NETWORK", "testnet")

        attestation_data = {
            "type": "uptime_attestation",
            "ts": datetime.utcnow().isoformat(),
            "nodes": user_ids_batch,
            "count": len(user_ids_batch),
        }

        tx_hash = None

        try:
            from xrpl.clients import JsonRpcClient
            from xrpl.wallet import Wallet
            from xrpl.models.transactions import Payment, Memo
            from xrpl.utils import xrp_to_drops
            from xrpl.transaction import sign, submit_and_wait

            if not wallet_seed:
                logger.debug("XRPL wallet not configured, skipping attestation")
                return None

            networks = {
                "mainnet": "https://xrplcluster.com",
                "testnet": "https://s.altnet.rippletest.net:51234",
            }
            client = JsonRpcClient(networks.get(xrpl_network, networks["testnet"]))
            wallet = Wallet.from_seed(wallet_seed)

            # Self-payment with memo (cheapest tx type)
            attestation_tx = Payment(
                account=wallet.address,
                destination=wallet.address,
                amount=xrp_to_drops(0),
                memos=[Memo(
                    memo_type=bytes("uptime_attestation", "utf-8").hex(),
                    memo_data=bytes(json.dumps(attestation_data), "utf-8").hex(),
                )],
            )
            signed_tx = sign(attestation_tx, wallet)
            response = submit_and_wait(signed_tx, client)
            tx_hash = response.result.get("hash", "")

        except ImportError:
            logger.debug("xrpl library not available, skipping attestation")
            tx_hash = f"SIM-ATT-{secrets.token_hex(8)}"
        except Exception as e:
            logger.error(f"Attestation submission failed: {e}")
            return None

        # Store attestation tx in active sessions for these users
        if tx_hash:
            sessions = NodeSession.query.filter(
                NodeSession.user_id.in_(user_ids_batch),
                NodeSession.status == 'active',
            ).all()
            for session in sessions:
                session.xrpl_attestation_tx = tx_hash
            db.session.commit()

        return tx_hash

    # ----------------------------------------------------------
    # Surge Pricing
    # ----------------------------------------------------------

    def get_zone_surge_multipliers(self):
        """Fetch active surge multipliers per zone from the hot zone engine.

        Returns dict of zone_code -> multiplier (1.0 if no surge).
        Surge activates when a zone's 15-min query volume exceeds 2× its
        rolling average.  Multiplier caps at 2.0× and lasts for 1 hour.
        """
        try:
            from hot_zone_economics import hot_zone_engine
            from models import db, NodeSession

            # Get all active zones
            active_zones = [
                row[0] for row in db.session.query(
                    db.func.distinct(NodeSession.ip_zone)
                ).filter(
                    NodeSession.status == 'active',
                    NodeSession.ip_zone.isnot(None),
                ).all()
            ]

            multipliers = {}
            for zone_code in active_zones:
                surge = hot_zone_engine.detect_surge(zone_code)
                if surge and surge.get("surge_active"):
                    multipliers[zone_code] = surge["surge_multiplier"]
                else:
                    multipliers[zone_code] = 1.0

            return multipliers

        except Exception as exc:
            logger.debug("Could not fetch surge multipliers: %s", exc)
            return {}

    # ----------------------------------------------------------
    # History & Stats
    # ----------------------------------------------------------

    def get_payout_history(self, user_id, limit=30):
        """Get payout history for a node operator."""
        from models import NodePayout, NodePayoutEpoch

        payouts = NodePayout.query.filter_by(
            user_id=user_id,
        ).join(NodePayoutEpoch).order_by(
            NodePayoutEpoch.period_start.desc()
        ).limit(limit).all()

        result = []
        for p in payouts:
            epoch = p.epoch
            result.append({
                "epoch_id": epoch.epoch_id,
                "period_date": epoch.period_start.strftime("%Y-%m-%d") if epoch.period_start else None,
                "uptime_hours": round(p.uptime_hours, 2),
                "payout_amount_rlusd": round(p.payout_amount_rlusd, 6),
                "rate_per_hour_usd": round(epoch.rate_per_hour_usd, 6),
                "tx_hash": p.tx_hash,
                "status": p.status,
                "paid_at": p.paid_at.isoformat() if p.paid_at else None,
            })

        return result

    def get_network_stats(self):
        """Get public network statistics."""
        from models import db, NodeSession, NodePayoutEpoch, NodePayout, User

        now = datetime.utcnow()

        # Active nodes right now
        nodes_online = NodeSession.query.filter_by(status='active').count()

        # Total registered nodes
        total_nodes = User.query.filter_by(is_helper_node=True).count()

        # Nodes by country
        country_counts = db.session.query(
            NodeSession.ip_country,
            db.func.count(db.func.distinct(NodeSession.user_id)),
        ).filter(
            NodeSession.status == 'active',
            NodeSession.ip_country.isnot(None),
        ).group_by(NodeSession.ip_country).all()

        nodes_by_country = {c: n for c, n in country_counts if c}

        # Uptime hours (last 24h, 7d, 30d)
        def total_hours_since(hours_ago):
            cutoff = now - timedelta(hours=hours_ago)
            result = db.session.query(
                db.func.sum(NodeSession.duration_minutes)
            ).filter(
                NodeSession.start_time >= cutoff,
                NodeSession.status.in_(['closed', 'stale']),
            ).scalar()
            return round((result or 0) / 60, 1)

        # Latest epoch
        latest_epoch = NodePayoutEpoch.query.filter(
            NodePayoutEpoch.status.in_(['completed', 'calculated']),
        ).order_by(NodePayoutEpoch.period_start.desc()).first()

        # Total RLUSD distributed
        total_distributed = db.session.query(
            db.func.sum(NodePayout.payout_amount_rlusd)
        ).filter(
            NodePayout.status == 'confirmed',
        ).scalar() or 0

        # Nodes by zone (sub-regional)
        zone_counts = db.session.query(
            NodeSession.ip_zone,
            db.func.count(db.func.distinct(NodeSession.user_id)),
        ).filter(
            NodeSession.status == 'active',
            NodeSession.ip_zone.isnot(None),
        ).group_by(NodeSession.ip_zone).all()

        nodes_by_zone = {z: n for z, n in zone_counts if z}

        return {
            "nodes_online": nodes_online,
            "total_registered_nodes": total_nodes,
            "nodes_by_country": nodes_by_country,
            "nodes_by_zone": nodes_by_zone,
            "network_hours_24h": total_hours_since(24),
            "network_hours_7d": total_hours_since(168),
            "network_hours_30d": total_hours_since(720),
            "total_rlusd_distributed": round(total_distributed, 2),
            "latest_epoch": latest_epoch.to_dict() if latest_epoch else None,
        }


# ============================================================
# Module-level singleton
# ============================================================

citizenserp_manager = CitizenSERPPayoutManager()
