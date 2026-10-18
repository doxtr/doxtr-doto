"""Tests for the calendar-sync conflict resolver.

The resolver turns a task's persisted ``_sync.conflict`` stash (the per-field
base/local/remote/both candidates recorded by a two-way merge) into the field
updates that apply a keep-local / keep-remote / keep-both choice, clearing the
``sync_conflict`` flag when every conflicted field is resolved.
"""

from __future__ import annotations

import pytest

from doxtr_doto.calsync.resolve import (
    ResolutionChoice,
    conflict_fields,
    conflict_preview,
    get_conflict,
    resolve_conflict,
)


def _task() -> dict:
    return {
        "id": "T1",
        "title": "Local title",
        "body": "<<<<<<< local\nLOCAL\n=======\nREMOTE\n>>>>>>> remote",
        "sync_conflict": True,
        "_sync": {
            "rst_file": None,
            "snapshot": None,
            "conflict": {
                "detected": "2026-01-01T00:00:00",
                "fields": [
                    {
                        "field": "body",
                        "base": "l1\nBASE\nl3",
                        "local": "l1\nLOCAL\nl3",
                        "remote": "l1\nREMOTE\nl3",
                        "both": "<<<<<<< local\nLOCAL\n=======\nREMOTE\n>>>>>>> remote",
                    },
                    {
                        "field": "title",
                        "base": "A",
                        "local": "Local title",
                        "remote": "Remote title",
                        "both": "Local title / Remote title",
                    },
                ],
            },
        },
    }


class TestInspection:
    def test_get_conflict_present(self):
        assert get_conflict(_task()) is not None

    def test_get_conflict_absent(self):
        assert get_conflict({"id": "X"}) is None
        assert get_conflict({"id": "X", "_sync": {"conflict": None}}) is None

    def test_conflict_fields_lists_both(self):
        names = [r["field"] for r in conflict_fields(_task())]
        assert names == ["body", "title"]


class TestResolveAll:
    def test_keep_local(self):
        updates = resolve_conflict(_task(), ResolutionChoice.LOCAL)
        assert updates["body"] == "l1\nLOCAL\nl3"
        assert updates["title"] == "Local title"
        assert updates["sync_conflict"] is False
        assert updates["_sync"] == {"conflict": None}

    def test_keep_remote(self):
        updates = resolve_conflict(_task(), ResolutionChoice.REMOTE)
        assert updates["body"] == "l1\nREMOTE\nl3"
        assert updates["title"] == "Remote title"
        assert updates["sync_conflict"] is False

    def test_keep_both(self):
        updates = resolve_conflict(_task(), ResolutionChoice.BOTH)
        assert "<<<<<<<" in updates["body"] and ">>>>>>>" in updates["body"]
        assert updates["title"] == "Local title / Remote title"
        assert updates["sync_conflict"] is False


class TestResolveOneField:
    def test_single_field_keeps_others_flagged(self):
        updates = resolve_conflict(_task(), ResolutionChoice.REMOTE, field="body")
        assert updates["body"] == "l1\nREMOTE\nl3"
        # Title still unresolved -> flag stays, stash keeps the title record.
        assert updates["sync_conflict"] is True
        remaining = updates["_sync"]["conflict"]["fields"]
        assert [r["field"] for r in remaining] == ["title"]

    def test_unknown_field_raises(self):
        with pytest.raises(ValueError):
            resolve_conflict(_task(), ResolutionChoice.LOCAL, field="assignee")


class TestErrors:
    def test_no_conflict_raises(self):
        with pytest.raises(ValueError):
            resolve_conflict({"id": "X"}, ResolutionChoice.LOCAL)


class TestMarkerFallback:
    """A flagged task with body markers but no stash is still resolvable.

    Regression for tasks merged before the structured ``_sync.conflict`` stash
    existed: ``conflict_fields`` reconstructs the body conflict from the
    git-style markers so ``doto calsync resolve`` / the TUI still work.
    """

    def _legacy_task(self) -> dict:
        return {
            "id": "T9",
            "sync_conflict": True,
            # No ``_sync.conflict`` stash -- only markers in the body.
            "_sync": {"rst_file": None, "snapshot": None},
            "body": (
                "shared top\n\n"
                "<<<<<<< local (doto)\n"
                "LOCAL side\n"
                "=======\n"
                "REMOTE side\n"
                ">>>>>>> remote (calendar)\n\n"
                "shared bottom"
            ),
        }

    def test_reconstructs_body_conflict(self):
        recs = conflict_fields(self._legacy_task())
        assert [r["field"] for r in recs] == ["body"]
        rec = recs[0]
        assert "LOCAL side" in rec["local"] and "REMOTE side" not in rec["local"]
        assert "REMOTE side" in rec["remote"] and "LOCAL side" not in rec["remote"]
        # Shared context is present on both sides.
        assert "shared top" in rec["local"] and "shared bottom" in rec["remote"]

    def test_resolve_local_from_markers(self):
        updates = resolve_conflict(self._legacy_task(), ResolutionChoice.LOCAL)
        assert "LOCAL side" in updates["body"]
        assert "<<<<<<<" not in updates["body"]
        assert updates["sync_conflict"] is False
        assert updates["_sync"] == {"conflict": None}

    def test_resolve_remote_from_markers(self):
        updates = resolve_conflict(self._legacy_task(), ResolutionChoice.REMOTE)
        assert "REMOTE side" in updates["body"]
        assert "LOCAL side" not in updates["body"]

    def test_resolve_both_from_markers_keeps_markers(self):
        updates = resolve_conflict(self._legacy_task(), ResolutionChoice.BOTH)
        assert "<<<<<<<" in updates["body"] and ">>>>>>>" in updates["body"]

    def test_no_markers_no_conflict(self):
        task = {"id": "X", "sync_conflict": True, "body": "plain body"}
        assert conflict_fields(task) == []


class TestConflictPreview:
    def test_focuses_on_differing_region(self):
        rec = {
            "field": "body",
            "local": "same prefix\nLOCAL TEXT\nsame suffix",
            "remote": "same prefix\nREMOTE TEXT\nsame suffix",
        }
        local_prev, remote_prev = conflict_preview(rec)
        # Only the characters that actually differ remain (shared prefix/suffix
        # -- including the common ``TEXT`` and trailing context -- are trimmed).
        assert "LOCAL" in local_prev
        assert "REMOTE" in remote_prev
        assert "same suffix" not in local_prev
        assert "same suffix" not in remote_prev
        # The shared prefix is elided with an ellipsis marker.
        assert local_prev.startswith("\u2026")

    def test_identical_values_returned_as_is(self):
        rec = {"field": "x", "local": "hello", "remote": "hello"}
        assert conflict_preview(rec) == ("hello", "hello")
