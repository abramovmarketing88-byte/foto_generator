from __future__ import annotations

import base64
import hashlib
import os

_SECRET_ENV = "KEY_ENCRYPTION_SECRET"


def _secret_bytes() -> bytes:
    secret = os.getenv(_SECRET_ENV, "dev-insecure-key-change-me")
    return hashlib.sha256(secret.encode("utf-8")).digest()


def _xor_bytes(payload: bytes, key: bytes) -> bytes:
    return bytes(value ^ key[idx % len(key)] for idx, value in enumerate(payload))


def encrypt_secret(value: str) -> str:
    raw = value.encode("utf-8")
    encrypted = _xor_bytes(raw, _secret_bytes())
    return base64.urlsafe_b64encode(encrypted).decode("ascii")


def decrypt_secret(value: str) -> str:
    encrypted = base64.urlsafe_b64decode(value.encode("ascii"))
    decrypted = _xor_bytes(encrypted, _secret_bytes())
    return decrypted.decode("utf-8")
