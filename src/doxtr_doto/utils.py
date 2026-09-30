"""Shared utilities for doxtr_doto extension.

This module provides common utility functions used across the doxtr_doto
extension, including:

- Date parsing and formatting utilities (delegated to date_utils.py)
- List parsing from comma-separated strings
- Validation functions for priority and status values
- HTML escaping utilities for secure output
- Path validation for traversal prevention

Note: Date functions in this module delegate to date_utils.py for consistency.
New code should import directly from doxtr_doto.date_utils.
"""

from __future__ import annotations

import html
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Union

from doxtr_doto.constants import VALID_PRIORITIES, VALID_STATUSES

# Re-export DotoDate for convenience
from doxtr_doto.date_utils import DotoDate

# Date format for parsing
DATE_FORMAT = "%Y-%m-%d"


def normalize_date(value: Union[str, date, datetime, None]) -> str | None:
    """Normalize a date value to ISO format string (YYYY-MM-DD).
    
    Accepts various date representations and converts them to a consistent
    ISO format string for storage and comparison.
    
    Note: This function delegates to date_utils.normalize_date.
    New code should import directly from doxtr_doto.date_utils.
    
    Args:
        value: Date as string (ISO format), date object, datetime object, or None.
        
    Returns:
        ISO format string (YYYY-MM-DD) or None if value is None/empty.
        
    Raises:
        ValueError: If string is not valid ISO format (YYYY-MM-DD).
        TypeError: If value is not a supported type.
        
    Examples:
        >>> normalize_date("2024-01-15")
        '2024-01-15'
        >>> normalize_date(date(2024, 1, 15))
        '2024-01-15'
        >>> normalize_date(None)
        None
    """
    from doxtr_doto.date_utils import normalize_date as _normalize_date
    return _normalize_date(value)


def parse_date_safe(value: str | None) -> date | None:
    """Safely parse an ISO date string to a date object.
    
    Unlike parse_date(), this function returns None for invalid input
    instead of raising an exception, making it suitable for use in
    contexts where invalid dates should be silently ignored.
    
    Note: This function delegates to date_utils.parse_date_safe.
    New code should import directly from doxtr_doto.date_utils.
    
    Args:
        value: ISO date string (YYYY-MM-DD) or None.
        
    Returns:
        Parsed date object, or None if value is None, empty, or invalid.
        
    Examples:
        >>> parse_date_safe("2024-01-15")
        datetime.date(2024, 1, 15)
        >>> parse_date_safe("invalid")
        None
        >>> parse_date_safe(None)
        None
    """
    from doxtr_doto.date_utils import parse_date_safe as _parse_date_safe
    result = _parse_date_safe(value)
    # Return the underlying date object for backward compatibility
    return result.date if result else None


def format_date_display(
    value: Union[str, date, None],
    fmt: str = DATE_FORMAT,
) -> str:
    """Format a date for display.
    
    Converts a date (as string or date object) to a formatted string
    for display in UI or reports.
    
    Note: This function delegates to date_utils.format_date_display.
    New code should import directly from doxtr_doto.date_utils.
    
    Args:
        value: Date as ISO string (YYYY-MM-DD), date object, or None.
        fmt: strftime format string. Defaults to YYYY-MM-DD.
        
    Returns:
        Formatted date string, or empty string if value is None.
        Returns the original string if parsing fails.
        
    Examples:
        >>> format_date_display("2024-01-15")
        '2024-01-15'
        >>> format_date_display(date(2024, 1, 15), "%b %d, %Y")
        'Jan 15, 2024'
        >>> format_date_display(None)
        ''
    """
    from doxtr_doto.date_utils import format_date_display as _format_date_display
    result = _format_date_display(value, fmt)
    # If date_utils returns empty string, check if we should return original
    if not result and isinstance(value, str) and value.strip():
        # Return original string if parse failed (backward compatibility)
        return value
    return result


def parse_list(value: str) -> list[str]:
    """Parse a comma-separated list of values.

    Args:
        value: Comma-separated string.

    Returns:
        List of stripped, non-empty strings.
    """
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_date(value: str) -> date | None:
    """Parse a date string in YYYY-MM-DD format.

    Note: This function delegates to date_utils.parse_date.
    New code should import directly from doxtr_doto.date_utils.

    Args:
        value: Date string to parse.

    Returns:
        Parsed date object or None if empty.

    Raises:
        ValueError: If the date format is invalid.
    """
    from doxtr_doto.date_utils import parse_date as _parse_date
    try:
        result = _parse_date(value)
        # Return the underlying date object for backward compatibility
        return result.date if result else None
    except (ValueError, TypeError) as e:
        raise ValueError(
            f"Invalid date format '{value}'. Expected YYYY-MM-DD."
        ) from e


