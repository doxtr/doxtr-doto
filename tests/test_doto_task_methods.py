"""Tests for DotoTask methods: to_sync_dict() and css_classes().

These tests verify that the DotoTask class provides proper methods for:
1. Extracting task data for bidirectional sync operations
2. Generating CSS classes based on task properties

This addresses the "Feature Envy" code smell by moving logic that was
previously scattered across sync/__init__.py and nodes.py into the
DotoTask class itself.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from doxtr_doto.collectors import DotoTask
from doxtr_doto.constants import (
    DEFAULT_PRIORITY,
    DEFAULT_STATUS,
    PRIORITY_CLASSES,
    STATUS_CLASSES,
)
from doxtr_doto.enums import TaskSource


class TestToSyncDict:
    """Tests for DotoTask.to_sync_dict() method."""
    
    def test_basic_task_sync_dict(self) -> None:
        """Test that to_sync_dict returns expected keys for a basic task."""
        task = DotoTask(
            id="TASK-001",
            title="Test Task",
            docname="index",
            lineno=10,
        )
        result = task.to_sync_dict()
        
        assert result["id"] == "TASK-001"
        assert result["title"] == "Test Task"
        assert result["_rst_file"] == "index"
        assert result["_rst_line"] == 10
    
    def test_all_fields_included(self) -> None:
        """Test that all task fields are included in sync dict."""
        task = DotoTask(
            id="TASK-002",
            title="Full Task",
            docname="docs/tasks",
            lineno=25,
            assignee="alice",
            priority="high",
            status="in-progress",
            due="2025-12-31",
            tags=["urgent", "backend"],
            depends_on=["TASK-001"],
            body="This is the task description.",
            progress=50,
        )
        result = task.to_sync_dict()
        
        assert result["id"] == "TASK-002"
        assert result["title"] == "Full Task"
        assert result["assignee"] == "alice"
        assert result["priority"] == "high"
        assert result["status"] == "in-progress"
        assert result["due"] == "2025-12-31"
        assert result["tags"] == ["urgent", "backend"]
        assert result["depends_on"] == ["TASK-001"]
        assert result["body"] == "This is the task description."
        assert result["progress"] == 50
        assert result["_rst_file"] == "docs/tasks"
        assert result["_rst_line"] == 25
    
    def test_none_docname_becomes_empty_string(self) -> None:
        """Test that None docname is converted to empty string for _rst_file."""
        task = DotoTask(
            id="TASK-003",
            title="No Doc Task",
            docname=None,
        )
        result = task.to_sync_dict()
        
        assert result["_rst_file"] == ""
        assert result["_rst_line"] is None
    
    def test_due_date_object_converted_to_string(self) -> None:
        """Test that due date as date object is converted to ISO string."""
        # DotoTask normalizes dates in __post_init__, so we test the output
        task = DotoTask(
            id="TASK-004",
            title="Date Task",
            due="2025-06-15",
        )
        result = task.to_sync_dict()
        
        assert result["due"] == "2025-06-15"
    
    def test_none_due_remains_none(self) -> None:
        """Test that None due date stays None."""
        task = DotoTask(
            id="TASK-005",
            title="No Due Task",
        )
        result = task.to_sync_dict()
        
        assert result["due"] is None
    
    def test_empty_lists_preserved(self) -> None:
        """Test that empty tags and depends_on lists are preserved."""
        task = DotoTask(
            id="TASK-006",
            title="Empty Lists Task",
            tags=[],
            depends_on=[],
        )
        result = task.to_sync_dict()
        
        assert result["tags"] == []
        assert result["depends_on"] == []
    
    def test_none_progress_preserved(self) -> None:
        """Test that None progress is preserved in sync dict."""
        task = DotoTask(
            id="TASK-007",
            title="No Progress Task",
            progress=None,
        )
        result = task.to_sync_dict()
        
        assert result["progress"] is None
    
    def test_zero_progress_preserved(self) -> None:
        """Test that zero progress is preserved (not confused with None)."""
        task = DotoTask(
            id="TASK-008",
            title="Zero Progress Task",
            progress=0,
        )
        result = task.to_sync_dict()
        
        assert result["progress"] == 0
    
    def test_sync_dict_does_not_include_internal_fields(self) -> None:
        """Test that internal fields like content_nodes are not included."""
        task = DotoTask(
            id="TASK-009",
            title="Internal Fields Task",
            created=datetime.now(),
            updated=datetime.now(),
            archived=True,
            source=TaskSource.JSON,
        )
        result = task.to_sync_dict()
        
        # These should NOT be in the sync dict
        assert "created" not in result
        assert "updated" not in result
        assert "archived" not in result
        assert "source" not in result
        assert "content_nodes" not in result
        assert "_sync" not in result
        assert "_git" not in result


class TestCssClasses:
    """Tests for DotoTask.css_classes() method."""
    
    def test_basic_classes(self) -> None:
        """Test that basic CSS classes are generated correctly."""
        task = DotoTask(
            id="TASK-001",
            title="Test Task",
            priority="medium",
            status="open",
        )
        classes = task.css_classes()
        
        assert "doto" in classes
        assert PRIORITY_CLASSES["medium"] in classes
        assert STATUS_CLASSES["open"] in classes
    
    def test_all_priorities(self) -> None:
        """Test CSS classes for all priority levels."""
        for priority, expected_class in PRIORITY_CLASSES.items():
            task = DotoTask(
                id="T-1",
                title="Test",
                priority=priority,
            )
            classes = task.css_classes()
            assert expected_class in classes, f"Missing class for priority {priority}"
    
    def test_all_statuses(self) -> None:
        """Test CSS classes for all status values."""
        for status, expected_class in STATUS_CLASSES.items():
            task = DotoTask(
                id="T-1",
                title="Test",
                status=status,
            )
            classes = task.css_classes()
            assert expected_class in classes, f"Missing class for status {status}"
    
    def test_overdue_class_added(self) -> None:
        """Test that doto-overdue class is added for overdue tasks."""
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        task = DotoTask(
            id="TASK-001",
            title="Overdue Task",
            due=yesterday,
            status="open",
        )
        classes = task.css_classes()
        
        assert "doto-overdue" in classes
    
    def test_overdue_class_not_added_for_done_tasks(self) -> None:
        """Test that done tasks are not marked overdue even with past due date."""
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        task = DotoTask(
            id="TASK-001",
            title="Done Task",
            due=yesterday,
            status="done",
        )
        classes = task.css_classes()
        
        assert "doto-overdue" not in classes
    
    def test_overdue_class_not_added_for_future_due(self) -> None:
        """Test that future due dates don't add overdue class."""
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        task = DotoTask(
            id="TASK-001",
            title="Future Task",
            due=tomorrow,
            status="open",
        )
        classes = task.css_classes()
        
        assert "doto-overdue" not in classes
    
    def test_extra_classes_added(self) -> None:
        """Test that extra classes are appended."""
        task = DotoTask(
            id="TASK-001",
            title="Test Task",
        )
        classes = task.css_classes(extra=["doto-card", "highlighted"])
        
        assert "doto-card" in classes
        assert "highlighted" in classes
    
    def test_extra_classes_with_overdue(self) -> None:
        """Test that extra classes work together with overdue."""
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        task = DotoTask(
            id="TASK-001",
            title="Overdue Task",
            due=yesterday,
            status="in-progress",
        )
        classes = task.css_classes(extra=["doto-card"])
        
        assert "doto" in classes
        assert "doto-card" in classes
        assert "doto-overdue" in classes
    
    def test_empty_strings_filtered_out(self) -> None:
        """Test that empty strings are not included in the result."""
        task = DotoTask(
            id="TASK-001",
            title="Test Task",
            priority="unknown_priority",  # Not in PRIORITY_CLASSES
            status="unknown_status",       # Not in STATUS_CLASSES
        )
        classes = task.css_classes()
        
        # Should only have "doto" (no empty strings)
        assert all(c for c in classes), "Empty strings should be filtered out"
        assert "" not in classes
    
    def test_classes_order(self) -> None:
        """Test that classes are in expected order: doto, priority, status, [overdue], [extra]."""
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        task = DotoTask(
            id="TASK-001",
            title="Test Task",
            priority="high",
            status="blocked",
            due=yesterday,
        )
        classes = task.css_classes(extra=["custom-class"])
        
        # Verify order
        doto_idx = classes.index("doto")
        priority_idx = classes.index(PRIORITY_CLASSES["high"])
        status_idx = classes.index(STATUS_CLASSES["blocked"])
        overdue_idx = classes.index("doto-overdue")
        custom_idx = classes.index("custom-class")
        
        assert doto_idx < priority_idx < status_idx < overdue_idx < custom_idx
    
    def test_none_extra_is_safe(self) -> None:
        """Test that passing None as extra is safe."""
        task = DotoTask(id="T-1", title="Test")
        classes = task.css_classes(extra=None)
        
        assert "doto" in classes
    
    def test_empty_extra_list_is_safe(self) -> None:
        """Test that passing empty list as extra is safe."""
        task = DotoTask(id="T-1", title="Test")
        classes = task.css_classes(extra=[])
        
        assert "doto" in classes


