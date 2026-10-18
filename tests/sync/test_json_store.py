"""Tests for the JSON task store."""

from __future__ import annotations

import json


class TestJsonTaskStore:
    """Test the JsonTaskStore class."""

    def test_delete_task_prunes_owning_series_link(self, tmp_path):
        """Deleting a series task removes it from the series' ``task_ids``.

        The pruning lives in the store so every delete path (the CLI
        ``doto delete`` verb and the TUI wrapper alike) keeps the series'
        occurrence count consistent.
        """
        from doxtr_doto.sync.json_store import JsonTaskStore

        json_path = tmp_path / ".doto" / "tasks.json"
        json_path.parent.mkdir(parents=True)
        json_path.write_text(
            json.dumps(
                {
                    "version": 6,
                    "updated": "2024-01-01T00:00:00",
                    "tasks": {
                        "S-1": {"title": "W1", "series_id": "SER-1", "status": "open"},
                        "S-2": {"title": "W2", "series_id": "SER-1", "status": "open"},
                    },
                    "series": {
                        "SER-1": {
                            "title_template": "W",
                            "pattern": {"type": "weekly", "interval": 1, "weekday": 0},
                            "start_date": "2026-01-05",
                            "end_date": "2026-01-12",
                            "task_ids": ["S-1", "S-2"],
                            "task_defaults": {},
                            "created": "2024-01-01T00:00:00",
                        }
                    },
                }
            )
        )
        store = JsonTaskStore(json_path)
        store.load()

        assert store.delete_task("S-1") is True

        series = store.get_series("SER-1")
        assert series is not None
        assert series["task_ids"] == ["S-2"]
        assert len(store.get_tasks_in_series("SER-1")) == 1

    def test_delete_standalone_task_leaves_series_untouched(self, tmp_path):
        """A task with no ``series_id`` deletes without touching any series."""
        from doxtr_doto.sync.json_store import JsonTaskStore

        json_path = tmp_path / ".doto" / "tasks.json"
        json_path.parent.mkdir(parents=True)
        json_path.write_text(
            json.dumps(
                {
                    "version": 6,
                    "updated": "2024-01-01T00:00:00",
                    "tasks": {"A-1": {"title": "Solo", "status": "open"}},
                    "series": {},
                }
            )
        )
        store = JsonTaskStore(json_path)
        store.load()
        assert store.delete_task("A-1") is True
        assert store.get_task("A-1") is None

    def test_delete_parent_clears_child_parent_link(self, tmp_path):
        """Deleting a parent clears the dangling ``parent`` on its children.

        Symmetric with the series prune: ``parent`` stores the deleted task's
        bare local id, so after the delete no surviving task may still point
        at it (otherwise the detail pane would show ``Parent: <deleted-id>``).
        """
        from doxtr_doto.sync.json_store import JsonTaskStore

        json_path = tmp_path / ".doto" / "tasks.json"
        json_path.parent.mkdir(parents=True)
        json_path.write_text(
            json.dumps(
                {
                    "version": 6,
                    "updated": "2024-01-01T00:00:00",
                    "tasks": {
                        "P-1": {"title": "Parent", "status": "open"},
                        "C-1": {"title": "Child", "status": "open", "parent": "P-1"},
                        "C-2": {"title": "Child2", "status": "open", "parent": "P-1"},
                        "O-1": {"title": "Other", "status": "open", "parent": "X-9"},
                    },
                    "series": {},
                }
            )
        )
        store = JsonTaskStore(json_path)
        store.load()

        assert store.delete_task("P-1") is True

        assert store.get_task("P-1") is None
        assert store.get_task("C-1")["parent"] is None
        assert store.get_task("C-2")["parent"] is None
        # An unrelated child's parent link is left untouched.
        assert store.get_task("O-1")["parent"] == "X-9"

    def test_create_empty_store(self, tmp_path):
        """Test creating a new empty store."""
        from doxtr_doto.sync.json_store import SCHEMA_VERSION, JsonTaskStore

        json_path = tmp_path / ".doto" / "tasks.json"
        store = JsonTaskStore(json_path)
        store.load()  # Initialize empty data
        store.save()

        assert json_path.exists()

        data = json.loads(json_path.read_text())
        assert data["version"] == SCHEMA_VERSION  # written at the current schema version
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

        assert store.version == SCHEMA_VERSION
        task = store.get_task("OLD-1")
        assert task is not None
        assert task["worklogs"] == []

    def test_migration_v5_to_v6_backfills_estimate(self, tmp_path):
        """A pre-existing v5 task without estimate is backfilled to v6.

        The v5->v6 migration adds an ``estimate`` key (``None`` = unset) to
        every task so the calendar-sync projection and display code can rely
        on the field existing.
        """
        from doxtr_doto.sync.json_store import SCHEMA_VERSION, JsonTaskStore

        json_path = tmp_path / ".doto" / "tasks.json"
        json_path.parent.mkdir(parents=True)
        json_path.write_text(
            json.dumps(
                {
                    "version": 5,
                    "updated": "2024-01-01T00:00:00",
                    "tasks": {
                        "OLD-1": {
                            "title": "Legacy task",
                            "status": "open",
                            "priority": "medium",
                            "worklogs": [],
                        }
                    },
                    "series": {},
                }
            )
        )

        store = JsonTaskStore(json_path)
        store.load()

        assert (
            store.version == SCHEMA_VERSION == 6
        )  # literal pinned to the v5->v6 migration under test
        task = store.get_task("OLD-1")
        assert task is not None
        assert task["estimate"] is None

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


