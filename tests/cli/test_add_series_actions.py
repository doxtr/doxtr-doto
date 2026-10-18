"""Tests for the add-series TUI helper and the shared ``actions.add_series``.

Covers the terminal-free validation/compose logic in
:mod:`doxtr_doto.cli.tui.add_series_fields` and the reusable series builder
:func:`doxtr_doto.cli.tui.actions.add_series` (shared by the CLI and the TUI).
"""

from __future__ import annotations

import json
from datetime import date, time

import pytest

from doxtr_doto.cli.config import load_config
from doxtr_doto.cli.global_state import GlobalStateStore
from doxtr_doto.cli.json_store import JsonTaskStore
from doxtr_doto.cli.main import DotoContext
from doxtr_doto.cli.output import get_formatter
from doxtr_doto.cli.recurrence import parse_recurrence
from doxtr_doto.cli.tui import actions
from doxtr_doto.cli.tui.add_series_fields import (
    SeriesFormValues,
    compose_pattern_str,
    validate_series_form,
)


class TestComposePatternStr:
    """Tests for compose_pattern_str."""

    def test_base_only(self):
        """No time/duration leaves the base pattern unchanged."""
        assert compose_pattern_str("every monday", "", "") == "every monday"

    def test_time_only(self):
        """A start time appends ' at <time>'."""
        assert compose_pattern_str("every monday", "16:00", "") == "every monday at 16:00"

    def test_duration_only(self):
        """A duration appends ' for <duration>'."""
        assert compose_pattern_str("every day", "", "2h") == "every day for 2h"

    def test_time_and_duration_order(self):
        """Time is appended before duration."""
        assert (
            compose_pattern_str("every 2 weeks on monday", "16:00", "2h")
            == "every 2 weeks on monday at 16:00 for 2h"
        )

    def test_strips_whitespace(self):
        """Surrounding whitespace on the tokens is stripped."""
        assert compose_pattern_str("  every day  ", " 09:00 ", " 1h ") == (
            "every day at 09:00 for 1h"
        )


class TestValidateSeriesForm:
    """Tests for validate_series_form."""

    def test_valid_full_form(self):
        """A complete, valid form resolves to a SeriesFormResult."""
        result, errors = validate_series_form(
            SeriesFormValues(
                title="Sync",
                pattern="every 2 weeks on monday",
                start_time="16:00",
                duration="2h",
                from_date="2026-11-01",
                until_date="2027-10-10",
            )
        )
        assert errors == []
        assert result is not None
        assert result.title == "Sync"
        assert result.pattern_str == "every 2 weeks on monday at 16:00 for 2h"
        assert result.from_date == date(2026, 11, 1)
        assert result.until_date == date(2027, 10, 10)
        # The composed pattern string is the single carrier of time/duration:
        # parse_recurrence recovers them on the build side (no separate fields).
        parsed = parse_recurrence(result.pattern_str)
        assert parsed.start_time == time(16, 0)
        assert parsed.duration_minutes == 120

    def test_from_defaults_to_today(self):
        """An empty from-date defaults to today."""
        result, errors = validate_series_form(
            SeriesFormValues(
                title="Daily",
                pattern="every day",
                until_date="+6m",
            )
        )
        assert errors == []
        assert result is not None
        assert result.from_date == date.today()

    def test_missing_title(self):
        """A missing title is an error."""
        result, errors = validate_series_form(
            SeriesFormValues(title="  ", pattern="every day", until_date="+6m")
        )
        assert result is None
        assert any("Title" in e for e in errors)

    def test_missing_pattern(self):
        """A missing pattern is an error (and does not double as a parse error)."""
        result, errors = validate_series_form(
            SeriesFormValues(title="X", pattern="", until_date="+6m")
        )
        assert result is None
        assert any("pattern is required" in e.lower() for e in errors)

    def test_missing_until(self):
        """A missing until-date is an error."""
        result, errors = validate_series_form(
            SeriesFormValues(title="X", pattern="every day", until_date="")
        )
        assert result is None
        assert any("Until" in e for e in errors)

    def test_invalid_time(self):
        """A malformed start time is an error."""
        result, errors = validate_series_form(
            SeriesFormValues(title="X", pattern="every day", start_time="99:99", until_date="+6m")
        )
        assert result is None
        assert any("start time" in e.lower() for e in errors)

    def test_invalid_duration(self):
        """A malformed duration is an error."""
        result, errors = validate_series_form(
            SeriesFormValues(title="X", pattern="every day", duration="banana", until_date="+6m")
        )
        assert result is None
        assert any("duration" in e.lower() for e in errors)

    def test_invalid_pattern(self):
        """A pattern that cannot be parsed is an error."""
        result, errors = validate_series_form(
            SeriesFormValues(title="X", pattern="every blurgday", until_date="+6m")
        )
        assert result is None
        assert any("pattern" in e.lower() for e in errors)

    def test_end_before_start(self):
        """An until-date on/before the start date is an error."""
        result, errors = validate_series_form(
            SeriesFormValues(
                title="X",
                pattern="every day",
                from_date="2026-11-10",
                until_date="2026-11-01",
            )
        )
        assert result is None
        assert any("after" in e.lower() for e in errors)

    def test_collects_multiple_errors(self):
        """All field errors are collected, not just the first."""
        result, errors = validate_series_form(SeriesFormValues(title="", pattern="", until_date=""))
        assert result is None
        assert len(errors) >= 3


