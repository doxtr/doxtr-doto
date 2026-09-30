"""doto delete command - Permanently delete tasks."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import click

from doxtr_doto.cli.completion import (
    complete_assignee,
    complete_priority,
    complete_status,
    complete_tag,
    complete_task_id,
)

if TYPE_CHECKING:
    from doxtr_doto.cli.main import DotoContext


def _get_series_for_task(store, task_id: str) -> str | None:
    """Check if a task belongs to a series.

    Args:
        store: The task store.
        task_id: Task identifier.

    Returns:
        Series ID if task is part of a series, None otherwise.
    """
    for series_id, series_data in store.get_all_series().items():
        if task_id in series_data.get("task_ids", []):
            return series_id
    return None


def _collect_tasks_to_delete(
    ctx: "DotoContext",
    task_ids: tuple[str, ...],
    filter_status: str | None,
    filter_priority: str | None,
    filter_assignee: str | None,
    filter_tags: str | None,
    filter_archived: bool,
    all_flag: bool,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect tasks to delete based on IDs and/or filters.

    Args:
        ctx: Doto context.
        task_ids: Specific task IDs to delete.
        filter_status: Filter by status.
        filter_priority: Filter by priority.
        filter_assignee: Filter by assignee.
        filter_tags: Filter by tags.
        filter_archived: Only include archived tasks.
        all_flag: Required flag for filter-based deletion.

    Returns:
        Tuple of (tasks_to_delete, not_found_ids).
    """
    store = ctx.store
    tasks_to_delete: list[dict[str, Any]] = []
    not_found: list[str] = []

    # If specific task IDs provided, collect those
    if task_ids:
        seen_ids: set[str] = set()
        for task_id in task_ids:
            # Skip duplicates
            if task_id in seen_ids:
                continue
            seen_ids.add(task_id)

            task = store.get_task(task_id)
            if task is None:
                not_found.append(task_id)
            else:
                tasks_to_delete.append({"id": task_id, **task})
    else:
        # Use filters to find tasks
        # Parse comma-separated filters
        status_list = [s.strip() for s in filter_status.split(",")] if filter_status else None
        priority_list = [p.strip() for p in filter_priority.split(",")] if filter_priority else None
        assignee_list = [a.strip() for a in filter_assignee.split(",")] if filter_assignee else None
        tag_list = [t.strip() for t in filter_tags.split(",")] if filter_tags else None

        # When filter_archived is set, we want ONLY archived tasks
        # Otherwise, include_archived=False means we only get active tasks
        if filter_archived:
            # Get all tasks including archived, then filter to only archived
            all_tasks = store.filter_tasks(
                assignee=assignee_list,
                priority=priority_list,
                status=status_list,
                tags=tag_list,
                include_archived=True,
            )
            tasks_to_delete = [t for t in all_tasks if t.get("archived")]
        else:
            tasks_to_delete = store.filter_tasks(
                assignee=assignee_list,
                priority=priority_list,
                status=status_list,
                tags=tag_list,
                include_archived=False,
            )

    return tasks_to_delete, not_found


