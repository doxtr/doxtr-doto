"""Tests for CLI stats command - task statistics."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from click.testing import CliRunner

from doxtr_doto.cli.main import cli


@pytest.fixture
def runner():
    """CLI test runner."""
    return CliRunner()


@pytest.fixture
def tasks_with_variety(tmp_path: Path, monkeypatch) -> Path:
    """Create a tasks.json with varied tasks for statistics."""
    doto_dir = tmp_path / ".doto"
    doto_dir.mkdir()

    today = date.today()
    yesterday = today - timedelta(days=1)
    next_week = today + timedelta(days=5)

    tasks_data = {
        "version": 2,
        "tasks": {
            "TASK-001": {
                "title": "Open task",
                "status": "open",
                "priority": "high",
                "assignee": "alice",
                "tags": ["bug"],
                "due": None,
                "archived": False,
            },
            "TASK-002": {
                "title": "In progress task",
                "status": "in-progress",
                "priority": "medium",
                "assignee": "bob",
                "tags": ["feature"],
                "due": next_week.isoformat(),
                "archived": False,
            },
            "TASK-003": {
                "title": "Done task",
                "status": "done",
                "priority": "low",
                "assignee": "alice",
                "tags": ["bug", "feature"],
                "due": None,
                "archived": False,
            },
            "TASK-004": {
                "title": "Overdue task",
                "status": "open",
                "priority": "critical",
                "assignee": None,
                "tags": [],
                "due": yesterday.isoformat(),
                "archived": False,
            },
            "TASK-005": {
                "title": "Archived task",
                "status": "done",
                "priority": "medium",
                "assignee": "charlie",
                "tags": ["cleanup"],
                "due": None,
                "archived": True,
            },
        },
    }

    json_path = doto_dir / "tasks.json"
    json_path.write_text(json.dumps(tasks_data, indent=2))

    # Change to this directory so CLI finds the store
    monkeypatch.chdir(tmp_path)

    return tmp_path


class TestStatsCommand:
    """Tests for doto stats command."""

    def test_stats_shows_total_count(self, runner: CliRunner, tasks_with_variety: Path):
        """Stats shows total task count."""
        result = runner.invoke(cli, ["stats"])

        assert result.exit_code == 0
        assert "Total tasks:" in result.output
        # Should show 4 active tasks (excluding archived by default)
        assert "Active: 4" in result.output

    def test_stats_shows_overdue_count(self, runner: CliRunner, tasks_with_variety: Path):
        """Stats shows overdue task count."""
        result = runner.invoke(cli, ["stats"])

        assert result.exit_code == 0
        assert "Overdue:" in result.output

    def test_stats_shows_due_this_week(self, runner: CliRunner, tasks_with_variety: Path):
        """Stats shows tasks due this week."""
        result = runner.invoke(cli, ["stats"])

        assert result.exit_code == 0
        assert "Due this week:" in result.output

    def test_stats_by_status(self, runner: CliRunner, tasks_with_variety: Path):
        """Stats --by-status shows status breakdown."""
        result = runner.invoke(cli, ["stats", "--by-status"])

        assert result.exit_code == 0
        assert "By Status:" in result.output
        assert "open" in result.output
        assert "in-progress" in result.output
        assert "done" in result.output

    def test_stats_by_priority(self, runner: CliRunner, tasks_with_variety: Path):
        """Stats --by-priority shows priority breakdown."""
        result = runner.invoke(cli, ["stats", "--by-priority"])

        assert result.exit_code == 0
        assert "By Priority:" in result.output
        assert "high" in result.output
        assert "medium" in result.output
        assert "low" in result.output
        assert "critical" in result.output

    def test_stats_by_assignee(self, runner: CliRunner, tasks_with_variety: Path):
        """Stats --by-assignee shows assignee breakdown."""
        result = runner.invoke(cli, ["stats", "--by-assignee"])

        assert result.exit_code == 0
        assert "By Assignee:" in result.output
        assert "alice" in result.output
        assert "bob" in result.output
        assert "unassigned" in result.output

    def test_stats_by_tag(self, runner: CliRunner, tasks_with_variety: Path):
        """Stats --by-tag shows tag breakdown."""
        result = runner.invoke(cli, ["stats", "--by-tag"])

        assert result.exit_code == 0
        assert "By Tag:" in result.output
        assert "bug" in result.output
        assert "feature" in result.output
        assert "untagged" in result.output

    def test_stats_includes_archived(self, runner: CliRunner, tasks_with_variety: Path):
        """Stats --archived includes archived tasks."""
        result = runner.invoke(cli, ["stats", "--archived"])

        assert result.exit_code == 0
        assert "Total tasks: 5" in result.output
        assert "Archived: 1" in result.output

    def test_stats_json_format(self, runner: CliRunner, tasks_with_variety: Path):
        """Stats --format json outputs JSON."""
        result = runner.invoke(cli, ["stats", "--format", "json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "total" in data
        assert "active" in data
        assert "overdue" in data

    def test_stats_json_includes_all_breakdowns(self, runner: CliRunner, tasks_with_variety: Path):
        """Stats JSON includes all breakdown data."""
        result = runner.invoke(cli, ["stats", "--format", "json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "by_status" in data
        assert "by_priority" in data
        assert "by_assignee" in data
        assert "by_tag" in data

    def test_stats_no_tasks(self, runner: CliRunner, tmp_path: Path):
        """Stats with no tasks shows message."""
        doto_dir = tmp_path / ".doto"
        doto_dir.mkdir()
        (doto_dir / "tasks.json").write_text('{"version": 2, "tasks": {}}')

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["stats"])

            assert result.exit_code == 0
            assert "No tasks found" in result.output

    def test_stats_no_tasks_json(self, runner: CliRunner, tmp_path: Path):
        """Stats JSON with no tasks returns empty result."""
        doto_dir = tmp_path / ".doto"
        doto_dir.mkdir()
        (doto_dir / "tasks.json").write_text('{"version": 2, "tasks": {}}')

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["stats", "--format", "json"])

            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["total"] == 0

    def test_stats_multiple_groupings(self, runner: CliRunner, tasks_with_variety: Path):
        """Stats can show multiple groupings at once."""
        result = runner.invoke(cli, ["stats", "--by-status", "--by-priority"])

        assert result.exit_code == 0
        assert "By Status:" in result.output
        assert "By Priority:" in result.output


class TestStatsBreakdownFormatting:
    """Tests for breakdown formatting."""

    def test_breakdown_shows_percentages(self, runner: CliRunner, tasks_with_variety: Path):
        """Breakdowns show percentages."""
        result = runner.invoke(cli, ["stats", "--by-status"])

        assert result.exit_code == 0
        assert "%" in result.output

    def test_breakdown_shows_visual_bars(self, runner: CliRunner, tasks_with_variety: Path):
        """Breakdowns show visual progress bars."""
        result = runner.invoke(cli, ["stats", "--by-status"])

        assert result.exit_code == 0
        # Visual bar characters
        assert "█" in result.output or "░" in result.output


class TestStatsEdgeCases:
    """Tests for edge cases in statistics."""

    def test_stats_with_all_archived(self, runner: CliRunner, tmp_path: Path):
        """Stats handles all tasks being archived."""
        doto_dir = tmp_path / ".doto"
        doto_dir.mkdir()

        tasks_data = {
            "version": 2,
            "tasks": {
                "TASK-001": {
                    "title": "Archived 1",
                    "status": "done",
                    "archived": True,
                },
                "TASK-002": {
                    "title": "Archived 2",
                    "status": "done",
                    "archived": True,
                },
            },
        }
        (doto_dir / "tasks.json").write_text(json.dumps(tasks_data))

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["stats"])

            assert result.exit_code == 0
            # Without --archived, should find no active tasks
            assert "No tasks found" in result.output or "Active: 0" in result.output

    def test_stats_with_missing_fields(self, runner: CliRunner, tmp_path: Path):
        """Stats handles tasks with missing optional fields."""
        doto_dir = tmp_path / ".doto"
        doto_dir.mkdir()

        tasks_data = {
            "version": 2,
            "tasks": {
                "TASK-001": {
                    "title": "Minimal task",
                    # Missing status, priority, assignee, tags, due
                },
            },
        }
        (doto_dir / "tasks.json").write_text(json.dumps(tasks_data))

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["stats"])

            # Should not crash
            assert result.exit_code == 0

    def test_stats_done_tasks_not_overdue(self, runner: CliRunner, tmp_path: Path, monkeypatch):
        """Done tasks are not counted as overdue even with past due date."""
        doto_dir = tmp_path / ".doto"
        doto_dir.mkdir()

        yesterday = (date.today() - timedelta(days=1)).isoformat()
        tasks_data = {
            "version": 2,
            "tasks": {
                "TASK-001": {
                    "title": "Done but past due",
                    "status": "done",
                    "due": yesterday,
                    "archived": False,
                },
            },
        }
        (doto_dir / "tasks.json").write_text(json.dumps(tasks_data))
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(cli, ["stats", "--format", "json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["overdue"] == 0

    def test_stats_archived_not_overdue(self, runner: CliRunner, tmp_path: Path, monkeypatch):
        """Archived tasks are not counted as overdue."""
        doto_dir = tmp_path / ".doto"
        doto_dir.mkdir()

        yesterday = (date.today() - timedelta(days=1)).isoformat()
        tasks_data = {
            "version": 2,
            "tasks": {
                "TASK-001": {
                    "title": "Archived but past due",
                    "status": "open",
                    "due": yesterday,
                    "archived": True,
                },
            },
        }
        (doto_dir / "tasks.json").write_text(json.dumps(tasks_data))
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(cli, ["stats", "--archived", "--format", "json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["overdue"] == 0
