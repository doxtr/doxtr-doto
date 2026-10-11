"""Tests for sync/conflict.py - conflict detection and formatting."""

from __future__ import annotations

import pytest

from doxtr_doto.sync.conflict import (
    ConflictError,
    FieldConflict,
    _format_value,
    format_conflict_error,
)


class TestFieldConflict:
    """Tests for FieldConflict dataclass."""

    def test_field_conflict_creation(self):
        """FieldConflict can be created with all fields."""
        conflict = FieldConflict(
            field="priority",
            base="medium",
            rst="high",
            json="low",
            rst_file="tasks.rst",
            task_id="TASK-001",
        )
        assert conflict.field == "priority"
        assert conflict.base == "medium"
        assert conflict.rst == "high"
        assert conflict.json == "low"
        assert conflict.rst_file == "tasks.rst"
        assert conflict.task_id == "TASK-001"

    def test_field_conflict_with_none_values(self):
        """FieldConflict handles None values."""
        conflict = FieldConflict(
            field="assignee",
            base=None,
            rst="alice",
            json=None,
            rst_file="tasks.rst",
            task_id="TASK-001",
        )
        assert conflict.base is None
        assert conflict.json is None

    def test_field_conflict_with_list_values(self):
        """FieldConflict handles list values."""
        conflict = FieldConflict(
            field="tags",
            base=["tag1"],
            rst=["tag1", "tag2"],
            json=["tag1", "tag3"],
            rst_file="tasks.rst",
            task_id="TASK-001",
        )
        assert conflict.base == ["tag1"]
        assert conflict.rst == ["tag1", "tag2"]
        assert conflict.json == ["tag1", "tag3"]


class TestFormatValue:
    """Tests for _format_value helper."""

    def test_format_none_value(self):
        """None is formatted as '(not set)'."""
        assert _format_value(None) == "(not set)"

    def test_format_empty_list(self):
        """Empty list is formatted as '(empty list)'."""
        assert _format_value([]) == "(empty list)"

    def test_format_list_with_items(self):
        """List with items is formatted as comma-separated."""
        assert _format_value(["a", "b", "c"]) == "a, b, c"

    def test_format_single_item_list(self):
        """Single-item list is formatted without comma."""
        assert _format_value(["only"]) == "only"

    def test_format_string(self):
        """String is returned as-is."""
        assert _format_value("high") == "high"

    def test_format_integer(self):
        """Integer is converted to string."""
        assert _format_value(42) == "42"


