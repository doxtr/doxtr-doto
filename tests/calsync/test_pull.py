"""Tests for the inbound (pull) and two-way sync engine.

Uses an in-memory fake provider (extended with ``list_events``) and a small
in-memory task store so the full import/update/archive lifecycle and the
two-way orchestration can be exercised deterministically without network
access or the JSON store on disk.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from doxtr_doto.calsync.engine import (
    ConflictResolution,
    PullAction,
    apply_plan,
    apply_pull_plan,
    build_plan,
    build_pull_plan,
    inbound_map,
    merge_doto_owned_conflict,
    merge_wins_policy,
    register_inbound_mapper,
    two_way_sync,
)
from doxtr_doto.calsync.model import EventKind, RemoteEvent, make_uid
from doxtr_doto.calsync.providers.base import CalendarProvider, PushResult
from doxtr_doto.calsync.state import CalSyncState
from doxtr_doto.cli.config import CalendarConfig


class FakeProvider(CalendarProvider):
    """In-memory provider recording push ops and serving remote events."""

    name = "fake"

    def __init__(self, config, *, remote=None):
        super().__init__(config)
        self.store: dict[str, object] = {}
        self.ops: list[tuple[str, str]] = []
        self._remote: list[RemoteEvent] = list(remote or [])

    def connect(self) -> None:
        self.ops.append(("connect", ""))

    def create_event(self, event):
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

    def list_events(self):
        return list(self._remote)


class FakeStore:
    """Minimal in-memory task store satisfying the engine's TaskStore protocol."""

    def __init__(self, tasks=None):
        self.tasks: dict[str, dict] = dict(tasks or {})
        self._counter = 0

    def generate_id(self, prefix: str = "DOTO", sequential: bool = True) -> str:
        self._counter += 1
        return f"{prefix}-{self._counter:03d}"

    def add_task(self, task_id: str, task_data: dict) -> None:
        self.tasks[task_id] = dict(task_data)

    def get_task(self, task_id: str):
        return self.tasks.get(task_id)

    def update_task(self, task_id: str, data: dict) -> bool:
        if task_id not in self.tasks:
            return False
        self.tasks[task_id].update(data)
        return True


def _cfg(**kw) -> CalendarConfig:
    base = {"provider": "fake", "calendar": "primary", "event_mode": "event"}
    base.update(kw)
    return CalendarConfig(**base)


def _state(tmp_path: Path) -> CalSyncState:
    st = CalSyncState(tmp_path / "calsync.json")
    st.load()
    return st


def _remote(uid, summary="Remote", start=None, all_day=False, description=""):
    return RemoteEvent(
        uid=uid,
        remote_id="rid-" + uid,
        summary=summary,
        description=description,
        start=start,
        all_day=all_day,
        kind=EventKind.EVENT,
    )


class TestBuildPullPlan:
    def test_new_user_event_is_imported(self, tmp_path):
        cal = _cfg()
        st = _state(tmp_path)
        rev = _remote("user-123@example.com", "Dentist", datetime(2026, 3, 2, 9, 0))
        plan = build_pull_plan([rev], {}, st, cal)
        assert plan.counts()["import"] == 1
        assert plan.items[0].action is PullAction.IMPORT

    def test_doto_owned_event_is_not_imported(self, tmp_path):
        cal = _cfg()
        st = _state(tmp_path)
        rev = _remote(make_uid("A"), "A", datetime(2026, 3, 2, 9, 0))
        plan = build_pull_plan([rev], {}, st, cal)
        assert plan.counts()["import"] == 0
        assert plan.items[0].action is PullAction.SKIP

    def test_second_pull_is_idempotent(self, tmp_path):
        cal = _cfg()
        st = _state(tmp_path)
        store = FakeStore()
        rev = _remote("user-xyz@example.com", "Dentist", datetime(2026, 3, 2, 9, 0))
        apply_pull_plan(build_pull_plan([rev], store.tasks, st, cal), store, st, cal)
        # Second pull of the identical event: no action.
        plan2 = build_pull_plan([rev], store.tasks, st, cal)
        assert plan2.counts()["import"] == 0
        assert plan2.actionable() == []

    def test_changed_remote_updates_local(self, tmp_path):
        cal = _cfg()
        st = _state(tmp_path)
        store = FakeStore()
        rev = _remote("user-xyz@example.com", "Dentist", datetime(2026, 3, 2, 9, 0))
        apply_pull_plan(build_pull_plan([rev], store.tasks, st, cal), store, st, cal)
        changed = _remote("user-xyz@example.com", "Dentist (moved)", datetime(2026, 3, 3, 9, 0))
        plan = build_pull_plan([changed], store.tasks, st, cal)
        assert plan.counts()["update_local"] == 1

    def test_deleted_remote_archives_local(self, tmp_path):
        cal = _cfg()
        st = _state(tmp_path)
        store = FakeStore()
        rev = _remote("user-xyz@example.com", "Dentist", datetime(2026, 3, 2, 9, 0))
        apply_pull_plan(build_pull_plan([rev], store.tasks, st, cal), store, st, cal)
        # Now the remote is gone entirely.
        plan = build_pull_plan([], store.tasks, st, cal)
        assert plan.counts()["archive_local"] == 1


