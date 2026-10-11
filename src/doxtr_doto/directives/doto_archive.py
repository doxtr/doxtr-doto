"""The doto-archive directive for rendering the archived-task page.

Unlike ``doto-list`` (which filters tasks by directive options), ``doto-archive``
always renders *all* archived tasks, sourced from the JSON task store via the
build environment. It exists so the virtual archive page (built by
:mod:`doxtr_doto.builders.archive_doc`) can present archived tasks with their
full metadata (id, title, status, assignee, priority, archived_on, original
page, body) using the theme/template system, keeping the rendering modular and
child-theme overridable.
"""

from __future__ import annotations

from typing import ClassVar

from docutils import nodes
from sphinx.util.docutils import SphinxDirective

from doxtr_doto.nodes import doto_archive_node


class DotoArchiveDirective(SphinxDirective):
    """Directive that renders all archived tasks from the JSON store.

    Usage::

        .. doto-archive::

    Takes no options or content: the archived tasks are read from the build
    environment (kept in sync with ``.doto/tasks.json``) at render time, so the
    page always reflects the current archive state.
    """

    has_content: ClassVar[bool] = False
    required_arguments: ClassVar[int] = 0
    optional_arguments: ClassVar[int] = 0
    option_spec: ClassVar[dict[str, object]] = {}

    def run(self) -> list[nodes.Node]:
        """Return a single ``doto_archive_node`` for later JSON-sourced render.

        Returns:
            A list containing the archive node; its visit handler pulls the
            archived tasks from the environment and renders them.
        """
        node = doto_archive_node("")
        node.source = self.get_source_info()[0]
        node.line = self.lineno
        return [node]
