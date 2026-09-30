"""Task collector for gathering doto tasks across documents.

This module provides the core task collection infrastructure for the doxtr_doto
extension, including:

- DotoTask: Dataclass representing a single task with all metadata
- DotoEnvironment: Storage container for task data in Sphinx environment
- DotoCollector: Sphinx EnvironmentCollector for gathering tasks from documents
- filter_tasks: Filtering and sorting utility for task queries (with caching)
- invalidate_filter_cache: Clear the filter cache when task data changes
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from docutils import nodes
from sphinx.environment.collectors import EnvironmentCollector

from doxtr_doto.constants import (
    DEFAULT_PRIORITY,
    DEFAULT_STATUS,
    DONE_STATUS,
    PRIORITY_ORDER,
    STATUS_ORDER,
)
from doxtr_doto.date_utils import DotoDate
from doxtr_doto.enums import TaskSource
from doxtr_doto.query import DisplayOptions, TaskFilter

if TYPE_CHECKING:
    from sphinx.application import Sphinx
    from sphinx.builders import Builder
    from sphinx.environment import BuildEnvironment

__all__ = [
    "DotoTask",
    "DotoEnvironment",
    "get_doto_env",
    "DotoCollector",
    "purge_doto_data",
    "merge_doto_data",
    "filter_tasks",
    "invalidate_filter_cache",
]


@dataclass
class DotoTask:
    """Represents a single doto task.
    
    This dataclass holds all metadata for a task, including identification,
    scheduling, and tracking information. Tasks can originate from RST files,
    JSON storage, or be created through the CLI.
    
    Attributes:
        id: Unique task identifier.
        title: Human-readable task title.
        docname: Source document name (for RST-originated tasks).
        lineno: Line number in source document.
        assignee: Person assigned to the task.
        priority: Task priority level (low, medium, high, critical).
        status: Task status (open, in-progress, blocked, done).
        due: Due date in ISO format (YYYY-MM-DD).
        tags: List of tags for categorization.
        depends_on: List of task IDs this task depends on.
        body: Extended task description/notes.
        content_nodes: Docutils nodes for rendered content.
        created: Timestamp when task was created.
        updated: Timestamp when task was last modified.
        archived: Whether task has been archived.
        archived_on: Timestamp when task was archived.
        source: Origin of task data ('rst', 'json', or 'merged').
    """
    
    id: str
    title: str
    docname: str | None = None
    lineno: int | None = None
    assignee: str | None = None
    priority: str = DEFAULT_PRIORITY
    status: str = DEFAULT_STATUS
    due: str | None = None  # ISO format YYYY-MM-DD
    tags: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    body: str = ""
    content_nodes: list[nodes.Node] = field(default_factory=list)
    created: datetime | None = None
    updated: datetime | None = None
    archived: bool = False
    archived_on: datetime | None = None
    progress: int | None = None  # 0-100 percent complete; None = not set
    source: TaskSource = TaskSource.RST
    
    def __post_init__(self) -> None:
        """Normalize date fields after initialization.
        
        Ensures the due date is in consistent ISO format (YYYY-MM-DD).
        """
        from doxtr_doto.utils import normalize_date
        
        if self.due is not None:
            try:
                self.due = normalize_date(self.due)
            except (ValueError, TypeError):
                # Keep original value if normalization fails
                pass
    
    @property
    def due_date(self) -> date | None:
        """Get due date as a date object.
        
        Returns:
            Parsed date object, or None if due is not set or invalid.
        """
        from doxtr_doto.utils import parse_date_safe
        return parse_date_safe(self.due)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert task to dictionary for JSON serialization."""
        return {
            "title": self.title,
            "assignee": self.assignee,
            "priority": self.priority,
            "status": self.status,
            "due": self.due,  # Already ISO format string
            "tags": self.tags,
            "depends_on": self.depends_on,
            "body": self.body,
            "progress": self.progress,
            "created": self.created.isoformat() if self.created else None,
            "updated": self.updated.isoformat() if self.updated else None,
            "archived": self.archived,
            "archived_on": self.archived_on.isoformat() if self.archived_on else None,
        }
    
    @classmethod
    def from_dict(cls, task_id: str, data: dict[str, Any]) -> DotoTask:
        """Create task from dictionary."""
        return cls(
            id=task_id,
            title=data.get("title", ""),
            docname=data.get("_sync", {}).get("rst_file"),
            lineno=data.get("_sync", {}).get("rst_line"),
            assignee=data.get("assignee"),
            priority=data.get("priority", DEFAULT_PRIORITY),
            status=data.get("status", DEFAULT_STATUS),
            due=data.get("due"),  # Already ISO format string
            tags=data.get("tags", []),
            depends_on=data.get("depends_on", []),
            body=data.get("body", ""),
            progress=data.get("progress"),
            created=datetime.fromisoformat(data["created"]) if data.get("created") else None,
            updated=datetime.fromisoformat(data["updated"]) if data.get("updated") else None,
            archived=data.get("archived", False),
            archived_on=datetime.fromisoformat(data["archived_on"]) if data.get("archived_on") else None,
            source=TaskSource.JSON,
        )
    
    def is_overdue(self) -> bool:
        """Check if task is overdue.
        
        A task is considered overdue if it has a due date in the past
        and its status is not 'done'.
        
        Uses DotoDate for consistent date handling.
        
        Returns:
            True if task is overdue, False otherwise.
        """
        if self.due is None or self.status == DONE_STATUS:
            return False
        due_date = DotoDate.parse_safe(self.due)
        if due_date is None:
            return False
        return due_date.is_overdue()
    
    def to_sync_dict(self) -> dict[str, Any]:
        """Return a dict suitable for use in bidirectional sync.
        
        Includes the internal _rst_file and _rst_line keys that the
        sync algorithm needs, but not _sync/_git metadata.
        
        This method centralizes the logic for extracting task data for sync,
        avoiding feature envy where external code reaches into DotoTask internals.
        
        Returns:
            Dictionary with task fields ready for sync operations.
        """
        # Handle due date - could be date object or string
        due_str = None
        if self.due:
            if hasattr(self.due, 'isoformat'):
                due_str = self.due.isoformat()
            else:
                due_str = str(self.due)
        
        return {
            "id": self.id,
            "title": self.title,
            "assignee": self.assignee,
            "priority": self.priority,
            "status": self.status,
            "due": due_str,
            "tags": self.tags,
            "depends_on": self.depends_on,
            "body": self.body,
            "progress": self.progress,
            "_rst_file": self.docname or "",
            "_rst_line": self.lineno,
        }
    
    def css_classes(self, extra: list[str] | None = None) -> list[str]:
        """Return CSS classes for this task's priority, status, and overdue state.
        
        This method centralizes CSS class generation, avoiding duplicate code
        across multiple render functions in nodes.py and templates.
        
        Args:
            extra: Optional list of additional CSS classes to include.
            
        Returns:
            List of CSS class names (empty strings filtered out).
            
        Example:
            >>> task = DotoTask(id="T-1", title="Test", priority="high", status="open")
            >>> task.css_classes()
            ['doto', 'doto-priority-high', 'doto-status-open']
            >>> task.css_classes(extra=["doto-card"])
            ['doto', 'doto-priority-high', 'doto-status-open', 'doto-card']
        """
        from doxtr_doto.constants import PRIORITY_CLASSES, STATUS_CLASSES
        
        classes = [
            "doto",
            PRIORITY_CLASSES.get(self.priority, ""),
            STATUS_CLASSES.get(self.status, ""),
        ]
        if self.is_overdue():
            classes.append("doto-overdue")
        if extra:
            classes.extend(extra)
        return [c for c in classes if c]


