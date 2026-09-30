"""Typed filter and display option containers.

This module provides typed dataclasses for task filtering and display options,
replacing raw `dict[str, Any]` parameters with type-safe containers that prevent
typos in key names and enable IDE auto-complete.

Both classes support backward compatibility via `from_dict()` class methods,
allowing existing code that passes dictionaries to continue working.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TaskFilter:
    """Typed filter specification for task queries.

    All list fields use AND-across-fields, OR-within-field semantics.
    E.g., assignee=["alice","bob"] means "assigned to alice OR bob".

    Attributes:
        assignee: List of assignees to include (OR semantics).
        priority: List of priorities to include (OR semantics).
        status: List of statuses to include (OR semantics).
        exclude_status: List of statuses to exclude.
        tags: List of tags (task must have at least one matching tag).
        depends_on: List of task IDs (task must depend on at least one).
        due_before: ISO date string - include tasks due before this date.
        due_after: ISO date string - include tasks due after this date.
        regex: Regex pattern to match against task title.
    """

    assignee: list[str] = field(default_factory=list)
    priority: list[str] = field(default_factory=list)
    status: list[str] = field(default_factory=list)
    exclude_status: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    due_before: str | None = None  # ISO date string
    due_after: str | None = None  # ISO date string
    regex: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TaskFilter:
        """Create a TaskFilter from a dictionary.

        This method enables backward compatibility with code that passes
        filter parameters as dictionaries.

        Args:
            d: Dictionary with filter parameters. Unknown keys are ignored.

        Returns:
            TaskFilter instance with values from the dictionary.
        """
        return cls(
            assignee=d.get("assignee", []),
            priority=d.get("priority", []),
            status=d.get("status", []),
            exclude_status=d.get("exclude_status", []),
            tags=d.get("tags", []),
            depends_on=d.get("depends_on", []),
            due_before=d.get("due_before"),
            due_after=d.get("due_after"),
            regex=d.get("regex"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary, omitting empty/None values.

        Returns:
            Dictionary with non-empty filter values.
        """
        result: dict[str, Any] = {}
        if self.assignee:
            result["assignee"] = self.assignee
        if self.priority:
            result["priority"] = self.priority
        if self.status:
            result["status"] = self.status
        if self.exclude_status:
            result["exclude_status"] = self.exclude_status
        if self.tags:
            result["tags"] = self.tags
        if self.depends_on:
            result["depends_on"] = self.depends_on
        if self.due_before is not None:
            result["due_before"] = self.due_before
        if self.due_after is not None:
            result["due_after"] = self.due_after
        if self.regex is not None:
            result["regex"] = self.regex
        return result

    def is_empty(self) -> bool:
        """Check if all filter fields are empty/unset.

        Returns:
            True if no filter criteria are set.
        """
        return not any([
            self.assignee,
            self.priority,
            self.status,
            self.exclude_status,
            self.tags,
            self.depends_on,
            self.due_before,
            self.due_after,
            self.regex,
        ])


@dataclass
class DisplayOptions:
    """Typed display options for task list rendering.

    Attributes:
        format: Display format - "list", "table", or "cards".
        sort: List of fields to sort by (in order of precedence).
        order: Sort order - "asc" or "desc".
        limit: Maximum number of tasks to return (None for unlimited).
        show_archived: Whether to include archived tasks.
        columns: List of column names to display (for table format).
    """

    format: str = "list"  # "list" | "table" | "cards"
    sort: list[str] = field(default_factory=lambda: ["priority"])
    order: str = "desc"  # "asc" | "desc"
    limit: int | None = None
    show_archived: bool = False
    columns: list[str] = field(
        default_factory=lambda: ["id", "title", "priority", "status"]
    )

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DisplayOptions:
        """Create DisplayOptions from a dictionary.

        This method enables backward compatibility with code that passes
        display options as dictionaries.

        Args:
            d: Dictionary with display options. Unknown keys are ignored.

        Returns:
            DisplayOptions instance with values from the dictionary.
        """
        return cls(
            format=d.get("format", "list"),
            sort=d.get("sort", ["priority"]),
            order=d.get("order", "desc"),
            limit=d.get("limit"),
            show_archived=d.get("show_archived", False),
            columns=d.get("columns", ["id", "title", "priority", "status"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary.

        Returns:
            Dictionary with all display option values.
        """
        return {
            "format": self.format,
            "sort": self.sort,
            "order": self.order,
            "limit": self.limit,
            "show_archived": self.show_archived,
            "columns": self.columns,
        }
