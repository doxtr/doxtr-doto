"""Jinja2 template loader for doto node rendering.

Templates are loaded from:
  1. Project's _doto/templates/html/ directory (user overrides)
  2. Extension's templates/html/ directory (bundled defaults)

This allows users to override individual templates without
modifying the extension source.

Usage:
    from doxtr_doto.template_loader import render_template
    
    html = render_template("doto.html", {
        "task_id": "TASK-001",
        "title": "My task",
        ...
    }, srcdir="/path/to/docs")

If Jinja2 is not installed, the module falls back to Python-based
rendering functions that produce equivalent output.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

# Check Jinja2 availability at import time
try:
    import jinja2
    JINJA2_AVAILABLE = True
except ImportError:
    jinja2 = None  # type: ignore[assignment]
    JINJA2_AVAILABLE = False

if TYPE_CHECKING:
    from jinja2 import Environment


# Type alias for fallback renderers
FallbackRenderer = Callable[[dict[str, Any]], str]

# Registry of fallback renderers (populated by _register_fallback_renderers)
_FALLBACK_RENDERERS: dict[str, FallbackRenderer] = {}


def _escape_id_filter(value: str) -> str:
    """Jinja filter: sanitize a string for use as an HTML id."""
    from doxtr_doto.utils import sanitize_html_id
    return sanitize_html_id(value)


def _row_classes_filter(task: Any) -> str:
    """Jinja filter: get CSS classes for a task row.
    
    Uses DotoTask.css_classes() if available, otherwise falls back
    to computing classes from priority and status attributes.
    """
    # Use the css_classes() method if available (DotoTask objects)
    if hasattr(task, 'css_classes') and callable(task.css_classes):
        # Get classes without 'doto' base class (templates add their own base)
        classes = task.css_classes()
        # Filter out 'doto' and 'doto-overdue' since templates handle those separately
        return ' '.join(c for c in classes if c not in ('doto', 'doto-overdue'))
    
    # Fallback for non-DotoTask objects
    from doxtr_doto.constants import PRIORITY_CLASSES, STATUS_CLASSES
    
    priority_class = PRIORITY_CLASSES.get(getattr(task, 'priority', ''), '')
    status_class = STATUS_CLASSES.get(getattr(task, 'status', ''), '')
    
    classes = [c for c in [priority_class, status_class] if c]
    return ' '.join(classes)


def _column_value_filter(task: Any, column: str) -> str:
    """Jinja filter: get the display value for a task column."""
    from doxtr_doto.utils import format_date_display
    
    if column == "id":
        return task.id
    elif column == "title":
        return task.title
    elif column == "priority":
        return task.priority
    elif column == "status":
        return task.status
    elif column == "assignee":
        return task.assignee or ""
    elif column == "due":
        return format_date_display(task.due)
    elif column == "tags":
        return ", ".join(task.tags) if task.tags else ""
    elif column == "created":
        return format_date_display(task.created) if task.created else ""
    elif column == "updated":
        return format_date_display(task.updated) if task.updated else ""
    elif column == "depends-on":
        return ", ".join(task.depends_on) if task.depends_on else ""
    elif column == "progress":
        progress = getattr(task, 'progress', None)
        return f"{progress}%" if progress is not None else ""
    return ""


def _is_overdue_test(task: Any) -> bool:
    """Jinja test: check if a task is overdue."""
    if hasattr(task, 'is_overdue'):
        if callable(task.is_overdue):
            return task.is_overdue()
        return task.is_overdue
    return False


@lru_cache(maxsize=8)
def _get_environment(template_dirs: tuple[Path, ...]) -> "Environment":
    """Build and cache a Jinja2 Environment for the given search path.
    
    Args:
        template_dirs: Tuple of template directories to search (must be tuple for hashability).
        
    Returns:
        Configured Jinja2 Environment.
    """
    if not JINJA2_AVAILABLE:
        raise RuntimeError("Jinja2 is not installed")
    
    loader = jinja2.FileSystemLoader(
        [str(d) for d in template_dirs],
        followlinks=False,
    )
    env = jinja2.Environment(
        loader=loader,
        autoescape=jinja2.select_autoescape(["html", "xml"]),
        keep_trailing_newline=True,
    )
    
    # Register doto-specific filters
    env.filters["escape_id"] = _escape_id_filter
    env.filters["row_classes"] = _row_classes_filter
    env.filters["column_value"] = _column_value_filter
    
    # Register doto-specific tests
    env.tests["overdue"] = _is_overdue_test
    
    return env


def get_template_dirs(srcdir: str | Path | None = None) -> tuple[Path, ...]:
    """Return ordered template search path.

    Priority:
    1. Project's _doto/templates/html/ (if srcdir provided and exists)
    2. Extension's bundled templates/html/
    
    Args:
        srcdir: Sphinx source directory for project overrides. If None,
                only bundled templates are available.
    
    Returns:
        Tuple of Path objects for template directories, in search order.
    """
    dirs: list[Path] = []

    if srcdir:
        project_tmpl = Path(srcdir) / "_doto" / "templates" / "html"
        if project_tmpl.is_dir():
            dirs.append(project_tmpl)

    bundled = Path(__file__).parent / "templates" / "html"
    if bundled.is_dir():
        dirs.append(bundled)

    return tuple(dirs)


def render_template(
    template_name: str,
    context: dict[str, Any],
    srcdir: str | Path | None = None,
) -> str:
    """Render a named template with the given context.

    Falls back to a minimal Python-based renderer if Jinja2 is not installed
    or the template is not found.

    Args:
        template_name: Template file name (e.g., "doto.html", "doto-list-table.html").
        context: Template variables dictionary.
        srcdir: Sphinx source directory for project overrides.

    Returns:
        Rendered HTML string.
        
    Example:
        >>> html = render_template("doto.html", {
        ...     "task_id": "TASK-001",
        ...     "title": "Fix bug",
        ...     "priority": "high",
        ...     "status": "open",
        ...     "classes": "doto doto-priority-high",
        ... })
    """
    if JINJA2_AVAILABLE:
        dirs = get_template_dirs(srcdir)
        if dirs:
            env = _get_environment(dirs)
            try:
                template = env.get_template(template_name)
                return template.render(**context)
            except jinja2.TemplateNotFound:
                pass  # Fall through to fallback
    
    # Jinja2 not available or template not found — use Python fallback
    return _fallback_render(template_name, context)


def template_exists(template_name: str, srcdir: str | Path | None = None) -> bool:
    """Check if a template exists in the search path.
    
    Args:
        template_name: Template file name to check.
        srcdir: Sphinx source directory for project overrides.
        
    Returns:
        True if template exists, False otherwise.
    """
    dirs = get_template_dirs(srcdir)
    for d in dirs:
        if (d / template_name).is_file():
            return True
    return False


def clear_template_cache() -> None:
    """Clear the template environment cache.
    
    Useful for testing or when template directories change.
    """
    _get_environment.cache_clear()


def _fallback_render(template_name: str, context: dict[str, Any]) -> str:
    """Minimal Python-based fallback renderer used when Jinja2 is absent.
    
    Args:
        template_name: Template file name.
        context: Template variables dictionary.
        
    Returns:
        Rendered HTML string, or empty string if no fallback exists.
    """
    # Ensure fallback renderers are registered
    if not _FALLBACK_RENDERERS:
        _register_fallback_renderers()
    
    renderer = _FALLBACK_RENDERERS.get(template_name)
    if renderer:
        return renderer(context)
    return ""


def _register_fallback_renderers() -> None:
    """Register all fallback renderers for Python-based template rendering."""
    _FALLBACK_RENDERERS["doto.html"] = _fallback_render_doto
    _FALLBACK_RENDERERS["doto-list-table.html"] = _fallback_render_table
    _FALLBACK_RENDERERS["doto-list-cards.html"] = _fallback_render_cards
    _FALLBACK_RENDERERS["doto-list-simple.html"] = _fallback_render_list


def _escape_html(value: Any) -> str:
    """Escape HTML content."""
    from doxtr_doto.utils import escape_html_content
    return escape_html_content(value)


def _escape_attr(value: Any) -> str:
    """Escape HTML attribute."""
    from doxtr_doto.utils import escape_html_attr
    return escape_html_attr(value)


def _fallback_render_doto(ctx: dict[str, Any]) -> str:
    """Fallback renderer for doto.html (single task)."""
    from doxtr_doto.utils import sanitize_html_id
    
    task_id = sanitize_html_id(ctx.get("task_id", ""))
    title = _escape_html(ctx.get("title", ""))
    priority = _escape_html(ctx.get("priority", "medium"))
    status = _escape_html(ctx.get("status", "open"))
    assignee = ctx.get("assignee", "")
    due = ctx.get("due", "")
    tags = ctx.get("tags", [])
    progress = ctx.get("progress")
    is_overdue = ctx.get("is_overdue", False)
    classes = _escape_attr(ctx.get("classes", "doto"))
    
    parts = [f'<div class="{classes}" id="{task_id}">']
    
    # Header
    parts.append('  <div class="doto-header">')
    parts.append(f'    <span class="doto-id">{_escape_html(task_id)}</span>')
    parts.append(f'    <span class="doto-title">{title}</span>')
    parts.append(f'    <span class="doto-priority">{priority}</span>')
    if status:
        parts.append(f'    <span class="doto-status">{status}</span>')
    parts.append('  </div>')
    
    # Meta
    parts.append('  <div class="doto-meta">')
    if assignee:
        parts.append(f'    <span class="doto-assignee">{_escape_html(assignee)}</span>')
    if due:
        due_class = "doto-due doto-overdue" if is_overdue else "doto-due"
        parts.append(f'    <span class="{due_class}">{_escape_html(due)}</span>')
    if tags:
        parts.append('    <span class="doto-tags">')
        for tag in tags:
            parts.append(f'      <span class="doto-tag">{_escape_html(tag)}</span>')
        parts.append('    </span>')
    if progress is not None:
        progress_int = int(progress)
        parts.append(f'    <div class="doto-progress" title="{progress_int}% complete">')
        parts.append(f'      <div class="doto-progress-bar" style="width:{progress_int}%"></div>')
        parts.append('    </div>')
    parts.append('  </div>')
    
    # Body placeholder (Sphinx will render children here)
    parts.append('  <div class="doto-body">')
    parts.append('  </div>')
    parts.append('</div>')
    
    return '\n'.join(parts) + '\n'


def _fallback_render_table(ctx: dict[str, Any]) -> str:
    """Fallback renderer for doto-list-table.html."""
    from doxtr_doto.fields import COLUMN_LABELS
    from doxtr_doto.utils import format_date_display
    
    tasks = ctx.get("tasks", [])
    columns = ctx.get("columns", ["id", "title", "priority", "status"])
    column_labels = ctx.get("column_labels", COLUMN_LABELS)
    
    parts = ['<table class="doto-table">']
    
    # Header
    parts.append('<thead><tr>')
    for col in columns:
        label = column_labels.get(col, col.title())
        parts.append(f'<th>{_escape_html(label)}</th>')
    parts.append('</tr></thead>')
    
    # Body
    parts.append('<tbody>')
    for task in tasks:
        # Use css_classes() method if available
        if hasattr(task, 'css_classes') and callable(task.css_classes):
            # Get classes without 'doto' base (table rows don't need it)
            classes = task.css_classes()
            row_class = ' '.join(c for c in classes if c != 'doto')
        else:
            # Fallback for non-DotoTask objects
            from doxtr_doto.constants import PRIORITY_CLASSES, STATUS_CLASSES
            priority_class = PRIORITY_CLASSES.get(task.priority, "")
            status_class = STATUS_CLASSES.get(task.status, "")
            row_class = f"{priority_class} {status_class}".strip()
            is_overdue = task.is_overdue() if callable(getattr(task, 'is_overdue', None)) else getattr(task, 'is_overdue', False)
            if is_overdue:
                row_class += " doto-overdue"
        
        parts.append(f'<tr class="{_escape_attr(row_class)}">')
        for col in columns:
            value = _column_value_filter(task, col)
            cell_class = f"doto-col-{col}"
            parts.append(f'<td class="{_escape_attr(cell_class)}">{_escape_html(value)}</td>')
        parts.append('</tr>')
    parts.append('</tbody>')
    parts.append('</table>')
    
    return '\n'.join(parts) + '\n'


def _fallback_render_cards(ctx: dict[str, Any]) -> str:
    """Fallback renderer for doto-list-cards.html."""
    from doxtr_doto.utils import format_date_display
    
    tasks = ctx.get("tasks", [])
    parts = []
    
    for task in tasks:
        # Use css_classes() method if available
        if hasattr(task, 'css_classes') and callable(task.css_classes):
            classes = task.css_classes(extra=["doto-card"])
            # Remove 'doto' base class since cards use 'doto-card' as base
            classes = [c for c in classes if c != 'doto']
        else:
            # Fallback for non-DotoTask objects
            from doxtr_doto.constants import PRIORITY_CLASSES, STATUS_CLASSES
            priority_class = PRIORITY_CLASSES.get(task.priority, "")
            status_class = STATUS_CLASSES.get(task.status, "")
            classes = ["doto-card", priority_class, status_class]
            is_overdue = task.is_overdue() if callable(getattr(task, 'is_overdue', None)) else getattr(task, 'is_overdue', False)
            if is_overdue:
                classes.append("doto-overdue")
        
        class_attr = _escape_attr(" ".join(c for c in classes if c))
        parts.append(f'<div class="{class_attr}">')
        parts.append('<div class="doto-card-header">')
        parts.append(f'<span class="doto-card-id">{_escape_html(task.id)}</span>')
        parts.append(f'<span class="doto-card-priority">{_escape_html(task.priority)}</span>')
        parts.append('</div>')
        parts.append(f'<div class="doto-card-title">{_escape_html(task.title)}</div>')
        parts.append('<div class="doto-card-meta">')
        if task.assignee:
            parts.append(f'<span class="doto-card-assignee">{_escape_html(task.assignee)}</span>')
        if task.due:
            due_str = format_date_display(task.due)
            parts.append(f'<span class="doto-card-due">{_escape_html(due_str)}</span>')
        parts.append(f'<span class="doto-card-status">{_escape_html(task.status)}</span>')
        parts.append('</div>')
        parts.append('</div>')
    
    return '\n'.join(parts) + '\n'


def _fallback_render_list(ctx: dict[str, Any]) -> str:
    """Fallback renderer for doto-list-simple.html."""
    tasks = ctx.get("tasks", [])
    parts = ['<ul class="doto-task-list">']
    
    for task in tasks:
        # Use css_classes() method if available
        if hasattr(task, 'css_classes') and callable(task.css_classes):
            classes = task.css_classes(extra=["doto-list-item"])
            # Remove 'doto' base class since list items use 'doto-list-item' as base
            classes = [c for c in classes if c != 'doto']
        else:
            # Fallback for non-DotoTask objects
            from doxtr_doto.constants import PRIORITY_CLASSES, STATUS_CLASSES
            priority_class = PRIORITY_CLASSES.get(task.priority, "")
            status_class = STATUS_CLASSES.get(task.status, "")
            classes = ["doto-list-item", priority_class, status_class]
            is_overdue = task.is_overdue() if callable(getattr(task, 'is_overdue', None)) else getattr(task, 'is_overdue', False)
            if is_overdue:
                classes.append("doto-overdue")
        
        class_attr = _escape_attr(" ".join(c for c in classes if c))
        parts.append(f'<li class="{class_attr}">')
        parts.append(f'<span class="doto-list-id">{_escape_html(task.id)}</span> ')
        parts.append(f'<span class="doto-list-title">{_escape_html(task.title)}</span> ')
        parts.append(f'<span class="doto-list-priority">[{_escape_html(task.priority)}]</span> ')
        parts.append(f'<span class="doto-list-status">({_escape_html(task.status)})</span>')
        if task.assignee:
            parts.append(f' <span class="doto-list-assignee">@{_escape_html(task.assignee)}</span>')
        parts.append('</li>')
    
    parts.append('</ul>')
    
    return '\n'.join(parts) + '\n'
