"""
PHOENIX Database Seed Script

Populates the database with realistic demo data for development and testing.

Usage:
    python seed_db.py          # Seed with default data
    python seed_db.py --reset  # Drop all tables and re-seed
    python seed_db.py --count  # Show current record counts
"""

import argparse
import json
import random
import secrets
import sys
import os
from datetime import datetime, timedelta, date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from server import app, db
from models import (
    User, Deal, Payment, Booking, PriceAlert, Escrow,
    HelperProfile, UserWallet, UserCard, P2PTransaction, P2PEscrow,
)


# --- Seed Data Constants ---

HELPERS = [
    {"country": "GB", "city": "London", "tz": "Europe/London"},
    {"country": "ES", "city": "Madrid", "tz": "Europe/Madrid"},
    {"country": "JP", "city": "Tokyo", "tz": "Asia/Tokyo"},
    {"country": "IN", "city": "Mumbai", "tz": "Asia/Kolkata"},
    {"country": "BR", "city": "São Paulo", "tz": "America/Sao_Paulo"},
    {"country": "DE", "city": "Berlin", "tz": "Europe/Berlin"},
    {"country": "MX", "city": "Mexico City", "tz": "America/Mexico_City"},
    {"country": "KR", "city": "Seoul", "tz": "Asia/Seoul"},
    {"country": "PH", "city": "Manila", "tz": "Asia/Manila"},
    {"country": "CO", "city": "Bogotá", "tz": "America/Bogota"},
    {"country": "TH", "city": "Bangkok", "tz": "Asia/Bangkok"},
    {"country": "NG", "city": "Lagos", "tz": "Africa/Lagos"},
]

AIRLINES = [
    ("BA", "British Airways"), ("JL", "Japan Airlines"), ("AF", "Air France"),
    ("LH", "Lufthansa"), ("EK", "Emirates"), ("SQ", "Singapore Airlines"),
    ("QF", "Qantas"), ("AA", "American Airlines"), ("DL", "Delta"),
    ("UA", "United Airlines"), ("IB", "Iberia"), ("AV", "Avianca"),
]

ROUTES = [
    ("JFK", "LHR"), ("LAX", "NRT"), ("SFO", "CDG"), ("ORD", "FRA"),
    ("MIA", "MAD"), ("JFK", "DXB"), ("LAX", "SIN"), ("SFO", "HND"),
    ("JFK", "NRT"), ("ORD", "LHR"), ("EWR", "CDG"), ("BOS", "DUB"),
    ("ATL", "FCO"), ("DFW", "GRU"), ("SEA", "ICN"), ("IAD", "AMS"),
]

MARKETS = {
    "LHR": ("GB", "GBP"), "NRT": ("JP", "JPY"), "HND": ("JP", "JPY"),
    "CDG": ("FR", "EUR"), "FRA": ("DE", "EUR"), "MAD": ("ES", "EUR"),
    "DXB": ("AE", "AED"), "SIN": ("SG", "SGD"), "DUB": ("IE", "EUR"),
    "FCO": ("IT", "EUR"), "GRU": ("BR", "BRL"), "ICN": ("KR", "KRW"),
    "AMS": ("NL", "EUR"),
}

P2P_STATUSES = [
    "requested", "matched", "escrow_locked", "helper_accepted",
    "purchasing", "confirmed", "completed", "failed", "cancelled",
]

CARD_BRANDS = ["visa", "mastercard", "amex"]

FIRST_NAMES = [
    "Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Jamie",
    "Avery", "Quinn", "Sage", "Kai", "Dakota", "Reese", "Emery",
    "Skyler", "Rowan", "Finley", "Harper", "Blair", "Drew",
]

LAST_NAMES = [
    "Chen", "Patel", "Kim", "Silva", "Garcia", "Müller", "Tanaka",
    "Santos", "Lee", "Park", "Nakamura", "Fernandez", "Larson",
    "O'Brien", "Kowalski", "Johansson", "Novak", "Rossi", "Martin", "Ali",
]


def random_date(start_days_ago=90, end_days_ahead=180):
    delta = random.randint(-start_days_ago, end_days_ahead)
    return date.today() + timedelta(days=delta)


def random_past_datetime(days_ago=90):
    delta = random.randint(0, days_ago * 24 * 60)
    return datetime.utcnow() - timedelta(minutes=delta)


def random_xrpl_address():
    return "r" + secrets.token_hex(20)[:33]


def random_tx_hash():
    return secrets.token_hex(32).upper()


