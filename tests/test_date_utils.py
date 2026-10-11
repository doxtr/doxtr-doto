"""Tests for the date_utils module.

This module tests the DotoDate class and module-level convenience functions
that provide consolidated date handling for the doxtr_doto extension.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from doxtr_doto.date_utils import (
    DotoDate,
    format_date_display,
    is_due_soon,
    is_overdue,
    normalize_date,
    parse_date,
    parse_date_safe,
)


class TestDotoDateParsing:
    """Tests for DotoDate parsing functionality."""

    def test_parse_none_returns_none(self):
        """Parsing None should return None."""
        assert DotoDate.parse(None) is None

    def test_parse_empty_string_returns_none(self):
        """Parsing empty string should return None."""
        assert DotoDate.parse("") is None
        assert DotoDate.parse("   ") is None

    def test_parse_iso_string(self):
        """Parsing ISO format string should work."""
        result = DotoDate.parse("2024-08-15")
        assert result is not None
        assert result.isoformat() == "2024-08-15"

    def test_parse_iso_string_with_whitespace(self):
        """Parsing ISO string with whitespace should trim it."""
        result = DotoDate.parse("  2024-08-15  ")
        assert result is not None
        assert result.isoformat() == "2024-08-15"

    def test_parse_date_object(self):
        """Parsing a date object should wrap it."""
        d = date(2024, 8, 15)
        result = DotoDate.parse(d)
        assert result is not None
        assert result.date == d

    def test_parse_datetime_object(self):
        """Parsing a datetime object should extract the date."""
        dt = datetime(2024, 8, 15, 10, 30, 45)
        result = DotoDate.parse(dt)
        assert result is not None
        assert result.date == date(2024, 8, 15)

    def test_parse_dotodate_returns_same(self):
        """Parsing a DotoDate should return the same instance."""
        original = DotoDate.parse("2024-08-15")
        result = DotoDate.parse(original)
        assert result is original

    def test_parse_invalid_string_raises(self):
        """Parsing invalid string should raise ValueError."""
        with pytest.raises(ValueError):
            DotoDate.parse("not-a-date")

    def test_parse_invalid_type_raises(self):
        """Parsing unsupported type should raise TypeError."""
        with pytest.raises(TypeError):
            DotoDate.parse(12345)  # type: ignore

    def test_parse_safe_invalid_returns_none(self):
        """parse_safe should return None for invalid input."""
        assert DotoDate.parse_safe("not-a-date") is None
        assert DotoDate.parse_safe(12345) is None  # type: ignore

    def test_parse_safe_valid_returns_dotodate(self):
        """parse_safe should return DotoDate for valid input."""
        result = DotoDate.parse_safe("2024-08-15")
        assert result is not None
        assert result.isoformat() == "2024-08-15"


class TestDotoDateConstruction:
    """Tests for DotoDate direct construction."""

    def test_init_with_date(self):
        """Direct construction with date object should work."""
        d = date(2024, 8, 15)
        doto_date = DotoDate(d)
        assert doto_date.date == d

    def test_init_with_datetime_raises(self):
        """Direct construction with datetime should raise TypeError."""
        dt = datetime(2024, 8, 15, 10, 30)
        with pytest.raises(TypeError):
            DotoDate(dt)  # type: ignore

    def test_init_with_string_raises(self):
        """Direct construction with string should raise TypeError."""
        with pytest.raises(TypeError):
            DotoDate("2024-08-15")  # type: ignore

    def test_today_class_method(self):
        """DotoDate.today() should return today's date."""
        result = DotoDate.today()
        assert result.date == date.today()


class TestDotoDateFormatting:
    """Tests for DotoDate formatting methods."""

    def test_isoformat(self):
        """isoformat should return YYYY-MM-DD string."""
        d = DotoDate.parse("2024-08-15")
        assert d.isoformat() == "2024-08-15"

    def test_to_display_default_format(self):
        """to_display with default format should return ISO format."""
        d = DotoDate.parse("2024-08-15")
        assert d.to_display() == "2024-08-15"

    def test_to_display_custom_format(self):
        """to_display with custom format should work."""
        d = DotoDate.parse("2024-08-15")
        assert d.to_display("%b %d, %Y") == "Aug 15, 2024"
        assert d.to_display("%m/%d/%Y") == "08/15/2024"

    def test_str(self):
        """str() should return ISO format."""
        d = DotoDate.parse("2024-08-15")
        assert str(d) == "2024-08-15"

    def test_repr(self):
        """repr() should return detailed representation."""
        d = DotoDate.parse("2024-08-15")
        assert repr(d) == "DotoDate('2024-08-15')"


