"""Tests for task -> CalendarEvent projection (model.py).

These exercise the core mapping logic: event vs todo mode, the workday/break
projection, all-day handling, UID generation, and status mapping. No network,
no provider SDKs.
"""

from __future__ import annotations

from datetime import datetime

import pytest

import doxtr_doto.calsync.model as model_mod
from doxtr_doto.calsync.model import (
    CalendarEvent,
    EventKind,
    is_doto_uid,
    make_uid,
    project,
    project_task_to_event,
    register_projector,
    task_id_from_uid,
)
from doxtr_doto.cli.config import CalendarConfig


def _event_cfg(**kw) -> CalendarConfig:
    base = {
        "provider": "caldav",
        "event_mode": "event",
        "workday_start": "08:00",
        "workday_end": "17:00",
        "break_start": "12:00",
        "break_end": "13:00",
        "event_duration_minutes": 30,
    }
    base.update(kw)
    return CalendarConfig(**base)


class TestUid:
    def test_make_uid_round_trip(self):
        uid = make_uid("DOTO-123")
        assert uid == "doto-DOTO-123@doxtr-doto"
        assert is_doto_uid(uid)
        assert task_id_from_uid(uid) == "DOTO-123"

    def test_foreign_uid_rejected(self):
        assert not is_doto_uid("random-event@google.com")
        assert task_id_from_uid("random-event@google.com") is None

    def test_none_uid(self):
        assert not is_doto_uid(None)


