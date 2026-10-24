"""Tests verifying the structure, safety, and validity of deployment artifacts."""
import json
from pathlib import Path

DEPLOY_DIR = Path(__file__).resolve().parent.parent / "deploy"


def test_iam_policy_json_validity_and_transaction_permission():
    """Verify deploy/iam-ec2-policy.json contains valid JSON and dynamodb:TransactWriteItems."""
    policy_file = DEPLOY_DIR / "iam-ec2-policy.json"
    assert policy_file.exists(), "iam-ec2-policy.json must exist"

    with open(policy_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data.get("Version") == "2012-10-17"
    statements = data.get("Statement", [])
    assert len(statements) >= 2

    # Verify DynamoDB statement
    dynamo_stmt = next((s for s in statements if s.get("Sid") == "DynamoDBTableAccess"), None)
    assert dynamo_stmt is not None
    actions = dynamo_stmt.get("Action", [])
    assert "dynamodb:TransactWriteItems" in actions
    assert "dynamodb:GetItem" in actions
    assert "dynamodb:PutItem" in actions
    assert "dynamodb:ConditionCheckItem" in actions

    # Verify all 6 tables and index paths are explicitly listed
    resources = dynamo_stmt.get("Resource", [])
    assert any("table/moviemagic_users" in r for r in resources)
    assert any("table/moviemagic_movies" in r for r in resources)
    assert any("table/moviemagic_theaters" in r for r in resources)
    assert any("table/moviemagic_showtimes" in r for r in resources)
    assert any("table/moviemagic_bookings" in r for r in resources)
    assert any("table/moviemagic_show_seats" in r for r in resources)

    # Verify SNS statement
    sns_stmt = next((s for s in statements if s.get("Sid") == "SNSTopicPublishAccess"), None)
    assert sns_stmt is not None
    assert "sns:Publish" in sns_stmt.get("Action", [])


def test_systemd_service_file_structure():
    """Verify deploy/moviemagic.service has correct paths and Gunicorn parameters."""
    service_file = DEPLOY_DIR / "moviemagic.service"
    assert service_file.exists(), "moviemagic.service must exist"

    content = service_file.read_text(encoding="utf-8")
    assert "WorkingDirectory=/home/ec2-user/movie-magic" in content
    assert "EnvironmentFile=" in content
    assert "/home/ec2-user/movie-magic/.venv/bin/gunicorn" in content
    assert '"run:app"' in content
    assert "User=ec2-user" in content


def test_ec2_setup_script_secret_protection():
    """Verify deploy/ec2-setup.sh does not overwrite existing .env secrets."""
    setup_file = DEPLOY_DIR / "ec2-setup.sh"
    assert setup_file.exists(), "ec2-setup.sh must exist"

    content = setup_file.read_text(encoding="utf-8")
    # Verify file-existence check before creating .env
    assert 'if [ ! -f "${APP_DIR}/.env" ]; then' in content
    # Verify secret generation via python secrets module
    assert "secrets.token_hex(32)" in content
    # Verify preserve message
    assert "Preserving existing SECRET_KEY" in content


def test_nginx_conf_structure():
    """Verify deploy/nginx-moviemagic.conf proxies port 80 to 5000 and serves static files."""
    conf_file = DEPLOY_DIR / "nginx-moviemagic.conf"
    assert conf_file.exists(), "nginx-moviemagic.conf must exist"

    content = conf_file.read_text(encoding="utf-8")
    assert "listen 80;" in content
    assert "proxy_pass http://moviemagic_upstream;" in content
    assert "alias /home/ec2-user/movie-magic/app/static/;" in content
    assert "location /health" in content
