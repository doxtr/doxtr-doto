"""Tests for the JSON task store."""

from __future__ import annotations

import json
import pytest
from pathlib import Path


class TestJsonTaskStore:
    """Test the JsonTaskStore class."""
    
    def test_create_empty_store(self, tmp_path):
        """Test creating a new empty store."""
        from doxtr_doto.sync.json_store import JsonTaskStore, SCHEMA_VERSION
        
        json_path = tmp_path / ".doto" / "tasks.json"
        store = JsonTaskStore(json_path)
        store.load()  # Initialize empty data
        store.save()
        
        assert json_path.exists()
        
        data = json.loads(json_path.read_text())
        assert data["version"] == SCHEMA_VERSION  # Now v3
        assert data["tasks"] == {}
    
    def test_load_existing_store(self, sample_json_store):
        """Test loading an existing store."""
        from doxtr_doto.sync.json_store import JsonTaskStore
        
        store = JsonTaskStore(sample_json_store)
        store.load()
        
        task = store.get_task("TASK-001")
        assert task is not None
        assert task["title"] == "Implement user authentication"
        assert task["assignee"] == "alice"
    
    def test_add_task(self, tmp_path):
        """Test adding a new task."""
        from doxtr_doto.sync.json_store import JsonTaskStore
        
        json_path = tmp_path / ".doto" / "tasks.json"
        json_path.parent.mkdir(parents=True)
        
        store = JsonTaskStore(json_path)
        store.load()  # Initialize
        store.add_task("NEW-001", {
            "title": "New task",
            "priority": "high",
            "status": "open",
        })
        store.save()
        
        # Reload and verify
        store2 = JsonTaskStore(json_path)
        store2.load()
        
        task = store2.get_task("NEW-001")
        assert task is not None
        assert task["title"] == "New task"
        assert task["priority"] == "high"
    
    def test_update_task(self, sample_json_store):
        """Test updating an existing task."""
        from doxtr_doto.sync.json_store import JsonTaskStore
        
        store = JsonTaskStore(sample_json_store)
        store.load()
        
        store.update_task("TASK-001", {
            "status": "done",
            "assignee": "bob",
        })
        store.save()
        
        # Reload and verify
        store2 = JsonTaskStore(sample_json_store)
        store2.load()
        
        task = store2.get_task("TASK-001")
        assert task["status"] == "done"
        assert task["assignee"] == "bob"
        # Other fields should be preserved
        assert task["title"] == "Implement user authentication"
    
    def test_delete_task(self, sample_json_store):
        """Test deleting a task."""
        from doxtr_doto.sync.json_store import JsonTaskStore
        
        store = JsonTaskStore(sample_json_store)
        store.load()
        
        store.delete_task("TASK-001")
        store.save()
        
        # Reload and verify
        store2 = JsonTaskStore(sample_json_store)
        store2.load()
        
        assert store2.get_task("TASK-001") is None
    
    def test_get_snapshot(self, sample_json_store):
        """Test getting task snapshot."""
        from doxtr_doto.sync.json_store import JsonTaskStore
        
        store = JsonTaskStore(sample_json_store)
        store.load()
        
        snapshot = store.get_snapshot("TASK-001")
        assert snapshot is not None
        assert snapshot["priority"] == "high"
    
    def test_update_snapshot(self, sample_json_store):
        """Test updating task snapshot."""
        from doxtr_doto.sync.json_store import JsonTaskStore
        
        store = JsonTaskStore(sample_json_store)
        store.load()
        
        new_snapshot = {"priority": "critical", "status": "done"}
        store.update_snapshot("TASK-001", new_snapshot, "newhash123")
        store.save()
        
        # Reload and verify
        store2 = JsonTaskStore(sample_json_store)
        store2.load()
        
        task = store2.get_task("TASK-001")
        assert task["_sync"]["snapshot"] == new_snapshot
        assert task["_sync"]["rst_hash"] == "newhash123"
    
    def test_list_all_tasks(self, sample_json_store):
        """Test listing all tasks."""
        from doxtr_doto.sync.json_store import JsonTaskStore
        
        store = JsonTaskStore(sample_json_store)
        store.load()
        
        # Use the tasks property (dict) instead of list_tasks()
        tasks = store.tasks
        assert len(tasks) >= 1
        assert "TASK-001" in tasks
    
    def test_nonexistent_task(self, sample_json_store):
        """Test getting a nonexistent task."""
        from doxtr_doto.sync.json_store import JsonTaskStore
        
        store = JsonTaskStore(sample_json_store)
        store.load()
        
        task = store.get_task("NONEXISTENT")
        assert task is None
