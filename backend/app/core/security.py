"""Password hashing, JWT access tokens and at-rest encryption of third-party tokens."""
from __future__ import annotations

import base64
import hashlib
import re
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

JWT_ALGORITHM = "HS256"


# --- Passwords ------------------------------------------------------------------

def hash_password(password: str) -> str:
    # bcrypt only uses the first 72 bytes; pre-hash to avoid silent truncation.
    digest = base64.b64encode(hashlib.sha256(password.encode("utf-8")).digest())
    return bcrypt.hashpw(digest, bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    digest = base64.b64encode(hashlib.sha256(password.encode("utf-8")).digest())
    try:
        return bcrypt.checkpw(digest, password_hash.encode("ascii"))
    except ValueError:
        return False


PASSWORD_RULES = "at least 10 characters, including a letter and a number"


def password_is_strong(password: str) -> bool:
    return len(password) >= 10 and re.search(r"[A-Za-z]", password) is not None and re.search(r"\d", password) is not None


# --- JWT --------------------------------------------------------------------------

def create_access_token(user_id: int, token_version: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "ver": token_version,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_expire_minutes)).timestamp()),
        "typ": "access",
    }
    return jwt.encode(payload, settings.secret_key, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[JWT_ALGORITHM], options={"require": ["exp", "sub"]})
    except jwt.PyJWTError:
        return None
    if payload.get("typ") != "access":
        return None
    return payload


def create_state_token(user_id: int, purpose: str, minutes: int = 10) -> str:
    """Short-lived signed token, used as the OAuth ``state`` parameter (CSRF protection)."""
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "typ": purpose, "exp": int((now + timedelta(minutes=minutes)).timestamp())}
    return jwt.encode(payload, settings.secret_key, algorithm=JWT_ALGORITHM)


def decode_state_token(token: str, purpose: str) -> int | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
    if payload.get("typ") != purpose:
        return None
    return int(payload["sub"])


# --- Token encryption -------------------------------------------------------------

def _fernet() -> Fernet:
    if settings.token_encryption_key:
        key = settings.token_encryption_key.encode()
    else:
        # Derive a stable Fernet key from SECRET_KEY (domain-separated).
        raw = hashlib.sha256(("testpilot-token-encryption:" + settings.secret_key).encode()).digest()
        key = base64.urlsafe_b64encode(raw)
    return Fernet(key)


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str) -> str | None:
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None
