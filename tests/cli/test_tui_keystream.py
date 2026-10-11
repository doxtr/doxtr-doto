"""Tests for the prefix "key-stream" keymap + context-sensitive hint bar.

Covers the new pure actions (``set_status`` / ``cycle_status_prev`` /
``start_work``), the status sub-key generation, the two-key dispatch state
machine, the ``_bulk_apply`` integration for the state stream and the flat
``w`` key, and the :class:`KeyHintBar` rendering. Mirrors the fixtures and
Pilot style of ``tests/cli/test_tui.py``.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from doxtr_doto.cli.config import load_config
from doxtr_doto.cli.display import DisplayScope
from doxtr_doto.cli.global_state import GlobalStateStore
from doxtr_doto.cli.json_store import JsonTaskStore
from doxtr_doto.cli.main import DotoContext
from doxtr_doto.cli.output import get_formatter
from doxtr_doto.cli.tui import TEXTUAL_AVAILABLE, actions

pytestmark = pytest.mark.skipif(not TEXTUAL_AVAILABLE, reason="textual not installed")


# ---------------------------------------------------------------------------
# Fixtures (mirrors tests/cli/test_tui.py)
# ---------------------------------------------------------------------------
@pytest.fixture
def store_file(tmp_path):
    """A JSON store with two open tasks."""
    store_path = tmp_path / "repoA" / ".doto" / "tasks.json"
    store_path.parent.mkdir(parents=True)
    data_dict = {
        "version": 5,
        "updated": "2024-01-01T00:00:00",
        "tasks": {
            "T-001": {
                "title": "First task",
                "status": "open",
                "priority": "high",
                "tags": ["alpha"],
                "worklogs": [],
            },
            "T-002": {
                "title": "Second task",
                "status": "open",
                "priority": "low",
                "tags": [],
                "worklogs": [],
            },
        },
        "series": {},
    }
    store_path.write_text(json.dumps(data_dict))
    return store_path


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Isolate the global config in a temp dir (see tests/cli/test_tui.py)."""
    from pathlib import Path

    cfg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    monkeypatch.setenv("DOTO_CONFIG", str(tmp_path / "global" / "config.json"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    return cfg


@pytest.fixture
def ctx(store_file, env):
    """A DotoContext wired to the temp store and isolated global state."""
    config = load_config(json_path=store_file)
    return DotoContext(
        config=config,
        store=JsonTaskStore(config.get_json_path()),
        formatter=get_formatter(config),
        global_store=GlobalStateStore(),
    )


def _load(store_file):
    return json.loads(store_file.read_text())


def _run(coro):
    """Run an async pilot coroutine on a fresh event loop (see test_tui.py)."""
    return asyncio.run(coro)


def _app(ctx):
    """Build a kickstart-suppressed, LOCAL-scope app (mirrors TestApp._app)."""
    from doxtr_doto.cli.tui import nudge
    from doxtr_doto.cli.tui.app import DotoApp

    nudge.mark_prompted(ctx, nudge.today_iso())
    app = DotoApp(ctx)
    app.scope = DisplayScope.LOCAL
    return app


# ---------------------------------------------------------------------------
# Pure action-layer tests
# ---------------------------------------------------------------------------
class TestSetStatus:
    """Tests for the explicit ``set_status`` action."""

    def test_sets_explicit_status_and_returns_it(self, ctx, store_file):
        assert actions.set_status(ctx, "T-001", "blocked") == "blocked"
        assert _load(store_file)["tasks"]["T-001"]["status"] == "blocked"

    def test_bad_ref_returns_none(self, ctx):
        assert actions.set_status(ctx, "T-999", "blocked") is None

    def test_does_not_touch_worklogs(self, ctx, store_file):
        # Open a worklog, then set the status; the worklog must survive.
        assert actions.toggle_timer(ctx, "T-001") == "started"
        before = _load(store_file)["tasks"]["T-001"]["worklogs"]
        assert len(before) == 1 and before[0]["stopped_at"] is None
        assert actions.set_status(ctx, "T-001", "blocked") == "blocked"
        task = _load(store_file)["tasks"]["T-001"]
        assert task["status"] == "blocked"
        assert task["worklogs"] == before


class TestCycleStatusPrev:
    """Tests for the reverse status cycle ``cycle_status_prev``."""

    def test_previous_in_cycle_and_wraps(self, ctx, store_file):
        # Default cycle: open -> in-progress -> blocked -> done -> open.
        # Previous of "open" wraps to "done".
        assert actions.cycle_status_prev(ctx, "T-001") == "done"
        assert _load(store_file)["tasks"]["T-001"]["status"] == "done"
        assert actions.cycle_status_prev(ctx, "T-001") == "blocked"
        assert actions.cycle_status_prev(ctx, "T-001") == "in-progress"
        assert actions.cycle_status_prev(ctx, "T-001") == "open"

    def test_unknown_current_resets_to_first(self, ctx, store_file):
        actions.update_task(ctx, "T-001", {"status": "weird"})
        assert actions.cycle_status_prev(ctx, "T-001") == "open"

    def test_missing_status_resets_to_first(self, ctx, store_file):
        # A task with no ``status`` key (current is None) must resolve to the
        # FIRST status, not the last - regression guard for the index-1 path.
        data = _load(store_file)
        del data["tasks"]["T-001"]["status"]
        store_file.write_text(json.dumps(data))
        assert actions.cycle_status_prev(ctx, "T-001") == "open"
        assert _load(store_file)["tasks"]["T-001"]["status"] == "open"

    def test_bad_ref_returns_none(self, ctx):
        assert actions.cycle_status_prev(ctx, "T-999") is None


class TestStartWork:
    """Tests for the combined ``start_work`` action (flat ``w``)."""

    def test_not_in_progress_no_session_sets_in_progress_and_starts(self, ctx, store_file):
        assert actions.start_work(ctx, "T-001") == "started"
        task = _load(store_file)["tasks"]["T-001"]
        assert task["status"] == "in-progress"
        assert len(task["worklogs"]) == 1 and task["worklogs"][0]["stopped_at"] is None

    def test_open_session_stops_and_leaves_status_unchanged(self, ctx, store_file):
        # First press starts (status -> in-progress).
        assert actions.start_work(ctx, "T-001") == "started"
        # Second press stops the timer; status stays in-progress (NOT done).
        assert actions.start_work(ctx, "T-001") == "stopped"
        task = _load(store_file)["tasks"]["T-001"]
        assert task["status"] == "in-progress"
        assert task["worklogs"][0]["stopped_at"] is not None

    def test_config_without_in_progress_is_timer_only(self, ctx, store_file):
        # A status cycle without "in-progress" degrades to timer-only: the
        # timer starts but no status write happens.
        ctx.config.statuses = ["open", "done"]
        assert actions.start_work(ctx, "T-001") == "started"
        task = _load(store_file)["tasks"]["T-001"]
        assert task["status"] == "open"  # unchanged
        assert len(task["worklogs"]) == 1 and task["worklogs"][0]["stopped_at"] is None

    def test_bad_ref_returns_not_found(self, ctx):
        assert actions.start_work(ctx, "T-999") == "not_found"


# ---------------------------------------------------------------------------
# Status sub-key generation
# ---------------------------------------------------------------------------
class TestStatusKeyGeneration:
    """Tests for ``DotoApp._status_key_entries`` (status sub-key generation)."""

    def test_default_statuses_yield_oibd(self, ctx):
        app = _app(ctx)
        entries = app._status_key_entries()
        mapped = {e.key: (e.action, e.label) for e in entries}
        assert mapped["o"] == ("set_status_open", "Open")
        assert mapped["i"] == ("set_status_in_progress", "In Progress")
        assert mapped["b"] == ("set_status_blocked", "Blocked")
        assert mapped["d"] == ("set_status_done", "Done")

    def test_first_letter_collision_falls_back(self, ctx):
        # Two statuses starting with the same letter: the later one takes its
        # first unused letter from the remaining letters of its name.
        ctx.config.statuses = ["backlog", "blocked"]
        app = _app(ctx)
        entries = app._status_key_entries()
        keys = [e.key for e in entries]
        # "backlog" claims "b"; "blocked" cannot reuse it, so it takes the next
        # unused letter from its own name: "l".
        assert keys[0] == "b"
        assert keys[1] == "l"
        assert keys[1] != keys[0]
        # The generated action names normalize the status name.
        actions_names = [e.action for e in entries]
        assert actions_names == ["set_status_backlog", "set_status_blocked"]

    def test_normalized_action_name_and_label_for_hyphenated(self, ctx):
        ctx.config.statuses = ["in-progress"]
        app = _app(ctx)
        (entry,) = app._status_key_entries()
        assert entry.action == "set_status_in_progress"
        assert entry.label == "In Progress"


# ---------------------------------------------------------------------------
# Hint bar rendering
# ---------------------------------------------------------------------------
class TestHintBar:
    """Tests for the pure KeyHintBar.format_* classmethods."""

    def test_format_idle_includes_prefixes_and_help_quit(self):
        from doxtr_doto.cli.tui.app import KEYMAP
        from doxtr_doto.cli.tui.widgets import KeyHintBar

        rendered = KeyHintBar.format_idle(KEYMAP)
        for cell in ("s", "State", "t", "Time", "c", "Config", "S", "Stats"):
            assert cell in rendered
        assert "Help" in rendered
        assert "Quit" in rendered
        # One line only.
        assert "\n" not in rendered

    def test_format_domain_includes_entries_and_affordances(self, ctx):
        from doxtr_doto.cli.tui.app import KEYMAP
        from doxtr_doto.cli.tui.widgets import KeyHintBar

        app = _app(ctx)
        spec = KEYMAP["s"]
        entries = spec.entries_fn(app)
        rendered = KeyHintBar.format_domain("s", spec, entries)
        assert "s ›" in rendered
        for label in ("Open", "Blocked", "Done", "Next", "Prev"):
            assert label in rendered
        assert "Cancel" in rendered
        assert "Esc" in rendered
        assert "Help" in rendered
        assert "\n" not in rendered


# ---------------------------------------------------------------------------
# Dispatch state machine (Pilot-driven)
# ---------------------------------------------------------------------------
class TestDispatch:
    """Pilot-driven tests of the two-key stream dispatcher."""

    def test_prefix_pending_set_and_cleared(self, ctx):
        app = _app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                assert app._pending is None
                await pilot.press("s")  # arm the state prefix
                await pilot.pause()
                assert app._pending == "s"
                await pilot.press("escape")  # cancel
                await pilot.pause()
                assert app._pending is None

        _run(body())

    def test_good_second_key_runs_action(self, ctx, store_file):
        app = _app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("s", "b")  # state -> blocked on T-001
                await pilot.pause()
                assert app._pending is None
                assert _load(store_file)["tasks"]["T-001"]["status"] == "blocked"

        _run(body())

    def test_prev_second_key_cycles_backwards(self, ctx, store_file):
        app = _app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("s", "p")  # prev of open -> done
                await pilot.pause()
                assert _load(store_file)["tasks"]["T-001"]["status"] == "done"

        _run(body())

    def test_next_second_key_cycles_forwards(self, ctx, store_file):
        app = _app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("s", "n")  # next of open -> in-progress
                await pilot.pause()
                assert _load(store_file)["tasks"]["T-001"]["status"] == "in-progress"

        _run(body())

    def test_domain_help_opens(self, ctx):
        from doxtr_doto.cli.tui.app import DomainHelpScreen

        app = _app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("s", "question_mark")  # state help
                await pilot.pause()
                assert isinstance(app.screen, DomainHelpScreen)
                await pilot.press("escape")
                await pilot.pause()
                assert not isinstance(app.screen, DomainHelpScreen)

        _run(body())

    def test_bare_question_mark_opens_top_level_help(self, ctx):
        from doxtr_doto.cli.tui.app import DomainHelpScreen, HelpScreen

        app = _app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("question_mark")  # bare ? -> top-level router
                await pilot.pause()
                assert isinstance(app.screen, HelpScreen)
                assert not isinstance(app.screen, DomainHelpScreen)
                await pilot.press("escape")
                await pilot.pause()
                assert not isinstance(app.screen, HelpScreen)

        _run(body())

    def test_prefix_survives_bare_modifier_before_shifted_second_key(self, ctx):
        """A bare modifier keypress must not clear a pending stream prefix.

        Regression: typing a shifted second key such as ``?`` requires pressing
        ``Shift`` first; on Kitty-protocol terminals that bare ``Shift`` is
        delivered as its own key event (``left_shift``). The dispatcher must
        ignore it so the ``t`` prefix survives and the following
        ``question_mark`` opens the *time-domain* help, not the top-level help.
        """
        from doxtr_doto.cli.tui.app import DomainHelpScreen, HelpScreen

        app = _app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("t")  # arm the time prefix
                await pilot.pause()
                assert app._pending == "t"
                await pilot.press("left_shift")  # bare modifier - must be ignored
                await pilot.pause()
                assert app._pending == "t"  # prefix survived
                await pilot.press("question_mark")  # resolves to time-domain help
                await pilot.pause()
                assert isinstance(app.screen, DomainHelpScreen)
                # The time-domain help, not the bare top-level router.
                assert type(app.screen) is not HelpScreen
                assert app.screen._prefix == "t"
                assert app._pending is None

        _run(body())

    def test_escape_cancels(self, ctx, store_file):
        app = _app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("s", "escape")
                await pilot.pause()
                assert app._pending is None
                # No status change happened.
                assert _load(store_file)["tasks"]["T-001"]["status"] == "open"

        _run(body())

    def test_unknown_second_key_noops(self, ctx, store_file):
        app = _app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("s", "z")  # "z" is not a state sub-key
                await pilot.pause()
                assert app._pending is None
                assert _load(store_file)["tasks"]["T-001"]["status"] == "open"

        _run(body())

    def test_flat_keys_still_work_when_no_prefix_pending(self, ctx):
        from doxtr_doto.cli.tui.app import FilterScreen
        from doxtr_doto.cli.tui.widgets import TaskList

        app = _app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                table = app.query_one(TaskList)
                assert table.selected_id() == "T-001"
                await pilot.press("j")  # flat nav still works
                assert table.selected_id() == "T-002"
                await pilot.press("k")
                assert table.selected_id() == "T-001"
                await pilot.press("slash")  # flat "/" opens the filter modal
                await pilot.pause()
                assert isinstance(app.screen, FilterScreen)

        _run(body())

    def test_flat_w_starts_work(self, ctx, store_file):
        app = _app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("w")  # start working on T-001
                await pilot.pause()
                task = _load(store_file)["tasks"]["T-001"]
                assert task["status"] == "in-progress"
                assert len(task["worklogs"]) == 1
                assert task["worklogs"][0]["stopped_at"] is None

        _run(body())


# ---------------------------------------------------------------------------
# _bulk_apply integration (multi-select) for s* and w
# ---------------------------------------------------------------------------
class TestBulkApplyIntegration:
    """The state stream and flat ``w`` honor the multi-selection."""

    def test_state_stream_honors_multi_select(self, ctx, store_file):
        app = _app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                # Select both tasks.
                await pilot.press("space")  # select T-001
                await pilot.press("j")
                await pilot.press("space")  # select T-002
                await pilot.pause()
                await pilot.press("s", "b")  # blocked on both
                await pilot.pause()
                tasks = _load(store_file)["tasks"]
                assert tasks["T-001"]["status"] == "blocked"
                assert tasks["T-002"]["status"] == "blocked"

        _run(body())

    def test_flat_w_honors_multi_select(self, ctx, store_file):
        app = _app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("space")  # select T-001
                await pilot.press("j")
                await pilot.press("space")  # select T-002
                await pilot.pause()
                await pilot.press("w")  # start work on both
                await pilot.pause()
                tasks = _load(store_file)["tasks"]
                assert tasks["T-001"]["status"] == "in-progress"
                assert tasks["T-002"]["status"] == "in-progress"
                assert len(tasks["T-001"]["worklogs"]) == 1
                assert len(tasks["T-002"]["worklogs"]) == 1

        _run(body())

    def test_time_toggle_stream_honors_multi_select(self, ctx, store_file):
        """``t t`` starts the focus timer on every selected task (spec §8.1)."""
        app = _app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("space")  # select T-001
                await pilot.press("j")
                await pilot.press("space")  # select T-002
                await pilot.pause()
                await pilot.press("t", "t")  # toggle focus timer on both
                await pilot.pause()
                tasks = _load(store_file)["tasks"]
                assert len(tasks["T-001"]["worklogs"]) == 1
                assert len(tasks["T-002"]["worklogs"]) == 1

        _run(body())


def test_stream_second_key_beats_colliding_flat_binding(ctx, store_file):
    """A stream second key wins over a flat binding with the same key.

    Regression: Textual checks ``BINDINGS`` before :meth:`DotoApp.on_key`, so a
    stream second key that is also a flat binding - ``S w`` (stats) vs flat
    ``w`` (start/stop work), ``t e`` vs flat ``e`` (edit), ``s d`` vs flat
    ``d`` (done) - was stolen by the flat binding, turning ``S w`` into
    "start work" and never opening the stats pop-up. :meth:`DotoApp.on_key`
    calls ``event.prevent_default()`` while a prefix is armed so the colliding
    flat binding does not also fire and the second key resolves through the
    stream dispatcher.
    """
    from doxtr_doto.cli.tui.app import TaskSessionsScreen, WorkStatsScreen
    from doxtr_doto.enums import TuiLayout

    # The bug only manifests when the focused widget's binding chain contains
    # the colliding flat binding. In the default TABLE layout the TaskList is
    # focused, so flat ``w``/``e``/``d`` are all active - exactly the case that
    # (pre-fix) stole the stream second key. Press the prefix and the second
    # key as *separate* events (a pump cycle between) to match real typing;
    # that is the path that routes the second key through the binding system.

    # S w must open work stats and must NOT start work. The second key ``w``
    # collides with the flat ``w`` (start_work); pre-fix the flat binding fired
    # and set the task in-progress + opened a worklog. The correct outcome is
    # the work-stats pop-up with no focus session and the status left ``open``.
    app = _app(ctx)

    async def body_sw():
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.layout_view is TuiLayout.TABLE
            await pilot.press("S")
            await pilot.pause()
            assert app._pending == "S"
            await pilot.press("w")
            await pilot.pause()
            assert isinstance(app.screen, WorkStatsScreen)
            task = _load(store_file)["tasks"]["T-001"]
            assert not task.get("worklogs")
            assert task["status"] == "open"
            assert app._pending is None

    _run(body_sw())

    # t e opens the session editor, NOT the flat edit-task modal (flat ``e``).
    app2 = _app(ctx)

    async def body_te():
        async with app2.run_test() as pilot:
            await pilot.pause()
            await pilot.press("t")
            await pilot.pause()
            await pilot.press("e")
            await pilot.pause()
            assert isinstance(app2.screen, TaskSessionsScreen)

    _run(body_te())

    # s d sets status done via the state stream; the second key ``d`` collides
    # with the flat ``d`` (done) binding but is routed by the stream
    # dispatcher (both happen to end at "done", but the routing is the point).
    app3 = _app(ctx)

    async def body_sd():
        async with app3.run_test() as pilot:
            await pilot.pause()
            await pilot.press("s")
            await pilot.pause()
            await pilot.press("d")
            await pilot.pause()
            assert _load(store_file)["tasks"]["T-001"]["status"] == "done"

    _run(body_sd())
