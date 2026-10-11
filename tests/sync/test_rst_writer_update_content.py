"""Regression tests for in-place directive updates (write-back correctness).

These cover a bug where ``SyncAction.UPDATE`` (triggered by a TUI/CLI edit that
changed ``tasks.json`` only) wrote the *full* merged task dict back into the
RST directive. ``_update_directive_content`` treated every field as an option,
so it emitted ``:title:`` and ``:body:`` options (which are really the
directive argument and content block) and inserted new options *after* the
blank line — i.e. into the body — corrupting the directive like::

    .. doto:: Original title
       :id: TASK-100
       :status: done

       :title: Original title
       :priority: medium
       Original body.

The corrupted directive stopped rendering the update. The fix keeps ``title``
on the ``.. doto::`` argument line, rewrites ``body`` as the content block, and
inserts/updates all other fields as options within the option block.
"""

from __future__ import annotations

from doxtr_doto.sync.rst_writer import (
    _update_directive_content,
    update_directive_in_content,
)


class TestUpdateDoesNotCorruptDirective:
    """Updating fields must keep the directive structurally valid."""

    def test_full_merged_dict_does_not_leak_options_into_body(self):
        """Passing the full merged dict must not emit :title:/:body: options."""
        block = ".. doto:: Original title\n   :id: TASK-100\n   :status: open\n\n   Original body."
        # This mirrors _queue_rst_update, which passes the whole merged task.
        updates = {
            "title": "Original title",
            "priority": "medium",
            "status": "done",
            "id": "TASK-100",
            "body": "Original body.",
        }
        result = _update_directive_content(block, updates)

        # Status updated in place.
        assert "   :status: done" in result
        # title/body are NOT emitted as options.
        assert ":title:" not in result
        assert ":body:" not in result
        # The id is preserved.
        assert "   :id: TASK-100" in result
        # The directive argument (title) is intact on the marker line.
        assert result.splitlines()[0] == ".. doto:: Original title"
        # Body appears exactly once, in the content block (not duplicated).
        assert result.count("Original body.") == 1

    def test_new_option_inserted_within_option_block(self):
        """A newly-added option lands above the body, not inside it."""
        block = ".. doto:: T\n   :id: X-1\n   :status: open\n\n   Body text."
        result = _update_directive_content(block, {"priority": "high"})
        lines = result.splitlines()
        # Options are contiguous after the marker; the blank line then body.
        assert lines[0] == ".. doto:: T"
        option_lines = [i for i, ln in enumerate(lines) if ln.strip().startswith(":")]
        blank_idx = lines.index("")
        # Every option precedes the blank line separating options from body.
        assert all(i < blank_idx for i in option_lines)
        assert "   :priority: high" in result

    def test_title_change_rewrites_argument_line(self):
        """A title change updates the .. doto:: argument, not an option."""
        block = ".. doto:: Old title\n   :id: X-1\n   :status: open"
        result = _update_directive_content(block, {"title": "New title", "status": "open"})
        assert result.splitlines()[0] == ".. doto:: New title"
        assert ":title:" not in result


class TestUpdateBodySync:
    """A body change must rewrite the directive's content block."""

    def test_body_change_replaces_content_block(self):
        block = ".. doto:: T\n   :id: X-1\n   :status: open\n\n   Old line one.\n   Old line two."
        result = _update_directive_content(block, {"body": "New body.\nSecond line."})
        assert "Old line one." not in result
        assert "Old line two." not in result
        assert "   New body." in result
        assert "   Second line." in result
        # id/status preserved.
        assert "   :id: X-1" in result
        assert "   :status: open" in result

    def test_empty_body_clears_content_block(self):
        block = ".. doto:: T\n   :id: X-1\n   :status: open\n\n   Some body."
        result = _update_directive_content(block, {"body": ""})
        assert "Some body." not in result
        assert "   :status: open" in result

    def test_body_added_to_directive_without_body(self):
        block = ".. doto:: T\n   :id: X-1\n   :status: open"
        result = _update_directive_content(block, {"body": "Fresh body."})
        assert result.splitlines()[-1] == "   Fresh body."

    def test_body_untouched_when_not_in_updates(self):
        block = ".. doto:: T\n   :id: X-1\n   :status: open\n\n   Keep this body."
        result = _update_directive_content(block, {"status": "done"})
        assert "   Keep this body." in result
        assert "   :status: done" in result


class TestUpdateDirectiveInContentRoundTrip:
    """update_directive_in_content splices the fixed block back correctly."""

    def test_status_update_preserves_surrounding_content(self):
        content = (
            "Doc\n"
            "===\n"
            "\n"
            ".. doto:: My task\n"
            "   :id: TASK-5\n"
            "   :status: open\n"
            "\n"
            "   Body paragraph.\n"
            "\n"
            "Trailing prose after the directive.\n"
        )
        result = update_directive_in_content(
            content, "TASK-5", {"title": "My task", "status": "done", "id": "TASK-5"}
        )
        assert ":status: done" in result
        assert ":title:" not in result
        assert "Trailing prose after the directive." in result
        # Directive argument and body preserved.
        assert ".. doto:: My task" in result
        assert "   Body paragraph." in result


