"""Tests for auto-generated ID write-back into RST directives.

Covers the ``insert_id_into_directive_at_line`` rst_writer helper and the
end-to-end sync write-back path that makes auto-generated
``{docname}-L{lineno}`` IDs stable across builds.

Bug: a bare ``.. doto::`` directive (no explicit ``:id:``) gets an
auto-generated line-based ID at collection time. If that ID is never written
back into the RST file, a line-number shift on the next build produces a new
ID, orphaning the JSON task and recreating it. The fix queues an INSERT_ID
RST update that injects the generated ``:id:`` into the existing directive.
"""

from __future__ import annotations

from pathlib import Path

from doxtr_doto.enums import SyncAction
from doxtr_doto.sync import (
    _apply_merge_result,
    _apply_update_to_content,
)
from doxtr_doto.sync.json_store import JsonTaskStore
from doxtr_doto.sync.merge import sync_task
from doxtr_doto.sync.rst_writer import insert_id_into_directive_at_line


class TestInsertIdIntoDirectiveAtLine:
    """Unit tests for the rst_writer helper."""

    def test_bare_directive_gets_id_injected_after_header(self):
        """A bare directive gets ``:id:`` injected right after the header."""
        content = "Tasks\n=====\n\n.. doto:: A bare task\n\n   Body text.\n"
        # Directive header is on line 4 (1-indexed).
        result = insert_id_into_directive_at_line(content, 4, "tasks-L4")

        lines = result.split("\n")
        assert lines[3] == ".. doto:: A bare task"
        assert lines[4] == "   :id: tasks-L4"
        # Original body is preserved further down.
        assert "   Body text." in result

    def test_directive_with_existing_id_is_untouched(self):
        """A directive that already has an ``:id:`` is never modified."""
        content = ".. doto:: Already has id\n   :id: EXISTING-1\n   :priority: high\n"
        result = insert_id_into_directive_at_line(content, 1, "tasks-L1")
        assert result == content

    def test_matches_option_indentation_of_existing_options(self):
        """The injected ``:id:`` line matches existing option indentation."""
        content = ".. doto:: Indented options\n     :priority: high\n"
        result = insert_id_into_directive_at_line(content, 1, "tasks-L1")
        lines = result.split("\n")
        # Injected id uses the same 5-space indent as :priority:.
        assert lines[1] == "     :id: tasks-L1"
        assert lines[2] == "     :priority: high"

    def test_id_injected_before_other_options(self):
        """The ``:id:`` is injected before pre-existing options."""
        content = ".. doto:: Task\n   :priority: high\n   :status: open\n"
        result = insert_id_into_directive_at_line(content, 1, "T-1")
        lines = result.split("\n")
        assert lines[0] == ".. doto:: Task"
        assert lines[1] == "   :id: T-1"
        assert lines[2] == "   :priority: high"

    def test_multiple_bare_directives_each_targeted_by_line(self):
        """Line-based lookup targets the correct directive among many."""
        content = (
            ".. doto:: First bare\n"
            "\n"
            "Some prose.\n"
            "\n"
            ".. doto:: Second bare\n"
            "\n"
            "More prose.\n"
            "\n"
            ".. doto:: Third bare\n"
        )
        # Target the second directive (header on line 5).
        result = insert_id_into_directive_at_line(content, 5, "doc-L5")
        lines = result.split("\n")
        assert lines[4] == ".. doto:: Second bare"
        assert lines[5] == "   :id: doc-L5"
        # The first and third directives are untouched (no :id:).
        assert ".. doto:: First bare" in result
        assert result.count(":id:") == 1

    def test_nearest_directive_at_or_after_line(self):
        """A lineno just before a directive still finds that directive."""
        content = ".. doto:: First bare\n\n.. doto:: Second bare\n"
        # lineno=2 is between directives; nearest at/after is line 3.
        result = insert_id_into_directive_at_line(content, 2, "doc-L3")
        lines = result.split("\n")
        assert lines[2] == ".. doto:: Second bare"
        assert lines[3] == "   :id: doc-L3"

    def test_not_found_line_returns_unchanged(self):
        """A lineno past the last bare directive returns content unchanged."""
        content = ".. doto:: Only bare\n"
        result = insert_id_into_directive_at_line(content, 99, "T-1")
        assert result == content

    def test_empty_content_returns_unchanged(self):
        """Empty content is returned unchanged."""
        assert insert_id_into_directive_at_line("", 1, "T-1") == ""

    def test_second_call_is_idempotent(self):
        """A second call with the same id is a no-op (directive now has :id:)."""
        content = ".. doto:: Bare\n"
        once = insert_id_into_directive_at_line(content, 1, "tasks-L1")
        twice = insert_id_into_directive_at_line(once, 1, "tasks-L1")
        assert twice == once
        assert once.count(":id:") == 1

    def test_batched_inserts_with_stale_line_numbers(self):
        """Three sequential inserts using ORIGINAL (stale) line numbers land
        on the correct distinct directives.

        This locks in the robustness invariant that makes the batched path in
        ``_process_file_updates`` safe: the helper (a) skips directives that
        already have ``:id:`` and (b) picks the nearest id-less directive
        at/after lineno. Because each insert only pushes later lines down and
        already-processed directives are skipped, a stale earlier line number
        can never land on a wrong earlier (already-processed) directive.
        """
        content = ".. doto:: First bare\n\n.. doto:: Second bare\n\n.. doto:: Third bare\n"
        # Original (stale) line numbers for the three directive headers.
        # Applied in-order; later inserts use line numbers computed against
        # the ORIGINAL content, not the mutated content.
        result = content
        result = insert_id_into_directive_at_line(result, 1, "doc-L1")
        result = insert_id_into_directive_at_line(result, 3, "doc-L3")
        result = insert_id_into_directive_at_line(result, 5, "doc-L5")

        assert result.count(":id:") == 3
        lines = result.split("\n")
        # Each id must sit directly under its own directive header.
        first = lines.index(".. doto:: First bare")
        second = lines.index(".. doto:: Second bare")
        third = lines.index(".. doto:: Third bare")
        assert lines[first + 1] == "   :id: doc-L1"
        assert lines[second + 1] == "   :id: doc-L3"
        assert lines[third + 1] == "   :id: doc-L5"


