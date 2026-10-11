"""doto export command - Export tasks to various formats."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

from doxtr_doto.cli.completion import complete_assignee, complete_status

if TYPE_CHECKING:
    from doxtr_doto.cli.main import DotoContext


def _format_json(tasks: list[dict[str, Any]]) -> str:
    """Format tasks as JSON.

    Args:
        tasks: List of task dictionaries.

    Returns:
        JSON string.
    """
    # Remove internal _sync field from export
    clean_tasks = []
    for task in tasks:
        clean = {k: v for k, v in task.items() if not k.startswith("_")}
        clean_tasks.append(clean)
    return json.dumps(clean_tasks, indent=2, default=str)


def _format_csv(tasks: list[dict[str, Any]]) -> str:
    """Format tasks as CSV.

    Args:
        tasks: List of task dictionaries.

    Returns:
        CSV string.
    """
    if not tasks:
        return ""

    columns = [
        "id",
        "title",
        "priority",
        "status",
        "assignee",
        "due",
        "tags",
        "depends_on",
        "created",
        "updated",
    ]

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()

    for task in tasks:
        row = {}
        for col in columns:
            value = task.get(col, "")
            if col == "tags" and isinstance(value, list):
                value = ",".join(value)
            elif col == "depends_on" and isinstance(value, list):
                value = ",".join(value)
            row[col] = value if value is not None else ""
        writer.writerow(row)

    return output.getvalue()


def _format_markdown(tasks: list[dict[str, Any]]) -> str:
    """Format tasks as Markdown.

    Args:
        tasks: List of task dictionaries.

    Returns:
        Markdown string.
    """
    lines = ["# Tasks\n"]

    # Group by status
    status_groups: dict[str, list[dict[str, Any]]] = {}
    for task in tasks:
        status = task.get("status", "open")
        if status not in status_groups:
            status_groups[status] = []
        status_groups[status].append(task)

    # Order: open, in-progress, blocked, done
    status_order = ["open", "in-progress", "blocked", "done"]

    for status in status_order:
        if status not in status_groups:
            continue

        lines.append(f"\n## {status.replace('-', ' ').title()}\n")

        for task in status_groups[status]:
            task_id = task.get("id", "?")
            title = task.get("title", "Untitled")
            priority = task.get("priority", "")
            assignee = task.get("assignee", "")
            due = task.get("due", "")

            # Checkbox style
            checkbox = "[x]" if status == "done" else "[ ]"
            lines.append(f"- {checkbox} **{task_id}**: {title}")

            # Task details as sub-items
            details = []
            if priority:
                details.append(f"Priority: {priority}")
            if assignee:
                details.append(f"Assignee: {assignee}")
            if due:
                details.append(f"Due: {due}")

            tags = task.get("tags", [])
            if tags:
                details.append(f"Tags: {', '.join(tags)}")

            depends_on = task.get("depends_on", [])
            if depends_on:
                details.append(f"Depends on: {', '.join(depends_on)}")

            if details:
                lines.append(f"  - {' | '.join(details)}")

            body = task.get("body", "")
            if body:
                # Indent body content
                body_lines = body.strip().split("\n")
                if len(body_lines) == 1:
                    lines.append(f"  - {body_lines[0]}")
                else:
                    lines.append("  - Description:")
                    for body_line in body_lines:
                        lines.append(f"    {body_line}")

    # Summary
    lines.append(f"\n---\n*Exported {len(tasks)} task(s)*\n")

    return "\n".join(lines)


@click.command("export")
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["json", "csv", "markdown"]),
    default="json",
    help="Export format.",
)
@click.option(
    "--output",
    "-o",
    "output_path",
    type=click.Path(),
    help="Output file path. Prints to stdout if omitted.",
)
@click.option("--archived", is_flag=True, help="Include archived tasks.")
@click.option(
    "--status",
    "-s",
    shell_complete=complete_status,
    help="Filter by status (comma-separated for multiple).",
)
@click.option(
    "--assignee",
    "-a",
    shell_complete=complete_assignee,
    help="Filter by assignee (comma-separated for multiple).",
)
@click.pass_obj
def export(
    ctx: DotoContext,
    output_format: str,
    output_path: str | None,
    archived: bool,
    status: str | None,
    assignee: str | None,
) -> None:
    """Export tasks to file or stdout.

    Supports JSON, CSV, and Markdown formats.

    Examples:

        doto export

        doto export --format csv --output tasks.csv

        doto export --format markdown -o report.md

        doto export --status done --format json

        doto export --archived --format csv
    """
    formatter = ctx.formatter
    store = ctx.store

    # Parse filters
    status_list = [s.strip() for s in status.split(",")] if status else None
    assignee_list = [a.strip() for a in assignee.split(",")] if assignee else None

    # Filter tasks
    tasks = store.filter_tasks(
        assignee=assignee_list,
        status=status_list,
        include_archived=archived,
    )

    # Format output
    if output_format == "json":
        content = _format_json(tasks)
    elif output_format == "csv":
        content = _format_csv(tasks)
    elif output_format == "markdown":
        content = _format_markdown(tasks)
    else:
        raise click.ClickException(f"Unknown format: {output_format}")

    # Output
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        formatter.print_success(f"Exported {len(tasks)} task(s) to {path}")
    else:
        click.echo(content, nl=False)
        # Add newline for non-JSON formats that don't end with one
        if not content.endswith("\n"):
            click.echo()
