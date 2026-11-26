# Build a Task Store

Implement the `TaskStore` methods in `task_store.py`. The provided `Task` data class lives in `task.py`. Use only the Python standard library; no database or external packages are needed.

The store holds tasks in memory for the lifetime of one `TaskStore` instance:

- `add(task_id, title)` creates and returns a `Task` with `completed=False`. Reject an empty or whitespace-only ID or title with `ValueError`. Reject an ID already in this store with `ValueError`. Preserve the original ID and title, including surrounding whitespace.
- `get(task_id)` returns the task with that ID, or `None` if it does not exist.
- `complete(task_id)` marks an existing task complete and returns the updated task. Completing an already complete task returns it unchanged. Raise `KeyError` when the ID does not exist.
- `list_all()` returns all tasks sorted by their IDs. An empty store returns an empty list.

Different `TaskStore` instances must not share tasks. You may change either starter file, but keep the public `Task` fields and `TaskStore` method signatures so the tests can use them.
