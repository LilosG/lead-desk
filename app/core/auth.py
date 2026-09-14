from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass

from fastapi import Request

from app.core.config import get_settings


SESSION_COOKIE = "lead_desk_session"
SESSION_TTL_SECONDS = 12 * 60 * 60
PASSWORD_ITERATIONS = 310_000


@dataclass(frozen=True)
class SessionIdentity:
    username: str
    expires_at: int


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS,
    )
    return (
        f"pbkdf2_sha256${PASSWORD_ITERATIONS}$"
        f"{salt.hex()}${digest.hex()}"
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            int(iterations),
        )
        return hmac.compare_digest(actual, expected)
    except (TypeError, ValueError):
        return False


def create_session_token(username: str) -> str:
    settings = get_settings()
    expires_at = int(time.time()) + SESSION_TTL_SECONDS
    payload = f"{username}|{expires_at}".encode("utf-8")
    signature = hmac.new(
        settings.auth_session_secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).digest()
    return f"{_b64encode(payload)}.{_b64encode(signature)}"


def parse_session_token(token: str | None) -> SessionIdentity | None:
    if not token:
        return None

    settings = get_settings()
    try:
        encoded_payload, encoded_signature = token.split(".", 1)
        payload = _b64decode(encoded_payload)
        signature = _b64decode(encoded_signature)
        expected = hmac.new(
            settings.auth_session_secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(signature, expected):
            return None

        username, raw_expiry = payload.decode("utf-8").rsplit("|", 1)
        expires_at = int(raw_expiry)
        if expires_at <= int(time.time()):
            return None
        if not hmac.compare_digest(username, settings.auth_username):
            return None
        return SessionIdentity(username=username, expires_at=expires_at)
    except (ValueError, UnicodeDecodeError):
        return None


def session_from_request(request: Request) -> SessionIdentity | None:
    return parse_session_token(request.cookies.get(SESSION_COOKIE))
