"""
Backward compatibility stub — real implementation in clients/redbox.py

All API client SDKs now live in the clients/ package (Layer 1).
This stub ensures existing imports continue to work.
"""

from clients.redbox import (  # noqa: F401
    RedboxClient,
    CABIN_MAP,
    GEO_SOLR_URL,
    DEFAULT_REDBOX_URL,
)
