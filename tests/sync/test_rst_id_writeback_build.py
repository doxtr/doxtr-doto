"""End-to-end build coverage for auto-generated ID write-back.

Runs a real Sphinx build over an ``.rst`` file containing a bare
``.. doto::`` directive (no explicit ``:id:``). After the build, the
generated ``:id:`` must be written back into the RST file, and a second
build must reuse that ID rather than recreating the task.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from doxtr_doto.enums import SyncAction
from doxtr_doto.sync import _process_file_updates


def _write_bare_directive_doc(srcdir: Path) -> Path:
    """Add a doc with a single bare ``.. doto::`` directive to the toctree."""
    tasks_rst = srcdir / "tasks.rst"
    tasks_rst.write_text("Tasks\n=====\n\n.. doto:: A bare directive without an explicit id\n")

    index_rst = srcdir / "index.rst"
    index_rst.write_text(index_rst.read_text() + "\n   tasks\n")
    return tasks_rst


class TestAutoIdWritebackEndToEnd:
    """A bare RST directive's auto-generated id is written back on build."""

    def test_generated_id_is_written_back_into_rst(self, doto_srcdir, make_app):
        """After a build, the bare directive gains its generated ``:id:``."""
        tasks_rst = _write_bare_directive_doc(doto_srcdir)

        app = make_app(srcdir=doto_srcdir)
        app.build()

        content = tasks_rst.read_text()
        # Directive on line 4 of tasks.rst -> auto id "tasks-L4".
        assert ":id: tasks-L4" in content, (
            f"generated id was not written back; content was:\n{content}"
        )

        # The id must appear in the existing directive, not a new one.
        assert content.count(".. doto::") == 1

        # And the task is persisted to tasks.json.
        json_path = Path(app.srcdir) / ".doto" / "tasks.json"
        data = json.loads(json_path.read_text())
        assert "tasks-L4" in data["tasks"]

    def test_second_build_does_not_recreate_task(self, doto_srcdir, make_app):
        """A second build reuses the written-back id (no duplicate task)."""
        tasks_rst = _write_bare_directive_doc(doto_srcdir)

        app = make_app(srcdir=doto_srcdir)
        app.build()

        json_path = Path(app.srcdir) / ".doto" / "tasks.json"
        first_ids = set(json.loads(json_path.read_text())["tasks"].keys())
        assert first_ids == {"tasks-L4"}

        # Simulate a line shift above the directive. The directive now carries
        # the explicit :id: that was written back, so its id stays stable even
        # though its line number changed.
        shifted = "Intro paragraph.\n\n" + tasks_rst.read_text()
        tasks_rst.write_text(shifted)

        app2 = make_app(srcdir=doto_srcdir)
        app2.build()

        second_ids = set(json.loads(json_path.read_text())["tasks"].keys())
        assert second_ids == {"tasks-L4"}, (
            f"task was recreated on second build; ids: {sorted(second_ids)}"
        )


