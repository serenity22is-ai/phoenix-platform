"""
ANASTASiA SDK — Backward compatibility re-exports.

API client SDKs have moved to the clients/ package (Layer 1).
This module re-exports for backward compatibility.

New code should import from clients/ directly:
    from clients import RedboxClient, DuffelNDCClient, AirGatewayClient
    from clients.redbox_auth import TokenManager
"""

__version__ = "0.3.0"

# Re-export through stubs (picasso.client -> clients.redbox)
from picasso.client import RedboxClient, CABIN_MAP, GEO_SOLR_URL  # noqa: F401

__all__ = [
    "RedboxClient",
    "CABIN_MAP",
    "GEO_SOLR_URL",
    "__version__",
]
