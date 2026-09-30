"""Tests for CLI commands."""

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
def cli_project(tmp_path):
    """Create a minimal doto project for CLI testing."""
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
    
    # Create empty tasks.json
    json_file = doto_dir / "tasks.json"
    json_file.write_text(json.dumps({
        "version": 2,
        "updated": "2026-07-26T10:00:00",
        "tasks": {}
    }))
    
    return tmp_path


class TestDotoAdd:
    """Test the doto add command."""
    
    def test_add_basic_task(self, cli_runner, cli_project):
        """Test adding a basic task."""
        from doxtr_doto.cli.main import cli
        
        result = cli_runner.invoke(cli, [
            "--config", str(cli_project),
            "add", "Test task"
        ])
        
        assert result.exit_code == 0
        
        # Verify task was added
        json_file = cli_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert len(data["tasks"]) == 1
    
    def test_add_task_with_options(self, cli_runner, cli_project):
        """Test adding a task with all options."""
        from doxtr_doto.cli.main import cli
        
        result = cli_runner.invoke(cli, [
            "--config", str(cli_project),
            "add", "Full task",
            "--id", "CUSTOM-001",
            "--assignee", "alice",
            "--priority", "high",
            "--status", "in-progress",
            "--due", "2026-12-31",
            "--tags", "feature,urgent",
        ])
        
        assert result.exit_code == 0
        
        json_file = cli_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        
        assert "CUSTOM-001" in data["tasks"]
        task = data["tasks"]["CUSTOM-001"]
        assert task["title"] == "Full task"
        assert task["assignee"] == "alice"
        assert task["priority"] == "high"
        assert task["status"] == "in-progress"
        assert task["due"] == "2026-12-31"
        assert task["tags"] == ["feature", "urgent"]
    
    def test_add_dry_run(self, cli_runner, cli_project):
        """Test add with dry-run flag."""
        from doxtr_doto.cli.main import cli
        
        result = cli_runner.invoke(cli, [
            "--config", str(cli_project),
            "add", "Dry run task",
            "--dry-run"
        ])
        
        assert result.exit_code == 0
        
        # Task should not be added
        json_file = cli_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert len(data["tasks"]) == 0


class TestDotoList:
    """Test the doto list command."""
    
    @pytest.fixture
    def populated_project(self, cli_project):
        """Create a project with some tasks."""
        json_file = cli_project / ".doto" / "tasks.json"
        json_file.write_text(json.dumps({
            "version": 2,
            "updated": "2026-07-26T10:00:00",
            "tasks": {
                "TASK-001": {
                    "title": "Task one",
                    "priority": "high",
                    "status": "open",
                    "assignee": "alice",
                    "tags": ["feature"],
                    "archived": False,
                },
                "TASK-002": {
                    "title": "Task two",
                    "priority": "low",
                    "status": "done",
                    "assignee": "bob",
                    "tags": ["bug"],
                    "archived": False,
                },
                "TASK-003": {
                    "title": "Task three",
                    "priority": "critical",
                    "status": "blocked",
                    "tags": ["urgent"],
                    "archived": True,
                },
            }
        }))
        return cli_project
    
    def test_list_all(self, cli_runner, populated_project):
        """Test listing all tasks."""
        from doxtr_doto.cli.main import cli
        
        result = cli_runner.invoke(cli, [
            "--config", str(populated_project),
            "list"
        ])
        
        assert result.exit_code == 0
        assert "TASK-001" in result.output
        assert "TASK-002" in result.output
        # Archived tasks should not show by default
        assert "TASK-003" not in result.output
    
    def test_list_with_archived(self, cli_runner, populated_project):
        """Test listing including archived tasks."""
        from doxtr_doto.cli.main import cli
        
        result = cli_runner.invoke(cli, [
            "--config", str(populated_project),
            "list", "--archived"
        ])
        
        assert result.exit_code == 0
        assert "TASK-003" in result.output
    
    def test_list_filter_by_status(self, cli_runner, populated_project):
        """Test filtering by status."""
        from doxtr_doto.cli.main import cli
        
        result = cli_runner.invoke(cli, [
            "--config", str(populated_project),
            "list", "--status", "open"
        ])
        
        assert result.exit_code == 0
        assert "TASK-001" in result.output
        assert "TASK-002" not in result.output
    
    def test_list_filter_by_assignee(self, cli_runner, populated_project):
        """Test filtering by assignee."""
        from doxtr_doto.cli.main import cli
        
        result = cli_runner.invoke(cli, [
            "--config", str(populated_project),
            "list", "--assignee", "alice"
        ])
        
        assert result.exit_code == 0
        assert "TASK-001" in result.output
        assert "TASK-002" not in result.output
    
    def test_list_json_format(self, cli_runner, populated_project):
        """Test JSON output format."""
        from doxtr_doto.cli.main import cli
        
        result = cli_runner.invoke(cli, [
            "--config", str(populated_project),
            "list", "--format", "json"
        ])
        
        assert result.exit_code == 0
        # Should be valid JSON
        data = json.loads(result.output)
        assert isinstance(data, list)


class TestDotoUpdate:
    """Test the doto update command."""
    
    @pytest.fixture
    def single_task_project(self, cli_project):
        """Create a project with one task."""
        json_file = cli_project / ".doto" / "tasks.json"
        json_file.write_text(json.dumps({
            "version": 2,
            "updated": "2026-07-26T10:00:00",
            "tasks": {
                "TASK-001": {
                    "title": "Original task",
                    "priority": "medium",
                    "status": "open",
                    "tags": ["original"],
                    "archived": False,
                }
            }
        }))
        return cli_project
    
    def test_update_status(self, cli_runner, single_task_project):
        """Test updating task status."""
        from doxtr_doto.cli.main import cli
        
        result = cli_runner.invoke(cli, [
            "--config", str(single_task_project),
            "update", "TASK-001", "--status", "in-progress"
        ])
        
        assert result.exit_code == 0
        
        json_file = single_task_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert data["tasks"]["TASK-001"]["status"] == "in-progress"
    
    def test_update_multiple_fields(self, cli_runner, single_task_project):
        """Test updating multiple fields at once."""
        from doxtr_doto.cli.main import cli
        
        result = cli_runner.invoke(cli, [
            "--config", str(single_task_project),
            "update", "TASK-001",
            "--priority", "high",
            "--assignee", "charlie"
        ])
        
        assert result.exit_code == 0
        
        json_file = single_task_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert data["tasks"]["TASK-001"]["priority"] == "high"
        assert data["tasks"]["TASK-001"]["assignee"] == "charlie"
    
    def test_update_nonexistent_task(self, cli_runner, single_task_project):
        """Test updating a nonexistent task."""
        from doxtr_doto.cli.main import cli
        
        result = cli_runner.invoke(cli, [
            "--config", str(single_task_project),
            "update", "NONEXISTENT", "--status", "done"
        ])
        
        assert result.exit_code != 0