class TestFormatConflictError:
    """Tests for format_conflict_error function."""

    def test_empty_conflicts_returns_no_conflicts_message(self):
        """Empty conflict list returns a 'no conflicts' message."""
        result = format_conflict_error([])
        assert "No conflicts detected" in result

    def test_single_conflict_formatting(self):
        """Single conflict is formatted with all details."""
        conflicts = [
            FieldConflict(
                field="priority",
                base="medium",
                rst="high",
                json="low",
                rst_file="features/auth.rst",
                task_id="TASK-001",
            )
        ]
        result = format_conflict_error(conflicts)

        assert "TASK-001" in result
        assert "priority" in result
        assert "medium" in result
        assert "high" in result
        assert "low" in result
        assert "features/auth.rst" in result
        assert "Resolution options" in result

    def test_multiple_conflicts_same_task(self):
        """Multiple conflicts for same task are grouped."""
        conflicts = [
            FieldConflict(
                field="priority",
                base="medium",
                rst="high",
                json="low",
                rst_file="tasks.rst",
                task_id="TASK-001",
            ),
            FieldConflict(
                field="assignee",
                base="alice",
                rst="bob",
                json="charlie",
                rst_file="tasks.rst",
                task_id="TASK-001",
            ),
        ]
        result = format_conflict_error(conflicts)

        # Task ID should appear once (grouped)
        assert result.count("Task TASK-001:") == 1
        # Both fields should be mentioned
        assert "priority" in result
        assert "assignee" in result

    def test_multiple_conflicts_different_tasks(self):
        """Multiple conflicts from different tasks are separated."""
        conflicts = [
            FieldConflict(
                field="priority",
                base="medium",
                rst="high",
                json="low",
                rst_file="tasks.rst",
                task_id="TASK-001",
            ),
            FieldConflict(
                field="status",
                base="open",
                rst="done",
                json="in-progress",
                rst_file="features.rst",
                task_id="TASK-002",
            ),
        ]
        result = format_conflict_error(conflicts)

        assert "TASK-001" in result
        assert "TASK-002" in result
        assert "priority" in result
        assert "status" in result

    def test_resolution_commands_shown_for_single_task(self):
        """Resolution commands include task ID for single task."""
        conflicts = [
            FieldConflict(
                field="priority",
                base="medium",
                rst="high",
                json="low",
                rst_file="tasks.rst",
                task_id="TASK-001",
            )
        ]
        result = format_conflict_error(conflicts)

        assert "doto resolve TASK-001 --use-rst" in result
        assert "doto resolve TASK-001 --use-json" in result

    def test_resolution_commands_generic_for_multiple_tasks(self):
        """Resolution commands use <task-id> placeholder for multiple tasks."""
        conflicts = [
            FieldConflict(
                field="priority",
                base="medium",
                rst="high",
                json="low",
                rst_file="tasks.rst",
                task_id="TASK-001",
            ),
            FieldConflict(
                field="status",
                base="open",
                rst="done",
                json="in-progress",
                rst_file="features.rst",
                task_id="TASK-002",
            ),
        ]
        result = format_conflict_error(conflicts)

        assert "doto resolve <task-id> --use-rst" in result
        assert "doto resolve <task-id> --use-json" in result

    def test_error_header_present(self):
        """Error message has appropriate header."""
        conflicts = [
            FieldConflict(
                field="priority",
                base="medium",
                rst="high",
                json="low",
                rst_file="tasks.rst",
                task_id="TASK-001",
            )
        ]
        result = format_conflict_error(conflicts)

        assert "ERROR" in result
        assert "conflicts detected" in result.lower()

    def test_conflict_with_none_base(self):
        """Conflict with None base value is formatted correctly."""
        conflicts = [
            FieldConflict(
                field="assignee",
                base=None,
                rst="alice",
                json="bob",
                rst_file="tasks.rst",
                task_id="TASK-001",
            )
        ]
        result = format_conflict_error(conflicts)

        assert "(not set)" in result

    def test_conflict_with_list_values(self):
        """Conflict with list values is formatted correctly."""
        conflicts = [
            FieldConflict(
                field="tags",
                base=["bug"],
                rst=["bug", "critical"],
                json=["bug", "feature"],
                rst_file="tasks.rst",
                task_id="TASK-001",
            )
        ]
        result = format_conflict_error(conflicts)

        assert "bug" in result
        assert "critical" in result
        assert "feature" in result


class TestConflictError:
    """Tests for ConflictError exception."""

    def test_conflict_error_creation(self):
        """ConflictError can be created with conflicts."""
        conflicts = [
            FieldConflict(
                field="priority",
                base="medium",
                rst="high",
                json="low",
                rst_file="tasks.rst",
                task_id="TASK-001",
            )
        ]
        error = ConflictError(conflicts)

        assert error.conflicts == conflicts
        assert "TASK-001" in str(error)

    def test_conflict_error_custom_message(self):
        """ConflictError can have custom message."""
        conflicts = [
            FieldConflict(
                field="priority",
                base="medium",
                rst="high",
                json="low",
                rst_file="tasks.rst",
                task_id="TASK-001",
            )
        ]
        error = ConflictError(conflicts, message="Custom conflict message")

        assert str(error) == "Custom conflict message"
        assert error.conflicts == conflicts

    def test_conflict_error_is_exception(self):
        """ConflictError can be raised and caught."""
        conflicts = [
            FieldConflict(
                field="priority",
                base="medium",
                rst="high",
                json="low",
                rst_file="tasks.rst",
                task_id="TASK-001",
            )
        ]

        with pytest.raises(ConflictError) as exc_info:
            raise ConflictError(conflicts)

        assert len(exc_info.value.conflicts) == 1
        assert exc_info.value.conflicts[0].task_id == "TASK-001"

    def test_conflict_error_auto_formats_message(self):
        """ConflictError auto-formats message from conflicts."""
        conflicts = [
            FieldConflict(
                field="status",
                base="open",
                rst="done",
                json="blocked",
                rst_file="tasks.rst",
                task_id="TASK-123",
            )
        ]
        error = ConflictError(conflicts)

        # Should auto-generate message
        assert "TASK-123" in str(error)
        assert "status" in str(error)

    def test_conflict_error_with_empty_conflicts(self):
        """ConflictError handles empty conflict list."""
        error = ConflictError([])
        assert "No conflicts" in str(error)
