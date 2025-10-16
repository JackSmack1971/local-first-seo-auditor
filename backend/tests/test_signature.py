from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import SECURITY_CONFIG

from .helpers import perform_handshake, signed_headers


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
    data = perform_handshake(client)
    assert data["nonce_ttl_seconds"] == SECURITY_CONFIG.nonce_ttl_seconds
    assert data["key_id"] == SECURITY_CONFIG.hmac_secret_env_var
    assert "issued_at" in data and "expires_at" in data


def test_health_check_accepts_valid_signature(client: TestClient) -> None:
    payload = b""
    handshake = perform_handshake(client)
    assert isinstance(handshake["nonce"], str) and len(handshake["nonce"]) == 64
    headers = signed_headers("/health", payload, handshake["nonce"])
    response = client.get("/health", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_rejects_replayed_nonce(client: TestClient) -> None:
    payload = b""
    handshake = perform_handshake(client)
    headers = signed_headers("/health", payload, handshake["nonce"])
    first_response = client.get("/health", headers=headers)
    assert first_response.status_code == 200

    second_response = client.get("/health", headers=headers)
    assert second_response.status_code == 409
    assert second_response.json()["detail"].startswith("Nonce already used")
