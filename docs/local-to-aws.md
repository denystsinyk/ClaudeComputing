# Execution handoff boundaries

The local API now supports a complete prebuilt problem **run and submit** flow. The AWS work can preserve the HTTP shapes in `backend/README.md` and the job ZIP/result JSON in `services/runner/README.md`.

| Boundary | Local implementation | AWS replacement |
| --- | --- | --- |
| Identity verifier | `TokenAuth` maps a server-issued token to a user ID. | Verify Cognito JWT claims; never use a client-provided user ID. |
| Job repository | `JobStore` keeps guarded state in memory. | DynamoDB conditional writes for create/start/finish and owner lookup. |
| Submission repository | `LocalSubmissionStore` stores private snapshots and summary history in SQLite. | Private S3 snapshots plus DynamoDB metadata/history. |
| Dispatcher | `LocalDispatcher` schedules a Docker run in a local thread. | Store the job ZIP in private S3 and send its job ID to SQS. |
| Completion rules | `JobLifecycle` checks state transitions and strips hidden-test details. | Invoke the same rules from the dispatcher/finalizer, with durable conditional updates. |

The API chooses `run` or `submit` and selects only the corresponding test files before dispatch. A `submit` result is reduced to verdict, counts, duration, and a safe error code before either job polling or history can expose it. The runner image already accepts local paths or job-specific presigned HTTPS URLs through `RUNNER_INPUT` and `RUNNER_OUTPUT`.

The local job store is intentionally volatile. In AWS, the job record, ZIP object, submission snapshot, and final result need durable IDs and retry-safe conditional transitions. Duplicate SQS deliveries and ECS STOPPED events must not overwrite a terminal verdict. The local tests in `backend/tests/` cover those transition and privacy rules without AWS credentials.
