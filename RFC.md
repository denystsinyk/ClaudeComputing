CS 1660 / 2060 Final Project Proposal

**RFC 0001: SudoSolver**

| **Field**    | **Value**                                                                                      |
| ------------ | ---------------------------------------------------------------------------------------------- |
| Status       | Draft                                                                                          |
| Repository   | [*https://github.com/denystsinyk/ClaudeCompute*](https://github.com/denystsinyk/ClaudeCompute) |
| Last updated | *2026-11-03*                                                                                   |

# Team

| **Name**      | **Pitt username** | **GitHub**                                                   | **Owns**                               |
| ------------- | ----------------- | ------------------------------------------------------------ | -------------------------------------- |
| Denys Tsinyk  | det82             | [github.com/denystsinyk](https://github.com/denystsinyk)     | Frontend & browser IDE                 |
| Sean Milliken | sem402            | [github.com/sean-milliken](https://github.com/sean-milliken) | Application API, authentication & data |
| Jayden Kelly  | jak678            | [github.com/jkelly924](https://github.com/jkelly924)         | Code execution, Terraform & CI/CD      |
| Liam Brem     | leb253            | [github.com/liambrem](https://github.com/liambrem)           | AI generation & provider integration   |

# Summary

SudoSolver is a browser-based platform for practicing practical software engineering interview problems beyond traditional LeetCode-style algorithms. Users sign in, choose a prebuilt challenge or generate a personalized one using their own OpenAI or Anthropic API key, and solve it in a lightweight multi-file Python editor. They can run visible tests, submit solutions against hidden tests, and return later to saved code and submission results. Generated questions can target a topic, difficulty, duration, and implementation style, including modifying a small existing codebase.

# Motivation

Software engineering interviews increasingly include tasks such as implementing a cache, debugging an existing codebase, or extending a small service. Traditional algorithm practice platforms do not focus on these workflows, and creating realistic exercises manually is time-consuming. SudoSolver provides on-demand, configurable practice. Cloud infrastructure is useful because AI generation and code execution are bursty, computationally separate tasks: Lambda and SQS handle asynchronous work, Fargate provides a fresh execution environment for each run, and S3/DynamoDB preserve user work across sessions. Most infrastructure can remain idle when nobody is practicing.

# Goals and Non-Goals

## Goals

- Users can sign in through an invite-only account and browse 1–2 prebuilt Python problems.
- Users can save an OpenAI or Anthropic API key and generate a problem using topic, difficulty, style, duration, and custom instructions.
- Users can edit multiple Python files in-browser and have their working code autosaved.
- Users can run provided visible pytest tests and see per-test results, errors, and execution time.
- Users can submit code against hidden tests and review their verdict and past submissions.
- A GitHub Actions workflow builds the execution image into ECR, and the AWS stack is deployed using Terraform.

## Non-Goals

- Languages other than Python, external Python packages, or a full terminal/cloud IDE.
- Multi-round interviews, AI code review, or automatic verification that generated problems are logically correct.
- Publicly publishing AI-generated problems, payments, or large-scale public registration.
- Production-grade sandboxing for arbitrary hostile code or multi-region availability.

# Architecture

The React/Monaco frontend is served from private S3 through CloudFront. Cognito authenticates users; API Gateway and Lambda handle application requests. DynamoDB stores metadata and job status, while private S3 stores code and test artifacts. AI generation and code execution use separate SQS queues. A generation Lambda calls OpenAI/Anthropic; an execution dispatcher Lambda launches a one-off Fargate task. EventBridge reports task completion to a finalizer Lambda.



Example request: submitting a solution

- An authenticated user clicks Submit in the browser IDE; the frontend sends their current files to POST /problems/{id}/submit through API Gateway.
- The API Lambda checks ownership and quotas, saves a submission snapshot in private S3, creates a QUEUED job in DynamoDB, and sends its job ID to the execution SQS queue. It returns 202 Accepted with the job ID.
- A dispatcher Lambda launches a single Fargate task using the runner image stored in ECR. The trusted runner receives short-lived, job-specific S3 presigned URLs for inputs and output.
- The runner loads the submitted Python files and hidden pytest tests, executes them with time/resource limits, and uploads a results artifact to S3. The submitted code does not receive application IAM credentials.
- ECS emits a STOPPED event through EventBridge. A finalizer Lambda retrieves the results, records the verdict and immutable submission in DynamoDB, and marks the job COMPLETED or FAILED.
- The frontend polls GET /jobs/{jobId} and displays the pass count and verdict without returning the hidden test source.





# AWS Services

| **#** | **Service**                         | **Role in our system**                                                         | **Why this and not an alternative**                                                    |
| ----- | ----------------------------------- | ------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------- |
| 1     | Amazon S3                           | Private storage for the website, codebases, tests, workspaces, and results     | Better suited to files and snapshots than DynamoDB items                               |
| 2     | Amazon CloudFront                   | Serves the React app from a private S3 origin                                  | CDN delivery without an always-running web server                                      |
| 3     | Amazon Cognito                      | Invite-only sign-in and JWT issuance                                           | Avoids building and securing custom authentication                                     |
| 4     | Amazon API Gateway                  | Exposes authenticated REST endpoints                                           | Native Lambda integration instead of a dedicated load balancer                         |
| 5     | AWS Lambda                          | Handles the API, AI generation, dispatching, and finalization                  | Scales to sporadic requests without an idle server                                     |
| 6     | Amazon DynamoDB                     | Stores problems, ownership, saved-work metadata, jobs, quotas, and submissions | Serverless key-value access instead of managing RDS                                    |
| 7     | Amazon SQS                          | Buffers generation and execution jobs                                          | Durable asynchronous processing instead of long HTTP requests                          |
| 8     | Amazon ECS with Fargate             | Starts one short-lived container per code execution                            | Better workload isolation and resource controls than running code in API Lambda        |
| 9     | Amazon ECR                          | Stores the pinned Python/pytest runner Docker image                            | Private AWS-native container registry integrated with GitHub Actions                   |
| 10    | Amazon EventBridge                  | Routes ECS task completion events to the finalizer                             | Event-based completion handling instead of constantly polling ECS                      |
| 11    | AWS Systems Manager Parameter Store | Stores each user's encrypted OpenAI/Anthropic API key as a SecureString        | Lower-overhead storage for a small beta than a separate Secrets Manager secret per key |

# Data Model

**DynamoDB access patterns (first):** (1) load a user's profile; (2) list public prebuilt problems and the user's generated problems; (3) read one problem after checking ownership; (4) load/update a user's workspace; (5) retrieve/poll a job; (6) list submissions for a problem; (7) atomically enforce per-user daily quotas and global execution limits.

We will use one DynamoDB table, `SudoSolver`, with `PK` and `SK` plus `GSI1PK` / `GSI1SK` for list queries:

| **Item**                 | **PK**        | **SK**                                     | **Key fields / index**                                                                                             |
| ------------------------ | ------------- | ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------ |
| User                     | USER#\<sub>   | PROFILE                                    | Cognito user ID, createdAt                                                                                         |
| Problem                  | PROBLEM#\<id> | META                                       | ownerId, visibility, topic, difficulty, S3 key; GSI1: `CATALOG` or `USER#<sub>#PROBLEMS`, ordered by creation time |
| Workspace                | USER#\<sub>   | WORKSPACE#\<problemId>                     | Latest S3 snapshot key, updatedAt                                                                                  |
| Job                      | JOB#\<id>     | META                                       | userId, problemId, type, status, timestamps, result key; GSI1 for user's job history                               |
| Submission               | USER#\<sub>   | SUBMISSION#\<problemId>#\<timestamp>#\<id> | Immutable S3 snapshot key, verdict, pass count                                                                     |
| Quota                    | USER#\<sub>   | QUOTA#\<date>                              | Daily generation/execution counters; conditional updates                                                           |
| Global execution counter | GLOBAL        | ACTIVE_EXECUTIONS                          | Maximum of two active Fargate executions, updated atomically                                                       |

**S3 layout:** A private frontend bucket contains `index.html` and `assets/*` (readable only through CloudFront Origin Access Control). A separate private artifacts bucket contains `problems/public/<id>/...`, `problems/users/<sub>/<id>/...`, `workspaces/<sub>/<problemId>/latest.zip`, `jobs/<jobId>/input.zip`, `jobs/<jobId>/results.json`, and `submissions/<sub>/<problemId>/<submissionId>.zip`. Problem packages distinguish starter files, visible tests, hidden tests, and reference solutions. The browser never receives hidden test files or reference solutions. The API authorizes each artifact access; execution runners use short-lived presigned URLs for specific job objects.



# API

All endpoints except `/health` require a valid Cognito JWT. Problem and job endpoints also check resource ownership.

| **Method** | **Path**                   | **Auth** | **Description**                                       |
| ---------- | -------------------------- | -------- | ----------------------------------------------------- |
| GET        | /health                    | No       | Basic API health check                                |
| GET        | /problems                  | Yes      | List prebuilt and the user's generated problems       |
| GET        | /problems/{id}             | Yes      | Get accessible problem instructions and visible files |
| POST       | /problems/generate         | Yes      | Queue AI generation; return job ID                    |
| GET        | /problems/{id}/workspace   | Yes      | Load saved working files                              |
| PUT        | /problems/{id}/workspace   | Yes      | Autosave editable files                               |
| POST       | /problems/{id}/run         | Yes      | Queue visible tests and user-written tests            |
| POST       | /problems/{id}/submit      | Yes      | Queue hidden tests and create submission              |
| GET        | /jobs/{id}                 | Yes      | Poll generation/execution status and results          |
| GET        | /problems/{id}/submissions | Yes      | List prior submission verdicts                        |
| PUT        | /settings/keys/{provider}  | Yes      | Store or replace an encrypted provider API key        |
| DELETE     | /settings/keys/{provider}  | Yes      | Delete a saved provider key                           |

Expected errors: 400 for malformed files/options, 401 for missing/invalid tokens, 403 for unauthorized access (optionally 404 to avoid revealing private resources), 404 for unknown problems/jobs, 409 for conflicting active jobs, and 429 for exceeded quotas. Job states are QUEUED, RUNNING, COMPLETED, and FAILED.

# Infrastructure as Code

Terraform will use a single infra/environments/dev root module and reusable modules for frontend, API/authentication, data, queues, and execution infrastructure. State lives in a separate private S3 backend with locking enabled; that state bucket is bootstrapped once and does not count toward the service requirement. The app stack, IAM roles, queue policies, networking, storage, and EventBridge rules are declared in Terraform. User-supplied API keys and application content are created at runtime, not in Terraform.



From a fresh clone, a teammate installs Terraform/AWS CLI, configures an authorized AWS role, initializes the backend, runs terraform plan and terraform apply (or uses the manual deployment workflow), and deploys the frontend and runner image using GitHub Actions. Required environment variables and bootstrap steps will be documented in the README.

# CI/CD

- Pull requests: GitHub Actions runs frontend/backend tests, Python formatting/static checks, and terraform fmt/validate.
- Push to main: Builds the pinned execution-runner Docker image and pushes it to Amazon ECR; builds the React frontend artifact. This does not automatically apply infrastructure changes.
- Manual workflow_dispatch: Assumes a scoped AWS deployment role using GitHub Actions OIDC, applies reviewed Terraform changes, and publishes the frontend to S3 (with CloudFront invalidation if needed). No long-lived AWS keys are stored in GitHub secrets.

# Security

- Authentication: Cognito handles invite-only user registration and JWTs; API Gateway/Lambda verifies tokens.
- Authorization: Lambda derives user identity from the verified token, not client-supplied owner IDs. DynamoDB records and S3 paths are checked before read/write; generated problems are private, while prebuilt ones are shared.
- IAM: The API Lambda can access only its table, designated S3 buckets, queues, and key-management endpoints. The generation Lambda can read the /sudosolver/users/\*/keys/\* SSM parameter path and write problem artifacts. The dispatcher can call ecs:RunTask for the designated task definition and pass only its execution role. The finalizer can read designated result objects and update job records. The Fargate task execution role can pull from ECR and write CloudWatch Logs; no application task role is granted to user-code execution tasks.
- Secrets: Provider API keys are stored as encrypted SSM SecureString parameters, never in Git or logs, and are retrievable only by trusted backend functions. Users can replace/delete them.
- Code execution: Each run uses an ephemeral Fargate task, a restricted network configuration, no general internet access, non-root Python execution, sanitized child-process environment, CPU/memory/time limits, and short-lived S3 URLs handled by the trusted runner. This is a restricted beta sandbox, not a production-grade guarantee against hostile code. Private-network ECR/Logs endpoints and an S3 gateway endpoint may be needed, with their costs tracked against credits.
- Abuse controls: One active generation and execution per user, 10 generations/30 executions daily, and two Fargate tasks globally. DynamoDB conditional updates enforce limits; stuck jobs require cleanup.





# Observability

Lambda and ECS write structured logs to CloudWatch Logs with jobId, user ID, operation, duration, and error category, excluding code contents and secrets. The /health endpoint checks API availability. Developers can inspect DynamoDB job states, SQS backlog, ECS task status, and correlated logs to diagnose failures. No custom CloudWatch dashboard or alarms are planned for the MVP. AWS budget notifications help watch credit usage.

# Demo Plan

- Sign in and browse a prebuilt problem; show that saved AI-generated problems also appear in the user's library (Goal 1).
- Briefly show the generation settings and a previously generated problem, including its saved provider configuration; avoid waiting for a live LLM call (Goal 2).
- Open the generated problem in the browser, edit two Python files, and show autosave (Goal 3).
- Run visible tests, inspect a failing assertion, fix the code, and rerun (Goal 4).
- Submit the solution, poll the job, and show the hidden-test verdict and saved submission history (Goal 5).
- Show the deployed AWS resources and the GitHub Actions ECR build/deploy workflow briefly (Goal 6).



# Risks and Open Questions

- Sandbox safety: Fargate isolates tasks, but safely separating runner credentials, hidden tests, and untrusted Python within a task is difficult. We will restrict access and clearly document remaining risks.
- Generated problem quality: Schema/syntax validation does not guarantee logically correct requirements or tests. Users can manually retry failed generations.
- Latency: Starting a new Fargate task can make Run Tests noticeably slower than local execution. The demo will use a prepared problem.
- Costs/networking: Fargate and private VPC endpoints can consume promotional credits; we'll cap concurrency, avoid NAT Gateways, and monitor spending. The project depends on credits covering these resources.
- Schedule: Four weeks is tight. First milestone is a vertical slice that runs a prebuilt Python test through Fargate; AI generation and autosave integrate after that.
- Open review question: Is the restricted, invite-only execution model acceptable for the course's security expectations?

# Alternatives Considered



- Lambda for user-code execution: Rejected in favor of dedicated Fargate tasks for greater control over the execution environment and per-run isolation.
- Always-running ECS backend: Rejected because API traffic will be low and bursty; API Gateway + Lambda avoids idle compute cost.
- RDS instead of DynamoDB: Rejected because our main access patterns are predictable key-based lookups and the project does not require relational joins.
- Step Functions for execution orchestration: Rejected to limit scope; SQS, Lambda, and EventBridge cover job dispatch and completion for the MVP.

# AI Usage

*Per the syllabus: if AI tools contributed significantly to this proposal or your design, say how. "None" is a valid answer.*

TBD
