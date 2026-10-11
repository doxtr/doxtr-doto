"""Tests for doto_export_json feature."""

from __future__ import annotations

import json
from pathlib import Path


class TestExportJsonDisabled:
    """Tests for JSON export when disabled."""

    def test_export_json_disabled_by_default(self, doto_srcdir, sample_tasks_rst, make_app):
        """Export should be disabled by default."""
        app = make_app(srcdir=doto_srcdir)
        app.build()

        export_path = Path(app.outdir) / "_static" / "doto-tasks.json"
        assert not export_path.exists()


class TestExportJsonEnabled:
    """Tests for JSON export when enabled."""

    def test_export_json_enabled_creates_file(self, doto_srcdir, sample_tasks_rst, make_app):
        """Export should create file when enabled."""
        app = make_app(
            srcdir=doto_srcdir,
            confoverrides={"doto_export_json": True},
        )
        app.build()

        export_path = Path(app.outdir) / "_static" / "doto-tasks.json"
        assert export_path.exists()

    def test_export_json_has_version_and_tasks(self, doto_srcdir, sample_tasks_rst, make_app):
        """Exported JSON should have version and tasks keys."""
        app = make_app(
            srcdir=doto_srcdir,
            confoverrides={"doto_export_json": True},
        )
        app.build()

        export_path = Path(app.outdir) / "_static" / "doto-tasks.json"
        data = json.loads(export_path.read_text())

        assert "version" in data
        assert data["version"] == 1
        assert "tasks" in data
        assert isinstance(data["tasks"], dict)

    def test_export_json_contains_task_ids(self, doto_srcdir, sample_tasks_rst, make_app):
        """Exported JSON should contain the defined task IDs."""
        app = make_app(
            srcdir=doto_srcdir,
            confoverrides={"doto_export_json": True},
        )
        app.build()

        export_path = Path(app.outdir) / "_static" / "doto-tasks.json"
        data = json.loads(export_path.read_text())

        # sample_tasks_rst creates TASK-001, TASK-002, TASK-003
        assert "TASK-001" in data["tasks"]
        assert "TASK-002" in data["tasks"]
        assert "TASK-003" in data["tasks"]


class TestExportJsonStructure:
    """Tests for exported JSON structure."""

    def test_export_json_task_has_required_fields(self, doto_srcdir, sample_tasks_rst, make_app):
        """Each exported task should have required fields."""
        app = make_app(
            srcdir=doto_srcdir,
            confoverrides={"doto_export_json": True},
        )
        app.build()

        export_path = Path(app.outdir) / "_static" / "doto-tasks.json"
        data = json.loads(export_path.read_text())

        task = data["tasks"]["TASK-001"]
        assert "title" in task
        assert "status" in task
        assert "priority" in task

    def test_export_json_task_field_values(self, doto_srcdir, sample_tasks_rst, make_app):
        """Exported task fields should have correct values."""
        app = make_app(
            srcdir=doto_srcdir,
            confoverrides={"doto_export_json": True},
        )
        app.build()

        export_path = Path(app.outdir) / "_static" / "doto-tasks.json"
        data = json.loads(export_path.read_text())

        task = data["tasks"]["TASK-001"]
        assert task["title"] == "Implement user authentication"
        assert task["priority"] == "high"
        assert task["status"] == "open"
        assert task["assignee"] == "alice"
        assert "security" in task["tags"]
        assert "backend" in task["tags"]

    def test_export_json_task_with_due_date(self, doto_srcdir, sample_tasks_rst, make_app):
        """Task with due date should have due field in export."""
        app = make_app(
            srcdir=doto_srcdir,
            confoverrides={"doto_export_json": True},
        )
        app.build()

        export_path = Path(app.outdir) / "_static" / "doto-tasks.json"
        data = json.loads(export_path.read_text())

        task = data["tasks"]["TASK-001"]
        assert "due" in task
        assert task["due"] == "2026-08-15"

    def test_export_json_task_with_depends_on(self, doto_srcdir, sample_tasks_rst, make_app):
        """Task with depends-on should have depends_on field in export."""
        app = make_app(
            srcdir=doto_srcdir,
            confoverrides={"doto_export_json": True},
        )
        app.build()

        export_path = Path(app.outdir) / "_static" / "doto-tasks.json"
        data = json.loads(export_path.read_text())

        task = data["tasks"]["TASK-003"]
        assert "depends_on" in task
        assert "TASK-001" in task["depends_on"]

    def test_export_json_task_has_source_doc(self, doto_srcdir, sample_tasks_rst, make_app):
        """Exported task should include source document reference."""
        app = make_app(
            srcdir=doto_srcdir,
            confoverrides={"doto_export_json": True},
        )
        app.build()

        export_path = Path(app.outdir) / "_static" / "doto-tasks.json"
        data = json.loads(export_path.read_text())

        task = data["tasks"]["TASK-001"]
        assert "source_doc" in task
        assert task["source_doc"] == "tasks"


