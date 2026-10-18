"""Tests for the doto directive."""

from __future__ import annotations

from datetime import date

import pytest


class TestDotoDirective:
    """Test the main doto directive."""

    def test_basic_task(self, doto_app, sample_tasks_rst):
        """Test parsing a basic task directive."""
        doto_app.build()

        env = doto_app.env
        assert hasattr(env, "doto_data")

        tasks = env.doto_data.all_tasks
        assert "TASK-001" in tasks

        task = tasks["TASK-001"]
        assert task.title == "Implement user authentication"
        assert task.assignee == "alice"
        assert task.priority == "high"
        assert task.status == "open"

    def test_auto_generated_id(self, doto_srcdir, make_app):
        """Test that IDs are auto-generated when not provided."""
        tasks_rst = doto_srcdir / "autoid.rst"
        tasks_rst.write_text("""
Auto ID Test
============

.. doto:: Task without explicit ID
   :priority: medium

   This task should get an auto-generated ID.
""")

        # Update index
        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   autoid\n")

        app = make_app(srcdir=doto_srcdir)
        app.build()

        tasks = app.env.doto_data.all_tasks
        # Should have at least one task with auto-generated ID
        assert len(tasks) >= 1

        # Auto-generated IDs use format {docname}-L{lineno}
        auto_ids = [tid for tid in tasks if tid.startswith("autoid-L")]
        assert len(auto_ids) == 1

    def test_task_with_all_options(self, doto_srcdir, make_app):
        """Test task with all available options."""
        tasks_rst = doto_srcdir / "full.rst"
        tasks_rst.write_text("""
Full Options Test
=================

.. doto:: Complete task example
   :id: FULL-001
   :assignee: charlie
   :priority: critical
   :status: in-progress
   :due: 2026-12-31
   :estimate: 4h
   :tags: feature, frontend, urgent
   :depends-on: TASK-001, TASK-002
   :created: 2026-01-01
   :updated: 2026-07-26

   This task has all options specified.

   It includes multiple paragraphs in the body.
""")

        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   full\n")

        app = make_app(srcdir=doto_srcdir)
        app.build()

        task = app.env.doto_data.all_tasks["FULL-001"]
        assert task.title == "Complete task example"
        assert task.assignee == "charlie"
        assert task.priority == "critical"
        assert task.status == "in-progress"
        # due is now stored as ISO string, not date object
        assert task.due == "2026-12-31"
        assert task.estimate == 240
        assert task.tags == ["feature", "frontend", "urgent"]
        assert task.depends_on == ["TASK-001", "TASK-002"]

    def test_estimate_parsed_to_minutes(self, doto_srcdir, make_app):
        """The :estimate: option is parsed to whole minutes via the duration syntax."""
        tasks_rst = doto_srcdir / "estimate.rst"
        tasks_rst.write_text("""
Estimate Test
=============

.. doto:: Quick task
   :id: EST-001
   :estimate: 5m

.. doto:: Combined estimate
   :id: EST-002
   :estimate: 1h30m

.. doto:: No estimate
   :id: EST-003
""")
        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   estimate\n")

        app = make_app(srcdir=doto_srcdir)
        app.build()

        tasks = app.env.doto_data.all_tasks
        assert tasks["EST-001"].estimate == 5
        assert tasks["EST-002"].estimate == 90
        assert tasks["EST-003"].estimate is None

    def test_multiline_title_normalized_to_single_line(self, doto_srcdir, make_app):
        """A title spanning continuation lines is stored as a single line.

        docutils preserves the embedded newlines and continuation
        indentation of a multi-line directive argument, so the stored title
        must collapse those whitespace runs to single spaces (no embedded
        newline, no doubled spaces).
        """
        tasks_rst = doto_srcdir / "multiline.rst"
        tasks_rst.write_text("""
Multiline Title Test
====================

.. doto:: Assess whether GitLab's SCIM 2.0 implementation is still
   incomplete (see GitLab work items 597897 and 452118) as a contributing
   root cause
   :id: MULTI-001
   :priority: high

   The title above is authored across continuation lines.
""")

        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   multiline\n")

        app = make_app(srcdir=doto_srcdir)
        app.build()

        task = app.env.doto_data.all_tasks["MULTI-001"]
        assert "\n" not in task.title
        assert "  " not in task.title
        assert task.title == (
            "Assess whether GitLab's SCIM 2.0 implementation is still "
            "incomplete (see GitLab work items 597897 and 452118) as a "
            "contributing root cause"
        )

    def test_invalid_priority_warning(self, doto_srcdir, make_app):
        """Test that invalid priority values cause build errors."""
        tasks_rst = doto_srcdir / "invalid.rst"
        tasks_rst.write_text("""
Invalid Priority
================

.. doto:: Task with invalid priority
   :id: INVALID-001
   :priority: ultra-high

   This should raise an error about invalid priority.
""")

        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   invalid\n")

        app = make_app(srcdir=doto_srcdir)
        # Build will complete but the task won't be created due to error
        app.build()

        # Invalid priority causes error, so task should NOT be in the list
        tasks = app.env.doto_data.all_tasks
        # The directive raises an error for invalid priority, so task is not created
        assert "INVALID-001" not in tasks

    def test_invalid_date_format(self, doto_srcdir, make_app):
        """Test handling of invalid date formats."""
        tasks_rst = doto_srcdir / "baddate.rst"
        tasks_rst.write_text("""
Bad Date
========

.. doto:: Task with bad date
   :id: BADDATE-001
   :due: not-a-date

   This has an invalid date format.
""")

        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   baddate\n")

        app = make_app(srcdir=doto_srcdir)
        app.build()

        # Invalid date causes error, so task should NOT be in the list
        tasks = app.env.doto_data.all_tasks
        assert "BADDATE-001" not in tasks

    def test_due_with_time_hh_mm(self, doto_srcdir, make_app):
        """A due with an appended HH:MM time is parsed and stored with time."""
        tasks_rst = doto_srcdir / "duetime.rst"
        tasks_rst.write_text("""
Due With Time
=============

.. doto:: Task due at a specific time
   :id: DUETIME-001
   :due: 2026-08-15 16:00

   This task has a time-bearing due.
""")

        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   duetime\n")

        app = make_app(srcdir=doto_srcdir)
        app.build()

        task = app.env.doto_data.all_tasks["DUETIME-001"]
        assert task.due == "2026-08-15T16:00"

    def test_due_with_hour_shorthand(self, doto_srcdir, make_app):
        """The HHh shorthand expands to HH:00 in the stored due."""
        tasks_rst = doto_srcdir / "dueshort.rst"
        tasks_rst.write_text("""
Due Shorthand
=============

.. doto:: Task due with hour shorthand
   :id: DUESHORT-001
   :due: 2026-08-15 16h
""")

        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   dueshort\n")

        app = make_app(srcdir=doto_srcdir)
        app.build()

        task = app.env.doto_data.all_tasks["DUESHORT-001"]
        assert task.due == "2026-08-15T16:00"

    def test_due_with_seconds(self, doto_srcdir, make_app):
        """A due with HH:MM:SS keeps its seconds."""
        tasks_rst = doto_srcdir / "duesec.rst"
        tasks_rst.write_text("""
Due Seconds
===========

.. doto:: Task due with seconds
   :id: DUESEC-001
   :due: 2026-08-15 16:00:31
""")

        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   duesec\n")

        app = make_app(srcdir=doto_srcdir)
        app.build()

        task = app.env.doto_data.all_tasks["DUESEC-001"]
        assert task.due == "2026-08-15T16:00:31"

    def test_due_date_only_unchanged(self, doto_srcdir, make_app):
        """A date-only due is stored exactly as before (no time added)."""
        tasks_rst = doto_srcdir / "duedateonly.rst"
        tasks_rst.write_text("""
Due Date Only
=============

.. doto:: Task due date only
   :id: DUEDATE-001
   :due: 2026-08-15
""")

        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   duedateonly\n")

        app = make_app(srcdir=doto_srcdir)
        app.build()

        task = app.env.doto_data.all_tasks["DUEDATE-001"]
        assert task.due == "2026-08-15"

    def test_due_invalid_time_rejected(self, doto_srcdir, make_app):
        """An out-of-range time makes the directive error; task is dropped."""
        tasks_rst = doto_srcdir / "duebadtime.rst"
        tasks_rst.write_text("""
Due Bad Time
============

.. doto:: Task with a bad due time
   :id: DUEBAD-001
   :due: 2026-08-15 25:00
""")

        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   duebadtime\n")

        app = make_app(srcdir=doto_srcdir)
        app.build()

        assert "DUEBAD-001" not in app.env.doto_data.all_tasks

    def test_due_with_time_renders_in_html(self, doto_srcdir, make_app):
        """The rendered HTML shows the due with its time, space-separated."""
        tasks_rst = doto_srcdir / "duerender.rst"
        tasks_rst.write_text("""
Due Render
==========

.. doto:: Task due render
   :id: DUERENDER-001
   :due: 2026-08-15 16:00
""")

        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   duerender\n")

        app = make_app(srcdir=doto_srcdir)
        app.build()

        html = (app.outdir / "duerender.html").read_text(encoding="utf-8")
        # Display form uses a space separator, not the ISO 'T'.
        assert "2026-08-15 16:00" in html
        assert "2026-08-15T16:00" not in html