@click.command("delete")
@click.argument("task_ids", nargs=-1, shell_complete=complete_task_id)
@click.option(
    "--filter-status",
    shell_complete=complete_status,
    help="Filter tasks by status (comma-separated).",
)
@click.option(
    "--filter-priority",
    shell_complete=complete_priority,
    help="Filter tasks by priority (comma-separated).",
)
@click.option(
    "--filter-assignee",
    shell_complete=complete_assignee,
    help="Filter tasks by assignee (comma-separated).",
)
@click.option(
    "--filter-tags",
    shell_complete=complete_tag,
    help="Filter tasks with any of these tags (comma-separated).",
)
@click.option(
    "--filter-archived",
    is_flag=True,
    help="Only delete archived tasks.",
)
@click.option(
    "--all",
    "all_flag",
    is_flag=True,
    help="Required safety flag when using filters without specific task IDs.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Preview deletions without actually deleting.",
)
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="Skip confirmation prompt.",
)
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    help="Output as JSON.",
)
@click.pass_obj
def delete(
    ctx: "DotoContext",
    task_ids: tuple[str, ...],
    filter_status: str | None,
    filter_priority: str | None,
    filter_assignee: str | None,
    filter_tags: str | None,
    filter_archived: bool,
    all_flag: bool,
    dry_run: bool,
    force: bool,
    json_output: bool,
) -> None:
    """Permanently delete tasks.

    This is a DESTRUCTIVE operation. Deleted tasks cannot be recovered.
    Consider using 'doto archive' instead if you might need the tasks later.

    You can delete specific tasks by ID, or use filters to bulk delete.
    When using filters without specific IDs, the --all flag is required
    as a safety measure.

    Examples:

        doto delete DOTO-001

        doto delete DOTO-001 DOTO-002 DOTO-003

        doto delete DOTO-001 --force

        doto delete --filter-status done --all

        doto delete --filter-archived --all

        doto delete --filter-status done --dry-run --all

        doto delete DOTO-001 --json
    """
    formatter = ctx.formatter
    if json_output:
        formatter.json_output = True

    store = ctx.store

    # Validate: either task_ids or filters must be provided
    has_filters = any([filter_status, filter_priority, filter_assignee, filter_tags, filter_archived])

    # Warn if both task IDs and filters are provided (IDs take precedence)
    if task_ids and has_filters:
        formatter.print_warning("Filter options ignored when specific task IDs are provided.")

    if not task_ids and not has_filters:
        if json_output:
            formatter.print_json({
                "error": "No tasks specified. Provide task IDs or use filter options with --all.",
                "deleted": [],
                "not_found": [],
            })
        else:
            formatter.print_error("No tasks specified. Provide task IDs or use filter options with --all.")
        raise SystemExit(1)

    # Safety check: require --all flag when using filters without specific IDs
    if has_filters and not task_ids and not all_flag:
        if json_output:
            formatter.print_json({
                "error": "The --all flag is required when using filters without specific task IDs.",
                "deleted": [],
                "not_found": [],
            })
        else:
            formatter.print_error(
                "The --all flag is required when using filters without specific task IDs.\n"
                "This is a safety measure to prevent accidental bulk deletion.\n"
                "Use --dry-run first to preview which tasks would be deleted."
            )
        raise SystemExit(1)

    # Collect tasks to delete
    tasks_to_delete, not_found = _collect_tasks_to_delete(
        ctx,
        task_ids,
        filter_status,
        filter_priority,
        filter_assignee,
        filter_tags,
        filter_archived,
        all_flag,
    )

    if not tasks_to_delete and not not_found:
        if json_output:
            formatter.print_json({
                "message": "No tasks matched the specified criteria.",
                "deleted": [],
                "not_found": [],
            })
        else:
            formatter.print_warning("No tasks matched the specified criteria.")
        return

    # Check for series membership and collect warnings
    series_warnings: list[tuple[str, str]] = []
    for task in tasks_to_delete:
        task_id = task["id"]
        series_id = _get_series_for_task(store, task_id)
        if series_id:
            series_warnings.append((task_id, series_id))

    # Dry run mode: just show what would be deleted
    if dry_run:
        if json_output:
            formatter.print_json({
                "dry_run": True,
                "would_delete": [t["id"] for t in tasks_to_delete],
                "series_warnings": [
                    {"task_id": tid, "series_id": sid}
                    for tid, sid in series_warnings
                ],
                "not_found": not_found,
            })
        else:
            formatter.print("Dry run - the following tasks would be deleted:", style="bold")
            for task in tasks_to_delete:
                task_id = task["id"]
                title = task.get("title", "")
                status = task.get("status", "")
                formatter.print(f"  {task_id}: [{status}] {title}")

            if series_warnings:
                formatter.print("\nWarning - these tasks are part of a series:", style="yellow")
                for task_id, series_id in series_warnings:
                    formatter.print(f"  {task_id} is part of series {series_id}")

            if not_found:
                formatter.print("\nNot found:", style="red")
                for task_id in not_found:
                    formatter.print(f"  {task_id}")

            formatter.print(f"\nTotal: {len(tasks_to_delete)} task(s) would be deleted.")
        return

    # Confirmation prompt (unless --force or --json)
    if not force and not json_output:
        # Show what will be deleted
        formatter.print("The following tasks will be PERMANENTLY deleted:", style="bold red")
        for task in tasks_to_delete:
            task_id = task["id"]
            title = task.get("title", "")
            status = task.get("status", "")
            formatter.print(f"  {task_id}: [{status}] {title}")

        if series_warnings:
            formatter.print("\nWarning - these tasks are part of a series:", style="yellow")
            for task_id, series_id in series_warnings:
                formatter.print(f"  {task_id} is part of series {series_id}")

        formatter.print(f"\nTotal: {len(tasks_to_delete)} task(s)")
        formatter.print("\nThis action cannot be undone!", style="red")

        if not click.confirm("Are you sure you want to delete these tasks?"):
            formatter.print("Aborted.")
            return

    # Perform deletion
    deleted: list[str] = []
    for task in tasks_to_delete:
        task_id = task["id"]
        if store.delete_task(task_id):
            deleted.append(task_id)

    # Save if any deletions were made
    if deleted:
        store.save()
        if not json_output and not formatter.quiet:
            for task_id in deleted:
                formatter.print_success(f"Deleted task {task_id}")

    # Report not found (only in non-JSON mode)
    if not json_output:
        for task_id in not_found:
            formatter.print_error(f"Task '{task_id}' not found.")

    # JSON output
    if json_output:
        result: dict[str, Any] = {
            "deleted": deleted,
            "not_found": not_found,
        }
        if series_warnings:
            result["series_warnings"] = [
                {"task_id": tid, "series_id": sid}
                for tid, sid in series_warnings
            ]
        formatter.print_json(result)
