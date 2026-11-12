# Agent Instructions — SudoSolver

SudoSolver is a CS 1660 / 2060 course project: an invite-only, browser-based platform for practical Python interview problems. Read [ARCHITECTURE.md](ARCHITECTURE.md) and `README.md` before making architectural changes.

> **Repository state:** The architecture is a target, not proof that a directory or service already exists. Inspect the actual files before editing, and implement incrementally.

## Working principles

1. **Keep changes small and scoped.** Prefer one component or one end-to-end feature per change. Don't refactor unrelated code.
2. **Develop locally first.** Avoid requiring AWS, credentials, or live LLM calls for routine tests. Prefer small interfaces and test doubles at service boundaries.
3. **Agree on contracts.** Keep frontend/API, problem-package, execution-job, and result shapes consistent. Update documentation when a shared contract changes.
4. **Use simple, readable code.** Favor explicit types, clear errors, focused modules, and minimal dependencies over abstractions that aren't needed yet.
5. **Add tests for behavior.** Cover happy paths and failure cases, especially authorization, malformed inputs, retries, and job-state transitions.
6. **Don't silently change scope.** Keep the MVP Python-only. Avoid introducing public sign-up, extra packages, paid services, or new AWS services without a concrete need.

## Component boundaries (planned)

| Path | Owns |
| --- | --- |
| `frontend/` | React UI, Monaco editor, API client, local editor state. |
| `backend/` | HTTP endpoints, auth, ownership checks, persistence, job orchestration. |
| `services/generator/` | OpenAI/Anthropic adapters, prompts, parsing, and package validation. |
| `services/runner/` | Container entrypoint, Python/pytest execution, resource limits, result format. |
| `infra/` | Terraform, AWS IAM/networking/storage/queues/compute. |
| `examples/` | Prebuilt problem fixtures and tests. |

## Important invariants

- The client never receives hidden tests, reference solutions, provider secrets, or AWS credentials.
- Backend access checks use verified identity, not client-provided user IDs.
- Generated problem packages and filenames must be validated before storage or execution.
- Execution code is untrusted. Never run it directly in the API or generation process; keep the runner isolated and constrained.
- Job handling must tolerate retries and duplicate SQS/EventBridge delivery; don't assume exactly-once execution.
- Never commit `.env` files, API keys, Terraform state, credentials, or user-generated private content.
- Do not run `terraform apply`, deploy, modify cloud resources, or add production credentials unless explicitly requested.

## Validation before finishing

Run only checks that are applicable to files that actually exist:

- Frontend: `npm run build` and available test/lint scripts in `frontend/`.
- Python components: `uv run pytest` and `uv run ruff check .` from the relevant project, if configured.
- Terraform: `terraform fmt -check -recursive` and `terraform validate` in initialized/configured roots, when relevant.

If checks cannot run, explain why instead of reporting success. For each change, summarize what changed, what was tested, and any remaining risks or follow-ups.
