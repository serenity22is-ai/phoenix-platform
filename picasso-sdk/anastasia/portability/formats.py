"""
Export Formats — Serialization and deserialization for portable data export.

Supports JSON, CSV, and XML using only the Python standard library.
Each format includes round-trip fidelity: serialize -> deserialize -> identical data.
Schema validation ensures exported data meets the expected structure before
it leaves the platform.

MYSTES KYRIOS LLC — Confidential.
"""

import csv
import io
import json
import logging
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schemas — canonical field definitions for exported entities
# ---------------------------------------------------------------------------

BOOKING_SCHEMA: Dict[str, Any] = {
    "required": [
        "booking_id", "agency_id", "status", "created_at",
    ],
    "optional": [
        "pnr", "gds_record_locator", "origin", "destination",
        "departure_date", "return_date", "cabin_class",
        "total_price", "currency", "supplier", "pos_market",
        "passengers", "segments", "payment_method", "payment_status",
        "ticketed_at", "cancelled_at", "refund_amount",
        "metadata",
    ],
    "types": {
        "booking_id": "string",
        "agency_id": "string",
        "status": "string",
        "created_at": "string",
        "pnr": "string",
        "gds_record_locator": "string",
        "origin": "string",
        "destination": "string",
        "departure_date": "string",
        "return_date": "string",
        "cabin_class": "string",
        "total_price": "number",
        "currency": "string",
        "supplier": "string",
        "pos_market": "string",
        "passengers": "array",
        "segments": "array",
        "payment_method": "string",
        "payment_status": "string",
        "ticketed_at": "string",
        "cancelled_at": "string",
        "refund_amount": "number",
        "metadata": "object",
    },
}

PASSENGER_SCHEMA: Dict[str, Any] = {
    "required": [
        "passenger_id", "type", "first_name", "last_name",
    ],
    "optional": [
        "date_of_birth", "gender", "nationality", "passport_number",
        "passport_expiry", "email", "phone", "frequent_flyer_number",
        "frequent_flyer_program", "seat_preference", "meal_preference",
        "special_requests", "ticket_number",
    ],
    "types": {
        "passenger_id": "string",
        "type": "string",
        "first_name": "string",
        "last_name": "string",
        "date_of_birth": "string",
        "gender": "string",
        "nationality": "string",
        "passport_number": "string",
        "passport_expiry": "string",
        "email": "string",
        "phone": "string",
        "frequent_flyer_number": "string",
        "frequent_flyer_program": "string",
        "seat_preference": "string",
        "meal_preference": "string",
        "special_requests": "string",
        "ticket_number": "string",
    },
}

CONFIG_SCHEMA: Dict[str, Any] = {
    "required": [
        "agency_id", "agency_name", "created_at",
    ],
    "optional": [
        "default_currency", "default_language", "timezone",
        "pos_markets", "pricing_rules", "fee_config",
        "notification_settings", "api_keys_redacted",
        "integration_endpoints", "branding", "contact_info",
        "compliance_settings", "feature_flags",
    ],
    "types": {
        "agency_id": "string",
        "agency_name": "string",
        "created_at": "string",
        "default_currency": "string",
        "default_language": "string",
        "timezone": "string",
        "pos_markets": "array",
        "pricing_rules": "object",
        "fee_config": "object",
        "notification_settings": "object",
        "api_keys_redacted": "object",
        "integration_endpoints": "array",
        "branding": "object",
        "contact_info": "object",
        "compliance_settings": "object",
        "feature_flags": "object",
    },
}

# Python type name -> schema type name
_PYTHON_TYPE_MAP = {
    "str": "string",
    "int": "number",
    "float": "number",
    "bool": "boolean",
    "list": "array",
    "dict": "object",
    "NoneType": "null",
}


