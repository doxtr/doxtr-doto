"""Tests for the push-first sync engine (engine.py).

Uses an in-memory fake provider so the full create/update/delete/skip lifecycle
can be exercised deterministically without network access.
"""

from __future__ import annotations

from pathlib import Path

from doxtr_doto.calsync.engine import apply_plan, build_plan
from doxtr_doto.calsync.providers.base import CalendarProvider, ProviderError, PushResult
from doxtr_doto.calsync.state import CalSyncState
from doxtr_doto.cli.config import CalendarConfig


class FakeProvider(CalendarProvider):
    """In-memory provider recording operations, for engine tests."""

    name = "fake"

    def __init__(self, config, *, fail_on=None):
        super().__init__(config)
        self.store: dict[str, object] = {}
        self.ops: list[tuple[str, str]] = []
        self._fail_on = fail_on or set()

    def connect(self) -> None:
        self.ops.append(("connect", ""))

    def create_event(self, event):
        if event.task_id in self._fail_on:
            raise ProviderError(f"boom {event.task_id}")
        self.store[event.uid] = event
        self.ops.append(("create", event.task_id))
        return PushResult(uid=event.uid, etag="v1", remote_id="r-" + (event.task_id or ""))

    def update_event(self, event, *, etag="", href=""):
        self.store[event.uid] = event
        self.ops.append(("update", event.task_id))
        return PushResult(uid=event.uid, etag="v2", remote_id="r-" + (event.task_id or ""))

    def delete_event(self, uid, *, etag="", href=""):
        self.store.pop(uid, None)
        self.ops.append(("delete", uid))


def _cfg(**kw) -> CalendarConfig:
    base = {"provider": "fake", "calendar": "primary", "event_mode": "event"}
    base.update(kw)
    return CalendarConfig(**base)


def _state(tmp_path: Path) -> CalSyncState:
    st = CalSyncState(tmp_path / "calsync.json")
    st.load()
    return st


class TestBuildPlan:
    def test_new_tasks_are_created(self, tmp_path):
        cal = _cfg()
        st = _state(tmp_path)
        tasks = {
            "A": {"title": "A", "due": "2026-01-01", "status": "open"},
            "B": {"title": "B", "due": "2026-01-02T10:00", "status": "open"},
        }
        plan = build_plan(tasks, st, cal)
        assert plan.counts()["create"] == 2

    def test_task_without_due_is_ignored(self, tmp_path):
        cal = _cfg()
        st = _state(tmp_path)
        tasks = {"A": {"title": "A", "status": "open"}}
        plan = build_plan(tasks, st, cal)
        assert plan.items == []

    def test_archived_task_without_prior_state_ignored(self, tmp_path):
        cal = _cfg()
        st = _state(tmp_path)
        tasks = {"A": {"title": "A", "due": "2026-01-01", "archived": True}}
        plan = build_plan(tasks, st, cal)
        assert plan.items == []

    def test_unchanged_task_is_skipped(self, tmp_path):
        cal = _cfg()
        st = _state(tmp_path)
        tasks = {"A": {"title": "A", "due": "2026-01-01", "status": "open"}}
        plan = build_plan(tasks, st, cal)
        prov = FakeProvider(cal)
        apply_plan(plan, prov, st, cal)
        plan2 = build_plan(tasks, st, cal)
        assert plan2.counts()["skip"] == 1
        assert plan2.counts()["create"] == 0

    def test_changed_task_is_updated(self, tmp_path):
        cal = _cfg()
        st = _state(tmp_path)
        tasks = {"A": {"title": "A", "due": "2026-01-01", "status": "open"}}
        apply_plan(build_plan(tasks, st, cal), FakeProvider(cal), st, cal)
        tasks["A"]["title"] = "A changed"
        plan = build_plan(tasks, st, cal)
        assert plan.counts()["update"] == 1

    def test_removed_task_is_deleted(self, tmp_path):
        cal = _cfg()
        st = _state(tmp_path)
        tasks = {"A": {"title": "A", "due": "2026-01-01", "status": "open"}}
        apply_plan(build_plan(tasks, st, cal), FakeProvider(cal), st, cal)
        plan = build_plan({}, st, cal)  # A gone from store
        assert plan.counts()["delete"] == 1

    def test_newly_unschedulable_task_is_deleted(self, tmp_path):
        cal = _cfg()
        st = _state(tmp_path)
        tasks = {"A": {"title": "A", "due": "2026-01-01", "status": "open"}}
        apply_plan(build_plan(tasks, st, cal), FakeProvider(cal), st, cal)
        tasks["A"].pop("due")  # loses its due date
        plan = build_plan(tasks, st, cal)
        assert plan.counts()["delete"] == 1

    def test_exclude_statuses_deletes_existing(self, tmp_path):
        cal = _cfg()
        st = _state(tmp_path)
        tasks = {"A": {"title": "A", "due": "2026-01-01", "status": "done"}}
        apply_plan(build_plan(tasks, st, cal), FakeProvider(cal), st, cal)
        plan = build_plan(tasks, st, cal, exclude_statuses={"done"})
        assert plan.counts()["delete"] == 1

    def test_actionable_excludes_skips(self, tmp_path):
        cal = _cfg()
        st = _state(tmp_path)
        tasks = {"A": {"title": "A", "due": "2026-01-01", "status": "open"}}
        apply_plan(build_plan(tasks, st, cal), FakeProvider(cal), st, cal)
        plan = build_plan(tasks, st, cal)
        assert plan.actionable() == []


