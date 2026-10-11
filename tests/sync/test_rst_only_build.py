"""End-to-end build coverage for RST-only task persistence.

These tests run a real Sphinx build over an .rst file containing a bare
``.. doto::`` directive (no explicit ``:id:``). The directive receives an
auto-generated ``{docname}-L{lineno}`` ID at collection time. The sync step
must then create that task in ``.doto/tasks.json`` so it is visible to
``doto list`` and the other CLI commands.

The unit test in ``test_json_store.py`` exercises ``_apply_merge_result``
directly; these tests prove the full upstream path (directive -> collector
-> sync_task -> create_in_json -> JSON store) actually produces persistence.
"""

from __future__ import annotations

import json
from pathlib import Path


def _write_bare_directive_doc(srcdir: Path) -> None:
    """Add a doc with a single bare ``.. doto::`` directive to the toctree.

    The directive deliberately omits ``:id:`` so the collector assigns the
    auto-generated ``{docname}-L{lineno}`` ID.
    """
    tasks_rst = srcdir / "tasks.rst"
    tasks_rst.write_text("Tasks\n=====\n\n.. doto:: A bare directive without an explicit id\n")

    index_rst = srcdir / "index.rst"
    index_rst.write_text(index_rst.read_text() + "\n   tasks\n")


class TestRstOnlyBuildPersistence:
    """A bare RST directive must be persisted to tasks.json after a build."""

    def test_bare_directive_is_persisted_to_tasks_json(self, doto_srcdir, make_app):
        """Build an .rst with a bare ``.. doto::`` and assert JSON persistence.

        The directive on line 4 of tasks.rst gets the auto-generated ID
        ``tasks-L4``. After the build, ``.doto/tasks.json`` must contain that
        task with the directive's title.
        """
        _write_bare_directive_doc(doto_srcdir)

        app = make_app(srcdir=doto_srcdir)
        app.build()

        json_path = Path(app.srcdir) / ".doto" / "tasks.json"
        assert json_path.exists(), "sync did not create tasks.json"

        data = json.loads(json_path.read_text())
        tasks = data["tasks"]

        # Auto-generated ID is "{docname}-L{lineno}"; the directive is on
        # line 4 of tasks.rst (docname "tasks").
        expected_id = "tasks-L4"
        assert expected_id in tasks, (
            f"RST-only task {expected_id!r} was not persisted; present IDs: {sorted(tasks)}"
        )

        task = tasks[expected_id]
        assert task["title"] == "A bare directive without an explicit id"
        # The persisted task records its RST origin via the _sync metadata.
        # The sync layer stores the docname ("tasks"), not the file name.
        assert task["_sync"]["rst_file"] == "tasks"