class TestApplyPullPlan:
    def test_import_creates_task_and_tracks_state(self, tmp_path):
        cal = _cfg()
        st = _state(tmp_path)
        store = FakeStore()
        rev = _remote(
            "user-123@example.com",
            "Dentist",
            datetime(2026, 3, 2, 9, 0),
            description="Body text\n\n[doto:repo#OLD]",
        )
        report = apply_pull_plan(build_pull_plan([rev], store.tasks, st, cal), store, st, cal)
        assert report.imported == 1
        assert len(store.tasks) == 1
        ((tid, task),) = store.tasks.items()
        assert task["title"] == "Dentist"
        # Back-reference line stripped from the imported body.
        assert task["body"] == "Body text"
        assert task["due"] == "2026-03-02T09:00"
        assert task["status"] == "open"
        ref = st.get_imported("fake", "primary", "user-123@example.com")
        assert ref is not None
        assert ref.task_id == tid

    def test_all_day_import_is_date_only(self, tmp_path):
        cal = _cfg()
        st = _state(tmp_path)
        store = FakeStore()
        rev = _remote("ad@example.com", "Holiday", datetime(2026, 7, 4, 0, 0), all_day=True)
        apply_pull_plan(build_pull_plan([rev], store.tasks, st, cal), store, st, cal)
        (task,) = store.tasks.values()
        assert task["due"] == "2026-07-04"

    def test_update_local_applies_remote_fields(self, tmp_path):
        cal = _cfg()
        st = _state(tmp_path)
        store = FakeStore()
        rev = _remote("u@example.com", "Call", datetime(2026, 3, 2, 9, 0))
        apply_pull_plan(build_pull_plan([rev], store.tasks, st, cal), store, st, cal)
        changed = _remote("u@example.com", "Call (rescheduled)", datetime(2026, 3, 5, 10, 0))
        apply_pull_plan(build_pull_plan([changed], store.tasks, st, cal), store, st, cal)
        (task,) = store.tasks.values()
        assert task["title"] == "Call (rescheduled)"
        assert task["due"] == "2026-03-05T10:00"

    def test_archive_local_soft_deletes(self, tmp_path):
        cal = _cfg()
        st = _state(tmp_path)
        store = FakeStore()
        rev = _remote("u@example.com", "Call", datetime(2026, 3, 2, 9, 0))
        apply_pull_plan(build_pull_plan([rev], store.tasks, st, cal), store, st, cal)
        (tid,) = store.tasks.keys()
        report = apply_pull_plan(build_pull_plan([], store.tasks, st, cal), store, st, cal)
        assert report.archived == 1
        assert store.tasks[tid]["archived"] is True
        # The task is NOT hard-deleted.
        assert tid in store.tasks
        # Import record cleared so it won't archive again.
        assert st.get_imported("fake", "primary", "u@example.com") is None


