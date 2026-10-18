"""CalDAV provider: serves generic CalDAV servers **and** Apple iCloud.

Apple iCloud exposes a standard CalDAV endpoint; the only difference from a
generic server is the well-known base URL and the requirement to use an
**app-specific password** (generated at appleid.apple.com) rather than the main
account password. There is no OAuth and no developer registration for CalDAV.

Auth is HTTP Basic with ``username`` + ``password`` (an app-specific password
for iCloud). The ``caldav`` library (an optional ``[calendar]`` dependency) is
imported lazily.
"""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime as _dt
from typing import TYPE_CHECKING, Any

from doxtr_doto.calsync.ical import event_to_ical
from doxtr_doto.calsync.model import EventKind, RemoteEvent
from doxtr_doto.calsync.providers.base import (
    CalendarProvider,
    ProviderAuthError,
    ProviderError,
    PushResult,
)

if TYPE_CHECKING:
    from doxtr_doto.calsync.model import CalendarEvent

#: Apple iCloud's well-known CalDAV entry point. Used when the provider is
#: ``apple``/``icloud`` and no explicit ``url`` is configured.
APPLE_CALDAV_URL = "https://caldav.icloud.com/"

_MISSING_MSG = (
    "CalDAV sync requires the 'caldav' package. Install the calendar extra: "
    "pip install 'doxtr-doto[calendar]'"
)


class CalDAVProvider(CalendarProvider):
    """Push doto events to a CalDAV calendar collection (incl. Apple iCloud)."""

    name = "caldav"

    def __init__(self, config: Any) -> None:
        super().__init__(config)
        self._client: Any = None
        self._calendar: Any = None

    def connect(self) -> None:
        """Open a CalDAV session and resolve the target calendar collection."""
        try:
            import caldav
        except ModuleNotFoundError as exc:  # pragma: no cover - env dependent
            raise ProviderError(_MISSING_MSG) from exc
        dav: Any = caldav

        username = self.config.username
        password = self.config.resolved_password()
        if not username or not password:
            raise ProviderAuthError(
                "CalDAV requires 'username' and 'password' (an app-specific "
                "password for Apple iCloud) in the [calendar] config."
            )

        url = self.config.url
        provider_key = (self.config.provider or "").lower()
        if not url and provider_key in ("apple", "icloud"):
            url = APPLE_CALDAV_URL
        if not url:
            raise ProviderAuthError(
                "CalDAV requires a 'url' (the server's CalDAV base URL) in the [calendar] config."
            )

        try:
            self._client = dav.DAVClient(url=url, username=username, password=password)
            principal = self._client.principal()
            self._calendar = self._resolve_calendar(principal)
        except ProviderError:
            raise
        except Exception as exc:  # caldav raises various exception types
            raise ProviderError(f"CalDAV connection failed: {exc}") from exc

    def _resolve_calendar(self, principal: Any) -> Any:
        """Pick the target calendar: by URL, by display name, or the first one."""
        target = (self.config.calendar or "").strip()
        if target.startswith("http://") or target.startswith("https://"):
            # Treat as an explicit calendar collection URL.
            return principal.calendar(cal_url=target)

        calendars = principal.calendars()
        if not calendars:
            raise ProviderError("No calendars found for this CalDAV account.")

        if not target:
            return calendars[0]

        for cal in calendars:
            try:
                if cal.get_display_name() == target:
                    return cal
            except Exception:
                continue
        raise ProviderError(
            f"No CalDAV calendar named {target!r}; available: "
            + ", ".join(self._safe_names(calendars))
        )

    @staticmethod
    def _safe_names(calendars: Any) -> list[str]:
        names = []
        for cal in calendars:
            try:
                names.append(cal.get_display_name() or "<unnamed>")
            except Exception:
                names.append("<unnamed>")
        return names

    def _save(self, event: CalendarEvent) -> PushResult:
        """Create-or-replace the item (CalDAV PUT is idempotent on UID/URL)."""
        assert self._calendar is not None, "connect() must be called first"
        ical = event_to_ical(event)
        try:
            obj = self._calendar.save_event(ical.decode("utf-8"))
        except Exception as exc:
            raise ProviderError(f"CalDAV write failed for {event.uid}: {exc}") from exc
        etag = ""
        href = ""
        try:
            etag = obj.etag or ""
        except Exception:
            etag = ""
        try:
            href = str(obj.url) if obj.url else ""
        except Exception:
            href = ""
        return PushResult(uid=event.uid, etag=etag, href=href)

    def create_event(self, event: CalendarEvent) -> PushResult:
        return self._save(event)

    def update_event(self, event: CalendarEvent, *, etag: str = "", href: str = "") -> PushResult:
        # CalDAV PUT with the same UID overwrites; we rely on UID idempotency.
        return self._save(event)

    def delete_event(self, uid: str, *, etag: str = "", href: str = "") -> None:
        assert self._calendar is not None, "connect() must be called first"
        try:
            if href:
                obj = self._calendar.event_by_url(href)
            else:
                obj = self._calendar.object_by_uid(uid)
            obj.delete()
        except Exception as exc:
            raise ProviderError(f"CalDAV delete failed for {uid}: {exc}") from exc

    def list_events(self) -> list[RemoteEvent]:
        """List the collection's events, parsed into :class:`RemoteEvent`.

        Reads every VEVENT in the resolved calendar collection and parses it
        with the ``icalendar`` library (already a ``[calendar]`` dependency).
        DTSTART/DTEND that are DATE values (not DATETIME) map to all-day items;
        timezone-aware datetimes are reduced to naive-local wall-clock to match
        doto's model.

        Error handling is deliberately asymmetric to avoid a data-loss trap:
        the pull planner treats a *missing* remote item as a user deletion
        (archiving the local task), so a transient read failure must **never**
        look like "the event is gone". If the collection fetch itself fails we
        raise :class:`ProviderError` so pull aborts rather than archiving every
        task. Only genuinely unparseable *individual* objects are skipped, and
        their count is surfaced in the raised error when every object fails.
        """
        assert self._calendar is not None, "connect() must be called first"
        try:
            import icalendar
        except ModuleNotFoundError as exc:  # pragma: no cover - env dependent
            raise ProviderError(_MISSING_MSG) from exc
        # A failure to list the collection is a transport error -- abort rather
        # than let an empty result masquerade as "every event was deleted".
        try:
            events = self._calendar.events()
        except Exception as exc:
            raise ProviderError(f"CalDAV list failed: {exc}") from exc

        out: list[RemoteEvent] = []
        skipped = 0
        for obj in events:
            # Reading an individual object's body is a per-object transport
            # read; a failure here is NOT evidence the event was deleted, so we
            # count it as unparseable (skip) rather than treat it as missing.
            try:
                data = obj.data
            except Exception:
                skipped += 1
                continue
            try:
                cal = icalendar.Calendar.from_ical(data)
            except Exception:
                # Genuinely unparseable iCalendar payload: skip just this one.
                skipped += 1
                continue
            href = ""
            try:
                href = str(obj.url) if obj.url else ""
            except Exception:
                href = ""
            etag = ""
            try:
                etag = obj.etag or ""
            except Exception:
                etag = ""
            for comp in cal.walk("vevent"):
                out.append(_vevent_to_remote(comp, href=href, etag=etag))
        # If we found objects but could parse none of them, something is wrong
        # with the feed as a whole; abort rather than report an empty calendar
        # (which pull would read as "all events deleted").
        if skipped and not out:
            raise ProviderError(
                f"CalDAV list returned {skipped} object(s) but none could be read/parsed; "
                "aborting to avoid treating them as deletions."
            )
        return out


