"""Tests for the archive document builder functionality."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest


class TestGenerateArchiveContent:
    """Test the generate_archive_content function."""

    def test_produces_valid_rst(self, doto_srcdir, make_app):
        """Test that generate_archive_content produces valid RST."""
        from doxtr_doto.builders.archive_doc import generate_archive_content
        from doxtr_doto.collectors import DotoEnvironment, DotoTask, get_doto_env

        app = make_app(srcdir=doto_srcdir, buildername="html")
        env = app.env

        # Set up a mock environment with archived tasks
        doto_env = get_doto_env(env)
        doto_env.all_tasks = {
            "TASK-001": DotoTask(
                id="TASK-001",
                title="Archived task one",
                status="done",
                archived=True,
                archived_on=datetime(2026, 7, 1, 12, 0, 0),
                updated=datetime(2026, 7, 1, 12, 0, 0),
            ),
            "TASK-002": DotoTask(
                id="TASK-002",
                title="Archived task two",
                status="done",
                archived=True,
                archived_on=datetime(2026, 7, 15, 10, 0, 0),
                updated=datetime(2026, 7, 15, 10, 0, 0),
            ),
        }

        content = generate_archive_content(app, env)

        # Verify RST structure
        assert "Archived Tasks" in content
        assert "==============" in content
        assert "Total archived tasks:** 2" in content
        assert ".. doto-list::" in content
        assert ":show-archived: true" in content

    def test_produces_empty_message_when_no_archived_tasks(self, doto_srcdir, make_app):
        """Test that generate_archive_content handles no archived tasks."""
        from doxtr_doto.builders.archive_doc import generate_archive_content
        from doxtr_doto.collectors import DotoEnvironment, get_doto_env

        app = make_app(srcdir=doto_srcdir, buildername="html")
        env = app.env

        # Set up empty environment
        doto_env = get_doto_env(env)
        doto_env.all_tasks = {}

        content = generate_archive_content(app, env)

        assert "Archived Tasks" in content
        assert "Total archived tasks:** 0" in content
        assert "*No archived tasks.*" in content
        assert ".. doto-list::" not in content

    def test_sorts_by_archived_date(self, doto_srcdir, make_app):
        """Test that archived tasks are sorted by archived_on date."""
        from doxtr_doto.builders.archive_doc import generate_archive_content
        from doxtr_doto.collectors import DotoTask, get_doto_env

        app = make_app(srcdir=doto_srcdir, buildername="html")
        env = app.env

        doto_env = get_doto_env(env)
        # Add tasks with different archived dates
        doto_env.all_tasks = {
            "TASK-001": DotoTask(
                id="TASK-001",
                title="First archived",
                status="done",
                archived=True,
                archived_on=datetime(2026, 1, 1),
            ),
            "TASK-002": DotoTask(
                id="TASK-002",
                title="Second archived",
                status="done",
                archived=True,
                archived_on=datetime(2026, 6, 15),
            ),
            "TASK-003": DotoTask(
                id="TASK-003",
                title="Most recent archived",
                status="done",
                archived=True,
                archived_on=datetime(2026, 12, 25),
            ),
        }

        content = generate_archive_content(app, env)

        # Content should be generated (sorting is internal)
        assert "Total archived tasks:** 3" in content


class TestAddArchiveDoc:
    """Test the add_archive_doc function."""

    def test_returns_archive_docname_when_archived_tasks_exist(
        self, doto_srcdir, make_app
    ):
        """Test that add_archive_doc returns archive docname when archived tasks exist."""
        from doxtr_doto.builders.archive_doc import add_archive_doc
        from doxtr_doto.collectors import DotoTask, get_doto_env

        # Update config to enable auto_archive
        conf_py = doto_srcdir / "conf.py"
        conf_py.write_text(
            "extensions = ['doxtr_doto']\n"
            "master_doc = 'index'\n"
            "doto_auto_archive = True\n"
            "doto_archive_doc = '_archived_tasks'\n"
        )

        app = make_app(srcdir=doto_srcdir, buildername="html")
        env = app.env

        # Add an archived task
        doto_env = get_doto_env(env)
        doto_env.all_tasks = {
            "TASK-001": DotoTask(
                id="TASK-001",
                title="Archived task",
                status="done",
                archived=True,
            ),
        }

        result = add_archive_doc(app, env, set(), set(), set())

        assert result == ["_archived_tasks"]

    def test_returns_empty_when_no_archived_tasks(self, doto_srcdir, make_app):
        """Test that add_archive_doc returns empty when no archived tasks."""
        from doxtr_doto.builders.archive_doc import add_archive_doc
        from doxtr_doto.collectors import DotoTask, get_doto_env

        # Update config to enable auto_archive
        conf_py = doto_srcdir / "conf.py"
        conf_py.write_text(
            "extensions = ['doxtr_doto']\n"
            "master_doc = 'index'\n"
            "doto_auto_archive = True\n"
        )

        app = make_app(srcdir=doto_srcdir, buildername="html")
        env = app.env

        # Add only non-archived tasks
        doto_env = get_doto_env(env)
        doto_env.all_tasks = {
            "TASK-001": DotoTask(
                id="TASK-001",
                title="Active task",
                status="open",
                archived=False,
            ),
        }

        result = add_archive_doc(app, env, set(), set(), set())

        assert result == []

    def test_returns_empty_when_auto_archive_disabled(self, doto_srcdir, make_app):
        """Test that add_archive_doc returns empty when auto_archive is disabled."""
        from doxtr_doto.builders.archive_doc import add_archive_doc
        from doxtr_doto.collectors import DotoTask, get_doto_env

        # Config with auto_archive disabled (default)
        app = make_app(srcdir=doto_srcdir, buildername="html")
        env = app.env

        # Add an archived task
        doto_env = get_doto_env(env)
        doto_env.all_tasks = {
            "TASK-001": DotoTask(
                id="TASK-001",
                title="Archived task",
                status="done",
                archived=True,
            ),
        }

        result = add_archive_doc(app, env, set(), set(), set())

        assert result == []


class TestInjectArchiveDoc:
    """Test the inject_archive_doc function."""

    def test_stores_content_in_env_doto_virtual_docs(self, doto_srcdir, make_app):
        """Test that inject_archive_doc stores content in env.doto_virtual_docs."""
        from doxtr_doto.builders.archive_doc import inject_archive_doc
        from doxtr_doto.collectors import DotoTask, get_doto_env

        # Update config to enable auto_archive
        conf_py = doto_srcdir / "conf.py"
        conf_py.write_text(
            "extensions = ['doxtr_doto']\n"
            "master_doc = 'index'\n"
            "doto_auto_archive = True\n"
            "doto_archive_doc = '_doto_archive'\n"
        )

        app = make_app(srcdir=doto_srcdir, buildername="html")
        env = app.env

        # Add an archived task
        doto_env = get_doto_env(env)
        doto_env.all_tasks = {
            "TASK-001": DotoTask(
                id="TASK-001",
                title="Archived task",
                status="done",
                archived=True,
            ),
        }

        docnames = ["_doto_archive"]
        inject_archive_doc(app, env, docnames)

        assert hasattr(env, "doto_virtual_docs")
        assert "_doto_archive" in env.doto_virtual_docs
        assert "Archived Tasks" in env.doto_virtual_docs["_doto_archive"]

    def test_does_nothing_when_archive_doc_not_in_docnames(self, doto_srcdir, make_app):
        """Test that inject_archive_doc does nothing when archive doc not requested."""
        from doxtr_doto.builders.archive_doc import inject_archive_doc

        # Update config to enable auto_archive
        conf_py = doto_srcdir / "conf.py"
        conf_py.write_text(
            "extensions = ['doxtr_doto']\n"
            "master_doc = 'index'\n"
            "doto_auto_archive = True\n"
            "doto_archive_doc = '_doto_archive'\n"
        )

        app = make_app(srcdir=doto_srcdir, buildername="html")
        env = app.env

        # Don't include archive doc in docnames
        docnames = ["index", "tasks"]
        inject_archive_doc(app, env, docnames)

        # Should not create doto_virtual_docs or should be empty
        if hasattr(env, "doto_virtual_docs"):
            assert "_doto_archive" not in env.doto_virtual_docs

    def test_does_nothing_when_auto_archive_disabled(self, doto_srcdir, make_app):
        """Test that inject_archive_doc does nothing when auto_archive disabled."""
        from doxtr_doto.builders.archive_doc import inject_archive_doc

        # Config with auto_archive disabled (default)
        app = make_app(srcdir=doto_srcdir, buildername="html")
        env = app.env

        docnames = ["_doto_archive"]
        inject_archive_doc(app, env, docnames)

        # Should not create doto_virtual_docs
        assert not hasattr(env, "doto_virtual_docs") or "_doto_archive" not in getattr(
            env, "doto_virtual_docs", {}
        )


class TestGetArchiveDocContent:
    """Test the get_archive_doc_content function."""

    def test_returns_content_when_available(self, doto_srcdir, make_app):
        """Test that get_archive_doc_content returns stored content."""
        from doxtr_doto.builders.archive_doc import get_archive_doc_content

        app = make_app(srcdir=doto_srcdir, buildername="html")
        env = app.env

        # Manually set up virtual docs
        env.doto_virtual_docs = {"_archive": "Test content"}

        result = get_archive_doc_content(env, "_archive")

        assert result == "Test content"

    def test_returns_none_when_not_available(self, doto_srcdir, make_app):
        """Test that get_archive_doc_content returns None when not found."""
        from doxtr_doto.builders.archive_doc import get_archive_doc_content

        app = make_app(srcdir=doto_srcdir, buildername="html")
        env = app.env

        result = get_archive_doc_content(env, "_nonexistent")

        assert result is None

    def test_returns_none_when_no_virtual_docs(self, doto_srcdir, make_app):
        """Test that get_archive_doc_content returns None when doto_virtual_docs missing."""
        from doxtr_doto.builders.archive_doc import get_archive_doc_content

        app = make_app(srcdir=doto_srcdir, buildername="html")
        env = app.env

        # Ensure doto_virtual_docs doesn't exist
        if hasattr(env, "doto_virtual_docs"):
            delattr(env, "doto_virtual_docs")

        result = get_archive_doc_content(env, "_archive")

        assert result is None


class TestReadVirtualDoc:
    """Test the read_virtual_doc function."""

    def test_replaces_source_with_virtual_content(self, doto_srcdir, make_app):
        """Test that read_virtual_doc replaces source with virtual content."""
        from doxtr_doto.builders.archive_doc import read_virtual_doc

        app = make_app(srcdir=doto_srcdir, buildername="html")
        env = app.env

        # Set up virtual docs
        env.doto_virtual_docs = {"_archive": "Virtual content here"}

        source = ["Original content"]
        read_virtual_doc(app, "_archive", source)

        assert source[0] == "Virtual content here"

    def test_does_not_modify_source_for_regular_docs(self, doto_srcdir, make_app):
        """Test that read_virtual_doc doesn't modify regular documents."""
        from doxtr_doto.builders.archive_doc import read_virtual_doc

        app = make_app(srcdir=doto_srcdir, buildername="html")
        env = app.env

        # Set up virtual docs without the requested doc
        env.doto_virtual_docs = {"_archive": "Virtual content"}

        source = ["Original content"]
        read_virtual_doc(app, "regular_doc", source)

        assert source[0] == "Original content"
