"""doto series command - Manage recurring task series."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from typing import TYPE_CHECKING

import click

from doxtr_doto.cli.completion import complete_series_id
from doxtr_doto.cli.recurrence import RecurrencePattern, parse_recurrence

if TYPE_CHECKING:
    from doxtr_doto.cli.main import DotoContext
    from doxtr_doto.sync.json_store import JsonTaskStore


@click.group("series")
def series() -> None:
    """Manage recurring task series.

    A series is a collection of tasks generated from a recurrence pattern.
    Use 'doto add --repeat' to create a series, then manage it with these commands.
    """
    pass


@series.command("list")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
@click.pass_obj
def series_list(ctx: DotoContext, json_output: bool) -> None:
    """List all series."""
    formatter = ctx.formatter
    if json_output:
        formatter.json_output = True

    store = ctx.store
    all_series = store.get_all_series()

    if not all_series:
        formatter.print("No series found.")
        return

    if formatter.json_output:
        formatter.print_json(
            {"series": [{"id": sid, **sdata} for sid, sdata in all_series.items()]}
        )
        return

    # Print series list
    formatter.print(f"{'ID':<12} {'Progress':<10} {'Pattern':<30} {'Title'}")
    formatter.print("-" * 80)

    for series_id, series_data in sorted(all_series.items()):
        pattern = RecurrencePattern.from_dict(series_data["pattern"])
        tasks = store.get_tasks_in_series(series_id)

        # Count status
        done_count = sum(1 for t in tasks if t.get("status") == "done")
        total_count = len(tasks)
        progress = f"{done_count}/{total_count}"

        title = series_data["title_template"]
        if len(title) > 30:
            title = title[:27] + "..."

        formatter.print(f"{series_id:<12} {progress:<10} {pattern.describe():<30} {title}")


@series.command("show")
@click.argument("series_id", shell_complete=complete_series_id)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
@click.pass_obj
def series_show(ctx: DotoContext, series_id: str, json_output: bool) -> None:
    """Show details of a series and its tasks.

    SERIES_ID is the identifier of the series to show.
    """
    formatter = ctx.formatter
    if json_output:
        formatter.json_output = True

    store = ctx.store
    series_data = store.get_series(series_id)

    if series_data is None:
        raise click.ClickException(f"Series '{series_id}' not found.")

    tasks = store.get_tasks_in_series(series_id)
    pattern = RecurrencePattern.from_dict(series_data["pattern"])

    if formatter.json_output:
        formatter.print_json(
            {
                "id": series_id,
                **series_data,
                "pattern_description": pattern.describe(),
                "tasks": tasks,
            }
        )
        return

    # Print series info
    formatter.print(f"Series: {series_id}")
    formatter.print(f"  Title:   {series_data['title_template']}")
    formatter.print(f"  Pattern: {pattern.describe()}")
    formatter.print(f"  Start:   {series_data['start_date']}")
    formatter.print(f"  Until:   {series_data['end_date']}")
    formatter.print(f"  Created: {series_data['created'][:10]}")
    formatter.print("")

    # Count by status
    status_counts: dict[str, int] = {}
    for task in tasks:
        status = task.get("status", "open")
        status_counts[status] = status_counts.get(status, 0) + 1

    formatter.print(f"  Tasks: {len(tasks)} total")
    for status, count in sorted(status_counts.items()):
        formatter.print(f"    {status}: {count}")
    formatter.print("")

    # Print task list
    if tasks:
        formatter.print("  Occurrences:")
        formatter.format_task_table(
            tasks,
            columns=["id", "status", "due", "title"],
        )


@series.command("complete")
@click.argument("series_id", shell_complete=complete_series_id)
@click.option(
    "--before", "-b", "before_date", help="Complete tasks due before this date (default: today)."
)
@click.option(
    "--dry-run", "-n", is_flag=True, help="Show what would be completed without making changes."
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
@click.pass_obj
def series_complete(
    ctx: DotoContext,
    series_id: str,
    before_date: str | None,
    dry_run: bool,
    json_output: bool,
) -> None:
    """Mark all past tasks in a series as done.

    SERIES_ID is the identifier of the series.

    By default, completes all tasks with a due date before today.
    Use --before to specify a different cutoff date.
    """
    from doxtr_doto.cli.commands.add import parse_relative_date

    formatter = ctx.formatter
    if json_output:
        formatter.json_output = True

    store = ctx.store
    series_data = store.get_series(series_id)

    if series_data is None:
        raise click.ClickException(f"Series '{series_id}' not found.")

    # Parse cutoff date
    if before_date:
        cutoff = parse_relative_date(before_date)
    else:
        cutoff = date.today().isoformat()

    # Find tasks to complete
    tasks = store.get_tasks_in_series(series_id)
    to_complete = []
    for task in tasks:
        task_due = task.get("due")
        task_status = task.get("status", "open")

        if task_due and task_due < cutoff and task_status != "done":
            to_complete.append(task)

    if not to_complete:
        formatter.print("No tasks to complete.")
        return

    if formatter.json_output:
        result = {
            "series_id": series_id,
            "cutoff_date": cutoff,
            "dry_run": dry_run,
            "tasks_to_complete": [t["id"] for t in to_complete],
            "count": len(to_complete),
        }
        formatter.print_json(result)
        if dry_run:
            return

    if dry_run:
        formatter.print(f"Would complete {len(to_complete)} tasks (due before {cutoff}):")
        for task in to_complete:
            formatter.print(
                f"  {task['id']}: {task.get('title', '')} (due: {task.get('due', 'none')})"
            )
        return

    # Complete the tasks
    for task in to_complete:
        store.update_task(task["id"], {"status": "done"})

    store.save()
    formatter.print_success(f"Completed {len(to_complete)} tasks in series {series_id}")


@series.command("delete")
@click.argument("series_id", shell_complete=complete_series_id)
@click.option("--keep-tasks", is_flag=True, help="Keep the tasks, only delete the series metadata.")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
@click.option("--force", "-f", is_flag=True, hidden=True, help="Alias for --yes (deprecated).")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
@click.pass_obj
def series_delete(
    ctx: DotoContext,
    series_id: str,
    keep_tasks: bool,
    yes: bool,
    force: bool,
    json_output: bool,
) -> None:
    """Delete a series and optionally its tasks.

    ⚠️  This is a DESTRUCTIVE operation. Deleted series and tasks cannot be recovered.

    SERIES_ID is the identifier of the series to delete.

    By default, deletes both the series and all its tasks.
    Use --keep-tasks to only remove the series metadata while preserving the tasks.

    Confirmation is required unless --yes is provided.
    """
    formatter = ctx.formatter
    if json_output:
        formatter.json_output = True

    store = ctx.store
    series_data = store.get_series(series_id)

    if series_data is None:
        raise click.ClickException(f"Series '{series_id}' not found.")

    # --force is an alias for --yes (backward compatibility)
    skip_confirm = yes or force

    task_count = len(series_data.get("task_ids", []))

    # Confirmation
    if not skip_confirm and not json_output:
        if keep_tasks:
            msg = f"Delete series {series_id}? (tasks will be kept)"
        else:
            msg = f"Delete series {series_id} and {task_count} tasks?"
        if not click.confirm(msg):
            formatter.print("Cancelled.")
            return

    # Delete
    success, deleted_tasks = store.delete_series(series_id, delete_tasks=not keep_tasks)

    if not success:
        raise click.ClickException(f"Failed to delete series '{series_id}'.")

    store.save()

    if formatter.json_output:
        formatter.print_json(
            {
                "deleted_series": series_id,
                "deleted_tasks": deleted_tasks,
                "tasks_kept": keep_tasks,
            }
        )
        return

    if keep_tasks:
        formatter.print_success(f"Deleted series {series_id} (kept {task_count} tasks)")
    else:
        formatter.print_success(f"Deleted series {series_id} and {len(deleted_tasks)} tasks")


@series.command("extend")
@click.argument("series_id", shell_complete=complete_series_id)
@click.argument("new_until")
@click.option(
    "--dry-run", "-n", is_flag=True, help="Show what would be created without making changes."
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
@click.pass_obj
def series_extend(
    ctx: DotoContext,
    series_id: str,
    new_until: str,
    dry_run: bool,
    json_output: bool,
) -> None:
    """Extend a series with a new end date.

    SERIES_ID is the identifier of the series.
    NEW_UNTIL is the new end date (YYYY-MM-DD or relative like +3m).

    Creates additional tasks for the extended period.
    """
    from doxtr_doto.cli.commands.add import parse_relative_date
    from doxtr_doto.cli.recurrence import build_series_task_data, generate_occurrences

    formatter = ctx.formatter
    if json_output:
        formatter.json_output = True

    store = ctx.store
    config = ctx.config
    series_data = store.get_series(series_id)

    if series_data is None:
        raise click.ClickException(f"Series '{series_id}' not found.")

    # Parse new end date
    new_until_date = parse_relative_date(new_until)
    old_until_date = series_data["end_date"]

    if new_until_date <= old_until_date:
        raise click.ClickException(
            f"New end date ({new_until_date}) must be after current end date ({old_until_date})."
        )

    # Generate new occurrences
    pattern = RecurrencePattern.from_dict(series_data["pattern"])
    start_after = date.fromisoformat(old_until_date) + timedelta(days=1)
    end = date.fromisoformat(new_until_date)

    new_dates = list(generate_occurrences(pattern, start_after, end))

    if not new_dates:
        formatter.print("No new occurrences to create.")
        return

    if formatter.json_output and dry_run:
        formatter.print_json(
            {
                "series_id": series_id,
                "old_until": old_until_date,
                "new_until": new_until_date,
                "dry_run": True,
                "new_occurrences": [d.isoformat() for d in new_dates],
                "count": len(new_dates),
            }
        )
        return

    if dry_run:
        formatter.print(
            f"Would extend series {series_id} from {old_until_date} to {new_until_date}:"
        )
        formatter.print(f"  New occurrences: {len(new_dates)}")
        for d in new_dates[:10]:
            formatter.print(f"    {d.isoformat()}")
        if len(new_dates) > 10:
            formatter.print(f"    ... and {len(new_dates) - 10} more")
        return

    # Create new tasks
    title_template = series_data["title_template"]
    task_defaults = series_data.get("task_defaults", {})
    new_task_ids = []

    for occurrence_date in new_dates:
        task_id = store.generate_id(
            prefix=config.id_prefix,
            sequential=config.id_sequential,
        )

        # Build the task via the shared helper so extended occurrences get the
        # same time-bearing ``due`` + ``estimate`` (from the pattern) as the
        # original ``doto add --repeat`` create path.
        task_data = build_series_task_data(
            pattern,
            occurrence_date,
            title_template,
            series_id,
            task_defaults,
        )

        store.add_task(task_id, task_data)
        new_task_ids.append(task_id)

    # Update series
    all_task_ids = series_data.get("task_ids", []) + new_task_ids
    store.update_series(
        series_id,
        {
            "end_date": new_until_date,
            "task_ids": all_task_ids,
        },
    )

    store.save()

    if formatter.json_output:
        formatter.print_json(
            {
                "series_id": series_id,
                "old_until": old_until_date,
                "new_until": new_until_date,
                "new_tasks": new_task_ids,
                "count": len(new_task_ids),
            }
        )
        return

    formatter.print_success(f"Extended series {series_id} to {new_until_date}")
    formatter.print(f"  Created {len(new_task_ids)} new tasks")


@series.command("update")
@click.argument("series_id", shell_complete=complete_series_id)
@click.option(
    "--from",
    "from_anchor",
    help="Anchor for the forward-only re-stamp: a task id OR a date "
    "(YYYY-MM-DD or relative like +1w). Required unless --metadata-only.",
)
@click.option("--at", "at_time", help="Set the per-occurrence start time (e.g. 16:00).")
@click.option("--no-time", is_flag=True, help="Clear the per-occurrence start time.")
@click.option("--for", "for_duration", help="Set the per-occurrence duration (e.g. 2h, 90m).")
@click.option("--no-duration", is_flag=True, help="Clear the per-occurrence duration.")
@click.option("--repeat", help="Replace the calendar pattern (e.g. 'every 2 weeks on monday').")
@click.option("--title", "title_template", help="Replace the series title template.")
@click.option(
    "--metadata-only",
    is_flag=True,
    help="Update the stored pattern/title only; re-stamp no tasks.",
)
@click.option(
    "--dry-run", "-n", is_flag=True, help="Show what would change without making changes."
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
@click.pass_obj
def series_update(
    ctx: DotoContext,
    series_id: str,
    from_anchor: str | None,
    at_time: str | None,
    no_time: bool,
    for_duration: str | None,
    no_duration: bool,
    repeat: str | None,
    title_template: str | None,
    metadata_only: bool,
    dry_run: bool,
    json_output: bool,
) -> None:
    """Update a recurring series and re-stamp its forward occurrences.

    SERIES_ID is the identifier of the series.

    Replaces the stored pattern (--repeat), start time (--at / --no-time),
    duration (--for / --no-duration) and/or title template (--title). The
    re-stamp is FORWARD-ONLY: only occurrences whose due date is on or after
    the --from anchor are changed, and done/archived occurrences are skipped.
    Occurrences before the anchor are never modified.

    The --from anchor accepts a task id (its due date is used) OR a date
    (YYYY-MM-DD or relative). It is required whenever a task re-stamp is
    requested (i.e. not --metadata-only).

    Changing the calendar SHAPE of the pattern only re-stamps
    time/duration/title onto the EXISTING forward dates; it does not move or
    add occurrence dates. Use 'doto series extend' to add dates.
    """
    from datetime import time as _time

    from doxtr_doto.cli.commands.add import parse_relative_date
    from doxtr_doto.cli.tui import actions
    from doxtr_doto.date_utils import parse_duration, parse_time_token

    formatter = ctx.formatter
    if json_output:
        formatter.json_output = True

    store = ctx.store
    series_data = store.get_series(series_id)
    if series_data is None:
        raise click.ClickException(f"Series '{series_id}' not found.")

    # Mutually-exclusive flag checks.
    if at_time is not None and no_time:
        raise click.ClickException("--at and --no-time are mutually exclusive.")
    if for_duration is not None and no_duration:
        raise click.ClickException("--for and --no-duration are mutually exclusive.")

    # Require at least one mutating option.
    mutating = any(
        [
            repeat is not None,
            at_time is not None,
            no_time,
            for_duration is not None,
            no_duration,
            title_template is not None,
        ]
    )
    if not mutating:
        raise click.ClickException("nothing to update (pass --repeat/--at/--for/--title/...).")

    # Build the effective pattern from the stored one, applying --repeat first
    # (a trailing at/for in the string is honored unless overridden by flags),
    # then the explicit time/duration flags.
    pattern_dict = series_data["pattern"]
    stored_pattern = RecurrencePattern.from_dict(pattern_dict)
    if repeat is not None:
        new_pattern = parse_recurrence(repeat)
    else:
        # A distinct instance (not an alias of stored_pattern) so the
        # time/duration mutations below do not corrupt the later
        # ``new_pattern.to_dict() != stored_pattern.to_dict()`` comparison.
        new_pattern = RecurrencePattern.from_dict(pattern_dict)

    new_start_time: _time | None = new_pattern.start_time
    if at_time is not None:
        try:
            new_start_time = parse_time_token(at_time)
        except ValueError as exc:
            raise click.ClickException(f"Invalid --at time: {exc}") from exc
    elif no_time:
        new_start_time = None

    new_duration: int | None = new_pattern.duration_minutes
    if for_duration is not None:
        try:
            new_duration = parse_duration(for_duration)
        except (ValueError, TypeError) as exc:
            raise click.ClickException(f"Invalid --for duration: {exc}") from exc
    elif no_duration:
        new_duration = None

    new_pattern.start_time = new_start_time
    new_pattern.duration_minutes = new_duration

    # Resolve the anchor date (unless metadata-only).
    anchor_date: date | None = None
    if not metadata_only:
        if not from_anchor:
            raise click.ClickException(
                "--from is required unless --metadata-only (anchor a task id or a date)."
            )
        anchor_date = _resolve_series_anchor(store, series_id, from_anchor, parse_relative_date)
    pattern_changed = new_pattern.to_dict() != stored_pattern.to_dict()
    result = actions.update_series(
        ctx,
        series_id,
        pattern=new_pattern if pattern_changed else None,
        title_template=title_template,
        anchor_date=anchor_date,
        dry_run=dry_run,
    )

    if formatter.json_output:
        formatter.print_json(
            {
                "series_id": result.series_id,
                "anchor": anchor_date.isoformat() if anchor_date else None,
                "old_pattern": result.old_pattern_desc,
                "new_pattern": result.new_pattern_desc,
                "title_template": title_template,
                "updated_tasks": result.updated_task_ids,
                "skipped_before_anchor": result.skipped_before_anchor,
                "skipped_done": result.skipped_done,
                "dry_run": dry_run,
            }
        )
        return

    verb = "Would update" if dry_run else "Updated"
    formatter.print_success(f"{verb} series {series_id}")
    formatter.print(f"  Pattern: {result.old_pattern_desc} -> {result.new_pattern_desc}")
    if title_template is not None:
        formatter.print(f"  Title:   {title_template}")
    if anchor_date is not None:
        formatter.print(f"  Anchor:  {anchor_date.isoformat()} (forward-only)")
        formatter.print(f"  Re-stamped: {len(result.updated_task_ids)} occurrences")
        formatter.print(f"  Skipped (before anchor): {result.skipped_before_anchor}")
        formatter.print(f"  Skipped (done/archived): {len(result.skipped_done)}")
    else:
        formatter.print("  Metadata-only: no tasks were re-stamped.")
    if pattern_changed:
        formatter.print(
            "  Note: existing due dates were kept; use 'doto series extend' to add dates."
        )


def _resolve_series_anchor(
    store: JsonTaskStore,
    series_id: str,
    from_anchor: str,
    parse_relative_date: Callable[[str], str],
) -> date:
    """Resolve a ``--from`` anchor (a task id or a date) to a calendar date.

    A task id is looked up within the series and resolved to that task's due
    date; a date (absolute or relative) resolves directly. Both forms are
    accepted because a date is unambiguous within a single series. Prefers the
    task-id interpretation when the string matches an occurrence's id.

    Args:
        store: The task store.
        series_id: The series the anchor task must belong to.
        from_anchor: The raw ``--from`` value.
        parse_relative_date: The ``parse_relative_date`` callable.

    Returns:
        The resolved anchor :class:`datetime.date`.

    Raises:
        click.ClickException: If the value is neither a known occurrence id in
            the series nor a parseable date.
    """
    from doxtr_doto.date_utils import DotoDate

    # Task-id interpretation first: match an occurrence in this series.
    for task in store.get_tasks_in_series(series_id):
        if task["id"] == from_anchor:
            parsed = DotoDate.parse_safe(task.get("due"))
            if parsed is None:
                raise click.ClickException(
                    f"Anchor task '{from_anchor}' has no due date to anchor on."
                )
            return parsed.date

    # Date interpretation.
    try:
        iso = parse_relative_date(from_anchor)
        return date.fromisoformat(iso.split("T")[0])
    except ValueError as exc:
        raise click.ClickException(
            f"--from '{from_anchor}' is not a task in series {series_id} nor a valid date."
        ) from exc
