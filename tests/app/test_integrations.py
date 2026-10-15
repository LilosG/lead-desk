from __future__ import annotations

import base64

from app.core.config import Settings
from app.core.crypto import CredentialCipher
from app.services.integrations import GmailIntegrationService


class FakeRepository:
    def __init__(self):
        self.credential = None
        self.state_hash = None

    def get_credential(self, provider):
        return self.credential

    def create_oauth_state(self, provider, *, state_hash, ttl_minutes=10):
        self.state_hash = state_hash

    def consume_oauth_state(self, provider, *, state_hash):
        return state_hash == self.state_hash

    def upsert_credential(self, provider, **kwargs):
        self.credential = {
            "provider": provider,
            **kwargs,
        }
        return self.credential

    def delete_credential(self, provider):
        existed = self.credential is not None
        self.credential = None
        return existed


def make_settings() -> Settings:
    key = base64.urlsafe_b64encode(b"k" * 32).decode("ascii")
    return Settings(
        DATABASE_URL="postgresql://example",
        AUTH_USERNAME="mike",
        AUTH_PASSWORD_HASH="pbkdf2_sha256$310000$salt$digest",
        AUTH_SESSION_SECRET="s" * 32,
        PUBLIC_APP_URL="https://lead-desk-alpha.vercel.app",
        INTEGRATION_ENCRYPTION_KEY=key,
        GMAIL_CLIENT_ID="client-id",
        GMAIL_CLIENT_SECRET="client-secret",
        GMAIL_SENDER_EMAIL="mike@lilosgrowth.com",
    )


def test_credential_cipher_round_trip_and_aad_binding():
    key = base64.urlsafe_b64encode(b"k" * 32).decode("ascii")
    cipher = CredentialCipher(key)
    encrypted = cipher.encrypt("refresh-token", aad="gmail")

    assert b"refresh-token" not in encrypted
    assert cipher.decrypt(encrypted, aad="gmail") == "refresh-token"

    try:
        cipher.decrypt(encrypted, aad="other-provider")
    except Exception:
        pass
    else:
        raise AssertionError("AES-GCM associated data must bind ciphertext to provider")


def test_gmail_authorization_url_uses_https_callback_and_required_scope():
    repo = FakeRepository()
    service = GmailIntegrationService(repo, make_settings())

    url = service.authorization_url()

    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "gmail.compose" in url
    assert "access_type=offline" in url
    assert "state=" in url
    assert repo.state_hash is not None
    assert service.redirect_uri == (
        "https://lead-desk-alpha.vercel.app/api/integrations/gmail/callback"
    )


def test_gmail_status_never_exposes_encrypted_token():
    repo = FakeRepository()
    repo.credential = {
        "provider": "gmail",
        "account_email": "mike@lilosgrowth.com",
        "refresh_token_ciphertext": b"secret-ciphertext",
        "scopes": ["https://www.googleapis.com/auth/gmail.compose"],
    }
    service = GmailIntegrationService(repo, make_settings())

    status = service.status()

    assert status["connected"] is True
    assert status["account_email"] == "mike@lilosgrowth.com"
    assert "refresh_token" not in status
    assert "ciphertext" not in status
    assert status["send_enabled"] is False


class _Resp:
    def __init__(self, payload, ok=True, status=200):
        self._payload, self.ok, self.status_code, self.text = payload, ok, status, ""

    def json(self):
        return self._payload


def _authorize(monkeypatch, granted_scope):
    import pytest
    from app.services import integrations as I

    repo = FakeRepository()
    service = GmailIntegrationService(repo, make_settings())
    service.authorization_url()
    monkeypatch.setattr(I.secrets, "token_urlsafe", lambda n=32: "state", raising=False)
    monkeypatch.setattr(I.requests, "post", lambda *a, **k: _Resp(
        {"refresh_token": "r", "access_token": "a", "scope": granted_scope}))
    monkeypatch.setattr(I.requests, "get", lambda *a, **k: _Resp({"email": "mike@lilosgrowth.com"}))
    monkeypatch.setattr(repo, "consume_oauth_state", lambda provider, state_hash: True)
    return repo, service


def test_connect_refuses_a_grant_without_the_gmail_permission(monkeypatch):
    import pytest
    from app.services.integrations import MissingGmailPermission

    repo, service = _authorize(monkeypatch, "openid https://www.googleapis.com/auth/userinfo.email")
    with pytest.raises(MissingGmailPermission):
        service.complete_authorization(code="c", state="state")
    assert repo.credential is None


def test_connect_accepts_a_grant_with_the_gmail_permission(monkeypatch):
    repo, service = _authorize(
        monkeypatch,
        "openid https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/gmail.compose",
    )
    service.complete_authorization(code="c", state="state")
    assert repo.credential is not None
