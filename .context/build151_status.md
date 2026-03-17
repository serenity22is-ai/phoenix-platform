# Build #151 — Open Developer Platform, Hosting Architecture & Market Strategy (Discussion Only)
**Date**: 2026-03-09
**Status**: DECISIONS FINALIZED — no code changes, planning/discussion session

## What Was Decided

### 1. API as Immutable Black Box
- ANASTASiA's API is proprietary, sealed, invisible
- Customers interact through REST endpoints only — cannot see or copy code
- Devs build ON TOP of the API logic, which functions immutably

### 2. Four Distinct Revenue Streams (FINAL)
1. **Pro/Enterprise Subscription** ($599/$1,499/mo) — vertical intelligence + maintenance
2. **Sandbox Commission** — 20% (own creds), 35-40% (our creds) during evaluation
3. **Dev Mode** — separate metered product, 2-3x Anthropic API markup
4. **Platform Credential Access** — commission on bookings via our credentials

### 3. Core Subscription vs Dev Mode (Separated)
- Core = vertical intelligence (search, book, issue, refund) + Update Call System. NOT dev exploration.
- Dev mode = separate product, additional subscription, same API key. Metered/query-capped.
- Production ops = structured API routing, near-zero AI cost.
- Update Call System = one Opus 4.6 call amortized across entire network.

### 4. Open Developer Platform
- SDKs + developer tools for building on the platform
- Customers can build whatever they want, including unrelated projects
- Ship, sell, export modules — all via API key
- Open source community building integrations = ecosystem expansion
- Customer liability for modules that conflict with core updates

### 5. Constitution Model (Knowledge Cards)
- Knowledge cards = immutable constitution of what the vertical IS
- Network updates push through core — non-negotiable
- Customer modules built ON TOP with creative freedom
- Modules that conflict with updates break — customer's liability

### 6. Customer-Managed Hosting
- Customers manage their own Render/AWS hosting
- ANASTASiA provides templates (render.yaml, Dockerfile, env vars)
- Hosting NOT bundled — zero costs on our balance sheet, zero data custody liability
- ANASTASiA acts as install wizard

### 7. Integration "Blanks" Architecture
- Vertical ships with defined integration interfaces:
  - PaymentProvider (default: Stripe)
  - HostingProvider (default: Render templates)
  - AuthProvider (default: built-in)
  - DatabaseProvider (default: PostgreSQL)
- Customers fill blanks — core never changes

### 8. Market Strategy — Friction Reduction EXPANDS Markets
- Shopify analogy: lowering barriers creates MORE micro-OTAs, not fewer
- Single person + ANASTASiA = production OTA in a day
- Agencies with only GDS terminal access die; agencies with differentiation thrive
- More OTAs = more ANASTASiA customers

### 9. AERTiCKET Partner Channel — UNCHANGED
- Wholesale volume pricing as competitive moat for consolidators
- Onboarding faster: enter credentials → deploy (no daemon installation)
- Consolidators get exclusive pricing to beat competitors

### 10. Credential Network as Strategic Trojan Horse
- Consolidators join independently → feed same platform unknowingly
- By the time they cooperate, momentum is established
- All network revenue → IATA/ARC accreditation → direct GDS access → replace consolidators
- **Don't signal endgame prematurely**

### 11. Structural COGS Advantage
- MYSTES KYRIOS LLC overhead: ~$550/mo vs AERTiCKET's 850 employees
- Architecture = competitive moat, impossible to match without full business model rebuild
- Near-zero overhead enables devastating market undercutting
- Forces competitors to adopt ANASTASiA subscription model

## Files Modified (Memory/Docs Only)
| File | Action |
|------|--------|
| `memory/sandbox_and_product_model.md` | MODIFY — Added Build #151 sections + 8 new locked decisions |
| `memory/MEMORY.md` | MODIFY — Added Build #151 reference + updated context files |
| `.context/build151_status.md` | CREATE — This file |

## No Code Changes
This was a pure discussion/planning session. All decisions documented for implementation in future builds.

## Previous Build
- **Build #150**: Product Model & Sandbox Economics — ANASTASiA identity, immutable core, delivery mechanisms, sandbox commission
