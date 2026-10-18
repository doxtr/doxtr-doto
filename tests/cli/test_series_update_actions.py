"""Tests for the shared series-update / delete actions and the edit-series form.

Covers the terminal-free validation in
:mod:`doxtr_doto.cli.tui.edit_series_fields` and the reusable actions
:func:`doxtr_doto.cli.tui.actions.update_series` / ``delete_task`` /
``delete_series`` (shared by the CLI ``doto series update`` command, the
``doto delete`` path and the TUI), mirroring ``tests/cli/test_add_series_actions.py``.
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
from doxtr_doto.cli.tui.edit_series_fields import (
    EditSeriesFormValues,
    validate_edit_series_form,
)


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


def _make_series(ctx, pattern_str="every monday", start=date(2026, 1, 5), end=date(2026, 2, 2)):
    """Create a weekly series via the reusable builder and return its result."""
    pattern = parse_recurrence(pattern_str)
    return actions.add_series(
        ctx,
        title_template="Weekly {date}",
        pattern=pattern,
        start_date=start,
        end_date=end,
        task_defaults={
            "assignee": None,
            "priority": "medium",
            "status": "open",
            "tags": [],
            "depends_on": [],
            "body": None,
        },
    )


class TestUpdateSeriesForwardOnly:
    """Tests for the forward-only re-stamp semantics of update_series."""

    def test_anchor_in_middle_earlier_untouched_later_changed(self, series_ctx):
        """Only occurrences on/after the anchor are re-stamped."""
        series = _make_series(series_ctx)
        series_ctx.store.load()
        tasks = series_ctx.store.get_tasks_in_series(series.series_id)
        assert len(tasks) >= 4
        # Pick the 3rd occurrence's date as the anchor.
        anchor = date.fromisoformat(tasks[2]["due"][:10])
        new_pattern = parse_recurrence("every monday at 16:00 for 2h")

        result = actions.update_series(
            series_ctx,
            series.series_id,
            pattern=new_pattern,
            anchor_date=anchor,
        )

        # Earlier occurrences unchanged (date-only due, no estimate).
        series_ctx.store.load()
        for task in series_ctx.store.get_tasks_in_series(series.series_id):
            due_date = date.fromisoformat(task["due"][:10])
            if due_date < anchor:
                assert "T" not in task["due"]
                assert task.get("estimate") is None
            else:
                assert task["due"].endswith("T16:00")
                assert task["estimate"] == 120
        assert len(result.updated_task_ids) == len(tasks) - 2
        assert result.skipped_before_anchor == 2
        assert result.skipped_done == []

    def test_anchor_first_restamps_all(self, series_ctx):
        """Anchor on the first occurrence re-stamps every occurrence."""
        series = _make_series(series_ctx)
        series_ctx.store.load()
        tasks = series_ctx.store.get_tasks_in_series(series.series_id)
        anchor = date.fromisoformat(tasks[0]["due"][:10])
        result = actions.update_series(
            series_ctx,
            series.series_id,
            pattern=parse_recurrence("every monday for 90m"),
            anchor_date=anchor,
        )
        assert len(result.updated_task_ids) == len(tasks)
        assert result.skipped_before_anchor == 0

    def test_anchor_last_restamps_only_last(self, series_ctx):
        """Anchor on the last occurrence re-stamps only that one."""
        series = _make_series(series_ctx)
        series_ctx.store.load()
        tasks = series_ctx.store.get_tasks_in_series(series.series_id)
        anchor = date.fromisoformat(tasks[-1]["due"][:10])
        result = actions.update_series(
            series_ctx,
            series.series_id,
            pattern=parse_recurrence("every monday for 30m"),
            anchor_date=anchor,
        )
        assert len(result.updated_task_ids) == 1
        assert result.skipped_before_anchor == len(tasks) - 1

    def test_done_and_archived_are_skipped(self, series_ctx):
        """Done / archived forward occurrences are skipped and recorded."""
        series = _make_series(series_ctx)
        series_ctx.store.load()
        tasks = series_ctx.store.get_tasks_in_series(series.series_id)
        anchor = date.fromisoformat(tasks[0]["due"][:10])
        # Mark the 2nd done and the 3rd archived.
        series_ctx.store.update_task(tasks[1]["id"], {"status": "done"})
        series_ctx.store.update_task(tasks[2]["id"], {"archived": True})
        series_ctx.store.save()

        result = actions.update_series(
            series_ctx,
            series.series_id,
            pattern=parse_recurrence("every monday for 45m"),
            anchor_date=anchor,
        )
        assert tasks[1]["id"] in result.skipped_done
        assert tasks[2]["id"] in result.skipped_done
        assert tasks[1]["id"] not in result.updated_task_ids
        assert tasks[2]["id"] not in result.updated_task_ids

    def test_metadata_only_restamps_nothing(self, series_ctx):
        """anchor_date=None updates the stored pattern but no tasks."""
        series = _make_series(series_ctx)
        series_ctx.store.load()
        before = [t["due"] for t in series_ctx.store.get_tasks_in_series(series.series_id)]
        result = actions.update_series(
            series_ctx,
            series.series_id,
            pattern=parse_recurrence("every monday at 16:00 for 2h"),
            anchor_date=None,
        )
        assert result.updated_task_ids == []
        series_ctx.store.load()
        after = [t["due"] for t in series_ctx.store.get_tasks_in_series(series.series_id)]
        assert after == before
        # The stored pattern metadata was updated.
        stored = series_ctx.store.get_series(series.series_id)
        assert stored["pattern"]["start_time"] == "16:00"
        assert stored["pattern"]["duration_minutes"] == 120

    def test_dry_run_writes_nothing(self, series_ctx):
        """dry_run computes the result without writing/saving."""
        series = _make_series(series_ctx)
        series_ctx.store.load()
        tasks = series_ctx.store.get_tasks_in_series(series.series_id)
        anchor = date.fromisoformat(tasks[0]["due"][:10])
        before = [t["due"] for t in tasks]

        result = actions.update_series(
            series_ctx,
            series.series_id,
            pattern=parse_recurrence("every monday at 16:00 for 2h"),
            anchor_date=anchor,
            dry_run=True,
        )
        assert len(result.updated_task_ids) == len(tasks)
        # Nothing persisted.
        series_ctx.store.load()
        after = [t["due"] for t in series_ctx.store.get_tasks_in_series(series.series_id)]
        assert after == before
        stored = series_ctx.store.get_series(series.series_id)
        assert stored["pattern"]["start_time"] is None

    def test_forward_slice_matches_from_scratch_series(self, series_ctx):
        """Re-stamped forward slice equals a from-scratch series (same pattern)."""
        series = _make_series(series_ctx)
        series_ctx.store.load()
        tasks = series_ctx.store.get_tasks_in_series(series.series_id)
        anchor = date.fromisoformat(tasks[0]["due"][:10])
        new_pattern = parse_recurrence("every monday at 16:00 for 2h")
        actions.update_series(series_ctx, series.series_id, pattern=new_pattern, anchor_date=anchor)
        series_ctx.store.load()
        restamped = series_ctx.store.get_tasks_in_series(series.series_id)

        # Build a fresh series with the same pattern over the same window.
        fresh = actions.add_series(
            series_ctx,
            title_template="Scratch {date}",
            pattern=new_pattern,
            start_date=date.fromisoformat(tasks[0]["due"][:10]),
            end_date=date.fromisoformat(tasks[-1]["due"][:10]),
            task_defaults={"status": "open", "tags": [], "depends_on": []},
        )
        series_ctx.store.load()
        scratch = series_ctx.store.get_tasks_in_series(fresh.series_id)

        assert [t["due"] for t in restamped] == [t["due"] for t in scratch]
        assert [t["estimate"] for t in restamped] == [t["estimate"] for t in scratch]

    def test_title_restamped_only_when_changed(self, series_ctx):
        """The title is re-rendered only when the template changed."""
        series = _make_series(series_ctx)
        series_ctx.store.load()
        tasks = series_ctx.store.get_tasks_in_series(series.series_id)
        anchor = date.fromisoformat(tasks[0]["due"][:10])
        actions.update_series(
            series_ctx,
            series.series_id,
            title_template="Renamed {date}",
            anchor_date=anchor,
        )
        series_ctx.store.load()
        for task in series_ctx.store.get_tasks_in_series(series.series_id):
            assert task["title"].startswith("Renamed ")

    def test_changing_calendar_shape_keeps_existing_dates(self, series_ctx):
        """A biweekly pattern over a weekly series keeps the existing due dates.

        Changing the calendar *shape* only re-stamps time/duration/title onto
        the existing forward occurrence dates; it never moves or adds dates.
        """
        series = _make_series(series_ctx)
        series_ctx.store.load()
        tasks = series_ctx.store.get_tasks_in_series(series.series_id)
        anchor = date.fromisoformat(tasks[0]["due"][:10])
        before_dates = [t["due"][:10] for t in tasks]

        new_pattern = parse_recurrence("every 2 weeks on monday at 16:00 for 2h")
        result = actions.update_series(
            series_ctx, series.series_id, pattern=new_pattern, anchor_date=anchor
        )

        series_ctx.store.load()
        restamped = series_ctx.store.get_tasks_in_series(series.series_id)
        # Dates are unchanged (no occurrences moved or added)...
        assert [t["due"][:10] for t in restamped] == before_dates
        # ...while time/duration were re-stamped onto every forward occurrence.
        for task in restamped:
            assert task["due"].endswith("T16:00")
            assert task["estimate"] == 120
        assert len(result.updated_task_ids) == len(tasks)
        # Stored metadata reflects the new biweekly shape.
        stored = series_ctx.store.get_series(series.series_id)
        assert stored["pattern"]["interval"] == 2

    def test_malformed_due_occurrence_skipped_silently(self, series_ctx):
        """An occurrence with a missing/garbage due is skipped without counting."""
        series = _make_series(series_ctx)
        series_ctx.store.load()
        tasks = series_ctx.store.get_tasks_in_series(series.series_id)
        anchor = date.fromisoformat(tasks[0]["due"][:10])
        # Corrupt one occurrence's due so occurrence_date() returns None.
        series_ctx.store.update_task(tasks[1]["id"], {"due": "not-a-date"})
        series_ctx.store.save()

        result = actions.update_series(
            series_ctx,
            series.series_id,
            pattern=parse_recurrence("every monday for 30m"),
            anchor_date=anchor,
        )

        # The malformed occurrence is neither re-stamped nor counted as skipped.
        assert tasks[1]["id"] not in result.updated_task_ids
        assert result.skipped_before_anchor == 0
        assert result.skipped_done == []
        assert len(result.updated_task_ids) == len(tasks) - 1


class TestDeleteTaskAction:
    """Tests for actions.delete_task (prunes the owning series link)."""

    def test_deletes_task_and_prunes_series_link(self, series_ctx):
        """Deleting a series task removes it from the series' task_ids."""
        series = _make_series(series_ctx)
        series_ctx.store.load()
        tasks = series_ctx.store.get_tasks_in_series(series.series_id)
        victim = tasks[1]["id"]

        assert actions.delete_task(series_ctx, victim) is True

        series_ctx.store.load()
        stored = series_ctx.store.get_series(series.series_id)
        assert victim not in stored["task_ids"]
        # The occurrence count dropped by one.
        assert len(series_ctx.store.get_tasks_in_series(series.series_id)) == len(tasks) - 1
        assert series_ctx.store.get_task(victim) is None

    def test_delete_missing_task_returns_false(self, series_ctx):
        assert actions.delete_task(series_ctx, "NOPE-999") is False


