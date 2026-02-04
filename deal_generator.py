"""
Deal Generator — Background job that searches popular routes and populates the deals table.

Run manually:
    python3 deal_generator.py

Run with cron (every 30 minutes):
    */30 * * * * cd /path/to/flightfinder2 && python3 deal_generator.py >> /tmp/deal_generator.log 2>&1

Or call from Flask:
    from deal_generator import run_deal_scan
    run_deal_scan()  # must be called within app context
"""

import logging
import os
import secrets
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Route definitions — popular origin/destination pairs to scan
# ---------------------------------------------------------------------------

SCAN_ROUTES = [
    # US origins
    ("JFK", "LHR"),  # New York → London
    ("JFK", "NRT"),  # New York → Tokyo
    ("JFK", "CDG"),  # New York → Paris
    ("LAX", "NRT"),  # Los Angeles → Tokyo
    ("LAX", "ICN"),  # Los Angeles → Seoul
    ("LAX", "SYD"),  # Los Angeles → Sydney
    ("ORD", "FRA"),  # Chicago → Frankfurt
    ("SFO", "HND"),  # San Francisco → Tokyo
    ("MIA", "GRU"),  # Miami → São Paulo
    ("MIA", "BOG"),  # Miami → Bogotá
    # EU origins
    ("LHR", "JFK"),  # London → New York
    ("CDG", "NRT"),  # Paris → Tokyo
    ("FRA", "BKK"),  # Frankfurt → Bangkok
    ("MAD", "MEX"),  # Madrid → Mexico City
    ("BCN", "JFK"),  # Barcelona → New York
]


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


