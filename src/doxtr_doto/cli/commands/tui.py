"""doto tui command - launch the optional Textual 3-pane terminal UI.

``textual`` is an *optional* dependency (install via the ``tui`` extra:
``pip install 'doxtr-doto[tui]'``). It is imported lazily so the core CLI
keeps working when it is absent; running ``doto tui`` without it prints a
helpful install hint instead of raising an import error.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from doxtr_doto.cli.main import DotoContext


@click.command("tui")
@click.pass_obj
def tui(ctx: DotoContext) -> None:
    """Launch the interactive 3-pane terminal UI.

    Opens a Textual-based terminal UI with a repo tree, task list, and task
    details pane plus live work/focus counters. Requires the optional
    ``textual`` dependency; install it with ``pip install 'doxtr-doto[tui]'``.
    """
    from doxtr_doto.cli.tui import TEXTUAL_AVAILABLE, run_tui

    if not TEXTUAL_AVAILABLE:
        ctx.formatter.print_error(
            "The TUI requires the optional 'textual' package. "
            "Install it with: pip install 'doxtr-doto\\[tui]'"
        )
        return

    run_tui(ctx)