class TestMixedDirectiveWritebackEndToEnd:
    """Write-back must survive files that also contain list/summary directives.

    Regression for a crash during RST write-back:

        doto: Error SyncAction.UPDATEing task <id> in <docname>:
        'Values' object has no attribute 'env'

    A real build registers the env-dependent ``doto-list`` /
    ``doto-summary`` directives globally. When the write-back path parsed an
    RST file containing those directives with a standalone (env-free)
    docutils parser, invoking them raised. This builds exactly such a file
    (bare ``.. doto::`` plus a list and a summary) and asserts the build
    succeeds and the generated id is written back.
    """

    def _write_mixed_doc(self, srcdir: Path) -> Path:
        """Add a doc with a bare ``.. doto::`` plus list/summary directives."""
        tasks_rst = srcdir / "tasks.rst"
        tasks_rst.write_text(
            "Tasks\n"
            "=====\n"
            "\n"
            ".. doto-summary::\n"
            "   :group-by: status\n"
            "\n"
            ".. doto:: A bare directive without an explicit id\n"
            "\n"
            ".. doto-list::\n"
            "   :status: open\n"
        )
        index_rst = srcdir / "index.rst"
        index_rst.write_text(index_rst.read_text() + "\n   tasks\n")
        return tasks_rst

    def test_build_succeeds_and_writes_back_id_with_list_and_summary(
        self, doto_srcdir, make_app, caplog
    ):
        """Build succeeds without the env error and writes the id back."""
        tasks_rst = self._write_mixed_doc(doto_srcdir)

        app = make_app(srcdir=doto_srcdir)
        with caplog.at_level(logging.ERROR):
            app.build()

        # (a) The write-back env crash must not be logged.
        assert "'Values' object has no attribute 'env'" not in caplog.text
        assert "UPDATE" not in caplog.text or "env" not in caplog.text

        # (b) The generated id is written back into the bare directive.
        content = tasks_rst.read_text()
        # The bare ``.. doto::`` header is on line 7 of tasks.rst.
        assert ":id: tasks-L7" in content, (
            f"generated id was not written back; content was:\n{content}"
        )
        # The write-back targets the existing directive, not a new one, and
        # leaves the list/summary directives intact.
        assert content.count(".. doto::") == 1
        assert ".. doto-list::" in content
        assert ".. doto-summary::" in content

        # And the task is persisted to tasks.json under the generated id.
        json_path = Path(app.srcdir) / ".doto" / "tasks.json"
        data = json.loads(json_path.read_text())
        assert "tasks-L7" in data["tasks"]


class TestDoc2PathResolution:
    """_process_file_updates resolves docnames to real source files."""

    def test_insert_id_resolves_docname_to_rst_file(self, doto_srcdir, make_app):
        """An INSERT_ID queued with ``rst_file`` as a docname (no extension)
        writes into the real ``tasks.rst`` via doc2path resolution."""
        tasks_rst = doto_srcdir / "tasks.rst"
        tasks_rst.write_text("Tasks\n=====\n\n.. doto:: A bare directive\n")
        index_rst = doto_srcdir / "index.rst"
        index_rst.write_text(index_rst.read_text() + "\n   tasks\n")

        # Build so app.env knows about the "tasks" docname for doc2path.
        app = make_app(srcdir=doto_srcdir)
        app.build()

        # Reset the directive to a bare form so we can drive the write-back
        # directly through _process_file_updates with a docname rst_file.
        tasks_rst.write_text("Tasks\n=====\n\n.. doto:: A bare directive\n")

        logger = logging.getLogger("doto-test")
        _process_file_updates(
            app,
            "tasks",  # docname, no extension and no matching bare path
            [(SyncAction.INSERT_ID, "tasks-L4", {"_rst_line": 4})],
            logger,
        )

        content = tasks_rst.read_text()
        assert ":id: tasks-L4" in content
        assert content.count(".. doto::") == 1

    def test_existing_path_short_circuits_before_doc2path(self, doto_srcdir, make_app, monkeypatch):
        """When ``rst_path.exists()`` is True the legacy path is used unchanged
        and ``doc2path`` is never consulted."""
        tasks_rst = doto_srcdir / "tasks.rst"
        tasks_rst.write_text("Tasks\n=====\n\n.. doto:: A bare directive\n")

        app = make_app(srcdir=doto_srcdir)

        # doc2path must not be called when the raw path already exists.
        def _boom(*args, **kwargs):  # pragma: no cover - should never run
            raise AssertionError("doc2path should not be called")

        monkeypatch.setattr(app.env, "doc2path", _boom)

        logger = logging.getLogger("doto-test")
        # rst_file given WITH extension so the raw path exists directly.
        _process_file_updates(
            app,
            "tasks.rst",
            [(SyncAction.INSERT_ID, "tasks-L4", {"_rst_line": 4})],
            logger,
        )

        content = tasks_rst.read_text()
        assert ":id: tasks-L4" in content

    def test_create_path_resolves_through_existing_file(self, doto_srcdir, make_app):
        """A CREATE action against an existing file resolves via the
        short-circuit (no doc2path needed) and inserts the directive."""
        tasks_rst = doto_srcdir / "tasks.rst"
        tasks_rst.write_text("Tasks\n=====\n")

        app = make_app(srcdir=doto_srcdir)
        logger = logging.getLogger("doto-test")
        _process_file_updates(
            app,
            "tasks.rst",
            [
                (
                    SyncAction.CREATE,
                    "NEW-1",
                    {"id": "NEW-1", "title": "Fresh task"},
                )
            ],
            logger,
        )

        content = tasks_rst.read_text()
        assert ".. doto:: Fresh task" in content
        assert ":id: NEW-1" in content