def _vevent_to_remote(comp: Any, *, href: str, etag: str) -> RemoteEvent:
    """Map an ``icalendar`` VEVENT component into a :class:`RemoteEvent`.

    DATE-valued DTSTART/DTEND (no time) become an all-day item; a
    timezone-aware DATETIME is reduced to naive-local wall-clock to match
    doto's naive-local time model. CATEGORIES, when present, are surfaced as
    the RemoteEvent's ``categories`` (cheap to read here).
    """

    def _naive(value: Any) -> tuple[_dt | None, bool]:
        if value is None:
            return None, False
        dt = getattr(value, "dt", value)
        if isinstance(dt, _dt):
            return (dt.replace(tzinfo=None) if dt.tzinfo else dt), False
        if isinstance(dt, _date):
            return _dt(dt.year, dt.month, dt.day), True
        return None, False

    start, start_all_day = _naive(comp.get("dtstart"))
    end, _end_all_day = _naive(comp.get("dtend"))

    def _text(key: str) -> str:
        val = comp.get(key)
        return str(val) if val is not None else ""

    return RemoteEvent(
        uid=_text("uid"),
        remote_id="",
        etag=etag,
        summary=_text("summary"),
        description=_text("description"),
        start=start,
        end=end,
        all_day=start_all_day,
        due=None,
        kind=EventKind.EVENT,
        status=_text("status") or None,
        categories=_categories(comp),
        raw=href or None,
    )


def _categories(comp: Any) -> list[str]:
    """Extract iCalendar CATEGORIES from a VEVENT as a flat list of strings.

    ``icalendar`` represents CATEGORIES either as a single value or a list of
    values, each of which may itself be a comma-joined ``vCategory``; this
    flattens whatever shape into a plain ``list[str]`` (empty when absent).
    """
    raw = comp.get("categories")
    if raw is None:
        return []
    items = raw if isinstance(raw, list) else [raw]
    out: list[str] = []
    for item in items:
        cats = getattr(item, "cats", None)
        if cats is not None:
            out.extend(str(c) for c in cats)
        else:
            out.append(str(item))
    return [c for c in (s.strip() for s in out) if c]