class TestDotoDateComparison:
    """Tests for DotoDate comparison methods."""

    def test_is_before_dotodate(self):
        """is_before should work with DotoDate."""
        d1 = DotoDate.parse("2024-08-15")
        d2 = DotoDate.parse("2024-08-20")
        assert d1.is_before(d2)
        assert not d2.is_before(d1)

    def test_is_before_date(self):
        """is_before should work with date object."""
        d1 = DotoDate.parse("2024-08-15")
        assert d1.is_before(date(2024, 8, 20))
        assert not d1.is_before(date(2024, 8, 10))

    def test_is_before_string(self):
        """is_before should work with ISO string."""
        d1 = DotoDate.parse("2024-08-15")
        assert d1.is_before("2024-08-20")
        assert not d1.is_before("2024-08-10")

    def test_is_before_none_returns_false(self):
        """is_before with None should return False."""
        d1 = DotoDate.parse("2024-08-15")
        assert not d1.is_before(None)

    def test_is_after_dotodate(self):
        """is_after should work with DotoDate."""
        d1 = DotoDate.parse("2024-08-20")
        d2 = DotoDate.parse("2024-08-15")
        assert d1.is_after(d2)
        assert not d2.is_after(d1)

    def test_is_after_none_returns_false(self):
        """is_after with None should return False."""
        d1 = DotoDate.parse("2024-08-15")
        assert not d1.is_after(None)

    def test_is_on_or_before(self):
        """is_on_or_before should work correctly."""
        d1 = DotoDate.parse("2024-08-15")
        assert d1.is_on_or_before("2024-08-15")  # Same date
        assert d1.is_on_or_before("2024-08-20")  # Before
        assert not d1.is_on_or_before("2024-08-10")  # After

    def test_is_on_or_after(self):
        """is_on_or_after should work correctly."""
        d1 = DotoDate.parse("2024-08-15")
        assert d1.is_on_or_after("2024-08-15")  # Same date
        assert d1.is_on_or_after("2024-08-10")  # After
        assert not d1.is_on_or_after("2024-08-20")  # Before


class TestDotoDateOverdue:
    """Tests for DotoDate overdue checking."""

    def test_is_overdue_past_date(self):
        """Past date should be overdue."""
        past = date.today() - timedelta(days=5)
        d = DotoDate(past)
        assert d.is_overdue()

    def test_is_overdue_today_not_overdue(self):
        """Today's date should not be overdue."""
        d = DotoDate.today()
        assert not d.is_overdue()

    def test_is_overdue_future_not_overdue(self):
        """Future date should not be overdue."""
        future = date.today() + timedelta(days=5)
        d = DotoDate(future)
        assert not d.is_overdue()


class TestDotoDateDueSoon:
    """Tests for DotoDate due soon checking."""

    def test_is_due_soon_today(self):
        """Today should be due soon."""
        d = DotoDate.today()
        assert d.is_due_soon()

    def test_is_due_soon_within_7_days(self):
        """Date within 7 days should be due soon."""
        future = date.today() + timedelta(days=5)
        d = DotoDate(future)
        assert d.is_due_soon()

    def test_is_due_soon_exactly_7_days(self):
        """Date exactly 7 days away should be due soon."""
        future = date.today() + timedelta(days=7)
        d = DotoDate(future)
        assert d.is_due_soon()

    def test_is_due_soon_beyond_7_days(self):
        """Date beyond 7 days should not be due soon."""
        future = date.today() + timedelta(days=8)
        d = DotoDate(future)
        assert not d.is_due_soon()

    def test_is_due_soon_custom_days(self):
        """is_due_soon with custom days parameter."""
        future = date.today() + timedelta(days=3)
        d = DotoDate(future)
        assert d.is_due_soon(days=3)
        assert d.is_due_soon(days=5)
        assert not d.is_due_soon(days=2)

    def test_is_due_soon_past_date(self):
        """Past date should not be due soon."""
        past = date.today() - timedelta(days=1)
        d = DotoDate(past)
        assert not d.is_due_soon()


class TestDotoDateDaysUntil:
    """Tests for DotoDate days_until method."""

    def test_days_until_future(self):
        """days_until for future date should be positive."""
        future = date.today() + timedelta(days=5)
        d = DotoDate(future)
        assert d.days_until() == 5

    def test_days_until_past(self):
        """days_until for past date should be negative."""
        past = date.today() - timedelta(days=3)
        d = DotoDate(past)
        assert d.days_until() == -3

    def test_days_until_today(self):
        """days_until for today should be 0."""
        d = DotoDate.today()
        assert d.days_until() == 0


