"""Tests for the regex_utils module - ReDoS prevention.

Tests cover pattern validation, safe compilation, and timeout-protected matching.
"""
from __future__ import annotations

import re
import sys

import pytest

from doxtr_doto.regex_utils import (
    MAX_PATTERN_LENGTH,
    RegexTimeoutError,
    UnsafePatternError,
    compile_safe,
    safe_match,
    validate_pattern,
)


class TestValidatePattern:
    """Tests for pattern validation."""

    def test_simple_pattern_is_accepted(self):
        """Simple patterns should pass validation."""
        validate_pattern("auth.*timeout")  # Should not raise

    def test_word_boundary_pattern_accepted(self):
        """Word boundary patterns are safe."""
        validate_pattern(r"\btest\b")

    def test_character_class_pattern_accepted(self):
        """Character class patterns are safe."""
        validate_pattern(r"[a-zA-Z0-9_]+")

    def test_alternation_pattern_accepted(self):
        """Alternation patterns are safe."""
        validate_pattern(r"foo|bar|baz")

    def test_anchored_pattern_accepted(self):
        """Anchored patterns are safe."""
        validate_pattern(r"^start.*end$")

    def test_pattern_too_long_raises(self):
        """Patterns exceeding MAX_PATTERN_LENGTH are rejected."""
        with pytest.raises(UnsafePatternError, match="too long"):
            validate_pattern("a" * (MAX_PATTERN_LENGTH + 1))

    def test_pattern_at_max_length_accepted(self):
        """Patterns at exactly MAX_PATTERN_LENGTH are accepted."""
        validate_pattern("a" * MAX_PATTERN_LENGTH)  # Should not raise

    def test_nested_quantifier_plus_plus_raises(self):
        """Nested quantifier (a+)+ is rejected."""
        with pytest.raises(UnsafePatternError, match="nested quantifiers"):
            validate_pattern(r"(a+)+$")

    def test_nested_quantifier_star_star_raises(self):
        """Nested quantifier (a*)* is rejected."""
        with pytest.raises(UnsafePatternError, match="nested quantifiers"):
            validate_pattern(r"(a*)*$")

    def test_nested_quantifier_plus_star_raises(self):
        """Nested quantifier (a+)* is rejected."""
        with pytest.raises(UnsafePatternError, match="nested quantifiers"):
            validate_pattern(r"(a+)*")

    def test_nested_quantifier_star_plus_raises(self):
        """Nested quantifier (a*)+ is rejected."""
        with pytest.raises(UnsafePatternError, match="nested quantifiers"):
            validate_pattern(r"(a*)+")

    def test_nested_quantifier_with_dot_raises(self):
        """Nested quantifier (.*)+$ is rejected."""
        with pytest.raises(UnsafePatternError, match="nested quantifiers"):
            validate_pattern(r"(.*)+$")

    def test_nested_quantifier_with_character_class_raises(self):
        """Nested quantifier ([a-z]+)+ is rejected."""
        with pytest.raises(UnsafePatternError, match="nested quantifiers"):
            validate_pattern(r"([a-z]+)+")

    def test_nested_quantifier_with_word_class_raises(self):
        """Nested quantifier (\\w+)+ is rejected."""
        with pytest.raises(UnsafePatternError, match="nested quantifiers"):
            validate_pattern(r"(\w+)+")

    def test_invalid_syntax_raises_re_error(self):
        """Invalid regex syntax raises re.error."""
        with pytest.raises(re.error):
            validate_pattern(r"[invalid")

    def test_unbalanced_parentheses_raises(self):
        """Unbalanced parentheses raise re.error."""
        with pytest.raises(re.error):
            validate_pattern(r"(unclosed")

    def test_empty_pattern_accepted(self):
        """Empty pattern is technically valid."""
        validate_pattern("")  # Should not raise


class TestCompileSafe:
    """Tests for safe pattern compilation."""

    def test_simple_pattern_compiles(self):
        """Simple patterns compile successfully."""
        pattern = compile_safe("auth.*timeout")
        assert pattern is not None
        assert pattern.search("authentication timeout error")

    def test_ignorecase_flag_default(self):
        """IGNORECASE flag is applied by default."""
        pattern = compile_safe("test")
        assert pattern.search("TEST") is not None
        assert pattern.search("test") is not None
        assert pattern.search("TeSt") is not None

    def test_custom_flags(self):
        """Custom flags can be passed."""
        pattern = compile_safe("test", flags=0)  # No IGNORECASE
        assert pattern.search("test") is not None
        assert pattern.search("TEST") is None

    def test_multiline_flag(self):
        """MULTILINE flag works."""
        pattern = compile_safe("^line", flags=re.MULTILINE | re.IGNORECASE)
        assert pattern.search("first\nline two") is not None

    def test_unsafe_pattern_raises(self):
        """Unsafe patterns are rejected at compile time."""
        with pytest.raises(UnsafePatternError):
            compile_safe(r"(a+)+")

    def test_long_pattern_raises(self):
        """Patterns exceeding length limit are rejected."""
        with pytest.raises(UnsafePatternError, match="too long"):
            compile_safe("a" * (MAX_PATTERN_LENGTH + 1))

    def test_invalid_syntax_raises(self):
        """Invalid syntax raises re.error."""
        with pytest.raises(re.error):
            compile_safe(r"[bad")


