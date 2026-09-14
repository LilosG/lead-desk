import hashlib
import os

import pytest
from fastapi.testclient import TestClient


TEST_USERNAME = "test-admin"
TEST_PASSWORD = "test-password-strong-enough"
TEST_SALT = bytes.fromhex("00112233445566778899aabbccddeeff")
TEST_DIGEST = hashlib.pbkdf2_hmac(
    "sha256",
    TEST_PASSWORD.encode("utf-8"),
    TEST_SALT,
    310_000,
)

os.environ.setdefault("AUTH_USERNAME", TEST_USERNAME)
os.environ.setdefault(
    "AUTH_PASSWORD_HASH",
    f"pbkdf2_sha256$310000${TEST_SALT.hex()}${TEST_DIGEST.hex()}",
)
os.environ.setdefault(
    "AUTH_SESSION_SECRET",
    "test-session-secret-that-is-longer-than-thirty-two-characters",
)

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def public_client():
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client


@pytest.fixture(scope="session")
def client():
    with TestClient(app, base_url="https://testserver") as test_client:
        response = test_client.post(
            "/api/auth/login",
            json={"username": TEST_USERNAME, "password": TEST_PASSWORD},
        )
        assert response.status_code == 200
        yield test_client
