# PHOENIX PROJECT - SESSION CONTEXT LOG

**CRITICAL: Read this file FIRST at the start of every new session before making ANY changes.**
**UPDATE: After every user prompt, capture key points and user intent below.**
**ARCHIVE: Before any context compaction, write a compressed archive to `session_archives/`.**

Last updated: 2026-01-30 (Prompt #70 of current session)

---

## USER COMMUNICATION STYLE & EXPECTATIONS

- The user is building faster than they can manually track — they rely on Claude to be the memory and continuity layer
- **Do NOT ask the user to remember or re-explain decisions** — that's Claude's job
- The user expects Claude to review prior work and context BEFORE making changes
- If unsure about a prior decision, check this file and the codebase — do not guess or assume
- The user will correct Claude directly when something is wrong — take corrections seriously and update this file
- This project will grow to thousands of lines — maintaining context is non-negotiable

---

## ARCHITECTURAL DECISIONS (DO NOT REVERSE)

### 1. SerpAPI is DEPRECATED — Use Amadeus + Proxies
- **Decision date:** ~2026-01-28
- **Reason:** SerpAPI rate limits (429 errors) made it unreliable. We hit the limit repeatedly and it blocked searches.
- **What replaced it:** Amadeus API (flight details) + Residential proxies via Playwright (regional pricing)
- **Current state:** SerpAPI code still exists in main.py (`fetch_flights()`, `SERPAPI_URL`, `API_KEY`) but is NOT called by any active search path. It is dead code.
- **DO NOT:** Re-add SerpAPI as a fallback, add rate limiting for SerpAPI, or reference it in new code.

### 2. Search Priority Chain
```
1. Amadeus + Proxy (best) → search_amadeus_with_proxy_prices()
2. Proxy-only (if no Amadeus) → search_proxy_only()
3. Return error with config guidance (NO silent fallback)
```
- Defined in `search.py:search_global()` and `main.py:search_hybrid()`
- `search_hybrid()` uses Amadeus for flight details (not SerpAPI)

### 3. Proxy Strategy: Paid Residential + P2P Node Network
- **P2P goal**: Node network replaces paid proxies market-by-market as user density scales in each region
- **Paid proxies supplement**: Fill gaps in markets with weak node coverage or where more proxy capacity is needed
- **Transition**: Per-market — once a market has sufficient P2P nodes, paid proxies for that market can be retired
- **Always available as backup**: Paid proxies (Webshare or similar) are never fully removed — they remain as permanent backup even after P2P covers a market
- Residential proxies with country-targeting
- Manual proxy URLs configured in .env for US, ES, UK, PL
- Auto-generation from credentials supported but credentials not yet in .env

### 4. Payment System: Multi-method
- XRP + RLUSD on XRPL (configured, testnet)
- Stripe (not yet configured)
- Coinbase Commerce (not yet configured)
- XRPL Escrow for trustless booking

### 5. Booking Fulfillment: Four modes
- Self-service (user books via proxy link)
- Automated (platform books with card — card not configured)
- Manual agent
- **P2P Network (System 2)** — helper in target market executes purchase via Phoenix-controlled browser session

### 6. P2P Purchasing Network (System 2) — DECIDED 2026-01-29
- **Purpose:** Fallback/upgrade to System 1 (proxy scraping). Uses real humans in foreign markets as booking endpoints instead of proxy IPs. Activates when corporations block System 1, or as opt-in feature.
- **How it works:**
  1. Proxies still handle price discovery (find cheapest market)
  2. Helper in target market grants Phoenix temporary browser control via client app
  3. Phoenix automates the purchase on helper's device (same Playwright scripts, different execution env)
  4. Helper's device = real IP, real Google account, real browser fingerprint = undetectable
- **Payment flow (RLUSD closed-loop):**
  1. Buyer converts USD → RLUSD (1:1 stablecoin)
  2. Buyer deposits RLUSD into XRPL escrow smart contract
  3. Helper can verify escrow is locked ON-CHAIN before accepting
  4. Helper purchases ticket with their own card (trusts on-chain escrow guarantee)
  5. Booking confirmation triggers escrow release
  6. RLUSD releases to: helper (reimbursement + cut), platform (fee)
  7. Helper uses RLUSD for their own future flights OR cashes out via Coinbase Commerce → XRP → local fiat
- **On-chain verification:** Both parties can inspect the locked escrow on XRPL ledger — genuinely trustless
- **No Phoenix seed capital needed:** Buyer's RLUSD is locked before helper purchases. Helper fronts with credit card, gets RLUSD immediately on confirmation.
- **Token system (RESERVE — only if needed):** Phoenix token on XRPL backed 1:1 by RLUSD. Only build if direct RLUSD payments create friction. Not planned for initial build.
- **DO NOT:** Build token system without explicit user approval. Keep payment rails on RLUSD/XRP/Coinbase Commerce.
- **Wallet onboarding:** Users connect XRPL wallets + payment cards to their profile. Buyers need wallet (for escrow deposits) + optional card. Helpers need wallet (for receiving RLUSD) + card (for fronting ticket purchases). Coinbase Commerce for RLUSD on/off ramp. Balance displayed by querying XRPL ledger directly.
- **Exchange on-ramp:** Users need to acquire RLUSD/XRP to fund their wallet. Primary: Coinbase. Global alternatives: Binance, Kraken, Uphold, Bitstamp, Crypto.com. Embedded buy widget (MoonPay or Transak) for in-app purchases without leaving Phoenix. Show exchange recommendations by user's country/region.

### 7. Commercial Account Onboarding — DECIDED 2026-01-29
- **Purpose:** Onboard travel agencies, OTAs, and corporate travel desks to use Phoenix as their arbitrage engine via API.
- **Fee model:** Percentage of realized savings ONLY. No minimum fee. No charge if no savings found. Pure value alignment — Phoenix earns only when it delivers value.
- **Tier ladder (performance-based, rolling 30-day ticket volume):**
  - Starter: 0+ tickets → 20% of savings
  - Professional: 50+ tickets → 15% of savings
  - Enterprise: 500+ tickets → 10% of savings
  - Partner: 5,000+ tickets → 7% of savings
- **Use-it-or-lose-it mechanic:** If volume drops below tier threshold for 2 consecutive 30-day periods, rate cut suspends (tier downgrades). Incentivizes agencies to keep pushing volume through Phoenix.
- **P2P access:** All tiers have P2P network access. Agencies onboarding clients doubles as P2P helper recruitment (users run residential proxy nodes).
- **No data exclusivity:** All accounts access the same data. Rate exclusivity only, based on performance.
- **API-first:** Commercial accounts authenticate via API key (phx_xxx), not session cookies. Endpoints: /api/v1/search, /api/v1/account/stats, /api/v1/account/tier.
- **Fee only on completed transactions:** Searches are free (within daily quota). Fee calculated and recorded only on booked tickets.
- **Agency flywheel:** Agencies onboard their clients to Phoenix portal → clients link Google accounts → Phoenix handles booking → agencies get savings kickbacks (lower fee tiers). Clients become passive P2P helper nodes, expanding Phoenix's residential proxy network. More clients = more markets = better scraping = more savings for everyone.
- **Referral system:** Each commercial account gets a unique referral code (e.g. "APEXTRAVEL"). /join/<code> redirects to signup with attribution. Referred users tracked, helper node conversions counted. Agencies can view referral stats via API or dashboard.
- **DO NOT:** Add minimum fees. DO NOT gate P2P access by tier. DO NOT offer data exclusivity.

### 8. Core Mission & Market Position — DECIDED 2026-01-29
- **Core mission:** Phoenix is not choosing a side — it is choosing everyone. A neutral intermediary that strengthens the relationship between consumer and airline through pricing transparency. The airline can no longer bully the consumer. This is the core message to both consumers and airlines.
- **Phoenix is NOT adversarial to airlines.** Geo-pricing is structural — driven by local economies, currency fluctuations, airline scale, and regulatory costs. It cannot be eliminated. Phoenix exposes it, and all parties benefit from transparency.
- **Three-sided market model:**
  - **Consumers** — pay 25% of realized savings. Get fair pricing across markets.
  - **Agencies/OTAs** — pay 7-20% of savings (tier-based). Get arbitrage engine via API.
  - **Airlines** — pay $100K-500K/mo SaaS subscription. Get competitive pricing intelligence, ancillary optimization data (bags, seats, meals by geography), route-level market positioning. Separate data-as-a-service product, NOT booking.
- **Airline Intelligence Product:** Airlines use Phoenix data to sharpen their competitive positioning WITHIN geo-pricing, not to close arbitrage gaps. More aggressive airline competition creates MORE arbitrage opportunities, not fewer. Ancillary pricing intelligence (bags, seats, upgrades by market) is uniquely valuable — no one else provides it.
- **MAD (Mutually Assured Destruction) strategic position:** Phoenix earns whether airlines subscribe or don't. Airlines that subscribe get competitive edge via data. Airlines that don't subscribe get exposed by Phoenix offering their passengers better pricing through competitors. Either way Phoenix earns, and consumers benefit. This hedges revenue across all scenarios.
- **"Citizen API" concept:** People-powered market data layer accessible to all participants. Phoenix becomes a provably honest API built on real user data, not institutional data feeds. GDS/ATPCO don't provide real consumer-facing prices — Phoenix does.
- **Airline SaaS creates strategic relationships** that provide legal and regulatory cover for the core consumer product.
- **Revenue model key assumptions (IATA 2026):**
  - 5.2B global passengers, ~$700 avg ticket price
  - Per 1% global capture: ~$310M annual revenue (moderate scenario)
  - At 5% capture: ~$1.55B annual, 60-90M users, 300K-500K active helpers
  - Airline SaaS: $210-336M at maturity
  - Combined mature revenue target: $910M-1.34B at 65-70% margin
- **Helper payout model:**
  - Active helpers: 10% of realized savings per booking (paid from escrow). Bootstrap phase: 15-20%.
  - Passive scraping nodes: $0.10-0.25/hour uptime
  - Three phases: Bootstrap (15-20% helper cut) → Growth (10%) → Mature Equilibrium (10% locked)
  - Savings compression: ~11% avg savings early → 6-8% at maturity as arbitrage gets exploited at scale
  - Equilibrium: Phoenix $65-95M/month revenue, avg active helper $100-200/month, passive node $12-20/month (at 5% capture)
- **CitizenSERP Micropayment Model (Node Payout from Airline SaaS Revenue):**
  - Residential proxy nodes (Phoenix users) are the data collection layer powering the Airline Intelligence product
  - Two income streams per node: Variable (% of booking savings, compresses at maturity) + Fixed (CitizenSERP micropayments, steady)
  - Fixed stream = percentage of airline SaaS subscription revenue distributed to all running nodes proportional to verified uptime
  - Uptime verified on-chain via XRPL — blockchain record of time each node was online and available for use
  - XRPL micropayments enable near-zero cost distribution to 500K+ nodes (sub-cent transaction fees)
  - This is the hedge against savings compression: when arbitrage margins shrink at market maturity, CitizenSERP revenue provides steady baseline income that prevents node attrition
  - Flywheel: more airline subscribers → more CitizenSERP revenue pool → higher node payouts → more nodes join → better/more data → more airline subscribers
  - At maturity: Variable stream drops (savings compress 11% → 6-8%), Fixed stream rises (more airline subscribers). Total node income stabilizes.
  - CitizenSERP is opt-in — users can run nodes for CitizenSERP income even when booking savings revenue drops
  - The residential proxy network becomes so large it functions as an open-source market data API — airlines pay exorbitant fees for access to data that no institutional feed (GDS/ATPCO) can provide
- **Multi-Vertical Expansion — Universal Arbitrage Search Engine:**
  - Phoenix is NOT a flight app — flights are vertical #1. The platform expands to all goods and services with geographic pricing arbitrage.
  - CitizenSERP is the infrastructure layer INSIDE Phoenix — the decentralized residential proxy network that powers all verticals. It is not a separate product.
  - **Expansion path:** Flights (built) → Hotels → Cruises → E-Commerce (fashion, electronics) → Software/Digital → Universal search
  - **Endgame:** User types any product or service into Phoenix search, CitizenSERP nodes fan out across markets, return price matrix with arbitrage opportunities. "Carhartt jacket" returns US vs Japan vs UK prices. "JFK to LAX March 1" returns flight prices by market. Same search bar, same node network.
  - **What stays the same across verticals:** Node infrastructure, CitizenSERP payouts, XRPL micropayments, P2P escrow model, on-chain uptime verification, commercial API
  - **What changes per vertical:** Scraping targets/modules, product matching logic, price normalization (currency + tax + shipping + duties for physical goods), fulfillment pathways (booking vs shipping vs instant digital delivery), SaaS data consumers (airlines → retailers → brands → software companies)
  - **Physical goods caveat:** Landed cost (price + shipping + customs + tax) must be calculated — raw price arbitrage on physical goods can be misleading. The search engine must show true delivered cost, not just sticker price.
  - **Node economics improve with each vertical:** Same nodes serve multiple data consumers. Revenue pool grows without proportional node growth. At 3-4 verticals, passive node earnings reach $25-30/month at 1M nodes.
  - **Existing code is vertical-agnostic where it matters:** citizenserp_payouts.py, xrpl_monitor.py, event_stream.py, monitoring.py, node session tracking — none of these reference flights specifically. They work for any vertical.
- **Cross-Market Direct Access — Disintermediation Engine:**
  - Phoenix eliminates middlemen/gatekeepers (importers, brokers, resellers) by giving users direct proxy access to foreign marketplaces
  - Example: US user wants a JDM import car. Today they can only find US importers charging 2x markup. Phoenix provides proxy gateway so they browse Facebook Marketplace Japan directly, see listings locals see, at local prices
  - **Proxy gateway model:** User stays logged into their OWN social/marketplace account (Facebook, etc). Phoenix piggybacks proxy location so the platform's geo-restrictions are bypassed. User sees foreign listings through their own authenticated session.
  - **Communication:** No custom messaging system needed. User is logged into their own Facebook → they use Facebook Messenger directly to contact the seller. Same applies to WhatsApp, Telegram, or any native messaging on the platform. Phoenix just provides the geographic access — the existing communication infrastructure handles the rest.
  - **Translation layer:** Future enhancement — real-time translation overlay for cross-language buyer-seller interaction. But the MVP is just proxy access + existing platform messaging.
  - **Hard goods friction:** Physical goods have shipping, customs, duties — but the transparency alone creates new markets. Users who couldn't even SEE the foreign listing before can now discover it, evaluate true landed cost, and decide for themselves.
  - **This is the endgame vision:** Phoenix doesn't just find price differences — it connects people directly across markets that were previously invisible to each other. The proxy network becomes a market access layer, not just a price comparison tool.
- **Two Transaction Models:**
  - **Retail commerce** (flights, hotels, cruises): Purchased through vendors with checkout flows. Savings model works — detect arbitrage → P2P helper books at lower price → escrow → split savings. Fee = % of realized savings.
  - **Private market** (goods found through proxy portal): No vendor, no reference price. Direct buyer-seller transactions. Phoenix can't (and shouldn't try to) prevent direct payments — users can always exchange wallet addresses through Messenger/WhatsApp. But Phoenix offers voluntary trustless XRPL escrow with real-time AI-built smart contracts. The fee buys trustlessness, not access. Tiered escrow fees: 3% under $100, 2.5% $100-$1K, 2% $1K-$10K, 1.5% $10K+, $500 cap.
- **Phoenix AI Search Engine:**
  - Multi-provider ensemble: queries Claude, Grok, DeepSeek, ChatGPT, Gemini, Mistral, Cohere, HuggingFace, Ollama in parallel, ranks responses, returns best
  - Proxy stays pure — AI is a separate feature layer, not bundled
  - BYOAI (primary path): users log into their own AI subscription (ChatGPT, Claude, Gemini, etc.) through the proxy portal with their own credentials (Google SSO, etc.). Their AI sees data from the proxy's geographic location. No API key needed — user's existing subscription handles billing, Phoenix provides the geographic tunnel. The AI category in the proxy portal app directory (21 LLM sites) IS the BYOAI onboarding mechanism.
  - BYOAI (advanced path): users can also add their provider API key to Phoenix's ensemble search engine (no Phoenix credit cost when using own keys)
  - Credit system: 0.001 RLUSD per query, free tier 10/day, metered via existing RLUSD wallet
  - AI also powers fair value assessment for private market escrow deals
- **Everything runs through Phoenix — data at every touchpoint:**
  - Phoenix is the data layer even when "just" providing proxy access. Every interaction generates capturable market intelligence.
  - Proxy sessions → geographic demand signals (which markets, which sites, how long, what categories)
  - AI search queries → consumer intent data (what people want, from which markets, which providers answer best)
  - Private market deals → private market pricing intelligence (item types, prices, fair values, deal completion rates)
  - BYOAI proxy sessions → AI usage patterns + market interest signals
  - Node network → real-time geographic distribution, availability, uptime
  - All data feeds commercial products: Airline Intelligence SaaS today, multi-vertical market intelligence tomorrow
  - The proxy IS the data collection mechanism. The commercial API (commercial.py) already has tiered access to sell this data.
  - **Core principle: Phoenix learns from every transaction, every query, every session. This accumulated intelligence IS the product that enterprises pay for.**
