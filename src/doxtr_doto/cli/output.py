"""Output formatting with rich."""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, Any

from doxtr_doto.date_utils import format_date_display, task_is_overdue

try:
    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


def _rich_escape(markup: str) -> str:
    """Return ``markup`` with every ``[`` backslash-escaped.

    Both rich and Textual consume a leading backslash and render ``\\[`` as a
    literal ``[``, so this one escape makes free text render literally in both.
    It is deliberately stricter than :func:`rich.markup.escape`, which only
    escapes brackets it recognises as a tag and so leaves a bare ``"[WIP]"``
    untouched - fine for rich, but Textual's parser *does* treat ``"[WIP]"`` as
    a style tag and would drop it. Escaping every ``[`` is correct for both
    renderers and keeps the detail lines (shared by the CLI card and the TUI
    card viewer) consistent.

    Args:
        markup: The text to escape.

    Returns:
        The text with each ``[`` replaced by ``\\[``.
    """
    return markup.replace("[", r"\[")


def escape_markup(value: object) -> str:
    """Return ``value`` as a markup-safe string for rich/Textual rendering.

    Free-text task fields (title, tags, ids, ...) may contain ``[`` / ``]``
    characters - e.g. a title like ``"[WIP] fix"`` or ``"[] cleanup"``. When
    such a value is interpolated into a rich/Textual markup string it is
    otherwise parsed as a *style tag*, which silently drops the bracketed text
    (``"[red] oops"`` renders as ``" oops"``), throws off visible-width
    measurement so framed cards misalign, or - for a bare ``"[/]"`` - raises a
    ``MarkupError``. Escaping backslash-escapes each ``[`` so the brackets
    render literally and occupy their true width in both renderers (see
    :func:`_rich_escape` for why a plain ``rich.markup.escape`` is not enough
    for Textual).

    This is the single escaper shared by the CLI card builder and the TUI
    widgets (re-exported via :mod:`doxtr_doto.cli.tui.theme`) so both surfaces
    treat free text identically.

    Args:
        value: The value to escape; coerced to ``str`` first.

    Returns:
        The stringified, markup-escaped value.
    """
    return _rich_escape(str(value))


if TYPE_CHECKING:
    from doxtr_doto.cli.config import DotoConfig


def _wrap_style(text: str, style: str) -> str:
    """Wrap ``text`` in rich/Textual markup for ``style`` (empty = unchanged).

    The ``[style]text[/style]`` form is understood by both rich (CLI card
    panels) and Textual (TUI card viewer), so this single helper feeds both
    renderers.

    Args:
        text: The (already markup-escaped) text to style.
        style: A style string such as ``"red bold"``; empty means no styling.

    Returns:
        The styled markup, or ``text`` unchanged when ``style`` is empty.
    """
    if not style:
        return text
    return f"[{style}]{text}[/{style}]"


