"""Tests for the charts module."""

from __future__ import annotations


class TestGenerateBarChart:
    """Test the bar chart generation."""

    def test_empty_data_returns_empty_string(self):
        """Empty data should return empty string."""
        from doxtr_doto.charts import generate_bar_chart

        result = generate_bar_chart({}, "Test Chart")
        assert result == ""

    def test_single_bar(self):
        """Single data point creates one bar."""
        from doxtr_doto.charts import generate_bar_chart

        result = generate_bar_chart({"open": 5}, "Status")
        assert "<svg" in result
        assert "<rect" in result
        assert "open" in result
        assert "5" in result

    def test_multiple_bars(self):
        """Multiple data points create multiple bars."""
        from doxtr_doto.charts import generate_bar_chart

        data = {"open": 3, "done": 7, "blocked": 2}
        result = generate_bar_chart(data, "Status")

        assert result.count("<rect") == 3
        assert "open" in result
        assert "done" in result
        assert "blocked" in result

    def test_title_in_svg(self):
        """Title appears in SVG."""
        from doxtr_doto.charts import generate_bar_chart

        result = generate_bar_chart({"test": 1}, "My Chart Title")
        assert "My Chart Title" in result

    def test_custom_colors(self):
        """Custom color map is applied."""
        from doxtr_doto.charts import generate_bar_chart

        color_map = {"high": "#ff0000", "low": "#00ff00"}
        result = generate_bar_chart({"high": 5, "low": 3}, "Priority", color_map=color_map)

        assert "#ff0000" in result
        assert "#00ff00" in result

    def test_zero_max_value(self):
        """Handles case where all values are zero."""
        from doxtr_doto.charts import generate_bar_chart

        result = generate_bar_chart({"open": 0, "done": 0}, "Status")
        # Should not crash, bars should have zero height
        assert "<svg" in result

    def test_xml_special_chars_escaped(self):
        """Special XML characters are escaped."""
        from doxtr_doto.charts import generate_bar_chart

        result = generate_bar_chart({"<test>": 5, "a&b": 3}, "Title")
        assert "&lt;" in result
        assert "&gt;" in result
        assert "&amp;" in result


class TestGenerateStatusChart:
    """Test status chart generation."""

    def test_status_chart_counts_correctly(self):
        """Status chart counts tasks by status."""
        from doxtr_doto.charts import generate_status_chart

        tasks = [
            {"status": "open"},
            {"status": "open"},
            {"status": "done"},
            {"status": "blocked"},
        ]
        result = generate_status_chart(tasks, "Task Status")

        assert "open" in result.lower()
        assert "done" in result.lower()
        assert "blocked" in result.lower()

    def test_status_chart_empty_tasks(self):
        """Empty task list returns empty string."""
        from doxtr_doto.charts import generate_status_chart

        result = generate_status_chart([], "Status")
        assert result == ""


class TestGeneratePriorityChart:
    """Test priority chart generation."""

    def test_priority_chart_counts_correctly(self):
        """Priority chart counts tasks by priority."""
        from doxtr_doto.charts import generate_priority_chart

        tasks = [
            {"priority": "high"},
            {"priority": "high"},
            {"priority": "low"},
            {"priority": "critical"},
        ]
        result = generate_priority_chart(tasks, "Priority Distribution")

        assert "high" in result.lower()
        assert "low" in result.lower()
        assert "critical" in result.lower()


class TestGenerateAssigneeChart:
    """Test assignee chart generation."""

    def test_assignee_chart_groups_by_assignee(self):
        """Assignee chart groups tasks by assignee."""
        from doxtr_doto.charts import generate_assignee_chart

        tasks = [
            {"assignee": "alice"},
            {"assignee": "alice"},
            {"assignee": "bob"},
            {"assignee": None},
        ]
        result = generate_assignee_chart(tasks, "By Assignee")

        assert "alice" in result.lower()
        assert "bob" in result.lower()
        # Unassigned tasks should be labeled
        assert "unassigned" in result.lower()


