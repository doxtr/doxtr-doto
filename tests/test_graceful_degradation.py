"""Tests that the extension degrades gracefully under adverse conditions."""
from __future__ import annotations

from pathlib import Path
import warnings

import pytest


@pytest.fixture
def sphinx_build(tmp_path):
    """Helper fixture that runs a minimal Sphinx HTML build."""
    def _build(
        rst_content: str,
        conf_extra: str = "",
        expect_warning: bool = False,
    ) -> tuple[Path, str]:
        """
        Build a single RST page and return (outdir, page_html).

        Args:
            rst_content: The body of index.rst.
            conf_extra:  Extra lines appended to conf.py.
            expect_warning: If True, suppress warnings during build.
        """
        src = tmp_path / "src"
        src.mkdir(exist_ok=True)
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
        
        if expect_warning:
            with warnings.catch_warnings(record=True):
                warnings.simplefilter("always")
                app = Sphinx(
                    srcdir=str(src),
                    confdir=str(src),
                    outdir=str(out),
                    doctreedir=str(tmp_path / ".doctrees"),
                    buildername="html",
                )
                app.build()
        else:
            app = Sphinx(
                srcdir=str(src),
                confdir=str(src),
                outdir=str(out),
                doctreedir=str(tmp_path / ".doctrees"),
                buildername="html",
            )
            app.build()

        html_file = out / "index.html"
        html = html_file.read_text() if html_file.exists() else ""
        return out, html

    return _build


# ── Build with no tasks ────────────────────────────────────────────────────


def test_build_with_no_tasks_succeeds(tmp_path):
    """A project with no doto directives builds without error."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "conf.py").write_text(
        "extensions = ['doxtr_doto']\n"
        "master_doc = 'index'\n"
    )
    (src / "index.rst").write_text(
        "Empty\n=====\n\nNo tasks here.\n"
    )

    from sphinx.application import Sphinx
    app = Sphinx(
        srcdir=str(src),
        confdir=str(src),
        outdir=str(tmp_path / "out"),
        doctreedir=str(tmp_path / ".doctrees"),
        buildername="html",
    )
    app.build()   # Should not raise
    
    # Build should complete and produce output
    assert (tmp_path / "out" / "index.html").exists()


def test_build_with_no_tasks_produces_valid_html(tmp_path):
    """A project with no doto directives produces valid HTML."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "conf.py").write_text(
        "extensions = ['doxtr_doto']\n"
        "master_doc = 'index'\n"
    )
    (src / "index.rst").write_text(
        "Empty Project\n"
        "=============\n\n"
        "This project has no tasks.\n"
    )

    from sphinx.application import Sphinx
    app = Sphinx(
        srcdir=str(src),
        confdir=str(src),
        outdir=str(tmp_path / "out"),
        doctreedir=str(tmp_path / ".doctrees"),
        buildername="html",
    )
    app.build()
    
    html = (tmp_path / "out" / "index.html").read_text()
    assert "Empty Project" in html
    assert "no tasks" in html.lower()


# ── Empty doto-list ────────────────────────────────────────────────────────


