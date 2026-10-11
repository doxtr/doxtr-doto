"""Tests for the ``studies`` multi-repo test-bed generator.

The generator (``scripts/gen_studies_testbed.py``, exposed via the
``studies_generator`` / ``studies_testbed`` fixtures in ``conftest.py``) builds
a realistic, deterministic set of doto repositories -- a high-school student's
subject notes plus a university programme -- for exercising cross-repo
behaviour: discovery, filtering, aggregation, and time tracking.

These tests do two jobs:

1. **Self-test the generator** so the shared fixture stays trustworthy: the
   emitted ``.doto/tasks.json`` is schema-correct, every status is represented,
   worklogs parse, dependencies are internally consistent, and IDs match each
   repo's configured prefix.
2. **Exercise the real code paths** the test bed exists to support
   (``RepoRegistry`` discovery, ``JsonTaskStore`` filtering, and the
   ``time_tracking`` helpers) against that data.
"""

from __future__ import annotations

from pathlib import Path

from doxtr_doto.cli.global_state import GlobalStateStore
from doxtr_doto.cli.repo_registry import RepoRegistry
from doxtr_doto.sync.json_store import SCHEMA_VERSION, JsonTaskStore
from doxtr_doto.time_tracking import elapsed_seconds, has_open_session, parse_timestamp

# Statuses every generated repo should collectively cover.
ALL_STATUSES = {"open", "in-progress", "blocked", "done"}
# Repos the generator is expected to emit (folder names).
EXPECTED_REPOS = {
    # high school
    "maths",
    "physics",
    "chemistry",
    "biology",
    "english",
    "german",
    "history",
    "computer-basics",
    # university
    "cs101-programming",
    "cs102-discrete-maths",
    "cs103-calculus",
    "ac100-academic-writing",
    "cs201-data-structures",
    "cs202-databases",
    "cs203-computer-systems",
    "cs204-software-engineering",
}


class TestGeneratorShape:
    """The generator produces the expected tree and summary metadata."""

    def test_builds_all_repos(self, studies_testbed: dict) -> None:
        names = {r["name"] for r in studies_testbed["repos"]}
        assert names == EXPECTED_REPOS

    def test_root_layout(self, studies_testbed: dict) -> None:
        root: Path = studies_testbed["root"]
        assert (root / "index.rst").is_file()
        assert (root / "highschool" / "index.rst").is_file()
        assert (root / "university" / "index.rst").is_file()
        # High-school subjects nest under highschool/, modules under university/.
        assert (root / "highschool" / "maths" / ".doto.toml").is_file()
        assert (root / "university" / "cs201-data-structures" / ".doto.toml").is_file()

    def test_metadata_totals_match_disk(self, studies_testbed: dict) -> None:
        # total_tasks and status_totals are derived from the files, but assert
        # internal consistency so a drift in the summary is caught.
        summed = sum(r["task_count"] for r in studies_testbed["repos"])
        assert summed == studies_testbed["total_tasks"]
        status_sum = sum(studies_testbed["status_totals"].values())
        assert status_sum == studies_testbed["total_tasks"]

    def test_all_statuses_represented(self, studies_testbed: dict) -> None:
        assert set(studies_testbed["status_totals"]) == ALL_STATUSES
        # Every status should have at least one task so filtering tests have
        # something to match in each bucket.
        assert all(count > 0 for count in studies_testbed["status_totals"].values())

    def test_build_is_deterministic(self, studies_generator, tmp_path: Path) -> None:
        a = studies_generator.build(tmp_path / "a")
        b = studies_generator.build(tmp_path / "b")
        assert a["total_tasks"] == b["total_tasks"]
        assert a["status_totals"] == b["status_totals"]
        # The on-disk task stores should be byte-identical across builds.
        for repo in a["repos"]:
            rel = repo["path"].relative_to(a["root"])
            fa = (a["root"] / rel / ".doto" / "tasks.json").read_text()
            fb = (b["root"] / rel / ".doto" / "tasks.json").read_text()
            assert fa == fb

    def test_build_does_not_touch_default_root(self, studies_generator, tmp_path: Path) -> None:
        # Building into a tmp dir must restore the module-level output roots so
        # the real studies/ folder is never clobbered by a test run.
        studies_generator.build(tmp_path / "studies")
        assert studies_generator.ROOT == studies_generator.DEFAULT_ROOT
        assert studies_generator.HS == studies_generator.DEFAULT_ROOT / "highschool"


