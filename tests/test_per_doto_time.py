"""Tests for per-doto time reporting and per-doto session editing in the TUI.

Covers the pure, Textual-free helpers (the per-doto / per-repo chart-row
builders, the per-task interval-row builder and the shared cross-repo task
collector) and the overridable ``format_*`` classmethods, plus Pilot tests
that:

* the per-doto time-stats pop-up opens from the ``time`` layout with ``T``
  (and is a no-op elsewhere), supports granularity / anchor navigation, and
  renders the worked-time bar chart, and
* the per-doto session editor opens with ``E`` on the highlighted doto, lists
  its sessions, and persists an added / edited / deleted session back to the
  owning repo store.

Mirrors ``tests/test_work_stats.py`` / ``tests/test_tui_time_view.py``.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timezone
from pathlib import Path

from textual.widgets import Label, ListView

from doxtr_doto.cli.config import DotoConfig
from doxtr_doto.cli.display import DisplayScope
from doxtr_doto.cli.global_state import GlobalStateStore
from doxtr_doto.cli.json_store import JsonTaskStore
from doxtr_doto.cli.main import DotoContext
from doxtr_doto.cli.output import OutputFormatter
from doxtr_doto.cli.session import format_duration, render_time_spent_line
from doxtr_doto.cli.task_collector import collect_repo_tasks
from doxtr_doto.cli.tui.app import DotoApp
from doxtr_doto.cli.tui.time_mgmt import (
    BAR_CHAR,
    TaskSessionsScreen,
    TaskTimeStatsScreen,
    WorkIntervalEditScreen,
    task_breakdown_chart_rows,
    task_interval_display_rows,
    task_repo_chart_rows,
)
from doxtr_doto.enums import TuiLayout
from doxtr_doto.work_report import TaskHours, compute_task_breakdown

TZ = timezone.utc


def _ts(h: int, m: int, day: int = 1, month: int = 6) -> str:
    return datetime(2026, month, day, h, m, tzinfo=TZ).isoformat()


# --- task_breakdown_chart_rows (pure) -------------------------------------


def test_task_breakdown_chart_rows_labels_namespaced_and_capped():
    tasks = [
        TaskHours(repo="alpha", task_id="1", title="A", seconds=300),
        TaskHours(repo="beta", task_id="2", title="B", seconds=100),
    ]
    rows = task_breakdown_chart_rows(tasks)
    assert rows == [("alpha#1", 300), ("beta#2", 100)]


def test_task_breakdown_chart_rows_caps_to_max_rows():
    tasks = [TaskHours(repo="r", task_id=str(i), title="t", seconds=i) for i in range(20)]
    rows = task_breakdown_chart_rows(tasks, max_rows=5)
    assert len(rows) == 5
    assert rows[0] == ("r#0", 0)


def test_task_breakdown_chart_rows_empty():
    assert task_breakdown_chart_rows([]) == []


# --- task_repo_chart_rows (pure) ------------------------------------------


def test_task_repo_chart_rows_sorted_desc():
    rows = task_repo_chart_rows({"a": 10, "b": 50, "c": 30})
    assert rows == [("b", 50), ("c", 30), ("a", 10)]


def test_task_repo_chart_rows_empty():
    assert task_repo_chart_rows({}) == []


# --- task_interval_display_rows (pure) ------------------------------------


def test_task_interval_display_rows_indices_and_durations():
    worklogs = [
        {"started_at": _ts(9, 0), "stopped_at": _ts(10, 0)},
        {"started_at": _ts(11, 0), "stopped_at": None},  # running
    ]
    rows = task_interval_display_rows(worklogs)
    assert len(rows) == 2
    index0, start0, stop0, secs0 = rows[0]
    assert index0 == 0
    assert start0 == _ts(9, 0)
    assert stop0 == _ts(10, 0)
    assert secs0 == 3600
    index1, _start1, stop1, secs1 = rows[1]
    assert index1 == 1
    assert stop1 == ""  # running interval has a blank stop
    assert secs1 is None


def test_task_interval_display_rows_empty():
    assert task_interval_display_rows([]) == []


# --- format_* classmethods (pure) -----------------------------------------


def test_task_time_stats_format_breakdown_empty_state():
    body = TaskTimeStatsScreen.format_breakdown(0, [], [])
    assert "no task sessions" in body


def test_task_time_stats_format_breakdown_renders_charts():
    body = TaskTimeStatsScreen.format_breakdown(
        400, [("alpha#1", 300), ("beta#2", 100)], [("alpha", 300), ("beta", 100)]
    )
    assert BAR_CHAR in body
    assert "Per doto" in body
    assert "Per repo" in body
    assert format_duration(400) in body


def test_task_time_stats_format_title_variants():
    assert "day" in TaskTimeStatsScreen.format_title("day", date(2026, 6, 1), date(2026, 6, 1))
    assert "week of" in TaskTimeStatsScreen.format_title("week", date(2026, 6, 1), date(2026, 6, 7))


def test_task_time_stats_format_title_rejects_unknown():
    import pytest

    with pytest.raises(ValueError):
        TaskTimeStatsScreen.format_title("decade", date(2026, 6, 1), date(2026, 6, 30))


def test_task_sessions_format_interval_row_running_and_closed():
    running = TaskSessionsScreen.format_interval_row(_ts(9, 0), "", None)
    assert "(running)" in running
    closed = TaskSessionsScreen.format_interval_row(_ts(9, 0), _ts(10, 0), 3600)
    assert "1h00m00s" in closed


def test_task_sessions_format_title():
    assert "alpha#1" in TaskSessionsScreen.format_title("alpha#1")


# --- collect_repo_tasks (shared collector) --------------------------------


def test_collect_repo_tasks_includes_current_store(tmp_path):
    store_dir = tmp_path / ".doto"
    store_dir.mkdir()
    store = JsonTaskStore(store_dir / "tasks.json")
    store.add_task("1", {"title": "Worked", "worklogs": [{"started_at": _ts(9, 0)}]})
    store.add_task("2", {"title": "No logs"})  # skipped: no worklogs
    store.save()
    global_store = GlobalStateStore(tmp_path / "global.json")
    global_store.save(global_store.load())
    ctx = DotoContext(
        config=DotoConfig(source_dir=tmp_path),
        store=store,
        formatter=OutputFormatter(),
        global_store=global_store,
    )
    tuples = collect_repo_tasks(ctx)
    task_ids = {t[1] for t in tuples}
    assert "1" in task_ids
    assert "2" not in task_ids  # no worklogs -> skipped


def test_compute_task_breakdown_over_collected(tmp_path):
    store_dir = tmp_path / ".doto"
    store_dir.mkdir()
    store = JsonTaskStore(store_dir / "tasks.json")
    store.add_task(
        "1",
        {"title": "A", "worklogs": [{"started_at": _ts(9, 0), "stopped_at": _ts(11, 0)}]},
    )
    store.save()
    global_store = GlobalStateStore(tmp_path / "global.json")
    global_store.save(global_store.load())
    ctx = DotoContext(
        config=DotoConfig(source_dir=tmp_path),
        store=store,
        formatter=OutputFormatter(),
        global_store=global_store,
    )
    now = datetime(2026, 6, 2, tzinfo=TZ)
    breakdown = compute_task_breakdown(
        collect_repo_tasks(ctx), date(2026, 6, 1), date(2026, 6, 1), now
    )
    assert breakdown.total_seconds == 2 * 3600
    assert len(breakdown.tasks) == 1
    assert breakdown.tasks[0].task_id == "1"


# --- App wiring (Textual pilot) -------------------------------------------


def _make_ctx(tmp_path: Path, worklogs: list[dict[str, object]] | None = None) -> DotoContext:
    store_dir = tmp_path / ".doto"
    store_dir.mkdir()
    store = JsonTaskStore(store_dir / "tasks.json")
    store.add_task(
        "1",
        {
            "title": "Task one",
            "worklogs": [{"started_at": _ts(9, 0), "stopped_at": _ts(11, 0)}],
        },
    )
    store.save()
    global_store = GlobalStateStore(tmp_path / "global.json")
    state = global_store.load()
    state.work_clock.worklogs = list(worklogs or [])
    from doxtr_doto.cli.tui import nudge

    state.last_prompt_date = nudge.today_iso()
    global_store.save(state)
    return DotoContext(
        config=DotoConfig(source_dir=tmp_path),
        store=store,
        formatter=OutputFormatter(),
        global_store=global_store,
    )


def _run(coro) -> None:
    asyncio.run(coro)


async def _cycle_to_time(app, pilot) -> None:
    for _ in range(len(list(TuiLayout))):
        if app.layout_view is TuiLayout.TIME:
            break
        await pilot.press("v")
        await pilot.pause()
    assert app.layout_view is TuiLayout.TIME


def test_task_time_stats_opens_from_time_layout(tmp_path):
    worklogs = [{"started_at": _ts(9, 0, 1), "stopped_at": _ts(12, 0, 1)}]
    ctx = _make_ctx(tmp_path, worklogs)

    async def scenario() -> None:
        app = DotoApp(ctx)
        async with app.run_test() as pilot:
            await pilot.pause()
            await _cycle_to_time(app, pilot)
            # Anchor the stats on the day the seeded task was worked.
            await pilot.press("S", "t")  # stats stream -> per-doto time
            await pilot.pause()
            assert isinstance(app.screen, TaskTimeStatsScreen)
            # Day granularity so the single worked day shows the doto's bar.
            await pilot.press("d")
            await pilot.pause()
            app.screen.anchor = date(2026, 6, 1)
            app.screen._refresh()
            await pilot.pause()
            content = str(app.screen.query_one("#taskstats-content").render())
            assert BAR_CHAR in content
            assert "Per doto" in content

    _run(scenario())


def test_task_time_stats_granularity_and_anchor_moves(tmp_path):
    ctx = _make_ctx(tmp_path, [{"started_at": _ts(9, 0, 1), "stopped_at": _ts(12, 0, 1)}])

    async def scenario() -> None:
        app = DotoApp(ctx)
        async with app.run_test() as pilot:
            await pilot.pause()
            await _cycle_to_time(app, pilot)
            await pilot.press("S", "t")  # stats stream -> per-doto time
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, TaskTimeStatsScreen)
            assert screen.granularity == "week"
            anchor_before = screen.anchor
            await pilot.press("m")
            await pilot.pause()
            assert screen.granularity == "month"
            await pilot.press("left")
            await pilot.pause()
            assert screen.anchor < anchor_before
            await pilot.press("g")
            await pilot.pause()
            assert screen.granularity == "year"

    _run(scenario())


def test_task_time_stats_opens_outside_time_layout(tmp_path):
    # The stats stream (``S``) is advertised globally in the hint bar, so
    # ``S t`` must open the per-doto time pop-up from any layout - including
    # the default TABLE layout - not only the TIME layout.
    ctx = _make_ctx(tmp_path)

    async def scenario() -> None:
        app = DotoApp(ctx)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.layout_view is TuiLayout.TABLE
            await pilot.press("S")  # arm the stats prefix
            await pilot.pause()
            await pilot.press("t")  # -> per-doto time
            await pilot.pause()
            assert isinstance(app.screen, TaskTimeStatsScreen)

    _run(scenario())


def test_edit_sessions_opens_on_highlighted_doto(tmp_path):
    ctx = _make_ctx(tmp_path)

    async def scenario() -> None:
        app = DotoApp(ctx)
        app.scope = DisplayScope.LOCAL  # highlight the current repo's seeded doto
        async with app.run_test() as pilot:
            await pilot.pause()
            # Default TABLE layout; the single task is highlighted.
            await pilot.press("t", "e")  # time stream -> edit sessions
            await pilot.pause()
            assert isinstance(app.screen, TaskSessionsScreen)
            assert app.screen.task_ref == "1"
            # The seeded 2h session renders in the list + total.
            total = str(app.screen.query_one("#tasksessions-total").render())
            assert format_duration(2 * 3600) in total

    _run(scenario())


def test_edit_sessions_noop_in_time_layout(tmp_path):
    ctx = _make_ctx(tmp_path, [{"started_at": _ts(9, 0, 1), "stopped_at": _ts(12, 0, 1)}])

    async def scenario() -> None:
        app = DotoApp(ctx)
        async with app.run_test() as pilot:
            await pilot.pause()
            await _cycle_to_time(app, pilot)
            screen_before = app.screen
            await pilot.press("t", "e")  # time stream -> edit sessions
            await pilot.pause()
            assert not isinstance(app.screen, TaskSessionsScreen)
            assert app.screen is screen_before

    _run(scenario())


def test_edit_sessions_add_persists_to_store(tmp_path):
    ctx = _make_ctx(tmp_path)

    async def scenario() -> None:
        app = DotoApp(ctx)
        app.scope = DisplayScope.LOCAL  # highlight the current repo's seeded doto
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("t", "e")  # time stream -> edit sessions
            await pilot.pause()
            assert isinstance(app.screen, TaskSessionsScreen)
            # Add a second session via the interval editor.
            await pilot.press("a")
            await pilot.pause()
            editor = app.screen
            assert isinstance(editor, WorkIntervalEditScreen)
            start_iso = datetime.combine(date(2026, 6, 2), time(14, 0), tzinfo=TZ).isoformat()
            stop_iso = datetime.combine(date(2026, 6, 2), time(15, 30), tzinfo=TZ).isoformat()
            editor.query_one("#interval-start").value = start_iso
            editor.query_one("#interval-stop").value = stop_iso
            await pilot.click("#interval-save")
            await pilot.pause()
            assert isinstance(app.screen, TaskSessionsScreen)
            # The store now has the original 2h session + the new 1h30m one.
            task = ctx.store.get_task("1")
            assert len(task["worklogs"]) == 2

    _run(scenario())


def test_edit_sessions_delete_persists_to_store(tmp_path):
    ctx = _make_ctx(tmp_path)

    async def scenario() -> None:
        app = DotoApp(ctx)
        app.scope = DisplayScope.LOCAL  # highlight the current repo's seeded doto
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("t", "e")  # time stream -> edit sessions
            await pilot.pause()
            assert isinstance(app.screen, TaskSessionsScreen)
            # Delete the highlighted (only) session.
            await pilot.press("x")
            await pilot.pause()
            task = ctx.store.get_task("1")
            assert task["worklogs"] == []

    _run(scenario())


def _make_ctx_with_task_worklogs(tmp_path: Path, worklogs: list[dict[str, object]]) -> DotoContext:
    """Build a ctx whose single task "1" carries ``worklogs``.

    Mirrors :func:`_make_ctx` but lets a test seed an arbitrary per-task
    session list (e.g. a multi-day worklog) rather than the fixed 2h session.
    """
    store_dir = tmp_path / ".doto"
    store_dir.mkdir()
    store = JsonTaskStore(store_dir / "tasks.json")
    store.add_task("1", {"title": "Task one", "worklogs": list(worklogs)})
    store.save()
    global_store = GlobalStateStore(tmp_path / "global.json")
    state = global_store.load()
    from doxtr_doto.cli.tui import nudge

    state.last_prompt_date = nudge.today_iso()
    global_store.save(state)
    return DotoContext(
        config=DotoConfig(source_dir=tmp_path),
        store=store,
        formatter=OutputFormatter(),
        global_store=global_store,
    )


def test_task_time_stats_total_at_week_month_year(tmp_path):
    # Seed a multi-day worklog so the TOTAL differs by granularity:
    #   * 06-01 (Mon)  2h  -> in the 06-01 week, June, 2026
    #   * 06-10 (Wed)  1h  -> in June + 2026 (NOT the 06-01 week)
    #   * 03-01        3h  -> in 2026 only
    worklogs = [
        {"started_at": _ts(9, 0, day=1), "stopped_at": _ts(11, 0, day=1)},
        {"started_at": _ts(9, 0, day=10), "stopped_at": _ts(10, 0, day=10)},
        {"started_at": _ts(9, 0, day=1, month=3), "stopped_at": _ts(12, 0, day=1, month=3)},
    ]
    ctx = _make_ctx_with_task_worklogs(tmp_path, worklogs)

    async def scenario() -> None:
        app = DotoApp(ctx)
        async with app.run_test() as pilot:
            await pilot.pause()
            await _cycle_to_time(app, pilot)
            await pilot.press("S", "t")  # stats stream -> per-doto time
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, TaskTimeStatsScreen)
            screen.anchor = date(2026, 6, 1)

            # Week of 06-01 (Mon 06-01 .. Sun 06-07): only the 2h session.
            await pilot.press("w")
            await pilot.pause()
            week_content = str(screen.query_one("#taskstats-content").render())
            assert format_duration(2 * 3600) in week_content

            # June: 2h + 1h = 3h.
            await pilot.press("m")
            await pilot.pause()
            month_content = str(screen.query_one("#taskstats-content").render())
            assert format_duration(3 * 3600) in month_content

            # 2026: 2h + 1h + 3h = 6h.
            await pilot.press("y")
            await pilot.pause()
            year_content = str(screen.query_one("#taskstats-content").render())
            assert format_duration(6 * 3600) in year_content

    _run(scenario())


def test_edit_sessions_edit_persists_mutated_timestamps(tmp_path):
    ctx = _make_ctx(tmp_path)

    async def scenario() -> None:
        app = DotoApp(ctx)
        app.scope = DisplayScope.LOCAL  # highlight the current repo's seeded doto
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("t", "e")  # time stream -> edit sessions
            await pilot.pause()
            assert isinstance(app.screen, TaskSessionsScreen)
            # The single seeded session is highlighted (row 0); edit it.
            await pilot.press("e")
            await pilot.pause()
            editor = app.screen
            assert isinstance(editor, WorkIntervalEditScreen)
            # Shift the session to a new, non-overlapping start/stop.
            new_start = datetime.combine(date(2026, 6, 5), time(13, 0), tzinfo=TZ).isoformat()
            new_stop = datetime.combine(date(2026, 6, 5), time(16, 0), tzinfo=TZ).isoformat()
            editor.query_one("#interval-start").value = new_start
            editor.query_one("#interval-stop").value = new_stop
            await pilot.click("#interval-save")
            await pilot.pause()
            assert isinstance(app.screen, TaskSessionsScreen)
            # The mutated timestamps persist (still one session, new times).
            worklogs = ctx.store.get_task("1")["worklogs"]
            assert len(worklogs) == 1
            assert worklogs[0]["started_at"] == new_start
            assert worklogs[0]["stopped_at"] == new_stop

    _run(scenario())


def test_edit_sessions_cross_repo_persists_to_second_repo(tmp_path):
    # Current repo plus a SECOND registered repo, each with its own store.
    ctx = _make_ctx(tmp_path)
    other_root = tmp_path / "other-repo"
    other_store_dir = other_root / ".doto"
    other_store_dir.mkdir(parents=True)
    other_store = JsonTaskStore(other_store_dir / "tasks.json")
    other_store.add_task(
        "1",
        {
            "title": "Other task",
            "worklogs": [{"started_at": _ts(9, 0), "stopped_at": _ts(10, 0)}],
        },
    )
    other_store.save()
    from doxtr_doto.cli.repo_registry import RepoRegistry

    repo = RepoRegistry(ctx.global_store).add(other_root)
    task_ref = f"{repo.name}#1"

    async def scenario() -> None:
        app = DotoApp(ctx)
        async with app.run_test() as pilot:
            await pilot.pause()
            # Open the session editor directly for the namespaced ref.
            await app.push_screen(TaskSessionsScreen(ctx, task_ref))
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, TaskSessionsScreen)
            assert screen.task_ref == task_ref
            # Edit the single (highlighted) session.
            await pilot.press("e")
            await pilot.pause()
            editor = app.screen
            assert isinstance(editor, WorkIntervalEditScreen)
            new_start = datetime.combine(date(2026, 6, 7), time(8, 0), tzinfo=TZ).isoformat()
            new_stop = datetime.combine(date(2026, 6, 7), time(12, 0), tzinfo=TZ).isoformat()
            editor.query_one("#interval-start").value = new_start
            editor.query_one("#interval-stop").value = new_stop
            await pilot.click("#interval-save")
            await pilot.pause()

    _run(scenario())

    # The edit lands in the SECOND repo's tasks.json, not the current store.
    reloaded = JsonTaskStore(other_store_dir / "tasks.json")
    other_worklogs = reloaded.get_task("1")["worklogs"]
    assert len(other_worklogs) == 1
    assert other_worklogs[0]["started_at"].startswith("2026-06-07T08:00")
    # The current repo's own task "1" is untouched (still its 2h session).
    assert len(ctx.store.get_task("1")["worklogs"]) == 1
    assert ctx.store.get_task("1")["worklogs"][0]["started_at"] == _ts(9, 0)


def test_task_time_stats_empty_period_renders_empty_state(tmp_path):
    # A task worked only on 06-01; anchor the stats on an empty earlier year.
    ctx = _make_ctx_with_task_worklogs(
        tmp_path,
        [{"started_at": _ts(9, 0, day=1), "stopped_at": _ts(11, 0, day=1)}],
    )

    async def scenario() -> None:
        app = DotoApp(ctx)
        async with app.run_test() as pilot:
            await pilot.pause()
            await _cycle_to_time(app, pilot)
            await pilot.press("S", "t")  # stats stream -> per-doto time
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, TaskTimeStatsScreen)
            # Move the anchor to a year with no sessions and re-render.
            screen.anchor = date(2020, 6, 1)
            screen.granularity = "year"
            screen._refresh()
            await pilot.pause()
            content = str(screen.query_one("#taskstats-content").render())
            assert "no task sessions" in content

    _run(scenario())


def test_edit_sessions_empty_task_is_safe(tmp_path):
    # A task with no worklogs: the editor shows "(no sessions)" and a/e/x are
    # safe no-ops when nothing is highlighted.
    ctx = _make_ctx_with_task_worklogs(tmp_path, [])

    async def scenario() -> None:
        app = DotoApp(ctx)
        app.scope = DisplayScope.LOCAL  # highlight the current repo's seeded doto
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("t", "e")  # time stream -> edit sessions
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, TaskSessionsScreen)
            labels = [
                str(label.render())
                for label in screen.query_one("#tasksessions-list", ListView).query(Label)
            ]
            assert any("(no sessions)" in text for text in labels)
            # e and x with no highlighted session are safe no-ops: the screen
            # stays open and the store keeps its empty worklog list.
            await pilot.press("e")
            await pilot.pause()
            assert isinstance(app.screen, TaskSessionsScreen)
            await pilot.press("x")
            await pilot.pause()
            assert isinstance(app.screen, TaskSessionsScreen)
            assert ctx.store.get_task("1")["worklogs"] == []

    _run(scenario())


def test_collect_repo_tasks_skips_missing_store(tmp_path):
    # A registered repo whose tasks.json does not exist is skipped silently.
    ctx = _make_ctx(tmp_path)
    from doxtr_doto.cli.repo_registry import DiscoveredRepo

    missing_root = tmp_path / "ghost-repo"
    state = ctx.global_store.load()
    state.repositories.append(DiscoveredRepo(name="ghost", path=str(missing_root)).to_dict())
    ctx.global_store.save(state)
    # No .doto/tasks.json under missing_root -> the collector skips it without
    # raising, still returning the current repo's worked task.
    tuples = collect_repo_tasks(ctx)
    repos = {t[0] for t in tuples}
    assert "ghost" not in repos
    assert any(t[1] == "1" for t in tuples)


def test_collect_repo_tasks_skips_unreadable_store(tmp_path):
    # A registered repo whose store cannot be read is skipped silently.
    ctx = _make_ctx(tmp_path)
    other_root = tmp_path / "broken-repo"
    other_store_dir = other_root / ".doto"
    other_store_dir.mkdir(parents=True)
    # Write a tasks.json that JsonTaskStore.get_all_tasks will fail to parse.
    (other_store_dir / "tasks.json").write_text("{ not valid json", encoding="utf-8")
    from doxtr_doto.cli.repo_registry import DiscoveredRepo

    state = ctx.global_store.load()
    state.repositories.append(DiscoveredRepo(name="broken", path=str(other_root)).to_dict())
    ctx.global_store.save(state)
    tuples = collect_repo_tasks(ctx)
    repos = {t[0] for t in tuples}
    assert "broken" not in repos
    assert any(t[1] == "1" for t in tuples)


# ── render_time_spent_line (TUI card viewer "Time spent" field) ──────────────


def test_render_time_spent_line_omits_when_no_worklogs():
    """No worklogs -> no line (the field only appears with tracked time)."""
    assert render_time_spent_line([]) is None


def test_render_time_spent_line_omits_when_zero_elapsed():
    """Worklogs that sum to zero elapsed -> no line (omit rather than ``0s``)."""
    logs = [{"started_at": _ts(9, 0), "stopped_at": _ts(9, 0)}]
    assert render_time_spent_line(logs) is None


def test_render_time_spent_line_nonzero_closed_interval():
    """A closed interval renders ``Time spent: <duration>``."""
    from rich.text import Text

    logs = [{"started_at": _ts(9, 0), "stopped_at": _ts(10, 0)}]
    line = render_time_spent_line(logs)
    assert line is not None
    plain = Text.from_markup(line).plain
    assert "Time spent:" in plain
    assert format_duration(3600) in plain


def test_render_time_spent_line_open_session_counts_to_now():
    """An open (running) session is counted up to ``now`` (live elapsed)."""
    from rich.text import Text

    now = datetime(2026, 6, 1, 11, 0, tzinfo=timezone.utc)
    logs = [{"started_at": _ts(9, 0), "stopped_at": None}]
    line = render_time_spent_line(logs, now=now)
    assert line is not None
    plain = Text.from_markup(line).plain
    # 2h elapsed from 09:00 to the 11:00 reference "now".
    assert format_duration(2 * 3600) in plain


def test_render_time_spent_renderer_seam():
    """The ``Time spent`` renderer is overridable via register/reset."""
    from doxtr_doto.cli.session import (
        register_time_spent_renderer,
        reset_time_spent_renderer,
    )

    try:
        calls: list[object] = []

        def stub(worklogs, now=None):
            calls.append((worklogs, now))
            return "STUB-TIME"

        register_time_spent_renderer(stub)
        logs = [{"started_at": _ts(9, 0), "stopped_at": _ts(10, 0)}]
        assert render_time_spent_line(logs) == "STUB-TIME"
        assert calls == [(logs, None)]
    finally:
        reset_time_spent_renderer()

    # After reset the default renderer is active again.
    logs = [{"started_at": _ts(9, 0), "stopped_at": _ts(10, 0)}]
    assert "Time spent:" in str(render_time_spent_line(logs))