class TestDotoDirectiveValidation:
    """Test directive validation logic."""

    def test_valid_statuses(self):
        """Test all valid status values."""
        from doxtr_doto.utils import VALID_STATUSES, validate_status

        for status in VALID_STATUSES:
            assert validate_status(status) == status

    def test_valid_priorities(self):
        """Test all valid priority values."""
        from doxtr_doto.utils import VALID_PRIORITIES, validate_priority

        for priority in VALID_PRIORITIES:
            assert validate_priority(priority) == priority

    def test_parse_tags(self):
        """Test tag parsing."""
        from doxtr_doto.utils import parse_list

        assert parse_list("a, b, c") == ["a", "b", "c"]
        assert parse_list("single") == ["single"]
        assert parse_list("  spaced , items  ") == ["spaced", "items"]
        assert parse_list("") == []

    def test_normalize_whitespace(self):
        """Test whitespace normalization collapses runs and strips ends."""
        from doxtr_doto.utils import normalize_whitespace

        # Already single-line input is left unchanged.
        assert normalize_whitespace("already one line") == "already one line"
        # Embedded newlines plus continuation indentation collapse to one space.
        assert normalize_whitespace("first line\n   second line") == ("first line second line")
        # Tabs and mixed whitespace runs collapse to a single space.
        assert normalize_whitespace("a\n\tb") == "a b"
        assert normalize_whitespace("  spaced   out  ") == "spaced out"
        # Leading/trailing newlines are stripped.
        assert normalize_whitespace("\n  trimmed  \n") == "trimmed"
        # Empty and whitespace-only inputs become empty strings.
        assert normalize_whitespace("") == ""
        assert normalize_whitespace("   ") == ""

    def test_parse_date(self):
        """Test date parsing."""
        from doxtr_doto.utils import parse_date

        assert parse_date("2026-08-15") == date(2026, 8, 15)
        assert parse_date("2026-01-01") == date(2026, 1, 1)
        # Invalid date raises ValueError
        with pytest.raises(ValueError):
            parse_date("invalid")
        # Empty string returns None
        assert parse_date("") is None
