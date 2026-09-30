"""Tests for the query module - TaskFilter and DisplayOptions dataclasses."""

from __future__ import annotations

import pytest

from doxtr_doto.query import DisplayOptions, TaskFilter


class TestTaskFilter:
    """Tests for TaskFilter dataclass."""

    def test_default_values(self) -> None:
        """TaskFilter should have sensible defaults for all fields."""
        f = TaskFilter()
        assert f.assignee == []
        assert f.priority == []
        assert f.status == []
        assert f.exclude_status == []
        assert f.tags == []
        assert f.depends_on == []
        assert f.due_before is None
        assert f.due_after is None
        assert f.regex is None

    def test_from_dict_empty(self) -> None:
        """from_dict should handle empty dictionary."""
        f = TaskFilter.from_dict({})
        assert f.assignee == []
        assert f.priority == []
        assert f.status == []
        assert f.due_before is None

    def test_from_dict_all_fields(self) -> None:
        """from_dict should populate all fields from dictionary."""
        d = {
            "assignee": ["alice", "bob"],
            "priority": ["high", "critical"],
            "status": ["open", "in-progress"],
            "exclude_status": ["done"],
            "tags": ["security", "urgent"],
            "depends_on": ["TASK-001"],
            "due_before": "2026-12-31",
            "due_after": "2026-01-01",
            "regex": "auth.*",
        }
        f = TaskFilter.from_dict(d)
        assert f.assignee == ["alice", "bob"]
        assert f.priority == ["high", "critical"]
        assert f.status == ["open", "in-progress"]
        assert f.exclude_status == ["done"]
        assert f.tags == ["security", "urgent"]
        assert f.depends_on == ["TASK-001"]
        assert f.due_before == "2026-12-31"
        assert f.due_after == "2026-01-01"
        assert f.regex == "auth.*"

    def test_from_dict_ignores_unknown_keys(self) -> None:
        """from_dict should ignore unknown dictionary keys."""
        d = {
            "assignee": ["alice"],
            "unknown_key": "should be ignored",
            "another_unknown": 42,
        }
        f = TaskFilter.from_dict(d)
        assert f.assignee == ["alice"]
        assert not hasattr(f, "unknown_key")

    def test_to_dict_omits_empty_values(self) -> None:
        """to_dict should not include empty lists or None values."""
        f = TaskFilter(assignee=["alice"], priority=[])
        d = f.to_dict()
        assert d == {"assignee": ["alice"]}
        assert "priority" not in d
        assert "due_before" not in d

    def test_to_dict_includes_all_set_values(self) -> None:
        """to_dict should include all non-empty values."""
        f = TaskFilter(
            assignee=["alice"],
            priority=["high"],
            due_before="2026-12-31",
            regex="test",
        )
        d = f.to_dict()
        assert d == {
            "assignee": ["alice"],
            "priority": ["high"],
            "due_before": "2026-12-31",
            "regex": "test",
        }

    def test_roundtrip_from_dict_to_dict(self) -> None:
        """from_dict -> to_dict should preserve values."""
        original = {
            "assignee": ["alice"],
            "priority": ["high"],
            "status": ["open"],
            "tags": ["important"],
        }
        f = TaskFilter.from_dict(original)
        result = f.to_dict()
        assert result == original

    def test_is_empty_true_for_default(self) -> None:
        """is_empty should return True for default TaskFilter."""
        f = TaskFilter()
        assert f.is_empty() is True

    def test_is_empty_false_when_any_field_set(self) -> None:
        """is_empty should return False if any field is set."""
        assert TaskFilter(assignee=["alice"]).is_empty() is False
        assert TaskFilter(priority=["high"]).is_empty() is False
        assert TaskFilter(due_before="2026-12-31").is_empty() is False
        assert TaskFilter(regex="test").is_empty() is False

    def test_direct_instantiation_with_kwargs(self) -> None:
        """TaskFilter can be instantiated directly with keyword arguments."""
        f = TaskFilter(
            assignee=["alice"],
            priority=["high", "critical"],
            status=["open"],
        )
        assert f.assignee == ["alice"]
        assert f.priority == ["high", "critical"]
        assert f.status == ["open"]


