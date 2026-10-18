"""doto add command - Add a new task."""

from __future__ import annotations

import os
import subprocess
import tempfile
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

import click

from doxtr_doto.cli.completion import (
    complete_assignee,
    complete_date,
    complete_priority,
    complete_recurrence,
    complete_status,
    complete_tag,
    complete_task_id,
)
from doxtr_doto.cli.validators import validate_priority, validate_status

if TYPE_CHECKING:
    from doxtr_doto.cli.config import DotoConfig
    from doxtr_doto.cli.main import DotoContext


# Maximum number of recurring task occurrences allowed in a single series.
# This prevents accidental creation of thousands of tasks.
# Can be overridden via config: doto.max_occurrences
MAX_OCCURRENCES = 500


def _add_months(d: date, months: int) -> date:
    """Add months to a date, handling month-end edge cases."""
    month = d.month + months
    year = d.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    # Handle edge cases like Jan 31 + 1 month
    days_in_month = [
        31,
        28 + (1 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 0),
        31,
        30,
        31,
        30,
        31,
        31,
        30,
        31,
        30,
        31,
    ]
    day = min(d.day, days_in_month[month - 1])
    return date(year, month, day)


def parse_relative_date(date_str: str) -> str:
    """Parse a relative date (optionally with a time) into storage format.

    Supports:
    - YYYY-MM-DD (passed through)
    - +Nd (N days from now)
    - +Nw (N weeks from now)
    - +Nm (N months from now)
    - today, tomorrow
    - monday, tuesday, etc. (next occurrence, could be today)
    - next-monday, next-tuesday, etc. (always in the future)
    - next-week, end-of-week, end-of-month

    An optional clock time may be appended to any of the above, space- or
    ``T``-separated (``friday 16:00``, ``+2d 16h``, ``2026-08-15T16:00:31``).
    The time is parsed/validated via :mod:`doxtr_doto.date_utils` and the result
    is returned in canonical storage format (``YYYY-MM-DD`` or
    ``YYYY-MM-DDTHH:MM[:SS]``), so date-only inputs are 100% unchanged.

    Args:
        date_str: Date string to parse (optionally with a time suffix).

    Returns:
        Date in ``YYYY-MM-DD`` format, or ``YYYY-MM-DDTHH:MM[:SS]`` when a time
        was supplied.
    """
    from doxtr_doto.date_utils import normalize_date, parse_time_token

    raw = date_str.strip()
    # Split off an optional time suffix (space- or ``T``-separated) so the
    # relative-date resolution below only ever sees the date portion. A ``T``
    # takes precedence; otherwise a trailing space-separated token that parses
    # as a time is treated as the time (so multi-word relatives like
    # ``next-week`` are unaffected -- they contain no space).
    date_part = raw
    time_suffix = ""
    if "T" in raw:
        date_part, _, time_token = raw.partition("T")
        time_token = time_token.strip()
        if time_token:
            time_suffix = parse_time_token(time_token).strftime("%H:%M:%S")
    elif " " in raw:
        head, _, tail = raw.rpartition(" ")
        tail = tail.strip()
        try:
            parsed_time = parse_time_token(tail)
        except ValueError:
            parsed_time = None
        if parsed_time is not None:
            date_part = head.strip()
            time_suffix = parsed_time.strftime("%H:%M:%S")

    resolved_date = _parse_relative_date_only(date_part.strip())

    if not time_suffix:
        return resolved_date
    # Re-join through date_utils so the stored form is canonical (seconds are
    # dropped when zero: ``16:00`` not ``16:00:00``).
    combined = normalize_date(f"{resolved_date}T{time_suffix}")
    return combined if combined is not None else resolved_date