class TestCompletionTimestamp:
    """Central ``completed_at`` stamping in ``_TaskRepository.update``.

    Every write path funnels through ``update_task``, so these verify the
    single chokepoint stamps/clears ``completed_at`` correctly and leaves
    unrelated updates alone.
    """

    def _store(self, tmp_path):
        import json as _json

        from doxtr_doto.sync.json_store import JsonTaskStore

        json_path = tmp_path / ".doto" / "tasks.json"
        json_path.parent.mkdir(parents=True)
        json_path.write_text(
            _json.dumps(
                {
                    "version": 6,
                    "updated": "2024-01-01T00:00:00",
                    "tasks": {
                        "T-1": {"title": "A", "status": "open"},
                    },
                }
            )
        )
        store = JsonTaskStore(json_path)
        store.load()
        return store

    def test_transition_to_done_stamps_completed_at(self, tmp_path):
        store = self._store(tmp_path)
        store.update_task("T-1", {"status": "done"})
        task = store.get_task("T-1")
        assert task is not None
        assert task.get("completed_at")  # a non-empty ISO timestamp

    def test_move_away_from_done_clears_completed_at(self, tmp_path):
        store = self._store(tmp_path)
        store.update_task("T-1", {"status": "done"})
        assert store.get_task("T-1").get("completed_at")
        store.update_task("T-1", {"status": "open"})
        assert store.get_task("T-1").get("completed_at") is None

    def test_recompleting_restamps_fresh_date(self, tmp_path):
        store = self._store(tmp_path)
        store.update_task("T-1", {"status": "done"})
        store.update_task("T-1", {"status": "open"})
        store.update_task("T-1", {"status": "done"})
        assert store.get_task("T-1").get("completed_at")

    def test_unrelated_update_does_not_touch_completed_at(self, tmp_path):
        store = self._store(tmp_path)
        store.update_task("T-1", {"status": "done"})
        stamped = store.get_task("T-1").get("completed_at")
        # An update with no status key must leave completed_at untouched.
        store.update_task("T-1", {"priority": "high"})
        assert store.get_task("T-1").get("completed_at") == stamped

    def test_redundant_same_status_done_keeps_original_stamp(self, tmp_path):
        store = self._store(tmp_path)
        store.update_task("T-1", {"status": "done"})
        stamped = store.get_task("T-1").get("completed_at")
        # Writing status=done again while already done must not re-stamp.
        store.update_task("T-1", {"status": "done", "priority": "low"})
        assert store.get_task("T-1").get("completed_at") == stamped

    def test_legacy_done_without_stamp_gets_stamped_on_update(self, tmp_path):
        store = self._store(tmp_path)
        # Simulate a legacy done task created before completed_at existed.
        store.update_task("T-1", {"status": "done"})
        # Remove the stamp to mimic old data, then write status=done again.
        store.get_task("T-1")["completed_at"] = None
        store.update_task("T-1", {"status": "done"})
        assert store.get_task("T-1").get("completed_at")

    def test_non_done_update_on_non_done_task_is_untouched(self, tmp_path):
        store = self._store(tmp_path)
        store.update_task("T-1", {"status": "in-progress"})
        assert store.get_task("T-1").get("completed_at") is None


