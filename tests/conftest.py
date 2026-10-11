"""Pytest configuration and fixtures for doto tests."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

#: Repo root (two levels up from this file: tests/ -> repo).
_REPO_ROOT = Path(__file__).resolve().parent.parent
#: The ``studies`` test-bed generator lives in ``scripts/`` which is not an
#: importable package, so it is loaded by file path on demand (and cached).
_GEN_PATH = _REPO_ROOT / "scripts" / "gen_studies_testbed.py"


def _load_studies_generator() -> ModuleType:
    """Import the ``gen_studies_testbed`` module from ``scripts/`` by path.

    ``scripts/`` is not a package and is not on ``sys.path`` during the test
    run, so a plain ``import`` would fail. Loading by file path keeps the
    generator usable as both a standalone script and a test helper without
    adding packaging boilerplate.

    Returns:
        The loaded module (cached in ``sys.modules`` as
        ``gen_studies_testbed``).
    """
    cached = sys.modules.get("gen_studies_testbed")
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location("gen_studies_testbed", _GEN_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["gen_studies_testbed"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def studies_generator() -> ModuleType:
    """The imported ``gen_studies_testbed`` module.

    Session-scoped: importing is cheap but there is no reason to repeat it.
    Use :func:`studies_generator.build` to materialise a test bed, or the
    ready-made :func:`studies_testbed` / :func:`studies_meta` fixtures.
    """
    return _load_studies_generator()


@pytest.fixture
def studies_testbed(tmp_path: Path, studies_generator: ModuleType) -> dict:
    """Build a fresh ``studies`` multi-repo test bed under ``tmp_path``.

    Materialises the full high-school + university tree (16 doto repositories,
    tasks in every status, logged time) into an isolated temporary directory
    and returns the generator's metadata summary (see
    ``gen_studies_testbed._discover_metadata``): ``root``, ``repos`` (each with
    ``name``/``path``/``prefix``/``task_count``/``statuses``), ``total_tasks``
    and ``status_totals``.

    The tree is self-contained -- every subject/module folder has its own
    ``.doto.toml`` + ``.doto/tasks.json`` -- so tests can exercise cross-repo
    discovery, filtering, aggregation and time-tracking against realistic,
    deterministic data.
    """
    return studies_generator.build(tmp_path / "studies")


@pytest.fixture
def studies_repo(studies_testbed: dict):
    """Return a lookup helper for repos in the :func:`studies_testbed`.

    Returns a callable ``get(name)`` that returns the per-repo metadata dict
    for a repository folder name (e.g. ``"maths"``,
    ``"cs201-data-structures"``), raising ``KeyError`` if absent.
    """
    by_name = {r["name"]: r for r in studies_testbed["repos"]}

    def get(name: str) -> dict:
        return by_name[name]

    return get


@pytest.fixture
def tmp_path_factory_custom(tmp_path: Path) -> Path:
    """Provide a temporary directory for tests."""
    return tmp_path


@pytest.fixture
def sphinx_srcdir(tmp_path: Path) -> Path:
    """Create a minimal Sphinx source directory."""
    srcdir = tmp_path / "source"
    srcdir.mkdir()

    # Create minimal conf.py
    (srcdir / "conf.py").write_text("extensions = ['doxtr_doto']\nmaster_doc = 'index'\n")

    # Create index.rst
    (srcdir / "index.rst").write_text(
        "Test Documentation\n==================\n\n.. toctree::\n   :maxdepth: 2\n"
    )

    return srcdir


@pytest.fixture
def doto_srcdir(sphinx_srcdir: Path) -> Path:
    """Create a Sphinx source directory with doto configuration."""
    # Create .doto directory
    doto_dir = sphinx_srcdir / ".doto"
    doto_dir.mkdir()

    return sphinx_srcdir


@pytest.fixture
def sample_tasks_rst(doto_srcdir: Path) -> Path:
    """Create sample RST file with doto tasks."""
    tasks_rst = doto_srcdir / "tasks.rst"
    tasks_rst.write_text("""
Tasks
=====

.. doto:: Implement user authentication
   :id: TASK-001
   :assignee: alice
   :priority: high
   :status: open
   :due: 2026-08-15
   :tags: security, backend

   Users need to be able to log in securely.

.. doto:: Add export feature
   :id: TASK-002
   :priority: medium
   :status: in-progress
   :tags: feature

   Export data to CSV and JSON formats.

.. doto:: Fix database connection
   :id: TASK-003
   :assignee: bob
   :priority: critical
   :status: blocked
   :depends-on: TASK-001

   Connection pooling needs to be fixed.
