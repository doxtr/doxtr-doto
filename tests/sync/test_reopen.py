"""Tests for re-opening done tasks via RST edit propagates to JSON.

Section 12 tests: Ensures that changing status from 'done' to 'open' in RST
propagates correctly to JSON without triggering conflicts.
"""
from __future__ import annotations

import pytest

from doxtr_doto.sync.merge import sync_task, create_snapshot, MergeResult


class TestReopenViaMerge:
    """Tests for reopening tasks through the 3-way merge."""

    def test_reopen_via_rst_updates_json(self):
        """Changing status from 'done' to 'open' in RST is merged into JSON."""
        # Setup: Task was done, snapshot reflects done status
        snapshot = {
            "title": "Finished task",
            "status": "done",
            "priority": "medium",
            "assignee": None,
            "due": None,
            "tags": [],
            "depends_on": [],
            "body": "",
        }
        json_task = {
            "title": "Finished task",
            "status": "done",
            "priority": "medium",
            "assignee": None,
            "due": None,
            "tags": [],
            "depends_on": [],
            "body": "",
            "_sync": {
                "snapshot": snapshot,
                "rst_file": "tasks.rst",
                "rst_line": 10,
            },
        }
        rst_current = {
            "title": "Finished task",
            "status": "open",  # User changed this in RST
            "priority": "medium",
            "assignee": None,
            "due": None,
            "tags": [],
            "depends_on": [],
            "body": "",
        }

        result = sync_task("TASK-001", rst_current, json_task, "tasks.rst", 10)

        assert not result.has_conflicts
        assert result.merged is not None
        assert result.merged["status"] == "open"
        assert result.update_json is True
        # RST doesn't need updating since RST is the source of this change
        assert result.write_rst is False

    def test_reopen_does_not_trigger_conflict_when_only_rst_changed(self):
        """RST-only status change is not a conflict — it should win cleanly."""
        snapshot = {
            "title": "T",
            "status": "done",
            "priority": "medium",
            "assignee": None,
            "due": None,
            "tags": [],
            "depends_on": [],
            "body": "",
        }
        json_task = {
            "title": "T",
            "status": "done",
            "priority": "medium",
            "_sync": {"snapshot": snapshot},
        }
        rst_current = {
            "title": "T",
            "status": "open",
            "priority": "medium",
        }

        result = sync_task("TASK-001", rst_current, json_task, "x.rst", 1)

        assert result.has_conflicts is False
        assert result.merged is not None
        assert result.merged["status"] == "open"

    def test_reopen_with_json_change_causes_conflict(self):
        """If both RST and JSON changed status differently, it's a conflict."""
        snapshot = {
            "title": "Task",
            "status": "done",
            "priority": "medium",
            "assignee": None,
            "due": None,
            "tags": [],
            "depends_on": [],
            "body": "",
        }
        json_task = {
            "title": "Task",
            "status": "in-progress",  # CLI changed to in-progress
            "priority": "medium",
            "_sync": {"snapshot": snapshot, "rst_file": "tasks.rst"},
        }
        rst_current = {
            "title": "Task",
            "status": "open",  # RST changed to open
            "priority": "medium",
        }

        result = sync_task("TASK-001", rst_current, json_task, "tasks.rst", 1)

        # Both changed status to different values = conflict
        assert result.has_conflicts is True
        assert len(result.conflicts) == 1
        assert result.conflicts[0].field == "status"
        assert result.conflicts[0].base == "done"
        assert result.conflicts[0].rst == "open"
        assert result.conflicts[0].json == "in-progress"


class TestReopenStatusTransitions:
    """Tests for various status transition scenarios during reopen."""

    def test_reopen_from_done_to_open(self):
        """Standard reopen: done -> open."""
        snapshot = {"title": "T", "status": "done", "priority": "medium",
                    "assignee": None, "due": None, "tags": [], "depends_on": [], "body": ""}
        json_task = {"title": "T", "status": "done", "priority": "medium",
                     "_sync": {"snapshot": snapshot}}
        rst_current = {"title": "T", "status": "open", "priority": "medium"}

        result = sync_task("TASK-001", rst_current, json_task, "t.rst", 1)

        assert not result.has_conflicts
        assert result.merged["status"] == "open"

    def test_reopen_from_done_to_in_progress(self):
        """Reopen directly to in-progress: done -> in-progress."""
        snapshot = {"title": "T", "status": "done", "priority": "medium",
                    "assignee": None, "due": None, "tags": [], "depends_on": [], "body": ""}
        json_task = {"title": "T", "status": "done", "priority": "medium",
                     "_sync": {"snapshot": snapshot}}
        rst_current = {"title": "T", "status": "in-progress", "priority": "medium"}

        result = sync_task("TASK-001", rst_current, json_task, "t.rst", 1)

        assert not result.has_conflicts
        assert result.merged["status"] == "in-progress"

    def test_reopen_from_done_to_blocked(self):
        """Reopen to blocked state: done -> blocked."""
        snapshot = {"title": "T", "status": "done", "priority": "medium",
                    "assignee": None, "due": None, "tags": [], "depends_on": [], "body": ""}
        json_task = {"title": "T", "status": "done", "priority": "medium",
                     "_sync": {"snapshot": snapshot}}
        rst_current = {"title": "T", "status": "blocked", "priority": "medium"}

        result = sync_task("TASK-001", rst_current, json_task, "t.rst", 1)

        assert not result.has_conflicts
        assert result.merged["status"] == "blocked"


