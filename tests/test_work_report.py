"""Tests for break-aware work reporting (:mod:`doxtr_doto.work_report`)."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from doxtr_doto.work_report import (
    BreakSpec,
    RecordedBreak,
    TimesheetRow,
    compute_day,
    compute_period,
    compute_task_breakdown,
    day_range,
    format_hhmm,
    month_range,
    round_to_quarter_hour,
    timesheet_csv,
    timesheet_matrix,
    timesheet_rows,
    week_range,
    work_span_seconds,
    year_range,
)

assert RecordedBreak is not None  # imported for the recorded-break assertions below

TZ = timezone.utc


def _ts(h: int, m: int, day: int = 1) -> str:
    """ISO timestamp on 2026-06-``day`` at ``h:m`` UTC."""
    return datetime(2026, 6, day, h, m, tzinfo=TZ).isoformat()


def _wl(start: str, stop: str | None) -> dict:
    return {"started_at": start, "stopped_at": stop}


# The default LUNCH break records real clock-out gaps and never deducts a
# nominal duration (the fixed behavior). LUNCH_AUTO opts into the legacy
# straight-through auto-deduction for the auto_deduct=True path tests.
LUNCH = BreakSpec(name="Lunch", hour=12, minute=0, duration_minutes=60, leeway_minutes=30)
LUNCH_AUTO = BreakSpec(
    name="Lunch", hour=12, minute=0, duration_minutes=60, leeway_minutes=30, auto_deduct=True
)
NOW = datetime(2026, 6, 1, 20, 0, tzinfo=TZ)
DAY = date(2026, 6, 1)


# --- Default behavior: recorded breaks, no phantom auto-deduction ---------


def test_default_break_outside_window_no_extra_deduction() -> None:
    # The reported bug: a break 12:55-13:34 falls OUTSIDE the 12:00 lunch
    # window+leeway (11:30-12:30). With the default (recorded) behavior the
    # 39-minute gap is already excluded from gross and NOTHING extra is
    # deducted - net equals gross.
    worklogs = [
        _wl(_ts(9, 0), _ts(12, 55)),
        _wl(_ts(13, 34), _ts(18, 0)),
    ]
    result = compute_day(worklogs, DAY, [LUNCH], NOW)
    gross_expected = (12 * 3600 + 55 * 60 - 9 * 3600) + (18 * 3600 - (13 * 3600 + 34 * 60))
    assert result.gross_seconds == gross_expected
    # No auto-deduction with the default break.
    assert result.total_break_seconds == 0
    # Net == gross: the hour break is NOT double-counted.
    assert result.net_seconds == gross_expected
    # The real break is surfaced as a recorded gap of 39 minutes.
    assert result.recorded_break_seconds == 39 * 60
    assert len(result.recorded_breaks) == 1
    rb = result.recorded_breaks[0]
    assert rb.start.hour == 12 and rb.start.minute == 55
    assert rb.stop.hour == 13 and rb.stop.minute == 34
    assert rb.seconds == 39 * 60


def test_default_straight_through_no_deduction() -> None:
    # Worked straight through with no clock-out: a default (non-auto) break
    # deducts nothing and there is no recorded gap.
    worklogs = [_wl(_ts(9, 0), _ts(19, 0))]
    result = compute_day(worklogs, DAY, [LUNCH], NOW)
    assert result.gross_seconds == 10 * 3600
    assert result.total_break_seconds == 0
    assert result.net_seconds == 10 * 3600
    assert result.recorded_breaks == []


def test_multiple_recorded_breaks_each_surfaced() -> None:
    # Two clock-out gaps become two recorded breaks (none deducted).
    worklogs = [
        _wl(_ts(9, 0), _ts(10, 30)),
        _wl(_ts(10, 45), _ts(13, 0)),
        _wl(_ts(13, 45), _ts(18, 0)),
    ]
    result = compute_day(worklogs, DAY, [LUNCH], NOW)
    assert result.total_break_seconds == 0
    assert [rb.seconds for rb in result.recorded_breaks] == [15 * 60, 45 * 60]
    assert result.recorded_break_seconds == 60 * 60


# --- Opt-in auto_deduct behavior (legacy straight-through) ----------------


def test_straight_through_deducts_full_break() -> None:
    # 09:00 - 19:00 continuous, no clock-out: full 60m lunch deducted (opt-in).
    worklogs = [_wl(_ts(9, 0), _ts(19, 0))]
    result = compute_day(worklogs, DAY, [LUNCH_AUTO], NOW)
    assert result.gross_seconds == 10 * 3600
    assert result.total_break_seconds == 60 * 60
    assert result.net_seconds == 9 * 3600


def test_partial_gap_only_deducts_remainder() -> None:
    # User's example: clock out 11:48, back in 12:45 => 57m gap already taken.
    # Only 60 - 57 = 3 minutes should be auto-deducted (opt-in).
    worklogs = [
        _wl(_ts(9, 0), _ts(11, 48)),
        _wl(_ts(12, 45), _ts(19, 0)),
    ]
    result = compute_day(worklogs, DAY, [LUNCH_AUTO], NOW)
    # Gross excludes the 57m gap already (it was not clocked).
    gross_expected = (11 * 3600 + 48 * 60 - 9 * 3600) + (19 * 3600 - (12 * 3600 + 45 * 60))
    assert result.gross_seconds == gross_expected
    assert result.total_break_seconds == 3 * 60
    assert result.net_seconds == gross_expected - 3 * 60
    # The gap is also surfaced as a recorded break of 57 minutes.
    assert result.recorded_break_seconds == 57 * 60


def test_long_gap_deducts_nothing_extra() -> None:
    # 90-minute lunch gap >= configured 60m: no extra auto-deduction.
    worklogs = [
        _wl(_ts(9, 0), _ts(11, 45)),
        _wl(_ts(13, 15), _ts(19, 0)),
    ]
    result = compute_day(worklogs, DAY, [LUNCH_AUTO], NOW)
    assert result.total_break_seconds == 0


def test_gap_at_window_edge_counts_as_break() -> None:
    # Gap starting at 11:30 (window start, 12:00 - 30m) is credited to lunch.
    worklogs = [
        _wl(_ts(9, 0), _ts(11, 30)),
        _wl(_ts(12, 0), _ts(19, 0)),
    ]
    result = compute_day(worklogs, DAY, [LUNCH_AUTO], NOW)
    # 30-minute gap credited; 60 - 30 = 30 auto-deducted.
    assert result.total_break_seconds == 30 * 60


def test_gap_starting_at_1230_counts() -> None:
    # Gap starting at 12:30 (window end) is still credited to lunch.
    worklogs = [
        _wl(_ts(9, 0), _ts(12, 30)),
        _wl(_ts(13, 0), _ts(19, 0)),
    ]
    result = compute_day(worklogs, DAY, [LUNCH_AUTO], NOW)
    assert result.total_break_seconds == 30 * 60


def test_gap_outside_window_not_credited() -> None:
    # A 30m gap at 15:00 is unrelated to lunch; full lunch still deducted
    # under the opt-in auto_deduct path.
    worklogs = [
        _wl(_ts(9, 0), _ts(15, 0)),
        _wl(_ts(15, 30), _ts(19, 0)),
    ]
    result = compute_day(worklogs, DAY, [LUNCH_AUTO], NOW)
    assert result.total_break_seconds == 60 * 60
    # The 30m gap is still recorded as a real break.
    assert result.recorded_break_seconds == 30 * 60


def test_deduction_never_negative() -> None:
    bigbreak = BreakSpec(
        name="Nap", hour=12, minute=0, duration_minutes=30, leeway_minutes=30, auto_deduct=True
    )
    worklogs = [
        _wl(_ts(9, 0), _ts(11, 45)),
        _wl(_ts(13, 15), _ts(19, 0)),  # 90m gap >> 30m break
    ]
    result = compute_day(worklogs, DAY, [bigbreak], NOW)
    assert result.total_break_seconds == 0
    assert result.net_seconds >= 0


def test_empty_day_no_deduction() -> None:
    result = compute_day([], DAY, [LUNCH], NOW)
    assert result.gross_seconds == 0
    assert result.total_break_seconds == 0
    assert result.net_seconds == 0
    assert result.recorded_breaks == []


def test_multiple_breaks_each_applied_once() -> None:
    breakfast = BreakSpec("Breakfast", 9, 30, 15, 30, auto_deduct=True)
    worklogs = [_wl(_ts(8, 0), _ts(19, 0))]
    result = compute_day(worklogs, DAY, [breakfast, LUNCH_AUTO], NOW)
    assert result.total_break_seconds == 15 * 60 + 60 * 60
    assert {d.name for d in result.break_deductions} == {"Breakfast", "Lunch"}


def test_period_aggregates_and_skips_empty_days() -> None:
    worklogs = [
        _wl(_ts(9, 0, day=1), _ts(19, 0, day=1)),
        _wl(_ts(9, 0, day=3), _ts(17, 0, day=3)),
    ]
    period = compute_period(worklogs, date(2026, 6, 1), date(2026, 6, 3), [LUNCH_AUTO], NOW)
    assert len(period.days) == 2  # day 2 skipped (no work)
    assert period.gross_seconds == 10 * 3600 + 8 * 3600
    assert period.break_seconds == 2 * 60 * 60  # lunch each day (auto-deducted)
    assert period.net_seconds == period.gross_seconds - period.break_seconds


def test_period_recorded_breaks_aggregate() -> None:
    # Default breaks: recorded gaps aggregate across days; nothing deducted.
    worklogs = [
        _wl(_ts(9, 0, day=1), _ts(12, 0, day=1)),
        _wl(_ts(12, 30, day=1), _ts(17, 0, day=1)),  # 30m gap on day 1
        _wl(_ts(9, 0, day=2), _ts(13, 0, day=2)),
        _wl(_ts(14, 0, day=2), _ts(18, 0, day=2)),  # 60m gap on day 2
    ]
    period = compute_period(worklogs, date(2026, 6, 1), date(2026, 6, 2), [LUNCH], NOW)
    assert period.break_seconds == 0
    assert period.recorded_break_seconds == 30 * 60 + 60 * 60
    assert period.net_seconds == period.gross_seconds


def test_open_session_closed_at_now() -> None:
    worklogs = [_wl(_ts(9, 0), None)]
    result = compute_day(worklogs, DAY, [], NOW)
    assert result.gross_seconds == 11 * 3600  # 09:00 -> 20:00 (now)


def test_overnight_clipped_per_day() -> None:
    # Session spanning midnight is attributed to each day it covers.
    worklogs = [
        _wl(
            datetime(2026, 6, 1, 22, 0, tzinfo=TZ).isoformat(),
            datetime(2026, 6, 2, 2, 0, tzinfo=TZ).isoformat(),
        )
    ]
    d1 = compute_day(worklogs, date(2026, 6, 1), [], NOW)
    d2 = compute_day(worklogs, date(2026, 6, 2), [], NOW)
    assert d1.gross_seconds == 2 * 3600
    assert d2.gross_seconds == 2 * 3600


def test_task_breakdown_separates_per_repo() -> None:
    tasks = [
        ("repo-a", "T1", "Alpha", [_wl(_ts(9, 0), _ts(10, 0))]),
        ("repo-a", "T2", "Beta", [_wl(_ts(10, 0), _ts(11, 30))]),
        ("repo-b", "T3", "Gamma", [_wl(_ts(13, 0), _ts(14, 0))]),
    ]
    bd = compute_task_breakdown(tasks, DAY, DAY, NOW)
    assert bd.per_repo == {"repo-a": 3600 + 90 * 60, "repo-b": 3600}
    assert bd.total_seconds == 3600 + 90 * 60 + 3600
    # Sorted descending: T2 (90m) first.
    assert bd.tasks[0].task_id == "T2"


def test_task_breakdown_skips_zero() -> None:
    tasks = [("r", "T1", "x", [_wl(_ts(9, 0, day=5), _ts(10, 0, day=5))])]
    bd = compute_task_breakdown(tasks, DAY, DAY, NOW)  # day 1, task on day 5
    assert bd.tasks == []


def test_range_helpers() -> None:
    assert day_range(date(2026, 6, 10)) == (date(2026, 6, 10), date(2026, 6, 10))
    # 2026-06-10 is a Wednesday -> week Mon 8th .. Sun 14th.
    assert week_range(date(2026, 6, 10)) == (date(2026, 6, 8), date(2026, 6, 14))
    assert month_range(date(2026, 6, 10)) == (date(2026, 6, 1), date(2026, 6, 30))
    assert month_range(date(2026, 12, 10)) == (date(2026, 12, 1), date(2026, 12, 31))
    assert year_range(2026) == (date(2026, 1, 1), date(2026, 12, 31))


def test_breakspec_from_config_validates() -> None:
    class Cfg:
        name = "Lunch"
        time = "12:30"
        duration_minutes = 45
        leeway_minutes = 20
        auto_deduct = True

    spec = BreakSpec.from_config(Cfg())
    assert (spec.hour, spec.minute, spec.duration_minutes, spec.leeway_minutes) == (12, 30, 45, 20)
    assert spec.auto_deduct is True

    class CfgDefault:
        name = "Lunch"
        time = "12:30"
        duration_minutes = 45
        leeway_minutes = 20

    # A config without an auto_deduct attribute defaults to False.
    assert BreakSpec.from_config(CfgDefault()).auto_deduct is False

    class Bad:
        name = "x"
        time = "nope"
        duration_minutes = 10
        leeway_minutes = 30

    with pytest.raises(ValueError):
        BreakSpec.from_config(Bad())


# --- Timesheet: quarter-hour rounding (midpoint rule) ---------------------


@pytest.mark.parametrize(
    ("minute", "second", "expected_hour", "expected_minute"),
    [
        # Within the :00-:15 window: < 7.5m rounds down, >= 7.5m rounds up.
        (0, 0, 10, 0),  # exact boundary stays
        (7, 0, 10, 0),  # :07 -> :00 (7m < 7.5m)
        (7, 29, 10, 0),  # :07:29 -> :00 (just below midpoint)
        (7, 30, 10, 15),  # :07:30 -> :15 (exactly at midpoint rounds up)
        (8, 0, 10, 15),  # :08 -> :15 (8m >= 7.5m)
        # Within the :30-:45 window.
        (43, 0, 10, 45),  # :43 -> :45
        (45, 0, 10, 45),  # :45 stays
        (37, 0, 10, 30),  # :37 -> :30 (offset 7m from :30)
        # Within the :45-:00 window: rounds up across the hour.
        (53, 0, 11, 0),  # :53 -> next hour :00 (offset 8m)
        (52, 0, 10, 45),  # :52 -> :45 (offset 7m)
    ],
)
def test_round_to_quarter_hour_midpoint(
    minute: int, second: int, expected_hour: int, expected_minute: int
) -> None:
    moment = datetime(2026, 6, 1, 10, minute, second, tzinfo=TZ)
    rounded = round_to_quarter_hour(moment)
    assert (rounded.hour, rounded.minute) == (expected_hour, expected_minute)
    assert rounded.second == 0 and rounded.microsecond == 0
    # tzinfo is preserved.
    assert rounded.tzinfo == TZ


def test_round_to_quarter_hour_preserves_tz_and_zeroes_subminute() -> None:
    moment = datetime(2026, 6, 1, 10, 8, 59, 123456, tzinfo=TZ)
    rounded = round_to_quarter_hour(moment)
    assert (rounded.hour, rounded.minute, rounded.second, rounded.microsecond) == (10, 15, 0, 0)


def test_round_to_quarter_hour_rolls_over_midnight() -> None:
    # Day-boundary roll-up: :53 on the last quarter of the day rounds up past
    # midnight to 00:00 of the next day (floor + timedelta handles the date
    # arithmetic). Guards the midnight-wrap regression.
    moment = datetime(2026, 6, 1, 23, 53, tzinfo=TZ)
    rounded = round_to_quarter_hour(moment)
    assert (rounded.date(), rounded.hour, rounded.minute) == (date(2026, 6, 2), 0, 0)
    assert rounded.tzinfo == TZ


def test_format_hhmm() -> None:
    assert format_hhmm(0) == "00:00"
    assert format_hhmm(5 * 3600 + 45 * 60) == "05:45"
    assert format_hhmm(-10) == "00:00"
    # Minutes are floored and hours are uncapped (spans > 24h still render).
    assert format_hhmm(26 * 3600 + 30 * 60 + 59) == "26:30"


# --- Timesheet: CSV formula-injection hardening ---------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("=1+1", "'=1+1"),
        ('=HYPERLINK("http://evil","x")', '\'=HYPERLINK("http://evil","x")'),
        ("+2", "'+2"),
        ("-3", "'-3"),
        ("@cmd", "'@cmd"),
        ("\tfoo", "'\tfoo"),
        ("\rbar", "'\rbar"),
        ("Normal title", "Normal title"),
        ("", ""),
        ("1+1", "1+1"),  # only a *leading* trigger is sanitized
    ],
)
def test_sanitize_csv_cell(raw: str, expected: str) -> None:
    from doxtr_doto.work_report import _sanitize_csv_cell

    assert _sanitize_csv_cell(raw) == expected


def test_timesheet_sanitizes_free_text_columns() -> None:
    # A task titled "=1+1" and with a formula-trigger task_id must be prefixed
    # with an apostrophe in the title/task_id cells so a spreadsheet treats
    # them as literal text, not formulas.
    tasks = [("repo", "=T1", "=1+1", [_wl(_ts(11, 0), _ts(12, 0))])]
    rows = timesheet_rows([], tasks, DAY, NOW)
    matrix = timesheet_matrix(rows, 0, DAY, ["task_id", "title"])
    # matrix[0] is the header; matrix[1] is the one task row.
    assert matrix[1] == ["'=T1", "'=1+1"]


def test_timesheet_leaves_normal_free_text_untouched() -> None:
    tasks = [("repo", "T1", "Alpha", [_wl(_ts(11, 0), _ts(12, 0))])]
    rows = timesheet_rows([], tasks, DAY, NOW)
    matrix = timesheet_matrix(rows, 0, DAY, ["task_id", "title"])
    assert matrix[1] == ["T1", "Alpha"]


# --- Timesheet: column renderer registry ----------------------------------


def test_every_timesheet_column_has_a_renderer() -> None:
    # Guards against a column being declared "valid" without a renderer behind
    # it (the silent-blank failure mode). Every column in TIMESHEET_COLUMNS
    # must appear in both renderer registries.
    from doxtr_doto.work_report import (
        TIMESHEET_COLUMNS,
        TIMESHEET_ROW_RENDERERS,
        TIMESHEET_TOTAL_RENDERERS,
    )

    assert set(TIMESHEET_COLUMNS) == set(TIMESHEET_ROW_RENDERERS)
    assert set(TIMESHEET_COLUMNS) == set(TIMESHEET_TOTAL_RENDERERS)


def test_default_timesheet_columns_derived_from_renderer_keys() -> None:
    from doxtr_doto.work_report import DEFAULT_TIMESHEET_COLUMNS, TIMESHEET_ROW_RENDERERS

    assert DEFAULT_TIMESHEET_COLUMNS == list(TIMESHEET_ROW_RENDERERS)


# --- Timesheet: row generation + total + columns --------------------------


def test_timesheet_rows_work_and_task() -> None:
    # Work clock: 10:07-15:43 (rounds to 10:00-15:45).
    work = [_wl(_ts(10, 7), _ts(15, 43))]
    # Task: 11:08-12:52 (rounds to 11:15-12:45).
    tasks = [("repo", "T1", "Alpha", [_wl(_ts(11, 8), _ts(12, 52))])]
    rows = timesheet_rows(work, tasks, DAY, NOW)
    assert len(rows) == 2
    # Work row is first (earlier start, and work sorts before task on ties).
    assert rows[0].kind == "work"
    assert rows[0].start.strftime("%H:%M") == "10:00"
    assert rows[0].stop.strftime("%H:%M") == "15:45"
    assert rows[0].task_id == "" and rows[0].title == ""
    assert rows[1].kind == "task"
    assert rows[1].task_id == "T1"
    assert rows[1].title == "Alpha"
    assert rows[1].start.strftime("%H:%M") == "11:15"
    assert rows[1].stop.strftime("%H:%M") == "12:45"


def test_timesheet_rows_work_before_task_on_tie() -> None:
    # Identical rounded start -> work sorts first.
    work = [_wl(_ts(10, 0), _ts(11, 0))]
    tasks = [("repo", "T1", "Alpha", [_wl(_ts(10, 2), _ts(11, 0))])]
    rows = timesheet_rows(work, tasks, DAY, NOW)
    assert [r.kind for r in rows] == ["work", "task"]
    assert rows[0].start == rows[1].start


def test_timesheet_rows_empty_day() -> None:
    assert timesheet_rows([], [], DAY, NOW) == []


def test_timesheet_rounded_duration() -> None:
    row = TimesheetRow(
        day=DAY,
        start=datetime(2026, 6, 1, 10, 0, tzinfo=TZ),
        stop=datetime(2026, 6, 1, 15, 45, tzinfo=TZ),
        kind="work",
    )
    assert row.rounded_duration_seconds == 5 * 3600 + 45 * 60


def test_work_span_seconds_uses_bracket_not_sum() -> None:
    # Two work intervals with a gap: span is earliest-start -> latest-stop,
    # INCLUDING the gap, not the sum of the two intervals.
    work = [
        _wl(_ts(10, 0), _ts(15, 45)),
        _wl(_ts(16, 0), _ts(18, 15)),
    ]
    span = work_span_seconds(work, DAY, NOW)
    # 10:00 -> 18:15 == 8h15m.
    assert span == 8 * 3600 + 15 * 60
    assert format_hhmm(span) == "08:15"


def test_work_span_seconds_empty() -> None:
    assert work_span_seconds([], DAY, NOW) == 0


def test_timesheet_matrix_header_rows_total() -> None:
    work = [
        _wl(_ts(10, 0), _ts(15, 45)),
        _wl(_ts(16, 0), _ts(18, 15)),
    ]
    rows = timesheet_rows(work, [], DAY, NOW)
    span = work_span_seconds(work, DAY, NOW)
    matrix = timesheet_matrix(rows, span, DAY, ["date", "start_time", "end_time"])
    assert matrix[0] == ["date", "start_time", "end_time"]
    assert matrix[1] == ["2026-06-01", "10:00", "15:45"]
    assert matrix[2] == ["2026-06-01", "16:00", "18:15"]
    # Total row: exact unrounded span lands in end_time for this subset.
    assert matrix[-1] == ["2026-06-01", "", "08:15"]


def test_timesheet_matrix_default_columns_and_total_in_duration() -> None:
    work = [_wl(_ts(10, 0), _ts(15, 45))]
    rows = timesheet_rows(work, [], DAY, NOW)
    span = work_span_seconds(work, DAY, NOW)
    matrix = timesheet_matrix(rows, span, DAY)  # default columns
    assert matrix[0] == [
        "date",
        "start_time",
        "end_time",
        "task_id",
        "title",
        "kind",
        "duration",
    ]
    # Data row has kind "work" and a rounded duration.
    assert matrix[1][5] == "work"
    assert matrix[1][6] == "05:45"
    # Total row: kind == total, duration carries the exact span.
    total = matrix[-1]
    assert total[5] == "total"
    assert total[6] == "05:45"
    assert total[4] == "Total work-clock span"


def test_timesheet_matrix_empty_day_header_only() -> None:
    matrix = timesheet_matrix([], 0, DAY, ["date", "start_time", "end_time"])
    assert matrix == [["date", "start_time", "end_time"]]


def test_timesheet_csv_matches_target_example() -> None:
    # The documented minimum-column example.
    day = date(2026, 10, 1)
    now = datetime(2026, 10, 1, 20, 0, tzinfo=TZ)
    work = [
        {
            "started_at": datetime(2026, 10, 1, 10, 0, tzinfo=TZ).isoformat(),
            "stopped_at": datetime(2026, 10, 1, 15, 45, tzinfo=TZ).isoformat(),
        },
        {
            "started_at": datetime(2026, 10, 1, 16, 0, tzinfo=TZ).isoformat(),
            "stopped_at": datetime(2026, 10, 1, 18, 15, tzinfo=TZ).isoformat(),
        },
    ]
    rows = timesheet_rows(work, [], day, now)
    span = work_span_seconds(work, day, now)
    csv_text = timesheet_csv(rows, span, day, ["date", "start_time", "end_time"])
    lines = csv_text.splitlines()
    assert lines[0] == "date,start_time,end_time"
    assert lines[1] == "2026-10-01,10:00,15:45"
    assert lines[2] == "2026-10-01,16:00,18:15"
    # Final total row (end_time carries the unrounded span for this subset).
    assert lines[-1] == "2026-10-01,,08:15"


def test_timesheet_csv_empty_day_header_only() -> None:
    csv_text = timesheet_csv([], 0, DAY, ["date", "start_time", "end_time"])
    assert csv_text.splitlines() == ["date,start_time,end_time"]
