# Local application API

This is the local prebuilt-problem run and submit flow. It uses the real runner image through Docker. Active job state is in memory; private submission snapshots and verdict history are stored in SQLite. It does not use AWS or Cognito.

## Run locally

From the repository root:

```sh
make api-smoke
make api-local
```

`api-smoke` runs and submits the task-store reference solution through Docker, checking both results. `api-local` builds the image and starts an HTTP server on `127.0.0.1:8080`. It prints a random local bearer token. Use that token in the `Authorization: Bearer <token>` header. The token maps to one server-side local identity; a request cannot choose its user ID.

The default submission database is `backend/.local/submissions.sqlite3`, which is Git-ignored and restricted to the local user. Set `SUDOSOLVER_LOCAL_DB` to use another path. Submission history survives a server restart; unfinished submissions are marked `FAILED` with `local_restart`. Active jobs and the local token are in memory, so old job IDs cannot be polled after a restart.

## Current endpoints

| Method | Path | Result |
| --- | --- | --- |
| GET | `/health` | `{"status":"ok"}`; no token required. |
| GET | `/problems` | Public prebuilt problem catalog; token required. |
| GET | `/problems/{id}` | Instructions, editable starter files, visible tests; token required. |
| POST | `/problems/{id}/run` | Queues a Docker run and returns `202` with `jobId`; token required. |
| POST | `/problems/{id}/submit` | Snapshots the files, queues hidden tests, and returns `202` with `jobId` and `submissionId`; token required. |
| GET | `/jobs/{id}` | Job status and, when finished, runner result; owner only. |
| GET | `/problems/{id}/submissions` | The current user's submission verdict history; token required. |

Run and submit requests use the same JSON body with exactly one `files` object. Its keys must exactly match the problem's editable file names:

```json
{"files":{"task.py":"...Python source...","task_store.py":"...Python source..."}}
```

Start with the `files` returned by `GET /problems/task-store`, edit them, then POST them to `/problems/task-store/run` or `/problems/task-store/submit`. Poll `/jobs/{jobId}` until its status is `COMPLETED` or `FAILED`. A failing assertion produces a completed job with `verdict: "FAIL"`; runner or dispatch errors produce a failed job. Run ZIPs contain visible tests; submit ZIPs contain hidden tests. Submit job results and submission history contain only a verdict and counts, never hidden-test names or failure text. The backend never returns reference files or the job ZIP to the client.

The local API checks bearer tokens and job ownership. `JobLifecycle` guards `QUEUED → RUNNING → COMPLETED/FAILED` transitions, ignores duplicate dispatch and completion, and filters submit results before storage. The adapter boundaries for a later AWS implementation are in [`ports.py`](ports.py), with a focused [handoff note](../docs/local-to-aws.md). The job ZIP and result formats are in the [runner contract](../services/runner/README.md).
