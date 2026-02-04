"""
Payment Ramp Network Integration (Build #86)

Provides on-ramp/off-ramp provider registry, FX cost estimation,
and virtual card pipeline for universal Phoenix payment infrastructure.
Serves ALL proxy browsing — arbitrage, free shopping, and direct purchases.
"""

import json
import logging
import os
import time
import uuid
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ============================================================
# Default Ramp Provider Data
# ============================================================

RAMP_PROVIDERS = [
    {
        'provider_code': 'coinbase_onramp',
        'provider_name': 'Coinbase Onramp',
        'description': 'Zero-fee USDC on Base for US users. Card, ACH, or Coinbase balance.',
        'widget_base_url': 'https://pay.coinbase.com/buy',
        'widget_type': 'redirect',
        'supported_countries': ['US'],
        'supported_fiat_methods': ['card', 'ach', 'coinbase_balance'],
        'supported_crypto_out': ['USDC'],
        'fee_estimate_pct': 0.0,
        'kyc_required': True,
        'api_key_env_var': 'COINBASE_ONRAMP_APP_ID',
        'priority': 0,
    },
    {
        'provider_code': 'stripe_onramp',
        'provider_name': 'Stripe Crypto Onramp',
        'description': 'Fiat-to-crypto via Stripe. Card and bank transfer in US, CA, GB, and EU.',
        'widget_base_url': 'https://crypto-onramp.stripe.com',
        'widget_type': 'iframe',
        'supported_countries': [
            'US', 'CA', 'GB', 'DE', 'FR', 'IT', 'ES', 'NL', 'AT', 'CH',
            'SE', 'NO', 'DK', 'FI', 'PL', 'CZ', 'PT', 'IE', 'BE', 'LU',
        ],
        'supported_fiat_methods': ['card', 'bank_transfer'],
        'supported_crypto_out': ['USDC', 'ETH'],
        'fee_estimate_pct': 2.0,
        'kyc_required': False,
        'api_key_env_var': 'STRIPE_SECRET_KEY',
        'priority': 1,
    },
    {
        'provider_code': 'moonpay',
        'provider_name': 'MoonPay',
        'description': '160+ countries. Card, PayPal, Venmo, ACH, SEPA, bank transfer.',
        'widget_base_url': 'https://buy.moonpay.com',
        'widget_type': 'redirect',
        'supported_countries': [
            'US', 'CA', 'GB', 'AU', 'NZ',
            'DE', 'FR', 'IT', 'ES', 'NL', 'AT', 'CH', 'SE', 'NO', 'DK',
            'FI', 'PL', 'CZ', 'PT', 'IE', 'GR', 'RO', 'BE', 'LU',
            'JP', 'KR', 'SG', 'HK', 'TH', 'MY',
            'BR', 'MX', 'AR', 'CO', 'CL', 'PE',
            'AE', 'SA', 'TR', 'IL', 'EG',
            'IN', 'ID', 'PH', 'VN', 'ZA', 'NG', 'KE',
        ],
        'supported_fiat_methods': ['card', 'bank_transfer', 'paypal', 'venmo', 'ach', 'sepa'],
        'supported_crypto_out': ['USDC', 'XRP', 'ETH', 'BTC'],
        'fee_estimate_pct': 3.5,
        'kyc_required': True,
        'api_key_env_var': 'MOONPAY_API_KEY',
        'priority': 2,
    },
    {
        'provider_code': 'transak',
        'provider_name': 'Transak',
        'description': '169 countries, 76 fiat currencies. UPI for India, PIX for Brazil, SEPA for EU.',
        'widget_base_url': 'https://global.transak.com',
        'widget_type': 'iframe',
        'supported_countries': [
            'US', 'CA', 'GB', 'AU', 'NZ',
            'DE', 'FR', 'IT', 'ES', 'NL', 'AT', 'CH', 'SE', 'NO', 'DK',
            'FI', 'PL', 'CZ', 'PT', 'IE', 'GR', 'RO', 'BE', 'LU',
            'JP', 'KR', 'SG', 'HK', 'TH', 'MY',
            'BR', 'MX', 'AR', 'CO', 'CL', 'PE',
            'AE', 'SA', 'TR', 'IL', 'EG',
            'IN', 'ID', 'PH', 'VN', 'ZA', 'NG', 'KE',
        ],
        'supported_fiat_methods': ['card', 'bank_transfer', 'upi', 'sepa', 'pix'],
        'supported_crypto_out': ['USDC', 'XRP', 'ETH', 'BTC'],
        'fee_estimate_pct': 2.5,
        'kyc_required': True,
        'api_key_env_var': 'TRANSAK_API_KEY',
        'priority': 3,
    },
]

