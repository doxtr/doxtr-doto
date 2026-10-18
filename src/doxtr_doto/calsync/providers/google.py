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
from doxtr_doto.calsync.model import (
    BACK_REFERENCE_CLOSE,
    BACK_REFERENCE_OPEN,
    EventKind,
    RemoteEvent,
)
from doxtr_doto.calsync.providers._shared import (
    local_tz_name,
    parse_google_datetime,
    read_client_secrets,
)
from doxtr_doto.calsync.providers.base import (
    CalendarProvider,
    ProviderAuthError,
    ProviderError,
    PushResult,
)
from doxtr_doto.calsync.richtext import (
    calendar_html_to_markdown,
    markdown_to_calendar_html,
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
            "description": self._description_html(event.description),
            "start": start,
            "end": end,
            "iCalUID": event.uid,
        }
        return body

    @staticmethod
    def _description_html(description: str) -> str:
        """Render the outbound description's Markdown body to Calendar HTML.

        The projected ``description`` is the task's **Markdown** body followed
        by a ``[doto:<ref>]`` back-reference paragraph. Google Calendar renders
        a small HTML subset, so we convert the Markdown portion to that HTML
        (bold/italic/underline/links/lists) while keeping the back-reference
        marker intact -- re-appended on its own ``<br>`` line so the pull-side
        :func:`_strip_back_reference` still removes it and the body round-trips
        (Markdown -> HTML on push, HTML -> Markdown on pull).

        The back-reference is split off *before* conversion so the marker is
        never mangled by the Markdown renderer (its ``[...]`` looks like a link)
        and never escaped.
        """
        text = description or ""
        marker = ""
        stripped = text.rstrip()
        # Peel off a trailing ``[doto:...]`` marker (push appends it as the last
        # paragraph) so only the user's Markdown body is converted.
        if stripped.endswith(BACK_REFERENCE_CLOSE):
            open_at = stripped.rfind(BACK_REFERENCE_OPEN)
            if open_at != -1:
                marker = stripped[open_at:]
                text = stripped[:open_at].rstrip()
        html_body = markdown_to_calendar_html(text)
        if marker and html_body:
            return f"{html_body}<br><br>{marker}"
        return html_body or marker

    def create_event(self, event: CalendarEvent) -> PushResult:
        assert self._service is not None, "connect() must be called first"
        body = self._body(event)
        try:
            created = (
                self._service.events().insert(calendarId=self._calendar_id, body=body).execute()
            )
        except Exception as exc:
            # Google reserves an event's iCalUID even after the event is
            # deleted (it lingers as a 'cancelled' tombstone, invisible to
            # events().list(showDeleted=False)). A fresh insert with that same
            # iCalUID -- e.g. a task id reused after its event was removed --
            # is then rejected with 409 'The requested identifier already
            # exists.'. Rather than fail the whole sync, self-heal by
            # resurrecting/overwriting the existing item via events().import_,
            # which (unlike insert) accepts a reserved iCalUID.
            if _is_duplicate_identifier_error(exc):
                return self._recover_duplicate(event, body)
            raise ProviderError(f"Google create failed for {event.uid}: {exc}") from exc
        return PushResult(
            uid=event.uid,
            etag=str(created.get("etag", "")),
            remote_id=str(created.get("id", "")),
        )

    def _recover_duplicate(self, event: CalendarEvent, body: dict[str, Any]) -> PushResult:
        """Reconcile a 409-duplicate create by importing over the existing item.

        ``events().import_`` resurrects a cancelled tombstone (or overwrites a
        live event) that already holds ``event.uid`` as its iCalUID, so the
        local task re-adopts its remote item instead of the sync aborting.
        Falls back to a plain update if the item is live and import is refused.
        """
        try:
            imported = (
                self._service.events().import_(calendarId=self._calendar_id, body=body).execute()
            )
            return PushResult(
                uid=event.uid,
                etag=str(imported.get("etag", "")),
                remote_id=str(imported.get("id", "")),
            )
        except Exception as import_exc:
            # Import could not resurrect it; if the item is live, update it in
            # place so the create still converges.
            remote_id = self._find_remote_id(event.uid)
            if remote_id:
                return self.update_event(event, href=remote_id)
            raise ProviderError(
                f"Google create failed for {event.uid}: duplicate identifier "
                f"could not be reconciled: {import_exc}"
            ) from import_exc

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

    def list_events(self) -> list[RemoteEvent]:
        """List the configured calendar's events as provider-neutral snapshots.

        Uses ``events().list`` with ``singleEvents=True`` (recurrence expanded
        into concrete instances) and follows ``nextPageToken`` to page through
        the whole calendar. Google start/end dict shapes are mapped to
        naive-local datetimes via the shared parser, matching how ``_body``
        writes them on push.
        """
        assert self._service is not None, "connect() must be called first"
        out: list[RemoteEvent] = []
        page_token: str | None = None
        while True:
            try:
                resp = (
                    self._service.events()
                    .list(
                        calendarId=self._calendar_id,
                        singleEvents=True,
                        showDeleted=False,
                        maxResults=250,
                        pageToken=page_token,
                    )
                    .execute()
                )
            except Exception as exc:
                raise ProviderError(f"Google list failed: {exc}") from exc
            for item in resp.get("items", []):
                if item.get("status") == "cancelled":
                    continue
                out.append(self._to_remote_event(item))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return out

    @staticmethod
    def _to_remote_event(item: dict[str, Any]) -> RemoteEvent:
        """Map one Google events#resource into a :class:`RemoteEvent`.

        Google stores/returns the description as its rendered HTML subset. We
        convert it back to **Markdown** here so the provider-neutral
        :class:`RemoteEvent` (and everything downstream -- import, merge, the
        inbound hash) sees the same Markdown representation the local store
        uses. This keeps the body round-trip stable (push converts Markdown ->
        HTML, pull converts HTML -> Markdown) and prevents the stored HTML from
        leaking into a task body.
        """
        start, start_all_day = parse_google_datetime(item.get("start", {}))
        end, _end_all_day = parse_google_datetime(item.get("end", {}))
        return RemoteEvent(
            uid=str(item.get("iCalUID", "")),
            remote_id=str(item.get("id", "")),
            etag=str(item.get("etag", "")),
            summary=str(item.get("summary", "")),
            description=calendar_html_to_markdown(str(item.get("description", ""))),
            start=start,
            end=end,
            all_day=start_all_day,
            due=None,
            kind=EventKind.EVENT,
            status=str(item.get("status")) if item.get("status") else None,
            raw=item,
        )


def _is_duplicate_identifier_error(exc: Exception) -> bool:
    """Whether ``exc`` is Google's 409 'identifier already exists' on insert.

    Matches a googleapiclient ``HttpError`` with HTTP status 409. We avoid a
    hard import of ``googleapiclient.errors`` (the SDK is an optional extra and
    this module imports cleanly without it) by duck-typing ``status_code`` and
    falling back to a substring check on the reason/message for resilience
    against SDK shape changes.
    """
    status = getattr(exc, "status_code", None)
    if status is None:
        resp = getattr(exc, "resp", None)
        status = getattr(resp, "status", None)
    try:
        if status is not None and int(status) == 409:
            return True
    except (TypeError, ValueError):  # pragma: no cover - defensive
        pass
    text = f"{getattr(exc, 'reason', '')} {exc}".lower()
    return "already exists" in text or "duplicate" in text


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
