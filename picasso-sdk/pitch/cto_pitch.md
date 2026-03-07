# CTO / Dev Team Pitch — Talking Points

## Opening (30 seconds)

"We're a Picasso Travel partner running a live OTA on the Redbox API. During our integration, we discovered there's no SDK, no public docs, and no developer tools for the API. So we built them. We're offering this as a product to accelerate agency onboarding across the AERTiCKET network."

---

## The Problem (2 minutes)

**Ask the room:** "How long does it take a new agency to go live on Cockpit/Redbox?"

Then present the friction points:

1. **No API documentation** — Swagger returns 401, no public reference
2. **Undocumented field mapping** — `contactData.emailAddress` not `email`, `apisDocument` not top-level passport fields, `Male` not `MALE`
3. **Manual session management** — copy-paste cookies from browser
4. **Trial-and-error discovery** — agencies waste weeks finding that `pageNumber` is 1-indexed, the results key is `results` not `fareList`, booking requires at least one search filter
5. **No error reference** — `FARE_VERIFICATION_FAILED` means subscription issue, not auth issue

**Key stat:** "We probed 60+ Redbox endpoints. Only 12 work. Every agency discovers this the hard way."

---

## The Solution (3 minutes)

**Live demo** — run `demo_live.py` or show the recording.

Key moments to highlight:

1. **Setup** — "3 lines of code. pip install, create client, search flights."
2. **Airport search** — "Public endpoint, no auth. Works immediately."
3. **Flight search** — "One call, parsed results with pricing, segments, baggage, policies."
4. **Fare rules** — "16 categories of fare rules. HTML-formatted. One method call."
5. **Booking code** — "Show the `book_flight()` method. One call does cart + checkout + PNR."
6. **Auth** — "Session tokens managed automatically. No manual login. Persists across restarts."

**Don't show:** Source code, architecture diagrams, auth implementation details.

---

## Servivuelo Opportunity (1 minute)

*Only use this section when pitching to AERTiCKET/Servivuelo specifically.*

"Servivuelo joined the group in January 2025. That's 11,500 agencies that need to integrate with Cockpit/Redbox. At 2 months per agency with the current onboarding, that's years of migration work. With our SDK, you send each agency their auth key and a pip install command — they can all be onboarded and functioning the same day. Not one at a time. All of them. Simultaneously."

**Do the math in front of them:**
- 11,500 agencies × 2 months each = impossible to do sequentially
- With the SDK: send each agency an auth key + `pip install` — they **all go live the same day**
- It's not 1 agency per day. It's **all 11,500 in parallel**. Every agency installs independently.
- Every day an agency isn't integrated = bookings going to competitors

**The hidden cost:** "Right now you're paying dev teams to walk each agency through the same undocumented API — the same field mapping gotchas, the same session token issues, the same error codes with no reference. That's senior engineering talent burned on repetitive support instead of building product. The SDK eliminates that entire cost center. Agencies self-onboard. Your engineers build features."

---

## Business Model (1 minute)

Present two options (let them pick):

**Option A: Annual License**
- $75,000/year, group-wide deployment
- Includes updates, new endpoints, integration support
- Less than one developer's annual salary

**Option B: Per-Agency**
- $50-$100/agency/month
- Scales with your growth
- No upfront commitment

"Either way, the ROI is immediate. You're currently paying dev teams to hand-hold every agency through the same integration — explaining the same undocumented fields, the same session token issues, the same error codes. That's senior engineering salary burned on repetitive onboarding support. The SDK makes agencies self-service. Your engineers go back to building product. The annual license costs less than one month of one developer's time."

---

## Objection Handling

### "We can build this ourselves"
"Absolutely. You have a great dev team. The question is whether you want them spending 6 months on an SDK or 6 months building features for your agencies. We've already done the work — 60+ endpoints probed, every field mapped, every edge case handled. Buy vs. build."

### "How do we know it works?"
"We run a live OTA on it. Real bookings, real PNRs, real money. This isn't a prototype — it's production software."

### "What about security?"
"The SDK uses your credentials, your agency account, your session. We never see your tokens or bookings. It's a client library, not a proxy service."

### "What if you stop maintaining it?"
"Annual license includes source code escrow. If we disappear, you get the code. But we're actively building on this — our own business depends on it."

### "Can we see the source code?"
"After NDA and license agreement, absolutely. We're confident in the code quality because we use it ourselves every day."

### "Why should we pay when the API is free?"
"The API is free. The documentation, the field mapping, the auth automation, the error handling, and the 3 months of reverse engineering that went into this — that's what you're paying for."

---

## Close (30 seconds)

"I'd like to propose a 30-day pilot. Pick 5 of your agencies. We'll get them integrated in a week. If it works, we talk about a license. If it doesn't, you've lost nothing. Can we start next week?"

---

## Demo Recording Tips

1. **Terminal setup**: Dark background, large font (18pt+), clear prompt
2. **Narrate**: Talk through each step, don't just run the script silently
3. **Pause**: Let numbers sink in (airline count, fare count, pricing)
4. **Highlight**: Point out the parsed output — "Notice the SDK returns structured data, not raw JSON"
5. **Booking code**: Read it line by line, emphasize what the SDK handles vs. what the agency would have to figure out
6. **Time it**: Keep under 5 minutes total
7. **End on**: "pip install to first search result: under 5 minutes"

## Screen Recording on Mac
- Built-in: Shift+Cmd+5 → "Record Selected Portion"
- Or QuickTime Player → File → New Screen Recording
- Export as .mov or .mp4
