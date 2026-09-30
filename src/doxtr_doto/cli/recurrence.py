"""Recurrence pattern parsing and date generation for recurring tasks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from typing import Iterator


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
    """Parsed recurrence pattern."""
    
    type: RecurrenceType
    interval: int = 1  # every N days/weeks/months
    weekday: int | None = None  # 0-6 for weekly patterns
    day_of_month: int | None = None  # 1-31 for monthly patterns
    weekday_position: WeekdayPosition | None = None  # first/last/etc for monthly weekday patterns
    
    def to_dict(self) -> dict:
        """Serialize to dictionary for JSON storage."""
        return {
            "type": self.type.value,
            "interval": self.interval,
            "weekday": self.weekday,
            "day_of_month": self.day_of_month,
            "weekday_position": self.weekday_position.value if self.weekday_position else None,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "RecurrencePattern":
        """Deserialize from dictionary."""
        return cls(
            type=RecurrenceType(data["type"]),
            interval=data.get("interval", 1),
            weekday=data.get("weekday"),
            day_of_month=data.get("day_of_month"),
            weekday_position=WeekdayPosition(data["weekday_position"]) if data.get("weekday_position") else None,
        )
    
    def describe(self) -> str:
        """Return human-readable description of the pattern."""
        if self.type == RecurrenceType.DAILY:
            if self.interval == 1:
                return "every day"
            return f"every {self.interval} days"
        
        if self.type == RecurrenceType.WEEKLY:
            weekday_name = WEEKDAY_NAMES.get(self.weekday, "day")
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
                return f"every {self.interval} months on {self.weekday_position.value} {weekday_name}"
        
        return "unknown pattern"


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
    
    Args:
        pattern_str: Pattern string to parse.
        
    Returns:
        Parsed RecurrencePattern.
        
    Raises:
        ValueError: If pattern cannot be parsed.
    """
    pattern_str = pattern_str.strip().lower()
    
    # Remove leading "every" if present
    if pattern_str.startswith("every "):
        pattern_str = pattern_str[6:].strip()
    
    # Normalize multiple spaces to single space
    pattern_str = re.sub(r'\s+', ' ', pattern_str)
    
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
        pattern_str
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


def _nth_weekday_of_month(year: int, month: int, weekday: int, position: WeekdayPosition) -> date | None:
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
                occurrence = date(year, month, day)
            elif pattern.weekday is not None and pattern.weekday_position:
                # Nth weekday of month
                occurrence = _nth_weekday_of_month(year, month, pattern.weekday, pattern.weekday_position)
                if occurrence is None:
                    # Skip this month (e.g., no 5th Friday)
                    year, month = (year, month + 1) if month < 12 else (year + 1, 1)
                    continue
            else:
                break
            
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
