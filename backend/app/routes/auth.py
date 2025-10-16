"""Authentication and handshake endpoints for the backend API."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, status

from ..config import SECURITY_CONFIG, ConfigurationError, load_hmac_secret
from ..models import HandshakeResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/handshake",
    response_model=HandshakeResponse,
    summary="Obtain a nonce for request signing",
)
async def create_handshake() -> HandshakeResponse:
    """Issue a nonce so the client can sign subsequent requests securely.

    The backend verifies that an HMAC signing secret is configured before issuing
    a nonce. The nonce is random, 32 bytes long, and represented as a hex string
    to simplify transmission. The client must use the nonce immediately to sign
    its next request; once a request succeeds the nonce becomes invalid to guard
    against replay attacks.
    """

    try:
        # Validate the signing secret is present before we hand out a nonce.
        load_hmac_secret()
    except ConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="HMAC signing secret not configured.",
        ) from exc

    issued_at = datetime.now(timezone.utc)
    nonce = secrets.token_hex(32)  # 32 bytes -> 64 hex characters (per PRD requirements)
    expires_at = issued_at + timedelta(seconds=SECURITY_CONFIG.nonce_ttl_seconds)

    return HandshakeResponse(
        nonce=nonce,
        issued_at=issued_at,
        expires_at=expires_at,
        nonce_ttl_seconds=SECURITY_CONFIG.nonce_ttl_seconds,
        key_id=SECURITY_CONFIG.hmac_secret_env_var,
    )
