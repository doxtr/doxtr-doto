"""Tests for the Google and Microsoft provider request-body mapping.

The OAuth flows need a browser/live server and are not unit-tested here, but the
deterministic parts -- how a CalendarEvent is translated into each provider's
request body, and the client-config/credential error paths -- are. SDKs are
exercised via the installed packages where possible and otherwise mocked.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from doxtr_doto.calsync.model import CalendarEvent, EventKind, make_uid
from doxtr_doto.calsync.providers.base import ProviderAuthError
from doxtr_doto.calsync.providers.google import GoogleCalendarProvider
from doxtr_doto.calsync.providers.microsoft import MicrosoftCalendarProvider
from doxtr_doto.cli.config import CalendarConfig


def _timed() -> CalendarEvent:
    return CalendarEvent(
        uid=make_uid("T1"),
        kind=EventKind.EVENT,
        summary="Standup",
        description="d",
        start=datetime(2026, 8, 15, 9, 0),
        end=datetime(2026, 8, 15, 9, 30),
        task_id="T1",
    )


def _all_day() -> CalendarEvent:
    return CalendarEvent(
        uid=make_uid("T2"),
        kind=EventKind.EVENT,
        summary="Deadline",
        start=datetime(2026, 8, 15, 0, 0),
        end=datetime(2026, 8, 16, 0, 0),
        all_day=True,
        task_id="T2",
    )


def _todo() -> CalendarEvent:
    return CalendarEvent(
        uid=make_uid("T3"),
        kind=EventKind.TODO,
        summary="Todo",
        due=datetime(2026, 8, 15, 9, 0),
        task_id="T3",
    )


class TestGoogleBody:
    def test_timed_event_body(self):
        prov = GoogleCalendarProvider(CalendarConfig(provider="google"))
        body = prov._body(_timed())
        assert body["summary"] == "Standup"
        assert body["iCalUID"] == make_uid("T1")
        assert "dateTime" in body["start"]
        assert "dateTime" in body["end"]

    def test_all_day_body_uses_date(self):
        prov = GoogleCalendarProvider(CalendarConfig(provider="google"))
        body = prov._body(_all_day())
        assert body["start"] == {"date": "2026-08-15"}
        assert body["end"] == {"date": "2026-08-16"}

    def test_todo_body_is_all_day(self):
        prov = GoogleCalendarProvider(CalendarConfig(provider="google"))
        body = prov._body(_todo())
        assert body["start"]["date"] == "2026-08-15"

    def test_client_config_missing_file(self):
        prov = GoogleCalendarProvider(
            CalendarConfig(provider="google", oauth_client_secrets="/no/such/file.json")
        )
        with pytest.raises(ProviderAuthError, match="Cannot read"):
            prov._client_config()

    def test_client_config_none_when_unset(self):
        prov = GoogleCalendarProvider(CalendarConfig(provider="google"))
        assert prov._client_config() is None

    def test_client_config_reads_file(self, tmp_path):
        p = tmp_path / "cs.json"
        p.write_text('{"installed": {"client_id": "abc"}}')
        prov = GoogleCalendarProvider(
            CalendarConfig(provider="google", oauth_client_secrets=str(p))
        )
        assert prov._client_config() == {"installed": {"client_id": "abc"}}

    def test_connect_without_token_raises(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        prov = GoogleCalendarProvider(CalendarConfig(provider="google"))
        with pytest.raises(ProviderAuthError, match="Not logged in"):
            prov.connect()


class TestMicrosoftBody:
    def test_timed_event_body(self):
        prov = MicrosoftCalendarProvider(CalendarConfig(provider="microsoft"))
        body = prov._body(_timed())
        assert body["subject"] == "Standup"
        assert "dateTime" in body["start"]
        # UID is stashed as an extended property for later lookup.
        ext = body["singleValueExtendedProperties"][0]
        assert ext["value"] == make_uid("T1")

    def test_all_day_body(self):
        prov = MicrosoftCalendarProvider(CalendarConfig(provider="microsoft"))
        body = prov._body(_all_day())
        assert body["isAllDay"] is True
        assert body["start"]["dateTime"].startswith("2026-08-15")

    def test_todo_body(self):
        prov = MicrosoftCalendarProvider(CalendarConfig(provider="microsoft"))
        body = prov._body(_todo())
        assert body["isAllDay"] is True

    def test_events_url_default(self):
        prov = MicrosoftCalendarProvider(CalendarConfig(provider="microsoft"))
        assert prov._events_url().endswith("/me/events")

    def test_events_url_with_calendar(self):
        prov = MicrosoftCalendarProvider(CalendarConfig(provider="microsoft", calendar="CAL123"))
        prov._calendar_id = "CAL123"
        assert "/me/calendars/CAL123/events" in prov._events_url()

    def test_client_id_missing_config(self):
        prov = MicrosoftCalendarProvider(CalendarConfig(provider="microsoft"))
        with pytest.raises(ProviderAuthError, match="No Microsoft OAuth client"):
            prov._client_id()

    def test_client_id_from_file(self, tmp_path):
        p = tmp_path / "ms.json"
        p.write_text('{"client_id": "ms-app-123"}')
        prov = MicrosoftCalendarProvider(
            CalendarConfig(provider="microsoft", oauth_client_secrets=str(p))
        )
        assert prov._client_id() == "ms-app-123"

    def test_client_id_from_appid_key(self, tmp_path):
        p = tmp_path / "ms.json"
        p.write_text('{"appId": "entra-456"}')
        prov = MicrosoftCalendarProvider(
            CalendarConfig(provider="microsoft", oauth_client_secrets=str(p))
        )
        assert prov._client_id() == "entra-456"

    def test_client_id_file_missing_id(self, tmp_path):
        p = tmp_path / "ms.json"
        p.write_text("{}")
        prov = MicrosoftCalendarProvider(
            CalendarConfig(provider="microsoft", oauth_client_secrets=str(p))
        )
        with pytest.raises(ProviderAuthError, match="no 'client_id'"):
            prov._client_id()


class TestMicrosoftAllDayTimezone:
    def test_all_day_not_hardcoded_utc(self):
        """All-day events use the local tz (consistent with the timed branch).

        A naive-local date must not be stamped as UTC, which could shift the
        day across the date boundary for users away from UTC.
        """
        import doxtr_doto.calsync.providers._shared as shared

        prov = MicrosoftCalendarProvider(CalendarConfig(provider="microsoft"))
        body = prov._body(_all_day())
        assert body["start"]["timeZone"] == shared.local_tz_name()
        assert body["end"]["timeZone"] == shared.local_tz_name()
        # Exclusive next-day end is preserved.
        assert body["end"]["dateTime"].startswith("2026-08-16")

    def test_find_remote_id_escapes_quotes(self, monkeypatch):
        """A single quote in the UID is OData-escaped (doubled) in the filter."""
        captured = {}

        class _Resp:
            status_code = 200

            def json(self):
                return {"value": []}

        class _Session:
            def get(self, url, params=None):
                captured["filter"] = params["$filter"]
                return _Resp()

        prov = MicrosoftCalendarProvider(CalendarConfig(provider="microsoft"))
        prov._session = _Session()
        prov._find_remote_id("doto-O'Brien@doxtr-doto")
        assert "O''Brien" in captured["filter"]


class TestSharedHelpers:
    def test_read_client_secrets_invalid_json(self, tmp_path):
        from doxtr_doto.calsync.providers._shared import read_client_secrets

        p = tmp_path / "bad.json"
        p.write_text("{ not json")
        with pytest.raises(ProviderAuthError, match="Invalid JSON"):
            read_client_secrets(str(p))

    def test_local_tz_name_returns_string(self):
        from doxtr_doto.calsync.providers._shared import local_tz_name

        assert isinstance(local_tz_name(), str)
        assert local_tz_name()  # non-empty

    def test_local_tz_name_is_valid_iana(self):
        """Whatever it returns must resolve as an IANA zone (Google requires it).

        Regression: a fixed-offset tzinfo used to yield an abbreviation like
        'CEST', which Google rejects with 'Invalid time zone definition'.
        """
        from doxtr_doto.calsync.providers._shared import _is_valid_iana, local_tz_name

        assert _is_valid_iana(local_tz_name())

    def test_local_tz_name_prefers_valid_tz_env(self, monkeypatch):
        from doxtr_doto.calsync.providers import _shared

        monkeypatch.setenv("TZ", "America/New_York")
        assert _shared.local_tz_name() == "America/New_York"

    def test_local_tz_name_rejects_abbreviation_tz_env(self, monkeypatch):
        """A TZ abbreviation ('CEST') must not leak through; fall back instead."""
        from doxtr_doto.calsync.providers import _shared

        monkeypatch.setenv("TZ", "CEST")
        result = _shared.local_tz_name()
        assert result != "CEST"
        assert _shared._is_valid_iana(result)

    def test_local_tz_name_uses_localtime_symlink_when_no_tz(self, monkeypatch):
        """With no TZ, resolve the IANA name behind /etc/localtime (step 2)."""
        from doxtr_doto.calsync.providers import _shared

        monkeypatch.delenv("TZ", raising=False)
        monkeypatch.setattr(_shared, "_tz_from_localtime_symlink", lambda: "Europe/Berlin")
        assert _shared.local_tz_name() == "Europe/Berlin"

    def test_tz_from_localtime_symlink_parses_zoneinfo_path(self, monkeypatch):
        """_tz_from_localtime_symlink extracts the name after 'zoneinfo'."""
        from pathlib import Path

        from doxtr_doto.calsync.providers import _shared

        monkeypatch.setattr(
            Path,
            "resolve",
            lambda self, *a, **k: Path("/usr/share/zoneinfo/Europe/Berlin"),
        )
        assert _shared._tz_from_localtime_symlink() == "Europe/Berlin"

    def test_tz_from_localtime_symlink_none_without_zoneinfo(self, monkeypatch):
        """A target not under a 'zoneinfo' dir yields None (not a bogus name)."""
        from pathlib import Path

        from doxtr_doto.calsync.providers import _shared

        monkeypatch.setattr(Path, "resolve", lambda self, *a, **k: Path("/etc/some/other/file"))
        assert _shared._tz_from_localtime_symlink() is None

    def test_is_valid_iana(self):
        from doxtr_doto.calsync.providers._shared import _is_valid_iana

        assert _is_valid_iana("Europe/Berlin")
        assert _is_valid_iana("UTC")
        assert not _is_valid_iana("CEST")
        assert not _is_valid_iana("")
        assert not _is_valid_iana("Not/AZone")
