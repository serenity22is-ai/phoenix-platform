"""
AirGateway NDC Tool Definitions — Claude function calling schemas.

Each tool maps 1:1 to an AirGatewayClient method. Prefixed with "agw_"
to distinguish from Redbox/Duffel/Kiwi tools.

11 tools covering the full NDC lifecycle:
    Search → Verify → Book (instant/hold) → Poll → Retrieve → Cancel
    Seats → Services → Issue Ticket → Refund → Change/Reprice

MYSTES KYRIOS LLC — Confidential.
"""

AIRGATEWAY_TOOL_DEFINITIONS = [
    {
        "name": "agw_search_flights",
        "description": "Search for flights via AirGateway NDC (25+ airlines direct + AERTiCKET consolidator). Supports POS country switching for geographic arbitrage. Connected airlines include AA, BA, LH, AF, KL, EK, IB, QF, SQ, AY, AV, A3.",
        "input_schema": {
            "type": "object",
            "properties": {
                "origin": {
                    "type": "string",
                    "description": "Origin airport IATA code (e.g., 'JFK')"
                },
                "destination": {
                    "type": "string",
                    "description": "Destination airport IATA code (e.g., 'LHR')"
                },
                "departure_date": {
                    "type": "string",
                    "description": "Departure date in YYYY-MM-DD format"
                },
                "return_date": {
                    "type": "string",
                    "description": "Return date in YYYY-MM-DD format (omit for one-way)"
                },
                "adults": {
                    "type": "integer",
                    "description": "Number of adult passengers (default: 1)",
                    "default": 1
                },
                "children": {
                    "type": "integer",
                    "description": "Number of child passengers 2-11 (default: 0)",
                    "default": 0
                },
                "infants": {
                    "type": "integer",
                    "description": "Number of infant passengers under 2 (default: 0)",
                    "default": 0
                },
                "cabin_class": {
                    "type": "string",
                    "enum": ["economy", "premium_economy", "business", "first"],
                    "description": "Cabin class (default: economy)",
                    "default": "economy"
                },
                "nonstop": {
                    "type": "boolean",
                    "description": "Direct flights only",
                    "default": False
                },
                "providers": {
                    "type": "string",
                    "description": "Airline IATA codes comma-separated, or '*' for all. NDC-direct: A3,AA,AF,AV,AY,BA,EK,IB,KL,LH,QF,SQ. Non-NDC codes routed via AERTiCKET GDS.",
                    "default": "*"
                },
                "country": {
                    "type": "string",
                    "description": "POS country code for geographic arbitrage (e.g., 'DK', 'ES', 'US'). European POS often cheaper for transatlantic.",
                    "default": "US"
                },
                "currency": {
                    "type": "string",
                    "description": "Currency code (default: USD)",
                    "default": "USD"
                }
            },
            "required": ["origin", "destination", "departure_date"]
        }
    },
    {
        "name": "agw_verify_price",
        "description": "Verify current pricing for an AirGateway flight offer before booking. ALWAYS call this between search and booking — NDC fares are live and prices change. Checks session validity automatically.",
        "input_schema": {
            "type": "object",
            "properties": {
                "shopping_response_id": {
                    "type": "string",
                    "description": "ShoppingResponseID from search results"
                },
                "offer_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of offer IDs to verify pricing for"
                }
            },
            "required": ["shopping_response_id", "offer_ids"]
        }
    },
    {
        "name": "agw_create_order",
        "description": "Book a flight via AirGateway NDC. Creates an order with passenger details. Supports instant purchase and hold/reserve modes. CRITICAL: Confirm with user before calling — this creates a real booking.",
        "input_schema": {
            "type": "object",
            "properties": {
                "shopping_response_id": {
                    "type": "string",
                    "description": "ShoppingResponseID from search/price verification"
                },
                "passengers": {
                    "type": "array",
                    "description": "List of passenger details",
                    "items": {
                        "type": "object",
                        "properties": {
                            "nameGiven": {"type": "string", "description": "First name (must match passport)"},
                            "surname": {"type": "string", "description": "Last name"},
                            "nameTitle": {"type": "string", "description": "Title: MR, MRS, MS, MISS (UPPERCASE)"},
                            "gender": {"type": "string", "enum": ["Male", "Female"]},
                            "birthdate": {"type": "string", "description": "Date of birth YYYY-MM-DD"},
                            "passengerType": {"type": "string", "enum": ["ADT", "CHD", "INF"], "description": "ADT=adult, CHD/CNN=child, INF=infant"},
                            "emailContact": {"type": "string", "description": "Contact email"},
                            "phone": {"type": "string", "description": "Phone with country code"},
                            "travelerReference": {"type": "string", "description": "Reference: T1, T2, T3..."},
                            "countryCode": {"type": "string", "description": "Nationality ISO code (optional, for international)"},
                            "documentNumber": {"type": "string", "description": "Passport number (optional, for international)"},
                            "documentExpiry": {"type": "string", "description": "Passport expiry YYYY-MM-DD (optional)"},
                        },
                        "required": ["nameGiven", "surname", "nameTitle", "gender", "birthdate", "passengerType", "emailContact", "phone", "travelerReference"]
                    }
                },
                "payment_method": {
                    "type": "string",
                    "enum": ["card", "cash", "ms"],
                    "description": "Payment method: cash (agency settlement, default), card (credit card), ms (merchant settlement)",
                    "default": "cash"
                },
                "hold_mode": {
                    "type": "boolean",
                    "description": "Reserve fare without payment. Hold window varies by airline (typically 24-72 hours). Not all airlines support holds.",
                    "default": False
                },
                "fake_ticket": {
                    "type": "boolean",
                    "description": "Sandbox only — creates test booking without contacting airline. For development/testing only.",
                    "default": False
                }
            },
            "required": ["shopping_response_id", "passengers"]
        }
    },
    {
        "name": "agw_retrieve_order",
        "description": "Retrieve details of an existing AirGateway booking by order ID. Returns current status, PNR, tickets, and passenger details.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "AirGateway order ID"},
                "owner": {"type": "string", "description": "Airline owner code (optional)"}
            },
            "required": ["order_id"]
        }
    },
    {
        "name": "agw_cancel_order",
        "description": "Cancel an AirGateway booking. Use type 'void' for immediate void (within void window, penalty-free), 'cancel' for cancellation with potential penalties/refund.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "AirGateway order ID"},
                "cancel_type": {"type": "string", "enum": ["void", "cancel"], "default": "void", "description": "void = penalty-free within window, cancel = with potential penalties"}
            },
            "required": ["order_id"]
        }
    },
    {
        "name": "agw_poll_order",
        "description": "Poll for async booking confirmation. Some airlines confirm asynchronously — OrderCreate returns 'pending' and PNR/ticket arrives later. Poll every 5-10 seconds, timeout after 2 minutes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "AirGateway order ID"},
                "owner": {"type": "string", "description": "Airline owner code (optional)"}
            },
            "required": ["order_id"]
        }
    },
    {
        "name": "agw_issue_ticket",
        "description": "Issue e-ticket for a confirmed AirGateway booking (AirDocIssue). For NDC-direct airlines, issues via airline system. For AERTiCKET GDS content, AERTiCKET issues on their IATA plate. Call after OrderCreate confirms. Some airlines auto-ticket.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "AirGateway order ID"}
            },
            "required": ["order_id"]
        }
    },
    {
        "name": "agw_get_seats",
        "description": "Get available seat map for an AirGateway booking. Shows seat layout with pricing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "AirGateway order ID"}
            },
            "required": ["order_id"]
        }
    },
    {
        "name": "agw_get_services",
        "description": "Get available ancillary services (baggage, meals, lounge, etc.) for an AirGateway booking.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "AirGateway order ID"}
            },
            "required": ["order_id"]
        }
    },
    {
        "name": "agw_reshop_refund",
        "description": "Request refund quote for an AirGateway booking (OrderReshopRefund). Returns refund amount, penalties, and fare rules. Use to check refundability before cancelling.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "AirGateway order ID"}
            },
            "required": ["order_id"]
        }
    },
    {
        "name": "agw_reshop_reprice",
        "description": "Request date/flight change pricing for an AirGateway booking (OrderReshopReprice). Returns price difference and change fees for voluntary modifications.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "AirGateway order ID"}
            },
            "required": ["order_id"]
        }
    },
]
