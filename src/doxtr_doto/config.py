"""Configuration options for the doto extension."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from doxtr_doto.constants import (
    DEFAULT_PRIORITY,
    DEFAULT_STATUS,
    DONE_STATUS,
    VALID_LATEX_LAYOUTS,
    VALID_LIST_ICON_MODES,
    VALID_PRIORITIES,
    VALID_STATUSES,
)
from doxtr_doto.enums import ConflictResolution

if TYPE_CHECKING:
    from sphinx.application import Sphinx


# Default configuration values
DEFAULTS: dict[str, Any] = {
    # Core settings
    "doto_enabled": True,
    "doto_include_done": True,
    "doto_render_in_toc": False,
    # JSON store
    "doto_json_file": ".doto/tasks.json",
    "doto_auto_create_json": True,
    # Auto-archive (enabled by default; set False to disable)
    "doto_auto_archive": True,
    "doto_archive_doc": "_doto_archive",
    "doto_archive_after_days": 0,
    "doto_archive_statuses": [DONE_STATUS],
    # Sync settings
    "doto_sync_on_build": True,
    "doto_conflict_action": "error",
    # Defaults
    "doto_default_priority": DEFAULT_PRIORITY,
    "doto_default_status": DEFAULT_STATUS,
    "doto_date_format": "%Y-%m-%d",
    "doto_id_prefix": "",
    "doto_inbox_file": "tasks/inbox.rst",
    # Current user for RACI auto-defaults in Sphinx builds. Serves the same
    # purpose as the CLI's ``[doto] user`` setting. Supports ``$VAR`` /
    # ``${VAR}`` env-var references (resolved via
    # doxtr_doto.cli.config.resolve_env_vars). Empty by default.
    "doto_default_user": "",
    # Validation
    "doto_statuses": list(VALID_STATUSES),
    "doto_priorities": list(VALID_PRIORITIES),
    "doto_required_fields": [],
    "doto_warn_overdue": True,
    # Styling - theme names: "default" | "minimal"
    "doto_html_theme": "default",  # HTML theme: "default" or "minimal"
    "doto_latex_theme": "default",  # LaTeX theme: "default" or "minimal"
    # PDF/LaTeX task-box layout: "default" | "compact" (Feature D).
    #   "default" = the roomy stacked-icon box: a filled title bar plus one
    #               metadata group per row (id/priority, status, assignee/due,
    #               created/updated, tags, raci), each shown as a stacked
    #               icon-over-label.
    #   "compact" = the SAME fields laid out densely: a single-line header
    #               (id + priority + status), tighter box geometry, and inline
    #               icon+value pairs for the remaining fields separated by a
    #               thin rule rather than one roomy row each. No detail is
    #               dropped relative to "default".
    # The layout only selects which .sty macros/box styles nodes.py emits; the
    # geometry/visual truth lives in themes/latex/doto.sty (dotobox* vs
    # dotoboxcompact*, \dotocompact* macros) so a child theme's .sty can
    # override either layout without touching Python. Fully backward compatible:
    # the default preserves the previous output byte-for-byte.
    "doto_latex_layout": "default",
    "doto_epub_theme": "default",  # epub theme: "default" or "minimal"
    "doto_html_css_files": [],
    "doto_latex_preamble": "",
    # Task-list rendering mode: "icon" | "icon-text" | "text"
    # Controls how list/table cells render field values (Feature 5).
    #   "icon"      = Font Awesome icon only where a good icon exists (else text)
    #   "icon-text" = icon followed by text (default)
    #   "text"      = text only
    "doto_list_icon_mode": "icon-text",
    # Email view: default number of task rows kept visible at once in the
    # scrollable list pane. A per-directive ``:visible-tasks:`` overrides this.
    # Must be an int >= 0; 0 means "show all / no scroll cap". Default 5.
    "doto_list_visible_tasks": 5,
    # Task-list icon overrides (Feature 5 extensibility).
    #
    # A dict merged over the built-in field/value -> icon maps so custom
    # statuses/priorities (allowed via doto_statuses/doto_priorities) — or any
    # field — can get icons without editing the extension source. Only the keys
    # you supply are overridden; every built-in default keeps working.
    #
    # Shape (all keys optional)::
    #
    #     doto_list_icons = {
    #         # Field-level icons keyed by list column name. Each value is a
    #         # {"html": <FA CSS class>, "latex": <\faXxx macro>} mapping; use
    #         # None for either to suppress the icon (falls back to text).
    #         "fields": {
    #             "due": {"html": "fa-solid fa-clock", "latex": r"\faClock"},
    #         },
    #         # Per-value status icons keyed by status value (lowercased).
    #         "status": {
    #             "deferred": {"html": "fa-solid fa-pause", "latex": r"\faPause"},
    #         },
    #         # Per-value priority icons keyed by priority value (lowercased).
    #         "priority": {
    #             "urgent": {"html": "fa-solid fa-fire", "latex": r"\faFire"},
    #         },
    #     }
    #
    # A per-entry mapping may also be a bare string, which is treated as the
    # HTML class with no LaTeX macro. Keys not present here fall through to the
    # built-in defaults in nodes.py.
    "doto_list_icons": {},
    # Chart rendering engine for doto-summary: "svg" | "plotly"
    # "svg" (default) keeps the built-in inline-SVG charts for full backward
    # compatibility and zero extra dependencies. "plotly" renders richer charts
    # via plotly + kaleido, falling back to SVG when those packages are absent
    # (Feature 7).
    "doto_chart_engine": "svg",
    # xlink resolution (optional doxtr-xlink integration)
    # When True (default) and doxtr-xlink is installed AND listed in
    # the project's extensions, the :assignee: field's value is scanned for
    # :xlink:`key` tokens and each is resolved to the person/entity display
    # name (and linked in HTML/PDF) at render time. Only the :assignee: field
    # resolves today (see fields.XLINK_FIELDS; title/body do not). The stored
    # JSON/RST keep the raw token so sync round-trips stay byte-stable. Set
    # False to always render the raw token. Degrades gracefully (renders the
    # raw token) when xlink is absent.
    "doto_resolve_xlinks": True,
    # Integration
    "doto_export_json": False,
    "doto_doxtr_integration": "auto",
    # LaTeX table column specifications (user overrides)
    "doto_latex_column_specs": {},
}


def setup_config(app: Sphinx) -> None:
    """Register all doto configuration values with Sphinx."""
    for name, default in DEFAULTS.items():
        # Use 'env' rebuild type for values that affect content
        rebuild: Literal["env", "html"] = (
            "env"
            if name
            in {
                "doto_enabled",
                "doto_include_done",
                "doto_auto_archive",
                "doto_archive_doc",
                "doto_archive_after_days",
                "doto_archive_statuses",
                "doto_default_priority",
                "doto_default_status",
                "doto_statuses",
                "doto_priorities",
                "doto_required_fields",
                "doto_list_icon_mode",
                "doto_list_visible_tasks",
                "doto_list_icons",
                "doto_latex_layout",
                "doto_chart_engine",
                "doto_resolve_xlinks",
            }
            else "html"
        )

        app.add_config_value(name, default, rebuild)


def is_valid_visible_tasks(value: Any) -> bool:
    """Return True if value is a valid doto_list_visible_tasks.

    A valid value is a non-negative int that is not a bool (0 = show all).
    Single source of truth for the directive override guard
    (nodes._resolve_visible_tasks), the config validation below, and the
    template_loader fallback renderer.
    """
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def get_config(app: Sphinx, name: str) -> Any:
    """Get a doto configuration value, with fallback to default."""
    if not name.startswith("doto_"):
        name = f"doto_{name}"
    return getattr(app.config, name, DEFAULTS.get(name))


def validate_config(app: Sphinx) -> list[str]:
    """Validate doto configuration and return list of warnings.

    Only validates that default values are within the configured sets,
    not that the configured sets themselves contain specific values.
    Custom statuses/priorities are allowed.
    """
    warnings = []

    # Get configured sets (custom values are allowed)
    config_statuses = set(get_config(app, "statuses"))
    config_priorities = set(get_config(app, "priorities"))

    # Validate default values are in allowed sets
    default_status = get_config(app, "default_status")
    if default_status not in config_statuses:
        warnings.append(f"doto_default_status '{default_status}' not in doto_statuses")

    default_priority = get_config(app, "default_priority")
    if default_priority not in config_priorities:
        warnings.append(f"doto_default_priority '{default_priority}' not in doto_priorities")

    # Validate conflict action
    valid_actions = {e.value for e in ConflictResolution}
    conflict_action = get_config(app, "conflict_action")
    if conflict_action not in valid_actions:
        warnings.append(f"doto_conflict_action '{conflict_action}' must be one of {valid_actions}")

    # Validate list icon mode (Feature 5)
    icon_mode = get_config(app, "list_icon_mode")
    if icon_mode not in VALID_LIST_ICON_MODES:
        warnings.append(
            f"doto_list_icon_mode '{icon_mode}' must be one of {sorted(VALID_LIST_ICON_MODES)}"
        )

    # Validate email-view visible task cap: must be an int >= 0 (0 = show all).
    visible_tasks = get_config(app, "list_visible_tasks")
    if not is_valid_visible_tasks(visible_tasks):
        warnings.append(f"doto_list_visible_tasks '{visible_tasks}' must be an integer >= 0")

    # Validate chart engine (Feature 7)
    valid_engines = {"svg", "plotly"}
    chart_engine = get_config(app, "chart_engine")
    if chart_engine not in valid_engines:
        warnings.append(
            f"doto_chart_engine '{chart_engine}' must be one of {sorted(valid_engines)}"
        )

    # Validate PDF/LaTeX layout (Feature D)
    latex_layout = get_config(app, "latex_layout")
    if latex_layout not in VALID_LATEX_LAYOUTS:
        warnings.append(
            f"doto_latex_layout '{latex_layout}' must be one of {sorted(VALID_LATEX_LAYOUTS)}"
        )

    return warnings
