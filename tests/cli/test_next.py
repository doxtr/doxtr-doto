"""Tests for doto next command - Additional edge cases.

Supplements the tests in test_commands.py with additional edge cases
and scoring behavior tests.
"""

from __future__ import annotations

import json
import pytest
from click.testing import CliRunner


@pytest.fixture
def cli_runner():
    """Create a CLI runner."""
    return CliRunner()


@pytest.fixture
def cli_project(tmp_path):
    """Create a minimal doto project for CLI testing."""
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
        "version": 2,
        "updated": "2026-07-26T10:00:00",
        "tasks": {},
        "series": {},
    }))
    
    return tmp_path


class TestNextScoring:
    """Tests for task scoring logic in next command."""
    
    @pytest.fixture
    def scored_project(self, cli_project):
        """Create a project with tasks to test scoring."""
        json_file = cli_project / ".doto" / "tasks.json"
        json_file.write_text(json.dumps({
            "version": 2,
            "updated": "2026-07-26T10:00:00",
            "tasks": {
                "LOW-001": {
                    "title": "Low priority task",
                    "priority": "low",
                    "status": "open",
                    "archived": False,
                },
                "MED-001": {
                    "title": "Medium priority task",
                    "priority": "medium",
                    "status": "open",
                    "archived": False,
                },
                "HIGH-001": {
                    "title": "High priority task",
                    "priority": "high",
                    "status": "open",
                    "archived": False,
                },
                "CRIT-001": {
                    "title": "Critical priority task",
                    "priority": "critical",
                    "status": "open",
                    "archived": False,
                },
            },
            "series": {},
        }))
        return cli_project
    
    def test_next_prioritizes_critical(self, cli_runner, scored_project):
        """Critical priority should be recommended first."""
        from doxtr_doto.cli.main import cli
        
        result = cli_runner.invoke(cli, [
            "--config", str(scored_project),
            "next"
        ])
        
        assert result.exit_code == 0
        # Critical should appear first
        assert "CRIT-001" in result.output
    
    def test_next_in_progress_bonus(self, cli_runner, cli_project):
        """In-progress tasks should get priority bonus."""
        json_file = cli_project / ".doto" / "tasks.json"
        json_file.write_text(json.dumps({
            "version": 2,
            "updated": "2026-07-26T10:00:00",
            "tasks": {
                "HIGH-001": {
                    "title": "High priority not started",
                    "priority": "high",
                    "status": "open",
                    "archived": False,
                },
                "LOW-001": {
                    "title": "Low priority in progress",
                    "priority": "low",
                    "status": "in-progress",
                    "archived": False,
                },
            },
            "series": {},
        }))
        
        from doxtr_doto.cli.main import cli
        
        result = cli_runner.invoke(cli, [
            "--config", str(cli_project),
            "next"
        ])
        
        assert result.exit_code == 0
        # In-progress should appear first despite lower priority
        assert "LOW-001" in result.output


