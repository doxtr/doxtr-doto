"""Break-aware work-clock reporting.

This module turns raw work-clock intervals and per-task sessions into
day/week/month/year/all-time reports. It is deliberately pure (no I/O): the
CLI and TUI gather the raw data and hand it to these functions.

Two tracking layers are reported **separately** and are never summed:

* The *work clock* (Layer 1) is the global clock-in/clock-out. Its gross
  time has configured breaks auto-deducted (only for breaks worked straight
  through) to yield a *net* work total.
* *Task sessions* (Layer 2) are per-task focus timers. They are reported on
  their own, broken down per task and per repository.

Break semantics
---------------

A break is modelled as **real recorded non-worked time**: the clock-out gap
between two work-clock intervals (when the user is on break they are clocked
out). Because such a gap falls *outside* every clocked interval, it is already
excluded from the day's gross worked seconds and therefore needs no further
deduction. The report surfaces each recorded break gap as an explicit
``RecordedBreak`` row (span + duration) so a break shows up as what actually
happened, regardless of the time of day it occurred.

This is the fix for the double-counting bug: a break taken *outside* a
configured nominal window (e.g. ``12:55-13:34`` for a ``12:00`` lunch) used to
leave the full configured duration deducted on top of the already-missing
worked time. Now the recorded gap is simply the break, and nothing extra is
subtracted.

Opt-in auto-deduction (``BreakConfig.auto_deduct``)
---------------------------------------------------

For users who do **not** clock out for breaks (they work straight through),
a configured break may set ``auto_deduct=True`` to restore the old
time-window-based behavior:

* The break's *window* is ``[time - leeway, time + leeway]``.
* A real clock-out gap that *starts* inside the window is credited as the
  break already taken.
* The amount auto-deducted is ``max(0, duration - gap_already_taken)``. If
  the user worked straight through (no gap in the window), the full
  ``duration`` is deducted; a gap at least as long as the configured duration
  deducts nothing extra.

Auto-deduction is **off by default**: the headline behavior never
double-counts, and only an explicitly opted-in break subtracts a nominal
duration.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from doxtr_doto.sync.json_store import WorkLog
from doxtr_doto.time_tracking import parse_timestamp


@dataclass
class BreakSpec:
    """Normalized break specification used by the report math.

    Mirrors :class:`doxtr_doto.cli.global_state.BreakConfig` but decoupled so
    this module has no dependency on CLI/global-state types.

    Attributes:
        name: Human label.
        hour: Nominal break hour (0-23).
        minute: Nominal break minute (0-59).
        duration_minutes: Intended break length in minutes.
        leeway_minutes: Drift tolerance on each side of the nominal time.
        auto_deduct: When True, auto-deduct the nominal duration (opt-in
            legacy straight-through behavior). Defaults to False.
    """

    name: str
    hour: int
    minute: int
    duration_minutes: int
    leeway_minutes: int
    auto_deduct: bool = False

    @classmethod
    def from_config(cls, cfg: object) -> BreakSpec:
        """Build a BreakSpec from a BreakConfig-like object.

        Args:
            cfg: An object with ``name``, ``time`` (``"HH:MM"``),
                ``duration_minutes`` and ``leeway_minutes`` attributes, plus an
                optional ``auto_deduct`` flag (defaults to ``False`` when
                absent, so older config objects degrade gracefully).

        Returns:
            A normalized BreakSpec.

        Raises:
            ValueError: If ``time`` is not a valid ``HH:MM`` string.
        """
        raw = str(getattr(cfg, "time", "")).strip()
        parts = raw.split(":")
        if len(parts) != 2:
            raise ValueError(f"Invalid break time {raw!r}; expected HH:MM.")
        hour, minute = int(parts[0]), int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError(f"Break time {raw!r} out of range.")
        return cls(
            name=str(getattr(cfg, "name", "")),
            hour=hour,
            minute=minute,
            duration_minutes=int(getattr(cfg, "duration_minutes", 0)),
            leeway_minutes=int(getattr(cfg, "leeway_minutes", 30)),
            auto_deduct=bool(getattr(cfg, "auto_deduct", False)),
        )


@dataclass
class BreakDeduction:
    """The outcome of applying one break to one day.

    Attributes:
        name: Break label.
        deducted_seconds: Seconds auto-deducted from gross for this break.
            Always ``0`` unless the break opted in with ``auto_deduct=True``.
        gap_seconds: Seconds already taken as a clock-out gap in the window.
    """

    name: str
    deducted_seconds: int
    gap_seconds: int


@dataclass
class RecordedBreak:
    """A real clock-out gap recorded during the working day.

    A recorded break is the span between one interval's stop and the next
    interval's start - the time the user was actually clocked out mid-day.
    It is surfaced for display (an explicit "break" row) and is already
    excluded from :attr:`DayWork.gross_seconds`, so it is **never** deducted
    again.

    Attributes:
        start: Gap start (when the user clocked out), timezone-aware.
        stop: Gap end (when the user clocked back in), timezone-aware.
        seconds: Gap length in whole seconds.
    """

    start: datetime
    stop: datetime
    seconds: int


@dataclass
class DayWork:
    """Work-clock figures for a single calendar day.

    Attributes:
        day: The calendar date.
        gross_seconds: Sum of all clocked intervals on this day.
        break_deductions: Per-break auto-deduction detail (only non-zero when
            a configured break opted in with ``auto_deduct=True``).
        recorded_breaks: Real clock-out gaps recorded during the working day
            (the explicit breaks the user actually took). These are already
            excluded from ``gross_seconds`` and are shown, not deducted.
    """

    day: date
    gross_seconds: int = 0
    break_deductions: list[BreakDeduction] = field(default_factory=list)
    recorded_breaks: list[RecordedBreak] = field(default_factory=list)

    @property
    def total_break_seconds(self) -> int:
        """Total auto-deducted break seconds for the day.

        Only counts explicit opt-in (``auto_deduct=True``) deductions; the
        default behavior deducts nothing because recorded break gaps are
        already excluded from gross.
        """
        return sum(d.deducted_seconds for d in self.break_deductions)

    @property
    def recorded_break_seconds(self) -> int:
        """Total seconds of real recorded clock-out breaks for the day."""
        return sum(b.seconds for b in self.recorded_breaks)

    @property
    def net_seconds(self) -> int:
        """Net work seconds (gross minus any opt-in auto-deducted breaks).

        Recorded break gaps are already excluded from ``gross_seconds`` (they
        fall outside every clocked interval), so only opt-in auto-deductions
        reduce net further.
        """
        return max(0, self.gross_seconds - self.total_break_seconds)


def _clip_interval(
    started: datetime,
    stopped: datetime,
    day: date,
) -> tuple[datetime, datetime] | None:
    """Clip an interval to the portion falling on ``day`` (local date).

    Args:
        started: Interval start (timezone-aware).
        stopped: Interval stop (timezone-aware).
        day: The target calendar date.

    Returns:
        The clipped ``(start, stop)`` tuple, or None if no overlap.
    """
    tz = started.tzinfo
    day_start = datetime.combine(day, time.min, tzinfo=tz)
    day_end = day_start + timedelta(days=1)
    lo = max(started, day_start)
    hi = min(stopped, day_end)
    if hi <= lo:
        return None
    return lo, hi


def _day_intervals(
    worklogs: list[WorkLog],
    day: date,
    now: datetime,
) -> list[tuple[datetime, datetime]]:
    """Return sorted, clipped ``(start, stop)`` intervals on ``day``.

    Open intervals are closed at ``now``. Intervals are clipped to the day
    boundary so overnight sessions are attributed correctly per day.

    Args:
        worklogs: Raw worklog intervals.
        day: The calendar date to extract.
        now: Reference time for open intervals.

    Returns:
        Sorted list of clipped intervals on the day.
    """
    intervals: list[tuple[datetime, datetime]] = []
    for log in worklogs:
        started_raw = log.get("started_at")
        if not started_raw:
            continue
        started = parse_timestamp(str(started_raw))
        stopped_raw = log.get("stopped_at")
        stopped = parse_timestamp(str(stopped_raw)) if stopped_raw else now
        if stopped <= started:
            continue
        clipped = _clip_interval(started, stopped, day)
        if clipped is not None:
            intervals.append(clipped)
    intervals.sort(key=lambda iv: iv[0])
    return intervals


def _window_bounds(spec: BreakSpec, day: date, tz: object) -> tuple[datetime, datetime, datetime]:
    """Return ``(window_start, nominal, window_end)`` for a break on a day.

    Args:
        spec: The break spec.
        day: The calendar date.
        tz: The timezone of the day's intervals.

    Returns:
        Tuple of the leeway window start, the nominal break time, and the
        leeway window end.
    """
    nominal = datetime.combine(day, time(spec.hour, spec.minute), tzinfo=tz)  # type: ignore[arg-type]
    leeway = timedelta(minutes=spec.leeway_minutes)
    return nominal - leeway, nominal, nominal + leeway


def _gap_in_window(
    intervals: list[tuple[datetime, datetime]],
    window_start: datetime,
    window_end: datetime,
) -> int:
    """Seconds of clock-out gap whose start falls within the break window.

    A gap is the span between consecutive intervals. Only gaps that *begin*
    inside ``[window_start, window_end]`` are credited against the break
    (matching the "a gap starting within the window counts as that break"
    rule). The full gap length is returned (capped later by the caller).

    Args:
        intervals: Sorted, clipped intervals for the day.
        window_start: Start of the break's leeway window.
        window_end: End of the break's leeway window.

    Returns:
        Total gap seconds attributable to this break window.
    """
    total = 0
    for i in range(len(intervals) - 1):
        gap_start = intervals[i][1]
        gap_end = intervals[i + 1][0]
        if gap_end <= gap_start:
            continue
        if window_start <= gap_start <= window_end:
            total += int((gap_end - gap_start).total_seconds())
    # Only gaps *between* two clocked intervals are considered here. A trailing
    # open period after the last interval of the day is not a gap (the user is
    # simply clocked out for the rest of the day), so it contributes nothing.
    return total


def _recorded_gaps(
    intervals: list[tuple[datetime, datetime]],
) -> list[RecordedBreak]:
    """Return the real clock-out gaps between consecutive clocked intervals.

    Each gap (one interval's stop to the next interval's start) is time the
    user was clocked out during the working day - i.e. a real break. These
    gaps already fall outside every clocked interval, so they are not part of
    gross and are surfaced for display rather than deducted.

    Args:
        intervals: Sorted, clipped intervals for the day.

    Returns:
        One :class:`RecordedBreak` per positive-length gap, in time order.
    """
    gaps: list[RecordedBreak] = []
    for i in range(len(intervals) - 1):
        gap_start = intervals[i][1]
        gap_end = intervals[i + 1][0]
        if gap_end <= gap_start:
            continue
        gaps.append(
            RecordedBreak(
                start=gap_start,
                stop=gap_end,
                seconds=int((gap_end - gap_start).total_seconds()),
            )
        )
    return gaps


def compute_day(
    worklogs: list[WorkLog],
    day: date,
    breaks: list[BreakSpec],
    now: datetime,
) -> DayWork:
    """Compute gross/break/net work for a single day.

    Args:
        worklogs: Raw work-clock worklog intervals (any dates; filtered here).
        day: The calendar date to compute.
        breaks: Configured breaks. A break only auto-deducts a nominal
            duration when it opted in with ``auto_deduct=True``; otherwise it
            contributes a zero deduction (real recorded gaps already excluded
            from gross stand in for the break).
        now: Reference time for open intervals.

    Returns:
        A :class:`DayWork` with gross, recorded break gaps, per-break
        (opt-in) deductions, and net derived.
    """
    intervals = _day_intervals(worklogs, day, now)
    gross = sum(int((hi - lo).total_seconds()) for lo, hi in intervals)
    result = DayWork(day=day, gross_seconds=gross)
    if not intervals:
        return result

    # Real recorded breaks are the clock-out gaps during the working day.
    # They are already excluded from gross, so they are shown, not deducted.
    result.recorded_breaks = _recorded_gaps(intervals)

    tz = intervals[0][0].tzinfo
    for spec in breaks:
        # Default behavior: a break deducts nothing - the real recorded gap
        # (already out of gross) is the break. Only an opt-in auto_deduct
        # break restores the old nominal-duration deduction, for users who
        # work straight through without clocking out.
        if not spec.auto_deduct:
            continue
        window_start, _nominal, window_end = _window_bounds(spec, day, tz)
        duration_sec = spec.duration_minutes * 60
        gap_sec = _gap_in_window(intervals, window_start, window_end)
        # Only auto-deduct the portion of the break NOT already taken as a
        # real clock-out gap: max(0, duration - gap_already_taken).
        deducted = max(0, duration_sec - gap_sec)
        result.break_deductions.append(
            BreakDeduction(
                name=spec.name,
                deducted_seconds=deducted,
                gap_seconds=gap_sec,
            )
        )
    return result


@dataclass
class WorkPeriod:
    """Aggregated work-clock figures over a set of days.

    Attributes:
        gross_seconds: Sum of gross clocked seconds across the period.
        break_seconds: Sum of opt-in auto-deducted break seconds across the
            period (``0`` unless some break set ``auto_deduct=True``).
        recorded_break_seconds: Sum of real recorded clock-out break seconds
            across the period (already excluded from gross; shown, not
            deducted).
        days: The per-day breakdown.
    """

    gross_seconds: int = 0
    break_seconds: int = 0
    recorded_break_seconds: int = 0
    days: list[DayWork] = field(default_factory=list)

    @property
    def net_seconds(self) -> int:
        """Net work seconds across the period."""
        return max(0, self.gross_seconds - self.break_seconds)


def days_in_range(start: date, end: date) -> list[date]:
    """Return the inclusive list of dates from ``start`` to ``end``.

    Args:
        start: First date (inclusive).
        end: Last date (inclusive).

    Returns:
        A list of :class:`datetime.date` from start to end.
    """
    if end < start:
        return []
    span = (end - start).days
    return [start + timedelta(days=i) for i in range(span + 1)]


def compute_period(
    worklogs: list[WorkLog],
    start: date,
    end: date,
    breaks: list[BreakSpec],
    now: datetime,
) -> WorkPeriod:
    """Aggregate work-clock figures over an inclusive date range.

    Args:
        worklogs: Raw work-clock worklog intervals.
        start: First date (inclusive).
        end: Last date (inclusive).
        breaks: Configured breaks to auto-deduct per day.
        now: Reference time for open intervals.

    Returns:
        A :class:`WorkPeriod` aggregate. Days with no clocked time are
        omitted from ``days`` so the breakdown stays compact.
    """
    period = WorkPeriod()
    for day in days_in_range(start, end):
        day_work = compute_day(worklogs, day, breaks, now)
        if day_work.gross_seconds == 0:
            continue
        period.days.append(day_work)
        period.gross_seconds += day_work.gross_seconds
        period.break_seconds += day_work.total_break_seconds
        period.recorded_break_seconds += day_work.recorded_break_seconds
    return period


# --- Task-session aggregation (reported separately from the work clock) ---


@dataclass
class TaskHours:
    """Elapsed session time for one task within a period.

    Attributes:
        repo: Repository name the task belongs to.
        task_id: Local task identifier.
        title: Task title (for display).
        seconds: Elapsed session seconds within the period.
    """

    repo: str
    task_id: str
    title: str
    seconds: int


@dataclass
class TaskBreakdown:
    """Per-task and per-repo session totals for a period.

    Attributes:
        tasks: Per-task elapsed seconds (sorted descending by seconds).
        per_repo: Mapping of repo name -> total elapsed seconds.
    """

    tasks: list[TaskHours] = field(default_factory=list)
    per_repo: dict[str, int] = field(default_factory=dict)

    @property
    def total_seconds(self) -> int:
        """Total task session seconds across all tasks."""
        return sum(t.seconds for t in self.tasks)


def task_seconds_in_range(
    worklogs: list[WorkLog],
    start: date,
    end: date,
    now: datetime,
) -> int:
    """Elapsed session seconds for one task clipped to a date range.

    Open sessions are closed at ``now``. Each interval is clipped to each
    overlapping day so time is attributed only within ``[start, end]``.

    Args:
        worklogs: The task's worklog intervals.
        start: First date (inclusive).
        end: Last date (inclusive).
        now: Reference time for open sessions.

    Returns:
        Elapsed seconds within the range.
    """
    total = 0
    for day in days_in_range(start, end):
        for lo, hi in _day_intervals(worklogs, day, now):
            total += int((hi - lo).total_seconds())
    return total


def compute_task_breakdown(
    tasks: list[tuple[str, str, str, list[WorkLog]]],
    start: date,
    end: date,
    now: datetime,
) -> TaskBreakdown:
    """Aggregate per-task session time across repos for a period.

    Args:
        tasks: Iterable of ``(repo, task_id, title, worklogs)`` tuples drawn
            from every registered repository.
        start: First date (inclusive).
        end: Last date (inclusive).
        now: Reference time for open sessions.

    Returns:
        A :class:`TaskBreakdown` with per-task entries (only tasks with
        nonzero time in the period) and per-repo totals.
    """
    breakdown = TaskBreakdown()
    for repo, task_id, title, worklogs in tasks:
        seconds = task_seconds_in_range(worklogs, start, end, now)
        if seconds <= 0:
            continue
        breakdown.tasks.append(TaskHours(repo=repo, task_id=task_id, title=title, seconds=seconds))
        breakdown.per_repo[repo] = breakdown.per_repo.get(repo, 0) + seconds
    breakdown.tasks.sort(key=lambda t: t.seconds, reverse=True)
    return breakdown


# --- Period range helpers (day/week/month/year/all) -----------------------


def day_range(anchor: date) -> tuple[date, date]:
    """Return the single-day range for ``anchor``."""
    return anchor, anchor


def week_range(anchor: date) -> tuple[date, date]:
    """Return the ISO week (Mon-Sun) range containing ``anchor``."""
    start = anchor - timedelta(days=anchor.weekday())
    return start, start + timedelta(days=6)


def month_range(anchor: date) -> tuple[date, date]:
    """Return the calendar-month range containing ``anchor``."""
    start = anchor.replace(day=1)
    if start.month == 12:
        next_month = start.replace(year=start.year + 1, month=1)
    else:
        next_month = start.replace(month=start.month + 1)
    return start, next_month - timedelta(days=1)


def year_range(anchor_year: int) -> tuple[date, date]:
    """Return the calendar-year range for ``anchor_year``."""
    return date(anchor_year, 1, 1), date(anchor_year, 12, 31)


# --- Daily worked-tasks timesheet (CSV export) ----------------------------
#
# These are the pure building blocks behind the ``doto timesheet`` command:
# a reusable midpoint rounding helper, a row model, row collection from the
# work clock + per-task worklogs, and a CSV serializer. Keeping them here
# (pure, no I/O) means the CLI command stays a thin shell and a child theme
# can subclass/replace individual pieces (e.g. override ``round_to_quarter_hour``
# or ``timesheet_rows``) without touching click wiring.

QUARTER_HOUR_MINUTES = 15
"""The rounding granularity (minutes) for timesheet start/end times."""

QUARTER_HOUR_MIDPOINT_SECONDS = QUARTER_HOUR_MINUTES * 60 / 2
"""Half of the quarter-hour window in seconds (the midpoint rounding pivot)."""

#: Leading characters that trigger spreadsheet formula evaluation (Excel,
#: Google Sheets, LibreOffice). A free-text cell starting with any of these is
#: prefixed with an apostrophe so it is treated as literal text rather than a
#: formula when the CSV is opened in a spreadsheet.
_CSV_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def _sanitize_csv_cell(value: str) -> str:
    """Neutralize spreadsheet formula injection in a free-text CSV cell.

    A spreadsheet (Excel/Sheets/LibreOffice) auto-evaluates any cell whose text
    begins with ``=``, ``+``, ``-``, ``@`` or a leading tab/carriage return, so
    a task titled ``=1+1`` (or ``=HYPERLINK(...)``) would execute on open. This
    helper prefixes a single apostrophe to such a cell so the value is rendered
    as literal text; cells that do not start with a trigger are returned
    unchanged. The empty string is returned unchanged.

    Only free-text columns (``title``, ``task_id``) are routed through this
    helper; machine-formatted columns (dates, times, ``HH:MM`` durations,
    ``kind``) are already constrained and never need sanitizing.

    Args:
        value: The raw cell text.

    Returns:
        ``value`` with a leading apostrophe prepended when it starts with a
        formula trigger, otherwise ``value`` unchanged.
    """
    if value and value[0] in _CSV_FORMULA_TRIGGERS:
        return "'" + value
    return value


def round_to_quarter_hour(moment: datetime) -> datetime:
    """Round a datetime to the nearest 15-minute boundary (midpoint rule).

    The minute-of-the-quarter offset is measured in seconds from the quarter
    boundary. An offset **below** the 7.5-minute midpoint rounds *down* to the
    boundary; an offset **at or above** 7.5 minutes rounds *up* to the next
    boundary. Seconds and microseconds are included in the offset so, e.g.,
    ``:07:30`` rounds up while ``:07:29`` rounds down.

    Examples (minute component):
        * ``:07`` -> ``:00`` (offset 7m < 7.5m, rounds down)
        * ``:08`` -> ``:15`` (offset 8m >= 7.5m, rounds up)
        * ``:43`` -> ``:45`` (offset within the :30-:45 window >= 7.5m)
        * ``:45`` -> ``:45`` (exact boundary, unchanged)

    This is a pure helper so it is reusable and child-overridable: a child
    theme that wants a different granularity or tie-breaking rule can replace
    it (or wrap it) without touching the row/CSV logic.

    Args:
        moment: The datetime to round (any timezone / naive).

    Returns:
        A new datetime rounded to the nearest quarter hour, preserving the
        original ``tzinfo``. Seconds and microseconds are zeroed.
    """
    floor = moment.replace(
        minute=(moment.minute // QUARTER_HOUR_MINUTES) * QUARTER_HOUR_MINUTES,
        second=0,
        microsecond=0,
    )
    offset_seconds = (moment - floor).total_seconds()
    if offset_seconds >= QUARTER_HOUR_MIDPOINT_SECONDS:
        return floor + timedelta(minutes=QUARTER_HOUR_MINUTES)
    return floor


@dataclass
class TimesheetRow:
    """One rounded worked interval for the daily timesheet.

    Each row is a single worked interval - either a global work-clock interval
    (``kind == "work"``) or a task focus-session interval (``kind == "task"``)
    - clipped to the target day and with its ``start``/``stop`` rounded to the
    nearest quarter hour via :func:`round_to_quarter_hour`.

    Attributes:
        day: The calendar date the interval falls on.
        start: Rounded interval start (timezone-aware).
        stop: Rounded interval stop (timezone-aware).
        kind: ``"work"`` for the global clock, ``"task"`` for a task session.
        task_id: The task identifier (empty for ``"work"`` rows).
        title: The task title (empty for ``"work"`` rows).
    """

    day: date
    start: datetime
    stop: datetime
    kind: str
    task_id: str = ""
    title: str = ""

    @property
    def rounded_duration_seconds(self) -> int:
        """Rounded interval length in whole seconds (never negative)."""
        return max(0, int((self.stop - self.start).total_seconds()))


def _rounded_rows_for_intervals(
    intervals: list[tuple[datetime, datetime]],
    day: date,
    kind: str,
    task_id: str,
    title: str,
) -> list[TimesheetRow]:
    """Build rounded :class:`TimesheetRow` objects for clipped intervals.

    Args:
        intervals: Sorted, clipped ``(start, stop)`` intervals on ``day``.
        day: The calendar date.
        kind: Row kind (``"work"`` or ``"task"``).
        task_id: Task identifier (empty for work rows).
        title: Task title (empty for work rows).

    Returns:
        One row per interval, with start/stop rounded to the quarter hour.
    """
    rows: list[TimesheetRow] = []
    for lo, hi in intervals:
        rows.append(
            TimesheetRow(
                day=day,
                start=round_to_quarter_hour(lo),
                stop=round_to_quarter_hour(hi),
                kind=kind,
                task_id=task_id,
                title=title,
            )
        )
    return rows


def timesheet_rows(
    work_worklogs: list[WorkLog],
    tasks: list[tuple[str, str, str, list[WorkLog]]],
    day: date,
    now: datetime,
) -> list[TimesheetRow]:
    """Collect all rounded worked intervals for a single day.

    Produces one :class:`TimesheetRow` per worked interval: every global
    work-clock interval on ``day`` (``kind == "work"``) followed by every
    per-task focus-session interval on ``day`` (``kind == "task"``). Intervals
    are clipped to the day (overnight sessions attribute correctly) and each
    endpoint is rounded to the nearest quarter hour.

    Rows are ordered by start time, with ``"work"`` rows kept before ``"task"``
    rows that share an identical rounded start so the global clock reads first.

    Args:
        work_worklogs: The global work-clock intervals (``WorkClock.worklogs``).
        tasks: ``(repo, task_id, title, worklogs)`` tuples across repos, as
            returned by
            :func:`doxtr_doto.cli.task_collector.collect_repo_tasks`.
        day: The calendar date to export.
        now: Reference time for open intervals.

    Returns:
        The day's worked-interval rows, sorted by (start, kind-order).
    """
    rows: list[TimesheetRow] = _rounded_rows_for_intervals(
        _day_intervals(work_worklogs, day, now), day, "work", "", ""
    )
    for _repo, task_id, title, worklogs in tasks:
        rows.extend(
            _rounded_rows_for_intervals(
                _day_intervals(worklogs, day, now), day, "task", task_id, title
            )
        )
    # Stable sort by start; "work" sorts before "task" on a tie so the global
    # clock interval always reads above a task interval that rounds identically.
    rows.sort(key=lambda r: (r.start, 0 if r.kind == "work" else 1))
    return rows


def work_span_seconds(
    work_worklogs: list[WorkLog],
    day: date,
    now: datetime,
) -> int:
    """Exact, unrounded work-clock span for a day in whole seconds.

    The span is measured from the **earliest** work-clock start to the
    **latest** work-clock stop on ``day`` (the full bracket of the day's
    global "work" task), *including* any mid-day clock-out gaps. This is the
    figure the timesheet's final ``total`` row reports - it is the work-clock
    span, deliberately **not** the sum of individual task or interval times.

    Open intervals are closed at ``now`` and intervals are clipped to the day.

    Args:
        work_worklogs: The global work-clock intervals.
        day: The calendar date.
        now: Reference time for open intervals.

    Returns:
        Seconds from the earliest start to the latest stop on the day, or
        ``0`` when there is no work-clock time that day.
    """
    intervals = _day_intervals(work_worklogs, day, now)
    if not intervals:
        return 0
    earliest = min(lo for lo, _hi in intervals)
    latest = max(hi for _lo, hi in intervals)
    return max(0, int((latest - earliest).total_seconds()))


def format_hhmm(total_seconds: int) -> str:
    """Format whole seconds as a zero-padded ``HH:MM`` duration string.

    Used for the timesheet total row and the per-row rounded ``duration``
    column. Minutes are truncated (floored); negative inputs clamp to zero.
    Hours are not capped, so a span over 24h still renders (e.g. ``26:30``).

    Args:
        total_seconds: Duration in whole seconds.

    Returns:
        A ``HH:MM`` string, e.g. ``"05:45"`` or ``"00:00"``.
    """
    seconds = max(0, int(total_seconds))
    hours, rem = divmod(seconds, 3600)
    minutes = rem // 60
    return f"{hours:02d}:{minutes:02d}"


#: Per-column renderer for a data row. Each callable takes a
#: :class:`TimesheetRow` and returns the cell string. This registry is the
#: single source of truth for which columns exist and how each renders, so
#: :data:`DEFAULT_TIMESHEET_COLUMNS`/:data:`TIMESHEET_COLUMNS` are derived from
#: its keys and adding a column is one entry (no silent-blank ``if``-ladder).
#: Free-text columns (``title``, ``task_id``) are routed through
#: :func:`_sanitize_csv_cell` to neutralize spreadsheet formula injection.
TIMESHEET_ROW_RENDERERS: dict[str, Callable[[TimesheetRow], str]] = {
    "date": lambda row: row.day.isoformat(),
    "start_time": lambda row: row.start.strftime("%H:%M"),
    "end_time": lambda row: row.stop.strftime("%H:%M"),
    "task_id": lambda row: _sanitize_csv_cell(row.task_id),
    "title": lambda row: _sanitize_csv_cell(row.title),
    "kind": lambda row: row.kind,
    "duration": lambda row: format_hhmm(row.rounded_duration_seconds),
}

#: Per-column renderer for the final ``total`` row. Each callable takes the
#: day and the exact unrounded work-clock span (seconds) and returns the cell
#: string. Columns absent here render empty on the total row. Keyed by the
#: same column names as :data:`TIMESHEET_ROW_RENDERERS`.
TIMESHEET_TOTAL_RENDERERS: dict[str, Callable[[date, int], str]] = {
    "date": lambda day, _span: day.isoformat(),
    "start_time": lambda _day, _span: "",
    "end_time": lambda _day, span: format_hhmm(span),
    "task_id": lambda _day, _span: "",
    "title": lambda _day, _span: "Total work-clock span",
    "kind": lambda _day, _span: "total",
    "duration": lambda _day, span: format_hhmm(span),
}

DEFAULT_TIMESHEET_COLUMNS = list(TIMESHEET_ROW_RENDERERS)
"""Default timesheet column order, derived from the row-renderer registry.

