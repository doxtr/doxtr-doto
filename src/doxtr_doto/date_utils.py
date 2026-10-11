"""Date handling utilities for doxtr_doto.

Single source of truth for date parsing, formatting, and comparison.
All other modules should import from here instead of using direct
date.fromisoformat() calls.

This module provides:
- DotoDate: Immutable wrapper for consistent date handling
- Module-level convenience functions that delegate to DotoDate
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from typing import Union

DateLike = Union[str, date, datetime, "DotoDate", None]

_ISO_FORMAT = "%Y-%m-%d"

# A due value may optionally carry a *naive, local* clock time appended to the
# calendar date. The project intentionally models dates as naive local (ruff
# DTZ is disabled); the time component follows the same convention -- it carries
# no timezone and is interpreted in the author's local wall-clock. This keeps
# the foundation simple for a later calendar-sync feature, which can attach a
# timezone at that boundary.
#
# Accepted time syntaxes appended to a ``YYYY-MM-DD`` date, separated by a
# single space or a ``T`` (ISO 8601 style):
#   * ``HH:MM``       e.g. ``16:00``
#   * ``HHh``         hour shorthand, e.g. ``16h`` -> ``16:00``
#   * ``HH:MM:SS``    e.g. ``16:00:31``
# A date with no time is still a pure date and behaves identically to before.
_HOUR_SHORTHAND_RE = re.compile(r"^(?P<hour>\d{1,2})h$", re.IGNORECASE)
_TIME_RE = re.compile(r"^(?P<hour>\d{1,2}):(?P<minute>\d{2})(?::(?P<second>\d{2}))?$")


def parse_time_token(token: str) -> time:
    """Parse a single time token into a naive :class:`datetime.time`.

    Accepts the documented time syntaxes (``HH:MM``, ``HHh``, ``HH:MM:SS``).
    This is the public helper for callers (e.g. the CLI relative-date parser)
    that must split a time suffix off before the date part is in ISO form.

    Args:
        token: The time portion of a due string (no date, already stripped).

    Returns:
        A naive ``time`` object (no timezone).

    Raises:
        ValueError: If the token is not a recognized/valid time.
    """
    shorthand = _HOUR_SHORTHAND_RE.match(token)
    if shorthand is not None:
        hour = int(shorthand.group("hour"))
        return time(hour=hour)

    match = _TIME_RE.match(token)
    if match is None:
        raise ValueError(f"Invalid time '{token}'")
    hour = int(match.group("hour"))
    minute = int(match.group("minute"))
    second = int(match.group("second") or 0)
    # time() validates the ranges (0-23 / 0-59) and raises ValueError otherwise.
    return time(hour=hour, minute=minute, second=second)


def _split_date_and_time(value: str) -> tuple[str, time | None]:
    """Split a due string into its date part and optional naive time part.

    The date and an optional time may be separated by a single space or a
    ``T`` (ISO 8601 style). A value with no separator is treated as date-only.

    Args:
        value: The already-stripped due string.

    Returns:
        A ``(date_str, time_or_none)`` tuple. ``time_or_none`` is ``None`` for a
        date-only value.

    Raises:
        ValueError: If a time part is present but not a recognized time.
    """
    # Prefer the ISO 'T' separator; fall back to a single space separator.
    if "T" in value:
        date_str, _, time_str = value.partition("T")
    elif " " in value:
        date_str, _, time_str = value.partition(" ")
    else:
        return value, None

    time_str = time_str.strip()
    if not time_str:
        return date_str.strip(), None
    return date_str.strip(), parse_time_token(time_str)


class DotoDate:
    """Immutable wrapper for consistent date handling throughout doto.

    Stores the date as a date object internally. Accepts strings,
    date objects, datetime objects, or None on construction via parse().

    Usage:
        d = DotoDate.parse("2026-08-15")
        d.isoformat()        # "2026-08-15"
        d.is_before(date.today())
        d.to_display("%b %d, %Y")  # "Aug 15, 2026"
        d.is_overdue()       # True if past today
        str(d)               # "2026-08-15"

    Comparison operators work with DotoDate, date objects, and ISO strings:
        d1 = DotoDate.parse("2026-08-15")
        d2 = DotoDate.parse("2026-08-20")
        d1 < d2              # True
        d1 < date(2026, 8, 20)  # True

    Comparison granularity: ``__eq__``/``__lt__``/``__gt__`` (and the
    ``is_before``/``is_after`` helpers) compare the calendar *date only* and
    ignore any time component -- two dues on the same day with different times
    compare equal and ``__hash__`` is date-based. ``is_overdue()`` is the
    exception: it is instant-aware when a time is present. For instant-level
    comparison (e.g. future calendar-sync change detection) use
    ``to_datetime()`` or compare ``isoformat()`` strings instead of ``==``.
    """

    __slots__ = ("_date", "_time")

    def __init__(self, value: date, time_part: time | None = None) -> None:
        """Initialize with a date object and an optional naive time.

        Use DotoDate.parse() for flexible input types.

        Args:
            value: A date object (not datetime, not string).
            time_part: Optional naive :class:`datetime.time` for a due that
                carries a clock time. ``None`` (the default) means date-only,
                which behaves exactly as before.

        Raises:
            TypeError: If value is not a date object, or time_part is not a
                naive time.
        """
        if not isinstance(value, date) or isinstance(value, datetime):
            raise TypeError(f"Expected date, got {type(value).__name__}")
        if time_part is not None:
            if not isinstance(time_part, time):
                raise TypeError(f"Expected time, got {type(time_part).__name__}")
            if time_part.tzinfo is not None:
                raise ValueError("DotoDate time must be naive (no timezone)")
        self._date = value
        self._time = time_part

    @classmethod
    def parse(cls, value: DateLike) -> DotoDate | None:
        """Parse any date-like value. Returns None for None/empty.

        Args:
            value: Date-like value to parse. Can be:
                - None: returns None
                - DotoDate: returns as-is
                - datetime: extracts date part
                - date: wraps in DotoDate
                - str: parses as ISO format (YYYY-MM-DD)

        Returns:
            DotoDate instance or None if value is None/empty.

        Raises:
            ValueError: If string is not valid ISO format.
            TypeError: If value is an unsupported type.
        """
        if value is None:
            return None
        if isinstance(value, DotoDate):
            return value
        if isinstance(value, datetime):
            # Backward compatible: a datetime is reduced to its date part (the
            # historical behavior). Time-bearing dues are expressed as strings
            # (``YYYY-MM-DDTHH:MM``) and parsed via the str branch below, so
            # created/updated datetimes keep rendering/serializing as before.
            return cls(value.date())
        if isinstance(value, date):
            return cls(value)
        if isinstance(value, str):
            v = value.strip()
            if not v:
                return None
            # Split off an optional time component, then parse the date part as
            # ISO format. A date-only string parses exactly as before.
            date_str, time_part = _split_date_and_time(v)
            parsed = date.fromisoformat(date_str)
            return cls(parsed, time_part)
        raise TypeError(f"Cannot parse date from {type(value).__name__}")

    @classmethod
    def parse_safe(cls, value: DateLike) -> DotoDate | None:
        """Like parse() but returns None instead of raising on bad input.

        Args:
            value: Date-like value to parse.

        Returns:
            DotoDate instance or None if value is None, empty, or invalid.
        """
        try:
            return cls.parse(value)
        except (ValueError, TypeError):
            return None

    @classmethod
    def today(cls) -> DotoDate:
        """Return today's date as a DotoDate.

        Returns:
            DotoDate for today.
        """
        return cls(date.today())

    def isoformat(self) -> str:
        """Return the due in ISO format.

        Date-only returns ``YYYY-MM-DD`` (unchanged). When a time is present it
        returns ``YYYY-MM-DDTHH:MM`` (or ``YYYY-MM-DDTHH:MM:SS`` when seconds
        are non-zero), i.e. an ISO 8601 datetime. This is the canonical storage
        string round-tripped through RST and JSON.

        Returns:
            ISO format string.
        """
        if self._time is None:
            return self._date.isoformat()
        return f"{self._date.isoformat()}T{self._format_time()}"

    def _format_time(self) -> str:
        """Return the time component as ``HH:MM`` or ``HH:MM:SS``.

        Seconds are only emitted when non-zero, so ``16:00`` round-trips as
        ``16:00`` (not ``16:00:00``) and ``16:00:31`` keeps its seconds.
        Returns an empty string when there is no time component.
        """
        if self._time is None:
            return ""
        t = self._time
        if t.second:
            return f"{t.hour:02d}:{t.minute:02d}:{t.second:02d}"
        return f"{t.hour:02d}:{t.minute:02d}"

    @property
    def has_time(self) -> bool:
        """Whether this due carries a clock time (vs being date-only).

        Returns:
            True when a time component is present.
        """
        return self._time is not None

    @property
    def time(self) -> time | None:
        """Get the underlying naive time component, or None if date-only.

        Returns:
            A naive :class:`datetime.time`, or None when date-only.
        """
        return self._time

    def to_datetime(self) -> datetime:
        """Return a naive :class:`datetime` combining the date and time.

        A date-only due is combined with midnight (00:00). The result is naive
        (no timezone), consistent with the project's naive-local model.

        Returns:
            Naive datetime for this due.
        """
        return datetime.combine(self._date, self._time or time())

    def to_display(self, fmt: str = _ISO_FORMAT) -> str:
        """Format the due for display.

        Date-only formats with ``fmt`` exactly as before. When a time is
        present it is appended as `` HH:MM`` (or `` HH:MM:SS`` with non-zero
        seconds), space-separated, so date-only display is 100% unchanged and
        time-bearing display shows the clock time.

        Args:
            fmt: strftime format string for the date part. Defaults to
                YYYY-MM-DD.

        Returns:
            Formatted display string.
        """
        date_text = self._date.strftime(fmt)
        if self._time is None:
            return date_text
        return f"{date_text} {self._format_time()}"

    def is_overdue(self) -> bool:
        """Check whether this due is in the past.

        Date-only: overdue once the day has fully passed (``date < today``),
        unchanged from before -- a task due today is NOT overdue.

        Time-bearing: overdue once the specific naive-local instant has passed
        (``datetime < now``), so a task due today at 16:00 becomes overdue at
        16:00 local, not at midnight.

        Returns:
            True if the due is in the past, False otherwise.
        """
        if self._time is None:
            return self._date < date.today()
        # datetime.now() is naive local by design (project-wide DTZ convention).
        return self.to_datetime() < datetime.now()

    def is_due_soon(self, days: int = 7) -> bool:
        """Check if this date is within the specified number of days.

        Args:
            days: Number of days to check. Defaults to 7.

        Returns:
            True if date is today or within the next N days.
        """
        today = date.today()
        return today <= self._date <= today + timedelta(days=days)

    def is_before(self, other: DateLike) -> bool:
        """Check if this date is before another date.

        Args:
            other: Date to compare against.

        Returns:
            True if this date is before other, False if other is None or
            this date is on or after other.
        """
        other_d = DotoDate.parse_safe(other)
        if other_d is None:
            return False
        return self._date < other_d._date

    def is_after(self, other: DateLike) -> bool:
        """Check if this date is after another date.

        Args:
            other: Date to compare against.

        Returns:
            True if this date is after other, False if other is None or
            this date is on or before other.
        """
        other_d = DotoDate.parse_safe(other)
        if other_d is None:
            return False
        return self._date > other_d._date

    def is_on_or_before(self, other: DateLike) -> bool:
        """Check if this date is on or before another date.

        Args:
            other: Date to compare against.

        Returns:
            True if this date is on or before other.
        """
        other_d = DotoDate.parse_safe(other)
        if other_d is None:
            return False
        return self._date <= other_d._date

    def is_on_or_after(self, other: DateLike) -> bool:
        """Check if this date is on or after another date.

        Args:
            other: Date to compare against.

        Returns:
            True if this date is on or after other.
        """
        other_d = DotoDate.parse_safe(other)
        if other_d is None:
            return False
        return self._date >= other_d._date

    def days_until(self) -> int:
        """Return the number of days until this date from today.

        Returns:
            Positive number if date is in future, negative if in past, 0 if today.
        """
        return (self._date - date.today()).days

    def add_days(self, days: int) -> DotoDate:
        """Return a new DotoDate with days added.

        Args:
            days: Number of days to add (can be negative).

        Returns:
            New DotoDate instance.
        """
        return DotoDate(self._date + timedelta(days=days))

    @property
    def date(self) -> date:
        """Get the underlying date object.

        Returns:
            Python date object.
        """
        return self._date

    def __str__(self) -> str:
        """Return ISO format string representation."""
        return self.isoformat()

    def __repr__(self) -> str:
        """Return detailed string representation."""
        return f"DotoDate({self.isoformat()!r})"

    def __eq__(self, other: object) -> bool:
        """Check equality with another date-like value."""
        if isinstance(other, DotoDate):
            return self._date == other._date
        if isinstance(other, date) and not isinstance(other, datetime):
            return self._date == other
        if isinstance(other, str):
            other_d = DotoDate.parse_safe(other)
            return other_d is not None and self._date == other_d._date
        return NotImplemented

    def __lt__(self, other: object) -> bool:
        """Check if this date is less than another."""
        if isinstance(other, DotoDate):
            return self._date < other._date
        if isinstance(other, date) and not isinstance(other, datetime):
            return self._date < other
        if isinstance(other, str):
            other_d = DotoDate.parse_safe(other)
            return other_d is not None and self._date < other_d._date
        return NotImplemented

    def __le__(self, other: object) -> bool:
        """Check if this date is less than or equal to another."""
        return self == other or self < other

    def __gt__(self, other: object) -> bool:
        """Check if this date is greater than another."""
        if isinstance(other, DotoDate):
            return self._date > other._date
        if isinstance(other, date) and not isinstance(other, datetime):
            return self._date > other
        if isinstance(other, str):
            other_d = DotoDate.parse_safe(other)
            return other_d is not None and self._date > other_d._date
        return NotImplemented

    def __ge__(self, other: object) -> bool:
        """Check if this date is greater than or equal to another."""
        return self == other or self > other

    def __hash__(self) -> int:
        """Return hash of the date."""
        return hash(self._date)


# --- Module-level convenience functions (thin wrappers) ---


def parse_date(value: DateLike) -> DotoDate | None:
    """Parse a date value, raising ValueError for invalid strings.

    Args:
        value: Date-like value to parse.

    Returns:
        DotoDate instance or None if value is None/empty.

    Raises:
        ValueError: If string is not valid ISO format.
    """
    return DotoDate.parse(value)


def parse_date_safe(value: DateLike) -> DotoDate | None:
    """Parse a date value, returning None for invalid/missing input.

    Args:
        value: Date-like value to parse.

    Returns:
        DotoDate instance or None if value is None, empty, or invalid.
    """
    return DotoDate.parse_safe(value)


def format_date_display(value: DateLike, fmt: str = _ISO_FORMAT) -> str:
    """Format a date for display, returning '' for None.

    Args:
        value: Date-like value to format.
        fmt: strftime format string. Defaults to YYYY-MM-DD.

    Returns:
        Formatted date string, or empty string if value is None/invalid.
    """
    d = DotoDate.parse_safe(value)
    return d.to_display(fmt) if d else ""


def normalize_date(value: DateLike) -> str | None:
    """Normalize a date to ISO string or None.

    Args:
        value: Date-like value to normalize.

    Returns:
        ISO format string or None.

    Raises:
        ValueError: If string is not valid ISO format.
    """
    d = DotoDate.parse(value)
    return d.isoformat() if d else None


def is_overdue(value: DateLike) -> bool:
    """Check if a date is in the past.

    Args:
        value: Date-like value to check.

    Returns:
        True if date is before today, False if None or on/after today.
    """
    d = DotoDate.parse_safe(value)
    return d.is_overdue() if d else False


def is_due_soon(value: DateLike, days: int = 7) -> bool:
    """Check if a date is within the specified number of days from today.

    Args:
        value: Date-like value to check.
        days: Number of days to check. Defaults to 7.

    Returns:
        True if date is today or within the next N days.
    """
    d = DotoDate.parse_safe(value)
    return d.is_due_soon(days) if d else False