def _parse_relative_date_only(date_str: str) -> str:
    """Parse a relative date string (no time) into YYYY-MM-DD format.

    This is the date-only core of :func:`parse_relative_date`; the public
    wrapper peels off any time suffix before delegating here.

    Args:
        date_str: Date string to parse.

    Returns:
        Date in YYYY-MM-DD format.
    """
    date_str = date_str.strip().lower()
    today = date.today()

    # Already in YYYY-MM-DD format - validate before returning
    if len(date_str) == 10 and date_str[4] == "-" and date_str[7] == "-":
        try:
            date.fromisoformat(date_str)
            return date_str
        except ValueError:
            # Fall through to error at end
            pass

    # Relative days: +7d
    if date_str.startswith("+") and date_str.endswith("d"):
        try:
            days = int(date_str[1:-1])
            return (today + timedelta(days=days)).isoformat()
        except ValueError:
            pass

    # Relative weeks: +2w
    if date_str.startswith("+") and date_str.endswith("w"):
        try:
            weeks = int(date_str[1:-1])
            return (today + timedelta(weeks=weeks)).isoformat()
        except ValueError:
            pass

    # Relative months: +2m
    if date_str.startswith("+") and date_str.endswith("m"):
        try:
            months = int(date_str[1:-1])
            return _add_months(today, months).isoformat()
        except ValueError:
            pass

    # Named days
    if date_str == "today":
        return today.isoformat()
    if date_str == "tomorrow":
        return (today + timedelta(days=1)).isoformat()

    # Period shortcuts
    if date_str == "next-week":
        return (today + timedelta(weeks=1)).isoformat()
    if date_str == "end-of-week":
        # End of week is Sunday
        days_until_sunday = 6 - today.weekday()
        return (today + timedelta(days=days_until_sunday)).isoformat()
    if date_str == "end-of-month":
        if today.month == 12:
            last_day = date(today.year + 1, 1, 1) - timedelta(days=1)
        else:
            last_day = date(today.year, today.month + 1, 1) - timedelta(days=1)
        return last_day.isoformat()

    # Weekday names
    weekdays = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }

    # next-monday, next-tuesday, etc. (always in the future)
    if date_str.startswith("next-"):
        day_name = date_str[5:]
        if day_name in weekdays:
            target_day = weekdays[day_name]
            current_day = today.weekday()
            days_ahead = target_day - current_day
            if days_ahead <= 0:
                days_ahead += 7
            return (today + timedelta(days=days_ahead)).isoformat()

    # monday, tuesday, etc. (next occurrence, could be today)
    if date_str in weekdays:
        target_day = weekdays[date_str]
        current_day = today.weekday()
        days_ahead = target_day - current_day
        if days_ahead < 0:
            days_ahead += 7
        return (today + timedelta(days=days_ahead)).isoformat()

    # Validate the date string - raise error for invalid dates
    try:
        # Try to parse as ISO format date
        parsed = date.fromisoformat(date_str)
        return parsed.isoformat()
    except ValueError as err:
        raise ValueError(
            f"Invalid date: '{date_str}'. Use YYYY-MM-DD or relative format "
            "(+7d, +2w, +1m, today, tomorrow, monday, next-monday, etc.)"
        ) from err


def _find_editor() -> str | None:
    """Find an available editor.

    Returns:
        Path to editor executable, or None if not found.
    """
    import shutil

    # Check environment variables first
    for var in ("EDITOR", "VISUAL"):
        editor = os.environ.get(var)
        if editor and shutil.which(editor):
            return editor

    # Try common editors
    for editor in ("nano", "vi", "vim"):
        if shutil.which(editor):
            return editor

    return None


def open_editor(initial_content: str = "") -> str:
    """Open an editor for the user to input text.

    Falls back to a simple prompt if no editor is available.

    Args:
        initial_content: Initial content to show in editor.

    Returns:
        Edited content.
    """
    editor = _find_editor()

    if not editor:
        # Fallback: simple multi-line input
        click.echo("Enter description (blank line to finish):")
        lines = []
        while True:
            try:
                line = input()
                if line == "":
                    break
                lines.append(line)
            except EOFError:
                break
        return "\n".join(lines).strip()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(initial_content)
        temp_path = f.name

    try:
        subprocess.run([editor, temp_path], check=True)
        with open(temp_path) as f:
            return f.read().strip()
    finally:
        os.unlink(temp_path)


