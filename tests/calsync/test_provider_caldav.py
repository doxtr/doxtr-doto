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
