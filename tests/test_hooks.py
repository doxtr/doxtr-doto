"""Tests for the task lifecycle hook system."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from doxtr_doto.collectors import DotoTask
from doxtr_doto.hooks import TaskHookRegistry, task_hooks


@pytest.fixture
def registry() -> TaskHookRegistry:
    """Create a fresh hook registry for each test."""
    return TaskHookRegistry()


@pytest.fixture
def sample_task() -> DotoTask:
    """Create a sample task for testing hooks."""
    return DotoTask(
        id="DOTO-001",
        title="Test Task",
        docname="test_doc",
        lineno=10,
        assignee="alice",
        priority="high",
        status="open",
        due="2025-12-31",
        tags=["test", "hooks"],
        depends_on=[],
        body="Test task body",
        created=datetime(2025, 1, 1, 12, 0, 0),
        updated=datetime(2025, 1, 2, 12, 0, 0),
    )


@pytest.fixture(autouse=True)
def clear_global_hooks():
    """Clear global task_hooks before and after each test."""
    task_hooks.clear()
    yield
    task_hooks.clear()


class TestTaskHookRegistry:
    """Tests for TaskHookRegistry class."""

    def test_on_task_created_registers_hook(self, registry: TaskHookRegistry) -> None:
        """Test that on_task_created decorator registers the hook."""

        @registry.on_task_created
        def my_hook(task: DotoTask) -> None:
            pass

        assert len(registry._on_task_created) == 1
        assert registry._on_task_created[0] is my_hook

    def test_on_task_updated_registers_hook(self, registry: TaskHookRegistry) -> None:
        """Test that on_task_updated decorator registers the hook."""

        @registry.on_task_updated
        def my_hook(task: DotoTask) -> None:
            pass

        assert len(registry._on_task_updated) == 1

    def test_on_status_changed_registers_hook(self, registry: TaskHookRegistry) -> None:
        """Test that on_status_changed decorator registers the hook."""

        @registry.on_status_changed
        def my_hook(task: DotoTask, old: str, new: str) -> None:
            pass

        assert len(registry._on_status_changed) == 1

    def test_on_task_archived_registers_hook(self, registry: TaskHookRegistry) -> None:
        """Test that on_task_archived decorator registers the hook."""

        @registry.on_task_archived
        def my_hook(task: DotoTask) -> None:
            pass

        assert len(registry._on_task_archived) == 1

    def test_on_task_reopened_registers_hook(self, registry: TaskHookRegistry) -> None:
        """Test that on_task_reopened decorator registers the hook."""

        @registry.on_task_reopened
        def my_hook(task: DotoTask) -> None:
            pass

        assert len(registry._on_task_reopened) == 1

    def test_on_conflict_registers_hook(self, registry: TaskHookRegistry) -> None:
        """Test that on_conflict decorator registers the hook."""

        @registry.on_conflict
        def my_hook(task: DotoTask, conflicts: list[Any]) -> None:
            pass

        assert len(registry._on_conflict) == 1

    def test_decorator_returns_original_function(self, registry: TaskHookRegistry) -> None:
        """Test that decorators return the original function."""

        def my_hook(task: DotoTask) -> None:
            pass

        result = registry.on_task_created(my_hook)
        assert result is my_hook


class TestHookFiring:
    """Tests for hook firing behavior."""

    def test_fire_task_created_calls_hook(
        self, registry: TaskHookRegistry, sample_task: DotoTask
    ) -> None:
        """Test that fire_task_created calls registered hooks."""
        called_with: list[DotoTask] = []

        @registry.on_task_created
        def my_hook(task: DotoTask) -> None:
            called_with.append(task)

        registry.fire_task_created(sample_task)

        assert len(called_with) == 1
        assert called_with[0] is sample_task

    def test_fire_task_updated_calls_hook(
        self, registry: TaskHookRegistry, sample_task: DotoTask
    ) -> None:
        """Test that fire_task_updated calls registered hooks."""
        called_with: list[DotoTask] = []

        @registry.on_task_updated
        def my_hook(task: DotoTask) -> None:
            called_with.append(task)

        registry.fire_task_updated(sample_task)

        assert len(called_with) == 1
        assert called_with[0] is sample_task

    def test_fire_status_changed_calls_hook_with_all_args(
        self, registry: TaskHookRegistry, sample_task: DotoTask
    ) -> None:
        """Test that fire_status_changed passes all arguments."""
        calls: list[tuple[DotoTask, str, str]] = []

        @registry.on_status_changed
        def my_hook(task: DotoTask, old_status: str, new_status: str) -> None:
            calls.append((task, old_status, new_status))

        registry.fire_status_changed(sample_task, "open", "in-progress")

        assert len(calls) == 1
        assert calls[0] == (sample_task, "open", "in-progress")

    def test_fire_task_archived_calls_hook(
        self, registry: TaskHookRegistry, sample_task: DotoTask
    ) -> None:
        """Test that fire_task_archived calls registered hooks."""
        called = []

        @registry.on_task_archived
        def my_hook(task: DotoTask) -> None:
            called.append(task.id)

        registry.fire_task_archived(sample_task)

        assert called == ["DOTO-001"]

    def test_fire_task_reopened_calls_hook(
        self, registry: TaskHookRegistry, sample_task: DotoTask
    ) -> None:
        """Test that fire_task_reopened calls registered hooks."""
        called = []

        @registry.on_task_reopened
        def my_hook(task: DotoTask) -> None:
            called.append(task.id)

        registry.fire_task_reopened(sample_task)

        assert called == ["DOTO-001"]

    def test_fire_conflict_calls_hook_with_conflicts(
        self, registry: TaskHookRegistry, sample_task: DotoTask
    ) -> None:
        """Test that fire_conflict passes task and conflicts list."""
        calls: list[tuple[str, list[Any]]] = []
        conflicts = [{"field": "status", "rst": "open", "json": "done"}]

        @registry.on_conflict
        def my_hook(task: DotoTask, conflict_list: list[Any]) -> None:
            calls.append((task.id, conflict_list))

        registry.fire_conflict(sample_task, conflicts)

        assert len(calls) == 1
        assert calls[0][0] == "DOTO-001"
        assert calls[0][1] is conflicts


class TestMultipleHooks:
    """Tests for multiple hooks registered to the same event."""

    def test_multiple_hooks_all_called(
        self, registry: TaskHookRegistry, sample_task: DotoTask
    ) -> None:
        """Test that all registered hooks are called."""
        call_order: list[str] = []

        @registry.on_task_created
        def hook_a(task: DotoTask) -> None:
            call_order.append("a")

        @registry.on_task_created
        def hook_b(task: DotoTask) -> None:
            call_order.append("b")

        @registry.on_task_created
        def hook_c(task: DotoTask) -> None:
            call_order.append("c")

        registry.fire_task_created(sample_task)

        assert call_order == ["a", "b", "c"]

    def test_hooks_called_in_registration_order(
        self, registry: TaskHookRegistry, sample_task: DotoTask
    ) -> None:
        """Test that hooks are called in the order they were registered."""
        call_order: list[int] = []

        for i in range(5):

            def make_hook(n: int):
                def hook(task: DotoTask) -> None:
                    call_order.append(n)

                return hook

            registry.on_task_updated(make_hook(i))

        registry.fire_task_updated(sample_task)

        assert call_order == [0, 1, 2, 3, 4]


class TestHookExceptionHandling:
    """Tests for exception handling in hooks."""

    def test_hook_exception_does_not_abort(
        self, registry: TaskHookRegistry, sample_task: DotoTask
    ) -> None:
        """Test that exceptions in hooks don't stop other hooks."""
        call_order: list[str] = []

        @registry.on_task_created
        def hook_before(task: DotoTask) -> None:
            call_order.append("before")

        @registry.on_task_created
        def hook_raises(task: DotoTask) -> None:
            call_order.append("raises")
            raise RuntimeError("Test exception")

        @registry.on_task_created
        def hook_after(task: DotoTask) -> None:
            call_order.append("after")

        # Should not raise
        registry.fire_task_created(sample_task)

        # All hooks should have been attempted
        assert call_order == ["before", "raises", "after"]

    def test_hook_exception_is_logged(
        self, registry: TaskHookRegistry, sample_task: DotoTask, caplog
    ) -> None:
        """Test that exceptions in hooks are logged."""

        @registry.on_task_created
        def failing_hook(task: DotoTask) -> None:
            raise ValueError("Something went wrong")

        with caplog.at_level(logging.WARNING):
            registry.fire_task_created(sample_task)

        assert "Exception in doto hook 'failing_hook'" in caplog.text
        assert "Something went wrong" in caplog.text

    def test_multiple_exceptions_all_logged(
        self, registry: TaskHookRegistry, sample_task: DotoTask, caplog
    ) -> None:
        """Test that multiple exceptions are all logged."""

        @registry.on_task_created
        def fail_1(task: DotoTask) -> None:
            raise ValueError("Error 1")

        @registry.on_task_created
        def fail_2(task: DotoTask) -> None:
            raise RuntimeError("Error 2")

        with caplog.at_level(logging.WARNING):
            registry.fire_task_created(sample_task)

        assert "Error 1" in caplog.text
        assert "Error 2" in caplog.text