class TestDotoDateAddDays:
    """Tests for DotoDate add_days method."""

    def test_add_days_positive(self):
        """add_days with positive number."""
        d = DotoDate.parse("2024-08-15")
        result = d.add_days(5)
        assert result.isoformat() == "2024-08-20"

    def test_add_days_negative(self):
        """add_days with negative number."""
        d = DotoDate.parse("2024-08-15")
        result = d.add_days(-5)
        assert result.isoformat() == "2024-08-10"

    def test_add_days_returns_new_instance(self):
        """add_days should return a new instance."""
        d = DotoDate.parse("2024-08-15")
        result = d.add_days(5)
        assert result is not d


class TestDotoDateOperators:
    """Tests for DotoDate comparison operators."""

    def test_eq_dotodate(self):
        """Equality with another DotoDate."""
        d1 = DotoDate.parse("2024-08-15")
        d2 = DotoDate.parse("2024-08-15")
        d3 = DotoDate.parse("2024-08-20")
        assert d1 == d2
        assert not d1 == d3

    def test_eq_date(self):
        """Equality with date object."""
        d = DotoDate.parse("2024-08-15")
        assert d == date(2024, 8, 15)
        assert not d == date(2024, 8, 20)

    def test_eq_string(self):
        """Equality with ISO string."""
        d = DotoDate.parse("2024-08-15")
        assert d == "2024-08-15"
        assert not d == "2024-08-20"

    def test_lt_dotodate(self):
        """Less than with another DotoDate."""
        d1 = DotoDate.parse("2024-08-15")
        d2 = DotoDate.parse("2024-08-20")
        assert d1 < d2
        assert not d2 < d1

    def test_lt_date(self):
        """Less than with date object."""
        d = DotoDate.parse("2024-08-15")
        assert d < date(2024, 8, 20)
        assert not d < date(2024, 8, 10)

    def test_le(self):
        """Less than or equal."""
        d1 = DotoDate.parse("2024-08-15")
        d2 = DotoDate.parse("2024-08-15")
        d3 = DotoDate.parse("2024-08-20")
        assert d1 <= d2
        assert d1 <= d3
        assert not d3 <= d1

    def test_gt_dotodate(self):
        """Greater than with another DotoDate."""
        d1 = DotoDate.parse("2024-08-20")
        d2 = DotoDate.parse("2024-08-15")
        assert d1 > d2
        assert not d2 > d1

    def test_ge(self):
        """Greater than or equal."""
        d1 = DotoDate.parse("2024-08-20")
        d2 = DotoDate.parse("2024-08-20")
        d3 = DotoDate.parse("2024-08-15")
        assert d1 >= d2
        assert d1 >= d3
        assert not d3 >= d1

    def test_hash(self):
        """DotoDate should be hashable."""
        d1 = DotoDate.parse("2024-08-15")
        d2 = DotoDate.parse("2024-08-15")
        assert hash(d1) == hash(d2)
        # Should work in sets/dicts
        s = {d1}
        assert d2 in s


class TestModuleFunctions:
    """Tests for module-level convenience functions."""

    def test_parse_date_valid(self):
        """parse_date with valid input."""
        result = parse_date("2024-08-15")
        assert result is not None
        assert result.isoformat() == "2024-08-15"

    def test_parse_date_none(self):
        """parse_date with None."""
        assert parse_date(None) is None

    def test_parse_date_invalid_raises(self):
        """parse_date with invalid input should raise."""
        with pytest.raises(ValueError):
            parse_date("not-a-date")

    def test_parse_date_safe_valid(self):
        """parse_date_safe with valid input."""
        result = parse_date_safe("2024-08-15")
        assert result is not None
        assert result.isoformat() == "2024-08-15"

    def test_parse_date_safe_invalid(self):
        """parse_date_safe with invalid input returns None."""
        assert parse_date_safe("not-a-date") is None

    def test_format_date_display_valid(self):
        """format_date_display with valid input."""
        assert format_date_display("2024-08-15") == "2024-08-15"
        assert format_date_display("2024-08-15", "%b %d, %Y") == "Aug 15, 2024"

    def test_format_date_display_none(self):
        """format_date_display with None returns empty string."""
        assert format_date_display(None) == ""

    def test_format_date_display_invalid(self):
        """format_date_display with invalid input returns empty string."""
        assert format_date_display("not-a-date") == ""

    def test_normalize_date_valid(self):
        """normalize_date with valid input."""
        assert normalize_date("2024-08-15") == "2024-08-15"
        assert normalize_date(date(2024, 8, 15)) == "2024-08-15"
        assert normalize_date(datetime(2024, 8, 15, 10, 30)) == "2024-08-15"

    def test_normalize_date_none(self):
        """normalize_date with None."""
        assert normalize_date(None) is None

    def test_normalize_date_invalid_raises(self):
        """normalize_date with invalid input should raise."""
        with pytest.raises(ValueError):
            normalize_date("not-a-date")

    def test_is_overdue_function(self):
        """is_overdue module function."""
        past = (date.today() - timedelta(days=5)).isoformat()
        future = (date.today() + timedelta(days=5)).isoformat()
        assert is_overdue(past)
        assert not is_overdue(future)
        assert not is_overdue(None)

    def test_is_due_soon_function(self):
        """is_due_soon module function."""
        soon = (date.today() + timedelta(days=3)).isoformat()
        far = (date.today() + timedelta(days=30)).isoformat()
        assert is_due_soon(soon)
        assert not is_due_soon(far)
        assert not is_due_soon(None)


