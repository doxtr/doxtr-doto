"""Tests for the global cross-repo state store."""

from __future__ import annotations

from pathlib import Path

from doxtr_doto.cli.global_state import (
    GLOBAL_STATE_VERSION,
    GlobalState,
    GlobalStateStore,
    WorkClock,
    default_config_path,
)


class TestDefaultConfigPath:
    """Tests for default_config_path."""

    def test_respects_xdg_config_home(self, tmp_path, monkeypatch):
        # Isolate the resolver from the real environment: clear the
        # $DOTO_CONFIG override and chdir into a clean tmp dir so the
        # portable walk-up does not find the real repo's .doto/config.json.
        monkeypatch.delenv("DOTO_CONFIG", raising=False)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        path = default_config_path()
        assert path == tmp_path / "doto" / "config.json"

    def test_falls_back_to_home_config(self, tmp_path, monkeypatch):
        # Isolate from $DOTO_CONFIG and cwd for the same reason as above.
        monkeypatch.delenv("DOTO_CONFIG", raising=False)
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        path = default_config_path()
        assert path == tmp_path / ".config" / "doto" / "config.json"


class TestWorkClock:
    """Tests for the WorkClock dataclass."""

    def test_default_empty(self):
        clock = WorkClock()
        assert clock.worklogs == []

    def test_to_from_dict_roundtrip(self):
        logs = [{"started_at": "2024-01-01T09:00:00+00:00", "stopped_at": None}]
        clock = WorkClock(worklogs=logs)
        data = clock.to_dict()
        assert data == {"worklogs": logs}
        rebuilt = WorkClock.from_dict(data)
        assert rebuilt.worklogs == logs

    def test_from_dict_none(self):
        assert WorkClock.from_dict(None).worklogs == []


