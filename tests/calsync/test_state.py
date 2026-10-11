"""Tests for the sync-state store (state.py)."""

from __future__ import annotations

from doxtr_doto.calsync.state import CalSyncState, RemoteRef


class TestRemoteRef:
    def test_round_trip_dict(self):
        ref = RemoteRef(
            uid="u", etag="e", href="h", content_hash="c", remote_id="r", updated="2026-01-01"
        )
        assert RemoteRef.from_dict(ref.to_dict()) == ref

    def test_from_dict_defaults(self):
        ref = RemoteRef.from_dict({"uid": "u"})
        assert ref.uid == "u"
        assert ref.etag == ""


class TestCalSyncState:
    def test_empty_load_and_save(self, tmp_path):
        p = tmp_path / ".doto" / "calsync.json"
        st = CalSyncState(p)
        st.load()
        st.save()
        assert p.exists()

    def test_set_get_delete(self, tmp_path):
        st = CalSyncState(tmp_path / "calsync.json")
        st.load()
        ref = RemoteRef(uid="doto-A@doxtr-doto", content_hash="abc")
        st.set("google", "primary", "A", ref)
        assert st.get("google", "primary", "A") == ref
        assert st.get("google", "primary", "missing") is None
        st.delete("google", "primary", "A")
        assert st.get("google", "primary", "A") is None

    def test_namespacing_isolates_providers(self, tmp_path):
        st = CalSyncState(tmp_path / "calsync.json")
        st.load()
        st.set("google", "primary", "A", RemoteRef(uid="g"))
        st.set("caldav", "work", "A", RemoteRef(uid="c"))
        assert st.get("google", "primary", "A").uid == "g"
        assert st.get("caldav", "work", "A").uid == "c"
        assert st.task_ids("google", "primary") == ["A"]

    def test_persistence_across_instances(self, tmp_path):
        p = tmp_path / "calsync.json"
        st = CalSyncState(p)
        st.load()
        st.set("google", "primary", "A", RemoteRef(uid="x", content_hash="h"))
        st.save()

        st2 = CalSyncState(p)
        st2.load()
        got = st2.get("google", "primary", "A")
        assert got is not None
        assert got.content_hash == "h"

    def test_corrupt_file_recovers_empty(self, tmp_path):
        p = tmp_path / "calsync.json"
        p.write_text("{ not json")
        st = CalSyncState(p)
        st.load()  # must not raise
        assert st.task_ids("google", "primary") == []
