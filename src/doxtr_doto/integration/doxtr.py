"""Doxtr integration module.

This module provides integration with doxtr-pdf-theme-core and other
doxtr tools when available.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from sphinx.application import Sphinx

__all__ = [
    "detect_doxtr_features",
    "setup_doxtr_integration",
    "get_doxtr_color",
    "_core_light_palette_defaults",
    "_merged_semantic_palette",
    "resolve_doto_palette_colors",
    "build_doto_color_preamble",
    "get_landscape_min_columns",
    "wrap_longtable_in_landscape",
]

#: Mapping of doto LaTeX color macro names (the ``doto@<name>`` colors defined
#: in ``themes/latex/doto.sty``) to ``dd:`` palette expressions. When
#: ``doxtr-pdf-theme-core`` is active these are resolved against the project's
#: semantic palette and emitted as ``\definecolor`` overrides into the LaTeX
#: preamble, so the doto macros pick up theme-derived colors instead of the
#: hardcoded defaults baked into ``doto.sty``.
#:
#: Sensible semantic mapping:
#:   - priorities: critical -> danger, high -> warning, medium -> primary,
#:     low -> secondary
#:   - statuses:   open -> success, in-progress -> info, blocked -> danger,
#:     done -> secondary, overdue -> danger
#:   - box:        background -> a light tint of primary, border -> primary,
#:     title bar -> primary (darkened), title text -> contrast on the title bar
DOTO_COLOR_EXPRESSIONS: dict[str, str] = {
    # Priority colors
    "doto@low": "dd:secondary",
    "doto@medium": "dd:primary",
    "doto@high": "dd:warning",
    "doto@critical": "dd:danger",
    # Status colors
    "doto@open": "dd:success",
    "doto@inprogress": "dd:info",
    "doto@blocked": "dd:danger",
    "doto@done": "dd:secondary",
    "doto@overdue": "dd:danger",
    # Box colors
    "doto@bg": "dd:primary:lighten:88",
    "doto@border": "dd:primary:lighten:40",
    "doto@titlebg": "dd:primary:darken:10",
    "doto@titlefg": "dd:primary:contrast:fg:primary",
    "doto@text": "dd:primary:darken:45",
    "doto@label": "dd:primary:darken:25",
}


def detect_doxtr_features(app: Sphinx) -> dict[str, bool]:
    """
    Detect available doxtr features without hard dependencies.

    Checks for doxtr-pdf-theme-core extension which provides:
    - LaTeX/PDF theming via preamble.tex_t templates
    - Config values: doxtr_theme_defaults, doxtr_containers, etc.
    - AST processing for containers, tables, needs, epigraphs, sidebars

    Returns:
        Dictionary of available features
    """
    return {
        # Correct extension name (uses underscore, not dot)
        "pdf_backend": "doxtr_pdf_theme_core" in app.extensions,
        # Config registered by the extension
        "theme_config": hasattr(app.config, "doxtr_theme_defaults"),
        # Cross-references: not implemented in doxtr-pdf-theme-core
        "cross_references": False,
    }


def setup_doxtr_integration(app: Sphinx) -> None:
    """
    Set up doxtr integration if available.

    This configures doto to use doxtr's theming system when available,
    falling back to standalone CSS/LaTeX when not.
    """
    from doxtr_doto.config import get_config
    from doxtr_doto.enums import DotoIntegration

    integration_mode = get_config(app, "doxtr_integration")

    if integration_mode == DotoIntegration.DISABLED:
        return

    features = detect_doxtr_features(app)

    if integration_mode == DotoIntegration.AUTO:
        # Auto-detect and integrate if available
        if features["pdf_backend"]:
            _register_doxtr_containers(app)
    elif integration_mode == DotoIntegration.ENABLED:
        # Force integration - warn if not available
        if not features["pdf_backend"]:
            from sphinx.util import logging

            logger = logging.getLogger(__name__)
            logger.warning(
                "doto_doxtr_integration is 'enabled' but doxtr-pdf-theme-core "
                "extension is not loaded. Falling back to standalone themes."
            )
        else:
            _register_doxtr_containers(app)

    # Semantic-palette color overrides for the LaTeX preamble (Feature 3) are
    # deferred to a config-inited handler so they run after the user's conf.py
    # is loaded (palette available) and after ``\usepackage{doto}`` is injected.
    # See ``apply_doxtr_semantic_colors`` (wired in doxtr_doto.__init__.setup).


def apply_doxtr_semantic_colors(app: Sphinx) -> None:
    r"""Emit palette-derived ``\definecolor`` overrides when the core is active.

    This is the config-inited entry point for Feature 3. It is a no-op unless
    ``doxtr-pdf-theme-core`` is loaded, the integration mode allows it, and a
    ``doxtr_semantic_palette`` is configured. Standalone builds keep the
    defaults defined in ``doto.sty``.

    Args:
        app: Sphinx application instance.
    """
    from doxtr_doto.config import get_config
    from doxtr_doto.enums import DotoIntegration

    integration_mode = get_config(app, "doxtr_integration")
    if integration_mode == DotoIntegration.DISABLED:
        return

    features = detect_doxtr_features(app)
    if not features["pdf_backend"]:
        return

    _apply_semantic_colors(app)


def _apply_semantic_colors(app: Sphinx) -> None:
    r"""Emit ``\definecolor`` overrides derived from the semantic palette.

    Resolves the doto color macros (see :data:`DOTO_COLOR_EXPRESSIONS`) against
    ``app.config.doxtr_semantic_palette`` and appends the resulting
    ``\definecolor`` lines to ``latex_elements['preamble']`` *after* the
    ``\usepackage{doto}`` line injected by ``_setup_latex_theme``. Because
    xcolor lets a later ``\definecolor`` win, this overrides the hardcoded
    defaults in ``doto.sty`` without touching that file.

    Standalone builds (no core / no palette) skip this entirely and keep the
    defaults from ``doto.sty``.

    Args:
        app: Sphinx application instance.
    """
    resolved = resolve_doto_palette_colors(app)
    if not resolved:
        return

    preamble_block = build_doto_color_preamble(resolved)
    if not preamble_block:
        return

    config = app.config
    latex_elements = dict(getattr(config, "latex_elements", {}) or {})
    existing = latex_elements.get("preamble", "")
    # Guard against duplicate injection (config-inited can fire more than once
    # across incremental builds / test setups).
    marker = "% doto semantic palette overrides"
    if marker in existing:
        return
    latex_elements["preamble"] = existing + "\n" + preamble_block
    config.latex_elements = latex_elements


def _core_light_palette_defaults(
    app: Sphinx,
) -> tuple[dict[str, str], Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]] | None:
    r"""Seam: source the core's light-palette base + merge primitive.

    This is the SINGLE place doto reaches into ``doxtr-pdf-theme-core``'s
    (currently unexported) light-palette internals. It isolates both core
    internals the merge needs:

    1. ``doxtr_pdf_theme_core.core_config.DOXTR_SEMANTIC_PALETTE`` (the core
       tier the merge starts from), and
    2. ``doxtr_pdf_theme_core.utils.deep_update`` (the recursive-merge
       primitive the core engine uses to layer the theme/user tiers).

    It returns a *fresh* deep copy of the core palette so callers can never
    mutate the core's module-level constant, paired with the ``deep_update``
    callable so :func:`_merged_semantic_palette` can apply the remaining tiers
    the same way the core engine does.

    Override point
    --------------
    A child theme (or a future public-core accessor) can redirect where doto's
    merged light palette comes from by overriding *only this function*:

    * To swap in a public merged-light-palette accessor once the core exposes
      one, return that palette as the base here (with a no-op/identity
      ``deep_update`` if the core has already merged every tier); the
      orchestration in :func:`_merged_semantic_palette` stays unchanged.
    * To point doto at a different base palette entirely, return it here.

    Keeping this the lone seam means swapping to a public accessor is a
    one-function change and child themes have exactly one hook.

    Args:
        app: Sphinx application instance (reserved for overrides that need to
            consult config; the default implementation does not read it).

    Returns:
        A ``(base_palette, deep_update)`` tuple, or ``None`` when the core is
        not importable (standalone build) so callers can skip resolution and
        keep the ``doto.sty`` defaults.
    """
    try:
        from doxtr_pdf_theme_core.core_config import DOXTR_SEMANTIC_PALETTE
        from doxtr_pdf_theme_core.utils import deep_update
    except ImportError:
        return None

    return copy.deepcopy(DOXTR_SEMANTIC_PALETTE), deep_update


def _merged_semantic_palette(app: Sphinx) -> dict[str, str] | None:
    r"""Reconstruct the core's three-tier merged light semantic palette.

    ``doxtr-pdf-theme-core`` resolves ``dd:`` expressions against a palette
    merged from three tiers (core defaults -> theme defaults -> user config),
    but it only publishes the merged *dark* palette on
    ``config.doxtr_dark_semantic_palette``; the merged light palette is kept
    internal. doto's ``dd:primary``/``dd:danger``/... expressions therefore
    cannot be resolved against ``config.doxtr_semantic_palette`` alone, because
    that dict holds only the user tier and omits the brand keys supplied by the
    core and the active theme (e.g. ``primary``, ``secondary``, ``danger``).

    This is the orchestration layer: it sources the core-tier base palette and
    the merge primitive from the :func:`_core_light_palette_defaults` seam
    (the single core-internal access point), then layers the remaining tiers
    so doto resolves the same colors the rest of the PDF uses:

    1. ``_core_light_palette_defaults(app)`` base (core tier)
    2. ``config.doxtr_theme_defaults['semantic_palette']`` (theme tier)
    3. ``config.doxtr_semantic_palette`` (user tier)

    The ``dark`` sub-key is stripped from the theme and user tiers to match the
    core's light-palette merge (dark overrides live under a nested ``dark``
    key).

    Args:
        app: Sphinx application instance.

    Returns:
        The merged light palette, or ``None`` when the core is not importable
        (standalone build) so callers can skip resolution and keep the
        ``doto.sty`` defaults.
    """
    defaults = _core_light_palette_defaults(app)
    if defaults is None:
        return None
    base_palette, deep_update = defaults

    config = app.config
    theme_raw = getattr(config, "doxtr_theme_defaults", None) or {}
    user_raw = getattr(config, "doxtr_semantic_palette", None) or {}

    palette_theme = {
        k: v for k, v in (theme_raw.get("semantic_palette", {}) or {}).items() if k != "dark"
    }
    palette_user = {k: v for k, v in user_raw.items() if k != "dark"}

    # This reconstruction intentionally omits the core's v1.1.0-deprecated
    # ``page_background`` -> ``page`` shims (user ``doxtr_page_background`` and
    # theme ``doxtr_theme_defaults['page_background']``); doto only uses the
    # ``page`` key as a contrast background and those shims are slated for
    # removal in core v1.1.0, so a future maintainer diffing against the core
    # should not treat their absence as a missing merge step.
    # Three-tier merge: core -> theme -> user (same order as the core engine).
    # ``base_palette`` is already a deep copy from the seam, so the merge never
    # mutates the core's module-level constant.
    merged = deep_update(
        deep_update(base_palette, copy.deepcopy(palette_theme)),
        copy.deepcopy(palette_user),
    )
    return merged


def resolve_doto_palette_colors(app: Sphinx) -> dict[str, str]:
    r"""Resolve doto's ``dd:`` color expressions against the semantic palette.

    Uses ``doxtr_pdf_theme_core.utils.resolve_color`` (the ``dd:`` expression
    system) to turn each entry of :data:`DOTO_COLOR_EXPRESSIONS` into a static
    hex color. Resolution runs against the core's three-tier merged light
    palette (core defaults -> theme defaults -> user config, see
    :func:`_merged_semantic_palette`), not ``config.doxtr_semantic_palette``
    alone, so brand keys such as ``primary`` and ``danger`` supplied by the
    core/theme are available even when the user only overrides a few keys.
    Degrades gracefully: returns an empty dict when the core is not importable.

    Args:
        app: Sphinx application instance.

    Returns:
        Mapping of doto color macro name (e.g. ``doto@critical``) to a resolved
        hex color string (e.g. ``#E74C3C``). Empty when unavailable.
    """
    palette = _merged_semantic_palette(app)
    if not palette:
        return {}

    try:
        from doxtr_pdf_theme_core.utils import resolve_color
    except ImportError:
        return {}

    page_bg = palette.get("page", "#FFFFFF")

    resolved: dict[str, str] = {}
    for macro_name, expr in DOTO_COLOR_EXPRESSIONS.items():
        try:
            color = resolve_color(expr, palette, page_bg, "", {}, {}, {}, {})
        except Exception:
            # Never let a color-resolution edge case break the build; the
            # doto.sty default for this macro remains in effect.
            continue
        if isinstance(color, str) and color.startswith("#"):
            resolved[macro_name] = color
    return resolved


def build_doto_color_preamble(resolved: dict[str, str]) -> str:
    r"""Build a LaTeX preamble block of ``\definecolor`` overrides.

    Args:
        resolved: Mapping of doto color macro name to hex color, as produced by
            :func:`resolve_doto_palette_colors`.

    Returns:
        A LaTeX snippet (possibly empty) redefining the ``doto@*`` colors. Each
        color is emitted with ``\definecolor{<name>}{HTML}{RRGGBB}``; the
        leading ``#`` and any alpha channel are stripped so the value is a bare
        6-digit hex accepted by xcolor's ``HTML`` model.
    """
    if not resolved:
        return ""

    lines = ["% doto semantic palette overrides"]
    for macro_name, hex_color in resolved.items():
        clean = hex_color.lstrip("#")
        # xcolor HTML model wants 6 hex digits; drop an alpha channel if present.
        if len(clean) >= 6:
            clean = clean[:6]
        else:
            continue
        lines.append(f"\\definecolor{{{macro_name}}}{{HTML}}{{{clean.upper()}}}")
    if len(lines) == 1:
        return ""
    return "\n".join(lines) + "\n"


def get_landscape_min_columns(app: Sphinx) -> int:
    """Return the core's landscape column threshold for wide tables.

    Reads ``app.config.doxtr_landscape_min_columns`` when the core is active,
    falling back to the core's ``DEFAULT_MIN_COLUMNS`` constant (or a hardcoded
    4 if the core cannot be imported). Used by the LaTeX task-table renderer to
    decide when a table should be rotated to landscape (Feature 6).

    Args:
        app: Sphinx application instance.

    Returns:
        The minimum column count that triggers landscape rotation.
    """
    default_min = 4
    try:
        from doxtr_pdf_theme_core.ast_processors.landscape import (
            DEFAULT_MIN_COLUMNS,
        )

        default_min = DEFAULT_MIN_COLUMNS
    except ImportError:
        pass
    value = getattr(app.config, "doxtr_landscape_min_columns", None)
    if isinstance(value, int) and value > 0:
        return value
    return default_min


def wrap_longtable_in_landscape(body: str, col_count: int) -> str:
    r"""Wrap raw longtable LaTeX in the core's adaptive-landscape environment.

    The doto task table is emitted as a raw ``longtable`` and therefore never
    reaches the core's docutils-``table`` landscape AST processor. This helper
    applies the same rotation the core would have applied to a wide table: it
    wraps the longtable in ``\begin{doxtradaptivelandscape}[N]`` /
    ``\end{doxtradaptivelandscape}`` (defined in the core's ``preamble.tex_t``),
    which selects an appropriate A-series landscape page size for ``N`` columns
    and lets the breakable longtable paginate naturally.

    The ``doxtradaptivelandscape`` environment is preferred over the plain
    pdflscape ``landscape`` environment because the core does not load
    pdflscape unconditionally, and because ``doxtradaptivelandscape`` is
    breakable (a plain ``landscape``/minipage wrap would clip a tall table).

    Args:
        body: The raw longtable LaTeX (a ``\begin{longtable}...\end{longtable}``
            block, possibly with trailing whitespace).
        col_count: The number of columns in the table, used to size the
            adaptive landscape page.

    Returns:
        The same LaTeX wrapped in the adaptive landscape environment.
    """
    n = col_count if isinstance(col_count, int) and col_count > 0 else 1
    return (
        f"\n\\begin{{doxtradaptivelandscape}}[{n}]\n" + body + "\n\\end{doxtradaptivelandscape}\n"
    )


def _register_doxtr_containers(app: Sphinx) -> None:
    """
    Register doto as a custom container type in doxtr's system.

    Uses ThemeRegistry if available (doxtr-pdf-theme-core >= 2.0),
    falls back to config-based registration for older versions.
    """
    # Try new registry pattern first
    try:
        from doxtr.pdf_theme_core import ThemeRegistry

        ThemeRegistry.register_element(
            "doto",
            {
                "template": "doto/task.tex.jinja",
                "styles": {
                    "default": "doto/styles/default.yaml",
                    "minimal": "doto/styles/minimal.yaml",
                },
            },
        )

        # Register priority variants
        for priority in ["low", "medium", "high", "critical"]:
            ThemeRegistry.register_element(
                f"doto-task-{priority}",
                {
                    "parent": "doto",
                    "style_overrides": f"doto/styles/{priority}.yaml",
                },
            )

        return
    except (ImportError, AttributeError):
        pass  # Fall back to config-based registration

    # Fallback: config-based registration (existing code)
    # Get or initialize doxtr_containers config
    if not hasattr(app.config, "doxtr_containers"):
        return

    containers = getattr(app.config, "doxtr_containers", {})

    # Register doto task container styles
    containers.setdefault(
        "doto-task",
        {
            "title_style": "classic",
            "title_icon": r"\faListCheck",
            "title_color": "#3B82F6",
        },
    )

    # Priority-specific overrides.
    #
    # These hex literals mirror PRIORITY_COLORS in src/doxtr_doto/constants.py
    # (the SINGLE SOURCE OF TRUTH for the doto palette). Keep them in sync with
    # that module; do not edit the doxtr color-resolution logic here — only the
    # fallback values. See PHASE F2 in the fix brief.
    containers.setdefault(
        "doto-task-low",
        {
            "title_color": "#6c757d",
            "border_color": "#6c757d",
        },
    )
    containers.setdefault(
        "doto-task-medium",
        {
            "title_color": "#0d6efd",
            "border_color": "#0d6efd",
        },
    )
    containers.setdefault(
        "doto-task-high",
        {
            "title_color": "#fd7e14",
            "border_color": "#fd7e14",
        },
    )
    containers.setdefault(
        "doto-task-critical",
        {
            "title_color": "#dc3545",
            "border_color": "#dc3545",
        },
    )


def get_doxtr_color(
    app: Sphinx,
    color_name: str,
    fallback: str = "#000000",
) -> str:
    """
    Get a color from doxtr's semantic palette if available.

    Args:
        app: Sphinx application
        color_name: Name of the color in doxtr palette
        fallback: Fallback color if not available

    Returns:
        Color value (hex string)
    """
    if not hasattr(app.config, "doxtr_semantic_palette"):
        return fallback

    palette = getattr(app.config, "doxtr_semantic_palette", {})
    color: str = palette.get(color_name, fallback)
    return color