class TestCssClassesIntegration:
    """Integration tests for css_classes() with various scenarios."""
    
    def test_critical_blocked_overdue_task(self) -> None:
        """Test a task with critical priority, blocked status, and overdue."""
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        task = DotoTask(
            id="URGENT-001",
            title="Critical Issue",
            priority="critical",
            status="blocked",
            due=yesterday,
        )
        classes = task.css_classes()
        
        assert "doto" in classes
        assert "doto-priority-critical" in classes
        assert "doto-status-blocked" in classes
        assert "doto-overdue" in classes
    
    def test_low_priority_done_task(self) -> None:
        """Test a low priority done task."""
        task = DotoTask(
            id="LOW-001",
            title="Minor Task",
            priority="low",
            status="done",
        )
        classes = task.css_classes()
        
        assert "doto" in classes
        assert "doto-priority-low" in classes
        assert "doto-status-done" in classes
        assert "doto-overdue" not in classes
    
    def test_card_rendering_classes(self) -> None:
        """Test classes suitable for card rendering."""
        task = DotoTask(
            id="CARD-001",
            title="Card Task",
            priority="high",
            status="in-progress",
        )
        classes = task.css_classes(extra=["doto-card"])
        
        assert "doto" in classes
        assert "doto-card" in classes
        assert "doto-priority-high" in classes
        assert "doto-status-in-progress" in classes
    
    def test_list_item_rendering_classes(self) -> None:
        """Test classes suitable for list item rendering."""
        task = DotoTask(
            id="LIST-001",
            title="List Task",
        )
        classes = task.css_classes(extra=["doto-list-item"])
        
        assert "doto" in classes
        assert "doto-list-item" in classes


