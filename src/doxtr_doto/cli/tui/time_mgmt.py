"""Time-management modal screens for ``doto tui``.

Three screens, all reachable from the main app:

* :class:`BreaksConfigScreen` — configure the recurring breaks (name, time,
  duration, leeway, optional auto-deduct flag) **and** the "work week"
  weekday set backing the summary panel's work-week net total. Persisted into
  the global config file (``breaks`` + ``workweek_days``). Breaks are recorded
  clock-out gaps by default; a break only auto-deducts a nominal duration when
  its ``auto`` column is enabled.
* :class:`WorkTimeScreen` — edit the global work clock's individual intervals
  (start/stop timestamps), add a new interval, or delete one, for a chosen
  day. Mirrors the "edit a finished doto's session" idea: a saved interval is
  rewritten in place.
* :class:`WorkStatsScreen` — the day/week/month/year work-statistics pop-up
  (opened with ``S`` from the ``time`` layout): per-period net/gross/break
  numbers plus a text/ASCII block-character bar chart of the period's
  sub-totals.

All three screens keep their business logic in small, importable helper
functions (:func:`parse_breaks_text`, :func:`format_breaks_text`,
:func:`parse_workweek_text`, :func:`format_workweek_text`,
:func:`interval_duration_seconds`, :func:`apply_interval_edit`,
:func:`render_bar_chart`, :func:`build_week_day_distribution`,
:func:`anchor_range_for`, :func:`shift_anchor`) so the
parsing/mutation/aggregation can be unit-tested without rendering Textual.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, ListItem, ListView, Static, TextArea

from doxtr_doto.cli.global_state import (
    DEFAULT_BREAK_LEEWAY_MINUTES,
    DEFAULT_WORKWEEK_DAYS,
    BreakConfig,
)
from doxtr_doto.cli.session import format_duration
from doxtr_doto.constants import WEEKDAY_ABBR
from doxtr_doto.sync.json_store import WorkLog
from doxtr_doto.time_tracking import (
    add_interval,
    elapsed_seconds,
    parse_timestamp,
    remove_interval,
    set_interval,
)

if TYPE_CHECKING:
    from doxtr_doto.cli.main import DotoContext
    from doxtr_doto.work_report import TaskHours


# --- Pure helpers (unit-testable without Textual) -------------------------

#: Commented example/header shown at the top of the breaks editor. Every line
#: starts with ``#`` so :func:`parse_breaks_text` skips it; the user edits the
#: real break rows beneath it.
BREAKS_EXAMPLE_HEADER = (
    "# Configure recurring breaks, one per line:\n"
    "#   name,HH:MM,duration[,leeway[,auto]]\n"
    "# duration and leeway are in minutes; leeway defaults to "
    f"{DEFAULT_BREAK_LEEWAY_MINUTES}.\n"
    "# 'auto' (yes/no, default no) auto-deducts the duration only if you work\n"
    "# straight through without clocking out; by default a break is just the\n"
    "# real clock-out gap you record and nothing extra is deducted.\n"
    "# Lines starting with '#' and blank lines are ignored.\n"
    "# Example:\n"
    "#   Breakfast,08:00,20,15\n"
    "#   Lunch,12:00,60,30\n"
    "#   Dinner,18:30,45,30,yes\n"
)


def format_breaks_text(breaks: list[BreakConfig], include_header: bool = False) -> str:
    """Render breaks as an editable ``name,HH:MM,duration,leeway[,auto]`` block.

    One break per line. This is the text shown in the breaks editor so the
    user can edit all breaks at once. The optional trailing ``auto`` column
    (``yes``/``no``) is only emitted when the break opted into auto-deduction,
    keeping the common (recorded-break) rows compact.

    Args:
        breaks: The configured breaks.
        include_header: When True, prepend :data:`BREAKS_EXAMPLE_HEADER` (a
            commented usage example) above the real rows. The header is made
            entirely of ``#`` lines so a round-trip through
            :func:`parse_breaks_text` ignores it.

    Returns:
        A newline-separated block, one ``name,time,duration,leeway[,auto]`` per
        row, optionally preceded by the commented example header.
    """
    rows = "\n".join(
        f"{b.name},{b.time},{b.duration_minutes},{b.leeway_minutes}"
        + (",yes" if b.auto_deduct else "")
        for b in breaks
    )
    if include_header:
        return BREAKS_EXAMPLE_HEADER + ("\n" + rows if rows else "")
    return rows


def parse_breaks_text(text: str) -> list[BreakConfig]:
    """Parse the breaks editor text block into :class:`BreakConfig` list.

    Each non-empty line must be ``name,HH:MM,duration[,leeway[,auto]]``. The
    leeway column is optional and defaults to
    :data:`DEFAULT_BREAK_LEEWAY_MINUTES`. The optional ``auto`` column accepts
    ``yes``/``no``/``true``/``false``/``1``/``0`` (default ``no``) and controls
    whether the break auto-deducts its duration (legacy straight-through
    behavior) rather than being represented purely by the real recorded
    clock-out gap. Blank lines and *comment* lines (those whose first
    non-whitespace character is ``#``) are ignored, so the editor can ship a
    commented example block the user edits around.

    Args:
        text: The editor text block.

    Returns:
        Parsed breaks.

    Raises:
        ValueError: On a malformed line (surfaced to the user as an error).
    """
    breaks: list[BreakConfig] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            raise ValueError(
                f"Line {lineno}: expected 'name,HH:MM,duration[,leeway[,auto]]', got {raw!r}."
            )
        name, time_str, duration_str = parts[0], parts[1], parts[2]
        leeway_str = parts[3] if len(parts) >= 4 and parts[3] else str(DEFAULT_BREAK_LEEWAY_MINUTES)
        auto_str = parts[4] if len(parts) >= 5 else ""
        if not name:
            raise ValueError(f"Line {lineno}: break name must not be empty.")
        hhmm = time_str.split(":")
        if len(hhmm) != 2:
            raise ValueError(f"Line {lineno}: time {time_str!r} must be HH:MM.")
        try:
            hour, minute = int(hhmm[0]), int(hhmm[1])
            duration = int(duration_str)
            leeway = int(leeway_str)
        except ValueError as exc:
            raise ValueError(f"Line {lineno}: numeric field invalid ({exc}).") from exc
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError(f"Line {lineno}: time {time_str!r} out of range.")
        if duration < 0 or leeway < 0:
            raise ValueError(f"Line {lineno}: duration/leeway must be non-negative.")
        auto_deduct = _parse_auto_flag(auto_str, lineno)
        breaks.append(
            BreakConfig(
                name=name,
                time=f"{hour:02d}:{minute:02d}",
                duration_minutes=duration,
                leeway_minutes=leeway,
                auto_deduct=auto_deduct,
            )
        )
    return breaks


#: Tokens accepted for the breaks editor's optional ``auto`` column, mapped to
#: the resulting ``auto_deduct`` boolean. Matched case-insensitively.
_AUTO_TRUE_TOKENS = frozenset({"yes", "y", "true", "t", "1", "auto"})
_AUTO_FALSE_TOKENS = frozenset({"", "no", "n", "false", "f", "0"})


def _parse_auto_flag(token: str, lineno: int) -> bool:
    """Parse the optional ``auto`` column into a boolean.

    Args:
        token: The raw ``auto`` cell (may be empty when the column is omitted).
        lineno: The 1-based line number, for error messages.

    Returns:
        True when the break opts into auto-deduction, else False.

    Raises:
        ValueError: On an unrecognized token.
    """
    value = token.strip().lower()
    if value in _AUTO_TRUE_TOKENS:
        return True
    if value in _AUTO_FALSE_TOKENS:
        return False
    raise ValueError(f"Line {lineno}: auto flag {token!r} must be yes/no.")


def interval_duration_seconds(started_at: str, stopped_at: str | None) -> int | None:
    """Return the whole-second duration of a work interval, or None.

    Pure (no Textual, no I/O) so the live-duration field in
    :class:`WorkIntervalEditScreen` can be unit-tested directly. Reuses
    :func:`doxtr_doto.time_tracking.parse_timestamp` so it accepts the same
    ISO 8601 strings the editor's inputs hold.

    Args:
        started_at: The interval's start timestamp (ISO 8601). May be blank.
        stopped_at: The interval's stop timestamp (ISO 8601), or None/blank
            for a still-running (open) interval.

    Returns:
        The duration ``stop - start`` in whole seconds, or ``None`` when it
        cannot be computed: a blank/missing stop (running interval), an
        unparseable start or stop timestamp, or a stop that is not strictly
        after the start.
    """
    if not started_at or not started_at.strip():
        return None
    if not stopped_at or not stopped_at.strip():
        return None
    try:
        start_dt = parse_timestamp(started_at.strip())
        stop_dt = parse_timestamp(stopped_at.strip())
    except (ValueError, TypeError):
        return None
    if stop_dt <= start_dt:
        return None
    return int((stop_dt - start_dt).total_seconds())


#: Monday-first weekday abbreviations lowercased for matching, derived from the
#: canonical :data:`doxtr_doto.constants.WEEKDAY_ABBR` tuple so the ordering
#: cannot drift from the title-case display labels in
#: :mod:`doxtr_doto.cli.tui.widgets` (both share one source of truth). Indexed
#: by Python's :meth:`datetime.date.weekday` convention (Monday=0 .. Sunday=6).
_WORKWEEK_ABBR = tuple(abbr.lower() for abbr in WEEKDAY_ABBR)


def format_workweek_text(workweek_days: list[int]) -> str:
    """Render a workweek-day set as the editable comma-separated input value.

    Produces the compact numeric form (e.g. ``"0,1,2,3,4"``) shown in the
    workweek field of :class:`BreaksConfigScreen`. Weekday numbers use
    Python's Monday=0 .. Sunday=6 convention and are sorted/de-duplicated.

    Args:
        workweek_days: Weekday numbers (any order).

    Returns:
        A comma-separated string of the sorted, de-duplicated weekday numbers.
    """
    return ",".join(str(d) for d in sorted({d for d in workweek_days if 0 <= d <= 6}))


def parse_workweek_text(text: str) -> list[int]:
    """Parse the workweek editor input into a sorted weekday-number list.

    Accepts either numeric weekday tokens (``"0,1,2,3,4"`` with Monday=0 ..
    Sunday=6) or three-letter weekday abbreviations (``"Mon-Fri"``,
    ``"mon,tue,wed"``). Both ``,`` and ``-`` act as separators, and a numeric
    ``a-b`` or abbreviation ``Mon-Fri`` form is expanded to the inclusive
    range between its endpoints. Whitespace and empty tokens are ignored.
    The result is de-duplicated and sorted ascending.

    Args:
        text: The raw workweek field value.

    Returns:
        A sorted, de-duplicated list of weekday numbers in ``0..6``.

    Raises:
        ValueError: If the field is empty/blank or contains an unrecognized
            or out-of-range token, so the modal can surface an inline error
            without closing.
    """
    raw = text.strip()
    if not raw:
        raise ValueError("Work week must list at least one day.")

    def _token_to_day(tok: str) -> int:
        tok = tok.strip().lower()
        if not tok:
            raise ValueError("Empty weekday token in work week.")
        if tok.isdigit():
            value = int(tok)
            if not 0 <= value <= 6:
                raise ValueError(f"Weekday {tok!r} out of range (expected 0-6, Mon=0).")
            return value
        if tok[:3] in _WORKWEEK_ABBR:
            return _WORKWEEK_ABBR.index(tok[:3])
        raise ValueError(f"Unrecognized weekday {tok!r}; use 0-6 (Mon=0) or Mon..Sun.")

    days: set[int] = set()
    # Split on commas first; each comma-part may itself be an ``a-b`` range.
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        # A range uses a ``-`` that is not the token's leading character (so a
        # bare numeric token is not mistaken for a range).
        dash = part.find("-", 1)
        if dash != -1:
            lo = _token_to_day(part[:dash])
            hi = _token_to_day(part[dash + 1 :])
            if hi < lo:
                lo, hi = hi, lo
            days.update(range(lo, hi + 1))
        else:
            days.add(_token_to_day(part))
    if not days:
        raise ValueError("Work week must list at least one day.")
    return sorted(days)


def apply_interval_edit(
    worklogs: list[WorkLog],
    index: int | None,
    started_at: str,
    stopped_at: str | None,
) -> list[WorkLog]:
    """Apply an add/edit of a single work-clock interval.

    Validates the timestamps and (when both ends are set) their ordering,
    then returns a new worklog list with the interval added (``index is
    None``) or replaced (existing ``index``).

    Args:
        worklogs: The current work-clock intervals.
        index: Index to replace, or None to append a new interval.
        started_at: ISO 8601 start timestamp.
        stopped_at: ISO 8601 stop timestamp, or None for an open interval.

    Returns:
        A new worklog list.

    Raises:
        ValueError: On an unparseable timestamp or stop-before-start.
    """
    start_dt = parse_timestamp(started_at)
    start_iso = start_dt.isoformat()
    stop_iso: str | None = None
    if stopped_at:
        stop_dt = parse_timestamp(stopped_at)
        if stop_dt <= start_dt:
            raise ValueError("Stop time must be after start time.")
        stop_iso = stop_dt.isoformat()
    if index is None:
        return add_interval(worklogs, start_iso, stop_iso)
    return set_interval(worklogs, index, start_iso, stop_iso)


def intervals_for_day(
    worklogs: list[WorkLog],
    day: date,
) -> list[tuple[int, WorkLog]]:
    """Return ``(global_index, interval)`` pairs whose start is on ``day``.

    The global index is preserved so edits/deletes target the right entry in
    the full worklog list.

    Args:
        worklogs: The full work-clock interval list.
        day: The calendar day to filter by (local start date).

    Returns:
        List of ``(index, interval)`` for intervals starting on ``day``.
    """
    rows: list[tuple[int, WorkLog]] = []
    for i, log in enumerate(worklogs):
        started_raw = log.get("started_at")
        if not started_raw:
            continue
        if parse_timestamp(str(started_raw)).date() == day:
            rows.append((i, log))
    return rows


#: The block character used to draw filled portions of a text bar chart.
BAR_CHAR = "\u2588"


def render_bar_chart(
    rows: list[tuple[str, int]],
    width: int = 20,
    value_formatter: Any = None,
) -> list[str]:
    """Render labelled numeric rows as text/ASCII block-character bar lines.

    Each output line is ``"<label>  <bars> <value>"``: the label is padded to
    the widest label so the bars align, the bar is drawn with the block
    character :data:`BAR_CHAR` (``█``) scaled against the largest value, and
    the formatted value is appended. This is a pure, Textual-free helper so it
    can be unit-tested directly and reused by any renderer; the
    :class:`WorkStatsScreen` joins the returned lines with newlines.

    A zero or negative maximum (every value is zero) yields empty bars, so an
    all-zero chart still renders its labels and ``0`` values without dividing
    by zero.

    Args:
        rows: ``(label, value)`` pairs, in display order. Values are treated as
            non-negative (negatives are clamped to zero for bar length).
        width: The number of characters the largest bar spans (>= 1).
        value_formatter: Optional ``int -> str`` callable to format each
            value column (e.g. :func:`doxtr_doto.cli.session.format_duration`).
            Defaults to ``str``.

    Returns:
        One rendered line per input row (an empty list for no rows).
    """
    if not rows:
        return []
    width = max(1, int(width))
    fmt = value_formatter if value_formatter is not None else str
    label_width = max(len(label) for label, _ in rows)
    max_value = max((max(0, value) for _, value in rows), default=0)
    lines: list[str] = []
    for label, value in rows:
        value = max(0, int(value))
        if max_value > 0:
            filled = round(width * value / max_value)
        else:
            filled = 0
        bar = BAR_CHAR * filled
        lines.append(f"{label.ljust(label_width)}  {bar.ljust(width)} {fmt(value)}")
    return lines


def build_week_day_distribution(
    worklogs: list[WorkLog],
    anchor: date,
    specs: list[Any],
    now: datetime,
) -> list[tuple[str, int]]:
    """Return per-weekday net work seconds for the week containing ``anchor``.

    This is the "day work length distribution per week" chart data: one row
    per weekday (Mon..Sun) whose value is that day's *net* work length (gross
    minus auto-deducted breaks), reusing
    :func:`doxtr_doto.work_report.compute_day` so the net figures match the
    CLI report. Pure (no Textual, no I/O) so it is directly unit-testable.

    Args:
        worklogs: The global work clock's worklog intervals.
        anchor: Any day inside the target week (the ISO Mon-Sun week is used).
        specs: Normalized :class:`doxtr_doto.work_report.BreakSpec` list.
        now: Reference "now" for open intervals.

    Returns:
        Seven ``(weekday_label, net_seconds)`` rows, Monday first.
    """
    from doxtr_doto.work_report import compute_day, week_range

    start, _end = week_range(anchor)
    labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    rows: list[tuple[str, int]] = []
    for offset, label in enumerate(labels):
        day = start + timedelta(days=offset)
        work = compute_day(worklogs, day, specs, now)
        rows.append((label, work.net_seconds))
    return rows


#: The granularities the statistics pop-up can switch between, in cycle order.
STATS_GRANULARITIES = ("day", "week", "month", "year")


def anchor_range_for(granularity: str, anchor: date) -> tuple[date, date]:
    """Return the inclusive ``(start, end)`` range for a granularity + anchor.

    Reuses the :mod:`doxtr_doto.work_report` range helpers so the stats
    pop-up's period math matches the rest of the app.

    Args:
        granularity: One of :data:`STATS_GRANULARITIES`.
        anchor: The anchor date the period is built around.

    Returns:
        The inclusive date range for the period.

    Raises:
        ValueError: On an unknown granularity.
    """
    from doxtr_doto.work_report import (
        day_range,
        month_range,
        week_range,
        year_range,
    )

    if granularity == "day":
        return day_range(anchor)
    if granularity == "week":
        return week_range(anchor)
    if granularity == "month":
        return month_range(anchor)
    if granularity == "year":
        return year_range(anchor.year)
    raise ValueError(f"Unknown granularity {granularity!r}.")


def shift_anchor(granularity: str, anchor: date, direction: int) -> date:
    """Return the anchor moved one period in ``direction`` for a granularity.

    Args:
        granularity: One of :data:`STATS_GRANULARITIES`.
        anchor: The current anchor date.
        direction: ``-1`` for the previous period, ``+1`` for the next.

    Returns:
        The new anchor date (normalized to the first day of the new period for
        week/month/year so repeated moves stay stable).

    Raises:
        ValueError: On an unknown granularity.
    """
    from doxtr_doto.work_report import month_range, week_range

    step = 1 if direction >= 0 else -1
    if granularity == "day":
        return anchor + timedelta(days=step)
    if granularity == "week":
        start, _end = week_range(anchor)
        return start + timedelta(days=7 * step)
    if granularity == "month":
        start, _end = month_range(anchor)
        if step > 0:
            if start.month == 12:
                return start.replace(year=start.year + 1, month=1)
            return start.replace(month=start.month + 1)
        if start.month == 1:
            return start.replace(year=start.year - 1, month=12)
        return start.replace(month=start.month - 1)
    if granularity == "year":
        return date(anchor.year + step, 1, 1)
    raise ValueError(f"Unknown granularity {granularity!r}.")


def task_breakdown_chart_rows(
    tasks: list[TaskHours],
    max_rows: int = 10,
) -> list[tuple[str, int]]:
    """Return the ``(label, seconds)`` bar-chart rows for a task breakdown.

    Turns the per-task entries of a
    :class:`doxtr_doto.work_report.TaskBreakdown` into labelled rows for the
    pure :func:`render_bar_chart`. Each label is the task's namespaced
    ``repo#id`` so a doto is identifiable in the chart; the rows are already
    sorted descending by seconds (``compute_task_breakdown`` sorts them) and
    are capped to ``max_rows`` so a very wide report still renders compactly.
    Pure (no Textual, no I/O) so it is directly unit-testable.

    Args:
        tasks: The :class:`doxtr_doto.work_report.TaskHours` entries from a
            breakdown (``breakdown.tasks``), in descending-seconds order.
        max_rows: The maximum number of rows to return (>= 1); extra tasks
            beyond this are omitted from the chart.

    Returns:
        ``(label, seconds)`` rows ready for :func:`render_bar_chart`, capped
        to ``max_rows`` (an empty list for no tasks).
    """
    from doxtr_doto.cli.session import namespaced_id

    limit = max(1, int(max_rows))
    rows: list[tuple[str, int]] = []
    for task in tasks[:limit]:
        rows.append((namespaced_id(task.repo, task.task_id), task.seconds))
    return rows


def task_repo_chart_rows(per_repo: dict[str, int]) -> list[tuple[str, int]]:
    """Return the ``(repo, seconds)`` bar-chart rows for a breakdown's repos.

    Turns a breakdown's ``per_repo`` mapping into labelled rows for
    :func:`render_bar_chart`, sorted descending by seconds. Pure (no Textual,
    no I/O) so it is directly unit-testable.

    Args:
        per_repo: The ``repo -> seconds`` mapping from a
            :class:`doxtr_doto.work_report.TaskBreakdown`.

    Returns:
        ``(repo, seconds)`` rows sorted descending by seconds (an empty list
        when the mapping is empty).
    """
    return sorted(per_repo.items(), key=lambda kv: kv[1], reverse=True)


def task_interval_display_rows(
    worklogs: list[WorkLog],
) -> list[tuple[int, str, str, int | None]]:
    """Return ``(index, start, stop, duration_seconds)`` rows for a task's log.

    Mirrors :func:`intervals_for_day` but for *all* of a single task's
    worklog intervals (the per-doto session list the
    :class:`TaskSessionsScreen` renders), not a single day of the global work
    clock. The global index into ``worklogs`` is preserved so edits/deletes
    target the right entry via :func:`apply_interval_edit` /
    :func:`doxtr_doto.time_tracking.remove_interval`. Pure (no Textual, no
    I/O) so it is directly unit-testable.

    Args:
        worklogs: The task's worklog intervals.

    Returns:
        One ``(index, started_at, stopped_at_or_blank, duration_seconds)``
        tuple per worklog, in list order. ``duration_seconds`` is ``None``
        for a running interval or an unparseable timestamp.
    """
    rows: list[tuple[int, str, str, int | None]] = []
    for index, log in enumerate(worklogs):
        start = str(log.get("started_at", ""))
        stop_raw = log.get("stopped_at")
        stop = str(stop_raw) if stop_raw else ""
        seconds = interval_duration_seconds(start, stop) if stop else None
        rows.append((index, start, stop, seconds))
    return rows


# --- Textual screens ------------------------------------------------------


class BreaksConfigScreen(ModalScreen["tuple[list[BreakConfig], list[int]] | None"]):
    """Modal to configure recurring breaks and the "work week" day set.

    Dismisses with a ``(breaks, workweek_days)`` tuple on save, or ``None`` on
    cancel. The breaks block is parsed by :func:`parse_breaks_text` and the
    work-week field by :func:`parse_workweek_text`; either parse error surfaces
    an inline error without closing the modal.

    ``workweek_days`` uses Python's Monday=0 .. Sunday=6 convention and backs
    the ``time`` layout summary panel's work-week net total (default
    Monday-Friday). The field accepts ``"Mon-Fri"`` or ``"0,1,2,3,4"``.
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+s", "save", "Save"),
    ]

    HELP = (
        "One break per line: [b]name,HH:MM,duration[,leeway[,auto]][/b]  —  "
        f"minutes; leeway defaults to {DEFAULT_BREAK_LEEWAY_MINUTES}. "
        "'auto' (yes/no, default no) auto-deducts the duration if you work "
        "straight through.  '#' lines are comments.  Work week: [b]Mon-Fri[/b] "
        "or [b]0,1,2,3,4[/b] (Mon=0..Sun=6).  [b]Ctrl+S[/b] save, [b]Esc[/b] cancel."
    )

    def __init__(
        self,
        breaks: list[BreakConfig],
        workweek_days: list[int] | None = None,
    ) -> None:
        """Initialize with the current breaks and work-week day set.

        Args:
            breaks: The breaks to pre-populate the editor with.
            workweek_days: The current work-week weekday set (Monday=0 ..
                Sunday=6). Defaults to
                :data:`doxtr_doto.cli.global_state.DEFAULT_WORKWEEK_DAYS`
                (Monday-Friday) when omitted.
        """
        super().__init__()
        self._breaks = breaks
        self._workweek_days = (
            list(workweek_days) if workweek_days is not None else list(DEFAULT_WORKWEEK_DAYS)
        )

    def compose(self) -> ComposeResult:
        """Build the breaks editor modal.

        The editor is a multi-line :class:`~textual.widgets.TextArea`
        pre-seeded with a commented example header (:data:`BREAKS_EXAMPLE_HEADER`)
        above the real break rows. Comment (``#``) and blank lines are skipped
        on save by :func:`parse_breaks_text`, so the example stays as guidance.
        A single-line work-week :class:`~textual.widgets.Input` configures the
        weekday set backing the summary panel's work-week net total.
        """
        with Vertical(id="breaks-modal"):
            yield Label("Configure breaks + work week", id="breaks-title")
            yield Static(self.HELP, id="breaks-help")
            yield TextArea(
                format_breaks_text(self._breaks, include_header=True),
                id="breaks-input",
            )
            yield Label("Work week (e.g. Mon-Fri or 0,1,2,3,4):", id="breaks-workweek-label")
            yield Input(
                value=format_workweek_text(self._workweek_days),
                id="breaks-workweek",
            )
            yield Label("", id="breaks-error")
            with Horizontal(id="breaks-bottom"):
                yield Button("Save", variant="primary", id="breaks-save")
                yield Button("Cancel", id="breaks-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle Save/Cancel."""
        if event.button.id == "breaks-cancel":
            self.dismiss(None)
            return
        self._save()

    def action_save(self) -> None:
        """Save via the Ctrl+S keybinding."""
        self._save()

    def _save(self) -> None:
        """Parse breaks + work week and dismiss, or show an inline error."""
        text = self.query_one("#breaks-input", TextArea).text
        workweek_raw = self.query_one("#breaks-workweek", Input).value
        try:
            breaks = parse_breaks_text(text)
            workweek_days = parse_workweek_text(workweek_raw)
        except ValueError as exc:
            self.query_one("#breaks-error", Label).update(f"[red]{exc}[/red]")
            return
        self.dismiss((breaks, workweek_days))

    def action_cancel(self) -> None:
        """Cancel without saving."""
        self.dismiss(None)


class WorkIntervalEditScreen(ModalScreen["tuple[int | None, str, str | None] | None"]):
    """Modal to add or edit a single work-clock interval.

    Dismisses with ``(index, started_at, stopped_at)`` on save (``index`` is
    None for a new interval), or ``None`` on cancel. Timestamp validation is
    delegated to :func:`apply_interval_edit` by the caller after dismissal, so
    this screen only gathers raw strings.
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        index: int | None,
        started_at: str,
        stopped_at: str | None,
    ) -> None:
        """Initialize the interval editor.

        Args:
            index: Interval index being edited, or None when adding.
            started_at: Pre-filled start timestamp (ISO 8601).
            stopped_at: Pre-filled stop timestamp (ISO 8601) or None.
        """
        super().__init__()
        self._index = index
        self._started = started_at
        self._stopped = stopped_at or ""

    def compose(self) -> ComposeResult:
        """Build the interval editor modal.

        Includes a read-only ``#interval-duration`` field that shows the
        current ``stop - start`` duration (via
        :func:`doxtr_doto.cli.session.format_duration`) and updates live as
        either input changes (see :meth:`on_input_changed`).
        """
        verb = "Add" if self._index is None else "Edit"
        with Vertical(id="interval-modal"):
            yield Label(f"{verb} work interval", id="interval-title")
            yield Label("Start (ISO 8601, e.g. 2026-06-01T09:00:00+00:00)")
            yield Input(value=self._started, id="interval-start")
            yield Label("Stop (blank = still running)")
            yield Input(value=self._stopped, id="interval-stop")
            yield Static(
                self._duration_markup(self._started, self._stopped),
                id="interval-duration",
            )
            yield Label("", id="interval-error")
            with Horizontal(id="interval-bottom"):
                yield Button("Save", variant="primary", id="interval-save")
                yield Button("Cancel", id="interval-cancel")

    @staticmethod
    def _duration_markup(started_at: str, stopped_at: str | None) -> str:
        """Return the Duration field markup for the given raw input values.

        A blank stop (running interval) shows a dim ``(running)`` marker; an
        unparseable timestamp or a stop at/<= the start shows a dim ``—``
        placeholder; otherwise the formatted duration (e.g. ``1h42m``) is
        shown. Never raises, so live keystroke updates cannot crash the modal.

        Args:
            started_at: The raw start-input value.
            stopped_at: The raw stop-input value (blank/None = running).

        Returns:
            Textual markup for the ``#interval-duration`` field.
        """
        if not stopped_at or not stopped_at.strip():
            return "Duration: [dim](running)[/dim]"
        seconds = interval_duration_seconds(started_at, stopped_at)
        if seconds is None:
            return "Duration: [dim]—[/dim]"
        return f"Duration: [b]{format_duration(seconds)}[/b]"

    def _refresh_duration(self) -> None:
        """Recompute and update the live ``#interval-duration`` field.

        Belt-and-suspenders: the field is only updated when it is actually
        mounted, so a future :meth:`compose` reordering (or an input change
        delivered before the duration Static exists) cannot raise
        :class:`~textual.css.query.NoMatches`. Behavior in the normal
        (mounted) case is identical.
        """
        try:
            duration = self.query_one("#interval-duration", Static)
        except NoMatches:
            return
        start = self.query_one("#interval-start", Input).value
        stop = self.query_one("#interval-stop", Input).value
        duration.update(self._duration_markup(start, stop))

    def on_input_changed(self, event: Input.Changed) -> None:
        """Recompute the live duration on every start/stop keystroke.

        Only the two interval inputs drive the duration field; any other
        input change is ignored. The computation is delegated to the pure
        :func:`interval_duration_seconds` helper so a transient invalid value
        shows a placeholder instead of crashing.
        """
        if event.input.id in ("interval-start", "interval-stop"):
            self._refresh_duration()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle Save/Cancel."""
        if event.button.id == "interval-cancel":
            self.dismiss(None)
            return
        start = self.query_one("#interval-start", Input).value.strip()
        stop = self.query_one("#interval-stop", Input).value.strip()
        if not start:
            self.query_one("#interval-error", Label).update("[red]Start is required.[/red]")
            return
        # Validate here so the error can be shown without closing.
        try:
            apply_interval_edit([], None, start, stop or None)
        except ValueError as exc:
            self.query_one("#interval-error", Label).update(f"[red]{exc}[/red]")
            return
        self.dismiss((self._index, start, stop or None))

    def action_cancel(self) -> None:
        """Cancel without saving."""
        self.dismiss(None)


class WorkTimeScreen(ModalScreen[None]):
    """Modal to manage the global work clock's intervals for a day.

    Lists each interval starting on the chosen day with its start/stop and
    offers add (``a``), edit (``e`` / Enter), and delete (``x``). The first
    interval is highlighted on open so the edit/delete actions always have a
    target, and the day's total work time (summed across the listed intervals)
    is shown beneath the list. All mutations are written back to the global
    config file immediately so the change is durable, mirroring editing a
    finished doto's session.
    """

    BINDINGS = [
        ("escape", "close", "Close"),
        ("a", "add", "Add"),
        ("e", "edit", "Edit"),
        ("enter", "edit", "Edit"),
        ("x", "delete", "Delete"),
        ("left", "prev_day", "Prev day"),
        ("right", "next_day", "Next day"),
        # Session navigation: arrow Up/Down and the vim-style j/k move the
        # highlighted row within the interval list so e/Enter/x act on the
        # row the user actually navigated to (including the 2nd+ intervals).
        ("up", "nav_up", "Prev session"),
        ("down", "nav_down", "Next session"),
        ("k", "nav_up", "Prev session"),
        ("j", "nav_down", "Next session"),
    ]

    def __init__(self, ctx: DotoContext, day: date | None = None) -> None:
        """Initialize the work-time manager.

        Args:
            ctx: The CLI context (for the global store).
            day: The day to manage (defaults to today).
        """
        super().__init__()
        self.ctx = ctx
        self.day = day or datetime.now().astimezone().date()

    def compose(self) -> ComposeResult:
        """Build the work-time manager modal."""
        with Vertical(id="worktime-modal"):
            yield Label("", id="worktime-title")
            with VerticalScroll(id="worktime-body"):
                yield ListView(id="worktime-list")
            yield Label("", id="worktime-total")
            yield Static(
                "[b]a[/b] add  [b]e/Enter[/b] edit  [b]x[/b] delete  "
                "[b]↑/↓[/b] (or [b]j/k[/b]) session  "
                "[b]←/→[/b] change day  [b]Esc[/b] close",
                id="worktime-hint",
            )

    def on_mount(self) -> None:
        """Populate the list on first display and focus it.

        The ``#worktime-list`` :class:`ListView` must hold focus for its
        Up/Down highlight to move; without that focus the highlight was stuck
        on row 0, so the user could neither navigate to nor edit the 2nd+
        interval (the ``e``/Enter action acted on row 0 only). Focusing the
        list on mount (and after every :meth:`_refresh`) fixes that.
        """
        self._refresh()

    def _refresh(self) -> None:
        """Reload intervals for the current day into the list.

        Preserves the highlighted row position where possible (so an edit does
        not snap the highlight back to the first row), clamping it to the new
        row count, and keeps the ``#worktime-list`` focused so Up/Down
        navigation keeps working after the refresh.
        """
        self.query_one("#worktime-title", Label).update(
            f"[b]Work time — {self.day.isoformat()}[/b]"
        )
        list_view = self.query_one("#worktime-list", ListView)
        previous_index = list_view.index
        list_view.clear()
        state = self.ctx.global_store.load()
        rows = intervals_for_day(state.work_clock.worklogs, self.day)
        total_seconds = elapsed_seconds([log for _, log in rows])
        self.query_one("#worktime-total", Label).update(
            f"[b]Total:[/b] {format_duration(total_seconds)}"
        )
        if not rows:
            list_view.append(ListItem(Label("(no intervals this day)")))
            return
        for idx, log in rows:
            start = str(log.get("started_at", ""))
            stop = log.get("stopped_at")
            stop_display = str(stop) if stop else "(running)"
            item = ListItem(Label(f"{start}  →  {stop_display}"))
            item.worklog_index = idx  # type: ignore[attr-defined]
            list_view.append(item)
        # Highlight a real interval so e/x/Enter act on a row immediately.
        # Without this the ListView starts with no highlighted child and the
        # edit/delete actions early-return (looks like "cannot edit"). The
        # previously-highlighted row index is preserved (clamped) across a
        # refresh so an edit does not snap the highlight back to row 0.
        if previous_index is None:
            list_view.index = 0
        else:
            list_view.index = max(0, min(previous_index, len(rows) - 1))
        # Re-focus the list so Up/Down keep moving the highlight after a
        # rebuild (e.g. after an edit/delete or a day change).
        list_view.focus()

    def _selected_index(self) -> int | None:
        """Return the global worklog index of the highlighted row, if any."""
        list_view = self.query_one("#worktime-list", ListView)
        item = list_view.highlighted_child
        if item is None:
            return None
        return getattr(item, "worklog_index", None)

    def action_nav_up(self) -> None:
        """Highlight the previous session row (Up / k)."""
        self.query_one("#worktime-list", ListView).action_cursor_up()

    def action_nav_down(self) -> None:
        """Highlight the next session row (Down / j)."""
        self.query_one("#worktime-list", ListView).action_cursor_down()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Open the editor when a row is activated with Enter.

        The focused :class:`ListView` consumes the ``enter`` key for its own
        ``select_cursor`` binding, so the screen-level ``enter`` binding never
        fires. Handling the resulting :class:`ListView.Selected` message is
        what actually wires Enter to the interval editor.
        """
        event.stop()
        self.action_edit()

    def action_add(self) -> None:
        """Open the interval editor to add a new interval for the day."""
        default_start = datetime.combine(
            self.day, time(9, 0), tzinfo=datetime.now().astimezone().tzinfo
        ).isoformat()
        self.app.push_screen(
            WorkIntervalEditScreen(None, default_start, None),
            self._apply_edit,
        )

    def action_edit(self) -> None:
        """Open the interval editor for the highlighted interval."""
        index = self._selected_index()
        if index is None:
            return
        state = self.ctx.global_store.load()
        log = state.work_clock.worklogs[index]
        self.app.push_screen(
            WorkIntervalEditScreen(index, str(log.get("started_at", "")), log.get("stopped_at")),
            self._apply_edit,
        )

    def action_delete(self) -> None:
        """Delete the highlighted interval."""
        index = self._selected_index()
        if index is None:
            return
        state = self.ctx.global_store.load()
        try:
            state.work_clock.worklogs = remove_interval(state.work_clock.worklogs, index)
        except IndexError:
            return
        self.ctx.global_store.save(state)
        self._refresh()

    def _apply_edit(
        self,
        result: tuple[int | None, str, str | None] | None,
    ) -> None:
        """Persist an add/edit returned by :class:`WorkIntervalEditScreen`."""
        if result is None:
            return
        index, start, stop = result
        state = self.ctx.global_store.load()
        try:
            state.work_clock.worklogs = apply_interval_edit(
                state.work_clock.worklogs, index, start, stop
            )
        except (ValueError, IndexError) as exc:
            self.app.notify(f"Could not save interval: {exc}", severity="error")
            return
        self.ctx.global_store.save(state)
        self._refresh()

    def action_prev_day(self) -> None:
        """Move to the previous day."""
        self.day = self.day - timedelta(days=1)
        self._refresh()

    def action_next_day(self) -> None:
        """Move to the next day."""
        self.day = self.day + timedelta(days=1)
        self._refresh()

    def action_close(self) -> None:
        """Close the manager."""
        self.dismiss(None)


class _GranularityStatsScreen(ModalScreen[None]):
    """Shared base for the day/week/month/year statistics pop-ups.

    Holds the surface that :class:`WorkStatsScreen` and
    :class:`TaskTimeStatsScreen` share verbatim — the granularity key
    bindings, the ``anchor``/``granularity`` state, the ``__init__``
    defaulting + granularity validation, the single :meth:`format_title`
    (parameterized by the :attr:`title_prefix` class attribute), and the
    anchor/granularity navigation actions (``←``/``→`` and ``d``/``w``/``m``/
    ``y``/``g``) plus ``Esc`` to close. Subclasses implement only their own
    :meth:`compose`, :meth:`_refresh`, and content ``format_*`` hooks.

    This is a pure refactor of the two previously-duplicated screens: no key
    binding, action, title format, or defaulting behavior changes.
    """

    #: Title prefix used by the shared :meth:`format_title` (e.g.
    #: ``"Work statistics"`` or ``"Task time"``). Subclasses override it.
    title_prefix: str = "Statistics"

    BINDINGS = [
        ("escape", "close", "Close"),
        ("left", "prev_period", "Prev period"),
        ("right", "next_period", "Next period"),
        ("d", "set_day", "Day"),
        ("w", "set_week", "Week"),
        ("m", "set_month", "Month"),
        ("y", "set_year", "Year"),
        ("g", "cycle_granularity", "Cycle granularity"),
    ]

    # Instance attribute holding the anchor period's date. Annotated at class
    # scope to override textual's inherited ``Widget.anchor()`` method type so
    # mypy treats ``self.anchor`` as a date rather than a bound method.
    anchor: date  # type: ignore[assignment]
    granularity: str

    def __init__(
        self,
        ctx: DotoContext,
        anchor: date | None = None,
        granularity: str = "week",
    ) -> None:
        """Initialize the statistics pop-up.

        Args:
            ctx: The CLI context (for the global store / collectors).
            anchor: The anchor date the period is built around (defaults to
                local today).
            granularity: The initial granularity, one of
                :data:`STATS_GRANULARITIES` (defaults to ``"week"``).
        """
        super().__init__()
        self.ctx = ctx
        self.anchor = anchor or datetime.now().astimezone().date()
        if granularity not in STATS_GRANULARITIES:
            granularity = "week"
        self.granularity = granularity

    def on_mount(self) -> None:
        """Render the initial statistics."""
        self._refresh()

    def _refresh(self) -> None:
        """Recompute and re-render the statistics for the current state.

        Overridden by each subclass to compute and render its own content;
        the base keeps the surface (bindings / navigation) shared.
        """
        raise NotImplementedError

    @classmethod
    def format_title(cls, granularity: str, start: date, end: date) -> str:
        """Return the modal title markup for a granularity and range.

        The title prefix comes from the :attr:`title_prefix` class attribute
        so the two statistics screens share one implementation while keeping
        their distinct labels.

        Args:
            granularity: The active granularity.
            start: The period's first day.
            end: The period's last day.

        Returns:
            Textual markup for the title line.

        Raises:
            ValueError: On an unknown granularity, so a future
                :data:`STATS_GRANULARITIES` addition fails fast instead of
                silently mis-rendering.
        """
        if granularity == "day":
            label = start.strftime("%a %Y-%m-%d")
        elif granularity == "week":
            label = f"week of {start.isoformat()} – {end.isoformat()}"
        elif granularity == "month":
            label = start.strftime("%B %Y")
        elif granularity == "year":
            label = str(start.year)
        else:
            raise ValueError(f"Unknown granularity {granularity!r}.")
        return f"[b]{cls.title_prefix} — {granularity}: {label}[/b]"

    def action_prev_period(self) -> None:
        """Move the anchor to the previous period."""
        self.anchor = shift_anchor(self.granularity, self.anchor, -1)
        self._refresh()

    def action_next_period(self) -> None:
        """Move the anchor to the next period."""
        self.anchor = shift_anchor(self.granularity, self.anchor, 1)
        self._refresh()

    def _set_granularity(self, granularity: str) -> None:
        """Switch the active granularity and re-render."""
        self.granularity = granularity
        self._refresh()

    def action_set_day(self) -> None:
        """Switch to the day granularity."""
        self._set_granularity("day")

    def action_set_week(self) -> None:
        """Switch to the week granularity."""
        self._set_granularity("week")

    def action_set_month(self) -> None:
        """Switch to the month granularity."""
        self._set_granularity("month")

    def action_set_year(self) -> None:
        """Switch to the year granularity."""
        self._set_granularity("year")

    def action_cycle_granularity(self) -> None:
        """Cycle to the next granularity in :data:`STATS_GRANULARITIES`."""
        index = STATS_GRANULARITIES.index(self.granularity)
        self._set_granularity(STATS_GRANULARITIES[(index + 1) % len(STATS_GRANULARITIES)])

    def action_close(self) -> None:
        """Close the statistics pop-up."""
        self.dismiss(None)


class WorkStatsScreen(_GranularityStatsScreen):
    """Modal showing work-clock statistics as numbers and text bar charts.

    Opened from the ``time`` TUI layout (the ``S`` key). Shows, for a chosen
    *granularity* (day / week / month / year) and anchor period:

    * the period's **net** total (and gross / break) work time as numbers, and
    * a text/ASCII block-character bar chart (NOT the SVG
      :mod:`doxtr_doto.charts`): for the ``week`` granularity the chart is the
      "day work length distribution per week" (a bar per weekday Mon..Sun
      showing that day's net length); for the other granularities the chart
      shows the net totals of each sub-period in the current period (days of
      the week, days of the month, months of the year, with ``day`` showing
      the single day).

    Keys:

    * ``d`` / ``w`` / ``m`` / ``y`` jump to that granularity, and ``g`` cycles
      through them in order,
    * ``←`` / ``→`` move the anchor to the previous / next period,
    * ``Esc`` closes.

    All period math reuses :mod:`doxtr_doto.work_report`
    (:func:`~doxtr_doto.work_report.compute_period` /
    :func:`~doxtr_doto.work_report.compute_day`) so the figures agree with the
    CLI report; the bars are drawn by the pure :func:`render_bar_chart`. The
    numeric/bar rendering is delegated to the overridable
    :meth:`format_stats` classmethod so a child theme can replace it by
    subclassing and swapping
    :attr:`doxtr_doto.cli.tui.app.DotoApp.work_stats_screen_class`.

    All of the shared granularity surface (key bindings, anchor/granularity
    state, ``__init__`` defaulting, :meth:`format_title`, and the
    anchor/granularity navigation actions) is inherited unchanged from
    :class:`_GranularityStatsScreen`.
    """

    #: Title prefix used by the shared
    #: :meth:`_GranularityStatsScreen.format_title`.
    title_prefix = "Work statistics"

    def compose(self) -> ComposeResult:
        """Build the statistics modal."""
        with Vertical(id="workstats-modal"):
            yield Label("", id="workstats-title")
            with VerticalScroll(id="workstats-body"):
                yield Static("", id="workstats-content")
            yield Static(
                "[b]d/w/m/y[/b] granularity  [b]g[/b] cycle  "
                "[b]←/→[/b] prev/next period  [b]Esc[/b] close",
                id="workstats-hint",
            )

    def _specs(self) -> list[Any]:
        """Return the normalized break specs from the configured breaks."""
        from doxtr_doto.work_report import BreakSpec

        state = self.ctx.global_store.load()
        specs: list[Any] = []
        for cfg in state.breaks:
            try:
                specs.append(BreakSpec.from_config(cfg))
            except (ValueError, TypeError):
                continue
        return specs

    def _refresh(self) -> None:
        """Recompute and re-render the statistics for the current state."""
        from doxtr_doto.work_report import compute_period

        state = self.ctx.global_store.load()
        worklogs = state.work_clock.worklogs
        specs = self._specs()
        now = datetime.now().astimezone()
        start, end = anchor_range_for(self.granularity, self.anchor)
        period = compute_period(worklogs, start, end, specs, now)
        chart_rows = self._chart_rows(worklogs, specs, now, start, end)
        self.query_one("#workstats-title", Label).update(
            self.format_title(self.granularity, start, end)
        )
        self.query_one("#workstats-content", Static).update(
            self.format_stats(
                self.granularity,
                period.gross_seconds,
                period.recorded_break_seconds,
                period.net_seconds,
                chart_rows,
            )
        )

    def _chart_rows(
        self,
        worklogs: list[WorkLog],
        specs: list[Any],
        now: datetime,
        start: date,
        end: date,
    ) -> list[tuple[str, int]]:
        """Return the ``(label, net_seconds)`` rows for the current chart.

        For the ``week`` granularity this is the per-weekday net distribution
        (the brief's "day work length distribution per week"); for ``day`` it
        is the single day; for ``month``/``year`` it is each day/month in the
        period.

        Raises:
            ValueError: On an unknown granularity, so a future
                :data:`STATS_GRANULARITIES` addition fails fast instead of
                silently mis-rendering.
        """
        from doxtr_doto.work_report import compute_period, days_in_range, month_range

        if self.granularity == "week":
            return build_week_day_distribution(worklogs, self.anchor, specs, now)
        if self.granularity == "year":
            rows: list[tuple[str, int]] = []
            for month_index in range(1, 13):
                month_start, month_end = month_range(date(self.anchor.year, month_index, 1))
                net = compute_period(worklogs, month_start, month_end, specs, now).net_seconds
                rows.append((calendar.month_abbr[month_index], net))
            return rows
        if self.granularity in ("day", "month"):
            # A bar per calendar day in the range; one compute_period per day
            # keeps the net figure identical to the per-day computation while
            # reusing the shared aggregation helper.
            day_rows: list[tuple[str, int]] = []
            for day in days_in_range(start, end):
                net = compute_period(worklogs, day, day, specs, now).net_seconds
                day_rows.append((day.strftime("%d"), net))
            return day_rows
        raise ValueError(f"Unknown granularity {self.granularity!r}.")

    @classmethod
    def format_stats(
        cls,
        granularity: str,
        gross_seconds: int,
        recorded_break_seconds: int,
        net_seconds: int,
        chart_rows: list[tuple[str, int]],
    ) -> str:
        """Return the statistics body markup (numbers + text bar chart).

        Args:
            granularity: The active granularity (drives the chart heading).
            gross_seconds: Period gross work seconds.
            recorded_break_seconds: Period recorded break (clock-out gap)
                seconds. These are informational: recorded breaks fall outside
                clocked intervals and are already excluded from gross, so they
                are *not* subtracted to reach ``net_seconds``.
            net_seconds: Period net work seconds.
            chart_rows: The ``(label, net_seconds)`` bar rows.

        Returns:
            Textual markup for the body (numbers block + ASCII bar chart).

        Raises:
            ValueError: On an unknown granularity, so a future
                :data:`STATS_GRANULARITIES` addition fails fast instead of
                silently mis-rendering.
        """
        numbers = (
            f"Gross {format_duration(gross_seconds)}   "
            f"Breaks {format_duration(recorded_break_seconds)}   "
            f"[b]Net {format_duration(net_seconds)}[/b]"
        )
        if granularity == "week":
            heading = "Day work length distribution (net, per weekday)"
        elif granularity == "year":
            heading = "Net work length per month"
        elif granularity == "day":
            heading = "Net work length"
        elif granularity == "month":
            heading = "Net work length per day"
        else:
            raise ValueError(f"Unknown granularity {granularity!r}.")
        bars = render_bar_chart(chart_rows, value_formatter=format_duration)
        chart = "\n".join(bars) if bars else "[dim](no data)[/dim]"
        return numbers + "\n\n" + f"[b]{heading}[/b]\n" + chart


class TaskTimeStatsScreen(_GranularityStatsScreen):
    """Per-doto time-reporting pop-up (day/week/month/year breakdown).

    Opened from the ``time`` TUI layout (the ``T`` key). Mirrors
    :class:`WorkStatsScreen` but reports *per-task focus-session* time rather
    than the global work clock: for a chosen *granularity* (day / week / month
    / year) and anchor period it shows, aggregated across every registered
    repository:

    * each doto's total worked session time, sorted descending (a text/ASCII
      block-character bar chart via the pure :func:`render_bar_chart`), and
    * the per-repository totals (a second bar chart).

    The aggregation reuses :func:`doxtr_doto.work_report.compute_task_breakdown`
    over the shared :func:`doxtr_doto.cli.task_collector.collect_repo_tasks`
    collector (the same one ``doto report`` uses, so the figures agree with
    the CLI), and the period math reuses :func:`anchor_range_for` /
    :func:`shift_anchor`.

    Keys:

    * ``d`` / ``w`` / ``m`` / ``y`` jump to that granularity, and ``g`` cycles
      through them in order,
    * ``←`` / ``→`` move the anchor to the previous / next period (navigating
      across years),
    * ``Esc`` closes.

    The numeric/bar rendering is delegated to the overridable
    :meth:`format_title` / :meth:`format_breakdown` classmethods so a child
    theme can replace it by subclassing and swapping
    :attr:`doxtr_doto.cli.tui.app.DotoApp.task_time_stats_screen_class`.

    All of the shared granularity surface (key bindings, anchor/granularity
    state, ``__init__`` defaulting, :meth:`format_title`, and the
    anchor/granularity navigation actions) is inherited unchanged from
    :class:`_GranularityStatsScreen`.
    """

    #: Title prefix used by the shared
    #: :meth:`_GranularityStatsScreen.format_title`.
    title_prefix = "Task time"

    #: Maximum number of per-doto rows the breakdown chart draws, so a child
    #: theme can tune the cap without overriding :meth:`_refresh`. Mirrors the
    #: :func:`task_breakdown_chart_rows` default.
    max_chart_rows: int = 10

    def compose(self) -> ComposeResult:
        """Build the per-doto statistics modal."""
        with Vertical(id="taskstats-modal"):
            yield Label("", id="taskstats-title")
            with VerticalScroll(id="taskstats-body"):
                yield Static("", id="taskstats-content")
            yield Static(
                "[b]d/w/m/y[/b] granularity  [b]g[/b] cycle  "
                "[b]←/→[/b] prev/next period  [b]Esc[/b] close",
                id="taskstats-hint",
            )

    def _refresh(self) -> None:
        """Recompute and re-render the breakdown for the current state."""
        from doxtr_doto.cli.task_collector import collect_repo_tasks
        from doxtr_doto.work_report import compute_task_breakdown

        now = datetime.now().astimezone()
        start, end = anchor_range_for(self.granularity, self.anchor)
        task_tuples = collect_repo_tasks(self.ctx)
        breakdown = compute_task_breakdown(task_tuples, start, end, now)
        self.query_one("#taskstats-title", Label).update(
            self.format_title(self.granularity, start, end)
        )
        self.query_one("#taskstats-content", Static).update(
            self.format_breakdown(
                breakdown.total_seconds,
                task_breakdown_chart_rows(breakdown.tasks, self.max_chart_rows),
                task_repo_chart_rows(breakdown.per_repo),
            )
        )

    @classmethod
    def format_breakdown(
        cls,
        total_seconds: int,
        task_rows: list[tuple[str, int]],
        repo_rows: list[tuple[str, int]],
    ) -> str:
        """Return the per-doto breakdown body markup (totals + bar charts).

        Args:
            total_seconds: Total task session seconds across all dotos in the
                period.
            task_rows: The ``(repo#id, seconds)`` per-doto bar rows (already
                sorted descending), from :func:`task_breakdown_chart_rows`.
            repo_rows: The ``(repo, seconds)`` per-repo bar rows (sorted
                descending), from :func:`task_repo_chart_rows`.

        Returns:
            Textual markup for the body (totals line + per-doto chart +
            per-repo chart), or an empty-state line when nothing was worked.
        """
        if not task_rows:
            return "[dim](no task sessions in this period)[/dim]"
        numbers = f"[b]Total task time {format_duration(total_seconds)}[/b]"
        task_bars = render_bar_chart(task_rows, value_formatter=format_duration)
        repo_bars = render_bar_chart(repo_rows, value_formatter=format_duration)
        task_chart = "\n".join(task_bars) if task_bars else "[dim](no data)[/dim]"
        repo_chart = "\n".join(repo_bars) if repo_bars else "[dim](no data)[/dim]"
        return (
            numbers
            + "\n\n"
            + "[b]Per doto (worked time)[/b]\n"
            + task_chart
            + "\n\n"
            + "[b]Per repo[/b]\n"
            + repo_chart
        )


class TaskSessionsScreen(ModalScreen[None]):
    """Modal to edit a single doto's recorded focus sessions.

    Mirrors :class:`WorkTimeScreen` but edits one task's ``worklogs`` (its
    recorded focus sessions) in the task's owning repository store, rather
    than the global work clock. Lists every session interval with its
    start/stop and per-interval duration, offers add (``a``), edit (``e`` /
    Enter), and delete (``x``), and shows the task's total session time
    beneath the list. All mutations are persisted back to the correct repo's
    task store immediately: the task is resolved via
    :func:`doxtr_doto.cli.id_resolver.resolve_task_ref` (so a namespaced
    ``repo#id`` writes into the right repo), the task is loaded fresh, its
    ``worklogs`` mutated by the pure :func:`apply_interval_edit` /
    :func:`doxtr_doto.time_tracking.remove_interval` primitives, and saved.

    All rendering goes through the pure, overridable :meth:`format_title` /
    :meth:`format_interval_row` classmethods so a child theme can replace it
    by subclassing and swapping
    :attr:`doxtr_doto.cli.tui.app.DotoApp.task_sessions_screen_class`.
    """

    BINDINGS = [
        ("escape", "close", "Close"),
        ("a", "add", "Add"),
        ("e", "edit", "Edit"),
        ("enter", "edit", "Edit"),
        ("x", "delete", "Delete"),
        # Session navigation: arrow Up/Down and the vim-style j/k move the
        # highlighted row within the interval list so e/Enter/x act on the
        # row the user actually navigated to.
        ("up", "nav_up", "Prev session"),
        ("down", "nav_down", "Next session"),
        ("k", "nav_up", "Prev session"),
        ("j", "nav_down", "Next session"),
    ]

    def __init__(self, ctx: DotoContext, task_ref: str) -> None:
        """Initialize the per-doto session editor.

        Args:
            ctx: The CLI context (for repo-store resolution).
            task_ref: The task reference (bare ``id`` or namespaced
                ``repo#id``) whose sessions are edited.
        """
        super().__init__()
        self.ctx = ctx
        self.task_ref = task_ref

    def compose(self) -> ComposeResult:
        """Build the per-doto session editor modal."""
        with Vertical(id="tasksessions-modal"):
            yield Label("", id="tasksessions-title")
            with VerticalScroll(id="tasksessions-body"):
                yield ListView(id="tasksessions-list")
            yield Label("", id="tasksessions-total")
            yield Static(
                "[b]a[/b] add  [b]e/Enter[/b] edit  [b]x[/b] delete  "
                "[b]↑/↓[/b] (or [b]j/k[/b]) session  [b]Esc[/b] close",
                id="tasksessions-hint",
            )

    def on_mount(self) -> None:
        """Populate the session list on first display."""
        self._refresh()

    def _load_worklogs(self) -> list[WorkLog]:
        """Return the task's current worklogs (empty when it cannot resolve)."""
        from doxtr_doto.cli.id_resolver import resolve_task_ref

        resolved = resolve_task_ref(self.ctx, self.task_ref)
        if resolved is None:
            return []
        task = resolved.store.get_task(resolved.task_id)
        if task is None:
            return []
        return list(task.get("worklogs", []))

    def _save_worklogs(self, worklogs: list[WorkLog]) -> bool:
        """Persist the mutated worklogs back to the owning repo store.

        Delegates to :func:`doxtr_doto.cli.tui.actions.update_task` so the
        write path never duplicates the resolve → get-task guard →
        ``update_task`` → ``save`` business logic (that function is the single
        TUI task-write seam).

        Args:
            worklogs: The new worklog list to persist.

        Returns:
            True when the task resolved and the write succeeded, else False
            (the reference could not be resolved).
        """
        from doxtr_doto.cli.tui import actions

        return actions.update_task(self.ctx, self.task_ref, {"worklogs": worklogs})

    def _refresh(self) -> None:
        """Reload the task's sessions into the list, preserving the cursor."""
        self.query_one("#tasksessions-title", Label).update(self.format_title(self.task_ref))
        list_view = self.query_one("#tasksessions-list", ListView)
        previous_index = list_view.index
        list_view.clear()
        worklogs = self._load_worklogs()
        total_seconds = elapsed_seconds(worklogs)
        self.query_one("#tasksessions-total", Label).update(
            f"[b]Total:[/b] {format_duration(total_seconds)}"
        )
        rows = task_interval_display_rows(worklogs)
        if not rows:
            list_view.append(ListItem(Label("(no sessions)")))
            return
        for index, start, stop, seconds in rows:
            item = ListItem(Label(self.format_interval_row(start, stop, seconds)))
            item.worklog_index = index  # type: ignore[attr-defined]
            list_view.append(item)
        if previous_index is None:
            list_view.index = 0
        else:
            list_view.index = max(0, min(previous_index, len(rows) - 1))
        list_view.focus()

    @classmethod
    def format_title(cls, task_ref: str) -> str:
        """Return the modal title markup for the edited task.

        Args:
            task_ref: The task reference being edited.

        Returns:
            Textual markup for the title line.
        """
        return f"[b]Sessions — {task_ref}[/b]"

    @classmethod
    def format_interval_row(cls, start: str, stop: str, seconds: int | None) -> str:
        """Return one session-interval row's display label.

        Args:
            start: The interval's start timestamp (ISO 8601).
            stop: The interval's stop timestamp, or blank for a running one.
            seconds: The interval's duration in seconds, or None for a running
                / unparseable interval.

        Returns:
            A plain-text label for the list row.
        """
        stop_display = stop if stop else "(running)"
        if seconds is None:
            return f"{start}  →  {stop_display}"
        return f"{start}  →  {stop_display}  ({format_duration(seconds)})"

    def _selected_index(self) -> int | None:
        """Return the worklog index of the highlighted row, if any."""
        list_view = self.query_one("#tasksessions-list", ListView)
        item = list_view.highlighted_child
        if item is None:
            return None
        return getattr(item, "worklog_index", None)

    def action_nav_up(self) -> None:
        """Highlight the previous session row (Up / k)."""
        self.query_one("#tasksessions-list", ListView).action_cursor_up()

    def action_nav_down(self) -> None:
        """Highlight the next session row (Down / j)."""
        self.query_one("#tasksessions-list", ListView).action_cursor_down()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Open the editor when a row is activated with Enter."""
        event.stop()
        self.action_edit()

    def action_add(self) -> None:
        """Open the interval editor to add a new session."""
        default_start = datetime.now().astimezone().isoformat()
        self.app.push_screen(
            WorkIntervalEditScreen(None, default_start, None),
            self._apply_edit,
        )

    def action_edit(self) -> None:
        """Open the interval editor for the highlighted session."""
        index = self._selected_index()
        if index is None:
            return
        worklogs = self._load_worklogs()
        if index < 0 or index >= len(worklogs):
            return
        log = worklogs[index]
        self.app.push_screen(
            WorkIntervalEditScreen(index, str(log.get("started_at", "")), log.get("stopped_at")),
            self._apply_edit,
        )

    def action_delete(self) -> None:
        """Delete the highlighted session interval."""
        index = self._selected_index()
        if index is None:
            return
        worklogs = self._load_worklogs()
        try:
            new_worklogs = remove_interval(worklogs, index)
        except IndexError:
            return
        if self._save_worklogs(new_worklogs):
            self._refresh()

    def _apply_edit(
        self,
        result: tuple[int | None, str, str | None] | None,
    ) -> None:
        """Persist an add/edit returned by :class:`WorkIntervalEditScreen`."""
        if result is None:
            return
        index, start, stop = result
        worklogs = self._load_worklogs()
        try:
            new_worklogs = apply_interval_edit(worklogs, index, start, stop)
        except (ValueError, IndexError) as exc:
            self.app.notify(f"Could not save session: {exc}", severity="error")
            return
        if self._save_worklogs(new_worklogs):
            self._refresh()

    def action_close(self) -> None:
        """Close the session editor."""
        self.dismiss(None)
