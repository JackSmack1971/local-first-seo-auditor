from __future__ import annotations

import os
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from app.config import SECURITY_CONFIG
from app.main import create_app
from app.security import SignatureContext, compute_signature


@pytest.fixture(autouse=True)
def set_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(SECURITY_CONFIG.hmac_secret_env_var, "a" * 64)


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def _signed_headers(path: str, body: bytes) -> dict[str, str]:
    nonce = "123e4567-e89b-12d3-a456-426614174000"
    secret = bytes.fromhex(os.environ[SECURITY_CONFIG.hmac_secret_env_var])
    signature = compute_signature(
        secret=secret,
        context=SignatureContext(nonce=nonce, path=path, body=body),
    )
    return {"X-Nonce": nonce, "X-Signature": signature}


def test_health_check_requires_signature(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 400
    assert response.json()["detail"] == "Missing X-Nonce header."


def test_health_check_accepts_valid_signature(client: TestClient) -> None:
    payload = b""
    headers = _signed_headers("/health", payload)
    response = client.get("/health", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_rejects_replayed_nonce(client: TestClient) -> None:
    payload = b""
    headers = _signed_headers("/health", payload)
    first_response = client.get("/health", headers=headers)
    assert first_response.status_code == 200

    second_response = client.get("/health", headers=headers)
    assert second_response.status_code == 409
    assert second_response.json()["detail"].startswith("Nonce already used")
