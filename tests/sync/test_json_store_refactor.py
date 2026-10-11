"""Tests for JsonTaskStore refactoring (Story 1.5).

These tests verify that the extracted helper classes work correctly
and that the JsonTaskStore delegation maintains backward compatibility.
"""

from __future__ import annotations

import pytest

from doxtr_doto.sync.json_store import (
    JsonTaskStore,
    SeriesData,
    TaskData,
    _IdGenerator,
    _SeriesRepository,
    _TaskRepository,
)


class TestIdGenerator:
    """Tests for _IdGenerator helper class."""

    def test_sequential_id_starts_at_001(self):
        """Sequential ID starts at 001 when no existing IDs."""
        gen = _IdGenerator(set())
        assert gen.sequential("DOTO") == "DOTO-001"

    def test_sequential_id_increments(self):
        """Sequential ID increments from highest existing."""
        gen = _IdGenerator({"DOTO-001", "DOTO-002", "DOTO-005"})
        assert gen.sequential("DOTO") == "DOTO-006"

    def test_sequential_id_ignores_other_prefixes(self):
        """Sequential ID ignores IDs with different prefixes."""
        gen = _IdGenerator({"OTHER-100", "DOTO-002"})
        assert gen.sequential("DOTO") == "DOTO-003"

    def test_sequential_id_handles_non_numeric_suffix(self):
        """Sequential ID handles IDs with non-numeric suffixes gracefully."""
        gen = _IdGenerator({"DOTO-abc", "DOTO-002"})
        assert gen.sequential("DOTO") == "DOTO-003"

    def test_hash_based_id_format(self):
        """Hash-based ID has correct format."""
        gen = _IdGenerator(set())
        new_id = gen.hash_based("DOTO")
        assert new_id.startswith("DOTO-")
        assert len(new_id) >= 11  # DOTO- + at least 6 chars

    def test_hash_based_id_unique(self):
        """Hash-based ID avoids collisions."""
        gen = _IdGenerator(set())
        id1 = gen.hash_based("DOTO")
        # Add generated ID to existing set for next generation
        gen2 = _IdGenerator({id1})
        id2 = gen2.hash_based("DOTO")
        assert id1 != id2


class TestTaskRepository:
    """Tests for _TaskRepository helper class."""

    @pytest.fixture
    def tasks_dict(self) -> dict[str, TaskData]:
        """Create a tasks dictionary for testing."""
        return {}

    @pytest.fixture
    def repo(self, tasks_dict) -> _TaskRepository:
        """Create a task repository instance."""
        return _TaskRepository(tasks_dict)

    def test_get_nonexistent_returns_none(self, repo):
        """Get returns None for nonexistent task."""
        assert repo.get("DOTO-999") is None

    def test_add_and_get(self, repo, tasks_dict):
        """Add task and retrieve it."""
        repo.add("DOTO-001", {"title": "Test task"})
        task = repo.get("DOTO-001")
        assert task is not None
        assert task["title"] == "Test task"
        assert "DOTO-001" in tasks_dict

    def test_add_sets_defaults(self, repo):
        """Add task sets default values."""
        repo.add("DOTO-001", {"title": "Test"})
        task = repo.get("DOTO-001")
        assert task["priority"] == "medium"
        assert task["status"] == "open"
        assert task["archived"] is False
        assert task["tags"] == []
        assert "_sync" in task

    def test_update_existing_task(self, repo):
        """Update existing task returns True."""
        repo.add("DOTO-001", {"title": "Original"})
        result = repo.update("DOTO-001", {"title": "Updated"})
        assert result is True
        assert repo.get("DOTO-001")["title"] == "Updated"

    def test_update_nonexistent_task(self, repo):
        """Update nonexistent task returns False."""
        result = repo.update("DOTO-999", {"title": "Updated"})
        assert result is False

    def test_update_merges_sync_metadata(self, repo):
        """Update merges _sync dict instead of replacing."""
        repo.add("DOTO-001", {"title": "Test"})
        repo.update("DOTO-001", {"_sync": {"rst_file": "index.rst"}})
        task = repo.get("DOTO-001")
        assert task["_sync"]["rst_file"] == "index.rst"
        assert task["_sync"]["rst_hash"] is None  # Original value preserved

    def test_delete_existing_task(self, repo):
        """Delete existing task returns True."""
        repo.add("DOTO-001", {"title": "Test"})
        result = repo.delete("DOTO-001")
        assert result is True
        assert repo.get("DOTO-001") is None

    def test_delete_nonexistent_task(self, repo):
        """Delete nonexistent task returns False."""
        result = repo.delete("DOTO-999")
        assert result is False

    def test_get_all(self, repo):
        """Get all returns the tasks dictionary."""
        repo.add("DOTO-001", {"title": "Task 1"})
        repo.add("DOTO-002", {"title": "Task 2"})
        all_tasks = repo.get_all()
        assert len(all_tasks) == 2
        assert "DOTO-001" in all_tasks
        assert "DOTO-002" in all_tasks

    def test_iter_active_excludes_archived(self, repo):
        """iter_active excludes archived tasks."""
        repo.add("DOTO-001", {"title": "Active"})
        repo.add("DOTO-002", {"title": "Archived", "archived": True})
        active = list(repo.iter_active())
        assert len(active) == 1
        assert active[0][0] == "DOTO-001"

    def test_iter_archived_includes_only_archived(self, repo):
        """iter_archived includes only archived tasks."""
        repo.add("DOTO-001", {"title": "Active"})
        repo.add("DOTO-002", {"title": "Archived", "archived": True})
        archived = list(repo.iter_archived())
        assert len(archived) == 1
        assert archived[0][0] == "DOTO-002"


