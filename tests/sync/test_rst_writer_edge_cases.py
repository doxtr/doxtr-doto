"""Edge case tests for RST writer.

Tests for generate_directive_text edge cases.
Note: Tests involving RST parsing with doto directives are in test_rst_insertion.py
and test_rst_removal.py to avoid test ordering issues with Sphinx directive registration.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from doxtr_doto.exceptions import DotoValidationError
from doxtr_doto.sync.rst_writer import (
    generate_directive_text,
    insert_doto_directive,
    remove_doto_directive,
    update_doto_directive,
)


class TestGenerateDirectiveText:
    """Tests for directive text generation edge cases."""
    
    def test_generate_missing_id_raises(self):
        """Should raise ValueError if id is missing."""
        with pytest.raises(ValueError, match="requires 'id'"):
            generate_directive_text({"title": "Test"})
    
    def test_generate_empty_id_raises(self):
        """Should raise ValueError if id is empty."""
        with pytest.raises(ValueError, match="requires 'id'"):
            generate_directive_text({"id": "", "title": "Test"})
    
    def test_generate_with_special_characters_in_title(self):
        """Title with special RST characters should be preserved."""
        result = generate_directive_text({
            "id": "TEST-001",
            "title": "Fix *bold* and ``code``",
        })
        assert "Fix *bold* and ``code``" in result
        assert ":id: TEST-001" in result
    
    def test_generate_with_multiline_body(self):
        """Body with multiple lines should be properly indented."""
        result = generate_directive_text({
            "id": "TEST-001",
            "title": "Test",
            "body": "Line 1\nLine 2\nLine 3",
        })
        lines = result.split("\n")
        body_lines = [l for l in lines if "Line" in l]
        # All body lines should be indented with 3 spaces
        assert len(body_lines) == 3
        assert all(l.startswith("   ") for l in body_lines)
    
    def test_generate_with_empty_tags_list(self):
        """Empty tags list should not add :tags: line."""
        result = generate_directive_text({
            "id": "TEST-001",
            "title": "Test",
            "tags": [],
        })
        assert ":tags:" not in result
    
    def test_generate_with_tags_list(self):
        """Tags list should be comma-separated."""
        result = generate_directive_text({
            "id": "TEST-001",
            "title": "Test",
            "tags": ["one", "two", "three"],
        })
        assert ":tags: one, two, three" in result
    
    def test_generate_with_depends_on_list(self):
        """depends_on list should be comma-separated."""
        result = generate_directive_text({
            "id": "TEST-001",
            "title": "Test",
            "depends_on": ["DEP-001", "DEP-002"],
        })
        assert ":depends-on: DEP-001, DEP-002" in result
    
    def test_generate_omits_default_priority(self):
        """Default priority 'medium' should be omitted."""
        result = generate_directive_text({
            "id": "TEST-001",
            "title": "Test",
            "priority": "medium",
        })
        assert ":priority:" not in result
    
    def test_generate_includes_non_default_priority(self):
        """Non-default priority should be included."""
        result = generate_directive_text({
            "id": "TEST-001",
            "title": "Test",
            "priority": "high",
        })
        assert ":priority: high" in result
    
    def test_generate_omits_default_status(self):
        """Default status 'open' should be omitted."""
        result = generate_directive_text({
            "id": "TEST-001",
            "title": "Test",
            "status": "open",
        })
        assert ":status:" not in result
    
    def test_generate_includes_non_default_status(self):
        """Non-default status should be included."""
        result = generate_directive_text({
            "id": "TEST-001",
            "title": "Test",
            "status": "in-progress",
        })
        assert ":status: in-progress" in result
    
    def test_generate_with_due_date(self):
        """Due date should be included."""
        result = generate_directive_text({
            "id": "TEST-001",
            "title": "Test",
            "due": "2026-12-31",
        })
        assert ":due: 2026-12-31" in result
    
    def test_generate_with_assignee(self):
        """Assignee should be included."""
        result = generate_directive_text({
            "id": "TEST-001",
            "title": "Test",
            "assignee": "alice",
        })
        assert ":assignee: alice" in result
    
    def test_generate_with_empty_body(self):
        """Empty body should not add extra content."""
        result = generate_directive_text({
            "id": "TEST-001",
            "title": "Test",
            "body": "",
        })
        # Should just have directive and id
        lines = [l for l in result.split("\n") if l.strip()]
        assert len(lines) == 2
    
    def test_generate_with_all_fields(self):
        """Should generate directive with all fields."""
        result = generate_directive_text({
            "id": "TEST-001",
            "title": "Full task",
            "assignee": "alice",
            "priority": "high",
            "status": "in-progress",
            "due": "2026-12-31",
            "tags": ["feature", "urgent"],
            "depends_on": ["DEP-001"],
            "body": "Task description.",
        })
        assert ".. doto:: Full task" in result
        assert ":id: TEST-001" in result
        assert ":assignee: alice" in result
        assert ":priority: high" in result
        assert ":status: in-progress" in result
        assert ":due: 2026-12-31" in result
        assert ":tags: feature, urgent" in result
        assert ":depends-on: DEP-001" in result
        assert "Task description." in result


class TestInsertDotoDirectiveValidation:
    """Tests for insert_doto_directive validation (no RST parsing)."""
    
    def test_insert_creates_file_if_missing(self, tmp_path: Path):
        """Should create file if it doesn't exist."""
        rst_file = tmp_path / "new.rst"
        
        success = insert_doto_directive(rst_file, {
            "id": "NEW-001",
            "title": "New task",
        })
        
        assert success
        assert rst_file.exists()
        assert "NEW-001" in rst_file.read_text()
    
    def test_insert_creates_parent_dirs(self, tmp_path: Path):
        """Should create parent directories."""
        rst_file = tmp_path / "subdir" / "deep" / "new.rst"
        
        success = insert_doto_directive(rst_file, {
            "id": "NEW-001",
            "title": "New task",
        })
        
        assert success
        assert rst_file.exists()
        content = rst_file.read_text()
        assert "NEW-001" in content
    
    def test_insert_without_id_raises(self, tmp_path: Path):
        """Should raise DotoValidationError if id is missing."""
        rst_file = tmp_path / "tasks.rst"
        
        with pytest.raises(DotoValidationError, match="'id'"):
            insert_doto_directive(rst_file, {"title": "Test"})
    
    def test_insert_with_empty_id_raises(self, tmp_path: Path):
        """Should raise DotoValidationError if id is empty."""
        rst_file = tmp_path / "tasks.rst"
        
        with pytest.raises((DotoValidationError, ValueError)):
            insert_doto_directive(rst_file, {"id": "", "title": "Test"})
    
    def test_insert_with_after_line(self, tmp_path: Path):
        """Should insert after specified line (no doto directives to parse)."""
        rst_file = tmp_path / "tasks.rst"
        rst_file.write_text("Line 1\nLine 2\nLine 3\n")
        
        success = insert_doto_directive(rst_file, {
            "id": "TASK-001",
            "title": "Inserted Task",
        }, after_line=2)
        
        assert success
        content = rst_file.read_text()
        # Task should appear after Line 2
        pos_line2 = content.find("Line 2")
        pos_task = content.find("TASK-001")
        assert pos_line2 < pos_task
    
    def test_insert_into_empty_file(self, tmp_path: Path):
        """Should insert into empty file."""
        rst_file = tmp_path / "empty.rst"
        rst_file.write_text("")
        
        success = insert_doto_directive(rst_file, {
            "id": "TASK-001",
            "title": "First task",
        })
        
        assert success
        content = rst_file.read_text()
        assert "TASK-001" in content
        assert ".. doto:: First task" in content


