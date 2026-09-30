"""Sphinx domain for doto tasks.

Provides proper domain-based cross-referencing for tasks, enabling:
- Standard `:doto:task:`TASK-001`` role syntax
- Integration with Sphinx's cross-reference system
- Automatic index generation
- Intersphinx support
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterable

from docutils import nodes
from sphinx.domains import Domain, ObjType
from sphinx.roles import XRefRole
from sphinx.util.nodes import make_refnode

if TYPE_CHECKING:
    from sphinx.addnodes import pending_xref
    from sphinx.application import Sphinx
    from sphinx.builders import Builder
    from sphinx.environment import BuildEnvironment


class DotoXRefRole(XRefRole):
    """Cross-reference role for doto tasks.
    
    Handles the `:doto:task:` role syntax for referencing tasks.
    """
    
    def process_link(
        self,
        env: BuildEnvironment,
        refnode: nodes.Element,
        has_explicit_title: bool,
        title: str,
        target: str,
    ) -> tuple[str, str]:
        """Process the link target and title.
        
        Args:
            env: Build environment.
            refnode: The reference node being built.
            has_explicit_title: Whether an explicit title was provided.
            title: The display title.
            target: The reference target (task ID).
            
        Returns:
            Tuple of (title, target) after processing.
        """
        refnode["doto:task_id"] = target
        if not has_explicit_title:
            title = target
        return title, target


class DotoDomain(Domain):
    """Sphinx domain for doto task management.
    
    Registers tasks and provides cross-reference resolution for task IDs.
    """
    
    name = "doto"
    label = "Doto Tasks"
    
    object_types = {
        "task": ObjType("task", "task"),
    }
    
    directives: dict[str, Any] = {
        # Tasks are registered via the doto directive, not domain directive
    }
    
    roles = {
        "task": DotoXRefRole(),
    }
    
    initial_data: dict[str, Any] = {
        "tasks": {},  # task_id -> (docname, lineno, title)
    }
    
    @property
    def tasks(self) -> dict[str, tuple[str, int, str]]:
        """Return task registry.
        
        Returns:
            Dictionary mapping task_id to (docname, lineno, title).
        """
        return self.data.setdefault("tasks", {})
    
    def note_task(
        self,
        task_id: str,
        docname: str,
        lineno: int,
        title: str,
    ) -> None:
        """Register a task in the domain.
        
        Args:
            task_id: Unique task identifier.
            docname: Document containing the task.
            lineno: Line number of the task definition.
            title: Task title.
        """
        self.tasks[task_id] = (docname, lineno, title)
    
    def clear_doc(self, docname: str) -> None:
        """Clear tasks from a document.
        
        Called when a document is being re-read.
        
        Args:
            docname: Document name being cleared.
        """
        to_remove = [
            task_id for task_id, (doc, _, _) in self.tasks.items()
            if doc == docname
        ]
        for task_id in to_remove:
            del self.tasks[task_id]
    
    def merge_domaindata(
        self,
        docnames: list[str],
        otherdata: dict[str, Any],
    ) -> None:
        """Merge domain data from parallel builds.
        
        Args:
            docnames: List of document names from the other build.
            otherdata: Domain data from the other build.
        """
        for task_id, (docname, lineno, title) in otherdata.get("tasks", {}).items():
            if docname in docnames:
                self.tasks[task_id] = (docname, lineno, title)
    
    def resolve_xref(
        self,
        env: BuildEnvironment,
        fromdocname: str,
        builder: Builder,
        typ: str,
        target: str,
        node: pending_xref,
        contnode: nodes.Element,
    ) -> nodes.reference | None:
        """Resolve a cross-reference to a task.
        
        Args:
            env: Build environment.
            fromdocname: Document containing the reference.
            builder: The active builder.
            typ: Reference type (should be "task").
            target: Target task ID.
            node: The pending_xref node.
            contnode: The content node to wrap.
            
        Returns:
            Resolved reference node or None if not found.
        """
        if target not in self.tasks:
            # Try to resolve from collector as fallback
            return self._resolve_from_collector(
                env, fromdocname, builder, target, contnode
            )
        
        docname, lineno, title = self.tasks[target]
        
        return make_refnode(
            builder,
            fromdocname,
            docname,
            target,
            contnode,
            title=f"{target}: {title}",
        )
    
    def _resolve_from_collector(
        self,
        env: BuildEnvironment,
        fromdocname: str,
        builder: Builder,
        target: str,
        contnode: nodes.Element,
    ) -> nodes.reference | None:
        """Resolve reference from collector data as fallback.
        
        This handles tasks that were registered via the collector but not
        yet registered with the domain (e.g., during initial setup).
        
        Args:
            env: Build environment.
            fromdocname: Document containing the reference.
            builder: The active builder.
            target: Target task ID.
            contnode: The content node to wrap.
            
        Returns:
            Resolved reference node or None if not found.
        """
        from doxtr_doto.collectors import get_doto_env
        
        doto_env = get_doto_env(env)
        
        if target not in doto_env.all_tasks:
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
        
        return make_refnode(
            builder,
            fromdocname,
            task.docname,
            target,
            contnode,
            title=f"{target}: {task.title}",
        )
    
    def resolve_any_xref(
        self,
        env: BuildEnvironment,
        fromdocname: str,
        builder: Builder,
        target: str,
        node: pending_xref,
        contnode: nodes.Element,
    ) -> list[tuple[str, nodes.reference]]:
        """Resolve any cross-reference (for :any: role).
        
        Args:
            env: Build environment.
            fromdocname: Document containing the reference.
            builder: The active builder.
            target: Target to resolve.
            node: The pending_xref node.
            contnode: The content node to wrap.
            
        Returns:
            List of (domain:type, reference_node) tuples.
        """
        refnode = self.resolve_xref(
            env, fromdocname, builder, "task", target, node, contnode
        )
        if refnode is None:
            return []
        
        return [("doto:task", refnode)]
    
    def get_objects(self) -> Iterable[tuple[str, str, str, str, str, int]]:
        """Return all tasks for the objects inventory.
        
        Used by intersphinx and the search index.
        
        Yields:
            Tuples of (name, dispname, type, docname, anchor, priority).
        """
        for task_id, (docname, lineno, title) in self.tasks.items():
            yield (
                task_id,      # name
                title,        # dispname
                "task",       # type
                docname,      # docname
                task_id,      # anchor
                1,            # priority (1 = default)
            )
    
    def get_full_qualified_name(self, node: nodes.Element) -> str | None:
        """Return fully qualified name for a node.
        
        Args:
            node: The node to get the name for.
            
        Returns:
            Fully qualified name or None.
        """
        target = node.get("reftarget")
        if target:
            return f"doto.{target}"
        return None


def setup(app: Sphinx) -> dict[str, Any]:
    """Set up the doto domain.
    
    Args:
        app: Sphinx application instance.
        
    Returns:
        Extension metadata.
    """
    app.add_domain(DotoDomain)
    
    return {
        "version": "0.1.0",
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
