"""Pure, unit-testable filter + sort helpers for the doto TUI.

These functions assemble the task list the TUI shows after the gathered task
set (:func:`doxtr_doto.cli.tui.data.gather_tasks`) has passed the text filter
(:attr:`doxtr_doto.cli.tui.app.DotoApp.filter_term`). They are deliberately
*pure* - no I/O, no mutation of their inputs - so they can be unit-tested
without rendering the TUI and reused/overridden by a child theme.

The composition order the app wires in
:meth:`doxtr_doto.cli.tui.app.DotoApp._visible_tasks` is::

    gather -> text filter_term -> apply ViewPrefs filters
          -> apply ViewPrefs sort -> pin active task(s) to top

:func:`apply_view_prefs` composes the three pipeline steps
(:func:`apply_filters`, :func:`apply_sort`, :func:`pin_active_first`) through
**injectable step callables** that default to those module functions, and the
app exposes each as an overridable ``staticmethod`` class attribute
(:attr:`~doxtr_doto.cli.tui.app.DotoApp.apply_filters` /
:attr:`~doxtr_doto.cli.tui.app.DotoApp.apply_sort` /
:attr:`~doxtr_doto.cli.tui.app.DotoApp.pin_active_first`) that
:meth:`~doxtr_doto.cli.tui.app.DotoApp._visible_tasks` passes in. A child theme
can therefore swap any one step by setting a single attribute (mirroring the
``*_class`` widget/screen seam) without re-implementing ``_visible_tasks``.
:func:`pin_active_first` (Feature A) is applied *last* so the active
(time-recorded) task stays on top regardless of the configured sort
(Feature C).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from doxtr_doto.constants import DONE_STATUS, PRIORITY_ORDER
from doxtr_doto.enums import DueFilter, SortKey, SortOrder


@dataclass
class ViewPrefs:
    """The user-configurable filter + sort preferences for the TUI task list.

    A small, serializable settings object that
    :func:`apply_view_prefs` consumes to filter and sort the gathered task
    set. It is round-tripped through global state (via
    :func:`doxtr_doto.cli.tui.actions.load_view_prefs` /
    :func:`doxtr_doto.cli.tui.actions.save_view_prefs`) so the last filter/sort
    state is remembered across TUI sessions (the sort-memory requirement).

    Attributes:
        hide_completed: Hide tasks whose status is ``done`` when True.
        recent_done_days: When set to a positive int ``N``, hide ``done`` tasks
            whose ``completed_at`` timestamp is strictly older than ``N`` days
            (recently-completed tasks and non-``done`` tasks are kept). None
            disables the filter (all ``done`` tasks shown). This is
            independent of :attr:`hide_completed` and only matters when
            ``hide_completed`` is False (otherwise *every* done task is already
            hidden). Done tasks with a missing/unparseable ``completed_at``
            (e.g. completed before the timestamp existed) are always kept, so
            upgrading never hides legitimately-visible history.
        conflicts_only: Keep only tasks flagged with an unresolved
            calendar-sync conflict (``sync_conflict`` truthy) when True, so the
            user can jump to the tasks needing a hand-merge.
        due_filter: Which due-date window to keep (:class:`DueFilter`): all,
            due today, or due this week.
        tag_filter: Keep only tasks carrying this tag (case-insensitive). None
            or empty means no tag filter.
        priority_filter: Keep only tasks with this priority. None or empty
            means no priority filter.
        sort_key: How to order the kept tasks (:class:`SortKey`).
        sort_order: Ascending or descending (:class:`SortOrder`).
        repo_filter: The repository names to keep (matched case-sensitively
            against each task's ``_repo`` tag). An empty tuple means no repo
            filter - every repository's tasks pass. Only meaningful in
            :data:`doxtr_doto.cli.display.DisplayScope.GLOBAL`; in LOCAL the
            app suppresses it (see
            :meth:`doxtr_doto.cli.tui.app.DotoApp._visible_tasks`) so the
            current repo is always shown regardless of a persisted selection.
            Stored as an immutable tuple so a :class:`ViewPrefs` stays
            hashable/safe to share and the dataclass default cannot be
            mutated across instances.
    """

    hide_completed: bool = False
    recent_done_days: int | None = None
    conflicts_only: bool = False
    due_filter: DueFilter = DueFilter.ALL
    tag_filter: str | None = None
    priority_filter: str | None = None
    sort_key: SortKey = SortKey.NONE
    sort_order: SortOrder = SortOrder.ASC
    repo_filter: tuple[str, ...] = field(default_factory=tuple)

    def is_default(self) -> bool:
        """Return whether the prefs are entirely at their defaults.

        Lets the app skip the filter/sort pass (and surface a "no prefs"
        state) when nothing is configured.

        Returns:
            True when no filter is active and the sort is the default
            (no explicit sort, ascending).
        """
        return (
            not self.hide_completed
            and self.recent_done_days is None
            and not self.conflicts_only
            and self.due_filter is DueFilter.ALL
            and not self.tag_filter
            and not self.priority_filter
            and not self.repo_filter
            and self.sort_key is SortKey.NONE
            and self.sort_order is SortOrder.ASC
        )


def _parse_due(task: dict[str, Any]) -> date | None:
    """Return a task's ``due`` field as a date, or None when absent/invalid.

    Args:
        task: A task dict.

    Returns:
        The parsed :class:`datetime.date`, or None when the ``due`` field is
        missing, empty, or not a valid ISO date.
    """
    raw = task.get("due")
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def filter_hide_completed(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return ``tasks`` with completed (``done``) tasks removed.

    Args:
        tasks: The task dicts to filter.

    Returns:
        A new list excluding tasks whose status is :data:`DONE_STATUS`.
    """
    return [t for t in tasks if t.get("status") != DONE_STATUS]


def filter_done_recent(
    tasks: list[dict[str, Any]],
    max_age_days: int,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Hide ``done`` tasks completed longer than ``max_age_days`` days ago.

    Keeps every non-``done`` task unchanged and keeps ``done`` tasks whose
    ``completed_at`` timestamp is within the last ``max_age_days`` days
    (inclusive). A ``done`` task with a missing or unparseable ``completed_at``
    is **always kept** (backward compatibility: tasks completed before the
    timestamp existed carry no date, and we must not hide legitimately-visible
    history just because we cannot tell when they were completed). Only
    ``done`` tasks whose ``completed_at`` is strictly older than
    ``max_age_days`` days are dropped.

    Args:
        tasks: The task dicts to filter.
        max_age_days: The maximum completion age, in days, to keep a done task.
            A non-positive value keeps only done tasks completed *today*
            (``0``) and still keeps undated done tasks.
        today: Reference "today" (defaults to the current local date), so the
            window is deterministic in tests.

    Returns:
        A new list with stale done tasks removed; every other task preserved.
    """
    reference = today if today is not None else date.today()
    cutoff = reference - timedelta(days=max_age_days)
    kept: list[dict[str, Any]] = []
    for task in tasks:
        if task.get("status") != DONE_STATUS:
            kept.append(task)
            continue
        completed = _parse_completed_at(task)
        # Missing/unparseable completion date: always keep (back-compat).
        if completed is None or completed >= cutoff:
            kept.append(task)
    return kept


def _parse_completed_at(task: dict[str, Any]) -> date | None:
    """Return a task's ``completed_at`` field as a date, or None when invalid.

    Only the calendar date is used (any time component is stripped) since the
    recent-done window is measured in whole days.

    Args:
        task: A task dict.

    Returns:
        The parsed :class:`datetime.date`, or None when ``completed_at`` is
        missing, empty, or not a valid ISO-8601 timestamp.
    """
    raw = task.get("completed_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw)).date()
    except ValueError:
        return None


def filter_sync_conflicts(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only ``tasks`` flagged with an unresolved calendar-sync conflict.

    A two-way merge that wrote git-style conflict markers into a task body sets
    a persistent ``sync_conflict`` flag (see
    :func:`doxtr_doto.calsync.engine.two_way_sync`). This keeps only those
    tasks so the user can jump straight to the ones needing a hand-merge.

    Args:
        tasks: The task dicts to filter.

    Returns:
        A new list keeping only tasks whose ``sync_conflict`` flag is truthy.
    """
    return [t for t in tasks if t.get("sync_conflict")]


def filter_by_due(
    tasks: list[dict[str, Any]],
    due_filter: DueFilter,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Return ``tasks`` filtered to the given due-date window.

    Args:
        tasks: The task dicts to filter.
        due_filter: The due window (:class:`DueFilter`). :attr:`DueFilter.ALL`
            keeps everything.
        today: Reference "today" (defaults to the current local date), so the
            window is deterministic in tests.

    Returns:
        A new list keeping only tasks due within the window. The week window is
        today through the coming Sunday (inclusive); undated tasks are dropped
        by any non-``ALL`` filter.
    """
    if due_filter is DueFilter.ALL:
        return list(tasks)
    reference = today if today is not None else date.today()
    if due_filter is DueFilter.TODAY:
        return [t for t in tasks if _parse_due(t) == reference]
    # DueFilter.WEEK: today through the coming Sunday (Monday=0 .. Sunday=6).
    week_end = reference + timedelta(days=6 - reference.weekday())
    kept: list[dict[str, Any]] = []
    for task in tasks:
        due = _parse_due(task)
        if due is not None and reference <= due <= week_end:
            kept.append(task)
    return kept


def filter_by_tag(tasks: list[dict[str, Any]], tag: str) -> list[dict[str, Any]]:
    """Return ``tasks`` carrying ``tag`` (case-insensitive).

    Args:
        tasks: The task dicts to filter.
        tag: The tag to require. An empty tag keeps everything.

    Returns:
        A new list keeping only tasks whose ``tags`` include ``tag``
        (case-insensitively).
    """
    needle = tag.strip().lower()
    if not needle:
        return list(tasks)
    return [t for t in tasks if any(str(x).lower() == needle for x in (t.get("tags") or []))]


def filter_by_priority(tasks: list[dict[str, Any]], priority: str) -> list[dict[str, Any]]:
    """Return ``tasks`` with the given ``priority``.

    Args:
        tasks: The task dicts to filter.
        priority: The priority to require. An empty priority keeps everything.

    Returns:
        A new list keeping only tasks whose ``priority`` matches
        (case-insensitively).
    """
    needle = priority.strip().lower()
    if not needle:
        return list(tasks)
    return [t for t in tasks if str(t.get("priority") or "").lower() == needle]


def filter_by_repos(
    tasks: list[dict[str, Any]],
    repos: Sequence[str],
) -> list[dict[str, Any]]:
    """Return ``tasks`` whose owning repository is in ``repos``.

    Each task carries its owning repository under ``_repo`` (set by
    :func:`doxtr_doto.cli.display.tag_repo` during
    :func:`doxtr_doto.cli.tui.data.gather_tasks`). This keeps only the tasks
    whose ``_repo`` is one of ``repos``, matched on the repo *name*
    case-sensitively. An empty ``repos`` keeps everything, so the repo filter
    is inert until the user selects at least one repository.

    Args:
        tasks: The task dicts to filter.
        repos: The repository names to keep. Empty keeps everything.

    Returns:
        A new list keeping only tasks whose ``_repo`` is in ``repos`` (all
        tasks when ``repos`` is empty).
    """
    if not repos:
        return list(tasks)
    allowed = set(repos)
    return [t for t in tasks if t.get("_repo") in allowed]


def apply_filters(
    tasks: list[dict[str, Any]],
    prefs: ViewPrefs,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Apply every active :class:`ViewPrefs` filter to ``tasks`` in order.

    Composes the individual, overridable filter helpers
    (:func:`filter_hide_completed`, :func:`filter_done_recent`,
    :func:`filter_by_due`, :func:`filter_by_tag`, :func:`filter_by_priority`,
    :func:`filter_by_repos`). Each is a no-op when its corresponding pref is
    unset, so the result is ``tasks`` unchanged when no filter is configured.
    The recent-done filter (:attr:`ViewPrefs.recent_done_days`) only runs when
    :attr:`ViewPrefs.hide_completed` is False - hiding *all* done tasks already
    supersedes hiding only the stale ones. The repo filter only has
    an effect when :attr:`ViewPrefs.repo_filter` is non-empty. The LOCAL-scope
    contract (where the gathered set is already the single current repo) is
    enforced by the *caller* -
    :meth:`doxtr_doto.cli.tui.app.DotoApp._visible_tasks` suppresses
    ``repo_filter`` in LOCAL before calling this - so this pure helper stays
    scope-agnostic and simply applies whatever filter it is given.

    Args:
        tasks: The task dicts to filter.
        prefs: The configured view preferences.
        today: Reference "today" for the due filter (defaults to local today).

    Returns:
        A new list with every active filter applied.
    """
    result = list(tasks)
    if prefs.hide_completed:
        result = filter_hide_completed(result)
    elif prefs.recent_done_days is not None:
        # Independent of hide_completed: only prune stale done tasks when we
        # are *not* already hiding every done task. When hide_completed is on
        # the recent-done filter is a redundant no-op, so skip it.
        result = filter_done_recent(result, prefs.recent_done_days, today)
    if prefs.conflicts_only:
        result = filter_sync_conflicts(result)
    result = filter_by_due(result, prefs.due_filter, today)
    if prefs.tag_filter:
        result = filter_by_tag(result, prefs.tag_filter)
    if prefs.priority_filter:
        result = filter_by_priority(result, prefs.priority_filter)
    if prefs.repo_filter:
        result = filter_by_repos(result, prefs.repo_filter)
    return result


def _due_sort_key(task: dict[str, Any]) -> str:
    """Return a sortable due-date string (undated tasks sort last).

    Args:
        task: A task dict.

    Returns:
        The ISO ``due`` date, or a sentinel ``"9999-99-99"`` for undated tasks
        so they sort after every dated task in ascending order.
    """
    due = _parse_due(task)
    return due.isoformat() if due is not None else "9999-99-99"


def _priority_sort_key(task: dict[str, Any]) -> int:
    """Return a sortable priority rank (higher is more important).

    Args:
        task: A task dict.

    Returns:
        The priority's rank from :data:`doxtr_doto.constants.PRIORITY_ORDER`
        (critical=4 .. low=1), or 0 for an unknown/absent priority so it sorts
        below all known priorities in ascending order.
    """
    return PRIORITY_ORDER.get(str(task.get("priority") or "").lower(), 0)


def _tag_sort_key(task: dict[str, Any]) -> str:
    """Return a sortable first-tag string (untagged tasks sort last).

    Args:
        task: A task dict.

    Returns:
        The task's lowest (alphabetically first) tag lowercased, or a sentinel
        ``"\\uffff"`` for untagged tasks so they sort after every tagged task
        in ascending order.
    """
    tags = [str(x).lower() for x in (task.get("tags") or [])]
    return min(tags) if tags else "\uffff"


def apply_sort(
    tasks: list[dict[str, Any]],
    prefs: ViewPrefs,
    all_tasks: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return ``tasks`` sorted by the configured :class:`SortKey` / order.

    The sort is **stable** so tasks that compare equal keep their incoming
    (gathered) order. :attr:`SortKey.NONE` returns ``tasks`` unchanged (a
    copy). The ``next`` key reuses the ``doto next`` scoring
    (:func:`doxtr_doto.cli.commands.next.calculate_task_score`) rather than
    duplicating it, so the TUI's recommended-next order matches the CLI; its
    higher-is-first score is ordered descending for ``ASC`` (the recommended
    task first) and the sign is flipped for ``DESC``.

    Args:
        tasks: The task dicts to sort.
        prefs: The configured view preferences.
        all_tasks: The full id -> task mapping used by the ``next`` scorer to
            resolve dependency blocks. Defaults to a mapping built from
            ``tasks`` themselves (keyed by display ``id``) when None, which is
            sufficient for the common single-scope case.

    Returns:
        A new, stably sorted list.
    """
    if prefs.sort_key is SortKey.NONE:
        return list(tasks)

    reverse = prefs.sort_order is SortOrder.DESC

    if prefs.sort_key is SortKey.NEXT:
        from doxtr_doto.cli.commands.next import calculate_task_score

        mapping = all_tasks
        if mapping is None:
            mapping = {str(t.get("id", "")): t for t in tasks}
        scored: list[tuple[int, str, str]] = []
        for task in tasks:
            tid = str(task.get("id", ""))
            score, due_sort, _ = calculate_task_score(tid, task, mapping)
            scored.append((score, due_sort, tid))
        # Higher score first (recommended-next), tie-break on earlier due then
        # id, mirroring doto next's get_ready_tasks ordering. ASC means
        # "recommended first", so the base order is score-descending.
        order = sorted(
            range(len(tasks)),
            key=lambda i: (-scored[i][0], scored[i][1], scored[i][2]),
        )
        ordered = [tasks[i] for i in order]
        return list(reversed(ordered)) if reverse else ordered

    key_fns: dict[SortKey, Callable[[dict[str, Any]], Any]] = {
        SortKey.DUE: _due_sort_key,
        SortKey.PRIORITY: _priority_sort_key,
        SortKey.TAG: _tag_sort_key,
    }
    key_fn = key_fns[prefs.sort_key]
    # Tie-break asymmetry under DESC: this key-fn path uses ``sorted(reverse=
    # True)``, which reverses only the primary key while keeping equal-key
    # (gathered) order stable; the NEXT path above instead ``reversed()`` the
    # whole base order, which also flips its ``(due, id)`` secondary tie-break.
    # The two sort paths therefore resolve ties differently under DESC - by
    # design (NEXT mirrors ``doto next``), not a bug.
    return sorted(tasks, key=key_fn, reverse=reverse)


def pin_active_first(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return ``tasks`` reordered so running (active) tasks come first.

    Feature A: the currently active task - the one with an open worklog
    session, flagged ``task["_running"] is True`` by
    :func:`doxtr_doto.cli.tui.data.gather_tasks` - must be pinned to the TOP of
    every view's list. This is the single, pure, overridable helper every view
    applies *after* sorting, so the active task stays on top regardless of the
    configured sort (Feature C).

    The reorder is **stable**: non-running tasks keep their relative order and,
    when several tasks are running, those keep their relative order too.

    Args:
        tasks: The task dicts to reorder (already filtered/sorted).

    Returns:
        A new list with running tasks first, otherwise the input order
        preserved.
    """
    running = [t for t in tasks if t.get("_running")]
    rest = [t for t in tasks if not t.get("_running")]
    return running + rest


@dataclass(frozen=True)
class TreeRow:
    """One flattened row of the parent/child task tree.

    :func:`flatten_tree` produces an ordered list of these: a depth-first
    pre-order walk of the ``parent`` forest (see
    :class:`doxtr_doto.sync.json_store.TaskData`) built from the visible task
    list. Each row carries just enough shape for the renderer
    (:meth:`doxtr_doto.cli.tui.widgets.TaskList.format_row` via
    :meth:`~doxtr_doto.cli.tui.widgets.TaskList.format_tree_prefix`) to draw an
    expand/collapse triangle and depth indentation without re-deriving the
    hierarchy.

    Attributes:
        task: The task dict for this row (the same dict from the visible list).
        depth: The nesting level - 0 for a root, 1 for its children, and so on.
        has_children: True when this task has at least one visible child (so a
            triangle is drawn and Space toggles its expansion).
        expanded: True when this task's children are currently shown. Always
            False for a leaf (``has_children`` False).
    """

    task: dict[str, Any]
    depth: int
    has_children: bool
    expanded: bool


def flatten_tree(
    tasks: list[dict[str, Any]],
    expanded_ids: set[str] | None = None,
    *,
    default_expanded: bool = True,
) -> list[TreeRow]:
    """Flatten the visible task forest into ordered, depth-annotated rows.

    Pure helper (no I/O, no input mutation) that turns the ordered visible
    task list into the rows the TUI draws, nesting children under their
    ``parent`` (see :class:`doxtr_doto.sync.json_store.TaskData`) as an
    expandable tree. A task whose ``parent`` is None/absent *or* whose parent
    is not in the visible set (e.g. filtered out) is treated as a ROOT, so a
    child never vanishes just because its parent is hidden.

    The walk is depth-first pre-order: each task is emitted, then - when it is
    expanded - its children (recursively), to arbitrary depth. The children of
    a collapsed task are omitted. Sibling order follows the incoming ``tasks``
    order (which already reflects the configured sort / active-pin), so the
    ordering stays deterministic.

    Expansion is tracked by the caller-supplied ``expanded_ids`` set, but the
    *default* for a task not mentioned there is ``default_expanded`` (True by
    default, so new parents show their children). A caller that wants
    collapse-by-default flips the flag and uses ``expanded_ids`` as the set of
    *expanded* ids; the recommended session-scoped home
    (:attr:`doxtr_doto.cli.tui.app.DotoApp._collapsed_ids`) instead passes the
    *collapsed* ids with ``default_expanded=True`` so unseen parents default
    open - see that attribute.

    A visited guard makes the walk robust against a malformed store that still
    contains a ``parent`` cycle (the acyclic invariant is enforced at write
    time via :func:`doxtr_doto.sync.json_store.would_create_cycle`, but a
    hand-edited store could violate it): each task is emitted at most once and
    the recursion can never loop forever.

    An active (``_running``) task is *always* kept visible even when an
    ancestor is collapsed: before walking, the full ancestor chain of every
    running task is force-expanded (treated as expanded regardless of the
    collapsed set), so the running sub-task and the path down to it always
    show in their correct hierarchical position. Without this, collapsing a
    parent would hide a sub-task the user is actively timing - the user could
    be running a timer on a task they cannot see. The force-expand is
    recursive/multi-level: a running node N levels deep force-expands all N of
    its ancestors. A running task's *own* children still honour the collapsed
    set (only the chain of ancestors leading to the running task is forced
    open, not the running task's own subtree).

    Args:
        tasks: The ordered, filtered, sorted visible task dicts.
        expanded_ids: The set of task ids whose expansion state differs from
            ``default_expanded``. When ``default_expanded`` is True this is the
            set of *collapsed* ids; when False it is the set of *expanded*
            ids. None is treated as empty.
        default_expanded: Whether a task not listed in ``expanded_ids`` is
            expanded. True (the app default) means children show unless the
            parent was explicitly collapsed.

    Returns:
        The flattened :class:`TreeRow` list in display order.
    """
    toggled = expanded_ids or set()
    by_id = {str(t.get("id", "")): t for t in tasks}
    visible_ids = set(by_id)
    # Children grouped by parent id, preserving incoming sibling order.
    children: dict[str, list[dict[str, Any]]] = {}
    roots: list[dict[str, Any]] = []

    # Force-expand the full ancestor chain of every running task so an active
    # (time-recorded) sub-task stays visible even when an ancestor is
    # collapsed - otherwise the user could be timing a task they cannot see.
    # Recursive/multi-level: walk each running task's ``parent`` chain and
    # mark every ancestor force-expanded (a visited guard keeps a residual
    # cycle from looping forever).
    force_expanded: set[str] = set()
    for task in tasks:
        if not task.get("_running"):
            continue
        seen: set[str] = set()
        current: str | None = str(task.get("id", ""))
        # Skip the running task itself; force-expand only its ancestors so the
        # path *down to* it stays open while its own subtree still honours the
        # collapsed set.
        if current is not None:
            seen.add(current)
            current = by_id.get(current, {}).get("parent") if current in visible_ids else None
        while current is not None and current in visible_ids and current not in seen:
            seen.add(current)
            force_expanded.add(current)
            current = by_id[current].get("parent")

    def is_root(task: dict[str, Any]) -> bool:
        """A task is a root when its parent is None/absent/filtered-out, or
        when walking its ``parent`` chain never terminates at such a task (a
        residual cycle - defensively promoted to a root so its nodes still
        appear and the flatten cannot stall)."""
        parent = task.get("parent")
        if parent is None or parent not in visible_ids:
            return True
        seen: set[str] = {str(task.get("id", ""))}
        current: str | None = str(parent)
        while current is not None and current in visible_ids:
            if current in seen:
                # Cycle: no root ancestor reachable - treat as a root itself.
                return True
            seen.add(current)
            current = by_id[current].get("parent")
        return False

    for task in tasks:
        parent = task.get("parent")
        if parent is not None and parent in visible_ids:
            children.setdefault(str(parent), []).append(task)
        if is_root(task):
            roots.append(task)

    def is_expanded(task_id: str) -> bool:
        # An ancestor of a running task is always shown as expanded so the
        # running task below it stays visible, regardless of the collapsed set.
        if task_id in force_expanded:
            return True
        toggled_here = task_id in toggled
        return not default_expanded if toggled_here else default_expanded

    rows: list[TreeRow] = []
    visited: set[str] = set()

    def walk(task: dict[str, Any], depth: int) -> None:
        task_id = str(task.get("id", ""))
        if task_id in visited:
            return
        visited.add(task_id)
        kids = children.get(task_id, [])
        has_children = bool(kids)
        expanded = has_children and is_expanded(task_id)
        rows.append(TreeRow(task, depth, has_children, expanded))
        if expanded:
            for child in kids:
                walk(child, depth + 1)

    for root in roots:
        walk(root, 0)
    return rows


def apply_view_prefs(
    tasks: list[dict[str, Any]],
    prefs: ViewPrefs,
    today: date | None = None,
    all_tasks: dict[str, dict[str, Any]] | None = None,
    *,
    apply_filters_fn: Callable[
        [list[dict[str, Any]], ViewPrefs, date | None], list[dict[str, Any]]
    ] = apply_filters,
    apply_sort_fn: Callable[
        [list[dict[str, Any]], ViewPrefs, dict[str, dict[str, Any]] | None],
        list[dict[str, Any]],
    ] = apply_sort,
    pin_active_first_fn: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] = pin_active_first,
) -> list[dict[str, Any]]:
    """Filter, sort, then pin the active task - the full composed pipeline.

    The single entry point the app's :meth:`_visible_tasks` composes after the
    text filter: it runs the filter step, then the sort step, then the
    active-pin step so the active (time-recorded) task is always on top
    (Feature A) regardless of the configured sort (Feature C).

    Each step is an **injectable callable** defaulting to the module function
    (:func:`apply_filters` / :func:`apply_sort` / :func:`pin_active_first`), so
    a child theme can swap exactly one step by passing a replacement - which is
    how :meth:`doxtr_doto.cli.tui.app.DotoApp._visible_tasks` wires the app's
    overridable ``staticmethod`` seams (``apply_filters``/``apply_sort``/
    ``pin_active_first``) through here. Setting one of those attributes on a
    :class:`~doxtr_doto.cli.tui.app.DotoApp` subclass replaces that single
    pipeline step, mirroring the ``*_class`` widget/screen seam.

    Args:
        tasks: The task dicts (already text-filtered).
        prefs: The configured view preferences.
        today: Reference "today" for the due filter (defaults to local today).
        all_tasks: The full id -> task mapping for the ``next`` scorer; see
            :func:`apply_sort`.
        apply_filters_fn: The filter step (defaults to :func:`apply_filters`).
        apply_sort_fn: The sort step (defaults to :func:`apply_sort`).
        pin_active_first_fn: The active-pin step (defaults to
            :func:`pin_active_first`).

    Returns:
        The filtered, sorted, active-pinned task list.
    """
    filtered = apply_filters_fn(tasks, prefs, today)
    ordered = apply_sort_fn(filtered, prefs, all_tasks)
    return pin_active_first_fn(ordered)
