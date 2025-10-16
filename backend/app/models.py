"""Pydantic models used by the backend API."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, HttpUrl, StringConstraints, field_validator, model_validator


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


NameStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class SitemapTarget(BaseModel):
    """Project target that references a sitemap URL."""

    type: Literal["sitemap"]
    sitemap_url: HttpUrl


class SeedListTarget(BaseModel):
    """Project target comprising a curated list of seed URLs."""

    type: Literal["seeds"]
    seed_urls: list[HttpUrl] = Field(
        ..., description="List of seed URLs to begin crawling from.", min_length=1, max_length=50
    )

    @model_validator(mode="after")
    def ensure_unique_urls(self) -> "SeedListTarget":
        """Enforce uniqueness of seed URLs to avoid redundant crawl work."""

        normalised = [str(url).rstrip("/") for url in self.seed_urls]
        if len(set(normalised)) != len(normalised):
            raise ValueError("Seed URLs must be unique.")
        return self


ProjectTarget = Annotated[SitemapTarget | SeedListTarget, Field(discriminator="type")]


class ProjectCreateRequest(BaseModel):
    """Payload for creating a new SEO project."""

    name: NameStr = Field(..., description="Human-readable project identifier.")
    target: ProjectTarget

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not value:
            raise ValueError("Project name cannot be empty.")
        return value


class ProjectResponse(BaseModel):
    """Project record returned by the backend API."""

    id: str
    name: str
    target: ProjectTarget
    created_at: datetime
    updated_at: datetime
    last_run_status: str = Field(
        ..., description="Current lifecycle status for the most recent run (e.g. SUCCEEDED)."
    )
    last_run_at: datetime | None = Field(
        None, description="Timestamp of the most recent run if the project has ever executed."
    )
    disk_usage_bytes: int = Field(
        ..., description="Approximate on-disk footprint for all project artefacts.", ge=0
    )
