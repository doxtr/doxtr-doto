"""Tests for CLI output formatting."""

from __future__ import annotations

import json

import pytest

from doxtr_doto.cli.output import OutputFormatter, build_task_detail_lines


class TestOutputFormatter:
    """Tests for OutputFormatter class."""

    def test_default_initialization(self):
        """Default initialization with quiet=False."""
        formatter = OutputFormatter()
        assert formatter.quiet is False
        assert formatter.json_output is False

    def test_quiet_mode(self):
        """Quiet mode suppresses normal output."""
        formatter = OutputFormatter(quiet=True)
        assert formatter.quiet is True

    def test_json_output_mode(self):
        """JSON output mode can be enabled."""
        formatter = OutputFormatter()
        formatter.json_output = True
        assert formatter.json_output is True

    def test_print_outputs_to_stdout(self, capsys):
        """print() outputs to stdout."""
        formatter = OutputFormatter()
        formatter.print("Hello, world!")
        captured = capsys.readouterr()
        assert "Hello, world!" in captured.out

    def test_print_suppressed_in_quiet_mode(self, capsys):
        """print() is suppressed in quiet mode."""
        formatter = OutputFormatter(quiet=True)
        formatter.print("This should not appear")
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_print_success(self, capsys):
        """print_success() outputs success message."""
        formatter = OutputFormatter()
        formatter.print_success("Operation completed")
        captured = capsys.readouterr()
        assert "Operation completed" in captured.out

    def test_print_error(self, capsys):
        """print_error() outputs error message."""
        formatter = OutputFormatter()
        formatter.print_error("Something went wrong")
        captured = capsys.readouterr()
        # Error may go to stdout or stderr depending on implementation
        assert "Something went wrong" in captured.out or "Something went wrong" in captured.err

    def test_print_warning(self, capsys):
        """print_warning() outputs warning message."""
        formatter = OutputFormatter()
        formatter.print_warning("Be careful")
        captured = capsys.readouterr()
        assert "Be careful" in captured.out or "Be careful" in captured.err

    def test_print_json_outputs_valid_json(self, capsys):
        """print_json() outputs valid JSON."""
        formatter = OutputFormatter()
        data = {"key": "value", "number": 42}
        formatter.print_json(data)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed == data

    def test_print_json_with_list(self, capsys):
        """print_json() handles lists."""
        formatter = OutputFormatter()
        data = [{"id": 1}, {"id": 2}]
        formatter.print_json(data)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed == data

    def test_format_task_detail(self, capsys):
        """format_task_detail() formats a task."""
        formatter = OutputFormatter()
        task = {
            "id": "TASK-001",
            "title": "Test task",
            "status": "open",
            "priority": "high",
        }
        formatter.format_task_detail(task)
        captured = capsys.readouterr()
        assert "TASK-001" in captured.out
        assert "Test task" in captured.out

    def test_format_task_list(self, capsys):
        """format_task_list() formats multiple tasks."""
        formatter = OutputFormatter()
        tasks = [
            {"id": "TASK-001", "title": "First", "status": "open", "priority": "high"},
            {"id": "TASK-002", "title": "Second", "status": "done", "priority": "low"},
        ]
        formatter.format_task_list(tasks)
        captured = capsys.readouterr()
        assert "TASK-001" in captured.out
        assert "TASK-002" in captured.out

    def test_format_task_list_empty(self, capsys):
        """format_task_list() handles empty list."""
        formatter = OutputFormatter()
        formatter.format_task_list([])
        capsys.readouterr()
        # Should either output nothing or a "no tasks" message
        # Not crash

    def test_format_task_list_json_mode(self, capsys):
        """format_task_list() outputs JSON in JSON mode."""
        formatter = OutputFormatter()
        formatter.json_output = True
        tasks = [
            {"id": "TASK-001", "title": "First"},
        ]
        formatter.format_task_list(tasks)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert isinstance(parsed, list)


class TestOutputFormatterStyles:
    """Tests for styled output."""

    def test_print_with_style(self, capsys):
        """print() accepts style parameter."""
        formatter = OutputFormatter()
        formatter.print("Bold text", style="bold")
        captured = capsys.readouterr()
        assert "Bold text" in captured.out

    def test_print_with_color_style(self, capsys):
        """print() accepts color styles."""
        formatter = OutputFormatter()
        formatter.print("Red text", style="red")
        captured = capsys.readouterr()
        assert "Red text" in captured.out

    def test_print_with_invalid_style(self, capsys):
        """print() with invalid style raises error."""
        formatter = OutputFormatter()
        # Invalid styles cause rich to raise an error
        from rich.errors import MissingStyle

        with pytest.raises(MissingStyle):
            formatter.print("Normal text", style="nonexistent")


class TestBuildTaskDetailLinesBodyInvariant:
    """Pin the trailing ``["", body]`` invariant at its source.

    The TUI ``CardViewerScreen.build_field_lines`` drops the body via a
    ``lines[:-2]`` slice, which relies on ``build_task_detail_lines`` always
    appending the body as exactly a trailing blank-separator + body pair and
    emitting nothing after it. These tests guard that ``[:-2]`` slice against
    drift so a change here fails loudly instead of silently corrupting the
    card viewer's field region.
    """

    def test_body_is_trailing_blank_separator_then_body(self):
        """A task with a body ends with ``["", body]`` (body is the last line)."""
        body = "Some multi-word body text that is the final element."
        task = {
            "id": "TASK-001",
            "title": "Test task",
            "status": "open",
            "priority": "high",
            "body": body,
        }
        lines = build_task_detail_lines(task)
        # Blank separator immediately precedes the body ...
        assert lines[-2] == ""
        # ... and the body text is the final element (nothing emitted after it).
        assert body in lines[-1]

    def test_body_does_not_leak_when_absent(self):
        """The same task without a body must not emit the body text anywhere."""
        body = "Some multi-word body text that is the final element."
        task = {
            "id": "TASK-001",
            "title": "Test task",
            "status": "open",
            "priority": "high",
        }
        lines = build_task_detail_lines(task)
        assert all(body not in line for line in lines)


class TestOutputFormatterTableFormatting:
    """Tests for table formatting."""

    def test_format_task_table(self, capsys):
        """format_task_table() creates aligned columns."""
        formatter = OutputFormatter()
        tasks = [
            {"id": "TASK-001", "title": "First task", "status": "open", "priority": "high"},
            {"id": "TASK-002", "title": "Second task", "status": "done", "priority": "low"},
        ]
        columns = ["id", "title", "status"]
        formatter.format_task_table(tasks, columns)
        captured = capsys.readouterr()
        assert "TASK-001" in captured.out
        assert "First task" in captured.out

    def test_format_task_table_empty_tasks(self, capsys):
        """format_task_table() handles empty tasks list."""
        formatter = OutputFormatter()
        tasks = []
        columns = ["id", "title"]
        formatter.format_task_table(tasks, columns)
        # Should not crash

    def test_format_task_table_with_none_values(self, capsys):
        """format_task_table() handles None values in cells."""
        formatter = OutputFormatter()
        tasks = [
            {
                "id": "TASK-001",
                "assignee": None,
                "title": "Test",
                "status": "open",
                "priority": "medium",
            },
        ]
        columns = ["id", "assignee"]
        formatter.format_task_table(tasks, columns)
        captured = capsys.readouterr()
        assert "TASK-001" in captured.out
