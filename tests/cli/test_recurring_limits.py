"""Tests for CLI add command recurring task limits."""

from __future__ import annotations

import json
import pytest
from datetime import date, timedelta
from click.testing import CliRunner


@pytest.fixture
def cli_runner():
    """Create a CLI runner."""
    return CliRunner()


@pytest.fixture
def add_project(tmp_path):
    """Create a project for add command testing."""
    doto_dir = tmp_path / ".doto"
    doto_dir.mkdir()
    
    # Just create the json file, don't rely on .toml config
    json_file = doto_dir / "tasks.json"
    json_file.write_text(json.dumps({
        "version": 3,
        "updated": "2026-07-26T10:00:00",
        "tasks": {},
        "series": {},
    }))
    
    return tmp_path


class TestRecurringTaskLimits:
    """Tests for recurring task occurrence limits."""

    def test_exceeding_max_occurrences_raises_error(self, cli_runner, add_project):
        """Test that exceeding MAX_OCCURRENCES raises an error."""
        from doxtr_doto.cli.main import cli

        # Daily tasks for 3 years would be ~1095 occurrences, well over 500 limit
        today = date.today()
        end_date = (today + timedelta(days=1095)).isoformat()
        
        result = cli_runner.invoke(cli, [
            "--config", str(add_project),
            "add", "Daily standup",
            "--repeat", "every day",
            "--until", end_date
        ])

        assert result.exit_code != 0
        assert "limit" in result.output.lower()
        assert "500" in result.output  # Default limit

    def test_exactly_at_limit_is_accepted(self, cli_runner, add_project, monkeypatch):
        """Test that exactly max_occurrences tasks are accepted."""
        from doxtr_doto.cli.main import cli

        # Set low limit via env var for testing
        monkeypatch.setenv("DOTO_MAX_OCCURRENCES", "10")

        # Calculate end date for exactly 10 daily occurrences
        today = date.today()
        end_date = (today + timedelta(days=9)).isoformat()  # 10 days = 10 occurrences

        result = cli_runner.invoke(cli, [
            "--config", str(add_project),
            "add", "Daily review",
            "--repeat", "every day",
            "--until", end_date
        ])

        assert result.exit_code == 0
        assert "Created series" in result.output

    def test_one_over_limit_raises_error(self, cli_runner, add_project, monkeypatch):
        """Test that one task over limit raises an error."""
        from doxtr_doto.cli.main import cli

        # Set low limit via env var for testing
        monkeypatch.setenv("DOTO_MAX_OCCURRENCES", "5")

        # Calculate end date for 6 daily occurrences (1 over limit)
        today = date.today()
        end_date = (today + timedelta(days=5)).isoformat()  # 6 days = 6 occurrences

        result = cli_runner.invoke(cli, [
            "--config", str(add_project),
            "add", "Daily review",
            "--repeat", "every day",
            "--until", end_date
        ])

        assert result.exit_code != 0
        assert "limit" in result.output.lower()
        assert "5" in result.output  # Configured limit

    def test_dry_run_respects_limit_check(self, cli_runner, add_project, monkeypatch):
        """Test that dry-run also checks the limit."""
        from doxtr_doto.cli.main import cli

        # Set very low limit via env var
        monkeypatch.setenv("DOTO_MAX_OCCURRENCES", "3")

        # Calculate end date for 5 daily occurrences
        today = date.today()
        end_date = (today + timedelta(days=4)).isoformat()

        # Even with dry-run, limit check should happen before showing preview
        result = cli_runner.invoke(cli, [
            "--config", str(add_project),
            "add", "Daily review",
            "--repeat", "every day",
            "--until", end_date,
            "--dry-run"
        ])

        # Should fail with limit error, not show dry-run output
        assert result.exit_code != 0
        assert "limit" in result.output.lower()

    def test_default_limit_is_500(self, cli_runner, add_project):
        """Test that default limit is 500."""
        from doxtr_doto.cli.commands.add import MAX_OCCURRENCES
        assert MAX_OCCURRENCES == 500

    def test_env_var_can_increase_limit(self, cli_runner, add_project, monkeypatch):
        """Test that DOTO_MAX_OCCURRENCES env var can increase the limit."""
        from doxtr_doto.cli.main import cli

        # Set higher limit via env var
        monkeypatch.setenv("DOTO_MAX_OCCURRENCES", "1000")

        # Daily tasks for 2 years = ~730 occurrences, over default but under new limit
        today = date.today()
        end_date = (today + timedelta(days=730)).isoformat()

        result = cli_runner.invoke(cli, [
            "--config", str(add_project),
            "add", "Daily task",
            "--repeat", "every day",
            "--until", end_date,
            "--dry-run"
        ])

        # Should show dry-run output, not limit error
        assert result.exit_code == 0
        assert "Would create series" in result.output

    def test_env_var_can_set_low_limit(self, cli_runner, add_project, monkeypatch):
        """Test that DOTO_MAX_OCCURRENCES env var sets the limit."""
        from doxtr_doto.cli.main import cli

        monkeypatch.setenv("DOTO_MAX_OCCURRENCES", "3")

        # Calculate end date for 5 daily occurrences
        today = date.today()
        end_date = (today + timedelta(days=4)).isoformat()

        result = cli_runner.invoke(cli, [
            "--config", str(add_project),
            "add", "Daily review",
            "--repeat", "every day",
            "--until", end_date
        ])

        assert result.exit_code != 0
        assert "limit" in result.output.lower()
        assert "3" in result.output


class TestRecurringTaskCreation:
    """Additional tests for recurring task creation."""

    def test_recurring_task_within_limit_succeeds(self, cli_runner, add_project):
        """Test that recurring task within limit succeeds."""
        from doxtr_doto.cli.main import cli

        # Daily for 4 days = 4 occurrences, well within limit
        today = date.today()
        end_date = (today + timedelta(days=3)).isoformat()

        result = cli_runner.invoke(cli, [
            "--config", str(add_project),
            "add", "Daily standup",
            "--repeat", "every day",
            "--until", end_date
        ])

        assert result.exit_code == 0
        assert "Created series" in result.output

        # Verify tasks were created
        json_file = add_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert len(data["tasks"]) == 4
        assert len(data["series"]) == 1

    def test_error_message_includes_helpful_info(self, cli_runner, add_project):
        """Test that error message includes helpful information."""
        from doxtr_doto.cli.main import cli

        # Daily tasks for 3 years
        today = date.today()
        end_date = (today + timedelta(days=1095)).isoformat()

        result = cli_runner.invoke(cli, [
            "--config", str(add_project),
            "add", "Daily task",
            "--repeat", "every day",
            "--until", end_date
        ])

        assert result.exit_code != 0
        # Should include the actual count and helpful suggestions
        assert "limit" in result.output.lower()
        assert any(suggestion in result.output.lower() for suggestion in [
            "shorten", "interval", "config", "max_occurrences"
        ])
