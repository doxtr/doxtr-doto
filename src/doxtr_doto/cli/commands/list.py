"""doto list command - List tasks with filters."""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

import click

from doxtr_doto.cli.completion import complete_assignee, complete_tag

if TYPE_CHECKING:
    from doxtr_doto.cli.main import DotoContext


def sort_tasks(
    tasks: list[dict[str, Any]],
    sort_fields: list[str],
    reverse: bool = False,
) -> list[dict[str, Any]]:
    """Sort tasks by specified fields.

    Args:
        tasks: List of tasks to sort.
        sort_fields: Fields to sort by (in order of priority).
        reverse: Reverse sort order.

    Returns:
        Sorted list of tasks.
    """
    # Priority order (higher is more important)
    priority_order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    # Status order
    status_order = {"blocked": 4, "in-progress": 3, "open": 2, "done": 1}

    def sort_key(task: dict[str, Any]) -> tuple:
        keys = []
        for field in sort_fields:
            value = task.get(field)
            if field == "priority":
                # Higher priority first (negate for descending)
                keys.append(-priority_order.get(value or "medium", 2))
            elif field == "status":
                keys.append(-status_order.get(value or "open", 2))
            elif field == "due":
                # Tasks without due date go last
                if value:
                    keys.append(value)
                else:
                    keys.append("9999-99-99")
            elif field == "created" or field == "updated":
                keys.append(value or "")
            else:
                keys.append(str(value or "").lower())
        return tuple(keys)

    return sorted(tasks, key=sort_key, reverse=reverse)


def format_csv(tasks: list[dict[str, Any]], columns: list[str]) -> str:
    """Format tasks as CSV.

    Args:
        tasks: List of tasks.
        columns: Columns to include.

    Returns:
        CSV string.
    """
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()

    for task in tasks:
        row = {}
        for col in columns:
            value = task.get(col, "")
            if col == "tags" and isinstance(value, list):
                value = ",".join(value)
            elif col == "depends_on" and isinstance(value, list):
                value = ",".join(value)
            row[col] = value
        writer.writerow(row)

    return output.getvalue()


@click.command("list")
@click.option("--assignee", "-a", shell_complete=complete_assignee, help="Filter by assignee (comma-separated for multiple).")
@click.option(
    "--priority",
    "-p",
    help="Filter by priority (comma-separated for multiple).",
)
@click.option(
    "--status",
    "-s",
    help="Filter by status (comma-separated for multiple).",
)
@click.option("--tags", "-t", shell_complete=complete_tag, help="Filter by tags (comma-separated, matches any).")
@click.option("--due-before", help="Filter by due date before (YYYY-MM-DD).")
@click.option("--due-after", help="Filter by due date after (YYYY-MM-DD).")
@click.option("--archived", is_flag=True, help="Include archived tasks.")
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["table", "list", "cards", "json", "csv", "tree"]),
    default="table",
    help="Output format.",
)
@click.option("--sort", "sort_by", help="Sort by field(s) (comma-separated).")
@click.option("--reverse", "-r", is_flag=True, help="Reverse sort order.")
@click.option("--limit", "-l", type=int, help="Maximum number of tasks to show.")
@click.option("--columns", help="Columns to display (comma-separated).")
@click.option(
    "--with-deps",
    is_flag=True,
    help="Show dependency information (adds deps column or tree view).",
)
@click.pass_obj
def list_tasks(
    ctx: DotoContext,
    assignee: str | None,
    priority: str | None,
    status: str | None,
    tags: str | None,
    due_before: str | None,
    due_after: str | None,
    archived: bool,
    output_format: str,
    sort_by: str | None,
    reverse: bool,
    limit: int | None,
    columns: str | None,
    with_deps: bool,
) -> None:
    """List tasks with optional filters.

    Examples:

        doto list

        doto list --assignee alice --priority high,critical

        doto list --status open,in-progress --due-before 2026-08-01

        doto list --format json

        doto list --sort due,priority --limit 10

        doto list --with-deps

        doto list --format tree
    """
    formatter = ctx.formatter
    store = ctx.store

    # Parse comma-separated filters
    assignee_list = [a.strip() for a in assignee.split(",")] if assignee else None
    priority_list = [p.strip() for p in priority.split(",")] if priority else None
    status_list = [s.strip() for s in status.split(",")] if status else None
    tag_list = [t.strip() for t in tags.split(",")] if tags else None

    # Filter tasks
    tasks = store.filter_tasks(
        assignee=assignee_list,
        priority=priority_list,
        status=status_list,
        tags=tag_list,
        due_before=due_before,
        due_after=due_after,
        include_archived=archived,
    )

    # Sort tasks
    if sort_by:
        sort_fields = [f.strip() for f in sort_by.split(",")]
    else:
        # Default sort: priority desc, then due asc
        sort_fields = ["priority", "due"]

    tasks = sort_tasks(tasks, sort_fields, reverse=reverse)

    # Apply limit
    if limit:
        tasks = tasks[:limit]

    # Parse columns (CLI overrides config)
    column_list = None
    if columns:
        column_list = [c.strip() for c in columns.split(",")]
    elif ctx.config.list_columns:
        column_list = ctx.config.list_columns

    # Add dependency info if requested
    if with_deps:
        all_tasks = store.get_all_tasks()
        for task in tasks:
            deps = task.get("depends_on", [])
            task["has_deps"] = len(deps) > 0
            task["deps_count"] = len(deps)
            # Count pending deps
            pending = sum(
                1 for d in deps
                if all_tasks.get(d, {}).get("status") != "done"
            )
            task["pending_deps"] = pending
            # Format deps display
            if deps:
                task["deps_display"] = _format_deps_display(deps, all_tasks)
            else:
                task["deps_display"] = "-"

        # Add deps column if not already specified
        if column_list and "deps" not in column_list:
            column_list = column_list + ["deps"]
        elif not column_list:
            column_list = ["id", "priority", "status", "assignee", "due", "deps", "title"]

    # Format output
    if output_format == "tree":
        all_tasks = store.get_all_tasks()
        _format_task_tree(formatter, tasks, all_tasks)
    elif output_format == "json":
        formatter.print_json(tasks)
    elif output_format == "csv":
        default_columns = ["id", "title", "priority", "status", "assignee", "due", "tags"]
        csv_output = format_csv(tasks, column_list or default_columns)
        click.echo(csv_output, nl=False)
    elif output_format == "list":
        formatter.format_task_list(tasks)
    elif output_format == "cards":
        formatter.format_task_cards(tasks)
    else:  # table
        formatter.format_task_table(tasks, columns=column_list)


