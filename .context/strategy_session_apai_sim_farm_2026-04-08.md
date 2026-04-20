# Strategic Discussion — APAi Revenue Model + SIM Farm Impact
**Date**: 2026-04-08 through 2026-04-10
**Status**: MODEL CONVERGING — Key decisions made, some details TBD. NO CODE CHANGES.
**Builds discussed**: #202 (1.55x markup removal — APPROVED), #203 (revenue model — CONVERGING)

---

## CONTEXT: What Triggered This Discussion

Build #203 was supposed to fix `revenue.py` from flat $2.50 to percentage-based routing fees (5%/3%/2% by APAi tier per `product_model.md` Build #193). User stopped the build because:

1. They remembered deciding on a **flat fee** model, not percentage
2. The introduction of the **CitizenSerp SIM farm** fundamentally changes the credential network calculus
3. They wanted to think through splits realistically before committing to code

Discussion evolved across multiple messages into a comprehensive 4-layer revenue model.

---

## FINAL MODEL (converged 2026-04-10)

### The Four Layers of MYSTES KYRIOS

#### Layer 1: MYSTES Consumer (Guest/Free/Travel+)
- SIM-sourced pricing is a **native MYSTES feature** across ALL consumer tiers
- Customer searches, sees SIM-arbitraged prices (POS hidden), books through MYSTES UI
- Airline is merchant of record. MYSTES charges consumer fee per `payments.py` tiers (50%/45%/35%)
- Customer doesn't know about SIMs, POS, Denmark — just sees a great price
- MYSTES pays itself $0 for SIM routing (own infrastructure, own margin)

#### Layer 2: MYSTES B2B (Starter $49 / Growth $99 / Volume $199)
- Same SIM pricing, same platform, same UI
- B2B subscriber adds own markup, sells through MYSTES using referral links + B2B tools
- "The college kid with a referral code selling group trips"
- Never touches API, never manages credentials, never leaves MYSTES
- MYSTES takes subscription + reduced fee (25%/20%/15%)
- Every B2B sale IS a MYSTES sale — B2B operators are MYSTES's sales force
- "B2B inside MYSTES is basically gated APAi" with SIM pricing advantage

#### Layer 3: APAi ($299/$599/$999)
- Separate turnkey product. Own brand, own domain, own MYSTES template copy
- Gets ANASTASiA SDK + knowledge cards + AI terminal for their own credentials
- Gets Duffel passthrough for immediate inventory (no Duffel account needed)
- Gets **metered, fee-bearing** access to SIM farm pricing:
  - **Per-query search fees** — no hard caps, searches always work, but every SIM query costs money
  - **Percentage of arbitrage on confirmed bookings** — KYRIOS takes a cut because we OWN the infrastructure
  - Query fees ride existing ANASTASiA metering (Pro 500 included/$0.12 overage, Enterprise 2000/$0.08, Scale 5000/$0.05) — or separate meter TBD
- KYRIOS takes $0 on OTA's own credential usage — subscription covers that
- Airline is merchant of record on SIM-routed bookings. Clean hands.

#### Layer 4: Peer-to-Peer Credential Sharing (optional, opsec)
- Build #201 code repurposed. OTAs choose "friends group" affiliates
- Bilateral credential sharing on their own terms. They handle their own costs.
- KYRIOS takes $0. ANASTASiA facilitates routing as the intelligent layer.
- OTAs merge API portfolios to offer more products to consumers
- KYRIOS provides tools: metrics calculator, SDK, ANASTASiA routing intelligence
- **THIS IS THE OPSEC COVER** — outsiders see credential sharing and assume that's how MYSTES achieves its prices. Meanwhile the real engine is the SIM farm.

---

## KEY STRATEGIC INSIGHTS (user-originated)

