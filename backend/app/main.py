"""Entry point for the FastAPI application."""

from __future__ import annotations

from fastapi import FastAPI

from .routes import health
from .routes import auth
from .routes import projects


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    app = FastAPI(
        title="Local-First SEO Auditor Backend",
        version="0.1.0",
        description=(
            "Backend API for the local-first SEO auditor. All endpoints require HMAC "
            "request signing with rotating nonces."
        ),
    )
    app.include_router(auth.router)
    app.include_router(health.router)
    app.include_router(projects.router)
    return app


app = create_app()
