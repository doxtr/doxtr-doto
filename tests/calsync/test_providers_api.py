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
from doxtr_doto.calsync.providers.base import ProviderAuthError, ProviderError
from doxtr_doto.calsync.providers.google import (
    GoogleCalendarProvider,
    _is_duplicate_identifier_error,
)
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


class TestGoogleCreateDuplicateRecovery:
    """create_event self-heals Google's 409 'identifier already exists'.

    Google reserves an iCalUID even after its event is deleted (a lingering
    'cancelled' tombstone), so inserting with a reused iCalUID 409s. The
    provider must recover by importing over the existing item (or updating a
    live one) instead of aborting the whole sync.
    """

    @staticmethod
    def _http_409() -> Exception:
        """Build a googleapiclient HttpError with status 409, as Google raises."""
        from googleapiclient.errors import HttpError

        class _Resp:
            status = 409
            reason = "Conflict"

        content = (
            b'{"error": {"code": 409, "message": "The requested identifier '
            b'already exists.", "errors": [{"reason": "duplicate"}]}}'
        )
        return HttpError(_Resp(), content, uri="https://example/insert")

    def test_detects_409_duplicate(self):
        assert _is_duplicate_identifier_error(self._http_409()) is True

    def test_ignores_non_409(self):
        from googleapiclient.errors import HttpError

        class _Resp:
            status = 404
            reason = "Not Found"

        err = HttpError(_Resp(), b'{"error": {"message": "missing"}}', uri="u")
        assert _is_duplicate_identifier_error(err) is False

    def test_detects_409_via_resp_status_when_no_status_code(self):
        """Fallback branch: no ``status_code`` attr, but ``resp.status`` is 409."""

        class _Resp:
            status = 409

        exc = Exception("conflict")
        exc.resp = _Resp()  # type: ignore[attr-defined]
        assert _is_duplicate_identifier_error(exc) is True

    def test_detects_duplicate_by_message_substring(self):
        """Fallback branch: no status at all, but the message says 'already exists'."""
        assert (
            _is_duplicate_identifier_error(RuntimeError("The requested identifier already exists"))
            is True
        )
        assert _is_duplicate_identifier_error(RuntimeError("duplicate entry")) is True

    def test_plain_error_without_409_or_keywords_is_false(self):
        """A plain error with no 409 and no keywords must not be misclassified."""
        assert _is_duplicate_identifier_error(RuntimeError("network down")) is False

    def test_plain_insert_succeeds(self):
        """The happy path still returns the inserted item's ids."""

        class _Events:
            def insert(self, calendarId=None, body=None):
                self._res = {"id": "gid-new", "etag": '"e-new"'}
                return self

            def execute(self):
                return self._res

        class _Service:
            def events(self):
                return _Events()

        prov = GoogleCalendarProvider(CalendarConfig(provider="google"))
        prov._service = _Service()
        prov._calendar_id = "primary"
        res = prov.create_event(_timed())
        assert res.remote_id == "gid-new"
        assert res.etag == '"e-new"'
        assert res.uid == make_uid("T1")

    def test_409_recovers_via_import(self):
        """A 409 on insert falls back to import_, returning the live item ids."""
        calls: list[str] = []
        err = self._http_409()

        class _Events:
            def insert(self, calendarId=None, body=None):
                calls.append("insert")
                self._raise = True
                return self

            def import_(self, calendarId=None, body=None):
                calls.append("import")
                self._raise = False
                self._res = {"id": "gid-resurrected", "etag": '"e-res"'}
                return self

            def execute(self):
                if getattr(self, "_raise", False):
                    raise err
                return self._res

        class _Service:
            def events(self):
                return _Events()

        prov = GoogleCalendarProvider(CalendarConfig(provider="google"))
        prov._service = _Service()
        prov._calendar_id = "primary"
        res = prov.create_event(_timed())
        assert calls == ["insert", "import"]
        assert res.remote_id == "gid-resurrected"
        assert res.etag == '"e-res"'

    def test_409_import_fails_falls_back_to_update(self):
        """If import_ is refused but the item is live, update it in place."""
        err = self._http_409()

        class _Events:
            def insert(self, calendarId=None, body=None):
                self._mode = "insert"
                return self

            def import_(self, calendarId=None, body=None):
                self._mode = "import"
                return self

            def list(self, **kw):
                self._mode = "list"
                return self

            def update(self, calendarId=None, eventId=None, body=None):
                self._mode = "update"
                assert eventId == "gid-live"
                return self

            def execute(self):
                mode = self._mode
                if mode in ("insert", "import"):
                    raise err
                if mode == "list":
                    return {"items": [{"id": "gid-live"}]}
                return {"id": "gid-live", "etag": '"e-upd"'}

        class _Service:
            def events(self):
                return _Events()

        prov = GoogleCalendarProvider(CalendarConfig(provider="google"))
        prov._service = _Service()
        prov._calendar_id = "primary"
        res = prov.create_event(_timed())
        assert res.remote_id == "gid-live"
        assert res.etag == '"e-upd"'

    def test_409_unrecoverable_raises_provider_error(self):
        """Import fails and no live item is found -> a clear ProviderError."""
        err = self._http_409()

        class _Events:
            def insert(self, calendarId=None, body=None):
                self._mode = "insert"
                return self

            def import_(self, calendarId=None, body=None):
                self._mode = "import"
                return self

            def list(self, **kw):
                self._mode = "list"
                return self

            def execute(self):
                if self._mode in ("insert", "import"):
                    raise err
                return {"items": []}  # no live item to update

        class _Service:
            def events(self):
                return _Events()

        prov = GoogleCalendarProvider(CalendarConfig(provider="google"))
        prov._service = _Service()
        prov._calendar_id = "primary"
        with pytest.raises(ProviderError, match="could not be reconciled"):
            prov.create_event(_timed())

    def test_non_duplicate_error_still_raises(self):
        """A non-409 insert error is wrapped and raised (no recovery attempt)."""

        class _Events:
            def insert(self, calendarId=None, body=None):
                return self

            def execute(self):
                raise RuntimeError("network down")

        class _Service:
            def events(self):
                return _Events()

        prov = GoogleCalendarProvider(CalendarConfig(provider="google"))
        prov._service = _Service()
        prov._calendar_id = "primary"
        with pytest.raises(ProviderError, match="network down"):
            prov.create_event(_timed())


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