class TestJsonEditSyncsToRstOnBuild:
    """A JSON-only edit (as the TUI makes) must sync into RST on next build.

    Reproduces the end-to-end symptom: after editing a task in the TUI (which
    writes only to ``tasks.json``), ``make html`` wrote the change back into
    the RST directive but corrupted it (emitting ``:title:``/``:body:`` options
    and leaking new options into the body), so the rendered page did not show
    the update. The write-back must now update the directive cleanly.
    """

    def _write_doc(self, srcdir: Path) -> Path:
        tasks_rst = srcdir / "tasks.rst"
        tasks_rst.write_text(
            "Tasks\n"
            "=====\n"
            "\n"
            ".. doto:: Original title\n"
            "   :id: TASK-100\n"
            "   :status: open\n"
            "\n"
            "   Original body.\n"
        )
        index_rst = srcdir / "index.rst"
        index_rst.write_text(index_rst.read_text() + "\n   tasks\n")
        return tasks_rst

    def test_status_edit_in_json_syncs_to_rst_without_corruption(self, doto_srcdir, make_app):
        """TUI-style status edit lands in RST as a clean :status: option."""
        tasks_rst = self._write_doc(doto_srcdir)

        # First build establishes the JSON task + sync snapshot.
        app = make_app(srcdir=doto_srcdir)
        app.build()

        json_path = Path(app.srcdir) / ".doto" / "tasks.json"
        from doxtr_doto.cli.json_store import JsonTaskStore

        store = JsonTaskStore(json_path)
        store.update_task("TASK-100", {"status": "done"})
        store.save()

        # Second build pushes the JSON change back into the RST.
        app2 = make_app(srcdir=doto_srcdir)
        app2.build()

        content = tasks_rst.read_text()
        # The status change is written back.
        assert ":status: done" in content
        # The directive is NOT corrupted.
        assert ":title:" not in content
        assert ":body:" not in content
        # Argument line, id, and body are intact and un-duplicated.
        assert ".. doto:: Original title" in content
        assert ":id: TASK-100" in content
        assert content.count("Original body.") == 1
        assert content.count(".. doto::") == 1

    def test_body_edit_in_json_syncs_to_rst(self, doto_srcdir, make_app):
        """TUI-style body edit rewrites the directive content block."""
        tasks_rst = self._write_doc(doto_srcdir)

        app = make_app(srcdir=doto_srcdir)
        app.build()

        json_path = Path(app.srcdir) / ".doto" / "tasks.json"
        from doxtr_doto.cli.json_store import JsonTaskStore

        store = JsonTaskStore(json_path)
        store.update_task("TASK-100", {"body": "Updated body content."})
        store.save()

        app2 = make_app(srcdir=doto_srcdir)
        app2.build()

        content = tasks_rst.read_text()
        assert "Updated body content." in content
        assert "Original body." not in content
        assert ":body:" not in content
        assert content.count(".. doto::") == 1


