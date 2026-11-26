"""Transport-independent API behavior for the local prebuilt-problem flow."""

import hmac
import io
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from backend.jobs import ActiveJobError, DockerRunError, JobStore, failed_result
from backend.problem_packages import (
    MAX_SOURCE_BYTES,
    PROBLEM_ID,
    PackageError,
    ProblemPackage,
    list_problems,
    load_problem,
)


MAX_REQUEST_BYTES = 256_000


@dataclass(frozen=True)
class Response:
    status: int
    payload: dict


class ApiError(Exception):
    def __init__(self, status: int, code: str) -> None:
        self.status = status
        self.code = code
        super().__init__(code)


class TokenAuth:
    """Local test identity; the caller cannot provide its own user ID."""

    def __init__(self, tokens: dict[str, str]) -> None:
        self._tokens = tokens.copy()

    def user_id(self, authorization: str | None) -> str | None:
        if not authorization or not authorization.startswith("Bearer "):
            return None
        presented = authorization.removeprefix("Bearer ")
        for token, user_id in self._tokens.items():
            try:
                if hmac.compare_digest(presented, token):
                    return user_id
            except TypeError:
                return None
        return None


class Api:
    def __init__(
        self,
        examples_root: Path,
        auth: TokenAuth,
        jobs: JobStore,
        executor,
        scheduler,
    ) -> None:
        self.examples_root = examples_root
        self.auth = auth
        self.jobs = jobs
        self.executor = executor
        self.scheduler = scheduler

    def handle(
        self, method: str, path: str, authorization: str | None = None, body: bytes = b""
    ) -> Response:
        try:
            return self._handle(method, path, authorization, body)
        except ApiError as exc:
            return Response(exc.status, {"error": {"code": exc.code}})

    def _handle(self, method: str, path: str, authorization: str | None, body: bytes) -> Response:
        if method == "GET" and path == "/health":
            return Response(200, {"status": "ok"})

        user_id = self.auth.user_id(authorization)
        if user_id is None:
            raise ApiError(401, "unauthorized")

        if method == "GET" and path == "/problems":
            try:
                packages = list_problems(self.examples_root)
            except (OSError, PackageError) as exc:
                raise ApiError(500, "invalid_problem_package") from exc
            return Response(200, {"problems": [package.catalog_entry() for package in packages]})

        parts = path.strip("/").split("/")
        if method == "GET" and len(parts) == 2 and parts[0] == "problems":
            return Response(200, self._problem(parts[1]).public_detail())
        if method == "POST" and len(parts) == 3 and parts[0] == "problems" and parts[2] == "run":
            package = self._problem(parts[1])
            files = self._parse_files(body, package)
            job_id = uuid.uuid4().hex
            archive = self._make_job_zip(job_id, files, package)
            try:
                self.jobs.create(job_id, user_id, package.id)
            except ActiveJobError as exc:
                raise ApiError(409, "active_job_exists") from exc
            try:
                self.scheduler.submit(self._run_job, job_id, archive)
            except RuntimeError:
                self.jobs.start(job_id)
                self.jobs.finish(job_id, failed_result(job_id, "dispatch_unavailable"))
            return Response(202, {"jobId": job_id, "status": "QUEUED"})
        if method == "GET" and len(parts) == 2 and parts[0] == "jobs":
            job = self.jobs.get(parts[1])
            if not job or job["userId"] != user_id:
                raise ApiError(404, "not_found")
            payload = {
                "jobId": job["jobId"],
                "problemId": job["problemId"],
                "status": job["status"],
            }
            if job["result"] is not None:
                payload["result"] = job["result"]
            return Response(200, payload)
        raise ApiError(404, "not_found")

    def _problem(self, problem_id: str) -> ProblemPackage:
        if not PROBLEM_ID.fullmatch(problem_id) or not (self.examples_root / problem_id).is_dir():
            raise ApiError(404, "not_found")
        try:
            return load_problem(self.examples_root, problem_id)
        except PackageError as exc:
            raise ApiError(500, "invalid_problem_package") from exc

    @staticmethod
    def _parse_files(body: bytes, package: ProblemPackage) -> dict[str, str]:
        if len(body) > MAX_REQUEST_BYTES:
            raise ApiError(400, "request_too_large")
        try:
            request = json.loads(body)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ApiError(400, "invalid_json") from exc
        if not isinstance(request, dict) or set(request) != {"files"}:
            raise ApiError(400, "invalid_files")
        files = request["files"]
        if not isinstance(files, dict) or set(files) != set(package.starter_files):
            raise ApiError(400, "invalid_files")
        for contents in files.values():
            if not isinstance(contents, str) or "\0" in contents:
                raise ApiError(400, "invalid_files")
            try:
                size = len(contents.encode("utf-8"))
            except UnicodeError as exc:
                raise ApiError(400, "invalid_files") from exc
            if size > MAX_SOURCE_BYTES:
                raise ApiError(400, "invalid_files")
        return files

    @staticmethod
    def _make_job_zip(job_id: str, files: dict[str, str], package: ProblemPackage) -> bytes:
        metadata = {"schema_version": 1, "job_id": job_id, "mode": "run", "timeout_seconds": 10}
        buffer = io.BytesIO()
        with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
            archive.writestr("job.json", json.dumps(metadata))
            for path, contents in sorted(files.items()):
                archive.writestr(f"submission/{path}", contents)
            for path, contents in sorted(package.visible_tests.items()):
                archive.writestr(path, contents)
        return buffer.getvalue()

    def _run_job(self, job_id: str, archive: bytes) -> None:
        if not self.jobs.start(job_id):
            return  # Duplicate dispatch or an already finished job.
        try:
            result = self.executor.run(job_id, archive)
        except DockerRunError as exc:
            result = failed_result(job_id, exc.code)
        except Exception:
            result = failed_result(job_id, "internal_error")
        if (
            not isinstance(result, dict)
            or result.get("job_id") != job_id
            or result.get("status") not in {"COMPLETED", "FAILED"}
        ):
            result = failed_result(job_id, "invalid_runner_result")
        self.jobs.finish(job_id, result)
