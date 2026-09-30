"""Transform and utilities for auto-archiving doto tasks."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from sphinx.transforms import SphinxTransform

if TYPE_CHECKING:
    from sphinx.application import Sphinx
    from sphinx.environment import BuildEnvironment


class DotoArchiveTransform(SphinxTransform):
    """
    Transform to handle auto-archiving of completed tasks.
    
    When auto-archive is enabled:
    1. Tasks matching archive criteria are marked as archived
    2. Their directives are removed from RST files
    3. They are preserved in the JSON store
    4. They appear only on the archive page
    """
    
    # Run late, after sync
    default_priority = 900
    
    def apply(self) -> None:
        """Apply archive transform - marks tasks for archival."""
        # This transform runs per-document, but archiving is global
        # Actual archiving happens in the event handler
        pass
    
    @staticmethod
    def process_auto_archive(app: Sphinx, env: BuildEnvironment) -> None:
        """
        Process auto-archiving for all tasks.
        
        Called via env-check-consistency event.
        """
        from doxtr_doto.collectors import get_doto_env
        from doxtr_doto.config import get_config
        from doxtr_doto.hooks import task_hooks
        
        if not get_config(app, "auto_archive"):
            return
        
        doto_env = get_doto_env(env)
        archive_statuses = set(get_config(app, "archive_statuses"))
        archive_after_days = get_config(app, "archive_after_days")
        
        tasks_to_archive = []
        
        for task_id, task in doto_env.all_tasks.items():
            if task.archived:
                continue
            
            if should_archive(task, archive_statuses, archive_after_days):
                tasks_to_archive.append(task_id)
        
        # Mark tasks for archival
        for task_id in tasks_to_archive:
            task = doto_env.all_tasks[task_id]
            task.archived = True
            task.archived_on = datetime.now()
            
            # Fire the task archived hook
            task_hooks.fire_task_archived(task)
            
            # Schedule RST directive removal
            if task.docname:
                if task.docname not in doto_env.pending_rst_updates:
                    doto_env.pending_rst_updates[task.docname] = {}
                doto_env.pending_rst_updates[task.docname][task_id] = {
                    "action": "remove",
                    "task_id": task_id,
                }


def should_archive(
    task: Any,
    archive_statuses: set[str],
    archive_after_days: int,
) -> bool:
    """
    Determine if a task should be archived.
    
    Args:
        task: The DotoTask to check
        archive_statuses: Set of statuses that trigger archiving
        archive_after_days: Days after status change before archiving
    
    Returns:
        True if task should be archived
    """
    if task.status not in archive_statuses:
        return False
    
    if archive_after_days > 0 and task.updated:
        # Check if enough time has passed since status changed
        days_since = (datetime.now() - task.updated).days
        if days_since < archive_after_days:
            return False
    
    return True


def reopen_task(
    task_id: str,
    json_store: Any,
    target_file: str | None = None,
    new_status: str = "open",
    inbox_file: str = "tasks/inbox.rst",
) -> None:
    """
    Reopen an archived task.
    
    Args:
        task_id: The task ID to reopen
        json_store: JsonTaskStore instance
        target_file: Optional target RST file (uses original if not specified)
        new_status: Status to set (default: "open")
        inbox_file: Fallback file if original doesn't exist
    """
    from doxtr_doto.collectors import DotoTask
    from doxtr_doto.hooks import task_hooks
    
    task = json_store.get_task(task_id)
    if task is None:
        raise ValueError(f"Task {task_id} not found")
    
    if not task.get("archived"):
        raise ValueError(f"Task {task_id} is not archived")
    
    # Update task
    task["archived"] = False
    task["archived_on"] = None
    task["status"] = new_status
    task["updated"] = datetime.now().isoformat()
    
    # Set target file
    if target_file:
        task.setdefault("_sync", {})["rst_file"] = target_file
    elif not task.get("_sync", {}).get("rst_file"):
        task.setdefault("_sync", {})["rst_file"] = inbox_file
    
    # Clear snapshot to force write on next build
    if "_sync" in task:
        task["_sync"]["snapshot"] = None
        task["_sync"]["rst_hash"] = None
    
    json_store.update_task(task_id, task)
    
    # Fire the task reopened hook
    hook_task = DotoTask.from_dict(task_id, task)
    task_hooks.fire_task_reopened(hook_task)
