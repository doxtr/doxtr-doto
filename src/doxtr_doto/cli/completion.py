"""Shell completion support for doto CLI."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import click
from click.shell_completion import CompletionItem

if TYPE_CHECKING:
    from click import Context, Parameter


def get_task_store():
    """Get task store for completion, returns None if not available."""
    from doxtr_doto.cli.config import load_config
    from doxtr_doto.cli.json_store import JsonTaskStore

    try:
        config = load_config()
        json_path = config.get_json_path()
        if json_path.exists():
            return JsonTaskStore(json_path)
    except Exception:
        pass
    return None


def complete_task_id(
    ctx: Context, param: Parameter, incomplete: str
) -> list[CompletionItem]:
    """Complete task IDs from the task store."""
    store = get_task_store()
    if not store:
        return []

    completions = []
    for task_id, task in store.get_all_tasks().items():
        if task_id.lower().startswith(incomplete.lower()):
            # Include task title as help text
            title = task.get("title", "")
            status = task.get("status", "")
            help_text = f"[{status}] {title[:40]}" if title else f"[{status}]"
            completions.append(CompletionItem(task_id, help=help_text))

    return completions


def complete_open_task_id(
    ctx: Context, param: Parameter, incomplete: str
) -> list[CompletionItem]:
    """Complete task IDs for open/in-progress tasks only."""
    store = get_task_store()
    if not store:
        return []

    completions = []
    for task_id, task in store.get_all_tasks().items():
        status = task.get("status", "open")
        if status in ("open", "in-progress", "blocked"):
            if task_id.lower().startswith(incomplete.lower()):
                title = task.get("title", "")
                help_text = f"[{status}] {title[:40]}" if title else f"[{status}]"
                completions.append(CompletionItem(task_id, help=help_text))

    return completions


def complete_done_task_id(
    ctx: Context, param: Parameter, incomplete: str
) -> list[CompletionItem]:
    """Complete task IDs for done tasks only (for reopen command)."""
    store = get_task_store()
    if not store:
        return []

    completions = []
    for task_id, task in store.get_all_tasks().items():
        status = task.get("status", "open")
        if status == "done":
            if task_id.lower().startswith(incomplete.lower()):
                title = task.get("title", "")
                help_text = f"{title[:50]}" if title else ""
                completions.append(CompletionItem(task_id, help=help_text))

    return completions


def complete_assignee(
    ctx: Context, param: Parameter, incomplete: str
) -> list[CompletionItem]:
    """Complete assignee names from existing tasks."""
    store = get_task_store()
    if not store:
        return []

    assignees = set()
    for task in store.get_all_tasks().values():
        assignee = task.get("assignee")
        if assignee:
            assignees.add(assignee)

    completions = []
    for assignee in sorted(assignees):
        if assignee.lower().startswith(incomplete.lower()):
            completions.append(CompletionItem(assignee))

    return completions


def complete_tag(
    ctx: Context, param: Parameter, incomplete: str
) -> list[CompletionItem]:
    """Complete tag names from existing tasks."""
    store = get_task_store()
    if not store:
        return []

    tags = set()
    for task in store.get_all_tasks().values():
        for tag in task.get("tags", []):
            tags.add(tag)

    completions = []
    for tag in sorted(tags):
        if tag.lower().startswith(incomplete.lower()):
            completions.append(CompletionItem(tag))

    return completions


def complete_status(
    ctx: Context, param: Parameter, incomplete: str
) -> list[CompletionItem]:
    """Complete status values."""
    statuses = ["open", "in-progress", "blocked", "done"]
    return [
        CompletionItem(s) for s in statuses if s.startswith(incomplete.lower())
    ]


def complete_priority(
    ctx: Context, param: Parameter, incomplete: str
) -> list[CompletionItem]:
    """Complete priority values."""
    priorities = ["low", "medium", "high", "critical"]
    return [
        CompletionItem(p) for p in priorities if p.startswith(incomplete.lower())
    ]


def _format_date(d: date) -> str:
    """Format date as 'Mon Jan 1' style."""
    return d.strftime("%a %b %-d")


def _next_weekday(weekday: int, after_today: bool = True) -> date:
    """Get next occurrence of a weekday (0=Monday, 6=Sunday).
    
    If after_today is True, always returns a future date.
    If after_today is False and today is that weekday, returns today.
    """
    today = date.today()
    days_ahead = weekday - today.weekday()
    if days_ahead < 0 or (days_ahead == 0 and after_today):
        days_ahead += 7
    return today + timedelta(days=days_ahead)


def _add_months(d: date, months: int) -> date:
    """Add months to a date, handling month-end edge cases."""
    month = d.month + months
    year = d.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    # Handle edge cases like Jan 31 + 1 month
    day = min(d.day, [31, 28 + (1 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 0), 
                      31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day)


def _end_of_week() -> date:
    """Get the end of the current week (Sunday)."""
    today = date.today()
    days_until_sunday = 6 - today.weekday()
    return today + timedelta(days=days_until_sunday)


def _end_of_month() -> date:
    """Get the last day of the current month."""
    today = date.today()
    if today.month == 12:
        return date(today.year + 1, 1, 1) - timedelta(days=1)
    return date(today.year, today.month + 1, 1) - timedelta(days=1)


def complete_date(
    ctx: Context, param: Parameter, incomplete: str
) -> list[CompletionItem]:
    """Complete date shortcuts with dynamic date calculation."""
    today = date.today()
    
    # Build shortcuts with actual resolved dates
    shortcuts = [
        # Named dates
        ("today", today),
        ("tomorrow", today + timedelta(days=1)),
        
        # Relative days
        ("+1d", today + timedelta(days=1)),
        ("+2d", today + timedelta(days=2)),
        ("+3d", today + timedelta(days=3)),
        ("+5d", today + timedelta(days=5)),
        ("+7d", today + timedelta(days=7)),
        ("+10d", today + timedelta(days=10)),
        ("+14d", today + timedelta(days=14)),
        ("+30d", today + timedelta(days=30)),
        
        # Relative weeks
        ("+1w", today + timedelta(weeks=1)),
        ("+2w", today + timedelta(weeks=2)),
        ("+3w", today + timedelta(weeks=3)),
        ("+4w", today + timedelta(weeks=4)),
        
        # Relative months
        ("+1m", _add_months(today, 1)),
        ("+2m", _add_months(today, 2)),
        ("+3m", _add_months(today, 3)),
        
        # Weekdays (next occurrence, could be today)
        ("monday", _next_weekday(0, after_today=False)),
        ("tuesday", _next_weekday(1, after_today=False)),
        ("wednesday", _next_weekday(2, after_today=False)),
        ("thursday", _next_weekday(3, after_today=False)),
        ("friday", _next_weekday(4, after_today=False)),
        ("saturday", _next_weekday(5, after_today=False)),
        ("sunday", _next_weekday(6, after_today=False)),
        
        # Next weekday (always in the future)
        ("next-monday", _next_weekday(0, after_today=True)),
        ("next-tuesday", _next_weekday(1, after_today=True)),
        ("next-wednesday", _next_weekday(2, after_today=True)),
        ("next-thursday", _next_weekday(3, after_today=True)),
        ("next-friday", _next_weekday(4, after_today=True)),
        ("next-saturday", _next_weekday(5, after_today=True)),
        ("next-sunday", _next_weekday(6, after_today=True)),
        
        # Period shortcuts
        ("next-week", today + timedelta(weeks=1)),
        ("end-of-week", _end_of_week()),
        ("end-of-month", _end_of_month()),
    ]
    
    return [
        CompletionItem(value, help=_format_date(target_date))
        for value, target_date in shortcuts
        if value.startswith(incomplete.lower())
    ]


def complete_series_id(
    ctx: Context, param: Parameter, incomplete: str
) -> list[CompletionItem]:
    """Complete series IDs from the task store."""
    store = get_task_store()
    if not store:
        return []

    completions = []
    for series_id, series_data in store.get_all_series().items():
        if series_id.lower().startswith(incomplete.lower()):
            title = series_data.get("title_template", "")
            help_text = f"{title[:40]}" if title else ""
            completions.append(CompletionItem(series_id, help=help_text))

    return completions


def complete_recurrence(
    ctx: Context, param: Parameter, incomplete: str
) -> list[CompletionItem]:
    """Complete recurrence pattern suggestions."""
    patterns = [
        ("every day", "Daily"),
        ("every monday", "Weekly on Monday"),
        ("every tuesday", "Weekly on Tuesday"),
        ("every wednesday", "Weekly on Wednesday"),
        ("every thursday", "Weekly on Thursday"),
        ("every friday", "Weekly on Friday"),
        ("every saturday", "Weekly on Saturday"),
        ("every sunday", "Weekly on Sunday"),
        ("every 2 weeks on monday", "Bi-weekly on Monday"),
        ("every 2 weeks on friday", "Bi-weekly on Friday"),
        ("every month on 1", "Monthly on the 1st"),
        ("every month on 15", "Monthly on the 15th"),
        ("every month on first monday", "First Monday of month"),
        ("every month on first friday", "First Friday of month"),
        ("every month on last friday", "Last Friday of month"),
        ("every 3 months on first monday", "Quarterly"),
    ]
    
    return [
        CompletionItem(value, help=desc)
        for value, desc in patterns
        if value.startswith(incomplete.lower())
    ]
