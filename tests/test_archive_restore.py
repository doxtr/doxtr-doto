"""Tests for archive restore-to-place, the restore anchor, and doto-archive.

Covers:
- capturing the restore anchor at archive time
- restoring to the same place when the anchor still matches
- the heavily-modified top-of-page fallback
- the renamed/deleted page error message
- the doto-archive directive rendering from the JSON store
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from doxtr_doto.sync.restore import RestorePath, restore_task_to_rst
from doxtr_doto.sync.rst_writer import (
    capture_restore_anchor,
    extract_page_title,
    find_anchor_insertion_line,
    find_title_insertion_line,
)

# Sample page: a heading, some prose, then a doto directive.
SAMPLE_RST = """\
Project Tasks
=============

Some introductory prose about the project.

A second paragraph of context.

.. doto:: Fix the login bug
   :id: TASK-001
   :status: done

   The login button does nothing.

More content after the task.
"""


class TestExtractPageTitle:
    """Tests for extract_page_title."""

    def test_extracts_first_heading(self):
        assert extract_page_title(SAMPLE_RST) == "Project Tasks"

    def test_returns_none_without_heading(self):
        assert extract_page_title("just some text\nno heading here\n") is None

    def test_handles_overline(self):
        content = "=====\nTitle\n=====\n\nbody\n"
        assert extract_page_title(content) == "Title"


class TestCaptureRestoreAnchor:
    """Tests for capture_restore_anchor."""

    def test_captures_anchor_fields(self):
        anchor = capture_restore_anchor(SAMPLE_RST, "TASK-001")
        assert anchor is not None
        assert anchor["version"] == 1
        assert anchor["page_title"] == "Project Tasks"
        # The last preceding non-blank line is the paragraph above the directive.
        assert anchor["preceding_lines"][-1] == "A second paragraph of context."
        # removed_directive is intentionally NOT captured: restore regenerates
        # the directive from current fields (fix: stale status on reopen).
        assert "removed_directive" not in anchor
        assert isinstance(anchor["directive_line"], int)

    def test_returns_none_for_missing_task(self):
        assert capture_restore_anchor(SAMPLE_RST, "NOPE-999") is None


class TestAnchorMatching:
    """Tests for find_anchor_insertion_line and find_title_insertion_line."""

    def test_unique_anchor_matches(self):
        preceding = ["A second paragraph of context."]
        line = find_anchor_insertion_line(SAMPLE_RST, preceding)
        assert line is not None

    def test_missing_anchor_returns_none(self):
        assert find_anchor_insertion_line(SAMPLE_RST, ["not present at all"]) is None

    def test_ambiguous_anchor_returns_none(self):
        content = "A\n\nmarker line\n\nB\n\nmarker line\n\nC\n"
        assert find_anchor_insertion_line(content, ["marker line"]) is None

    def test_title_insertion_line(self):
        line = find_title_insertion_line(SAMPLE_RST)
        # The underline is the 2nd line (1-indexed).
        assert line == 2


def _archived_task(rst_file: str, anchor: dict | None) -> dict:
    """Build an archived task dict with optional restore anchor."""
    sync: dict = {"rst_file": rst_file}
    if anchor is not None:
        sync["_archive"] = {"original_rst_file": rst_file, **anchor}
    return {
        "id": "TASK-001",
        "title": "Fix the login bug",
        "status": "done",
        "priority": "medium",
        "archived": True,
        "body": "The login button does nothing.",
        "_sync": sync,
    }


class TestRestoreToSamePlace:
    """restore_task_to_rst anchored success path."""

    def test_restores_at_anchor(self, tmp_path):
        # Write the file WITHOUT the directive (as if it had been removed).
        removed = SAMPLE_RST.replace(
            ".. doto:: Fix the login bug\n"
            "   :id: TASK-001\n"
            "   :status: done\n"
            "\n"
            "   The login button does nothing.\n\n",
            "",
        )
        rst = tmp_path / "tasks.rst"
        rst.write_text(removed)

        anchor = capture_restore_anchor(SAMPLE_RST, "TASK-001")
        task = _archived_task("tasks.rst", anchor)

        result = restore_task_to_rst(task, tmp_path)
        assert result.success is True
        assert result.path == RestorePath.ANCHOR

        new_content = rst.read_text()
        assert ".. doto:: Fix the login bug" in new_content
        # The directive should sit right after the anchored paragraph and
        # before the trailing "More content" line.
        anchor_pos = new_content.index("A second paragraph of context.")
        directive_pos = new_content.index(".. doto:: Fix the login bug")
        more_pos = new_content.index("More content after the task.")
        assert anchor_pos < directive_pos < more_pos


class TestHeavilyModifiedFallback:
    """restore_task_to_rst top-of-page fallback."""

    def test_falls_back_to_top_of_page(self, tmp_path):
        # A heavily-modified file: the original preceding context is gone.
        modified = "Project Tasks\n=============\n\nTotally different content now.\n"
        rst = tmp_path / "tasks.rst"
        rst.write_text(modified)

        anchor = capture_restore_anchor(SAMPLE_RST, "TASK-001")
        task = _archived_task("tasks.rst", anchor)

        result = restore_task_to_rst(task, tmp_path)
        assert result.success is True
        assert result.path == RestorePath.TOP_OF_PAGE

        new_content = rst.read_text()
        assert ".. doto:: Fix the login bug" in new_content
        # Inserted under the heading, before the "Totally different" content.
        directive_pos = new_content.index(".. doto:: Fix the login bug")
        other_pos = new_content.index("Totally different content now.")
        assert directive_pos < other_pos


class TestRenamedDeletedPage:
    """restore_task_to_rst renamed/deleted error."""

    def test_errors_when_page_missing(self, tmp_path):
        anchor = capture_restore_anchor(SAMPLE_RST, "TASK-001")
        # Point at a file that does not exist.
        task = _archived_task("gone.rst", anchor)

        result = restore_task_to_rst(task, tmp_path)
        assert result.success is False
        assert result.path == RestorePath.PAGE_MISSING
        assert "this doto was originally on a page with title" in result.message
        assert '"Project Tasks"' in result.message
        assert "gone.rst" in result.message

    def test_no_recorded_origin_fails(self, tmp_path):
        task = {
            "id": "TASK-X",
            "title": "No origin",
            "status": "done",
            "archived": True,
            "_sync": {},
        }
        result = restore_task_to_rst(task, tmp_path)
        assert result.success is False
        assert result.path == RestorePath.PAGE_MISSING


class TestReopenRestoresInPlace:
    """json_store.reopen_task restore-to-place integration."""

    def test_reopen_anchors_directive(self, tmp_path):
        from doxtr_doto.sync.json_store import JsonTaskStore

        removed = SAMPLE_RST.replace(
            ".. doto:: Fix the login bug\n"
            "   :id: TASK-001\n"
            "   :status: done\n"
            "\n"
            "   The login button does nothing.\n\n",
            "",
        )
        rst = tmp_path / "tasks.rst"
        rst.write_text(removed)

        anchor = capture_restore_anchor(SAMPLE_RST, "TASK-001")

        json_path = tmp_path / ".doto" / "tasks.json"
        json_path.parent.mkdir(parents=True)
        store = JsonTaskStore(json_path)
        store.add_task("TASK-001", _archived_task("tasks.rst", anchor))
        store.save()

        result = store.reopen_task("TASK-001", srcdir=tmp_path)
        store.save()

        assert result.path == RestorePath.ANCHOR
        task = store.get_task("TASK-001")
        assert task["archived"] is False
        assert "_archive" not in task["_sync"]
        assert ".. doto:: Fix the login bug" in rst.read_text()

    def test_reopen_renamed_page_leaves_archived(self, tmp_path):
        from doxtr_doto.sync.json_store import JsonTaskStore

        anchor = capture_restore_anchor(SAMPLE_RST, "TASK-001")
        json_path = tmp_path / ".doto" / "tasks.json"
        json_path.parent.mkdir(parents=True)
        store = JsonTaskStore(json_path)
        store.add_task("TASK-001", _archived_task("missing.rst", anchor))
        store.save()

        result = store.reopen_task("TASK-001", srcdir=tmp_path)
        assert result.success is False
        assert result.path == RestorePath.PAGE_MISSING
        # Task is left archived so the user can retrace.
        task = store.get_task("TASK-001")
        assert task["archived"] is True


class TestDotoArchiveDirective:
    """Rendering tests for the doto-archive directive."""

    def test_renders_archived_tasks_from_env(self, doto_srcdir, make_app):
        from doxtr_doto.collectors import DotoTask, get_doto_env

        # A page that uses the new directive.
        archive_rst = doto_srcdir / "arch.rst"
        archive_rst.write_text("Archive\n=======\n\n.. doto-archive::\n")
        index_rst = doto_srcdir / "index.rst"
        index_rst.write_text(index_rst.read_text() + "\n   arch\n")

        app = make_app(srcdir=doto_srcdir, buildername="html")

        # Seed the environment with an archived task before build render.
        doto_env = get_doto_env(app.env)
        doto_env.all_tasks = {
            "TASK-A": DotoTask(
                id="TASK-A",
                title="Done and archived",
                status="done",
                priority="high",
                assignee="alice",
                docname="tasks",
                archived=True,
                archived_on=datetime(2026, 7, 1, 10, 0, 0),
            ),
        }

        app.build()

        html = (Path(app.outdir) / "arch.html").read_text()
        assert "doto-archive-table" in html
        assert "TASK-A" in html
        assert "Done and archived" in html
        assert "alice" in html

    def test_renders_empty_when_no_archived_tasks(self, doto_srcdir, make_app):
        from doxtr_doto.collectors import get_doto_env

        archive_rst = doto_srcdir / "arch.rst"
        archive_rst.write_text("Archive\n=======\n\n.. doto-archive::\n")
        index_rst = doto_srcdir / "index.rst"
        index_rst.write_text(index_rst.read_text() + "\n   arch\n")

        app = make_app(srcdir=doto_srcdir, buildername="html")
        get_doto_env(app.env).all_tasks = {}
        app.build()

        html = (Path(app.outdir) / "arch.html").read_text()
        assert "No archived tasks" in html


class TestFallbackArchiveRenderer:
    """The Jinja-less fallback renderer for doto-archive.html."""

    def test_fallback_render_archive(self):
        from doxtr_doto.template_loader import _fallback_render_archive

        html = _fallback_render_archive(
            {
                "rows": [
                    {
                        "id": "T-1",
                        "title": "Thing",
                        "status": "done",
                        "priority": "low",
                        "assignee": "bob",
                        "archived_on": "2026-07-01",
                        "original_page": "tasks",
                        "body": "a body",
                    },
                ],
                "total": 1,
            }
        )
        assert "doto-archive" in html
        assert "T-1" in html
        assert "Thing" in html
        assert "bob" in html
        assert "a body" in html

    def test_fallback_render_archive_empty(self):
        from doxtr_doto.template_loader import _fallback_render_archive

        html = _fallback_render_archive({"rows": [], "total": 0})
        assert "No archived tasks" in html


class TestModuleReopenTaskRestore:
    """transforms.archive.reopen_task restore-to-place path."""

    def test_module_reopen_restores_in_place(self, tmp_path):
        from doxtr_doto.sync.json_store import JsonTaskStore
        from doxtr_doto.transforms.archive import reopen_task

        removed = SAMPLE_RST.replace(
            ".. doto:: Fix the login bug\n"
            "   :id: TASK-001\n"
            "   :status: done\n"
            "\n"
            "   The login button does nothing.\n\n",
            "",
        )
        rst = tmp_path / "tasks.rst"
        rst.write_text(removed)

        anchor = capture_restore_anchor(SAMPLE_RST, "TASK-001")

        json_path = tmp_path / ".doto" / "tasks.json"
        json_path.parent.mkdir(parents=True)
        store = JsonTaskStore(json_path)
        store.add_task("TASK-001", _archived_task("tasks.rst", anchor))
        store.save()

        result = reopen_task("TASK-001", store, srcdir=tmp_path)
        store.save()

        assert result is not None
        assert result.path == RestorePath.ANCHOR
        assert ".. doto:: Fix the login bug" in rst.read_text()


class TestReopenAppliesStatusNotArchived:
    """Fix #1: the re-inserted directive must carry the reopen status."""

    def _removed_file(self, tmp_path):
        removed = SAMPLE_RST.replace(
            ".. doto:: Fix the login bug\n"
            "   :id: TASK-001\n"
            "   :status: done\n"
            "\n"
            "   The login button does nothing.\n\n",
            "",
        )
        rst = tmp_path / "tasks.rst"
        rst.write_text(removed)
        return rst

    def test_json_store_reopen_writes_open_status(self, tmp_path):
        from doxtr_doto.sync.json_store import JsonTaskStore

        rst = self._removed_file(tmp_path)
        anchor = capture_restore_anchor(SAMPLE_RST, "TASK-001")

        json_path = tmp_path / ".doto" / "tasks.json"
        json_path.parent.mkdir(parents=True)
        store = JsonTaskStore(json_path)
        store.add_task("TASK-001", _archived_task("tasks.rst", anchor))
        store.save()

        result = store.reopen_task("TASK-001", status="open", srcdir=tmp_path)
        store.save()

        assert result.path == RestorePath.ANCHOR
        text = rst.read_text()
        # The directive carries the reopen status, not the archived done status.
        assert ":status: done" not in text
        # ``open`` is the default status so generate_directive_text omits the
        # option entirely; assert it is NOT 'done' (above) and the directive is
        # present without a done status.
        assert ".. doto:: Fix the login bug" in text

    def test_module_reopen_writes_in_progress_status(self, tmp_path):
        from doxtr_doto.sync.json_store import JsonTaskStore
        from doxtr_doto.transforms.archive import reopen_task

        rst = self._removed_file(tmp_path)
        anchor = capture_restore_anchor(SAMPLE_RST, "TASK-001")

        json_path = tmp_path / ".doto" / "tasks.json"
        json_path.parent.mkdir(parents=True)
        store = JsonTaskStore(json_path)
        store.add_task("TASK-001", _archived_task("tasks.rst", anchor))
        store.save()

        result = reopen_task("TASK-001", store, new_status="in-progress", srcdir=tmp_path)
        store.save()

        text = rst.read_text()
        assert result.path == RestorePath.ANCHOR
        # Non-default status IS emitted, and must be the reopen status.
        assert ":status: in-progress" in text
        assert ":status: done" not in text