class TestDotoConfig:
    """Test the doto config command."""

    def test_config_shows_json_path(self, cli_runner, cli_project):
        """Test that config shows the JSON database path."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(cli_project),
            "config"
        ])

        assert result.exit_code == 0
        assert ".doto/tasks.json" in result.output
        assert "JSON database" in result.output

    def test_config_json_format(self, cli_runner, cli_project):
        """Test config with JSON output format."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(cli_project),
            "config", "--format", "json"
        ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "json_file" in data
        assert "mode" in data
        assert "defaults" in data

    def test_config_shows_mode(self, cli_runner, cli_project):
        """Test that config shows the operation mode."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(cli_project),
            "config"
        ])

        assert result.exit_code == 0
        assert "Mode" in result.output


class TestDotoDeps:
    """Test the doto deps command."""

    @pytest.fixture
    def deps_project(self, cli_project):
        """Create a project with task dependencies."""
        json_file = cli_project / ".doto" / "tasks.json"
        json_file.write_text(json.dumps({
            "version": 2,
            "updated": "2026-07-26T10:00:00",
            "tasks": {
                "TASK-001": {
                    "title": "Main task",
                    "status": "open",
                    "depends_on": ["TASK-002", "TASK-003"],
                    "archived": False,
                },
                "TASK-002": {
                    "title": "Dependency one",
                    "status": "done",
                    "priority": "high",
                    "archived": False,
                },
                "TASK-003": {
                    "title": "Dependency two",
                    "status": "open",
                    "priority": "medium",
                    "depends_on": ["TASK-004"],
                    "archived": False,
                },
                "TASK-004": {
                    "title": "Nested dependency",
                    "status": "in-progress",
                    "priority": "low",
                    "archived": False,
                },
                "TASK-005": {
                    "title": "Independent task",
                    "status": "open",
                    "archived": False,
                },
            }
        }))
        return cli_project

    def test_deps_shows_direct_dependencies(self, cli_runner, deps_project):
        """Test showing direct dependencies."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(deps_project),
            "deps", "TASK-001"
        ])

        assert result.exit_code == 0
        assert "TASK-002" in result.output
        assert "TASK-003" in result.output
        # Should not show nested deps without --recursive
        assert "TASK-004" not in result.output

    def test_deps_recursive(self, cli_runner, deps_project):
        """Test showing recursive dependencies."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(deps_project),
            "deps", "TASK-001", "--recursive"
        ])

        assert result.exit_code == 0
        assert "TASK-002" in result.output
        assert "TASK-003" in result.output
        assert "TASK-004" in result.output

    def test_deps_pending_only(self, cli_runner, deps_project):
        """Test showing only pending dependencies."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(deps_project),
            "deps", "TASK-001", "--pending-only"
        ])

        assert result.exit_code == 0
        # TASK-002 is done, should not appear
        assert "TASK-002" not in result.output
        # TASK-003 is open, should appear
        assert "TASK-003" in result.output

    def test_deps_json_format(self, cli_runner, deps_project):
        """Test deps with JSON output format."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(deps_project),
            "deps", "TASK-001", "--format", "json"
        ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["task_id"] == "TASK-001"
        assert "dependencies" in data
        assert len(data["dependencies"]) == 2

    def test_deps_no_dependencies(self, cli_runner, deps_project):
        """Test task with no dependencies."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(deps_project),
            "deps", "TASK-005"
        ])

        assert result.exit_code == 0
        assert "No dependencies" in result.output or "can be started" in result.output

    def test_deps_nonexistent_task(self, cli_runner, deps_project):
        """Test deps for nonexistent task."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(deps_project),
            "deps", "NONEXISTENT"
        ])

        assert result.exit_code != 0

    def test_deps_tree_format(self, cli_runner, deps_project):
        """Test deps with tree output format."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(deps_project),
            "deps", "TASK-001", "--format", "tree", "--recursive"
        ])

        assert result.exit_code == 0
        # Tree format should show hierarchy indicators
        assert "TASK-001" in result.output
        assert "TASK-002" in result.output


class TestDotoListColumns:
    """Test configurable columns in doto list."""

    @pytest.fixture
    def project_with_columns_config(self, cli_project):
        """Create a project with custom list columns config."""
        # Update config to specify columns
        config_file = cli_project / ".doto.toml"
        config_file.write_text('''
[doto]
json_file = ".doto/tasks.json"
id_prefix = "TEST"
list_columns = ["id", "title", "status"]
''')

        # Add a task
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
                    "archived": False,
                }
            }
        }))
        return cli_project

    def test_list_uses_config_columns(self, cli_runner, project_with_columns_config):
        """Test that list uses columns from config."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(project_with_columns_config),
            "list"
        ])

        assert result.exit_code == 0
        # With config ["id", "title", "status"], assignee column shouldn't appear as header
        # The task data is there but columns control display

    def test_list_cli_columns_override_config(self, cli_runner, project_with_columns_config):
        """Test that CLI --columns overrides config."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(project_with_columns_config),
            "list", "--columns", "id,priority"
        ])

        assert result.exit_code == 0
        assert "TASK-001" in result.output


