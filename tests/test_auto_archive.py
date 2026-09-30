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
        from doxtr_doto.transforms.archive import reopen_task
        from doxtr_doto.sync.json_store import JsonTaskStore
        
        json_path = tmp_path / ".doto" / "tasks.json"
        json_path.parent.mkdir(parents=True)
        
        store = JsonTaskStore(json_path)
        store.add_task("TASK-001", {
            "title": "Archived task",
            "status": "done",
            "archived": True,
            "archived_on": "2026-07-01T10:00:00",
            "_sync": {
                "rst_file": "tasks.rst",
                "snapshot": {"title": "Archived task"},
            },
        })
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
        from doxtr_doto.transforms.archive import reopen_task
        from doxtr_doto.sync.json_store import JsonTaskStore
        
        json_path = tmp_path / ".doto" / "tasks.json"
        json_path.parent.mkdir(parents=True)
        
        store = JsonTaskStore(json_path)
        store.add_task("TASK-002", {
            "title": "Another archived task",
            "status": "done",
            "archived": True,
            "archived_on": "2026-07-01T10:00:00",
        })
        store.save()
        
        reopen_task("TASK-002", store, new_status="in-progress")
        store.save()
        
        store2 = JsonTaskStore(json_path)
        store2.load()
        
        task = store2.get_task("TASK-002")
        assert task["status"] == "in-progress"
    
    def test_reopen_with_target_file(self, tmp_path):
        """Test reopening task to a specific file."""
        from doxtr_doto.transforms.archive import reopen_task
        from doxtr_doto.sync.json_store import JsonTaskStore
        
        json_path = tmp_path / ".doto" / "tasks.json"
        json_path.parent.mkdir(parents=True)
        
        store = JsonTaskStore(json_path)
        store.add_task("TASK-003", {
            "title": "Task to relocate",
            "status": "done",
            "archived": True,
            "archived_on": "2026-07-01T10:00:00",
        })
        store.save()
        
        reopen_task("TASK-003", store, target_file="new_tasks.rst")
        store.save()
        
        store2 = JsonTaskStore(json_path)
        store2.load()
        
        task = store2.get_task("TASK-003")
        assert task["_sync"]["rst_file"] == "new_tasks.rst"
    
    def test_reopen_nonexistent_task(self, tmp_path):
        """Test reopening a nonexistent task raises error."""
        from doxtr_doto.transforms.archive import reopen_task
        from doxtr_doto.sync.json_store import JsonTaskStore
        
        json_path = tmp_path / ".doto" / "tasks.json"
        json_path.parent.mkdir(parents=True)
        
        store = JsonTaskStore(json_path)
        store.save()
        
        with pytest.raises(ValueError) as excinfo:
            reopen_task("NONEXISTENT", store)
        assert "not found" in str(excinfo.value)
    
    def test_reopen_non_archived_task(self, tmp_path):
        """Test reopening a non-archived task raises error."""
        from doxtr_doto.transforms.archive import reopen_task
        from doxtr_doto.sync.json_store import JsonTaskStore
        
        json_path = tmp_path / ".doto" / "tasks.json"
        json_path.parent.mkdir(parents=True)
        
        store = JsonTaskStore(json_path)
        store.add_task("TASK-ACTIVE", {
            "title": "Active task",
            "status": "open",
            "archived": False,
        })
        store.save()
        
        with pytest.raises(ValueError) as excinfo:
            reopen_task("TASK-ACTIVE", store)
        assert "not archived" in str(excinfo.value)


class TestAutoArchiveIntegration:
    """Integration tests for auto-archive with Sphinx builds."""
    
    def test_auto_archive_disabled_by_default(self, doto_srcdir, make_app, sample_tasks_rst):
        """Test that auto-archive is disabled by default."""
        app = make_app(srcdir=doto_srcdir)
        
        # Default config should have auto_archive disabled
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
        app.env.doto_virtual_docs = {
            "archive": "Virtual Archive Content\n======================\n"
        }
        
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
        tasks_rst.write_text('''
Tasks
=====

.. doto:: Completed task
   :id: TASK-DONE
   :status: done

   This task is done.
''')
        
        # Add tasks to index toctree
        index_rst = doto_srcdir / "index.rst"
        index_rst.write_text(
            index_rst.read_text() + "\n   tasks\n   archive\n"
        )
        
        # Create archive.rst placeholder (Sphinx needs the file to exist)
        archive_rst = doto_srcdir / "archive.rst"
        archive_rst.write_text("placeholder")
        
        # Create JSON store with an archived task
        json_path = doto_srcdir / ".doto" / "tasks.json"
        json_path.write_text(json.dumps({
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
                    "_sync": {
                        "rst_file": None,
                        "snapshot": None
                    }
                }
            }
        }, indent=2))
        
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
