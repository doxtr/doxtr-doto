"""JSON task store for .doto/tasks.json operations."""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict, cast

from doxtr_doto.constants import DONE_STATUS

if TYPE_CHECKING:
    from doxtr_doto.sync.restore import RestoreResult


class ArchiveData(TypedDict, total=False):
    """Restore-anchor metadata captured when a task is archived.

    Persisted under ``_sync._archive`` so a reopened task can be restored to
    the same place in its original RST file.

    Attributes:
        version: Schema version of this ``_archive`` block. Lets the restore
            layer branch defensively as the capture format evolves; a
            missing/unknown version is treated as version 1 for back-compat.
        original_rst_file: The docname/path the directive was removed from.
        page_title: The document title / first heading of that page, used in
            the renamed/deleted error message.
        preceding_lines: The run of non-blank source lines immediately above
            the removed directive, used as the positional anchor.
        directive_line: 1-indexed header line the directive was on (diagnostic).
    """

    version: int
    original_rst_file: str | None
    page_title: str | None
    preceding_lines: list[str]
    directive_line: int


class SyncData(TypedDict, total=False):
    """Sync metadata for a task."""

    rst_file: str | None
    rst_line: int | None
    rst_hash: str | None
    snapshot: dict[str, Any] | None
    _archive: ArchiveData


class GitData(TypedDict, total=False):
    """Git metadata for a task."""

    commits: list[dict[str, Any]]


class WorkLog(TypedDict):
    """A single work session interval for a task.

    Attributes:
        started_at: ISO 8601 timestamp when the session started.
        stopped_at: ISO 8601 timestamp when the session stopped, or None
            if the session is still open.
    """

    started_at: str
    stopped_at: str | None


class TaskData(TypedDict, total=False):
    """Task data structure stored in JSON."""

    title: str
    assignee: str | None
    priority: str
    status: str
    due: str | None
    estimate: int | None
    tags: list[str]
    depends_on: list[str]
    body: str
    progress: int | None
    raci: dict[str, list[str]] | None
    created: str
    updated: str
    # ISO-8601 timestamp of when the task most recently transitioned *into*
    # the ``done`` status (stamped centrally by :meth:`_TaskRepository.update`;
    # see that method's "completion-timestamp" block). Cleared when the task
    # moves back out of ``done`` so re-completing re-stamps a fresh date.
    # Absent on tasks created before this field existed, which the TUI's
    # "recent done" filter treats as "always show" for backward compatibility
    # (see :func:`doxtr_doto.cli.tui.filtersort.filter_done_recent`).
    completed_at: str | None
    # Parent-task link: the task id of THIS task's parent in a parent/child
    # task hierarchy ("this task's parent is <id>"), or None / absent when the
    # task has no parent (a top-level task). Seeded to None in
    # :meth:`_TaskRepository.add` so freshly created tasks carry it explicitly.
    #
    # Deliberately distinct from ``depends_on`` (a *dependency* list - "this
    # task is blocked by those tasks", a different, many-to-many relation) and
    # from ``series_id`` (recurring-series membership). ``parent`` is a single
    # optional child->parent edge forming the task hierarchy.
    #
    # Cycle safety: callers must route parent assignments through
    # :func:`would_create_cycle` (which rejects self-parenting and any direct
    # or transitive A->B->...->A loop) before writing this field. The store's
    # :meth:`update` does not enforce acyclicity itself, so an absent check in
    # a future caller would be the bug - the guard lives at the call site.
    parent: str | None
    archived: bool
    archived_on: str | None
    worklogs: list[WorkLog]
    _sync: SyncData
    _git: GitData


class SeriesData(TypedDict, total=False):
    """Series data structure stored in JSON."""

    title_template: str
    pattern: dict[str, Any]
    start_date: str
    end_date: str
    task_ids: list[str]
    task_defaults: dict[str, Any]
    created: str
    updated: str


class _JsonStoreOptional(TypedDict, total=False):
    """Optional keys of :class:`JsonStoreData` (absent on a clean store)."""

    # Pending field-level sync conflicts, persisted so ``doto resolve`` can act
    # on them across invocations.
    _conflicts: list[dict[str, Any]]


class JsonStoreData(_JsonStoreOptional):
    """Root structure of tasks.json."""

    version: int
    updated: str
    tasks: dict[str, TaskData]
    series: dict[str, SeriesData]


