"""Tests for recursive repo discovery, the registry, and namespaced ids."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from doxtr_doto.cli.global_state import GlobalStateStore
from doxtr_doto.cli.main import cli
from doxtr_doto.cli.repo_registry import (
    DiscoveredRepo,
    RepoRegistry,
    _dedupe_name,
    _matches_gitignore,
)


@pytest.fixture
def runner():
    """Create a CLI runner."""
    return CliRunner()


def _make_repo(root: Path, name: str, tasks: dict | None = None) -> Path:
    """Create a doto repo directory with a tasks.json under ``root/name``.

    Args:
        root: Parent directory.
        name: Repository directory name.
        tasks: Optional tasks dict to seed.

    Returns:
        Path to the repository root directory.
    """
    repo = root / name
    store = repo / ".doto" / "tasks.json"
    store.parent.mkdir(parents=True)
    data = {
        "version": 5,
        "updated": "2024-01-01T00:00:00",
        "tasks": tasks or {},
        "series": {},
    }
    store.write_text(json.dumps(data))
    return repo


@pytest.fixture
def global_store(tmp_path):
    """A GlobalStateStore backed by a temp config file."""
    return GlobalStateStore(tmp_path / "config.json")


class TestDiscovery:
    """Tests for RepoRegistry.discover."""

    def test_discovers_nested_repos(self, tmp_path, global_store):
        _make_repo(tmp_path, "alpha")
        _make_repo(tmp_path / "nested", "beta")
        registry = RepoRegistry(global_store)
        found = registry.discover(tmp_path)
        names = {r.name for r in found}
        assert names == {"alpha", "beta"}

    def test_prunes_default_dirs(self, tmp_path, global_store):
        _make_repo(tmp_path, "visible")
        # A repo buried under a pruned directory must not be found.
        _make_repo(tmp_path / "node_modules", "hidden")
        _make_repo(tmp_path / ".git", "ignored")
        registry = RepoRegistry(global_store)
        found = registry.discover(tmp_path)
        assert {r.name for r in found} == {"visible"}

    def test_honors_gitignore(self, tmp_path, global_store):
        _make_repo(tmp_path, "kept")
        (tmp_path / ".gitignore").write_text("skipme/\n")
        _make_repo(tmp_path / "skipme", "gone")
        registry = RepoRegistry(global_store)
        found = registry.discover(tmp_path)
        assert {r.name for r in found} == {"kept"}

    def test_discovers_repo_nested_inside_repo(self, tmp_path, global_store):
        # A doto repo nested inside another doto repo must be discovered too:
        # the walk keeps descending into a repository's children.
        outer = _make_repo(tmp_path, "outer")
        _make_repo(outer, "inner")
        registry = RepoRegistry(global_store)
        found = registry.discover(tmp_path)
        assert {r.name for r in found} == {"outer", "inner"}

    def test_descending_into_repo_still_prunes_default_dirs(self, tmp_path, global_store):
        # Even now that we descend into a repo, nested repos under a pruned
        # directory must still be skipped.
        outer = _make_repo(tmp_path, "outer")
        _make_repo(outer / "node_modules", "hidden")
        _make_repo(outer / ".git", "ignored")
        registry = RepoRegistry(global_store)
        found = registry.discover(tmp_path)
        assert {r.name for r in found} == {"outer"}

    def test_descending_into_repo_still_honors_gitignore(self, tmp_path, global_store):
        # Nested repos under a gitignored directory of a repo stay hidden.
        outer = _make_repo(tmp_path, "outer")
        (outer / ".gitignore").write_text("skipme/\n")
        _make_repo(outer / "skipme", "gone")
        registry = RepoRegistry(global_store)
        found = registry.discover(tmp_path)
        assert {r.name for r in found} == {"outer"}

    def test_dedupes_colliding_names(self, tmp_path, global_store):
        _make_repo(tmp_path / "a", "proj")
        _make_repo(tmp_path / "b", "proj")
        registry = RepoRegistry(global_store)
        found = registry.discover(tmp_path)
        names = sorted(r.name for r in found)
        assert names == ["proj", "proj-2"]

    def test_dedupes_nested_parent_child_name_collision(self, tmp_path, global_store):
        # A repo nested inside a same-named parent exercises the parent/child
        # dedupe path now that discovery descends into a repo's children.
        outer = _make_repo(tmp_path, "proj")
        _make_repo(outer, "proj")
        registry = RepoRegistry(global_store)
        found = registry.discover(tmp_path)
        names = sorted(r.name for r in found)
        assert names == ["proj", "proj-2"]

    def test_does_not_rediscover_own_doto_dir_as_repo(self, tmp_path, global_store):
        # The repo's own .doto/ dir is pruned, so a stray marker buried inside
        # it (``outer/.doto/weird/.doto/tasks.json``) is never a phantom repo.
        outer = _make_repo(tmp_path, "outer")
        phantom = outer / ".doto" / "weird" / ".doto" / "tasks.json"
        phantom.parent.mkdir(parents=True)
        phantom.write_text("{}")
        registry = RepoRegistry(global_store)
        found = registry.discover(tmp_path)
        assert {r.name for r in found} == {"outer"}


class TestRegistryCache:
    """Tests for caching behavior of the registry."""

    def test_rescan_persists(self, tmp_path, global_store):
        _make_repo(tmp_path, "alpha")
        registry = RepoRegistry(global_store)
        registry.rescan(tmp_path)
        # list_repos reads the cache without scanning.
        cached = registry.list_repos()
        assert [r.name for r in cached] == ["alpha"]

    def test_list_repos_empty_when_no_cache(self, global_store):
        registry = RepoRegistry(global_store)
        assert registry.list_repos() == []

    def test_add_and_resolve(self, tmp_path, global_store):
        repo = _make_repo(tmp_path, "alpha")
        registry = RepoRegistry(global_store)
        added = registry.add(repo)
        assert added.name == "alpha"
        assert registry.resolve("alpha").path == str(repo.resolve())

    def test_add_non_repo_raises(self, tmp_path, global_store):
        registry = RepoRegistry(global_store)
        with pytest.raises(ValueError, match="not a doto repository"):
            registry.add(tmp_path)

    def test_add_is_idempotent(self, tmp_path, global_store):
        repo = _make_repo(tmp_path, "alpha")
        registry = RepoRegistry(global_store)
        registry.add(repo)
        registry.add(repo)
        assert len(registry.list_repos()) == 1

    def test_add_dedupes_name(self, tmp_path, global_store):
        a = _make_repo(tmp_path / "a", "proj")
        b = _make_repo(tmp_path / "b", "proj")
        registry = RepoRegistry(global_store)
        registry.add(a)
        second = registry.add(b)
        assert second.name == "proj-2"

    def test_forget(self, tmp_path, global_store):
        repo = _make_repo(tmp_path, "alpha")
        registry = RepoRegistry(global_store)
        registry.add(repo)
        assert registry.forget("alpha") is True
        assert registry.list_repos() == []

    def test_forget_missing(self, global_store):
        registry = RepoRegistry(global_store)
        assert registry.forget("nope") is False

    def test_resolve_missing(self, global_store):
        registry = RepoRegistry(global_store)
        assert registry.resolve("nope") is None


class TestHelpers:
    """Tests for small registry helpers."""

    def test_dedupe_name(self):
        used = {"proj"}
        assert _dedupe_name("proj", used) == "proj-2"
        assert _dedupe_name("other", used) == "other"

    def test_matches_gitignore_basename(self):
        assert _matches_gitignore("build", ["build/"])
        assert _matches_gitignore("thing.egg-info", ["*.egg-info"])
        assert not _matches_gitignore("src", ["build"])

    def test_matches_gitignore_path_anchored(self):
        assert _matches_gitignore("dist", ["foo/dist"])

    def test_discovered_repo_to_dict(self):
        repo = DiscoveredRepo(name="x", path="/tmp/x")
        assert repo.to_dict() == {"name": "x", "path": "/tmp/x"}


class TestReposCLI:
    """Tests for the 'doto repos' command group."""

    @pytest.fixture
    def env(self, tmp_path, monkeypatch):
        """Isolate global config and home under temp dirs.

        ``DOTO_CONFIG`` is pinned to an isolated per-test path. It is the
        highest-priority entry in the global-config resolution order, so it
        overrides both the cwd-walk portable lookup (which would otherwise
        find the real repo's ``.doto/config.json`` relative to the test's
        cwd) and the XDG fallback. Without this, every ``doto repos`` CLI
        invocation here reads/writes the shared real-repo config, leaking
        registry state across tests (e.g. ``repos list`` showing repos cached
        by an earlier test), which is the order-dependent in-suite failure.
        """
        cfg = tmp_path / "xdg"
        monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
        monkeypatch.setenv("DOTO_CONFIG", str(tmp_path / "global-config.json"))
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
        return cfg

    def test_repos_list_empty(self, runner, tmp_path, env):
        store = _make_repo(tmp_path, "alpha") / ".doto" / "tasks.json"
        result = runner.invoke(cli, ["--json", str(store), "repos"])
        assert result.exit_code == 0
        assert "No repositories cached" in result.output

    def test_repos_rescan_then_list(self, runner, tmp_path, env, monkeypatch):
        store = _make_repo(tmp_path, "alpha") / ".doto" / "tasks.json"
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(cli, ["--json", str(store), "repos", "rescan"])
        assert result.exit_code == 0
        assert "Discovered 1 repository" in result.output

        listed = runner.invoke(cli, ["--json", str(store), "repos", "list"])
        assert "alpha" in listed.output

    def test_repos_rescan_json(self, runner, tmp_path, env):
        store = _make_repo(tmp_path, "alpha") / ".doto" / "tasks.json"
        result = runner.invoke(
            cli,
            ["--json", str(store), "repos", "rescan", str(tmp_path), "--json"],
        )
        payload = json.loads(result.output)
        assert payload["repositories"][0]["name"] == "alpha"

    def test_repos_add_and_forget(self, runner, tmp_path, env):
        repo = _make_repo(tmp_path, "alpha")
        store = repo / ".doto" / "tasks.json"
        add = runner.invoke(cli, ["--json", str(store), "repos", "add", str(repo)])
        assert "Added alpha" in add.output

        forget = runner.invoke(cli, ["--json", str(store), "repos", "forget", "alpha"])
        assert "Forgot repository 'alpha'" in forget.output

    def test_repos_add_non_repo_errors(self, runner, tmp_path, env):
        repo = _make_repo(tmp_path, "alpha")
        store = repo / ".doto" / "tasks.json"
        bad = tmp_path / "notarepo"
        bad.mkdir()
        result = runner.invoke(cli, ["--json", str(store), "repos", "add", str(bad)])
        assert result.exit_code != 0
        assert "not a doto repository" in result.output

    def test_repos_forget_missing_warns(self, runner, tmp_path, env):
        store = _make_repo(tmp_path, "alpha") / ".doto" / "tasks.json"
        result = runner.invoke(cli, ["--json", str(store), "repos", "forget", "ghost"])
        assert "No cached repository" in result.output
