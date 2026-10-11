"""Global cross-repo state stored in ~/.config/doto/config.json.

This module manages state that is not tied to a single project: the registry
of discovered repositories, favorites, the currently active focus session, the
global daily work clock, and daily-nudge dedupe metadata.

Location resolution (read, highest priority first):

1. ``$DOTO_CONFIG`` environment variable (explicit path to a config file).
2. A ``.doto/config.json`` found by walking **up** from the current working
   directory (portable, survives ephemeral container restarts, and can live
   under version control alongside ``.doto/tasks.json``).
3. ``$XDG_CONFIG_HOME``/``doto/config.json`` (falling back to
   ``~/.config/doto/config.json``).

First-run *write* target (when no config exists yet) mirrors this intent
without surprising writes in arbitrary directories:

1. ``$DOTO_CONFIG`` if set.
2. ``<project-root>/.doto/config.json`` when a project root is detected.
3. ``~/.config/doto/config.json`` otherwise.

The on-disk shape is::

    {
        "version": 1,
        "repositories": [ {"name": str, "path": str}, ... ],
        "favorites": [ str, ... ],
        "active_session": {"repo": str, "task_id": str, "json_path": str} | None,
        "work_clock": {"worklogs": [ {"started_at": str, "stopped_at": str|None} ]},
        "breaks": [ {"name": str, "time": "HH:MM",
                     "duration_minutes": int, "leeway_minutes": int,
                     "auto_deduct": bool}, ... ],
        "workweek_days": [ int, ... ],  # Mon=0 .. Sun=6; default [0,1,2,3,4]
        "last_prompt_date": str | None,
        "tui_layout": str | None,
        "tui_hide_completed": bool,
        "tui_due_filter": str | None,
        "tui_tag_filter": str | None,
        "tui_priority_filter": str | None,
        "tui_sort_key": str | None,
        "tui_sort_order": str | None,
        "tui_repo_filter": [ str, ... ] | None
    }

Writes are atomic (temp file + rename), matching the pattern used by
:class:`doxtr_doto.sync.json_store.JsonTaskStore`.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from doxtr_doto.sync.json_store import WorkLog

GLOBAL_STATE_VERSION = 1

CONFIG_ENV_VAR = "DOTO_CONFIG"
"""Environment variable holding an explicit path to the global config file."""

DEFAULT_BREAK_LEEWAY_MINUTES = 30
"""Default drift/leeway (minutes) around a break's nominal time."""

DEFAULT_WORKWEEK_DAYS = [0, 1, 2, 3, 4]
"""Default "work week" weekday set: Monday-Friday.

Weekdays use Python's :meth:`datetime.date.weekday` convention where Monday is
``0`` and Sunday is ``6``.
"""


def sanitize_workweek_days(value: object) -> list[int]:
    """Normalize a stored ``workweek_days`` value into a valid weekday set.

    Keeps only integers in the ``0..6`` range (Python's Monday=0 .. Sunday=6
    convention), de-duplicates them, and returns them sorted ascending. A
    missing, empty, or wholly invalid value falls back to
    :data:`DEFAULT_WORKWEEK_DAYS` (Monday-Friday).

    Args:
        value: The raw stored value (any type; defensively validated).

    Returns:
        A sorted, de-duplicated list of weekday numbers in ``0..6``; the
        Monday-Friday default when nothing valid is present.
    """
    if not isinstance(value, (list, tuple)):
        return list(DEFAULT_WORKWEEK_DAYS)
    days: set[int] = set()
    for item in value:
        # Reject bools (a subclass of int) and out-of-range values.
        if isinstance(item, bool) or not isinstance(item, int):
            continue
        if 0 <= item <= 6:
            days.add(item)
    if not days:
        return list(DEFAULT_WORKWEEK_DAYS)
    return sorted(days)