class TestTwoWay:
    def test_only_remote_new(self, tmp_path):
        cal = _cfg()
        st = _state(tmp_path)
        store = FakeStore()
        rev = _remote("u1@example.com", "New remote", datetime(2026, 3, 2, 9, 0))
        prov = FakeProvider(cal, remote=[rev])
        report = two_way_sync(
            prov,
            store,
            dict(store.tasks),
            st,
            cal,
            reload_tasks=lambda: dict(store.tasks),
        )
        assert report.pull.imported == 1
        # The freshly imported task must NOT be pushed back out -- it already
        # exists remotely as the user's event; re-pushing it would create a
        # duplicate doto-owned copy on the calendar.
        assert report.push.created == 0
        # No doto-owned create op was recorded for the imported task.
        assert ("create", "DOTO-001") not in prov.ops

    def test_only_local_new(self, tmp_path):
        cal = _cfg()
        st = _state(tmp_path)
        store = FakeStore({"A": {"title": "A", "due": "2026-01-01", "status": "open"}})
        prov = FakeProvider(cal, remote=[])
        report = two_way_sync(
            prov,
            store,
            dict(store.tasks),
            st,
            cal,
            reload_tasks=lambda: dict(store.tasks),
        )
        assert report.pull.imported == 0
        assert report.push.created == 1

    def test_both_local_and_remote_new(self, tmp_path):
        cal = _cfg()
        st = _state(tmp_path)
        store = FakeStore(
            {
                "A": {"title": "A", "due": "2026-01-01", "status": "open"},
                "B": {"title": "B", "due": "2026-01-02", "status": "open"},
            }
        )
        remote = [
            _remote("u1@example.com", "R1", datetime(2026, 3, 2, 9, 0)),
            _remote("u2@example.com", "R2", datetime(2026, 3, 3, 9, 0)),
        ]
        prov = FakeProvider(cal, remote=remote)
        report = two_way_sync(
            prov,
            store,
            dict(store.tasks),
            st,
            cal,
            reload_tasks=lambda: dict(store.tasks),
        )
        # Two remote imports; only the local tasks A and B are pushed -- the
        # two imported tasks must NOT be re-pushed (they already exist remotely
        # as the user's events, so pushing them would duplicate them).
        assert report.pull.imported == 2
        assert report.push.created == 2
        created_ids = {tid for op, tid in prov.ops if op == "create"}
        assert created_ids == {"A", "B"}

    def test_exactly_one_each(self, tmp_path):
        cal = _cfg()
        st = _state(tmp_path)
        store = FakeStore({"A": {"title": "A", "due": "2026-01-01", "status": "open"}})
        remote = [_remote("u1@example.com", "R1", datetime(2026, 3, 2, 9, 0))]
        prov = FakeProvider(cal, remote=remote)
        report = two_way_sync(
            prov,
            store,
            dict(store.tasks),
            st,
            cal,
            reload_tasks=lambda: dict(store.tasks),
        )
        assert report.pull.imported == 1
        # Only the local task A is pushed; the imported remote task is not
        # pushed back out (it already exists remotely).
        assert report.push.created == 1
        created_ids = {tid for op, tid in prov.ops if op == "create"}
        assert created_ids == {"A"}

    def test_import_is_not_re_pushed_on_second_sync(self, tmp_path):
        """An imported remote event is never pushed back as a doto-owned copy.

        Regression for the two-way duplication bug: pull imports a user-created
        event as a task, and the subsequent push (same sync, and every later
        sync) must leave it alone. Otherwise each sync would create a duplicate
        doto-owned event alongside the user's original, and a real provider
        (Google) would reject the repeated iCalUID with HTTP 409 on the first
        re-create. We assert zero creates across two syncs for the import.
        """
        cal = _cfg()
        st = _state(tmp_path)
        store = FakeStore()
        rev = _remote("user@example.com", "User event", datetime(2026, 4, 1, 9, 0))
        prov = FakeProvider(cal, remote=[rev])

        two_way_sync(
            prov, store, dict(store.tasks), st, cal, reload_tasks=lambda: dict(store.tasks)
        )
        # Second sync: the imported event is still present remotely.
        report2 = two_way_sync(
            prov, store, dict(store.tasks), st, cal, reload_tasks=lambda: dict(store.tasks)
        )

        assert report2.push.created == 0
        # No doto-owned event was ever created for the imported task.
        assert all(op != "create" for op, _ in prov.ops)
        # The user's original event is the only non-doto remote item; no
        # doto-owned twin was added to the provider store.
        assert make_uid("DOTO-001") not in prov.store

    def test_conflict_is_local_wins(self, tmp_path):
        """Both a local task and its doto-owned remote event changed -> local wins."""
        cal = _cfg()
        st = _state(tmp_path)
        store = FakeStore({"A": {"title": "A", "due": "2026-01-01", "status": "open"}})
        # First push creates the doto-owned remote event + state.
        apply_plan(build_plan(store.tasks, st, cal), FakeProvider(cal), st, cal)

        # Local edit.
        store.tasks["A"]["title"] = "A local change"
        # Remote edit of the SAME doto-owned event.
        remote_doto = _remote(make_uid("A"), "A remote change", datetime(2026, 1, 1, 8, 0))
        prov = FakeProvider(cal, remote=[remote_doto])

        report = two_way_sync(
            prov,
            store,
            dict(store.tasks),
            st,
            cal,
            reload_tasks=lambda: dict(store.tasks),
        )
        # The conflict is detected...
        assert report.conflicts == ["A"]
        # ...and resolved local-wins: the local task keeps its edit and push
        # overwrites the remote (an UPDATE), never re-importing the remote text.
        assert store.tasks["A"]["title"] == "A local change"
        assert report.pull.imported == 0
        assert report.push.updated == 1

    def test_two_way_idempotent(self, tmp_path):
        cal = _cfg()
        st = _state(tmp_path)
        store = FakeStore({"A": {"title": "A", "due": "2026-01-01", "status": "open"}})
        rev = _remote("u1@example.com", "R1", datetime(2026, 3, 2, 9, 0))
        prov = FakeProvider(cal, remote=[rev])
        two_way_sync(
            prov,
            store,
            dict(store.tasks),
            st,
            cal,
            reload_tasks=lambda: dict(store.tasks),
        )
        # Second run with the same remote view: no new imports, no new creates.
        # Remote now also contains the doto-owned items push created; feed those
        # back so the provider's view is realistic.
        doto_uids = list(prov.store)
        remote2 = [rev] + [
            _remote(u, prov.store[u].summary, prov.store[u].start) for u in doto_uids
        ]
        prov2 = FakeProvider(cal, remote=remote2)
        report = two_way_sync(
            prov2,
            store,
            dict(store.tasks),
            st,
            cal,
            reload_tasks=lambda: dict(store.tasks),
        )
        assert report.pull.imported == 0
        assert report.push.created == 0


