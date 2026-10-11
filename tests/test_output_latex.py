"""Tests for LaTeX output of doto directives."""

from __future__ import annotations

import pytest

import doxtr_doto.charts as charts


@pytest.fixture
def latex_build(tmp_path):
    """Helper that runs a minimal Sphinx LaTeX build."""

    def _build(rst_content: str, conf_extra: str = "") -> str:
        src = tmp_path / "src"
        src.mkdir(exist_ok=True)
        out = tmp_path / "out"

        (src / "conf.py").write_text(
            "extensions = ['doxtr_doto']\n"
            "master_doc = 'index'\n"
            "latex_documents = [('index', 'test.tex', 'Test', 'Author', 'manual')]\n"
            + conf_extra
            + "\n"
        )
        (src / "index.rst").write_text("Test\n====\n\n" + rst_content)

        from sphinx.application import Sphinx

        app = Sphinx(
            srcdir=str(src),
            confdir=str(src),
            outdir=str(out),
            doctreedir=str(tmp_path / ".doctrees"),
            buildername="latex",
        )
        app.build()

        return (out / "test.tex").read_text()

    return _build


def test_doto_node_latex_opens_dotobox(latex_build):
    """doto directive emits a priority-specific box environment in LaTeX."""
    tex = latex_build(".. doto:: LaTeX Task\n   :id: TASK-L01\n   :priority: high\n")
    # priority=high selects the dotoboxhigh variant (see doto.sty).
    assert r"\begin{dotoboxhigh}" in tex
    assert r"\end{dotoboxhigh}" in tex
    assert "TASK-L01" in tex


def test_doto_node_latex_selects_priority_box_env(latex_build):
    """Each priority selects its matching dotobox<priority> environment."""
    cases = {
        "low": "dotoboxlow",
        "medium": "dotoboxmedium",
        "high": "dotoboxhigh",
        "critical": "dotoboxcritical",
    }
    for priority, env in cases.items():
        tex = latex_build(
            f".. doto:: Task {priority}\n   :id: TASK-P-{priority}\n   :priority: {priority}\n"
        )
        assert (rf"\begin{{{env}}}") in tex
        assert (rf"\end{{{env}}}") in tex


def test_doto_node_latex_unknown_priority_falls_back_to_dotobox(latex_build):
    """A priority with no dedicated box env falls back to the plain dotobox.

    A custom priority (allowed via doto_priorities) has no matching
    dotobox<priority> variant, so the visitor must fall back to ``dotobox``.
    """
    tex = latex_build(
        ".. doto:: Custom priority\n   :id: TASK-PX\n   :priority: someday\n",
        conf_extra="doto_priorities = ['low', 'medium', 'high', 'critical', 'someday']",
    )
    assert r"\begin{dotobox}" in tex
    assert r"\end{dotobox}" in tex
    # Must not fabricate a nonexistent priority variant.
    assert r"\begin{dotoboxsomeday}" not in tex


def test_doto_node_latex_box_title_is_latex_escaped(latex_build):
    """The box title uses _latex_escape (not encode_uri) so specials are escaped."""
    tex = latex_build(".. doto:: Fix 50% of the A&B bug\n   :id: TASK-ESC\n")
    # _latex_escape turns % -> \\% and & -> \\& in the box title argument.
    assert r"\%" in tex
    assert r"\&" in tex
    assert "Fix 50" in tex


def test_doto_node_latex_emits_cross_reference_label(latex_build):
    """Task box emits a \\label anchor so :doto: cross-refs resolve.

    The anchor must be the detokenized ``<docname>:<task_id>`` label the domain
    resolver targets via make_refnode; otherwise LaTeX reports the hyper
    reference as undefined.
    """
    tex = latex_build(".. doto:: Linkable Task\n   :id: TASK-L02\n")
    # \dotolabel emits a \phantomsection\label with the detokenized anchor.
    assert r"\dotolabel{\detokenize{index:TASK-L02}}" in tex


def test_doto_ref_latex_target_label_matches_reference(latex_build):
    """The emitted task label matches the \\hyperref target for the ref."""
    tex = latex_build(
        ".. doto:: Target Task\n   :id: TASK-L03\n\nSee :doto:`TASK-L03` for details.\n"
    )
    # The box emits the anchor label ...
    assert r"\dotolabel{\detokenize{index:TASK-L03}}" in tex
    # ... and the reference targets the same detokenized label.
    assert r"\hyperref[\detokenize{index:TASK-L03}]" in tex