class TestDeleteSeriesAction:
    """Tests for actions.delete_series (with and without delete_tasks)."""

    def test_delete_series_and_tasks(self, series_ctx):
        series = _make_series(series_ctx)
        series_ctx.store.load()
        tasks = series_ctx.store.get_tasks_in_series(series.series_id)

        success, deleted = actions.delete_series(series_ctx, series.series_id, delete_tasks=True)
        assert success is True
        assert set(deleted) == {t["id"] for t in tasks}

        series_ctx.store.load()
        assert series_ctx.store.get_series(series.series_id) is None
        for task in tasks:
            assert series_ctx.store.get_task(task["id"]) is None

    def test_delete_series_keep_tasks(self, series_ctx):
        series = _make_series(series_ctx)
        series_ctx.store.load()
        tasks = series_ctx.store.get_tasks_in_series(series.series_id)

        success, deleted = actions.delete_series(series_ctx, series.series_id, delete_tasks=False)
        assert success is True
        assert deleted == []

        series_ctx.store.load()
        assert series_ctx.store.get_series(series.series_id) is None
        # Tasks survive.
        for task in tasks:
            assert series_ctx.store.get_task(task["id"]) is not None

    def test_delete_missing_series_returns_false(self, series_ctx):
        success, deleted = actions.delete_series(series_ctx, "NOPE", delete_tasks=True)
        assert success is False
        assert deleted == []