class TestApplyUpdateInsertId:
    """INSERT_ID action is dispatched to the rst_writer helper."""

    def test_insert_id_action_injects_id(self):
        """SyncAction.INSERT_ID injects the id using the carried line number."""
        content = ".. doto:: Bare\n"
        result = _apply_update_to_content(
            content,
            SyncAction.INSERT_ID,
            "doc-L1",
            {"id": "doc-L1", "_rst_line": 1},
        )
        assert ":id: doc-L1" in result

    def test_insert_id_without_line_is_noop(self):
        """INSERT_ID with no recorded line leaves content unchanged."""
        content = ".. doto:: Bare\n"
        result = _apply_update_to_content(
            content,
            SyncAction.INSERT_ID,
            "doc-L1",
            {"id": "doc-L1"},
        )
        assert result == content

    def test_batched_insert_id_actions_with_stale_lines(self):
        """Repeated INSERT_ID actions on shared content with stale line
        numbers (the batched ``_process_file_updates`` path) land each id on
        its correct directive.

        Exercises the dispatcher (``_apply_update_to_content``) rather than
        the helper directly, mirroring how ``write_rst_updates`` applies all
        queued updates for one file to the in-memory content in sequence.
        """
        content = ".. doto:: First bare\n\n.. doto:: Second bare\n\n.. doto:: Third bare\n"
        updates = [
            ("doc-L1", {"_rst_line": 1}),
            ("doc-L3", {"_rst_line": 3}),
            ("doc-L5", {"_rst_line": 5}),
        ]
        modified = content
        for task_id, data in updates:
            modified = _apply_update_to_content(modified, SyncAction.INSERT_ID, task_id, data)

        assert modified.count(":id:") == 3
        lines = modified.split("\n")
        first = lines.index(".. doto:: First bare")
        second = lines.index(".. doto:: Second bare")
        third = lines.index(".. doto:: Third bare")
        assert lines[first + 1] == "   :id: doc-L1"
        assert lines[second + 1] == "   :id: doc-L3"
        assert lines[third + 1] == "   :id: doc-L5"


class TestAutogeneratedWritebackQueueing:
    """_apply_merge_result queues INSERT_ID only for auto-generated IDs."""

    def _make_store(self, tmp_path: Path) -> JsonTaskStore:
        store = JsonTaskStore(tmp_path / ".doto" / "tasks.json")
        store.load()
        return store

    def test_autogenerated_rst_only_task_queues_insert_id(self, tmp_path):
        """An auto-generated RST-only task queues an INSERT_ID update."""
        store = self._make_store(tmp_path)
        task_id = "tasks-L4"
        rst_current = {
            "id": task_id,
            "title": "A bare directive",
            "priority": "medium",
            "status": "open",
            "_rst_file": "tasks",
            "_rst_line": 4,
            "_id_autogenerated": True,
        }
        result = sync_task(
            task_id=task_id,
            rst_current=rst_current,
            json_task=None,
            rst_file="tasks",
            rst_line=4,
        )
        assert result.create_in_json is True

        sync_data = {"rst_updates": []}
        _apply_merge_result(
            result=result,
            task_id=task_id,
            store=store,
            app=None,
            rst_file="tasks",
            rst_line=4,
            rst_current=rst_current,
            sync_data=sync_data,
        )

        assert len(sync_data["rst_updates"]) == 1
        action, target, tid, data = sync_data["rst_updates"][0]
        assert action == SyncAction.INSERT_ID
        assert target == "tasks"
        assert tid == task_id
        assert data["_rst_line"] == 4

    def test_explicit_id_rst_only_task_does_not_queue(self, tmp_path):
        """A task with an explicit ID does not queue any INSERT_ID update."""
        store = self._make_store(tmp_path)
        task_id = "TASK-123"
        rst_current = {
            "id": task_id,
            "title": "Explicit id task",
            "priority": "medium",
            "status": "open",
            "_rst_file": "tasks",
            "_rst_line": 4,
            "_id_autogenerated": False,
        }
        result = sync_task(
            task_id=task_id,
            rst_current=rst_current,
            json_task=None,
            rst_file="tasks",
            rst_line=4,
        )
        sync_data = {"rst_updates": []}
        _apply_merge_result(
            result=result,
            task_id=task_id,
            store=store,
            app=None,
            rst_file="tasks",
            rst_line=4,
            rst_current=rst_current,
            sync_data=sync_data,
        )
        assert sync_data["rst_updates"] == []