- **DO NOT:** Frame Phoenix as adversarial to airlines. DO NOT build airline product as a booking tool (data-only SaaS). DO NOT promise savings percentages won't compress at scale. DO NOT build CitizenSERP payouts without on-chain uptime verification. DO NOT build new verticals as separate products — they are vertical plugins within Phoenix. DO NOT build custom messaging — leverage existing platform communication (Facebook Messenger, WhatsApp, Telegram). DO NOT build a marketplace — Phoenix provides access to existing marketplaces across geographic boundaries.

### 9. PhoenixAI Agent Architecture — DECIDED 2026-01-30
- **PhoenixAI is the brain. CitizenSERP is the engine. RLUSD is the fuel.**
- **Agent Mode (Option B: Agent + Ensemble Hybrid):** One capable LLM orchestrates data gathering via tools (intelligence routes), then results fed to 9-model ensemble for consensus. The agent replaces user's manual decision-making about markets, routing, timing.
- **Three coexisting AI systems (NOT redundant):**
  1. **Existing search pipeline (tool):** User-driven — user types query, AI ensemble answers with Phoenix data context. Already built.
  2. **BYOAI via proxy (infrastructure):** User's own AI subscription through geographic tunnel. Already built.
  3. **Agent mode (intelligence):** PhoenixAI itself makes decisions — which markets to search, which nodes to dispatch, how to interpret results. THIS is what's being built.
- **"Learning" = data accumulation, NOT LLM training:** LLMs don't learn between sessions. Phoenix's database IS the memory. More searches = richer data = better AI context. Three feedback loops: Route Learning (which market was chosen), Query Pattern Learning (what users ask about), Outcome Learning (did the booking succeed, what were actual savings).
- **Intelligence routes ARE agent tools:** Each `/api/intelligence/*` route simultaneously serves as user-facing dashboard, commercial API data product, and callable tool for the PhoenixAI agent. Triple-use by design.
- **All searches go through CitizenSERP nodes:** Whether it's a flight, hotel, product, or marketplace browse — every search is a CitizenSERP task that pays the node operator in RLUSD. New verticals are new task types, not new infrastructure.
- **CitizenSERP task types:** Expanding from generic search to typed tasks: `flight_search`, `product_search`, `hotel_search`, `marketplace_browse`, `general_search`. Each task type tells the node what to search and how to extract structured data. PhoenixAI decides which task type to dispatch and to which markets.
- **Self-upgrading:** PhoenixAI reads its own telemetry (query patterns, proxy usage by site, alert demand) and discovers new arbitrage opportunities autonomously. It doesn't need anyone to manually add "hotel search" — it sees query patterns and creates new search types.
- **The flywheel:** More searches → more node payments → more nodes join → broader geographic coverage → better data → PhoenixAI finds new patterns → creates new search types → more searches.
- **P2P helpers solve anti-bot:** Helpers are real people with real Google accounts on residential connections. Anti-bot detection is a non-issue. Helper availability is the real constraint, not bot detection.
- **DO NOT:** Build agent as separate from CitizenSERP. DO NOT build verticals with separate infrastructure. DO NOT train/fine-tune LLMs — accumulate data in Phoenix's DB instead. DO NOT frame PhoenixAI as redundant to BYOAI — they serve different purposes.

---

## CURRENT PROJECT STATE

