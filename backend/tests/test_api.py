import io
import json
import shutil
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from zipfile import ZipFile

import pytest

from backend.api import Api, TokenAuth
from backend.jobs import DockerRunError, JobStore, failed_result
from backend.local_server import create_server
from backend.problem_packages import PackageError, load_problem


EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


class ManualScheduler:
    def __init__(self) -> None:
        self.tasks = []

    def submit(self, function, *args) -> None:
        self.tasks.append((function, args))

    def run_next(self) -> None:
        function, args = self.tasks.pop(0)
        function(*args)


class FakeExecutor:
    def __init__(self, failure: str | None = None) -> None:
        self.calls = []
        self.failure = failure

    def run(self, job_id: str, archive: bytes) -> dict:
        self.calls.append((job_id, archive))
        if self.failure:
            raise DockerRunError(self.failure)
        return {
            "schema_version": 1,
            "job_id": job_id,
            "mode": "run",
            "status": "COMPLETED",
            "verdict": "PASS",
            "summary": {"passed": 4, "failed": 0, "errors": 0, "skipped": 0, "duration_ms": 200},
            "tests": [],
        }


@pytest.fixture
def app():
    scheduler = ManualScheduler()
    executor = FakeExecutor()
    api = Api(
        EXAMPLES,
        TokenAuth({"alice-token": "alice", "bob-token": "bob"}),
        JobStore(),
        executor,
        scheduler,
    )
    return api, scheduler, executor


def starter_files(api: Api) -> dict[str, str]:
    detail = api.handle("GET", "/problems/task-store", "Bearer alice-token")
    assert detail.status == 200
    return detail.payload["files"]


def run_request(api: Api, files: dict[str, str], token: str = "alice-token"):
    return api.handle(
        "POST", "/problems/task-store/run", f"Bearer {token}", json.dumps({"files": files}).encode()
    )


def test_catalog_detail_and_run_job(app) -> None:
    api, scheduler, executor = app
    assert api.handle("GET", "/health").status == 200
    assert api.handle("GET", "/problems").status == 401
    catalog = api.handle("GET", "/problems", "Bearer alice-token")
    assert catalog.payload["problems"][0]["id"] == "task-store"

    detail = api.handle("GET", "/problems/task-store", "Bearer alice-token")
    assert set(detail.payload["files"]) == {"task.py", "task_store.py"}
    assert "visible_cases.py" in detail.payload["visibleTests"]
    assert "hidden_cases" not in json.dumps(detail.payload)
    assert "reference" not in json.dumps(detail.payload)

    accepted = run_request(api, detail.payload["files"])
    assert accepted.status == 202
    job_id = accepted.payload["jobId"]
    assert api.handle("GET", f"/jobs/{job_id}", "Bearer alice-token").payload["status"] == "QUEUED"

    scheduler.run_next()
    polled = api.handle("GET", f"/jobs/{job_id}", "Bearer alice-token")
    assert polled.payload["status"] == "COMPLETED"
    assert polled.payload["result"]["verdict"] == "PASS"
    assert "userId" not in polled.payload

    with ZipFile(io.BytesIO(executor.calls[0][1])) as archive:
        names = set(archive.namelist())
        metadata = json.loads(archive.read("job.json"))
    assert names == {
        "job.json",
        "submission/task.py",
        "submission/task_store.py",
        "tests/visible_cases.py",
    }
    assert metadata["mode"] == "run"
    assert metadata["job_id"] == job_id


def test_identity_and_job_ownership(app) -> None:
    api, _, _ = app
    files = starter_files(api)
    accepted = run_request(api, files)
    job_id = accepted.payload["jobId"]

    assert api.handle("GET", f"/jobs/{job_id}", "Bearer bob-token").status == 404
    assert api.handle("GET", f"/jobs/{job_id}", "Bearer wrong-token").status == 401
    assert api.handle("GET", f"/jobs/{job_id}", "Bearer café").status == 401
    assert api.handle("GET", "/problems/task-store", "Bearer wrong-token").status == 401
    assert api.handle("GET", "/problems/unknown", "Bearer alice-token").status == 404


def test_active_job_conflict_and_duplicate_dispatch(app) -> None:
    api, scheduler, executor = app
    files = starter_files(api)
    first = run_request(api, files)
    assert run_request(api, files).status == 409

    function, args = scheduler.tasks[0]
    function(*args)
    function(*args)  # A repeated queue delivery must not run the same job twice.
    assert len(executor.calls) == 1
    assert run_request(api, files).status == 202
    assert (
        api.jobs.finish(first.payload["jobId"], failed_result(first.payload["jobId"], "late"))
        is False
    )


def test_runner_failure_becomes_failed_job(app) -> None:
    api, scheduler, executor = app
    executor.failure = "docker_unavailable"
    accepted = run_request(api, starter_files(api))

    scheduler.run_next()
    polled = api.handle("GET", f"/jobs/{accepted.payload['jobId']}", "Bearer alice-token")
    assert polled.payload["status"] == "FAILED"
    assert polled.payload["result"]["error"] == {"code": "docker_unavailable"}


def test_job_store_rejects_duplicate_ids_and_invalid_transitions() -> None:
    jobs = JobStore()
    jobs.create("job-1", "alice", "task-store")

    with pytest.raises(ValueError, match="already exists"):
        jobs.create("job-1", "bob", "task-store")
    assert jobs.start("job-1") is True
    assert jobs.start("job-1") is False
    with pytest.raises(ValueError, match="invalid terminal"):
        jobs.finish("job-1", {"job_id": "job-1", "status": "QUEUED"})
    assert jobs.finish("job-1", failed_result("job-1", "test_error")) is True
    assert jobs.finish("job-1", failed_result("job-1", "late_error")) is False


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"{}",
        b'{"files":{"task.py":"pass"}}',
        b'{"files":{"task.py":"pass","task_store.py":"pass","evil.py":"pass"}}',
        b'{"files":{},"userId":"bob"}',
    ],
)
def test_bad_run_requests_are_rejected(app, body: bytes) -> None:
    api, _, _ = app
    response = api.handle("POST", "/problems/task-store/run", "Bearer alice-token", body)
    assert response.status == 400


def test_invalid_package_path_is_rejected(tmp_path: Path) -> None:
    package = tmp_path / "task-store"
    shutil.copytree(
        EXAMPLES / "task-store",
        package,
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"),
    )
    manifest_path = package / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["starter_files"] = ["starter/../hidden.py"]
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(PackageError):
        load_problem(tmp_path, "task-store")


def test_loopback_http_adapter(app) -> None:
    api, scheduler, _ = app
    server = create_server(api, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(f"{base}/health") as response:
            assert json.load(response) == {"status": "ok"}
        with pytest.raises(HTTPError) as denied:
            urlopen(f"{base}/problems")
        assert denied.value.code == 401

        body = json.dumps({"files": starter_files(api)}).encode()
        request = Request(
            f"{base}/problems/task-store/run",
            data=body,
            headers={"Authorization": "Bearer alice-token", "Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request) as response:
            assert response.status == 202
            job_id = json.load(response)["jobId"]
        scheduler.run_next()
        request = Request(f"{base}/jobs/{job_id}", headers={"Authorization": "Bearer alice-token"})
        with urlopen(request) as response:
            assert json.load(response)["status"] == "COMPLETED"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
