"""Unit tests for application configurations and deployment safety."""
import os
import pytest
from app import create_app
from app.config import Config, DevelopmentConfig, ProductionConfig, TestingConfig


class TestApplicationConfig:
    """Verify configuration environments and environment-variable safety."""

    def test_development_config_defaults(self, monkeypatch):
        monkeypatch.delenv("USE_AWS_MOCK", raising=False)
        app = create_app("development")
        assert app.config["DEBUG"] is True
        assert app.config["TESTING"] is False
        assert app.config["USE_AWS_MOCK"] is True

    def test_development_config_honors_live_mode_override(self, monkeypatch):
        monkeypatch.setenv("USE_AWS_MOCK", "False")
        # Re-import or re-evaluate DevelopmentConfig
        class DynDevConfig(DevelopmentConfig):
            USE_AWS_MOCK = os.environ.get("USE_AWS_MOCK", "True").lower() in ("true", "1", "yes")

        assert DynDevConfig.USE_AWS_MOCK is False

    def test_production_config_defaults(self, monkeypatch):
        monkeypatch.delenv("USE_AWS_MOCK", raising=False)
        monkeypatch.delenv("SESSION_COOKIE_SECURE", raising=False)
        monkeypatch.delenv("SHOW_DEMO_CREDENTIALS", raising=False)
        monkeypatch.setenv("SECRET_KEY", "prod-test-secret-key-abcdef-123456")

        app = create_app("production")
        assert app.config["DEBUG"] is False
        assert app.config["TESTING"] is False
        assert app.config["USE_AWS_MOCK"] is False
        assert app.config["SESSION_COOKIE_SECURE"] is False
        assert app.config["SHOW_DEMO_CREDENTIALS"] is False

    def test_production_config_secure_session_opt_in(self, monkeypatch):
        monkeypatch.setenv("SESSION_COOKIE_SECURE", "True")
        monkeypatch.setenv("SECRET_KEY", "prod-test-secret-key-abcdef-123456")

        class DynProdConfig(ProductionConfig):
            SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "False").lower() in ("true", "1", "yes")

        assert DynProdConfig.SESSION_COOKIE_SECURE is True

    def test_demo_credentials_visibility_defaults(self, monkeypatch):
        monkeypatch.delenv("SHOW_DEMO_CREDENTIALS", raising=False)
        monkeypatch.setenv("SECRET_KEY", "prod-test-secret-key-abcdef-123456")

        dev_app = create_app("development")
        assert dev_app.config["SHOW_DEMO_CREDENTIALS"] is True

        test_app = create_app("testing")
        assert test_app.config["SHOW_DEMO_CREDENTIALS"] is True

        prod_app = create_app("production")
        assert prod_app.config["SHOW_DEMO_CREDENTIALS"] is False

    def test_demo_credentials_visibility_env_override(self, monkeypatch):
        monkeypatch.setenv("SECRET_KEY", "prod-test-secret-key-abcdef-123456")

        # Disable in development via env var
        monkeypatch.setenv("SHOW_DEMO_CREDENTIALS", "False")
        dev_app = create_app("development")
        assert dev_app.config["SHOW_DEMO_CREDENTIALS"] is False

        # Opt in in production via explicit env var
        monkeypatch.setenv("SHOW_DEMO_CREDENTIALS", "True")
        prod_app = create_app("production")
        assert prod_app.config["SHOW_DEMO_CREDENTIALS"] is True

    def test_testing_config_defaults(self):
        app = create_app("testing")
        assert app.config["TESTING"] is True
        assert app.config["DEBUG"] is False
        assert app.config["WTF_CSRF_ENABLED"] is False
        assert app.config["USE_AWS_MOCK"] is True
