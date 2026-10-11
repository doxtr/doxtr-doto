"""Centralized constants for doxtr_doto extension.

This module provides the single source of truth for status, priority,
and related constants used across directives, CLI, and rendering.
"""

from __future__ import annotations

# Valid values for task status
VALID_STATUSES: tuple[str, ...] = ("open", "in-progress", "blocked", "done")

# Valid values for task priority
VALID_PRIORITIES: tuple[str, ...] = ("low", "medium", "high", "critical")

# Valid task-list icon rendering modes (Feature 5). Single source of truth
# referenced by config.validate_config, directives/doto_list.py::_parse_icon_mode,
# and nodes._resolve_list_icon_mode so the set cannot drift across those sites.
#   "icon"      = Font Awesome icon only where a good icon exists (else text)
#   "icon-text" = icon followed by text (default)
#   "text"      = text only
VALID_LIST_ICON_MODES: frozenset[str] = frozenset({"icon", "icon-text", "text"})

# Valid PDF/LaTeX task-box layouts (Feature D). Single source of truth shared
# by config.validate_config and nodes._resolve_latex_layout so the set cannot
# drift across those sites.
#   "default" = roomy stacked-icon box (one metadata group per row)
#   "compact" = dense single-line header + inline icon+field pairs, same fields
VALID_LATEX_LAYOUTS: frozenset[str] = frozenset({"default", "compact"})

# Status ordering (higher value = more urgent/active)
STATUS_ORDER: dict[str, int] = {
    "blocked": 4,
    "in-progress": 3,
    "open": 2,
    "done": 1,
}

# Priority ordering (higher value = more important)
PRIORITY_ORDER: dict[str, int] = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
}

# CSS classes for priorities
PRIORITY_CLASSES: dict[str, str] = {
    "low": "doto-priority-low",
    "medium": "doto-priority-medium",
    "high": "doto-priority-high",
    "critical": "doto-priority-critical",
}

# CSS classes for statuses
STATUS_CLASSES: dict[str, str] = {
    "open": "doto-status-open",
    "in-progress": "doto-status-in-progress",
    "blocked": "doto-status-blocked",
    "done": "doto-status-done",
}

# Colors for charts and CLI output.
#
# SINGLE SOURCE OF TRUTH for the doto semantic color palette. These hex values
# are mirrored (as \definecolor{doto@*}) in themes/latex/doto.sty and referenced
# as fallback literals in integration/doxtr.py::_register_doxtr_containers. When
# changing a color here, update those two locations too (they are cross-linked
# with comments pointing back to this module). See PHASE F2 in the fix brief.
PRIORITY_COLORS: dict[str, str] = {
    "low": "#6c757d",
    "medium": "#0d6efd",
    "high": "#fd7e14",
    "critical": "#dc3545",
}

STATUS_COLORS: dict[str, str] = {
    "open": "#198754",
    "in-progress": "#0dcaf0",
    "blocked": "#dc3545",
    "done": "#6c757d",
}

# Display ordering (for iteration in UI/CLI)
STATUS_DISPLAY_ORDER: list[str] = ["open", "in-progress", "blocked", "done"]
PRIORITY_DISPLAY_ORDER: list[str] = ["critical", "high", "medium", "low"]

# Human-readable labels for UI display
STATUS_LABELS: dict[str, str] = {
    "open": "Open",
    "in-progress": "In Progress",
    "blocked": "Blocked",
    "done": "Done",
}

PRIORITY_LABELS: dict[str, str] = {
    "low": "Low",
    "medium": "Medium",
    "high": "High",
    "critical": "Critical",
}

# Default values
DEFAULT_PRIORITY = "medium"
DEFAULT_STATUS = "open"

# Status constants for specific checks
DONE_STATUS = "done"

# Monday-first three-letter weekday abbreviations, indexed by Python's
# datetime.date.weekday() convention (Monday=0 .. Sunday=6). SINGLE SOURCE OF
# TRUTH for weekday abbreviations: the title-case display labels and the
# lowercase parse-match set used by the TUI time-management screens
# (cli/tui/time_mgmt.py parse_workweek_text, cli/tui/widgets.py
# weekday_range_label) are both derived from this tuple, so the ordering
# cannot drift across those sites. This module imports nothing from the
# package, so it is a safe low-level home with no circular-import risk.
WEEKDAY_ABBR: tuple[str, ...] = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

# Archive defaults
ARCHIVE_DEFAULT_STATUSES: list[str] = ["done"]