@dataclass
class DotoEnvironment:
    """Storage for doto data in Sphinx environment."""
    
    all_tasks: dict[str, DotoTask] = field(default_factory=dict)
    tasks_by_doc: dict[str, list[str]] = field(default_factory=dict)
    pending_rst_updates: dict[str, dict[str, Any]] = field(default_factory=dict)
    conflicts: list[Any] = field(default_factory=list)


def get_doto_env(env: BuildEnvironment) -> DotoEnvironment:
    """Get or create doto environment data.
    
    Type-safe accessor for the doto data stored on the Sphinx
    BuildEnvironment. Creates a new DotoEnvironment if one
    doesn't exist.
    
    Args:
        env: Sphinx BuildEnvironment.
        
    Returns:
        DotoEnvironment instance.
    """
    if not hasattr(env, "doto_data"):
        env.doto_data = DotoEnvironment()
    return env.doto_data


class DotoCollector(EnvironmentCollector):
    """Collect doto tasks from documents."""
    
    def clear_doc(self, app: Sphinx, env: BuildEnvironment, docname: str) -> None:
        """Clear tasks from a specific document."""
        doto_env = get_doto_env(env)
        
        # Remove tasks belonging to this document
        if docname in doto_env.tasks_by_doc:
            for task_id in doto_env.tasks_by_doc[docname]:
                if task_id in doto_env.all_tasks:
                    del doto_env.all_tasks[task_id]
            del doto_env.tasks_by_doc[docname]
            # Invalidate filter cache since task data changed
            invalidate_filter_cache()
    
    def merge_other(
        self,
        app: Sphinx,
        env: BuildEnvironment,
        docnames: set[str],
        other: BuildEnvironment,
    ) -> None:
        """Merge collected tasks from parallel builds."""
        doto_env = get_doto_env(env)
        other_env = get_doto_env(other)
        
        # Merge tasks from other environment
        merged_any = False
        for task_id, task in other_env.all_tasks.items():
            if task.docname in docnames:
                doto_env.all_tasks[task_id] = task
                merged_any = True
        
        # Merge tasks_by_doc
        for docname, task_ids in other_env.tasks_by_doc.items():
            if docname in docnames:
                doto_env.tasks_by_doc[docname] = task_ids
        
        # Invalidate filter cache if any tasks were merged
        if merged_any:
            invalidate_filter_cache()
    
    def process_doc(self, app: Sphinx, doctree: nodes.document) -> None:
        """Process a document and collect tasks."""
        from doxtr_doto.nodes import doto_node
        from doxtr_doto.config import get_config
        
        env = app.env
        if env is None:
            return
            
        doto_env = get_doto_env(env)
        docname = env.docname
        
        # Check if TOC rendering is enabled
        render_in_toc = get_config(app, "render_in_toc")
        
        # Find all doto nodes in the document
        task_ids = []
        for node in doctree.findall(doto_node):
            task_id = node.get("task_id", "")
            if not task_id:
                continue
            
            task = DotoTask(
                id=task_id,
                title=node.get("title", ""),
                docname=docname,
                lineno=node.line,
                assignee=node.get("assignee"),
                priority=node.get("priority", DEFAULT_PRIORITY),
                status=node.get("status", DEFAULT_STATUS),
                due=node.get("due"),
                tags=node.get("tags", []),
                depends_on=node.get("depends_on", []),
                body=node.get("body", ""),
                progress=node.get("progress"),
                content_nodes=list(node.children),
                created=node.get("created"),
                updated=node.get("updated"),
                source=TaskSource.RST,
            )
            
            doto_env.all_tasks[task_id] = task
            task_ids.append(task_id)
            
            # Inject TOC entry if enabled
            if render_in_toc:
                _inject_toc_entry(doctree, node, task)
        
        if task_ids:
            doto_env.tasks_by_doc[docname] = task_ids
            # Invalidate filter cache since task data changed
            invalidate_filter_cache()


