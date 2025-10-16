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


def _handshake(client: TestClient) -> dict[str, str | int]:
    response = client.post("/auth/handshake")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data["nonce"], str) and len(data["nonce"]) == 64
    return data


def _signed_headers(path: str, body: bytes, nonce: str) -> dict[str, str]:
    secret = bytes.fromhex(os.environ[SECURITY_CONFIG.hmac_secret_env_var])
    signature = compute_signature(
        secret=secret,
        context=SignatureContext(nonce=nonce, path=path, body=body),
    )
    return {"X-Nonce": nonce, "X-Signature": signature}


def test_handshake_requires_configured_secret(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(SECURITY_CONFIG.hmac_secret_env_var)
    response = client.post("/auth/handshake")
    assert response.status_code == 500
    assert response.json()["detail"] == "HMAC signing secret not configured."


def test_health_check_requires_signature(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 400
    assert response.json()["detail"] == "Missing X-Nonce header."


def test_handshake_returns_nonce_metadata(client: TestClient) -> None:
    data = _handshake(client)
    assert data["nonce_ttl_seconds"] == SECURITY_CONFIG.nonce_ttl_seconds
    assert data["key_id"] == SECURITY_CONFIG.hmac_secret_env_var
    assert "issued_at" in data and "expires_at" in data


def test_health_check_accepts_valid_signature(client: TestClient) -> None:
    payload = b""
    handshake = _handshake(client)
    headers = _signed_headers("/health", payload, handshake["nonce"])
    response = client.get("/health", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_rejects_replayed_nonce(client: TestClient) -> None:
    payload = b""
    handshake = _handshake(client)
    headers = _signed_headers("/health", payload, handshake["nonce"])
    first_response = client.get("/health", headers=headers)
    assert first_response.status_code == 200

    second_response = client.get("/health", headers=headers)
    assert second_response.status_code == 409
    assert second_response.json()["detail"].startswith("Nonce already used")