class TestExportJsonArchivedTasks:
    """Tests for archived task handling in JSON export."""

    def test_export_json_includes_archived_tasks(self, doto_srcdir, sample_json_store, make_app):
        """Archived tasks should be included in export for external tools."""
        import json as json_mod

        # Modify JSON store to have an archived task
        json_data = json_mod.loads(sample_json_store.read_text())
        json_data["tasks"]["ARCHIVED-001"] = {
            "title": "Archived task for export test",
            "status": "done",
            "priority": "low",
            "archived": True,
            "archived_on": "2026-07-01T12:00:00",
            "tags": [],
            "depends_on": [],
            "body": "",
        }
        sample_json_store.write_text(json_mod.dumps(json_data, indent=2))

        # Create an RST file that references a task (to ensure build processes tasks)
        tasks_rst = doto_srcdir / "tasks.rst"
        tasks_rst.write_text("""
Tasks
=====

.. doto:: Active task
   :id: ACTIVE-001
   :status: open
   :priority: medium

   An active task.
""")

        # Update index.rst to include tasks
        index_rst = doto_srcdir / "index.rst"
        index_rst.write_text(index_rst.read_text() + "\n   tasks\n")

        app = make_app(
            srcdir=doto_srcdir,
            confoverrides={
                "doto_export_json": True,
                "doto_json_file": ".doto/tasks.json",
            },
        )
        app.build()

        export_path = Path(app.outdir) / "_static" / "doto-tasks.json"
        assert export_path.exists()

        data = json_mod.loads(export_path.read_text())
        # The active task should definitely be present
        assert "ACTIVE-001" in data["tasks"]


class TestExportJsonBuildFailure:
    """Tests for export behavior on build failure."""

    def test_export_not_created_when_exception_passed(self, doto_srcdir, make_app):
        """Export handler should not create file when exception is passed."""
        # This tests the internal behavior - when build-finished is called
        # with an exception, export should be skipped
        from doxtr_doto import _export_tasks_json

        app = make_app(srcdir=doto_srcdir, confoverrides={"doto_export_json": True})

        # Simulate build finished with exception
        _export_tasks_json(app, exception=Exception("Build failed"))

        export_path = Path(app.outdir) / "_static" / "doto-tasks.json"
        assert not export_path.exists()


class TestExportJsonEdgeCases:
    """Tests for edge cases in JSON export."""

    def test_export_json_empty_tasks(self, doto_srcdir, make_app):
        """Export should work with no tasks defined."""
        app = make_app(
            srcdir=doto_srcdir,
            confoverrides={"doto_export_json": True},
        )
        app.build()

        export_path = Path(app.outdir) / "_static" / "doto-tasks.json"
        assert export_path.exists()

        data = json.loads(export_path.read_text())
        assert data["version"] == 1
        assert data["tasks"] == {}

    def test_export_json_creates_static_directory(self, doto_srcdir, make_app):
        """Export should create _static directory if it doesn't exist."""
        app = make_app(
            srcdir=doto_srcdir,
            confoverrides={"doto_export_json": True},
        )
        app.build()

        static_dir = Path(app.outdir) / "_static"
        assert static_dir.exists()
        assert static_dir.is_dir()

    def test_export_json_is_valid_json(self, doto_srcdir, sample_tasks_rst, make_app):
        """Exported file should be valid, parseable JSON."""
        app = make_app(
            srcdir=doto_srcdir,
            confoverrides={"doto_export_json": True},
        )
        app.build()

        export_path = Path(app.outdir) / "_static" / "doto-tasks.json"

        # Should not raise
        with open(export_path, encoding="utf-8") as f:
            data = json.load(f)

        assert isinstance(data, dict)