def _prompt_missing_fields(
    config: DotoConfig,
    title: str | None,
    assignee: str | None,
    priority: str | None,
    status: str | None,
    due: str | None,
    tags: str | None,
    body: str | None,
) -> tuple[str | None, str | None, str | None, str | None, str | None, str | None, str | None]:
    """Interactively prompt for any missing fields.

    Args:
        config: DotoConfig instance with priorities, statuses, and defaults.
        title: Current title value (may be None).
        assignee: Current assignee value (may be None).
        priority: Current priority value (may be None).
        status: Current status value (may be None).
        due: Current due date value (may be None).
        tags: Current tags value (may be None).
        body: Current body value (may be None).

    Returns:
        Tuple of (title, assignee, priority, status, due, tags, body).
    """
    if not title:
        title = click.prompt("Title")
    if not assignee:
        assignee = click.prompt("Assignee", default="", show_default=False) or None
    if not priority:
        priority = click.prompt(
            "Priority",
            type=click.Choice(config.priorities),
            default=config.default_priority,
        )
    if not status:
        status = click.prompt(
            "Status",
            type=click.Choice(config.statuses),
            default=config.default_status,
        )
    if not due:
        due = click.prompt("Due date", default="", show_default=False) or None
    if not tags:
        tags = click.prompt("Tags (comma-separated)", default="", show_default=False) or None
    if not body and click.confirm("Add description?", default=False):
        body = open_editor()
    return title, assignee, priority, status, due, tags, body


def _resolve_title_from_editor(body: str | None) -> tuple[str, str | None]:
    """Open $EDITOR to get title (first line) and body (rest).

    Args:
        body: Existing body content to preserve if editor content has no body.

    Returns:
        Tuple of (title, body).
    """
    content = open_editor("# Enter task title on first line\n\n")
    lines = content.split("\n")
    title = lines[0].lstrip("#").strip()
    new_body = "\n".join(lines[1:]).strip() or body
    return title, new_body


def _build_task_data(
    config: DotoConfig,
    title: str,
    assignee: str | None,
    priority: str | None,
    status: str | None,
    due: str | None,
    tags: str | None,
    depends_on: str | None,
    body: str | None,
    rst_file: str | None,
    raci: str | None = None,
) -> dict[str, Any]:
    """Assemble the task data dict from parsed inputs.

    Applies config defaults for unset priority/status/assignee.
    Parses comma-separated tags and depends_on into lists.

    RACI defaults: when no explicit ``raci`` is given, the configured current
    user (``config.user``, resolved against the environment with a ``$USER``
    fallback) is auto-assigned as both Responsible and Accountable so a task
    added by a user records them without any interactive prompting. An
    explicit ``raci`` string overrides this entirely.

    Args:
        config: DotoConfig instance with defaults.
        title: Task title (required).
        assignee: Assignee name or None.
        priority: Priority value or None (uses config default).
        status: Status value or None (uses config default).
        due: Due date string or None.
        tags: Comma-separated tags string or None.
        depends_on: Comma-separated dependency IDs or None.
        body: Task body/description or None.
        rst_file: Target RST file for Sphinx mode or None.
        raci: Explicit RACI string (``"responsible alice, ..."``) or None.

    Returns:
        Task data dict ready for storage.
    """
    from doxtr_doto.cli.config import resolve_user
    from doxtr_doto.raci import parse_raci

    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    dep_list = [d.strip() for d in depends_on.split(",") if d.strip()] if depends_on else []

    raci_data: dict[str, list[str]] | None
    if raci is not None:
        raci_data = parse_raci(raci) or None
    else:
        current_user = resolve_user(config.user)
        if current_user:
            raci_data = {"responsible": [current_user], "accountable": [current_user]}
        else:
            raci_data = None

    task_data: dict[str, Any] = {
        "title": title,
        "assignee": assignee or config.default_assignee or None,
        "priority": priority or config.default_priority,
        "status": status or config.default_status,
        "due": due,
        "tags": tag_list,
        "depends_on": dep_list,
        "body": body,
        "raci": raci_data,
    }

    if rst_file:
        task_data["_sync"] = {
            "rst_file": rst_file,
            "rst_line": None,
            "rst_hash": None,
            "snapshot": None,
        }

    return task_data


