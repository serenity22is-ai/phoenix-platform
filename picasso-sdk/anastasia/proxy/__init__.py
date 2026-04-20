"""
Proxy Neuron — Multi-provider proxy abstraction for POS arbitrage.

Manages residential proxy connections across vendors (Bright Data, Webshare)
with country-targeted routing, Scraping Browser CDP for airline checkout,
and anti-detection market rotation.

Architecture:
- ProxyProvider ABC → BrightDataProvider (primary) + WebshareProvider (fallback)
- MarketRouter → POS market selection, rotation, per-route learning
- ProxyModule → NeuronModule interface, provider lifecycle, health monitoring

MYSTES calls this neuron for ALL proxy operations. APAi subscribers inherit it
automatically via the ANASTASiA platform deployment.

MYSTES KYRIOS LLC — Confidential.
"""

import logging
import os
from typing import Any, Dict, List, Optional

from ..core.events import Event, EventBus, EventType
from ..core.registry import NeuronModule
from .market_router import MARKET_CONFIG, MarketRouter
from .providers import BrightDataProvider, ProxyProvider, WebshareProvider

logger = logging.getLogger(__name__)

__all__ = [
    "ProxyModule",
    "BrightDataProvider",
    "WebshareProvider",
    "MarketRouter",
    "MARKET_CONFIG",
]


