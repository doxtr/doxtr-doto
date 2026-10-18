"""Tests for iCalendar serialization and content hashing (ical.py)."""

from __future__ import annotations

from datetime import datetime

from doxtr_doto.calsync.engine import _strip_back_reference, inbound_map
from doxtr_doto.calsync.ical import (
    content_hash,
    event_to_ical,
    inbound_hash_of_pushed,
    remote_content_hash,
)
from doxtr_doto.calsync.model import (
    CalendarEvent,
    EventKind,
    RemoteEvent,
    make_uid,
    project_task_to_event,
)
from doxtr_doto.cli.config import CalendarConfig


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


class TestInboundHashBaseline:
    """inbound_hash_of_pushed must match remote_content_hash of the read-back."""

    def test_pushed_timed_event_matches_read_back_remote(self):
        ev = _timed_event()
        # The server returns the pushed event verbatim (summary/body/start/end,
        # with the [doto:] marker still in the description). A real provider
        # read-back always carries the end time, so the duration is part of the
        # comparable fingerprint.
        read_back = RemoteEvent(
            uid=ev.uid,
            summary=ev.summary,
            description=ev.description,
            start=ev.start,
            end=ev.end,
            all_day=ev.all_day,
            kind=EventKind.EVENT,
        )
        assert inbound_hash_of_pushed(ev) == remote_content_hash(read_back)

    def test_pushed_all_day_event_matches_read_back_remote(self):
        ev = CalendarEvent(
            uid=make_uid("AD"),
            kind=EventKind.EVENT,
            summary="Holiday",
            description="[doto:AD]",
            start=datetime(2026, 7, 4, 0, 0),
            end=datetime(2026, 7, 5, 0, 0),
            all_day=True,
            task_id="AD",
        )
        read_back = RemoteEvent(
            uid=ev.uid,
            summary=ev.summary,
            description=ev.description,
            start=ev.start,
            all_day=True,
            kind=EventKind.EVENT,
        )
        assert inbound_hash_of_pushed(ev) == remote_content_hash(read_back)

    def test_duration_change_changes_remote_hash(self):
        """A timed event's end time is part of the inbound fingerprint.

        Regression: the remote content hash used to ignore the end time, so a
        duration-only edit (which maps onto the task estimate) was not detected
        as a remote change. Two otherwise-identical events differing only in
        end time must hash differently.
        """
        base = {
            "uid": make_uid("D"),
            "summary": "Practice",
            "description": "[doto:D]",
            "start": datetime(2026, 10, 18, 10, 45),
            "all_day": False,
            "kind": EventKind.EVENT,
        }
        short = RemoteEvent(**base, end=datetime(2026, 10, 18, 11, 15))  # 30m
        long = RemoteEvent(**base, end=datetime(2026, 10, 18, 11, 30))  # 45m
        assert remote_content_hash(short) != remote_content_hash(long)


class TestBodyRoundTrip:
    """project -> RemoteEvent -> pull-map: body has no [doto:] marker."""

    def test_back_reference_stripped_on_round_trip(self):
        cal = CalendarConfig(provider="fake", calendar="primary", event_mode="event")
        task = {"title": "Write docs", "body": "Draft the guide", "due": "2026-08-15T09:00"}
        event = project_task_to_event("T9", task, cal, back_reference="repo#T9")
        # Push appended the marker as its own paragraph.
        assert "[doto:repo#T9]" in event.description
        # Read back as a RemoteEvent (server returns the description verbatim).
        remote = RemoteEvent(
            uid=event.uid,
            summary=event.summary,
            description=event.description,
            start=event.start,
            kind=EventKind.EVENT,
        )
        fields = inbound_map(remote, cal)
        # Stripped on the inbound mapping -- no accumulating marker.
        assert fields["body"] == "Draft the guide"
        assert "[doto:" not in fields["body"]
        # And the stripper is idempotent.
        assert _strip_back_reference(fields["body"]) == "Draft the guide"


class TestStripBackReference:
    """_strip_back_reference handles newline, HTML-<br>, and inline markers."""

    def test_strips_newline_separated_marker(self):
        assert _strip_back_reference("body text\n\n[doto:x#X]") == "body text"

    def test_strips_html_br_separated_marker(self):
        # Google's web UI stores the description as HTML, so the marker comes
        # back separated by <br> tags rather than newlines (regression).
        s = "We <u>have</u> to look!<br><br>[doto:computer-basics#COMP-003]"
        assert _strip_back_reference(s) == "We <u>have</u> to look!"

    def test_strips_br_variants(self):
        for br in ("<br>", "<br/>", "<br />", "<BR>"):
            assert _strip_back_reference(f"text{br}{br}[doto:X]") == "text"

    def test_strips_inline_glued_marker(self):
        assert _strip_back_reference("body [doto:X]") == "body"

    def test_no_marker_is_preserved_verbatim(self):
        assert _strip_back_reference("just a body") == "just a body"

    def test_empty_returns_empty(self):
        assert _strip_back_reference("") == ""
        assert _strip_back_reference(None) == ""  # type: ignore[arg-type]

    def test_marker_only_body_becomes_empty(self):
        assert _strip_back_reference("[doto:X]") == ""
        assert _strip_back_reference("<br><br>[doto:X]") == ""
