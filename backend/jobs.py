"""Local job state and Docker dispatch for the development API."""

import copy
import json
import os
import subprocess
import tempfile
import threading
from pathlib import Path


MAX_RESULT_BYTES = 1_000_000


class ActiveJobError(Exception):
    pass


class DockerRunError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class JobStore:
    """Thread-safe local store with guarded job transitions."""

    def __init__(self) -> None:
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def create(self, job_id: str, user_id: str, problem_id: str) -> None:
        with self._lock:
            if job_id in self._jobs:
                raise ValueError("job already exists")
            if any(
                job["userId"] == user_id and job["status"] in {"QUEUED", "RUNNING"}
                for job in self._jobs.values()
            ):
                raise ActiveJobError
            self._jobs[job_id] = {
                "jobId": job_id,
                "userId": user_id,
                "problemId": problem_id,
                "status": "QUEUED",
                "result": None,
            }

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return copy.deepcopy(job) if job else None

    def start(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job["status"] != "QUEUED":
                return False
            job["status"] = "RUNNING"
            return True

    def finish(self, job_id: str, result: dict) -> bool:
        if result.get("job_id") != job_id or result.get("status") not in {"COMPLETED", "FAILED"}:
            raise ValueError("invalid terminal job result")
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job["status"] != "RUNNING":
                return False
            job["status"] = result["status"]
            job["result"] = copy.deepcopy(result)
            return True


def failed_result(job_id: str, code: str) -> dict:
    return {
        "schema_version": 1,
        "job_id": job_id,
        "mode": "run",
        "status": "FAILED",
        "verdict": None,
        "error": {"code": code},
    }


class LocalDockerExecutor:
    """Runs the existing runner image; submitted code never executes in the API process."""

    def __init__(self, image: str = "sudosolver-runner:local") -> None:
        self.image = image

    def run(self, job_id: str, archive: bytes) -> dict:
        with tempfile.TemporaryDirectory(prefix="sudosolver-job-") as directory:
            root = Path(directory)
            input_dir = root / "input"
            output_dir = root / "output"
            input_dir.mkdir()
            output_dir.mkdir()
            (input_dir / "job.zip").write_bytes(archive)

            command = [
                "docker", "run", "--rm", "--pull=never", "--read-only", "--network", "none",
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "--pids-limit", "64", "--memory", "256m", "--cpus", "1",
                "--tmpfs", "/tmp:rw,nosuid,size=32m",
                "--user", f"{os.getuid()}:{os.getgid()}",
                "--mount", f"type=bind,src={input_dir},dst=/input,readonly",
                "--mount", f"type=bind,src={output_dir},dst=/output",
                "-e", "RUNNER_INPUT=/input/job.zip",
                "-e", "RUNNER_OUTPUT=/output/result.json",
                self.image,
            ]
            try:
                process = subprocess.run(command, capture_output=True, timeout=60, check=False)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise DockerRunError("docker_unavailable") from exc
            if process.returncode != 0:
                raise DockerRunError("docker_failed")

            try:
                with (output_dir / "result.json").open("rb") as result_file:
                    data = result_file.read(MAX_RESULT_BYTES + 1)
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise DockerRunError("missing_runner_result") from exc
            if len(data) > MAX_RESULT_BYTES:
                raise DockerRunError("invalid_runner_result")
            try:
                result = json.loads(data)
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise DockerRunError("invalid_runner_result") from exc
            if (
                not isinstance(result, dict)
                or result.get("schema_version") != 1
                or result.get("job_id") != job_id
                or result.get("mode") != "run"
                or result.get("status") not in {"COMPLETED", "FAILED"}
            ):
                raise DockerRunError("invalid_runner_result")
            return result