@pytest.fixture
def series_ctx(tmp_path, monkeypatch):
    """A DotoContext wired to an empty temp store and isolated global state."""
    from pathlib import Path

    monkeypatch.setenv("DOTO_CONFIG", str(tmp_path / "global" / "config.json"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")

    store_path = tmp_path / "repo" / ".doto" / "tasks.json"
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
    config = load_config(json_path=store_path)
    return DotoContext(
        config=config,
        store=JsonTaskStore(config.get_json_path()),
        formatter=get_formatter(config),
        global_store=GlobalStateStore(),
    )


class TestActionsAddSeries:
    """Tests for the reusable actions.add_series builder."""

    def test_builds_time_and_duration_series(self, series_ctx):
        """The builder applies time-bearing dues and estimates from the pattern."""
        pattern = parse_recurrence("every 2 weeks on monday at 16:00 for 2h")
        result = actions.add_series(
            series_ctx,
            title_template="Important Sync Meeting",
            pattern=pattern,
            start_date=date(2026, 11, 1),
            end_date=date(2027, 10, 10),
            task_defaults={
                "assignee": None,
                "priority": "medium",
                "status": "open",
                "tags": [],
                "depends_on": [],
                "body": None,
            },
        )
        assert result.occurrence_count == len(result.task_ids)
        assert result.occurrence_count > 0
        assert result.start_date == "2026-11-01"
        assert result.end_date == "2027-10-10"

        series_ctx.store.load()
        for task_id in result.task_ids:
            task = series_ctx.store.get_task(task_id)
            assert task is not None
            assert task["due"].endswith("T16:00")
            assert task["estimate"] == 120
            assert task["series_id"] == result.series_id

        series = series_ctx.store.get_series(result.series_id)
        assert series is not None
        assert series["pattern"]["start_time"] == "16:00"
        assert series["pattern"]["duration_minutes"] == 120

    def test_plain_series_is_date_only(self, series_ctx):
        """A plain calendar pattern yields date-only dues and no estimate."""
        pattern = parse_recurrence("every day")
        result = actions.add_series(
            series_ctx,
            title_template="Daily",
            pattern=pattern,
            start_date=date(2026, 11, 1),
            end_date=date(2026, 11, 3),
            task_defaults={
                "assignee": None,
                "priority": "medium",
                "status": "open",
                "tags": [],
                "depends_on": [],
                "body": None,
            },
        )
        assert result.occurrence_count == 3
        series_ctx.store.load()
        for task_id in result.task_ids:
            task = series_ctx.store.get_task(task_id)
            assert task is not None
            assert "T" not in task["due"]
            assert task.get("estimate") is None