class TestToSyncDictAndCssClassesConsistency:
    """Tests to ensure both methods work consistently on the same task."""
    
    def test_methods_do_not_modify_task(self) -> None:
        """Test that calling these methods doesn't modify the task."""
        task = DotoTask(
            id="TASK-001",
            title="Test Task",
            priority="high",
            status="open",
            due="2025-12-31",
            tags=["test"],
        )
        
        # Store original values
        orig_id = task.id
        orig_title = task.title
        orig_priority = task.priority
        orig_status = task.status
        orig_due = task.due
        orig_tags = list(task.tags)
        
        # Call both methods
        _ = task.to_sync_dict()
        _ = task.css_classes()
        _ = task.css_classes(extra=["extra"])
        
        # Verify nothing changed
        assert task.id == orig_id
        assert task.title == orig_title
        assert task.priority == orig_priority
        assert task.status == orig_status
        assert task.due == orig_due
        assert task.tags == orig_tags
    
    def test_repeated_calls_return_consistent_results(self) -> None:
        """Test that repeated calls return the same results."""
        task = DotoTask(
            id="TASK-001",
            title="Test Task",
            priority="medium",
            status="open",
        )
        
        sync_dict1 = task.to_sync_dict()
        sync_dict2 = task.to_sync_dict()
        assert sync_dict1 == sync_dict2
        
        classes1 = task.css_classes()
        classes2 = task.css_classes()
        assert classes1 == classes2