class TestConflictBaseline:
    """The inbound baseline hash must prevent spurious conflicts (P1.1)."""

    def test_local_only_edit_with_unchanged_remote_is_not_a_conflict(self, tmp_path):
        """A routine local edit of a previously-pushed task is NOT a conflict.

        Regression for the false-positive conflict bug: ``_pushed_inbound_hash``
        used to always return "", so every local-only edit of a pushed task was
        flagged as a conflict. With the stored inbound baseline, an untouched
        remote compares equal and reports no conflict.
        """
        cal = _cfg()
        st = _state(tmp_path)
        store = FakeStore({"A": {"title": "A", "due": "2026-01-01T09:00", "status": "open"}})
        prov = FakeProvider(cal)
        # First push creates the doto-owned remote event + inbound baseline.
        apply_plan(build_plan(store.tasks, st, cal), prov, st, cal)

        # The remote the server would return for the just-pushed event, read
        # back UNCHANGED (same summary/body/due the push wrote).
        pushed = prov.store[make_uid("A")]
        remote_unchanged = RemoteEvent(
            uid=make_uid("A"),
            summary=pushed.summary,
            description=pushed.description,
            start=pushed.start,
            end=pushed.end,
            all_day=pushed.all_day,
            kind=EventKind.EVENT,
        )

        # Local-only edit (title change); remote is untouched.
        store.tasks["A"]["title"] = "A edited locally"
        prov2 = FakeProvider(cal, remote=[remote_unchanged])
        report = two_way_sync(
            prov2,
            store,
            dict(store.tasks),
            st,
            cal,
            reload_tasks=lambda: dict(store.tasks),
        )
        assert report.conflicts == []
        # The local edit is still pushed out as an UPDATE.
        assert report.push.updated == 1

    def test_both_sides_change_is_still_a_conflict(self, tmp_path):
        """A genuine dual edit is still reported (local-wins preserved)."""
        cal = _cfg()
        st = _state(tmp_path)
        store = FakeStore({"A": {"title": "A", "due": "2026-01-01T09:00", "status": "open"}})
        apply_plan(build_plan(store.tasks, st, cal), FakeProvider(cal), st, cal)

        store.tasks["A"]["title"] = "A local change"
        remote_changed = RemoteEvent(
            uid=make_uid("A"),
            summary="A remote change",
            description="[doto:A]",
            start=datetime(2026, 1, 1, 9, 0),
            kind=EventKind.EVENT,
        )
        prov = FakeProvider(cal, remote=[remote_changed])
        report = two_way_sync(
            prov,
            store,
            dict(store.tasks),
            st,
            cal,
            reload_tasks=lambda: dict(store.tasks),
        )
        assert report.conflicts == ["A"]
        assert store.tasks["A"]["title"] == "A local change"
        assert report.push.updated == 1


class TestInboundMapperSeam:
    """register_inbound_mapper swaps the RemoteEvent -> task-fields mapping."""

    def test_custom_inbound_mapper_is_used(self, tmp_path):
        cal = _cfg()
        st = _state(tmp_path)
        store = FakeStore()
        rev = _remote("user@example.com", "Dentist", datetime(2026, 3, 2, 9, 0))

        def _custom(remote, cal):
            return {"title": "MAPPED:" + remote.summary, "body": "custom"}

        register_inbound_mapper(_custom)
        try:
            apply_pull_plan(build_pull_plan([rev], store.tasks, st, cal), store, st, cal)
        finally:
            # Restore the built-in mapper so other tests are unaffected.
            from doxtr_doto.calsync.engine import _task_fields_from_remote

            register_inbound_mapper(_task_fields_from_remote)
        (task,) = store.tasks.values()
        assert task["title"] == "MAPPED:Dentist"
        assert task["body"] == "custom"

    def test_default_inbound_map_maps_summary_and_body(self):
        rev = _remote("u@example.com", "Hello", datetime(2026, 3, 2, 9, 0), description="Body")
        fields = inbound_map(rev, _cfg())
        assert fields["title"] == "Hello"
        assert fields["body"] == "Body"
        assert fields["due"] == "2026-03-02T09:00"