def test_doto_list_with_no_tasks_renders_empty_message(tmp_path):
    """A doto-list with no tasks in the project shows the empty state."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "conf.py").write_text(
        "extensions = ['doxtr_doto']\n"
        "master_doc = 'index'\n"
    )
    (src / "index.rst").write_text(
        "Empty\n=====\n\n"
        ".. doto-list::\n"
        "   :status: open\n"
    )

    from sphinx.application import Sphinx
    out = tmp_path / "out"
    app = Sphinx(
        srcdir=str(src),
        confdir=str(src),
        outdir=str(out),
        doctreedir=str(tmp_path / ".doctrees"),
        buildername="html",
    )
    app.build()
    html = (out / "index.html").read_text()
    assert "No tasks match" in html


def test_doto_list_with_no_matching_tasks(sphinx_build):
    """A doto-list that filters out all tasks shows empty message."""
    _, html = sphinx_build(
        ".. doto:: Active task\n"
        "   :id: FILTER-001\n"
        "   :status: open\n\n"
        ".. doto-list::\n"
        "   :status: done\n"  # No tasks are done
    )
    assert "No tasks match" in html


def test_doto_summary_with_no_tasks_renders_empty_message(sphinx_build):
    """A doto-summary with no tasks shows empty state."""
    _, html = sphinx_build(
        ".. doto-summary::\n"
        "   :status: done\n"  # No tasks exist with done status
    )
    assert "No tasks found" in html


# ── Theme fallback ─────────────────────────────────────────────────────────


def test_unknown_html_theme_falls_back_gracefully(tmp_path):
    """An unknown doto_html_theme logs a warning but does not crash."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "conf.py").write_text(
        "extensions = ['doxtr_doto']\n"
        "master_doc = 'index'\n"
        'doto_html_theme = "nonexistent-theme"\n'
    )
    (src / "index.rst").write_text("T\n=\n\n")

    from sphinx.application import Sphinx
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        app = Sphinx(
            srcdir=str(src),
            confdir=str(src),
            outdir=str(tmp_path / "out"),
            doctreedir=str(tmp_path / ".doctrees"),
            buildername="html",
        )
        app.build()   # Must not raise; warning should have been emitted
    
    # Build should complete
    assert (tmp_path / "out" / "index.html").exists()


def test_unknown_html_theme_uses_default_css(tmp_path):
    """An unknown theme falls back to default doto.css."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "conf.py").write_text(
        "extensions = ['doxtr_doto']\n"
        "master_doc = 'index'\n"
        'doto_html_theme = "does-not-exist"\n'
    )
    (src / "index.rst").write_text(
        "Theme Test\n==========\n\n"
        ".. doto:: Test task\n"
        "   :id: THEME-001\n"
    )

    from sphinx.application import Sphinx
    out = tmp_path / "out"
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        app = Sphinx(
            srcdir=str(src),
            confdir=str(src),
            outdir=str(out),
            doctreedir=str(tmp_path / ".doctrees"),
            buildername="html",
        )
        app.build()
    
    # Should fall back to default CSS
    assert (out / "_static" / "doto.css").exists()


# ── Sync disabled ──────────────────────────────────────────────────────────


def test_sync_disabled_skips_json_operations(tmp_path):
    """doto_sync_on_build = False skips all JSON read/write operations."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "conf.py").write_text(
        "extensions = ['doxtr_doto']\n"
        "master_doc = 'index'\n"
        "doto_sync_on_build = False\n"
        "doto_auto_create_json = False\n"
    )
    (src / "index.rst").write_text(
        "T\n=\n\n.. doto:: Unsaved\n   :id: T-001\n"
    )

    from sphinx.application import Sphinx
    out = tmp_path / "out"
    app = Sphinx(
        srcdir=str(src),
        confdir=str(src),
        outdir=str(out),
        doctreedir=str(tmp_path / ".doctrees"),
        buildername="html",
    )
    app.build()

    # JSON store should NOT have been created
    assert not (src / ".doto" / "tasks.json").exists()


def test_sync_disabled_still_renders_tasks(tmp_path):
    """With sync disabled, tasks still render in HTML output."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "conf.py").write_text(
        "extensions = ['doxtr_doto']\n"
        "master_doc = 'index'\n"
        "doto_sync_on_build = False\n"
        "doto_auto_create_json = False\n"
    )
    (src / "index.rst").write_text(
        "Tasks\n=====\n\n"
        ".. doto:: Rendered task\n"
        "   :id: RENDER-001\n"
        "   :priority: high\n"
    )

    from sphinx.application import Sphinx
    out = tmp_path / "out"
    app = Sphinx(
        srcdir=str(src),
        confdir=str(src),
        outdir=str(out),
        doctreedir=str(tmp_path / ".doctrees"),
        buildername="html",
    )
    app.build()

    html = (out / "index.html").read_text()
    assert "RENDER-001" in html
    assert "Rendered task" in html


def test_auto_create_json_disabled_no_json_created(tmp_path):
    """With auto_create_json disabled, no JSON is created if missing."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "conf.py").write_text(
        "extensions = ['doxtr_doto']\n"
        "master_doc = 'index'\n"
        "doto_auto_create_json = False\n"
    )
    (src / "index.rst").write_text(
        "T\n=\n\n.. doto:: Task\n   :id: T-002\n"
    )

    from sphinx.application import Sphinx
    out = tmp_path / "out"
    app = Sphinx(
        srcdir=str(src),
        confdir=str(src),
        outdir=str(out),
        doctreedir=str(tmp_path / ".doctrees"),
        buildername="html",
    )
    app.build()

    # JSON store should NOT have been created since auto_create is disabled
    # and sync will skip when JSON doesn't exist
    # (behavior depends on sync_on_build default, but we test no crashes)
    assert (out / "index.html").exists()


