"""doto stop command - pause focus and optionally clock out.

``stop`` closes the active focus session but keeps the global work clock
running. ``stop work`` closes the focus session (if any) and also stops the
global work clock (clock out).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

from doxtr_doto.cli.session import (
    WORK_REPO,
    resolve_session_store,
)
from doxtr_doto.time_tracking import close_session, has_open_session

if TYPE_CHECKING:
    from doxtr_doto.cli.main import DotoContext


def _close_orphan_focus(ctx: DotoContext) -> str | None:
    """Close an orphaned open worklog in the current store, if any.

    Recovers from a desync where a task still carries an open worklog (the
    TUI's green focus arrow stays on) while global state has no
    ``active_session`` pointing at it - e.g. after a crash, a manual edit, or
    a ``stop`` that cleared the pointer without closing the worklog. ``start``
    already self-heals its target task's worklogs; this gives ``stop`` the
    matching recovery path so such a task can never get permanently stuck
    running.

    Scans ``ctx.store`` for the first task with an open worklog and closes it.

    Args:
        ctx: The CLI context.

    Returns:
        The id of the task whose orphaned worklog was closed, or None if the
        current store had no open worklog.
    """
    store = ctx.store
    store.load()
    for task_id, task in store.get_all_tasks().items():
        if has_open_session(task.get("worklogs", [])):
            closed = close_session(task.get("worklogs", []))
            store.update_task(task_id, {"worklogs": closed})
            store.save()
            return task_id
    return None


def stop_focus(ctx: DotoContext) -> str | None:
    """Close the active focus session, if any.

    Clears the active session from global state and closes the open worklog
    in the owning task store. When global state has no active session but the
    current store still holds an orphaned open worklog, falls back to
    :func:`_close_orphan_focus` so a desynced task can still be stopped.

    Args:
        ctx: The CLI context.

    Returns:
        The task id of the stopped focus session, or None if nothing was
        running.
    """
    state = ctx.global_store.load()
    session = state.active_session
    if not session or not session.get("task_id"):
        # No pointer in global state. A task may still carry an orphaned open
        # worklog (pointer and worklog drifted apart); close it so the task is
        # not permanently stuck in the running state.
        return _close_orphan_focus(ctx)

    task_id: str = session["task_id"]
    store = resolve_session_store(ctx.store, session.get("json_path"))
    # Reload from disk before the read-modify-write. ``resolve_session_store``
    # may hand back the long-lived ``ctx.store`` instance whose cache is stale
    # relative to writes made through a different store instance for the same
    # path (the TUI reuses one context across presses while ``start`` opens the
    # worklog through a freshly resolved store). Without the reload the close
    # would clobber disk with the stale snapshot, leaving the open worklog -
    # and the TUI's green focus arrow - stuck on.
    store.load()
    task = store.get_task(task_id)
    if task is not None:
        task["worklogs"] = close_session(task.get("worklogs", []))
        store.update_task(task_id, {"worklogs": task["worklogs"]})
        store.save()

    state.active_session = None
    ctx.global_store.save(state)
    return task_id


def stop_work_clock(ctx: DotoContext) -> bool:
    """Close the global work clock if it is running.

    Args:
        ctx: The CLI context.

    Returns:
        True if the work clock was stopped, False if it was not running.
    """
    state = ctx.global_store.load()
    if not has_open_session(state.work_clock.worklogs):
        return False
    state.work_clock.worklogs = close_session(state.work_clock.worklogs)
    ctx.global_store.save(state)
    return True


@click.command("stop")
@click.argument("target", required=False)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
@click.pass_obj
def stop(
    ctx: DotoContext,
    target: str | None,
    json_output: bool,
) -> None:
    """Stop the active focus timer, keeping the work clock running.

    Use ``stop work`` to also clock out (stop the global work clock).
    """
    formatter = ctx.formatter
    if json_output:
        formatter.json_output = True

    stop_work = target is not None and target.lower() == WORK_REPO

    stopped_focus = stop_focus(ctx)
    clocked_out = False
    if stop_work:
        clocked_out = stop_work_clock(ctx)

    if json_output:
        formatter.print_json(
            {
                "action": "stop",
                "stopped_focus": stopped_focus,
                "clocked_out": clocked_out,
            }
        )
        return

    if stopped_focus:
        formatter.print_success(f"Stopped focus timer for {stopped_focus}.")
    else:
        formatter.print_warning("No active focus session.")

    if stop_work:
        if clocked_out:
            formatter.print_success("Clocked out. Work clock stopped.")
        else:
            formatter.print_warning("Work clock was not running.")
