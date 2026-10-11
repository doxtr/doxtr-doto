"""doto clock-out command - stop both the focus timer and work clock.

This is an alias of ``stop work``: it closes the active focus session (if
any) and stops the global work clock.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

from doxtr_doto.cli.commands.stop import stop_focus, stop_work_clock

if TYPE_CHECKING:
    from doxtr_doto.cli.main import DotoContext


@click.command("clock-out")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
@click.pass_obj
def clock_out(
    ctx: DotoContext,
    json_output: bool,
) -> None:
    """Clock out: stop the focus timer and the global work clock.

    Equivalent to ``doto stop work``.
    """
    formatter = ctx.formatter
    if json_output:
        formatter.json_output = True

    stopped_focus = stop_focus(ctx)
    clocked_out = stop_work_clock(ctx)

    if json_output:
        formatter.print_json(
            {
                "action": "clock-out",
                "stopped_focus": stopped_focus,
                "clocked_out": clocked_out,
            }
        )
        return

    if stopped_focus:
        formatter.print_success(f"Stopped focus timer for {stopped_focus}.")

    if clocked_out:
        formatter.print_success("Clocked out. Work clock stopped.")
    else:
        formatter.print_warning("Work clock was not running.")
