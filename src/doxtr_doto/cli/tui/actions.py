"""Mutating actions for the doto TUI, routed through the CLI verb functions.

Every mutation the TUI performs delegates to the same functions the CLI verbs
use so the two never diverge:

* complete a task -> :func:`doxtr_doto.cli.json_store.JsonTaskStore.update_task`
  (the body of ``doto done``),
* edit / cycle a task's fields -> :func:`doxtr_doto.cli.json_store.JsonTaskStore.update_task`
  (the single-task body of ``doto update``),
* start a focus timer -> :func:`doxtr_doto.cli.commands.start.start_focus`,
* stop a focus timer -> :func:`doxtr_doto.cli.commands.stop.stop_focus`,
* clock out -> :func:`doxtr_doto.cli.commands.stop.stop_work_clock`,
* add a task -> :func:`doxtr_doto.cli.json_store.JsonTaskStore.add_task`
  (the body of ``doto add``),
* rescan repos -> :func:`doxtr_doto.cli.repo_registry.RepoRegistry.rescan`.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from doxtr_doto.cli.commands.start import start_focus
from doxtr_doto.cli.commands.stop import stop_focus, stop_work_clock
from doxtr_doto.cli.id_resolver import resolve_task_ref
from doxtr_doto.cli.repo_registry import DiscoveredRepo, RepoRegistry
from doxtr_doto.cli.tui import data
from doxtr_doto.constants import DONE_STATUS, STATUS_DISPLAY_ORDER
from doxtr_doto.enums import TuiLayout
from doxtr_doto.time_tracking import has_open_session

if TYPE_CHECKING:
    from doxtr_doto.cli.main import DotoContext
    from doxtr_doto.cli.tui.filtersort import ViewPrefs
    from doxtr_doto.sync.json_store import TaskData


def complete_task(ctx: DotoContext, task_ref: str) -> bool:
    """Mark a task done, reusing the ``doto done`` mutation.

    Args:
        ctx: The CLI context.
        task_ref: A bare or ``repo#id`` task reference.

    Returns:
        True if the task was found and marked done (or already done), False
        if it could not be resolved.
    """
    resolved = resolve_task_ref(ctx, task_ref)
    if resolved is None:
        return False
    task = resolved.store.get_task(resolved.task_id)
    if task is None:
        return False
    if task.get("status") != DONE_STATUS:
        resolved.store.update_task(resolved.task_id, {"status": DONE_STATUS})
        resolved.store.save()
    return True


def update_task(
    ctx: DotoContext,
    task_ref: str,
    updates: dict[str, Any],
) -> bool:
    """Apply arbitrary field updates to a task, like single-task ``doto update``.

    Mirrors the single-task path in
    :func:`doxtr_doto.cli.commands.update._update_single_task`: the reference
    is resolved via :func:`resolve_task_ref` and the updates are written with
    :meth:`JsonTaskStore.update_task` + :meth:`JsonTaskStore.save` so the TUI
    never duplicates the write logic.

    Args:
        ctx: The CLI context.
        task_ref: A bare or ``repo#id`` task reference.
        updates: A mapping of task fields to new values (empty is a no-op).

    Returns:
        True if the task was found and the updates were applied (or there was
        nothing to apply), False if the reference could not be resolved.
    """
    resolved = resolve_task_ref(ctx, task_ref)
    if resolved is None:
        return False
    task = resolved.store.get_task(resolved.task_id)
    if task is None:
        return False
    if updates:
        resolved.store.update_task(resolved.task_id, updates)
        resolved.store.save()
        # Persist any new assignee/tags/RACI names to the known-names memory store
        from doxtr_doto.cli import known_names
        from doxtr_doto.raci import raci_names

        known_names.remember_task_names(updates.get("assignee"), updates.get("tags", []))
        for rn in raci_names(updates.get("raci")):
            known_names.remember_task_names(rn, [])
    return True


def status_cycle(ctx: DotoContext) -> list[str]:
    """Return the ordered status cycle used by :func:`cycle_status`.

    Prefers the configured statuses (``ctx.config.statuses``), falling back to
    :data:`doxtr_doto.constants.STATUS_DISPLAY_ORDER` when the config exposes
    no (non-empty) status list.

    Args:
        ctx: The CLI context.

    Returns:
        The list of statuses, in cycle order.
    """
    configured = list(ctx.config.statuses or [])
    return configured or list(STATUS_DISPLAY_ORDER)


def cycle_status(ctx: DotoContext, task_ref: str) -> str | None:
    """Advance a task to the next status in the configured cycle.

    The cycle is :func:`status_cycle`; the new status is the one following the
    task's current status, wrapping around at the end. If the current status
    is not in the cycle, the first status is used. Routes the write through
    :meth:`JsonTaskStore.update_task` + :meth:`JsonTaskStore.save` (the same
    path as ``doto update``).

    Args:
        ctx: The CLI context.
        task_ref: A bare or ``repo#id`` task reference.

    Returns:
        The new status string, or None if the reference could not be resolved.
    """
    resolved = resolve_task_ref(ctx, task_ref)
    if resolved is None:
        return None
    task = resolved.store.get_task(resolved.task_id)
    if task is None:
        return None
    cycle = status_cycle(ctx)
    if not cycle:
        return None
    current = task.get("status")
    try:
        index = cycle.index(current) if current is not None else -1
        next_status = cycle[(index + 1) % len(cycle)]
    except ValueError:
        next_status = cycle[0]
    resolved.store.update_task(resolved.task_id, {"status": next_status})
    resolved.store.save()
    return next_status


def set_status(ctx: DotoContext, task_ref: str, status: str) -> str | None:
    """Set a task's status to an explicit value.

    Mirrors :func:`cycle_status`' store path - the reference is resolved via
    :func:`resolve_task_ref` and the write goes through
    :meth:`JsonTaskStore.update_task` + :meth:`JsonTaskStore.save` (the same
    path as ``doto update``) - but the status is set to the given value rather
    than the next one in the cycle. Only the ``status`` field is written, so
    worklogs (and every other field) are left untouched.

    Args:
        ctx: The CLI context.
        task_ref: A bare or ``repo#id`` task reference.
        status: The explicit status value to set.

    Returns:
        The new status string, or None if the reference could not be resolved.
    """
    resolved = resolve_task_ref(ctx, task_ref)
    if resolved is None:
        return None
    task = resolved.store.get_task(resolved.task_id)
    if task is None:
        return None
    resolved.store.update_task(resolved.task_id, {"status": status})
    resolved.store.save()
    return status


def cycle_status_prev(ctx: DotoContext, task_ref: str) -> str | None:
    """Advance a task to the PREVIOUS status in the configured cycle.

    Mirror of :func:`cycle_status` with an index of -1: the new status is the
    one preceding the task's current status in :func:`status_cycle`, wrapping
    around at the start. If the current status is not in the cycle, the first
    status is used. Routes the write through :meth:`JsonTaskStore.update_task`
    + :meth:`JsonTaskStore.save` (the same path as ``doto update``).

    Args:
        ctx: The CLI context.
        task_ref: A bare or ``repo#id`` task reference.

    Returns:
        The new status string, or None if the reference could not be resolved.
    """
    resolved = resolve_task_ref(ctx, task_ref)
    if resolved is None:
        return None
    task = resolved.store.get_task(resolved.task_id)
    if task is None:
        return None
    cycle = status_cycle(ctx)
    if not cycle:
        return None
    current = task.get("status")
    try:
        # ``index = 1`` for a missing status yields ``cycle[(1-1) % len]`` =
        # ``cycle[0]`` (the first status), matching the spec's
        # "unknown-current -> first" rule and the ValueError branch below.
        index = cycle.index(current) if current is not None else 1
        prev_status = cycle[(index - 1) % len(cycle)]
    except ValueError:
        prev_status = cycle[0]
    resolved.store.update_task(resolved.task_id, {"status": prev_status})
    resolved.store.save()
    return prev_status


def toggle_timer(ctx: DotoContext, task_ref: str) -> str:
    """Start or stop a focus timer for a task.

    If the task currently has an open worklog, its focus session is stopped
    (via :func:`stop_focus`); otherwise a focus timer is started (via
    :func:`start_focus`).

    Args:
        ctx: The CLI context.
        task_ref: A bare or ``repo#id`` task reference.

    Returns:
        ``"started"``, ``"stopped"``, or ``"not_found"``.
    """
    resolved = resolve_task_ref(ctx, task_ref)
    if resolved is None:
        return "not_found"
    # Decide start-vs-stop against on-disk truth. The TUI reuses one long-lived
    # ``ctx.store`` across presses while the worklog is opened/closed through a
    # freshly resolved store for the same path, so this instance's cache can be
    # stale. Reloading first keeps the branch decision consistent with the
    # reload discipline in ``start_focus``/``stop_focus`` - otherwise a stale
    # ``_running`` read could misclassify an open session as stopped (leaving
    # the green focus arrow stuck on).
    resolved.store.load()
    task = resolved.store.get_task(resolved.task_id)
    if task is None:
        return "not_found"

    if has_open_session(task.get("worklogs", [])):
        stop_focus(ctx)
        return "stopped"

    start_focus(ctx, resolved)
    return "started"


def start_work(ctx: DotoContext, task_ref: str) -> str:
    """Start working on a doto: set it in-progress AND start the focus timer.

    Reuses :func:`toggle_timer`'s start-vs-stop decision (made against on-disk
    truth, so the two never disagree):

    * On the START branch the focus timer is started and - only here - the
      status is set to ``"in-progress"`` via :func:`set_status`, but *only* if
      ``"in-progress"`` is in :func:`status_cycle`. If that status is not
      configured, ``start_work`` degrades gracefully to a timer-only start
      (no status write).
    * A second press stops the timer (the doto already had an open focus
      session) and leaves the status unchanged; it does NOT mark the task
      done.

    Args:
        ctx: The CLI context.
        task_ref: A bare or ``repo#id`` task reference.

    Returns:
        ``"started"``, ``"stopped"``, or ``"not_found"``.
    """
    result = toggle_timer(ctx, task_ref)
    if result == "started" and "in-progress" in status_cycle(ctx):
        set_status(ctx, task_ref, "in-progress")
    return result


def clock_out(ctx: DotoContext) -> bool:
    """Stop the focus timer and the global work clock.

    Equivalent to ``doto clock-out``.

    Args:
        ctx: The CLI context.

    Returns:
        True if the work clock was running and is now stopped, False
        otherwise.
    """
    stop_focus(ctx)
    return stop_work_clock(ctx)


def clock_in_work(ctx: DotoContext) -> bool:
    """Clock in to the global work clock without a focus task.

    Equivalent to ``doto start`` with no task id: opens the Layer-1 work
    clock if it is not already running, reusing the same ``clock_in_work``
    helper so the behavior matches the CLI.

    Args:
        ctx: The CLI context.

    Returns:
        True if the work clock was newly started, False if already running.
    """
    from doxtr_doto.cli.commands.start import clock_in_work as _start_clock_in

    return _start_clock_in(ctx)


def add_task(
    ctx: DotoContext,
    title: str,
    *,
    priority: str | None = None,
    status: str | None = None,
    assignee: str | None = None,
    tags: str | None = None,
    repo: DiscoveredRepo | None = None,
) -> str:
    """Create a new task, reusing ``doto add`` logic.

    By default the task is created in the current directory's store
    (``ctx.store``), matching ``doto add``. When ``repo`` is given the task is
    created in *that* repository's store instead (built via
    :func:`doxtr_doto.cli.tui.data.store_for_repo`), so the TUI can let the
    user choose which repository a task lands in. When a repository is given
    its own ``.doto.toml`` is loaded so the id prefix / sequencing and task
    defaults come from the target repository rather than the directory doto was
    launched in (falling back to the launch directory's config when the target
    repo has no ``.doto.toml``).

    Args:
        ctx: The CLI context.
        title: The task title (required).
        priority: Priority value, or None to use the config default.
        status: Status value, or None to use the config default.
        assignee: Assignee name, or None.
        tags: Comma-separated tags, or None.
        repo: Target repository to create the task in. When None (the
            default), the current directory's store (``ctx.store``) is used,
            preserving the original behavior.

    Returns:
        The id of the newly created task.
    """
    from doxtr_doto.cli.commands.add import _build_task_data

    if repo is None:
        store = ctx.store
        config = ctx.config
    else:
        store = data.store_for_repo(repo)
        # Resolve the target repo's own config (its .doto.toml drives the id
        # prefix / sequencing and defaults), falling back to the launch dir's
        # config when the repo has no .doto.toml. See data.config_for_repo.
        config = data.config_for_repo(repo, ctx.config)
    task_id = store.generate_id(prefix=config.id_prefix, sequential=config.id_sequential)
    task_data = _build_task_data(
        config,
        title,
        assignee,
        priority,
        status,
        None,  # due
        tags,
        None,  # depends_on
        None,  # body
        None,  # rst_file
    )
    store.add_task(task_id, task_data)
    store.save()
    # Persist any new assignee/tags to the known-names memory store
    from doxtr_doto.cli import known_names

    known_names.remember_task_names(task_data.get("assignee"), task_data.get("tags", []))
    return task_id


def rescan_repos(ctx: DotoContext, start_dir: Path | str | None = None) -> int:
    """Rediscover repositories and refresh the cached registry.

    Args:
        ctx: The CLI context.
        start_dir: Directory to walk (defaults to the current directory).

    Returns:
        The number of repositories now in the cache.
    """
    registry = RepoRegistry(ctx.global_store)
    root = Path(start_dir) if start_dir is not None else Path.cwd()
    return len(registry.rescan(root))


def find_task(ctx: DotoContext, task_ref: str) -> TaskData | None:
    """Resolve and return a task's data dict, if it exists.

    Args:
        ctx: The CLI context.
        task_ref: A bare or ``repo#id`` task reference.

    Returns:
        The task data dict, or None if it could not be resolved.
    """
    resolved = resolve_task_ref(ctx, task_ref)
    if resolved is None:
        return None
    return resolved.store.get_task(resolved.task_id)


def load_tui_layout(ctx: DotoContext) -> TuiLayout:
    """Return the user's persisted TUI task-list layout preference.

    Reads ``tui_layout`` from the global state the same way other TUI
    preferences (favorites, ``last_prompt_date``) are read. When the field is
    absent (older state files that predate the feature) or holds an
    unrecognized value, the default :attr:`doxtr_doto.enums.TuiLayout.TABLE`
    view is returned so the behavior is backward compatible.

    Args:
        ctx: The CLI context.

    Returns:
        The persisted :class:`~doxtr_doto.enums.TuiLayout`, defaulting to
        :attr:`~doxtr_doto.enums.TuiLayout.TABLE`.
    """
    stored = ctx.global_store.load().tui_layout
    if stored is None:
        return TuiLayout.TABLE
    try:
        return TuiLayout(stored)
    except ValueError:
        return TuiLayout.TABLE


def save_tui_layout(ctx: DotoContext, layout: TuiLayout) -> None:
    """Persist the user's TUI task-list layout preference.

    Writes ``tui_layout`` into the global config the same atomic way
    :func:`doxtr_doto.cli.tui.nudge.mark_prompted` persists
    ``last_prompt_date`` (load -> mutate -> save), so the chosen layout
    becomes the default on the next launch.

    Args:
        ctx: The CLI context.
        layout: The layout view to persist.
    """
    state = ctx.global_store.load()
    state.tui_layout = TuiLayout(layout).value
    ctx.global_store.save(state)


def load_view_prefs(ctx: DotoContext) -> ViewPrefs:
    """Return the user's persisted TUI filter/sort preferences (Feature C).

    Reads the ``tui_*`` filter/sort fields from the global state - mirroring
    how :func:`load_tui_layout` reads ``tui_layout`` - and reconstructs a
    :class:`doxtr_doto.cli.tui.filtersort.ViewPrefs`. Absent fields (older
    state files that predate the feature) and unrecognized enum values fall
    back to their defaults, so the behavior is backward compatible and never
    raises on a stale/invalid stored value. This is the "sort memory" load
    side: the last filter/sort state is restored on the next launch.

    Args:
        ctx: The CLI context.

    Returns:
        The persisted :class:`~doxtr_doto.cli.tui.filtersort.ViewPrefs`,
        defaulting each field when unset/invalid.
    """
    from doxtr_doto.cli.tui.filtersort import ViewPrefs
    from doxtr_doto.enums import DueFilter, SortKey, SortOrder

    state = ctx.global_store.load()

    def _enum(enum_cls: Any, value: Any, default: Any) -> Any:
        if value is None:
            return default
        try:
            return enum_cls(value)
        except ValueError:
            return default

    return ViewPrefs(
        hide_completed=bool(state.tui_hide_completed),
        due_filter=_enum(DueFilter, state.tui_due_filter, DueFilter.ALL),
        tag_filter=state.tui_tag_filter or None,
        priority_filter=state.tui_priority_filter or None,
        sort_key=_enum(SortKey, state.tui_sort_key, SortKey.NONE),
        sort_order=_enum(SortOrder, state.tui_sort_order, SortOrder.ASC),
        repo_filter=tuple(state.tui_repo_filter or ()),
    )


def save_view_prefs(ctx: DotoContext, prefs: ViewPrefs) -> None:
    """Persist the user's TUI filter/sort preferences (Feature C).

    Writes the ``tui_*`` filter/sort fields into the global config the same
    atomic load -> mutate -> save way :func:`save_tui_layout` persists
    ``tui_layout``, so the chosen filter/sort (the "sort memory") becomes the
    default on the next launch. Enum fields are stored as their string value
    and empty text filters are normalized to None.

    Args:
        ctx: The CLI context.
        prefs: The view preferences to persist.
    """
    state = ctx.global_store.load()
    state.tui_hide_completed = bool(prefs.hide_completed)
    state.tui_due_filter = prefs.due_filter.value
    state.tui_tag_filter = prefs.tag_filter or None
    state.tui_priority_filter = prefs.priority_filter or None
    state.tui_sort_key = prefs.sort_key.value
    state.tui_sort_order = prefs.sort_order.value
    state.tui_repo_filter = list(prefs.repo_filter) or None
    ctx.global_store.save(state)
