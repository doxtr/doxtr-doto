"""Tests for the 3-way merge algorithm."""

from __future__ import annotations

import pytest


class TestThreeWayMerge:
    """Test the 3-way merge algorithm."""
    
    def test_no_changes(self, doto_sync):
        """Neither RST nor JSON changed - no updates needed."""
        result = doto_sync.merge_task(
            task_id="TASK-001",
            snapshot={"priority": "medium", "assignee": "alice"},
            rst_current={"priority": "medium", "assignee": "alice"},
            json_current={"priority": "medium", "assignee": "alice"},
        )
        assert result.has_changes is False
        assert result.conflicts == []
    
    def test_rst_only_change(self, doto_sync):
        """RST changed, JSON didn't - use RST value."""
        result = doto_sync.merge_task(
            task_id="TASK-001",
            snapshot={"priority": "medium"},
            rst_current={"priority": "high"},      # Changed in RST
            json_current={"priority": "medium"},   # Unchanged
        )
        assert result.merged["priority"] == "high"
        assert result.update_json is True
        assert result.write_rst is False  # write_rst, not update_rst
    
    def test_json_only_change(self, doto_sync):
        """JSON changed (via CLI), RST didn't - use JSON value."""
        result = doto_sync.merge_task(
            task_id="TASK-001",
            snapshot={"assignee": "alice"},
            rst_current={"assignee": "alice"},     # Unchanged
            json_current={"assignee": "bob"},      # Changed via CLI
        )
        assert result.merged["assignee"] == "bob"
        assert result.write_rst is True  # write_rst, not update_rst
        assert result.update_json is False
    
    def test_both_change_same_value(self, doto_sync):
        """Both changed to same value - no conflict."""
        result = doto_sync.merge_task(
            task_id="TASK-001",
            snapshot={"status": "open"},
            rst_current={"status": "done"},
            json_current={"status": "done"},
        )
        assert result.merged["status"] == "done"
        assert result.conflicts == []
    
    def test_both_change_different_values_conflict(self, doto_sync):
        """Both changed to different values - conflict."""
        result = doto_sync.merge_task(
            task_id="TASK-001",
            snapshot={"priority": "medium"},
            rst_current={"priority": "critical"},  # User edited RST
            json_current={"priority": "high"},     # CLI changed it
        )
        assert len(result.conflicts) == 1
        conflict = result.conflicts[0]
        assert conflict.field == "priority"
        assert conflict.base == "medium"
        assert conflict.rst == "critical"
        assert conflict.json == "high"
    
    def test_multiple_fields_mixed_changes(self, doto_sync):
        """Multiple fields with different change patterns."""
        result = doto_sync.merge_task(
            task_id="TASK-001",
            snapshot={"priority": "medium", "assignee": "alice", "status": "open"},
            rst_current={"priority": "high", "assignee": "alice", "status": "open"},
            json_current={"priority": "medium", "assignee": "bob", "status": "in-progress"},
        )
        # RST changed priority, JSON changed assignee and status
        assert result.merged["priority"] == "high"       # From RST
        assert result.merged["assignee"] == "bob"        # From JSON
        assert result.merged["status"] == "in-progress"  # From JSON
        assert result.conflicts == []
    
    def test_new_task_from_rst_no_snapshot(self, doto_sync):
        """New task in RST with no prior snapshot - RST is authoritative."""
        result = doto_sync.merge_task(
            task_id="TASK-NEW",
            snapshot=None,
            rst_current={"priority": "high", "assignee": "alice"},
            json_current=None,
        )
        assert result.merged["priority"] == "high"
        assert result.create_in_json is True
    
    def test_new_task_from_json_cli(self, doto_sync):
        """New task created via CLI - should be written to RST."""
        result = doto_sync.merge_task(
            task_id="TASK-CLI",
            snapshot=None,
            rst_current=None,
            json_current={"priority": "medium", "assignee": "bob", "archived": False},
        )
        assert result.merged["priority"] == "medium"
        assert result.create_in_rst is True


class TestConflictDetection:
    """Test conflict detection and error messages."""
    
    def test_conflict_error_message_format(self, doto_sync):
        """Conflict error message includes all necessary info."""
        result = doto_sync.merge_task(
            task_id="TASK-001",
            snapshot={"priority": "medium"},
            rst_current={"priority": "critical"},
            json_current={"priority": "high"},
            rst_file="features/auth.rst",
            rst_line=42,
        )
        
        assert len(result.conflicts) == 1
        conflict = result.conflicts[0]
        
        # Verify conflict contains all required info
        assert conflict.task_id == "TASK-001"
        assert conflict.field == "priority"
        assert conflict.base == "medium"
        assert conflict.rst == "critical"
        assert conflict.json == "high"
        assert conflict.rst_file == "features/auth.rst"
    
    def test_multiple_conflicts_all_reported(self, doto_sync):
        """Multiple field conflicts are all reported."""
        result = doto_sync.merge_task(
            task_id="TASK-001",
            snapshot={"priority": "medium", "assignee": "alice"},
            rst_current={"priority": "critical", "assignee": "charlie"},
            json_current={"priority": "high", "assignee": "bob"},
        )
        assert len(result.conflicts) == 2
        conflict_fields = {c.field for c in result.conflicts}
        assert conflict_fields == {"priority", "assignee"}


class TestRstHashTracking:
    """Test RST content hash for change detection."""
    
    def test_hash_unchanged_content(self, doto_sync):
        """Same content produces same hash."""
        content = '''.. doto:: Fix bug
   :priority: high
   :assignee: alice

   Description here.
'''
        hash1 = doto_sync.compute_rst_hash(content)
        hash2 = doto_sync.compute_rst_hash(content)
        assert hash1 == hash2
    
    def test_hash_whitespace_normalization(self, doto_sync):
        """Whitespace differences don't affect hash."""
        content1 = '''.. doto:: Fix bug
   :priority: high
'''
        content2 = '''.. doto:: Fix bug
   :priority:   high
'''
        hash1 = doto_sync.compute_rst_hash(content1)
        hash2 = doto_sync.compute_rst_hash(content2)
        assert hash1 == hash2  # Whitespace normalized
    
    def test_hash_detects_content_change(self, doto_sync):
        """Content changes produce different hash."""
        content1 = '''.. doto:: Fix bug
   :priority: high
'''
        content2 = '''.. doto:: Fix bug
   :priority: critical
'''
        hash1 = doto_sync.compute_rst_hash(content1)
        hash2 = doto_sync.compute_rst_hash(content2)
        assert hash1 != hash2
