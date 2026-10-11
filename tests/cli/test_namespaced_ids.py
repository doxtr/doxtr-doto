"""Tests for namespaced id resolution and context-aware display."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from doxtr_doto.cli.display import (
    DisplayScope,
    _should_namespace,
    apply_scope,
    namespaced,
    tag_repo,
)
from doxtr_doto.cli.id_resolver import base_id, resolve_task_ref, split_task_ref
from doxtr_doto.cli.main import cli


@pytest.fixture
def runner():
    """Create a CLI runner."""
    return CliRunner()


def _make_repo(root: Path, name: str, tasks: dict) -> Path:
    """Create a doto repo with seeded tasks; returns the repo root."""
    repo = root / name
    store = repo / ".doto" / "tasks.json"
    store.parent.mkdir(parents=True)
    store.write_text(
        json.dumps(
            {
                "version": 5,
                "updated": "2024-01-01T00:00:00",
                "tasks": tasks,
                "series": {},
            }
        )
    )
    return repo


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Isolate global config and home under temp dirs.

    ``DOTO_CONFIG`` is pinned to an isolated per-test path. It is the
    highest-priority entry in the global-config resolution order, so it
    overrides both the cwd-walk portable lookup (which would otherwise find
    the real repo's ``.doto/config.json`` relative to the test's cwd) and the
    XDG fallback. Without this, every CLI invocation in these tests would
    read/write the shared real-repo config and leak repo-registry state across
    tests (the registry entries added by one test would be visible to the
    next), which is the order-dependent in-suite failure.
    """
    cfg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    monkeypatch.setenv("DOTO_CONFIG", str(tmp_path / "global-config.json"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    return cfg


class TestSplitTaskRef:
    """Tests for split_task_ref."""

    def test_bare_id(self):
        assert split_task_ref("T-001") == (None, "T-001")

    def test_namespaced(self):
        assert split_task_ref("web-app#14") == ("web-app", "14")

    def test_empty_repo_treated_as_bare(self):
        assert split_task_ref("#14") == (None, "14")


class TestDisplayScope:
    """Tests for the context-aware display helpers."""

    def test_namespaced(self):
        assert namespaced("web", "14") == "web#14"

    def test_tag_repo_records_local_id(self):
        tasks = [{"id": "T-1"}]
        tag_repo(tasks, "web")
        assert tasks[0]["_repo"] == "web"
        assert tasks[0]["_local_id"] == "T-1"

    def test_apply_scope_local_leaves_ids(self):
        tasks = tag_repo([{"id": "T-1"}], "web")
        apply_scope(tasks, DisplayScope.LOCAL)
        assert tasks[0]["id"] == "T-1"

    def test_apply_scope_global_unique_base_stays_short(self):
        # A base prefix used by only one repo in the view keeps its bare id.
        tasks = tag_repo([{"id": "T-1"}], "web")
        apply_scope(tasks, DisplayScope.GLOBAL)
        assert tasks[0]["id"] == "T-1"
        # Resolution tags are preserved regardless of shortening.
        assert tasks[0]["_repo"] == "web"
        assert tasks[0]["_local_id"] == "T-1"

    def test_apply_scope_global_colliding_base_namespaces_group(self):
        # Two repos share base ``CALC`` -> every CALC task becomes repo#id,
        # even though CALC-002 vs CALC-003 would not individually collide.
        tasks = [
            {"id": "CALC-002", "_repo": "calc-a", "_local_id": "CALC-002"},
            {"id": "CALC-003", "_repo": "calc-b", "_local_id": "CALC-003"},
        ]
        apply_scope(tasks, DisplayScope.GLOBAL)
        assert tasks[0]["id"] == "calc-a#CALC-002"
        assert tasks[1]["id"] == "calc-b#CALC-003"

    def test_apply_scope_global_mixed_view(self):
        # One colliding base (CALC) and one unique base (PHYS) in the same view.
        tasks = [
            {"id": "CALC-001", "_repo": "calc-a", "_local_id": "CALC-001"},
            {"id": "CALC-002", "_repo": "calc-b", "_local_id": "CALC-002"},
            {"id": "PHYS-001", "_repo": "phys", "_local_id": "PHYS-001"},
        ]
        apply_scope(tasks, DisplayScope.GLOBAL)
        assert tasks[0]["id"] == "calc-a#CALC-001"
        assert tasks[1]["id"] == "calc-b#CALC-002"
        assert tasks[2]["id"] == "PHYS-001"

    def test_apply_scope_global_same_repo_shared_base_stays_short(self):
        # A base shared only within ONE repo is still unique -> bare ids.
        tasks = [
            {"id": "CALC-001", "_repo": "calc", "_local_id": "CALC-001"},
            {"id": "CALC-002", "_repo": "calc", "_local_id": "CALC-002"},
        ]
        apply_scope(tasks, DisplayScope.GLOBAL)
        assert tasks[0]["id"] == "CALC-001"
        assert tasks[1]["id"] == "CALC-002"

    def test_apply_scope_global_no_suffix_base_is_whole_id(self):
        # Ids without a trailing -<digits> suffix are their own base.
        tasks = [
            {"id": "RELEASE", "_repo": "a", "_local_id": "RELEASE"},
            {"id": "RELEASE", "_repo": "b", "_local_id": "RELEASE"},
        ]
        apply_scope(tasks, DisplayScope.GLOBAL)
        assert tasks[0]["id"] == "a#RELEASE"
        assert tasks[1]["id"] == "b#RELEASE"

    def test_apply_scope_global_multi_dash_base(self):
        # Multi-dash ids strip only the trailing numeric segment: FOO-BAR.
        tasks = [
            {"id": "FOO-BAR-01", "_repo": "x", "_local_id": "FOO-BAR-01"},
            {"id": "FOO-BAR-02", "_repo": "y", "_local_id": "FOO-BAR-02"},
        ]
        apply_scope(tasks, DisplayScope.GLOBAL)
        assert tasks[0]["id"] == "x#FOO-BAR-01"
        assert tasks[1]["id"] == "y#FOO-BAR-02"

    def test_apply_scope_global_empty_list(self):
        assert apply_scope([], DisplayScope.GLOBAL) == []

    def test_apply_scope_global_untagged_noop(self):
        tasks = [{"id": "T-1"}]
        apply_scope(tasks, DisplayScope.GLOBAL)
        assert tasks[0]["id"] == "T-1"

    def test_apply_scope_global_missing_local_id_falls_back_to_id(self):
        # Without _local_id, the bare id is derived from the current id.
        tasks = [{"id": "X-1", "_repo": "solo"}]
        apply_scope(tasks, DisplayScope.GLOBAL)
        assert tasks[0]["id"] == "X-1"


class TestBaseId:
    """Tests for the base-prefix helper used by per-view shortening."""

    def test_strips_trailing_numeric_suffix(self):
        assert base_id("CALC-002") == "CALC"

    def test_no_suffix_is_whole_id(self):
        assert base_id("RELEASE") == "RELEASE"

    def test_multi_dash_keeps_prefix(self):
        assert base_id("FOO-BAR-01") == "FOO-BAR"

    def test_non_numeric_suffix_is_whole_id(self):
        assert base_id("T-abc") == "T-abc"

    def test_empty_string(self):
        assert base_id("") == ""


class TestShouldNamespace:
    """Tests for the short-vs-long display policy predicate."""

    def test_single_repo_stays_bare(self):
        assert _should_namespace({"repo-a"}) is False

    def test_multiple_repos_namespaced(self):
        assert _should_namespace({"repo-a", "repo-b"}) is True

    def test_empty_set_stays_bare(self):
        assert _should_namespace(set()) is False


class TestResolveTaskRef:
    """Tests for resolve_task_ref against a running CLI context."""

    def _ctx(self, store_path, env):
        """Build a DotoContext as the CLI would for the given store."""
        from doxtr_doto.cli.config import load_config
        from doxtr_doto.cli.global_state import GlobalStateStore
        from doxtr_doto.cli.json_store import JsonTaskStore
        from doxtr_doto.cli.main import DotoContext
        from doxtr_doto.cli.output import get_formatter

        config = load_config(json_path=store_path)
        store = JsonTaskStore(config.get_json_path())
        formatter = get_formatter(config)
        return DotoContext(
            config=config,
            store=store,
            formatter=formatter,
            global_store=GlobalStateStore(),
        )

    def test_bare_id_uses_current_store(self, tmp_path, env):
        repo = _make_repo(tmp_path, "web", {"T-1": {"title": "x"}})
        store_path = repo / ".doto" / "tasks.json"
        ctx = self._ctx(store_path, env)
        resolved = resolve_task_ref(ctx, "T-1")
        assert resolved is not None
        assert resolved.task_id == "T-1"
        assert resolved.store.get_task("T-1") is not None

    def test_namespaced_resolves_via_registry(self, tmp_path, env):
        other = _make_repo(tmp_path, "api", {"A-1": {"title": "y"}})
        local = _make_repo(tmp_path, "web", {"T-1": {"title": "x"}})
        local_store = local / ".doto" / "tasks.json"
        ctx = self._ctx(local_store, env)

        # Register the other repo in the cache.
        from doxtr_doto.cli.repo_registry import RepoRegistry

        RepoRegistry(ctx.global_store).add(other)

        resolved = resolve_task_ref(ctx, "api#A-1")
        assert resolved is not None
        assert resolved.repo == "api"
        assert resolved.task_id == "A-1"
        assert resolved.store.get_task("A-1")["title"] == "y"

    def test_namespaced_unknown_repo_returns_none(self, tmp_path, env):
        local = _make_repo(tmp_path, "web", {"T-1": {"title": "x"}})
        store_path = local / ".doto" / "tasks.json"
        ctx = self._ctx(store_path, env)
        assert resolve_task_ref(ctx, "ghost#1") is None


class TestNamespacedCommands:
    """Tests that CLI verbs accept namespaced ids from any cwd."""

    @pytest.fixture
    def two_repos(self, tmp_path, env, runner, monkeypatch):
        """Two repos; register 'api' in the cache keyed to the local repo."""
        api = _make_repo(tmp_path, "api", {"A-1": {"title": "api task", "status": "open"}})
        web = _make_repo(tmp_path, "web", {"T-1": {"title": "web task", "status": "open"}})
        web_store = web / ".doto" / "tasks.json"
        runner.invoke(cli, ["--json", str(web_store), "repos", "add", str(api)])
        return web_store, api, web

    def test_done_namespaced(self, two_repos, runner):
        web_store, api, _web = two_repos
        result = runner.invoke(cli, ["--json", str(web_store), "done", "api#A-1"])
        assert result.exit_code == 0
        data = json.loads((api / ".doto" / "tasks.json").read_text())
        assert data["tasks"]["A-1"]["status"] == "done"

    def test_show_namespaced(self, two_repos, runner):
        web_store, _api, _web = two_repos
        result = runner.invoke(cli, ["--json", str(web_store), "show", "api#A-1"])
        assert result.exit_code == 0
        assert "api task" in result.output

    def test_update_namespaced(self, two_repos, runner):
        web_store, api, _web = two_repos
        result = runner.invoke(
            cli,
            ["--json", str(web_store), "update", "api#A-1", "--priority", "high"],
        )
        assert result.exit_code == 0
        data = json.loads((api / ".doto" / "tasks.json").read_text())
        assert data["tasks"]["A-1"]["priority"] == "high"

    def test_done_unknown_namespaced_reports_not_found(self, two_repos, runner):
        web_store, _api, _web = two_repos
        result = runner.invoke(cli, ["--json", str(web_store), "done", "ghost#9"])
        assert "not found" in result.output

    def test_log_namespaced_reads_foreign_store(self, two_repos, runner):
        # Regression: `doto log repo#id` from a foreign cwd must read the
        # foreign repo's store, not the local one. Seed a worklog in the api
        # repo and a same-id (bare) task locally to prove the local store is
        # NOT the one being read.
        web_store, api, web = two_repos
        api_store_path = api / ".doto" / "tasks.json"
        api_data = json.loads(api_store_path.read_text())
        api_data["tasks"]["A-1"]["worklogs"] = [
            {
                "started_at": "2000-01-01T09:00:00+00:00",
                "stopped_at": "2000-01-01T10:00:00+00:00",
            }
        ]
        api_store_path.write_text(json.dumps(api_data))

        result = runner.invoke(cli, ["--json", str(web_store), "log", "api#A-1", "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["task_id"] == "A-1"
        assert len(payload["worklogs"]) == 1
        assert payload["worklogs"][0]["started_at"] == "2000-01-01T09:00:00+00:00"

    def test_done_already_done_namespaced_warns_no_resave(self, two_repos, runner):
        # Completing an already-done task via the namespaced path must emit the
        # "already done" warning and must not perform a second save (the store
        # mtime stays unchanged).
        web_store, api, _web = two_repos
        api_store_path = api / ".doto" / "tasks.json"

        first = runner.invoke(cli, ["--json", str(web_store), "done", "api#A-1"])
        assert first.exit_code == 0
        mtime_after_first = api_store_path.stat().st_mtime_ns

        second = runner.invoke(cli, ["--json", str(web_store), "done", "api#A-1"])
        assert second.exit_code == 0
        assert "already done" in second.output
        # No erroneous second save: the store file was not rewritten.
        assert api_store_path.stat().st_mtime_ns == mtime_after_first
        # Task remains done in the foreign store.
        api_data = json.loads(api_store_path.read_text())
        assert api_data["tasks"]["A-1"]["status"] == "done"


class TestListAggregation:
    """Tests for 'doto list -r' aggregated multi-repo views."""

    @pytest.fixture
    def repos(self, tmp_path, env, runner, monkeypatch):
        api = _make_repo(
            tmp_path, "api", {"A-1": {"title": "api task", "status": "open", "priority": "high"}}
        )
        web = _make_repo(
            tmp_path, "web", {"T-1": {"title": "web task", "status": "open", "priority": "low"}}
        )
        monkeypatch.chdir(tmp_path)
        web_store = web / ".doto" / "tasks.json"
        # Cache both repos.
        runner.invoke(cli, ["--json", str(web_store), "repos", "rescan", str(tmp_path)])
        return web_store, api, web

    def test_recursive_shortens_distinct_bases(self, repos, runner):
        # api#A-1 and web#T-1 have distinct base prefixes (A vs T), so each is
        # unique in the view and shown as its bare local id.
        web_store, _api, _web = repos
        result = runner.invoke(cli, ["--json", str(web_store), "list", "-r", "--format", "json"])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        ids = {t["id"] for t in payload}
        assert ids == {"A-1", "T-1"}
        # Resolution tags are preserved so the ids still map back to a repo.
        by_id = {t["id"]: t for t in payload}
        assert by_id["A-1"]["_repo"] == "api"
        assert by_id["A-1"]["_local_id"] == "A-1"
        assert by_id["T-1"]["_repo"] == "web"

    def test_local_scope_no_prefix(self, repos, runner):
        web_store, _api, _web = repos
        result = runner.invoke(cli, ["--json", str(web_store), "list", "--format", "json"])
        payload = json.loads(result.output)
        ids = {t["id"] for t in payload}
        assert ids == {"T-1"}

    def test_recursive_respects_filters(self, repos, runner):
        web_store, _api, _web = repos
        result = runner.invoke(
            cli,
            [
                "--json",
                str(web_store),
                "list",
                "-r",
                "--priority",
                "high",
                "--format",
                "json",
            ],
        )
        payload = json.loads(result.output)
        ids = {t["id"] for t in payload}
        # Only one task survives the filter; its base prefix is unique so it is
        # shown short.
        assert ids == {"A-1"}

    def test_rescan_flag_implies_recursive(self, repos, runner):
        web_store, _api, _web = repos
        result = runner.invoke(
            cli, ["--json", str(web_store), "list", "--rescan", "--format", "json"]
        )
        payload = json.loads(result.output)
        ids = {t["id"] for t in payload}
        assert ids == {"A-1", "T-1"}

    def test_recursive_namespaces_colliding_base_group(self, tmp_path, env, runner, monkeypatch):
        # Two repos share the ``T`` base prefix in the same view, so the whole
        # group is shown as repo#id even though the full ids differ.
        api = _make_repo(tmp_path, "api", {"T-1": {"title": "api t", "status": "open"}})
        web = _make_repo(tmp_path, "web", {"T-2": {"title": "web t", "status": "open"}})
        monkeypatch.chdir(tmp_path)
        web_store = web / ".doto" / "tasks.json"
        runner.invoke(cli, ["--json", str(web_store), "repos", "rescan", str(tmp_path)])
        result = runner.invoke(cli, ["--json", str(web_store), "list", "-r", "--format", "json"])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        ids = {t["id"] for t in payload}
        assert ids == {"api#T-1", "web#T-2"}
        # The bare local ids are still recoverable for resolution.
        assert {t["_local_id"] for t in payload} == {"T-1", "T-2"}
        _ = api