class TestGenerateTagsChart:
    """Test tags chart generation."""

    def test_tags_chart_counts_by_tag(self):
        """Tags chart counts tasks by each tag."""
        from doxtr_doto.charts import generate_tags_chart

        tasks = [
            {"tags": ["security", "backend"]},
            {"tags": ["security"]},
            {"tags": ["frontend"]},
            {"tags": []},
        ]
        result = generate_tags_chart(tasks, "Tags")

        assert "security" in result.lower()
        assert "frontend" in result.lower()
        assert "backend" in result.lower()


class TestGenerateSummaryCharts:
    """Test combined summary chart generation."""

    def test_summary_charts_multiple_groups(self):
        """Summary charts generates charts for each group."""
        from doxtr_doto.charts import generate_summary_charts

        tasks = [
            {"status": "open", "priority": "high"},
            {"status": "done", "priority": "low"},
        ]
        result = generate_summary_charts(tasks, ["status", "priority"])

        # Should contain both charts
        assert "status" in result.lower()
        assert "priority" in result.lower()

    def test_summary_charts_empty_tasks(self):
        """Empty tasks returns empty string."""
        from doxtr_doto.charts import generate_summary_charts

        result = generate_summary_charts([], ["status"])
        assert result == ""

    def test_summary_charts_bar_type_default(self):
        """Bar chart is the default chart type."""
        from doxtr_doto.charts import generate_summary_charts

        tasks = [{"status": "open"}]
        result = generate_summary_charts(tasks, ["status"])

        assert "doto-bar-chart" in result

    def test_summary_charts_pie_type(self):
        """Pie chart type generates pie charts."""
        from doxtr_doto.charts import generate_summary_charts

        tasks = [{"status": "open"}, {"status": "done"}]
        result = generate_summary_charts(tasks, ["status"], chart_type="pie")

        assert "doto-pie-chart" in result

    def test_summary_charts_burndown_type(self):
        """Burndown chart type generates burndown chart."""
        from datetime import date, timedelta

        from doxtr_doto.charts import generate_summary_charts

        today = date.today()
        yesterday = today - timedelta(days=1)

        tasks = [
            {"status": "open", "created": yesterday.isoformat()},
            {"status": "done", "created": yesterday.isoformat(), "updated": today.isoformat()},
        ]
        result = generate_summary_charts(tasks, ["status"], chart_type="burndown")

        assert "doto-burndown-chart" in result

    def test_summary_charts_burndown_fallback_to_bar(self):
        """Burndown falls back to bar if no date data."""
        from doxtr_doto.charts import generate_summary_charts

        tasks = [{"status": "open"}, {"status": "done"}]  # No dates
        result = generate_summary_charts(tasks, ["status"], chart_type="burndown")

        # Should fall back to bar chart
        assert "doto-bar-chart" in result or "doto-chart" in result