class TestEventProjection:
    def test_timed_due_becomes_timed_event(self):
        cal = _event_cfg()
        task = {"title": "Standup", "due": "2026-08-15T09:00", "status": "open"}
        ev = project_task_to_event("T1", task, cal)
        assert ev.kind is EventKind.EVENT
        assert ev.all_day is False
        assert ev.start == datetime(2026, 8, 15, 9, 0)
        assert ev.end == datetime(2026, 8, 15, 9, 30)
        assert ev.summary == "Standup"

    def test_event_during_break_pushed_to_break_end(self):
        # Uses the space-separated due form on purpose (see the dedicated
        # separator-equivalence test below): DotoDate accepts both forms.
        cal = _event_cfg()
        task = {"title": "x", "due": "2026-08-15 12:30", "status": "open"}
        ev = project_task_to_event("T2", task, cal)
        assert ev.start == datetime(2026, 8, 15, 13, 0)
        assert ev.end == datetime(2026, 8, 15, 13, 30)

    def test_due_separator_space_and_T_are_equivalent(self):
        # tasks.json stores the canonical ISO 'T' form (e.g. "2026-08-15T09:00"),
        # while a user may hand-write the space form. DotoDate accepts both, so
        # the projection must produce an identical event for either separator.
        cal = _event_cfg()
        ev_space = project_task_to_event(
            "T", {"title": "x", "due": "2026-08-15 09:00", "status": "open"}, cal
        )
        ev_t = project_task_to_event(
            "T", {"title": "x", "due": "2026-08-15T09:00", "status": "open"}, cal
        )
        assert ev_space.start == ev_t.start == datetime(2026, 8, 15, 9, 0)
        assert ev_space.end == ev_t.end == datetime(2026, 8, 15, 9, 30)

    def test_event_before_workday_clamped_to_start(self):
        cal = _event_cfg()
        task = {"title": "early", "due": "2026-08-15T06:00", "status": "open"}
        ev = project_task_to_event("T3", task, cal)
        assert ev.start == datetime(2026, 8, 15, 8, 0)

    def test_estimate_sets_event_duration(self):
        # A per-task :estimate: (stored as whole minutes) sizes the event,
        # overriding the global event_duration_minutes default (30).
        cal = _event_cfg()
        task = {
            "title": "deep work",
            "due": "2026-08-15T08:00",
            "status": "open",
            "estimate": 90,
        }
        ev = project_task_to_event("T-est", task, cal)
        assert ev.start == datetime(2026, 8, 15, 8, 0)
        assert ev.end == datetime(2026, 8, 15, 9, 30)

    def test_estimate_as_duration_string(self):
        # The projection parses a human duration string too (not just an int),
        # so a task carrying the raw "4h" form still projects a 4h block.
        cal = _event_cfg()
        task = {
            "title": "big",
            "due": "2026-08-15T13:00",
            "status": "open",
            "estimate": "4h",
        }
        ev = project_task_to_event("T-est2", task, cal)
        assert ev.end - ev.start == datetime(2026, 8, 15, 17, 0) - datetime(2026, 8, 15, 13, 0)

    def test_no_estimate_falls_back_to_config_default(self):
        cal = _event_cfg(event_duration_minutes=45)
        task = {"title": "x", "due": "2026-08-15T09:00", "status": "open"}
        ev = project_task_to_event("T-def", task, cal)
        assert ev.end - ev.start == datetime(2026, 8, 15, 9, 45) - datetime(2026, 8, 15, 9, 0)

    def test_malformed_estimate_falls_back_to_default(self):
        # Malformed stored data must never break a push: fall back to default.
        cal = _event_cfg()
        task = {
            "title": "x",
            "due": "2026-08-15T09:00",
            "status": "open",
            "estimate": "garbage",
        }
        ev = project_task_to_event("T-bad", task, cal)
        assert ev.end - ev.start == datetime(2026, 8, 15, 9, 30) - datetime(2026, 8, 15, 9, 0)

    def test_estimate_makes_event_overlap_break_and_pushes(self):
        # The estimate-driven duration is what makes the interval cross the
        # break window, so the start must be pushed to break_end. A task due
        # 11:30 with a 2h estimate would end 13:30 and overlap 12:00-13:00, so
        # it is nudged to start 13:00 / end 15:00. This exercises the
        # estimate->duration value feeding the break-overlap nudge.
        cal = _event_cfg()  # break 12:00-13:00
        task = {"title": "x", "due": "2026-08-15T11:30", "status": "open", "estimate": 120}
        ev = project_task_to_event("T-estbrk", task, cal)
        assert ev.start == datetime(2026, 8, 15, 13, 0)
        assert ev.end == datetime(2026, 8, 15, 15, 0)

    def test_estimate_short_enough_to_end_at_break_start_not_pushed(self):
        # Counterpart: a 30min estimate due 11:30 ends exactly at 12:00 (break
        # start). The break window is half-open, so ending AT break_start does
        # not overlap and the event is left in place.
        cal = _event_cfg()
        task = {"title": "x", "due": "2026-08-15T11:30", "status": "open", "estimate": 30}
        ev = project_task_to_event("T-estnobrk", task, cal)
        assert ev.start == datetime(2026, 8, 15, 11, 30)
        assert ev.end == datetime(2026, 8, 15, 12, 0)

    def test_float_estimate_from_foreign_store_does_not_break_push(self):
        # A float estimate (e.g. written by a foreign JSON producer) must be
        # tolerated by the forgiving projector, not raise.
        cal = _event_cfg()
        task = {"title": "x", "due": "2026-08-15T09:00", "status": "open", "estimate": 90.0}
        ev = project_task_to_event("T-float", task, cal)
        assert ev.end - ev.start == datetime(2026, 8, 15, 10, 30) - datetime(2026, 8, 15, 9, 0)

    def test_break_boundary_at_break_end_not_pushed(self):
        cal = _event_cfg()
        task = {"title": "ok", "due": "2026-08-15T13:00", "status": "open"}
        ev = project_task_to_event("T4", task, cal)
        assert ev.start == datetime(2026, 8, 15, 13, 0)

    def test_break_start_boundary_is_pushed(self):
        # A start exactly at break_start overlaps the half-open break window.
        cal = _event_cfg()
        task = {"title": "x", "due": "2026-08-15T12:00", "status": "open"}
        ev = project_task_to_event("T4b", task, cal)
        assert ev.start == datetime(2026, 8, 15, 13, 0)

    def test_event_ending_inside_break_is_pushed(self):
        # 11:45 + 30min ends 12:15, which overlaps the 12:00-13:00 break.
        cal = _event_cfg(event_duration_minutes=30)
        task = {"title": "x", "due": "2026-08-15T11:45", "status": "open"}
        ev = project_task_to_event("T4c", task, cal)
        assert ev.start == datetime(2026, 8, 15, 13, 0)
        assert ev.end == datetime(2026, 8, 15, 13, 30)

    def test_event_ending_exactly_at_break_start_not_pushed(self):
        # 11:45 + 15min ends exactly 12:00 == break_start; half-open -> no overlap.
        cal = _event_cfg(event_duration_minutes=15)
        task = {"title": "x", "due": "2026-08-15T11:45", "status": "open"}
        ev = project_task_to_event("T4d", task, cal)
        assert ev.start == datetime(2026, 8, 15, 11, 45)
        assert ev.end == datetime(2026, 8, 15, 12, 0)

    def test_event_after_workday_end_kept(self):
        # A late due is not clamped down; the event stays at its own time.
        cal = _event_cfg(workday_end="17:00")
        task = {"title": "late", "due": "2026-08-15T18:30", "status": "open"}
        ev = project_task_to_event("T4e", task, cal)
        assert ev.start == datetime(2026, 8, 15, 18, 30)

    def test_custom_duration(self):
        cal = _event_cfg(event_duration_minutes=90)
        task = {"title": "long", "due": "2026-08-15T14:00", "status": "open"}
        ev = project_task_to_event("T5", task, cal)
        assert ev.end == datetime(2026, 8, 15, 15, 30)

    def test_dateless_all_day_default(self):
        cal = _event_cfg(all_day_for_dateless=True)
        task = {"title": "Deadline", "due": "2026-08-15", "status": "open"}
        ev = project_task_to_event("T6", task, cal)
        assert ev.all_day is True
        assert ev.start == datetime(2026, 8, 15, 0, 0)
        assert ev.end == datetime(2026, 8, 16, 0, 0)  # exclusive next day

    def test_dateless_projected_to_workday_start(self):
        cal = _event_cfg(all_day_for_dateless=False, workday_start="09:30")
        task = {"title": "Deadline", "due": "2026-08-15", "status": "open"}
        ev = project_task_to_event("T7", task, cal)
        assert ev.all_day is False
        assert ev.start == datetime(2026, 8, 15, 9, 30)

    def test_dateless_non_allday_sized_by_estimate(self):
        # A date-only due with all_day_for_dateless=False becomes a *timed*
        # event at workday_start, and that event IS sized by the estimate
        # (not the all-day span). Guards the documented date-only + estimate
        # interaction that previously had no coverage.
        cal = _event_cfg(all_day_for_dateless=False, workday_start="09:00")
        task = {"title": "Deadline", "due": "2026-08-15", "status": "open", "estimate": 120}
        ev = project_task_to_event("T7-est", task, cal)
        assert ev.all_day is False
        assert ev.start == datetime(2026, 8, 15, 9, 0)
        assert ev.end == datetime(2026, 8, 15, 11, 0)  # 2h from the estimate

    def test_dateless_all_day_ignores_estimate(self):
        # When all_day_for_dateless=True a date-only due is an all-day event,
        # which has no duration, so a present estimate is ignored (always a
        # one-day exclusive span regardless of the estimate size).
        cal = _event_cfg(all_day_for_dateless=True)
        task = {"title": "Deadline", "due": "2026-08-15", "status": "open", "estimate": 240}
        ev = project_task_to_event("T6-est", task, cal)
        assert ev.all_day is True
        assert ev.start == datetime(2026, 8, 15, 0, 0)
        assert ev.end == datetime(2026, 8, 16, 0, 0)  # one day, estimate ignored

    def test_tags_become_categories(self):
        cal = _event_cfg()
        task = {"title": "x", "due": "2026-08-15T10:00", "tags": ["a", "b"]}
        ev = project_task_to_event("T8", task, cal)
        assert ev.categories == ["a", "b"]

    def test_back_reference_in_description(self):
        cal = _event_cfg()
        task = {"title": "x", "due": "2026-08-15T10:00", "body": "do the thing"}
        ev = project_task_to_event("T9", task, cal, back_reference="myrepo#T9")
        assert "do the thing" in ev.description
        assert "[doto:myrepo#T9]" in ev.description

    def test_status_mapping_event(self):
        cal = _event_cfg()
        task = {"title": "x", "due": "2026-08-15T10:00", "status": "blocked"}
        ev = project_task_to_event("T10", task, cal)
        assert ev.status == "TENTATIVE"

    def test_missing_due_raises(self):
        cal = _event_cfg()
        with pytest.raises(ValueError, match="no due date"):
            project_task_to_event("T11", {"title": "x"}, cal)


