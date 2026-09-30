"""Tests for CLI init command - project initialization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from doxtr_doto.cli.main import cli


@pytest.fixture
def runner():
    """CLI test runner."""
    return CliRunner()


class TestInitCommand:
    """Tests for doto init command."""

    def test_init_creates_config_file(self, runner: CliRunner, tmp_path: Path):
        """Init creates .doto.toml config file."""
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["init"])
            
            assert result.exit_code == 0
            assert Path(".doto.toml").exists()
            
            content = Path(".doto.toml").read_text()
            assert "[doto]" in content
            assert "json_file" in content

    def test_init_creates_doto_directory(self, runner: CliRunner, tmp_path: Path):
        """Init creates .doto directory."""
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["init"])
            
            assert result.exit_code == 0
            assert Path(".doto").is_dir()

    def test_init_creates_json_store(self, runner: CliRunner, tmp_path: Path):
        """Init creates tasks.json file."""
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["init"])
            
            assert result.exit_code == 0
            json_path = Path(".doto/tasks.json")
            assert json_path.exists()
            
            data = json.loads(json_path.read_text())
            assert "version" in data
            assert "tasks" in data

    def test_init_creates_inbox_file(self, runner: CliRunner, tmp_path: Path):
        """Init creates inbox.rst file."""
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["init"])
            
            assert result.exit_code == 0
            inbox_path = Path("tasks/inbox.rst")
            assert inbox_path.exists()
            
            content = inbox_path.read_text()
            assert "Task Inbox" in content

    def test_init_custom_inbox_file(self, runner: CliRunner, tmp_path: Path):
        """Init creates inbox at custom location."""
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["init", "--inbox", "custom/tasks.rst"])
            
            assert result.exit_code == 0
            assert Path("custom/tasks.rst").exists()

    def test_init_fails_if_config_exists(self, runner: CliRunner, tmp_path: Path):
        """Init fails if .doto.toml already exists."""
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path(".doto.toml").write_text("[doto]\n")
            
            result = runner.invoke(cli, ["init"])
            
            assert result.exit_code != 0
            assert "already exists" in result.output

    def test_init_force_overwrites(self, runner: CliRunner, tmp_path: Path):
        """Init --force overwrites existing files."""
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path(".doto.toml").write_text("old content")
            
            result = runner.invoke(cli, ["init", "--force"])
            
            assert result.exit_code == 0
            content = Path(".doto.toml").read_text()
            assert "[doto]" in content
            assert "old content" not in content

    def test_init_standalone_mode(self, runner: CliRunner, tmp_path: Path, monkeypatch):
        """Init --standalone creates config in ~/.doto/."""
        # Use tmp_path as home directory
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        
        # Need to also patch Path.home() since it might cache the value
        monkeypatch.setattr(Path, "home", lambda: fake_home)
        
        result = runner.invoke(cli, ["init", "--standalone"])
        
        assert result.exit_code == 0
        config_path = fake_home / ".doto" / "config.toml"
        assert config_path.exists()
        
        content = config_path.read_text()
        assert "[doto]" in content

    def test_init_standalone_creates_json_store(self, runner: CliRunner, tmp_path: Path, monkeypatch):
        """Init --standalone creates tasks.json in ~/.doto/."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)
        
        result = runner.invoke(cli, ["init", "--standalone"])
        
        assert result.exit_code == 0
        json_path = fake_home / ".doto" / "tasks.json"
        assert json_path.exists()

    def test_init_standalone_fails_if_exists(self, runner: CliRunner, tmp_path: Path, monkeypatch):
        """Init --standalone fails if config already exists."""
        fake_home = tmp_path / "home"
        doto_dir = fake_home / ".doto"
        doto_dir.mkdir(parents=True)
        (doto_dir / "config.toml").write_text("[doto]\n")
        monkeypatch.setattr(Path, "home", lambda: fake_home)
        
        result = runner.invoke(cli, ["init", "--standalone"])
        
        assert result.exit_code != 0
        assert "already exists" in result.output

    def test_init_standalone_force_overwrites(self, runner: CliRunner, tmp_path: Path, monkeypatch):
        """Init --standalone --force overwrites existing config."""
        fake_home = tmp_path / "home"
        doto_dir = fake_home / ".doto"
        doto_dir.mkdir(parents=True)
        (doto_dir / "config.toml").write_text("old")
        monkeypatch.setattr(Path, "home", lambda: fake_home)
        
        result = runner.invoke(cli, ["init", "--standalone", "--force"])
        
        assert result.exit_code == 0
        content = (doto_dir / "config.toml").read_text()
        assert "[doto]" in content

    def test_init_with_source_dir(self, runner: CliRunner, tmp_path: Path):
        """Init with --source creates config in specified directory."""
        with runner.isolated_filesystem(temp_dir=tmp_path):
            source_dir = Path("docs")
            source_dir.mkdir()
            
            result = runner.invoke(cli, ["init", "--source", "docs"])
            
            assert result.exit_code == 0
            assert (source_dir / ".doto.toml").exists()

    def test_init_shows_completion_hint(self, runner: CliRunner, tmp_path: Path):
        """Init shows tab completion hint."""
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["init"])
            
            assert result.exit_code == 0
            assert "completion" in result.output

    def test_init_detects_conf_py(self, runner: CliRunner, tmp_path: Path):
        """Init detects existing conf.py and shows hint."""
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path("conf.py").write_text("# Sphinx config\n")
            
            result = runner.invoke(cli, ["init"])
            
            assert result.exit_code == 0
            assert "conf.py" in result.output
            assert "extensions" in result.output

    def test_init_detects_conf_py_in_subdirs(self, runner: CliRunner, tmp_path: Path):
        """Init detects conf.py in common subdirectories."""
        with runner.isolated_filesystem(temp_dir=tmp_path):
            docs_dir = Path("docs/source")
            docs_dir.mkdir(parents=True)
            (docs_dir / "conf.py").write_text("# Sphinx config\n")
            
            result = runner.invoke(cli, ["init"])
            
            assert result.exit_code == 0
            assert "conf.py" in result.output
