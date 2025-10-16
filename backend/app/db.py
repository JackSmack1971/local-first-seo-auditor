"""Database utilities for interacting with the application's SQLite store."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .config import resolve_sqlite_path


def _ensure_parent_directory(path: Path) -> None:
    """Create the directory structure for the SQLite database if missing."""

    path.parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def sqlite_connection() -> Iterator[sqlite3.Connection]:
    """Provide a configured SQLite connection as a context manager."""

    path = resolve_sqlite_path()
    _ensure_parent_directory(path)
    connection = sqlite3.connect(
        path,
        detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        check_same_thread=False,
    )
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
