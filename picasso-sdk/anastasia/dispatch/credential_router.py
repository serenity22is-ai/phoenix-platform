"""
Credential Router — Glue between CredentialNetwork and dispatch pipeline.

Builds API client instances from vault-stored credentials for a given tenant.
If the tenant has their own credentials (Tier 1), those are used at zero fee.
Otherwise, routes through the network to find a credential holder.

This is the bridge that makes ANASTASiA a credential network, not just an OTA.
Without this, MYSTES is a single agency. With this, it's the platform.

MYSTES KYRIOS LLC — Confidential.
"""

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Provider ID → source name mapping (network uses provider_id, dispatch uses source)
_PROVIDER_TO_SOURCE = {
    "picasso": "picasso",
    "picasso_redbox": "picasso",
    "duffel_ndc": "duffel_ndc",
    "duffel": "duffel_ndc",
    "kiwi_tequila": "kiwi_tequila",
    "kiwi": "kiwi_tequila",
    "airgateway_ndc": "airgateway_ndc",
    "airgateway": "airgateway_ndc",
}

_SOURCE_TO_PROVIDER = {
    "picasso": "picasso_redbox",
    "duffel_ndc": "duffel_ndc",
    "kiwi_tequila": "kiwi_tequila",
    "airgateway_ndc": "airgateway_ndc",
}