# Current schema version
#
# Note: the ``completed_at`` task field (added for the TUI "recent done"
# filter) intentionally has NO schema migration/backfill here - unlike
# ``progress`` (v4), ``worklogs`` (v5), and ``estimate`` (v6). It relies on the
# filter's "missing completed_at = always keep" rule
# (:func:`doxtr_doto.cli.tui.filtersort.filter_done_recent`), so pre-existing
# done tasks stay visible without a backfill. This omission is deliberate, not
# a forgotten migration.
SCHEMA_VERSION = 6


def would_create_cycle(
    all_tasks: dict[str, TaskData],
    child_id: str,
    new_parent_id: str,
) -> bool:
    """Report whether parenting ``child_id`` under ``new_parent_id`` cycles.

    A pure guard for the ``parent`` task link (see :class:`TaskData`). The
    parent relation must stay acyclic: following ``parent`` edges from any task
    has to terminate at a top-level task (``parent`` None/absent), never loop.

    Rejects (returns True) when:

    * ``new_parent_id == child_id`` -- a task cannot be its own parent; and
    * ``new_parent_id`` is already a descendant of ``child_id`` -- i.e. walking
      the existing ``parent`` chain upward from ``new_parent_id`` reaches
      ``child_id`` (this covers both a direct ``A -> B -> A`` cycle and any
      deeper transitive ``A -> B -> C -> ... -> A`` loop).

    The walk is bounded by a visited set so a pre-existing (malformed) cycle in
    the stored data cannot spin forever; it simply stops and reports a cycle.
    A ``new_parent_id`` that is not present in ``all_tasks`` is treated as a
    valid (non-cycling) parent here -- existence is the caller's concern, this
    helper only answers the acyclicity question.

    Args:
        all_tasks: The full task map (id -> task data) to walk ``parent`` edges
            through.
        child_id: The task being (re)parented.
        new_parent_id: The candidate parent id.

    Returns:
        True if the assignment would create a self-loop or a cycle, else False.
    """
    if new_parent_id == child_id:
        return True
    # Walk up from the candidate parent via existing ``parent`` edges: if we
    # reach ``child_id`` the new edge would close a loop. The visited guard
    # stops a pre-existing malformed cycle from looping forever.
    seen: set[str] = set()
    current: str | None = new_parent_id
    while current is not None and current not in seen:
        if current == child_id:
            return True
        seen.add(current)
        task = all_tasks.get(current)
        if task is None:
            break
        current = task.get("parent")
    return False


def _cleanup_stale_tmp_files(path: Path) -> None:
    """Remove stale .tmp files from a previous crashed run.

    Only removes .tmp files that match our specific naming pattern to avoid
    deleting temp files from other tools.

    Args:
        path: Path to the main file (used to find directory and base name).
    """
    if not path.parent.exists():
        return
    # Only clean up temp files matching our specific pattern (e.g., tasks.json.tmp)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    if tmp_path.exists():
        try:
            tmp_path.unlink()
        except OSError:
            pass  # Ignore errors removing stale files


class _IdGenerator:
    """Generates unique task IDs.

    This helper class encapsulates ID generation logic, supporting both
    sequential and hash-based ID generation strategies.
    """

    def __init__(self, existing_ids: set[str]) -> None:
        """Initialize with existing IDs to avoid collisions.

        Args:
            existing_ids: Set of IDs already in use.
        """
        self._existing = existing_ids

    def sequential(self, prefix: str) -> str:
        """Generate a sequential ID with the given prefix.

        Args:
            prefix: ID prefix (e.g., 'DOTO').

        Returns:
            New unique ID in format PREFIX-NNN.
        """
        max_num = 0
        for tid in self._existing:
            if tid.startswith(prefix + "-"):
                try:
                    max_num = max(max_num, int(tid[len(prefix) + 1 :]))
                except ValueError:
                    pass
        return f"{prefix}-{max_num + 1:03d}"

    def hash_based(self, prefix: str) -> str:
        """Generate a hash-based unique ID.

        Args:
            prefix: ID prefix (e.g., 'DOTO').

        Returns:
            New unique ID in format PREFIX-XXXXXX.
        """
        base = f"{time.time()}-{os.getpid()}"
        h = hashlib.sha256(base.encode()).hexdigest()[:6]
        candidate = f"{prefix}-{h}"
        counter = 0
        while candidate in self._existing:
            counter += 1
            candidate = f"{prefix}-{h}{counter}"
        return candidate


