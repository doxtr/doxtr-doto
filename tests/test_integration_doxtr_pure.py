"""Core-INDEPENDENT integration tests for doxtr-pdf-theme-core.

These assertions exercise the parts of the Feature 3 / Feature 6 integration
that do not require ``doxtr-pdf-theme-core`` to be importable:

* ``build_doto_color_preamble`` — a pure ``\\definecolor`` string builder.
* ``wrap_longtable_in_landscape`` — a pure longtable-wrapping string builder.
* the no-op / graceful-degradation branches of
  ``resolve_doto_palette_colors`` and ``apply_doxtr_semantic_colors`` that run
  when the core is absent or the integration is disabled.

They deliberately live OUTSIDE the module-level ``pytest.importorskip`` used by
``test_integration_doxtr.py`` so they still run in the CI matrix job even when
the core package is not installed (testing P2). Do not add ``importorskip`` or
core-dependent assertions here — those belong in ``test_integration_doxtr.py``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

# Palette used by the no-op assertions; the values are never resolved because
# these paths short-circuit before touching the core's resolver.
PALETTE = {
    "primary": "#1B4F72",
    "secondary": "#F39C12",
    "info": "#2E86C1",
    "success": "#28B463",
    "warning": "#E67E22",
    "danger": "#E74C3C",
    "page": "#FFFFFF",
}


class TestBuildDotoColorPreamble:
    """Feature 3: emit \\definecolor overrides for the preamble (pure)."""

    def test_emits_definecolor_lines(self):
        from doxtr_doto.integration import build_doto_color_preamble

        block = build_doto_color_preamble(
            {"doto@critical": "#E74C3C", "doto@low": "#F39C12"}
        )
        assert "% doto semantic palette overrides" in block
        assert "\\definecolor{doto@critical}{HTML}{E74C3C}" in block
        assert "\\definecolor{doto@low}{HTML}{F39C12}" in block

    def test_strips_alpha_channel(self):
        from doxtr_doto.integration import build_doto_color_preamble

        block = build_doto_color_preamble({"doto@bg": "#AABBCCDD"})
        assert "\\definecolor{doto@bg}{HTML}{AABBCC}" in block

    def test_empty_input_returns_empty(self):
        from doxtr_doto.integration import build_doto_color_preamble

        assert build_doto_color_preamble({}) == ""


class TestWrapLongtableInLandscape:
    """Feature 6: wrap raw longtable output in the core landscape env (pure)."""

    def test_wraps_longtable(self):
        from doxtr_doto.integration import wrap_longtable_in_landscape

        body = "\\begin{longtable}{|l|l|}\nrow\n\\end{longtable}\n\n"
        wrapped = wrap_longtable_in_landscape(body, 5)

        assert "\\begin{longtable}" in wrapped
        assert "\\end{longtable}" in wrapped
        # Uses the core's breakable adaptive-landscape environment (defined in
        # the core preamble), sized by the column count.
        assert "\\begin{doxtradaptivelandscape}[5]" in wrapped
        assert "\\end{doxtradaptivelandscape}" in wrapped
        # Longtable content must sit inside the landscape block.
        assert wrapped.index("\\begin{doxtradaptivelandscape}") < wrapped.index(
            "\\begin{longtable}"
        )
        assert wrapped.index("\\end{longtable}") < wrapped.index(
            "\\end{doxtradaptivelandscape}"
        )


class TestResolvePaletteWithoutCore:
    """Feature 3: color resolution degrades gracefully without a palette."""

    def test_returns_empty_without_palette(self, doto_srcdir, make_app):
        from doxtr_doto.integration import resolve_doto_palette_colors

        app = make_app(srcdir=doto_srcdir, buildername="latex")
        if hasattr(app.config, "doxtr_semantic_palette"):
            delattr(app.config, "doxtr_semantic_palette")

        assert resolve_doto_palette_colors(app) == {}


class TestApplySemanticColorsNoop:
    """Feature 3: preamble injection is skipped when the core is inactive."""

    def test_noop_without_core(self, doto_srcdir, make_app):
        from doxtr_doto.integration import apply_doxtr_semantic_colors

        app = make_app(srcdir=doto_srcdir, buildername="latex")
        # No core extension registered.
        app.config.doxtr_semantic_palette = dict(PALETTE)
        app.config.latex_elements = {"preamble": "\\usepackage{doto}\n"}

        apply_doxtr_semantic_colors(app)

        assert "% doto semantic palette overrides" not in (
            app.config.latex_elements["preamble"]
        )

    def test_noop_when_disabled(self, doto_srcdir, make_app):
        from doxtr_doto.integration import apply_doxtr_semantic_colors

        conf_py = doto_srcdir / "conf.py"
        conf_py.write_text(
            "extensions = ['doxtr_doto']\n"
            "master_doc = 'index'\n"
            "doto_doxtr_integration = 'disabled'\n"
        )
        app = make_app(srcdir=doto_srcdir, buildername="latex")
        # Even with the core extension registered, an explicit "disabled"
        # integration must skip the injection.
        app.extensions["doxtr_pdf_theme_core"] = MagicMock()
        app.config.doxtr_semantic_palette = dict(PALETTE)
        app.config.latex_elements = {"preamble": "\\usepackage{doto}\n"}

        apply_doxtr_semantic_colors(app)

        assert "% doto semantic palette overrides" not in (
            app.config.latex_elements["preamble"]
        )