class TestGeneratePieChart:
    """Test pie chart generation."""

    def test_generates_svg(self):
        """Pie chart generates valid SVG."""
        from doxtr_doto.charts import generate_pie_chart

        data = {"open": 5, "done": 3}
        result = generate_pie_chart(data, "Tasks by Status")

        assert "<svg" in result
        assert "</svg>" in result
        assert "doto-pie-chart" in result

    def test_empty_data_returns_empty_string(self):
        """Empty data returns empty string."""
        from doxtr_doto.charts import generate_pie_chart

        result = generate_pie_chart({}, "Empty Chart")
        assert result == ""

    def test_zero_total_returns_empty_string(self):
        """All zero values returns empty string."""
        from doxtr_doto.charts import generate_pie_chart

        result = generate_pie_chart({"open": 0, "done": 0}, "Zero Chart")
        assert result == ""

    def test_title_in_svg(self):
        """Title appears in SVG."""
        from doxtr_doto.charts import generate_pie_chart

        result = generate_pie_chart({"test": 5}, "My Pie Title")
        assert "My Pie Title" in result

    def test_escapes_labels(self):
        """Special characters in labels are escaped."""
        from doxtr_doto.charts import generate_pie_chart

        result = generate_pie_chart({"<script>": 5, "a&b": 3}, "XSS Test")
        assert "&lt;" in result
        assert "&gt;" in result
        assert "&amp;" in result
        assert "<script>" not in result

    def test_handles_single_item(self):
        """Single item (100%) renders as full circle."""
        from doxtr_doto.charts import generate_pie_chart

        result = generate_pie_chart({"only": 10}, "Single Slice")
        # Should use circle element for 100%
        assert "<circle" in result or "<path" in result
        assert "only" in result.lower()

    def test_custom_color_map(self):
        """Custom color map is applied."""
        from doxtr_doto.charts import generate_pie_chart

        color_map = {"high": "#ff0000", "low": "#00ff00"}
        result = generate_pie_chart({"high": 5, "low": 3}, "Priority", color_map=color_map)

        assert "#ff0000" in result
        assert "#00ff00" in result

    def test_percentages_in_legend(self):
        """Percentages appear in legend."""
        from doxtr_doto.charts import generate_pie_chart

        result = generate_pie_chart({"a": 75, "b": 25}, "Percentages")
        assert "75%" in result
        assert "25%" in result

    def test_multiple_slices(self):
        """Multiple slices render correctly."""
        from doxtr_doto.charts import generate_pie_chart

        data = {"open": 3, "done": 5, "blocked": 2}
        result = generate_pie_chart(data, "Multi-slice")

        # Should have path elements for slices
        assert "<path" in result or "<circle" in result
        assert "open" in result.lower()
        assert "done" in result.lower()
        assert "blocked" in result.lower()

    def test_skips_zero_values(self):
        """Zero values don't create slices."""
        from doxtr_doto.charts import generate_pie_chart

        data = {"open": 5, "done": 0, "blocked": 3}
        result = generate_pie_chart(data, "With Zero")

        # Should still render
        assert "<svg" in result
        # Zero items still appear in legend
        assert "open" in result.lower()


class TestGenerateBurndownChart:
    """Test burndown chart generation."""

    def test_generates_svg_with_dated_tasks(self):
        """Burndown chart generates valid SVG with dated tasks."""
        from datetime import date, timedelta

        from doxtr_doto.charts import generate_burndown_chart

        today = date.today()
        week_ago = today - timedelta(days=7)

        tasks = [
            {"status": "open", "created": week_ago.isoformat()},
            {"status": "done", "created": week_ago.isoformat(), "updated": today.isoformat()},
        ]
        result = generate_burndown_chart(tasks, "Burndown")

        assert "<svg" in result
        assert "</svg>" in result
        assert "doto-burndown-chart" in result

    def test_returns_empty_for_undated_tasks(self):
        """Returns empty string when no tasks have dates."""
        from doxtr_doto.charts import generate_burndown_chart

        tasks = [
            {"status": "open"},
            {"status": "done"},
        ]
        result = generate_burndown_chart(tasks, "No Dates")
        assert result == ""

    def test_returns_empty_for_single_day(self):
        """Returns empty string when all tasks are same day."""
        from datetime import date

        from doxtr_doto.charts import generate_burndown_chart

        today = date.today().isoformat()
        tasks = [
            {"status": "open", "created": today},
            {"status": "done", "created": today, "updated": today},
        ]
        result = generate_burndown_chart(tasks, "Single Day")
        # Need at least 2 days for a meaningful burndown
        assert result == ""

    def test_title_in_svg(self):
        """Title appears in SVG."""
        from datetime import date, timedelta

        from doxtr_doto.charts import generate_burndown_chart

        today = date.today()
        week_ago = today - timedelta(days=7)

        tasks = [{"status": "open", "created": week_ago.isoformat()}]
        result = generate_burndown_chart(tasks, "Sprint Burndown")

        assert "Sprint Burndown" in result

    def test_counts_correctly_over_time(self):
        """Burndown calculates remaining tasks correctly."""
        from datetime import date, timedelta

        from doxtr_doto.charts import generate_burndown_chart

        today = date.today()
        day1 = today - timedelta(days=5)
        day3 = today - timedelta(days=3)
        day5 = today - timedelta(days=1)

        tasks = [
            # Task created day 1, still open
            {"status": "open", "created": day1.isoformat()},
            # Task created day 1, completed day 3
            {"status": "done", "created": day1.isoformat(), "updated": day3.isoformat()},
            # Task created day 3, completed day 5
            {"status": "done", "created": day3.isoformat(), "updated": day5.isoformat()},
        ]
        result = generate_burndown_chart(tasks, "Test Burndown")

        # Should have generated a valid chart
        assert "<svg" in result
        assert "<path" in result
        assert "doto-burndown-line" in result

    def test_has_axes(self):
        """Burndown chart has axis lines."""
        from datetime import date, timedelta

        from doxtr_doto.charts import generate_burndown_chart

        today = date.today()
        week_ago = today - timedelta(days=7)

        tasks = [{"status": "open", "created": week_ago.isoformat()}]
        result = generate_burndown_chart(tasks)

        # Should have axis lines
        assert "<line" in result

    def test_has_date_labels(self):
        """Burndown chart has date labels on x-axis."""
        from datetime import date, timedelta

        from doxtr_doto.charts import generate_burndown_chart

        today = date.today()
        week_ago = today - timedelta(days=7)

        tasks = [{"status": "open", "created": week_ago.isoformat()}]
        result = generate_burndown_chart(tasks)

        # Should have ISO date format labels
        assert week_ago.isoformat() in result

    def test_handles_datetime_objects(self):
        """Burndown handles datetime objects as dates."""
        from datetime import datetime, timedelta

        from doxtr_doto.charts import generate_burndown_chart

        now = datetime.now()
        week_ago = now - timedelta(days=7)

        tasks = [{"status": "open", "created": week_ago}]
        result = generate_burndown_chart(tasks)

        assert "<svg" in result

    def test_handles_date_objects(self):
        """Burndown handles date objects directly."""
        from datetime import date, timedelta

        from doxtr_doto.charts import generate_burndown_chart

        today = date.today()
        week_ago = today - timedelta(days=7)

        tasks = [{"status": "open", "created": week_ago}]  # date object, not string
        result = generate_burndown_chart(tasks)

        assert "<svg" in result


