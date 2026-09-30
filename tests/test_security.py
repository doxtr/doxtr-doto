"""Tests for security utilities and XSS prevention."""

from __future__ import annotations

from pathlib import Path

import pytest

from doxtr_doto.utils import (
    escape_html_attr,
    escape_html_content,
    sanitize_html_id,
    validate_path_within,
)


# ── HTML escaping tests ────────────────────────────────────────────────────


class TestEscapeHtmlAttr:
    """Tests for escape_html_attr function."""

    def test_escapes_double_quotes(self):
        """Double quotes are escaped for attribute safety."""
        assert escape_html_attr('test"value') == "test&quot;value"

    def test_escapes_single_quotes(self):
        """Single quotes are escaped for attribute safety."""
        assert escape_html_attr("test'value") == "test&#x27;value"

    def test_escapes_angle_brackets(self):
        """Angle brackets are escaped."""
        assert escape_html_attr("<script>") == "&lt;script&gt;"

    def test_escapes_ampersand(self):
        """Ampersands are escaped."""
        assert escape_html_attr("foo&bar") == "foo&amp;bar"

    def test_handles_none(self):
        """None returns empty string."""
        assert escape_html_attr(None) == ""

    def test_handles_integers(self):
        """Integer values are converted and escaped."""
        assert escape_html_attr(42) == "42"

    def test_handles_empty_string(self):
        """Empty string returns empty string."""
        assert escape_html_attr("") == ""


class TestEscapeHtmlContent:
    """Tests for escape_html_content function."""

    def test_escapes_script_tags(self):
        """Script tags are escaped."""
        result = escape_html_content("<script>alert(1)</script>")
        assert result == "&lt;script&gt;alert(1)&lt;/script&gt;"

    def test_escapes_ampersand(self):
        """Ampersands are escaped."""
        assert escape_html_content("foo&bar") == "foo&amp;bar"

    def test_does_not_escape_quotes(self):
        """Quotes are not escaped in content (quote=False)."""
        # Content escaping doesn't need to escape quotes
        result = escape_html_content('test"value')
        assert "&quot;" not in result or '"' in result

    def test_handles_none(self):
        """None returns empty string."""
        assert escape_html_content(None) == ""

    def test_handles_multiline_content(self):
        """Multiline content is handled correctly."""
        result = escape_html_content("line1\nline2<br>")
        assert "line1\nline2" in result
        assert "&lt;br&gt;" in result


class TestSanitizeHtmlId:
    """Tests for sanitize_html_id function."""

    def test_valid_id_unchanged(self):
        """Valid IDs pass through unchanged."""
        assert sanitize_html_id("TASK-001") == "TASK-001"
        assert sanitize_html_id("task_123") == "task_123"
        assert sanitize_html_id("my.task") == "my.task"

    def test_replaces_special_characters(self):
        """Special characters are replaced with hyphens."""
        result = sanitize_html_id("task<script>")
        assert "<" not in result
        assert ">" not in result
        assert "script" in result

    def test_prefixes_leading_digit(self):
        """IDs starting with digits get a prefix."""
        assert sanitize_html_id("123-task") == "doto-123-task"

    def test_handles_empty_string(self):
        """Empty string returns default."""
        assert sanitize_html_id("") == "doto-unknown"

    def test_collapses_consecutive_hyphens(self):
        """Multiple consecutive hyphens are collapsed."""
        result = sanitize_html_id("task---test")
        assert "---" not in result

    def test_strips_leading_trailing_hyphens(self):
        """Leading and trailing hyphens are stripped."""
        result = sanitize_html_id("-task-")
        assert not result.startswith("-")
        assert not result.endswith("-")

    def test_handles_spaces(self):
        """Spaces are replaced with hyphens."""
        result = sanitize_html_id("my task id")
        assert " " not in result
        assert "-" in result or result == "my-task-id"

    def test_handles_unicode(self):
        """Unicode characters are handled."""
        result = sanitize_html_id("täsk-ñame")
        # Should either keep valid unicode word chars or replace them
        assert result  # Should not be empty


# ── Path validation tests ──────────────────────────────────────────────────