class CredentialRouter:
    """
    Builds API clients from vault-stored credentials for credential-aware
    search and booking dispatch.

    Used by SearchOrchestrator and BookingDispatcher to route through
    the credential network when a tenant doesn't have their own credentials
    for a given provider.
    """

    def __init__(self, network, vault, db_session=None):
        """
        Args:
            network: CredentialNetwork instance (routing + membership).
            vault: CredentialVault instance (encrypted credential storage).
            db_session: Optional SQLAlchemy session for network accounting.
                        When provided, routing events are logged to the DB.
        """
        self._network = network
        self._vault = vault
        self._db_session = db_session

    def get_routed_clients(
        self,
        requester_tenant_id: str,
        requested_sources: Optional[List[str]] = None,
        vertical: str = "flights",
        strategy: str = "balanced",
    ) -> Dict[str, dict]:
        """
        Build search/booking clients for a tenant, routing through the
        credential network when needed.

        For each requested source:
        1. Check if requester owns credentials for that provider → Tier 1
        2. If not, route through the network → Tier 2/3

        Args:
            requester_tenant_id: Who's requesting (their tenant ID).
            requested_sources: List of source names to build clients for
                (e.g., ["picasso", "duffel_ndc"]). If None, tries all known.
            vertical: "flights", "hotels", etc.
            strategy: "balanced", "best_price", "best_reliability".

        Returns:
            Dict mapping source_name → {
                "client": API client instance (or None if unavailable),
                "routing": RoutingResult (or None if own credentials),
                "tier": 1 for own, 2/3 for network-routed,
                "owner_tenant_id": who owns the credential,
            }
        """
        if requested_sources is None:
            requested_sources = list(_SOURCE_TO_PROVIDER.keys())

        results = {}

        for source in requested_sources:
            provider_id = _SOURCE_TO_PROVIDER.get(source, source)

            # Check if requester has their own credentials
            own_creds = self._find_own_credential(requester_tenant_id, provider_id)

            if own_creds:
                # Tier 1: own credentials, zero routing fee
                client = self._build_client_from_credential(
                    provider_id, own_creds["credential_id"], requester_tenant_id
                )
                if client:
                    results[source] = {
                        "client": client,
                        "routing": None,
                        "tier": 1,
                        "owner_tenant_id": requester_tenant_id,
                    }
                    logger.info(
                        "Tenant %s using own credentials for %s (Tier 1)",
                        requester_tenant_id, source,
                    )
                continue

            # Route through network (Tier 2/3)
            routing_result = self._route_through_network(
                requester_tenant_id, provider_id, vertical, strategy,
            )

            if routing_result:
                client = self._build_client_from_credential(
                    provider_id,
                    routing_result.credential_id,
                    routing_result.owner_tenant_id,
                )
                if client:
                    results[source] = {
                        "client": client,
                        "routing": routing_result,
                        "tier": routing_result.routing_tier,
                        "owner_tenant_id": routing_result.owner_tenant_id,
                    }
                    logger.info(
                        "Tenant %s routed to %s via %s (Tier %d)",
                        requester_tenant_id, source,
                        routing_result.owner_tenant_id,
                        routing_result.routing_tier,
                    )
                else:
                    logger.warning(
                        "Found credential for %s via network but failed to build client",
                        source,
                    )
            else:
                logger.debug(
                    "No credential available for %s (tenant=%s)",
                    source, requester_tenant_id,
                )

        return results

    def build_client(self, provider_id: str, raw_credentials: dict) -> Optional[Any]:
        """
        Instantiate an API client from decrypted credential data.

        Args:
            provider_id: Provider identifier (e.g., "picasso_redbox", "duffel_ndc").
            raw_credentials: Decrypted credential dict from vault.

        Returns:
            API client instance or None if provider unknown.
        """
        source = _PROVIDER_TO_SOURCE.get(provider_id, provider_id)

        if source == "picasso":
            return self._build_picasso_client(raw_credentials)
        elif source == "duffel_ndc":
            return self._build_duffel_client(raw_credentials)
        elif source == "kiwi_tequila":
            return self._build_kiwi_client(raw_credentials)
        elif source == "airgateway_ndc":
            return self._build_airgateway_client(raw_credentials)

        logger.warning("Unknown provider for client build: %s", provider_id)
        return None

    def confirm_booking(self, routing_result_id: str, execution_result: dict) -> bool:
        """
        Confirm a booking was successfully executed through the credential network.

        Records the execution result and triggers revenue tracking.

        Args:
            routing_result_id: The RoutingResult ID from search/route.
            execution_result: Dict with confirmation_code, transaction_amount_usd, etc.

        Returns:
            True if confirmation recorded, False otherwise.
        """
        if not self._network:
            return False
        try:
            self._network.confirm_execution(routing_result_id, execution_result)
            logger.info("Credential routing confirmed: %s", routing_result_id)
            return True
        except Exception as e:
            logger.warning("Failed to confirm credential routing: %s", e)
            return False

    def fail_booking(self, routing_result_id: str, reason: str) -> bool:
        """
        Record a booking failure for the credential network.

        Args:
            routing_result_id: The RoutingResult ID.
            reason: Why the booking failed.

        Returns:
            True if failure recorded, False otherwise.
        """
        if not self._network:
            return False
        try:
            self._network.fail_execution(routing_result_id, reason)
            logger.info("Credential routing failed: %s — %s", routing_result_id, reason)
            return True
        except Exception as e:
            logger.warning("Failed to record credential routing failure: %s", e)
            return False

    # ------------------------------------------------------------------
    # Query Cost Accounting — DB-backed event recording
    # ------------------------------------------------------------------

    def record_query(
        self,
        connection_id: int,
        router_key_hash: str,
        host_key_hash: str,
        credential_type: str = "",
        provider_system: str = "",
        origin: str = "",
        destination: str = "",
        market_code: str = "",
        response_time_ms: int = 0,
        success: bool = True,
        error_message: str = "",
        query_fee_usd: float = 0.0,
    ) -> Optional[str]:
        """
        Record a search query routed through the credential network.

        Creates a RoutingEvent and updates the NetworkConnection stats.
        Returns the event_id or None if DB not configured.
        """
        if not self._db_session:
            return None

        try:
            from picasso.agent.db_models import NetworkConnection, RoutingEvent

            event_id = str(uuid.uuid4())
            event = RoutingEvent(
                event_id=event_id,
                connection_id=connection_id,
                event_type="search",
                router_key_hash=router_key_hash,
                host_key_hash=host_key_hash,
                query_fee_usd=query_fee_usd,
                credential_type=credential_type,
                provider_system=provider_system,
                route_origin=origin,
                route_destination=destination,
                market_code=market_code,
                response_time_ms=response_time_ms,
                success=success,
                error_message=error_message if not success else None,
            )
            self._db_session.add(event)

            # Update connection stats
            conn = self._db_session.get(NetworkConnection, connection_id)
            if conn:
                conn.queries_this_month = (conn.queries_this_month or 0) + 1
                conn.total_queries_lifetime = (conn.total_queries_lifetime or 0) + 1
                if not success:
                    conn.error_count_this_month = (conn.error_count_this_month or 0) + 1
                # Rolling average response time
                if response_time_ms and conn.avg_response_time_ms:
                    conn.avg_response_time_ms = (
                        conn.avg_response_time_ms * 0.9 + response_time_ms * 0.1
                    )
                elif response_time_ms:
                    conn.avg_response_time_ms = float(response_time_ms)
                # Auto-health calculation
                conn.health = self._calculate_health(conn)

            self._db_session.commit()
            return event_id

        except Exception as e:
            logger.warning("Failed to record query event: %s", e)
            try:
                self._db_session.rollback()
            except Exception:
                pass
            return None

    def record_booking(
        self,
        connection_id: int,
        router_key_hash: str,
        host_key_hash: str,
        transaction_amount_usd: float,
        router_amount_usd: float,
        host_amount_usd: float,
        credential_type: str = "",
        provider_system: str = "",
        origin: str = "",
        destination: str = "",
        market_code: str = "",
        response_time_ms: int = 0,
        success: bool = True,
        error_message: str = "",
        query_fee_usd: float = 0.0,
    ) -> Optional[str]:
        """
        Record a booking routed through the credential network.

        Creates a RoutingEvent with financial data and updates connection stats.
        Returns the event_id or None if DB not configured.
        """
        if not self._db_session:
            return None

        try:
            from picasso.agent.db_models import NetworkConnection, RoutingEvent

            event_type = "booking" if success else "failure"
            event_id = str(uuid.uuid4())
            event = RoutingEvent(
                event_id=event_id,
                connection_id=connection_id,
                event_type=event_type,
                router_key_hash=router_key_hash,
                host_key_hash=host_key_hash,
                query_fee_usd=query_fee_usd,
                transaction_amount_usd=transaction_amount_usd,
                router_amount_usd=router_amount_usd,
                host_amount_usd=host_amount_usd,
                credential_type=credential_type,
                provider_system=provider_system,
                route_origin=origin,
                route_destination=destination,
                market_code=market_code,
                response_time_ms=response_time_ms,
                success=success,
                error_message=error_message if not success else None,
            )
            self._db_session.add(event)

            # Update connection stats
            conn = self._db_session.get(NetworkConnection, connection_id)
            if conn:
                if success:
                    conn.bookings_this_month = (conn.bookings_this_month or 0) + 1
                    conn.total_bookings_lifetime = (conn.total_bookings_lifetime or 0) + 1
                    conn.revenue_earned_this_month_usd = (
                        (conn.revenue_earned_this_month_usd or 0.0) + router_amount_usd
                    )
                    conn.revenue_paid_this_month_usd = (
                        (conn.revenue_paid_this_month_usd or 0.0) + host_amount_usd
                    )
                else:
                    conn.error_count_this_month = (conn.error_count_this_month or 0) + 1
                conn.health = self._calculate_health(conn)

            self._db_session.commit()
            return event_id

        except Exception as e:
            logger.warning("Failed to record booking event: %s", e)
            try:
                self._db_session.rollback()
            except Exception:
                pass
            return None

    @staticmethod
    def _calculate_health(conn) -> str:
        """Calculate connection health from error rate and response time."""
        queries = conn.queries_this_month or 0
        errors = conn.error_count_this_month or 0
        avg_rt = conn.avg_response_time_ms or 0

        if queries == 0:
            return "green"

        error_rate = errors / queries
        if error_rate > 0.15 or avg_rt > 15000:
            return "red"
        elif error_rate > 0.05 or avg_rt > 8000:
            return "yellow"
        return "green"

    # ------------------------------------------------------------------
    # Internal: Credential Discovery
    # ------------------------------------------------------------------

    def _find_own_credential(
        self, tenant_id: str, provider_id: str
    ) -> Optional[dict]:
        """
        Check if a tenant owns active credentials for a given provider.

        Returns the credential dict or None.
        """
        try:
            creds = self._vault.list(tenant_id)
            for cred in creds:
                if cred.get("provider_id") == provider_id:
                    return cred
            # Also check the base name (picasso vs picasso_redbox)
            alt_provider = _PROVIDER_TO_SOURCE.get(provider_id, provider_id)
            for cred in creds:
                if cred.get("provider_id") == alt_provider:
                    return cred
        except Exception as e:
            logger.warning("Error checking own credentials: %s", e)
        return None

    def _route_through_network(
        self,
        requester_tenant_id: str,
        provider_id: str,
        vertical: str = "flights",
        strategy: str = "balanced",
    ) -> Optional[Any]:
        """
        Route a request through the credential network.

        Returns a RoutingResult or None if no route available.
        """
        if not self._network:
            return None

        try:
            from anastasia.credentials.network import RoutingRequest
            request = RoutingRequest(
                requester_tenant_id=requester_tenant_id,
                provider_id=provider_id,
                vertical=vertical,
                strategy=strategy,
            )
            return self._network.route_booking(request)
        except Exception as e:
            logger.warning("Network routing failed for %s: %s", provider_id, e)
            return None

    def _build_client_from_credential(
        self,
        provider_id: str,
        credential_id: str,
        owner_tenant_id: str,
    ) -> Optional[Any]:
        """
        Retrieve a credential from the vault and build an API client from it.

        The credential_id format from the network may be "tenant:provider".
        We extract the actual vault credential ID and retrieve it.
        """
        try:
            # Credential IDs from network may be "tenant_id:provider_id" format
            vault_id = credential_id
            if ":" in credential_id:
                # Network stores composite IDs — look up by tenant+provider
                parts = credential_id.split(":", 1)
                tenant = parts[0]
                provider = parts[1] if len(parts) > 1 else provider_id
                # Find the actual vault credential
                creds = self._vault.list(tenant)
                for c in creds:
                    if c.get("provider_id") in (provider, provider_id):
                        vault_id = c["credential_id"]
                        break
                else:
                    logger.warning(
                        "No vault credential found for %s:%s", tenant, provider
                    )
                    return None

            # Retrieve decrypted credentials
            raw_creds = self._vault.retrieve(vault_id, requester_tenant_id=owner_tenant_id)
            if not raw_creds:
                logger.warning("Failed to decrypt credential %s", vault_id)
                return None

            return self.build_client(provider_id, raw_creds)

        except Exception as e:
            logger.warning("Error building client from credential %s: %s", credential_id, e)
            return None

    # ------------------------------------------------------------------
    # Internal: Client Builders
    # ------------------------------------------------------------------

    def _build_duffel_client(self, creds: dict) -> Optional[Any]:
        """Build a DuffelClient from vault credentials."""
        try:
            from duffel_client import DuffelClient
            access_token = creds.get("access_token") or creds.get("token")
            if not access_token:
                logger.warning("Duffel credential missing access_token")
                return None
            return DuffelClient(access_token=access_token)
        except ImportError:
            logger.warning("duffel_client module not available")
            return None

    def _build_picasso_client(self, creds: dict) -> Optional[Any]:
        """
        Build a Picasso/Redbox search+booking adapter from vault credentials.

        The Picasso client uses session tokens obtained via Keycloak auth.
        Vault stores the session token; the daemon bridge handles refresh.
        """
        try:
            from picasso_client import search_with_picasso, book_flight
            # For Picasso, we return the book_flight callable which the
            # dispatcher expects. The session token is managed by the
            # PicassoClient singleton via environment variables.
            # When credential routing is active with Picasso daemon bridge,
            # the credential includes the session_token directly.
            session_token = creds.get("session_token") or creds.get("token")
            if session_token:
                # Create a partial that injects the token
                import functools
                return functools.partial(book_flight, session_token=session_token)
            # Fallback: use default env-var-based client
            return book_flight
        except ImportError:
            logger.warning("picasso_client module not available")
            return None

    def _build_kiwi_client(self, creds: dict) -> Optional[Any]:
        """Build a KiwiClient from vault credentials."""
        try:
            from kiwi_client import KiwiClient
            api_key = creds.get("api_key") or creds.get("apikey")
            if not api_key:
                logger.warning("Kiwi credential missing api_key")
                return None
            return KiwiClient(api_key=api_key)
        except ImportError:
            logger.warning("kiwi_client module not available")
            return None

    def _build_airgateway_client(self, creds: dict) -> Optional[Any]:
        """Build an AirGatewayClient from vault credentials."""
        try:
            from picasso.airgateway import AirGatewayClient
            api_key = creds.get("api_key") or creds.get("token")
            if not api_key:
                logger.warning("AirGateway credential missing api_key")
                return None
            return AirGatewayClient(api_key=api_key)
        except ImportError:
            logger.warning("airgateway client module not available")
            return None