def _format_deps_display(deps: list[str], all_tasks: dict[str, Any]) -> str:
    """Format dependencies for display in table."""
    parts = []
    for dep_id in deps:
        dep_task = all_tasks.get(dep_id)
        if dep_task:
            status = dep_task.get("status", "")
            if status == "done":
                parts.append(f"✓{dep_id}")
            elif status == "blocked":
                parts.append(f"✗{dep_id}")
            else:
                parts.append(f"○{dep_id}")
        else:
            parts.append(f"?{dep_id}")
    return " ".join(parts)


def _format_task_tree(
    formatter,
    tasks: list[dict[str, Any]],
    all_tasks: dict[str, Any],
) -> None:
    """Format tasks as a tree showing dependencies."""
    if not tasks:
        formatter.print("No tasks found.")
        return

    # Build reverse dependency map (what depends on each task)
    dependents: dict[str, list[str]] = {}
    for task_id, task_data in all_tasks.items():
        for dep_id in task_data.get("depends_on", []):
            if dep_id not in dependents:
                dependents[dep_id] = []
            dependents[dep_id].append(task_id)

    # Find root tasks (tasks with no incomplete dependencies)
    task_ids = {t["id"] for t in tasks}
    printed = set()

    def get_status_marker(status: str) -> tuple[str, str]:
        """Get marker and style for status."""
        if status == "done":
            return "✓", "dim"
        elif status == "blocked":
            return "✗", "red"
        elif status == "in-progress":
            return "◐", "cyan"
        else:
            return "○", ""

    def print_task(task: dict[str, Any], prefix: str, is_last: bool) -> None:
        """Print a task with tree formatting."""
        task_id = task["id"]
        if task_id in printed:
            return
        printed.add(task_id)

        connector = "└── " if is_last else "├── "
        child_prefix = prefix + ("    " if is_last else "│   ")

        status = task.get("status", "open")
        marker, style = get_status_marker(status)
        title = task.get("title", "")
        priority = task.get("priority", "")

        # Show pending deps count
        deps = task.get("depends_on", [])
        pending_deps = sum(
            1 for d in deps
            if all_tasks.get(d, {}).get("status") != "done"
        )
        deps_info = ""
        if pending_deps > 0:
            deps_info = f" [waiting on {pending_deps}]"
        elif deps:
            deps_info = " [deps done]"

        line = f"{prefix}{connector}{marker} {task_id}: {title} ({priority}) [{status}]{deps_info}"
        formatter.print(line, style=style)

        # Print tasks that depend on this one (if in our filtered list)
        children = [
            all_tasks.get(dep_id)
            for dep_id in dependents.get(task_id, [])
            if dep_id in task_ids and dep_id not in printed
        ]
        children = [c for c in children if c]  # Filter None
        for i, child in enumerate(children):
            child_task = {"id": dependents.get(task_id, [])[i], **child}
            for t in tasks:
                if t["id"] in dependents.get(task_id, []):
                    print_task(t, child_prefix, i == len(children) - 1)
                    break

    # Print tasks that have no dependencies first (root tasks)
    root_tasks = [
        t for t in tasks
        if not t.get("depends_on") or all(
            all_tasks.get(d, {}).get("status") == "done"
            for d in t.get("depends_on", [])
        )
    ]
    other_tasks = [t for t in tasks if t not in root_tasks]

    formatter.print("Tasks (ready to start):", style="bold")
    for i, task in enumerate(root_tasks):
        if task["id"] not in printed:
            print_task(task, "", i == len(root_tasks) - 1)

    if other_tasks:
        formatter.print("\nTasks (waiting on dependencies):", style="bold")
        for i, task in enumerate(other_tasks):
            if task["id"] not in printed:
                print_task(task, "", i == len(other_tasks) - 1)

    # Summary
    total = len(tasks)
    ready = len([t for t in tasks if t["id"] in {r["id"] for r in root_tasks}])
    formatter.print(f"\n{total} tasks: {ready} ready, {total - ready} waiting")
