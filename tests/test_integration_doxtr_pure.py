"""Core-INDEPENDENT integration tests for doxtr-pdf-theme-core.

These assertions exercise the parts of the Feature 3 / Feature 6 integration
that do not require ``doxtr-pdf-theme-core`` to be importable:

* ``build_doto_color_preamble`` — a pure ``\\definecolor`` string builder.
* ``wrap_longtable_in_landscape`` — a pure longtable-wrapping string builder.
* the no-op / graceful-degradation branches of
  ``resolve_doto_palette_colors`` and ``apply_doxtr_semantic_colors`` that run
  when the core is absent or the integration is disabled.

They deliberately live OUTSIDE the module-level ``pytest.importorskip`` used by
``test_integration_doxtr.py``: they run without ``importorskip`` and simulate
core-absence via import patching, so they do not require
``doxtr-pdf-theme-core`` to be installed. Do not add ``importorskip`` or
core-dependent assertions here — those belong in ``test_integration_doxtr.py``.
"""

from __future__ import annotations

import builtins
from unittest.mock import MagicMock, patch

import pytest

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

        block = build_doto_color_preamble({"doto@critical": "#E74C3C", "doto@low": "#F39C12"})
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
        assert wrapped.index("\\end{longtable}") < wrapped.index("\\end{doxtradaptivelandscape}")


class TestResolvePaletteWithoutCore:
    """Feature 3: color resolution degrades gracefully without the core."""

    def test_returns_empty_without_core(self, doto_srcdir, make_app):
        # Resolution now draws brand keys from the core's merged light palette
        # (core defaults -> theme -> user), so it only degrades to {} when the
        # core itself is not importable (a standalone build). Simulate that by
        # failing the core import.
        from doxtr_doto.integration import resolve_doto_palette_colors

        app = make_app(srcdir=doto_srcdir, buildername="latex")
        app.config.doxtr_semantic_palette = dict(PALETTE)

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name.startswith("doxtr_pdf_theme_core"):
                raise ImportError("simulated standalone build")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            assert resolve_doto_palette_colors(app) == {}


class TestMergedSemanticPaletteWithoutCore:
    """Feature 3: the merged-palette helper returns None without the core."""

    def test_returns_none_when_core_not_importable(self, doto_srcdir, make_app):
        # Simulate a standalone build where doxtr-pdf-theme-core is absent by
        # making its core_config import fail. The helper must return None so
        # callers skip resolution and keep the doto.sty defaults.
        from doxtr_doto.integration import _merged_semantic_palette

        app = make_app(srcdir=doto_srcdir, buildername="latex")
        app.config.doxtr_semantic_palette = dict(PALETTE)

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name.startswith("doxtr_pdf_theme_core"):
                raise ImportError("simulated standalone build")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            assert _merged_semantic_palette(app) is None


