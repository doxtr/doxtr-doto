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
