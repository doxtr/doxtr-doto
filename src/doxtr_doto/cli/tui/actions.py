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
* add a recurring series -> :func:`add_series`, which builds each occurrence
  via :func:`doxtr_doto.cli.recurrence.build_series_task_data` (the shared body
  of ``doto add --repeat``),
* update a recurring series (forward-only re-stamp) -> :func:`update_series`,
  the single source of truth shared by ``doto series update`` and the TUI,
* delete a task / series -> :func:`delete_task` / :func:`delete_series`,
  thin wrappers over the store's delete methods (+ ``save``),
* rescan repos -> :func:`doxtr_doto.cli.repo_registry.RepoRegistry.rescan`.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

from doxtr_doto.cli.commands.start import start_focus
from doxtr_doto.cli.commands.stop import stop_focus, stop_work_clock
from doxtr_doto.cli.id_resolver import resolve_task_ref
from doxtr_doto.cli.recurrence import RecurrencePattern, build_occurrence_due, render_series_title
from doxtr_doto.cli.repo_registry import DiscoveredRepo, RepoRegistry
from doxtr_doto.cli.tui import data
from doxtr_doto.constants import DONE_STATUS, STATUS_DISPLAY_ORDER
from doxtr_doto.enums import SetParentResult, TuiLayout
from doxtr_doto.time_tracking import has_open_session

if TYPE_CHECKING:
    from doxtr_doto.cli.main import DotoContext
    from doxtr_doto.cli.tui.filtersort import ViewPrefs
    from doxtr_doto.sync.json_store import TaskData


def _reject_cross_repo_deps(
    ctx: DotoContext,
    owner_store: Any,
    depends_on: Any,
) -> None:
    """Raise if ``depends_on`` names a dependency in a DIFFERENT repository.

    The dependency relation, like the ``parent`` link, is an in-store relation
    resolved by bare local id against the owning task's own store. A namespaced
    ``repo#id`` dependency pointing at another repo could never be resolved
    from the owner store, so -- mirroring the ``cross_repo`` rejection in
    :func:`set_parent` -- it is rejected up front rather than stored as an
    unresolvable cross-repo edge.

    A ``None`` / non-list ``depends_on`` (the common "this update does not touch
    dependencies" case) is a no-op, so callers can pass an update dict's
    ``depends_on`` value unconditionally.

    Args:
        ctx: The CLI context (provides the repo registry for resolution).
        owner_store: The store that will hold the task carrying the deps.
        depends_on: The candidate dependency list (or None / non-list).

    Raises:
        DotoValidationError: If any dependency ref resolves outside
            ``owner_store``'s repository.
    """
    if not isinstance(depends_on, list):
        return
    from doxtr_doto.cli.id_resolver import cross_repo_deps
    from doxtr_doto.exceptions import DotoValidationError

    offending = cross_repo_deps(ctx, owner_store, [str(d) for d in depends_on])
    if offending:
        joined = ", ".join(offending)
        raise DotoValidationError(
            f"Cross-repo dependencies are not supported: {joined}. "
            "A dependency must live in the same repository as the task."
        )


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
        _reject_cross_repo_deps(ctx, resolved.store, updates.get("depends_on"))
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


#: Sentinel ``parent_ref`` value for :func:`set_parent` that means "remove the
#: child's parent" (make it top-level) rather than attach a new parent. The
#: empty string is used because it can never collide with a real task ref
#: (every task ref resolves to a non-empty bare id or ``repo#id``). The TUI's
#: "(no parent)" picker entry reports this value.
CLEAR_PARENT = ""


