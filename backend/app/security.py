"""Password hashing and JWT access tokens.

The only module that touches passlib/PyJWT, so swapping either library later
is contained here.
"""

import secrets
from datetime import UTC, datetime, timedelta

import jwt
from passlib.context import CryptContext

from app.config import settings
from app.models.user import Role

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(plain, hashed)
    except ValueError:
        # Malformed/unknown hash: treat as a failed login, not a 500.
        return False


def make_unusable_password_hash() -> str:
    """A valid bcrypt hash of a discarded random secret.

    Used for imported/placeholder accounts: password_hash stays NOT NULL, but
    no password can ever verify against it until an admin sets a real one.
    """
    return hash_password(secrets.token_urlsafe(32))


def create_access_token(*, user_id: int, role: Role) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),  # JWT requires a string subject (PyJWT >= 2.10)
        "role": role.value,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """Decode and validate a token; raises jwt.InvalidTokenError if bad."""
    return jwt.decode(token, settings.jwt_secret_key, [settings.jwt_algorithm])
