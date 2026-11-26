from dataclasses import replace

from task import Task


class TaskStore:
    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}

    def add(self, task_id: str, title: str) -> Task:
        if not task_id.strip() or not title.strip():
            raise ValueError("Task ID and title must not be blank")
        if task_id in self._tasks:
            raise ValueError("Task ID already exists")

        task = Task(id=task_id, title=title)
        self._tasks[task_id] = task
        return task

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def complete(self, task_id: str) -> Task:
        task = self._tasks[task_id]
        if task.completed:
            return task

        completed = replace(task, completed=True)
        self._tasks[task_id] = completed
        return completed

    def list_all(self) -> list[Task]:
        return [self._tasks[task_id] for task_id in sorted(self._tasks)]
