"""Tests for the ``doto report`` command's break-aware work-clock output.

Focuses on the fixed break behavior: a recorded clock-out gap is the break
(surfaced, not deducted), and a break taken outside a configured nominal
window does NOT additionally deduct the nominal duration (the reported
double-counting bug).
"""

from __future__ import annotations

import json
from pathlib import Path

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
def env(tmp_path, monkeypatch):
    """Isolate the global config under XDG_CONFIG_HOME in a temp dir."""
    # Clear any $DOTO_CONFIG override and chdir into a clean tmp dir so the
    # config resolver's portable walk-up does not pick up the real repo's
    # .doto/config.json instead of the XDG path written by _write_global.
    monkeypatch.delenv("DOTO_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    cfg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    return cfg


def _write_global(env, worklogs, breaks=None):
    path = env / "doto" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "work_clock": {"worklogs": worklogs},
                "breaks": breaks or [],
            }
        )
    )


def _invoke(runner, store_file, *args):
    return runner.invoke(cli, ["--json", str(store_file), *args])


def _ts(h, m, day=1):
    return f"2026-06-{day:02d}T{h:02d}:{m:02d}:00+00:00"


def test_report_break_outside_window_not_double_counted(runner, store_file, env):
    # The reported scenario: a 12:55-13:34 break outside the 12:00 lunch
    # window must NOT additionally deduct an hour. Net == gross worked.
    worklogs = [
        {"started_at": _ts(9, 0), "stopped_at": _ts(12, 55)},
        {"started_at": _ts(13, 34), "stopped_at": _ts(18, 0)},
    ]
    _write_global(
        env,
        worklogs,
        breaks=[{"name": "Lunch", "time": "12:00", "duration_minutes": 60, "leeway_minutes": 30}],
    )
    result = _invoke(runner, store_file, "report", "-p", "day", "--on", "2026-06-01", "--json")
    assert result.exit_code == 0
    payload = json.loads(result.output)
    wc = payload["work_clock"]
    gross = wc["gross_seconds"]
    expected_gross = (12 * 3600 + 55 * 60 - 9 * 3600) + (18 * 3600 - (13 * 3600 + 34 * 60))
    assert gross == expected_gross
    # No nominal auto-deduction with the default (recorded) break.
    assert wc["break_seconds"] == 0
    # Net equals gross: the hour break is NOT double-counted.
    assert wc["net_seconds"] == expected_gross
    # The real break is recorded (39 minutes).
    assert wc["recorded_break_seconds"] == 39 * 60
    day = wc["days"][0]
    assert len(day["recorded_breaks"]) == 1
    assert day["recorded_breaks"][0]["seconds"] == 39 * 60


def test_report_text_shows_breaks_taken(runner, store_file, env):
    worklogs = [
        {"started_at": _ts(9, 0), "stopped_at": _ts(12, 55)},
        {"started_at": _ts(13, 34), "stopped_at": _ts(18, 0)},
    ]
    _write_global(env, worklogs)
    result = runner.invoke(
        cli, ["--json", str(store_file), "report", "-p", "day", "--on", "2026-06-01"]
    )
    assert result.exit_code == 0
    assert "Breaks taken:" in result.output
    assert "12:55-13:34" in result.output
    assert "Recorded breaks:" in result.output


def test_report_multi_day_per_day_line_shows_recorded_breaks(runner, store_file, env):
    # The multi-day "Per day" line's "breaks" column shows the recorded
    # clock-out gap (not a nominal auto-deduction): a default break reports a
    # non-zero recorded break while break_seconds (auto-deduct) stays 0.
    worklogs = [
        {"started_at": _ts(9, 0, day=1), "stopped_at": _ts(12, 55, day=1)},
        {"started_at": _ts(13, 34, day=1), "stopped_at": _ts(18, 0, day=1)},
    ]
    _write_global(
        env,
        worklogs,
        breaks=[{"name": "Lunch", "time": "12:00", "duration_minutes": 60, "leeway_minutes": 30}],
    )
    # Text (non-JSON) week report so the multi-day "Per day" line is rendered.
    text = runner.invoke(
        cli, ["--json", str(store_file), "report", "-p", "week", "--on", "2026-06-01"]
    )
    assert text.exit_code == 0
    assert "Per day:" in text.output
    # The per-day line labels the recorded break as "breaks" and shows 39m.
    assert "2026-06-01" in text.output
    assert "breaks 39m00s" in text.output
    # And the auto-deduction (break_seconds) is 0 in the JSON for the same data.
    json_result = _invoke(
        runner, store_file, "report", "-p", "week", "--on", "2026-06-01", "--json"
    )
    payload = json.loads(json_result.output)
    day = payload["work_clock"]["days"][0]
    assert day["break_seconds"] == 0
    assert day["recorded_break_seconds"] == 39 * 60


def test_report_auto_deduct_break_still_subtracts(runner, store_file, env):
    # An opt-in auto_deduct break restores the legacy straight-through
    # deduction for a day worked without clocking out.
    worklogs = [{"started_at": _ts(9, 0), "stopped_at": _ts(19, 0)}]
    _write_global(
        env,
        worklogs,
        breaks=[
            {
                "name": "Lunch",
                "time": "12:00",
                "duration_minutes": 60,
                "leeway_minutes": 30,
                "auto_deduct": True,
            }
        ],
    )
    result = _invoke(runner, store_file, "report", "-p", "day", "--on", "2026-06-01", "--json")
    payload = json.loads(result.output)
    wc = payload["work_clock"]
    assert wc["gross_seconds"] == 10 * 3600
    assert wc["break_seconds"] == 60 * 60
    assert wc["net_seconds"] == 9 * 3600
