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

from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

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
    if hasattr(task, "css_classes") and callable(task.css_classes):
        # Get classes without 'doto' base class (templates add their own base)
        classes = task.css_classes()
        # Filter out 'doto' and 'doto-overdue' since templates handle those separately
        return " ".join(c for c in classes if c not in ("doto", "doto-overdue"))

    # Fallback for non-DotoTask objects
    from doxtr_doto.constants import PRIORITY_CLASSES, STATUS_CLASSES

    priority_class = PRIORITY_CLASSES.get(getattr(task, "priority", ""), "")
    status_class = STATUS_CLASSES.get(getattr(task, "status", ""), "")

    classes = [c for c in [priority_class, status_class] if c]
    return " ".join(classes)


def _display_date_filter(value: Any) -> str:
    """Jinja filter: format a due/date value for display.

    Routes through the centralized ``utils.format_date_display`` so templates
    never emit the raw stored ISO string (e.g. ``2026-08-15T16:00``). This is
    the single display seam list templates should use for ``task.due`` so a
    child theme overriding only markup inherits consistent formatting without
    re-implementing parsing.
    """
    from doxtr_doto.utils import format_date_display

    return format_date_display(value)


def _column_value_filter(task: Any, column: str) -> str:
    """Jinja filter: get the display value for a task column."""
    from doxtr_doto.utils import format_date_display

    if column == "id":
        return str(task.id)
    elif column == "title":
        return str(task.title)
    elif column == "priority":
        return str(task.priority)
    elif column == "status":
        return str(task.status)
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
        progress = getattr(task, "progress", None)
        return f"{progress}%" if progress is not None else ""
    elif column == "estimate":
        from doxtr_doto.date_utils import format_duration_minutes

        return format_duration_minutes(getattr(task, "estimate", None))
    return ""


def _is_overdue_test(task: Any) -> bool:
    """Jinja test: check if a task is overdue."""
    if hasattr(task, "is_overdue"):
        if callable(task.is_overdue):
            return bool(task.is_overdue())
        return bool(task.is_overdue)
    return False


@lru_cache(maxsize=8)
def _get_environment(template_dirs: tuple[Path, ...]) -> Environment:
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
    env.filters["display_date"] = _display_date_filter

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
    _FALLBACK_RENDERERS["doto-list-kanban.html"] = _fallback_render_kanban
    _FALLBACK_RENDERERS["doto-list-calendar.html"] = _fallback_render_calendar
    _FALLBACK_RENDERERS["doto-list-email.html"] = _fallback_render_email
    _FALLBACK_RENDERERS["doto-archive.html"] = _fallback_render_archive


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
    assignee_href = ctx.get("assignee_href", "")
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
    parts.append("  </div>")

    # Meta
    parts.append('  <div class="doto-meta">')
    if assignee:
        if assignee_href:
            parts.append(
                f'    <span class="doto-assignee">'
                f'<a class="doto-assignee-link" href="{_escape_attr(assignee_href)}">'
                f"{_escape_html(assignee)}</a></span>"
            )
        else:
            parts.append(f'    <span class="doto-assignee">{_escape_html(assignee)}</span>')
    if due:
        due_class = "doto-due doto-overdue" if is_overdue else "doto-due"
        parts.append(f'    <span class="{due_class}">{_escape_html(due)}</span>')
    if tags:
        parts.append('    <span class="doto-tags">')
        for tag in tags:
            parts.append(f'      <span class="doto-tag">{_escape_html(tag)}</span>')
        parts.append("    </span>")
    if progress is not None:
        progress_int = int(progress)
        parts.append(f'    <div class="doto-progress" title="{progress_int}% complete">')
        parts.append(f'      <div class="doto-progress-bar" style="width:{progress_int}%"></div>')
        parts.append("    </div>")
    parts.append("  </div>")

    # Body placeholder (Sphinx will render children here)
    parts.append('  <div class="doto-body">')
    parts.append("  </div>")
    parts.append("</div>")

    return "\n".join(parts) + "\n"


