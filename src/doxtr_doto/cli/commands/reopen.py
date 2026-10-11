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
    """Reopen archived tasks, restoring them to their original place.

    TASK_IDS are the identifiers of archived tasks to reopen.
    Supports multiple task IDs.

    Each reopened task's directive is re-inserted into the RST file it was
    archived from, at the same position (using the restore anchor captured
    when it was archived). If the file was heavily modified and the original
    position can no longer be found, the directive is placed at the top of the
    page instead. If the original page was renamed or deleted, the task is NOT
    relocated: it stays archived and an error naming the original page title
    and path is printed so you can retrace where it belonged.

    Use ``--file`` to force a specific target RST file (skips anchor restore;
    the directive is written there on the next Sphinx build).
    """
    formatter = ctx.formatter
    if json_output:
        formatter.json_output = True

    from doxtr_doto.sync.restore import RestoreResult

    store = ctx.store
    srcdir = ctx.config.source_dir

    reopened: list[str] = []
    restore_paths: dict[str, str] = {}
    not_found = []
    not_archived = []
    failed: list[dict[str, str]] = []

    for task_id in task_ids:
        task = store.get_task(task_id)
        if task is None:
            not_found.append(task_id)
            continue

        if not task.get("archived"):
            not_archived.append(task_id)
            continue

        if rst_file:
            # Explicit target override: legacy write-on-next-build behavior.
            success = store.reopen_task(task_id, status=status, target_file=rst_file)
            if success:
                reopened.append(task_id)
                restore_paths[task_id] = "target_file"
            continue

        # Restore-to-place: result is a RestoreResult (or a bool when the task
        # had no recorded origin and the legacy path was taken).
        result = store.reopen_task(task_id, status=status, srcdir=srcdir)

        if isinstance(result, RestoreResult):
            if result.success:
                reopened.append(task_id)
                restore_paths[task_id] = result.path.value
            else:
                failed.append(
                    {
                        "id": task_id,
                        "restore_path": result.path.value,
                        "message": result.message,
                    }
                )
        elif result:
            reopened.append(task_id)
            restore_paths[task_id] = "inbox"

    if reopened or failed:
        store.save()

    for task_id in reopened:
        path = restore_paths.get(task_id, "")
        if path == "anchor":
            where = "restored to its original location"
        elif path == "top_of_page":
            where = "restored to the top of its original page (file was heavily modified)"
        elif path == "target_file":
            where = f"will be written to {rst_file} on next build"
        elif path == "inbox":
            where = "will be written to the inbox on next build"
        else:
            where = "reopened"
        formatter.print_success(f"Reopened {task_id} with status '{status}' ({where}).")

    for item in failed:
        # Renamed/deleted page: surface the retrace message, keep task archived.
        formatter.print_error(f"Could not reopen {item['id']}: {item['message']}")

    if not_archived:
        for task_id in not_archived:
            formatter.print_warning(f"Task {task_id} is not archived.")

    if not_found:
        for task_id in not_found:
            formatter.print_error(f"Task '{task_id}' not found.")

    if json_output:
        formatter.print_json(
            {
                "reopened": reopened,
                "restore_paths": restore_paths,
                "failed": failed,
                "not_archived": not_archived,
                "not_found": not_found,
            }
        )

    # Exit non-zero when there were renamed/deleted-page failures and nothing
    # was reopened, so scripts can detect the retrace case. If at least one
    # task reopened, exit zero (partial success) and let the per-task messages
    # carry the failures.
    if failed and not reopened:
        ctx_obj = click.get_current_context()
        ctx_obj.exit(1)