def run_deal_scan(routes=None, dates=None, max_routes=None):
    """
    Run a deal scan across routes and dates.

    Calls search_global() for each route/date combo and stores discovered
    deals in the database. Skips routes that error and continues.

    Args:
        routes: List of (origin, destination) tuples. Defaults to SCAN_ROUTES.
        dates: List of date strings (YYYY-MM-DD). Defaults to auto-generated spread.
        max_routes: Max number of routes to scan (for quick test runs).

    Returns:
        dict with scan statistics.
    """
    from models import db, Deal
    from search import search_global

    scan_routes = routes or SCAN_ROUTES
    scan_dates = dates or _generate_scan_dates()

    if max_routes:
        scan_routes = scan_routes[:max_routes]

    stats = {
        "started_at": datetime.utcnow().isoformat(),
        "routes_scanned": 0,
        "searches_attempted": 0,
        "searches_succeeded": 0,
        "searches_failed": 0,
        "deals_found": 0,
        "deals_new": 0,
        "deals_updated": 0,
        "errors": [],
    }

    logger.info(
        "Deal scan starting: %d routes × %d dates = %d searches",
        len(scan_routes), len(scan_dates), len(scan_routes) * len(scan_dates),
    )

    for origin, destination in scan_routes:
        stats["routes_scanned"] += 1

        for date_str in scan_dates:
            stats["searches_attempted"] += 1

            try:
                logger.info("Searching %s → %s on %s", origin, destination, date_str)
                results = search_global(
                    origin=origin,
                    destination=destination,
                    date=date_str,
                    fast_mode=True,
                )

                if not results or not isinstance(results, dict):
                    stats["searches_failed"] += 1
                    continue

                stats["searches_succeeded"] += 1

                # Extract and store deals
                for deal_data in results.get("deals", []):
                    deal_info = deal_data.get("deal", {})
                    deal_id = deal_info.get("deal_id")

                    if not deal_id:
                        # Generate a deal_id if the search result doesn't have one
                        deal_id = f"DL{secrets.token_hex(6).upper()}"

                    stats["deals_found"] += 1

                    # Check if deal already exists
                    existing = Deal.query.filter_by(deal_id=deal_id).first()
                    if existing:
                        # Update expiry and pricing if it already exists
                        existing.is_active = True
                        existing.expires_at = datetime.utcnow() + timedelta(hours=24)
                        if deal_info.get("arbitrage_price"):
                            existing.arbitrage_price_usd = deal_info.get("arbitrage_price")
                        if deal_info.get("user_savings"):
                            existing.user_savings_usd = deal_info.get("user_savings")
                        stats["deals_updated"] += 1
                    else:
                        # Create new deal record
                        try:
                            departure_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                        except (ValueError, TypeError):
                            departure_date = None

                        deal = Deal(
                            deal_id=deal_id,
                            airline=deal_data.get("airline"),
                            flight_number=deal_data.get("flight_number"),
                            origin=origin,
                            destination=destination,
                            departure_date=departure_date,
                            home_market=deal_info.get("home_market", "US"),
                            home_price_usd=deal_info.get("home_price"),
                            arbitrage_market=deal_data.get("cheapest_market"),
                            arbitrage_price_usd=deal_info.get("arbitrage_price"),
                            gross_savings_usd=deal_info.get("gross_savings"),
                            platform_fee_usd=deal_info.get("platform_fee_usd"),
                            platform_fee_xrp=deal_info.get("platform_fee_xrp"),
                            user_savings_usd=deal_info.get("user_savings"),
                            savings_percent=deal_info.get("user_saves_pct"),
                            booking_url=deal_info.get("booking_url"),
                            destination_tag=deal_info.get("payment", {}).get(
                                "payment_request", {}
                            ).get("destination_tag"),
                            is_active=True,
                            expires_at=datetime.utcnow() + timedelta(hours=24),
                        )
                        db.session.add(deal)
                        stats["deals_new"] += 1

                db.session.commit()

            except Exception as exc:
                db.session.rollback()
                error_msg = f"{origin}-{destination} {date_str}: {type(exc).__name__}: {exc}"
                logger.warning("Search failed: %s", error_msg)
                stats["searches_failed"] += 1
                stats["errors"].append(error_msg)

    # Expire old deals
    expired_count = Deal.query.filter(
        Deal.is_active == True,
        Deal.expires_at != None,
        Deal.expires_at < datetime.utcnow(),
    ).update({"is_active": False})
    db.session.commit()

    stats["deals_expired"] = expired_count
    stats["finished_at"] = datetime.utcnow().isoformat()

    logger.info(
        "Deal scan complete: %d searches (%d ok, %d fail), "
        "%d deals found (%d new, %d updated), %d expired",
        stats["searches_attempted"],
        stats["searches_succeeded"],
        stats["searches_failed"],
        stats["deals_found"],
        stats["deals_new"],
        stats["deals_updated"],
        expired_count,
    )

    return stats


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )

    # Import Flask app for DB context
    from server import app

    with app.app_context():
        # Parse optional --quick flag for fewer routes
        quick = "--quick" in sys.argv
        max_routes = 3 if quick else None

        print(f"\n{'='*60}")
        print(f"PHOENIX Deal Generator")
        print(f"{'='*60}")
        print(f"Routes: {len(SCAN_ROUTES) if not max_routes else max_routes}")
        print(f"Dates: {len(_generate_scan_dates())}")
        if quick:
            print("Mode: QUICK (3 routes only)")
        print(f"{'='*60}\n")

        stats = run_deal_scan(max_routes=max_routes)

        print(f"\n{'='*60}")
        print(f"SCAN RESULTS")
        print(f"{'='*60}")
        print(f"Searches: {stats['searches_attempted']} attempted, "
              f"{stats['searches_succeeded']} succeeded, "
              f"{stats['searches_failed']} failed")
        print(f"Deals: {stats['deals_found']} found, "
              f"{stats['deals_new']} new, "
              f"{stats['deals_updated']} updated")
        print(f"Expired: {stats.get('deals_expired', 0)} deals deactivated")

        if stats["errors"]:
            print(f"\nErrors ({len(stats['errors'])}):")
            for err in stats["errors"][:10]:
                print(f"  - {err}")

        print(f"{'='*60}\n")
