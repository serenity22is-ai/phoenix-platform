"""
Booking flow — Search, select, and book a flight via Redbox.

IMPORTANT: This will create a real booking if run against a production account.
Only run against a sandbox account for testing.

Prerequisites:
    pip install picasso-redbox-sdk[auth]
"""

from picasso import RedboxClient
from picasso.auth import TokenManager

# Auto-login via TOTP (reads from .env)
manager = TokenManager()
client = RedboxClient(
    agency_id="YOUR_AGENCY_ID",
    branch="YOUR_BRANCH",
    token_provider=manager.get_token,
)


def booking_example():
    """Complete booking flow: search -> select -> book."""

    # Step 1: Search flights
    print("=== Step 1: Search ===")
    result = client.search_flights(
        origin="JFK",
        destination="LHR",
        departure_date="2026-06-15",
        return_date="2026-06-22",
        adults=1,
    )

    if not result["success"]:
        print(f"Search failed: {result['error']}")
        return

    flights = result["flights"]
    fare_search_id = result["fare_search_id"]
    print(f"Found {len(flights)} flights")

    # Step 2: Select cheapest flight
    selected = flights[0]
    print(f"\n=== Step 2: Selected ===")
    print(f"  {selected['airline_name']} — ${selected['price']:.2f}")
    print(f"  {selected['origin']} -> {selected['destination']}")
    print(f"  {selected['duration_formatted']}, {selected['stops']} stops")
    print(f"  Fare ID: {selected['fare_id']}")

    # Step 3: Check seatmap (optional)
    if selected["segments"]:
        seg = selected["segments"][0]
        print(f"\n=== Seatmap for {seg['flight_number']} ===")
        seatmap = client.get_seatmap(
            airline_code=seg["carrier"],
            flight_number=str(seg["flight_num_raw"]),
            departure=seg["departure_airport"],
            destination=seg["arrival_airport"],
            departure_date="2026-06-15",
            booking_class=seg.get("booking_class", "Y"),
        )
        if seatmap["success"]:
            print("  Seatmap data available")
        else:
            print(f"  Seatmap not available: {seatmap.get('error')}")

    # Step 4: Book the flight
    print(f"\n=== Step 3: Book ===")
    passengers = [
        {
            "firstName": "John",
            "lastName": "Smith",
            "paxType": "ADT",
            "dateOfBirth": "1990-05-15",
            "gender": "Male",
            "title": "MR",
            "email": "john.smith@example.com",
            "phone": "+12125551234",
            # For international flights:
            "passportNumber": "123456789",
            "passportExpiry": "2030-12-31",
            "nationality": "US",
        }
    ]

    # book_flight() orchestrates: cart + checkout + superPNR in one call
    booking = client.book_flight(
        fare_search_id=fare_search_id,
        fare_id=selected["fare_id"],
        passengers=passengers,
        order_tickets=True,
        markup_amount=15.00,  # Optional: adds BOOKING_FEE_OVERRIDE
    )

    if booking["success"]:
        print(f"  BOOKED! PNR: {booking['pnr']}")
        print(f"  SuperPNR ID: {booking['super_pnr_id']}")
        print(f"  Status: {booking['status']}")
        print(f"  Cart ID: {booking['cart_id']}")

        # Step 5: Generate confirmation document
        print(f"\n=== Step 4: Confirmation Doc ===")
        doc = client.generate_document(
            document_type="CONFIRMATION",
            super_pnr_id=booking["super_pnr_id"],
        )
        if doc["success"]:
            print(f"  Document generated ({doc['content_type']})")
        else:
            print(f"  Document error: {doc.get('error')}")
    else:
        print(f"  Booking failed at step '{booking.get('step')}': {booking['error']}")

    # Step 6: Search bookings
    print(f"\n=== Step 5: Search Bookings ===")
    bookings = client.search_bookings(
        date_from="2026-02-01",
        date_to="2026-12-31",
    )
    if bookings["success"]:
        summary = bookings["summary"]
        print(f"  Open: {summary.get('openBookings', 0)}")
        print(f"  Issued: {summary.get('issued', 0)}")
        print(f"  Cancelled: {summary.get('cancelled', 0)}")


def manual_cart_example():
    """Lower-level booking: manually manage cart and checkout separately."""

    # Search first...
    result = client.search_flights("JFK", "LHR", "2026-06-15")
    if not result["success"]:
        return

    fare_search_id = result["fare_search_id"]
    fare_id = result["flights"][0]["fare_id"]

    # Step 1: Add to cart and checkout
    cart = client.add_to_cart_and_checkout(
        fare_search_id=fare_search_id,
        fare_id=fare_id,
        passengers=[{
            "firstName": "Jane",
            "lastName": "Doe",
            "paxType": "ADT",
            "gender": "Female",
        }],
        markup_amount=10.00,
    )

    if not cart["success"]:
        print(f"Cart error: {cart['error']}")
        return

    print(f"Cart ID: {cart['cart_id']}")

    # Step 2: Create booking from cart
    booking = client.create_booking(
        shopping_cart_id=cart["cart_id"],
        order_tickets=True,
    )

    if booking["success"]:
        print(f"PNR: {booking['pnr']}")
    else:
        # Clean up on failure
        client.delete_shopping_cart(cart["cart_id"])
        print(f"Booking failed: {booking['error']}")


if __name__ == "__main__":
    print("NOTE: This will attempt REAL bookings. Use sandbox credentials only.\n")
    booking_example()
