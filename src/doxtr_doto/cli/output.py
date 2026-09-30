"""Output formatting with rich."""

from __future__ import annotations

import json
import sys
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich import box

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

if TYPE_CHECKING:
    from doxtr_doto.cli.config import DotoConfig


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
        today = date.today()
        for task in tasks:
            row = []
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
                        due_date = (
                            datetime.fromisoformat(value).date()
                            if isinstance(value, str)
                            else value
                        )
                        style = "red bold" if due_date < today else ""
                        display = str(value)
                        if due_date < today:
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
        overdue = sum(
            1
            for t in tasks
            if t.get("due")
            and datetime.fromisoformat(t["due"]).date() < today
            and t.get("status") != "done"
        )
        blocked = sum(1 for t in tasks if t.get("status") == "blocked")
        summary_parts = [f"{len(tasks)} task{'s' if len(tasks) != 1 else ''}"]
        if overdue:
            summary_parts.append(f"{overdue} overdue")
        if blocked:
            summary_parts.append(f"{blocked} blocked")
        self.print(f"\n{' ('.join(summary_parts)}{')'if len(summary_parts) > 1 else ''}")

    def _format_task_table_plain(
        self, tasks: list[dict[str, Any]], columns: list[str]
    ) -> None:
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
            # Build content
            lines = []
            if task.get("assignee"):
                lines.append(f"[bold]Assignee:[/bold] {task['assignee']}")
            priority_style = PRIORITY_COLORS.get(priority, "")
            if priority_style:
                lines.append(f"[bold]Priority:[/bold] [{priority_style}]{priority}[/{priority_style}]")
            else:
                lines.append(f"[bold]Priority:[/bold] {priority}")
            status_style = STATUS_COLORS.get(status, "")
            if status_style:
                lines.append(f"[bold]Status:[/bold] [{status_style}]{status}[/{status_style}]")
            else:
                lines.append(f"[bold]Status:[/bold] {status}")
            if task.get("due"):
                due_style = ""
                if task.get("status") != "done":
                    due_date = datetime.fromisoformat(task["due"]).date()
                    if due_date < date.today():
                        due_style = "red bold"
                if due_style:
                    lines.append(f"[bold]Due:[/bold] [{due_style}]{task['due']}[/{due_style}]")
                else:
                    lines.append(f"[bold]Due:[/bold] {task['due']}")
            if task.get("tags"):
                lines.append(f"[bold]Tags:[/bold] {', '.join(task['tags'])}")
            if task.get("depends_on"):
                lines.append(f"[bold]Depends on:[/bold] {', '.join(task['depends_on'])}")
            if task.get("_series_info"):
                series_info = task["_series_info"]
                lines.append(f"[bold]Series:[/bold] {series_info['series_id']} ({series_info['pattern']}, until {series_info['until']})")
            if task.get("created"):
                lines.append(f"[bold]Created:[/bold] {task['created']}")
            if task.get("updated"):
                lines.append(f"[bold]Updated:[/bold] {task['updated']}")
            if task.get("body"):
                lines.append("")
                lines.append(task["body"])

            panel = Panel(
                "\n".join(lines),
                title=f"[bold]{task_id}[/bold] - {title}",
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
                print(f"Series: {series_info['series_id']} ({series_info['pattern']}, until {series_info['until']})")
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
                self.console.print(
                    f"  RST file value:    [cyan]{rst}[/]  ({rst_file}:{rst_line})"
                )
                self.console.print(f"  JSON file value:   [yellow]{json_val}[/]")
            else:
                print(f"\nConflict in {task_id}: {field}")
                print(f"  Base (last sync):  {base}")
                print(f"  RST file value:    {rst}  ({rst_file}:{rst_line})")
                print(f"  JSON file value:   {json_val}")


def get_formatter(config: DotoConfig, json_output: bool = False, quiet: bool = False) -> OutputFormatter:
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
