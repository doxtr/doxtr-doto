"""Read-only data gathering for the doto TUI.

These helpers assemble the view model the TUI renders: the cached repository
list, the task rows for the current scope, the active focus session, and the
live Layer-1 / Layer-2 counters. They never mutate state (that is the job of
:mod:`doxtr_doto.cli.tui.actions`), and they reuse the same stores and
registry the CLI uses so the TUI stays consistent with ``doto list`` and
``doto status``.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from doxtr_doto.cli.display import DisplayScope, apply_scope, tag_repo
from doxtr_doto.cli.repo_registry import DOTO_MARKER, DiscoveredRepo, RepoRegistry
from doxtr_doto.cli.session import (
    derive_repo_name,
    live_focus_elapsed,
    work_elapsed_today,
)
from doxtr_doto.time_tracking import (
    elapsed_seconds,
    has_open_session,
    open_session,
)

if TYPE_CHECKING:
    from doxtr_doto.cli.config import DotoConfig
    from doxtr_doto.cli.json_store import JsonTaskStore
    from doxtr_doto.cli.main import DotoContext


def list_repos(ctx: DotoContext) -> list[DiscoveredRepo]:
    """Return the cached repositories for the repo tree pane.

    Args:
        ctx: The CLI context.

    Returns:
        Cached repositories (never triggers discovery).
    """
    return RepoRegistry(ctx.global_store).list_repos()


def current_repo_name(ctx: DotoContext) -> str:
    """Return the repository name for the current working directory.

    Args:
        ctx: The CLI context.

    Returns:
        The short repo name used for namespaced display.
    """
    return derive_repo_name(ctx.config)


def current_repo(ctx: DotoContext) -> DiscoveredRepo:
    """Return a :class:`DiscoveredRepo` for the current working directory.

    The current directory's store is not guaranteed to appear in the cached
    registry (:func:`list_repos`), so this synthesizes a repo entry from the
    active config. The ``path`` is anchored to the *store* the current
    directory actually uses - the parent of the ``.doto`` directory holding
    the active ``tasks.json`` (``get_json_path().resolve().parent.parent``) -
    so that :func:`store_for_repo` of this repo always targets the same store
    as ``ctx.store``. The ``name`` comes from :func:`current_repo_name` (which
    derives from ``config.source_dir`` via
    :func:`~doxtr_doto.cli.session.derive_repo_name`).

    For the default ``.doto/tasks.json`` layout ``source_dir`` is this same
    repo root, so the name and the path share one root and cannot diverge.
    When ``json_file`` is reconfigured to point outside ``source_dir`` the two
    can differ (the name follows ``source_dir`` while the path follows the
    store); the store-anchored ``path`` is deliberate because the add-task
    selector must write back into the store the task list reads from, so the
    store invariant takes precedence over name/path coincidence.

    The TUI uses this so the add-task repo selector can always default to - and
    write back into - the current repo even when discovery has not been run.

    Args:
        ctx: The CLI context.

    Returns:
        A :class:`DiscoveredRepo` whose ``path`` is the current repo root
        (anchored to the active store) and whose ``name`` is the current repo
        name.
    """
    json_path = ctx.config.get_json_path().resolve()
    repo_root = json_path.parent.parent
    return DiscoveredRepo(name=current_repo_name(ctx), path=str(repo_root))


def store_for_repo(repo: DiscoveredRepo) -> JsonTaskStore:
    """Return a task store for a discovered repository.

    Args:
        repo: The discovered repository.

    Returns:
        A :class:`JsonTaskStore` for the repo's ``.doto/tasks.json``.
    """
    from doxtr_doto.cli.json_store import JsonTaskStore

    return JsonTaskStore(Path(repo.path) / DOTO_MARKER)


def config_for_repo(repo: DiscoveredRepo, fallback: DotoConfig) -> DotoConfig:
    """Return the target repo's own config, falling back when it has none.

    The repo's own ``.doto.toml`` drives the id prefix / sequencing and task
    defaults. When the repo has no ``.doto.toml`` the ``fallback`` config (the
    directory doto was launched in) is returned instead.

    Pass only ``config_path`` (not ``json_path``) to :func:`load_config`:
    ``json_path`` would force standalone mode and skip loading the repo's
    ``.doto.toml``.

    Args:
        repo: The discovered repository.
        fallback: Config to use when the repo has no ``.doto.toml``.

    Returns:
        The resolved :class:`DotoConfig` for the repo.
    """
    from doxtr_doto.cli.config import load_config

    repo_toml = Path(repo.path) / ".doto.toml"
    return load_config(config_path=repo_toml) if repo_toml.is_file() else fallback


def gather_tasks(
    ctx: DotoContext,
    scope: DisplayScope,
    *,
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    """Gather task rows for the given display scope.

    In :data:`DisplayScope.LOCAL`, only the current directory's store is read.
    In :data:`DisplayScope.GLOBAL`, every cached repository is aggregated and
    ids are namespaced via :func:`doxtr_doto.cli.display.apply_scope`.

    Each returned task dict carries the extra keys used by the TUI:

    * ``id`` - the display id (namespaced in global scope),
    * ``_repo`` / ``_local_id`` - the owning repo and bare id,
    * ``_running`` - whether the task has an open worklog.

    Args:
        ctx: The CLI context.
        scope: The display scope to gather for.
        include_archived: Whether to include archived tasks.

    Returns:
        A list of task dicts ready for the task-list pane.
    """
    merged: list[dict[str, Any]] = []
    if scope is DisplayScope.GLOBAL:
        for repo in list_repos(ctx):
            store = store_for_repo(repo)
            if not store.exists():
                continue
            tasks = store.filter_tasks(include_archived=include_archived)
            merged.extend(tag_repo(tasks, repo.name))
    else:
        repo_name = current_repo_name(ctx)
        tasks = ctx.store.filter_tasks(include_archived=include_archived)
        merged.extend(tag_repo(tasks, repo_name))

    for task in merged:
        task["_running"] = has_open_session(task.get("worklogs", []))

    apply_scope(merged, scope)
    return merged


def active_session(ctx: DotoContext) -> dict[str, Any] | None:
    """Return the active focus session from global state, if any.

    Args:
        ctx: The CLI context.

    Returns:
        The active session dict, or None.
    """
    return ctx.global_store.load().active_session


def live_counters(ctx: DotoContext, now: datetime | None = None) -> tuple[int, bool, int, int]:
    """Return the live status-line counters plus the current-session seconds.

    Args:
        ctx: The CLI context.
        now: Reference "current" time (defaults to current local time).

    Returns:
        A tuple ``(work_today_seconds, work_running, work_session_seconds,
        focus_seconds)`` where ``work_today_seconds`` sums *all* of today's
        work-clock intervals (the status line's daily work counter),
        ``work_session_seconds`` is the elapsed time of the single
        currently-open work-clock interval only (the current work session; 0
        when none is open), and ``focus_seconds`` is the elapsed time of the
        currently open focus session (0 if none). Reading all four in one
        store load keeps the timer path from loading the store twice.
    """
    moment = now if now is not None else datetime.now().astimezone()
    state = ctx.global_store.load()

    work_today = work_elapsed_today(state.work_clock.worklogs, moment)
    work_running = has_open_session(state.work_clock.worklogs)
    work_session_seconds = live_focus_elapsed(state.work_clock.worklogs, now=moment)

    focus_seconds = 0
    session = state.active_session
    if session and session.get("task_id"):
        from doxtr_doto.cli.session import resolve_session_store

        store = resolve_session_store(ctx.store, session.get("json_path"))
        task = store.get_task(session["task_id"])
        if task is not None:
            open_log = open_session(task.get("worklogs", []))
            if open_log is not None:
                focus_seconds = elapsed_seconds([open_log], now=moment)

    return work_today, work_running, work_session_seconds, focus_seconds


def current_work_session_seconds(ctx: DotoContext, now: datetime | None = None) -> int:
    """Return the elapsed seconds of the currently open work-clock session.

    This is the *current work session*: the elapsed time of the single
    currently-open Layer-1 work-clock interval only, computed via
    :func:`doxtr_doto.cli.session.live_focus_elapsed`. It is deliberately
    distinct from :func:`live_counters`' ``work_today_seconds``, which sums
    *all* of today's work-clock intervals (the status line's daily work
    counter). When no work session is open this is 0.

    Args:
        ctx: The CLI context.
        now: Reference "current" time (defaults to current local time).

    Returns:
        Elapsed seconds of the open work-clock interval, or 0 when no work
        session is open.
    """
    moment = now if now is not None else datetime.now().astimezone()
    worklogs = ctx.global_store.load().work_clock.worklogs
    return live_focus_elapsed(worklogs, now=moment)


def task_total_seconds(
    task: Mapping[str, Any] | None,
    now: datetime | None = None,
) -> int:
    """Return the total time spent on a single task across all its worklogs.

    This is the per-task total shown in the TUI's elapsed-time display for the
    currently highlighted task. Unlike the live focus counter (which counts
    only the open interval), this sums *every* interval - closed and open -
    via :func:`doxtr_doto.time_tracking.elapsed_seconds` so it reflects the
    cumulative time the task has been worked on.

    Args:
        task: A task dict (with a ``worklogs`` list), or None.
        now: Reference "current" time for any open interval (defaults to the
            current local time inside ``elapsed_seconds``).

    Returns:
        Total elapsed seconds across the task's worklogs (0 when there is no
        task or it has no worklogs).
    """
    if not task:
        return 0
    return elapsed_seconds(task.get("worklogs", []), now=now)


def session_intervals(
    task: Mapping[str, Any] | None,
    now: datetime | None = None,
) -> list[tuple[str, str, str, bool]]:
    """Build display rows for a task's session interval log.

    Args:
        task: A task dict (with a ``worklogs`` list), or None.
        now: Reference "current" time for open sessions.

    Returns:
        A list of ``(start, stop, duration, is_open)`` tuples.
    """
    from doxtr_doto.cli.session import interval_rows

    if not task:
        return []
    return interval_rows(task.get("worklogs", []), now, None)
