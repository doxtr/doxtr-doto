"""Tests for conflict detection and storage in bidirectional sync.

Section 12 tests: Ensures conflicts are properly detected, stored in JSON,
and cleared when sync completes cleanly.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from doxtr_doto.sync.json_store import JsonTaskStore
from doxtr_doto.sync.merge import sync_task, create_snapshot
from doxtr_doto.sync.conflict import FieldConflict


@pytest.fixture
def store_with_snapshot(tmp_path: Path) -> JsonTaskStore:
    """A JSON store with a task that has a snapshot."""
    store_path = tmp_path / ".doto" / "tasks.json"
    store_path.parent.mkdir(parents=True)
    store = JsonTaskStore(store_path)
    store.data["tasks"] = {
        "TASK-001": {
            "title": "Original title",
            "status": "open",
            "priority": "medium",
            "assignee": None,
            "due": None,
            "tags": [],
            "depends_on": [],
            "body": "",
            "_sync": {
                "snapshot": {
                    "title": "Original title",
                    "status": "open",
                    "priority": "medium",
                    "assignee": None,
                    "due": None,
                    "tags": [],
                    "depends_on": [],
                    "body": "",
                },
                "rst_file": "index.rst",
                "rst_line": 5,
            },
        }
    }
    store.save()
    return store


class TestConflictStorage:
    """Tests for conflict storage in the JSON store."""

    def test_conflicts_written_to_store_data(self, store_with_snapshot: JsonTaskStore):
        """Conflicts can be serialized and stored in the JSON store."""
        # Create a conflict manually
        conflicts = [
            FieldConflict(
                task_id="TASK-001",
                field="title",
                base="Original title",
                rst="RST title",
                json="JSON title",
                rst_file="index.rst",
            )
        ]
        
        # Serialize conflicts to store
        serialized = [
            {
                "task_id": c.task_id,
                "field": c.field,
                "base": c.base,
                "rst": c.rst,
                "json": c.json,
                "rst_file": c.rst_file,
            }
            for c in conflicts
        ]
        store_with_snapshot.data["_conflicts"] = serialized
        store_with_snapshot.save()
        
        # Reload and verify
        store_with_snapshot.load()
        assert "_conflicts" in store_with_snapshot.data
        assert len(store_with_snapshot.data["_conflicts"]) == 1
        assert store_with_snapshot.data["_conflicts"][0]["task_id"] == "TASK-001"

    def test_conflicts_cleared_when_removed(self, store_with_snapshot: JsonTaskStore):
        """Conflicts key can be removed from store after resolution."""
        # Pre-populate conflicts
        store_with_snapshot.data["_conflicts"] = [
            {"task_id": "TASK-001", "field": "title"}
        ]
        store_with_snapshot.save()
        
        # Clear conflicts
        store_with_snapshot.data.pop("_conflicts", None)
        store_with_snapshot.save()
        
        # Reload and verify
        store_with_snapshot.load()
        assert "_conflicts" not in store_with_snapshot.data

    def test_conflict_fields_contain_required_keys(self):
        """FieldConflict contains all required information."""
        conflict = FieldConflict(
            task_id="TASK-001",
            field="status",
            base="open",
            rst="done",
            json="in-progress",
            rst_file="tasks.rst",
        )
        
        assert conflict.task_id == "TASK-001"
        assert conflict.field == "status"
        assert conflict.base == "open"
        assert conflict.rst == "done"
        assert conflict.json == "in-progress"
        assert conflict.rst_file == "tasks.rst"


class TestConflictDetectionInMerge:
    """Tests for conflict detection during 3-way merge."""

    def test_conflict_detected_when_both_sides_differ(self):
        """Merge detects conflict when RST and JSON both changed differently."""
        snapshot = {
            "title": "Original",
            "status": "open",
            "priority": "medium",
            "assignee": None,
            "due": None,
            "tags": [],
            "depends_on": [],
            "body": "",
        }
        json_task = {
            "title": "JSON changed",
            "status": "open",
            "priority": "medium",
            "_sync": {"snapshot": snapshot, "rst_file": "tasks.rst"},
        }
        rst_current = {
            "title": "RST changed",
            "status": "open",
            "priority": "medium",
        }
        
        result = sync_task("TASK-001", rst_current, json_task, "tasks.rst", 10)
        
        assert result.has_conflicts
        assert len(result.conflicts) == 1
        assert result.conflicts[0].field == "title"
        assert result.conflicts[0].base == "Original"
        assert result.conflicts[0].rst == "RST changed"
        assert result.conflicts[0].json == "JSON changed"

    def test_no_conflict_when_both_change_to_same_value(self):
        """No conflict when RST and JSON both changed to the same value."""
        snapshot = {
            "title": "Original",
            "status": "open",
            "priority": "medium",
            "assignee": None,
            "due": None,
            "tags": [],
            "depends_on": [],
            "body": "",
        }
        json_task = {
            "title": "Same new title",
            "status": "open",
            "priority": "medium",
            "_sync": {"snapshot": snapshot},
        }
        rst_current = {
            "title": "Same new title",
            "status": "open",
            "priority": "medium",
        }
        
        result = sync_task("TASK-001", rst_current, json_task, "tasks.rst", 10)
        
        assert not result.has_conflicts
        assert result.merged["title"] == "Same new title"

    def test_no_conflict_when_only_rst_changed(self):
        """No conflict when only RST changed."""
        snapshot = {
            "title": "Original",
            "status": "open",
            "priority": "medium",
            "assignee": None,
            "due": None,
            "tags": [],
            "depends_on": [],
            "body": "",
        }
        json_task = {
            "title": "Original",
            "status": "open",
            "priority": "medium",
            "_sync": {"snapshot": snapshot},
        }
        rst_current = {
            "title": "RST changed",
            "status": "open",
            "priority": "medium",
        }
        
        result = sync_task("TASK-001", rst_current, json_task, "tasks.rst", 10)
        
        assert not result.has_conflicts
        assert result.merged["title"] == "RST changed"
        assert result.update_json is True

    def test_no_conflict_when_only_json_changed(self):
        """No conflict when only JSON changed."""
        snapshot = {
            "title": "Original",
            "status": "open",
            "priority": "medium",
            "assignee": None,
            "due": None,
            "tags": [],
            "depends_on": [],
            "body": "",
        }
        json_task = {
            "title": "JSON changed",
            "status": "open",
            "priority": "medium",
            "_sync": {"snapshot": snapshot},
        }
        rst_current = {
            "title": "Original",
            "status": "open",
            "priority": "medium",
        }
        
        result = sync_task("TASK-001", rst_current, json_task, "tasks.rst", 10)
        
        assert not result.has_conflicts
        assert result.merged["title"] == "JSON changed"
        assert result.write_rst is True

    def test_multiple_conflicts_all_reported(self):
        """Multiple field conflicts are all detected and reported."""
        snapshot = {
            "title": "Original title",
            "status": "open",
            "priority": "medium",
            "assignee": "alice",
            "due": None,
            "tags": [],
            "depends_on": [],
            "body": "",
        }
        json_task = {
            "title": "JSON title",
            "status": "in-progress",
            "priority": "high",
            "assignee": "alice",
            "_sync": {"snapshot": snapshot, "rst_file": "tasks.rst"},
        }
        rst_current = {
            "title": "RST title",
            "status": "blocked",
            "priority": "critical",
            "assignee": "alice",
        }
        
        result = sync_task("TASK-001", rst_current, json_task, "tasks.rst", 10)
        
        assert result.has_conflicts
        assert len(result.conflicts) == 3
        conflict_fields = {c.field for c in result.conflicts}
        assert conflict_fields == {"title", "status", "priority"}


class TestConflictSerialization:
    """Tests for serializing conflict values."""

    def test_date_values_serialized(self):
        """Date values in conflicts are properly serialized."""
        from datetime import date
        
        # Create a conflict with date values
        conflict = FieldConflict(
            task_id="TASK-001",
            field="due",
            base=date(2025, 1, 1),
            rst=date(2025, 2, 1),
            json=date(2025, 3, 1),
            rst_file="tasks.rst",
        )
        
        # Serialize using the helper pattern
        def _serialize_value(v: Any) -> Any:
            if hasattr(v, "isoformat"):
                return v.isoformat()
            return v
        
        serialized = {
            "task_id": conflict.task_id,
            "field": conflict.field,
            "base": _serialize_value(conflict.base),
            "rst": _serialize_value(conflict.rst),
            "json": _serialize_value(conflict.json),
            "rst_file": conflict.rst_file,
        }
        
        assert serialized["base"] == "2025-01-01"
        assert serialized["rst"] == "2025-02-01"
        assert serialized["json"] == "2025-03-01"
        
        # Verify JSON serializable
        json_str = json.dumps(serialized)
        assert "2025-01-01" in json_str

    def test_list_values_serialized(self):
        """List values in conflicts are properly serialized."""
        conflict = FieldConflict(
            task_id="TASK-001",
            field="tags",
            base=["tag1", "tag2"],
            rst=["tag1", "tag3"],
            json=["tag1", "tag4"],
            rst_file="tasks.rst",
        )
        
        serialized = {
            "task_id": conflict.task_id,
            "field": conflict.field,
            "base": conflict.base,
            "rst": conflict.rst,
            "json": conflict.json,
        }
        
        # Verify JSON serializable
        json_str = json.dumps(serialized)
        assert "tag1" in json_str
        assert "tag3" in json_str
        assert "tag4" in json_str

    def test_none_values_serialized(self):
        """None values in conflicts are properly handled."""
        conflict = FieldConflict(
            task_id="TASK-001",
            field="assignee",
            base=None,
            rst="alice",
            json="bob",
            rst_file="tasks.rst",
        )
        
        serialized = {
            "task_id": conflict.task_id,
            "field": conflict.field,
            "base": conflict.base,
            "rst": conflict.rst,
            "json": conflict.json,
        }
        
        # Verify JSON serializable
        json_str = json.dumps(serialized)
        parsed = json.loads(json_str)
        assert parsed["base"] is None


class TestConflictResolutionSnapshot:
    """Tests for snapshot updates after conflict resolution."""

    def test_snapshot_updated_after_rst_wins(self, store_with_snapshot: JsonTaskStore):
        """Snapshot is updated when RST value is chosen during resolution."""
        task = store_with_snapshot.get_task("TASK-001")
        assert task is not None
        
        # Simulate choosing RST value
        task["title"] = "RST title wins"
        snapshot = create_snapshot(task)
        
        # Update the task's sync snapshot
        task["_sync"]["snapshot"] = snapshot
        store_with_snapshot.update_task("TASK-001", task)
        store_with_snapshot.save()
        
        # Verify snapshot updated
        store_with_snapshot.load()
        updated_task = store_with_snapshot.get_task("TASK-001")
        assert updated_task is not None
        assert updated_task["_sync"]["snapshot"]["title"] == "RST title wins"

    def test_snapshot_updated_after_json_wins(self, store_with_snapshot: JsonTaskStore):
        """Snapshot is updated when JSON value is chosen during resolution."""
        task = store_with_snapshot.get_task("TASK-001")
        assert task is not None
        
        # Simulate choosing JSON value (keeping current JSON value)
        task["title"] = "JSON title wins"
        snapshot = create_snapshot(task)
        
        # Update the task's sync snapshot
        task["_sync"]["snapshot"] = snapshot
        store_with_snapshot.update_task("TASK-001", task)
        store_with_snapshot.save()
        
        # Verify snapshot updated
        store_with_snapshot.load()
        updated_task = store_with_snapshot.get_task("TASK-001")
        assert updated_task is not None
        assert updated_task["_sync"]["snapshot"]["title"] == "JSON title wins"
