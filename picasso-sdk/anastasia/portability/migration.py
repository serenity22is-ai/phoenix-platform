"""
Migration Tool — System-to-system data migration with known format mappings.

Transforms booking data, configuration, and integration artifacts between
ANASTASiA's internal format and industry-standard GDS/NDC formats. Every
migration is tracked, validated, and reversible.

Known migration paths:
  - ANASTASiA -> raw JSON (universal export)
  - ANASTASiA -> Redbox/Cockpit (AERTiCKET/Picasso) — primary entry point
  - ANASTASiA -> Amadeus format (GDS standard)
  - ANASTASiA -> Sabre format
  - ANASTASiA -> Travelport format
  - ANASTASiA -> IATA NDC format
  - ANASTASiA -> custom (user-defined mapping)

MYSTES KYRIOS LLC — Confidential.
"""

import copy
import logging
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..core.events import Event, EventBus, EventType

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Known target systems and their field mappings
# ---------------------------------------------------------------------------

KNOWN_TARGETS = {
    "json": {
        "label": "Raw JSON (Universal)",
        "description": "Flat JSON export — no transformation applied.",
    },
    "redbox": {
        "label": "Redbox/Cockpit (AERTiCKET/Picasso)",
        "description": "AERTiCKET Redbox SuperPNR and shopping cart format. "
                       "Primary entry point for ANASTASiA — reverse-engineered "
                       "API with 60+ endpoints documented.",
        "booking_field_map": {
            "booking_id": "superPnrId",
            "agency_id": "agencyId",
            "status": "bookingStatus",
            "created_at": "createdTimestamp",
            "pnr": "pnrLocator",
            "origin": "departure.code",
            "destination": "destination.code",
            "departure_date": "departureTimestamp",
            "return_date": "arrivalTimestamp",
            "cabin_class": "cabinClass",
            "total_price": "total",
            "currency": "currencyIsoCode",
            "passengers": "passengerList",
            "segments": "legList",
            "fare_id": "fareId",
            "fare_search_id": "fareSearchId",
            "gds": "gds",
            "fare_type": "fareCharacteristicList",
            "validating_airline": "validatingAirline.code",
            "ticket_deadline": "ticketTimeLimit",
            "baggage": "baggageAllowance",
            "cancellation_policy": "cancellationInfo",
            "rebooking_policy": "rebookingInfo",
        },
        "passenger_field_map": {
            "passenger_id": "id",
            "type": "paxType",
            "first_name": "firstName",
            "last_name": "lastName",
            "date_of_birth": "dateOfBirth",
            "gender": "gender",
            "passport_number": "apisDocument.documentNumber",
            "passport_expiry": "apisDocument.expiryDate",
            "nationality": "apisDocument.nationality",
            "email": "contactData.emailAddress",
            "phone": "contactData.phoneNumber",
            "phone_country_code": "contactData.telCountryCode",
            "salutation": "salutation",
            "frequent_flyer": "frequentFlyerNumberList",
        },
        "status_map": {
            "confirmed": "openBookings",
            "cancelled": "cancelled",
            "voided": "voided",
            "ticketed": "issued",
            "refunded": "refunded",
            "completed": "flown",
            "partial": "partiallyFlown",
            "archived": "archived",
        },
        "cabin_map": {
            "economy": "ECONOMY",
            "premium_economy": "PREMIUM_ECONOMY",
            "business": "BUSINESS",
            "first": "FIRST",
        },
        "pax_type_map": {
            "adult": "ADT",
            "child": "CHD",
            "infant": "INF",
            "youth": "YTH",
            "student": "STU",
            "senior": "SEN",
            "military": "MIL",
        },
        "fare_characteristic_map": {
            "published": "PUB",
            "net": "NET",
            "negotiated": "NEG",
            "corporate": "COR",
            "web": "WEB",
        },
        "cart_item_types": [
            "FLIGHT", "PASSENGER", "HOTEL", "INSURANCE", "PAYMENT",
            "ANCILLARY", "SEAT", "BOOKING_FEE_OVERRIDE",
        ],
    },
    "amadeus": {
        "label": "Amadeus GDS",
        "description": "Amadeus PNR and booking record format.",
        "booking_field_map": {
            "booking_id": "RecordLocator",
            "agency_id": "OfficeId",
            "status": "Status",
            "created_at": "CreationDate",
            "pnr": "PNR",
            "origin": "OriginLocationCode",
            "destination": "DestinationLocationCode",
            "departure_date": "DepartureDate",
            "return_date": "ReturnDate",
            "cabin_class": "CabinCode",
            "total_price": "TotalPrice.Amount",
            "currency": "TotalPrice.CurrencyCode",
            "passengers": "Travelers",
            "segments": "FlightOffers.Itineraries.Segments",
        },
        "passenger_field_map": {
            "passenger_id": "TravelerId",
            "type": "TravelerType",
            "first_name": "Name.FirstName",
            "last_name": "Name.LastName",
            "date_of_birth": "DateOfBirth",
            "gender": "Gender",
            "passport_number": "Document.Number",
            "passport_expiry": "Document.ExpiryDate",
            "email": "Contact.EmailAddress",
            "phone": "Contact.Phone.Number",
        },
        "status_map": {
            "confirmed": "HK",
            "cancelled": "XX",
            "pending": "NN",
            "ticketed": "TK",
            "refunded": "RF",
        },
        "cabin_map": {
            "economy": "Y",
            "premium_economy": "W",
            "business": "C",
            "first": "F",
        },
    },
    "sabre": {
        "label": "Sabre GDS",
        "description": "Sabre booking and PNR format.",
        "booking_field_map": {
            "booking_id": "ConfirmationId",
            "agency_id": "PseudoCityCode",
            "status": "BookingStatus",
            "created_at": "CreateDateTime",
            "pnr": "RecordLocator",
            "origin": "DepartureAirport",
            "destination": "ArrivalAirport",
            "departure_date": "DepartureDateTime",
            "return_date": "ReturnDateTime",
            "cabin_class": "CabinClass",
            "total_price": "Fare.TotalAmount",
            "currency": "Fare.CurrencyCode",
            "passengers": "PassengerList",
            "segments": "SegmentList",
        },
        "passenger_field_map": {
            "passenger_id": "NameNumber",
            "type": "PassengerTypeCode",
            "first_name": "GivenName",
            "last_name": "Surname",
            "date_of_birth": "BirthDate",
            "gender": "Gender",
            "passport_number": "DocumentNumber",
            "passport_expiry": "DocumentExpiryDate",
            "email": "EmailAddress",
            "phone": "PhoneNumber",
        },
        "status_map": {
            "confirmed": "HK",
            "cancelled": "XX",
            "pending": "NN",
            "ticketed": "TK",
            "refunded": "RF",
        },
        "cabin_map": {
            "economy": "Y",
            "premium_economy": "S",
            "business": "J",
            "first": "F",
        },
    },
    "travelport": {
        "label": "Travelport (Galileo/Apollo/Worldspan)",
        "description": "Travelport Universal API format.",
        "booking_field_map": {
            "booking_id": "UniversalRecordLocatorCode",
            "agency_id": "AgencyPCC",
            "status": "Status",
            "created_at": "CreateDate",
            "pnr": "LocatorCode",
            "origin": "Origin",
            "destination": "Destination",
            "departure_date": "DepartureTime",
            "return_date": "ArrivalTime",
            "cabin_class": "CabinClass",
            "total_price": "TotalPrice",
            "currency": "Currency",
            "passengers": "BookingTraveler",
            "segments": "AirSegment",
        },
        "passenger_field_map": {
            "passenger_id": "Key",
            "type": "TravelerType",
            "first_name": "First",
            "last_name": "Last",
            "date_of_birth": "DOB",
            "gender": "Gender",
            "passport_number": "DocumentNumber",
            "passport_expiry": "ExpirationDate",
            "email": "Email",
            "phone": "PhoneNumber",
        },
        "status_map": {
            "confirmed": "HK",
            "cancelled": "XX",
            "pending": "NN",
            "ticketed": "TK",
            "refunded": "RF",
        },
        "cabin_map": {
            "economy": "Economy",
            "premium_economy": "PremiumEconomy",
            "business": "Business",
            "first": "First",
        },
    },
    "ndc": {
        "label": "IATA NDC (New Distribution Capability)",
        "description": "IATA NDC XML schema standard.",
        "booking_field_map": {
            "booking_id": "OrderID",
            "agency_id": "AgentID",
            "status": "OrderStatus",
            "created_at": "CreationDateTime",
            "pnr": "BookingReference.ID",
            "origin": "Departure.AirportCode",
            "destination": "Arrival.AirportCode",
            "departure_date": "Departure.Date",
            "return_date": "Arrival.Date",
            "cabin_class": "CabinType.Code",
            "total_price": "TotalOrderPrice.DetailCurrencyPrice.Total",
            "currency": "TotalOrderPrice.DetailCurrencyPrice.Total.Code",
            "passengers": "Passengers.Passenger",
            "segments": "OrderItems.FlightItem.OriginDestination",
        },
        "passenger_field_map": {
            "passenger_id": "PassengerID",
            "type": "PTC",
            "first_name": "Individual.GivenName",
            "last_name": "Individual.Surname",
            "date_of_birth": "Individual.Birthdate",
            "gender": "Individual.Gender",
            "passport_number": "IdentityDocument.IdentityDocumentNumber",
            "passport_expiry": "IdentityDocument.ExpiryDate",
            "email": "ContactInfoRef.EmailAddress",
            "phone": "ContactInfoRef.Phone.PhoneNumber",
        },
        "status_map": {
            "confirmed": "Confirmed",
            "cancelled": "Cancelled",
            "pending": "Pending",
            "ticketed": "Ticketed",
            "refunded": "Refunded",
        },
        "cabin_map": {
            "economy": "M",
            "premium_economy": "W",
            "business": "C",
            "first": "F",
        },
    },
}