def set_parent(ctx: DotoContext, child_ref: str, parent_ref: str) -> str:
    """Attach a task to a PARENT task (or clear its parent), with cycle rejection.

    Establishes the child->parent link of the :data:`TaskData` ``parent`` field
    (distinct from ``depends_on`` / ``series_id``). Mirrors :func:`set_status`'
    store path - both refs are resolved via :func:`resolve_task_ref` and the
    write goes through :meth:`JsonTaskStore.update_task` +
    :meth:`JsonTaskStore.save` - writing only the ``parent`` field so every
    other field is left untouched.

    Passing :data:`CLEAR_PARENT` (the empty string) as ``parent_ref`` *removes*
    the child's parent link instead of setting one: the ``parent`` field is set
    back to ``None`` so the task becomes top-level again. This is the
    "remove parent" path used by the TUI's "(no parent)" picker entry. The
    child must still resolve to a real task; clearing a parent can never create
    a cycle or cross a repo boundary, so those guards are skipped.

    Both tasks must live in the SAME repository store: a parent/child link is
    an in-store relation, so the acyclicity guard
    (:func:`doxtr_doto.sync.json_store.would_create_cycle`) can walk the
    ``parent`` chain within one task map. A parent in a different repo is
    rejected (``"cross_repo"``) rather than stored as an unresolvable edge.

    The parent is stored as its *bare local id* (what the owning store keys its
    tasks on), so a later ``parent`` walk resolves inside that store.

    Args:
        ctx: The CLI context.
        child_ref: A bare or ``repo#id`` reference to the task being parented.
        parent_ref: A bare or ``repo#id`` reference to the chosen parent task,
            or :data:`CLEAR_PARENT` (``""``) to remove the child's parent.

    Returns:
        One of the :class:`~doxtr_doto.enums.SetParentResult` values (as its
        ``str`` value):

        * :attr:`~doxtr_doto.enums.SetParentResult.OK` -- the parent was set;
        * :attr:`~doxtr_doto.enums.SetParentResult.CLEARED` -- the parent link
          was removed (``parent_ref`` was :data:`CLEAR_PARENT`);
        * :attr:`~doxtr_doto.enums.SetParentResult.NOT_FOUND` -- a reference
          could not be resolved to a task;
        * :attr:`~doxtr_doto.enums.SetParentResult.CROSS_REPO` -- child and
          parent are in different repos;
        * :attr:`~doxtr_doto.enums.SetParentResult.CYCLE` -- the assignment
          would create a self-loop or cycle.
    """
    from doxtr_doto.sync.json_store import would_create_cycle

    child = resolve_task_ref(ctx, child_ref)
    if child is None:
        return SetParentResult.NOT_FOUND.value
    store = child.store
    if store.get_task(child.task_id) is None:
        return SetParentResult.NOT_FOUND.value
    # Empty parent ref => clear the link (make the task top-level). No cycle /
    # cross-repo checks are needed since nothing is being attached.
    if parent_ref == CLEAR_PARENT:
        store.update_task(child.task_id, {"parent": None})
        store.save()
        return SetParentResult.CLEARED.value
    parent = resolve_task_ref(ctx, parent_ref)
    if parent is None:
        return SetParentResult.NOT_FOUND.value
    if child.store.path != parent.store.path:
        return SetParentResult.CROSS_REPO.value
    if store.get_task(parent.task_id) is None:
        return SetParentResult.NOT_FOUND.value
    if would_create_cycle(store.get_all_tasks(), child.task_id, parent.task_id):
        return SetParentResult.CYCLE.value
    store.update_task(child.task_id, {"parent": parent.task_id})
    store.save()
    return SetParentResult.OK.value


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
    due: str | None = None,
    estimate: int | None = None,
    depends_on: str | None = None,
    body: str | None = None,
    progress: int | None = None,
    raci: str | None = None,
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

    All optional fields are forwarded to
    :func:`doxtr_doto.cli.commands.add._build_task_data` the same way the
    ``doto add`` verb does, so the configurable add-task modal
    (:class:`doxtr_doto.cli.tui.app.AddTaskScreen`) can create a fully
    populated task. The ``due`` / ``estimate`` values are expected pre-parsed
    (the modal parses them via its ``parse_due`` / ``parse_estimate`` helpers,
    the same parsers ``doto add`` uses); ``tags`` / ``depends_on`` / ``raci``
    are comma-separated / directive strings split by ``_build_task_data``.

    Args:
        ctx: The CLI context.
        title: The task title (required).
        priority: Priority value, or None to use the config default.
        status: Status value, or None to use the config default.
        assignee: Assignee name, or None.
        tags: Comma-separated tags, or None.
        due: Pre-parsed due date (``YYYY-MM-DD`` / ``...THH:MM``), or None.
        estimate: Estimate in whole minutes, or None.
        depends_on: Comma-separated dependency task IDs, or None.
        body: Task body/description, or None.
        progress: Progress percentage (0-100), or None.
        raci: Explicit RACI directive string, or None (uses the current-user
            RACI default from ``_build_task_data``).
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
        due,
        tags,
        depends_on,
        body,
        None,  # rst_file
        raci=raci,
    )
    if estimate is not None:
        task_data["estimate"] = estimate
    if progress is not None:
        task_data["progress"] = progress
    _reject_cross_repo_deps(ctx, store, task_data.get("depends_on"))
    store.add_task(task_id, task_data)
    store.save()
    # Persist any new assignee/tags/RACI names to the known-names memory store
    from doxtr_doto.cli import known_names
    from doxtr_doto.raci import raci_names

    known_names.remember_task_names(task_data.get("assignee"), task_data.get("tags", []))
    for rn in raci_names(task_data.get("raci")):
        known_names.remember_task_names(rn, [])
    return task_id


