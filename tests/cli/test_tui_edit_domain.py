"""Tests for the ``e`` Edit-domain dispatcher, menu visibility and modals.

Covers:
* :meth:`DotoApp._selected_is_series_member` True/False,
* the dynamic ``e`` domain entries (E/D shown only for a series occurrence),
* the two-key dispatch (``e e`` edit, ``e E`` edit-series, ``e d`` delete-task,
  ``e D`` delete-series) and that a bare ``e`` no longer edits immediately,
* :class:`EditSeriesScreen` pre-population (unchanged series -> no-op) and that
  an invalid form keeps the modal open,
* :class:`ConfirmScreen` confirm / cancel / keep-tasks branches.

Mirrors the Pilot style / fixtures of ``tests/cli/test_tui_keystream.py``.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date

import pytest

from doxtr_doto.cli.config import load_config
from doxtr_doto.cli.display import DisplayScope
from doxtr_doto.cli.global_state import GlobalStateStore
from doxtr_doto.cli.json_store import JsonTaskStore
from doxtr_doto.cli.main import DotoContext
from doxtr_doto.cli.output import get_formatter
from doxtr_doto.cli.tui import TEXTUAL_AVAILABLE

pytestmark = pytest.mark.skipif(not TEXTUAL_AVAILABLE, reason="textual not installed")


@pytest.fixture
def store_file(tmp_path):
    """A JSON store with one standalone task and one weekly series occurrence."""
    store_path = tmp_path / "repoA" / ".doto" / "tasks.json"
    store_path.parent.mkdir(parents=True)
    data_dict = {
        "version": 5,
        "updated": "2024-01-01T00:00:00",
        "tasks": {
            "T-001": {
                "title": "Standalone",
                "status": "open",
                "priority": "high",
                "tags": [],
                "worklogs": [],
                "due": "2026-01-05",
            },
            "S-001": {
                "title": "Weekly W1",
                "status": "open",
                "priority": "low",
                "series_id": "SER-1",
                "tags": [],
                "worklogs": [],
                "due": "2026-01-05",
            },
            "S-002": {
                "title": "Weekly W2",
                "status": "open",
                "priority": "low",
                "series_id": "SER-1",
                "tags": [],
                "worklogs": [],
                "due": "2026-01-12",
            },
        },
        "series": {
            "SER-1": {
                "title_template": "Weekly",
                "pattern": {
                    "type": "weekly",
                    "interval": 1,
                    "weekday": 0,
                    "day_of_month": None,
                    "weekday_position": None,
                    "start_time": None,
                    "duration_minutes": None,
                },
                "start_date": "2026-01-05",
                "end_date": "2026-01-12",
                "task_ids": ["S-001", "S-002"],
                "task_defaults": {},
                "created": "2026-01-01T00:00:00",
            }
        },
    }
    store_path.write_text(json.dumps(data_dict))
    return store_path


@pytest.fixture
def env(tmp_path, monkeypatch):
    from pathlib import Path

    cfg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    monkeypatch.setenv("DOTO_CONFIG", str(tmp_path / "global" / "config.json"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    return cfg


@pytest.fixture
def ctx(store_file, env):
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
    return asyncio.run(coro)


def _app(ctx):
    from doxtr_doto.cli.tui import nudge
    from doxtr_doto.cli.tui.app import DotoApp

    nudge.mark_prompted(ctx, nudge.today_iso())
    app = DotoApp(ctx)
    app.scope = DisplayScope.LOCAL
    return app


def _select(app, task_id):
    """Move the active view's cursor to ``task_id``."""
    app.select_task(task_id)