class TestDotoListWithDeps:
    """Test doto list with dependency information."""

    @pytest.fixture
    def deps_list_project(self, cli_project):
        """Create a project with task dependencies for list testing."""
        json_file = cli_project / ".doto" / "tasks.json"
        json_file.write_text(json.dumps({
            "version": 2,
            "updated": "2026-07-26T10:00:00",
            "tasks": {
                "TASK-001": {
                    "title": "Main task",
                    "status": "open",
                    "priority": "high",
                    "depends_on": ["TASK-002", "TASK-003"],
                    "archived": False,
                },
                "TASK-002": {
                    "title": "Dependency one",
                    "status": "done",
                    "priority": "medium",
                    "archived": False,
                },
                "TASK-003": {
                    "title": "Dependency two",
                    "status": "open",
                    "priority": "high",
                    "archived": False,
                },
                "TASK-004": {
                    "title": "Independent task",
                    "status": "open",
                    "priority": "low",
                    "archived": False,
                },
            }
        }))
        return cli_project

    def test_list_with_deps_flag(self, cli_runner, deps_list_project):
        """Test list with --with-deps shows dependency column."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(deps_list_project),
            "list", "--with-deps"
        ])

        assert result.exit_code == 0
        # Should show dependency markers
        assert "TASK-001" in result.output
        assert "TASK-002" in result.output

    def test_list_tree_format(self, cli_runner, deps_list_project):
        """Test list with tree format."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(deps_list_project),
            "list", "--format", "tree"
        ])

        assert result.exit_code == 0
        # Tree format shows ready vs waiting
        assert "ready" in result.output.lower() or "waiting" in result.output.lower()

    def test_list_with_deps_json(self, cli_runner, deps_list_project):
        """Test list with --with-deps and JSON format."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(deps_list_project),
            "list", "--with-deps", "--format", "json"
        ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        # Tasks should have dependency info
        task_001 = next(t for t in data if t["id"] == "TASK-001")
        assert "has_deps" in task_001
        assert task_001["has_deps"] is True
        assert task_001["deps_count"] == 2
        assert task_001["pending_deps"] == 1  # TASK-003 is still open


class TestOpenEditor:
    """Test the open_editor function and editor fallback."""

    def test_find_editor_from_env(self, monkeypatch, tmp_path):
        """Test that _find_editor uses EDITOR env var."""
        from doxtr_doto.cli.commands.add import _find_editor

        # Create a fake editor script
        fake_editor = tmp_path / "my-editor"
        fake_editor.write_text("#!/bin/sh\nexit 0")
        fake_editor.chmod(0o755)

        monkeypatch.setenv("EDITOR", str(fake_editor))
        monkeypatch.delenv("VISUAL", raising=False)

        result = _find_editor()
        assert result == str(fake_editor)

    def test_find_editor_from_visual(self, monkeypatch, tmp_path):
        """Test that _find_editor falls back to VISUAL env var."""
        from doxtr_doto.cli.commands.add import _find_editor

        fake_editor = tmp_path / "visual-editor"
        fake_editor.write_text("#!/bin/sh\nexit 0")
        fake_editor.chmod(0o755)

        monkeypatch.delenv("EDITOR", raising=False)
        monkeypatch.setenv("VISUAL", str(fake_editor))

        result = _find_editor()
        assert result == str(fake_editor)

    def test_find_editor_returns_none_when_no_editor(self, monkeypatch):
        """Test that _find_editor returns None when no editor is available."""
        from doxtr_doto.cli.commands.add import _find_editor
        import shutil

        monkeypatch.delenv("EDITOR", raising=False)
        monkeypatch.delenv("VISUAL", raising=False)
        # Mock shutil.which to return None for all editors
        monkeypatch.setattr(shutil, "which", lambda x: None)

        result = _find_editor()
        assert result is None

    def test_open_editor_fallback_to_stdin(self, monkeypatch):
        """Test that open_editor falls back to stdin when no editor available."""
        from doxtr_doto.cli.commands.add import open_editor
        import shutil

        monkeypatch.delenv("EDITOR", raising=False)
        monkeypatch.delenv("VISUAL", raising=False)
        monkeypatch.setattr(shutil, "which", lambda x: None)

        # Simulate user input
        input_lines = iter(["Line one", "Line two", ""])
        monkeypatch.setattr("builtins.input", lambda: next(input_lines))

        result = open_editor()
        assert result == "Line one\nLine two"

    def test_open_editor_fallback_handles_eof(self, monkeypatch):
        """Test that open_editor fallback handles EOF gracefully."""
        from doxtr_doto.cli.commands.add import open_editor
        import shutil

        monkeypatch.delenv("EDITOR", raising=False)
        monkeypatch.delenv("VISUAL", raising=False)
        monkeypatch.setattr(shutil, "which", lambda x: None)

        # Simulate EOF after some input
        input_count = [0]
        def fake_input():
            input_count[0] += 1
            if input_count[0] == 1:
                return "Only line"
            raise EOFError()

        monkeypatch.setattr("builtins.input", fake_input)

        result = open_editor()
        assert result == "Only line"

    def test_add_interactive_no_editor_available(self, cli_runner, cli_project, monkeypatch):
        """Test interactive add falls back gracefully when no editor exists."""
        from doxtr_doto.cli.main import cli
        import shutil

        monkeypatch.delenv("EDITOR", raising=False)
        monkeypatch.delenv("VISUAL", raising=False)
        monkeypatch.setattr(shutil, "which", lambda x: None)

        # Simulate interactive input including description via stdin fallback
        result = cli_runner.invoke(cli, [
            "--config", str(cli_project),
            "add", "--interactive"
        ], input="Test task\nalice\nmedium\nopen\n\n\nn\n")

        assert result.exit_code == 0
        assert "Added task" in result.output


class TestShellCompletion:
    """Test shell completion functions."""

    @pytest.fixture
    def completion_project(self, cli_project):
        """Create a project with tasks for completion testing."""
        json_file = cli_project / ".doto" / "tasks.json"
        json_file.write_text(json.dumps({
            "version": 2,
            "updated": "2026-07-26T10:00:00",
            "tasks": {
                "TASK-001": {
                    "title": "First task",
                    "status": "open",
                    "assignee": "alice",
                    "tags": ["feature", "backend"],
                    "archived": False,
                },
                "TASK-002": {
                    "title": "Second task",
                    "status": "in-progress",
                    "assignee": "bob",
                    "tags": ["bug"],
                    "archived": False,
                },
                "TASK-003": {
                    "title": "Done task",
                    "status": "done",
                    "assignee": "alice",
                    "tags": ["feature"],
                    "archived": False,
                },
            }
        }))
        return cli_project

    def test_complete_task_id(self, completion_project, monkeypatch):
        """Test task ID completion."""
        monkeypatch.chdir(completion_project)
        from doxtr_doto.cli.completion import complete_task_id

        # Complete all tasks starting with "TASK"
        results = complete_task_id(None, None, "TASK")
        assert len(results) == 3
        values = [r.value for r in results]
        assert "TASK-001" in values
        assert "TASK-002" in values
        assert "TASK-003" in values

    def test_complete_task_id_partial(self, completion_project, monkeypatch):
        """Test partial task ID completion."""
        monkeypatch.chdir(completion_project)
        from doxtr_doto.cli.completion import complete_task_id

        results = complete_task_id(None, None, "TASK-00")
        assert len(results) == 3

        results = complete_task_id(None, None, "TASK-001")
        assert len(results) == 1
        assert results[0].value == "TASK-001"

    def test_complete_open_task_id(self, completion_project, monkeypatch):
        """Test open task ID completion (excludes done tasks)."""
        monkeypatch.chdir(completion_project)
        from doxtr_doto.cli.completion import complete_open_task_id

        results = complete_open_task_id(None, None, "TASK")
        values = [r.value for r in results]
        assert "TASK-001" in values
        assert "TASK-002" in values
        assert "TASK-003" not in values  # Done task excluded

    def test_complete_done_task_id(self, completion_project, monkeypatch):
        """Test done task ID completion (only done tasks)."""
        monkeypatch.chdir(completion_project)
        from doxtr_doto.cli.completion import complete_done_task_id

        results = complete_done_task_id(None, None, "TASK")
        values = [r.value for r in results]
        assert "TASK-001" not in values
        assert "TASK-002" not in values
        assert "TASK-003" in values  # Only done task

    def test_complete_assignee(self, completion_project, monkeypatch):
        """Test assignee completion."""
        monkeypatch.chdir(completion_project)
        from doxtr_doto.cli.completion import complete_assignee

        results = complete_assignee(None, None, "")
        values = [r.value for r in results]
        assert "alice" in values
        assert "bob" in values

        # Partial match
        results = complete_assignee(None, None, "al")
        values = [r.value for r in results]
        assert "alice" in values
        assert "bob" not in values

    def test_complete_tag(self, completion_project, monkeypatch):
        """Test tag completion."""
        monkeypatch.chdir(completion_project)
        from doxtr_doto.cli.completion import complete_tag

        results = complete_tag(None, None, "")
        values = [r.value for r in results]
        assert "feature" in values
        assert "backend" in values
        assert "bug" in values

        # Partial match
        results = complete_tag(None, None, "b")
        values = [r.value for r in results]
        assert "backend" in values
        assert "bug" in values
        assert "feature" not in values

    def test_complete_date(self):
        """Test date completion."""
        from doxtr_doto.cli.completion import complete_date

        results = complete_date(None, None, "")
        values = [r.value for r in results]
        assert "today" in values
        assert "tomorrow" in values
        assert "+1d" in values
        assert "friday" in values

        # Partial match
        results = complete_date(None, None, "to")
        values = [r.value for r in results]
        assert "today" in values
        assert "tomorrow" in values
        assert "friday" not in values

    def test_completion_without_project(self, tmp_path, monkeypatch):
        """Test completion gracefully handles missing project."""
        monkeypatch.chdir(tmp_path)
        from doxtr_doto.cli.completion import complete_task_id, complete_assignee

        # Should return empty list, not error
        results = complete_task_id(None, None, "TASK")
        assert results == []

        results = complete_assignee(None, None, "")
        assert results == []


class TestCompletionCommand:
    """Test the doto completion command."""

    def test_completion_bash_output(self, cli_runner, cli_project):
        """Test completion command outputs bash script."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(cli_project),
            "completion", "bash"
        ])

        assert result.exit_code == 0
        assert "_doto_completion" in result.output
        assert "COMP_WORDS" in result.output

    def test_completion_zsh_output(self, cli_runner, cli_project):
        """Test completion command outputs zsh script."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(cli_project),
            "completion", "zsh"
        ])

        assert result.exit_code == 0
        assert "_doto_completion" in result.output

    def test_completion_fish_output(self, cli_runner, cli_project):
        """Test completion command outputs fish script."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(cli_project),
            "completion", "fish"
        ])

        assert result.exit_code == 0
        assert "complete" in result.output.lower()

    def test_completion_install_bash(self, cli_runner, cli_project, tmp_path, monkeypatch):
        """Test completion --install for bash."""
        from doxtr_doto.cli.main import cli

        # Create a fake .bashrc
        bashrc = tmp_path / ".bashrc"
        bashrc.write_text("# existing config\n")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        result = cli_runner.invoke(cli, [
            "--config", str(cli_project),
            "completion", "bash", "--install"
        ])

        assert result.exit_code == 0
        assert "Added completion" in result.output

        # Check file was modified
        content = bashrc.read_text()
        assert "_DOTO_COMPLETE" in content
        assert "bash_source" in content

    def test_completion_install_already_installed(self, cli_runner, cli_project, tmp_path, monkeypatch):
        """Test completion --install when already installed."""
        from doxtr_doto.cli.main import cli

        # Create a .bashrc with completion already installed
        bashrc = tmp_path / ".bashrc"
        bashrc.write_text('eval "$(_DOTO_COMPLETE=bash_source doto)"\n')
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        result = cli_runner.invoke(cli, [
            "--config", str(cli_project),
            "completion", "bash", "--install"
        ])

        assert result.exit_code == 0
        assert "already installed" in result.output


class TestDotoTree:
    """Test the doto tree command."""

    @pytest.fixture
    def tree_project(self, cli_project):
        """Create a project with dependency chains for tree testing."""
        json_file = cli_project / ".doto" / "tasks.json"
        json_file.write_text(json.dumps({
            "version": 2,
            "updated": "2026-07-26T10:00:00",
            "tasks": {
                "ROOT-001": {
                    "title": "Root task",
                    "status": "open",
                    "priority": "high",
                    "archived": False,
                },
                "CHILD-001": {
                    "title": "Child task",
                    "status": "open",
                    "priority": "medium",
                    "depends_on": ["ROOT-001"],
                    "archived": False,
                },
                "CHILD-002": {
                    "title": "Another child",
                    "status": "open",
                    "priority": "low",
                    "depends_on": ["ROOT-001"],
                    "archived": False,
                },
                "GRANDCHILD-001": {
                    "title": "Grandchild task",
                    "status": "in-progress",
                    "priority": "high",
                    "depends_on": ["CHILD-001"],
                    "archived": False,
                },
                "STANDALONE": {
                    "title": "Standalone task",
                    "status": "open",
                    "priority": "medium",
                    "archived": False,
                },
            }
        }))
        return cli_project

    def test_tree_shows_all_tasks(self, cli_runner, tree_project):
        """Test tree shows all tasks in hierarchy."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(tree_project),
            "tree"
        ])

        assert result.exit_code == 0
        assert "ROOT-001" in result.output
        assert "CHILD-001" in result.output
        assert "GRANDCHILD-001" in result.output
        assert "STANDALONE" in result.output

    def test_tree_single_task_deps(self, cli_runner, tree_project):
        """Test tree for single task shows dependencies."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(tree_project),
            "tree", "GRANDCHILD-001"
        ])

        assert result.exit_code == 0
        assert "Dependencies of GRANDCHILD-001" in result.output
        assert "CHILD-001" in result.output
        assert "ROOT-001" in result.output

    def test_tree_reverse_deps(self, cli_runner, tree_project):
        """Test tree --reverse shows dependents."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(tree_project),
            "tree", "ROOT-001", "--reverse"
        ])

        assert result.exit_code == 0
        assert "Tasks that depend on ROOT-001" in result.output
        assert "CHILD-001" in result.output
        assert "CHILD-002" in result.output
        assert "GRANDCHILD-001" in result.output

    def test_tree_compact_mode(self, cli_runner, tree_project):
        """Test tree --compact shows minimal output."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(tree_project),
            "tree", "--compact"
        ])

        assert result.exit_code == 0
        # Compact mode shows IDs without titles
        assert "ROOT-001" in result.output
        # Title should not appear in compact mode
        assert "Root task" not in result.output

    def test_tree_depth_limit(self, cli_runner, tree_project):
        """Test tree --depth limits output depth."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(tree_project),
            "tree", "--depth", "1"
        ])

        assert result.exit_code == 0
        assert "ROOT-001" in result.output
        assert "CHILD-001" in result.output
        # Grandchild should be cut off at depth 1
        assert "GRANDCHILD-001" not in result.output

    def test_tree_nonexistent_task(self, cli_runner, tree_project):
        """Test tree with nonexistent task."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(tree_project),
            "tree", "NONEXISTENT"
        ])

        assert result.exit_code != 0
        assert "not found" in result.output.lower()