class MigrationTool:
    """
    Transforms data between ANASTASiA's internal format and industry
    GDS/NDC standards.

    Every migration is:
      - Planned: ``create_migration_plan()`` outlines steps and risks.
      - Tracked: Each migration gets an id with full lifecycle timestamps.
      - Validated: ``validate_migration()`` checks output against schemas.
      - Reversible: ``rollback_migration()`` restores original data.

    Usage:
        tool = MigrationTool(event_bus)
        plan = tool.create_migration_plan("anastasia", "amadeus")
        migrated = tool.migrate_bookings(bookings, "amadeus")
        result = tool.validate_migration(migrated, target_schema)
    """

    def __init__(self, event_bus: EventBus):
        """
        Args:
            event_bus: Shared ANASTASiA event bus for audit events.
        """
        self._event_bus = event_bus
        self._migrations: Dict[str, dict] = {}  # migration_id -> record
        self._snapshots: Dict[str, Any] = {}     # migration_id -> original data

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_migration_plan(
        self,
        source_system: str,
        target_system: str,
    ) -> dict:
        """
        Plan a migration between two systems.

        Analyzes the source and target formats to determine required
        field mappings, potential data loss, and estimated effort.

        Args:
            source_system: Source format (e.g., "anastasia", "amadeus").
            target_system: Target format (e.g., "amadeus", "sabre", "ndc").

        Returns:
            Plan dict with keys: steps, estimated_time, risks, data_mapping.
        """
        target_lower = target_system.lower()
        source_lower = source_system.lower()

        # Build steps
        steps = [
            {
                "order": 1,
                "action": "snapshot",
                "description": f"Create snapshot of {source_lower} data for rollback",
            },
            {
                "order": 2,
                "action": "validate_source",
                "description": f"Validate source data against {source_lower} schema",
            },
            {
                "order": 3,
                "action": "transform",
                "description": f"Map fields from {source_lower} to {target_lower} format",
            },
            {
                "order": 4,
                "action": "validate_target",
                "description": f"Validate transformed data against {target_lower} schema",
            },
            {
                "order": 5,
                "action": "finalize",
                "description": "Write migration record and publish audit event",
            },
        ]

        # Identify risks
        risks = self._assess_risks(source_lower, target_lower)

        # Build field mapping
        data_mapping = self._get_field_mapping(source_lower, target_lower)

        # Estimate time
        target_info = KNOWN_TARGETS.get(target_lower)
        if target_info:
            estimated_time = "5-15 minutes (known migration path)"
        elif target_lower == "custom":
            estimated_time = "30-60 minutes (custom mapping required)"
        else:
            estimated_time = "15-30 minutes (unmapped target — best-effort)"

        plan = {
            "source": source_lower,
            "target": target_lower,
            "steps": steps,
            "estimated_time": estimated_time,
            "risks": risks,
            "data_mapping": data_mapping,
            "target_known": target_lower in KNOWN_TARGETS,
        }

        logger.info(
            "Migration plan created: %s -> %s (%d steps, %d risks)",
            source_lower, target_lower, len(steps), len(risks),
        )
        return plan

    def migrate_bookings(
        self,
        bookings_data: List[dict],
        target_format: str,
    ) -> List[dict]:
        """
        Transform booking data from ANASTASiA format to the target format.

        Creates a migration record, snapshots the original data, and
        applies the field mapping for the target system.

        Args:
            bookings_data: List of booking dicts in ANASTASiA format.
            target_format: Target system identifier (e.g., "amadeus").

        Returns:
            List of booking dicts in the target format.
        """
        migration_id = self._start_migration(
            source="anastasia",
            target=target_format,
            record_count=len(bookings_data),
        )

        # Snapshot for rollback
        self._snapshots[migration_id] = copy.deepcopy(bookings_data)

        try:
            target_lower = target_format.lower()

            if target_lower == "json":
                # Raw JSON — no transformation
                result = copy.deepcopy(bookings_data)
            elif target_lower == "custom":
                # Custom — pass through (caller applies their own mapping)
                result = copy.deepcopy(bookings_data)
            elif target_lower in KNOWN_TARGETS:
                result = self._transform_bookings(bookings_data, target_lower)
            else:
                logger.warning(
                    "Unknown target format '%s' — performing best-effort copy",
                    target_format,
                )
                result = copy.deepcopy(bookings_data)

            self._complete_migration(migration_id, len(result))
            return result

        except Exception as e:
            self._fail_migration(migration_id, str(e))
            raise

    def migrate_config(
        self,
        config_data: dict,
        target_platform: str,
    ) -> dict:
        """
        Transform agency configuration for a target platform.

        Maps ANASTASiA config keys to the target platform's expected
        configuration structure.

        Args:
            config_data: Agency config dict in ANASTASiA format.
            target_platform: Target platform identifier.

        Returns:
            Config dict in the target platform's format.
        """
        migration_id = self._start_migration(
            source="anastasia",
            target=target_platform,
            record_count=1,
        )
        self._snapshots[migration_id] = copy.deepcopy(config_data)

        try:
            target_lower = target_platform.lower()
            result = self._transform_config(config_data, target_lower)
            self._complete_migration(migration_id, 1)
            return result

        except Exception as e:
            self._fail_migration(migration_id, str(e))
            raise

    def validate_migration(
        self,
        migrated_data: List[dict],
        target_schema: dict,
    ) -> dict:
        """
        Validate migrated data against a target schema.

        Args:
            migrated_data: List of migrated records to validate.
            target_schema: Schema dict with "required", "optional",
                           and "types" keys.

        Returns:
            {"valid": bool, "errors": [str, ...], "records_checked": int}
        """
        all_errors: List[str] = []
        records_checked = 0

        for i, record in enumerate(migrated_data):
            records_checked += 1

            if not isinstance(record, dict):
                all_errors.append(f"Record {i}: expected dict, got {type(record).__name__}")
                continue

            required = target_schema.get("required", [])
            types_map = target_schema.get("types", {})

            for field in required:
                if field not in record:
                    all_errors.append(f"Record {i}: missing required field '{field}'")
                elif record[field] is None:
                    all_errors.append(f"Record {i}: required field '{field}' is null")

            for field, value in record.items():
                if field in types_map and value is not None:
                    expected = types_map[field]
                    actual = type(value).__name__
                    # Normalize type names
                    type_ok = (
                        (expected == "string" and actual == "str") or
                        (expected == "number" and actual in ("int", "float")) or
                        (expected == "boolean" and actual == "bool") or
                        (expected == "array" and actual == "list") or
                        (expected == "object" and actual == "dict") or
                        (expected == actual)
                    )
                    if not type_ok:
                        all_errors.append(
                            f"Record {i}: field '{field}' expected "
                            f"'{expected}', got '{actual}'"
                        )

        result = {
            "valid": len(all_errors) == 0,
            "errors": all_errors,
            "records_checked": records_checked,
        }

        logger.info(
            "Migration validation: %d records, %d errors",
            records_checked, len(all_errors),
        )
        return result

    def rollback_migration(self, migration_id: str) -> dict:
        """
        Undo a migration by restoring the original snapshot.

        Args:
            migration_id: ID of the migration to roll back.

        Returns:
            {"rolled_back": bool, "migration_id": str, "message": str,
             "original_data": <snapshot or None>}
        """
        if migration_id not in self._migrations:
            return {
                "rolled_back": False,
                "migration_id": migration_id,
                "message": f"Migration '{migration_id}' not found.",
                "original_data": None,
            }

        record = self._migrations[migration_id]

        if record["status"] == "rolled_back":
            return {
                "rolled_back": False,
                "migration_id": migration_id,
                "message": "Migration already rolled back.",
                "original_data": self._snapshots.get(migration_id),
            }

        original = self._snapshots.get(migration_id)
        if original is None:
            return {
                "rolled_back": False,
                "migration_id": migration_id,
                "message": "No snapshot available — rollback not possible.",
                "original_data": None,
            }

        record["status"] = "rolled_back"
        record["rolled_back_at"] = datetime.utcnow().isoformat() + "Z"

        # Publish audit event
        self._event_bus.publish(Event(
            type=EventType.AUDIT_ENTRY,
            source="portability",
            data={
                "action": "migration_rollback",
                "migration_id": migration_id,
                "source": record.get("source"),
                "target": record.get("target"),
            },
        ))

        logger.info("Migration %s rolled back.", migration_id)

        return {
            "rolled_back": True,
            "migration_id": migration_id,
            "message": "Migration rolled back. Original data restored.",
            "original_data": original,
        }

    def get_migration_history(self) -> List[dict]:
        """Return all migration records, newest first."""
        records = sorted(
            self._migrations.values(),
            key=lambda r: r.get("started_at", ""),
            reverse=True,
        )
        return records

    # ------------------------------------------------------------------
    # Internal: migration lifecycle
    # ------------------------------------------------------------------

    def _start_migration(
        self,
        source: str,
        target: str,
        record_count: int,
    ) -> str:
        """Create a migration tracking record and return its ID."""
        migration_id = f"mig_{uuid.uuid4().hex[:12]}"
        now = datetime.utcnow().isoformat() + "Z"

        record = {
            "id": migration_id,
            "source": source,
            "target": target,
            "status": "in_progress",
            "started_at": now,
            "completed_at": None,
            "records_processed": 0,
            "records_total": record_count,
            "errors": [],
        }
        self._migrations[migration_id] = record

        self._event_bus.publish(Event(
            type=EventType.AUDIT_ENTRY,
            source="portability",
            data={
                "action": "migration_started",
                "migration_id": migration_id,
                "source": source,
                "target": target,
                "record_count": record_count,
            },
        ))

        logger.info(
            "Migration %s started: %s -> %s (%d records)",
            migration_id, source, target, record_count,
        )
        return migration_id

    def _complete_migration(self, migration_id: str, records_processed: int) -> None:
        """Mark a migration as completed."""
        record = self._migrations.get(migration_id)
        if record:
            record["status"] = "completed"
            record["completed_at"] = datetime.utcnow().isoformat() + "Z"
            record["records_processed"] = records_processed

        self._event_bus.publish(Event(
            type=EventType.AUDIT_ENTRY,
            source="portability",
            data={
                "action": "migration_completed",
                "migration_id": migration_id,
                "records_processed": records_processed,
            },
        ))
        logger.info("Migration %s completed (%d records).", migration_id, records_processed)

    def _fail_migration(self, migration_id: str, error: str) -> None:
        """Mark a migration as failed."""
        record = self._migrations.get(migration_id)
        if record:
            record["status"] = "failed"
            record["completed_at"] = datetime.utcnow().isoformat() + "Z"
            record["errors"].append(error)

        self._event_bus.publish(Event(
            type=EventType.AUDIT_ENTRY,
            source="portability",
            data={
                "action": "migration_failed",
                "migration_id": migration_id,
                "error": error,
            },
        ))
        logger.error("Migration %s failed: %s", migration_id, error)

    # ------------------------------------------------------------------
    # Internal: transformation logic
    # ------------------------------------------------------------------

    def _transform_bookings(
        self,
        bookings: List[dict],
        target: str,
    ) -> List[dict]:
        """Apply field mapping to transform bookings to the target format."""
        target_info = KNOWN_TARGETS[target]
        field_map = target_info.get("booking_field_map", {})
        pax_field_map = target_info.get("passenger_field_map", {})
        status_map = target_info.get("status_map", {})
        cabin_map = target_info.get("cabin_map", {})

        result = []
        for booking in bookings:
            transformed = {}
            for src_field, tgt_field in field_map.items():
                value = booking.get(src_field)
                if value is None:
                    continue

                # Apply value mappings
                if src_field == "status" and isinstance(value, str):
                    value = status_map.get(value.lower(), value)
                elif src_field == "cabin_class" and isinstance(value, str):
                    value = cabin_map.get(value.lower(), value)
                elif src_field == "passengers" and isinstance(value, list):
                    value = [
                        self._transform_passenger(p, pax_field_map)
                        for p in value
                    ]

                # Handle dotted target keys (e.g., "TotalPrice.Amount")
                self._set_nested(transformed, tgt_field, value)

            # Preserve any unmapped fields under _unmapped
            mapped_src_fields = set(field_map.keys())
            unmapped = {
                k: v for k, v in booking.items()
                if k not in mapped_src_fields and v is not None
            }
            if unmapped:
                transformed["_unmapped"] = unmapped

            result.append(transformed)

        return result

    def _transform_passenger(
        self,
        passenger: dict,
        field_map: dict,
    ) -> dict:
        """Transform a single passenger record using the field mapping."""
        transformed = {}
        for src_field, tgt_field in field_map.items():
            value = passenger.get(src_field)
            if value is not None:
                self._set_nested(transformed, tgt_field, value)
        return transformed

    def _transform_config(self, config: dict, target: str) -> dict:
        """
        Transform agency config for a target platform.

        Config migration is less standardized than bookings — each
        platform has its own config structure. We produce a best-effort
        mapping with an _original section for anything we cannot map.
        """
        migrated = {
            "_migration_metadata": {
                "source": "anastasia",
                "target": target,
                "migrated_at": datetime.utcnow().isoformat() + "Z",
            },
            "_original": copy.deepcopy(config),
        }

        # Common fields that map across platforms
        if target in KNOWN_TARGETS:
            migrated["agency_identifier"] = config.get("agency_id", "")
            migrated["agency_display_name"] = config.get("agency_name", "")
            migrated["default_currency"] = config.get("default_currency", "USD")
            migrated["default_locale"] = config.get("default_language", "en")
            migrated["timezone"] = config.get("timezone", "UTC")
            migrated["pos_markets"] = config.get("pos_markets", [])
            migrated["pricing_rules"] = config.get("pricing_rules", {})
            migrated["feature_flags"] = config.get("feature_flags", {})
        else:
            # Unknown target — just wrap the original config
            migrated["config"] = copy.deepcopy(config)

        return migrated

    # ------------------------------------------------------------------
    # Internal: helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _set_nested(target: dict, dotted_key: str, value: Any) -> None:
        """
        Set a value in a nested dict using a dotted key path.

        Example: _set_nested(d, "TotalPrice.Amount", 199.99)
                 -> d["TotalPrice"]["Amount"] = 199.99
        """
        parts = dotted_key.split(".")
        current = target
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value

    def _get_field_mapping(self, source: str, target: str) -> dict:
        """
        Return the field mapping between source and target.

        For ANASTASiA as source, the mapping is the booking_field_map
        from the target's entry in KNOWN_TARGETS.
        """
        target_info = KNOWN_TARGETS.get(target, {})
        if not target_info:
            return {"note": f"No predefined mapping for target '{target}'"}

        return {
            "booking_fields": target_info.get("booking_field_map", {}),
            "passenger_fields": target_info.get("passenger_field_map", {}),
            "status_values": target_info.get("status_map", {}),
            "cabin_values": target_info.get("cabin_map", {}),
        }

    @staticmethod
    def _assess_risks(source: str, target: str) -> List[str]:
        """Identify potential risks for a migration path."""
        risks = []

        if target == "custom":
            risks.append(
                "Custom mapping: no predefined field mapping — user must "
                "provide their own mapping definition."
            )

        if target not in KNOWN_TARGETS and target != "custom":
            risks.append(
                f"Unknown target '{target}': best-effort migration only. "
                f"No field mapping or validation available."
            )

        if target in ("amadeus", "sabre", "travelport"):
            risks.append(
                "GDS format: some ANASTASiA fields (e.g., arbitrage metadata, "
                "fee breakdowns) have no GDS equivalent and will be placed in "
                "'_unmapped' section."
            )
            risks.append(
                "GDS status codes may not round-trip perfectly if the booking "
                "originated from a non-GDS source."
            )

        if target == "ndc":
            risks.append(
                "NDC format: field nesting is deep. Some flat fields are "
                "restructured into nested objects — verify downstream "
                "parsers can handle the depth."
            )

        if target == "redbox":
            risks.append(
                "Redbox passenger fields use nested contactData/apisDocument "
                "objects — DO NOT use top-level email/phone/passportNumber "
                "(will 400). Gender must be 'Male'/'Female' (capitalized)."
            )
            risks.append(
                "Redbox cart operations require an active paid Picasso account. "
                "Sandbox allows search but FLIGHT cart items fail with "
                "FARE_VERIFICATION_FAILED."
            )
            risks.append(
                "Redbox BOOKING_FEE_OVERRIDE cart item changes fare total — "
                "required for airline compliance (ticket shows customer price, "
                "not wholesale). Include platform markup here."
            )

        if source != "anastasia" and source not in KNOWN_TARGETS:
            risks.append(
                f"Unknown source '{source}': cannot verify source data structure."
            )

        # Always include a general risk
        risks.append(
            "Dates and timestamps are exported in ISO-8601. Target systems "
            "using non-standard date formats may need post-processing."
        )

        return risks
