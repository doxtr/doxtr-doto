"""Tests for doto-list layout views (kanban / calendar / email).

Covers the new ``:format:`` layout views added for the configurable
task-list layout feature:

* each new format renders (statuscode 0) and emits its namespaced container
* kanban groups tasks by status into columns
* calendar places a due task on its day
* email emits the three panes
* invalid formats are still rejected; existing formats unchanged
* LaTeX / epub builds with a new format do not crash (graceful fallback)
* the vendored JS / CSS assets are registered and copied to ``_static``
* the ListFormat enum and the directive VALID_FORMATS stay in sync

Follows the ``sphinx_build`` fixture pattern from ``test_output_html.py`` and
the directive-build patterns from ``test_directive_doto_list.py``.
"""

from __future__ import annotations

import io

import pytest

# ── shared helpers ───────────────────────────────────────────────────────────


def _write_list_page(doto_srcdir, name: str, options: str) -> None:
    """Write a doto-list page with the given option block and toctree it."""
    page = doto_srcdir / f"{name}.rst"
    page.write_text(f"{name.title()}\n{'=' * len(name)}\n\n.. doto-list::\n{options}")
    index = doto_srcdir / "index.rst"
    index.write_text(index.read_text() + f"\n   {name}\n")


# ── enum <-> directive sync ──────────────────────────────────────────────────


class TestLayoutEnumSync:
    """The new formats must be present in the enum and the directive set."""

    def test_enum_has_new_formats(self):
        from doxtr_doto.enums import ListFormat

        values = {e.value for e in ListFormat}
        assert {"kanban", "calendar", "email"} <= values

    def test_valid_formats_matches_enum(self):
        from doxtr_doto.directives.doto_list import VALID_FORMATS
        from doxtr_doto.enums import ListFormat

        assert VALID_FORMATS == {e.value for e in ListFormat}

    def test_renderers_registered_for_each_format(self):
        from doxtr_doto.enums import ListFormat
        from doxtr_doto.nodes import _LIST_RENDERERS

        for fmt in (f.value for f in ListFormat):
            # table dispatches with columns separately in the visit handler, but
            # every format must have a renderer entry (table included).
            assert fmt in _LIST_RENDERERS


# ── HTML rendering of each new view ──────────────────────────────────────────


class TestLayoutViewsHtml:
    """Each new format renders and emits its namespaced container."""

    def test_kanban_renders_container(self, doto_srcdir, make_app, sample_tasks_rst):
        _write_list_page(doto_srcdir, "kanban", "   :format: kanban\n")
        app = make_app(srcdir=doto_srcdir)
        app.build()
        assert app.statuscode == 0
        html = (app.outdir / "kanban.html").read_text()
        assert "doto-kanban" in html
        assert 'data-doto-view="kanban"' in html

    def test_calendar_renders_container(self, doto_srcdir, make_app, sample_tasks_rst):
        _write_list_page(doto_srcdir, "calendar", "   :format: calendar\n")
        app = make_app(srcdir=doto_srcdir)
        app.build()
        assert app.statuscode == 0
        html = (app.outdir / "calendar.html").read_text()
        assert "doto-calendar" in html
        assert 'data-doto-view="calendar"' in html

    def test_email_renders_container(self, doto_srcdir, make_app, sample_tasks_rst):
        _write_list_page(doto_srcdir, "email", "   :format: email\n")
        app = make_app(srcdir=doto_srcdir)
        app.build()
        assert app.statuscode == 0
        html = (app.outdir / "email.html").read_text()
        assert "doto-email" in html
        assert 'data-doto-view="email"' in html

    def test_existing_formats_unchanged(self, doto_srcdir, make_app, sample_tasks_rst):
        """The pre-existing list/table/cards formats still build cleanly."""
        _write_list_page(doto_srcdir, "classic", "   :format: cards\n")
        app = make_app(srcdir=doto_srcdir)
        app.build()
        assert app.statuscode == 0
        html = (app.outdir / "classic.html").read_text()
        assert "doto-card" in html


