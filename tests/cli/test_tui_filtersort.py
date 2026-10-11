"""Pure-logic tests for the TUI filter/sort helpers (Feature A + C).

These exercise :mod:`doxtr_doto.cli.tui.filtersort` directly - no Textual
rendering - so they run regardless of whether the optional ``textual``
dependency is installed, mirroring the pure-logic sections of
``tests/cli/test_tui.py``.
"""

from __future__ import annotations

from datetime import date, timedelta

from doxtr_doto.cli.tui.filtersort import (
    ViewPrefs,
    apply_filters,
    apply_sort,
    apply_view_prefs,
    filter_by_due,
    filter_by_priority,
    filter_by_repos,
    filter_by_tag,
    filter_hide_completed,
    pin_active_first,
)
from doxtr_doto.enums import DueFilter, SortKey, SortOrder


def _task(tid, **kw):
    """Return a minimal task dict with sensible defaults."""
    task = {
        "id": tid,
        "title": tid,
        "status": "open",
        "priority": "medium",
        "tags": [],
        "worklogs": [],
    }
    task.update(kw)
    return task


class TestPinActiveFirst:
    """Tests for the active-task pin helper (Feature A)."""

    def test_running_task_moves_to_front(self):
        tasks = [_task("A"), _task("B", _running=True), _task("C")]
        result = pin_active_first(tasks)
        assert [t["id"] for t in result] == ["B", "A", "C"]

    def test_stable_when_none_running(self):
        tasks = [_task("A"), _task("B"), _task("C")]
        assert [t["id"] for t in pin_active_first(tasks)] == ["A", "B", "C"]

    def test_multiple_running_keep_relative_order(self):
        tasks = [
            _task("A"),
            _task("B", _running=True),
            _task("C"),
            _task("D", _running=True),
        ]
        result = pin_active_first(tasks)
        # Both running first, in their original relative order; rest stable.
        assert [t["id"] for t in result] == ["B", "D", "A", "C"]

    def test_does_not_mutate_input(self):
        tasks = [_task("A"), _task("B", _running=True)]
        pin_active_first(tasks)
        assert [t["id"] for t in tasks] == ["A", "B"]

    def test_empty(self):
        assert pin_active_first([]) == []


class TestFilters:
    """Tests for each individual filter helper and their composition."""

    def test_hide_completed(self):
        tasks = [_task("A", status="done"), _task("B", status="open")]
        assert [t["id"] for t in filter_hide_completed(tasks)] == ["B"]

    def test_due_filter_all_keeps_everything(self):
        tasks = [_task("A", due="2024-01-01"), _task("B")]
        assert filter_by_due(tasks, DueFilter.ALL) == tasks

    def test_due_filter_today(self):
        today = date(2024, 6, 10)
        tasks = [
            _task("A", due="2024-06-10"),
            _task("B", due="2024-06-11"),
            _task("C"),  # undated
        ]
        result = filter_by_due(tasks, DueFilter.TODAY, today=today)
        assert [t["id"] for t in result] == ["A"]

    def test_due_filter_week(self):
        # 2024-06-10 is a Monday; the week window runs through Sunday 06-16.
        today = date(2024, 6, 10)
        tasks = [
            _task("A", due="2024-06-10"),  # today -> in
            _task("B", due="2024-06-16"),  # Sunday -> in
            _task("C", due="2024-06-17"),  # next Monday -> out
            _task("D", due="2024-06-09"),  # yesterday -> out
            _task("E"),  # undated -> out
        ]
        result = filter_by_due(tasks, DueFilter.WEEK, today=today)
        assert [t["id"] for t in result] == ["A", "B"]

    def test_due_filter_ignores_invalid_date(self):
        today = date(2024, 6, 10)
        tasks = [_task("A", due="not-a-date")]
        assert filter_by_due(tasks, DueFilter.TODAY, today=today) == []

    def test_tag_filter_case_insensitive(self):
        tasks = [_task("A", tags=["Alpha"]), _task("B", tags=["beta"])]
        assert [t["id"] for t in filter_by_tag(tasks, "alpha")] == ["A"]

    def test_tag_filter_empty_keeps_all(self):
        tasks = [_task("A"), _task("B")]
        assert filter_by_tag(tasks, "") == tasks

    def test_priority_filter(self):
        tasks = [_task("A", priority="high"), _task("B", priority="low")]
        assert [t["id"] for t in filter_by_priority(tasks, "high")] == ["A"]

    def test_apply_filters_composes_all(self):
        today = date(2024, 6, 10)
        tasks = [
            _task("A", status="done", priority="high", tags=["x"], due="2024-06-10"),
            _task("B", status="open", priority="high", tags=["x"], due="2024-06-10"),
            _task("C", status="open", priority="low", tags=["x"], due="2024-06-10"),
            _task("D", status="open", priority="high", tags=["y"], due="2024-06-10"),
            _task("E", status="open", priority="high", tags=["x"], due="2024-06-20"),
        ]
        prefs = ViewPrefs(
            hide_completed=True,
            due_filter=DueFilter.WEEK,
            tag_filter="x",
            priority_filter="high",
        )
        result = apply_filters(tasks, prefs, today=today)
        # Only B survives: not done, due this week, tag x, high priority.
        assert [t["id"] for t in result] == ["B"]

    def test_apply_filters_default_is_passthrough(self):
        tasks = [_task("A", status="done"), _task("B")]
        assert apply_filters(tasks, ViewPrefs()) == tasks


