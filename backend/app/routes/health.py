"""Health check endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..config import SECURITY_CONFIG
from ..dependencies import enforce_signed_request, get_nonce_store
from ..models import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Service health check")
async def health_check(_: None = Depends(enforce_signed_request)) -> HealthResponse:
    """Return a signed health status response.

    The dependency enforces request signing even for health checks because the
    backend is bound to localhost and we want to avoid information leakage to
    unauthenticated processes.
    """

    nonce_store = get_nonce_store()
    entries = nonce_store.active_count(ttl_seconds=SECURITY_CONFIG.nonce_ttl_seconds)
    return HealthResponse(status="ok", nonce_cache_entries=entries)
