"""Tests for standalone (non-Sphinx) operation mode."""
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
def standalone_store(tmp_path):
    """A JSON store at an explicit path for standalone mode testing."""
    store_file = tmp_path / "my-tasks.json"
    store_file.write_text(json.dumps({"version": 2, "tasks": {}}))
    return store_file


class TestStandaloneAddAndList:
    """Tests for basic add and list operations in standalone mode."""

    def test_standalone_add_and_list(self, runner, standalone_store):
        """Add a task with --json flag, then list it."""
        result = runner.invoke(
            cli,
            [
                "--json",
                str(standalone_store),
                "add",
                "Standalone task",
                "--priority",
                "high",
            ],
        )
        assert result.exit_code == 0

        result = runner.invoke(cli, ["--json", str(standalone_store), "list"])
        assert result.exit_code == 0
        assert "Standalone task" in result.output

    def test_standalone_add_with_all_options(self, runner, standalone_store):
        """Add a task with all available options."""
        result = runner.invoke(
            cli,
            [
                "--json",
                str(standalone_store),
                "add",
                "Full options task",
                "--id",
                "CUSTOM-001",
                "--priority",
                "critical",
                "--status",
                "in-progress",
                "--assignee",
                "alice",
                "--tags",
                "urgent,backend",
            ],
        )
        assert result.exit_code == 0

        data = json.loads(standalone_store.read_text())
        assert "CUSTOM-001" in data["tasks"]
        task = data["tasks"]["CUSTOM-001"]
        assert task["title"] == "Full options task"
        assert task["priority"] == "critical"
        assert task["status"] == "in-progress"
        assert task["assignee"] == "alice"
        assert task["tags"] == ["urgent", "backend"]


class TestStandaloneWithoutConfPy:
    """Tests for CLI operation without Sphinx conf.py."""

    def test_standalone_mode_does_not_require_conf_py(
        self, runner, standalone_store, tmp_path
    ):
        """CLI works from a directory with no conf.py or .doto.toml."""
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli,
                ["--json", str(standalone_store), "list"],
            )
            assert result.exit_code == 0

    def test_standalone_works_in_empty_directory(self, runner, tmp_path):
        """CLI works when invoked from an empty directory with explicit --json."""
        store_file = tmp_path / "tasks.json"
        store_file.write_text(json.dumps({"version": 2, "tasks": {}}))

        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        with runner.isolated_filesystem(temp_dir=empty_dir):
            result = runner.invoke(
                cli,
                ["--json", str(store_file), "list"],
            )
            assert result.exit_code == 0


class TestStandaloneStoreCreation:
    """Tests for automatic store creation."""

    def test_standalone_store_is_created_if_absent(self, runner, tmp_path):
        """Using --json with a non-existent file creates it on first write."""
        new_store = tmp_path / "brand-new.json"
        assert not new_store.exists()

        result = runner.invoke(
            cli,
            ["--json", str(new_store), "add", "First task"],
        )
        assert result.exit_code == 0
        assert new_store.exists()

        data = json.loads(new_store.read_text())
        assert len(data["tasks"]) == 1

    def test_standalone_store_created_with_correct_schema(self, runner, tmp_path):
        """New store is created with correct schema version."""
        new_store = tmp_path / "new-store.json"

        runner.invoke(
            cli,
            ["--json", str(new_store), "add", "Schema test task"],
        )

        data = json.loads(new_store.read_text())
        assert "version" in data
        assert data["version"] >= 2  # Minimum expected schema version