class TestSort:
    """Tests for each sort key and the asc/desc order."""

    def test_sort_none_is_passthrough(self):
        tasks = [_task("B"), _task("A")]
        assert [t["id"] for t in apply_sort(tasks, ViewPrefs())] == ["B", "A"]

    def test_sort_by_due_ascending_undated_last(self):
        tasks = [
            _task("A", due="2024-06-10"),
            _task("B"),  # undated -> last
            _task("C", due="2024-06-05"),
        ]
        prefs = ViewPrefs(sort_key=SortKey.DUE, sort_order=SortOrder.ASC)
        assert [t["id"] for t in apply_sort(tasks, prefs)] == ["C", "A", "B"]

    def test_sort_by_due_descending(self):
        tasks = [
            _task("A", due="2024-06-10"),
            _task("C", due="2024-06-05"),
        ]
        prefs = ViewPrefs(sort_key=SortKey.DUE, sort_order=SortOrder.DESC)
        assert [t["id"] for t in apply_sort(tasks, prefs)] == ["A", "C"]

    def test_sort_by_priority_ascending_low_first(self):
        tasks = [
            _task("A", priority="critical"),
            _task("B", priority="low"),
            _task("C", priority="high"),
        ]
        prefs = ViewPrefs(sort_key=SortKey.PRIORITY, sort_order=SortOrder.ASC)
        # Ascending by rank: low(1) < high(3) < critical(4).
        assert [t["id"] for t in apply_sort(tasks, prefs)] == ["B", "C", "A"]

    def test_sort_by_priority_descending_critical_first(self):
        tasks = [
            _task("A", priority="low"),
            _task("B", priority="critical"),
        ]
        prefs = ViewPrefs(sort_key=SortKey.PRIORITY, sort_order=SortOrder.DESC)
        assert [t["id"] for t in apply_sort(tasks, prefs)] == ["B", "A"]

    def test_sort_by_tag_ascending_untagged_last(self):
        tasks = [
            _task("A", tags=["zeta"]),
            _task("B", tags=["alpha"]),
            _task("C"),  # untagged -> last
        ]
        prefs = ViewPrefs(sort_key=SortKey.TAG, sort_order=SortOrder.ASC)
        assert [t["id"] for t in apply_sort(tasks, prefs)] == ["B", "A", "C"]

    def test_sort_next_reuses_doto_next_scoring(self):
        # The in-progress task scores far higher in doto next's scoring, so
        # ``next`` ascending ("recommended first") puts it first.
        tasks = [
            _task("A", status="open", priority="low"),
            _task("B", status="in-progress", priority="low"),
        ]
        prefs = ViewPrefs(sort_key=SortKey.NEXT, sort_order=SortOrder.ASC)
        assert [t["id"] for t in apply_sort(tasks, prefs)] == ["B", "A"]

    def test_sort_next_descending_flips(self):
        tasks = [
            _task("A", status="open", priority="low"),
            _task("B", status="in-progress", priority="low"),
        ]
        prefs = ViewPrefs(sort_key=SortKey.NEXT, sort_order=SortOrder.DESC)
        assert [t["id"] for t in apply_sort(tasks, prefs)] == ["A", "B"]

    def test_sort_is_stable_on_ties(self):
        tasks = [
            _task("A", priority="high"),
            _task("B", priority="high"),
            _task("C", priority="high"),
        ]
        prefs = ViewPrefs(sort_key=SortKey.PRIORITY, sort_order=SortOrder.ASC)
        assert [t["id"] for t in apply_sort(tasks, prefs)] == ["A", "B", "C"]


