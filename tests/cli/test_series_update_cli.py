"""Tests for the ``doto series update`` CLI command.

Exercises the mutating paths (--repeat / --at / --for / --title), the --from
anchor by task id and by date, --metadata-only, the mutually-exclusive flag
errors, the "nothing to update" error, the unknown-series error and dry-run.
Mirrors the fixtures/style of ``tests/cli/test_series.py``.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner


@pytest.fixture
def cli_runner():
    return CliRunner()


@pytest.fixture
def series_project(tmp_path):
    """A doto project with one weekly series of four open occurrences."""
    doto_dir = tmp_path / ".doto"
    doto_dir.mkdir()
    (tmp_path / ".doto.toml").write_text(
        '[doto]\njson_file = ".doto/tasks.json"\nid_prefix = "TEST"\n'
    )
    data = {
        "version": 5,
        "updated": "2026-01-01T00:00:00",
        "tasks": {
            "TEST-1": {"title": "W1", "series_id": "SER-1", "status": "open", "due": "2026-01-05"},
            "TEST-2": {"title": "W2", "series_id": "SER-1", "status": "open", "due": "2026-01-12"},
            "TEST-3": {"title": "W3", "series_id": "SER-1", "status": "open", "due": "2026-01-19"},
            "TEST-4": {"title": "W4", "series_id": "SER-1", "status": "open", "due": "2026-01-26"},
        },
        "series": {
            "SER-1": {
                "title_template": "Weekly",
                "pattern": {
                    "type": "weekly",
                    "interval": 1,
                    "weekday": 0,
                    "day_of_month": None,
                    "weekday_position": None,
                    "start_time": None,
                    "duration_minutes": None,
                },
                "start_date": "2026-01-05",
                "end_date": "2026-01-26",
                "task_ids": ["TEST-1", "TEST-2", "TEST-3", "TEST-4"],
                "task_defaults": {},
                "created": "2026-01-01T00:00:00",
            }
        },
    }
    (doto_dir / "tasks.json").write_text(json.dumps(data))
    return tmp_path


def _invoke(cli_runner, project, *args):
    from doxtr_doto.cli.main import cli

    return cli_runner.invoke(cli, ["--config", str(project), "series", "update", *args])


def _load(project):
    return json.loads((project / ".doto" / "tasks.json").read_text())


class TestSeriesUpdateCLI:
    def test_repeat_and_time_from_task_id(self, cli_runner, series_project):
        """--repeat + --at/--for anchored by a task id re-stamps forward."""
        result = _invoke(
            cli_runner,
            series_project,
            "SER-1",
            "--from",
            "TEST-2",
            "--at",
            "16:00",
            "--for",
            "2h",
        )
        assert result.exit_code == 0, result.output
        data = _load(series_project)
        # TEST-1 (before anchor) unchanged; TEST-2..4 re-stamped.
        assert "T" not in data["tasks"]["TEST-1"]["due"]
        assert data["tasks"]["TEST-2"]["due"].endswith("T16:00")
        assert data["tasks"]["TEST-2"]["estimate"] == 120
        assert data["tasks"]["TEST-4"]["estimate"] == 120

    def test_from_by_date(self, cli_runner, series_project):
        """--from accepts a date directly."""
        result = _invoke(
            cli_runner, series_project, "SER-1", "--from", "2026-01-19", "--for", "30m"
        )
        assert result.exit_code == 0, result.output
        data = _load(series_project)
        assert data["tasks"]["TEST-2"].get("estimate") is None
        assert data["tasks"]["TEST-3"]["estimate"] == 30
        assert data["tasks"]["TEST-4"]["estimate"] == 30

    def test_repeat_changes_pattern_shape_keeps_dates(self, cli_runner, series_project):
        """--repeat replaces the calendar shape but keeps existing due dates."""
        result = _invoke(
            cli_runner,
            series_project,
            "SER-1",
            "--from",
            "TEST-1",
            "--repeat",
            "every 2 weeks on monday",
        )
        assert result.exit_code == 0, result.output
        data = _load(series_project)
        # Stored pattern shape changed to biweekly.
        assert data["series"]["SER-1"]["pattern"]["interval"] == 2
        # Existing due *dates* are kept (shape change does not move/add dates).
        assert data["tasks"]["TEST-1"]["due"].startswith("2026-01-05")
        assert data["tasks"]["TEST-2"]["due"].startswith("2026-01-12")
        assert data["tasks"]["TEST-4"]["due"].startswith("2026-01-26")

    def test_title_update(self, cli_runner, series_project):
        result = _invoke(
            cli_runner, series_project, "SER-1", "--from", "TEST-1", "--title", "Renamed"
        )
        assert result.exit_code == 0, result.output
        data = _load(series_project)
        assert data["series"]["SER-1"]["title_template"] == "Renamed"
        assert data["tasks"]["TEST-1"]["title"] == "Renamed"

    def test_metadata_only(self, cli_runner, series_project):
        """--metadata-only updates the stored pattern but no tasks."""
        result = _invoke(cli_runner, series_project, "SER-1", "--metadata-only", "--at", "09:00")
        assert result.exit_code == 0, result.output
        data = _load(series_project)
        assert data["series"]["SER-1"]["pattern"]["start_time"] == "09:00"
        # No task re-stamped.
        assert "T" not in data["tasks"]["TEST-1"]["due"]

    def test_at_and_no_time_mutually_exclusive(self, cli_runner, series_project):
        result = _invoke(
            cli_runner,
            series_project,
            "SER-1",
            "--from",
            "TEST-1",
            "--at",
            "16:00",
            "--no-time",
        )
        assert result.exit_code != 0
        assert "mutually exclusive" in result.output

    def test_for_and_no_duration_mutually_exclusive(self, cli_runner, series_project):
        result = _invoke(
            cli_runner,
            series_project,
            "SER-1",
            "--from",
            "TEST-1",
            "--for",
            "2h",
            "--no-duration",
        )
        assert result.exit_code != 0
        assert "mutually exclusive" in result.output

    def test_nothing_to_update(self, cli_runner, series_project):
        result = _invoke(cli_runner, series_project, "SER-1", "--from", "TEST-1")
        assert result.exit_code != 0
        assert "nothing to update" in result.output

    def test_unknown_series(self, cli_runner, series_project):
        result = _invoke(cli_runner, series_project, "NOPE", "--from", "TEST-1", "--for", "2h")
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_from_required_without_metadata_only(self, cli_runner, series_project):
        result = _invoke(cli_runner, series_project, "SER-1", "--for", "2h")
        assert result.exit_code != 0
        assert "--from is required" in result.output

    def test_dry_run_is_noop(self, cli_runner, series_project):
        before = _load(series_project)
        result = _invoke(
            cli_runner,
            series_project,
            "SER-1",
            "--from",
            "TEST-1",
            "--for",
            "2h",
            "--dry-run",
        )
        assert result.exit_code == 0, result.output
        after = _load(series_project)
        assert after["tasks"] == before["tasks"]
        assert after["series"] == before["series"]

    def test_json_output(self, cli_runner, series_project):
        result = _invoke(
            cli_runner,
            series_project,
            "SER-1",
            "--from",
            "TEST-2",
            "--for",
            "2h",
            "--json",
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["series_id"] == "SER-1"
        assert payload["anchor"] == "2026-01-12"
        assert set(payload["updated_tasks"]) == {"TEST-2", "TEST-3", "TEST-4"}
        assert payload["skipped_before_anchor"] == 1
        assert payload["dry_run"] is False