def test_doto_node_latex_uses_stacked_icon_macros(latex_build):
    """Metadata fields render via the stacked-icon macros from doto.sty."""
    tex = latex_build(
        ".. doto:: Icon Task\n"
        "   :id: TASK-L04\n"
        "   :assignee: alice\n"
        "   :due: 2099-01-01\n"
        "   :tags: security, backend\n"
        "   :created: 2099-01-01\n"
        "   :updated: 2099-02-01\n"
    )
    assert r"\dotometaid{" in tex
    assert r"\dotometapriority{" in tex
    assert r"\dotometastatus{" in tex
    assert r"\dotometaassignee{" in tex
    assert r"\dotometadue{" in tex
    assert r"\dotometatags{" in tex
    assert r"\dotometacreated{" in tex
    assert r"\dotometaupdated{" in tex


def test_doto_node_latex_priority_colored_via_macro(latex_build):
    """Priority value uses the severity-colored macro rather than inline color."""
    tex = latex_build(".. doto:: Critical Task\n   :id: TASK-L05\n   :priority: critical\n")
    assert r"\dotopriorityvalue{critical}{critical}" in tex


def test_doto_list_latex_produces_longtable(latex_build):
    """doto-list with table format emits a longtable."""
    tex = latex_build(
        ".. doto:: T\n   :id: TASK-L10\n\n"
        ".. doto-list::\n"
        "   :format: table\n"
        "   :columns: id, title\n"
    )
    assert r"\begin{longtable}" in tex
    assert "TASK-L10" in tex


def test_doto_list_latex_description_list(latex_build):
    """doto-list with list format emits a description environment."""
    tex = latex_build(".. doto:: Desc task\n   :id: TASK-L11\n\n.. doto-list::\n")
    assert r"\begin{description}" in tex


def test_doto_summary_latex_shows_total(latex_build):
    """doto-summary emits total task count in LaTeX."""
    tex = latex_build(
        ".. doto:: A\n   :id: TASK-L20\n\n.. doto:: B\n   :id: TASK-L21\n\n.. doto-summary::\n"
    )
    assert "Total tasks:" in tex
    assert "2" in tex


def test_doto_summary_latex_renders_native_chart_without_kaleido(latex_build, monkeypatch):
    r"""doto-summary :show-chart: emits a native-LaTeX visual + textual breakdown.

    The PDF summary must always render a real chart (F1), not just text, even
    when kaleido/Chrome is unavailable (the common CI case). The native-LaTeX
    renderer emits a themeable ``\begin{dotochart}{...}`` block; for the default
    bar chart it contains ``\dotochartbar`` rows drawn with tikz in doto.sty.
    The textual breakdown (``Total tasks:``) must still be present alongside it.

    We deterministically simulate the "kaleido/Chrome unavailable" case by
    forcing ``render_plotly_chart_image`` to return ``None`` (its documented
    behavior when static export is impossible). Otherwise this test is
    environment-dependent: on runners that *do* have plotly+kaleido+Chrome the
    plotly PNG ``\includegraphics`` path is taken and the native fallback is
    never exercised.
    """
    # Patch the attribute on the ``charts`` module (not ``nodes``): the LaTeX
    # summary visitor re-imports ``render_plotly_chart_image`` from
    # doxtr_doto.charts at call time, so the patched module attribute is what
    # it resolves. If that import is ever hoisted to module top-level in
    # nodes.py, patch ``doxtr_doto.nodes.render_plotly_chart_image`` instead.
    # The stub mirrors the real signature so an argument-contract drift surfaces
    # here instead of silently passing against a permissive ``*a, **k`` stub.
    monkeypatch.setattr(
        charts,
        "render_plotly_chart_image",
        lambda tasks, group_by, chart_type, output_dir, image_format="png": None,
    )
    tex = latex_build(
        ".. doto:: A\n   :id: TASK-L22\n   :status: open\n\n"
        ".. doto:: B\n   :id: TASK-L23\n   :status: done\n\n"
        ".. doto-summary::\n"
        "   :group-by: status\n"
        "   :show-chart: true\n",
        conf_extra="doto_chart_engine = 'plotly'",
    )
    # A native-LaTeX chart environment (visual) is emitted even though plotly
    # was requested but kaleido/Chrome is unavailable -> fall through to native.
    assert r"\begin{dotochart}" in tex
    assert r"\end{dotochart}" in tex
    # The default chart type is a bar chart, drawn via \dotochartbar rows.
    assert r"\dotochartbar" in tex
    # And the textual breakdown remains as an accompanying summary.
    assert "Total tasks:" in tex


