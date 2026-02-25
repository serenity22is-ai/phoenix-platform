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

    # XRPL
    XRPL_NETWORK = os.environ.get('XRPL_NETWORK', 'testnet')
    XRPL_WALLET_ADDRESS = os.environ.get('XRPL_WALLET_ADDRESS')
    XRPL_WALLET_SEED = os.environ.get('XRPL_WALLET_SEED')

    # Stripe
    STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY')
    STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY')
    STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET')
    STRIPE_ISSUING_ENABLED = os.environ.get('STRIPE_ISSUING_ENABLED', 'false').lower() == 'true'

    # Payment Ramp Networks (Build #86)
    MOONPAY_API_KEY = os.environ.get('MOONPAY_API_KEY')
    MOONPAY_SECRET_KEY = os.environ.get('MOONPAY_SECRET_KEY')
    TRANSAK_API_KEY = os.environ.get('TRANSAK_API_KEY')
    COINBASE_ONRAMP_APP_ID = os.environ.get('COINBASE_ONRAMP_APP_ID')

    # Platform fee by membership status
    MEMBER_FEE_PERCENT = 25       # Members: 25% of savings
    NON_MEMBER_FEE_PERCENT = 50   # Non-members: 50% of savings
    MIN_SAVINGS_THRESHOLD = 20.00

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
    }

    # Redis-backed rate limiting
    RATELIMIT_STORAGE_URL = os.environ.get('RATELIMIT_STORAGE_URL', 'redis://redis:6379/1')
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
