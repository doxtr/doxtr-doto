"""Transform to hide doto TOC-injection section titles from page body."""

from __future__ import annotations

from docutils import nodes
from sphinx.transforms import SphinxTransform

from doxtr_doto.nodes import doto_node


class DotoTocInjectTransform(SphinxTransform):
    """Remove visible title text from doto TOC-injection sections.

    The section ids are kept so TOC links still resolve; only the
    rendered <h> tag is suppressed by replacing the title with an
    empty inline target node.
    """

    default_priority = 500  # After standard Sphinx transforms

    def apply(self) -> None:
        from doxtr_doto.config import get_config

        if not get_config(self.app, "render_in_toc"):
            return

        for section in self.document.findall(nodes.section):
            ids = section.get("ids", [])
            # Identify our injected sections by the presence of a doto task id.
            # Convention: injected sections have exactly one id that matches
            # the doto_node sibling that follows them.
            if not ids:
                continue
            # Check whether the next sibling is a doto_node with the same id
            parent = section.parent
            if parent is None:
                continue
            idx = parent.index(section)
            siblings_after = parent.children[idx + 1:]
            if siblings_after and isinstance(siblings_after[0], doto_node):
                sibling_id = siblings_after[0].get("task_id", "")
                if sibling_id in ids:
                    # Replace the title node with a hidden target
                    for child in list(section.children):
                        if isinstance(child, nodes.title):
                            target = nodes.target()
                            target["ids"] = ids
                            target["names"] = section.get("names", [])
                            target["refid"] = ids[0]
                            section.replace(child, target)
