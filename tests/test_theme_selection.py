"""Tests for HTML and LaTeX theme selection."""
from __future__ import annotations

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
            "extensions = ['doxtr_doto']\n"
            "master_doc = 'index'\n"
            + conf_extra + "\n"
        )
        (src / "index.rst").write_text(
            "Test\n====\n\n" + rst_content
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
        return out, html

    return _build


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


def test_default_theme_is_linked_in_html(sphinx_build):
    """Default theme CSS is linked in HTML output."""
    _, html = sphinx_build(".. doto:: X\n   :id: T-003\n")
    assert 'doto.css' in html


def test_minimal_theme_is_linked_in_html(sphinx_build):
    """Minimal theme CSS is linked in HTML output."""
    _, html = sphinx_build(
        ".. doto:: X\n   :id: T-004\n",
        conf_extra='doto_html_theme = "minimal"',
    )
    assert 'doto-minimal.css' in html


def test_unknown_theme_falls_back_to_default(sphinx_build, tmp_path):
    """An unknown doto_html_theme logs a warning but falls back to default."""
    import warnings
    
    with warnings.catch_warnings(record=True):
        out, html = sphinx_build(
            ".. doto:: X\n   :id: T-005\n",
            conf_extra='doto_html_theme = "nonexistent-theme"',
        )
    
    # Should fall back to default.css
    assert (out / "_static" / "doto.css").exists()
    assert 'doto.css' in html
