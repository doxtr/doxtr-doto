"""Recurrence pattern parsing and date generation for recurring tasks."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, time, timedelta
from enum import Enum
from typing import Any


class RecurrenceType(Enum):
    """Type of recurrence pattern."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class WeekdayPosition(Enum):
    """Position of weekday in month."""

    FIRST = "first"
    SECOND = "second"
    THIRD = "third"
    FOURTH = "fourth"
    LAST = "last"


WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

WEEKDAY_NAMES = {v: k for k, v in WEEKDAYS.items()}

POSITION_MAP = {
    "first": WeekdayPosition.FIRST,
    "second": WeekdayPosition.SECOND,
    "third": WeekdayPosition.THIRD,
    "fourth": WeekdayPosition.FOURTH,
    "last": WeekdayPosition.LAST,
    "1st": WeekdayPosition.FIRST,
    "2nd": WeekdayPosition.SECOND,
    "3rd": WeekdayPosition.THIRD,
    "4th": WeekdayPosition.FOURTH,
}


@dataclass
class RecurrencePattern:
    """Parsed recurrence pattern.

    Beyond the calendar recurrence (type/interval/weekday/day-of-month/weekday
    position), a pattern may optionally carry a per-occurrence clock time
    (:attr:`start_time`) and a duration (:attr:`duration_minutes`), parsed from
    the trailing ``at <time>`` / ``for <duration>`` suffixes on the pattern
    string (see :func:`parse_recurrence`). Both are ``None`` for a plain
    calendar pattern, which behaves exactly as before.

    Attributes:
        type: The recurrence type (daily/weekly/monthly).
        interval: Repeat every N days/weeks/months.
        weekday: Weekday (0-6) for weekly / monthly-weekday patterns.
        day_of_month: Day of month (1-31) for monthly day-of-month patterns.
        weekday_position: first/second/.../last for monthly weekday patterns.
        start_time: Optional naive clock time each occurrence starts at (from
            the ``at <time>`` suffix), or ``None`` for date-only occurrences.
        duration_minutes: Optional per-occurrence duration in whole minutes
            (from the ``for <duration>`` suffix), applied as each generated
            task's ``estimate``, or ``None``.
    """

    type: RecurrenceType
    interval: int = 1  # every N days/weeks/months
    weekday: int | None = None  # 0-6 for weekly patterns
    day_of_month: int | None = None  # 1-31 for monthly patterns
    weekday_position: WeekdayPosition | None = None  # first/last/etc for monthly weekday patterns
    start_time: time | None = None  # per-occurrence clock time (from 'at HH:MM')
    duration_minutes: int | None = None  # per-occurrence duration (from 'for 2h')

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for JSON storage.

        The optional :attr:`start_time` is stored as an ISO ``HH:MM`` /
        ``HH:MM:SS`` string (seconds only when non-zero) and
        :attr:`duration_minutes` as the raw int minute count, so a pattern
        round-trips through :meth:`from_dict`. Both keys are always present
        (``None`` when unset) so stored data is self-describing.
        """
        return {
            "type": self.type.value,
            "interval": self.interval,
            "weekday": self.weekday,
            "day_of_month": self.day_of_month,
            "weekday_position": self.weekday_position.value if self.weekday_position else None,
            "start_time": format_time(self.start_time),
            "duration_minutes": self.duration_minutes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RecurrencePattern:
        """Deserialize from dictionary.

        Backward compatible: a stored pattern that predates the time/duration
        feature (no ``start_time`` / ``duration_minutes`` keys) deserializes
        with both set to ``None``, so existing series keep working unchanged.
        """
        from doxtr_doto.date_utils import parse_time_token

        start_time_raw = data.get("start_time")
        start_time = parse_time_token(start_time_raw) if start_time_raw else None
        return cls(
            type=RecurrenceType(data["type"]),
            interval=data.get("interval", 1),
            weekday=data.get("weekday"),
            day_of_month=data.get("day_of_month"),
            weekday_position=WeekdayPosition(data["weekday_position"])
            if data.get("weekday_position")
            else None,
            start_time=start_time,
            duration_minutes=data.get("duration_minutes"),
        )

    def describe(self) -> str:
        """Return human-readable description of the pattern.

        Appends `` at HH:MM`` and/or `` for <duration>`` (via
        :func:`doxtr_doto.date_utils.format_duration_minutes`) when the pattern
        carries a :attr:`start_time` / :attr:`duration_minutes`, so
        ``series list`` / ``series show`` and dry runs read naturally (e.g.
        ``every 2 weeks on monday at 16:00 for 2h``).
        """
        base = self._describe_calendar()
        return base + self._describe_time_suffix()

    def _describe_calendar(self) -> str:
        """Return the calendar portion of the description (no time/duration)."""
        if self.type == RecurrenceType.DAILY:
            if self.interval == 1:
                return "every day"
            return f"every {self.interval} days"

        if self.type == RecurrenceType.WEEKLY:
            weekday_name = (
                WEEKDAY_NAMES.get(self.weekday, "day") if self.weekday is not None else "day"
            )
            if self.interval == 1:
                return f"every {weekday_name}"
            return f"every {self.interval} weeks on {weekday_name}"

        if self.type == RecurrenceType.MONTHLY:
            if self.day_of_month:
                suffix = _ordinal_suffix(self.day_of_month)
                if self.interval == 1:
                    return f"every month on the {self.day_of_month}{suffix}"
                return f"every {self.interval} months on the {self.day_of_month}{suffix}"

            if self.weekday is not None and self.weekday_position:
                weekday_name = WEEKDAY_NAMES.get(self.weekday, "day")
                if self.interval == 1:
                    return f"every month on {self.weekday_position.value} {weekday_name}"
                return (
                    f"every {self.interval} months on {self.weekday_position.value} {weekday_name}"
                )

        return "unknown pattern"

    def _describe_time_suffix(self) -> str:
        """Return the `` at HH:MM`` / `` for <duration>`` description suffix.

        Each piece is appended only when set, in time-then-duration order, so a
        plain calendar pattern yields an empty suffix (unchanged description).
        """
        from doxtr_doto.date_utils import format_duration_minutes

        suffix = ""
        if self.start_time is not None:
            suffix += f" at {format_time(self.start_time)}"
        if self.duration_minutes is not None:
            suffix += f" for {format_duration_minutes(self.duration_minutes)}"
        return suffix


def format_time(value: time | None) -> str | None:
    """Format a naive time as ``HH:MM`` / ``HH:MM:SS`` (seconds when non-zero).

    Mirrors :meth:`doxtr_doto.date_utils.DotoDate._format_time` so a serialized
    ``start_time`` round-trips through :func:`doxtr_doto.date_utils.parse_time_token`.

    Args:
        value: The time to format, or ``None``.

    Returns:
        The ``HH:MM[:SS]`` string, or ``None`` when ``value`` is ``None``.
    """
    if value is None:
        return None
    if value.second:
        return f"{value.hour:02d}:{value.minute:02d}:{value.second:02d}"
    return f"{value.hour:02d}:{value.minute:02d}"


def _ordinal_suffix(n: int) -> str:
    """Return ordinal suffix for a number (1st, 2nd, 3rd, etc.)."""
    if 11 <= n <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def parse_recurrence(pattern_str: str) -> RecurrencePattern:
    """Parse a recurrence pattern string.

    Supported formats:
    - every day
    - every N days
    - every monday/tuesday/...
    - every N weeks on monday/tuesday/...
    - every month on N (day of month)
    - every month on first/last monday/tuesday/...
    - every N months on first/last monday/tuesday/...

    Any of the above may carry an optional trailing ``at <time>`` and/or
    ``for <duration>`` suffix (time before duration), e.g.
    ``every 2 weeks on monday at 16:00 for 2h``:

    - ``at <time>`` sets :attr:`RecurrencePattern.start_time`, parsed via
      :func:`doxtr_doto.date_utils.parse_time_token` (``16:00``, ``16h``,
      ``16:00:31``).
    - ``for <duration>`` sets :attr:`RecurrencePattern.duration_minutes`,
      parsed via :func:`doxtr_doto.date_utils.parse_duration` (``2h``, ``90m``,
      ``1h30m``).

    A pattern with no ``at`` / ``for`` suffix is parsed exactly as before.

    Args:
        pattern_str: Pattern string to parse.

    Returns:
        Parsed RecurrencePattern.

    Raises:
        ValueError: If the pattern (or an ``at`` / ``for`` token) cannot be
            parsed.
    """
    pattern_str = pattern_str.strip().lower()

    # Peel off any trailing ``at <time>`` / ``for <duration>`` suffixes before
    # the calendar matching below, so the existing matchers only ever see the
    # pure calendar portion. ``every month on 15`` (day-of-month) stays intact
    # because the split keys on the whole words ``at`` / ``for`` only.
    pattern_str, start_time, duration_minutes = _split_time_duration(pattern_str)

    pattern = _parse_calendar(pattern_str)
    pattern.start_time = start_time
    pattern.duration_minutes = duration_minutes
    return pattern


def _split_time_duration(pattern_str: str) -> tuple[str, time | None, int | None]:
    """Split trailing ``at <time>`` / ``for <duration>`` off a pattern string.

    Scans for the ``at`` and ``for`` keywords as whole words and parses the
    token that follows each (``at`` -> :func:`parse_time_token`, ``for`` ->
    :func:`parse_duration`). Only a *trailing* suffix is consumed: the calendar
    portion returned is the text before the first matched keyword. A pattern
    with neither keyword is returned unchanged with both values ``None``.

    Args:
        pattern_str: The lower-cased, stripped pattern string.

    Returns:
        A ``(calendar_str, start_time, duration_minutes)`` tuple.

    Raises:
        ValueError: If an ``at`` / ``for`` token is present but malformed.
    """
    from doxtr_doto.date_utils import parse_duration, parse_time_token

    start_time: time | None = None
    duration_minutes: int | None = None
    calendar_end = len(pattern_str)

    for match in re.finditer(r"\b(at|for)\b\s+(\S+)", pattern_str):
        keyword = match.group(1)
        token = match.group(2)
        if keyword == "at":
            start_time = parse_time_token(token)
        else:  # keyword == "for"
            # The regex guarantees a non-empty token, so parse_duration never
            # returns None here; let its ValueError propagate on a bad token
            # (mirrors the ``at`` branch above).
            duration_minutes = parse_duration(token)
        calendar_end = min(calendar_end, match.start())

    calendar_str = pattern_str[:calendar_end].strip()
    return calendar_str, start_time, duration_minutes


def _parse_calendar(pattern_str: str) -> RecurrencePattern:
    """Parse the calendar portion of a pattern (no time/duration suffix).

    This is the original :func:`parse_recurrence` body: it matches the
    daily/weekly/monthly calendar forms and returns a pattern with
    ``start_time`` / ``duration_minutes`` left at their defaults (``None``).
    :func:`parse_recurrence` peels any ``at`` / ``for`` suffix first and sets
    those fields on the result.

    Args:
        pattern_str: The lower-cased, stripped calendar-only pattern string.

    Returns:
        Parsed RecurrencePattern (time/duration unset).

    Raises:
        ValueError: If the calendar portion cannot be parsed.
    """
    # Remove leading "every" if present
    if pattern_str.startswith("every "):
        pattern_str = pattern_str[6:].strip()

    # Normalize multiple spaces to single space
    pattern_str = re.sub(r"\s+", " ", pattern_str)

    # "day" or "N days"
    match = re.match(r"^(\d+\s+)?days?$", pattern_str)
    if match:
        interval = int(match.group(1).strip()) if match.group(1) else 1
        return RecurrencePattern(type=RecurrenceType.DAILY, interval=interval)

    # "monday", "tuesday", etc. (weekly, interval 1)
    if pattern_str in WEEKDAYS:
        return RecurrencePattern(
            type=RecurrenceType.WEEKLY,
            interval=1,
            weekday=WEEKDAYS[pattern_str],
        )

    # "N weeks on monday"
    match = re.match(r"^(\d+)\s+weeks?\s+on\s+(\w+)$", pattern_str)
    if match:
        interval = int(match.group(1))
        weekday_str = match.group(2)
        if weekday_str not in WEEKDAYS:
            raise ValueError(f"Unknown weekday: {weekday_str}")
        return RecurrencePattern(
            type=RecurrenceType.WEEKLY,
            interval=interval,
            weekday=WEEKDAYS[weekday_str],
        )

    # "week on monday" (interval 1)
    match = re.match(r"^weeks?\s+on\s+(\w+)$", pattern_str)
    if match:
        weekday_str = match.group(1)
        if weekday_str not in WEEKDAYS:
            raise ValueError(f"Unknown weekday: {weekday_str}")
        return RecurrencePattern(
            type=RecurrenceType.WEEKLY,
            interval=1,
            weekday=WEEKDAYS[weekday_str],
        )

    # "month on N" or "N months on N"
    match = re.match(r"^(?:(\d+)\s+)?months?\s+on\s+(\d+)(?:st|nd|rd|th)?$", pattern_str)
    if match:
        interval = int(match.group(1)) if match.group(1) else 1
        day = int(match.group(2))
        if day < 1 or day > 31:
            raise ValueError(f"Invalid day of month: {day}")
        return RecurrencePattern(
            type=RecurrenceType.MONTHLY,
            interval=interval,
            day_of_month=day,
        )

    # "month on first/last monday" or "N months on first/last monday"
    match = re.match(
        r"^(?:(\d+)\s+)?months?\s+on\s+(first|second|third|fourth|last|1st|2nd|3rd|4th)\s+(\w+)$",
        pattern_str,
    )
    if match:
        interval = int(match.group(1)) if match.group(1) else 1
        position_str = match.group(2)
        weekday_str = match.group(3)

        if weekday_str not in WEEKDAYS:
            raise ValueError(f"Unknown weekday: {weekday_str}")
        if position_str not in POSITION_MAP:
            raise ValueError(f"Unknown position: {position_str}")

        return RecurrencePattern(
            type=RecurrenceType.MONTHLY,
            interval=interval,
            weekday=WEEKDAYS[weekday_str],
            weekday_position=POSITION_MAP[position_str],
        )

    raise ValueError(f"Cannot parse recurrence pattern: '{pattern_str}'")


def _add_months(d: date, months: int) -> date:
    """Add months to a date, handling month-end edge cases."""
    month = d.month + months
    year = d.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    # Handle edge cases like Jan 31 + 1 month
    days_in_month = _days_in_month(year, month)
    day = min(d.day, days_in_month)
    return date(year, month, day)


def _days_in_month(year: int, month: int) -> int:
    """Return number of days in a month."""
    if month == 2:
        if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0):
            return 29
        return 28
    if month in (4, 6, 9, 11):
        return 30
    return 31


def _nth_weekday_of_month(
    year: int, month: int, weekday: int, position: WeekdayPosition
) -> date | None:
    """Get the nth weekday of a month.

    Args:
        year: Year.
        month: Month (1-12).
        weekday: Weekday (0=Monday, 6=Sunday).
        position: Which occurrence (first, second, third, fourth, last).

    Returns:
        Date of the nth weekday, or None if it doesn't exist.
    """
    if position == WeekdayPosition.LAST:
        # Start from last day of month and work backwards
        last_day = _days_in_month(year, month)
        d = date(year, month, last_day)
        while d.weekday() != weekday:
            d -= timedelta(days=1)
        return d

    # Start from first day of month
    d = date(year, month, 1)

    # Find first occurrence of weekday
    while d.weekday() != weekday:
        d += timedelta(days=1)

    # Add weeks for position
    position_num = {
        WeekdayPosition.FIRST: 0,
        WeekdayPosition.SECOND: 1,
        WeekdayPosition.THIRD: 2,
        WeekdayPosition.FOURTH: 3,
    }[position]

    d += timedelta(weeks=position_num)

    # Check if still in same month
    if d.month != month:
        return None

    return d


def generate_occurrences(
    pattern: RecurrencePattern,
    start_date: date,
    end_date: date,
) -> Iterator[date]:
    """Generate occurrence dates for a recurrence pattern.

    Args:
        pattern: Recurrence pattern.
        start_date: First possible occurrence date.
        end_date: Last possible occurrence date (inclusive).

    Yields:
        Dates matching the pattern.
    """
    if start_date > end_date:
        return

    if pattern.type == RecurrenceType.DAILY:
        current = start_date
        while current <= end_date:
            yield current
            current += timedelta(days=pattern.interval)

    elif pattern.type == RecurrenceType.WEEKLY:
        # Find first occurrence of weekday on or after start_date
        current = start_date
        while current.weekday() != pattern.weekday:
            current += timedelta(days=1)

        while current <= end_date:
            yield current
            current += timedelta(weeks=pattern.interval)

    elif pattern.type == RecurrenceType.MONTHLY:
        # Start from month of start_date
        year, month = start_date.year, start_date.month

        while True:
            if pattern.day_of_month:
                # Fixed day of month
                day = min(pattern.day_of_month, _days_in_month(year, month))
                occurrence: date | None = date(year, month, day)
            elif pattern.weekday is not None and pattern.weekday_position:
                # Nth weekday of month
                occurrence = _nth_weekday_of_month(
                    year, month, pattern.weekday, pattern.weekday_position
                )
                if occurrence is None:
                    # Skip this month (e.g., no 5th Friday)
                    year, month = (year, month + 1) if month < 12 else (year + 1, 1)
                    continue
            else:
                break

            assert occurrence is not None
            if occurrence > end_date:
                break

            if occurrence >= start_date:
                yield occurrence

            # Move to next interval
            for _ in range(pattern.interval):
                month += 1
                if month > 12:
                    month = 1
                    year += 1


def pattern_base_str(pattern: RecurrencePattern) -> str:
    """Return a parseable base pattern string (no ``at`` / ``for`` suffix).

    Unlike :meth:`RecurrencePattern.describe`, the result always round-trips
    through :func:`parse_recurrence` -- in particular a monthly day-of-month
    pattern is rendered as ``every month on <N>`` (not ``on the Nth``), which
    the parser accepts. Used to pre-populate the edit-series dialog's pattern
    field from a stored series.

    Args:
        pattern: The recurrence pattern to render.

    Returns:
        A base pattern string parseable by :func:`parse_recurrence`.

    Raises:
        ValueError: If the pattern's type (or monthly variant) cannot be
            rendered, so an unhandled :class:`RecurrenceType` surfaces at test
            time rather than silently mis-rendering to ``"every day"``.
    """
    if pattern.type == RecurrenceType.DAILY:
        if pattern.interval == 1:
            return "every day"
        return f"every {pattern.interval} days"

    if pattern.type == RecurrenceType.WEEKLY:
        weekday_name = (
            WEEKDAY_NAMES.get(pattern.weekday, "monday")
            if pattern.weekday is not None
            else "monday"
        )
        if pattern.interval == 1:
            return f"every {weekday_name}"
        return f"every {pattern.interval} weeks on {weekday_name}"

    if pattern.type == RecurrenceType.MONTHLY:
        if pattern.day_of_month:
            if pattern.interval == 1:
                return f"every month on {pattern.day_of_month}"
            return f"every {pattern.interval} months on {pattern.day_of_month}"
        if pattern.weekday is not None and pattern.weekday_position:
            weekday_name = WEEKDAY_NAMES.get(pattern.weekday, "monday")
            position = pattern.weekday_position.value
            if pattern.interval == 1:
                return f"every month on {position} {weekday_name}"
            return f"every {pattern.interval} months on {position} {weekday_name}"

    raise ValueError(f"cannot render base pattern for {pattern.type!r}")


def format_date_for_title(d: date, format_str: str = "%b %-d") -> str:
    """Format a date for inclusion in task title.

    Args:
        d: Date to format.
        format_str: strftime format string.

    Returns:
        Formatted date string.
    """
    try:
        return d.strftime(format_str)
    except ValueError:
        # Fallback for platforms that don't support %-d
        return d.strftime("%b %d").replace(" 0", " ")


def render_series_title(title_template: str, occurrence_date: date) -> str:
    """Render a series title for one occurrence.

    When ``title_template`` contains the ``{date}`` placeholder it is replaced
    with :func:`format_date_for_title` for the occurrence; otherwise the
    template is returned unchanged. Shared by
    :func:`build_series_task_data` and the ``doto add --repeat`` dry-run
    preview so the two render titles identically.

    Args:
        title_template: The series title template (may contain ``{date}``).
        occurrence_date: The calendar date of this occurrence.

    Returns:
        The rendered title string.
    """
    if "{date}" in title_template:
        return title_template.replace("{date}", format_date_for_title(occurrence_date))
    return title_template


def build_occurrence_due(pattern: RecurrencePattern, occurrence_date: date) -> str:
    """Return the stored ``due`` string for one occurrence of a pattern.

    When the pattern carries a :attr:`~RecurrencePattern.start_time`, the
    occurrence date is combined with that clock time and serialized as
    ``YYYY-MM-DDTHH:MM`` (via :class:`doxtr_doto.date_utils.DotoDate`) so the
    existing due-with-time feature and calendar sync pick it up. A pattern
    without a start time yields the plain date-only ``YYYY-MM-DD`` string,
    unchanged from before.

    Args:
        pattern: The recurrence pattern (its :attr:`start_time` drives whether
            a time is appended).
        occurrence_date: The calendar date of this occurrence.

    Returns:
        The canonical storage ``due`` string.
    """
    from doxtr_doto.date_utils import DotoDate

    return DotoDate(occurrence_date, pattern.start_time).isoformat()


def build_series_task_data(
    pattern: RecurrencePattern,
    occurrence_date: date,
    title_template: str,
    series_id: str,
    task_defaults: dict[str, Any],
) -> dict[str, Any]:
    """Build one task dict from an occurrence + pattern + series defaults.

    The single source of truth for turning a generated occurrence into a stored
    task, shared by the ``doto add --repeat`` create path
    (:func:`doxtr_doto.cli.commands.add._add_recurring_tasks`) and ``series
    extend`` (:func:`doxtr_doto.cli.commands.series.series_extend`) so the two
    never diverge. It applies:

    * the title template (``{date}`` replaced with
      :func:`format_date_for_title` when present),
    * the ``due`` via :func:`build_occurrence_due` (date + the pattern's
      :attr:`~RecurrencePattern.start_time` when set, else date-only),
    * the ``series_id`` and all ``task_defaults``, and
    * the ``estimate`` from the pattern's
      :attr:`~RecurrencePattern.duration_minutes` when set (the series default;
      it only sets ``estimate`` when the pattern carries a duration, so a plain
      calendar series is unchanged).

    Args:
        pattern: The recurrence pattern (supplies time + duration).
        occurrence_date: The calendar date of this occurrence.
        title_template: The series title template (may contain ``{date}``).
        series_id: The owning series id, stored on the task.
        task_defaults: Shared per-series task defaults (assignee/priority/etc).

    Returns:
        The task data dict ready for :meth:`JsonTaskStore.add_task`.
    """
    title = render_series_title(title_template, occurrence_date)

    task_data: dict[str, Any] = {
        "title": title,
        "due": build_occurrence_due(pattern, occurrence_date),
        "series_id": series_id,
        **task_defaults,
    }
    if pattern.duration_minutes is not None:
        task_data["estimate"] = pattern.duration_minutes
    return task_data
