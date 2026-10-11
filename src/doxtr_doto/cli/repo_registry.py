"""Recursive repository discovery and a cached cross-repo registry.

A *repository* is any directory that contains a ``.doto/tasks.json`` task
store. :class:`RepoRegistry` discovers such directories by walking a tree
(pruning noisy directories and honoring ``.gitignore`` entries), and persists
the result into the shared :class:`doxtr_doto.cli.global_state.GlobalState`
so normal operation reads the cache and only rediscovers on explicit request.

Discovery is intentionally conservative: it never writes anything until an
explicit rescan/add/forget operation asks it to, and the on-disk shape is a
simple ``[{"name": str, "path": str}, ...]`` list stored under
``repositories`` in the global config file.
"""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from doxtr_doto.cli.global_state import GlobalStateStore

#: Directory names that are always skipped during discovery.
DEFAULT_PRUNE_DIRS = frozenset(
    {
        ".git",
        "node_modules",
        "target",
        ".venv",
        "dist",
        "build",
        "__pycache__",
        # A repo's own task-store dir; never a nested repo. Pruning it avoids
        # walking into every discovered repo's internals (and the phantom
        # ``.doto/<x>/.doto/tasks.json`` it could otherwise expose).
        ".doto",
    }
)

#: Marker that identifies a doto repository within a directory.
DOTO_MARKER = Path(".doto") / "tasks.json"


@dataclass(frozen=True)
class DiscoveredRepo:
    """A repository found during discovery.

    Attributes:
        name: Short, de-duplicated repository name (parent folder name).
        path: Absolute path to the repository root (the directory that
            contains ``.doto/tasks.json``).
    """

    name: str
    path: str

    def to_dict(self) -> dict[str, str]:
        """Serialize to the on-disk registry shape.

        Returns:
            A ``{"name", "path"}`` dict.
        """
        return {"name": self.name, "path": self.path}


def _load_gitignore_patterns(directory: Path) -> list[str]:
    """Read raw ``.gitignore`` patterns from a directory.

    Only directory-oriented matching is needed for pruning, so blank lines,
    comments and negations are discarded.

    Args:
        directory: Directory whose ``.gitignore`` should be read.

    Returns:
        A list of glob patterns (leading/trailing slashes stripped).
    """
    gitignore = directory / ".gitignore"
    if not gitignore.is_file():
        return []
    patterns: list[str] = []
    try:
        lines = gitignore.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("!"):
            continue
        patterns.append(stripped.strip("/"))
    return patterns


def _matches_gitignore(name: str, patterns: list[str]) -> bool:
    """Return whether a directory name matches any gitignore pattern.

    Matching is deliberately simple: a directory is pruned if its base name
    matches a pattern via :func:`fnmatch.fnmatch`. This covers the common
    cases (``build/``, ``*.egg-info``, ``.cache``) without a full gitignore
    engine.

    Args:
        name: The directory base name.
        patterns: Patterns gathered from ``.gitignore`` files in scope.

    Returns:
        True if the directory should be pruned.
    """
    for pattern in patterns:
        base = pattern.rstrip("/")
        if "/" in base:
            # Path-anchored patterns are matched against the base name's
            # final component only, which is sufficient for pruning.
            base = base.rsplit("/", 1)[-1]
        if fnmatch.fnmatch(name, base):
            return True
    return False


def _dedupe_name(name: str, used: set[str]) -> str:
    """Return a unique name, appending a numeric suffix on collision.

    Args:
        name: The desired base name.
        used: Names already taken (updated in place by the caller).

    Returns:
        ``name`` if free, otherwise ``name-2``, ``name-3``, ... .
    """
    if name not in used:
        return name
    counter = 2
    while f"{name}-{counter}" in used:
        counter += 1
    return f"{name}-{counter}"


