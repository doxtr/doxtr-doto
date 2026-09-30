"""doto stats command - Show task statistics."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

import click

from doxtr_doto.constants import (
    PRIORITY_DISPLAY_ORDER,
    STATUS_DISPLAY_ORDER,
)

if TYPE_CHECKING:
    from doxtr_doto.cli.main import DotoContext


@click.command("stats")
@click.option(
    "--by-status",
    is_flag=True,
    help="Group statistics by status.",
)
@click.option(
    "--by-priority",
    is_flag=True,
    help="Group statistics by priority.",
)
@click.option(
    "--by-assignee",
    is_flag=True,
    help="Group statistics by assignee.",
)
@click.option(
    "--by-tag",
    is_flag=True,
    help="Group statistics by tag.",
)
@click.option(
    "--archived",
    is_flag=True,
    help="Include archived tasks in statistics.",
)
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    help="Output format.",
)
@click.pass_obj
def stats(
    ctx: DotoContext,
    by_status: bool,
    by_priority: bool,
    by_assignee: bool,
    by_tag: bool,
    archived: bool,
    output_format: str,
) -> None:
    """Show task statistics.

    Examples:

        doto stats

        doto stats --by-status

        doto stats --by-priority --by-assignee

        doto stats --archived --format json
    """
    formatter = ctx.formatter
    store = ctx.store

    # Get all tasks
    tasks = store.filter_tasks(include_archived=archived)

    if not tasks:
        if output_format == "json":
            formatter.print_json({"total": 0, "message": "No tasks found"})
        else:
            formatter.print("No tasks found.")
        return

    # Calculate statistics
    stats_data: dict[str, Any] = {
        "total": len(tasks),
    }

    # Count archived vs active
    archived_count = sum(1 for t in tasks if t.get("archived"))
    active_count = len(tasks) - archived_count
    stats_data["active"] = active_count
    stats_data["archived"] = archived_count

    # Overdue tasks
    today = date.today()
    overdue = [
        t for t in tasks
        if t.get("due")
        and datetime.fromisoformat(t["due"]).date() < today
        and t.get("status") != "done"
        and not t.get("archived")
    ]
    stats_data["overdue"] = len(overdue)

    # Tasks due this week
    from datetime import timedelta
    week_end = today + timedelta(days=7)
    due_this_week = [
        t for t in tasks
        if t.get("due")
        and today <= datetime.fromisoformat(t["due"]).date() <= week_end
        and t.get("status") != "done"
        and not t.get("archived")
    ]
    stats_data["due_this_week"] = len(due_this_week)

    # If no grouping specified, show all groupings
    show_all = not (by_status or by_priority or by_assignee or by_tag)

    # Group by status
    if by_status or show_all:
        status_counts = Counter(t.get("status", "open") for t in tasks if not t.get("archived"))
        stats_data["by_status"] = dict(status_counts)

    # Group by priority
    if by_priority or show_all:
        priority_counts = Counter(t.get("priority", "medium") for t in tasks if not t.get("archived"))
        stats_data["by_priority"] = dict(priority_counts)

    # Group by assignee
    if by_assignee or show_all:
        assignee_counts = Counter(t.get("assignee") or "unassigned" for t in tasks if not t.get("archived"))
        stats_data["by_assignee"] = dict(assignee_counts)

    # Group by tag
    if by_tag or show_all:
        tag_counts: Counter[str] = Counter()
        for t in tasks:
            if t.get("archived"):
                continue
            tags = t.get("tags", [])
            if tags:
                tag_counts.update(tags)
            else:
                tag_counts["untagged"] += 1
        stats_data["by_tag"] = dict(tag_counts)

    # Output
    if output_format == "json":
        formatter.print_json(stats_data)
    else:
        _format_stats_text(formatter, stats_data, by_status, by_priority, by_assignee, by_tag, show_all)


def _format_stats_text(
    formatter,
    stats_data: dict[str, Any],
    by_status: bool,
    by_priority: bool,
    by_assignee: bool,
    by_tag: bool,
    show_all: bool,
) -> None:
    """Format statistics as text output."""
    formatter.print("Task Statistics", style="bold")
    formatter.print("=" * 40)

    # Summary
    formatter.print(f"\nTotal tasks: {stats_data['total']}")
    formatter.print(f"  Active: {stats_data['active']}")
    if stats_data['archived'] > 0:
        formatter.print(f"  Archived: {stats_data['archived']}")

    if stats_data['overdue'] > 0:
        formatter.print(f"  Overdue: {stats_data['overdue']}", style="red")
    if stats_data['due_this_week'] > 0:
        formatter.print(f"  Due this week: {stats_data['due_this_week']}", style="yellow")

    # Status breakdown
    if by_status or show_all:
        _print_breakdown(formatter, "Status", stats_data.get("by_status", {}), STATUS_ORDER)

    # Priority breakdown
    if by_priority or show_all:
        _print_breakdown(formatter, "Priority", stats_data.get("by_priority", {}), PRIORITY_ORDER)

    # Assignee breakdown
    if by_assignee or show_all:
        _print_breakdown(formatter, "Assignee", stats_data.get("by_assignee", {}))

    # Tag breakdown
    if by_tag or show_all:
        _print_breakdown(formatter, "Tag", stats_data.get("by_tag", {}))


# Use centralized display ordering constants
STATUS_ORDER = STATUS_DISPLAY_ORDER
PRIORITY_ORDER = PRIORITY_DISPLAY_ORDER


def _print_breakdown(
    formatter,
    title: str,
    counts: dict[str, int],
    order: list[str] | None = None,
) -> None:
    """Print a breakdown section with optional ordering."""
    if not counts:
        return

    formatter.print(f"\nBy {title}:")

    # Sort by specified order, then alphabetically for others
    if order:
        sorted_items = []
        for key in order:
            if key in counts:
                sorted_items.append((key, counts[key]))
        # Add any remaining items alphabetically
        for key in sorted(counts.keys()):
            if key not in order:
                sorted_items.append((key, counts[key]))
    else:
        # Sort by count descending, then alphabetically
        sorted_items = sorted(counts.items(), key=lambda x: (-x[1], x[0]))

    total = sum(counts.values())
    for key, count in sorted_items:
        pct = (count / total * 100) if total > 0 else 0
        bar_width = int(pct / 5)  # 20 chars = 100%
        bar = "█" * bar_width + "░" * (20 - bar_width)
        formatter.print(f"  {key:15} {bar} {count:3} ({pct:5.1f}%)")