class SeriesResult(NamedTuple):
    """The outcome of creating a recurring task series via :func:`add_series`.

    Attributes:
        series_id: The id of the newly created series.
        task_ids: The ids of the tasks created for the series, in occurrence
            order.
        pattern: The parsed :class:`~doxtr_doto.cli.recurrence.RecurrencePattern`
            (carries the resolved ``start_time`` / ``duration_minutes``).
        start_date: The resolved series start date (ISO ``YYYY-MM-DD``).
        end_date: The resolved series end date (ISO ``YYYY-MM-DD``).
        occurrence_count: The number of occurrences (== ``len(task_ids)``).
    """

    series_id: str
    task_ids: list[str]
    pattern: RecurrencePattern
    start_date: str
    end_date: str
    occurrence_count: int


def add_series(
    ctx: DotoContext,
    *,
    title_template: str,
    pattern: RecurrencePattern,
    start_date: date,
    end_date: date,
    task_defaults: dict[str, Any],
    repo: DiscoveredRepo | None = None,
) -> SeriesResult:
    """Create a recurring task series, reusing the shared occurrence builder.

    The single source of truth for *building* a series from an already-parsed
    pattern and resolved start/end dates. Both the CLI ``doto add --repeat``
    path (:func:`doxtr_doto.cli.commands.add._add_recurring_tasks`, a thin
    wrapper that keeps the dry-run / printing / validation) and the TUI
    add-series dialog (:meth:`doxtr_doto.cli.tui.app.DotoApp.action_add_series`)
    call this, so the two never diverge.

    Each occurrence's task dict is built by the shared
    :func:`doxtr_doto.cli.recurrence.build_series_task_data`, so the pattern's
    ``start_time`` (-> time-bearing ``due``) and ``duration_minutes``
    (-> ``estimate``) are applied identically to the ``series extend`` path.

    The caller is responsible for *validating* the pattern/dates and enforcing
    the occurrence limit; this function assumes they are already resolved. The
    task is created in ``ctx.store`` by default, or in ``repo``'s store (with
    that repo's own config) when given -- mirroring :func:`add_task`.

    Args:
        ctx: The CLI context.
        title_template: The series title template (``{date}`` supported).
        pattern: The parsed recurrence pattern (supplies time + duration).
        start_date: The resolved first-occurrence date.
        end_date: The resolved last-occurrence date (inclusive).
        task_defaults: Shared per-series task defaults (assignee/priority/etc).
        repo: Target repository, or None for the current directory's store.

    Returns:
        A :class:`SeriesResult` describing the created series.
    """
    from doxtr_doto.cli.recurrence import build_series_task_data, generate_occurrences

    if repo is None:
        store = ctx.store
        config = ctx.config
    else:
        store = data.store_for_repo(repo)
        config = data.config_for_repo(repo, ctx.config)

    occurrences = list(generate_occurrences(pattern, start_date, end_date))
    series_id = store.generate_series_id()

    task_ids: list[str] = []
    for occurrence_date in occurrences:
        task_id = store.generate_id(
            prefix=config.id_prefix,
            sequential=config.id_sequential,
        )
        task_data = build_series_task_data(
            pattern,
            occurrence_date,
            title_template,
            series_id,
            task_defaults,
        )
        store.add_task(task_id, task_data)
        task_ids.append(task_id)

    store.add_series(
        series_id=series_id,
        title_template=title_template,
        pattern=pattern.to_dict(),
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        task_ids=task_ids,
        task_defaults=task_defaults,
    )
    store.save()

    from doxtr_doto.cli import known_names

    known_names.remember_task_names(task_defaults.get("assignee"), task_defaults.get("tags", []))

    return SeriesResult(
        series_id=series_id,
        task_ids=task_ids,
        pattern=pattern,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        occurrence_count=len(occurrences),
    )