class TestDotoNext:
    """Test the doto next command."""

    @pytest.fixture
    def next_project(self, cli_project):
        """Create a project with tasks for next testing."""
        json_file = cli_project / ".doto" / "tasks.json"
        json_file.write_text(json.dumps({
            "version": 2,
            "updated": "2026-07-26T10:00:00",
            "tasks": {
                "TASK-001": {
                    "title": "Low priority task",
                    "status": "open",
                    "priority": "low",
                    "archived": False,
                },
                "TASK-002": {
                    "title": "High priority task",
                    "status": "open",
                    "priority": "high",
                    "archived": False,
                },
                "TASK-003": {
                    "title": "In progress task",
                    "status": "in-progress",
                    "priority": "medium",
                    "archived": False,
                },
                "TASK-004": {
                    "title": "Blocked task",
                    "status": "open",
                    "priority": "critical",
                    "depends_on": ["TASK-001"],
                    "archived": False,
                },
                "TASK-005": {
                    "title": "Done task",
                    "status": "done",
                    "priority": "high",
                    "archived": False,
                },
            }
        }))
        return cli_project

    def test_next_shows_top_task(self, cli_runner, next_project):
        """Test next shows the highest priority actionable task."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(next_project),
            "next"
        ])

        assert result.exit_code == 0
        # In-progress task should be shown (gets bonus)
        assert "TASK-003" in result.output
        assert "In progress task" in result.output

    def test_next_excludes_blocked_by_default(self, cli_runner, next_project):
        """Test next excludes tasks with pending dependencies."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(next_project),
            "next", "--all"
        ])

        assert result.exit_code == 0
        # TASK-004 is blocked by TASK-001, should not appear
        assert "TASK-004" not in result.output

    def test_next_include_blocked(self, cli_runner, next_project):
        """Test next --include-blocked shows blocked tasks."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(next_project),
            "next", "--all", "--include-blocked"
        ])

        assert result.exit_code == 0
        assert "TASK-004" in result.output
        assert "blocked by 1" in result.output

    def test_next_excludes_done(self, cli_runner, next_project):
        """Test next excludes done tasks."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(next_project),
            "next", "--all"
        ])

        assert result.exit_code == 0
        assert "TASK-005" not in result.output

    def test_next_json_output(self, cli_runner, next_project):
        """Test next with JSON output."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(next_project),
            "next", "--json"
        ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "id" in data
        assert "score" in data

    def test_next_no_tasks(self, cli_runner, cli_project):
        """Test next with no tasks."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(cli_project),
            "next"
        ])

        assert result.exit_code == 0
        assert "No tasks found" in result.output


class TestDotoDone:
    """Test the doto done command."""
    
    @pytest.fixture
    def open_tasks_project(self, cli_project):
        """Create a project with open tasks."""
        json_file = cli_project / ".doto" / "tasks.json"
        json_file.write_text(json.dumps({
            "version": 2,
            "updated": "2026-07-26T10:00:00",
            "tasks": {
                "TASK-001": {"title": "Task 1", "status": "open", "archived": False},
                "TASK-002": {"title": "Task 2", "status": "in-progress", "archived": False},
            }
        }))
        return cli_project
    
    def test_done_single_task(self, cli_runner, open_tasks_project):
        """Test marking a single task as done."""
        from doxtr_doto.cli.main import cli
        
        result = cli_runner.invoke(cli, [
            "--config", str(open_tasks_project),
            "done", "TASK-001"
        ])
        
        assert result.exit_code == 0
        
        json_file = open_tasks_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert data["tasks"]["TASK-001"]["status"] == "done"
        assert data["tasks"]["TASK-002"]["status"] == "in-progress"
    
    def test_done_multiple_tasks(self, cli_runner, open_tasks_project):
        """Test marking multiple tasks as done."""
        from doxtr_doto.cli.main import cli
        
        result = cli_runner.invoke(cli, [
            "--config", str(open_tasks_project),
            "done", "TASK-001", "TASK-002"
        ])
        
        assert result.exit_code == 0
        
        json_file = open_tasks_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert data["tasks"]["TASK-001"]["status"] == "done"
        assert data["tasks"]["TASK-002"]["status"] == "done"


class TestDotoSearch:
    """Test the doto search command."""

    @pytest.fixture
    def search_project(self, cli_project):
        """Create a project with searchable tasks."""
        json_file = cli_project / ".doto" / "tasks.json"
        json_file.write_text(json.dumps({
            "version": 3,
            "updated": "2026-07-26T10:00:00",
            "tasks": {
                "TASK-001": {
                    "title": "Fix login bug",
                    "status": "open",
                    "priority": "high",
                    "body": "Authentication failing for some users",
                    "tags": ["bug", "auth"],
                    "archived": False,
                },
                "TASK-002": {
                    "title": "Add user profile page",
                    "status": "in-progress",
                    "priority": "medium",
                    "body": "Create profile view component",
                    "tags": ["feature"],
                    "archived": False,
                },
                "TASK-003": {
                    "title": "Old feature request",
                    "status": "done",
                    "priority": "low",
                    "body": "Some archived content",
                    "tags": ["feature"],
                    "archived": True,
                },
            },
            "series": {},
        }))
        return cli_project

    def test_search_by_title(self, cli_runner, search_project):
        """Test searching tasks by title."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(search_project),
            "search", "login"
        ])

        assert result.exit_code == 0
        assert "TASK-001" in result.output
        assert "TASK-002" not in result.output

    def test_search_by_body(self, cli_runner, search_project):
        """Test searching tasks by body content."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(search_project),
            "search", "Authentication", "--body"
        ])

        assert result.exit_code == 0
        assert "TASK-001" in result.output

    def test_search_regex(self, cli_runner, search_project):
        """Test searching with regex pattern."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(search_project),
            "search", "fix|add", "--regex"
        ])

        assert result.exit_code == 0
        assert "TASK-001" in result.output
        assert "TASK-002" in result.output

    def test_search_with_field(self, cli_runner, search_project):
        """Test searching specific field."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(search_project),
            "search", "bug", "--field", "tags"
        ])

        assert result.exit_code == 0
        assert "TASK-001" in result.output
        assert "TASK-002" not in result.output

    def test_search_includes_archived(self, cli_runner, search_project):
        """Test searching includes archived tasks when flag is set."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(search_project),
            "search", "Old", "--archived"
        ])

        assert result.exit_code == 0
        assert "TASK-003" in result.output

    def test_search_json_output(self, cli_runner, search_project):
        """Test search with JSON output."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(search_project),
            "search", "login", "--json"
        ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["id"] == "TASK-001"

    def test_search_no_results(self, cli_runner, search_project):
        """Test search with no matching results."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(search_project),
            "search", "nonexistent"
        ])

        assert result.exit_code == 0
        assert "No tasks found" in result.output


class TestDotoExport:
    """Test the doto export command."""

    @pytest.fixture
    def export_project(self, cli_project):
        """Create a project with tasks for export."""
        json_file = cli_project / ".doto" / "tasks.json"
        json_file.write_text(json.dumps({
            "version": 3,
            "updated": "2026-07-26T10:00:00",
            "tasks": {
                "TASK-001": {
                    "title": "Task one",
                    "status": "open",
                    "priority": "high",
                    "assignee": "alice",
                    "tags": ["urgent"],
                    "archived": False,
                },
                "TASK-002": {
                    "title": "Task two",
                    "status": "done",
                    "priority": "low",
                    "assignee": "bob",
                    "tags": [],
                    "archived": False,
                },
            },
            "series": {},
        }))
        return cli_project

    def test_export_json(self, cli_runner, export_project):
        """Test exporting tasks as JSON."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(export_project),
            "export", "--format", "json"
        ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 2

    def test_export_csv(self, cli_runner, export_project):
        """Test exporting tasks as CSV."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(export_project),
            "export", "--format", "csv"
        ])

        assert result.exit_code == 0
        assert "id,title" in result.output
        assert "TASK-001" in result.output
        assert "TASK-002" in result.output

    def test_export_markdown(self, cli_runner, export_project):
        """Test exporting tasks as Markdown."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(export_project),
            "export", "--format", "markdown"
        ])

        assert result.exit_code == 0
        assert "# Tasks" in result.output
        assert "TASK-001" in result.output
        assert "[ ]" in result.output  # Open task checkbox
        assert "[x]" in result.output  # Done task checkbox

    def test_export_to_file(self, cli_runner, export_project, tmp_path):
        """Test exporting tasks to a file."""
        from doxtr_doto.cli.main import cli

        output_file = tmp_path / "export.json"
        result = cli_runner.invoke(cli, [
            "--config", str(export_project),
            "export", "--format", "json", "--output", str(output_file)
        ])

        assert result.exit_code == 0
        assert output_file.exists()
        data = json.loads(output_file.read_text())
        assert len(data) == 2

    def test_export_filter_by_status(self, cli_runner, export_project):
        """Test exporting with status filter."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(export_project),
            "export", "--format", "json", "--status", "done"
        ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["id"] == "TASK-002"

    def test_export_filter_by_assignee(self, cli_runner, export_project):
        """Test exporting with assignee filter."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(export_project),
            "export", "--format", "json", "--assignee", "alice"
        ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["id"] == "TASK-001"