class TestWritebackTwoRunStability:
    """Integration-style: the fix must be stable across two sync runs."""

    def test_two_runs_do_not_recreate_task(self, tmp_path):
        """Simulate two sync runs; the second must not duplicate the task.

        Run 1: a bare directive gets an auto-generated ID, persisted to JSON,
        and the ``:id:`` is written back into the RST file.
        Run 2 (after a line shift above the directive): the directive now has
        an explicit ``:id:``, so the same ID is reused and no new task is
        created.
        """
        rst_path = tmp_path / "tasks.rst"
        rst_content = "Tasks\n=====\n\n.. doto:: A bare directive\n"
        rst_path.write_text(rst_content)

        store = JsonTaskStore(tmp_path / ".doto" / "tasks.json")
        store.load()

        # --- Run 1: directive header on line 4 -> auto id "tasks-L4" ---
        task_id = "tasks-L4"
        rst_current = {
            "id": task_id,
            "title": "A bare directive",
            "priority": "medium",
            "status": "open",
            "_rst_file": "tasks",
            "_rst_line": 4,
            "_id_autogenerated": True,
        }
        result = sync_task(
            task_id=task_id,
            rst_current=rst_current,
            json_task=None,
            rst_file="tasks",
            rst_line=4,
        )
        sync_data = {"rst_updates": []}
        _apply_merge_result(
            result=result,
            task_id=task_id,
            store=store,
            app=None,
            rst_file="tasks",
            rst_line=4,
            rst_current=rst_current,
            sync_data=sync_data,
        )
        store.save()

        # Apply the queued INSERT_ID write-back to the RST content.
        for action, _target, tid, data in sync_data["rst_updates"]:
            rst_content = _apply_update_to_content(rst_content, action, tid, data)
        rst_path.write_text(rst_content)

        # The generated :id: is now present in the RST file.
        assert ":id: tasks-L4" in rst_path.read_text()

        # --- Run 2: simulate a line shift (two lines added at the top). ---
        # The directive is now on line 6, but it carries an explicit :id:.
        shifted = "New intro.\n\n" + rst_path.read_text()
        rst_path.write_text(shifted)

        # The directive now parses with an explicit id, so collection would
        # yield id "tasks-L4" again with _id_autogenerated=False.
        reloaded = JsonTaskStore(tmp_path / ".doto" / "tasks.json")
        reloaded.load()
        before_ids = set(reloaded.tasks.keys())
        assert before_ids == {"tasks-L4"}

        rst_current_run2 = {
            "id": "tasks-L4",
            "title": "A bare directive",
            "priority": "medium",
            "status": "open",
            "_rst_file": "tasks",
            "_rst_line": 6,
            "_id_autogenerated": False,
        }
        json_task = reloaded.get_task("tasks-L4")
        result2 = sync_task(
            task_id="tasks-L4",
            rst_current=rst_current_run2,
            json_task=json_task,
            rst_file="tasks",
            rst_line=6,
        )
        # Both sides agree; no new creation, no conflict.
        assert result2.create_in_json is False
        assert result2.has_conflicts is False

        sync_data2 = {"rst_updates": []}
        _apply_merge_result(
            result=result2,
            task_id="tasks-L4",
            store=reloaded,
            app=None,
            rst_file="tasks",
            rst_line=6,
            rst_current=rst_current_run2,
            sync_data=sync_data2,
        )
        reloaded.save()

        # No INSERT_ID queued on the second run (explicit id now). A benign
        # field UPDATE may be queued depending on snapshot state, but the id
        # write-back must never fire again.
        assert not any(action == SyncAction.INSERT_ID for action, *_ in sync_data2["rst_updates"])

        # Exactly one task remains - not recreated or duplicated.
        final = JsonTaskStore(tmp_path / ".doto" / "tasks.json")
        final.load()
        assert set(final.tasks.keys()) == {"tasks-L4"}
