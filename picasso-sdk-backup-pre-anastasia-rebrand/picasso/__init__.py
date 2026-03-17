"""
Picasso Redbox SDK — Python client for the Picasso Travel / AERTiCKET Redbox API.

Quick start:
    from picasso import RedboxClient

    client = RedboxClient(
        agency_id="YOUR_AGENCY_ID",
        branch="YOUR_BRANCH",
        session_token="YOUR_TOKEN",
    )
    result = client.search_flights("JFK", "LHR", "2026-06-15")

With auto-login (requires `pip install picasso-redbox-sdk[auth]`):
    from picasso import RedboxClient
    from picasso.auth import TokenManager

    manager = TokenManager()
    client = RedboxClient(
        agency_id="YOUR_AGENCY_ID",
        branch="YOUR_BRANCH",
        token_provider=manager.get_token,
    )
"""

__version__ = "0.1.0"

from picasso.client import RedboxClient, CABIN_MAP, GEO_SOLR_URL

__all__ = [
    "RedboxClient",
    "CABIN_MAP",
    "GEO_SOLR_URL",
    "__version__",
]
