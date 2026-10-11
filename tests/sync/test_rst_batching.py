"""Tests for RST file update batching.

This module tests that multiple updates to the same RST file are
batched together into a single read/write cycle for efficiency.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from doxtr_doto.enums import SyncAction
from doxtr_doto.sync import write_rst_updates
from doxtr_doto.sync.rst_writer import (
    insert_directive_into_content,
    remove_directive_from_content,
    update_directive_in_content,
)

# =============================================================================
# Content-level function tests
# =============================================================================


class TestUpdateDirectiveInContent:
    """Tests for update_directive_in_content function."""

    def test_updates_existing_field(self) -> None:
        """Update an existing field in a directive."""
        content = """\
.. doto:: Test Task
   :id: TASK-001
   :status: open
   :priority: medium
"""
        result = update_directive_in_content(content, "TASK-001", {"status": "done"})
        assert ":status: done" in result
        assert ":status: open" not in result

    def test_returns_unchanged_if_task_not_found(self) -> None:
        """Return unchanged content if task ID not found."""
        content = """\
.. doto:: Test Task
   :id: TASK-001
   :status: open
"""
        result = update_directive_in_content(content, "TASK-999", {"status": "done"})
        assert result == content

    def test_adds_new_field(self) -> None:
        """Add a new field that didn't exist before."""
        content = """\
.. doto:: Test Task
   :id: TASK-001
   :status: open
"""
        result = update_directive_in_content(content, "TASK-001", {"assignee": "alice"})
        assert ":assignee: alice" in result

    def test_handles_multiple_tasks(self) -> None:
        """Update only the matching task when multiple exist."""
        content = """\
.. doto:: Task One
   :id: TASK-001
   :status: open

.. doto:: Task Two
   :id: TASK-002
   :status: open
"""
        result = update_directive_in_content(content, "TASK-001", {"status": "done"})
        # TASK-001 should be updated
        assert "TASK-001" in result
        # TASK-002 should remain unchanged
        lines = result.split("\n")
        task2_idx = next(i for i, line in enumerate(lines) if "TASK-002" in line)
        # Check status after TASK-002 is still open
        assert any(
            ":status: open" in lines[i] for i in range(task2_idx, min(task2_idx + 5, len(lines)))
        )


class TestRemoveDirectiveFromContent:
    """Tests for remove_directive_from_content function."""

    def test_removes_directive(self) -> None:
        """Remove a directive by task ID."""
        content = """\
.. doto:: Test Task
   :id: TASK-001
   :status: open

Some other content.
"""
        result = remove_directive_from_content(content, "TASK-001")
        assert "TASK-001" not in result
        assert "Some other content" in result

    def test_returns_unchanged_if_not_found(self) -> None:
        """Return unchanged content if task ID not found."""
        content = """\
.. doto:: Test Task
   :id: TASK-001
   :status: open
"""
        result = remove_directive_from_content(content, "TASK-999")
        assert result == content

    def test_cleans_up_extra_blank_lines(self) -> None:
        """Clean up multiple consecutive blank lines after removal."""
        content = """\
.. doto:: Task One
   :id: TASK-001
   :status: open



.. doto:: Task Two
   :id: TASK-002
   :status: open
"""
        result = remove_directive_from_content(content, "TASK-001")
        # Should not have more than 2 consecutive newlines
        assert "\n\n\n" not in result


class TestInsertDirectiveIntoContent:
    """Tests for insert_directive_into_content function."""

    def test_inserts_into_empty_content(self) -> None:
        """Insert directive into empty content."""
        task_data = {"id": "TASK-001", "title": "New Task", "status": "open"}
        result = insert_directive_into_content("", task_data)
        assert ".. doto:: New Task" in result
        assert ":id: TASK-001" in result

    def test_appends_to_existing_content(self) -> None:
        """Append directive to content without existing directives."""
        content = "Some existing content.\n"
        task_data = {"id": "TASK-001", "title": "New Task", "status": "open"}
        result = insert_directive_into_content(content, task_data)
        assert "Some existing content" in result
        assert ".. doto:: New Task" in result
        assert ":id: TASK-001" in result

    def test_inserts_after_existing_directive(self) -> None:
        """Insert after existing directives."""
        content = """\
.. doto:: Existing Task
   :id: TASK-001
   :status: open
"""
        task_data = {"id": "TASK-002", "title": "New Task", "status": "open"}
        result = insert_directive_into_content(content, task_data)
        # Both tasks should be present
        assert "TASK-001" in result
        assert "TASK-002" in result
        # TASK-002 should come after TASK-001
        assert result.index("TASK-001") < result.index("TASK-002")

    def test_raises_if_no_id(self) -> None:
        """Raise ValueError if task_data has no 'id' key."""
        task_data = {"title": "No ID Task"}
        with pytest.raises(ValueError, match="'id'"):
            insert_directive_into_content("", task_data)


