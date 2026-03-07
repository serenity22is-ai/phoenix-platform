# ANASTASiA — Product Card

> AI flight booking agent + OTA platform for travel agencies
> By MYSTES KYRIOS LLC

## The Problem
Travel agencies on consolidator platforms (Picasso, AERTiCKET, etc.) face:
- **2.5 months** average onboarding time
- **$3,500** training course fees
- **Undocumented APIs** with zero developer resources
- **Manual GDS terminal operations** requiring trained agents
- **No after-hours booking capability**

## The Solution
ANASTASiA is a hosted AI agent that automates the entire flight booking workflow:
- Natural language in, structured results back
- Search 102 countries of POS simultaneously
- Book flights, manage bookings, generate documents
- 24/7 operation, no human bottleneck
- Same-day integration (vs 2.5 months)

## What's Inside
- **12 Redbox API endpoints** fully integrated (reverse-engineered from undocumented API)
- **16 AI tools** for the booking agent (search, fare rules, seatmap, booking, document generation)
- **Auto-login system** (Playwright + TOTP, no manual token management)
- **Billing engine** (Stripe, 3 tiers, usage tracking)
- **Admin dashboard** (7-tab config: pricing, display, branding, features, analytics, billing)
- **Consumer UI template** (white-label OTA for Enterprise tier)
- **Auto-heal daemon** (monitors and recovers from API failures)

## Live Demo
- **API**: https://anastasia-api.onrender.com
- **Health**: https://anastasia-api.onrender.com/api/v1/health
- **Signup**: https://anastasia-api.onrender.com/signup

## Target Market
**AERTiCKET Group** — EUR 3.5B revenue, 130,000+ agencies across 25 subsidiaries
- Pilot: Servivuelos (Spain) — 11,500 agencies
- All subsidiaries run the same Cockpit/Redbox platform
- ANASTASiA replaces human travel agents at GDS terminals

## Revenue Model
| Channel | Pricing |
|---------|---------|
| Retail (direct) | $249 / $599 / $1,499 per month |
| Wholesale (consolidator resale) | $99 / $249 / $599 per month |
| Partner (platform license) | $99-$299 per agency/month (volume-committed) |

**Full AERTiCKET rollout (130K agencies)**: $12.87M/month = **$154M/year**

## Competitive Moat
1. Only automated Redbox authentication system in existence
2. Only comprehensive Redbox API documentation (60+ endpoints probed, 12 confirmed)
3. 6+ year head start over AERTiCKET's own development
4. Battle-tested in production (MYSTES consumer OTA)
5. AI knowledge base with every API quirk documented

## Tech Stack
Python 3.11 | Flask | Claude Opus 4.6 | Stripe | Docker | Render | Playwright + TOTP
