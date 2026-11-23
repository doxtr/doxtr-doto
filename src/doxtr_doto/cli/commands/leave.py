"""doto leave - record and manage holidays and sick days.

Leave days are the counterpart to the work clock: on a leave day the user does
not clock in, but the day still counts toward the expected working time so a
day off reads as neither overtime nor a shortfall. A ``holiday`` draws down the
configured yearly allowance; a ``sick`` day is tracked separately.

Subcommands:

* ``doto leave add <date> [--to <date>] [--kind holiday|sick] [--half] [--note ...]``
  records one day or an inclusive range of leave.
* ``doto leave list [--year N] [--kind ...]`` lists recorded leave.
* ``doto leave remove <date> [--kind ...]`` deletes recorded leave on a date.

Dates accept the same relative expressions as ``doto add`` (``today``,
``tomorrow``, ``friday``, ``+7d``, ``YYYY-MM-DD``).
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import click

from doxtr_doto.cli.commands.add import parse_relative_date
from doxtr_doto.cli.global_state import (
    LEAVE_KINDS,
    LeaveEntry,
    apply_leave_range,
    sanitize_leave_kind,
)

if TYPE_CHECKING:
    from doxtr_doto.cli.main import DotoContext


def _resolve_date(value: str) -> date:
    """Resolve a user-supplied date string to a concrete :class:`date`.

    Reuses :func:`doxtr_doto.cli.commands.add.parse_relative_date` so leave
    dates accept the same relative expressions as ``doto add``, then strips
    any time suffix (leave is a whole-day concept).

    Args:
        value: The raw date string (relative or ISO).

    Returns:
        The resolved calendar date.

    Raises:
        click.ClickException: On an unparseable date.
    """
    try:
        resolved = parse_relative_date(value)
    except ValueError as exc:
        raise click.ClickException(f"Invalid date {value!r}: {exc}") from exc
    iso = resolved.split("T", 1)[0]
    try:
        return date.fromisoformat(iso)
    except ValueError as exc:
        raise click.ClickException(f"Invalid date {value!r}.") from exc


@click.group("leave")
def leave() -> None:
    """Record and manage holidays and sick days.

    Examples:

        doto leave add 2026-07-06 --to 2026-07-10   # a week of holiday

        doto leave add today --kind sick

        doto leave add friday --half --note "afternoon off"

        doto leave list --year 2026

        doto leave remove 2026-07-06

        doto leave remove 2026-07-06 --to 2026-07-10   # remove a whole range
    """


@leave.command("add")
@click.argument("start")
@click.option("--to", "end", help="End of an inclusive date range (default: single day).")
@click.option(
    "--kind",
    "-k",
    type=click.Choice(list(LEAVE_KINDS)),
    default="holiday",
    help="Leave kind (default: holiday).",
)
@click.option("--half", is_flag=True, help="Record half days (fraction 0.5) instead of full days.")
@click.option("--note", default="", help="Optional note (e.g. the holiday's name).")
@click.option(
    "--include-weekends",
    is_flag=True,
    help="Also record leave on days outside the configured work week.",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
@click.pass_obj
def leave_add(
    ctx: DotoContext,
    start: str,
    end: str | None,
    kind: str,
    half: bool,
    note: str,
    include_weekends: bool,
    json_output: bool,
) -> None:
    """Record one day (or an inclusive range) of leave.

    By default a range skips days outside the configured work week (so a
    Mon-Fri holiday block does not record Saturday/Sunday); pass
    ``--include-weekends`` to record every day in the range.
    """
    formatter = ctx.formatter
    if json_output:
        formatter.json_output = True

    start_date = _resolve_date(start)
    end_date = _resolve_date(end) if end else start_date
    if end_date < start_date:
        start_date, end_date = end_date, start_date

    state = ctx.global_store.load()
    fraction = 0.5 if half else 1.0
    added, skipped_weekend = apply_leave_range(
        state.leave_days,
        start_date,
        end_date,
        kind,
        fraction=fraction,
        note=note,
        workweek_days=list(state.workweek_days),
        include_weekends=include_weekends,
    )
    ctx.global_store.save(state)

    if json_output:
        formatter.print_json(
            {
                "action": "leave-add",
                "kind": kind,
                "fraction": fraction,
                "added": added,
                "skipped_weekend": skipped_weekend,
            }
        )
        return

    if not added:
        formatter.print_warning("No new leave days recorded (already present or all weekends).")
        return
    noun = "half-day" if half else "day"
    formatter.print_success(f"Recorded {len(added)} {kind} {noun}(s): {', '.join(added)}.")
    if skipped_weekend:
        formatter.print(
            f"  Skipped {skipped_weekend} non-work-week day(s) "
            "(use --include-weekends to record them)."
        )


@leave.command("list")
@click.option("--year", type=int, help="Only show leave in this calendar year.")
@click.option(
    "--kind",
    "-k",
    type=click.Choice(list(LEAVE_KINDS)),
    help="Only show this leave kind.",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
@click.pass_obj
def leave_list(
    ctx: DotoContext,
    year: int | None,
    kind: str | None,
    json_output: bool,
) -> None:
    """List recorded holidays and sick days."""
    formatter = ctx.formatter
    if json_output:
        formatter.json_output = True

    state = ctx.global_store.load()
    entries = sorted(state.leave_days, key=lambda e: (e.date, e.kind))
    rows: list[LeaveEntry] = []
    for entry in entries:
        if kind and entry.kind != kind:
            continue
        if year is not None:
            try:
                if date.fromisoformat(entry.date).year != year:
                    continue
            except ValueError:
                continue
        rows.append(entry)

    holiday_days = sum(e.fraction for e in rows if e.kind == "holiday")
    sick_days = sum(e.fraction for e in rows if e.kind == "sick")

    if json_output:
        formatter.print_json(
            {
                "year": year,
                "kind": kind,
                "holiday_days": holiday_days,
                "sick_days": sick_days,
                "allowance_days": float(state.holiday_allowance_days),
                "entries": [e.to_dict() for e in rows],
            }
        )
        return

    if not rows:
        formatter.print("No leave recorded for the given filter.")
        return

    formatter.print("Recorded leave:", style="bold")
    for entry in rows:
        frac = "" if entry.fraction == 1.0 else f" ({_fmt_days(entry.fraction)}d)"
        note = f"  {entry.note}" if entry.note else ""
        formatter.print(f"  {entry.date}  {entry.kind}{frac}{note}")
    formatter.print("")
    formatter.print(
        f"  Holidays: {_fmt_days(holiday_days)} day(s)   Sick: {_fmt_days(sick_days)} day(s)"
    )
    if year is not None:
        remaining = float(state.holiday_allowance_days) - holiday_days
        formatter.print(
            f"  Allowance {year}: {_fmt_days(state.holiday_allowance_days)} used "
            f"{_fmt_days(holiday_days)} remaining {_fmt_days(remaining)}"
        )


@leave.command("remove")
@click.argument("start", metavar="DATE")
@click.option("--to", "end", help="End of an inclusive date range (default: single day).")
@click.option(
    "--kind",
    "-k",
    type=click.Choice(list(LEAVE_KINDS)),
    help="Only remove this kind of leave on the date(s).",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
@click.pass_obj
def leave_remove(
    ctx: DotoContext,
    start: str,
    end: str | None,
    kind: str | None,
    json_output: bool,
) -> None:
    """Remove recorded leave on a date or an inclusive range.

    Mirrors ``leave add``: pass ``--to`` to remove every recorded leave day in
    an inclusive range (weekends included, since only days that were actually
    recorded are affected). An optional ``--kind`` narrows the removal to
    holidays or sick days.
    """
    formatter = ctx.formatter
    if json_output:
        formatter.json_output = True

    start_date = _resolve_date(start)
    end_date = _resolve_date(end) if end else start_date
    if end_date < start_date:
        start_date, end_date = end_date, start_date
    start_iso = start_date.isoformat()
    end_iso = end_date.isoformat()

    state = ctx.global_store.load()
    removed_dates = sorted(
        {
            e.date
            for e in state.leave_days
            if start_iso <= e.date <= end_iso and (kind is None or e.kind == kind)
        }
    )
    before = len(state.leave_days)
    state.leave_days = [
        e
        for e in state.leave_days
        if not (start_iso <= e.date <= end_iso and (kind is None or e.kind == kind))
    ]
    removed = before - len(state.leave_days)
    ctx.global_store.save(state)

    if json_output:
        formatter.print_json(
            {
                "action": "leave-remove",
                "start": start_iso,
                "end": end_iso,
                "removed": removed,
                "removed_dates": removed_dates,
            }
        )
        return

    if removed:
        scope = start_iso if start_iso == end_iso else f"{start_iso}..{end_iso}"
        formatter.print_success(f"Removed {removed} leave entry(ies) on {scope}.")
    else:
        scope = start_iso if start_iso == end_iso else f"{start_iso}..{end_iso}"
        formatter.print_warning(f"No matching leave on {scope}.")


def _fmt_days(days: float) -> str:
    """Format a day count, dropping a trailing ``.0`` on whole numbers."""
    if days == int(days):
        return str(int(days))
    return f"{days:.1f}"


# ``sanitize_leave_kind`` is imported for callers that want to normalize a raw
# kind before passing it in; re-exported for convenience.
__all__ = ["leave", "sanitize_leave_kind"]
