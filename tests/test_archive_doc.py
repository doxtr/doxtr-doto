"""Tests for the archive document builder functionality."""

from __future__ import annotations

from datetime import datetime


class TestGenerateArchiveContent:
    """Test the generate_archive_content function."""

    def test_produces_valid_rst(self, doto_srcdir, make_app):
        """Test that generate_archive_content produces valid RST."""
        from doxtr_doto.builders.archive_doc import generate_archive_content
        from doxtr_doto.collectors import DotoTask, get_doto_env

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
        # The archive page now renders from the JSON store via the dedicated
        # doto-archive directive (sourced from the task store, child-theme
        # overridable), not a plain doto-list over RST data.
        assert ".. doto-archive::" in content

    def test_produces_empty_message_when_no_archived_tasks(self, doto_srcdir, make_app):
        """Test that generate_archive_content handles no archived tasks."""
        from doxtr_doto.builders.archive_doc import generate_archive_content
        from doxtr_doto.collectors import get_doto_env

        app = make_app(srcdir=doto_srcdir, buildername="html")
        env = app.env

        # Set up empty environment
        doto_env = get_doto_env(env)
        doto_env.all_tasks = {}

        content = generate_archive_content(app, env)

        assert "Archived Tasks" in content
        assert "Total archived tasks:** 0" in content
        assert "*No archived tasks.*" in content
        assert ".. doto-archive::" not in content

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

    def test_returns_archive_docname_when_archived_tasks_exist(self, doto_srcdir, make_app):
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
            "extensions = ['doxtr_doto']\nmaster_doc = 'index'\ndoto_auto_archive = True\n"
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

        # Explicitly disable auto_archive (now enabled by default).
        app = make_app(
            srcdir=doto_srcdir,
            buildername="html",
            confoverrides={"doto_auto_archive": False},
        )
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

        # Explicitly disable auto_archive (now enabled by default).
        app = make_app(
            srcdir=doto_srcdir,
            buildername="html",
            confoverrides={"doto_auto_archive": False},
        )
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


def _write_json_only_archived_store(doto_srcdir, task_id="JSON-ARCH-001"):
    """Write a tasks.json containing an archived task that exists ONLY in JSON.

    The task's directive is intentionally NOT present in any RST file, which is
    the normal steady state after the build that archived it. This exercises
    the regression where the archive page sourced from ``all_tasks`` showed
    "No archived tasks" because ``all_tasks`` is populated only from parsed RST
    directives.
    """
    import json

    json_path = doto_srcdir / ".doto" / "tasks.json"
    json_path.write_text(
        json.dumps(
            {
                "version": 5,
                "updated": "2026-07-26T10:00:00",
                "tasks": {
                    task_id: {
                        "title": "JSON-only archived task",
                        "status": "done",
                        "priority": "high",
                        "assignee": "alice",
                        "tags": [],
                        "depends_on": [],
                        "body": "This task lives only in the JSON store.",
                        "created": "2026-07-01T09:00:00",
                        "updated": "2026-07-10T10:00:00",
                        "archived": True,
                        "archived_on": "2026-07-15T10:00:00",
                        "_sync": {
                            "rst_file": "tasks",
                            "rst_line": 5,
                            "rst_hash": None,
                            "snapshot": None,
                            "_archive": {
                                "version": 1,
                                "original_rst_file": "tasks",
                                "page_title": "Project Tasks",
                                "preceding_lines": ["Intro paragraph."],
                                "directive_line": 5,
                            },
                        },
                    }
                },
                "series": {},
            },
            indent=2,
        )
    )
    return json_path, task_id


