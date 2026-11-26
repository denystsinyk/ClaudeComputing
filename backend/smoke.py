"""Exercise the prebuilt problem API through the real local Docker executor."""

import json
import tempfile
from pathlib import Path

from backend.api import Api, TokenAuth
from backend.execution import JobLifecycle, LocalDispatcher
from backend.jobs import JobStore, LocalDockerExecutor
from backend.submissions import LocalSubmissionStore


class ImmediateScheduler:
    def submit(self, function, *args) -> None:
        function(*args)


def main() -> None:
    examples = Path(__file__).resolve().parents[1] / "examples"
    with tempfile.TemporaryDirectory(prefix="sudosolver-smoke-") as directory:
        lifecycle = JobLifecycle(
            JobStore(), LocalSubmissionStore(Path(directory) / "submissions.sqlite3")
        )
        api = Api(
            examples,
            TokenAuth({"smoke-token": "smoke-user"}),
            lifecycle,
            LocalDispatcher(LocalDockerExecutor(), ImmediateScheduler(), lifecycle),
        )
        detail = api.handle("GET", "/problems/task-store", "Bearer smoke-token")
        if detail.status != 200:
            raise SystemExit(f"Could not load task-store: {detail.payload}")

        files = detail.payload["files"]
        files["task_store.py"] = (examples / "task-store/reference/task_store.py").read_text()
        for mode in ("run", "submit"):
            accepted = api.handle(
                "POST",
                f"/problems/task-store/{mode}",
                "Bearer smoke-token",
                json.dumps({"files": files}).encode(),
            )
            if accepted.status != 202:
                raise SystemExit(f"Could not queue {mode}: {accepted.payload}")
            job_id = accepted.payload["jobId"]
            job = api.handle("GET", f"/jobs/{job_id}", "Bearer smoke-token").payload
            print(json.dumps(job, indent=2))
            if job["status"] != "COMPLETED" or job["result"]["verdict"] != "PASS":
                raise SystemExit(f"Local {mode} API-to-Docker smoke test failed")
        history = api.handle("GET", "/problems/task-store/submissions", "Bearer smoke-token")
        if len(history.payload["submissions"]) != 1:
            raise SystemExit("Submission history was not saved")


if __name__ == "__main__":
    main()
