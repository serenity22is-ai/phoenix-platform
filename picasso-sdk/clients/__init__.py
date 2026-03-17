"""
ANASTASiA API Client SDKs — Layer 1 (Dumb Pipes)

Each client is a thin wrapper (~500-800 LOC) around one external API.
ANASTASiA intelligence (Layer 2) orchestrates all clients through the
credential network, deduplicates results, and surfaces best pricing
through the unified MYSTES API feed.

Clients are swappable cartridges — adding a new provider means writing
one new client file. The intelligence layer is provider-agnostic.

Available clients:
    - RedboxClient     — Picasso/Cockpit/AERTiCKET (GDS via consolidator, 102 POS)
    - TokenManager     — Redbox auth (Playwright + TOTP auto-login)
    - DuffelNDCClient  — Duffel (NDC direct, 300+ airlines)
    - AirGatewayClient — AirGateway (NDC + AERTiCKET GDS content)
    - KiwiTequilaClient — Kiwi Tequila (750+ carriers, virtual interlining)

Future clients (pending API access):
    - MystiflyClient   — Mystifly OnePoint (multi-GDS, 80+ POS)
    - LiteAPIClient    — liteAPI (hotels, already built in consumer OTA)

MYSTES KYRIOS LLC — Confidential.
"""

from clients.redbox import RedboxClient, CABIN_MAP, GEO_SOLR_URL  # noqa: F401
from clients.duffel import DuffelNDCClient  # noqa: F401
from clients.airgateway import AirGatewayClient  # noqa: F401
from clients.kiwi import KiwiTequilaClient  # noqa: F401

__all__ = [
    "RedboxClient",
    "CABIN_MAP",
    "GEO_SOLR_URL",
    "DuffelNDCClient",
    "AirGatewayClient",
    "KiwiTequilaClient",
]
