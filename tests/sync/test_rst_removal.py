"""Tests for RST directive removal functionality."""

from __future__ import annotations


class TestRemoveDotoDirective:
    """Test the remove_doto_directive function."""

    def test_remove_simple_directive(self, tmp_path):
        """Test removing a simple doto directive."""
        from doxtr_doto.sync.rst_writer import remove_doto_directive

        rst_file = tmp_path / "tasks.rst"
        rst_file.write_text("""Tasks
=====

.. doto:: Fix the bug
   :id: TASK-001
   :priority: high
   :status: open

   This is the description.

Some other content.
""")

        result = remove_doto_directive(rst_file, "TASK-001")

        assert result is True
        content = rst_file.read_text()
        assert "TASK-001" not in content
        assert "Some other content" in content
        assert "Tasks" in content

    def test_remove_directive_preserves_others(self, tmp_path):
        """Test that removing one directive preserves others."""
        from doxtr_doto.sync.rst_writer import remove_doto_directive

        rst_file = tmp_path / "tasks.rst"
        rst_file.write_text("""Tasks
=====

.. doto:: First task
   :id: TASK-001
   :priority: high

   First description.

.. doto:: Second task
   :id: TASK-002
   :priority: medium

   Second description.

.. doto:: Third task
   :id: TASK-003
   :priority: low

   Third description.
""")

        result = remove_doto_directive(rst_file, "TASK-002")

        assert result is True
        content = rst_file.read_text()
        assert "TASK-001" in content
        assert "TASK-002" not in content
        assert "TASK-003" in content
        assert "First task" in content
        assert "Second task" not in content
        assert "Third task" in content

    def test_remove_directive_not_found(self, tmp_path):
        """Test removing a non-existent directive returns False."""
        from doxtr_doto.sync.rst_writer import remove_doto_directive

        rst_file = tmp_path / "tasks.rst"
        rst_file.write_text("""Tasks
=====

.. doto:: Existing task
   :id: TASK-001
   :priority: high

   Description.
""")

        result = remove_doto_directive(rst_file, "NONEXISTENT")

        assert result is False
        content = rst_file.read_text()
        assert "TASK-001" in content

    def test_remove_directive_file_not_found(self, tmp_path):
        """Test removing from non-existent file returns False."""
        from doxtr_doto.sync.rst_writer import remove_doto_directive

        rst_file = tmp_path / "nonexistent.rst"

        result = remove_doto_directive(rst_file, "TASK-001")

        assert result is False

    def test_remove_directive_with_all_options(self, tmp_path):
        """Test removing a directive with all possible options."""
        from doxtr_doto.sync.rst_writer import remove_doto_directive

        rst_file = tmp_path / "tasks.rst"
        rst_file.write_text("""Tasks
=====

.. doto:: Complete task with all options
   :id: TASK-FULL
   :assignee: alice
   :priority: critical
   :status: in-progress
   :due: 2026-12-31
   :tags: feature, urgent, frontend
   :depends-on: TASK-001, TASK-002
   :created: 2026-01-01
   :updated: 2026-07-26

   This task has a multi-paragraph body.

   It includes all possible options.

Remaining content.
""")

        result = remove_doto_directive(rst_file, "TASK-FULL")

        assert result is True
        content = rst_file.read_text()
        assert "TASK-FULL" not in content
        assert "alice" not in content
        assert "Remaining content" in content

    def test_remove_directive_cleans_blank_lines(self, tmp_path):
        """Test that removal doesn't leave excessive blank lines."""
        from doxtr_doto.sync.rst_writer import remove_doto_directive

        rst_file = tmp_path / "tasks.rst"
        rst_file.write_text("""Tasks
=====

.. doto:: Task to remove
   :id: TASK-001

   Description.

Next section
------------

Content here.
""")

        result = remove_doto_directive(rst_file, "TASK-001")

        assert result is True
        content = rst_file.read_text()

        # Should not have more than 2 consecutive newlines
        assert "\n\n\n\n" not in content


