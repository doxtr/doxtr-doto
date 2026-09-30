"""The doto-list directive for displaying filtered task lists."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from docutils import nodes
from docutils.parsers.rst import directives
from sphinx.util.docutils import SphinxDirective

from doxtr_doto.constants import VALID_LIST_ICON_MODES
from doxtr_doto.enums import ListFormat
from doxtr_doto.nodes import doto_list_node
from doxtr_doto.query import DisplayOptions, TaskFilter
from doxtr_doto.utils import parse_boolean, parse_date, parse_list

if TYPE_CHECKING:
    from sphinx.application import Sphinx


# Valid sort fields
VALID_SORT_FIELDS = frozenset({
    "priority", "due", "status", "assignee", "created", "title", "id"
})

# Valid format types
VALID_FORMATS = frozenset(e.value for e in ListFormat)

# Valid order values
VALID_ORDERS = frozenset({"asc", "desc"})


def parse_int(value: str) -> int | None:
    """Parse an integer value.
    
    Args:
        value: String to parse as integer.
        
    Returns:
        Integer value or None if empty.
        
    Raises:
        ValueError: If value is not a valid integer.
    """
    if not value or not value.strip():
        return None
    try:
        result = int(value.strip())
        if result < 0:
            raise ValueError("Value must be non-negative")
        return result
    except ValueError as e:
        raise ValueError(f"Invalid integer value '{value}'") from e


def validate_sort_fields(value: str) -> list[str]:
    """Validate sort field names.
    
    Args:
        value: Comma-separated sort fields.
        
    Returns:
        List of validated sort field names.
        
    Raises:
        ValueError: If any sort field is invalid.
    """
    fields = parse_list(value)
    for field in fields:
        if field not in VALID_SORT_FIELDS:
            raise ValueError(
                f"Invalid sort field '{field}'. "
                f"Must be one of: {', '.join(sorted(VALID_SORT_FIELDS))}"
            )
    return fields


def validate_format(value: str) -> str:
    """Validate display format.
    
    Args:
        value: Format string to validate.
        
    Returns:
        Validated format string.
        
    Raises:
        ValueError: If format is not valid.
    """
    normalized = value.strip().lower()
    if normalized not in VALID_FORMATS:
        raise ValueError(
            f"Invalid format '{value}'. "
            f"Must be one of: {', '.join(sorted(VALID_FORMATS))}"
        )
    return normalized


def validate_order(value: str) -> str:
    """Validate sort order.
    
    Args:
        value: Order string to validate.
        
    Returns:
        Validated order string.
        
    Raises:
        ValueError: If order is not valid.
    """
    normalized = value.strip().lower()
    if normalized not in VALID_ORDERS:
        raise ValueError(
            f"Invalid order '{value}'. Must be 'asc' or 'desc'."
        )
    return normalized


class DotoListDirective(SphinxDirective):
    """Directive for displaying a filtered list of tasks.
    
    Usage::
    
        .. doto-list::
           :assignee: alice, bob
           :priority: high, critical
           :status: open, in-progress
           :tags: security
           :due-before: 2026-09-01
           :due-after: 2026-07-01
           :sort: priority, due
           :order: desc
           :limit: 20
           :format: table
           :show-archived: false
           :columns: id, title, assignee, due
    """
    
    has_content: ClassVar[bool] = False
    required_arguments: ClassVar[int] = 0
    optional_arguments: ClassVar[int] = 0
    
    option_spec: ClassVar[dict[str, object]] = {
        # Filter options
        "assignee": directives.unchanged,
        "priority": directives.unchanged,
        "status": directives.unchanged,
        "tags": directives.unchanged,
        "due-before": directives.unchanged,
        "due-after": directives.unchanged,
        "depends-on": directives.unchanged,
        "regex": directives.unchanged,
        "exclude-status": directives.unchanged,
        # Display options
        "sort": directives.unchanged,
        "order": directives.unchanged,
        "limit": directives.unchanged,
        "format": directives.unchanged,
        "show-archived": directives.unchanged,
        "columns": directives.unchanged,
        # Per-directive override of doto_list_icon_mode (Feature 5):
        # "icon" | "icon-text" | "text".
        "icon-mode": directives.unchanged,
    }
    
    def run(self) -> list[nodes.Node]:
        """Process the directive and return document nodes.
        
        Returns:
            List containing the doto_list_node with filter configuration.
        """
        # Parse filter options
        filters = self._parse_filters()
        
        # Parse display options
        display = self._parse_display_options()

        # Parse per-directive icon-mode override (Feature 5). Validated here so
        # a bad value is reported at parse time; None means "use config".
        icon_mode = self._parse_icon_mode()

        # Create the node with filter and display configuration
        node = doto_list_node(
            "",
            filters=filters,
            display=display,
            icon_mode=icon_mode,
            docname=self.env.docname,
            lineno=self.lineno,
        )
        
        # Set source info for better error messages
        node.source = self.get_source_info()[0]
        node.line = self.lineno
        
        return [node]
    
    def _parse_icon_mode(self) -> str | None:
        """Parse and validate the per-directive ``:icon-mode:`` override.

        Returns:
            The validated icon mode (``icon`` | ``icon-text`` | ``text``), or
            None when the option is absent (renderers then use the
            ``doto_list_icon_mode`` config default).

        Raises:
            self.error: If the supplied mode is not a recognized value.
        """
        if "icon-mode" not in self.options:
            return None
        mode = self.options["icon-mode"].strip().lower()
        if mode not in VALID_LIST_ICON_MODES:
            raise self.error(
                f"Invalid icon-mode '{mode}'. "
                f"Must be one of: {', '.join(sorted(VALID_LIST_ICON_MODES))}"
            )
        return mode

    def _parse_filters(self) -> dict[str, Any]:
        """Parse and validate filter options.
        
        Returns:
            Dictionary with filter configuration including:
            - All TaskFilter fields
            - regex_compiled: Pre-compiled regex pattern (if regex specified)
        """
        from doxtr_doto.config import get_config
        
        # Get valid values from config
        valid_statuses = set(get_config(self.env.app, "statuses"))
        valid_priorities = set(get_config(self.env.app, "priorities"))
        
        # Initialize filter fields
        assignee: list[str] = []
        priority: list[str] = []
        status: list[str] = []
        exclude_status: list[str] = []
        tags: list[str] = []
        depends_on: list[str] = []
        due_before: str | None = None
        due_after: str | None = None
        regex: str | None = None
        regex_compiled: Any = None  # Pre-compiled regex pattern
        
        # Parse list filters
        if "assignee" in self.options:
            assignee = parse_list(self.options["assignee"])
        
        if "priority" in self.options:
            priorities = parse_list(self.options["priority"])
            # Validate priority values against config
            for p in priorities:
                if p.lower() not in valid_priorities:
                    raise self.error(
                        f"Invalid priority '{p}'. "
                        f"Must be one of: {', '.join(sorted(valid_priorities))}"
                    )
            priority = [p.lower() for p in priorities]
        
        if "status" in self.options:
            statuses = parse_list(self.options["status"])
            # Validate status values against config
            for s in statuses:
                if s.lower() not in valid_statuses:
                    raise self.error(
                        f"Invalid status '{s}'. "
                        f"Must be one of: {', '.join(sorted(valid_statuses))}"
                    )
            status = [s.lower() for s in statuses]
        
        if "exclude-status" in self.options:
            exclude_statuses = parse_list(self.options["exclude-status"])
            for s in exclude_statuses:
                if s.lower() not in valid_statuses:
                    raise self.error(
                        f"Invalid exclude-status '{s}'. "
                        f"Must be one of: {', '.join(sorted(valid_statuses))}"
                    )
            exclude_status = [s.lower() for s in exclude_statuses]
        
        if "tags" in self.options:
            tags = parse_list(self.options["tags"])
        
        if "depends-on" in self.options:
            depends_on = parse_list(self.options["depends-on"])
        
        # Parse date filters
        if "due-before" in self.options:
            try:
                due_before_date = parse_date(self.options["due-before"])
                if due_before_date:
                    due_before = due_before_date.isoformat()
            except ValueError as e:
                raise self.error(f"Invalid due-before: {e}") from e
        
        if "due-after" in self.options:
            try:
                due_after_date = parse_date(self.options["due-after"])
                if due_after_date:
                    due_after = due_after_date.isoformat()
            except ValueError as e:
                raise self.error(f"Invalid due-after: {e}") from e
        
        # Parse regex filter
        if "regex" in self.options:
            regex_str = self.options["regex"].strip()
            if regex_str:
                # Validate and compile regex pattern at parse time using safe utilities
                # This rejects patterns that could cause ReDoS (catastrophic backtracking)
                # Compiled regex is picklable in Python 3.7+, so safe to store on node
                import re
                from doxtr_doto.regex_utils import compile_safe, UnsafePatternError
                try:
                    regex_compiled = compile_safe(regex_str)
                except UnsafePatternError as e:
                    raise self.error(str(e)) from e
                except re.error as e:
                    raise self.error(f"Invalid regex pattern: {e}") from e
                regex = regex_str
        
        # Return as dict to include compiled regex alongside TaskFilter fields
        # filter_tasks() accepts both TaskFilter objects and dicts
        return {
            "assignee": assignee,
            "priority": priority,
            "status": status,
            "exclude_status": exclude_status,
            "tags": tags,
            "depends_on": depends_on,
            "due_before": due_before,
            "due_after": due_after,
            "regex": regex,
            "regex_compiled": regex_compiled,  # Pre-compiled for performance
        }
    
    def _parse_display_options(self) -> DisplayOptions:
        """Parse and validate display options.
        
        Returns:
            DisplayOptions object with validated display configuration.
        """
        # Initialize with defaults
        sort_fields: list[str] = ["priority"]
        order: str = "desc"
        limit: int | None = None
        format_str: str = "list"
        show_archived: bool = False
        columns: list[str] = ["id", "title", "priority", "status"]
        
        # Parse sort fields
        if "sort" in self.options:
            try:
                sort_fields = validate_sort_fields(self.options["sort"])
            except ValueError as e:
                raise self.error(str(e)) from e
        
        # Parse order
        if "order" in self.options:
            try:
                order = validate_order(self.options["order"])
            except ValueError as e:
                raise self.error(str(e)) from e
        else:
            # Default order depends on sort field
            primary_sort = sort_fields[0] if sort_fields else "priority"
            if primary_sort in ("due", "created"):
                order = "asc"
            else:
                order = "desc"
        
        # Parse limit
        if "limit" in self.options:
            try:
                limit = parse_int(self.options["limit"])
            except ValueError as e:
                raise self.error(f"Invalid limit: {e}") from e
        
        # Parse format
        if "format" in self.options:
            try:
                format_str = validate_format(self.options["format"])
            except ValueError as e:
                raise self.error(str(e)) from e
        
        # Parse show-archived
        if "show-archived" in self.options:
            show_archived = parse_boolean(self.options["show-archived"])
        
        # Parse columns
        if "columns" in self.options:
            from doxtr_doto.fields import VALID_COLUMNS
            columns_raw = parse_list(self.options["columns"])
            # Validate column names against central field registry
            for col in columns_raw:
                if col.lower() not in VALID_COLUMNS:
                    raise self.error(
                        f"Invalid column '{col}'. "
                        f"Must be one of: {', '.join(sorted(VALID_COLUMNS))}"
                    )
            columns = [col.lower() for col in columns_raw]
        
        return DisplayOptions(
            format=format_str,
            sort=sort_fields,
            order=order,
            limit=limit,
            show_archived=show_archived,
            columns=columns,
        )


def setup(app: Sphinx) -> dict[str, object]:
    """Set up the doto-list directive.
    
    Args:
        app: Sphinx application instance.
        
    Returns:
        Extension metadata.
    """
    app.add_directive("doto-list", DotoListDirective)
    
    return {
        "version": "0.1.0",
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
