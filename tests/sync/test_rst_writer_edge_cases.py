"""Edge case tests for RST writer.

Tests for generate_directive_text edge cases.
Note: Tests involving RST parsing with doto directives are in test_rst_insertion.py
and test_rst_removal.py to avoid test ordering issues with Sphinx directive registration.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from doxtr_doto.exceptions import DotoValidationError
from doxtr_doto.sync.rst_writer import (
    generate_directive_text,
    insert_doto_directive,
    remove_doto_directive,
    update_doto_directive,
)


class TestGenerateDirectiveText:
    """Tests for directive text generation edge cases."""

    def test_generate_missing_id_raises(self):
        """Should raise ValueError if id is missing."""
        with pytest.raises(ValueError, match="requires 'id'"):
            generate_directive_text({"title": "Test"})

    def test_generate_empty_id_raises(self):
        """Should raise ValueError if id is empty."""
        with pytest.raises(ValueError, match="requires 'id'"):
            generate_directive_text({"id": "", "title": "Test"})

    def test_generate_with_special_characters_in_title(self):
        """Title with special RST characters should be preserved."""
        result = generate_directive_text(
            {
                "id": "TEST-001",
                "title": "Fix *bold* and ``code``",
            }
        )
        assert "Fix *bold* and ``code``" in result
        assert ":id: TEST-001" in result

    def test_generate_with_multiline_body(self):
        """Body with multiple lines should be properly indented."""
        result = generate_directive_text(
            {
                "id": "TEST-001",
                "title": "Test",
                "body": "Line 1\nLine 2\nLine 3",
            }
        )
        lines = result.split("\n")
        body_lines = [line for line in lines if "Line" in line]
        # All body lines should be indented with 3 spaces
        assert len(body_lines) == 3
        assert all(line.startswith("   ") for line in body_lines)

    def test_generate_with_empty_tags_list(self):
        """Empty tags list should not add :tags: line."""
        result = generate_directive_text(
            {
                "id": "TEST-001",
                "title": "Test",
                "tags": [],
            }
        )
        assert ":tags:" not in result

    def test_generate_with_tags_list(self):
        """Tags list should be comma-separated."""
        result = generate_directive_text(
            {
                "id": "TEST-001",
                "title": "Test",
                "tags": ["one", "two", "three"],
            }
        )
        assert ":tags: one, two, three" in result

    def test_generate_with_depends_on_list(self):
        """depends_on list should be comma-separated."""
        result = generate_directive_text(
            {
                "id": "TEST-001",
                "title": "Test",
                "depends_on": ["DEP-001", "DEP-002"],
            }
        )
        assert ":depends-on: DEP-001, DEP-002" in result

    def test_generate_omits_default_priority(self):
        """Default priority 'medium' should be omitted."""
        result = generate_directive_text(
            {
                "id": "TEST-001",
                "title": "Test",
                "priority": "medium",
            }
        )
        assert ":priority:" not in result

    def test_generate_includes_non_default_priority(self):
        """Non-default priority should be included."""
        result = generate_directive_text(
            {
                "id": "TEST-001",
                "title": "Test",
                "priority": "high",
            }
        )
        assert ":priority: high" in result

    def test_generate_omits_default_status(self):
        """Default status 'open' should be omitted."""
        result = generate_directive_text(
            {
                "id": "TEST-001",
                "title": "Test",
                "status": "open",
            }
        )
        assert ":status:" not in result

    def test_generate_includes_non_default_status(self):
        """Non-default status should be included."""
        result = generate_directive_text(
            {
                "id": "TEST-001",
                "title": "Test",
                "status": "in-progress",
            }
        )
        assert ":status: in-progress" in result

    def test_generate_with_due_date(self):
        """Due date should be included."""
        result = generate_directive_text(
            {
                "id": "TEST-001",
                "title": "Test",
                "due": "2026-12-31",
            }
        )
        assert ":due: 2026-12-31" in result

    def test_generate_with_assignee(self):
        """Assignee should be included."""
        result = generate_directive_text(
            {
                "id": "TEST-001",
                "title": "Test",
                "assignee": "alice",
            }
        )
        assert ":assignee: alice" in result

    def test_generate_with_empty_body(self):
        """Empty body should not add extra content."""
        result = generate_directive_text(
            {
                "id": "TEST-001",
                "title": "Test",
                "body": "",
            }
        )
        # Should just have directive and id
        lines = [line for line in result.split("\n") if line.strip()]
        assert len(lines) == 2

    def test_generate_with_all_fields(self):
        """Should generate directive with all fields."""
        result = generate_directive_text(
            {
                "id": "TEST-001",
                "title": "Full task",
                "assignee": "alice",
                "priority": "high",
                "status": "in-progress",
                "due": "2026-12-31",
                "tags": ["feature", "urgent"],
                "depends_on": ["DEP-001"],
                "body": "Task description.",
            }
        )
        assert ".. doto:: Full task" in result
        assert ":id: TEST-001" in result
        assert ":assignee: alice" in result
        assert ":priority: high" in result
        assert ":status: in-progress" in result
        assert ":due: 2026-12-31" in result
        assert ":tags: feature, urgent" in result
        assert ":depends-on: DEP-001" in result
        assert "Task description." in result

    def test_generate_multiline_title_collapses_to_single_line(self):
        """A hard-wrapped title (single newlines) is emitted on ONE line.

        reST does not need manual title line breaks (the editor/view wraps long
        lines), so single newlines are collapsed to spaces and the whole title
        sits on the ``.. doto::`` marker. The ``:id:`` option follows
        immediately, with no orphaned option block.
        """
        result = generate_directive_text(
            {
                "id": "TEST-001",
                "title": "A very long title\nthat wraps onto\nthree lines",
                "priority": "high",
            }
        )
        lines = result.split("\n")
        assert lines[0] == ".. doto:: A very long title that wraps onto three lines"
        # The option block follows the single-line title with no orphaning.
        assert lines[1] == "   :id: TEST-001"
        assert "   :priority: high" in lines

    def test_generate_singleline_title_roundtrips_through_parser(self):
        """A hard-wrapped title round-trips as a single argument with options.

        Parsing the generated directive back recovers exactly one directive
        whose single argument is the collapsed one-line title, with the
        ``:id:``/options intact (no orphaning).
        """
        from doxtr_doto.sync.rst_writer import _parse_rst_for_directives

        result = generate_directive_text(
            {
                "id": "TEST-001",
                "title": "A very long title\nthat wraps onto\nthree lines",
                "priority": "high",
            }
        )
        parsed = _parse_rst_for_directives(result + "\n")
        assert len(parsed) == 1
        info = parsed[0]
        assert len(info["arguments"]) == 1
        assert info["arguments"][0] == "A very long title that wraps onto three lines"
        # The option block survived intact.
        assert info["options"].get("id") == "TEST-001"
        assert info["options"].get("priority") == "high"

    def test_generate_multiparagraph_title_relocates_to_body(self):
        """A title with a blank-line paragraph break moves extras to the body.

        Only the FIRST paragraph can be the directive argument; the remaining
        paragraph(s) are relocated into the directive body, indented 3 spaces
        and blank-line separated. The round-trip recovers one directive whose
        argument is the first paragraph and whose body carries the rest.
        """
        from doxtr_doto.sync.rst_writer import _parse_rst_for_directives

        result = generate_directive_text(
            {
                "id": "TEST-001",
                "title": "First paragraph title\nwrapped\n\nSecond paragraph here",
                "priority": "high",
            }
        )
        lines = result.split("\n")
        assert lines[0] == ".. doto:: First paragraph title wrapped"
        assert lines[1] == "   :id: TEST-001"
        # The relocated paragraph appears in the body, 3-space indented.
        assert "   Second paragraph here" in lines

        parsed = _parse_rst_for_directives(result + "\n")
        assert len(parsed) == 1
        info = parsed[0]
        assert info["arguments"][0] == "First paragraph title wrapped"
        assert info["options"].get("id") == "TEST-001"
        assert "Second paragraph here" in "\n".join(info["content"])

    def test_generate_multiparagraph_title_prepends_to_existing_body(self):
        """Relocated title paragraphs are prepended to a pre-existing body.

        The extra title paragraph(s) go into the body ahead of any existing
        body text, separated by a blank line, so neither is lost. The parse
        recovers the first title paragraph as the argument and both the
        relocated paragraph and the original body in the directive content.
        """
        from doxtr_doto.sync.rst_writer import _parse_rst_for_directives

        result = generate_directive_text(
            {
                "id": "TEST-001",
                "title": "Title paragraph\n\nExtra title paragraph",
                "body": "Original body text.",
            }
        )
        lines = result.split("\n")
        assert lines[0] == ".. doto:: Title paragraph"
        # Both the relocated title paragraph and the original body are present,
        # with the relocated paragraph first.
        extra_idx = lines.index("   Extra title paragraph")
        body_idx = lines.index("   Original body text.")
        assert extra_idx < body_idx
        # A blank line separates the two paragraphs.
        assert lines[extra_idx + 1] == ""

        parsed = _parse_rst_for_directives(result + "\n")
        assert len(parsed) == 1
        info = parsed[0]
        assert info["arguments"][0] == "Title paragraph"
        joined_body = "\n".join(info["content"])
        assert "Extra title paragraph" in joined_body
        assert "Original body text." in joined_body


class TestInsertDotoDirectiveValidation:
    """Tests for insert_doto_directive validation (no RST parsing)."""

    def test_insert_creates_file_if_missing(self, tmp_path: Path):
        """Should create file if it doesn't exist."""
        rst_file = tmp_path / "new.rst"

        success = insert_doto_directive(
            rst_file,
            {
                "id": "NEW-001",
                "title": "New task",
            },
        )

        assert success
        assert rst_file.exists()
        assert "NEW-001" in rst_file.read_text()

    def test_insert_creates_parent_dirs(self, tmp_path: Path):
        """Should create parent directories."""
        rst_file = tmp_path / "subdir" / "deep" / "new.rst"

        success = insert_doto_directive(
            rst_file,
            {
                "id": "NEW-001",
                "title": "New task",
            },
        )

        assert success
        assert rst_file.exists()
        content = rst_file.read_text()
        assert "NEW-001" in content

    def test_insert_without_id_raises(self, tmp_path: Path):
        """Should raise DotoValidationError if id is missing."""
        rst_file = tmp_path / "tasks.rst"

        with pytest.raises(DotoValidationError, match="'id'"):
            insert_doto_directive(rst_file, {"title": "Test"})

    def test_insert_with_empty_id_raises(self, tmp_path: Path):
        """Should raise DotoValidationError if id is empty."""
        rst_file = tmp_path / "tasks.rst"

        with pytest.raises((DotoValidationError, ValueError)):
            insert_doto_directive(rst_file, {"id": "", "title": "Test"})

    def test_insert_with_after_line(self, tmp_path: Path):
        """Should insert after specified line (no doto directives to parse)."""
        rst_file = tmp_path / "tasks.rst"
        rst_file.write_text("Line 1\nLine 2\nLine 3\n")

        success = insert_doto_directive(
            rst_file,
            {
                "id": "TASK-001",
                "title": "Inserted Task",
            },
            after_line=2,
        )

        assert success
        content = rst_file.read_text()
        # Task should appear after Line 2
        pos_line2 = content.find("Line 2")
        pos_task = content.find("TASK-001")
        assert pos_line2 < pos_task

    def test_insert_into_empty_file(self, tmp_path: Path):
        """Should insert into empty file."""
        rst_file = tmp_path / "empty.rst"
        rst_file.write_text("")

        success = insert_doto_directive(
            rst_file,
            {
                "id": "TASK-001",
                "title": "First task",
            },
        )

        assert success
        content = rst_file.read_text()
        assert "TASK-001" in content
        assert ".. doto:: First task" in content

    def test_insert_multiline_title_parses_as_single_directive(self, tmp_path: Path):
        """End-to-end: inserting a multi-line-title directive yields ONE directive.

        Regression for the multi-line-title duplication cascade: emitting the
        raw title newline verbatim orphaned the ``:id:``/option block, which
        made the task look missing and caused duplicate re-insertions. Now the
        hard-wrapped title is collapsed to a single endless line. Insert via the
        real public API, re-parse the file with the real parser, and assert
        exactly one directive is found with its ``:id:`` intact and the full
        title recovered as a single argument.
        """
        from doxtr_doto.sync.rst_writer import _parse_rst_for_directives

        rst_file = tmp_path / "tasks.rst"
        rst_file.write_text("Page Title\n==========\n\nIntro paragraph.\n")

        success = insert_doto_directive(
            rst_file,
            {
                "id": "ML-001",
                "title": "A long task title\nthat wraps onto a\nsecond and third line",
                "priority": "high",
            },
        )
        assert success

        parsed = _parse_rst_for_directives(rst_file.read_text())
        # Exactly one directive, no orphaned-option duplication cascade.
        assert len(parsed) == 1
        assert parsed[0]["options"].get("id") == "ML-001"
        # The whole hard-wrapped title round-trips as a single argument.
        assert parsed[0]["arguments"][0] == (
            "A long task title that wraps onto a second and third line"
        )