def test_doto_summary_latex_pie_chart_native(latex_build):
    r"""A :chart-type: pie summary emits the native pie environment."""
    tex = latex_build(
        ".. doto:: A\n   :id: TASK-L24\n   :status: open\n\n"
        ".. doto:: B\n   :id: TASK-L25\n   :status: done\n\n"
        ".. doto-summary::\n"
        "   :group-by: status\n"
        "   :show-chart: true\n"
        "   :chart-type: pie\n",
    )
    assert r"\begin{dotochart}" in tex
    assert r"\begin{dotochartpie}" in tex
    assert "Total tasks:" in tex


def test_doto_summary_latex_plotly_png_emits_includegraphics(latex_build, monkeypatch):
    r"""When plotly export succeeds, the visitor emits ``\includegraphics``.

    This is the success-branch counterpart to
    ``test_doto_summary_latex_renders_native_chart_without_kaleido``: with the
    plotly engine selected and ``render_plotly_chart_image`` returning a
    filename, the LaTeX summary visitor must ``\includegraphics`` the PNG and
    return early -- it must NOT fall through to the native ``dotochart`` block.
    Forcing the return value keeps the test deterministic regardless of whether
    the runner actually has plotly/kaleido/Chrome. See the note in the native
    test above for why the patch targets ``charts.<name>``.
    """
    monkeypatch.setattr(
        charts,
        "render_plotly_chart_image",
        lambda tasks, group_by, chart_type, output_dir, image_format="png": (
            "doto-chart-deadbeef.png"
        ),
    )
    tex = latex_build(
        ".. doto:: A\n   :id: TASK-L26\n   :status: open\n\n"
        ".. doto:: B\n   :id: TASK-L27\n   :status: done\n\n"
        ".. doto-summary::\n"
        "   :group-by: status\n"
        "   :show-chart: true\n",
        conf_extra="doto_chart_engine = 'plotly'",
    )
    # The exported PNG is included via a forward-slash relative path.
    assert r"\includegraphics" in tex
    assert "_images/doto-chart-deadbeef.png" in tex
    # The success path returns early, so the native chart is NOT also emitted.
    assert r"\begin{dotochart}" not in tex
    # The textual breakdown still accompanies the figure.
    assert "Total tasks:" in tex


@pytest.mark.parametrize("chart_type", sorted(charts.VALID_CHART_TYPES))
def test_doto_summary_latex_native_chart_all_types(latex_build, monkeypatch, chart_type):
    r"""Every valid chart type emits a native ``dotochart`` block in LaTeX.

    Parametrized over ``charts.VALID_CHART_TYPES`` so that adding a new chart
    type without a native-LaTeX renderer is caught here (the dispatch defaults
    to the bar renderer on an unknown type, so a registry omission would
    otherwise be invisible). ``render_plotly_chart_image`` is forced to ``None``
    to keep the native path deterministic on all runners.
    """
    monkeypatch.setattr(
        charts,
        "render_plotly_chart_image",
        lambda tasks, group_by, chart_type, output_dir, image_format="png": None,
    )
    tex = latex_build(
        ".. doto:: A\n   :id: TASK-L28\n   :status: open\n\n"
        ".. doto:: B\n   :id: TASK-L29\n   :status: done\n\n"
        ".. doto-summary::\n"
        "   :group-by: status\n"
        "   :show-chart: true\n"
        f"   :chart-type: {chart_type}\n",
        conf_extra="doto_chart_engine = 'plotly'",
    )
    assert r"\begin{dotochart}" in tex
    assert r"\end{dotochart}" in tex
    assert "Total tasks:" in tex