def _inject_toc_entry(
    doctree: nodes.document,
    task_node: nodes.Element,
    task: DotoTask,
) -> None:
    """Inject a lightweight section node so Sphinx includes the task in the TOC.

    The injected section is invisible in normal HTML output (zero-height anchor)
    but registers the task ID with Sphinx's TOC machinery.

    Args:
        doctree: The document tree being processed.
        task_node: The doto_node in the tree.
        task: The DotoTask metadata object.
    """
    # Create a section node with the task ID as its name/id
    section = nodes.section()
    section["ids"] = [task.id]
    section["names"] = [task.id]

    # Minimal title — displayed in TOC sidebar
    title_node = nodes.title(text=f"{task.id}: {task.title}")
    section += title_node

    # Insert immediately before the doto_node so the anchor lands correctly
    parent = task_node.parent
    if parent is not None:
        idx = parent.index(task_node)
        parent.insert(idx, section)


def purge_doto_data(app: Sphinx, env: BuildEnvironment, docname: str) -> None:
    """Purge doto data for a document (event handler)."""
    doto_env = get_doto_env(env)
    
    if docname in doto_env.tasks_by_doc:
        for task_id in doto_env.tasks_by_doc[docname]:
            if task_id in doto_env.all_tasks:
                del doto_env.all_tasks[task_id]
        del doto_env.tasks_by_doc[docname]
        # Invalidate filter cache since task data changed
        invalidate_filter_cache()


def merge_doto_data(
    app: Sphinx,
    env: BuildEnvironment,
    docnames: set[str],
    other: BuildEnvironment,
) -> None:
    """Merge doto data from parallel builds (event handler)."""
    doto_env = get_doto_env(env)
    other_env = get_doto_env(other)
    
    merged_any = False
    for task_id, task in other_env.all_tasks.items():
        if task.docname in docnames:
            doto_env.all_tasks[task_id] = task
            merged_any = True
    
    for docname, task_ids in other_env.tasks_by_doc.items():
        if docname in docnames:
            doto_env.tasks_by_doc[docname] = task_ids
    
    # Invalidate filter cache if any tasks were merged
    if merged_any:
        invalidate_filter_cache()


