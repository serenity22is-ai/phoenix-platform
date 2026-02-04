"""
Arbitrage Deal Generator — Background scanner for hotel, cruise, and rental deals.

Build #76: Scans popular destinations across all verticals and populates deal tables.

Run manually:
    python3 arbitrage_deal_generator.py

Run with cron (every hour):
    0 * * * * cd /path/to/flightfinder2 && python3 arbitrage_deal_generator.py >> /tmp/arb_deal_generator.log 2>&1
"""

import logging
import secrets
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scan configuration — popular destinations, cruise lines, and rental locations
# ---------------------------------------------------------------------------

HOTEL_SCAN_DESTINATIONS = [
    "Tokyo",
    "Paris",
    "London",
    "New York",
    "Barcelona",
    "Bali",
    "Dubai",
    "Rome",
    "Bangkok",
    "Istanbul",
    "Cancun",
    "Maldives",
    "Santorini",
    "Phuket",
    "Miami",
]

CRUISE_SCAN_CONFIGS = [
    {"line": "carnival", "port": "Miami", "duration": 7},
    {"line": "royal_caribbean", "port": "Fort Lauderdale", "duration": 7},
    {"line": "norwegian", "port": "Barcelona", "duration": 10},
    {"line": "msc", "port": "Genoa", "duration": 7},
    {"line": "princess", "port": "Seattle", "duration": 7},
    {"line": "celebrity", "port": "Fort Lauderdale", "duration": 10},
]

