#!/usr/bin/env python3
"""
PHOENIX Domestic Flight Price Comparison Test

Compares US domestic flight prices between US market and international markets
to detect price discrimination and arbitrage opportunities.
"""

import os
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv
import json

# Load environment
load_dotenv()

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import (
    compare_markets,
    calculate_deal,
    CURRENCY_RATES_TO_USD,
    search_amadeus_with_proxy_prices,
    search_hybrid,
    DIRECT_SCRAPER_AVAILABLE,
    AMADEUS_AVAILABLE,
    AMADEUS_CONFIGURED,
)


def format_price(price, currency="USD"):
    """Format price with currency symbol."""
    symbols = {"USD": "$", "EUR": "€", "GBP": "£"}
    return f"{symbols.get(currency, currency)}{price:.2f}"


def run_domestic_comparison(routes, date_str):
    """
    Run price comparison for domestic US routes across multiple markets.

    Args:
        routes: List of (origin, destination) tuples
        date_str: Date string in YYYY-MM-DD format

    Returns:
        List of comparison results
    """
    results = []

    print("\n" + "=" * 70)
    print("PHOENIX DOMESTIC FLIGHT PRICE COMPARISON TEST")
    print("=" * 70)
    print(f"Date: {date_str}")
    print(f"Routes: {len(routes)} domestic US routes")
    print(f"Markets: US (google.com) vs ES (google.es) vs UK (google.co.uk)")
    print("=" * 70 + "\n")

    for origin, dest in routes:
        print(f"\n{'─' * 60}")
        print(f"ROUTE: {origin} → {dest}")
        print(f"{'─' * 60}")

        try:
            # Search using Amadeus + Proxy (preferred) or hybrid fallback
            if AMADEUS_AVAILABLE and AMADEUS_CONFIGURED:
                search_result = search_amadeus_with_proxy_prices(
                    origin=origin,
                    destination=dest,
                    date=date_str,
                    cabin_class="economy"
                )
            else:
                search_result = search_hybrid(
                    origin=origin,
                    destination=dest,
                    date=date_str,
                    cabin_class="economy"
                )

            if not search_result or "error" in search_result:
                print(f"  ⚠ No results found: {search_result.get('error', 'Unknown error')}")
                results.append({
                    "route": f"{origin} → {dest}",
                    "status": "no_results",
                    "error": search_result.get("error") if search_result else "No data"
                })
                continue

            # Extract data from search_hybrid result structure
            price_comparison = search_result.get("price_comparison", [])
            us_price = search_result.get("us_price_usd", 0)
            cheapest_market = search_result.get("cheapest_market", "US")
            cheapest_price = search_result.get("cheapest_price_usd", 0)
            savings_vs_us = search_result.get("savings_vs_us", 0)
            savings_pct = search_result.get("savings_pct", 0)

            print(f"  Price comparisons: {len(price_comparison)}")

            # Show market prices
            if price_comparison:
                print(f"\n  Market Price Summary:")
                for pc in price_comparison:
                    market = pc.get("market", "?")
                    price_usd = pc.get("price_usd", 0)
                    original = pc.get("price_original", 0)
                    currency = pc.get("currency", "USD")
                    print(f"    {market}: {format_price(price_usd)} USD (original: {currency} {original:.2f})")

            # Build result
            if us_price and cheapest_price:
                result = {
                    "route": f"{origin} → {dest}",
                    "us_price": us_price,
                    "best_foreign_price": cheapest_price,
                    "best_foreign_market": cheapest_market,
                    "savings_usd": savings_vs_us,
                    "savings_pct": savings_pct,
                    "status": "success",
                    "price_comparison": price_comparison
                }

                if savings_vs_us > 0:
                    print(f"\n  ✅ SAVINGS: {format_price(savings_vs_us)} ({savings_pct:.1f}%)")
                    print(f"     Book via {cheapest_market} instead of US")
                elif savings_vs_us < 0:
                    print(f"\n  ℹ US is cheaper by {format_price(abs(savings_vs_us))}")
                else:
                    print(f"\n  ℹ Prices are equal across markets")
            else:
                result = {
                    "route": f"{origin} → {dest}",
                    "us_price": us_price,
                    "status": "partial_data",
                    "price_comparison": price_comparison
                }
                print(f"\n  ⚠ Incomplete market data (US: {us_price}, Cheapest: {cheapest_price})")

            results.append(result)

        except Exception as e:
            print(f"  ❌ Error: {str(e)}")
            results.append({
                "route": f"{origin} → {dest}",
                "status": "error",
                "error": str(e)
            })

    return results


