"""Reusable FastAPI dependency providers."""

from __future__ import annotations

from typing import Annotated

from fastapi import Header, Request

from .security import InMemoryNonceStore, SignatureContext, verify_request_signature


_nonce_store = InMemoryNonceStore()


async def enforce_signed_request(
    request: Request,
    x_nonce: Annotated[str | None, Header(alias="X-Nonce")],
    x_signature: Annotated[str | None, Header(alias="X-Signature")],
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