RENTAL_SCAN_LOCATIONS = [
    "LAX",
    "JFK",
    "LHR",
    "CDG",
    "NRT",
    "FCO",
    "BCN",
    "MIA",
    "SFO",
    "ORD",
    "DXB",
    "SIN",
    "BKK",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_scan_dates(days_ahead_start=14, days_ahead_end=90, count=5):
    """Generate a spread of dates to scan — near-term, mid-term, far-term."""
    today = datetime.utcnow().date()
    dates = []
    # Near-term (2-3 weeks out)
    dates.append((today + timedelta(days=days_ahead_start)).isoformat())
    dates.append((today + timedelta(days=days_ahead_start + 7)).isoformat())
    # Mid-term (1-2 months out)
    dates.append((today + timedelta(days=45)).isoformat())
    dates.append((today + timedelta(days=60)).isoformat())
    # Far-term (3 months out)
    dates.append((today + timedelta(days=days_ahead_end)).isoformat())
    return dates[:count]


def _make_stats():
    """Return a fresh stats dict for a scan run."""
    return {
        "started_at": datetime.utcnow().isoformat(),
        "searches_attempted": 0,
        "searches_succeeded": 0,
        "searches_failed": 0,
        "deals_found": 0,
        "deals_new": 0,
        "deals_updated": 0,
        "errors": [],
    }


def _merge_stats(target, source):
    """Merge counts from *source* stats dict into *target*."""
    for key in ("searches_attempted", "searches_succeeded", "searches_failed",
                "deals_found", "deals_new", "deals_updated"):
        target[key] += source.get(key, 0)
    target["errors"].extend(source.get("errors", []))


# ---------------------------------------------------------------------------
# Main generator class
# ---------------------------------------------------------------------------

class ArbitrageDealGenerator:
    """Background deal scanner for all non-flight verticals (hotels, cruises, rentals)."""

    def __init__(self):
        # Lazy import so the module can be imported without triggering heavy init
        from arbitrage_search import ArbitrageSearchEngine
        self.engine = ArbitrageSearchEngine()

    # ------------------------------------------------------------------
    # Full scan
    # ------------------------------------------------------------------

    def run_full_scan(self, max_per_vertical=None):
        """
        Scan all verticals and return combined stats.

        Args:
            max_per_vertical: Cap destinations/configs/locations per vertical
                              (useful for quick test runs).

        Returns:
            dict with combined scan statistics plus per-vertical breakdown.
        """
        combined = _make_stats()

        logger.info("=== Arbitrage full scan starting ===")

        hotel_stats = self.scan_hotels(max_destinations=max_per_vertical)
        cruise_stats = self.scan_cruises(max_configs=max_per_vertical)
        rental_stats = self.scan_rentals(max_locations=max_per_vertical)

        _merge_stats(combined, hotel_stats)
        _merge_stats(combined, cruise_stats)
        _merge_stats(combined, rental_stats)

        expire_stats = self.expire_old_deals()

        combined["hotels"] = hotel_stats
        combined["cruises"] = cruise_stats
        combined["rentals"] = rental_stats
        combined["expired"] = expire_stats
        combined["finished_at"] = datetime.utcnow().isoformat()

        logger.info(
            "=== Arbitrage full scan complete: %d searches (%d ok, %d fail), "
            "%d deals found (%d new, %d updated) ===",
            combined["searches_attempted"],
            combined["searches_succeeded"],
            combined["searches_failed"],
            combined["deals_found"],
            combined["deals_new"],
            combined["deals_updated"],
        )

        return combined

    # ------------------------------------------------------------------
    # Hotel scan
    # ------------------------------------------------------------------

    def scan_hotels(self, destinations=None, dates=None, max_destinations=None):
        """
        Scan hotel deals across popular destinations.

        Args:
            destinations: List of city names. Defaults to HOTEL_SCAN_DESTINATIONS.
            dates: List of date strings (YYYY-MM-DD). Defaults to auto-generated spread.
            max_destinations: Max destinations to scan (for quick test runs).

        Returns:
            dict with scan statistics.
        """
        from models import db, HotelDeal

        scan_destinations = destinations or HOTEL_SCAN_DESTINATIONS
        scan_dates = dates or _generate_scan_dates()

        if max_destinations:
            scan_destinations = scan_destinations[:max_destinations]

        stats = _make_stats()

        logger.info(
            "Hotel scan starting: %d destinations x %d dates = %d searches",
            len(scan_destinations), len(scan_dates),
            len(scan_destinations) * len(scan_dates),
        )

        for city in scan_destinations:
            for date_str in scan_dates:
                stats["searches_attempted"] += 1
                query = f"hotel in {city} check-in {date_str}"

                try:
                    logger.info("Hotel search: %s", query)
                    results = self.engine.search(query=query, vertical="hotel")

                    if not results or not isinstance(results, dict):
                        stats["searches_failed"] += 1
                        continue

                    stats["searches_succeeded"] += 1

                    for deal_data in results.get("deals", []):
                        deal_info = deal_data.get("deal", {})
                        deal_id = deal_info.get("hotel_deal_id")

                        if not deal_id:
                            deal_id = f"HD{secrets.token_hex(6).upper()}"

                        stats["deals_found"] += 1

                        existing = HotelDeal.query.filter_by(hotel_deal_id=deal_id).first()
                        if existing:
                            existing.is_active = True
                            existing.expires_at = datetime.utcnow() + timedelta(hours=24)
                            if deal_info.get("arbitrage_price"):
                                existing.arbitrage_price_usd = deal_info["arbitrage_price"]
                            if deal_info.get("user_savings"):
                                existing.user_savings_usd = deal_info["user_savings"]
                            stats["deals_updated"] += 1
                        else:
                            try:
                                check_in = datetime.strptime(date_str, "%Y-%m-%d").date()
                            except (ValueError, TypeError):
                                check_in = None

                            nights = deal_data.get("nights", 3)
                            check_out = check_in + timedelta(days=nights) if check_in else None

                            deal = HotelDeal(
                                hotel_deal_id=deal_id,
                                hotel_name=deal_data.get("hotel_name"),
                                hotel_chain=deal_data.get("hotel_chain"),
                                city=city,
                                country=deal_data.get("country"),
                                star_rating=deal_data.get("star_rating"),
                                guest_rating=deal_data.get("guest_rating"),
                                check_in=check_in,
                                check_out=check_out,
                                nights=nights,
                                room_type=deal_data.get("room_type", "standard"),
                                guests=deal_data.get("guests", 2),
                                source_url=deal_info.get("source_url"),
                                home_market=deal_info.get("home_market", "US"),
                                home_price_usd=deal_info.get("home_price"),
                                arbitrage_market=deal_data.get("cheapest_market"),
                                arbitrage_price_usd=deal_info.get("arbitrage_price"),
                                price_per_night_home=deal_info.get("price_per_night_home"),
                                price_per_night_arb=deal_info.get("price_per_night_arb"),
                                gross_savings_usd=deal_info.get("gross_savings"),
                                platform_fee_usd=deal_info.get("platform_fee_usd"),
                                user_savings_usd=deal_info.get("user_savings"),
                                savings_percent=deal_info.get("user_saves_pct"),
                                is_active=True,
                                expires_at=datetime.utcnow() + timedelta(hours=24),
                            )
                            db.session.add(deal)
                            stats["deals_new"] += 1

                    db.session.commit()

                except Exception as exc:
                    db.session.rollback()
                    error_msg = f"hotel {city} {date_str}: {type(exc).__name__}: {exc}"
                    logger.warning("Hotel search failed: %s", error_msg)
                    stats["searches_failed"] += 1
                    stats["errors"].append(error_msg)

        stats["finished_at"] = datetime.utcnow().isoformat()
        logger.info(
            "Hotel scan complete: %d searches (%d ok, %d fail), %d deals (%d new, %d updated)",
            stats["searches_attempted"], stats["searches_succeeded"],
            stats["searches_failed"], stats["deals_found"],
            stats["deals_new"], stats["deals_updated"],
        )
        return stats

    # ------------------------------------------------------------------
    # Cruise scan
    # ------------------------------------------------------------------

    def scan_cruises(self, configs=None, dates=None, max_configs=None):
        """
        Scan cruise deals across popular cruise lines and ports.

        Args:
            configs: List of config dicts with keys line, port, duration.
                     Defaults to CRUISE_SCAN_CONFIGS.
            dates: List of date strings (YYYY-MM-DD). Defaults to auto-generated spread.
            max_configs: Max configs to scan (for quick test runs).

        Returns:
            dict with scan statistics.
        """
        from models import db, CruiseDeal

        scan_configs = configs or CRUISE_SCAN_CONFIGS
        scan_dates = dates or _generate_scan_dates()

        if max_configs:
            scan_configs = scan_configs[:max_configs]

        stats = _make_stats()

        logger.info(
            "Cruise scan starting: %d configs x %d dates = %d searches",
            len(scan_configs), len(scan_dates),
            len(scan_configs) * len(scan_dates),
        )

        for cfg in scan_configs:
            line = cfg["line"]
            port = cfg["port"]
            duration = cfg.get("duration", 7)

            for date_str in scan_dates:
                stats["searches_attempted"] += 1
                query = f"{line} cruise from {port} {duration} nights {date_str}"

                try:
                    logger.info("Cruise search: %s", query)
                    results = self.engine.search(query=query, vertical="cruise")

                    if not results or not isinstance(results, dict):
                        stats["searches_failed"] += 1
                        continue

                    stats["searches_succeeded"] += 1

                    for deal_data in results.get("deals", []):
                        deal_info = deal_data.get("deal", {})
                        deal_id = deal_info.get("cruise_deal_id")

                        if not deal_id:
                            deal_id = f"CD{secrets.token_hex(6).upper()}"

                        stats["deals_found"] += 1

                        existing = CruiseDeal.query.filter_by(cruise_deal_id=deal_id).first()
                        if existing:
                            existing.is_active = True
                            existing.expires_at = datetime.utcnow() + timedelta(hours=24)
                            if deal_info.get("arbitrage_price"):
                                existing.arbitrage_price_usd = deal_info["arbitrage_price"]
                            if deal_info.get("user_savings"):
                                existing.user_savings_usd = deal_info["user_savings"]
                            stats["deals_updated"] += 1
                        else:
                            try:
                                departure_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                            except (ValueError, TypeError):
                                departure_date = None

                            actual_duration = deal_data.get("duration_nights", duration)
                            return_date = (
                                departure_date + timedelta(days=actual_duration)
                                if departure_date else None
                            )

                            import json as _json
                            itinerary_raw = deal_data.get("itinerary")
                            itinerary_str = (
                                _json.dumps(itinerary_raw)
                                if isinstance(itinerary_raw, list)
                                else itinerary_raw
                            )

                            deal = CruiseDeal(
                                cruise_deal_id=deal_id,
                                cruise_line=deal_data.get("cruise_line", line),
                                ship_name=deal_data.get("ship_name"),
                                departure_port=deal_data.get("departure_port", port),
                                itinerary=itinerary_str,
                                departure_date=departure_date,
                                return_date=return_date,
                                duration_nights=actual_duration,
                                cabin_category=deal_data.get("cabin_category", "inside"),
                                deck=deal_data.get("deck"),
                                source_url=deal_info.get("source_url"),
                                home_market=deal_info.get("home_market", "US"),
                                home_price_usd=deal_info.get("home_price"),
                                arbitrage_market=deal_data.get("cheapest_market"),
                                arbitrage_price_usd=deal_info.get("arbitrage_price"),
                                price_per_night_home=deal_info.get("price_per_night_home"),
                                price_per_night_arb=deal_info.get("price_per_night_arb"),
                                gross_savings_usd=deal_info.get("gross_savings"),
                                platform_fee_usd=deal_info.get("platform_fee_usd"),
                                user_savings_usd=deal_info.get("user_savings"),
                                savings_percent=deal_info.get("user_saves_pct"),
                                is_active=True,
                                expires_at=datetime.utcnow() + timedelta(hours=24),
                            )
                            db.session.add(deal)
                            stats["deals_new"] += 1

                    db.session.commit()

                except Exception as exc:
                    db.session.rollback()
                    error_msg = (
                        f"cruise {line}/{port} {date_str}: "
                        f"{type(exc).__name__}: {exc}"
                    )
                    logger.warning("Cruise search failed: %s", error_msg)
                    stats["searches_failed"] += 1
                    stats["errors"].append(error_msg)

        stats["finished_at"] = datetime.utcnow().isoformat()
        logger.info(
            "Cruise scan complete: %d searches (%d ok, %d fail), %d deals (%d new, %d updated)",
            stats["searches_attempted"], stats["searches_succeeded"],
            stats["searches_failed"], stats["deals_found"],
            stats["deals_new"], stats["deals_updated"],
        )
        return stats

    # ------------------------------------------------------------------
    # Rental scan
    # ------------------------------------------------------------------

    def scan_rentals(self, locations=None, dates=None, max_locations=None):
        """
        Scan car rental deals across popular airport locations.

        Args:
            locations: List of airport codes. Defaults to RENTAL_SCAN_LOCATIONS.
            dates: List of date strings (YYYY-MM-DD). Defaults to auto-generated spread.
            max_locations: Max locations to scan (for quick test runs).

        Returns:
            dict with scan statistics.
        """
        from models import db, RentalDeal

        scan_locations = locations or RENTAL_SCAN_LOCATIONS
        scan_dates = dates or _generate_scan_dates()

        if max_locations:
            scan_locations = scan_locations[:max_locations]

        stats = _make_stats()

        logger.info(
            "Rental scan starting: %d locations x %d dates = %d searches",
            len(scan_locations), len(scan_dates),
            len(scan_locations) * len(scan_dates),
        )

        for location in scan_locations:
            for date_str in scan_dates:
                stats["searches_attempted"] += 1
                query = f"car rental at {location} pickup {date_str} 7 days"

                try:
                    logger.info("Rental search: %s", query)
                    results = self.engine.search(query=query, vertical="rental")

                    if not results or not isinstance(results, dict):
                        stats["searches_failed"] += 1
                        continue

                    stats["searches_succeeded"] += 1

                    for deal_data in results.get("deals", []):
                        deal_info = deal_data.get("deal", {})
                        deal_id = deal_info.get("rental_deal_id")

                        if not deal_id:
                            deal_id = f"RD{secrets.token_hex(6).upper()}"

                        stats["deals_found"] += 1

                        existing = RentalDeal.query.filter_by(rental_deal_id=deal_id).first()
                        if existing:
                            existing.is_active = True
                            existing.expires_at = datetime.utcnow() + timedelta(hours=24)
                            if deal_info.get("arbitrage_price"):
                                existing.arbitrage_price_usd = deal_info["arbitrage_price"]
                            if deal_info.get("user_savings"):
                                existing.user_savings_usd = deal_info["user_savings"]
                            stats["deals_updated"] += 1
                        else:
                            try:
                                pickup_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                            except (ValueError, TypeError):
                                pickup_date = None

                            rental_days = deal_data.get("rental_days", 7)
                            dropoff_date = (
                                pickup_date + timedelta(days=rental_days)
                                if pickup_date else None
                            )

                            deal = RentalDeal(
                                rental_deal_id=deal_id,
                                rental_company=deal_data.get("rental_company"),
                                pickup_location=deal_data.get("pickup_location", location),
                                dropoff_location=deal_data.get("dropoff_location", location),
                                pickup_date=pickup_date,
                                dropoff_date=dropoff_date,
                                rental_days=rental_days,
                                vehicle_class=deal_data.get("vehicle_class", "economy"),
                                vehicle_example=deal_data.get("vehicle_example"),
                                source_url=deal_info.get("source_url"),
                                home_market=deal_info.get("home_market", "US"),
                                home_price_usd=deal_info.get("home_price"),
                                arbitrage_market=deal_data.get("cheapest_market"),
                                arbitrage_price_usd=deal_info.get("arbitrage_price"),
                                price_per_day_home=deal_info.get("price_per_day_home"),
                                price_per_day_arb=deal_info.get("price_per_day_arb"),
                                gross_savings_usd=deal_info.get("gross_savings"),
                                platform_fee_usd=deal_info.get("platform_fee_usd"),
                                user_savings_usd=deal_info.get("user_savings"),
                                savings_percent=deal_info.get("user_saves_pct"),
                                is_active=True,
                                expires_at=datetime.utcnow() + timedelta(hours=24),
                            )
                            db.session.add(deal)
                            stats["deals_new"] += 1

                    db.session.commit()

                except Exception as exc:
                    db.session.rollback()
                    error_msg = (
                        f"rental {location} {date_str}: "
                        f"{type(exc).__name__}: {exc}"
                    )
                    logger.warning("Rental search failed: %s", error_msg)
                    stats["searches_failed"] += 1
                    stats["errors"].append(error_msg)

        stats["finished_at"] = datetime.utcnow().isoformat()
        logger.info(
            "Rental scan complete: %d searches (%d ok, %d fail), %d deals (%d new, %d updated)",
            stats["searches_attempted"], stats["searches_succeeded"],
            stats["searches_failed"], stats["deals_found"],
            stats["deals_new"], stats["deals_updated"],
        )
        return stats

    # ------------------------------------------------------------------
    # Expire old deals
    # ------------------------------------------------------------------

    def expire_old_deals(self):
        """
        Expire stale deals across all vertical tables.

        Returns:
            dict with counts of expired deals per vertical.
        """
        from models import db, HotelDeal, CruiseDeal, RentalDeal

        now = datetime.utcnow()
        expire_stats = {}

        # Hotels
        hotel_expired = HotelDeal.query.filter(
            HotelDeal.is_active == True,
            HotelDeal.expires_at != None,
            HotelDeal.expires_at < now,
        ).update({"is_active": False})
        expire_stats["hotels_expired"] = hotel_expired

        # Cruises
        cruise_expired = CruiseDeal.query.filter(
            CruiseDeal.is_active == True,
            CruiseDeal.expires_at != None,
            CruiseDeal.expires_at < now,
        ).update({"is_active": False})
        expire_stats["cruises_expired"] = cruise_expired

        # Rentals
        rental_expired = RentalDeal.query.filter(
            RentalDeal.is_active == True,
            RentalDeal.expires_at != None,
            RentalDeal.expires_at < now,
        ).update({"is_active": False})
        expire_stats["rentals_expired"] = rental_expired

        db.session.commit()

        total = hotel_expired + cruise_expired + rental_expired
        expire_stats["total_expired"] = total

        logger.info(
            "Expired deals: %d hotels, %d cruises, %d rentals (%d total)",
            hotel_expired, cruise_expired, rental_expired, total,
        )

        return expire_stats


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )

    from server import app

    with app.app_context():
        quick = "--quick" in sys.argv
        vertical = None
        for arg in sys.argv[1:]:
            if arg in ("hotels", "cruises", "rentals"):
                vertical = arg

        generator = ArbitrageDealGenerator()

        scan_dates = _generate_scan_dates()

        print(f"\n{'=' * 60}")
        print("PHOENIX Arbitrage Deal Generator")
        print(f"{'=' * 60}")
        print(f"Vertical: {vertical or 'ALL'}")
        if vertical == "hotels":
            dest_count = 3 if quick else len(HOTEL_SCAN_DESTINATIONS)
            print(f"Destinations: {dest_count}")
        elif vertical == "cruises":
            cfg_count = 2 if quick else len(CRUISE_SCAN_CONFIGS)
            print(f"Cruise configs: {cfg_count}")
        elif vertical == "rentals":
            loc_count = 3 if quick else len(RENTAL_SCAN_LOCATIONS)
            print(f"Locations: {loc_count}")
        else:
            cap = 3 if quick else None
            print(f"Hotels: {cap or len(HOTEL_SCAN_DESTINATIONS)} destinations")
            print(f"Cruises: {cap or len(CRUISE_SCAN_CONFIGS)} configs")
            print(f"Rentals: {cap or len(RENTAL_SCAN_LOCATIONS)} locations")
        print(f"Dates: {len(scan_dates)}")
        if quick:
            print("Mode: QUICK")
        print(f"{'=' * 60}\n")

        if vertical == "hotels":
            stats = generator.scan_hotels(max_destinations=3 if quick else None)
        elif vertical == "cruises":
            stats = generator.scan_cruises(max_configs=2 if quick else None)
        elif vertical == "rentals":
            stats = generator.scan_rentals(max_locations=3 if quick else None)
        else:
            stats = generator.run_full_scan(max_per_vertical=3 if quick else None)

        print(f"\n{'=' * 60}")
        print("SCAN RESULTS")
        print(f"{'=' * 60}")
        print(
            f"Searches: {stats['searches_attempted']} attempted, "
            f"{stats['searches_succeeded']} succeeded, "
            f"{stats['searches_failed']} failed"
        )
        print(
            f"Deals: {stats['deals_found']} found, "
            f"{stats['deals_new']} new, "
            f"{stats['deals_updated']} updated"
        )

        if "expired" in stats:
            exp = stats["expired"]
            print(
                f"Expired: {exp.get('total_expired', 0)} total "
                f"({exp.get('hotels_expired', 0)} hotels, "
                f"{exp.get('cruises_expired', 0)} cruises, "
                f"{exp.get('rentals_expired', 0)} rentals)"
            )

        if stats["errors"]:
            print(f"\nErrors ({len(stats['errors'])}):")
            for err in stats["errors"][:10]:
                print(f"  - {err}")
            if len(stats["errors"]) > 10:
                print(f"  ... and {len(stats['errors']) - 10} more")

        print(f"{'=' * 60}\n")
