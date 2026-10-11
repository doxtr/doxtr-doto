"""doto resolve command - Resolve merge conflicts."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import click

from doxtr_doto.cli.completion import complete_task_id

if TYPE_CHECKING:
    from doxtr_doto.cli.main import DotoContext
    from doxtr_doto.sync.json_store import JsonTaskStore


def get_conflicts(store: JsonTaskStore) -> list[dict[str, Any]]:
    """Get list of current conflicts from the store.

    Conflicts are detected when _sync.snapshot exists and the current
    values differ from both the snapshot and each other.

    Args:
        store: JSON task store.

    Returns:
        List of conflict dictionaries.
    """
    # In practice, conflicts would be stored during Sphinx build
    # For now, we read from a conflicts key in the JSON
    conflicts: list[dict[str, Any]] = store.data.get("_conflicts", [])
    return conflicts


def clear_conflict(store: JsonTaskStore, task_id: str, field: str | None = None) -> None:
    """Clear a conflict from the store.

    Args:
        store: JSON task store.
        task_id: Task ID.
        field: Specific field (None to clear all fields for task).
    """
    conflicts = store.data.get("_conflicts", [])
    if field:
        conflicts = [
            c for c in conflicts if not (c.get("task_id") == task_id and c.get("field") == field)
        ]
    else:
        conflicts = [c for c in conflicts if c.get("task_id") != task_id]
    store.data["_conflicts"] = conflicts


@click.command("resolve")
@click.argument("task_id", required=False, shell_complete=complete_task_id)
@click.option("--list", "-l", "list_conflicts", is_flag=True, help="List all conflicts.")
@click.option("--use-rst", is_flag=True, help="Use RST file value.")
@click.option("--use-json", is_flag=True, help="Use JSON file value.")
@click.option("--field", "-f", help="Resolve specific field only.")
@click.option("--interactive", "-i", is_flag=True, help="Interactive resolution.")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
@click.pass_obj
def resolve(
    ctx: DotoContext,
    task_id: str | None,
    list_conflicts: bool,
    use_rst: bool,
    use_json: bool,
    field: str | None,
    interactive: bool,
    json_output: bool,
) -> None:
    """Resolve merge conflicts between RST and JSON files.

    When both RST and JSON files are modified between syncs, conflicts
    can occur. Use this command to resolve them.

    Use --list to see current conflicts, then resolve with:
      doto resolve TASK-001 --use-rst     # Use RST value
      doto resolve TASK-001 --use-json    # Use JSON value
      doto resolve TASK-001 -i            # Interactive
    """
    formatter = ctx.formatter
    if json_output:
        formatter.json_output = True

    store = ctx.store
    conflicts = get_conflicts(store)

    # List conflicts
    if list_conflicts or (not task_id and not conflicts):
        if not conflicts:
            formatter.print("No conflicts found.")
            return

        if json_output:
            formatter.print_json(conflicts)
        else:
            formatter.format_conflicts(conflicts)
        return

    # Require task_id for resolution
    if not task_id:
        if conflicts:
            formatter.print_error("Conflicts exist. Use --list to see them, or specify a task ID.")
            raise SystemExit(1)
        formatter.print("No conflicts found.")
        return

    # Find conflicts for this task
    task_conflicts = [c for c in conflicts if c.get("task_id") == task_id]
    if not task_conflicts:
        formatter.print(f"No conflicts found for task {task_id}.")
        return

    # Filter by field if specified
    if field:
        task_conflicts = [c for c in task_conflicts if c.get("field") == field]
        if not task_conflicts:
            formatter.print(f"No conflict found for field '{field}' in task {task_id}.")
            return

    # Check resolution method
    if not use_rst and not use_json and not interactive:
        raise click.UsageError("Specify resolution method: --use-rst, --use-json, or --interactive")

    if use_rst and use_json:
        raise click.UsageError("Cannot use both --use-rst and --use-json")

    # Get the task
    task = store.get_task(task_id)
    if task is None:
        raise click.ClickException(f"Task '{task_id}' not found.")

    # Resolve each conflict
    resolved = []
    for conflict in task_conflicts:
        conflict_field = conflict.get("field")
        if conflict_field is None:
            continue
        rst_value = conflict.get("rst")
        json_value = conflict.get("json")

        if interactive:
            # Show conflict and prompt
            formatter.print(f"\nConflict in {task_id}: {conflict_field}")
            formatter.print(f"  Base (last sync):  {conflict.get('base')}")
            formatter.print(f"  RST file value:    {rst_value}")
            formatter.print(f"  JSON file value:   {json_value}")
            formatter.print("")

            choice = click.prompt(
                "Use which value? [r]st, [j]son, [c]ustom, [s]kip",
                type=click.Choice(["r", "j", "c", "s"]),
                default="s",
            )

            if choice == "r":
                chosen_value = rst_value
            elif choice == "j":
                chosen_value = json_value
            elif choice == "c":
                chosen_value = click.prompt(f"Enter value for {conflict_field}")
            else:
                formatter.print(f"Skipped {conflict_field}.")
                continue
        elif use_rst:
            chosen_value = rst_value
        else:  # use_json
            chosen_value = json_value

        # Apply resolution
        store.update_task(task_id, {conflict_field: chosen_value})

        # Update snapshot to match - unconditionally create if needed
        # Re-fetch task after update to get current state
        task = store.get_task(task_id)
        if task is not None:
            sync_meta = task.setdefault("_sync", {})
            snapshot = sync_meta.get("snapshot")
            if snapshot is None:
                snapshot = {}
                sync_meta["snapshot"] = snapshot
            snapshot[conflict_field] = chosen_value
            store.update_task(task_id, {"_sync": sync_meta})

        clear_conflict(store, task_id, conflict_field)
        resolved.append(conflict_field)
        formatter.print_success(f"Resolved {conflict_field} to '{chosen_value}'")

    if resolved:
        store.save()

    if json_output:
        formatter.print_json({"resolved": resolved})