class TestInboundEstimate:
    """A timed event's duration maps back onto the task estimate."""

    def test_timed_duration_minutes_helper(self):
        from datetime import datetime as _dt

        from doxtr_doto.calsync.model import timed_duration_minutes

        assert timed_duration_minutes(False, _dt(2026, 1, 1, 9, 0), _dt(2026, 1, 1, 9, 45)) == 45
        # all-day, missing end, and non-positive span all yield None.
        assert timed_duration_minutes(True, _dt(2026, 1, 1), _dt(2026, 1, 2)) is None
        assert timed_duration_minutes(False, _dt(2026, 1, 1, 9, 0), None) is None
        assert timed_duration_minutes(False, _dt(2026, 1, 1, 9, 0), _dt(2026, 1, 1, 9, 0)) is None

    def test_non_default_estimate_helper(self):
        from doxtr_doto.calsync.engine import _non_default_estimate_minutes

        cal = _cfg(event_duration_minutes=30)
        assert _non_default_estimate_minutes(45, cal) == 45
        assert _non_default_estimate_minutes(30, cal) is None  # default -> no estimate
        assert _non_default_estimate_minutes(None, cal) is None
        # No cal -> any duration is taken literally.
        assert _non_default_estimate_minutes(30, None) == 30

    def _timed(self, start, end, all_day=False):
        return RemoteEvent(
            uid="user@example.com",
            summary="Practice",
            description="",
            start=start,
            end=end,
            all_day=all_day,
            kind=EventKind.EVENT,
        )

    def test_non_default_duration_sets_estimate(self):
        # 10:45-11:30 == 45 minutes; default event_duration_minutes is 30, so
        # the estimate IS set (the user picked a non-default length).
        rev = self._timed(datetime(2026, 10, 18, 10, 45), datetime(2026, 10, 18, 11, 30))
        fields = inbound_map(rev, _cfg(event_duration_minutes=30))
        assert fields["estimate"] == "45m"
        assert rev.inbound_estimate_minutes() == 45

    def test_default_duration_does_not_set_estimate(self):
        # A 30-minute event with a 30-minute default is the round-trip of a
        # task that had no estimate -> do NOT stamp a spurious estimate.
        rev = self._timed(datetime(2026, 10, 18, 9, 0), datetime(2026, 10, 18, 9, 30))
        fields = inbound_map(rev, _cfg(event_duration_minutes=30))
        assert "estimate" not in fields

    def test_hour_duration_formats_canonically(self):
        rev = self._timed(datetime(2026, 10, 18, 9, 0), datetime(2026, 10, 18, 10, 30))
        fields = inbound_map(rev, _cfg(event_duration_minutes=30))
        assert fields["estimate"] == "1h30m"

    def test_all_day_has_no_estimate(self):
        rev = self._timed(datetime(2026, 10, 18, 0, 0), datetime(2026, 10, 19, 0, 0), all_day=True)
        assert rev.inbound_estimate_minutes() is None
        fields = inbound_map(rev, _cfg())
        assert "estimate" not in fields

    def test_missing_end_has_no_estimate(self):
        rev = self._timed(datetime(2026, 10, 18, 9, 0), None)
        assert rev.inbound_estimate_minutes() is None


class TestConflictPolicySeam:
    """two_way_sync accepts an injectable conflict policy (default local-wins)."""

    def test_default_policy_resolves_local_wins(self, tmp_path):
        cal = _cfg()
        st = _state(tmp_path)
        store = FakeStore({"A": {"title": "A", "due": "2026-01-01T09:00", "status": "open"}})
        apply_plan(build_plan(store.tasks, st, cal), FakeProvider(cal), st, cal)
        store.tasks["A"]["title"] = "A local"
        remote_changed = RemoteEvent(
            uid=make_uid("A"),
            summary="A remote",
            description="[doto:A]",
            start=datetime(2026, 1, 1, 9, 0),
            kind=EventKind.EVENT,
        )
        prov = FakeProvider(cal, remote=[remote_changed])
        report = two_way_sync(
            prov,
            store,
            dict(store.tasks),
            st,
            cal,
            reload_tasks=lambda: dict(store.tasks),
        )
        assert report.conflicts == ["A"]
        assert store.tasks["A"]["title"] == "A local"  # local wins

    def test_custom_policy_is_consulted(self, tmp_path):
        cal = _cfg()
        st = _state(tmp_path)
        store = FakeStore({"A": {"title": "A", "due": "2026-01-01T09:00", "status": "open"}})
        apply_plan(build_plan(store.tasks, st, cal), FakeProvider(cal), st, cal)
        store.tasks["A"]["title"] = "A local"
        remote_changed = RemoteEvent(
            uid=make_uid("A"),
            summary="A remote",
            description="[doto:A]",
            start=datetime(2026, 1, 1, 9, 0),
            kind=EventKind.EVENT,
        )
        prov = FakeProvider(cal, remote=[remote_changed])

        seen: list[str] = []

        def _policy(task_id, task, remote, prior):
            seen.append(task_id)
            return ConflictResolution.REMOTE_WINS

        report = two_way_sync(
            prov,
            store,
            dict(store.tasks),
            st,
            cal,
            reload_tasks=lambda: dict(store.tasks),
            conflict_policy=_policy,
        )
        # The policy was consulted for the conflicted task.
        assert seen == ["A"]
        # REMOTE_WINS is not wired, so it falls back to the local-wins flow;
        # local work is kept.
        assert report.conflicts == ["A"]
        assert store.tasks["A"]["title"] == "A local"