class SeriesUpdateResult(NamedTuple):
    """The outcome of updating a recurring series via :func:`update_series`.

    Attributes:
        series_id: The id of the updated series.
        anchor_date: The forward-only anchor date; ``None`` for a
            metadata-only update (no task re-stamp).
        old_pattern_desc: The stored pattern's description *before* the update.
        new_pattern_desc: The pattern's description *after* the update.
        updated_task_ids: The ids of the occurrences that were re-stamped (on a
            dry run, the ids that *would* be re-stamped), in iteration order.
        skipped_before_anchor: The count of occurrences skipped because their
            due date was strictly before the anchor (forward-only).
        skipped_done: The ids of occurrences skipped because they are done or
            archived.
    """

    series_id: str
    anchor_date: date | None
    old_pattern_desc: str
    new_pattern_desc: str
    updated_task_ids: list[str]
    skipped_before_anchor: int
    skipped_done: list[str]


def update_series(
    ctx: DotoContext,
    series_id: str,
    *,
    pattern: RecurrencePattern | None = None,
    title_template: str | None = None,
    anchor_date: date | None = None,
    dry_run: bool = False,
) -> SeriesUpdateResult:
    """Update a series' metadata and (optionally) re-stamp forward occurrences.

    The single source of truth for updating a series, shared by the CLI
    ``doto series update`` command
    (:func:`doxtr_doto.cli.commands.series.series_update`) and the TUI
    (:meth:`doxtr_doto.cli.tui.app.DotoApp.action_edit_series`) so the two
    never diverge. Mirrors the store path of :func:`add_series` /
    :func:`update_task`: writes go through
    :meth:`JsonTaskStore.update_series` / :meth:`JsonTaskStore.update_task` and
    a single :meth:`JsonTaskStore.save` at the end.

    Behavior:

    * When ``pattern`` / ``title_template`` are given they are written to the
      stored series (only the keys that actually changed are included).
    * When ``anchor_date`` is ``None`` the update is **metadata-only**: no task
      is re-stamped.
    * Otherwise the series' tasks are iterated (via
      :meth:`JsonTaskStore.get_tasks_in_series`) and only occurrences whose due
      **date** (any time component stripped) is ``>= anchor_date`` are
      re-stamped. The update is **forward-only**: occurrences before the
      anchor are never touched (even if in the past). Done / archived
      occurrences are skipped and recorded in
      :attr:`SeriesUpdateResult.skipped_done`.

      For each re-stamped occurrence the new ``due`` is recomputed from the
      *effective* pattern applied to the occurrence's own date (via
      :func:`doxtr_doto.cli.recurrence.build_occurrence_due`, so a pattern
      ``start_time`` yields a time-bearing due); the ``estimate`` is set from
      the pattern's ``duration_minutes`` (cleared to ``None`` when the pattern
      carries no duration); and the title is re-rendered from the (new) title
      template (``{date}`` replaced for the occurrence's date) only when the
      template changed.
    * ``dry_run`` computes and returns the result **without** writing or saving.

    Changing the calendar *shape* of the pattern only re-stamps
    time/duration/title onto the *existing* forward dates; it does not move or
    add occurrence dates (use ``doto series extend`` to add dates).

    Args:
        ctx: The CLI context.
        series_id: The series to update (assumed to exist; the caller resolves
            / validates it).
        pattern: The new recurrence pattern, or ``None`` to keep the stored
            one. When ``None`` the stored pattern is used for the re-stamp.
        title_template: The new title template, or ``None`` to keep the stored
            one.
        anchor_date: The forward-only anchor; ``None`` for metadata-only.
        dry_run: When ``True``, compute the result without writing / saving.

    Returns:
        A :class:`SeriesUpdateResult` describing the update.
    """
    store = ctx.store
    series = store.get_series(series_id)
    assert series is not None, f"Series '{series_id}' not found."

    stored_pattern = RecurrencePattern.from_dict(series["pattern"])
    stored_title = series["title_template"]
    effective_pattern = pattern if pattern is not None else stored_pattern
    effective_title = title_template if title_template is not None else stored_title
    title_changed = title_template is not None and title_template != stored_title

    old_pattern_desc = stored_pattern.describe()
    new_pattern_desc = effective_pattern.describe()

    # Build the metadata update (only the keys that actually changed).
    series_updates: dict[str, Any] = {}
    if pattern is not None and pattern.to_dict() != stored_pattern.to_dict():
        series_updates["pattern"] = pattern.to_dict()
    if title_template is not None and title_template != stored_title:
        series_updates["title_template"] = title_template

    updated_task_ids: list[str] = []
    skipped_before_anchor = 0
    skipped_done: list[str] = []

    if anchor_date is not None:
        for task in store.get_tasks_in_series(series_id):
            task_id = task["id"]
            due_date = occurrence_date(task.get("due"))
            if due_date is None:
                # Malformed/missing due: cannot anchor, skip without counting.
                continue
            if due_date < anchor_date:
                skipped_before_anchor += 1
                continue
            if task.get("status") == DONE_STATUS or task.get("archived"):
                skipped_done.append(task_id)
                continue

            task_updates: dict[str, Any] = {
                "due": build_occurrence_due(effective_pattern, due_date),
                "estimate": effective_pattern.duration_minutes,
            }
            if title_changed:
                task_updates["title"] = render_series_title(effective_title, due_date)
            updated_task_ids.append(task_id)
            if not dry_run:
                store.update_task(task_id, task_updates)

    if not dry_run:
        if series_updates:
            store.update_series(series_id, series_updates)
        store.save()

    return SeriesUpdateResult(
        series_id=series_id,
        anchor_date=anchor_date,
        old_pattern_desc=old_pattern_desc,
        new_pattern_desc=new_pattern_desc,
        updated_task_ids=updated_task_ids,
        skipped_before_anchor=skipped_before_anchor,
        skipped_done=skipped_done,
    )