class TestPathTraversalRefused:
    """Fix #2: a traversal original_rst_file must not write outside srcdir."""

    def test_traversal_path_does_not_write(self, tmp_path):
        srcdir = tmp_path / "docs"
        srcdir.mkdir()
        outside = tmp_path / "evil.rst"
        # Pre-create a target the attack would clobber if containment failed.
        outside.write_text("ORIGINAL\n")

        anchor = capture_restore_anchor(SAMPLE_RST, "TASK-001")
        task = _archived_task("../evil", anchor)

        result = restore_task_to_rst(task, srcdir)
        assert result.success is False
        assert result.path == RestorePath.PAGE_MISSING
        # The file outside srcdir was left untouched.
        assert outside.read_text() == "ORIGINAL\n"


class TestHeadingLessTopOfPage:
    """Fix #7: top-of-page fallback for a heading-less heavily-modified file."""

    def test_inserts_at_document_start_without_heading(self, tmp_path):
        # Heavily modified AND heading-less: anchor won't match, no title line.
        modified = "just some prose now\nand more prose\n"
        rst = tmp_path / "tasks.rst"
        rst.write_text(modified)

        anchor = capture_restore_anchor(SAMPLE_RST, "TASK-001")
        task = _archived_task("tasks.rst", anchor)

        result = restore_task_to_rst(task, tmp_path)
        assert result.success is True
        assert result.path == RestorePath.TOP_OF_PAGE

        text = rst.read_text()
        directive_pos = text.index(".. doto:: Fix the login bug")
        prose_pos = text.index("just some prose now")
        # Directive lands at the TOP (document start), before the prose, not
        # appended at the end.
        assert directive_pos < prose_pos


