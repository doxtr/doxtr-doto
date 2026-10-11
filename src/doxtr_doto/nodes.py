"""Custom docutils nodes for doto directives."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from docutils import nodes

from doxtr_doto.constants import (
    DEFAULT_PRIORITY,
    DEFAULT_STATUS,
    PRIORITY_CLASSES,
    PRIORITY_DISPLAY_ORDER,
    STATUS_CLASSES,
    STATUS_DISPLAY_ORDER,
    VALID_LATEX_LAYOUTS,
    VALID_LIST_ICON_MODES,
)
from doxtr_doto.fields import XLINK_FIELDS
from doxtr_doto.utils import (
    escape_html_attr,
    escape_html_content,
    sanitize_html_id,
)

# Column specifications for LaTeX tables
LATEX_COLUMN_SPECS: dict[str, str] = {
    "id": r"l",  # Left-aligned, auto width
    "title": r"p{5cm}",  # Paragraph, 5cm width
    "priority": r"c",  # Centered
    "status": r"c",  # Centered
    "assignee": r"l",  # Left-aligned
    "due": r"c",  # Centered (dates)
    "tags": r"p{3cm}",  # Paragraph for wrapping
    "created": r"c",  # Centered
    "updated": r"c",  # Centered
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

#: Compact-layout counterpart of :data:`_DOTO_BOX_ENVS` (Feature D). Selects the
#: ``dotoboxcompact<priority>`` tcolorbox variants defined in ``doto.sty`` so the
#: compact layout's tighter geometry is themeable in the ``.sty`` and a child
#: theme can override it. Unknown priorities fall back to
#: :data:`DEFAULT_COMPACT_BOX_ENV`.
DEFAULT_COMPACT_BOX_ENV = "dotoboxcompact"
_DOTO_COMPACT_BOX_ENVS: dict[str, str] = {
    "low": "dotoboxcompactlow",
    "medium": "dotoboxcompactmedium",
    "high": "dotoboxcompacthigh",
    "critical": "dotoboxcompactcritical",
}

#: Layout registry mapping a resolved layout name to its
#: ``(priority -> box-env map, default box env)`` pair (Feature D). This is the
#: single source of truth for which box environment each layout opens, so
#: :func:`_resolve_box_env` is one dict lookup and adding a third layout is one
#: entry rather than another ``if layout == ...`` branch. Unknown layouts fall
#: back to the ``default`` entry (see :func:`_resolve_box_env`). Kept in sync
#: with :data:`~doxtr_doto.constants.VALID_LATEX_LAYOUTS` by
#: ``tests/test_output_latex.py`` (so "valid" cannot drift from "renderable").
_LAYOUT_BOX_ENVS: dict[str, tuple[dict[str, str], str]] = {
    "default": (_DOTO_BOX_ENVS, DEFAULT_BOX_ENV),
    "compact": (_DOTO_COMPACT_BOX_ENVS, DEFAULT_COMPACT_BOX_ENV),
}

#: Field-level Font Awesome CSS class (HTML) keyed by list column.
LIST_FIELD_FA_HTML: dict[str, str | None] = {
    "id": "fa-solid fa-hashtag",
    "title": None,  # titles are text (and clickable) — no icon
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
        return str(override)
    if app is not None:
        from doxtr_doto.config import get_config

        mode = get_config(app, "list_icon_mode")
        if mode in VALID_LIST_ICON_MODES:
            return str(mode)
    return "icon-text"


def _resolve_latex_layout(node: Any, app: Any) -> str:
    """Resolve the effective PDF/LaTeX layout for a task box.

    A per-directive ``:latex-layout:`` override on the node wins when valid;
    otherwise the ``doto_latex_layout`` config value is used, defaulting to
    ``default``. An invalid value (directive or config) falls through to
    ``default`` so a bad layout name can never emit an undefined box environment.

    Args:
        node: The ``doto_node`` (may carry a ``latex_layout`` attribute).
        app: Sphinx application instance (may be None).

    Returns:
        One of the values in :data:`~doxtr_doto.constants.VALID_LATEX_LAYOUTS`
        (``default`` or ``compact``).
    """
    override = node.get("latex_layout") if hasattr(node, "get") else None
    if override in VALID_LATEX_LAYOUTS:
        return str(override)
    if app is not None:
        from doxtr_doto.config import get_config

        layout = get_config(app, "latex_layout")
        if layout in VALID_LATEX_LAYOUTS:
            return str(layout)
    return "default"


def _resolve_box_env(priority: str, layout: str) -> str:
    """Return the ``.sty`` box environment name for a priority and layout.

    The ``default`` layout maps to the roomy ``dotobox<priority>`` variants and
    the ``compact`` layout to the dense ``dotoboxcompact<priority>`` variants;
    both are defined (and overridable) in ``doto.sty``. The layout is looked up
    in :data:`_LAYOUT_BOX_ENVS` (falling back to the ``default`` entry for an
    unknown layout), then the priority is looked up in that entry's map
    (falling back to the layout's plain box for an unknown priority). Keeping
    the mapping here (rather than inline in the visitor) means a child theme
    overrides geometry by re-defining the ``.sty`` environment, never Python,
    and adding a third layout is a single registry entry.

    Args:
        priority: Task priority (any case; unknown priorities fall back).
        layout: Resolved layout (``default``/``compact``; unknown falls back
            to ``default``).

    Returns:
        The LaTeX environment name to open for the task box.
    """
    env_map, default_env = _LAYOUT_BOX_ENVS.get(layout, _LAYOUT_BOX_ENVS["default"])
    key = str(priority).lower()
    return env_map.get(key, default_env)


def _resolve_visible_tasks(display: Any, app: Any) -> int:
    """Resolve the effective visible-task cap for the email list pane.

    A per-directive ``:visible-tasks:`` override on the display options wins
    when it is valid (a non-negative int that is not a bool); otherwise the
    ``doto_list_visible_tasks`` config value is used when valid, defaulting to
    the canonical ``DEFAULTS`` value. The result caps how many task rows are
    visible at once in the scrollable list pane; a value of 0 means "show all"
    (no scroll cap). All matching tasks are always rendered regardless of this
    value.

    Args:
        display: Resolved ``DisplayOptions`` (may carry ``visible_tasks``; None
            there means "use config").
        app: Sphinx application instance (may be None).

    Returns:
        A non-negative integer; 0 means "no scroll cap".
    """
    from doxtr_doto.config import DEFAULTS, is_valid_visible_tasks

    # Validate the directive override with the same guard as the config path
    # so a stale/hand-constructed DisplayOptions (e.g. visible_tasks=-1) can
    # never emit invalid CSS; a bad override falls through to config/default.
    override = getattr(display, "visible_tasks", None)
    if override is not None and is_valid_visible_tasks(override):
        return int(override)
    if app is not None:
        from doxtr_doto.config import get_config

        value = get_config(app, "list_visible_tasks")
        if is_valid_visible_tasks(value):
            return int(value)
    return int(DEFAULTS["doto_list_visible_tasks"])


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
        return (
            html if isinstance(html, str) or html is None else None,
            latex if isinstance(latex, str) or latex is None else None,
        )
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

    def _pairs(
        html_map: Mapping[str, str | None], latex_map: Mapping[str, str | None]
    ) -> dict[str, tuple[str | None, str | None]]:
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
    from sphinx.application import Sphinx
    from sphinx.writers.html5 import HTML5Translator
    from sphinx.writers.latex import LaTeXTranslator

    from doxtr_doto.collectors import DotoTask
    from doxtr_doto.query import DisplayOptions


# docutils ships no type stubs, so its node base classes are seen as Any by
# mypy and subclassing them trips disallow_subclassing_any (strict mode).
class doto_node(nodes.General, nodes.Element):  # type: ignore[misc]
    """Node representing a single doto task."""

    def __init__(
        self,
        rawsource: str = "",
        *children: nodes.Node,
        **attributes: Any,
    ) -> None:
        super().__init__(rawsource, *children, **attributes)


class doto_list_node(nodes.General, nodes.Element):  # type: ignore[misc]
    """Node representing a filtered list of tasks."""

    def __init__(
        self,
        rawsource: str = "",
        *children: nodes.Node,
        **attributes: Any,
    ) -> None:
        super().__init__(rawsource, *children, **attributes)


class doto_summary_node(nodes.General, nodes.Element):  # type: ignore[misc]
    """Node representing task statistics summary."""

    def __init__(
        self,
        rawsource: str = "",
        *children: nodes.Node,
        **attributes: Any,
    ) -> None:
        super().__init__(rawsource, *children, **attributes)


class doto_archive_node(nodes.General, nodes.Element):  # type: ignore[misc]
    """Node representing the archive page's archived-task listing.

    Rendered from the JSON task store / build environment rather than from any
    RST directives in the source, so the archive page reflects exactly what has
    been archived. Rendering goes through the theme/template system (same as
    doto-list), so a child theme can override it.
    """

    def __init__(
        self,
        rawsource: str = "",
        *children: nodes.Node,
        **attributes: Any,
    ) -> None:
        super().__init__(rawsource, *children, **attributes)


class doto_ref(nodes.Inline, nodes.Element):  # type: ignore[misc]
    """Node representing a cross-reference to a task."""

    pass


def visit_doto_node_html(self: HTML5Translator, node: doto_node) -> None:
    """Visit handler for doto_node in HTML output.

    Uses Jinja2 templates if available, otherwise falls back to Python rendering.
    Templates can be overridden by placing files in _doto/templates/html/.
    """
    from doxtr_doto.template_loader import render_template
    from doxtr_doto.xlink import resolve_field_value

    task_id = node.get("task_id", "")
    title = node.get("title", "")
    priority = node.get("priority", DEFAULT_PRIORITY)
    status = node.get("status", DEFAULT_STATUS)
    assignee = node.get("assignee", "")
    # Display the due with its optional time as ``YYYY-MM-DD HH:MM`` (date-only
    # is unchanged). Formatting is centralized in date_utils so a child theme
    # that overrides the template still receives a sensibly-formatted value and
    # never has to re-parse the ISO ``T`` form.
    from doxtr_doto.date_utils import format_date_display

    due = format_date_display(node.get("due", ""))
    tags = node.get("tags", [])
    progress = node.get("progress")
    raci = node.get("raci")
    is_overdue = node.get("is_overdue", False)

    # Resolve any :xlink: tokens in the assignee at render time (graceful no-op
    # when sphinxcontrib-xlink is absent/disabled). The stored value is never
    # mutated. When the token resolves to a URL, pass it as assignee_href so the
    # template can emit a real link.
    app = getattr(self.builder, "app", None)
    assignee_href = ""
    if assignee:
        assignee, url = resolve_field_value(app, str(assignee))
        assignee_href = url or ""

    # Build CSS classes
    priority_class = PRIORITY_CLASSES.get(priority, "")
    status_class = STATUS_CLASSES.get(status, "")
    classes = " ".join(
        c for c in ["doto", priority_class, status_class, "doto-overdue" if is_overdue else ""] if c
    )

    # Render RACI subsection (overridable via register_raci_html_renderer)
    from doxtr_doto.raci import render_raci_html

    raci_html = render_raci_html(raci)

    # Get srcdir for template overrides
    srcdir = getattr(self.builder, "srcdir", None)

    # Render template
    html = render_template(
        "doto.html",
        {
            "task_id": task_id,
            "title": title,
            "priority": priority,
            "status": status,
            "assignee": assignee,
            "assignee_href": assignee_href,
            "due": due,
            "tags": tags,
            "progress": progress,
            "raci_html": raci_html,
            "is_overdue": is_overdue,
            "classes": classes,
        },
        srcdir=srcdir,
    )

    # Split at body div so Sphinx can render children into it
    # The template should contain: <div class="doto-body">\n  </div>
    body_marker = '<div class="doto-body">'
    if body_marker in html:
        parts = html.split(body_marker, 1)
        self.body.append(parts[0] + body_marker + "\n")
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
    r"""Visit handler for doto_node in LaTeX output.

    Emits a hyperlink anchor so ``:doto:`ID``` cross-references resolve, opens a
    priority-specific box environment and renders the task's metadata into the
    box body. The box environment and body layout are selected by the resolved
    PDF layout (``doto_latex_layout``):

    * ``default`` opens ``dotobox<priority>`` (``dotoboxlow`` / ``dotoboxmedium``
      / ``dotoboxhigh`` / ``dotoboxcritical``, falling back to the plain
      ``dotobox``) with the title as a styled title bar and renders the metadata
      as roomy stacked-icon rows via the ``\dotometa*`` macros.
    * ``compact`` opens the matching ``dotoboxcompact<priority>`` variant and
      renders the SAME fields densely via the ``\dotocompact*`` macros (a
      single-line header plus inline icon+value pairs). No detail is dropped.

    All visual specifics (box geometry, icon placement) live in those ``.sty``
    macros so a child theme can override either layout by shipping its own
    ``doto.sty`` (or a project ``_doto/latex/*.sty``, discovered in
    ``__init__.py``). There is intentionally no Jinja LaTeX template seam: the
    box body is emitted by this translator via node traversal, so the ``.sty``
    macros are the single override surface for the LaTeX box.
    """
    task_id = node.get("task_id", "")
    title = node.get("title", "")
    priority = node.get("priority", DEFAULT_PRIORITY)
    docname = node.get("docname", "")

    # Emit the cross-reference anchor matching what the domain resolver targets,
    # so :doto:`ID` links become clickable and the "Hyper reference ... undefined"
    # LaTeX warnings for doto IDs disappear.
    label = _latex_task_label(docname, task_id)
    self.body.append(f"\\dotolabel{{{label}}}\n")

    # Resolve the layout (per-directive override or doto_latex_layout config)
    # and select the matching, overridable box environment from doto.sty. The
    # chosen environment is stored on the node so the depart handler closes it.
    app = getattr(self.builder, "app", None)
    layout = _resolve_latex_layout(node, app)
    box_env = _resolve_box_env(str(priority), layout)
    node["_box_env"] = box_env
    self.body.append(f"\\begin{{{box_env}}}[{_latex_escape(title)}]\n")

    # Dispatch the box body through the layout-emitter registry (one lookup,
    # falling back to the default emitter for an unknown layout) rather than an
    # ``if layout == ...`` branch, so a third layout is one registry entry.
    emitter = _LAYOUT_BODY_EMITTERS.get(layout, _LAYOUT_BODY_EMITTERS["default"])
    emitter(self, node)


@dataclass
class _DotoBoxFields:
    """The task metadata fields both LaTeX box-body emitters consume.

    Extracted once by :func:`_doto_box_fields` so the default and compact body
    emitters read the node through a single helper instead of each repeating
    the same ``node.get(...)`` block (if a field is added/renamed on the node,
    only :func:`_doto_box_fields` changes).

    Attributes:
        task_id: Task identifier.
        title: Task title (used by the compact header).
        priority: Task priority (unresolved; the emitters color it).
        status: Task status.
        assignee: Assignee display string (may be empty).
        due: Due date string (may be empty).
        created: Created timestamp string (may be empty).
        updated: Updated timestamp string (may be empty).
        tags: Tag strings.
        is_overdue: Whether the task is overdue (wraps ``due`` in the overdue
            macro).
        raci: Raw RACI payload (``None`` when absent).
    """

    task_id: str
    title: str
    priority: str
    status: str
    assignee: str
    due: str
    created: str
    updated: str
    tags: list[str]
    is_overdue: bool
    raci: Any


def _doto_box_fields(node: doto_node) -> _DotoBoxFields:
    """Extract the task metadata both box-body emitters render.

    The single source of the node field read shared by
    :func:`_emit_doto_box_body_default` and :func:`_emit_doto_box_body_compact`
    so the ~9-field extraction is not duplicated across the two emitters.

    Args:
        node: The ``doto_node`` carrying the task fields.

    Returns:
        A :class:`_DotoBoxFields` with every field the emitters need.
    """
    from doxtr_doto.date_utils import format_date_display

    return _DotoBoxFields(
        task_id=node.get("task_id", ""),
        title=node.get("title", ""),
        priority=node.get("priority", DEFAULT_PRIORITY),
        status=node.get("status", DEFAULT_STATUS),
        assignee=node.get("assignee", ""),
        # Display the due's optional time as ``YYYY-MM-DD HH:MM`` (date-only
        # unchanged). Centralized in date_utils so both LaTeX emitters agree.
        due=format_date_display(node.get("due", "")),
        created=node.get("created", ""),
        updated=node.get("updated", ""),
        tags=node.get("tags", []),
        is_overdue=node.get("is_overdue", False),
        raci=node.get("raci"),
    )


def _emit_doto_box_body_default(self: LaTeXTranslator, node: doto_node) -> None:
    """Emit the default (roomy) task-box body via the ``\\dotometa*`` macros.

    Renders each metadata group on its own row (id/priority, status,
    assignee/due, created/updated, tags, raci) as stacked icon-over-label
    cells. This is the original default-layout body, factored out so the layout
    dispatch in :func:`visit_doto_node_latex` stays small and a child theme can
    swap only one layout. Output is byte-identical to the pre-Feature-D path.

    Args:
        self: LaTeXTranslator instance.
        node: The ``doto_node`` carrying the task fields.
    """
    fields = _doto_box_fields(node)
    task_id = fields.task_id
    priority = fields.priority
    status = fields.status
    assignee = fields.assignee
    due = fields.due
    created = fields.created
    updated = fields.updated
    tags = fields.tags
    is_overdue = fields.is_overdue

    # Metadata row: ID + priority (priority colored by severity via macro).
    self.body.append(f"\\dotometaid{{{_latex_escape(task_id)}}}\\hfill ")
    priority_display = _latex_escape(priority)
    self.body.append(
        f"\\dotometapriority{{\\dotopriorityvalue{{{priority}}}{{{priority_display}}}}}\n\n"
    )

    # Status row.
    self.body.append(f"\\dotometastatus{{{_latex_escape(status)}}}\n\n")

    if assignee or due:
        if assignee:
            self.body.append(f"\\dotometaassignee{{{_latex_assignee(self, assignee)}}}")
        if due:
            if assignee:
                self.body.append("\\hfill ")
            due_text = _latex_escape(due)
            if is_overdue:
                due_text = f"\\dotooverdue{{{due_text}}}"
            self.body.append(f"\\dotometadue{{{due_text}}}")
        self.body.append("\n\n")

    if created or updated:
        if created:
            self.body.append(f"\\dotometacreated{{{_latex_escape(created)}}}")
        if updated:
            if created:
                self.body.append("\\hfill ")
            self.body.append(f"\\dotometaupdated{{{_latex_escape(updated)}}}")
        self.body.append("\n\n")

    if tags:
        tag_text = ", ".join(_latex_escape(t) for t in tags)
        self.body.append(f"\\dotometatags{{{tag_text}}}\n\n")

    raci = fields.raci
    if raci:
        from doxtr_doto.raci import render_raci_compact

        compact = render_raci_compact(raci)
        if compact:
            self.body.append(f"\\dotometaraci{{{_latex_escape(compact)}}}\n\n")


def _emit_doto_box_body_compact(self: LaTeXTranslator, node: doto_node) -> None:
    r"""Emit the compact task-box body via the ``\dotocompact*`` macros.

    Lays out the SAME fields as :func:`_emit_doto_box_body_default` (id,
    priority, status, assignee, due, created, updated, tags, raci) much more
    densely: a single-line header (title + id + priority + status) via
    ``\dotocompactheader``, a thin ``\dotocompactrule`` separator, then the
    remaining fields as inline ``\dotocompactfield{icon}{value}`` pairs joined
    by ``\dotocompactsep`` so several fields flow onto one line. Icons are
    grouped inline rather than stacked per-row (the Feature-D icon layout).

    No field is dropped relative to the default layout; only the geometry is
    denser. All visual constants live in the ``.sty`` macros so a child theme
    overrides the compact look there, never in Python.

    Args:
        self: LaTeXTranslator instance.
        node: The ``doto_node`` carrying the task fields.
    """
    fields = _doto_box_fields(node)
    task_id = fields.task_id
    priority = fields.priority
    status = fields.status
    assignee = fields.assignee
    due = fields.due
    created = fields.created
    updated = fields.updated
    tags = fields.tags
    is_overdue = fields.is_overdue

    # Single-line header: title + id + priority (severity-colored) + status.
    priority_display = _latex_escape(priority)
    priority_value = f"\\dotopriorityvalue{{{priority}}}{{{priority_display}}}"
    self.body.append(
        "\\dotocompactheader"
        f"{{{_latex_escape(fields.title)}}}"
        f"{{{_latex_escape(task_id)}}}"
        f"{{{priority_value}}}"
        f"{{{_latex_escape(status)}}}\n"
    )

    # Build the inline icon+value field pairs for the remaining fields. Each
    # pair uses the field-level FA macro from LIST_FIELD_FA_LATEX so icon
    # placement is a single source of truth shared with the task-list renderer.
    pairs: list[str] = []

    def _add(field: str, value: str) -> None:
        icon = LIST_FIELD_FA_LATEX.get(field) or ""
        pairs.append(f"\\dotocompactfield{{{icon}}}{{{value}}}")

    if assignee:
        _add("assignee", _latex_assignee(self, assignee))
    if due:
        due_text = _latex_escape(due)
        if is_overdue:
            due_text = f"\\dotooverdue{{{due_text}}}"
        _add("due", due_text)
    if created:
        _add("created", _latex_escape(created))
    if updated:
        _add("updated", _latex_escape(updated))
    if tags:
        _add("tags", ", ".join(_latex_escape(t) for t in tags))

    raci = fields.raci
    if raci:
        from doxtr_doto.raci import render_raci_compact

        raci_compact = render_raci_compact(raci)
        if raci_compact:
            # No field-level FA macro for raci in LIST_FIELD_FA_LATEX; reuse the
            # stacked-icon \faUsers glyph so the pair still carries an icon.
            pairs.append(f"\\dotocompactfield{{\\faUsers}}{{{_latex_escape(raci_compact)}}}")

    if pairs:
        self.body.append("\\dotocompactrule\n")
        self.body.append("\\dotocompactsep".join(pairs) + "\n\n")


#: Layout registry mapping a resolved layout name to its box-body emitter
#: (Feature D). The single source of truth for which emitter renders each
#: layout's body, so :func:`visit_doto_node_latex` dispatches with one dict
#: lookup (falling back to the ``default`` emitter for an unknown layout)
#: rather than an ``if layout == ...`` branch. Adding a third layout is one
#: entry here plus one in :data:`_LAYOUT_BOX_ENVS`. Kept in sync with
#: :data:`~doxtr_doto.constants.VALID_LATEX_LAYOUTS` by
#: ``tests/test_output_latex.py``.
_LAYOUT_BODY_EMITTERS: dict[str, Callable[[LaTeXTranslator, doto_node], None]] = {
    "default": _emit_doto_box_body_default,
    "compact": _emit_doto_box_body_compact,
}


def depart_doto_node_latex(self: LaTeXTranslator, node: doto_node) -> None:
    """Depart handler for doto_node in LaTeX output.

    Closes the priority-specific box environment opened in the visit handler
    (stored on the node), falling back to ``dotobox`` if it was not recorded.
    """
    box_env = node.get("_box_env", DEFAULT_BOX_ENV)
    self.body.append(f"\\end{{{box_env}}}\n")


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

    # Dispatch table for format-specific renderers. Every renderer takes the
    # uniform ``(self, tasks, display)`` signature and reads whatever it needs
    # from ``display`` (e.g. table reads ``display.columns``), so a new view is
    # a pure dict entry with no per-format branching here.
    renderer = _LIST_RENDERERS.get(format_type, _render_task_list)
    renderer(self, filtered_tasks, display)


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

    # Resolve :xlink: tokens in fields that opt in via XLINK_FIELDS (currently
    # :assignee:) at render time. Graceful no-op when xlink is absent/disabled;
    # stored value is untouched.
    xlink_href: str | None = None
    if col in XLINK_FIELDS and value:
        from doxtr_doto.xlink import resolve_field_value

        app = getattr(self.builder, "app", None)
        value, xlink_href = resolve_field_value(app, value)

    fa_class = _list_icon_html(col, value, icons) if mode in ("icon", "icon-text") else None

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
    elif xlink_href:
        href = xlink_href

    return {
        "value": value,
        "icon_class": fa_class,
        "show_icon": show_icon,
        "show_text": show_text,
        "sr_only": sr_only,
        "title": title,
        "href": href,
    }


def _render_task_table(
    self: HTML5Translator, tasks: list[DotoTask], display: DisplayOptions
) -> None:
    """Render tasks as an HTML table.

    Uses Jinja2 templates if available, otherwise falls back to Python rendering.
    Per-cell data (icon class, link href, sr-only flags, value) is passed as
    structured data so ``doto-list-table.html`` composes the ``<td>`` contents
    itself — the same way the cards/simple templates author their links/icons —
    making cell markup fully child-theme overridable (no raw-HTML injection).

    Args:
        self: HTML5Translator instance.
        tasks: List of DotoTask objects to render.
        display: Resolved display options; the column set is read from
            ``display.columns``.
    """
    from doxtr_doto.fields import COLUMN_LABELS
    from doxtr_doto.template_loader import render_template

    columns = display.columns
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

    html = render_template(
        "doto-list-table.html",
        {
            "tasks": tasks,
            "columns": columns,
            "column_labels": COLUMN_LABELS,
            "cell_data": cell_data,
            "icon_mode": mode,
        },
        srcdir=srcdir,
    )

    self.body.append(html)


def _build_task_links(self: HTML5Translator, tasks: list[DotoTask]) -> dict[str, str]:
    """Build the ``task.id -> href`` map used by every HTML list renderer.

    Centralizes the id-to-anchor mapping (Feature 5 clickable ids/titles) so the
    table/cards/list/kanban/calendar/email renderers share one source of truth
    instead of repeating the comprehension.

    Args:
        self: HTML5Translator instance.
        tasks: List of DotoTask objects to link.

    Returns:
        Dict mapping each task id to its in-document href.
    """
    return {getattr(t, "id", ""): _task_html_href(self, t) for t in tasks}


def _render_task_cards(
    self: HTML5Translator, tasks: list[DotoTask], display: DisplayOptions
) -> None:
    """Render tasks as cards.

    Uses Jinja2 templates if available, otherwise falls back to Python rendering.
    The card id/title are rendered as clickable links to the task box and the
    icon mode (Feature 5) is passed to the template.

    Args:
        self: HTML5Translator instance.
        tasks: List of DotoTask objects to render.
        display: Resolved display options (unused by this view; kept for the
            uniform renderer signature).
    """
    from doxtr_doto.template_loader import render_template
    from doxtr_doto.xlink import resolve_field_value

    srcdir = getattr(self.builder, "srcdir", None)
    app = getattr(self.builder, "app", None)
    node = getattr(self, "_doto_current_list_node", None)
    mode = _resolve_list_icon_mode(node, app)

    task_links = _build_task_links(self, tasks)

    # Resolve :xlink: tokens for the assignee (XLINK_FIELDS) so the cards view
    # matches table/list output instead of showing the raw token. Keyed by task
    # id: {assignee, assignee_href}. Graceful no-op when xlink is absent.
    card_data: dict[str, dict[str, str]] = {}
    for task in tasks:
        assignee = getattr(task, "assignee", "") or ""
        assignee_display, href = assignee, None
        if "assignee" in XLINK_FIELDS and assignee:
            assignee_display, href = resolve_field_value(app, assignee)
        card_data[getattr(task, "id", "")] = {
            "assignee": assignee_display,
            "assignee_href": href or "",
        }

    html = render_template(
        "doto-list-cards.html",
        {
            "tasks": tasks,
            "task_links": task_links,
            "card_data": card_data,
            "icon_mode": mode,
        },
        srcdir=srcdir,
    )

    self.body.append(html)


def _render_task_list(
    self: HTML5Translator, tasks: list[DotoTask], display: DisplayOptions
) -> None:
    """Render tasks as a simple list.

    Uses Jinja2 templates if available, otherwise falls back to Python rendering.
    The id/title are rendered as clickable links to the task box and the icon
    mode (Feature 5) is passed to the template.

    Args:
        self: HTML5Translator instance.
        tasks: List of DotoTask objects to render.
        display: Resolved display options (unused by this view; kept for the
            uniform renderer signature).
    """
    from doxtr_doto.template_loader import render_template
    from doxtr_doto.xlink import resolve_field_value

    srcdir = getattr(self.builder, "srcdir", None)
    app = getattr(self.builder, "app", None)
    node = getattr(self, "_doto_current_list_node", None)
    mode = _resolve_list_icon_mode(node, app)

    task_links = _build_task_links(self, tasks)

    # Resolve :xlink: tokens for the assignee (XLINK_FIELDS) so the simple list
    # matches the table/cards output. Keyed by task id. No-op when xlink absent.
    card_data: dict[str, dict[str, str]] = {}
    for task in tasks:
        assignee = getattr(task, "assignee", "") or ""
        assignee_display, href = assignee, None
        if "assignee" in XLINK_FIELDS and assignee:
            assignee_display, href = resolve_field_value(app, assignee)
        card_data[getattr(task, "id", "")] = {
            "assignee": assignee_display,
            "assignee_href": href or "",
        }

    html = render_template(
        "doto-list-simple.html",
        {
            "tasks": tasks,
            "task_links": task_links,
            "card_data": card_data,
            "icon_mode": mode,
        },
        srcdir=srcdir,
    )

    self.body.append(html)


def _list_status_columns(app: Any) -> list[tuple[str, str]]:
    """Return the ordered ``(status, label)`` columns for the kanban view.

    The configured statuses (``doto_statuses``) drive the columns so custom
    status sets stay in sync; display order follows
    :data:`STATUS_DISPLAY_ORDER` with any extra configured statuses appended.
    Labels come from :data:`STATUS_LABELS`, falling back to a title-cased
    status name for custom statuses.

    Args:
        app: Sphinx application instance (may be None).

    Returns:
        List of ``(status_value, display_label)`` pairs in column order.
    """
    from doxtr_doto.constants import STATUS_DISPLAY_ORDER, STATUS_LABELS

    statuses: list[str]
    if app is not None:
        from doxtr_doto.config import get_config

        configured = get_config(app, "statuses")
        statuses = list(configured) if configured else list(STATUS_DISPLAY_ORDER)
    else:
        statuses = list(STATUS_DISPLAY_ORDER)

    # Order: display-order first, then any remaining configured statuses.
    ordered: list[str] = [s for s in STATUS_DISPLAY_ORDER if s in statuses]
    ordered += [s for s in statuses if s not in ordered]
    return [(s, STATUS_LABELS.get(s, s.replace("-", " ").title())) for s in ordered]


def _group_tasks_by_status(
    tasks: list[DotoTask], columns: list[tuple[str, str]]
) -> dict[str, list[Any]]:
    """Group tasks into ``{status: [tasks]}`` using the column order.

    Statuses that are not among the configured columns fall into the first
    column so no task is silently dropped from the board/tree. Shared by the
    kanban and email views so the grouping/fallback rule has a single source.

    Args:
        tasks: List of DotoTask objects to group.
        columns: Ordered ``(status, label)`` pairs from
            :func:`_list_status_columns`.

    Returns:
        Dict mapping each column status to its list of tasks (in column order).
    """
    column_statuses = {status for status, _ in columns}
    fallback = columns[0][0] if columns else ""
    grouped: dict[str, list[Any]] = {status: [] for status, _ in columns}
    for task in tasks:
        status = getattr(task, "status", "") or fallback
        if status not in column_statuses:
            status = fallback
        if status in grouped:
            grouped[status].append(task)
    return grouped


def _render_task_kanban(
    self: HTML5Translator, tasks: list[DotoTask], display: DisplayOptions
) -> None:
    """Render tasks as a kanban board (status columns, client-side drag).

    Groups tasks into columns keyed by status and passes structured data to
    ``doto-list-kanban.html`` so the template composes all markup. Card ids and
    titles link to the task box (reusing :func:`_task_html_href`). Drag between
    columns is a client-side visual interaction handled by the vendored
    ``doto-views.js``; a static Sphinx build has no backend to persist a status
    change, so this is documented as visual-only.

    Args:
        self: HTML5Translator instance.
        tasks: List of DotoTask objects to render.
        display: Resolved display options (unused by this view; kept for the
            uniform renderer signature).
    """
    from doxtr_doto.template_loader import render_template

    srcdir = getattr(self.builder, "srcdir", None)
    app = getattr(self.builder, "app", None)
    node = getattr(self, "_doto_current_list_node", None)
    mode = _resolve_list_icon_mode(node, app)

    columns = _list_status_columns(app)
    grouped = _group_tasks_by_status(tasks, columns)

    task_links = _build_task_links(self, tasks)

    html = render_template(
        "doto-list-kanban.html",
        {
            "columns": columns,
            "grouped": grouped,
            "task_links": task_links,
            "icon_mode": mode,
        },
        srcdir=srcdir,
    )

    self.body.append(html)


def _calendar_month_grid(tasks: list[DotoTask]) -> dict[str, Any]:
    """Build the month-grid context for the calendar view.

    Determines the month to show from the earliest due date among tasks (or the
    current month when no task has a due date), lays out a Monday-first week
    grid of ``date`` cells (including leading/trailing padding days from the
    adjacent months), and buckets tasks onto their due day.

    Args:
        tasks: List of DotoTask objects.

    Returns:
        Dict with keys:
          * ``year`` / ``month`` — ints for the displayed month.
          * ``month_label`` — e.g. ``"August 2026"``.
          * ``weekday_labels`` — ordered short weekday names (Mon..Sun).
          * ``weeks`` — list of weeks; each week is a list of 7 day dicts with
            ``day`` (int), ``iso`` (YYYY-MM-DD), ``in_month`` (bool), and
            ``tasks`` (list of DotoTask whose due date is that day).
          * ``unscheduled`` — tasks without a parseable due date.
    """
    import calendar as _calendar
    from datetime import date as _date

    due_dates = [t.due_date for t in tasks if t.due_date is not None]
    if due_dates:
        anchor = min(due_dates)
    else:
        anchor = _date.today()
    year, month = anchor.year, anchor.month

    # Bucket tasks by their ISO due day; unscheduled tasks tracked separately.
    by_day: dict[str, list[Any]] = {}
    unscheduled: list[Any] = []
    for task in tasks:
        due = getattr(task, "due_date", None)
        if due is None:
            unscheduled.append(task)
            continue
        by_day.setdefault(due.isoformat(), []).append(task)

    cal = _calendar.Calendar(firstweekday=0)  # Monday-first
    weeks: list[list[dict[str, Any]]] = []
    for week in cal.monthdatescalendar(year, month):
        cells: list[dict[str, Any]] = []
        for day in week:
            iso = day.isoformat()
            cells.append(
                {
                    "day": day.day,
                    "iso": iso,
                    "in_month": day.month == month,
                    "tasks": by_day.get(iso, []),
                }
            )
        weeks.append(cells)

    weekday_labels = [_calendar.day_abbr[i] for i in range(7)]
    month_label = f"{_calendar.month_name[month]} {year}"

    return {
        "year": year,
        "month": month,
        "month_label": month_label,
        "weekday_labels": weekday_labels,
        "weeks": weeks,
        "unscheduled": unscheduled,
    }


def _render_task_calendar(
    self: HTML5Translator, tasks: list[DotoTask], display: DisplayOptions
) -> None:
    """Render tasks on a month-grid calendar (click a day to reveal tasks).

    Builds the month grid via :func:`_calendar_month_grid` and passes it to
    ``doto-list-calendar.html`` so the template composes all markup. Clicking a
    day to reveal that day's task panel is a client-side interaction handled by
    the vendored ``doto-views.js``.

    Args:
        self: HTML5Translator instance.
        tasks: List of DotoTask objects to render.
        display: Resolved display options (unused by this view; kept for the
            uniform renderer signature).
    """
    from doxtr_doto.template_loader import render_template

    srcdir = getattr(self.builder, "srcdir", None)
    app = getattr(self.builder, "app", None)
    node = getattr(self, "_doto_current_list_node", None)
    mode = _resolve_list_icon_mode(node, app)

    grid = _calendar_month_grid(tasks)
    task_links = _build_task_links(self, tasks)

    html = render_template(
        "doto-list-calendar.html",
        {
            "calendar": grid,
            "task_links": task_links,
            "icon_mode": mode,
        },
        srcdir=srcdir,
    )

    self.body.append(html)


def _render_task_email(
    self: HTML5Translator, tasks: list[DotoTask], display: DisplayOptions
) -> None:
    """Render tasks in a three-pane email layout (tree / list / detail).

    Builds a status-grouped tree (left pane), the flat task list (top-right
    pane) and per-task detail payloads (bottom-right pane), and passes them to
    ``doto-list-email.html`` so the template composes all markup. Selecting a
    tree node or a list row to populate the detail pane is a client-side
    interaction handled by the vendored ``doto-views.js``.

    Args:
        self: HTML5Translator instance.
        tasks: List of DotoTask objects to render.
        display: Resolved display options; ``visible_tasks`` controls the
            scrollable list pane's visible-row cap (0 = show all).
    """
    from doxtr_doto.template_loader import render_template

    srcdir = getattr(self.builder, "srcdir", None)
    app = getattr(self.builder, "app", None)
    node = getattr(self, "_doto_current_list_node", None)
    mode = _resolve_list_icon_mode(node, app)

    # Resolve the effective scroll-cap (per-directive :visible-tasks: override
    # or the doto_list_visible_tasks config). The template emits this as a data
    # attribute / CSS custom property; the CSS computes the list pane's
    # max-height from it. 0 means "show all" (no cap). All tasks still render.
    visible_tasks = _resolve_visible_tasks(display, app)

    columns = _list_status_columns(app)
    tree = _group_tasks_by_status(tasks, columns)

    task_links = _build_task_links(self, tasks)

    html = render_template(
        "doto-list-email.html",
        {
            "columns": columns,
            "tree": tree,
            "tasks": tasks,
            "task_links": task_links,
            "icon_mode": mode,
            "visible_tasks": visible_tasks,
        },
        srcdir=srcdir,
    )

    self.body.append(html)


# Dispatch table mapping format types to their render functions. Every renderer
# takes the uniform ``(self, tasks, display)`` signature, so adding a format is
# a single dict entry plus its renderer — no dispatch branching required.
_LIST_RENDERERS: dict[str, Callable[..., None]] = {
    "table": _render_task_table,
    "cards": _render_task_cards,
    "list": _render_task_list,
    "kanban": _render_task_kanban,
    "calendar": _render_task_calendar,
    "email": _render_task_email,
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
    elif column == "raci":
        from doxtr_doto.raci import render_raci_compact

        return render_raci_compact(getattr(task, "raci", None))
    return ""


def depart_doto_list_node_html(self: HTML5Translator, node: doto_list_node) -> None:
    """Depart handler for doto_list_node in HTML output."""
    self.body.append("</div>\n")


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
        self.body.append("\\textit{No tasks match the specified criteria.}\n\n")
        raise nodes.SkipNode

    # Resolve the effective icon mode (per-directive override or config) once
    # so both LaTeX list formats render consistently (Feature 5).
    app = getattr(self.builder, "app", None)
    mode = _resolve_list_icon_mode(node, app)
    icons = _resolve_list_icons(app)

    if format_type == "table":
        columns = display.columns
        _render_task_table_latex(self, tasks, columns, mode, icons)
    elif format_type == "calendar":
        # Calendar is an HTML-interactive month grid with no sensible static
        # LaTeX equivalent; degrade to the table rendering so the PDF/epub
        # still shows every task's due date (Feature: layout views).
        _render_task_table_latex(self, tasks, display.columns, mode, icons)
    else:
        # Any other format (list / cards / kanban / email, plus any future
        # ``_LIST_RENDERERS`` entry) degrades to the description-list rendering
        # in LaTeX. Kanban's status columns and email's panes are client-side-
        # only layouts, so a flat grouped list is the graceful static fallback.
        # New formats auto-degrade here and never crash; add an explicit branch
        # above only when a format warrants a richer static LaTeX equivalent.
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
            return str(user_specs[col])

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
    return f"\\dotolistlink{{{label}}}{{{display_text}}}"


def _render_cell_latex(
    task: Any,
    column: str,
    mode: str,
    icons: dict[str, dict[str, tuple[str | None, str | None]]] | None = None,
    app: Sphinx | None = None,
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
        icons: Resolved field/value -> icon maps.
        app: Sphinx application (used to resolve :xlink: tokens in XLINK_FIELDS,
            currently the assignee); ``None`` disables xlink resolution.

    Returns:
        LaTeX string for the cell.
    """
    value = _get_task_column_value(task, column)
    col = column.lower()

    # Resolve :xlink: tokens for fields that opt in via XLINK_FIELDS (currently
    # the assignee) at render time (no-op when xlink is absent/disabled). When a
    # URL resolves, link via \sphinxhref.
    xlink_url: str | None = None
    if col in XLINK_FIELDS and value:
        from doxtr_doto.xlink import resolve_field_value

        value, xlink_url = resolve_field_value(app, str(value))

    esc = _latex_escape(str(value))

    icon = _list_icon_latex(col, str(value), icons) if mode in ("icon", "icon-text") else None

    if mode == "icon" and icon and value:
        content = icon
    elif mode == "icon-text" and icon:
        content = f"{icon}\\,{esc}" if value else icon
    else:
        content = esc

    if xlink_url:
        content = _latex_href(xlink_url, content)

    if col in ("id", "title") and value:
        return _latex_task_link(task, content)
    return content


def _render_task_table_latex(
    self: LaTeXTranslator,
    tasks: list[DotoTask],
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
    app = getattr(self.builder, "app", None)
    col_specs = [_get_latex_column_spec(col, app) for col in columns]
    col_spec = "|".join(col_specs)

    # Assemble the longtable into a local buffer so it can optionally be wrapped
    # in a landscape environment before being appended to the body.
    parts: list[str] = []
    parts.append(f"\\begin{{longtable}}{{|{col_spec}|}}\n")
    parts.append("\\hline\n")

    # Header row - use central column labels
    header_cells = " & ".join(f"\\textbf{{{COLUMN_LABELS.get(c, c.title())}}}" for c in columns)
    parts.append(f"{header_cells} \\\\\n\\hline\n\\endfirsthead\n")

    # Continuation header for multi-page tables
    parts.append(f"\\hline\n{header_cells} \\\\\n\\hline\n\\endhead\n")

    # Data rows
    for task in tasks:
        cells = []
        for col in columns:
            # Icon-mode aware, clickable id/title (Feature 5).
            cells.append(_render_cell_latex(task, col, mode, icons, app))
        parts.append(" & ".join(cells) + " \\\\\n\\hline\n")

    parts.append("\\end{longtable}\n\n")
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
    tasks: list[DotoTask],
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
    self.body.append("\\begin{description}\n")
    app = getattr(self.builder, "app", None)
    for task in tasks:
        # id label (clickable), title (clickable).
        id_cell = _render_cell_latex(task, "id", mode, icons, app)
        title_cell = _render_cell_latex(task, "title", mode, icons, app)
        # Metadata cells honor the icon mode too.
        meta_cells = [
            _render_cell_latex(task, "priority", mode, icons, app),
            _render_cell_latex(task, "status", mode, icons, app),
        ]
        if task.assignee:
            meta_cells.append(_render_cell_latex(task, "assignee", mode, icons, app))
        if task.due:
            meta_cells.append(_render_cell_latex(task, "due", mode, icons, app))
        meta = ", ".join(c for c in meta_cells if c)
        self.body.append(f"\\item[{id_cell}] {title_cell} \\hfill \\textit{{({meta})}}\n")
    self.body.append("\\end{description}\n\n")


def _latex_escape(text: str) -> str:
    """Escape LaTeX special characters in text."""
    if not text:
        return ""
    # Order matters: & must be escaped before adding more &
    replacements = [
        ("\\", "\\textbackslash{}"),
        ("&", "\\&"),
        ("%", "\\%"),
        ("$", "\\$"),
        ("#", "\\#"),
        ("_", "\\_"),
        ("{", "\\{"),
        ("}", "\\}"),
        ("~", "\\textasciitilde{}"),
        ("^", "\\textasciicircum{}"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def _latex_href(url: str, body: str) -> str:
    r"""Wrap already-escaped ``body`` in ``\sphinxhref`` with a LaTeX-safe URL.

    URLs are escaped differently from ordinary text (only ``\\``, ``%``, ``#``)
    because :func:`_latex_escape` would corrupt legal URL characters like ``~``,
    ``_`` and ``&`` that ``\sphinxhref`` wants literal. Single site for the
    identical escape+wrap used by both LaTeX render seams.
    """
    safe_url = url.replace("\\", "\\\\").replace("%", "\\%").replace("#", "\\#")
    return f"\\sphinxhref{{{safe_url}}}{{{body}}}"


def _latex_assignee(self: LaTeXTranslator, assignee: str) -> str:
    r"""Resolve :xlink: tokens in a LaTeX assignee value and escape it.

    Resolution is render-time only (the stored value is untouched) and degrades
    gracefully to the escaped raw text when sphinxcontrib-xlink is absent or
    disabled. When a token resolves to a URL the escaped display text is wrapped
    in ``\sphinxhref{url}{text}`` (the same macro xlink uses for its own LaTeX
    links).

    Args:
        self: LaTeXTranslator instance (used to reach the Sphinx app).
        assignee: Raw assignee field value.

    Returns:
        A LaTeX string: either escaped plain text, or a ``\sphinxhref`` link.
    """
    from doxtr_doto.xlink import resolve_field_value

    app = getattr(self.builder, "app", None)
    display, url = resolve_field_value(app, assignee)
    escaped = _latex_escape(display)
    if url:
        return _latex_href(url, escaped)
    return escaped


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
    self.body.append('<div class="doto-summary-stat doto-summary-total">\n')
    self.body.append(f'<span class="doto-summary-stat-value">{total_tasks}</span>\n')
    self.body.append('<span class="doto-summary-stat-label">Total</span>\n')
    self.body.append("</div>\n")

    for field in group_by:
        stats = _calculate_group_stats(filtered_tasks, field)
        for label, count in stats.items():
            css_class = f"doto-summary-{field}-{label.lower().replace(' ', '-')}"
            self.body.append(f'<div class="doto-summary-stat {escape_html_attr(css_class)}">\n')
            self.body.append(f'<span class="doto-summary-stat-value">{count}</span>\n')
            self.body.append(
                f'<span class="doto-summary-stat-label">{escape_html_content(label)}</span>\n'
            )
            self.body.append("</div>\n")
    self.body.append("</div>\n")

    # Generate charts if enabled
    if show_chart:
        chart_type = config.get("chart_type", "bar")
        chart_html = _render_summary_chart_html(self, filtered_tasks, group_by, chart_type)
        self.body.append(chart_html)


def _render_summary_chart_html(
    self: HTML5Translator,
    tasks: list[DotoTask],
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
            html = generate_summary_charts_plotly_html(tasks, group_by, chart_type, static_dir)
            if html is not None:
                _record_chart_image(app, static_dir, tasks, group_by, chart_type)
                return html
        # Fall through to SVG on any unavailability/failure.

    return generate_summary_charts(tasks, group_by, chart_type=chart_type)


def _record_chart_image(
    app: Any,
    directory: str,
    tasks: list[DotoTask],
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


def _calculate_group_stats(tasks: list[DotoTask], field: str) -> dict[str, int]:
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
    self.body.append("</div>\n")


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
        self.body.append("\\textit{No tasks found.}\n\n")
        raise nodes.SkipNode

    total = len(tasks)
    self.body.append("\n\\textbf{Total tasks:} " + str(total) + "\n\n")

    # Feature 7: when the plotly engine is active and a chart is requested,
    # export a static image with kaleido and \includegraphics it. Any
    # unavailability/failure falls through to the textual breakdown below so
    # the PDF build never crashes.
    if config.get("show_chart"):
        chart_type = config.get("chart_type", "bar")
        _emit_summary_chart_latex(self, tasks, group_by, chart_type)

    for field in group_by:
        stats = _calculate_group_stats(tasks, field)
        self.body.append(f"\\textbf{{{field.title()} breakdown:}}\n\\begin{{itemize}}\n")
        for label, count in stats.items():
            pct = round(count / total * 100) if total else 0
            self.body.append(f"\\item {_latex_escape(label)}: {count} ({pct}\\%)\n")
        self.body.append("\\end{itemize}\n\n")

    raise nodes.SkipNode


def _emit_summary_chart_latex(
    self: LaTeXTranslator,
    tasks: list[DotoTask],
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


# --- doto_archive visitors (archive page from JSON store) ---


def _load_archived_from_json_store(self: Any) -> list[Any]:
    """Return archived tasks sourced from the JSON task store.

    The archive page's whole purpose is that an archived task's ``.. doto::``
    directive is REMOVED from its RST file and the task survives only in the
    JSON store (``.doto/tasks.json``). So the archive listing must come from the
    JSON store, not from ``all_tasks`` (which is populated only from parsed RST
    directives and is therefore empty for archived tasks on every build after
    the one that archived them).

    The in-memory sync store attached to the environment during
    ``env-check-consistency`` is not guaranteed to still be present (or current)
    during the HTML/LaTeX write phase, so this re-loads the store from disk at
    ``app.srcdir/json_file`` for a reliable read. A missing/absent JSON file is
    handled gracefully (empty list, no crash).

    Args:
        self: The translator instance (HTML or LaTeX).

    Returns:
        List of archived :class:`~doxtr_doto.collectors.DotoTask` objects
        converted from the JSON store (``source=JSON``), unsorted.
    """
    from pathlib import Path

    from doxtr_doto.collectors import DotoTask
    from doxtr_doto.config import get_config
    from doxtr_doto.sync.json_store import JsonTaskStore

    app = getattr(self.builder, "app", None)
    if app is None:
        return []

    json_file = get_config(app, "json_file")
    json_path = Path(app.srcdir) / json_file
    if not json_path.exists():
        return []

    try:
        store = JsonTaskStore(json_path)
        store.load()
        return [DotoTask.from_dict(task_id, data) for task_id, data in store.iter_archived_tasks()]
    except (OSError, ValueError, KeyError, TypeError):
        # Corrupt/unreadable store: degrade to no JSON-sourced tasks rather
        # than breaking the whole build.
        return []


def _collect_archived_tasks(self: Any) -> list[Any]:
    """Return archived tasks for the archive page, newest first.

    Archived tasks are sourced primarily from the JSON task store (see
    :func:`_load_archived_from_json_store`), because an archived task's
    directive is removed from its RST file and the task lives only in
    ``.doto/tasks.json``. Any archived tasks still present in ``all_tasks``
    (e.g. during the very build that archives them, before the directive is
    stripped) are merged in and de-duplicated by task id, with the JSON store
    copy preferred as the source of truth.

    The result preserves the existing newest-first ordering via
    :func:`_archive_sort_key` and its type-homogeneity fix.

    Args:
        self: The translator instance (HTML or LaTeX).

    Returns:
        List of archived DotoTask objects sorted by archive date descending.
    """
    from doxtr_doto.collectors import get_doto_env

    env = self.builder.env
    doto_env = get_doto_env(env)

    # JSON store is the authoritative source; keyed by id so it wins on merge.
    by_id: dict[str, Any] = {task.id: task for task in _load_archived_from_json_store(self)}
    # Merge in archived tasks still in all_tasks that the JSON store lacks.
    for task in doto_env.all_tasks.values():
        if getattr(task, "archived", False) and task.id not in by_id:
            by_id[task.id] = task

    archived = list(by_id.values())
    archived.sort(key=_archive_sort_key, reverse=True)
    return archived


def _archive_sort_key(task: Any) -> str:
    """Return a type-homogeneous sort key for an archived task.

    Falls back through ``archived_on`` -> ``updated`` -> ``created``, coercing
    whichever is first present to an ISO-8601 string. Coercing to a single
    string type avoids the ``TypeError`` that arose when the list mixed
    ``datetime`` and ``str`` dates (e.g. one task with a datetime and another
    whose dates are all None). Tasks with no dates sort last (empty string).

    Args:
        task: An archived DotoTask (or compatible object).

    Returns:
        An ISO-8601 string (or "" when the task has no dates).
    """
    for attr in ("archived_on", "updated", "created"):
        value = getattr(task, attr, None)
        if value is None:
            continue
        if hasattr(value, "isoformat"):
            return str(value.isoformat())
        return str(value)
    return ""


def _archive_task_rows(tasks: list[Any]) -> list[dict[str, Any]]:
    """Build template-ready row dicts for the archive listing.

    Pulls id, title, status, assignee, priority, archived_on, original page,
    and body from each task so the ``doto-archive.html`` template (or a child
    theme's override) can render them without reaching into DotoTask internals.

    Each row also carries the originating ``task`` object under the ``task``
    key, mirroring how doto-list passes task objects, so a child template can
    surface additional columns (tags, due, custom fields) without a core edit.
    The ``original_page`` display uses the captured page title when available,
    falling back to the docname, for consistency with the reopen error
    identity.

    Args:
        tasks: Archived DotoTask objects.

    Returns:
        List of plain dicts, one per archived task.
    """
    from doxtr_doto.utils import format_date_display

    rows: list[dict[str, Any]] = []
    for task in tasks:
        archived_on = getattr(task, "archived_on", None)
        if archived_on is not None and hasattr(archived_on, "isoformat"):
            archived_on_display = format_date_display(archived_on.isoformat()[:10])
        else:
            archived_on_display = str(archived_on) if archived_on else ""
        docname = getattr(task, "docname", "") or ""
        page_title = getattr(task, "page_title", "") or ""
        rows.append(
            {
                "id": task.id,
                "title": task.title,
                "status": task.status,
                "assignee": task.assignee or "",
                "priority": task.priority,
                "archived_on": archived_on_display,
                "original_page": page_title or docname,
                "body": getattr(task, "body", "") or "",
                # Full task object for child-template overrides (extra columns).
                "task": task,
            }
        )
    return rows


def visit_doto_archive_node_html(self: HTML5Translator, node: doto_archive_node) -> None:
    """Visit handler for doto_archive_node in HTML output.

    Renders archived tasks (sourced from the JSON store / environment) through
    the ``doto-archive.html`` template so a child theme can override the markup
    by shipping its own ``_doto/templates/html/doto-archive.html``.
    """
    from doxtr_doto.template_loader import render_template

    tasks = _collect_archived_tasks(self)
    rows = _archive_task_rows(tasks)
    srcdir = getattr(self.builder, "srcdir", None)

    html = render_template(
        "doto-archive.html",
        {"rows": rows, "tasks": tasks, "total": len(rows)},
        srcdir=srcdir,
    )
    self.body.append(html)
    raise nodes.SkipNode


def depart_doto_archive_node_html(self: HTML5Translator, node: doto_archive_node) -> None:
    """Depart handler for doto_archive_node in HTML output."""
    pass  # SkipNode raised in visit handler


def visit_doto_archive_node_latex(self: LaTeXTranslator, node: doto_archive_node) -> None:
    r"""Visit handler for doto_archive_node in LaTeX output.

    Emits a description list of archived tasks using the themeable ``\dotometa*``
    macros from ``doto.sty`` so a child theme's ``.sty`` can restyle the output.
    """
    tasks = _collect_archived_tasks(self)
    rows = _archive_task_rows(tasks)

    if not rows:
        self.body.append("\\textit{No archived tasks.}\n\n")
        raise nodes.SkipNode

    self.body.append(f"\\textbf{{Total archived tasks:}} {len(rows)}\n\n")
    self.body.append("\\begin{description}\n")
    for row in rows:
        id_text = _latex_escape(row["id"])
        title_text = _latex_escape(row["title"])
        meta_parts = [
            _latex_escape(row["status"]),
            _latex_escape(row["priority"]),
        ]
        if row["assignee"]:
            meta_parts.append(_latex_escape(row["assignee"]))
        if row["archived_on"]:
            meta_parts.append(_latex_escape(row["archived_on"]))
        if row["original_page"]:
            meta_parts.append(_latex_escape(row["original_page"]))
        meta = ", ".join(p for p in meta_parts if p)
        self.body.append(f"\\item[{id_text}] {title_text} \\hfill \\textit{{({meta})}}\n")
    self.body.append("\\end{description}\n\n")
    raise nodes.SkipNode


def depart_doto_archive_node_latex(self: LaTeXTranslator, node: doto_archive_node) -> None:
    """Depart handler for doto_archive_node in LaTeX output."""
    pass  # SkipNode raised in visit handler


def visit_doto_archive_node_epub(self: HTML5Translator, node: doto_archive_node) -> None:
    """Visit handler for doto_archive_node in epub output (delegates to HTML)."""
    visit_doto_archive_node_html(self, node)


def depart_doto_archive_node_epub(self: HTML5Translator, node: doto_archive_node) -> None:
    """Depart handler for doto_archive_node in epub output (delegates to HTML)."""
    depart_doto_archive_node_html(self, node)


# --- doto_ref visitors ---


def visit_doto_ref_html(self: HTML5Translator, node: doto_ref) -> None:
    """Visit handler for doto_ref in HTML output."""
    task_id = node.get("reftarget", "")
    refuri = node.get("refuri", f"#{task_id}")
    title = node.get("title", task_id)
    self.body.append(
        f'<a class="doto-ref" href="{escape_html_attr(refuri)}" title="{escape_html_attr(title)}">'
    )


def depart_doto_ref_html(self: HTML5Translator, node: doto_ref) -> None:
    """Depart handler for doto_ref in HTML output."""
    self.body.append("</a>")


def visit_doto_ref_latex(self: LaTeXTranslator, node: doto_ref) -> None:
    """Visit handler for doto_ref in LaTeX output."""
    task_id = node.get("reftarget", "")
    self.body.append(f"\\dotoref{{{task_id}}}")


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
