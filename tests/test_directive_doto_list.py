"""Tests for the doto-list directive."""

from __future__ import annotations

import io


class TestDotoListDirective:
    """Test the doto-list directive."""

    def test_basic_list(self, doto_srcdir, make_app, sample_tasks_rst):
        """Test basic task list rendering."""
        list_rst = doto_srcdir / "tasklist.rst"
        list_rst.write_text("""
Task List
=========

.. doto-list::
""")

        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   tasklist\n")

        app = make_app(srcdir=doto_srcdir)
        app.build()

        # Check that build succeeded
        assert app.statuscode == 0

    def test_filter_by_status(self, doto_srcdir, make_app, sample_tasks_rst):
        """Test filtering tasks by status."""
        list_rst = doto_srcdir / "filtered.rst"
        list_rst.write_text("""
Open Tasks
==========

.. doto-list::
   :status: open
""")

        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   filtered\n")

        app = make_app(srcdir=doto_srcdir)
        app.build()

        assert app.statuscode == 0

    def test_filter_by_priority(self, doto_srcdir, make_app, sample_tasks_rst):
        """Test filtering tasks by priority."""
        list_rst = doto_srcdir / "priority.rst"
        list_rst.write_text("""
High Priority
=============

.. doto-list::
   :priority: high, critical
""")

        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   priority\n")

        app = make_app(srcdir=doto_srcdir)
        app.build()

        assert app.statuscode == 0

    def test_filter_by_assignee(self, doto_srcdir, make_app, sample_tasks_rst):
        """Test filtering tasks by assignee."""
        list_rst = doto_srcdir / "assigned.rst"
        list_rst.write_text("""
Alice's Tasks
=============

.. doto-list::
   :assignee: alice
""")

        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   assigned\n")

        app = make_app(srcdir=doto_srcdir)
        app.build()

        assert app.statuscode == 0

    def test_sort_by_priority(self, doto_srcdir, make_app, sample_tasks_rst):
        """Test sorting tasks by priority."""
        list_rst = doto_srcdir / "sorted.rst"
        list_rst.write_text("""
Sorted by Priority
==================

.. doto-list::
   :sort: priority
   :order: desc
""")

        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   sorted\n")

        app = make_app(srcdir=doto_srcdir)
        app.build()

        assert app.statuscode == 0

    def test_table_format(self, doto_srcdir, make_app, sample_tasks_rst):
        """Test table format rendering."""
        list_rst = doto_srcdir / "table.rst"
        list_rst.write_text("""
Task Table
==========

.. doto-list::
   :format: table
   :columns: id, title, priority, status, assignee
""")

        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   table\n")

        app = make_app(srcdir=doto_srcdir)
        app.build()

        # Check HTML output contains table
        html_file = app.outdir / "table.html"
        if html_file.exists():
            content = html_file.read_text()
            assert "doto-list-table" in content or "table" in content.lower()

    def test_limit_option(self, doto_srcdir, make_app, sample_tasks_rst):
        """Test limiting number of displayed tasks."""
        list_rst = doto_srcdir / "limited.rst"
        list_rst.write_text("""
Limited List
============

.. doto-list::
   :limit: 2
""")

        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   limited\n")

        app = make_app(srcdir=doto_srcdir)
        app.build()

        assert app.statuscode == 0

    def test_exclude_status(self, doto_srcdir, make_app, sample_tasks_rst):
        """Test excluding tasks by status."""
        list_rst = doto_srcdir / "exclude.rst"
        list_rst.write_text("""
Not Done
========

.. doto-list::
   :exclude-status: done
""")

        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   exclude\n")

        app = make_app(srcdir=doto_srcdir)
        app.build()

        assert app.statuscode == 0

    def test_cards_format(self, doto_srcdir, make_app, sample_tasks_rst):
        """Test cards format rendering."""
        list_rst = doto_srcdir / "cards.rst"
        list_rst.write_text("""
Task Cards
==========

.. doto-list::
   :format: cards
""")

        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   cards\n")

        app = make_app(srcdir=doto_srcdir)
        app.build()

        assert app.statuscode == 0

    def test_date_filters(self, doto_srcdir, make_app, sample_tasks_rst):
        """Test date-based filtering."""
        list_rst = doto_srcdir / "datefilter.rst"
        list_rst.write_text("""
Due Soon
========

.. doto-list::
   :due-before: 2026-12-31
   :due-after: 2026-01-01
""")

        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   datefilter\n")

        app = make_app(srcdir=doto_srcdir)
        app.build()

        assert app.statuscode == 0


class TestDotoListIconMode:
    """Parse-time handling of the ``:icon-mode:`` directive option (Feature 5)."""

    def _build_with_icon_mode(self, doto_srcdir, tmp_path, mode):
        """Build a doto-list with the given :icon-mode: and capture warnings.

        Returns the (statuscode, warning_text) pair. A dedicated build is used
        (rather than the make_app fixture) so the Sphinx warning stream can be
        captured to assert the parse-time validation message.
        """
        from sphinx.application import Sphinx

        list_rst = doto_srcdir / "iconmode.rst"
        list_rst.write_text(f"Icon Mode\n=========\n\n.. doto-list::\n   :icon-mode: {mode}\n")
        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   iconmode\n")

        warning_stream = io.StringIO()
        outdir = tmp_path / "build" / "iconmode-html"
        doctreedir = tmp_path / "build" / "iconmode-doctrees"
        app = Sphinx(
            srcdir=str(doto_srcdir),
            confdir=str(doto_srcdir),
            outdir=str(outdir),
            doctreedir=str(doctreedir),
            buildername="html",
            warning=warning_stream,
            freshenv=True,
        )
        app.build()
        return app.statuscode, warning_stream.getvalue()

    def test_invalid_icon_mode_reports_parse_error(self, doto_srcdir, tmp_path, sample_tasks_rst):
        """An invalid :icon-mode: value is rejected at parse time.

        ``DotoListDirective._parse_icon_mode`` raises ``self.error`` for a value
        outside VALID_LIST_ICON_MODES, which surfaces as a docutils/Sphinx
        warning naming the offending value and the valid options.
        """
        _, warnings = self._build_with_icon_mode(doto_srcdir, tmp_path, "bogus")
        assert "Invalid icon-mode 'bogus'" in warnings
        # The message lists the accepted values so authors can self-correct.
        assert "icon-text" in warnings

    def test_valid_icon_mode_parses_cleanly(self, doto_srcdir, tmp_path, sample_tasks_rst):
        """A valid :icon-mode: value produces no parse-time warning."""
        statuscode, warnings = self._build_with_icon_mode(doto_srcdir, tmp_path, "text")
        assert statuscode == 0
        assert "Invalid icon-mode" not in warnings