class TestClear:
    """Tests for the clear() method."""

    def test_clear_removes_all_hooks(self, registry: TaskHookRegistry) -> None:
        """Test that clear() removes all registered hooks."""
        # Register hooks on all types
        registry.on_task_created(lambda t: None)
        registry.on_task_updated(lambda t: None)
        registry.on_status_changed(lambda t, o, n: None)
        registry.on_task_archived(lambda t: None)
        registry.on_task_reopened(lambda t: None)
        registry.on_conflict(lambda t, c: None)

        # Verify they're registered
        assert registry.hook_counts == {
            "on_task_created": 1,
            "on_task_updated": 1,
            "on_status_changed": 1,
            "on_task_archived": 1,
            "on_task_reopened": 1,
            "on_conflict": 1,
        }

        registry.clear()

        # Verify all cleared
        assert registry.hook_counts == {
            "on_task_created": 0,
            "on_task_updated": 0,
            "on_status_changed": 0,
            "on_task_archived": 0,
            "on_task_reopened": 0,
            "on_conflict": 0,
        }


class TestHookCounts:
    """Tests for the hook_counts property."""

    def test_hook_counts_returns_correct_counts(self, registry: TaskHookRegistry) -> None:
        """Test that hook_counts returns accurate counts."""
        registry.on_task_created(lambda t: None)
        registry.on_task_created(lambda t: None)
        registry.on_task_updated(lambda t: None)
        registry.on_status_changed(lambda t, o, n: None)
        registry.on_status_changed(lambda t, o, n: None)
        registry.on_status_changed(lambda t, o, n: None)

        counts = registry.hook_counts

        assert counts["on_task_created"] == 2
        assert counts["on_task_updated"] == 1
        assert counts["on_status_changed"] == 3
        assert counts["on_task_archived"] == 0
        assert counts["on_task_reopened"] == 0
        assert counts["on_conflict"] == 0


