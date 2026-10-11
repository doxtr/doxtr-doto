"""RFC 5545 (de)serialization for :class:`CalendarEvent`.

Uses the battle-tested ``icalendar`` library rather than hand-rolling the wire
format. ``icalendar`` is an optional dependency (the ``[calendar]`` extra), so
it is imported lazily and a clear error is raised if it is missing.

A content hash of the serialized item is computed for change detection: the
engine stores the hash in the sync state and only re-pushes a task when its
projected event's hash changes, mirroring the RST ``sync.hash`` approach.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from doxtr_doto.calsync.model import CalendarEvent, EventKind

_MISSING_MSG = (
    "Calendar sync requires the 'icalendar' package. Install the calendar extra: "
    "pip install 'doxtr-doto[calendar]'"
)


def _require_icalendar() -> Any:
    """Import ``icalendar`` lazily, raising a friendly error when absent."""
    try:
        import icalendar
    except ModuleNotFoundError as exc:  # pragma: no cover - env dependent
        raise RuntimeError(_MISSING_MSG) from exc
    return icalendar


def event_to_ical(event: CalendarEvent, *, prodid: str = "-//doxtr-doto//calsync//EN") -> bytes:
    """Serialize a :class:`CalendarEvent` to a full VCALENDAR byte string.

    Args:
        event: The event to serialize.
        prodid: PRODID stamped on the VCALENDAR wrapper.

    Returns:
        The iCalendar document as UTF-8 bytes (CRLF line endings per RFC 5545).
    """
    icalendar = _require_icalendar()
    cal = icalendar.Calendar()
    cal.add("prodid", prodid)
    cal.add("version", "2.0")
    cal.add_component(_build_component(event, icalendar))
    result: bytes = cal.to_ical()
    return result


def _build_component(event: CalendarEvent, icalendar: Any) -> Any:
    """Build the inner VEVENT/VTODO component for ``event``."""
    if event.kind is EventKind.TODO:
        comp = icalendar.Todo()
        comp.add("uid", event.uid)
        comp.add("summary", event.summary)
        if event.description:
            comp.add("description", event.description)
        if event.due is not None:
            comp.add("due", event.due)
        if event.status:
            comp.add("status", event.status)
        if event.categories:
            comp.add("categories", event.categories)
        comp.add("dtstamp", datetime.now(timezone.utc))
        return comp

    comp = icalendar.Event()
    comp.add("uid", event.uid)
    comp.add("summary", event.summary)
    if event.description:
        comp.add("description", event.description)
    if event.all_day and event.start is not None:
        # All-day: DTSTART/DTEND are DATE values (exclusive end).
        comp.add("dtstart", event.start.date())
        if event.end is not None:
            comp.add("dtend", event.end.date())
    else:
        if event.start is not None:
            comp.add("dtstart", event.start)
        if event.end is not None:
            comp.add("dtend", event.end)
    if event.status:
        comp.add("status", event.status)
    if event.categories:
        comp.add("categories", event.categories)
    comp.add("dtstamp", datetime.now(timezone.utc))
    return comp


def content_hash(event: CalendarEvent) -> str:
    """Compute a stable content hash of an event for change detection.

    The hash deliberately excludes volatile fields (``DTSTAMP``) so the same
    task projected twice yields the same hash. We hash the salient projected
    fields directly rather than the serialized output (which carries a
    per-call timestamp).

    Args:
        event: The event to hash.

    Returns:
        A 16-char hex digest.
    """
    parts = [
        event.uid,
        event.kind.value,
        event.summary,
        event.description,
        event.start.isoformat() if event.start else "",
        event.end.isoformat() if event.end else "",
        "1" if event.all_day else "0",
        event.due.isoformat() if event.due else "",
        event.status or "",
        ",".join(sorted(event.categories)),
    ]
    payload = "\x1f".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]
