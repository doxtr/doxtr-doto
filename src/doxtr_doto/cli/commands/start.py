"""doto start command - clock in and start focus timers.

``start`` with no argument (or ``start work``) clocks in the global
Layer-1 work clock. ``start <task-id>`` auto-clocks-in the work clock if
needed and then opens a Layer-2 focus session for the task, auto-stopping any
previously running focus session first.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

from doxtr_doto.cli.completion import complete_open_task_id
from doxtr_doto.cli.id_resolver import ResolvedTask, resolve_task_ref
from doxtr_doto.cli.session import (
    WORK_REPO,
    resolve_session_store,
)
from doxtr_doto.time_tracking import (
    close_session,
    has_open_session,
    start_session,
)

if TYPE_CHECKING:
    from doxtr_doto.cli.main import DotoContext


def clock_in_work(ctx: DotoContext) -> bool:
    """Open the global work clock if it is not already running.

    Args:
        ctx: The CLI context.

    Returns:
        True if the work clock was newly started, False if already running.
    """
    state = ctx.global_store.load()
    if has_open_session(state.work_clock.worklogs):
        return False
    state.work_clock.worklogs = start_session(state.work_clock.worklogs)
    ctx.global_store.save(state)
    return True


def start_focus(ctx: DotoContext, resolved: ResolvedTask) -> tuple[bool, str | None]:
    """Start a focus timer for a resolved task.

    Auto clocks-in the global work clock if needed, auto-stops any previously
    running focus session, opens a new focus worklog on the task, and records
    the active session in global state. This is the single implementation used
    by both the ``start`` CLI command and the TUI's ``s`` toggle so the two
    never diverge.

    Enforces the single-open-session invariant: any pre-existing open worklog
    on the target task is closed before the new focus worklog is opened, so a
    task never holds two open worklogs (which would leave the TUI's focus
    arrow stuck on after a single stop).

    Args:
        ctx: The CLI context.
        resolved: The resolved task to focus on.

    Returns:
        A tuple ``(work_clocked_in, stopped_previous)`` where
        ``work_clocked_in`` is True if the work clock was newly started and
        ``stopped_previous`` is the local id of a focus session that was
        auto-stopped (or None).
    """
    store = resolved.store
    local_id = resolved.task_id
    repo = resolved.repo
    # Read against on-disk truth. The TUI reuses one long-lived context (and
    # thus one ``ctx.store``) across presses while ``resolve_task_ref`` hands
    # ``start``/``stop`` fresh store instances for namespaced ids; reloading
    # here guarantees this instance's cache reflects what other instances have
    # already persisted so we never read a stale worklog list.
    store.load()
    task = store.get_task(local_id)
    if task is None:
        raise ValueError(f"Task '{local_id}' not found.")

    # Auto clock-in the work clock (Layer 1) first.
    clocked_in = clock_in_work(ctx)

    state = ctx.global_store.load()

    # Auto-stop any previously running focus session.
    stopped_previous: str | None = None
    already_focused = False
    prev = state.active_session
    if prev:
        prev_repo = prev.get("repo")
        prev_id = prev.get("task_id")
        prev_path = prev.get("json_path")
        if prev_id and prev_id == local_id and prev_repo == repo:
            # Same task already running; nothing to stop or re-open. Starting
            # the same task again is a no-op on the worklogs so we do not append
            # a second open session (which would double-count elapsed time and
            # leave a dangling open worklog after stop).
            already_focused = has_open_session(task.get("worklogs", []))
        elif prev_id:
            _close_focus(ctx, prev_repo, prev_id, prev_path)
            stopped_previous = prev_id
            # The auto-stop above may have mutated the same store on disk (when
            # the previous session lived in this store). Re-read so the append
            # below starts from the just-persisted worklog list, not a stale
            # pre-close snapshot.
            store.load()
            task = store.get_task(local_id)
            if task is None:
                raise ValueError(f"Task '{local_id}' not found.")

    # Open the new focus session, unless the target task is already the active
    # focus with an open worklog (short-circuit the append). Enforce the
    # single-open-session invariant: close any lingering open worklog(s) on
    # the target first so a task can never carry more than the one worklog we
    # are about to open (which would leave the TUI's green focus arrow stuck
    # on after a single stop). The loop also self-heals a task that somehow
    # already carries multiple open worklogs from pre-existing on-disk
    # corruption - closing one per iteration until none remain.
    if not already_focused:
        worklogs = task.get("worklogs", [])
        while has_open_session(worklogs):
            worklogs = close_session(worklogs)
        task["worklogs"] = start_session(worklogs)
        store.update_task(local_id, {"worklogs": task["worklogs"]})
        store.save()

    state = ctx.global_store.load()
    state.active_session = {
        "repo": repo,
        "task_id": local_id,
        "json_path": str(store.path),
    }
    ctx.global_store.save(state)
    return clocked_in, stopped_previous


@click.command("start")
@click.argument("task_id", required=False, shell_complete=complete_open_task_id)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
@click.pass_obj
def start(
    ctx: DotoContext,
    task_id: str | None,
    json_output: bool,
) -> None:
    """Clock in, or start a focus timer for a task.

    With no TASK_ID (or ``work``), clock in the global work clock. With a
    TASK_ID, auto clock-in the work clock if needed, then start a focus timer
    for that task. Starting a new focus timer auto-stops the previous one.
    """
    formatter = ctx.formatter
    if json_output:
        formatter.json_output = True

    # Clock-in only (Layer 1).
    if task_id is None or task_id.lower() == WORK_REPO:
        started = clock_in_work(ctx)
        if not json_output:
            if started:
                formatter.print_success("Clocked in. Work clock started.")
            else:
                formatter.print_warning("Work clock is already running.")
        else:
            formatter.print_json({"action": "clock-in", "started": started})
        return

    # Focus timer (Layer 2) for a specific task.
    resolved = resolve_task_ref(ctx, task_id)
    if resolved is None:
        if json_output:
            formatter.print_json({"action": "start", "not_found": task_id})
        else:
            formatter.print_error(f"Task '{task_id}' not found.")
        return
    local_id = resolved.task_id
    if resolved.store.get_task(local_id) is None:
        if json_output:
            formatter.print_json({"action": "start", "not_found": local_id})
        else:
            formatter.print_error(f"Task '{local_id}' not found.")
        return

    clocked_in, stopped_previous = start_focus(ctx, resolved)

    if json_output:
        formatter.print_json(
            {
                "action": "start",
                "task_id": local_id,
                "work_clocked_in": clocked_in,
                "stopped_previous": stopped_previous,
            }
        )
        return

    if clocked_in:
        formatter.print_success("Clocked in. Work clock started.")
    if stopped_previous:
        formatter.print_warning(f"Stopped focus timer for {stopped_previous}.")
    formatter.print_success(f"Started focus timer for {local_id}.")


def _close_focus(
    ctx: DotoContext,
    repo: str | None,
    task_id: str,
    json_path: str | None,
) -> None:
    """Close the open focus worklog for a task in its own store.

    Args:
        ctx: The CLI context.
        repo: The repository name of the session (unused for local scope but
            kept for symmetry with the stored session shape).
        task_id: The local task identifier.
        json_path: Absolute path to the task's store, if recorded.
    """
    store = resolve_session_store(ctx.store, json_path)
    # Reload from disk before the read-modify-write. ``resolve_session_store``
    # may return the long-lived ``ctx.store`` instance (when the session lives
    # in the current repo), whose in-memory cache can be stale relative to
    # writes made through a different store instance for the same path. Without
    # this reload the close would overwrite disk with the stale snapshot,
    # silently dropping worklogs the other instance persisted.
    store.load()
    task = store.get_task(task_id)
    if task is None:
        return
    task["worklogs"] = close_session(task.get("worklogs", []))
    store.update_task(task_id, {"worklogs": task["worklogs"]})
    store.save()