def _fallback_render_table(ctx: dict[str, Any]) -> str:
    """Fallback renderer for doto-list-table.html."""
    from doxtr_doto.fields import COLUMN_LABELS

    tasks = ctx.get("tasks", [])
    columns = ctx.get("columns", ["id", "title", "priority", "status"])
    column_labels = ctx.get("column_labels", COLUMN_LABELS)

    parts = ['<table class="doto-table">']

    # Header
    parts.append("<thead><tr>")
    for col in columns:
        label = column_labels.get(col, col.title())
        parts.append(f"<th>{_escape_html(label)}</th>")
    parts.append("</tr></thead>")

    # Body
    parts.append("<tbody>")
    for task in tasks:
        # Use css_classes() method if available
        if hasattr(task, "css_classes") and callable(task.css_classes):
            # Get classes without 'doto' base (table rows don't need it)
            classes = task.css_classes()
            row_class = " ".join(c for c in classes if c != "doto")
        else:
            # Fallback for non-DotoTask objects
            from doxtr_doto.constants import PRIORITY_CLASSES, STATUS_CLASSES

            priority_class = PRIORITY_CLASSES.get(task.priority, "")
            status_class = STATUS_CLASSES.get(task.status, "")
            row_class = f"{priority_class} {status_class}".strip()
            is_overdue = (
                task.is_overdue()
                if callable(getattr(task, "is_overdue", None))
                else getattr(task, "is_overdue", False)
            )
            if is_overdue:
                row_class += " doto-overdue"

        parts.append(f'<tr class="{_escape_attr(row_class)}">')
        for col in columns:
            value = _column_value_filter(task, col)
            cell_class = f"doto-col-{col}"
            parts.append(f'<td class="{_escape_attr(cell_class)}">{_escape_html(value)}</td>')
        parts.append("</tr>")
    parts.append("</tbody>")
    parts.append("</table>")

    return "\n".join(parts) + "\n"


def _fallback_render_cards(ctx: dict[str, Any]) -> str:
    """Fallback renderer for doto-list-cards.html."""
    from doxtr_doto.utils import format_date_display

    tasks = ctx.get("tasks", [])
    card_data = ctx.get("card_data", {}) or {}
    parts = []

    for task in tasks:
        # Use css_classes() method if available
        if hasattr(task, "css_classes") and callable(task.css_classes):
            classes = task.css_classes(extra=["doto-card"])
            # Remove 'doto' base class since cards use 'doto-card' as base
            classes = [c for c in classes if c != "doto"]
        else:
            # Fallback for non-DotoTask objects
            from doxtr_doto.constants import PRIORITY_CLASSES, STATUS_CLASSES

            priority_class = PRIORITY_CLASSES.get(task.priority, "")
            status_class = STATUS_CLASSES.get(task.status, "")
            classes = ["doto-card", priority_class, status_class]
            is_overdue = (
                task.is_overdue()
                if callable(getattr(task, "is_overdue", None))
                else getattr(task, "is_overdue", False)
            )
            if is_overdue:
                classes.append("doto-overdue")

        class_attr = _escape_attr(" ".join(c for c in classes if c))
        parts.append(f'<div class="{class_attr}">')
        parts.append('<div class="doto-card-header">')
        parts.append(f'<span class="doto-card-id">{_escape_html(task.id)}</span>')
        parts.append(f'<span class="doto-card-priority">{_escape_html(task.priority)}</span>')
        parts.append("</div>")
        parts.append(f'<div class="doto-card-title">{_escape_html(task.title)}</div>')
        parts.append('<div class="doto-card-meta">')
        cd = card_data.get(task.id, {})
        assignee = cd.get("assignee", task.assignee) if cd else task.assignee
        assignee_href = cd.get("assignee_href", "") if cd else ""
        if assignee:
            if assignee_href:
                parts.append(
                    f'<span class="doto-card-assignee">'
                    f'<a class="doto-list-link doto-card-assignee-link" '
                    f'href="{_escape_attr(assignee_href)}">'
                    f"{_escape_html(assignee)}</a></span>"
                )
            else:
                parts.append(f'<span class="doto-card-assignee">{_escape_html(assignee)}</span>')
        if task.due:
            due_str = format_date_display(task.due)
            parts.append(f'<span class="doto-card-due">{_escape_html(due_str)}</span>')
        parts.append(f'<span class="doto-card-status">{_escape_html(task.status)}</span>')
        parts.append("</div>")
        parts.append("</div>")

    return "\n".join(parts) + "\n"


