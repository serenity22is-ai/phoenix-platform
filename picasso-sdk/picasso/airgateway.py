"""
Backward compatibility stub — real implementation in clients/airgateway.py

All API client SDKs now live in the clients/ package (Layer 1).
This stub ensures existing imports continue to work.
"""

from clients.airgateway import AirGatewayClient  # noqa: F401