class TestSeriesRepository:
    """Tests for _SeriesRepository helper class."""

    @pytest.fixture
    def series_dict(self) -> dict[str, SeriesData]:
        """Create a series dictionary for testing."""
        return {}

    @pytest.fixture
    def repo(self, series_dict) -> _SeriesRepository:
        """Create a series repository instance."""
        return _SeriesRepository(series_dict)

    def test_get_nonexistent_returns_none(self, repo):
        """Get returns None for nonexistent series."""
        assert repo.get("SER-999") is None

    def test_add_and_get(self, repo, series_dict):
        """Add series and retrieve it."""
        repo.add(
            "SER-001",
            title_template="Weekly {date}",
            pattern={"freq": "weekly"},
            start_date="2024-01-01",
            end_date="2024-12-31",
            task_ids=["DOTO-001"],
        )
        series = repo.get("SER-001")
        assert series is not None
        assert series["title_template"] == "Weekly {date}"
        assert "SER-001" in series_dict

    def test_add_sets_timestamps(self, repo):
        """Add series sets created and updated timestamps."""
        repo.add(
            "SER-001",
            title_template="Test",
            pattern={},
            start_date="2024-01-01",
            end_date="2024-12-31",
            task_ids=[],
        )
        series = repo.get("SER-001")
        assert "created" in series
        assert "updated" in series

    def test_update_existing_series(self, repo):
        """Update existing series returns True."""
        repo.add(
            "SER-001",
            title_template="Original",
            pattern={},
            start_date="2024-01-01",
            end_date="2024-12-31",
            task_ids=[],
        )
        result = repo.update("SER-001", {"title_template": "Updated"})
        assert result is True
        assert repo.get("SER-001")["title_template"] == "Updated"

    def test_update_nonexistent_series(self, repo):
        """Update nonexistent series returns False."""
        result = repo.update("SER-999", {"title_template": "Updated"})
        assert result is False

    def test_delete_existing_series(self, repo):
        """Delete existing series returns True."""
        repo.add(
            "SER-001",
            title_template="Test",
            pattern={},
            start_date="2024-01-01",
            end_date="2024-12-31",
            task_ids=[],
        )
        result = repo.delete("SER-001")
        assert result is True
        assert repo.get("SER-001") is None

    def test_delete_nonexistent_series(self, repo):
        """Delete nonexistent series returns False."""
        result = repo.delete("SER-999")
        assert result is False

    def test_get_all(self, repo):
        """Get all returns the series dictionary."""
        repo.add(
            "SER-001",
            title_template="S1",
            pattern={},
            start_date="2024-01-01",
            end_date="2024-12-31",
            task_ids=[],
        )
        repo.add(
            "SER-002",
            title_template="S2",
            pattern={},
            start_date="2024-01-01",
            end_date="2024-12-31",
            task_ids=[],
        )
        all_series = repo.get_all()
        assert len(all_series) == 2

    def test_generate_id_starts_at_001(self, repo):
        """Generate ID starts at 001 when no existing series."""
        assert repo.generate_id() == "SER-001"

    def test_generate_id_increments(self, repo):
        """Generate ID increments from highest existing."""
        repo.add(
            "SER-001",
            title_template="S1",
            pattern={},
            start_date="2024-01-01",
            end_date="2024-12-31",
            task_ids=[],
        )
        repo.add(
            "SER-005",
            title_template="S5",
            pattern={},
            start_date="2024-01-01",
            end_date="2024-12-31",
            task_ids=[],
        )
        assert repo.generate_id() == "SER-006"


