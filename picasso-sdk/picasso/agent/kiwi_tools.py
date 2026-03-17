"""
Kiwi Tequila Tool Definitions — Claude function calling schemas.

Each tool maps 1:1 to a KiwiTequilaClient method. The agent orchestrator
routes Claude's kiwi_* tool_use blocks to the corresponding SDK calls.

Tool names are prefixed with "kiwi_" to distinguish from Redbox/Duffel tools.
All three toolsets can be active simultaneously for multi-source searches.

MYSTES KYRIOS LLC — Confidential.
"""

KIWI_TOOL_DEFINITIONS = [
    {
        "name": "kiwi_search_places",
        "description": "Autocomplete airports and cities by name via Kiwi Tequila. Use this to resolve city names to IATA airport codes. Returns airports and cities matching the query.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Airport name, city name, or IATA code (e.g., 'New York', 'JFK', 'London')"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "kiwi_search_flights",
        "description": "Search for flights via Kiwi Tequila API (750+ carriers including virtual interlining). Kiwi's unique feature is virtual interlining — combining carriers that don't normally work together into single itineraries. Returns booking_tokens required for booking.",
        "input_schema": {
            "type": "object",
            "properties": {
                "origin": {
                    "type": "string",
                    "description": "Origin airport IATA code (e.g., 'JFK')"
                },
                "destination": {
                    "type": "string",
                    "description": "Destination airport IATA code (e.g., 'LAX')"
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
                    "description": "Number of child passengers aged 2-11 (default: 0)",
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
                "max_results": {
                    "type": "integer",
                    "description": "Maximum results to return (default: 30)",
                    "default": 30
                },
                "nonstop_only": {
                    "type": "boolean",
                    "description": "Only return non-stop (direct) flights",
                    "default": False
                }
            },
            "required": ["origin", "destination", "departure_date"]
        }
    },
    {
        "name": "kiwi_check_flights",
        "description": "Validate a Kiwi flight itinerary and check current pricing. Must be called within 30 minutes of search. Returns whether the flight is still available and if the price has changed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "booking_token": {
                    "type": "string",
                    "description": "The booking_token from kiwi_search_flights results"
                },
                "bags": {
                    "type": "integer",
                    "description": "Number of checked bags (default: 0)",
                    "default": 0
                },
                "adults": {
                    "type": "integer",
                    "description": "Number of adult passengers (default: 1)",
                    "default": 1
                }
            },
            "required": ["booking_token"]
        }
    },
    {
        "name": "kiwi_book_flight",
        "description": "Book a flight via Kiwi Tequila. Creates a booking with passenger details. CRITICAL: Always confirm with the user before calling — bookings create real reservations. Must call kiwi_check_flights first to validate availability.",
        "input_schema": {
            "type": "object",
            "properties": {
                "booking_token": {
                    "type": "string",
                    "description": "The booking_token from search results"
                },
                "session_id": {
                    "type": "string",
                    "description": "Session ID from kiwi_check_flights response"
                },
                "passengers": {
                    "type": "array",
                    "description": "List of passenger details",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "First name (must match passport/ID)"
                            },
                            "surname": {
                                "type": "string",
                                "description": "Last name (must match passport/ID)"
                            },
                            "birthday": {
                                "type": "string",
                                "description": "Date of birth in DD/MM/YYYY format"
                            },
                            "nationality": {
                                "type": "string",
                                "description": "Country code (e.g., 'US')"
                            },
                            "category": {
                                "type": "string",
                                "enum": ["adult", "child", "infant"],
                                "description": "Passenger category"
                            },
                            "email": {
                                "type": "string",
                                "description": "Contact email"
                            },
                            "phone": {
                                "type": "string",
                                "description": "Phone with country code"
                            },
                            "cardno": {
                                "type": "string",
                                "description": "Passport/ID number (required for international)"
                            },
                            "expiration": {
                                "type": "string",
                                "description": "Passport expiry in DD/MM/YYYY"
                            }
                        },
                        "required": ["name", "surname", "birthday", "nationality", "category", "email", "phone"]
                    }
                },
                "bags": {
                    "type": "integer",
                    "description": "Number of checked bags (default: 0)",
                    "default": 0
                }
            },
            "required": ["booking_token", "session_id", "passengers"]
        }
    },
    {
        "name": "kiwi_confirm_payment",
        "description": "Confirm payment for a Kiwi booking. Must be called within 30 minutes of save_booking. Returns booking confirmation status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "booking_id": {
                    "type": "integer",
                    "description": "Booking ID from kiwi_book_flight response"
                },
                "transaction_id": {
                    "type": "string",
                    "description": "Transaction ID from kiwi_book_flight response"
                }
            },
            "required": ["booking_id", "transaction_id"]
        }
    },
]
