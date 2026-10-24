"""Tests for authentication, registration, password hashing, and sessions."""
from app.utils.security import verify_password, validate_password_strength
from app.repositories import user_repository


def test_password_strength_validator():
    """Verify password complexity rules."""
    valid, _ = validate_password_strength("Short1")
    assert not valid  # Too short

    valid, _ = validate_password_strength("nouppercase123")
    assert not valid  # No uppercase

    valid, _ = validate_password_strength("NOLOWERCASE123")
    assert not valid  # No lowercase

    valid, _ = validate_password_strength("NoDigitsHere")
    assert not valid  # No digits

    valid, _ = validate_password_strength("ValidSecret123")
    assert valid


def test_register_new_user(client):
    """Test user registration flow."""
    response = client.post(
        "/auth/register",
        data={
            "full_name": "Sarah Connor",
            "email": "sarah@resistance.org",
            "password": "JudgementDay1997",
            "confirm_password": "JudgementDay1997",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Registration successful" in response.data

    user = user_repository.get_by_email("sarah@resistance.org")
    assert user is not None
    assert user["full_name"] == "Sarah Connor"
    assert verify_password("JudgementDay1997", user["password_hash"])
    assert not verify_password("WrongPassword", user["password_hash"])


def test_register_duplicate_email(client):
    """Test rejection of already registered email."""
    response = client.post(
        "/auth/register",
        data={
            "full_name": "Demo Duplicate",
            "email": "demo@moviemagic.com",
            "password": "Password123",
            "confirm_password": "Password123",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"already exists" in response.data


def test_login_successful(client):
    """Test successful login with pre-seeded demo user."""
    response = client.post(
        "/auth/login",
        data={
            "email": "demo@moviemagic.com",
            "password": "Demo@123",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Welcome back" in response.data
    with client.session_transaction() as sess:
        assert sess.get("user_id") == "usr-demo-1"
        assert sess.get("user_role") == "user"


def test_login_invalid_password(client):
    """Test rejection of incorrect password."""
    response = client.post(
        "/auth/login",
        data={
            "email": "demo@moviemagic.com",
            "password": "IncorrectPassword123",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Invalid email or password" in response.data


def test_login_nonexistent_user(client):
    """Test rejection of nonexistent email."""
    response = client.post(
        "/auth/login",
        data={
            "email": "nonexistent@moviemagic.com",
            "password": "Password123",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Invalid email or password" in response.data


def test_logout(auth_client):
    """Test logout clears session."""
    response = auth_client.get("/auth/logout", follow_redirects=True)
    assert response.status_code == 200
    with auth_client.session_transaction() as sess:
        assert sess.get("user_id") is None


def test_login_page_renders_demo_credentials_when_enabled(client):
    """Verify demo-user quick-fill renders when SHOW_DEMO_CREDENTIALS is enabled."""
    response = client.get("/auth/login")
    assert response.status_code == 200
    html = response.data.decode("utf-8")
    assert "Public Demo Credentials" in html
    assert "Quick Fill Demo User" in html
    assert "demo@moviemagic.com" in html
    # Ensure admin credentials are NEVER exposed in frontend HTML or JS
    assert "admin@moviemagic.com" not in html
    assert "Admin@123" not in html


def test_login_page_hides_demo_credentials_when_disabled(app, client):
    """Verify demo credential helpers are completely omitted from DOM when disabled."""
    app.config["SHOW_DEMO_CREDENTIALS"] = False
    try:
        response = client.get("/auth/login")
        assert response.status_code == 200
        html = response.data.decode("utf-8")
        assert "Public Demo Credentials" not in html
        assert "Quick Fill Demo User" not in html
        assert "fillDemoCredentials" not in html
        assert "demo@moviemagic.com" not in html
        assert "admin@moviemagic.com" not in html
        assert "Admin@123" not in html
    finally:
        app.config["SHOW_DEMO_CREDENTIALS"] = True
