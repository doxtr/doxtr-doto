"""Tests for ``doto add --repeat`` with ``--from``, start time and duration.

Covers the series-with-time/duration feature: the pattern's ``at HH:MM`` /
``for <duration>`` suffixes, the ``--from`` start-date flag, and the related
validation errors, exercised end-to-end through the CLI.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from doxtr_doto.cli.main import cli


@pytest.fixture
def cli_runner():
    """Create a CLI runner."""
    return CliRunner()


@pytest.fixture
def add_project(tmp_path):
    """Create a minimal project for add command testing."""
    doto_dir = tmp_path / ".doto"
    doto_dir.mkdir()
    (doto_dir / "tasks.json").write_text(
        json.dumps(
            {
                "version": 3,
                "updated": "2026-01-01T00:00:00",
                "tasks": {},
                "series": {},
            }
        )
    )
    return tmp_path


def _load(project):
    """Load the project's tasks.json."""
    return json.loads((project / ".doto" / "tasks.json").read_text())


class TestAddSeriesTimeDuration:
    """Tests for the ``at`` / ``for`` pattern suffixes via ``doto add``."""

    def test_target_command(self, cli_runner, add_project):
        """The feature's exact target command creates a time-bearing series.

        ``doto add "Important Sync Meeting"
          --repeat "every 2 weeks on monday at 16:00 for 2h"
          --from 2026-11-01 -u 2027-10-10``
        """
        result = cli_runner.invoke(
            cli,
            [
                "--config",
                str(add_project),
                "add",
                "Important Sync Meeting",
                "--repeat",
                "every 2 weeks on monday at 16:00 for 2h",
                "--from",
                "2026-11-01",
                "-u",
                "2027-10-10",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Created series" in result.output

        data = _load(add_project)
        assert len(data["series"]) == 1
        series = next(iter(data["series"].values()))
        assert series["start_date"] == "2026-11-01"
        assert series["end_date"] == "2027-10-10"
        assert series["pattern"]["start_time"] == "16:00"
        assert series["pattern"]["duration_minutes"] == 120

        # Every generated task carries the time-bearing due + estimate.
        tasks = list(data["tasks"].values())
        assert tasks, "expected generated tasks"
        for task in tasks:
            assert task["due"].endswith("T16:00")
            assert task["estimate"] == 120
        # First occurrence is the Monday on/after the from date.
        first = min(tasks, key=lambda t: t["due"])
        assert first["due"] == "2026-11-02T16:00"

    def test_time_only(self, cli_runner, add_project):
        """A pattern with only ``at`` gives time-bearing dues, no estimate."""
        result = cli_runner.invoke(
            cli,
            [
                "--config",
                str(add_project),
                "add",
                "Standup",
                "--repeat",
                "every day at 09:00",
                "--from",
                "2026-11-01",
                "-u",
                "2026-11-03",
            ],
        )
        assert result.exit_code == 0, result.output
        tasks = list(_load(add_project)["tasks"].values())
        assert len(tasks) == 3
        for task in tasks:
            assert task["due"].endswith("T09:00")
            assert "estimate" not in task or task.get("estimate") is None

    def test_from_defaults_to_today_when_absent(self, cli_runner, add_project):
        """Without --from the series still starts today (backward compatible)."""
        from datetime import date, timedelta

        end = (date.today() + timedelta(days=5)).isoformat()
        result = cli_runner.invoke(
            cli,
            [
                "--config",
                str(add_project),
                "add",
                "Daily",
                "--repeat",
                "every day",
                "-u",
                end,
            ],
        )
        assert result.exit_code == 0, result.output
        series = next(iter(_load(add_project)["series"].values()))
        assert series["start_date"] == date.today().isoformat()


class TestAddSeriesValidation:
    """Tests for the new ``--from`` validation errors."""

    def test_from_without_repeat_is_usage_error(self, cli_runner, add_project):
        """--from without --repeat is a usage error."""
        result = cli_runner.invoke(
            cli,
            [
                "--config",
                str(add_project),
                "add",
                "Task",
                "--from",
                "2026-11-01",
            ],
        )
        assert result.exit_code != 0
        assert "--from" in result.output and "--repeat" in result.output

    def test_end_before_start_is_error(self, cli_runner, add_project):
        """--until before the resolved --from start is an error."""
        result = cli_runner.invoke(
            cli,
            [
                "--config",
                str(add_project),
                "add",
                "Task",
                "--repeat",
                "every day",
                "--from",
                "2026-11-10",
                "-u",
                "2026-11-01",
            ],
        )
        assert result.exit_code != 0
        assert "after" in result.output.lower()

    def test_dry_run_shows_time_in_describe(self, cli_runner, add_project):
        """--dry-run previews the pattern description with at/for."""
        result = cli_runner.invoke(
            cli,
            [
                "--config",
                str(add_project),
                "add",
                "Sync",
                "--repeat",
                "every monday at 16:00 for 2h",
                "--from",
                "2026-11-01",
                "-u",
                "2026-11-30",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "at 16:00 for 2h" in result.output
        # Dry run writes nothing.
        assert _load(add_project)["series"] == {}