class TestJsonTaskStoreDelegation:
    """Tests verifying JsonTaskStore delegates to helper classes correctly."""

    @pytest.fixture
    def store(self, tmp_path) -> JsonTaskStore:
        """Create a JsonTaskStore instance."""
        return JsonTaskStore(tmp_path / "tasks.json")

    def test_helper_classes_are_exposed(self):
        """Helper classes can be imported from the module."""
        from doxtr_doto.sync.json_store import _IdGenerator, _SeriesRepository, _TaskRepository

        assert _IdGenerator is not None
        assert _TaskRepository is not None
        assert _SeriesRepository is not None

    def test_store_initializes_repos_lazily(self, store):
        """Store initializes repository helpers lazily."""
        # Before any access, repos should be None
        assert store._tasks_repo is None
        assert store._series_repo is None

    def test_store_initializes_repos_on_access(self, store):
        """Store initializes repository helpers on first access."""
        # Access triggers lazy initialization
        _ = store.get_task("DOTO-001")
        assert store._tasks_repo is not None

    def test_add_task_uses_repo(self, store):
        """add_task delegates to _TaskRepository."""
        store.add_task("DOTO-001", {"title": "Test"})
        # Verify through public API
        task = store.get_task("DOTO-001")
        assert task is not None
        assert task["title"] == "Test"

    def test_update_task_uses_repo(self, store):
        """update_task delegates to _TaskRepository."""
        store.add_task("DOTO-001", {"title": "Original"})
        result = store.update_task("DOTO-001", {"title": "Updated"})
        assert result is True
        assert store.get_task("DOTO-001")["title"] == "Updated"

    def test_delete_task_uses_repo(self, store):
        """delete_task delegates to _TaskRepository."""
        store.add_task("DOTO-001", {"title": "Test"})
        result = store.delete_task("DOTO-001")
        assert result is True
        assert store.get_task("DOTO-001") is None

    def test_iter_active_tasks(self, store):
        """iter_active_tasks iterates only active tasks."""
        store.add_task("DOTO-001", {"title": "Active"})
        store.add_task("DOTO-002", {"title": "Archived", "archived": True})
        active = list(store.iter_active_tasks())
        assert len(active) == 1
        assert active[0][0] == "DOTO-001"

    def test_iter_archived_tasks(self, store):
        """iter_archived_tasks iterates only archived tasks."""
        store.add_task("DOTO-001", {"title": "Active"})
        store.add_task("DOTO-002", {"title": "Archived", "archived": True})
        archived = list(store.iter_archived_tasks())
        assert len(archived) == 1
        assert archived[0][0] == "DOTO-002"

    def test_generate_id_uses_id_generator(self, store):
        """generate_id uses _IdGenerator."""
        id1 = store.generate_id()
        assert id1 == "DOTO-001"
        store.add_task(id1, {"title": "Task 1"})
        id2 = store.generate_id()
        assert id2 == "DOTO-002"

    def test_generate_id_hash_based(self, store):
        """generate_id with sequential=False uses hash-based generation."""
        new_id = store.generate_id(sequential=False)
        assert new_id.startswith("DOTO-")
        assert len(new_id) >= 11

    def test_add_series_uses_serepo(self, store):
        """add_series delegates to _SeriesRepository."""
        store.add_series(
            "SER-001",
            title_template="Weekly",
            pattern={"freq": "weekly"},
            start_date="2024-01-01",
            end_date="2024-12-31",
            task_ids=[],
        )
        series = store.get_series("SER-001")
        assert series is not None
        assert series["title_template"] == "Weekly"

    def test_update_series_uses_serepo(self, store):
        """update_series delegates to _SeriesRepository."""
        store.add_series(
            "SER-001",
            title_template="Original",
            pattern={},
            start_date="2024-01-01",
            end_date="2024-12-31",
            task_ids=[],
        )
        result = store.update_series("SER-001", {"title_template": "Updated"})
        assert result is True
        assert store.get_series("SER-001")["title_template"] == "Updated"

    def test_delete_series_uses_serepo(self, store):
        """delete_series delegates to _SeriesRepository."""
        store.add_series(
            "SER-001",
            title_template="Test",
            pattern={},
            start_date="2024-01-01",
            end_date="2024-12-31",
            task_ids=[],
        )
        success, deleted = store.delete_series("SER-001")
        assert success is True
        assert store.get_series("SER-001") is None

    def test_delete_series_with_tasks(self, store):
        """delete_series with delete_tasks=True removes associated tasks."""
        store.add_task("DOTO-001", {"title": "Task in series"})
        store.add_series(
            "SER-001",
            title_template="Test",
            pattern={},
            start_date="2024-01-01",
            end_date="2024-12-31",
            task_ids=["DOTO-001"],
        )
        success, deleted = store.delete_series("SER-001", delete_tasks=True)
        assert success is True
        assert deleted == ["DOTO-001"]
        assert store.get_task("DOTO-001") is None

    def test_generate_series_id_uses_serepo(self, store):
        """generate_series_id delegates to _SeriesRepository."""
        id1 = store.generate_series_id()
        assert id1 == "SER-001"


