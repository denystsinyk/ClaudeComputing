# Local Python runner

This image runs **one** Python test job and exits. The local and future Fargate entrypoints are the same `runner.py`; only the job input/output locations change.

## Try the example

From the repository root, with Docker running:

```sh
make runner-example
make runner-example MODE=run SOLUTION=reference
make runner-example MODE=submit SOLUTION=reference
```

The first command runs the unfinished starter and reports failed visible tests. The second passes the visible tests. The third passes hidden tests and returns only a summary. The output is also written to `services/runner/.local/output/result.json`. The job builder reads the trusted `examples/task-store/manifest.json` and creates `services/runner/.local/input/job.zip`.

The Docker command in the Makefile uses a read-only filesystem, no network, no Linux capabilities, an unprivileged user, a 32 MB writable temporary directory, and CPU, memory, and process limits. The runner also enforces a job timeout. Run submitted code through Docker, not with `python runner.py` on the host. Host-side unit tests use only trusted fixture code.

## Job ZIP v1

The local API creates this ZIP today. An AWS adapter can store it at `jobs/<jobId>/input.zip`. It contains:

```text
job.json                 {"schema_version":1,"job_id":"...","mode":"run|submit","timeout_seconds":10}
submission/*.py          The user's editable files, preserving subdirectories
tests/*.py               Visible tests for run, hidden tests for submit
```

Only `.py` files under `submission/` and `tests/` are accepted. `job.json` is required. The runner rejects traversal paths, symlinks, duplicate paths, oversized archives, and invalid metadata. The API and generator still need their own package validation before job creation. The job ZIP is private and must never be sent to the browser when it contains hidden tests.

The backend must choose `mode` and the test files; neither is a client-controlled setting. A `run` ZIP contains only visible tests, while a `submit` ZIP contains only hidden tests.

## Result JSON v1

The runner writes `schema_version`, `job_id`, `mode`, `status`, and `verdict`. A completed job includes `summary` counts for passed, failed, error, and skipped tests, plus `duration_ms`. `run` results also contain a `tests` array with per-test names, status, duration, and truncated failure text. `submit` results do not contain test names or failure text. A failed job has `status: "FAILED"` and an `error.code`; its verdict is `null`. A test assertion failure is a completed job with `verdict: "FAIL"`.

For Fargate, the dispatcher can set `RUNNER_INPUT` to a short-lived presigned S3 GET URL and `RUNNER_OUTPUT` to a short-lived presigned S3 PUT URL. The runner downloads the ZIP, runs pytest in a child process with a restricted environment, then uploads JSON using `Content-Type: application/json`; the PUT URL must be signed for that header. The task does not need an application IAM role. The same variables use absolute file paths locally. The task should have access only to the required S3 endpoint for artifact transfer, and the API/finalizer must authorize job ownership and filter results before returning them to the browser.

This is a restricted course-project sandbox. Python code inside the task may still inspect files and processes in its own container, so hidden-test confidentiality and result integrity against a hostile submitter are not guaranteed by this design alone.
