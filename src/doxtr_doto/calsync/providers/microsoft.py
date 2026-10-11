"""Microsoft 365 / Outlook calendar provider (Microsoft Graph + OAuth2).

Auth model mirrors Google: a single app registration (in Microsoft Entra ID)
identifies "doto"; each user consents once via a browser and doto caches the
per-user token. Outlook.com no longer supports CalDAV, so Graph is the only
route. Uses MSAL for the OAuth2 device/interactive flow and plain ``requests``
for the REST calls -- both lazily imported (``[calendar]`` extra).
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

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SCOPES = ["Calendars.ReadWrite"]
#: "common" lets both work and personal Microsoft accounts sign in.
DEFAULT_AUTHORITY = "https://login.microsoftonline.com/common"

#: Graph single-value extended property doto uses to stash its own UID on an
#: event so it can be found again on update/delete. The GUID is Graph's
#: well-known ``PublicStrings`` property-set namespace; the ``Name`` suffix is
#: doto's own key within it. Defined once and referenced by both the write path
#: (``_body``) and the lookup path (``_find_remote_id``) so they can never
#: diverge.
DOTO_UID_PROP = "String {00020329-0000-0000-C000-000000000046} Name doto-uid"

_MISSING_MSG = (
    "Microsoft calendar sync requires 'msal' and 'requests'. Install the "
    "calendar extra: pip install 'doxtr-doto[calendar]'"
)


class MicrosoftCalendarProvider(CalendarProvider):
    """Push doto events to an Outlook/Microsoft 365 calendar via Graph."""

    name = "microsoft"

    def __init__(self, config: Any) -> None:
        super().__init__(config)
        self._token: str = ""
        self._session: Any = None
        self._calendar_id = ""

    def _imports(self) -> tuple[Any, Any]:
        try:
            import msal
            import requests
        except ModuleNotFoundError as exc:  # pragma: no cover - env dependent
            raise ProviderError(_MISSING_MSG) from exc
        return msal, requests

    def _client_id(self) -> str:
        """OAuth client (application) id, read from the client-secrets JSON."""
        path = self.config.oauth_client_secrets
        if path:
            data = read_client_secrets(path)
            # Accept either a bare {"client_id": ...} or an Entra app manifest.
            cid = data.get("client_id") or data.get("appId")
            if not cid:
                raise ProviderAuthError("oauth_client_secrets JSON has no 'client_id'/'appId'.")
            return str(cid)
        raise ProviderAuthError(
            "No Microsoft OAuth client configured. Set 'oauth_client_secrets' "
            "in [calendar] to a JSON file containing the application client_id."
        )

    def _msal_app(self, msal: Any) -> Any:
        return msal.PublicClientApplication(self._client_id(), authority=DEFAULT_AUTHORITY)

    def connect(self) -> None:
        """Acquire a token silently from the MSAL cache; else require login."""
        msal, requests = self._imports()
        cache = msal.SerializableTokenCache()
        cached = auth.load_token(self.name)
        if cached and cached.get("cache"):
            cache.deserialize(cached["cache"])
        app = msal.PublicClientApplication(
            self._client_id(), authority=DEFAULT_AUTHORITY, token_cache=cache
        )
        accounts = app.get_accounts()
        result = None
        if accounts:
            result = app.acquire_token_silent(SCOPES, account=accounts[0])
        if not result or "access_token" not in result:
            raise ProviderAuthError("Not logged in to Microsoft. Run 'doto calsync login' first.")
        self._finish(result, cache, requests)

    def login(self) -> None:
        """Interactive OAuth2 (falls back to device-code) and cache the token."""
        msal, requests = self._imports()
        cache = msal.SerializableTokenCache()
        app = msal.PublicClientApplication(
            self._client_id(), authority=DEFAULT_AUTHORITY, token_cache=cache
        )
        try:
            result = app.acquire_token_interactive(SCOPES)
        except Exception:
            flow = app.initiate_device_flow(scopes=SCOPES)
            if "user_code" not in flow:
                raise ProviderAuthError("Failed to start Microsoft device flow.") from None
            print(flow["message"])
            result = app.acquire_token_by_device_flow(flow)
        if "access_token" not in result:
            raise ProviderAuthError(
                f"Microsoft login failed: {result.get('error_description', result)}"
            )
        self._finish(result, cache, requests)

    def _finish(self, result: Any, cache: Any, requests: Any) -> None:
        self._token = result["access_token"]
        if cache.has_state_changed:
            auth.save_token(self.name, {"cache": cache.serialize()})
        self._session = requests.Session()
        self._session.headers.update(
            {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}
        )
        self._calendar_id = self.config.calendar or ""

    def _events_url(self) -> str:
        if self._calendar_id:
            return f"{GRAPH_BASE}/me/calendars/{self._calendar_id}/events"
        return f"{GRAPH_BASE}/me/events"

    def _body(self, event: CalendarEvent) -> dict[str, Any]:
        from datetime import datetime

        tz = local_tz_name()

        def _dt(d: datetime) -> dict[str, Any]:
            return {"dateTime": d.isoformat(), "timeZone": tz}

        def _all_day(d: datetime) -> dict[str, Any]:
            # Graph wants a dateTime even for all-day; stamp it with the local
            # zone (not UTC) so a naive-local date doesn't shift across the day
            # boundary for users away from UTC -- consistent with the timed
            # branch and with the Google provider's date-only handling.
            return {"dateTime": d.date().isoformat() + "T00:00:00", "timeZone": tz}

        body: dict[str, Any] = {
            "subject": event.summary,
            "body": {"contentType": "text", "content": event.description},
            "singleValueExtendedProperties": [
                # Stash our UID so we can find the event again on update/delete.
                {"id": DOTO_UID_PROP, "value": event.uid}
            ],
        }
        if event.kind is EventKind.TODO and event.due:
            body["isAllDay"] = True
            body["start"] = _all_day(event.due)
            body["end"] = body["start"]
        elif event.all_day and event.start and event.end:
            body["isAllDay"] = True
            body["start"] = _all_day(event.start)
            body["end"] = _all_day(event.end)
        else:
            if event.start:
                body["start"] = _dt(event.start)
            if event.end:
                body["end"] = _dt(event.end)
        return body

    def create_event(self, event: CalendarEvent) -> PushResult:
        assert self._session is not None, "connect() must be called first"
        resp = self._session.post(self._events_url(), json=self._body(event))
        if resp.status_code >= 400:
            raise ProviderError(
                f"Microsoft create failed for {event.uid}: {resp.status_code} {resp.text}"
            )
        data = resp.json()
        return PushResult(
            uid=event.uid,
            etag=str(data.get("@odata.etag", "")),
            remote_id=str(data.get("id", "")),
        )

    def update_event(self, event: CalendarEvent, *, etag: str = "", href: str = "") -> PushResult:
        assert self._session is not None, "connect() must be called first"
        remote_id = href or self._find_remote_id(event.uid)
        if not remote_id:
            return self.create_event(event)
        url = f"{self._events_url()}/{remote_id}"
        resp = self._session.patch(url, json=self._body(event))
        if resp.status_code >= 400:
            raise ProviderError(
                f"Microsoft update failed for {event.uid}: {resp.status_code} {resp.text}"
            )
        data = resp.json()
        return PushResult(
            uid=event.uid,
            etag=str(data.get("@odata.etag", "")),
            remote_id=str(data.get("id", "")),
        )

    def delete_event(self, uid: str, *, etag: str = "", href: str = "") -> None:
        assert self._session is not None, "connect() must be called first"
        remote_id = href or self._find_remote_id(uid)
        if not remote_id:
            return
        url = f"{self._events_url()}/{remote_id}"
        resp = self._session.delete(url)
        if resp.status_code >= 400 and resp.status_code != 404:
            raise ProviderError(
                f"Microsoft delete failed for {uid}: {resp.status_code} {resp.text}"
            )

    def _find_remote_id(self, uid: str) -> str:
        assert self._session is not None
        # Filter by our stashed extended property. OData escapes a single quote
        # by doubling it; uid is doto-generated today, but escaping keeps the
        # filter well-formed if a task id ever contains a quote.
        safe_uid = uid.replace("'", "''")
        params = {
            "$filter": (
                f"singleValueExtendedProperties/Any(ep: ep/id eq '{DOTO_UID_PROP}' "
                f"and ep/value eq '{safe_uid}')"
            )
        }
        resp = self._session.get(self._events_url(), params=params)
        if resp.status_code >= 400:
            return ""
        items = resp.json().get("value", [])
        return str(items[0]["id"]) if items else ""
