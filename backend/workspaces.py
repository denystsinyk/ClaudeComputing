"""Durable local workspaces, keyed by verified user and problem."""

import json
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


MAX_REVISION = 2**63 - 2


class WorkspaceConflict(Exception):
    """The client saved against an out-of-date revision."""


@dataclass(frozen=True)
class Workspace:
    files: dict[str, str]
    revision: int
    updated_at: str | None

    def response(self) -> dict:
        return {
            "files": self.files.copy(),
            "revision": self.revision,
            "updatedAt": self.updated_at,
        }


class LocalWorkspaceStore:
    """SQLite adapter. One row per user and problem, updated with compare-and-swap."""

    def __init__(self, database: Path) -> None:
        database.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.database = database
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS workspaces (
                    user_id TEXT NOT NULL,
                    problem_id TEXT NOT NULL,
                    files_json TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, problem_id)
                )
                """
            )
        os.chmod(database, 0o600)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def get(self, user_id: str, problem_id: str) -> Workspace | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT files_json, revision, updated_at FROM workspaces "
                "WHERE user_id = ? AND problem_id = ?",
                (user_id, problem_id),
            ).fetchone()
        if row is None:
            return None
        return Workspace(json.loads(row["files_json"]), row["revision"], row["updated_at"])

    def save(
        self, user_id: str, problem_id: str, files: dict[str, str], expected_revision: int
    ) -> Workspace:
        if not 0 <= expected_revision <= MAX_REVISION:
            raise ValueError("invalid revision")
        updated_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        serialized = json.dumps(files, sort_keys=True)
        with closing(self._connect()) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT revision FROM workspaces WHERE user_id = ? AND problem_id = ?",
                    (user_id, problem_id),
                ).fetchone()
                current_revision = row["revision"] if row else 0
                if current_revision != expected_revision:
                    raise WorkspaceConflict
                new_revision = current_revision + 1
                if row is None:
                    connection.execute(
                        "INSERT INTO workspaces "
                        "(user_id, problem_id, files_json, revision, updated_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (user_id, problem_id, serialized, new_revision, updated_at),
                    )
                else:
                    connection.execute(
                        "UPDATE workspaces SET files_json = ?, revision = ?, updated_at = ? "
                        "WHERE user_id = ? AND problem_id = ?",
                        (serialized, new_revision, updated_at, user_id, problem_id),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return Workspace(files.copy(), new_revision, updated_at)
