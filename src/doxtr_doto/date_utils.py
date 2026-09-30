"""Date handling utilities for doxtr_doto.

Single source of truth for date parsing, formatting, and comparison.
All other modules should import from here instead of using direct
date.fromisoformat() calls.

This module provides:
- DotoDate: Immutable wrapper for consistent date handling
- Module-level convenience functions that delegate to DotoDate
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Union


DateLike = Union[str, date, datetime, "DotoDate", None]

_ISO_FORMAT = "%Y-%m-%d"


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
    """

    __slots__ = ("_date",)

    def __init__(self, value: date) -> None:
        """Initialize with a date object.

        Use DotoDate.parse() for flexible input types.

        Args:
            value: A date object (not datetime, not string).

        Raises:
            TypeError: If value is not a date object.
        """
        if not isinstance(value, date) or isinstance(value, datetime):
            raise TypeError(f"Expected date, got {type(value).__name__}")
        self._date = value

    @classmethod
    def parse(cls, value: DateLike) -> "DotoDate | None":
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
            return cls(value.date())
        if isinstance(value, date):
            return cls(value)
        if isinstance(value, str):
            v = value.strip()
            if not v:
                return None
            # Parse ISO format and create DotoDate
            parsed = date.fromisoformat(v)
            return cls(parsed)
        raise TypeError(f"Cannot parse date from {type(value).__name__}")

    @classmethod
    def parse_safe(cls, value: DateLike) -> "DotoDate | None":
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
    def today(cls) -> "DotoDate":
        """Return today's date as a DotoDate.

        Returns:
            DotoDate for today.
        """
        return cls(date.today())

    def isoformat(self) -> str:
        """Return date in ISO format (YYYY-MM-DD).

        Returns:
            ISO format string.
        """
        return self._date.isoformat()

    def to_display(self, fmt: str = _ISO_FORMAT) -> str:
        """Format date for display.

        Args:
            fmt: strftime format string. Defaults to YYYY-MM-DD.

        Returns:
            Formatted date string.
        """
        return self._date.strftime(fmt)

    def is_overdue(self) -> bool:
        """Check if this date is in the past (before today).

        Returns:
            True if date is before today, False otherwise.
        """
        return self._date < date.today()

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

    def add_days(self, days: int) -> "DotoDate":
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