class TestValidateEditSeriesForm:
    """Tests for the terminal-free validate_edit_series_form."""

    def test_set_time_and_duration(self):
        result, errors = validate_edit_series_form(
            EditSeriesFormValues(
                title="Sync",
                pattern="every monday",
                start_time="16:00",
                duration="2h",
            )
        )
        assert errors == []
        assert result is not None
        assert result.title == "Sync"
        assert result.pattern_str == "every monday at 16:00 for 2h"
        assert result.start_time == time(16, 0)
        assert result.duration_minutes == 120

    def test_blank_time_and_duration_clear(self):
        """Blank start_time/duration => CLEAR (result fields None)."""
        result, errors = validate_edit_series_form(
            EditSeriesFormValues(title="Sync", pattern="every monday")
        )
        assert errors == []
        assert result is not None
        assert result.start_time is None
        assert result.duration_minutes is None
        # The pattern was given, so pattern_str is the base (no suffix).
        assert result.pattern_str == "every monday"

    def test_blank_pattern_and_title_keep(self):
        """Blank pattern/title => KEEP (result fields None)."""
        result, errors = validate_edit_series_form(
            EditSeriesFormValues(title="", pattern="", start_time="09:00")
        )
        assert errors == []
        assert result is not None
        assert result.title is None
        assert result.pattern_str is None
        # A time was still parsed (clears nothing since it is set).
        assert result.start_time == time(9, 0)

    def test_change_pattern_and_title(self):
        result, errors = validate_edit_series_form(
            EditSeriesFormValues(title="New", pattern="every 2 weeks on friday")
        )
        assert errors == []
        assert result is not None
        assert result.title == "New"
        assert result.pattern_str == "every 2 weeks on friday"

    def test_collects_all_errors(self):
        """Multiple invalid inputs are all reported, not just the first."""
        result, errors = validate_edit_series_form(
            EditSeriesFormValues(
                title="x",
                pattern="not a pattern",
                start_time="not-a-time",
                duration="not-a-duration",
            )
        )
        assert result is None
        assert len(errors) >= 3