def xdg_config_path() -> Path:
    """Return the ``~/.config``-style global config path.

    Respects ``XDG_CONFIG_HOME`` and falls back to ``~/.config``.

    Returns:
        Path to ``<config dir>/doto/config.json``.
    """
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "doto" / "config.json"


def _env_config_path() -> Path | None:
    """Return the config path from ``$DOTO_CONFIG`` if set, else None."""
    raw = os.environ.get(CONFIG_ENV_VAR)
    if not raw:
        return None
    return Path(raw).expanduser()


def _find_portable_config(start: Path | None = None) -> Path | None:
    """Walk up from ``start`` looking for an existing ``.doto/config.json``.

    Args:
        start: Starting directory (defaults to cwd).

    Returns:
        The path to the first existing ``.doto/config.json`` found, or None.
    """
    current = (start or Path.cwd()).resolve()
    while True:
        candidate = current / ".doto" / "config.json"
        if candidate.exists():
            return candidate
        if current == current.parent:
            return None
        current = current.parent


def resolve_global_config_path(start: Path | None = None) -> Path:
    """Resolve the global config path for *reading*.

    Search order (highest priority first):

    1. ``$DOTO_CONFIG`` environment variable.
    2. A ``.doto/config.json`` found by walking up from ``start``/cwd.
    3. ``$XDG_CONFIG_HOME``/``doto/config.json`` (``~/.config`` fallback).

    The returned path is where doto will *read* from. It may not exist yet
    (callers return a default state in that case). Use
    :func:`resolve_global_config_write_path` to decide where to create a
    config on first run.

    Args:
        start: Starting directory for the portable lookup (defaults to cwd).

    Returns:
        The resolved config path.
    """
    env_path = _env_config_path()
    if env_path is not None:
        return env_path
    portable = _find_portable_config(start)
    if portable is not None:
        return portable
    return xdg_config_path()


def resolve_global_config_write_path(start: Path | None = None) -> Path:
    """Resolve where to *create* the global config on first run.

    Write order (highest priority first):

    1. ``$DOTO_CONFIG`` if set.
    2. ``<project-root>/.doto/config.json`` when a project root is detected
       (via :func:`doxtr_doto.cli.config.find_project_root`).
    3. ``~/.config/doto/config.json`` otherwise.

    If a config already exists anywhere in the read search order, that
    existing path is returned so first-run detection does not clobber it.

    Args:
        start: Starting directory (defaults to cwd).

    Returns:
        The path to create (or reuse) the config at.
    """
    env_path = _env_config_path()
    if env_path is not None:
        return env_path

    # Reuse an existing portable config instead of creating a new one.
    portable = _find_portable_config(start)
    if portable is not None:
        return portable

    # Fall back to a project-root-anchored portable location when inside a
    # project; otherwise the user-level config dir.
    from doxtr_doto.cli.config import find_project_root

    project_root = find_project_root(start)
    if project_root is not None:
        return project_root / ".doto" / "config.json"
    return xdg_config_path()


def default_config_path() -> Path:
    """Return the resolved global config path (read order).

    Retained as a backwards-compatible alias for
    :func:`resolve_global_config_path`.

    Returns:
        The resolved config path.
    """
    return resolve_global_config_path()