class _TaskRepository:
    """CRUD operations on the tasks dict.

    This helper class encapsulates all task-related data operations,
    providing a clean separation of concerns from the main store class.
    """

    def __init__(self, tasks: dict[str, TaskData]) -> None:
        """Initialize with a reference to the tasks dictionary.

        Args:
            tasks: The tasks dictionary to operate on.
        """
        self._tasks = tasks

    def get(self, task_id: str) -> TaskData | None:
        """Get a task by ID.

        Args:
            task_id: The task identifier.

        Returns:
            Task data dict or None if not found.
        """
        return self._tasks.get(task_id)

    def get_all(self) -> dict[str, TaskData]:
        """Get all tasks.

        Returns:
            Dictionary of task ID to task data.
        """
        return self._tasks

    def add(self, task_id: str, task_data: dict[str, Any]) -> None:
        """Add a new task with defaults.

        Args:
            task_id: Task identifier.
            task_data: Task data dictionary.
        """
        now = datetime.now().isoformat()
        task_data.setdefault("title", "")
        task_data.setdefault("assignee", None)
        task_data.setdefault("priority", "medium")
        task_data.setdefault("status", "open")
        task_data.setdefault("due", None)
        task_data.setdefault("tags", [])
        task_data.setdefault("depends_on", [])
        task_data.setdefault("body", "")
        task_data.setdefault("created", now)
        task_data.setdefault("updated", now)
        task_data.setdefault("archived", False)
        task_data.setdefault("archived_on", None)
        task_data.setdefault("completed_at", None)
        task_data.setdefault("parent", None)
        task_data.setdefault("worklogs", [])
        task_data.setdefault(
            "_sync",
            {
                "rst_file": None,
                "rst_line": None,
                "rst_hash": None,
                "snapshot": None,
            },
        )
        # task_data has been populated with every required TaskData field via
        # the setdefault calls above, so narrow the user-supplied dict to
        # TaskData for storage.
        self._tasks[task_id] = cast("TaskData", task_data)

    def update(self, task_id: str, data: dict[str, Any]) -> bool:
        """Update a task's fields.

        Args:
            task_id: The task identifier.
            data: Dictionary of fields to update.

        Returns:
            True if task was updated, False if not found.
        """
        if task_id not in self._tasks:
            return False
        task = self._tasks[task_id]
        # ``key`` is a runtime-dynamic field name, so operate through a plain
        # mutable-mapping view (TaskData only permits literal keys).
        task_mut = cast("dict[str, Any]", task)
        # Completion-timestamp: this is the single chokepoint every write path
        # (CLI ``doto done``, TUI done/status cycle/set-status) funnels through
        # via ``store.update_task``, so stamping ``completed_at`` here covers
        # them all. The incoming ``data`` is a *partial* update, so we only act
        # when ``status`` is actually being written, comparing the new status
        # against the task's *current* status so unrelated field updates (and
        # redundant same-status writes) never disturb the timestamp.
        if "status" in data:
            old_status = task_mut.get("status")
            new_status = data["status"]
            if new_status == DONE_STATUS and (
                old_status != DONE_STATUS or not task_mut.get("completed_at")
            ):
                # Transitioned into done (or was done but never stamped, e.g. a
                # legacy task): record when it became done.
                task_mut["completed_at"] = datetime.now().isoformat()
            elif new_status != DONE_STATUS and old_status == DONE_STATUS:
                # Moved back out of done: clear the stamp so a later
                # re-completion records a fresh date.
                task_mut["completed_at"] = None
        for key, value in data.items():
            if key in ("_sync", "_git"):
                task_mut.setdefault(key, {}).update(value)
            else:
                task_mut[key] = value
        task_mut["updated"] = datetime.now().isoformat()
        return True

    def delete(self, task_id: str) -> bool:
        """Delete a task by ID.

        Args:
            task_id: The task identifier.

        Returns:
            True if task was deleted, False if not found.
        """
        if task_id in self._tasks:
            del self._tasks[task_id]
            return True
        return False

    def iter_active(self) -> Iterator[tuple[str, TaskData]]:
        """Iterate over non-archived tasks.

        Yields:
            Tuples of (task_id, task_data) for active tasks.
        """
        for tid, t in self._tasks.items():
            if not t.get("archived"):
                yield tid, t

    def iter_archived(self) -> Iterator[tuple[str, TaskData]]:
        """Iterate over archived tasks.

        Yields:
            Tuples of (task_id, task_data) for archived tasks.
        """
        for tid, t in self._tasks.items():
            if t.get("archived"):
                yield tid, t