class TestKanbanGrouping:
    """Kanban groups tasks into status columns."""

    def test_tasks_grouped_by_status(self, doto_srcdir, make_app, sample_tasks_rst):
        # sample_tasks_rst: TASK-001 open, TASK-002 in-progress, TASK-003 blocked.
        _write_list_page(doto_srcdir, "board", "   :format: kanban\n")
        app = make_app(srcdir=doto_srcdir)
        app.build()
        html = (app.outdir / "board.html").read_text()

        # Columns for each configured status are present.
        for status in ("open", "in-progress", "blocked", "done"):
            assert f'data-doto-status="{status}"' in html
            assert f'data-doto-dropzone="{status}"' in html

        # Each task card carries its own status, and open-task TASK-001 is
        # inside the open dropzone (grouping, not just presence).
        open_zone = html.split('data-doto-dropzone="open"', 1)[1]
        open_zone = open_zone.split("</ul>", 1)[0]
        assert "TASK-001" in open_zone

        progress_zone = html.split('data-doto-dropzone="in-progress"', 1)[1]
        progress_zone = progress_zone.split("</ul>", 1)[0]
        assert "TASK-002" in progress_zone


class TestCalendarPlacement:
    """Calendar places a due task on its day."""

    def test_due_task_on_its_day(self, doto_srcdir, make_app, sample_tasks_rst):
        # TASK-001 is due 2026-08-15 in the sample fixture.
        _write_list_page(doto_srcdir, "cal", "   :format: calendar\n")
        app = make_app(srcdir=doto_srcdir)
        app.build()
        html = (app.outdir / "cal.html").read_text()

        assert "August 2026" in html
        # The due day's panel exists and holds the task.
        assert 'data-doto-day-panel="2026-08-15"' in html
        panel = html.split('data-doto-day-panel="2026-08-15"', 1)[1]
        panel = panel.split("</ul>", 1)[0]
        assert "TASK-001" in panel

    def test_undated_task_is_unscheduled(self, doto_srcdir, make_app, sample_tasks_rst):
        # TASK-002 / TASK-003 have no due date -> unscheduled bucket.
        _write_list_page(doto_srcdir, "cal2", "   :format: calendar\n")
        app = make_app(srcdir=doto_srcdir)
        app.build()
        html = (app.outdir / "cal2.html").read_text()
        assert "doto-calendar-unscheduled" in html


class TestEmailPanes:
    """Email view emits the three panes."""

    def test_three_panes_present(self, doto_srcdir, make_app, sample_tasks_rst):
        _write_list_page(doto_srcdir, "mail", "   :format: email\n")
        app = make_app(srcdir=doto_srcdir)
        app.build()
        html = (app.outdir / "mail.html").read_text()

        # Left tree, top-right list, bottom-right detail.
        assert "doto-email-tree" in html
        assert "doto-email-list" in html
        assert "doto-email-detail" in html
        # Tree groups by status, list rows are selectable, detail panels exist.
        assert 'data-doto-tree-filter="open"' in html
        assert 'data-doto-select="TASK-001"' in html
        assert 'data-doto-detail="TASK-001"' in html


# ── invalid format still rejected ────────────────────────────────────────────


class TestInvalidFormat:
    """An unknown :format: value is rejected at parse time."""

    def test_invalid_format_reports_error(self, doto_srcdir, tmp_path, sample_tasks_rst):
        from sphinx.application import Sphinx

        _write_list_page(doto_srcdir, "bad", "   :format: bogus\n")
        warning_stream = io.StringIO()
        outdir = tmp_path / "build" / "bad-html"
        doctreedir = tmp_path / "build" / "bad-doctrees"
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
        warnings = warning_stream.getvalue()
        assert "Invalid format 'bogus'" in warnings
        # The message lists the accepted values so authors can self-correct.
        assert "kanban" in warnings


# ── LaTeX / epub graceful fallback ───────────────────────────────────────────


