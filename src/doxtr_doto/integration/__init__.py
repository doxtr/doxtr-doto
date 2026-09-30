"""Integration with doxtr-pdf-theme-core and other tools.

This package contains integration with external tools and extensions.
"""

from __future__ import annotations

from doxtr_doto.integration.doxtr import (
    _register_doxtr_containers,
    apply_doxtr_semantic_colors,
    build_doto_color_preamble,
    detect_doxtr_features,
    get_doxtr_color,
    get_landscape_min_columns,
    resolve_doto_palette_colors,
    setup_doxtr_integration,
    wrap_longtable_in_landscape,
)

__all__ = [
    "detect_doxtr_features",
    "get_doxtr_color",
    "setup_doxtr_integration",
    "_register_doxtr_containers",
    "apply_doxtr_semantic_colors",
    "build_doto_color_preamble",
    "get_landscape_min_columns",
    "resolve_doto_palette_colors",
    "wrap_longtable_in_landscape",
]
