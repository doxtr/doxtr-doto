"""Integration tests for doxtr-pdf-theme-core semantic coloring and landscape.

Covers Feature 3 (derive doto's LaTeX colors from the semantic palette) and
Feature 6 (auto-rotate wide task tables to landscape when the core is active).
Both must degrade gracefully: standalone builds keep the defaults from
``doto.sty`` and emit a plain longtable regardless of column count.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

# The core is expected to be importable in the test environment; skip the
# core-dependent assertions cleanly if it is ever absent.
core = pytest.importorskip("doxtr_pdf_theme_core")


PALETTE = {
    "primary": "#1B4F72",
    "secondary": "#F39C12",
    "info": "#2E86C1",
    "success": "#28B463",
    "warning": "#E67E22",
    "danger": "#E74C3C",
    "page": "#FFFFFF",
}


class TestResolveDotoPaletteColors:
    """Feature 3: resolve doto colors from the semantic palette."""

    def test_resolves_priority_and_status_colors(self, doto_srcdir, make_app):
        from doxtr_doto.integration import resolve_doto_palette_colors

        app = make_app(srcdir=doto_srcdir, buildername="latex")
        app.config.doxtr_semantic_palette = dict(PALETTE)

        resolved = resolve_doto_palette_colors(app)

        # Priority mapping: critical -> danger, high -> warning,
        # medium -> primary, low -> secondary.
        assert resolved["doto@critical"] == "#E74C3C"
        assert resolved["doto@high"] == "#E67E22"
        assert resolved["doto@medium"] == "#1B4F72"
        assert resolved["doto@low"] == "#F39C12"

        # Status mapping.
        assert resolved["doto@open"] == "#28B463"
        assert resolved["doto@inprogress"] == "#2E86C1"
        assert resolved["doto@blocked"] == "#E74C3C"
        assert resolved["doto@overdue"] == "#E74C3C"

        # Box colors are derived (non-empty hex strings).
        for key in ("doto@bg", "doto@border", "doto@titlebg", "doto@titlefg"):
            assert resolved[key].startswith("#")


# NOTE: the core-INDEPENDENT assertions (build_doto_color_preamble,
# wrap_longtable_in_landscape, resolve returns-empty-without-palette, and the
# apply no-op branches) live in test_integration_doxtr_pure.py so they run in
# the CI matrix job even when doxtr-pdf-theme-core is absent. Keep only
# core-DEPENDENT assertions here, under the module-level importorskip above.


class TestApplySemanticColors:
    """Feature 3: preamble injection is wired only when the core is active."""

    def test_injects_after_usepackage_when_core_active(self, doto_srcdir, make_app):
        from doxtr_doto.integration import apply_doxtr_semantic_colors

        app = make_app(srcdir=doto_srcdir, buildername="latex")
        app.extensions["doxtr_pdf_theme_core"] = MagicMock()
        app.config.doxtr_semantic_palette = dict(PALETTE)
        # Simulate _setup_latex_theme having already injected the usepackage.
        app.config.latex_elements = {"preamble": "\\usepackage{doto}\n"}

        apply_doxtr_semantic_colors(app)

        preamble = app.config.latex_elements["preamble"]
        assert "\\usepackage{doto}" in preamble
        assert "% doto semantic palette overrides" in preamble
        # Override must come AFTER the usepackage so xcolor's later definition wins.
        assert preamble.index("\\usepackage{doto}") < preamble.index(
            "% doto semantic palette overrides"
        )
        assert "\\definecolor{doto@critical}{HTML}{E74C3C}" in preamble

    def test_no_duplicate_injection(self, doto_srcdir, make_app):
        from doxtr_doto.integration import apply_doxtr_semantic_colors

        app = make_app(srcdir=doto_srcdir, buildername="latex")
        app.extensions["doxtr_pdf_theme_core"] = MagicMock()
        app.config.doxtr_semantic_palette = dict(PALETTE)
        app.config.latex_elements = {"preamble": "\\usepackage{doto}\n"}

        apply_doxtr_semantic_colors(app)
        apply_doxtr_semantic_colors(app)

        preamble = app.config.latex_elements["preamble"]
        assert preamble.count("% doto semantic palette overrides") == 1


class TestLandscapeThreshold:
    """Feature 6: landscape threshold reads the core's config."""

    def test_default_matches_core_constant(self, doto_srcdir, make_app):
        from doxtr_doto.integration import get_landscape_min_columns
        from doxtr_pdf_theme_core.ast_processors.landscape import (
            DEFAULT_MIN_COLUMNS,
        )

        app = make_app(srcdir=doto_srcdir, buildername="latex")
        assert get_landscape_min_columns(app) == DEFAULT_MIN_COLUMNS

    def test_honors_config_override(self, doto_srcdir, make_app):
        from doxtr_doto.integration import get_landscape_min_columns

        app = make_app(srcdir=doto_srcdir, buildername="latex")
        app.config.doxtr_landscape_min_columns = 6
        assert get_landscape_min_columns(app) == 6


def _build_latex_task_table(make_app, doto_srcdir, columns, integrated):
    """Helper: build a LaTeX task-list table and return the generated body.

    Renders a doto-list table directive with the given columns, optionally
    with doxtr-pdf-theme-core marked active, and returns the ``.tex`` output.
    """
    col_opt = ", ".join(columns)
    index_rst = doto_srcdir / "index.rst"
    index_rst.write_text(
        "Doto\n====\n\n"
        ".. doto:: Sample task\n"
        "   :id: TASK-001\n"
        "   :assignee: alice\n"
        "   :priority: high\n"
        "   :status: open\n"
        "   :due: 2026-08-15\n"
        "   :tags: backend\n\n"
        "   Body.\n\n"
        ".. doto-list::\n"
        "   :format: table\n"
        f"   :columns: {col_opt}\n"
    )

    app = make_app(srcdir=doto_srcdir, buildername="latex")
    if integrated:
        app.extensions["doxtr_pdf_theme_core"] = MagicMock()
    app.build()

    from pathlib import Path

    tex = list(Path(app.outdir).glob("*.tex"))
    assert tex, "no .tex output produced"
    return tex[0].read_text()


class TestTaskTableLandscapeRendering:
    """Feature 6: end-to-end LaTeX task-table rotation on/off."""

    def test_wide_table_rotated_when_integrated(self, doto_srcdir, make_app):
        # 5 columns >= default threshold (4): should be wrapped.
        tex = _build_latex_task_table(
            make_app,
            doto_srcdir,
            ["id", "title", "priority", "status", "due"],
            integrated=True,
        )
        assert "\\begin{longtable}" in tex
        assert "\\begin{doxtradaptivelandscape}" in tex
        assert "\\end{doxtradaptivelandscape}" in tex

    def test_narrow_table_not_rotated_when_integrated(self, doto_srcdir, make_app):
        # 2 columns < threshold: no landscape wrapping even when integrated.
        tex = _build_latex_task_table(
            make_app,
            doto_srcdir,
            ["id", "title"],
            integrated=True,
        )
        assert "\\begin{longtable}" in tex
        assert "\\begin{doxtradaptivelandscape}" not in tex

    def test_wide_table_plain_when_standalone(self, doto_srcdir, make_app):
        # 5 columns but no core: plain longtable, no landscape wrapping.
        tex = _build_latex_task_table(
            make_app,
            doto_srcdir,
            ["id", "title", "priority", "status", "due"],
            integrated=False,
        )
        assert "\\begin{longtable}" in tex
        assert "\\begin{doxtradaptivelandscape}" not in tex
        assert "\\begin{landscape}" not in tex
