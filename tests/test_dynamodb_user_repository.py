"""Unit tests for DynamoDB User Repository, atomic uniqueness, and authentication.

Verifies:
- Email normalization across registrations, lookups, and locks
- Atomic email uniqueness via DynamoDB TransactWriteItems
- Selective mapping of TransactionCanceledException cancellation reasons (only email lock = DuplicateEmailError)
- Non-silent failure when USE_AWS_MOCK=False is misconfigured
- Full compatibility with existing password hashing and session contracts
- Zero live AWS calls (all AWS interactions mocked)
"""

import os
from unittest.mock import MagicMock, patch
import pytest
from botocore.exceptions import ClientError

from app.repositories.user_repository import (
    InMemoryUserRepository,
    DynamoDBUserRepository,
    DuplicateEmailError,
    UserPersistenceError,
    normalize_email,
    is_email_lock_conditional_failure,
    get_user_repository,
    UserRepositoryProxy,
)
from app.services.auth_service import AuthService
from app.utils.security import hash_password, verify_password


class TestEmailNormalization:
    """Test email address normalization."""

    def test_normalize_email_trims_and_lowercases(self):
        assert normalize_email("  User@Example.COM  ") == "user@example.com"
        assert normalize_email("TEST@MovieMagic.Com") == "test@moviemagic.com"
        assert normalize_email("") == ""
        assert normalize_email(None) == ""


class TestInMemoryUserRepository:
    """Verify in-memory repository retains demo users and enforces uniqueness."""

    def test_demo_accounts_seeded_and_accessible(self):
        repo = InMemoryUserRepository()
        admin = repo.get_by_email("admin@moviemagic.com")
        assert admin is not None
        assert admin["role"] == "admin"
        assert verify_password("Admin@123", admin["password_hash"])

        demo = repo.get_by_email("DEMO@MovieMagic.COM")
        assert demo is not None
        assert demo["role"] == "user"
        assert verify_password("Demo@123", demo["password_hash"])

    def test_duplicate_email_raises_duplicate_email_error(self):
        repo = InMemoryUserRepository()
        with pytest.raises(DuplicateEmailError):
            repo.create_user(
                email="demo@moviemagic.com",
                password_hash=hash_password("NewPassword@123"),
                full_name="Duplicate Demo",
            )


class TestCancellationReasonInspection:
    """Verify selective mapping of DynamoDB TransactionCanceledException."""

    def test_email_lock_failure_detected(self):
        """Index 1 (email lock) ConditionalCheckFailed maps to email lock failure."""
        error_response = {
            "Error": {"Code": "TransactionCanceledException", "Message": "Transaction cancelled"},
            "CancellationReasons": [
                {"Code": "None"},
                {"Code": "ConditionalCheckFailed", "Message": "Conditional check failed"},
            ],
        }
        client_error = ClientError(error_response, "TransactWriteItems")
        assert is_email_lock_conditional_failure(client_error) is True

    def test_user_id_collision_is_not_email_lock_failure(self):
        """Index 0 (user profile) ConditionalCheckFailed is NOT an email lock failure."""
        error_response = {
            "Error": {"Code": "TransactionCanceledException", "Message": "Transaction cancelled"},
            "CancellationReasons": [
                {"Code": "ConditionalCheckFailed", "Message": "Conditional check failed"},
                {"Code": "None"},
            ],
        }
        client_error = ClientError(error_response, "TransactWriteItems")
        assert is_email_lock_conditional_failure(client_error) is False

    def test_transaction_conflict_is_not_email_lock_failure(self):
        """Transaction conflict (concurrency race) is NOT classified as duplicate email."""
        error_response = {
            "Error": {"Code": "TransactionCanceledException", "Message": "Transaction cancelled"},
            "CancellationReasons": [
                {"Code": "TransactionConflict", "Message": "Transaction conflict"},
                {"Code": "TransactionConflict", "Message": "Transaction conflict"},
            ],
        }
        client_error = ClientError(error_response, "TransactWriteItems")
        assert is_email_lock_conditional_failure(client_error) is False