# ============================================================
# FX Cost Estimates (static, conservative)
# ============================================================

FX_COST_ESTIMATES = {
    'FIVE_EYES': {
        'card_spread_pct': 1.0,
        'crypto_spread_pct': 0.5,
        'notes': 'Low FX cost, same-network cards accepted broadly',
    },
    'SEPA': {
        'card_spread_pct': 1.5,
        'crypto_spread_pct': 0.5,
        'notes': 'EUR base, low spread for EUR-denominated cards',
    },
    'APAC_INTL': {
        'card_spread_pct': 3.0,
        'crypto_spread_pct': 0.5,
        'notes': 'Higher FX for non-local cards, virtual card recommended',
    },
    'LATAM': {
        'card_spread_pct': 4.0,
        'crypto_spread_pct': 0.5,
        'notes': 'Variable FX rates, virtual card strongly recommended',
    },
    'MENA': {
        'card_spread_pct': 3.5,
        'crypto_spread_pct': 0.5,
        'notes': 'Moderate FX spread, card acceptance varies by country',
    },
}

FIAT_METHOD_LABELS = {
    'card': 'Card',
    'bank_transfer': 'Bank',
    'ach': 'ACH',
    'sepa': 'SEPA',
    'upi': 'UPI',
    'pix': 'PIX',
    'paypal': 'PayPal',
    'venmo': 'Venmo',
    'coinbase_balance': 'Coinbase',
}


# ============================================================
# Ramp Provider Engine
# ============================================================

