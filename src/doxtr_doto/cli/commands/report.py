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

from doxtr_doto.cli.global_state import BreakConfig
from doxtr_doto.cli.session import format_duration
from doxtr_doto.cli.task_collector import collect_repo_tasks
from doxtr_doto.work_report import (
    BreakSpec,
    TaskBreakdown,
    WorkPeriod,
    compute_period,
    compute_task_breakdown,
    day_range,
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

    start, end, label = _resolve_range(period, on, year, now)

    work = compute_period(state.work_clock.worklogs, start, end, specs, now)
    task_tuples = collect_repo_tasks(ctx)
    breakdown = compute_task_breakdown(task_tuples, start, end, now)

    if json_output:
        _print_json(formatter, label, start, end, work, breakdown)
        return

    _render(formatter, label, work, breakdown, multi_day=period != "day")


def _print_json(
    formatter: OutputFormatter,
    label: str,
    start: date,
    end: date,
    work: WorkPeriod,
    breakdown: TaskBreakdown,
) -> None:
    """Emit the report as JSON."""
    formatter.print_json(
        {
            "period": label,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "work_clock": {
                "gross_seconds": work.gross_seconds,
                "break_seconds": work.break_seconds,
                "recorded_break_seconds": work.recorded_break_seconds,
                "net_seconds": work.net_seconds,
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
) -> None:
    """Render the human-readable report."""
    formatter.print(f"Work report — {label}", style="bold")
    formatter.print("")

    formatter.print("Work clock:", style="bold underline")
    formatter.print(f"  Gross clocked:   {format_duration(work.gross_seconds)}")
    formatter.print(f"  Recorded breaks: {format_duration(work.recorded_break_seconds)}")
    if work.break_seconds:
        formatter.print(f"  Auto-deducted:   {format_duration(work.break_seconds)}")
    formatter.print(f"  Net work:        {format_duration(work.net_seconds)}", style="green")

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
