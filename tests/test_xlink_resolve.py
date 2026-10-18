"""Tests for render-time ``:xlink:`` resolution (doxtr-xlink).

Covers the resolver parsing, token replacement, graceful no-xlink path, the
HTML build resolution (with ``<a href>`` when a URL is present), the
``doto_resolve_xlinks = False`` opt-out, and a sync round-trip proving the raw
``:xlink:`` token is preserved in the stored RST/JSON (no source mutation).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from doxtr_doto import xlink

# ── unit: token parsing / app-less resolver ─────────────────────────────────


def _write_xlink_file(xdir: Path) -> None:
    xdir.mkdir(parents=True, exist_ok=True)
    (xdir / "people.xlink").write_text(
        "# people\n"
        "yourdirectory-person-alice-bobbington :: Alice Bobbington :: https://example.com/people/abobbington\n"
        "yourdirectory-person-jane-doe :: Jane Doe :: https://example.com/people/jdoe\n"
    )


def test_appless_resolver_parses_file_and_resolves_key(tmp_path):
    """The app-less resolver reads a .xlink file and returns (title, url)."""
    xdir = tmp_path / "xlinks"
    _write_xlink_file(xdir)

    resolve = xlink._appless_resolver(str(xdir))
    assert resolve("yourdirectory-person-alice-bobbington") == (
        "Alice Bobbington",
        "https://example.com/people/abobbington",
    )
    assert resolve("missing-key") == (None, None)


def test_appless_resolver_missing_dir_returns_none(tmp_path):
    """A missing xlink directory degrades to (None, None) for every key."""
    resolve = xlink._appless_resolver(str(tmp_path / "does-not-exist"))
    assert resolve("anything") == (None, None)


def test_contains_and_iter_tokens():
    """Token detection and iteration use the single shared regex."""
    text = "lead :xlink:`a` and :xlink:`Label <b>`"
    assert xlink.contains_xlink_token(text)
    assert not xlink.contains_xlink_token("no tokens here")
    keys = [m.group("key") for m in xlink.iter_xlink_tokens(text)]
    assert keys == ["a", "Label <b>"]


def test_normalize_key_handles_label_form():
    """``Label <key>`` reduces to ``key``; bare keys pass through."""
    assert xlink._normalize_key("Label <the-key>") == "the-key"
    assert xlink._normalize_key("the-key") == "the-key"


def test_normalize_key_rejects_nested_angle_brackets():
    """The tightened regex never captures nested angle brackets into the key.

    ``A <b> <c>`` previously captured ``key="b> <c"`` with the old over-greedy
    pattern (``<(?P<key>.*)>``). The ``[^<>]+`` key group now forbids ``<``/``>``
    inside the key, so the key is a clean bracket-free token (``c``) — the
    corrupt ``b> <c`` capture can no longer happen.
    """
    key = xlink._normalize_key("A <b> <c>")
    assert "<" not in key and ">" not in key
    assert key == "c"
    # The simple single-bracket form still reduces to the inner key.
    assert xlink._normalize_key("Owner <team-x>") == "team-x"


def test_resolve_with_replaces_tokens_and_collects_links(tmp_path):
    """resolve replaces every token with its title and collects (title, url)."""
    xdir = tmp_path / "xlinks"
    _write_xlink_file(xdir)
    resolve = xlink._appless_resolver(str(xdir))

    text = "owner :xlink:`yourdirectory-person-alice-bobbington`, backup :xlink:`yourdirectory-person-jane-doe`"
    result = xlink._resolve_with(text, resolve)
    assert result.display == "owner Alice Bobbington, backup Jane Doe"
    assert result.links == [
        ("Alice Bobbington", "https://example.com/people/abobbington"),
        ("Jane Doe", "https://example.com/people/jdoe"),
    ]


def test_resolve_with_unresolved_key_falls_back_to_bare_key(tmp_path):
    """An unresolved key renders its bare key and contributes no link."""
    resolve = xlink._appless_resolver(str(tmp_path / "empty"))
    result = xlink._resolve_with("x :xlink:`unknown-key`", resolve)
    assert result.display == "x unknown-key"
    assert result.links == []


def test_resolve_with_no_resolver_is_graceful():
    """With no resolver (xlink absent), tokens reduce to the bare key."""
    result = xlink._resolve_with("hi :xlink:`yourdirectory-person-alice-bobbington`", None)
    assert result.display == "hi yourdirectory-person-alice-bobbington"
    assert result.links == []


def test_resolve_without_tokens_returns_text_unchanged():
    """Plain text with no tokens is returned verbatim with no links."""
    result = xlink._resolve_with("plain assignee", None)
    assert result.display == "plain assignee"
    assert result.links == []


def test_resolve_xlink_text_appless(tmp_path):
    """The app-less text helper resolves via a given xlink dir."""
    xdir = tmp_path / "xlinks"
    _write_xlink_file(xdir)
    out = xlink.resolve_xlink_text(":xlink:`yourdirectory-person-jane-doe`", str(xdir))
    assert out == "Jane Doe"


def test_resolve_xlink_text_without_dir_shows_raw_token():
    """With no xlink dir, the text helper leaves the raw token unchanged."""
    out = xlink.resolve_xlink_text(":xlink:`yourdirectory-person-jane-doe`", None)
    assert out == ":xlink:`yourdirectory-person-jane-doe`"


def test_resolve_xlink_tokens_none_app_is_graceful():
    """A None app disables resolution: the raw token is returned unchanged."""
    result = xlink.resolve_xlink_tokens(None, "x :xlink:`k`")
    assert result.display == "x :xlink:`k`"
    assert result.links == []


# ── Sphinx build fixture ─────────────────────────────────────────────────────


@pytest.fixture
def xlink_build(tmp_path):
    """Build a single HTML page with an xlink directory and return the HTML."""

    def _build(rst_content: str, conf_extra: str = "", *, with_xlink_dir: bool = True):
        pytest.importorskip("doxtr_xlink")

        src = tmp_path / "src"
        src.mkdir()
        out = tmp_path / "out"

        if with_xlink_dir:
            _write_xlink_file(src / "xlinks")

        (src / "conf.py").write_text(
            "extensions = ['doxtr_doto', 'doxtr_xlink']\nmaster_doc = 'index'\n" + conf_extra + "\n"
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
        return src, out, html

    return _build


# ── HTML build: resolution ───────────────────────────────────────────────────


def test_html_build_resolves_assignee_with_link(xlink_build):
    """An :assignee: with an xlink token renders the name and an <a href>."""
    _, _, html = xlink_build(
        ".. doto:: Document the decision\n"
        "   :id: DEC-001\n"
        "   :assignee: :xlink:`yourdirectory-person-alice-bobbington`\n"
    )
    assert "Alice Bobbington" in html
    assert 'href="https://example.com/people/abobbington"' in html
    # The raw token must not leak into the rendered HTML.
    assert ":xlink:`yourdirectory-person-alice-bobbington`" not in html


def test_html_build_unresolved_key_shows_bare_key(xlink_build):
    """An unknown xlink key renders its bare key, no crash, no link to it."""
    _, _, html = xlink_build(".. doto:: Task\n   :id: T-1\n   :assignee: :xlink:`nope-not-here`\n")
    assert "nope-not-here" in html
    assert ":xlink:`nope-not-here`" not in html


def test_html_build_resolve_xlinks_false_keeps_raw_token(xlink_build):
    """doto_resolve_xlinks=False renders the raw :xlink: token unchanged."""
    _, _, html = xlink_build(
        ".. doto:: Task\n   :id: T-2\n   :assignee: :xlink:`yourdirectory-person-alice-bobbington`\n",
        conf_extra="doto_resolve_xlinks = False",
    )
    assert ":xlink:`yourdirectory-person-alice-bobbington`" in html
    assert 'href="https://example.com/people/abobbington"' not in html


def test_html_build_without_xlink_extension_keeps_raw_token(tmp_path):
    """Without doxtr_xlink in extensions, the raw token is rendered."""
    src = tmp_path / "src"
    src.mkdir()
    out = tmp_path / "out"
    (src / "conf.py").write_text("extensions = ['doxtr_doto']\nmaster_doc = 'index'\n")
    (src / "index.rst").write_text(
        "Test\n====\n\n"
        ".. doto:: Task\n   :id: T-3\n   :assignee: :xlink:`yourdirectory-person-alice-bobbington`\n"
    )

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
    # Degrade gracefully: the token stays as-is (reduced-key resolution requires
    # xlink to be enabled, which it is not here).
    assert ":xlink:`yourdirectory-person-alice-bobbington`" in html


# ── sync round-trip: no source mutation ──────────────────────────────────────


def test_sync_roundtrip_preserves_raw_token_in_rst_and_json(xlink_build):
    """After a build, the stored RST and JSON keep the raw :xlink: token."""
    src, _, _ = xlink_build(
        ".. doto:: Document the decision\n"
        "   :id: DEC-010\n"
        "   :assignee: :xlink:`yourdirectory-person-alice-bobbington`\n"
    )

    # RST source still carries the raw token (render-time resolution only).
    rst = (src / "index.rst").read_text()
    assert ":xlink:`yourdirectory-person-alice-bobbington`" in rst

    # JSON store persisted the raw token too (not the resolved display name).
    json_path = src / ".doto" / "tasks.json"
    data = json.loads(json_path.read_text())
    task = data["tasks"]["DEC-010"]
    assert task["assignee"] == ":xlink:`yourdirectory-person-alice-bobbington`"


# ── fixtures / helpers for the field-coverage + multi-builder tests ──────────


def _write_xlink_file_extended(xdir):
    """Write a .xlink file with an extra key whose URL contains % and #.

    The ``%``/``#`` entry locks the LaTeX URL escaping (``_latex_href``), which
    only escapes ``\\``, ``%`` and ``#`` (not ordinary text).
    """
    xdir.mkdir(parents=True, exist_ok=True)
    (xdir / "people.xlink").write_text(
        "# people\n"
        "yourdirectory-person-alice-bobbington :: Alice Bobbington :: https://example.com/people/abobbington\n"
        "yourdirectory-person-jane-doe :: Jane Doe :: https://example.com/people/jdoe\n"
        "yourdirectory-person-escape :: Esca Pee :: https://example.com/p?a=50%25#frag\n"
    )


@pytest.fixture
def xlink_build_to(tmp_path):
    """Build one page with a chosen builder; return (src, out, output_text).

    Mirrors ``xlink_build`` but parameterizes the builder (html/latex) and
    writes the extended .xlink file (adds a %/# URL key).
    """

    def _build(rst_content, conf_extra="", *, builder="html"):
        pytest.importorskip("doxtr_xlink")

        src = tmp_path / "src"
        src.mkdir()
        out = tmp_path / "out"
        _write_xlink_file_extended(src / "xlinks")

        (src / "conf.py").write_text(
            "extensions = ['doxtr_doto', 'doxtr_xlink']\nmaster_doc = 'index'\n" + conf_extra + "\n"
        )
        (src / "index.rst").write_text("Test\n====\n\n" + rst_content)

        from sphinx.application import Sphinx

        app = Sphinx(
            srcdir=str(src),
            confdir=str(src),
            outdir=str(out),
            doctreedir=str(tmp_path / ".doctrees"),
            buildername=builder,
        )
        app.build()

        if builder == "latex":
            tex_files = list(out.glob("*.tex"))
            assert tex_files, "no .tex output produced"
            text = tex_files[0].read_text()
        else:
            text = (out / "index.html").read_text()
        return src, out, text

    return _build


# ── E1. LaTeX build resolution + escaping + opt-out ──────────────────────────


def test_latex_build_resolves_assignee_with_sphinxhref(xlink_build_to):
    """A LaTeX build resolves the xlink assignee into \\sphinxhref{url}{name}."""
    _, _, tex = xlink_build_to(
        ".. doto:: Document the decision\n"
        "   :id: DEC-100\n"
        "   :assignee: :xlink:`yourdirectory-person-alice-bobbington`\n",
        builder="latex",
    )
    assert "Alice Bobbington" in tex
    assert "\\sphinxhref{https://example.com/people/abobbington}{" in tex
    assert ":xlink:`yourdirectory-person-alice-bobbington`" not in tex


def test_latex_build_escapes_percent_and_hash_in_url(xlink_build_to):
    """A URL with % and # is escaped to \\% / \\# inside \\sphinxhref."""
    _, _, tex = xlink_build_to(
        ".. doto:: Edge\n   :id: DEC-101\n   :assignee: :xlink:`yourdirectory-person-escape`\n",
        builder="latex",
    )
    assert "Esca Pee" in tex
    assert "\\sphinxhref{https://example.com/p?a=50\\%25\\#frag}{" in tex


def test_latex_build_resolve_xlinks_false_keeps_raw_token(xlink_build_to):
    """doto_resolve_xlinks=False renders the raw token in LaTeX (no href)."""
    _, _, tex = xlink_build_to(
        ".. doto:: Task\n   :id: DEC-102\n   :assignee: :xlink:`yourdirectory-person-alice-bobbington`\n",
        conf_extra="doto_resolve_xlinks = False",
        builder="latex",
    )
    assert "xlink" in tex  # raw token text remains
    assert "\\sphinxhref{https://example.com/people/abobbington}" not in tex


# ── E2. doto-list build: table AND list format resolve the assignee cell ─────


def test_doto_list_table_resolves_assignee_cell(xlink_build_to):
    """A doto-list table cell resolves the assignee name and links it."""
    _, _, html = xlink_build_to(
        ".. doto:: Task\n   :id: LST-1\n   :assignee: :xlink:`yourdirectory-person-jane-doe`\n\n"
        ".. doto-list::\n   :format: table\n   :columns: id, assignee\n"
    )
    assert "Jane Doe" in html
    assert 'href="https://example.com/people/jdoe"' in html
    assert ":xlink:`yourdirectory-person-jane-doe`" not in html


def test_doto_list_simple_resolves_assignee_cell(xlink_build_to):
    """A doto-list list (simple) view resolves the assignee name."""
    _, _, html = xlink_build_to(
        ".. doto:: Task\n   :id: LST-2\n   :assignee: :xlink:`yourdirectory-person-jane-doe`\n\n"
        ".. doto-list::\n   :format: list\n   :columns: id, assignee\n"
    )
    assert "Jane Doe" in html
    assert ":xlink:`yourdirectory-person-jane-doe`" not in html


def test_doto_list_table_latex_resolves_assignee_cell(xlink_build_to):
    """A LaTeX doto-list table cell resolves the assignee via \\sphinxhref."""
    _, _, tex = xlink_build_to(
        ".. doto:: Task\n   :id: LST-3\n   :assignee: :xlink:`yourdirectory-person-jane-doe`\n\n"
        ".. doto-list::\n   :format: table\n   :columns: id, assignee\n",
        builder="latex",
    )
    assert "Jane Doe" in tex
    assert "\\sphinxhref{https://example.com/people/jdoe}{" in tex


# ── E3. cards view resolves the assignee (A2) ────────────────────────────────


def test_doto_list_cards_resolves_assignee(xlink_build_to):
    """The :format: cards view resolves the assignee name and links it (A2)."""
    _, _, html = xlink_build_to(
        ".. doto:: Task\n   :id: CRD-1\n   :assignee: :xlink:`yourdirectory-person-alice-bobbington`\n\n"
        ".. doto-list::\n   :format: cards\n"
    )
    assert "Alice Bobbington" in html
    assert 'href="https://example.com/people/abobbington"' in html
    assert ":xlink:`yourdirectory-person-alice-bobbington`" not in html


# ── E4. explicit Label <key> form resolves (label must not leak) ─────────────


def test_doto_build_label_key_form_resolves(xlink_build_to):
    """A ``Label <key>`` assignee resolves to the title; the label is dropped."""
    _, _, html = xlink_build_to(
        ".. doto:: Task\n   :id: LBL-1\n   :assignee: :xlink:`Owner <yourdirectory-person-jane-doe>`\n"
    )
    assert "Jane Doe" in html
    # The label text and the raw key must not leak into the output.
    assert "Owner <yourdirectory-person-jane-doe>" not in html
    assert ":xlink:" not in html


# ── E5. multiple tokens in one field: both render; first URL wins ────────────


def test_doto_build_multiple_tokens_first_url_wins(xlink_build_to):
    """Two tokens in :assignee: both render; the href is the first token's URL."""
    _, _, html = xlink_build_to(
        ".. doto:: Task\n"
        "   :id: MULTI-1\n"
        "   :assignee: :xlink:`yourdirectory-person-alice-bobbington` / :xlink:`yourdirectory-person-jane-doe`\n"
    )
    assert "Alice Bobbington" in html
    assert "Jane Doe" in html
    # First-wins: the assignee link href is Alice's URL, not Jane's.
    assert 'href="https://example.com/people/abobbington"' in html


# ── E6. Jinja-less fallback renderer honors/omits the href context var ───────


def test_fallback_render_doto_honors_assignee_href():
    """The Python fallback single-task renderer emits an <a> when href is set."""
    from doxtr_doto.template_loader import _fallback_render_doto

    html = _fallback_render_doto(
        {
            "task_id": "F-1",
            "title": "T",
            "assignee": "Alice Bobbington",
            "assignee_href": "https://example.com/people/abobbington",
        }
    )
    assert 'class="doto-assignee-link" href="https://example.com/people/abobbington"' in html
    assert "Alice Bobbington" in html


def test_fallback_render_doto_omits_href_when_absent():
    """With no href, the fallback renderer emits plain assignee text (no <a>)."""
    from doxtr_doto.template_loader import _fallback_render_doto

    html = _fallback_render_doto(
        {"task_id": "F-2", "title": "T", "assignee": "Alice Bobbington", "assignee_href": ""}
    )
    assert "doto-assignee-link" not in html
    assert "Alice Bobbington" in html


def test_fallback_render_cards_honors_card_data_href():
    """The fallback cards renderer links the assignee from card_data href."""
    from types import SimpleNamespace

    from doxtr_doto.template_loader import _fallback_render_cards

    task = SimpleNamespace(
        id="C-1",
        title="T",
        priority="medium",
        status="open",
        assignee=":xlink:`yourdirectory-person-alice-bobbington`",
        due=None,
        tags=[],
        is_overdue=lambda: False,
    )
    html = _fallback_render_cards(
        {
            "tasks": [task],
            "card_data": {
                "C-1": {
                    "assignee": "Alice Bobbington",
                    "assignee_href": "https://example.com/people/abobbington",
                }
            },
        }
    )
    assert 'href="https://example.com/people/abobbington"' in html
    assert "Alice Bobbington" in html
    # The raw token must not leak through the fallback path.
    assert ":xlink:" not in html


# ── E7. field coverage: assignee resolves; title (non-XLINK field) does not ──


def test_xlink_fields_contains_only_assignee():
    """XLINK_FIELDS reflects the A1 decision: only the assignee resolves."""
    from doxtr_doto.fields import XLINK_FIELDS

    assert XLINK_FIELDS == frozenset({"assignee"})


def test_title_field_is_not_resolved_renders_raw_token(xlink_build_to):
    """:title: is NOT in XLINK_FIELDS, so its :xlink: token renders raw."""
    _, _, html = xlink_build_to(
        ".. doto:: Owner :xlink:`yourdirectory-person-alice-bobbington`\n   :id: TTL-1\n"
    )
    # Title is not resolved: the raw token survives, the display name does not
    # appear from title resolution.
    assert ":xlink:`yourdirectory-person-alice-bobbington`" in html


def test_title_column_in_doto_list_not_resolved(xlink_build_to):
    """A :title: list cell renders the raw token (title is not an XLINK field)."""
    _, _, html = xlink_build_to(
        ".. doto:: Owner :xlink:`yourdirectory-person-jane-doe`\n   :id: TTL-2\n\n"
        ".. doto-list::\n   :format: table\n   :columns: id, title\n"
    )
    assert ":xlink:`yourdirectory-person-jane-doe`" in html
