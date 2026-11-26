# Local application API

This is the first prebuilt-problem run slice. It uses the real runner image through Docker and keeps job state in memory. It does not use AWS, Cognito, DynamoDB, S3, or SQS yet.

## Run locally

From the repository root:

```sh
make api-smoke
make api-local
```

`api-smoke` assembles a job from the task-store reference solution, launches Docker, and checks for a passing result. `api-local` builds the image and starts an HTTP server on `127.0.0.1:8080`. It prints a random local bearer token. Use that token in the `Authorization: Bearer <token>` header. The token maps to one server-side local identity; a request cannot choose its user ID. Jobs and the token are lost when the server restarts.

## Current endpoints

| Method | Path | Result |
| --- | --- | --- |
| GET | `/health` | `{"status":"ok"}`; no token required. |
| GET | `/problems` | Public prebuilt problem catalog; token required. |
| GET | `/problems/{id}` | Instructions, editable starter files, visible tests; token required. |
| POST | `/problems/{id}/run` | Queues a Docker run and returns `202` with `jobId`; token required. |
| GET | `/jobs/{id}` | Job status and, when finished, runner result; owner only. |

The run request is JSON with exactly one `files` object. Its keys must exactly match the problem's editable file names:

```json
{"files":{"task.py":"...Python source...","task_store.py":"...Python source..."}}
```

Start with the `files` returned by `GET /problems/task-store`, edit them, then POST them to `/problems/task-store/run`. Poll `/jobs/{jobId}` until its status is `COMPLETED` or `FAILED`. A failing assertion produces a completed job with `verdict: "FAIL"`; runner or dispatch errors produce a failed job. The backend constructs a ZIP containing only the submitted files and visible tests, using the [runner contract](../services/runner/README.md). It never returns hidden tests, reference files, or the job ZIP to the client.

This local implementation checks bearer tokens and job ownership. Its in-memory job store guards `QUEUED → RUNNING → COMPLETED/FAILED` transitions and ignores duplicate dispatch. The next AWS step will replace the local token verifier, job store, and Docker dispatch with Cognito verification, DynamoDB, S3/SQS, and Fargate while preserving the HTTP and runner contracts.
