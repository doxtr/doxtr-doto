"""Tests for the ``time`` TUI layout (:class:`...tui.widgets.TimeView`).

Covers the pure rendering/navigation contract of the view and the app-level
wiring: cycling to the time layout with ``v`` and opening the work-time
manager for the selected day with ``Enter``.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from pathlib import Path

from doxtr_doto.cli.config import DotoConfig
from doxtr_doto.cli.global_state import GlobalStateStore
from doxtr_doto.cli.json_store import JsonTaskStore
from doxtr_doto.cli.main import DotoContext
from doxtr_doto.cli.output import OutputFormatter
from doxtr_doto.cli.tui.app import DotoApp
from doxtr_doto.cli.tui.time_mgmt import WorkTimeScreen
from doxtr_doto.cli.tui.widgets import TimeView
from doxtr_doto.enums import TuiLayout

TZ = timezone.utc


def _ts(h: int, m: int, day: int = 1) -> str:
    return datetime(2026, 6, day, h, m, tzinfo=TZ).isoformat()


# --- Pure view contract ---------------------------------------------------


def test_time_view_groups_days_newest_first_and_totals():
    worklogs = [
        {"started_at": _ts(9, 0, 1), "stopped_at": _ts(12, 0, 1)},
        {"started_at": _ts(13, 0, 1), "stopped_at": _ts(14, 30, 1)},
        {"started_at": _ts(10, 0, 2), "stopped_at": _ts(11, 0, 2)},
    ]
    view = TimeView()
    view.rebuild(worklogs, [], now=datetime(2026, 6, 3, tzinfo=TZ))
    assert [d.isoformat() for d in view.days] == ["2026-06-02", "2026-06-01"]
    # Grand total gross = 1h + 4h30m = 5h30m = 19800s.
    assert view._totals[0] == 19800
    assert view.selected_id() == "2026-06-02"
    text = view.rendered_text()
    assert "Net 5h30m00s" in text
    assert "Tue 2026-06-02" in text
    assert "Mon 2026-06-01" in text


def test_time_view_empty_state():
    view = TimeView()
    view.rebuild([], [])
    assert view.days == []
    assert view.selected_id() is None
    assert "No work-clock time recorded." in view.rendered_text()


def test_time_view_cursor_moves_and_preserves_by_date():
    worklogs = [
        {"started_at": _ts(9, 0, 1), "stopped_at": _ts(10, 0, 1)},
        {"started_at": _ts(9, 0, 2), "stopped_at": _ts(10, 0, 2)},
    ]
    view = TimeView()
    view.rebuild(worklogs, [], now=datetime(2026, 6, 3, tzinfo=TZ))
    # Newest first: index 0 is 06-02.
    assert view.selected_id() == "2026-06-02"
    view.move_cursor(1)
    assert view.selected_id() == "2026-06-01"
    # A rebuild preserves the selected day by date.
    view.rebuild(worklogs, [], now=datetime(2026, 6, 3, tzinfo=TZ))
    assert view.selected_id() == "2026-06-01"


def test_time_view_shows_recorded_break_not_nominal_deduction():
    # A break 12:55-13:34 (outside a 12:00 nominal window) is surfaced as the
    # real recorded gap (39m) and net equals gross: no phantom hour deducted.
    worklogs = [
        {"started_at": _ts(9, 0, 1), "stopped_at": _ts(12, 55, 1)},
        {"started_at": _ts(13, 34, 1), "stopped_at": _ts(18, 0, 1)},
    ]

    class _Lunch:
        name = "Lunch"
        time = "12:00"
        duration_minutes = 60
        leeway_minutes = 30
        auto_deduct = False

    view = TimeView()
    view.rebuild(worklogs, [_Lunch()], now=datetime(2026, 6, 2, tzinfo=TZ))
    gross, brk, net = view._totals
    expected_gross = (12 * 3600 + 55 * 60 - 9 * 3600) + (18 * 3600 - (13 * 3600 + 34 * 60))
    assert gross == expected_gross
    # The time view surfaces the real recorded break (39m), not a nominal hour.
    assert brk == 39 * 60
    assert net == expected_gross


def test_time_view_skips_unparseable_break():
    worklogs = [{"started_at": _ts(9, 0, 1), "stopped_at": _ts(12, 0, 1)}]

    class _BadBreak:
        name = "oops"
        time = "not-a-time"
        duration_minutes = 30
        leeway_minutes = 15

    view = TimeView()
    # Must not raise; the bad break is simply skipped.
    view.rebuild(worklogs, [_BadBreak()], now=datetime(2026, 6, 2, tzinfo=TZ))
    assert view._totals[0] == 3 * 3600


# --- App wiring (Textual pilot) -------------------------------------------


def _make_ctx(tmp_path: Path, worklogs: list[dict[str, object]]) -> DotoContext:
    store_dir = tmp_path / ".doto"
    store_dir.mkdir()
    store = JsonTaskStore(store_dir / "tasks.json")
    global_store = GlobalStateStore(tmp_path / "global.json")
    state = global_store.load()
    state.work_clock.worklogs = list(worklogs)
    # Suppress the once-per-day kickstart nudge so it doesn't intercept keys.
    from doxtr_doto.cli.tui import nudge

    state.last_prompt_date = nudge.today_iso()
    global_store.save(state)
    ctx = DotoContext(
        config=DotoConfig(),
        store=store,
        formatter=OutputFormatter(),
        global_store=global_store,
    )
    return ctx


def _run(coro) -> None:
    asyncio.run(coro)


def test_app_cycles_to_time_layout_and_enter_opens_manager(tmp_path):
    worklogs = [
        {"started_at": _ts(9, 0, 1), "stopped_at": _ts(12, 0, 1)},
    ]
    ctx = _make_ctx(tmp_path, worklogs)

    async def scenario() -> None:
        app = DotoApp(ctx)
        async with app.run_test() as pilot:
            await pilot.pause()
            # Cycle v until the time layout is active (table -> ... -> time).
            for _ in range(len(list(TuiLayout))):
                if app.layout_view is TuiLayout.TIME:
                    break
                await pilot.press("v")
                await pilot.pause()
            assert app.layout_view is TuiLayout.TIME
            time_view = app.query_one(app.time_view_class)
            assert time_view.selected_id() == "2026-06-01"
            # Enter opens the work-time manager for the selected day.
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, WorkTimeScreen)
            assert app.screen.day == date(2026, 6, 1)

    _run(scenario())


def test_breaks_config_screen_saves_work_length_settings(tmp_path):
    """The breaks/work-length config screen persists the new settings."""
    from doxtr_doto.cli.tui.time_mgmt import BreaksConfigScreen

    ctx = _make_ctx(tmp_path, [])

    async def scenario() -> None:
        app = DotoApp(ctx)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_configure_breaks()
            await pilot.pause()
            assert isinstance(app.screen, BreaksConfigScreen)
            screen = app.screen
            # Edit the three work-length fields.
            screen.query_one("#breaks-day-length").value = "8h24m"
            screen.query_one("#breaks-week-length").value = "40h"
            screen.query_one("#breaks-holiday").value = "27.5"
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()

        state = ctx.global_store.load()
        assert state.day_length_minutes == 504
        assert state.week_length_minutes == 2400
        assert state.holiday_allowance_days == 27.5

    _run(scenario())


def test_breaks_config_screen_prefills_current_settings(tmp_path):
    from doxtr_doto.cli.tui.time_mgmt import BreaksConfigScreen

    ctx = _make_ctx(tmp_path, [])
    state = ctx.global_store.load()
    state.day_length_minutes = 450  # 7h30m
    state.week_length_minutes = 2250  # 37h30m
    state.holiday_allowance_days = 30.0
    ctx.global_store.save(state)

    async def scenario() -> None:
        app = DotoApp(ctx)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_configure_breaks()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, BreaksConfigScreen)
            assert screen.query_one("#breaks-day-length").value == "7h30m"
            assert screen.query_one("#breaks-week-length").value == "37h30m"
            assert screen.query_one("#breaks-holiday").value == "30"

    _run(scenario())


# --- Leave visualization in the time view ---------------------------------


class _Leave:
    """Minimal LeaveEntry-like object for TimeView.rebuild tests."""

    def __init__(self, date, kind="holiday", fraction=1.0, note=""):
        self.date = date
        self.kind = kind
        self.fraction = fraction
        self.note = note


def test_time_view_shows_leave_only_day():
    # A holiday with no work interval still appears as a day block.
    view = TimeView()
    view.rebuild(
        [],
        [],
        now=datetime(2026, 6, 3, tzinfo=TZ),
        leave=[_Leave("2026-06-02", "holiday", note="Summer")],
    )
    assert [d.isoformat() for d in view.days] == ["2026-06-02"]
    text = view.rendered_text()
    assert "Holiday" in text
    assert "Summer" in text


def test_time_view_sick_day_marker_on_worked_day():
    worklogs = [{"started_at": _ts(9, 0, 2), "stopped_at": _ts(11, 0, 2)}]
    view = TimeView()
    view.rebuild(
        worklogs,
        [],
        now=datetime(2026, 6, 3, tzinfo=TZ),
        leave=[_Leave("2026-06-02", "sick", fraction=0.5)],
    )
    text = view.rendered_text()
    assert "Sick day (half day)" in text


def test_time_view_day_height_accounts_for_leave_lines():
    # One interval + two leave markers: header + 1 interval + 2 leave + total + blank.
    assert TimeView.day_height(1, 2) == 1 + 1 + 2 + 1 + 1


def test_time_view_leave_day_navigable():
    view = TimeView()
    view.rebuild(
        [{"started_at": _ts(9, 0, 1), "stopped_at": _ts(10, 0, 1)}],
        [],
        now=datetime(2026, 6, 3, tzinfo=TZ),
        leave=[_Leave("2026-06-02", "holiday")],
    )
    # Both the worked day and the leave-only day are present, newest first.
    assert [d.isoformat() for d in view.days] == ["2026-06-02", "2026-06-01"]
    view.move_cursor(1)
    assert view.selected_id() == "2026-06-01"


def test_leave_config_screen_records_period(tmp_path):
    """The leave configurator records a holiday period into global state."""
    from doxtr_doto.cli.tui.time_mgmt import LeaveConfigScreen

    ctx = _make_ctx(tmp_path, [])

    async def scenario() -> None:
        app = DotoApp(ctx)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_configure_leave()
            await pilot.pause()
            assert isinstance(app.screen, LeaveConfigScreen)
            screen = app.screen
            screen.query_one("#leave-start").value = "2026-07-06"  # Monday
            screen.query_one("#leave-end").value = "2026-07-10"  # Friday
            screen.query_one("#leave-kind").value = "holiday"
            screen.query_one("#leave-note").value = "Summer"
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()

        state = ctx.global_store.load()
        dates = sorted(e.date for e in state.leave_days)
        assert dates == [
            "2026-07-06",
            "2026-07-07",
            "2026-07-08",
            "2026-07-09",
            "2026-07-10",
        ]
        assert all(e.kind == "holiday" for e in state.leave_days)
        assert all(e.note == "Summer" for e in state.leave_days)

    _run(scenario())


def test_leave_config_screen_sick_half_day(tmp_path):
    from doxtr_doto.cli.tui.time_mgmt import LeaveConfigScreen

    ctx = _make_ctx(tmp_path, [])

    async def scenario() -> None:
        app = DotoApp(ctx)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_configure_leave()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, LeaveConfigScreen)
            screen.query_one("#leave-start").value = "2026-07-06"
            screen.query_one("#leave-kind").value = "sick"
            screen.query_one("#leave-half").value = "yes"
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()

        state = ctx.global_store.load()
        assert len(state.leave_days) == 1
        entry = state.leave_days[0]
        assert entry.date == "2026-07-06"
        assert entry.kind == "sick"
        assert entry.fraction == 0.5

    _run(scenario())


def test_leave_config_screen_invalid_date_keeps_open(tmp_path):
    from doxtr_doto.cli.tui.time_mgmt import LeaveConfigScreen

    ctx = _make_ctx(tmp_path, [])

    async def scenario() -> None:
        app = DotoApp(ctx)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_configure_leave()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, LeaveConfigScreen)
            screen.query_one("#leave-start").value = "not-a-date"
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()
            # Parse error keeps the modal open and records nothing.
            assert isinstance(app.screen, LeaveConfigScreen)

        state = ctx.global_store.load()
        assert state.leave_days == []

    _run(scenario())


def test_top_bar_shows_next_holiday_after_recording(tmp_path):
    """Recording a leave period updates the top-bar next-leave display."""
    from doxtr_doto.cli.global_state import LeaveEntry
    from doxtr_doto.cli.tui.widgets import NextHolidayLine

    ctx = _make_ctx(tmp_path, [])
    # Seed a far-future holiday so it is always "upcoming" regardless of today.
    state = ctx.global_store.load()
    state.leave_days = [
        LeaveEntry(date=f"2099-07-0{d}", kind="holiday", note="Summer") for d in (6, 7, 8)
    ]
    ctx.global_store.save(state)

    async def scenario() -> None:
        app = DotoApp(ctx)
        async with app.run_test() as pilot:
            await pilot.pause()
            line = app.query_one(NextHolidayLine)
            rendered = str(line.render())
            assert "Holiday" in rendered
            assert "2099-07-06" in rendered
            assert "Summer" in rendered

    _run(scenario())


def test_top_bar_next_holiday_none_when_no_leave(tmp_path):
    from doxtr_doto.cli.tui.widgets import NextHolidayLine

    ctx = _make_ctx(tmp_path, [])

    async def scenario() -> None:
        app = DotoApp(ctx)
        async with app.run_test() as pilot:
            await pilot.pause()
            line = app.query_one(NextHolidayLine)
            assert "none" in str(line.render())

    _run(scenario())


def test_top_bar_updates_after_leave_configurator(tmp_path):
    from doxtr_doto.cli.tui.time_mgmt import LeaveConfigScreen
    from doxtr_doto.cli.tui.widgets import NextHolidayLine

    ctx = _make_ctx(tmp_path, [])

    async def scenario() -> None:
        app = DotoApp(ctx)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert "none" in str(app.query_one(NextHolidayLine).render())
            app.action_configure_leave()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, LeaveConfigScreen)
            screen.query_one("#leave-start").value = "2099-12-24"
            screen.query_one("#leave-end").value = "2099-12-26"
            screen.query_one("#leave-note").value = "Winter"
            screen.query_one("#leave-weekends").value = "yes"
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()
            rendered = str(app.query_one(NextHolidayLine).render())
            assert "2099-12-24" in rendered
            assert "Winter" in rendered

    _run(scenario())