class TestDynamoDBUserRepository:
    """Test DynamoDBUserRepository operations using mocked Boto3 client."""

    @pytest.fixture
    def mock_dynamo_client(self):
        client = MagicMock()
        return client

    @pytest.fixture
    def repo(self, mock_dynamo_client):
        return DynamoDBUserRepository(client=mock_dynamo_client, table_name="moviemagic_users")

    def test_create_user_submits_atomic_transaction(self, repo, mock_dynamo_client):
        """create_user writes User Profile and Email Lock in a single transaction."""
        hashed = hash_password("SecurePass@123")
        created = repo.create_user(
            email="  NEW_USER@MovieMagic.COM  ",
            password_hash=hashed,
            full_name="New Cinema Fan",
            role="user",
        )

        assert created["email"] == "new_user@moviemagic.com"
        assert created["id"].startswith("usr-")
        assert created["user_id"] == created["id"]
        assert created["full_name"] == "New Cinema Fan"

        mock_dynamo_client.transact_write_items.assert_called_once()
        _, kwargs = mock_dynamo_client.transact_write_items.call_args
        items = kwargs["TransactItems"]
        assert len(items) == 2

        # Item 0: User Profile
        user_put = items[0]["Put"]
        assert user_put["TableName"] == "moviemagic_users"
        assert user_put["ConditionExpression"] == "attribute_not_exists(user_id)"
        assert user_put["Item"]["type"] == {"S": "USER"}
        assert user_put["Item"]["email"] == {"S": "new_user@moviemagic.com"}

        # Item 1: Email Lock (Omit 'email' so GSI is not polluted)
        lock_put = items[1]["Put"]
        assert lock_put["TableName"] == "moviemagic_users"
        assert lock_put["ConditionExpression"] == "attribute_not_exists(user_id)"
        assert lock_put["Item"]["user_id"] == {"S": "EMAIL#new_user@moviemagic.com"}
        assert lock_put["Item"]["type"] == {"S": "EMAIL_LOCK"}
        assert "email" not in lock_put["Item"]  # Sparse GSI guarantee

    def test_create_user_duplicate_email_raises_duplicate_email_error(self, repo, mock_dynamo_client):
        """When email lock conditional check fails, DuplicateEmailError is raised."""
        error_response = {
            "Error": {"Code": "TransactionCanceledException"},
            "CancellationReasons": [
                {"Code": "None"},
                {"Code": "ConditionalCheckFailed"},
            ],
        }
        mock_dynamo_client.transact_write_items.side_effect = ClientError(
            error_response, "TransactWriteItems"
        )

        with pytest.raises(DuplicateEmailError) as exc_info:
            repo.create_user(
                email="existing@moviemagic.com",
                password_hash="hash",
                full_name="Existing User",
            )
        assert "already exists" in str(exc_info.value)

    def test_create_user_other_error_raises_user_persistence_error(self, repo, mock_dynamo_client):
        """When a non-email lock error occurs, UserPersistenceError is raised."""
        error_response = {
            "Error": {"Code": "ProvisionedThroughputExceededException"},
        }
        mock_dynamo_client.transact_write_items.side_effect = ClientError(
            error_response, "TransactWriteItems"
        )

        with pytest.raises(UserPersistenceError):
            repo.create_user(
                email="throttled@moviemagic.com",
                password_hash="hash",
                full_name="Throttled User",
            )

    def test_get_by_email_queries_email_index(self, repo, mock_dynamo_client):
        """get_by_email queries EmailIndex with normalized email and deserializes attributes."""
        mock_dynamo_client.query.return_value = {
            "Items": [
                {
                    "user_id": {"S": "usr-12345"},
                    "email": {"S": "queried@moviemagic.com"},
                    "full_name": {"S": "Queried User"},
                    "password_hash": {"S": "stored_hash"},
                    "role": {"S": "user"},
                    "type": {"S": "USER"},
                }
            ]
        }

        user = repo.get_by_email("  QUERIED@moviemagic.com ")
        assert user is not None
        assert user["id"] == "usr-12345"
        assert user["user_id"] == "usr-12345"
        assert user["email"] == "queried@moviemagic.com"
        assert user["full_name"] == "Queried User"

        mock_dynamo_client.query.assert_called_once_with(
            TableName="moviemagic_users",
            IndexName="EmailIndex",
            KeyConditionExpression="email = :email",
            ExpressionAttributeValues={":email": {"S": "queried@moviemagic.com"}},
            Limit=1,
        )

    def test_get_by_id_ignores_email_lock_item(self, repo, mock_dynamo_client):
        """get_by_id ignores email lock items if requested."""
        mock_dynamo_client.get_item.return_value = {
            "Item": {
                "user_id": {"S": "EMAIL#test@moviemagic.com"},
                "type": {"S": "EMAIL_LOCK"},
                "target_user_id": {"S": "usr-999"},
            }
        }
        user = repo.get_by_id("EMAIL#test@moviemagic.com")
        assert user is None

    def test_get_all_filters_only_users(self, repo, mock_dynamo_client):
        """get_all executes scan filtering for type='USER'."""
        mock_dynamo_client.scan.return_value = {
            "Items": [
                {
                    "user_id": {"S": "usr-1"},
                    "type": {"S": "USER"},
                    "email": {"S": "u1@moviemagic.com"},
                    "full_name": {"S": "User One"},
                    "role": {"S": "user"},
                }
            ]
        }
        users = repo.get_all()
        assert len(users) == 1
        assert users[0]["user_id"] == "usr-1"
        mock_dynamo_client.scan.assert_called_once_with(
            TableName="moviemagic_users",
            FilterExpression="#t = :user_type",
            ExpressionAttributeNames={"#t": "type"},
            ExpressionAttributeValues={":user_type": {"S": "USER"}},
        )


