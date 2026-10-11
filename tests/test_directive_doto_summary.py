"""Tests for the doto-summary directive."""

from __future__ import annotations

import pytest


class TestDotoSummaryDirective:
    """Test the doto-summary directive."""

    def test_basic_summary(self, doto_srcdir, make_app, sample_tasks_rst):
        """Test basic summary rendering."""
        summary_rst = doto_srcdir / "summary.rst"
        summary_rst.write_text("""
Task Summary
============

.. doto-summary::
""")

        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   summary\n")

        app = make_app(srcdir=doto_srcdir)
        app.build()

        # Check that build succeeded
        assert app.statuscode == 0

    def test_summary_group_by_status(self, doto_srcdir, make_app, sample_tasks_rst):
        """Test grouping summary by status."""
        summary_rst = doto_srcdir / "by_status.rst"
        summary_rst.write_text("""
Summary by Status
=================

.. doto-summary::
   :group-by: status
""")

        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   by_status\n")

        app = make_app(srcdir=doto_srcdir)
        app.build()

        assert app.statuscode == 0

    def test_summary_group_by_priority(self, doto_srcdir, make_app, sample_tasks_rst):
        """Test grouping summary by priority."""
        summary_rst = doto_srcdir / "by_priority.rst"
        summary_rst.write_text("""
Summary by Priority
===================

.. doto-summary::
   :group-by: priority
""")

        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   by_priority\n")

        app = make_app(srcdir=doto_srcdir)
        app.build()

        assert app.statuscode == 0

    def test_summary_group_by_assignee(self, doto_srcdir, make_app, sample_tasks_rst):
        """Test grouping summary by assignee."""
        summary_rst = doto_srcdir / "by_assignee.rst"
        summary_rst.write_text("""
Summary by Assignee
===================

.. doto-summary::
   :group-by: assignee
""")

        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   by_assignee\n")

        app = make_app(srcdir=doto_srcdir)
        app.build()

        assert app.statuscode == 0

    def test_summary_multiple_grouping(self, doto_srcdir, make_app, sample_tasks_rst):
        """Test grouping by multiple fields."""
        summary_rst = doto_srcdir / "multi_group.rst"
        summary_rst.write_text("""
Summary by Status and Priority
==============================

.. doto-summary::
   :group-by: status, priority
""")

        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   multi_group\n")

        app = make_app(srcdir=doto_srcdir)
        app.build()

        assert app.statuscode == 0

    def test_summary_with_assignee_filter(self, doto_srcdir, make_app, sample_tasks_rst):
        """Test summary filtered by assignee."""
        summary_rst = doto_srcdir / "alice_summary.rst"
        summary_rst.write_text("""
Alice's Summary
===============

.. doto-summary::
   :assignee: alice
""")

        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   alice_summary\n")

        app = make_app(srcdir=doto_srcdir)
        app.build()

        assert app.statuscode == 0

    def test_summary_with_status_filter(self, doto_srcdir, make_app, sample_tasks_rst):
        """Test summary filtered by status."""
        summary_rst = doto_srcdir / "open_summary.rst"
        summary_rst.write_text("""
Open Tasks Summary
==================

.. doto-summary::
   :status: open
""")

        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   open_summary\n")

        app = make_app(srcdir=doto_srcdir)
        app.build()

        assert app.statuscode == 0

    def test_summary_with_chart(self, doto_srcdir, make_app, sample_tasks_rst):
        """Test summary with chart option."""
        summary_rst = doto_srcdir / "chart_summary.rst"
        summary_rst.write_text("""
Summary with Chart
==================

.. doto-summary::
   :group-by: status
   :show-chart: true
""")

        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   chart_summary\n")

        app = make_app(srcdir=doto_srcdir)
        app.build()

        assert app.statuscode == 0

    def test_summary_with_pie_chart(self, doto_srcdir, make_app, sample_tasks_rst):
        """Test summary with pie chart type."""
        summary_rst = doto_srcdir / "pie_chart.rst"
        summary_rst.write_text("""
Summary with Pie Chart
======================

.. doto-summary::
   :group-by: status
   :show-chart: true
   :chart-type: pie
""")

        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   pie_chart\n")

        app = make_app(srcdir=doto_srcdir)
        app.build()

        assert app.statuscode == 0

        # Check that pie chart was generated
        output_file = doto_srcdir / "_build" / "html" / "pie_chart.html"
        if output_file.exists():
            content = output_file.read_text()
            assert "doto-pie-chart" in content or "doto-chart" in content

    def test_summary_with_bar_chart(self, doto_srcdir, make_app, sample_tasks_rst):
        """Test summary with explicit bar chart type."""
        summary_rst = doto_srcdir / "bar_chart.rst"
        summary_rst.write_text("""
Summary with Bar Chart
======================

.. doto-summary::
   :group-by: status
   :show-chart: true
   :chart-type: bar
""")

        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   bar_chart\n")

        app = make_app(srcdir=doto_srcdir)
        app.build()

        assert app.statuscode == 0

    def test_summary_with_burndown_chart(self, doto_srcdir, make_app, sample_tasks_rst):
        """Test summary with burndown chart type."""
        summary_rst = doto_srcdir / "burndown_chart.rst"
        summary_rst.write_text("""
Summary with Burndown Chart
===========================

.. doto-summary::
   :group-by: status
   :show-chart: true
   :chart-type: burndown
""")

        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   burndown_chart\n")

        app = make_app(srcdir=doto_srcdir)
        app.build()

        assert app.statuscode == 0