class TestApplyViewPrefs:
    """Tests for the composed filter -> sort -> active-pin pipeline."""

    def test_active_pin_wins_over_sort(self):
        # Even though sorting by priority would put the critical task first,
        # the running task is pinned to the very top (Feature A beats C).
        tasks = [
            _task("A", priority="critical"),
            _task("B", priority="low", _running=True),
            _task("C", priority="high"),
        ]
        prefs = ViewPrefs(sort_key=SortKey.PRIORITY, sort_order=SortOrder.DESC)
        result = apply_view_prefs(tasks, prefs)
        assert result[0]["id"] == "B"  # running pinned first
        # The remaining order follows the descending-priority sort.
        assert [t["id"] for t in result[1:]] == ["A", "C"]

    def test_filter_then_sort_then_pin(self):
        today = date(2024, 6, 10)
        tasks = [
            _task("done", status="done", priority="high"),
            _task("hi", status="open", priority="high"),
            _task("lo", status="open", priority="low", _running=True),
        ]
        prefs = ViewPrefs(
            hide_completed=True,
            sort_key=SortKey.PRIORITY,
            sort_order=SortOrder.DESC,
        )
        result = apply_view_prefs(tasks, prefs, today=today)
        # "done" filtered out; running "lo" pinned first; then "hi".
        assert [t["id"] for t in result] == ["lo", "hi"]

    def test_default_prefs_only_pin_active(self):
        tasks = [_task("A"), _task("B", _running=True), _task("C")]
        result = apply_view_prefs(tasks, ViewPrefs())
        assert [t["id"] for t in result] == ["B", "A", "C"]


class TestViewPrefsIsDefault:
    """Tests for the ``is_default`` convenience predicate."""

    def test_fresh_prefs_are_default(self):
        assert ViewPrefs().is_default()

    def test_any_filter_is_not_default(self):
        assert not ViewPrefs(hide_completed=True).is_default()
        assert not ViewPrefs(due_filter=DueFilter.TODAY).is_default()
        assert not ViewPrefs(tag_filter="x").is_default()
        assert not ViewPrefs(priority_filter="high").is_default()
        assert not ViewPrefs(repo_filter=("web",)).is_default()

    def test_any_sort_is_not_default(self):
        assert not ViewPrefs(sort_key=SortKey.DUE).is_default()
        assert not ViewPrefs(sort_order=SortOrder.DESC).is_default()

    def test_default_repo_filter_is_empty_tuple(self):
        assert ViewPrefs().repo_filter == ()


class TestRepoFilter:
    """Tests for the repository filter helper and its composition."""

    def test_empty_repos_keeps_everything(self):
        tasks = [_task("A", _repo="web"), _task("B", _repo="api")]
        assert filter_by_repos(tasks, ()) == tasks

    def test_keeps_only_selected_repos(self):
        tasks = [
            _task("A", _repo="web"),
            _task("B", _repo="api"),
            _task("C", _repo="web"),
        ]
        result = filter_by_repos(tasks, ["web"])
        assert [t["id"] for t in result] == ["A", "C"]

    def test_multiple_selected_repos(self):
        tasks = [
            _task("A", _repo="web"),
            _task("B", _repo="api"),
            _task("C", _repo="docs"),
        ]
        result = filter_by_repos(tasks, ["web", "docs"])
        assert [t["id"] for t in result] == ["A", "C"]

    def test_case_sensitive_name_match(self):
        tasks = [_task("A", _repo="Web"), _task("B", _repo="web")]
        # Matching is case-sensitive on the repo name.
        assert [t["id"] for t in filter_by_repos(tasks, ["web"])] == ["B"]

    def test_untagged_task_dropped_when_filtering(self):
        tasks = [_task("A", _repo="web"), _task("B")]  # B has no _repo
        assert [t["id"] for t in filter_by_repos(tasks, ["web"])] == ["A"]

    def test_does_not_mutate_input(self):
        tasks = [_task("A", _repo="web"), _task("B", _repo="api")]
        filter_by_repos(tasks, ["web"])
        assert [t["id"] for t in tasks] == ["A", "B"]

    def test_apply_filters_applies_repo_filter(self):
        tasks = [
            _task("A", _repo="web"),
            _task("B", _repo="api"),
            _task("C", _repo="web"),
        ]
        prefs = ViewPrefs(repo_filter=("web",))
        assert [t["id"] for t in apply_filters(tasks, prefs)] == ["A", "C"]

    def test_apply_filters_empty_repo_filter_is_inert(self):
        tasks = [_task("A", _repo="web"), _task("B", _repo="api")]
        assert apply_filters(tasks, ViewPrefs()) == tasks

    def test_apply_view_prefs_filters_then_pins(self):
        tasks = [
            _task("A", _repo="web"),
            _task("B", _repo="api", _running=True),
            _task("C", _repo="web"),
        ]
        prefs = ViewPrefs(repo_filter=("web",))
        # api task is filtered out even though it is running.
        result = apply_view_prefs(tasks, prefs)
        assert [t["id"] for t in result] == ["A", "C"]


def test_week_window_handles_mid_week_today():
    # 2024-06-12 is a Wednesday; the window runs Wed..Sun (06-16).
    today = date(2024, 6, 12)
    tasks = [
        _task("A", due="2024-06-12"),
        _task("B", due="2024-06-16"),
        _task("C", due=(today + timedelta(days=5)).isoformat()),  # 06-17 Mon -> out
    ]
    result = filter_by_due(tasks, DueFilter.WEEK, today=today)
    assert [t["id"] for t in result] == ["A", "B"]