# ---------------------------------------------------------------------------
# _selected_is_series_member + dynamic domain entries
# ---------------------------------------------------------------------------
class TestSeriesMemberMenu:
    def test_series_member_true_and_entries_include_series(self, ctx):
        from doxtr_doto.cli.tui.app import KEYMAP

        app = _app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                _select(app, "S-001")
                await pilot.pause()
                assert app._selected_is_series_member() is True
                entries = KEYMAP["e"].entries_fn(app)
                actions_present = {e.action for e in entries}
                assert {"edit", "delete_task", "edit_series", "delete_series"} <= actions_present

        _run(body())

    def test_standalone_false_and_entries_exclude_series(self, ctx):
        from doxtr_doto.cli.tui.app import KEYMAP

        app = _app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                _select(app, "T-001")
                await pilot.pause()
                assert app._selected_is_series_member() is False
                entries = KEYMAP["e"].entries_fn(app)
                actions_present = {e.action for e in entries}
                assert "edit" in actions_present
                assert "add_subtask" in actions_present
                assert "delete_task" in actions_present
                assert "edit_series" not in actions_present
                assert "delete_series" not in actions_present

        _run(body())

    def test_no_selection_is_not_series_member(self, tmp_path, env):
        """With an empty store (nothing selectable) the helper returns False."""
        store_path = tmp_path / "empty" / ".doto" / "tasks.json"
        store_path.parent.mkdir(parents=True)
        store_path.write_text(
            json.dumps(
                {
                    "version": 5,
                    "updated": "2024-01-01T00:00:00",
                    "tasks": {},
                    "series": {},
                }
            )
        )
        config = load_config(json_path=store_path)
        empty_ctx = DotoContext(
            config=config,
            store=JsonTaskStore(config.get_json_path()),
            formatter=get_formatter(config),
            global_store=GlobalStateStore(),
        )
        app = _app(empty_ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                assert app._current_selected_id() is None
                assert app._selected_is_series_member() is False

        _run(body())


# ---------------------------------------------------------------------------
# Dispatch: e is a prefix (bare e no longer edits)
# ---------------------------------------------------------------------------
class TestEditDomainDispatch:
    def test_bare_e_arms_prefix_not_edit(self, ctx):
        app = _app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                _select(app, "T-001")
                await pilot.press("e")  # arm the edit prefix (no modal yet)
                await pilot.pause()
                assert app._pending == "e"
                # No edit modal was pushed by the bare prefix.
                from doxtr_doto.cli.tui.app import EditTaskScreen

                assert not isinstance(app.screen, EditTaskScreen)
                await pilot.press("escape")
                await pilot.pause()
                assert app._pending is None

        _run(body())

    def test_e_e_opens_edit_modal(self, ctx):
        from doxtr_doto.cli.tui.app import EditTaskScreen

        app = _app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                _select(app, "T-001")
                await pilot.press("e", "e")
                await pilot.pause()
                await pilot.pause()
                assert isinstance(app.screen, EditTaskScreen)

        _run(body())

    def test_e_shift_e_opens_edit_series_modal(self, ctx):
        from doxtr_doto.cli.tui.app import EditSeriesScreen

        app = _app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                _select(app, "S-001")
                await pilot.press("e", "E")
                await pilot.pause()
                await pilot.pause()
                assert isinstance(app.screen, EditSeriesScreen)

        _run(body())

    def test_e_d_opens_confirm_for_delete_task(self, ctx):
        from doxtr_doto.cli.tui.app import ConfirmScreen

        app = _app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                _select(app, "T-001")
                await pilot.press("e", "d")
                await pilot.pause()
                await pilot.pause()
                assert isinstance(app.screen, ConfirmScreen)

        _run(body())

    def test_e_shift_d_opens_confirm_for_delete_series(self, ctx):
        from doxtr_doto.cli.tui.app import ConfirmScreen

        app = _app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                _select(app, "S-001")
                await pilot.press("e", "D")
                await pilot.pause()
                await pilot.pause()
                assert isinstance(app.screen, ConfirmScreen)
                # Three-way confirm (keep-tasks button present).
                assert app.screen.keep_tasks_label is not None

        _run(body())


# ---------------------------------------------------------------------------
# End-to-end action flows (confirm/submit callbacks mutate the store)
# ---------------------------------------------------------------------------
class TestEditDomainFlows:
    def test_e_d_confirm_deletes_task_and_prunes_series(self, ctx, store_file):
        from doxtr_doto.cli.tui.app import ConfirmScreen

        app = _app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                _select(app, "S-001")
                await pilot.press("e", "d")
                await pilot.pause()
                await pilot.pause()
                assert isinstance(app.screen, ConfirmScreen)
                await pilot.click("#confirm-yes")
                await pilot.pause()
                await pilot.pause()

        _run(body())
        data = _load(store_file)
        assert "S-001" not in data["tasks"]
        assert "S-001" not in data["series"]["SER-1"]["task_ids"]

    def test_e_shift_d_keep_tasks_removes_series_only(self, ctx, store_file):
        from doxtr_doto.cli.tui.app import ConfirmScreen

        app = _app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                _select(app, "S-001")
                await pilot.press("e", "D")
                await pilot.pause()
                await pilot.pause()
                assert isinstance(app.screen, ConfirmScreen)
                await pilot.click("#confirm-keep")
                await pilot.pause()
                await pilot.pause()

        _run(body())
        data = _load(store_file)
        assert "SER-1" not in data["series"]
        # Tasks survive.
        assert "S-001" in data["tasks"]
        assert "S-002" in data["tasks"]

    def test_edit_series_submit_restamps_forward(self, ctx, store_file):
        from doxtr_doto.cli.tui.app import EditSeriesResult, EditSeriesScreen

        app = _app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                _select(app, "S-001")
                await pilot.press("e", "E")
                await pilot.pause()
                await pilot.pause()
                assert isinstance(app.screen, EditSeriesScreen)
                # Dismiss with a result that sets a duration from the anchor.
                app.screen.dismiss(
                    EditSeriesResult(
                        series_id="SER-1",
                        pattern_str="every monday for 2h",
                        title=None,
                        start_time=None,
                        duration_minutes=120,
                    )
                )
                await pilot.pause()
                await pilot.pause()

        _run(body())
        data = _load(store_file)
        # S-001 is the anchor (2026-01-05) and forward, so both re-stamped.
        assert data["tasks"]["S-001"]["estimate"] == 120
        assert data["tasks"]["S-002"]["estimate"] == 120


# ---------------------------------------------------------------------------
# EditSeriesScreen pre-population + validation
# ---------------------------------------------------------------------------
class TestEditSeriesScreen:
    def test_prepopulation_roundtrips_unchanged_to_noop(self, ctx):
        from doxtr_doto.cli.tui.app import EditSeriesScreen
        from doxtr_doto.cli.tui.edit_series_fields import EditSeriesFormValues

        series_data = ctx.store.get_series("SER-1")
        screen = EditSeriesScreen("SER-1", dict(series_data), date(2026, 1, 5), 2, 0)
        fields = screen.initial_fields()
        # The pre-populated base pattern round-trips.
        assert fields["pattern"] == "every monday"
        assert fields["title"] == "Weekly"
        assert fields["time"] == ""
        assert fields["duration"] == ""

        # Feeding the pre-populated values straight back collects a result that
        # keeps the stored pattern/title (blank title => keep) and a base
        # pattern string equal to the stored shape, i.e. a no-op edit.
        screen.form_values = lambda: EditSeriesFormValues(  # type: ignore[method-assign]
            title=fields["title"],
            pattern=fields["pattern"],
            start_time=fields["time"],
            duration=fields["duration"],
        )
        result = screen.collect_result()
        assert result.series_id == "SER-1"
        assert result.pattern_str == "every monday"
        assert result.title == "Weekly"

    def test_invalid_form_keeps_modal_open(self, ctx):
        from doxtr_doto.cli.tui.app import EditSeriesScreen
        from doxtr_doto.cli.tui.edit_series_fields import EditSeriesFormValues

        series_data = ctx.store.get_series("SER-1")
        screen = EditSeriesScreen("SER-1", dict(series_data), date(2026, 1, 5), 2, 0)
        # collect_result raises ValueError on an invalid pattern (no terminal
        # needed): simulate the field read by replacing form_values.
        screen.form_values = lambda: EditSeriesFormValues(  # type: ignore[method-assign]
            title="", pattern="not a pattern"
        )
        with pytest.raises(ValueError):
            screen.collect_result()

    def test_valid_form_collects_result(self, ctx):
        from doxtr_doto.cli.tui.app import EditSeriesScreen
        from doxtr_doto.cli.tui.edit_series_fields import EditSeriesFormValues

        series_data = ctx.store.get_series("SER-1")
        screen = EditSeriesScreen("SER-1", dict(series_data), date(2026, 1, 5), 2, 0)
        screen.form_values = lambda: EditSeriesFormValues(  # type: ignore[method-assign]
            title="", pattern="every monday", start_time="16:00", duration="2h"
        )
        result = screen.collect_result()
        assert result.series_id == "SER-1"
        assert result.pattern_str == "every monday at 16:00 for 2h"
        assert result.title is None


# ---------------------------------------------------------------------------
# ConfirmScreen branches
# ---------------------------------------------------------------------------
class TestConfirmScreen:
    def test_confirm_branch(self, ctx):
        from doxtr_doto.cli.tui.app import ConfirmResult, ConfirmScreen, DotoApp

        app = DotoApp(ctx)
        results = []

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                app.push_screen(ConfirmScreen("Delete?", confirm_label="Delete"), results.append)
                await pilot.pause()
                await pilot.click("#confirm-yes")
                await pilot.pause()

        _run(body())
        assert results == [ConfirmResult.CONFIRM]

    def test_cancel_branch(self, ctx):
        from doxtr_doto.cli.tui.app import ConfirmResult, ConfirmScreen, DotoApp

        app = DotoApp(ctx)
        results = []

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                app.push_screen(ConfirmScreen("Delete?"), results.append)
                await pilot.pause()
                await pilot.press("escape")
                await pilot.pause()

        _run(body())
        assert results == [ConfirmResult.CANCEL]

    def test_keep_tasks_branch(self, ctx):
        from doxtr_doto.cli.tui.app import ConfirmResult, ConfirmScreen, DotoApp

        app = DotoApp(ctx)
        results = []

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                app.push_screen(
                    ConfirmScreen(
                        "Delete series?",
                        confirm_label="Delete series + tasks",
                        keep_tasks_label="Keep tasks, remove series",
                    ),
                    results.append,
                )
                await pilot.pause()
                await pilot.click("#confirm-keep")
                await pilot.pause()

        _run(body())
        assert results == [ConfirmResult.KEEP_TASKS]


# ---------------------------------------------------------------------------
# e a: add sub-task under selected task (all views + cross-repo + collapsed)
# ---------------------------------------------------------------------------
class TestAddSubtask:
    def test_e_a_creates_subtask_with_parent_in_table_view(self, ctx, store_file):
        """Pressing 'e a' on T-001 creates a new task with parent='T-001'."""
        from doxtr_doto.cli.tui.app import AddTaskScreen

        app = _app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                _select(app, "T-001")
                await pilot.pause()
                await pilot.press("e")
                await pilot.press("a")
                await pilot.pause()
                assert isinstance(app.screen, AddTaskScreen)
                assert app.screen.parent_label == "T-001"
                # First field is immediately focused so typing starts right away.
                assert app.screen.focused is not None
                assert app.screen.focused.id == "add-input"
                for ch in "Child of T-001":
                    await pilot.press(ch if ch != " " else "space")
                await pilot.press("enter")
                await pilot.pause()
                return app._current_selected_id()

        selected_after = _run(body())
        tasks = _load(store_file)["tasks"]
        child_id = next(tid for tid, t in tasks.items() if t["title"] == "Child of T-001")
        assert tasks[child_id]["parent"] == "T-001"
        assert selected_after == child_id

    def test_e_a_works_in_calendar_view(self, ctx, store_file):
        """Pressing 'e a' in calendar view creates a sub-task of the highlighted task."""
        from doxtr_doto.cli.tui.app import AddTaskScreen
        from doxtr_doto.enums import TuiLayout

        app = _app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                app.layout_mode = TuiLayout.CALENDAR
                app.apply_layout()
                app.refresh_tasks()
                await pilot.pause()
                assert app.select_task("T-001")
                await pilot.pause()
                await pilot.press("e")
                await pilot.press("a")
                await pilot.pause()
                assert isinstance(app.screen, AddTaskScreen)
                for ch in "Calendar child":
                    await pilot.press(ch if ch != " " else "space")
                await pilot.press("enter")
                await pilot.pause()

        _run(body())
        tasks = _load(store_file)["tasks"]
        child = next(t for t in tasks.values() if t["title"] == "Calendar child")
        assert child["parent"] == "T-001"

    def test_e_a_works_in_kanban_view(self, ctx, store_file):
        """Pressing 'e a' in kanban view creates a sub-task of the highlighted card."""
        from doxtr_doto.cli.tui.app import AddTaskScreen
        from doxtr_doto.enums import TuiLayout

        app = _app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                app.layout_mode = TuiLayout.KANBAN
                app.apply_layout()
                app.refresh_tasks()
                await pilot.pause()
                assert app.select_task("T-001")
                await pilot.pause()
                await pilot.press("e")
                await pilot.press("a")
                await pilot.pause()
                assert isinstance(app.screen, AddTaskScreen)
                for ch in "Kanban child":
                    await pilot.press(ch if ch != " " else "space")
                await pilot.press("enter")
                await pilot.pause()

        _run(body())
        tasks = _load(store_file)["tasks"]
        child = next(t for t in tasks.values() if t["title"] == "Kanban child")
        assert child["parent"] == "T-001"

    def test_e_a_expands_collapsed_parent_on_create(self, ctx, store_file):
        """Adding a sub-task to a collapsed parent expands it so the child shows."""
        from doxtr_doto.cli.tui.app import AddTaskScreen

        app = _app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                _select(app, "T-001")
                app._collapsed_ids.add("T-001")
                await pilot.pause()
                await pilot.press("e")
                await pilot.press("a")
                await pilot.pause()
                assert isinstance(app.screen, AddTaskScreen)
                for ch in "Expanded child":
                    await pilot.press(ch if ch != " " else "space")
                await pilot.press("enter")
                await pilot.pause()
                return "T-001" in app._collapsed_ids, app._current_selected_id()

        still_collapsed, selected = _run(body())
        tasks = _load(store_file)["tasks"]
        child_id = next(tid for tid, t in tasks.items() if t["title"] == "Expanded child")
        assert not still_collapsed
        assert tasks[child_id]["parent"] == "T-001"
        assert selected == child_id

    def test_e_a_escape_cancels_without_creating(self, ctx, store_file):
        """Pressing Escape in the 'e a' modal cancels without modifying the store."""
        from doxtr_doto.cli.tui.app import AddTaskScreen

        before = set(_load(store_file)["tasks"].keys())
        app = _app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                _select(app, "T-001")
                await pilot.press("e")
                await pilot.press("a")
                await pilot.pause()
                assert isinstance(app.screen, AddTaskScreen)
                await pilot.press("escape")
                await pilot.pause()

        _run(body())
        assert set(_load(store_file)["tasks"].keys()) == before

    def test_e_a_noop_when_no_selection(self, tmp_path, env):
        """With an empty store, 'e a' is a no-op and opens no modal."""
        from doxtr_doto.cli.tui.app import AddTaskScreen

        store_path = tmp_path / "empty" / ".doto" / "tasks.json"
        store_path.parent.mkdir(parents=True)
        store_path.write_text(
            json.dumps({"version": 5, "updated": "2024-01-01T00:00:00", "tasks": {}, "series": {}})
        )
        config = load_config(json_path=store_path)
        empty_ctx = DotoContext(
            config=config,
            store=JsonTaskStore(config.get_json_path()),
            formatter=get_formatter(config),
            global_store=GlobalStateStore(),
        )
        app = _app(empty_ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.press("e")
                await pilot.press("a")
                await pilot.pause()
                assert not isinstance(app.screen, AddTaskScreen)

        _run(body())

    def test_e_a_in_global_scope_creates_subtask_in_foreign_repo(self, tmp_path, env, store_file):
        """In GLOBAL scope, 'e a' on a foreign-repo task creates the child in THAT repo."""
        from doxtr_doto.cli.display import DisplayScope
        from doxtr_doto.cli.repo_registry import RepoRegistry
        from doxtr_doto.cli.tui.app import AddTaskScreen

        other_store = tmp_path / "repoB" / ".doto" / "tasks.json"
        other_store.parent.mkdir(parents=True)
        other_store.write_text(
            json.dumps(
                {
                    "version": 5,
                    "updated": "2024-01-01T00:00:00",
                    "tasks": {
                        "B-001": {
                            "title": "Foreign parent",
                            "status": "open",
                            "priority": "medium",
                            "tags": [],
                            "worklogs": [],
                        }
                    },
                    "series": {},
                }
            )
        )
        config = load_config(json_path=store_file)
        multi_ctx = DotoContext(
            config=config,
            store=JsonTaskStore(config.get_json_path()),
            formatter=get_formatter(config),
            global_store=GlobalStateStore(),
        )
        RepoRegistry(multi_ctx.global_store).rescan(tmp_path)
        app = _app(multi_ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                app.scope = DisplayScope.GLOBAL
                app.refresh_tasks()
                await pilot.pause()
                assert app.select_task("B-001")
                await pilot.pause()
                await pilot.press("e")
                await pilot.press("a")
                await pilot.pause()
                assert isinstance(app.screen, AddTaskScreen)
                # Repo selector is hidden because a child always lives in its parent's repo.
                assert list(app.screen.query("#add-repo")) == []
                for ch in "Foreign child":
                    await pilot.press(ch if ch != " " else "space")
                await pilot.press("enter")
                await pilot.pause()

        _run(body())
        # Created in repoB with parent="B-001"; repoA is untouched.
        foreign_tasks = _load(other_store)["tasks"]
        child_id = next(tid for tid, t in foreign_tasks.items() if t["title"] == "Foreign child")
        assert foreign_tasks[child_id]["parent"] == "B-001"
        local_tasks = _load(store_file)["tasks"]
        assert not any(t["title"] == "Foreign child" for t in local_tasks.values())

    def test_add_task_action_parent_validation(self, tmp_path, env, store_file):
        """actions.add_task validates parent existence and same-repo invariant."""
        from doxtr_doto.cli.repo_registry import RepoRegistry
        from doxtr_doto.cli.tui import actions
        from doxtr_doto.exceptions import DotoValidationError

        other_store = tmp_path / "repoB" / ".doto" / "tasks.json"
        other_store.parent.mkdir(parents=True)
        other_store.write_text(
            json.dumps(
                {
                    "version": 5,
                    "updated": "2024-01-01T00:00:00",
                    "tasks": {"B-001": {"title": "Other", "status": "open", "priority": "low"}},
                    "series": {},
                }
            )
        )
        config = load_config(json_path=store_file)
        multi_ctx = DotoContext(
            config=config,
            store=JsonTaskStore(config.get_json_path()),
            formatter=get_formatter(config),
            global_store=GlobalStateStore(),
        )
        RepoRegistry(multi_ctx.global_store).rescan(tmp_path)

        # Valid same-repo parent succeeds.
        new_id = actions.add_task(multi_ctx, "Good child", parent="T-001")
        assert _load(store_file)["tasks"][new_id]["parent"] == "T-001"

        # Missing parent fails.
        with pytest.raises(DotoValidationError, match="not found"):
            actions.add_task(multi_ctx, "Orphan", parent="NOPE-999")

        # Cross-repo parent (when targeting current repo) fails.
        with pytest.raises(DotoValidationError, match="Cross-repo parent"):
            actions.add_task(multi_ctx, "Cross child", parent="repoB#B-001")

    def test_e_a_focuses_first_field_in_multi_field_layout(self, ctx, store_file):
        """With multi-field tui_add_fields, 'e a' focuses the first field immediately."""
        from doxtr_doto.cli.tui.app import AddTaskScreen

        ctx.config.tui_add_fields = "default"
        app = _app(ctx)

        async def body():
            async with app.run_test() as pilot:
                await pilot.pause()
                _select(app, "T-001")
                await pilot.pause()
                await pilot.press("e")
                await pilot.press("a")
                await pilot.pause()
                assert isinstance(app.screen, AddTaskScreen)
                focused_id = app.screen.focused.id if app.screen.focused is not None else None
                for ch in "Multi-field child":
                    await pilot.press(ch if ch != " " else "space")
                await pilot.press("enter")
                await pilot.pause()
                return focused_id

        focused_id = _run(body())
        assert focused_id == "add-title"
        tasks = _load(store_file)["tasks"]
        child = next(t for t in tasks.values() if t["title"] == "Multi-field child")
        assert child["parent"] == "T-001"
