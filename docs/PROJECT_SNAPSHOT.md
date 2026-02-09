# Phoenix Platform — Project Snapshot

**Snapshot Date:** February 9, 2026
**Current Build:** #100
**Status:** Awaiting Amadeus credentials + Airline Consolidator

---

## Quick Resume Checklist

When returning to this project:

1. **Read this file first**
2. **Check `docs/BUILD_LOG_100.md`** for last session's work
3. **Run the server:** `python server.py`
4. **Production URL:** https://phoenix-web-nj67.onrender.com

---

## Project Stats

- **~90,500 lines of Python** across 89 files
- **Largest files:** server.py (20K), models.py (4K), phoenix_ai.py (3K)
- **Git commits:** 100+ builds

---

## What's Built & Working

### Core Platform
- [x] User authentication (email + OAuth: Google, Apple, Microsoft)
- [x] Dashboard with tier info
- [x] Settings page
- [x] Wallet management (crypto + cards)

### Phoenix AI
- [x] LLM-powered tool-calling engine (26+ tools)
- [x] Flight search with multi-market comparison
- [x] Hotel, cruise, rental, product search
- [x] Route intelligence and market briefings
- [x] Booking flow with traveler collection
- [x] Tier-based query limits

### Booking Infrastructure
- [x] TravelerProfile model (IATA/APIS compliant)
- [x] Traveler management UI at /travelers
- [x] Multi-passenger booking (up to 9 per PNR)
- [x] Amadeus client ready (needs credentials)
- [x] Payment infrastructure (Stripe + Crypto)

### Node Network
- [x] Node registration and management
- [x] Tier system (Bronze → Platinum)
- [x] Anti-dilution protection
- [x] Yield dashboard
- [x] Escrow and payout logic

### Data Products
- [x] Data marketplace
- [x] Browsing tiers for B2B data access
- [x] SERP API tiers
- [x] Zone pricing engine

### Admin
- [x] Admin dashboard
- [x] Feature flags (Layer 1/2/3)
- [x] Node management
- [x] Security/anti-dilution controls

---

## What's Pending (Blocked by External)

| Item | Blocker | Action Needed |
|------|---------|---------------|
| Live flight booking | Amadeus credentials | Apply for enterprise account |
| Payment processing | Airline consolidator | Partnership agreement |
| LLC formation | User action | Legal setup |

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `server.py` | Main Flask app (20K lines, all routes) |
| `models.py` | SQLAlchemy models |
| `phoenix_ai.py` | AI engine with tool definitions |
| `amadeus_client.py` | Amadeus GDS integration |
| `node_antidilution.py` | Sybil attack protection |
| `data_marketplace.py` | B2B data products |

---

## Documentation

| Doc | Contents |
|-----|----------|
| `docs/BUILD_LOG_100.md` | Last session's work (Feb 6, 2026) |
| `docs/NODE_REWARD_MODEL.md` | Complete node economics + anti-dilution |
| `docs/PHOENIX_MODEL.md` | Platform architecture reference |
| `PHOENIX_MODEL_2.md` | Updated structural reference |

---

## Environment Variables Needed

```
DATABASE_URL=postgresql://...
ANTHROPIC_API_KEY=sk-ant-...
AMADEUS_API_KEY=...        # PENDING
AMADEUS_API_SECRET=...     # PENDING
STRIPE_SECRET_KEY=sk_...
STRIPE_WEBHOOK_SECRET=whsec_...
```

---

## Git Remote

```
origin: https://github.com/serenity22is-ai/phoenix-platform.git
```

All work is pushed. Nothing will be lost.

---

## To Resume Development

```bash
cd /Users/adramainjest/flightfinder2
git pull origin main
python server.py
```

Then tell Claude: "Let's continue working on Phoenix. Read docs/PROJECT_SNAPSHOT.md first."

---

*Phoenix is ready. Just waiting on the business side.*
