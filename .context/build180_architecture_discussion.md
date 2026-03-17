# Build #180 — Architecture Discussion (Session Card)
**Date**: 2026-03-17 | **Status**: IN PROGRESS — discussion continues

---

## THE EXPLOIT: ANASTASiA = Tool, Not Entity

### Legal Structure
- ANASTASiA is a **TOOL** that powers each OTA's tech stack natively
- Each OTA is an **ENTITY** — holds credentials, signs NDAs, has non-competes
- ANASTASiA accessing credentials to build SDK = OTA's own tooling using own credentials (not sharing)
- Credential ROUTING not SHARING — credentialed entity always executes the sale
- APAi owners (MYSTES KYRIOS LLC) cannot see anyone's credentials
- MYSTES is just another credentialed entity on APAi — not privileged

### Credential Routing Flow
1. Non-credentialed OTA needs to book via API they don't have credentials for
2. ANASTASiA routes the sale TO the credentialed entity
3. Credentialed entity technically executes the sale (no NDA violation)
4. ANASTASiA routes 70% margin back to entity that brought the retail customer
5. 30% stays with credentialed entity + $2-3 network fee
6. No laws broken — routing through a tool, not sharing logins between entities

### Why This Breaks the System
- Every APAi subscriber gets access to ANASTASiA (the tool)
- ANASTASiA has routing access to all credentials on the network
- Every OTA gets the REACH of every other OTA's credentials
- Without any entity "sharing" credentials with another entity
- ANASTASiA IS the moat — keeps credentials safe, opaque, legally compliant

## SDK Auto-Deploy Pipeline (AGREED)
1. Customer enters credentials through ANASTASiA admin portal
2. Credentials sent to APAi → Claude Opus uses credentials AS A TOOL (not entity)
3. Claude probes API, tests endpoints, maps schema, builds SDK client + knowledge card
4. Internal tests run against live API using customer's credentials
5. SDK deploys IMMEDIATELY across entire APAi network (not batched, not 24hr delay)
6. Customer's turnkey template is live with new API source active
7. All other APAi subscribers can now ROUTE through this API source

## Turnkey Template Dependency
- Template is REQUIRED for ANASTASiA — ANASTASiA doesn't exist without consumer-facing template
- OTA operator decides usage: consumer-facing automated OR manual travel agent booking
- We don't care how they use it — their business, their choice

## Product Separation (CONFIRMED)
- MYSTES = just another credentialed entity on APAi
- APAi = the tool/platform, separate deployment, $600/mo
- Separation is CRUCIAL — MYSTES can't be privileged or the legal structure breaks

## DISCUSSION CONTINUES — user was elaborating when prior session crashed