class TestGracefulFallback:
    """LaTeX and epub builds with a new format degrade without crashing."""

    @pytest.mark.parametrize("fmt", ["kanban", "calendar", "email"])
    def test_latex_build_does_not_crash(self, doto_srcdir, make_app, sample_tasks_rst, fmt):
        _write_list_page(doto_srcdir, f"latex_{fmt}", f"   :format: {fmt}\n")
        app = make_app(buildername="latex", srcdir=doto_srcdir)
        app.build()
        assert app.statuscode == 0

    @pytest.mark.parametrize("fmt", ["kanban", "calendar", "email"])
    def test_epub_build_does_not_crash(self, doto_srcdir, make_app, sample_tasks_rst, fmt):
        _write_list_page(doto_srcdir, f"epub_{fmt}", f"   :format: {fmt}\n")
        app = make_app(buildername="epub", srcdir=doto_srcdir)
        app.build()
        assert app.statuscode == 0


# ── asset registration / copy ────────────────────────────────────────────────


class TestAssetRegistration:
    """The vendored JS and CSS are registered and copied to _static."""

    def test_views_js_copied_to_static(self, doto_srcdir, make_app, sample_tasks_rst):
        _write_list_page(doto_srcdir, "assets", "   :format: kanban\n")
        app = make_app(srcdir=doto_srcdir)
        app.build()
        js = app.outdir / "_static" / "doto-views.js"
        assert js.exists()
        # Registered as a script in the rendered page.
        html = (app.outdir / "assets.html").read_text()
        assert "doto-views.js" in html

    def test_css_contains_layout_styles(self, doto_srcdir, make_app, sample_tasks_rst):
        _write_list_page(doto_srcdir, "css", "   :format: kanban\n")
        app = make_app(srcdir=doto_srcdir)
        app.build()
        css = app.outdir / "_static" / "doto.css"
        assert css.exists()
        text = css.read_text()
        assert ".doto-kanban" in text
        assert ".doto-calendar" in text
        assert ".doto-email" in text

    def test_js_not_registered_for_epub(self, doto_srcdir, make_app, sample_tasks_rst):
        """epub builders should not get the HTML-only JS asset registered."""
        _write_list_page(doto_srcdir, "epubassets", "   :format: kanban\n")
        app = make_app(buildername="epub", srcdir=doto_srcdir)
        app.build()
        # The HTML-only JS is not copied into the epub _static tree.
        js = app.outdir / "_static" / "doto-views.js"
        assert not js.exists()


# ── fallback renderers (Jinja2-absent path) ─────────────────────────────────


class TestFallbackRenderers:
    """The Python fallback renderers emit each view's markup without Jinja2."""

    def _make_tasks(self):
        from doxtr_doto.collectors import DotoTask

        return [
            DotoTask(
                id="T-1",
                title="Alpha",
                status="open",
                priority="high",
                due="2026-08-15",
                assignee="alice",
                tags=["x"],
                body="b1",
            ),
            DotoTask(id="T-2", title="Beta", status="in-progress", priority="low"),
        ]

    def test_kanban_fallback(self):
        from doxtr_doto.nodes import _list_status_columns
        from doxtr_doto.template_loader import _fallback_render_kanban

        tasks = self._make_tasks()
        columns = _list_status_columns(None)
        grouped = {s: [t for t in tasks if t.status == s] for s, _ in columns}
        html = _fallback_render_kanban(
            {
                "columns": columns,
                "grouped": grouped,
                "task_links": {t.id: f"#{t.id}" for t in tasks},
                "icon_mode": "icon-text",
            }
        )
        assert "doto-kanban" in html
        assert "T-1" in html
        assert 'data-doto-dropzone="open"' in html

    def test_calendar_fallback(self):
        from doxtr_doto.nodes import _calendar_month_grid
        from doxtr_doto.template_loader import _fallback_render_calendar

        tasks = self._make_tasks()
        grid = _calendar_month_grid(tasks)
        html = _fallback_render_calendar(
            {
                "calendar": grid,
                "task_links": {t.id: f"#{t.id}" for t in tasks},
                "icon_mode": "icon-text",
            }
        )
        assert "doto-calendar" in html
        assert 'data-doto-day-panel="2026-08-15"' in html
        assert "doto-calendar-unscheduled" in html

    def test_email_fallback(self):
        from doxtr_doto.nodes import _list_status_columns
        from doxtr_doto.template_loader import _fallback_render_email

        tasks = self._make_tasks()
        columns = _list_status_columns(None)
        tree = {s: [t for t in tasks if t.status == s] for s, _ in columns}
        html = _fallback_render_email(
            {
                "columns": columns,
                "tree": tree,
                "tasks": tasks,
                "task_links": {t.id: f"#{t.id}" for t in tasks},
                "icon_mode": "icon-text",
            }
        )
        assert "doto-email-tree" in html
        assert "doto-email-list" in html
        assert "doto-email-detail" in html
        assert 'data-doto-select="T-1"' in html


