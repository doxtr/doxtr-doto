"""Tests for iCalendar serialization and content hashing (ical.py)."""

from __future__ import annotations

from datetime import datetime

from doxtr_doto.calsync.ical import content_hash, event_to_ical
from doxtr_doto.calsync.model import CalendarEvent, EventKind, make_uid


def _timed_event() -> CalendarEvent:
    return CalendarEvent(
        uid=make_uid("T1"),
        kind=EventKind.EVENT,
        summary="Standup",
        description="daily [doto:demo#T1]",
        start=datetime(2026, 8, 15, 9, 0),
        end=datetime(2026, 8, 15, 9, 30),
        all_day=False,
        status="CONFIRMED",
        categories=["team"],
        task_id="T1",
    )


class TestSerialization:
    def test_vevent_round_trip_fields(self):
        ical = event_to_ical(_timed_event())
        assert b"BEGIN:VCALENDAR" in ical
        assert b"BEGIN:VEVENT" in ical
        assert b"doto-T1@doxtr-doto" in ical
        assert b"Standup" in ical
        assert b"CONFIRMED" in ical

    def test_all_day_uses_date_values(self):
        ev = CalendarEvent(
            uid=make_uid("T2"),
            kind=EventKind.EVENT,
            summary="Deadline",
            start=datetime(2026, 8, 15, 0, 0),
            end=datetime(2026, 8, 16, 0, 0),
            all_day=True,
            task_id="T2",
        )
        ical = event_to_ical(ev).decode("utf-8")
        # DATE value (no time component) for an all-day event.
        assert "DTSTART;VALUE=DATE:20260815" in ical
        assert "DTEND;VALUE=DATE:20260816" in ical

    def test_vtodo(self):
        ev = CalendarEvent(
            uid=make_uid("T3"),
            kind=EventKind.TODO,
            summary="Do it",
            due=datetime(2026, 8, 15, 9, 0),
            status="NEEDS-ACTION",
            task_id="T3",
        )
        ical = event_to_ical(ev)
        assert b"BEGIN:VTODO" in ical
        assert b"NEEDS-ACTION" in ical


class TestContentHash:
    def test_hash_is_stable_across_calls(self):
        assert content_hash(_timed_event()) == content_hash(_timed_event())

    def test_hash_changes_with_summary(self):
        a = _timed_event()
        b = _timed_event()
        b.summary = "Changed"
        assert content_hash(a) != content_hash(b)

    def test_hash_changes_with_time(self):
        a = _timed_event()
        b = _timed_event()
        b.start = datetime(2026, 8, 15, 10, 0)
        assert content_hash(a) != content_hash(b)

    def test_hash_ignores_category_order(self):
        a = _timed_event()
        a.categories = ["x", "y"]
        b = _timed_event()
        b.categories = ["y", "x"]
        assert content_hash(a) == content_hash(b)
