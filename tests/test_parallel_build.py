"""Tests for parallel build support."""

from __future__ import annotations

from unittest.mock import MagicMock


class TestParallelBuildDeclaration:
    """Tests for parallel read/write safety declarations."""

    def test_parallel_read_safe_declaration(self):
        """Extension should declare parallel_read_safe."""
        from doxtr_doto import setup

        app = MagicMock()
        app.config = MagicMock()

        result = setup(app)

        assert result.get("parallel_read_safe") is True

    def test_parallel_write_safe_declaration(self):
        """Extension should declare parallel_write_safe."""
        from doxtr_doto import setup

        app = MagicMock()
        app.config = MagicMock()

        result = setup(app)

        assert result.get("parallel_write_safe") is True

    def test_setup_returns_version(self):
        """Extension setup should return version."""
        from doxtr_doto import __version__, setup

        app = MagicMock()
        app.config = MagicMock()

        result = setup(app)

        assert "version" in result
        assert result["version"] == __version__


class TestDotoCollectorMergeOther:
    """Tests for DotoCollector.merge_other method."""

    def test_collector_merge_other_basic(self):
        """DotoCollector.merge_other should merge task data correctly."""
        from doxtr_doto.collectors import DotoCollector, DotoEnvironment, DotoTask

        # Create mock main environment
        main_env = MagicMock()
        main_env.doto_data = DotoEnvironment()
        main_env.doto_data.all_tasks["TASK-001"] = DotoTask(
            id="TASK-001",
            title="Main task",
            docname="main",
        )

        # Create mock other environment
        other_env = MagicMock()
        other_env.doto_data = DotoEnvironment()
        other_env.doto_data.all_tasks["TASK-002"] = DotoTask(
            id="TASK-002",
            title="Other task",
            docname="other",
        )
        other_env.doto_data.tasks_by_doc["other"] = ["TASK-002"]

        # Merge
        collector = DotoCollector()
        collector.merge_other(
            MagicMock(),  # app
            main_env,
            {"other"},  # docnames
            other_env,
        )

        # Verify merge
        assert "TASK-001" in main_env.doto_data.all_tasks
        assert "TASK-002" in main_env.doto_data.all_tasks
        assert "other" in main_env.doto_data.tasks_by_doc

    def test_collector_merge_other_only_specified_docs(self):
        """merge_other should only merge tasks from specified docnames."""
        from doxtr_doto.collectors import DotoCollector, DotoEnvironment, DotoTask

        # Create mock main environment
        main_env = MagicMock()
        main_env.doto_data = DotoEnvironment()

        # Create mock other environment with multiple docs
        other_env = MagicMock()
        other_env.doto_data = DotoEnvironment()
        other_env.doto_data.all_tasks["TASK-002"] = DotoTask(
            id="TASK-002",
            title="Task in doc2",
            docname="doc2",
        )
        other_env.doto_data.all_tasks["TASK-003"] = DotoTask(
            id="TASK-003",
            title="Task in doc3",
            docname="doc3",
        )
        other_env.doto_data.tasks_by_doc["doc2"] = ["TASK-002"]
        other_env.doto_data.tasks_by_doc["doc3"] = ["TASK-003"]

        # Merge only doc2
        collector = DotoCollector()
        collector.merge_other(
            MagicMock(),
            main_env,
            {"doc2"},  # Only doc2
            other_env,
        )

        # Verify only doc2 tasks were merged
        assert "TASK-002" in main_env.doto_data.all_tasks
        assert "TASK-003" not in main_env.doto_data.all_tasks
        assert "doc2" in main_env.doto_data.tasks_by_doc
        assert "doc3" not in main_env.doto_data.tasks_by_doc

    def test_collector_merge_other_empty_docnames(self):
        """merge_other with empty docnames should not merge anything."""
        from doxtr_doto.collectors import DotoCollector, DotoEnvironment, DotoTask

        # Create mock main environment
        main_env = MagicMock()
        main_env.doto_data = DotoEnvironment()

        # Create mock other environment
        other_env = MagicMock()
        other_env.doto_data = DotoEnvironment()
        other_env.doto_data.all_tasks["TASK-002"] = DotoTask(
            id="TASK-002",
            title="Other task",
            docname="other",
        )
        other_env.doto_data.tasks_by_doc["other"] = ["TASK-002"]

        # Merge with empty docnames
        collector = DotoCollector()
        collector.merge_other(
            MagicMock(),
            main_env,
            set(),  # Empty set
            other_env,
        )

        # Verify nothing was merged
        assert "TASK-002" not in main_env.doto_data.all_tasks
        assert "other" not in main_env.doto_data.tasks_by_doc