# -- shared grouping helper ---------------------------------------------------


class TestGroupTasksByStatus:
    """Kanban and email share one status-grouping rule."""

    def _make_tasks(self):
        from doxtr_doto.collectors import DotoTask

        return [
            DotoTask(id="T-1", title="Alpha", status="open", priority="high"),
            DotoTask(id="T-2", title="Beta", status="blocked", priority="low"),
            DotoTask(id="T-3", title="Gamma", status="mystery", priority="low"),
        ]

    def test_groups_by_known_status(self):
        from doxtr_doto.nodes import _group_tasks_by_status, _list_status_columns

        tasks = self._make_tasks()
        columns = _list_status_columns(None)
        fallback = columns[0][0]
        grouped = _group_tasks_by_status(tasks, columns)

        # Known, non-fallback statuses land in their own column.
        assert [t.id for t in grouped["blocked"]] == ["T-2"]
        # The fallback column holds its own task plus the unknown-status task.
        assert "T-1" in [t.id for t in grouped[fallback]]
        # Every column status is a key, even when empty.
        assert set(grouped) == {s for s, _ in columns}

    def test_unknown_status_falls_into_first_column(self):
        from doxtr_doto.nodes import _group_tasks_by_status, _list_status_columns

        tasks = self._make_tasks()
        columns = _list_status_columns(None)
        fallback = columns[0][0]
        grouped = _group_tasks_by_status(tasks, columns)

        # The task with an unrecognized status is not dropped; it lands in the
        # first column.
        assert "T-3" in [t.id for t in grouped[fallback]]
        # No task is lost overall.
        placed = {t.id for col in grouped.values() for t in col}
        assert placed == {"T-1", "T-2", "T-3"}

    def test_empty_columns_drops_nothing_safely(self):
        from doxtr_doto.nodes import _group_tasks_by_status

        # Defensive: no columns -> empty grouping, no crash.
        assert _group_tasks_by_status(self._make_tasks(), []) == {}


# -- Jinja/fallback render parity ---------------------------------------------


class TestRenderParity:
    """The Jinja template and the Python fallback agree on due-date display.

    The fallback docstrings promise "equivalent static markup". The kanban
    fallback previously formatted the due date while the Jinja template emits
    the raw ISO string; this locks both paths to the raw ISO value so they
    cannot drift.
    """

    def _make_tasks(self):
        from doxtr_doto.collectors import DotoTask

        return [
            DotoTask(id="T-1", title="Alpha", status="open", priority="high", due="2026-08-15"),
        ]

    def test_kanban_fallback_due_is_raw_iso(self):
        from doxtr_doto.nodes import _list_status_columns
        from doxtr_doto.template_loader import _fallback_render_kanban

        tasks = self._make_tasks()
        columns = _list_status_columns(None)
        grouped = {s: [t for t in tasks if t.status == s] for s, _ in columns}
        html = _fallback_render_kanban(
            {
                "columns": columns,
                "grouped": grouped,
                "task_links": {t.id: f"#{t.id}" for t in tasks},
                "icon_mode": "icon-text",
            }
        )
        # Raw ISO due, matching doto-list-kanban.html's ``{{ task.due }}``.
        assert ">2026-08-15<" in html

    def test_kanban_template_and_fallback_agree_on_due(
        self, doto_srcdir, make_app, sample_tasks_rst
    ):
        """The Jinja-rendered board shows the same raw due string as the fallback.

        sample_tasks_rst gives TASK-001 a due date of 2026-08-15.
        """
        _write_list_page(doto_srcdir, "parity", "   :format: kanban\n")
        app = make_app(srcdir=doto_srcdir)
        app.build()
        html = (app.outdir / "parity.html").read_text()
        assert "2026-08-15" in html


