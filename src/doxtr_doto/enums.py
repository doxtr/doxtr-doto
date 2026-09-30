"""Enumerations for doxtr_doto.

All string-valued enums are defined here. Using enums instead of
raw strings prevents typos, enables IDE auto-complete, and makes
refactoring safe.

Since all enums inherit from (str, Enum), existing string comparisons
continue to work without modification (e.g., `action == "create"` still
matches `SyncAction.CREATE`). This makes the migration safe and incremental.
"""

from __future__ import annotations

from enum import Enum


class SyncAction(str, Enum):
    """Action type for a queued RST update."""

    CREATE = "create"
    UPDATE = "update"
    REMOVE = "remove"


class ConflictResolution(str, Enum):
    """Behaviour when a bidirectional sync conflict is detected."""

    ERROR = "error"
    WARN = "warn"
    PREFER_RST = "prefer-rst"
    PREFER_JSON = "prefer-json"


class DotoIntegration(str, Enum):
    """Doxtr integration mode."""

    AUTO = "auto"
    ENABLED = "enabled"
    DISABLED = "disabled"


class TaskSource(str, Enum):
    """Indicates where a DotoTask originated."""

    RST = "rst"
    JSON = "json"
    MERGED = "merged"


class ChartType(str, Enum):
    """Chart type for doto-summary directive.

    Kept in sync with ``charts.VALID_CHART_TYPES`` (the authoritative set the
    renderers dispatch on). ``tests/test_enums.py`` asserts they match.
    """

    BAR = "bar"
    PIE = "pie"
    STACKED_BAR = "stacked-bar"
    PROGRESS = "progress"
    BURNDOWN = "burndown"


class ListFormat(str, Enum):
    """Display format for doto-list directive."""

    TABLE = "table"
    LIST = "list"
    CARDS = "cards"
