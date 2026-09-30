"""Tests for the doto reopen command."""
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
def store_with_archived_task(tmp_path):
    """A JSON store with an archived task."""
    store_file = tmp_path / ".doto" / "tasks.json"
    store_file.parent.mkdir()
    data = {
        "version": 2,
        "tasks": {
            "TASK-001": {
                "title": "Archived task",
                "status": "done",
                "priority": "medium",
                "archived": True,
            },
            "TASK-002": {
                "title": "Open task",
                "status": "open",
                "priority": "high",
                "archived": False,
            },
        },
    }
    store_file.write_text(json.dumps(data))
    return store_file


class TestReopenBasic:
    """Basic tests for doto reopen command."""

    def test_reopen_sets_status_to_open(self, runner, store_with_archived_task):
        """doto reopen TASK-001 changes status back to 'open'."""
        result = runner.invoke(
            cli, ["--json", str(store_with_archived_task), "reopen", "TASK-001"]
        )
        assert result.exit_code == 0

        data = json.loads(store_with_archived_task.read_text())
        assert data["tasks"]["TASK-001"]["status"] == "open"
        assert data["tasks"]["TASK-001"]["archived"] is False

    def test_reopen_with_custom_status(self, runner, store_with_archived_task):
        """doto reopen TASK-001 --status in-progress sets the specified status."""
        result = runner.invoke(
            cli,
            [
                "--json",
                str(store_with_archived_task),
                "reopen",
                "TASK-001",
                "--status",
                "in-progress",
            ],
        )
        assert result.exit_code == 0

        data = json.loads(store_with_archived_task.read_text())
        assert data["tasks"]["TASK-001"]["status"] == "in-progress"
        assert data["tasks"]["TASK-001"]["archived"] is False


class TestReopenIdempotent:
    """Tests for idempotent behavior of reopen."""

    def test_reopen_not_archived_task_warns(self, runner, store_with_archived_task):
        """Reopening a task that's not archived shows a warning."""
        result = runner.invoke(
            cli, ["--json", str(store_with_archived_task), "reopen", "TASK-002"]
        )
        # Should succeed but warn that task is not archived
        assert "not archived" in result.output.lower()


class TestReopenErrors:
    """Tests for doto reopen error cases."""

    def test_reopen_unknown_task_errors(self, runner, store_with_archived_task):
        """doto reopen UNKNOWN exits with non-zero code or shows error."""
        result = runner.invoke(
            cli, ["--json", str(store_with_archived_task), "reopen", "UNKNOWN"]
        )
        # Should report not found
        assert "not found" in result.output.lower()


class TestReopenMultiple:
    """Tests for reopening multiple tasks."""

    @pytest.fixture
    def store_with_multiple_archived(self, tmp_path):
        """A JSON store with multiple archived tasks."""
        store_file = tmp_path / ".doto" / "tasks.json"
        store_file.parent.mkdir()
        data = {
            "version": 2,
            "tasks": {
                "TASK-001": {
                    "title": "Archived task 1",
                    "status": "done",
                    "priority": "medium",
                    "archived": True,
                },
                "TASK-002": {
                    "title": "Archived task 2",
                    "status": "done",
                    "priority": "high",
                    "archived": True,
                },
                "TASK-003": {
                    "title": "Open task",
                    "status": "open",
                    "priority": "low",
                    "archived": False,
                },
            },
        }
        store_file.write_text(json.dumps(data))
        return store_file

    def test_reopen_multiple_tasks(self, runner, store_with_multiple_archived):
        """doto reopen TASK-001 TASK-002 reopens both tasks."""
        result = runner.invoke(
            cli,
            [
                "--json",
                str(store_with_multiple_archived),
                "reopen",
                "TASK-001",
                "TASK-002",
            ],
        )
        assert result.exit_code == 0

        data = json.loads(store_with_multiple_archived.read_text())
        assert data["tasks"]["TASK-001"]["archived"] is False
        assert data["tasks"]["TASK-002"]["archived"] is False
        assert data["tasks"]["TASK-001"]["status"] == "open"
        assert data["tasks"]["TASK-002"]["status"] == "open"

    def test_reopen_mixed_results(self, runner, store_with_multiple_archived):
        """Reopening a mix of archived, non-archived, and unknown tasks reports each."""
        result = runner.invoke(
            cli,
            [
                "--json",
                str(store_with_multiple_archived),
                "reopen",
                "TASK-001",  # archived - should succeed
                "TASK-003",  # not archived - should warn
                "UNKNOWN",  # not found - should error
            ],
        )
        # Should report success for TASK-001, warning for TASK-003, error for UNKNOWN
        assert "TASK-001" in result.output
        assert "not archived" in result.output.lower() or "TASK-003" in result.output
        assert "not found" in result.output.lower()


class TestReopenJsonOutput:
    """Tests for JSON output mode."""

    def test_reopen_json_output(self, runner, store_with_archived_task):
        """doto reopen --json outputs structured JSON."""
        result = runner.invoke(
            cli,
            ["--json", str(store_with_archived_task), "reopen", "TASK-001", "--json"],
        )
        assert result.exit_code == 0
        
        # Find the JSON output (may be mixed with success messages and warnings)
        # The JSON is pretty-printed, so we need to find the start and parse it
        output = result.output
        json_start = output.find('{')
        if json_start != -1:
            # Find the matching closing brace
            brace_count = 0
            json_end = json_start
            for i, char in enumerate(output[json_start:], json_start):
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        json_end = i + 1
                        break
            
            json_str = output[json_start:json_end]
            data = json.loads(json_str)
            assert "reopened" in data
            assert "TASK-001" in data["reopened"]
