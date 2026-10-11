"""Tests for auto-archive functionality."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest


class TestShouldArchive:
    """Test the should_archive function."""

    def test_archive_done_status(self):
        """Test that done status triggers archiving."""
        from doxtr_doto.transforms.archive import should_archive

        class MockTask:
            status = "done"
            updated = datetime.now() - timedelta(days=10)

        task = MockTask()
        assert should_archive(task, {"done"}, 0) is True

    def test_no_archive_open_status(self):
        """Test that open status does not trigger archiving."""
        from doxtr_doto.transforms.archive import should_archive

        class MockTask:
            status = "open"
            updated = datetime.now()

        task = MockTask()
        assert should_archive(task, {"done"}, 0) is False

    def test_no_archive_in_progress(self):
        """Test that in-progress status does not trigger archiving."""
        from doxtr_doto.transforms.archive import should_archive

        class MockTask:
            status = "in-progress"
            updated = datetime.now()

        task = MockTask()
        assert should_archive(task, {"done"}, 0) is False

    def test_archive_after_days_not_met(self):
        """Test archiving is delayed when days threshold not met."""
        from doxtr_doto.transforms.archive import should_archive

        class MockTask:
            status = "done"
            updated = datetime.now() - timedelta(days=2)

        task = MockTask()
        # Requires 7 days, only 2 have passed
        assert should_archive(task, {"done"}, 7) is False

    def test_archive_after_days_met(self):
        """Test archiving proceeds when days threshold is met."""
        from doxtr_doto.transforms.archive import should_archive

        class MockTask:
            status = "done"
            updated = datetime.now() - timedelta(days=10)

        task = MockTask()
        # Requires 7 days, 10 have passed
        assert should_archive(task, {"done"}, 7) is True

    def test_multiple_archive_statuses(self):
        """Test archiving with multiple status triggers."""
        from doxtr_doto.transforms.archive import should_archive

        archive_statuses = {"done", "cancelled", "wontfix"}

        class DoneTask:
            status = "done"
            updated = datetime.now()

        class CancelledTask:
            status = "cancelled"
            updated = datetime.now()

        class OpenTask:
            status = "open"
            updated = datetime.now()

        assert should_archive(DoneTask(), archive_statuses, 0) is True
        assert should_archive(CancelledTask(), archive_statuses, 0) is True
        assert should_archive(OpenTask(), archive_statuses, 0) is False

    def test_archive_no_updated_date(self):
        """Test archiving when task has no updated date."""
        from doxtr_doto.transforms.archive import should_archive

        class MockTask:
            status = "done"
            updated = None

        task = MockTask()
        # With archive_after_days = 0, should archive immediately
        assert should_archive(task, {"done"}, 0) is True


class TestReopenTask:
    """Test the reopen_task function."""

    def test_reopen_archived_task(self, tmp_path):
        """Test reopening an archived task."""
        from doxtr_doto.sync.json_store import JsonTaskStore
        from doxtr_doto.transforms.archive import reopen_task

        json_path = tmp_path / ".doto" / "tasks.json"
        json_path.parent.mkdir(parents=True)

        store = JsonTaskStore(json_path)
        store.add_task(
            "TASK-001",
            {
                "title": "Archived task",
                "status": "done",
                "archived": True,
                "archived_on": "2026-07-01T10:00:00",
                "_sync": {
                    "rst_file": "tasks.rst",
                    "snapshot": {"title": "Archived task"},
                },
            },
        )
        store.save()

        reopen_task("TASK-001", store)
        store.save()

        # Reload and verify
        store2 = JsonTaskStore(json_path)
        store2.load()

        task = store2.get_task("TASK-001")
        assert task["archived"] is False
        assert task["archived_on"] is None
        assert task["status"] == "open"

    def test_reopen_with_custom_status(self, tmp_path):
        """Test reopening task with custom status."""
        from doxtr_doto.sync.json_store import JsonTaskStore
        from doxtr_doto.transforms.archive import reopen_task

        json_path = tmp_path / ".doto" / "tasks.json"
        json_path.parent.mkdir(parents=True)

        store = JsonTaskStore(json_path)
        store.add_task(
            "TASK-002",
            {
                "title": "Another archived task",
                "status": "done",
                "archived": True,
                "archived_on": "2026-07-01T10:00:00",
            },
        )
        store.save()

        reopen_task("TASK-002", store, new_status="in-progress")
        store.save()

        store2 = JsonTaskStore(json_path)
        store2.load()

        task = store2.get_task("TASK-002")
        assert task["status"] == "in-progress"

    def test_reopen_with_target_file(self, tmp_path):
        """Test reopening task to a specific file."""
        from doxtr_doto.sync.json_store import JsonTaskStore
        from doxtr_doto.transforms.archive import reopen_task

        json_path = tmp_path / ".doto" / "tasks.json"
        json_path.parent.mkdir(parents=True)

        store = JsonTaskStore(json_path)
        store.add_task(
            "TASK-003",
            {
                "title": "Task to relocate",
                "status": "done",
                "archived": True,
                "archived_on": "2026-07-01T10:00:00",
            },
        )
        store.save()

        reopen_task("TASK-003", store, target_file="new_tasks.rst")
        store.save()

        store2 = JsonTaskStore(json_path)
        store2.load()

        task = store2.get_task("TASK-003")
        assert task["_sync"]["rst_file"] == "new_tasks.rst"

    def test_reopen_nonexistent_task(self, tmp_path):
        """Test reopening a nonexistent task raises error."""
        from doxtr_doto.sync.json_store import JsonTaskStore
        from doxtr_doto.transforms.archive import reopen_task

        json_path = tmp_path / ".doto" / "tasks.json"
        json_path.parent.mkdir(parents=True)

        store = JsonTaskStore(json_path)
        store.save()

        with pytest.raises(ValueError) as excinfo:
            reopen_task("NONEXISTENT", store)
        assert "not found" in str(excinfo.value)

    def test_reopen_non_archived_task(self, tmp_path):
        """Test reopening a non-archived task raises error."""
        from doxtr_doto.sync.json_store import JsonTaskStore
        from doxtr_doto.transforms.archive import reopen_task

        json_path = tmp_path / ".doto" / "tasks.json"
        json_path.parent.mkdir(parents=True)

        store = JsonTaskStore(json_path)
        store.add_task(
            "TASK-ACTIVE",
            {
                "title": "Active task",
                "status": "open",
                "archived": False,
            },
        )
        store.save()

        with pytest.raises(ValueError) as excinfo:
            reopen_task("TASK-ACTIVE", store)
        assert "not archived" in str(excinfo.value)


class TestAutoArchiveIntegration:
    """Integration tests for auto-archive with Sphinx builds."""

    def test_auto_archive_enabled_by_default(self, doto_srcdir, make_app, sample_tasks_rst):
        """Test that auto-archive is enabled by default."""
        app = make_app(srcdir=doto_srcdir)

        # Default config should have auto_archive enabled.
        assert app.config.doto_auto_archive is True

    def test_auto_archive_can_be_disabled(self, doto_srcdir, make_app, sample_tasks_rst):
        """Test that auto-archive can be explicitly turned off."""
        app = make_app(
            srcdir=doto_srcdir,
            confoverrides={"doto_auto_archive": False},
        )

        assert app.config.doto_auto_archive is False

    def test_archive_config_values(self, doto_srcdir, make_app):
        """Test archive configuration values."""
        app = make_app(
            srcdir=doto_srcdir,
            confoverrides={
                "doto_auto_archive": True,
                "doto_archive_after_days": 7,
                "doto_archive_statuses": ["done", "cancelled"],
            },
        )

        assert app.config.doto_auto_archive is True
        assert app.config.doto_archive_after_days == 7
        assert app.config.doto_archive_statuses == ["done", "cancelled"]


class TestVirtualArchiveDocRendering:
    """Tests for virtual archive document rendering."""

    def test_read_virtual_doc_injects_content(self, doto_srcdir, make_app):
        """Test that read_virtual_doc injects virtual document content."""
        from doxtr_doto.builders.archive_doc import read_virtual_doc

        app = make_app(
            srcdir=doto_srcdir,
            confoverrides={"doto_auto_archive": True},
        )

        # Manually set up virtual doc content
        app.env.doto_virtual_docs = {"archive": "Virtual Archive Content\n======================\n"}

        source = ["Original content"]
        read_virtual_doc(app, "archive", source)

        assert source[0] == "Virtual Archive Content\n======================\n"

    def test_read_virtual_doc_ignores_non_virtual(self, doto_srcdir, make_app):
        """Test that read_virtual_doc ignores non-virtual documents."""
        from doxtr_doto.builders.archive_doc import read_virtual_doc

        app = make_app(
            srcdir=doto_srcdir,
            confoverrides={"doto_auto_archive": True},
        )

        # Set up virtual docs without the requested docname
        app.env.doto_virtual_docs = {"archive": "Archive content"}

        original_content = "Original content"
        source = [original_content]
        read_virtual_doc(app, "other_doc", source)

        # Content should remain unchanged
        assert source[0] == original_content

    def test_archive_doc_rendered_with_archived_tasks(self, doto_srcdir, make_app):
        """Test that archive document is rendered when archived tasks exist."""
        import json
        from pathlib import Path

        # Create a tasks.rst with a done task
        tasks_rst = doto_srcdir / "tasks.rst"
        tasks_rst.write_text("""