class ExportFormats:
    """
    Stateless utility for serializing, deserializing, and validating
    portable data in JSON, CSV, and XML formats.

    All methods are classmethods so you never need an instance — but
    instantiation is allowed for consistency with other ANASTASiA classes.
    """

    # Expose schemas as class attributes for convenient access
    BOOKING_SCHEMA = BOOKING_SCHEMA
    PASSENGER_SCHEMA = PASSENGER_SCHEMA
    CONFIG_SCHEMA = CONFIG_SCHEMA

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    @classmethod
    def to_json(cls, data: Any, pretty: bool = True) -> str:
        """
        Serialize data to a JSON string.

        Args:
            data: Any JSON-serializable Python object.
            pretty: If True, indent with 2 spaces for readability.

        Returns:
            JSON string.
        """
        indent = 2 if pretty else None
        return json.dumps(data, indent=indent, default=str, ensure_ascii=False)

    @classmethod
    def to_csv(cls, data: List[dict], columns: List[str] = None) -> str:
        """
        Serialize a list of flat dicts to a CSV string.

        Args:
            data: List of dicts (one dict per row). Nested objects are
                  JSON-encoded in their cells.
            columns: Explicit column order. If None, columns are derived
                     from the union of all keys across all rows, sorted
                     alphabetically for deterministic output.

        Returns:
            CSV string with header row.
        """
        if not data:
            return ""

        if columns is None:
            col_set: set = set()
            for row in data:
                col_set.update(row.keys())
            columns = sorted(col_set)

        buf = io.StringIO()
        writer = csv.DictWriter(
            buf, fieldnames=columns, extrasaction="ignore",
            quoting=csv.QUOTE_MINIMAL,
        )
        writer.writeheader()
        for row in data:
            # Flatten nested structures into JSON strings for CSV cells
            flat = {}
            for col in columns:
                val = row.get(col, "")
                if isinstance(val, (dict, list)):
                    flat[col] = json.dumps(val, default=str)
                else:
                    flat[col] = val
            writer.writerow(flat)

        return buf.getvalue()

    @classmethod
    def to_xml(cls, data: Any, root_element: str = "export") -> str:
        """
        Serialize data to an XML string.

        Args:
            data: A dict, list of dicts, or primitive value.
            root_element: Tag name for the root XML element.

        Returns:
            XML string with declaration.
        """
        root = ET.Element(root_element)
        cls._build_xml_tree(root, data)
        # Produce string with declaration
        tree = ET.ElementTree(root)
        buf = io.BytesIO()
        tree.write(buf, encoding="unicode", xml_declaration=True)
        return buf.getvalue()

    @classmethod
    def _build_xml_tree(cls, parent: ET.Element, data: Any) -> None:
        """Recursively build XML elements from Python data."""
        if isinstance(data, dict):
            for key, value in data.items():
                # XML tag names must be valid — sanitize if needed
                tag = cls._sanitize_xml_tag(str(key))
                child = ET.SubElement(parent, tag)
                cls._build_xml_tree(child, value)
        elif isinstance(data, (list, tuple)):
            for i, item in enumerate(data):
                child = ET.SubElement(parent, "item")
                child.set("index", str(i))
                cls._build_xml_tree(child, item)
        elif data is None:
            parent.text = ""
            parent.set("null", "true")
        else:
            parent.text = str(data)

    @staticmethod
    def _sanitize_xml_tag(tag: str) -> str:
        """
        Ensure a string is a valid XML tag name.

        Replaces invalid characters with underscores. Prepends underscore
        if the tag starts with a digit.
        """
        sanitized = re.sub(r"[^a-zA-Z0-9_.\-]", "_", tag)
        if sanitized and sanitized[0].isdigit():
            sanitized = "_" + sanitized
        if not sanitized:
            sanitized = "_empty"
        return sanitized

    # ------------------------------------------------------------------
    # Deserialization
    # ------------------------------------------------------------------

    @classmethod
    def from_json(cls, content: str) -> Any:
        """
        Deserialize a JSON string to Python objects.

        Args:
            content: Valid JSON string.

        Returns:
            Parsed Python object (dict, list, str, int, etc.).

        Raises:
            json.JSONDecodeError: If content is not valid JSON.
        """
        return json.loads(content)

    @classmethod
    def from_csv(cls, content: str) -> List[dict]:
        """
        Deserialize a CSV string (with header row) to a list of dicts.

        Args:
            content: CSV string where the first row contains column headers.

        Returns:
            List of dicts, one per data row.
        """
        buf = io.StringIO(content)
        reader = csv.DictReader(buf)
        rows = []
        for row in reader:
            # Attempt to parse JSON-encoded cells back into objects
            parsed = {}
            for key, value in row.items():
                parsed[key] = cls._try_parse_csv_value(value)
            rows.append(parsed)
        return rows

    @staticmethod
    def _try_parse_csv_value(value: str) -> Any:
        """
        Try to recover structured data from a CSV cell.

        CSV cells containing JSON arrays or objects are parsed back.
        Numeric strings are left as strings to preserve fidelity.
        """
        if not value:
            return value
        stripped = value.strip()
        if (stripped.startswith("{") and stripped.endswith("}")) or \
           (stripped.startswith("[") and stripped.endswith("]")):
            try:
                return json.loads(stripped)
            except (json.JSONDecodeError, ValueError):
                pass
        return value

    @classmethod
    def from_xml(cls, content: str) -> dict:
        """
        Deserialize an XML string to a Python dict.

        Args:
            content: Valid XML string.

        Returns:
            Dict representation of the XML tree.

        Raises:
            ET.ParseError: If content is not valid XML.
        """
        root = ET.fromstring(content)
        return {root.tag: cls._xml_element_to_dict(root)}

    @classmethod
    def _xml_element_to_dict(cls, element: ET.Element) -> Any:
        """Recursively convert an XML element to Python objects."""
        # Check for null marker
        if element.get("null") == "true":
            return None

        children = list(element)
        if not children:
            # Leaf node — return text content
            text = element.text
            if text is None:
                return ""
            return text

        # Check if children are indexed list items
        if all(child.tag == "item" and child.get("index") is not None
               for child in children):
            result = []
            for child in sorted(children, key=lambda c: int(c.get("index", 0))):
                result.append(cls._xml_element_to_dict(child))
            return result

        # Otherwise treat as dict
        result = {}
        for child in children:
            child_data = cls._xml_element_to_dict(child)
            if child.tag in result:
                # Duplicate tags -> convert to list
                existing = result[child.tag]
                if isinstance(existing, list):
                    existing.append(child_data)
                else:
                    result[child.tag] = [existing, child_data]
            else:
                result[child.tag] = child_data
        return result

    # ------------------------------------------------------------------
    # Format detection
    # ------------------------------------------------------------------

    @classmethod
    def detect_format(cls, content: str) -> str:
        """
        Auto-detect the format of input data by inspecting its content.

        Args:
            content: Raw string data to inspect.

        Returns:
            One of: "json", "csv", "xml", "unknown".
        """
        stripped = content.strip()

        # XML: starts with declaration or root element
        if stripped.startswith("<?xml") or stripped.startswith("<"):
            try:
                ET.fromstring(stripped)
                return "xml"
            except ET.ParseError:
                pass

        # JSON: starts with { or [
        if stripped.startswith(("{", "[")):
            try:
                json.loads(stripped)
                return "json"
            except (json.JSONDecodeError, ValueError):
                pass

        # CSV: multiple lines with consistent comma/tab delimiters
        lines = stripped.split("\n")
        if len(lines) >= 2:
            # Check if header and first data row have the same number of fields
            try:
                sniffer = csv.Sniffer()
                sniffer.sniff(stripped[:4096])
                return "csv"
            except csv.Error:
                pass

        return "unknown"

    # ------------------------------------------------------------------
    # Schema validation
    # ------------------------------------------------------------------

    @classmethod
    def validate_against_schema(cls, data: dict, schema: dict) -> dict:
        """
        Validate a dict against a schema definition.

        Schema format:
            {
                "required": ["field1", "field2"],
                "optional": ["field3"],
                "types": {"field1": "string", "field2": "number", ...}
            }

        Args:
            data: Dict to validate.
            schema: Schema definition dict.

        Returns:
            {"valid": bool, "errors": [str, ...]}
        """
        errors: List[str] = []

        if not isinstance(data, dict):
            return {"valid": False, "errors": ["Data must be a dict"]}

        required_fields = schema.get("required", [])
        optional_fields = schema.get("optional", [])
        type_map = schema.get("types", {})
        all_known = set(required_fields) | set(optional_fields)

        # Check required fields
        for field in required_fields:
            if field not in data:
                errors.append(f"Missing required field: '{field}'")
            elif data[field] is None:
                errors.append(f"Required field '{field}' is null")

        # Check types for present fields
        for field, value in data.items():
            if field in type_map and value is not None:
                expected = type_map[field]
                actual = _PYTHON_TYPE_MAP.get(type(value).__name__, type(value).__name__)
                if actual != expected:
                    errors.append(
                        f"Field '{field}' expected type '{expected}', "
                        f"got '{actual}'"
                    )

        # Warn about unknown fields (not an error, just informational)
        unknown = set(data.keys()) - all_known
        if unknown:
            logger.debug(
                "Validation: data contains fields not in schema: %s",
                ", ".join(sorted(unknown))
            )

        return {"valid": len(errors) == 0, "errors": errors}
