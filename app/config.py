import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    """Base configuration with shared application defaults."""
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure-secret-key-change-in-production-movie-magic-2026")
    APP_NAME = os.environ.get("APP_NAME", "Movie Magic")
    APP_HOST = os.environ.get("APP_HOST", "127.0.0.1")
    APP_PORT = int(os.environ.get("APP_PORT", 5000))

    # Session and Cookie Security
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "False").lower() in ("true", "1", "yes")
    PERMANENT_SESSION_LIFETIME = 3600  # 1 hour session

    # CSRF Protection
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600

    # TMDB Metadata Configuration (Optional enrichment; local catalogue works without it)
    TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "")

    # AWS Configuration (Phase 2: ap-south-1 Mumbai)
    AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1")
    AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID", "")
    AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
    DYNAMODB_TABLE_PREFIX = os.environ.get("DYNAMODB_TABLE_PREFIX", "moviemagic_")
    DYNAMODB_ENDPOINT_URL = os.environ.get("DYNAMODB_ENDPOINT_URL", "")
    SNS_BOOKING_TOPIC_ARN = os.environ.get("SNS_BOOKING_TOPIC_ARN", "")
    USE_AWS_MOCK = os.environ.get("USE_AWS_MOCK", "True").lower() in ("true", "1", "yes")

    # Resend Transactional Email Configuration
    RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
    RESEND_FROM_EMAIL = os.environ.get("RESEND_FROM_EMAIL", "Movie Magic <tickets@mail.shardul.online>")
    RESEND_REPLY_TO = os.environ.get("RESEND_REPLY_TO", "")
    APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://43.204.215.123")

    # Demo Credentials Visibility (for academic evaluation vs production hardening)
    SHOW_DEMO_CREDENTIALS = os.environ.get("SHOW_DEMO_CREDENTIALS", "True").lower() in ("true", "1", "yes")


class DevelopmentConfig(Config):
    """Development environment configuration."""
    DEBUG = True
    TESTING = False
    USE_AWS_MOCK = os.environ.get("USE_AWS_MOCK", "True").lower() in ("true", "1", "yes")
    SHOW_DEMO_CREDENTIALS = os.environ.get("SHOW_DEMO_CREDENTIALS", "True").lower() in ("true", "1", "yes")


class TestingConfig(Config):
    """Testing environment configuration."""
    DEBUG = False
    TESTING = True
    WTF_CSRF_ENABLED = False  # Disabled for unit tests to simplify form testing
    SECRET_KEY = "testing-secret-key-12345"
    USE_AWS_MOCK = True
    SHOW_DEMO_CREDENTIALS = os.environ.get("SHOW_DEMO_CREDENTIALS", "True").lower() in ("true", "1", "yes")


class ProductionConfig(Config):
    """Production environment configuration with hardened security."""
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "False").lower() in ("true", "1", "yes")
    USE_AWS_MOCK = os.environ.get("USE_AWS_MOCK", "False").lower() in ("true", "1", "yes")
    SHOW_DEMO_CREDENTIALS = os.environ.get("SHOW_DEMO_CREDENTIALS", "False").lower() in ("true", "1", "yes")

    @classmethod
    def init_app(cls, app):
        assert os.environ.get("SECRET_KEY"), "SECRET_KEY environment variable must be set in production!"


config_by_name = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig,
}