Tasks
=====

.. doto:: Completed task
   :id: TASK-DONE
   :status: done

   This task is done.
""")

        # Add tasks to index toctree
        index_rst = doto_srcdir / "index.rst"
        index_rst.write_text(index_rst.read_text() + "\n   tasks\n   archive\n")

        # Create archive.rst placeholder (Sphinx needs the file to exist)
        archive_rst = doto_srcdir / "archive.rst"
        archive_rst.write_text("placeholder")

        # Create JSON store with an archived task
        json_path = doto_srcdir / ".doto" / "tasks.json"
        json_path.write_text(
            json.dumps(
                {
                    "version": 2,
                    "updated": "2026-07-26T10:00:00",
                    "tasks": {
                        "TASK-ARCHIVED": {
                            "title": "Archived completed task",
                            "status": "done",
                            "priority": "medium",
                            "tags": [],
                            "depends_on": [],
                            "body": "This task was archived.",
                            "created": "2026-07-01T09:00:00",
                            "updated": "2026-07-10T10:00:00",
                            "archived": True,
                            "archived_on": "2026-07-15T10:00:00",
                            "_sync": {"rst_file": None, "snapshot": None},
                        }
                    },
                },
                indent=2,
            )
        )

        app = make_app(
            srcdir=doto_srcdir,
            confoverrides={
                "doto_auto_archive": True,
                "doto_archive_doc": "archive",
            },
        )

        # Build the documentation
        app.build()

        # Check that archive.html was created
        archive_html = Path(app.outdir) / "archive.html"
        assert archive_html.exists(), "archive.html should be created"

        # Verify the content contains archive-related text
        html_content = archive_html.read_text()
        assert "Archived Tasks" in html_content or "archived" in html_content.lower()

    def test_get_archive_doc_content_returns_none_when_not_set(self):
        """Test get_archive_doc_content returns None when no virtual docs."""
        from doxtr_doto.builders.archive_doc import get_archive_doc_content

        class MockEnv:
            pass

        env = MockEnv()
        assert get_archive_doc_content(env, "archive") is None

    def test_get_archive_doc_content_returns_content_when_set(self):
        """Test get_archive_doc_content returns content when available."""
        from doxtr_doto.builders.archive_doc import get_archive_doc_content

        class MockEnv:
            doto_virtual_docs = {"archive": "Test content"}

        env = MockEnv()
        assert get_archive_doc_content(env, "archive") == "Test content"
        assert get_archive_doc_content(env, "other") is None


class TestAutoArchiveEndToEnd:
    """End-to-end: auto-archive-on removes from RST and preserves in JSON."""

    def test_done_task_removed_from_rst_and_archived_in_json(self, doto_srcdir, make_app):
        """A done task is stripped from its RST file and archived in JSON with
        a restore anchor, with auto-archive enabled (the new default)."""
        import json

        tasks_rst = doto_srcdir / "tasks.rst"
        tasks_rst.write_text(
            "Tasks\n"
            "=====\n"
            "\n"
            "Intro paragraph above the task.\n"
            "\n"
            ".. doto:: Finished work\n"
            "   :id: TASK-DONE\n"
            "   :status: done\n"
            "\n"
            "   This is complete.\n"
            "\n"
            "Trailing content.\n"
        )

        index_rst = doto_srcdir / "index.rst"
        index_rst.write_text(index_rst.read_text() + "\n   tasks\n")

        app = make_app(
            srcdir=doto_srcdir,
            confoverrides={"doto_auto_archive": True},
        )
        app.build()

        # The directive is removed from the RST file.
        new_rst = tasks_rst.read_text()
        assert ".. doto:: Finished work" not in new_rst
        assert "Intro paragraph above the task." in new_rst

        # The task is archived in JSON with a restore anchor.
        json_path = doto_srcdir / ".doto" / "tasks.json"
        data = json.loads(json_path.read_text())
        task = data["tasks"]["TASK-DONE"]
        assert task["archived"] is True
        archive_meta = task["_sync"]["_archive"]
        assert archive_meta["original_rst_file"] == "tasks"
        assert "Intro paragraph above the task." in archive_meta["preceding_lines"]

    def test_disabled_keeps_task_in_rst(self, doto_srcdir, make_app):
        """With auto-archive disabled, a done task stays in its RST file."""
        tasks_rst = doto_srcdir / "tasks.rst"
        tasks_rst.write_text(
            "Tasks\n=====\n\n.. doto:: Finished work\n   :id: TASK-DONE2\n   :status: done\n"
        )
        index_rst = doto_srcdir / "index.rst"
        index_rst.write_text(index_rst.read_text() + "\n   tasks\n")

        app = make_app(
            srcdir=doto_srcdir,
            confoverrides={"doto_auto_archive": False},
        )
        app.build()

        assert ".. doto:: Finished work" in tasks_rst.read_text()


class TestArchivePageJsonSteadyState:
    """Regression: the archive page must list archived tasks on builds AFTER
    the one that archived them, sourcing from the JSON store (not all_tasks).
    """

    def test_archive_page_lists_task_after_second_build(self, doto_srcdir, make_app):
        """Build a project where a done task is auto-archived (removed from RST,
        archived in JSON) on the first build, then build AGAIN and confirm the
        archive HTML lists the archived task id/title and NOT 'No archived
        tasks'. This is the steady-state regression: on the second build the
        directive no longer exists in any RST file, so all_tasks is empty for
        that task and only the JSON store knows about it.
        """
        import json
        from pathlib import Path

        tasks_rst = doto_srcdir / "tasks.rst"
        tasks_rst.write_text(
            "Project Tasks\n"
            "=============\n"
            "\n"
            "Intro paragraph above the task.\n"
            "\n"
            ".. doto:: Finished work\n"
            "   :id: TASK-ARCH\n"
            "   :status: done\n"
            "\n"
            "   This is complete.\n"
            "\n"
            "Trailing content.\n"
        )

        index_rst = doto_srcdir / "index.rst"
        index_rst.write_text(index_rst.read_text() + "\n   tasks\n   archive\n")

        # Sphinx needs the archive doc file to exist to add it to the build;
        # the builder fills it in via inject_archive_doc.
        archive_rst = doto_srcdir / "archive.rst"
        archive_rst.write_text("placeholder")

        # First build: auto-archive removes the directive from RST and archives
        # the task in JSON.
        app1 = make_app(
            srcdir=doto_srcdir,
            confoverrides={
                "doto_auto_archive": True,
                "doto_archive_doc": "archive",
            },
        )
        app1.build()

        # The directive is gone from the RST file now.
        assert ".. doto:: Finished work" not in tasks_rst.read_text()
        # And the task is archived in the JSON store.
        json_path = doto_srcdir / ".doto" / "tasks.json"
        data = json.loads(json_path.read_text())
        assert data["tasks"]["TASK-ARCH"]["archived"] is True

        # Second build: steady state. The directive is no longer in RST, so the
        # archive page must still render the task from the JSON store.
        app2 = make_app(
            srcdir=doto_srcdir,
            confoverrides={
                "doto_auto_archive": True,
                "doto_archive_doc": "archive",
            },
        )
        app2.build()

        archive_html = Path(app2.outdir) / "archive.html"
        assert archive_html.exists(), "archive.html should be created"
        html = archive_html.read_text()

        assert "TASK-ARCH" in html, (
            "archived task id must appear on the archive page after the second (steady-state) build"
        )
        assert "No archived tasks" not in html