def build_task_detail_lines(task: dict[str, Any]) -> list[str]:
    """Return the full-detail markup lines for a task (pure, single source).

    This is the one place the task "detail card" field set, order, labels and
    conditional-emit / styling rules live. Both the CLI reference card
    (:meth:`OutputFormatter.format_task_detail`, i.e. ``doto list -f cards``)
    and the TUI card viewer
    (:meth:`doxtr_doto.cli.tui.app.CardViewerScreen.build_detail_lines`)
    consume these lines, so a change to the detail layout happens in exactly
    one place and the two surfaces cannot drift.

    The lines use ``[style]...[/style]`` markup understood by both rich and
    Textual. Free-text values (title, assignee, tags, body, series) are
    markup-escaped so a value such as ``"[WIP] fix"`` is not misparsed as a
    style tag. Only fields the task actually has are emitted; the body is
    always last, separated by a blank line. Priority and status are always
    shown (with a ``-`` placeholder when empty); an overdue, non-done due date
    is styled ``red bold`` to match the CLI card.

    Args:
        task: The task dict to render (carrying its display ``id``).

    Returns:
        The detail lines (rich/Textual markup) including the ``id - title``
        header line and a trailing blank line before the body.
    """
    task_id = _rich_escape(str(task.get("id", "?")))
    title = _rich_escape(str(task.get("title", "Untitled")))
    lines: list[str] = [f"[bold]{task_id}[/bold] - {title}", ""]
    if task.get("assignee"):
        lines.append(f"[bold]Assignee:[/bold] {_rich_escape(str(task['assignee']))}")
    priority = task.get("priority") or ""
    lines.append(
        f"[bold]Priority:[/bold] "
        f"{_wrap_style(_rich_escape(priority) or '-', PRIORITY_COLORS.get(priority, ''))}"
    )
    status = task.get("status") or ""
    lines.append(
        f"[bold]Status:[/bold] "
        f"{_wrap_style(_rich_escape(status) or '-', STATUS_COLORS.get(status, ''))}"
    )
    if task.get("due"):
        due_style = ""
        if task_is_overdue(task):
            due_style = "red bold"
        due_display = format_date_display(task["due"])
        lines.append(f"[bold]Due:[/bold] {_wrap_style(_rich_escape(due_display), due_style)}")
    if task.get("tags"):
        tags = ", ".join(_rich_escape(str(t)) for t in task["tags"])
        lines.append(f"[bold]Tags:[/bold] {tags}")
    if task.get("depends_on"):
        deps = ", ".join(_rich_escape(str(d)) for d in task["depends_on"])
        lines.append(f"[bold]Depends on:[/bold] {deps}")
    series_info = task.get("_series_info")
    if series_info:
        lines.append(
            f"[bold]Series:[/bold] {_rich_escape(str(series_info['series_id']))} "
            f"({_rich_escape(str(series_info['pattern']))}, "
            f"until {_rich_escape(str(series_info['until']))})"
        )
    if task.get("created"):
        lines.append(f"[bold]Created:[/bold] {_rich_escape(str(task['created']))}")
    if task.get("updated"):
        lines.append(f"[bold]Updated:[/bold] {_rich_escape(str(task['updated']))}")
    if task.get("body"):
        lines.append("")
        lines.append(_rich_escape(str(task["body"])))
    return lines


# Priority colors
PRIORITY_COLORS = {
    "low": "dim",
    "medium": "blue",
    "high": "yellow",
    "critical": "red bold",
}

# Status colors
STATUS_COLORS = {
    "open": "green",
    "in-progress": "cyan",
    "blocked": "red",
    "done": "dim",
}