class _SeriesRepository:
    """CRUD operations on the series dict.

    This helper class encapsulates all series-related data operations,
    providing a clean separation of concerns from the main store class.
    """

    def __init__(self, series: dict[str, SeriesData]) -> None:
        """Initialize with a reference to the series dictionary.

        Args:
            series: The series dictionary to operate on.
        """
        self._series = series

    def get(self, series_id: str) -> SeriesData | None:
        """Get a series by ID.

        Args:
            series_id: Series identifier.

        Returns:
            Series dictionary or None if not found.
        """
        return self._series.get(series_id)

    def get_all(self) -> dict[str, SeriesData]:
        """Get all series.

        Returns:
            Dictionary of series ID to series data.
        """
        return self._series

    def add(
        self,
        series_id: str,
        title_template: str,
        pattern: dict[str, Any],
        start_date: str,
        end_date: str,
        task_ids: list[str],
        task_defaults: dict[str, Any] | None = None,
    ) -> None:
        """Add a new series.

        Args:
            series_id: Series identifier.
            title_template: Title template with optional {date} placeholder.
            pattern: Recurrence pattern dictionary.
            start_date: First occurrence date (ISO format).
            end_date: Last occurrence date (ISO format).
            task_ids: List of task IDs in this series.
            task_defaults: Default values for tasks in this series.
        """
        now = datetime.now().isoformat()
        self._series[series_id] = {
            "title_template": title_template,
            "pattern": pattern,
            "start_date": start_date,
            "end_date": end_date,
            "task_ids": task_ids,
            "task_defaults": task_defaults or {},
            "created": now,
            "updated": now,
        }

    def update(self, series_id: str, updates: dict[str, Any]) -> bool:
        """Update a series.

        Args:
            series_id: Series identifier.
            updates: Fields to update.

        Returns:
            True if series was updated, False if not found.
        """
        if series_id not in self._series:
            return False
        series_mut = cast("dict[str, Any]", self._series[series_id])
        series_mut.update(updates)
        series_mut["updated"] = datetime.now().isoformat()
        return True

    def delete(self, series_id: str) -> bool:
        """Delete a series by ID.

        Args:
            series_id: Series identifier.

        Returns:
            True if series was deleted, False if not found.
        """
        if series_id in self._series:
            del self._series[series_id]
            return True
        return False

    def generate_id(self, prefix: str = "SER") -> str:
        """Generate a new series ID.

        Args:
            prefix: ID prefix.

        Returns:
            New unique series ID.
        """
        max_num = 0
        for sid in self._series:
            if sid.startswith(prefix + "-"):
                try:
                    max_num = max(max_num, int(sid[len(prefix) + 1 :]))
                except ValueError:
                    pass
        return f"{prefix}-{max_num + 1:03d}"