class TestChartTypeRouting:
    """Test that chart type routing works correctly."""

    def test_bar_chart_selected_by_default(self):
        """Bar chart is selected when no chart_type specified."""
        from doxtr_doto.charts import generate_summary_charts

        tasks = [{"status": "open"}, {"status": "done"}]
        result = generate_summary_charts(tasks, ["status"])

        assert "doto-bar-chart" in result

    def test_pie_chart_selected_when_requested(self):
        """Pie chart is selected when chart_type=pie."""
        from doxtr_doto.charts import generate_summary_charts

        tasks = [{"status": "open"}, {"status": "done"}]
        result = generate_summary_charts(tasks, ["status"], chart_type="pie")

        assert "doto-pie-chart" in result

    def test_burndown_chart_selected_when_requested(self):
        """Burndown chart is selected when chart_type=burndown."""
        from datetime import date, timedelta

        from doxtr_doto.charts import generate_summary_charts

        today = date.today()
        week_ago = today - timedelta(days=7)

        tasks = [
            {"status": "open", "created": week_ago.isoformat()},
            {"status": "done", "created": week_ago.isoformat(), "updated": today.isoformat()},
        ]
        result = generate_summary_charts(tasks, ["status"], chart_type="burndown")

        assert "doto-burndown-chart" in result

    def test_pie_chart_for_priority(self):
        """Pie chart works for priority grouping."""
        from doxtr_doto.charts import generate_summary_charts

        tasks = [{"priority": "high"}, {"priority": "low"}]
        result = generate_summary_charts(tasks, ["priority"], chart_type="pie")

        assert "doto-pie-chart" in result
        assert "Priority" in result

    def test_pie_chart_for_assignee(self):
        """Pie chart works for assignee grouping."""
        from doxtr_doto.charts import generate_summary_charts

        tasks = [{"assignee": "alice"}, {"assignee": "bob"}]
        result = generate_summary_charts(tasks, ["assignee"], chart_type="pie")

        assert "doto-pie-chart" in result
        assert "Assignee" in result

    def test_pie_chart_for_tags(self):
        """Pie chart works for tags grouping."""
        from doxtr_doto.charts import generate_summary_charts

        tasks = [{"tags": ["bug"]}, {"tags": ["feature"]}]
        result = generate_summary_charts(tasks, ["tags"], chart_type="pie")

        assert "doto-pie-chart" in result
        assert "Tag" in result