class TestAuthServiceIntegration:
    """Test AuthService business logic with mocked DynamoDB repository."""

    def test_register_duplicate_email_returns_user_friendly_message(self):
        mock_repo = MagicMock()
        mock_repo.get_by_email.return_value = None  # Pre-check passes
        mock_repo.create_user.side_effect = DuplicateEmailError("Duplicate email")

        service = AuthService(repo=mock_repo)
        success, msg, user = service.register(
            email="duplicate@moviemagic.com",
            password="ValidSecret123",
            full_name="Duplicate Tester",
        )

        assert success is False
        assert "already exists" in msg
        assert user is None

    def test_register_persistence_error_returns_friendly_error(self):
        mock_repo = MagicMock()
        mock_repo.get_by_email.return_value = None
        mock_repo.create_user.side_effect = UserPersistenceError("DynamoDB unavailable")

        service = AuthService(repo=mock_repo)
        success, msg, user = service.register(
            email="fail@moviemagic.com",
            password="ValidSecret123",
            full_name="Fail Tester",
        )

        assert success is False
        assert "Unable to complete registration at this time" in msg
        assert user is None

    def test_authenticate_successful_with_dynamo_user(self):
        mock_repo = MagicMock()
        password = "CorrectPassword123"
        mock_repo.get_by_email.return_value = {
            "id": "usr-dyn-1",
            "email": "cinema@moviemagic.com",
            "password_hash": hash_password(password),
            "full_name": "Cinema Fan",
            "role": "user",
        }

        service = AuthService(repo=mock_repo)
        success, msg, user = service.authenticate("  CINEMA@moviemagic.COM ", password)
        assert success is True
        assert "Sign in successful" in msg
        assert user["id"] == "usr-dyn-1"

    def test_authenticate_invalid_password(self):
        mock_repo = MagicMock()
        mock_repo.get_by_email.return_value = {
            "id": "usr-dyn-1",
            "email": "cinema@moviemagic.com",
            "password_hash": hash_password("CorrectPassword123"),
            "full_name": "Cinema Fan",
            "role": "user",
        }

        service = AuthService(repo=mock_repo)
        success, msg, user = service.authenticate("cinema@moviemagic.com", "WrongPassword")
        assert success is False
        assert "Invalid email or password" in msg
        assert user is None


class TestConfigurationAndAntiDegradation:
    """Verify repository selection and strict anti-degradation rule."""

    def test_mock_mode_active_returns_in_memory_repository(self, monkeypatch):
        monkeypatch.setenv("USE_AWS_MOCK", "True")
        repo = get_user_repository()
        assert isinstance(repo, InMemoryUserRepository)

    def test_live_mode_misconfiguration_raises_runtime_error(self, monkeypatch):
        """When USE_AWS_MOCK=False but client cannot be initialized, raise RuntimeError."""
        monkeypatch.setenv("USE_AWS_MOCK", "False")
        with patch("app.repositories.user_repository.get_boto3_client", return_value=None):
            with pytest.raises(RuntimeError) as exc_info:
                get_user_repository()
            assert "Silent fallback to in-memory mock is prohibited" in str(exc_info.value)

    def test_repository_proxy_delegation(self):
        proxy = UserRepositoryProxy()
        # In testing/default environment, delegates to InMemoryUserRepository
        admin = proxy.get_by_email("admin@moviemagic.com")
        assert admin is not None
        assert admin["role"] == "admin"
