"""Configuration options for the doto extension."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from doxtr_doto.constants import (
    DEFAULT_PRIORITY,
    DEFAULT_STATUS,
    DONE_STATUS,
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
    
    # Auto-archive
    "doto_auto_archive": False,
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
    
    # Validation
    "doto_statuses": list(VALID_STATUSES),
    "doto_priorities": list(VALID_PRIORITIES),
    "doto_required_fields": [],
    "doto_warn_overdue": True,
    
    # Styling - theme names: "default" | "minimal"
    "doto_html_theme": "default",   # HTML theme: "default" or "minimal"
    "doto_latex_theme": "default",  # LaTeX theme: "default" or "minimal"
    "doto_epub_theme": "default",   # epub theme: "default" or "minimal"
    "doto_html_css_files": [],
    "doto_latex_preamble": "",

    # Task-list rendering mode: "icon" | "icon-text" | "text"
    # Controls how list/table cells render field values (Feature 5).
    #   "icon"      = Font Awesome icon only where a good icon exists (else text)
    #   "icon-text" = icon followed by text (default)
    #   "text"      = text only
    "doto_list_icon_mode": "icon-text",

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
        rebuild = "env" if name in {
            "doto_enabled",
            "doto_include_done",
            "doto_auto_archive",
            "doto_archive_statuses",
            "doto_default_priority",
            "doto_default_status",
            "doto_statuses",
            "doto_priorities",
            "doto_required_fields",
            "doto_list_icon_mode",
            "doto_list_icons",
            "doto_chart_engine",
        } else "html"
        
        app.add_config_value(name, default, rebuild)


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
        warnings.append(
            f"doto_default_status '{default_status}' not in doto_statuses"
        )
    
    default_priority = get_config(app, "default_priority")
    if default_priority not in config_priorities:
        warnings.append(
            f"doto_default_priority '{default_priority}' not in doto_priorities"
        )
    
    # Validate conflict action
    valid_actions = {e.value for e in ConflictResolution}
    conflict_action = get_config(app, "conflict_action")
    if conflict_action not in valid_actions:
        warnings.append(
            f"doto_conflict_action '{conflict_action}' must be one of {valid_actions}"
        )

    # Validate list icon mode (Feature 5)
    icon_mode = get_config(app, "list_icon_mode")
    if icon_mode not in VALID_LIST_ICON_MODES:
        warnings.append(
            f"doto_list_icon_mode '{icon_mode}' must be one of "
            f"{sorted(VALID_LIST_ICON_MODES)}"
        )

    # Validate chart engine (Feature 7)
    valid_engines = {"svg", "plotly"}
    chart_engine = get_config(app, "chart_engine")
    if chart_engine not in valid_engines:
        warnings.append(
            f"doto_chart_engine '{chart_engine}' must be one of {sorted(valid_engines)}"
        )

    return warnings
