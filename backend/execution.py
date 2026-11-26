"""Shared job lifecycle plus the local Docker dispatch adapter."""

from backend.jobs import DockerRunError, failed_result
from backend.ports import DispatchError, Executor, JobRepository, Scheduler, SubmissionRepository


class JobLifecycle:
    """Rules used by local workers and, later, an AWS completion handler."""

    def __init__(self, jobs: JobRepository, submissions: SubmissionRepository) -> None:
        self.jobs = jobs
        self.submissions = submissions

    def start(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if not job or not self.jobs.start(job_id):
            return False
        if job["submissionId"] is not None:
            try:
                self.submissions.start(job_id)
            except Exception:
                self.jobs.finish(job_id, failed_result(job_id, "submission_store_error", "submit"))
                return False
        return True

    @staticmethod
    def _safe_submit_result(job_id: str, result: dict) -> dict:
        if result["status"] == "FAILED":
            error = result.get("error")
            code = error.get("code") if isinstance(error, dict) else None
            if not isinstance(code, str) or not code.isidentifier() or len(code) > 64:
                code = "invalid_runner_result"
            return failed_result(job_id, code, "submit")
        summary = result.get("summary")
        fields = ("passed", "failed", "errors", "skipped", "duration_ms")
        if (
            result.get("verdict") not in {"PASS", "FAIL"}
            or not isinstance(summary, dict)
            or any(type(summary.get(key)) is not int or summary[key] < 0 for key in fields)
        ):
            return failed_result(job_id, "invalid_runner_result", "submit")
        return {
            "schema_version": 1,
            "job_id": job_id,
            "mode": "submit",
            "status": "COMPLETED",
            "verdict": result["verdict"],
            "summary": {key: summary[key] for key in fields},
        }

    def finish(self, job_id: str, result: dict) -> bool:
        job = self.jobs.get(job_id)
        if not job or job["status"] != "RUNNING":
            return False
        mode = job["mode"]
        if (
            not isinstance(result, dict)
            or result.get("schema_version") != 1
            or result.get("job_id") != job_id
            or result.get("mode") != mode
            or result.get("status") not in {"COMPLETED", "FAILED"}
        ):
            result = failed_result(job_id, "invalid_runner_result", mode)
        if job["submissionId"] is not None:
            result = self._safe_submit_result(job_id, result)
            try:
                self.submissions.finish(job_id, result)
            except Exception:
                result = failed_result(job_id, "submission_store_error", mode)
        return self.jobs.finish(job_id, result)

    def fail_dispatch(self, job_id: str) -> None:
        if self.start(job_id):
            job = self.jobs.get(job_id)
            self.finish(job_id, failed_result(job_id, "dispatch_unavailable", job["mode"]))


class LocalDispatcher:
    """Schedules Docker execution in this process; AWS can enqueue the same job ZIP."""

    def __init__(self, executor: Executor, scheduler: Scheduler, lifecycle: JobLifecycle) -> None:
        self.executor = executor
        self.scheduler = scheduler
        self.lifecycle = lifecycle

    def dispatch(self, job_id: str, archive: bytes) -> None:
        try:
            self.scheduler.submit(self._execute, job_id, archive)
        except RuntimeError as exc:
            raise DispatchError from exc

    def _execute(self, job_id: str, archive: bytes) -> None:
        if not self.lifecycle.start(job_id):
            return
        job = self.lifecycle.jobs.get(job_id)
        mode = job["mode"]
        try:
            result = self.executor.run(job_id, archive, mode)
        except DockerRunError as exc:
            result = failed_result(job_id, exc.code, mode)
        except Exception:
            result = failed_result(job_id, "internal_error", mode)
        self.lifecycle.finish(job_id, result)