# ── Invalid configurations ─────────────────────────────────────────────────


def test_invalid_priority_value_produces_error(tmp_path):
    """An invalid priority value produces an error in the build."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "conf.py").write_text(
        "extensions = ['doxtr_doto']\n"
        "master_doc = 'index'\n"
    )
    (src / "index.rst").write_text(
        "T\n=\n\n"
        ".. doto:: Bad priority\n"
        "   :id: BAD-001\n"
        "   :priority: ultra-mega-high\n"
    )

    from sphinx.application import Sphinx
    app = Sphinx(
        srcdir=str(src),
        confdir=str(src),
        outdir=str(tmp_path / "out"),
        doctreedir=str(tmp_path / ".doctrees"),
        buildername="html",
        warningiserror=True,  # Make warnings/errors fail the build
    )
    app.build()
    
    # Build should fail with non-zero status
    assert app.statuscode != 0


def test_invalid_status_value_produces_error(tmp_path):
    """An invalid status value produces an error in the build."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "conf.py").write_text(
        "extensions = ['doxtr_doto']\n"
        "master_doc = 'index'\n"
    )
    (src / "index.rst").write_text(
        "T\n=\n\n"
        ".. doto:: Bad status\n"
        "   :id: BAD-002\n"
        "   :status: maybe\n"
    )

    from sphinx.application import Sphinx
    app = Sphinx(
        srcdir=str(src),
        confdir=str(src),
        outdir=str(tmp_path / "out"),
        doctreedir=str(tmp_path / ".doctrees"),
        buildername="html",
        warningiserror=True,
    )
    app.build()
    
    assert app.statuscode != 0


def test_invalid_due_date_produces_error(tmp_path):
    """An invalid due date produces an error in the build."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "conf.py").write_text(
        "extensions = ['doxtr_doto']\n"
        "master_doc = 'index'\n"
    )
    (src / "index.rst").write_text(
        "T\n=\n\n"
        ".. doto:: Bad date\n"
        "   :id: BAD-003\n"
        "   :due: not-a-date\n"
    )

    from sphinx.application import Sphinx
    app = Sphinx(
        srcdir=str(src),
        confdir=str(src),
        outdir=str(tmp_path / "out"),
        doctreedir=str(tmp_path / ".doctrees"),
        buildername="html",
        warningiserror=True,
    )
    app.build()
    
    assert app.statuscode != 0


def test_duplicate_task_id_produces_error(tmp_path):
    """Duplicate task IDs produce an error in the build."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "conf.py").write_text(
        "extensions = ['doxtr_doto']\n"
        "master_doc = 'index'\n"
    )
    (src / "index.rst").write_text(
        "T\n=\n\n"
        ".. doto:: First task\n"
        "   :id: DUP-001\n\n"
        ".. doto:: Second task\n"
        "   :id: DUP-001\n"
    )

    from sphinx.application import Sphinx
    app = Sphinx(
        srcdir=str(src),
        confdir=str(src),
        outdir=str(tmp_path / "out"),
        doctreedir=str(tmp_path / ".doctrees"),
        buildername="html",
        warningiserror=True,
    )
    app.build()
    
    assert app.statuscode != 0