class TestReopenWithOtherFieldChanges:
    """Tests for reopening tasks while other fields also change."""

    def test_reopen_with_priority_change_in_rst(self):
        """Reopen with simultaneous priority change in RST."""
        snapshot = {"title": "T", "status": "done", "priority": "medium",
                    "assignee": None, "due": None, "tags": [], "depends_on": [], "body": ""}
        json_task = {"title": "T", "status": "done", "priority": "medium",
                     "_sync": {"snapshot": snapshot}}
        rst_current = {"title": "T", "status": "open", "priority": "high"}

        result = sync_task("TASK-001", rst_current, json_task, "t.rst", 1)

        assert not result.has_conflicts
        assert result.merged["status"] == "open"
        assert result.merged["priority"] == "high"
        assert result.update_json is True

    def test_reopen_with_json_assignee_change(self):
        """Reopen in RST while JSON has assignee change - both apply."""
        snapshot = {"title": "T", "status": "done", "priority": "medium",
                    "assignee": None, "due": None, "tags": [], "depends_on": [], "body": ""}
        json_task = {"title": "T", "status": "done", "priority": "medium",
                     "assignee": "bob",  # Changed via CLI
                     "_sync": {"snapshot": snapshot}}
        rst_current = {"title": "T", "status": "open", "priority": "medium",
                       "assignee": None}  # RST still has no assignee

        result = sync_task("TASK-001", rst_current, json_task, "t.rst", 1)

        # RST changed status, JSON changed assignee - no conflict
        assert not result.has_conflicts
        assert result.merged["status"] == "open"  # From RST
        assert result.merged["assignee"] == "bob"  # From JSON
        assert result.update_json is True  # Status changed
        assert result.write_rst is True  # Assignee changed

    def test_reopen_with_tags_change_no_conflict(self):
        """Reopen with tags change in JSON - both apply cleanly."""
        snapshot = {"title": "T", "status": "done", "priority": "medium",
                    "assignee": None, "due": None, "tags": ["old"], "depends_on": [], "body": ""}
        json_task = {"title": "T", "status": "done", "priority": "medium",
                     "tags": ["old", "new"],  # Tags added via CLI
                     "_sync": {"snapshot": snapshot}}
        rst_current = {"title": "T", "status": "open", "priority": "medium",
                       "tags": ["old"]}  # RST unchanged

        result = sync_task("TASK-001", rst_current, json_task, "t.rst", 1)

        assert not result.has_conflicts
        assert result.merged["status"] == "open"
        assert sorted(result.merged["tags"]) == ["new", "old"]


class TestReopenSnapshot:
    """Tests for snapshot handling during reopen."""

    def test_reopen_updates_snapshot_flag(self):
        """Reopening sets update_snapshot flag for future merges."""
        snapshot = {"title": "T", "status": "done", "priority": "medium",
                    "assignee": None, "due": None, "tags": [], "depends_on": [], "body": ""}
        json_task = {"title": "T", "status": "done", "priority": "medium",
                     "_sync": {"snapshot": snapshot}}
        rst_current = {"title": "T", "status": "open", "priority": "medium"}

        result = sync_task("TASK-001", rst_current, json_task, "t.rst", 1)

        assert result.update_snapshot is True

    def test_create_snapshot_after_reopen(self):
        """Verify snapshot creation captures the new status."""
        merged_data = {
            "title": "Reopened task",
            "status": "open",
            "priority": "medium",
            "assignee": "alice",
            "due": "2025-12-31",
            "tags": ["urgent"],
            "depends_on": ["TASK-000"],
            "body": "Task body",
        }

        snapshot = create_snapshot(merged_data)

        assert snapshot["status"] == "open"
        assert snapshot["title"] == "Reopened task"
        assert snapshot["assignee"] == "alice"
        assert snapshot["tags"] == ["urgent"]


class TestReopenEdgeCases:
    """Edge cases for reopening tasks."""

    def test_reopen_task_without_prior_snapshot(self):
        """Reopening task without prior snapshot - RST is authoritative."""
        json_task = {
            "title": "Task without snapshot",
            "status": "done",
            "priority": "medium",
            "_sync": {},  # No snapshot
        }
        rst_current = {
            "title": "Task without snapshot",
            "status": "open",
            "priority": "medium",
        }

        result = sync_task("TASK-001", rst_current, json_task, "t.rst", 1)

        # Without snapshot, RST is authoritative
        assert not result.has_conflicts
        assert result.merged["status"] == "open"
        assert result.update_json is True
        assert result.update_snapshot is True

    def test_reopen_same_status_no_change(self):
        """If status is already open in both, no change needed."""
        snapshot = {"title": "T", "status": "open", "priority": "medium",
                    "assignee": None, "due": None, "tags": [], "depends_on": [], "body": ""}
        json_task = {"title": "T", "status": "open", "priority": "medium",
                     "assignee": None, "due": None, "tags": [], "depends_on": [], "body": "",
                     "_sync": {"snapshot": snapshot}}
        rst_current = {"title": "T", "status": "open", "priority": "medium",
                       "assignee": None, "due": None, "tags": [], "depends_on": [], "body": ""}

        result = sync_task("TASK-001", rst_current, json_task, "t.rst", 1)

        assert not result.has_conflicts
        assert result.merged["status"] == "open"
        # No changes needed since everything matches
        assert result.has_changes is False