class TestCoreLightPaletteSeam:
    """The seam is the single override point for the merged light palette.

    These assertions are core-INDEPENDENT: they fully substitute
    ``_core_light_palette_defaults`` with fakes (or redirect it to ``None``),
    so they prove the single-override-point property without needing
    ``doxtr-pdf-theme-core`` installed. ``test_resolve_follows_overridden_seam``
    still exercises the core's ``resolve_color`` and so is skipped cleanly when
    the core is absent.
    """

    def test_merged_palette_follows_overridden_seam(self, doto_srcdir, make_app, monkeypatch):
        # Overriding ONLY _core_light_palette_defaults must redirect where the
        # merged light palette's base comes from. This proves the seam is the
        # single hook a child theme / future public-core accessor overrides.
        from doxtr_doto.integration import _merged_semantic_palette
        from doxtr_doto.integration import doxtr as doxtr_mod

        def fake_defaults(app):
            # A substituted base palette plus a trivial recursive-merge
            # primitive standing in for the core's deep_update.
            def merge(base, overrides):
                base.update(overrides)
                return base

            return {"primary": "#BA5E00", "danger": "#BADA55"}, merge

        monkeypatch.setattr(doxtr_mod, "_core_light_palette_defaults", fake_defaults)

        app = make_app(srcdir=doto_srcdir, buildername="latex")
        app.config.doxtr_theme_defaults = {}
        app.config.doxtr_semantic_palette = {"primary": "#USER01"}

        merged = _merged_semantic_palette(app)

        # The base now comes from the substituted seam, not the real core.
        assert merged["danger"] == "#BADA55"
        # The orchestration layer still applies the user tier on top.
        assert merged["primary"] == "#USER01"

    def test_identity_merge_override_shape(self, doto_srcdir, make_app, monkeypatch):
        # The docstring advertises a future-public-accessor override shape: a
        # seam returning an already-fully-merged base paired with an identity
        # (no-op) deep_update. Prove that shape works -- the orchestration must
        # layer the (deep-copied) user tier via the supplied merge without
        # mutating the base, so an identity merge leaves the base untouched.
        from doxtr_doto.integration import _merged_semantic_palette
        from doxtr_doto.integration import doxtr as doxtr_mod

        base = {"primary": "#AAA000", "danger": "#BBB000"}

        def fake_defaults(app):
            # Identity merge: the core already merged every tier upstream.
            return dict(base), lambda base_palette, _overrides: base_palette

        monkeypatch.setattr(doxtr_mod, "_core_light_palette_defaults", fake_defaults)

        app = make_app(srcdir=doto_srcdir, buildername="latex")
        app.config.doxtr_theme_defaults = {}
        app.config.doxtr_semantic_palette = {"primary": "#USER01"}

        merged = _merged_semantic_palette(app)

        # The identity merge ignores the overrides, so the already-merged base
        # wins unchanged -- the advertised accessor path resolves cleanly.
        assert merged["primary"] == "#AAA000"
        assert merged["danger"] == "#BBB000"

    def test_seam_returns_isolated_deepcopies(self):
        # The default seam's safety contract: successive calls return
        # independent dicts and mutating a returned base must not alter the
        # core's module-level DOXTR_SEMANTIC_PALETTE constant.
        core_config = pytest.importorskip("doxtr_pdf_theme_core.core_config")

        from doxtr_doto.integration import _core_light_palette_defaults

        first = _core_light_palette_defaults(app=None)
        second = _core_light_palette_defaults(app=None)
        assert first is not None and second is not None
        base_a, _ = first
        base_b, _ = second

        # Distinct objects per call.
        assert base_a is not base_b
        # Mutating a returned base leaves the core constant untouched.
        original_primary = core_config.DOXTR_SEMANTIC_PALETTE["primary"]
        base_a["primary"] = "#000000"
        assert core_config.DOXTR_SEMANTIC_PALETTE["primary"] == original_primary
        assert base_b["primary"] == original_primary

    def test_resolve_follows_overridden_seam(self, doto_srcdir, make_app, monkeypatch):
        # resolve_doto_palette_colors resolves against whatever the seam
        # supplies, so swapping the seam swaps the resolved doto colors too.
        # This exercises the core's resolve_color, so it is skipped cleanly
        # when the core is not importable.
        pytest.importorskip("doxtr_pdf_theme_core")

        from doxtr_doto.integration import doxtr as doxtr_mod
        from doxtr_doto.integration import resolve_doto_palette_colors

        def fake_defaults(app):
            def merge(base, overrides):
                base.update(overrides)
                return base

            # 'primary' drives doto@medium (dd:primary); use a distinctive value.
            return {
                "primary": "#123456",
                "danger": "#654321",
                "warning": "#AAAAAA",
                "secondary": "#BBBBBB",
                "success": "#CCCCCC",
                "info": "#DDDDDD",
                "page": "#FFFFFF",
            }, merge

        monkeypatch.setattr(doxtr_mod, "_core_light_palette_defaults", fake_defaults)

        app = make_app(srcdir=doto_srcdir, buildername="latex")
        app.config.doxtr_theme_defaults = {}
        app.config.doxtr_semantic_palette = {}

        resolved = resolve_doto_palette_colors(app)

        # doto@medium -> dd:primary resolves to the seam-supplied primary.
        assert resolved["doto@medium"] == "#123456"
        # doto@critical -> dd:danger resolves to the seam-supplied danger.
        assert resolved["doto@critical"] == "#654321"

    def test_none_seam_degrades_merged_palette_to_none(self, doto_srcdir, make_app, monkeypatch):
        # When the seam reports the core is unavailable (None), the merged
        # palette degrades to None so callers keep the doto.sty defaults.
        from doxtr_doto.integration import _merged_semantic_palette
        from doxtr_doto.integration import doxtr as doxtr_mod

        monkeypatch.setattr(doxtr_mod, "_core_light_palette_defaults", lambda app: None)

        app = make_app(srcdir=doto_srcdir, buildername="latex")
        app.config.doxtr_semantic_palette = dict(PALETTE)

        assert _merged_semantic_palette(app) is None


class TestApplySemanticColorsNoop:
    """Feature 3: preamble injection is skipped when the core is inactive."""

    def test_noop_without_core(self, doto_srcdir, make_app):
        from doxtr_doto.integration import apply_doxtr_semantic_colors

        app = make_app(srcdir=doto_srcdir, buildername="latex")
        # No core extension registered.
        app.config.doxtr_semantic_palette = dict(PALETTE)
        app.config.latex_elements = {"preamble": "\\usepackage{doto}\n"}

        apply_doxtr_semantic_colors(app)

        assert "% doto semantic palette overrides" not in (app.config.latex_elements["preamble"])

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

        assert "% doto semantic palette overrides" not in (app.config.latex_elements["preamble"])
