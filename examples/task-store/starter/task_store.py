from task import Task


class TaskStore:
    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}

    def add(self, task_id: str, title: str) -> Task:
        raise NotImplementedError

    def get(self, task_id: str) -> Task | None:
        raise NotImplementedError

    def complete(self, task_id: str) -> Task:
        raise NotImplementedError

    def list_all(self) -> list[Task]:
        raise NotImplementedError
