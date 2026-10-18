"""Tests for the ``doto calsync`` CLI command group.

The provider layer is monkeypatched with an in-memory fake so push/sync run
without any network or SDK, while still exercising the command plumbing, config
loading, and state persistence end to end.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from doxtr_doto.calsync.providers.base import CalendarProvider, PushResult


@pytest.fixture
def cli_runner():
    return CliRunner()


@pytest.fixture
def calsync_project(tmp_path):
    """A project configured for CalDAV calendar sync with two due tasks."""
    doto_dir = tmp_path / ".doto"
    doto_dir.mkdir()
    (tmp_path / ".doto.toml").write_text(
        """
[doto]
json_file = ".doto/tasks.json"
id_prefix = "TEST"

[calendar]
enabled = true
provider = "caldav"
calendar = "work"
event_mode = "event"
username = "me@example.com"
password = "pw"
url = "https://dav.example.com/"
"""
    )
    (doto_dir / "tasks.json").write_text(
        json.dumps(
            {
                "version": 3,
                "updated": "2026-07-26T10:00:00",
                "tasks": {
                    "TASK-001": {
                        "title": "Timed task",
                        "status": "open",
                        "due": "2026-08-15T09:00",
                        "archived": False,
                    },
                    "TASK-002": {
                        "title": "All-day deadline",
                        "status": "open",
                        "due": "2026-08-20",
                        "archived": False,
                    },
                    "TASK-003": {
                        "title": "No due date",
                        "status": "open",
                        "archived": False,
                    },
                },
                "series": {},
            }
        )
    )
    return tmp_path


class _FakeProvider(CalendarProvider):
    name = "fake"
    instances: list[_FakeProvider] = []

    def __init__(self, config):
        super().__init__(config)
        self.created: list[str] = []
        self.updated: list[str] = []
        self.deleted: list[str] = []
        _FakeProvider.instances.append(self)

    def connect(self):
        pass

    def create_event(self, event):
        self.created.append(event.task_id)
        return PushResult(uid=event.uid, etag="e1", remote_id="r-" + event.task_id)

    def update_event(self, event, *, etag="", href=""):
        self.updated.append(event.task_id)
        return PushResult(uid=event.uid, etag="e2", remote_id="r-" + event.task_id)

    def delete_event(self, uid, *, etag="", href=""):
        self.deleted.append(uid)


@pytest.fixture
def fake_provider(monkeypatch):
    """Patch the provider factory to always return the in-memory fake."""
    _FakeProvider.instances = []
    monkeypatch.setattr("doxtr_doto.calsync.providers.get_provider", lambda name: _FakeProvider)
    return _FakeProvider


class TestStatus:
    def test_status_reports_config_and_plan(self, cli_runner, calsync_project):
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, ["--config", str(calsync_project), "calsync", "status"])
        assert result.exit_code == 0
        assert "Provider:   caldav" in result.output
        assert "Event mode: event" in result.output
        # Two schedulable tasks (TASK-003 has no due).
        assert "2 create" in result.output

    def test_status_unconfigured(self, cli_runner, tmp_path):
        from doxtr_doto.cli.main import cli

        (tmp_path / ".doto").mkdir()
        (tmp_path / ".doto.toml").write_text('[doto]\njson_file = ".doto/tasks.json"\n')
        (tmp_path / ".doto" / "tasks.json").write_text(
            '{"version": 3, "updated": "x", "tasks": {}, "series": {}}'
        )
        result = cli_runner.invoke(cli, ["--config", str(tmp_path), "calsync", "status"])
        assert result.exit_code == 0
        assert "(unset)" in result.output


class TestPush:
    def test_dry_run_shows_plan_without_applying(self, cli_runner, calsync_project, fake_provider):
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(
            cli, ["--config", str(calsync_project), "calsync", "push", "--dry-run"]
        )
        assert result.exit_code == 0
        assert "Dry run" in result.output
        assert "2 create" in result.output
        # No provider should have been constructed for a dry run.
        assert fake_provider.instances == []
        # No state file written.
        assert not (calsync_project / ".doto" / "calsync.json").exists()

    def test_push_creates_events_and_writes_state(self, cli_runner, calsync_project, fake_provider):
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, ["--config", str(calsync_project), "calsync", "push"])
        assert result.exit_code == 0
        assert "2 created" in result.output
        prov = fake_provider.instances[-1]
        assert sorted(prov.created) == ["TASK-001", "TASK-002"]
        # State persisted.
        state = json.loads((calsync_project / ".doto" / "calsync.json").read_text())
        ns = state["namespaces"]["caldav::work"]
        assert set(ns.keys()) == {"TASK-001", "TASK-002"}

    def test_second_push_is_idempotent(self, cli_runner, calsync_project, fake_provider):
        from doxtr_doto.cli.main import cli

        cli_runner.invoke(cli, ["--config", str(calsync_project), "calsync", "push"])
        result = cli_runner.invoke(cli, ["--config", str(calsync_project), "calsync", "push"])
        assert result.exit_code == 0
        assert "already up to date" in result.output

    def test_sync_alias(self, cli_runner, calsync_project, fake_provider):
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(
            cli, ["--config", str(calsync_project), "calsync", "sync", "--dry-run"]
        )
        assert result.exit_code == 0
        assert "2 create" in result.output

    def test_exclude_done(self, cli_runner, calsync_project, fake_provider):
        from doxtr_doto.cli.main import cli

        # Mark TASK-001 done, then push with --exclude-done.
        tasks_file = calsync_project / ".doto" / "tasks.json"
        data = json.loads(tasks_file.read_text())
        data["tasks"]["TASK-001"]["status"] = "done"
        tasks_file.write_text(json.dumps(data))

        result = cli_runner.invoke(
            cli,
            ["--config", str(calsync_project), "calsync", "push", "--exclude-done"],
        )
        assert result.exit_code == 0
        prov = fake_provider.instances[-1]
        assert prov.created == ["TASK-002"]  # TASK-001 excluded


class TestLogout:
    def test_logout_without_token(self, cli_runner, calsync_project, monkeypatch, tmp_path):
        from doxtr_doto.cli.main import cli

        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        result = cli_runner.invoke(cli, ["--config", str(calsync_project), "calsync", "logout"])
        assert result.exit_code == 0
        assert "No cached token" in result.output


class TestErrorPaths:
    def test_push_reports_provider_errors(self, cli_runner, calsync_project, monkeypatch):
        """A per-task provider failure is reported, not fatal."""
        from doxtr_doto.calsync.providers.base import ProviderError
        from doxtr_doto.cli.main import cli

        class _FailingProvider(CalendarProvider):
            name = "failing"

            def connect(self):
                pass

            def create_event(self, event):
                raise ProviderError(f"nope {event.task_id}")

            def update_event(self, event, *, etag="", href=""):
                raise ProviderError("nope")

            def delete_event(self, uid, *, etag="", href=""):
                pass

        monkeypatch.setattr(
            "doxtr_doto.calsync.providers.get_provider", lambda name: _FailingProvider
        )
        result = cli_runner.invoke(cli, ["--config", str(calsync_project), "calsync", "push"])
        assert result.exit_code == 0
        # Both tasks failed -> reported per-task, 0 created.
        assert "0 created" in result.output
        assert "TASK-001" in result.output

    def test_connect_failure_is_click_error(self, cli_runner, calsync_project, monkeypatch):
        from doxtr_doto.calsync.providers.base import ProviderAuthError
        from doxtr_doto.cli.main import cli

        class _AuthFail(CalendarProvider):
            name = "authfail"

            def connect(self):
                raise ProviderAuthError("bad creds")

            def create_event(self, event):
                pass

            def update_event(self, event, *, etag="", href=""):
                pass

            def delete_event(self, uid, *, etag="", href=""):
                pass

        monkeypatch.setattr("doxtr_doto.calsync.providers.get_provider", lambda name: _AuthFail)
        result = cli_runner.invoke(cli, ["--config", str(calsync_project), "calsync", "push"])
        assert result.exit_code != 0
        assert "bad creds" in result.output

    def test_invalid_event_mode_rejected(self, cli_runner, tmp_path):
        from doxtr_doto.cli.main import cli

        (tmp_path / ".doto").mkdir()
        (tmp_path / ".doto.toml").write_text(
            '[doto]\njson_file = ".doto/tasks.json"\n'
            '[calendar]\nprovider = "caldav"\nevent_mode = "appointment"\n'
        )
        (tmp_path / ".doto" / "tasks.json").write_text(
            '{"version": 3, "updated": "x", "tasks": {}, "series": {}}'
        )
        result = cli_runner.invoke(cli, ["--config", str(tmp_path), "calsync", "push"])
        assert result.exit_code != 0
        assert "event_mode" in result.output


class _PullProvider(CalendarProvider):
    """Fake provider that also serves remote events for pull/two-way tests."""

    name = "fake"
    remote_events: list = []
    instances: list = []

    def __init__(self, config):
        super().__init__(config)
        self.created: list[str] = []
        self.updated: list[str] = []
        self.deleted: list[str] = []
        _PullProvider.instances.append(self)

    def connect(self):
        pass

    def create_event(self, event):
        self.created.append(event.task_id)
        return PushResult(uid=event.uid, etag="e1", remote_id="r-" + (event.task_id or ""))

    def update_event(self, event, *, etag="", href=""):
        self.updated.append(event.task_id)
        return PushResult(uid=event.uid, etag="e2", remote_id="r-" + (event.task_id or ""))

    def delete_event(self, uid, *, etag="", href=""):
        self.deleted.append(uid)

    def list_events(self):
        return list(_PullProvider.remote_events)


@pytest.fixture
def two_way_project(tmp_path):
    """A project configured for two-way calendar sync with one due task."""
    doto_dir = tmp_path / ".doto"
    doto_dir.mkdir()
    (tmp_path / ".doto.toml").write_text(
        """
