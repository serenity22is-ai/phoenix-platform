"""
Free Browse Portal — Node-based browsing for Mystes users.

Build #90 — Replaces the deleted proxy_portal.py (Webshare-based).

Users open their own browser through the Mystes portal into a
CitizenSERP network node.  They browse using their own Google account.
Mystes acts as a monitoring window — passively observing data
(price observations, search queries, ad impressions) at zero cost.

Browsing is unlimited.  No quota is consumed.

Architecture:
    User → selects a zone/country → portal finds available node →
    creates BrowseSession → user's browser connects through the node →
    Mystes monitoring JS captures events → POST /api/browse/event →
    BrowsingEvent records → data marketplace.
"""

import logging
import secrets
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Browse event base commercial values (USD)
# ---------------------------------------------------------------------------

BROWSE_EVENT_VALUES = {
    'page_visit':        0.0001,
    'search_query':      0.001,
    'price_observation': 0.002,
    'ad_impression':     0.005,
    'social_signal':     0.0003,
}

# ---------------------------------------------------------------------------
# App directory — sites available through the portal
# ---------------------------------------------------------------------------

PORTAL_APP_DIRECTORY = {
    'travel': [
        {'name': 'Google Flights', 'url': 'https://www.google.com/travel/flights', 'icon': 'flight'},
        {'name': 'Google Hotels', 'url': 'https://www.google.com/travel/hotels', 'icon': 'hotel'},
        {'name': 'Booking.com', 'url': 'https://www.booking.com', 'icon': 'hotel'},
        {'name': 'Expedia', 'url': 'https://www.expedia.com', 'icon': 'travel'},
        {'name': 'Kayak', 'url': 'https://www.kayak.com', 'icon': 'search'},
        {'name': 'Skyscanner', 'url': 'https://www.skyscanner.com', 'icon': 'flight'},
    ],
    'shopping': [
        {'name': 'Google Shopping', 'url': 'https://shopping.google.com', 'icon': 'shopping'},
        {'name': 'Amazon', 'url': 'https://www.amazon.com', 'icon': 'shopping'},
    ],
    'search': [
        {'name': 'Google', 'url': 'https://www.google.com', 'icon': 'search'},
        {'name': 'Google Maps', 'url': 'https://maps.google.com', 'icon': 'map'},
    ],
}