class TestProgressChart:
    """Test the SVG progress (completion) chart (Feature 7)."""

    def test_progress_chart_empty_tasks(self):
        from doxtr_doto.charts import generate_progress_chart

        assert generate_progress_chart([]) == ""

    def test_progress_chart_percentage(self):
        from doxtr_doto.charts import generate_progress_chart

        tasks = [
            {"status": "done"},
            {"status": "done"},
            {"status": "open"},
            {"status": "open"},
        ]
        result = generate_progress_chart(tasks)
        assert "doto-progress-chart" in result
        assert "50% complete" in result
        assert "(2/4)" in result

    def test_progress_chart_via_summary(self):
        from doxtr_doto.charts import generate_summary_charts

        tasks = [{"status": "done"}, {"status": "open"}]
        result = generate_summary_charts(tasks, ["status"], chart_type="progress")
        assert "doto-progress-chart" in result


class TestPlotlyEngineAvailability:
    """Test plotly/kaleido availability detection and graceful fallback."""

    def test_plotly_available_returns_bool(self):
        from doxtr_doto.charts import plotly_available

        assert isinstance(plotly_available(), bool)

    def test_kaleido_available_returns_bool(self):
        from doxtr_doto.charts import kaleido_available

        assert isinstance(kaleido_available(), bool)

    def test_render_returns_none_when_plotly_missing(self, monkeypatch, tmp_path):
        """When plotly is unavailable, image render returns None (SVG fallback)."""
        import doxtr_doto.charts as charts

        monkeypatch.setattr(charts, "plotly_available", lambda: False)
        result = charts.render_plotly_chart_image(
            [{"status": "open"}], ["status"], "pie", str(tmp_path)
        )
        assert result is None

    def test_render_returns_none_when_kaleido_missing(self, monkeypatch, tmp_path):
        """When kaleido is unavailable, image render returns None (SVG fallback)."""
        import doxtr_doto.charts as charts

        monkeypatch.setattr(charts, "kaleido_available", lambda: False)
        result = charts.render_plotly_chart_image(
            [{"status": "open"}], ["status"], "bar", str(tmp_path)
        )
        assert result is None

    def test_render_returns_none_on_export_failure(self, monkeypatch, tmp_path):
        """A kaleido runtime failure (e.g. no Chrome) degrades to None, not crash."""
        import doxtr_doto.charts as charts

        monkeypatch.setattr(charts, "kaleido_available", lambda: True)

        class _BadFig:
            def write_image(self, *a, **k):
                raise RuntimeError("Kaleido requires Google Chrome")

        monkeypatch.setattr(charts, "_plotly_figure", lambda *a, **k: _BadFig())
        result = charts.render_plotly_chart_image(
            [{"status": "open"}], ["status"], "bar", str(tmp_path)
        )
        assert result is None

    def test_plotly_html_returns_none_falls_back(self, monkeypatch, tmp_path):
        """The HTML helper returns None when the image can't be produced."""
        import doxtr_doto.charts as charts

        monkeypatch.setattr(charts, "kaleido_available", lambda: False)
        result = charts.generate_summary_charts_plotly_html(
            [{"status": "open"}], ["status"], "pie", str(tmp_path)
        )
        assert result is None