class TestSafeMatch:
    """Tests for timeout-protected matching."""

    def test_simple_match_succeeds(self):
        """Simple match returns Match object."""
        pattern = compile_safe("auth")
        result = safe_match(pattern, "authentication")
        assert result is not None
        assert result.group() == "auth"

    def test_no_match_returns_none(self):
        """No match returns None."""
        pattern = compile_safe("zzzz")
        result = safe_match(pattern, "authentication")
        assert result is None

    def test_match_at_start(self):
        """Match at start of string."""
        pattern = compile_safe("^auth")
        result = safe_match(pattern, "authentication")
        assert result is not None

    def test_match_in_middle(self):
        """Match in middle of string."""
        pattern = compile_safe("thent")
        result = safe_match(pattern, "authentication")
        assert result is not None

    def test_match_at_end(self):
        """Match at end of string."""
        pattern = compile_safe("tion$")
        result = safe_match(pattern, "authentication")
        assert result is not None

    def test_match_captures_groups(self):
        """Captured groups are accessible."""
        pattern = compile_safe(r"auth(\w+)")
        result = safe_match(pattern, "authentication")
        assert result is not None
        assert result.group(1) == "entication"

    def test_custom_timeout(self):
        """Custom timeout parameter is accepted."""
        pattern = compile_safe("test")
        result = safe_match(pattern, "testing", timeout_seconds=5.0)
        assert result is not None

    @pytest.mark.skipif(sys.platform == "win32", reason="SIGALRM not available on Windows")
    def test_timeout_parameter_is_used_on_unix(self):
        """Timeout parameter is actually used on Unix systems."""
        # This test just verifies the code path doesn't error
        pattern = compile_safe("test")
        result = safe_match(pattern, "testing", timeout_seconds=0.5)
        assert result is not None


class TestEdgeCases:
    """Tests for edge cases and special patterns."""

    def test_unicode_pattern(self):
        """Unicode patterns work correctly."""
        pattern = compile_safe("café")
        assert safe_match(pattern, "I love café") is not None

    def test_unicode_text(self):
        """Unicode text is matched correctly."""
        pattern = compile_safe("test")
        assert safe_match(pattern, "日本語test日本語") is not None

    def test_empty_text(self):
        """Empty text can be matched."""
        pattern = compile_safe(".*")
        result = safe_match(pattern, "")
        assert result is not None

    def test_very_long_text(self):
        """Very long text can be matched efficiently."""
        pattern = compile_safe("needle")
        text = "haystack " * 10000 + "needle" + " haystack" * 10000
        result = safe_match(pattern, text)
        assert result is not None

    def test_special_regex_chars_escaped(self):
        """Special chars in pattern work when escaped."""
        pattern = compile_safe(r"\[test\]")
        assert safe_match(pattern, "this is [test] text") is not None

    def test_lookahead_accepted(self):
        """Lookahead patterns are accepted (not nested quantifiers)."""
        pattern = compile_safe(r"foo(?=bar)")
        assert safe_match(pattern, "foobar") is not None
        assert safe_match(pattern, "foobaz") is None

    def test_lookbehind_accepted(self):
        """Lookbehind patterns are accepted."""
        pattern = compile_safe(r"(?<=foo)bar")
        assert safe_match(pattern, "foobar") is not None
        assert safe_match(pattern, "bazbar") is None

    def test_non_capturing_group_accepted(self):
        """Non-capturing groups are accepted."""
        pattern = compile_safe(r"(?:foo)+bar")
        assert safe_match(pattern, "foobar") is not None

    def test_named_group_accepted(self):
        """Named groups are accepted."""
        pattern = compile_safe(r"(?P<word>\w+)")
        result = safe_match(pattern, "hello")
        assert result is not None
        assert result.group("word") == "hello"


class TestMaxPatternLength:
    """Tests for MAX_PATTERN_LENGTH constant."""

    def test_max_pattern_length_is_reasonable(self):
        """MAX_PATTERN_LENGTH is a reasonable value."""
        assert MAX_PATTERN_LENGTH >= 100
        assert MAX_PATTERN_LENGTH <= 1000

    def test_max_pattern_length_is_200(self):
        """MAX_PATTERN_LENGTH is exactly 200."""
        assert MAX_PATTERN_LENGTH == 200


class TestExceptionTypes:
    """Tests for custom exception types."""

    def test_unsafe_pattern_error_is_value_error(self):
        """UnsafePatternError inherits from ValueError."""
        assert issubclass(UnsafePatternError, ValueError)

    def test_regex_timeout_error_is_value_error(self):
        """RegexTimeoutError inherits from ValueError."""
        assert issubclass(RegexTimeoutError, ValueError)

    def test_unsafe_pattern_error_message(self):
        """UnsafePatternError has descriptive message."""
        try:
            validate_pattern("a" * 300)
        except UnsafePatternError as e:
            assert "300" in str(e)
            assert "200" in str(e)

    def test_nested_quantifier_error_message(self):
        """Nested quantifier error includes the pattern."""
        try:
            validate_pattern(r"(a+)+")
        except UnsafePatternError as e:
            assert "(a+)+" in str(e)
            assert "nested quantifiers" in str(e)
