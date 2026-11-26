"""Private, durable local submission snapshots and verdict history."""

import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


class LocalSubmissionStore:
    """SQLite adapter. Snapshot contents are never included in history responses."""

    def __init__(self, database: Path) -> None:
        database.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.database = database
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS submissions (
                    submission_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL UNIQUE,
                    user_id TEXT NOT NULL,
                    problem_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    files_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    verdict TEXT,
                    summary_json TEXT,
                    error_code TEXT
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS submissions_by_user "
                "ON submissions(user_id, problem_id, created_at DESC)"
            )
            # No worker survives a local API restart. Preserve the snapshot and explain the failure.
            connection.execute(
                "UPDATE submissions SET status = 'FAILED', error_code = 'local_restart' "
                "WHERE status IN ('QUEUED', 'RUNNING')"
            )
        os.chmod(database, 0o600)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def create(
        self, submission_id: str, job_id: str, user_id: str, problem_id: str, files: dict[str, str]
    ) -> None:
        created_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT INTO submissions "
                "(submission_id, job_id, user_id, problem_id, created_at, files_json, status) "
                "VALUES (?, ?, ?, ?, ?, ?, 'QUEUED')",
                (
                    submission_id,
                    job_id,
                    user_id,
                    problem_id,
                    created_at,
                    json.dumps(files, sort_keys=True),
                ),
            )

    def start(self, job_id: str) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "UPDATE submissions SET status = 'RUNNING' "
                "WHERE job_id = ? AND status = 'QUEUED'",
                (job_id,),
            )

    def finish(self, job_id: str, result: dict) -> None:
        summary = result.get("summary")
        error = result.get("error")
        error_code = error.get("code") if isinstance(error, dict) else None
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "UPDATE submissions SET status = ?, verdict = ?, "
                "summary_json = ?, error_code = ? "
                "WHERE job_id = ? AND status IN ('QUEUED', 'RUNNING')",
                (
                    result["status"],
                    result.get("verdict"),
                    json.dumps(summary) if summary is not None else None,
                    error_code,
                    job_id,
                ),
            )

    def list_for_user(self, user_id: str, problem_id: str) -> list[dict]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT submission_id, job_id, created_at, status, verdict, "
                "summary_json, error_code "
                "FROM submissions WHERE user_id = ? AND problem_id = ? "
                "ORDER BY created_at DESC, submission_id DESC",
                (user_id, problem_id),
            ).fetchall()
        history = []
        for row in rows:
            item = {
                "submissionId": row["submission_id"],
                "jobId": row["job_id"],
                "createdAt": row["created_at"],
                "status": row["status"],
                "verdict": row["verdict"],
            }
            if row["summary_json"] is not None:
                item["summary"] = json.loads(row["summary_json"])
            if row["error_code"] is not None:
                item["error"] = {"code": row["error_code"]}
            history.append(item)
        return history

    def snapshot(self, submission_id: str) -> dict[str, str] | None:
        """Internal storage access for retries and tests; never exposed by the HTTP API."""
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT files_json FROM submissions WHERE submission_id = ?", (submission_id,)
            ).fetchone()
        return json.loads(row["files_json"]) if row else None
