# Build #150 — Product Model & Sandbox Economics (Discussion Only)
**Date**: 2026-03-09
**Status**: DECISIONS FINALIZED — no code changes, planning/discussion session

## What Was Decided

### 1. ANASTASiA Product Identity — FINAL
ANASTASiA is a **booking intelligence API**. She has mastered specific API frameworks and knows search, booking, payment, issuance, refund, troubleshooting within them. She is NOT a general coding AI.

### 2. Immutable Core + Customer Module Layer
- Template core is LOCKED across all deployments
- ANASTASiA (Claude Opus 4.6) builds MODULES on top of the core for each customer
- Customer modules are isolated — can't break the engine
- Update Call System pushes engine updates to all deployments simultaneously
- Shopify model: customers adapt to our framework

### 3. Three Delivery Mechanisms
1. **API Key** — REST endpoints, customer handles frontend
2. **Turnkey Template** — MYSTES white-labeled, working OTA in minutes
3. **Vertical Plugin** — Self-contained module, customer wires it up

### 4. Sandbox Revenue Model
- Full suite available during sandbox (not limited)
- Real purchases allowed — customers earn money from day one
- 20% commission (own creds), 35-40% (our creds) during sandbox
- Pro subscription ($599/mo) = 0% commission on own credentials
- Conversion trigger: at ~$3K/mo revenue, commission ≈ subscription cost

### 5. Credential Sharing — Two Distinct Features
- **Platform Credential Access (Pro)** — customer uses OUR API credentials. Service we provide. Commission-based.
- **Credential Network (Enterprise)** — federated bidirectional sharing. 85/10/5 revenue split. Network effect.

### 6. Knowledge Flywheel via Customer Credentials
- "Codebase access" = credential access to walled-garden APIs, NOT reading their React/PHP
- Customer credentials unlock APIs we can't access alone (Sabre, Travelport, etc.)
- System Profiles (functional API knowledge) retained permanently on churn
- Legal basis: functional knowledge, not proprietary data
- Automatic learning: new credentials → detect API type → AutoLearner → permanent profile

### 7. ANASTASiA Admin Terminal Scope
- Inside our template: FULL authority (refunds, troubleshooting, module building, config)
- Inside customer's code: READ-ONLY advisory (analyze, advise, generate snippets)
- Module building: customers can ask ANASTASiA to build UI modules within the template framework
- Core stays untouched — modules built on top

### 8. Vertical Positioning
- Flights vertical FIRST — "Replace your flights vertical with ours"
- Hotels when liteAPI production access live
- Future verticals learned from customer API access (knowledge flywheel)
- Each vertical learned = new product for ALL customers

## Files Modified (Memory/Docs Only)
| File | Action |
|------|--------|
| `memory/sandbox_and_product_model.md` | CREATE — Full product model + sandbox economics |
| `memory/MEMORY.md` | MODIFY — Added critical rules, new file reference, build log |
| `memory/anastasia_platform_vision.md` | MODIFY — Updated delivery mechanisms, core principles, sandbox model |
| `.context/build150_status.md` | CREATE — This file |

## No Code Changes
This was a pure discussion/planning session. All decisions documented for implementation in future builds.

## Previous Build
- **Build #149**: Starter Tier Removal — 14 code files + 6 memory/doc files updated, 429 tests passing