class TestRemoveDotoDirectiveValidation:
    """Tests for remove_doto_directive validation (no RST parsing)."""

    def test_remove_nonexistent_file_returns_false(self, tmp_path: Path):
        """Should return False for missing file."""
        rst_file = tmp_path / "missing.rst"

        result = remove_doto_directive(rst_file, "TASK-001")

        assert result is False

    def test_remove_empty_task_id_raises(self, tmp_path: Path):
        """Should raise DotoValidationError for empty task_id."""
        rst_file = tmp_path / "tasks.rst"
        rst_file.write_text("content")

        with pytest.raises(DotoValidationError):
            remove_doto_directive(rst_file, "")


class TestUpdateDotoDirectiveValidation:
    """Tests for update_doto_directive validation (no RST parsing)."""

    def test_update_nonexistent_returns_false(self, tmp_path: Path):
        """Should return False if task not found."""
        rst_file = tmp_path / "tasks.rst"
        rst_file.write_text("No tasks here.")

        result = update_doto_directive(rst_file, "TASK-001", {"priority": "high"})

        assert result is False

    def test_update_empty_task_id_raises(self, tmp_path: Path):
        """Should raise DotoValidationError for empty task_id."""
        rst_file = tmp_path / "tasks.rst"
        rst_file.write_text("content")

        with pytest.raises(DotoValidationError):
            update_doto_directive(rst_file, "", {"priority": "high"})

    def test_update_nonexistent_file_returns_false(self, tmp_path: Path):
        """Should return False for nonexistent file."""
        rst_file = tmp_path / "missing.rst"

        result = update_doto_directive(rst_file, "TASK-001", {"priority": "high"})

        assert result is False


