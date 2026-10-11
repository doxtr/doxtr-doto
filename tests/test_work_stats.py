"""Tests for the work-time summary panel and statistics pop-up.

Covers the pure, Textual-free helpers (the text bar-chart renderer, the
week/month/year summary computation and the stats granularity/anchor helpers)
plus Pilot tests that the stats pop-up opens from the ``time`` layout and the
summary panel renders the week/month/year groups.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from pathlib import Path

from doxtr_doto.cli.config import DotoConfig
from doxtr_doto.cli.global_state import BreakConfig, GlobalStateStore
from doxtr_doto.cli.json_store import JsonTaskStore
from doxtr_doto.cli.main import DotoContext
from doxtr_doto.cli.output import OutputFormatter
from doxtr_doto.cli.tui.app import DotoApp
from doxtr_doto.cli.tui.time_mgmt import (
    BAR_CHAR,
    STATS_GRANULARITIES,
    WorkStatsScreen,
    anchor_range_for,
    build_week_day_distribution,
    render_bar_chart,
    shift_anchor,
)
from doxtr_doto.cli.tui.widgets import (
    WorkTimeSummary,
    weekday_range_label,
    workweek_net_seconds,
)
from doxtr_doto.enums import TuiLayout
from doxtr_doto.work_report import BreakSpec

TZ = timezone.utc


def _ts(h: int, m: int, day: int = 1, month: int = 6) -> str:
    return datetime(2026, month, day, h, m, tzinfo=TZ).isoformat()


# --- render_bar_chart (pure) ----------------------------------------------


def test_render_bar_chart_empty_rows():
    assert render_bar_chart([]) == []


def test_render_bar_chart_scales_against_max():
    lines = render_bar_chart([("A", 100), ("B", 50), ("C", 0)], width=10)
    assert len(lines) == 3
    # The max value gets a full-width bar.
    assert lines[0].count(BAR_CHAR) == 10
    # Half the max gets a half-width bar.
    assert lines[1].count(BAR_CHAR) == 5
    # Zero gets no bar.
    assert lines[2].count(BAR_CHAR) == 0
    # Labels and values are present.
    assert lines[0].startswith("A")
    assert lines[0].endswith("100")


def test_render_bar_chart_all_zero_no_divide_by_zero():
    lines = render_bar_chart([("A", 0), ("B", 0)], width=8)
    assert all(line.count(BAR_CHAR) == 0 for line in lines)
    assert lines[0].strip().endswith("0")


def test_render_bar_chart_value_formatter():
    from doxtr_doto.cli.session import format_duration

    lines = render_bar_chart([("Mon", 3600)], value_formatter=format_duration)
    assert lines[0].endswith("1h00m00s")


def test_render_bar_chart_label_padding_aligns_bars():
    lines = render_bar_chart([("Mon", 1), ("Wednesday", 1)], width=4)
    # Both bars start at the same column (labels padded to widest label).
    col0 = lines[0].index(BAR_CHAR)
    col1 = lines[1].index(BAR_CHAR)
    assert col0 == col1


# --- build_week_day_distribution (pure) -----------------------------------


def test_build_week_day_distribution_seven_rows_mon_first():
    # 2026-06-01 is a Monday.
    worklogs = [
        {"started_at": _ts(9, 0, day=1), "stopped_at": _ts(12, 0, day=1)},  # Mon 3h
        {"started_at": _ts(9, 0, day=3), "stopped_at": _ts(10, 0, day=3)},  # Wed 1h
    ]
    rows = build_week_day_distribution(
        worklogs, date(2026, 6, 1), [], now=datetime(2026, 6, 8, tzinfo=TZ)
    )
    assert [label for label, _ in rows] == [
        "Mon",
        "Tue",
        "Wed",
        "Thu",
        "Fri",
        "Sat",
        "Sun",
    ]
    assert rows[0][1] == 3 * 3600
    assert rows[2][1] == 1 * 3600
    assert rows[1][1] == 0


def test_build_week_day_distribution_deducts_breaks():
    worklogs = [
        {"started_at": _ts(9, 0, day=1), "stopped_at": _ts(13, 0, day=1)},  # 4h gross
    ]
    specs = [BreakSpec.from_config(BreakConfig("Lunch", "12:00", 60, 30, auto_deduct=True))]
    rows = build_week_day_distribution(
        worklogs, date(2026, 6, 1), specs, now=datetime(2026, 6, 8, tzinfo=TZ)
    )
    # 4h gross minus the full 60m break (worked straight through, auto_deduct
    # opted in) = 3h net.
    assert rows[0][1] == 3 * 3600


def test_build_week_day_distribution_default_break_no_deduction():
    # The default (recorded) break does NOT auto-deduct: net equals gross for
    # a straight-through day.
    worklogs = [
        {"started_at": _ts(9, 0, day=1), "stopped_at": _ts(13, 0, day=1)},  # 4h gross
    ]
    specs = [BreakSpec.from_config(BreakConfig("Lunch", "12:00", 60, 30))]
    rows = build_week_day_distribution(
        worklogs, date(2026, 6, 1), specs, now=datetime(2026, 6, 8, tzinfo=TZ)
    )
    assert rows[0][1] == 4 * 3600


# --- anchor_range_for / shift_anchor (pure) -------------------------------


def test_anchor_range_for_each_granularity():
    anchor = date(2026, 6, 10)  # a Wednesday
    assert anchor_range_for("day", anchor) == (anchor, anchor)
    assert anchor_range_for("week", anchor) == (date(2026, 6, 8), date(2026, 6, 14))
    assert anchor_range_for("month", anchor) == (date(2026, 6, 1), date(2026, 6, 30))
    assert anchor_range_for("year", anchor) == (date(2026, 1, 1), date(2026, 12, 31))


def test_anchor_range_for_rejects_unknown():
    import pytest

    with pytest.raises(ValueError):
        anchor_range_for("decade", date(2026, 6, 10))


def test_shift_anchor_day():
    assert shift_anchor("day", date(2026, 6, 10), 1) == date(2026, 6, 11)
    assert shift_anchor("day", date(2026, 6, 10), -1) == date(2026, 6, 9)


def test_shift_anchor_week():
    assert shift_anchor("week", date(2026, 6, 10), 1) == date(2026, 6, 15)
    assert shift_anchor("week", date(2026, 6, 10), -1) == date(2026, 6, 1)


def test_shift_anchor_month_wraps_year():
    assert shift_anchor("month", date(2026, 12, 15), 1) == date(2027, 1, 1)
    assert shift_anchor("month", date(2026, 1, 15), -1) == date(2025, 12, 1)


def test_shift_anchor_year():
    assert shift_anchor("year", date(2026, 6, 10), 1) == date(2027, 1, 1)
    assert shift_anchor("year", date(2026, 6, 10), -1) == date(2025, 1, 1)


# --- WorkTimeSummary.summary_data (pure) ----------------------------------


def test_summary_data_week_month_year_groups():
    # now = Wed 2026-06-10; week = Mon 06-08 .. Sun 06-14.
    now = datetime(2026, 6, 10, 18, 0, tzinfo=TZ)
    worklogs = [
        # Inside the week (and month and year): 2h on 06-09.
        {"started_at": _ts(9, 0, day=9), "stopped_at": _ts(11, 0, day=9)},
        # Earlier in the month (not the week): 1h on 06-02.
        {"started_at": _ts(9, 0, day=2), "stopped_at": _ts(10, 0, day=2)},
        # Earlier in the year (not the month): 3h on 2026-03-01.
        {"started_at": _ts(9, 0, day=1, month=3), "stopped_at": _ts(12, 0, day=1, month=3)},
    ]
    data = WorkTimeSummary.summary_data(worklogs, [], now)
    assert [label for label, _ in data] == ["This week", "This month", "This year"]
    week_net = data[0][1][2]
    month_net = data[1][1][2]
    year_net = data[2][1][2]
    assert week_net == 2 * 3600
    assert month_net == 3 * 3600  # 2h (06-09) + 1h (06-02)
    assert year_net == 6 * 3600  # 3h + 2h + 1h


def test_format_summary_renders_three_groups():
    data = [
        ("This week", (3600, 0, 3600)),
        ("This month", (7200, 0, 7200)),
        ("This year", (10800, 0, 10800)),
    ]
    markup = WorkTimeSummary.format_summary(data)
    assert "This week" in markup
    assert "This month" in markup
    assert "This year" in markup
    assert "Net" in markup


# --- weekday_range_label (pure) -------------------------------------------


def test_weekday_range_label_contiguous_mon_fri():
    assert weekday_range_label([0, 1, 2, 3, 4]) == "Mon\u2013Fri"


def test_weekday_range_label_contiguous_unsorted_input():
    assert weekday_range_label([4, 0, 2, 1, 3]) == "Mon\u2013Fri"


def test_weekday_range_label_non_contiguous_lists_abbrevs():
    assert weekday_range_label([0, 2, 4]) == "Mon, Wed, Fri"


def test_weekday_range_label_single_day():
    assert weekday_range_label([2]) == "Wed"


def test_weekday_range_label_empty():
    assert weekday_range_label([]) == "(none)"


def test_weekday_range_label_includes_weekend():
    assert weekday_range_label([0, 1, 2, 3, 4, 5, 6]) == "Mon\u2013Sun"


# --- workweek_net_seconds (pure) ------------------------------------------


def test_workweek_net_seconds_default_excludes_weekend():
    # now = Wed 2026-06-10; week = Mon 06-08 .. Sun 06-14.
    now = datetime(2026, 6, 10, 18, 0, tzinfo=TZ)
    worklogs = [
        # Weekday work (Tue 06-09): 2h -> counts for Mon-Fri.
        {"started_at": _ts(9, 0, day=9), "stopped_at": _ts(11, 0, day=9)},
        # Saturday work (06-13): 3h -> excluded by the Mon-Fri default.
        {"started_at": _ts(9, 0, day=13), "stopped_at": _ts(12, 0, day=13)},
    ]
    net = workweek_net_seconds(worklogs, [], now, [0, 1, 2, 3, 4])
    assert net == 2 * 3600


def test_workweek_net_seconds_custom_set_includes_saturday():
    now = datetime(2026, 6, 10, 18, 0, tzinfo=TZ)
    worklogs = [
        {"started_at": _ts(9, 0, day=9), "stopped_at": _ts(11, 0, day=9)},
        {"started_at": _ts(9, 0, day=13), "stopped_at": _ts(12, 0, day=13)},
    ]
    # Mon-Fri plus Saturday now includes the 3h Saturday day.
    net = workweek_net_seconds(worklogs, [], now, [0, 1, 2, 3, 4, 5])
    assert net == (2 + 3) * 3600


def test_format_workweek_renders_label_and_net():
    markup = WorkTimeSummary.format_workweek(45000, [0, 1, 2, 3, 4])
    assert "Work week (Mon\u2013Fri)" in markup
    assert "Net" in markup
    assert "12h30m" in markup


def test_format_summary_includes_workweek_line_when_given():
    data = [("This week", (3600, 0, 3600))]
    markup = WorkTimeSummary.format_summary(data, 7200, [0, 1, 2, 3, 4])
    assert "Work week (Mon\u2013Fri)" in markup


def test_format_summary_omits_workweek_line_when_none():
    data = [("This week", (3600, 0, 3600))]
    markup = WorkTimeSummary.format_summary(data)
    assert "Work week" not in markup


# --- WorkStatsScreen format helpers (pure) --------------------------------


def test_format_stats_week_heading_and_bars():
    rows = [("Mon", 3600), ("Tue", 0)]
    body = WorkStatsScreen.format_stats("week", 3600, 0, 3600, rows)
    assert "distribution" in body
    assert "Net 1h00m00s" in body
    assert BAR_CHAR in body


def test_format_stats_empty_chart():
    body = WorkStatsScreen.format_stats("day", 0, 0, 0, [])
    assert "(no data)" in body


def test_format_stats_rejects_unknown_granularity():
    import pytest

    with pytest.raises(ValueError):
        WorkStatsScreen.format_stats("decade", 0, 0, 0, [])


def test_format_title_rejects_unknown_granularity():
    import pytest

    with pytest.raises(ValueError):
        WorkStatsScreen.format_title("decade", date(2026, 6, 1), date(2026, 6, 30))


def test_stats_granularities_order():
    assert STATS_GRANULARITIES == ("day", "week", "month", "year")


# --- App wiring (Textual pilot) -------------------------------------------


def _make_ctx(tmp_path: Path, worklogs: list[dict[str, object]]) -> DotoContext:
    store_dir = tmp_path / ".doto"
    store_dir.mkdir()
    store = JsonTaskStore(store_dir / "tasks.json")
    global_store = GlobalStateStore(tmp_path / "global.json")
    state = global_store.load()
    state.work_clock.worklogs = list(worklogs)
    from doxtr_doto.cli.tui import nudge

    state.last_prompt_date = nudge.today_iso()
    global_store.save(state)
    return DotoContext(
        config=DotoConfig(),
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


def test_summary_panel_renders_week_month_year(tmp_path):
    worklogs = [{"started_at": _ts(9, 0, 1), "stopped_at": _ts(12, 0, 1)}]
    ctx = _make_ctx(tmp_path, worklogs)

    async def scenario() -> None:
        app = DotoApp(ctx)
        async with app.run_test() as pilot:
            await pilot.pause()
            await _cycle_to_time(app, pilot)
            summary = app.query_one(app.work_time_summary_class)
            text = str(summary.render())
            assert "This week" in text
            assert "This month" in text
            assert "This year" in text

    _run(scenario())


def test_stats_popup_opens_from_time_layout(tmp_path):
    worklogs = [{"started_at": _ts(9, 0, 1), "stopped_at": _ts(12, 0, 1)}]
    ctx = _make_ctx(tmp_path, worklogs)

    async def scenario() -> None:
        app = DotoApp(ctx)
        async with app.run_test() as pilot:
            await pilot.pause()
            await _cycle_to_time(app, pilot)
            await pilot.press("S", "w")  # stats stream -> work stats
            await pilot.pause()
            assert isinstance(app.screen, WorkStatsScreen)
            # The weekday-distribution chart (default week granularity) renders.
            # The seeded fixture has work in the period, so a bar must appear.
            content = str(app.screen.query_one("#workstats-content").render())
            assert BAR_CHAR in content

    _run(scenario())


def test_stats_popup_granularity_and_anchor_moves(tmp_path):
    worklogs = [{"started_at": _ts(9, 0, 1), "stopped_at": _ts(12, 0, 1)}]
    ctx = _make_ctx(tmp_path, worklogs)

    async def scenario() -> None:
        app = DotoApp(ctx)
        async with app.run_test() as pilot:
            await pilot.pause()
            await _cycle_to_time(app, pilot)
            await pilot.press("S", "w")  # stats stream -> work stats
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, WorkStatsScreen)
            assert screen.granularity == "week"
            anchor_before = screen.anchor
            # Switch granularity to month, then move to the previous period.
            await pilot.press("m")
            await pilot.pause()
            assert screen.granularity == "month"
            await pilot.press("left")
            await pilot.pause()
            assert screen.anchor < anchor_before
            # Cycle granularity with g (month -> year).
            await pilot.press("g")
            await pilot.pause()
            assert screen.granularity == "year"

    _run(scenario())


def test_stats_popup_opens_outside_time_layout(tmp_path):
    # The stats stream (``S``) is advertised globally in the hint bar, so
    # ``S w`` must open the work-stats pop-up from any layout - including the
    # default TABLE layout - not only the TIME layout.
    worklogs = [{"started_at": _ts(9, 0, 1), "stopped_at": _ts(12, 0, 1)}]
    ctx = _make_ctx(tmp_path, worklogs)

    async def scenario() -> None:
        app = DotoApp(ctx)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.layout_view is TuiLayout.TABLE
            await pilot.press("S")  # arm the stats prefix
            await pilot.pause()
            await pilot.press("w")  # -> work stats
            await pilot.pause()
            assert isinstance(app.screen, WorkStatsScreen)

    _run(scenario())


def test_summary_panel_refreshes_after_work_time_manager_closes(tmp_path):
    # Opening the work-time manager (t), adding+saving a new interval, then
    # closing the manager must refresh the time-layout summary panel so its
    # net total reflects the newly added interval.
    from datetime import datetime as _dt
    from datetime import time as _time

    from doxtr_doto.cli.session import format_duration
    from doxtr_doto.cli.tui.time_mgmt import WorkIntervalEditScreen, WorkTimeScreen

    ctx = _make_ctx(tmp_path, [])

    async def scenario() -> None:
        app = DotoApp(ctx)
        async with app.run_test() as pilot:
            await pilot.pause()
            await _cycle_to_time(app, pilot)
            summary = app.query_one(app.work_time_summary_class)
            # The empty fixture has no work, so no non-zero duration is shown.
            today = _dt.now().astimezone().date()
            tz = _dt.now().astimezone().tzinfo
            # Open the work-time manager for today.
            await pilot.press("t", "w")  # time stream -> manage work time
            await pilot.pause()
            assert isinstance(app.screen, WorkTimeScreen)
            app.screen.day = today
            app.screen._refresh()
            await pilot.pause()
            # Add a new interval and fill the editor directly, then save.
            await pilot.press("a")
            await pilot.pause()
            editor = app.screen
            assert isinstance(editor, WorkIntervalEditScreen)
            start_iso = _dt.combine(today, _time(9, 0), tzinfo=tz).isoformat()
            stop_iso = _dt.combine(today, _time(17, 0), tzinfo=tz).isoformat()
            editor.query_one("#interval-start").value = start_iso
            editor.query_one("#interval-stop").value = stop_iso
            await pilot.click("#interval-save")
            await pilot.pause()
            # Back on the manager; close it.
            assert isinstance(app.screen, WorkTimeScreen)
            await pilot.press("escape")
            await pilot.pause()
            # The summary panel now reflects the 8h net total just added.
            text = str(summary.render())
            assert format_duration(8 * 3600) in text

    _run(scenario())


# --- WorkTimeSummary.rebuild work-week line (Textual pilot) ----------------


def _summary_harness_app():
    from textual.app import App

    from doxtr_doto.cli.tui.widgets import WorkTimeSummary

    class _Harness(App):
        def compose(self):
            yield WorkTimeSummary(id="summary-under-test")

    return _Harness()


def test_summary_rebuild_renders_workweek_line():
    now = datetime(2026, 6, 10, 18, 0, tzinfo=TZ)
    worklogs = [{"started_at": _ts(9, 0, day=9), "stopped_at": _ts(11, 0, day=9)}]

    async def scenario() -> None:
        app = _summary_harness_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            summary = app.query_one("#summary-under-test")
            summary.rebuild(worklogs, [], now, [0, 1, 2, 3, 4])
            await pilot.pause()
            text = str(summary.render())
            assert "Work week (Mon\u2013Fri)" in text
            # Tue 06-09 2h net counts under Mon-Fri.
            assert "2h00m" in text

    _run(scenario())


def test_summary_rebuild_non_default_workweek_changes_total():
    now = datetime(2026, 6, 10, 18, 0, tzinfo=TZ)
    worklogs = [
        {"started_at": _ts(9, 0, day=9), "stopped_at": _ts(11, 0, day=9)},  # Tue 2h
        {"started_at": _ts(9, 0, day=13), "stopped_at": _ts(12, 0, day=13)},  # Sat 3h
    ]

    async def scenario() -> None:
        app = _summary_harness_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            summary = app.query_one("#summary-under-test")
            # Mon-Fri default: Saturday's 3h is excluded -> 2h total.
            summary.rebuild(worklogs, [], now, [0, 1, 2, 3, 4])
            await pilot.pause()
            default_text = str(summary.render())
            assert "2h00m" in default_text
            # Including Saturday adds the 3h day -> 5h total.
            summary.rebuild(worklogs, [], now, [0, 1, 2, 3, 4, 5])
            await pilot.pause()
            custom_text = str(summary.render())
            assert "5h00m" in custom_text
            assert "Work week (Mon\u2013Sat)" in custom_text

    _run(scenario())
