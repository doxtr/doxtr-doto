"""doto tree command - Display tasks as a dependency tree."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import click

from doxtr_doto.cli.completion import complete_task_id

if TYPE_CHECKING:
    from doxtr_doto.cli.main import DotoContext


def get_status_marker(status: str) -> tuple[str, str]:
    """Get marker and style for status."""
    if status == "done":
        return "✓", "green"
    elif status == "blocked":
        return "✗", "red"
    elif status == "in-progress":
        return "◐", "cyan"
    else:
        return "○", ""


def get_priority_indicator(priority: str) -> str:
    """Get priority indicator."""
    indicators = {
        "critical": "!!!",
        "high": "!!",
        "medium": "!",
        "low": "",
    }
    return indicators.get(priority, "")


@click.command("tree")
@click.argument("task_id", required=False, shell_complete=complete_task_id)
@click.option("--all", "-A", "show_all", is_flag=True, help="Show all tasks as a forest.")
@click.option("--status", "-s", help="Filter by status (comma-separated).")
@click.option("--assignee", "-a", help="Filter by assignee.")
@click.option("--depth", "-d", type=int, help="Maximum tree depth to display.")
@click.option("--show-done", is_flag=True, help="Include completed tasks.")
@click.option("--reverse", "-r", is_flag=True, help="Show reverse dependencies (what depends on this).")
@click.option("--compact", "-c", is_flag=True, help="Compact output (no details).")
@click.pass_obj
def tree(
    ctx: DotoContext,
    task_id: str | None,
    show_all: bool,
    status: str | None,
    assignee: str | None,
    depth: int | None,
    show_done: bool,
    reverse: bool,
    compact: bool,
) -> None:
    """Display tasks as a dependency tree.

    Shows task dependencies in a tree structure similar to the 'tree' command.

    Without arguments, shows all root tasks (tasks with no dependencies)
    and their dependents.

    With TASK_ID, shows that task and its dependencies (or dependents with -r).

    Examples:

        doto tree                    # Show all tasks as a dependency forest

        doto tree TASK-001           # Show TASK-001 and what it depends on

        doto tree TASK-001 -r        # Show TASK-001 and what depends on it

        doto tree --show-done        # Include completed tasks

        doto tree -d 2               # Limit depth to 2 levels
    """
    formatter = ctx.formatter
    store = ctx.store
    all_tasks = store.get_all_tasks()

    if not all_tasks:
        formatter.print("No tasks found.")
        return

    # Parse status filter
    status_filter = None
    if status:
        status_filter = [s.strip() for s in status.split(",")]

    # Build dependency maps
    # depends_on_map: task_id -> list of task IDs it depends on
    # depended_by_map: task_id -> list of task IDs that depend on it
    depends_on_map: dict[str, list[str]] = {}
    depended_by_map: dict[str, list[str]] = {}

    for tid, task in all_tasks.items():
        deps = task.get("depends_on", [])
        depends_on_map[tid] = deps
        for dep_id in deps:
            if dep_id not in depended_by_map:
                depended_by_map[dep_id] = []
            depended_by_map[dep_id].append(tid)

    def should_show(tid: str) -> bool:
        """Check if task should be shown based on filters."""
        task = all_tasks.get(tid)
        if not task:
            return False
        if task.get("archived") and not show_done:
            return False
        if task.get("status") == "done" and not show_done:
            return False
        if status_filter and task.get("status") not in status_filter:
            return False
        if assignee and task.get("assignee") != assignee:
            return False
        return True

    def print_task_line(tid: str, prefix: str, connector: str) -> None:
        """Print a single task line."""
        task = all_tasks.get(tid)
        if not task:
            formatter.print(f"{prefix}{connector}{tid} (not found)", style="red")
            return

        task_status = task.get("status", "open")
        marker, style = get_status_marker(task_status)
        title = task.get("title", "")
        priority = task.get("priority", "medium")
        priority_ind = get_priority_indicator(priority)

        if compact:
            line = f"{prefix}{connector}{marker} {tid}"
        else:
            assignee_str = f" @{task.get('assignee')}" if task.get("assignee") else ""
            due_str = f" due:{task.get('due')}" if task.get("due") else ""
            line = f"{prefix}{connector}{marker} {tid}: {title}"
            if priority_ind:
                line += f" {priority_ind}"
            line += f" [{task_status}]{assignee_str}{due_str}"

        formatter.print(line, style=style)

    def print_tree_down(tid: str, prefix: str, is_last: bool, visited: set, current_depth: int) -> None:
        """Print task and its dependencies (what it depends ON)."""
        if depth is not None and current_depth > depth:
            return

        connector = "└── " if is_last else "├── "
        child_prefix = prefix + ("    " if is_last else "│   ")

        # Check for cycles
        if tid in visited:
            formatter.print(f"{prefix}{connector}↻ {tid} (cycle)", style="yellow")
            return

        if not should_show(tid):
            # Still show the node but dimmed if it's filtered out
            task = all_tasks.get(tid)
            if task:
                formatter.print(f"{prefix}{connector}○ {tid} (filtered)", style="dim")
            return

        print_task_line(tid, prefix, connector)
        visited.add(tid)

        # Get dependencies
        deps = depends_on_map.get(tid, [])
        for i, dep_id in enumerate(deps):
            is_last_child = i == len(deps) - 1
            print_tree_down(dep_id, child_prefix, is_last_child, visited.copy(), current_depth + 1)

    def print_tree_up(tid: str, prefix: str, is_last: bool, visited: set, current_depth: int) -> None:
        """Print task and its dependents (what depends ON it)."""
        if depth is not None and current_depth > depth:
            return

        connector = "└── " if is_last else "├── "
        child_prefix = prefix + ("    " if is_last else "│   ")

        # Check for cycles
        if tid in visited:
            formatter.print(f"{prefix}{connector}↻ {tid} (cycle)", style="yellow")
            return

        if not should_show(tid):
            task = all_tasks.get(tid)
            if task:
                formatter.print(f"{prefix}{connector}○ {tid} (filtered)", style="dim")
            return

        print_task_line(tid, prefix, connector)
        visited.add(tid)

        # Get dependents
        dependents = depended_by_map.get(tid, [])
        for i, dep_id in enumerate(dependents):
            is_last_child = i == len(dependents) - 1
            print_tree_up(dep_id, child_prefix, is_last_child, visited.copy(), current_depth + 1)

    # Single task mode
    if task_id:
        task = all_tasks.get(task_id)
        if not task:
            formatter.print_error(f"Task not found: {task_id}")
            raise SystemExit(1)

        if reverse:
            formatter.print(f"Tasks that depend on {task_id}:", style="bold")
        else:
            formatter.print(f"Dependencies of {task_id}:", style="bold")
        formatter.print("")

        # Print root task
        marker, style = get_status_marker(task.get("status", "open"))
        title = task.get("title", "")
        if compact:
            formatter.print(f"{marker} {task_id}", style=style)
        else:
            formatter.print(f"{marker} {task_id}: {title} [{task.get('status', 'open')}]", style=style)

        # Print tree
        if reverse:
            dependents = depended_by_map.get(task_id, [])
            if not dependents:
                formatter.print("└── (nothing depends on this task)")
            else:
                for i, dep_id in enumerate(dependents):
                    print_tree_up(dep_id, "", i == len(dependents) - 1, {task_id}, 1)
        else:
            deps = depends_on_map.get(task_id, [])
            if not deps:
                formatter.print("└── (no dependencies)")
            else:
                for i, dep_id in enumerate(deps):
                    print_tree_down(dep_id, "", i == len(deps) - 1, {task_id}, 1)
        return

    # Forest mode - show all tasks organized by dependency structure
    formatter.print("Task Dependency Tree:", style="bold")
    formatter.print("")

    # Find root tasks (no dependencies or all deps are done)
    root_tasks = []
    non_root_tasks = []

    for tid, task in all_tasks.items():
        if not should_show(tid):
            continue
        deps = depends_on_map.get(tid, [])
        # A task is a root if it has no deps, or all deps are done/not shown
        active_deps = [d for d in deps if should_show(d)]
        if not active_deps:
            root_tasks.append(tid)
        else:
            non_root_tasks.append(tid)

    if not root_tasks and not non_root_tasks:
        formatter.print("No tasks to display.")
        return

    # Print root tasks and their dependents (what depends on them)
    printed = set()

    def print_forest_node(tid: str, prefix: str, is_last: bool, current_depth: int) -> None:
        """Print a task and everything that depends on it."""
        if depth is not None and current_depth > depth:
            return
        if tid in printed:
            return
        if not should_show(tid):
            return

        connector = "└── " if is_last else "├── "
        child_prefix = prefix + ("    " if is_last else "│   ")

        print_task_line(tid, prefix, connector)
        printed.add(tid)

        # Get tasks that depend on this one
        dependents = [d for d in depended_by_map.get(tid, []) if should_show(d) and d not in printed]
        for i, dep_id in enumerate(dependents):
            print_forest_node(dep_id, child_prefix, i == len(dependents) - 1, current_depth + 1)

    # Sort roots by priority
    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    root_tasks.sort(key=lambda t: (
        priority_order.get(all_tasks[t].get("priority", "medium"), 2),
        all_tasks[t].get("due") or "9999-99-99",
        t
    ))

    for i, tid in enumerate(root_tasks):
        if tid not in printed:
            # Print as root level
            task = all_tasks[tid]
            marker, style = get_status_marker(task.get("status", "open"))
            title = task.get("title", "")
            priority = task.get("priority", "medium")
            priority_ind = get_priority_indicator(priority)

            if compact:
                formatter.print(f"{marker} {tid}", style=style)
            else:
                assignee_str = f" @{task.get('assignee')}" if task.get("assignee") else ""
                due_str = f" due:{task.get('due')}" if task.get("due") else ""
                line = f"{marker} {tid}: {title}"
                if priority_ind:
                    line += f" {priority_ind}"
                line += f" [{task.get('status', 'open')}]{assignee_str}{due_str}"
                formatter.print(line, style=style)

            printed.add(tid)

            # Print dependents
            dependents = [d for d in depended_by_map.get(tid, []) if should_show(d) and d not in printed]
            for j, dep_id in enumerate(dependents):
                print_forest_node(dep_id, "", j == len(dependents) - 1, 1)

            # Add blank line between root trees (except last)
            if i < len(root_tasks) - 1:
                formatter.print("")

    # Summary
    total = len(printed)
    done = sum(1 for t in printed if all_tasks[t].get("status") == "done")
    in_progress = sum(1 for t in printed if all_tasks[t].get("status") == "in-progress")
    blocked = sum(1 for t in printed if all_tasks[t].get("status") == "blocked")

    formatter.print("")
    summary = f"{total} task(s)"
    if done:
        summary += f", {done} done"
    if in_progress:
        summary += f", {in_progress} in-progress"
    if blocked:
        summary += f", {blocked} blocked"
    formatter.print(summary, style="dim")
