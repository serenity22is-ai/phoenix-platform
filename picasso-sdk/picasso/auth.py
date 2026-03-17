"""
Backward compatibility stub — real implementation in clients/redbox_auth.py

All API client SDKs now live in the clients/ package (Layer 1).
This stub ensures existing imports continue to work.
"""

from clients.redbox_auth import TokenManager  # noqa: F401