class TestGoogleInboundMapper:
    """Unit-test Google's events#resource -> RemoteEvent mapping (no network)."""

    def test_all_day_resource_maps_to_date_only(self):
        item = {
            "iCalUID": "user-ad@example.com",
            "id": "gid1",
            "etag": '"etag1"',
            "summary": "Holiday",
            "description": "Day off",
            "start": {"date": "2026-07-04"},
            "end": {"date": "2026-07-05"},
            "status": "confirmed",
        }
        rev = GoogleCalendarProvider._to_remote_event(item)
        assert rev.uid == "user-ad@example.com"
        assert rev.remote_id == "gid1"
        assert rev.all_day is True
        assert rev.start == datetime(2026, 7, 4, 0, 0)
        assert rev.start.tzinfo is None
        assert rev.inbound_due() == "2026-07-04"

    def test_timed_resource_is_naive_local(self):
        item = {
            "iCalUID": "user-t@example.com",
            "id": "gid2",
            "summary": "Call",
            "start": {"dateTime": "2026-03-02T09:00:00+02:00", "timeZone": "Europe/Berlin"},
            "end": {"dateTime": "2026-03-02T09:30:00+02:00", "timeZone": "Europe/Berlin"},
        }
        rev = GoogleCalendarProvider._to_remote_event(item)
        assert rev.all_day is False
        # tzinfo dropped; the +02:00 wall-clock is kept as naive-local.
        assert rev.start == datetime(2026, 3, 2, 9, 0)
        assert rev.start.tzinfo is None
        assert rev.inbound_due() == "2026-03-02T09:00"

    def test_cancelled_items_are_skipped_by_list(self):
        """list_events must drop status == 'cancelled' items (contract)."""

        class _FakeEvents:
            def list(self, **kw):
                return self

            def execute(self):
                return {
                    "items": [
                        {"iCalUID": "a@x", "status": "cancelled", "summary": "gone"},
                        {
                            "iCalUID": "b@x",
                            "status": "confirmed",
                            "summary": "live",
                            "start": {"date": "2026-01-01"},
                        },
                    ]
                }

        class _FakeService:
            def events(self):
                return _FakeEvents()

        prov = GoogleCalendarProvider(CalendarConfig(provider="google"))
        prov._service = _FakeService()
        prov._calendar_id = "primary"
        out = prov.list_events()
        assert [r.summary for r in out] == ["live"]


class TestMicrosoftInboundMapper:
    """Unit-test Graph event -> RemoteEvent mapping (no network)."""

    def test_extended_property_uid_wins(self):
        from doxtr_doto.calsync.providers.microsoft import DOTO_UID_PROP

        item = {
            "id": "mid1",
            "@odata.etag": 'W/"e1"',
            "subject": "Doto owned",
            "body": {"content": "note"},
            "isAllDay": False,
            "start": {"dateTime": "2026-03-02T09:00:00.0000000", "timeZone": "UTC"},
            "end": {"dateTime": "2026-03-02T09:30:00.0000000", "timeZone": "UTC"},
            "iCalUId": "fallback@outlook.com",
            "singleValueExtendedProperties": [{"id": DOTO_UID_PROP, "value": "doto-A@doxtr-doto"}],
        }
        rev = MicrosoftCalendarProvider._to_remote_event(item)
        # The stashed doto-uid extended property wins over iCalUId.
        assert rev.uid == "doto-A@doxtr-doto"
        assert rev.remote_id == "mid1"
        assert rev.all_day is False
        # Naive-local (Prefer header makes Graph return local wall-clock).
        assert rev.start == datetime(2026, 3, 2, 9, 0)
        assert rev.start.tzinfo is None

    def test_icaluid_fallback_when_no_extended_property(self):
        item = {
            "id": "mid2",
            "subject": "User event",
            "body": {"content": ""},
            "isAllDay": True,
            "start": {"dateTime": "2026-07-04T00:00:00.0000000", "timeZone": "UTC"},
            "end": {"dateTime": "2026-07-05T00:00:00.0000000", "timeZone": "UTC"},
            "iCalUId": "user@outlook.com",
            "singleValueExtendedProperties": [],
        }
        rev = MicrosoftCalendarProvider._to_remote_event(item)
        assert rev.uid == "user@outlook.com"
        assert rev.all_day is True
        assert rev.inbound_due() == "2026-07-04"

    def test_list_sends_prefer_timezone_header(self, monkeypatch):
        """list_events must send Prefer: outlook.timezone with the local zone."""
        from doxtr_doto.calsync.providers import microsoft as ms_mod

        monkeypatch.setattr(ms_mod, "local_tz_name", lambda: "Europe/Berlin")

        captured: dict = {}

        class _FakeResp:
            status_code = 200

            def json(self):
                return {"value": []}

        class _FakeSession:
            def get(self, url, params=None, headers=None):
                captured["headers"] = headers
                return _FakeResp()

        prov = MicrosoftCalendarProvider(CalendarConfig(provider="microsoft"))
        prov._session = _FakeSession()
        prov._calendar_id = ""
        prov.list_events()
        assert captured["headers"]["Prefer"] == 'outlook.timezone="Europe/Berlin"'