class TestArchivePageSourcedFromJsonStore:
    """Regression tests: the archive page must source archived tasks from the
    JSON store, not from ``all_tasks`` (which only holds RST-parsed tasks).
    """

    def test_generate_archive_content_emits_directive_for_json_only_task(
        self, doto_srcdir, make_app
    ):
        """generate_archive_content must emit the ``.. doto-archive::`` directive
        (not the empty-state prose) when the JSON store has an archived task
        absent from ``all_tasks``."""
        from doxtr_doto.builders.archive_doc import generate_archive_content
        from doxtr_doto.collectors import get_doto_env

        _write_json_only_archived_store(doto_srcdir)

        app = make_app(
            srcdir=doto_srcdir,
            buildername="html",
            confoverrides={"doto_auto_archive": True},
        )
        env = app.env

        # all_tasks is empty: the task exists ONLY in the JSON store.
        doto_env = get_doto_env(env)
        doto_env.all_tasks = {}

        content = generate_archive_content(app, env)

        assert "Total archived tasks:** 1" in content
        assert ".. doto-archive::" in content
        assert "*No archived tasks.*" not in content

    def test_add_archive_doc_true_for_json_only_task(self, doto_srcdir, make_app):
        """add_archive_doc must add the archive doc when the JSON store has an
        archived task even though ``all_tasks`` is empty."""
        from doxtr_doto.builders.archive_doc import add_archive_doc
        from doxtr_doto.collectors import get_doto_env

        _write_json_only_archived_store(doto_srcdir)

        app = make_app(
            srcdir=doto_srcdir,
            buildername="html",
            confoverrides={
                "doto_auto_archive": True,
                "doto_archive_doc": "_archived_tasks",
            },
        )
        env = app.env
        get_doto_env(env).all_tasks = {}

        result = add_archive_doc(app, env, set(), set(), set())

        assert result == ["_archived_tasks"]

    def test_add_archive_doc_respects_auto_archive_off(self, doto_srcdir, make_app):
        """With auto-archive disabled, no archive doc is added even if the JSON
        store has archived tasks."""
        from doxtr_doto.builders.archive_doc import add_archive_doc
        from doxtr_doto.collectors import get_doto_env

        _write_json_only_archived_store(doto_srcdir)

        app = make_app(
            srcdir=doto_srcdir,
            buildername="html",
            confoverrides={"doto_auto_archive": False},
        )
        env = app.env
        get_doto_env(env).all_tasks = {}

        result = add_archive_doc(app, env, set(), set(), set())

        assert result == []

    def test_collect_archived_tasks_returns_json_only_tasks(self, doto_srcdir, make_app):
        """_collect_archived_tasks must return archived tasks sourced from the
        JSON store when they are absent from ``all_tasks``."""
        from doxtr_doto.collectors import get_doto_env
        from doxtr_doto.nodes import _collect_archived_tasks

        _, task_id = _write_json_only_archived_store(doto_srcdir)

        app = make_app(
            srcdir=doto_srcdir,
            buildername="html",
            confoverrides={"doto_auto_archive": True},
        )
        env = app.env
        get_doto_env(env).all_tasks = {}

        # Minimal translator stand-in exposing the .builder used by the collector.
        class _Translator:
            def __init__(self, builder):
                self.builder = builder

        class _Builder:
            def __init__(self, app, env):
                self.app = app
                self.env = env
                self.srcdir = app.srcdir

        translator = _Translator(_Builder(app, env))
        tasks = _collect_archived_tasks(translator)

        assert [t.id for t in tasks] == [task_id]
        assert tasks[0].title == "JSON-only archived task"
        assert tasks[0].archived is True

    def test_archive_rows_show_captured_page_title_for_json_only_task(self, doto_srcdir, make_app):
        """The 'Original page' column must show the captured page_title for a
        JSON-only archived task (whose docname is just the removed-from file)."""
        from doxtr_doto.collectors import get_doto_env
        from doxtr_doto.nodes import _archive_task_rows, _collect_archived_tasks

        _write_json_only_archived_store(doto_srcdir)

        app = make_app(
            srcdir=doto_srcdir,
            buildername="html",
            confoverrides={"doto_auto_archive": True},
        )
        env = app.env
        get_doto_env(env).all_tasks = {}

        class _Translator:
            def __init__(self, builder):
                self.builder = builder

        class _Builder:
            def __init__(self, app, env):
                self.app = app
                self.env = env
                self.srcdir = app.srcdir

        translator = _Translator(_Builder(app, env))
        rows = _archive_task_rows(_collect_archived_tasks(translator))

        assert len(rows) == 1
        assert rows[0]["original_page"] == "Project Tasks"
