"""SQLite-backed repository for managing SEO projects."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable
from uuid import uuid4

from fastapi import HTTPException, status

from ..db import sqlite_connection
from ..models import (
    ProjectCreateRequest,
    ProjectResponse,
    ProjectTarget,
    SeedListTarget,
    SitemapTarget,
)


@dataclass(frozen=True)
class _ProjectRow:
    """Internal representation of a project row fetched from SQLite."""

    id: str
    name: str
    target_type: str
    target_payload: str
    created_at: str
    updated_at: str
    last_run_status: str
    last_run_at: str | None
    disk_usage_bytes: int


class ProjectsRepository:
    """Encapsulates CRUD operations for project metadata."""

    def create_project(self, payload: ProjectCreateRequest) -> ProjectResponse:
        now = datetime.now(timezone.utc).isoformat()
        project_id = str(uuid4())
        target_type, target_payload = self._serialise_target(payload.target)

        with sqlite_connection() as connection:
            self._ensure_schema(connection)
            try:
                connection.execute(
                    """
                    INSERT INTO projects (
                        id,
                        name,
                        target_type,
                        target_payload,
                        created_at,
                        updated_at,
                        last_run_status,
                        last_run_at,
                        disk_usage_bytes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        payload.name,
                        target_type,
                        target_payload,
                        now,
                        now,
                        "NEVER_RUN",
                        None,
                        0,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                if "UNIQUE constraint failed: projects.name" in str(exc):
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="A project with this name already exists.",
                    ) from exc
                raise

            row = connection.execute(
                """
                SELECT id, name, target_type, target_payload, created_at, updated_at,
                       last_run_status, last_run_at, disk_usage_bytes
                FROM projects
                WHERE id = ?
                """,
                (project_id,),
            ).fetchone()

        if row is None:  # pragma: no cover - defensive guard
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Project creation failed.")

        return self._row_to_response(_ProjectRow(**dict(row)))

    def list_projects(self) -> list[ProjectResponse]:
        with sqlite_connection() as connection:
            self._ensure_schema(connection)
            rows = connection.execute(
                """
                SELECT id, name, target_type, target_payload, created_at, updated_at,
                       last_run_status, last_run_at, disk_usage_bytes
                FROM projects
                ORDER BY lower(name)
                """,
            ).fetchall()

        return [self._row_to_response(_ProjectRow(**dict(row))) for row in rows]

    def get_project(self, project_id: str) -> ProjectResponse:
        with sqlite_connection() as connection:
            self._ensure_schema(connection)
            row = connection.execute(
                """
                SELECT id, name, target_type, target_payload, created_at, updated_at,
                       last_run_status, last_run_at, disk_usage_bytes
                FROM projects
                WHERE id = ?
                """,
                (project_id,),
            ).fetchone()

        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

        return self._row_to_response(_ProjectRow(**dict(row)))

    def delete_project(self, project_id: str) -> None:
        with sqlite_connection() as connection:
            self._ensure_schema(connection)
            self._purge_project_artifacts(connection, project_id)
            cursor = connection.execute(
                "DELETE FROM projects WHERE id = ?",
                (project_id,),
            )
            deleted = cursor.rowcount

        if deleted == 0:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")

    def _ensure_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                target_type TEXT NOT NULL CHECK(target_type IN ('sitemap', 'seeds')),
                target_payload TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_run_status TEXT NOT NULL,
                last_run_at TEXT,
                disk_usage_bytes INTEGER NOT NULL DEFAULT 0
            )
            """
        )

    def _serialise_target(self, target: ProjectTarget) -> tuple[str, str]:
        if isinstance(target, SitemapTarget):
            payload = json.dumps({"sitemap_url": str(target.sitemap_url)})
            return target.type, payload

        if isinstance(target, SeedListTarget):
            payload = json.dumps({"seed_urls": [str(url) for url in target.seed_urls]})
            return target.type, payload

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported project target type.")

    def _row_to_response(self, row: _ProjectRow) -> ProjectResponse:
        target = self._deserialise_target(row.target_type, row.target_payload)
        return ProjectResponse(
            id=row.id,
            name=row.name,
            target=target,
            created_at=datetime.fromisoformat(row.created_at),
            updated_at=datetime.fromisoformat(row.updated_at),
            last_run_status=row.last_run_status,
            last_run_at=datetime.fromisoformat(row.last_run_at) if row.last_run_at else None,
            disk_usage_bytes=row.disk_usage_bytes,
        )

    def _deserialise_target(self, target_type: str, payload: str) -> ProjectTarget:
        data = json.loads(payload)
        if target_type == "sitemap":
            return SitemapTarget(type="sitemap", sitemap_url=data["sitemap_url"])
        if target_type == "seeds":
            return SeedListTarget(type="seeds", seed_urls=data["seed_urls"])
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Stored project target invalid.")

    def _existing_tables(self, connection: sqlite3.Connection) -> set[str]:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'",
        ).fetchall()
        return {row[0] for row in rows}

    def _purge_project_artifacts(self, connection: sqlite3.Connection, project_id: str) -> None:
        """Remove project-linked artefacts from auxiliary tables when available."""

        cleanup_statements = {
            "audit_run": "DELETE FROM audit_run WHERE project_id = ?",
            "audit_metric": "DELETE FROM audit_metric WHERE project_id = ?",
            "topic_term": "DELETE FROM topic_term WHERE project_id = ?",
            "link_edge": "DELETE FROM link_edge WHERE project_id = ?",
            "host_rank": "DELETE FROM host_rank WHERE project_id = ?",
            "jobs": "DELETE FROM jobs WHERE payload_json LIKE ?",
        }
        existing_tables = self._existing_tables(connection)
        for table_name, statement in cleanup_statements.items():
            if table_name not in existing_tables:
                continue
            if table_name == "jobs":
                connection.execute(statement, (f'%"project_id": "{project_id}"%',))
            else:
                connection.execute(statement, (project_id,))


def iter_projects(repository: ProjectsRepository) -> Iterable[ProjectResponse]:
    """Convenience generator for enumerating stored projects."""

    yield from repository.list_projects()