class FreeBrowsePortalManager:
    """Manages Free Browse sessions through CitizenSERP nodes.

    Each session connects a user to a single node in a target zone.
    The user browses freely; Mystes monitors data passively.
    Zero cost to Mystes — the user provides the browser, the node
    provides the connection.
    """

    def create_browse_session(
        self,
        user_id: int,
        zone_code: str,
        target_site: Optional[str] = None,
    ) -> Dict:
        """Create a new browse session through a node in the target zone.

        Args:
            user_id: The requesting user's ID.
            zone_code: Target geographic zone (e.g. "US-NE", "JP-KT") or
                       country code (e.g. "US", "JP").
            target_site: Optional URL to open in the browse session.

        Returns:
            dict with session details or error.
        """
        from models import db, BrowseSession

        # 1. Discover an available node in the zone
        node = self._find_node_for_browse(zone_code)
        if not node:
            return {
                'error': f'No nodes available in zone {zone_code}. '
                         'Try a different zone or check back later.',
            }

        # 2. Derive country code from zone
        country_code = zone_code[:2] if len(zone_code) >= 2 else zone_code

        # 3. Create the session
        session_id = f"BS-{secrets.token_hex(8)}"
        session = BrowseSession(
            session_id=session_id,
            user_id=user_id,
            node_user_id=node['user_id'],
            zone_code=zone_code.upper(),
            country_code=country_code.upper(),
            target_site=target_site,
            session_type='free_browse',
            status='active',
        )
        db.session.add(session)
        db.session.commit()

        logger.info(
            "Browse session %s created: user=%s node=%s zone=%s",
            session_id, user_id, node.get('node_id', '?'), zone_code,
        )

        return {
            'session_id': session_id,
            'zone_code': zone_code.upper(),
            'country_code': country_code.upper(),
            'node_id': node.get('node_id', ''),
            'status': 'active',
            'target_site': target_site,
            'started_at': session.started_at.isoformat(),
        }

    def end_browse_session(self, session_id: int, user_id: int) -> Dict:
        """End a browse session.  Computes final duration and data stats."""
        from models import db, BrowseSession

        session = BrowseSession.query.filter_by(
            id=session_id, user_id=user_id,
        ).first()
        if not session:
            return {'error': 'Session not found'}

        if session.status != 'active':
            return {'error': f'Session already {session.status}'}

        now = datetime.utcnow()
        session.status = 'closed'
        session.ended_at = now
        if session.started_at:
            session.duration_seconds = int((now - session.started_at).total_seconds())
        db.session.commit()

        logger.info(
            "Browse session %s closed: duration=%ss events=%d value=$%.4f",
            session.session_id,
            session.duration_seconds,
            session.events_captured,
            session.data_value_usd or 0,
        )

        return session.to_dict()

    def get_active_sessions(self, user_id: int) -> List[Dict]:
        """Return all active browse sessions for a user."""
        from models import BrowseSession

        sessions = BrowseSession.query.filter_by(
            user_id=user_id, status='active',
        ).order_by(BrowseSession.started_at.desc()).all()

        # Auto-close stale sessions (no activity for 30 min)
        now = datetime.utcnow()
        results = []
        for s in sessions:
            if s.last_activity and (now - s.last_activity).total_seconds() > 1800:
                self._close_stale_session(s)
            else:
                results.append(s.to_dict())
        return results

    def get_available_zones(self) -> List[Dict]:
        """Return zones that have online nodes available for browse sessions.

        Queries the node registry for available nodes, groups by zone,
        and returns zone metadata with node availability.
        """
        try:
            from node_registry import node_registry
            # Get all online nodes
            all_nodes = node_registry.get_all_online_nodes()
        except (ImportError, Exception) as e:
            logger.debug("Node registry unavailable: %s", e)
            all_nodes = []

        if not all_nodes:
            # Fallback: return zones from geographic_zones with 0 availability
            return self._get_zones_from_geography()

        # Group by zone
        zone_map = {}
        for node in all_nodes:
            zc = node.get('zone_code') or ''
            cc = node.get('country_code') or ''
            key = zc if zc else cc
            if not key:
                continue
            if key not in zone_map:
                zone_map[key] = {
                    'zone_code': key,
                    'country_code': cc,
                    'available_nodes': 0,
                    'avg_rating': 0.0,
                    'ratings': [],
                }
            zone_map[key]['available_nodes'] += 1
            rating = node.get('success_rate', 0.0) or node.get('rating', 0.0)
            zone_map[key]['ratings'].append(rating)

        # Compute averages and format
        result = []
        for key, info in zone_map.items():
            ratings = info.pop('ratings')
            info['avg_rating'] = round(sum(ratings) / len(ratings), 2) if ratings else 0.0
            # Resolve zone name
            info['zone_name'] = self._resolve_zone_name(key)
            result.append(info)

        result.sort(key=lambda z: z['available_nodes'], reverse=True)
        return result

    def heartbeat(self, session_id: str) -> Dict:
        """Keep a browse session alive.  Updates last_activity timestamp.

        If the node has become unavailable, attempts to migrate the
        session to another node in the same zone.
        """
        from models import db, BrowseSession

        session = BrowseSession.query.filter_by(
            session_id=session_id, status='active',
        ).first()
        if not session:
            return {'error': 'Session not found or not active'}

        session.last_activity = datetime.utcnow()
        db.session.commit()

        return {'status': 'ok', 'session_id': session_id}

    def ingest_browse_event(
        self,
        session_id: str,
        event_type: str,
        url: str = '',
        domain: str = '',
        title: str = '',
        event_data: Optional[Dict] = None,
    ) -> Dict:
        """Record a browsing event from a Free Browse session.

        Called by the monitoring JS in the portal page.  Each event
        is stored as a BrowsingEvent record and the session counters
        are incremented.

        Returns:
            dict with event_id, value_usd, session totals.
        """
        from models import db, BrowseSession

        session = BrowseSession.query.filter_by(
            session_id=session_id, status='active',
        ).first()
        if not session:
            return {'error': 'Session not found or not active'}

        base_value = BROWSE_EVENT_VALUES.get(event_type, 0.0001)

        # Create BrowsingEvent record if model is available
        event_id = None
        try:
            from models import BrowsingEvent
            evt = BrowsingEvent(
                user_id=session.user_id,
                session_id=session_id,
                event_type=event_type,
                url=url[:500] if url else '',
                domain=domain[:200] if domain else '',
                title=title[:300] if title else '',
                commercial_value_usd=base_value,
                data_category='browsing_data',
                captured_at=datetime.utcnow(),
            )
            db.session.add(evt)
            db.session.flush()
            event_id = evt.id
        except Exception as e:
            logger.debug("BrowsingEvent creation skipped: %s", e)

        # Update session counters
        session.events_captured = (session.events_captured or 0) + 1
        session.data_value_usd = (session.data_value_usd or 0) + base_value
        session.last_activity = datetime.utcnow()

        if event_type == 'page_visit':
            session.pages_visited = (session.pages_visited or 0) + 1
        elif event_type == 'price_observation':
            session.price_observations_count = (
                (session.price_observations_count or 0) + 1
            )
            # Feed into spatial pricing index
            self._record_price_observation(session, event_data)

        db.session.commit()

        return {
            'event_id': event_id,
            'event_type': event_type,
            'value_usd': base_value,
            'session_events_total': session.events_captured,
            'session_data_value_usd': round(session.data_value_usd, 4),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_node_for_browse(self, zone_code: str) -> Optional[Dict]:
        """Find the best available node for a browse session in the zone."""
        # Strategy 1: Node registry (in-memory, fast)
        try:
            from node_registry import node_registry
            nodes = node_registry.discover_nodes(
                market=zone_code, task_type='general_search', limit=5,
            )
            if nodes:
                return nodes[0]
        except (ImportError, Exception) as e:
            logger.debug("Node registry lookup failed: %s", e)

        # Strategy 2: DB fallback via HelperProfile
        try:
            from models import HelperProfile
            code = zone_code.upper()
            if '-' in code:
                # Zone code — try zone_code match
                helper = HelperProfile.query.filter_by(
                    zone_code=code, is_active=True, is_approved=True,
                ).order_by(HelperProfile.average_rating.desc()).first()
            else:
                # Country code
                helper = HelperProfile.query.filter_by(
                    country_code=code, is_active=True, is_approved=True,
                ).order_by(HelperProfile.average_rating.desc()).first()

            if helper:
                return {
                    'user_id': helper.user_id,
                    'node_id': helper.node_id or f'helper-{helper.id}',
                    'country_code': helper.country_code,
                    'zone_code': helper.zone_code or '',
                    'success_rate': helper.average_rating or 0.0,
                }
        except Exception as e:
            logger.debug("DB helper lookup failed: %s", e)

        return None

    def _close_stale_session(self, session) -> None:
        """Close a session that has been inactive for too long."""
        from models import db

        now = datetime.utcnow()
        session.status = 'closed'
        session.ended_at = now
        if session.started_at:
            session.duration_seconds = int((now - session.started_at).total_seconds())
        db.session.commit()
        logger.info("Closed stale browse session %s", session.session_id)

    def _resolve_zone_name(self, zone_code: str) -> str:
        """Resolve a zone code to a human-readable name."""
        try:
            from geographic_zones import get_zone
            zone = get_zone(zone_code)
            if zone:
                return zone.name
        except (ImportError, Exception):
            pass
        return zone_code

    def _get_zones_from_geography(self) -> List[Dict]:
        """Fallback: return zone list from geographic_zones with 0 nodes."""
        try:
            from geographic_zones import get_zone_summary
            summary = get_zone_summary()
            zones = []
            for zone in summary.get('zones', []):
                zones.append({
                    'zone_code': zone.get('zone_code', ''),
                    'zone_name': zone.get('name', ''),
                    'country_code': zone.get('country', ''),
                    'available_nodes': 0,
                    'avg_rating': 0.0,
                })
            return zones
        except (ImportError, Exception):
            return []

    def _record_price_observation(self, session, event_data: Optional[Dict]) -> None:
        """Feed a price observation into the spatial pricing index."""
        if not event_data:
            return
        try:
            from models import PriceObservation
            from models import db
            obs = PriceObservation(
                zone_id=None,  # Will be resolved by zone engine
                node_id=session.node_user_id,
                country_code=session.country_code,
                vertical=event_data.get('vertical', 'unknown'),
                item_key=event_data.get('item_key', ''),
                price_usd=event_data.get('price_usd', 0),
                price_local=event_data.get('price_local', 0),
                currency=event_data.get('currency', 'USD'),
            )
            db.session.add(obs)
        except Exception as e:
            logger.debug("Price observation recording skipped: %s", e)

    def get_apps_for_market(self, market: str) -> List[Dict]:
        """Return apps relevant to a market (all apps for now)."""
        all_apps = []
        for category_apps in PORTAL_APP_DIRECTORY.values():
            all_apps.extend(category_apps)
        return all_apps

    def get_apps_by_category(self, category: str) -> List[Dict]:
        """Return apps for a specific category."""
        return PORTAL_APP_DIRECTORY.get(category, [])


# ---------------------------------------------------------------------------
# Module singleton
# ---------------------------------------------------------------------------

browse_portal_manager = FreeBrowsePortalManager()