# Module-level cache for filter_tasks results
# Keyed on (tasks dict id, frozen filter state, frozen display state)
_filter_cache: dict[tuple, list["DotoTask"]] = {}


def _make_filter_cache_key(
    tasks_id: int,
    filters: TaskFilter,
    display: DisplayOptions,
) -> tuple:
    """Create a hashable cache key from filter and display state.
    
    The cache key incorporates:
    - The identity (id) of the tasks dictionary to detect when tasks change
    - All filter parameters in a canonical (sorted) form
    - All display parameters
    
    Args:
        tasks_id: The id() of the tasks dictionary.
        filters: TaskFilter object with filter configuration.
        display: DisplayOptions object with display configuration.
        
    Returns:
        A hashable tuple that uniquely identifies this query.
    """
    return (
        tasks_id,
        tuple(sorted(filters.assignee)),
        tuple(sorted(filters.priority)),
        tuple(sorted(filters.status)),
        tuple(sorted(filters.exclude_status)),
        tuple(sorted(filters.tags)),
        tuple(sorted(filters.depends_on)),
        filters.due_before,
        filters.due_after,
        filters.regex,
        display.format,
        tuple(display.sort),
        display.order,
        display.limit,
        display.show_archived,
        tuple(display.columns),
    )


def invalidate_filter_cache() -> None:
    """Clear the filter cache.
    
    Called when task data changes to ensure subsequent filter_tasks calls
    return fresh results. This should be called from:
    - DotoCollector.process_doc() after adding tasks
    - DotoCollector.clear_doc() after removing tasks
    - DotoCollector.merge_other() after merging tasks from parallel builds
    - purge_doto_data() event handler
    - merge_doto_data() event handler
    """
    _filter_cache.clear()


def filter_tasks(
    tasks: dict[str, DotoTask],
    filters: TaskFilter | dict[str, Any],
    display: DisplayOptions | dict[str, Any] | None = None,
) -> list[DotoTask]:
    """Filter and sort tasks based on filter and display configuration.
    
    Results are cached per build. The cache is keyed on the tasks dictionary
    identity and the frozen filter/display state. Cache is invalidated when
    task data changes.
    
    Args:
        tasks: Dictionary of all tasks keyed by task ID.
        filters: Filter configuration - either a TaskFilter object or a dictionary with keys:
            - assignee: list of assignees to include
            - priority: list of priorities to include
            - status: list of statuses to include
            - exclude_status: list of statuses to exclude
            - tags: list of tags (task must have at least one)
            - depends_on: list of task IDs (task must depend on at least one)
            - due_before: ISO date string (task due before this date)
            - due_after: ISO date string (task due after this date)
            - regex: regex pattern to match against task title
            - regex_compiled: pre-compiled regex pattern (optional, for performance)
        display: Display configuration - either a DisplayOptions object or a dictionary with keys:
            - sort: list of fields to sort by
            - order: 'asc' or 'desc'
            - limit: maximum number of tasks to return
            - show_archived: whether to include archived tasks
            
    Returns:
        List of filtered and sorted DotoTask objects.
    """
    # Normalize to typed objects if plain dicts are passed (backward compat)
    # Also extract pre-compiled regex if present
    regex_compiled = None
    if isinstance(filters, dict):
        regex_compiled = filters.get("regex_compiled")
        filters = TaskFilter.from_dict(filters)
    if display is None:
        display = DisplayOptions()
    elif isinstance(display, dict):
        display = DisplayOptions.from_dict(display)
    
    # Check cache
    cache_key = _make_filter_cache_key(id(tasks), filters, display)
    if cache_key in _filter_cache:
        return _filter_cache[cache_key]
    
    # Perform actual filtering
    result = _filter_tasks_impl(tasks, filters, display, regex_compiled)
    
    # Store in cache
    _filter_cache[cache_key] = result
    return result