### Merchant of Record = Clean Hands
- SIM farm routes through airline's public checkout. Airline processes payment via Stripe Issuing virtual card.
- Airline is merchant of record. KYRIOS never touches the ticket transaction.
- KYRIOS charges a separate service fee for "finding a better price"
- No IATA, no NDC contracts, no GDS agreements, no foreign entity needed
- No seller-of-travel (KYRIOS didn't sell the ticket — the airline did)
- Multi-POS without ANY of the traditional regulatory/commercial requirements
- User analogy: "this is legally routing around them just like cellphone carriers did to avoid per text fees"

### SIM Routing = Not Credential Sharing
- SIM routing goes through existing platforms (Google Flights → airline checkout)
- This looks like NDC from the outside. "We honestly seem more ndc."
- It's routing to the airline's own checkout page, not through a third-party API
- The OTA that's routed through (when SIM hits an airline checkout) is the airline itself
- "Clean hands approach to the regulated headache of foreign pos markets"

### Query Fees as Self-Regulating Throttle
- No hard caps that block searches — APAi OTAs can search as much as they want
- Per-query fees for SIM searches mean abuse costs money
- OTAs self-regulate because excessive searching is expensive
- "A competitor trying to clog the network is paying per-query the entire time"
- MYSTES consumer + B2B = uncapped (own platform, own priority)

### MYSTES Always Wins on Price
- KYRIOS charges itself $0 for SIM routing
- APAi OTAs pay query fees + arbitrage percentage
- Same SIM farm, same inventory, but MYSTES keeps 100% of the spread
- This is structural, permanent, and non-negotiable

### B2B = Micro-OTA Infantry
- "The college dorm kid or the kid planning the high school group trip"
- Subscribe for $49, get SIM pricing through MYSTES, sell via referral links
- "Literally anyone can do this. Its a simple referral system"
- Each B2B subscriber is a MYSTES sales channel at zero marketing cost

---

## DECISIONS LOCKED

1. **Build #202 APPROVED**: Remove all `ESTIMATED_RETAIL_MARKUP = 1.55` from search.py (6+ blocks). Ready to execute.

2. **APAi sells three things**: (1) ANASTASiA intelligence + SDK + knowledge cards for own credentials, (2) Turnkey MYSTES template deployment, (3) Metered access to KYRIOS SIM farm pricing.

3. **SIM farm = MYSTES-native feature**: All MYSTES tiers (consumer + B2B) get SIM pricing. No separate product, no separate fee — it's just how MYSTES works.

4. **APAi SIM access = metered**: Per-query search fees (no hard caps) + percentage of arbitrage on confirmed bookings. Self-regulating through economics.

5. **KYRIOS takes $0 on traditional credential routing**: OTA uses own Duffel/Picasso/etc credentials → subscription covers it. ANASTASiA automates it. KYRIOS takes nothing extra.

6. **Peer-to-peer credential sharing = optional opsec**: Build #201 code repurposed. OTAs choose affiliates, handle own costs. KYRIOS provides tools, takes $0.

7. **Merchant of record = airline**: SIM farm routes to airline checkout. Airline processes payment. KYRIOS charges service fee only. Clean hands.

8. **B2B on MYSTES = gated APAi with SIM pricing**: B2B → APAi migration when they want own brand (but they lose SIM pricing advantage).

9. **Two separate query meters for APAi** (locked 2026-04-10): (a) SIM search queries = ALWAYS charged per query, no included allotment, no freebies — this is access to multi-POS arbitrage without IATA/regulatory hurdles. (b) ANASTASiA queries (Anthropic AI) = included cap per tier (500/2000/5000), then overage at Anthropic API cost + KYRIOS markup. Two pools, two economics, two meters.

10. **Build #202 EXECUTED** (2026-04-10): All 6 blocks of `ESTIMATED_RETAIL_MARKUP = 1.55` removed from search.py. `estimated_count` references cleaned. Zero fake savings markup remaining.

---

## STILL TBD (details, not direction)

1. **SIM arbitrage percentage** — what % of arbitrage does KYRIOS take from APAi OTAs on confirmed bookings? Flat across tiers? Or tiered (Pro/Enterprise/Scale)?

2. ~~**SIM query fee metering**~~ — **RESOLVED (2026-04-10)**: SEPARATE meter. SIM queries are ALWAYS charged, no included allotment. ANASTASiA queries (Anthropic AI) have included cap (500/2000/5000) then overage at Anthropic cost + KYRIOS markup. Two pools, two economics. User: "sim search queries are not included they are charged for. apai anastasia queries has a query cap and then is charged per query per the api fees charged by anthropic with our piece on top."

3. **Duffel passthrough cost model** — baked into ticket price (opaque) or passed through as fee? User hasn't specified. Lean opaque.

4. **Peer-to-peer split defaults** — when OTAs share credentials bilaterally, is there a suggested split or do they negotiate everything? Build #201 had 70/30 — is that the default template?

---

## FILES EXAMINED (NO CHANGES MADE)

| File | What was found |
|------|---------------|
| `revenue.py` | Flat $2.50 + 70/30 model (Build #201). WRONG — needs complete rewrite for new model. |
| `search.py` | 6+ blocks of `ESTIMATED_RETAIL_MARKUP = 1.55`. APPROVED for removal (Build #202). |
| `credentials/__init__.py` | Docstring says "Flat $2.50". Will need updating. |
| `test_credential_routing.py` | 12 test classes assert flat $2.50. Will need updating. |
| `test_credential_vault.py` | `test_platform_fee_is_flat_not_percentage` tests $2.50 stays constant. Will need updating. |
| `server.py` (~7170-7199) | `booking.routing_fee_usd = FLAT_PLATFORM_FEE_USD`. Will need updating. |
| `product_model.md` | Says percentage 5%/3%/2%. Outdated — needs rewrite for 4-layer model. |

---

## BUILD #203 SCOPE (when approved)

`revenue.py` becomes a **cost/margin tracker** with three modes:
1. **SIM routing (MYSTES internal)**: Track arbitrage spread + SIM operating cost. KYRIOS keeps 100%.
2. **SIM routing (APAi external)**: Track query fees + arbitrage percentage. Calculate KYRIOS cut.
3. **Peer-to-peer credential sharing**: Track settlements between OTAs. KYRIOS takes $0. OTA-facing analytics tool.

Strip: flat $2.50 KYRIOS fee, hardcoded 70/30 split.
Add: configurable per-affiliate splits, SIM arbitrage fee calculator, query metering hooks.
Keep: vault, network, router infrastructure intact.

---

## WHAT TO DO NEXT SESSION

1. **Execute Build #202** (1.55x markup removal) — all blocks identified, approved, independent of revenue model
2. **Lock TBD items** — SIM arbitrage %, query meter pool, Duffel cost model, p2p split defaults
3. **Execute Build #203** — rewrite revenue.py for 4-layer model
4. **Update MEMORY.md and product_model.md** to reflect final locked model