class RampProviderEngine:
    """Registry and recommendation engine for on-ramp/off-ramp providers."""

    def __init__(self):
        self._provider_cache = None
        self._cache_at = 0
        self._cache_ttl = 300  # 5 minutes

    def _load_providers(self) -> List[dict]:
        """Load providers from DB with fallback to defaults."""
        now = time.time()
        if self._provider_cache is not None and (now - self._cache_at) < self._cache_ttl:
            return self._provider_cache

        try:
            from models import RampProvider
            db_providers = RampProvider.query.filter_by(is_active=True).order_by(
                RampProvider.priority.asc()
            ).all()
            if db_providers:
                self._provider_cache = [p.to_dict() for p in db_providers]
                self._cache_at = now
                return self._provider_cache
        except Exception:
            pass

        # Fallback to built-in defaults
        self._provider_cache = sorted(RAMP_PROVIDERS, key=lambda p: p.get('priority', 10))
        self._cache_at = now
        return self._provider_cache

    def invalidate_cache(self):
        """Force cache refresh on next load."""
        self._provider_cache = None
        self._cache_at = 0

    def get_providers_for_country(self, country_code: str) -> List[dict]:
        """Return ramp providers available in a given country, sorted by priority."""
        providers = self._load_providers()
        country = country_code.upper()
        result = []
        for p in providers:
            countries = p.get('supported_countries', [])
            if country in countries:
                result.append(p)
        return result

    def get_recommended_ramps(self, user_id: int) -> List[dict]:
        """Recommend best ramp providers for a user based on their home_market."""
        try:
            from models import User, UserRampPreference
            user = User.query.get(user_id)
            home = user.home_market.upper() if user and user.home_market else 'US'
        except Exception:
            home = 'US'

        available = self.get_providers_for_country(home)

        # Check user preference
        default_code = None
        try:
            from models import UserRampPreference
            pref = UserRampPreference.query.filter_by(
                user_id=user_id, is_default=True
            ).first()
            if pref:
                default_code = pref.provider_code
        except Exception:
            pass

        result = []
        for p in available:
            entry = dict(p)
            entry['is_user_default'] = (p['provider_code'] == default_code)
            entry['is_best_for_country'] = (p == available[0]) if available else False

            # Check if API key is configured
            env_var = p.get('api_key_env_var')
            entry['is_configured'] = bool(os.environ.get(env_var)) if env_var else False

            # Generate fiat method summary
            methods = p.get('supported_fiat_methods', [])
            entry['fiat_methods_summary'] = ', '.join(
                FIAT_METHOD_LABELS.get(m, m.title()) for m in methods[:4]
            )
            result.append(entry)

        return result

    def generate_widget_url(self, provider_code: str, params: dict) -> Optional[str]:
        """Generate widget/redirect URL for a ramp provider.

        params: wallet_address, crypto_currency, fiat_currency, fiat_amount
        Returns None if provider not found or API key not configured.
        """
        providers = self._load_providers()
        provider = None
        for p in providers:
            if p['provider_code'] == provider_code:
                provider = p
                break
        if not provider:
            return None

        base_url = provider.get('widget_base_url', '')
        wallet = params.get('wallet_address', '')
        crypto = params.get('crypto_currency', 'USDC')
        fiat = params.get('fiat_currency', 'USD')
        amount = params.get('fiat_amount')

        if provider_code == 'coinbase_onramp':
            app_id = os.environ.get('COINBASE_ONRAMP_APP_ID', '')
            url = f"{base_url}?appId={app_id}&destinationWallets=%5B%7B%22address%22%3A%22{wallet}%22%2C%22blockchains%22%3A%5B%22base%22%5D%7D%5D"
            if amount:
                url += f"&presetFiatAmount={amount}"
            return url

        elif provider_code == 'stripe_onramp':
            # Stripe onramp is typically embedded via their SDK, return base URL
            url = f"{base_url}?wallet_address={wallet}&crypto_currency={crypto}"
            if amount:
                url += f"&source_amount={amount}&source_currency={fiat}"
            return url

        elif provider_code == 'moonpay':
            api_key = os.environ.get('MOONPAY_API_KEY', '')
            crypto_code = crypto.lower()
            url = f"{base_url}?apiKey={api_key}&currencyCode={crypto_code}&walletAddress={wallet}&baseCurrencyCode={fiat.lower()}"
            if amount:
                url += f"&baseCurrencyAmount={amount}"
            return url

        elif provider_code == 'transak':
            api_key = os.environ.get('TRANSAK_API_KEY', '')
            url = f"{base_url}?apiKey={api_key}&cryptoCurrencyCode={crypto}&walletAddress={wallet}&fiatCurrency={fiat}"
            if amount:
                url += f"&fiatAmount={amount}"
            return url

        # Generic fallback
        return base_url

    def estimate_ramp_cost(self, provider_code: str, fiat_amount: float) -> dict:
        """Estimate fees for a given ramp provider and amount."""
        providers = self._load_providers()
        for p in providers:
            if p['provider_code'] == provider_code:
                fee_pct = p.get('fee_estimate_pct', 0.0)
                fee_usd = round(fiat_amount * fee_pct / 100, 2)
                return {
                    'fee_pct': fee_pct,
                    'fee_usd': fee_usd,
                    'receive_amount': round(fiat_amount - fee_usd, 2),
                    'crypto_currency': (p.get('supported_crypto_out', ['USDC']) or ['USDC'])[0],
                }
        return {'fee_pct': 0, 'fee_usd': 0, 'receive_amount': fiat_amount, 'crypto_currency': 'USDC'}

    def seed_default_providers(self):
        """Populate ramp_providers table from built-in defaults if empty."""
        try:
            from models import db, RampProvider
            existing = RampProvider.query.first()
            if existing:
                logger.info("Ramp providers already seeded, skipping")
                return

            for pdata in RAMP_PROVIDERS:
                provider = RampProvider(
                    provider_code=pdata['provider_code'],
                    provider_name=pdata['provider_name'],
                    description=pdata.get('description', ''),
                    widget_base_url=pdata.get('widget_base_url', ''),
                    widget_type=pdata.get('widget_type', 'redirect'),
                    supported_countries=json.dumps(pdata.get('supported_countries', [])),
                    supported_fiat_methods=json.dumps(pdata.get('supported_fiat_methods', [])),
                    supported_crypto_out=json.dumps(pdata.get('supported_crypto_out', [])),
                    fee_estimate_pct=pdata.get('fee_estimate_pct', 0.0),
                    kyc_required=pdata.get('kyc_required', True),
                    api_key_env_var=pdata.get('api_key_env_var'),
                    priority=pdata.get('priority', 10),
                    is_active=True,
                )
                db.session.add(provider)

            db.session.commit()
            logger.info(f"Seeded {len(RAMP_PROVIDERS)} default ramp providers")
            self.invalidate_cache()
        except Exception as e:
            logger.error(f"Failed to seed ramp providers: {e}")
            try:
                from models import db
                db.session.rollback()
            except Exception:
                pass


# ============================================================
# Virtual Card Pipeline (Stripe Issuing — stubbed)
# ============================================================

