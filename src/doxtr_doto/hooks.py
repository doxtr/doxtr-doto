"""Task lifecycle hook system.

Hooks allow downstream code (other extensions, conf.py, plugins) to
react to doto task events without modifying the extension source.

Usage in conf.py:

    from doxtr_doto.hooks import task_hooks

    @task_hooks.on_task_created
    def notify_slack(task):
        ...

    @task_hooks.on_status_changed
    def log_transition(task, old_status, new_status):
        ...

All hooks are called synchronously in registration order. Exceptions
in hooks are caught and logged; they never abort the Sphinx build.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from doxtr_doto.collectors import DotoTask

__all__ = ["TaskHookRegistry", "task_hooks"]


# Type aliases for hook callbacks
OnTaskCreated = Callable[["DotoTask"], None]
OnTaskUpdated = Callable[["DotoTask"], None]
OnStatusChanged = Callable[["DotoTask", str, str], None]
OnTaskArchived = Callable[["DotoTask"], None]
OnTaskReopened = Callable[["DotoTask"], None]
OnConflictRaised = Callable[["DotoTask", list[Any]], None]


def _get_logger() -> logging.Logger | logging.LoggerAdapter[logging.Logger]:
    """Get logger, preferring Sphinx's logger if available."""
    try:
        from sphinx.util import logging as sphinx_logging

        return sphinx_logging.getLogger("doxtr_doto.hooks")
    except ImportError:
        return logging.getLogger("doxtr_doto.hooks")