class TestMergePolicy:
    """merge_wins_policy three-way merges a dual edit instead of discarding one."""

    def _setup_pushed(self, tmp_path, task):
        """Push a task once so it has a doto-owned remote event + base snapshot."""
        cal = _cfg()
        st = _state(tmp_path)
        store = FakeStore({"A": dict(task)})
        prov = FakeProvider(cal)
        apply_plan(build_plan(store.tasks, st, cal), prov, st, cal)
        return cal, st, store, prov

    def _pushed_remote(self, prov, *, summary=None, description=None):
        """Build the remote read-back of the pushed event, optionally edited."""
        pushed = prov.store[make_uid("A")]
        return RemoteEvent(
            uid=make_uid("A"),
            summary=summary if summary is not None else pushed.summary,
            description=description if description is not None else pushed.description,
            start=pushed.start,
            end=pushed.end,
            all_day=pushed.all_day,
            kind=EventKind.EVENT,
        )

    def test_base_snapshot_is_stored_on_push(self, tmp_path):
        cal, st, store, prov = self._setup_pushed(
            tmp_path, {"title": "A", "body": "hello", "due": "2026-01-01", "status": "open"}
        )
        ref = st.get(cal.provider, cal.calendar, "A")
        assert ref is not None
        assert ref.base_title == "A"
        assert ref.base_body == "hello"
        assert ref.base_due == "2026-01-01"

    def test_remote_only_body_edit_is_pulled_back_cleanly(self, tmp_path):
        """A remote-only edit of a doto event merges in without markers.

        Regression for the gap where pull skips doto-owned events: a note typed
        into the calendar app (local task untouched) must still flow back. With
        a recorded base snapshot the three-way merge takes the remote value
        cleanly (no conflict markers), since base == local.
        """
        cal, st, store, prov = self._setup_pushed(
            tmp_path,
            {"title": "A", "body": "original", "due": "2026-01-01", "status": "open"},
        )
        # Local unchanged; remote body edited (with the pushed back-ref marker).
        remote = self._pushed_remote(prov, description="original\n\nextra remote note\n\n[doto:A]")
        prov2 = FakeProvider(cal, remote=[remote])
        report = two_way_sync(
            prov2,
            store,
            dict(store.tasks),
            st,
            cal,
            reload_tasks=lambda: dict(store.tasks),
            conflict_policy=merge_wins_policy,
        )
        assert report.merged == ["A"]
        assert report.merge_conflicts == []  # clean take-remote, no markers
        assert store.tasks["A"]["body"] == "original\n\nextra remote note"

    def test_remote_only_edit_is_noop_under_local_wins(self, tmp_path):
        """Under the default local-wins policy a remote-only edit is NOT pulled.

        This documents the deliberate difference between the two policies:
        local-wins keeps doto as the system of record and discards the remote
        edit (push overwrites it); only the merge policy reconciles it back.
        """
        cal, st, store, prov = self._setup_pushed(
            tmp_path,
            {"title": "A", "body": "original", "due": "2026-01-01", "status": "open"},
        )
        remote = self._pushed_remote(prov, description="original\n\nremote note\n\n[doto:A]")
        prov2 = FakeProvider(cal, remote=[remote])
        report = two_way_sync(
            prov2,
            store,
            dict(store.tasks),
            st,
            cal,
            reload_tasks=lambda: dict(store.tasks),
            # default conflict_policy == local_wins_policy
        )
        assert report.merged == []
        assert store.tasks["A"]["body"] == "original"  # remote edit discarded

    def test_disjoint_body_edits_merge_without_conflict(self, tmp_path):
        cal, st, store, prov = self._setup_pushed(
            tmp_path,
            {"title": "A", "body": "l1\nl2\nl3", "due": "2026-01-01", "status": "open"},
        )
        # Local edits line 1; remote edits line 3 -> both kept, no conflict.
        store.tasks["A"]["body"] = "L1\nl2\nl3"
        remote = self._pushed_remote(prov, description="l1\nl2\nL3\n\n[doto:A]")
        prov2 = FakeProvider(cal, remote=[remote])
        report = two_way_sync(
            prov2,
            store,
            dict(store.tasks),
            st,
            cal,
            reload_tasks=lambda: dict(store.tasks),
            conflict_policy=merge_wins_policy,
        )
        assert report.merged == ["A"]
        assert report.merge_conflicts == []
        assert store.tasks["A"]["body"] == "L1\nl2\nL3"
        # The merged result is re-pushed so the calendar converges (an UPDATE).
        assert report.push.updated == 1

    def test_true_body_divergence_emits_conflict_markers(self, tmp_path):
        cal, st, store, prov = self._setup_pushed(
            tmp_path,
            {"title": "A", "body": "l1\nl2\nl3", "due": "2026-01-01", "status": "open"},
        )
        # Both edit the SAME line differently -> git-style conflict markers.
        store.tasks["A"]["body"] = "l1\nLOCAL\nl3"
        remote = self._pushed_remote(prov, description="l1\nREMOTE\nl3\n\n[doto:A]")
        prov2 = FakeProvider(cal, remote=[remote])
        report = two_way_sync(
            prov2,
            store,
            dict(store.tasks),
            st,
            cal,
            reload_tasks=lambda: dict(store.tasks),
            conflict_policy=merge_wins_policy,
        )
        assert report.merged == ["A"]
        assert report.merge_conflicts == ["A"]
        body = store.tasks["A"]["body"]
        assert "<<<<<<<" in body and "=======" in body and ">>>>>>>" in body
        assert "LOCAL" in body and "REMOTE" in body
        # A real text conflict sets the persistent flag so it is findable later
        # via ``doto list --conflicts``.
        assert store.tasks["A"]["sync_conflict"] is True
        # The per-field base/local/remote/both candidates are stashed under
        # ``_sync.conflict`` so a resolver can offer a clean choice later.
        conflict = store.tasks["A"]["_sync"]["conflict"]
        body_rec = next(f for f in conflict["fields"] if f["field"] == "body")
        assert body_rec["local"] == "l1\nLOCAL\nl3"
        assert body_rec["remote"] == "l1\nREMOTE\nl3"
        assert "<<<<<<<" in body_rec["both"]

    def test_resolve_after_conflict_clears_flag_and_stash(self, tmp_path):
        from doxtr_doto.calsync.resolve import ResolutionChoice, resolve_conflict

        cal, st, store, prov = self._setup_pushed(
            tmp_path,
            {"title": "A", "body": "l1\nl2\nl3", "due": "2026-01-01", "status": "open"},
        )
        store.tasks["A"]["body"] = "l1\nLOCAL\nl3"
        remote = self._pushed_remote(prov, description="l1\nREMOTE\nl3\n\n[doto:A]")
        prov2 = FakeProvider(cal, remote=[remote])
        two_way_sync(
            prov2,
            store,
            dict(store.tasks),
            st,
            cal,
            reload_tasks=lambda: dict(store.tasks),
            conflict_policy=merge_wins_policy,
        )
        # Resolve: keep the remote body -> flag + stash cleared.
        updates = resolve_conflict(store.tasks["A"], ResolutionChoice.REMOTE)
        store.tasks["A"].update(updates)
        assert store.tasks["A"]["body"] == "l1\nREMOTE\nl3"
        assert store.tasks["A"]["sync_conflict"] is False
        assert store.tasks["A"]["_sync"]["conflict"] is None

    def test_title_changed_remote_only_takes_remote(self, tmp_path):
        cal, st, store, prov = self._setup_pushed(
            tmp_path, {"title": "A", "body": "b", "due": "2026-01-01", "status": "open"}
        )
        # Local edits body only; remote edits title only -> both applied.
        store.tasks["A"]["body"] = "b local"
        remote = self._pushed_remote(prov, summary="A renamed remotely")
        prov2 = FakeProvider(cal, remote=[remote])
        report = two_way_sync(
            prov2,
            store,
            dict(store.tasks),
            st,
            cal,
            reload_tasks=lambda: dict(store.tasks),
            conflict_policy=merge_wins_policy,
        )
        assert report.merged == ["A"]
        assert report.merge_conflicts == []
        assert store.tasks["A"]["title"] == "A renamed remotely"
        assert store.tasks["A"]["body"] == "b local"
        # A clean merge explicitly clears the flag (False), so a task resolved
        # and re-synced drops out of the ``--conflicts`` filter.
        assert store.tasks["A"]["sync_conflict"] is False

    def test_merge_unit_title_local_only(self, tmp_path):
        """merge_doto_owned_conflict: only-local title change takes local."""
        from doxtr_doto.calsync.state import RemoteRef

        prior = RemoteRef(uid=make_uid("A"), base_title="Old", base_body="B", base_due="")
        task = {"title": "New local", "body": "B", "due": ""}
        remote = RemoteEvent(uid=make_uid("A"), summary="Old", description="B", all_day=True)
        res = merge_doto_owned_conflict(task, remote, prior)
        assert res.fields["title"] == "New local"
        assert res.had_text_conflict is False

    def test_merge_unit_due_divergence_keeps_local(self, tmp_path):
        """A true due divergence keeps the local due and flags a conflict."""
        from doxtr_doto.calsync.state import RemoteRef

        prior = RemoteRef(uid=make_uid("A"), base_title="A", base_body="", base_due="2026-01-01")
        task = {"title": "A", "body": "", "due": "2026-02-02"}
        remote = RemoteEvent(
            uid=make_uid("A"),
            summary="A",
            description="",
            start=datetime(2026, 3, 3),
            all_day=True,
        )
        res = merge_doto_owned_conflict(task, remote, prior)
        assert res.fields["due"] == "2026-02-02"  # local kept, never a marker
        assert res.had_text_conflict is True

    def test_remote_duration_change_flows_back_as_estimate(self, tmp_path):
        """Resizing a timed event on the calendar updates the task estimate.

        End-to-end: push a timed task (no estimate -> default 30m event), then
        the user drags the event end to 11:30 (45m). The merge policy maps the
        new duration back onto the task's estimate so the end recomputes on the
        next push.
        """
        cal = _cfg(event_duration_minutes=30)
        st = _state(tmp_path)
        store = FakeStore(
            {"A": {"title": "A", "body": "", "due": "2026-10-18T10:45", "status": "open"}}
        )
        prov = FakeProvider(cal)
        apply_plan(build_plan(store.tasks, st, cal), prov, st, cal)

        # The user resized the event on the calendar: 10:45 -> 11:30 (45 min).
        pushed = prov.store[make_uid("A")]
        resized = RemoteEvent(
            uid=make_uid("A"),
            summary=pushed.summary,
            description=pushed.description,
            start=datetime(2026, 10, 18, 10, 45),
            end=datetime(2026, 10, 18, 11, 30),
            all_day=False,
            kind=EventKind.EVENT,
        )
        prov2 = FakeProvider(cal, remote=[resized])
        report = two_way_sync(
            prov2,
            store,
            dict(store.tasks),
            st,
            cal,
            reload_tasks=lambda: dict(store.tasks),
            conflict_policy=merge_wins_policy,
        )
        assert report.merged == ["A"]
        assert store.tasks["A"]["estimate"] == "45m"

    def test_merge_unit_estimate_remote_only(self, tmp_path):
        """merge_doto_owned_conflict: a remote-only duration sets the estimate."""
        from doxtr_doto.calsync.state import RemoteRef

        # Base/local had no estimate; remote event is 45 minutes long.
        prior = RemoteRef(
            uid=make_uid("A"),
            base_title="A",
            base_body="",
            base_due="2026-10-18T10:45",
            base_estimate="",
        )
        task = {"title": "A", "body": "", "due": "2026-10-18T10:45"}
        remote = RemoteEvent(
            uid=make_uid("A"),
            summary="A",
            description="",
            start=datetime(2026, 10, 18, 10, 45),
            end=datetime(2026, 10, 18, 11, 30),
            all_day=False,
        )
        res = merge_doto_owned_conflict(task, remote, prior)
        assert res.fields["estimate"] == "45m"
        assert res.had_text_conflict is False

    def test_second_sync_after_merge_is_clean_noop(self, tmp_path):
        """The baseline refresh must make a repeated merge sync a no-op.

        Regression lock for the convergence fix: after a merge, the stored
        inbound baseline is refreshed to the reconciled remote hash, so feeding
        the re-pushed event back on a second sync produces no merge and no push.
        A regression (stale baseline, or a merged body that fails to round-trip
        through push's [doto:] append + strip) would re-merge every run.
        """
        cal, st, store, prov = self._setup_pushed(
            tmp_path,
            {"title": "A", "body": "l1\nl2\nl3", "due": "2026-01-01", "status": "open"},
        )
        store.tasks["A"]["body"] = "L1\nl2\nl3"
        remote = self._pushed_remote(prov, description="l1\nl2\nL3\n\n[doto:A]")
        prov2 = FakeProvider(cal, remote=[remote])
        two_way_sync(
            prov2,
            store,
            dict(store.tasks),
            st,
            cal,
            reload_tasks=lambda: dict(store.tasks),
            conflict_policy=merge_wins_policy,
        )
        merged_body = store.tasks["A"]["body"]
        # Second sync: feed back the re-pushed event as the remote view.
        repushed = prov2.store[make_uid("A")]
        read_back = RemoteEvent(
            uid=repushed.uid,
            summary=repushed.summary,
            description=repushed.description,
            start=repushed.start,
            end=repushed.end,
            all_day=repushed.all_day,
            kind=EventKind.EVENT,
        )
        prov3 = FakeProvider(cal, remote=[read_back])
        report2 = two_way_sync(
            prov3,
            store,
            dict(store.tasks),
            st,
            cal,
            reload_tasks=lambda: dict(store.tasks),
            conflict_policy=merge_wins_policy,
        )
        assert report2.merged == []
        assert report2.push.updated == 0
        assert store.tasks["A"]["body"] == merged_body

    def test_estimate_true_divergence_keeps_local(self, tmp_path):
        """base/local/remote estimates all differ -> keep local, flag conflict."""
        from doxtr_doto.calsync.state import RemoteRef

        prior = RemoteRef(
            uid=make_uid("A"),
            base_title="A",
            base_body="",
            base_due="2026-10-18T10:45",
            base_estimate="30m",
        )
        task = {"title": "A", "body": "", "due": "2026-10-18T10:45", "estimate": "45m"}
        remote = RemoteEvent(
            uid=make_uid("A"),
            summary="A",
            description="",
            start=datetime(2026, 10, 18, 10, 45),
            end=datetime(2026, 10, 18, 11, 45),  # 60m -- diverges from base(30) and local(45)
            all_day=False,
        )
        res = merge_doto_owned_conflict(task, remote, prior, _cfg(event_duration_minutes=30))
        assert res.fields["estimate"] == "45m"  # local kept
        assert res.had_text_conflict is True


class TestBodyMergerSeam:
    """register_body_merger swaps the three-way body-merge strategy."""

    def test_custom_body_merger_is_used(self, tmp_path):
        from doxtr_doto.calsync.engine import register_body_merger
        from doxtr_doto.calsync.state import RemoteRef
        from doxtr_doto.calsync.textmerge import MergeOutcome

        prior = RemoteRef(uid=make_uid("A"), base_title="A", base_body="base", base_due="")
        task = {"title": "A", "body": "local", "due": ""}
        remote = RemoteEvent(uid=make_uid("A"), summary="A", description="remote", all_day=True)

        def _custom(base, local, remote):
            return MergeOutcome("CUSTOM-MERGED", False)

        register_body_merger(_custom)
        try:
            res = merge_doto_owned_conflict(task, remote, prior)
        finally:
            # Restore the built-in diff3 merger so other tests are unaffected.
            from doxtr_doto.calsync.engine import _default_body_merger

            register_body_merger(_default_body_merger)
        assert res.fields["body"] == "CUSTOM-MERGED"
