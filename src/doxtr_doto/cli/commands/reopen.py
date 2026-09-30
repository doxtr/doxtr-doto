"""doto reopen command - Reopen archived tasks."""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

from doxtr_doto.cli.completion import complete_done_task_id

if TYPE_CHECKING:
    from doxtr_doto.cli.main import DotoContext


@click.command("reopen")
@click.argument("task_ids", nargs=-1, required=True, shell_complete=complete_done_task_id)
@click.option(
    "--status",
    "-s",
    type=click.Choice(["open", "in-progress", "blocked"]),
    default="open",
    help="Status for reopened tasks.",
)
@click.option("--file", "-f", "rst_file", help="Target RST file (overrides original).")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
@click.pass_obj
def reopen(
    ctx: DotoContext,
    task_ids: tuple[str, ...],
    status: str,
    rst_file: str | None,
    json_output: bool,
) -> None:
    """Reopen archived tasks.

    TASK_IDS are the identifiers of archived tasks to reopen.
    Supports multiple task IDs.

    Reopened tasks will be written to their original RST file on the next
    Sphinx build, or to the inbox file if the original file doesn't exist.
    Use --file to specify a different target RST file.
    """
    formatter = ctx.formatter
    if json_output:
        formatter.json_output = True

    store = ctx.store

    reopened = []
    not_found = []
    not_archived = []

    for task_id in task_ids:
        task = store.get_task(task_id)
        if task is None:
            not_found.append(task_id)
            continue

        if not task.get("archived"):
            not_archived.append(task_id)
            continue

        success = store.reopen_task(task_id, status=status, target_file=rst_file)
        if success:
            reopened.append(task_id)

    if reopened:
        store.save()
        for task_id in reopened:
            formatter.print_success(f"Reopened {task_id} with status '{status}'.")

    if not_archived:
        for task_id in not_archived:
            formatter.print_warning(f"Task {task_id} is not archived.")

    if not_found:
        for task_id in not_found:
            formatter.print_error(f"Task '{task_id}' not found.")

    if json_output:
        formatter.print_json({
            "reopened": reopened,
            "not_archived": not_archived,
            "not_found": not_found,
        })