class TestBackwardCompatibility:
    """Tests ensuring the refactoring maintains backward compatibility."""

    @pytest.fixture
    def store(self, tmp_path) -> JsonTaskStore:
        """Create a JsonTaskStore instance."""
        return JsonTaskStore(tmp_path / "tasks.json")

    def test_tasks_property_still_works(self, store):
        """The tasks property returns the task dictionary."""
        store.add_task("DOTO-001", {"title": "Test"})
        tasks = store.tasks
        assert isinstance(tasks, dict)
        assert "DOTO-001" in tasks

    def test_data_property_still_works(self, store):
        """The data property returns the full JSON data."""
        store.add_task("DOTO-001", {"title": "Test"})
        data = store.data
        assert "version" in data
        assert "tasks" in data
        assert "series" in data

    def test_get_all_tasks_still_works(self, store):
        """get_all_tasks returns all tasks."""
        store.add_task("DOTO-001", {"title": "Task 1"})
        store.add_task("DOTO-002", {"title": "Task 2"})
        all_tasks = store.get_all_tasks()
        assert len(all_tasks) == 2

    def test_iter_tasks_still_works(self, store):
        """iter_tasks with include_archived parameter still works."""
        store.add_task("DOTO-001", {"title": "Active"})
        store.add_task("DOTO-002", {"title": "Archived", "archived": True})

        # Without archived
        active = list(store.iter_tasks(include_archived=False))
        assert len(active) == 1

        # With archived
        all_tasks = list(store.iter_tasks(include_archived=True))
        assert len(all_tasks) == 2

    def test_get_active_tasks_still_works(self, store):
        """get_active_tasks returns only non-archived tasks."""
        store.add_task("DOTO-001", {"title": "Active"})
        store.add_task("DOTO-002", {"title": "Archived", "archived": True})
        active = store.get_active_tasks()
        assert len(active) == 1
        assert "DOTO-001" in active

    def test_get_archived_tasks_still_works(self, store):
        """get_archived_tasks returns only archived tasks."""
        store.add_task("DOTO-001", {"title": "Active"})
        store.add_task("DOTO-002", {"title": "Archived", "archived": True})
        archived = store.get_archived_tasks()
        assert len(archived) == 1
        assert "DOTO-002" in archived

    def test_save_and_load_roundtrip(self, store):
        """Save and load maintains data integrity."""
        store.add_task("DOTO-001", {"title": "Test task"})
        store.add_series(
            "SER-001",
            title_template="Weekly",
            pattern={"freq": "weekly"},
            start_date="2024-01-01",
            end_date="2024-12-31",
            task_ids=["DOTO-001"],
        )
        store.save()

        # Load in a new store instance
        store2 = JsonTaskStore(store.path)
        store2.load()

        assert store2.get_task("DOTO-001")["title"] == "Test task"
        assert store2.get_series("SER-001")["title_template"] == "Weekly"