def occurrence_date(due: Any) -> date | None:
    """Return the calendar date of a stored ``due`` value, stripping any time.

    Uses :meth:`doxtr_doto.date_utils.DotoDate.parse_safe` so a malformed or
    missing ``due`` yields ``None`` rather than raising (such occurrences are
    then skipped by :func:`update_series`'s forward-only filter).

    Args:
        due: The stored ``due`` string (``YYYY-MM-DD`` / ``...THH:MM``), or
            ``None``.

    Returns:
        The occurrence's calendar :class:`datetime.date`, or ``None``.
    """
    from doxtr_doto.date_utils import DotoDate

    parsed = DotoDate.parse_safe(due)
    return parsed.date if parsed is not None else None


def delete_task(ctx: DotoContext, task_ref: str) -> bool:
    """Delete a task, reusing the ``doto delete`` store path.

    Resolves the reference via :func:`resolve_task_ref` and writes through
    :meth:`JsonTaskStore.delete_task` + :meth:`JsonTaskStore.save` (the same
    path as the ``doto delete`` verb), so the TUI never duplicates the delete
    logic.

    Pruning the owning series' ``task_ids`` link is handled **inside the
    store** (:meth:`JsonTaskStore.delete_task`), so every delete path -- the
    CLI ``doto delete`` verb and this TUI wrapper alike -- keeps the series'
    occurrence count consistent. This wrapper does not prune separately.

    Args:
        ctx: The CLI context.
        task_ref: A bare or ``repo#id`` task reference.

    Returns:
        True if the task was found and deleted, False if the reference could
        not be resolved or the task did not exist.
    """
    resolved = resolve_task_ref(ctx, task_ref)
    if resolved is None:
        return False
    deleted = resolved.store.delete_task(resolved.task_id)
    if deleted:
        resolved.store.save()
    return deleted