class TestDotoArchive:
    """Test the doto archive command."""

    @pytest.fixture
    def archive_project(self, cli_project):
        """Create a project with tasks for archiving."""
        json_file = cli_project / ".doto" / "tasks.json"
        json_file.write_text(json.dumps({
            "version": 3,
            "updated": "2026-07-26T10:00:00",
            "tasks": {
                "TASK-001": {
                    "title": "Task to archive",
                    "status": "done",
                    "priority": "low",
                    "archived": False,
                },
                "TASK-002": {
                    "title": "Another task",
                    "status": "open",
                    "priority": "high",
                    "archived": False,
                },
                "TASK-003": {
                    "title": "Already archived",
                    "status": "done",
                    "priority": "low",
                    "archived": True,
                },
            },
            "series": {},
        }))
        return cli_project

    def test_archive_single_task(self, cli_runner, archive_project):
        """Test archiving a single task."""
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
        assert data["tasks"]["TASK-002"]["archived"] is False

    def test_archive_multiple_tasks(self, cli_runner, archive_project):
        """Test archiving multiple tasks."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(archive_project),
            "archive", "TASK-001", "TASK-002", "--yes"
        ])

        assert result.exit_code == 0

        json_file = archive_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert data["tasks"]["TASK-001"]["archived"] is True
        assert data["tasks"]["TASK-002"]["archived"] is True

    def test_archive_already_archived(self, cli_runner, archive_project):
        """Test archiving an already archived task."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(archive_project),
            "archive", "TASK-003", "--yes"
        ])

        assert result.exit_code == 0
        assert "already archived" in result.output

    def test_archive_nonexistent_task(self, cli_runner, archive_project):
        """Test archiving a nonexistent task."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(archive_project),
            "archive", "NONEXISTENT"
        ])

        assert result.exit_code == 0
        assert "not found" in result.output

    def test_archive_json_output(self, cli_runner, archive_project):
        """Test archive with JSON output."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(archive_project),
            "archive", "TASK-001", "--json"
        ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "TASK-001" in data["archived"]


class TestConfigValidators:
    """Test config-aware validators for priority and status."""

    def test_add_with_valid_priority(self, cli_runner, cli_project):
        """Test add command accepts valid priority."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(cli_project),
            "add", "Test task", "--priority", "high"
        ])

        assert result.exit_code == 0

    def test_add_with_invalid_priority(self, cli_runner, cli_project):
        """Test add command rejects invalid priority."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(cli_project),
            "add", "Test task", "--priority", "invalid"
        ])

        assert result.exit_code != 0
        assert "Invalid priority" in result.output

    def test_add_with_valid_status(self, cli_runner, cli_project):
        """Test add command accepts valid status."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(cli_project),
            "add", "Test task", "--status", "in-progress"
        ])

        assert result.exit_code == 0

    def test_add_with_invalid_status(self, cli_runner, cli_project):
        """Test add command rejects invalid status."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(cli_project),
            "add", "Test task", "--status", "invalid"
        ])

        assert result.exit_code != 0
        assert "Invalid status" in result.output

    def test_update_with_valid_priority(self, cli_runner, cli_project):
        """Test update command accepts valid priority."""
        from doxtr_doto.cli.main import cli

        # First add a task
        cli_runner.invoke(cli, [
            "--config", str(cli_project),
            "add", "Test task", "--id", "TEST-001"
        ])

        result = cli_runner.invoke(cli, [
            "--config", str(cli_project),
            "update", "TEST-001", "--priority", "critical"
        ])

        assert result.exit_code == 0

    def test_update_with_invalid_status(self, cli_runner, cli_project):
        """Test update command rejects invalid status."""
        from doxtr_doto.cli.main import cli

        # First add a task
        cli_runner.invoke(cli, [
            "--config", str(cli_project),
            "add", "Test task", "--id", "TEST-001"
        ])

        result = cli_runner.invoke(cli, [
            "--config", str(cli_project),
            "update", "TEST-001", "--status", "badstatus"
        ])

        assert result.exit_code != 0
        assert "Invalid status" in result.output


class TestDotoSeriesList:
    """Test the doto series list command."""

    @pytest.fixture
    def series_project(self, cli_project):
        """Create a project with series data."""
        json_file = cli_project / ".doto" / "tasks.json"
        json_file.write_text(json.dumps({
            "version": 3,
            "updated": "2026-07-26T10:00:00",
            "tasks": {
                "TASK-001": {
                    "title": "Weekly standup - 2026-07-01",
                    "status": "done",
                    "due": "2026-07-01",
                    "series_id": "SERIES-001",
                    "archived": False,
                },
                "TASK-002": {
                    "title": "Weekly standup - 2026-07-08",
                    "status": "open",
                    "due": "2026-07-08",
                    "series_id": "SERIES-001",
                    "archived": False,
                },
                "TASK-003": {
                    "title": "Monthly report - 2026-07",
                    "status": "open",
                    "due": "2026-07-31",
                    "series_id": "SERIES-002",
                    "archived": False,
                },
            },
            "series": {
                "SERIES-001": {
                    "title_template": "Weekly standup - {date}",
                    "pattern": {"type": "weekly", "interval": 1, "weekdays": [0]},
                    "start_date": "2026-07-01",
                    "end_date": "2026-08-31",
                    "task_ids": ["TASK-001", "TASK-002"],
                    "created": "2026-06-25T10:00:00",
                },
                "SERIES-002": {
                    "title_template": "Monthly report - {date}",
                    "pattern": {"type": "monthly", "interval": 1, "day_of_month": 31},
                    "start_date": "2026-07-01",
                    "end_date": "2026-12-31",
                    "task_ids": ["TASK-003"],
                    "created": "2026-06-25T10:00:00",
                },
            },
        }))
        return cli_project

    def test_series_list_shows_all_series(self, cli_runner, series_project):
        """Test that series list shows all series."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(series_project),
            "series", "list"
        ])

        assert result.exit_code == 0
        assert "SERIES-001" in result.output
        assert "SERIES-002" in result.output
        assert "Weekly standup" in result.output
        assert "Monthly report" in result.output

    def test_series_list_shows_progress(self, cli_runner, series_project):
        """Test that series list shows progress (done/total)."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(series_project),
            "series", "list"
        ])

        assert result.exit_code == 0
        # SERIES-001 has 1 done, 1 open = 1/2
        assert "1/2" in result.output

    def test_series_list_json_output(self, cli_runner, series_project):
        """Test that series list outputs JSON when --json flag used."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(series_project),
            "series", "list", "--json"
        ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "series" in data
        assert len(data["series"]) == 2
        series_ids = [s["id"] for s in data["series"]]
        assert "SERIES-001" in series_ids
        assert "SERIES-002" in series_ids

    def test_series_list_empty(self, cli_runner, cli_project):
        """Test that series list handles no series gracefully."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(cli_project),
            "series", "list"
        ])

        assert result.exit_code == 0
        assert "No series found" in result.output