class ProxyModule(NeuronModule):
    """
    ANASTASiA Proxy Neuron — residential proxy infrastructure for POS arbitrage.

    Provides:
    - Country-targeted residential proxy for search (IP geolocation = POS pricing)
    - Scraping Browser CDP for airline checkout (sticky session, CAPTCHA solving)
    - Market routing with anti-detection rotation
    - Provider failover (Bright Data → Webshare)
    """

    def __init__(self):
        self._event_bus: Optional[EventBus] = None
        self._providers: Dict[str, ProxyProvider] = {}
        self._active_provider: Optional[str] = None
        self._market_router: Optional[MarketRouter] = None
        self._session_count: int = 0
        self._failure_count: int = 0
        self._initialized: bool = False

    @property
    def name(self) -> str:
        return "proxy"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def dependencies(self) -> List[str]:
        return []  # Foundational — no dependencies

    def initialize(self, event_bus: EventBus, config: Dict[str, Any]) -> None:
        self._event_bus = event_bus

        # Initialize providers
        bd = BrightDataProvider()
        ws = WebshareProvider()

        if bd.is_configured():
            self._providers["brightdata"] = bd
        if ws.is_configured():
            self._providers["webshare"] = ws

        # Select active provider from config or auto-detect
        preferred = config.get(
            "proxy_provider",
            os.environ.get("PROXY_PROVIDER", "brightdata"),
        )
        if preferred in self._providers:
            self._active_provider = preferred
        elif self._providers:
            # Fall back to first available
            self._active_provider = next(iter(self._providers))
        else:
            self._active_provider = None
            logger.warning("No proxy providers configured")

        # Initialize market router
        priority_markets = config.get("proxy_priority_markets")
        self._market_router = MarketRouter(
            priority_markets=priority_markets,
            max_queries_per_market_per_min=config.get(
                "proxy_max_queries_per_market_per_min", 30
            ),
            cooldown_seconds=config.get("proxy_cooldown_seconds", 2),
        )

        self._initialized = True

        provider_names = list(self._providers.keys())
        logger.info(
            "Proxy neuron initialized: active=%s, providers=%s, markets=%d",
            self._active_provider,
            provider_names,
            len(MARKET_CONFIG),
        )

    def health_check(self) -> Dict[str, Any]:
        if not self._initialized:
            return {"healthy": False, "details": "Not initialized"}

        has_provider = self._active_provider is not None
        return {
            "healthy": has_provider,
            "details": (
                f"Active: {self._active_provider}, "
                f"{len(self._providers)} providers"
                if has_provider
                else "No proxy providers configured"
            ),
            "active_provider": self._active_provider,
            "providers": list(self._providers.keys()),
            "sessions": self._session_count,
            "failures": self._failure_count,
            "market_router": self._market_router.stats if self._market_router else {},
        }

    def shutdown(self) -> None:
        self._initialized = False
        logger.info("Proxy neuron shut down")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def market_router(self) -> MarketRouter:
        """Access the market router for POS selection."""
        if self._market_router is None:
            raise RuntimeError("ProxyModule not initialized")
        return self._market_router

    def get_proxy(self, market: str, provider: Optional[str] = None) -> Dict[str, str]:
        """Get proxy config for a market.

        Args:
            market: ISO country code (e.g., "DK", "DE")
            provider: Specific provider name, or None for active

        Returns:
            dict with keys: server, username, password, country_code
        """
        p = self._get_provider(provider)
        proxy = p.get_proxy(market)

        self._market_router.record_query(market)
        self._session_count += 1

        if self._event_bus:
            self._event_bus.publish(Event(
                type=EventType.PROXY_SESSION_STARTED,
                source="proxy",
                data={
                    "market": market,
                    "provider": p.name,
                    "purpose": "search",
                },
            ))

        return proxy

    def get_scraping_browser_url(self, market: str) -> str:
        """Get Scraping Browser CDP URL for airline checkout.

        Connects Playwright via:
            browser = await pw.chromium.connect_over_cdp(url)

        Features:
        - Sticky session (same IP for entire checkout)
        - Auto CAPTCHA solving
        - Fingerprint randomization
        - Country-targeted residential IP

        Args:
            market: ISO country code for POS pricing

        Returns:
            WebSocket URL for CDP connection

        Raises:
            RuntimeError: If no provider supports Scraping Browser
        """
        # Prefer active provider, fall back to any that supports CDP
        provider = self._providers.get(self._active_provider)
        if provider and provider.supports_scraping_browser():
            url = provider.get_scraping_browser_url(market)
        else:
            # Find any provider with CDP support
            for p in self._providers.values():
                if p.supports_scraping_browser():
                    url = p.get_scraping_browser_url(market)
                    break
            else:
                raise RuntimeError(
                    "No proxy provider supports Scraping Browser CDP. "
                    "Configure Bright Data credentials."
                )

        self._session_count += 1

        if self._event_bus:
            self._event_bus.publish(Event(
                type=EventType.PROXY_SESSION_STARTED,
                source="proxy",
                data={
                    "market": market,
                    "provider": provider.name if provider else "unknown",
                    "purpose": "booking",
                },
            ))

        return url

    def record_session_result(
        self,
        market: str,
        success: bool,
        purpose: str = "search",
        error: Optional[str] = None,
    ) -> None:
        """Record the result of a proxy session for monitoring."""
        if not success:
            self._failure_count += 1

        event_type = (
            EventType.PROXY_SESSION_COMPLETED
            if success
            else EventType.PROXY_SESSION_FAILED
        )

        if self._event_bus:
            self._event_bus.publish(Event(
                type=event_type,
                source="proxy",
                data={
                    "market": market,
                    "success": success,
                    "purpose": purpose,
                    "error": error,
                },
            ))

    def switch_provider(self, provider_name: str) -> bool:
        """Switch active proxy provider.

        Returns True if switch succeeded.
        """
        if provider_name not in self._providers:
            logger.error("Unknown provider: %s", provider_name)
            return False

        old = self._active_provider
        self._active_provider = provider_name
        logger.info("Proxy provider switched: %s → %s", old, provider_name)

        if self._event_bus:
            self._event_bus.publish(Event(
                type=EventType.PROXY_PROVIDER_SWITCHED,
                source="proxy",
                data={"old": old, "new": provider_name},
            ))

        return True

    def is_configured(self) -> bool:
        """Return True if at least one provider is configured."""
        return bool(self._providers)

    def has_scraping_browser(self) -> bool:
        """Return True if any provider supports Scraping Browser CDP."""
        return any(p.supports_scraping_browser() for p in self._providers.values())

    def get_market_config(self, market: str) -> Optional[Dict]:
        """Return full config for a market code."""
        return MARKET_CONFIG.get(market.upper())

    def select_markets(
        self,
        origin: str,
        destination: str,
        max_markets: int = 3,
    ) -> List[str]:
        """Select best POS markets for a route (delegates to MarketRouter)."""
        return self._market_router.select_markets(origin, destination, max_markets)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_provider(self, provider_name: Optional[str] = None) -> ProxyProvider:
        """Get a provider by name or return the active one."""
        name = provider_name or self._active_provider
        if not name or name not in self._providers:
            raise RuntimeError(
                f"Proxy provider '{name}' not available. "
                f"Configured: {list(self._providers.keys())}"
            )
        return self._providers[name]
