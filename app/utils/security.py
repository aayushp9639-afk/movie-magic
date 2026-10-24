"""Security utilities: password hashing and verification using Werkzeug.
Ensures passwords are never stored in plaintext and meet strength standards.
"""
import re
from werkzeug.security import generate_password_hash, check_password_hash


def hash_password(password: str) -> str:
    """Hash password using scrypt or pbkdf2:sha256."""
    return generate_password_hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Safely verify plain password against stored hash."""
    if not plain_password or not hashed_password:
        return False
    return check_password_hash(hashed_password, plain_password)


def validate_password_strength(password: str) -> tuple[bool, str]:
    """Validate password meets minimum complexity rules."""
    if len(password) < 8:
        return False, "Password must be at least 8 characters long."
    if not re.search(r"[A-Z]", password):
        return False, "Password must include at least one uppercase letter."
    if not re.search(r"[a-z]", password):
        return False, "Password must include at least one lowercase letter."
    if not re.search(r"\d", password):
        return False, "Password must include at least one digit."
    return True, ""
