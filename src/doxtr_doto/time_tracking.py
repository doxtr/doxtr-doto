"""Pure functions for session time tracking.

This module provides the computational core for per-task work sessions
(worklogs). A worklog is a dict with ``started_at`` (ISO 8601) and
``stopped_at`` (ISO 8601 or ``None`` for an open/running session).

All functions are pure: they do not mutate their inputs and do not perform
I/O. Functions that "modify" a worklog list return a new list instead.

Timestamps are stored as ISO 8601 strings. Datetimes passed in and parsed
are expected to be timezone-aware; naive datetimes are treated as being in
the local timezone so that elapsed calculations remain consistent.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from doxtr_doto.sync.json_store import WorkLog


def now_iso(now: datetime | None = None) -> str:
    """Return the current time as a timezone-aware ISO 8601 string.

    Args:
        now: Override for the current time (useful for tests). If None,
            the current local time with timezone info is used.

    Returns:
        ISO 8601 timestamp string including timezone offset.
    """
    moment = now if now is not None else datetime.now(timezone.utc).astimezone()
    return _ensure_aware(moment).isoformat()


def _ensure_aware(moment: datetime) -> datetime:
    """Return a timezone-aware datetime.

    Naive datetimes are assumed to be in the local timezone.

    Args:
        moment: The datetime to normalize.

    Returns:
        A timezone-aware datetime.
    """
    if moment.tzinfo is None:
        return moment.astimezone()
    return moment


def parse_timestamp(value: str) -> datetime:
    """Parse an ISO 8601 timestamp into a timezone-aware datetime.

    Args:
        value: ISO 8601 timestamp string.

    Returns:
        A timezone-aware datetime. Naive inputs are assumed local time.
    """
    return _ensure_aware(datetime.fromisoformat(value))


def open_session(worklogs: list[WorkLog]) -> WorkLog | None:
    """Return the currently open (running) worklog, if any.

    An open session is one whose ``stopped_at`` is None. If multiple open
    sessions exist (an inconsistent state), the first one is returned.

    Args:
        worklogs: List of worklog intervals.

    Returns:
        The open worklog dict, or None if no session is running.
    """
    for log in worklogs:
        if log.get("stopped_at") is None:
            return log
    return None


def has_open_session(worklogs: list[WorkLog]) -> bool:
    """Return whether any worklog is currently open.

    Args:
        worklogs: List of worklog intervals.

    Returns:
        True if a running session exists, False otherwise.
    """
    return open_session(worklogs) is not None


def elapsed_seconds(worklogs: list[WorkLog], now: datetime | None = None) -> int:
    """Compute total elapsed seconds across all worklogs.

    Closed intervals contribute ``stopped_at - started_at``. Open intervals
    contribute ``now - started_at``. Negative intervals (where the stop
    precedes the start) are clamped to zero.

    Args:
        worklogs: List of worklog intervals.
        now: Reference "current" time for open sessions. Defaults to the
            current local time. Should be timezone-aware; naive values are
            assumed to be local time.

    Returns:
        Total elapsed time in whole seconds (floored).
    """
    reference = _ensure_aware(now) if now is not None else datetime.now(timezone.utc).astimezone()

    total = 0.0
    for log in worklogs:
        started_raw = log.get("started_at")
        if not started_raw:
            continue
        started = parse_timestamp(started_raw)
        stopped_raw = log.get("stopped_at")
        stopped = parse_timestamp(stopped_raw) if stopped_raw else reference
        delta = (stopped - started).total_seconds()
        if delta > 0:
            total += delta
    return int(total)


def detect_overnight(worklogs: list[WorkLog], now: datetime | None = None) -> list[WorkLog]:
    """Return open sessions that started on a prior calendar day.

    These represent sessions a user likely forgot to stop (for example, an
    overnight session left running). Comparison uses the local calendar date
    of ``now``.

    Args:
        worklogs: List of worklog intervals.
        now: Reference "current" time. Defaults to current local time.

    Returns:
        List of open worklogs whose start date is before ``now``'s date.
    """
    reference = _ensure_aware(now) if now is not None else datetime.now(timezone.utc).astimezone()
    today = reference.date()

    stale: list[WorkLog] = []
    for log in worklogs:
        if log.get("stopped_at") is not None:
            continue
        started_raw = log.get("started_at")
        if not started_raw:
            continue
        started = parse_timestamp(started_raw)
        if started.date() < today:
            stale.append(log)
    return stale


def close_session(worklogs: list[WorkLog], now: datetime | None = None) -> list[WorkLog]:
    """Return a new worklog list with the open session closed at ``now``.

    If there is no open session, the input is returned unchanged (as a copy).

    Args:
        worklogs: List of worklog intervals.
        now: Stop timestamp to apply. Defaults to current local time.

    Returns:
        A new list where the open session (if any) has ``stopped_at`` set.
    """
    stop_at = now_iso(now)
    result: list[WorkLog] = []
    closed = False
    for log in worklogs:
        if not closed and log.get("stopped_at") is None:
            result.append({"started_at": log["started_at"], "stopped_at": stop_at})
            closed = True
        else:
            result.append(dict(log))  # type: ignore[arg-type]
    return result


def start_session(worklogs: list[WorkLog], now: datetime | None = None) -> list[WorkLog]:
    """Return a new worklog list with a fresh open session appended.

    Any already-open session is left as-is; callers that want a single open
    session should close first (see :func:`close_session`).

    Args:
        worklogs: List of worklog intervals.
        now: Start timestamp to apply. Defaults to current local time.

    Returns:
        A new list with a new open worklog appended.
    """
    start_at = now_iso(now)
    result: list[WorkLog] = [dict(log) for log in worklogs]  # type: ignore[misc]
    result.append({"started_at": start_at, "stopped_at": None})
    return result


def discard_session(worklogs: list[WorkLog]) -> list[WorkLog]:
    """Return a new worklog list with the open session removed.

    Useful for recovering from a forgotten/overnight session where the
    elapsed time should not be counted. If no session is open, the input is
    returned unchanged (as a copy).

    Args:
        worklogs: List of worklog intervals.

    Returns:
        A new list with the first open session removed.
    """
    result: list[WorkLog] = []
    dropped = False
    for log in worklogs:
        if not dropped and log.get("stopped_at") is None:
            dropped = True
            continue
        result.append(dict(log))  # type: ignore[arg-type]
    return result


def split_at_midnight(worklogs: list[WorkLog], now: datetime | None = None) -> list[WorkLog]:
    """Split the open session at the midnight boundary before ``now``.

    If an open session started on a prior calendar day, it is closed at the
    start of ``now``'s day (local midnight) and a new open session is started
    from that midnight. This keeps per-day accounting accurate when a session
    spans days.

    If there is no open session, or the open session started today, the input
    is returned unchanged (as a copy).

    Args:
        worklogs: List of worklog intervals.
        now: Reference "current" time. Defaults to current local time.

    Returns:
        A new worklog list with the overnight open session split at midnight.
    """
    reference = _ensure_aware(now) if now is not None else datetime.now(timezone.utc).astimezone()
    midnight = datetime.combine(reference.date(), datetime.min.time(), tzinfo=reference.tzinfo)

    result: list[WorkLog] = []
    split_done = False
    for log in worklogs:
        if not split_done and log.get("stopped_at") is None and log.get("started_at"):
            started = parse_timestamp(log["started_at"])
            if started < midnight:
                # Close the pre-midnight portion at (midnight - 1 microsecond)
                # boundary represented by midnight itself, then reopen at
                # midnight so the two intervals do not overlap.
                boundary = midnight - timedelta(microseconds=0)
                result.append(
                    {
                        "started_at": log["started_at"],
                        "stopped_at": boundary.isoformat(),
                    }
                )
                result.append({"started_at": midnight.isoformat(), "stopped_at": None})
                split_done = True
                continue
        result.append(dict(log))  # type: ignore[arg-type]
    return result


def set_interval(
    worklogs: list[WorkLog],
    index: int,
    started_at: str,
    stopped_at: str | None,
) -> list[WorkLog]:
    """Return a new worklog list with interval ``index`` replaced.

    Pure editing primitive used by the TUI/CLI time-management UI to adjust a
    single work-clock interval's start/stop timestamps (mirroring the way a
    finished doto's session can be edited).

    Args:
        worklogs: List of worklog intervals.
        index: Zero-based index of the interval to replace.
        started_at: New ISO 8601 start timestamp.
        stopped_at: New ISO 8601 stop timestamp, or None to leave it open.

    Returns:
        A new list with the interval at ``index`` replaced.

    Raises:
        IndexError: If ``index`` is out of range.
    """
    if index < 0 or index >= len(worklogs):
        raise IndexError(f"worklog index {index} out of range")
    result: list[WorkLog] = [dict(log) for log in worklogs]  # type: ignore[misc]
    result[index] = {"started_at": started_at, "stopped_at": stopped_at}
    return result


def add_interval(
    worklogs: list[WorkLog],
    started_at: str,
    stopped_at: str | None,
) -> list[WorkLog]:
    """Return a new worklog list with an interval appended.

    Args:
        worklogs: List of worklog intervals.
        started_at: ISO 8601 start timestamp.
        stopped_at: ISO 8601 stop timestamp, or None for an open session.

    Returns:
        A new list with the interval appended, re-sorted by start time.
    """
    result: list[WorkLog] = [dict(log) for log in worklogs]  # type: ignore[misc]
    result.append({"started_at": started_at, "stopped_at": stopped_at})
    result.sort(key=lambda log: log.get("started_at") or "")
    return result


def remove_interval(worklogs: list[WorkLog], index: int) -> list[WorkLog]:
    """Return a new worklog list with interval ``index`` removed.

    Args:
        worklogs: List of worklog intervals.
        index: Zero-based index of the interval to remove.

    Returns:
        A new list without the interval at ``index``.

    Raises:
        IndexError: If ``index`` is out of range.
    """
    if index < 0 or index >= len(worklogs):
        raise IndexError(f"worklog index {index} out of range")
    return [dict(log) for i, log in enumerate(worklogs) if i != index]  # type: ignore[misc]