[doto]
json_file = ".doto/tasks.json"
id_prefix = "TEST"

[calendar]
enabled = true
provider = "caldav"
calendar = "work"
event_mode = "event"
direction = "two-way"
username = "me@example.com"
password = "pw"
url = "https://dav.example.com/"
"""
    )
    (doto_dir / "tasks.json").write_text(
        json.dumps(
            {
                "version": 3,
                "updated": "2026-07-26T10:00:00",
                "tasks": {
                    "TASK-001": {
                        "title": "Local task",
                        "status": "open",
                        "due": "2026-08-15T09:00",
                        "archived": False,
                    }
                },
                "series": {},
            }
        )
    )
    return tmp_path


@pytest.fixture
def pull_provider(monkeypatch):
    from doxtr_doto.calsync.model import EventKind, RemoteEvent

    _PullProvider.instances = []
    _PullProvider.remote_events = [
        RemoteEvent(
            uid="user-ev@example.com",
            remote_id="rid-1",
            summary="User created",
            start=__import__("datetime").datetime(2026, 9, 1, 10, 0),
            kind=EventKind.EVENT,
        )
    ]
    monkeypatch.setattr("doxtr_doto.calsync.providers.get_provider", lambda name: _PullProvider)
    return _PullProvider


class TestPull:
    def test_pull_dry_run_imports_nothing(self, cli_runner, two_way_project, pull_provider):
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(
            cli, ["--config", str(two_way_project), "calsync", "pull", "--dry-run"]
        )
        assert result.exit_code == 0, result.output
        assert "1 import" in result.output
        # No state written on dry-run.
        tasks = json.loads((two_way_project / ".doto" / "tasks.json").read_text())["tasks"]
        assert len(tasks) == 1  # only the pre-existing local task

    def test_pull_imports_remote_event(self, cli_runner, two_way_project, pull_provider):
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, ["--config", str(two_way_project), "calsync", "pull"])
        assert result.exit_code == 0, result.output
        assert "1 imported" in result.output
        tasks = json.loads((two_way_project / ".doto" / "tasks.json").read_text())["tasks"]
        # The imported task was added alongside the pre-existing one.
        titles = {t["title"] for t in tasks.values()}
        assert "User created" in titles


class TestTwoWaySync:
    def test_sync_runs_pull_then_push(self, cli_runner, two_way_project, pull_provider):
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, ["--config", str(two_way_project), "calsync", "sync"])
        assert result.exit_code == 0, result.output
        assert "imported" in result.output
        assert "Pushed" in result.output

    def test_sync_dry_run_previews_both(self, cli_runner, two_way_project, pull_provider):
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(
            cli, ["--config", str(two_way_project), "calsync", "sync", "--dry-run"]
        )
        assert result.exit_code == 0, result.output
        assert "Pull (calendar -> doto)" in result.output
        assert "Push (doto -> calendar)" in result.output


@pytest.fixture
def conflict_project(tmp_path):
    """A project whose single task carries an unresolved sync-conflict stash."""
    doto_dir = tmp_path / ".doto"
    doto_dir.mkdir()
    (tmp_path / ".doto.toml").write_text(
        """