class TestDotoSeriesShow:
    """Test the doto series show command."""

    @pytest.fixture
    def series_project(self, cli_project):
        """Create a project with series data."""
        json_file = cli_project / ".doto" / "tasks.json"
        json_file.write_text(json.dumps({
            "version": 3,
            "updated": "2026-07-26T10:00:00",
            "tasks": {
                "TASK-001": {
                    "title": "Daily check - 2026-07-01",
                    "status": "done",
                    "due": "2026-07-01",
                    "series_id": "SERIES-001",
                    "archived": False,
                },
                "TASK-002": {
                    "title": "Daily check - 2026-07-02",
                    "status": "in-progress",
                    "due": "2026-07-02",
                    "series_id": "SERIES-001",
                    "archived": False,
                },
                "TASK-003": {
                    "title": "Daily check - 2026-07-03",
                    "status": "open",
                    "due": "2026-07-03",
                    "series_id": "SERIES-001",
                    "archived": False,
                },
            },
            "series": {
                "SERIES-001": {
                    "title_template": "Daily check - {date}",
                    "pattern": {"type": "daily", "interval": 1},
                    "start_date": "2026-07-01",
                    "end_date": "2026-07-31",
                    "task_ids": ["TASK-001", "TASK-002", "TASK-003"],
                    "created": "2026-06-25T10:00:00",
                },
            },
        }))
        return cli_project

    def test_series_show_displays_details(self, cli_runner, series_project):
        """Test that series show displays series details."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(series_project),
            "series", "show", "SERIES-001"
        ])

        assert result.exit_code == 0
        assert "SERIES-001" in result.output
        assert "Daily check" in result.output
        assert "2026-07-01" in result.output
        assert "2026-07-31" in result.output

    def test_series_show_displays_task_counts(self, cli_runner, series_project):
        """Test that series show displays task status counts."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(series_project),
            "series", "show", "SERIES-001"
        ])

        assert result.exit_code == 0
        assert "done: 1" in result.output
        assert "in-progress: 1" in result.output
        assert "open: 1" in result.output

    def test_series_show_json_output(self, cli_runner, series_project):
        """Test that series show outputs JSON when --json flag used."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(series_project),
            "series", "show", "SERIES-001", "--json"
        ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["id"] == "SERIES-001"
        assert "title_template" in data
        assert "pattern" in data
        assert "tasks" in data
        assert len(data["tasks"]) == 3

    def test_series_show_nonexistent(self, cli_runner, series_project):
        """Test that series show fails for nonexistent series."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(series_project),
            "series", "show", "NONEXISTENT"
        ])

        assert result.exit_code != 0
        assert "not found" in result.output.lower()


class TestDotoSeriesDelete:
    """Test the doto series delete command."""

    @pytest.fixture
    def series_project(self, cli_project):
        """Create a project with series data."""
        json_file = cli_project / ".doto" / "tasks.json"
        json_file.write_text(json.dumps({
            "version": 3,
            "updated": "2026-07-26T10:00:00",
            "tasks": {
                "TASK-001": {
                    "title": "Series task 1",
                    "status": "open",
                    "series_id": "SERIES-001",
                    "archived": False,
                },
                "TASK-002": {
                    "title": "Series task 2",
                    "status": "open",
                    "series_id": "SERIES-001",
                    "archived": False,
                },
                "TASK-003": {
                    "title": "Independent task",
                    "status": "open",
                    "archived": False,
                },
            },
            "series": {
                "SERIES-001": {
                    "title_template": "Series task {date}",
                    "pattern": {"type": "daily", "interval": 1},
                    "start_date": "2026-07-01",
                    "end_date": "2026-07-31",
                    "task_ids": ["TASK-001", "TASK-002"],
                    "created": "2026-06-25T10:00:00",
                },
            },
        }))
        return cli_project

    def test_series_delete_removes_series_and_tasks(self, cli_runner, series_project):
        """Test that series delete removes series and its tasks."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(series_project),
            "series", "delete", "SERIES-001", "--force"
        ])

        assert result.exit_code == 0
        assert "Deleted" in result.output

        # Verify series and tasks are deleted
        json_file = series_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert "SERIES-001" not in data.get("series", {})
        assert "TASK-001" not in data["tasks"]
        assert "TASK-002" not in data["tasks"]
        # Independent task should remain
        assert "TASK-003" in data["tasks"]

    def test_series_delete_keep_tasks(self, cli_runner, series_project):
        """Test that series delete --keep-tasks keeps tasks."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(series_project),
            "series", "delete", "SERIES-001", "--keep-tasks", "--force"
        ])

        assert result.exit_code == 0
        assert "Deleted" in result.output
        assert "kept" in result.output.lower()

        # Verify series is deleted but tasks remain
        json_file = series_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert "SERIES-001" not in data.get("series", {})
        assert "TASK-001" in data["tasks"]
        assert "TASK-002" in data["tasks"]

    def test_series_delete_json_output(self, cli_runner, series_project):
        """Test that series delete outputs JSON when --json flag used."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(series_project),
            "series", "delete", "SERIES-001", "--json"
        ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["deleted_series"] == "SERIES-001"
        assert "deleted_tasks" in data

    def test_series_delete_nonexistent(self, cli_runner, series_project):
        """Test that series delete fails for nonexistent series."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(series_project),
            "series", "delete", "NONEXISTENT", "--force"
        ])

        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_series_delete_confirms_by_default(self, cli_runner, series_project):
        """Test that series delete prompts for confirmation by default."""
        from doxtr_doto.cli.main import cli

        # Without --force, should prompt and abort on 'n'
        result = cli_runner.invoke(cli, [
            "--config", str(series_project),
            "series", "delete", "SERIES-001"
        ], input="n\n")

        assert "Cancelled" in result.output or result.exit_code == 0

        # Series should still exist
        json_file = series_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert "SERIES-001" in data.get("series", {})