def _filter_tasks_impl(
    tasks: dict[str, DotoTask],
    filters: TaskFilter,
    display: DisplayOptions,
    regex_compiled: "re.Pattern[str] | None" = None,
) -> list[DotoTask]:
    """Internal implementation of task filtering and sorting.
    
    This function performs the actual filtering work. It is called by
    filter_tasks() after cache lookup.
    
    Args:
        tasks: Dictionary of all tasks keyed by task ID.
        filters: TaskFilter object with filter configuration.
        display: DisplayOptions object with display configuration.
        regex_compiled: Pre-compiled regex pattern (optional).
        
    Returns:
        List of filtered and sorted DotoTask objects.
    """
    from doxtr_doto.regex_utils import compile_safe, safe_match, RegexTimeoutError, UnsafePatternError
    
    result: list[DotoTask] = []
    regex_timeout_warned = False  # Track if we've already warned about timeout
    
    # Use pre-compiled regex pattern if available, otherwise compile safely
    regex_pattern = regex_compiled
    if regex_pattern is None and filters.regex:
        try:
            regex_pattern = compile_safe(filters.regex)
        except (UnsafePatternError, Exception):
            pass  # Invalid or unsafe regex, skip filtering by it
    
    for task in tasks.values():
        # Filter by archived status
        if not display.show_archived and task.archived:
            continue
        
        # Filter by assignee
        if filters.assignee:
            if task.assignee is None or task.assignee.lower() not in [
                a.lower() for a in filters.assignee
            ]:
                continue
        
        # Filter by priority
        if filters.priority:
            if task.priority.lower() not in [p.lower() for p in filters.priority]:
                continue
        
        # Filter by status
        if filters.status:
            if task.status.lower() not in [s.lower() for s in filters.status]:
                continue
        
        # Exclude by status
        if filters.exclude_status:
            if task.status.lower() in [s.lower() for s in filters.exclude_status]:
                continue
        
        # Filter by tags (task must have at least one matching tag)
        if filters.tags:
            task_tags_lower = [t.lower() for t in task.tags]
            filter_tags_lower = [t.lower() for t in filters.tags]
            if not any(t in task_tags_lower for t in filter_tags_lower):
                continue
        
        # Filter by depends_on (task must depend on at least one)
        if filters.depends_on:
            if not any(d in task.depends_on for d in filters.depends_on):
                continue
        
        # Filter by due_before (using DotoDate for consistent handling)
        if filters.due_before:
            if task.due is None:
                continue
            task_due_d = DotoDate.parse_safe(task.due)
            due_before_d = DotoDate.parse_safe(filters.due_before)
            if task_due_d is None or due_before_d is None:
                continue
            if not task_due_d.is_before(due_before_d):
                continue
        
        # Filter by due_after (using DotoDate for consistent handling)
        if filters.due_after:
            if task.due is None:
                continue
            task_due_d = DotoDate.parse_safe(task.due)
            due_after_d = DotoDate.parse_safe(filters.due_after)
            if task_due_d is None or due_after_d is None:
                continue
            if not task_due_d.is_after(due_after_d):
                continue
        
        # Filter by regex pattern on title (using safe_match for timeout protection)
        if regex_pattern is not None:
            try:
                if not safe_match(regex_pattern, task.title):
                    continue
            except RegexTimeoutError:
                # Log warning once, then skip regex filtering for remaining tasks
                if not regex_timeout_warned:
                    import logging
                    logging.getLogger(__name__).warning(
                        "Regex match timed out; skipping regex filter for remaining tasks"
                    )
                    regex_timeout_warned = True
                # Don't filter out this task since we couldn't check it
                pass
        
        result.append(task)
    
    # Sort tasks
    sort_fields = display.sort
    order = display.order
    reverse = order == "desc"
    
    def sort_key(task: DotoTask) -> tuple:
        keys = []
        for field in sort_fields:
            if field == "priority":
                keys.append(PRIORITY_ORDER.get(task.priority.lower(), 0))
            elif field == "status":
                keys.append(STATUS_ORDER.get(task.status.lower(), 0))
            elif field == "due":
                # None dates sort last (or first depending on order)
                if task.due is None:
                    keys.append("9999-12-31" if not reverse else "0000-01-01")
                else:
                    # task.due is ISO string, use directly for string comparison
                    keys.append(task.due if isinstance(task.due, str) else task.due.isoformat())
            elif field == "created":
                if task.created is None:
                    keys.append("9999-12-31T23:59:59" if not reverse else "0000-01-01T00:00:00")
                else:
                    keys.append(task.created.isoformat() if hasattr(task.created, 'isoformat') else str(task.created))
            elif field == "assignee":
                keys.append(task.assignee or "")
            elif field == "title":
                keys.append(task.title.lower())
            elif field == "id":
                keys.append(task.id)
        return tuple(keys)
    
    result.sort(key=sort_key, reverse=reverse)
    
    # Apply limit
    if display.limit is not None and display.limit > 0:
        result = result[:display.limit]
    
    return result
