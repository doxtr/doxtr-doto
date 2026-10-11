"""Tests for the time-tracking CLI verbs (start/stop/clock-out/status/log)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from doxtr_doto.cli.main import cli


@pytest.fixture
def runner():
    """Create a CLI runner."""
    return CliRunner()


@pytest.fixture
def store_file(tmp_path):
    """A JSON store with a single open task."""
    store_path = tmp_path / "repoA" / ".doto" / "tasks.json"
    store_path.parent.mkdir(parents=True)
    data = {
        "version": 5,
        "updated": "2024-01-01T00:00:00",
        "tasks": {
            "T-001": {
                "title": "First task",
                "status": "open",
                "priority": "high",
                "worklogs": [],
            },
            "T-002": {
                "title": "Second task",
                "status": "open",
                "priority": "low",
                "worklogs": [],
            },
        },
        "series": {},
    }
    store_path.write_text(json.dumps(data))
    return store_path


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Isolate the global config under XDG_CONFIG_HOME in a temp dir."""
    cfg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    # Avoid picking up a real user config / home TOML files.
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    # Isolate the portable config lookup: ``resolve_global_config_path`` walks
    # up from the cwd for a ``.doto/config.json`` *before* falling back to
    # XDG. Running from the repo root would otherwise find the real
    # ``.doto/config.json`` and leak its active session / work clock into
    # these tests. Chdir to an empty tmp dir so the walk-up finds nothing and
    # resolution falls through to the isolated XDG path. ``DOTO_CONFIG`` has
    # even higher priority, so clear it too in case the environment sets it.
    monkeypatch.delenv("DOTO_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    return cfg


def _invoke(runner, store_file, *args):
    """Invoke the CLI with the store file wired in via --json."""
    return runner.invoke(cli, ["--json", str(store_file), *args])


def _load(store_file):
    return json.loads(store_file.read_text())


def _global_state(env):
    path = env / "doto" / "config.json"
    return json.loads(path.read_text())


class TestStart:
    """Tests for the start command."""

    def test_start_work_clocks_in(self, runner, store_file, env):
        result = _invoke(runner, store_file, "start")
        assert result.exit_code == 0
        assert "Clocked in" in result.output
        state = _global_state(env)
        logs = state["work_clock"]["worklogs"]
        assert len(logs) == 1
        assert logs[0]["stopped_at"] is None

    def test_start_work_twice_warns(self, runner, store_file, env):
        _invoke(runner, store_file, "start")
        result = _invoke(runner, store_file, "start", "work")
        assert "already running" in result.output
        assert len(_global_state(env)["work_clock"]["worklogs"]) == 1

    def test_start_task_auto_clocks_in_and_starts_focus(self, runner, store_file, env):
        result = _invoke(runner, store_file, "start", "T-001")
        assert result.exit_code == 0
        assert "Started focus timer for T-001" in result.output

        state = _global_state(env)
        # Work clock auto-started.
        assert len(state["work_clock"]["worklogs"]) == 1
        # Active session points at the task.
        assert state["active_session"]["task_id"] == "T-001"

        task = _load(store_file)["tasks"]["T-001"]
        assert len(task["worklogs"]) == 1
        assert task["worklogs"][0]["stopped_at"] is None

    def test_start_new_task_stops_previous_focus(self, runner, store_file, env):
        _invoke(runner, store_file, "start", "T-001")
        result = _invoke(runner, store_file, "start", "T-002")
        assert "Stopped focus timer for T-001" in result.output

        data = _load(store_file)
        # Previous focus closed.
        assert data["tasks"]["T-001"]["worklogs"][0]["stopped_at"] is not None
        # New focus open.
        assert data["tasks"]["T-002"]["worklogs"][0]["stopped_at"] is None
        assert _global_state(env)["active_session"]["task_id"] == "T-002"

    def test_start_same_task_does_not_stop_itself(self, runner, store_file, env):
        _invoke(runner, store_file, "start", "T-001")
        result = _invoke(runner, store_file, "start", "T-001")
        assert "Stopped focus timer" not in result.output
        task = _load(store_file)["tasks"]["T-001"]
        # Re-starting the already-active task is a no-op on the worklogs: it
        # must NOT append a second open session (that would double-count
        # elapsed time and leave a dangling open worklog after stop).
        assert len(task["worklogs"]) == 1
        assert task["worklogs"][0]["stopped_at"] is None

    def test_start_same_task_twice_then_stop_closes_single_session(self, runner, store_file, env):
        # Regression for the double-open-session bug: start X; start X must
        # leave exactly one open worklog, and a single stop must close it with
        # no dangling open session left behind.
        _invoke(runner, store_file, "start", "T-001")
        _invoke(runner, store_file, "start", "T-001")
        task = _load(store_file)["tasks"]["T-001"]
        open_sessions = [w for w in task["worklogs"] if w["stopped_at"] is None]
        assert len(open_sessions) == 1

        _invoke(runner, store_file, "stop")
        task = _load(store_file)["tasks"]["T-001"]
        open_after = [w for w in task["worklogs"] if w["stopped_at"] is None]
        assert open_after == []

    def test_start_missing_task_errors(self, runner, store_file, env):
        result = _invoke(runner, store_file, "start", "NOPE")
        assert "not found" in result.output

    def test_start_json_output(self, runner, store_file, env):
        result = _invoke(runner, store_file, "start", "T-001", "--json")
        payload = json.loads(result.output)
        assert payload["action"] == "start"
        assert payload["task_id"] == "T-001"
        assert payload["work_clocked_in"] is True

    def test_start_focus_restart_after_autostop_stops_cleanly(self, store_file, env):
        """Regression: a stale ``ctx.store`` must not clobber disk worklogs.

        Drives the shared :func:`start_focus` / :func:`stop_focus` helpers the
        way the live TUI does: one long-lived :class:`DotoContext` (and thus
        one ``ctx.store``) is reused across presses while the worklog is
        opened through a *freshly resolved* store for the same path. That
        leaves ``ctx.store``'s cache stale. Pre-fix both helpers performed
        their read-modify-write against the stale snapshot and clobbered disk,
        silently dropping the open worklog (and its elapsed time) - the root
        cause of the stuck focus arrow. After the fix each helper reloads
        first, so:

        * ``start_focus`` on a task that already has an open worklog on disk
          closes it and appends a new one (both intervals preserved,
          enforcing the single-open-session invariant), and
        * ``stop_focus`` closes the open worklog in place rather than wiping
          it, and clears ``active_session``.

        Pre-fix this fails (the dropped worklog leaves fewer intervals on disk
        and an open session after stop).
        """
        from doxtr_doto.cli.commands.start import start_focus
        from doxtr_doto.cli.commands.stop import stop_focus
        from doxtr_doto.cli.config import load_config
        from doxtr_doto.cli.global_state import GlobalStateStore
        from doxtr_doto.cli.id_resolver import resolve_task_ref
        from doxtr_doto.cli.json_store import JsonTaskStore
        from doxtr_doto.cli.main import DotoContext
        from doxtr_doto.cli.output import get_formatter
        from doxtr_doto.time_tracking import has_open_session, start_session

        config = load_config(json_path=store_file)

        # --- start_focus clobber (drops an already-open interval) ---------
        ctx = DotoContext(
            config=config,
            store=JsonTaskStore(config.get_json_path()),
            formatter=get_formatter(config),
            global_store=GlobalStateStore(),
        )
        # Prime ctx.store's cache the way the live client reads tasks first,
        # then let it go stale while a different store instance for the same
        # path opens a worklog on A and persists it (the TUI opens through a
        # freshly resolved store).
        ctx.store.get_all_tasks()
        other = JsonTaskStore(store_file)
        task = other.get_task("T-001")
        task["worklogs"] = start_session(task.get("worklogs", []))
        other.update_task("T-001", {"worklogs": task["worklogs"]})
        other.save()

        # start_focus on A through the stale ctx.store must preserve the
        # already-open interval (close it) and append the new one: two total,
        # exactly one open. Pre-fix the stale read dropped the first interval.
        start_focus(ctx, resolve_task_ref(ctx, "T-001"))
        a_worklogs = _load(store_file)["tasks"]["T-001"]["worklogs"]
        assert len(a_worklogs) == 2
        assert len([w for w in a_worklogs if w["stopped_at"] is None]) == 1

        # --- stop_focus clobber (wipes the open interval) -----------------
        # Fresh context with a primed-then-stale ctx.store, and a session that
        # resolves back to it (matching json_path). A different store instance
        # opens a worklog on T-002, so ctx.store's cache is stale (no open
        # worklog). Pre-fix stop_focus clobbered disk with the empty snapshot.
        ctx2 = DotoContext(
            config=config,
            store=JsonTaskStore(config.get_json_path()),
            formatter=get_formatter(config),
            global_store=GlobalStateStore(),
        )
        ctx2.store.get_all_tasks()  # prime, then go stale
        other2 = JsonTaskStore(store_file)
        task = other2.get_task("T-002")
        task["worklogs"] = start_session(task.get("worklogs", []))
        other2.update_task("T-002", {"worklogs": task["worklogs"]})
        other2.save()
        state = ctx2.global_store.load()
        state.active_session = {
            "repo": "repoA",
            "task_id": "T-002",
            "json_path": str(store_file),
        }
        ctx2.global_store.save(state)

        stopped = stop_focus(ctx2)
        assert stopped == "T-002"
        b_worklogs = _load(store_file)["tasks"]["T-002"]["worklogs"]
        # The interval is retained and closed in place, not wiped.
        assert len(b_worklogs) == 1
        task = JsonTaskStore(store_file).get_task("T-002")
        assert task is not None
        assert has_open_session(task.get("worklogs", [])) is False
        assert ctx2.global_store.load().active_session is None


class TestStop:
    """Tests for the stop command."""

    def test_stop_closes_focus_keeps_work(self, runner, store_file, env):
        _invoke(runner, store_file, "start", "T-001")
        result = _invoke(runner, store_file, "stop")
        assert "Stopped focus timer for T-001" in result.output

        state = _global_state(env)
        assert state["active_session"] is None
        # Work clock still running.
        assert state["work_clock"]["worklogs"][0]["stopped_at"] is None

        task = _load(store_file)["tasks"]["T-001"]
        assert task["worklogs"][0]["stopped_at"] is not None

    def test_stop_work_stops_both(self, runner, store_file, env):
        _invoke(runner, store_file, "start", "T-001")
        result = _invoke(runner, store_file, "stop", "work")
        assert "Clocked out" in result.output

        state = _global_state(env)
        assert state["active_session"] is None
        assert state["work_clock"]["worklogs"][0]["stopped_at"] is not None

    def test_stop_without_session_warns(self, runner, store_file, env):
        result = _invoke(runner, store_file, "stop")
        assert "No active focus session" in result.output

    def test_stop_closes_orphaned_worklog_without_active_session(self, runner, store_file, env):
        """stop recovers a task stuck running with no active_session pointer.

        Simulates the pointer/worklog desync: the task carries an open worklog
        on disk but global state has no ``active_session``. ``stop`` must still
        close the dangling worklog so the task does not stay stuck running.
        """
        # Open a worklog directly on disk, leaving active_session unset.
        data = _load(store_file)
        data["tasks"]["T-001"]["worklogs"] = [
            {"started_at": "2024-01-01T08:00:00", "stopped_at": None}
        ]
        store_file.write_text(json.dumps(data))

        result = _invoke(runner, store_file, "stop")
        assert "Stopped focus timer for T-001" in result.output

        task = _load(store_file)["tasks"]["T-001"]
        assert task["worklogs"][0]["stopped_at"] is not None

    def test_stop_json_output(self, runner, store_file, env):
        _invoke(runner, store_file, "start", "T-001")
        result = _invoke(runner, store_file, "stop", "--json")
        payload = json.loads(result.output)
        assert payload["stopped_focus"] == "T-001"
        assert payload["clocked_out"] is False


class TestClockOut:
    """Tests for the clock-out command."""

    def test_clock_out_stops_focus_and_work(self, runner, store_file, env):
        _invoke(runner, store_file, "start", "T-001")
        result = _invoke(runner, store_file, "clock-out")
        assert "Stopped focus timer for T-001" in result.output
        assert "Clocked out" in result.output

        state = _global_state(env)
        assert state["active_session"] is None
        assert state["work_clock"]["worklogs"][0]["stopped_at"] is not None

    def test_clock_out_when_not_running_warns(self, runner, store_file, env):
        result = _invoke(runner, store_file, "clock-out")
        assert "was not running" in result.output

    def test_clock_out_json(self, runner, store_file, env):
        _invoke(runner, store_file, "start", "T-001")
        result = _invoke(runner, store_file, "clock-out", "--json")
        payload = json.loads(result.output)
        assert payload["action"] == "clock-out"
        assert payload["clocked_out"] is True


class TestStatus:
    """Tests for the status command."""

    def test_status_no_session(self, runner, store_file, env):
        result = _invoke(runner, store_file, "status")
        assert "No active focus session" in result.output
        assert "Work clock (stopped)" in result.output

    def test_status_with_focus(self, runner, store_file, env):
        _invoke(runner, store_file, "start", "T-001")
        result = _invoke(runner, store_file, "status")
        assert "T-001" in result.output
        assert "First task" in result.output
        assert "Work clock (running)" in result.output

    def test_status_json(self, runner, store_file, env):
        _invoke(runner, store_file, "start", "T-001")
        result = _invoke(runner, store_file, "status", "--json")
        payload = json.loads(result.output)
        assert payload["focus"]["id"] == "T-001"
        assert payload["work_clock"]["running"] is True


class TestLog:
    """Tests for the log command."""

    def test_log_lists_open_session(self, runner, store_file, env):
        _invoke(runner, store_file, "start", "T-001")
        result = _invoke(runner, store_file, "log", "T-001")
        assert "Sessions for T-001" in result.output
        assert "(running)" in result.output

    def test_log_defaults_to_active_task(self, runner, store_file, env):
        _invoke(runner, store_file, "start", "T-001")
        result = _invoke(runner, store_file, "log")
        assert "Sessions for T-001" in result.output

    def test_log_no_task_no_session_errors(self, runner, store_file, env):
        result = _invoke(runner, store_file, "log")
        assert "no active session" in result.output.lower()

    def test_log_missing_task(self, runner, store_file, env):
        result = _invoke(runner, store_file, "log", "NOPE")
        assert "not found" in result.output

    def test_log_day_filter_excludes(self, runner, store_file, env):
        _invoke(runner, store_file, "start", "T-001")
        result = _invoke(runner, store_file, "log", "T-001", "--day", "1999-01-01")
        assert "No sessions" in result.output

    def test_log_json(self, runner, store_file, env):
        _invoke(runner, store_file, "start", "T-001")
        result = _invoke(runner, store_file, "log", "T-001", "--json")
        payload = json.loads(result.output)
        assert payload["task_id"] == "T-001"
        assert len(payload["worklogs"]) == 1

    def test_log_fix_close(self, runner, store_file, env):
        _invoke(runner, store_file, "start", "T-001")
        result = _invoke(runner, store_file, "log", "T-001", "--fix", "close")
        assert "Closed T-001" in result.output
        task = _load(store_file)["tasks"]["T-001"]
        assert task["worklogs"][0]["stopped_at"] is not None
        # Active session cleared.
        assert _global_state(env)["active_session"] is None

    def test_log_fix_discard(self, runner, store_file, env):
        _invoke(runner, store_file, "start", "T-001")
        result = _invoke(runner, store_file, "log", "T-001", "--fix", "discard")
        assert "Discarded T-001" in result.output
        task = _load(store_file)["tasks"]["T-001"]
        assert task["worklogs"] == []
        assert _global_state(env)["active_session"] is None

    def test_log_fix_split_on_overnight(self, runner, store_file, env):
        # Seed an overnight open session directly.
        data = _load(store_file)
        data["tasks"]["T-001"]["worklogs"] = [
            {"started_at": "2000-01-01T22:00:00+00:00", "stopped_at": None}
        ]
        store_file.write_text(json.dumps(data))

        result = _invoke(runner, store_file, "log", "T-001", "--fix", "split")
        assert "Split T-001" in result.output
        task = _load(store_file)["tasks"]["T-001"]
        # Original interval closed, new open interval appended.
        assert len(task["worklogs"]) == 2
        assert task["worklogs"][0]["stopped_at"] is not None
        assert task["worklogs"][1]["stopped_at"] is None

    def test_log_fix_split_today_warns(self, runner, store_file, env):
        _invoke(runner, store_file, "start", "T-001")
        result = _invoke(runner, store_file, "log", "T-001", "--fix", "split")
        assert "nothing to split" in result.output

    def test_log_fix_no_open_session_warns(self, runner, store_file, env):
        result = _invoke(runner, store_file, "log", "T-001", "--fix", "close")
        assert "No open session" in result.output

    def test_log_edit_sets_stop(self, runner, store_file, env):
        _invoke(runner, store_file, "start", "T-001")
        result = _invoke(
            runner,
            store_file,
            "log",
            "T-001",
            "--edit",
            "2030-01-01T12:00:00+00:00",
        )
        assert "Set stop time" in result.output
        task = _load(store_file)["tasks"]["T-001"]
        assert task["worklogs"][0]["stopped_at"] == "2030-01-01T12:00:00+00:00"
        assert _global_state(env)["active_session"] is None

    def test_log_edit_invalid_timestamp(self, runner, store_file, env):
        _invoke(runner, store_file, "start", "T-001")
        result = _invoke(runner, store_file, "log", "T-001", "--edit", "not-a-date")
        assert "Invalid timestamp" in result.output

    def test_log_edit_no_open_session_warns(self, runner, store_file, env):
        result = _invoke(
            runner,
            store_file,
            "log",
            "T-001",
            "--edit",
            "2030-01-01T12:00:00+00:00",
        )
        assert "No open session" in result.output


class TestCompleteAlias:
    """Tests for the 'complete' alias of 'done'."""

    def test_complete_marks_done(self, runner, store_file, env):
        result = _invoke(runner, store_file, "complete", "T-001")
        assert result.exit_code == 0
        assert _load(store_file)["tasks"]["T-001"]["status"] == "done"


class TestSessionHelpers:
    """Tests for pure helpers in doxtr_doto.cli.session."""

    def test_format_duration_hours(self):
        from doxtr_doto.cli.session import format_duration

        assert format_duration(3723) == "1h02m03s"

    def test_format_duration_minutes(self):
        from doxtr_doto.cli.session import format_duration

        assert format_duration(305) == "5m05s"

    def test_format_duration_seconds(self):
        from doxtr_doto.cli.session import format_duration

        assert format_duration(0) == "0s"
        assert format_duration(-10) == "0s"

    def test_namespaced_id_roundtrip(self):
        from doxtr_doto.cli.session import namespaced_id, split_namespaced_id

        assert namespaced_id("web", "14") == "web#14"
        assert split_namespaced_id("web#14") == ("web", "14")
        assert split_namespaced_id("14") == (None, "14")

    def test_session_display_hides_local_prefix(self):
        from doxtr_doto.cli.session import session_display_id

        session = {"repo": "web", "task_id": "14"}
        assert session_display_id(session, "web") == "14"

    def test_session_display_shows_foreign_prefix(self):
        from doxtr_doto.cli.session import session_display_id

        session = {"repo": "api", "task_id": "14"}
        assert session_display_id(session, "web") == "api#14"

    def test_session_display_none(self):
        from doxtr_doto.cli.session import session_display_id

        assert session_display_id(None, "web") is None

    def test_derive_repo_name(self, tmp_path):
        from doxtr_doto.cli.config import DotoConfig
        from doxtr_doto.cli.session import derive_repo_name

        source = tmp_path / "my-project"
        source.mkdir()
        config = DotoConfig(source_dir=source)
        assert derive_repo_name(config) == "my-project"