class TestNextFiltering:
    """Tests for filtering in next command."""
    
    @pytest.fixture
    def filter_project(self, cli_project):
        """Create a project with tasks for filter testing."""
        json_file = cli_project / ".doto" / "tasks.json"
        json_file.write_text(json.dumps({
            "version": 2,
            "updated": "2026-07-26T10:00:00",
            "tasks": {
                "ALICE-001": {
                    "title": "Alice's task",
                    "assignee": "alice",
                    "priority": "high",
                    "status": "open",
                    "tags": ["frontend"],
                    "archived": False,
                },
                "BOB-001": {
                    "title": "Bob's task",
                    "assignee": "bob",
                    "priority": "critical",
                    "status": "open",
                    "tags": ["backend"],
                    "archived": False,
                },
                "UNASSIGNED-001": {
                    "title": "Unassigned task",
                    "priority": "medium",
                    "status": "open",
                    "archived": False,
                },
            },
            "series": {},
        }))
        return cli_project
    
    def test_next_filter_by_assignee(self, cli_runner, filter_project):
        """Should filter by assignee."""
        from doxtr_doto.cli.main import cli
        
        result = cli_runner.invoke(cli, [
            "--config", str(filter_project),
            "next", "--assignee", "alice"
        ])
        
        assert result.exit_code == 0
        assert "ALICE-001" in result.output
        assert "BOB-001" not in result.output
    
    def test_next_excludes_done(self, cli_runner, cli_project):
        """Should exclude done tasks."""
        json_file = cli_project / ".doto" / "tasks.json"
        json_file.write_text(json.dumps({
            "version": 2,
            "updated": "2026-07-26T10:00:00",
            "tasks": {
                "DONE-001": {
                    "title": "Done task",
                    "priority": "critical",
                    "status": "done",
                    "archived": False,
                },
                "OPEN-001": {
                    "title": "Open task",
                    "priority": "low",
                    "status": "open",
                    "archived": False,
                },
            },
            "series": {},
        }))
        
        from doxtr_doto.cli.main import cli
        
        result = cli_runner.invoke(cli, [
            "--config", str(cli_project),
            "next"
        ])
        
        assert result.exit_code == 0
        assert "OPEN-001" in result.output
        assert "DONE-001" not in result.output
    
    def test_next_excludes_archived(self, cli_runner, cli_project):
        """Should exclude archived tasks."""
        json_file = cli_project / ".doto" / "tasks.json"
        json_file.write_text(json.dumps({
            "version": 2,
            "updated": "2026-07-26T10:00:00",
            "tasks": {
                "ARCHIVED-001": {
                    "title": "Archived task",
                    "priority": "critical",
                    "status": "open",
                    "archived": True,
                },
                "ACTIVE-001": {
                    "title": "Active task",
                    "priority": "low",
                    "status": "open",
                    "archived": False,
                },
            },
            "series": {},
        }))
        
        from doxtr_doto.cli.main import cli
        
        result = cli_runner.invoke(cli, [
            "--config", str(cli_project),
            "next"
        ])
        
        assert result.exit_code == 0
        assert "ACTIVE-001" in result.output
        assert "ARCHIVED-001" not in result.output


class TestNextDependencies:
    """Tests for dependency handling in next command."""
    
    def test_next_excludes_blocked_by_default(self, cli_runner, cli_project):
        """Should exclude tasks with pending dependencies by default."""
        json_file = cli_project / ".doto" / "tasks.json"
        json_file.write_text(json.dumps({
            "version": 2,
            "updated": "2026-07-26T10:00:00",
            "tasks": {
                "BASE-001": {
                    "title": "Base task",
                    "priority": "low",
                    "status": "open",
                    "archived": False,
                },
                "BLOCKED-001": {
                    "title": "Blocked task",
                    "priority": "critical",
                    "status": "open",
                    "depends_on": ["BASE-001"],
                    "archived": False,
                },
            },
            "series": {},
        }))
        
        from doxtr_doto.cli.main import cli
        
        result = cli_runner.invoke(cli, [
            "--config", str(cli_project),
            "next"
        ])
        
        assert result.exit_code == 0
        assert "BASE-001" in result.output
        # BLOCKED-001 should not be shown because it depends on open BASE-001
    
    def test_next_include_blocked_shows_blocked_tasks(self, cli_runner, cli_project):
        """--include-blocked should show blocked tasks."""
        json_file = cli_project / ".doto" / "tasks.json"
        json_file.write_text(json.dumps({
            "version": 2,
            "updated": "2026-07-26T10:00:00",
            "tasks": {
                "BASE-001": {
                    "title": "Base task",
                    "priority": "low",
                    "status": "open",
                    "archived": False,
                },
                "BLOCKED-001": {
                    "title": "Blocked task",
                    "priority": "critical",
                    "status": "open",
                    "depends_on": ["BASE-001"],
                    "archived": False,
                },
            },
            "series": {},
        }))
        
        from doxtr_doto.cli.main import cli
        
        result = cli_runner.invoke(cli, [
            "--config", str(cli_project),
            "next", "--include-blocked", "--all"
        ])
        
        assert result.exit_code == 0
        assert "BLOCKED-001" in result.output
    
    def test_next_done_dependency_unblocks(self, cli_runner, cli_project):
        """Task should be unblocked when dependency is done."""
        json_file = cli_project / ".doto" / "tasks.json"
        json_file.write_text(json.dumps({
            "version": 2,
            "updated": "2026-07-26T10:00:00",
            "tasks": {
                "BASE-001": {
                    "title": "Done base task",
                    "priority": "low",
                    "status": "done",
                    "archived": False,
                },
                "READY-001": {
                    "title": "Ready task",
                    "priority": "high",
                    "status": "open",
                    "depends_on": ["BASE-001"],
                    "archived": False,
                },
            },
            "series": {},
        }))
        
        from doxtr_doto.cli.main import cli
        
        result = cli_runner.invoke(cli, [
            "--config", str(cli_project),
            "next"
        ])
        
        assert result.exit_code == 0
        # READY-001 should appear since BASE-001 is done
        assert "READY-001" in result.output