class TestBareDirectiveStatusWriteback:
    """A JSON edit must sync into a BARE directive (no :id: in the RST).

    Reproduces the reported case: an RST directive carrying only an argument
    and an ``:assignee:`` (no ``:id:``, no ``:status:``). ``doto done`` sets
    status in JSON, but the write-back UPDATE matched by ``:id:`` and found
    nothing, so the RST (and rendered page) never changed. The UPDATE now
    falls back to the directive's line number, injects the ``:id:`` to make it
    stable, and writes the ``:status:`` option.
    """

    def _write_bare_doc(self, srcdir: Path) -> Path:
        tasks_rst = srcdir / "tasks.rst"
        tasks_rst.write_text(
            "Tasks\n"
            "=====\n"
            "\n"
            ".. doto:: Document the decision\n"
            "   :assignee: :xlink:`yourdirectory-person-alice-bobbington`\n"
        )
        index_rst = srcdir / "index.rst"
        index_rst.write_text(index_rst.read_text() + "\n   tasks\n")
        return tasks_rst

    def test_status_edit_syncs_into_bare_directive(self, doto_srcdir, make_app):
        tasks_rst = self._write_bare_doc(doto_srcdir)

        # First build: assigns an auto id and persists the task to JSON. The
        # id is written back into the (previously bare) directive.
        app = make_app(srcdir=doto_srcdir)
        app.build()

        content_after_1 = tasks_rst.read_text()
        # The bare directive header is on line 4 -> auto id "tasks-L4".
        assert ":id: tasks-L4" in content_after_1
        # The assignee role is preserved verbatim.
        assert ":assignee: :xlink:`yourdirectory-person-alice-bobbington`" in content_after_1

        json_path = Path(app.srcdir) / ".doto" / "tasks.json"
        from doxtr_doto.cli.json_store import JsonTaskStore

        store = JsonTaskStore(json_path)
        store.update_task("tasks-L4", {"status": "done"})
        store.save()

        # Second build: status change must land in the RST.
        app2 = make_app(srcdir=doto_srcdir)
        app2.build()

        content_after_2 = tasks_rst.read_text()
        assert ":status: done" in content_after_2
        assert ":id: tasks-L4" in content_after_2
        assert ":assignee: :xlink:`yourdirectory-person-alice-bobbington`" in content_after_2
        assert content_after_2.count(".. doto::") == 1
        # No bogus internal option leaked in.
        assert ":_rst_line:" not in content_after_2


class TestMultiBareDirectiveDoneNoCorruption:
    """Regression for the reported multi-directive corruption on `doto done`.

    Several bare `.. doto::` directives in one file, each marked done in JSON
    (as `doto done` does), must sync back on build without (a) duplicate
    `:id:` lines or (b) losing the blank line that separates directives (which
    previously made them run together). Covers the stale-line batch ordering
    fix, the id-duplication guard, and the empty-body trailing-newline fix.
    """

    def _write_three_bare(self, srcdir: Path) -> Path:
        tasks_rst = srcdir / "tasks.rst"
        tasks_rst.write_text(
            "Tasks\n"
            "=====\n"
            "\n"
            ".. doto:: First decision\n"
            "   :assignee: :xlink:`person-a`\n"
            "\n"
            ".. doto:: Second decision\n"
            "   :assignee: :xlink:`person-b`\n"
            "\n"
            ".. doto:: Third decision\n"
            "   :assignee: :xlink:`person-c`\n"
        )
        index_rst = srcdir / "index.rst"
        index_rst.write_text(index_rst.read_text() + "\n   tasks\n")
        return tasks_rst

    def test_done_on_all_bare_directives_round_trips_cleanly(self, doto_srcdir, make_app):
        import json as _json

        from doxtr_doto.cli.json_store import JsonTaskStore

        tasks_rst = self._write_three_bare(doto_srcdir)

        app = make_app(srcdir=doto_srcdir)
        app.build()

        # Build 1 wrote the ids back and kept the directives separated.
        after_1 = tasks_rst.read_text()
        assert after_1.count(".. doto::") == 3
        assert ":status: done\n.. doto::" not in after_1

        json_path = Path(app.srcdir) / ".doto" / "tasks.json"
        ids = sorted(_json.loads(json_path.read_text())["tasks"].keys())
        store = JsonTaskStore(json_path)
        for tid in ids:
            store.update_task(tid, {"status": "done"})
        store.save()

        app2 = make_app(srcdir=doto_srcdir)
        app2.build()

        out = tasks_rst.read_text()
        # (a) No duplicate ids.
        for tid in ids:
            assert out.count(f":id: {tid}") == 1, f"dup {tid}\n{out}"
        # (b) All three updated.
        assert out.count(":status: done") == 3, out
        # (c) Directives remain separated by a blank line (none run together).
        assert out.count(".. doto::") == 3
        assert ":status: done\n.. doto::" not in out, out
        assert out.count("\n\n.. doto::") == 3, out
        # (d) Assignee roles preserved verbatim.
        assert ":xlink:`person-a`" in out
        assert ":xlink:`person-c`" in out
