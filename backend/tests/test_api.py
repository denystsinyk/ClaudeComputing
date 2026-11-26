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
from backend.execution import JobLifecycle, LocalDispatcher
from backend.jobs import DockerRunError, JobStore, failed_result
from backend.local_server import create_server
from backend.problem_packages import PackageError, load_problem
from backend.submissions import LocalSubmissionStore


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

    def run(self, job_id: str, archive: bytes, mode: str) -> dict:
        self.calls.append((job_id, archive, mode))
        if self.failure:
            raise DockerRunError(self.failure)
        return {
            "schema_version": 1,
            "job_id": job_id,
            "mode": mode,
            "status": "COMPLETED",
            "verdict": "PASS",
            "summary": {
                "passed": 4 if mode == "run" else 5,
                "failed": 0,
                "errors": 0,
                "skipped": 0,
                "duration_ms": 200,
            },
            "tests": [{"name": "hidden_cases.test_secret"}] if mode == "submit" else [],
        }


@pytest.fixture
def app(tmp_path: Path):
    scheduler = ManualScheduler()
    executor = FakeExecutor()
    lifecycle = JobLifecycle(JobStore(), LocalSubmissionStore(tmp_path / "submissions.sqlite3"))
    api = Api(
        EXAMPLES,
        TokenAuth({"alice-token": "alice", "bob-token": "bob"}),
        lifecycle,
        LocalDispatcher(executor, scheduler, lifecycle),
    )
    return api, scheduler, executor


def starter_files(api: Api) -> dict[str, str]:
    detail = api.handle("GET", "/problems/task-store", "Bearer alice-token")
    assert detail.status == 200
    return detail.payload["files"]