class TestPlotlyFigure:
    """Test plotly figure construction when plotly is importable."""

    def test_figure_builds_for_each_chart_type(self):
        from doxtr_doto.charts import _plotly_figure, plotly_available

        if not plotly_available():
            import pytest as _pytest

            _pytest.skip("plotly not installed")

        tasks = [
            {"id": "A-1", "status": "open", "priority": "high", "created": "2024-01-01"},
            {
                "id": "A-2",
                "status": "done",
                "priority": "low",
                "created": "2024-01-02",
                "updated": "2024-01-05",
            },
        ]
        for ct in ("pie", "bar", "stacked-bar", "progress"):
            fig = _plotly_figure(tasks, ["status"], ct)
            assert fig is not None

    def test_burndown_none_without_dates(self):
        from doxtr_doto.charts import _plotly_figure, plotly_available

        if not plotly_available():
            import pytest as _pytest

            _pytest.skip("plotly not installed")

        # No created dates -> insufficient data -> None (SVG fallback).
        fig = _plotly_figure([{"status": "open"}], ["status"], "burndown")
        assert fig is None

    def test_render_image_when_kaleido_works(self, tmp_path):
        """End-to-end static export, skipped when Chrome/kaleido unavailable."""
        from doxtr_doto.charts import kaleido_available, render_plotly_chart_image

        if not kaleido_available():
            import pytest as _pytest

            _pytest.skip("kaleido not installed")

        tasks = [{"id": "A-1", "status": "open", "priority": "high"}]
        filename = render_plotly_chart_image(tasks, ["status"], "pie", str(tmp_path))
        # May be None if Chrome is unavailable in this environment; only assert
        # the file exists when a filename was returned.
        if filename is not None:
            assert (tmp_path / filename).exists()
            assert (tmp_path / filename).stat().st_size > 0


class TestChartFilename:
    """Test deterministic chart image filenames used for caching/cleanup."""

    def test_filename_is_deterministic(self):
        from doxtr_doto.charts import _chart_filename

        tasks = [{"id": "A-1", "status": "open", "priority": "high"}]
        a = _chart_filename(tasks, ["status"], "pie", "png")
        b = _chart_filename(tasks, ["status"], "pie", "png")
        assert a == b
        assert a.startswith("doto-chart-")
        assert a.endswith(".png")

    def test_filename_changes_with_data(self):
        from doxtr_doto.charts import _chart_filename

        a = _chart_filename(
            [{"id": "A-1", "status": "open", "priority": "high"}],
            ["status"],
            "pie",
            "png",
        )
        b = _chart_filename(
            [{"id": "A-1", "status": "done", "priority": "high"}],
            ["status"],
            "pie",
            "png",
        )
        assert a != b


class TestNativeLatexCharts:
    """Test the native-LaTeX chart engine (no browser/kaleido needed)."""

    def _tasks(self):
        return [
            {"id": "T-1", "status": "open", "priority": "high", "assignee": "alice", "tags": ["x"]},
            {"id": "T-2", "status": "done", "priority": "low", "assignee": "bob", "tags": []},
            {
                "id": "T-3",
                "status": "open",
                "priority": "high",
                "assignee": "alice",
                "tags": ["x", "y"],
            },
        ]

    def test_empty_tasks_returns_empty(self):
        from doxtr_doto.charts import generate_summary_charts_latex

        assert generate_summary_charts_latex([], ["status"], "bar") == ""

    def test_bar_chart_emits_dotochart_macros(self):
        from doxtr_doto.charts import generate_summary_charts_latex

        out = generate_summary_charts_latex(self._tasks(), ["status"], "bar")
        assert "\\begin{dotochart}" in out
        assert "\\dotochartbar{open}{2}" in out
        assert "\\end{dotochart}" in out

    def test_bar_chart_uses_status_palette_hex(self):
        from doxtr_doto.charts import generate_summary_charts_latex

        out = generate_summary_charts_latex(self._tasks(), ["status"], "bar")
        # open -> #198754 from STATUS_COLORS, emitted without leading '#'.
        assert "198754" in out

    def test_pie_chart_emits_slices(self):
        from doxtr_doto.charts import generate_summary_charts_latex

        out = generate_summary_charts_latex(self._tasks(), ["priority"], "pie")
        assert "\\begin{dotochartpie}" in out
        assert "\\dotochartslice" in out
        assert "\\end{dotochartpie}" in out

    def test_stacked_bar_reuses_bar_renderer(self):
        from doxtr_doto.charts import generate_summary_charts_latex

        out = generate_summary_charts_latex(self._tasks(), ["status"], "stacked-bar")
        assert "\\dotochartbar" in out

    def test_progress_chart(self):
        from doxtr_doto.charts import generate_summary_charts_latex

        out = generate_summary_charts_latex(self._tasks(), ["status"], "progress")
        # 1 of 3 done -> 33%
        assert "\\dotochartprogress{33}{1}{3}" in out

    def test_unknown_type_falls_back_to_bar(self):
        from doxtr_doto.charts import generate_summary_charts_latex

        out = generate_summary_charts_latex(self._tasks(), ["status"], "nope")
        assert "\\dotochartbar" in out

    def test_burndown_falls_back_to_bar_without_dates(self):
        from doxtr_doto.charts import generate_summary_charts_latex

        # dict tasks have no created dates -> burndown falls back to status bars
        out = generate_summary_charts_latex(self._tasks(), ["status"], "burndown")
        assert "\\dotochartbar" in out

    def test_burndown_emits_line_with_dates(self):
        from datetime import date, timedelta

        from doxtr_doto.charts import generate_summary_charts_latex

        today = date.today()
        tasks = [
            {"id": "B-1", "status": "open", "created": (today - timedelta(days=5)).isoformat()},
            {
                "id": "B-2",
                "status": "done",
                "created": (today - timedelta(days=4)).isoformat(),
                "updated": (today - timedelta(days=1)).isoformat(),
            },
        ]
        out = generate_summary_charts_latex(tasks, ["status"], "burndown")
        assert "\\dotochartline{" in out
        # coordinates are (x,y) pairs
        assert "(0.0000," in out

    def test_labels_are_latex_escaped(self):
        from doxtr_doto.charts import generate_summary_charts_latex

        tasks = [{"id": "T", "status": "open", "assignee": "a_b&c"}]
        out = generate_summary_charts_latex(tasks, ["assignee"], "bar")
        assert "a\\_b\\&c" in out


