"""Tests for the CalDAV provider using a mocked ``caldav`` library.

These validate calendar resolution, create/update/delete calls, and auth error
handling without any network. The ``caldav`` module is replaced with a stub.
"""

from __future__ import annotations

import sys
import types

import pytest

from doxtr_doto.calsync.model import CalendarEvent, EventKind, make_uid
from doxtr_doto.calsync.providers.base import ProviderAuthError, ProviderError
from doxtr_doto.calsync.providers.caldav import CalDAVProvider
from doxtr_doto.cli.config import CalendarConfig


class _FakeObj:
    def __init__(self, url="https://dav/obj/1", etag="et1"):
        self.url = url
        self.etag = etag
        self.deleted = False

    def delete(self):
        self.deleted = True


class _FakeCalendar:
    def __init__(self, name="work"):
        self._name = name
        self.saved: list[str] = []
        self.last_obj = _FakeObj()

    def get_display_name(self):
        return self._name

    def save_event(self, ical):
        self.saved.append(ical)
        return self.last_obj

    def object_by_uid(self, uid):
        return self.last_obj

    def event_by_url(self, url):
        return self.last_obj


class _FakePrincipal:
    def __init__(self, calendars, named=None):
        self._calendars = calendars
        self._named = named or {}

    def calendars(self):
        return self._calendars

    def calendar(self, cal_url=None):
        return self._named.get(cal_url, self._calendars[0])


def _install_fake_caldav(monkeypatch, principal, record=None):
    """Install a stub ``caldav`` module into sys.modules."""
    mod = types.ModuleType("caldav")

    def DAVClient(url=None, username=None, password=None, **kw):
        if record is not None:
            record["url"] = url
            record["username"] = username
            record["password"] = password

        class _Client:
            def principal(self_inner):
                return principal

        return _Client()

    mod.DAVClient = DAVClient
    monkeypatch.setitem(sys.modules, "caldav", mod)
    return mod


def _event():
    return CalendarEvent(
        uid=make_uid("T1"),
        kind=EventKind.EVENT,
        summary="x",
        task_id="T1",
    )


class TestConnect:
    def test_missing_credentials_raises(self):
        cfg = CalendarConfig(provider="caldav", url="https://dav/")
        prov = CalDAVProvider(cfg)
        with pytest.raises(ProviderAuthError, match="username"):
            prov.connect()

    def test_apple_default_url(self, monkeypatch):
        cal = _FakeCalendar()
        principal = _FakePrincipal([cal])
        record: dict = {}
        _install_fake_caldav(monkeypatch, principal, record)
        cfg = CalendarConfig(provider="apple", username="a@me.com", password="pw")
        prov = CalDAVProvider(cfg)
        prov.connect()
        assert record["url"] == "https://caldav.icloud.com/"

    def test_resolve_calendar_by_name(self, monkeypatch):
        work = _FakeCalendar("work")
        home = _FakeCalendar("home")
        principal = _FakePrincipal([home, work])
        _install_fake_caldav(monkeypatch, principal)
        cfg = CalendarConfig(
            provider="caldav",
            url="https://dav/",
            username="u",
            password="p",
            calendar="work",
        )
        prov = CalDAVProvider(cfg)
        prov.connect()
        assert prov._calendar.get_display_name() == "work"

    def test_resolve_calendar_name_not_found(self, monkeypatch):
        principal = _FakePrincipal([_FakeCalendar("home")])
        _install_fake_caldav(monkeypatch, principal)
        cfg = CalendarConfig(
            provider="caldav",
            url="https://dav/",
            username="u",
            password="p",
            calendar="nope",
        )
        prov = CalDAVProvider(cfg)
        with pytest.raises(ProviderError, match="No CalDAV calendar named"):
            prov.connect()

    def test_empty_calendar_uses_first(self, monkeypatch):
        first = _FakeCalendar("first")
        principal = _FakePrincipal([first, _FakeCalendar("second")])
        _install_fake_caldav(monkeypatch, principal)
        cfg = CalendarConfig(provider="caldav", url="https://dav/", username="u", password="p")
        prov = CalDAVProvider(cfg)
        prov.connect()
        assert prov._calendar is first