class JsonTaskStore:
    """Handler for .doto/tasks.json operations.

    Manages loading, saving, and CRUD operations on the JSON task store.
    The JSON file is the authoritative source of truth for all tasks.

    Attributes:
        path: Path to the tasks.json file.
        tasks: Dictionary of task_id -> task data.
        _data: Full JSON data including version and metadata.
    """

    VERSION = SCHEMA_VERSION  # Expose for external access

    def __init__(self, path: Path | str) -> None:
        """Initialize the JSON task store.

        Args:
            path: Path to the tasks.json file.
        """
        self.path = Path(path)
        self._data: JsonStoreData | None = None
        self._tasks_repo: _TaskRepository | None = None
        self._series_repo: _SeriesRepository | None = None

    def _ensure_loaded(self) -> None:
        """Ensure data is loaded before accessing repositories."""
        if self._data is None:
            self.load()

    @property
    def _repo(self) -> _TaskRepository:
        """Get the task repository, initializing if needed."""
        self._ensure_loaded()
        if self._tasks_repo is None:
            self._tasks_repo = _TaskRepository(self._data["tasks"])  # type: ignore[index]
        return self._tasks_repo

    @property
    def _serepo(self) -> _SeriesRepository:
        """Get the series repository, initializing if needed."""
        self._ensure_loaded()
        if self._series_repo is None:
            self._series_repo = _SeriesRepository(
                self._data.setdefault("series", {})  # type: ignore[union-attr]
            )
        return self._series_repo

    @property
    def data(self) -> JsonStoreData:
        """Get the data, loading if necessary (lazy loading)."""
        if self._data is None:
            self.load()
        return self._data  # type: ignore[return-value]

    @property
    def tasks(self) -> dict[str, TaskData]:
        """Get the tasks dictionary."""
        return self.data["tasks"]

    @property
    def version(self) -> int:
        """Get the schema version."""
        return self.data["version"]

    def load(self) -> None:
        """Load tasks from the JSON file.

        If the file doesn't exist, initializes with an empty store.
        Handles schema migration if needed.

        Reloading an already-loaded store rebinds the cached task/series
        repositories to the freshly loaded data. Without this the repositories
        would keep wrapping the previous ``_data`` dict, so reads/writes would
        operate on stale data while :meth:`save` persisted the new ``_data`` -
        silently dropping concurrent edits made through another store instance
        for the same path.
        """
        # Invalidate cached repository wrappers so they rebind to the data
        # loaded below (they lazily wrap ``self._data`` on next access).
        self._tasks_repo = None
        self._series_repo = None

        if not self.path.exists():
            self._data = {
                "version": SCHEMA_VERSION,
                "updated": datetime.now().isoformat(),
                "tasks": {},
                "series": {},
            }
            return

        with open(self.path, encoding="utf-8") as f:
            self._data = json.load(f)

        # Handle schema migration if needed
        if self._data.get("version", 1) < SCHEMA_VERSION:
            self._migrate_schema()

    def save(self) -> None:
        """Save tasks to the JSON file.

        Creates parent directories if they don't exist.
        Uses atomic write with backup for safety.
        Cleans up any stale .tmp files first.
        """
        if self._data is None:
            return

        # Update timestamp
        self._data["updated"] = datetime.now().isoformat()

        # Ensure parent directory exists
        self.path.parent.mkdir(parents=True, exist_ok=True)

        # Cleanup stale .tmp files before writing
        _cleanup_stale_tmp_files(self.path)

        # Atomic write: write to temp file, then rename
        temp_path = self.path.with_suffix(".json.tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False, default=str)
                f.write("\n")  # Trailing newline
            temp_path.replace(self.path)
        except Exception:
            # Clean up temp file on failure
            if temp_path.exists():
                temp_path.unlink()
            raise

    def exists(self) -> bool:
        """Check if the JSON file exists."""
        return self.path.exists()

    def get_task(self, task_id: str) -> TaskData | None:
        """Get a task by ID.

        Args:
            task_id: The task identifier.

        Returns:
            Task data dict or None if not found.
        """
        return self._repo.get(task_id)

    def get_all_tasks(self) -> dict[str, TaskData]:
        """Get all tasks.

        Returns:
            Dictionary of task ID to task data.
        """
        return self._repo.get_all()

    def add_task(self, task_id: str, task_data: dict[str, Any]) -> None:
        """Add a new task with defaults.

        Args:
            task_id: Task identifier.
            task_data: Task data dictionary.
        """
        self._repo.add(task_id, task_data)

    def update_task(self, task_id: str, data: dict[str, Any]) -> bool:
        """Update a task's fields.

        Args:
            task_id: The task identifier.
            data: Dictionary of fields to update.

        Returns:
            True if task was updated, False if not found.
        """
        return self._repo.update(task_id, data)

    def delete_task(self, task_id: str) -> bool:
        """Delete a task by ID, pruning dangling series and parent links.

        When the task belongs to a series, its id is also removed from that
        series' ``task_ids`` list so the series' occurrence count stays
        consistent (otherwise :meth:`get_tasks_in_series` would keep counting a
        now-deleted task). This runs on every delete path -- including the CLI
        ``doto delete`` verb and the TUI's single-entry delete -- so no caller
        has to prune the link itself.

        Symmetrically, any remaining task whose ``parent`` points at the
        deleted task has its ``parent`` cleared to ``None``. The ``parent``
        field stores the bare local id (what :func:`doxtr_doto.cli.tui.actions\
        .set_parent` writes), which is the same id form passed here, so a
        direct equality compare finds every orphaned child. This keeps the
        invariant that ``parent`` always points at a live task -- otherwise the
        detail pane would render ``Parent: <deleted-id>`` for a task that no
        longer exists.

        Args:
            task_id: The task identifier.

        Returns:
            True if task was deleted, False if not found.
        """
        task = self._repo.get(task_id)
        series_id = task.get("series_id") if task else None
        deleted = self._repo.delete(task_id)
        if deleted and isinstance(series_id, str) and series_id:
            series = self._serepo.get(series_id)
            if series is not None:
                task_ids = [tid for tid in series.get("task_ids", []) if tid != task_id]
                self._serepo.update(series_id, {"task_ids": task_ids})
        if deleted:
            for tid in list(self._repo.get_all()):
                child = self._repo.get(tid)
                if child is not None and child.get("parent") == task_id:
                    self._repo.update(tid, {"parent": None})
        return deleted

    def archive_task(self, task_id: str) -> bool:
        """Archive a task.

        Args:
            task_id: Task identifier.

        Returns:
            True if task was archived, False if not found.
        """
        task = self.get_task(task_id)
        if task is None:
            return False

        task["archived"] = True
        task["archived_on"] = datetime.now().isoformat()
        task["updated"] = datetime.now().isoformat()
        return True

    def reopen_task(
        self,
        task_id: str,
        status: str = "open",
        target_file: str | None = None,
        srcdir: Path | str | None = None,
    ) -> RestoreResult | bool:
        """Reopen an archived task, optionally restoring it in place.

        When ``srcdir`` is provided and no ``target_file`` override is given,
        the directive is re-inserted into its original RST file using the
        restore anchor captured at archive time (see
        :func:`doxtr_doto.sync.restore.restore_task_to_rst`). The archived flag
        is only cleared when the restore succeeds; a renamed/deleted original
        page leaves the task archived and returns a failing
        :class:`~doxtr_doto.sync.restore.RestoreResult` so the caller can
        surface the retrace message.

        Args:
            task_id: Task identifier.
            status: New status for the task.
            target_file: Target RST file (overrides original + anchor).
            srcdir: Sphinx source directory. When given, enables
                restore-to-place and the return value is a ``RestoreResult``.

        Returns:
            ``True``/``False`` in the legacy (no ``srcdir``) path; a
            ``RestoreResult`` when ``srcdir`` is provided.
        """
        task = self.get_task(task_id)
        if task is None:
            return False

        if not task.get("archived"):
            return False

        # Restore-to-place path.
        if srcdir is not None and not target_file:
            from doxtr_doto.sync.restore import restore_task_to_rst

            sync = task.get("_sync", {}) or {}
            has_restore_info = bool(sync.get("_archive") or sync.get("rst_file"))
            # Only attempt restore-to-place when we actually know where the
            # task came from. A task that was never on an RST page (e.g. a
            # CLI-created archived task) has no origin to restore to, so fall
            # through to the legacy reopen (writes to inbox on next build).
            if has_restore_info:
                # Build the restore input with the *reopen* status applied and
                # the archived flags cleared, so the re-inserted directive
                # carries ``:status: <reopen status>`` rather than the archived
                # ``:status: done``. Otherwise the now-default auto-archive
                # would immediately re-archive the task on the next build.
                restore_input = dict(task)
                restore_input["id"] = task_id
                restore_input["status"] = status
                restore_input["archived"] = False
                restore_input["archived_on"] = None
                result = restore_task_to_rst(restore_input, srcdir)
                if not result.success:
                    return result

                task["archived"] = False
                task["archived_on"] = None
                task["status"] = status
                if status != DONE_STATUS:
                    # Reopened out of done: drop the stale completion stamp so
                    # a later re-completion records a fresh date.
                    task["completed_at"] = None
                task["updated"] = datetime.now().isoformat()
                sync = task.setdefault("_sync", {})
                if result.rst_file:
                    sync["rst_file"] = result.rst_file
                sync["snapshot"] = None
                sync["rst_hash"] = None
                sync.pop("_archive", None)
                return result

        # Legacy path.
        task["archived"] = False
        task["archived_on"] = None
        task["status"] = status
        if status != DONE_STATUS:
            # Reopened out of done: drop the stale completion stamp so a later
            # re-completion records a fresh date.
            task["completed_at"] = None
        task["updated"] = datetime.now().isoformat()

        # Update target file if specified
        if target_file:
            if "_sync" not in task:
                task["_sync"] = {}
            task["_sync"]["rst_file"] = target_file

        # Clear snapshot to force RST write on next build
        if "_sync" in task:
            task["_sync"]["snapshot"] = None
            task["_sync"]["rst_hash"] = None
            task["_sync"].pop("_archive", None)

        return True

    def iter_tasks(
        self,
        include_archived: bool = False,
    ) -> Iterator[tuple[str, TaskData]]:
        """Iterate over tasks.

        Args:
            include_archived: Include archived tasks.

        Yields:
            Tuples of (task_id, task_data).
        """
        if include_archived:
            yield from self._repo.get_all().items()
        else:
            yield from self._repo.iter_active()

    def iter_active_tasks(self) -> Iterator[tuple[str, TaskData]]:
        """Iterate over non-archived tasks.

        Prefer this over iter_tasks(include_archived=False) for clarity.

        Yields:
            Tuples of (task_id, task_data) for active tasks.
        """
        yield from self._repo.iter_active()

    def iter_archived_tasks(self) -> Iterator[tuple[str, TaskData]]:
        """Iterate over archived tasks.

        Yields:
            Tuples of (task_id, task_data) for archived tasks.
        """
        yield from self._repo.iter_archived()

    def filter_tasks(
        self,
        assignee: str | list[str] | None = None,
        priority: str | list[str] | None = None,
        status: str | list[str] | None = None,
        tags: list[str] | None = None,
        due_before: str | None = None,
        due_after: str | None = None,
        include_archived: bool = False,
        sync_conflict: bool | None = None,
    ) -> list[dict[str, Any]]:
        """Filter tasks by criteria.

        Args:
            assignee: Filter by assignee(s).
            priority: Filter by priority/priorities.
            status: Filter by status(es).
            tags: Filter by tags (any match).
            due_before: Filter by due date before.
            due_after: Filter by due date after.
            include_archived: Include archived tasks.
            sync_conflict: When True, keep only tasks flagged with an unresolved
                calendar-sync conflict (``sync_conflict`` truthy). When False,
                keep only tasks without one. ``None`` (default) does not filter
                on the conflict flag.

        Returns:
            List of matching tasks with id included.
        """
        # Normalize filter values to lists
        if isinstance(assignee, str):
            assignee = [assignee]
        if isinstance(priority, str):
            priority = [priority]
        if isinstance(status, str):
            status = [status]

        results = []
        for task_id, task_data in self.iter_tasks(include_archived=include_archived):
            # Apply filters
            if assignee and task_data.get("assignee") not in assignee:
                continue
            if priority and task_data.get("priority") not in priority:
                continue
            if status and task_data.get("status") not in status:
                continue
            if tags:
                task_tags = task_data.get("tags", [])
                if not any(t in task_tags for t in tags):
                    continue
            if due_before:
                task_due = task_data.get("due")
                if not task_due or task_due > due_before:
                    continue
            if due_after:
                task_due = task_data.get("due")
                if not task_due or task_due < due_after:
                    continue
            if sync_conflict is not None:
                if bool(task_data.get("sync_conflict")) != sync_conflict:
                    continue

            # Include task with id
            result = {"id": task_id, **task_data}
            results.append(result)

        return results

    def generate_id(self, prefix: str = "DOTO", sequential: bool = True) -> str:
        """Generate a new task ID.

        Args:
            prefix: ID prefix.
            sequential: Use sequential numbering.

        Returns:
            New unique task ID.
        """
        gen = _IdGenerator(set(self.tasks.keys()))
        return gen.sequential(prefix) if sequential else gen.hash_based(prefix)

    def get_snapshot(self, task_id: str) -> dict[str, Any] | None:
        """Get the sync snapshot for a task.

        The snapshot represents the last synced state for 3-way merge.

        Args:
            task_id: The task identifier.

        Returns:
            Snapshot dict or None if no snapshot exists.
        """
        task = self.get_task(task_id)
        if task is None:
            return None
        return task.get("_sync", {}).get("snapshot")

    def update_snapshot(
        self,
        task_id: str,
        snapshot: dict[str, Any],
        rst_hash: str,
    ) -> bool:
        """Update the sync snapshot and hash for a task.

        Args:
            task_id: The task identifier.
            snapshot: The new snapshot state.
            rst_hash: The RST content hash.

        Returns:
            True if updated, False if task not found.
        """
        if task_id not in self.tasks:
            return False

        task = self.tasks[task_id]
        if "_sync" not in task:
            task["_sync"] = {}

        task["_sync"]["snapshot"] = snapshot
        task["_sync"]["rst_hash"] = rst_hash
        return True

    def get_rst_hash(self, task_id: str) -> str | None:
        """Get the stored RST hash for a task.

        Args:
            task_id: The task identifier.

        Returns:
            The hash string or None if not stored.
        """
        task = self.get_task(task_id)
        if task is None:
            return None
        return task.get("_sync", {}).get("rst_hash")

    def get_tasks_by_rst_file(self, rst_file: str) -> dict[str, TaskData]:
        """Get all tasks associated with a specific RST file.

        Args:
            rst_file: The RST file path (relative).

        Returns:
            Dictionary of task_id -> task data for tasks in that file.
        """
        return {
            task_id: task
            for task_id, task in self.tasks.items()
            if task.get("_sync", {}).get("rst_file") == rst_file
        }

    def get_active_tasks(self) -> dict[str, TaskData]:
        """Get all non-archived tasks.

        Returns:
            Dictionary of task_id -> task data for active tasks.
        """
        return dict(self._repo.iter_active())

    def get_archived_tasks(self) -> dict[str, TaskData]:
        """Get all archived tasks.

        Returns:
            Dictionary of task_id -> task data for archived tasks.
        """
        return dict(self._repo.iter_archived())

    # Series management methods

    def get_series(self, series_id: str) -> SeriesData | None:
        """Get a series by ID.

        Args:
            series_id: Series identifier.

        Returns:
            Series dictionary or None if not found.
        """
        return self._serepo.get(series_id)

    def get_all_series(self) -> dict[str, SeriesData]:
        """Get all series.

        Returns:
            Dictionary of series ID to series data.
        """
        return self._serepo.get_all()

    def add_series(
        self,
        series_id: str,
        title_template: str,
        pattern: dict[str, Any],
        start_date: str,
        end_date: str,
        task_ids: list[str],
        task_defaults: dict[str, Any] | None = None,
    ) -> None:
        """Add a new series.

        Args:
            series_id: Series identifier.
            title_template: Title template with optional {date} placeholder.
            pattern: Recurrence pattern dictionary.
            start_date: First occurrence date (ISO format).
            end_date: Last occurrence date (ISO format).
            task_ids: List of task IDs in this series.
            task_defaults: Default values for tasks in this series.
        """
        self._serepo.add(
            series_id,
            title_template=title_template,
            pattern=pattern,
            start_date=start_date,
            end_date=end_date,
            task_ids=task_ids,
            task_defaults=task_defaults,
        )

    def update_series(self, series_id: str, updates: dict[str, Any]) -> bool:
        """Update a series.

        Args:
            series_id: Series identifier.
            updates: Fields to update.

        Returns:
            True if series was updated, False if not found.
        """
        return self._serepo.update(series_id, updates)

    def delete_series(self, series_id: str, delete_tasks: bool = False) -> tuple[bool, list[str]]:
        """Delete a series.

        Args:
            series_id: Series identifier.
            delete_tasks: Also delete all tasks in the series.

        Returns:
            Tuple of (success, deleted_task_ids).
        """
        series = self._serepo.get(series_id)
        if series is None:
            return False, []

        deleted_tasks = []
        if delete_tasks:
            for task_id in series.get("task_ids", []):
                if self._repo.delete(task_id):
                    deleted_tasks.append(task_id)

        self._serepo.delete(series_id)
        return True, deleted_tasks

    def get_tasks_in_series(self, series_id: str) -> list[dict[str, Any]]:
        """Get all tasks in a series.

        Args:
            series_id: Series identifier.

        Returns:
            List of tasks with id included, sorted by due date.
        """
        series = self.get_series(series_id)
        if series is None:
            return []

        tasks = []
        for task_id in series.get("task_ids", []):
            task = self.get_task(task_id)
            if task:
                tasks.append({"id": task_id, **task})

        # Sort by due date
        tasks.sort(key=lambda t: str(t.get("due") or ""))
        return tasks

    def generate_series_id(self, prefix: str = "SER") -> str:
        """Generate a new series ID.

        Args:
            prefix: ID prefix.

        Returns:
            New unique series ID.
        """
        return self._serepo.generate_id(prefix)

    def _migrate_schema(self) -> None:
        """Migrate data from older schema versions to current."""
        if self._data is None:
            return

        version = self._data.get("version", 1)

        if version < 2:
            # Migration from v1 to v2:
            # - Add _sync field to all tasks
            # - Ensure archived/archived_on fields exist
            for task in self._data.get("tasks", {}).values():
                if "_sync" not in task:
                    task["_sync"] = {
                        "rst_file": None,
                        "rst_line": None,
                        "rst_hash": None,
                        "snapshot": None,
                    }
                if "archived" not in task:
                    task["archived"] = False
                if "archived_on" not in task:
                    task["archived_on"] = None

            self._data["version"] = 2
            version = 2

        if version < 3:
            # Migration from v2 to v3:
            # - Add series support
            if "series" not in self._data:
                self._data["series"] = {}

            self._data["version"] = 3
            version = 3

        if version < 4:
            # Migration from v3 to v4:
            # - Add progress field to all tasks
            for task in self._data.get("tasks", {}).values():
                task.setdefault("progress", None)

            self._data["version"] = 4
            version = 4

        if version < 5:
            # Migration from v4 to v5:
            # - Add worklogs field (session time tracking) to all tasks
            for task in self._data.get("tasks", {}).values():
                task.setdefault("worklogs", [])

            self._data["version"] = 5
            version = 5

        if version < 6:
            # Migration from v5 to v6:
            # - Add estimate field (expected duration in whole minutes) to all
            #   tasks; None means "no estimate set".
            for task in self._data.get("tasks", {}).values():
                task.setdefault("estimate", None)

            self._data["version"] = 6