def test_doto_list_latex_empty_message(latex_build):
    """Empty doto-list emits the fallback textit message."""
    tex = latex_build(
        ".. doto:: Open\n   :id: TASK-L30\n   :status: open\n\n.. doto-list::\n   :status: done\n"
    )
    assert r"\textit{No tasks" in tex


def test_doto_summary_latex_empty_message(latex_build):
    """Empty doto-summary emits the fallback textit message."""
    tex = latex_build(".. doto-summary::\n   :status: done\n")
    assert r"\textit{No tasks found.}" in tex


def test_doto_list_latex_escapes_special_chars(latex_build):
    """LaTeX special characters in task data are escaped."""
    tex = latex_build(".. doto:: Task with $special & chars\n   :id: TASK-L40\n\n.. doto-list::\n")
    # The & and $ should be escaped
    assert r"\$" in tex or "special" in tex
    assert r"\&" in tex or "chars" in tex


def test_doto_list_latex_ids_are_clickable(latex_build):
    """Task ids in a LaTeX list link to the task box via \\dotolistlink."""
    tex = latex_build(
        ".. doto:: Linkable\n   :id: TASK-L50\n\n"
        ".. doto-list::\n"
        "   :format: table\n"
        "   :columns: id, title\n"
    )
    assert r"\dotolistlink" in tex
    # The link target matches the label emitted by the task box.
    assert r"\detokenize{index:TASK-L50}" in tex


def test_doto_list_latex_text_mode_no_icons(latex_build):
    """icon-mode text renders plain text (no FA macros) in the list."""
    tex = latex_build(
        ".. doto:: Plain\n   :id: TASK-L51\n   :status: open\n\n"
        ".. doto-list::\n"
        "   :format: table\n"
        "   :columns: id, status\n"
        "   :icon-mode: text\n"
    )
    # In text mode, the status cell should not use the FA status macro.
    assert r"\faCircleDot" not in tex
    assert r"\faRegularCircle" not in tex


def test_doto_list_latex_icon_mode_emits_fa_macros(latex_build):
    """icon-mode icon-text emits FA macros for iconizable fields."""
    tex = latex_build(
        ".. doto:: Iconic\n   :id: TASK-L52\n   :status: open\n"
        "   :assignee: alice\n\n"
        ".. doto-list::\n"
        "   :format: table\n"
        "   :columns: id, status, assignee\n"
        "   :icon-mode: icon-text\n"
    )
    # Assignee gets the user icon; status open maps to the regular circle icon.
    assert r"\faUser" in tex


def test_doto_list_latex_config_icon_mode(latex_build):
    """The doto_list_icon_mode config drives list rendering when no override."""
    tex = latex_build(
        ".. doto:: ConfMode\n   :id: TASK-L53\n   :assignee: bob\n\n"
        ".. doto-list::\n"
        "   :format: table\n"
        "   :columns: id, assignee\n",
        conf_extra="doto_list_icon_mode = 'text'",
    )
    assert r"\faUser" not in tex


# ── Feature D: PDF layouts (default / compact) ──────────────────────────────


def test_doto_node_latex_default_layout_unchanged(latex_build):
    """The default layout still emits the roomy dotobox + \\dotometa* macros.

    Guards backward compatibility: with no doto_latex_layout set (default), the
    task box must open ``dotobox<priority>`` and render the stacked-icon
    metadata macros exactly as before Feature D.
    """
    tex = latex_build(
        ".. doto:: Default Layout\n"
        "   :id: TASK-D01\n"
        "   :priority: high\n"
        "   :assignee: alice\n"
        "   :due: 2099-01-01\n"
    )
    assert r"\begin{dotoboxhigh}" in tex
    assert r"\dotometaid{" in tex
    assert r"\dotometaassignee{" in tex
    assert r"\dotometadue{" in tex
    # Compact macros/box must NOT appear in the default layout.
    assert r"\begin{dotoboxcompact" not in tex
    assert r"\dotocompactheader" not in tex


