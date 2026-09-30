"""Tests for CLI delete command."""

from __future__ import annotations

import json
import pytest
from pathlib import Path
from click.testing import CliRunner


@pytest.fixture
def cli_runner():
    """Create a CLI runner."""
    return CliRunner()


@pytest.fixture
def delete_project(tmp_path):
    """Create a project with tasks for deletion testing."""
    # Create project structure
    doto_dir = tmp_path / ".doto"
    doto_dir.mkdir()
    
    # Create config
    config_file = tmp_path / ".doto.toml"
    config_file.write_text('''
[doto]
json_file = ".doto/tasks.json"
id_prefix = "TEST"
''')
    
    # Create tasks.json with test data
    json_file = doto_dir / "tasks.json"
    json_file.write_text(json.dumps({
        "version": 3,
        "updated": "2026-07-26T10:00:00",
        "tasks": {
            "TASK-001": {
                "title": "Active task",
                "status": "open",
                "priority": "high",
                "assignee": "alice",
                "tags": ["feature"],
                "archived": False,
            },
            "TASK-002": {
                "title": "Done task",
                "status": "done",
                "priority": "medium",
                "assignee": "bob",
                "tags": ["bug"],
                "archived": False,
            },
            "TASK-003": {
                "title": "Archived task",
                "status": "done",
                "priority": "low",
                "assignee": "alice",
                "tags": [],
                "archived": True,
                "archived_on": "2026-07-01T00:00:00",
            },
            "TASK-004": {
                "title": "Series task",
                "status": "open",
                "priority": "medium",
                "assignee": None,
                "tags": [],
                "archived": False,
            },
        },
        "series": {
            "SER-001": {
                "title_template": "Weekly review",
                "pattern": {},
                "start_date": "2026-01-01",
                "end_date": "2026-12-31",
                "task_ids": ["TASK-004"],
                "task_defaults": {},
                "created": "2026-01-01T00:00:00",
                "updated": "2026-01-01T00:00:00",
            }
        }
    }))
    
    return tmp_path


class TestDotoDelete:
    """Test the doto delete command."""

    def test_delete_single_task_with_force(self, cli_runner, delete_project):
        """Test deleting a single task with --force flag."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(delete_project),
            "delete", "TASK-001", "--force"
        ])

        assert result.exit_code == 0
        assert "Deleted task TASK-001" in result.output

        # Verify task was deleted
        json_file = delete_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert "TASK-001" not in data["tasks"]
        assert len(data["tasks"]) == 3

    def test_delete_multiple_tasks(self, cli_runner, delete_project):
        """Test deleting multiple tasks at once."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(delete_project),
            "delete", "TASK-001", "TASK-002", "--force"
        ])

        assert result.exit_code == 0
        assert "Deleted task TASK-001" in result.output
        assert "Deleted task TASK-002" in result.output

        json_file = delete_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert "TASK-001" not in data["tasks"]
        assert "TASK-002" not in data["tasks"]
        assert len(data["tasks"]) == 2

    def test_delete_nonexistent_task(self, cli_runner, delete_project):
        """Test deleting a task that doesn't exist."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(delete_project),
            "delete", "NONEXISTENT", "--force"
        ])

        assert result.exit_code == 0
        assert "not found" in result.output

    def test_delete_requires_confirmation(self, cli_runner, delete_project):
        """Test that delete requires confirmation without --force."""
        from doxtr_doto.cli.main import cli

        # Decline confirmation
        result = cli_runner.invoke(cli, [
            "--config", str(delete_project),
            "delete", "TASK-001"
        ], input="n\n")

        assert result.exit_code == 0
        assert "Aborted" in result.output

        # Verify task was NOT deleted
        json_file = delete_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert "TASK-001" in data["tasks"]

    def test_delete_with_confirmation(self, cli_runner, delete_project):
        """Test delete with user confirmation."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(delete_project),
            "delete", "TASK-001"
        ], input="y\n")

        assert result.exit_code == 0

        json_file = delete_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert "TASK-001" not in data["tasks"]

    def test_delete_dry_run(self, cli_runner, delete_project):
        """Test delete with --dry-run flag."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(delete_project),
            "delete", "TASK-001", "--dry-run"
        ])

        assert result.exit_code == 0
        assert "Dry run" in result.output
        assert "TASK-001" in result.output
        assert "would be deleted" in result.output

        # Verify task was NOT deleted
        json_file = delete_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert "TASK-001" in data["tasks"]

    def test_delete_json_output(self, cli_runner, delete_project):
        """Test delete with JSON output."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(delete_project),
            "delete", "TASK-001", "--force", "--json"
        ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["deleted"] == ["TASK-001"]
        assert data["not_found"] == []

    def test_delete_json_output_dry_run(self, cli_runner, delete_project):
        """Test delete with JSON output and dry run."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(delete_project),
            "delete", "TASK-001", "--dry-run", "--json"
        ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["dry_run"] is True
        assert data["would_delete"] == ["TASK-001"]

    def test_delete_no_tasks_specified(self, cli_runner, delete_project):
        """Test delete without specifying any tasks."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(delete_project),
            "delete"
        ])

        assert result.exit_code == 1
        assert "No tasks specified" in result.output

    def test_delete_series_warning(self, cli_runner, delete_project):
        """Test delete shows warning for tasks in a series."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(delete_project),
            "delete", "TASK-004", "--dry-run"
        ])

        assert result.exit_code == 0
        assert "Warning" in result.output
        assert "series" in result.output.lower()
        assert "SER-001" in result.output

    def test_delete_series_warning_json(self, cli_runner, delete_project):
        """Test delete shows series warning in JSON output."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(delete_project),
            "delete", "TASK-004", "--dry-run", "--json"
        ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "series_warnings" in data
        assert len(data["series_warnings"]) == 1
        assert data["series_warnings"][0]["task_id"] == "TASK-004"
        assert data["series_warnings"][0]["series_id"] == "SER-001"