class TestChartDispatchRegistries:
    """The chart-type dispatch is a dict-based registry (extensibility)."""

    def test_svg_registry_covers_all_valid_types(self):
        from doxtr_doto.charts import SVG_CHART_RENDERERS, VALID_CHART_TYPES

        assert set(SVG_CHART_RENDERERS) == set(VALID_CHART_TYPES)

    def test_latex_registry_covers_all_valid_types(self):
        from doxtr_doto.charts import LATEX_CHART_RENDERERS, VALID_CHART_TYPES

        assert set(LATEX_CHART_RENDERERS) == set(VALID_CHART_TYPES)

    def test_plotly_registry_covers_all_valid_types(self):
        from doxtr_doto.charts import PLOTLY_CHART_BUILDERS, VALID_CHART_TYPES

        assert set(PLOTLY_CHART_BUILDERS) == set(VALID_CHART_TYPES)

    def test_svg_registry_values_are_callable(self):
        from doxtr_doto.charts import SVG_CHART_RENDERERS

        assert all(callable(v) for v in SVG_CHART_RENDERERS.values())

    def test_latex_registry_values_are_callable(self):
        from doxtr_doto.charts import LATEX_CHART_RENDERERS

        assert all(callable(v) for v in LATEX_CHART_RENDERERS.values())


class TestBurndownDedup:
    """Both burndown paths share one series helper and guard None status."""

    def test_shared_helper_used_by_both_engines(self):
        from datetime import date, timedelta

        from doxtr_doto.charts import _burndown_daily_counts, _burndown_series

        today = date.today()
        tasks = [
            {"id": "B-1", "status": "open", "created": (today - timedelta(days=3)).isoformat()},
        ]
        raw = _burndown_daily_counts(tasks)
        series = _burndown_series(tasks)
        assert raw is not None and series is not None
        start, counts = raw
        dates, series_counts = series
        assert counts == series_counts
        assert dates[0] == start.isoformat()

    def test_none_status_does_not_crash(self):
        from datetime import date, timedelta

        from doxtr_doto.charts import _burndown_daily_counts, generate_burndown_chart

        today = date.today()
        tasks = [
            {"id": "B-1", "status": None, "created": (today - timedelta(days=3)).isoformat()},
        ]
        # Must not raise AttributeError on None.lower()
        result = _burndown_daily_counts(tasks)
        assert result is not None
        # SVG path also survives
        generate_burndown_chart(tasks)
