"""Doto role for cross-referencing tasks."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from docutils import nodes
from sphinx.addnodes import pending_xref
from sphinx.util.nodes import split_explicit_title

if TYPE_CHECKING:
    from docutils.parsers.rst.states import Inliner
    from sphinx.application import Sphinx
    from sphinx.environment import BuildEnvironment


def doto_role(
    name: str,
    rawtext: str,
    text: str,
    lineno: int,
    inliner: Inliner,
    options: dict[str, Any] | None = None,
    content: list[str] | None = None,
) -> tuple[list[nodes.Node], list[nodes.system_message]]:
    """
    Role for cross-referencing doto tasks.

    Now uses the doto domain for resolution, enabling proper intersphinx
    support and standard Sphinx cross-reference handling.

    Usage:
        :doto:`TASK-001`
        :doto:`TASK-001 <custom text>`
    """
    options = options or {}
    content = content or []

    # Parse explicit title if present
    has_explicit_title, title, target = split_explicit_title(text)
    target = target.strip()

    # Create a domain-based pending cross-reference node
    ref_node = pending_xref(
        rawtext,
        refdomain="doto",
        reftype="task",
        reftarget=target,
        refwarn=True,
        refexplicit=has_explicit_title,
        classes=["doto-ref"],
    )
    ref_node["doto_target"] = target  # Store original target for fallback

    # Set the display text
    inner_node = nodes.literal(
        rawtext, title if has_explicit_title else target, classes=["xref", "doto"]
    )
    ref_node += inner_node

    return [ref_node], []


def resolve_doto_xref(
    app: Sphinx,
    env: BuildEnvironment,
    node: pending_xref,
    contnode: nodes.Node,
) -> nodes.reference | None:
    """
    Resolve a doto cross-reference to its target.

    Connected to missing-reference event.
    """
    # Check if this is our doto reference
    if node.get("reftype") != "doto":
        return None

    from doxtr_doto.collectors import get_doto_env

    target = node.get("doto_target", "") or node.get("reftarget", "")
    doto_env = get_doto_env(env)

    if target not in doto_env.all_tasks:
        # Task not found - return None to let Sphinx emit warning
        return None

    task = doto_env.all_tasks[target]

    if task.docname is None:
        # Task has no document (JSON-only, possibly archived)
        # Create a broken reference
        ref_node = nodes.reference(
            "",
            "",
            internal=True,
            refuri="#",
            classes=["doto-ref", "doto-broken-ref"],
        )
        ref_node += contnode
        return ref_node

    # Create resolved reference
    try:
        refuri = app.builder.get_relative_uri(env.docname, task.docname)
        refuri += f"#{target}"
    except Exception:
        refuri = f"#{target}"

    ref_node = nodes.reference(
        "",
        "",
        internal=True,
        refuri=refuri,
        classes=["doto-ref"],
    )
    ref_node["title"] = f"{target}: {task.title}"

    # Use the content node
    ref_node += contnode

    return ref_node
