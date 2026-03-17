"""
Payment Zone Compatibility Engine (Build #85)

Determines which markets a user can purchase in based on their payment
instruments (cards, crypto wallets) and a data-driven compatibility matrix.
Filters arbitrage searches to only payment-compatible zones.

Core concepts:
- PaymentZoneRule: card brand X, issued in country Y, accepted in country Z
- PaymentInteropGroup: clusters of countries with shared payment infra (SEPA, Five Eyes)
- Acceptance levels: high > medium > low > none
- Wildcard '*' for issuing/merchant country = applies globally
- XRPL/crypto bypass: verified wallet holders get universal access via virtual card

Usage:
    from payment_compatibility import payment_compat_engine

    # User's reachable markets
    markets = payment_compat_engine.get_reachable_countries(user_id=42)

    # Filter zones pre-dispatch
    filtered = payment_compat_engine.filter_zones(["JP-KT", "DE-NW"], user_id=42)

    # Annotate a deal
    compat = payment_compat_engine.assess_deal_compatibility("JP", user_id=42)
"""

import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACCEPTANCE_LEVELS = {
    'high': 3,
    'medium': 2,
    'low': 1,
    'none': 0,
}

# All countries with geographic zones in the system
ALL_MARKET_COUNTRIES = [
    'US', 'CA', 'GB', 'DE', 'FR', 'IT', 'ES', 'NL', 'AT', 'CH', 'SE', 'NO',
    'DK', 'FI', 'PL', 'CZ', 'PT', 'IE', 'GR', 'RO', 'BE', 'LU',
    'JP', 'KR', 'SG', 'HK', 'TH', 'MY', 'IN', 'AU', 'NZ',
    'BR', 'MX', 'AR', 'CO', 'CL', 'PE',
    'AE', 'SA', 'TR', 'IL', 'EG', 'ZA', 'NG', 'KE',
    'CN', 'TW', 'ID', 'PH', 'VN',
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PaymentProfile:
    """A user's payment instruments."""
    cards: List[dict] = field(default_factory=list)
    has_xrp_wallet: bool = False
    has_verified_wallet: bool = False
    home_market: str = 'US'


# ---------------------------------------------------------------------------
# Default seed data
# ---------------------------------------------------------------------------

DEFAULT_INTEROP_GROUPS = [
    {
        'group_code': 'SEPA',
        'group_name': 'Single Euro Payments Area',
        'description': 'EU/EEA countries with unified payment infrastructure',
        'countries': ['DE', 'FR', 'IT', 'ES', 'NL', 'AT', 'CH', 'SE', 'NO',
                      'DK', 'FI', 'PL', 'CZ', 'PT', 'IE', 'GR', 'RO', 'BE', 'LU'],
        'payment_types': ['visa', 'mastercard'],
        'default_acceptance': 'high',
    },
    {
        'group_code': 'FIVE_EYES',
        'group_name': 'Five Eyes Alliance',
        'description': 'US, CA, GB, AU, NZ — seamless card acceptance',
        'countries': ['US', 'CA', 'GB', 'AU', 'NZ'],
        'payment_types': ['visa', 'mastercard', 'amex'],
        'default_acceptance': 'high',
    },
    {
        'group_code': 'APAC_INTL',
        'group_name': 'Asia-Pacific International',
        'description': 'Major APAC markets accepting international cards at OTAs',
        'countries': ['JP', 'KR', 'SG', 'HK', 'TH', 'MY'],
        'payment_types': ['visa', 'mastercard'],
        'default_acceptance': 'medium',
    },
    {
        'group_code': 'LATAM',
        'group_name': 'Latin America',
        'description': 'Major LATAM markets — Visa/MC accepted at large OTAs',
        'countries': ['BR', 'MX', 'AR', 'CO', 'CL', 'PE'],
        'payment_types': ['visa', 'mastercard'],
        'default_acceptance': 'medium',
    },
    {
        'group_code': 'MENA',
        'group_name': 'Middle East & North Africa',
        'description': 'Gulf and MENA markets with international card acceptance',
        'countries': ['AE', 'SA', 'TR', 'IL', 'EG'],
        'payment_types': ['visa', 'mastercard'],
        'default_acceptance': 'medium',
    },
]

DEFAULT_RULES = [
    # Global Visa/MC baseline — medium acceptance at international OTAs
    {'payment_type': 'visa', 'issuing_country': '*', 'merchant_country': '*',
     'acceptance_level': 'medium', 'notes': 'Visa accepted at most international OTAs'},
    {'payment_type': 'mastercard', 'issuing_country': '*', 'merchant_country': '*',
     'acceptance_level': 'medium', 'notes': 'MC accepted at most international OTAs'},

    # Amex — strong in US/UK, limited elsewhere
    {'payment_type': 'amex', 'issuing_country': '*', 'merchant_country': 'US',
     'acceptance_level': 'high', 'notes': 'Amex widely accepted in US'},
    {'payment_type': 'amex', 'issuing_country': '*', 'merchant_country': 'CA',
     'acceptance_level': 'high', 'notes': 'Amex widely accepted in Canada'},
    {'payment_type': 'amex', 'issuing_country': '*', 'merchant_country': 'GB',
     'acceptance_level': 'medium', 'notes': 'Amex decent in UK'},
    {'payment_type': 'amex', 'issuing_country': '*', 'merchant_country': 'AU',
     'acceptance_level': 'medium', 'notes': 'Amex decent in Australia'},
    {'payment_type': 'amex', 'issuing_country': '*', 'merchant_country': 'JP',
     'acceptance_level': 'low', 'notes': 'Amex limited acceptance in Japan'},

    # JCB — Japan domestic, rare elsewhere
    {'payment_type': 'jcb', 'issuing_country': 'JP', 'merchant_country': 'JP',
     'acceptance_level': 'high', 'notes': 'JCB dominant domestically in Japan'},
    {'payment_type': 'jcb', 'issuing_country': 'JP', 'merchant_country': '*',
     'acceptance_level': 'low', 'notes': 'JCB rarely accepted outside Japan'},

    # UnionPay — China domestic, limited internationally
    {'payment_type': 'unionpay', 'issuing_country': 'CN', 'merchant_country': 'CN',
     'acceptance_level': 'high', 'notes': 'UnionPay dominant in China'},
    {'payment_type': 'unionpay', 'issuing_country': 'CN', 'merchant_country': 'HK',
     'acceptance_level': 'medium', 'notes': 'UnionPay accepted in Hong Kong'},
    {'payment_type': 'unionpay', 'issuing_country': 'CN', 'merchant_country': 'SG',
     'acceptance_level': 'medium', 'notes': 'UnionPay accepted at major SG merchants'},
    {'payment_type': 'unionpay', 'issuing_country': 'CN', 'merchant_country': '*',
     'acceptance_level': 'low', 'notes': 'UnionPay rare outside Asia'},

    # Discover — US mainly
    {'payment_type': 'discover', 'issuing_country': 'US', 'merchant_country': 'US',
     'acceptance_level': 'high', 'notes': 'Discover widely accepted in US'},
    {'payment_type': 'discover', 'issuing_country': 'US', 'merchant_country': '*',
     'acceptance_level': 'low', 'notes': 'Discover rare outside US'},

    # XRPL / RLUSD — universal via Mystes intermediation
    {'payment_type': 'xrp', 'issuing_country': '*', 'merchant_country': '*',
     'acceptance_level': 'high', 'notes': 'XRP via Mystes virtual card intermediation'},
    {'payment_type': 'rlusd', 'issuing_country': '*', 'merchant_country': '*',
     'acceptance_level': 'high', 'notes': 'RLUSD via Mystes virtual card intermediation'},

    # Virtual card — Mystes's Stripe Issuing card for universal coverage
    {'payment_type': 'virtual_card', 'issuing_country': '*', 'merchant_country': '*',
     'acceptance_level': 'high', 'notes': 'Mystes virtual card service'},

    # China — foreign cards mostly blocked on domestic sites
    {'payment_type': 'visa', 'issuing_country': '*', 'merchant_country': 'CN',
     'acceptance_level': 'low', 'notes': 'Foreign Visa limited on Chinese domestic sites'},
    {'payment_type': 'mastercard', 'issuing_country': '*', 'merchant_country': 'CN',
     'acceptance_level': 'low', 'notes': 'Foreign MC limited on Chinese domestic sites'},

    # India — foreign cards work at major OTAs but domestic carriers can be tricky
    {'payment_type': 'visa', 'issuing_country': '*', 'merchant_country': 'IN',
     'acceptance_level': 'medium', 'vertical': 'flight',
     'notes': 'International Visa works on major Indian airline sites'},
    {'payment_type': 'visa', 'issuing_country': '*', 'merchant_country': 'IN',
     'acceptance_level': 'low', 'vertical': 'hotel',
     'notes': 'Hotel booking sites in India often prefer UPI/domestic cards'},
]


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class PaymentCompatibilityEngine:
    """Determines which markets a user can purchase in."""

    def __init__(self):
        self._rule_cache: Optional[List[dict]] = None
        self._rule_cache_at: Optional[datetime] = None
        self._rule_cache_ttl = timedelta(minutes=5)
        self._group_cache: Optional[List[dict]] = None
        self._group_cache_at: Optional[datetime] = None
        self._profile_cache: Dict[int, Tuple[PaymentProfile, datetime]] = {}
        self._profile_cache_ttl = timedelta(minutes=2)
        self._lock = threading.Lock()

    # ---------------------------------------------------------------
    # Cache management
    # ---------------------------------------------------------------

    def _load_rules(self) -> List[dict]:
        """Load all active rules from DB, with caching."""
        now = datetime.utcnow()
        if (self._rule_cache is not None
                and self._rule_cache_at
                and now - self._rule_cache_at < self._rule_cache_ttl):
            return self._rule_cache

        try:
            from models import PaymentZoneRule
            rules = PaymentZoneRule.query.filter_by(is_active=True).all()
            self._rule_cache = [r.to_dict() for r in rules]
            self._rule_cache_at = now
        except Exception as e:
            logger.warning("Failed to load payment rules from DB: %s", e)
            if self._rule_cache is None:
                self._rule_cache = []

        return self._rule_cache

    def _load_groups(self) -> List[dict]:
        """Load all active interop groups from DB, with caching."""
        now = datetime.utcnow()
        if (self._group_cache is not None
                and self._group_cache_at
                and now - self._group_cache_at < self._rule_cache_ttl):
            return self._group_cache

        try:
            from models import PaymentInteropGroup
            groups = PaymentInteropGroup.query.filter_by(is_active=True).all()
            self._group_cache = [g.to_dict() for g in groups]
            self._group_cache_at = now
        except Exception as e:
            logger.warning("Failed to load interop groups from DB: %s", e)
            if self._group_cache is None:
                self._group_cache = []

        return self._group_cache

    def invalidate_cache(self):
        """Force cache refresh on next access."""
        with self._lock:
            self._rule_cache = None
            self._rule_cache_at = None
            self._group_cache = None
            self._group_cache_at = None
            self._profile_cache.clear()

    # ---------------------------------------------------------------
    # User payment profile
    # ---------------------------------------------------------------

    def get_user_payment_profile(self, user_id: int) -> PaymentProfile:
        """Load user's payment instruments (cards + wallets)."""
        now = datetime.utcnow()

        # Check cache
        if user_id in self._profile_cache:
            profile, cached_at = self._profile_cache[user_id]
            if now - cached_at < self._profile_cache_ttl:
                return profile

        from models import User, UserCard, UserWallet

        user = User.query.get(user_id)
        if not user:
            return PaymentProfile()

        cards = UserCard.query.filter_by(user_id=user_id, is_active=True).all()
        card_list = []
        for c in cards:
            card_list.append({
                'brand': (c.card_brand or '').lower(),
                'billing_country': (c.billing_country or user.home_market or 'US').upper(),
                'last_four': c.card_last_four,
            })

        wallets = UserWallet.query.filter_by(user_id=user_id).all()
        has_wallet = len(wallets) > 0
        has_verified = any(w.is_verified for w in wallets)

        # Also check if user has XRPL wallet on User model directly
        if user.xrpl_wallet_address:
            has_wallet = True
            has_verified = True  # Auto-generated wallets are trusted

        profile = PaymentProfile(
            cards=card_list,
            has_xrp_wallet=has_wallet,
            has_verified_wallet=has_verified,
            home_market=(user.home_market or 'US').upper(),
        )

        self._profile_cache[user_id] = (profile, now)
        return profile

    # ---------------------------------------------------------------
    # Rule matching
    # ---------------------------------------------------------------

    def _match_rules(self, payment_type: str, issuing_country: str,
                     merchant_country: str, vertical: Optional[str] = None) -> str:
        """Find the best acceptance level for a specific payment/country combination.
        Returns acceptance level string ('high', 'medium', 'low', 'none').
        """
        rules = self._load_rules()
        best_level = 'none'
        best_score = 0

        for rule in rules:
            # Match payment type
            if rule['payment_type'] != payment_type:
                continue

            # Match issuing country (exact or wildcard)
            if rule['issuing_country'] != '*' and rule['issuing_country'] != issuing_country:
                continue

            # Match merchant country (exact or wildcard)
            if rule['merchant_country'] != '*' and rule['merchant_country'] != merchant_country:
                continue

            # Match vertical (None = all verticals)
            if rule.get('vertical') and vertical and rule['vertical'] != vertical:
                continue

            level = rule['acceptance_level']
            score = ACCEPTANCE_LEVELS.get(level, 0)

            # Prefer specific rules over wildcard
            specificity = 0
            if rule['issuing_country'] != '*':
                specificity += 2
            if rule['merchant_country'] != '*':
                specificity += 2
            if rule.get('vertical'):
                specificity += 1

            # Higher specificity wins ties; otherwise higher acceptance wins
            if score > best_score or (score == best_score and specificity > 0):
                best_level = level
                best_score = score

        return best_level

    def _get_group_acceptance(self, payment_type: str, issuing_country: str,
                              merchant_country: str) -> Optional[str]:
        """Check if issuing and merchant countries share an interop group
        that covers this payment type. Returns acceptance level or None."""
        groups = self._load_groups()

        for group in groups:
            countries = group.get('countries', [])
            ptypes = group.get('payment_types', [])

            if payment_type not in ptypes:
                continue
            if issuing_country not in countries:
                continue
            if merchant_country not in countries:
                continue

            return group.get('default_acceptance', 'high')

        return None

    # ---------------------------------------------------------------
    # Core: reachable countries
    # ---------------------------------------------------------------

    def get_reachable_countries(self, user_id: int = None,
                                profile: PaymentProfile = None,
                                vertical: Optional[str] = None,
                                min_acceptance: str = 'medium') -> Dict[str, dict]:
        """Get all countries reachable by the user's payment instruments.

        Returns: {country_code: {methods: [...], acceptance: 'high', via_group: str|None}}
        """
        if profile is None and user_id is not None:
            profile = self.get_user_payment_profile(user_id)
        if profile is None:
            return {}

        min_score = ACCEPTANCE_LEVELS.get(min_acceptance, 2)
        reachable: Dict[str, dict] = {}

        # For each card, check all market countries
        for card in profile.cards:
            brand = card.get('brand', '')
            issuing = card.get('billing_country', profile.home_market)

            if not brand:
                continue

            for country in ALL_MARKET_COUNTRIES:
                # Check interop group first (more specific)
                group_level = self._get_group_acceptance(brand, issuing, country)
                if group_level:
                    group_score = ACCEPTANCE_LEVELS.get(group_level, 0)
                    if group_score >= min_score:
                        method_key = f"{brand}_{issuing}"
                        if country not in reachable or group_score > ACCEPTANCE_LEVELS.get(
                                reachable[country].get('acceptance', 'none'), 0):
                            reachable[country] = {
                                'methods': [method_key],
                                'acceptance': group_level,
                                'via_group': True,
                            }
                        elif country in reachable and method_key not in reachable[country]['methods']:
                            reachable[country]['methods'].append(method_key)
                        continue

                # Check individual rules
                level = self._match_rules(brand, issuing, country, vertical)
                score = ACCEPTANCE_LEVELS.get(level, 0)

                if score >= min_score:
                    method_key = f"{brand}_{issuing}"
                    if country not in reachable or score > ACCEPTANCE_LEVELS.get(
                            reachable[country].get('acceptance', 'none'), 0):
                        reachable[country] = {
                            'methods': [method_key],
                            'acceptance': level,
                            'via_group': None,
                        }
                    elif country in reachable and method_key not in reachable[country]['methods']:
                        reachable[country]['methods'].append(method_key)

        # XRPL/crypto bypass: verified wallet holders get universal access
        if profile.has_verified_wallet:
            for country in ALL_MARKET_COUNTRIES:
                crypto_methods = []
                for ptype in ['xrp', 'rlusd', 'virtual_card']:
                    level = self._match_rules(ptype, '*', country, vertical)
                    if ACCEPTANCE_LEVELS.get(level, 0) >= min_score:
                        crypto_methods.append(ptype)

                if crypto_methods:
                    if country in reachable:
                        reachable[country]['methods'].extend(crypto_methods)
                        # Upgrade acceptance if crypto is higher
                        if ACCEPTANCE_LEVELS.get('high', 3) > ACCEPTANCE_LEVELS.get(
                                reachable[country]['acceptance'], 0):
                            reachable[country]['acceptance'] = 'high'
                    else:
                        reachable[country] = {
                            'methods': crypto_methods,
                            'acceptance': 'high',
                            'via_group': 'MYSTES_VIRTUAL_CARD',
                        }

        return reachable

    # ---------------------------------------------------------------
    # Filtering
    # ---------------------------------------------------------------

    def filter_zones(self, zone_codes: List[str], user_id: int,
                     vertical: Optional[str] = None,
                     min_acceptance: str = 'medium') -> List[str]:
        """Filter zone codes to payment-compatible ones only."""
        reachable = self.get_reachable_countries(
            user_id=user_id, vertical=vertical, min_acceptance=min_acceptance
        )

        filtered = []
        for zone in zone_codes:
            # Extract country from zone code (e.g., 'US-NE' -> 'US', 'JP' -> 'JP')
            country = zone[:2].upper()
            if country in reachable:
                filtered.append(zone)

        return filtered

    def filter_countries(self, countries: List[str], user_id: int,
                         vertical: Optional[str] = None,
                         min_acceptance: str = 'medium') -> List[str]:
        """Filter country codes to payment-compatible ones only."""
        reachable = self.get_reachable_countries(
            user_id=user_id, vertical=vertical, min_acceptance=min_acceptance
        )
        return [c for c in countries if c.upper() in reachable]

    # ---------------------------------------------------------------
    # Deal assessment
    # ---------------------------------------------------------------

    def assess_deal_compatibility(self, deal_market: str, user_id: int,
                                   vertical: Optional[str] = None) -> dict:
        """Assess payment compatibility for a specific deal market and user."""
        profile = self.get_user_payment_profile(user_id)
        country = deal_market[:2].upper()

        compatible_methods = []
        best_acceptance = 'none'
        best_score = 0
        warnings = []

        # Check each card
        for card in profile.cards:
            brand = card.get('brand', '')
            issuing = card.get('billing_country', profile.home_market)
            if not brand:
                continue

            # Check group first
            group_level = self._get_group_acceptance(brand, issuing, country)
            level = group_level or self._match_rules(brand, issuing, country, vertical)
            score = ACCEPTANCE_LEVELS.get(level, 0)

            method_key = f"{brand}_{issuing}"
            if score > 0:
                compatible_methods.append(method_key)
                if score > best_score:
                    best_acceptance = level
                    best_score = score

                if level == 'low':
                    warnings.append(
                        f"{brand.upper()} ({issuing}) has low acceptance in {country}"
                    )

        # Check crypto bypass
        if profile.has_verified_wallet:
            for ptype in ['xrp', 'rlusd']:
                level = self._match_rules(ptype, '*', country, vertical)
                score = ACCEPTANCE_LEVELS.get(level, 0)
                if score > 0:
                    compatible_methods.append(ptype)
                    if score > best_score:
                        best_acceptance = level
                        best_score = score

        requires_virtual_card = (
            best_score < ACCEPTANCE_LEVELS.get('medium', 2)
            and profile.has_verified_wallet
        )

        if requires_virtual_card:
            compatible_methods.append('virtual_card')
            best_acceptance = 'high'
            best_score = 3

        is_compatible = best_score >= ACCEPTANCE_LEVELS.get('medium', 2)

        if not is_compatible and not compatible_methods:
            warnings.append(f"No accepted payment method for {country} merchants")

        return {
            'is_compatible': is_compatible,
            'compatible_methods': list(set(compatible_methods)),
            'best_acceptance': best_acceptance,
            'requires_virtual_card': requires_virtual_card,
            'warnings': warnings,
            'market': country,
        }

    def get_market_payment_summary(self, market_country: str,
                                    vertical: Optional[str] = None) -> dict:
        """Non-user-specific summary of what payment types a market accepts."""
        rules = self._load_rules()
        country = market_country[:2].upper()

        accepted_networks = set()
        crypto_accepted = False
        virtual_card = False
        notes_list = []

        for rule in rules:
            mc = rule['merchant_country']
            if mc != country and mc != '*':
                continue
            if rule.get('vertical') and vertical and rule['vertical'] != vertical:
                continue

            level = rule['acceptance_level']
            if ACCEPTANCE_LEVELS.get(level, 0) >= ACCEPTANCE_LEVELS['medium']:
                ptype = rule['payment_type']
                if ptype in ('xrp', 'rlusd', 'crypto'):
                    crypto_accepted = True
                elif ptype == 'virtual_card':
                    virtual_card = True
                else:
                    accepted_networks.add(ptype)

                if rule.get('notes') and mc == country:
                    notes_list.append(rule['notes'])

        return {
            'market': country,
            'accepted_card_networks': sorted(accepted_networks),
            'crypto_accepted': crypto_accepted,
            'virtual_card_available': virtual_card,
            'notes': notes_list[:3],
        }

    # ---------------------------------------------------------------
    # FX estimation + zone availability (Build #86)
    # ---------------------------------------------------------------

    def _estimate_fx(self, merchant_country: str, methods: list) -> dict:
        """Estimate FX conversion cost for reaching a market.

        Returns: {spread_pct, group, notes}
        """
        try:
            from payment_ramps import FX_COST_ESTIMATES
        except ImportError:
            return {'spread_pct': 3.0, 'group': None, 'notes': 'FX estimation unavailable'}

        groups = self._load_groups()
        has_crypto = any(m in ('xrp', 'rlusd', 'virtual_card') for m in methods)

        for group in groups:
            countries = group.get('countries', [])
            if merchant_country in countries:
                group_code = group['group_code']
                estimates = FX_COST_ESTIMATES.get(group_code, {})
                spread = (estimates.get('crypto_spread_pct', 0.5) if has_crypto
                          else estimates.get('card_spread_pct', 3.0))
                return {
                    'spread_pct': spread,
                    'group': group_code,
                    'notes': estimates.get('notes', ''),
                }

        return {'spread_pct': 3.0, 'group': None, 'notes': 'No interop group match — estimated'}

    def get_zone_availability_summary(self, user_id: int) -> list:
        """Return per-interop-group summary for the wallet settings UI.

        Shows which groups are reachable, how many countries, FX costs.
        Used for both arbitrage and free browsing/shopping.
        """
        try:
            from payment_ramps import FX_COST_ESTIMATES
        except ImportError:
            FX_COST_ESTIMATES = {}

        profile = self.get_user_payment_profile(user_id)
        groups = self._load_groups()
        reachable = self.get_reachable_countries(profile=profile)

        summary = []
        for group in groups:
            group_code = group.get('group_code', '')
            group_name = group.get('group_name', group_code)
            countries = group.get('countries', [])

            reachable_in_group = [c for c in countries if c in reachable]
            coverage_pct = (len(reachable_in_group) / len(countries) * 100) if countries else 0

            methods_used = set()
            for c in reachable_in_group:
                methods_used.update(reachable[c].get('methods', []))

            fx_estimate = FX_COST_ESTIMATES.get(group_code, {
                'card_spread_pct': 3.0,
                'crypto_spread_pct': 0.5,
            })

            if coverage_pct == 100:
                status = 'full'
            elif coverage_pct > 0:
                status = 'partial'
            else:
                status = 'none'

            summary.append({
                'group_code': group_code,
                'group_name': group_name,
                'total_countries': len(countries),
                'reachable_countries': len(reachable_in_group),
                'coverage_pct': round(coverage_pct, 0),
                'methods': sorted(methods_used),
                'fx_estimate': {
                    'card_spread_pct': fx_estimate.get('card_spread_pct', 3.0),
                    'crypto_spread_pct': fx_estimate.get('crypto_spread_pct', 0.5),
                    'notes': fx_estimate.get('notes', ''),
                },
                'status': status,
            })

        return summary

    # ---------------------------------------------------------------
    # Seed data
    # ---------------------------------------------------------------

    def seed_default_rules(self):
        """Populate default payment rules and interop groups if tables are empty."""
        from models import db, PaymentZoneRule, PaymentInteropGroup

        # Seed interop groups
        existing_groups = PaymentInteropGroup.query.count()
        if existing_groups == 0:
            for gdata in DEFAULT_INTEROP_GROUPS:
                group = PaymentInteropGroup(
                    group_code=gdata['group_code'],
                    group_name=gdata['group_name'],
                    description=gdata.get('description', ''),
                    countries=json.dumps(gdata['countries']),
                    payment_types=json.dumps(gdata['payment_types']),
                    default_acceptance=gdata.get('default_acceptance', 'high'),
                )
                db.session.add(group)
            db.session.commit()
            logger.info("Seeded %d payment interop groups", len(DEFAULT_INTEROP_GROUPS))

        # Seed rules
        existing_rules = PaymentZoneRule.query.count()
        if existing_rules == 0:
            for rdata in DEFAULT_RULES:
                rule = PaymentZoneRule(
                    payment_type=rdata['payment_type'],
                    issuing_country=rdata['issuing_country'],
                    merchant_country=rdata['merchant_country'],
                    acceptance_level=rdata['acceptance_level'],
                    vertical=rdata.get('vertical'),
                    notes=rdata.get('notes'),
                )
                db.session.add(rule)

            # Auto-generate intra-group rules for elevated acceptance
            for gdata in DEFAULT_INTEROP_GROUPS:
                countries = gdata['countries']
                ptypes = gdata['payment_types']
                level = gdata.get('default_acceptance', 'high')

                for ptype in ptypes:
                    for issuing in countries:
                        for merchant in countries:
                            # Check if a more specific rule already exists in DEFAULT_RULES
                            already_exists = any(
                                r['payment_type'] == ptype
                                and r['issuing_country'] == issuing
                                and r['merchant_country'] == merchant
                                for r in DEFAULT_RULES
                            )
                            if not already_exists:
                                rule = PaymentZoneRule(
                                    payment_type=ptype,
                                    issuing_country=issuing,
                                    merchant_country=merchant,
                                    acceptance_level=level,
                                    notes=f"Intra-group: {gdata['group_code']}",
                                )
                                db.session.add(rule)

            db.session.commit()
            total = PaymentZoneRule.query.count()
            logger.info("Seeded %d payment zone rules (including intra-group)", total)

        self.invalidate_cache()


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

payment_compat_engine = PaymentCompatibilityEngine()