def delete_series(
    ctx: DotoContext,
    series_id: str,
    *,
    delete_tasks: bool,
) -> tuple[bool, list[str]]:
    """Delete a series (optionally its tasks), reusing the store path.

    Thin wrapper over :meth:`JsonTaskStore.delete_series` +
    :meth:`JsonTaskStore.save` (the same path as ``doto series delete``), so
    the TUI never duplicates the delete logic.

    Args:
        ctx: The CLI context.
        series_id: The series to delete (in ``ctx.store``).
        delete_tasks: When True, also delete every task in the series; when
            False, keep the tasks and only remove the series metadata (parity
            with the CLI ``--keep-tasks`` flag).

    Returns:
        A ``(success, deleted_task_ids)`` tuple. ``success`` is False when the
        series did not exist (and ``deleted_task_ids`` is empty).
    """
    success, deleted = ctx.store.delete_series(series_id, delete_tasks=delete_tasks)
    if success:
        ctx.store.save()
    return success, deleted


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


#: The default table-layout detail-pane ratio: the lower detail pane takes 3/4
#: of the total height (so the task list above it takes the remaining 1/4).
DEFAULT_DETAIL_RATIO = "3/4"


def parse_detail_ratio(value: str | None) -> tuple[int, int]:
    """Parse a ``"n/d"`` detail-ratio string into ``(top_fr, detail_fr)``.

    The stored ratio ``n/d`` means the lower detail pane takes ``n/d`` of the
    *total* vertical space, so the detail pane gets ``n`` fractional units of
    height and the task list above it gets the remaining ``d - n`` (e.g.
    ``"3/4"`` -> ``(1, 3)``: detail 3/4 of the space, task list 1/4). The
    numerator must be a positive integer strictly less than the (positive)
    denominator; a malformed, out-of-range, zero, negative, or missing value
    falls back to :data:`DEFAULT_DETAIL_RATIO` so a stale/invalid stored value
    never breaks the layout.

    Args:
        value: The ``"n/d"`` ratio string, or None.

    Returns:
        ``(top_fr, detail_fr)`` - the ``fr`` height units for the task list and
        the detail pane respectively.
    """
    raw = (value or DEFAULT_DETAIL_RATIO).strip()
    parts = raw.split("/")
    if len(parts) == 2:
        try:
            numerator = int(parts[0].strip())
            denominator = int(parts[1].strip())
        except ValueError:
            numerator = denominator = 0
        if 0 < numerator < denominator:
            # ``n/d`` -> detail pane ``n`` fr, task list the remaining ``d-n``.
            return denominator - numerator, numerator
    # Fall back to the default ratio.
    d_num, d_den = (int(p) for p in DEFAULT_DETAIL_RATIO.split("/"))
    return d_den - d_num, d_num