class TestDotoDeleteFilters:
    """Test the doto delete command with filters."""

    def test_delete_filter_status(self, cli_runner, delete_project):
        """Test delete with --filter-status."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(delete_project),
            "delete", "--filter-status", "done", "--all", "--dry-run"
        ])

        assert result.exit_code == 0
        assert "TASK-002" in result.output
        # TASK-001 is open, should not be included
        assert "TASK-001" not in result.output

    def test_delete_filter_priority(self, cli_runner, delete_project):
        """Test delete with --filter-priority."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(delete_project),
            "delete", "--filter-priority", "high", "--all", "--dry-run"
        ])

        assert result.exit_code == 0
        assert "TASK-001" in result.output
        assert "TASK-002" not in result.output

    def test_delete_filter_assignee(self, cli_runner, delete_project):
        """Test delete with --filter-assignee."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(delete_project),
            "delete", "--filter-assignee", "alice", "--all", "--dry-run"
        ])

        assert result.exit_code == 0
        assert "TASK-001" in result.output
        # TASK-003 is archived (by alice), should not appear without --filter-archived
        assert "TASK-003" not in result.output
        assert "TASK-002" not in result.output

    def test_delete_filter_tags(self, cli_runner, delete_project):
        """Test delete with --filter-tags."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(delete_project),
            "delete", "--filter-tags", "bug", "--all", "--dry-run"
        ])

        assert result.exit_code == 0
        assert "TASK-002" in result.output
        assert "TASK-001" not in result.output

    def test_delete_filter_archived(self, cli_runner, delete_project):
        """Test delete with --filter-archived."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(delete_project),
            "delete", "--filter-archived", "--all", "--dry-run"
        ])

        assert result.exit_code == 0
        assert "TASK-003" in result.output
        # Non-archived tasks should not appear
        assert "TASK-001" not in result.output
        assert "TASK-002" not in result.output

    def test_delete_filter_requires_all_flag(self, cli_runner, delete_project):
        """Test that filter-based delete requires --all flag."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(delete_project),
            "delete", "--filter-status", "done"
        ])

        assert result.exit_code == 1
        assert "--all flag is required" in result.output

    def test_delete_filter_with_force(self, cli_runner, delete_project):
        """Test filter-based delete with --force."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(delete_project),
            "delete", "--filter-archived", "--all", "--force"
        ])

        assert result.exit_code == 0
        assert "Deleted task TASK-003" in result.output

        json_file = delete_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert "TASK-003" not in data["tasks"]

    def test_delete_filter_no_match(self, cli_runner, delete_project):
        """Test filter-based delete with no matches."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(delete_project),
            "delete", "--filter-status", "blocked", "--all", "--dry-run"
        ])

        assert result.exit_code == 0
        assert "No tasks matched" in result.output

    def test_delete_combined_filters(self, cli_runner, delete_project):
        """Test delete with multiple filters combined."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(delete_project),
            "delete",
            "--filter-status", "open",
            "--filter-priority", "high",
            "--all", "--dry-run"
        ])

        assert result.exit_code == 0
        # Only TASK-001 matches both open and high priority
        assert "TASK-001" in result.output
        assert "would be deleted" in result.output

    def test_delete_filter_json_output(self, cli_runner, delete_project):
        """Test filter-based delete with JSON output."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(delete_project),
            "delete", "--filter-archived", "--all", "--force", "--json"
        ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["deleted"] == ["TASK-003"]
