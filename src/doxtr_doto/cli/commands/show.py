"""doto show command - Show task details."""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

from doxtr_doto.cli.completion import complete_task_id
from doxtr_doto.cli.id_resolver import resolve_task_ref

if TYPE_CHECKING:
    from doxtr_doto.cli.main import DotoContext


@click.command("show")
@click.argument("task_id", shell_complete=complete_task_id)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
@click.pass_obj
def show(
    ctx: DotoContext,
    task_id: str,
    json_output: bool,
) -> None:
    """Show details of a specific task.

    TASK_ID is the identifier of the task to show.
    """
    formatter = ctx.formatter
    if json_output:
        formatter.json_output = True

    resolved = resolve_task_ref(ctx, task_id)
    if resolved is None:
        raise click.ClickException(f"Task '{task_id}' not found.")
    store = resolved.store
    local_id = resolved.task_id

    # Get task
    task = store.get_task(local_id)
    if task is None:
        raise click.ClickException(f"Task '{task_id}' not found.")

    # Add series info if part of a series
    task_with_id = {"id": task_id, **task}
    series_id = task.get("series_id")
    if series_id:
        series = store.get_series(str(series_id))
        if series:
            from doxtr_doto.cli.recurrence import RecurrencePattern

            pattern = RecurrencePattern.from_dict(series["pattern"])
            task_with_id["_series_info"] = {
                "series_id": series_id,
                "pattern": pattern.describe(),
                "until": series["end_date"],
            }

    # Display task
    formatter.format_task_detail(task_with_id)
