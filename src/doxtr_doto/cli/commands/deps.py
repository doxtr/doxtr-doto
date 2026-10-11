"""doto deps command - Show task dependencies."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import click

from doxtr_doto.cli.completion import complete_task_id

if TYPE_CHECKING:
    from doxtr_doto.cli.main import DotoContext
    from doxtr_doto.cli.output import OutputFormatter
    from doxtr_doto.sync.json_store import TaskData


@click.command("deps")
@click.argument("task_id", shell_complete=complete_task_id)
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["table", "list", "json", "tree"]),
    default="table",
    help="Output format.",
)
@click.option(
    "--recursive",
    "-r",
    is_flag=True,
    help="Show transitive dependencies (dependencies of dependencies).",
)
@click.option(
    "--status",
    "-s",
    "filter_status",
    help="Filter dependencies by status (comma-separated).",
)
@click.option(
    "--pending-only",
    "-p",
    is_flag=True,
    help="Show only pending (non-done) dependencies.",
)
@click.pass_obj
def deps(
    ctx: DotoContext,
    task_id: str,
    output_format: str,
    recursive: bool,
    filter_status: str | None,
    pending_only: bool,
) -> None:
    """List tasks that must be completed before a task can start.

    Shows the direct dependencies of a task (tasks listed in its depends_on field).
    Use --recursive to also show transitive dependencies.

    Examples:

        doto deps TASK-001

        doto deps TASK-001 --recursive

        doto deps TASK-001 --pending-only

        doto deps TASK-001 --format tree
    """
    formatter = ctx.formatter
    store = ctx.store

    # Get the target task
    task = store.get_task(task_id)
    if task is None:
        formatter.print_error(f"Task not found: {task_id}")
        raise SystemExit(1)

    # Get all tasks for lookup
    all_tasks = store.get_all_tasks()

    # Parse status filter
    status_list = None
    if filter_status:
        status_list = [s.strip() for s in filter_status.split(",")]

    # Collect dependencies
    if recursive:
        deps_info = _collect_recursive_deps(task_id, all_tasks, set())
    else:
        deps_info = _collect_direct_deps(task_id, all_tasks)

    # Filter by status
    if pending_only:
        deps_info = [d for d in deps_info if d.get("status") != "done"]
    elif status_list:
        deps_info = [d for d in deps_info if d.get("status") in status_list]

    # Output
    if output_format == "json":
        formatter.print_json(
            {
                "task_id": task_id,
                "task_title": task.get("title", ""),
                "dependencies": deps_info,
                "total_count": len(deps_info),
                "pending_count": sum(1 for d in deps_info if d.get("status") != "done"),
            }
        )
    elif output_format == "tree":
        _print_deps_tree(formatter, task_id, task, all_tasks, recursive, status_list, pending_only)
    elif output_format == "list":
        _print_deps_list(formatter, task_id, task, deps_info)
    else:  # table
        _print_deps_table(formatter, task_id, task, deps_info)


def _collect_direct_deps(
    task_id: str,
    all_tasks: dict[str, TaskData],
) -> list[dict[str, Any]]:
    """Collect direct dependencies of a task."""
    task = all_tasks.get(task_id)
    if task is None:
        return []

    depends_on = task.get("depends_on", [])
    deps_info = []

    for dep_id in depends_on:
        dep_task = all_tasks.get(dep_id)
        if dep_task:
            deps_info.append(
                {
                    "id": dep_id,
                    "title": dep_task.get("title", ""),
                    "status": dep_task.get("status", ""),
                    "priority": dep_task.get("priority", ""),
                    "assignee": dep_task.get("assignee", ""),
                    "depth": 1,
                }
            )
        else:
            # Dependency references a non-existent task
            deps_info.append(
                {
                    "id": dep_id,
                    "title": "(task not found)",
                    "status": "unknown",
                    "priority": "",
                    "assignee": "",
                    "depth": 1,
                    "missing": True,
                }
            )

    return deps_info


def _collect_recursive_deps(
    task_id: str,
    all_tasks: dict[str, TaskData],
    visited: set[str],
    depth: int = 1,
) -> list[dict[str, Any]]:
    """Collect all dependencies recursively, avoiding cycles."""
    task = all_tasks.get(task_id)
    if task is None:
        return []

    depends_on = task.get("depends_on", [])
    deps_info = []

    for dep_id in depends_on:
        if dep_id in visited:
            # Cycle detected, skip
            continue

        visited.add(dep_id)
        dep_task = all_tasks.get(dep_id)

        if dep_task:
            deps_info.append(
                {
                    "id": dep_id,
                    "title": dep_task.get("title", ""),
                    "status": dep_task.get("status", ""),
                    "priority": dep_task.get("priority", ""),
                    "assignee": dep_task.get("assignee", ""),
                    "depth": depth,
                }
            )
            # Recursively collect dependencies of this dependency
            nested_deps = _collect_recursive_deps(dep_id, all_tasks, visited, depth + 1)
            deps_info.extend(nested_deps)
        else:
            deps_info.append(
                {
                    "id": dep_id,
                    "title": "(task not found)",
                    "status": "unknown",
                    "priority": "",
                    "assignee": "",
                    "depth": depth,
                    "missing": True,
                }
            )

    return deps_info


def _print_deps_table(
    formatter: OutputFormatter,
    task_id: str,
    task: TaskData,
    deps_info: list[dict[str, Any]],
) -> None:
    """Print dependencies as a table."""
    task_title = task.get("title", "")
    formatter.print(f"Dependencies for {task_id}: {task_title}", style="bold")
    formatter.print("")

    if not deps_info:
        formatter.print("No dependencies - this task can be started immediately.", style="green")
        return

    # Use the existing table formatter
    formatter.format_task_table(
        deps_info, columns=["id", "status", "priority", "assignee", "title"]
    )

    # Summary
    pending = sum(1 for d in deps_info if d.get("status") != "done")
    if pending == 0:
        formatter.print("\nAll dependencies are complete. This task can be started.", style="green")
    else:
        formatter.print(
            f"\n{pending} of {len(deps_info)} dependencies still pending.", style="yellow"
        )


def _print_deps_list(
    formatter: OutputFormatter,
    task_id: str,
    task: TaskData,
    deps_info: list[dict[str, Any]],
) -> None:
    """Print dependencies as a simple list."""
    task_title = task.get("title", "")
    formatter.print(f"Dependencies for {task_id}: {task_title}", style="bold")
    formatter.print("")

    if not deps_info:
        formatter.print("No dependencies.")
        return

    for dep in deps_info:
        indent = "  " * (dep.get("depth", 1) - 1)
        status_marker = "✓" if dep.get("status") == "done" else "○"
        missing_marker = " (missing)" if dep.get("missing") else ""
        formatter.print(f"{indent}{status_marker} {dep['id']}: {dep['title']}{missing_marker}")


def _print_deps_tree(
    formatter: OutputFormatter,
    task_id: str,
    task: TaskData,
    all_tasks: dict[str, TaskData],
    recursive: bool,
    status_list: list[str] | None,
    pending_only: bool,
) -> None:
    """Print dependencies as a tree structure."""
    task_title = task.get("title", "")
    formatter.print(f"{task_id}: {task_title}", style="bold")

    depends_on = task.get("depends_on", [])
    if not depends_on:
        formatter.print("└── (no dependencies)")
        return

    _print_tree_branch(
        formatter,
        depends_on,
        all_tasks,
        prefix="",
        recursive=recursive,
        visited=set(),
        status_list=status_list,
        pending_only=pending_only,
    )


def _print_tree_branch(
    formatter: OutputFormatter,
    dep_ids: list[str],
    all_tasks: dict[str, TaskData],
    prefix: str,
    recursive: bool,
    visited: set[str],
    status_list: list[str] | None,
    pending_only: bool,
) -> None:
    """Print a branch of the dependency tree."""
    for i, dep_id in enumerate(dep_ids):
        is_last = i == len(dep_ids) - 1
        connector = "└── " if is_last else "├── "
        child_prefix = prefix + ("    " if is_last else "│   ")

        dep_task = all_tasks.get(dep_id)
        if dep_task is None:
            formatter.print(f"{prefix}{connector}{dep_id} (missing)", style="red")
            continue

        # Apply filters
        status = dep_task.get("status", "")
        if pending_only and status == "done":
            continue
        if status_list and status not in status_list:
            continue

        # Status indicator
        if status == "done":
            status_style = "dim"
            marker = "✓"
        elif status == "blocked":
            status_style = "red"
            marker = "✗"
        elif status == "in-progress":
            status_style = "cyan"
            marker = "◐"
        else:
            status_style = ""
            marker = "○"

        title = dep_task.get("title", "")
        formatter.print(
            f"{prefix}{connector}{marker} {dep_id}: {title} [{status}]", style=status_style
        )

        # Recurse if requested and not visited
        if recursive and dep_id not in visited:
            visited.add(dep_id)
            nested_deps = dep_task.get("depends_on", [])
            if nested_deps:
                _print_tree_branch(
                    formatter,
                    nested_deps,
                    all_tasks,
                    child_prefix,
                    recursive,
                    visited,
                    status_list,
                    pending_only,
                )