### Files & Sizes
| File | Purpose |
|------|---------|
| server.py (~14300 lines) | Flask app, all routes, inline HTML templates, P2P dashboard, wallet onboarding, P2P orchestrator API, P2P booking flow, admin P2P management, node registry API, pipeline API, feedback API, dispute arbitration API |
| main.py (~2400 lines) | Core search, market config, currency rates |
| search.py (~1260 lines) | search_global(), flight matching, itineraries |
| google_flights_scraper.py (~1150 lines) | Playwright + proxy Google Flights scraper |
| amadeus_client.py (~500 lines) | Amadeus API client |
| airline_booker.py (~1090 lines) | Automated booking via Playwright |
| payments.py (~1020 lines) | Multi-payment gateway + P2P escrow functions |
| models.py (~780 lines) | SQLAlchemy models + P2P models (HelperProfile, UserWallet, UserCard, P2PTransaction, P2PEscrow) |
| airports.py (1787 lines) | 980 airports database |
| proxy_manager.py | Webshare.io proxy management |
| booking_fulfillment.py | Booking workflow orchestration (System 1) |
| browser_control.py (~680 lines) | **NEW** WebSocket remote browser control protocol (System 2 core) |
| p2p_orchestrator.py (~620 lines) | **UPDATED** P2P transaction workflow engine with real-time SSE event emissions at every state transition |
| email_service.py (~700 lines) | Email notifications + P2P email templates |
| xrpl_escrow.py (~600 lines) | XRPL escrow integration |
| templates/base_template.py | Phoenix UI template (aurora/cosmic theme) — nav updated with Earn/Helper/Wallet links |
| helper_client.py (~400 lines) | **NEW** Standalone P2P helper client app (CLI, Playwright, WebSocket) |
| config.py (~150 lines) | Enhanced environment-based config (Dev/Prod/Test) with PostgreSQL, Redis, connection pooling |
| gunicorn.conf.py (~60 lines) | **NEW** Production gunicorn config (gevent, 120s timeout, max_requests) |
| Dockerfile (~60 lines) | Enhanced multi-stage Docker build with Playwright, non-root user |
| docker-compose.yml (~115 lines) | Enhanced full stack: web + postgres + redis + websocket services |
| nginx.conf (~150 lines) | **NEW** Reverse proxy with SSL, WebSocket, security headers, rate limiting |
| requirements.txt (~45 lines) | Updated with all deps active (psycopg2, redis, websockets, gevent, pytest) |
| tests/test_p2p.py (~430 lines) | **NEW** Automated tests: P2P amounts, orchestrator, browser control, escrow |
| tests/test_integration.py (~370 lines) | **NEW** End-to-end integration tests: page loads, auth, wallet, helper, search, P2P, admin, edge cases |
| seed_db.py (~300 lines) | **NEW** Database seed script with demo data: admin, buyers, 12 helpers across markets, 25 deals, P2P transactions, escrows |
| monitoring.py (~220 lines) | **NEW** Sentry integration + Prometheus metrics (/metrics endpoint), request tracking, business metrics helpers |
| openapi.yaml (~700 lines) | **NEW** OpenAPI 3.1 spec for all API endpoints: search, deals, P2P, payments, escrow, system |
| logging_config.py (~180 lines) | **NEW** Structured JSON logging (prod) + colored dev output, request context, log rotation |
| .github/workflows/ci.yml | **NEW** GitHub Actions CI/CD: lint, test, Docker build, security scan |
| celery_app.py (~880 lines) | **UPDATED** Celery distributed task queue: 17 periodic tasks, 3 queues (payments, p2p, maintenance), beat schedule, SSE emission, airline intelligence tasks, CitizenSERP payout tasks, stale node cleanup, auto-dispute resolution, feedback pattern detection, triggered alert checking |
| event_stream.py (~350 lines) | **UPDATED** SSE real-time event bus: Redis pub/sub → SSE stream, per-user channels, heartbeat, 9 typed event emitters (P2P, payment, alert, opportunity, anomaly, node, dispute, deal, system) |
| cache.py (~250 lines) | **NEW** Redis caching layer: search results, exchange rates, airport/market data, deal listings, decorator |
| xrpl_monitor.py (~400 lines) | **NEW** XRPL ledger subscription monitor: WebSocket real-time escrow detection, DB+SSE updates |
| search_tracker.py (~250 lines) | **NEW** Search history & price tracking: record searches, price snapshots, trends, popular routes |
| helper_matching.py (~230 lines) | **NEW** Smart helper matching: 6-factor weighted scoring (reliability, rating, experience, availability, recency, speed) |
| dispute_resolution.py (~850 lines) | **UPDATED** Dispute resolution system: open/review/resolve workflow, message threads, SSE notifications, 6-factor auto-evaluation, auto-resolve, evidence system, analytics, deadlines |
| models.py (~960 lines) | Updated: +Dispute, DisputeMessage, SearchHistory, PriceHistory models |
| migrations/versions/a1b2c3d4e5f6 | **NEW** P2P tables migration (helper_profiles, user_wallets, user_cards, p2p_transactions, p2p_escrows) |
| migrations/versions/b2c3d4e5f6a7 | **NEW** Search history + price tracking migration |
| migrations/versions/c3d4e5f6a7b8 | **NEW** Dispute resolution tables migration |
| commercial.py (~500 lines) | **NEW** Commercial account management: tiered fees, API key lifecycle, usage metering, tier recalculation, referral system (code generation, attribution, helper node tracking) |
| commercial_auth.py (~920 lines) | **UPDATED** API key auth middleware + commercial API routes + referral routes + SERP API endpoints + yield dashboard (4 routes) + ad intel (3 routes) + marketplace (2 routes) + vertical price query (/api/v1/vertical/prices with per-vertical filters) |
| models.py (~1600 lines) | Updated: +CommercialAccount (referral_code, referred counters), User (referred_by_account_id, is_helper_node), CommercialAPIKey, CommercialTransaction, +AirlineClient, AirlineAPIKey, AirlineReport, AirlineAlert, AncillarySnapshot, CompetitorPricing, +NodeSession, NodePayoutEpoch, NodePayout |
| airline_intelligence.py (~550 lines) | **NEW** Airline intelligence manager: client onboarding, competitive pricing analysis, ancillary analysis, demand signals, alerts, report generation |
| airline_auth.py (~470 lines) | **NEW** Airline API key auth middleware + 23 routes: admin client CRUD, /api/v1/intel/* endpoints (pricing, ancillary, demand, alerts, reports), /api/v1/node/* CitizenSERP node routes, /api/v1/network/stats |
| migrations/versions/d4e5f6a7b8c9 | **NEW** Commercial account tables migration |
| migrations/versions/e5f6a7b8c9d0 | **NEW** Referral fields migration (users + commercial_accounts) |
| migrations/versions/f6a7b8c9d0e1 | **NEW** Airline intelligence tables migration (6 tables) |
| citizenserp_tasks.py (~1160 lines) | **UPDATED** CitizenSERP task type system: TaskType enum (16 types incl 6 Build #65 high-value types), TaskRegistry, TaskDispatcher with node_registry integration, feedback engine + vertical pipeline wiring + yield/ad-intel hooks on task completion, ExtractionRules (marketplace 8 rules), multi-market dispatch, MARKET_CONFIG (45 countries), zone-aware node finding |
| phoenix_agent.py (~1165 lines) | **UPDATED** PhoenixAI agent orchestrator: AgentTools (12 intelligence tools), MarketSelector (zone-level selection), PhoenixAgent (search, discover, analyze), intent parsing (10 verticals), universal_search (smart hybrid dispatcher), search_flights/search_cruise/search_ecommerce/search_digital, cruise+digital demand discovery signals |
| geographic_zones.py (~400 lines) | **NEW** Geographic zone registry: GeoZone dataclass, ~75 zones across 45 countries, zone/city/country lookups, market resolution, zone summary |
| migrations/versions/j0k1l2m3n4o5 | **NEW** Zone columns migration (zone_code on helper_profiles, ip_zone on node_sessions) |
| citizenserp_payouts.py (~420 lines) | **UPDATED** CitizenSERP payout manager: node uptime tracking, epoch payout calculation, XRPL RLUSD distribution, on-chain uptime attestation, network stats. Revenue pool includes airline SaaS + SERP API + ad intelligence revenue |
| serp_api.py (~905 lines) | **NEW** Phoenix Residential SERP API Service: SERPAPIManager class (validate, credits, quota, rate limit, sync/async execution, task dispatch, result formatting, usage tracking, monitoring), SERP_TIERS (6 tiers: free→partner), CREDIT_MULTIPLIERS (8 options), SUPPORTED_ENGINES (8 engines: Google/Bing/DuckDuckGo/Yahoo/Yandex/Baidu/Naver/Yahoo Japan), GOOGLE_DOMAINS (15 country domains) |
| ad_intelligence.py (~1144 lines) | **NEW** Ad Intelligence Pipeline: AdIntelligenceEngine class (ingest_task_result, normalize, classify_vertical, classify_ad_format, estimate_bid, query_ads, get_ad_trends, get_competitor_report, get_revenue_stats, get_monthly_revenue, get_pricing_info). AD_DATA_VALUES (6 formats), VERTICAL_KEYWORDS (8 verticals), AD_INTEL_TIERS (3 buyer tiers: $500/$2K/$10K/mo), BID_ESTIMATES (format+position CPC estimates with market multipliers) |
| node_yield_dashboard.py (~450 lines) | **UPDATED** Node Yield Dashboard: NodeYieldDashboard class (get_yield_summary, get_yield_history, get_category_breakdown, get_yield_optimization, record_extraction). DATA_CATEGORY_VALUES (11 categories incl browsing_data $0.0001), TASK_CATEGORY_MAP (21 task types → categories incl page_visit/ad_impression/price_observation/social_signal/search_query). Yield score composite: 30% uptime + 30% diversity + 20% quality + 20% volume |
| migrations/versions/n4o5p6q7r8s9 | **NEW** Build #65 tables: node_data_extractions (extraction tracking per task) + ad_intelligence_records (individual ad data points) |
| migrations/versions/o5p6q7r8s9t0 | **NEW** Build #66 tables: flight_price_records, hotel_price_records, cruise_price_records, product_price_records, marketplace_listing_records (5 vertical-specific structured price tables) |
| proxy_portal.py (~420 lines) | **UPDATED** Proxy Portal manager: app directory catalog (8 categories incl AI + search_engines, 80+ sites), proxy session lifecycle, market catalog, usage tracking. Search engines: Google, DuckDuckGo, Yandex, Baidu, Naver, Yahoo Japan, Brave, Ecosia |
| migrations/versions/g7h8i9j0k1l2 | **NEW** CitizenSERP payout tables migration (3 tables: node_sessions, node_payout_epochs, node_payouts) |
| migrations/versions/h8i9j0k1l2m3 | **NEW** Proxy portal tables migration (proxy_sessions) |
| node_registry.py (~580 lines) | **UPDATED** CitizenSERP node registration & discovery: NodeCapabilities/RegisteredNode dataclasses (+has_extension, +browsing_data task type), 3 in-memory indexes, register/unregister/heartbeat/discover/topology/assign_task/complete_task, zone-aware routing |
| intelligence_feedback.py (~544 lines) | **NEW** Intelligence feedback loop: FeedbackEngine with route_cache, anomaly detection (>15% below=drop, >20% above=spike), auto-create opportunities, check triggered alerts, price history recording |
| vertical_pipelines.py (~1860 lines) | **UPDATED** Multi-vertical processing pipelines: PriceNormalizer (currency+duty), FlightPipeline, HotelPipeline (fuzzy matching + location constraint), ProductPipeline (landed cost), CruisePipeline (per-person-per-night), ECommercePipeline (landed cost + 10-category detection), DigitalPipeline (region-lock standardized to 14 canonical codes, no duty), MarketplacePipeline (fair value + seller/condition/posted_date), PipelineManager router. Fee Engine: REWARDS_TIERS (25%→17%), calculate_arbitrage_fee(), calculate_private_market_fee() |
| ai_search.py (~870 lines) | **UPDATED** PhoenixAI multi-provider ensemble search engine + private market escrow builder + P2P deal links with single-link revocation + share_links integration. 9 providers, parallel query, BYOAI, deal contract builder, XRPL escrow, link gen/accept/email |
| models.py (~2250 lines) | Updated: +AISearchQuery, UserAIProvider, PrivateMarketDeal, +SERPAPIQuery, +SERPAPIUsageSummary, +NodeDataExtraction, +AdIntelligenceRecord, +FlightPriceRecord, +HotelPriceRecord, +CruisePriceRecord, +ProductPriceRecord, +MarketplaceListingRecord, +BrowsingEvent, +DataQualityFeedback. HelperProfile +helper_token/node_id/last_seen. CommercialAccount +serp_tier/credits |
| node_data_processor.py (~1000 lines) | **NEW** Server-side browser event processor: NodeDataProcessor class (ingest_batch, validate, dedupe LRU cache, quality score 0-100, domain classification 50+ domains → 8 verticals, commercial value calculation, route to yield_dashboard/ad_intelligence/feedback_engine). EVENT_COMMERCIAL_VALUES (5 types), DOMAIN_VERTICAL_MAP (50+ domains), rate limiting 1K/min 50K/day per node. Singleton: node_data_processor |
| node_service_api.py (~350 lines) | **NEW** Node service REST API: register_node_service_routes(app), require_helper_token decorator. 7 routes: POST /node/auth, /node/heartbeat, /node/data/ingest (max 500 events), GET /node/config, POST /node/session/start, /session/end, GET /node/earnings. NODE_CONFIG dict with extraction rules/intervals/limits |
| node_service.py (~500 lines) | **NEW** Local node service daemon (aiohttp): PhoenixNodeService class on localhost:19750. HTTP handlers: /status, /events, /config, /proxy.pac, /stop. Background loops: heartbeat (60s), batch upload (30s), config refresh (5min). Reconnection with exponential backoff (1s→60s). CLI with --token/--server/--port/--proxy-mode/--verbose |
| phoenix_extension/ | **NEW** Chrome Manifest V3 extension: manifest.json (activeTab, storage, alarms, webNavigation permissions), background.js (~250 lines, service worker: status pings, event buffering, flush to localhost:19750), content.js (~350 lines, DOM extractors: search queries, ads, prices, social signals, MutationObserver for SPA), popup.html/js (earnings + status display), options.html/js (server URL, token, port config) |
| migrations/versions/p6q7r8s9t0u1 | **NEW** Build #67 tables: browsing_events (6 indexes) + helper_profiles columns (helper_token, node_id, last_seen) |
| migrations/versions/q7r8s9t0u1v2 | **NEW** Build #69 table: data_quality_feedback (feedback_id, event_id FK→browsing_events, account_id, node_id, rating, comment, 5 indexes) |
| payout_disbursement.py (~350 lines) | **NEW** RLUSD disbursement worker: PayoutDisbursementWorker class (process_pending_payouts, _submit_payment via xrpl-py, verify_sent_payouts, _check_xrpl_confirmation, get_disbursement_stats, trigger_epoch_and_disburse). SIMULATED mode for dev. Singleton: disbursement_worker |
| build_extension.py (~210 lines) | **NEW** Chrome extension CRX packaging: validate_manifest(), build_zip(), generate_update_xml() for self-hosted auto-update, generate_build_info(), CLI entry point |
| data_quality_feedback.py (~350 lines) | **NEW** Data quality feedback engine: DataQualityFeedbackEngine class (submit_feedback, _recalculate_node_adjustments, get_node_adjustment, get_feedback_stats). Quality multiplier adjustments per-node based on buyer ratings. Singleton: quality_feedback_engine |
| browsing_tiers.py (~200 lines) | **NEW** Browsing data buyer tier system: BROWSING_TIERS (4 tiers: free/$0, starter/$199, professional/$999, enterprise/$4999). get_tier(), check_browsing_access(), check_browsing_quota(), record_browsing_usage(), reset_monthly_browsing(), get_browsing_tier_info(), get_all_tiers() |
| migrations/versions/r8s9t0u1v2w3 | **NEW** Build #70 migration: +browsing_tier, +browsing_events_used_this_month, +browsing_month_reset_date on commercial_accounts |
| phoenix_ai.py (~1400 lines) | **NEW** Phoenix AI engine: PhoenixAI class with tool-calling orchestration. 14 tool definitions (search_flights, search_hotels, search_products, analyze_route, get_route_intelligence, get_market_briefing, get_trending, get_price_history, browse_proxy, serp_search, get_node_status, get_earnings, get_deals, discover_opportunities). PHOENIX_AI_TIERS (4 tiers: ai_free/25 queries, ai_starter/$19/500, ai_professional/$49/2000, ai_unlimited/$99/unlimited). Tool router dispatches to existing modules. Rich content formatting (HTML tables, charts). Node operator 25% discount |
| phoenix_ai_api.py (~350 lines) | **NEW** Phoenix AI API routes: register_phoenix_ai_routes(app). 7 routes: POST /api/v1/ai/chat (SSE streaming), GET/POST/DELETE /api/v1/ai/conversations, GET /api/v1/ai/conversations/<id>, GET /api/v1/ai/tier, GET /api/v1/ai/pricing. Per-query credit system, tier quota enforcement, in-memory rate limiting |
| migrations/versions/s9t0u1v2w3x4 | **NEW** Build #72 migration: ai_conversations table (4 indexes), ai_messages table (2 indexes), +ai_tier/ai_queries_used_this_month/ai_month_reset_date on users |
| share_links.py (~330 lines) | **NEW** Multi-platform share link generator + smart contract templates. 12 platforms (WhatsApp, Telegram, Signal, Facebook, Messenger, X, Instagram, TikTok, Gmail, SMS, Email, Copy). 8 contract templates (goods_standard, goods_high_value, services_standard, services_milestone, digital_instant, vehicle_purchase, rental_deposit, custom) |
| migrations/versions/i9j0k1l2m3n4 | **NEW** AI search + private market deal tables migration (3 tables) |
| migrations/versions/k1l2m3n4o5p6 | **NEW** Deal link columns migration (6 new columns + seller_wallet nullable + unique index) |
| migrations/versions/l2m3n4o5p6q7 | **NEW** Seller onboarding attribution migration (onboarded_from_deal_id on users) |
| migrations/versions/m3n4o5p6q7r8 | **NEW** SERP API tables migration (serp_api_queries, serp_api_usage_summaries, +4 columns on commercial_accounts) |

### Markets: 45+ configured
- main.py MARKETS list: 45 entries
- google_flights_scraper.py MARKET_CONFIG: 45+ entries
- PRIORITY_MARKETS: 19 core markets for fast mode

### Airports: 980 in database

### .env Configuration Status
**Configured:** Flask, database, XRPL (testnet), manual proxy URLs (US/ES/UK/PL), booking settings, escrow
**Empty/Not configured:** Amadeus keys, Stripe keys, Coinbase keys, Webshare credentials, platform card, mail credentials

---

## WORK COMPLETED (Chronological)

### Session ~2026-01-27 (Early sessions)
- Built core platform: server.py, main.py, search.py
- Implemented proxy scraping with Playwright
- Built payment system (XRP, Stripe, Coinbase)
- Created booking pipeline
- Built UI templates (Phoenix aurora theme)

### Session ~2026-01-28
- Expanded airports from 618 → 980 (later referenced as 1,326 in some contexts)
- Ran domestic flight comparison tests
- Hit SerpAPI rate limits → **DECIDED to switch to Amadeus**
- Built amadeus_client.py
- Built search_amadeus_with_proxy_prices() in main.py
- Updated search_global() to prefer Amadeus over SerpAPI

### Session 2026-01-29 (Current)
- Identified 6 improvement tasks from codebase analysis:
  1. ✅ Fixed booking pipeline self-service flow (redirect, confirmation code submission)
  2. ✅ Passenger data form (already existed)
  3. ✅ Fixed automated booking errors (event loop conflict in book_flight_sync)
  4. ✅ Added /about page (route + template)
  5. ✅ Expanded markets from 24→45 (main.py) and 19→45+ (google_flights_scraper.py)
  6. ❌ Incorrectly added SerpAPI rate limiting — REVERTED
- Removed SerpAPI from all active search paths:
  - search_hybrid() now uses Amadeus for flight details
  - search_global() no longer falls back to SerpAPI
  - server.py flexible dates uses Amadeus fallback
  - test_domestic_comparison.py uses search_amadeus_with_proxy_prices()
- Changed SCRAPING_MODE default from "serpapi" to "hybrid"
- **Cleaned all SerpAPI dead code:**
  - Removed `API_KEY` (hardcoded SerpAPI key), `SERPAPI_URL`, `extract_serpapi_flight()`, `fetch_flights()` from main.py
  - Refactored `search_route()`, `search_flight_number()`, `run()` to use `fetch_flights_direct()` (proxy scraper)
  - Updated server.py imports and all callers to use `fetch_flights_direct()`
  - Removed `fetch_flights`/`extract_flights` unused imports from search.py
  - Removed SerpAPI comment from .env
  - `extract_flights()` kept — it's a generic parser for the shared data format

---

## KNOWN ISSUES & INCOMPLETE ITEMS

1. **Amadeus API keys not in .env** — System works with proxy-only but Amadeus provides richer flight data
2. ~~**SerpAPI dead code remains**~~ — **RESOLVED** — All SerpAPI code removed
3. **Platform payment card not configured** — Automated booking can't actually purchase tickets
4. **Stripe/Coinbase not configured** — Only XRP/RLUSD payments work
5. **Mail disabled** — MAIL_ENABLED=false in .env
6. ~~**SerpAPI key hardcoded**~~ — **RESOLVED** — Removed
7. **server.py line 6697** — SyntaxWarning for `\s` in inline JS (pre-existing, cosmetic)

---

## SESSION PROTOCOL

### On Session Start:
1. Read this file FIRST — before touching any code
2. Check git log for any changes since last session
3. Verify the architectural decisions above still hold
4. Ask the user what they want to work on
5. Do NOT re-introduce deprecated patterns (especially SerpAPI)

### After Every User Prompt:
1. Update "USER INTENT LOG" section below with the key point or decision from this exchange
2. Update "Last updated" timestamp at the top

### Before Context Compaction:
1. Write a compressed session archive to `session_archives/session_YYYYMMDD_NN.md`
2. Include: all decisions made, all files changed, all user corrections, current state
3. Update this file with final state

### On Session End:
1. Update WORK COMPLETED section with what was done
2. Update KNOWN ISSUES if any new ones were found
3. Update ARCHITECTURAL DECISIONS if any new ones were made

---

## USER INTENT LOG (Chronological per session)

### Session 2026-01-29
1. **User asked to build 6 improvement tasks** — all 6 identified from codebase analysis
2. **User corrected SerpAPI usage** — "we fixed this issue and are using amadeus now" — SerpAPI was already decided as deprecated, Claude incorrectly added rate limiting instead of removing it
3. **User emphasized context continuity** — Claude must not undo prior decisions when sessions restart from compacted summaries. This is the #1 risk to the project.
4. **User requested persistent session tracking** — Claude must update this file after every prompt, archive before compaction, and never rely solely on compacted summaries for decision context
5. **User asked where to focus next** — Claude provided prioritized roadmap: (1) Amadeus keys, (2) clean SerpAPI dead code, (3) end-to-end test, (4) Stripe, (5) email, (6) error handling, (7) more proxies. Waiting for user direction.
6. **User approved roadmap ("lets do it")** — Completed SerpAPI dead code cleanup: removed API_KEY, SERPAPI_URL, fetch_flights(), extract_serpapi_flight() from main.py; refactored search_route/search_flight_number/run to use fetch_flights_direct (proxy scraper); cleaned server.py, search.py, .env. All files pass syntax check.
7. **User asked how app works without Amadeus keys** — Clarified: proxy scraper (Playwright + residential proxies) is the core engine that provides real pricing. Amadeus is optional enhancement for richer flight metadata. App functions fully on proxy-only path.
8. **User requested end-to-end test** — Server started on port 5001, homepage (200), about page (200), API search POST tested. JFK→LAX returned 19 flights, 60 price comparisons across US/ES/UK. Spain cheapest at $208 vs US $240 (~13% savings). App confirmed working.
9. **User asked what search API does** — Clarified: it's Playwright headless browsers loading Google Flights through residential proxies in multiple countries, extracting prices from the DOM, converting to USD, and comparing. No Google API exists — this is browser automation.
10. **User confirmed architecture matches their vision** — Proxies = core (pricing + arbitrage detection), Amadeus = enhancement (flight metadata like airline codes, aircraft, flight numbers), Payment gateways = separate layer (XRP, Stripe, Coinbase). Pricing always comes from proxies since Amadeus returns single global price.
11. **User asked about competitive moat and market impact** — Discussed: technical concept is replicable, defensibility comes from execution (proxy ops, matching accuracy, data accumulation, first-mover). Key risks: Google anti-scraping, airlines canceling proxy-booked tickets. Unlikely to force systemic price honesty at scale — serves niche of price-conscious travelers.
12. **User proposed peer-to-peer purchasing network** — Concept: incentivize real users in foreign markets to make purchases on behalf of US customers using their legitimate Google accounts, earning a cut of Phoenix revenue. Solves bot detection problem entirely. Claude assessed: strong concept for anti-detection, creates network effects moat, but raises legal concerns (airline ToS, ticket purchaser vs passenger mismatch), fraud/trust risk (needs escrow both sides), tax complexity across jurisdictions, and cold-start supply problem. Suggested manual pilot first. User also sees political angle — exposing geopricing publicly.
13. **User clarified P2P payment rails** — Use XRPL (XRP/RLUSD) + Coinbase Commerce for trustless cross-border payments. Smart contract escrow handles release on booking confirmation. No fiat wire transfers needed.
14. **User clarified P2P escrow model** — Two options discussed: (A) lock buyer funds, release to helper pre-purchase (has counterparty risk), (B) Phoenix provides seed liquidity while buyer funds locked (eliminates risk but requires capital). User initially favored Model B.
15. **User clarified Phoenix controls the browser** — Helper doesn't manually navigate. Phoenix takes remote control of helper's browser session via client app. Same Playwright automation as System 1, just executing on helper's device instead of through a proxy. Helper is a trusted endpoint, not an operator.
16. **User proposed token system as reserve option** — Phoenix token backed 1:1 by RLUSD stablecoins. Only deploy if needed. Not for initial build.
17. **User solved the seed capital problem** — Buyer converts USD → RLUSD upfront, locks in escrow. Helper sees on-chain escrow, trusts it, fronts purchase with their credit card. Escrow releases RLUSD to helper on confirmation. No Phoenix treasury needed. RLUSD circulates in ecosystem — helpers spend earned RLUSD on their own flights. Closed-loop economy.
18. **User confirmed on-chain escrow verification** — Both buyer and helper can inspect locked escrow directly on XRPL ledger. This is the trust foundation — neither party relies on Phoenix's word, they verify on-chain.
19. **User requested wallet onboarding** — Users need to connect XRPL wallets and payment cards directly to their profile. Wallet for escrow (buyers deposit RLUSD, helpers receive RLUSD). Cards for helpers to front purchases and for System 1 direct booking. Coinbase Commerce as on/off ramp for RLUSD.
20. **User requested crypto exchange on-ramp** — Users need access to exchanges to acquire crypto/RLUSD for their Phoenix wallet. Support Coinbase (primary) plus major global exchanges (Binance, Kraken, Uphold, Bitstamp, Crypto.com). Embedded buy widgets (MoonPay/Transak) recommended for seamless in-app purchases without leaving Phoenix.
21. **User requested /earn page for P2P helper recruitment** — Build a pitch page advertising the helper income system. Key messaging: earn XRP passively by granting Google account access, Phoenix rents access to established accounts instead of paying data farms, helpers seed the network and earn from every purchase through their region, "take back your data" angle — users benefit from their data instead of institutions. Built /earn route + EARN_CONTENT in server.py, added "Earn" link to nav bar.
22. **User articulated broader Phoenix mission** — Phoenix as a "citizen SerpAPI" — an honest, people-powered data network. Mission: expose that Google/airlines gatekeep geopricing data to exploit consumers. Build a decentralized residential network of real users that corporations cannot stop. Passive earning model: users just allow Phoenix access to run in background, Phoenix handles all automation. Vision: Phoenix becomes a provably honest API that demonstrates big tech/travel corps manipulate data for market advantage. Supply-side moat: network of opted-in real users is not replicable like proxy farms. Key distinction noted: Google doesn't fabricate prices — the manipulation is in the opacity (no disclosure of cross-border price differences).
23. **User approved building P2P infrastructure ("lets do it")** — Built the full P2P backend:
    - **models.py**: Added 5 new models — HelperProfile, UserWallet, UserCard, P2PTransaction, P2PEscrow
    - **payments.py**: Added P2P escrow functions — calculate_p2p_amounts(), create_p2p_escrow(), verify_p2p_escrow_on_chain(), release_p2p_escrow(), P2PEscrowStatus enum, P2P_FEE_CONFIG
    - **server.py**: Added /wallet page (add/remove wallets + cards, exchange on-ramp links), /helper dashboard (activate profile, toggle active, view transactions/stats), /helper/activate + /helper/toggle routes, /api/p2p/match endpoint, /api/p2p/escrow/verify endpoint. Added Helper + Wallet links to authenticated nav. Updated /earn page with "Citizen SerpAPI" branding, "The Honest API" mission section, "Citizen Data Network" section.
    - Updated models import in server.py to include all new models
    - All files pass syntax check
24. **User requested building all roadmap items** — Built everything that doesn't require purchasing external services:
    - **browser_control.py (NEW ~680 lines)**: WebSocket remote browser control protocol for System 2. Includes BrowserControlServer (session management, auth, command tracking), HelperBrowserClient (Playwright executor on helper device), FlightBookingAutomation (pre-built command sequences), MessageProtocol (JSON WebSocket messages), CommandType enum (navigate, click, type, extract, screenshot, etc.), async WebSocket server via `websockets` package.
    - **p2p_orchestrator.py (NEW ~580 lines)**: P2P transaction workflow engine. 8-step lifecycle: initiate → match → escrow → verify → browser session → purchase → confirm → release. Includes P2POrchestrator class with run_full_workflow() entry point, failure/cancellation handling, notification triggers, query methods for buyer/helper transactions.
    - **email_service.py (updated +190 lines)**: Added 6 P2P email templates — send_p2p_escrow_locked(), send_p2p_helper_matched(), send_p2p_booking_confirmed(), send_p2p_helper_payment(), send_p2p_transaction_failed(), send_p2p_escrow_refunded(). All use Phoenix branded HTML layout.
    - **server.py (updated +170 lines)**: Added 9 new P2P orchestrator API routes — /api/p2p/book (POST, full workflow), /api/p2p/transaction/<id> (GET status), /api/p2p/transaction/<id>/verify (POST helper verify), /api/p2p/transaction/<id>/session (POST create browser session), /api/p2p/transaction/<id>/purchase (POST start purchase), /api/p2p/transaction/<id>/confirm (POST confirm + release), /api/p2p/transaction/<id>/cancel (POST), /api/p2p/my-transactions (GET), /api/p2p/browser-session/<id> (GET). Enhanced /health endpoint with service status for XRPL, Stripe, proxy scraper, Amadeus, browser control, email.
    - **Stripe integration**: Already fully built (payments.py has checkout sessions, verification, webhooks; server.py has routes). Just needs API keys from dashboard.stripe.com.
    - All files pass syntax check (only pre-existing \s warning in server.py inline JS)
25. **User requested building all 6 roadmap items ("lets dive into all and build")** — Built everything:
    - **Admin dashboard enhanced**: Added P2P Network and Helper Approvals admin pages (/admin/p2p, /admin/helpers). P2P stats (active helpers, pending approvals, transaction count, RLUSD volume) added to main admin dashboard. Helper approval/reject/suspend actions. Full P2P transaction table with escrow monitoring. Top markets and top helpers panels.
    - **Frontend P2P booking flow**: Added "Book via P2P Network" button to search results (appears when savings > $5). Created /p2p/book page with flight summary, price comparison, escrow breakdown, passenger form. Created /p2p/status/<id> page with transaction timeline (animated dots, auto-refresh). Created /p2p/my-bookings listing page. /p2p/book/confirm POST handler initiates orchestrator workflow. /p2p/cancel/<id> POST handler.
    - **helper_client.py (NEW ~400 lines)**: Standalone CLI app for helpers. argparse (--server, --token, --headless, --verbose). Playwright Chromium execution. Domain allowlist (30+ airline/travel domains). WebSocket protocol compatible with browser_control.py. ASCII banner, status printer, session summary. Dependency checker, auto-installs Playwright browsers. SIGINT/SIGTERM signal handling.
    - **tests/test_p2p.py (NEW ~430 lines)**: 5 test classes, ~60 tests. TestP2PAmounts (9 tests), TestP2POrchestrator (8 tests), TestBrowserControl (29 tests), TestEscrowCalculations (9 tests), TestWorkflowStatus (3 tests). Uses unittest.mock for database operations.
    - **config.py enhanced**: Added PostgreSQL config (ProductionConfig), connection pooling (pool_size=10, max_overflow=20), Redis URL, Stripe keys, RotatingFileHandler for production logging, TestingConfig with in-memory SQLite.
    - **Deployment config**:
      - Dockerfile: Multi-stage build (builder + production), Playwright system deps, non-root phoenix user, gunicorn.conf.py CMD
      - docker-compose.yml: 4 services (web, postgres, redis, websocket), health checks, named volumes, phoenix-network
      - nginx.conf: HTTPS with SSL, WebSocket proxy (/ws), rate limiting zones (10r/s general, 5r/s API), security headers (HSTS, CSP, X-Frame-Options), gzip, sensitive file blocking
      - gunicorn.conf.py: gevent workers, 120s timeout, max_requests=1000 with jitter, capture_output
    - **requirements.txt updated**: All optional deps now active (psycopg2-binary, redis, websockets, gevent, pytest, pytest-cov, alembic)
    - **base_template.py nav updated**: Added Earn, Helper, Wallet links to main navigation
    - All files pass syntax check
26. **User requested building all 9 remaining items ("lets tackle them all one at a time")** — Built everything:
    - **tests/test_integration.py (NEW ~370 lines)**: End-to-end Flask test client tests. 10 test classes, ~50 tests covering page loads, auth, wallet, helper, search API, P2P API, admin, P2P booking flow, payments, edge cases.
    - **seed_db.py (NEW ~300 lines)**: Database seed script with admin, demo buyer, 8 users, 12 helpers across 12 markets, 25 deals, 6 bookings, 15 P2P transactions, 5 price alerts. Supports --reset and --count flags.
    - **monitoring.py (NEW ~220 lines)**: Sentry integration + lightweight Prometheus metrics collector + /metrics endpoint + request tracking middleware + business metrics helpers.
    - **openapi.yaml (NEW ~700 lines)**: Full OpenAPI 3.1 spec for all 35+ API endpoints.
    - **Mobile responsiveness**: Hamburger menu for mobile nav, tablet breakpoint, responsive tables/stats/forms/grids.
    - **CI/CD pipeline (.github/workflows/ci.yml)**: 4 jobs — lint, test, Docker build, security scan.
    - **Helper earnings dashboard polished**: 14-day earnings bar chart, success rate bar, availability settings, pending approval notice, improved transaction list.
    - **Per-endpoint rate limiting tuned**: register (10/hr), login (15/hr), payment/verify (20/hr), escrow/create (10/hr), p2p/book (10/hr). Redis storage in prod.
    - **logging_config.py (NEW ~180 lines)**: Structured JSON logging for prod, colored dev output, request context enrichment, log rotation.
    - All files pass syntax check
27. **User asked "what should we attack next architecturally"** — Claude audited codebase and identified 8 architectural gaps, ranked by execution priority.
28. **User approved all 8 ("lets tackle them all in order")** — Built all 8 items:
    - **celery_app.py (NEW ~300 lines)**: Celery + Redis distributed task queue replacing threading-based tasks.py. 6 periodic tasks on beat schedule: verify_payments (30s), expire_deals (5m), check_price_alerts (15m), monitor_p2p_escrows (60s), match_pending_p2p (30s), cleanup_sessions (hourly). 3 routing queues: payments, p2p, maintenance. emit_event task bridges Celery → Redis pub/sub for SSE.
    - **event_stream.py (NEW ~210 lines)**: SSE real-time event bus. SSEManager with Redis pub/sub, /events/stream (per-user + admin channels), /events/test. Heartbeat every 15s.
    - **cache.py (NEW ~250 lines)**: Redis caching layer. Typed helpers for search results (4h/1h TTL), exchange rates (2h), XRP price (10m), airport data (24h), deals (15m). @cached decorator. Graceful fallback.
    - **Alembic migration a1b2c3d4e5f6**: P2P tables — helper_profiles, user_wallets, user_cards, p2p_transactions, p2p_escrows.
    - **xrpl_monitor.py (NEW ~400 lines)**: XRPL WebSocket ledger subscription. Detects EscrowCreate/Finish/Cancel/Payment in real-time. Updates DB + SSE. Exponential backoff reconnect.
    - **search_tracker.py (NEW ~250 lines)**: Search history + price tracking. record_search(), price history/trends/popular routes. Migration b2c3d4e5f6a7.
    - **dispute_resolution.py (NEW ~270 lines)**: Full dispute workflow — open/review/resolve with message threads, SSE notifications. Migration c3d4e5f6a7b8.
    - **helper_matching.py (NEW ~230 lines)**: 6-factor weighted scoring replacing basic sort. Factors: reliability (0.30), rating (0.20), experience (0.15), availability (0.15), recency (0.10), speed (0.10). High-value transaction weighting. Integrated into celery_app.py match_pending_p2p.
    - **models.py (+180 lines)**: Added Dispute, DisputeMessage, SearchHistory, PriceHistory models.
29. **User proposed commercial onboarding for travel agencies** — Discussed fee structure, decided: percentage of savings only (no minimum fee), performance-based tier ladder with use-it-or-lose-it mechanic, P2P access for all tiers, no data exclusivity.
30. **Built commercial account system**:
    - **commercial.py (NEW ~350 lines)**: CommercialManager class — account CRUD, API key generation/verification (bcrypt hashed, prefix-indexed), fee calculation (savings × tier percent, zero if no savings), transaction recording, tier recalculation engine (upgrade immediate, downgrade after 2 grace periods). Tier config: starter 20%, professional 15% @50 tickets/30d, enterprise 10% @500, partner 7% @5000.
    - **commercial_auth.py (NEW ~250 lines)**: API key auth middleware via Authorization: Bearer or X-API-Key headers. require_api_key(scope) decorator with scope enforcement. 10 routes: account CRUD (admin), API key management (owner), /api/v1/search (commercial search endpoint), /api/v1/account/stats, /api/v1/account/tier.
    - **models.py (+160 lines)**: CommercialAccount (tier, fee_percent, volume tracking, P2P enabled), CommercialAPIKey (bcrypt hash, scopes, expiry), CommercialTransaction (retail/booked/savings/fee per completed booking).
    - **celery_app.py updated**: Added recalculate_commercial_tiers daily beat task.
    - **Migration d4e5f6a7b8c9**: commercial_accounts, commercial_api_keys, commercial_transactions tables.
31. **Built referral attribution system for agency flywheel**:
    - **models.py updated**: CommercialAccount gained referral_code (unique, indexed), total_referred_users, total_referred_helpers. User model gained referred_by_account_id (FK), referral_code_used, is_helper_node. Fixed stale docstring mentioning fee_min_usd.
    - **commercial.py (+150 lines)**: Added referral methods to CommercialManager — _sanitize_referral_code(), _generate_referral_code() (auto from company name), get_account_by_referral_code(), attribute_referral() (called during signup), activate_helper_node() (increments referring account's helper count), get_referral_stats() (referred users, active helpers, active bookers), update_referral_code(). create_account() now accepts/auto-generates referral code.
    - **commercial_auth.py (+80 lines)**: Added 5 referral routes — /join/<code> (agency portal redirect, stores code in session), /api/referral/validate/<code> (public validation), /api/commercial/accounts/<id>/referrals (GET stats), /api/commercial/accounts/<id>/referral-code (PUT update), /api/v1/account/referrals (API key authenticated stats).
    - **Migration e5f6a7b8c9d0**: Adds referral columns to users + commercial_accounts.
32. **Captured core mission and market position as Architectural Decision #8**:
    - Phoenix is not choosing a side — it is choosing everyone
    - Neutral intermediary strengthening consumer-airline relationship through pricing transparency
    - Three-sided market: consumers (25% of savings), agencies (7-20%), airlines ($100K-500K/mo SaaS)
    - Airline Intelligence SaaS product (data-only, NOT booking) — competitive pricing + ancillary intelligence
    - MAD strategic position: Phoenix earns whether airlines subscribe or don't
    - "Citizen API" — people-powered honest market data layer
    - Helper payout model: 10% of savings (15-20% bootstrap), passive nodes $0.10-0.25/hr
    - Revenue model anchored on IATA 2026 data: ~$310M per 1% capture, $1.55B at 5%
33. **Built Airline Intelligence SaaS infrastructure**:
    - **models.py (+350 lines)**: Added 6 new models — AirlineClient (IATA code, subscription tiers basic/pro/enterprise, monthly fee, contract dates, route/market/competitor subscriptions), AirlineAPIKey (air_ prefix, bcrypt hashed, scoped), AirlineReport (async generation, JSON report data, status tracking), AirlineAlert (5 alert types: price_drop/spike/demand_surge/new_route/ancillary_change, thresholds, webhook/SSE/email notification), AncillarySnapshot (bags/seats/upgrades per route/market/date/airline), CompetitorPricing (materialized daily aggregate with market rank and price vs avg %).
    - **airline_intelligence.py (NEW ~550 lines)**: AirlineIntelligenceManager class — create_client(), verify_api_key() (air_ prefix), get_competitor_analysis() (airline-by-airline pricing with ranks), get_route_pricing_history() (daily trends), get_ancillary_analysis() (bags/seats by airline), get_demand_analysis() (search volume from SearchHistory), create_alert()/check_alerts()/_trigger_alert() (price/demand alerts with SSE), generate_pricing_report()/_build_report_sync()/get_report()/list_reports(), get_route_summary() (multi-market view). Tier config: basic $100K/mo, pro $250K/mo, enterprise $500K/mo.
    - **airline_auth.py (NEW ~430 lines)**: API key auth middleware (require_airline_api_key decorator), 20 routes: admin client CRUD (create/list/detail/suspend/reactivate, API key management), intelligence API (pricing competitive analysis, price history, route summary, ancillary analysis, demand signals, competitor routes), alerts (create/list/delete), reports (generate/list/latest/get-by-id), account info.
    - **celery_app.py (+200 lines)**: 5 new tasks — check_airline_alerts (5m), snapshot_ancillary_data (hourly), generate_daily_airline_reports (6 AM for enterprise/pro clients), generate_airline_pricing_report (async), calculate_competitor_pricing (4 AM daily materialized view).
    - **Migration f6a7b8c9d0e1**: 6 new tables — airline_clients, airline_api_keys, airline_reports, airline_alerts, ancillary_snapshots, competitor_pricing. All with composite indexes.
    - **server.py**: Registered commercial_auth and airline_auth routes via register_*_routes(app).
    - All files pass syntax check.
34. **Added CitizenSERP micropayment model to Architectural Decision #8**:
    - Two-stream node income: Variable (booking savings %) + Fixed (CitizenSERP micropayments from airline SaaS revenue)
    - On-chain uptime verification via XRPL
    - Flywheel economics: more airline subscribers → more CitizenSERP pool → higher node payouts → more nodes → better data → more subscribers
    - Hedge against savings compression at market maturity
35. **Built CitizenSERP node payout infrastructure**:
    - **models.py (+150 lines)**: Added 3 new models — NodeSession (session_id, user_id, start/end time, duration, wallet_address, ip_country, xrpl_attestation_tx, status active/closed/stale), NodePayoutEpoch (epoch_id, period, revenue pool, payout %, rate per hour, nodes paid, status calculating/calculated/distributing/completed/failed), NodePayout (epoch_id FK, user_id FK, wallet_address, uptime_hours, payout_amount_rlusd, tx_hash, status pending/sent/confirmed/failed)
    - **citizenserp_payouts.py (NEW ~400 lines)**: CitizenSERPPayoutManager class — record_node_online/offline, close_stale_sessions, refresh_heartbeats, get_node_uptime (hours/sessions/earnings), calculate_epoch_payouts (prorates daily airline revenue, divides by total network hours), distribute_payouts (XRPL RLUSD Payment transactions with memos), submit_uptime_attestation (0-value self-payment memo tx for on-chain proof), get_payout_history, get_network_stats
    - **celery_app.py (+80 lines)**: 3 new tasks — record_node_heartbeats (5m, verify online nodes + attestations), calculate_citizenserp_payouts (midnight UTC, epoch calculation), distribute_citizenserp_payouts (1 AM UTC, XRPL distribution with max_retries=3)
    - **airline_auth.py (+45 lines)**: 3 new routes — GET /api/v1/node/stats (session auth, uptime+earnings), GET /api/v1/node/payouts (payout history), GET /api/v1/network/stats (public, no auth)
    - **Migration g7h8i9j0k1l2**: 3 new tables — node_sessions, node_payout_epochs, node_payouts with composite indexes
    - All files pass syntax check
36. **Built 4 architectural hardening items** (2 of 6 identified were already implemented):
    - **server.py: Infrastructure wiring**: init_logging(app) for structured logging, init_monitoring(app) for Sentry+Prometheus, register_sse_routes(app) for SSE endpoints, register_monitor_routes(app) for XRPL monitor status, LedgerMonitor.start() for real-time escrow detection — all now initialized in __main__ block
    - **server.py: Celery task admin dashboard**: 3 new admin endpoints — /admin/tasks (schedule + worker status), /admin/tasks/trigger/<task_name> (manual trigger with allowlist), /admin/tasks/result/<task_id> (check result). JSON API for visibility into 14+ periodic tasks
    - **server.py: Security hardening**: Security headers via @after_request (X-Frame-Options DENY, X-Content-Type-Options nosniff, X-XSS-Protection, Referrer-Policy, Permissions-Policy, HSTS on HTTPS). Rate limit on /api/p2p/match (30/hr) + login_required. Audit logger (phoenix.audit) with audit_log() helper for financial events (p2p_book, payment_verified, data_export, account_deletion)
    - **server.py: GDPR compliance**: /api/account/export (Article 20 data portability — profile, payments, wallets, P2P transactions, price alerts, helper profile as JSON, 3/day limit). /api/account/delete (Article 17 right to erasure — blocks if active P2P, anonymizes PII, deactivates helper, deletes wallets/alerts, closes node sessions, logs out, 1/day limit)
    - **Already implemented (not stubs)**: verify_p2p_escrow_on_chain() already queries XRPL via Tx request (lines 954-998 in payments.py), Coinbase webhook already has HMAC-SHA256 verification (lines 508-514 in payments.py)
    - All files pass syntax check
37. **Node economics analysis at 1M nodes** — At 1M nodes with airline-only CitizenSERP: passive nodes earn ~$2.80/month (10% of $28M/mo airline SaaS ÷ 1M). Active P2P helpers: $50-143/month. The $12-20/month passive figure from AD#8 was modeled at ~100-200K nodes. Network is self-correcting (nodes leave if payouts drop, remaining earn more).
38. **User declared multi-vertical expansion vision** — Phoenix is a universal arbitrage search engine, not a flight app. Flights are vertical #1. Expansion: hotels → cruises → e-commerce (fashion, electronics) → software/digital → universal search. User wants anyone to type any product/service and see arbitrage opportunities across markets. CitizenSERP is the infrastructure layer inside Phoenix, not a separate product. Existing flight code stays as-is — new verticals are additive. At 3-4 verticals, passive node earnings reach ~$25-30/month at 1M nodes due to multiple data subscriber pools sharing the same node network.
39. **User articulated cross-market disintermediation vision** — Phoenix eliminates middlemen (importers, brokers) by providing proxy gateways to foreign marketplaces. Example: JDM import car from Japan — US buyer currently can only find importers at 2x markup. Phoenix lets them browse Facebook Marketplace Japan directly and find the seller at half the price. Communication via existing platform messaging (Facebook Messenger, Telegram, WhatsApp) — no custom messaging system needed. Translation layer is a future enhancement. Hard goods have shipping/customs friction but the transparency alone births new markets by connecting people directly.
40. **User clarified proxy gateway model** — User stays logged into their OWN Facebook account. Phoenix piggybacks the proxy location so Facebook's geo-restrictions on Marketplace are bypassed. User sees foreign listings through their own authenticated session. They contact sellers directly via Messenger. No intermediary platform needed — Phoenix just provides geographic access. This is the simplest, most powerful model: leverage existing marketplace + messaging infrastructure, just remove the geographic wall.
41. **User requested universal proxy portal ("is there a universal way to allow any app or site to plug in")** — Wants on-ramps to social media, messaging apps, marketplaces all accessible through Phoenix's proxy infrastructure. The universal model is the proxy itself — no per-app integration needed. Built a Proxy Portal with curated app directory + proxy session management.
42. **Built Proxy Portal — Universal Market Access Gateway**:
    - **proxy_portal.py (NEW ~350 lines)**: ProxyPortalManager class — app directory catalog (6 categories: marketplaces, automotive, shopping, real estate, social commerce, services; 50+ curated sites with region tags), proxy session creation with sticky residential IPs via Webshare, session lifecycle management (create/end/expire/cleanup), market catalog (46 countries with metadata), usage tracking and stats, rate limiting (2 concurrent, 4hr max, 10/day)
    - **models.py (+50 lines)**: ProxySession model — user_id, country_code, target_site, proxy credentials (host/port/username/password/protocol), status (active/expired/ended), expiry timestamps. Composite index on (user_id, status).
    - **server.py (+300 lines)**: Portal UI page (/portal, @login_required) with PORTAL_CONTENT inline HTML — hero section, interactive market grid (46 countries with flags), category-tabbed app directory, active session panel with credential display, setup guide (Chrome/Firefox/macOS proxy config), earn CTA. 5 API routes: POST /api/portal/session (create, 10/day limit), GET /api/portal/sessions (list active), DELETE /api/portal/session/<id> (end), GET /api/portal/markets (catalog), GET /api/portal/apps (directory with market/category filters).
    - **base_template.py**: Added "Portal" nav link for authenticated users
    - **Migration h8i9j0k1l2m3**: proxy_sessions table with user_id FK and composite index
    - All files pass syntax check
43. **User requested onboarding all major LLMs into CitizenSERP** — iteratively refined across 4 messages: started as "onboard LLMs through proxies", evolved to "run on user server with proxy data", then "build AI using all frameworks in ensemble", finally settled on: "Keep proxy pure by default. Onboard major cloud AI models (Grok, DeepSeek, Claude, ChatGPT, Gemini, Mistral). Build ensemble search engine combining all providers' strengths. Allow users to bring their own AI. Lock everything through Phoenix payment system (RLUSD/XRP)."
44. **User articulated private market escrow model** — Phoenix can't stop users from exchanging wallet addresses directly through Messenger/WhatsApp. But Phoenix offers voluntary trustless XRPL escrow with real-time smart contracts. The fee isn't a toll — it's the price of trustlessness. Users who skip it gamble on counterparty risk. Two transaction models: Retail commerce (vendor checkout, savings model) vs Private market (no vendor, escrow fee model 1.5-3% tiered, $500 cap).
45. **Built Phoenix AI Search Engine + Private Market Escrow**:
    - **ai_search.py (NEW ~650 lines)**: PhoenixAI class — 9 provider registry (Anthropic, OpenAI, xAI/Grok, DeepSeek, Google Gemini, Mistral, Cohere, HuggingFace, Ollama), ThreadPoolExecutor parallel queries, response ranking (completeness/relevance/specificity/confidence/speed/agreement), OpenAI-compatible shortcut (1 function serves 4 providers), API key encryption (Fernet), credit system (0.001 RLUSD/query, 10 free/day), BYOAI (user-provided API keys bypass credits), market context builder, 4 system prompts (search/analysis/comparison/deal assessment). Private market: build_deal_contract() with AI fair value assessment, tiered escrow fees, XRPL EscrowCreate with CryptoCondition, fund/confirm/dispute lifecycle.
    - **models.py (+130 lines)**: 3 new models — AISearchQuery (query text, providers queried JSON, best response, all responses JSON, tokens, credits used), UserAIProvider (encrypted API keys, custom model/endpoint, unique per user+provider), PrivateMarketDeal (buyer/seller, item, price, XRPL escrow tx hash/sequence/condition/fulfillment, AI fair value estimate, risk score 1-10, status lifecycle draft→escrow_funded→delivered→completed with dispute/cancel/expire paths)
    - **server.py (+400 lines)**: AI Search page (/ai-search, @login_required) with AI_SEARCH_CONTENT inline HTML — search bar, market selector, provider badges, credit display, results area (best + all responses), query history, private deal form (item/price/seller wallet/deal type/deadline), contract terms display, deal list with confirm/dispute actions, add provider modal. 12 API routes: 6 AI search (POST search, GET/POST/DELETE providers, GET history, GET credits) + 6 private deal (POST create, POST fund, POST confirm-delivery, POST dispute, GET list, GET detail). Rate limited 30/day on search.
    - **base_template.py**: Added "AI Search" nav link for authenticated users
    - **Migration i9j0k1l2m3n4**: 3 new tables — ai_search_queries, user_ai_providers, private_market_deals with composite indexes
    - All files pass syntax check
46. **User clarified BYOAI model** — "Users with their own AI subscription can login to their AI with their Google credentials and login to onboard the use of their AI service through the proxy portal so their AI can access the data on that side of the proxy while remaining wherever the user is who onboarded." This means BYOAI = proxy portal, NOT API keys. The primary path: user goes to proxy portal, selects ChatGPT/Claude/etc. from AI category, sets proxy to target country, logs in with their own credentials (Google SSO, etc.). Their AI sees data from that geographic market. No API key needed. The AI category in the portal app directory (21 LLM sites) IS the BYOAI onboarding mechanism. API key contribution to Phoenix ensemble is an advanced secondary option.
47. **User declared data-first principle** — "Everything must run through Phoenix ultimately. I want Phoenix to take in data at any point possible to learn and procure useable market data to sell." Phoenix is the data layer even when providing proxy access. Every session, query, and transaction teaches Phoenix about market demand, pricing, and consumer behavior. This accumulated intelligence is the product enterprises pay for via the commercial API.
48. **Integration wiring sprint — connected all disconnected modules**:
    - **search_tracker wired** — `search_tracker.record_search()` now called in `/api/search` (server.py) and `/api/v1/search` (commercial_auth.py) after every search. Non-blocking try/except.
    - **Savings calculation added** — Commercial API `/api/v1/search` now calculates gross_savings, fee_usd, net_savings, savings_percent for each deal based on account fee tier.
    - **Celery worker + beat in docker-compose** — Added celery-worker (queues: payments, p2p, maintenance, concurrency 4) and celery-beat (periodic scheduler) services with Redis broker on db/2, result backend on db/3.
    - **Node session lifecycle wired** — `/helper/toggle` now calls `citizenserp_manager.record_node_online()` on activation and `record_node_offline()` on deactivation.
    - **Admin navigation bar** — All 7 admin HTML pages (dashboard, payments, users, deals, wallet, proxies, P2P, helpers) now have a shared ADMIN_NAV bar with links to all admin sections. Replaces the old "← Back to Dashboard" links.
    - **Private market escrow fully wired to XRPL**:
      - `confirm_delivery()` in ai_search.py now submits actual EscrowFinish with fulfillment to XRPL (was DB-only before)
      - `xrpl_monitor.py` now detects PrivateMarketDeal escrows in all three handlers: `_process_escrow_create` (confirms deal on-chain), `_process_escrow_finish` (completes deal), `_process_escrow_cancel` (cancels deal)
      - Fixed buggy `finish_after` calculation in `fund_deal_escrow()` (was subtracting day-of-month, now uses utcnow + 1 hour)
      - SSE events emitted: `deal_escrow_confirmed`, `deal_completed`, `deal_cancelled`
    - All modified files pass `python3 -m py_compile`: server.py, ai_search.py, xrpl_monitor.py, commercial_auth.py, models.py
49. **Built Phoenix Intelligence Engine — data-aware AI**:
    - **phoenix_intelligence.py (NEW ~450 lines)**: PhoenixIntelligence class bridges Phoenix's proprietary data to AI. `build_ai_context(query, market)` — THE KEY FUNCTION — parses queries for airport codes/cities/dates, pulls route intelligence + market briefing + trending data, returns formatted context string injected into every AI system prompt. `get_route_intelligence(origin, dest)` — multi-market pricing via tracker, price trend direction, demand level from SearchHistory, recent deals. `get_market_briefing(market)` — popular routes, avg savings, price volatility, demand trends. `get_platform_stats()` — total searches, routes, markets, savings. `detect_anomalies()` — high-savings deals + demand surges. `get_provider_performance()` — AI provider win rates from AISearchQuery. CITY_AIRPORT_MAP (50+ cities). All methods lazy-import, try/except, <500ms.
    - **ai_search.py (MODIFIED)**: Replaced `_build_market_context()` call in `search()` with `intelligence.build_ai_context(query, market)` — every AI query now gets Phoenix data injected. Fallback to old market context if intelligence fails. Updated SEARCH_PROMPT to reference proprietary data. Added `search_with_data()` method — fetches live flight prices via AmadeusClient, formats top 5, asks AI ensemble to analyse with Phoenix intelligence context. Returns `{ai_analysis, flights[], data_enhanced: true}`.
    - **server.py (+65 lines)**: 4 portal intelligence routes: `GET /api/intelligence/route/<origin>/<destination>` (route profile), `GET /api/intelligence/market/<market>` (market briefing), `GET /api/intelligence/trending` (anomalies + platform stats), `GET /api/intelligence/platform` (full stats + AI provider performance). All @login_required.
    - **commercial_auth.py (+35 lines)**: 3 commercial intelligence routes: `GET /api/v1/intelligence/route/<origin>/<destination>`, `GET /api/v1/intelligence/market/<market>`, `GET /api/v1/intelligence/trending`. All @require_api_key(scope="analytics").
    - All 4 files pass `python3 -m py_compile`
    - **Data flow**: User query → intelligence parses for route → pulls SearchHistory/PriceHistory/Deal data → formats as context → injects into LLM system prompt → AI answers with REAL Phoenix data instead of guesses

50. **Intelligence Engine Phase 2 — Full Intelligence API (10 new endpoints)**:
    - **phoenix_intelligence.py (+350 lines, 10 new methods)**: `get_p2p_network(days_back)` — helper coverage by country, transaction funnel (status counts), dispute rate + resolution breakdown. `get_p2p_savings(days_back, limit)` — top savings routes grouped by origin/dest/market. `get_node_network()` — delegates to citizenserp_manager.get_network_stats(). `get_proxy_usage(days_back)` — portal sessions, top target sites, sessions by country. `get_ai_analytics(days_back)` — extends provider performance with daily query volume, BYOAI adoption counts, top queried markets, total credits. `get_alert_demand(limit)` — most-watched routes from active PriceAlerts, avg price/savings thresholds. `get_private_market_stats(days_back)` — deal volume by status/type, avg deal size, risk score, completion rate, escrow fees. `get_payment_analytics(days_back)` — payment method distribution, daily revenue trend, conversion rate. `get_price_timeline(origin, dest, days_back)` — delegates to tracker.get_price_trend(). `get_airline_comparison(origin, dest, days_back)` — airline pricing from CompetitorPricing + ancillary fees from AncillarySnapshot, ranks by total cost.
    - **server.py (+140 lines, 10 portal routes)**: `GET /api/intelligence/p2p/network`, `/p2p/savings`, `/nodes`, `/proxy`, `/ai`, `/alerts`, `/deals`, `/payments`, `/price-history/<origin>/<dest>`, `/airlines/<origin>/<dest>`. All @login_required, support `?days=N` and `?limit=N` query params.
    - **commercial_auth.py (+70 lines, 7 commercial routes)**: `GET /api/v1/intelligence/p2p/network`, `/p2p/savings`, `/nodes`, `/proxy`, `/ai`, `/price-history/<origin>/<dest>`, `/airlines/<origin>/<dest>`. All @require_api_key(scope="analytics"). Alerts/deals/payments are portal-only (internal data).
    - All 3 files pass `python3 -m py_compile`
    - **Purpose**: Triple-use — user-facing intelligence dashboards, commercial API data products, and future agent tool kit (each route becomes a callable tool for PhoenixAI agent)

51. **CitizenSERP Task Type System — typed task dispatch**:
    - **citizenserp_tasks.py (NEW ~550 lines)**: Complete task type infrastructure for CitizenSERP nodes. `TaskType` enum (flight_search, hotel_search, product_search, marketplace_browse, price_monitor, general_search). `TaskStatus` enum (created→queued→dispatched→executing→extracting→completed/failed/timed_out/cancelled). `TaskPriority` enum (LOW=1, NORMAL=5, HIGH=8, URGENT=10). `ExtractionRule` dataclass — CSS selector-based structured data extraction (field_name, selector, attribute, transform, required, multiple). `TaskDefinition` dataclass — blueprint per task type with navigation_steps, extraction_rules, timeout, retry, payout_multiplier. `CitizenSERPTask` dataclass — concrete task instance with dispatch tracking, result data, node assignment, requester info. `TaskResult` dataclass — structured node response. `TaskRegistry` class — registers builtin + dynamic task types, `create_task()` factory. `TaskDispatcher` class — `find_available_node(market)` queries HelperProfile+UserWallet, `dispatch(task)` assigns to best node, `dispatch_multi_market()` fans out to N markets, `record_result()` with retry logic, `cleanup_stale()` timeout handling. `MARKET_CONFIG` — 45 country configs (currency, language, Google domain). Pre-built extraction rules for Google Flights, Google Hotels, Google Shopping, Facebook Marketplace, price monitors. Module singletons: `task_registry`, `task_dispatcher`.
    - All files pass `python3 -m py_compile`

52. **PhoenixAI Agent Orchestrator — autonomous intelligence layer**:
    - **phoenix_agent.py (NEW ~500 lines)**: The brain of Phoenix. `AgentTools` class wraps all 12 PhoenixIntelligence methods as callable tools (route_intelligence, market_briefing, platform_stats, p2p_network, node_network, proxy_usage, ai_analytics, alert_demand, price_timeline, airline_comparison, p2p_savings, get_popular_routes). `MarketSelector` class — intelligent market selection using node availability, route history, priority markets, confidence scoring. `PhoenixAgent` class — `handle_search(query, user_id, task_type, user_market)` end-to-end search orchestration (parse intent → select markets → dispatch CitizenSERP tasks → gather context → generate recommendations). `_parse_query_intent()` — NLP-lite intent detection for task type, airport code extraction, city-to-airport mapping, date extraction. `discover_opportunities(force)` — autonomous opportunity discovery from alert demand, P2P savings routes, underutilized markets, proxy usage patterns (new vertical signals). `analyze_route(origin, dest)` — deep parallel analysis combining all intelligence tools. `get_agent_status()` — operational capabilities, tool availability, dispatcher stats. Multi-vertical methods: `search_product()`, `search_hotel()`, `browse_marketplace()`. Module singleton: `phoenix_agent`.
    - **server.py (+160 lines, 11 portal routes)**: 6 agent routes: `POST /api/agent/search` (agent-orchestrated search), `GET /api/agent/analyze/<origin>/<dest>` (deep route analysis), `GET /api/agent/discover` (opportunity discovery), `POST /api/agent/markets` (market selection), `GET /api/agent/status` (agent status). 5 task routes: `GET /api/tasks/types` (list task types), `POST /api/tasks/dispatch` (dispatch task to node), `GET /api/tasks/<task_id>` (task status), `GET /api/tasks/active` (active tasks), `GET /api/tasks/stats` (dispatcher stats). All @login_required.
    - **commercial_auth.py (+60 lines, 6 commercial routes)**: `POST /api/v1/agent/search` (@require_api_key scope="search"), `GET /api/v1/agent/analyze/<origin>/<dest>` (analytics), `GET /api/v1/agent/discover` (analytics), `GET /api/v1/agent/status` (analytics), `GET /api/v1/tasks/types` (analytics), `GET /api/v1/tasks/stats` (analytics).
    - All 4 files pass `python3 -m py_compile`
    - **Architecture**: Agent uses intelligence routes as tools → dispatches typed tasks to CitizenSERP nodes → aggregates results → AI ensemble analysis. Every search pays the node. Every search feeds Phoenix's data layer. Self-upgrading via opportunity discovery.

53. **Geographic Zone System — Sub-Regional Precision Arbitrage**:
    - **geographic_zones.py (NEW ~400 lines)**: Central zone definition system. `GeoZone` dataclass (zone_code, country, name, cities, lat/lon, timezone, population_tier). `ZONE_REGISTRY` — ~75 zones across 45 countries. US: 9 zones (NE, SE, MW, SW, NW, SC, NC, GL, MT). CA: 5, MX: 3, GB: 4, DE: 4, FR: 3, ES: 3, IT: 3, JP: 4, IN: 4, KR: 2, AU: 3, BR: 3, AR: 2. Smaller countries: single-zone. Auto-built indexes: `_COUNTRY_ZONES` (country→zones), `_CITY_TO_ZONE` (city→zone). Public API: `get_zone()`, `get_zones_for_country()`, `get_zone_for_city()`, `resolve_market()`, `is_zone_code()`, `get_country_from_zone()`, `get_zone_summary()`, `get_all_zones()`, `get_all_countries()`. Zone code format: `{country}-{suffix}` (e.g. US-NE, JP-KT, GB-LN).
    - **Migration j0k1l2m3n4o5**: ADD zone_code VARCHAR(10) to helper_profiles + index. ADD ip_zone VARCHAR(10) to node_sessions + index.
    - **models.py (MODIFIED)**: HelperProfile gained `zone_code = db.Column(db.String(10), nullable=True, index=True)`. NodeSession gained `ip_zone = db.Column(db.String(10), nullable=True, index=True)`.
    - **citizenserp_tasks.py (MODIFIED +40 lines)**: `get_market_config()` handles zone codes by extracting country prefix. `find_available_node()` rewritten for zone-aware routing: zone_code match → city match via geographic_zones → country fallback. Returns zone_code in node info dict.
    - **phoenix_agent.py (MODIFIED +60 lines)**: `MarketSelector.select_zones()` — adds intra-country zones for home market, expands foreign countries to major zones, boosts zones with active nodes, deduplicates by confidence. `discover_opportunities()` gained `intra_country_arbitrage` opportunity type.
    - **citizenserp_payouts.py (MODIFIED +20 lines)**: `record_node_online()` accepts `ip_zone` parameter, auto-derives zone from helper city via `geographic_zones.get_zone_for_city()`, updates helper.zone_code. `get_network_stats()` added `nodes_by_zone` breakdown.
    - **proxy_portal.py (MODIFIED +10 lines)**: `create_proxy_session()` accepts optional zone parameter, handles zone codes passed as country_code.
    - **server.py (MODIFIED +40 lines)**: 2 new zone routes — `GET /api/zones` (full zone summary with live node counts per zone), `GET /api/zones/<country>` (zones for specific country with node counts).
    - All 9 files pass `python3 -m py_compile`
    - **Core insight**: Google's URL params (gl, hl) are country-level, but proxy IP physical location determines actual prices shown. A node in NYC vs Dallas returns different prices. The zone system is about node routing precision, not URL construction. Universal for all verticals.

54. **Node Registration & Discovery System**:
    - **node_registry.py (NEW ~580 lines)**: Central node registration and discovery for CitizenSERP network. `NodeCapabilities` dataclass (country_code, city, zone_code, has_browser, has_auth_sessions, bandwidth_tier, max_concurrent_tasks, supported_task_types, platform). `RegisteredNode` dataclass (node_id, user_id, capabilities, status, current_tasks, timing stats, computed success_rate and is_available). `NodeRegistry` class with 3 in-memory indexes (_nodes, _user_nodes, _zone_nodes) + threading.Lock. Key methods: `register_node()` (generates node_id, persists to DB), `unregister_node()`, `heartbeat()`, `update_capabilities()`, `discover_nodes()` (filtered by zone/country/task_type), `get_network_topology()`, `cleanup_stale_nodes()` (marks stale after 5 min), `assign_task()`/`complete_task()`. Module singleton: `node_registry`. Bridges helper_client.py ↔ browser_control.py ↔ citizenserp_payouts.py.
    - **server.py (+120 lines, 6 routes)**: `POST /api/nodes/register`, `POST /api/nodes/heartbeat`, `POST /api/nodes/unregister`, `GET /api/nodes/discover` (filtered), `GET /api/nodes/topology`, `GET /api/nodes/my`.

55. **Real-Time Event Emitters — Typed SSE Push**:
    - **event_stream.py (MODIFIED +130 lines)**: Added 9 typed event emitter convenience functions after register_sse_routes: `emit_p2p_update(buyer_id, helper_user_id, event_type, data)` — notifies both parties + admin; `emit_payment_event(user_id, event_type, data)` — payment status to user + admin; `emit_price_alert(user_id, alert_data)` — to specific user; `emit_opportunity(data)` — global + admin; `emit_anomaly(data)` — admin only; `emit_node_event(event_type, data)` — nodes channel + admin + node owner; `emit_dispute_event(buyer_id, helper_user_id, event_type, data)` — both parties + admin; `emit_deal_event(event_type, data, user_id)` — global + optional user; `emit_system_broadcast(event_type, data)` — global + admin. All add timestamp + category automatically. Enhanced docstring with full event taxonomy.
    - **p2p_orchestrator.py (MODIFIED +40 lines)**: Added `_emit_p2p()` helper (best-effort, never blocks). Wired emit calls at every state transition: matched, escrow_locked, booking_confirmed, completed (+ escrow_released), failed (+ escrow_cancelled), cancelled. Each emit is try/except wrapped so SSE failure never blocks transaction flow.
    - **server.py (MODIFIED +20 lines)**: Added emit calls at escrow release, escrow cancel, and deal dispute state changes.

56. **Dispute Arbitration Engine**:
    - **dispute_resolution.py (MODIFIED +510 lines, now ~850 lines)**: Added `DISPUTE_CONFIG` dict (auto_resolve_threshold=0.75, escalation_amount=500, max_resolution_hours=72, repeat_disputer_threshold=3, stale_dispute_hours=24). 6 new methods on DisputeEngine: `auto_evaluate(dispute_id)` — 6-factor weighted scoring (timeout 20%, evidence 20%, history 15%, helper_rating 15%, amount 15%, timing 15%) → buyer_confidence + helper_confidence + recommendation; `auto_resolve(dispute_id)` — executes recommendation if confidence >= threshold, auto-admin (admin_id=0); `check_auto_resolvable()` — batch job for stale disputes; `get_dispute_analytics()` — totals by status, avg resolution time, repeat disputers, auto-resolved stats; `add_evidence(dispute_id, submitted_by, evidence_type, content)` — screenshot/email/receipt/conversation/other stored as DisputeMessage with [EVIDENCE:{type}] tag; `set_deadline(dispute_id, deadline_dt)` — stores [DEADLINE:iso] tag in resolution_notes to avoid migration.
    - **server.py (+60 lines, 4 routes)**: `POST /api/disputes/<id>/auto-evaluate`, `POST /api/disputes/<id>/auto-resolve`, `POST /api/disputes/<id>/evidence`, `GET /api/disputes/analytics`.

57. **Multi-Vertical Processing Pipelines**:
    - **vertical_pipelines.py (NEW ~1122 lines)**: Processing pipelines for every vertical. `PriceNormalizer` — currency conversion via static rates + landed cost estimation with DUTY_RATES by country. `FlightPipeline.process(results, user_market)` — cross-market flight comparison, normalize to USD, find cheapest per route, calculate savings %. `HotelPipeline.process()` — hotel rate comparison with fuzzy name matching across markets (>80% word overlap), group by property, per-night rate normalization. `ProductPipeline.process()` — product price + shipping + duty = landed cost, SHIPPING_ESTIMATES by region, cross-market product matching, identify cheapest landed cost. `MarketplacePipeline.process()` — listing discovery, fair value via median price, bargain detection (<70% median). `PipelineManager` — unified router by task_type → pipeline, `get_supported_verticals()`. Module singleton: `pipeline_manager`.
    - **server.py (+30 lines, 2 routes)**: `GET /api/pipelines/verticals` (list supported verticals), `POST /api/pipelines/process` (process results through pipeline).

58. **Intelligence Feedback Loop**:
    - **intelligence_feedback.py (NEW ~544 lines)**: Closes the data loop — search results feed back into intelligence for pattern detection and autonomous opportunity creation. `FeedbackEngine` class with in-memory route_cache (route → {prices[], markets, last_updated}), anomaly_log (deque max 1000), stats counters. Key methods: `ingest_task_result(task_result)` — extracts prices, records PriceHistory to DB, detects anomalies, auto-creates opportunities; `ingest_search_result(search_data)` — lighter-weight ingestion from search flows; `detect_patterns()` — analyzes route cache for price trends (declining/rising/stable), volume spikes, savings opportunities (>15% cross-market), new routes; `detect_price_anomaly(route_key, price, market)` — statistical detection (>15% below cache avg = price_drop, >20% above = price_spike), emits SSE anomaly events; `auto_create_opportunity(route_key, opp_type, data)` — creates Opportunity row in DB, emits SSE event; `check_triggered_alerts()` — checks all active PriceAlerts against recent prices; `update_route_cache()`/`get_route_cache()` — per-route price aggregation; `get_feedback_stats()` — processed counts, anomaly counts, cache size; `get_recent_anomalies(limit)`. Module singleton: `feedback_engine`.
    - **server.py (+40 lines, 3 routes)**: `GET /api/feedback/stats`, `GET /api/feedback/anomalies`, `GET /api/feedback/route-cache/<origin>/<dest>`.

59. **Wiring & Cleanup**:
    - Deleted `intelligence_methods_tmp.py` (empty 0-line file, not imported anywhere).
    - All new/modified files pass `python3 -m py_compile`: node_registry.py, intelligence_feedback.py, vertical_pipelines.py, dispute_resolution.py, event_stream.py, p2p_orchestrator.py, server.py.
    - Total new API routes added: 15 routes (6 node, 2 pipeline, 3 feedback, 4 dispute).

60. **Close the Data Loop — Full Integration Wiring**:
    - **citizenserp_tasks.py (MODIFIED +50 lines)**: `_record_node_task_completion()` now calls: (1) `feedback_engine.ingest_task_result()` — feeds completed task data into intelligence feedback loop for anomaly detection and opportunity creation; (2) `pipeline_manager.process()` — processes result data through the appropriate vertical pipeline (flight/hotel/product/marketplace), enriches task result with `pipeline` key containing cross-market arbitrage analysis; (3) `node_registry.complete_task()` — updates the in-memory registry with task completion stats. `find_available_node()` rewritten with dual strategy: tries `node_registry.discover_nodes()` first (in-memory, fast), falls back to DB queries on cold start. All integrations are try/except wrapped — failures never block task flow.
    - **celery_app.py (MODIFIED +80 lines, 4 new periodic tasks)**: (1) `cleanup_stale_nodes` (every 10 min) — calls `node_registry.cleanup_stale_nodes()`, marks dead nodes offline, emits SSE events; (2) `auto_resolve_stale_disputes` (every 30 min) — calls `dispute_manager.check_auto_resolvable()`, auto-evaluates disputes older than 24 hours, resolves or escalates; (3) `detect_feedback_patterns` (every 6 hours) — calls `feedback_engine.detect_patterns()`, detects price trends, anomalies, savings opportunities; (4) `check_feedback_triggered_alerts` (every 10 min) — calls `feedback_engine.check_triggered_alerts()`, notifies users when prices drop below alert thresholds. All 4 tasks routed to `maintenance` queue. Beat schedule updated from 13 → 17 periodic tasks.
    - Both files pass `python3 -m py_compile`.
    - **Impact**: The data flywheel is now connected: Task dispatch → Node execution → Task completion → Feedback ingestion → Pattern detection → Anomaly alerts → Opportunity creation → New tasks. Node registry provides fast in-memory discovery. Disputes auto-resolve. Price alerts trigger automatically.

61. **Private P2P Deal Links — Shareable Escrow for Foreign Marketplace Transactions**:
    - **Problem**: Users browsing foreign marketplaces via Phoenix proxy (e.g., Facebook Marketplace Japan) had no transaction vehicle to settle with sellers. The market comparison model (flights, hotels, products) doesn't apply to one-off private listings.
    - **Solution**: Shareable deal links that create XRPL escrow between a Phoenix buyer and an external seller who does NOT need a Phoenix account.
    - **Flow**: Buyer creates deal (no seller_wallet required) → generates shareable link → emails link to seller → seller clicks link (public page, no auth) → views terms, provides XRPL wallet, accepts → buyer gets SSE notification → buyer funds escrow → normal delivery/confirmation/dispute flow.
    - **models.py (MODIFIED +20 lines)**: `PrivateMarketDeal` — 6 new columns (link_token String(64) unique indexed, seller_email String(256), seller_name String(200), link_expires_at DateTime, seller_accepted_at DateTime, link_viewed_at DateTime). `seller_wallet` changed from NOT NULL to nullable. Updated `to_dict()` with new fields + computed `link_url` and `is_link_expired`. Status flow updated: `draft → link_sent → seller_accepted → escrow_funded → delivered → completed`.
    - **ai_search.py (MODIFIED +200 lines)**: Added `_validate_xrpl_address()` module-level helper (regex + optional xrpl-py). Updated `create_private_deal()` — seller_wallet now optional, accepts seller_email/seller_name. Updated `fund_deal_escrow()` — accepts both 'draft' and 'seller_accepted' status, validates seller_wallet is set. 6 new PhoenixAI methods: `generate_deal_link(deal_id, user_id, expiration_days)` — generates secrets.token_urlsafe(32), sets status=link_sent, emits SSE; `send_deal_link_email(deal_id, user_id)` — sends HTML email via email_service with deal terms + escrow explainer + CTA button; `get_deal_by_link_token(link_token)` — public lookup, sanitised response, checks expiration; `accept_deal_link(link_token, seller_wallet, seller_name)` — XRPL address validation, sets seller_wallet + status=seller_accepted, emits SSE to buyer; `mark_deal_link_viewed(link_token)` — analytics, first-view timestamp + SSE to buyer; `cleanup_expired_deal_links()` — batch marks expired links.
    - **server.py (MODIFIED +120 lines, 5 new routes)**: Updated `POST /api/portal/deal/create` — seller_wallet no longer required. 3 new authenticated routes: `POST /api/portal/deal/<id>/generate-link` (1-30 day expiration), `POST /api/portal/deal/<id>/send-link` (email to seller), `GET /api/portal/deal/<id>/link-status` (viewed/accepted/expired). 2 new PUBLIC routes (no auth): `GET /deal/link/<token>` (self-contained HTML page with PHOENIX branding, deal terms, price breakdown, escrow explainer, wallet input form, JS fetch-based acceptance), `POST /deal/link/<token>/accept` (rate-limited 3/min per IP, XRPL wallet validation). In-memory rate limiter `_check_rate_limit()`.
    - **migration k1l2m3n4o5p6**: ALTER seller_wallet nullable, ADD 6 columns, CREATE UNIQUE INDEX on link_token.
    - All 4 files pass `python3 -m py_compile`.
    - **Key design**: Seller needs zero Phoenix infrastructure — just a browser and an XRPL wallet. Link token is the auth. Backwards compatible — existing direct-wallet deal flow unchanged. Email failure gracefully degraded (buyer can share URL manually).

62. **Multi-Platform Share Links + Smart Contract Templates + Seller Onboarding**:
    - **Problem**: Deal links and referral links existed but had no platform-specific sharing — users had to manually copy/paste URLs. No contract templates for common transaction types. Sellers accepting deals had no onboarding path to become Phoenix users.
    - **Solution**: (A) 12-platform share link generation for deal links AND referral links. (B) Single active link revocation — generating new link invalidates previous. (C) 8 reusable smart contract templates for common transaction types. (D) Seller onboarding funnel built into deal acceptance page.
    - **share_links.py (NEW ~330 lines)**: Central share link + contract template module. `PLATFORMS` dict — 12 platforms (WhatsApp, Telegram, Signal, Facebook, Messenger, X/Twitter, Instagram, TikTok, Gmail, SMS, Email, Copy) with URL templates, icons, direct_share flags. `ShareContext` dataclass (url, title, description, message, subject). `generate_share_links(ctx)` — builds all platform URLs from context. `generate_deal_share_links(deal, base_url)` — deal-specific wrapper with escrow messaging. `generate_referral_share_links(referral_code, user_name, base_url)` — referral wrapper with download CTA. `get_platform_list()` — all platforms with metadata. `CONTRACT_TEMPLATES` dict — 8 templates: goods_standard (14d, delivery confirm), goods_high_value (21d, 3-day inspection), services_standard (7d, completion confirm), services_milestone (30d, partial releases), digital_instant (1d, auto-release), vehicle_purchase (30d, title transfer + 5-day inspection), rental_deposit (90d, refund on return), custom (user-defined). `get_contract_templates()`, `get_template(id)`, `apply_template(id, details)` — template defaults merge with user overrides (user wins).
    - **models.py (MODIFIED +1 line)**: `User.onboarded_from_deal_id` — Integer, nullable. Tracks which deal brought a seller into Phoenix as a user.
    - **ai_search.py (MODIFIED ~20 lines)**: `generate_deal_link()` updated with single-link revocation — clears old link_token, resets seller_wallet/seller_name/seller_accepted_at/link_viewed_at before generating new token. Now allows `seller_accepted` status deals to regenerate links (not just draft/link_sent). Includes `share_links` dict in response via `generate_deal_share_links()`.
    - **server.py (MODIFIED +150 lines, 7 new routes)**: `POST /deal/link/<token>/signup` — PUBLIC seller account creation (email, password, name). Creates User with onboarded_from_deal_id, creates UserWallet from deal.seller_wallet as verified primary wallet. `GET /api/portal/deal/<id>/share-links` — multi-platform share links for deal (auth required). `GET /api/referral/share-links` — referral share links for current user (auth required). `GET /api/share/platforms` — list all 12 supported share platforms (public). `GET /api/contracts/templates` — list all 8 contract templates (public). `GET /api/contracts/templates/<id>` — specific template detail (public). Updated deal acceptance HTML page — after successful acceptance, shows onboarding signup form (email + password) with `doSignup()` JS function. Wallet pre-linked on signup.
    - **commercial_auth.py (MODIFIED +15 lines)**: `GET /api/v1/account/share-links` — commercial account referral share links using generate_referral_share_links().
    - **migration l2m3n4o5p6q7**: ADD onboarded_from_deal_id to users table.
    - All 6 files pass `python3 -m py_compile`.
    - **Key design**: Platform-agnostic ShareContext → per-platform URL generation. Instagram/TikTok/Signal gracefully degrade to clipboard text (no share URL API). Single active link prevents old links from being accepted — old token cleared, all seller fields reset. Contract templates are additive defaults — user overrides always win. Seller onboarding is optional soft CTA — seller can accept deal without creating account.

72. **Build #72 — Phoenix AI: Conversational Interface + Tool Orchestration**:
    - **Problem**: Users interact with Phoenix through manual form-based UI. Need a modern AI-powered conversational interface as a premium layer that can access all Phoenix capabilities via natural language.
    - **Solution**: Phoenix AI — LLM-powered chat interface with tool-calling orchestration. Dual-function: standard Phoenix features remain accessible without AI; Phoenix AI is a tiered subscription.
    - **phoenix_ai.py (NEW ~1400 lines)**: PhoenixAI class — tool-calling orchestrator using Anthropic Messages API (claude-sonnet-4-20250514). 14 tool definitions mapping to existing modules: search_flights→search_global, search_hotels/products→phoenix_agent, analyze_route→phoenix_agent.analyze_route, get_route_intelligence/market_briefing/trending/price_history→intelligence module, browse_proxy→proxy session, serp_search→serp_api_manager, get_node_status→node_registry, get_earnings→yield_dashboard, get_deals→Deal.query, discover_opportunities→phoenix_agent. PHOENIX_AI_TIERS dict (4 tiers: ai_free/0$/25q, ai_starter/$19/500q, ai_professional/$49/2000q, ai_unlimited/$99/unlimited). Node operators get 25% discount. Rich content formatting (HTML tables, charts, cards). Multi-turn context management.
    - **phoenix_ai_api.py (NEW ~350 lines)**: register_phoenix_ai_routes(app). 7 routes: POST /api/v1/ai/chat (SSE streaming chat with tier quota + rate limit enforcement), GET /api/v1/ai/conversations (list user conversations), POST /api/v1/ai/conversations (create new), GET /api/v1/ai/conversations/<id> (history), DELETE /api/v1/ai/conversations/<id>, GET /api/v1/ai/tier (user tier + usage), GET /api/v1/ai/pricing (public tier options). In-memory sliding window rate limiting per user. Per-query credit system (1 query = 1 credit, tool calls free).
    - **models.py (MODIFIED +40 lines)**: AIConversation model (conversation_id, user_id, title, message_count, total_credits_used, is_active, timestamps, composite index on user_id+last_message_at). AIMessage model (conversation_id FK, role, content, tool_calls JSON, credits_used, model_used, response_time_ms, composite index on conversation_id+created_at). User +ai_tier (String(30), default 'ai_free'), +ai_queries_used_this_month (Integer, default 0), +ai_month_reset_date (DateTime).
    - **server.py (MODIFIED +270 lines)**: PHOENIX_AI_CONTENT template — full-height chat UI with conversation sidebar, message bubbles (user/assistant), rich content rendering, SSE streaming typewriter effect, input bar, quick action buttons (Search flights, Browse proxy, Check earnings, Find deals), tier/usage indicator. /ai route. Nav updated: "Phoenix AI" link. register_phoenix_ai_routes(app) call.
    - **event_stream.py (MODIFIED +6 lines)**: emit_ai_response(user_id, chunk_data) helper for SSE streaming of AI chat responses.
    - **migrations/versions/s9t0u1v2w3x4 (NEW)**: ai_conversations table (4 indexes), ai_messages table (2 indexes), +3 columns on users.
    - All files pass `python3 -m py_compile`.

71. **Build #71 — Tier Gates, Webhook Delivery, Operator Dashboard, Commercial Onboarding, Rate Limiting**:
    - **Problem**: Build #70 created the browsing tier system but: (1) tier checks not enforced on browsing endpoints, (2) async SERP queries don't deliver results to callback URLs, (3) node operators can't see payout history or quality ratings, (4) no self-service commercial signup, (5) no per-account rate limiting on browsing API.
    - **Solution**: 5 features closing the enforcement + delivery + onboarding gaps.
    - **commercial_auth.py (MODIFIED +120 lines)**: Browsing API tier enforcement — all 3 browsing endpoints (/browsing, /browsing/trends, /browsing/domain/<domain>) now check rate limits via _check_browsing_rate_limit(), enforce feature access (raw_events, domain_reports) per tier, check quota, enforce tier-specific days_back and result limits, record usage after queries. Module-level _check_browsing_rate_limit() function — in-memory sliding window (60s) keyed by account_id, uses tier's rate_limit_per_minute (10/60/300/1000). 2 node operator routes: GET /api/v1/node/payouts (payout history with summary), GET /api/v1/node/quality (quality multiplier + rating + feedback). Self-service signup: POST /api/commercial/signup (company_name, contact_email, contact_name, company_website → auto-creates account + starter API key, duplicate email check, validation).
    - **serp_api.py (MODIFIED +120 lines)**: deliver_webhook() method — POST result to callback_url with HMAC-SHA256 signature, 3 retries with exponential backoff (1s/4s/16s), sets callback_status to delivered/failed. Webhook calls wired into monitor_async_queries() for both completed and failed queries. process_pending_webhooks() method — retries stuck "pending" deliveries after server restart. Added imports: hashlib, hmac, requests.
    - All files pass `python3 -m py_compile`.

70. **Build #70 — Revenue Integration, Disbursement Dashboard, Extension Updates, Quality Payouts, Browsing Tiers**:
    - **Problem**: Build #69 created the browsing data pipeline + disbursement worker but: (1) browsing data buyer revenue not in payout pool, (2) no admin UI for RLUSD payouts, (3) no server route to serve extension updates, (4) quality feedback doesn't affect payout weighting, (5) no tier system for browsing data buyers.
    - **Solution**: 5 features closing the revenue + quality feedback loop.
    - **citizenserp_payouts.py (MODIFIED +30 lines)**: Browsing data revenue added to payout pool — queries CommercialAccount.browsing_tier, sums monthly prices from BROWSING_TIERS. Quality score integration — queries data_quality_feedback.get_node_adjustment() per node, applies multiplier to uptime hours (weighted_hours = hours × quality_multiplier), distributes pool by weighted hours. Epoch result includes browsing_data_revenue and quality_adjusted flag.
    - **server.py (MODIFIED +200 lines)**: "Payouts" link added to ADMIN_NAV. ADMIN_DISBURSEMENT_CONTENT template (~100 lines): pending/sent/confirmed/failed summary cards, epoch stats, recent payouts table (user/wallet/amount/status/tx_hash), manual epoch trigger button with CSRF. GET /admin/payouts route (disbursement_worker.get_disbursement_stats() + NodePayout query). POST /admin/payouts/trigger-epoch route. Extension auto-update: GET /extension/updates.xml (serve or generate Google Update2 XML from manifest version), GET /extension/download/<version> (serve ZIP with version validation regex).
    - **browsing_tiers.py (NEW ~200 lines)**: BROWSING_TIERS dict (4 tiers: browsing_free/$0/1K events/7d lookback, browsing_starter/$199/50K/30d, browsing_professional/$999/500K/90d/streaming, browsing_enterprise/$4999/unlimited/365d/custom extractors). Functions: get_tier(), check_browsing_access(), check_browsing_quota(), record_browsing_usage(), reset_monthly_browsing(), get_browsing_tier_info(), get_all_tiers().
    - **models.py (MODIFIED +4 lines)**: CommercialAccount +browsing_tier (String(30), default 'browsing_free'), +browsing_events_used_this_month (Integer, default 0), +browsing_month_reset_date (DateTime, nullable).
    - **commercial_auth.py (MODIFIED +20 lines)**: 2 browsing tier routes: GET /api/v1/intelligence/browsing/tier (current tier + usage + features), GET /api/v1/intelligence/browsing/pricing (all tier options).
    - **migrations/versions/r8s9t0u1v2w3 (NEW)**: +3 columns on commercial_accounts (browsing_tier, browsing_events_used_this_month, browsing_month_reset_date).
    - All files pass `python3 -m py_compile`.

69. **Build #69 — Browsing Data API, Fleet Dashboard, Disbursement, CRX Packaging, Quality Feedback**:
    - **Problem**: Build #67+68 pipeline captures browsing data but: (1) no buyer-facing API for browsing intelligence, (2) no admin fleet overview, (3) no automated RLUSD payouts, (4) no extension packaging for distribution, (5) no quality feedback loop from data buyers.
    - **Solution**: 5 features completing the node-to-buyer data monetization loop.
    - **node_data_processor.py (MODIFIED +120 lines)**: 3 commercial query methods: query_browsing_events() (paginated, filtered by type/domain/category/quality), get_browsing_trends() (time series + top domains + event distribution), get_browsing_domain_report() (deep-dive per domain).
    - **commercial_auth.py (MODIFIED +80 lines)**: 3 browsing intelligence routes: GET /api/v1/intelligence/browsing, /browsing/trends, /browsing/domain/<domain> (all require_api_key scope="browsing_data"). 2 feedback routes: POST /api/v1/intelligence/feedback, GET /api/v1/intelligence/feedback/stats.
    - **server.py (MODIFIED +120 lines)**: ADMIN_NODE_FLEET_CONTENT template (~80 lines): fleet summary cards (total helpers, token-enabled, active nodes), pipeline stats (pending/processed/failed events, total value), event type distribution, top 10 nodes by event count, processor runtime. GET /admin/nodes route. "Nodes" added to ADMIN_NAV.
    - **payout_disbursement.py (NEW ~350 lines)**: PayoutDisbursementWorker class: process_pending_payouts() queries NodePayout(status=pending), skips dust <0.0001, submits XRPL Payment via xrpl-py (graceful fallback to simulation). verify_sent_payouts() confirms on-chain, updates HelperProfile.total_earned_rlusd, marks epochs completed. get_disbursement_stats() aggregate reporting. trigger_epoch_and_disburse() convenience. SIMULATED mode default for dev.
    - **tasks.py (MODIFIED +30 lines)**: payout_disbursement_task (300s interval) + payout_verification_task (120s interval) registered in start_background_tasks().
    - **build_extension.py (NEW ~210 lines)**: validate_manifest(), build_zip() (versioned ZIP), generate_update_xml() (self-hosted Chrome auto-update), generate_build_info() (JSON metadata), CLI entry point.
    - **data_quality_feedback.py (NEW ~350 lines)**: DataQualityFeedbackEngine: submit_feedback() (persist + recalculate), _recalculate_node_adjustments() (weighted rating→multiplier 0.5-1.5), get_node_adjustment() per-node, get_feedback_stats() aggregate. Singleton: quality_feedback_engine.
    - **models.py (MODIFIED +20 lines)**: DataQualityFeedback model (feedback_id unique, event_id FK→browsing_events.event_id, account_id, node_id, rating good/neutral/poor, comment).
    - **migrations/versions/q7r8s9t0u1v2 (NEW)**: data_quality_feedback table with 5 indexes.
    - All files pass `python3 -m py_compile`.

68. **Post-Build #67 — Token Flow, Tests, Icons, Background Worker, Dashboard**:
    - **Problem**: Build #67 pipeline complete but: (1) no way for users to generate helper tokens, (2) no tests, (3) no extension icons, (4) synchronous-only event processing, (5) no UI for browsing earnings.
    - **Solution**: 5 post-build items completing the Build #67 activation path.
    - **server.py (MODIFIED +110 lines)**: 2 token routes: POST /helper/token/generate (secrets.token_urlsafe(48), requires active helper), GET /helper/token (JSON response for copy-to-clipboard). BROWSING_DASHBOARD_CONTENT template (~90 lines inline HTML): connection status, token management with copy+regenerate, 4 earnings summary cards (total value, events, avg/day, quality), per-type breakdown table, setup instructions. GET /helper/browsing route using node_data_processor.get_ingestion_stats().
    - **node_data_processor.py (MODIFIED +60 lines)**: process_pending_events(batch_size=200) method — queries BrowsingEvent(is_processed=False), reconstructs event_dict from stored fields + JSON, routes through _route_event(), marks processed, batch commits.
    - **tasks.py (MODIFIED +15 lines)**: browsing_event_processing_task() registered via start_task() with 15s interval. Calls node_data_processor.process_pending_events().
    - **tests/test_extension_pipeline.py (NEW ~370 lines)**: 24 tests across 5 classes: TestHelperTokenGeneration (4), TestNodeServiceAuth (5), TestDataIngestion (6), TestNodeSessionLifecycle (6), TestNodeConfig (3). helper_client fixture with full HelperProfile+wallet+card+token setup.
    - **phoenix_extension/icons/ (NEW, 3 PNG files)**: icon16.png, icon48.png, icon128.png — orange "P" on dark circle, generated programmatically as valid PNGs.
    - All modified files pass `python3 -m py_compile`.

67. **Browser Extension + Local Node Service (Build #67)**:
    - **Problem**: Node data collection only occurs during active CitizenSERP task execution. Passive browsing data (search queries, ad impressions, prices, social signals) is never captured. Nodes earn nothing during idle browsing time.
    - **Solution**: Chrome extension + localhost daemon + server-side processor that captures ALL browsing data passively, routes it through existing hooks, and pays nodes micropayments for continuous data contribution.
    - **Data flow**: Chrome extension (content.js DOM extraction) → background.js buffering → localhost:19750/events → node_service.py batch upload → /api/v1/node/data/ingest → node_data_processor.py (validate, dedupe, score, classify, persist, route) → yield_dashboard + ad_intelligence + feedback_engine
    - **models.py (MODIFIED +65 lines)**: BrowsingEvent model (event_id, user_id, node_id, event_type, url, domain, event_data JSON, quality_score, commercial_value_usd, captured_at/ingested_at/processed_at). HelperProfile +helper_token (unique, indexed), +node_id, +last_seen. HelperProfile.to_dict() updated.
    - **node_data_processor.py (NEW ~1000 lines)**: NodeDataProcessor class: ingest_batch() pipeline (rate limit → validate → dedupe → score → classify → value → persist → route). LRU dedup cache (50K entries, SHA-256 keyed by user+url+type+hour). Quality scoring 0-100 (base 30, +title, +rich data, +HTTPS, +classified domain, +type-specific). DOMAIN_VERTICAL_MAP (50+ domains → 8 verticals). Rate limiting 1K/min, 50K/day per node. Routes to yield_dashboard.record_extraction(), ad_intelligence.ingest_ad_from_extension(), feedback_engine.record_search/price_observation().
    - **node_service_api.py (NEW ~350 lines)**: 7 REST routes with require_helper_token decorator. POST /node/auth (generate NOD-xxx node_id), /node/heartbeat, /node/data/ingest (max 500 events), /node/session/start (SES-xxx), /node/session/end. GET /node/config (extraction rules, intervals, limits), /node/earnings.
    - **node_service.py (NEW ~500 lines)**: PhoenixNodeService aiohttp daemon on localhost:19750. Localhost handlers: /status, /events, /config, /proxy.pac, /stop. Background loops: heartbeat (60s), batch upload (30s), config refresh (5min). Exponential backoff reconnect (1s→60s). CLI entry point with --token/--server/--port/--proxy-mode/--verbose.
    - **phoenix_extension/ (NEW, 8 files)**: Manifest V3 Chrome extension. background.js: service worker with event buffering (max 200), flush to localhost every 10s via alarms, status badge (green/gray). content.js: DOM extractors for search queries (Google/Bing/Yahoo/DDG), ads (13 selectors), prices (schema.org/JSON-LD/CSS fallback), social signals (7 platforms), MutationObserver for SPA. popup.html/js: earnings + status display. options.html/js: server URL, token, port settings via chrome.storage.sync.
    - **node_yield_dashboard.py (MODIFIED +5 lines)**: +browsing_data category ($0.0001/record). TASK_CATEGORY_MAP +5 event types: page_visit→browsing_data, ad_impression→ad_intelligence, price_observation→product_pricing, social_signal→social_signals, search_query→search_results.
    - **node_registry.py (MODIFIED +5 lines)**: +browsing_data to DEFAULT_TASK_TYPES. +has_extension capability on NodeCapabilities (to_dict/from_dict updated).
    - **event_stream.py (MODIFIED +10 lines)**: emit_extension_event(user_id, event_type, data) → publishes to user:{id} + nodes channels.
    - **server.py (MODIFIED +3 lines)**: register_node_service_routes(app) imported and called.
    - **migration p6q7r8s9t0u1 (NEW)**: browsing_events table (6 indexes) + 3 columns on helper_profiles (helper_token unique indexed, node_id, last_seen).
    - All 8 Python files pass `python3 -m py_compile`.

66. **Vertical Completion — Gaps Fixed (Build #66)**:
    - **Problem**: 7 verticals at 85-90% completion with specific gaps: flights missing dedicated agent method, marketplace limited to 5 extraction rules with no commercial API, no vertical-specific DB models (all prices stored as JSON blobs), hotel fuzzy matching ignores location, digital goods region-lock values not standardized, e-commerce category detection limited to 6 categories.
    - **Solution**: Close all 7 gaps to bring all verticals to 100%.
    - **phoenix_agent.py (MODIFIED +14 lines)**: Added `search_flights(origin, destination, date)` method — flights now have a dedicated agent method like all other verticals.
    - **citizenserp_tasks.py (MODIFIED)**: MARKETPLACE_BROWSE extraction_rules expanded from 5 to 8: +seller_name, +condition, +posted_date selectors.
    - **vertical_pipelines.py (MODIFIED +80 lines)**: (A) MarketplacePipeline.process() now extracts seller_name, condition, posted_date. (B) HotelPipeline._fuzzy_match_hotels() now accepts location params — rejects matches where locations share no common words. (C) DigitalPipeline gains REGION_LOCK_MAP (14 canonical codes: Global, EU, NA, APAC, JP, CN, LATAM, CIS, SEA, ROW, etc.) and _normalize_region_lock() classmethod. (D) ECommercePipeline.CATEGORY_KEYWORDS expanded from 6 to 10 categories: +automotive, +baby, +pet, +garden. Existing categories also expanded with more keywords.
    - **models.py (MODIFIED +200 lines)**: 5 new vertical-specific models: FlightPriceRecord (origin/dest/airline/stops/duration/cabin), HotelPriceRecord (hotel_name/location/rating/star_rating/amenities), CruisePriceRecord (cruise_line/ship/itinerary/port/cabin_type), ProductPriceRecord (category/seller/platform/shipping/landed_cost), MarketplaceListingRecord (seller/condition/is_bargain/pct_of_median). All with to_dict() and composite indexes.
    - **commercial_auth.py (MODIFIED +105 lines)**: 3 new routes: GET /api/v1/marketplace/listings (filtered query with bargain flag), GET /api/v1/marketplace/stats (volume/price/bargain analytics), GET /api/v1/vertical/prices (unified price query across all 4 verticals with per-vertical filters: origin/dest/airline for flights, hotel_name/location for hotels, cruise_line/port for cruises, category/platform for products).
    - **migration o5p6q7r8s9t0** (NEW): Creates 5 vertical-specific price tables with full indexes.
    - All 6 files pass `python3 -m py_compile`.

65. **Enhanced Data Extraction + Node Yield Dashboard + Ad Intelligence**:
    - **Problem**: Phoenix nodes earn flat uptime payouts regardless of data value. No visibility into earnings by data category. No ad intelligence pipeline despite ad data being the highest-value category.
    - **Solution**: (A) 6 new high-value task types with higher payout multipliers. (B) Node yield dashboard with per-category earnings, optimization suggestions. (C) Ad intelligence pipeline processing ad extractions into commercial API for data buyers. All revenue feeds back into payout pool.
    - **citizenserp_tasks.py (MODIFIED +200 lines)**: TaskType enum +6 values: AD_INTELLIGENCE (2.0x), PRICING_INTELLIGENCE_DEEP (1.8x), SOCIAL_SIGNAL_EXTRACT (1.5x), AUDIENCE_PROFILE_EXTRACT (1.7x), RETAIL_SHELF_MONITOR (1.6x), COMPETITOR_AD_TRACK (1.9x). Each with full navigation_steps + extraction_rules. `_record_node_task_completion()` +2 hooks: yield_dashboard.record_extraction() for all tasks, ad_intelligence_engine.ingest_task_result() for ad tasks.
    - **ad_intelligence.py (NEW ~1144 lines)**: AD_DATA_VALUES (6 ad formats: search 0.005, shopping 0.008, display 0.003, video 0.010, native 0.004, competitor 0.012 USD/record), VERTICAL_KEYWORDS (8 verticals auto-classification), AD_INTEL_TIERS (starter $500/mo, growth $2K/mo, enterprise $10K/mo), BID_ESTIMATES (format+position CPC with 8 market multipliers). `AdIntelligenceEngine` class: ingest_task_result() (normalize→bulk insert AdIntelligenceRecord + NodeDataExtraction), _normalize_ad_record(), _classify_vertical(), _classify_ad_format(), _estimate_bid(), query_ads() (paginated with market/vertical/advertiser/network filters), get_ad_trends() (daily/weekly time-series + top advertisers + format distribution), get_competitor_report() (ad frequency, spend, copy variations, position distribution, competing advertisers), get_revenue_stats() (total/sold/realized + vertical/market breakdowns), get_monthly_revenue() (sold records + tier subscriptions → payout pool).
    - **node_yield_dashboard.py (NEW ~450 lines)**: DATA_CATEGORY_VALUES (10 categories: flight_pricing 0.002, hotel_pricing 0.002, product_pricing 0.001, ad_intelligence 0.005, social_signals 0.003, audience_data 0.004, retail_shelf 0.003, competitor_ads 0.008, deep_pricing 0.004, search_results 0.001 USD/record), TASK_CATEGORY_MAP (16 task types → categories). `NodeYieldDashboard` class: get_yield_summary() (today/week/month/total earnings, yield score 0-100: 30% uptime + 30% diversity + 20% quality + 20% volume), get_yield_history() (daily time-series, weekly totals, trend direction, best day), get_category_breakdown() (per-category earnings/records/quality with % of total), get_yield_optimization() (compare active vs available categories, estimate uplift, network benchmarks), record_extraction() (task→category mapping, commercial value calculation, NodeDataExtraction insert).
    - **models.py (MODIFIED +100 lines)**: `NodeDataExtraction` model (session_id, user_id, task_id, task_type, data_category, records_extracted, data_points, data_size_bytes, commercial_value_usd, payout_multiplier, payout_earned_rlusd, quality_score, extraction_metadata). `AdIntelligenceRecord` model (record_id "AI-" prefix, task_id, node_user_id, market, source_url, advertiser, ad_network, ad_format, ad_position, ad_text, ad_destination_url, ad_image_hash, estimated_bid_usd, targeting_keywords/demographics JSON, targeting_geo, vertical, sub_vertical, commercial_value_usd, is_sold, confidence_score, observed_at).
    - **commercial_auth.py (MODIFIED +90 lines)**: 4 yield dashboard routes (@login_required, is_helper_node): GET /api/v1/node/yield, /yield/history, /yield/categories, /yield/optimize. 3 ad intelligence routes (@require_api_key scope="ad_intelligence"): GET /api/v1/intelligence/ads, /ads/trends, /ads/competitors.
    - **citizenserp_payouts.py (MODIFIED +8 lines)**: calculate_epoch_payouts() revenue pool now includes ad_intelligence_engine.get_monthly_revenue() alongside airline SaaS + SERP API revenue.
    - **migration n4o5p6q7r8s9** (NEW): Creates `node_data_extractions` table (7 indexes) + `ad_intelligence_records` table (11 indexes).
    - All 7 files pass `python3 -m py_compile`.
    - **Key design decisions**: (1) Phoenix as data intermediary/custodian — sells data, takes cut, pays nodes as much as possible. (2) Higher-value data categories = higher payout multipliers (2.0x for ad intelligence vs 0.3x for general search). (3) Yield optimizer shows nodes what categories to enable for more earnings — incentivizes broader data access consent. (4) Ad intelligence revenue feeds directly into payout pool alongside airline SaaS and SERP API — adds "monetary fuel" without reducing per-node velocity. (5) Three-tier ad intelligence pricing for data buyers ($500/$2K/$10K/mo). (6) Revenue flywheel: more data buyers → more revenue → higher payouts → more nodes → better data → more buyers.

64. **Phoenix Residential SERP API Service**:
    - **Problem**: Phoenix has a residential proxy node network (CitizenSERP) but no commercial API to sell SERP extraction as a service. Competitors (SerpAPI, Oxylabs) use datacenter proxies — Phoenix is the first fully residential proxy SERP API.
    - **Solution**: Credit-based SERP extraction API with 6 pricing tiers, 8 supported search engines, sync+async execution, rate limiting, and node payout integration.
    - **serp_api.py (NEW ~905 lines)**: `SERP_TIERS` dict (serp_free $0/100 credits → serp_partner custom/999K credits), `CREDIT_MULTIPLIERS` (8 option multipliers: base 1.0, additional_market +1.0, additional_page +0.5, screenshot +0.5, js_rendering +0.3, shopping +0.5, local +0.3, realtime 2.0x), `GOOGLE_DOMAINS` (15 country TLDs), `SUPPORTED_ENGINES` (Google/DuckDuckGo/Bing/Yahoo/Yandex/Baidu/Naver/Yahoo Japan with URL templates + market lists). `SERPAPIManager` class: validate_query(), calculate_credits(), reset_monthly_credits(), check_quota() (hard cap on free, overage on paid), check_rate_limit() (in-memory sliding window), build_task_params() (→ SEARCH_ENGINE_EXTRACT task), format_serp_result() (normalize organic/shopping/ads/related/knowledge_panel), record_usage() (credit decrement + daily summary upsert), execute_sync() (full pipeline: validate→quota→rate→credits→dispatch→format→record), execute_async() (create pending SERPAPIQuery, return query_id), get_query_result(), get_usage_stats() (30-day daily breakdown), get_supported_engines(), get_pricing_info(), monitor_async_queries() (process pending records).
    - **models.py (MODIFIED +100 lines)**: `SERPAPIQuery` model (query_id "sq_" prefix, engine, market, query_text, options JSON, credits_used, status pending/processing/completed/failed/expired, result JSON, error_message, node_id, callback_url, response_time_ms, timestamps). `SERPAPIUsageSummary` model (daily aggregates: total_queries, total_credits, successful/failed, avg_response_time_ms, engines_used/markets_used JSON, unique on account_id+date). `CommercialAccount` +4 columns: serp_tier, serp_monthly_credits, serp_credits_used_this_month, serp_month_reset_date.
    - **commercial_auth.py (MODIFIED +120 lines)**: 6 new routes with `@require_api_key(scope="serp")`: POST /api/v1/serp/search (sync/async mode), POST /api/v1/serp/batch (up to 100 queries, async only), GET /api/v1/serp/query/<query_id> (ownership-verified result retrieval), GET /api/v1/serp/usage (billing period stats), GET /api/v1/serp/engines (supported engines list), GET /api/v1/serp/pricing (tier info + all available tiers).
    - **citizenserp_payouts.py (MODIFIED +15 lines)**: `calculate_epoch_payouts()` revenue pool now includes SERP API subscription revenue — queries paid SERP tier commercial accounts, sums monthly prices, adds to airline SaaS revenue before calculating daily payout pool.
    - **migration m3n4o5p6q7r8** (NEW): Creates `serp_api_queries` table (3 indexes), `serp_api_usage_summaries` table (unique constraint on account+date), adds 4 SERP columns to `commercial_accounts`.
    - All 5 files pass `python3 -m py_compile`.
    - **Key design decisions**: (1) Credit-based pricing — multipliers reward simple queries, charge more for complex options. (2) Sync + async modes — sync for real-time, async for batch with polling. (3) Residential-first positioning — every response includes proxy_type:"residential" and node zone metadata. (4) Reuses SEARCH_ENGINE_EXTRACT task type from Build #63 for actual node dispatch. (5) "serp" scope separate from "search" scope for granular API key permissions. (6) Free tier has hard cap (no overage), paid tiers allow overage at decreasing rates. (7) SERP API subscription revenue feeds into CitizenSERP node payout pool — nodes earn from API queries too.

63. **Four New Verticals + Transaction Fee Engine + Search Engines + Universal Search**:
    - **Problem**: Phoenix only had 4 verticals (flights, hotels, products, marketplace). No fee model to monetize arbitrage savings. No cross-vertical search. No search engine onboarding portal.
    - **Solution**: (A) 3 new pipeline classes (Cruises, E-Commerce, Digital). (B) Fee engine with two models: arbitrage (% of savings, tier-reduced) and private market (flat $1.50 + 1%). (C) Universal search orchestrator dispatching multiple verticals concurrently. (D) Search engine portal category for proxy browsing. (E) 4 new CitizenSERP task types.
    - **vertical_pipelines.py (MODIFIED +678 lines, now ~1801)**: Fee Engine — `REWARDS_TIERS` dict (Standard 25% at 0 tx, Silver 22% at 10 tx, Gold 20% at 25 tx, Platinum 17% at 50 tx), `FLAT_FEE=$1.50`, `BASE_RATE=1%`, `get_user_tier(completed_transactions)`, `_next_tier_info()`, `calculate_arbitrage_fee(savings_amount, deal_amount, completed_transactions)` applies tier rate to savings with minimum floor ($1.50 + 1%), `calculate_private_market_fee(deal_amount)` flat $1.50 + 1%. `CruisePipeline` — per-person-per-night normalization, cruise_line + itinerary fuzzy matching (80% word overlap on line, 50% on itinerary, ±2 nights duration), 5% arbitrage threshold, cross-market matching. `ECommercePipeline` — category detection (electronics/fashion/home/beauty/sports/toys/general from keywords), shipping estimates (30+ origin-dest pairs), landed cost via PriceNormalizer, 80% title overlap matching, FILLER_WORDS set. `DigitalPipeline` — NO shipping/duty, pure currency-normalized price, region-lock tracking per product per market, 3% arbitrage threshold, platform grouping. PipelineManager updated: +3 instances, +3 dispatch entries, +3 convenience methods, +3 supported verticals.
    - **citizenserp_tasks.py (MODIFIED +120 lines)**: TaskType enum +4 values: `CRUISE_SEARCH`, `ECOMMERCE_SEARCH`, `DIGITAL_SEARCH`, `SEARCH_ENGINE_EXTRACT`. TaskDefinitions: CRUISE_SEARCH (60s timeout, 2 retries, 1.3x payout, Google Travel Cruises), ECOMMERCE_SEARCH (45s, 2 retries, 1.0x, Google Shopping broad), DIGITAL_SEARCH (30s, 2 retries, 0.8x, Google + digital license keywords), SEARCH_ENGINE_EXTRACT (30s, 2 retries, 0.5x, lightweight SERP extraction). Each has full navigation_steps + extraction_rules with CSS selectors.
    - **phoenix_agent.py (MODIFIED +200 lines)**: `_parse_query_intent()` reordered — checks cruise/digital/ecommerce/universal BEFORE existing verticals to avoid keyword overlap. `handle_search()` routes `universal_search` intent to `self.universal_search()`. `search_cruise()`, `search_ecommerce()`, `search_digital()` convenience methods. `universal_search()` — smart hybrid: detects primary vertical, maps to 1-2 related via `VERTICAL_MAP`, dispatches all concurrently with ThreadPoolExecutor, merges results. `discover_opportunities()` +2 new signals: cruise_demand_signal (cruise booking sites with >5 sessions), digital_demand_signal (Steam/CDKeys/G2A etc >5 sessions). `get_agent_status()` capabilities list +5 entries.
    - **proxy_portal.py (MODIFIED +12 lines)**: `PORTAL_APP_DIRECTORY` +`search_engines` category with 8 engines: Google (primary, 43 regional domains), DuckDuckGo (privacy-focused), Yandex (RU/CIS), Baidu (CN, behind GFW), Naver (KR, shopping integration), Yahoo Japan (JP auctions), Brave Search (crypto-native), Ecosia (eco-conscious, Europe-heavy).
    - All 4 files pass `python3 -m py_compile`.
    - **Key design decisions**: (1) Two fee models — arbitrage takes % of savings Phoenix finds (25% default, reduced by tier), private market takes flat $1.50 + 1% (no arbitrage possible). (2) ALL transaction types (arbitrage + private market) count toward rewards tier progression. (3) Minimum floor on arbitrage fee = private market fee ($1.50 + 1%). (4) Universal Search is NOT a CitizenSERP task — pure orchestration dispatching existing task types concurrently. (5) CruisePipeline uses per-person-per-night for fair comparison across durations. (6) ECommercePipeline coexists with ProductPipeline — broader scope + category detection. (7) DigitalPipeline has NO landed cost — pure currency conversion + region-lock tracking. (8) New verticals checked FIRST in intent detection to avoid keyword overlap with existing product_search.
    - **Future build specs (documented, not coded)**: Browser extension (auto-detect shopping pages, show arbitrage badge), Telegram bot (@PhoenixArbitrageBot with /search, /compare, /alerts, /deals, /wallet), Crypto wallet integration (XRPL wallet discovery, Xaman deep link, browser wallet detection).
    - **Future concept: Device-Wide Data Monetization (idea #3 from Prompt #65)**: User installs Phoenix app/VPN that intercepts app telemetry and ad tracking from all device apps (Facebook, Google, TikTok etc). Phoenix becomes the intermediary — blocks unwanted data collection, sells consented anonymized/aggregated behavioral data through Phoenix data marketplace, returns revenue to node operators. Requires VPN/DNS filter layer, app store compliance (ATT on iOS, Privacy Sandbox on Android), data marketplace integration. Separate product phase — build after core proxy + SERP API revenue is flowing. Competitive landscape: Brave (BAT), Permission.io, Swash. Phoenix advantage: XRPL settlement rail already built.
