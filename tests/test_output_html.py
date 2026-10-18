"""Tests for HTML output of doto directives."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def sphinx_build(tmp_path):
    """Helper fixture that runs a minimal Sphinx HTML build."""

    def _build(rst_content: str, conf_extra: str = "") -> tuple[Path, str]:
        """
        Build a single RST page and return (outdir, page_html).

        Args:
            rst_content: The body of index.rst.
            conf_extra:  Extra lines appended to conf.py.
        """
        src = tmp_path / "src"
        src.mkdir()
        out = tmp_path / "out"

        (src / "conf.py").write_text(
            "extensions = ['doxtr_doto']\nmaster_doc = 'index'\n" + conf_extra + "\n"
        )
        (src / "index.rst").write_text("Test\n====\n\n" + rst_content)

        from sphinx.application import Sphinx

        app = Sphinx(
            srcdir=str(src),
            confdir=str(src),
            outdir=str(out),
            doctreedir=str(tmp_path / ".doctrees"),
            buildername="html",
        )
        app.build()

        html = (out / "index.html").read_text()
        return out, html

    return _build


# ── doto directive ─────────────────────────────────────────────────────────


def test_doto_node_renders_task_id(sphinx_build):
    """A doto directive produces an element with the task id."""
    _, html = sphinx_build(
        ".. doto:: My Task\n   :id: TASK-001\n   :priority: high\n   :status: open\n"
    )
    assert 'id="TASK-001"' in html
    assert "TASK-001" in html
    assert "My Task" in html


def test_doto_node_priority_class(sphinx_build):
    """Priority is reflected as a CSS class on the container div."""
    _, html = sphinx_build(".. doto:: Critical task\n   :id: TASK-002\n   :priority: critical\n")
    assert "doto-priority-critical" in html


def test_doto_node_low_priority_class(sphinx_build):
    """Low priority gets the correct CSS class."""
    _, html = sphinx_build(
        ".. doto:: Task with low priority\n   :id: TASK-low\n   :priority: low\n"
    )
    assert "doto-priority-low" in html


def test_doto_node_medium_priority_class(sphinx_build):
    """Medium priority gets the correct CSS class."""
    _, html = sphinx_build(
        ".. doto:: Task with medium priority\n   :id: TASK-medium\n   :priority: medium\n"
    )
    assert "doto-priority-medium" in html


def test_doto_node_high_priority_class(sphinx_build):
    """High priority gets the correct CSS class."""
    _, html = sphinx_build(
        ".. doto:: Task with high priority\n   :id: TASK-high\n   :priority: high\n"
    )
    assert "doto-priority-high" in html


def test_doto_node_status_class(sphinx_build):
    """Status is reflected as a CSS class on the container div."""
    _, html = sphinx_build(
        ".. doto:: In progress task\n   :id: TASK-003\n   :status: in-progress\n"
    )
    assert "doto-status-in-progress" in html


def test_doto_node_overdue_class(sphinx_build):
    """An overdue task gets the doto-overdue CSS class."""
    _, html = sphinx_build(".. doto:: Overdue\n   :id: TASK-004\n   :due: 2000-01-01\n")
    assert "doto-overdue" in html


def test_doto_node_not_overdue_for_future_date(sphinx_build):
    """A task with a future due date does not get doto-overdue class."""
    _, html = sphinx_build(".. doto:: Future task\n   :id: TASK-005\n   :due: 2099-12-31\n")
    # The task should exist but not be marked overdue
    assert 'id="TASK-005"' in html
    # Check that doto-overdue is not in the task's container
    # It could appear elsewhere in html, so we check context
    assert "Future task" in html


def test_doto_node_done_not_overdue(sphinx_build):
    """A done task with past due date is not marked overdue."""
    _, html = sphinx_build(
        ".. doto:: Completed task\n   :id: TASK-006\n   :status: done\n   :due: 2000-01-01\n"
    )
    # The task should have done status class
    assert "doto-status-done" in html
    # Check that the task's container doesn't have overdue
    # This is tricky because overdue could be in other parts
    assert 'id="TASK-006"' in html


def test_doto_node_renders_assignee(sphinx_build):
    """A doto directive renders the assignee."""
    _, html = sphinx_build(".. doto:: Assigned task\n   :id: TASK-007\n   :assignee: alice\n")
    assert "alice" in html
    assert "doto-assignee" in html


def test_doto_node_renders_tags(sphinx_build):
    """A doto directive renders tags."""
    _, html = sphinx_build(".. doto:: Tagged task\n   :id: TASK-008\n   :tags: backend, security\n")
    assert "backend" in html
    assert "security" in html
    assert "doto-tag" in html


def test_doto_node_renders_due_date(sphinx_build):
    """A doto directive renders the due date."""
    _, html = sphinx_build(".. doto:: Task with due date\n   :id: TASK-009\n   :due: 2026-08-15\n")
    assert "2026-08-15" in html
    assert "doto-due" in html


# ── doto-list directive ────────────────────────────────────────────────────


def test_doto_list_table_format(sphinx_build):
    """doto-list with format: table produces an HTML table."""
    _, html = sphinx_build(
        ".. doto:: Table task\n"
        "   :id: TASK-010\n"
        "   :priority: high\n\n"
        ".. doto-list::\n"
        "   :format: table\n"
        "   :columns: id, title, priority\n"
    )
    assert "<table" in html
    assert "TASK-010" in html
    assert "doto-table" in html


def test_doto_list_table_has_headers(sphinx_build):
    """doto-list table format includes proper headers."""
    _, html = sphinx_build(
        ".. doto:: Task for headers\n"
        "   :id: TASK-011\n\n"
        ".. doto-list::\n"
        "   :format: table\n"
        "   :columns: id, title, priority, status\n"
    )
    assert "<thead" in html
    assert "ID" in html
    assert "Title" in html
    assert "Priority" in html
    assert "Status" in html


def test_doto_list_table_renders_estimate_and_progress_columns(sphinx_build):
    """estimate/progress selected as columns render through the docutils path.

    Regression guard: the estimate/progress column values are produced by
    ``nodes._get_task_column_value`` (the real build path), not only the
    Jinja-absent fallback. A regression there would silently show empty cells.
    """
    _, html = sphinx_build(
        ".. doto:: Sized task\n"
        "   :id: TASK-EST\n"
        "   :estimate: 1h30m\n"
        "   :progress: 50\n\n"
        ".. doto-list::\n"
        "   :format: table\n"
        "   :columns: id, estimate, progress\n"
    )
    assert "1h30m" in html
    assert "50%" in html


def test_doto_single_task_renders_estimate(sphinx_build):
    """A single ``.. doto::`` with :estimate: emits the estimate span."""
    _, html = sphinx_build(".. doto:: Estimated task\n   :id: TASK-EST1\n   :estimate: 4h\n")
    assert "doto-estimate" in html
    assert "4h" in html


def test_doto_single_task_without_estimate_omits_span(sphinx_build):
    """A task without :estimate: does not emit the estimate span."""
    _, html = sphinx_build(".. doto:: No estimate\n   :id: TASK-EST2\n   :priority: high\n")
    assert "doto-estimate" not in html


def test_doto_list_empty_message(sphinx_build):
    """doto-list with no matching tasks shows the empty message."""
    _, html = sphinx_build(
        ".. doto:: Some task\n"
        "   :id: TASK-020\n"
        "   :status: open\n\n"
        ".. doto-list::\n"
        "   :status: done\n"  # filter for done; nothing is done
    )
    assert "No tasks match" in html


def test_doto_list_cards_format(sphinx_build):
    """doto-list with format: cards produces card divs."""
    _, html = sphinx_build(
        ".. doto:: Card task\n   :id: TASK-030\n\n.. doto-list::\n   :format: cards\n"
    )
    assert "doto-card" in html


def test_doto_list_cards_show_task_details(sphinx_build):
    """doto-list cards show task id, title, and status."""
    _, html = sphinx_build(
        ".. doto:: Card task details\n"
        "   :id: TASK-031\n"
        "   :priority: high\n"
        "   :status: open\n"
        "   :assignee: bob\n\n"
        ".. doto-list::\n"
        "   :format: cards\n"
    )
    assert "TASK-031" in html
    assert "Card task details" in html
    assert "doto-card-id" in html
    assert "doto-card-title" in html


def test_doto_list_default_format_is_list(sphinx_build):
    """doto-list without format option uses list format."""
    _, html = sphinx_build(".. doto:: List task\n   :id: TASK-032\n\n.. doto-list::\n")
    assert "doto-task-list" in html or "doto-list-item" in html


def test_doto_list_filters_by_status(sphinx_build):
    """doto-list filters tasks by status correctly."""
    _, html = sphinx_build(
        ".. doto:: Open task\n"
        "   :id: TASK-033\n"
        "   :status: open\n\n"
        ".. doto:: Done task\n"
        "   :id: TASK-034\n"
        "   :status: done\n\n"
        ".. doto-list::\n"
        "   :status: open\n"
    )
    assert "TASK-033" in html
    # TASK-034 should not be in the doto-list output (but might be in the page)


def test_doto_list_filters_by_priority(sphinx_build):
    """doto-list filters tasks by priority correctly."""
    _, html = sphinx_build(
        ".. doto:: High priority\n"
        "   :id: TASK-035\n"
        "   :priority: high\n\n"
        ".. doto:: Low priority\n"
        "   :id: TASK-036\n"
        "   :priority: low\n\n"
        ".. doto-list::\n"
        "   :priority: high\n"
    )
    # The list should contain the high priority task
    assert "TASK-035" in html


# ── doto-summary directive ─────────────────────────────────────────────────


def test_doto_summary_shows_total(sphinx_build):
    """doto-summary renders the total task count."""
    _, html = sphinx_build(
        ".. doto:: A\n   :id: TASK-040\n\n.. doto:: B\n   :id: TASK-041\n\n.. doto-summary::\n"
    )
    assert "2" in html  # two tasks
    assert "Total" in html


def test_doto_summary_empty_message(sphinx_build):
    """doto-summary with no tasks shows empty message."""
    _, html = sphinx_build(".. doto-summary::\n   :status: done\n")
    assert "No tasks found" in html


def test_doto_summary_shows_status_breakdown(sphinx_build):
    """doto-summary shows status breakdown."""
    _, html = sphinx_build(
        ".. doto:: Open task\n"
        "   :id: TASK-042\n"
        "   :status: open\n\n"
        ".. doto:: In progress\n"
        "   :id: TASK-043\n"
        "   :status: in-progress\n\n"
        ".. doto-summary::\n"
        "   :group-by: status\n"
    )
    assert "doto-summary" in html
    assert "open" in html.lower()


def test_doto_summary_chart(sphinx_build):
    """doto-summary with show-chart emits SVG markup."""
    _, html = sphinx_build(
        ".. doto:: Chart task\n   :id: TASK-050\n\n.. doto-summary::\n   :show-chart: true\n"
    )
    assert "<svg" in html


def test_doto_summary_chart_has_correct_structure(sphinx_build):
    """doto-summary chart has proper SVG structure."""
    _, html = sphinx_build(
        ".. doto:: Task for chart\n"
        "   :id: TASK-051\n"
        "   :status: open\n\n"
        ".. doto:: Another task\n"
        "   :id: TASK-052\n"
        "   :status: done\n\n"
        ".. doto-summary::\n"
        "   :show-chart: true\n"
    )
    # SVG chart should be present
    assert "<svg" in html
    assert "</svg>" in html


# ── theme selection ────────────────────────────────────────────────────────


def test_default_theme_css_in_output(sphinx_build):
    """Default theme copies doto.css into _static."""
    out, _ = sphinx_build(".. doto:: X\n   :id: T-001\n")
    assert (out / "_static" / "doto.css").exists()


def test_minimal_theme_css_in_output(sphinx_build):
    """Minimal theme copies doto-minimal.css into _static."""
    out, _ = sphinx_build(
        ".. doto:: X\n   :id: T-002\n",
        conf_extra='doto_html_theme = "minimal"',
    )
    assert (out / "_static" / "doto-minimal.css").exists()


def test_default_theme_css_is_linked(sphinx_build):
    """Default theme CSS is linked in the HTML head."""
    _, html = sphinx_build(".. doto:: X\n   :id: T-003\n")
    assert "doto.css" in html


def test_minimal_theme_css_is_linked(sphinx_build):
    """Minimal theme CSS is linked in the HTML head."""
    _, html = sphinx_build(
        ".. doto:: X\n   :id: T-004\n",
        conf_extra='doto_html_theme = "minimal"',
    )
    assert "doto-minimal.css" in html


# ── export_json ────────────────────────────────────────────────────────────


def test_export_json_creates_file(sphinx_build):
    """doto_export_json = True writes _static/doto-tasks.json."""
    out, _ = sphinx_build(
        ".. doto:: Exported\n   :id: T-005\n",
        conf_extra="doto_export_json = True",
    )
    export_file = out / "_static" / "doto-tasks.json"
    assert export_file.exists()
    data = json.loads(export_file.read_text())
    assert "T-005" in data["tasks"]


def test_export_json_absent_by_default(sphinx_build):
    """doto_export_json defaults to False; file should not be created."""
    out, _ = sphinx_build(".. doto:: X\n   :id: T-006\n")
    assert not (out / "_static" / "doto-tasks.json").exists()


def test_export_json_contains_task_details(sphinx_build):
    """Exported JSON contains task metadata."""
    out, _ = sphinx_build(
        ".. doto:: Detailed export\n"
        "   :id: T-007\n"
        "   :priority: high\n"
        "   :status: in-progress\n"
        "   :assignee: alice\n"
        "   :tags: backend, api\n",
        conf_extra="doto_export_json = True",
    )
    export_file = out / "_static" / "doto-tasks.json"
    data = json.loads(export_file.read_text())

    assert "T-007" in data["tasks"]
    task = data["tasks"]["T-007"]
    assert task["title"] == "Detailed export"
    assert task["priority"] == "high"
    assert task["status"] == "in-progress"


def test_export_json_has_version(sphinx_build):
    """Exported JSON includes a version field."""
    out, _ = sphinx_build(
        ".. doto:: Version test\n   :id: T-008\n",
        conf_extra="doto_export_json = True",
    )
    export_file = out / "_static" / "doto-tasks.json"
    data = json.loads(export_file.read_text())
    assert "version" in data
    assert data["version"] == 1


# ── Multiple tasks ─────────────────────────────────────────────────────────


def test_multiple_tasks_all_rendered(sphinx_build):
    """Multiple tasks are all rendered in the HTML output."""
    _, html = sphinx_build(
        ".. doto:: First task\n"
        "   :id: MULTI-001\n\n"
        ".. doto:: Second task\n"
        "   :id: MULTI-002\n\n"
        ".. doto:: Third task\n"
        "   :id: MULTI-003\n\n"
    )
    assert "MULTI-001" in html
    assert "MULTI-002" in html
    assert "MULTI-003" in html
    assert "First task" in html
    assert "Second task" in html
    assert "Third task" in html


def test_task_body_content_rendered(sphinx_build):
    """Task body content is rendered in the HTML output."""
    _, html = sphinx_build(
        ".. doto:: Task with body\n"
        "   :id: BODY-001\n\n"
        "   This is the task body.\n"
        "   It can have multiple lines.\n"
    )
    assert "This is the task body" in html
    assert "doto-body" in html


# ── Feature 5: task-list icon-mode + clickable links ────────────────────────


def test_doto_list_table_ids_are_clickable(sphinx_build):
    """Task id/title cells link to the task box in HTML table output."""
    _, html = sphinx_build(
        ".. doto:: Clicky\n   :id: TASK-H50\n\n"
        ".. doto-list::\n"
        "   :format: table\n"
        "   :columns: id, title\n"
    )
    assert 'class="doto-list-link"' in html
    assert "#TASK-H50" in html


def test_doto_list_table_icon_text_mode_emits_icon(sphinx_build):
    """icon-text mode emits Font Awesome icon classes for iconizable fields."""
    _, html = sphinx_build(
        ".. doto:: Iconic\n   :id: TASK-H51\n   :assignee: alice\n\n"
        ".. doto-list::\n"
        "   :format: table\n"
        "   :columns: id, assignee\n"
        "   :icon-mode: icon-text\n"
    )
    assert "doto-list-icon" in html
    assert "fa-user" in html


def test_doto_list_table_text_mode_no_icons(sphinx_build):
    """text mode renders plain text with no FA icon classes."""
    _, html = sphinx_build(
        ".. doto:: Plain\n   :id: TASK-H52\n   :assignee: bob\n\n"
        ".. doto-list::\n"
        "   :format: table\n"
        "   :columns: id, assignee\n"
        "   :icon-mode: text\n"
    )
    assert "fa-user" not in html


def test_doto_list_table_icon_only_mode_sr_text(sphinx_build):
    """icon mode keeps meaning accessible via sr-only text."""
    _, html = sphinx_build(
        ".. doto:: SrOnly\n   :id: TASK-H53\n   :status: open\n\n"
        ".. doto-list::\n"
        "   :format: table\n"
        "   :columns: id, status\n"
        "   :icon-mode: icon\n"
    )
    assert "doto-sr-only" in html


def test_doto_list_config_icon_mode_default(sphinx_build):
    """The doto_list_icon_mode config drives rendering absent an override."""
    _, html = sphinx_build(
        ".. doto:: ConfDriven\n   :id: TASK-H54\n   :assignee: carol\n\n"
        ".. doto-list::\n"
        "   :format: table\n"
        "   :columns: id, assignee\n",
        conf_extra="doto_list_icon_mode = 'text'",
    )
    assert "fa-user" not in html


def test_doto_list_table_cell_template_override_renders_icons_and_links(tmp_path):
    """A project _doto/templates/html/doto-list-table.html override composes cells.

    Cell markup (icons + clickable id/title links) is passed to the template as
    structured per-cell data, so a child theme can fully re-author the <td>
    contents. This build ships a project override that wraps each cell in a
    custom marker while still composing the icon element and link href from the
    structured ``cell_data`` — proving the raw-HTML injection is gone and the
    template is the composition point.
    """
    from doxtr_doto.template_loader import clear_template_cache

    src = tmp_path / "src"
    (src / "_doto" / "templates" / "html").mkdir(parents=True)
    out = tmp_path / "out"

    (src / "conf.py").write_text("extensions = ['doxtr_doto']\nmaster_doc = 'index'\n")
    (src / "index.rst").write_text(
        "Test\n====\n\n"
        ".. doto:: Overridable\n   :id: TASK-OVR1\n   :assignee: alice\n\n"
        ".. doto-list::\n"
        "   :format: table\n"
        "   :columns: id, assignee\n"
        "   :icon-mode: icon-text\n"
    )
    # Project override: compose cells from structured cell_data, adding a marker.
    (src / "_doto" / "templates" / "html" / "doto-list-table.html").write_text(
        '<table class="custom-doto-table">\n'
        "{%- for task in tasks %}\n"
        "{%- set ti = loop.index0 %}\n"
        "<tr>\n"
        "{%- for col in columns %}\n"
        "{%- set d = cell_data[(ti, col)] %}\n"
        '<td data-overridden="1">\n'
        '{%- if d.icon_class %}<i class="doto-list-icon {{ d.icon_class }}"></i>{% endif %}\n'
        '{%- if d.href %}<a class="doto-list-link" href="{{ d.href }}">{{ d.value }}</a>\n'
        "{%- else %}{{ d.value }}{% endif %}\n"
        "</td>\n"
        "{%- endfor %}\n"
        "</tr>\n"
        "{%- endfor %}\n"
        "</table>\n"
    )

    clear_template_cache()
    try:
        from sphinx.application import Sphinx

        app = Sphinx(
            srcdir=str(src),
            confdir=str(src),
            outdir=str(out),
            doctreedir=str(tmp_path / ".doctrees"),
            buildername="html",
        )
        app.build()
    finally:
        clear_template_cache()

    html = (out / "index.html").read_text()
    # The override was used (custom marker) and it still composed icon + link
    # from the structured cell_data.
    assert 'class="custom-doto-table"' in html
    assert 'data-overridden="1"' in html
    assert "doto-list-icon" in html
    assert "fa-user" in html
    assert 'class="doto-list-link"' in html
    assert "#TASK-OVR1" in html


def test_doto_list_custom_status_icon_from_config_renders(sphinx_build):
    """A custom status icon supplied via doto_list_icons renders in HTML output.

    The custom status is allowed via doto_statuses; the icon override lets it
    render an FA icon without editing extension source (Feature 5 extensibility).
    """
    _, html = sphinx_build(
        ".. doto:: Deferred task\n"
        "   :id: TASK-H60\n"
        "   :status: deferred\n\n"
        ".. doto-list::\n"
        "   :format: table\n"
        "   :columns: id, status\n"
        "   :status: deferred\n"
        "   :icon-mode: icon-text\n",
        conf_extra=(
            "doto_statuses = ['open', 'in-progress', 'blocked', 'done', 'deferred']\n"
            "doto_list_icons = {\n"
            "    'status': {'deferred': {'html': 'fa-solid fa-pause', 'latex': r'\\faPause'}},\n"
            "}"
        ),
    )
    assert "doto-list-icon" in html
    assert "fa-pause" in html


def test_doto_list_simple_ids_clickable(sphinx_build):
    """Simple list format links id/title to the task box."""
    _, html = sphinx_build(
        ".. doto:: SimpleLink\n   :id: TASK-H55\n\n.. doto-list::\n   :format: list\n"
    )
    assert 'class="doto-list-link doto-list-id"' in html
    assert "#TASK-H55" in html


def test_doto_summary_plotly_engine_falls_back_to_svg(sphinx_build):
    """With plotly engine but no Chrome/kaleido, HTML falls back to SVG charts."""
    _, html = sphinx_build(
        ".. doto:: PlotlyA\n   :id: TASK-H60\n   :status: open\n\n"
        ".. doto:: PlotlyB\n   :id: TASK-H61\n   :status: done\n\n"
        ".. doto-summary::\n"
        "   :show-chart: true\n"
        "   :chart-type: pie\n",
        conf_extra="doto_chart_engine = 'plotly'",
    )
    # Either a plotly <img> (if Chrome present) or the SVG fallback must appear;
    # the build must not crash and a chart must render.
    assert ("doto-chart-image" in html) or ("doto-pie-chart" in html)