def test_doto_node_latex_compact_layout_emits_compact_macros(latex_build):
    """doto_latex_layout='compact' emits the compact box + \\dotocompact* macros."""
    tex = latex_build(
        ".. doto:: Compact Layout\n"
        "   :id: TASK-D02\n"
        "   :priority: high\n"
        "   :assignee: alice\n"
        "   :due: 2099-01-01\n",
        conf_extra="doto_latex_layout = 'compact'",
    )
    # Compact priority box variant is opened/closed.
    assert r"\begin{dotoboxcompacthigh}" in tex
    assert r"\end{dotoboxcompacthigh}" in tex
    # Single-line header + inline field pairs via the compact macros.
    assert r"\dotocompactheader" in tex
    assert r"\dotocompactfield" in tex
    assert r"\dotocompactrule" in tex
    # The roomy default stacked-icon macros must NOT appear in compact mode.
    assert r"\dotometaid{" not in tex
    assert r"\dotometaassignee{" not in tex


def test_doto_node_latex_compact_keeps_detail_parity(latex_build):
    """The compact layout lays out the SAME fields as default (no detail lost).

    Every field supplied on the directive must still be present in the compact
    output: id/priority/status in the header, assignee/due/created/updated/tags
    as inline field pairs.
    """
    tex = latex_build(
        ".. doto:: Parity\n"
        "   :id: TASK-D03\n"
        "   :priority: critical\n"
        "   :status: in-progress\n"
        "   :assignee: alice\n"
        "   :due: 2099-01-01\n"
        "   :created: 2099-01-01\n"
        "   :updated: 2099-02-01\n"
        "   :tags: security, backend\n",
        conf_extra="doto_latex_layout = 'compact'",
    )
    # Header carries id + priority (severity-colored) + status.
    assert "TASK-D03" in tex
    assert r"\dotopriorityvalue{critical}{critical}" in tex
    assert "in-progress" in tex
    # Inline field pairs carry assignee/due/created/updated/tags values.
    assert "alice" in tex
    assert "2099-01-01" in tex
    assert "2099-02-01" in tex
    assert "security" in tex and "backend" in tex


def test_doto_node_latex_compact_icons_inline(latex_build):
    """Compact layout groups icons inline via \\dotocompactfield{icon}{value}.

    The icon layout differs from the default (stacked per-row): the assignee
    FA icon is passed as the first argument of an inline \\dotocompactfield.
    """
    tex = latex_build(
        ".. doto:: Icons\n   :id: TASK-D04\n   :assignee: alice\n",
        conf_extra="doto_latex_layout = 'compact'",
    )
    # The assignee icon+value is an inline field pair, not a stacked meta row.
    assert r"\dotocompactfield{\faUser}" in tex
    assert r"\dotometaassignee" not in tex


def test_doto_node_latex_compact_per_directive_override(latex_build):
    """A per-directive :latex-layout: compact overrides the default config."""
    tex = latex_build(".. doto:: Override\n   :id: TASK-D05\n   :latex-layout: compact\n")
    assert r"\begin{dotoboxcompact" in tex
    assert r"\dotocompactheader" in tex


def test_doto_node_latex_per_directive_override_default_wins(latex_build):
    """:latex-layout: default forces the default box even when config=compact."""
    tex = latex_build(
        ".. doto:: ForceDefault\n   :id: TASK-D06\n   :priority: low\n   :latex-layout: default\n",
        conf_extra="doto_latex_layout = 'compact'",
    )
    assert r"\begin{dotoboxlow}" in tex
    assert r"\dotometaid{" in tex
    assert r"\begin{dotoboxcompact" not in tex


def test_doto_node_latex_invalid_layout_falls_back_to_default(latex_build):
    """An invalid doto_latex_layout defaults to the roomy layout (no crash).

    A bad config value must never emit an undefined box env; it falls back to
    ``default`` so the build is well-formed.
    """
    tex = latex_build(
        ".. doto:: BadLayout\n   :id: TASK-D07\n   :priority: medium\n",
        conf_extra="doto_latex_layout = 'nonexistent'",
    )
    assert r"\begin{dotoboxmedium}" in tex
    assert r"\dotometaid{" in tex
    assert r"\begin{dotoboxcompact" not in tex


