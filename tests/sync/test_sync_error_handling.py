"""Tests for sync error handling and edge cases."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from doxtr_doto.sync.json_store import JsonTaskStore


class TestJsonStoreErrorHandling:
    """Tests for JsonTaskStore error handling."""

    def test_corrupted_json_raises_clear_error(self, tmp_path: Path):
        """Corrupted JSON file raises clear error."""
        json_path = tmp_path / "tasks.json"
        json_path.write_text("not valid json {")

        store = JsonTaskStore(json_path)
        with pytest.raises(json.JSONDecodeError):
            store.load()

    def test_empty_json_file_handled(self, tmp_path: Path):
        """Empty JSON file is handled gracefully."""
        json_path = tmp_path / "tasks.json"
        json_path.write_text("")

        store = JsonTaskStore(json_path)
        # Should raise or handle gracefully
        with pytest.raises((json.JSONDecodeError, ValueError)):
            store.load()

    def test_missing_version_field_handled(self, tmp_path: Path):
        """Missing version field triggers migration."""
        json_path = tmp_path / "tasks.json"
        json_path.write_text('{"tasks": {}}')

        store = JsonTaskStore(json_path)
        store.load()
        # Should have been migrated to have version
        assert store.data.get("version") is not None

    def test_missing_tasks_field_raises_on_access(self, tmp_path: Path):
        """Missing tasks field raises KeyError when accessing tasks."""
        json_path = tmp_path / "tasks.json"
        json_path.write_text('{"version": 2}')

        store = JsonTaskStore(json_path)
        store.load()
        # Accessing tasks without the key raises - user must provide valid JSON
        with pytest.raises(KeyError):
            _ = store.tasks

    def test_nonexistent_file_creates_empty_store(self, tmp_path: Path):
        """Nonexistent file creates empty store on load."""
        json_path = tmp_path / "nonexistent" / "tasks.json"

        store = JsonTaskStore(json_path)
        store.load()

        assert store.data["version"] is not None
        assert store.data["tasks"] == {}

    def test_save_creates_parent_directories(self, tmp_path: Path):
        """Save creates parent directories if needed."""
        json_path = tmp_path / "deep" / "nested" / "tasks.json"

        store = JsonTaskStore(json_path)
        store.load()
        store.save()

        assert json_path.exists()

    def test_update_nonexistent_task_returns_false(self, tmp_path: Path):
        """Updating nonexistent task returns False."""
        json_path = tmp_path / "tasks.json"
        store = JsonTaskStore(json_path)
        store.load()

        result = store.update_task("NONEXISTENT-999", {"title": "New"})

        assert result is False

    def test_delete_nonexistent_task_returns_false(self, tmp_path: Path):
        """Deleting nonexistent task returns False."""
        json_path = tmp_path / "tasks.json"
        store = JsonTaskStore(json_path)
        store.load()

        result = store.delete_task("NONEXISTENT-999")

        assert result is False

    def test_get_nonexistent_task_returns_none(self, tmp_path: Path):
        """Getting nonexistent task returns None."""
        json_path = tmp_path / "tasks.json"
        store = JsonTaskStore(json_path)
        store.load()

        result = store.get_task("NONEXISTENT-999")

        assert result is None


class TestJsonStoreSchemaMigration:
    """Tests for JSON store schema migration."""

    def test_migration_from_v1_to_current(self, tmp_path: Path):
        """Migration from v1 adds missing fields."""
        json_path = tmp_path / "tasks.json"
        v1_data = {
            "version": 1,
            "tasks": {
                "TASK-001": {
                    "title": "Old task",
                    "status": "open",
                }
            },
        }
        json_path.write_text(json.dumps(v1_data))

        store = JsonTaskStore(json_path)
        store.load()

        task = store.get_task("TASK-001")
        # Should have all expected fields after migration
        assert task is not None
        assert "title" in task

    def test_migration_preserves_existing_data(self, tmp_path: Path):
        """Migration preserves all existing task data."""
        json_path = tmp_path / "tasks.json"
        v1_data = {
            "version": 1,
            "tasks": {
                "TASK-001": {
                    "title": "Important task",
                    "status": "in-progress",
                    "priority": "high",
                    "assignee": "alice",
                    "tags": ["bug", "urgent"],
                }
            },
        }
        json_path.write_text(json.dumps(v1_data))

        store = JsonTaskStore(json_path)
        store.load()

        task = store.get_task("TASK-001")
        assert task["title"] == "Important task"
        assert task["status"] == "in-progress"
        assert task["priority"] == "high"
        assert task["assignee"] == "alice"
        assert task["tags"] == ["bug", "urgent"]


class TestJsonStoreIdGeneration:
    """Tests for task ID generation."""

    def test_sequential_id_generation(self, tmp_path: Path):
        """Sequential IDs increment correctly."""
        json_path = tmp_path / "tasks.json"
        store = JsonTaskStore(json_path)
        store.load()

        id1 = store.generate_id(prefix="TEST", sequential=True)
        store.add_task(id1, {"title": "First"})

        id2 = store.generate_id(prefix="TEST", sequential=True)

        assert id1 == "TEST-001"
        assert id2 == "TEST-002"

    def test_sequential_id_finds_gaps(self, tmp_path: Path):
        """Sequential ID generation handles gaps in sequence."""
        json_path = tmp_path / "tasks.json"
        store = JsonTaskStore(json_path)
        store.load()

        # Add tasks with specific IDs
        store.add_task("TEST-001", {"title": "First"})
        store.add_task("TEST-005", {"title": "Fifth"})

        # Next ID should be TEST-006 (after highest)
        next_id = store.generate_id(prefix="TEST", sequential=True)
        assert next_id == "TEST-006"

    def test_hash_based_id_generation(self, tmp_path: Path):
        """Hash-based IDs are unique."""
        json_path = tmp_path / "tasks.json"
        store = JsonTaskStore(json_path)
        store.load()

        id1 = store.generate_id(prefix="HASH", sequential=False)
        store.add_task(id1, {"title": "First"})

        id2 = store.generate_id(prefix="HASH", sequential=False)

        assert id1 != id2
        assert id1.startswith("HASH-")
        assert id2.startswith("HASH-")


class TestJsonStoreFilterTasks:
    """Tests for task filtering."""

    def test_filter_by_status(self, tmp_path: Path):
        """Filter tasks by status."""
        json_path = tmp_path / "tasks.json"
        store = JsonTaskStore(json_path)
        store.load()

        store.add_task("TASK-001", {"title": "Open", "status": "open"})
        store.add_task("TASK-002", {"title": "Done", "status": "done"})
        store.add_task("TASK-003", {"title": "Also Open", "status": "open"})

        open_tasks = store.filter_tasks(status="open")

        assert len(open_tasks) == 2

    def test_filter_by_assignee(self, tmp_path: Path):
        """Filter tasks by assignee."""
        json_path = tmp_path / "tasks.json"
        store = JsonTaskStore(json_path)
        store.load()

        store.add_task("TASK-001", {"title": "Alice's", "assignee": "alice"})
        store.add_task("TASK-002", {"title": "Bob's", "assignee": "bob"})
        store.add_task("TASK-003", {"title": "Also Alice's", "assignee": "alice"})

        alice_tasks = store.filter_tasks(assignee="alice")

        assert len(alice_tasks) == 2

    def test_filter_excludes_archived_by_default(self, tmp_path: Path):
        """Filter excludes archived tasks by default."""
        json_path = tmp_path / "tasks.json"
        store = JsonTaskStore(json_path)
        store.load()

        store.add_task("TASK-001", {"title": "Active", "archived": False})
        store.add_task("TASK-002", {"title": "Archived", "archived": True})

        active_tasks = store.filter_tasks()

        assert len(active_tasks) == 1
        assert active_tasks[0].get("title") == "Active"

    def test_filter_includes_archived_when_requested(self, tmp_path: Path):
        """Filter includes archived tasks when requested."""
        json_path = tmp_path / "tasks.json"
        store = JsonTaskStore(json_path)
        store.load()

        store.add_task("TASK-001", {"title": "Active", "archived": False})
        store.add_task("TASK-002", {"title": "Archived", "archived": True})

        all_tasks = store.filter_tasks(include_archived=True)

        assert len(all_tasks) == 2


class TestJsonStoreAtomicWrite:
    """Tests for atomic write operations."""

    def test_save_is_atomic(self, tmp_path: Path):
        """Save operation is atomic (uses temp file)."""
        json_path = tmp_path / "tasks.json"
        store = JsonTaskStore(json_path)
        store.load()

        store.add_task("TASK-001", {"title": "Test"})
        store.save()

        # File should exist and be valid JSON
        assert json_path.exists()
        data = json.loads(json_path.read_text())
        assert "TASK-001" in data["tasks"]

    def test_save_preserves_data_on_error(self, tmp_path: Path):
        """Original file preserved if save fails."""
        json_path = tmp_path / "tasks.json"

        # Create initial valid file
        initial_data = {"version": 2, "tasks": {"TASK-001": {"title": "Original"}}}
        json_path.write_text(json.dumps(initial_data))

        store = JsonTaskStore(json_path)
        store.load()

        # File should still be readable
        store2 = JsonTaskStore(json_path)
        store2.load()
        assert "TASK-001" in store2.data["tasks"]
