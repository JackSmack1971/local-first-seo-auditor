from __future__ import annotations

import os
from typing import Any

from fastapi.testclient import TestClient

from app.config import SECURITY_CONFIG
from app.security import SignatureContext, compute_signature


def perform_handshake(client: TestClient) -> dict[str, Any]:
    """Return the nonce payload for a new signed session."""

    response = client.post("/auth/handshake")
    assert response.status_code == 200
    return response.json()


def signed_headers(path: str, body: bytes, nonce: str) -> dict[str, str]:
    """Generate X-Nonce and X-Signature headers for authenticated requests."""

    secret = bytes.fromhex(os.environ[SECURITY_CONFIG.hmac_secret_env_var])
    signature = compute_signature(
        secret=secret,
        context=SignatureContext(nonce=nonce, path=path, body=body),
    )
    return {"X-Nonce": nonce, "X-Signature": signature}
