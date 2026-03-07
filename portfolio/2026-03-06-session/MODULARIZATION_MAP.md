# Server.py Modularization Map
## Build #136 — March 6, 2026

## Before → After
```
BEFORE: server.py = 22,289 lines, 254 routes (everything in one file)
AFTER:  server.py = 15,070 lines, 118 routes (Phase 1 only)
        + routes_hotels.py (3 routes)
        + routes_xrpl.py (11 routes)
        + routes_p2p.py (122 routes)
```

## What Stayed in server.py (Phase 1 — Active)
Core OTA functionality for flight arbitrage platform:
- `/` — Landing page
- `/login`, `/register`, `/logout` — Authentication
- `/search`, `/api/search` — Flight search via Picasso + Google price matching
- `/dashboard` — User dashboard
- `/deals`, `/deals/<id>` — Deal management
- `/booking-status/<id>`, `/booking-confirmation/<id>` — Booking lifecycle
- `/pay/stripe`, `/pay/stripe/confirm` — Stripe payments
- `/admin` — Admin dashboard (slimmed to 6 links)
- `/admin/payments`, `/admin/users`, `/admin/deals` — Core admin
- `/admin/features` — Feature flag management
- `/admin/security` — Security settings
- `/health` — Health check (Render monitoring)
- `/api/mystes-ai` — AI chat endpoint
- `/api/picasso/*` — Picasso API proxy routes (6 routes)

## What Was Extracted

### routes_hotels.py (Phase 2 — Hotels via liteAPI)
```
/hotels                  — Hotel search page
/api/hotels/search       — Hotel search API
/api/hotels/select       — Hotel selection/booking
```
Templates: HOTELS_SEARCH_CONTENT, HOTEL_BOOK_CONTENT
Re-enable: from routes_hotels import register_hotel_routes; register_hotel_routes(app, csrf, limiter)

### routes_xrpl.py (Phase 2/3 — Crypto Payments)
```
/api/escrow/create       — Create XRPL escrow
/api/escrow/confirm      — Confirm escrow
/api/escrow/release      — Release escrow
/api/escrow/cancel       — Cancel escrow
/api/escrow/<id>         — Escrow details
/wallet                  — User wallet page
/wallet/add              — Add wallet address
/wallet/remove           — Remove wallet
/card/add                — Add payment card
/card/remove             — Remove payment card
/pay/verify/xrp          — Verify XRP payment
/pay/verify/rlusd        — Verify RLUSD payment
/admin/wallet            — Admin wallet management
```
Templates: WALLET_CONTENT, ADMIN_WALLET_CONTENT
Re-enable: from routes_xrpl import register_xrpl_routes; register_xrpl_routes(app, csrf, limiter)

### routes_p2p.py (Phase 2 — P2P Network / CitizenSERP)
```
EARN PORTAL (3 routes)
/earn                    — Earn landing page
/earn/register           — Register as helper
/api/earn/register       — Registration API

PORTAL (5 routes)
/portal                  — Portal dashboard
/portal/ai               — Portal AI interface
/portal/intelligence     — Intelligence dashboard
/api/portal/intelligence — Intelligence API
/api/portal/deals        — Portal deals

BROWSE (4 routes)
/browse                  — Browse helpers
/browse/zones            — Browse zones
/api/browse/helpers      — Helpers API
/api/browse/zones        — Zones API

ZONE MANAGEMENT (5 routes)
/api/zones               — List zones
/api/zones/create        — Create zone
/api/zones/<id>          — Zone details
/api/zones/<id>/tasks    — Zone tasks
/api/zones/<id>/join     — Join zone

NODE DASHBOARD (3 routes)
/node/dashboard          — Node operator dashboard
/api/node/yield          — Node yield data
/api/node/economics      — Network economics

HELPER DASHBOARD (4 routes)
/helper/dashboard        — Helper dashboard
/api/helper/status       — Helper status
/api/helper/availability — Set availability
/api/helper/history      — Transaction history

P2P BOOKING (6 routes)
/p2p/book                — P2P booking page
/api/p2p/match           — Match with helper
/api/p2p/book            — Create P2P booking
/api/p2p/status/<id>     — Booking status
/api/p2p/confirm/<id>    — Confirm booking
/api/p2p/cancel/<id>     — Cancel booking

ADMIN (80+ routes)
/admin/p2p               — P2P admin dashboard
/admin/helpers           — Helper management
/admin/nodes             — Node management
/admin/node-fleet        — Fleet overview
/admin/disbursement      — Payout management
/admin/consent-economy   — Consent management
/admin/strategy          — Strategy learner
/admin/data-marketplace  — Data marketplace
/api/admin/node/*        — Node registry, pipelines, feedback, disputes
/api/admin/installer/*   — Node installer
... and 60+ more admin API routes
```
Templates: 15 total (EARN, PORTAL, NODE_YIELD_DASHBOARD, HELPER_DASHBOARD, etc.)
Re-enable: from routes_p2p import register_p2p_routes; register_p2p_routes(app, csrf, limiter)

## Admin Portal — Before vs After

### Navigation (ADMIN_NAV)
```
BEFORE (14 links):
Dashboard | Payments | Users | Deals | Features | Security |
Wallet | Proxies | P2P | Helpers | Tasks | Nodes | Payouts | Consent Economy

AFTER (6 links):
Dashboard | Payments | Users | Deals | Features | Security
```

### Dashboard Cards
```
REMOVED: Wallet Balance, Proxy Status, P2P Network, Helper Pool
ADDED:   Feature Flags, Security Settings
KEPT:    Revenue, Active Users, Pending Deals, System Status
```