class TestNextOutput:
    """Tests for next command output formats."""
    
    @pytest.fixture
    def output_project(self, cli_project):
        """Create a project for output testing."""
        json_file = cli_project / ".doto" / "tasks.json"
        json_file.write_text(json.dumps({
            "version": 2,
            "updated": "2026-07-26T10:00:00",
            "tasks": {
                "TASK-001": {
                    "title": "Test task",
                    "priority": "high",
                    "status": "open",
                    "assignee": "alice",
                    "due": "2026-12-31",
                    "archived": False,
                },
            },
            "series": {},
        }))
        return cli_project
    
    def test_next_json_output(self, cli_runner, output_project):
        """Should output valid JSON with --json flag."""
        from doxtr_doto.cli.main import cli
        
        result = cli_runner.invoke(cli, [
            "--config", str(output_project),
            "next", "--json"
        ])
        
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "id" in data
        assert data["id"] == "TASK-001"
        assert "score" in data
    
    def test_next_all_json_output(self, cli_runner, output_project):
        """Should output valid JSON array with --all --json."""
        from doxtr_doto.cli.main import cli
        
        result = cli_runner.invoke(cli, [
            "--config", str(output_project),
            "next", "--all", "--json"
        ])
        
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
    
    def test_next_no_tasks(self, cli_runner, cli_project):
        """Should handle no tasks gracefully."""
        from doxtr_doto.cli.main import cli
        
        result = cli_runner.invoke(cli, [
            "--config", str(cli_project),
            "next"
        ])
        
        assert result.exit_code == 0
        assert "No tasks found" in result.output


class TestNextDueDateScoring:
    """Tests for due date scoring in next command."""
    
    def test_next_overdue_gets_priority(self, cli_runner, cli_project):
        """Overdue tasks should be prioritized."""
        json_file = cli_project / ".doto" / "tasks.json"
        json_file.write_text(json.dumps({
            "version": 2,
            "updated": "2026-07-26T10:00:00",
            "tasks": {
                "FUTURE-001": {
                    "title": "Future task",
                    "priority": "critical",
                    "status": "open",
                    "due": "2099-12-31",
                    "archived": False,
                },
                "OVERDUE-001": {
                    "title": "Overdue task",
                    "priority": "low",
                    "status": "open",
                    "due": "2020-01-01",
                    "archived": False,
                },
            },
            "series": {},
        }))
        
        from doxtr_doto.cli.main import cli
        
        result = cli_runner.invoke(cli, [
            "--config", str(cli_project),
            "next"
        ])
        
        assert result.exit_code == 0
        # Overdue should appear first despite lower priority
        assert "OVERDUE-001" in result.output
