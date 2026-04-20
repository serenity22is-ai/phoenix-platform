"""
MYSTES Configuration

Centralized configuration management for different environments.
"""

import os
from datetime import timedelta


class Config:
    """Base configuration."""

    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    APP_NAME = 'MYSTES'

    # Database
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///mystes.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
    }

    # Session
    SESSION_COOKIE_SECURE = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)

    # CSRF
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600

    # Rate Limiting
    RATELIMIT_DEFAULT = "200 per day;50 per hour"
    RATELIMIT_STORAGE_URL = os.environ.get('RATELIMIT_STORAGE_URL', 'memory://')

    # Email
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'true').lower() == 'true'
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', 'MYSTES <noreply@mystes.app>')

    # Stripe
    STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY')
    STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY')
    STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET')

    # Payment Ramps (Build #86, cleaned Build #196)
    # Stripe + MoonPay ONLY. Coinbase PERMANENTLY RETIRED. Transak RETIRED.
    MOONPAY_API_KEY = os.environ.get('MOONPAY_API_KEY')
    MOONPAY_SECRET_KEY = os.environ.get('MOONPAY_SECRET_KEY')

    # Platform fee by membership status (Build #156 → Build #170)
    # Guest (anonymous): 50% | Free Member (authenticated): 45% | Travel+: 35%
    FREE_MEMBER_FEE_PERCENT = 45  # Authenticated free members: 45% of savings
    MEMBER_FEE_PERCENT = 35       # Travel+ subscribers: 35% of savings
    NON_MEMBER_FEE_PERCENT = 50   # Consumers (anonymous/guest): 50% of savings

    # B2B Subscription (Build #158, updated Build #167)
    B2B_STARTER_PRICE_USD = 49
    B2B_STARTER_FEE_PERCENT = 25
    B2B_GROWTH_PRICE_USD = 99
    B2B_GROWTH_FEE_PERCENT = 20
    B2B_VOLUME_PRICE_USD = 199
    B2B_VOLUME_FEE_PERCENT = 15
    B2B_STRIPE_PRICE_ID = os.environ.get('B2B_STARTER_STRIPE_PRICE_ID', '')

    # Travel+ Subscription (Build #167)
    TRAVEL_PLUS_MONTHLY_USD = 9.99
    TRAVEL_PLUS_ANNUAL_USD = 79.99
    TRAVEL_PLUS_FEE_PERCENT = 35
    TRAVEL_PLUS_STRIPE_MONTHLY_PRICE_ID = os.environ.get('TRAVEL_PLUS_MONTHLY_STRIPE_PRICE_ID', '')
    TRAVEL_PLUS_STRIPE_ANNUAL_PRICE_ID = os.environ.get('TRAVEL_PLUS_ANNUAL_STRIPE_PRICE_ID', '')

    # Pay-Per-Session AI (Build #167)
    AI_SESSION_PRICE_USD = 2.99
    AI_SESSION_DURATION_MINUTES = 30
    AI_SESSION_MAX_MESSAGES = 30

    # APAi Tiers (Build #194 — replaces standalone Dev Portal pricing)
    # Actual tier configs in dev_portal_billing.py TIER_CONFIG
    # Pro $299/500q, Enterprise $599/2000q, Scale $999/5000q (ALL PROVISIONAL)
    APAI_PRO_STRIPE_PRICE_ID = os.environ.get('APAI_PRO_STRIPE_PRICE_ID', '')
    APAI_ENTERPRISE_STRIPE_PRICE_ID = os.environ.get('APAI_ENTERPRISE_STRIPE_PRICE_ID', '')
    APAI_SCALE_STRIPE_PRICE_ID = os.environ.get('APAI_SCALE_STRIPE_PRICE_ID', '')

    # Referral System (Build #170)
    REFERRAL_SIGNUP_POINTS = 2000         # Points when referee signs up
    REFERRAL_FIRST_BOOKING_POINTS = 5000  # Points when referee completes first booking
    REFERRAL_TRAVEL_PLUS_POINTS = 10000   # Points when referee subscribes to Travel+
    FREE_MEMBER_REFERRAL_POINTS = 1000    # Free members earn per friend booking
    SHARE_TO_SAVE_DISCOUNT = 0.05         # 5% discount on platform fee for social sharing

    # Rewards Points (Build #167)
    POINTS_PER_DOLLAR = 10
    POINTS_REDEMPTION_VALUE = 0.001       # 1 point = $0.001 (1000 pts = $1)
    POINTS_TRAVEL_PLUS_MULTIPLIER = 1.5
    POINTS_EXPIRY_MONTHS = 12
    POINTS_MIN_GIFT = 1000
    POINTS_GIFT_SEND_LIMIT_MONTHLY = 20000
    POINTS_GIFT_RECEIVE_LIMIT_MONTHLY = 50000
    POINTS_ESCROW_DAYS = 90

    # Local Business (Build #167)
    LOCAL_BUSINESS_COMMISSION_PERCENT = 15.0
    LOCAL_BUSINESS_FEATURED_PRICE_USD = 29.0
    LOCAL_BUSINESS_FEATURED_COMMISSION_PERCENT = 10.0

    # Proxy
    JP_PROXY_URL = os.environ.get('JP_PROXY_URL')
    US_PROXY_URL = os.environ.get('US_PROXY_URL')

    # Deal settings
    DEAL_EXPIRY_HOURS = 24
    PAYMENT_TIMEOUT_MINUTES = 30

    # Redis
    REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')

    # liteAPI (Hotel Search — replaces Amadeus Hotel Self-Service)
    LITEAPI_KEY = os.environ.get('LITEAPI_KEY')

    # Picasso Travel / AERTiCKET Redbox (Flight Search + Ticketing — replaces Amadeus)
    PICASSO_SESSION_TOKEN = os.environ.get('PICASSO_SESSION_TOKEN')
    PICASSO_REDBOX_URL = os.environ.get('PICASSO_REDBOX_URL', 'https://aerpackit.flightconex.de/redbox')
    PICASSO_AGENCY_ID = os.environ.get('PICASSO_AGENCY_ID', '629818')
    PICASSO_BRANCH = os.environ.get('PICASSO_BRANCH', 'PICL_707')
    PICASSO_USERNAME = os.environ.get('PICASSO_USERNAME')
    PICASSO_PASSWORD = os.environ.get('PICASSO_PASSWORD')
    PICASSO_TOTP_SECRET = os.environ.get('PICASSO_TOTP_SECRET')
    PICASSO_COCKPIT_URL = os.environ.get('PICASSO_COCKPIT_URL', 'https://cockpit.thegoodconsolidator.com')


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///mystes_dev.db'
    RATELIMIT_STORAGE_URL = 'memory://'