@click.command("add")
@click.argument("title", nargs=-1)
@click.option("--id", "-I", "task_id", help="Task ID (auto-generated if omitted).")
@click.option("--assignee", "-a", shell_complete=complete_assignee, help="Assignee name.")
@click.option(
    "--priority",
    "-p",
    callback=validate_priority,
    shell_complete=complete_priority,
    help="Task priority.",
)
@click.option(
    "--status",
    "-s",
    callback=validate_status,
    shell_complete=complete_status,
    help="Task status.",
)
@click.option(
    "--due",
    "-d",
    shell_complete=complete_date,
    help="Due date (YYYY-MM-DD or relative: +7d, friday), optional time: 'friday 16:00'.",
)
@click.option("--tags", "-t", shell_complete=complete_tag, help="Comma-separated tags.")
@click.option(
    "--depends-on",
    "-D",
    shell_complete=complete_task_id,
    help="Comma-separated dependency task IDs.",
)
@click.option("--file", "-f", "rst_file", help="Target RST file (Sphinx mode only).")
@click.option("--body", "-b", help="Task description/body.")
@click.option("--edit", "-e", is_flag=True, help="Open $EDITOR for body.")
@click.option("--interactive", "-i", is_flag=True, help="Interactive prompt mode.")
@click.option(
    "--repeat",
    "-r",
    "repeat_pattern",
    shell_complete=complete_recurrence,
    help="Recurrence pattern (e.g., 'every friday', 'every 2 weeks on monday').",
)
@click.option(
    "--until",
    "-u",
    "until_date",
    shell_complete=complete_date,
    help="End date for recurring tasks (required with --repeat).",
)
@click.option(
    "--from",
    "-F",
    "from_date",
    shell_complete=complete_date,
    help="Series start date for recurring tasks (default: today; requires --repeat).",
)
@click.option("--dry-run", "-n", is_flag=True, help="Show output without writing.")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
@click.option("--raci", help='RACI roles (e.g. "responsible alice, accountable bob").')
@click.pass_obj
def add(
    ctx: DotoContext,
    title: tuple[str, ...],
    task_id: str | None,
    assignee: str | None,
    priority: str | None,
    status: str | None,
    due: str | None,
    tags: str | None,
    depends_on: str | None,
    rst_file: str | None,
    body: str | None,
    edit: bool,
    interactive: bool,
    repeat_pattern: str | None,
    until_date: str | None,
    from_date: str | None,
    dry_run: bool,
    json_output: bool,
    raci: str | None,
) -> None:
    """Add a new task.

    TITLE is the task title (can be multiple words). If omitted, use --interactive or --edit.

    For recurring tasks, use --repeat with --until:

        doto add "Weekly review" --repeat "every friday" --until 2025-12-31

        doto add "Sprint planning" --repeat "every 2 weeks on monday" --until +6m

        doto add "Monthly report {date}" --repeat "every month on last friday" --until +1y

    A pattern may carry a start time (``at HH:MM``) and a duration
    (``for <duration>``), and --from sets the series start date (default:
    today):

        doto add "Important Sync Meeting" \\
            --repeat "every 2 weeks on monday at 16:00 for 2h" \\
            --from 2026-11-01 -u 2027-10-10

    Use {date} in the title to include the occurrence date.

    Examples:

        doto add my next task i need to do

        doto add "Fix the login bug" --priority high

        doto add implement feature --assignee alice --due friday
    """
    formatter = ctx.formatter
    if json_output:
        formatter.json_output = True

    title_str: str | None = " ".join(title) if title else None

    if interactive:
        title_str, assignee, priority, status, due, tags, body = _prompt_missing_fields(
            ctx.config, title_str, assignee, priority, status, due, tags, body
        )

    if not title_str:
        if edit:
            title_str, body = _resolve_title_from_editor(body)
        else:
            raise click.UsageError("Title is required. Use --interactive or provide TITLE.")

    if repeat_pattern:
        _add_recurring_tasks(
            ctx=ctx,
            title_template=title_str,
            repeat_pattern=repeat_pattern,
            until_date=until_date,
            from_date=from_date,
            assignee=assignee,
            priority=priority,
            status=status,
            tags=tags,
            body=body,
            rst_file=rst_file,
            dry_run=dry_run,
        )
        return

    if until_date:
        raise click.UsageError("--until requires --repeat for recurring tasks.")

    if from_date:
        raise click.UsageError("--from requires --repeat for recurring tasks.")

    if not task_id:
        task_id = ctx.store.generate_id(
            prefix=ctx.config.id_prefix, sequential=ctx.config.id_sequential
        )

    if ctx.store.get_task(task_id):
        raise click.ClickException(f"Task with ID '{task_id}' already exists.")

    if due:
        due = parse_relative_date(due)

    if edit and not body:
        body = open_editor()

    task_data = _build_task_data(
        ctx.config,
        title_str,
        assignee,
        priority,
        status,
        due,
        tags,
        depends_on,
        body,
        rst_file,
        raci=raci,
    )

    from doxtr_doto.cli.id_resolver import cross_repo_deps

    offending = cross_repo_deps(ctx, ctx.store, list(task_data.get("depends_on", [])))
    if offending:
        raise click.ClickException(
            "Cross-repo dependencies are not supported: "
            f"{', '.join(offending)}. A dependency must live in the same "
            "repository as the task."
        )

    if dry_run:
        formatter.print("Would add task:")
        formatter.format_task_detail({"id": task_id, **task_data})
        return

    ctx.store.add_task(task_id, task_data)
    ctx.store.save()
    from doxtr_doto.cli import known_names
    from doxtr_doto.raci import raci_names

    known_names.remember_task_names(task_data.get("assignee"), task_data.get("tags", []))
    for rn in raci_names(task_data.get("raci")):
        known_names.remember_task_names(rn, [])
    formatter.print_success(f"Added task {task_id}")
    if not formatter.quiet:
        formatter.format_task_detail({"id": task_id, **task_data})


