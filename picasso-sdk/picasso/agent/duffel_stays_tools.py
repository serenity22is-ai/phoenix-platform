"""
Duffel Stays Tool Definitions — Claude function calling schemas.

Each tool maps 1:1 to a Duffel Stays API method. The agent orchestrator
routes Claude's duffel_stays_* tool_use blocks to the corresponding SDK calls.

Tool names are prefixed with "duffel_stays_" to distinguish from Duffel flight
tools and liteAPI hotel tools. All three toolsets can be active simultaneously
for multi-source hotel searches.

MYSTES KYRIOS LLC — Confidential.
"""

DUFFEL_STAYS_TOOL_DEFINITIONS = [
    {
        "name": "duffel_stays_suggest",
        "description": "Autocomplete hotel/accommodation names by query via Duffel Stays. Use this to resolve property or location names. Minimum 3 characters required. Returns accommodation suggestions with IDs and coordinates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Property name, chain name, or location (minimum 3 characters, e.g., 'Marriott Times Square', 'Hilton London')",
                    "minLength": 3
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "duffel_stays_list_accommodation",
        "description": "List available accommodation properties near a geographic point via Duffel Stays. Use this to discover hotels in an area when you have coordinates. Returns properties with IDs, names, ratings, and locations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "latitude": {
                    "type": "number",
                    "description": "Latitude of the search center point (e.g., 40.7580 for Times Square)"
                },
                "longitude": {
                    "type": "number",
                    "description": "Longitude of the search center point (e.g., -73.9855 for Times Square)"
                },
                "radius": {
                    "type": "integer",
                    "description": "Search radius in kilometers (default: 5)",
                    "default": 5
                }
            },
            "required": ["latitude", "longitude"]
        }
    },
    {
        "name": "duffel_stays_get_accommodation",
        "description": "Get detailed information about a specific accommodation property via Duffel Stays. Returns property details including name, address, description, amenities, photos, and star rating.",
        "input_schema": {
            "type": "object",
            "properties": {
                "accommodation_id": {
                    "type": "string",
                    "description": "The accommodation ID from suggest or list results (e.g., 'acc_...')"
                }
            },
            "required": ["accommodation_id"]
        }
    },
    {
        "name": "duffel_stays_search",
        "description": "Search for available hotel rooms and rates via Duffel Stays (1M+ properties, major chains). Returns search_result_ids required for fetching rates. Requires coordinates — use duffel_stays_suggest or duffel_stays_list_accommodation first to resolve locations. Optionally filter by specific accommodation_ids.",
        "input_schema": {
            "type": "object",
            "properties": {
                "check_in": {
                    "type": "string",
                    "description": "Check-in date in YYYY-MM-DD format"
                },
                "check_out": {
                    "type": "string",
                    "description": "Check-out date in YYYY-MM-DD format"
                },
                "adults": {
                    "type": "integer",
                    "description": "Number of adult guests (default: 1)",
                    "default": 1
                },
                "rooms": {
                    "type": "integer",
                    "description": "Number of rooms required (default: 1)",
                    "default": 1
                },
                "latitude": {
                    "type": "number",
                    "description": "Latitude of the search center point"
                },
                "longitude": {
                    "type": "number",
                    "description": "Longitude of the search center point"
                },
                "accommodation_ids": {
                    "type": "array",
                    "description": "Optional list of specific accommodation IDs to search (from suggest or list results)",
                    "items": {
                        "type": "string"
                    }
                }
            },
            "required": ["check_in", "check_out", "latitude", "longitude"]
        }
    },
    {
        "name": "duffel_stays_fetch_rates",
        "description": "Fetch detailed rates for a specific search result via Duffel Stays. Returns available room types, rate plans, pricing breakdowns, cancellation policies, and rate_ids required for creating a quote.",
        "input_schema": {
            "type": "object",
            "properties": {
                "search_result_id": {
                    "type": "string",
                    "description": "The search_result_id from duffel_stays_search results"
                }
            },
            "required": ["search_result_id"]
        }
    },
    {
        "name": "duffel_stays_create_quote",
        "description": "Create a price-locked quote for a specific hotel rate via Duffel Stays. Locks the price for a limited time (check expires_at). Returns a quote_id required for booking. IMPORTANT: Quotes expire — if expired, re-search and create a new quote.",
        "input_schema": {
            "type": "object",
            "properties": {
                "rate_id": {
                    "type": "string",
                    "description": "The rate_id from duffel_stays_fetch_rates results"
                }
            },
            "required": ["rate_id"]
        }
    },
    {
        "name": "duffel_stays_book",
        "description": "Book a hotel stay via Duffel Stays. Creates a confirmed booking. CRITICAL: Always confirm with the user before calling — bookings create real hotel reservations. Requires quote_id, guest details, email, and phone (E.164 format). No passport or date of birth needed for hotels.",
        "input_schema": {
            "type": "object",
            "properties": {
                "quote_id": {
                    "type": "string",
                    "description": "The quote_id from duffel_stays_create_quote"
                },
                "email": {
                    "type": "string",
                    "description": "Primary contact email address for the booking"
                },
                "phone_number": {
                    "type": "string",
                    "description": "Phone number in E.164 format (e.g., +12125551234)"
                },
                "guests": {
                    "type": "array",
                    "description": "List of guest details for the booking",
                    "items": {
                        "type": "object",
                        "properties": {
                            "given_name": {
                                "type": "string",
                                "description": "Guest's first name"
                            },
                            "family_name": {
                                "type": "string",
                                "description": "Guest's last name"
                            }
                        },
                        "required": ["given_name", "family_name"]
                    }
                },
                "loyalty_programme_account_number": {
                    "type": "string",
                    "description": "Hotel loyalty programme account number (optional, e.g., Marriott Bonvoy number)"
                },
                "accommodation_special_requests": {
                    "type": "string",
                    "description": "Special requests for the hotel (optional, e.g., 'high floor', 'late check-out', 'extra pillows')"
                }
            },
            "required": ["quote_id", "email", "phone_number", "guests"]
        }
    },
    {
        "name": "duffel_stays_list_bookings",
        "description": "List Duffel Stays hotel bookings with pagination. Returns recent bookings with confirmation references, status, and pricing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Number of bookings to return (default: 20)",
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
        "name": "duffel_stays_get_booking",
        "description": "Get full details for an existing Duffel Stays hotel booking by booking ID. Returns confirmation reference, status, property details, room information, dates, guests, and cancellation policy.",
        "input_schema": {
            "type": "object",
            "properties": {
                "booking_id": {
                    "type": "string",
                    "description": "Duffel Stays booking ID"
                }
            },
            "required": ["booking_id"]
        }
    },
    {
        "name": "duffel_stays_update_booking",
        "description": "Update an existing Duffel Stays hotel booking. Can modify guest details, special requests, or other mutable booking fields. Check the booking status before attempting updates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "booking_id": {
                    "type": "string",
                    "description": "Duffel Stays booking ID to update"
                },
                "updates": {
                    "type": "object",
                    "description": "Object containing the fields to update (e.g., accommodation_special_requests, guest details)"
                }
            },
            "required": ["booking_id", "updates"]
        }
    },
    {
        "name": "duffel_stays_cancel_booking",
        "description": "Cancel a Duffel Stays hotel booking. IMPORTANT: Always check the cancellation policy on the rate BEFORE booking, and confirm with the user before cancelling. Returns cancellation confirmation and any applicable fees.",
        "input_schema": {
            "type": "object",
            "properties": {
                "booking_id": {
                    "type": "string",
                    "description": "Duffel Stays booking ID to cancel"
                }
            },
            "required": ["booking_id"]
        }
    },
]
