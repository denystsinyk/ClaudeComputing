"""Exercise the prebuilt problem API through the real local Docker executor."""

import json
from pathlib import Path

from backend.api import Api, TokenAuth
from backend.jobs import JobStore, LocalDockerExecutor


class ImmediateScheduler:
    def submit(self, function, *args) -> None:
        function(*args)


def main() -> None:
    examples = Path(__file__).resolve().parents[1] / "examples"
    api = Api(
        examples,
        TokenAuth({"smoke-token": "smoke-user"}),
        JobStore(),
        LocalDockerExecutor(),
        ImmediateScheduler(),
    )
    detail = api.handle("GET", "/problems/task-store", "Bearer smoke-token")
    if detail.status != 200:
        raise SystemExit(f"Could not load task-store: {detail.payload}")

    files = detail.payload["files"]
    files["task_store.py"] = (examples / "task-store/reference/task_store.py").read_text()
    accepted = api.handle(
        "POST",
        "/problems/task-store/run",
        "Bearer smoke-token",
        json.dumps({"files": files}).encode(),
    )
    if accepted.status != 202:
        raise SystemExit(f"Could not queue run: {accepted.payload}")

    job_id = accepted.payload["jobId"]
    job = api.handle("GET", f"/jobs/{job_id}", "Bearer smoke-token").payload
    print(json.dumps(job, indent=2))
    if job["status"] != "COMPLETED" or job["result"]["verdict"] != "PASS":
        raise SystemExit("Local API-to-Docker smoke test failed")


if __name__ == "__main__":
    main()
