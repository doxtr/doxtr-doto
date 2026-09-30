"""Tests for RST directive insertion.

Section 02 tests: Ensures task_id is properly propagated during RST updates.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from doxtr_doto.exceptions import DotoValidationError
from doxtr_doto.sync.rst_writer import (
    generate_directive_text,
    insert_doto_directive,
    _find_last_directive_line,
)


class TestGenerateDirectiveText:
    """Tests for generate_directive_text function."""

    def test_raises_on_missing_id(self):
        """generate_directive_text raises ValueError when 'id' is absent."""
        with pytest.raises(ValueError, match="'id'"):
            generate_directive_text({"title": "No ID Task"})

    def test_raises_on_empty_id(self):
        """generate_directive_text raises ValueError when 'id' is empty."""
        with pytest.raises(ValueError, match="'id'"):
            generate_directive_text({"title": "Empty ID Task", "id": ""})

    def test_generates_valid_directive_with_id(self):
        """generate_directive_text produces valid output with id present."""
        task_data = {
            "id": "TASK-001",
            "title": "Test Task",
            "status": "open",
            "priority": "medium",
        }
        result = generate_directive_text(task_data)
        assert ".. doto:: Test Task" in result
        assert ":id: TASK-001" in result

    def test_includes_all_fields(self):
        """generate_directive_text includes all provided fields."""
        task_data = {
            "id": "TASK-002",
            "title": "Full Task",
            "assignee": "alice",
            "priority": "high",
            "status": "in-progress",
            "due": "2025-12-31",
            "tags": ["urgent", "backend"],
            "depends_on": ["TASK-001"],
            "body": "Task description here.",
        }
        result = generate_directive_text(task_data)
        assert ":id: TASK-002" in result
        assert ":assignee: alice" in result
        assert ":priority: high" in result
        assert ":status: in-progress" in result
        assert ":due: 2025-12-31" in result
        assert ":tags: urgent, backend" in result
        assert ":depends-on: TASK-001" in result
        assert "Task description here." in result


class TestInsertDotoDirective:
    """Tests for insert_doto_directive function."""

    def test_raises_on_missing_id(self, tmp_path: Path):
        """insert_doto_directive raises DotoValidationError when task_data has no 'id'."""
        rst = tmp_path / "inbox.rst"
        with pytest.raises(DotoValidationError, match="'id'"):
            insert_doto_directive(rst, {"title": "No ID Task"})

    def test_insert_into_empty_file_produces_id_line(self, tmp_path: Path):
        """Inserting a new directive into an empty file includes :id: option."""
        rst = tmp_path / "inbox.rst"
        task_data = {
            "id": "TASK-001",
            "title": "My Task",
            "status": "open",
            "priority": "medium",
            "tags": [],
            "depends_on": [],
            "body": "",
        }
        insert_doto_directive(rst, task_data)

        content = rst.read_text()
        assert ":id: TASK-001" in content
        assert ".. doto:: My Task" in content

    def test_insert_creates_file_if_not_exists(self, tmp_path: Path):
        """insert_doto_directive creates file if it doesn't exist."""
        rst = tmp_path / "new_file.rst"
        assert not rst.exists()
        
        task_data = {"id": "TASK-001", "title": "New Task"}
        insert_doto_directive(rst, task_data)
        
        assert rst.exists()
        content = rst.read_text()
        assert ":id: TASK-001" in content

    def test_insert_creates_parent_directories(self, tmp_path: Path):
        """insert_doto_directive creates parent directories if they don't exist."""
        rst = tmp_path / "tasks" / "inbox" / "new.rst"
        task_data = {
            "id": "TASK-003",
            "title": "Nested",
            "status": "open",
            "priority": "medium",
            "tags": [],
            "depends_on": [],
            "body": "",
        }
        insert_doto_directive(rst, task_data)
        assert rst.exists()
        content = rst.read_text()
        assert ":id: TASK-003" in content

    def test_insert_after_existing_directive(self, tmp_path: Path):
        """New directive is inserted after the last existing doto directive."""
        rst = tmp_path / "tasks.rst"
        rst.write_text(
            ".. doto:: First Task\n"
            "   :id: TASK-001\n"
            "   :status: open\n\n"
            "Some prose.\n"
        )
        task_data = {
            "id": "TASK-002",
            "title": "Second Task",
            "status": "open",
            "priority": "medium",
            "tags": [],
            "depends_on": [],
            "body": "",
        }
        insert_doto_directive(rst, task_data)

        content = rst.read_text()
        pos_first = content.index("TASK-001")
        pos_second = content.index("TASK-002")
        assert pos_first < pos_second, "New directive should come after existing one"

    def test_insert_with_explicit_after_line(self, tmp_path: Path):
        """insert_doto_directive respects explicit after_line parameter."""
        rst = tmp_path / "tasks.rst"
        rst.write_text("Line 1\nLine 2\nLine 3\n")
        
        task_data = {"id": "TASK-001", "title": "Inserted Task"}
        insert_doto_directive(rst, task_data, after_line=2)
        
        content = rst.read_text()
        lines = content.split("\n")
        # Should have Line 1, Line 2, blank, directive, blank, Line 3
        assert "Line 2" in lines[1]
        task_line_idx = next(i for i, l in enumerate(lines) if "TASK-001" in l)
        assert task_line_idx > 1  # After line 2


class TestFindLastDirectiveLine:
    """Tests for _find_last_directive_line helper."""

    def test_returns_none_for_no_directives(self):
        """Returns None when there are no doto directives."""
        content = "Some prose.\n\nMore text.\n"
        result = _find_last_directive_line(content)
        assert result is None

    def test_finds_single_directive(self):
        """Finds the end line of a single directive."""
        content = (
            ".. doto:: Single Task\n"
            "   :id: TASK-001\n"
            "   :status: open\n"
        )
        result = _find_last_directive_line(content)
        assert result is not None
        assert result >= 3  # Should be at least line 3

    def test_finds_last_of_multiple_directives(self):
        """Finds the end line of the last directive when multiple exist."""
        content = (
            ".. doto:: First\n"
            "   :id: TASK-001\n\n"
            ".. doto:: Second\n"
            "   :id: TASK-002\n"
            "   :priority: high\n"
        )
        result = _find_last_directive_line(content)
        assert result is not None
        # Should point to end of TASK-002, not TASK-001
        assert result >= 5

    def test_handles_directive_with_body(self):
        """Correctly finds end of directive with body content."""
        content = (
            ".. doto:: Task with body\n"
            "   :id: TASK-001\n\n"
            "   This is the body.\n"
            "   More body text.\n"
        )
        result = _find_last_directive_line(content)
        assert result is not None
        assert result >= 4  # Should include body lines