def generate_report(results, date_str):
    """Generate a summary report of the comparison results."""

    print("\n\n" + "=" * 70)
    print("COMPARISON RESULTS SUMMARY")
    print("=" * 70)
    print(f"Test Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Flight Date: {date_str}")
    print("=" * 70)

    # Calculate statistics
    successful = [r for r in results if r.get("status") == "success"]
    with_savings = [r for r in successful if r.get("savings_usd", 0) > 0]
    us_cheaper = [r for r in successful if r.get("savings_usd", 0) < 0]
    equal = [r for r in successful if r.get("savings_usd", 0) == 0]

    print(f"\nRoutes Tested: {len(results)}")
    print(f"Successful Comparisons: {len(successful)}")
    print(f"Routes with Foreign Savings: {len(with_savings)}")
    print(f"Routes where US is Cheaper: {len(us_cheaper)}")
    print(f"Routes with Equal Prices: {len(equal)}")

    # Detailed results table
    print("\n" + "-" * 70)
    print(f"{'Route':<15} {'US Price':<12} {'Best Foreign':<15} {'Savings':<12} {'%':<8}")
    print("-" * 70)

    for r in results:
        route = r.get("route", "N/A")
        if r.get("status") == "success":
            us = format_price(r.get("us_price", 0))
            foreign = f"{format_price(r.get('best_foreign_price', 0))} ({r.get('best_foreign_market', '?')})"
            savings = r.get("savings_usd", 0)
            savings_str = format_price(savings) if savings >= 0 else f"-{format_price(abs(savings))}"
            pct = f"{r.get('savings_pct', 0):.1f}%"
            print(f"{route:<15} {us:<12} {foreign:<15} {savings_str:<12} {pct:<8}")
        else:
            print(f"{route:<15} {'N/A':<12} {'N/A':<15} {'N/A':<12} {'N/A':<8}")

    print("-" * 70)

    # Summary statistics
    if with_savings:
        avg_savings = sum(r["savings_usd"] for r in with_savings) / len(with_savings)
        avg_pct = sum(r["savings_pct"] for r in with_savings) / len(with_savings)
        max_savings = max(r["savings_usd"] for r in with_savings)
        best_route = max(with_savings, key=lambda x: x["savings_usd"])

        print(f"\n📊 SAVINGS STATISTICS:")
        print(f"   Average Savings: {format_price(avg_savings)} ({avg_pct:.1f}%)")
        print(f"   Maximum Savings: {format_price(max_savings)}")
        print(f"   Best Deal Route: {best_route['route']}")

    # Market distribution
    print(f"\n🌍 MARKET ANALYSIS:")
    es_wins = len([r for r in with_savings if r.get("best_foreign_market") == "ES"])
    uk_wins = len([r for r in with_savings if r.get("best_foreign_market") == "UK"])
    print(f"   Spain (ES) cheapest: {es_wins} routes")
    print(f"   UK cheapest: {uk_wins} routes")
    print(f"   US cheapest: {len(us_cheaper)} routes")

    return {
        "test_date": datetime.now().isoformat(),
        "flight_date": date_str,
        "total_routes": len(results),
        "successful": len(successful),
        "with_savings": len(with_savings),
        "us_cheaper": len(us_cheaper),
        "results": results
    }


def main():
    """Main test execution."""

    # Define test routes (US domestic)
    domestic_routes = [
        ("JFK", "LAX"),  # New York to Los Angeles
        ("LAX", "MIA"),  # Los Angeles to Miami
        ("ORD", "SFO"),  # Chicago to San Francisco
        ("DFW", "SEA"),  # Dallas to Seattle
        ("BOS", "ATL"),  # Boston to Atlanta
        ("DEN", "LAS"),  # Denver to Las Vegas
    ]

    # Use date 3 weeks out for better availability
    test_date = (datetime.now() + timedelta(days=21)).strftime("%Y-%m-%d")

    print("\n🔥 PHOENIX FLIGHT PRICE ARBITRAGE TEST 🔥")
    print("Testing domestic US flights for geographic price discrimination\n")

    # Check available search providers
    if AMADEUS_AVAILABLE and AMADEUS_CONFIGURED:
        print("✅ Amadeus API configured - will get detailed flight data")
    else:
        print("⚠ Amadeus API not configured - set AMADEUS_API_KEY and AMADEUS_API_SECRET in .env")

    if DIRECT_SCRAPER_AVAILABLE:
        print("✅ Direct proxy scraper available - will get REAL regional prices")
    else:
        print("⚠ Direct scraper not available - install playwright for proxy scraping")

    # Run the comparison
    results = run_domestic_comparison(domestic_routes, test_date)

    # Generate report
    report = generate_report(results, test_date)

    # Save results to JSON
    output_file = f"/Users/adramainjest/flightfinder2/domestic_test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\n📄 Results saved to: {output_file}")

    return report


if __name__ == "__main__":
    main()