class TestParentField:
    """The ``parent`` task-hierarchy field and its cycle-prevention guard.

    Covers the ``parent`` link added to :class:`TaskData`: it is None-seeded on
    :meth:`JsonTaskStore.add_task`, written through the normal ``update_task``
    path, and guarded against self/cyclic assignment by
    :func:`doxtr_doto.sync.json_store.would_create_cycle`.
    """

    def _store(self, tmp_path):
        from doxtr_doto.sync.json_store import JsonTaskStore

        json_path = tmp_path / ".doto" / "tasks.json"
        json_path.parent.mkdir(parents=True)
        store = JsonTaskStore(json_path)
        store.load()
        return store

    def test_add_task_seeds_parent_none(self, tmp_path):
        """A freshly added task carries ``parent`` explicitly set to None."""
        store = self._store(tmp_path)
        store.add_task("T-1", {"title": "A"})
        task = store.get_task("T-1")
        assert task is not None
        assert "parent" in task
        assert task["parent"] is None

    def test_update_task_sets_parent(self, tmp_path):
        """Setting ``parent`` via ``update_task`` stamps + persists the field."""
        store = self._store(tmp_path)
        store.add_task("CHILD", {"title": "child"})
        store.add_task("PARENT", {"title": "parent"})
        store.update_task("CHILD", {"parent": "PARENT"})
        store.save()

        from doxtr_doto.sync.json_store import JsonTaskStore

        reloaded = JsonTaskStore(store.path)
        reloaded.load()
        assert reloaded.get_task("CHILD")["parent"] == "PARENT"
        # The parent task itself is unaffected (still a top-level task).
        assert reloaded.get_task("PARENT")["parent"] is None

    def test_would_create_cycle_rejects_self_parent(self):
        from doxtr_doto.sync.json_store import would_create_cycle

        tasks = {"A": {"title": "A"}}
        assert would_create_cycle(tasks, "A", "A") is True

    def test_would_create_cycle_rejects_direct_cycle(self):
        """A -> B already; making B's parent A would close A -> B -> A."""
        from doxtr_doto.sync.json_store import would_create_cycle

        # A's parent is B. Setting B's parent to A would create A<->B.
        tasks = {"A": {"title": "A", "parent": "B"}, "B": {"title": "B"}}
        assert would_create_cycle(tasks, "B", "A") is True

    def test_would_create_cycle_rejects_transitive_cycle(self):
        """A -> B -> C already; making C's parent A closes the longer loop."""
        from doxtr_doto.sync.json_store import would_create_cycle

        tasks = {
            "A": {"title": "A", "parent": "B"},
            "B": {"title": "B", "parent": "C"},
            "C": {"title": "C"},
        }
        assert would_create_cycle(tasks, "C", "A") is True

    def test_would_create_cycle_accepts_valid_parent(self):
        from doxtr_doto.sync.json_store import would_create_cycle

        tasks = {"A": {"title": "A"}, "B": {"title": "B"}}
        assert would_create_cycle(tasks, "A", "B") is False

    def test_would_create_cycle_tolerates_missing_parent_task(self):
        """An unknown candidate parent id is treated as non-cycling."""
        from doxtr_doto.sync.json_store import would_create_cycle

        tasks = {"A": {"title": "A"}}
        assert would_create_cycle(tasks, "A", "GHOST") is False

    def test_would_create_cycle_survives_preexisting_loop(self):
        """A malformed stored cycle does not spin the walk forever."""
        from doxtr_doto.sync.json_store import would_create_cycle

        # X -> Y -> X is a pre-existing (malformed) loop; querying a new,
        # unrelated child must terminate and report no *new* cycle.
        tasks = {
            "X": {"title": "X", "parent": "Y"},
            "Y": {"title": "Y", "parent": "X"},
            "Z": {"title": "Z"},
        }
        assert would_create_cycle(tasks, "Z", "X") is False
