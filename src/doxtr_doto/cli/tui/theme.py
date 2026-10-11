"""Color/style mapping for the doto TUI.

The CLI's rich styles (:data:`doxtr_doto.cli.output.PRIORITY_COLORS` and
:data:`doxtr_doto.cli.output.STATUS_COLORS`) are reused and translated into
Textual markup styles. Keeping this mapping behind small helpers lets a child
theme override colors without touching widget logic.

Free-text escaping is re-exported from :func:`doxtr_doto.cli.output.escape_markup`
(the single source of truth for both surfaces). It backslash-escapes *every*
``[`` because the TUI renders through *Textual* markup, whose parser is stricter
than rich's: Textual treats even a bare ``"[WIP]"`` as a style tag and drops
it, so a bracketed title must be escaped to render literally - and measure the
same width - in both the Textual render path and the rich-based width
measurement the kanban cards use. :func:`escape_title` additionally colours
each ``[...]`` run with the active theme accent.
"""

from __future__ import annotations

import re

from doxtr_doto.cli.output import PRIORITY_COLORS, STATUS_COLORS, escape_markup

#: Re-exported helpers so widgets import free-text handling from the theme
#: layer (a child theme can swap it) rather than reaching into
#: :mod:`doxtr_doto.cli.output` directly.
__all__ = [
    "DEFAULT_STYLE",
    "escape_markup",
    "escape_title",
    "priority_style",
    "status_style",
    "styled",
]

#: Fallback Textual style used when a value has no mapping.
DEFAULT_STYLE = ""

#: Matches one ``[...]`` bracket run (no nested bracket); used to colour
#: bracketed title segments in :func:`escape_title`.
_BRACKET_RUN = re.compile(r"\[[^\[\]]*\]")


def escape_title(value: object, style: str = "") -> str:
    """Escape ``value`` and accent-highlight its ``[...]`` runs for the TUI.

    The single helper every ``format_*`` surface uses for free-text titles: it
    markup-escapes the text (so brackets render literally and keep their true
    width - see :func:`escape_markup`) and colours each bracketed run with
    ``style``. ``style`` is passed in by the caller (the widgets forward their
    overridable :data:`~doxtr_doto.cli.tui.widgets.TitleHighlight.BRACKET_HIGHLIGHT_STYLE`
    class attribute) rather than read from module state, so the function stays
    pure and a child theme can vary the highlight per widget. With an empty
    ``style`` (the pure-logic / test default) it degrades to a plain
    :func:`escape_markup`, so width/plain-text behaviour is unchanged.

    ``style`` must be a markup value both rich and Textual understand (a
    concrete colour such as ``"#ffa62b"`` - *not* a ``$accent`` CSS token,
    which rich markup cannot resolve).

    Args:
        value: The free-text value (title) to escape and highlight.
        style: The markup style for bracket runs; empty disables the highlight.

    Returns:
        The escaped, accent-highlighted Textual markup string.
    """
    text = str(value)
    if not style:
        return escape_markup(text)
    parts: list[str] = []
    pos = 0
    for match in _BRACKET_RUN.finditer(text):
        parts.append(escape_markup(text[pos : match.start()]))
        parts.append(f"[{style}]{escape_markup(match.group(0))}[/{style}]")
        pos = match.end()
    parts.append(escape_markup(text[pos:]))
    return "".join(parts)


def priority_style(priority: str | None) -> str:
    """Return the Textual markup style for a task priority.

    Args:
        priority: The task priority value (may be None).

    Returns:
        A Textual style string (possibly empty).
    """
    if not priority:
        return DEFAULT_STYLE
    return PRIORITY_COLORS.get(priority, DEFAULT_STYLE)


def status_style(status: str | None) -> str:
    """Return the Textual markup style for a task status.

    Args:
        status: The task status value (may be None).

    Returns:
        A Textual style string (possibly empty).
    """
    if not status:
        return DEFAULT_STYLE
    return STATUS_COLORS.get(status, DEFAULT_STYLE)


def styled(text: str, style: str) -> str:
    """Wrap ``text`` in Textual markup for ``style``.

    Args:
        text: The text to style.
        style: A Textual style string; empty means no styling.

    Returns:
        The text wrapped in ``[style]...[/style]`` markup, or unchanged if
        ``style`` is empty.
    """
    if not style:
        return text
    return f"[{style}]{text}[/{style}]"