class TestTaskStoreCorrectness:
    """Every generated store is schema-correct and internally consistent."""

    def test_schema_version_and_structure(self, studies_testbed: dict) -> None:
        for repo in studies_testbed["repos"]:
            store = JsonTaskStore(repo["path"] / ".doto" / "tasks.json")
            data = store.data
            assert data["version"] == SCHEMA_VERSION
            assert isinstance(data["tasks"], dict)
            assert isinstance(data.get("series", {}), dict)

    def test_ids_match_repo_prefix(self, studies_testbed: dict) -> None:
        for repo in studies_testbed["repos"]:
            prefix = repo["prefix"]
            assert prefix, f"{repo['name']} has no id_prefix"
            store = JsonTaskStore(repo["path"] / ".doto" / "tasks.json")
            for task_id in store.get_all_tasks():
                assert task_id.startswith(f"{prefix}-"), task_id

    def test_required_fields_present(self, studies_testbed: dict) -> None:
        required = {
            "title",
            "status",
            "priority",
            "created",
            "updated",
            "tags",
            "depends_on",
            "worklogs",
            "_sync",
        }
        for repo in studies_testbed["repos"]:
            store = JsonTaskStore(repo["path"] / ".doto" / "tasks.json")
            for task_id, task in store.get_all_tasks().items():
                missing = required - set(task)
                assert not missing, f"{task_id} missing {missing}"
                assert task["status"] in ALL_STATUSES

    def test_dependencies_resolve_within_repo(self, studies_testbed: dict) -> None:
        # Every depends_on target must be a real task in the *same* repo so the
        # dependency/blocked-chain data is coherent.
        for repo in studies_testbed["repos"]:
            store = JsonTaskStore(repo["path"] / ".doto" / "tasks.json")
            ids = set(store.get_all_tasks())
            for task_id, task in store.get_all_tasks().items():
                for dep in task.get("depends_on", []):
                    assert dep in ids, f"{task_id} depends on unknown {dep}"


class TestWorklogData:
    """The logged-time data is parseable and aggregates to positive totals."""

    def test_worklogs_parse_and_accumulate(self, studies_testbed: dict) -> None:
        total_logged = 0
        tasks_with_time = 0
        for repo in studies_testbed["repos"]:
            store = JsonTaskStore(repo["path"] / ".doto" / "tasks.json")
            for task in store.get_all_tasks().values():
                worklogs = task.get("worklogs", [])
                for wl in worklogs:
                    # started_at always present and parseable.
                    parse_timestamp(wl["started_at"])
                    if wl["stopped_at"] is not None:
                        parse_timestamp(wl["stopped_at"])
                if worklogs:
                    tasks_with_time += 1
                    secs = elapsed_seconds(worklogs)
                    assert secs > 0
                    total_logged += secs
        # The test bed deliberately logs time on many tasks.
        assert tasks_with_time > 0
        assert total_logged > 0

    def test_contains_an_open_session(self, studies_testbed: dict) -> None:
        # At least one task should have a running (open) session so live-timer
        # handling can be tested.
        found_open = False
        for repo in studies_testbed["repos"]:
            store = JsonTaskStore(repo["path"] / ".doto" / "tasks.json")
            for task in store.get_all_tasks().values():
                if has_open_session(task.get("worklogs", [])):
                    found_open = True
        assert found_open


class TestCrossRepoBehaviour:
    """The data supports the discovery/filtering/aggregation it exists for."""

    def test_registry_discovers_every_repo(self, studies_testbed: dict, tmp_path: Path) -> None:
        # Isolate the registry's global state so discovery is reproducible.
        store = GlobalStateStore(tmp_path / "global.json")
        registry = RepoRegistry(store)
        found = registry.discover(studies_testbed["root"])
        names = {r.name for r in found}
        assert names == EXPECTED_REPOS

    def test_filter_by_status_per_repo(self, studies_repo) -> None:
        maths = studies_repo("maths")
        store = JsonTaskStore(maths["path"] / ".doto" / "tasks.json")
        blocked = store.filter_tasks(status="blocked", include_archived=True)
        assert blocked, "maths should have a blocked task"
        assert all(t["status"] == "blocked" for t in blocked)

    def test_status_aggregation_across_repos(self, studies_testbed: dict) -> None:
        # Re-aggregate independently of the generator's summary and compare, so
        # a cross-repo stats roll-up has a trusted expected value.
        import collections

        agg: collections.Counter[str] = collections.Counter()
        for repo in studies_testbed["repos"]:
            store = JsonTaskStore(repo["path"] / ".doto" / "tasks.json")
            for task in store.get_all_tasks().values():
                agg[task["status"]] += 1
        assert dict(agg) == studies_testbed["status_totals"]

    def test_prefixes_are_unique(self, studies_testbed: dict) -> None:
        prefixes = [r["prefix"] for r in studies_testbed["repos"]]
        assert len(prefixes) == len(set(prefixes)), "repo id-prefixes must be unique"