[doto]
json_file = ".doto/tasks.json"
id_prefix = "TEST"

[calendar]
enabled = true
provider = "caldav"
calendar = "work"
event_mode = "event"
username = "me@example.com"
password = "pw"
url = "https://dav.example.com/"
"""
    )
    (doto_dir / "tasks.json").write_text(
        json.dumps(
            {
                "version": 3,
                "updated": "2026-07-26T10:00:00",
                "tasks": {
                    "TEST-001": {
                        "title": "Local title",
                        "status": "open",
                        "due": "2026-08-15T09:00",
                        "archived": False,
                        "body": "<<<<<<< local\nLOCAL\n=======\nREMOTE\n>>>>>>> remote",
                        "sync_conflict": True,
                        "_sync": {
                            "conflict": {
                                "detected": "2026-07-26T10:00:00",
                                "fields": [
                                    {
                                        "field": "body",
                                        "base": "l1\nBASE\nl3",
                                        "local": "l1\nLOCAL\nl3",
                                        "remote": "l1\nREMOTE\nl3",
                                        "both": "<<<<<<< local\nLOCAL\n"
                                        "=======\nREMOTE\n>>>>>>> remote",
                                    }
                                ],
                            }
                        },
                    },
                },
                "series": {},
            }
        )
    )
    return tmp_path


class TestConflictsAndResolve:
    def test_conflicts_lists_flagged_task(self, cli_runner, conflict_project):
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, ["--config", str(conflict_project), "calsync", "conflicts"])
        assert result.exit_code == 0, result.output
        assert "TEST-001" in result.output
        assert "body" in result.output

    def test_conflicts_none(self, cli_runner, calsync_project):
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(cli, ["--config", str(calsync_project), "calsync", "conflicts"])
        assert result.exit_code == 0, result.output
        assert "No unresolved" in result.output

    def test_resolve_remote_clears_flag(self, cli_runner, conflict_project):
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(
            cli,
            ["--config", str(conflict_project), "calsync", "resolve", "TEST-001", "--remote"],
        )
        assert result.exit_code == 0, result.output
        tasks = json.loads((conflict_project / ".doto" / "tasks.json").read_text())["tasks"]
        t = tasks["TEST-001"]
        assert t["body"] == "l1\nREMOTE\nl3"
        assert t["sync_conflict"] is False
        assert t["_sync"]["conflict"] is None

    def test_resolve_both_keeps_markers(self, cli_runner, conflict_project):
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(
            cli,
            ["--config", str(conflict_project), "calsync", "resolve", "TEST-001", "--both"],
        )
        assert result.exit_code == 0, result.output
        tasks = json.loads((conflict_project / ".doto" / "tasks.json").read_text())["tasks"]
        assert "<<<<<<<" in tasks["TEST-001"]["body"]

    def test_resolve_requires_a_choice(self, cli_runner, conflict_project):
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(
            cli, ["--config", str(conflict_project), "calsync", "resolve", "TEST-001"]
        )
        assert result.exit_code != 0
        assert "Choose one of" in result.output

    def test_resolve_no_conflict_errors(self, cli_runner, calsync_project):
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(
            cli,
            ["--config", str(calsync_project), "calsync", "resolve", "TASK-001", "--local"],
        )
        assert result.exit_code != 0
        assert "no unresolved" in result.output.lower()


@pytest.fixture
def legacy_conflict_project(tmp_path):
    """A task flagged with markers in the body but no structured stash.

    Mirrors a task merged before the ``_sync.conflict`` stash existed, so the
    resolver must reconstruct the conflict from the git-style markers.
    """
    doto_dir = tmp_path / ".doto"
    doto_dir.mkdir()
    (tmp_path / ".doto.toml").write_text(
        """