""")

    # Add to toctree
    index_rst = doto_srcdir / "index.rst"
    index_rst.write_text(index_rst.read_text() + "\n   tasks\n")

    return tasks_rst


@pytest.fixture
def sample_json_store(doto_srcdir: Path) -> Path:
    """Create sample tasks.json file."""
    import json

    json_path = doto_srcdir / ".doto" / "tasks.json"
    json_path.write_text(
        json.dumps(
            {
                "version": 2,
                "updated": "2026-07-26T10:00:00",
                "tasks": {
                    "TASK-001": {
                        "title": "Implement user authentication",
                        "assignee": "alice",
                        "priority": "high",
                        "status": "open",
                        "due": "2026-08-15",
                        "tags": ["security", "backend"],
                        "depends_on": [],
                        "body": "Users need to be able to log in securely.",
                        "created": "2026-07-20T09:00:00",
                        "updated": "2026-07-26T10:00:00",
                        "archived": False,
                        "archived_on": None,
                        "_sync": {
                            "rst_file": "tasks.rst",
                            "rst_line": 5,
                            "rst_hash": "abc123",
                            "snapshot": {
                                "title": "Implement user authentication",
                                "assignee": "alice",
                                "priority": "high",
                                "status": "open",
                                "due": "2026-08-15",
                                "tags": ["security", "backend"],
                                "depends_on": [],
                                "body": "Users need to be able to log in securely.",
                            },
                        },
                    }
                },
            },
            indent=2,
        )
    )

    return json_path


@pytest.fixture
def make_app(tmp_path: Path):
    """Factory fixture to create Sphinx applications for testing."""
    from sphinx.application import Sphinx

    def _make(
        buildername: str = "html",
        srcdir: Path | None = None,
        confoverrides: dict[str, Any] | None = None,
    ) -> Sphinx:
        if srcdir is None:
            srcdir = tmp_path / "source"
            srcdir.mkdir(exist_ok=True)
            (srcdir / "conf.py").write_text("extensions = ['doxtr_doto']")
            (srcdir / "index.rst").write_text("Test\n====\n")

        outdir = tmp_path / "build" / buildername
        doctreedir = tmp_path / "build" / ".doctrees"

        return Sphinx(
            srcdir=str(srcdir),
            confdir=str(srcdir),
            outdir=str(outdir),
            doctreedir=str(doctreedir),
            buildername=buildername,
            confoverrides=confoverrides or {},
            freshenv=True,
        )

    return _make


@pytest.fixture
def doto_app(doto_srcdir: Path, make_app):
    """Create a Sphinx app with doto extension."""
    return make_app(srcdir=doto_srcdir)


@pytest.fixture
def json_store(doto_srcdir: Path):
    """Create a JsonTaskStore instance for testing."""
    from doxtr_doto.sync.json_store import JsonTaskStore

    json_path = doto_srcdir / ".doto" / "tasks.json"
    return JsonTaskStore(json_path)


@pytest.fixture
def doto_sync():
    """Create sync utilities for testing."""
    from doxtr_doto.sync.hash import compute_rst_hash, normalize_rst_directive
    from doxtr_doto.sync.merge import MergeResult, sync_task

    class SyncHelper:
        @staticmethod
        def merge_task(
            task_id: str,
            snapshot: dict | None,
            rst_current: dict | None,
            json_current: dict | None,
            rst_file: str = "test.rst",
            rst_line: int = 1,
        ) -> MergeResult:
            json_task = json_current.copy() if json_current else {}
            if json_task:
                json_task.setdefault("_sync", {})
                json_task["_sync"]["snapshot"] = snapshot
                json_task["_sync"]["rst_file"] = rst_file
                json_task["_sync"]["rst_line"] = rst_line

            return sync_task(task_id, rst_current, json_task if json_task else None)

        @staticmethod
        def compute_rst_hash(content: str) -> str:
            return compute_rst_hash(content)

        @staticmethod
        def normalize_rst(content: str) -> str:
            return normalize_rst_directive(content)

    return SyncHelper()


@pytest.fixture(autouse=True)
def _restore_accent_class_attrs():
    """Restore the accent class-attribute seams around every test.

    The live TUI app publishes the resolved theme accent onto the *global*
    class attributes ``TitleHighlight.BRACKET_HIGHLIGHT_STYLE`` and
    ``KanbanView.SELECTED_FRAME_ACCENT`` at mount / theme-change. Because they
    are class-level, a live-app test in *any* module would otherwise leak the
    accent into the pure-logic tests that assert on the un-published defaults
    (e.g. that a selected frame uses ``SELECTED_FRAME_STYLE``). This lives in
    the shared ``conftest`` -- rather than a single test module -- so the
    snapshot/restore protects every test regardless of which module (and
    which pytest-randomly order) first constructs a live app.

    ``textual`` is an optional dependency and this conftest is shared by
    non-TUI tests, so the widgets module is imported lazily and an
    :class:`ImportError` makes the fixture a no-op (mirroring the
    ``TEXTUAL_AVAILABLE`` guard used by ``tests/cli/test_tui.py``).
    """
    try:
        from doxtr_doto.cli.tui.widgets import KanbanView, TitleHighlight
    except ImportError:
        # textual not installed -- nothing to snapshot/restore.
        yield
        return

    prev_bracket = TitleHighlight.BRACKET_HIGHLIGHT_STYLE
    prev_frame = KanbanView.SELECTED_FRAME_ACCENT
    try:
        yield
    finally:
        TitleHighlight.BRACKET_HIGHLIGHT_STYLE = prev_bracket
        KanbanView.SELECTED_FRAME_ACCENT = prev_frame