@dataclass
class WorkClock:
    """The global daily work clock (Layer 1 tracking).

    Attributes:
        worklogs: Session intervals for the global clock-in/clock-out.
    """

    worklogs: list[WorkLog] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for JSON storage.

        Returns:
            Dict with a ``worklogs`` key.
        """
        return {"worklogs": list(self.worklogs)}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> WorkClock:
        """Build a WorkClock from stored data.

        Args:
            data: Stored dict (or None).

        Returns:
            A WorkClock instance.
        """
        if not data:
            return cls()
        return cls(worklogs=list(data.get("worklogs", [])))


@dataclass
class BreakConfig:
    """A configurable recurring break for the work clock.

    By default a break is **not** auto-deducted: the real recorded clock-out
    gap (the time the user was clocked out mid-day) already represents the
    break and is excluded from gross, so nothing extra is subtracted. The
    report/TUI surface that recorded gap as an explicit break instead of
    silently removing a nominal duration.

    Setting ``auto_deduct=True`` restores the legacy behavior for users who do
    **not** clock out for breaks (they work straight through): the configured
    duration is deducted from a day's gross clocked time, minus any real
    clock-out gap that starts inside the break's window
    (``max(0, duration - gap_already_taken)``) so an explicit gap in the
    window is never double-counted.

    Attributes:
        name: Human label, e.g. ``"Lunch"``.
        time: Nominal break time as ``"HH:MM"`` (local wall-clock). Only used
            by the opt-in ``auto_deduct`` path to locate the break window.
        duration_minutes: Intended break length in minutes (opt-in deduction).
        leeway_minutes: Drift tolerance (minutes) on each side of ``time``;
            a clock-out gap whose start falls within this window is credited
            against this break under ``auto_deduct``. Defaults to
            :data:`DEFAULT_BREAK_LEEWAY_MINUTES`.
        auto_deduct: When True, auto-deduct the configured duration from gross
            (legacy straight-through behavior). Defaults to False so the
            headline behavior only ever counts real recorded break time and
            never double-counts.
        _extra: Unrecognized per-break keys preserved verbatim across a
            load/save round-trip, so a newer version's extra break fields are
            not silently dropped (forward compatibility at the break level).
    """

    name: str
    time: str
    duration_minutes: int
    leeway_minutes: int = DEFAULT_BREAK_LEEWAY_MINUTES
    auto_deduct: bool = False
    #: Unrecognized per-break keys, preserved verbatim so a newer version's
    #: extra break fields survive a load/save round-trip (forward compat),
    #: mirroring :attr:`GlobalState._extra` at the break level.
    _extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for JSON storage.

        Any unrecognized keys captured on load are merged back in so a newer
        version's extra break fields are never silently dropped on save.
        """
        data: dict[str, Any] = dict(self._extra)
        data.update(
            {
                "name": self.name,
                "time": self.time,
                "duration_minutes": int(self.duration_minutes),
                "leeway_minutes": int(self.leeway_minutes),
                "auto_deduct": bool(self.auto_deduct),
            }
        )
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BreakConfig:
        """Build a BreakConfig from stored data.

        Args:
            data: Stored dict with ``name``/``time``/``duration_minutes`` and
                optional ``leeway_minutes`` / ``auto_deduct``. An older file
                that predates ``auto_deduct`` loads it as ``False`` (the new
                safe default), so old data never double-counts. Unrecognized
                keys are captured in :attr:`_extra` so a newer version's extra
                break fields round-trip through the next save (forward compat).

        Returns:
            A BreakConfig instance.
        """
        known = {"name", "time", "duration_minutes", "leeway_minutes", "auto_deduct"}
        extra = {k: v for k, v in data.items() if k not in known}
        return cls(
            name=str(data.get("name", "")),
            time=str(data.get("time", "")),
            duration_minutes=int(data.get("duration_minutes", 0)),
            leeway_minutes=int(data.get("leeway_minutes", DEFAULT_BREAK_LEEWAY_MINUTES)),
            auto_deduct=bool(data.get("auto_deduct", False)),
            _extra=extra,
        )


