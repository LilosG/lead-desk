from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class CredentialCipher:
    def __init__(self, key_b64: str) -> None:
        try:
            key = base64.urlsafe_b64decode(key_b64.encode("ascii"))
        except Exception as exc:  # pragma: no cover - defensive validation
            raise ValueError("INTEGRATION_ENCRYPTION_KEY must be urlsafe base64") from exc
        if len(key) != 32:
            raise ValueError("INTEGRATION_ENCRYPTION_KEY must decode to exactly 32 bytes")
        self._cipher = AESGCM(key)

    def encrypt(self, plaintext: str, *, aad: str) -> bytes:
        nonce = os.urandom(12)
        ciphertext = self._cipher.encrypt(
            nonce,
            plaintext.encode("utf-8"),
            aad.encode("utf-8"),
        )
        return nonce + ciphertext

    def decrypt(self, payload: bytes, *, aad: str) -> str:
        if len(payload) < 13:
            raise ValueError("encrypted credential payload is invalid")
        nonce, ciphertext = payload[:12], payload[12:]
        plaintext = self._cipher.decrypt(
            nonce,
            ciphertext,
            aad.encode("utf-8"),
        )
        return plaintext.decode("utf-8")
