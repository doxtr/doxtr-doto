"""Tests for the pure session time-tracking functions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from doxtr_doto.time_tracking import (
    close_session,
    detect_overnight,
    discard_session,
    elapsed_seconds,
    find_long_sessions,
    has_open_session,
    long_session_threshold_seconds,
    now_iso,
    open_session,
    open_session_stop_bound,
    parse_timestamp,
    recover_stale_open_session,
    split_at_midnight,
    start_session,
)

TZ = timezone.utc


def _dt(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=TZ)


class TestOpenSession:
    """Tests for open_session / has_open_session."""

    def test_no_open_session(self):
        logs = [
            {
                "started_at": _dt(2024, 1, 1, 9).isoformat(),
                "stopped_at": _dt(2024, 1, 1, 10).isoformat(),
            }
        ]
        assert open_session(logs) is None
        assert has_open_session(logs) is False

    def test_detects_open_session(self):
        logs = [{"started_at": _dt(2024, 1, 1, 9).isoformat(), "stopped_at": None}]
        result = open_session(logs)
        assert result is not None
        assert result["stopped_at"] is None
        assert has_open_session(logs) is True

    def test_empty_list(self):
        assert open_session([]) is None
        assert has_open_session([]) is False

    def test_returns_first_open(self):
        logs = [
            {"started_at": _dt(2024, 1, 1, 9).isoformat(), "stopped_at": None},
            {"started_at": _dt(2024, 1, 1, 11).isoformat(), "stopped_at": None},
        ]
        assert open_session(logs)["started_at"] == _dt(2024, 1, 1, 9).isoformat()


class TestElapsedSeconds:
    """Tests for elapsed_seconds."""

    def test_empty(self):
        assert elapsed_seconds([], now=_dt(2024, 1, 1, 12)) == 0

    def test_single_closed_interval(self):
        logs = [
            {
                "started_at": _dt(2024, 1, 1, 9).isoformat(),
                "stopped_at": _dt(2024, 1, 1, 10).isoformat(),
            }
        ]
        assert elapsed_seconds(logs, now=_dt(2024, 1, 1, 12)) == 3600

    def test_multiple_closed_intervals(self):
        logs = [
            {
                "started_at": _dt(2024, 1, 1, 9).isoformat(),
                "stopped_at": _dt(2024, 1, 1, 10).isoformat(),
            },
            {
                "started_at": _dt(2024, 1, 1, 11).isoformat(),
                "stopped_at": _dt(2024, 1, 1, 11, 30).isoformat(),
            },
        ]
        assert elapsed_seconds(logs, now=_dt(2024, 1, 1, 12)) == 3600 + 1800

    def test_open_interval_counts_against_now(self):
        logs = [{"started_at": _dt(2024, 1, 1, 9).isoformat(), "stopped_at": None}]
        assert elapsed_seconds(logs, now=_dt(2024, 1, 1, 9, 30)) == 1800

    def test_mixed_open_and_closed(self):
        logs = [
            {
                "started_at": _dt(2024, 1, 1, 9).isoformat(),
                "stopped_at": _dt(2024, 1, 1, 10).isoformat(),
            },
            {"started_at": _dt(2024, 1, 1, 11).isoformat(), "stopped_at": None},
        ]
        assert elapsed_seconds(logs, now=_dt(2024, 1, 1, 11, 15)) == 3600 + 900

    def test_negative_interval_clamped(self):
        logs = [
            {
                "started_at": _dt(2024, 1, 1, 10).isoformat(),
                "stopped_at": _dt(2024, 1, 1, 9).isoformat(),
            }
        ]
        assert elapsed_seconds(logs, now=_dt(2024, 1, 1, 12)) == 0

    def test_skips_missing_started_at(self):
        logs = [{"started_at": "", "stopped_at": None}]
        assert elapsed_seconds(logs, now=_dt(2024, 1, 1, 12)) == 0

    def test_default_now_uses_current_time(self):
        start = datetime.now(TZ) - timedelta(seconds=10)
        logs = [{"started_at": start.isoformat(), "stopped_at": None}]
        # Should be at least 10 seconds, allow slack
        assert elapsed_seconds(logs) >= 9


class TestDetectOvernight:
    """Tests for detect_overnight."""

    def test_no_open_sessions(self):
        logs = [
            {
                "started_at": _dt(2024, 1, 1, 9).isoformat(),
                "stopped_at": _dt(2024, 1, 1, 10).isoformat(),
            }
        ]
        assert detect_overnight(logs, now=_dt(2024, 1, 2, 9)) == []

    def test_open_session_from_prior_day(self):
        logs = [{"started_at": _dt(2024, 1, 1, 23).isoformat(), "stopped_at": None}]
        stale = detect_overnight(logs, now=_dt(2024, 1, 2, 8))
        assert len(stale) == 1
        assert stale[0]["started_at"] == _dt(2024, 1, 1, 23).isoformat()

    def test_open_session_same_day_not_stale(self):
        logs = [{"started_at": _dt(2024, 1, 2, 8).isoformat(), "stopped_at": None}]
        assert detect_overnight(logs, now=_dt(2024, 1, 2, 9)) == []

    def test_ignores_missing_started_at(self):
        logs = [{"started_at": "", "stopped_at": None}]
        assert detect_overnight(logs, now=_dt(2024, 1, 2, 9)) == []


class TestCloseSession:
    """Tests for close_session."""

    def test_closes_open_session(self):
        logs = [{"started_at": _dt(2024, 1, 1, 9).isoformat(), "stopped_at": None}]
        result = close_session(logs, now=_dt(2024, 1, 1, 10))
        assert result[0]["stopped_at"] == _dt(2024, 1, 1, 10).isoformat()
        # Original not mutated
        assert logs[0]["stopped_at"] is None

    def test_no_open_session_returns_copy(self):
        logs = [
            {
                "started_at": _dt(2024, 1, 1, 9).isoformat(),
                "stopped_at": _dt(2024, 1, 1, 10).isoformat(),
            }
        ]
        result = close_session(logs, now=_dt(2024, 1, 1, 11))
        assert result == logs
        assert result is not logs

    def test_only_first_open_closed(self):
        logs = [
            {"started_at": _dt(2024, 1, 1, 9).isoformat(), "stopped_at": None},
            {"started_at": _dt(2024, 1, 1, 11).isoformat(), "stopped_at": None},
        ]
        result = close_session(logs, now=_dt(2024, 1, 1, 12))
        assert result[0]["stopped_at"] == _dt(2024, 1, 1, 12).isoformat()
        assert result[1]["stopped_at"] is None


class TestStartSession:
    """Tests for start_session."""

    def test_appends_open_session(self):
        logs: list = []
        result = start_session(logs, now=_dt(2024, 1, 1, 9))
        assert len(result) == 1
        assert result[0]["started_at"] == _dt(2024, 1, 1, 9).isoformat()
        assert result[0]["stopped_at"] is None
        assert logs == []  # not mutated

    def test_preserves_existing(self):
        logs = [
            {
                "started_at": _dt(2024, 1, 1, 9).isoformat(),
                "stopped_at": _dt(2024, 1, 1, 10).isoformat(),
            }
        ]
        result = start_session(logs, now=_dt(2024, 1, 1, 11))
        assert len(result) == 2
        assert result[1]["stopped_at"] is None


class TestDiscardSession:
    """Tests for discard_session."""

    def test_removes_open_session(self):
        logs = [
            {
                "started_at": _dt(2024, 1, 1, 9).isoformat(),
                "stopped_at": _dt(2024, 1, 1, 10).isoformat(),
            },
            {"started_at": _dt(2024, 1, 1, 11).isoformat(), "stopped_at": None},
        ]
        result = discard_session(logs)
        assert len(result) == 1
        assert result[0]["stopped_at"] == _dt(2024, 1, 1, 10).isoformat()
        assert len(logs) == 2  # not mutated

    def test_no_open_session_returns_copy(self):
        logs = [
            {
                "started_at": _dt(2024, 1, 1, 9).isoformat(),
                "stopped_at": _dt(2024, 1, 1, 10).isoformat(),
            }
        ]
        result = discard_session(logs)
        assert result == logs
        assert result is not logs

    def test_only_first_open_dropped(self):
        logs = [
            {"started_at": _dt(2024, 1, 1, 9).isoformat(), "stopped_at": None},
            {"started_at": _dt(2024, 1, 1, 11).isoformat(), "stopped_at": None},
        ]
        result = discard_session(logs)
        assert len(result) == 1
        assert result[0]["started_at"] == _dt(2024, 1, 1, 11).isoformat()


class TestFindLongSessions:
    """Tests for intelligent overly-long / forgotten session detection."""

    def test_normal_day_sessions_not_flagged(self):
        logs = [
            {
                "started_at": _dt(2026, 11, 23, 9, 0).isoformat(),
                "stopped_at": _dt(2026, 11, 23, 12, 0).isoformat(),
            },
            {
                "started_at": _dt(2026, 11, 23, 13, 0).isoformat(),
                "stopped_at": _dt(2026, 11, 23, 18, 0).isoformat(),
            },
        ]
        assert find_long_sessions(logs, now=_dt(2026, 11, 23, 19, 0), day_length_minutes=480) == []

    def test_flags_open_stale_and_multiday_and_over_threshold(self):
        logs = [
            # Closed > 12h (16h)
            {
                "started_at": _dt(2026, 11, 13, 7, 0).isoformat(),
                "stopped_at": _dt(2026, 11, 13, 23, 0).isoformat(),
            },
            # Closed spanning multiple days (49h+)
            {
                "started_at": _dt(2026, 10, 16, 21, 30).isoformat(),
                "stopped_at": _dt(2026, 10, 18, 23, 15).isoformat(),
            },
            # Still open from 9 days ago
            {
                "started_at": _dt(2026, 11, 14, 12, 30).isoformat(),
                "stopped_at": None,
            },
        ]
        findings = find_long_sessions(
            logs,
            now=_dt(2026, 11, 23, 21, 0),
            day_length_minutes=480,
        )
        assert len(findings) == 3
        # Open/stale finding comes first.
        assert findings[0].index == 2
        assert findings[0].is_open is True
        assert any(r.startswith("open 9d") for r in findings[0].reasons)
        # Longest closed span next.
        assert findings[1].index == 1
        assert "spans days" in findings[1].reasons
        # Single-day 16h session (> 12h) last.
        assert findings[2].index == 0
        assert ">12h" in findings[2].reasons

    def test_threshold_scales_with_day_length(self):
        assert long_session_threshold_seconds(480) == 12 * 3600
        assert long_session_threshold_seconds(600) == 15 * 3600


class TestStaleOpenSession:
    """Tests for safe handling of forgotten prior-day work clocks."""

    def test_open_session_is_bounded_to_start_day(self):
        log = {"started_at": _dt(2024, 1, 1, 23).isoformat(), "stopped_at": None}
        assert open_session_stop_bound(log, _dt(2024, 1, 3, 8)) == _dt(2024, 1, 2, 0)

    def test_recover_closes_stale_interval_without_filling_intervening_days(self):
        logs = [{"started_at": _dt(2024, 1, 1, 9).isoformat(), "stopped_at": None}]
        result = recover_stale_open_session(logs, now=_dt(2024, 1, 3, 8))
        assert result[0]["stopped_at"] == _dt(2024, 1, 2, 0).isoformat()
        assert logs[0]["stopped_at"] is None

    def test_recover_keeps_same_day_open_session_running(self):
        logs = [{"started_at": _dt(2024, 1, 3, 8).isoformat(), "stopped_at": None}]
        assert recover_stale_open_session(logs, now=_dt(2024, 1, 3, 10)) == logs


class TestSplitAtMidnight:
    """Tests for split_at_midnight."""

    def test_splits_overnight_session(self):
        logs = [{"started_at": _dt(2024, 1, 1, 23).isoformat(), "stopped_at": None}]
        result = split_at_midnight(logs, now=_dt(2024, 1, 2, 8))
        assert len(result) == 2
        midnight = _dt(2024, 1, 2, 0).isoformat()
        assert result[0]["started_at"] == _dt(2024, 1, 1, 23).isoformat()
        assert result[0]["stopped_at"] == midnight
        assert result[1]["started_at"] == midnight
        assert result[1]["stopped_at"] is None
        assert len(logs) == 1  # not mutated

    def test_same_day_open_unchanged(self):
        logs = [{"started_at": _dt(2024, 1, 2, 8).isoformat(), "stopped_at": None}]
        result = split_at_midnight(logs, now=_dt(2024, 1, 2, 10))
        assert result == logs

    def test_no_open_session_unchanged(self):
        logs = [
            {
                "started_at": _dt(2024, 1, 1, 9).isoformat(),
                "stopped_at": _dt(2024, 1, 1, 10).isoformat(),
            }
        ]
        result = split_at_midnight(logs, now=_dt(2024, 1, 2, 10))
        assert result == logs
        assert result is not logs

    def test_elapsed_preserved_after_split(self):
        logs = [{"started_at": _dt(2024, 1, 1, 23).isoformat(), "stopped_at": None}]
        before = elapsed_seconds(logs, now=_dt(2024, 1, 2, 8))
        split = split_at_midnight(logs, now=_dt(2024, 1, 2, 8))
        after = elapsed_seconds(split, now=_dt(2024, 1, 2, 8))
        assert before == after


class TestTimestampHelpers:
    """Tests for now_iso and parse_timestamp."""

    def test_now_iso_with_override(self):
        assert now_iso(_dt(2024, 1, 1, 9)) == _dt(2024, 1, 1, 9).isoformat()

    def test_now_iso_default_is_aware(self):
        parsed = parse_timestamp(now_iso())
        assert parsed.tzinfo is not None

    def test_parse_naive_becomes_aware(self):
        naive = datetime(2024, 1, 1, 9).isoformat()  # noqa: DTZ001 - intentionally naive
        parsed = parse_timestamp(naive)
        assert parsed.tzinfo is not None

    def test_parse_aware_roundtrip(self):
        value = _dt(2024, 1, 1, 9).isoformat()
        assert parse_timestamp(value).isoformat() == value
