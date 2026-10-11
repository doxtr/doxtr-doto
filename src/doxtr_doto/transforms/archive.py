"""Transform and utilities for auto-archiving doto tasks."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sphinx.transforms import SphinxTransform
from sphinx.util import logging as sphinx_logging

from doxtr_doto.enums import SyncAction

if TYPE_CHECKING:
    from sphinx.application import Sphinx
    from sphinx.environment import BuildEnvironment

    from doxtr_doto.sync.json_store import JsonTaskStore
    from doxtr_doto.sync.restore import RestoreResult
    from doxtr_doto.types import DotoSyncData

logger = sphinx_logging.getLogger(__name__)


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

        Called via env-check-consistency event. For each task that should be
        archived this:

        1. Marks the in-memory task archived (so it drops off active lists).
        2. Captures a restore anchor from the task's RST file and persists it
           into the JSON store under ``_sync._archive`` so the directive can be
           restored to the same place on reopen.
        3. Queues a REMOVE RST update so the directive is removed from the
           source file in the same build (write_rst_updates on build-finished).
        """
        from doxtr_doto.collectors import get_doto_env
        from doxtr_doto.config import get_config
        from doxtr_doto.hooks import task_hooks
        from doxtr_doto.types import get_doto_sync_data

        if not get_config(app, "auto_archive"):
            return

        doto_env = get_doto_env(env)
        archive_statuses = set(get_config(app, "archive_statuses"))
        archive_after_days = get_config(app, "archive_after_days")

        sync_data = get_doto_sync_data(env)
        store = sync_data.get("json_store")

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

                # Capture a restore anchor and persist the archive state to
                # the JSON store, then queue the actual REMOVE so the
                # directive is stripped from the source RST in this build.
                _capture_and_queue_archive(app, env, store, sync_data, task, task_id)

        # Persist the archive-state updates to the JSON store. perform_
        # bidirectional_sync already saved the store before this runs, so the
        # archived flags and restore anchors added above would otherwise be
        # lost. Only save when we actually archived something.
        if tasks_to_archive and store is not None:
            store.save()


