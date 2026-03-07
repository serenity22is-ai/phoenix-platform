"""
Tool Definitions — Claude function calling schemas for each SDK method.

Each tool maps 1:1 to a RedboxClient method. The agent orchestrator
routes Claude's tool_use blocks to the corresponding SDK calls.

MYSTES KYRIOS LLC — Confidential.
"""

TOOL_DEFINITIONS = [
    {
        "name": "search_airports",
        "description": "Search for airports by name, city, or IATA code. This is a public endpoint that requires no authentication. Use this to resolve city names to airport codes before searching flights.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Airport name, city name, or IATA code to search for (e.g., 'New York', 'JFK', 'London Heathrow')"
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 10)",
                    "default": 10
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "search_flights",
        "description": "Search for available flights between two airports. Returns a fare_search_id (required for all subsequent operations like pagination, fare rules, and booking) and a list of parsed flight results with pricing, segments, baggage, and policies.",
        "input_schema": {
            "type": "object",
            "properties": {
                "origin": {
                    "type": "string",
                    "description": "Origin airport IATA code (e.g., 'JFK', 'LAX')"
                },
                "destination": {
                    "type": "string",
                    "description": "Destination airport IATA code (e.g., 'LHR', 'CDG')"
                },
                "departure_date": {
                    "type": "string",
                    "description": "Departure date in YYYY-MM-DD format"
                },
                "return_date": {
                    "type": "string",
                    "description": "Return date in YYYY-MM-DD format for round-trip flights. Omit for one-way."
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
                    "enum": ["ECONOMY", "PREMIUM_ECONOMY", "BUSINESS", "FIRST"],
                    "description": "Cabin class (default: ECONOMY)",
                    "default": "ECONOMY"
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum results to return, up to 50 (default: 20)",
                    "default": 20
                },
                "nonstop_only": {
                    "type": "boolean",
                    "description": "Only return non-stop flights (default: false)",
                    "default": False
                }
            },
            "required": ["origin", "destination", "departure_date"]
        }
    },
    {
        "name": "get_search_results",
        "description": "Fetch additional pages of results from an existing flight search, with optional sorting and filtering. Requires the fare_search_id from a previous search_flights call.",
        "input_schema": {
            "type": "object",
            "properties": {
                "fare_search_id": {
                    "type": "string",
                    "description": "The fare_search_id from a previous search_flights result"
                },
                "page_number": {
                    "type": "integer",
                    "description": "Page number to fetch (1-indexed, default: 1)",
                    "default": 1
                },
                "results_per_page": {
                    "type": "integer",
                    "description": "Number of results per page, up to 50 (default: 20)",
                    "default": 20
                },
                "sorting_criteria": {
                    "type": "string",
                    "description": "Sort results by criteria (e.g., 'PRICE')"
                },
                "filter_criteria": {
                    "type": "object",
                    "description": "Filter criteria to narrow results (e.g., by airline, stops, time)"
                }
            },
            "required": ["fare_search_id"]
        }
    },
    {
        "name": "get_fare_rules",
        "description": "Retrieve detailed fare rules for a specific flight fare. Returns structured rules by category including penalties, cancellation policy, rebooking rules, advance purchase requirements, and more. Rules are HTML-formatted.",
        "input_schema": {
            "type": "object",
            "properties": {
                "fare_search_id": {
                    "type": "string",
                    "description": "The fare_search_id from the search that produced this fare"
                },
                "fare_id": {
                    "type": "string",
                    "description": "The fare_id of the specific flight to get rules for"
                }
            },
            "required": ["fare_search_id", "fare_id"]
        }
    },
    {
        "name": "get_seatmap",
        "description": "Retrieve the seatmap for a specific flight showing available, occupied, and blocked seats. Requires individual flight segment details (not fare-level).",
        "input_schema": {
            "type": "object",
            "properties": {
                "airline_code": {
                    "type": "string",
                    "description": "Marketing airline IATA code (e.g., 'AA', 'DL', 'UA')"
                },
                "flight_number": {
                    "type": "string",
                    "description": "Flight number without airline prefix (e.g., '1758')"
                },
                "departure": {
                    "type": "string",
                    "description": "Departure airport IATA code"
                },
                "destination": {
                    "type": "string",
                    "description": "Destination airport IATA code"
                },
                "departure_date": {
                    "type": "string",
                    "description": "Departure date in YYYY-MM-DD format"
                },
                "booking_class": {
                    "type": "string",
                    "description": "GDS booking class code (e.g., 'Y', 'B', 'M'). Found in segment data.",
                    "default": "Y"
                },
                "cabin_class": {
                    "type": "string",
                    "enum": ["ECONOMY", "PREMIUM_ECONOMY", "BUSINESS", "FIRST"],
                    "description": "Cabin class (default: ECONOMY)",
                    "default": "ECONOMY"
                }
            },
            "required": ["airline_code", "flight_number", "departure", "destination", "departure_date"]
        }
    },
    {
        "name": "book_flight",
        "description": "Book a flight end-to-end. This is the high-level booking method that orchestrates: adding flight + passengers to cart, checking out, and creating the booking (SuperPNR). Returns PNR on success. IMPORTANT: Always confirm with the user before calling this — bookings may be non-refundable.",
        "input_schema": {
            "type": "object",
            "properties": {
                "fare_search_id": {
                    "type": "string",
                    "description": "The fare_search_id from the search that found this flight"
                },
                "fare_id": {
                    "type": "string",
                    "description": "The fare_id of the selected flight"
                },
                "passengers": {
                    "type": "array",
                    "description": "List of passenger objects with booking details",
                    "items": {
                        "type": "object",
                        "properties": {
                            "firstName": {
                                "type": "string",
                                "description": "Passenger first name (must match ID/passport)"
                            },
                            "lastName": {
                                "type": "string",
                                "description": "Passenger last name (must match ID/passport)"
                            },
                            "paxType": {
                                "type": "string",
                                "enum": ["ADT", "CHD", "INF"],
                                "description": "Passenger type: ADT (adult), CHD (child 2-11), INF (infant under 2)"
                            },
                            "dateOfBirth": {
                                "type": "string",
                                "description": "Date of birth in YYYY-MM-DD format"
                            },
                            "gender": {
                                "type": "string",
                                "enum": ["Male", "Female"],
                                "description": "Gender — must be exactly 'Male' or 'Female' (capitalized)"
                            },
                            "title": {
                                "type": "string",
                                "description": "Title: MR, MRS, MS, MISS"
                            },
                            "email": {
                                "type": "string",
                                "description": "Contact email address"
                            },
                            "phone": {
                                "type": "string",
                                "description": "Contact phone number with country code (e.g., +12125551234)"
                            },
                            "passportNumber": {
                                "type": "string",
                                "description": "Passport number (required for international flights)"
                            },
                            "passportExpiry": {
                                "type": "string",
                                "description": "Passport expiry date in YYYY-MM-DD format"
                            },
                            "nationality": {
                                "type": "string",
                                "description": "Nationality country code (e.g., 'US', 'GB', 'DE')"
                            }
                        },
                        "required": ["firstName", "lastName", "paxType"]
                    }
                },
                "order_tickets": {
                    "type": "boolean",
                    "description": "Issue tickets immediately after booking (default: true). Set false to create PNR without ticketing.",
                    "default": True
                },
                "markup_amount": {
                    "type": "number",
                    "description": "Agency markup fee in USD to add to ticket price (0-999, default: 0)",
                    "default": 0
                }
            },
            "required": ["fare_search_id", "fare_id", "passengers"]
        }
    },
    {
        "name": "search_bookings",
        "description": "Search existing bookings (SuperPNRs) by various criteria. At least one search parameter is required. Returns booking summaries with PNR, status, route, and pricing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "locator": {
                    "type": "string",
                    "description": "PNR / record locator to look up"
                },
                "departure": {
                    "type": "string",
                    "description": "Departure airport IATA code"
                },
                "destination": {
                    "type": "string",
                    "description": "Destination airport IATA code"
                },
                "airline": {
                    "type": "string",
                    "description": "Validating airline IATA code"
                },
                "date_from": {
                    "type": "string",
                    "description": "Booking creation date from (YYYY-MM-DD)"
                },
                "date_to": {
                    "type": "string",
                    "description": "Booking creation date to (YYYY-MM-DD)"
                },
                "travel_date_from": {
                    "type": "string",
                    "description": "Travel date from (YYYY-MM-DD)"
                },
                "travel_date_to": {
                    "type": "string",
                    "description": "Travel date to (YYYY-MM-DD)"
                }
            }
        }
    },
    {
        "name": "generate_document",
        "description": "Generate a travel document (PDF or email) for a booking or offer. Use after booking to create confirmation documents, or before booking to create itinerary/offer documents.",
        "input_schema": {
            "type": "object",
            "properties": {
                "document_type": {
                    "type": "string",
                    "enum": ["ITINERARY", "OFFER", "CONFIRMATION", "TRAVEL_REGISTRATION"],
                    "description": "Type of document to generate"
                },
                "super_pnr_id": {
                    "type": "string",
                    "description": "SuperPNR ID for post-booking documents (CONFIRMATION)"
                },
                "shopping_cart_id": {
                    "type": "string",
                    "description": "Shopping cart ID for pre-booking documents (ITINERARY, OFFER)"
                },
                "fare_search_id": {
                    "type": "string",
                    "description": "Search ID for offer documents"
                },
                "fare_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Fare IDs to include in offer documents"
                },
                "display_prices": {
                    "type": "boolean",
                    "description": "Show prices in the document (default: true)",
                    "default": True
                },
                "language": {
                    "type": "string",
                    "description": "Document language ISO code (default: 'en')",
                    "default": "en"
                },
                "email_recipients": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Email addresses to send the document to"
                }
            },
            "required": ["document_type"]
        }
    },
    {
        "name": "search_profiles",
        "description": "Search for saved traveler profiles by name. Useful for quickly populating passenger details for repeat travelers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "search_term": {
                    "type": "string",
                    "description": "Name or identifier to search for"
                }
            },
            "required": ["search_term"]
        }
    },
    {
        "name": "get_shopping_cart",
        "description": "Retrieve the current shopping cart contents. Useful for checking what's in the cart before proceeding with booking.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_extras",
        "description": "Discover available extras for a flight fare — travel insurance plans, ancillary services (baggage, meals, priority boarding, lounge access), and seat availability. Call this after a flight search when the user wants to add insurance, buy extra baggage, or select seats. Requires the fare_search_id and fare_id from search results.",
        "input_schema": {
            "type": "object",
            "properties": {
                "fare_search_id": {
                    "type": "string",
                    "description": "The fare_search_id from the search that produced this fare"
                },
                "fare_id": {
                    "type": "string",
                    "description": "The fare_id of the flight to get extras for"
                }
            },
            "required": ["fare_search_id", "fare_id"]
        }
    },
    {
        "name": "book_flight_with_extras",
        "description": "Book a flight with optional insurance, ancillary services (baggage, meals), and seat selections included. This is the enhanced booking method that handles everything in one cart: flight + passengers + insurance + ancillaries + seats + agency markup. IMPORTANT: Always confirm with the user before calling — bookings may be non-refundable. Use get_extras() first to discover available options.",
        "input_schema": {
            "type": "object",
            "properties": {
                "fare_search_id": {
                    "type": "string",
                    "description": "The fare_search_id from the search"
                },
                "fare_id": {
                    "type": "string",
                    "description": "The fare_id of the selected flight"
                },
                "passengers": {
                    "type": "array",
                    "description": "List of passenger objects (same format as book_flight)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "firstName": {"type": "string"},
                            "lastName": {"type": "string"},
                            "paxType": {"type": "string", "enum": ["ADT", "CHD", "INF"]},
                            "dateOfBirth": {"type": "string"},
                            "gender": {"type": "string", "enum": ["Male", "Female"]},
                            "title": {"type": "string"},
                            "email": {"type": "string"},
                            "phone": {"type": "string"},
                            "passportNumber": {"type": "string"},
                            "passportExpiry": {"type": "string"},
                            "nationality": {"type": "string"},
                            "frequentFlyerNumber": {"type": "string", "description": "Loyalty program number"},
                            "frequentFlyerAirline": {"type": "string", "description": "Airline code for FF program"}
                        },
                        "required": ["firstName", "lastName", "paxType"]
                    }
                },
                "insurance": {
                    "type": "object",
                    "description": "Insurance selection from get_extras() results",
                    "properties": {
                        "insurance_id": {
                            "type": "string",
                            "description": "Insurance option ID from get_extras()"
                        },
                        "plan_name": {
                            "type": "string",
                            "description": "Insurance plan name"
                        },
                        "passenger_indices": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "Which passengers to insure (0-indexed). Omit for all."
                        }
                    },
                    "required": ["insurance_id"]
                },
                "ancillaries": {
                    "type": "array",
                    "description": "Ancillary services to add (from get_extras())",
                    "items": {
                        "type": "object",
                        "properties": {
                            "ancillary_id": {
                                "type": "string",
                                "description": "Ancillary option ID from get_extras()"
                            },
                            "service_type": {
                                "type": "string",
                                "description": "Service type: BAGGAGE, MEAL, PRIORITY_BOARDING, LOUNGE_ACCESS, WIFI, etc."
                            },
                            "quantity": {
                                "type": "integer",
                                "description": "Quantity (default: 1)",
                                "default": 1
                            },
                            "passenger_indices": {
                                "type": "array",
                                "items": {"type": "integer"},
                                "description": "Which passengers (0-indexed). Omit for all."
                            }
                        },
                        "required": ["ancillary_id", "service_type"]
                    }
                },
                "seat_selections": {
                    "type": "array",
                    "description": "Seat selections for each passenger/segment",
                    "items": {
                        "type": "object",
                        "properties": {
                            "seat_number": {
                                "type": "string",
                                "description": "Seat designation (e.g., '14A')"
                            },
                            "segment_id": {
                                "type": "string",
                                "description": "Flight segment ID (from search results segments)"
                            },
                            "passenger_index": {
                                "type": "integer",
                                "description": "Which passenger (0-indexed)",
                                "default": 0
                            }
                        },
                        "required": ["seat_number", "segment_id"]
                    }
                },
                "order_tickets": {
                    "type": "boolean",
                    "description": "Issue tickets immediately (default: true)",
                    "default": True
                },
                "markup_amount": {
                    "type": "number",
                    "description": "Agency markup fee in USD (0-999, default: 0)",
                    "default": 0
                }
            },
            "required": ["fare_search_id", "fare_id", "passengers"]
        }
    },
    {
        "name": "get_booking_details",
        "description": "Get full details for an existing booking by SuperPNR ID. Returns PNR, segments, passengers, ticket numbers, status, pricing, insurance, and ancillaries. Use this to check booking status or retrieve ticket information.",
        "input_schema": {
            "type": "object",
            "properties": {
                "super_pnr_id": {
                    "type": "string",
                    "description": "SuperPNR ID from create_booking() or search_bookings()"
                }
            },
            "required": ["super_pnr_id"]
        }
    },
    {
        "name": "cancel_booking",
        "description": "Cancel a booking (SuperPNR). IMPORTANT: Check fare rules first — cancellation policies vary by fare. Some fares are non-refundable (cancel with penalty) and some are fully non-cancellable. Always confirm cancellation with the user and explain any penalties before proceeding.",
        "input_schema": {
            "type": "object",
            "properties": {
                "super_pnr_id": {
                    "type": "string",
                    "description": "SuperPNR ID of the booking to cancel"
                },
                "reason": {
                    "type": "string",
                    "description": "Cancellation reason (optional but recommended)"
                }
            },
            "required": ["super_pnr_id"]
        }
    },
    {
        "name": "void_ticket",
        "description": "Void an issued ticket within the airline void window (typically 24 hours after issuance). Voiding completely reverses the ticketing with no penalties and full refund — as if the ticket was never issued. Only available within the void window. After the void window closes, use cancel_booking instead.",
        "input_schema": {
            "type": "object",
            "properties": {
                "super_pnr_id": {
                    "type": "string",
                    "description": "SuperPNR ID of the booking with tickets to void"
                }
            },
            "required": ["super_pnr_id"]
        }
    },
    {
        "name": "request_refund",
        "description": "Request a refund for a cancelled booking. Refund processing depends on fare rules and airline policy. Penalties may apply for non-refundable fares. The refund is processed through the agency's Cockpit account. Always check fare rules and explain refund terms before requesting.",
        "input_schema": {
            "type": "object",
            "properties": {
                "super_pnr_id": {
                    "type": "string",
                    "description": "SuperPNR ID of the cancelled booking"
                },
                "refund_type": {
                    "type": "string",
                    "enum": ["FULL", "PARTIAL"],
                    "description": "Full or partial refund (default: FULL)",
                    "default": "FULL"
                },
                "amount": {
                    "type": "number",
                    "description": "For partial refunds, the amount to refund"
                },
                "reason": {
                    "type": "string",
                    "description": "Refund reason"
                }
            },
            "required": ["super_pnr_id"]
        }
    }
]