class TestStandaloneJsonOutput:
    """Tests for JSON output format in standalone mode."""

    def test_standalone_list_json_format(self, runner, standalone_store):
        """list --format json outputs valid JSON."""
        runner.invoke(
            cli,
            ["--json", str(standalone_store), "add", "JSON output test"],
        )
        result = runner.invoke(
            cli,
            ["--json", str(standalone_store), "list", "--format", "json"],
        )
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert isinstance(parsed, list)
        assert len(parsed) == 1
        assert parsed[0]["title"] == "JSON output test"

    def test_standalone_show_json_format(self, runner, standalone_store):
        """show --json outputs valid JSON for a single task."""
        runner.invoke(
            cli,
            ["--json", str(standalone_store), "add", "Show test", "--id", "TEST-001"],
        )
        result = runner.invoke(
            cli,
            ["--json", str(standalone_store), "show", "TEST-001", "--json"],
        )
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["id"] == "TEST-001"
        assert parsed["title"] == "Show test"


class TestStandaloneOperations:
    """Tests for various CLI operations in standalone mode."""

    @pytest.fixture
    def populated_standalone_store(self, tmp_path):
        """A standalone store with some tasks."""
        store_file = tmp_path / "tasks.json"
        data = {
            "version": 2,
            "tasks": {
                "TASK-001": {
                    "title": "Task one",
                    "status": "open",
                    "priority": "high",
                    "archived": False,
                },
                "TASK-002": {
                    "title": "Task two",
                    "status": "in-progress",
                    "priority": "medium",
                    "archived": False,
                },
                "TASK-003": {
                    "title": "Task three",
                    "status": "done",
                    "priority": "low",
                    "archived": False,
                },
            },
        }
        store_file.write_text(json.dumps(data))
        return store_file

    def test_standalone_update(self, runner, populated_standalone_store):
        """update command works in standalone mode."""
        result = runner.invoke(
            cli,
            [
                "--json",
                str(populated_standalone_store),
                "update",
                "TASK-001",
                "--status",
                "in-progress",
            ],
        )
        assert result.exit_code == 0

        data = json.loads(populated_standalone_store.read_text())
        assert data["tasks"]["TASK-001"]["status"] == "in-progress"

    def test_standalone_done(self, runner, populated_standalone_store):
        """done command works in standalone mode."""
        result = runner.invoke(
            cli,
            ["--json", str(populated_standalone_store), "done", "TASK-001"],
        )
        assert result.exit_code == 0

        data = json.loads(populated_standalone_store.read_text())
        assert data["tasks"]["TASK-001"]["status"] == "done"

    def test_standalone_search(self, runner, populated_standalone_store):
        """search command works in standalone mode."""
        result = runner.invoke(
            cli,
            ["--json", str(populated_standalone_store), "search", "one"],
        )
        assert result.exit_code == 0
        assert "TASK-001" in result.output

    def test_standalone_filter_by_status(self, runner, populated_standalone_store):
        """list --status filter works in standalone mode."""
        result = runner.invoke(
            cli,
            ["--json", str(populated_standalone_store), "list", "--status", "open"],
        )
        assert result.exit_code == 0
        assert "TASK-001" in result.output
        assert "TASK-002" not in result.output  # in-progress, not open
        assert "TASK-003" not in result.output  # done


class TestStandaloneConfigCommand:
    """Tests for config command in standalone mode."""

    def test_standalone_config_shows_mode(self, runner, standalone_store):
        """config command shows standalone mode."""
        result = runner.invoke(
            cli,
            ["--json", str(standalone_store), "config"],
        )
        assert result.exit_code == 0
        # Should show the JSON path being used
        assert "my-tasks.json" in result.output or "Mode" in result.output


class TestStandaloneNestedPath:
    """Tests for standalone stores in nested paths."""

    def test_standalone_store_in_nested_directory(self, runner, tmp_path):
        """--json flag works with nested directory paths."""
        nested_store = tmp_path / "data" / "tasks" / "store.json"
        # Parent directories don't exist yet

        result = runner.invoke(
            cli,
            ["--json", str(nested_store), "add", "Nested path task"],
        )
        assert result.exit_code == 0
        assert nested_store.exists()

        data = json.loads(nested_store.read_text())
        assert len(data["tasks"]) == 1
