"""doto report - break-aware work hours and task-time breakdown.

Reports the global work clock (gross clocked time, recorded break gaps, and
net work hours) for a day/week/month/year/all-time period, plus a *separate*
per-task / per-repo breakdown of focus-session time aggregated across every
registered repository. The two totals are never summed: task hours are shown
on their own, as requested.

Breaks are the real clock-out gaps the user recorded during the working day;
they are already excluded from gross and are surfaced as explicit "Breaks
taken" rows rather than silently deducted. A configured break only subtracts a
nominal duration when it opted into ``auto_deduct`` (for users who work
straight through without clocking out).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

import click

from doxtr_doto.cli.global_state import BreakConfig, LeaveEntry
from doxtr_doto.cli.session import format_duration
from doxtr_doto.cli.task_collector import collect_repo_tasks
from doxtr_doto.time_tracking import (
    LongSessionFinding,
    find_long_sessions,
    open_session,
)
from doxtr_doto.work_report import (
    BreakSpec,
    LeaveSpec,
    OvertimePeriod,
    TaskBreakdown,
    WorkPeriod,
    compute_overtime,
    compute_period,
    compute_task_breakdown,
    day_range,
    holiday_days_used,
    month_range,
    week_range,
    year_range,
)

if TYPE_CHECKING:
    from doxtr_doto.cli.main import DotoContext
    from doxtr_doto.cli.output import OutputFormatter


def _breaks_to_specs(breaks: list[BreakConfig]) -> list[BreakSpec]:
    """Convert stored break configs to report specs, skipping invalid ones.

    Args:
        breaks: Stored :class:`BreakConfig` entries.

    Returns:
        Valid :class:`BreakSpec` list (invalid ``time`` values are dropped).
    """
    specs: list[BreakSpec] = []
    for cfg in breaks:
        try:
            specs.append(BreakSpec.from_config(cfg))
        except ValueError:
            continue
    return specs


def _leave_to_specs(leave: list[LeaveEntry]) -> list[LeaveSpec]:
    """Convert stored leave entries to report specs, skipping invalid ones.

    Args:
        leave: Stored :class:`doxtr_doto.cli.global_state.LeaveEntry` entries.

    Returns:
        Valid :class:`LeaveSpec` list (entries with a bad date are dropped).
    """
    specs: list[LeaveSpec] = []
    for entry in leave:
        spec = LeaveSpec.from_entry(entry)
        if spec is not None:
            specs.append(spec)
    return specs


def _resolve_range(
    period: str,
    on: str | None,
    year: int | None,
    now: datetime,
) -> tuple[date, date, str]:
    """Resolve the ``(start, end, label)`` for the requested period.

    Args:
        period: One of ``day``/``week``/``month``/``year``/``all``.
        on: Optional anchor date (``YYYY-MM-DD``) for day/week/month.
        year: Optional explicit year for ``year`` period.
        now: Reference "now".

    Returns:
        Tuple of inclusive start/end dates and a display label.

    Raises:
        click.ClickException: On an invalid ``--on`` date.
    """
    anchor = now.date()
    if on:
        try:
            anchor = date.fromisoformat(on)
        except ValueError as exc:
            raise click.ClickException(f"Invalid --on date {on!r} (expected YYYY-MM-DD).") from exc

    if period == "day":
        start, end = day_range(anchor)
        return start, end, f"Day {start.isoformat()}"
    if period == "week":
        start, end = week_range(anchor)
        return start, end, f"Week {start.isoformat()} - {end.isoformat()}"
    if period == "month":
        start, end = month_range(anchor)
        return start, end, f"Month {start.strftime('%Y-%m')}"
    if period == "year":
        y = year if year is not None else anchor.year
        start, end = year_range(y)
        return start, end, f"Year {y}"
    # all-time: from earliest clocked day to today (bounded wide; empty days
    # are skipped by compute_period so this is cheap enough in practice).
    return date(1970, 1, 1), anchor, "All time"


@click.command("report")
@click.option(
    "--period",
    "-p",
    type=click.Choice(["day", "week", "month", "year", "all"]),
    default="day",
    help="Reporting period (default: day).",
)
@click.option("--on", help="Anchor date YYYY-MM-DD for day/week/month (default: today).")
@click.option("--year", "year", type=int, help="Explicit year for --period year.")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
@click.pass_obj
def report(
    ctx: DotoContext,
    period: str,
    on: str | None,
    year: int | None,
    json_output: bool,
) -> None:
    """Report work-clock hours and a separate per-task/per-repo breakdown.

    Shows gross clocked time, total auto-deducted break time, and net work
    hours for the work clock. Task focus-session time is reported on its own
    (per task and per repo) and is never added to the work total.

    Examples:

        doto report               # today

        doto report -p week

        doto report -p year --year 2026

        doto report -p all
    """
    formatter = ctx.formatter
    if json_output:
        formatter.json_output = True

    now = datetime.now().astimezone()
    state = ctx.global_store.load()
    specs = _breaks_to_specs(state.breaks)
    leave_specs = _leave_to_specs(state.leave_days)

    start, end, label = _resolve_range(period, on, year, now)

    work = compute_period(state.work_clock.worklogs, start, end, specs, now)
    overtime = compute_overtime(
        work,
        start,
        end,
        day_length_minutes=state.day_length_minutes,
        week_length_minutes=state.week_length_minutes,
        workweek_days=list(state.workweek_days),
        leave=leave_specs,
    )
    open_work = open_session(state.work_clock.worklogs)
    work_started_at = (
        str(open_work["started_at"]) if open_work and open_work.get("started_at") else None
    )
    long_sessions = find_long_sessions(
        state.work_clock.worklogs,
        now=now,
        day_length_minutes=state.day_length_minutes,
    )
    # Yearly holiday allowance accounting is anchored on the period's end year
    # (for an "all" period this is today's year) so the "remaining" figure is
    # meaningful against the calendar-year allowance.
    allowance_year = end.year
    holidays_used = holiday_days_used(leave_specs, allowance_year)
    task_tuples = collect_repo_tasks(ctx)
    breakdown = compute_task_breakdown(task_tuples, start, end, now)

    if json_output:
        _print_json(
            formatter,
            label,
            start,
            end,
            work,
            breakdown,
            overtime,
            allowance_year,
            float(state.holiday_allowance_days),
            holidays_used,
            work_started_at=work_started_at,
            long_sessions=long_sessions,
        )
        return

    _render(
        formatter,
        label,
        work,
        breakdown,
        multi_day=period != "day",
        overtime=overtime,
        allowance_year=allowance_year,
        holiday_allowance=float(state.holiday_allowance_days),
        holidays_used=holidays_used,
        work_started_at=work_started_at,
        long_sessions=long_sessions,
    )


def _print_json(
    formatter: OutputFormatter,
    label: str,
    start: date,
    end: date,
    work: WorkPeriod,
    breakdown: TaskBreakdown,
    overtime: OvertimePeriod,
    allowance_year: int,
    holiday_allowance: float,
    holidays_used: float,
    *,
    work_started_at: str | None = None,
    long_sessions: list[LongSessionFinding] | None = None,
) -> None:
    """Emit the report as JSON."""
    flagged = long_sessions or []
    formatter.print_json(
        {
            "period": label,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "overtime": {
                "worked_seconds": overtime.worked_seconds,
                "leave_credit_seconds": overtime.leave_credit_seconds,
                "expected_seconds": overtime.expected_seconds,
                "overtime_seconds": overtime.overtime_seconds,
                "working_days": overtime.working_days,
                "holiday_days_taken": overtime.holiday_days_taken,
                "sick_days_taken": overtime.sick_days_taken,
            },
            "holidays": {
                "year": allowance_year,
                "allowance_days": holiday_allowance,
                "used_days": holidays_used,
                "remaining_days": holiday_allowance - holidays_used,
            },
            "work_clock": {
                "running_since": work_started_at,
                "gross_seconds": work.gross_seconds,
                "break_seconds": work.break_seconds,
                "recorded_break_seconds": work.recorded_break_seconds,
                "net_seconds": work.net_seconds,
                "flagged_sessions": [
                    {
                        "index": f.index,
                        "started_at": f.started_at,
                        "stopped_at": f.stopped_at,
                        "duration_seconds": f.duration_seconds,
                        "is_open": f.is_open,
                        "reasons": list(f.reasons),
                    }
                    for f in flagged
                ],
                "days": [
                    {
                        "day": d.day.isoformat(),
                        "gross_seconds": d.gross_seconds,
                        "break_seconds": d.total_break_seconds,
                        "recorded_break_seconds": d.recorded_break_seconds,
                        "net_seconds": d.net_seconds,
                        "breaks": [
                            {
                                "name": b.name,
                                "deducted_seconds": b.deducted_seconds,
                                "gap_seconds": b.gap_seconds,
                            }
                            for b in d.break_deductions
                        ],
                        "recorded_breaks": [
                            {
                                "start": rb.start.isoformat(),
                                "stop": rb.stop.isoformat(),
                                "seconds": rb.seconds,
                            }
                            for rb in d.recorded_breaks
                        ],
                    }
                    for d in work.days
                ],
            },
            "task_hours": {
                "total_seconds": breakdown.total_seconds,
                "per_repo": breakdown.per_repo,
                "tasks": [
                    {
                        "repo": t.repo,
                        "task_id": t.task_id,
                        "title": t.title,
                        "seconds": t.seconds,
                    }
                    for t in breakdown.tasks
                ],
            },
        }
    )


def _render(
    formatter: OutputFormatter,
    label: str,
    work: WorkPeriod,
    breakdown: TaskBreakdown,
    multi_day: bool,
    *,
    overtime: OvertimePeriod,
    allowance_year: int,
    holiday_allowance: float,
    holidays_used: float,
    work_started_at: str | None = None,
    long_sessions: list[LongSessionFinding] | None = None,
) -> None:
    """Render the human-readable report."""
    formatter.print(f"Work report — {label}", style="bold")
    formatter.print("")

    formatter.print("Work clock:", style="bold underline")
    if work_started_at:
        formatter.print(f"  Running since:   {work_started_at}")
    formatter.print(f"  Gross clocked:   {format_duration(work.gross_seconds)}")
    formatter.print(f"  Recorded breaks: {format_duration(work.recorded_break_seconds)}")
    if work.break_seconds:
        formatter.print(f"  Auto-deducted:   {format_duration(work.break_seconds)}")
    formatter.print(f"  Net work:        {format_duration(work.net_seconds)}", style="green")

    if long_sessions:
        formatter.print("")
        formatter.print("  Warnings (overly long / forgotten work-clock sessions):", style="yellow")
        for f in long_sessions:
            stop_str = f.stopped_at if f.stopped_at else "(still running)"
            reasons = ", ".join(f.reasons)
            formatter.print(
                f"    {f.started_at} -> {stop_str}  "
                f"({format_duration(f.duration_seconds)}; {reasons})",
                style="yellow",
            )
        formatter.print(
            "    Hint: inspect/fix these in `doto tui` via `t a` (Session audit) or `t w`.",
            style="dim",
        )

    if work.days:
        recorded_rows = [
            (d.day, rb) for d in work.days for rb in d.recorded_breaks if rb.seconds > 0
        ]
        if recorded_rows:
            formatter.print("")
            formatter.print("  Breaks taken:")
            for day, rb in recorded_rows:
                prefix = f"{day.isoformat()}  " if multi_day else ""
                formatter.print(
                    f"    {prefix}{rb.start.strftime('%H:%M')}-{rb.stop.strftime('%H:%M')}  "
                    f"({format_duration(rb.seconds)})"
                )

    if multi_day and work.days:
        formatter.print("")
        formatter.print("  Per day:")
        for d in work.days:
            formatter.print(
                f"    {d.day.isoformat()}  "
                f"gross {format_duration(d.gross_seconds)}  "
                f"breaks {format_duration(d.recorded_break_seconds)}  "
                f"net {format_duration(d.net_seconds)}"
            )

    _render_overtime(formatter, overtime, allowance_year, holiday_allowance, holidays_used)

    formatter.print("")
    formatter.print("Task hours (reported separately):", style="bold underline")
    if not breakdown.tasks:
        formatter.print("  (no task sessions in this period)")
        return

    formatter.print(f"  Total task time: {format_duration(breakdown.total_seconds)}")
    formatter.print("")
    formatter.print("  Per repo:")
    for repo, seconds in sorted(breakdown.per_repo.items(), key=lambda kv: kv[1], reverse=True):
        formatter.print(f"    {repo}: {format_duration(seconds)}")

    formatter.print("")
    formatter.print("  Per task:")
    for t in breakdown.tasks:
        title = (t.title[:40] + "…") if len(t.title) > 41 else t.title
        formatter.print(f"    {t.repo}#{t.task_id}  {format_duration(t.seconds)}  {title}")


def _format_signed_duration(seconds: int) -> str:
    """Format a possibly-negative duration with an explicit sign.

    Overtime can be negative (a shortfall / undertime), so a leading ``+`` or
    ``-`` is prepended to :func:`format_duration` of the magnitude. Zero reads
    as a plain ``0s`` with no sign.

    Args:
        seconds: Signed duration in whole seconds.

    Returns:
        E.g. ``"+1h30m00s"``, ``"-45m00s"``, or ``"0s"``.
    """
    if seconds == 0:
        return format_duration(0)
    sign = "+" if seconds > 0 else "-"
    return sign + format_duration(abs(seconds))


def _format_days(days: float) -> str:
    """Format a day count, dropping a trailing ``.0`` on whole numbers.

    Args:
        days: A (possibly fractional) number of days.

    Returns:
        E.g. ``"5"`` or ``"4.5"``.
    """
    if days == int(days):
        return str(int(days))
    return f"{days:.1f}"


def _render_overtime(
    formatter: OutputFormatter,
    overtime: OvertimePeriod,
    allowance_year: int,
    holiday_allowance: float,
    holidays_used: float,
) -> None:
    """Render the overtime + holidays/sick-days block.

    Shows expected vs. worked time (with leave credited), the resulting
    overtime/shortfall, and the holiday allowance drawdown plus any sick days
    recorded in the period. When the period accrues no working-day
    expectation and no leave was recorded the block is omitted entirely so the
    report stays compact for a day with nothing to say about leave.

    Args:
        formatter: The output formatter.
        overtime: The computed overtime/leave summary.
        allowance_year: The calendar year the allowance drawdown is anchored
            on (the period's end year).
        holiday_allowance: The configured yearly holiday allowance in days.
        holidays_used: Holiday days taken in ``allowance_year``.
    """
    has_leave = overtime.holiday_days_taken > 0 or overtime.sick_days_taken > 0
    if overtime.expected_seconds == 0 and not has_leave:
        return

    formatter.print("")
    formatter.print("Overtime & leave:", style="bold underline")
    formatter.print(
        f"  Expected:        {format_duration(overtime.expected_seconds)}  "
        f"({overtime.working_days} working day(s))"
    )
    formatter.print(f"  Worked (net):    {format_duration(overtime.worked_seconds)}")
    if overtime.leave_credit_seconds:
        formatter.print(f"  Leave credit:    {format_duration(overtime.leave_credit_seconds)}")
    ot_style = "green" if overtime.overtime_seconds >= 0 else "yellow"
    formatter.print(
        f"  Overtime:        {_format_signed_duration(overtime.overtime_seconds)}",
        style=ot_style,
    )
    if overtime.worked_seconds == 0 and overtime.leave_credit_seconds == 0:
        formatter.print(
            "  Note:            no work-clock intervals recorded for this period "
            "(overtime uses the global work clock, not task focus timers).",
            style="dim",
        )

    if has_leave:
        formatter.print("")
        formatter.print("  Leave in period:")
        if overtime.holiday_days_taken:
            formatter.print(f"    Holidays: {_format_days(overtime.holiday_days_taken)} day(s)")
        if overtime.sick_days_taken:
            formatter.print(f"    Sick:     {_format_days(overtime.sick_days_taken)} day(s)")

    remaining = holiday_allowance - holidays_used
    formatter.print("")
    formatter.print(f"  Holiday allowance ({allowance_year}):")
    formatter.print(f"    Allowance: {_format_days(holiday_allowance)} day(s)")
    formatter.print(f"    Used:      {_format_days(holidays_used)} day(s)")
    remaining_style = "green" if remaining >= 0 else "red"
    formatter.print(
        f"    Remaining: {_format_days(remaining)} day(s)",
        style=remaining_style,
    )