class TestAmbiguousAnchorFallsBack:
    """Optional: an ambiguous anchor routes through to TOP_OF_PAGE."""

    def test_ambiguous_anchor_top_of_page(self, tmp_path):
        # The preceding context appears twice => ambiguous => top of page.
        content = (
            "Project Tasks\n"
            "=============\n"
            "\n"
            "A second paragraph of context.\n"
            "\n"
            "middle\n"
            "\n"
            "A second paragraph of context.\n"
            "\n"
            "tail\n"
        )
        rst = tmp_path / "tasks.rst"
        rst.write_text(content)

        anchor = capture_restore_anchor(SAMPLE_RST, "TASK-001")
        task = _archived_task("tasks.rst", anchor)

        result = restore_task_to_rst(task, tmp_path)
        assert result.success is True
        assert result.path == RestorePath.TOP_OF_PAGE
        text = rst.read_text()
        directive_pos = text.index(".. doto:: Fix the login bug")
        other_pos = text.index("middle")
        assert directive_pos < other_pos


class TestArchiveSortKeyMixedDates:
    """Fix #3: archive collection sorts without TypeError on mixed dates."""

    def test_sort_key_mixed_datetime_and_none(self):
        from doxtr_doto.nodes import _archive_sort_key

        class _T:
            def __init__(self, archived_on=None, updated=None, created=None):
                self.archived_on = archived_on
                self.updated = updated
                self.created = created

        with_dt = _T(archived_on=datetime(2026, 7, 1, 10, 0, 0, tzinfo=timezone.utc))
        all_none = _T()
        # Sorting a list mixing a datetime-bearing task with an all-None task
        # must not raise (previously mixed datetime and "").
        tasks = [with_dt, all_none]
        tasks.sort(key=_archive_sort_key, reverse=True)
        assert tasks[0] is with_dt

    def test_archive_page_renders_with_dateless_task(self, doto_srcdir, make_app):
        from doxtr_doto.collectors import DotoTask, get_doto_env

        archive_rst = doto_srcdir / "arch.rst"
        archive_rst.write_text("Archive\n=======\n\n.. doto-archive::\n")
        index_rst = doto_srcdir / "index.rst"
        index_rst.write_text(index_rst.read_text() + "\n   arch\n")

        app = make_app(srcdir=doto_srcdir, buildername="html")
        doto_env = get_doto_env(app.env)
        doto_env.all_tasks = {
            "WITH-DATE": DotoTask(
                id="WITH-DATE",
                title="Has a date",
                status="done",
                priority="high",
                archived=True,
                archived_on=datetime(2026, 7, 1, 10, 0, 0, tzinfo=timezone.utc),
            ),
            "NO-DATE": DotoTask(
                id="NO-DATE",
                title="No dates at all",
                status="done",
                priority="low",
                archived=True,
            ),
        }
        # Must build (render) without a sort-key TypeError.
        app.build()
        html = (Path(app.outdir) / "arch.html").read_text()
        assert "WITH-DATE" in html
        assert "NO-DATE" in html


