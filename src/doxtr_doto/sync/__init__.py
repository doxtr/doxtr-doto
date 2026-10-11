"""Bidirectional sync module for doto.

This module implements the bidirectional synchronization between RST files
and the JSON task store (.doto/tasks.json). The JSON file is the authoritative
source of truth, with Sphinx builds performing 3-way merge to reconcile changes
from both RST edits and CLI operations.

Key components:
- JsonTaskStore: CRUD operations on .doto/tasks.json
- sync_task: 3-way merge algorithm for individual tasks
- compute_rst_hash: Change detection via content hashing
- RST writer: Surgical modification of RST files
- Conflict detection and reporting

Usage in Sphinx build:
    1. perform_bidirectional_sync() runs on env-check-consistency event
    2. Parses RST files, loads JSON store, performs 3-way merge
    3. Detects and reports conflicts
    4. write_rst_updates() runs on build-finished to update RST files
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from doxtr_doto.collectors import get_doto_env
from doxtr_doto.config import get_config
from doxtr_doto.enums import ConflictResolution, SyncAction
from doxtr_doto.exceptions import DotoRstWriteError
from doxtr_doto.fields import MERGE_FIELDS
from doxtr_doto.types import DotoSyncData, get_doto_sync_data
from doxtr_doto.utils import validate_path_within

from .conflict import ConflictError, FieldConflict, format_conflict_error
from .hash import compute_rst_hash, normalize_rst_directive
from .json_store import SCHEMA_VERSION, JsonTaskStore
from .merge import MergeResult, create_snapshot, sync_task
from .rst_writer import (
    _atomic_write,
    generate_directive_text,
    insert_directive_into_content,
    insert_doto_directive,
    insert_id_into_directive_at_line,
    remove_directive_from_content,
    remove_doto_directive,
    render_directive_text,
    update_directive_in_content,
    update_doto_directive,
)

if TYPE_CHECKING:
    from sphinx.application import Sphinx
    from sphinx.environment import BuildEnvironment

__all__ = [
    # Main sync functions
    "perform_bidirectional_sync",
    "write_rst_updates",
    # JSON store
    "JsonTaskStore",
    "SCHEMA_VERSION",
    # Hash functions
    "compute_rst_hash",
    "normalize_rst_directive",
    # Merge algorithm
    "MergeResult",
    "MERGE_FIELDS",
    "sync_task",
    "create_snapshot",
    # Conflict handling
    "ConflictError",
    "FieldConflict",
    "format_conflict_error",
    # RST writer
    "generate_directive_text",
    "insert_doto_directive",
    "remove_doto_directive",
    "update_doto_directive",
]


def _serialize_value(v: Any) -> Any:
    """Make a conflict value JSON-serializable.

    Converts date/datetime objects to ISO format strings and handles
    other types appropriately for JSON serialization.

    Args:
        v: Value to serialize (can be any type).

    Returns:
        JSON-serializable version of the value.
    """
    if hasattr(v, "isoformat"):  # date / datetime
        return v.isoformat()
    if isinstance(v, (list, dict, str, int, float, bool)) or v is None:
        return v
    return str(v)


def _load_or_create_json_store(
    app: Sphinx,
    json_path: Path,
) -> JsonTaskStore | None:
    """Load JSON store or create if auto_create enabled.

    Args:
        app: Sphinx application instance.
        json_path: Path to the JSON store file.

    Returns:
        Loaded JsonTaskStore instance, or None if file doesn't exist
        and auto_create is disabled.
    """
    store = JsonTaskStore(json_path)

    if json_path.exists():
        store.load()
        return store
    elif get_config(app, "auto_create_json"):
        store.save()
        return store
    else:
        return None


def _setup_sync_data(
    env: BuildEnvironment,
    store: JsonTaskStore,
) -> DotoSyncData:
    """Initialize sync data storage on environment.

    Args:
        env: Sphinx BuildEnvironment.
        store: JsonTaskStore instance to store reference to.

    Returns:
        The sync_data dictionary for further modifications.
    """
    sync_data = get_doto_sync_data(env)
    sync_data["json_store"] = store
    sync_data["rst_updates"] = []
    return sync_data


def _collect_rst_tasks(env: BuildEnvironment) -> dict[str, dict[str, Any]]:
    """Collect all tasks from parsed RST files.

    Args:
        env: Sphinx BuildEnvironment containing parsed task data.

    Returns:
        Dictionary mapping task IDs to task data dictionaries.
    """
    doto_env = get_doto_env(env)
    return {task_id: task.to_sync_dict() for task_id, task in doto_env.all_tasks.items()}


def _get_rst_location(
    rst_current: dict[str, Any] | None,
    json_task: Mapping[str, Any] | None,
) -> tuple[str | None, int | None]:
    """Extract RST file location from task data.

    Args:
        rst_current: Task data from RST source, or None.
        json_task: Task data from JSON store, or None.

    Returns:
        Tuple of (rst_file, rst_line), either may be None.
    """
    if rst_current:
        return rst_current.get("_rst_file"), rst_current.get("_rst_line")
    elif json_task:
        sync = json_task.get("_sync", {})
        return sync.get("rst_file"), sync.get("rst_line")
    return None, None


def _apply_merge_result(
    result: MergeResult,
    task_id: str,
    store: JsonTaskStore,
    app: Sphinx,
    rst_file: str | None,
    rst_line: int | None,
    rst_current: dict[str, Any] | None,
    sync_data: DotoSyncData,
) -> None:
    """Apply the results of a successful merge.

    Updates the JSON store and queues RST updates as needed based
    on the merge result flags. Also fires lifecycle hooks for task
    creation, updates, and status changes.

    Args:
        result: MergeResult from sync_task().
        task_id: ID of the task being merged.
        store: JsonTaskStore instance.
        app: Sphinx application instance.
        rst_file: RST file path, or None.
        rst_line: Line number in RST file, or None.
        rst_current: Current RST task data, or None.
        sync_data: Sync data dictionary for queueing RST updates.
    """
    from doxtr_doto.collectors import DotoTask
    from doxtr_doto.hooks import task_hooks

    if result.merged is None:
        return

    # Track old status for status change hook
    old_status = None
    if result.update_json:
        existing_task = store.get_task(task_id)
        if existing_task:
            old_status = existing_task.get("status")

    if result.create_in_json:
        # update_task only updates existing tasks (returns False if missing),
        # so create the task first when it is new (e.g. an RST-only directive
        # with an auto-generated {docname}-L{lineno} ID). Otherwise RST-only
        # tasks would never be persisted to tasks.json.
        if store.get_task(task_id) is None:
            # Copy is NECESSARY: add_task stores the dict by reference and
            # seeds defaults (including an all-null _sync) in place, so
            # without the copy result.merged would be mutated and later
            # observed by the created hook / snapshot below.
            new_task = dict(result.merged)
            if rst_file:
                # Seed _sync here so the create is a single write; add_task
                # only setdefault()s _sync, so this value is preserved. The
                # remaining keys match add_task's all-null _sync defaults.
                new_task["_sync"] = {
                    "rst_file": rst_file,
                    "rst_line": rst_line,
                    "rst_hash": None,
                    "snapshot": None,
                }
            store.add_task(task_id, new_task)
        else:
            store.update_task(task_id, result.merged)
            if rst_file:
                store.update_task(
                    task_id,
                    {
                        "_sync": {
                            "rst_file": rst_file,
                            "rst_line": rst_line,
                        }
                    },
                )
        # Fire task created hook
        hook_task = DotoTask.from_dict(task_id, result.merged)
        task_hooks.fire_task_created(hook_task)

        # Write-back: if this RST-only task used an auto-generated ID (no
        # explicit :id: in the directive), queue an INSERT_ID update so the
        # generated :id: is written into the existing directive. This makes
        # the ID stable so future builds reuse it instead of regenerating a
        # new {docname}-L{lineno} ID (which would orphan this JSON task and
        # recreate it).
        if (
            rst_current is not None
            and rst_current.get("_id_autogenerated", False)
            and rst_file
            and rst_line is not None
        ):
            sync_data["rst_updates"].append(
                (
                    SyncAction.INSERT_ID,
                    rst_file,
                    task_id,
                    {"_rst_line": rst_line},
                )
            )

    if result.update_json:
        store.update_task(task_id, result.merged)
        # Fire task updated hook
        hook_task = DotoTask.from_dict(task_id, result.merged)
        task_hooks.fire_task_updated(hook_task)
        # Fire status changed hook if status actually changed
        new_status = result.merged.get("status")
        if old_status and new_status and old_status != new_status:
            task_hooks.fire_status_changed(hook_task, old_status, new_status)

    if result.update_snapshot:
        snapshot = create_snapshot(result.merged)
        rst_content = _reconstruct_directive_content(rst_current) if rst_current else ""
        rst_hash = compute_rst_hash(rst_content) if rst_content else None
        store.update_snapshot(task_id, snapshot, rst_hash or "")

    if result.write_rst or result.create_in_rst:
        _queue_rst_update(result, task_id, rst_file, rst_line, app, sync_data)


def _queue_rst_update(
    result: MergeResult,
    task_id: str,
    rst_file: str | None,
    rst_line: int | None,
    app: Sphinx,
    sync_data: DotoSyncData,
) -> None:
    """Queue an RST file update for after build completes.

    Args:
        result: MergeResult containing merged task data.
        task_id: ID of the task being updated.
        rst_file: Target RST file path, or None to use inbox.
        rst_line: 1-indexed line of the directive in the RST file, or None.
            Carried as ``_rst_line`` so an UPDATE can locate a *bare*
            directive (one with no ``:id:`` option) by line number and inject
            the ``:id:`` while updating.
        app: Sphinx application instance.
        sync_data: Sync data dictionary containing rst_updates list.
    """
    action = SyncAction.CREATE if result.create_in_rst else SyncAction.UPDATE
    target_file = rst_file or get_config(app, "inbox_file")

    merged_with_id = dict(result.merged or {})
    merged_with_id["id"] = task_id
    if rst_line is not None:
        merged_with_id["_rst_line"] = rst_line

    sync_data["rst_updates"].append((action, target_file, task_id, merged_with_id))


def _merge_all_tasks(
    all_task_ids: set[str],
    rst_tasks: dict[str, dict[str, Any]],
    store: JsonTaskStore,
    app: Sphinx,
    sync_data: DotoSyncData,
) -> list[FieldConflict]:
    """Perform 3-way merge for all tasks.

    Args:
        all_task_ids: Set of all task IDs from both RST and JSON.
        rst_tasks: Task data from RST files.
        store: JsonTaskStore instance.
        app: Sphinx application instance.
        sync_data: Sync data dictionary for queueing updates.

    Returns:
        List of FieldConflict objects for any unresolved conflicts.
    """
    conflicts: list[FieldConflict] = []

    for task_id in all_task_ids:
        rst_current = rst_tasks.get(task_id)
        json_task = store.get_task(task_id)

        rst_file, rst_line = _get_rst_location(rst_current, json_task)

        result = sync_task(
            task_id=task_id,
            rst_current=rst_current,
            json_task=json_task,
            rst_file=rst_file,
            rst_line=rst_line,
        )

        if result.has_conflicts:
            conflicts.extend(result.conflicts)
            continue

        if result.merged is None:
            continue

        _apply_merge_result(result, task_id, store, app, rst_file, rst_line, rst_current, sync_data)

    return conflicts


def _handle_conflicts(
    conflicts: list[FieldConflict],
    store: JsonTaskStore,
    env: BuildEnvironment,
    app: Sphinx,
) -> None:
    """Handle detected merge conflicts based on configuration.

    Persists conflicts to JSON store for CLI resolution, then takes
    action based on the conflict_action configuration setting.
    Also fires the on_conflict hook for each conflict.

    Args:
        conflicts: List of FieldConflict objects to handle.
        store: JsonTaskStore instance.
        env: Sphinx BuildEnvironment.
        app: Sphinx application instance.

    Raises:
        ConflictError: If conflict_action is 'error'.
    """
    from doxtr_doto.collectors import DotoTask
    from doxtr_doto.hooks import task_hooks

    # Fire conflict hooks for each unique task
    tasks_with_conflicts: dict[str, list[FieldConflict]] = {}
    for conflict in conflicts:
        if conflict.task_id not in tasks_with_conflicts:
            tasks_with_conflicts[conflict.task_id] = []
        tasks_with_conflicts[conflict.task_id].append(conflict)

    for task_id, task_conflicts in tasks_with_conflicts.items():
        task_data = store.get_task(task_id)
        if task_data:
            hook_task = DotoTask.from_dict(task_id, task_data)
            # Convert FieldConflict objects to serializable dicts for the hook
            conflict_info = [
                {
                    "field": c.field,
                    "base": _serialize_value(c.base),
                    "rst": _serialize_value(c.rst),
                    "json": _serialize_value(c.json),
                    "rst_file": c.rst_file,
                }
                for c in task_conflicts
            ]
            task_hooks.fire_conflict(hook_task, conflict_info)

    # Persist conflicts so `doto resolve` can read them
    serialized = [
        {
            "task_id": c.task_id,
            "field": c.field,
            "base": _serialize_value(c.base),
            "rst": _serialize_value(c.rst),
            "json": _serialize_value(c.json),
            "rst_file": c.rst_file,
        }
        for c in conflicts
    ]
    store.data["_conflicts"] = serialized
    store.save()  # Write before potentially raising

    conflict_action = get_config(app, "conflict_action")
    error_msg = format_conflict_error(conflicts)

    if conflict_action == ConflictResolution.ERROR:
        raise ConflictError(conflicts, error_msg)
    elif conflict_action == ConflictResolution.WARN:
        from sphinx.util import logging

        logger = logging.getLogger(__name__)
        logger.warning(error_msg)
    elif conflict_action == ConflictResolution.PREFER_RST:
        _resolve_conflicts_prefer_rst(store, conflicts, env)
    elif conflict_action == ConflictResolution.PREFER_JSON:
        _resolve_conflicts_prefer_json(store, conflicts, env)


def perform_bidirectional_sync(
    app: Sphinx,
    env: BuildEnvironment,
) -> None:
    """Perform bidirectional sync between RST files and JSON store.

    This is the main sync entry point, connected to the env-check-consistency
    event with priority 100 (runs before archive processing).

    The function orchestrates the sync process by delegating to focused
    helper functions for each step.

    Algorithm:
        1. Load .doto/tasks.json (create if auto_create_json is enabled)
        2. Collect all tasks from parsed RST files in env.doto_data
        3. For each task in JSON ∪ RST, run 3-way merge
        4. If conflicts: emit errors based on conflict_action config
        5. Queue RST updates for write_rst_updates()

    Args:
        app: Sphinx application instance.
        env: Build environment with parsed RST data.

    Raises:
        ConflictError: If conflicts are detected and conflict_action is 'error'.
    """
    # Check if sync is enabled
    if not get_config(app, "sync_on_build"):
        return

    # Load or create JSON store
    json_file = get_config(app, "json_file")
    json_path = Path(app.srcdir) / json_file

    store = _load_or_create_json_store(app, json_path)
    if store is None:
        return

    # Initialize sync data on environment
    sync_data = _setup_sync_data(env, store)

    # Collect tasks from RST files
    rst_tasks = _collect_rst_tasks(env)

    # Get all task IDs from both sources
    all_task_ids = set(rst_tasks.keys()) | set(store.tasks.keys())

    # Perform 3-way merge for all tasks
    conflicts = _merge_all_tasks(all_task_ids, rst_tasks, store, app, sync_data)

    # Handle any conflicts
    if conflicts:
        _handle_conflicts(conflicts, store, env, app)
    else:
        # Clear stale conflicts on clean sync
        store.data.pop("_conflicts", None)

    # Save JSON store
    store.save()


def write_rst_updates(app: Sphinx, exception: Exception | None) -> None:
    """Write queued RST updates after build completes.

    Connected to build-finished event. Only writes if build succeeded.
    Processes all queued RST updates (create, update, remove) batched by file
    for efficiency - each file is read and written exactly once.

    Args:
        app: Sphinx application instance.
        exception: Exception if build failed, None otherwise. If an exception
            is present, no RST updates are written to avoid partial state.
    """
    if exception is not None:
        # Build failed - don't write RST updates
        return

    env = app.env
    if env is None:
        return

    sync_data = get_doto_sync_data(env)
    rst_updates = sync_data.get("rst_updates", [])
    if not rst_updates:
        return

    from collections import defaultdict

    from sphinx.util import logging

    logger = logging.getLogger(__name__)

    # Group updates by file: {rst_file: [(action, task_id, task_data), ...]}
    by_file: dict[str, list[tuple[str, str, dict[str, Any]]]] = defaultdict(list)
    for action, rst_file, task_id, task_data in rst_updates:
        by_file[rst_file].append((action, task_id, task_data))

    # Process each file's updates in a single read/write cycle
    for rst_file, file_updates in by_file.items():
        _process_file_updates(app, rst_file, file_updates, logger)


def _process_file_updates(
    app: Sphinx,
    rst_file: str,
    updates: list[tuple[str, str, dict[str, Any]]],
    logger: Any,
) -> None:
    """Apply all queued updates for one RST file in a single read/write.

    Args:
        app: Sphinx application instance.
        rst_file: Relative path to the RST file.
        updates: List of (action, task_id, task_data) tuples for this file.
        logger: Logger instance for status messages.
    """
    # Validate path is within source directory to prevent traversal attacks
    try:
        rst_path = validate_path_within(rst_file, app.srcdir)
    except ValueError as e:
        logger.error(f"doto: Security error - {e}")
        return

    # The sync layer records rst_file as a docname (no extension). If the raw
    # path does not exist, resolve the docname to its real source file via
    # Sphinx's doc2path so write-backs land in the actual .rst file.
    if not rst_path.exists() and app.env is not None:
        try:
            resolved = Path(app.env.doc2path(rst_file, base=True))
        except (KeyError, ValueError, TypeError):
            logger.debug(
                f"doto: could not resolve docname {rst_file!r} via doc2path; "
                f"falling back to unresolved path {rst_path}"
            )
            resolved = None
        if resolved is not None and resolved.exists():
            try:
                rst_path = validate_path_within(str(resolved.relative_to(app.srcdir)), app.srcdir)
            except ValueError as e:
                logger.error(f"doto: Security error - {e}")
                return

    # Read once
    try:
        if rst_path.exists():
            content = rst_path.read_text(encoding="utf-8")
        else:
            content = ""
    except (OSError, UnicodeDecodeError) as e:
        logger.error(f"doto: Cannot read {rst_file}: {e}")
        return

    # Apply all updates to the in-memory content.
    #
    # Ordering matters: each update is applied to the running ``modified``
    # buffer, but the line numbers (``_rst_line``) carried by UPDATE and
    # INSERT_ID were computed against the ORIGINAL file. Any edit that changes
    # the line count (injecting an ``:id:`` option, adding a new option, or
    # inserting an id) shifts every directive *below* it, invalidating the
    # stale line numbers of later updates and causing wrong-directive matches
    # (e.g. a duplicate ``:id:`` or a consumed blank line between directives).
    #
    # Applying line-based updates bottom-to-top (descending ``_rst_line``)
    # avoids this: editing a lower directive never shifts the line numbers of
    # the directives above it, so each remaining stale line number is still
    # correct when its update runs. Updates without a line number (CREATE,
    # REMOVE, or UPDATE matched purely by id) are applied first, in their
    # original order, since they don't depend on a stable line mapping.
    def _sort_key(
        indexed_update: tuple[int, tuple[str, str, dict[str, Any]]],
    ) -> tuple[int, int, int]:
        index, (_action, _task_id, task_data) = indexed_update
        line = task_data.get("_rst_line")
        if line is None:
            # No line dependency: keep before line-based edits, stable order.
            return (0, 0, index)
        # Line-based edits: apply in descending line order (bottom-to-top).
        return (1, -int(line), index)

    ordered = [u for _i, u in sorted(enumerate(updates), key=_sort_key)]

    modified = content
    for action, task_id, task_data in ordered:
        try:
            modified = _apply_update_to_content(modified, action, task_id, task_data)
            logger.info(f"doto: {action} task {task_id} in {rst_file}")
        except Exception as e:
            logger.error(f"doto: Error {action}ing task {task_id} in {rst_file}: {e}")
            # Continue processing other updates - don't let one failure block others

    # Write once if content changed
    if modified != content:
        try:
            # Ensure parent directory exists for new files
            rst_path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(rst_path, modified)
        except Exception as e:
            logger.error(f"doto: Failed to write {rst_file}: {e}")


def _apply_update_to_content(
    content: str,
    action: str,
    task_id: str,
    task_data: dict[str, Any],
) -> str:
    """Apply a single update action to in-memory content.

    Args:
        content: Current file content.
        action: Action type (SyncAction enum or string).
        task_id: ID of the task being modified.
        task_data: Task data dictionary (for create/update actions).

    Returns:
        Modified content string.
    """
    if action == SyncAction.CREATE:
        return insert_directive_into_content(content, task_data)
    elif action == SyncAction.UPDATE:
        return update_directive_in_content(
            content, task_id, task_data, rst_line=task_data.get("_rst_line")
        )
    elif action == SyncAction.INSERT_ID:
        lineno = task_data.get("_rst_line")
        if lineno is None:
            return content
        return insert_id_into_directive_at_line(content, lineno, task_id)
    elif action == SyncAction.REMOVE:
        return remove_directive_from_content(content, task_id)
    else:
        # Unknown action - return content unchanged
        return content


# Legacy function kept for backward compatibility
def _process_single_rst_update(
    app: Sphinx,
    action: str,
    rst_file: str,
    task_id: str,
    task_data: dict[str, Any],
    logger: Any,
) -> None:
    """Process a single RST update action.

    Args:
        app: Sphinx application instance.
        action: Action type ('create', 'update', or 'remove').
        rst_file: Relative path to the RST file.
        task_id: ID of the task being modified.
        task_data: Task data dictionary (for create/update actions).
        logger: Logger instance for status messages.
    """
    # Validate path is within source directory to prevent traversal attacks
    try:
        rst_path = validate_path_within(rst_file, app.srcdir)
    except ValueError as e:
        logger.error(f"doto: Security error - {e}")
        return

    try:
        if action == SyncAction.CREATE:
            success = insert_doto_directive(rst_path, task_data)
            if success:
                logger.info(f"doto: Created task {task_id} in {rst_file}")
            else:
                logger.warning(f"doto: Failed to create task {task_id} in {rst_file}")
        elif action == SyncAction.UPDATE:
            success = update_doto_directive(rst_path, task_id, task_data)
            if success:
                logger.info(f"doto: Updated task {task_id} in {rst_file}")
            else:
                logger.warning(f"doto: Failed to update task {task_id} in {rst_file}")
        elif action == SyncAction.REMOVE:
            success = remove_doto_directive(rst_path, task_id)
            if success:
                logger.info(f"doto: Removed archived task {task_id} from {rst_file}")
            else:
                logger.warning(f"doto: Failed to remove task {task_id} from {rst_file}")
        else:
            logger.warning(f"doto: Unknown action {action!r} for task {task_id}")
    except DotoRstWriteError as e:
        logger.error(f"doto: {e}")
    except Exception as e:
        logger.error(f"doto: Unexpected error {action}ing task {task_id}: {e}")


def _reconstruct_directive_content(task_data: dict[str, Any]) -> str:
    """Reconstruct directive content for hashing.

    Args:
        task_data: Task data dictionary.

    Returns:
        Reconstructed directive content.
    """
    return render_directive_text(task_data)


def _resolve_conflicts_prefer_rst(
    store: JsonTaskStore,
    conflicts: list[FieldConflict],
    env: BuildEnvironment,
) -> None:
    """Resolve conflicts by preferring RST values.

    Args:
        store: JSON task store.
        conflicts: List of conflicts to resolve.
        env: Build environment.
    """
    for conflict in conflicts:
        task = store.get_task(conflict.task_id)
        if task:
            # ``conflict.field`` is a runtime-dynamic field name, so cast the
            # TaskData to a plain mutable mapping for the assignment (TaskData
            # only permits literal keys).
            cast("dict[str, Any]", task)[conflict.field] = conflict.rst
            # Update snapshot to prevent repeated conflict detection
            snapshot = create_snapshot(task)
            store.update_snapshot(conflict.task_id, snapshot, "")


def _resolve_conflicts_prefer_json(
    store: JsonTaskStore,
    conflicts: list[FieldConflict],
    env: BuildEnvironment,
) -> None:
    """Resolve conflicts by preferring JSON values.

    Args:
        store: JSON task store.
        conflicts: List of conflicts to resolve.
        env: Build environment.
    """
    # JSON values are already in the store, but we need to queue RST updates
    for conflict in conflicts:
        task = store.get_task(conflict.task_id)
        if task:
            # Update snapshot to prevent repeated conflict detection
            snapshot = create_snapshot(task)
            store.update_snapshot(conflict.task_id, snapshot, "")

            rst_file = task.get("_sync", {}).get("rst_file")
            if rst_file:
                # Build full task data with id for directive generation
                # (generate_directive_text requires 'id' in task_data)
                full_data = dict(task)
                full_data["id"] = conflict.task_id
                # Queue update to write JSON value to RST
                sync_data = get_doto_sync_data(env)
                sync_data["rst_updates"].append(
                    (SyncAction.UPDATE, rst_file, conflict.task_id, full_data)
                )
