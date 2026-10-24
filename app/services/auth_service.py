"""Authentication Service.
Handles user registration, login verification, password strength checks, and session data.
"""
import logging
from typing import Optional, Dict, Any, Tuple
from app.repositories import (
    user_repository,
    DuplicateEmailError,
    UserPersistenceError,
    normalize_email,
)
from app.utils.security import hash_password, verify_password, validate_password_strength

logger = logging.getLogger(__name__)


class AuthService:
    """Business logic for authentication and authorization."""

    def __init__(self, repo=None, email_service=None):
        self._repo = repo
        self._email_service = email_service

    @property
    def email_service(self):
        """Active email service adapter."""
        if self._email_service is not None:
            return self._email_service
        from app.services.email_service import email_service
        return email_service

    @property
    def repo(self):
        """Active user repository."""
        if self._repo is not None:
            return self._repo
        return user_repository

    def register(self, email: str, password: str, full_name: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Register a new user account with normalized email and atomic uniqueness."""
        norm_email = normalize_email(email)
        if not norm_email or "@" not in norm_email:
            return False, "A valid email address is required.", None

        existing_user = self.repo.get_by_email(norm_email)
        if existing_user:
            return False, "An account with this email address already exists.", None

        is_strong, msg = validate_password_strength(password)
        if not is_strong:
            return False, msg, None

        if not full_name or len(full_name.strip()) < 2:
            return False, "Please enter your full name.", None

        hashed = hash_password(password)
        try:
            new_user = self.repo.create_user(
                email=norm_email,
                password_hash=hashed,
                full_name=full_name,
                role="user"
            )
        except DuplicateEmailError:
            return False, "An account with this email address already exists.", None
        except UserPersistenceError as e:
            logger.error("User persistence failure during registration: %s", type(e).__name__)
            return False, "Unable to complete registration at this time. Please try again later.", None
        except Exception as e:
            logger.error("Unexpected error during registration: %s", type(e).__name__)
            return False, "Unable to complete registration at this time. Please try again later.", None

        # Isolated customer welcome email dispatch: email failure must NEVER invalidate a successful registration
        try:
            self.email_service.send_welcome_email(
                user_email=new_user.get("email", norm_email),
                user_name=new_user.get("full_name", full_name),
            )
        except Exception as email_err:
            logger.error("Failed to dispatch welcome email for %s: %s", norm_email, email_err)

        return True, "Registration successful! You may now sign in.", new_user

    def authenticate(self, email: str, password: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Authenticate user by email and password."""
        norm_email = normalize_email(email)
        try:
            user = self.repo.get_by_email(norm_email)
        except Exception as e:
            logger.error("Error retrieving user during authentication: %s", type(e).__name__)
            return False, "Unable to sign in at this time. Please try again later.", None

        if not user:
            return False, "Invalid email or password.", None

        if not verify_password(password, user.get("password_hash", "")):
            return False, "Invalid email or password.", None

        return True, "Sign in successful.", user

    def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        return self.repo.get_by_id(user_id)


auth_service = AuthService()