# -- JS override seam ---------------------------------------------------------


class TestViewsJsOverride:
    """A project-shipped doto-views.js replaces the bundled script."""

    def test_project_js_overrides_bundled(self, doto_srcdir, make_app, sample_tasks_rst):
        marker = "/* PROJECT OVERRIDE MARKER */"
        html_dir = doto_srcdir / "_doto" / "html"
        html_dir.mkdir(parents=True, exist_ok=True)
        # A project theme needs a CSS file for the theme branch, plus its own JS.
        (html_dir / "custom.css").write_text(".doto-kanban { color: red; }\n")
        (html_dir / "doto-views.js").write_text(marker + "\n")

        _write_list_page(doto_srcdir, "override", "   :format: kanban\n")
        app = make_app(srcdir=doto_srcdir)
        app.build()
        js = app.outdir / "_static" / "doto-views.js"
        assert js.exists()
        # The project script replaced the bundled one.
        assert marker in js.read_text()


# -- email list scroll cap (:visible-tasks: / doto_list_visible_tasks) --------


class TestEmailVisibleTasks:
    """The email list pane caps visible rows via :visible-tasks: / config.

    sample_tasks_rst has three tasks (TASK-001..003). The cap limits how many
    rows are visible at once (a scroll viewport) but must never truncate the
    rendered list — every task still renders and stays clickable.
    """

    def test_directive_option_parsed_onto_display_options(self):
        """:visible-tasks: lands on DisplayOptions via the directive parser."""
        from doxtr_doto.query import DisplayOptions

        # Round-trips through from_dict/to_dict so stored nodes stay stable.
        opts = DisplayOptions(visible_tasks=3)
        assert opts.visible_tasks == 3
        assert opts.to_dict()["visible_tasks"] == 3
        assert DisplayOptions.from_dict({"visible_tasks": 7}).visible_tasks == 7
        # Default is None -> "use config".
        assert DisplayOptions().visible_tasks is None

    def test_config_default_is_five(self):
        """The global default doto_list_visible_tasks is 5."""
        from doxtr_doto.config import DEFAULTS

        assert DEFAULTS["doto_list_visible_tasks"] == 5

    def test_resolve_prefers_directive_over_config(self):
        """A directive override wins over the config default."""

        from doxtr_doto.nodes import _resolve_visible_tasks
        from doxtr_doto.query import DisplayOptions

        class _App:
            class config:
                doto_list_visible_tasks = 5

        # Directive override present -> used verbatim.
        assert _resolve_visible_tasks(DisplayOptions(visible_tasks=2), _App()) == 2
        # No override -> fall back to the config default.
        assert _resolve_visible_tasks(DisplayOptions(visible_tasks=None), _App()) == 5
        # Zero override means "show all" and is preserved (not treated as unset).
        assert _resolve_visible_tasks(DisplayOptions(visible_tasks=0), _App()) == 0

    def test_resolve_defaults_to_five_without_app(self):
        """Without an app/config, the resolver falls back to 5."""
        from doxtr_doto.nodes import _resolve_visible_tasks
        from doxtr_doto.query import DisplayOptions

        assert _resolve_visible_tasks(DisplayOptions(), None) == 5

    def test_email_html_carries_config_default(self, doto_srcdir, make_app, sample_tasks_rst):
        """With no directive override, the email list uses the config default 5."""
        _write_list_page(doto_srcdir, "vt_default", "   :format: email\n")
        app = make_app(srcdir=doto_srcdir)
        app.build()
        assert app.statuscode == 0
        html = (app.outdir / "vt_default.html").read_text()
        assert 'data-doto-visible-tasks="5"' in html
        assert "--doto-visible-tasks: 5" in html

    def test_directive_overrides_config_in_html(self, doto_srcdir, make_app, sample_tasks_rst):
        """A directive :visible-tasks: overrides the config default in the markup."""
        _write_list_page(doto_srcdir, "vt_override", "   :format: email\n   :visible-tasks: 2\n")
        app = make_app(srcdir=doto_srcdir)
        app.build()
        assert app.statuscode == 0
        html = (app.outdir / "vt_override.html").read_text()
        assert 'data-doto-visible-tasks="2"' in html
        assert "--doto-visible-tasks: 2" in html
        assert 'data-doto-visible-tasks="5"' not in html

    def test_all_tasks_still_render_when_capped(self, doto_srcdir, make_app, sample_tasks_rst):
        """The cap limits the viewport, not the content: all tasks render."""
        _write_list_page(doto_srcdir, "vt_all", "   :format: email\n   :visible-tasks: 2\n")
        app = make_app(srcdir=doto_srcdir)
        app.build()
        html = (app.outdir / "vt_all.html").read_text()
        # All three sample tasks remain as selectable list rows.
        for task_id in ("TASK-001", "TASK-002", "TASK-003"):
            assert f'data-doto-select="{task_id}"' in html

    def test_zero_means_show_all_no_cap(self, doto_srcdir, make_app, sample_tasks_rst):
        """:visible-tasks: 0 renders no scroll-cap attribute (show all)."""
        _write_list_page(doto_srcdir, "vt_zero", "   :format: email\n   :visible-tasks: 0\n")
        app = make_app(srcdir=doto_srcdir)
        app.build()
        assert app.statuscode == 0
        html = (app.outdir / "vt_zero.html").read_text()
        assert "data-doto-visible-tasks" not in html
        assert "--doto-visible-tasks" not in html

    def test_invalid_visible_tasks_reports_parse_error(
        self, doto_srcdir, tmp_path, sample_tasks_rst
    ):
        """A non-integer / negative :visible-tasks: is rejected at parse time."""
        from sphinx.application import Sphinx

        _write_list_page(doto_srcdir, "vt_bad", "   :format: email\n   :visible-tasks: nope\n")
        warning_stream = io.StringIO()
        outdir = tmp_path / "build" / "vt-bad-html"
        doctreedir = tmp_path / "build" / "vt-bad-doctrees"
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
        warnings = warning_stream.getvalue()
        assert "Invalid visible-tasks" in warnings

    def test_css_contains_scroll_cap_rule(self, doto_srcdir, make_app, sample_tasks_rst):
        """The shipped CSS computes max-height from --doto-visible-tasks."""
        _write_list_page(doto_srcdir, "vt_css", "   :format: email\n")
        app = make_app(srcdir=doto_srcdir)
        app.build()
        text = (app.outdir / "_static" / "doto.css").read_text()
        assert "--doto-visible-tasks" in text
        assert "max-height" in text

    def test_fallback_email_emits_visible_tasks(self):
        """The Jinja-absent fallback mirrors the scroll-cap markup."""
        from doxtr_doto.collectors import DotoTask
        from doxtr_doto.nodes import _list_status_columns
        from doxtr_doto.template_loader import _fallback_render_email

        tasks = [
            DotoTask(id="T-1", title="Alpha", status="open", priority="high"),
            DotoTask(id="T-2", title="Beta", status="open", priority="low"),
        ]
        columns = _list_status_columns(None)
        tree = {s: [t for t in tasks if t.status == s] for s, _ in columns}
        html = _fallback_render_email(
            {
                "columns": columns,
                "tree": tree,
                "tasks": tasks,
                "task_links": {t.id: f"#{t.id}" for t in tasks},
                "icon_mode": "icon-text",
                "visible_tasks": 2,
            }
        )
        assert 'data-doto-visible-tasks="2"' in html
        assert "--doto-visible-tasks: 2" in html
        # All tasks still present.
        assert 'data-doto-select="T-1"' in html
        assert 'data-doto-select="T-2"' in html

    def test_capped_email_renders_every_task_row(self, doto_srcdir, make_app, sample_tasks_rst):
        """A below-count cap is a viewport, not truncation.

        The number of ``doto-email-list-item`` rows must equal the task count
        even when :visible-tasks: is lower than that count.
        """
        _write_list_page(doto_srcdir, "vt_count", "   :format: email\n   :visible-tasks: 1\n")
        app = make_app(srcdir=doto_srcdir)
        app.build()
        assert app.statuscode == 0
        html = (app.outdir / "vt_count.html").read_text()
        # sample_tasks_rst has three tasks; all three list rows must render.
        assert html.count('class="doto-email-list-item') == 3
        assert 'data-doto-visible-tasks="1"' in html

    def test_invalid_visible_tasks_leaks_no_scroll_cap(
        self, doto_srcdir, tmp_path, sample_tasks_rst
    ):
        """An invalid :visible-tasks: value emits no scroll-cap markup."""
        from sphinx.application import Sphinx

        _write_list_page(doto_srcdir, "vt_leak", "   :format: email\n   :visible-tasks: nope\n")
        warning_stream = io.StringIO()
        outdir = tmp_path / "build" / "vt-leak-html"
        doctreedir = tmp_path / "build" / "vt-leak-doctrees"
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
        page = outdir / "vt_leak.html"
        if page.exists():
            assert "data-doto-visible-tasks" not in page.read_text()

    def test_non_email_format_emits_no_scroll_cap(self, doto_srcdir, make_app, sample_tasks_rst):
        """Scope guard: :visible-tasks: only affects the email view."""
        _write_list_page(doto_srcdir, "vt_scope", "   :format: table\n   :visible-tasks: 2\n")
        app = make_app(srcdir=doto_srcdir)
        app.build()
        assert app.statuscode == 0
        html = (app.outdir / "vt_scope.html").read_text()
        assert "data-doto-visible-tasks" not in html

    def test_resolve_config_invalid_falls_back_to_default(self):
        """A bad config value makes the resolver return the DEFAULTS value."""
        from doxtr_doto.config import DEFAULTS
        from doxtr_doto.nodes import _resolve_visible_tasks
        from doxtr_doto.query import DisplayOptions

        default = DEFAULTS["doto_list_visible_tasks"]

        class _AppNeg:
            class config:
                doto_list_visible_tasks = -1

        class _AppStr:
            class config:
                doto_list_visible_tasks = "x"

        assert _resolve_visible_tasks(DisplayOptions(), _AppNeg()) == default
        assert _resolve_visible_tasks(DisplayOptions(), _AppStr()) == default

    def test_resolve_invalid_override_falls_back(self):
        """A negative directive override is rejected and falls through (FIX 3)."""
        from doxtr_doto.nodes import _resolve_visible_tasks
        from doxtr_doto.query import DisplayOptions

        class _App:
            class config:
                doto_list_visible_tasks = 5

        # An invalid override does not leak -1; it falls back to config/default.
        assert _resolve_visible_tasks(DisplayOptions(visible_tasks=-1), _App()) == 5

    def test_parse_int_negative_message_is_specific(self):
        """A negative integer reports a non-negative-specific message (FIX 8)."""
        import pytest

        from doxtr_doto.directives.doto_list import parse_int

        with pytest.raises(ValueError, match="must be non-negative"):
            parse_int("-3")
        # Non-integers still report the invalid-integer message.
        with pytest.raises(ValueError, match="Invalid integer value"):
            parse_int("nope")
