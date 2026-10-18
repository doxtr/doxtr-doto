"""Tests for the ``sync_conflict`` persistent flag and its list filter.

A two-way calendar merge that produces git-style conflict markers in a task
body sets a persistent ``sync_conflict`` flag so the task can be found later
(``doto list --conflicts``) without re-running a sync. These tests pin the
store-level filter behavior that backs that feature.
"""

from __future__ import annotations

from pathlib import Path

from doxtr_doto.sync.json_store import JsonTaskStore


def _store(tmp_path: Path) -> JsonTaskStore:
    store = JsonTaskStore(tmp_path / ".doto" / "tasks.json")
    store.add_task("DOTO-001", {"title": "clean", "status": "open"})
    store.add_task("DOTO-002", {"title": "conflicted", "status": "open", "sync_conflict": True})
    store.add_task("DOTO-003", {"title": "resolved", "status": "open", "sync_conflict": False})
    return store


def test_filter_conflicts_only(tmp_path: Path):
    store = _store(tmp_path)
    ids = {t["id"] for t in store.filter_tasks(sync_conflict=True)}
    assert ids == {"DOTO-002"}


def test_filter_non_conflicts(tmp_path: Path):
    store = _store(tmp_path)
    ids = {t["id"] for t in store.filter_tasks(sync_conflict=False)}
    # Both the never-flagged and the explicitly-resolved tasks count as clean.
    assert ids == {"DOTO-001", "DOTO-003"}


def test_filter_default_returns_all(tmp_path: Path):
    store = _store(tmp_path)
    ids = {t["id"] for t in store.filter_tasks()}
    assert ids == {"DOTO-001", "DOTO-002", "DOTO-003"}