class TestDotoCollectorClearDoc:
    """Tests for DotoCollector.clear_doc method."""

    def test_collector_clear_doc_removes_tasks(self):
        """clear_doc should remove tasks from specified document."""
        from doxtr_doto.collectors import DotoCollector, DotoEnvironment, DotoTask

        # Create mock environment with tasks
        env = MagicMock()
        env.doto_data = DotoEnvironment()
        env.doto_data.all_tasks["TASK-001"] = DotoTask(
            id="TASK-001",
            title="Task in doc1",
            docname="doc1",
        )
        env.doto_data.all_tasks["TASK-002"] = DotoTask(
            id="TASK-002",
            title="Task in doc2",
            docname="doc2",
        )
        env.doto_data.tasks_by_doc["doc1"] = ["TASK-001"]
        env.doto_data.tasks_by_doc["doc2"] = ["TASK-002"]

        # Clear doc1
        collector = DotoCollector()
        collector.clear_doc(MagicMock(), env, "doc1")

        # Verify doc1 tasks removed, doc2 preserved
        assert "TASK-001" not in env.doto_data.all_tasks
        assert "TASK-002" in env.doto_data.all_tasks
        assert "doc1" not in env.doto_data.tasks_by_doc
        assert "doc2" in env.doto_data.tasks_by_doc

    def test_collector_clear_doc_nonexistent_doc(self):
        """clear_doc should handle nonexistent document gracefully."""
        from doxtr_doto.collectors import DotoCollector, DotoEnvironment, DotoTask

        # Create mock environment
        env = MagicMock()
        env.doto_data = DotoEnvironment()
        env.doto_data.all_tasks["TASK-001"] = DotoTask(
            id="TASK-001",
            title="Task",
            docname="existing",
        )
        env.doto_data.tasks_by_doc["existing"] = ["TASK-001"]

        # Clear nonexistent doc - should not raise
        collector = DotoCollector()
        collector.clear_doc(MagicMock(), env, "nonexistent")

        # Existing data should be unchanged
        assert "TASK-001" in env.doto_data.all_tasks
        assert "existing" in env.doto_data.tasks_by_doc

    def test_collector_clear_doc_multiple_tasks_in_doc(self):
        """clear_doc should remove all tasks from a document."""
        from doxtr_doto.collectors import DotoCollector, DotoEnvironment, DotoTask

        # Create mock environment with multiple tasks in one doc
        env = MagicMock()
        env.doto_data = DotoEnvironment()
        env.doto_data.all_tasks["TASK-001"] = DotoTask(
            id="TASK-001",
            title="Task 1",
            docname="doc1",
        )
        env.doto_data.all_tasks["TASK-002"] = DotoTask(
            id="TASK-002",
            title="Task 2",
            docname="doc1",
        )
        env.doto_data.all_tasks["TASK-003"] = DotoTask(
            id="TASK-003",
            title="Task 3",
            docname="doc1",
        )
        env.doto_data.tasks_by_doc["doc1"] = ["TASK-001", "TASK-002", "TASK-003"]

        # Clear doc1
        collector = DotoCollector()
        collector.clear_doc(MagicMock(), env, "doc1")

        # Verify all tasks removed
        assert "TASK-001" not in env.doto_data.all_tasks
        assert "TASK-002" not in env.doto_data.all_tasks
        assert "TASK-003" not in env.doto_data.all_tasks
        assert "doc1" not in env.doto_data.tasks_by_doc