class TestGlobalState:
    """Tests for the GlobalState dataclass."""

    def test_defaults(self):
        state = GlobalState()
        assert state.version == GLOBAL_STATE_VERSION
        assert state.repositories == []
        assert state.favorites == []
        assert state.active_session is None
        assert state.work_clock.worklogs == []
        assert state.last_prompt_date is None
        assert state.workweek_days == [0, 1, 2, 3, 4]
        # Filter/sort memory fields default to "unset" (Feature C).
        assert state.tui_hide_completed is False
        assert state.tui_due_filter is None
        assert state.tui_tag_filter is None
        assert state.tui_priority_filter is None
        assert state.tui_sort_key is None
        assert state.tui_sort_order is None
        assert state.tui_repo_filter is None
        assert state.tui_recent_done_enabled is None
        assert state.tui_recent_done_days is None
        assert state.tui_detail_ratio is None
        assert state.tui_modal_width_ratio is None

    def test_to_dict_shape(self):
        state = GlobalState()
        data = state.to_dict()
        assert set(data.keys()) == {
            "version",
            "repositories",
            "favorites",
            "active_session",
            "work_clock",
            "breaks",
            "workweek_days",
            "last_prompt_date",
            "tui_layout",
            "tui_hide_completed",
            "tui_conflicts_only",
            "tui_due_filter",
            "tui_tag_filter",
            "tui_priority_filter",
            "tui_sort_key",
            "tui_sort_order",
            "tui_repo_filter",
            "tui_recent_done_enabled",
            "tui_recent_done_days",
            "tui_detail_ratio",
            "tui_modal_width_ratio",
        }
        assert data["work_clock"] == {"worklogs": []}
        assert data["breaks"] == []
        assert data["workweek_days"] == [0, 1, 2, 3, 4]

    def test_from_dict_full(self):
        data = {
            "version": 1,
            "repositories": [{"name": "web", "path": "/x/web"}],
            "favorites": ["web#1"],
            "active_session": {"repo": "web", "task_id": "1"},
            "work_clock": {
                "worklogs": [{"started_at": "2024-01-01T09:00:00+00:00", "stopped_at": None}]
            },
            "last_prompt_date": "2024-01-01",
        }
        state = GlobalState.from_dict(data)
        assert state.repositories == [{"name": "web", "path": "/x/web"}]
        assert state.favorites == ["web#1"]
        assert state.active_session == {"repo": "web", "task_id": "1"}
        assert state.last_prompt_date == "2024-01-01"
        assert len(state.work_clock.worklogs) == 1

    def test_from_dict_missing_keys_use_defaults(self):
        state = GlobalState.from_dict({})
        assert state.version == GLOBAL_STATE_VERSION
        assert state.repositories == []
        assert state.last_prompt_date is None
        # Missing workweek_days falls back to the Monday-Friday default.
        assert state.workweek_days == [0, 1, 2, 3, 4]

    def test_workweek_days_round_trip(self):
        state = GlobalState(workweek_days=[0, 2, 4])
        data = state.to_dict()
        assert data["workweek_days"] == [0, 2, 4]
        rebuilt = GlobalState.from_dict(data)
        assert rebuilt.workweek_days == [0, 2, 4]

    def test_view_pref_fields_round_trip(self):
        # Feature C sort memory: the filter/sort preference fields survive a
        # to_dict/from_dict round-trip.
        state = GlobalState(
            tui_hide_completed=True,
            tui_due_filter="week",
            tui_tag_filter="frontend",
            tui_priority_filter="high",
            tui_sort_key="priority",
            tui_sort_order="desc",
            tui_repo_filter=["web", "api"],
        )
        data = state.to_dict()
        assert data["tui_hide_completed"] is True
        assert data["tui_due_filter"] == "week"
        assert data["tui_sort_key"] == "priority"
        assert data["tui_repo_filter"] == ["web", "api"]
        rebuilt = GlobalState.from_dict(data)
        assert rebuilt.tui_hide_completed is True
        assert rebuilt.tui_due_filter == "week"
        assert rebuilt.tui_tag_filter == "frontend"
        assert rebuilt.tui_priority_filter == "high"
        assert rebuilt.tui_sort_key == "priority"
        assert rebuilt.tui_sort_order == "desc"
        assert rebuilt.tui_repo_filter == ["web", "api"]

    def test_recent_done_fields_round_trip(self):
        # The recent-done filter's on/off state and N-day window survive a
        # to_dict/from_dict round-trip.
        state = GlobalState(
            tui_recent_done_enabled=True,
            tui_recent_done_days=30,
        )
        data = state.to_dict()
        assert data["tui_recent_done_enabled"] is True
        assert data["tui_recent_done_days"] == 30
        rebuilt = GlobalState.from_dict(data)
        assert rebuilt.tui_recent_done_enabled is True
        assert rebuilt.tui_recent_done_days == 30

    def test_recent_done_disabled_state_round_trip(self):
        # Explicitly-disabled (enabled=False) persists distinctly from "unset".
        state = GlobalState(tui_recent_done_enabled=False, tui_recent_done_days=10)
        rebuilt = GlobalState.from_dict(state.to_dict())
        assert rebuilt.tui_recent_done_enabled is False
        assert rebuilt.tui_recent_done_days == 10

    def test_detail_ratio_round_trip(self):
        # The table-layout detail-pane ratio survives a to_dict/from_dict
        # round-trip; None means no saved preference.
        state = GlobalState(tui_detail_ratio="5/8")
        data = state.to_dict()
        assert data["tui_detail_ratio"] == "5/8"
        assert GlobalState.from_dict(data).tui_detail_ratio == "5/8"
        assert GlobalState.from_dict({}).tui_detail_ratio is None

    def test_modal_width_ratio_round_trip(self):
        # The edit/note pop-up width ratio survives a to_dict/from_dict
        # round-trip; None means no saved preference.
        state = GlobalState(tui_modal_width_ratio="1/2")
        data = state.to_dict()
        assert data["tui_modal_width_ratio"] == "1/2"
        assert GlobalState.from_dict(data).tui_modal_width_ratio == "1/2"
        assert GlobalState.from_dict({}).tui_modal_width_ratio is None

    def test_repo_filter_round_trip(self):
        # The repo filter is persisted as a list of repository names and
        # survives a to_dict/from_dict round-trip; None means no filter.
        state = GlobalState(tui_repo_filter=["web", "api"])
        data = state.to_dict()
        assert data["tui_repo_filter"] == ["web", "api"]
        assert GlobalState.from_dict(data).tui_repo_filter == ["web", "api"]
        # Missing / absent repo filter stays None.
        assert GlobalState.from_dict({}).tui_repo_filter is None

    def test_view_pref_fields_missing_use_defaults(self):
        # Older state files that predate Feature C load the fields as unset.
        state = GlobalState.from_dict({})
        assert state.tui_hide_completed is False
        assert state.tui_due_filter is None
        assert state.tui_sort_key is None
        assert state.tui_repo_filter is None

    def test_workweek_days_sanitized_dedupe_sort(self):
        state = GlobalState.from_dict({"workweek_days": [4, 0, 2, 2, 0]})
        assert state.workweek_days == [0, 2, 4]

    def test_workweek_days_sanitized_drops_out_of_range_and_non_ints(self):
        state = GlobalState.from_dict({"workweek_days": [0, 7, -1, 3, "x", 2.5, True]})
        assert state.workweek_days == [0, 3]

    def test_workweek_days_empty_falls_back_to_default(self):
        assert GlobalState.from_dict({"workweek_days": []}).workweek_days == [0, 1, 2, 3, 4]

    def test_workweek_days_invalid_type_falls_back_to_default(self):
        assert GlobalState.from_dict({"workweek_days": "mon"}).workweek_days == [0, 1, 2, 3, 4]

    def test_workweek_days_all_invalid_falls_back_to_default(self):
        assert GlobalState.from_dict({"workweek_days": [7, 8, -1]}).workweek_days == [
            0,
            1,
            2,
            3,
            4,
        ]


