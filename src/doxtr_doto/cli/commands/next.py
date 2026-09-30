"""doto next command - Show the next task to work on."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any

import click

if TYPE_CHECKING:
    from doxtr_doto.cli.main import DotoContext


def calculate_task_score(
    task_id: str,
    task: dict[str, Any],
    all_tasks: dict[str, dict[str, Any]],
) -> tuple[int, str, str]:
    """Calculate a priority score for a task.

    Higher scores should be worked on first.
    Returns (score, due_date, task_id) for sorting.

    Scoring factors:
    - In-progress tasks get a bonus (continue what you started)
    - Blocked dependencies reduce score significantly
    - Priority affects score
    - Overdue tasks get highest priority
    - Due soon increases priority
    """
    score = 0
    status = task.get("status", "open")
    priority = task.get("priority", "medium")
    due = task.get("due")

    # Base score from priority
    priority_scores = {
        "critical": 1000,
        "high": 750,
        "medium": 500,
        "low": 250,
    }
    score += priority_scores.get(priority, 500)

    # Bonus for in-progress (continue what you started)
    if status == "in-progress":
        score += 2000

    # Check dependencies
    depends_on = task.get("depends_on", [])
    pending_deps = 0
    for dep_id in depends_on:
        dep_task = all_tasks.get(dep_id)
        if dep_task and dep_task.get("status") != "done":
            pending_deps += 1

    # Penalize tasks with pending dependencies
    if pending_deps > 0:
        score -= 5000 * pending_deps  # Heavy penalty

    # Due date scoring
    due_sort = "9999-99-99"  # Default for no due date
    if due:
        due_sort = due
        try:
            due_date = date.fromisoformat(due)
            today = date.today()
            days_until = (due_date - today).days

            if days_until < 0:
                # Overdue - highest priority
                score += 3000 + abs(days_until) * 100
            elif days_until == 0:
                # Due today
                score += 2500
            elif days_until <= 2:
                # Due very soon
                score += 2000
            elif days_until <= 7:
                # Due this week
                score += 1000
            elif days_until <= 14:
                # Due in two weeks
                score += 500
        except ValueError:
            pass

    return (score, due_sort, task_id)


def get_ready_tasks(
    all_tasks: dict[str, dict[str, Any]],
    assignee: str | None = None,
) -> list[tuple[str, dict[str, Any], tuple]]:
    """Get tasks that are ready to be worked on.

    Returns list of (task_id, task, score_tuple) sorted by priority.
    """
    ready = []

    for task_id, task in all_tasks.items():
        # Skip archived
        if task.get("archived"):
            continue

        # Skip done tasks
        status = task.get("status", "open")
        if status == "done":
            continue

        # Filter by assignee if specified
        if assignee and task.get("assignee") != assignee:
            continue

        # Calculate score
        score_tuple = calculate_task_score(task_id, task, all_tasks)
        ready.append((task_id, task, score_tuple))

    # Sort by score (descending), then due date, then task_id
    ready.sort(key=lambda x: (-x[2][0], x[2][1], x[2][2]))

    return ready


def has_pending_deps(
    task: dict[str, Any],
    all_tasks: dict[str, dict[str, Any]],
) -> list[str]:
    """Get list of pending dependency IDs."""
    pending = []
    for dep_id in task.get("depends_on", []):
        dep_task = all_tasks.get(dep_id)
        if dep_task and dep_task.get("status") != "done":
            pending.append(dep_id)
    return pending


@click.command("next")
@click.option("--assignee", "-a", help="Filter by assignee.")
@click.option("--all", "-A", "show_all", is_flag=True, help="Show all ready tasks, not just the top one.")
@click.option("--limit", "-l", type=int, default=5, help="Number of tasks to show with --all.")
@click.option("--include-blocked", "-b", is_flag=True, help="Include tasks with pending dependencies.")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
@click.pass_obj
def next_task(
    ctx: DotoContext,
    assignee: str | None,
    show_all: bool,
    limit: int,
    include_blocked: bool,
    json_output: bool,
) -> None:
    """Show the next task to work on.

    Suggests tasks based on:
    - In-progress tasks (continue what you started)
    - Priority level
    - Due dates (overdue and urgent first)
    - Dependency status (tasks with pending deps are deprioritized)

    Examples:

        doto next

        doto next --assignee alice

        doto next --all --limit 10
    """
    formatter = ctx.formatter
    if json_output:
        formatter.json_output = True

    store = ctx.store
    all_tasks = store.get_all_tasks()

    if not all_tasks:
        formatter.print("No tasks found. Create one with 'doto add'.")
        return

    # Get ready tasks
    ready = get_ready_tasks(all_tasks, assignee)

    # Filter out tasks with pending dependencies unless requested
    if not include_blocked:
        ready = [
            (tid, t, s) for tid, t, s in ready
            if not has_pending_deps(t, all_tasks)
        ]

    if not ready:
        if assignee:
            formatter.print(f"No actionable tasks for {assignee}.")
        else:
            formatter.print("No actionable tasks found.")
        formatter.print("\nAll tasks may be done, blocked, or waiting on dependencies.")
        formatter.print("Use 'doto list' to see all tasks or 'doto next --include-blocked' to see blocked tasks.")
        return

    # JSON output
    if json_output:
        tasks_out = []
        for task_id, task, (score, _, _) in ready[:limit if show_all else 1]:
            pending = has_pending_deps(task, all_tasks)
            tasks_out.append({
                "id": task_id,
                "score": score,
                "pending_dependencies": pending,
                **task,
            })
        formatter.print_json(tasks_out if show_all else tasks_out[0])
        return

    # Show single next task
    if not show_all:
        task_id, task, (score, _, _) = ready[0]
        pending = has_pending_deps(task, all_tasks)

        formatter.print("Next task to work on:", style="bold")
        formatter.print("")
        formatter.format_task_detail({"id": task_id, **task})

        # Show why this task
        reasons = []
        status = task.get("status")
        priority = task.get("priority")
        due = task.get("due")

        if status == "in-progress":
            reasons.append("Currently in progress")
        if priority == "critical":
            reasons.append("Critical priority")
        elif priority == "high":
            reasons.append("High priority")

        if due:
            try:
                due_date = date.fromisoformat(due)
                days = (due_date - date.today()).days
                if days < 0:
                    reasons.append(f"Overdue by {abs(days)} day(s)")
                elif days == 0:
                    reasons.append("Due today")
                elif days <= 2:
                    reasons.append(f"Due in {days} day(s)")
            except ValueError:
                pass

        if pending:
            reasons.append(f"Waiting on: {', '.join(pending)}")

        if reasons:
            formatter.print("\nWhy this task:", style="dim")
            for reason in reasons:
                formatter.print(f"  • {reason}", style="dim")

        # Show count of other ready tasks
        if len(ready) > 1:
            formatter.print(f"\n{len(ready) - 1} other task(s) ready. Use 'doto next --all' to see more.")
        return

    # Show multiple tasks
    formatter.print(f"Top {min(limit, len(ready))} tasks to work on:", style="bold")
    formatter.print("")

    tasks_for_table = []
    for task_id, task, (score, _, _) in ready[:limit]:
        pending = has_pending_deps(task, all_tasks)
        status = task.get("status", "open")
        priority = task.get("priority", "medium")
        due = task.get("due", "")

        # Build reason hint
        hints = []
        if status == "in-progress":
            hints.append("in-progress")
        if due:
            try:
                days = (date.fromisoformat(due) - date.today()).days
                if days < 0:
                    hints.append(f"overdue")
                elif days == 0:
                    hints.append("due today")
                elif days <= 2:
                    hints.append(f"due soon")
            except ValueError:
                pass
        if pending:
            hints.append(f"blocked by {len(pending)}")

        tasks_for_table.append({
            "id": task_id,
            "priority": priority,
            "status": status,
            "due": due if due else "",
            "title": task.get("title", ""),
            "hint": ", ".join(hints) if hints else "",
        })

    formatter.format_task_table(
        tasks_for_table,
        columns=["id", "priority", "status", "due", "title", "hint"],
    )

    remaining = len(ready) - limit
    if remaining > 0:
        formatter.print(f"\n{remaining} more task(s) ready.")