class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False

    SECRET_KEY = os.environ.get('SECRET_KEY')

    # Secure cookies
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'

    # PostgreSQL
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'postgresql://mystes:mystes_secret@localhost:5432/mystes_db'
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
        'pool_size': 10,
        'max_overflow': 20,
        'connect_args': {
            'connect_timeout': 5,        # Fail fast if DB unreachable (5s, not 30s)
            'options': '-c statement_timeout=30000',  # Kill queries after 30s
        },
    }

    # Redis-backed rate limiting (falls back to memory:// if REDIS not configured)
    RATELIMIT_STORAGE_URL = os.environ.get('RATELIMIT_STORAGE_URL', 'memory://')
    RATELIMIT_DEFAULT = "1000 per day;100 per hour"

    REMEMBER_COOKIE_SECURE = True
    REMEMBER_COOKIE_HTTPONLY = True

    @classmethod
    def init_app(cls, app):
        """Production-specific initialization."""
        import logging
        from logging.handlers import RotatingFileHandler

        file_handler = RotatingFileHandler(
            'logs/mystes.log',
            maxBytes=10 * 1024 * 1024,
            backupCount=10
        )
        file_handler.setLevel(logging.WARNING)
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
        ))
        app.logger.addHandler(file_handler)


class TestingConfig(Config):
    """Testing configuration."""
    TESTING = True
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False
    RATELIMIT_STORAGE_URL = 'memory://'
    SERVER_NAME = 'localhost.localdomain'


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig,
}


def get_config(env=None):
    """Get configuration based on environment."""
    if env is None:
        env = os.environ.get('FLASK_ENV', 'development')
    return config.get(env, config['default'])
