"""doto archive command - Archive tasks."""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

from doxtr_doto.cli.completion import complete_task_id

if TYPE_CHECKING:
    from doxtr_doto.cli.main import DotoContext


@click.command("archive")
@click.argument("task_ids", nargs=-1, required=True, shell_complete=complete_task_id)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
@click.pass_obj
def archive(
    ctx: DotoContext,
    task_ids: tuple[str, ...],
    yes: bool,
    json_output: bool,
) -> None:
    """Archive tasks.

    TASK_IDS are the identifiers of tasks to archive.
    Archived tasks are hidden from normal listings but can be
    viewed with --archived flag and reopened later.

    Unlike delete, archiving is reversible - use 'doto reopen' to restore.

    When archiving multiple tasks, confirmation is required unless --yes is provided.

    Examples:

        doto archive DOTO-001

        doto archive DOTO-001 DOTO-002 DOTO-003 --yes

        doto archive DOTO-001 --json
    """
    formatter = ctx.formatter
    if json_output:
        formatter.json_output = True

    store = ctx.store

    archived = []
    not_found = []
    already_archived = []

    # Collect tasks to archive first (for confirmation)
    tasks_to_archive = []
    for task_id in task_ids:
        task = store.get_task(task_id)
        if task is None:
            not_found.append(task_id)
        elif task.get("archived"):
            already_archived.append(task_id)
        else:
            tasks_to_archive.append((task_id, task))

    # Confirmation prompt for bulk operations (unless --yes or --json)
    if tasks_to_archive and not yes and not json_output:
        if len(tasks_to_archive) > 1:
            formatter.print(f"About to archive {len(tasks_to_archive)} tasks:")
            for task_id, task in tasks_to_archive[:5]:
                title = task.get("title", "")
                formatter.print(f"  {task_id}: {title}")
            if len(tasks_to_archive) > 5:
                formatter.print(f"  ... and {len(tasks_to_archive) - 5} more")
            if not click.confirm("\nArchive these tasks?"):
                formatter.print("Cancelled.")
                return
        else:
            task_id, task = tasks_to_archive[0]
            title = task.get("title", task_id)
            if not click.confirm(f"Archive '{title}' ({task_id})?"):
                formatter.print("Cancelled.")
                return

    # Perform archiving
    for task_id, _task in tasks_to_archive:
        if store.archive_task(task_id):
            archived.append(task_id)

    # Save if any changes were made
    if archived:
        store.save()
        if not json_output:
            for task_id in archived:
                formatter.print_success(f"Archived task {task_id}")

    # Report warnings (only in non-JSON mode)
    if not json_output:
        for task_id in already_archived:
            formatter.print_warning(f"Task {task_id} is already archived.")

        # Report errors
        for task_id in not_found:
            formatter.print_error(f"Task '{task_id}' not found.")

    # JSON output
    if json_output:
        formatter.print_json(
            {
                "archived": archived,
                "already_archived": already_archived,
                "not_found": not_found,
            }
        )
