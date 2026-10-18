"""Tests for filter_tasks caching functionality.

This module tests the caching layer added to filter_tasks() to improve
performance when the same filter/display options are used multiple times
during a single build.
"""

from __future__ import annotations

import re
from unittest.mock import patch

import pytest

from doxtr_doto.collectors import (
    DotoTask,
    _filter_cache,
    _make_filter_cache_key,
    filter_tasks,
    invalidate_filter_cache,
)
from doxtr_doto.query import DisplayOptions, TaskFilter


@pytest.fixture
def sample_tasks() -> dict[str, DotoTask]:
    """Create a sample set of tasks for testing."""
    return {
        "TASK-001": DotoTask(
            id="TASK-001",
            title="First task",
            assignee="alice",
            priority="high",
            status="open",
            due="2025-06-15",
            tags=["backend", "urgent"],
        ),
        "TASK-002": DotoTask(
            id="TASK-002",
            title="Second task",
            assignee="bob",
            priority="medium",
            status="in-progress",
            due="2025-06-20",
            tags=["frontend"],
        ),
        "TASK-003": DotoTask(
            id="TASK-003",
            title="Third task",
            assignee="alice",
            priority="low",
            status="done",
            due="2025-06-10",
            tags=["backend"],
        ),
        "TASK-004": DotoTask(
            id="TASK-004",
            title="Fourth task",
            assignee="charlie",
            priority="critical",
            status="blocked",
            due="2025-06-25",
            tags=["security"],
            archived=True,
        ),
    }


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the filter cache before and after each test."""
    invalidate_filter_cache()
    yield
    invalidate_filter_cache()


class TestFilterCacheKey:
    """Tests for _make_filter_cache_key function."""

    def test_cache_key_is_hashable(self, sample_tasks: dict[str, DotoTask]):
        """Cache key should be hashable (usable as dict key)."""
        filters = TaskFilter(assignee=["alice"])
        display = DisplayOptions()
        key = _make_filter_cache_key(id(sample_tasks), filters, display)

        # Should be able to use as dict key
        cache = {}
        cache[key] = "test_value"
        assert cache[key] == "test_value"

    def test_cache_key_includes_all_filter_fields(self, sample_tasks: dict[str, DotoTask]):
        """Cache key should incorporate all filter fields."""
        filters1 = TaskFilter(assignee=["alice"])
        filters2 = TaskFilter(assignee=["bob"])
        display = DisplayOptions()

        key1 = _make_filter_cache_key(id(sample_tasks), filters1, display)
        key2 = _make_filter_cache_key(id(sample_tasks), filters2, display)

        assert key1 != key2

    def test_cache_key_includes_all_display_fields(self, sample_tasks: dict[str, DotoTask]):
        """Cache key should incorporate all display fields."""
        filters = TaskFilter()
        display1 = DisplayOptions(limit=5)
        display2 = DisplayOptions(limit=10)

        key1 = _make_filter_cache_key(id(sample_tasks), filters, display1)
        key2 = _make_filter_cache_key(id(sample_tasks), filters, display2)

        assert key1 != key2

    def test_cache_key_different_for_different_task_dicts(self, sample_tasks: dict[str, DotoTask]):
        """Cache key should be different for different task dictionaries."""
        other_tasks = {"TASK-005": DotoTask(id="TASK-005", title="Other")}
        filters = TaskFilter()
        display = DisplayOptions()

        key1 = _make_filter_cache_key(id(sample_tasks), filters, display)
        key2 = _make_filter_cache_key(id(other_tasks), filters, display)

        assert key1 != key2

    def test_cache_key_same_for_equivalent_filters(self, sample_tasks: dict[str, DotoTask]):
        """Cache key should be the same for equivalent filter configurations."""
        # Different order of list elements should produce same key (sorted)
        filters1 = TaskFilter(assignee=["alice", "bob"])
        filters2 = TaskFilter(assignee=["bob", "alice"])
        display = DisplayOptions()

        key1 = _make_filter_cache_key(id(sample_tasks), filters1, display)
        key2 = _make_filter_cache_key(id(sample_tasks), filters2, display)

        assert key1 == key2

    def test_cache_key_includes_regex(self, sample_tasks: dict[str, DotoTask]):
        """Cache key should include regex pattern."""
        filters1 = TaskFilter(regex="test.*")
        filters2 = TaskFilter(regex="other.*")
        display = DisplayOptions()

        key1 = _make_filter_cache_key(id(sample_tasks), filters1, display)
        key2 = _make_filter_cache_key(id(sample_tasks), filters2, display)

        assert key1 != key2

    def test_cache_key_includes_date_filters(self, sample_tasks: dict[str, DotoTask]):
        """Cache key should include date filter values."""
        filters1 = TaskFilter(due_before="2025-06-15")
        filters2 = TaskFilter(due_before="2025-06-20")
        display = DisplayOptions()

        key1 = _make_filter_cache_key(id(sample_tasks), filters1, display)
        key2 = _make_filter_cache_key(id(sample_tasks), filters2, display)

        assert key1 != key2


class TestFilterCache:
    """Tests for filter_tasks caching behavior."""

    def test_second_call_with_same_args_returns_cached_result(
        self, sample_tasks: dict[str, DotoTask]
    ):
        """Second call with same arguments should return cached result."""
        filters = TaskFilter(assignee=["alice"])
        display = DisplayOptions()

        # First call
        result1 = filter_tasks(sample_tasks, filters, display)

        # Second call should return same object (cached)
        result2 = filter_tasks(sample_tasks, filters, display)

        assert result1 is result2  # Same object, not just equal

    def test_different_filters_produce_different_cache_entries(
        self, sample_tasks: dict[str, DotoTask]
    ):
        """Different filter configurations should not share cache entries."""
        filters1 = TaskFilter(assignee=["alice"])
        filters2 = TaskFilter(assignee=["bob"])
        display = DisplayOptions()

        result1 = filter_tasks(sample_tasks, filters1, display)
        result2 = filter_tasks(sample_tasks, filters2, display)

        assert result1 is not result2
        assert len(result1) == 2  # alice has 2 tasks
        assert len(result2) == 1  # bob has 1 task

    def test_cache_invalidation_clears_all_entries(self, sample_tasks: dict[str, DotoTask]):
        """invalidate_filter_cache should clear all cached results."""
        filters = TaskFilter(assignee=["alice"])
        display = DisplayOptions()

        # First call - populate cache
        result1 = filter_tasks(sample_tasks, filters, display)

        # Invalidate cache
        invalidate_filter_cache()

        # Second call - should recompute (different object)
        result2 = filter_tasks(sample_tasks, filters, display)

        # Results should be equal but not the same object
        assert result1 == result2
        assert result1 is not result2

    def test_cache_works_with_dict_filters(self, sample_tasks: dict[str, DotoTask]):
        """Caching should work when filters are passed as dict."""
        filters_dict = {"assignee": ["alice"], "status": ["open"]}
        display = DisplayOptions()

        result1 = filter_tasks(sample_tasks, filters_dict, display)
        result2 = filter_tasks(sample_tasks, filters_dict, display)

        # Both should return same cached result
        assert result1 is result2

    def test_cache_works_with_dict_display(self, sample_tasks: dict[str, DotoTask]):
        """Caching should work when display is passed as dict."""
        filters = TaskFilter()
        display_dict = {"limit": 2, "sort": ["priority"], "order": "desc"}

        result1 = filter_tasks(sample_tasks, filters, display_dict)
        result2 = filter_tasks(sample_tasks, filters, display_dict)

        assert result1 is result2

    def test_cache_works_with_precompiled_regex(self, sample_tasks: dict[str, DotoTask]):
        """Caching should work when regex_compiled is provided."""
        compiled = re.compile("first", re.IGNORECASE)
        filters_dict = {
            "regex": "first",
            "regex_compiled": compiled,
        }

        result1 = filter_tasks(sample_tasks, filters_dict)
        result2 = filter_tasks(sample_tasks, filters_dict)

        assert result1 is result2
        assert len(result1) == 1
        assert result1[0].id == "TASK-001"

    def test_precompiled_regex_used_for_filtering(self, sample_tasks: dict[str, DotoTask]):
        """Pre-compiled regex should be used instead of recompiling."""
        compiled = re.compile("second", re.IGNORECASE)
        filters_dict = {
            "regex": "second",
            "regex_compiled": compiled,
        }

        result = filter_tasks(sample_tasks, filters_dict)

        assert len(result) == 1
        assert result[0].id == "TASK-002"

    def test_cache_respects_show_archived_option(self, sample_tasks: dict[str, DotoTask]):
        """Different show_archived values should have separate cache entries."""
        filters = TaskFilter()
        display1 = DisplayOptions(show_archived=False)
        display2 = DisplayOptions(show_archived=True)

        result1 = filter_tasks(sample_tasks, filters, display1)
        result2 = filter_tasks(sample_tasks, filters, display2)

        assert result1 is not result2
        assert len(result1) == 3  # 3 non-archived tasks
        assert len(result2) == 4  # All 4 tasks

    def test_cache_is_module_level(self):
        """Filter cache should be a module-level dict."""
        assert isinstance(_filter_cache, dict)

    def test_invalidate_clears_module_cache(self, sample_tasks: dict[str, DotoTask]):
        """invalidate_filter_cache should clear the module-level cache."""
        # Populate cache
        filter_tasks(sample_tasks, TaskFilter())
        assert len(_filter_cache) > 0

        # Invalidate
        invalidate_filter_cache()

        assert len(_filter_cache) == 0


class TestCacheInvalidationIntegration:
    """Tests for cache invalidation in collector methods."""

    def test_cache_used_across_multiple_calls(self, sample_tasks: dict[str, DotoTask]):
        """Multiple filter_tasks calls should benefit from caching."""
        filters = TaskFilter(status=["open"])
        display = DisplayOptions()

        # Simulate multiple doto-list directives with same config
        results = []
        for _ in range(5):
            results.append(filter_tasks(sample_tasks, filters, display))

        # All should be the same cached object
        assert all(r is results[0] for r in results)

    def test_different_sort_orders_cached_separately(self, sample_tasks: dict[str, DotoTask]):
        """Different sort orders should have separate cache entries."""
        filters = TaskFilter()
        display_asc = DisplayOptions(sort=["priority"], order="asc")
        display_desc = DisplayOptions(sort=["priority"], order="desc")

        result_asc = filter_tasks(sample_tasks, filters, display_asc)
        result_desc = filter_tasks(sample_tasks, filters, display_desc)

        assert result_asc is not result_desc
        # Verify order is actually different
        if len(result_asc) > 1 and len(result_desc) > 1:
            assert result_asc[0].id != result_desc[0].id

    def test_different_columns_cached_separately(self, sample_tasks: dict[str, DotoTask]):
        """Different column configurations should have separate cache entries."""
        filters = TaskFilter()
        display1 = DisplayOptions(columns=["id", "title"])
        display2 = DisplayOptions(columns=["id", "title", "status"])

        result1 = filter_tasks(sample_tasks, filters, display1)
        result2 = filter_tasks(sample_tasks, filters, display2)

        assert result1 is not result2


class TestCachePerformance:
    """Tests verifying performance benefits of caching."""

    def test_cache_avoids_repeated_filtering(self, sample_tasks: dict[str, DotoTask]):
        """Caching should avoid repeated filtering work."""
        filters = TaskFilter(priority=["high", "critical"])
        display = DisplayOptions()

        with patch(
            "doxtr_doto.collectors._filter_tasks_impl",
            wraps=__import__(
                "doxtr_doto.collectors", fromlist=["_filter_tasks_impl"]
            )._filter_tasks_impl,
        ) as mock_impl:
            # First call - should call implementation
            filter_tasks(sample_tasks, filters, display)
            first_call_count = mock_impl.call_count

            # Second call - should use cache
            filter_tasks(sample_tasks, filters, display)
            second_call_count = mock_impl.call_count

            # Third call - should use cache
            filter_tasks(sample_tasks, filters, display)
            third_call_count = mock_impl.call_count

            # Implementation should only be called once
            assert first_call_count == 1
            assert second_call_count == 1
            assert third_call_count == 1

    def test_regex_not_recompiled_when_precompiled_provided(
        self, sample_tasks: dict[str, DotoTask]
    ):
        """Pre-compiled regex should prevent recompilation."""
        # Clear cache to ensure fresh call
        invalidate_filter_cache()

        compiled = re.compile("task", re.IGNORECASE)
        filters_dict = {
            "regex": "task",
            "regex_compiled": compiled,
        }

        with patch("re.compile") as mock_compile:
            filter_tasks(sample_tasks, filters_dict)
            # re.compile should not be called since we provided compiled
            mock_compile.assert_not_called()


class TestEdgeCases:
    """Tests for edge cases in caching."""

    def test_empty_tasks_dict_cached(self):
        """Empty tasks dictionary should still be cached."""
        empty_tasks: dict[str, DotoTask] = {}
        filters = TaskFilter()
        display = DisplayOptions()

        result1 = filter_tasks(empty_tasks, filters, display)
        result2 = filter_tasks(empty_tasks, filters, display)

        assert result1 is result2
        assert result1 == []

    def test_none_display_normalized_for_caching(self, sample_tasks: dict[str, DotoTask]):
        """None display should be normalized to default for caching."""
        filters = TaskFilter()

        result1 = filter_tasks(sample_tasks, filters, None)
        result2 = filter_tasks(sample_tasks, filters, DisplayOptions())

        # Should be same cached result since None normalizes to default
        assert result1 is result2

    def test_cache_with_all_filter_types(self, sample_tasks: dict[str, DotoTask]):
        """Cache should work with all filter types combined."""
        filters = TaskFilter(
            assignee=["alice"],
            priority=["high"],
            status=["open"],
            exclude_status=["done"],
            tags=["backend"],
            due_before="2025-12-31",
            due_after="2025-01-01",
            regex="first",
        )
        display = DisplayOptions(
            format="table",
            sort=["priority", "due"],
            order="desc",
            limit=10,
            show_archived=False,
            columns=["id", "title", "status"],
        )

        result1 = filter_tasks(sample_tasks, filters, display)
        result2 = filter_tasks(sample_tasks, filters, display)

        assert result1 is result2

    def test_invalid_regex_handled_gracefully(self, sample_tasks: dict[str, DotoTask]):
        """Invalid regex pattern should not crash, just skip regex filtering."""
        filters_dict = {
            "regex": "[invalid(",  # Invalid regex
        }

        # Should not raise, just skip regex filtering
        result = filter_tasks(sample_tasks, filters_dict)

        # Should return all non-archived tasks
        assert len(result) == 3


class TestEstimateSort:
    """Sorting by the estimate field must be numeric, not lexicographic."""

    def _tasks(self) -> dict[str, DotoTask]:
        return {
            "A": DotoTask(id="A", title="a", estimate=90),
            "B": DotoTask(id="B", title="b", estimate=120),
            "C": DotoTask(id="C", title="c", estimate=5),
            "D": DotoTask(id="D", title="d", estimate=None),
        }

    def test_sort_estimate_ascending_is_numeric(self):
        invalidate_filter_cache()
        display = DisplayOptions.from_dict({"sort": ["estimate"], "order": "asc"})
        result = filter_tasks(self._tasks(), {}, display)
        ids = [t.id for t in result]
        # 5 < 90 < 120, then None (no estimate) sorts last.
        assert ids == ["C", "A", "B", "D"]

    def test_sort_estimate_descending(self):
        invalidate_filter_cache()
        display = DisplayOptions.from_dict({"sort": ["estimate"], "order": "desc"})
        result = filter_tasks(self._tasks(), {}, display)
        ids = [t.id for t in result]
        # 120 > 90 > 5, None sorts last under desc too.
        assert ids[:3] == ["B", "A", "C"]
        assert ids[3] == "D"


class TestCliEstimateSort:
    """The CLI list sort_key must compare estimate numerically."""

    def test_cli_sort_estimate_numeric(self):
        from doxtr_doto.cli.commands.list import sort_tasks

        tasks = [
            {"id": "A", "estimate": 90},
            {"id": "B", "estimate": 120},
            {"id": "C", "estimate": 5},
            {"id": "D", "estimate": None},
        ]
        result = sort_tasks(tasks, ["estimate"], reverse=False)
        ids = [t["id"] for t in result]
        # Numeric: 5 < 90 < 120; a lexicographic bug would give "120" < "90".
        assert ids == ["C", "A", "B", "D"]
