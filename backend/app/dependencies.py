"""Reusable FastAPI dependency providers."""

from __future__ import annotations

from typing import Annotated

from fastapi import Header, HTTPException, Request, status

from .security import InMemoryNonceStore, SignatureContext, verify_request_signature


_nonce_store = InMemoryNonceStore()


async def enforce_signed_request(
    request: Request,
    x_nonce: Annotated[str | None, Header(alias="X-Nonce")] = None,
    x_signature: Annotated[str | None, Header(alias="X-Signature")] = None,
) -> None:
    """Validate request signatures for authenticated endpoints."""

    body = await request.body()
    context = SignatureContext(
        nonce=x_nonce or "",
        path=request.url.path,
        body=body,
    )
    verify_request_signature(
        context=context,
        provided_signature=x_signature or "",
        nonce_store=_nonce_store,
    )


def get_nonce_store() -> InMemoryNonceStore:
    """Expose the nonce store for other components (e.g., tests)."""

    return _nonce_store


async def enforce_pin_verification(
    x_pin_verified: Annotated[str | None, Header(alias="X-PIN-Verified")] = None,
) -> None:
    """Ensure the caller has completed a PIN challenge for sensitive operations."""

    if x_pin_verified is None or x_pin_verified.lower() != "true":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="PIN verification required for this action.",
        )
