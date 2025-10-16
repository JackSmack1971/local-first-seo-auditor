"""Pydantic models used by the backend API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Response payload for service health checks."""

    status: str = Field(..., description="Human-readable service status message.")
    nonce_cache_entries: int = Field(
        ..., description="Number of active nonce entries retained for replay protection."
    )