def parse_boolean(value: str) -> bool:
    """Parse a boolean string value.

    For directive options, an empty string means the flag was present without
    a value (e.g., `:show-chart:` vs `:show-chart: true`), which should be
    treated as True.

    Args:
        value: String to parse as boolean.

    Returns:
        True for "true", "yes", "1", or empty string (flag present).
        False for any other value.
    """
    return value.strip().lower() in ("true", "yes", "1", "")


def validate_priority(value: str) -> str:
    """Validate and normalize priority value.

    Args:
        value: Priority string to validate.

    Returns:
        Normalized priority string.

    Raises:
        ValueError: If priority is not valid.
    """
    normalized = value.strip().lower()
    if normalized not in VALID_PRIORITIES:
        raise ValueError(
            f"Invalid priority '{value}'. "
            f"Must be one of: {', '.join(sorted(VALID_PRIORITIES))}"
        )
    return normalized


def validate_status(value: str) -> str:
    """Validate and normalize status value.

    Args:
        value: Status string to validate.

    Returns:
        Normalized status string.

    Raises:
        ValueError: If status is not valid.
    """
    normalized = value.strip().lower()
    if normalized not in VALID_STATUSES:
        raise ValueError(
            f"Invalid status '{value}'. "
            f"Must be one of: {', '.join(sorted(VALID_STATUSES))}"
        )
    return normalized


# ── HTML escaping utilities ────────────────────────────────────────────────


def escape_html_attr(value: Any) -> str:
    """Escape a value for use in an HTML attribute.

    Args:
        value: Value to escape.

    Returns:
        HTML-safe string suitable for attribute values.

    Example:
        >>> escape_html_attr('test"value')
        'test&quot;value'
        >>> escape_html_attr(None)
        ''
    """
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def escape_html_content(value: Any) -> str:
    """Escape a value for use in HTML content.

    Args:
        value: Value to escape.

    Returns:
        HTML-safe string suitable for element content.

    Example:
        >>> escape_html_content('<script>alert(1)</script>')
        '&lt;script&gt;alert(1)&lt;/script&gt;'
        >>> escape_html_content(None)
        ''
    """
    if value is None:
        return ""
    return html.escape(str(value), quote=False)


def sanitize_html_id(value: str) -> str:
    """Sanitize a string for use as an HTML id attribute.

    HTML5 ids can contain any characters except spaces, but for
    compatibility and URL fragment safety, we restrict to:
    - Letters (a-z, A-Z)
    - Digits (0-9)
    - Hyphens (-)
    - Underscores (_)
    - Periods (.)

    Other characters are replaced with hyphens. Leading digits
    get a prefix.

    Args:
        value: String to sanitize.

    Returns:
        Safe HTML id string.

    Example:
        >>> sanitize_html_id('TASK-001')
        'TASK-001'
        >>> sanitize_html_id('task<script>')
        'task-script-'
        >>> sanitize_html_id('123-task')
        'doto-123-task'
    """
    if not value:
        return "doto-unknown"

    # Replace invalid characters with hyphens
    sanitized = re.sub(r'[^\w\-\.]', '-', value)

    # Remove consecutive hyphens
    sanitized = re.sub(r'-+', '-', sanitized)

    # Strip leading/trailing hyphens
    sanitized = sanitized.strip('-')

    # Ensure doesn't start with digit (add prefix)
    if sanitized and sanitized[0].isdigit():
        sanitized = f"doto-{sanitized}"

    return sanitized or "doto-unknown"


# ── Path validation utilities ──────────────────────────────────────────────


def validate_path_within(path: Path | str, base: Path | str) -> Path:
    """Validate that a path is within a base directory.

    Resolves the path and ensures it's under the base directory,
    preventing path traversal attacks.

    Args:
        path: Path to validate (can be relative).
        base: Base directory that path must be within.

    Returns:
        Resolved absolute path.

    Raises:
        ValueError: If path is outside base directory.

    Example:
        >>> validate_path_within("tasks/new.rst", "/project/docs")
        PosixPath('/project/docs/tasks/new.rst')

        >>> validate_path_within("../secret.txt", "/project/docs")
        ValueError: Path '../secret.txt' is outside base directory
    """
    base = Path(base).resolve()

    # Handle relative paths
    if not Path(path).is_absolute():
        full_path = base / path
    else:
        full_path = Path(path)

    # Resolve to handle .. and symlinks
    resolved = full_path.resolve()

    # Check if resolved path is under base
    try:
        resolved.relative_to(base)
    except ValueError:
        raise ValueError(
            f"Path '{path}' resolves to '{resolved}' which is outside "
            f"the base directory '{base}'"
        ) from None

    return resolved
