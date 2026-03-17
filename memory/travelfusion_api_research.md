# Travelfusion API Research Report
**Research Date:** 2026-03-09
**Researcher:** Claude Sonnet 4.5
**Purpose:** Technical evaluation for MYSTES flight booking integration

---

## Executive Summary

Travelfusion operates the world's largest Direct Connect GDS, offering access to 400+ LCC carriers and 55+ NDC full-service carriers. They provide two main API products: **tfFlight API** (flagship REST/JSON) and **Direct Connect XML API** (legacy but fully featured). The platform claims 412 airlines total, 99% booking success rate, and 3M monthly bookings.

**KEY FINDING:** Travelfusion is a mature, enterprise-grade aggregator with extensive LCC coverage including Ryanair, Spirit, and partnerships with major FSCs. However, documentation is gated behind partner login, and pricing appears to be custom/negotiated.

---

## 1. API Products & Endpoints

### 1.1 tfFlight API (Flagship Product)
- **Type:** REST/JSON (with XML fallback)
- **Description:** Modern flagship airline distribution platform used by leading OTAs, metas, and corporate enterprises
- **Features:**
  - Flight search, pricing, booking, ticketing
  - NDC content support where available
  - Industry-highest booking success rates (99%)
  - Proven scalability
  - Full post-booking support (change/cancel/void)
- **Base URL:** Not publicly documented (requires partner access)
- **Status:** PRIMARY RECOMMENDATION for new integrations

### 1.2 Direct Connect XML API
- **Type:** SOAP/XML over HTTPS POST
- **Description:** Legacy but fully-featured XML API with real-time availability
- **Base URLs:**
  - **Production:** `https://api.travelfusion.com/Xml`
  - **Test/Sandbox:** `https://xmltest.travelfusion.com/`
  - **Reports Portal:** `https://reports.travelfusion.com`