class TestDotoEnvironment:
    """Tests for DotoEnvironment dataclass."""

    def test_doto_environment_initialization(self):
        """DotoEnvironment should initialize with empty collections."""
        from doxtr_doto.collectors import DotoEnvironment

        env = DotoEnvironment()

        assert env.all_tasks == {}
        assert env.tasks_by_doc == {}
        assert env.pending_rst_updates == {}
        assert env.conflicts == []

    def test_get_doto_env_creates_new(self):
        """get_doto_env should create new environment if none exists."""
        from doxtr_doto.collectors import DotoEnvironment, get_doto_env

        mock_env = MagicMock(spec=[])  # No doto_data attribute

        result = get_doto_env(mock_env)

        assert isinstance(result, DotoEnvironment)
        assert hasattr(mock_env, "doto_data")

    def test_get_doto_env_returns_existing(self):
        """get_doto_env should return existing environment."""
        from doxtr_doto.collectors import DotoEnvironment, get_doto_env

        existing = DotoEnvironment()
        existing.all_tasks["TASK-001"] = MagicMock()

        mock_env = MagicMock()
        mock_env.doto_data = existing

        result = get_doto_env(mock_env)

        assert result is existing
        assert "TASK-001" in result.all_tasks


class TestDotoTask:
    """Tests for DotoTask dataclass."""

    def test_doto_task_defaults(self):
        """DotoTask should have proper defaults."""
        from doxtr_doto.collectors import DotoTask
        from doxtr_doto.constants import DEFAULT_PRIORITY, DEFAULT_STATUS

        task = DotoTask(id="TASK-001", title="Test")

        assert task.id == "TASK-001"
        assert task.title == "Test"
        assert task.priority == DEFAULT_PRIORITY
        assert task.status == DEFAULT_STATUS
        assert task.tags == []
        assert task.depends_on == []
        assert task.archived is False

    def test_doto_task_is_overdue(self):
        """is_overdue should work correctly."""
        from doxtr_doto.collectors import DotoTask

        # Task with past due date and open status
        overdue_task = DotoTask(
            id="TASK-001",
            title="Overdue",
            due="2000-01-01",
            status="open",
        )
        assert overdue_task.is_overdue() is True

        # Task with future due date
        future_task = DotoTask(
            id="TASK-002",
            title="Future",
            due="2099-12-31",
            status="open",
        )
        assert future_task.is_overdue() is False

        # Done task with past due date - not overdue
        done_task = DotoTask(
            id="TASK-003",
            title="Done",
            due="2000-01-01",
            status="done",
        )
        assert done_task.is_overdue() is False

        # Task without due date - not overdue
        no_due_task = DotoTask(
            id="TASK-004",
            title="No due",
            status="open",
        )
        assert no_due_task.is_overdue() is False

    def test_doto_task_to_dict(self):
        """to_dict should serialize task properly."""
        from datetime import datetime

        from doxtr_doto.collectors import DotoTask

        task = DotoTask(
            id="TASK-001",
            title="Test task",
            assignee="alice",
            priority="high",
            status="in-progress",
            due="2026-12-31",
            tags=["feature", "urgent"],
            depends_on=["DEP-001"],
            body="Task body",
            created=datetime(2026, 1, 1, 12, 0, 0),
        )

        result = task.to_dict()

        assert result["title"] == "Test task"
        assert result["assignee"] == "alice"
        assert result["priority"] == "high"
        assert result["status"] == "in-progress"
        assert result["due"] == "2026-12-31"
        assert result["tags"] == ["feature", "urgent"]
        assert result["depends_on"] == ["DEP-001"]
        assert result["body"] == "Task body"
        assert result["created"] == "2026-01-01T12:00:00"

    def test_doto_task_from_dict(self):
        """from_dict should deserialize task properly."""
        from doxtr_doto.collectors import DotoTask

        data = {
            "title": "Test task",
            "assignee": "bob",
            "priority": "critical",
            "status": "blocked",
            "due": "2026-06-15",
            "tags": ["bug"],
            "depends_on": ["DEP-002"],
            "body": "Description",
            "created": "2026-01-15T10:30:00",
            "archived": False,
            "_sync": {
                "rst_file": "tasks.rst",
                "rst_line": 10,
            },
        }

        task = DotoTask.from_dict("TASK-001", data)

        assert task.id == "TASK-001"
        assert task.title == "Test task"
        assert task.assignee == "bob"
        assert task.priority == "critical"
        assert task.status == "blocked"
        assert task.due == "2026-06-15"
        assert task.tags == ["bug"]
        assert task.depends_on == ["DEP-002"]
        assert task.docname == "tasks.rst"
        assert task.lineno == 10
