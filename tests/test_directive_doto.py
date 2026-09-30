"""Tests for the doto directive."""

from __future__ import annotations

import pytest
from datetime import date


class TestDotoDirective:
    """Test the main doto directive."""
    
    def test_basic_task(self, doto_app, sample_tasks_rst):
        """Test parsing a basic task directive."""
        doto_app.build()
        
        env = doto_app.env
        assert hasattr(env, "doto_data")
        
        tasks = env.doto_data.all_tasks
        assert "TASK-001" in tasks
        
        task = tasks["TASK-001"]
        assert task.title == "Implement user authentication"
        assert task.assignee == "alice"
        assert task.priority == "high"
        assert task.status == "open"
    
    def test_auto_generated_id(self, doto_srcdir, make_app):
        """Test that IDs are auto-generated when not provided."""
        tasks_rst = doto_srcdir / "autoid.rst"
        tasks_rst.write_text('''
Auto ID Test
============

.. doto:: Task without explicit ID
   :priority: medium

   This task should get an auto-generated ID.
''')
        
        # Update index
        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   autoid\n")
        
        app = make_app(srcdir=doto_srcdir)
        app.build()
        
        tasks = app.env.doto_data.all_tasks
        # Should have at least one task with auto-generated ID
        assert len(tasks) >= 1
        
        # Auto-generated IDs use format {docname}-L{lineno}
        auto_ids = [tid for tid in tasks if tid.startswith("autoid-L")]
        assert len(auto_ids) == 1
    
    def test_task_with_all_options(self, doto_srcdir, make_app):
        """Test task with all available options."""
        tasks_rst = doto_srcdir / "full.rst"
        tasks_rst.write_text('''
Full Options Test
=================

.. doto:: Complete task example
   :id: FULL-001
   :assignee: charlie
   :priority: critical
   :status: in-progress
   :due: 2026-12-31
   :tags: feature, frontend, urgent
   :depends-on: TASK-001, TASK-002
   :created: 2026-01-01
   :updated: 2026-07-26

   This task has all options specified.
   
   It includes multiple paragraphs in the body.
''')
        
        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   full\n")
        
        app = make_app(srcdir=doto_srcdir)
        app.build()
        
        task = app.env.doto_data.all_tasks["FULL-001"]
        assert task.title == "Complete task example"
        assert task.assignee == "charlie"
        assert task.priority == "critical"
        assert task.status == "in-progress"
        # due is now stored as ISO string, not date object
        assert task.due == "2026-12-31"
        assert task.tags == ["feature", "frontend", "urgent"]
        assert task.depends_on == ["TASK-001", "TASK-002"]
    
    def test_invalid_priority_warning(self, doto_srcdir, make_app):
        """Test that invalid priority values cause build errors."""
        tasks_rst = doto_srcdir / "invalid.rst"
        tasks_rst.write_text('''
Invalid Priority
================

.. doto:: Task with invalid priority
   :id: INVALID-001
   :priority: ultra-high

   This should raise an error about invalid priority.
''')
        
        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   invalid\n")
        
        app = make_app(srcdir=doto_srcdir)
        # Build will complete but the task won't be created due to error
        app.build()
        
        # Invalid priority causes error, so task should NOT be in the list
        tasks = app.env.doto_data.all_tasks
        # The directive raises an error for invalid priority, so task is not created
        assert "INVALID-001" not in tasks
    
    def test_invalid_date_format(self, doto_srcdir, make_app):
        """Test handling of invalid date formats."""
        tasks_rst = doto_srcdir / "baddate.rst"
        tasks_rst.write_text('''
Bad Date
========

.. doto:: Task with bad date
   :id: BADDATE-001
   :due: not-a-date

   This has an invalid date format.
''')
        
        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   baddate\n")
        
        app = make_app(srcdir=doto_srcdir)
        app.build()
        
        # Invalid date causes error, so task should NOT be in the list
        tasks = app.env.doto_data.all_tasks
        assert "BADDATE-001" not in tasks


class TestDotoDirectiveValidation:
    """Test directive validation logic."""
    
    def test_valid_statuses(self):
        """Test all valid status values."""
        from doxtr_doto.utils import validate_status, VALID_STATUSES
        
        for status in VALID_STATUSES:
            assert validate_status(status) == status
    
    def test_valid_priorities(self):
        """Test all valid priority values."""
        from doxtr_doto.utils import validate_priority, VALID_PRIORITIES
        
        for priority in VALID_PRIORITIES:
            assert validate_priority(priority) == priority
    
    def test_parse_tags(self):
        """Test tag parsing."""
        from doxtr_doto.utils import parse_list
        
        assert parse_list("a, b, c") == ["a", "b", "c"]
        assert parse_list("single") == ["single"]
        assert parse_list("  spaced , items  ") == ["spaced", "items"]
        assert parse_list("") == []
    
    def test_parse_date(self):
        """Test date parsing."""
        from doxtr_doto.utils import parse_date
        
        assert parse_date("2026-08-15") == date(2026, 8, 15)
        assert parse_date("2026-01-01") == date(2026, 1, 1)
        # Invalid date raises ValueError
        import pytest
        with pytest.raises(ValueError):
            parse_date("invalid")
        # Empty string returns None
        assert parse_date("") is None