def normalize_detail_ratio(value: str | None) -> str:
    """Return a canonical ``"n/d"`` ratio string, defaulting invalid input.

    Parses ``value`` via :func:`parse_detail_ratio` and re-renders it, so a
    malformed/empty value is normalized to :data:`DEFAULT_DETAIL_RATIO` and a
    well-formed one (e.g. ``" 3 / 4 "``) is tidied to ``"3/4"``. The ``n/d``
    form denotes the detail pane's share of the total height, so it is rebuilt
    as ``detail_fr / (top_fr + detail_fr)``.

    Args:
        value: The candidate ratio string, or None.

    Returns:
        A canonical ``"n/d"`` string.
    """
    top_fr, detail_fr = parse_detail_ratio(value)
    return f"{detail_fr}/{top_fr + detail_fr}"


def load_detail_ratio(ctx: DotoContext) -> str:
    """Return the user's persisted table-layout detail-pane ratio.

    Reads ``tui_detail_ratio`` from the global state the same way
    :func:`load_tui_layout` reads ``tui_layout``. An absent field (older state
    files that predate the feature) or a malformed value falls back to
    :data:`DEFAULT_DETAIL_RATIO` so the behavior is backward compatible.

    Args:
        ctx: The CLI context.

    Returns:
        A canonical ``"n/d"`` detail-ratio string.
    """
    stored = ctx.global_store.load().tui_detail_ratio
    return normalize_detail_ratio(stored)


def save_detail_ratio(ctx: DotoContext, ratio: str) -> None:
    """Persist the user's table-layout detail-pane ratio.

    Writes ``tui_detail_ratio`` into the global state the same atomic
    load -> mutate -> save way :func:`save_tui_layout` persists ``tui_layout``,
    so the chosen ratio becomes the default on the next launch. The value is
    canonicalized via :func:`normalize_detail_ratio` before storing.

    Args:
        ctx: The CLI context.
        ratio: The ``"n/d"`` ratio string to persist.
    """
    state = ctx.global_store.load()
    state.tui_detail_ratio = normalize_detail_ratio(ratio)
    ctx.global_store.save(state)


#: The default width ratio for the edit-task and edit-body/note pop-ups: each
#: modal takes 3/4 of the total terminal width (centered).
DEFAULT_MODAL_WIDTH_RATIO = "3/4"


def parse_modal_width_ratio(value: str | None) -> tuple[int, int]:
    """Parse a ``"n/d"`` modal-width-ratio string into ``(numerator, denom)``.

    The stored ratio ``n/d`` means the modal takes ``n/d`` of the total
    terminal width (e.g. ``"3/4"`` -> three quarters). The numerator must be a
    positive integer strictly less than or equal to the (positive)
    denominator; a malformed, out-of-range, zero, negative, or missing value
    falls back to :data:`DEFAULT_MODAL_WIDTH_RATIO` so a stale/invalid stored
    value never breaks the layout. (Unlike
    :func:`parse_detail_ratio`, ``n == d`` is allowed - a full-width modal is
    a sensible choice.)

    Args:
        value: The ``"n/d"`` ratio string, or None.

    Returns:
        ``(numerator, denominator)`` - the modal's share of the total width.
    """
    raw = (value or DEFAULT_MODAL_WIDTH_RATIO).strip()
    parts = raw.split("/")
    if len(parts) == 2:
        try:
            numerator = int(parts[0].strip())
            denominator = int(parts[1].strip())
        except ValueError:
            numerator = denominator = 0
        if 0 < numerator <= denominator:
            return numerator, denominator
    d_num, d_den = (int(p) for p in DEFAULT_MODAL_WIDTH_RATIO.split("/"))
    return d_num, d_den


def normalize_modal_width_ratio(value: str | None) -> str:
    """Return a canonical ``"n/d"`` modal-width-ratio string.

    Parses ``value`` via :func:`parse_modal_width_ratio` and re-renders it, so
    a malformed/empty value is normalized to
    :data:`DEFAULT_MODAL_WIDTH_RATIO` and a well-formed one (e.g.
    ``" 3 / 4 "``) is tidied to ``"3/4"``.

    Args:
        value: The candidate ratio string, or None.

    Returns:
        A canonical ``"n/d"`` string.
    """
    numerator, denominator = parse_modal_width_ratio(value)
    return f"{numerator}/{denominator}"


