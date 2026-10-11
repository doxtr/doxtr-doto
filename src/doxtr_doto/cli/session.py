"""Session time-tracking helpers and rendering for the doto CLI.

This module centralizes the logic shared by the time-tracking verbs
(``start``, ``stop``, ``clock-out``, ``status``, ``log``):

* deriving a repository name for the current project (used for namespaced
  ``repo#id`` display),
* resolving the active focus session against the current task store,
* formatting durations, and
* rendering ``status`` / ``log`` output.

Presentation logic is kept behind small, overridable functions so a child
theme or alternate renderer can replace it without touching command logic.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from doxtr_doto.cli.id_resolver import (
    namespaced_id,
)
from doxtr_doto.cli.id_resolver import (
    split_task_ref as split_namespaced_id,
)
from doxtr_doto.cli.output import (
    PRIORITY_COLORS,
    STATUS_COLORS,
)
from doxtr_doto.sync.json_store import WorkLog
from doxtr_doto.time_tracking import (
    elapsed_seconds,
    open_session,
    parse_timestamp,
)

if TYPE_CHECKING:
    from doxtr_doto.cli.config import DotoConfig
    from doxtr_doto.cli.json_store import JsonTaskStore
    from doxtr_doto.cli.output import OutputFormatter

WORK_REPO = "work"
"""Sentinel repo name used for the Layer-1 global work clock."""

# ``namespaced_id`` / ``split_namespaced_id`` are canonically defined in
# :mod:`doxtr_doto.cli.id_resolver` and re-exported here for the session API's
# historical callers (one source of truth, backwards-compatible names).
__all__ = [
    "WORK_REPO",
    "derive_repo_name",
    "format_duration",
    "interval_rows",
    "live_focus_elapsed",
    "namespaced_id",
    "render_log",
    "render_status",
    "resolve_session_store",
    "session_display_id",
    "split_namespaced_id",
    "work_elapsed_today",
]


def resolve_session_store(
    current_store: JsonTaskStore,
    json_path: str | None,
) -> JsonTaskStore:
    """Return the task store that owns an active session.

    If the session recorded a ``json_path`` different from the current
    store's path, a store for that path is returned; otherwise the current
    store is reused.

    Args:
        current_store: The store for the current working directory.
        json_path: Absolute path recorded on the active session, if any.

    Returns:
        The task store that holds the session's worklogs.
    """
    from doxtr_doto.cli.json_store import JsonTaskStore

    if json_path and json_path != str(current_store.path):
        return JsonTaskStore(json_path)
    return current_store


def derive_repo_name(config: DotoConfig) -> str:
    """Derive a short repository name for namespaced display.

    The name is the final path component of the project's source directory.
    This is used to build ``repo#id`` identifiers and to label the active
    session.

    Args:
        config: The loaded CLI configuration.

    Returns:
        The repository name (never empty; falls back to ``"repo"``).
    """
    source = config.source_dir.resolve()
    name = source.name
    return name or "repo"


def work_elapsed_today(worklogs: list[WorkLog], now: datetime) -> int:
    """Compute today's elapsed work-clock seconds.

    Intervals are counted only for the portion that falls on ``now``'s local
    calendar date. Open intervals are counted up to ``now``. Shared by
    ``doto status`` and the TUI status line so the two always agree.

    Args:
        worklogs: The work clock's worklog intervals.
        now: Reference "current" time.

    Returns:
        Elapsed seconds on the work clock for today.
    """
    today = now.date()
    todays: list[WorkLog] = []
    for log in worklogs:
        started_raw = log.get("started_at")
        if not started_raw:
            continue
        if parse_timestamp(started_raw).date() == today:
            todays.append(log)
    return elapsed_seconds(todays, now=now)


def format_duration(total_seconds: int) -> str:
    """Format a duration in seconds as a compact ``HhMmSs`` string.

    Args:
        total_seconds: Duration in whole seconds. Negative values are
            clamped to zero.

    Returns:
        A compact human-readable string, e.g. ``"1h02m03s"``, ``"5m00s"``,
        or ``"0s"``.
    """
    seconds = max(0, int(total_seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{secs:02d}s"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def render_time_spent_line(
    worklogs: list[WorkLog],
    now: datetime | None = None,
) -> str | None:
    """Return a ``Time spent`` detail line for a task's worklogs (or ``None``).

    This answers "how long have I been working on this task": it sums every
    worklog interval via :func:`doxtr_doto.time_tracking.elapsed_seconds` and
    formats the total with :func:`format_duration`. Because
    :func:`elapsed_seconds` counts an *open* (running) session up to ``now``,
    the line reflects a live, in-progress session - the elapsed value keeps
    growing while the timer runs - without any special-casing here.

    The line uses ``[style]...[/style]`` markup understood by both rich and
    Textual, matching the shared card builder
    (:func:`doxtr_doto.cli.output.build_task_detail_lines`): ``Time spent:``
    followed by the formatted duration (e.g. ``"1h02m03s"``).

    Edge case - *no time tracked*: when the task has no worklogs, or they sum
    to zero elapsed seconds, this returns ``None`` so the caller omits the
    line entirely. Omitting (rather than showing ``"0s"``) keeps the card
    uncluttered for the common case of a task nobody has clocked time on; the
    field only appears once there is real time to report.

    Overridable by child themes that register a replacement via
    :func:`register_time_spent_renderer`.

    Args:
        worklogs: The task's worklog intervals (may be empty).
        now: Reference "current" time for open sessions (defaults to the
            current local time inside :func:`elapsed_seconds`).

    Returns:
        The ``Time spent`` detail line (rich/Textual markup), or ``None`` when
        there is no tracked time.
    """
    return _time_spent_renderer(worklogs, now)


def _default_time_spent_renderer(
    worklogs: list[WorkLog],
    now: datetime | None = None,
) -> str | None:
    """Built-in ``Time spent`` renderer (omits the line when nothing tracked)."""
    if not worklogs:
        return None
    total = elapsed_seconds(worklogs, now=now)
    if total <= 0:
        return None
    return f"[bold]Time spent:[/bold] {format_duration(total)}"


#: Signature of a time-spent renderer: ``(worklogs, now) -> line | None``.
TimeSpentRenderer = Callable[["list[WorkLog]", "datetime | None"], "str | None"]

#: THE active ``Time spent`` renderer (modularity seam for child themes).
#: Reassign via :func:`register_time_spent_renderer`.
_time_spent_renderer: TimeSpentRenderer = _default_time_spent_renderer


def register_time_spent_renderer(fn: TimeSpentRenderer) -> None:
    """Replace the renderer used by :func:`render_time_spent_line`.

    Args:
        fn: A callable ``(worklogs, now) -> str | None``.
    """
    global _time_spent_renderer
    _time_spent_renderer = fn


def reset_time_spent_renderer() -> None:
    """Reset the ``Time spent`` renderer to the built-in default."""
    global _time_spent_renderer
    _time_spent_renderer = _default_time_spent_renderer


def session_display_id(
    active_session: dict[str, Any] | None,
    current_repo: str,
) -> str | None:
    """Return the display identifier for an active session.

    When the active session belongs to the current repository (local scope),
    the ``repo#`` prefix is hidden. Otherwise the full ``repo#id`` is shown.

    Args:
        active_session: The active session dict (``{"repo", "task_id"}``) or
            None.
        current_repo: The repository name for the current project.

    Returns:
        The display identifier, or None if there is no active session.
    """
    if not active_session:
        return None
    repo = active_session.get("repo")
    task_id = str(active_session.get("task_id", ""))
    if repo and repo != current_repo:
        return namespaced_id(repo, task_id)
    return task_id


def _status_style(status: str) -> str:
    """Return the rich style for a task status.

    Args:
        status: The task status value.

    Returns:
        A rich style string (possibly empty).
    """
    return STATUS_COLORS.get(status, "")


def _priority_style(priority: str) -> str:
    """Return the rich style for a task priority.

    Args:
        priority: The task priority value.

    Returns:
        A rich style string (possibly empty).
    """
    return PRIORITY_COLORS.get(priority, "")


def render_status(
    formatter: OutputFormatter,
    *,
    focus_display_id: str | None,
    focus_title: str | None,
    focus_status: str | None,
    focus_priority: str | None,
    focus_elapsed: int,
    work_running: bool,
    work_today_elapsed: int,
) -> None:
    """Render the ``status`` output.

    Presentation is isolated here so an alternate renderer can override it.

    Args:
        formatter: The output formatter.
        focus_display_id: Display id of the active focus task, or None.
        focus_title: Title of the active focus task, or None.
        focus_status: Status of the active focus task, or None.
        focus_priority: Priority of the active focus task, or None.
        focus_elapsed: Live elapsed seconds for the active focus session.
        work_running: Whether the global work clock is currently running.
        work_today_elapsed: Elapsed seconds on the work clock for today.
    """
    if focus_display_id is None:
        formatter.print("No active focus session.")
    else:
        p_style = _priority_style(focus_priority or "")
        s_style = _status_style(focus_status or "")
        title = focus_title or ""
        if formatter.console is not None:
            formatter.console.print(
                f"[bold]▶ {focus_display_id}[/bold] - {title} "
                f"[{p_style}]({focus_priority})[/{p_style}] "
                f"[{s_style}][{focus_status}][/{s_style}]"
            )
            formatter.console.print(f"  Focus: [cyan]{format_duration(focus_elapsed)}[/cyan]")
        else:
            formatter.print(f"> {focus_display_id} - {title} ({focus_priority}) [{focus_status}]")
            formatter.print(f"  Focus: {format_duration(focus_elapsed)}")

    clock_state = "running" if work_running else "stopped"
    clock_line = f"Work clock ({clock_state}): {format_duration(work_today_elapsed)} today"
    if formatter.console is not None:
        style = "green" if work_running else "dim"
        formatter.console.print(f"[{style}]{clock_line}[/{style}]")
    else:
        formatter.print(clock_line)


def interval_rows(
    worklogs: list[WorkLog],
    now: datetime | None,
    day: str | None,
) -> list[tuple[str, str, str, bool]]:
    """Build display rows for session intervals.

    Args:
        worklogs: The task's worklog intervals.
        now: Reference time for open sessions.
        day: Optional ISO date (``YYYY-MM-DD``) to filter by start date.

    Returns:
        A list of ``(start, stop, duration, is_open)`` tuples.
    """
    rows: list[tuple[str, str, str, bool]] = []
    for log in worklogs:
        started_raw = log.get("started_at")
        if not started_raw:
            continue
        started = parse_timestamp(started_raw)
        if day and started.date().isoformat() != day:
            continue
        stopped_raw = log.get("stopped_at")
        is_open = stopped_raw is None
        duration = elapsed_seconds([log], now=now)
        stop_display = stopped_raw if stopped_raw else "(running)"
        rows.append((started_raw, stop_display, format_duration(duration), is_open))
    return rows


def render_log(
    formatter: OutputFormatter,
    *,
    display_id: str,
    worklogs: list[WorkLog],
    now: datetime | None = None,
    day: str | None = None,
) -> None:
    """Render the per-task session interval log.

    Presentation is isolated here so an alternate renderer can override it.

    Args:
        formatter: The output formatter.
        display_id: The task display id (``repo#id`` or bare ``id``).
        worklogs: The task's worklog intervals.
        now: Reference time for open sessions.
        day: Optional ISO date (``YYYY-MM-DD``) to filter by start date.
    """
    rows = interval_rows(worklogs, now, day)
    if not rows:
        scope = f" on {day}" if day else ""
        formatter.print(f"No sessions for {display_id}{scope}.")
        return

    header = f"Sessions for {display_id}"
    if day:
        header += f" on {day}"
    formatter.print(header)
    total = elapsed_seconds([log for log in worklogs if _matches_day(log, day)], now=now)
    for start, stop, duration, is_open in rows:
        marker = "▶ " if is_open else "  "
        line = f"{marker}{start}  ->  {stop}  ({duration})"
        if formatter.console is not None and is_open:
            formatter.console.print(f"[cyan]{line}[/cyan]")
        else:
            formatter.print(line)
    formatter.print(f"Total: {format_duration(total)}")


def _matches_day(log: WorkLog, day: str | None) -> bool:
    """Return whether a worklog's start date matches the given day filter.

    Args:
        log: A worklog interval.
        day: Optional ISO date (``YYYY-MM-DD``) filter.

    Returns:
        True if there is no filter or the start date matches.
    """
    if not day:
        return True
    started_raw = log.get("started_at")
    if not started_raw:
        return False
    return parse_timestamp(started_raw).date().isoformat() == day


def live_focus_elapsed(
    worklogs: list[WorkLog],
    now: datetime | None = None,
) -> int:
    """Return the elapsed seconds for the currently open focus session.

    Only the open interval is counted (not historical closed intervals),
    matching the "live" session timer semantics expected by ``status``.

    Args:
        worklogs: The task's worklog intervals.
        now: Reference time for the open session.

    Returns:
        Elapsed seconds for the open session, or 0 if none is open.
    """
    open_log = open_session(worklogs)
    if open_log is None:
        return 0
    return elapsed_seconds([open_log], now=now)