def run_request(api: Api, files: dict[str, str], token: str = "alice-token", mode: str = "run"):
    return api.handle(
        "POST",
        f"/problems/task-store/{mode}",
        f"Bearer {token}",
        json.dumps({"files": files}).encode(),
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


def test_submit_saves_private_snapshot_and_returns_only_summary(app) -> None:
    api, scheduler, executor = app
    files = starter_files(api)
    original = files["task_store.py"]
    accepted = run_request(api, files, mode="submit")
    assert accepted.status == 202
    submission_id = accepted.payload["submissionId"]
    job_id = accepted.payload["jobId"]
    files["task_store.py"] = "changed after submission"
    assert api.submissions.snapshot(submission_id)["task_store.py"] == original

    queued = api.handle("GET", "/problems/task-store/submissions", "Bearer alice-token")
    assert queued.payload["submissions"][0]["status"] == "QUEUED"
    assert api.handle("GET", "/problems/task-store/submissions", "Bearer bob-token").payload == {
        "submissions": []
    }

    scheduler.run_next()
    job = api.handle("GET", f"/jobs/{job_id}", "Bearer alice-token")
    assert job.payload["status"] == "COMPLETED"
    assert job.payload["mode"] == "submit"
    assert job.payload["submissionId"] == submission_id
    assert job.payload["result"]["summary"]["passed"] == 5
    assert "tests" not in job.payload["result"]
    assert "hidden_cases" not in json.dumps(job.payload)

    history = api.handle("GET", "/problems/task-store/submissions", "Bearer alice-token")
    assert history.payload["submissions"][0]["verdict"] == "PASS"
    assert history.payload["submissions"][0]["summary"]["passed"] == 5
    assert "files" not in json.dumps(history.payload)
    assert "hidden_cases" not in json.dumps(history.payload)

    with ZipFile(io.BytesIO(executor.calls[0][1])) as archive:
        names = set(archive.namelist())
        metadata = json.loads(archive.read("job.json"))
    assert names == {
        "job.json",
        "submission/task.py",
        "submission/task_store.py",
        "tests/hidden_cases.py",
    }
    assert metadata["mode"] == "submit"


def test_failed_submission_history_and_duplicate_completion(app) -> None:
    api, scheduler, executor = app
    executor.failure = "docker_failed"
    accepted = run_request(api, starter_files(api), mode="submit")
    function, args = scheduler.tasks[0]
    function(*args)
    function(*args)
    assert len(executor.calls) == 1

    job_id = accepted.payload["jobId"]
    job = api.handle("GET", f"/jobs/{job_id}", "Bearer alice-token")
    assert job.payload["status"] == "FAILED"
    assert job.payload["result"]["mode"] == "submit"
    history = api.handle("GET", "/problems/task-store/submissions", "Bearer alice-token")
    assert history.payload["submissions"][0]["error"] == {"code": "docker_failed"}


def test_shared_lifecycle_accepts_external_completion_once(app) -> None:
    api, scheduler, _ = app
    accepted = run_request(api, starter_files(api), mode="submit")
    job_id = accepted.payload["jobId"]
    result = {
        "schema_version": 1,
        "job_id": job_id,
        "mode": "submit",
        "status": "COMPLETED",
        "verdict": "FAIL",
        "summary": {"passed": 3, "failed": 2, "errors": 0, "skipped": 0, "duration_ms": 50},
        "tests": [{"name": "hidden_cases.test_private"}],
    }

    assert api.lifecycle.start(job_id) is True
    assert api.lifecycle.finish(job_id, result) is True
    assert api.lifecycle.finish(job_id, result) is False
    scheduler.run_next()  # A delayed duplicate dispatch must not run after completion.

    job = api.handle("GET", f"/jobs/{job_id}", "Bearer alice-token")
    assert job.payload["result"]["verdict"] == "FAIL"
    assert "tests" not in job.payload["result"]
    assert api.handle("GET", "/problems/task-store/submissions", "Bearer alice-token").payload[
        "submissions"
    ][0]["verdict"] == "FAIL"


def test_dispatch_failure_marks_submission_failed(app) -> None:
    api, _, _ = app

    class RejectedScheduler:
        def submit(self, function, *args) -> None:
            raise RuntimeError("shut down")

    api.dispatcher = LocalDispatcher(FakeExecutor(), RejectedScheduler(), api.lifecycle)
    accepted = run_request(api, starter_files(api), mode="submit")

    assert accepted.status == 202
    job = api.handle("GET", f"/jobs/{accepted.payload['jobId']}", "Bearer alice-token")
    assert job.payload["status"] == "FAILED"
    assert job.payload["result"]["error"] == {"code": "dispatch_unavailable"}
    history = api.handle("GET", "/problems/task-store/submissions", "Bearer alice-token")
    assert history.payload["submissions"][0]["status"] == "FAILED"


def test_submission_history_survives_local_store_restart(tmp_path: Path) -> None:
    database = tmp_path / "private/submissions.sqlite3"
    store = LocalSubmissionStore(database)
    store.create("submission-1", "job-1", "alice", "task-store", {"task.py": "private code"})
    store.start("job-1")

    restarted = LocalSubmissionStore(database)

    assert restarted.snapshot("submission-1") == {"task.py": "private code"}
    assert restarted.list_for_user("alice", "task-store")[0]["error"] == {
        "code": "local_restart"
    }
    assert restarted.list_for_user("bob", "task-store") == []


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
    for mode in ("run", "submit"):
        response = api.handle("POST", f"/problems/task-store/{mode}", "Bearer alice-token", body)
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

        submit = Request(
            f"{base}/problems/task-store/submit",
            data=body,
            headers={"Authorization": "Bearer alice-token", "Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(submit) as response:
            submission_job_id = json.load(response)["jobId"]
        scheduler.run_next()
        request = Request(
            f"{base}/jobs/{submission_job_id}",
            headers={"Authorization": "Bearer alice-token"},
        )
        with urlopen(request) as response:
            assert "tests" not in json.load(response)["result"]
        request = Request(
            f"{base}/problems/task-store/submissions",
            headers={"Authorization": "Bearer alice-token"},
        )
        with urlopen(request) as response:
            assert len(json.load(response)["submissions"]) == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