class TestRemoveDotoDirectiveValidation:
    """Tests for remove_doto_directive validation (no RST parsing)."""
    
    def test_remove_nonexistent_file_returns_false(self, tmp_path: Path):
        """Should return False for missing file."""
        rst_file = tmp_path / "missing.rst"
        
        result = remove_doto_directive(rst_file, "TASK-001")
        
        assert result is False
    
    def test_remove_empty_task_id_raises(self, tmp_path: Path):
        """Should raise DotoValidationError for empty task_id."""
        rst_file = tmp_path / "tasks.rst"
        rst_file.write_text("content")
        
        with pytest.raises(DotoValidationError):
            remove_doto_directive(rst_file, "")


class TestUpdateDotoDirectiveValidation:
    """Tests for update_doto_directive validation (no RST parsing)."""
    
    def test_update_nonexistent_returns_false(self, tmp_path: Path):
        """Should return False if task not found."""
        rst_file = tmp_path / "tasks.rst"
        rst_file.write_text("No tasks here.")
        
        result = update_doto_directive(rst_file, "TASK-001", {"priority": "high"})
        
        assert result is False
    
    def test_update_empty_task_id_raises(self, tmp_path: Path):
        """Should raise DotoValidationError for empty task_id."""
        rst_file = tmp_path / "tasks.rst"
        rst_file.write_text("content")
        
        with pytest.raises(DotoValidationError):
            update_doto_directive(rst_file, "", {"priority": "high"})
    
    def test_update_nonexistent_file_returns_false(self, tmp_path: Path):
        """Should return False for nonexistent file."""
        rst_file = tmp_path / "missing.rst"
        
        result = update_doto_directive(rst_file, "TASK-001", {"priority": "high"})
        
        assert result is False