[doto]
json_file = ".doto/tasks.json"
id_prefix = "TEST"

[calendar]
enabled = true
provider = "caldav"
calendar = "work"
event_mode = "event"
username = "me@example.com"
password = "pw"
url = "https://dav.example.com/"
"""
    )
    (doto_dir / "tasks.json").write_text(
        json.dumps(
            {
                "version": 3,
                "updated": "2026-07-26T10:00:00",
                "tasks": {
                    "TEST-001": {
                        "title": "Legacy conflict",
                        "status": "open",
                        "due": "2026-08-15T09:00",
                        "archived": False,
                        "sync_conflict": True,
                        # No _sync.conflict stash -- only markers in the body.
                        "_sync": {"rst_file": None, "snapshot": None},
                        "body": (
                            "shared\n\n"
                            "<<<<<<< local (doto)\n"
                            "LOCAL note\n"
                            "=======\n"
                            "REMOTE note\n"
                            ">>>>>>> remote (calendar)"
                        ),
                    },
                },
                "series": {},
            }
        )
    )
    return tmp_path


class TestLegacyMarkerConflict:
    def test_conflicts_finds_legacy_marker_task(self, cli_runner, legacy_conflict_project):
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(
            cli, ["--config", str(legacy_conflict_project), "calsync", "conflicts"]
        )
        assert result.exit_code == 0, result.output
        assert "TEST-001" in result.output

    def test_resolve_legacy_marker_task_local(self, cli_runner, legacy_conflict_project):
        from doxtr_doto.cli.main import cli

        result = cli_runner.invoke(
            cli,
            ["--config", str(legacy_conflict_project), "calsync", "resolve", "TEST-001", "--local"],
        )
        assert result.exit_code == 0, result.output
        tasks = json.loads((legacy_conflict_project / ".doto" / "tasks.json").read_text())["tasks"]
        t = tasks["TEST-001"]
        assert "LOCAL note" in t["body"]
        assert "<<<<<<<" not in t["body"]
        assert t["sync_conflict"] is False
        assert t["_sync"]["conflict"] is None
