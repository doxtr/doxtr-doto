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

from typing import TYPE_CHECKING, Any

from doxtr_doto.calsync.ical import event_to_ical
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