class TestApplyPlan:
    def test_apply_creates_and_tracks_state(self, tmp_path):
        cal = _cfg()
        st = _state(tmp_path)
        tasks = {"A": {"title": "A", "due": "2026-01-01", "status": "open"}}
        prov = FakeProvider(cal)
        report = apply_plan(build_plan(tasks, st, cal), prov, st, cal)
        assert report.created == 1
        assert report.total_changes() == 1
        ref = st.get("fake", "primary", "A")
        assert ref is not None
        assert ref.remote_id == "r-A"
        assert ref.content_hash != ""

    def test_full_lifecycle(self, tmp_path):
        cal = _cfg()
        st = _state(tmp_path)
        tasks = {
            "A": {"title": "A", "due": "2026-01-01", "status": "open"},
            "B": {"title": "B", "due": "2026-01-02T10:00", "status": "open"},
        }
        prov = FakeProvider(cal)
        apply_plan(build_plan(tasks, st, cal), prov, st, cal)

        tasks["A"]["title"] = "A2"
        del tasks["B"]
        report = apply_plan(build_plan(tasks, st, cal), prov, st, cal)
        assert report.updated == 1
        assert report.deleted == 1
        assert sorted(prov.store.keys()) == ["doto-A@doxtr-doto"]

    def test_per_item_error_does_not_abort(self, tmp_path):
        cal = _cfg()
        st = _state(tmp_path)
        tasks = {
            "A": {"title": "A", "due": "2026-01-01", "status": "open"},
            "B": {"title": "B", "due": "2026-01-02", "status": "open"},
        }
        prov = FakeProvider(cal, fail_on={"A"})
        report = apply_plan(build_plan(tasks, st, cal), prov, st, cal)
        assert report.created == 1  # B succeeded
        assert len(report.errors) == 1
        assert report.errors[0][0] == "A"
        # A's state must NOT be recorded (it failed).
        assert st.get("fake", "primary", "A") is None
        assert st.get("fake", "primary", "B") is not None

    def test_delete_uses_stored_identifiers(self, tmp_path):
        cal = _cfg()
        st = _state(tmp_path)
        tasks = {"A": {"title": "A", "due": "2026-01-01", "status": "open"}}
        prov = FakeProvider(cal)
        apply_plan(build_plan(tasks, st, cal), prov, st, cal)
        apply_plan(build_plan({}, st, cal), prov, st, cal)
        assert ("delete", "doto-A@doxtr-doto") in prov.ops
        assert st.get("fake", "primary", "A") is None