class TestUpdateBareDirectiveByLine:
    """UPDATE must locate a bare directive (no :id:) by line number.

    Mirrors the reported bug: ``doto done`` on a directive with no ``:id:``
    produced no RST change because the write-back matched only by ``:id:``.
    The updater now falls back to the directive's line number and injects the
    ``:id:`` so the directive becomes self-identifying.
    """

    def test_update_bare_directive_injects_id_and_status(self):
        content = ".. doto:: Document the decision\n   :assignee: :xlink:`yourdirectory-person-alice-bobbington`\n"
        result = update_directive_in_content(
            content,
            "noter-L1",
            {"status": "done", "_rst_line": 1},
            rst_line=1,
        )
        assert ":id: noter-L1" in result
        assert ":status: done" in result
        # Assignee role preserved verbatim.
        assert ":assignee: :xlink:`yourdirectory-person-alice-bobbington`" in result
        # No bogus internal option leaked in.
        assert ":_rst_line:" not in result
        # id appears right after the marker (first option).
        lines = result.splitlines()
        assert lines[0].startswith(".. doto::")
        assert lines[1].strip() == ":id: noter-L1"

    def test_second_update_matches_by_injected_id(self):
        content = ".. doto:: T\n   :assignee: alice\n"
        once = update_directive_in_content(
            content, "noter-L1", {"status": "done", "_rst_line": 1}, rst_line=1
        )
        twice = update_directive_in_content(
            once, "noter-L1", {"status": "open", "_rst_line": 1}, rst_line=1
        )
        # No duplicate id; status updated in place.
        assert twice.count(":id: noter-L1") == 1
        assert ":status: open" in twice

    def test_no_line_fallback_without_rst_line(self):
        """Without rst_line, a bare directive is still a no-op (safe default)."""
        content = ".. doto:: T\n   :assignee: alice\n"
        result = update_directive_in_content(content, "noter-L1", {"status": "done"})
        assert result == content

    def test_explicit_id_wins_over_line_fallback(self):
        """When a directive has the id, it matches by id, not line."""
        content = (
            ".. doto:: First\n"
            "   :id: KEEP-1\n"
            "   :status: open\n"
            "\n"
            ".. doto:: Second\n"
            "   :id: KEEP-2\n"
            "   :status: open\n"
        )
        # rst_line points at the first directive, but task id is KEEP-2.
        result = update_directive_in_content(
            content, "KEEP-2", {"status": "done", "_rst_line": 1}, rst_line=1
        )
        # KEEP-2 (second directive) is the one updated, not the line-1 one.
        assert "KEEP-1\n   :status: open" in result
        second = result.split(".. doto:: Second")[1]
        assert ":status: done" in second


class TestUpdateNeverDuplicatesId:
    """UPDATE must never emit a second :id: when one already exists.

    The write-back passes the full merged task dict (which always carries
    ``id``). When the directive already has that id, the ``id`` must be dropped
    from the applied options so a stale line number cannot cause a duplicate
    ``:id:`` line (the reported corruption).
    """

    def test_update_with_id_and_line_does_not_duplicate_existing_id(self):
        content = ".. doto:: First\n   :id: noter-L1\n   :status: open\n"
        # Full merged dict carries id + a stale-ish rst_line pointing at the
        # directive header; the id is already present.
        result = update_directive_in_content(
            content,
            "noter-L1",
            {"id": "noter-L1", "status": "done", "_rst_line": 1},
            rst_line=1,
        )
        assert result.count(":id: noter-L1") == 1
        assert ":status: done" in result

    def test_update_by_id_ignores_id_in_updates(self):
        """Matching by id (no rst_line) still never re-emits the id."""
        content = ".. doto:: First\n   :id: KEEP-1\n   :status: open\n"
        result = update_directive_in_content(
            content, "KEEP-1", {"id": "KEEP-1", "priority": "high"}
        )
        assert result.count(":id: KEEP-1") == 1
        assert ":priority: high" in result


class TestEmptyBodyPreservesTerminator:
    """An empty-body UPDATE must not strip the directive's trailing newline.

    The write-back passes the full merged dict, which always carries ``body``
    (often ``''``). When that empty-body replace ran on a directive whose block
    ended with a newline, it stripped the terminator, so the directive ran into
    the next one. The block's structural trailing newline must be preserved.
    """

    def test_empty_body_update_keeps_separation_from_next_directive(self):
        content = (
            ".. doto:: A\n   :id: X\n   :assignee: a\n\n.. doto:: B\n   :id: Y\n   :assignee: b\n"
        )
        result = update_directive_in_content(
            content, "Y", {"id": "Y", "status": "done", "body": ""}
        )
        # The updated directive keeps a trailing newline and does not merge
        # with anything after it.
        assert result.endswith("\n")
        assert ":status: done" in result
        # A would still be separated from B if there were content after B;
        # here just assert the terminator and no accidental run-together.
        assert ":status: done\n.. doto::" not in result

    def test_empty_body_update_middle_directive_keeps_blank_lines(self):
        content = (
            ".. doto:: A\n"
            "   :id: X\n"
            "   :assignee: a\n"
            "\n"
            ".. doto:: B\n"
            "   :id: Y\n"
            "   :assignee: b\n"
            "\n"
            ".. doto:: C\n"
            "   :id: Z\n"
            "   :assignee: c\n"
        )
        result = update_directive_in_content(
            content, "Y", {"id": "Y", "status": "done", "body": ""}
        )
        # B gained :status: done but B and C are still blank-line separated.
        assert result.count("\n\n.. doto:: C") == 1, result
        assert ":status: done\n.. doto::" not in result
