"""Tests for the TUI time-management helpers (:mod:`...tui.time_mgmt`)."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from doxtr_doto.cli.global_state import BreakConfig
from doxtr_doto.cli.tui.time_mgmt import (
    BREAKS_EXAMPLE_HEADER,
    WorkIntervalEditScreen,
    WorkTimeScreen,
    apply_interval_edit,
    format_breaks_text,
    format_workweek_text,
    interval_duration_seconds,
    intervals_for_day,
    parse_breaks_text,
    parse_workweek_text,
)
from doxtr_doto.time_tracking import add_interval, remove_interval, set_interval

TZ = timezone.utc


def _ts(h: int, m: int, day: int = 1) -> str:
    return datetime(2026, 6, day, h, m, tzinfo=TZ).isoformat()


def test_breaks_round_trip_text():
    breaks = [
        BreakConfig("Lunch", "12:00", 60, 30),
        BreakConfig("Dinner", "18:30", 45, 20),
    ]
    text = format_breaks_text(breaks)
    assert parse_breaks_text(text) == breaks


def test_parse_breaks_default_leeway():
    out = parse_breaks_text("Tea,15:00,15")
    assert out == [BreakConfig("Tea", "15:00", 15, 30)]
    assert out[0].auto_deduct is False


def test_parse_breaks_auto_flag_yes():
    out = parse_breaks_text("Lunch,12:00,60,30,yes")
    assert out == [BreakConfig("Lunch", "12:00", 60, 30, auto_deduct=True)]


def test_parse_breaks_auto_flag_accepts_synonyms():
    for token in ("yes", "y", "true", "1", "auto"):
        out = parse_breaks_text(f"Lunch,12:00,60,30,{token}")
        assert out[0].auto_deduct is True
    for token in ("no", "n", "false", "0"):
        out = parse_breaks_text(f"Lunch,12:00,60,30,{token}")
        assert out[0].auto_deduct is False


def test_parse_breaks_auto_flag_rejects_bad_token():
    with pytest.raises(ValueError):
        parse_breaks_text("Lunch,12:00,60,30,maybe")


def test_format_breaks_emits_auto_only_when_enabled():
    breaks = [
        BreakConfig("Lunch", "12:00", 60, 30),
        BreakConfig("Dinner", "18:30", 45, 20, auto_deduct=True),
    ]
    text = format_breaks_text(breaks)
    lines = text.splitlines()
    assert lines[0] == "Lunch,12:00,60,30"
    assert lines[1] == "Dinner,18:30,45,20,yes"
    # Round-trips back to the same configs.
    assert parse_breaks_text(text) == breaks


def test_parse_breaks_ignores_blank_and_comment():
    out = parse_breaks_text("# header\n\nLunch,12:00,60,30\n")
    assert out == [BreakConfig("Lunch", "12:00", 60, 30)]


def test_parse_breaks_ignores_indented_comment():
    out = parse_breaks_text("   # indented comment\nLunch,12:00,60,30")
    assert out == [BreakConfig("Lunch", "12:00", 60, 30)]


def test_example_header_is_all_comments_and_parses_empty():
    # Every header line must be a comment so a round-trip ignores it.
    assert all(
        (not line.strip()) or line.strip().startswith("#")
        for line in BREAKS_EXAMPLE_HEADER.splitlines()
    )
    assert parse_breaks_text(BREAKS_EXAMPLE_HEADER) == []


def test_format_with_header_round_trips_to_rows_only():
    breaks = [BreakConfig("Lunch", "12:00", 60, 30)]
    text = format_breaks_text(breaks, include_header=True)
    assert text.startswith("#")  # header first
    assert parse_breaks_text(text) == breaks


def test_format_with_header_empty_breaks():
    text = format_breaks_text([], include_header=True)
    assert parse_breaks_text(text) == []


def test_parse_breaks_normalizes_time():
    out = parse_breaks_text("Lunch,9:5,60,30")
    assert out[0].time == "09:05"


@pytest.mark.parametrize(
    "line",
    [
        "Lunch,12:00",  # too few columns
        "Lunch,25:00,60",  # hour out of range
        "Lunch,12:99,60",  # minute out of range
        ",12:00,60",  # empty name
        "Lunch,12:00,-5",  # negative duration
        "Lunch,noon,60",  # non-numeric time
    ],
)
def test_parse_breaks_rejects_bad_lines(line):
    with pytest.raises(ValueError):
        parse_breaks_text(line)


def test_apply_interval_edit_add():
    out = apply_interval_edit([], None, _ts(9, 0), _ts(12, 0))
    assert len(out) == 1
    assert out[0]["started_at"].startswith("2026-06-01T09:00")
    assert out[0]["stopped_at"].startswith("2026-06-01T12:00")


def test_apply_interval_edit_open():
    out = apply_interval_edit([], None, _ts(9, 0), None)
    assert out[0]["stopped_at"] is None


def test_apply_interval_edit_replace():
    worklogs = [{"started_at": _ts(9, 0), "stopped_at": _ts(10, 0)}]
    out = apply_interval_edit(worklogs, 0, _ts(9, 0), _ts(11, 0))
    assert out[0]["stopped_at"].startswith("2026-06-01T11:00")
    # original untouched (pure)
    assert worklogs[0]["stopped_at"].startswith("2026-06-01T10:00")


def test_apply_interval_edit_rejects_stop_before_start():
    with pytest.raises(ValueError):
        apply_interval_edit([], None, _ts(12, 0), _ts(9, 0))


def test_apply_interval_edit_rejects_bad_timestamp():
    with pytest.raises(ValueError):
        apply_interval_edit([], None, "not-a-date", None)


def test_intervals_for_day_preserves_global_index():
    worklogs = [
        {"started_at": _ts(9, 0, day=1), "stopped_at": _ts(10, 0, day=1)},
        {"started_at": _ts(9, 0, day=2), "stopped_at": _ts(10, 0, day=2)},
        {"started_at": _ts(11, 0, day=1), "stopped_at": _ts(12, 0, day=1)},
    ]
    rows = intervals_for_day(worklogs, date(2026, 6, 1))
    assert [idx for idx, _ in rows] == [0, 2]


def test_set_remove_add_primitives():
    worklogs = [{"started_at": _ts(9, 0), "stopped_at": _ts(10, 0)}]
    edited = set_interval(worklogs, 0, _ts(9, 0), _ts(11, 0))
    assert edited[0]["stopped_at"].endswith("11:00:00+00:00")

    added = add_interval(worklogs, _ts(8, 0), _ts(8, 30))
    assert len(added) == 2
    # re-sorted by start
    assert added[0]["started_at"].endswith("08:00:00+00:00")

    removed = remove_interval(worklogs, 0)
    assert removed == []

    with pytest.raises(IndexError):
        remove_interval([], 0)


# --- interval_duration_seconds (pure) -------------------------------------


def test_interval_duration_seconds_valid():
    assert interval_duration_seconds(_ts(9, 0), _ts(10, 42)) == 102 * 60


def test_interval_duration_seconds_blank_stop_is_none():
    assert interval_duration_seconds(_ts(9, 0), None) is None
    assert interval_duration_seconds(_ts(9, 0), "") is None
    assert interval_duration_seconds(_ts(9, 0), "   ") is None


def test_interval_duration_seconds_blank_start_is_none():
    assert interval_duration_seconds("", _ts(10, 0)) is None
    assert interval_duration_seconds("   ", _ts(10, 0)) is None


def test_interval_duration_seconds_unparseable_is_none():
    assert interval_duration_seconds("not-a-date", _ts(10, 0)) is None
    assert interval_duration_seconds(_ts(9, 0), "not-a-date") is None


def test_interval_duration_seconds_stop_not_after_start_is_none():
    assert interval_duration_seconds(_ts(10, 0), _ts(9, 0)) is None
    assert interval_duration_seconds(_ts(10, 0), _ts(10, 0)) is None


# --- parse_workweek_text / format_workweek_text (pure) --------------------


def test_parse_workweek_numeric_csv():
    assert parse_workweek_text("0,1,2,3,4") == [0, 1, 2, 3, 4]


def test_parse_workweek_numeric_range():
    assert parse_workweek_text("0-4") == [0, 1, 2, 3, 4]


def test_parse_workweek_abbrev_range():
    assert parse_workweek_text("Mon-Fri") == [0, 1, 2, 3, 4]


def test_parse_workweek_abbrev_csv_case_insensitive():
    assert parse_workweek_text("mon,WED,fri") == [0, 2, 4]


def test_parse_workweek_dedupe_and_sort():
    assert parse_workweek_text("4,0,0,2") == [0, 2, 4]


def test_parse_workweek_reversed_range():
    assert parse_workweek_text("Fri-Mon") == [0, 1, 2, 3, 4]


def test_parse_workweek_including_saturday():
    assert parse_workweek_text("Mon-Sat") == [0, 1, 2, 3, 4, 5]


@pytest.mark.parametrize("text", ["", "   ", "7", "-1", "funday", "Mon,xyz"])
def test_parse_workweek_rejects_invalid(text):
    with pytest.raises(ValueError):
        parse_workweek_text(text)


def test_format_workweek_text_sorts_dedupes():
    assert format_workweek_text([4, 0, 2, 2]) == "0,2,4"


def test_format_workweek_round_trips_through_parse():
    assert parse_workweek_text(format_workweek_text([0, 1, 2, 3, 4])) == [0, 1, 2, 3, 4]


# --- WorkTimeScreen interaction (Textual pilot) ---------------------------


class _FakeWorkClock:
    def __init__(self, worklogs):
        self.worklogs = worklogs


class _FakeState:
    def __init__(self, worklogs):
        self.work_clock = _FakeWorkClock(worklogs)


class _FakeGlobalStore:
    def __init__(self, worklogs):
        self._state = _FakeState(worklogs)

    def load(self):
        return self._state

    def save(self, state):
        self._state = state


class _FakeCtx:
    def __init__(self, worklogs):
        self.global_store = _FakeGlobalStore(worklogs)


def _harness_app(ctx, day):
    from textual.app import App

    class _Harness(App):
        def on_mount(self) -> None:
            self.push_screen(WorkTimeScreen(ctx, day))

    return _Harness()


def _run(coro) -> None:
    import asyncio

    asyncio.run(coro)


def test_worktime_screen_highlights_first_row_and_shows_total():
    from textual.widgets import ListView

    worklogs = [
        {"started_at": _ts(9, 0, day=1), "stopped_at": _ts(12, 0, day=1)},
        {"started_at": _ts(13, 0, day=1), "stopped_at": _ts(14, 30, day=1)},
    ]

    async def scenario() -> None:
        ctx = _FakeCtx(worklogs)
        app = _harness_app(ctx, date(2026, 6, 1))
        async with app.run_test() as pilot:
            await pilot.pause()
            list_view = app.screen.query_one("#worktime-list", ListView)
            # The first interval is highlighted so edit/delete have a target.
            assert list_view.index == 0
            assert getattr(list_view.highlighted_child, "worklog_index", None) == 0
            # The day's total work time (3h + 1h30m = 4h30m) is displayed.
            total = app.screen.query_one("#worktime-total").render()
            assert "4h30m" in str(total)

    _run(scenario())


def test_worktime_screen_enter_opens_editor():
    worklogs = [{"started_at": _ts(9, 0, day=1), "stopped_at": _ts(12, 0, day=1)}]

    async def scenario() -> None:
        ctx = _FakeCtx(worklogs)
        app = _harness_app(ctx, date(2026, 6, 1))
        async with app.run_test() as pilot:
            await pilot.pause()
            # Enter is consumed by the ListView's select binding, but the
            # resulting ListView.Selected message must still open the editor.
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, WorkIntervalEditScreen)

    _run(scenario())


def test_worktime_screen_edit_key_opens_editor():
    worklogs = [{"started_at": _ts(9, 0, day=1), "stopped_at": _ts(12, 0, day=1)}]

    async def scenario() -> None:
        ctx = _FakeCtx(worklogs)
        app = _harness_app(ctx, date(2026, 6, 1))
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("e")
            await pilot.pause()
            assert isinstance(app.screen, WorkIntervalEditScreen)

    _run(scenario())


def test_worktime_screen_empty_day_shows_zero_total():
    async def scenario() -> None:
        ctx = _FakeCtx([])
        app = _harness_app(ctx, date(2026, 6, 1))
        async with app.run_test() as pilot:
            await pilot.pause()
            total = app.screen.query_one("#worktime-total").render()
            assert "0s" in str(total)
            # Pressing edit with only the placeholder row is a safe no-op.
            await pilot.press("e")
            await pilot.pause()
            assert isinstance(app.screen, WorkTimeScreen)

    _run(scenario())


def test_worktime_screen_down_then_e_edits_second_interval():
    # Feature 2: the ListView must be focused on mount so Down moves the
    # highlight to the 2nd interval and ``e`` edits *that* row (previously the
    # highlight was stuck on row 0 and the 2nd interval could not be edited).
    worklogs = [
        {"started_at": _ts(9, 0, day=1), "stopped_at": _ts(12, 0, day=1)},
        {"started_at": _ts(13, 0, day=1), "stopped_at": _ts(14, 30, day=1)},
    ]

    async def scenario() -> None:
        ctx = _FakeCtx(worklogs)
        app = _harness_app(ctx, date(2026, 6, 1))
        async with app.run_test() as pilot:
            await pilot.pause()
            manager = app.screen
            assert isinstance(manager, WorkTimeScreen)
            # Move the highlight down to the 2nd interval, then edit it.
            await pilot.press("down")
            await pilot.pause()
            # _selected_index() tracks the 2nd interval's global index (1).
            assert manager._selected_index() == 1
            await pilot.press("e")
            await pilot.pause()
            editor = app.screen
            assert isinstance(editor, WorkIntervalEditScreen)
            # The editor is pre-filled with the SECOND interval's start (13:00).
            start_value = editor.query_one("#interval-start").value
            assert "13:00" in start_value

    _run(scenario())


def test_worktime_screen_j_k_navigation_edits_second_interval():
    # j/k also move the highlight (vim-style), mirroring Down/Up.
    worklogs = [
        {"started_at": _ts(9, 0, day=1), "stopped_at": _ts(12, 0, day=1)},
        {"started_at": _ts(13, 0, day=1), "stopped_at": _ts(14, 30, day=1)},
    ]

    async def scenario() -> None:
        ctx = _FakeCtx(worklogs)
        app = _harness_app(ctx, date(2026, 6, 1))
        async with app.run_test() as pilot:
            await pilot.pause()
            manager = app.screen
            assert isinstance(manager, WorkTimeScreen)
            await pilot.press("j")
            await pilot.pause()
            assert manager._selected_index() == 1
            await pilot.press("k")
            await pilot.pause()
            assert manager._selected_index() == 0

    _run(scenario())


# --- WorkIntervalEditScreen live duration field (Textual pilot) -----------


def _editor_harness_app(index, started_at, stopped_at):
    from textual.app import App

    class _Harness(App):
        def on_mount(self) -> None:
            self.push_screen(WorkIntervalEditScreen(index, started_at, stopped_at))

    return _Harness()


def test_interval_editor_shows_initial_duration():
    async def scenario() -> None:
        app = _editor_harness_app(0, _ts(9, 0), _ts(10, 42))
        async with app.run_test() as pilot:
            await pilot.pause()
            editor = app.screen
            assert isinstance(editor, WorkIntervalEditScreen)
            duration = str(editor.query_one("#interval-duration").render())
            # 9:00 -> 10:42 is 1h42m.
            assert "1h42m" in duration

    _run(scenario())


def test_interval_editor_duration_live_updates_on_stop_change():
    from textual.widgets import Input

    async def scenario() -> None:
        app = _editor_harness_app(0, _ts(9, 0), _ts(10, 42))
        async with app.run_test() as pilot:
            await pilot.pause()
            editor = app.screen
            stop_input = editor.query_one("#interval-stop", Input)
            # Nudge the stop time to 10:57 (1h57m).
            stop_input.value = _ts(10, 57)
            await pilot.pause()
            duration = str(editor.query_one("#interval-duration").render())
            assert "1h57m" in duration

    _run(scenario())


def test_interval_editor_duration_running_when_stop_blank():
    async def scenario() -> None:
        app = _editor_harness_app(None, _ts(9, 0), None)
        async with app.run_test() as pilot:
            await pilot.pause()
            editor = app.screen
            duration = str(editor.query_one("#interval-duration").render())
            assert "running" in duration

    _run(scenario())
