"""User Repository layer supporting both In-Memory (Mock) and DynamoDB implementations.

Features:
- Normalized email handling across all lookups, reservations, and mutations.
- Strict atomic email uniqueness via DynamoDB TransactWriteItems (User Profile + EMAIL# lock).
- Inspection of TransactionCanceledException cancellation reasons.
- Zero schema modifications to the moviemagic_users table.
- Strict anti-degradation rule: USE_AWS_MOCK=False never silently falls back to mock.
- Transparent UserRepositoryProxy preserving backward-compatible user_repository imports.
"""

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from boto3.dynamodb.types import TypeDeserializer
from botocore.exceptions import ClientError

from app.aws.client_factory import get_boto3_client, is_mock_mode_active
from app.utils.security import hash_password
from .base import BaseRepository

logger = logging.getLogger(__name__)
_deserializer = TypeDeserializer()


class DuplicateEmailError(ValueError):
    """Raised when user registration fails due to an already registered email."""
    pass


class UserPersistenceError(RuntimeError):
    """Raised when user creation or retrieval fails due to a database/service error."""
    pass


def normalize_email(email: Optional[str]) -> str:
    """Normalize an email address: strip whitespace and lowercase."""
    if not email:
        return ""
    return str(email).strip().lower()


def deserialize_dynamodb_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Convert low-level DynamoDB typed item into standard Python dictionary."""
    if not item:
        return {}
    deserialized = {k: _deserializer.deserialize(v) for k, v in item.items()}
    if "user_id" in deserialized and "id" not in deserialized:
        deserialized["id"] = deserialized["user_id"]
    elif "id" in deserialized and "user_id" not in deserialized:
        deserialized["user_id"] = deserialized["id"]
    return deserialized


def is_email_lock_conditional_failure(client_error: ClientError) -> bool:
    """Inspect TransactionCanceledException cancellation reasons.

    Returns True ONLY if the email-lock condition check (TransactItems index 1) failed.
    """
    error_code = client_error.response.get("Error", {}).get("Code")
    if error_code != "TransactionCanceledException":
        return False

    reasons = client_error.response.get("CancellationReasons", [])
    # In transact_write_items:
    # Index 0 is the User Profile Put
    # Index 1 is the Email Reservation Lock Put
    if reasons and len(reasons) > 1:
        email_lock_reason = reasons[1].get("Code")
        if email_lock_reason == "ConditionalCheckFailed":
            return True
        return False

    # If CancellationReasons array is empty/omitted by older client/emulator:
    error_msg = client_error.response.get("Error", {}).get("Message", "")
    return "ConditionalCheckFailed" in error_msg


class InMemoryUserRepository(BaseRepository):
    """User data access repository with in-memory store for development and testing."""

    def __init__(self):
        self._users: Dict[str, Dict[str, Any]] = {}
        self._email_index: Dict[str, str] = {}
        self._seed_initial_users()

    def _seed_initial_users(self):
        """Seed demo users with securely hashed passwords."""
        demo_users = [
            {
                "id": "usr-admin-1",
                "user_id": "usr-admin-1",
                "email": "admin@moviemagic.com",
                "full_name": "Admin Manager",
                "password_hash": hash_password("Admin@123"),
                "role": "admin",
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            {
                "id": "usr-demo-1",
                "user_id": "usr-demo-1",
                "email": "demo@moviemagic.com",
                "full_name": "Demo Moviegoer",
                "password_hash": hash_password("Demo@123"),
                "role": "user",
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        ]
        for user in demo_users:
            norm_email = normalize_email(user["email"])
            user["email"] = norm_email
            self._users[user["id"]] = user
            self._email_index[norm_email] = user["id"]

    def get_by_id(self, item_id: str) -> Optional[Dict[str, Any]]:
        return self._users.get(str(item_id).strip() if item_id else "")

    def get_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        norm_email = normalize_email(email)
        user_id = self._email_index.get(norm_email)
        if user_id:
            return self._users.get(user_id)
        return None

    def get_all(self) -> List[Dict[str, Any]]:
        return list(self._users.values())

    def create_user(
        self,
        email: str,
        password_hash: str,
        full_name: str,
        role: str = "user"
    ) -> Dict[str, Any]:
        """Create a new user record in memory with uniqueness check."""
        norm_email = normalize_email(email)
        if not norm_email:
            raise ValueError("Email address cannot be empty.")

        if norm_email in self._email_index:
            raise DuplicateEmailError(f"An account with this email address already exists: {norm_email}")

        user_id = f"usr-{uuid.uuid4().hex[:12]}"
        user = {
            "id": user_id,
            "user_id": user_id,
            "email": norm_email,
            "password_hash": password_hash,
            "full_name": full_name.strip(),
            "role": role,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._users[user_id] = user
        self._email_index[norm_email] = user_id
        return user


class DynamoDBUserRepository(BaseRepository):
    """DynamoDB user data access repository.

    Persists user accounts in moviemagic_users and enforces email uniqueness
    via atomic transactions with email lock records.
    """

    def __init__(
        self,
        client: Optional[Any] = None,
        table_name: Optional[str] = None,
        table_prefix: Optional[str] = None,
    ):
        self.client = client
        prefix = table_prefix or os.environ.get("DYNAMODB_TABLE_PREFIX", "moviemagic_")
        self.table_name = table_name or f"{prefix}users"

    def _ensure_client(self):
        """Ensure client is present or initialize via factory."""
        if not self.client:
            self.client = get_boto3_client("dynamodb")
            if not self.client:
                raise RuntimeError(
                    "Configuration Error: USE_AWS_MOCK is set to False, but AWS DynamoDB client "
                    "could not be initialized. Check AWS credentials (AWS_PROFILE, IAM role, or env vars) "
                    "and AWS_REGION. Silent fallback to in-memory mock is prohibited."
                )

    def get_by_id(self, item_id: str) -> Optional[Dict[str, Any]]:
        self._ensure_client()
        if not item_id:
            return None
        clean_id = str(item_id).strip()
        try:
            resp = self.client.get_item(
                TableName=self.table_name,
                Key={"user_id": {"S": clean_id}},
            )
            raw = resp.get("Item")
            if not raw:
                return None
            item = deserialize_dynamodb_item(raw)
            # Filter out email reservation lock items so they are never returned as user profiles
            if item.get("type") == "EMAIL_LOCK":
                return None
            return item
        except ClientError as e:
            logger.error("DynamoDB get_by_id error for user_id=%s: %s", clean_id, e)
            raise UserPersistenceError(f"Database error retrieving user by ID: {e}")

    def get_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        self._ensure_client()
        norm_email = normalize_email(email)
        if not norm_email:
            return None
        try:
            resp = self.client.query(
                TableName=self.table_name,
                IndexName="EmailIndex",
                KeyConditionExpression="email = :email",
                ExpressionAttributeValues={":email": {"S": norm_email}},
                Limit=1,
            )
            items = resp.get("Items", [])
            if not items:
                return None
            return deserialize_dynamodb_item(items[0])
        except ClientError as e:
            logger.error("DynamoDB get_by_email error for email=%s: %s", norm_email, e)
            raise UserPersistenceError(f"Database error retrieving user by email: {e}")

    def get_all(self) -> List[Dict[str, Any]]:
        self._ensure_client()
        try:
            resp = self.client.scan(
                TableName=self.table_name,
                FilterExpression="#t = :user_type",
                ExpressionAttributeNames={"#t": "type"},
                ExpressionAttributeValues={":user_type": {"S": "USER"}},
            )
            items = resp.get("Items", [])
            return [deserialize_dynamodb_item(item) for item in items]
        except ClientError as e:
            logger.error("DynamoDB get_all error: %s", e)
            raise UserPersistenceError(f"Database error retrieving users: {e}")

    def create_user(
        self,
        email: str,
        password_hash: str,
        full_name: str,
        role: str = "user"
    ) -> Dict[str, Any]:
        """Atomically create user profile and email uniqueness lock record."""
        self._ensure_client()
        norm_email = normalize_email(email)
        if not norm_email:
            raise ValueError("Email address cannot be empty.")

        user_id = f"usr-{uuid.uuid4().hex[:12]}"
        created_at = datetime.now(timezone.utc).isoformat()

        # Item 1: User Profile (has email, indexed in EmailIndex)
        user_item = {
            "user_id": {"S": user_id},
            "type": {"S": "USER"},
            "email": {"S": norm_email},
            "password_hash": {"S": password_hash},
            "full_name": {"S": full_name.strip()},
            "role": {"S": role},
            "created_at": {"S": created_at},
        }

        # Item 2: Email Reservation Lock (omits 'email' so it is NOT indexed into EmailIndex)
        lock_item = {
            "user_id": {"S": f"EMAIL#{norm_email}"},
            "type": {"S": "EMAIL_LOCK"},
            "target_user_id": {"S": user_id},
            "created_at": {"S": created_at},
        }

        try:
            self.client.transact_write_items(
                TransactItems=[
                    {
                        "Put": {
                            "TableName": self.table_name,
                            "Item": user_item,
                            "ConditionExpression": "attribute_not_exists(user_id)",
                        }
                    },
                    {
                        "Put": {
                            "TableName": self.table_name,
                            "Item": lock_item,
                            "ConditionExpression": "attribute_not_exists(user_id)",
                        }
                    },
                ]
            )
            return {
                "id": user_id,
                "user_id": user_id,
                "email": norm_email,
                "full_name": full_name.strip(),
                "password_hash": password_hash,
                "role": role,
                "created_at": created_at,
            }
        except ClientError as e:
            if is_email_lock_conditional_failure(e):
                logger.warning("Duplicate registration rejected for email: %s", norm_email)
                raise DuplicateEmailError(f"An account with this email address already exists: {norm_email}")
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            logger.error("DynamoDB transact_write_items failed with code %s: %s", error_code, e)
            raise UserPersistenceError(f"Failed to create user account: {error_code}")


_in_memory_instance: Optional[InMemoryUserRepository] = None
_dynamo_instance: Optional[DynamoDBUserRepository] = None


def get_user_repository() -> BaseRepository:
    """Resolve user repository according to active configuration.

    Guarantees:
    - If USE_AWS_MOCK is True, returns InMemoryUserRepository singleton.
    - If USE_AWS_MOCK is False, returns DynamoDBUserRepository.
    - NEVER silently degrades to mock mode if live mode is misconfigured.
    """
    global _in_memory_instance, _dynamo_instance

    if is_mock_mode_active():
        if _in_memory_instance is None:
            _in_memory_instance = InMemoryUserRepository()
        return _in_memory_instance

    # Live DynamoDB requested: ensure client is initializable
    client = get_boto3_client("dynamodb")
    if not client:
        raise RuntimeError(
            "Configuration Error: USE_AWS_MOCK is set to False, but AWS DynamoDB client "
            "could not be initialized. Check AWS credentials (AWS_PROFILE, IAM role, or env vars) "
            "and AWS_REGION. Silent fallback to in-memory mock is prohibited."
        )

    if _dynamo_instance is None or _dynamo_instance.client is not client:
        _dynamo_instance = DynamoDBUserRepository(client=client)
    return _dynamo_instance


class UserRepositoryProxy(BaseRepository):
    """Transparent proxy delegating calls to the active UserRepository."""

    @property
    def active_repo(self) -> BaseRepository:
        return get_user_repository()

    def get_by_id(self, item_id: str) -> Optional[Dict[str, Any]]:
        return self.active_repo.get_by_id(item_id)

    def get_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        return self.active_repo.get_by_email(email)

    def get_all(self) -> List[Dict[str, Any]]:
        return self.active_repo.get_all()

    def create_user(
        self,
        email: str,
        password_hash: str,
        full_name: str,
        role: str = "user"
    ) -> Dict[str, Any]:
        return self.active_repo.create_user(
            email=email,
            password_hash=password_hash,
            full_name=full_name,
            role=role
        )


user_repository = UserRepositoryProxy()
UserRepository = InMemoryUserRepository  # Backward compatibility alias