class TestDisplayOptions:
    """Tests for DisplayOptions dataclass."""

    def test_default_values(self) -> None:
        """DisplayOptions should have sensible defaults."""
        d = DisplayOptions()
        assert d.format == "list"
        assert d.sort == ["priority"]
        assert d.order == "desc"
        assert d.limit is None
        assert d.show_archived is False
        assert d.columns == ["id", "title", "priority", "status"]

    def test_from_dict_empty(self) -> None:
        """from_dict should use defaults for empty dictionary."""
        d = DisplayOptions.from_dict({})
        assert d.format == "list"
        assert d.sort == ["priority"]
        assert d.order == "desc"
        assert d.limit is None
        assert d.show_archived is False

    def test_from_dict_all_fields(self) -> None:
        """from_dict should populate all fields from dictionary."""
        data = {
            "format": "table",
            "sort": ["due", "priority"],
            "order": "asc",
            "limit": 10,
            "show_archived": True,
            "columns": ["id", "title", "due", "assignee"],
        }
        d = DisplayOptions.from_dict(data)
        assert d.format == "table"
        assert d.sort == ["due", "priority"]
        assert d.order == "asc"
        assert d.limit == 10
        assert d.show_archived is True
        assert d.columns == ["id", "title", "due", "assignee"]

    def test_from_dict_ignores_unknown_keys(self) -> None:
        """from_dict should ignore unknown dictionary keys."""
        data = {
            "format": "cards",
            "unknown_key": "ignored",
        }
        d = DisplayOptions.from_dict(data)
        assert d.format == "cards"
        assert not hasattr(d, "unknown_key")

    def test_to_dict_includes_all_values(self) -> None:
        """to_dict should include all fields, even defaults."""
        d = DisplayOptions()
        result = d.to_dict()
        assert result == {
            "format": "list",
            "sort": ["priority"],
            "order": "desc",
            "limit": None,
            "show_archived": False,
            "columns": ["id", "title", "priority", "status"],
        }

    def test_roundtrip_from_dict_to_dict(self) -> None:
        """from_dict -> to_dict should preserve all values."""
        original = {
            "format": "table",
            "sort": ["due"],
            "order": "asc",
            "limit": 5,
            "show_archived": True,
            "columns": ["id", "title"],
        }
        d = DisplayOptions.from_dict(original)
        result = d.to_dict()
        assert result == original

    def test_direct_instantiation_with_kwargs(self) -> None:
        """DisplayOptions can be instantiated directly with keyword arguments."""
        d = DisplayOptions(
            format="cards",
            sort=["created"],
            order="asc",
            limit=20,
        )
        assert d.format == "cards"
        assert d.sort == ["created"]
        assert d.order == "asc"
        assert d.limit == 20


