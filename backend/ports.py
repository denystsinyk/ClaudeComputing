"""Small boundaries replaced by AWS adapters after the local flow is stable."""

from typing import Callable, Protocol


class DispatchError(Exception):
    """A job was not accepted by the local scheduler or a future queue."""


class IdentityVerifier(Protocol):
    def user_id(self, authorization: str | None) -> str | None: ...


class JobRepository(Protocol):
    def create(
        self, job_id: str, user_id: str, problem_id: str, mode: str, submission_id: str | None
    ) -> None: ...

    def get(self, job_id: str) -> dict | None: ...

    def start(self, job_id: str) -> bool: ...

    def finish(self, job_id: str, result: dict) -> bool: ...


class SubmissionRepository(Protocol):
    def create(
        self, submission_id: str, job_id: str, user_id: str, problem_id: str, files: dict[str, str]
    ) -> None: ...

    def start(self, job_id: str) -> None: ...

    def finish(self, job_id: str, result: dict) -> None: ...

    def list_for_user(self, user_id: str, problem_id: str) -> list[dict]: ...


class Executor(Protocol):
    def run(self, job_id: str, archive: bytes, mode: str) -> dict: ...


class Dispatcher(Protocol):
    def dispatch(self, job_id: str, archive: bytes) -> None: ...


class Scheduler(Protocol):
    def submit(self, function: Callable, *args: object) -> object: ...