class TestTodoProjection:
    def test_todo_mode(self):
        cal = _event_cfg(event_mode="todo")
        task = {"title": "x", "due": "2026-08-15T09:00", "status": "done"}
        ev = project_task_to_event("T12", task, cal)
        assert ev.kind is EventKind.TODO
        assert ev.due == datetime(2026, 8, 15, 9, 0)
        assert ev.status == "COMPLETED"

    def test_todo_dateless(self):
        cal = _event_cfg(event_mode="todo")
        task = {"title": "x", "due": "2026-08-15", "status": "open"}
        ev = project_task_to_event("T13", task, cal)
        assert ev.kind is EventKind.TODO
        assert ev.due == datetime(2026, 8, 15, 0, 0)
        assert ev.status == "NEEDS-ACTION"

    def test_todo_ignores_estimate(self):
        # A VTODO has a due instant but no duration, so an :estimate: must be
        # irrelevant to the todo projection (the todo branch returns before the
        # estimate/duration logic). Pinning this guards against a refactor that
        # moves the estimate computation above the todo branch.
        cal = _event_cfg(event_mode="todo")
        task = {"title": "x", "due": "2026-08-15T09:00", "status": "open", "estimate": 240}
        ev = project_task_to_event("T13e", task, cal)
        assert ev.kind is EventKind.TODO
        assert ev.due == datetime(2026, 8, 15, 9, 0)
        assert ev.end is None  # todos carry no end/duration


class TestProjectorExtensionPoint:
    """The projection used by the engine is swappable via register_projector."""

    def test_default_project_delegates_to_builtin(self):
        cal = _event_cfg()
        task = {"title": "x", "due": "2026-08-15T09:00", "status": "open"}
        assert project("T", task, cal).summary == "x"

    def test_register_projector_overrides(self, monkeypatch):
        # Restore the module default after the test to avoid leaking state.
        original = model_mod._PROJECTOR
        monkeypatch.setattr(model_mod, "_PROJECTOR", original)

        def custom(task_id, task, cal, back_reference=None):
            return CalendarEvent(
                uid=make_uid(task_id),
                kind=EventKind.EVENT,
                summary="CUSTOM-" + task_id,
                task_id=task_id,
            )

        register_projector(custom)
        try:
            cal = _event_cfg()
            ev = project("T99", {"title": "ignored", "due": "2026-08-15"}, cal)
            assert ev.summary == "CUSTOM-T99"
        finally:
            register_projector(original)

        # After restoration, the built-in behavior returns.
        assert project("T", {"title": "x", "due": "2026-08-15T09:00"}, _event_cfg()).summary == "x"
