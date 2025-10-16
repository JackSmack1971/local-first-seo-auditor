"""Pydantic models used by the backend API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Response payload for service health checks."""

    status: str = Field(..., description="Human-readable service status message.")
    nonce_cache_entries: int = Field(
        ..., description="Number of active nonce entries retained for replay protection."
    )


class HandshakeResponse(BaseModel):
    """Response payload for the request-signing handshake."""

    nonce: str = Field(..., description="Hex-encoded 32-byte nonce for signing the next request.")
    issued_at: datetime = Field(..., description="ISO timestamp indicating when the nonce was issued.")
    expires_at: datetime = Field(
        ..., description="Timestamp after which the client must request a new nonce.",
    )
    nonce_ttl_seconds: int = Field(
        ..., description="Server-configured nonce validity window communicated to the client.",
    )
    key_id: str = Field(
        ..., description="Identifier that tells the client which keyring entry holds the HMAC secret.",
    )