class OutputFormatter:
    """Handles CLI output formatting."""

    def __init__(
        self,
        color: str = "auto",
        quiet: bool = False,
        json_output: bool = False,
    ) -> None:
        """Initialize formatter.

        Args:
            color: Color mode (auto, always, never).
            quiet: Suppress non-essential output.
            json_output: Output in JSON format.
        """
        self.quiet = quiet
        self.json_output = json_output

        # Determine if we should use colors
        if color == "never":
            force_terminal = False
            no_color = True
        elif color == "always":
            force_terminal = True
            no_color = False
        else:  # auto
            force_terminal = None
            no_color = False

        if RICH_AVAILABLE:
            self.console = Console(
                force_terminal=force_terminal,
                no_color=no_color,
                stderr=False,
            )
            self.error_console = Console(
                force_terminal=force_terminal,
                no_color=no_color,
                stderr=True,
            )
        else:
            self.console = None  # type: ignore[assignment]
            self.error_console = None  # type: ignore[assignment]

    def print(self, message: str, style: str | None = None) -> None:
        """Print a message.

        Args:
            message: Message to print.
            style: Optional rich style.
        """
        if self.quiet:
            return
        if self.console:
            self.console.print(message, style=style)
        else:
            print(message)

    def print_success(self, message: str) -> None:
        """Print a success message."""
        if self.quiet:
            return
        if self.console:
            self.console.print(f"✓ {message}", style="green")
        else:
            print(f"✓ {message}")

    def print_error(self, message: str) -> None:
        """Print an error message."""
        if self.error_console:
            self.error_console.print(f"✗ {message}", style="red bold")
        else:
            print(f"✗ {message}", file=sys.stderr)

    def print_warning(self, message: str) -> None:
        """Print a warning message."""
        if self.quiet:
            return
        if self.console:
            self.console.print(f"⚠ {message}", style="yellow")
        else:
            print(f"⚠ {message}")

    def print_json(self, data: Any) -> None:
        """Print data as JSON."""
        print(json.dumps(data, indent=2, default=str))

    def format_task_table(
        self,
        tasks: list[dict[str, Any]],
        columns: list[str] | None = None,
    ) -> None:
        """Format tasks as a table.

        Args:
            tasks: List of task dictionaries.
            columns: Columns to display (default: id, priority, status, assignee, due, title).
        """
        if self.json_output:
            self.print_json(tasks)
            return

        if not tasks:
            self.print("No tasks found.")
            return

        if columns is None:
            columns = ["id", "priority", "status", "assignee", "due", "title"]

        if not RICH_AVAILABLE:
            self._format_task_table_plain(tasks, columns)
            return

        table = Table(box=box.SIMPLE)

        # Add columns
        column_headers = {
            "id": "ID",
            "title": "Title",
            "priority": "Priority",
            "status": "Status",
            "assignee": "Assignee",
            "due": "Due",
            "tags": "Tags",
            "created": "Created",
            "updated": "Updated",
            "deps": "Dependencies",
            "depends_on": "Depends On",
        }
        for col in columns:
            table.add_column(column_headers.get(col, col.title()))

        # Add rows
        for task in tasks:
            row: list[str | Text] = []
            for col in columns:
                value = task.get(col, "")
                if col == "priority":
                    style = PRIORITY_COLORS.get(value, "")
                    row.append(Text(str(value or "-"), style=style))
                elif col == "status":
                    style = STATUS_COLORS.get(value, "")
                    row.append(Text(str(value or "-"), style=style))
                elif col == "due":
                    if value:
                        overdue = task_is_overdue(task)
                        style = "red bold" if overdue else ""
                        display = format_date_display(value)
                        if overdue:
                            display += " [OVERDUE]"
                        row.append(Text(display, style=style))
                    else:
                        row.append("-")
                elif col == "tags":
                    row.append(", ".join(value) if value else "-")
                elif col == "deps":
                    # Use pre-formatted deps_display if available
                    deps_display = task.get("deps_display", "")
                    if deps_display:
                        row.append(deps_display)
                    elif value and isinstance(value, list):
                        row.append(", ".join(value))
                    else:
                        row.append("-")
                elif col == "depends_on":
                    if value and isinstance(value, list):
                        row.append(", ".join(value))
                    else:
                        row.append("-")
                elif col == "title":
                    # Truncate long titles
                    title = str(value or "")
                    if len(title) > 50:
                        title = title[:47] + "..."
                    row.append(title)
                else:
                    row.append(str(value) if value else "-")
            table.add_row(*row)

        self.console.print(table)

        # Summary
        overdue_count = sum(1 for t in tasks if task_is_overdue(t))
        blocked = sum(1 for t in tasks if t.get("status") == "blocked")
        summary_parts = [f"{len(tasks)} task{'s' if len(tasks) != 1 else ''}"]
        if overdue_count:
            summary_parts.append(f"{overdue_count} overdue")
        if blocked:
            summary_parts.append(f"{blocked} blocked")
        self.print(f"\n{' ('.join(summary_parts)}{')' if len(summary_parts) > 1 else ''}")

    def _format_task_table_plain(self, tasks: list[dict[str, Any]], columns: list[str]) -> None:
        """Format tasks as plain text table."""
        # Calculate column widths
        widths = {col: len(col) for col in columns}
        for task in tasks:
            for col in columns:
                value = task.get(col, "")
                if col == "tags":
                    value = ", ".join(value) if value else ""
                widths[col] = max(widths[col], len(str(value or "-")))

        # Print header
        header = "  ".join(col.upper().ljust(widths[col]) for col in columns)
        print(header)
        print("-" * len(header))

        # Print rows
        for task in tasks:
            row_parts = []
            for col in columns:
                value = task.get(col, "")
                if col == "tags":
                    value = ", ".join(value) if value else ""
                row_parts.append(str(value or "-").ljust(widths[col]))
            print("  ".join(row_parts))

    def format_task_list(self, tasks: list[dict[str, Any]]) -> None:
        """Format tasks as a simple list.

        Args:
            tasks: List of task dictionaries.
        """
        if self.json_output:
            self.print_json(tasks)
            return

        if not tasks:
            self.print("No tasks found.")
            return

        for task in tasks:
            task_id = task.get("id", "?")
            title = task.get("title", "Untitled")
            status = task.get("status", "")
            priority = task.get("priority", "")

            if RICH_AVAILABLE:
                status_style = STATUS_COLORS.get(status, "")
                priority_style = PRIORITY_COLORS.get(priority, "")
                self.console.print(
                    f"[bold]{task_id}[/bold] - {title} "
                    f"[{priority_style}]({priority})[/{priority_style}] "
                    f"[{status_style}][{status}][/{status_style}]"
                )
            else:
                print(f"{task_id} - {title} ({priority}) [{status}]")

    def format_task_cards(self, tasks: list[dict[str, Any]]) -> None:
        """Format tasks as cards.

        Args:
            tasks: List of task dictionaries.
        """
        if self.json_output:
            self.print_json(tasks)
            return

        if not tasks:
            self.print("No tasks found.")
            return

        for task in tasks:
            self.format_task_detail(task)
            if RICH_AVAILABLE:
                self.console.print()
            else:
                print()

    def format_task_detail(self, task: dict[str, Any]) -> None:
        """Format a single task with full details.

        Args:
            task: Task dictionary.
        """
        if self.json_output:
            self.print_json(task)
            return

        task_id = task.get("id", "?")
        title = task.get("title", "Untitled")
        status = task.get("status", "")
        priority = task.get("priority", "")

        if RICH_AVAILABLE:
            # Body = the shared detail lines minus the id/title header line
            # (and its trailing blank), since the Panel renders the title
            # itself. build_task_detail_lines is the single source of truth
            # for the field set/order/styling shared with the TUI card viewer.
            lines = build_task_detail_lines(task)[2:]

            panel = Panel(
                "\n".join(lines),
                title=f"[bold]{_rich_escape(str(task_id))}[/bold] - {_rich_escape(str(title))}",
                title_align="left",
                border_style=PRIORITY_COLORS.get(priority, ""),
            )
            self.console.print(panel)
        else:
            print(f"{'=' * 60}")
            print(f"{task_id} - {title}")
            print(f"{'=' * 60}")
            if task.get("assignee"):
                print(f"Assignee: {task['assignee']}")
            print(f"Priority: {priority}")
            print(f"Status: {status}")
            if task.get("due"):
                print(f"Due: {task['due']}")
            if task.get("tags"):
                print(f"Tags: {', '.join(task['tags'])}")
            if task.get("depends_on"):
                print(f"Depends on: {', '.join(task['depends_on'])}")
            if task.get("_series_info"):
                series_info = task["_series_info"]
                print(
                    f"Series: {series_info['series_id']} ({series_info['pattern']}, until {series_info['until']})"
                )
            if task.get("created"):
                print(f"Created: {task['created']}")
            if task.get("updated"):
                print(f"Updated: {task['updated']}")
            if task.get("body"):
                print()
                print(task["body"])

    def format_conflicts(self, conflicts: list[dict[str, Any]]) -> None:
        """Format merge conflicts for display.

        Args:
            conflicts: List of conflict dictionaries.
        """
        if self.json_output:
            self.print_json(conflicts)
            return

        if not conflicts:
            self.print("No conflicts found.")
            return

        for conflict in conflicts:
            task_id = conflict.get("task_id", "?")
            field = conflict.get("field", "?")
            base = conflict.get("base", "")
            rst = conflict.get("rst", "")
            json_val = conflict.get("json", "")
            rst_file = conflict.get("rst_file", "")
            rst_line = conflict.get("rst_line", "")

            if RICH_AVAILABLE:
                self.console.print(f"\n[bold red]Conflict in {task_id}: {field}[/]")
                self.console.print(f"  Base (last sync):  [dim]{base}[/]")
                self.console.print(f"  RST file value:    [cyan]{rst}[/]  ({rst_file}:{rst_line})")
                self.console.print(f"  JSON file value:   [yellow]{json_val}[/]")
            else:
                print(f"\nConflict in {task_id}: {field}")
                print(f"  Base (last sync):  {base}")
                print(f"  RST file value:    {rst}  ({rst_file}:{rst_line})")
                print(f"  JSON file value:   {json_val}")


def get_formatter(
    config: DotoConfig, json_output: bool = False, quiet: bool = False
) -> OutputFormatter:
    """Get an output formatter based on config.

    Args:
        config: CLI configuration.
        json_output: Force JSON output.
        quiet: Suppress non-essential output.

    Returns:
        Configured OutputFormatter.
    """
    return OutputFormatter(
        color=config.color,
        quiet=quiet,
        json_output=json_output,
    )