- **Required Namespace:** `xmlns="http://www.travelfusion.com/xml/api/simple"`
- **Features:**
  - 150+ airlines (subset of tfFlight's 412)
  - Real-time database availability
  - Fully automated booking processes
  - Rich set of functions
  - Versatile integration capabilities

### 1.3 Fast API (Lightweight Variant)
- **Type:** Lightweight XML/JSON/URL
- **Base URL:** `http://mirrorapi.travelfusion.com/api-v2/`
- **Description:** Designed for rapid integration with fast, small responses
- **Use Case:** Mobile services, widgets, minimal processing requirements
- **Protocols Supported:** XML (primary), JSON, JSONP, URL parameters
- **Note:** JSON/JSONP requires advance permission from Travelfusion

---

## 2. Authentication Flow

### 2.1 Login Process
1. **Initial Login Request:**
   ```xml
   POST https://api.travelfusion.com/Xml
   Content-Type: application/xml

   <LoginRequest xmlns="http://www.travelfusion.com/xml/api/simple">
     <username>YOUR_USERNAME</username>
     <password>YOUR_PASSWORD</password>
   </LoginRequest>
   ```

2. **Login Response:**
   - Returns authentication `token` (value varies per session)
   - Token valid for **12 hours**
   - Same token can be used for all requests across all users/sessions until expiration

3. **Token Usage:**
   - Add `token` attribute to top-level element of every subsequent request
   - Example: `<SearchRequest xmlns="..." token="sdjkr348573498">`

4. **Token Refresh:**
   - Submit new `LoginRequest` every 12 hours to obtain fresh token
   - No automatic refresh mechanism

### 2.2 Authentication Requirements
- **LoginId:** Represents the end user's Travelfusion account
- **XmlLoginId:** Represents the XML client account
- Both must be submitted with every XML request
- Credentials provided in initial welcome pack after signing agreements

### 2.3 Connection Requirements
- **HTTPS:** SSL required for all requests
- **HTTP Method:** POST (HTTP 1.0 or 1.1)
- **Encoding:** UTF-8
- **Compression:** GZip compression MUST be requested in all HTTP requests
- **Request Origin:** Mandatory `RequestOrigin` parameter identifying the source website

---

## 3. Search & Booking Flow

### 3.1 Core Request Types

#### Search Request (StartRoutingRequest)
```xml
<StartRoutingRequest xmlns="http://www.travelfusion.com/xml/api/simple" token="YOUR_TOKEN">
  <LoginId>YOUR_LOGIN_ID</LoginId>
  <XmlLoginId>YOUR_XML_LOGIN_ID</XmlLoginId>
  <Origin>
    <Type>airportcode</Type>
    <Descriptor>JFK</Descriptor>
  </Origin>
  <Destination>
    <Type>airportcode</Type>
    <Descriptor>LHR</Descriptor>
  </Destination>
  <OutwardDates>
    <DateOfSearch>27/11/2026-10:00</DateOfSearch>
  </OutwardDates>
  <TravellerList>
    <Traveller>
      <Age>30</Age>
    </Traveller>
  </TravellerList>
  <RequestOrigin>mystes.app</RequestOrigin>
  <IncrementalResults>true</IncrementalResults>
  <MaxChanges>2</MaxChanges>
  <MaxHops>2</MaxHops>
  <Timeout>60000</Timeout>
</StartRoutingRequest>
```

**Key Parameters:**
- **Origin/Destination:**
  - Airport-specific: `Type=airportcode`, `Descriptor=JFK`
  - City-wide: `Type=airportgroup`, `Descriptor=NYC`
- **OutwardDates:** Date format `DD/MM/YYYY-HH:MM`
- **TravellerList:** Age-based passenger specification
- **IncrementalResults:** MUST be `true`
- **MaxChanges/MaxHops:** Connection limits
- **RequestOrigin:** MANDATORY source website identifier

#### Booking Request
- Asynchronous process (background execution)
- Requires fare/flight selection from search results
- Split into multiple sub-requests internally
- Returns booking reference upon success

#### Post-Booking Operations
- **CancelRequest:** Cancel subset of travelers on booking
  - Splits original booking into two: `BookingChangeSucceeded` + `CancelSucceeded`
  - Asynchronous, submit once only
- **ChangeRequest:** Modify dates, flights, passengers
- **VoidRequest:** Void booking before ticketing
- **ManageBookingRequest:** Retrieve booking details

### 3.2 Optional Response Formats
- **XML (Default):** Standard response format
- **JSON:** Add `responseType="json"` to top-level element
- **JSONP:** Add `responseType="jsonp"` + `callback="functionName"`
- **Language:** Add `lang="sv"` (or other ISO codes) for localized responses

**IMPORTANT:** JSON/JSONP require advance permission from Travelfusion. XML is recommended.

---

## 4. Sandbox / Test Environment

### 4.1 Available Resources
- **Test Portal:** `https://xmltest.travelfusion.com/`
  - XML Test Tool for sending sample requests
  - Receive live responses during development
  - Login with Travelfusion username/password (NOT XmlLoginId)
- **Documentation Portals:**
  - `https://xmldocs.travelfusion.com/` (main XML docs, requires login)
  - `https://fastdocs.travelfusion.com/` (Fast API docs, requires login)
- **Reports Portal:** `https://reports.travelfusion.com` (check username in Administration section)

### 4.2 Testing Features
- **FakeBooking:** Test booking flow without actual airline transactions
- **Going Live Checklist:** Questionnaire to ensure proper integration choices
- **Support Email:** `apisupport@travelfusion.com` for technical issues

---

## 5. Carrier Coverage

### 5.1 Official Statistics
- **Total Airlines:** 412 (per corporate website)
- **Low-Cost Carriers (LCC):** 400+ with direct connections
- **NDC Full-Service Carriers:** 55+ (certified NDC API)
- **Consolidator Content:** Included in tfFlight API

### 5.2 Confirmed Major Carriers
- **LCC:** Ryanair, easyJet, Spirit Airlines, Eurowings, Flybe
- **FSC:** Air France, Lufthansa, British Airways, Qatar Airways, Emirates, Philippine Airlines, Brussels Airlines, Ruili Airlines, ZipAir
- **Partnership Note:** Ryanair partnership described as "landmark" / "Approved OTA Aggregator"

### 5.3 Coverage Details
- **Annual Booked Segments:** 150+ million
- **Monthly Bookings:** 3 million
- **Booking Success Rate:** 99%
- **Supported Currencies:** 27+

---

## 6. Request Format Details

### 6.1 XML Structure
- **Namespace:** `xmlns="http://www.travelfusion.com/xml/api/simple"` (REQUIRED)
- **Top-Level Attributes:**
  - `token` (authentication)
  - `lang` (optional, e.g., `"en"`, `"sv"`, `"es"`)
  - `responseType` (optional, `"json"` or `"jsonp"`)
  - `callback` (required if `responseType="jsonp"`)

### 6.2 Schema Files
- Available as `.xsd` files for select requests/responses
- XML guaranteed to be valid against latest schema versions
- Access via XML API Documentation portal

### 6.3 Best Practices
- **Every request MUST be user-initiated** (except polling and token refresh)
- Use GZip compression on all requests
- UTF-8 encoding required
- Refresh token before 12-hour expiration
- Submit same request only once (especially for bookings/cancellations)

---

## 7. Pricing Model

### 7.1 Pricing Structure
- **NOT publicly disclosed** — appears to be negotiated per partner
- **Merchant Fee:** 3-5% of airfare + taxes + credit card surcharge (varies by card type)
- **tfPay Settlement:** Travelfusion acts as Merchant of Record
  - Entitled to retain fees for payment processing and refunds
  - Possible transaction fees (configurable in merchant account)
- **Fare Quote Currency:** Configurable to preferred currency

### 7.2 Commercial Process
1. **Contact Sales:** `sales@travelfusion.com`
2. **Sign Commercial Agreement**
3. **Receive Credentials:** LoginId, XmlLoginId, username/password
4. **Onboarding:** Integration support, documentation access
5. **Testing Phase:** Use FakeBooking + sandbox
6. **Go-Live Checklist:** Complete questionnaire
7. **Production Activation**

---

## 8. Documentation Access

### 8.1 Public Resources (Limited)
- Corporate overview: `https://corporate.travelfusion.com/`
- Product pages: tfFlight, tfRail, tfHotel, tfNDC descriptions
- Supplier directory: Partial airline list
- Registration form: `/resources/register-customer-supplier`

### 8.2 Partner-Only Resources (Login Required)
- **XML API Docs:** `https://xmldocs.travelfusion.com/travelfusion-direct-connect-xml-api`
  - Connection Guide
  - Getting Started Guide
  - XML Request/Response Specifications
  - Search and Book API
  - Post Booking APIs (Cancellations, Changes, Manage)
  - Guidelines (Routes, Routing, Airports, Cities)
  - Hotel Booking API
  - Trains API
  - FAQ
- **Fast API Docs:** `https://fastdocs.travelfusion.com/`
- **Reports Portal:** `https://reports.travelfusion.com/`

### 8.3 Support Channels
- **Technical Support:** `apisupport@travelfusion.com`
- **Sales Inquiries:** `sales@travelfusion.com`
- **Helpdesk:** `https://helpdesk.travelfusion.com`

---

## 9. Additional Products (Beyond Flight API)

### 9.1 Other APIs
- **tfRail API:** Largest aggregated rail content (Europe, North America, China)
- **tfHotel API:** Comprehensive hotel content aggregation
- **tfNDC:** Certified NDC API (55+ carriers)

### 9.2 Value-Add Services
- **tfPay:** Payment and settlement solution (MoR model)
- **tfDesktop:** Distressed flight inventory aggregator
- **tfConnect:** (Details not disclosed)
- **tfCache:** (Details not disclosed)
- **tfOnlineCheckin:** Online check-in API integration
- **tfCFAR:** Cancel For Any Reason insurance integration
- **tfVPay:** Virtual payment solution
- **tfOneOrder:** IATA One Order support

---

## 10. Technical Comparison: tfFlight vs XML API

| Feature | tfFlight API | Direct Connect XML API |
|---------|-------------|------------------------|
| **Format** | REST/JSON (primary) | SOAP/XML |
| **Airlines** | 412 (LCC + NDC + FSC) | 150+ (legacy subset) |
| **Integration Speed** | Modern, SDKs available | Manual, XML schemas |
| **NDC Support** | Full NDC integration | Limited/indirect |
| **Booking Success** | 99% (industry-leading) | High (not specified) |
| **Post-Booking** | Full change/cancel/void | Full change/cancel/void |
| **Recommended For** | New integrations, scale | Legacy systems, XML-only |
| **Documentation** | Partner portal (login) | Partner portal (login) |
| **JSON Support** | Native | Optional (needs approval) |

**RECOMMENDATION:** tfFlight API is the clear choice for modern integrations. XML API is legacy maintenance mode.

---

## 11. Integration Checklist

### Before Starting Integration:
- [ ] Contact `sales@travelfusion.com` to initiate commercial discussion
- [ ] Sign commercial agreement
- [ ] Receive credentials (LoginId, XmlLoginId, username, password)
- [ ] Read ALL documentation (particularly Connection Guide, Getting Started)
- [ ] Set up test environment with sandbox endpoint
- [ ] Implement LoginRequest with 12-hour token refresh logic
- [ ] Implement GZip compression for all HTTP requests
- [ ] Set up HTTPS-only connections
- [ ] Configure RequestOrigin parameter with your domain

### During Integration:
- [ ] Test with XML Test Tool (`xmltest.travelfusion.com`)
- [ ] Use FakeBooking mode to test booking flow
- [ ] Implement proper error handling for token expiration
- [ ] Test multi-city, open-jaw, round-trip itineraries
- [ ] Test passenger age variations (infant, child, adult, senior)
- [ ] Test post-booking operations (cancel, change, manage)
- [ ] Verify currency handling and pricing display

### Before Go-Live:
- [ ] Complete "Going Live Check List" questionnaire
- [ ] Review integration with Travelfusion technical team
- [ ] Switch from sandbox to production endpoint
- [ ] Monitor first 50-100 bookings closely
- [ ] Set up automated token refresh (every 11 hours recommended)

---

## 12. Pros & Cons for MYSTES Integration

### PROS:
1. **Largest LCC coverage** (400+ carriers) — addresses MYSTES core value prop
2. **Includes Ryanair** (largest European LCC) via official partnership
3. **99% booking success** — critical for customer trust
4. **Mature platform** — 3M monthly bookings, 150M annual segments
5. **Direct connections** — not screen-scraping, not third-party aggregation
6. **Multi-POS capability** (27+ currencies) — supports arbitrage model
7. **Post-booking support** — change/cancel/void APIs for customer service
8. **NDC support** — future-proof as airlines migrate off GDS

### CONS:
1. **Documentation gated** — requires commercial agreement before full specs
2. **Pricing not transparent** — must negotiate custom rates
3. **No self-service signup** — sales cycle required
4. **Token refresh complexity** — 12-hour expiration needs automation
5. **XML-first architecture** — JSON support requires permission, not first-class
6. **Enterprise-grade overhead** — likely overkill for MVP/Phase 1
7. **Unknown POS flexibility** — unclear if they support per-request market switching like Picasso
8. **Settlement model** — tfPay MoR may complicate MYSTES platform fee model

### RISK ASSESSMENT:
- **HIGH BARRIER TO ENTRY:** Requires commercial agreement, likely minimum volume commitments
- **INTEGRATION COMPLEXITY:** XML API is heavyweight; tfFlight API docs not publicly available
- **PRICING UNCERTAINTY:** No published rates; could be prohibitively expensive for startup
- **POS ARBITRAGE SUPPORT:** NOT CONFIRMED — Travelfusion may enforce single POS per account (dealbreaker for MYSTES)

---

## 13. Comparison to Current MYSTES Stack

| Feature | Picasso Travel (Current) | Travelfusion |
|---------|-------------------------|--------------|
| **LCC Coverage** | Limited (Amadeus-based) | 400+ direct LCC |
| **POS Markets** | 102 countries confirmed | 27+ currencies (unclear if per-request switching) |
| **Pricing** | $500/month flat | Custom/negotiated (likely higher) |
| **Arbitrage Support** | CONFIRMED (core feature) | UNKNOWN (not documented) |
| **Self-Service** | Yes (sandbox granted) | No (sales cycle required) |
| **Integration Status** | LIVE (Build #119-125) | Not started |
| **Documentation** | Reverse-engineered + partnership | Gated behind login |
| **Booking Success** | Unknown | 99% (claimed) |

**STRATEGIC RECOMMENDATION:**
Travelfusion is a **premium LCC aggregator** but may NOT support the per-request POS switching that MYSTES requires for arbitrage. Before pursuing integration:

1. **EMAIL SALES/API SUPPORT:** Explicitly ask if they support per-request POS market selection (e.g., "Can I search the same route from Denmark POS in one request, then Spain POS in another?")
2. **REQUEST PRICING:** Ask for startup/small-volume pricing tiers
3. **EVALUATE REDUNDANCY:** Given Picasso already provides 102-POS consolidator access + Amadeus SERP under the hood, Travelfusion may be redundant unless it unlocks carriers Picasso doesn't have

**PRIORITY:** MEDIUM — Evaluate as a Phase 2 LCC supplement if Picasso's carrier coverage proves insufficient.

---

## 14. Next Steps

### Immediate Actions:
1. **Contact Travelfusion:**
   - Email: `sales@travelfusion.com` + `apisupport@travelfusion.com`
   - Subject: "POS Market Switching Support Inquiry - OTA Arbitrage Platform"
   - Key Questions:
     - Does tfFlight/XML API support per-request POS market selection?
     - What's the pricing model for low-volume startups (<100 bookings/month)?
     - Can we access demo/test credentials before signing commercial agreement?
     - Which airlines/routes support multi-POS pricing in your system?
     - Do you have any OTA partners using your API for price arbitrage?

2. **Archive This Report:**
   - Save to `memory/travelfusion_api_research.md`
   - Reference in `CLAUDE_CONTEXT.md` under "API Evaluations"

3. **Update Decision Log:**
   - Add Travelfusion to Phase 2 evaluation backlog
   - Priority: MEDIUM (after Picasso proves limitations)

### Long-Term Considerations:
- If Travelfusion confirms POS switching support + reasonable pricing → pilot integration
- If Travelfusion CANNOT support arbitrage → SKIP (incompatible with MYSTES model)
- If Picasso proves sufficient → Travelfusion becomes redundant backup

---

## 15. Sources

All information sourced from web research conducted 2026-03-09:

- [Travelfusion Corporate - XML API Resources](https://corporate.travelfusion.com/resources/xml-api)
- [tfFlight API Product Page](https://corporate.travelfusion.com/products-services/tf-flight-api)
- [Fast API Documentation - Connection Guide](https://fastdocs.travelfusion.com/connection-guide)
- [Travelfusion XML API Documentation Portal](https://xmldocs.travelfusion.com/travelfusion-direct-connect-xml-api)
- [Travelfusion Test Portal](https://xmltest.travelfusion.com/)
- [Travelfusion Getting Started Guide](https://xmldocs.travelfusion.com/travelfusion-direct-connect-xml-api/getting-started-guide)
- [Travelfusion Search and Book API Docs](https://xmldocs.travelfusion.com/travelfusion-direct-connect-xml-api/search-and-book-api)
- [Travelfusion Cancellations API Docs](https://xmldocs.travelfusion.com/travelfusion-direct-connect-xml-api/post-booking-apis/cancellations-api)
- [Travelfusion Post Booking APIs](https://xmldocs.travelfusion.com/travelfusion-direct-connect-xml-api/post-booking-apis)
- [Travelfusion Corporate - All Suppliers List](https://corporate.travelfusion.com/resources/all-suppliers)
- [Ryanair Partnership Announcement](https://corporate.ryanair.com/news/ryanair-announces-partnership-with-travelfusion-the-worlds-largest-flight-aggregator/)
- [Business Travel News - Ryanair-Travelfusion Deal](https://www.businesstravelnewseurope.com/TMC-Distribution/Ryanair-agrees-landmark-deal-with-Travelfusion)
- [SAP Concur - Travelfusion LCC Bookings](https://www.concur.com/app-center/listings/550353cc99066b13221bce29)

---

**Report Compiled By:** Claude Sonnet 4.5
**For:** MYSTES KYRIOS LLC / ANASTASiA Platform Evaluation
**Date:** 2026-03-09
**Status:** READY FOR DECISION-MAKER REVIEW