class TestGlobalStateStore:
    """Tests for load/save behavior."""

    def test_load_missing_file_returns_default(self, tmp_path):
        store = GlobalStateStore(tmp_path / "doto" / "config.json")
        state = store.load()
        assert isinstance(state, GlobalState)
        assert state.repositories == []
        # Loading does not create the file
        assert not store.path.exists()

    def test_save_then_load_roundtrip(self, tmp_path):
        path = tmp_path / "doto" / "config.json"
        store = GlobalStateStore(path)
        state = GlobalState(
            favorites=["web#1"],
            last_prompt_date="2024-01-02",
        )
        state.work_clock.worklogs.append(
            {"started_at": "2024-01-02T08:00:00+00:00", "stopped_at": None}
        )
        store.save(state)
        assert path.exists()

        reloaded = GlobalStateStore(path).load()
        assert reloaded.favorites == ["web#1"]
        assert reloaded.last_prompt_date == "2024-01-02"
        assert len(reloaded.work_clock.worklogs) == 1

    def test_save_then_load_workweek_days_round_trip(self, tmp_path):
        path = tmp_path / "doto" / "config.json"
        store = GlobalStateStore(path)
        store.save(GlobalState(workweek_days=[0, 1, 2, 3, 4, 5]))
        reloaded = GlobalStateStore(path).load()
        assert reloaded.workweek_days == [0, 1, 2, 3, 4, 5]

    def test_save_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "nested" / "deeper" / "config.json"
        store = GlobalStateStore(path)
        store.save(GlobalState())
        assert path.exists()

    def test_save_is_atomic_no_tmp_left(self, tmp_path):
        path = tmp_path / "config.json"
        store = GlobalStateStore(path)
        store.save(GlobalState())
        tmp = path.with_suffix(path.suffix + ".tmp")
        assert not tmp.exists()

    def test_unknown_top_level_key_round_trips(self, tmp_path):
        # Forward compatibility: a newer version's or plugin's extra top-level
        # config key must survive a load/save/reload cycle rather than being
        # silently dropped.
        import json

        path = tmp_path / "doto" / "config.json"
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    "version": GLOBAL_STATE_VERSION,
                    "favorites": ["web#1"],
                    "future_feature": {"enabled": True, "level": 3},
                }
            )
        )

        store = GlobalStateStore(path)
        state = store.load()
        # Save it straight back out (as any mutation would).
        store.save(state)

        reloaded_raw = json.loads(path.read_text())
        assert reloaded_raw["future_feature"] == {"enabled": True, "level": 3}
        # And the typed reload still exposes the known fields.
        reloaded = GlobalStateStore(path).load()
        assert reloaded.favorites == ["web#1"]
        assert reloaded._extra["future_feature"] == {"enabled": True, "level": 3}

    def test_load_corrupt_file_returns_default(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text("{ not valid json")
        state = GlobalStateStore(path).load()
        assert isinstance(state, GlobalState)
        assert state.repositories == []

    def test_load_non_dict_returns_default(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text("[1, 2, 3]")
        state = GlobalStateStore(path).load()
        assert state.repositories == []

    def test_default_path_used_when_none(self, tmp_path, monkeypatch):
        # Isolate from $DOTO_CONFIG and cwd so the resolver uses the XDG path
        # rather than the real repo's portable .doto/config.json.
        monkeypatch.delenv("DOTO_CONFIG", raising=False)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        store = GlobalStateStore()
        assert store.path == tmp_path / "doto" / "config.json"
