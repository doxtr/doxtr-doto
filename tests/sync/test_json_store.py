"""Tests for the JSON task store."""

from __future__ import annotations

import json


class TestJsonTaskStore:
    """Test the JsonTaskStore class."""

    def test_create_empty_store(self, tmp_path):
        """Test creating a new empty store."""
        from doxtr_doto.sync.json_store import SCHEMA_VERSION, JsonTaskStore

        json_path = tmp_path / ".doto" / "tasks.json"
        store = JsonTaskStore(json_path)
        store.load()  # Initialize empty data
        store.save()

        assert json_path.exists()

        data = json.loads(json_path.read_text())
        assert data["version"] == SCHEMA_VERSION  # Current schema version (v5)
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
        store.add_task(
            "NEW-001",
            {
                "title": "New task",
                "priority": "high",
                "status": "open",
            },
        )
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

        store.update_task(
            "TASK-001",
            {
                "status": "done",
                "assignee": "bob",
            },
        )
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

    def test_migration_v4_to_v5_backfills_worklogs(self, tmp_path):
        """A pre-existing v4 task without worklogs is backfilled to v5.

        The v4->v5 migration adds an empty ``worklogs`` list to every task so
        the session time-tracking code can rely on the field existing.
        """
        from doxtr_doto.sync.json_store import SCHEMA_VERSION, JsonTaskStore

        json_path = tmp_path / ".doto" / "tasks.json"
        json_path.parent.mkdir(parents=True)
        json_path.write_text(
            json.dumps(
                {
                    "version": 4,
                    "updated": "2024-01-01T00:00:00",
                    "tasks": {
                        "OLD-1": {
                            "title": "Legacy task",
                            "status": "open",
                            "priority": "medium",
                        }
                    },
                    "series": {},
                }
            )
        )

        store = JsonTaskStore(json_path)
        store.load()

        assert store.version == SCHEMA_VERSION == 5
        task = store.get_task("OLD-1")
        assert task is not None
        assert task["worklogs"] == []

    def test_reload_rebinds_cached_repository(self, tmp_path):
        """Reloading a store rebinds its task repository to the fresh data.

        Regression: :meth:`load` reassigned ``_data`` but left the cached
        ``_TaskRepository`` wrapping the previous ``_data`` dict. After a
        reload, reads/writes went to the stale dict while :meth:`save`
        persisted the freshly loaded ``_data`` - so edits made through a
        different store instance for the same path were silently dropped (the
        root cause of the focus-timer worklog-loss bug). After the fix a
        reloaded store must observe the on-disk state and persist edits made
        on top of it.
        """
        from doxtr_doto.sync.json_store import JsonTaskStore

        json_path = tmp_path / ".doto" / "tasks.json"
        json_path.parent.mkdir(parents=True)
        json_path.write_text(
            json.dumps(
                {
                    "version": 5,
                    "updated": "2024-01-01T00:00:00",
                    "tasks": {"T-1": {"title": "One", "status": "open", "worklogs": []}},
                    "series": {},
                }
            )
        )

        store = JsonTaskStore(json_path)
        # Populate the cached repository against the original data.
        assert store.get_task("T-1") is not None

        # A second instance adds a task and persists it to the same path.
        other = JsonTaskStore(json_path)
        other.add_task("T-2", {"title": "Two", "status": "open", "worklogs": []})
        other.save()

        # Reloading the first instance must observe T-2 (the repository is
        # rebound to the freshly loaded data, not the stale wrapper).
        store.load()
        assert store.get_task("T-2") is not None

        # Editing on top of the reloaded state and saving must not drop T-2.
        store.update_task("T-1", {"status": "done"})
        store.save()
        on_disk = json.loads(json_path.read_text())["tasks"]
        assert set(on_disk) == {"T-1", "T-2"}
        assert on_disk["T-1"]["status"] == "done"


class TestRstOnlyTaskPersistence:
    """Regression tests for persisting RST-only tasks to tasks.json.

    An RST-only directive (a bare ".. doto::" without an explicit ":id:",
    which receives an auto-generated "{docname}-L{lineno}" ID) must be
    written to tasks.json during sync. The create_in_json branch previously
    used update_task(), which is update-only and silently no-ops for a task
    that is not yet in the store, so these tasks were never persisted.
    """

    def test_rst_only_task_is_created_in_json(self, tmp_path):
        """A new RST-only task is persisted to tasks.json after a sync.

        This exercises _apply_merge_result() for the create_in_json branch,
        which is the path taken when a task exists in RST but not yet in JSON.
        Before the fix this asserted nothing was written; now the task must
        be present in the store and survive a save/reload round-trip.
        """
        from doxtr_doto.sync import _apply_merge_result
        from doxtr_doto.sync.json_store import JsonTaskStore
        from doxtr_doto.sync.merge import sync_task

        json_path = tmp_path / ".doto" / "tasks.json"
        store = JsonTaskStore(json_path)
        store.load()  # Initialize empty store

        # Auto-generated ID for a bare directive: "{docname}-L{lineno}".
        task_id = "tasks-L5"
        # Mirrors DotoTask.to_sync_dict(): includes the "id" key that the
        # sync algorithm (and directive reconstruction) relies on.
        rst_current = {
            "id": task_id,
            "title": "A bare directive without an explicit id",
            "priority": "medium",
            "status": "open",
            "_rst_file": "tasks.rst",
            "_rst_line": 5,
        }

        # Task is only in RST, not yet in JSON -> create_in_json result.
        result = sync_task(
            task_id=task_id,
            rst_current=rst_current,
            json_task=None,
            rst_file="tasks.rst",
            rst_line=5,
        )
        assert result.create_in_json is True

        # app is only dereferenced when queueing RST updates, which does not
        # happen for a create_in_json-only result, so None is safe here.
        _apply_merge_result(
            result=result,
            task_id=task_id,
            store=store,
            app=None,
            rst_file="tasks.rst",
            rst_line=5,
            rst_current=rst_current,
            sync_data={"rst_updates": []},
        )

        # Must be in the live store after the merge is applied.
        task = store.get_task(task_id)
        assert task is not None, "RST-only task was not created in the store"
        assert task["title"] == "A bare directive without an explicit id"
        assert task["_sync"]["rst_file"] == "tasks.rst"
        assert task["_sync"]["rst_line"] == 5

        # Must survive persistence to tasks.json and reload.
        store.save()
        reloaded = JsonTaskStore(json_path)
        reloaded.load()
        persisted = reloaded.get_task(task_id)
        assert persisted is not None, "RST-only task was not persisted to tasks.json"
        assert persisted["title"] == "A bare directive without an explicit id"
