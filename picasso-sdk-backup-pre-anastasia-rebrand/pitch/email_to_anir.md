# Email to Anir — SDK Pitch

## Subject Line Options (pick one):
1. "Developer tool for Redbox onboarding — can this help Servivuelo?"
2. "Built something during our integration — could be useful for Picasso agencies"
3. "Redbox Integration SDK — 2 months → 1 day for agency onboarding"

---

## Email Body:

Hi Anir,

Hope you're doing well. I wanted to share something we built during our Redbox integration that I think could be valuable for Picasso — especially with the Servivuelo migration underway.

**The problem we solved for ourselves:**
When we started integrating with the Redbox API, there was no documentation, no SDK, and the field mapping was entirely trial-and-error. It took us weeks of reverse engineering to get to our first search result.

**What we built:**
A complete Python SDK that wraps all 12 Redbox API endpoints — flight search, booking, fare rules, seatmaps, the works. Automated authentication (no more copying session tokens), correct field mapping built-in, structured error handling. A new agency can go from `pip install` to their first live search in under 5 minutes.

**Why this matters for Picasso:**
Every new agency going live on Cockpit/Redbox faces the same 2-month integration hurdle, and right now your dev teams are spending significant time hand-holding each agency through the same undocumented API — the same field mapping issues, the same session management, the same error codes. That's engineering talent burned on repetitive support instead of building product. With Servivuelo bringing 11,500+ agencies into the network, that cost only multiplies. With our SDK, you send each agency their auth key and a pip install command — they can all be onboarded and functioning the same day. Self-service. No support calls. All of them, in parallel.

I have a working demo I can walk through — it runs against the live API. Would you have 15 minutes this week to take a look? I also put together a one-page overview I can send over.

Happy to sign an NDA before sharing any technical details.

Best,
[Your name]
MYSTES KYRIOS LLC

---

## Follow-up if he asks "who should I loop in?":

"If there's someone on the product or engineering side who handles agency integrations or developer tools, they'd be the right person. Happy to do a technical demo for the dev team — I can show the SDK running live against the API."

## Follow-up if he asks for the one-pager:

Send the HTML one-pager (pitch/one-pager.html) — print to PDF first.
DO NOT send source code, the API reference, or technical architecture.

## Follow-up if he says "let me check internally":

"Of course! No rush. If it helps, here's a quick summary of what it covers:
- 12 API endpoints (all that work in production)
- Automated auth (Playwright + TOTP, no manual tokens)
- End-to-end booking (search → cart → PNR in one call)
- Field mapping (the contactData/apisDocument nesting that trips everyone up)

We're running our own OTA on it, so it's production-tested. Happy to do a live walkthrough whenever works."
