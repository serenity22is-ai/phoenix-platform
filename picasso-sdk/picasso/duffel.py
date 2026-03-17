"""
Backward compatibility stub — real implementation in clients/duffel.py

All API client SDKs now live in the clients/ package (Layer 1).
This stub ensures existing imports continue to work.
"""

from clients.duffel import DuffelNDCClient  # noqa: F401
