"""
ZoneEngine core — Build #78 (Location-Aware Pricing Zones)

Provides geographic zone management, node location tracking, price
observation recording, and promotion detection for location-aware
pricing across verticals (flights, hotels, cruises, rentals).
"""

import logging
import math
import uuid
import json
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Resolution hierarchy (finest to coarsest)
# ---------------------------------------------------------------------------
RESOLUTION_ORDER = ["micro", "district", "city", "region", "country"]


class ZoneEngine:
    """
    Singleton engine that manages pricing zones, resolves node locations
    into zones, records price observations, and detects geo-fenced
    promotions.  All DB model imports are lazy to avoid circular imports.
    """

    # ------------------------------------------------------------------
    # 1. Initialisation
    # ------------------------------------------------------------------
    def __init__(self) -> None:
        self.logger = logging.getLogger(f"{__name__}.ZoneEngine")
        self._zone_cache: Dict[str, Any] = {}
        self.logger.info("ZoneEngine initialised")

    # ------------------------------------------------------------------
    # 2. Seed from geographic_zones registry
    # ------------------------------------------------------------------
    def seed_from_geographic_zones(self) -> int:
        """
        Import every entry in ZONE_REGISTRY and create corresponding
        PricingZone rows (country-level parent, then region-level child).
        Idempotent — existing zones are skipped.  Returns the count of
        newly created zones.
        """
        from geographic_zones import ZONE_REGISTRY
        from models import PricingZone, db

        created = 0
        seen_countries: set = set()

        for zone_code, geo_zone in ZONE_REGISTRY.items():
            country = geo_zone.country

            # --- country-level parent --------------------------------
            if country not in seen_countries:
                seen_countries.add(country)
                existing = PricingZone.query.filter_by(
                    zone_id=country, resolution="country"
                ).first()
                if existing is None:
                    try:
                        parent = PricingZone(
                            zone_id=country,
                            resolution="country",
                            parent_zone_id=None,
                            name=country,
                            lat_center=geo_zone.lat_center,
                            lon_center=geo_zone.lon_center,
                            radius_km=1000.0,
                            is_active=True,
                            created_at=datetime.now(timezone.utc),
                        )
                        db.session.add(parent)
                        created += 1
                        self.logger.debug("Created country zone %s", country)
                    except Exception as exc:
                        self.logger.error(
                            "Failed to create country zone %s: %s", country, exc
                        )
                        db.session.rollback()
                        continue

            # --- region-level zone -----------------------------------
            existing = PricingZone.query.filter_by(
                zone_id=zone_code, resolution="region"
            ).first()
            if existing is None:
                try:
                    region = PricingZone(
                        zone_id=zone_code,
                        resolution="region",
                        parent_zone_id=country,
                        name=geo_zone.name,
                        lat_center=geo_zone.lat_center,
                        lon_center=geo_zone.lon_center,
                        radius_km=200.0,
                        is_active=True,
                        created_at=datetime.now(timezone.utc),
                    )
                    db.session.add(region)
                    created += 1
                    self.logger.debug("Created region zone %s", zone_code)
                except Exception as exc:
                    self.logger.error(
                        "Failed to create region zone %s: %s", zone_code, exc
                    )
                    db.session.rollback()
                    continue

        try:
            db.session.commit()
            self.logger.info(
                "seed_from_geographic_zones complete — %d zones created", created
            )
        except Exception as exc:
            db.session.rollback()
            self.logger.error("Commit failed during seeding: %s", exc)
            created = 0

        return created

    # ------------------------------------------------------------------
    # 3. Haversine distance
    # ------------------------------------------------------------------
    @staticmethod
    def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Return the great-circle distance in kilometres between two points."""
        R = 6371.0
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        d_phi = math.radians(lat2 - lat1)
        d_lambda = math.radians(lon2 - lon1)

        a = (
            math.sin(d_phi / 2.0) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
        )
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
        return R * c

    # ------------------------------------------------------------------
    # 4. Resolve a lat/lon to the finest matching zone
    # ------------------------------------------------------------------
    def resolve_location(
        self, lat: float, lon: float, country_code: str = None
    ) -> Optional[str]:
        """
        Walk from the finest resolution upward and return the first zone
        whose centre is within its own radius_km of the given point.
        If *country_code* is supplied, prefer zones belonging to that
        country.
        """
        from models import PricingZone

        try:
            zones = PricingZone.query.filter_by(is_active=True).all()
        except Exception as exc:
            self.logger.error("resolve_location query failed: %s", exc)
            return None

        if not zones:
            return None

        # Bucket by resolution
        by_resolution: Dict[str, List] = {r: [] for r in RESOLUTION_ORDER}
        for z in zones:
            res = z.resolution or "region"
            if res in by_resolution:
                by_resolution[res].append(z)

        # Walk finest → coarsest
        for res in RESOLUTION_ORDER:
            candidates = by_resolution.get(res, [])
            if not candidates:
                continue

            best_zone = None
            best_dist = float("inf")

            for z in candidates:
                dist = self.haversine_km(lat, lon, z.lat_center, z.lon_center)
                radius = z.radius_km if z.radius_km else 500.0

                if dist > radius:
                    continue

                # Prefer matching country
                if country_code and z.parent_zone_id:
                    parent_country = z.parent_zone_id.split("-")[0]
                    if parent_country == country_code and dist < best_dist:
                        best_dist = dist
                        best_zone = z
                        continue
                    elif parent_country == country_code:
                        continue

                if dist < best_dist:
                    best_dist = dist
                    best_zone = z

            if best_zone is not None:
                return best_zone.zone_id

        return None

    # ------------------------------------------------------------------
    # 5. Resolve zone for a specific node (considers city name)
    # ------------------------------------------------------------------
    def resolve_zone_for_node(
        self,
        node_id: str,
        lat: float,
        lon: float,
        country_code: str = None,
        city: str = None,
    ) -> str:
        """
        Wrapper around resolve_location that also attempts city-name
        matching when a *city* string is provided.
        """
        from models import PricingZone

        # Try city name match first
        if city:
            try:
                city_upper = city.strip().upper()
                zones = PricingZone.query.filter_by(is_active=True).all()
                for z in zones:
                    if z.name and z.name.strip().upper() == city_upper:
                        self.logger.debug(
                            "Node %s matched zone %s by city name '%s'",
                            node_id, z.zone_id, city,
                        )
                        return z.zone_id
            except Exception as exc:
                self.logger.warning("City-name lookup failed: %s", exc)

        # Fall back to geographic resolution
        zone_id = self.resolve_location(lat, lon, country_code=country_code)
        if zone_id:
            return zone_id

        # Last resort: use country_code itself
        if country_code:
            return country_code

        return "UNKNOWN"

    # ------------------------------------------------------------------
    # 6. Record a node's location
    # ------------------------------------------------------------------
    def record_node_location(
        self,
        node_id: str,
        user_id: int,
        lat: float,
        lon: float,
        accuracy_m: float = None,
        source: str = "ip_geolocation",
    ) -> dict:
        """
        Persist a node location observation after checking user consent.
        """
        if not self._check_location_consent(user_id):
            return {"recorded": False, "reason": "no_consent"}

        from models import NodeLocationHistory, db

        zone_id = self.resolve_location(lat, lon)

        try:
            entry = NodeLocationHistory(
                node_id=node_id,
                user_id=user_id,
                lat=lat,
                lon=lon,
                accuracy_m=accuracy_m,
                source=source,
                resolved_zone_id=zone_id,
                recorded_at=datetime.now(timezone.utc),
            )
            db.session.add(entry)
            db.session.commit()
            self.logger.info(
                "Recorded location for node %s in zone %s", node_id, zone_id
            )
            return {"recorded": True, "zone_id": zone_id}
        except Exception as exc:
            db.session.rollback()
            self.logger.error("record_node_location failed: %s", exc)
            return {"recorded": False, "reason": str(exc)}

    # ------------------------------------------------------------------
    # 7. Get node locations in a zone (last 24 h)
    # ------------------------------------------------------------------
    def get_node_locations_in_zone(self, zone_id: str) -> List[dict]:
        from models import NodeLocationHistory

        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        try:
            rows = (
                NodeLocationHistory.query
                .filter_by(resolved_zone_id=zone_id)
                .filter(NodeLocationHistory.recorded_at >= cutoff)
                .all()
            )
            return [
                {
                    "node_id": r.node_id,
                    "lat": r.lat,
                    "lon": r.lon,
                    "recorded_at": r.recorded_at.isoformat() if r.recorded_at else None,
                }
                for r in rows
            ]
        except Exception as exc:
            self.logger.error("get_node_locations_in_zone failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # 8. Record a price observation
    # ------------------------------------------------------------------
    def record_observation(
        self,
        vertical: str,
        item_key: str,
        price_usd: float,
        country_code: str,
        zone_id: str = None,
        node_id: str = None,
        lat: float = None,
        lon: float = None,
        price_local: float = None,
        currency: str = None,
        source_tier: int = None,
        is_promoted: bool = False,
        promotion_type: str = None,
        source_url: str = None,
    ) -> dict:
        """
        Create a PriceObservation row.  Zone is resolved from lat/lon
        when not explicitly provided.
        """
        from models import PriceObservation, db

        # Resolve zone_id if missing
        if zone_id is None and lat is not None and lon is not None:
            zone_id = self.resolve_location(lat, lon, country_code=country_code)
        if zone_id is None and country_code:
            zone_id = country_code

        observation_id = "OBS-" + uuid.uuid4().hex[:12]

        try:
            obs = PriceObservation(
                observation_id=observation_id,
                vertical=vertical,
                item_key=item_key,
                price_usd=price_usd,
                price_local=price_local,
                currency=currency,
                country_code=country_code,
                zone_id=zone_id,
                node_id=node_id,
                lat=lat,
                lon=lon,
                source_tier=source_tier,
                is_promoted=is_promoted,
                promotion_type=promotion_type,
                source_url=source_url,
                observed_at=datetime.now(timezone.utc),
            )
            db.session.add(obs)
            db.session.commit()
            self.logger.info(
                "Recorded observation %s for %s/%s in zone %s",
                observation_id, vertical, item_key, zone_id,
            )
            return {"observation_id": observation_id, "zone_id": zone_id}
        except Exception as exc:
            db.session.rollback()
            self.logger.error("record_observation failed: %s", exc)
            return {"observation_id": None, "zone_id": zone_id, "error": str(exc)}

    # ------------------------------------------------------------------
    # 9. Get prices for a zone (with optional child roll-up)
    # ------------------------------------------------------------------
    def get_zone_prices(
        self,
        zone_id: str,
        vertical: str = None,
        item_key: str = None,
        hours_back: int = 24,
        include_children: bool = True,
    ) -> dict:
        from models import PriceObservation, PricingZone

        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)

        try:
            query = PriceObservation.query.filter(
                PriceObservation.observed_at >= cutoff
            )

            if include_children:
                query = query.filter(
                    PriceObservation.zone_id.like(f"{zone_id}%")
                )
            else:
                query = query.filter_by(zone_id=zone_id)

            if vertical:
                query = query.filter_by(vertical=vertical)
            if item_key:
                query = query.filter_by(item_key=item_key)

            observations = query.all()
        except Exception as exc:
            self.logger.error("get_zone_prices query failed: %s", exc)
            return {"zone_id": zone_id, "error": str(exc)}

        if not observations:
            return {
                "zone_id": zone_id,
                "observation_count": 0,
                "avg_price": None,
                "min_price": None,
                "max_price": None,
                "price_by_sub_zone": {},
                "promoted_deals": [],
            }

        prices = [o.price_usd for o in observations if o.price_usd is not None]
        avg_price = sum(prices) / len(prices) if prices else None
        min_price = min(prices) if prices else None
        max_price = max(prices) if prices else None

        # Sub-zone breakdown
        sub_zone_map: Dict[str, List[float]] = {}
        for o in observations:
            sz = o.zone_id or zone_id
            sub_zone_map.setdefault(sz, [])
            if o.price_usd is not None:
                sub_zone_map[sz].append(o.price_usd)

        price_by_sub_zone = {}
        for sz, sz_prices in sub_zone_map.items():
            if sz_prices:
                price_by_sub_zone[sz] = {
                    "avg_price": round(sum(sz_prices) / len(sz_prices), 2),
                    "min_price": round(min(sz_prices), 2),
                    "max_price": round(max(sz_prices), 2),
                    "count": len(sz_prices),
                }

        # Promoted deals
        promoted_deals = [
            {
                "observation_id": o.observation_id,
                "item_key": o.item_key,
                "price_usd": o.price_usd,
                "promotion_type": o.promotion_type,
                "zone_id": o.zone_id,
            }
            for o in observations
            if o.is_promoted
        ]

        return {
            "zone_id": zone_id,
            "observation_count": len(observations),
            "avg_price": round(avg_price, 2) if avg_price else None,
            "min_price": round(min_price, 2) if min_price else None,
            "max_price": round(max_price, 2) if max_price else None,
            "price_by_sub_zone": price_by_sub_zone,
            "promoted_deals": promoted_deals,
        }

    # ------------------------------------------------------------------
    # 10. Compare prices across zones for a given item
    # ------------------------------------------------------------------
    def compare_zone_prices(
        self,
        item_key: str,
        vertical: str,
        zone_ids: List[str] = None,
    ) -> dict:
        from models import PriceObservation

        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

        try:
            base_query = PriceObservation.query.filter(
                PriceObservation.item_key == item_key,
                PriceObservation.vertical == vertical,
                PriceObservation.observed_at >= cutoff,
            )

            if zone_ids:
                base_query = base_query.filter(
                    PriceObservation.zone_id.in_(zone_ids)
                )

            observations = base_query.all()
        except Exception as exc:
            self.logger.error("compare_zone_prices failed: %s", exc)
            return {"item_key": item_key, "vertical": vertical, "error": str(exc)}

        # Group by zone
        zone_prices: Dict[str, List[float]] = {}
        for o in observations:
            if o.zone_id and o.price_usd is not None:
                zone_prices.setdefault(o.zone_id, []).append(o.price_usd)

        zones_result = []
        for zid, prices in zone_prices.items():
            avg = round(sum(prices) / len(prices), 2)
            zones_result.append({
                "zone_id": zid,
                "avg_price": avg,
                "observation_count": len(prices),
            })

        zones_result.sort(key=lambda z: z["avg_price"])

        cheapest = zones_result[0] if zones_result else None
        most_expensive = zones_result[-1] if zones_result else None

        spread_pct = None
        if cheapest and most_expensive and cheapest["avg_price"] > 0:
            spread_pct = round(
                (most_expensive["avg_price"] - cheapest["avg_price"])
                / cheapest["avg_price"]
                * 100,
                2,
            )

        return {
            "item_key": item_key,
            "vertical": vertical,
            "zones": zones_result,
            "cheapest_zone": cheapest["zone_id"] if cheapest else None,
            "most_expensive_zone": most_expensive["zone_id"] if most_expensive else None,
            "price_spread_pct": spread_pct,
        }

    # ------------------------------------------------------------------
    # 11. Zone price trend (daily averages over N days)
    # ------------------------------------------------------------------
    def get_zone_price_trend(
        self,
        zone_id: str,
        item_key: str,
        vertical: str,
        days_back: int = 7,
    ) -> dict:
        from models import PriceObservation

        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

        try:
            observations = (
                PriceObservation.query
                .filter(
                    PriceObservation.zone_id == zone_id,
                    PriceObservation.item_key == item_key,
                    PriceObservation.vertical == vertical,
                    PriceObservation.observed_at >= cutoff,
                )
                .order_by(PriceObservation.observed_at.asc())
                .all()
            )
        except Exception as exc:
            self.logger.error("get_zone_price_trend failed: %s", exc)
            return {"zone_id": zone_id, "error": str(exc)}

        # Group by date
        daily: Dict[str, List[float]] = {}
        for o in observations:
            if o.observed_at and o.price_usd is not None:
                day_key = o.observed_at.strftime("%Y-%m-%d")
                daily.setdefault(day_key, []).append(o.price_usd)

        trend = []
        for day_key in sorted(daily.keys()):
            prices = daily[day_key]
            trend.append({
                "date": day_key,
                "avg_price": round(sum(prices) / len(prices), 2),
                "min_price": round(min(prices), 2),
                "max_price": round(max(prices), 2),
                "count": len(prices),
            })

        return {
            "zone_id": zone_id,
            "item_key": item_key,
            "vertical": vertical,
            "days_back": days_back,
            "trend": trend,
        }

    # ------------------------------------------------------------------
    # 12. Detect geo-fenced promotions
    # ------------------------------------------------------------------
    def detect_promotions(
        self,
        zone_id: str,
        vertical: str = None,
        hours_back: int = 6,
    ) -> List[dict]:
        from models import PriceObservation, PricingZone

        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)

        try:
            zone = PricingZone.query.filter_by(zone_id=zone_id).first()
            if not zone or not zone.parent_zone_id:
                self.logger.debug(
                    "Cannot detect promotions — zone %s has no parent", zone_id
                )
                return []

            # Sibling zones (same parent, excluding self)
            siblings = (
                PricingZone.query
                .filter_by(parent_zone_id=zone.parent_zone_id, is_active=True)
                .filter(PricingZone.zone_id != zone_id)
                .all()
            )
            sibling_ids = [s.zone_id for s in siblings]

            if not sibling_ids:
                return []

            # This zone's recent observations
            zone_obs = (
                PriceObservation.query
                .filter(
                    PriceObservation.zone_id == zone_id,
                    PriceObservation.observed_at >= cutoff,
                )
                .all()
            )
            if vertical:
                zone_obs = [o for o in zone_obs if o.vertical == vertical]

            # Sibling observations for same window
            sibling_obs = (
                PriceObservation.query
                .filter(
                    PriceObservation.zone_id.in_(sibling_ids),
                    PriceObservation.observed_at >= cutoff,
                )
                .all()
            )

            # Build sibling average by item_key
            sibling_item_prices: Dict[str, List[float]] = {}
            for o in sibling_obs:
                if o.price_usd is not None:
                    sibling_item_prices.setdefault(o.item_key, []).append(o.price_usd)

            sibling_avg: Dict[str, float] = {}
            for ik, prices in sibling_item_prices.items():
                sibling_avg[ik] = sum(prices) / len(prices)

            # Flag items where zone price is >15% below sibling average
            flagged: List[dict] = []
            seen_items: set = set()
            for o in zone_obs:
                if o.item_key in seen_items:
                    continue
                if o.price_usd is None:
                    continue
                sib_price = sibling_avg.get(o.item_key)
                if sib_price is None or sib_price == 0:
                    continue

                discount_pct = (sib_price - o.price_usd) / sib_price * 100
                if discount_pct > 15.0:
                    flagged.append({
                        "item_key": o.item_key,
                        "vertical": o.vertical,
                        "zone_id": zone_id,
                        "zone_price": round(o.price_usd, 2),
                        "sibling_avg_price": round(sib_price, 2),
                        "discount_pct": round(discount_pct, 1),
                        "observation_id": o.observation_id,
                        "is_promoted": o.is_promoted,
                        "potential_geo_fence": True,
                    })
                    seen_items.add(o.item_key)

        except Exception as exc:
            self.logger.error("detect_promotions failed: %s", exc)
            return []

        return flagged

    # ------------------------------------------------------------------
    # 13. Discover new zones from node clustering
    # ------------------------------------------------------------------
    def discover_zones(
        self,
        min_nodes_city: int = 5,
        city_radius_km: float = 50,
        min_nodes_district: int = 3,
        district_radius_km: float = 10,
        min_nodes_micro: int = 10,
        micro_radius_km: float = 2,
    ) -> dict:
        from models import NodeLocationHistory, PricingZone, db

        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        zones_created = 0
        zones_by_resolution: Dict[str, int] = {"city": 0, "district": 0, "micro": 0}

        try:
            locations = (
                NodeLocationHistory.query
                .filter(NodeLocationHistory.recorded_at >= cutoff)
                .all()
            )
        except Exception as exc:
            self.logger.error("discover_zones query failed: %s", exc)
            return {"zones_created": 0, "zones_by_resolution": zones_by_resolution}

        # Group by existing region zone
        region_groups: Dict[str, List[dict]] = {}
        for loc in locations:
            rz = loc.resolved_zone_id or "UNKNOWN"
            region_groups.setdefault(rz, []).append({
                "lat": loc.lat,
                "lon": loc.lon,
                "node_id": loc.node_id,
            })

        level_params = [
            ("city", city_radius_km, min_nodes_city),
            ("district", district_radius_km, min_nodes_district),
            ("micro", micro_radius_km, min_nodes_micro),
        ]

        for parent_zone_id, locs in region_groups.items():
            remaining = locs

            for resolution, radius, min_nodes in level_params:
                clusters = self._cluster_locations(remaining, radius, min_nodes)

                for idx, cluster in enumerate(clusters):
                    name_label = f"C{idx + 1}"
                    new_zone_id = self._generate_zone_id(
                        parent_zone_id, name_label, resolution
                    )

                    existing = PricingZone.query.filter_by(zone_id=new_zone_id).first()
                    if existing:
                        continue

                    try:
                        new_zone = PricingZone(
                            zone_id=new_zone_id,
                            resolution=resolution,
                            parent_zone_id=parent_zone_id,
                            name=name_label,
                            lat_center=cluster["lat"],
                            lon_center=cluster["lon"],
                            radius_km=radius,
                            is_active=True,
                            created_at=datetime.now(timezone.utc),
                        )
                        db.session.add(new_zone)
                        zones_created += 1
                        zones_by_resolution[resolution] += 1
                    except Exception as exc:
                        self.logger.error(
                            "Failed creating discovered zone %s: %s",
                            new_zone_id, exc,
                        )
                        db.session.rollback()

        try:
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            self.logger.error("discover_zones commit failed: %s", exc)
            return {"zones_created": 0, "zones_by_resolution": zones_by_resolution}

        self.logger.info(
            "discover_zones complete — %d zones created: %s",
            zones_created, zones_by_resolution,
        )
        return {
            "zones_created": zones_created,
            "zones_by_resolution": zones_by_resolution,
        }

    # ------------------------------------------------------------------
    # 14. Greedy centroid clustering (no scipy)
    # ------------------------------------------------------------------
    def _cluster_locations(
        self,
        locations: List[dict],
        radius_km: float,
        min_points: int,
    ) -> List[dict]:
        """
        Greedy density-first clustering.  Picks the densest point,
        absorbs neighbours within *radius_km*, computes centroid, repeat.
        Returns clusters meeting the *min_points* threshold.
        """
        if not locations:
            return []

        remaining = list(locations)

        # Pre-compute neighbour counts for sorting by density
        def _count_neighbours(loc: dict) -> int:
            count = 0
            for other in remaining:
                if other is loc:
                    continue
                dist = self.haversine_km(
                    loc["lat"], loc["lon"], other["lat"], other["lon"]
                )
                if dist <= radius_km:
                    count += 1
            return count

        clusters: List[dict] = []

        while remaining:
            # Sort by density descending
            remaining.sort(key=_count_neighbours, reverse=True)
            seed = remaining[0]

            absorbed = []
            leftover = []

            for loc in remaining:
                dist = self.haversine_km(
                    seed["lat"], seed["lon"], loc["lat"], loc["lon"]
                )
                if dist <= radius_km:
                    absorbed.append(loc)
                else:
                    leftover.append(loc)

            if len(absorbed) < min_points:
                # Not dense enough — remove seed and continue
                remaining = [l for l in remaining if l is not seed]
                continue

            # Compute centroid
            avg_lat = sum(l["lat"] for l in absorbed) / len(absorbed)
            avg_lon = sum(l["lon"] for l in absorbed) / len(absorbed)
            node_ids = list({l["node_id"] for l in absorbed if l.get("node_id")})

            clusters.append({
                "lat": round(avg_lat, 6),
                "lon": round(avg_lon, 6),
                "count": len(absorbed),
                "node_ids": node_ids,
            })

            remaining = leftover

        return clusters

    # ------------------------------------------------------------------
    # 15. Update zone stats (density score, node count, observations)
    # ------------------------------------------------------------------
    def update_zone_stats(self, zone_id: str = None) -> int:
        from models import PricingZone, PriceObservation, NodeLocationHistory, db

        cutoff_24h = datetime.now(timezone.utc) - timedelta(hours=24)
        updated = 0

        try:
            if zone_id:
                zones = PricingZone.query.filter_by(zone_id=zone_id).all()
            else:
                zones = PricingZone.query.all()
        except Exception as exc:
            self.logger.error("update_zone_stats query failed: %s", exc)
            return 0

        for z in zones:
            try:
                active_node_count = (
                    NodeLocationHistory.query
                    .filter_by(resolved_zone_id=z.zone_id)
                    .filter(NodeLocationHistory.recorded_at >= cutoff_24h)
                    .distinct(NodeLocationHistory.node_id)
                    .count()
                )

                total_observations = (
                    PriceObservation.query
                    .filter_by(zone_id=z.zone_id)
                    .count()
                )

                density_score = (
                    min(1.0, active_node_count / 20) * 0.5
                    + min(1.0, total_observations / 1000) * 0.5
                )

                z.active_node_count = active_node_count
                z.total_observations = total_observations
                z.density_score = round(density_score, 4)
                updated += 1
            except Exception as exc:
                self.logger.warning(
                    "Failed to update stats for zone %s: %s", z.zone_id, exc
                )

        try:
            db.session.commit()
            self.logger.info("Updated stats for %d zones", updated)
        except Exception as exc:
            db.session.rollback()
            self.logger.error("update_zone_stats commit failed: %s", exc)
            return 0

        return updated

    # ------------------------------------------------------------------
    # 16. Zone hierarchy (tree)
    # ------------------------------------------------------------------
    def get_zone_hierarchy(self, country_code: str = None) -> dict:
        from models import PricingZone

        try:
            query = PricingZone.query
            if country_code:
                query = query.filter(
                    (PricingZone.zone_id == country_code)
                    | (PricingZone.parent_zone_id == country_code)
                    | (PricingZone.zone_id.like(f"{country_code}-%"))
                )
            zones = query.all()
        except Exception as exc:
            self.logger.error("get_zone_hierarchy query failed: %s", exc)
            return {}

        zone_map: Dict[str, dict] = {}
        for z in zones:
            zone_map[z.zone_id] = {
                "zone_id": z.zone_id,
                "resolution": z.resolution,
                "name": z.name,
                "parent_zone_id": z.parent_zone_id,
                "lat_center": z.lat_center,
                "lon_center": z.lon_center,
                "radius_km": z.radius_km,
                "is_active": z.is_active,
                "children": [],
            }

        # Build parent→children links
        roots: List[dict] = []
        for zid, zdata in zone_map.items():
            parent_id = zdata["parent_zone_id"]
            if parent_id and parent_id in zone_map:
                zone_map[parent_id]["children"].append(zdata)
            else:
                roots.append(zdata)

        return {"roots": roots, "total_zones": len(zone_map)}

    # ------------------------------------------------------------------
    # 17. Zone summary (high-level dashboard data)
    # ------------------------------------------------------------------
    def get_zone_summary(self) -> dict:
        from models import PricingZone, PriceObservation

        try:
            zones = PricingZone.query.all()
            total_observations = PriceObservation.query.count()
        except Exception as exc:
            self.logger.error("get_zone_summary query failed: %s", exc)
            return {"error": str(exc)}

        by_resolution: Dict[str, int] = {}
        top_density: List[dict] = []

        for z in zones:
            res = z.resolution or "unknown"
            by_resolution[res] = by_resolution.get(res, 0) + 1
            density = getattr(z, "density_score", None) or 0.0
            top_density.append({
                "zone_id": z.zone_id,
                "resolution": z.resolution,
                "density_score": density,
            })

        top_density.sort(key=lambda x: x["density_score"], reverse=True)

        return {
            "total_zones": len(zones),
            "by_resolution": by_resolution,
            "total_observations": total_observations,
            "top_zones_by_density": top_density[:10],
        }

    # ------------------------------------------------------------------
    # 18. Observation gap detection (for harvest scheduler)
    # ------------------------------------------------------------------
    def get_observation_gaps(
        self,
        hours_back: int = 24,
        min_observations: int = 5,
        verticals: list = None,
    ) -> list:
        """Return zones × verticals with insufficient recent observations.

        Used by the autonomous harvest scheduler (Build #79) to identify
        where the network needs more data collection.

        Returns a list of dicts sorted by staleness (most stale first):
            [{zone_id, vertical, observation_count, staleness_hours,
              density_score, active_node_count}, ...]
        """
        from models import PricingZone, PriceObservation

        if verticals is None:
            verticals = ["flight", "hotel", "cruise", "rental"]

        gaps = []
        try:
            zones = PricingZone.query.filter_by(is_active=True).filter(
                PricingZone.active_node_count > 0
            ).all()

            cutoff = datetime.utcnow() - timedelta(hours=hours_back)

            for zone in zones:
                for vertical in verticals:
                    count = PriceObservation.query.filter(
                        PriceObservation.zone_id == zone.zone_id,
                        PriceObservation.vertical == vertical,
                        PriceObservation.observed_at >= cutoff,
                    ).count()

                    if count < min_observations:
                        latest = PriceObservation.query.filter(
                            PriceObservation.zone_id == zone.zone_id,
                            PriceObservation.vertical == vertical,
                        ).order_by(
                            PriceObservation.observed_at.desc()
                        ).first()

                        staleness = float(hours_back)
                        if latest and latest.observed_at:
                            delta = datetime.utcnow() - latest.observed_at
                            staleness = round(delta.total_seconds() / 3600, 1)

                        gaps.append({
                            "zone_id": zone.zone_id,
                            "vertical": vertical,
                            "observation_count": count,
                            "staleness_hours": staleness,
                            "density_score": zone.density_score or 0.0,
                            "active_node_count": zone.active_node_count or 0,
                        })

        except Exception as exc:
            self.logger.error("get_observation_gaps error: %s", exc)

        return sorted(gaps, key=lambda g: g["staleness_hours"], reverse=True)

    # ------------------------------------------------------------------
    # 19. Check location consent
    # ------------------------------------------------------------------
    def _check_location_consent(self, user_id: int) -> bool:
        try:
            from models import NodeConsentProfile

            profile = NodeConsentProfile.query.filter_by(user_id=user_id).first()
            if profile is None:
                return False
            return bool(getattr(profile, "consent_location", False))
        except ImportError:
            self.logger.warning(
                "NodeConsentProfile not available — defaulting to no consent"
            )
            return False
        except Exception as exc:
            self.logger.error("_check_location_consent error: %s", exc)
            return False

    # ------------------------------------------------------------------
    # 19. Generate a zone ID
    # ------------------------------------------------------------------
    def _generate_zone_id(
        self, parent_zone_id: str, name: str, resolution: str
    ) -> str:
        """
        Build a hierarchical zone ID.  Example: parent="US-NE", name="NYC"
        produces "US-NE-NYC".  The name portion is sanitised to uppercase
        alphanumeric and truncated to 4 characters.
        """
        import re

        sanitised = re.sub(r"[^A-Z0-9]", "", name.upper())[:4]
        if not sanitised:
            sanitised = uuid.uuid4().hex[:4].upper()

        if parent_zone_id:
            candidate = f"{parent_zone_id}-{sanitised}"
        else:
            candidate = sanitised

        # Uniqueness check — append digit if collision
        from models import PricingZone

        try:
            if PricingZone.query.filter_by(zone_id=candidate).first() is None:
                return candidate

            for suffix in range(2, 100):
                alt = f"{candidate}{suffix}"
                if PricingZone.query.filter_by(zone_id=alt).first() is None:
                    return alt
        except Exception:
            pass

        # Fallback with random suffix
        return f"{candidate}-{uuid.uuid4().hex[:4].upper()}"

    # ------------------------------------------------------------------
    # 20. Find nearest zone by haversine
    # ------------------------------------------------------------------
    def _find_nearest_zone(
        self, lat: float, lon: float, resolution: str = None
    ) -> Optional[str]:
        from models import PricingZone

        try:
            query = PricingZone.query.filter_by(is_active=True)
            if resolution:
                query = query.filter_by(resolution=resolution)
            zones = query.all()
        except Exception as exc:
            self.logger.error("_find_nearest_zone query failed: %s", exc)
            return None

        best_id = None
        best_dist = float("inf")

        for z in zones:
            dist = self.haversine_km(lat, lon, z.lat_center, z.lon_center)
            if dist < best_dist:
                best_dist = dist
                best_id = z.zone_id

        return best_id

    # ------------------------------------------------------------------
    # 21. Build a canonical item key from a vertical + item dict
    # ------------------------------------------------------------------
    def _build_item_key(self, vertical: str, item: dict) -> str:
        """
        Generate a deterministic item key based on the vertical type.
        """

        def _slug(value: str) -> str:
            import re
            return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")

        vertical_lower = vertical.lower() if vertical else ""

        if vertical_lower == "hotel":
            hotel = _slug(item.get("hotel_name", "unknown"))
            city = _slug(item.get("city", "unknown"))
            return f"{hotel}-{city}"

        if vertical_lower == "flight":
            origin = item.get("origin", "XXX").upper()
            dest = item.get("dest", "XXX").upper()
            date = item.get("date", "na")
            cabin = item.get("cabin", "economy").lower()
            return f"{origin}-{dest}:{date}:{cabin}"

        if vertical_lower == "cruise":
            ship = _slug(item.get("ship_name", "unknown"))
            port = _slug(item.get("departure_port", "unknown"))
            date = item.get("date", "na")
            return f"{ship}-{port}:{date}"

        if vertical_lower == "rental":
            vehicle = _slug(item.get("vehicle_class", "standard"))
            pickup = _slug(item.get("pickup_location", "unknown"))
            dates = item.get("dates", "na")
            return f"{vehicle}-{pickup}:{dates}"

        # Fallback — hash the item keys for uniqueness
        key_data = json.dumps(item, sort_keys=True)
        h = hashlib.sha256(key_data.encode()).hexdigest()[:10]
        return f"{_slug(vertical)}-{h}"


# ======================================================================
# Module-level singleton
# ======================================================================
zone_engine = ZoneEngine()
