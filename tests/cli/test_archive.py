"""Tests for CLI archive command confirmation prompts."""

from __future__ import annotations

import json
import pytest
from click.testing import CliRunner


@pytest.fixture
def cli_runner():
    """Create a CLI runner."""
    return CliRunner()


@pytest.fixture
def archive_project(tmp_path):
    """Create a project with tasks for archive testing."""
    doto_dir = tmp_path / ".doto"
    doto_dir.mkdir()
    
    config_file = tmp_path / ".doto.toml"
    config_file.write_text('''
[doto]
json_file = ".doto/tasks.json"
id_prefix = "TEST"
''')
    
    json_file = doto_dir / "tasks.json"
    json_file.write_text(json.dumps({
        "version": 3,
        "updated": "2026-07-26T10:00:00",
        "tasks": {
            "TASK-001": {
                "title": "First task",
                "status": "open",
                "priority": "high",
                "archived": False,
            },
            "TASK-002": {
                "title": "Second task",
                "status": "done",
                "priority": "medium",
                "archived": False,
            },
            "TASK-003": {
                "title": "Third task",
                "status": "open",
                "priority": "low",
                "archived": False,
            },
            "TASK-004": {
                "title": "Already archived",
                "status": "done",
                "priority": "medium",
                "archived": True,
            },
        },
        "series": {},
    }))
    
    return tmp_path


class TestArchiveConfirmation:
    """Tests for archive command confirmation prompts."""

    def test_single_archive_prompts_for_confirmation(self, cli_runner, archive_project):
        """Test that archiving a single task prompts for confirmation."""
        from doxtr_doto.cli.main import cli

        # Decline confirmation
        result = cli_runner.invoke(cli, [
            "--config", str(archive_project),
            "archive", "TASK-001"
        ], input="n\n")

        assert result.exit_code == 0
        assert "Cancelled" in result.output

        # Verify task was NOT archived
        json_file = archive_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert data["tasks"]["TASK-001"]["archived"] is False

    def test_single_archive_with_confirmation(self, cli_runner, archive_project):
        """Test archiving a single task with user confirmation."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(archive_project),
            "archive", "TASK-001"
        ], input="y\n")

        assert result.exit_code == 0
        assert "Archived task TASK-001" in result.output

        json_file = archive_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert data["tasks"]["TASK-001"]["archived"] is True

    def test_bulk_archive_prompts_with_count(self, cli_runner, archive_project):
        """Test that bulk archive shows task count in confirmation."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(archive_project),
            "archive", "TASK-001", "TASK-002", "TASK-003"
        ], input="n\n")

        assert result.exit_code == 0
        assert "3 tasks" in result.output
        assert "Cancelled" in result.output

    def test_bulk_archive_with_confirmation(self, cli_runner, archive_project):
        """Test bulk archive with user confirmation."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(archive_project),
            "archive", "TASK-001", "TASK-002"
        ], input="y\n")

        assert result.exit_code == 0
        assert "Archived task TASK-001" in result.output
        assert "Archived task TASK-002" in result.output

        json_file = archive_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert data["tasks"]["TASK-001"]["archived"] is True
        assert data["tasks"]["TASK-002"]["archived"] is True

    def test_yes_flag_skips_confirmation(self, cli_runner, archive_project):
        """Test that --yes flag skips confirmation prompt."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(archive_project),
            "archive", "TASK-001", "--yes"
        ])

        assert result.exit_code == 0
        assert "Archived task TASK-001" in result.output

        json_file = archive_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert data["tasks"]["TASK-001"]["archived"] is True

    def test_y_flag_skips_confirmation(self, cli_runner, archive_project):
        """Test that -y flag skips confirmation prompt."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(archive_project),
            "archive", "TASK-001", "-y"
        ])

        assert result.exit_code == 0
        assert "Archived task TASK-001" in result.output

    def test_bulk_archive_with_yes_flag(self, cli_runner, archive_project):
        """Test bulk archive with --yes flag."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(archive_project),
            "archive", "TASK-001", "TASK-002", "TASK-003", "--yes"
        ])

        assert result.exit_code == 0

        json_file = archive_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert data["tasks"]["TASK-001"]["archived"] is True
        assert data["tasks"]["TASK-002"]["archived"] is True
        assert data["tasks"]["TASK-003"]["archived"] is True

    def test_json_output_skips_confirmation(self, cli_runner, archive_project):
        """Test that --json flag skips confirmation prompt."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(archive_project),
            "archive", "TASK-001", "--json"
        ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["archived"] == ["TASK-001"]

    def test_archive_nonexistent_task(self, cli_runner, archive_project):
        """Test archiving a task that doesn't exist."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(archive_project),
            "archive", "NONEXISTENT", "--yes"
        ])

        assert result.exit_code == 0
        assert "not found" in result.output

    def test_archive_already_archived_task(self, cli_runner, archive_project):
        """Test archiving an already archived task."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(archive_project),
            "archive", "TASK-004", "--yes"
        ])

        assert result.exit_code == 0
        assert "already archived" in result.output