class TestRestoreStrategyRegistry:
    """Fix #8: pluggable anchor/restore strategy seam."""

    def test_builtin_registered_as_default(self):
        from doxtr_doto.sync.restore import (
            _CURRENT_ARCHIVE_VERSION,
            _RESTORE_STRATEGIES,
            _resolve_strategy,
        )

        assert _CURRENT_ARCHIVE_VERSION in _RESTORE_STRATEGIES
        assert "builtin" in _RESTORE_STRATEGIES
        # Unknown version falls back to the default built-in.
        assert _resolve_strategy({"version": 999}) is _RESTORE_STRATEGIES[_CURRENT_ARCHIVE_VERSION]

    def test_register_custom_strategy_by_name(self, tmp_path):
        from doxtr_doto.sync import restore as restore_mod

        rst = tmp_path / "tasks.rst"
        rst.write_text("Project Tasks\n=============\n\nbody\n")

        calls = {"anchor": 0, "title": 0}

        def _always_top(content, preceding):
            calls["anchor"] += 1
            return None  # force top-of-page

        def _title(content):
            calls["title"] += 1
            return restore_mod.find_title_insertion_line(content)

        strat = restore_mod.RestoreStrategy(find_anchor=_always_top, find_title=_title)
        restore_mod.register_restore_strategy("test-strat", strat)
        try:
            anchor = capture_restore_anchor(SAMPLE_RST, "TASK-001")
            anchor["strategy"] = "test-strat"
            task = _archived_task("tasks.rst", anchor)
            result = restore_mod.restore_task_to_rst(task, tmp_path)
            assert result.path == restore_mod.RestorePath.TOP_OF_PAGE
            assert calls["anchor"] == 1
            assert calls["title"] == 1
        finally:
            restore_mod._RESTORE_STRATEGIES.pop("test-strat", None)