def modal_width_percent(value: str | None) -> int:
    """Return the modal width as an integer percentage of the terminal width.

    Parses ``value`` via :func:`parse_modal_width_ratio` and converts the
    ``n/d`` ratio into a percentage (e.g. ``"3/4"`` -> ``75``) suitable for a
    Textual ``width: N%`` style. The result is clamped to ``1..100``.

    Args:
        value: The ``"n/d"`` ratio string, or None.

    Returns:
        The width as an integer percentage in ``1..100``.
    """
    numerator, denominator = parse_modal_width_ratio(value)
    percent = round(numerator * 100 / denominator)
    return max(1, min(100, percent))


def load_modal_width_ratio(ctx: DotoContext) -> str:
    """Return the user's persisted edit/note pop-up width ratio.

    Reads ``tui_modal_width_ratio`` from the global state the same way
    :func:`load_detail_ratio` reads ``tui_detail_ratio``. An absent field
    (older state files that predate the feature) or a malformed value falls
    back to :data:`DEFAULT_MODAL_WIDTH_RATIO` so the behavior is backward
    compatible.

    Args:
        ctx: The CLI context.

    Returns:
        A canonical ``"n/d"`` modal-width-ratio string.
    """
    stored = ctx.global_store.load().tui_modal_width_ratio
    return normalize_modal_width_ratio(stored)


def save_modal_width_ratio(ctx: DotoContext, ratio: str) -> None:
    """Persist the user's edit/note pop-up width ratio.

    Writes ``tui_modal_width_ratio`` into the global state the same atomic
    load -> mutate -> save way :func:`save_detail_ratio` persists
    ``tui_detail_ratio``, so the chosen ratio becomes the default on the next
    launch. The value is canonicalized via :func:`normalize_modal_width_ratio`
    before storing.

    Args:
        ctx: The CLI context.
        ratio: The ``"n/d"`` ratio string to persist.
    """
    state = ctx.global_store.load()
    state.tui_modal_width_ratio = normalize_modal_width_ratio(ratio)
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

    # Recent-done filter: on by default (seeded from the config's
    # ``tui_recent_done_days``, default 10) until the user toggles it in the
    # filter pop-up, after which their choice persists. ``recent_done_days``
    # is None when the filter is disabled (show all done) and a positive int N
    # when active (hide done completed > N days ago). A stale/invalid persisted
    # day count falls back to the config default so a bad value never breaks
    # the view.
    config_days = int(getattr(ctx.config, "tui_recent_done_days", 10))
    enabled = state.tui_recent_done_enabled
    if enabled is None:
        enabled = True  # On by default on first use.
    stored_days = state.tui_recent_done_days
    if stored_days is None:
        days = config_days
    else:
        try:
            days = int(stored_days)
        except (TypeError, ValueError):
            # Corrupt persisted value (e.g. a non-numeric string): fall back
            # to the config default rather than crashing the view.
            days = config_days
    recent_done_days = days if enabled and days > 0 else None

    return ViewPrefs(
        hide_completed=bool(state.tui_hide_completed),
        recent_done_days=recent_done_days,
        conflicts_only=bool(state.tui_conflicts_only),
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
    # Recent-done filter: persist both the on/off state and the chosen window
    # so the user's choice survives restarts (overriding the config default).
    # ``recent_done_days`` None means disabled (show all done); a positive int
    # means active with that N.
    state.tui_recent_done_enabled = prefs.recent_done_days is not None
    if prefs.recent_done_days is not None:
        state.tui_recent_done_days = prefs.recent_done_days
    state.tui_conflicts_only = bool(prefs.conflicts_only)
    state.tui_due_filter = prefs.due_filter.value
    state.tui_tag_filter = prefs.tag_filter or None
    state.tui_priority_filter = prefs.priority_filter or None
    state.tui_sort_key = prefs.sort_key.value
    state.tui_sort_order = prefs.sort_order.value
    state.tui_repo_filter = list(prefs.repo_filter) or None
    ctx.global_store.save(state)
