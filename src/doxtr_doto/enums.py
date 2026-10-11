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
    INSERT_ID = "insert-id"


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
    """Display format (layout view) for the doto-list directive.

    Kept in sync with ``directives.doto_list.VALID_FORMATS`` (derived from this
    enum) and the HTML renderer dispatch table ``nodes._LIST_RENDERERS``.
    ``tests/test_enums.py`` asserts the enum and VALID_FORMATS match.

    The ``kanban``/``calendar``/``email`` views are HTML-interactive layouts
    backed by a vendored, dependency-free JS asset (client-side only; a static
    Sphinx build has no backend to persist changes). LaTeX/epub degrade these
    to a static table/list fallback.
    """

    TABLE = "table"
    LIST = "list"
    CARDS = "cards"
    KANBAN = "kanban"
    CALENDAR = "calendar"
    EMAIL = "email"


class TuiLayout(str, Enum):
    """Layout view for the interactive ``doto tui`` task list.

    Distinct from :class:`ListFormat` (which drives the static ``doto-list``
    directive HTML renders): this enum selects the live Textual TUI's
    task-list layout, cycled with the ``v`` keybinding and persisted as the
    user's default in global state (``tui_layout``).

    Members:
        TABLE: The default 3-pane table (the existing TUI task list).
        LIST: A single-column list, one task per line; Enter reveals details.
        KANBAN: Columns grouped by status; a task is moved between columns
            (changing its status) with the terminal drag-equivalent ``h``/``l``
            keys.
        CALENDAR: A month calendar placing tasks on their due date, with a
            "no due date" bucket for undated tasks and a selected-day detail.
        TIME: A time-management view of the global work clock: each worked day
            with its intervals and gross/break/net totals plus a grand total.
            Enter opens the work-time manager for the selected day.
    """

    TABLE = "table"
    LIST = "list"
    KANBAN = "kanban"
    CALENDAR = "calendar"
    TIME = "time"


class DueFilter(str, Enum):
    """Due-date filter for the interactive ``doto tui`` filter/sort pop-up.

    Selects which tasks the :class:`doxtr_doto.cli.tui.filtersort.ViewPrefs`
    due filter keeps, based on each task's ``due`` date relative to a
    reference "today". Persisted in global state as the user's last filter
    choice (``tui_due_filter``).

    Members:
        ALL: No due-date filter (every task passes). The default.
        TODAY: Keep only tasks whose ``due`` date is today.
        WEEK: Keep only tasks whose ``due`` date falls within the current
            week (today through the coming Sunday, inclusive).
    """

    ALL = "all"
    TODAY = "today"
    WEEK = "week"


class SortKey(str, Enum):
    """Sort key for the interactive ``doto tui`` filter/sort pop-up.

    Selects how :class:`doxtr_doto.cli.tui.filtersort.ViewPrefs` orders the
    visible tasks before the active (time-recorded) task is pinned to the top.
    Persisted in global state as the user's last sort choice
    (``tui_sort_key``).

    Members:
        NONE: No explicit sort; preserve the gathered order. The default.
        DUE: Sort by ``due`` date (undated tasks sort last).
        PRIORITY: Sort by priority (critical highest).
        TAG: Sort by the task's first tag (alphabetical; untagged last).
        NEXT: Sort by the recommended-next ordering, reusing the ``doto next``
            scoring (:func:`doxtr_doto.cli.commands.next.calculate_task_score`).
    """

    NONE = "none"
    DUE = "due"
    PRIORITY = "priority"
    TAG = "tag"
    NEXT = "next"


class SortOrder(str, Enum):
    """Sort direction for the interactive ``doto tui`` filter/sort pop-up.

    Members:
        ASC: Ascending order (the natural order of the sort key). The default.
        DESC: Descending order (the reverse of ``ASC``).
    """

    ASC = "asc"
    DESC = "desc"


#: Human-readable labels for each :class:`DueFilter` member, keyed by the enum.
#: Single source of truth for the filter/sort pop-up's due-filter select
#: options so a new member cannot be backend-supported but UI-unselectable;
#: ``tests/test_enums.py`` asserts every member has a label.
DUE_FILTER_LABELS: dict[DueFilter, str] = {
    DueFilter.ALL: "All",
    DueFilter.TODAY: "Due today",
    DueFilter.WEEK: "Due this week",
}

#: Human-readable labels for each :class:`SortKey` member, keyed by the enum.
#: Single source of truth for the filter/sort pop-up's sort-key select options
#: so a new member cannot be backend-supported but UI-unselectable;
#: ``tests/test_enums.py`` asserts every member has a label.
SORT_KEY_LABELS: dict[SortKey, str] = {
    SortKey.NONE: "None",
    SortKey.DUE: "Due date",
    SortKey.PRIORITY: "Priority",
    SortKey.TAG: "Tag",
    SortKey.NEXT: "Next (recommended)",
}
