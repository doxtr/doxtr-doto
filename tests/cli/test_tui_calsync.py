"""Tests for the TUI ``C`` (Calendar Sync) domain.

Two layers are covered without any network or a running Textual app:

* :mod:`doxtr_doto.cli.tui.calsync_tui` orchestration -- status/push/pull/sync/
  login/logout against a registered in-memory fake provider, asserting the
  :class:`CalSyncOutcome` summary and the side effects on the task store and
  sync state.
* The ``C`` entry in :data:`doxtr_doto.cli.tui.app.KEYMAP` and its sub-key ->
  action wiring (Pilot-free: the registry rows and dispatch routing are pure).

The provider is swapped in via the public ``register_provider`` registry (the
same extension seam downstreams use), so no core internals are monkeypatched.
"""

from __future__ import annotations

import json

import pytest

from doxtr_doto.calsync.model import EventKind, RemoteEvent
from doxtr_doto.calsync.providers import register_provider
from doxtr_doto.calsync.providers.base import CalendarProvider, ProviderAuthError, PushResult
from doxtr_doto.cli.config import load_config
from doxtr_doto.cli.json_store import JsonTaskStore
from doxtr_doto.cli.main import DotoContext
from doxtr_doto.cli.output import get_formatter
from doxtr_doto.cli.tui import TEXTUAL_AVAILABLE, calsync_tui


# ---------------------------------------------------------------------------
# Fake provider (in-memory; registered under the configured provider name)
# ---------------------------------------------------------------------------
class _FakeProvider(CalendarProvider):
    """Records pushes and serves a canned remote-event list (no network)."""

    name = "faketui"

    #: Remote events returned by list_events() -- set per test before connect.
    seed_remote: list[RemoteEvent] = []
    #: Whether login()/connect() should fail with an auth error.
    fail_auth: bool = False
    #: Recorded operations across all instances in a test.
    ops: list[tuple[str, str]] = []

    def connect(self) -> None:
        if type(self).fail_auth:
            raise ProviderAuthError("not logged in")
        type(self).ops.append(("connect", ""))

    def login(self) -> None:
        if type(self).fail_auth:
            raise ProviderAuthError("login refused")
        type(self).ops.append(("login", ""))

    def create_event(self, event):
        type(self).ops.append(("create", event.task_id or ""))
        return PushResult(uid=event.uid, etag="e1", remote_id="r-" + (event.task_id or ""))

    def update_event(self, event, *, etag="", href=""):
        type(self).ops.append(("update", event.task_id or ""))
        return PushResult(uid=event.uid, etag="e2", remote_id="r-" + (event.task_id or ""))

    def delete_event(self, uid, *, etag="", href=""):
        type(self).ops.append(("delete", uid))

    def list_events(self):
        type(self).ops.append(("list", ""))
        return list(type(self).seed_remote)


