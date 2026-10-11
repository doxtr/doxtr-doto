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