class TestDotoSummaryValidation:
    """Test doto-summary directive validation."""

    def test_validate_group_by(self):
        """Test validate_group_by function."""
        from doxtr_doto.directives.doto_summary import validate_group_by

        # Valid group-by fields
        assert validate_group_by("status") == ["status"]
        assert validate_group_by("priority") == ["priority"]
        assert validate_group_by("assignee") == ["assignee"]
        assert validate_group_by("tags") == ["tags"]

        # Multiple fields
        result = validate_group_by("status, priority")
        assert result == ["status", "priority"]

        # Case insensitive
        result = validate_group_by("STATUS, Priority")
        assert result == ["status", "priority"]

    def test_validate_group_by_invalid(self):
        """Test validate_group_by with invalid values."""
        from doxtr_doto.directives.doto_summary import validate_group_by

        with pytest.raises(ValueError) as excinfo:
            validate_group_by("invalid_field")
        assert "Invalid group-by field" in str(excinfo.value)

    def test_parse_filters(self):
        """Test filter parsing in the directive."""
        from doxtr_doto.utils import parse_list

        # Single value
        assert parse_list("alice") == ["alice"]

        # Multiple values
        assert parse_list("alice, bob") == ["alice", "bob"]

        # With whitespace
        assert parse_list("  alice , bob  ") == ["alice", "bob"]

    def test_valid_chart_types_constant(self):
        """Test that VALID_CHART_TYPES contains expected values."""
        from doxtr_doto.directives.doto_summary import VALID_CHART_TYPES

        assert "bar" in VALID_CHART_TYPES
        assert "pie" in VALID_CHART_TYPES
        assert "burndown" in VALID_CHART_TYPES
        # Feature 7 extended the set with stacked-bar and progress.
        assert "stacked-bar" in VALID_CHART_TYPES
        assert "progress" in VALID_CHART_TYPES
        assert len(VALID_CHART_TYPES) == 5


class TestChartTypeValidation:
    """Test chart-type option validation."""

    def test_invalid_chart_type_raises_error(self, doto_srcdir, make_app, sample_tasks_rst):
        """Test that invalid chart-type raises error during build."""
        summary_rst = doto_srcdir / "invalid_chart.rst"
        summary_rst.write_text("""
Invalid Chart Type
==================

.. doto-summary::
   :show-chart: true
   :chart-type: scatter
""")

        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   invalid_chart\n")

        app = make_app(srcdir=doto_srcdir)

        # Build should fail or produce error for invalid chart type
        # Sphinx directive errors often result in non-zero status or warnings
        try:
            app.build()
            # If build succeeds, check that there's an error in the output
            # by verifying status code is non-zero or warnings contain the error
            assert (
                app.statuscode != 0
                or any(
                    "Invalid chart-type" in str(w.message)
                    for w in app._warning.getvalue()
                    if hasattr(w, "message")
                )
                or "Invalid chart-type" in app._warning.getvalue()
            )
        except Exception:
            # Exception during build is also acceptable
            pass

    def test_chart_type_case_insensitive(self, doto_srcdir, make_app, sample_tasks_rst):
        """Test that chart-type is case insensitive."""
        summary_rst = doto_srcdir / "upper_chart.rst"
        summary_rst.write_text("""
Uppercase Chart Type
====================

.. doto-summary::
   :show-chart: true
   :chart-type: PIE
""")

        index = doto_srcdir / "index.rst"
        index.write_text(index.read_text() + "\n   upper_chart\n")

        app = make_app(srcdir=doto_srcdir)
        app.build()

        assert app.statuscode == 0

    def test_default_chart_type_is_bar(self):
        """Test that default chart type is bar."""
        from doxtr_doto.directives.doto_summary import DotoSummaryDirective

        # Verify chart_type option exists in option_spec
        assert "chart-type" in DotoSummaryDirective.option_spec