def _fallback_render_list(ctx: dict[str, Any]) -> str:
    """Fallback renderer for doto-list-simple.html."""
    tasks = ctx.get("tasks", [])
    card_data = ctx.get("card_data", {}) or {}
    parts = ['<ul class="doto-task-list">']

    for task in tasks:
        # Use css_classes() method if available
        if hasattr(task, "css_classes") and callable(task.css_classes):
            classes = task.css_classes(extra=["doto-list-item"])
            # Remove 'doto' base class since list items use 'doto-list-item' as base
            classes = [c for c in classes if c != "doto"]
        else:
            # Fallback for non-DotoTask objects
            from doxtr_doto.constants import PRIORITY_CLASSES, STATUS_CLASSES

            priority_class = PRIORITY_CLASSES.get(task.priority, "")
            status_class = STATUS_CLASSES.get(task.status, "")
            classes = ["doto-list-item", priority_class, status_class]
            is_overdue = (
                task.is_overdue()
                if callable(getattr(task, "is_overdue", None))
                else getattr(task, "is_overdue", False)
            )
            if is_overdue:
                classes.append("doto-overdue")

        class_attr = _escape_attr(" ".join(c for c in classes if c))
        parts.append(f'<li class="{class_attr}">')
        parts.append(f'<span class="doto-list-id">{_escape_html(task.id)}</span> ')
        parts.append(f'<span class="doto-list-title">{_escape_html(task.title)}</span> ')
        parts.append(f'<span class="doto-list-priority">[{_escape_html(task.priority)}]</span> ')
        parts.append(f'<span class="doto-list-status">({_escape_html(task.status)})</span>')
        cd = card_data.get(task.id, {})
        assignee = cd.get("assignee", task.assignee) if cd else task.assignee
        assignee_href = cd.get("assignee_href", "") if cd else ""
        if assignee:
            if assignee_href:
                parts.append(
                    f' <span class="doto-list-assignee">@'
                    f'<a class="doto-list-link doto-list-assignee-link" '
                    f'href="{_escape_attr(assignee_href)}">'
                    f"{_escape_html(assignee)}</a></span>"
                )
            else:
                parts.append(f' <span class="doto-list-assignee">@{_escape_html(assignee)}</span>')
        parts.append("</li>")

    parts.append("</ul>")

    return "\n".join(parts) + "\n"


def _fallback_row_class(task: Any, base: str) -> str:
    """Compute a task's CSS class string for a fallback container element.

    Mirrors how the other fallback renderers derive row classes: uses
    ``css_classes()`` when available (dropping the ``doto`` base), else computes
    priority/status/overdue classes manually. The ``base`` class is prepended.

    Args:
        task: DotoTask (or compatible) object.
        base: Base CSS class for the element (e.g. ``doto-kanban-card``).

    Returns:
        An escaped, space-joined class attribute value.
    """
    if hasattr(task, "css_classes") and callable(task.css_classes):
        classes = [c for c in task.css_classes(extra=[base]) if c != "doto"]
    else:
        from doxtr_doto.constants import PRIORITY_CLASSES, STATUS_CLASSES

        priority_class = PRIORITY_CLASSES.get(getattr(task, "priority", ""), "")
        status_class = STATUS_CLASSES.get(getattr(task, "status", ""), "")
        classes = [base, priority_class, status_class]
        is_overdue = (
            task.is_overdue()
            if callable(getattr(task, "is_overdue", None))
            else getattr(task, "is_overdue", False)
        )
        if is_overdue:
            classes.append("doto-overdue")
    return _escape_attr(" ".join(c for c in classes if c))


