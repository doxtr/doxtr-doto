"""Tests for the doto resolve command."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from doxtr_doto.cli.main import cli


@pytest.fixture
def runner():
    """Create a CLI runner."""
    return CliRunner()


@pytest.fixture
def store_with_conflicts(tmp_path):
    """A JSON store pre-loaded with one conflict entry."""
    store_dir = tmp_path / ".doto"
    store_dir.mkdir()
    store_file = store_dir / "tasks.json"
    data = {
        "version": 2,
        "tasks": {
            "TASK-001": {
                "title": "Conflict task",
                "status": "open",
                "priority": "medium",
                "_sync": {
                    "snapshot": {
                        "title": "Base title",
                        "status": "open",
                        "priority": "medium",
                    },
                    "rst_file": "tasks.rst",
                    "rst_line": 5,
                },
            }
        },
        "_conflicts": [
            {
                "task_id": "TASK-001",
                "field": "title",
                "base": "Base title",
                "rst": "RST title",
                "json": "JSON title",
                "rst_file": "tasks.rst",
            }
        ],
    }
    store_file.write_text(json.dumps(data))
    return store_file


class TestResolveList:
    """Tests for doto resolve --list."""

    def test_resolve_list_shows_conflicts(self, runner, store_with_conflicts, tmp_path):
        """doto resolve --list prints the conflict entry."""
        result = runner.invoke(
            cli, ["--json", str(store_with_conflicts), "resolve", "--list"]
        )
        assert result.exit_code == 0
        assert "TASK-001" in result.output

    def test_resolve_no_conflicts_prints_message(self, runner, tmp_path):
        """doto resolve --list with no conflicts prints 'No conflicts found.'"""
        store_file = tmp_path / ".doto" / "tasks.json"
        store_file.parent.mkdir()
        store_file.write_text(json.dumps({"version": 2, "tasks": {}}))

        result = runner.invoke(cli, ["--json", str(store_file), "resolve", "--list"])
        assert result.exit_code == 0
        assert "No conflicts" in result.output


class TestResolveUseRst:
    """Tests for doto resolve --use-rst."""

    def test_resolve_use_rst_applies_value(self, runner, store_with_conflicts, tmp_path):
        """doto resolve TASK-001 --use-rst sets title to RST value."""
        result = runner.invoke(
            cli,
            ["--json", str(store_with_conflicts), "resolve", "TASK-001", "--use-rst"],
        )
        assert result.exit_code == 0

        data = json.loads(store_with_conflicts.read_text())
        assert data["tasks"]["TASK-001"]["title"] == "RST title"

    def test_resolve_clears_conflict_after_resolution(self, runner, store_with_conflicts):
        """After resolving, the conflict entry is removed from _conflicts."""
        runner.invoke(
            cli,
            ["--json", str(store_with_conflicts), "resolve", "TASK-001", "--use-rst"],
        )
        data = json.loads(store_with_conflicts.read_text())
        remaining = [
            c for c in data.get("_conflicts", []) if c["task_id"] == "TASK-001"
        ]
        assert remaining == []


class TestResolveUseJson:
    """Tests for doto resolve --use-json."""

    def test_resolve_use_json_applies_value(self, runner, store_with_conflicts, tmp_path):
        """doto resolve TASK-001 --use-json sets title to JSON value."""
        result = runner.invoke(
            cli,
            ["--json", str(store_with_conflicts), "resolve", "TASK-001", "--use-json"],
        )
        assert result.exit_code == 0

        data = json.loads(store_with_conflicts.read_text())
        assert data["tasks"]["TASK-001"]["title"] == "JSON title"


class TestResolveErrors:
    """Tests for doto resolve error cases."""

    def test_resolve_unknown_task_errors(self, runner, store_with_conflicts):
        """doto resolve NONEXISTENT --use-rst exits with error."""
        result = runner.invoke(
            cli,
            ["--json", str(store_with_conflicts), "resolve", "NONEXISTENT", "--use-rst"],
        )
        # Should indicate no conflict found for that task
        assert "No conflict" in result.output or "not found" in result.output.lower()

    def test_resolve_both_flags_errors(self, runner, store_with_conflicts):
        """Passing both --use-rst and --use-json exits with a usage error."""
        result = runner.invoke(
            cli,
            [
                "--json",
                str(store_with_conflicts),
                "resolve",
                "TASK-001",
                "--use-rst",
                "--use-json",
            ],
        )
        assert result.exit_code != 0

    def test_resolve_no_method_specified_errors(self, runner, store_with_conflicts):
        """Resolving without specifying a method exits with error."""
        result = runner.invoke(
            cli,
            ["--json", str(store_with_conflicts), "resolve", "TASK-001"],
        )
        assert result.exit_code != 0
        assert "resolution method" in result.output.lower() or "use-rst" in result.output.lower()


class TestResolveMultipleConflicts:
    """Tests for resolving multiple conflicts."""

    @pytest.fixture
    def store_with_multiple_conflicts(self, tmp_path):
        """A JSON store with multiple conflict entries for one task."""
        store_dir = tmp_path / ".doto"
        store_dir.mkdir()
        store_file = store_dir / "tasks.json"
        data = {
            "version": 2,
            "tasks": {
                "TASK-001": {
                    "title": "Task title",
                    "status": "open",
                    "priority": "medium",
                    "_sync": {
                        "snapshot": {
                            "title": "Base title",
                            "status": "open",
                            "priority": "low",
                        },
                        "rst_file": "tasks.rst",
                        "rst_line": 5,
                    },
                }
            },
            "_conflicts": [
                {
                    "task_id": "TASK-001",
                    "field": "title",
                    "base": "Base title",
                    "rst": "RST title",
                    "json": "JSON title",
                    "rst_file": "tasks.rst",
                },
                {
                    "task_id": "TASK-001",
                    "field": "priority",
                    "base": "low",
                    "rst": "high",
                    "json": "medium",
                    "rst_file": "tasks.rst",
                },
            ],
        }
        store_file.write_text(json.dumps(data))
        return store_file

    def test_resolve_specific_field(self, runner, store_with_multiple_conflicts):
        """doto resolve TASK-001 --field title --use-rst resolves only that field."""
        result = runner.invoke(
            cli,
            [
                "--json",
                str(store_with_multiple_conflicts),
                "resolve",
                "TASK-001",
                "--field",
                "title",
                "--use-rst",
            ],
        )
        assert result.exit_code == 0

        data = json.loads(store_with_multiple_conflicts.read_text())
        assert data["tasks"]["TASK-001"]["title"] == "RST title"
        # Priority conflict should still exist
        remaining = [
            c
            for c in data.get("_conflicts", [])
            if c["task_id"] == "TASK-001" and c["field"] == "priority"
        ]
        assert len(remaining) == 1

    def test_resolve_all_fields(self, runner, store_with_multiple_conflicts):
        """doto resolve TASK-001 --use-json resolves all conflicts for the task."""
        result = runner.invoke(
            cli,
            [
                "--json",
                str(store_with_multiple_conflicts),
                "resolve",
                "TASK-001",
                "--use-json",
            ],
        )
        assert result.exit_code == 0

        data = json.loads(store_with_multiple_conflicts.read_text())
        assert data["tasks"]["TASK-001"]["title"] == "JSON title"
        assert data["tasks"]["TASK-001"]["priority"] == "medium"
        # All conflicts should be cleared
        remaining = [
            c for c in data.get("_conflicts", []) if c["task_id"] == "TASK-001"
        ]
        assert remaining == []


class TestResolveSnapshotUpdate:
    """Tests for snapshot updates after resolution."""

    def test_resolve_updates_snapshot(self, runner, store_with_conflicts):
        """After resolving, the snapshot is updated to match the chosen value."""
        runner.invoke(
            cli,
            ["--json", str(store_with_conflicts), "resolve", "TASK-001", "--use-rst"],
        )
        data = json.loads(store_with_conflicts.read_text())
        snapshot = data["tasks"]["TASK-001"]["_sync"]["snapshot"]
        assert snapshot["title"] == "RST title"