class RepoRegistry:
    """Discovers and caches doto repositories across a directory tree.

    The registry reads from and writes to the shared global state. Discovery
    runs only when explicitly requested; ordinary commands should use
    :meth:`list_repos` to read the cache.

    Attributes:
        store: The :class:`GlobalStateStore` backing the registry.
    """

    def __init__(self, store: GlobalStateStore) -> None:
        """Initialize the registry.

        Args:
            store: The global state store used to read/persist repositories.
        """
        self.store = store

    def discover(self, start_dir: Path | str) -> list[DiscoveredRepo]:
        """Walk ``start_dir`` and return the repositories found.

        Prunes :data:`DEFAULT_PRUNE_DIRS` and any directory names matched by
        ``.gitignore`` files encountered along the way. A directory that
        contains ``.doto/tasks.json`` is reported as a repository; the walk
        still descends into its (non-pruned) children so nested repositories
        are discovered too. Names are de-duplicated with a numeric suffix on
        collision. Gitignore patterns are inherited across repository
        boundaries, so an ancestor directory's ``.gitignore`` can still prune a
        nested repository's subtree.

        This method does not persist anything; use :meth:`rescan` to discover
        and cache in one step.

        Args:
            start_dir: Directory to start the walk from.

        Returns:
            Discovered repositories, ordered by path.
        """
        root = Path(start_dir).resolve()
        found: list[DiscoveredRepo] = []
        used_names: set[str] = set()
        # Map each visited directory to the gitignore patterns in scope.
        gitignore_by_dir: dict[str, list[str]] = {}

        for current_dir, subdirs, _files in os.walk(root):
            current_path = Path(current_dir)

            # Accumulate gitignore patterns from this dir plus ancestors.
            parent = str(current_path.parent)
            inherited = gitignore_by_dir.get(parent, [])
            patterns = inherited + _load_gitignore_patterns(current_path)
            gitignore_by_dir[str(current_path)] = patterns

            # Is this directory itself a doto repository?
            if (current_path / DOTO_MARKER).is_file():
                name = _dedupe_name(current_path.name or "repo", used_names)
                used_names.add(name)
                found.append(DiscoveredRepo(name=name, path=str(current_path)))
                # Keep descending so nested repositories are discovered too.

            # Prune noisy / ignored directories in place.
            subdirs[:] = [
                d
                for d in subdirs
                if d not in DEFAULT_PRUNE_DIRS and not _matches_gitignore(d, patterns)
            ]

        found.sort(key=lambda r: r.path)
        return found

    def list_repos(self) -> list[DiscoveredRepo]:
        """Return the cached repositories from the global state.

        Returns:
            Cached repositories (possibly empty); never triggers discovery.
        """
        state = self.store.load()
        return [
            DiscoveredRepo(name=entry["name"], path=entry["path"])
            for entry in state.repositories
            if entry.get("name") and entry.get("path")
        ]

    def rescan(self, start_dir: Path | str) -> list[DiscoveredRepo]:
        """Discover repositories under ``start_dir`` and cache the result.

        The discovered set replaces the cached registry.

        Args:
            start_dir: Directory to start the walk from.

        Returns:
            The newly discovered and cached repositories.
        """
        repos = self.discover(start_dir)
        state = self.store.load()
        state.repositories = [r.to_dict() for r in repos]
        self.store.save(state)
        return repos

    def add(self, path: Path | str) -> DiscoveredRepo:
        """Add a single repository to the cache.

        Args:
            path: Path to a directory containing ``.doto/tasks.json``.

        Returns:
            The added (or already-present) repository entry.

        Raises:
            ValueError: If ``path`` is not a doto repository.
        """
        repo_path = Path(path).resolve()
        if not (repo_path / DOTO_MARKER).is_file():
            raise ValueError(f"{repo_path} is not a doto repository (missing .doto/tasks.json).")

        state = self.store.load()
        for entry in state.repositories:
            if entry.get("path") == str(repo_path):
                return DiscoveredRepo(name=entry["name"], path=entry["path"])

        used_names = {entry["name"] for entry in state.repositories}
        name = _dedupe_name(repo_path.name or "repo", used_names)
        repo = DiscoveredRepo(name=name, path=str(repo_path))
        state.repositories.append(repo.to_dict())
        self.store.save(state)
        return repo

    def forget(self, name: str) -> bool:
        """Remove a repository from the cache by name.

        Args:
            name: The registry name to remove.

        Returns:
            True if an entry was removed, False if no match was found.
        """
        state = self.store.load()
        before = len(state.repositories)
        state.repositories = [entry for entry in state.repositories if entry.get("name") != name]
        if len(state.repositories) == before:
            return False
        self.store.save(state)
        return True

    def resolve(self, name: str) -> DiscoveredRepo | None:
        """Return the cached repository with the given name, if any.

        Args:
            name: The registry name to look up.

        Returns:
            The matching repository, or None.
        """
        for repo in self.list_repos():
            if repo.name == name:
                return repo
        return None
