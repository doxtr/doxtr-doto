"""doto search command - Search tasks by query."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import click

if TYPE_CHECKING:
    from doxtr_doto.cli.main import DotoContext


def _match_query(
    value: str,
    query: str,
    regex: bool = False,
    case_sensitive: bool = False,
) -> bool:
    """Check if a value matches the query.

    Args:
        value: Value to search in.
        query: Query string or regex pattern.
        regex: Treat query as regex.
        case_sensitive: Case-sensitive matching.

    Returns:
        True if value matches query.
    """
    if not value:
        return False

    if regex:
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            return bool(re.search(query, value, flags))
        except re.error:
            return False
    else:
        if case_sensitive:
            return query in value
        return query.lower() in value.lower()


def _search_task(
    task: dict[str, Any],
    query: str,
    regex: bool = False,
    search_body: bool = False,
    fields: list[str] | None = None,
) -> bool:
    """Check if a task matches the search query.

    Args:
        task: Task dictionary.
        query: Query string or regex.
        regex: Treat query as regex.
        search_body: Include body content in search.
        fields: Specific fields to search (default: title, id).

    Returns:
        True if task matches.
    """
    # Default fields to search
    if fields:
        search_fields = fields
    else:
        search_fields = ["title", "id"]
        if search_body:
            search_fields.append("body")

    for field in search_fields:
        value = task.get(field)
        if value is None:
            continue

        # Handle list fields (e.g., tags)
        if isinstance(value, list):
            for item in value:
                if _match_query(str(item), query, regex):
                    return True
        else:
            if _match_query(str(value), query, regex):
                return True

    return False


@click.command("search")
@click.argument("query")
@click.option("--regex", "-r", is_flag=True, help="Treat query as regex pattern.")
@click.option("--body", "-b", is_flag=True, help="Search in body content.")
@click.option("--archived", is_flag=True, help="Include archived tasks.")
@click.option(
    "--field",
    "-f",
    "fields",
    multiple=True,
    help="Fields to search (can be repeated). Default: title, id.",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
@click.pass_obj
def search(
    ctx: DotoContext,
    query: str,
    regex: bool,
    body: bool,
    archived: bool,
    fields: tuple[str, ...],
    json_output: bool,
) -> None:
    """Search tasks by query.

    QUERY is the search string or regex pattern.

    By default, searches in task title and ID. Use --body to include
    body content, or --field to specify exact fields.

    Examples:

        doto search "login bug"

        doto search --regex "fix|bug"

        doto search --body "authentication"

        doto search --field title --field tags "api"

        doto search --archived "old feature"
    """
    formatter = ctx.formatter
    if json_output:
        formatter.json_output = True

    store = ctx.store

    # Convert fields tuple to list
    field_list = list(fields) if fields else None

    # If --body is specified and no fields, add body to default search
    search_body = body

    # Validate regex if specified
    if regex:
        try:
            re.compile(query)
        except re.error as e:
            raise click.ClickException(f"Invalid regex pattern: {e}")

    # Search tasks
    matching_tasks = []
    for task_id, task_data in store.iter_tasks(include_archived=archived):
        task = {"id": task_id, **task_data}
        if _search_task(task, query, regex=regex, search_body=search_body, fields=field_list):
            matching_tasks.append(task)

    # Display results
    if not matching_tasks:
        if json_output:
            formatter.print_json([])
        else:
            formatter.print(f"No tasks found matching '{query}'.")
        return

    if json_output:
        formatter.print_json(matching_tasks)
    else:
        formatter.print(f"Found {len(matching_tasks)} task(s) matching '{query}':\n")
        formatter.format_task_table(matching_tasks)