class TestValidatePathWithin:
    """Tests for validate_path_within function."""

    def test_valid_relative_path(self, tmp_path: Path):
        """Valid relative paths within base are accepted."""
        base = tmp_path / "project"
        base.mkdir()
        
        result = validate_path_within("tasks/new.rst", base)
        assert result == base / "tasks" / "new.rst"

    def test_valid_absolute_path(self, tmp_path: Path):
        """Valid absolute paths within base are accepted."""
        base = tmp_path / "project"
        base.mkdir()
        target = base / "tasks" / "new.rst"
        
        result = validate_path_within(str(target), base)
        assert result == target

    def test_rejects_parent_traversal(self, tmp_path: Path):
        """Parent directory traversal is rejected."""
        base = tmp_path / "project" / "docs"
        base.mkdir(parents=True)
        
        with pytest.raises(ValueError, match="outside"):
            validate_path_within("../secret.txt", base)

    def test_rejects_double_parent_traversal(self, tmp_path: Path):
        """Multiple parent traversals are rejected."""
        base = tmp_path / "project" / "docs"
        base.mkdir(parents=True)
        
        with pytest.raises(ValueError, match="outside"):
            validate_path_within("../../etc/passwd", base)

    def test_rejects_absolute_outside_base(self, tmp_path: Path):
        """Absolute paths outside base are rejected."""
        base = tmp_path / "project"
        base.mkdir()
        
        with pytest.raises(ValueError, match="outside"):
            validate_path_within("/etc/passwd", base)

    def test_handles_nested_relative_paths(self, tmp_path: Path):
        """Nested relative paths are resolved correctly."""
        base = tmp_path / "project"
        base.mkdir()
        
        # Path with internal .. that still stays within base
        result = validate_path_within("tasks/../docs/file.rst", base)
        assert result == base / "docs" / "file.rst"

    def test_handles_path_objects(self, tmp_path: Path):
        """Path objects work as input."""
        base = tmp_path / "project"
        base.mkdir()
        
        result = validate_path_within(Path("tasks/new.rst"), base)
        assert result == base / "tasks" / "new.rst"


# ── XSS prevention integration tests ───────────────────────────────────────


@pytest.fixture
def sphinx_build(tmp_path):
    """Helper fixture that runs a minimal Sphinx HTML build."""
    def _build(rst_content: str, conf_extra: str = "") -> tuple[Path, str]:
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


class TestXssPrevention:
    """Integration tests for XSS prevention in HTML output."""

    def test_title_with_script_tag_is_escaped(self, sphinx_build):
        """Script tags in task titles are escaped."""
        _, html = sphinx_build(
            ".. doto:: <script>alert('xss')</script>\n"
            "   :id: XSS-001\n"
        )
        # Script tag should be escaped, not raw
        assert "<script>alert" not in html
        assert "&lt;script&gt;" in html or "alert" not in html

    def test_assignee_with_html_is_escaped(self, sphinx_build):
        """HTML in assignee field is escaped."""
        _, html = sphinx_build(
            ".. doto:: Test task\n"
            "   :id: XSS-002\n"
            '   :assignee: <img src=x onerror="alert(1)">\n'
        )
        # Should not contain unescaped img tag
        assert '<img src=x onerror="alert(1)">' not in html

    def test_tag_with_html_is_escaped(self, sphinx_build):
        """HTML in tags is escaped."""
        _, html = sphinx_build(
            ".. doto:: Test task\n"
            "   :id: XSS-003\n"
            "   :tags: <b>bold</b>, normal\n"
        )
        # Bold tag should be escaped
        assert "<b>bold</b>" not in html


class TestLatexEscaping:
    """Tests for LaTeX special character escaping."""

    def test_latex_escape_function(self):
        """LaTeX special characters are properly escaped."""
        from doxtr_doto.nodes import _latex_escape
        
        # Test special characters
        assert _latex_escape("test&value") == "test\\&value"
        assert _latex_escape("100%") == "100\\%"
        assert _latex_escape("$price") == "\\$price"
        assert _latex_escape("item #1") == "item \\#1"
        assert _latex_escape("under_score") == "under\\_score"
        assert _latex_escape("{braces}") == "\\{braces\\}"

    def test_latex_escape_empty_string(self):
        """Empty string returns empty string."""
        from doxtr_doto.nodes import _latex_escape
        
        assert _latex_escape("") == ""

    def test_latex_escape_backslash(self):
        """Backslashes are escaped."""
        from doxtr_doto.nodes import _latex_escape
        
        result = _latex_escape("path\\to\\file")
        assert "\\\\" in result or "textbackslash" in result
