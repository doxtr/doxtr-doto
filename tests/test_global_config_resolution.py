"""Tests for portable global config resolution and break config storage."""

from __future__ import annotations

from pathlib import Path

import pytest

from doxtr_doto.cli.global_state import (
    BreakConfig,
    GlobalState,
    GlobalStateStore,
    resolve_global_config_path,
    resolve_global_config_write_path,
)


class TestStateFileConfig:
    """The ``state_file`` config key / ``DOTO_STATE_FILE`` env for a private clock."""

    def test_unset_returns_none(self):
        from doxtr_doto.cli.config import DotoConfig

        assert DotoConfig().get_state_path() is None

    def test_absolute_path_used_verbatim(self, tmp_path):
        from doxtr_doto.cli.config import DotoConfig

        cfg = DotoConfig(source_dir=tmp_path)
        cfg.state_file = str(tmp_path / "me" / "state.json")
        assert cfg.get_state_path() == tmp_path / "me" / "state.json"

    def test_relative_path_anchored_to_source_dir(self, tmp_path):
        from doxtr_doto.cli.config import DotoConfig

        cfg = DotoConfig(source_dir=tmp_path)
        cfg.state_file = "mine/.doto/state.json"
        assert cfg.get_state_path() == tmp_path / "mine" / ".doto" / "state.json"

    def test_tilde_and_env_expansion(self, monkeypatch, tmp_path):
        from doxtr_doto.cli.config import DotoConfig

        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.setenv("PRIV_DIR", str(tmp_path / "priv"))
        cfg = DotoConfig(source_dir=tmp_path)
        cfg.state_file = "~/state.json"
        assert cfg.get_state_path() == tmp_path / "home" / "state.json"
        cfg.state_file = "${PRIV_DIR}/state.json"
        assert cfg.get_state_path() == tmp_path / "priv" / "state.json"

    def test_toml_state_table_and_doto_key(self, tmp_path):
        from doxtr_doto.cli.config import DotoConfig, _apply_state_config, _apply_toml_config

        cfg = DotoConfig()
        _apply_toml_config(cfg, {"state_file": "a/state.json"})
        assert cfg.state_file == "a/state.json"
        cfg2 = DotoConfig()
        _apply_state_config(cfg2, {"file": "b/state.json"})
        assert cfg2.state_file == "b/state.json"

    def test_state_table_file_beats_state_file_key(self):
        from doxtr_doto.cli.config import DotoConfig, _apply_state_config

        cfg = DotoConfig()
        _apply_state_config(cfg, {"file": "a.json", "state_file": "b.json"})
        assert cfg.state_file == "a.json"

    def test_state_table_empty_value_ignored(self):
        from doxtr_doto.cli.config import DotoConfig, _apply_state_config

        cfg = DotoConfig()
        cfg.state_file = "keep.json"
        _apply_state_config(cfg, {"file": ""})
        assert cfg.state_file == "keep.json"

    def test_doto_state_file_env_sets_state_file(self, monkeypatch, tmp_path):
        from doxtr_doto.cli.config import DotoConfig, _apply_env_config

        monkeypatch.setenv("DOTO_STATE_FILE", str(tmp_path / "env-state.json"))
        cfg = DotoConfig(source_dir=tmp_path)
        _apply_env_config(cfg)
        assert cfg.get_state_path() == tmp_path / "env-state.json"

    def test_unset_env_var_not_baked_in_at_load(self):
        # _apply_state_config stores the raw value; expansion is deferred to
        # get_state_path, so an unset ${VAR} is not frozen to "" at load time.
        from doxtr_doto.cli.config import DotoConfig, _apply_state_config

        cfg = DotoConfig()
        _apply_state_config(cfg, {"file": "${DOTO_TEST_UNSET_VAR}/x.json"})
        assert cfg.state_file == "${DOTO_TEST_UNSET_VAR}/x.json"


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path):
    """Isolate HOME/XDG/DOTO_CONFIG so tests do not touch the real config."""
    monkeypatch.delenv("DOTO_CONFIG", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    yield


def test_env_var_wins(monkeypatch, tmp_path):
    target = tmp_path / "custom" / "config.json"
    monkeypatch.setenv("DOTO_CONFIG", str(target))
    assert resolve_global_config_path(tmp_path) == target
    assert resolve_global_config_write_path(tmp_path) == target


def test_portable_config_found_by_walking_up(monkeypatch, tmp_path):
    project = tmp_path / "workspaces" / "docs"
    (project / ".doto").mkdir(parents=True)
    cfg = project / ".doto" / "config.json"
    cfg.write_text("{}")
    sub = project / "a" / "b"
    sub.mkdir(parents=True)
    assert resolve_global_config_path(sub) == cfg


def test_falls_back_to_xdg(monkeypatch, tmp_path):
    resolved = resolve_global_config_path(tmp_path)
    assert resolved == tmp_path / "xdg" / "doto" / "config.json"


def test_config_override_beats_portable_and_xdg(tmp_path):
    """A configured private state path wins over the portable/XDG fallbacks."""
    # A portable config exists in the shared tree ...
    project = tmp_path / "shared"
    (project / ".doto").mkdir(parents=True)
    (project / ".doto" / "config.json").write_text("{}")
    # ... but the user configured a private location.
    private = tmp_path / "me" / "state.json"
    assert resolve_global_config_path(project, config_override=private) == private
    # Write target honours it too, so a first-run save lands privately.
    assert resolve_global_config_write_path(project, config_override=private) == private


def test_env_var_still_wins_over_config_override(monkeypatch, tmp_path):
    """$DOTO_CONFIG has higher precedence than the configured state path."""
    env_target = tmp_path / "env" / "config.json"
    monkeypatch.setenv("DOTO_CONFIG", str(env_target))
    private = tmp_path / "me" / "state.json"
    assert resolve_global_config_path(tmp_path, config_override=private) == env_target
    assert resolve_global_config_write_path(tmp_path, config_override=private) == env_target


def test_store_writes_work_clock_to_private_override(tmp_path):
    """The work clock is persisted to the configured private path only."""
    from doxtr_doto.time_tracking import start_session

    shared = tmp_path / "shared"
    (shared / ".doto").mkdir(parents=True)
    private = tmp_path / "me" / "private-state.json"

    store = GlobalStateStore(config_override=private)
    assert store.path == private
    state = store.load()
    state.work_clock.worklogs = start_session(state.work_clock.worklogs)
    store.save(state)

    assert private.exists()
    # The shared tree never receives the work clock.
    assert not (shared / ".doto" / "config.json").exists()
    reloaded = GlobalStateStore(config_override=private).load()
    assert len(reloaded.work_clock.worklogs) == 1


def test_relative_state_file_lands_inside_project_tree(tmp_path):
    """A relative ``state_file`` is anchored to source_dir (the "not private"
    footgun), so the state file is created inside the project tree.

    This is the behavioral counterpart to the private-override test: it
    documents that a relative path does NOT escape the shared tree, so users
    understand they must use ``~`` or an absolute path for privacy.
    """
    from doxtr_doto.cli.config import DotoConfig
    from doxtr_doto.time_tracking import start_session

    project = tmp_path / "project"
    project.mkdir()
    cfg = DotoConfig(source_dir=project)
    cfg.state_file = ".doto/state.json"
    resolved = cfg.get_state_path()
    assert resolved == project / ".doto" / "state.json"

    store = GlobalStateStore(config_override=resolved)
    state = store.load()
    state.work_clock.worklogs = start_session(state.work_clock.worklogs)
    store.save(state)
    assert (project / ".doto" / "state.json").exists()


def test_load_config_env_state_file_wins_over_toml(monkeypatch, tmp_path):
    """End-to-end: DOTO_STATE_FILE overrides a .doto.toml state_file.

    load_config applies TOML before env, so the env value wins -- the contract
    the README states ("DOTO_STATE_FILE ... overrides state_file").
    """
    from doxtr_doto.cli.config import load_config

    project = tmp_path / "proj"
    project.mkdir()
    (project / ".doto.toml").write_text('[doto]\nstate_file = "toml-state.json"\n')
    monkeypatch.chdir(project)
    monkeypatch.setenv("DOTO_STATE_FILE", str(tmp_path / "env-state.json"))
    cfg = load_config()
    assert cfg.get_state_path() == tmp_path / "env-state.json"


def test_write_path_anchors_to_project_root(monkeypatch, tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".doto.toml").write_text("")  # marks project root
    sub = project / "src"
    sub.mkdir()
    assert resolve_global_config_write_path(sub) == project / ".doto" / "config.json"


def test_write_path_reuses_existing_portable(monkeypatch, tmp_path):
    project = tmp_path / "proj"
    (project / ".doto").mkdir(parents=True)
    cfg = project / ".doto" / "config.json"
    cfg.write_text("{}")
    assert resolve_global_config_write_path(project) == cfg


def test_write_path_falls_back_to_xdg_without_project(monkeypatch, tmp_path):
    lonely = tmp_path / "nowhere"
    lonely.mkdir()
    assert resolve_global_config_write_path(lonely) == tmp_path / "xdg" / "doto" / "config.json"


def test_break_config_round_trip():
    b = BreakConfig(name="Lunch", time="12:00", duration_minutes=60, leeway_minutes=30)
    assert BreakConfig.from_dict(b.to_dict()) == b


def test_break_config_auto_deduct_round_trip():
    b = BreakConfig(
        name="Lunch", time="12:00", duration_minutes=60, leeway_minutes=30, auto_deduct=True
    )
    restored = BreakConfig.from_dict(b.to_dict())
    assert restored == b
    assert restored.auto_deduct is True


def test_break_config_auto_deduct_defaults_false_for_old_data():
    # An older config file that predates auto_deduct loads it as False, so
    # existing data never double-counts under the new recorded-break default.
    b = BreakConfig.from_dict({"name": "Lunch", "time": "12:00", "duration_minutes": 60})
    assert b.auto_deduct is False


def test_break_config_preserves_unknown_keys_round_trip():
    # A newer version's extra per-break field survives a load/save round-trip
    # (forward compat) instead of being silently dropped, mirroring the
    # top-level GlobalState._extra behavior.
    b = BreakConfig.from_dict(
        {
            "name": "Lunch",
            "time": "12:00",
            "duration_minutes": 60,
            "leeway_minutes": 30,
            "auto_deduct": True,
            "paid": True,
            "break_kind": "meal",
        }
    )
    assert b._extra == {"paid": True, "break_kind": "meal"}
    dumped = b.to_dict()
    assert dumped["paid"] is True
    assert dumped["break_kind"] == "meal"
    assert dumped["auto_deduct"] is True
    assert BreakConfig.from_dict(dumped) == b


def test_break_default_leeway():
    b = BreakConfig.from_dict({"name": "Tea", "time": "15:00", "duration_minutes": 15})
    assert b.leeway_minutes == 30


def test_global_state_breaks_persist(tmp_path):
    path = tmp_path / "config.json"
    store = GlobalStateStore(path)
    state = GlobalState()
    state.breaks = [
        BreakConfig("Breakfast", "08:00", 20, 15),
        BreakConfig("Lunch", "12:00", 60, 30),
    ]
    store.save(state)
    reloaded = store.load()
    assert reloaded.breaks == state.breaks


def test_unknown_keys_round_trip(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"version": 1, "future_key": {"x": 1}, "breaks": []}')
    store = GlobalStateStore(path)
    state = store.load()
    store.save(state)
    import json

    data = json.loads(Path(path).read_text())
    assert data["future_key"] == {"x": 1}
