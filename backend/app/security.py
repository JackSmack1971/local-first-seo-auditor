"""Security utilities for request signing and nonce management.

The PRD/FRD mandate HMAC-based request signing with per-session nonces stored in
an OS keyring. This module provides reusable helpers that the API layer can use
for validating incoming requests.
"""

from __future__ import annotations

import hmac
import time
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol

from fastapi import HTTPException, status

from .config import SECURITY_CONFIG, load_hmac_secret


class NonceStore(Protocol):
    """Protocol describing how nonce replay protection is implemented."""

    def register(self, nonce: str, *, ttl_seconds: int) -> None:
        """Register a nonce and raise if it has already been used."""


class InMemoryNonceStore:
    """Simple nonce store suitable for local development and tests.

    Production deployments must replace this with a process-safe store backed by
    SQLite (§2.2 FRD). The store keeps timestamps to expire entries and prevent
    unbounded growth.
    """

    def __init__(self) -> None:
        self._seen: dict[str, float] = {}

    def register(self, nonce: str, *, ttl_seconds: int) -> None:  # pragma: no cover - trivial
        now = time.time()
        expired = [value for value, timestamp in self._seen.items() if now - timestamp > ttl_seconds]
        for value in expired:
            del self._seen[value]
        if nonce in self._seen:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Nonce already used. Reauthenticate to obtain a new session nonce.",
            )
        self._seen[nonce] = now

    def active_count(self, *, ttl_seconds: int) -> int:
        """Return the number of valid nonces currently cached."""

        now = time.time()
        for value, timestamp in list(self._seen.items()):
            if now - timestamp > ttl_seconds:
                del self._seen[value]
        return len(self._seen)


@dataclass
class SignatureContext:
    """Represents the canonical fields required for HMAC verification."""

    nonce: str
    path: str
    body: bytes


def compute_signature(*, secret: bytes, context: SignatureContext) -> str:
    """Compute a hexadecimal HMAC signature for the provided context."""

    signer = hmac.new(secret, digestmod=sha256)
    signer.update(context.nonce.encode("utf-8"))
    signer.update(context.path.encode("utf-8"))
    signer.update(context.body)
    return signer.hexdigest()


def verify_request_signature(
    *,
    context: SignatureContext,
    provided_signature: str,
    nonce_store: NonceStore,
    secret: bytes | None = None,
) -> None:
    """Verify the request signature and enforce nonce replay protection.

    Raises :class:`fastapi.HTTPException` when validation fails. All responses
    use generic error messages to avoid leaking implementation details.
    """

    if not context.nonce:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing X-Nonce header.",
        )
    if not provided_signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing X-Signature header.",
        )

    signing_secret = secret or load_hmac_secret()
    expected_signature = compute_signature(secret=signing_secret, context=context)
    if not hmac.compare_digest(expected_signature, provided_signature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid request signature.",
        )

    nonce_store.register(context.nonce, ttl_seconds=SECURITY_CONFIG.nonce_ttl_seconds)
