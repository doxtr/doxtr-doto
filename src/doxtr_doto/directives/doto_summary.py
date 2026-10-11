"""The doto-summary directive for displaying task statistics."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from docutils import nodes
from docutils.parsers.rst import directives
from sphinx.util.docutils import SphinxDirective

from doxtr_doto.charts import VALID_CHART_TYPES
from doxtr_doto.nodes import doto_summary_node
from doxtr_doto.utils import parse_boolean, parse_list

if TYPE_CHECKING:
    from sphinx.application import Sphinx


# Valid group-by fields
VALID_GROUP_BY_FIELDS = frozenset({"status", "priority", "assignee", "tags"})

# NOTE: VALID_CHART_TYPES is imported from charts.py (the single authoritative
# source the renderers dispatch on). Do not redefine it here.


def validate_group_by(value: str) -> list[str]:
    """Validate group-by field names.

    Args:
        value: Comma-separated group-by fields.

    Returns:
        List of validated group-by field names.

    Raises:
        ValueError: If any group-by field is invalid.
    """
    fields = parse_list(value)
    for field in fields:
        normalized = field.lower()
        if normalized not in VALID_GROUP_BY_FIELDS:
            raise ValueError(
                f"Invalid group-by field '{field}'. "
                f"Must be one of: {', '.join(sorted(VALID_GROUP_BY_FIELDS))}"
            )
    return [f.lower() for f in fields]


class DotoSummaryDirective(SphinxDirective):
    """Directive for displaying task statistics.

    Usage::

        .. doto-summary::
           :group-by: status, priority
           :assignee: alice
           :show-chart: true

    This directive creates a summary view of tasks, optionally filtered
    and grouped by specified fields. The actual statistics are computed
    during the transform phase when all tasks have been collected.
    """

    has_content: ClassVar[bool] = False
    required_arguments: ClassVar[int] = 0
    optional_arguments: ClassVar[int] = 0

    option_spec: ClassVar[dict[str, object]] = {
        "group-by": directives.unchanged,
        "assignee": directives.unchanged,
        "show-chart": directives.unchanged,
        "chart-type": directives.unchanged,
        "status": directives.unchanged,
        "priority": directives.unchanged,
        "tags": directives.unchanged,
    }

    def run(self) -> list[nodes.Node]:
        """Process the directive and return document nodes.

        Returns:
            List containing the doto_summary_node with configuration.
        """
        # Parse configuration options
        config = self._parse_config()

        # Parse filter options
        filters = self._parse_filters()

        # Create the node with configuration
        node = doto_summary_node(
            "",
            config=config,
            filters=filters,
            docname=self.env.docname,
            lineno=self.lineno,
        )

        # Set source info for better error messages
        node.source = self.get_source_info()[0]
        node.line = self.lineno

        return [node]

    def _parse_config(self) -> dict[str, Any]:
        """Parse and validate configuration options.

        Returns:
            Dictionary of configuration settings.
        """
        config: dict[str, Any] = {}

        # Parse group-by fields
        if "group-by" in self.options:
            try:
                config["group_by"] = validate_group_by(self.options["group-by"])
            except ValueError as e:
                raise self.error(str(e)) from e
        else:
            config["group_by"] = ["status"]  # Default grouping

        # Parse show-chart option
        if "show-chart" in self.options:
            config["show_chart"] = parse_boolean(self.options["show-chart"])
        else:
            config["show_chart"] = False  # Default to no chart

        # Parse chart-type option
        if "chart-type" in self.options:
            chart_type = self.options["chart-type"].strip().lower()
            if chart_type not in VALID_CHART_TYPES:
                raise self.error(
                    f"Invalid chart-type '{chart_type}'. "
                    f"Must be one of: {', '.join(sorted(VALID_CHART_TYPES))}"
                )
            config["chart_type"] = chart_type
        else:
            config["chart_type"] = "bar"  # Default to bar chart

        return config

    def _parse_filters(self) -> dict[str, Any]:
        """Parse and validate filter options.

        Returns:
            Dictionary of filter settings.
        """
        from doxtr_doto.config import get_config

        filters: dict[str, Any] = {}

        # Get valid values from config
        valid_statuses = set(get_config(self.env.app, "statuses"))
        valid_priorities = set(get_config(self.env.app, "priorities"))

        # Parse assignee filter
        if "assignee" in self.options:
            assignees = parse_list(self.options["assignee"])
            if assignees:
                filters["assignee"] = assignees

        # Parse status filter
        if "status" in self.options:
            statuses = parse_list(self.options["status"])
            for s in statuses:
                if s.lower() not in valid_statuses:
                    raise self.error(
                        f"Invalid status '{s}'. Must be one of: {', '.join(sorted(valid_statuses))}"
                    )
            filters["status"] = [s.lower() for s in statuses]

        # Parse priority filter
        if "priority" in self.options:
            priorities = parse_list(self.options["priority"])
            for p in priorities:
                if p.lower() not in valid_priorities:
                    raise self.error(
                        f"Invalid priority '{p}'. "
                        f"Must be one of: {', '.join(sorted(valid_priorities))}"
                    )
            filters["priority"] = [p.lower() for p in priorities]

        # Parse tags filter
        if "tags" in self.options:
            tags = parse_list(self.options["tags"])
            if tags:
                filters["tags"] = tags

        return filters


def _cleanup_orphan_chart_images(app: Sphinx, exception: Exception | None) -> None:
    """Remove plotly chart images no longer referenced after a build.

    Plotly summary charts (Feature 7) are written as content-addressed PNGs
    (``doto-chart-<hash>.png``) into ``_static`` (HTML) and ``_images``
    (LaTeX). Identical charts reuse the same file across rebuilds, but files
    for charts whose underlying task data changed would otherwise linger. This
    build-finished handler prunes ``doto-chart-*`` images that were not written
    during the current build.

    Cleanup is best-effort: it never raises, and it is a no-op when the build
    failed or when no doto chart images were produced this run.

    Args:
        app: Sphinx application instance.
        exception: Build exception if any (skip cleanup on failure).
    """
    if exception is not None:
        return

    import glob
    import os

    produced = getattr(app, "_doto_chart_images", None)
    outdir = getattr(app, "outdir", None)
    if not outdir:
        return

    produced_set = set(produced or ())
    for subdir in ("_static", "_images"):
        pattern = os.path.join(str(outdir), subdir, "doto-chart-*.png")
        for path in glob.glob(pattern):
            if os.path.abspath(path) in produced_set:
                continue
            try:
                os.remove(path)
            except OSError:
                pass


def setup(app: Sphinx) -> dict[str, object]:
    """Set up the doto-summary directive.

    Args:
        app: Sphinx application instance.

    Returns:
        Extension metadata.
    """
    app.add_directive("doto-summary", DotoSummaryDirective)
    # Prune stale plotly chart images after each build (Feature 7 cleanup).
    app.connect("build-finished", _cleanup_orphan_chart_images, priority=800)

    return {
        "version": "0.1.0",
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