@pytest.fixture
def fake_provider():
    """Register the fake under 'google' for the duration of a test, then restore."""
    from doxtr_doto.calsync.providers import _load_google

    _FakeProvider.seed_remote = []
    _FakeProvider.fail_auth = False
    _FakeProvider.ops = []
    register_provider("google", lambda: _FakeProvider)
    yield _FakeProvider
    # Restore the real built-in loader.
    register_provider("google", _load_google)


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    """A DotoContext with a [calendar] google config and two due tasks."""
    from pathlib import Path

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("DOTO_CONFIG", str(tmp_path / "global" / "config.json"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")

    repo = tmp_path / "repo"
    (repo / ".doto").mkdir(parents=True)
    (repo / ".doto" / "tasks.json").write_text(
        json.dumps(
            {
                "version": 5,
                "updated": "2024-01-01T00:00:00",
                "tasks": {
                    "DOTO-001": {"title": "A", "status": "open", "due": "2026-01-01"},
                    "DOTO-002": {"title": "B", "status": "open", "due": "2026-01-02"},
                },
                "series": {},
            }
        )
    )
    config = load_config(json_path=repo / ".doto" / "tasks.json")
    # Calendar config is normally read from the [calendar] TOML table during
    # project discovery (cwd-based); set it directly so the test does not
    # depend on cwd and the TOML discovery path.
    config.calendar.enabled = True
    config.calendar.provider = "google"
    config.calendar.calendar = "cal-1"
    config.calendar.event_mode = "event"
    config.calendar.direction = "push"
    return DotoContext(
        config=config,
        store=JsonTaskStore(config.get_json_path()),
        formatter=get_formatter(config),
    )


def _remote(uid: str, summary: str) -> RemoteEvent:
    """Build a user-created (non-doto) all-day remote event."""
    from datetime import datetime

    return RemoteEvent(
        uid=uid,
        remote_id=uid.split("@")[0],
        etag='"re1"',
        summary=summary,
        description="",
        start=datetime(2026, 3, 1, 0, 0),
        end=datetime(2026, 3, 2, 0, 0),
        all_day=True,
        due=None,
        kind=EventKind.EVENT,
        status="confirmed",
    )


# ---------------------------------------------------------------------------
# Orchestration: status / push / pull / sync
# ---------------------------------------------------------------------------
class TestStatus:
    def test_status_reports_plan_without_network(self, ctx, fake_provider):
        out = calsync_tui.status(ctx)
        assert out.ok
        assert "2 create" in out.message
        # No provider connect for status.
        assert fake_provider.ops == []

    def test_status_errors_when_unconfigured(self, ctx, fake_provider):
        ctx.config.calendar.provider = ""
        out = calsync_tui.status(ctx)
        assert not out.ok
        assert "not configured" in out.message


class TestPush:
    def test_push_creates_events(self, ctx, fake_provider):
        out = calsync_tui.push(ctx)
        assert out.ok
        assert "2 created" in out.message
        creates = [op for op in fake_provider.ops if op[0] == "create"]
        assert {c[1] for c in creates} == {"DOTO-001", "DOTO-002"}

    def test_push_noop_when_nothing_actionable(self, ctx, fake_provider):
        calsync_tui.push(ctx)  # first push creates
        fake_provider.ops = []
        out = calsync_tui.push(ctx)  # second push: unchanged
        assert out.ok
        assert "nothing to push" in out.message.lower()
        # No connect/create on a no-op second push.
        assert fake_provider.ops == []

    def test_push_connect_failure_is_reported(self, ctx, fake_provider):
        fake_provider.fail_auth = True
        out = calsync_tui.push(ctx)
        assert not out.ok
        assert "not logged in" in out.message


class TestPull:
    def test_pull_imports_user_event(self, ctx, fake_provider):
        fake_provider.seed_remote = [_remote("user-1@google.com", "Imported")]
        out = calsync_tui.pull(ctx)
        assert out.ok
        assert "1 imported" in out.message
        # A new local task exists for the imported event.
        ctx.store.load()
        titles = [t.get("title") for t in ctx.store.get_all_tasks().values()]
        assert "Imported" in titles

    def test_pull_noop_when_no_remote_events(self, ctx, fake_provider):
        out = calsync_tui.pull(ctx)
        assert out.ok
        assert "nothing to pull" in out.message.lower()


class TestSync:
    def test_sync_push_direction_pushes(self, ctx, fake_provider):
        ctx.config.calendar.direction = "push"
        out = calsync_tui.sync(ctx)
        assert out.ok
        assert "created" in out.message

    def test_sync_pull_direction_pulls(self, ctx, fake_provider):
        ctx.config.calendar.direction = "pull"
        fake_provider.seed_remote = [_remote("user-2@google.com", "Pulled")]
        out = calsync_tui.sync(ctx)
        assert out.ok
        assert "imported" in out.message

    def test_sync_two_way_pulls_then_pushes(self, ctx, fake_provider):
        ctx.config.calendar.direction = "two-way"
        fake_provider.seed_remote = [_remote("user-3@google.com", "Both")]
        out = calsync_tui.sync(ctx)
        assert out.ok
        assert "Pulled:" in out.message and "Pushed:" in out.message

    def test_sync_pull_connect_failure_is_reported(self, ctx, fake_provider):
        ctx.config.calendar.direction = "pull"
        fake_provider.fail_auth = True
        out = calsync_tui.sync(ctx)
        assert not out.ok
        assert "not logged in" in out.message


class TestErrorPaths:
    """Connect failures and per-item provider errors surface in the summary."""

    def test_pull_connect_failure_is_reported(self, ctx, fake_provider):
        fake_provider.fail_auth = True
        out = calsync_tui.pull(ctx)
        assert not out.ok
        assert "not logged in" in out.message

    def test_push_per_item_error_is_appended(self, ctx, fake_provider, monkeypatch):
        # A provider whose create_event raises produces a per-item error that
        # _format_errors appends to the (still ok=True) summary.
        from doxtr_doto.calsync.providers.base import ProviderError

        def _boom(self, event):
            raise ProviderError("kaboom")

        # monkeypatch restores the original method automatically on teardown,
        # so the shared _FakeProvider class is not left mutated for other tests.
        monkeypatch.setattr(fake_provider, "create_event", _boom)
        out = calsync_tui.push(ctx)
        assert out.ok  # the run itself completed; per-item errors don't flip ok
        assert "Errors -" in out.message
        assert "kaboom" in out.message


class TestLoginLogout:
    def test_login_success(self, ctx, fake_provider):
        out = calsync_tui.login(ctx)
        assert out.ok
        assert "Logged in" in out.message
        assert ("login", "") in fake_provider.ops

    def test_login_failure(self, ctx, fake_provider):
        fake_provider.fail_auth = True
        out = calsync_tui.login(ctx)
        assert not out.ok
        assert "login refused" in out.message

    def test_logout_without_token(self, ctx, fake_provider):
        out = calsync_tui.logout(ctx)
        assert out.ok
        assert "No cached token" in out.message

    def test_logout_normalizes_apple_alias(self, ctx, fake_provider, monkeypatch):
        """'apple' must clear the 'caldav' token (alias normalization)."""
        from doxtr_doto.calsync import auth

        ctx.config.calendar.provider = "apple"
        called: dict = {}

        def _spy(name):
            called["name"] = name
            return True

        monkeypatch.setattr(auth, "clear_token", _spy)
        out = calsync_tui.logout(ctx)
        assert out.ok
        # Cleared the canonical token name, not the alias.
        assert called["name"] == "caldav"
        # The user-facing message still names the configured provider.
        assert "apple" in out.message


class TestSyncDisplayed:
    """C s syncs every *displayed* calendar-enabled repo (scope + repo_filter)."""

    def _make_repo(self, root, name, *, enabled, task_id="R-001"):
        """Create an on-disk repo with its own .doto.toml + one due task."""
        from doxtr_doto.cli.repo_registry import DiscoveredRepo

        repo = root / name
        (repo / ".doto").mkdir(parents=True)
        (repo / ".doto" / "tasks.json").write_text(
            json.dumps(
                {
                    "version": 5,
                    "updated": "2024-01-01T00:00:00",
                    "tasks": {task_id: {"title": name, "status": "open", "due": "2026-01-01"}},
                    "series": {},
                }
            )
        )
        toml = f'[doto]\nid_prefix = "{name.upper()}"\n'
        if enabled:
            toml += (
                '\n[calendar]\nenabled = true\nprovider = "google"\n'
                'calendar = "cal-1"\nevent_mode = "event"\ndirection = "push"\n'
            )
        (repo / ".doto.toml").write_text(toml)
        return DiscoveredRepo(name=name, path=str(repo))

    def test_displayed_sync_repos_filters_to_calendar_enabled(
        self, ctx, fake_provider, tmp_path, monkeypatch
    ):
        from doxtr_doto.cli.display import DisplayScope
        from doxtr_doto.cli.tui import data

        synced = self._make_repo(tmp_path, "alpha", enabled=True)
        unsynced = self._make_repo(tmp_path, "beta", enabled=False)
        monkeypatch.setattr(data, "list_repos", lambda _ctx: [synced, unsynced])

        repos = calsync_tui.displayed_sync_repos(ctx, scope=DisplayScope.GLOBAL, repo_filter=())
        assert [r.name for r in repos] == ["alpha"]

    def test_repo_filter_narrows_the_set(self, ctx, fake_provider, tmp_path, monkeypatch):
        from doxtr_doto.cli.display import DisplayScope
        from doxtr_doto.cli.tui import data

        a = self._make_repo(tmp_path, "alpha", enabled=True)
        b = self._make_repo(tmp_path, "gamma", enabled=True)
        monkeypatch.setattr(data, "list_repos", lambda _ctx: [a, b])

        # Only 'gamma' is in the repo filter -> only it is returned.
        repos = calsync_tui.displayed_sync_repos(
            ctx, scope=DisplayScope.GLOBAL, repo_filter=("gamma",)
        )
        assert [r.name for r in repos] == ["gamma"]

    def test_sync_displayed_syncs_each_enabled_repo(
        self, ctx, fake_provider, tmp_path, monkeypatch
    ):
        from doxtr_doto.cli.display import DisplayScope
        from doxtr_doto.cli.tui import data

        a = self._make_repo(tmp_path, "alpha", enabled=True)
        b = self._make_repo(tmp_path, "gamma", enabled=True)
        monkeypatch.setattr(data, "list_repos", lambda _ctx: [a, b])

        out = calsync_tui.sync_displayed(ctx, scope=DisplayScope.GLOBAL, repo_filter=())
        assert out.ok
        # Aggregated message names both repos, and each pushed its one task.
        assert "alpha:" in out.message and "gamma:" in out.message
        creates = [op for op in fake_provider.ops if op[0] == "create"]
        assert len(creates) == 2

    def test_sync_displayed_no_enabled_repo_is_clear_not_silent(
        self, ctx, fake_provider, tmp_path, monkeypatch
    ):
        from doxtr_doto.cli.display import DisplayScope
        from doxtr_doto.cli.tui import data

        unsynced = self._make_repo(tmp_path, "beta", enabled=False)
        monkeypatch.setattr(data, "list_repos", lambda _ctx: [unsynced])

        out = calsync_tui.sync_displayed(ctx, scope=DisplayScope.GLOBAL, repo_filter=())
        assert not out.ok
        assert "no displayed repository" in out.message.lower()

    def test_local_scope_syncs_only_current_repo(self, ctx, fake_provider, tmp_path, monkeypatch):
        from doxtr_doto.cli.display import DisplayScope
        from doxtr_doto.cli.tui import data

        # In LOCAL scope the launch-dir repo (the ctx fixture, calendar-enabled)
        # is used; list_repos must not be consulted.
        current = self._make_repo(tmp_path, "launch", enabled=True)
        monkeypatch.setattr(data, "current_repo", lambda _ctx: current)
        monkeypatch.setattr(
            data, "list_repos", lambda _ctx: (_ for _ in ()).throw(AssertionError("used"))
        )
        repos = calsync_tui.displayed_sync_repos(ctx, scope=DisplayScope.LOCAL, repo_filter=())
        assert [r.name for r in repos] == ["launch"]


# ---------------------------------------------------------------------------
# KEYMAP registration + sub-key -> action wiring
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not TEXTUAL_AVAILABLE, reason="textual not installed")
class TestKeymapRegistration:
    def test_capital_c_domain_registered(self):
        from doxtr_doto.cli.tui.app import KEYMAP

        assert "C" in KEYMAP
        assert KEYMAP["C"].label == "Calendar Sync"

    def test_subkeys_map_to_calsync_actions(self):
        from doxtr_doto.cli.tui.app import KEYMAP, DotoApp

        spec = KEYMAP["C"]
        # entries_fn only reads nothing app-specific for this domain, so a bare
        # instance is unnecessary; pass a dummy since the lambda ignores it.
        entries = spec.entries_fn(object())
        by_key = {e.key: e.action for e in entries}
        assert by_key == {
            "s": "calsync_sync",
            "p": "calsync_push",
            "l": "calsync_pull",
            "t": "calsync_status",
            "r": "calsync_resolve",
            "i": "calsync_login",
            "o": "calsync_logout",
        }
        # Every action resolves to a real method on the app.
        for action in by_key.values():
            assert callable(getattr(DotoApp, f"action_{action}", None))


@pytest.mark.skipif(not TEXTUAL_AVAILABLE, reason="textual not installed")
class TestDispatchIntegration:
    """Pilot-driven: pressing C then a sub-key runs the worker end to end."""

    def _app(self, ctx):
        from doxtr_doto.cli.display import DisplayScope
        from doxtr_doto.cli.tui import nudge
        from doxtr_doto.cli.tui.app import DotoApp

        nudge.mark_prompted(ctx, nudge.today_iso())
        app = DotoApp(ctx)
        app.scope = DisplayScope.LOCAL
        return app

    def test_capital_c_arms_calendar_prefix(self, ctx, fake_provider):
        import asyncio

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                assert app._pending is None
                await pilot.press("C")
                await pilot.pause()
                assert app._pending == "C"
                await pilot.press("escape")
                await pilot.pause()
                assert app._pending is None

        asyncio.run(body())

    def test_c_p_pushes_via_worker(self, ctx, fake_provider):
        import asyncio

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("C", "p")  # Calendar Sync -> Push
                await pilot.pause()
                # The push runs in a thread worker; wait for it to finish.
                await app.workers.wait_for_complete()
                await pilot.pause()
                assert app._pending is None

        asyncio.run(body())
        creates = [op for op in fake_provider.ops if op[0] == "create"]
        assert {c[1] for c in creates} == {"DOTO-001", "DOTO-002"}

    def test_c_t_status_runs_inline_without_connect(self, ctx, fake_provider):
        import asyncio

        app = self._app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("C", "t")  # Calendar Sync -> Status
                await pilot.pause()
                assert app._pending is None

        asyncio.run(body())
        # Status is network-free: no provider connect/list.
        assert fake_provider.ops == []

    def test_c_l_pulls_and_refreshes_view(self, ctx, fake_provider):
        """C l pulls via the worker and refreshes the task list on success."""
        import asyncio

        fake_provider.seed_remote = [_remote("user-refresh@google.com", "Imported via C l")]
        app = self._app(ctx)
        refreshed = {"count": 0}
        orig_refresh = app.refresh_tasks

        def _spy():
            refreshed["count"] += 1
            orig_refresh()

        app.refresh_tasks = _spy  # type: ignore[method-assign]

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("C", "l")  # Calendar Sync -> Pull
                await pilot.pause()
                await app.workers.wait_for_complete()
                await pilot.pause()
                assert app._pending is None

        asyncio.run(body())
        # The pull imported the remote event as a local task...
        ctx.store.load()
        titles = [t.get("title") for t in ctx.store.get_all_tasks().values()]
        assert "Imported via C l" in titles
        # ...and _reload_after_calsync refreshed the view at least once.
        assert refreshed["count"] >= 1

    def test_c_s_syncs_displayed_repo_via_worker(self, ctx, fake_provider):
        """C s runs the multi-repo sync worker; the LOCAL-scope repo is pushed."""
        import asyncio

        app = self._app(ctx)  # LOCAL scope; the ctx fixture repo is calsync-enabled

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("C", "s")  # Calendar Sync -> Sync
                await pilot.pause()
                await app.workers.wait_for_complete()
                await pilot.pause()
                assert app._pending is None

        asyncio.run(body())
        # The displayed (current) repo's due tasks were pushed through the worker.
        creates = [op for op in fake_provider.ops if op[0] == "create"]
        assert {c[1] for c in creates} == {"DOTO-001", "DOTO-002"}


@pytest.mark.skipif(not TEXTUAL_AVAILABLE, reason="textual not installed")
class TestKeymapOverride:
    """A child theme can override the keymap without editing core."""

    def test_subclass_can_remove_calendar_domain(self):
        from doxtr_doto.cli.tui.app import KEYMAP, DotoApp

        class ChildTheme(DotoApp):
            keymap = {k: v for k, v in DotoApp.keymap.items() if k != "C"}

        # The override is instance/class-local; core's KEYMAP is untouched.
        assert "C" in KEYMAP
        assert "C" in DotoApp.keymap
        assert "C" not in ChildTheme.keymap

    def test_help_screen_renders_the_passed_keymap(self):
        from doxtr_doto.cli.tui.app import KEYMAP, HelpScreen

        filtered = {k: v for k, v in KEYMAP.items() if k != "C"}
        assert "Calendar Sync" in HelpScreen(KEYMAP)._body()
        assert "Calendar Sync" not in HelpScreen(filtered)._body()
