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
from datetime import date, timedelta
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
    (:func:`filter_hide_completed`, :func:`filter_by_due`,
    :func:`filter_by_tag`, :func:`filter_by_priority`, :func:`filter_by_repos`).
    Each is a no-op when its corresponding pref is unset, so the result is
    ``tasks`` unchanged when no filter is configured. The repo filter only has
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
