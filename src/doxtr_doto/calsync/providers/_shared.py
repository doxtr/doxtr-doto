"""Shared helpers for the API-based calendar providers (Google, Microsoft).

Kept in one place so the two OAuth/REST providers can't drift on timezone
handling or client-secret parsing, and so a future provider reuses the same
logic.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from doxtr_doto.calsync.providers.base import ProviderAuthError


def _is_valid_iana(name: str) -> bool:
    """Return True if ``name`` resolves to a real IANA zone via ``zoneinfo``."""
    if not name or name == "UTC":
        return name == "UTC"
    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    except ModuleNotFoundError:  # pragma: no cover - py<3.9
        return False
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False


def _tz_from_localtime_symlink() -> str | None:
    """Resolve the IANA name behind ``/etc/localtime`` (e.g. ``Europe/Berlin``).

    Returns the zone name if ``/etc/localtime`` points under a ``zoneinfo``
    directory, else None.
    """
    try:
        link = Path("/etc/localtime").resolve()
    except OSError:  # pragma: no cover - platform dependent
        return None
    parts = link.parts
    if "zoneinfo" in parts:
        idx = parts.index("zoneinfo")
        name = "/".join(parts[idx + 1 :])
        return name or None
    return None


def local_tz_name() -> str:
    """Best-effort IANA timezone name for the local machine.

    doto models due dates/times as naive *local* wall-clock values; API
    providers (Google/Microsoft) must stamp a timezone at the wire boundary,
    and they require a valid IANA name (e.g. ``"Europe/Berlin"``) -- an
    abbreviation such as ``"CEST"`` is rejected with "Invalid time zone
    definition".

    Resolution order (first that yields a valid IANA name wins):

    1. The ``TZ`` environment variable, if it names a real IANA zone.
    2. The target of the ``/etc/localtime`` symlink (``.../zoneinfo/<name>``).
    3. ``ZoneInfo.key`` on the system ``tzinfo``, if present.
    4. ``str(tzinfo)`` only when it is itself a valid IANA name.

    Returns:
        A valid IANA timezone name, or ``"UTC"`` as a safe fallback.
    """
    try:
        env = os.environ.get("TZ", "").strip()
        if env and _is_valid_iana(env):
            return env

        from_link = _tz_from_localtime_symlink()
        if from_link and _is_valid_iana(from_link):
            return from_link

        tz = datetime.now().astimezone().tzinfo
        key = getattr(tz, "key", None)
        if key and _is_valid_iana(str(key)):
            return str(key)

        name = str(tz) if tz else ""
        if _is_valid_iana(name):
            return name

        return "UTC"
    except Exception:  # pragma: no cover - platform dependent
        return "UTC"


def read_client_secrets(path: str) -> dict[str, Any]:
    """Read and parse an OAuth client-secrets JSON file.

    Args:
        path: Filesystem path to the client-secrets JSON.

    Returns:
        The parsed JSON object.

    Raises:
        ProviderAuthError: If the file cannot be read or parsed.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            data: dict[str, Any] = json.load(fh)
        return data
    except OSError as exc:
        raise ProviderAuthError(f"Cannot read oauth_client_secrets {path!r}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ProviderAuthError(f"Invalid JSON in oauth_client_secrets {path!r}: {exc}") from exc


def parse_google_datetime(node: dict[str, Any]) -> tuple[datetime | None, bool]:
    """Parse a Google events#resource start/end node into naive-local time.

    Google represents an all-day boundary as ``{"date": "YYYY-MM-DD"}`` and a
    timed boundary as ``{"dateTime": "...", "timeZone": "..."}``. doto models
    due dates/times as *naive, local* wall-clock values, so the returned
    datetime is naive: for a timed value we drop the timezone (keeping the
    wall-clock the API returned, which the push path stamps with the local
    zone), and for an all-day value we return a midnight datetime.

    Args:
        node: The ``start`` or ``end`` object from a Google event resource.

    Returns:
        ``(datetime | None, all_day)``. ``all_day`` is True for a ``date``
        node. Returns ``(None, False)`` for an empty/unrecognized node.
    """
    if not node:
        return None, False
    date_only = node.get("date")
    if date_only:
        try:
            parsed = datetime.fromisoformat(str(date_only))
        except ValueError:
            return None, True
        return parsed.replace(hour=0, minute=0, second=0, microsecond=0), True
    dt_str = node.get("dateTime")
    if dt_str:
        try:
            parsed = datetime.fromisoformat(str(dt_str))
        except ValueError:
            return None, False
        # Drop any timezone to get back to naive-local wall-clock. Google
        # returns the time already expressed in the event's own zone, so the
        # wall-clock fields are what we want.
        return parsed.replace(tzinfo=None), False
    return None, False


def parse_graph_datetime(node: dict[str, Any]) -> datetime | None:
    """Parse a Microsoft Graph ``{"dateTime", "timeZone"}`` node to naive-local.

    Graph returns a boundary as ``{"dateTime": "2026-03-02T09:00:00.0000000",
    "timeZone": "..."}``. doto models due dates/times as *naive, local*
    wall-clock values, so we take the wall-clock ``dateTime`` and drop any
    timezone marker. The list request stamps a ``Prefer: outlook.timezone``
    header asking Graph to express times in the local zone, so the wall-clock
    fields are already correct once tzinfo is stripped. Shared by the Microsoft
    provider; kept here next to :func:`parse_google_datetime` so the two API
    providers can't drift on inbound time handling.

    Args:
        node: The ``start`` or ``end`` object from a Graph event resource.

    Returns:
        A naive :class:`datetime`, or None for an empty/unparseable node.
    """
    raw = (node or {}).get("dateTime")
    if not raw:
        return None
    try:
        # Microsoft Graph uses 7-digit fractional seconds (100-ns ticks), e.g.
        # "2026-03-02T09:00:00.0000000". Python < 3.11 fromisoformat() only
        # accepts up to 6 fractional digits, so we truncate before parsing.
        s = str(raw).replace("Z", "")
        if "." in s:
            dt_part, frac = s.rsplit(".", 1)
            s = f"{dt_part}.{frac[:6]}"
        return datetime.fromisoformat(s).replace(tzinfo=None)
    except ValueError:
        return None
