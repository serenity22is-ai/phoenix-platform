"""
Quickstart — Search flights with the Picasso Redbox SDK.

Prerequisites:
    pip install picasso-redbox-sdk

    Set in .env or environment:
        PICASSO_SESSION_TOKEN=your_26_char_token

    Or for auto-login (requires `pip install picasso-redbox-sdk[auth]`):
        PICASSO_USERNAME=your_cockpit_email@gmail.com
        PICASSO_PASSWORD=your_cockpit_password
        PICASSO_TOTP_SECRET=your_32_char_base32_secret
"""

from picasso import RedboxClient

# --- Option 1: Static token ---
client = RedboxClient(
    agency_id="YOUR_AGENCY_ID",
    branch="YOUR_BRANCH",
    session_token="YOUR_SESSION_TOKEN",  # or set PICASSO_SESSION_TOKEN env var
)

# --- Option 2: Auto-login with TokenManager ---
# from picasso.auth import TokenManager
# manager = TokenManager()
# client = RedboxClient(
#     agency_id="YOUR_AGENCY_ID",
#     branch="YOUR_BRANCH",
#     token_provider=manager.get_token,
# )


def search_example():
    """Search for flights from JFK to London Heathrow."""

    # Search airports (public — no auth needed)
    airports = client.search_airports("London")
    print(f"Found {len(airports)} airports matching 'London':")
    for apt in airports[:5]:
        print(f"  {apt['code']} — {apt['name']} ({apt['country_name']})")
    print()

    # Search flights
    result = client.search_flights(
        origin="JFK",
        destination="LHR",
        departure_date="2026-06-15",
        return_date="2026-06-22",
        adults=1,
        cabin_class="ECONOMY",
        max_results=10,
    )

    if not result["success"]:
        print(f"Search failed: {result['error']}")
        return

    print(f"Found {result['total_results']} fares from {result['airlines_count']} airlines")
    print(f"Showing top {len(result['flights'])} results:\n")

    for i, flight in enumerate(result["flights"], 1):
        print(f"  {i}. {flight['airline_name']} ({flight['airline']})")
        print(f"     {flight['origin']} -> {flight['destination']}")
        print(f"     Depart: {flight['departure_time']}")
        print(f"     Duration: {flight['duration_formatted']}, Stops: {flight['stops']}")
        print(f"     Cabin: {flight['cabin_class']}, Fare: {flight['fare_family']}")
        print(f"     Price: ${flight['price']:.2f} ({flight['currency']})")
        print(f"     Baggage: {flight['baggage_info'] or 'N/A'}")
        print(f"     GDS: {flight['gds']}, Fare ID: {flight['fare_id']}")
        print()

    # Get fare rules for cheapest flight
    cheapest = result["flights"][0]
    print(f"--- Fare rules for {cheapest['airline_name']} ${cheapest['price']:.2f} ---")
    rules = client.get_fare_rules(result["fare_search_id"], cheapest["fare_id"])
    if rules["success"]:
        for code, rule in rules["rules"].items():
            print(f"  [{code}] {rule['title']}")
    else:
        print(f"  Could not load fare rules: {rules.get('error')}")

    # Pagination — get page 2 with filters
    page2 = client.get_search_results(
        fare_search_id=result["fare_search_id"],
        page_number=2,
        results_per_page=10,
        show_filters=True,
    )
    if page2["success"]:
        print(f"\nPage 2: {len(page2['flights'])} more flights")
        if page2.get("filters"):
            print(f"Available filters: {list(page2['filters'].keys())}")


if __name__ == "__main__":
    search_example()