def _fallback_render_kanban(ctx: dict[str, Any]) -> str:
    """Fallback renderer for doto-list-kanban.html (Jinja2 absent).

    Produces an equivalent static kanban board to the Jinja template, with
    status columns and draggable cards (drag is wired by doto-views.js at
    runtime; this only emits the markup).

    Args:
        ctx: Template context with ``columns``, ``grouped``, ``task_links`` and
             ``icon_mode``.

    Returns:
        Rendered HTML string.
    """
    columns = ctx.get("columns", [])
    grouped = ctx.get("grouped", {})
    task_links = ctx.get("task_links", {})
    icon_mode = ctx.get("icon_mode", "icon-text")

    from doxtr_doto.utils import format_date_display

    parts = [
        (
            f'<div class="doto-kanban doto-list-icon-mode-{_escape_attr(icon_mode)}" '
            'data-doto-view="kanban">'
        )
    ]
    for status, label in columns:
        tasks = grouped.get(status, [])
        parts.append(f'<div class="doto-kanban-column" data-doto-status="{_escape_attr(status)}">')
        parts.append('<div class="doto-kanban-column-header">')
        parts.append(f'<span class="doto-kanban-column-title">{_escape_html(label)}</span>')
        parts.append(f'<span class="doto-kanban-column-count">{len(tasks)}</span>')
        parts.append("</div>")
        parts.append(f'<ul class="doto-kanban-cards" data-doto-dropzone="{_escape_attr(status)}">')
        for task in tasks:
            href = _escape_attr(task_links.get(task.id, f"#{task.id}"))
            card_class = _fallback_row_class(task, "doto-kanban-card")
            parts.append(
                f'<li class="{card_class}" draggable="true" '
                f'data-doto-task="{_escape_attr(task.id)}" '
                f'data-doto-status="{_escape_attr(task.status)}">'
            )
            parts.append('<div class="doto-kanban-card-header">')
            parts.append(
                f'<a class="doto-list-link doto-kanban-card-id" href="{href}">'
                f"{_escape_html(task.id)}</a>"
            )
            parts.append(
                f'<span class="doto-kanban-card-priority">{_escape_html(task.priority)}</span>'
            )
            parts.append("</div>")
            parts.append(
                f'<a class="doto-list-link doto-kanban-card-title" href="{href}">'
                f"{_escape_html(task.title)}</a>"
            )
            parts.append('<div class="doto-kanban-card-meta">')
            if task.assignee:
                parts.append(
                    f'<span class="doto-kanban-card-assignee">{_escape_html(task.assignee)}</span>'
                )
            if task.due:
                parts.append(
                    f'<span class="doto-kanban-card-due">'
                    f"{_escape_html(format_date_display(task.due))}</span>"
                )
            parts.append(
                f'<span class="doto-kanban-card-status" data-doto-status-badge>'
                f"{_escape_html(task.status)}</span>"
            )
            parts.append("</div>")
            parts.append("</li>")
        parts.append("</ul>")
        parts.append("</div>")
    parts.append("</div>")
    return "\n".join(parts) + "\n"


def _fallback_render_calendar(ctx: dict[str, Any]) -> str:
    """Fallback renderer for doto-list-calendar.html (Jinja2 absent).

    Produces an equivalent static month grid to the Jinja template; the
    click-a-day interaction is wired by doto-views.js at runtime.

    Args:
        ctx: Template context with ``calendar`` and ``task_links``.

    Returns:
        Rendered HTML string.
    """
    cal = ctx.get("calendar", {})
    task_links = ctx.get("task_links", {})
    icon_mode = ctx.get("icon_mode", "icon-text")

    def _task_items(tasks: list[Any]) -> list[str]:
        items: list[str] = []
        for task in tasks:
            href = _escape_attr(task_links.get(task.id, f"#{task.id}"))
            cls = _fallback_row_class(task, "doto-calendar-task")
            items.append(
                f'<li class="{cls}">'
                f'<a class="doto-list-link doto-calendar-task-link" href="{href}">'
                f"{_escape_html(task.id)}: {_escape_html(task.title)}</a></li>"
            )
        return items

    parts = [
        (
            f'<div class="doto-calendar doto-list-icon-mode-{_escape_attr(icon_mode)}" '
            'data-doto-view="calendar">'
        )
    ]
    parts.append('<div class="doto-calendar-header">')
    parts.append(
        f'<span class="doto-calendar-month">{_escape_html(cal.get("month_label", ""))}</span>'
    )
    parts.append("</div>")
    parts.append('<table class="doto-calendar-grid"><thead><tr>')
    for weekday in cal.get("weekday_labels", []):
        parts.append(f'<th class="doto-calendar-weekday">{_escape_html(weekday)}</th>')
    parts.append("</tr></thead><tbody>")
    for week in cal.get("weeks", []):
        parts.append('<tr class="doto-calendar-week">')
        for cell in week:
            day_tasks = cell.get("tasks", [])
            cell_class = "doto-calendar-day"
            if not cell.get("in_month"):
                cell_class += " doto-calendar-day-other"
            if day_tasks:
                cell_class += " doto-calendar-day-has-tasks"
            iso = _escape_attr(cell.get("iso", ""))
            parts.append(f'<td class="{cell_class}" data-doto-day="{iso}">')
            disabled = "" if day_tasks else " disabled"
            parts.append(
                f'<button type="button" class="doto-calendar-day-number" '
                f'data-doto-day-toggle="{iso}"{disabled}>{cell.get("day", "")}'
            )
            if day_tasks:
                parts.append(f'<span class="doto-calendar-day-count">{len(day_tasks)}</span>')
            parts.append("</button>")
            if day_tasks:
                parts.append(f'<ul class="doto-calendar-day-tasks" data-doto-day-panel="{iso}">')
                parts.extend(_task_items(day_tasks))
                parts.append("</ul>")
            parts.append("</td>")
        parts.append("</tr>")
    parts.append("</tbody></table>")
    unscheduled = cal.get("unscheduled", [])
    if unscheduled:
        parts.append('<div class="doto-calendar-unscheduled">')
        parts.append('<span class="doto-calendar-unscheduled-title">No due date</span>')
        parts.append('<ul class="doto-calendar-day-tasks">')
        parts.extend(_task_items(unscheduled))
        parts.append("</ul>")
        parts.append("</div>")
    parts.append("</div>")
    return "\n".join(parts) + "\n"


