"""Passwords, tokens and envelope encryption for integration credentials."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
import uuid
from typing import Any

import jwt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from cairn.config import get_settings

# ---------------------------------------------------------------- passwords

_SCRYPT = dict(n=2**14, r=8, p=1, dklen=32)


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_b64, dk_b64 = stored.split("$")
    except ValueError:
        return False
    dk = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64), **_SCRYPT)
    return hmac.compare_digest(dk, base64.b64decode(dk_b64))


# ------------------------------------------------------------------ tokens

def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def random_token(prefix: str, nbytes: int = 24) -> str:
    return f"{prefix}_{secrets.token_urlsafe(nbytes)}"


def issue_session(user_id: uuid.UUID, tenant_id: uuid.UUID, role: str, email: str = "") -> str:
    s = get_settings()
    now = int(time.time())
    payload = {
        "sub": str(user_id), "tid": str(tenant_id), "role": role, "email": email,
        "iat": now, "exp": now + s.session_ttl_hours * 3600,
    }
    return jwt.encode(payload, s.session_secret, algorithm="HS256")


def read_session(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, get_settings().session_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def identity_signature(secret: str, customer_ref: str) -> str:
    """HMAC a business computes server-side to vouch for a signed-in customer."""
    return hmac.new(secret.encode(), customer_ref.encode(), hashlib.sha256).hexdigest()


def verify_identity_signature(secret: str, customer_ref: str, signature: str) -> bool:
    return hmac.compare_digest(identity_signature(secret, customer_ref), signature or "")


# ----------------------------------------------------- envelope encryption

def _master() -> AESGCM:
    key = base64.b64decode(get_settings().encryption_master_key)
    if len(key) != 32:
        raise ValueError("CAIRN_MASTER_KEY must decode to 32 bytes")
    return AESGCM(key)


def seal(plaintext: bytes, tenant_id: uuid.UUID | str) -> tuple[bytes, bytes]:
    """Encrypt with a fresh data key; return (ciphertext, wrapped data key).

    The data key is wrapped by the master key with the tenant id as
    associated data, so a ciphertext cannot be unwrapped under another tenant.
    In production the master key lives in the cloud secrets manager (KMS).
    """
    dek = AESGCM.generate_key(bit_length=256)
    n1, n2 = os.urandom(12), os.urandom(12)
    ct = n1 + AESGCM(dek).encrypt(n1, plaintext, None)
    wrapped = n2 + _master().encrypt(n2, dek, str(tenant_id).encode())
    return ct, wrapped


def unseal(ciphertext: bytes, wrapped: bytes, tenant_id: uuid.UUID | str) -> bytes:
    dek = _master().decrypt(wrapped[:12], wrapped[12:], str(tenant_id).encode())
    return AESGCM(dek).decrypt(ciphertext[:12], ciphertext[12:], None)
