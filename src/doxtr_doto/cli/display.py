"""Context-aware, overridable presentation for cross-repo task views.

The multi-repo (``doto list -r``) and single-repo (``doto list``) views share
the same column rendering in :mod:`doxtr_doto.cli.output`; the only difference
is whether task ids are shown with a ``repo#`` prefix.

:data:`DisplayScope` captures that choice and :func:`apply_scope` is a small,
overridable presentation step that rewrites the ``id`` column for display. A
child theme or alternate renderer can replace :func:`apply_scope` wholesale
(the three callers import it by name, so the whole function is the seam)
without touching command logic or the underlying column renderer. The
short-vs-long policy itself lives in one named predicate, :func:`_should_namespace`,
so a replacement can mirror or retarget that rule without re-deriving the
threshold.

In :data:`DisplayScope.GLOBAL`, ids are shortened *per view*: a task keeps its
bare local id when its base prefix (the id with a trailing ``-<digits>``
suffix stripped, e.g. ``CALC`` for ``CALC-002``) is used by only one repo in
the current view. When two or more repos share a base prefix in the same view,
*every* task with that base prefix is shown in the full ``repo#id`` form so the
group stays unambiguous. Uniqueness is always computed over the single list
handed to :func:`apply_scope` (the aggregated, gathered-scope view), never
over all repos globally. Note that this list is the set gathered for the view
(e.g. the aggregated repos), which may be a superset of what a later text or
view filter ultimately shows.
"""

from __future__ import annotations

from collections import defaultdict
from enum import Enum
from typing import Any

from doxtr_doto.cli.id_resolver import base_id
from doxtr_doto.cli.id_resolver import namespaced_id as namespaced


class DisplayScope(Enum):
    """Whether task ids should be namespaced for display.

    Attributes:
        LOCAL: Single-repo view; the ``repo#`` prefix is suppressed.
        GLOBAL: Aggregated/recursive view; ids are shown as ``repo#id``.
    """

    LOCAL = "local"
    GLOBAL = "global"


def tag_repo(tasks: list[dict[str, Any]], repo: str) -> list[dict[str, Any]]:
    """Tag each task with its owning repository name.

    The repo name is recorded under ``_repo`` and the original local id is
    preserved under ``_local_id`` so later display logic can namespace ids
    without losing the bare id.

    Args:
        tasks: Task dicts (each must contain an ``id``).
        repo: The repository name to attach.

    Returns:
        The same task dicts, mutated in place and returned for convenience.
    """
    for task in tasks:
        task["_repo"] = repo
        task.setdefault("_local_id", task.get("id", ""))
    return tasks


def _should_namespace(repos: set[str]) -> bool:
    """Decide whether a base-prefix group should be namespaced for display.

    This is the single policy point behind :func:`apply_scope`'s short-vs-long
    decision: a group is namespaced (shown as ``repo#id``) when more than one
    repo shares its base prefix in the current view, and shown bare otherwise.
    It is factored out so the rule has one named home that a child
    theme/renderer overriding :func:`apply_scope` can mirror or replace
    without re-deriving the threshold.

    Args:
        repos: The set of repos that use a given base prefix in this view.

    Returns:
        ``True`` to namespace the whole group, ``False`` to keep bare ids.
    """
    return len(repos) > 1


def apply_scope(
    tasks: list[dict[str, Any]],
    scope: DisplayScope,
) -> list[dict[str, Any]]:
    """Rewrite task ids for display according to ``scope``.

    In :data:`DisplayScope.GLOBAL`, ids are shortened per view by base-prefix
    uniqueness:

    * The base prefix of each task is computed from its bare local id with
      :func:`doxtr_doto.cli.id_resolver.base_id` (``CALC`` for ``CALC-002``).
    * A base prefix is *unique* when every task sharing it in this view
      belongs to the same repo. Those tasks keep their bare local id.
    * When two or more repos share a base prefix in this view, *all* tasks
      with that base prefix are rewritten to ``repo#id`` so the group stays
      unambiguous — even if the full ids would not have individually
      collided.

    Untagged tasks (no ``_repo``) are left as-is; this makes the function a
    no-op for single-repo lists that were never tagged. In
    :data:`DisplayScope.LOCAL`, ids are left as-is.

    ``_repo`` and ``_local_id`` are always preserved so the id resolver and
    TUI actions can map a displayed id back to its owning repo.

    Args:
        tasks: Task dicts, optionally tagged by :func:`tag_repo`.
        scope: The display scope.

    Returns:
        The task dicts, mutated in place and returned for convenience.
    """
    if scope is DisplayScope.LOCAL:
        return tasks

    # Per-view pass 1: map each base prefix to the set of repos that use it in
    # this (aggregated, gathered-scope) view. Untagged tasks are ignored
    # here; they are left untouched below.
    repos_by_base: dict[str, set[str]] = defaultdict(set)
    for task in tasks:
        repo = task.get("_repo")
        if not repo:
            continue
        local_id = task.get("_local_id", task.get("id", ""))
        repos_by_base[base_id(local_id)].add(repo)

    # Pass 2: namespace only the groups whose base prefix is shared by more
    # than one repo; otherwise keep the bare local id.
    for task in tasks:
        repo = task.get("_repo")
        if not repo:
            continue
        local_id = task.get("_local_id", task.get("id", ""))
        if _should_namespace(repos_by_base[base_id(local_id)]):
            task["id"] = namespaced(repo, local_id)
        else:
            task["id"] = local_id
    return tasks
