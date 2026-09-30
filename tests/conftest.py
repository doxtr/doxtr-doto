"""Pytest configuration and fixtures for doto tests."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Generator

import pytest


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
    (srcdir / "conf.py").write_text(
        "extensions = ['doxtr_doto']\n"
        "master_doc = 'index'\n"
    )
    
    # Create index.rst
    (srcdir / "index.rst").write_text(
        "Test Documentation\n"
        "==================\n"
        "\n"
        ".. toctree::\n"
        "   :maxdepth: 2\n"
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
    tasks_rst.write_text('''
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
''')
    
    # Add to toctree
    index_rst = doto_srcdir / "index.rst"
    index_rst.write_text(
        index_rst.read_text() + "\n   tasks\n"
    )
    
    return tasks_rst


@pytest.fixture
def sample_json_store(doto_srcdir: Path) -> Path:
    """Create sample tasks.json file."""
    import json
    
    json_path = doto_srcdir / ".doto" / "tasks.json"
    json_path.write_text(json.dumps({
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
                        "body": "Users need to be able to log in securely."
                    }
                }
            }
        }
    }, indent=2))
    
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
    from doxtr_doto.sync.merge import sync_task, MergeResult, FieldConflict
    from doxtr_doto.sync.hash import compute_rst_hash, normalize_rst_directive
    
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