The minimum documented columns are ``date``, ``start_time`` and ``end_time``;
the remaining columns (``task_id``, ``title``, ``kind``, ``duration``) are the
useful extras surfaced by default. ``--columns`` can narrow or reorder this
set. See :data:`TIMESHEET_COLUMNS` for the full set of recognized names.
"""

TIMESHEET_COLUMNS = frozenset(TIMESHEET_ROW_RENDERERS)
"""The full set of recognized timesheet column names (for validation).

Derived from :data:`TIMESHEET_ROW_RENDERERS` so a column can never be declared
"valid" without a renderer behind it.
"""


def _row_cell(row: TimesheetRow, column: str) -> str:
    """Return the string cell value of ``row`` for ``column``.

    Dispatches through :data:`TIMESHEET_ROW_RENDERERS` so the recognized
    column set and its per-column rendering live in one registry (no parallel
    ``if``-ladder). An unrecognized column raises :class:`KeyError`; callers
    only pass validated columns (see :func:`timesheet_matrix`).

    Args:
        row: The timesheet row.
        column: A recognized column name from :data:`TIMESHEET_COLUMNS`.

    Returns:
        The cell's string value.
    """
    return TIMESHEET_ROW_RENDERERS[column](row)


def _total_cell(column: str, day: date, total_seconds: int) -> str:
    """Return the string cell value of the final ``total`` row for ``column``.

    The total row carries the day in ``date``, the literal ``total`` marker in
    ``kind``, the ``Total work-clock span`` label in ``title``, and the exact
    unrounded work-clock span (``HH:MM``) in ``duration``/``end_time`` so the
    headline figure survives any column subset that keeps a time column.
    Dispatches through :data:`TIMESHEET_TOTAL_RENDERERS` so the recognized
    column set stays in one registry.

    Args:
        column: A recognized column name.
        day: The calendar date.
        total_seconds: Exact unrounded work-clock span in seconds.

    Returns:
        The total row's cell value for the column.
    """
    return TIMESHEET_TOTAL_RENDERERS[column](day, total_seconds)


def timesheet_matrix(
    rows: list[TimesheetRow],
    total_seconds: int,
    day: date,
    columns: list[str] | None = None,
) -> list[list[str]]:
    """Build the full timesheet matrix (header + rows + total) as strings.

    This is the pure, I/O-free core shared by the CSV serializer and tests.
    The final row is the exact, **unrounded** work-clock span for the day
    (earliest start to latest stop) - never the sum of the per-row rounded
    durations.

    Args:
        rows: The day's rounded worked-interval rows (see
            :func:`timesheet_rows`).
        total_seconds: Exact unrounded work-clock span for the day (see
            :func:`work_span_seconds`).
        day: The calendar date (used for the total row's ``date`` cell).
        columns: Ordered column names to emit; defaults to
            :data:`DEFAULT_TIMESHEET_COLUMNS`.

    Returns:
        A list of string rows; the first is the header, the last is the
        ``total`` row. Only the header is returned when the day has no rows
        **and** no work-clock span (``total_seconds == 0``) - the empty-day
        case. When there are task-session rows but no global work-clock span,
        a ``total`` row showing a ``00:00`` span is still appended (the span is
        the work clock's, deliberately not the sum of task time).
    """
    cols = list(columns) if columns else list(DEFAULT_TIMESHEET_COLUMNS)
    matrix: list[list[str]] = [list(cols)]
    for row in rows:
        matrix.append([_row_cell(row, col) for col in cols])
    # Only append a total row when the day actually had work-clock time;
    # an empty day emits the header alone so downstream tools see a valid,
    # content-free CSV.
    if total_seconds > 0 or rows:
        matrix.append([_total_cell(col, day, total_seconds) for col in cols])
    return matrix


def timesheet_csv(
    rows: list[TimesheetRow],
    total_seconds: int,
    day: date,
    columns: list[str] | None = None,
) -> str:
    """Serialize a day's timesheet to CSV text (header + rows + total).

    Thin pure wrapper over :func:`timesheet_matrix` that renders the matrix
    with :mod:`csv` so quoting/escaping matches the rest of the project's CSV
    output. The returned text ends with a trailing newline.

    Args:
        rows: The day's rounded worked-interval rows.
        total_seconds: Exact unrounded work-clock span for the day.
        day: The calendar date.
        columns: Ordered column names; defaults to
            :data:`DEFAULT_TIMESHEET_COLUMNS`.

    Returns:
        CSV text with ``\\r\\n`` line terminators (the :mod:`csv` default).
    """
    import csv
    import io

    matrix = timesheet_matrix(rows, total_seconds, day, columns)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerows(matrix)
    return output.getvalue()
