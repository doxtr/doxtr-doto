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