class TestDotoDateIntegration:
    """Integration tests for DotoDate with other parts of the codebase."""

    def test_dotodate_in_filter_comparison(self):
        """DotoDate should work in filter comparisons."""
        task_due = DotoDate.parse("2024-08-15")
        filter_date = DotoDate.parse("2024-08-20")

        # This mirrors the filter_tasks logic
        assert task_due.is_before(filter_date)
        assert not task_due.is_after(filter_date)

    def test_dotodate_date_property(self):
        """The date property should return the underlying date."""
        d = DotoDate.parse("2024-08-15")
        assert d.date == date(2024, 8, 15)
        assert isinstance(d.date, date)


class TestBackwardCompatibility:
    """Tests ensuring backward compatibility with existing code."""

    def test_utils_parse_date_returns_date(self):
        """utils.parse_date should still return a date object."""
        from doxtr_doto.utils import parse_date as utils_parse_date

        result = utils_parse_date("2024-08-15")
        # utils.parse_date returns the underlying date for backward compat
        assert isinstance(result, date)
        assert result == date(2024, 8, 15)

    def test_utils_parse_date_safe_returns_date(self):
        """utils.parse_date_safe should still return a date object."""
        from doxtr_doto.utils import parse_date_safe as utils_parse_date_safe

        result = utils_parse_date_safe("2024-08-15")
        # utils.parse_date_safe returns the underlying date for backward compat
        assert isinstance(result, date)
        assert result == date(2024, 8, 15)

    def test_utils_normalize_date_returns_string(self):
        """utils.normalize_date should return ISO string."""
        from doxtr_doto.utils import normalize_date as utils_normalize_date

        result = utils_normalize_date("2024-08-15")
        assert result == "2024-08-15"
        assert isinstance(result, str)

    def test_utils_format_date_display_returns_string(self):
        """utils.format_date_display should return formatted string."""
        from doxtr_doto.utils import format_date_display as utils_format

        result = utils_format("2024-08-15")
        assert result == "2024-08-15"
        assert isinstance(result, str)


