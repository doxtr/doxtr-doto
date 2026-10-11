"""Textual 3-pane terminal UI for doto.

The TUI is an *optional* feature backed by the ``textual`` package (install
via the ``tui`` extra: ``pip install 'doxtr-doto[tui]'``). ``textual`` is
imported lazily so the core CLI keeps working when it is not installed.

Public entry points:

* :data:`TEXTUAL_AVAILABLE` - whether ``textual`` can be imported.
* :func:`run_tui` - launch the app for a :class:`DotoContext`.

Rendering is deliberately modular: widget classes live in
:mod:`doxtr_doto.cli.tui.widgets`, the color mapping in
:mod:`doxtr_doto.cli.tui.theme`, and all mutations route through
:mod:`doxtr_doto.cli.tui.actions` which reuses the CLI verb functions so the
TUI never duplicates business logic.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from doxtr_doto.cli.main import DotoContext

#: Title shown in the terminal tab / window while the TUI is running.
#: Change this single constant to re-label the terminal tab (by default the
#: tab shows the process name, e.g. ``python3``).
TERMINAL_TITLE = "[DoTO]"


def _textual_available() -> bool:
    """Return whether the ``textual`` package can be imported.

    Returns:
        True if ``textual`` is importable, False otherwise.
    """
    try:
        import textual  # noqa: F401
    except ImportError:
        return False
    return True


#: Whether the optional ``textual`` dependency is installed.
TEXTUAL_AVAILABLE = _textual_available()


def _ensure_utf8_io() -> None:
    """Force stdin/stdout/stderr to UTF-8 so the TUI renders non-ASCII glyphs.

    The TUI draws German umlauts (ä ö ü Ä Ö Ü ß), box-drawing characters
    (card frames) and status glyphs (▶ ✔ ⏱). On a non-UTF-8 locale (e.g.
    ``LANG=C`` / a latin-1 console) those bytes garble or raise encoding
    errors. Textual itself expects a UTF-8 terminal, so this reconfigures the
    three standard streams to UTF-8 up front, removing the dependency on the
    user's ``LANG`` / ``PYTHONIOENCODING``.

    ``TextIOWrapper.reconfigure`` exists on CPython 3.7+, but a stream may be
    replaced by something without it (e.g. pytest's capture buffers, a plain
    ``io.StringIO``, or a redirected pipe wrapper), so each call is guarded by
    ``hasattr`` and wrapped in ``try``/``except`` and never raises - a stream
    that cannot be reconfigured is simply left as-is.
    """
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except (ValueError, OSError, AttributeError):
            # Stream is detached / already in use / not reconfigurable; leave
            # it untouched rather than crashing the TUI launch.
            continue


def run_tui(ctx: DotoContext) -> None:
    """Launch the Textual TUI for the given context.

    Forces the standard streams to UTF-8 (:func:`_ensure_utf8_io`) before
    launching so German umlauts, box-drawing card frames and status glyphs
    render correctly even on a non-UTF-8 locale, then builds and runs the app.

    Args:
        ctx: The CLI context (store, config, global state).

    Raises:
        RuntimeError: If ``textual`` is not installed.
    """
    if not TEXTUAL_AVAILABLE:
        raise RuntimeError(
            "The 'textual' package is required for the TUI. "
            "Install it with: pip install 'doxtr-doto[tui]'"
        )
    from doxtr_doto.cli.tui.app import DotoApp

    _ensure_utf8_io()
    app = DotoApp(ctx)
    app.run()