def _fallback_render_email(ctx: dict[str, Any]) -> str:
    """Fallback renderer for doto-list-email.html (Jinja2 absent).

    Produces the equivalent static three-pane layout (tree / list / detail);
    pane selection is wired by doto-views.js at runtime.

    Args:
        ctx: Template context with ``columns``, ``tree``, ``tasks`` and
             ``task_links``.

    Returns:
        Rendered HTML string.
    """
    columns = ctx.get("columns", [])
    tree = ctx.get("tree", {})
    tasks = ctx.get("tasks", [])
    task_links = ctx.get("task_links", {})
    icon_mode = ctx.get("icon_mode", "icon-text")

    from doxtr_doto.utils import format_date_display

    parts = [
        (
            f'<div class="doto-email doto-list-icon-mode-{_escape_attr(icon_mode)}" '
            'data-doto-view="email">'
        )
    ]
    # Left pane: tree grouped by status.
    parts.append('<div class="doto-email-tree" role="tree" aria-label="Task tree">')
    for status, label in columns:
        count = len(tree.get(status, []))
        parts.append(
            f'<div class="doto-email-tree-group" data-doto-tree-group="{_escape_attr(status)}">'
        )
        parts.append(
            f'<button type="button" class="doto-email-tree-node" '
            f'data-doto-tree-filter="{_escape_attr(status)}">'
            f'<span class="doto-email-tree-label">{_escape_html(label)}</span>'
            f'<span class="doto-email-tree-count">{count}</span></button>'
        )
        parts.append("</div>")
    parts.append(
        '<div class="doto-email-tree-group" data-doto-tree-group="">'
        '<button type="button" class="doto-email-tree-node" data-doto-tree-filter="">'
        '<span class="doto-email-tree-label">All tasks</span>'
        f'<span class="doto-email-tree-count">{len(tasks)}</span></button></div>'
    )
    parts.append("</div>")
    # Right panes: list (top) + detail (bottom).
    parts.append('<div class="doto-email-main">')
    # Mirror the Jinja template: emit the scroll-cap data attribute / CSS
    # custom property when a positive visible-task count is resolved. 0 /
    # absent means "show all" (no cap).
    from doxtr_doto.config import is_valid_visible_tasks

    visible_tasks = ctx.get("visible_tasks")
    if visible_tasks is not None and is_valid_visible_tasks(visible_tasks) and visible_tasks > 0:
        parts.append(
            f'<ul class="doto-email-list" role="list" '
            f'data-doto-visible-tasks="{visible_tasks}" '
            f'style="--doto-visible-tasks: {visible_tasks};">'
        )
    else:
        parts.append('<ul class="doto-email-list" role="list">')
    for task in tasks:
        item_class = _fallback_row_class(task, "doto-email-list-item")
        parts.append(
            f'<li class="{item_class}" data-doto-select="{_escape_attr(task.id)}" '
            f'data-doto-status="{_escape_attr(task.status)}" tabindex="0">'
            f'<span class="doto-email-list-id">{_escape_html(task.id)}</span>'
            f'<span class="doto-email-list-title">{_escape_html(task.title)}</span>'
            f'<span class="doto-email-list-status">{_escape_html(task.status)}</span></li>'
        )
    parts.append("</ul>")
    parts.append('<div class="doto-email-detail">')
    for i, task in enumerate(tasks):
        href = _escape_attr(task_links.get(task.id, f"#{task.id}"))
        panel_class = _fallback_row_class(task, "doto-email-detail-panel")
        hidden = "" if i == 0 else " hidden"
        parts.append(
            f'<div class="{panel_class}" data-doto-detail="{_escape_attr(task.id)}"{hidden}>'
        )
        parts.append(
            f'<h4 class="doto-email-detail-title">'
            f'<a class="doto-list-link" href="{href}">'
            f"{_escape_html(task.id)}: {_escape_html(task.title)}</a></h4>"
        )
        parts.append('<dl class="doto-email-detail-meta">')
        parts.append(f"<dt>Priority</dt><dd>{_escape_html(task.priority)}</dd>")
        parts.append(f"<dt>Status</dt><dd>{_escape_html(task.status)}</dd>")
        if task.assignee:
            parts.append(f"<dt>Assignee</dt><dd>{_escape_html(task.assignee)}</dd>")
        if task.due:
            parts.append(f"<dt>Due</dt><dd>{_escape_html(format_date_display(task.due))}</dd>")
        if task.tags:
            tags = "".join(
                f'<span class="doto-tag">{_escape_html(tag)}</span>' for tag in task.tags
            )
            parts.append(f"<dt>Tags</dt><dd>{tags}</dd>")
        parts.append("</dl>")
        if task.body:
            parts.append(f'<div class="doto-email-detail-body">{_escape_html(task.body)}</div>')
        parts.append("</div>")
    parts.append("</div>")
    parts.append("</div>")
    parts.append("</div>")
    return "\n".join(parts) + "\n"


