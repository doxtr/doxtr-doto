"""Persistent memory for assignee names and tags.

Stores known names in ``.doto/known_names.json`` so they survive across
sessions and can be offered as completions even when no current task uses
them.  The store is case-preserving but deduplicates case-insensitively
(e.g. ``"Alice"`` and ``"alice"`` are considered the same; the latest
spelling wins).

The store uses best-effort persistence with no locking. Concurrent
processes may lose a name on rare write collisions; the name will be
re-learned on next use. This is acceptable for completion history.

Public API
----------
* :func:`add_assignee` / :func:`add_tag` — remember a single name.
* :func:`remember_task_names` — best-effort persist an assignee and tags.
* :func:`get_assignees` / :func:`get_tags` — sorted list of known names.
* :func:`get_known_names_path` — resolve the JSON path (next to
  ``tasks.json``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def get_known_names_path() -> Path | None:
    """Resolve the path to ``known_names.json`` (next to ``tasks.json``).

    Returns ``None`` when the config cannot be loaded or the ``.doto``
    directory cannot be determined.
    """
    from doxtr_doto.cli.config import load_config

    try:
        config = load_config()
        json_path = config.get_json_path()
        return json_path.parent / "known_names.json"
    except Exception:
        return None


def _load(path: Path) -> dict[str, list[str]]:
    """Read and parse the known-names file.

    Returns a dict with ``"assignees"`` and ``"tags"`` keys (both lists of
    strings).  Returns empty lists when the file is missing, unreadable, or
    contains invalid JSON.
    """
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {"assignees": [], "tags": []}
        assignees = raw.get("assignees", [])
        tags = raw.get("tags", [])
        if not isinstance(assignees, list) or not isinstance(tags, list):
            return {"assignees": [], "tags": []}
        return {
            "assignees": [a for a in assignees if isinstance(a, str)],
            "tags": [t for t in tags if isinstance(t, str)],
        }
    except (OSError, json.JSONDecodeError, ValueError):
        return {"assignees": [], "tags": []}


def _save(path: Path, data: dict[str, list[str]]) -> None:
    """Write the known-names file atomically, creating parent dirs as needed.

    Writes to a temporary file and renames it into place so a crash or
    disk-full condition cannot corrupt the existing store.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    try:
        tmp.write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise


def _merge(existing: list[str], name: str) -> list[str]:
    """Add *name* to *existing*, deduplicating case-insensitively.

    The latest spelling wins: if ``"Alice"`` is already stored and ``"alice"``
    is added, the list will contain ``"alice"`` (the newest form).  The
    returned list is sorted case-insensitively.
    """
    by_lower: dict[str, str] = {n.lower(): n for n in existing}
    by_lower[name.lower()] = name
    return sorted(by_lower.values(), key=lambda s: s.lower())


def add_assignee(name: str, *, path: Path | None = None) -> None:
    """Remember an assignee name.

    Args:
        name: The assignee name to store.  Empty/whitespace-only strings are
            silently ignored.
        path: Override the known-names file path (used by tests).
    """
    name = name.strip()
    if not name:
        return
    resolved = path or get_known_names_path()
    if resolved is None:
        return
    data = _load(resolved)
    data["assignees"] = _merge(data["assignees"], name)
    _save(resolved, data)


def add_tag(name: str, *, path: Path | None = None) -> None:
    """Remember a tag name.

    Args:
        name: The tag to store.  Empty/whitespace-only strings are silently
            ignored.
        path: Override the known-names file path (used by tests).
    """
    name = name.strip()
    if not name:
        return
    resolved = path or get_known_names_path()
    if resolved is None:
        return
    data = _load(resolved)
    data["tags"] = _merge(data["tags"], name)
    _save(resolved, data)


def remember_task_names(
    assignee: str | None, tags: list[str] | None = None, *, path: Path | None = None
) -> None:
    """Best-effort persist of task names to the memory store.

    Catches all exceptions so callers are never blocked by a persistence
    failure.  This is the single place the "failures never block" contract
    is enforced for the add/update/TUI call sites.

    Args:
        assignee: The assignee name to remember, or None.
        tags: The tags to remember (empty/None is a no-op).
        path: Override the known-names file path (used by tests).
    """
    try:
        if assignee:
            add_assignee(assignee, path=path)
        for tag in tags or []:
            add_tag(tag, path=path)
    except Exception:
        pass


def get_assignees(*, path: Path | None = None) -> list[str]:
    """Return all known assignee names, sorted case-insensitively.

    Args:
        path: Override the known-names file path (used by tests).
    """
    resolved = path or get_known_names_path()
    if resolved is None:
        return []
    return _load(resolved).get("assignees", [])


def get_tags(*, path: Path | None = None) -> list[str]:
    """Return all known tags, sorted case-insensitively.

    Args:
        path: Override the known-names file path (used by tests).
    """
    resolved = path or get_known_names_path()
    if resolved is None:
        return []
    return _load(resolved).get("tags", [])