class VirtualCardPipeline:
    """Models the USDC settlement + Stripe Issuing flow.

    Actual Stripe Issuing API calls are stubbed until compliance approval.
    The data model and status machine exist so the system can track state
    once the API integration goes live.
    """

    def create_virtual_card_request(
        self,
        user_id: int,
        amount_usdc: float,
        merchant_country: str,
        purpose: str = 'browsing',
        deal_id: Optional[str] = None,
        deal_type: Optional[str] = None,
    ) -> dict:
        """Create a VirtualCardTransaction record."""
        try:
            from models import db, VirtualCardTransaction

            txn_id = f"VCT-{uuid.uuid4().hex[:12]}"
            context = 'arbitrage' if deal_id and purpose != 'direct' else purpose

            txn = VirtualCardTransaction(
                transaction_id=txn_id,
                user_id=user_id,
                usdc_amount=amount_usdc,
                merchant_country=merchant_country.upper(),
                deal_id=deal_id,
                deal_type=deal_type,
                purchase_context=context,
                status='initiated',
            )
            db.session.add(txn)
            db.session.commit()

            return {
                'success': True,
                'transaction_id': txn_id,
                'status': 'initiated',
                'usdc_amount': amount_usdc,
                'merchant_country': merchant_country,
                'purchase_context': context,
                'message': 'Virtual card request created. Send XRP/RLUSD to fund.',
            }
        except Exception as e:
            logger.error(f"Failed to create virtual card request: {e}")
            return {'success': False, 'error': str(e)}

    def fund_virtual_card(self, transaction_id: str) -> dict:
        """STUB: Would call Stripe Issuing to create and fund a virtual card."""
        try:
            from models import db, VirtualCardTransaction

            txn = VirtualCardTransaction.query.filter_by(transaction_id=transaction_id).first()
            if not txn:
                return {'success': False, 'error': 'Transaction not found'}
            if txn.status != 'usdc_received':
                return {'success': False, 'error': f'Invalid status: {txn.status}, expected usdc_received'}

            # STUB — in production this would:
            # 1. stripe.issuing.Card.create(type='virtual', currency='usd')
            # 2. Fund the card from platform balance
            txn.stripe_card_id = f"ic_stub_{uuid.uuid4().hex[:8]}"
            txn.card_funded_amount = txn.usdc_amount
            txn.card_funded_at = datetime.utcnow()
            txn.status = 'card_funded'
            db.session.commit()

            return {
                'success': True,
                'transaction_id': transaction_id,
                'status': 'card_funded',
                'stripe_card_id': txn.stripe_card_id,
                'funded_amount': txn.card_funded_amount,
                'message': 'STUB: Virtual card funded. Ready for vendor charge.',
            }
        except Exception as e:
            logger.error(f"Failed to fund virtual card: {e}")
            return {'success': False, 'error': str(e)}

    def charge_virtual_card(self, transaction_id: str, merchant_details: dict) -> dict:
        """STUB: Would authorize a charge on the virtual card."""
        try:
            from models import db, VirtualCardTransaction

            txn = VirtualCardTransaction.query.filter_by(transaction_id=transaction_id).first()
            if not txn:
                return {'success': False, 'error': 'Transaction not found'}
            if txn.status != 'card_funded':
                return {'success': False, 'error': f'Invalid status: {txn.status}, expected card_funded'}

            txn.merchant_name = merchant_details.get('merchant_name', '')
            txn.charge_amount_usd = merchant_details.get('amount_usd', txn.card_funded_amount)
            txn.charge_currency = merchant_details.get('currency', 'USD')
            txn.charge_amount_local = merchant_details.get('amount_local', txn.charge_amount_usd)
            txn.charged_at = datetime.utcnow()
            txn.status = 'card_charged'

            # Estimate FX cost
            if txn.charge_currency != 'USD' and txn.charge_amount_usd and txn.usdc_amount:
                txn.fx_spread_pct = round(
                    abs(txn.charge_amount_usd - txn.usdc_amount) / txn.usdc_amount * 100, 2
                )
            txn.total_fees_usd = round((txn.fx_spread_pct or 0) / 100 * txn.usdc_amount, 2)

            db.session.commit()

            return {
                'success': True,
                'transaction_id': transaction_id,
                'status': 'card_charged',
                'message': 'STUB: Vendor charge authorized.',
            }
        except Exception as e:
            logger.error(f"Failed to charge virtual card: {e}")
            return {'success': False, 'error': str(e)}

    def get_pipeline_status(self, transaction_id: str) -> dict:
        """Return the current state of a virtual card pipeline transaction."""
        try:
            from models import VirtualCardTransaction

            txn = VirtualCardTransaction.query.filter_by(transaction_id=transaction_id).first()
            if not txn:
                return {'success': False, 'error': 'Transaction not found'}
            return {'success': True, 'transaction': txn.to_dict()}
        except Exception as e:
            return {'success': False, 'error': str(e)}


# ============================================================
# Module-level singletons
# ============================================================

ramp_engine = RampProviderEngine()
virtual_card_pipeline = VirtualCardPipeline()
