"""
doto - Documentation Task Management for Sphinx

A Sphinx extension for managing documentation tasks with structured metadata,
bidirectional sync with JSON storage, and a companion CLI tool.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

# Import task_hooks for public API
from doxtr_doto.hooks import task_hooks

if TYPE_CHECKING:
    from sphinx.application import Sphinx
    from sphinx.environment import BuildEnvironment

__version__ = "0.3.0"

__all__ = ["setup", "task_hooks", "__version__"]


def setup(app: Sphinx) -> dict[str, Any]:
    """Set up the doto Sphinx extension."""
    from doxtr_doto.builders.archive_doc import (
        add_archive_doc,
        cleanup_virtual_docs,
        inject_archive_doc,
        read_virtual_doc,
    )
    from doxtr_doto.collectors import DotoCollector
    from doxtr_doto.config import setup_config
    from doxtr_doto.directives.doto import DotoDirective
    from doxtr_doto.directives.doto_archive import DotoArchiveDirective
    from doxtr_doto.directives.doto_list import DotoListDirective
    from doxtr_doto.directives.doto_summary import DotoSummaryDirective
    from doxtr_doto.domain import DotoDomain
    from doxtr_doto.integration.doxtr import setup_doxtr_integration
    from doxtr_doto.nodes import (
        depart_doto_archive_node_epub,
        depart_doto_archive_node_html,
        depart_doto_archive_node_latex,
        depart_doto_list_node_epub,
        depart_doto_list_node_html,
        depart_doto_list_node_latex,
        depart_doto_node_epub,
        depart_doto_node_html,
        depart_doto_node_latex,
        depart_doto_ref_epub,
        depart_doto_ref_html,
        depart_doto_ref_latex,
        depart_doto_summary_node_epub,
        depart_doto_summary_node_html,
        depart_doto_summary_node_latex,
        doto_archive_node,
        doto_list_node,
        doto_node,
        doto_ref,
        doto_summary_node,
        visit_doto_archive_node_epub,
        visit_doto_archive_node_html,
        visit_doto_archive_node_latex,
        visit_doto_list_node_epub,
        visit_doto_list_node_html,
        visit_doto_list_node_latex,
        visit_doto_node_epub,
        visit_doto_node_html,
        visit_doto_node_latex,
        visit_doto_ref_epub,
        visit_doto_ref_html,
        visit_doto_ref_latex,
        visit_doto_summary_node_epub,
        visit_doto_summary_node_html,
        visit_doto_summary_node_latex,
    )
    from doxtr_doto.roles.doto_ref import doto_role, resolve_doto_xref
    from doxtr_doto.sync import (
        perform_bidirectional_sync,
        write_rst_updates,
    )
    from doxtr_doto.transforms.archive import DotoArchiveTransform
    from doxtr_doto.transforms.toc_inject import DotoTocInjectTransform

    # Register configuration values
    setup_config(app)

    # Register doto domain for cross-references
    app.add_domain(DotoDomain)

    # Register nodes
    app.add_node(
        doto_node,
        html=(visit_doto_node_html, depart_doto_node_html),
        latex=(visit_doto_node_latex, depart_doto_node_latex),
        epub=(visit_doto_node_epub, depart_doto_node_epub),
    )
    app.add_node(
        doto_list_node,
        html=(visit_doto_list_node_html, depart_doto_list_node_html),
        latex=(visit_doto_list_node_latex, depart_doto_list_node_latex),
        epub=(visit_doto_list_node_epub, depart_doto_list_node_epub),
    )
    app.add_node(
        doto_summary_node,
        html=(visit_doto_summary_node_html, depart_doto_summary_node_html),
        latex=(visit_doto_summary_node_latex, depart_doto_summary_node_latex),
        epub=(visit_doto_summary_node_epub, depart_doto_summary_node_epub),
    )
    app.add_node(
        doto_archive_node,
        html=(visit_doto_archive_node_html, depart_doto_archive_node_html),
        latex=(visit_doto_archive_node_latex, depart_doto_archive_node_latex),
        epub=(visit_doto_archive_node_epub, depart_doto_archive_node_epub),
    )
    app.add_node(
        doto_ref,
        html=(visit_doto_ref_html, depart_doto_ref_html),
        latex=(visit_doto_ref_latex, depart_doto_ref_latex),
        epub=(visit_doto_ref_epub, depart_doto_ref_epub),
    )

    # Register directives
    app.add_directive("doto", DotoDirective)
    app.add_directive("doto-list", DotoListDirective)
    app.add_directive("doto-summary", DotoSummaryDirective)
    app.add_directive("doto-archive", DotoArchiveDirective)

    # Register role
    app.add_role("doto", doto_role)

    # Connect missing-reference handler for doto cross-references
    app.connect("missing-reference", resolve_doto_xref)

    # Register environment collector
    app.add_env_collector(DotoCollector)

    # Register transforms
    app.add_transform(DotoArchiveTransform)
    app.add_transform(DotoTocInjectTransform)

    # Connect event handlers
    # Bidirectional sync (before consistency check)
    app.connect("env-check-consistency", perform_bidirectional_sync, priority=100)

    # Archive processing (after sync)
    app.connect("env-check-consistency", DotoArchiveTransform.process_auto_archive, priority=200)

    # Virtual archive document
    app.connect("env-get-outdated", add_archive_doc)
    app.connect("env-before-read-docs", inject_archive_doc)
    app.connect("source-read", read_virtual_doc)
    app.connect("build-finished", cleanup_virtual_docs, priority=900)  # Run late

    # RST file updates (write merged changes back)
    app.connect("build-finished", write_rst_updates)

    # Doxtr integration
    setup_doxtr_integration(app)

    # Connect handlers for theme and additional config features
    app.connect("builder-inited", _add_theme_css)
    app.connect("config-inited", _setup_latex_theme)
    app.connect("builder-inited", _add_epub_css)
    app.connect("builder-inited", _add_custom_css_files)
    app.connect("config-inited", _setup_latex_preamble)
    # Feature 3: derive doto LaTeX colors from the doxtr semantic palette when
    # doxtr-pdf-theme-core is active. Connected after _setup_latex_theme so the
    # color overrides are appended *after* the \usepackage{doto} line (xcolor
    # lets the later \definecolor win). No-op when the core/palette is absent.
    app.connect("config-inited", _apply_doxtr_semantic_colors)
    app.connect("build-finished", _export_tasks_json)

    # Warn about overdue tasks (after archive processing)
    app.connect("env-check-consistency", _warn_overdue_tasks, priority=300)

    return {
        "version": __version__,
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }


def _discover_project_themes(app: Sphinx) -> dict[str, Path | None]:
    """Discover custom theme files in project's _doto/ directory.

    Looks for:
    - {srcdir}/_doto/html/*.css
    - {srcdir}/_doto/latex/*.sty
    - {srcdir}/_doto/epub/*.css

    Args:
        app: Sphinx application instance.

    Returns:
        Dict mapping builder type to custom theme path.
    """
    srcdir = Path(app.srcdir)
    doto_dir = srcdir / "_doto"

    discovered: dict[str, Path | None] = {
        "html": None,
        "latex": None,
        "epub": None,
    }

    if not doto_dir.exists():
        return discovered

    # HTML custom CSS
    html_dir = doto_dir / "html"
    if html_dir.exists():
        css_files = list(html_dir.glob("*.css"))
        if css_files:
            discovered["html"] = html_dir

    # LaTeX custom sty
    latex_dir = doto_dir / "latex"
    if latex_dir.exists():
        sty_files = list(latex_dir.glob("*.sty"))
        if sty_files:
            discovered["latex"] = latex_dir

    # epub custom CSS
    epub_dir = doto_dir / "epub"
    if epub_dir.exists():
        css_files = list(epub_dir.glob("*.css"))
        if css_files:
            discovered["epub"] = epub_dir

    return discovered


def _add_theme_css(app: Sphinx) -> None:
    """Add the CSS file for the configured HTML theme.

    Connected to builder-inited. Runs after config is finalised so
    doto_html_theme is readable.

    Priority:
    1. Project's _doto/html/ directory (if exists)
    2. Configured doto_html_theme
    3. Default theme

    Args:
        app: Sphinx application instance.
    """
    from sphinx.util import logging

    from doxtr_doto.config import get_config

    # Skip for non-HTML builders
    if app.builder.name not in ("html", "dirhtml", "singlehtml", "readthedocs"):
        return

    # Check for project custom themes first
    discovered = _discover_project_themes(app)
    if discovered["html"]:
        # Use all CSS files from project's _doto/html/
        app.config.html_static_path = list(getattr(app.config, "html_static_path", []) or []) + [
            str(discovered["html"])
        ]
        for project_css in discovered["html"].glob("*.css"):
            app.add_css_file(project_css.name)
        # Register the bundled view-interaction JS even with a project CSS
        # theme: the JS is layout behavior (kanban drag / calendar / email),
        # not styling, so it should ship regardless of the CSS theme in use.
        _add_views_js(app)
        return

    theme_name = get_config(app, "html_theme")  # "default" | "minimal" | ...

    # Map theme names to bundled CSS filenames
    theme_css_map = {
        "default": "doto.css",
        "minimal": "doto-minimal.css",
    }
    css_file = theme_css_map.get(theme_name, "doto.css")

    # Sphinx resolves paths relative to confdir/_static, or from a registered
    # static path. We register the themes/html/ directory as a static path.
    theme_dir = Path(__file__).parent / "themes" / "html"

    if not (theme_dir / css_file).exists():
        logger = logging.getLogger("doxtr_doto")
        logger.warning(
            f"doto_html_theme '{theme_name}' not found "
            f"(looked for {theme_dir / css_file}). Falling back to 'default'."
        )
        css_file = "doto.css"

    # Register the themes/html directory so Sphinx copies its contents to _static
    app.config.html_static_path = list(getattr(app.config, "html_static_path", []) or []) + [
        str(theme_dir)
    ]

    app.add_css_file(css_file)

    # Register the vendored, dependency-free layout-view JS (kanban drag /
    # calendar day reveal / email pane selection). The themes/html directory is
    # already on html_static_path above, so Sphinx copies the JS into _static.
    _add_views_js(app)


def _add_views_js(app: Sphinx) -> None:
    """Register the layout-view JS for HTML builders (project override aware).

    Mirrors the CSS precedence in :func:`_add_theme_css`: if a project ships its
    own ``doto-views.js`` in ``<srcdir>/_doto/html/`` it fully replaces the
    bundled script, so a child theme that re-authors the templates with
    different ``data-*`` hooks (or wants its own interaction behavior) can
    suppress the bundled handlers. Otherwise the bundled, dependency-free
    ``themes/html/doto-views.js`` is registered. In both cases the containing
    directory is placed on ``html_static_path`` so Sphinx copies the script into
    ``_static``. The bundled script is defensive and no-ops on pages without a
    doto-list layout view, so adding it globally is safe.

    Args:
        app: Sphinx application instance (already confirmed to be an HTML
            builder by the caller).
    """
    js_name = "doto-views.js"

    # Project override: <srcdir>/_doto/html/doto-views.js replaces the bundled
    # script (same precedence as the CSS theme seam).
    project_dir = Path(app.srcdir) / "_doto" / "html"
    source_dir = (
        project_dir
        if (project_dir / js_name).exists()
        else Path(__file__).parent / "themes" / "html"
    )
    if not (source_dir / js_name).exists():
        return
    static_paths = list(getattr(app.config, "html_static_path", []) or [])
    if str(source_dir) not in static_paths:
        static_paths.append(str(source_dir))
        app.config.html_static_path = static_paths
    app.add_js_file(js_name)


def _setup_latex_theme(app: Sphinx, config: Any) -> None:
    r"""Set up the correct .sty file based on doto_latex_theme.

    Connected to config-inited event. This MUST run at config-inited (not
    builder-inited) because the LaTeX builder copies ``latex_elements['preamble']``
    into its render context during ``builder.init()``, which happens *before*
    ``builder-inited`` fires. Mutating the preamble at builder-inited is too late
    and the ``\usepackage{doto}`` line never reaches the generated .tex, causing
    ``Environment dotobox undefined`` fatal LaTeX errors.

    Priority:
    1. Project's _doto/latex/ directory (if exists)
    2. Configured doto_latex_theme
    3. Default theme

    ``latex_additional_files`` and ``latex_elements`` are only consumed by the
    LaTeX builder, so registering them unconditionally is harmless for other
    builders (html/epub ignore them).

    Args:
        app: Sphinx application instance.
        config: Sphinx configuration object.
    """
    from sphinx.util import logging

    from doxtr_doto.config import get_config

    # Check for project custom themes first
    discovered = _discover_project_themes(app)
    if discovered["latex"]:
        # Use custom sty files from project's _doto/latex/
        additional = list(getattr(config, "latex_additional_files", []) or [])
        sty_files = list(discovered["latex"].glob("*.sty"))
        for sty_path in sty_files:
            if str(sty_path) not in additional:
                additional.append(str(sty_path))
            # Add usepackage for each custom sty
            pkg_name = sty_path.stem
            preamble_line = f"\\usepackage{{{pkg_name}}}\n"
            latex_elements = dict(getattr(config, "latex_elements", {}) or {})
            existing = latex_elements.get("preamble", "")
            if preamble_line not in existing:
                latex_elements["preamble"] = existing + preamble_line
            config.latex_elements = latex_elements
        config.latex_additional_files = additional
        return

    theme_name = get_config(app, "latex_theme")

    theme_sty_map = {
        "default": "doto.sty",
        "minimal": "doto-minimal.sty",
    }
    sty_file = theme_sty_map.get(theme_name, "doto.sty")

    theme_dir = Path(__file__).parent / "themes" / "latex"
    sty_path = theme_dir / sty_file

    if not sty_path.exists():
        logging.getLogger("doxtr_doto").warning(
            f"doto_latex_theme '{theme_name}' not found. Falling back to 'default'."
        )
        sty_path = theme_dir / "doto.sty"

    # Add to latex_additional_files so Sphinx copies it into the output directory
    additional = list(getattr(config, "latex_additional_files", []) or [])
    if str(sty_path) not in additional:
        additional.append(str(sty_path))
    config.latex_additional_files = additional

    # Ensure \usepackage{doto} is in the preamble (the file is always named doto.sty
    # or doto-minimal.sty, so include by the base name without extension)
    pkg_name = sty_path.stem  # "doto" or "doto-minimal"
    preamble_line = f"\\usepackage{{{pkg_name}}}\n"
    latex_elements = dict(getattr(config, "latex_elements", {}) or {})
    existing = latex_elements.get("preamble", "")
    if preamble_line not in existing:
        latex_elements["preamble"] = existing + preamble_line
    config.latex_elements = latex_elements


def _add_epub_css(app: Sphinx) -> None:
    """Add CSS file for epub builds.

    Connected to builder-inited event.

    Priority:
    1. Project's _doto/epub/ directory (if exists)
    2. Configured doto_epub_theme (or html_theme as fallback)
    3. Default epub theme

    Args:
        app: Sphinx application instance.
    """
    from sphinx.util import logging

    from doxtr_doto.config import get_config

    if app.builder.name not in ("epub", "epub3"):
        return

    # Check for project custom themes first
    discovered = _discover_project_themes(app)
    if discovered["epub"]:
        # Use CSS files from project's _doto/epub/
        epub_css_files = list(getattr(app.config, "epub_css_files", []) or [])
        for epub_css in discovered["epub"].glob("*.css"):
            epub_css_files.append(str(epub_css))
        app.config.epub_css_files = epub_css_files
        return

    # Use configured theme (fallback to html_theme if epub_theme not set)
    theme_name = get_config(app, "epub_theme") or get_config(app, "html_theme")

    theme_css_map = {
        "default": "doto.css",
        "minimal": "doto-minimal.css",
    }
    css_file = theme_css_map.get(theme_name, "doto.css")

    theme_dir = Path(__file__).parent / "themes" / "epub"
    css_path = theme_dir / css_file

    if not css_path.exists():
        logging.getLogger("doxtr_doto").warning(
            f"doto epub theme '{theme_name}' not found. Falling back to 'default'."
        )
        css_path = theme_dir / "doto.css"

    # Add to epub_css_files config
    epub_css_files = list(getattr(app.config, "epub_css_files", []) or [])
    if str(css_path) not in epub_css_files:
        epub_css_files.append(str(css_path))
    app.config.epub_css_files = epub_css_files


def _add_custom_css_files(app: Sphinx) -> None:
    """Add custom CSS files from doto_html_css_files config.

    Connected to builder-inited event.

    Args:
        app: Sphinx application instance.
    """
    from doxtr_doto.config import get_config

    # Skip for non-HTML builders
    if app.builder.name not in ("html", "dirhtml", "singlehtml", "readthedocs"):
        return

    css_files = get_config(app, "html_css_files")
    if css_files:
        for css_file in css_files:
            app.add_css_file(css_file)


def _setup_latex_preamble(app: Sphinx, config: Any) -> None:
    """Add custom LaTeX preamble from doto_latex_preamble config.

    Connected to config-inited event.

    Args:
        app: Sphinx application instance.
        config: Sphinx configuration object.
    """
    preamble = getattr(config, "doto_latex_preamble", "")
    if preamble:
        # Initialize latex_elements if not present
        if not hasattr(config, "latex_elements") or config.latex_elements is None:
            config.latex_elements = {}

        # Append to existing preamble or create new
        existing_preamble = config.latex_elements.get("preamble", "")
        config.latex_elements["preamble"] = existing_preamble + "\n" + preamble


def _apply_doxtr_semantic_colors(app: Sphinx, config: Any) -> None:
    r"""Emit palette-derived doto color overrides into the LaTeX preamble.

    Connected to config-inited event, after ``_setup_latex_theme`` so the
    ``\definecolor`` overrides land after the ``\usepackage{doto}`` line and
    win over the defaults baked into ``doto.sty`` (Feature 3). Delegates to
    :func:`doxtr_doto.integration.doxtr.apply_doxtr_semantic_colors`, which is a
    no-op when ``doxtr-pdf-theme-core`` or a semantic palette is not present.

    Args:
        app: Sphinx application instance.
        config: Sphinx configuration object (unused; palette read via app.config).
    """
    from doxtr_doto.integration.doxtr import apply_doxtr_semantic_colors

    apply_doxtr_semantic_colors(app)


def _export_tasks_json(app: Sphinx, exception: Exception | None) -> None:
    """Export tasks to _static/doto-tasks.json if enabled.

    Connected to build-finished event.

    Args:
        app: Sphinx application instance.
        exception: Exception if build failed, None otherwise.
    """
    if exception is not None:
        return

    from doxtr_doto.config import get_config

    if not get_config(app, "export_json"):
        return

    from doxtr_doto.collectors import get_doto_env

    env = app.env
    doto_env = get_doto_env(env)

    # Get all tasks from environment
    tasks_data: dict[str, dict[str, Any]] = {}

    for task_id, task in doto_env.all_tasks.items():
        # Convert task to serializable dict
        task_dict: dict[str, Any] = {
            "title": task.title,
            "status": task.status,
            "priority": task.priority,
        }
        if task.assignee:
            task_dict["assignee"] = task.assignee
        if task.due:
            # Handle date objects and strings
            task_dict["due"] = (
                task.due.isoformat() if hasattr(task.due, "isoformat") else str(task.due)
            )
        if task.tags:
            task_dict["tags"] = task.tags
        if task.depends_on:
            task_dict["depends_on"] = task.depends_on
        if task.body:
            task_dict["body"] = task.body
        if task.docname:
            task_dict["source_doc"] = task.docname

        tasks_data[task_id] = task_dict

    # Write to _static/doto-tasks.json in output directory
    static_dir = Path(app.outdir) / "_static"
    static_dir.mkdir(parents=True, exist_ok=True)

    output_path = static_dir / "doto-tasks.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "tasks": tasks_data}, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _warn_overdue_tasks(app: Sphinx, env: BuildEnvironment) -> None:
    """Emit Sphinx warnings for overdue open tasks when doto_warn_overdue is True.

    Connected to env-check-consistency event at priority 300 (after archive processing).

    Args:
        app: Sphinx application instance.
        env: Build environment.
    """
    from sphinx.util import logging

    from doxtr_doto.collectors import get_doto_env
    from doxtr_doto.config import get_config
    from doxtr_doto.constants import DONE_STATUS

    if not get_config(app, "warn_overdue"):
        return

    logger = logging.getLogger("doxtr_doto")
    doto_env = get_doto_env(env)

    for task_id, task in doto_env.all_tasks.items():
        # Skip archived and done tasks
        if getattr(task, "archived", False) or task.status == DONE_STATUS:
            continue

        # Check if task is overdue
        if task.is_overdue():
            location = f"{task.docname}:{task.lineno}" if task.docname else task_id
            logger.warning(
                f"Task {task_id} is overdue (due: {task.due})",
                location=location,
                type="doto",
                subtype="overdue",
            )
