"""
Duffel NDC Tool Definitions — Claude function calling schemas.

Each tool maps 1:1 to a DuffelNDCClient method. The agent orchestrator
routes Claude's duffel_* tool_use blocks to the corresponding SDK calls.

Tool names are prefixed with "duffel_" to distinguish from Redbox tools.
Both toolsets can be active simultaneously for multi-source searches.

MYSTES KYRIOS LLC — Confidential.
"""

DUFFEL_TOOL_DEFINITIONS = [
    {
        "name": "duffel_search_places",
        "description": "Autocomplete airports and cities by name via Duffel. Use this to resolve city names to IATA airport codes. Returns airports and cities matching the query.",
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
        "name": "duffel_search_flights",
        "description": "Search for flights via Duffel NDC API (300+ airlines, direct NDC connections). Returns offer_ids required for booking, services, and seat maps. NDC fares may include exclusive pricing not available through traditional GDS channels.",
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
                    "description": "Maximum results to return (default: 20)",
                    "default": 20
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
        "name": "duffel_get_offer",
        "description": "Get current details for a specific flight offer. Use this to refresh the price before booking (prices can change). Returns full offer details including conditions, available services, and current pricing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "offer_id": {
                    "type": "string",
                    "description": "The offer_id from duffel_search_flights results"
                }
            },
            "required": ["offer_id"]
        }
    },
    {
        "name": "duffel_get_services",
        "description": "Get available ancillary services (extra baggage, meals, seats) for a Duffel flight offer. Call after search to discover purchasable extras.",
        "input_schema": {
            "type": "object",
            "properties": {
                "offer_id": {
                    "type": "string",
                    "description": "The offer_id to get services for"
                }
            },
            "required": ["offer_id"]
        }
    },
    {
        "name": "duffel_get_seat_map",
        "description": "Get the seat map for a Duffel flight offer. Shows available seats, cabin layout, and seat pricing for each segment.",
        "input_schema": {
            "type": "object",
            "properties": {
                "offer_id": {
                    "type": "string",
                    "description": "The offer_id to get seat map for"
                }
            },
            "required": ["offer_id"]
        }
    },
    {
        "name": "duffel_book_flight",
        "description": "Book a flight via Duffel NDC. Creates an order (booking) with confirmed tickets. CRITICAL: Always confirm with the user before calling — bookings create real airline reservations. Requires full passenger details including passport for international flights.",
        "input_schema": {
            "type": "object",
            "properties": {
                "offer_id": {
                    "type": "string",
                    "description": "The offer_id of the selected flight"
                },
                "passengers": {
                    "type": "array",
                    "description": "List of passenger details for booking",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "description": "Passenger ID from the offer (links search passenger to booking)"
                            },
                            "given_name": {
                                "type": "string",
                                "description": "First name (must match passport/ID)"
                            },
                            "family_name": {
                                "type": "string",
                                "description": "Last name (must match passport/ID)"
                            },
                            "born_on": {
                                "type": "string",
                                "description": "Date of birth in YYYY-MM-DD format"
                            },
                            "gender": {
                                "type": "string",
                                "enum": ["m", "f"],
                                "description": "Gender: 'm' or 'f'"
                            },
                            "title": {
                                "type": "string",
                                "enum": ["mr", "mrs", "ms", "miss", "dr"],
                                "description": "Title"
                            },
                            "email": {
                                "type": "string",
                                "description": "Contact email address"
                            },
                            "phone_number": {
                                "type": "string",
                                "description": "Phone with country code (e.g., +12125551234)"
                            },
                            "passport_number": {
                                "type": "string",
                                "description": "Passport number (required for international)"
                            },
                            "passport_expiry": {
                                "type": "string",
                                "description": "Passport expiry in YYYY-MM-DD"
                            },
                            "passport_country": {
                                "type": "string",
                                "description": "Issuing country code (e.g., 'US')"
                            },
                            "loyalty_airline": {
                                "type": "string",
                                "description": "FF airline IATA code (e.g., 'BA')"
                            },
                            "loyalty_number": {
                                "type": "string",
                                "description": "Frequent flyer account number"
                            }
                        },
                        "required": ["id", "given_name", "family_name", "born_on", "gender", "title", "email", "phone_number"]
                    }
                },
                "services": {
                    "type": "array",
                    "description": "Ancillary services to add (from duffel_get_services)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "description": "Service ID from duffel_get_services"
                            },
                            "quantity": {
                                "type": "integer",
                                "description": "Quantity (default: 1)",
                                "default": 1
                            },
                            "amount": {
                                "type": "string",
                                "description": "Service price amount"
                            }
                        },
                        "required": ["id"]
                    }
                },
                "metadata": {
                    "type": "object",
                    "description": "Custom metadata to attach to the order"
                }
            },
            "required": ["offer_id", "passengers"]
        }
    },
    {
        "name": "duffel_get_order",
        "description": "Get full details for an existing Duffel booking by order ID. Returns booking reference (PNR), status, segments, passengers, tickets/documents, and conditions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "Duffel order ID (ord_...)"
                }
            },
            "required": ["order_id"]
        }
    },
    {
        "name": "duffel_list_orders",
        "description": "List Duffel bookings/orders with pagination. Returns recent orders with booking references, status, and pricing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Number of orders to return (default: 20)",
                    "default": 20
                },
                "after": {
                    "type": "string",
                    "description": "Pagination cursor (from previous response meta.after)"
                }
            }
        }
    },
    {
        "name": "duffel_cancel_order",
        "description": "Cancel a Duffel booking/order. This is a two-step process: requests cancellation, then confirms it. Returns refund amount and penalty information. IMPORTANT: Always check conditions first and confirm with the user before cancelling.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "Duffel order ID to cancel (ord_...)"
                }
            },
            "required": ["order_id"]
        }
    },
    {
        "name": "duffel_change_order",
        "description": "Request a change to an existing Duffel order (date or route change). Creates a change request that generates available change offers with fare differences.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "Duffel order ID to change (ord_...)"
                },
                "new_slices": {
                    "type": "array",
                    "description": "New slice definitions for the changed itinerary",
                    "items": {
                        "type": "object",
                        "properties": {
                            "origin": {
                                "type": "string",
                                "description": "New origin IATA code"
                            },
                            "destination": {
                                "type": "string",
                                "description": "New destination IATA code"
                            },
                            "departure_date": {
                                "type": "string",
                                "description": "New departure date YYYY-MM-DD"
                            },
                            "cabin_class": {
                                "type": "string",
                                "description": "Cabin class (default: economy)"
                            }
                        },
                        "required": ["origin", "destination", "departure_date"]
                    }
                }
            },
            "required": ["order_id", "new_slices"]
        }
    },
]