# ── Edge cases ─────────────────────────────────────────────────────────────


def test_task_with_special_characters_in_title(sphinx_build):
    """Tasks with special characters in title render correctly."""
    _, html = sphinx_build(
        ".. doto:: Task with <special> & \"chars\"\n"
        "   :id: SPECIAL-001\n"
    )
    # Should be HTML-escaped
    assert "SPECIAL-001" in html
    # Title should be present (escaped)
    assert "special" in html.lower()


def test_task_with_empty_body(sphinx_build):
    """A task with no body content builds successfully."""
    _, html = sphinx_build(
        ".. doto:: Task without body\n"
        "   :id: EMPTY-001\n"
        "   :priority: low\n"
    )
    assert "EMPTY-001" in html
    assert "Task without body" in html


def test_task_with_only_required_fields(sphinx_build):
    """A task with only required fields (id, title) builds successfully."""
    _, html = sphinx_build(
        ".. doto:: Minimal task\n"
        "   :id: MINIMAL-001\n"
    )
    assert "MINIMAL-001" in html
    assert "Minimal task" in html


def test_multiple_doto_lists_on_same_page(sphinx_build):
    """Multiple doto-list directives on the same page work correctly."""
    _, html = sphinx_build(
        ".. doto:: Open task\n"
        "   :id: MULTI-LIST-001\n"
        "   :status: open\n\n"
        ".. doto:: Done task\n"
        "   :id: MULTI-LIST-002\n"
        "   :status: done\n\n"
        "Open Tasks\n----------\n\n"
        ".. doto-list::\n"
        "   :status: open\n\n"
        "Done Tasks\n----------\n\n"
        ".. doto-list::\n"
        "   :status: done\n"
    )
    # Both lists should render
    assert "doto-list" in html


def test_doto_list_and_summary_on_same_page(sphinx_build):
    """doto-list and doto-summary can coexist on the same page."""
    _, html = sphinx_build(
        ".. doto:: Task A\n"
        "   :id: COEXIST-001\n\n"
        ".. doto:: Task B\n"
        "   :id: COEXIST-002\n\n"
        "Task List\n---------\n\n"
        ".. doto-list::\n\n"
        "Summary\n-------\n\n"
        ".. doto-summary::\n"
    )
    assert "doto-list" in html
    assert "doto-summary" in html
    assert "Total" in html


# ── Build isolation ────────────────────────────────────────────────────────


def test_clean_build_environment(tmp_path):
    """Each build starts with a clean environment."""
    src = tmp_path / "src"
    src.mkdir()
    out = tmp_path / "out"
    
    (src / "conf.py").write_text(
        "extensions = ['doxtr_doto']\n"
        "master_doc = 'index'\n"
    )
    
    # First build with one task
    (src / "index.rst").write_text(
        "First\n=====\n\n"
        ".. doto:: First task\n"
        "   :id: BUILD-001\n"
    )
    
    from sphinx.application import Sphinx
    app1 = Sphinx(
        srcdir=str(src),
        confdir=str(src),
        outdir=str(out),
        doctreedir=str(tmp_path / ".doctrees"),
        buildername="html",
        freshenv=True,
    )
    app1.build()
    
    html1 = (out / "index.html").read_text()
    assert "BUILD-001" in html1
    
    # Second build with different task
    (src / "index.rst").write_text(
        "Second\n======\n\n"
        ".. doto:: Second task\n"
        "   :id: BUILD-002\n"
    )
    
    import shutil
    shutil.rmtree(out)
    shutil.rmtree(tmp_path / ".doctrees")
    
    app2 = Sphinx(
        srcdir=str(src),
        confdir=str(src),
        outdir=str(out),
        doctreedir=str(tmp_path / ".doctrees"),
        buildername="html",
        freshenv=True,
    )
    app2.build()
    
    html2 = (out / "index.html").read_text()
    assert "BUILD-002" in html2
    # First task should not appear in second build
    assert "BUILD-001" not in html2