def test_doto_node_latex_invalid_per_directive_layout_ignored(latex_build):
    """An invalid :latex-layout: value is ignored (config/default applies)."""
    tex = latex_build(
        ".. doto:: BadDirectiveLayout\n"
        "   :id: TASK-D08\n"
        "   :priority: medium\n"
        "   :latex-layout: bogus\n"
    )
    # Falls through to the default layout; no undefined compact box emitted.
    assert r"\begin{dotoboxmedium}" in tex
    assert r"\begin{dotoboxcompact" not in tex


def test_doto_node_latex_compact_unknown_priority_falls_back(latex_build):
    """A custom priority with no compact variant uses the plain dotoboxcompact."""
    tex = latex_build(
        ".. doto:: CustomPrio\n   :id: TASK-D09\n   :priority: someday\n",
        conf_extra=(
            "doto_latex_layout = 'compact'\n"
            "doto_priorities = ['low', 'medium', 'high', 'critical', 'someday']"
        ),
    )
    assert r"\begin{dotoboxcompact}" in tex
    assert r"\end{dotoboxcompact}" in tex
    assert r"\begin{dotoboxcompactsomeday}" not in tex


def test_doto_node_latex_compact_icon_mode_list_still_works(latex_build):
    """The compact box layout and the task-list icon-mode are independent.

    Selecting the compact box layout must not disturb the separate
    ``doto_list_icon_mode`` task-list rendering (Feature 5), which keeps
    emitting FA macros for iconizable list cells.
    """
    tex = latex_build(
        ".. doto:: Both\n   :id: TASK-D10\n   :assignee: alice\n\n"
        ".. doto-list::\n"
        "   :format: table\n"
        "   :columns: id, assignee\n"
        "   :icon-mode: icon-text\n",
        conf_extra="doto_latex_layout = 'compact'",
    )
    # Compact box for the task.
    assert r"\begin{dotoboxcompact" in tex
    # List still emits the user icon in icon-text mode.
    assert r"\faUser" in tex


# --- Feature D: layout registries (box-env + body emitter) ----------------


def test_latex_layout_registry_keys_match_valid_layouts():
    """VALID_LATEX_LAYOUTS must equal the layout registry keys.

    Guards against "valid" drifting from "renderable": a layout accepted by
    config validation must have both a box-env entry and a body emitter (so a
    bad name can never pass validation yet lack a renderer). This test-guard
    is used instead of deriving VALID_LATEX_LAYOUTS from the registry to avoid
    a constants.py -> nodes.py import cycle.
    """
    from doxtr_doto import nodes
    from doxtr_doto.constants import VALID_LATEX_LAYOUTS

    assert set(VALID_LATEX_LAYOUTS) == set(nodes._LAYOUT_BOX_ENVS)
    assert set(VALID_LATEX_LAYOUTS) == set(nodes._LAYOUT_BODY_EMITTERS)


def test_resolve_box_env_unknown_layout_falls_back_to_default():
    """A future/unknown layout name resolves through the default box-env map."""
    from doxtr_doto import nodes

    # Unknown layout falls back to the default layout's box env for the
    # priority (not the compact variant, not an undefined env).
    assert nodes._resolve_box_env("high", "futuristic") == "dotoboxhigh"
    assert nodes._resolve_box_env("unknownprio", "futuristic") == "dotobox"


def test_layout_body_emitter_unknown_layout_falls_back_to_default():
    """An unknown layout dispatches to the default body emitter."""
    from doxtr_doto import nodes

    emitter = nodes._LAYOUT_BODY_EMITTERS.get("futuristic", nodes._LAYOUT_BODY_EMITTERS["default"])
    assert emitter is nodes._emit_doto_box_body_default


def test_doto_node_latex_unknown_future_layout_renders_default(latex_build):
    """A valid-but-unimplemented-looking layout name falls back to default.

    The config validator only accepts VALID_LATEX_LAYOUTS, so an unknown name
    is coerced to ``default`` before rendering; this asserts the end-to-end
    build emits the roomy default box (never an undefined compact env).
    """
    tex = latex_build(
        ".. doto:: FutureLayout\n   :id: TASK-D11\n   :priority: high\n",
        conf_extra="doto_latex_layout = 'future-style'",
    )
    assert r"\begin{dotoboxhigh}" in tex
    assert r"\dotometaid{" in tex
    assert r"\begin{dotoboxcompact" not in tex
