"""Provider-neutral calendar item model and task -> event projection.

The ``CalendarEvent`` dataclass is the shared currency between the engine and
every provider: the engine builds it from a doto task, a provider serializes it
to the wire format (iCalendar VEVENT/VTODO or a provider-native JSON body), and
pushes it. Keeping it transport-neutral means the projection logic (workday /
break windows, per-task estimate sizing, all-day handling) lives in exactly one
place and is unit-testable without any network or SDK.

Time model: doto models due dates/times as *naive, local* wall-clock values
(see :mod:`doxtr_doto.date_utils`). This module preserves that: the produced
``start``/``end`` are naive ``datetime`` objects. A timezone is attached only at
the provider boundary (each provider stamps the event with the local zone).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Any

from doxtr_doto.date_utils import DotoDate

if TYPE_CHECKING:
    from doxtr_doto.cli.config import CalendarConfig

#: Stable prefix for the UID doto assigns to every item it creates, so a sync
#: can reliably recognize "its own" items on the server and never touch events
#: created by the user or other tools.
UID_PREFIX = "doto-"
UID_DOMAIN = "@doxtr-doto"

#: Opening marker of the back-reference line push appends to a calendar item's
#: description (``[doto:<ref>]``). Defined once here and consumed by both the
#: push writer (:func:`project_task_to_event`) and the pull stripper
#: (:func:`doxtr_doto.calsync.engine._strip_back_reference`) so the two can
#: never drift on the marker spelling.
BACK_REFERENCE_OPEN = "[doto:"
BACK_REFERENCE_CLOSE = "]"


class EventKind(str, Enum):
    """Whether a task projects to a calendar event or a to-do item."""

    EVENT = "event"
    TODO = "todo"


@dataclass
class CalendarEvent:
    """A provider-neutral calendar item derived from a doto task.

    Attributes:
        uid: Stable iCalendar UID (``doto-<task_id>@doxtr-doto``). Used as the
            idempotency key: re-pushing the same task updates the same item.
        kind: EVENT (VEVENT) or TODO (VTODO).
        summary: Event title (the task title).
        description: Longer text (task body + a doto back-reference line).
        start: Naive local start datetime. For an all-day item this is a date
            at midnight and ``all_day`` is True.
        end: Naive local end datetime (exclusive). None for a to-do.
        all_day: True when this is an all-day event (date-only due, event mode).
        due: Naive local due datetime for a VTODO (TODO kind only).
        status: Mapped calendar status (e.g. ``CONFIRMED`` / ``COMPLETED``).
        categories: Tag list surfaced as iCalendar CATEGORIES.
        task_id: The originating doto task id (diagnostic / back-reference).
        extra: Provider-specific passthrough (not serialized generically).
    """

    uid: str
    kind: EventKind
    summary: str
    description: str = ""
    start: datetime | None = None
    end: datetime | None = None
    all_day: bool = False
    due: datetime | None = None
    status: str | None = None
    categories: list[str] = field(default_factory=list)
    task_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def make_uid(task_id: str) -> str:
    """Build the stable iCalendar UID doto uses for a task.

    Args:
        task_id: The doto task identifier.

    Returns:
        A UID of the form ``doto-<task_id>@doxtr-doto``.
    """
    return f"{UID_PREFIX}{task_id}{UID_DOMAIN}"


def is_doto_uid(uid: str | None) -> bool:
    """Return True when ``uid`` was created by doto (safe to update/delete)."""
    if not uid:
        return False
    return uid.startswith(UID_PREFIX) and uid.endswith(UID_DOMAIN)


def task_id_from_uid(uid: str) -> str | None:
    """Extract the doto task id from a doto-created UID, or None."""
    if not is_doto_uid(uid):
        return None
    return uid[len(UID_PREFIX) : -len(UID_DOMAIN)]


@dataclass
class RemoteEvent:
    """A provider-neutral snapshot of an item read back from a calendar.

    This is the inbound counterpart to :class:`CalendarEvent` (which is the
    outbound projection). A provider's ``list_events`` maps its native item
    shape onto this so the pull planner can reason about remote items without
    any provider-specific knowledge.

    Time model matches the rest of doto: ``start`` / ``end`` / ``due`` are
    *naive, local* wall-clock datetimes (the provider strips any timezone at
    the wire boundary), so they round-trip cleanly into a task's ``due``.

    Attributes:
        uid: iCalendar UID (``iCalUID``). May be a doto-owned UID (push created
            it) or an arbitrary user/provider UID.
        remote_id: Provider-native id (Google/MS event id); empty for CalDAV.
        etag: Server ETag, when the provider exposes one.
        summary: Item title.
        description: Item body/notes.
        start: Naive local start datetime (events), or None.
        end: Naive local end datetime (events), or None.
        all_day: True for an all-day/date-only item.
        due: Naive local due datetime (to-dos), or None.
        kind: EVENT or TODO.
        status: Provider/iCal status string, when available.
        categories: Tag/category list (iCalendar CATEGORIES), when the provider
            surfaces them; empty otherwise.
        extra: Provider-specific passthrough so the inbound contract can grow
            without a model change (never serialized generically).
        raw: Optional provider-native payload (diagnostic; never serialized).
    """

    uid: str
    remote_id: str = ""
    etag: str = ""
    summary: str = ""
    description: str = ""
    start: datetime | None = None
    end: datetime | None = None
    all_day: bool = False
    due: datetime | None = None
    kind: EventKind = EventKind.EVENT
    status: str | None = None
    categories: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)
    raw: Any = None

    def inbound_due(self) -> str | None:
        """Return the naive-local ISO ``due`` string this item maps to.

        Preference order mirrors the push projection: a to-do's ``due``, then
        an event ``start``. All-day items yield a date-only string; timed
        items keep ``YYYY-MM-DDTHH:MM``. Returns None when nothing is present.
        """
        anchor = self.due or self.start
        if anchor is None:
            return None
        if self.all_day:
            return anchor.date().isoformat()
        return DotoDate(anchor.date(), anchor.time()).isoformat()

    def inbound_estimate_minutes(self) -> int | None:
        """Return the event's duration in whole minutes, or None.

        The inbound counterpart to how push projects a task's ``estimate`` into
        an event's end (``end = start + estimate``): for a **timed** event with
        both a ``start`` and a later ``end``, this is ``end - start`` in
        minutes, so the duration a user set on the calendar can be mapped back
        onto the task's ``estimate`` (letting the end time be recomputed on the
        next push).

        Returns None for an all-day item (its end is an exclusive next-day
        date, not a real duration), when ``start``/``end`` are missing, or when
        ``end`` is not strictly after ``start`` -- so a zero/negative span never
        produces a bogus estimate.
        """
        return timed_duration_minutes(self.all_day, self.start, self.end)


def timed_duration_minutes(
    all_day: bool, start: datetime | None, end: datetime | None
) -> int | None:
    """Return a timed event's ``end - start`` duration in whole minutes, or None.

    The single source of truth for "how long is this timed event", shared by
    :meth:`RemoteEvent.inbound_estimate_minutes`,
    :func:`~doxtr_doto.calsync.ical.inbound_hash_of_pushed`, and the merge
    baseline snapshot, so the inbound-change fingerprint, the push baseline, and
    the merge ancestor can never disagree on the arithmetic (a mismatch would
    reintroduce spurious two-way conflicts).

    Returns None for an all-day item (its end is an exclusive next-day date, not
    a real duration), when ``start``/``end`` are missing, or when the span is
    not strictly positive.
    """
    if all_day or start is None or end is None:
        return None
    minutes = int((end - start).total_seconds() // 60)
    return minutes if minutes > 0 else None


# ---------------------------------------------------------------------------
# Task status -> calendar status mapping
# ---------------------------------------------------------------------------

#: doto status -> iCalendar VEVENT STATUS. Unknown statuses fall back to
#: CONFIRMED (a normal, scheduled event).
_EVENT_STATUS = {
    "done": "CONFIRMED",
    "open": "CONFIRMED",
    "in-progress": "CONFIRMED",
    "blocked": "TENTATIVE",
}

#: doto status -> iCalendar VTODO STATUS.
_TODO_STATUS = {
    "done": "COMPLETED",
    "open": "NEEDS-ACTION",
    "in-progress": "IN-PROCESS",
    "blocked": "NEEDS-ACTION",
}


def _parse_hhmm(value: str, fallback: time) -> time:
    """Parse an ``HH:MM`` config string into a naive time, tolerant of errors.

    Args:
        value: The configured ``HH:MM`` string (may be empty/invalid).
        fallback: Time to use when ``value`` can't be parsed.

    Returns:
        A naive :class:`datetime.time`.
    """
    try:
        hh, mm = value.strip().split(":", 1)
        return time(hour=int(hh), minute=int(mm))
    except (ValueError, AttributeError):
        return fallback


def _slot_within_workday(
    start: time,
    duration: timedelta,
    workday_start: time,
    workday_end: time,
    break_start: time,
    break_end: time,
) -> time:
    """Nudge a start time out of the break window and into the workday.

    The projection is deliberately simple and deterministic (no multi-task
    bin-packing): a single start time is adjusted so a task's event does not
    begin before the workday starts and does not *overlap* the daily break.
    Overlap is checked against the whole event interval ``[start, start +
    duration)`` -- so an event that would *start* just before the break but
    *end* inside it is also pushed to ``break_end``. An event may still end
    after ``workday_end`` (we don't truncate), which keeps a late task visible
    rather than silently dropping its tail.

    Args:
        start: Proposed naive start time.
        duration: Event duration (used to detect break overlap by end time).
        workday_start: Start of the working day.
        workday_end: End of the working day.
        break_start: Start of the daily break.
        break_end: End of the daily break.

    Returns:
        An adjusted naive start time.
    """
    # Clamp below the workday start.
    if start < workday_start:
        start = workday_start
    # Push the start to break-end when the event *interval* intersects the
    # break window. Two naive times are compared via a same-day datetime so the
    # duration can extend the end past midnight-safe boundaries consistently.
    base = datetime(2000, 1, 1)
    start_dt = datetime.combine(base, start)
    end_dt = start_dt + duration
    break_start_dt = datetime.combine(base, break_start)
    break_end_dt = datetime.combine(base, break_end)
    # Interval overlap test: [start, end) intersects [break_start, break_end).
    if start_dt < break_end_dt and end_dt > break_start_dt:
        start = break_end
    return start


def project_task_to_event(
    task_id: str,
    task: dict[str, Any],
    cal: CalendarConfig,
    back_reference: str | None = None,
) -> CalendarEvent:
    """Project a doto task onto a provider-neutral :class:`CalendarEvent`.

    This is the heart of the mapping. It honours the configured ``event_mode``
    and, for events, the workday/break projection:

    * ``event_mode == "todo"`` -> a VTODO with a ``due`` (date or datetime).
    * ``event_mode == "event"`` and the due has a **time** -> a timed VEVENT of
      the task's ``estimate`` (when set) or ``event_duration_minutes``, nudged
      out of the break window.
    * ``event_mode == "event"`` and the due is **date-only**:
        - ``all_day_for_dateless`` True -> an all-day VEVENT on that date.
        - otherwise -> a timed VEVENT starting at ``workday_start``.

    Args:
        task_id: The doto task id (used for the stable UID and back-reference).
        task: The task data dict (title, body, due, status, tags, ...).
        cal: The resolved calendar configuration.
        back_reference: Optional short string (e.g. ``repo#id``) appended to the
            description so the calendar item points back at the task.

    Returns:
        A fully populated :class:`CalendarEvent`.

    Raises:
        ValueError: If the task has no ``due`` (nothing to place on a calendar).
    """
    due_raw = task.get("due")
    due = DotoDate.parse_safe(due_raw)
    if due is None:
        raise ValueError(f"Task {task_id!r} has no due date; nothing to schedule.")

    summary = str(task.get("title") or task_id)
    status = str(task.get("status") or "open")
    tags = list(task.get("tags") or [])
    body = str(task.get("body") or "").strip()

    description_parts: list[str] = []
    if body:
        description_parts.append(body)
    ref = back_reference or task_id
    description_parts.append(f"{BACK_REFERENCE_OPEN}{ref}{BACK_REFERENCE_CLOSE}")
    description = "\n\n".join(description_parts)

    mode = (cal.event_mode or "event").lower()

    if mode == "todo":
        return CalendarEvent(
            uid=make_uid(task_id),
            kind=EventKind.TODO,
            summary=summary,
            description=description,
            due=due.to_datetime(),
            status=_TODO_STATUS.get(status, "NEEDS-ACTION"),
            categories=tags,
            task_id=task_id,
        )

    # --- event mode ---------------------------------------------------------
    # Prefer a per-task estimate (expected duration, in minutes) when present;
    # fall back to the calendar's global ``event_duration_minutes``. This lets
    # a task carrying ``:estimate: 4h`` project a 4-hour block while a dateless
    # chore keeps the default slot size. Parsing is forgiving so malformed
    # stored data cannot break a push (it just falls back to the default).
    from doxtr_doto.date_utils import parse_duration_safe

    estimate_minutes = parse_duration_safe(task.get("estimate"))
    if estimate_minutes is None:
        estimate_minutes = int(cal.event_duration_minutes)
    duration = timedelta(minutes=max(1, estimate_minutes))

    if not due.has_time:
        if cal.all_day_for_dateless:
            start_dt = datetime.combine(due.date, time())
            end_dt = start_dt + timedelta(days=1)  # all-day: exclusive next day
            return CalendarEvent(
                uid=make_uid(task_id),
                kind=EventKind.EVENT,
                summary=summary,
                description=description,
                start=start_dt,
                end=end_dt,
                all_day=True,
                status=_EVENT_STATUS.get(status, "CONFIRMED"),
                categories=tags,
                task_id=task_id,
            )
        # Project a date-only due onto the start of the working day.
        workday_start = _parse_hhmm(cal.workday_start, time(8, 0))
        start_time = workday_start
    else:
        start_time = due.time or time()

    workday_start = _parse_hhmm(cal.workday_start, time(8, 0))
    workday_end = _parse_hhmm(cal.workday_end, time(17, 0))
    break_start = _parse_hhmm(cal.break_start, time(12, 0))
    break_end = _parse_hhmm(cal.break_end, time(13, 0))

    adjusted = _slot_within_workday(
        start_time, duration, workday_start, workday_end, break_start, break_end
    )
    start_dt = datetime.combine(due.date, adjusted)
    end_dt = start_dt + duration

    return CalendarEvent(
        uid=make_uid(task_id),
        kind=EventKind.EVENT,
        summary=summary,
        description=description,
        start=start_dt,
        end=end_dt,
        all_day=False,
        status=_EVENT_STATUS.get(status, "CONFIRMED"),
        categories=tags,
        task_id=task_id,
    )


# ---------------------------------------------------------------------------
# Projection extension point
# ---------------------------------------------------------------------------
#: Signature of a Task->Event projector: ``(task_id, task, cal, back_reference)``.
Projector = Callable[[str, dict[str, Any], "CalendarConfig", "str | None"], CalendarEvent]

#: The active projector. Defaults to the built-in :func:`project_task_to_event`;
#: a downstream can swap it via :func:`register_projector` to customize the
#: Task->Event mapping independently of the transport layer, mirroring
#: ``register_directive_renderer`` in :mod:`doxtr_doto.sync.rst_writer`.
_PROJECTOR: Projector = project_task_to_event


def register_projector(fn: Projector) -> None:
    """Replace the Task->Event projection used by the sync engine.

    Downstream extension point: a child project can customize how a task maps
    to a calendar item (duration logic, extra categories, VTODO handling, ...)
    without editing core and without touching any provider/transport code.

    Args:
        fn: The replacement projector. It must accept ``(task_id, task, cal,
            back_reference)`` and return a :class:`CalendarEvent`, raising
            ``ValueError`` for a task that cannot be scheduled.
    """
    global _PROJECTOR
    _PROJECTOR = fn


def project(
    task_id: str,
    task: dict[str, Any],
    cal: CalendarConfig,
    back_reference: str | None = None,
) -> CalendarEvent:
    """Project a task via the active projector (see :func:`register_projector`).

    This is the entry point the engine calls; it delegates to the built-in
    :func:`project_task_to_event` unless a downstream has registered its own.
    """
    return _PROJECTOR(task_id, task, cal, back_reference)
