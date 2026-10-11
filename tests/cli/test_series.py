"""Tests for doto series command - Additional edge cases.

Supplements the tests in test_commands.py with additional edge cases
for series listing, showing, extension, and deletion.
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
    config_file.write_text("""
[doto]
json_file = ".doto/tasks.json"
id_prefix = "TEST"
""")

    json_file = doto_dir / "tasks.json"
    json_file.write_text(
        json.dumps(
            {
                "version": 2,
                "updated": "2026-07-26T10:00:00",
                "tasks": {},
                "series": {},
            }
        )
    )

    return tmp_path


class TestSeriesListFiltering:
    """Tests for series list filtering."""

    @pytest.fixture
    def multi_series_project(self, cli_project):
        """Create a project with multiple series."""
        json_file = cli_project / ".doto" / "tasks.json"
        json_file.write_text(
            json.dumps(
                {
                    "version": 3,
                    "updated": "2026-07-26T10:00:00",
                    "tasks": {
                        "T1": {
                            "title": "S1 Task",
                            "series_id": "S1",
                            "status": "open",
                            "archived": False,
                        },
                        "T2": {
                            "title": "S2 Task",
                            "series_id": "S2",
                            "status": "done",
                            "archived": False,
                        },
                        "T3": {
                            "title": "S3 Task",
                            "series_id": "S3",
                            "status": "open",
                            "archived": True,
                        },
                    },
                    "series": {
                        "S1": {
                            "title_template": "Active daily",
                            "pattern": {"type": "daily"},
                            "start_date": "2026-07-01",
                            "end_date": "2026-12-31",
                            "task_ids": ["T1"],
                            "created": "2026-06-01T10:00:00",
                        },
                        "S2": {
                            "title_template": "Completed series",
                            "pattern": {"type": "weekly"},
                            "start_date": "2026-01-01",
                            "end_date": "2026-06-30",
                            "task_ids": ["T2"],
                            "created": "2026-01-01T10:00:00",
                        },
                        "S3": {
                            "title_template": "Archived series",
                            "pattern": {"type": "monthly"},
                            "start_date": "2025-01-01",
                            "end_date": "2025-12-31",
                            "task_ids": ["T3"],
                            "created": "2025-01-01T10:00:00",
                            "archived": True,
                        },
                    },
                }
            )
        )
        return cli_project

    def test_series_list_shows_active(self, cli_runner, multi_series_project):
        """Series list shows active series by default."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, ["--config", str(multi_series_project), "series", "list"])

        assert result.exit_code == 0
        assert "S1" in result.output
        assert "S2" in result.output

    def test_series_list_json(self, cli_runner, multi_series_project):
        """Series list JSON output."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(
            cli, ["--config", str(multi_series_project), "series", "list", "--json"]
        )

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "series" in data
        assert len(data["series"]) >= 2


class TestSeriesTaskRelationship:
    """Tests for series-task relationships."""

    @pytest.fixture
    def related_project(self, cli_project):
        """Create a project with series and related tasks."""
        json_file = cli_project / ".doto" / "tasks.json"
        json_file.write_text(
            json.dumps(
                {
                    "version": 3,
                    "updated": "2026-07-26T10:00:00",
                    "tasks": {
                        "SERIES-TASK-001": {
                            "title": "Series task 1",
                            "status": "done",
                            "due": "2026-07-01",
                            "series_id": "SERIES-001",
                            "archived": False,
                        },
                        "SERIES-TASK-002": {
                            "title": "Series task 2",
                            "status": "in-progress",
                            "due": "2026-07-02",
                            "series_id": "SERIES-001",
                            "archived": False,
                        },
                        "SERIES-TASK-003": {
                            "title": "Series task 3",
                            "status": "open",
                            "due": "2026-07-03",
                            "series_id": "SERIES-001",
                            "archived": False,
                        },
                        "STANDALONE-001": {
                            "title": "Standalone task",
                            "status": "open",
                            "archived": False,
                        },
                    },
                    "series": {
                        "SERIES-001": {
                            "title_template": "Series task {n}",
                            "pattern": {"type": "daily", "interval": 1},
                            "start_date": "2026-07-01",
                            "end_date": "2026-07-03",
                            "task_ids": ["SERIES-TASK-001", "SERIES-TASK-002", "SERIES-TASK-003"],
                            "created": "2026-06-25T10:00:00",
                        },
                    },
                }
            )
        )
        return cli_project

    def test_series_show_task_statuses(self, cli_runner, related_project):
        """Series show displays task status breakdown."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(
            cli, ["--config", str(related_project), "series", "show", "SERIES-001"]
        )

        assert result.exit_code == 0
        # Should show status breakdown
        assert "SERIES-001" in result.output or "Series task" in result.output

    def test_series_show_json_includes_tasks(self, cli_runner, related_project):
        """Series show JSON includes task details."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(
            cli, ["--config", str(related_project), "series", "show", "SERIES-001", "--json"]
        )

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "tasks" in data
        assert len(data["tasks"]) == 3


class TestSeriesEdgeCases:
    """Tests for series edge cases."""

    def test_series_empty_project(self, cli_runner, cli_project):
        """Series list on empty project."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, ["--config", str(cli_project), "series", "list"])

        assert result.exit_code == 0
        assert "No series found" in result.output

    def test_series_show_nonexistent(self, cli_runner, cli_project):
        """Series show for nonexistent series."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(
            cli, ["--config", str(cli_project), "series", "show", "NONEXISTENT"]
        )

        assert result.exit_code != 0
        assert "not found" in result.output.lower()


class TestSeriesExtend:
    """Tests for series extension."""

    @pytest.fixture
    def series_project(self, cli_project):
        """Create a project with an existing series."""
        json_file = cli_project / ".doto" / "tasks.json"
        json_file.write_text(
            json.dumps(
                {
                    "version": 3,
                    "updated": "2026-07-26T10:00:00",
                    "tasks": {
                        "TASK-001": {
                            "title": "Daily task - 2026-07-01",
                            "status": "done",
                            "due": "2026-07-01",
                            "series_id": "SERIES-001",
                            "archived": False,
                        },
                        "TASK-002": {
                            "title": "Daily task - 2026-07-02",
                            "status": "open",
                            "due": "2026-07-02",
                            "series_id": "SERIES-001",
                            "archived": False,
                        },
                    },
                    "series": {
                        "SERIES-001": {
                            "title_template": "Daily task - {date}",
                            "pattern": {"type": "daily", "interval": 1},
                            "start_date": "2026-07-01",
                            "end_date": "2026-07-02",
                            "task_ids": ["TASK-001", "TASK-002"],
                            "created": "2026-06-25T10:00:00",
                        },
                    },
                }
            )
        )
        return cli_project

    def test_series_extend(self, cli_runner, series_project):
        """Test extending a series."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(
            cli,
            [
                "--config",
                str(series_project),
                "series",
                "extend",
                "SERIES-001",
                "2026-07-05",
            ],
        )

        assert result.exit_code == 0
        assert "Extended" in result.output or "extended" in result.output.lower()

        # Verify new tasks were created
        json_file = series_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        series = data["series"]["SERIES-001"]
        assert series["end_date"] == "2026-07-05"
        assert len(series["task_ids"]) > 2

    def test_series_extend_nonexistent(self, cli_runner, series_project):
        """Test extending nonexistent series."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(
            cli,
            [
                "--config",
                str(series_project),
                "series",
                "extend",
                "NONEXISTENT",
                "2026-07-10",
            ],
        )

        assert result.exit_code != 0
        assert "not found" in result.output.lower()


class TestSeriesDeleteBehavior:
    """Tests for series deletion behavior."""

    @pytest.fixture
    def delete_project(self, cli_project):
        """Create a project for delete testing."""
        json_file = cli_project / ".doto" / "tasks.json"
        json_file.write_text(
            json.dumps(
                {
                    "version": 3,
                    "updated": "2026-07-26T10:00:00",
                    "tasks": {
                        "ST-001": {
                            "title": "Series task 1",
                            "status": "done",
                            "series_id": "S1",
                            "archived": False,
                        },
                        "ST-002": {
                            "title": "Series task 2",
                            "status": "open",
                            "series_id": "S1",
                            "archived": False,
                        },
                        "INDEP-001": {
                            "title": "Independent task",
                            "status": "open",
                            "archived": False,
                        },
                    },
                    "series": {
                        "S1": {
                            "title_template": "Series task",
                            "pattern": {"type": "daily"},
                            "start_date": "2026-07-01",
                            "end_date": "2026-07-02",
                            "task_ids": ["ST-001", "ST-002"],
                            "created": "2026-06-25T10:00:00",
                        },
                    },
                }
            )
        )
        return cli_project

    def test_series_delete_with_force(self, cli_runner, delete_project):
        """Series delete --force removes without confirmation."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(
            cli, ["--config", str(delete_project), "series", "delete", "S1", "--force"]
        )

        assert result.exit_code == 0

        # Verify deletion
        json_file = delete_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert "S1" not in data.get("series", {})
        assert "ST-001" not in data["tasks"]
        assert "ST-002" not in data["tasks"]
        assert "INDEP-001" in data["tasks"]  # Independent task preserved

    def test_series_delete_keep_tasks_option(self, cli_runner, delete_project):
        """Series delete --keep-tasks preserves tasks."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(
            cli,
            ["--config", str(delete_project), "series", "delete", "S1", "--keep-tasks", "--force"],
        )

        assert result.exit_code == 0

        # Verify series deleted but tasks preserved
        json_file = delete_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert "S1" not in data.get("series", {})
        assert "ST-001" in data["tasks"]
        assert "ST-002" in data["tasks"]

    def test_series_delete_nonexistent(self, cli_runner, delete_project):
        """Series delete for nonexistent series."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(
            cli, ["--config", str(delete_project), "series", "delete", "NONEXISTENT", "--force"]
        )

        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_series_delete_with_yes_flag(self, cli_runner, delete_project):
        """Series delete --yes removes without confirmation (preferred over --force)."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(
            cli, ["--config", str(delete_project), "series", "delete", "S1", "--yes"]
        )

        assert result.exit_code == 0

        # Verify deletion
        json_file = delete_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert "S1" not in data.get("series", {})
        assert "ST-001" not in data["tasks"]
        assert "ST-002" not in data["tasks"]

    def test_series_delete_with_y_flag(self, cli_runner, delete_project):
        """Series delete -y removes without confirmation."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(
            cli, ["--config", str(delete_project), "series", "delete", "S1", "-y"]
        )

        assert result.exit_code == 0

        json_file = delete_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert "S1" not in data.get("series", {})

    def test_series_delete_prompts_for_confirmation(self, cli_runner, delete_project):
        """Series delete prompts for confirmation without --yes or --force."""
        from doxtr_doto.cli.main import cli

        # Decline confirmation
        result = cli_runner.invoke(
            cli, ["--config", str(delete_project), "series", "delete", "S1"], input="n\n"
        )

        assert result.exit_code == 0
        assert "Cancelled" in result.output

        # Verify series was NOT deleted
        json_file = delete_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert "S1" in data.get("series", {})
        assert "ST-001" in data["tasks"]

    def test_series_delete_with_confirmation(self, cli_runner, delete_project):
        """Series delete with user confirmation."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(
            cli, ["--config", str(delete_project), "series", "delete", "S1"], input="y\n"
        )

        assert result.exit_code == 0

        json_file = delete_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert "S1" not in data.get("series", {})


class TestSeriesComplete:
    """Tests for series complete command."""

    @pytest.fixture
    def complete_project(self, cli_project):
        """Create a project with series tasks to complete."""
        json_file = cli_project / ".doto" / "tasks.json"
        json_file.write_text(
            json.dumps(
                {
                    "version": 3,
                    "updated": "2026-07-26T10:00:00",
                    "tasks": {
                        "PAST-001": {
                            "title": "Past task 1",
                            "status": "open",
                            "due": "2020-07-01",
                            "series_id": "S1",
                            "archived": False,
                        },
                        "PAST-002": {
                            "title": "Past task 2",
                            "status": "open",
                            "due": "2020-07-02",
                            "series_id": "S1",
                            "archived": False,
                        },
                        "FUTURE-001": {
                            "title": "Future task",
                            "status": "open",
                            "due": "2099-12-31",
                            "series_id": "S1",
                            "archived": False,
                        },
                    },
                    "series": {
                        "S1": {
                            "title_template": "Task {date}",
                            "pattern": {"type": "daily"},
                            "start_date": "2020-07-01",
                            "end_date": "2099-12-31",
                            "task_ids": ["PAST-001", "PAST-002", "FUTURE-001"],
                            "created": "2020-06-25T10:00:00",
                        },
                    },
                }
            )
        )
        return cli_project

    def test_series_complete_marks_past_done(self, cli_runner, complete_project):
        """Series complete marks past tasks as done."""
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(
            cli, ["--config", str(complete_project), "series", "complete", "S1"]
        )

        assert result.exit_code == 0

        # Verify past tasks are done, future task still open
        json_file = complete_project / ".doto" / "tasks.json"
        data = json.loads(json_file.read_text())
        assert data["tasks"]["PAST-001"]["status"] == "done"
        assert data["tasks"]["PAST-002"]["status"] == "done"
        assert data["tasks"]["FUTURE-001"]["status"] == "open"
