from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from .helpers import perform_handshake, signed_headers


def _post_project(client: TestClient, payload: dict[str, object]) -> dict[str, object]:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    handshake = perform_handshake(client)
    headers = signed_headers("/projects", body, handshake["nonce"])
    headers["Content-Type"] = "application/json"
    response = client.post("/projects", content=body, headers=headers)
    assert response.status_code == 201
    return response.json()


def test_create_project_requires_signature(client: TestClient) -> None:
    payload = {
        "name": "Example Project",
        "target": {"type": "sitemap", "sitemap_url": "https://example.com/sitemap.xml"},
    }
    response = client.post("/projects", json=payload)
    assert response.status_code == 400
    assert response.json()["detail"] == "Missing X-Nonce header."


def test_create_project_with_sitemap_target(client: TestClient) -> None:
    payload = {
        "name": "Example Project",
        "target": {"type": "sitemap", "sitemap_url": "https://example.com/sitemap.xml"},
    }
    record = _post_project(client, payload)
    assert record["name"] == "Example Project"
    assert record["target"] == payload["target"]
    assert record["last_run_status"] == "NEVER_RUN"
    assert record["disk_usage_bytes"] == 0


def test_create_project_with_seed_targets(client: TestClient) -> None:
    payload = {
        "name": "Seed Project",
        "target": {
            "type": "seeds",
            "seed_urls": [
                "https://example.com/about",
                "https://example.com/contact",
            ],
        },
    }
    record = _post_project(client, payload)
    assert record["target"]["type"] == "seeds"
    assert sorted(record["target"]["seed_urls"]) == sorted(payload["target"]["seed_urls"])


def test_reject_duplicate_project_names(client: TestClient) -> None:
    payload = {
        "name": "Duplicate Project",
        "target": {"type": "sitemap", "sitemap_url": "https://example.com/sitemap.xml"},
    }
    _post_project(client, payload)
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    handshake = perform_handshake(client)
    headers = signed_headers("/projects", body, handshake["nonce"])
    headers["Content-Type"] = "application/json"
    response = client.post("/projects", content=body, headers=headers)
    assert response.status_code == 409
    assert response.json()["detail"] == "A project with this name already exists."


def test_list_projects_returns_sorted_results(client: TestClient) -> None:
    first = {
        "name": "Beta",
        "target": {"type": "sitemap", "sitemap_url": "https://example.com/sitemap.xml"},
    }
    second = {
        "name": "Alpha",
        "target": {"type": "sitemap", "sitemap_url": "https://example.org/sitemap.xml"},
    }
    _post_project(client, first)
    _post_project(client, second)

    handshake = perform_handshake(client)
    headers = signed_headers("/projects", b"", handshake["nonce"])
    response = client.get("/projects", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert [item["name"] for item in data] == ["Alpha", "Beta"]
    assert all("created_at" in item for item in data)


@pytest.mark.parametrize(
    "seed_urls",
    [
        ["https://example.com/a", "https://example.com/a/"],
    ],
)
def test_seed_urls_must_be_unique(client: TestClient, seed_urls: list[str]) -> None:
    payload = {
        "name": "Duplicate Seeds",
        "target": {"type": "seeds", "seed_urls": seed_urls},
    }
    handshake = perform_handshake(client)
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    headers = signed_headers("/projects", body, handshake["nonce"])
    headers["Content-Type"] = "application/json"
    response = client.post("/projects", content=body, headers=headers)
    assert response.status_code == 422