@dataclass
class GlobalState:
    """Typed accessor for the global doto config file.

    Attributes:
        version: Schema version of the global state file.
        repositories: Registry of known repositories (name/path dicts).
        favorites: List of favorited repo names or namespaced task IDs.
        active_session: The currently active focus session, or None.
        work_clock: The global daily work clock.
        breaks: Configurable recurring breaks for the work clock. By default
            a break is the real recorded clock-out gap (already excluded from
            gross, surfaced not deducted); a break with ``auto_deduct=True``
            restores the legacy straight-through deduction (see
            :class:`BreakConfig`).
        workweek_days: The set of weekday numbers (Python's Monday=0 ..
            Sunday=6 convention) that count as the configurable "work week"
            for the ``time`` layout's summary panel work-week net total.
            Defaults to :data:`DEFAULT_WORKWEEK_DAYS` (Monday-Friday). On
            load the value is sanitized (ints in 0..6, de-duplicated, sorted;
            missing/empty/invalid falls back to the default).
        last_prompt_date: ISO date (YYYY-MM-DD) of the last kickstart nudge.
        tui_layout: The user's preferred ``doto tui`` task-list layout view
            (a :class:`doxtr_doto.enums.TuiLayout` value, e.g. ``"table"`` /
            ``"list"`` / ``"kanban"`` / ``"calendar"``). None means no
            preference has been saved yet, in which case the TUI falls back to
            the default table view (backward compatible with older state
            files that predate this field).
        tui_hide_completed: Whether the TUI filter/sort pop-up's "hide
            completed" filter is on. Part of the persisted filter/sort memory
            (:class:`doxtr_doto.cli.tui.filtersort.ViewPrefs`), restored on the
            next launch so the last filter/sort state is remembered.
        tui_due_filter: The persisted due-date filter choice (a
            :class:`doxtr_doto.enums.DueFilter` value). None means no
            preference saved (defaults to ``all``).
        tui_tag_filter: The persisted "only this tag" filter, or None/empty for
            no tag filter.
        tui_priority_filter: The persisted "only this priority" filter, or
            None/empty for no priority filter.
        tui_sort_key: The persisted sort key (a
            :class:`doxtr_doto.enums.SortKey` value, e.g. ``"due"`` /
            ``"priority"`` / ``"tag"`` / ``"next"``). None means no preference
            saved (defaults to ``none``). The LAST sort state is remembered
            across sessions via this field.
        tui_sort_order: The persisted sort direction (a
            :class:`doxtr_doto.enums.SortOrder` value, ``"asc"`` / ``"desc"``).
            None means no preference saved (defaults to ``asc``).
        tui_repo_filter: The persisted repository filter: the list of
            repository names the TUI's filter/sort pop-up (and the repo tree)
            restricts the task list to in GLOBAL scope. None or empty means no
            repo filter (all repositories' tasks are shown). Part of the
            persisted filter/sort memory
            (:class:`doxtr_doto.cli.tui.filtersort.ViewPrefs`), restored on the
            next launch.
    """

    version: int = GLOBAL_STATE_VERSION
    repositories: list[dict[str, Any]] = field(default_factory=list)
    favorites: list[str] = field(default_factory=list)
    active_session: dict[str, Any] | None = None
    work_clock: WorkClock = field(default_factory=WorkClock)
    breaks: list[BreakConfig] = field(default_factory=list)
    workweek_days: list[int] = field(default_factory=lambda: list(DEFAULT_WORKWEEK_DAYS))
    last_prompt_date: str | None = None
    tui_layout: str | None = None
    tui_hide_completed: bool = False
    tui_due_filter: str | None = None
    tui_tag_filter: str | None = None
    tui_priority_filter: str | None = None
    tui_sort_key: str | None = None
    tui_sort_order: str | None = None
    tui_repo_filter: list[str] | None = None
    #: Unrecognized top-level keys, preserved verbatim so a newer version's or
    #: plugin's extra config survives a load/save round-trip (forward compat).
    _extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the full state to a JSON-ready dict.

        Any unrecognized top-level keys captured on load are merged back in so
        they are never silently dropped on the next ``save()``.

        Returns:
            Dict matching the on-disk schema.
        """
        data: dict[str, Any] = dict(self._extra)
        data.update(
            {
                "version": self.version,
                "repositories": list(self.repositories),
                "favorites": list(self.favorites),
                "active_session": self.active_session,
                "work_clock": self.work_clock.to_dict(),
                "breaks": [b.to_dict() for b in self.breaks],
                "workweek_days": list(self.workweek_days),
                "last_prompt_date": self.last_prompt_date,
                "tui_layout": self.tui_layout,
                "tui_hide_completed": self.tui_hide_completed,
                "tui_due_filter": self.tui_due_filter,
                "tui_tag_filter": self.tui_tag_filter,
                "tui_priority_filter": self.tui_priority_filter,
                "tui_sort_key": self.tui_sort_key,
                "tui_sort_order": self.tui_sort_order,
                "tui_repo_filter": self.tui_repo_filter,
            }
        )
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GlobalState:
        """Build a GlobalState from stored data.

        Missing keys fall back to defaults. Unrecognized top-level keys are
        captured in :attr:`_extra` so they round-trip through the next
        ``save()`` instead of being silently deleted (forward compatibility).

        Args:
            data: Parsed JSON dict.

        Returns:
            A GlobalState instance.
        """
        known = {
            "version",
            "repositories",
            "favorites",
            "active_session",
            "work_clock",
            "breaks",
            "workweek_days",
            "last_prompt_date",
            "tui_layout",
            "tui_hide_completed",
            "tui_due_filter",
            "tui_tag_filter",
            "tui_priority_filter",
            "tui_sort_key",
            "tui_sort_order",
            "tui_repo_filter",
        }
        extra = {k: v for k, v in data.items() if k not in known}
        return cls(
            version=int(data.get("version", GLOBAL_STATE_VERSION)),
            repositories=list(data.get("repositories", [])),
            favorites=list(data.get("favorites", [])),
            active_session=data.get("active_session"),
            work_clock=WorkClock.from_dict(data.get("work_clock")),
            breaks=[
                BreakConfig.from_dict(b) for b in data.get("breaks", []) if isinstance(b, dict)
            ],
            workweek_days=sanitize_workweek_days(data.get("workweek_days")),
            last_prompt_date=data.get("last_prompt_date"),
            tui_layout=data.get("tui_layout"),
            tui_hide_completed=bool(data.get("tui_hide_completed", False)),
            tui_due_filter=data.get("tui_due_filter"),
            tui_tag_filter=data.get("tui_tag_filter"),
            tui_priority_filter=data.get("tui_priority_filter"),
            tui_sort_key=data.get("tui_sort_key"),
            tui_sort_order=data.get("tui_sort_order"),
            tui_repo_filter=data.get("tui_repo_filter"),
            _extra=extra,
        )


class GlobalStateStore:
    """Loads and persists :class:`GlobalState` to the global config file.

    Attributes:
        path: Path to the config.json file.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        """Initialize the store.

        Args:
            path: Override path to the config file. When omitted, the path is
                resolved from the portable search order
                (:func:`resolve_global_config_path`). If no config exists
                anywhere yet, the *write* target
                (:func:`resolve_global_config_write_path`) is used instead so
                a first-run ``save()`` lands in the project-anchored portable
                location rather than silently in ``~/.config``.
        """
        if path is not None:
            self.path = Path(path)
            return
        read_path = resolve_global_config_path()
        if read_path.exists():
            self.path = read_path
        else:
            self.path = resolve_global_config_write_path()

    def load(self) -> GlobalState:
        """Load the global state from disk.

        If the file does not exist or cannot be parsed, a fresh default
        state is returned (and not written).

        Returns:
            The loaded or default GlobalState.
        """
        if not self.path.exists():
            return GlobalState()
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return GlobalState()
        if not isinstance(data, dict):
            return GlobalState()
        return GlobalState.from_dict(data)

    def save(self, state: GlobalState) -> None:
        """Persist the global state atomically.

        Creates parent directories if needed and writes via a temp file +
        rename to avoid partial writes.

        Args:
            state: The state to persist.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)

        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(state.to_dict(), f, indent=2, ensure_ascii=False, default=str)
                f.write("\n")
            temp_path.replace(self.path)
        except Exception:
            if temp_path.exists():
                temp_path.unlink()
            raise