def _add_recurring_tasks(
    ctx: DotoContext,
    title_template: str,
    repeat_pattern: str,
    until_date: str | None,
    from_date: str | None,
    assignee: str | None,
    priority: str | None,
    status: str | None,
    tags: str | None,
    body: str | None,
    rst_file: str | None,
    dry_run: bool,
) -> None:
    """Create a recurring task series (the ``doto add --repeat`` path).

    A thin wrapper over :func:`doxtr_doto.cli.tui.actions.add_series`: this
    function owns the CLI-specific concerns -- parsing the pattern / dates,
    validating them, enforcing the occurrence limit, the ``--dry-run`` preview
    and the success printing -- while :func:`add_series` owns the actual
    occurrence/series building (shared with the TUI add-series dialog so the
    two never diverge).

    The ``--from`` date (``from_date``) sets the series start date (parsed via
    :func:`parse_relative_date`); without it the series starts today. The
    pattern may carry ``at HH:MM`` / ``for <duration>`` suffixes that
    :func:`parse_recurrence` turns into the pattern's ``start_time`` /
    ``duration_minutes`` (applied to each task's ``due`` / ``estimate``).
    """
    from doxtr_doto.cli.recurrence import (
        generate_occurrences,
        parse_recurrence,
        render_series_title,
    )
    from doxtr_doto.cli.tui import actions

    formatter = ctx.formatter
    config = ctx.config

    # Require --until for recurring tasks
    if not until_date:
        raise click.UsageError("--until is required for recurring tasks (--repeat).")

    # Parse recurrence pattern
    try:
        pattern = parse_recurrence(repeat_pattern)
    except ValueError as e:
        raise click.ClickException(str(e)) from e

    # Resolve the start date: --from when given, else today.
    if from_date:
        start_str = parse_relative_date(from_date)
        # Drop any time component; a series start is a calendar date.
        start = date.fromisoformat(start_str.split("T")[0])
    else:
        start = date.today()
    end_str = parse_relative_date(until_date)
    end = date.fromisoformat(end_str.split("T")[0])

    if end <= start:
        raise click.ClickException(
            f"End date ({end.isoformat()}) must be after start date ({start.isoformat()})."
        )

    # Generate occurrences (preview + limit check share this list)
    occurrences = list(generate_occurrences(pattern, start, end))

    if not occurrences:
        raise click.ClickException("No occurrences found for the given pattern and date range.")

    # Check occurrence limit to prevent accidental mass task creation
    # Get configurable limit from config, falling back to module default
    max_occurrences = getattr(config, "max_occurrences", MAX_OCCURRENCES)
    if len(occurrences) > max_occurrences:
        raise click.ClickException(
            f"Recurring task would create {len(occurrences)} tasks "
            f"(limit: {max_occurrences}).\n"
            f"Shorten the date range, increase the recurrence interval, "
            f"or adjust 'max_occurrences' in your config."
        )

    # Parse tags
    tag_list: list[str] = []
    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]

    # Build task defaults (shared by all tasks in series)
    task_defaults: dict[str, Any] = {
        "assignee": assignee or config.default_assignee or None,
        "priority": priority or config.default_priority,
        "status": status or config.default_status,
        "tags": tag_list,
        "depends_on": [],
        "body": body,
    }

    if rst_file:
        task_defaults["_sync"] = {
            "rst_file": rst_file,
            "rst_line": None,
            "rst_hash": None,
            "snapshot": None,
        }

    # Dry run
    if dry_run:
        formatter.print(f"Would create series with {len(occurrences)} tasks:")
        formatter.print(f"  Pattern: {pattern.describe()}")
        formatter.print(f"  From:    {start.isoformat()}")
        formatter.print(f"  Until:   {end.isoformat()}")
        formatter.print(f"  Title:   {title_template}")
        formatter.print("")
        formatter.print("Occurrences:")
        for occ in occurrences[:10]:
            title = render_series_title(title_template, occ)
            formatter.print(f"  {occ.isoformat()}: {title}")
        if len(occurrences) > 10:
            formatter.print(f"  ... and {len(occurrences) - 10} more")
        return

    # Build the series via the shared reusable helper (also used by the TUI).
    result = actions.add_series(
        ctx,
        title_template=title_template,
        pattern=pattern,
        start_date=start,
        end_date=end,
        task_defaults=task_defaults,
    )

    formatter.print_success(f"Created series {result.series_id} with {len(result.task_ids)} tasks")
    formatter.print(f"  Pattern: {pattern.describe()}")
    formatter.print(f"  Until:   {end.isoformat()}")
    if not formatter.quiet:
        formatter.print("")
        formatter.print("First few tasks:")
        for task_id in result.task_ids[:5]:
            task = ctx.store.get_task(task_id)
            if task:
                formatter.print(
                    f"  {task_id}: {task.get('title', '')} (due: {task.get('due', '')})"
                )
        if len(result.task_ids) > 5:
            formatter.print(f"  ... and {len(result.task_ids) - 5} more")