class TestDotoResolve:
    """Test the doto resolve command."""

    @pytest.fixture
    def conflict_project(self, cli_project):
        """Create a project with conflicts."""
        json_file = cli_project / ".doto" / "tasks.json"
        json_file.write_text(json.dumps({
            "version": 3,
            "updated": "2026-07-26T10:00:00",
            "tasks": {
                "TASK-001": {
                    "title": "Task with conflict",
                    "status": "open",
                    "priority": "medium",
                    "archived": False,
                    "_sync": {
                        "snapshot": {
                            "priority": "low",
                            "status": "open",
                        }
                    }
                },
                "TASK-002": {
                    "title": "Another task",
                    "status": "done",
                    "priority": "high",
                    "archived": False,
                },
            },
            "_conflicts": [
                {
                    "task_id": "TASK-001",
                    "field": "priority",
                    "base": "low",
                    "rst": "high",
                    "json": "medium",
                },
                {
                    "task_id": "TASK-001",
                    "field": "status",
                    "base": "open",
                    "rst": "in-progress",
                    "json": "blocked",
                },
            ],
            "series": {},
        }))
        return cli_project

    def test_resolve_list_shows_conflicts(self, cli_runner, conflict_project):
        """Test doto resolve --list shows conflicts."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(conflict_project),
            "resolve", "--list"
        ])

        assert result.exit_code == 0
        assert "TASK-001" in result.output
        assert "priority" in result.output

    def test_resolve_use_rst(self, cli_runner, conflict_project):
        """Test doto resolve TASK-ID --use-rst resolves using RST value."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(conflict_project),
            "resolve", "TASK-001", "--use-rst"
        ])

        assert result.exit_code == 0
        assert "Resolved" in result.output

        # Verify task was updated with RST values
        json_file = conflict_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert data["tasks"]["TASK-001"]["priority"] == "high"
        assert data["tasks"]["TASK-001"]["status"] == "in-progress"

    def test_resolve_use_json(self, cli_runner, conflict_project):
        """Test doto resolve TASK-ID --use-json resolves using JSON value."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(conflict_project),
            "resolve", "TASK-001", "--use-json"
        ])

        assert result.exit_code == 0
        assert "Resolved" in result.output

        # Verify task kept JSON values
        json_file = conflict_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert data["tasks"]["TASK-001"]["priority"] == "medium"
        assert data["tasks"]["TASK-001"]["status"] == "blocked"

    def test_resolve_specific_field_use_rst(self, cli_runner, conflict_project):
        """Test doto resolve TASK-ID --field priority --use-rst resolves specific field."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(conflict_project),
            "resolve", "TASK-001", "--field", "priority", "--use-rst"
        ])

        assert result.exit_code == 0
        assert "Resolved priority" in result.output

        # Verify only priority was changed
        json_file = conflict_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert data["tasks"]["TASK-001"]["priority"] == "high"
        # Status conflict should still exist (not resolved)
        assert any(
            c["field"] == "status" and c["task_id"] == "TASK-001"
            for c in data.get("_conflicts", [])
        )

    def test_resolve_no_conflicts_shows_message(self, cli_runner, cli_project):
        """Test doto resolve with no conflicts shows appropriate message."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(cli_project),
            "resolve", "--list"
        ])

        assert result.exit_code == 0
        assert "No conflicts found" in result.output

    def test_resolve_nonexistent_task(self, cli_runner, conflict_project):
        """Test doto resolve NONEXISTENT --use-rst shows error."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(conflict_project),
            "resolve", "NONEXISTENT", "--use-rst"
        ])

        assert result.exit_code == 0
        assert "No conflicts found for task NONEXISTENT" in result.output

    def test_resolve_json_output(self, cli_runner, conflict_project):
        """Test doto resolve --json outputs JSON format."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(conflict_project),
            "resolve", "--list", "--json"
        ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 2
        task_ids = [c["task_id"] for c in data]
        assert "TASK-001" in task_ids


class TestDotoReopen:
    """Test the doto reopen command."""

    @pytest.fixture
    def reopen_project(self, cli_project):
        """Create a project with archived tasks."""
        json_file = cli_project / ".doto" / "tasks.json"
        json_file.write_text(json.dumps({
            "version": 3,
            "updated": "2026-07-26T10:00:00",
            "tasks": {
                "TASK-001": {
                    "title": "Archived task",
                    "status": "done",
                    "priority": "high",
                    "archived": True,
                },
                "TASK-002": {
                    "title": "Another archived task",
                    "status": "done",
                    "priority": "low",
                    "archived": True,
                },
                "TASK-003": {
                    "title": "Active task",
                    "status": "open",
                    "priority": "medium",
                    "archived": False,
                },
            },
            "series": {},
        }))
        return cli_project

    def test_reopen_single_task(self, cli_runner, reopen_project):
        """Test doto reopen TASK-ID reopens archived task."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(reopen_project),
            "reopen", "TASK-001"
        ])

        assert result.exit_code == 0
        assert "Reopened TASK-001" in result.output

        json_file = reopen_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert data["tasks"]["TASK-001"]["archived"] is False
        assert data["tasks"]["TASK-001"]["status"] == "open"

    def test_reopen_with_custom_status(self, cli_runner, reopen_project):
        """Test doto reopen TASK-ID --status in-progress sets custom status."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(reopen_project),
            "reopen", "TASK-001", "--status", "in-progress"
        ])

        assert result.exit_code == 0
        assert "Reopened TASK-001" in result.output
        assert "in-progress" in result.output

        json_file = reopen_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert data["tasks"]["TASK-001"]["archived"] is False
        assert data["tasks"]["TASK-001"]["status"] == "in-progress"

    def test_reopen_with_file_option(self, cli_runner, reopen_project):
        """Test doto reopen TASK-ID --file path.rst sets target file."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(reopen_project),
            "reopen", "TASK-001", "--file", "tasks/backlog.rst"
        ])

        assert result.exit_code == 0
        assert "Reopened TASK-001" in result.output

        json_file = reopen_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert data["tasks"]["TASK-001"]["archived"] is False

    def test_reopen_multiple_tasks(self, cli_runner, reopen_project):
        """Test doto reopen TASK-1 TASK-2 reopens multiple tasks."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(reopen_project),
            "reopen", "TASK-001", "TASK-002"
        ])

        assert result.exit_code == 0
        assert "Reopened TASK-001" in result.output
        assert "Reopened TASK-002" in result.output

        json_file = reopen_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert data["tasks"]["TASK-001"]["archived"] is False
        assert data["tasks"]["TASK-002"]["archived"] is False

    def test_reopen_nonexistent_task(self, cli_runner, reopen_project):
        """Test doto reopen NONEXISTENT shows not found error."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(reopen_project),
            "reopen", "NONEXISTENT"
        ])

        assert result.exit_code == 0
        assert "not found" in result.output

    def test_reopen_active_task_shows_error(self, cli_runner, reopen_project):
        """Test doto reopen ACTIVE-TASK shows not archived error."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(reopen_project),
            "reopen", "TASK-003"
        ])

        assert result.exit_code == 0
        assert "not archived" in result.output

    def test_reopen_json_output(self, cli_runner, reopen_project):
        """Test doto reopen --json outputs JSON format."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(reopen_project),
            "reopen", "TASK-001", "--json"
        ])

        assert result.exit_code == 0
        # Extract JSON from output (may include success messages before JSON)
        output = result.output
        json_start = output.find("{")
        assert json_start != -1, "JSON output not found"
        data = json.loads(output[json_start:])
        assert "reopened" in data
        assert "TASK-001" in data["reopened"]


