"""3-way merge algorithm for bidirectional sync."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# Import MERGE_FIELDS from central field registry
from doxtr_doto.fields import MERGE_FIELDS

from .conflict import FieldConflict


@dataclass
class MergeResult:
    """Result of a 3-way merge operation for a single task.

    Attributes:
        merged: The merged task data, or None if conflicts exist.
        conflicts: List of field conflicts that need resolution.
        write_rst: Whether the RST file needs to be updated.
        update_json: Whether the JSON file needs to be updated.
        update_snapshot: Whether to update the sync snapshot.
        create_in_json: Whether this is a new task to create in JSON.
        create_in_rst: Whether this is a new task to create in RST.
    """

    merged: dict[str, Any] | None = None
    conflicts: list[FieldConflict] = field(default_factory=list)
    write_rst: bool = False
    update_json: bool = False
    update_snapshot: bool = False
    create_in_json: bool = False
    create_in_rst: bool = False

    @property
    def has_conflicts(self) -> bool:
        """Check if there are any conflicts."""
        return len(self.conflicts) > 0

    @property
    def has_changes(self) -> bool:
        """Check if any changes need to be written."""
        return self.write_rst or self.update_json or self.create_in_json or self.create_in_rst


def _mark_deleted_task_archived(json_task: Mapping[str, Any], now_iso: str) -> dict[str, Any]:
    """Return a copy of ``json_task`` marked done+archived for a deleted directive.

    The single named override point for how a task whose RST directive the user
    deleted is turned into an archived task (Case (b) of :func:`sync_task`): a
    subclass/extension can replace just this helper rather than reaching into
    the merge branch.

    Args:
        json_task: The current JSON task state (not mutated).
        now_iso: ISO timestamp used for both ``archived_on`` and ``updated`` so
            the single-timestamp contract holds.

    Returns:
        A copy with ``status="done"``, ``archived=True``, ``archived_on`` and
        ``updated`` set to ``now_iso``.
    """
    archived = dict(json_task)
    # "done" is the canonical archive sentinel status the sync layer always
    # writes here, independent of the user-configurable doto_archive_statuses:
    # sync_task has no access to the Sphinx config, so it cannot consult that
    # setting (threading config through is out of scope).
    archived["status"] = "done"
    archived["archived"] = True
    archived["archived_on"] = now_iso
    archived["updated"] = now_iso
    return archived


def sync_task(
    task_id: str,
    rst_current: Mapping[str, Any] | None,
    json_task: Mapping[str, Any] | None,
    rst_file: str | None = None,
    rst_line: int | None = None,
) -> MergeResult:
    """Perform 3-way merge for a single task.

    Implements the bidirectional sync algorithm per Section 3.3 of the plan:

    - If task only exists in RST (new task): create in JSON
    - If task only exists in JSON (CLI-created or archived): optionally create in RST
    - If both exist: perform field-level 3-way merge using snapshot as base

    Args:
        task_id: The task identifier.
        rst_current: Current state parsed from RST, or None if not in RST.
        json_task: Current state from JSON file, or None if not in JSON.
        rst_file: Path to the RST file (for conflict reporting).
        rst_line: Line number in RST file (for conflict reporting).

    Returns:
        MergeResult with merged values, change flags, and any conflicts.
    """
    # Case 1: Task only exists in RST (new task from documentation)
    if json_task is None:
        if rst_current is None:
            # Neither exists - shouldn't happen, but handle gracefully
            return MergeResult()

        # New task from RST - create in JSON
        merged = dict(rst_current)
        return MergeResult(
            merged=merged,
            create_in_json=True,
            update_snapshot=True,
        )

    # Case 2: Task only exists in JSON (CLI-created, archived, or deleted)
    if rst_current is None:
        if json_task.get("archived", False):
            # Archived task - don't write to RST
            return MergeResult(
                merged=dict(json_task),
                write_rst=False,
            )

        # Disambiguate two very different situations that both present as
        # "in JSON, not in RST":
        #
        #   (a) a CLI-created task that has never been written to its RST
        #       file yet -> it must still be created in RST, or
        #   (b) a task whose directive previously existed in an RST file and
        #       has now been removed by the user editing the .rst -> the user
        #       deleted it, so it should be treated as done and archived (and
        #       NOT re-inserted, which would fight the user's deletion).
        #
        # The discriminator is ``_sync.rst_hash``: it is only non-empty once a
        # directive genuinely existed in an RST file and was synced. A CLI
        # task targeting a file (``add --file``) keeps ``rst_hash == ""`` until
        # its directive is actually written, so an empty/missing hash means
        # "never in RST" (case a) and a truthy hash means "was in RST, now
        # gone" (case b).
        rst_hash = (json_task.get("_sync") or {}).get("rst_hash")
        if rst_hash:
            # Case (b): the directive was removed from the RST source. Mark
            # the task done and archived so it drops off active lists and
            # surfaces on the archive page. Do not write back to RST.
            now_iso = datetime.now().isoformat()
            archived = _mark_deleted_task_archived(json_task, now_iso)
            return MergeResult(
                merged=archived,
                update_json=True,
                write_rst=False,
            )

        # Case (a): new task from CLI - will be written to RST on sync.
        return MergeResult(
            merged=dict(json_task),
            create_in_rst=True,
            update_snapshot=True,
        )

    # Case 3: Task exists in both - perform 3-way merge
    snapshot = json_task.get("_sync", {}).get("snapshot")

    # If no snapshot exists, this is first sync - RST is authoritative
    if not snapshot:
        merged = dict(rst_current)
        return MergeResult(
            merged=merged,
            update_json=True,
            update_snapshot=True,
        )

    # Perform per-field 3-way merge
    merged = {}
    conflicts: list[FieldConflict] = []
    rst_changed_any = False
    json_changed_any = False

    for field_name in MERGE_FIELDS:
        base_val = snapshot.get(field_name)
        rst_val = rst_current.get(field_name)
        json_val = json_task.get(field_name)

        # Normalize for comparison (handle None vs missing)
        rst_changed = not _values_equal(rst_val, base_val)
        json_changed = not _values_equal(json_val, base_val)

        if not rst_changed and not json_changed:
            # No changes - use base value
            merged[field_name] = base_val
        elif rst_changed and not json_changed:
            # RST changed, JSON didn't → use RST
            merged[field_name] = rst_val
            rst_changed_any = True
        elif json_changed and not rst_changed:
            # JSON changed, RST didn't → use JSON
            merged[field_name] = json_val
            json_changed_any = True
        elif _values_equal(rst_val, json_val):
            # Both changed to same value → no conflict
            merged[field_name] = rst_val
            rst_changed_any = True
            json_changed_any = True
        else:
            # Both changed to different values → CONFLICT
            conflicts.append(
                FieldConflict(
                    field=field_name,
                    base=base_val,
                    rst=rst_val,
                    json=json_val,
                    rst_file=rst_file or json_task.get("_sync", {}).get("rst_file", ""),
                    task_id=task_id,
                )
            )

    if conflicts:
        return MergeResult(
            merged=None,
            conflicts=conflicts,
        )

    return MergeResult(
        merged=merged,
        write_rst=json_changed_any,  # JSON had changes → update RST
        update_json=rst_changed_any,  # RST had changes → update JSON
        update_snapshot=rst_changed_any or json_changed_any,
    )


def _values_equal(val1: Any, val2: Any) -> bool:
    """Check if two values are equal for merge purposes.

    Handles special cases like None vs empty string/list.

    Args:
        val1: First value.
        val2: Second value.

    Returns:
        True if values should be considered equal.
    """
    # Normalize None and empty values
    val1 = _normalize_value(val1)
    val2 = _normalize_value(val2)

    # Compare lists element-wise (order matters for depends_on, not for tags)
    if isinstance(val1, list) and isinstance(val2, list):
        return sorted(val1) == sorted(val2)

    return bool(val1 == val2)


def _normalize_value(val: Any) -> Any:
    """Normalize a value for comparison.

    Converts empty strings to None and ensures consistent types.

    Args:
        val: Value to normalize.

    Returns:
        Normalized value.
    """
    if val is None:
        return None
    if isinstance(val, str) and not val.strip():
        return None
    if isinstance(val, list):
        # Filter out empty strings and None values
        return [v for v in val if v is not None and (not isinstance(v, str) or v.strip())]
    return val


def create_snapshot(task_data: Mapping[str, Any]) -> dict[str, Any]:
    """Create a snapshot from task data for future 3-way merge.

    Only includes the merge-able fields, not metadata like _sync.

    Args:
        task_data: Full task data dictionary.

    Returns:
        Snapshot dictionary with only merge fields.
    """
    return {field: task_data.get(field) for field in MERGE_FIELDS}
