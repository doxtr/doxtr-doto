"""doto timesheet - daily worked-tasks CSV export.

Emits a CSV of every worked interval on a given day - the global work-clock
intervals **and** each task's focus-session intervals - with each interval's
start/end rounded to the nearest quarter hour (midpoint rule), plus a final
``total`` row carrying the exact, unrounded work-clock span for the day
(earliest work-clock start to latest work-clock stop).

The heavy lifting lives in pure, child-overridable helpers in
:mod:`doxtr_doto.work_report` (``round_to_quarter_hour``, ``timesheet_rows``,
``work_span_seconds``, ``timesheet_csv``); this command is a thin shell that
gathers the raw data (the work clock + the shared cross-repo task collector)
and writes the result to a file or stdout, mirroring ``doto export``.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import click

from doxtr_doto.cli.task_collector import collect_repo_tasks
from doxtr_doto.work_report import (
    DEFAULT_TIMESHEET_COLUMNS,
    TIMESHEET_COLUMNS,
    timesheet_csv,
    timesheet_rows,
    work_span_seconds,
)

if TYPE_CHECKING:
    from doxtr_doto.cli.main import DotoContext


def _resolve_day(on: str | None, now: datetime) -> date:
    """Resolve the target day from ``--date`` (default: today).

    Args:
        on: Optional ``YYYY-MM-DD`` date string.
        now: Reference "now" used for the default.

    Returns:
        The resolved calendar date.

    Raises:
        click.ClickException: On an invalid ``--date`` value.
    """
    if not on:
        return now.date()
    try:
        return date.fromisoformat(on)
    except ValueError as exc:
        raise click.ClickException(f"Invalid --date {on!r} (expected YYYY-MM-DD).") from exc


def _parse_columns(columns: str | None) -> list[str]:
    """Parse and validate the ``--columns`` option.

    Args:
        columns: Comma-separated column names, or None for the default set.

    Returns:
        The ordered list of column names to emit.

    Raises:
        click.ClickException: If any column name is unrecognized or the option
            resolves to an empty set.
    """
    if not columns:
        return list(DEFAULT_TIMESHEET_COLUMNS)
    requested = [c.strip() for c in columns.split(",") if c.strip()]
    if not requested:
        raise click.ClickException("--columns must list at least one column.")
    unknown = [c for c in requested if c not in TIMESHEET_COLUMNS]
    if unknown:
        valid = ", ".join(sorted(TIMESHEET_COLUMNS))
        raise click.ClickException(
            f"Unknown timesheet column(s): {', '.join(unknown)}. Valid columns: {valid}."
        )
    return requested


@click.command("timesheet")
@click.option(
    "--date",
    "-d",
    "on",
    help="Day to export as YYYY-MM-DD (default: today).",
)
@click.option(
    "--output",
    "-o",
    "output_path",
    type=click.Path(),
    help="Output CSV file path. Prints to stdout if omitted.",
)
@click.option(
    "--columns",
    help=(
        "Comma-separated columns to emit. Available: "
        f"{', '.join(DEFAULT_TIMESHEET_COLUMNS)}. "
        "Defaults to all of them."
    ),
)
@click.pass_obj
def timesheet(
    ctx: DotoContext,
    on: str | None,
    output_path: str | None,
    columns: str | None,
) -> None:
    """Export a day's worked intervals (work clock + task sessions) to CSV.

    Each row is one worked interval: every global work-clock interval on the
    day plus each task's focus-session intervals, with start/end rounded to
    the nearest quarter hour (midpoint rule: < 7.5m rounds down, >= 7.5m
    rounds up). A final ``total`` row reports the exact, unrounded work-clock
    span (earliest work start to latest work stop) formatted as ``HH:MM``.

    Columns (configurable via ``--columns``): ``date``, ``start_time``,
    ``end_time``, ``task_id``, ``title``, ``kind`` (``work``/``task``/``total``)
    and ``duration`` (per-row rounded length, ``HH:MM``).

    Examples:

        doto timesheet                       # today, to stdout

        doto timesheet --date 2026-10-01

        doto timesheet -o sheet.csv

        doto timesheet --columns date,start_time,end_time
    """
    formatter = ctx.formatter

    now = datetime.now().astimezone()
    day = _resolve_day(on, now)
    cols = _parse_columns(columns)

    state = ctx.global_store.load()
    work_worklogs = state.work_clock.worklogs
    task_tuples = collect_repo_tasks(ctx)

    rows = timesheet_rows(work_worklogs, task_tuples, day, now)
    total_seconds = work_span_seconds(work_worklogs, day, now)
    content = timesheet_csv(rows, total_seconds, day, cols)

    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        formatter.print_success(f"Wrote timesheet for {day.isoformat()} to {path}")
    else:
        click.echo(content, nl=False)
        if not content.endswith("\n"):
            click.echo()