class TestFilterTasksIntegration:
    """Integration tests for filter_tasks with typed objects."""

    def test_filter_tasks_accepts_task_filter_object(self) -> None:
        """filter_tasks should accept TaskFilter object directly."""
        from doxtr_doto.collectors import DotoTask, filter_tasks

        tasks = {
            "TASK-001": DotoTask(
                id="TASK-001",
                title="Task 1",
                assignee="alice",
                priority="high",
                status="open",
            ),
            "TASK-002": DotoTask(
                id="TASK-002",
                title="Task 2",
                assignee="bob",
                priority="medium",
                status="done",
            ),
        }

        f = TaskFilter(assignee=["alice"])
        result = filter_tasks(tasks, f)
        assert len(result) == 1
        assert result[0].id == "TASK-001"

    def test_filter_tasks_accepts_dict_for_backward_compatibility(self) -> None:
        """filter_tasks should still accept dict filters for backward compatibility."""
        from doxtr_doto.collectors import DotoTask, filter_tasks

        tasks = {
            "TASK-001": DotoTask(
                id="TASK-001",
                title="Task 1",
                priority="high",
                status="open",
            ),
            "TASK-002": DotoTask(
                id="TASK-002",
                title="Task 2",
                priority="low",
                status="open",
            ),
        }

        # Using dict (old style)
        result = filter_tasks(tasks, {"priority": ["high"]})
        assert len(result) == 1
        assert result[0].id == "TASK-001"

    def test_filter_tasks_accepts_display_options_object(self) -> None:
        """filter_tasks should accept DisplayOptions object."""
        from doxtr_doto.collectors import DotoTask, filter_tasks

        tasks = {
            "TASK-001": DotoTask(
                id="TASK-001",
                title="Task 1",
                priority="high",
                status="open",
            ),
            "TASK-002": DotoTask(
                id="TASK-002",
                title="Task 2",
                priority="medium",
                status="open",
            ),
            "TASK-003": DotoTask(
                id="TASK-003",
                title="Task 3",
                priority="low",
                status="open",
            ),
        }

        f = TaskFilter()
        d = DisplayOptions(sort=["priority"], order="desc", limit=2)
        result = filter_tasks(tasks, f, d)
        assert len(result) == 2
        # High priority should come first in desc order
        assert result[0].priority == "high"

    def test_filter_tasks_with_mixed_inputs(self) -> None:
        """filter_tasks should work with TaskFilter object and dict display."""
        from doxtr_doto.collectors import DotoTask, filter_tasks

        tasks = {
            "TASK-001": DotoTask(
                id="TASK-001",
                title="Task 1",
                status="open",
            ),
            "TASK-002": DotoTask(
                id="TASK-002",
                title="Task 2",
                status="done",
            ),
        }

        f = TaskFilter(status=["open"])
        # Display as dict (backward compatibility)
        result = filter_tasks(tasks, f, {"limit": 10})
        assert len(result) == 1
        assert result[0].status == "open"

    def test_filter_tasks_status_filter(self) -> None:
        """filter_tasks should filter by status correctly."""
        from doxtr_doto.collectors import DotoTask, filter_tasks

        tasks = {
            "TASK-001": DotoTask(id="TASK-001", title="T1", status="open"),
            "TASK-002": DotoTask(id="TASK-002", title="T2", status="in-progress"),
            "TASK-003": DotoTask(id="TASK-003", title="T3", status="done"),
        }

        f = TaskFilter(status=["open", "in-progress"])
        result = filter_tasks(tasks, f)
        assert len(result) == 2
        assert {t.status for t in result} == {"open", "in-progress"}

    def test_filter_tasks_exclude_status(self) -> None:
        """filter_tasks should exclude by status correctly."""
        from doxtr_doto.collectors import DotoTask, filter_tasks

        tasks = {
            "TASK-001": DotoTask(id="TASK-001", title="T1", status="open"),
            "TASK-002": DotoTask(id="TASK-002", title="T2", status="done"),
        }

        f = TaskFilter(exclude_status=["done"])
        result = filter_tasks(tasks, f)
        assert len(result) == 1
        assert result[0].status == "open"

    def test_filter_tasks_by_tags(self) -> None:
        """filter_tasks should filter by tags (OR semantics)."""
        from doxtr_doto.collectors import DotoTask, filter_tasks

        tasks = {
            "TASK-001": DotoTask(id="TASK-001", title="T1", tags=["security", "backend"]),
            "TASK-002": DotoTask(id="TASK-002", title="T2", tags=["frontend"]),
            "TASK-003": DotoTask(id="TASK-003", title="T3", tags=["security"]),
        }

        f = TaskFilter(tags=["security"])
        result = filter_tasks(tasks, f)
        assert len(result) == 2
        assert {t.id for t in result} == {"TASK-001", "TASK-003"}

    def test_filter_tasks_by_regex(self) -> None:
        """filter_tasks should filter by regex on title."""
        from doxtr_doto.collectors import DotoTask, filter_tasks

        tasks = {
            "TASK-001": DotoTask(id="TASK-001", title="Implement authentication"),
            "TASK-002": DotoTask(id="TASK-002", title="Fix database bug"),
            "TASK-003": DotoTask(id="TASK-003", title="Add auth logging"),
        }

        f = TaskFilter(regex="auth")
        result = filter_tasks(tasks, f)
        assert len(result) == 2
        assert {t.id for t in result} == {"TASK-001", "TASK-003"}

    def test_filter_tasks_by_due_date_range(self) -> None:
        """filter_tasks should filter by due date range."""
        from doxtr_doto.collectors import DotoTask, filter_tasks

        tasks = {
            "TASK-001": DotoTask(id="TASK-001", title="T1", due="2026-06-01"),
            "TASK-002": DotoTask(id="TASK-002", title="T2", due="2026-07-15"),
            "TASK-003": DotoTask(id="TASK-003", title="T3", due="2026-08-30"),
        }

        f = TaskFilter(due_after="2026-06-01", due_before="2026-08-01")
        result = filter_tasks(tasks, f)
        assert len(result) == 1
        assert result[0].id == "TASK-002"

    def test_display_options_limit(self) -> None:
        """DisplayOptions limit should restrict result count."""
        from doxtr_doto.collectors import DotoTask, filter_tasks

        tasks = {
            f"TASK-{i:03d}": DotoTask(id=f"TASK-{i:03d}", title=f"Task {i}")
            for i in range(1, 11)
        }

        f = TaskFilter()
        d = DisplayOptions(limit=3)
        result = filter_tasks(tasks, f, d)
        assert len(result) == 3

    def test_display_options_show_archived(self) -> None:
        """DisplayOptions show_archived should control archived task visibility."""
        from doxtr_doto.collectors import DotoTask, filter_tasks

        tasks = {
            "TASK-001": DotoTask(id="TASK-001", title="T1", archived=False),
            "TASK-002": DotoTask(id="TASK-002", title="T2", archived=True),
        }

        # Without show_archived
        f = TaskFilter()
        d = DisplayOptions(show_archived=False)
        result = filter_tasks(tasks, f, d)
        assert len(result) == 1
        assert result[0].id == "TASK-001"

        # With show_archived
        d = DisplayOptions(show_archived=True)
        result = filter_tasks(tasks, f, d)
        assert len(result) == 2

    def test_filter_tasks_by_depends_on(self) -> None:
        """filter_tasks should filter by depends_on field."""
        from doxtr_doto.collectors import DotoTask, filter_tasks

        tasks = {
            "TASK-001": DotoTask(id="TASK-001", title="Base task", depends_on=[]),
            "TASK-002": DotoTask(id="TASK-002", title="Depends on 001", depends_on=["TASK-001"]),
            "TASK-003": DotoTask(id="TASK-003", title="Depends on 001 and 002", depends_on=["TASK-001", "TASK-002"]),
            "TASK-004": DotoTask(id="TASK-004", title="Independent", depends_on=[]),
        }

        f = TaskFilter(depends_on=["TASK-001"])
        result = filter_tasks(tasks, f)
        assert len(result) == 2
        assert {t.id for t in result} == {"TASK-002", "TASK-003"}

    def test_display_options_sort_order_asc(self) -> None:
        """DisplayOptions order='asc' should sort in ascending order."""
        from doxtr_doto.collectors import DotoTask, filter_tasks

        tasks = {
            "TASK-001": DotoTask(id="TASK-001", title="T1", priority="high"),
            "TASK-002": DotoTask(id="TASK-002", title="T2", priority="low"),
            "TASK-003": DotoTask(id="TASK-003", title="T3", priority="critical"),
        }

        f = TaskFilter()
        d = DisplayOptions(sort=["priority"], order="asc")
        result = filter_tasks(tasks, f, d)
        # Ascending order: low -> medium -> high -> critical
        assert result[0].priority == "low"
        assert result[-1].priority == "critical"

    def test_filter_tasks_case_insensitive_matching(self) -> None:
        """filter_tasks should match filters case-insensitively."""
        from doxtr_doto.collectors import DotoTask, filter_tasks

        tasks = {
            "TASK-001": DotoTask(id="TASK-001", title="T1", status="Open", priority="High", assignee="Alice"),
            "TASK-002": DotoTask(id="TASK-002", title="T2", status="DONE", priority="LOW", assignee="BOB"),
        }

        # Filter with lowercase should match mixed-case values
        f = TaskFilter(status=["open"])
        result = filter_tasks(tasks, f)
        assert len(result) == 1
        assert result[0].id == "TASK-001"

        # Filter with uppercase should also match
        f = TaskFilter(priority=["HIGH"])
        result = filter_tasks(tasks, f)
        assert len(result) == 1
        assert result[0].id == "TASK-001"

        # Assignee filter case-insensitive
        f = TaskFilter(assignee=["alice"])
        result = filter_tasks(tasks, f)
        assert len(result) == 1
        assert result[0].id == "TASK-001"

    def test_filter_tasks_empty_tasks_dict(self) -> None:
        """filter_tasks should handle empty tasks dict gracefully."""
        from doxtr_doto.collectors import filter_tasks

        tasks: dict = {}
        f = TaskFilter(status=["open"])
        result = filter_tasks(tasks, f)
        assert result == []

        # Also with display options
        d = DisplayOptions(limit=10)
        result = filter_tasks(tasks, f, d)
        assert result == []
