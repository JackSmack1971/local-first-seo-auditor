from __future__ import annotations

from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from app.config import SECURITY_CONFIG
from app.main import create_app


@pytest.fixture(autouse=True)
def set_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure the HMAC secret is configured for every test case."""

    monkeypatch.setenv(SECURITY_CONFIG.hmac_secret_env_var, "a" * 64)


@pytest.fixture()
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the application at an isolated SQLite file for each test."""

    path = tmp_path / "app.db"
    monkeypatch.setenv("SEO_AUDITOR_DB_PATH", str(path))
    return path


@pytest.fixture()
def client(db_path: Path) -> Generator[TestClient, None, None]:
    """Provide a FastAPI test client bound to an isolated database."""

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
