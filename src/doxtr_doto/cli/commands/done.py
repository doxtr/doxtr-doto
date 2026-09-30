"""doto done command - Mark tasks as done."""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

from doxtr_doto.cli.completion import complete_open_task_id

if TYPE_CHECKING:
    from doxtr_doto.cli.main import DotoContext


@click.command("done")
@click.argument("task_ids", nargs=-1, required=True, shell_complete=complete_open_task_id)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
@click.pass_obj
def done(
    ctx: DotoContext,
    task_ids: tuple[str, ...],
    json_output: bool,
) -> None:
    """Mark tasks as done.

    TASK_IDS are the identifiers of tasks to mark as done.
    Supports multiple task IDs.
    """
    formatter = ctx.formatter
    if json_output:
        formatter.json_output = True

    store = ctx.store

    completed = []
    not_found = []

    for task_id in task_ids:
        task = store.get_task(task_id)
        if task is None:
            not_found.append(task_id)
            continue

        if task.get("status") == "done":
            formatter.print_warning(f"Task {task_id} is already done.")
            continue

        store.update_task(task_id, {"status": "done"})
        completed.append(task_id)

    if completed:
        store.save()
        for task_id in completed:
            formatter.print_success(f"Marked {task_id} as done.")

    if not_found:
        for task_id in not_found:
            formatter.print_error(f"Task '{task_id}' not found.")

    if json_output:
        formatter.print_json({
            "completed": completed,
            "not_found": not_found,
        })
