"""doto log command - list session intervals and recover stale sessions.

Lists the individual work intervals for a task (start -> stop with
duration), including a live row for an open session. Supports filtering by
day, and recovering/editing unclosed or overnight sessions via ``--fix`` and
``--edit``.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import click

from doxtr_doto.cli.completion import complete_task_id
from doxtr_doto.cli.id_resolver import resolve_task_ref
from doxtr_doto.cli.session import (
    derive_repo_name,
    namespaced_id,
    render_log,
)
from doxtr_doto.time_tracking import (
    close_session,
    detect_overnight,
    discard_session,
    has_open_session,
    parse_timestamp,
    split_at_midnight,
)

if TYPE_CHECKING:
    from doxtr_doto.cli.main import DotoContext
    from doxtr_doto.cli.output import OutputFormatter
    from doxtr_doto.sync.json_store import JsonTaskStore, TaskData


def _clear_active_if_matches(ctx: DotoContext, task_id: str) -> None:
    """Clear the global active session if it points at ``task_id``.

    Used after a ``--fix``/``--edit`` closes or discards the task's open
    session so global state does not keep a dangling focus pointer.

    Args:
        ctx: The CLI context.
        task_id: The local task identifier whose open session was resolved.
    """
    state = ctx.global_store.load()
    session = state.active_session
    if session and session.get("task_id") == task_id:
        state.active_session = None
        ctx.global_store.save(state)


@click.command("log")
@click.argument("task_id", required=False, shell_complete=complete_task_id)
@click.option("--day", help="Filter sessions by start date (YYYY-MM-DD).")
@click.option(
    "--fix",
    type=click.Choice(["split", "close", "discard"]),
    help="Recover an unclosed/overnight session: split at midnight, close now, or discard it.",
)
@click.option(
    "--edit",
    "edit_stop",
    help="Set the open session's stop time to this ISO 8601 timestamp.",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
@click.pass_obj
def log(
    ctx: DotoContext,
    task_id: str | None,
    day: str | None,
    fix: str | None,
    edit_stop: str | None,
    json_output: bool,
) -> None:
    """Show session intervals for a task.

    TASK_ID defaults to the active focus task. ``--day`` filters by start
    date. ``--fix`` recovers an unclosed/overnight session; ``--edit`` sets
    the open session's stop time explicitly.
    """
    formatter = ctx.formatter
    if json_output:
        formatter.json_output = True

    repo = derive_repo_name(ctx.config)

    # Resolve the target task: explicit arg, else the active focus task.
    if task_id is None:
        state = ctx.global_store.load()
        if state.active_session and state.active_session.get("task_id"):
            task_id = state.active_session["task_id"]
        else:
            formatter.print_error("No task specified and no active session.")
            return

    # Resolve the (possibly namespaced) reference the same way the sibling
    # verbs (done/show/update/start/status) do so ``doto log repo#id`` reads
    # the foreign repo's store rather than the local one.
    resolved = resolve_task_ref(ctx, task_id)
    if resolved is None:
        formatter.print_error(f"Task '{task_id}' not found.")
        if json_output:
            formatter.print_json({"not_found": task_id})
        return
    store = resolved.store
    local_id = resolved.task_id
    task = store.get_task(local_id)
    if task is None:
        formatter.print_error(f"Task '{local_id}' not found.")
        if json_output:
            formatter.print_json({"not_found": local_id})
        return

    now = datetime.now().astimezone()

    if edit_stop is not None:
        _apply_edit(ctx, store, local_id, task, edit_stop, formatter)
    elif fix is not None:
        _apply_fix(ctx, store, local_id, task, fix, now, formatter)

    worklogs = task.get("worklogs", [])
    # Namespace the display id only when the task lives in another repo.
    if resolved.repo and resolved.repo != repo:
        display_id = namespaced_id(resolved.repo, local_id)
    else:
        display_id = local_id

    if json_output:
        formatter.print_json(
            {
                "task_id": local_id,
                "worklogs": worklogs,
            }
        )
        return

    render_log(
        formatter,
        display_id=display_id,
        worklogs=worklogs,
        now=now,
        day=day,
    )


def _apply_edit(
    ctx: DotoContext,
    store: JsonTaskStore,
    local_id: str,
    task: TaskData,
    edit_stop: str,
    formatter: OutputFormatter,
) -> None:
    """Set the open session's stop time to an explicit timestamp.

    Args:
        ctx: The CLI context.
        store: The task store owning the task.
        local_id: The local task identifier.
        task: The task data dict.
        edit_stop: The ISO 8601 stop timestamp to apply.
        formatter: The output formatter.
    """
    worklogs = task.get("worklogs", [])
    if not has_open_session(worklogs):
        formatter.print_warning(f"No open session for {local_id} to edit.")
        return
    try:
        stop_dt = parse_timestamp(edit_stop)
    except ValueError:
        formatter.print_error(f"Invalid timestamp: {edit_stop!r}.")
        return
    task["worklogs"] = close_session(worklogs, now=stop_dt)
    store.update_task(local_id, {"worklogs": task["worklogs"]})
    store.save()
    _clear_active_if_matches(ctx, local_id)
    formatter.print_success(f"Set stop time for {local_id}'s session to {stop_dt.isoformat()}.")


def _apply_fix(
    ctx: DotoContext,
    store: JsonTaskStore,
    local_id: str,
    task: TaskData,
    fix: str,
    now: datetime,
    formatter: OutputFormatter,
) -> None:
    """Recover an unclosed/overnight session.

    Args:
        ctx: The CLI context.
        store: The task store owning the task.
        local_id: The local task identifier.
        task: The task data dict.
        fix: One of ``split``, ``close`` or ``discard``.
        now: Reference "current" time.
        formatter: The output formatter.
    """
    worklogs = task.get("worklogs", [])
    if not has_open_session(worklogs):
        formatter.print_warning(f"No open session for {local_id} to fix.")
        return

    overnight = detect_overnight(worklogs, now=now)

    if fix == "split":
        task["worklogs"] = split_at_midnight(worklogs, now=now)
        store.update_task(local_id, {"worklogs": task["worklogs"]})
        store.save()
        if overnight:
            formatter.print_success(f"Split {local_id}'s overnight session at midnight.")
        else:
            formatter.print_warning(f"{local_id}'s session started today; nothing to split.")
    elif fix == "close":
        task["worklogs"] = close_session(worklogs, now=now)
        store.update_task(local_id, {"worklogs": task["worklogs"]})
        store.save()
        _clear_active_if_matches(ctx, local_id)
        formatter.print_success(f"Closed {local_id}'s open session.")
    else:  # discard
        task["worklogs"] = discard_session(worklogs)
        store.update_task(local_id, {"worklogs": task["worklogs"]})
        store.save()
        _clear_active_if_matches(ctx, local_id)
        formatter.print_success(f"Discarded {local_id}'s open session.")
