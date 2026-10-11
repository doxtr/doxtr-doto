"""Tests for the OAuth token cache (auth.py)."""

from __future__ import annotations

import os
import stat

from doxtr_doto.calsync import auth


def _isolate(monkeypatch, tmp_path):
    """Point the token dir at a temp config via XDG_CONFIG_HOME."""
    monkeypatch.delenv(auth.CONFIG_ENV_VAR, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))


class TestTokenCache:
    def test_save_load_round_trip(self, monkeypatch, tmp_path):
        _isolate(monkeypatch, tmp_path)
        auth.save_token("google", {"refresh_token": "abc", "token": "xyz"})
        loaded = auth.load_token("google")
        assert loaded == {"refresh_token": "abc", "token": "xyz"}

    def test_missing_token_is_none(self, monkeypatch, tmp_path):
        _isolate(monkeypatch, tmp_path)
        assert auth.load_token("microsoft") is None

    def test_clear_token(self, monkeypatch, tmp_path):
        _isolate(monkeypatch, tmp_path)
        auth.save_token("google", {"token": "x"})
        assert auth.clear_token("google") is True
        assert auth.clear_token("google") is False
        assert auth.load_token("google") is None

    def test_corrupt_token_is_none(self, monkeypatch, tmp_path):
        _isolate(monkeypatch, tmp_path)
        path = auth.token_path("google")
        path.write_text("{ broken")
        assert auth.load_token("google") is None

    def test_token_file_permissions(self, monkeypatch, tmp_path):
        _isolate(monkeypatch, tmp_path)
        auth.save_token("google", {"token": "x"})
        mode = stat.S_IMODE(os.stat(auth.token_path("google")).st_mode)
        # 0600 on POSIX; skip the strict check on platforms without chmod.
        if os.name == "posix":
            assert mode == 0o600

    def test_env_var_override(self, monkeypatch, tmp_path):
        cfg = tmp_path / "custom" / "config.json"
        cfg.parent.mkdir(parents=True)
        monkeypatch.setenv(auth.CONFIG_ENV_VAR, str(cfg))
        auth.save_token("google", {"token": "x"})
        # Token dir should live next to the configured config file.
        assert auth.token_path("google").is_relative_to(tmp_path / "custom")
