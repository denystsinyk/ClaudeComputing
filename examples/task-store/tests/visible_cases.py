import pytest

from task import Task
from task_store import TaskStore


def test_add_and_get_task() -> None:
    store = TaskStore()

    created = store.add("buy-milk", "Buy milk")

    assert created == Task(id="buy-milk", title="Buy milk")
    assert store.get("buy-milk") == created
    assert store.get("missing") is None


def test_complete_task() -> None:
    store = TaskStore()
    store.add("buy-milk", "Buy milk")

    completed = store.complete("buy-milk")

    assert completed == Task(id="buy-milk", title="Buy milk", completed=True)
    assert store.get("buy-milk") == completed


def test_list_all_is_sorted_by_id() -> None:
    store = TaskStore()
    store.add("z", "Last")
    store.add("a", "First")

    assert store.list_all() == [Task(id="a", title="First"), Task(id="z", title="Last")]


def test_blank_title_is_rejected() -> None:
    store = TaskStore()

    with pytest.raises(ValueError):
        store.add("buy-milk", "  ")