# =============================================================================
# Batched write tests
# =============================================================================


class TestRstUpdateBatching:
    """Tests for RST update batching in write_rst_updates."""

    @pytest.fixture
    def mock_app(self, tmp_path: Path) -> MagicMock:
        """Create a mock Sphinx app."""
        app = MagicMock()
        app.srcdir = str(tmp_path)
        app.env = MagicMock()
        return app

    @pytest.fixture
    def rst_file_with_tasks(self, tmp_path: Path) -> Path:
        """Create an RST file with multiple tasks."""
        rst_file = tmp_path / "tasks.rst"
        rst_file.write_text("""\
Tasks
=====

.. doto:: Task One
   :id: TASK-001
   :status: open
   :priority: medium

.. doto:: Task Two
   :id: TASK-002
   :status: open
   :priority: high

.. doto:: Task Three
   :id: TASK-003
   :status: open
   :priority: low
""")
        return rst_file

    def test_multiple_updates_to_same_file_read_once(
        self,
        mock_app: MagicMock,
        rst_file_with_tasks: Path,
        tmp_path: Path,
    ) -> None:
        """File should be read exactly once even with 3 task updates."""
        read_count = 0
        original_read_text = Path.read_text

        def counting_read_text(self: Path, *args: Any, **kwargs: Any) -> str:
            nonlocal read_count
            if self.suffix == ".rst":
                read_count += 1
            return original_read_text(self, *args, **kwargs)

        # Queue 3 updates to the same file
        rst_file_rel = str(rst_file_with_tasks.relative_to(tmp_path))
        sync_data = {
            "rst_updates": [
                (SyncAction.UPDATE, rst_file_rel, "TASK-001", {"id": "TASK-001", "status": "done"}),
                (
                    SyncAction.UPDATE,
                    rst_file_rel,
                    "TASK-002",
                    {"id": "TASK-002", "status": "in_progress"},
                ),
                (
                    SyncAction.UPDATE,
                    rst_file_rel,
                    "TASK-003",
                    {"id": "TASK-003", "priority": "high"},
                ),
            ]
        }

        with patch.object(Path, "read_text", counting_read_text):
            with patch("doxtr_doto.sync.get_doto_sync_data", return_value=sync_data):
                write_rst_updates(mock_app, None)

        # Should read the file exactly once
        assert read_count == 1

        # Verify all updates were applied
        content = rst_file_with_tasks.read_text()
        assert ":status: done" in content  # TASK-001
        assert ":status: in_progress" in content  # TASK-002
        # TASK-003 priority changed to high (check it's present)
        assert "TASK-003" in content

    def test_updates_to_different_files_each_read_once(
        self,
        mock_app: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Updates to different files should read each file exactly once."""
        # Create two RST files
        file1 = tmp_path / "file1.rst"
        file1.write_text("""\
.. doto:: Task A
   :id: TASK-A
   :status: open
""")
        file2 = tmp_path / "file2.rst"
        file2.write_text("""\
.. doto:: Task B
   :id: TASK-B
   :status: open
""")

        read_counts: dict[str, int] = {}
        original_read_text = Path.read_text

        def counting_read_text(self: Path, *args: Any, **kwargs: Any) -> str:
            if self.suffix == ".rst":
                read_counts[self.name] = read_counts.get(self.name, 0) + 1
            return original_read_text(self, *args, **kwargs)

        # Queue updates to both files
        sync_data = {
            "rst_updates": [
                (SyncAction.UPDATE, "file1.rst", "TASK-A", {"id": "TASK-A", "status": "done"}),
                (SyncAction.UPDATE, "file2.rst", "TASK-B", {"id": "TASK-B", "status": "done"}),
            ]
        }

        with patch.object(Path, "read_text", counting_read_text):
            with patch("doxtr_doto.sync.get_doto_sync_data", return_value=sync_data):
                write_rst_updates(mock_app, None)

        # Each file should be read exactly once
        assert read_counts.get("file1.rst", 0) == 1
        assert read_counts.get("file2.rst", 0) == 1

    def test_failed_update_does_not_block_other_tasks(
        self,
        mock_app: MagicMock,
        rst_file_with_tasks: Path,
        tmp_path: Path,
    ) -> None:
        """A failed update should not prevent other updates in the same file."""
        rst_file_rel = str(rst_file_with_tasks.relative_to(tmp_path))

        # Queue updates - one with a non-existent task that will fail silently
        sync_data = {
            "rst_updates": [
                (SyncAction.UPDATE, rst_file_rel, "TASK-001", {"id": "TASK-001", "status": "done"}),
                (
                    SyncAction.UPDATE,
                    rst_file_rel,
                    "NONEXISTENT",
                    {"id": "NONEXISTENT", "status": "done"},
                ),
                (SyncAction.UPDATE, rst_file_rel, "TASK-003", {"id": "TASK-003", "status": "done"}),
            ]
        }

        with patch("doxtr_doto.sync.get_doto_sync_data", return_value=sync_data):
            write_rst_updates(mock_app, None)

        # Both valid updates should succeed
        content = rst_file_with_tasks.read_text()
        # Check TASK-001 and TASK-003 are both updated to done
        lines = content.split("\n")

        # Find TASK-001 and verify its status
        task1_idx = next(i for i, line in enumerate(lines) if "TASK-001" in line)
        task1_section = "\n".join(lines[task1_idx : task1_idx + 5])
        assert ":status: done" in task1_section or "done" in task1_section

    def test_content_unchanged_does_not_trigger_write(
        self,
        mock_app: MagicMock,
        rst_file_with_tasks: Path,
        tmp_path: Path,
    ) -> None:
        """If no content changes, file should not be written."""
        write_count = 0
        original_write_text = Path.write_text

        def counting_write_text(self: Path, *args: Any, **kwargs: Any) -> None:
            nonlocal write_count
            if self.suffix == ".rst":
                write_count += 1
            return original_write_text(self, *args, **kwargs)

        rst_file_rel = str(rst_file_with_tasks.relative_to(tmp_path))

        # Queue updates for non-existent tasks (content won't change)
        sync_data = {
            "rst_updates": [
                (
                    SyncAction.UPDATE,
                    rst_file_rel,
                    "NONEXISTENT-1",
                    {"id": "NONEXISTENT-1", "status": "done"},
                ),
                (
                    SyncAction.UPDATE,
                    rst_file_rel,
                    "NONEXISTENT-2",
                    {"id": "NONEXISTENT-2", "status": "done"},
                ),
            ]
        }

        with patch.object(Path, "write_text", counting_write_text):
            with patch("doxtr_doto.sync.get_doto_sync_data", return_value=sync_data):
                write_rst_updates(mock_app, None)

        # File should not be written since no content changed
        assert write_count == 0

    def test_skips_on_build_exception(
        self,
        mock_app: MagicMock,
        tmp_path: Path,
    ) -> None:
        """No updates should be written if build had an exception."""
        rst_file = tmp_path / "tasks.rst"
        rst_file.write_text("""\
.. doto:: Task
   :id: TASK-001
   :status: open
""")
        original_content = rst_file.read_text()

        sync_data = {
            "rst_updates": [
                (SyncAction.UPDATE, "tasks.rst", "TASK-001", {"id": "TASK-001", "status": "done"}),
            ]
        }

        with patch("doxtr_doto.sync.get_doto_sync_data", return_value=sync_data):
            # Pass an exception to indicate build failure
            write_rst_updates(mock_app, RuntimeError("Build failed"))

        # File should be unchanged
        assert rst_file.read_text() == original_content

    def test_create_and_update_in_same_batch(
        self,
        mock_app: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Handle CREATE and UPDATE actions in the same batch."""
        rst_file = tmp_path / "tasks.rst"
        rst_file.write_text("""\
.. doto:: Existing Task
   :id: TASK-001
   :status: open
""")

        sync_data = {
            "rst_updates": [
                (SyncAction.UPDATE, "tasks.rst", "TASK-001", {"id": "TASK-001", "status": "done"}),
                (
                    SyncAction.CREATE,
                    "tasks.rst",
                    "TASK-002",
                    {"id": "TASK-002", "title": "New Task", "status": "open"},
                ),
            ]
        }

        with patch("doxtr_doto.sync.get_doto_sync_data", return_value=sync_data):
            write_rst_updates(mock_app, None)

        content = rst_file.read_text()
        # Both tasks should be present
        assert "TASK-001" in content
        assert "TASK-002" in content
        # TASK-001 should be updated
        assert ":status: done" in content or "done" in content

    def test_remove_action_in_batch(
        self,
        mock_app: MagicMock,
        rst_file_with_tasks: Path,
        tmp_path: Path,
    ) -> None:
        """Handle REMOVE action in a batch."""
        rst_file_rel = str(rst_file_with_tasks.relative_to(tmp_path))

        sync_data = {
            "rst_updates": [
                (SyncAction.UPDATE, rst_file_rel, "TASK-001", {"id": "TASK-001", "status": "done"}),
                (SyncAction.REMOVE, rst_file_rel, "TASK-002", {}),
            ]
        }

        with patch("doxtr_doto.sync.get_doto_sync_data", return_value=sync_data):
            write_rst_updates(mock_app, None)

        content = rst_file_with_tasks.read_text()
        # TASK-001 should be updated
        assert "TASK-001" in content
        # TASK-002 should be removed
        assert "TASK-002" not in content
        # TASK-003 should still be present (unchanged)
        assert "TASK-003" in content


class TestBareDirectiveBatchOrdering:
    """Regression: a batch of UPDATEs on *bare* directives must not corrupt.

    Several bare ``.. doto::`` directives (no ``:id:``) in one file each get an
    UPDATE carrying the task's auto-generated id plus the ORIGINAL line number.
    Applying them top-to-bottom shifts every later directive down as the first
    gains an injected ``:id:``, so the stale line numbers of later updates miss
    (silent no-op) or hit the wrong directive (duplicate ``:id:`` / consumed
    blank line between directives). The fix applies line-based updates
    bottom-to-top so earlier line numbers stay valid, and guards id injection
    with an authoritative whole-file id lookup.
    """

    def _run(self, tmp_path: Path, rst_text: str, updates: list) -> str:
        from doxtr_doto.sync import _process_file_updates

        rst = tmp_path / "tasks.rst"
        rst.write_text(rst_text)
        app = MagicMock()
        app.srcdir = str(tmp_path)
        app.env = None  # force the raw-path branch (no doc2path)
        logger = MagicMock()
        _process_file_updates(app, "tasks.rst", updates, logger)
        return rst.read_text()

    def test_batch_update_bare_directives_no_corruption(self, tmp_path: Path):
        rst_text = (
            ".. doto:: First task\n"
            "   :assignee: alice\n"
            "\n"
            ".. doto:: Second task\n"
            "   :assignee: bob\n"
            "\n"
            ".. doto:: Third task\n"
            "   :assignee: carol\n"
        )
        # Original header lines: 1, 4, 7.
        updates = [
            (SyncAction.UPDATE, "noter-L1", {"id": "noter-L1", "status": "done", "_rst_line": 1}),
            (SyncAction.UPDATE, "noter-L4", {"id": "noter-L4", "status": "done", "_rst_line": 4}),
            (SyncAction.UPDATE, "noter-L7", {"id": "noter-L7", "status": "done", "_rst_line": 7}),
        ]
        out = self._run(tmp_path, rst_text, updates)

        # (a) No duplicate :id: on any directive.
        for n in (1, 4, 7):
            assert out.count(f":id: noter-L{n}") == 1, f"L{n} id count\n{out}"
        # (b) All three directives were actually updated.
        assert out.count(":status: done") == 3, out
        # (c) Each directive got exactly its own id (bottom-up kept lines valid).
        assert ":id: noter-L1" in out
        assert ":id: noter-L4" in out
        assert ":id: noter-L7" in out
        # (d) The blank lines separating directives are preserved: three
        #     directive headers remain, none run together. Each header must
        #     start a line (either at the very start or after a newline), so
        #     no directive is concatenated onto a prior option line.
        assert out.count(".. doto::") == 3
        headers = [ln for ln in out.splitlines() if ln.startswith(".. doto::")]
        assert len(headers) == 3, out
        # A blank line precedes each directive after the first.
        assert out.count("\n\n.. doto::") == 2, out

    def test_batch_update_already_has_ids_no_duplicate(self, tmp_path: Path):
        """If ids are already present, a line-carrying UPDATE must not re-add."""
        rst_text = (
            ".. doto:: First\n"
            "   :id: noter-L1\n"
            "   :status: open\n"
            "\n"
            ".. doto:: Second\n"
            "   :id: noter-L5\n"
            "   :status: open\n"
        )
        updates = [
            (SyncAction.UPDATE, "noter-L1", {"id": "noter-L1", "status": "done", "_rst_line": 1}),
            (SyncAction.UPDATE, "noter-L5", {"id": "noter-L5", "status": "done", "_rst_line": 5}),
        ]
        out = self._run(tmp_path, rst_text, updates)
        assert out.count(":id: noter-L1") == 1
        assert out.count(":id: noter-L5") == 1
        assert out.count(":status: done") == 2