class TestDirectiveRendererSeam:
    """Tests for the overridable directive-rendering seam."""

    def test_register_renderer_is_used_by_internal_insert_then_resets(self, tmp_path: Path):
        """A registered renderer drives internal insertion; reset restores default.

        ``insert_doto_directive`` renders through ``render_directive_text``, so a
        renderer registered via ``register_directive_renderer`` must appear in
        the written file. After ``reset_directive_renderer`` the built-in
        default (``generate_directive_text``) is used again.
        """
        from doxtr_doto.sync.rst_writer import (
            register_directive_renderer,
            reset_directive_renderer,
        )

        def _custom(task_data: dict) -> str:
            return f".. doto:: CUSTOM {task_data['id']}\n   :id: {task_data['id']}"

        try:
            register_directive_renderer(_custom)
            custom_file = tmp_path / "custom.rst"
            insert_doto_directive(custom_file, {"id": "SEAM-001", "title": "Ignored"})
            content = custom_file.read_text()
            assert ".. doto:: CUSTOM SEAM-001" in content
            assert "Ignored" not in content
        finally:
            reset_directive_renderer()

        # Default behavior restored: the title is rendered again.
        default_file = tmp_path / "default.rst"
        insert_doto_directive(default_file, {"id": "SEAM-002", "title": "Real title"})
        default_content = default_file.read_text()
        assert ".. doto:: Real title" in default_content
        assert "CUSTOM" not in default_content