@dataclass
class TaskHookRegistry:
    """Registry of all task lifecycle hooks.

    Each hook list contains callables registered by user code.
    Hooks are called synchronously in registration order.
    Exceptions in hooks are caught and logged; they never
    abort the build.

    Example usage::

        from doxtr_doto.hooks import task_hooks

        @task_hooks.on_task_created
        def my_hook(task):
            print(f"Task created: {task.id}")
    """

    _on_task_created: list[OnTaskCreated] = field(default_factory=list)
    _on_task_updated: list[OnTaskUpdated] = field(default_factory=list)
    _on_status_changed: list[OnStatusChanged] = field(default_factory=list)
    _on_task_archived: list[OnTaskArchived] = field(default_factory=list)
    _on_task_reopened: list[OnTaskReopened] = field(default_factory=list)
    _on_conflict: list[OnConflictRaised] = field(default_factory=list)

    # --- Registration decorators ---

    def on_task_created(self, fn: OnTaskCreated) -> OnTaskCreated:
        """Register a hook called when a task is first added to the store.

        The callback receives a single argument: the DotoTask that was created.

        Args:
            fn: Callback function accepting a DotoTask.

        Returns:
            The original function (allowing use as a decorator).
        """
        self._on_task_created.append(fn)
        return fn

    def on_task_updated(self, fn: OnTaskUpdated) -> OnTaskUpdated:
        """Register a hook called when any task field changes.

        The callback receives a single argument: the DotoTask after the update.

        Args:
            fn: Callback function accepting a DotoTask.

        Returns:
            The original function (allowing use as a decorator).
        """
        self._on_task_updated.append(fn)
        return fn

    def on_status_changed(self, fn: OnStatusChanged) -> OnStatusChanged:
        """Register a hook called when a task's status changes.

        The callback receives three arguments:
        - task: The DotoTask after the status change
        - old_status: The previous status string
        - new_status: The new status string

        Args:
            fn: Callback function accepting (task, old_status, new_status).

        Returns:
            The original function (allowing use as a decorator).
        """
        self._on_status_changed.append(fn)
        return fn

    def on_task_archived(self, fn: OnTaskArchived) -> OnTaskArchived:
        """Register a hook called when a task is archived.

        The callback receives a single argument: the DotoTask that was archived.

        Args:
            fn: Callback function accepting a DotoTask.

        Returns:
            The original function (allowing use as a decorator).
        """
        self._on_task_archived.append(fn)
        return fn

    def on_task_reopened(self, fn: OnTaskReopened) -> OnTaskReopened:
        """Register a hook called when a task is reopened from archive.

        The callback receives a single argument: the DotoTask that was reopened.

        Args:
            fn: Callback function accepting a DotoTask.

        Returns:
            The original function (allowing use as a decorator).
        """
        self._on_task_reopened.append(fn)
        return fn

    def on_conflict(self, fn: OnConflictRaised) -> OnConflictRaised:
        """Register a hook called when a merge conflict is detected.

        The callback receives two arguments:
        - task: The DotoTask involved in the conflict
        - conflicts: List of conflict information dictionaries

        Args:
            fn: Callback function accepting (task, conflicts).

        Returns:
            The original function (allowing use as a decorator).
        """
        self._on_conflict.append(fn)
        return fn

    # --- Dispatch methods (called internally) ---

    def fire_task_created(self, task: DotoTask) -> None:
        """Fire all registered on_task_created hooks.

        Args:
            task: The DotoTask that was created.
        """
        self._fire(self._on_task_created, task)

    def fire_task_updated(self, task: DotoTask) -> None:
        """Fire all registered on_task_updated hooks.

        Args:
            task: The DotoTask that was updated.
        """
        self._fire(self._on_task_updated, task)

    def fire_status_changed(self, task: DotoTask, old_status: str, new_status: str) -> None:
        """Fire all registered on_status_changed hooks.

        Args:
            task: The DotoTask after the status change.
            old_status: The previous status string.
            new_status: The new status string.
        """
        self._fire(self._on_status_changed, task, old_status, new_status)

    def fire_task_archived(self, task: DotoTask) -> None:
        """Fire all registered on_task_archived hooks.

        Args:
            task: The DotoTask that was archived.
        """
        self._fire(self._on_task_archived, task)

    def fire_task_reopened(self, task: DotoTask) -> None:
        """Fire all registered on_task_reopened hooks.

        Args:
            task: The DotoTask that was reopened.
        """
        self._fire(self._on_task_reopened, task)

    def fire_conflict(self, task: DotoTask, conflicts: list[Any]) -> None:
        """Fire all registered on_conflict hooks.

        Args:
            task: The DotoTask involved in the conflict.
            conflicts: List of conflict information.
        """
        self._fire(self._on_conflict, task, conflicts)

    def _fire(self, hooks: list[Callable[..., None]], *args: Any) -> None:
        """Fire all hooks in a list, catching and logging exceptions.

        Exceptions in hooks are caught and logged but never re-raised,
        ensuring hooks cannot abort a Sphinx build.

        Args:
            hooks: List of callback functions to invoke.
            *args: Arguments to pass to each callback.
        """
        logger = _get_logger()
        for hook in hooks:
            try:
                hook(*args)
            except Exception as exc:
                # Get the function name safely
                hook_name = getattr(hook, "__name__", repr(hook))
                logger.warning(
                    f"Exception in doto hook {hook_name!r}: {exc}",
                    exc_info=False,
                )

    def clear(self) -> None:
        """Clear all registered hooks.

        Primarily useful for testing to ensure hook state doesn't
        leak between tests.
        """
        self._on_task_created.clear()
        self._on_task_updated.clear()
        self._on_status_changed.clear()
        self._on_task_archived.clear()
        self._on_task_reopened.clear()
        self._on_conflict.clear()

    @property
    def hook_counts(self) -> dict[str, int]:
        """Return counts of registered hooks by type.

        Useful for debugging and testing.

        Returns:
            Dictionary mapping hook type names to counts.
        """
        return {
            "on_task_created": len(self._on_task_created),
            "on_task_updated": len(self._on_task_updated),
            "on_status_changed": len(self._on_status_changed),
            "on_task_archived": len(self._on_task_archived),
            "on_task_reopened": len(self._on_task_reopened),
            "on_conflict": len(self._on_conflict),
        }


# Module-level singleton
task_hooks = TaskHookRegistry()
