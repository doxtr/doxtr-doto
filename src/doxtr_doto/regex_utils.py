"""Safe regex utilities for doxtr_doto.

Provides a compile-and-validate wrapper that rejects patterns
known to be susceptible to catastrophic backtracking (ReDoS).

This module is the single point of control for user-supplied regex
patterns in the extension. All regex from directive options should
be validated through compile_safe() before use.
"""

from __future__ import annotations

import re
import signal
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from re import Match, Pattern

__all__ = [
    "MAX_PATTERN_LENGTH",
    "RegexTimeoutError",
    "UnsafePatternError",
    "validate_pattern",
    "compile_safe",
    "safe_match",
]


# Maximum allowed length for user-supplied patterns
MAX_PATTERN_LENGTH = 200


class RegexTimeoutError(ValueError):
    """Raised when a regex match takes too long.

    This exception is raised on POSIX systems when a regex match
    exceeds the configured timeout. On Windows, this exception
    is never raised because SIGALRM is not available.
    """

    pass


class UnsafePatternError(ValueError):
    """Raised when a regex pattern contains known-risky constructs.

    Patterns that are rejected include:
    - Patterns longer than MAX_PATTERN_LENGTH characters
    - Patterns containing nested quantifiers (e.g., (a+)+, (.*)*)
      which can cause catastrophic backtracking
    """

    pass


def _is_unix() -> bool:
    """Check if running on a POSIX-compliant system.

    Returns:
        True if on Unix/Linux/macOS, False on Windows.
    """
    return sys.platform != "win32"


# Regex pattern to detect nested quantifiers - the main ReDoS vector
# Matches patterns where there's a quantifier INSIDE a group that also has a quantifier OUTSIDE
# e.g.: (a+)+, (.*)+, ([a-z]+)*, (\w+)+
# Does NOT match: (?:foo)+, (ab)+, (a|b)+ where no internal quantifier exists
_NESTED_QUANTIFIER_PATTERN = re.compile(r"\([^)]*[+*]\)[+*?{]")


def validate_pattern(pattern: str) -> None:
    """Validate that a pattern is safe to use.

    Performs three levels of validation:
    1. Length limit - patterns longer than MAX_PATTERN_LENGTH are rejected
    2. Syntax check - pattern must compile without error
    3. Structural check - pattern must not contain nested quantifiers

    Args:
        pattern: The regex pattern string to validate.

    Raises:
        UnsafePatternError: If the pattern is too long or contains
            nested quantifiers that could cause ReDoS.
        re.error: If the pattern has invalid regex syntax.

    Example:
        >>> validate_pattern("auth.*timeout")  # OK
        >>> validate_pattern("a" * 201)  # Raises UnsafePatternError (too long)
        >>> validate_pattern(r"(a+)+$")  # Raises UnsafePatternError (nested quantifiers)
        >>> validate_pattern(r"[invalid")  # Raises re.error (bad syntax)
    """
    # Check 1: Length limit
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise UnsafePatternError(
            f"Regex pattern too long ({len(pattern)} > {MAX_PATTERN_LENGTH} chars). "
            "Use a simpler pattern."
        )

    # Check 2: Syntax validation - compile to catch syntax errors
    re.compile(pattern)

    # Check 3: Structural check for nested quantifiers
    # These are the main ReDoS vector: (X+)+, (X*)*, (X+)*, etc.
    if _NESTED_QUANTIFIER_PATTERN.search(pattern):
        raise UnsafePatternError(
            f"Regex pattern '{pattern}' contains nested quantifiers that may "
            "cause catastrophic backtracking. Use a simpler pattern."
        )


def compile_safe(
    pattern: str,
    flags: int = re.IGNORECASE,
    timeout_seconds: float = 1.0,
) -> Pattern[str]:
    """Compile a regex pattern with safety checks.

    Validates the pattern for safety (length, syntax, structure) and
    returns a compiled regex. The compiled regex's match/search methods
    are not themselves wrapped with a timeout — use safe_match() for
    timeout-protected matching.

    Args:
        pattern: Regex pattern string to compile.
        flags: re module flags (default: re.IGNORECASE).
        timeout_seconds: Reserved for documentation; actual timeout
            is applied in safe_match().

    Returns:
        Compiled regex Pattern object.

    Raises:
        UnsafePatternError: If the pattern is structurally risky
            (too long or contains nested quantifiers).
        re.error: If the pattern has invalid syntax.

    Example:
        >>> pattern = compile_safe("auth.*timeout")
        >>> pattern.search("authentication timeout error")
        <re.Match object; ...>
    """
    validate_pattern(pattern)
    return re.compile(pattern, flags)


def safe_match(
    compiled: Pattern[str],
    text: str,
    timeout_seconds: float = 1.0,
) -> Match[str] | None:
    """Execute a regex search with a timeout on POSIX systems.

    On POSIX systems (Linux, macOS), uses SIGALRM to enforce a timeout
    on the regex match operation. This provides runtime protection
    against patterns that slip through static analysis.

    On Windows (no SIGALRM support), falls back to plain search without
    timeout — the structural validation in compile_safe() provides
    the primary protection there.

    Args:
        compiled: Pre-compiled regex Pattern from compile_safe().
        text: Text string to search.
        timeout_seconds: Maximum execution time in seconds (POSIX only).
            Default is 1.0 second.

    Returns:
        Match object if the pattern matches, None otherwise.

    Raises:
        RegexTimeoutError: If the match exceeds the timeout (POSIX only).

    Example:
        >>> pattern = compile_safe("auth")
        >>> safe_match(pattern, "authentication")
        <re.Match object; ...>
        >>> safe_match(pattern, "no match here")
        None
    """
    # On Windows, fall back to plain search (no SIGALRM available)
    if not _is_unix():
        return compiled.search(text)

    def _timeout_handler(signum: int, frame: object) -> None:
        raise RegexTimeoutError(
            f"Regex match timed out after {timeout_seconds}s. "
            "The pattern may be too complex for the input text."
        )

    # Save old handler and set up timeout
    old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
    signal.setitimer(signal.ITIMER_REAL, timeout_seconds)

    try:
        return compiled.search(text)
    finally:
        # Always restore timer and handler, even on exception
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)