class TestGenerateDirectiveText:
    """Test the generate_directive_text function."""

    def test_generate_minimal_directive(self):
        """Test generating a minimal directive."""
        from doxtr_doto.sync.rst_writer import generate_directive_text

        task_data = {
            "title": "Simple task",
            "id": "TASK-001",
        }

        result = generate_directive_text(task_data)

        assert ".. doto:: Simple task" in result
        assert ":id: TASK-001" in result

    def test_generate_full_directive(self):
        """Test generating a directive with all options."""
        from doxtr_doto.sync.rst_writer import generate_directive_text

        task_data = {
            "title": "Full task",
            "id": "TASK-FULL",
            "assignee": "bob",
            "priority": "high",
            "status": "in-progress",
            "due": "2026-12-31",
            "tags": ["backend", "urgent"],
            "depends_on": ["TASK-001", "TASK-002"],
            "body": "This is the task description.",
        }

        result = generate_directive_text(task_data)

        assert ".. doto:: Full task" in result
        assert ":id: TASK-FULL" in result
        assert ":assignee: bob" in result
        assert ":priority: high" in result
        assert ":status: in-progress" in result
        assert ":due: 2026-12-31" in result
        assert ":tags: backend, urgent" in result
        assert ":depends-on: TASK-001, TASK-002" in result
        assert "This is the task description." in result

    def test_generate_skips_default_values(self):
        """Test that default values are not included."""
        from doxtr_doto.sync.rst_writer import generate_directive_text

        task_data = {
            "title": "Task with defaults",
            "id": "TASK-001",
            "priority": "medium",  # Default - should be skipped
            "status": "open",  # Default - should be skipped
        }

        result = generate_directive_text(task_data)

        assert ":priority:" not in result
        assert ":status:" not in result

    def test_generate_multiline_body(self):
        """Test generating directive with multiline body."""
        from doxtr_doto.sync.rst_writer import generate_directive_text

        task_data = {
            "title": "Task with long description",
            "id": "TASK-001",
            "body": "First paragraph.\n\nSecond paragraph with more details.",
        }

        result = generate_directive_text(task_data)

        assert "First paragraph." in result
        assert "Second paragraph" in result


class TestInsertDotoDirective:
    """Test the insert_doto_directive function."""

    def test_insert_into_empty_file(self, tmp_path):
        """Test inserting into a non-existent file."""
        from doxtr_doto.sync.rst_writer import insert_doto_directive

        rst_file = tmp_path / "new_tasks.rst"

        task_data = {
            "title": "New task",
            "id": "TASK-NEW",
            "priority": "high",
        }

        result = insert_doto_directive(rst_file, task_data)

        assert result is True
        assert rst_file.exists()

        content = rst_file.read_text()
        assert ".. doto:: New task" in content
        assert ":id: TASK-NEW" in content

    def test_insert_at_end_of_file(self, tmp_path):
        """Test inserting at the end of an existing file."""
        from doxtr_doto.sync.rst_writer import insert_doto_directive

        rst_file = tmp_path / "tasks.rst"
        rst_file.write_text("""Tasks
=====

Existing content.
""")

        task_data = {
            "title": "Appended task",
            "id": "TASK-APPEND",
        }

        result = insert_doto_directive(rst_file, task_data)

        assert result is True
        content = rst_file.read_text()
        assert "Existing content" in content
        assert ".. doto:: Appended task" in content

    def test_insert_after_specific_line(self, tmp_path):
        """Test inserting after a specific line."""
        from doxtr_doto.sync.rst_writer import insert_doto_directive

        rst_file = tmp_path / "tasks.rst"
        rst_file.write_text("""Tasks
=====

Line 4 content.
Line 5 content.
""")

        task_data = {
            "title": "Inserted task",
            "id": "TASK-INSERT",
        }

        result = insert_doto_directive(rst_file, task_data, after_line=4)

        assert result is True
        content = rst_file.read_text()

        lines = content.split("\n")
        # Find where the directive was inserted
        directive_line_idx = None
        for i, line in enumerate(lines):
            if ".. doto:: Inserted task" in line:
                directive_line_idx = i
                break

        assert directive_line_idx is not None
        # Should appear after line 4 (0-indexed: after index 3)
        assert directive_line_idx > 3


class TestUpdateDotoDirective:
    """Test the update_doto_directive function."""

    def test_update_single_field(self, tmp_path):
        """Test updating a single field."""
        from doxtr_doto.sync.rst_writer import update_doto_directive

        rst_file = tmp_path / "tasks.rst"
        rst_file.write_text("""Tasks
=====

.. doto:: Task to update
   :id: TASK-001
   :priority: medium
   :status: open

   Description.
""")

        result = update_doto_directive(rst_file, "TASK-001", {"priority": "high"})

        assert result is True
        content = rst_file.read_text()
        assert ":priority: high" in content
        assert ":priority: medium" not in content

    def test_update_multiple_fields(self, tmp_path):
        """Test updating multiple fields."""
        from doxtr_doto.sync.rst_writer import update_doto_directive

        rst_file = tmp_path / "tasks.rst"
        rst_file.write_text("""Tasks
=====

.. doto:: Task to update
   :id: TASK-001
   :priority: medium
   :status: open
   :assignee: alice

   Description.
""")

        result = update_doto_directive(
            rst_file,
            "TASK-001",
            {"priority": "critical", "status": "in-progress", "assignee": "bob"},
        )

        assert result is True
        content = rst_file.read_text()
        assert ":priority: critical" in content
        assert ":status: in-progress" in content
        assert ":assignee: bob" in content

    def test_update_nonexistent_task(self, tmp_path):
        """Test updating a non-existent task returns False."""
        from doxtr_doto.sync.rst_writer import update_doto_directive

        rst_file = tmp_path / "tasks.rst"
        rst_file.write_text("""Tasks
=====

.. doto:: Existing task
   :id: TASK-001

   Description.
""")

        result = update_doto_directive(rst_file, "NONEXISTENT", {"priority": "high"})

        assert result is False
