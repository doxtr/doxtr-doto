"""Custom docutils nodes for doto directives."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from docutils import nodes

from doxtr_doto.constants import (
    DEFAULT_PRIORITY,
    DEFAULT_STATUS,
    PRIORITY_CLASSES,
    PRIORITY_DISPLAY_ORDER,
    STATUS_CLASSES,
    STATUS_DISPLAY_ORDER,
    VALID_LIST_ICON_MODES,
)
from doxtr_doto.utils import (
    escape_html_attr,
    escape_html_content,
    sanitize_html_id,
)

# Column specifications for LaTeX tables
LATEX_COLUMN_SPECS: dict[str, str] = {
    "id": r"l",           # Left-aligned, auto width
    "title": r"p{5cm}",   # Paragraph, 5cm width
    "priority": r"c",     # Centered
    "status": r"c",       # Centered
    "assignee": r"l",     # Left-aligned
    "due": r"c",          # Centered (dates)
    "tags": r"p{3cm}",    # Paragraph for wrapping
    "created": r"c",      # Centered
    "updated": r"c",      # Centered
    "depends-on": r"p{3cm}",  # Paragraph for wrapping
}

# Default spec for unknown columns
DEFAULT_LATEX_COLUMN_SPEC = "l"

# --- Task-list icon mapping (Feature 5) -----------------------------------
#
# Each entry maps a task-list field to the icon used when rendering that
# column/cell in "icon" or "icon-text" mode. Fields whose value carries its own
# semantics (status, priority) map value -> icon; the rest are field-level.
#
# HTML uses Font Awesome CSS classes (``fa-solid``/``fa-regular`` + name); the
# host Sphinx theme is expected to provide Font Awesome. LaTeX uses the
# ``\faXxx`` macros, which ``doto.sty`` \providecommand-guards so a missing FA
# package degrades to empty (text fallback still shown).
#
# ``None`` means "no good icon" for that field/value, so "icon" mode falls back
# to text for it.

#: Priority -> LaTeX task-box environment. Selects the priority-colored
#: ``dotobox<priority>`` variants defined in ``doto.sty`` so they are actually
#: used and overridable by a child theme's ``.sty``. Unknown priorities fall
#: back to :data:`DEFAULT_BOX_ENV`.
DEFAULT_BOX_ENV = "dotobox"
_DOTO_BOX_ENVS: dict[str, str] = {
    "low": "dotoboxlow",
    "medium": "dotoboxmedium",
    "high": "dotoboxhigh",
    "critical": "dotoboxcritical",
}

#: Field-level Font Awesome CSS class (HTML) keyed by list column.
LIST_FIELD_FA_HTML: dict[str, str | None] = {
    "id": "fa-solid fa-hashtag",
    "title": None,       # titles are text (and clickable) — no icon
    "assignee": "fa-solid fa-user",
    "due": "fa-solid fa-calendar-day",
    "created": "fa-solid fa-calendar-plus",
    "updated": "fa-solid fa-calendar-check",
    "tags": "fa-solid fa-tags",
    "depends-on": "fa-solid fa-link",
    "priority": "fa-solid fa-flag",
    "status": "fa-solid fa-circle-dot",
}

#: Field-level LaTeX FA macro keyed by list column (macros guarded in doto.sty).
LIST_FIELD_FA_LATEX: dict[str, str | None] = {
    "id": r"\faHashtag",
    "title": None,
    "assignee": r"\faUser",
    "due": r"\faCalendarDay",
    "created": r"\faCalendarPlus",
    "updated": r"\faCalendarCheck",
    "tags": r"\faTags",
    "depends-on": r"\faLink",
    "priority": r"\faFlag",
    "status": r"\faCircleDot",
}

#: Per-value status icons (HTML Font Awesome classes).
STATUS_FA_HTML: dict[str, str] = {
    "open": "fa-regular fa-circle",
    "in-progress": "fa-solid fa-spinner",
    "blocked": "fa-solid fa-ban",
    "done": "fa-solid fa-circle-check",
}

#: Per-value status icons (LaTeX FA macros).
STATUS_FA_LATEX: dict[str, str] = {
    "open": r"\faRegularCircle",
    "in-progress": r"\faSpinner",
    "blocked": r"\faBan",
    "done": r"\faCircleCheck",
}

#: Per-value priority icons (HTML Font Awesome classes).
PRIORITY_FA_HTML: dict[str, str] = {
    "low": "fa-solid fa-angle-down",
    "medium": "fa-solid fa-equals",
    "high": "fa-solid fa-angle-up",
    "critical": "fa-solid fa-angles-up",
}

#: Per-value priority icons (LaTeX FA macros).
PRIORITY_FA_LATEX: dict[str, str] = {
    "low": r"\faAngleDown",
    "medium": r"\faEquals",
    "high": r"\faAngleUp",
    "critical": r"\faAnglesUp",
}


def _resolve_list_icon_mode(node: Any, app: Any) -> str:
    """Resolve the effective icon mode for a task list.

    A per-directive ``:icon-mode:`` override on the node wins; otherwise the
    ``doto_list_icon_mode`` config value is used, defaulting to ``icon-text``.

    Args:
        node: The ``doto_list_node`` (may carry an ``icon_mode`` attribute).
        app: Sphinx application instance (may be None).

    Returns:
        One of ``icon``, ``icon-text``, ``text``.
    """
    override = node.get("icon_mode") if hasattr(node, "get") else None
    if override in VALID_LIST_ICON_MODES:
        return override
    if app is not None:
        from doxtr_doto.config import get_config
        mode = get_config(app, "list_icon_mode")
        if mode in VALID_LIST_ICON_MODES:
            return mode
    return "icon-text"


def _normalize_icon_spec(spec: Any) -> tuple[str | None, str | None]:
    """Normalize a config icon spec into an ``(html, latex)`` pair.

    Accepts either a mapping with ``html``/``latex`` keys or a bare string
    (treated as the HTML class with no LaTeX macro). Missing keys yield None.
    """
    if isinstance(spec, str):
        return spec, None
    if isinstance(spec, dict):
        html = spec.get("html")
        latex = spec.get("latex")
        return (html if isinstance(html, str) or html is None else None,
                latex if isinstance(latex, str) or latex is None else None)
    return None, None


def _resolve_list_icons(app: Any) -> dict[str, dict[str, tuple[str | None, str | None]]]:
    """Build the effective field/value -> icon maps, config merged over defaults.

    The built-in maps (``LIST_FIELD_FA_*``, ``STATUS_FA_*``, ``PRIORITY_FA_*``)
    are the defaults. A ``doto_list_icons`` config dict (see config.py for its
    shape) is merged on top so custom statuses/priorities (allowed via
    ``doto_statuses``/``doto_priorities``) — or any field — can get icons
    without editing source. Only supplied keys override; every default keeps
    working.

    Returns:
        Mapping ``{"fields"|"status"|"priority": {key: (html, latex)}}``.
    """
    def _pairs(html_map: dict[str, str | None],
               latex_map: dict[str, str | None]) -> dict[str, tuple[str | None, str | None]]:
        keys = set(html_map) | set(latex_map)
        return {k: (html_map.get(k), latex_map.get(k)) for k in keys}

    icons: dict[str, dict[str, tuple[str | None, str | None]]] = {
        "fields": _pairs(LIST_FIELD_FA_HTML, LIST_FIELD_FA_LATEX),
        "status": _pairs(STATUS_FA_HTML, STATUS_FA_LATEX),
        "priority": _pairs(PRIORITY_FA_HTML, PRIORITY_FA_LATEX),
    }

    if app is not None:
        from doxtr_doto.config import get_config
        overrides = get_config(app, "list_icons") or {}
        if isinstance(overrides, dict):
            for group in ("fields", "status", "priority"):
                group_overrides = overrides.get(group)
                if not isinstance(group_overrides, dict):
                    continue
                for key, spec in group_overrides.items():
                    lookup = key.lower() if group in ("status", "priority") else key
                    icons[group][lookup] = _normalize_icon_spec(spec)
    return icons


def _list_icon_html(
    column: str,
    value: str,
    icons: dict[str, dict[str, tuple[str | None, str | None]]] | None = None,
) -> str | None:
    """Return the Font Awesome CSS class for a list cell, or None if none fits.

    Status/priority use value-specific icons; other fields use a field-level
    icon. Returns None when no good icon exists (caller falls back to text).
    When ``icons`` (resolved via :func:`_resolve_list_icons`) is supplied, its
    config-merged maps are used; otherwise the built-in defaults are used.
    """
    col = column.lower()
    if icons is not None:
        if col == "status":
            spec = icons["status"].get(value.lower())
            return spec[0] if spec else None
        if col == "priority":
            spec = icons["priority"].get(value.lower())
            return spec[0] if spec else None
        spec = icons["fields"].get(col)
        return spec[0] if spec else None
    if col == "status":
        return STATUS_FA_HTML.get(value.lower())
    if col == "priority":
        return PRIORITY_FA_HTML.get(value.lower())
    return LIST_FIELD_FA_HTML.get(col)


def _list_icon_latex(
    column: str,
    value: str,
    icons: dict[str, dict[str, tuple[str | None, str | None]]] | None = None,
) -> str | None:
    """Return the LaTeX FA macro for a list cell, or None if none fits.

    When ``icons`` (resolved via :func:`_resolve_list_icons`) is supplied, its
    config-merged maps are used; otherwise the built-in defaults are used.
    """
    col = column.lower()
    if icons is not None:
        if col == "status":
            spec = icons["status"].get(value.lower())
            return spec[1] if spec else None
        if col == "priority":
            spec = icons["priority"].get(value.lower())
            return spec[1] if spec else None
        spec = icons["fields"].get(col)
        return spec[1] if spec else None
    if col == "status":
        return STATUS_FA_LATEX.get(value.lower())
    if col == "priority":
        return PRIORITY_FA_LATEX.get(value.lower())
    return LIST_FIELD_FA_LATEX.get(col)


if TYPE_CHECKING:
    from sphinx.writers.html5 import HTML5Translator
    from sphinx.writers.latex import LaTeXTranslator
    from sphinx.builders.epub3 import Epub3Builder


class doto_node(nodes.General, nodes.Element):
    """Node representing a single doto task."""
    
    def __init__(
        self,
        rawsource: str = "",
        *children: nodes.Node,
        **attributes: Any,
    ) -> None:
        super().__init__(rawsource, *children, **attributes)


class doto_list_node(nodes.General, nodes.Element):
    """Node representing a filtered list of tasks."""
    
    def __init__(
        self,
        rawsource: str = "",
        *children: nodes.Node,
        **attributes: Any,
    ) -> None:
        super().__init__(rawsource, *children, **attributes)


class doto_summary_node(nodes.General, nodes.Element):
    """Node representing task statistics summary."""
    
    def __init__(
        self,
        rawsource: str = "",
        *children: nodes.Node,
        **attributes: Any,
    ) -> None:
        super().__init__(rawsource, *children, **attributes)


class doto_ref(nodes.Inline, nodes.Element):
    """Node representing a cross-reference to a task."""
    pass


def visit_doto_node_html(self: HTML5Translator, node: doto_node) -> None:
    """Visit handler for doto_node in HTML output.
    
    Uses Jinja2 templates if available, otherwise falls back to Python rendering.
    Templates can be overridden by placing files in _doto/templates/html/.
    """
    from doxtr_doto.template_loader import render_template, JINJA2_AVAILABLE
    
    task_id = node.get("task_id", "")
    title = node.get("title", "")
    priority = node.get("priority", DEFAULT_PRIORITY)
    status = node.get("status", DEFAULT_STATUS)
    assignee = node.get("assignee", "")
    due = node.get("due", "")
    tags = node.get("tags", [])
    progress = node.get("progress")
    is_overdue = node.get("is_overdue", False)
    
    # Build CSS classes
    priority_class = PRIORITY_CLASSES.get(priority, "")
    status_class = STATUS_CLASSES.get(status, "")
    classes = " ".join(c for c in ["doto", priority_class, status_class,
                                    "doto-overdue" if is_overdue else ""] if c)
    
    # Get srcdir for template overrides
    srcdir = getattr(self.builder, "srcdir", None)
    
    # Render template
    html = render_template("doto.html", {
        "task_id": task_id,
        "title": title,
        "priority": priority,
        "status": status,
        "assignee": assignee,
        "due": due,
        "tags": tags,
        "progress": progress,
        "is_overdue": is_overdue,
        "classes": classes,
    }, srcdir=srcdir)
    
    # Split at body div so Sphinx can render children into it
    # The template should contain: <div class="doto-body">\n  </div>
    body_marker = '<div class="doto-body">'
    if body_marker in html:
        parts = html.split(body_marker, 1)
        self.body.append(parts[0] + body_marker + '\n')
        # Store suffix for depart handler
        node["_template_suffix"] = parts[1] if len(parts) > 1 else "  </div>\n</div>\n"
    else:
        # Fallback: emit everything and store empty suffix
        self.body.append(html)
        node["_template_suffix"] = ""


def depart_doto_node_html(self: HTML5Translator, node: doto_node) -> None:
    """Depart handler for doto_node in HTML output."""
    # Use stored suffix from template, or default closing tags
    suffix = node.get("_template_suffix", "  </div>\n</div>\n")
    self.body.append(suffix)


def _latex_task_label(docname: str, task_id: str) -> str:
    """Build the LaTeX cross-reference label for a task box.

    Sphinx's LaTeX writer resolves ``:doto:`ID``` references (via the domain's
    ``make_refnode``) to ``\\hyperref[\\detokenize{<docname>:<task_id>}]{...}``.
    For those links to resolve, the task box must emit a matching
    ``\\label{\\detokenize{<docname>:<task_id>}}``. This builds that
    ``\\detokenize{...}`` argument so the anchor and the reference agree.

    Args:
        docname: Source document name the task was defined in.
        task_id: Raw task identifier.

    Returns:
        A LaTeX label expression suitable for ``\\dotolabel``/``\\label``, e.g.
        ``\\detokenize{doto-showcase:AUTH-001}``. Falls back to the task id
        alone when the docname is unavailable.
    """
    if docname:
        anchor = f"{docname}:{task_id}"
    else:
        anchor = task_id
    return f"\\detokenize{{{anchor}}}"


def visit_doto_node_latex(self: LaTeXTranslator, node: doto_node) -> None:
    """Visit handler for doto_node in LaTeX output.

    Emits a hyperlink anchor so ``:doto:`ID``` cross-references resolve, opens a
    priority-specific ``dotobox<priority>`` environment (``dotoboxlow`` /
    ``dotoboxmedium`` / ``dotoboxhigh`` / ``dotoboxcritical``, falling back to the
    plain ``dotobox`` for unknown priorities) with the task title as its
    (visible, styled) title bar, and renders the metadata rows using the
    stacked-icon macros defined in ``doto.sty``.

    All visual specifics live in those macros so a child theme can override the
    look by shipping its own ``doto.sty`` (or a project ``_doto/latex/*.sty``,
    discovered in ``__init__.py``). There is intentionally no Jinja LaTeX
    template seam: the box body (metadata rows + reST children) is emitted by
    this translator via node traversal, so the ``.sty`` macros are the single
    override surface for the LaTeX box.
    """
    task_id = node.get("task_id", "")
    title = node.get("title", "")
    priority = node.get("priority", DEFAULT_PRIORITY)
    status = node.get("status", DEFAULT_STATUS)
    assignee = node.get("assignee", "")
    due = node.get("due", "")
    created = node.get("created", "")
    updated = node.get("updated", "")
    tags = node.get("tags", [])
    is_overdue = node.get("is_overdue", False)
    docname = node.get("docname", "")

    # Emit the cross-reference anchor matching what the domain resolver targets,
    # so :doto:`ID` links become clickable and the "Hyper reference ... undefined"
    # LaTeX warnings for doto IDs disappear.
    label = _latex_task_label(docname, task_id)
    self.body.append(f'\\dotolabel{{{label}}}\n')

    # Select the priority-colored box environment so the dotobox<priority>
    # variants in doto.sty are actually used and overridable; unknown
    # priorities fall back to the plain dotobox. The chosen environment is
    # stored on the node so the matching depart handler closes it.
    box_env = _DOTO_BOX_ENVS.get(str(priority).lower(), DEFAULT_BOX_ENV)
    node["_box_env"] = box_env
    self.body.append(f'\\begin{{{box_env}}}[{_latex_escape(title)}]\n')

    # Metadata row: ID + priority (priority colored by severity via macro).
    self.body.append(f'\\dotometaid{{{_latex_escape(task_id)}}}\\hfill ')
    priority_display = _latex_escape(priority)
    self.body.append(
        f'\\dotometapriority{{\\dotopriorityvalue{{{priority}}}{{{priority_display}}}}}'
        '\n\n'
    )

    # Status row.
    self.body.append(f'\\dotometastatus{{{_latex_escape(status)}}}\n\n')

    if assignee or due:
        if assignee:
            self.body.append(f'\\dotometaassignee{{{_latex_escape(assignee)}}}')
        if due:
            if assignee:
                self.body.append('\\hfill ')
            due_text = _latex_escape(due)
            if is_overdue:
                due_text = f'\\dotooverdue{{{due_text}}}'
            self.body.append(f'\\dotometadue{{{due_text}}}')
        self.body.append('\n\n')

    if created or updated:
        if created:
            self.body.append(f'\\dotometacreated{{{_latex_escape(created)}}}')
        if updated:
            if created:
                self.body.append('\\hfill ')
            self.body.append(f'\\dotometaupdated{{{_latex_escape(updated)}}}')
        self.body.append('\n\n')

    if tags:
        tag_text = ', '.join(_latex_escape(t) for t in tags)
        self.body.append(f'\\dotometatags{{{tag_text}}}\n\n')


def depart_doto_node_latex(self: LaTeXTranslator, node: doto_node) -> None:
    """Depart handler for doto_node in LaTeX output.

    Closes the priority-specific box environment opened in the visit handler
    (stored on the node), falling back to ``dotobox`` if it was not recorded.
    """
    box_env = node.get("_box_env", DEFAULT_BOX_ENV)
    self.body.append(f'\\end{{{box_env}}}\n')


def visit_doto_list_node_html(self: HTML5Translator, node: doto_list_node) -> None:
    """Visit handler for doto_list_node in HTML output."""
    from doxtr_doto.collectors import filter_tasks, get_doto_env
    from doxtr_doto.query import DisplayOptions, TaskFilter
    
    # Get filter and display configuration from node
    filters = node.get("filters", {})
    display = node.get("display", {})
    
    # Normalize to typed objects if needed (for backward compatibility)
    if isinstance(filters, dict):
        filters = TaskFilter.from_dict(filters)
    if isinstance(display, dict):
        display = DisplayOptions.from_dict(display)
    
    format_type = display.format
    
    self.body.append(f'<div class="doto-list doto-list-{format_type}">\n')
    
    # Get tasks from environment and filter them
    env = self.builder.env
    doto_env = get_doto_env(env)
    filtered_tasks = filter_tasks(doto_env.all_tasks, filters, display)
    
    if not filtered_tasks:
        self.body.append('<p class="doto-list-empty">No tasks match the specified criteria.</p>\n')
        return
    
    # Stash the node so cell renderers can read the per-directive icon-mode
    # override (Feature 5).
    self._doto_current_list_node = node

    # Dispatch table for format-specific renderers
    renderer = _LIST_RENDERERS.get(format_type, _render_task_list)
    if format_type == "table":
        renderer(self, filtered_tasks, display.columns)
    else:
        renderer(self, filtered_tasks)


def _task_html_href(self: HTML5Translator, task: Any) -> str:
    """Build the in-document HTML href that jumps to a task's box.

    The single-task box renders with ``id="<sanitized task id>"`` on the page
    named by ``task.docname``. This composes a relative URL from the document
    currently being written to that anchor so task IDs/titles in list output are
    clickable (Feature 5). Falls back to a bare ``#<id>`` fragment when the
    task's source document is unknown (e.g. JSON-only tasks).

    Args:
        self: HTML5Translator instance.
        task: DotoTask (or compatible) with ``id`` and ``docname``.

    Returns:
        A URL string suitable for an anchor ``href``.
    """
    anchor = sanitize_html_id(getattr(task, "id", "") or "")
    docname = getattr(task, "docname", None)
    builder = self.builder
    if docname and hasattr(builder, "get_relative_uri"):
        try:
            from_doc = builder.current_docname
            uri = builder.get_relative_uri(from_doc, docname)
            return f"{uri}#{anchor}"
        except Exception:
            pass
    return f"#{anchor}"


def _render_cell_data(
    self: HTML5Translator,
    task: Any,
    column: str,
    mode: str,
    icons: dict[str, dict[str, tuple[str | None, str | None]]] | None = None,
) -> dict[str, Any]:
    """Return structured per-cell data for the list-table template.

    Instead of pre-baking cell HTML in Python (which bypassed the template and
    made ``doto-list-table.html`` non-overridable for cell markup), this returns
    the pieces the template needs to compose the ``<td>`` contents itself,
    matching how the cards/simple templates already author their links/icons:

    * ``value`` — the plain (unescaped) display value; the template autoescapes.
    * ``icon_class`` — Font Awesome CSS class when the mode+field/value warrants
      an icon, else ``None``.
    * ``show_icon`` — whether an icon element should be emitted (icon/icon-text).
    * ``show_text`` — whether the visible text should be emitted (text/icon-text).
    * ``sr_only`` — whether the text should be rendered as an sr-only label
      (icon-only mode keeps meaning accessible).
    * ``title`` — the value to use as the cell ``title`` attribute (icon-only
      mode), else ``None``.
    * ``href`` — link target for the ``id``/``title`` columns (Feature 5
      clickable ids/titles), else ``None``.

    Args:
        self: HTML5Translator instance.
        task: DotoTask (or compatible).
        column: Column name.
        mode: Effective icon mode ("icon" | "icon-text" | "text").
        icons: Resolved field/value -> icon maps (see :func:`_resolve_list_icons`).

    Returns:
        Dict of cell data consumed by ``doto-list-table.html``.
    """
    value = _get_task_column_value(task, column)
    col = column.lower()

    fa_class = (
        _list_icon_html(col, value, icons)
        if mode in ("icon", "icon-text")
        else None
    )

    # Compose visibility flags per mode, mirroring the previous Python markup.
    if mode == "icon" and fa_class and value:
        show_icon, show_text, sr_only = True, True, True
        title = value
    elif mode == "icon-text" and fa_class:
        show_icon, show_text, sr_only = True, bool(value), False
        title = None
    else:
        # text mode, or no fitting icon: fall back to text.
        show_icon, show_text, sr_only = False, True, False
        title = None

    href = None
    if col in ("id", "title") and value:
        href = _task_html_href(self, task)

    return {
        "value": value,
        "icon_class": fa_class,
        "show_icon": show_icon,
        "show_text": show_text,
        "sr_only": sr_only,
        "title": title,
        "href": href,
    }



def _render_task_table(self: HTML5Translator, tasks: list, columns: list[str]) -> None:
    """Render tasks as an HTML table.

    Uses Jinja2 templates if available, otherwise falls back to Python rendering.
    Per-cell data (icon class, link href, sr-only flags, value) is passed as
    structured data so ``doto-list-table.html`` composes the ``<td>`` contents
    itself — the same way the cards/simple templates author their links/icons —
    making cell markup fully child-theme overridable (no raw-HTML injection).
    """
    from doxtr_doto.fields import COLUMN_LABELS
    from doxtr_doto.template_loader import render_template

    srcdir = getattr(self.builder, "srcdir", None)
    app = getattr(self.builder, "app", None)
    node = getattr(self, "_doto_current_list_node", None)
    mode = _resolve_list_icon_mode(node, app)
    icons = _resolve_list_icons(app)

    # Structured per-cell data keyed by (task index, column); the template
    # composes each cell from this instead of receiving pre-baked HTML.
    cell_data: dict[tuple[int, str], dict[str, Any]] = {}
    for i, task in enumerate(tasks):
        for col in columns:
            cell_data[(i, col)] = _render_cell_data(self, task, col, mode, icons)

    html = render_template("doto-list-table.html", {
        "tasks": tasks,
        "columns": columns,
        "column_labels": COLUMN_LABELS,
        "cell_data": cell_data,
        "icon_mode": mode,
    }, srcdir=srcdir)

    self.body.append(html)


def _render_task_cards(self: HTML5Translator, tasks: list) -> None:
    """Render tasks as cards.

    Uses Jinja2 templates if available, otherwise falls back to Python rendering.
    The card id/title are rendered as clickable links to the task box and the
    icon mode (Feature 5) is passed to the template.

    Args:
        self: HTML5Translator instance.
        tasks: List of DotoTask objects to render.
    """
    from doxtr_doto.template_loader import render_template

    srcdir = getattr(self.builder, "srcdir", None)
    app = getattr(self.builder, "app", None)
    node = getattr(self, "_doto_current_list_node", None)
    mode = _resolve_list_icon_mode(node, app)

    task_links = {
        getattr(t, "id", ""): _task_html_href(self, t) for t in tasks
    }

    html = render_template("doto-list-cards.html", {
        "tasks": tasks,
        "task_links": task_links,
        "icon_mode": mode,
    }, srcdir=srcdir)

    self.body.append(html)


def _render_task_list(self: HTML5Translator, tasks: list) -> None:
    """Render tasks as a simple list.

    Uses Jinja2 templates if available, otherwise falls back to Python rendering.
    The id/title are rendered as clickable links to the task box and the icon
    mode (Feature 5) is passed to the template.
    """
    from doxtr_doto.template_loader import render_template

    srcdir = getattr(self.builder, "srcdir", None)
    app = getattr(self.builder, "app", None)
    node = getattr(self, "_doto_current_list_node", None)
    mode = _resolve_list_icon_mode(node, app)

    task_links = {
        getattr(t, "id", ""): _task_html_href(self, t) for t in tasks
    }

    html = render_template("doto-list-simple.html", {
        "tasks": tasks,
        "task_links": task_links,
        "icon_mode": mode,
    }, srcdir=srcdir)

    self.body.append(html)


# Dispatch table mapping format types to their render functions
_LIST_RENDERERS: dict[str, callable] = {
    "table": _render_task_table,
    "cards": _render_task_cards,
    "list": _render_task_list,
}


def _get_task_column_value(task: Any, column: str) -> str:
    """Get the value for a specific column from a task.
    
    Args:
        task: DotoTask object or compatible object with task attributes.
        column: Column name to retrieve (id, title, priority, status, etc.).
        
    Returns:
        String value for the column, or empty string if not available.
    """
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
    return ""


def depart_doto_list_node_html(self: HTML5Translator, node: doto_list_node) -> None:
    """Depart handler for doto_list_node in HTML output."""
    self.body.append('</div>\n')


def visit_doto_list_node_latex(self: LaTeXTranslator, node: doto_list_node) -> None:
    """Visit handler for doto_list_node in LaTeX output."""
    from doxtr_doto.collectors import filter_tasks, get_doto_env
    from doxtr_doto.query import DisplayOptions, TaskFilter

    filters = node.get("filters", {})
    display = node.get("display", {})
    
    # Normalize to typed objects if needed (for backward compatibility)
    if isinstance(filters, dict):
        filters = TaskFilter.from_dict(filters)
    if isinstance(display, dict):
        display = DisplayOptions.from_dict(display)
    
    format_type = display.format
    
    env = self.builder.env
    doto_env = get_doto_env(env)
    tasks = filter_tasks(doto_env.all_tasks, filters, display)

    if not tasks:
        self.body.append('\\textit{No tasks match the specified criteria.}\n\n')
        raise nodes.SkipNode

    # Resolve the effective icon mode (per-directive override or config) once
    # so both LaTeX list formats render consistently (Feature 5).
    app = getattr(self.builder, "app", None)
    mode = _resolve_list_icon_mode(node, app)
    icons = _resolve_list_icons(app)

    if format_type == "table":
        columns = display.columns
        _render_task_table_latex(self, tasks, columns, mode, icons)
    else:
        _render_task_list_latex(self, tasks, mode, icons)

    raise nodes.SkipNode  # content fully generated; skip children


def _get_latex_column_spec(col: str, app: Any = None) -> str:
    """Get LaTeX column specification for a column.
    
    Checks user config first, falls back to defaults.
    
    Args:
        col: Column name.
        app: Optional Sphinx application for config access.
        
    Returns:
        LaTeX column specification string.
    """
    # Check user overrides from config
    if app is not None:
        from doxtr_doto.config import get_config
        user_specs = get_config(app, "latex_column_specs")
        if user_specs and col in user_specs:
            return user_specs[col]
    
    # Use defaults
    return LATEX_COLUMN_SPECS.get(col, DEFAULT_LATEX_COLUMN_SPEC)


def _latex_task_link(task: Any, display_text: str) -> str:
    r"""Wrap display text in a clickable link to the task box (LaTeX).

    Reuses the hyperref anchor mechanism from Phase A: the task box emits
    ``\dotolabel{\detokenize{<docname>:<id>}}`` and this links to the same
    label via the ``\dotolistlink`` macro. When the task's source document is
    unknown the text is returned unlinked.

    Args:
        task: DotoTask (or compatible) with ``id``/``docname``.
        display_text: Already-LaTeX-escaped display text.

    Returns:
        A ``\dotolistlink{...}{...}`` expression, or the plain text if no target.
    """
    docname = getattr(task, "docname", None)
    task_id = getattr(task, "id", "") or ""
    if not task_id:
        return display_text
    label = _latex_task_label(docname or "", task_id)
    return f'\\dotolistlink{{{label}}}{{{display_text}}}'


def _render_cell_latex(
    task: Any,
    column: str,
    mode: str,
    icons: dict[str, dict[str, tuple[str | None, str | None]]] | None = None,
) -> str:
    r"""Render one task-list cell as LaTeX honoring the icon mode (Feature 5).

    * ``text`` — escaped text value only.
    * ``icon`` — the field/value FA macro when one fits (else escaped text).
    * ``icon-text`` — icon macro (when available) followed by escaped text.

    The ``id`` and ``title`` columns are wrapped in a clickable link to the
    task box.

    Args:
        task: DotoTask (or compatible).
        column: Column name.
        mode: Effective icon mode.

    Returns:
        LaTeX string for the cell.
    """
    value = _get_task_column_value(task, column)
    esc = _latex_escape(str(value))
    col = column.lower()

    icon = _list_icon_latex(col, str(value), icons) if mode in ("icon", "icon-text") else None

    if mode == "icon" and icon and value:
        content = icon
    elif mode == "icon-text" and icon:
        content = f'{icon}\\,{esc}' if value else icon
    else:
        content = esc

    if col in ("id", "title") and value:
        return _latex_task_link(task, content)
    return content


def _render_task_table_latex(
    self: LaTeXTranslator,
    tasks: list,
    columns: list[str],
    mode: str = "icon-text",
    icons: dict[str, dict[str, tuple[str | None, str | None]]] | None = None,
) -> None:
    """Render a doto task list as a LaTeX longtable.

    When ``doxtr-pdf-theme-core`` is active and the table is wide (column count
    >= the core's ``doxtr_landscape_min_columns`` threshold, default 4), the
    emitted longtable is wrapped in the core's landscape environment so the
    wide table rotates to landscape automatically (Feature 6). The raw
    longtable bypasses the core's docutils-``table`` AST processor, so the
    rotation is applied here directly via the core's public
    ``wrap_in_landscape`` mechanism.

    Standalone builds (no core) emit an unwrapped longtable exactly as before,
    regardless of column count.

    Args:
        self: LaTeX translator instance.
        tasks: List of DotoTask objects.
        columns: Column names to display.
    """
    from doxtr_doto.fields import COLUMN_LABELS

    # Build column specification using configurable specs
    app = getattr(self.builder, 'app', None)
    col_specs = [_get_latex_column_spec(col, app) for col in columns]
    col_spec = "|".join(col_specs)

    # Assemble the longtable into a local buffer so it can optionally be wrapped
    # in a landscape environment before being appended to the body.
    parts: list[str] = []
    parts.append(f'\\begin{{longtable}}{{|{col_spec}|}}\n')
    parts.append('\\hline\n')

    # Header row - use central column labels
    header_cells = " & ".join(
        f'\\textbf{{{COLUMN_LABELS.get(c, c.title())}}}' for c in columns
    )
    parts.append(f'{header_cells} \\\\\n\\hline\n\\endfirsthead\n')

    # Continuation header for multi-page tables
    parts.append(f'\\hline\n{header_cells} \\\\\n\\hline\n\\endhead\n')

    # Data rows
    for task in tasks:
        cells = []
        for col in columns:
            # Icon-mode aware, clickable id/title (Feature 5).
            cells.append(_render_cell_latex(task, col, mode, icons))
        parts.append(" & ".join(cells) + " \\\\\n\\hline\n")

    parts.append('\\end{longtable}\n\n')
    table_latex = "".join(parts)

    # Feature 6: auto-rotate wide tables to landscape when the core is active.
    # Only wrap when integrated AND the table is wide enough; standalone output
    # (and narrow tables) stay as a plain longtable.
    if app is not None and _should_landscape_task_table(app, len(columns)):
        from doxtr_doto.integration.doxtr import wrap_longtable_in_landscape
        table_latex = wrap_longtable_in_landscape(table_latex, len(columns))

    self.body.append(table_latex)


def _should_landscape_task_table(app: Any, col_count: int) -> bool:
    """Decide whether a task table should be rotated to landscape.

    Returns True only when ``doxtr-pdf-theme-core`` is active, the core's
    auto-landscape feature is enabled, and the column count meets the core's
    landscape threshold. Standalone builds always return False so their output
    is unchanged.

    Args:
        app: Sphinx application instance.
        col_count: Number of columns in the task table.

    Returns:
        True if the table should be wrapped in a landscape environment.
    """
    from doxtr_doto.integration.doxtr import (
        detect_doxtr_features,
        get_landscape_min_columns,
    )

    if not detect_doxtr_features(app)["pdf_backend"]:
        return False
    # Honor the core's global auto-landscape switch.
    if not getattr(app.config, "doxtr_table_auto_landscape", True):
        return False
    return col_count >= get_landscape_min_columns(app)


def _render_task_list_latex(
    self: LaTeXTranslator,
    tasks: list,
    mode: str = "icon-text",
    icons: dict[str, dict[str, tuple[str | None, str | None]]] | None = None,
) -> None:
    """Render a doto task list as a LaTeX description list.

    The item label (task id) and title are clickable links to the task box, and
    the icon mode (Feature 5) selects whether metadata is shown as icons,
    icon+text, or plain text.

    Args:
        self: LaTeXTranslator instance.
        tasks: List of DotoTask objects to render.
        mode: Effective icon mode.
    """
    self.body.append('\\begin{description}\n')
    for task in tasks:
        # id label (clickable), title (clickable).
        id_cell = _render_cell_latex(task, "id", mode, icons)
        title_cell = _render_cell_latex(task, "title", mode, icons)
        # Metadata cells honor the icon mode too.
        meta_cells = [
            _render_cell_latex(task, "priority", mode, icons),
            _render_cell_latex(task, "status", mode, icons),
        ]
        if task.assignee:
            meta_cells.append(_render_cell_latex(task, "assignee", mode, icons))
        if task.due:
            meta_cells.append(_render_cell_latex(task, "due", mode, icons))
        meta = ", ".join(c for c in meta_cells if c)
        self.body.append(
            f'\\item[{id_cell}] {title_cell} \\hfill \\textit{{({meta})}}\n'
        )
    self.body.append('\\end{description}\n\n')


def _latex_escape(text: str) -> str:
    """Escape LaTeX special characters in text."""
    if not text:
        return ""
    # Order matters: & must be escaped before adding more &
    replacements = [
        ('\\', '\\textbackslash{}'),
        ('&', '\\&'),
        ('%', '\\%'),
        ('$', '\\$'),
        ('#', '\\#'),
        ('_', '\\_'),
        ('{', '\\{'),
        ('}', '\\}'),
        ('~', '\\textasciitilde{}'),
        ('^', '\\textasciicircum{}'),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def depart_doto_list_node_latex(self: LaTeXTranslator, node: doto_list_node) -> None:
    """Depart handler for doto_list_node in LaTeX output."""
    pass  # Content generated and SkipNode raised in visit handler


def visit_doto_summary_node_html(self: HTML5Translator, node: doto_summary_node) -> None:
    """Visit handler for doto_summary_node in HTML output."""
    from doxtr_doto.collectors import filter_tasks, get_doto_env
    
    # Get configuration from node
    config = node.get("config", {})
    filters = node.get("filters", {})
    group_by = config.get("group_by", ["status"])
    show_chart = config.get("show_chart", False)
    
    self.body.append('<div class="doto-summary">\n')
    
    # Get tasks from environment and filter them
    env = self.builder.env
    doto_env = get_doto_env(env)
    # For summary, we include all non-archived tasks by default
    display_config = {"show_archived": False}
    filtered_tasks = filter_tasks(doto_env.all_tasks, filters, display_config)
    
    if not filtered_tasks:
        self.body.append('<p class="doto-summary-empty">No tasks found.</p>\n')
        return
    
    # Generate statistics
    total_tasks = len(filtered_tasks)
    
    # Calculate stats for each group_by field
    self.body.append('<div class="doto-summary-stats">\n')
    self.body.append(f'<div class="doto-summary-stat doto-summary-total">\n')
    self.body.append(f'<span class="doto-summary-stat-value">{total_tasks}</span>\n')
    self.body.append('<span class="doto-summary-stat-label">Total</span>\n')
    self.body.append('</div>\n')
    
    for field in group_by:
        stats = _calculate_group_stats(filtered_tasks, field)
        for label, count in stats.items():
            css_class = f"doto-summary-{field}-{label.lower().replace(' ', '-')}"
            self.body.append(f'<div class="doto-summary-stat {escape_html_attr(css_class)}">\n')
            self.body.append(f'<span class="doto-summary-stat-value">{count}</span>\n')
            self.body.append(f'<span class="doto-summary-stat-label">{escape_html_content(label)}</span>\n')
            self.body.append('</div>\n')
    self.body.append('</div>\n')
    
    # Generate charts if enabled
    if show_chart:
        chart_type = config.get("chart_type", "bar")
        chart_html = _render_summary_chart_html(self, filtered_tasks, group_by, chart_type)
        self.body.append(chart_html)


def _render_summary_chart_html(
    self: HTML5Translator,
    tasks: list,
    group_by: list[str],
    chart_type: str,
) -> str:
    """Render summary charts for HTML, honoring the ``doto_chart_engine`` config.

    When ``doto_chart_engine`` is ``plotly`` and plotly/kaleido are available, a
    static PNG is written into the build output's ``_static`` directory and an
    ``<img>`` tag is returned. Otherwise (engine ``svg``, or plotly/kaleido
    unavailable, or export failure) this falls back to the built-in inline SVG
    charts so the build never breaks (Feature 7).

    Args:
        self: HTML5Translator instance.
        tasks: Filtered tasks to chart.
        group_by: Group-by fields.
        chart_type: Requested chart type.

    Returns:
        HTML string for the chart(s).
    """
    from doxtr_doto.charts import (
        generate_summary_charts,
        generate_summary_charts_plotly_html,
    )
    from doxtr_doto.config import get_config

    app = getattr(self.builder, "app", None)
    engine = get_config(app, "chart_engine") if app is not None else "svg"

    if engine == "plotly":
        import os

        outdir = getattr(self.builder, "outdir", None)
        if outdir is not None:
            static_dir = os.path.join(str(outdir), "_static")
            html = generate_summary_charts_plotly_html(
                tasks, group_by, chart_type, static_dir
            )
            if html is not None:
                _record_chart_image(app, static_dir, tasks, group_by, chart_type)
                return html
        # Fall through to SVG on any unavailability/failure.

    return generate_summary_charts(tasks, group_by, chart_type=chart_type)


def _record_chart_image(
    app: Any,
    directory: str,
    tasks: list,
    group_by: list[str],
    chart_type: str,
) -> None:
    """Record a produced plotly chart image path on the app for later cleanup.

    The build-finished handler in ``directives/doto_summary.py`` prunes
    ``doto-chart-*`` images that were not produced during the build; this
    registers the absolute path of an image just rendered so it is preserved.

    Args:
        app: Sphinx application instance (may be None).
        directory: Directory the image was written into.
        tasks: Tasks the chart was built from.
        group_by: Group-by fields.
        chart_type: Chart type.
    """
    if app is None:
        return
    import os

    from doxtr_doto.charts import _chart_filename

    filename = _chart_filename(tasks, group_by, chart_type, "png")
    abspath = os.path.abspath(os.path.join(directory, filename))
    produced = getattr(app, "_doto_chart_images", None)
    if produced is None:
        produced = set()
        app._doto_chart_images = produced
    produced.add(abspath)


def _calculate_group_stats(tasks: list, field: str) -> dict[str, int]:
    """Calculate statistics grouped by a field.
    
    Counts tasks grouped by the specified field (status, priority, assignee, or tags).
    For status and priority fields, returns counts in a consistent display order.
    
    Args:
        tasks: List of DotoTask objects to analyze.
        field: Field to group by ('status', 'priority', 'assignee', or 'tags').
        
    Returns:
        Dictionary mapping field values to task counts. Zero counts are excluded.
    """
    stats: dict[str, int] = {}
    
    if field == "status":
        # Use constant for ordering
        for status in STATUS_DISPLAY_ORDER:
            stats[status] = 0
        for task in tasks:
            status = task.status.lower()
            stats[status] = stats.get(status, 0) + 1
        # Remove zero counts
        stats = {k: v for k, v in stats.items() if v > 0}
    elif field == "priority":
        # Use constant for ordering
        for priority in PRIORITY_DISPLAY_ORDER:
            stats[priority] = 0
        for task in tasks:
            priority = task.priority.lower()
            stats[priority] = stats.get(priority, 0) + 1
        # Remove zero counts
        stats = {k: v for k, v in stats.items() if v > 0}
    elif field == "assignee":
        for task in tasks:
            assignee = task.assignee or "Unassigned"
            stats[assignee] = stats.get(assignee, 0) + 1
    elif field == "tags":
        for task in tasks:
            if task.tags:
                for tag in task.tags:
                    stats[tag] = stats.get(tag, 0) + 1
            else:
                stats["(no tags)"] = stats.get("(no tags)", 0) + 1
    
    return stats


def depart_doto_summary_node_html(self: HTML5Translator, node: doto_summary_node) -> None:
    """Depart handler for doto_summary_node in HTML output."""
    self.body.append('</div>\n')


def visit_doto_summary_node_latex(
    self: LaTeXTranslator,
    node: doto_summary_node,
) -> None:
    """Visit handler for doto_summary_node in LaTeX output."""
    from doxtr_doto.collectors import filter_tasks, get_doto_env

    config = node.get("config", {})
    filters = node.get("filters", {})
    group_by = config.get("group_by", ["status"])
    env = self.builder.env
    doto_env = get_doto_env(env)
    tasks = filter_tasks(doto_env.all_tasks, filters, {"show_archived": False})

    if not tasks:
        self.body.append('\\textit{No tasks found.}\n\n')
        raise nodes.SkipNode

    total = len(tasks)
    self.body.append('\n\\textbf{Total tasks:} ' + str(total) + '\n\n')

    # Feature 7: when the plotly engine is active and a chart is requested,
    # export a static image with kaleido and \includegraphics it. Any
    # unavailability/failure falls through to the textual breakdown below so
    # the PDF build never crashes.
    if config.get("show_chart"):
        chart_type = config.get("chart_type", "bar")
        _emit_summary_chart_latex(self, tasks, group_by, chart_type)

    for field in group_by:
        stats = _calculate_group_stats(tasks, field)
        self.body.append(
            f'\\textbf{{{field.title()} breakdown:}}\n'
            '\\begin{itemize}\n'
        )
        for label, count in stats.items():
            pct = round(count / total * 100) if total else 0
            self.body.append(
                f'\\item {_latex_escape(label)}: {count} ({pct}\\%)\n'
            )
        self.body.append('\\end{itemize}\n\n')

    raise nodes.SkipNode


def _emit_summary_chart_latex(
    self: LaTeXTranslator,
    tasks: list,
    group_by: list[str],
    chart_type: str,
) -> None:
    r"""Emit a summary chart into the PDF, always producing a visual.

    Selection order:

    1. If ``doto_chart_engine`` is ``plotly`` and plotly/kaleido are available,
       export a static PNG with kaleido and ``\includegraphics`` it.
    2. Otherwise (engine ``svg``, or plotly/kaleido unavailable, or export
       failure), render a **native-LaTeX chart** via the themeable
       ``\dotochart*`` macros in ``doto.sty`` (tikz bars / pie / progress /
       burndown line). No browser or kaleido is required, so the PDF always
       shows a real chart.
    3. The textual breakdown emitted by the caller remains as a final fallback
       only when even native rendering cannot produce anything.

    Args:
        self: LaTeX translator instance.
        tasks: Filtered tasks to chart.
        group_by: Group-by fields.
        chart_type: Requested chart type.
    """
    import os

    from doxtr_doto.charts import (
        generate_summary_charts_latex,
        render_plotly_chart_image,
    )
    from doxtr_doto.config import get_config

    app = getattr(self.builder, "app", None)
    engine = get_config(app, "chart_engine") if app is not None else "svg"

    # 1. Plotly PNG path (only when explicitly selected and available).
    if app is not None and engine == "plotly":
        outdir = getattr(self.builder, "outdir", None)
        if outdir is not None:
            # LaTeX resolves \includegraphics paths relative to the build
            # outdir; write the image into an _images subdir there so it sits
            # alongside other figures.
            images_dir = os.path.join(str(outdir), "_images")
            filename = render_plotly_chart_image(
                tasks, group_by, chart_type, images_dir, image_format="png"
            )
            if filename is not None:
                _record_chart_image(app, images_dir, tasks, group_by, chart_type)
                # Use a forward-slash relative path so it works on the LaTeX side.
                graphic = f"_images/{filename}"
                self.body.append(
                    "\n\\begin{center}\n"
                    f"\\includegraphics[width=0.8\\linewidth]{{{graphic}}}\n"
                    "\\end{center}\n\n"
                )
                return
        # Fall through to the native-LaTeX chart on any unavailability/failure.

    # 2. Native-LaTeX chart (default; no browser/kaleido needed).
    latex_chart = generate_summary_charts_latex(tasks, group_by, chart_type)
    if latex_chart:
        self.body.append("\n" + latex_chart + "\n")
    # 3. Otherwise the caller's textual breakdown remains as the final fallback.


def depart_doto_summary_node_latex(
    self: LaTeXTranslator,
    node: doto_summary_node,
) -> None:
    """Depart handler for doto_summary_node in LaTeX output."""
    pass  # SkipNode raised in visit handler


# --- doto_ref visitors ---

def visit_doto_ref_html(self: HTML5Translator, node: doto_ref) -> None:
    """Visit handler for doto_ref in HTML output."""
    task_id = node.get('reftarget', '')
    refuri = node.get('refuri', f'#{task_id}')
    title = node.get('title', task_id)
    self.body.append(f'<a class="doto-ref" href="{escape_html_attr(refuri)}" title="{escape_html_attr(title)}">')


def depart_doto_ref_html(self: HTML5Translator, node: doto_ref) -> None:
    """Depart handler for doto_ref in HTML output."""
    self.body.append('</a>')


def visit_doto_ref_latex(self: LaTeXTranslator, node: doto_ref) -> None:
    """Visit handler for doto_ref in LaTeX output."""
    task_id = node.get('reftarget', '')
    self.body.append(f'\\dotoref{{{task_id}}}')


def depart_doto_ref_latex(self: LaTeXTranslator, node: doto_ref) -> None:
    """Depart handler for doto_ref in LaTeX output."""
    pass


# --- epub visitors (delegate to HTML) ---

def visit_doto_node_epub(self: HTML5Translator, node: doto_node) -> None:
    """Visit handler for doto_node in epub output (delegates to HTML)."""
    visit_doto_node_html(self, node)


def depart_doto_node_epub(self: HTML5Translator, node: doto_node) -> None:
    """Depart handler for doto_node in epub output (delegates to HTML)."""
    depart_doto_node_html(self, node)


def visit_doto_list_node_epub(self: HTML5Translator, node: doto_list_node) -> None:
    """Visit handler for doto_list_node in epub output (delegates to HTML)."""
    visit_doto_list_node_html(self, node)


def depart_doto_list_node_epub(self: HTML5Translator, node: doto_list_node) -> None:
    """Depart handler for doto_list_node in epub output (delegates to HTML)."""
    depart_doto_list_node_html(self, node)


def visit_doto_summary_node_epub(self: HTML5Translator, node: doto_summary_node) -> None:
    """Visit handler for doto_summary_node in epub output (delegates to HTML)."""
    visit_doto_summary_node_html(self, node)


def depart_doto_summary_node_epub(self: HTML5Translator, node: doto_summary_node) -> None:
    """Depart handler for doto_summary_node in epub output (delegates to HTML)."""
    depart_doto_summary_node_html(self, node)


def visit_doto_ref_epub(self: HTML5Translator, node: doto_ref) -> None:
    """Visit handler for doto_ref in epub output (delegates to HTML)."""
    visit_doto_ref_html(self, node)


def depart_doto_ref_epub(self: HTML5Translator, node: doto_ref) -> None:
    """Depart handler for doto_ref in epub output (delegates to HTML)."""
    depart_doto_ref_html(self, node)