def _capture_and_queue_archive(
    app: Sphinx,
    env: BuildEnvironment,
    store: JsonTaskStore | None,
    sync_data: DotoSyncData,
    task: Any,
    task_id: str,
) -> None:
    """Capture a restore anchor and queue the RST removal for an archived task.

    Reads the task's source RST file, captures a positional restore anchor and
    the page title via
    :func:`doxtr_doto.sync.rst_writer.capture_restore_anchor`, persists that
    into the JSON store under ``_sync._archive``, and queues a REMOVE RST
    update so the directive is stripped from the source file in this build.

    Args:
        app: Sphinx application instance.
        env: Build environment.
        store: The JsonTaskStore for this build (may be None).
        sync_data: The sync data dict carrying the ``rst_updates`` queue.
        task: The in-memory DotoTask being archived.
        task_id: The task ID.
    """
    from doxtr_doto.sync.rst_writer import capture_restore_anchor

    docname = task.docname
    # Resolve the docname to a concrete source path to read for anchoring.
    try:
        rst_path = Path(env.doc2path(docname, base=True))
    except (KeyError, ValueError, TypeError):
        rst_path = Path(app.srcdir) / f"{docname}.rst"

    anchor: dict[str, Any] | None = None
    if rst_path.exists():
        try:
            content = rst_path.read_text(encoding="utf-8")
            anchor = capture_restore_anchor(content, task_id)
        except OSError:
            anchor = None
    if anchor is None:
        # Capture failed (file unreadable, or the directive could not be
        # located). Restore will still work via the top-of-page fallback, but
        # log it so a persistent failure is diagnosable rather than silent.
        logger.warning(
            "doto: could not capture restore anchor for %s in %s; "
            "reopen will fall back to top-of-page insertion",
            task_id,
            docname,
        )

    # Persist archive metadata to the JSON store so reopen can restore in place.
    if store is not None and store.get_task(task_id) is not None:
        archive_meta: dict[str, Any] = {"original_rst_file": docname}
        if anchor is not None:
            archive_meta.update(anchor)
        store.update_task(
            task_id,
            {
                "archived": True,
                "archived_on": (task.archived_on.isoformat() if task.archived_on else None),
                "_sync": {"_archive": archive_meta},
            },
        )

    # Queue the actual directive removal from the source RST file.
    sync_data["rst_updates"].append((SyncAction.REMOVE, docname, task_id, {"task_id": task_id}))


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
    srcdir: Path | str | None = None,
) -> RestoreResult | None:
    """
    Reopen an archived task, restoring its directive to the original place.

    When ``srcdir`` is provided and no explicit ``target_file`` override is
    given, the task's directive is re-inserted into its original RST file using
    the restore anchor captured at archive time (see
    :func:`doxtr_doto.sync.restore.restore_task_to_rst`). The task's archived
    flag is only cleared when the restore succeeds; if the original page was
    renamed/deleted the restore fails and the task is left archived so the
    caller can surface the retrace message.

    When ``srcdir`` is None (legacy build-time path), the behavior matches the
    original: the task is unarchived and its snapshot cleared so the directive
    is written back on the next build to the original file (or the inbox).

    Args:
        task_id: The task ID to reopen.
        json_store: JsonTaskStore instance.
        target_file: Optional target RST file (overrides original + anchor).
        new_status: Status to set (default: "open").
        inbox_file: Fallback file for the legacy path when no original exists.
        srcdir: Sphinx source directory. When given, enables restore-to-place.

    Returns:
        A :class:`doxtr_doto.sync.restore.RestoreResult` when ``srcdir`` is
        provided, else None (legacy behavior).

    Raises:
        ValueError: If the task is not found or is not archived.
    """
    from doxtr_doto.collectors import DotoTask
    from doxtr_doto.hooks import task_hooks

    task = json_store.get_task(task_id)
    if task is None:
        raise ValueError(f"Task {task_id} not found")

    if not task.get("archived"):
        raise ValueError(f"Task {task_id} is not archived")

    # Restore-to-place path: attempt the RST re-insertion first so a
    # renamed/deleted page leaves the task archived with a clear message.
    if srcdir is not None and not target_file:
        from doxtr_doto.sync.restore import restore_task_to_rst

        sync = task.get("_sync", {}) or {}
        has_restore_info = bool(sync.get("_archive") or sync.get("rst_file"))
        # Only attempt restore-to-place when the task actually has a recorded
        # origin; otherwise fall through to the legacy reopen (inbox default).
        if has_restore_info:
            # Build the restore input with the *reopen* status applied and the
            # archived flags cleared, so the re-inserted directive carries
            # ``:status: <reopen status>`` instead of the archived
            # ``:status: done`` (which the now-default auto-archive would
            # immediately re-archive on the next build).
            restore_input = dict(task)
            restore_input["id"] = task_id
            restore_input["status"] = new_status
            restore_input["archived"] = False
            restore_input["archived_on"] = None
            result = restore_task_to_rst(restore_input, srcdir)
            if not result.success:
                # Do NOT silently relocate; leave archived and report upstream.
                return result

            # Restore succeeded: clear archive state and point sync at the file
            # the directive now lives in so the next build does not duplicate it.
            task["archived"] = False
            task["archived_on"] = None
            task["status"] = new_status
            task["updated"] = datetime.now().isoformat()
            sync = task.setdefault("_sync", {})
            if result.rst_file:
                sync["rst_file"] = result.rst_file
            sync["snapshot"] = None
            sync["rst_hash"] = None
            sync.pop("_archive", None)
            json_store.update_task(task_id, task)

            hook_task = DotoTask.from_dict(task_id, task)
            task_hooks.fire_task_reopened(hook_task)
            return result

    # Legacy path (no srcdir, or explicit target override).
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
        task["_sync"].pop("_archive", None)

    json_store.update_task(task_id, task)

    # Fire the task reopened hook
    hook_task = DotoTask.from_dict(task_id, task)
    task_hooks.fire_task_reopened(hook_task)
    return None