class TestOperations:
    def _connected(self, monkeypatch):
        cal = _FakeCalendar("work")
        principal = _FakePrincipal([cal])
        _install_fake_caldav(monkeypatch, principal)
        cfg = CalendarConfig(
            provider="caldav",
            url="https://dav/",
            username="u",
            password="p",
            calendar="work",
        )
        prov = CalDAVProvider(cfg)
        prov.connect()
        return prov, cal

    def test_create_event(self, monkeypatch):
        prov, cal = self._connected(monkeypatch)
        result = prov.create_event(_event())
        assert len(cal.saved) == 1
        assert b"doto-T1@doxtr-doto" in cal.saved[0].encode()
        assert result.etag == "et1"
        assert result.href == "https://dav/obj/1"

    def test_update_event_also_saves(self, monkeypatch):
        prov, cal = self._connected(monkeypatch)
        prov.update_event(_event())
        assert len(cal.saved) == 1

    def test_delete_by_href(self, monkeypatch):
        prov, cal = self._connected(monkeypatch)
        prov.delete_event(make_uid("T1"), href="https://dav/obj/1")
        assert cal.last_obj.deleted is True

    def test_delete_by_uid(self, monkeypatch):
        prov, cal = self._connected(monkeypatch)
        prov.delete_event(make_uid("T1"))
        assert cal.last_obj.deleted is True


class TestVeventToRemote:
    """Unit-test raw VEVENT -> RemoteEvent parsing (needs icalendar)."""

    def _parse(self, vevent: str):
        icalendar = pytest.importorskip("icalendar")
        from doxtr_doto.calsync.providers.caldav import _vevent_to_remote

        cal = icalendar.Calendar.from_ical(vevent)
        (comp,) = list(cal.walk("vevent"))
        return _vevent_to_remote(comp, href="https://dav/obj/9", etag="e9")

    def test_timed_vevent_is_naive_local(self):
        vevent = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//t//EN\r\n"
            "BEGIN:VEVENT\r\n"
            "UID:user-9@example.com\r\n"
            "SUMMARY:Meeting\r\n"
            "DESCRIPTION:notes\r\n"
            "DTSTART:20260302T090000Z\r\n"
            "DTEND:20260302T093000Z\r\n"
            "CATEGORIES:work,urgent\r\n"
            "END:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        rev = self._parse(vevent)
        assert rev.uid == "user-9@example.com"
        assert rev.summary == "Meeting"
        assert rev.all_day is False
        assert rev.start is not None and rev.start.tzinfo is None
        assert rev.start == __import__("datetime").datetime(2026, 3, 2, 9, 0)
        assert "work" in rev.categories and "urgent" in rev.categories

    def test_all_day_vevent_is_date_only(self):
        vevent = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//t//EN\r\n"
            "BEGIN:VEVENT\r\n"
            "UID:user-ad@example.com\r\n"
            "SUMMARY:Holiday\r\n"
            "DTSTART;VALUE=DATE:20260704\r\n"
            "DTEND;VALUE=DATE:20260705\r\n"
            "END:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        rev = self._parse(vevent)
        assert rev.all_day is True
        assert rev.inbound_due() == "2026-07-04"


class _FakeDavObj:
    def __init__(self, data, url="https://dav/o", etag="e"):
        self._data = data
        self.url = url
        self.etag = etag

    @property
    def data(self):
        if isinstance(self._data, Exception):
            raise self._data
        return self._data


class TestListEventsErrorHandling:
    """A transient read failure must not masquerade as a remote deletion."""

    def _connected_with_events(self, monkeypatch, events_or_exc):
        icalendar = pytest.importorskip("icalendar")  # noqa: F841
        cal = _FakeCalendar("work")

        def _events():
            if isinstance(events_or_exc, Exception):
                raise events_or_exc
            return events_or_exc

        cal.events = _events
        principal = _FakePrincipal([cal])
        _install_fake_caldav(monkeypatch, principal)
        cfg = CalendarConfig(
            provider="caldav", url="https://dav/", username="u", password="p", calendar="work"
        )
        prov = CalDAVProvider(cfg)
        prov.connect()
        return prov

    def test_list_fetch_failure_raises_not_empty(self, monkeypatch):
        prov = self._connected_with_events(monkeypatch, RuntimeError("boom"))
        with pytest.raises(ProviderError, match="CalDAV list failed"):
            prov.list_events()

    def test_unparseable_objects_skipped_but_valid_kept(self, monkeypatch):
        valid = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//t//EN\r\n"
            "BEGIN:VEVENT\r\nUID:ok@x\r\nSUMMARY:ok\r\n"
            "DTSTART;VALUE=DATE:20260101\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        objs = [_FakeDavObj("not ical at all"), _FakeDavObj(valid)]
        prov = self._connected_with_events(monkeypatch, objs)
        out = prov.list_events()
        assert [r.uid for r in out] == ["ok@x"]

    def test_all_objects_unreadable_aborts(self, monkeypatch):
        objs = [_FakeDavObj(RuntimeError("read error")), _FakeDavObj("garbage")]
        prov = self._connected_with_events(monkeypatch, objs)
        with pytest.raises(ProviderError, match="none could be read/parsed"):
            prov.list_events()