class TestDotoDateTime:
    """Tests for optional naive-local time on a due value.

    A due may carry a clock time appended to the YYYY-MM-DD date. These tests
    cover parsing the accepted syntaxes, backward-compatible date-only
    behavior, display/serialization, and overdue semantics.
    """

    def test_date_only_has_no_time(self):
        """A plain date parses with no time component (unchanged behavior)."""
        d = DotoDate.parse("2026-08-15")
        assert d is not None
        assert d.has_time is False
        assert d.time is None
        assert d.isoformat() == "2026-08-15"

    def test_parse_hh_mm(self):
        """HH:MM time is parsed and preserved."""
        d = DotoDate.parse("2026-08-15 16:00")
        assert d is not None
        assert d.has_time is True
        assert d.isoformat() == "2026-08-15T16:00"

    def test_parse_hour_shorthand(self):
        """The HHh shorthand expands to HH:00."""
        d = DotoDate.parse("2026-08-15 16h")
        assert d is not None
        assert d.has_time is True
        assert d.isoformat() == "2026-08-15T16:00"

    def test_parse_hh_mm_ss(self):
        """HH:MM:SS time keeps its seconds."""
        d = DotoDate.parse("2026-08-15 16:00:31")
        assert d is not None
        assert d.has_time is True
        assert d.isoformat() == "2026-08-15T16:00:31"

    def test_t_separator_accepted(self):
        """An ISO 'T' separator is accepted equivalently to a space."""
        space = DotoDate.parse("2026-08-15 16:00")
        tsep = DotoDate.parse("2026-08-15T16:00")
        assert space is not None and tsep is not None
        assert space.isoformat() == tsep.isoformat()

    def test_seconds_dropped_when_zero(self):
        """Zero seconds are not emitted, so 16:00:00 round-trips as 16:00."""
        d = DotoDate.parse("2026-08-15T16:00:00")
        assert d is not None
        assert d.isoformat() == "2026-08-15T16:00"

    def test_isoformat_roundtrip(self):
        """isoformat output re-parses to an equal canonical form."""
        for raw in ("2026-08-15", "2026-08-15T16:00", "2026-08-15T16:00:31"):
            first = DotoDate.parse(raw)
            assert first is not None
            second = DotoDate.parse(first.isoformat())
            assert second is not None
            assert second.isoformat() == first.isoformat()

    def test_display_date_only_unchanged(self):
        """Date-only display is identical to before (no trailing time)."""
        d = DotoDate.parse("2026-08-15")
        assert d is not None
        assert d.to_display() == "2026-08-15"

    def test_display_with_time(self):
        """A time-bearing due displays with a space-separated clock time."""
        d = DotoDate.parse("2026-08-15 16:00")
        assert d is not None
        assert d.to_display() == "2026-08-15 16:00"

    def test_display_with_time_and_custom_date_format(self):
        """Custom date format applies to the date; the time is appended."""
        d = DotoDate.parse("2026-08-15 16:00:31")
        assert d is not None
        assert d.to_display("%b %d, %Y") == "Aug 15, 2026 16:00:31"

    def test_to_datetime_combines_time(self):
        """to_datetime combines date+time (midnight when date-only)."""
        from datetime import datetime

        timed = DotoDate.parse("2026-08-15 16:00")
        assert timed is not None
        assert timed.to_datetime() == datetime(2026, 8, 15, 16, 0)

        date_only = DotoDate.parse("2026-08-15")
        assert date_only is not None
        assert date_only.to_datetime() == datetime(2026, 8, 15, 0, 0)

    @pytest.mark.parametrize("bad", ["16:99", "25:00", "16:", "ab:cd", "16:00:99"])
    def test_invalid_times_rejected(self, bad):
        """Out-of-range or malformed times raise a clear ValueError."""
        with pytest.raises(ValueError):
            DotoDate.parse(f"2026-08-15 {bad}")

    def test_parse_safe_returns_none_on_bad_time(self):
        """parse_safe swallows a bad time and returns None."""
        assert DotoDate.parse_safe("2026-08-15 25:00") is None

    def test_normalize_date_preserves_time(self):
        """normalize_date keeps a time-bearing due as canonical ISO."""
        assert normalize_date("2026-08-15 16h") == "2026-08-15T16:00"
        assert normalize_date("2026-08-15") == "2026-08-15"

    def test_format_date_display_with_time(self):
        """The module helper formats a time-bearing due for display."""
        assert format_date_display("2026-08-15 16:00") == "2026-08-15 16:00"
        assert format_date_display("2026-08-15") == "2026-08-15"

    def test_overdue_date_only_today_not_overdue(self):
        """A date-only due of today is NOT overdue (unchanged semantics)."""
        today = date.today()
        d = DotoDate.parse(today.isoformat())
        assert d is not None
        assert d.is_overdue() is False

    def test_overdue_time_in_past_is_overdue(self):
        """A today due at a past clock time is overdue at that instant."""
        d = DotoDate.parse(f"{date.today().isoformat()} 00:00")
        assert d is not None
        # 00:00 today is already in the past at any later point in the day.
        assert d.is_overdue() is True

    def test_overdue_time_in_future_not_overdue(self):
        """A today due at 23:59 is not overdue until that instant passes."""
        d = DotoDate.parse(f"{date.today().isoformat()} 23:59")
        assert d is not None
        assert d.is_overdue() is False

    def test_comparison_uses_calendar_day(self):
        """Comparisons/equality are day-level (time ignored for ordering)."""
        a = DotoDate.parse("2026-08-15 09:00")
        b = DotoDate.parse("2026-08-15 17:00")
        assert a is not None and b is not None
        assert a == b
        assert not (a < b)
