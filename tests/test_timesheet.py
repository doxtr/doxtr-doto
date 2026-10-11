"""Tests for ``doto timesheet`` - daily worked-tasks CSV export.

Covers the click command wiring (date resolution, column parsing/validation,
stdout vs. file output, empty-day behavior) end-to-end through the registered
CLI, complementing the pure-function tests in ``test_work_report.py``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from click.testing import CliRunner

from doxtr_doto.cli.config import DotoConfig
from doxtr_doto.cli.global_state import GlobalStateStore
from doxtr_doto.cli.json_store import JsonTaskStore
from doxtr_doto.cli.main import DotoContext, timesheet
from doxtr_doto.cli.output import OutputFormatter

TZ = timezone.utc


def _ts(h: int, m: int, day: int = 1) -> str:
    """ISO timestamp on 2026-10-``day`` at ``h:m`` UTC."""
    return datetime(2026, 10, day, h, m, tzinfo=TZ).isoformat()


def _wl(start: str, stop: str | None) -> dict[str, Any]:
    return {"started_at": start, "stopped_at": stop}


def _make_ctx(
    tmp_path: Path,
    work_worklogs: list[dict[str, Any]] | None = None,
    task_worklogs: list[dict[str, Any]] | None = None,
) -> DotoContext:
    """Build a DotoContext with a work clock and (optionally) one task.

    Args:
        tmp_path: Temp project dir.
        work_worklogs: Global work-clock intervals.
        task_worklogs: Intervals for a single task "T1".

    Returns:
        A wired DotoContext for invoking the timesheet command.
    """
    store_dir = tmp_path / ".doto"
    store_dir.mkdir()
    store = JsonTaskStore(store_dir / "tasks.json")
    if task_worklogs:
        store.add_task("T1", {"title": "Alpha", "worklogs": list(task_worklogs)})
        store.save()
    global_store = GlobalStateStore(tmp_path / "global.json")
    state = global_store.load()
    state.work_clock.worklogs = list(work_worklogs or [])
    global_store.save(state)
    return DotoContext(
        config=DotoConfig(source_dir=tmp_path),
        store=store,
        formatter=OutputFormatter(),
        global_store=global_store,
    )


def test_timesheet_stdout_minimum_columns(tmp_path: Path) -> None:
    ctx = _make_ctx(
        tmp_path,
        work_worklogs=[
            _wl(_ts(10, 0), _ts(15, 43)),
            _wl(_ts(16, 0), _ts(18, 15)),
        ],
    )
    runner = CliRunner()
    result = runner.invoke(
        timesheet,
        ["--date", "2026-10-01", "--columns", "date,start_time,end_time"],
        obj=ctx,
    )
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0] == "date,start_time,end_time"
    assert lines[1] == "2026-10-01,10:00,15:45"
    assert lines[2] == "2026-10-01,16:00,18:15"
    # Total row: unrounded span 10:00 -> 18:15 == 08:15 in end_time.
    assert lines[-1] == "2026-10-01,,08:15"


def test_timesheet_includes_work_and_task_rows(tmp_path: Path) -> None:
    ctx = _make_ctx(
        tmp_path,
        work_worklogs=[_wl(_ts(10, 0), _ts(15, 45))],
        task_worklogs=[_wl(_ts(11, 8), _ts(12, 52))],
    )
    runner = CliRunner()
    result = runner.invoke(timesheet, ["--date", "2026-10-01"], obj=ctx)
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0].split(",") == [
        "date",
        "start_time",
        "end_time",
        "task_id",
        "title",
        "kind",
        "duration",
    ]
    # A work row and a task row, then the total row.
    kinds = [line.split(",")[5] for line in lines[1:]]
    assert "work" in kinds
    assert "task" in kinds
    assert kinds[-1] == "total"
    # The task row carries its id and title.
    task_rows = [line for line in lines[1:] if line.split(",")[5] == "task"]
    assert any("T1" in line and "Alpha" in line for line in task_rows)


def test_timesheet_output_file(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path, work_worklogs=[_wl(_ts(10, 0), _ts(12, 0))])
    out = tmp_path / "nested" / "sheet.csv"
    runner = CliRunner()
    result = runner.invoke(
        timesheet,
        ["--date", "2026-10-01", "-o", str(out)],
        obj=ctx,
    )
    assert result.exit_code == 0, result.output
    assert out.exists()
    content = out.read_text()
    assert content.splitlines()[0].startswith("date,start_time,end_time")
    assert "✓" in result.output or "timesheet" in result.output.lower()


def test_timesheet_empty_day_header_only(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path, work_worklogs=[])
    runner = CliRunner()
    result = runner.invoke(
        timesheet,
        ["--date", "2026-10-01", "--columns", "date,start_time,end_time"],
        obj=ctx,
    )
    assert result.exit_code == 0, result.output
    # Only the header line (no rows, no total) for a day with no worked time.
    assert result.output.splitlines() == ["date,start_time,end_time"]


def test_timesheet_invalid_date(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path, work_worklogs=[_wl(_ts(10, 0), _ts(12, 0))])
    runner = CliRunner()
    result = runner.invoke(timesheet, ["--date", "not-a-date"], obj=ctx)
    assert result.exit_code != 0
    assert "Invalid --date" in result.output


def test_timesheet_unknown_column(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path, work_worklogs=[_wl(_ts(10, 0), _ts(12, 0))])
    runner = CliRunner()
    result = runner.invoke(timesheet, ["--columns", "date,bogus"], obj=ctx)
    assert result.exit_code != 0
    assert "Unknown timesheet column" in result.output
    assert "bogus" in result.output


def test_timesheet_column_reordering(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path, work_worklogs=[_wl(_ts(10, 0), _ts(15, 45))])
    runner = CliRunner()
    result = runner.invoke(
        timesheet,
        ["--date", "2026-10-01", "--columns", "kind,start_time,end_time,date"],
        obj=ctx,
    )
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0] == "kind,start_time,end_time,date"
    assert lines[1] == "work,10:00,15:45,2026-10-01"
