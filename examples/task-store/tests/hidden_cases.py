import pytest

from task import Task
from task_store import TaskStore


def test_blank_id_and_duplicate_id_are_rejected() -> None:
    store = TaskStore()

    with pytest.raises(ValueError):
        store.add(" \t", "A task")

    store.add("first", "First task")
    with pytest.raises(ValueError):
        store.add("first", "Replacement")

    assert store.get("first") == Task(id="first", title="First task")


def test_complete_unknown_task_raises_key_error() -> None:
    with pytest.raises(KeyError):
        TaskStore().complete("missing")


def test_completion_is_idempotent() -> None:
    store = TaskStore()
    store.add("first", "First task")

    assert store.complete("first") == store.complete("first")


def test_list_is_sorted_and_stores_are_independent() -> None:
    first = TaskStore()
    second = TaskStore()
    first.add("z", "Last")
    first.add("a", "First")

    assert first.list_all() == [Task(id="a", title="First"), Task(id="z", title="Last")]
    assert second.list_all() == []


def test_original_text_is_preserved() -> None:
    store = TaskStore()

    assert store.add(" id ", " Title ") == Task(id=" id ", title=" Title ")