def _fallback_render_archive(ctx: dict[str, Any]) -> str:
    """Fallback renderer for doto-archive.html (archive page listing).

    Produces equivalent markup to the Jinja template when Jinja2 is absent,
    sourcing rows from the pre-built archive-row dicts.

    Args:
        ctx: Template context with ``rows`` and ``total``.

    Returns:
        Rendered HTML string.
    """
    rows = ctx.get("rows", [])
    total = ctx.get("total", len(rows))

    parts = ['<div class="doto-archive">']
    parts.append(
        f'  <p class="doto-archive-total"><strong>Total archived tasks:</strong> {total}</p>'
    )
    if rows:
        parts.append('  <table class="doto-archive-table">')
        parts.append("    <thead><tr>")
        for label in ("ID", "Title", "Status", "Priority", "Assignee", "Archived", "Original page"):
            parts.append(f"<th>{label}</th>")
        parts.append("</tr></thead>")
        parts.append("    <tbody>")
        for row in rows:
            priority = _escape_attr(row.get("priority", ""))
            status = _escape_attr(row.get("status", ""))
            parts.append(
                f'      <tr class="doto-archive-row doto-priority-{priority} doto-status-{status}">'
            )
            for key in (
                "id",
                "title",
                "status",
                "priority",
                "assignee",
                "archived_on",
                "original_page",
            ):
                parts.append(
                    f'<td class="doto-archive-{key}">{_escape_html(row.get(key, ""))}</td>'
                )
            parts.append("</tr>")
            if row.get("body"):
                parts.append(
                    '      <tr class="doto-archive-body-row">'
                    f'<td class="doto-archive-body" colspan="7">'
                    f"{_escape_html(row.get('body', ''))}</td></tr>"
                )
        parts.append("    </tbody>")
        parts.append("  </table>")
    else:
        parts.append('  <p class="doto-archive-empty"><em>No archived tasks.</em></p>')
    parts.append("</div>")
    return "\n".join(parts) + "\n"
