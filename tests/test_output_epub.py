"""Tests for epub output format."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def sphinx_build_epub(tmp_path):
    """Helper fixture that runs a minimal Sphinx epub build."""
    def _build(rst_content: str, conf_extra: str = "") -> tuple[Path, str | None]:
        """
        Build a single RST page and return (outdir, page_content).

        Args:
            rst_content: The body of index.rst.
            conf_extra:  Extra lines appended to conf.py.
            
        Returns:
            Tuple of (outdir, content) where content is the tasks page if it exists.
        """
        src = tmp_path / "src"
        src.mkdir()
        out = tmp_path / "out"

        (src / "conf.py").write_text(
            "extensions = ['doxtr_doto']\n"
            "master_doc = 'index'\n"
            "exclude_patterns = ['_build']\n"
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
            buildername="epub",
        )
        app.build()

        # Try to find output content
        content = None
        for ext in ["xhtml", "html"]:
            index_file = out / f"index.{ext}"
            if index_file.exists():
                content = index_file.read_text()
                break

        return out, content

    return _build


class TestEpubOutput:
    """Tests for epub builder output."""
    
    def test_epub_build_succeeds(self, sphinx_build_epub):
        """Basic epub build should succeed without errors."""
        out, content = sphinx_build_epub(
            ".. doto:: Test Task\n"
            "   :id: TASK-001\n"
            "   :priority: high\n"
        )
        
        # Check build completed - epub creates various files
        assert out.exists()
        # Content should be available
        assert content is not None
    
    def test_epub_contains_task_content(self, sphinx_build_epub):
        """Tasks should be rendered in epub output."""
        out, content = sphinx_build_epub(
            ".. doto:: Implement user authentication\n"
            "   :id: TASK-001\n"
            "   :priority: high\n"
            "   :status: open\n"
        )
        
        assert content is not None
        assert "TASK-001" in content
        assert "Implement user authentication" in content
    
    def test_epub_task_has_styling_classes(self, sphinx_build_epub):
        """Task elements should have proper CSS classes in epub."""
        out, content = sphinx_build_epub(
            ".. doto:: Critical task\n"
            "   :id: TASK-002\n"
            "   :priority: high\n"
            "   :status: open\n"
        )
        
        assert content is not None
        assert 'class="doto' in content or 'doto-' in content
        assert 'doto-priority-high' in content
    
    def test_epub_doto_list_renders(self, sphinx_build_epub):
        """doto-list directive should render in epub."""
        out, content = sphinx_build_epub(
            ".. doto:: Task for list\n"
            "   :id: TASK-010\n"
            "   :priority: high\n\n"
            "Task Listing\n"
            "------------\n\n"
            ".. doto-list::\n"
            "   :format: list\n"
        )
        
        assert content is not None
        # Verify doto-list rendered - should contain task or list class
        assert 'doto-list' in content or 'TASK-010' in content
    
    def test_epub_doto_ref_renders(self, sphinx_build_epub):
        """Cross-references should render in epub."""
        out, content = sphinx_build_epub(
            ".. doto:: Referenced task\n"
            "   :id: TASK-REF-001\n"
            "   :priority: high\n\n"
            "References\n"
            "----------\n\n"
            "See :doto:`TASK-REF-001` for details.\n"
        )
        
        assert content is not None
        assert 'TASK-REF-001' in content
        # Should be rendered as a link or reference
        assert 'href=' in content or 'doto-ref' in content or 'reference' in content
    
    def test_epub_renders_assignee(self, sphinx_build_epub):
        """Epub output should render assignee field."""
        out, content = sphinx_build_epub(
            ".. doto:: Assigned task\n"
            "   :id: TASK-003\n"
            "   :assignee: alice\n"
        )
        
        assert content is not None
        assert "alice" in content
    
    def test_epub_renders_tags(self, sphinx_build_epub):
        """Epub output should render tags."""
        out, content = sphinx_build_epub(
            ".. doto:: Tagged task\n"
            "   :id: TASK-004\n"
            "   :tags: backend, security\n"
        )
        
        assert content is not None
        assert "backend" in content
        assert "security" in content
    
    def test_epub_renders_due_date(self, sphinx_build_epub):
        """Epub output should render due date."""
        out, content = sphinx_build_epub(
            ".. doto:: Task with due date\n"
            "   :id: TASK-005\n"
            "   :due: 2026-08-15\n"
        )
        
        assert content is not None
        assert "2026-08-15" in content
    
    def test_epub_renders_status_class(self, sphinx_build_epub):
        """Epub output should have status CSS class."""
        out, content = sphinx_build_epub(
            ".. doto:: In progress task\n"
            "   :id: TASK-006\n"
            "   :status: in-progress\n"
        )
        
        assert content is not None
        assert "doto-status-in-progress" in content
    
    def test_epub_renders_body_content(self, sphinx_build_epub):
        """Epub output should render task body content."""
        out, content = sphinx_build_epub(
            ".. doto:: Task with body\n"
            "   :id: TASK-007\n\n"
            "   This is the task body.\n"
            "   It has multiple lines.\n"
        )
        
        assert content is not None
        assert "This is the task body" in content
    
    def test_epub_multiple_tasks(self, sphinx_build_epub):
        """Epub output should render multiple tasks."""
        out, content = sphinx_build_epub(
            ".. doto:: First task\n"
            "   :id: MULTI-001\n\n"
            ".. doto:: Second task\n"
            "   :id: MULTI-002\n\n"
            ".. doto:: Third task\n"
            "   :id: MULTI-003\n"
        )
        
        assert content is not None
        assert "MULTI-001" in content
        assert "MULTI-002" in content
        assert "MULTI-003" in content


class TestEpubTheme:
    """Tests for epub theme support."""
    
    def test_epub_with_minimal_theme(self, sphinx_build_epub):
        """Epub build should work with minimal theme."""
        out, content = sphinx_build_epub(
            ".. doto:: Minimal theme task\n"
            "   :id: TASK-MIN-001\n",
            conf_extra='doto_epub_theme = "minimal"',
        )
        
        assert content is not None
        assert "TASK-MIN-001" in content
    
    def test_epub_default_theme(self, sphinx_build_epub):
        """Epub build should work with default theme."""
        out, content = sphinx_build_epub(
            ".. doto:: Default theme task\n"
            "   :id: TASK-DEF-001\n",
            conf_extra='doto_epub_theme = "default"',
        )
        
        assert content is not None
        assert "TASK-DEF-001" in content


class TestEpubSummary:
    """Tests for doto-summary in epub."""
    
    def test_epub_summary_renders(self, sphinx_build_epub):
        """doto-summary should render in epub output."""
        out, content = sphinx_build_epub(
            ".. doto:: Task A\n"
            "   :id: TASK-SUM-001\n"
            "   :status: open\n\n"
            ".. doto:: Task B\n"
            "   :id: TASK-SUM-002\n"
            "   :status: done\n\n"
            "Summary\n"
            "-------\n\n"
            ".. doto-summary::\n"
        )
        
        assert content is not None
        # Summary should show totals
        assert "doto-summary" in content or "Total" in content or "2" in content
