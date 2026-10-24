"""Pytest fixtures for Movie Magic."""
import pytest
from app import create_app
from app.repositories import user_repository, movie_repository, booking_repository


@pytest.fixture(scope="session")
def app():
    """Create test application instance with testing configuration."""
    application = create_app("testing")
    return application


@pytest.fixture(scope="function")
def client(app):
    """Test HTTP client."""
    with app.test_client() as client:
        with app.app_context():
            yield client


@pytest.fixture
def auth_client(client):
    """Client authenticated as standard demo user."""
    with client.session_transaction() as sess:
        sess["user_id"] = "usr-demo-1"
        sess["user_email"] = "demo@moviemagic.com"
        sess["user_name"] = "Demo Moviegoer"
        sess["user_role"] = "user"
    return client


@pytest.fixture
def admin_client(client):
    """Client authenticated as administrator."""
    with client.session_transaction() as sess:
        sess["user_id"] = "usr-admin-1"
        sess["user_email"] = "admin@moviemagic.com"
        sess["user_name"] = "Admin Manager"
        sess["user_role"] = "admin"
    return client