class TestDotoBulkUpdate:
    """Test the doto update command bulk update functionality."""

    @pytest.fixture
    def bulk_update_project(self, cli_project):
        """Create a project with multiple tasks for bulk update testing."""
        json_file = cli_project / ".doto" / "tasks.json"
        json_file.write_text(json.dumps({
            "version": 3,
            "updated": "2026-07-26T10:00:00",
            "tasks": {
                "TASK-001": {
                    "title": "High priority open task",
                    "status": "open",
                    "priority": "high",
                    "assignee": "alice",
                    "tags": ["feature"],
                    "due": "2025-01-01",
                    "archived": False,
                },
                "TASK-002": {
                    "title": "High priority in-progress task",
                    "status": "in-progress",
                    "priority": "high",
                    "assignee": "bob",
                    "tags": ["bug"],
                    "archived": False,
                },
                "TASK-003": {
                    "title": "Low priority open task",
                    "status": "open",
                    "priority": "low",
                    "assignee": "alice",
                    "tags": ["feature", "backend"],
                    "due": "2025-06-01",
                    "archived": False,
                },
                "TASK-004": {
                    "title": "Done task",
                    "status": "done",
                    "priority": "medium",
                    "assignee": "charlie",
                    "tags": [],
                    "archived": False,
                },
                "TASK-005": {
                    "title": "Archived task",
                    "status": "done",
                    "priority": "low",
                    "archived": True,
                },
            },
            "series": {},
        }))
        return cli_project

    def test_bulk_update_by_priority_filter(self, cli_runner, bulk_update_project):
        """Test bulk update with --filter-priority."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(bulk_update_project),
            "update", "--filter-priority", "high", "--status", "blocked", "--all", "--yes"
        ])

        assert result.exit_code == 0
        assert "Updated 2 task(s)" in result.output

        json_file = bulk_update_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert data["tasks"]["TASK-001"]["status"] == "blocked"
        assert data["tasks"]["TASK-002"]["status"] == "blocked"
        assert data["tasks"]["TASK-003"]["status"] == "open"  # low priority unchanged

    def test_bulk_update_by_status_filter(self, cli_runner, bulk_update_project):
        """Test bulk update with --filter-status."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(bulk_update_project),
            "update", "--filter-status", "open", "--priority", "critical", "--all", "--yes"
        ])

        assert result.exit_code == 0
        assert "Updated 2 task(s)" in result.output

        json_file = bulk_update_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert data["tasks"]["TASK-001"]["priority"] == "critical"
        assert data["tasks"]["TASK-003"]["priority"] == "critical"
        assert data["tasks"]["TASK-002"]["priority"] == "high"  # in-progress unchanged

    def test_bulk_update_by_assignee_filter(self, cli_runner, bulk_update_project):
        """Test bulk update with --filter-assignee."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(bulk_update_project),
            "update", "--filter-assignee", "alice", "--add-tags", "alice-tasks", "--all", "--yes"
        ])

        assert result.exit_code == 0
        assert "Updated 2 task(s)" in result.output

        json_file = bulk_update_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert "alice-tasks" in data["tasks"]["TASK-001"]["tags"]
        assert "alice-tasks" in data["tasks"]["TASK-003"]["tags"]
        assert "alice-tasks" not in data["tasks"]["TASK-002"].get("tags", [])

    def test_bulk_update_by_tags_filter(self, cli_runner, bulk_update_project):
        """Test bulk update with --filter-tags."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(bulk_update_project),
            "update", "--filter-tags", "feature", "--assignee", "dave", "--all", "--yes"
        ])

        assert result.exit_code == 0
        assert "Updated 2 task(s)" in result.output

        json_file = bulk_update_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert data["tasks"]["TASK-001"]["assignee"] == "dave"
        assert data["tasks"]["TASK-003"]["assignee"] == "dave"
        assert data["tasks"]["TASK-002"]["assignee"] == "bob"  # bug tag, unchanged

    def test_bulk_update_by_overdue_filter(self, cli_runner, bulk_update_project):
        """Test bulk update with --filter-overdue."""
        from doxtr_doto.cli.main import cli

        # TASK-001 has due date 2025-01-01 which should be overdue
        result = cli_runner.invoke(cli, [
            "--config", str(bulk_update_project),
            "update", "--filter-overdue", "--add-tags", "overdue", "--all", "--yes"
        ])

        assert result.exit_code == 0

        json_file = bulk_update_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        # TASK-001 is overdue (due 2025-01-01)
        assert "overdue" in data["tasks"]["TASK-001"]["tags"]

    def test_bulk_update_multiple_filters(self, cli_runner, bulk_update_project):
        """Test bulk update with multiple filters (AND logic)."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(bulk_update_project),
            "update", "--filter-status", "open", "--filter-priority", "high",
            "--status", "in-progress", "--all", "--yes"
        ])

        assert result.exit_code == 0
        assert "Updated 1 task(s)" in result.output

        json_file = bulk_update_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert data["tasks"]["TASK-001"]["status"] == "in-progress"  # open + high
        assert data["tasks"]["TASK-003"]["status"] == "open"  # low priority, unchanged

    def test_bulk_update_dry_run(self, cli_runner, bulk_update_project):
        """Test bulk update with --dry-run doesn't make changes."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(bulk_update_project),
            "update", "--filter-priority", "high", "--status", "blocked", "--all", "--dry-run"
        ])

        assert result.exit_code == 0
        assert "Dry run" in result.output
        assert "Would update 2 task(s)" in result.output
        assert "TASK-001" in result.output
        assert "TASK-002" in result.output

        # Verify no changes were made
        json_file = bulk_update_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert data["tasks"]["TASK-001"]["status"] == "open"  # unchanged
        assert data["tasks"]["TASK-002"]["status"] == "in-progress"  # unchanged

    def test_bulk_update_dry_run_json(self, cli_runner, bulk_update_project):
        """Test bulk update with --dry-run --json."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(bulk_update_project),
            "update", "--filter-priority", "high", "--status", "blocked",
            "--all", "--dry-run", "--json"
        ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["dry_run"] is True
        assert data["count"] == 2
        assert "TASK-001" in data["would_update"]
        assert "TASK-002" in data["would_update"]
        assert "status" in data["updates"]

    def test_bulk_update_requires_all_flag(self, cli_runner, bulk_update_project):
        """Test bulk update requires --all flag for safety."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(bulk_update_project),
            "update", "--filter-priority", "high", "--status", "blocked"
        ])

        assert result.exit_code != 0
        assert "--all flag is required" in result.output

    def test_bulk_update_rejects_edit_flag(self, cli_runner, bulk_update_project):
        """Test bulk update rejects --edit flag."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(bulk_update_project),
            "update", "--filter-priority", "high", "--edit", "--all"
        ])

        assert result.exit_code != 0
        assert "--edit flag cannot be used with bulk updates" in result.output

    def test_bulk_update_no_matching_tasks(self, cli_runner, bulk_update_project):
        """Test bulk update with no matching tasks."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(bulk_update_project),
            "update", "--filter-assignee", "nonexistent", "--status", "blocked", "--all"
        ])

        assert result.exit_code == 0
        assert "No tasks match the filter criteria" in result.output

    def test_bulk_update_excludes_archived(self, cli_runner, bulk_update_project):
        """Test bulk update excludes archived tasks."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(bulk_update_project),
            "update", "--filter-priority", "low", "--status", "blocked", "--all", "--yes"
        ])

        assert result.exit_code == 0
        # Only TASK-003 should be updated (TASK-005 is archived)
        assert "Updated 1 task(s)" in result.output

        json_file = bulk_update_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert data["tasks"]["TASK-003"]["status"] == "blocked"
        # Archived task should be unchanged
        assert data["tasks"]["TASK-005"]["status"] == "done"

    def test_bulk_update_json_output(self, cli_runner, bulk_update_project):
        """Test bulk update with --json output."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(bulk_update_project),
            "update", "--filter-priority", "high", "--status", "blocked",
            "--all", "--yes", "--json"
        ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["count"] == 2
        assert "TASK-001" in data["updated"]
        assert "TASK-002" in data["updated"]

    def test_bulk_update_confirmation_prompt(self, cli_runner, bulk_update_project):
        """Test bulk update shows confirmation for >5 tasks."""
        from doxtr_doto.cli.main import cli

        # Add more tasks to exceed threshold
        json_file = bulk_update_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        for i in range(6, 15):
            data["tasks"][f"TASK-{i:03d}"] = {
                "title": f"Task {i}",
                "status": "open",
                "priority": "medium",
                "archived": False,
            }
        json_file.write_text(json.dumps(data))

        # Reject the prompt
        result = cli_runner.invoke(cli, [
            "--config", str(bulk_update_project),
            "update", "--filter-status", "open", "--priority", "critical", "--all"
        ], input="n\n")

        assert result.exit_code == 0
        assert "Aborted" in result.output

        # Verify no changes were made
        data = json.loads(json_file.read_text())
        assert data["tasks"]["TASK-001"]["priority"] == "high"  # unchanged

    def test_bulk_update_confirmation_accepted(self, cli_runner, bulk_update_project):
        """Test bulk update proceeds when confirmation accepted."""
        from doxtr_doto.cli.main import cli

        # Add more tasks to exceed threshold
        json_file = bulk_update_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        for i in range(6, 15):
            data["tasks"][f"TASK-{i:03d}"] = {
                "title": f"Task {i}",
                "status": "open",
                "priority": "medium",
                "archived": False,
            }
        json_file.write_text(json.dumps(data))

        # Accept the prompt
        result = cli_runner.invoke(cli, [
            "--config", str(bulk_update_project),
            "update", "--filter-status", "open", "--priority", "critical", "--all"
        ], input="y\n")

        assert result.exit_code == 0
        assert "Updated" in result.output

    def test_single_update_rejects_filters(self, cli_runner, bulk_update_project):
        """Test single task update rejects filter options."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(bulk_update_project),
            "update", "TASK-001", "--filter-priority", "high", "--status", "done"
        ])

        assert result.exit_code != 0
        assert "Cannot use filter options" in result.output

    def test_single_update_still_works(self, cli_runner, bulk_update_project):
        """Test single task update still works as before."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(bulk_update_project),
            "update", "TASK-001", "--status", "done"
        ])

        assert result.exit_code == 0
        assert "Updated task TASK-001" in result.output

        json_file = bulk_update_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert data["tasks"]["TASK-001"]["status"] == "done"
        # Other tasks unchanged
        assert data["tasks"]["TASK-002"]["status"] == "in-progress"

    def test_bulk_update_requires_updates(self, cli_runner, bulk_update_project):
        """Test bulk update requires at least one update option."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, [
            "--config", str(bulk_update_project),
            "update", "--filter-priority", "high", "--all"
        ])

        assert result.exit_code != 0
        assert "No updates specified" in result.output


class TestParseRelativeDate:
    """Tests for date validation in parse_relative_date."""

    def test_valid_iso_date(self):
        """Valid YYYY-MM-DD dates are accepted."""
        from doxtr_doto.cli.commands.add import parse_relative_date
        assert parse_relative_date("2025-08-15") == "2025-08-15"
        assert parse_relative_date("2024-02-29") == "2024-02-29"  # Leap year

    def test_invalid_iso_date_rejected(self):
        """Invalid YYYY-MM-DD dates raise ValueError."""
        from doxtr_doto.cli.commands.add import parse_relative_date
        import pytest

        with pytest.raises(ValueError, match="Invalid date"):
            parse_relative_date("2025-13-45")  # Invalid month/day

        with pytest.raises(ValueError, match="Invalid date"):
            parse_relative_date("2025-00-15")  # Month 0 invalid

        with pytest.raises(ValueError, match="Invalid date"):
            parse_relative_date("2025-02-30")  # Feb 30 doesn't exist

        with pytest.raises(ValueError, match="Invalid date"):
            parse_relative_date("abcd-ef-gh")  # Not a date at all

    def test_relative_dates_work(self):
        """Relative date formats work correctly."""
        from doxtr_doto.cli.commands.add import parse_relative_date
        from datetime import date, timedelta

        today = date.today()

        assert parse_relative_date("today") == today.isoformat()
        assert parse_relative_date("tomorrow") == (today + timedelta(days=1)).isoformat()
        assert parse_relative_date("+7d") == (today + timedelta(days=7)).isoformat()
        assert parse_relative_date("+2w") == (today + timedelta(weeks=2)).isoformat()
