"""doto status command - show the active focus session and work clock.

Displays the currently active focus task (namespaced ``repo#id`` when it
belongs to a different repo), its live elapsed time, and today's work-clock
duration.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import click

from doxtr_doto.cli.session import (
    derive_repo_name,
    live_focus_elapsed,
    render_status,
    resolve_session_store,
    session_display_id,
    work_elapsed_today,
)
from doxtr_doto.time_tracking import has_open_session

if TYPE_CHECKING:
    from doxtr_doto.cli.main import DotoContext


@click.command("status")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
@click.pass_obj
def status(
    ctx: DotoContext,
    json_output: bool,
) -> None:
    """Show the active focus session and today's work clock."""
    formatter = ctx.formatter
    if json_output:
        formatter.json_output = True

    now = datetime.now().astimezone()
    state = ctx.global_store.load()
    repo = derive_repo_name(ctx.config)

    focus_display = session_display_id(state.active_session, repo)
    focus_title = focus_status = focus_priority = None
    focus_elapsed = 0

    if state.active_session and state.active_session.get("task_id"):
        task_id = state.active_session["task_id"]
        store = resolve_session_store(ctx.store, state.active_session.get("json_path"))
        task = store.get_task(task_id)
        if task is not None:
            focus_title = task.get("title", "")
            focus_status = task.get("status", "")
            focus_priority = task.get("priority", "")
            focus_elapsed = live_focus_elapsed(task.get("worklogs", []), now=now)
        else:
            # Session points at a missing task; treat as no focus.
            focus_display = None

    work_running = has_open_session(state.work_clock.worklogs)
    work_today = work_elapsed_today(state.work_clock.worklogs, now)

    if json_output:
        formatter.print_json(
            {
                "focus": {
                    "id": focus_display,
                    "title": focus_title,
                    "status": focus_status,
                    "priority": focus_priority,
                    "elapsed_seconds": focus_elapsed,
                }
                if focus_display
                else None,
                "work_clock": {
                    "running": work_running,
                    "today_seconds": work_today,
                },
            }
        )
        return

    render_status(
        formatter,
        focus_display_id=focus_display,
        focus_title=focus_title,
        focus_status=focus_status,
        focus_priority=focus_priority,
        focus_elapsed=focus_elapsed,
        work_running=work_running,
        work_today_elapsed=work_today,
    )
