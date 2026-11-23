"""Tests for the ``doto leave`` command and leave-aware ``doto report`` output."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from doxtr_doto.cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def store_file(tmp_path):
    store_path = tmp_path / "repoA" / ".doto" / "tasks.json"
    store_path.parent.mkdir(parents=True)
    store_path.write_text(
        json.dumps(
            {
                "version": 5,
                "updated": "2024-01-01T00:00:00",
                "tasks": {},
                "series": {},
            }
        )
    )
    return store_path


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    """Point the global config at an explicit, isolated path via $DOTO_CONFIG."""
    cfg = tmp_path / "config.json"
    monkeypatch.setenv("DOTO_CONFIG", str(cfg))
    monkeypatch.chdir(tmp_path)
    return cfg


def _invoke(runner, store_file, *args):
    return runner.invoke(cli, ["--json", str(store_file), *args])


def test_leave_add_single_day(runner, store_file, config_path):
    result = _invoke(runner, store_file, "leave", "add", "2026-07-06", "--json")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["added"] == ["2026-07-06"]
    data = json.loads(config_path.read_text())
    assert data["leave_days"][0]["date"] == "2026-07-06"
    assert data["leave_days"][0]["kind"] == "holiday"


def test_leave_add_range_skips_weekends(runner, store_file, config_path):
    # 2026-07-06 is a Monday; the range Mon-Sun records only Mon-Fri.
    result = _invoke(
        runner, store_file, "leave", "add", "2026-07-06", "--to", "2026-07-12", "--json"
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["added"] == [
        "2026-07-06",
        "2026-07-07",
        "2026-07-08",
        "2026-07-09",
        "2026-07-10",
    ]
    assert payload["skipped_weekend"] == 2


def test_leave_add_range_include_weekends(runner, store_file, config_path):
    result = _invoke(
        runner,
        store_file,
        "leave",
        "add",
        "2026-07-06",
        "--to",
        "2026-07-12",
        "--include-weekends",
        "--json",
    )
    payload = json.loads(result.output)
    assert len(payload["added"]) == 7


def test_leave_add_sick_and_half(runner, store_file, config_path):
    _invoke(runner, store_file, "leave", "add", "2026-07-13", "--kind", "sick", "--json")
    _invoke(runner, store_file, "leave", "add", "2026-07-14", "--half", "--json")
    data = json.loads(config_path.read_text())
    kinds = {e["date"]: (e["kind"], e["fraction"]) for e in data["leave_days"]}
    assert kinds["2026-07-13"] == ("sick", 1.0)
    assert kinds["2026-07-14"] == ("holiday", 0.5)


def test_leave_add_dedup(runner, store_file, config_path):
    _invoke(runner, store_file, "leave", "add", "2026-07-06", "--json")
    result = _invoke(runner, store_file, "leave", "add", "2026-07-06", "--json")
    payload = json.loads(result.output)
    assert payload["added"] == []  # already present


def test_leave_list_totals(runner, store_file, config_path):
    _invoke(runner, store_file, "leave", "add", "2026-07-06", "--to", "2026-07-10", "--json")
    _invoke(runner, store_file, "leave", "add", "2026-07-13", "--kind", "sick", "--json")
    result = _invoke(runner, store_file, "leave", "list", "--year", "2026", "--json")
    payload = json.loads(result.output)
    assert payload["holiday_days"] == 5
    assert payload["sick_days"] == 1
    assert payload["allowance_days"] == 25.0


def test_leave_remove(runner, store_file, config_path):
    _invoke(runner, store_file, "leave", "add", "2026-07-06", "--json")
    result = _invoke(runner, store_file, "leave", "remove", "2026-07-06", "--json")
    payload = json.loads(result.output)
    assert payload["removed"] == 1
    data = json.loads(config_path.read_text())
    assert data["leave_days"] == []


def test_leave_remove_range(runner, store_file, config_path):
    _invoke(runner, store_file, "leave", "add", "2026-07-06", "--to", "2026-07-10", "--json")
    _invoke(runner, store_file, "leave", "add", "2026-07-13", "--json")
    result = _invoke(
        runner, store_file, "leave", "remove", "2026-07-06", "--to", "2026-07-10", "--json"
    )
    payload = json.loads(result.output)
    assert payload["removed"] == 5
    assert payload["removed_dates"] == [
        "2026-07-06",
        "2026-07-07",
        "2026-07-08",
        "2026-07-09",
        "2026-07-10",
    ]
    data = json.loads(config_path.read_text())
    # The day outside the range survives.
    assert [e["date"] for e in data["leave_days"]] == ["2026-07-13"]


def test_leave_remove_range_kind_filter(runner, store_file, config_path):
    _invoke(runner, store_file, "leave", "add", "2026-07-06", "--to", "2026-07-08", "--json")
    _invoke(runner, store_file, "leave", "add", "2026-07-07", "--kind", "sick", "--json")
    result = _invoke(
        runner,
        store_file,
        "leave",
        "remove",
        "2026-07-06",
        "--to",
        "2026-07-08",
        "--kind",
        "sick",
        "--json",
    )
    payload = json.loads(result.output)
    assert payload["removed"] == 1
    data = json.loads(config_path.read_text())
    # Only the sick entry on 2026-07-07 is gone; the three holidays remain.
    kinds = sorted((e["date"], e["kind"]) for e in data["leave_days"])
    assert kinds == [
        ("2026-07-06", "holiday"),
        ("2026-07-07", "holiday"),
        ("2026-07-08", "holiday"),
    ]


def test_leave_remove_range_reversed_dates(runner, store_file, config_path):
    _invoke(runner, store_file, "leave", "add", "2026-07-06", "--to", "2026-07-08", "--json")
    # end before start is swapped so the range still matches.
    result = _invoke(
        runner, store_file, "leave", "remove", "2026-07-08", "--to", "2026-07-06", "--json"
    )
    payload = json.loads(result.output)
    assert payload["removed"] == 3


def test_report_includes_overtime_and_holidays(runner, store_file, config_path):
    # Mon-Thu Jan 2026 worked 8h each; Fri a holiday -> overtime 0.
    worklogs = [
        {
            "started_at": f"2026-01-{d:02d}T09:00:00+00:00",
            "stopped_at": f"2026-01-{d:02d}T17:00:00+00:00",
        }
        for d in (5, 6, 7, 8)
    ]
    config_path.write_text(
        json.dumps(
            {
                "version": 1,
                "work_clock": {"worklogs": worklogs},
                "leave_days": [{"date": "2026-01-09", "kind": "holiday", "fraction": 1.0}],
            }
        )
    )
    result = _invoke(runner, store_file, "report", "-p", "week", "--on", "2026-01-07", "--json")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    ot = payload["overtime"]
    assert ot["expected_seconds"] == 5 * 8 * 3600
    assert ot["worked_seconds"] == 4 * 8 * 3600
    assert ot["leave_credit_seconds"] == 8 * 3600
    assert ot["overtime_seconds"] == 0
    assert ot["holiday_days_taken"] == 1.0
    holidays = payload["holidays"]
    assert holidays["allowance_days"] == 25.0
    assert holidays["used_days"] == 1.0
    assert holidays["remaining_days"] == 24.0


def test_config_set_work_settings(runner, store_file, config_path):
    result = runner.invoke(
        cli,
        [
            "--json",
            str(store_file),
            "config",
            "--set-day-length",
            "8h24m",
            "--set-week-length",
            "40h",
            "--set-holiday-allowance",
            "27.5",
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(config_path.read_text())
    assert data["day_length_minutes"] == 504
    assert data["week_length_minutes"] == 2400
    assert data["holiday_allowance_days"] == 27.5


def test_config_clear_week_length(runner, store_file, config_path):
    runner.invoke(cli, ["--json", str(store_file), "config", "--set-week-length", "40h"])
    result = runner.invoke(cli, ["--json", str(store_file), "config", "--set-week-length", "none"])
    assert result.exit_code == 0, result.output
    data = json.loads(config_path.read_text())
    assert data["week_length_minutes"] is None


def test_config_set_invalid_day_length(runner, store_file, config_path):
    result = runner.invoke(
        cli,
        ["--json", str(store_file), "config", "--set-day-length", "nonsense"],
    )
    assert result.exit_code != 0
