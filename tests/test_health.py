"""Tests for the application health check endpoint."""


def test_health_check_returns_200(client):
    """Verify /health returns HTTP 200 OK."""
    response = client.get("/health")
    assert response.status_code == 200


def test_health_check_payload(client):
    """Verify /health returns expected JSON structure."""
    response = client.get("/health")
    data = response.get_json()

    assert data is not None
    assert data.get("status") == "healthy"
    assert data.get("service") == "Movie Magic"
    assert "version" in data
    assert "environment" in data
    assert "aws_mode" in data
