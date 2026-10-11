"""Google Calendar provider (REST API + OAuth2).

Auth model (see the project docs / README for the full walk-through):

* A single OAuth2 *client* identifies "the doto application". For a published
  tool the maintainer registers it once (type "Desktop app") in Google Cloud
  Console and enables the Calendar API; the resulting client-id/secret are not
  truly secret for installed apps and may ship with doto.
* **Each end user** runs ``doto calsync login`` once per machine: a browser
  opens, they sign into *their own* Google account and consent. doto caches the
  resulting per-user token (auto-refreshed) under the config dir. Users never
  create a Cloud project themselves.

So an ordinary user does **not** set up Google Cloud -- *provided* doto ships a
(verified) client id. Until the app is Google-verified, users either see an
"unverified app" screen (and must be added as test users) or supply their own
client-secrets JSON via ``oauth_client_secrets``.

Events are written with the plain Calendar REST API; we deliberately avoid
heavyweight request builders and use the discovery client only for transport.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from doxtr_doto.calsync import auth
from doxtr_doto.calsync.model import EventKind
from doxtr_doto.calsync.providers._shared import local_tz_name, read_client_secrets
from doxtr_doto.calsync.providers.base import (
    CalendarProvider,
    ProviderAuthError,
    ProviderError,
    PushResult,
)

if TYPE_CHECKING:
    from doxtr_doto.calsync.model import CalendarEvent

#: Minimal scope: manage the user's calendars/events, nothing else.
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

_MISSING_MSG = (
    "Google Calendar sync requires 'google-api-python-client' and "
    "'google-auth-oauthlib'. Install the calendar extra: "
    "pip install 'doxtr-doto[calendar]'"
)


class GoogleCalendarProvider(CalendarProvider):
    """Push doto events to a Google Calendar via the REST API."""

    name = "google"

    def __init__(self, config: Any) -> None:
        super().__init__(config)
        self._service: Any = None
        self._calendar_id = "primary"

    def connect(self) -> None:
        """Load cached credentials (refreshing as needed) and build the client.

        This never launches an interactive browser flow -- that is done
        explicitly by ``doto calsync login`` so a plain ``sync`` run can't block
        on a browser. If no valid token is cached, raises
        :class:`ProviderAuthError` telling the user to log in.
        """
        creds = self._load_credentials(allow_interactive=False)
        if creds is None:
            raise ProviderAuthError("Not logged in to Google. Run 'doto calsync login' first.")
        self._build_service(creds)
        self._calendar_id = self.config.calendar or "primary"

    def login(self) -> None:
        """Run the interactive OAuth2 flow and cache the token.

        Called by ``doto calsync login``. Opens a browser for consent.
        """
        creds = self._load_credentials(allow_interactive=True)
        if creds is None:  # pragma: no cover - defensive
            raise ProviderAuthError("Google login did not produce credentials.")
        self._build_service(creds)
        self._calendar_id = self.config.calendar or "primary"

    # -- internals ----------------------------------------------------------
    def _imports(self) -> tuple[Any, Any, Any, Any]:
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ModuleNotFoundError as exc:  # pragma: no cover - env dependent
            raise ProviderError(_MISSING_MSG) from exc
        return Request, Credentials, InstalledAppFlow, build

    def _client_config(self) -> dict[str, Any] | None:
        """Return the OAuth client config (from file) or None to use bundled."""
        path = self.config.oauth_client_secrets
        if not path:
            return None
        return read_client_secrets(path)

    def _load_credentials(self, *, allow_interactive: bool) -> Any:
        Request, Credentials, InstalledAppFlow, _build = self._imports()

        cached = auth.load_token(self.name)
        creds = None
        if cached:
            creds = Credentials.from_authorized_user_info(cached, SCOPES)

        if creds and creds.valid:
            return creds

        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                auth.save_token(self.name, _creds_to_dict(creds))
                return creds
            except Exception as exc:
                if not allow_interactive:
                    raise ProviderAuthError(
                        f"Google token refresh failed; re-run login: {exc}"
                    ) from exc

        if not allow_interactive:
            return None

        client_config = self._client_config()
        if client_config is None:
            raise ProviderAuthError(
                "No Google OAuth client configured. Set 'oauth_client_secrets' "
                "in [calendar] to a downloaded client-secrets JSON (or ship a "
                "bundled client id)."
            )
        flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
        creds = flow.run_local_server(port=0)
        auth.save_token(self.name, _creds_to_dict(creds))
        return creds

    def _build_service(self, creds: Any) -> None:
        _r, _c, _f, build = self._imports()
        try:
            self._service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        except Exception as exc:
            raise ProviderError(f"Failed to build Google client: {exc}") from exc

    def _body(self, event: CalendarEvent) -> dict[str, Any]:
        """Translate a CalendarEvent into a Google events#resource body."""
        start: dict[str, Any]
        end: dict[str, Any]
        if event.kind is EventKind.TODO:
            # Google Calendar has no VTODO; model a to-do as an all-day event.
            start = {"date": (event.due.date().isoformat() if event.due else None)}
            end = start
        elif event.all_day and event.start and event.end:
            start = {"date": event.start.date().isoformat()}
            end = {"date": event.end.date().isoformat()}
        else:
            tz = local_tz_name()
            start = {"dateTime": event.start.isoformat(), "timeZone": tz} if event.start else {}
            end = {"dateTime": event.end.isoformat(), "timeZone": tz} if event.end else {}
        body: dict[str, Any] = {
            "summary": event.summary,
            "description": event.description,
            "start": start,
            "end": end,
            "iCalUID": event.uid,
        }
        return body

    def create_event(self, event: CalendarEvent) -> PushResult:
        assert self._service is not None, "connect() must be called first"
        try:
            created = (
                self._service.events()
                .insert(calendarId=self._calendar_id, body=self._body(event))
                .execute()
            )
        except Exception as exc:
            raise ProviderError(f"Google create failed for {event.uid}: {exc}") from exc
        return PushResult(
            uid=event.uid,
            etag=str(created.get("etag", "")),
            remote_id=str(created.get("id", "")),
        )

    def update_event(self, event: CalendarEvent, *, etag: str = "", href: str = "") -> PushResult:
        assert self._service is not None, "connect() must be called first"
        remote_id = href or self._find_remote_id(event.uid)
        if not remote_id:
            return self.create_event(event)
        try:
            updated = (
                self._service.events()
                .update(calendarId=self._calendar_id, eventId=remote_id, body=self._body(event))
                .execute()
            )
        except Exception as exc:
            raise ProviderError(f"Google update failed for {event.uid}: {exc}") from exc
        return PushResult(
            uid=event.uid,
            etag=str(updated.get("etag", "")),
            remote_id=str(updated.get("id", "")),
        )

    def delete_event(self, uid: str, *, etag: str = "", href: str = "") -> None:
        assert self._service is not None, "connect() must be called first"
        remote_id = href or self._find_remote_id(uid)
        if not remote_id:
            return
        try:
            self._service.events().delete(calendarId=self._calendar_id, eventId=remote_id).execute()
        except Exception as exc:
            raise ProviderError(f"Google delete failed for {uid}: {exc}") from exc

    def _find_remote_id(self, uid: str) -> str:
        """Resolve a Google event id from its iCalUID (returns '' if absent)."""
        assert self._service is not None
        try:
            resp = (
                self._service.events()
                .list(calendarId=self._calendar_id, iCalUID=uid, showDeleted=False)
                .execute()
            )
        except Exception:
            return ""
        items = resp.get("items", [])
        return str(items[0]["id"]) if items else ""


def _creds_to_dict(creds: Any) -> dict[str, Any]:
    """Serialize google.oauth2 Credentials into a cacheable dict."""
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or SCOPES),
    }
