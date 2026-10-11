"""Namespaced task-ID resolution across repositories.

Task identifiers can be written as ``repo#id`` (e.g. ``web-app#14``) or as a
bare ``id``. This module parses those identifiers and resolves them to a
concrete :class:`doxtr_doto.cli.json_store.JsonTaskStore` and local task id:

* ``repo#id`` looks ``repo`` up in the cached :class:`RepoRegistry`.
* a bare ``id`` is resolved against the current working directory's store
  (the one already loaded into the CLI context).

Resolution is a thin, side-effect-free layer so commands can accept
namespaced ids from any working directory without duplicating lookup logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from doxtr_doto.cli.json_store import JsonTaskStore
    from doxtr_doto.cli.main import DotoContext


@dataclass(frozen=True)
class ResolvedTask:
    """A resolved namespaced task reference.

    Attributes:
        repo: The repository name owning the task.
        task_id: The local (bare) task identifier.
        store: The task store that holds the task.
    """

    repo: str
    task_id: str
    store: JsonTaskStore


def split_task_ref(value: str) -> tuple[str | None, str]:
    """Split a possibly-namespaced identifier into ``(repo, task_id)``.

    This is the single canonical splitter for ``repo#id`` references; the
    aliases :func:`doxtr_doto.cli.session.split_namespaced_id` and
    :func:`doxtr_doto.cli.display` consumers re-export it so there is one
    source of truth.

    Args:
        value: Either ``repo#id`` or a bare ``id``.

    Returns:
        ``(repo, task_id)`` where ``repo`` is None when the input was not
        namespaced.
    """
    if "#" in value:
        repo, _, task_id = value.partition("#")
        return (repo or None, task_id)
    return (None, value)


def base_id(task_id: str) -> str:
    """Return the base prefix of a task id (its trailing ``-<digits>`` stripped).

    The "base" of an id is the identifier with a single trailing
    ``-<digits>`` suffix removed, e.g. ``base_id("CALC-002") == "CALC"`` and
    ``base_id("FOO-BAR-01") == "FOO-BAR"``. When there is no such numeric
    suffix the whole id is its own base (``base_id("RELEASE") == "RELEASE"``).

    This lives alongside the other id-parsing helpers so there is one place
    that understands id structure; :mod:`doxtr_doto.cli.display` uses it to
    decide, per view, whether a short (bare) id is unambiguous.

    Args:
        task_id: A local task identifier (e.g. ``CALC-002``).

    Returns:
        The base prefix.
    """
    prefix, sep, suffix = task_id.rpartition("-")
    if sep and prefix and suffix.isdigit():
        return prefix
    return task_id


def namespaced_id(repo: str, task_id: str) -> str:
    """Build a namespaced ``repo#id`` identifier.

    This is the single canonical builder for ``repo#id`` references; the
    aliases :func:`doxtr_doto.cli.session.namespaced_id` and
    :func:`doxtr_doto.cli.display.namespaced` re-export it so there is one
    source of truth.

    Args:
        repo: The repository name.
        task_id: The local task identifier.

    Returns:
        The ``repo#id`` string.
    """
    return f"{repo}#{task_id}"


def resolve_task_ref(ctx: DotoContext, value: str) -> ResolvedTask | None:
    """Resolve a namespaced or bare task reference to a store + local id.

    Args:
        ctx: The CLI context (provides the current store and global state).
        value: Either ``repo#id`` or a bare ``id``.

    Returns:
        A :class:`ResolvedTask`, or None if a named repository could not be
        found in the cached registry.
    """
    from doxtr_doto.cli.json_store import JsonTaskStore
    from doxtr_doto.cli.repo_registry import DOTO_MARKER, RepoRegistry
    from doxtr_doto.cli.session import derive_repo_name

    repo_name, task_id = split_task_ref(value)

    if repo_name is None:
        # Bare id → current working directory's store.
        return ResolvedTask(
            repo=derive_repo_name(ctx.config),
            task_id=task_id,
            store=ctx.store,
        )

    # Namespaced id → look up the repo in the cached registry.
    registry = RepoRegistry(ctx.global_store)
    repo = registry.resolve(repo_name)
    if repo is None:
        return None

    store_path = Path(repo.path) / DOTO_MARKER
    return ResolvedTask(
        repo=repo_name,
        task_id=task_id,
        store=JsonTaskStore(store_path),
    )