class TestGlobalSingleton:
    """Tests for the module-level task_hooks singleton."""

    def test_task_hooks_is_registry(self) -> None:
        """Test that task_hooks is a TaskHookRegistry instance."""
        assert isinstance(task_hooks, TaskHookRegistry)

    def test_global_hooks_can_be_registered(self, sample_task: DotoTask) -> None:
        """Test that hooks can be registered on the global singleton."""
        called = []

        @task_hooks.on_task_created
        def my_hook(task: DotoTask) -> None:
            called.append(task.id)

        task_hooks.fire_task_created(sample_task)

        assert called == ["DOTO-001"]

    def test_global_hooks_exported_from_main_module(self) -> None:
        """Test that task_hooks is exported from doxtr_doto."""
        from doxtr_doto import task_hooks as exported_hooks

        assert exported_hooks is task_hooks


class TestHooksIntegration:
    """Integration tests for hooks with sync and archive modules."""

    def test_hooks_importable_from_various_paths(self) -> None:
        """Test that hooks can be imported from expected paths."""
        from doxtr_doto import task_hooks as main_task_hooks
        from doxtr_doto.hooks import task_hooks

        assert task_hooks is main_task_hooks

    def test_hook_registry_usage_example(self, sample_task: DotoTask) -> None:
        """Test a realistic usage example of hooks."""
        # Simulating what a user might do in conf.py
        notifications: list[str] = []

        @task_hooks.on_task_created
        def notify_on_create(task: DotoTask) -> None:
            notifications.append(f"Created: {task.id} - {task.title}")

        @task_hooks.on_status_changed
        def notify_on_status_change(task: DotoTask, old_status: str, new_status: str) -> None:
            notifications.append(f"Status changed: {task.id} {old_status} -> {new_status}")

        @task_hooks.on_task_archived
        def notify_on_archive(task: DotoTask) -> None:
            notifications.append(f"Archived: {task.id}")

        # Simulate task lifecycle
        task_hooks.fire_task_created(sample_task)
        task_hooks.fire_status_changed(sample_task, "open", "in-progress")
        task_hooks.fire_status_changed(sample_task, "in-progress", "done")
        task_hooks.fire_task_archived(sample_task)

        assert notifications == [
            "Created: DOTO-001 - Test Task",
            "Status changed: DOTO-001 open -> in-progress",
            "Status changed: DOTO-001 in-progress -> done",
            "Archived: DOTO-001",
        ]


class TestNoHooksRegistered:
    """Tests for behavior when no hooks are registered."""

    def test_fire_with_no_hooks_does_not_error(
        self, registry: TaskHookRegistry, sample_task: DotoTask
    ) -> None:
        """Test that firing with no hooks registered is safe."""
        # Should not raise
        registry.fire_task_created(sample_task)
        registry.fire_task_updated(sample_task)
        registry.fire_status_changed(sample_task, "open", "done")
        registry.fire_task_archived(sample_task)
        registry.fire_task_reopened(sample_task)
        registry.fire_conflict(sample_task, [])


class TestHooksWithSphinxLogger:
    """Tests for Sphinx logger integration."""

    def test_uses_sphinx_logger_when_available(
        self, registry: TaskHookRegistry, sample_task: DotoTask
    ) -> None:
        """Test that Sphinx logger is used when available."""

        @registry.on_task_created
        def failing_hook(task: DotoTask) -> None:
            raise ValueError("Test error")

        # Mock the Sphinx logger
        with patch("doxtr_doto.hooks._get_logger") as mock_get_logger:
            mock_logger = MagicMock()
            mock_get_logger.return_value = mock_logger

            registry.fire_task_created(sample_task)

            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args
            assert "failing_hook" in call_args[0][0]
            assert "Test error" in call_args[0][0]