def show_counts():
    with app.app_context():
        models = [
            ("Users", User), ("Deals", Deal), ("Payments", Payment),
            ("Bookings", Booking), ("PriceAlerts", PriceAlert),
            ("Escrows", Escrow), ("HelperProfiles", HelperProfile),
            ("UserWallets", UserWallet), ("UserCards", UserCard),
            ("P2PTransactions", P2PTransaction), ("P2PEscrows", P2PEscrow),
        ]
        print("\n  PHOENIX Database Record Counts")
        print("  " + "=" * 35)
        for name, model in models:
            count = model.query.count()
            print(f"  {name:<20} {count:>6}")
        print()


def seed():
    with app.app_context():
        print("\n  Seeding PHOENIX database...\n")

        # --- 1. Admin user ---
        admin = User(
            email="admin@phoenix.flights",
            name="Phoenix Admin",
            is_admin=True,
            is_verified=True,
            is_active=True,
            home_market="US",
            created_at=datetime.utcnow() - timedelta(days=180),
        )
        admin.set_password("PhoenixAdmin123!")
        db.session.add(admin)
        db.session.flush()
        print("  [+] Admin user created (admin@phoenix.flights / PhoenixAdmin123!)")

        # --- 2. Demo buyer ---
        demo = User(
            email="demo@phoenix.flights",
            name="Demo Buyer",
            is_verified=True,
            is_active=True,
            home_market="US",
            xrp_wallet_address=random_xrpl_address(),
            created_at=datetime.utcnow() - timedelta(days=60),
        )
        demo.set_password("DemoUser123!")
        db.session.add(demo)
        db.session.flush()
        demo_wallet = UserWallet(
            user_id=demo.id,
            wallet_address=demo.xrp_wallet_address,
            wallet_label="Primary",
            is_primary=True,
            is_verified=True,
        )
        db.session.add(demo_wallet)
        print("  [+] Demo buyer created (demo@phoenix.flights / DemoUser123!)")

        # --- 3. Regular users ---
        users = [admin, demo]
        for i in range(8):
            fname = FIRST_NAMES[i]
            lname = LAST_NAMES[i]
            u = User(
                email=f"{fname.lower()}.{lname.lower()}@example.com",
                name=f"{fname} {lname}",
                is_verified=random.choice([True, True, True, False]),
                is_active=True,
                home_market="US",
                created_at=random_past_datetime(90),
            )
            u.set_password("TestUser123!")
            db.session.add(u)
            db.session.flush()
            users.append(u)

            if random.random() > 0.4:
                w = UserWallet(
                    user_id=u.id,
                    wallet_address=random_xrpl_address(),
                    wallet_label="Primary",
                    is_primary=True,
                    is_verified=random.choice([True, False]),
                )
                db.session.add(w)

            if random.random() > 0.6:
                c = UserCard(
                    user_id=u.id,
                    card_label=f"{random.choice(CARD_BRANDS).title()} ending {random.randint(1000,9999)}",
                    card_last_four=str(random.randint(1000, 9999)),
                    card_brand=random.choice(CARD_BRANDS),
                    card_exp_month=random.randint(1, 12),
                    card_exp_year=random.randint(2026, 2030),
                    billing_name=f"{fname} {lname}",
                    billing_country="US",
                    is_active=True,
                )
                db.session.add(c)

        print(f"  [+] {len(users) - 2} regular users created")

        # --- 4. Helper profiles ---
        helper_users = []
        helper_profiles = []
        for i, h in enumerate(HELPERS):
            fname = FIRST_NAMES[len(users) + i] if (len(users) + i) < len(FIRST_NAMES) else f"Helper{i}"
            lname = LAST_NAMES[i % len(LAST_NAMES)]
            hu = User(
                email=f"helper.{h['country'].lower()}.{i}@example.com",
                name=f"{fname} {lname}",
                is_verified=True,
                is_active=True,
                home_market=h["country"],
                xrp_wallet_address=random_xrpl_address(),
                created_at=random_past_datetime(120),
            )
            hu.set_password("Helper123!")
            db.session.add(hu)
            db.session.flush()
            helper_users.append(hu)

            total_tx = random.randint(0, 80)
            success_tx = int(total_tx * random.uniform(0.85, 0.98))
            hp = HelperProfile(
                user_id=hu.id,
                country_code=h["country"],
                city=h["city"],
                timezone=h["tz"],
                is_active=random.choice([True, True, True, False]),
                is_approved=i < 10,  # First 10 approved
                is_online=random.choice([True, False]) if i < 10 else False,
                total_transactions=total_tx,
                successful_transactions=success_tx,
                failed_transactions=total_tx - success_tx,
                total_earned_rlusd=round(success_tx * random.uniform(15, 45), 2),
                average_rating=round(random.uniform(4.2, 5.0), 1),
                available_hours_start=random.choice([0, 6, 8]),
                available_hours_end=random.choice([18, 22, 24]),
                max_daily_transactions=random.randint(5, 15),
                created_at=random_past_datetime(120),
                last_active=random_past_datetime(7) if i < 8 else None,
            )
            db.session.add(hp)
            db.session.flush()
            helper_profiles.append(hp)

            hw = UserWallet(
                user_id=hu.id,
                wallet_address=hu.xrp_wallet_address,
                wallet_label="Helper Wallet",
                is_primary=True,
                is_verified=True,
            )
            db.session.add(hw)

        print(f"  [+] {len(HELPERS)} helper profiles created across {len(set(h['country'] for h in HELPERS))} markets")

        # --- 5. Deals ---
        deals = []
        for i in range(25):
            origin, dest = random.choice(ROUTES)
            market_info = MARKETS.get(dest, ("XX", "USD"))
            airline_code, airline_name = random.choice(AIRLINES)
            flight_num = f"{airline_code}{random.randint(100, 999)}"

            us_price = round(random.uniform(350, 1800), 2)
            savings_pct = random.uniform(0.10, 0.40)
            arb_price = round(us_price * (1 - savings_pct), 2)
            gross_savings = round(us_price - arb_price, 2)
            platform_fee = round(gross_savings * 0.03, 2)
            user_savings = round(gross_savings - platform_fee, 2)

            dep_date = random_date(start_days_ago=10, end_days_ahead=120)
            d = Deal(
                deal_id=f"PX-{secrets.token_hex(4).upper()}",
                airline=airline_name,
                flight_number=flight_num,
                origin=origin,
                destination=dest,
                departure_date=dep_date,
                departure_time=f"{random.randint(6, 22):02d}:{random.choice(['00','15','30','45'])}",
                arrival_time=f"{random.randint(6, 22):02d}:{random.choice(['00','15','30','45'])}",
                stops=random.choices([0, 1, 2], weights=[60, 30, 10])[0],
                home_market="US",
                home_price_usd=us_price,
                arbitrage_market=market_info[0],
                arbitrage_price_usd=arb_price,
                arbitrage_currency=market_info[1],
                gross_savings_usd=gross_savings,
                platform_fee_usd=platform_fee,
                user_savings_usd=user_savings,
                savings_percent=round(savings_pct * 100, 1),
                destination_tag=random.randint(100000, 999999),
                is_active=dep_date > date.today(),
                expires_at=datetime.combine(dep_date, datetime.min.time()) - timedelta(days=1),
                created_at=random_past_datetime(30),
            )
            db.session.add(d)
            db.session.flush()
            deals.append(d)

        print(f"  [+] {len(deals)} flight deals created")

        # --- 6. Some bookings and payments ---
        for i in range(6):
            buyer = random.choice(users[1:])
            deal = random.choice(deals[:15])
            status = random.choice(["pending", "booked", "completed", "completed"])

            payment = Payment(
                user_id=buyer.id,
                deal_id=deal.id,
                payment_method=random.choice(["xrp", "rlusd", "card"]),
                amount_usd=deal.home_price_usd,
                destination_tag=deal.destination_tag,
                status="verified" if status in ("booked", "completed") else "pending",
                tx_hash=random_tx_hash() if status != "pending" else None,
                created_at=random_past_datetime(45),
            )
            db.session.add(payment)
            db.session.flush()

            booking = Booking(
                user_id=buyer.id,
                deal_id=deal.id,
                payment_id=payment.id,
                passenger_name=buyer.name,
                passenger_email=buyer.email,
                confirmation_code=f"PNR{secrets.token_hex(3).upper()}" if status in ("booked", "completed") else None,
                status=status,
                fulfillment_type=random.choice(["self_service", "automated"]),
                created_at=payment.created_at,
                booked_at=payment.created_at + timedelta(hours=1) if status in ("booked", "completed") else None,
            )
            db.session.add(booking)

        print(f"  [+] 6 bookings with payments created")

        # --- 7. P2P Transactions ---
        p2p_count = 0
        for i in range(15):
            buyer = random.choice(users[1:5])
            hp = random.choice(helper_profiles[:10])
            origin, dest = random.choice(ROUTES)
            market_info = MARKETS.get(dest, ("XX", "USD"))
            airline_code, airline_name = random.choice(AIRLINES)

            us_price = round(random.uniform(400, 1500), 2)
            target_price = round(us_price * random.uniform(0.60, 0.85), 2)
            savings = round(us_price - target_price, 2)
            helper_cut = round(target_price * 0.05, 2)
            platform_fee = round(target_price * 0.03, 2)
            escrow_total = round(target_price + helper_cut + platform_fee, 2)

            status = random.choice(P2P_STATUSES)
            created = random_past_datetime(60)

            tx = P2PTransaction(
                transaction_id=f"P2P-{secrets.token_hex(6).upper()}",
                buyer_id=buyer.id,
                helper_id=hp.id if status != "requested" else None,
                origin=origin,
                destination=dest,
                departure_date=random_date(start_days_ago=5, end_days_ahead=90),
                airline=airline_name,
                flight_number=f"{airline_code}{random.randint(100, 999)}",
                us_price_usd=us_price,
                target_price_usd=target_price,
                target_market=market_info[0],
                target_currency=market_info[1],
                savings_usd=savings,
                escrow_amount_rlusd=escrow_total,
                helper_reimbursement_rlusd=target_price,
                helper_earning_rlusd=helper_cut,
                platform_fee_rlusd=platform_fee,
                escrow_tx_hash=random_tx_hash() if status not in ("requested", "matched") else None,
                status=status,
                confirmation_code=f"PNR{secrets.token_hex(3).upper()}" if status in ("confirmed", "completed") else None,
                passenger_name=buyer.name,
                passenger_email=buyer.email,
                created_at=created,
                matched_at=created + timedelta(minutes=random.randint(1, 30)) if status != "requested" else None,
                escrow_locked_at=created + timedelta(minutes=random.randint(30, 60)) if status not in ("requested", "matched") else None,
                confirmed_at=created + timedelta(hours=random.randint(1, 4)) if status in ("confirmed", "completed") else None,
                completed_at=created + timedelta(hours=random.randint(4, 8)) if status == "completed" else None,
                cancelled_at=created + timedelta(hours=1) if status == "cancelled" else None,
                failure_reason="Helper browser disconnected" if status == "failed" else None,
            )
            db.session.add(tx)
            db.session.flush()
            p2p_count += 1

            # Create P2P escrow for transactions past the escrow stage
            if status not in ("requested", "matched"):
                pe = P2PEscrow(
                    escrow_id=f"ESC-{secrets.token_hex(6).upper()}",
                    p2p_transaction_id=tx.id,
                    buyer_address=random_xrpl_address(),
                    helper_address=random_xrpl_address() if status != "requested" else None,
                    platform_address="rPHOENIXPlatformWallet123456789",
                    total_rlusd=escrow_total,
                    helper_amount_rlusd=target_price + helper_cut,
                    platform_amount_rlusd=platform_fee,
                    create_tx_hash=random_tx_hash(),
                    condition=secrets.token_hex(32),
                    status="released" if status == "completed" else (
                        "cancelled" if status in ("failed", "cancelled") else "locked"
                    ),
                    on_chain_verified=status not in ("requested", "matched"),
                    created_at=tx.escrow_locked_at or created,
                    released_at=tx.completed_at if status == "completed" else None,
                    cancelled_at=tx.cancelled_at if status in ("failed", "cancelled") else None,
                    cancel_after=created + timedelta(hours=24),
                )
                db.session.add(pe)

        print(f"  [+] {p2p_count} P2P transactions created with escrows")

        # --- 8. Price alerts ---
        for i in range(5):
            buyer = random.choice(users[1:5])
            origin, dest = random.choice(ROUTES)
            pa = PriceAlert(
                user_id=buyer.id,
                origin=origin,
                destination=dest,
                max_price_usd=round(random.uniform(300, 800), 0),
                min_savings_percent=random.choice([10, 15, 20, 25]),
                is_active=True,
                created_at=random_past_datetime(30),
            )
            db.session.add(pa)

        print(f"  [+] 5 price alerts created")

        db.session.commit()
        print("\n  Database seeded successfully!\n")
        show_counts()


def reset_and_seed():
    with app.app_context():
        print("\n  Dropping all tables...")
        db.drop_all()
        print("  Recreating tables...")
        db.create_all()
        print("  Tables recreated.\n")
    seed()


def main():
    parser = argparse.ArgumentParser(description="PHOENIX Database Seed Script")
    parser.add_argument("--reset", action="store_true", help="Drop all tables and re-seed")
    parser.add_argument("--count", action="store_true", help="Show current record counts")
    args = parser.parse_args()

    if args.count:
        show_counts()
    elif args.reset:
        reset_and_seed()
    else:
        seed()


if __name__ == "__main__":
    main()
